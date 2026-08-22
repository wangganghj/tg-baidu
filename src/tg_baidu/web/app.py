"""
FastAPI application factory for the Web Dashboard.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..baidu.auth import BaiduAuthManager
from ..baidu.client import BaiduClient
from ..config import Config
from ..core.database import Database
from ..core.task_manager import TransferTaskManager
from ..tmdb.client import TMDBClient
from .routes import auth_routes, netdisk_routes, settings_routes, tasks_routes

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def create_web_app(
    config: Config,
    db: Database,
    auth_manager: BaiduAuthManager,
    baidu_client: BaiduClient,
    tmdb_client: TMDBClient,
    task_manager: TransferTaskManager,
) -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="tg-baidu Web Dashboard",
        description="Web dashboard for Baidu Netdisk share transfer and TMDB renaming.",
        version="0.1.0",
        docs_url="/docs",
        redoc_url=None,
    )

    # Attach shared singletons to app state
    app.state.config = config
    app.state.db = db
    app.state.auth_manager = auth_manager
    app.state.baidu_client = baidu_client
    app.state.tmdb_client = tmdb_client
    app.state.task_manager = task_manager

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register Routers
    app.include_router(auth_routes.router)
    app.include_router(netdisk_routes.router)
    app.include_router(settings_routes.router)
    app.include_router(tasks_routes.router)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        index_file = TEMPLATES_DIR / "index.html"
        if index_file.is_file():
            return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
        return templates.TemplateResponse(request=request, name="index.html")

    @app.get("/health")
    async def health_check():
        return {"status": "ok", "app": "tg-baidu", "version": "0.1.0"}

    return app
