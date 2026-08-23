"""
Baidu Netdisk directory browser and selector API routes.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/netdisk", tags=["netdisk"])


class CreateDirRequest(BaseModel):
    path: str


class SetTargetDirRequest(BaseModel):
    dir_type: str  # "movie" or "tv"
    path: str


@router.get("/dirs")
async def list_directories(
    request: Request,
    path: str = Query("/", description="Target directory path"),
) -> Dict[str, Any]:
    """List sub-directories of a directory on Baidu Netdisk."""
    baidu_client = request.app.state.baidu_client
    try:
        clean_path = "/" + path.strip("/") if path != "/" else "/"
        dirs = await baidu_client.list_directories(clean_path)
        return {
            "current_path": clean_path,
            "directories": dirs,
            "count": len(dirs),
        }
    except Exception as e:
        logger.exception("Failed to list directories at %s: %s", path, e)
        return {
            "current_path": path,
            "directories": [],
            "error": str(e),
        }


@router.post("/mkdir")
async def create_directory(
    payload: CreateDirRequest,
    request: Request,
) -> Dict[str, Any]:
    """Create a new folder recursively on Baidu Netdisk."""
    baidu_client = request.app.state.baidu_client
    try:
        clean_path = "/" + payload.path.strip("/")
        await baidu_client.ensure_dir(clean_path)
        return {"success": True, "path": clean_path}
    except Exception as e:
        logger.exception("Failed to create directory %s: %s", payload.path, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/set-target-dir")
async def set_target_dir(
    payload: SetTargetDirRequest,
    request: Request,
) -> Dict[str, Any]:
    """Update Movie or TV default directory in config and database, and auto-create folder."""
    config = request.app.state.config
    db = request.app.state.db
    baidu_client = request.app.state.baidu_client

    clean_path = "/" + payload.path.strip("/")
    if payload.dir_type == "movie":
        config.media.movie_dir = clean_path
        await db.save_system_setting("media_movie_dir", clean_path)
    elif payload.dir_type == "tv":
        config.media.tv_dir = clean_path
        await db.save_system_setting("media_tv_dir", clean_path)
    else:
        raise HTTPException(status_code=400, detail="Invalid dir_type. Must be 'movie' or 'tv'.")

    # Persist updated config into data/config.yaml
    config.save_yaml("data/config.yaml")

    # Automatically ensure directory exists on Baidu Netdisk
    try:
        if baidu_client.is_configured():
            await baidu_client.ensure_dir(clean_path)
    except Exception as e:
        logger.warning("Auto ensure_dir failed during set_target_dir: %s", e)

    # Update admin user settings in database if admin_user_id exists
    if config.telegram.admin_user_id:
        if payload.dir_type == "movie":
            await db.save_user_setting(config.telegram.admin_user_id, movie_dir=clean_path)
        else:
            await db.save_user_setting(config.telegram.admin_user_id, tv_dir=clean_path)

    return {
        "success": True,
        "dir_type": payload.dir_type,
        "new_path": clean_path,
        "movie_dir": config.media.movie_dir,
        "tv_dir": config.media.tv_dir,
    }
