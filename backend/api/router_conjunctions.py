from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List
from datetime import datetime
from service.conjunction_service import conjunction_service

router = APIRouter(prefix="/conjunctions", tags=["Conjunction Analysis"])


class ConjunctionAlertSchema(BaseModel):
    id: int
    sat1_id: int
    sat1_name: str
    sat2_id: int
    sat2_name: str
    tca: str
    miss_distance_km: float
    rel_velocity_km_s: float
    score: float
    created_at: str
    event_type: str


class ScreeningResponse(BaseModel):
    status: str
    processed_pairs: int
    alerts_saved: int


@router.post("/run-screening", response_model=ScreeningResponse)
async def run_screening():
    """
    Manuel olarak çarpışma taramasını tetikler.
    O anki zamandan itibaren 2 saatlik pencereyi tarar.
    """
    try:
        result = conjunction_service.run_conjunction_screening()
        return {
            "status": "completed",
            "processed_pairs": result["processed_pairs"],
            "alerts_saved": result["alerts_saved"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/alerts", response_model=List[ConjunctionAlertSchema])
async def get_latest_alerts(limit: int = 20, type: str = "COLLISION"):
    """
    Veritabanındaki uyarıları getirir.
    type param: 'COLLISION' veya 'DOCKING'
    """
    return conjunction_service.get_alerts(limit, event_type=type)
