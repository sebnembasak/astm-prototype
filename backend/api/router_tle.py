from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from service.tle_service import tle_service

router = APIRouter(prefix="/tle", tags=["TLE Data"])


class SatelliteSchema(BaseModel):
    id: int
    sat_name: str
    epoch: Optional[str]
    source: Optional[str]


class TLEUpdateResponse(BaseModel):
    message: str
    count: int


@router.post("/refresh", response_model=TLEUpdateResponse)
async def refresh_tles():
    """Celestraktan TLE verilerini çeker ve veritabanını günceller."""
    try:
        count = tle_service.update_tles_from_source()
        return {"message": "TLE verileri başarıyla yüklendi", "count": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list", response_model=List[SatelliteSchema])
async def list_satellites(limit: int = 100):
    """Sistemdeki uyduları listeler."""
    return tle_service.get_all_satellites(limit)


@router.get("/count")
async def get_satellite_count():
    """Toplam uydu sayısını döner"""
    count = tle_service.get_total_count()
    return {"count": count}


@router.get("/search", response_model=List[SatelliteSchema])
async def search_satellites(q: str = Query(..., min_length=2)):
    """Uydu ismine göre arama yapar."""
    results = tle_service.search_satellites(q)
    return results


# --- Bu ID endpointi en sonda olmalı
# --- Eğer üstte olursa "/count" isteğini de ID sanıp yakalar ve hata verir
@router.get("/{sat_id}")
async def get_satellite_details(sat_id: int):
    """IDye göre raw TLE verisini döner."""
    sat = tle_service.get_satellite_by_id(sat_id)
    if not sat:
        raise HTTPException(status_code=404, detail="Uydu bulunamadı")
    return sat
