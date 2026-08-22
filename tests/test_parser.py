"""
Tests for Media Parser (guessit + custom regex heuristics).
"""

import pytest
from tg_baidu.tmdb.parser import MediaParser


def test_clean_junk():
    text = "【最新电影首发微信公众号xxx】流浪地球2.2023.HD1080P.国英双语.中英双字.mp4"
    cleaned = MediaParser.clean_junk(text)
    assert "微信公众号" not in cleaned
    assert "国英双语" not in cleaned
    assert "中英双字" not in cleaned
    assert "流浪地球2" in cleaned or "流浪地球" in cleaned


def test_parse_movie_filename():
    filename = "Oppenheimer.2023.2160p.UHD.BluRay.x265.mkv"
    parsed = MediaParser.parse_filename(filename)

    assert parsed.is_video is True
    assert parsed.year == 2023
    assert parsed.media_type == "movie"
    assert parsed.resolution == "2160p"
    assert parsed.container == "mkv"
    assert "Oppenheimer" in parsed.cleaned_title


def test_parse_chinese_movie_with_ads():
    filename = "【免费首发】沙丘2.Dune.Part.Two.2024.1080p.TC中字.mp4"
    parsed = MediaParser.parse_filename(filename)

    assert parsed.is_video is True
    assert parsed.year == 2024
    assert parsed.media_type == "movie"
    assert parsed.resolution == "1080p"
    assert parsed.container == "mp4"


def test_parse_tv_episode():
    filename = "Stranger.Things.S04E01.1080p.NF.WEB-DL.x264.mkv"
    parsed = MediaParser.parse_filename(filename)

    assert parsed.media_type == "tv"
    assert parsed.season == 4
    assert parsed.episode == 1
    assert parsed.resolution == "1080p"
    assert parsed.container == "mkv"


def test_parse_chinese_tv_show():
    filename = "繁花.2023.第03集.4K.WEB-DL.H265.AAC.mp4"
    parsed = MediaParser.parse_filename(filename)

    assert parsed.media_type == "tv"
    assert parsed.season == 1
    assert parsed.episode == 3
    assert parsed.resolution == "2160p" or parsed.resolution == "4k"
    assert "繁花" in parsed.cleaned_title


def test_parse_chinese_multi_season():
    filename = "庆余年.第二季.第08集.1080p.mp4"
    parsed = MediaParser.parse_filename(filename)

    assert parsed.media_type == "tv"
    assert parsed.season == 2
    assert parsed.episode == 8


def test_is_video_file():
    assert MediaParser.is_video_file("test.mp4") is True
    assert MediaParser.is_video_file("test.mkv") is True
    assert MediaParser.is_video_file("test.srt") is False
    assert MediaParser.is_video_file("test.nfo") is False
    assert MediaParser.is_video_file("test.txt") is False
