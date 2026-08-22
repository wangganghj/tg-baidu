"""
Main entry point for tg-baidu application.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from rich.logging import RichHandler
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder

from .baidu.auth import BaiduAuthManager
from .baidu.client import BaiduClient
from .bot.handlers import BotHandlers
from .config import Config, get_config
from .core.database import Database
from .core.task_manager import TransferTaskManager
from .tmdb.client import TMDBClient


def setup_logging(log_level: str = "INFO") -> None:
    """Setup structured console logging."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="tg-baidu: Telegram Bot for Baidu Netdisk share transfer and TMDB renaming."
    )
    parser.add_argument(
        "-c", "--config", type=str, default=None, help="Path to config.yaml"
    )
    return parser.parse_args()


async def post_init_hook(application) -> None:
    """Run initial setup after Telegram application is initialized."""
    task_mgr: TransferTaskManager = application.bot_data["task_manager"]
    db: Database = application.bot_data["db"]
    await db.init()
    await task_mgr.start()
    logging.info("tg-baidu background task manager started.")


async def post_stop_hook(application) -> None:
    """Clean up background workers on shutdown."""
    task_mgr: TransferTaskManager = application.bot_data.get("task_manager")
    if task_mgr:
        await task_mgr.stop()
    logging.info("tg-baidu background task manager stopped.")


def main() -> None:
    """Main execution function."""
    args = parse_args()
    config = get_config(args.config)
    setup_logging(config.system.log_level)

    logger = logging.getLogger("tg_baidu")
    logger.info("Starting tg-baidu bot...")

    if not config.telegram.bot_token:
        logger.error("❌ Telegram Bot Token is missing! Please configure config.yaml or TG_BOT_TOKEN.")
        sys.exit(1)

    if not config.tmdb.api_key:
        logger.warning("⚠️ TMDB API Key is not set. TMDB search and metadata parsing may fail.")

    if not config.baidu.app_key:
        logger.warning("⚠️ Baidu AppKey is not set. Baidu OAuth authorization will require configuration.")

    # 1. Initialize Database
    db = Database(config.system.database_path)

    # 2. Initialize Baidu Auth and Client
    auth_manager = BaiduAuthManager(
        app_key=config.baidu.app_key,
        app_secret=config.baidu.app_secret,
        redirect_uri=config.baidu.redirect_uri,
        db=db,
    )
    baidu_client = BaiduClient(
        auth_manager=auth_manager,
        fallback_token=config.baidu.access_token,
        bduss=config.baidu.bduss,
        stoken=config.baidu.stoken,
    )

    # 3. Initialize TMDB Client
    tmdb_client = TMDBClient(
        api_key=config.tmdb.api_key,
        default_language=config.tmdb.language,
        include_adult=config.tmdb.include_adult,
    )

    # 4. Build Telegram Application
    app = (
        ApplicationBuilder()
        .token(config.telegram.bot_token)
        .post_init(post_init_hook)
        .post_stop(post_stop_hook)
        .build()
    )

    # 5. Notification callback from Task Manager to Telegram User
    async def notify_user(user_id: int, message: str) -> None:
        await app.bot.send_message(
            chat_id=user_id,
            text=message,
            parse_mode=ParseMode.HTML,
        )

    # 6. Initialize Task Manager
    task_manager = TransferTaskManager(
        config=config,
        db=db,
        baidu_client=baidu_client,
        tmdb_client=tmdb_client,
        notify_callback=notify_user,
    )

    # Attach to application bot_data
    app.bot_data["db"] = db
    app.bot_data["task_manager"] = task_manager

    # 7. Register Bot Handlers
    handlers = BotHandlers(
        config=config,
        db=db,
        auth_manager=auth_manager,
        baidu_client=baidu_client,
        tmdb_client=tmdb_client,
        task_manager=task_manager,
    )
    handlers.register(app)

    logger.info("Bot is ready. Starting polling...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
