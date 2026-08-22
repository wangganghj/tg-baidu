"""
Tests for Path and Filename Formatter (Plex / Emby standards).
"""

from tg_baidu.tmdb.client import TMDBEpisodeInfo, TMDBMediaResult
from tg_baidu.tmdb.formatter import PathFormatter, sanitize_filename
from tg_baidu.tmdb.parser import ParsedMediaInfo


def test_sanitize_filename():
    assert sanitize_filename("Avatar: The Way of Water") == "Avatar - The Way of Water"
    assert sanitize_filename("What/If?*<>|") == "What-If"
    assert sanitize_filename("  Clean   Title  ") == "Clean Title"


def test_format_movie_path():
    tmdb = TMDBMediaResult(
        id=872585,
        title="奥本海默",
        original_title="Oppenheimer",
        year=2023,
        media_type="movie",
        overview="...",
    )
    parsed = ParsedMediaInfo(
        raw_filename="Oppenheimer.2023.2160p.mkv",
        cleaned_title="Oppenheimer",
        year=2023,
        media_type="movie",
        resolution="2160p",
        container="mkv",
    )

    path = PathFormatter.format_movie_path("/Media/Movies", tmdb, parsed)
    assert path == "/Media/Movies/奥本海默 (2023)/奥本海默 (2023) [2160P].mkv"


def test_format_tv_path():
    tmdb = TMDBMediaResult(
        id=12345,
        title="繁花",
        original_title="Blossoms Shanghai",
        year=2023,
        media_type="tv",
        overview="...",
    )
    parsed = ParsedMediaInfo(
        raw_filename="繁花.S01E01.1080p.mp4",
        cleaned_title="繁花",
        year=2023,
        media_type="tv",
        season=1,
        episode=1,
        resolution="1080p",
        container="mp4",
    )
    ep_info = TMDBEpisodeInfo(
        episode_number=1,
        name="第一集",
        overview="...",
    )

    path = PathFormatter.format_tv_path("/Media/TV", tmdb, parsed, ep_info)
    assert path == "/Media/TV/繁花 (2023)/Season 01/繁花 - S01E01 - 第一集.mp4"
