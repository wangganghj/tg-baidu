"""
Parser for extracting Baidu Netdisk share links and extraction codes (pwd) from messages.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from typing import Optional


@dataclass
class BaiduShareLink:
    raw_text: str
    surl: str  # Short URL key (without '1' prefix if surl, or full short key)
    full_url: str
    pwd: str = ""

    @property
    def clean_share_url(self) -> str:
        return f"https://pan.baidu.com/s/1{self.surl.lstrip('1')}"


class BaiduShareParser:
    """Extracts Baidu Netdisk share URLs and extraction codes from raw text."""

    # Regex patterns for pan.baidu.com share links
    URL_PATTERN_S = re.compile(
        r"https?://pan\.baidu\.com/s/(1[a-zA-Z0-9_-]{5,25}|[a-zA-Z0-9_-]{5,25})",
        re.IGNORECASE,
    )
    URL_PATTERN_INIT = re.compile(
        r"https?://pan\.baidu\.com/share/init\?surl=([a-zA-Z0-9_-]{5,25})",
        re.IGNORECASE,
    )

    # Regex patterns for extraction codes (pwd/提取码/密码)
    PWD_PATTERNS = [
        re.compile(r"pwd=([a-zA-Z0-9]{4})", re.IGNORECASE),
        re.compile(r"提取码\s*[:：\s]*([a-zA-Z0-9]{4})", re.IGNORECASE),
        re.compile(r"密码\s*[:：\s]*([a-zA-Z0-9]{4})", re.IGNORECASE),
        re.compile(r"码\s*[:：\s]*([a-zA-Z0-9]{4})", re.IGNORECASE),
        re.compile(r"\b([a-zA-Z0-9]{4})\b"),
    ]

    @classmethod
    def parse(cls, text: str) -> Optional[BaiduShareLink]:
        """
        Parse first Baidu share link and extraction code from arbitrary text.
        """
        if not text:
            return None

        surl = ""
        full_url = ""
        pwd = ""

        # 1. Match /s/ link
        m_s = cls.URL_PATTERN_S.search(text)
        if m_s:
            full_match = m_s.group(0)
            raw_key = m_s.group(1)
            # Remove leading '1' if present for standard surl internal key
            surl = raw_key[1:] if raw_key.startswith("1") else raw_key
            full_url = full_match
        else:
            # 2. Match /share/init?surl= link
            m_init = cls.URL_PATTERN_INIT.search(text)
            if m_init:
                surl = m_init.group(1)
                full_url = m_init.group(0)

        if not surl:
            return None

        # 3. Check for pwd query parameter in URL (e.g. ?pwd=abcd)
        parsed_url = urllib.parse.urlparse(full_url)
        query_params = urllib.parse.parse_qs(parsed_url.query)
        if "pwd" in query_params and query_params["pwd"]:
            pwd = query_params["pwd"][0]

        # 4. Search in full text for extraction code patterns if not in URL query
        if not pwd:
            for pattern in cls.PWD_PATTERNS[:-1]:
                m_pwd = pattern.search(text)
                if m_pwd:
                    pwd = m_pwd.group(1)
                    break

        return BaiduShareLink(
            raw_text=text,
            surl=surl,
            full_url=full_url,
            pwd=pwd,
        )
