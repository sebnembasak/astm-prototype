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

    ssa_service.ensure_models_loaded()
    results = []
    for row in rows:
        d = dict(row)
        regime = ssa_service.regime_map.get(d['cluster_id'])
        d['regime_label'] = regime['name'] if regime else "Bilinmeyen Yörünge"
        results.append(d)
    return results


@router.get("/regimes")
async def get_regimes():
    """cluster_id -> {name, color, icon} eşlemesi (küme merkezlerinden dinamik hesaplanır)."""
    ssa_service.ensure_models_loaded()
    return ssa_service.regime_map


@router.get("/prediction/{sat_id}")
async def get_ssa_prediction(sat_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT predicted_category as category, confidence, cluster_id FROM satellite_intelligence WHERE sat_id = ? ORDER BY predicted_at DESC LIMIT 1",
        (sat_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return dict(row)


@router.get("/status")
async def get_ssa_status():
    """Kaç uydu sınıflandırılmamış, toplam kaç uydu var."""
    return ssa_service.get_pending_classification_count()


@router.get("/heatmap")
async def get_heatmap():
    return ssa_service.get_regime_heatmap_data()


@router.get("/performance-report")
async def get_performance_report():
    report = ssa_service.get_metrics()
    if not report:
        raise HTTPException(status_code=404, detail="Henüz bir eğitim yapılmadı.")
    return report

