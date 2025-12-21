from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
# Statik dosyaları servis etmek için gerekli kütüphaneler
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pathlib import Path

from backend.api import router_conjunctions, router_maneuver, router_tle, router_propagate, router_ssa
from backend.models.db import init_db

# Uygulama başladığında DByi kur
init_db()

app = FastAPI(
    title="ASTM Prototype API",
    description="ASTM",
    version="0.1.0",
)

# CORS ayarları
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Geliştirme ortamında tüm domainlere izin ver
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router_tle.router)
app.include_router(router_conjunctions.router)
app.include_router(router_maneuver.router)
app.include_router(router_propagate.router)
app.include_router(router_ssa.router)

# Statik dosyaları kök dizinine göre ayarla
app.mount("/assets", StaticFiles(directory="dashboard/assets"), name="assets")


# index.html dosyasını döndür
@app.get("/", tags=["Root"], response_class=HTMLResponse)
async def read_dashboard():
    dashboard_path = Path("dashboard/index.html")
    if not dashboard_path.exists():
        return HTMLResponse("<h1>Dashboard dosyası (dashboard/index.html) bulunamadı.</h1>", status_code=404)

    with open(dashboard_path, "r", encoding="utf-8") as f:
        return f.read()


@app.get("/health")
async def health_check():
    return {"status": "OK", "services": ["api", "database"]}


# Uygulama Uvicorn ile çalıştırılabilir:
# uvicorn backend.app.main:app --reload

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
