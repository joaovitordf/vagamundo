"""FastAPI Application Entrypoint for Vagamundo v2."""

from __future__ import annotations
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from backend.api.routes import applications, auto_mode, dashboard, documents, jobs, profile, recruiters, search, settings
from backend.api.security import HostCheckMiddleware, get_token

_here = Path(__file__).resolve()
ROOT = _here.parent.parent.parent if _here.parent.parent.name == "backend" else _here.parent.parent
ANGULAR_DIST = ROOT / "frontend" / "dist" / "frontend" / "browser"

app = FastAPI(
    title="Vagamundo API",
    description="Backend API unificada do Vagamundo v2",
    version="2.0.0",
)

# Security and CORS middlewares
app.add_middleware(HostCheckMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4200",
        "http://127.0.0.1:4200",
        "http://localhost:8765",
        "http://127.0.0.1:8765",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API route modules
app.include_router(settings.router, prefix="/api")
app.include_router(search.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(applications.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(profile.router, prefix="/api")
app.include_router(recruiters.router, prefix="/api")
app.include_router(auto_mode.router, prefix="/api")

# SPA serving fallback for Angular
if ANGULAR_DIST.is_dir():
    if (ANGULAR_DIST / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=str(ANGULAR_DIST / "assets")), name="assets")
    if (ANGULAR_DIST / "media").is_dir():
        app.mount("/media", StaticFiles(directory=str(ANGULAR_DIST / "media")), name="media")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # Allow API routes to 404 naturally
        if full_path.startswith("api/"):
            return HTMLResponse(status_code=404, content='{"error": "Endpoint não encontrado"}')

        dist_root = ANGULAR_DIST.resolve()
        file_path = (dist_root / full_path).resolve()
        if full_path and file_path.is_relative_to(dist_root) and file_path.is_file():
            return FileResponse(file_path)

        index_file = ANGULAR_DIST / "index.html"
        if index_file.is_file():
            html = index_file.read_text(encoding="utf-8")
            token = get_token()
            html = html.replace("__PAINEL_TOKEN__", token)
            return HTMLResponse(content=html, media_type="text/html")

        return HTMLResponse(content="<h1>Vagamundo API v2 rodando.</h1><p>Frontend não compilado.</p>")

