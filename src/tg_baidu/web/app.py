"""
FastAPI application factory for the Web Dashboard with password protection & IP whitelist.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..baidu.auth import BaiduAuthManager
from ..baidu.client import BaiduClient
from ..config import Config
from ..core.database import Database
from ..core.task_manager import TransferTaskManager
from ..tmdb.client import TMDBClient
from .auth_helper import is_request_authenticated
from .routes import auth_routes, netdisk_routes, settings_routes, tasks_routes

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Public paths that never require password authentication
PUBLIC_PATHS = {
    "/login",
    "/api/auth/web-login",
    "/api/auth/web-status",
    "/health",
    "/docs",
    "/openapi.json",
    "/favicon.ico",
    "/favicon.svg",
}


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

    # Authentication & IP Whitelist Middleware
    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        path = request.url.path
        # Allow public endpoints
        if path in PUBLIC_PATHS or path.startswith("/static"):
            return await call_next(request)

        # Check authentication status
        is_authed, reason = is_request_authenticated(request)
        if not is_authed:
            # If user is accessing web page from browser, redirect to login
            accept = request.headers.get("Accept", "")
            if path == "/" or "text/html" in accept:
                return RedirectResponse(url="/login", status_code=302)
            return JSONResponse(
                status_code=401,
                content={"detail": "未授权访问，需要登录", "need_login": True},
            )

        return await call_next(request)

    # Static Files Mounting
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Register Routers
    app.include_router(auth_routes.router)
    app.include_router(netdisk_routes.router)
    app.include_router(settings_routes.router)
    app.include_router(tasks_routes.router)

    @app.get("/favicon.svg")
    @app.get("/favicon.ico")
    async def favicon():
        favicon_file = STATIC_DIR / "favicon.svg"
        if favicon_file.is_file():
            return Response(content=favicon_file.read_bytes(), media_type="image/svg+xml")
        return Response(status_code=404)

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        is_authed, _ = is_request_authenticated(request)
        if is_authed:
            return RedirectResponse(url="/", status_code=302)
        login_file = TEMPLATES_DIR / "login.html"
        if login_file.is_file():
            return HTMLResponse(content=login_file.read_text(encoding="utf-8"))
        return templates.TemplateResponse(request=request, name="login.html")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        is_authed, _ = is_request_authenticated(request)
        if not is_authed:
            return RedirectResponse(url="/login", status_code=302)
        index_file = TEMPLATES_DIR / "index.html"
        if index_file.is_file():
            return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
        return templates.TemplateResponse(request=request, name="index.html")

    @app.get("/health")
    async def health_check():
        return {"status": "ok", "app": "tg-baidu", "version": "0.1.0"}

    return app
