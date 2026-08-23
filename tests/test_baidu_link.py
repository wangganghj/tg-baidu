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


def test_parse_forwarded_telegram_post():
    tg_post = """
    🎬 【韩剧】藏.锋（2026） 4K 60fps 完结
    📢 频道：@channel_name
    🔗 百度网盘链接：https://pan.baidu.com/s/1S31dvBIG1xBKEQaIrI6Eqw?pwd=zk77
    💬 简介：这是一部韩剧
    """
    parsed = BaiduShareParser.parse(tg_post)
    assert parsed is not None
    assert parsed.surl == "S31dvBIG1xBKEQaIrI6Eqw"
    assert parsed.pwd == "zk77"
    assert parsed.clean_share_url == "https://pan.baidu.com/s/1S31dvBIG1xBKEQaIrI6Eqw"


def test_parse_multiline_resource_post():
    tg_post = """
    资源名称：藏锋 (2026) 4K 高码版
    百度网盘：https://pan.baidu.com/s/1925dmULsLd8tafD0TW8Vew 提取码：qxn3
    阿里网盘：https://www.alipan.com/...
    """
    parsed = BaiduShareParser.parse(tg_post)
    assert parsed is not None
    assert parsed.surl == "925dmULsLd8tafD0TW8Vew"
    assert parsed.pwd == "qxn3"


def test_parse_markdown_link():
    md_post = """
    🎬 *藏锋* (2026) 4K
    📥 下载链接: [百度网盘](https://pan.baidu.com/s/1S31dvBIG1xBKEQaIrI6Eqw?pwd=zk77)
    """
    parsed = BaiduShareParser.parse(md_post)
    assert parsed is not None
    assert parsed.surl == "S31dvBIG1xBKEQaIrI6Eqw"
    assert parsed.pwd == "zk77"


def test_parse_markdownv2_link():
    mdv2_post = r"""
    🎬 \*藏锋\* \(2026\) 4K
    📥 下载链接: [百度网盘](https://pan\.baidu\.com/s/1S31dvBIG1xBKEQaIrI6Eqw?pwd=zk77)
    """
    parsed = BaiduShareParser.parse(mdv2_post)
    assert parsed is not None
    assert parsed.surl == "S31dvBIG1xBKEQaIrI6Eqw"
    assert parsed.pwd == "zk77"


def test_parse_html_link():
    html_post = """
    <b>🎬 藏锋 (2026) 4K</b>
    <a href="https://pan.baidu.com/share/init?surl=S31dvBIG1xBKEQaIrI6Eqw&amp;pwd=zk77">👉 点击转存百度网盘</a>
    """
    parsed = BaiduShareParser.parse(html_post)
    assert parsed is not None
    assert parsed.surl == "S31dvBIG1xBKEQaIrI6Eqw"
    assert parsed.pwd == "zk77"
