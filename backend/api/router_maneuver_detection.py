from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from service.maneuver_detection_service import maneuver_detection_service

router = APIRouter(prefix="/maneuver-detection", tags=["Maneuver Detection"])


class DetectionRunResponse(BaseModel):
    status: str
    new_events: int


@router.post("/run", response_model=DetectionRunResponse)
async def run_detection():
    """
    tle_history'deki ardışık epoch çiftlerini tarayarak manevra tespiti yapar.
    Yeni tespit edilen olaylar maneuver_events tablosuna eklenir.
    """
    new_count = maneuver_detection_service.detect_all_satellites()
    return {"status": "completed", "new_events": new_count}


@router.get("/events", response_model=List[Dict[str, Any]])
async def get_events(limit: int = 50, sat_id: Optional[int] = None):
    """Tespit edilen manevra olaylarını (epoch_after DESC) döner."""
    return maneuver_detection_service.get_maneuver_events(sat_id, limit)
