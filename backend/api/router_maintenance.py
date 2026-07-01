from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from service.maintenance_service import maintenance_service, DEFAULT_SATELLITE_LIMIT

router = APIRouter(prefix="/maintenance", tags=["Maintenance Impact Analysis"])


# ─── Request ────────────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    station_name: str = Field(..., examples=["Ankara"])
    duration_hours: float = Field(..., gt=0, le=72, examples=[4.0])
    priority_satellite_norad_ids: Optional[List[int]] = Field(
        default=None,
        examples=[[25994, 27540]],
        description="NORAD IDs that must be included regardless of orbit profile.",
    )
    satellite_limit: int = Field(
        default=DEFAULT_SATELLITE_LIMIT, ge=5, le=80,
        description="Total satellites to analyze (higher = slower but more complete).",
    )


# ─── Response ───────────────────────────────────────────────────────────────

class SatelliteWeightDetailOut(BaseModel):
    norad_id: int
    sat_name: str
    altitude_km: float
    bstar: float
    estimated_lifetime_days: Optional[float]  # null = no measurable drag (stable)
    weight: float
    bstar_history_points: int = 0
    bstar_source: str = "snapshot"


class PassLostDetailOut(BaseModel):
    sat_norad_id: int
    sat_name: str
    aos: datetime
    los: datetime
    duration_s: float
    max_elevation_deg: float
    satellite_weight: float


class WindowRecommendationOut(BaseModel):
    rank: int
    start_utc: datetime
    end_utc: datetime
    cost_score: float
    passes_lost: int
    contact_minutes_lost: float
    passes_lost_detail: List[PassLostDetailOut]


class AnalyzeResponse(BaseModel):
    station_name: str
    station_lat: float
    station_lon: float
    duration_hours: float
    analysis_start_utc: datetime
    analysis_end_utc: datetime
    total_satellites_analyzed: int
    total_passes_in_period: int
    total_contact_minutes: float
    candidate_windows_evaluated: int
    satellite_weight_details: List[SatelliteWeightDetailOut]
    best_windows: List[WindowRecommendationOut]
    worst_windows: List[WindowRecommendationOut]
    computation_time_s: float


# ─── Endpoint ───────────────────────────────────────────────────────────────

@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_maintenance_impact(req: AnalyzeRequest):
    """
    For a proposed maintenance window on a ground station, computes which
    satellite passes would be lost across the next 7 days and returns the
    three lowest-impact time slots (best windows) and highest-impact slots
    (worst windows to avoid).

    Phase 2 weights: cost = Σ (pass_duration_s × satellite_weight), where
    weight is derived from the B* drag term and orbital altitude:
      - estimated lifetime < 180 days  → weight 3.0
      - lifetime 180–365 days          → weight 2.0
      - lifetime > 365 days            → weight 1.0
      - B* = 0 or unavailable          → weight 1.0 (safe default)
    """
    try:
        result = maintenance_service.analyze(
            station_name=req.station_name,
            duration_hours=req.duration_hours,
            priority_norad_ids=req.priority_satellite_norad_ids,
            satellite_limit=req.satellite_limit,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    def _window(w) -> WindowRecommendationOut:
        return WindowRecommendationOut(
            rank=w.rank, start_utc=w.start_utc, end_utc=w.end_utc,
            cost_score=w.cost_score, passes_lost=w.passes_lost,
            contact_minutes_lost=w.contact_minutes_lost,
            passes_lost_detail=[
                PassLostDetailOut(
                    sat_norad_id=p.sat_norad_id, sat_name=p.sat_name,
                    aos=p.aos, los=p.los, duration_s=p.duration_s,
                    max_elevation_deg=p.max_elevation_deg, satellite_weight=p.satellite_weight,
                )
                for p in w.passes_lost_detail
            ],
        )

    return AnalyzeResponse(
        station_name=result.station_name,
        station_lat=result.station_lat,
        station_lon=result.station_lon,
        duration_hours=result.duration_hours,
        analysis_start_utc=result.analysis_start_utc,
        analysis_end_utc=result.analysis_end_utc,
        total_satellites_analyzed=result.total_satellites_analyzed,
        total_passes_in_period=result.total_passes_in_period,
        total_contact_minutes=result.total_contact_minutes,
        candidate_windows_evaluated=result.candidate_windows_evaluated,
        satellite_weight_details=[
            SatelliteWeightDetailOut(
                norad_id=d.norad_id, sat_name=d.sat_name,
                altitude_km=d.altitude_km, bstar=d.bstar,
                estimated_lifetime_days=d.estimated_lifetime_days,
                weight=d.weight,
                bstar_history_points=d.bstar_history_points,
                bstar_source=d.bstar_source,
            )
            for d in result.satellite_weight_details
        ],
        best_windows=[_window(w) for w in result.best_windows],
        worst_windows=[_window(w) for w in result.worst_windows],
        computation_time_s=result.computation_time_s,
    )
