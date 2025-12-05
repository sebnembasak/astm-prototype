from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timedelta, timezone
from service.propagation_service import propagation_service

router = APIRouter(prefix="/orbit", tags=["Orbit Propagation & Viz"])


class PositionPoint(BaseModel):
    time: str
    lat: float
    lon: float
    alt_km: float
    position_km: List[float]
    velocity_km_s: List[float]


@router.get("/propagate/{sat_id}", response_model=List[PositionPoint])
async def propagate_satellite_path(
        sat_id: int,
        duration_minutes: int = 90,
        step_seconds: int = 60
):
    """
    Belirtilen uydu için şimdiki zamandan başlayarak Lat/Lon/Alt yörüngesini hesaplar.
    Frontend tarafında harita çizimi için kullanılır.
    """
    now = datetime.now(timezone.utc)
    end = now + timedelta(minutes=duration_minutes)

    try:
        path = propagation_service.propagate_satellite(
            sat_id, now, end, step_seconds
        )
        return path
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))