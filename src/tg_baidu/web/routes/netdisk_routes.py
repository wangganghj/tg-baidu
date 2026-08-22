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
        clean_path = "/" + path.strip("/")
        dirs = await baidu_client.list_directories(clean_path)
        return {
            "current_path": clean_path,
            "directories": dirs,
        }
    except Exception as e:
        logger.exception("Failed to list directories at %s: %s", path, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/mkdir")
async def create_directory(
    payload: CreateDirRequest,
    request: Request,
) -> Dict[str, Any]:
    """Create a new folder on Baidu Netdisk."""
    baidu_client = request.app.state.baidu_client
    try:
        clean_path = "/" + payload.path.strip("/")
        res = await baidu_client.create_dir(clean_path)
        return {"success": True, "path": clean_path, "result": res}
    except Exception as e:
        logger.exception("Failed to create directory %s: %s", payload.path, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/set-target-dir")
async def set_target_dir(
    payload: SetTargetDirRequest,
    request: Request,
) -> Dict[str, Any]:
    """Update Movie or TV default directory in config and database."""
    config = request.app.state.config
    db = request.app.state.db

    clean_path = "/" + payload.path.strip("/")
    if payload.dir_type == "movie":
        config.media.movie_dir = clean_path
    elif payload.dir_type == "tv":
        config.media.tv_dir = clean_path
    else:
        raise HTTPException(status_code=400, detail="Invalid dir_type. Must be 'movie' or 'tv'.")

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
