"""
Tests for Config loading and validation.
"""

import os
from tg_baidu.config import Config


def test_default_config():
    cfg = Config()
    assert cfg.media.movie_dir == "/Media/Movies"
    assert cfg.media.tv_dir == "/Media/TV"
    assert cfg.tmdb.language == "zh-CN"
    assert cfg.system.max_concurrent_tasks == 3


def test_env_override(monkeypatch):
    monkeypatch.setenv("TG_BOT_TOKEN", "test_bot_token_123")
    monkeypatch.setenv("TG_ADMIN_USER_ID", "999999")
    monkeypatch.setenv("MEDIA_MOVIE_DIR", "/Custom/Movies")

    cfg = Config.load()
    assert cfg.telegram.bot_token == "test_bot_token_123"
    assert cfg.telegram.admin_user_id == 999999
    assert cfg.media.movie_dir == "/Custom/Movies"
