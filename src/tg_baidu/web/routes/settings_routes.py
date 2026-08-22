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
    # Baidu Cookie
    baidu_cookie: Optional[str] = None
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
            "cookie": config.baidu.cookie[:10] + "..." if len(config.baidu.cookie) > 15 else config.baidu.cookie,
            "raw_cookie": config.baidu.cookie or config.baidu.bduss,
            "bduss_hint": config.baidu.bduss[:8] + "..." if len(config.baidu.bduss) > 10 else config.baidu.bduss,
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
    baidu_client = request.app.state.baidu_client
    db = request.app.state.db

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

    # Baidu Cookie
    if payload.baidu_cookie is not None and payload.baidu_cookie.strip():
        raw_cookie = payload.baidu_cookie.strip()
        baidu_client.set_cookie(raw_cookie)
        config.baidu.cookie = baidu_client.cookie
        config.baidu.bduss = baidu_client.bduss
        config.baidu.stoken = baidu_client.stoken
        await db.save_baidu_cookie(cookie=baidu_client.cookie, bduss=baidu_client.bduss, stoken=baidu_client.stoken)

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
