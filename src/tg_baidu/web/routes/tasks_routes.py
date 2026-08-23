"""
Task management and transfer history API routes.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from ...baidu.share_parser import BaiduShareParser
from ...tmdb.client import TMDBMediaResult
from ...tmdb.parser import MediaParser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class SubmitTaskRequest(BaseModel):
    share_url: str
    share_pwd: Optional[str] = ""
    media_type: Optional[str] = "auto"
    custom_title: Optional[str] = ""
    target_root_dir: Optional[str] = None


class ClearTasksRequest(BaseModel):
    status: Optional[str] = None


@router.get("")
async def list_tasks(
    request: Request,
    status: Optional[str] = Query(None, description="Filter by status (ALL, COMPLETED, PROCESSING, FAILED)"),
    search: Optional[str] = Query(None, description="Search query in task title or ID"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> Dict[str, Any]:
    """List tasks with filtering and pagination."""
    db = request.app.state.db
    offset = (page - 1) * limit
    tasks, total_count = await db.list_all_tasks(
        status=status,
        search=search,
        limit=limit,
        offset=offset,
    )
    return {
        "tasks": tasks,
        "total": total_count,
        "page": page,
        "limit": limit,
        "total_pages": (total_count + limit - 1) // limit if total_count > 0 else 1,
    }


@router.get("/stats")
async def get_task_stats(request: Request) -> Dict[str, Any]:
    """Get task statistics for the dashboard."""
    db = request.app.state.db
    return await db.get_task_stats()


@router.get("/{task_id}")
async def get_task_detail(task_id: str, request: Request) -> Dict[str, Any]:
    """Get single task details and rename history."""
    db = request.app.state.db
    task = await db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")
    return task


@router.post("/submit")
async def submit_transfer_task(payload: SubmitTaskRequest, request: Request) -> Dict[str, Any]:
    """Submit a new Baidu Pan share link for processing directly from Web UI."""
    task_manager = request.app.state.task_manager
    tmdb_client = request.app.state.tmdb_client
    baidu_client = request.app.state.baidu_client
    config = request.app.state.config

    # 1. Parse share link
    share_link = BaiduShareParser.parse(payload.share_url)
    if not share_link:
        raise HTTPException(status_code=400, detail="未识别到有效的百度网盘分享链接 (https://pan.baidu.com/s/...)")

    pwd = payload.share_pwd or share_link.pwd

    # 2. Extract media title (from custom_title, or share content inspection, or URL text)
    search_query = (payload.custom_title or "").strip()
    detected_type = payload.media_type or "auto"
    detected_year = None

    if not search_query:
        # Query share content to find real file/folder names
        share_info = await baidu_client.get_share_content_info(payload.share_url, pwd)
        raw_name = ""
        if share_info and share_info.get("items"):
            first_item = share_info["items"][0]
            raw_name = first_item.get("server_filename") or share_info.get("title", "")
            if first_item.get("isdir") in (1, "1", True) or "剧" in share_info.get("title", ""):
                detected_type = "tv"
        elif share_info and share_info.get("title"):
            raw_name = share_info.get("title", "")

        if raw_name:
            clean_raw = raw_name.split("/")[-1]
            parsed_media = MediaParser.parse_filename(clean_raw)
            search_query = parsed_media.cleaned_title or clean_raw
            detected_year = parsed_media.year
            if detected_type == "auto":
                detected_type = parsed_media.media_type
        else:
            parsed_media = MediaParser.parse_filename(payload.share_url)
            search_query = parsed_media.cleaned_title or payload.share_url
            detected_year = parsed_media.year

    # 3. Search TMDB if api key is configured
    best_match = None
    if getattr(tmdb_client, "api_key", None) and search_query and not search_query.startswith("http"):
        try:
            results = await tmdb_client.search_multi(
                query=search_query,
                media_type=detected_type if detected_type in ("movie", "tv") else "auto",
                year=detected_year,
            )
            if not results:
                results = await tmdb_client.search_multi(query=search_query)
            if results:
                best_match = results[0]
        except Exception as e:
            logger.warning("TMDB search notice: %s", e)

    # 4. Fallback if TMDB search has no result or no API key
    if not best_match:
        final_title = search_query if (search_query and not search_query.startswith("http")) else "百度网盘分享资源"
        final_type = detected_type if detected_type in ("movie", "tv") else "movie"
        best_match = TMDBMediaResult(
            id=0,
            title=final_title,
            original_title=final_title,
            year=detected_year,
            media_type=final_type,
            overview="百度网盘直接转存归档",
            poster_url="",
            vote_average=0.0,
        )

    final_type = (
        payload.media_type
        if payload.media_type in ("movie", "tv")
        else best_match.media_type
    )

    # 5. Enqueue task
    admin_id = config.telegram.admin_user_id or 0
    task_id = await task_manager.enqueue_task(
        telegram_user_id=admin_id,
        share_url=share_link.clean_share_url,
        share_pwd=pwd,
        tmdb_result=best_match,
        media_type=final_type,
        target_root_dir=payload.target_root_dir,
    )

    return {
        "success": True,
        "task_id": task_id,
        "tmdb": {
            "id": best_match.id,
            "title": best_match.title,
            "year": best_match.year,
            "media_type": final_type,
            "poster_url": best_match.poster_url,
        },
    }


@router.delete("/{task_id}")
async def delete_task(task_id: str, request: Request) -> Dict[str, Any]:
    """Delete a task record from database."""
    db = request.app.state.db
    await db.delete_task(task_id)
    return {"success": True, "task_id": task_id}


@router.post("/clear")
async def clear_tasks(payload: ClearTasksRequest, request: Request) -> Dict[str, Any]:
    """Clear tasks by status."""
    db = request.app.state.db
    deleted = await db.clear_tasks(status=payload.status)
    return {"success": True, "deleted_count": deleted}
