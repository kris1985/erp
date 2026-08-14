from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1 import api_router
from app.api.wechat.callback import router as wechat_router
from app.config import get_settings
from app.db_schema import ensure_schema
from app.mcp.router import router as mcp_router
from app.services.agent_policy import get_policy_bundle

settings = get_settings()

# Governance artifacts are code: reject an invalid registry before serving traffic.
get_policy_bundle()

# 兼容已有库补列（如派工 assigned_worker_id）
try:
    ensure_schema()
except Exception:
    pass

app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(wechat_router)
app.include_router(mcp_router)

# 上传图片静态目录（供应商产品等）
UPLOADS = Path(settings.uploads_dir)
UPLOADS.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOADS), name="uploads")


@app.get("/api/health")
def health():
    return {"ok": True, "service": settings.app_name}


DIST = Path(settings.web_dist_dir)
if DIST.exists():
    assets = DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        # Do not shadow API / uploads
        if (
            full_path.startswith("api/")
            or full_path.startswith("mcp")
            or full_path.startswith("uploads/")
            or full_path.startswith("docs")
            or full_path.startswith("openapi")
        ):
            raise HTTPException(status_code=404)
        candidate = DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        index = DIST / "index.html"
        if index.exists():
            return FileResponse(index)
        raise HTTPException(status_code=404, detail="前端未构建，请先 npm run build")
