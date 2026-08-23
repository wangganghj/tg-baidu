"""
Async background task manager for transferring Baidu shares to a temporary directory,
performing TMDB identification and renaming, and organizing into Movie/TV libraries.
"""

from __future__ import annotations

import asyncio
import logging
import posixpath
import uuid
from typing import Any, Callable, Coroutine, Dict, List, Optional

from ..baidu.client import BaiduClient, NetdiskFile
from ..config import Config
from ..tmdb.client import TMDBClient, TMDBMediaResult
from ..tmdb.formatter import PathFormatter
from ..tmdb.parser import MediaParser
from .database import Database

logger = logging.getLogger(__name__)


class TransferTaskManager:
    """Manages asynchronous transfer, TMDB identification, and file organization jobs."""

    def __init__(
        self,
        config: Config,
        db: Database,
        baidu_client: BaiduClient,
        tmdb_client: TMDBClient,
        notify_callback: Optional[Callable[[int, str], Coroutine[Any, Any, None]]] = None,
    ):
        self.config = config
        self.db = db
        self.baidu_client = baidu_client
        self.tmdb_client = tmdb_client
        self.notify_callback = notify_callback
        self._queue: asyncio.Queue = asyncio.Queue()
        self._workers: List[asyncio.Task] = []
        self._running = False

    async def start(self) -> None:
        """Start task worker loop."""
        self._running = True
        for i in range(self.config.system.max_concurrent_tasks):
            worker = asyncio.create_task(self._worker_loop(i))
            self._workers.append(worker)
        logger.info(
            "Transfer task manager started with %d workers.",
            self.config.system.max_concurrent_tasks,
        )

    async def stop(self) -> None:
        """Stop worker loops gracefully."""
        self._running = False
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    async def enqueue_task(
        self,
        telegram_user_id: int,
        share_url: str,
        share_pwd: str,
        tmdb_result: TMDBMediaResult,
        media_type: str = "movie",
        target_root_dir: Optional[str] = None,
    ) -> str:
        """Create and enqueue a new transfer & rename job."""
        task_id = uuid.uuid4().hex[:12]
        await self.db.create_task(
            task_id=task_id,
            telegram_user_id=telegram_user_id,
            share_url=share_url,
            share_pwd=share_pwd,
            media_type=media_type,
            tmdb_id=tmdb_result.id,
            tmdb_title=tmdb_result.title,
            year=tmdb_result.year,
        )

        task_payload = {
            "task_id": task_id,
            "telegram_user_id": telegram_user_id,
            "share_url": share_url,
            "share_pwd": share_pwd,
            "tmdb_result": tmdb_result,
            "media_type": media_type,
            "target_root_dir": target_root_dir,
        }
        await self._queue.put(task_payload)
        return task_id

    async def _notify(self, user_id: int, message: str) -> None:
        if self.notify_callback:
            try:
                await self.notify_callback(user_id, message)
            except Exception as e:
                logger.error("Failed to send telegram notification: %s", e)

    async def _worker_loop(self, worker_id: int) -> None:
        while self._running:
            try:
                task_data = await self._queue.get()
                task_id = task_data["task_id"]
                user_id = task_data["telegram_user_id"]
                try:
                    await self._process_task(task_data)
                except Exception as e:
                    logger.exception("Task %s failed: %s", task_id, e)
                    await self.db.update_task_status(
                        task_id=task_id,
                        status="FAILED",
                        error_message=str(e),
                    )
                    await self._notify(
                        user_id,
                        f"❌ **任务失败** (`{task_id}`)\n"
                        f"🎬 **媒体**: {task_data['tmdb_result'].display_name}\n"
                        f"⚠️ **错误**: {e}",
                    )
                finally:
                    self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Worker %d error: %s", worker_id, e)

    async def _process_task(self, data: Dict[str, Any]) -> None:
        task_id: str = data["task_id"]
        user_id: int = data["telegram_user_id"]
        share_url: str = data["share_url"]
        share_pwd: str = data["share_pwd"]
        tmdb: TMDBMediaResult = data["tmdb_result"]
        media_type: str = data["media_type"]

        # Determine target destination directory
        user_settings = await self.db.get_user_settings(user_id)
        if media_type == "tv":
            dest_root = (
                data.get("target_root_dir")
                or user_settings.get("tv_dir")
                or self.config.media.tv_dir
            )
        else:
            dest_root = (
                data.get("target_root_dir")
                or user_settings.get("movie_dir")
                or self.config.media.movie_dir
            )

        # 1. Staging directory: Save to temporary directory first
        temp_dir = f"/Media/Temp/{task_id}"
        await self.baidu_client.ensure_dir(temp_dir)

        await self.db.update_task_status(task_id, status="PROCESSING", progress=0.1)
        await self._notify(
            user_id,
            f"🚀 **开始处理任务** (`{task_id}`)\n"
            f"📥 **临时目录**: `{temp_dir}`\n"
            f"📂 **最终归档**: `{dest_root}`\n"
            f"⏳ 正在将分享链接转存至临时目录...",
        )

        # 2. Transfer shared files into the temporary directory
        await self.baidu_client.transfer_share_files(
            share_url=share_url,
            share_pwd=share_pwd,
            target_dir=temp_dir,
        )

        await self.db.update_task_status(task_id, status="PROCESSING", progress=0.35)
        await self._notify(
            user_id,
            f"📦 **临时目录转存完成** (`{task_id}`)\n"
            f"🔍 正在扫描文件并进行 TMDB 影视识别与重命名...",
        )

        # 3. Recursively list all files in the temporary directory
        all_transferred_files = await self._list_all_recursive(temp_dir)
        video_files = [
            f for f in all_transferred_files if not f.isdir and MediaParser.is_video_file(f.server_filename)
        ]

        if not video_files:
            video_files = [f for f in all_transferred_files if not f.isdir]

        total_files = len(video_files)
        if total_files == 0:
            raise ValueError(f"临时目录 '{temp_dir}' 中未找到可处理的文件。")

        await self.db.update_task_status(
            task_id,
            status="PROCESSING",
            progress=0.5,
            total_files=total_files,
        )

        # 4. Refine TMDB match from actual transferred folder/file names in temp_dir
        clean_temp = "/" + temp_dir.strip("/")
        candidate_title_candidates = []
        is_tv_detected = False

        for item in all_transferred_files:
            rel = item.path[len(clean_temp):].strip("/")
            parts = [p for p in rel.split("/") if p]
            if item.isdir:
                if len(parts) >= 1:
                    top_part = parts[0]
                    if top_part.lower() not in ("s01", "s02", "season 1", "season 01", "season 02", "specials", "temp"):
                        if top_part not in candidate_title_candidates:
                            candidate_title_candidates.append(top_part)
            else:
                vf_parsed = MediaParser.parse_filename(posixpath.basename(item.path))
                if vf_parsed.media_type == "tv" or vf_parsed.episode is not None:
                    is_tv_detected = True
                if len(parts) > 1 and parts[0] not in candidate_title_candidates:
                    top_part = parts[0]
                    if top_part.lower() not in ("s01", "s02", "season 1", "season 01", "season 02", "specials", "temp"):
                        candidate_title_candidates.append(top_part)

        if len(video_files) > 1:
            is_tv_detected = True

        raw_title_to_search = ""
        if candidate_title_candidates:
            raw_title_to_search = candidate_title_candidates[0]
        elif video_files:
            raw_title_to_search = video_files[0].server_filename

        if raw_title_to_search:
            clean_search_parsed = MediaParser.parse_filename(raw_title_to_search)
            detected_query = clean_search_parsed.cleaned_title or raw_title_to_search
            detected_year = clean_search_parsed.year
            media_type = "tv" if is_tv_detected else clean_search_parsed.media_type

            # Search TMDB with the real title extracted from disk
            if getattr(self.tmdb_client, "api_key", None):
                try:
                    candidates = await self.tmdb_client.search_multi(
                        query=detected_query,
                        media_type=media_type,
                        year=detected_year,
                    )
                    if not candidates:
                        candidates = await self.tmdb_client.search_multi(query=detected_query)
                    if candidates:
                        tmdb = candidates[0]
                        media_type = tmdb.media_type
                    else:
                        tmdb = TMDBMediaResult(
                            id=0,
                            title=detected_query,
                            original_title=detected_query,
                            year=detected_year,
                            media_type=media_type,
                            overview="",
                            poster_url="",
                        )
                except Exception as e:
                    logger.warning("Refined TMDB search failed: %s", e)
            else:
                tmdb = TMDBMediaResult(
                    id=0,
                    title=detected_query,
                    original_title=detected_query,
                    year=detected_year,
                    media_type=media_type,
                    overview="",
                    poster_url="",
                )

        # Re-evaluate target destination root according to final media_type
        if media_type == "tv":
            dest_root = (
                data.get("target_root_dir")
                or user_settings.get("tv_dir")
                or self.config.media.tv_dir
            )
        else:
            dest_root = (
                data.get("target_root_dir")
                or user_settings.get("movie_dir")
                or self.config.media.movie_dir
            )

        logger.info("Task %s classified as %s: %s (Target: %s)", task_id, media_type, tmdb.display_name, dest_root)

        # 5. Prepare TMDB episode metadata if TV show
        tv_episodes_cache: Dict[int, Dict[int, Any]] = {}
        move_operations = []
        renamed_summary = []

        for vf in video_files:
            parsed_info = MediaParser.parse_filename(vf.server_filename)

            if media_type == "tv":
                season = parsed_info.season or 1
                episode_num = parsed_info.episode or 1

                if season not in tv_episodes_cache and tmdb.id > 0:
                    ep_map = await self.tmdb_client.get_season_episodes(
                        tmdb.id,
                        season,
                        language=user_settings.get("tmdb_language") or self.config.tmdb.language,
                    )
                    tv_episodes_cache[season] = ep_map

                ep_info = tv_episodes_cache.get(season, {}).get(episode_num)
                dest_full_path = PathFormatter.format_tv_path(
                    root_dir=dest_root,
                    tmdb=tmdb,
                    parsed=parsed_info,
                    episode_info=ep_info,
                    template=self.config.media.tv_format,
                )
            else:
                dest_full_path = PathFormatter.format_movie_path(
                    root_dir=dest_root,
                    tmdb=tmdb,
                    parsed=parsed_info,
                    template=self.config.media.movie_format,
                )

            dest_folder = posixpath.dirname(dest_full_path)
            dest_filename = posixpath.basename(dest_full_path)

            # Ensure the specific destination folder exists
            await self.baidu_client.ensure_dir(dest_folder)

            move_operations.append(
                {
                    "path": vf.path,
                    "dest": dest_folder,
                    "newname": dest_filename,
                }
            )
            renamed_summary.append(f"• `{vf.server_filename}`\n  ➡️ `{dest_full_path}`")

        # 6. Execute batch move & rename from temporary directory into destination
        await self.db.update_task_status(task_id, status="PROCESSING", progress=0.75)
        if move_operations:
            await self.baidu_client.batch_move_and_rename(move_operations)

        # 7. Cleanup temporary directory
        if self.config.media.cleanup_temp_dirs:
            try:
                await self.baidu_client.delete_file(temp_dir)
                logger.info("Cleaned up temp directory: %s", temp_dir)
            except Exception as e:
                logger.warning("Failed to delete temp dir %s: %s", temp_dir, e)

        # 8. Complete task
        summary_text = "\n".join(renamed_summary[:10])
        if len(renamed_summary) > 10:
            summary_text += f"\n... 以及其他 {len(renamed_summary) - 10} 个文件"

        await self.db.update_task_status(
            task_id=task_id,
            status="COMPLETED",
            progress=1.0,
            processed_files=total_files,
            result_summary=summary_text,
        )

        await self._notify(
            user_id,
            f"🎉 **任务完成！已成功归档** (`{task_id}`)\n"
            f"🎬 **媒体**: {tmdb.display_name}\n"
            f"📂 **整理结果 ({total_files} 个文件)**:\n{summary_text}",
        )

    async def _list_all_recursive(self, dir_path: str) -> List[NetdiskFile]:
        """Recursively list all files inside a directory."""
        all_files: List[NetdiskFile] = []
        queue = [dir_path]

        while queue:
            current_dir = queue.pop(0)
            try:
                items = await self.baidu_client.list_dir(current_dir)
                for item in items:
                    if item.isdir:
                        queue.append(item.path)
                    all_files.append(item)
            except Exception as e:
                logger.error("Failed to list dir %s: %s", current_dir, e)

        return all_files
