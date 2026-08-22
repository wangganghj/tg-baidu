"""
Tests for Baidu Netdisk share link parsing.
"""

from tg_baidu.baidu.share_parser import BaiduShareParser


def test_parse_standard_s_link_with_pwd():
    text = "链接: https://pan.baidu.com/s/1abcdEFG12345 提取码: 8888 复制这段内容后打开百度网盘手机App"
    parsed = BaiduShareParser.parse(text)

    assert parsed is not None
    assert parsed.surl == "abcdEFG12345"
    assert parsed.pwd == "8888"
    assert parsed.clean_share_url == "https://pan.baidu.com/s/1abcdEFG12345"


def test_parse_url_with_pwd_query():
    text = "https://pan.baidu.com/s/1xyz987654321?pwd=abcd"
    parsed = BaiduShareParser.parse(text)

    assert parsed is not None
    assert parsed.surl == "xyz987654321"
    assert parsed.pwd == "abcd"


def test_parse_init_surl_link():
    text = "https://pan.baidu.com/share/init?surl=kLmNoPqRsTuV 密码: 6666"
    parsed = BaiduShareParser.parse(text)

    assert parsed is not None
    assert parsed.surl == "kLmNoPqRsTuV"
    assert parsed.pwd == "6666"


def test_parse_invalid_text():
    assert BaiduShareParser.parse("hello world https://google.com") is None
    assert BaiduShareParser.parse("") is None
