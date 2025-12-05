from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime
from service.maneuver_service import maneuver_service

router = APIRouter(prefix="/maneuver", tags=["Maneuver Optimization"])


class ManeuverRequest(BaseModel):
    sat_id_primary: int
    sat_id_secondary: int
    tca: datetime
    target_miss_km: float = 1.0


class ManeuverResponse(BaseModel):
    success: bool
    burn_time: str
    tca_original: str
    predicted_miss_km: float
    dv_vector_m_s: list
    dv_magnitude_m_s: float
    message: str


@router.post("/calculate", response_model=ManeuverResponse)
async def calculate_maneuver(req: ManeuverRequest):
    """
    Çarpışma uyarısı için optimal kaçınma manevrası (deltav) hesaplar.
    """
    try:
        result = maneuver_service.calculate_avoidance_maneuver(
            sat_id_primary=req.sat_id_primary,
            sat_id_secondary=req.sat_id_secondary,
            tca=req.tca,
            target_miss_km=req.target_miss_km
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Optimization failed: {str(e)}")
