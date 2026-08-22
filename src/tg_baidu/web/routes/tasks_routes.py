"""
Task management and transfer history API routes.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from ...baidu.share_parser import BaiduShareParser
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
    config = request.app.state.config

    # 1. Parse share link
    share_link = BaiduShareParser.parse(payload.share_url)
    if not share_link:
        raise HTTPException(status_code=400, detail="Invalid Baidu Netdisk share link.")

    pwd = payload.share_pwd or share_link.pwd

    # 2. Extract media title
    search_query = payload.custom_title.strip()
    if not search_query:
        parsed_media = MediaParser.parse_filename(payload.share_url)
        search_query = parsed_media.cleaned_title or payload.share_url
        detected_type = parsed_media.media_type
        detected_year = parsed_media.year
    else:
        detected_type = payload.media_type or "auto"
        detected_year = None

    # 3. Search TMDB
    results = await tmdb_client.search_multi(
        query=search_query,
        media_type=detected_type if detected_type != "auto" else "auto",
        year=detected_year,
    )
    if not results:
        results = await tmdb_client.search_multi(query=search_query)

    if not results:
        raise HTTPException(
            status_code=400,
            detail=f"Could not find matching movie/TV in TMDB for query: '{search_query}'.",
        )

    best_match = results[0]
    final_type = (
        payload.media_type
        if payload.media_type in ("movie", "tv")
        else best_match.media_type
    )

    # 4. Enqueue task
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
    return {"success": True, "message": f"Task {task_id} deleted."}


@router.post("/clear")
async def clear_tasks(payload: ClearTasksRequest, request: Request) -> Dict[str, Any]:
    """Clear completed/failed task records."""
    db = request.app.state.db
    await db.clear_tasks(payload.status)
    return {"success": True, "message": "Tasks cleared successfully."}
