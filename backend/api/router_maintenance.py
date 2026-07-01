from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from service.maintenance_service import maintenance_service, DEFAULT_SATELLITE_LIMIT

router = APIRouter(prefix="/maintenance", tags=["Maintenance Impact Analysis"])


# ─── Request ────────────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    station_name: str = Field(..., examples=["Ankara"], description="Station name (DB or candidate config)")
    duration_hours: float = Field(..., gt=0, le=72, examples=[4.0])
    priority_satellite_norad_ids: Optional[List[int]] = Field(
        default=None,
        examples=[[25994, 27540]],
        description="NORAD IDs of satellites that must be included in the analysis.",
    )
    satellite_limit: int = Field(
        default=DEFAULT_SATELLITE_LIMIT,
        ge=5,
        le=80,
        description="Total satellites to analyze (higher = slower but more complete).",
    )


# ─── Response ───────────────────────────────────────────────────────────────

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
    best_windows: List[WindowRecommendationOut]
    worst_windows: List[WindowRecommendationOut]
    computation_time_s: float


# ─── Endpoint ───────────────────────────────────────────────────────────────

@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_maintenance_impact(req: AnalyzeRequest):
    """
    For a proposed maintenance window on a ground station, computes which
    satellite passes would be lost across the next 7 days and returns the
    three lowest-impact time slots (best windows to schedule) and the three
    highest-impact slots (worst windows to avoid).

    Cost score = Σ (pass_duration_s × satellite_weight) for all lost passes.
    Phase 1 uses uniform weight = 1.0; Phase 2 will derive weights from B*
    orbital decay term (satellites closer to re-entry get higher weight).
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

    def _serialize_window(w) -> WindowRecommendationOut:
        return WindowRecommendationOut(
            rank=w.rank,
            start_utc=w.start_utc,
            end_utc=w.end_utc,
            cost_score=w.cost_score,
            passes_lost=w.passes_lost,
            contact_minutes_lost=w.contact_minutes_lost,
            passes_lost_detail=[
                PassLostDetailOut(
                    sat_norad_id=p.sat_norad_id,
                    sat_name=p.sat_name,
                    aos=p.aos,
                    los=p.los,
                    duration_s=p.duration_s,
                    max_elevation_deg=p.max_elevation_deg,
                    satellite_weight=p.satellite_weight,
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
        best_windows=[_serialize_window(w) for w in result.best_windows],
        worst_windows=[_serialize_window(w) for w in result.worst_windows],
        computation_time_s=result.computation_time_s,
    )
