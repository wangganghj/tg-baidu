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
    cookie: str = Field(default="", description="Baidu Netdisk Cookie / BDUSS")
    bduss: str = Field(default="", description="Baidu Netdisk BDUSS")
    stoken: str = Field(default="", description="Optional STOKEN cookie")
    app_key: str = Field(default="", description="Optional AppKey")
    app_secret: str = Field(default="", description="Optional AppSecret")
    redirect_uri: str = Field(default="oob", description="OAuth Redirect URI")
    access_token: str = Field(default="", description="Optional Access Token")
    refresh_token: str = Field(default="", description="Optional Refresh Token")


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


class WebConfig(BaseModel):
    enabled: bool = Field(default=True, description="Enable Web dashboard UI")
    host: str = Field(default="0.0.0.0", description="Web server bind host")
    port: int = Field(default=8082, description="Web server bind port")
    auth_password: str = Field(default="", description="Optional password protection for web UI")


class Config(BaseModel):
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    tmdb: TMDBConfig = Field(default_factory=TMDBConfig)
    baidu: BaiduConfig = Field(default_factory=BaiduConfig)
    media: MediaConfig = Field(default_factory=MediaConfig)
    system: SystemConfig = Field(default_factory=SystemConfig)
    web: WebConfig = Field(default_factory=WebConfig)

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
            Path("data/config.yaml"),
            Path("data/config.yml"),
            Path("/app/config.yaml"),
            Path("/app/data/config.yaml"),
        ])

        for path in search_paths:
            try:
                if path.is_file():
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
            "BAIDU_COOKIE": ("baidu", "cookie"),
            "BAIDU_BDUSS": ("baidu", "bduss"),
            "BAIDU_STOKEN": ("baidu", "stoken"),
            "BAIDU_APP_KEY": ("baidu", "app_key"),
            "BAIDU_APP_SECRET": ("baidu", "app_secret"),
            "BAIDU_REDIRECT_URI": ("baidu", "redirect_uri"),
            "BAIDU_ACCESS_TOKEN": ("baidu", "access_token"),
            "BAIDU_REFRESH_TOKEN": ("baidu", "refresh_token"),
            "MEDIA_MOVIE_DIR": ("media", "movie_dir"),
            "MEDIA_TV_DIR": ("media", "tv_dir"),
            "MEDIA_DEFAULT_DIR": ("media", "default_dir"),
            "SYSTEM_DATABASE_PATH": ("system", "database_path"),
            "SYSTEM_LOG_LEVEL": ("system", "log_level"),
            "WEB_ENABLED": ("web", "enabled"),
            "WEB_HOST": ("web", "host"),
            "WEB_PORT": ("web", "port"),
            "WEB_AUTH_PASSWORD": ("web", "auth_password"),
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

    def save_yaml(self, config_path: Optional[str | Path] = None) -> None:
        """Save current config to YAML file in persistent volume."""
        target_path = Path(config_path) if config_path else Path("data/config.yaml")
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            data = self.model_dump()
            with open(target_path, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        except Exception as e:
            print(f"Warning: Failed to save config to {target_path}: {e}")


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
