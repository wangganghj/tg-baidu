"""
Media path and filename formatter adhering to Plex / Emby / Jellyfin standards.
"""

from __future__ import annotations

import os
import posixpath
import re
from typing import Optional
from .client import TMDBEpisodeInfo, TMDBMediaResult
from .parser import ParsedMediaInfo


def sanitize_filename(name: str) -> str:
    """
    Remove or replace characters that are invalid in file paths or Baidu Netdisk.
    Illegal chars: / \ : * ? " < > |
    """
    if not name:
        return ""
    # Replace colon with dash or space
    name = name.replace(":", " -").replace("/", "-").replace("\\", "-")
    # Remove remaining forbidden characters
    name = re.sub(r'[\*\?"<>\|]', "", name)
    # Collapse consecutive whitespace
    name = re.sub(r"\s+", " ", name).strip()
    return name


class PathFormatter:
    """Formats standardized destination paths for movies and TV episodes."""

    @classmethod
    def format_movie_path(
        cls,
        root_dir: str,
        tmdb: TMDBMediaResult,
        parsed: ParsedMediaInfo,
        template: Optional[str] = None,
    ) -> str:
        """
        Format destination relative path for a Movie.
        Default: {title} ({year})/{title} ({year}) [{resolution}].{ext}
        """
        title = sanitize_filename(tmdb.title)
        year = tmdb.year or parsed.year or ""
        year_str = str(year) if year else ""
        resolution = parsed.resolution.upper() if parsed.resolution else "1080P"
        ext = parsed.container.lower()

        if template:
            try:
                rel_path = template.format(
                    title=title,
                    year=year_str,
                    resolution=resolution,
                    video_codec=parsed.video_codec or "",
                    audio_codec=parsed.audio_codec or "",
                    ext=ext,
                )
            except Exception:
                rel_path = f"{title} ({year_str})/{title} ({year_str}) [{resolution}].{ext}"
        else:
            if year_str:
                folder_name = f"{title} ({year_str})"
                file_name = f"{title} ({year_str}) [{resolution}].{ext}"
            else:
                folder_name = title
                file_name = f"{title} [{resolution}].{ext}"
            rel_path = posixpath.join(folder_name, file_name)

        return posixpath.normpath(posixpath.join(root_dir, rel_path))

    @classmethod
    def format_tv_path(
        cls,
        root_dir: str,
        tmdb: TMDBMediaResult,
        parsed: ParsedMediaInfo,
        episode_info: Optional[TMDBEpisodeInfo] = None,
        template: Optional[str] = None,
    ) -> str:
        """
        Format destination relative path for a TV episode.
        Default: {title} ({year})/Season {season:02d}/{title} - S{season:02d}E{episode:02d} - {episode_title}.{ext}
        """
        title = sanitize_filename(tmdb.title)
        year = tmdb.year or parsed.year or ""
        year_str = str(year) if year else ""
        season = parsed.season or 1
        episode = parsed.episode or 1
        resolution = parsed.resolution.upper() if parsed.resolution else "1080P"
        ext = parsed.container.lower()
        episode_title = (
            sanitize_filename(episode_info.name) if episode_info and episode_info.name else ""
        )

        if template:
            try:
                rel_path = template.format(
                    title=title,
                    year=year_str,
                    season=season,
                    episode=episode,
                    episode_title=episode_title,
                    resolution=resolution,
                    video_codec=parsed.video_codec or "",
                    audio_codec=parsed.audio_codec or "",
                    ext=ext,
                )
            except Exception:
                show_folder = f"{title} ({year_str})" if year_str else title
                season_folder = f"Season {season:02d}"
                if episode_title:
                    file_name = f"{title} - S{season:02d}E{episode:02d} - {episode_title}.{ext}"
                else:
                    file_name = f"{title} - S{season:02d}E{episode:02d}.{ext}"
                rel_path = posixpath.join(show_folder, season_folder, file_name)
        else:
            show_folder = f"{title} ({year_str})" if year_str else title
            season_folder = f"Season {season:02d}"
            if episode_title:
                file_name = f"{title} - S{season:02d}E{episode:02d} - {episode_title}.{ext}"
            else:
                file_name = f"{title} - S{season:02d}E{episode:02d}.{ext}"
            rel_path = posixpath.join(show_folder, season_folder, file_name)

        return posixpath.normpath(posixpath.join(root_dir, rel_path))
