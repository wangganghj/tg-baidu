"""
SQLite Database layer for tg-baidu using aiosqlite.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import aiosqlite

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str = "data/tg_baidu.db"):
        self.db_path = db_path
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        p = Path(self.db_path)
        p.parent.mkdir(parents=True, exist_ok=True)

    async def init(self) -> None:
        """Initialize database schema."""
        async with aiosqlite.connect(self.db_path) as db:
            # Baidu OAuth Tokens table
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS baidu_auth (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_identifier TEXT UNIQUE NOT NULL,
                    access_token TEXT NOT NULL,
                    refresh_token TEXT,
                    expires_at REAL NOT NULL,
                    scope TEXT,
                    bduss TEXT,
                    stoken TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )

            # User Settings table
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS user_settings (
                    telegram_user_id INTEGER PRIMARY KEY,
                    movie_dir TEXT,
                    tv_dir TEXT,
                    tmdb_language TEXT,
                    auto_transfer INTEGER DEFAULT 0,
                    extra_json TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )

            # Task History table
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    telegram_user_id INTEGER NOT NULL,
                    share_url TEXT NOT NULL,
                    share_pwd TEXT,
                    media_type TEXT,
                    tmdb_id INTEGER,
                    tmdb_title TEXT,
                    year INTEGER,
                    status TEXT NOT NULL,  -- PENDING, PROCESSING, COMPLETED, FAILED
                    progress REAL DEFAULT 0.0,
                    total_files INTEGER DEFAULT 0,
                    processed_files INTEGER DEFAULT 0,
                    result_summary TEXT,
                    error_message TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            await db.commit()
            logger.info("Database initialized successfully at %s", self.db_path)

    # --------------------------------------------------------------------------
    # Baidu Auth Token Management
    # --------------------------------------------------------------------------

    async def save_baidu_token(
        self,
        access_token: str,
        refresh_token: str = "",
        expires_in: float = 2592000,
        scope: str = "",
        bduss: str = "",
        stoken: str = "",
        user_identifier: str = "default",
    ) -> None:
        now = time.time()
        expires_at = now + expires_in
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO baidu_auth (
                    user_identifier, access_token, refresh_token, expires_at,
                    scope, bduss, stoken, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_identifier) DO UPDATE SET
                    access_token = excluded.access_token,
                    refresh_token = excluded.refresh_token,
                    expires_at = excluded.expires_at,
                    scope = excluded.scope,
                    bduss = CASE WHEN excluded.bduss != '' THEN excluded.bduss ELSE baidu_auth.bduss END,
                    stoken = CASE WHEN excluded.stoken != '' THEN excluded.stoken ELSE baidu_auth.stoken END,
                    updated_at = excluded.updated_at
                """,
                (
                    user_identifier,
                    access_token,
                    refresh_token,
                    expires_at,
                    scope,
                    bduss,
                    stoken,
                    now,
                    now,
                ),
            )
            await db.commit()

    async def get_baidu_token(self, user_identifier: str = "default") -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM baidu_auth WHERE user_identifier = ?",
                (user_identifier,),
            )
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None

    # --------------------------------------------------------------------------
    # User Settings
    # --------------------------------------------------------------------------

    async def get_user_settings(self, telegram_user_id: int) -> Dict[str, Any]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM user_settings WHERE telegram_user_id = ?",
                (telegram_user_id,),
            )
            row = await cursor.fetchone()
            if row:
                res = dict(row)
                if res.get("extra_json"):
                    try:
                        res["extra"] = json.loads(res["extra_json"])
                    except Exception:
                        res["extra"] = {}
                return res
            return {}

    async def save_user_setting(
        self,
        telegram_user_id: int,
        movie_dir: Optional[str] = None,
        tv_dir: Optional[str] = None,
        tmdb_language: Optional[str] = None,
        auto_transfer: Optional[bool] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        now = time.time()
        current = await self.get_user_settings(telegram_user_id)
        m_dir = movie_dir if movie_dir is not None else current.get("movie_dir")
        t_dir = tv_dir if tv_dir is not None else current.get("tv_dir")
        lang = tmdb_language if tmdb_language is not None else current.get("tmdb_language", "zh-CN")
        auto = (
            int(auto_transfer)
            if auto_transfer is not None
            else current.get("auto_transfer", 0)
        )
        extra_json = json.dumps(extra or current.get("extra", {}))

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO user_settings (
                    telegram_user_id, movie_dir, tv_dir, tmdb_language,
                    auto_transfer, extra_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(telegram_user_id) DO UPDATE SET
                    movie_dir = excluded.movie_dir,
                    tv_dir = excluded.tv_dir,
                    tmdb_language = excluded.tmdb_language,
                    auto_transfer = excluded.auto_transfer,
                    extra_json = excluded.extra_json,
                    updated_at = excluded.updated_at
                """,
                (
                    telegram_user_id,
                    m_dir,
                    t_dir,
                    lang,
                    auto,
                    extra_json,
                    now,
                    now,
                ),
            )
            await db.commit()

    # --------------------------------------------------------------------------
    # Task Management
    # --------------------------------------------------------------------------

    async def create_task(
        self,
        task_id: str,
        telegram_user_id: int,
        share_url: str,
        share_pwd: str = "",
        media_type: str = "movie",
        tmdb_id: Optional[int] = None,
        tmdb_title: str = "",
        year: Optional[int] = None,
    ) -> None:
        now = time.time()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO tasks (
                    task_id, telegram_user_id, share_url, share_pwd,
                    media_type, tmdb_id, tmdb_title, year, status,
                    progress, total_files, processed_files, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', 0.0, 0, 0, ?, ?)
                """,
                (
                    task_id,
                    telegram_user_id,
                    share_url,
                    share_pwd,
                    media_type,
                    tmdb_id,
                    tmdb_title,
                    year,
                    now,
                    now,
                ),
            )
            await db.commit()

    async def update_task_status(
        self,
        task_id: str,
        status: str,
        progress: Optional[float] = None,
        total_files: Optional[int] = None,
        processed_files: Optional[int] = None,
        result_summary: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        now = time.time()
        fields = ["status = ?", "updated_at = ?"]
        params: List[Any] = [status, now]

        if progress is not None:
            fields.append("progress = ?")
            params.append(progress)
        if total_files is not None:
            fields.append("total_files = ?")
            params.append(total_files)
        if processed_files is not None:
            fields.append("processed_files = ?")
            params.append(processed_files)
        if result_summary is not None:
            fields.append("result_summary = ?")
            params.append(result_summary)
        if error_message is not None:
            fields.append("error_message = ?")
            params.append(error_message)

        params.append(task_id)
        query = f"UPDATE tasks SET {', '.join(fields)} WHERE task_id = ?"

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(query, params)
            await db.commit()

    async def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM tasks WHERE task_id = ?",
                (task_id,),
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def delete_baidu_token(self, user_identifier: str = "default") -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "DELETE FROM baidu_auth WHERE user_identifier = ?",
                (user_identifier,),
            )
            await db.commit()

    async def list_all_tasks(
        self,
        status: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[List[Dict[str, Any]], int]:
        """List tasks with filtering and pagination."""
        query = "SELECT * FROM tasks"
        count_query = "SELECT COUNT(*) FROM tasks"
        where_clauses = []
        params: List[Any] = []

        if status and status.upper() != "ALL":
            where_clauses.append("status = ?")
            params.append(status.upper())

        if search:
            where_clauses.append("(tmdb_title LIKE ? OR task_id LIKE ?)")
            search_param = f"%{search}%"
            params.extend([search_param, search_param])

        if where_clauses:
            clause = " WHERE " + " AND ".join(where_clauses)
            query += clause
            count_query += clause

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        fetch_params = params + [limit, offset]

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            count_cursor = await db.execute(count_query, params)
            count_row = await count_cursor.fetchone()
            total_count = count_row[0] if count_row else 0

            cursor = await db.execute(query, fetch_params)
            rows = await cursor.fetchall()
            return [dict(r) for r in rows], total_count

    async def delete_task(self, task_id: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
            await db.commit()

    async def clear_tasks(self, status: Optional[str] = None) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            if status:
                await db.execute("DELETE FROM tasks WHERE status = ?", (status.upper(),))
            else:
                await db.execute("DELETE FROM tasks")
            await db.commit()

    async def get_task_stats(self) -> Dict[str, int]:
        """Get summary stats for dashboard."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) as completed,
                    SUM(CASE WHEN status = 'PROCESSING' THEN 1 ELSE 0 END) as processing,
                    SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) as failed
                FROM tasks
                """
            )
            row = await cursor.fetchone()
            if row:
                return {
                    "total": row[0] or 0,
                    "completed": row[1] or 0,
                    "processing": row[2] or 0,
                    "failed": row[3] or 0,
                }
            return {"total": 0, "completed": 0, "processing": 0, "failed": 0}
