"""
System and Bot Settings API routes.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsUpdateRequest(BaseModel):
    # Telegram
    telegram_bot_token: Optional[str] = None
    telegram_admin_user_id: Optional[int] = None
    telegram_allowed_user_ids: Optional[List[int]] = None
    # TMDB
    tmdb_api_key: Optional[str] = None
    tmdb_language: Optional[str] = None
    tmdb_include_adult: Optional[bool] = None
    # Baidu App
    baidu_app_key: Optional[str] = None
    baidu_app_secret: Optional[str] = None
    baidu_redirect_uri: Optional[str] = None
    # Media
    media_movie_dir: Optional[str] = None
    media_tv_dir: Optional[str] = None
    media_movie_format: Optional[str] = None
    media_tv_format: Optional[str] = None
    media_auto_transfer: Optional[bool] = None
    media_cleanup_temp_dirs: Optional[bool] = None


class TMDBTestSearchRequest(BaseModel):
    query: str
    media_type: Optional[str] = "auto"
    year: Optional[int] = None
    language: Optional[str] = "zh-CN"


@router.get("")
async def get_settings(request: Request) -> Dict[str, Any]:
    """Retrieve current system configuration."""
    config = request.app.state.config
    return {
        "telegram": {
            "bot_token": config.telegram.bot_token[:6] + "..." if len(config.telegram.bot_token) > 10 else config.telegram.bot_token,
            "raw_bot_token": config.telegram.bot_token,
            "admin_user_id": config.telegram.admin_user_id,
            "allowed_user_ids": config.telegram.allowed_user_ids,
        },
        "tmdb": {
            "api_key": config.tmdb.api_key[:4] + "..." if len(config.tmdb.api_key) > 8 else config.tmdb.api_key,
            "raw_api_key": config.tmdb.api_key,
            "language": config.tmdb.language,
            "include_adult": config.tmdb.include_adult,
        },
        "baidu": {
            "app_key": config.baidu.app_key,
            "app_secret": config.baidu.app_secret[:4] + "..." if len(config.baidu.app_secret) > 8 else config.baidu.app_secret,
            "raw_app_secret": config.baidu.app_secret,
            "redirect_uri": config.baidu.redirect_uri,
        },
        "media": {
            "movie_dir": config.media.movie_dir,
            "tv_dir": config.media.tv_dir,
            "default_dir": config.media.default_dir,
            "movie_format": config.media.movie_format,
            "tv_format": config.media.tv_format,
            "auto_transfer": config.media.auto_transfer,
            "cleanup_temp_dirs": config.media.cleanup_temp_dirs,
        },
        "web": {
            "enabled": config.web.enabled,
            "host": config.web.host,
            "port": config.web.port,
            "has_auth": bool(config.web.auth_password),
        },
    }


@router.post("")
async def update_settings(payload: SettingsUpdateRequest, request: Request) -> Dict[str, Any]:
    """Update settings in memory and persist."""
    config = request.app.state.config
    tmdb_client = request.app.state.tmdb_client
    auth_manager = request.app.state.auth_manager

    # Telegram
    if payload.telegram_bot_token is not None:
        config.telegram.bot_token = payload.telegram_bot_token.strip()
    if payload.telegram_admin_user_id is not None:
        config.telegram.admin_user_id = payload.telegram_admin_user_id
    if payload.telegram_allowed_user_ids is not None:
        config.telegram.allowed_user_ids = payload.telegram_allowed_user_ids

    # TMDB
    if payload.tmdb_api_key is not None:
        config.tmdb.api_key = payload.tmdb_api_key.strip()
        tmdb_client.api_key = payload.tmdb_api_key.strip()
    if payload.tmdb_language is not None:
        config.tmdb.language = payload.tmdb_language.strip()
        tmdb_client.default_language = payload.tmdb_language.strip()
    if payload.tmdb_include_adult is not None:
        config.tmdb.include_adult = payload.tmdb_include_adult
        tmdb_client.include_adult = payload.tmdb_include_adult

    # Baidu
    if payload.baidu_app_key is not None:
        config.baidu.app_key = payload.baidu_app_key.strip()
        auth_manager.app_key = payload.baidu_app_key.strip()
    if payload.baidu_app_secret is not None:
        config.baidu.app_secret = payload.baidu_app_secret.strip()
        auth_manager.app_secret = payload.baidu_app_secret.strip()
    if payload.baidu_redirect_uri is not None:
        config.baidu.redirect_uri = payload.baidu_redirect_uri.strip()
        auth_manager.redirect_uri = payload.baidu_redirect_uri.strip()

    # Media
    if payload.media_movie_dir is not None:
        config.media.movie_dir = "/" + payload.media_movie_dir.strip("/")
    if payload.media_tv_dir is not None:
        config.media.tv_dir = "/" + payload.media_tv_dir.strip("/")
    if payload.media_movie_format is not None:
        config.media.movie_format = payload.media_movie_format.strip()
    if payload.media_tv_format is not None:
        config.media.tv_format = payload.media_tv_format.strip()
    if payload.media_auto_transfer is not None:
        config.media.auto_transfer = payload.media_auto_transfer
    if payload.media_cleanup_temp_dirs is not None:
        config.media.cleanup_temp_dirs = payload.media_cleanup_temp_dirs

    logger.info("Settings updated successfully.")
    return {"success": True, "message": "Settings updated successfully."}


@router.post("/test-tmdb")
async def test_tmdb_search(payload: TMDBTestSearchRequest, request: Request) -> Dict[str, Any]:
    """Test searching TMDB with given query."""
    tmdb_client = request.app.state.tmdb_client
    try:
        results = await tmdb_client.search_multi(
            query=payload.query.strip(),
            media_type=payload.media_type or "auto",
            year=payload.year,
            language=payload.language or "zh-CN",
        )
        return {
            "success": True,
            "count": len(results),
            "results": [
                {
                    "id": item.id,
                    "title": item.title,
                    "original_title": item.original_title,
                    "year": item.year,
                    "media_type": item.media_type,
                    "overview": item.overview,
                    "poster_url": item.poster_url,
                    "vote_average": item.vote_average,
                }
                for item in results[:6]
            ],
        }
    except Exception as e:
        logger.exception("TMDB test search failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
