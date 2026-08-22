"""
Telegram Bot Inline Keyboard Builders.
"""

from __future__ import annotations

from typing import List
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..tmdb.client import TMDBMediaResult


def build_media_confirmation_keyboard(
    session_id: str,
    tmdb: TMDBMediaResult,
    current_type: str,  # "movie" or "tv"
) -> InlineKeyboardMarkup:
    """Build confirmation buttons for a detected media share."""
    switch_label = "📺 切换为电视剧" if current_type == "movie" else "🎬 切换为电影"
    next_type = "tv" if current_type == "movie" else "movie"

    keyboard = [
        [
            InlineKeyboardButton(
                "✅ 确认识别并转存",
                callback_data=f"confirm:{session_id}:{current_type}:{tmdb.id}",
            )
        ],
        [
            InlineKeyboardButton(
                switch_label,
                callback_data=f"switch:{session_id}:{next_type}:{tmdb.id}",
            ),
            InlineKeyboardButton(
                "🔍 更多匹配结果",
                callback_data=f"more:{session_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                "❌ 取消",
                callback_data=f"cancel:{session_id}",
            )
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_search_selection_keyboard(
    session_id: str,
    results: List[TMDBMediaResult],
) -> InlineKeyboardMarkup:
    """Build list of search candidates for user to choose from."""
    keyboard = []
    for idx, item in enumerate(results[:5], start=1):
        type_icon = "🎬" if item.media_type == "movie" else "📺"
        year_str = f" ({item.year})" if item.year else ""
        button_text = f"{idx}. {type_icon} {item.title}{year_str}"
        keyboard.append(
            [
                InlineKeyboardButton(
                    button_text,
                    callback_data=f"select:{session_id}:{item.media_type}:{item.id}",
                )
            ]
        )

    keyboard.append([InlineKeyboardButton("❌ 取消", callback_data=f"cancel:{session_id}")])
    return InlineKeyboardMarkup(keyboard)


def build_settings_keyboard(
    auto_transfer: bool,
    tmdb_lang: str,
) -> InlineKeyboardMarkup:
    """Build interactive settings menu."""
    auto_label = "⚡ 自动转存: [已开启]" if auto_transfer else "⚡ 自动转存: [已关闭]"
    keyboard = [
        [
            InlineKeyboardButton(
                auto_label,
                callback_data="set_toggle_auto",
            )
        ],
        [
            InlineKeyboardButton(
                f"🌐 TMDB 语言: {tmdb_lang}",
                callback_data="set_lang",
            )
        ],
        [
            InlineKeyboardButton(
                "📁 电影目录",
                callback_data="set_movie_dir",
            ),
            InlineKeyboardButton(
                "📁 剧集目录",
                callback_data="set_tv_dir",
            ),
        ],
        [
            InlineKeyboardButton("❌ 关闭菜单", callback_data="close_settings"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)
