"""
Async background task manager for transferring Baidu shares and TMDB-based media organization.
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
    """Manages asynchronous transfer and file renaming jobs."""

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

        # Determine target root directory
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

        await self.db.update_task_status(task_id, status="PROCESSING", progress=0.1)
        await self._notify(
            user_id,
            f"🚀 **开始处理任务** (`{task_id}`)\n"
            f"🎬 **匹配媒体**: {tmdb.display_name} ({'剧集' if media_type == 'tv' else '电影'})\n"
            f"📂 **目标目录**: `{dest_root}`\n"
            f"⏳ 正在解析并转存分享链接...",
        )

        # 1. Parse share info
        from ..baidu.share_parser import BaiduShareParser

        parsed_link = BaiduShareParser.parse(share_url)
        if not parsed_link:
            raise ValueError(f"Invalid Baidu share URL: {share_url}")

        pwd = share_pwd or parsed_link.pwd
        share_info = await self.baidu_client.get_share_info(parsed_link.surl, pwd)
        share_id = share_info["share_id"]
        from_uk = share_info["uk"]
        files = share_info.get("file_list", [])

        if not files:
            raise ValueError("No files found in this share link.")

        fs_ids = [f["fs_id"] for f in files]

        # 2. Transfer to a temporary staging folder
        temp_dir = f"/Media/Temp/{task_id}"
        await self.baidu_client.create_dir(temp_dir)
        await self.baidu_client.transfer_share_files(
            share_id=share_id,
            from_uk=from_uk,
            fs_id_list=fs_ids,
            dest_dir=temp_dir,
            pwd=pwd,
        )

        await self.db.update_task_status(task_id, status="PROCESSING", progress=0.4)
        await self._notify(
            user_id,
            f"📦 **转存成功** (`{task_id}`)\n"
            f"🔄 正在按照 TMDB 规范智能重命名并归档...",
        )

        # 3. List transferred files in temporary directory (recursively)
        all_transferred_files = await self._list_all_recursive(temp_dir)
        video_files = [
            f for f in all_transferred_files if not f.isdir and MediaParser.is_video_file(f.server_filename)
        ]

        if not video_files:
            # Maybe the transfer contains non-standard video extensions or folder structure
            video_files = [f for f in all_transferred_files if not f.isdir]

        total_files = len(video_files)
        await self.db.update_task_status(
            task_id,
            status="PROCESSING",
            progress=0.6,
            total_files=total_files,
        )

        # 4. Prepare TMDB episode metadata if TV show
        tv_episodes_cache: Dict[int, Dict[int, Any]] = {}

        # 5. Build Move & Rename Operations
        move_operations = []
        renamed_summary = []

        for vf in video_files:
            parsed_info = MediaParser.parse_filename(vf.server_filename)

            if media_type == "tv":
                season = parsed_info.season or 1
                episode_num = parsed_info.episode or 1

                if season not in tv_episodes_cache:
                    ep_map = await self.tmdb_client.get_season_episodes(
                        tmdb.id,
                        season,
                        language=user_settings.get("tmdb_language") or self.config.tmdb.language,
                    )
                    tv_episodes_cache[season] = ep_map

                ep_info = tv_episodes_cache[season].get(episode_num)
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

        # 6. Execute batch move & rename on Baidu Netdisk
        if move_operations:
            await self.baidu_client.batch_move_and_rename(move_operations)

        # 7. Cleanup temp directory
        if self.config.media.cleanup_temp_dirs:
            try:
                await self.baidu_client.delete_file(temp_dir)
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
            f"🎉 **任务完成！** (`{task_id}`)\n"
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
