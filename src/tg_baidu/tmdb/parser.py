"""
Filename cleaner and metadata extractor using guessit and custom regex heuristics.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional
try:
    from guessit import guessit
except ImportError:
    guessit = None


# Regular expressions for common Chinese video ads, scrapers, and watermark junk
JUNK_PATTERNS = [
    r"【.*?公众号.*?】",
    r"【.*?首发.*?】",
    r"【.*?微信.*?】",
    r"【.*?分享.*?】",
    r"【.*?关注.*?】",
    r"\[.*?免费.*?\]",
    r"\[.*?网盘.*?\]",
    r"\[.*?首发.*?\]",
    r"\[.*?论坛.*?\]",
    r"www\.[a-zA-Z0-9_-]+\.(com|net|org|cn|cc|me|tv)",
    r"[a-zA-Z0-9_-]+\.(com|net|org|cn|cc|me|tv)",
    r"关注公众号[:：\s]*[\w\u4e00-\u9fa5]+",
    r"更多资源[:：\s]*[\w\u4e00-\u9fa5]+",
    r"高清无水印",
    r"国粤双语",
    r"国英双语",
    r"中英双字",
    r"中文字幕",
    r"双字",
    r"中字",
    r"60帧",
    r"120帧",
    r"高码版",
    r"抢先版",
    r"TC版",
    r"TC清晰版",
    r"HD中字",
    r"BD中字",
    r"HD高清",
    r"超清",
]

# Chinese / Anime Season and Episode patterns
CN_SEASON_PATTERN = re.compile(r"(?:第([0-9一二三四五六七八九十]+)季|\bS([0-9]{1,2})\b)", re.IGNORECASE)
CN_EPISODE_PATTERN = re.compile(
    r"(?:第\s*([0-9]{1,4})\s*[集话回期]|EP?\s*([0-9]{1,4})|\[([0-9]{1,4})\]|\bE([0-9]{1,4})\b|(?:\s*-\s*|\s+)(?:[0-9]{1,2})(?:\s*\[|\s*\.|\s+|$))",
    re.IGNORECASE,
)
ANIME_DASH_EPISODE_PATTERN = re.compile(r"(?:^|\s+)-\s+([0-9]{1,4})(?:\s*\[|\s*\.|\s+|$)", re.IGNORECASE)

# Supported Video Extensions
VIDEO_EXTENSIONS = {
    ".mkv",
    ".mp4",
    ".avi",
    ".mov",
    ".wmv",
    ".flv",
    ".m4v",
    ".ts",
    ".iso",
    ".strm",
}

# Chinese numerals to integers mapping
CN_NUM_MAP = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


@dataclass
class ParsedMediaInfo:
    raw_filename: str
    cleaned_title: str
    year: Optional[int] = None
    media_type: str = "movie"  # "movie" or "tv"
    season: int = 1
    episode: Optional[int] = None
    resolution: str = "1080p"
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    container: str = "mp4"
    is_video: bool = True


class MediaParser:
    """Intelligent media filename parser."""

    @classmethod
    def is_video_file(cls, filename: str) -> bool:
        ext = os.path.splitext(filename)[1].lower()
        return ext in VIDEO_EXTENSIONS

    @classmethod
    def clean_junk(cls, filename: str) -> str:
        """Remove ad texts, watermarks, domain names, and fullwidth bracket replacements."""
        name = filename
        # Replace fullwidth brackets and punctuation
        name = name.replace("（", "(").replace("）", ")").replace("【", "[").replace("】", "]")
        name = name.replace("：", ":").replace("，", ",").replace("／", "/")

        for pattern in JUNK_PATTERNS:
            name = re.sub(pattern, " ", name, flags=re.IGNORECASE)

        # Strip common release format noise words
        name = re.sub(
            r"\b(NF|DV&HDR|DV|HDR10|HDR|WEB-DL|WEBRip|BluRay|HDTV|BD|HD|TC|H\.?26[45]|HEVC|AVC|1080p|2160p|4K|720p|AAC|DDP|Atmos|Complete|FLAC)\b",
            " ",
            name,
            flags=re.IGNORECASE,
        )

        # Collapse repeated spaces/dots/underscores
        name = re.sub(r"[\s_.]+", " ", name).strip()
        return name

    @classmethod
    def _parse_chinese_season(cls, text: str) -> Optional[int]:
        m = CN_SEASON_PATTERN.search(text)
        if m:
            for val in m.groups():
                if val:
                    if val.isdigit():
                        return int(val)
                    if val in CN_NUM_MAP:
                        return CN_NUM_MAP[val]
        return None

    @classmethod
    def _parse_chinese_episode(cls, text: str) -> Optional[int]:
        m = CN_EPISODE_PATTERN.search(text)
        if m:
            for g in m.groups():
                if g and g.isdigit():
                    return int(g)
        m2 = ANIME_DASH_EPISODE_PATTERN.search(text)
        if m2:
            return int(m2.group(1))
        return None

    @classmethod
    def parse_filename(cls, filename: str) -> ParsedMediaInfo:
        """
        Parse raw filename into structured metadata.
        """
        base_name, ext = os.path.splitext(filename)
        container = ext.lstrip(".").lower() or "mp4"
        is_video = cls.is_video_file(filename)

        cleaned_name = cls.clean_junk(base_name)

        # Run guessit for deep metadata extraction
        guessed: dict = {}
        try:
            guessed = dict(guessit(cleaned_name))
        except Exception:
            guessed = {}

        # 1. Title
        title = guessed.get("title") or cleaned_name
        # Strip trailing dot / dash / brackets
        title = re.sub(r"[\[\(\{\]\)\}]", " ", str(title)).strip()

        # 2. Year
        year = guessed.get("year")
        if isinstance(year, list) and len(year) > 0:
            year = year[0]
        if not year:
            # Fallback regex for 4-digit year 1920-2099
            ym = re.search(r"\b(19\d{2}|20\d{2})\b", cleaned_name)
            if ym:
                year = int(ym.group(1))

        # 3. Media Type (Movie vs TV)
        media_type = "movie"
        guess_type = guessed.get("type")
        if guess_type == "episode":
            media_type = "tv"

        # Check Chinese Season / Episode
        cn_season = cls._parse_chinese_season(cleaned_name)
        cn_episode = cls._parse_chinese_episode(cleaned_name)

        season = guessed.get("season", 1)
        if isinstance(season, list) and len(season) > 0:
            season = season[0]
        if cn_season is not None:
            season = cn_season
            media_type = "tv"

        episode = guessed.get("episode")
        if isinstance(episode, list) and len(episode) > 0:
            episode = episode[0]
        if cn_episode is not None:
            episode = cn_episode
            media_type = "tv"

        if episode is not None:
            media_type = "tv"

        # 4. Resolution
        res = guessed.get("screen_size")
        if not res:
            if re.search(r"\b(4k|2160p|uhd)\b", cleaned_name, re.I):
                res = "2160p"
            elif re.search(r"\b(1080p|fhd)\b", cleaned_name, re.I):
                res = "1080p"
            elif re.search(r"\b(720p|hd)\b", cleaned_name, re.I):
                res = "720p"
            else:
                res = "1080p"

        # 5. Codecs
        video_codec = guessed.get("video_codec")
        audio_codec = guessed.get("audio_codec")

        # Further cleanup title if it still has "第X季" or year embedded
        if title:
            title = CN_SEASON_PATTERN.sub("", title)
            title = CN_EPISODE_PATTERN.sub("", title)
            if year:
                title = re.sub(rf"\b{year}\b", "", title)
            title = re.sub(r"[\s_.]+", " ", title).strip()

        return ParsedMediaInfo(
            raw_filename=filename,
            cleaned_title=title or cleaned_name,
            year=year,
            media_type=media_type,
            season=season or 1,
            episode=episode,
            resolution=str(res).lower(),
            video_codec=str(video_codec) if video_codec else None,
            audio_codec=str(audio_codec) if audio_codec else None,
            container=container,
            is_video=is_video,
        )
