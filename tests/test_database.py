"""
Tests for SQLite Database layer.
"""

import os
import pytest
from tg_baidu.core.database import Database


@pytest.mark.asyncio
async def test_database_lifecycle(tmp_path):
    db_file = tmp_path / "test.db"
    db = Database(str(db_file))
    await db.init()

    # 1. Test Baidu token save and retrieve
    await db.save_baidu_token(
        access_token="test_access_token",
        refresh_token="test_refresh_token",
        expires_in=3600,
        scope="basic,netdisk",
    )
    token_record = await db.get_baidu_token()
    assert token_record is not None
    assert token_record["access_token"] == "test_access_token"
    assert token_record["refresh_token"] == "test_refresh_token"

    # 2. Test User settings
    await db.save_user_setting(
        telegram_user_id=12345,
        movie_dir="/Custom/Movies",
        auto_transfer=True,
    )
    settings = await db.get_user_settings(12345)
    assert settings["movie_dir"] == "/Custom/Movies"
    assert settings["auto_transfer"] == 1

    # 3. Test Task lifecycle
    await db.create_task(
        task_id="task_001",
        telegram_user_id=12345,
        share_url="https://pan.baidu.com/s/1xyz",
        media_type="movie",
        tmdb_id=123,
        tmdb_title="Test Movie",
        year=2024,
    )
    task = await db.get_task("task_001")
    assert task is not None
    assert task["status"] == "PENDING"

    await db.update_task_status(
        task_id="task_001",
        status="COMPLETED",
        progress=1.0,
        total_files=1,
        processed_files=1,
    )
    task_after = await db.get_task("task_001")
    assert task_after["status"] == "COMPLETED"
    assert task_after["progress"] == 1.0
