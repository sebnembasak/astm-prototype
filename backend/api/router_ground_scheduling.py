from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.models.db import get_conn
from ground_scheduling_config import (
    CANDIDATE_GROUND_STATIONS,
    DEFAULT_MIN_ELEVATION_DEG,
    DEFAULT_SCENARIO_DURATION_HOURS,
    DEFAULT_STATION_ALT_KM,
    SCENARIO_SATELLITE_COUNTS,
    SCENARIO_STATION_COUNTS,
)
from service.capacity_planning_service import capacity_planning_service

router = APIRouter(prefix="/ground-scheduling", tags=["Ground Station Scheduling"])


class GroundStationIn(BaseModel):
    name: str
    lat: float
    lon: float
    alt_km: float = DEFAULT_STATION_ALT_KM
    min_elevation_deg: float = DEFAULT_MIN_ELEVATION_DEG


class GroundStationOut(GroundStationIn):
    id: int
    created_at: str


class ScenarioResultOut(BaseModel):
    num_satellites: int
    actual_satellites_used: int
    num_stations: int
    total_passes: int
    missed_passes: int
    capacity_loss_pct: float
    additional_stations_for_target: Optional[int]
    additional_stations_path: Optional[List[str]]


@router.get("/stations", response_model=List[GroundStationOut])
async def list_ground_stations():
    """Kullanıcı tarafından kaydedilmiş gerçek yer istasyonlarını döner."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, name, lat, lon, alt_km, min_elevation_deg, created_at FROM ground_stations ORDER BY id")
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


@router.post("/stations", response_model=GroundStationOut)
async def create_ground_station(station: GroundStationIn):
    """Yeni bir yer istasyonu kaydeder (Dashboard'daki Leaflet harita üzerinde gösterim için)."""
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    cur.execute("""
        INSERT INTO ground_stations (name, lat, lon, alt_km, min_elevation_deg, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (station.name, station.lat, station.lon, station.alt_km, station.min_elevation_deg, now))
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return {**station.dict(), "id": new_id, "created_at": now}


@router.get("/candidate-stations")
async def get_candidate_stations():
    """
    Kapasite planlama senaryolarında 'ek istasyon' aranırken kullanılan
    aday istasyon havuzunu döner (dashboard haritasında referans gösterim için).
    """
    return CANDIDATE_GROUND_STATIONS


@router.get("/scenario", response_model=ScenarioResultOut)
async def run_single_scenario(
        num_satellites: int = Query(..., gt=0),
        num_stations: int = Query(..., gt=0),
        duration_hours: int = Query(DEFAULT_SCENARIO_DURATION_HOURS, gt=0),
):
    """Tek bir (uydu sayısı, istasyon sayısı) kombinasyonu için kapasite kaybı senaryosu çalıştırır."""
    try:
        result = capacity_planning_service.run_scenario(num_satellites, num_stations, duration_hours)
        return result.__dict__
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scenarios", response_model=List[ScenarioResultOut])
async def run_scenario_grid(
        satellite_counts: Optional[str] = Query(None, description="Virgülle ayrılmış uydu sayıları, örn: 3,10,30,80"),
        station_counts: Optional[str] = Query(None, description="Virgülle ayrılmış istasyon sayıları, örn: 1,2,3"),
        duration_hours: int = Query(DEFAULT_SCENARIO_DURATION_HOURS, gt=0),
):
    """
    Büyüme hedefine paralel uydu sayıları (varsayılan 3/10/30/80)
    x istasyon sayıları (varsayılan 1/2/3) ızgarasını tarayıp, her kombinasyon
    için kapasite kaybı senaryosu üretir. Dashboard'daki senaryo karşılaştırma
    grafiğinin veri kaynağıdır.
    """
    sat_counts = [int(x) for x in satellite_counts.split(",")] if satellite_counts else SCENARIO_SATELLITE_COUNTS
    stat_counts = [int(x) for x in station_counts.split(",")] if station_counts else SCENARIO_STATION_COUNTS

    try:
        results = capacity_planning_service.run_all_scenarios(sat_counts, stat_counts, duration_hours)
        return [r.__dict__ for r in results]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
