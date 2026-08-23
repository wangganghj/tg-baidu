"""
Parser for extracting Baidu Netdisk share links and extraction codes (pwd) from Telegram messages and complex text.
Supports Markdown, MarkdownV2, HTML formatted text, hidden hyperlinked entities, and forwarded channel messages.
"""

from __future__ import annotations

import html
import re
import urllib.parse
from dataclasses import dataclass
from typing import Optional


@dataclass
class BaiduShareLink:
    raw_text: str
    surl: str  # Short URL key (without '1' prefix if standard surl)
    full_url: str
    pwd: str = ""

    @property
    def clean_share_url(self) -> str:
        return f"https://pan.baidu.com/s/1{self.surl.lstrip('1')}"


class BaiduShareParser:
    """Extracts Baidu Netdisk share URLs and extraction codes from raw text or forwarded messages."""

    # Regex patterns for pan.baidu.com / yun.baidu.com share links
    URL_PATTERN_S = re.compile(
        r"(?:https?://)?(?:pan|yun)\.baidu\.com/s/([a-zA-Z0-9_-]+)",
        re.IGNORECASE,
    )
    URL_PATTERN_INIT = re.compile(
        r"(?:https?://)?(?:pan|yun)\.baidu\.com/share/init\?([^\s\)\'\"\]]+)",
        re.IGNORECASE,
    )

    # Regex patterns for extraction codes (pwd/提取码/密码/访问码/code)
    PWD_PATTERNS = [
        re.compile(r"[?&]pwd=([a-zA-Z0-9]{4})", re.IGNORECASE),
        re.compile(r"(?:提取码|提取密码|访问码|密码|提取|pwd|code|码)[:：\s=]*([a-zA-Z0-9]{4})\b", re.IGNORECASE),
    ]

    @classmethod
    def preprocess_rich_text(cls, text: str) -> str:
        """
        Normalize Telegram rich-text formats (HTML tags, Markdown links, MarkdownV2 escapes).
        """
        if not text:
            return ""

        # 1. Unescape HTML entities (&amp;, &quot;, &#39;, &lt;, &gt;, etc.)
        t = html.unescape(text)

        # 2. Extract URLs from HTML <a> tags: <a href='...'>...</a> -> ... url
        t = re.sub(r'<a\s+(?:[^>]*?\s+)?href=[\'"]([^\'"]+)[\'"][^>]*>(.*?)</a>', r"\2 \1", t, flags=re.I | re.S)

        # 3. Extract URLs from Markdown / MarkdownV2 links: [text](url) -> text url
        t = re.sub(r"\[([^\]]+)\]\(([^\)]+)\)", r"\1 \2", t)

        # 4. Remove MarkdownV2 backslash escapes (e.g. pan\.baidu\.com -> pan.baidu.com)
        t = re.sub(r"\\([._*\[\]()~`>#+\-=|{}!])", r"\1", t)

        return t

    @classmethod
    def parse(cls, text: str) -> Optional[BaiduShareLink]:
        """
        Parse first Baidu share link and extraction code from arbitrary text or forwarded message.
        Supports HTML, Markdown, and MarkdownV2 syntax.
        """
        if not text:
            return None

        # Preprocess rich text formatting
        normalized_text = cls.preprocess_rich_text(text)

        surl = ""
        full_url = ""
        pwd = ""

        # 1. Match /s/ link on pan.baidu.com or yun.baidu.com
        m_s = cls.URL_PATTERN_S.search(normalized_text)
        if m_s:
            full_match = m_s.group(0)
            raw_key = m_s.group(1)
            # Normalize short key (strip leading '1' for internal standard surl key)
            surl = raw_key[1:] if raw_key.startswith("1") else raw_key
            full_url = full_match if full_match.startswith("http") else f"https://{full_match}"
        else:
            # 2. Match /share/init?surl= link
            m_init = cls.URL_PATTERN_INIT.search(normalized_text)
            if m_init:
                raw_init_url = m_init.group(0)
                full_url = raw_init_url if raw_init_url.startswith("http") else f"https://{raw_init_url}"
                parsed_url = urllib.parse.urlparse(full_url)
                query_params = urllib.parse.parse_qs(parsed_url.query)
                if "surl" in query_params and query_params["surl"]:
                    raw_key = query_params["surl"][0]
                    surl = raw_key[1:] if raw_key.startswith("1") else raw_key

        if not surl:
            return None

        # 3. Extract pwd from URL query or text patterns
        for pattern in cls.PWD_PATTERNS:
            m_pwd = pattern.search(normalized_text)
            if m_pwd:
                pwd = m_pwd.group(1)
                break

        return BaiduShareLink(
            raw_text=text,
            surl=surl,
            full_url=full_url,
            pwd=pwd,
        )
