"""
Configuration management for tg-baidu using Pydantic.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, List, Optional
import yaml
from pydantic import BaseModel, Field


class TelegramConfig(BaseModel):
    bot_token: str = Field(default="", description="Telegram Bot Token from BotFather")
    allowed_user_ids: List[int] = Field(default_factory=list, description="Allowed user IDs (empty for all)")
    admin_user_id: int = Field(default=0, description="Admin Telegram User ID")


class TMDBConfig(BaseModel):
    api_key: str = Field(default="", description="TMDB API Key or Read Access Token")
    language: str = Field(default="zh-CN", description="Default metadata language")
    include_adult: bool = Field(default=False, description="Include adult content")


class BaiduConfig(BaseModel):
    app_key: str = Field(default="", description="Baidu Netdisk AppKey (Client ID)")
    app_secret: str = Field(default="", description="Baidu Netdisk AppSecret (Client Secret)")
    redirect_uri: str = Field(default="oob", description="OAuth Redirect URI")
    access_token: str = Field(default="", description="Baidu OAuth Access Token")
    refresh_token: str = Field(default="", description="Baidu OAuth Refresh Token")
    bduss: str = Field(default="", description="Optional BDUSS cookie for share operations")
    stoken: str = Field(default="", description="Optional STOKEN cookie")


class MediaConfig(BaseModel):
    movie_dir: str = Field(default="/Media/Movies", description="Target directory for movies")
    tv_dir: str = Field(default="/Media/TV", description="Target directory for TV shows")
    default_dir: str = Field(default="/Media/Others", description="Fallback directory")
    movie_format: str = Field(
        default="{title} ({year})/{title} ({year}) [{resolution}].{ext}",
        description="Movie renaming template",
    )
    tv_format: str = Field(
        default="{title} ({year})/Season {season:02d}/{title} - S{season:02d}E{episode:02d} - {episode_title}.{ext}",
        description="TV show renaming template",
    )
    auto_transfer: bool = Field(default=False, description="Auto transfer without confirmation")
    cleanup_temp_dirs: bool = Field(default=True, description="Delete temporary transfer folders after moving")


class SystemConfig(BaseModel):
    database_path: str = Field(default="data/tg_baidu.db", description="SQLite database path")
    log_level: str = Field(default="INFO", description="Logging level")
    max_concurrent_tasks: int = Field(default=3, description="Max concurrent transfer tasks")


class Config(BaseModel):
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    tmdb: TMDBConfig = Field(default_factory=TMDBConfig)
    baidu: BaiduConfig = Field(default_factory=BaiduConfig)
    media: MediaConfig = Field(default_factory=MediaConfig)
    system: SystemConfig = Field(default_factory=SystemConfig)

    @classmethod
    def load(cls, config_path: Optional[str | Path] = None) -> Config:
        """
        Load configuration from YAML file and environment variables.
        Priority: Env Vars > YAML File > Defaults
        """
        data: dict[str, Any] = {}

        # Determine config file path
        search_paths = []
        if config_path:
            search_paths.append(Path(config_path))
        search_paths.extend([
            Path("config.yaml"),
            Path("config.yml"),
            Path("/app/config.yaml"),
        ])

        for path in search_paths:
            if path.is_file():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        yaml_data = yaml.safe_load(f)
                        if isinstance(yaml_data, dict):
                            data = yaml_data
                            break
                except Exception as e:
                    print(f"Warning: Failed to load config from {path}: {e}")

        # Override with environment variables
        env_mappings = {
            "TG_BOT_TOKEN": ("telegram", "bot_token"),
            "TG_ALLOWED_USER_IDS": ("telegram", "allowed_user_ids"),
            "TG_ADMIN_USER_ID": ("telegram", "admin_user_id"),
            "TMDB_API_KEY": ("tmdb", "api_key"),
            "TMDB_LANGUAGE": ("tmdb", "language"),
            "BAIDU_APP_KEY": ("baidu", "app_key"),
            "BAIDU_APP_SECRET": ("baidu", "app_secret"),
            "BAIDU_REDIRECT_URI": ("baidu", "redirect_uri"),
            "BAIDU_ACCESS_TOKEN": ("baidu", "access_token"),
            "BAIDU_REFRESH_TOKEN": ("baidu", "refresh_token"),
            "BAIDU_BDUSS": ("baidu", "bduss"),
            "BAIDU_STOKEN": ("baidu", "stoken"),
            "MEDIA_MOVIE_DIR": ("media", "movie_dir"),
            "MEDIA_TV_DIR": ("media", "tv_dir"),
            "MEDIA_DEFAULT_DIR": ("media", "default_dir"),
            "SYSTEM_DATABASE_PATH": ("system", "database_path"),
            "SYSTEM_LOG_LEVEL": ("system", "log_level"),
        }

        for env_var, (section, key) in env_mappings.items():
            val = os.getenv(env_var)
            if val is not None:
                if section not in data:
                    data[section] = {}
                if key == "allowed_user_ids":
                    data[section][key] = [
                        int(uid.strip())
                        for uid in val.split(",")
                        if uid.strip().isdigit()
                    ]
                elif key == "admin_user_id":
                    data[section][key] = int(val) if val.isdigit() else 0
                else:
                    data[section][key] = val

        return cls(**data)


# Global singleton instance holder
_global_config: Optional[Config] = None


def get_config(config_path: Optional[str | Path] = None) -> Config:
    """Get or load the global config."""
    global _global_config
    if _global_config is None or config_path is not None:
        _global_config = Config.load(config_path)
    return _global_config


def set_config(config: Config) -> None:
    """Set global config instance."""
    global _global_config
    _global_config = config
