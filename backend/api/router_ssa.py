from fastapi import APIRouter, HTTPException
from service.ssa_service import ssa_service
from backend.models.db import get_conn  # Veritabanı bağlantısı için

router = APIRouter(prefix="/ssa", tags=["SSA Intelligence"])


@router.post("/train")
async def train_ssa():
    msg = ssa_service.train_model()
    return {"message": msg}


@router.post("/run-analysis")
async def run_analysis():
    count = ssa_service.analyze_all_satellites()
    return {"status": "Analysis completed", "processed_satellites": count}


@router.get("/results")
async def get_ssa_results(limit: int = 50):
    conn = get_conn()
    cur = conn.cursor()
    query = """
        SELECT s.sat_name, si.predicted_category, si.confidence, 
               si.cluster_id, si.is_anomaly, si.predicted_country, si.decay_risk
        FROM satellite_intelligence si
        JOIN raw_tles s ON si.sat_id = s.id
        ORDER BY si.predicted_at DESC LIMIT ?
    """
    cur.execute(query, (limit,))
    rows = cur.fetchall()
    conn.close()

    results = []
    for row in rows:
        d = dict(row)
        d['regime_label'] = ssa_service.REGIME_MAP.get(d['cluster_id'], "Bilinmeyen Yörünge")
        results.append(d)
    return results


@router.get("/prediction/{sat_id}")
async def get_ssa_prediction(sat_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT predicted_category as category, confidence FROM satellite_intelligence WHERE sat_id = ? ORDER BY predicted_at DESC LIMIT 1",
        (sat_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return dict(row)


@router.get("/heatmap")
async def get_heatmap():
    return ssa_service.get_regime_heatmap_data()


@router.get("/performance-report")
async def get_performance_report():
    report = ssa_service.get_metrics()
    if not report:
        raise HTTPException(status_code=404, detail="Henüz bir eğitim yapılmadı.")
    return report

