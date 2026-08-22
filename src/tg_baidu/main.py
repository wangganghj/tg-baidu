"""
Main entry point for tg-baidu application: Telegram Bot + FastAPI Web Dashboard.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uvicorn
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
from .web.app import create_web_app


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
        description="tg-baidu: Telegram Bot and Web Dashboard for Baidu Netdisk share transfer and TMDB renaming."
    )
    parser.add_argument(
        "-c", "--config", type=str, default=None, help="Path to config.yaml"
    )
    return parser.parse_args()


async def run_services(config: Config) -> None:
    """Run Web Server and Telegram Bot concurrently."""
    logger = logging.getLogger("tg_baidu")
    logger.info("Initializing tg-baidu services...")

    # 1. Initialize Database
    db = Database(config.system.database_path)
    await db.init()

    # 2. Initialize Baidu Auth and Client from DB and Config
    auth_manager = BaiduAuthManager(
        app_key=config.baidu.app_key,
        app_secret=config.baidu.app_secret,
        redirect_uri=config.baidu.redirect_uri,
        db=db,
    )

    token_record = await db.get_baidu_token()
    cookie_val = config.baidu.cookie
    bduss_val = config.baidu.bduss
    stoken_val = config.baidu.stoken
    if token_record:
        if token_record.get("cookie"):
            cookie_val = token_record["cookie"]
        if token_record.get("bduss"):
            bduss_val = token_record["bduss"]
        if token_record.get("stoken"):
            stoken_val = token_record["stoken"]

    baidu_client = BaiduClient(
        cookie=cookie_val,
        bduss=bduss_val,
        stoken=stoken_val,
        auth_manager=auth_manager,
    )

    # 3. Initialize TMDB Client
    tmdb_client = TMDBClient(
        api_key=config.tmdb.api_key,
        default_language=config.tmdb.language,
        include_adult=config.tmdb.include_adult,
    )

    # 4. Telegram Application Setup (Optional if bot_token is empty initially)
    tg_app = None
    if config.telegram.bot_token:
        tg_app = (
            ApplicationBuilder()
            .token(config.telegram.bot_token)
            .build()
        )

    # 5. User Notification Callback
    async def notify_user(user_id: int, message: str) -> None:
        if tg_app and user_id:
            try:
                await tg_app.bot.send_message(
                    chat_id=user_id,
                    text=message,
                    parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                logger.error("Failed to send Telegram notification to user %s: %s", user_id, e)

    # 6. Initialize Task Manager
    task_manager = TransferTaskManager(
        config=config,
        db=db,
        baidu_client=baidu_client,
        tmdb_client=tmdb_client,
        notify_callback=notify_user,
    )
    await task_manager.start()

    # 7. Register Telegram Handlers if configured
    if tg_app:
        tg_app.bot_data["db"] = db
        tg_app.bot_data["task_manager"] = task_manager
        handlers = BotHandlers(
            config=config,
            db=db,
            auth_manager=auth_manager,
            baidu_client=baidu_client,
            tmdb_client=tmdb_client,
            task_manager=task_manager,
        )
        handlers.register(tg_app)

    tasks = []

    # 8. Web Server Task
    if config.web.enabled:
        web_app = create_web_app(
            config=config,
            db=db,
            auth_manager=auth_manager,
            baidu_client=baidu_client,
            tmdb_client=tmdb_client,
            task_manager=task_manager,
        )
        server_cfg = uvicorn.Config(
            app=web_app,
            host=config.web.host,
            port=config.web.port,
            log_level="info",
            access_log=True,
        )
        server = uvicorn.Server(server_cfg)
        logger.info(
            "🌐 Web Dashboard is running at http://%s:%d",
            "localhost" if config.web.host == "0.0.0.0" else config.web.host,
            config.web.port,
        )
        tasks.append(server.serve())

    # 9. Telegram Bot Task
    if tg_app:
        logger.info("🤖 Telegram Bot is starting polling...")
        async def run_bot():
            async with tg_app:
                await tg_app.start()
                await tg_app.updater.start_polling(drop_pending_updates=True)
                # Keep running until cancelled
                while True:
                    await asyncio.sleep(1)

        tasks.append(run_bot())
    else:
        logger.info("ℹ️ Telegram Bot Token is not configured yet. You can configure it via the Web Dashboard.")

    if not tasks:
        logger.error("No services are enabled. Please check configuration.")
        return

    try:
        await asyncio.gather(*tasks)
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        logger.info("Shutting down tg-baidu services...")
        await task_manager.stop()
        if tg_app and tg_app.updater:
            await tg_app.updater.stop()
            await tg_app.stop()


def main() -> None:
    """Main execution entrypoint."""
    args = parse_args()
    config = get_config(args.config)
    setup_logging(config.system.log_level)

    try:
        asyncio.run(run_services(config))
    except (KeyboardInterrupt, SystemExit):
        logging.info("tg-baidu stopped by user.")


if __name__ == "__main__":
    main()
