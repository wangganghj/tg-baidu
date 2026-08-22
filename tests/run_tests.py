import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# Mock third party modules if not present in standard library environment
for mod in [
    "httpx", "aiosqlite", "yaml", "pydantic", "telegram", "telegram.ext",
    "telegram.constants", "rich", "rich.logging", "fastapi", "fastapi.middleware.cors",
    "fastapi.responses", "fastapi.templating", "uvicorn", "jinja2"
]:
    if mod not in sys.modules:
        try:
            __import__(mod)
        except ImportError:
            sys.modules[mod] = MagicMock()

# Add src and tests to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from tg_baidu.tmdb.formatter import sanitize_filename, PathFormatter
from tg_baidu.tmdb.client import TMDBMediaResult, TMDBEpisodeInfo
from tg_baidu.tmdb.parser import MediaParser, ParsedMediaInfo
from tg_baidu.baidu.share_parser import BaiduShareParser


class TestCoreLogic(unittest.TestCase):

    def test_clean_junk(self):
        text = "【最新电影首发微信公众号xxx】流浪地球2.2023.HD1080P.国英双语.中英双字.mp4"
        cleaned = MediaParser.clean_junk(text)
        self.assertNotIn("微信公众号", cleaned)
        self.assertNotIn("国英双语", cleaned)
        self.assertNotIn("中英双字", cleaned)

    def test_sanitize_filename(self):
        self.assertEqual(sanitize_filename("Avatar: The Way of Water"), "Avatar - The Way of Water")
        self.assertEqual(sanitize_filename("What/If?*<>|"), "What-If")
        self.assertEqual(sanitize_filename("  Clean   Title  "), "Clean Title")

    def test_format_movie_path(self):
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
        self.assertEqual(path, "/Media/Movies/奥本海默 (2023)/奥本海默 (2023) [2160P].mkv")

    def test_format_tv_path(self):
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
        self.assertEqual(path, "/Media/TV/繁花 (2023)/Season 01/繁花 - S01E01 - 第一集.mp4")

    def test_parse_chinese_tv_show(self):
        filename = "繁花.2023.第03集.4K.WEB-DL.H265.AAC.mp4"
        parsed = MediaParser.parse_filename(filename)
        self.assertEqual(parsed.media_type, "tv")
        self.assertEqual(parsed.season, 1)
        self.assertEqual(parsed.episode, 3)
        self.assertTrue("繁花" in parsed.cleaned_title)

    def test_parse_chinese_multi_season(self):
        filename = "庆余年.第二季.第08集.1080p.mp4"
        parsed = MediaParser.parse_filename(filename)
        self.assertEqual(parsed.media_type, "tv")
        self.assertEqual(parsed.season, 2)
        self.assertEqual(parsed.episode, 8)

    def test_parse_anime(self):
        filename = "[Lilith-Raws] 葬送的芙莉莲 - 01 [1080p].mp4"
        parsed = MediaParser.parse_filename(filename)
        self.assertEqual(parsed.media_type, "tv")
        self.assertEqual(parsed.episode, 1)

    def test_custom_format_templates(self):
        tmdb = TMDBMediaResult(
            id=100,
            title="Inception",
            original_title="Inception",
            year=2010,
            media_type="movie",
            overview="...",
        )
        parsed = ParsedMediaInfo(
            raw_filename="Inception.2010.1080p.mp4",
            cleaned_title="Inception",
            year=2010,
            media_type="movie",
            resolution="1080p",
            container="mp4",
        )
        custom_tpl = "{year}/{title}/{title}.{ext}"
        path = PathFormatter.format_movie_path("/Movies", tmdb, parsed, template=custom_tpl)
        self.assertEqual(path, "/Movies/2010/Inception/Inception.mp4")

    def test_baidu_share_link_parsing(self):
        # 1. Standard share text
        text1 = "链接: https://pan.baidu.com/s/1abcdEFG12345 提取码: 8888 复制这段内容后打开百度网盘手机App"
        p1 = BaiduShareParser.parse(text1)
        self.assertIsNotNone(p1)
        self.assertEqual(p1.surl, "abcdEFG12345")
        self.assertEqual(p1.pwd, "8888")
        self.assertEqual(p1.clean_share_url, "https://pan.baidu.com/s/1abcdEFG12345")

        # 2. URL with ?pwd=
        text2 = "https://pan.baidu.com/s/1xyz987654321?pwd=abcd"
        p2 = BaiduShareParser.parse(text2)
        self.assertIsNotNone(p2)
        self.assertEqual(p2.surl, "xyz987654321")
        self.assertEqual(p2.pwd, "abcd")

        # 3. Share init url
        text3 = "https://pan.baidu.com/share/init?surl=kLmNoPqRsTuV 密码: 6666"
        p3 = BaiduShareParser.parse(text3)
        self.assertIsNotNone(p3)
        self.assertEqual(p3.surl, "kLmNoPqRsTuV")
        self.assertEqual(p3.pwd, "6666")


if __name__ == "__main__":
    unittest.main()
