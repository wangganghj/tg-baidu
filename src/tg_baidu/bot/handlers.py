"""
Telegram Bot Command and Message Handlers.
"""

from __future__ import annotations

import html
import logging
import uuid
from typing import Any, Dict, List, Optional
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from ..baidu.auth import BaiduAuthManager
from ..baidu.client import BaiduClient
from ..baidu.share_parser import BaiduShareParser
from ..config import Config
from ..core.database import Database
from ..core.task_manager import TransferTaskManager
from ..tmdb.client import TMDBClient, TMDBMediaResult
from ..tmdb.parser import MediaParser
from .keyboards import (
    build_media_confirmation_keyboard,
    build_search_selection_keyboard,
    build_settings_keyboard,
)

logger = logging.getLogger(__name__)


class BotHandlers:
    """Encapsulates all Telegram Bot command, message, and callback handlers."""

    def __init__(
        self,
        config: Config,
        db: Database,
        auth_manager: BaiduAuthManager,
        baidu_client: BaiduClient,
        tmdb_client: TMDBClient,
        task_manager: TransferTaskManager,
    ):
        self.config = config
        self.db = db
        self.auth_manager = auth_manager
        self.baidu_client = baidu_client
        self.tmdb_client = tmdb_client
        self.task_manager = task_manager
        # In-memory temporary cache for active inline sessions
        self._sessions: Dict[str, Dict[str, Any]] = {}

    def _is_user_allowed(self, user_id: int) -> bool:
        """Check if user has permission to use the bot."""
        allowed = self.config.telegram.allowed_user_ids
        if not allowed:
            return True
        return user_id in allowed or user_id == self.config.telegram.admin_user_id

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        user = update.effective_user
        if not self._is_user_allowed(user.id):
            await update.message.reply_text("⛔ 您没有使用此机器人的权限。")
            return

        welcome_text = (
            f"👋 <b>你好，{html.escape(user.first_name)}！</b>\n\n"
            f"欢迎使用 <b>tg-baidu</b> 百度网盘智能转存机器人。\n\n"
            f"✨ <b>主要功能</b>：\n"
            f"• 自动识别聊天中的百度网盘分享链接与提取码\n"
            f"• 接入 TMDB 自动智能匹配电影/剧集信息\n"
            f"• 按照 Plex / Emby / Jellyfin 规范重命名并自动归档\n\n"
            f"💡 <b>快速开始</b>：\n"
            f"1. 输入 /login 绑定百度网盘账号\n"
            f"2. 输入 /status 查看网盘空间与授权状态\n"
            f"3. 直接发送<b>百度网盘分享链接</b>即可开始转存！\n\n"
            f"输入 /help 查看所有可用命令。"
        )
        await update.message.reply_text(welcome_text, parse_mode=ParseMode.HTML)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command."""
        user = update.effective_user
        if not self._is_user_allowed(user.id):
            return

        help_text = (
            "📖 <b>tg-baidu 使用指南</b>\n\n"
            "<b>基本命令</b>：\n"
            "• /login - 获取百度网盘 OAuth2 授权链接\n"
            "• /code &lt;授权码&gt; - 提交授权码完成绑定\n"
            "• /status - 查看账号信息与百度网盘存储配额\n"
            "• /settings - 个人偏好设置（目录、TMDB语言、自动转存）\n"
            "• /tasks - 查看最近的转存与整理任务\n"
            "• /search &lt;关键词&gt; - 手动搜索 TMDB 影视条目\n"
            "• /help - 查看本帮助信息\n\n"
            "<b>转存使用方式</b>：\n"
            "直接在对话框发送包含百度网盘链接的消息，例如：\n"
            "<code>链接: https://pan.baidu.com/s/1xxxx 提取码: abcd 繁花.2023.4K</code>\n\n"
            "机器人会自动解析链接、提取影视名称并在 TMDB 检索，随后提供交互按钮供你确认。"
        )
        await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)

    async def login_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /login or /auth command."""
        user = update.effective_user
        if not self._is_user_allowed(user.id):
            return

        auth_url = self.auth_manager.get_authorization_url()
        text = (
            "🔐 <b>百度网盘 OAuth2 授权绑定</b>\n\n"
            "1. 点击下方链接在浏览器中打开并登录百度账号完成授权：\n"
            f"👉 <a href=\"{auth_url}\"><b>点击此处前往百度授权页面</b></a>\n\n"
            "2. 授权成功后，页面会显示一串 <b>授权码 (Authorization Code)</b>。\n"
            "3. 复制该授权码，并在本聊天框发送：\n"
            "<code>/code 你的授权码</code>"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    async def code_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /code <code> command."""
        user = update.effective_user
        if not self._is_user_allowed(user.id):
            return

        if not context.args:
            await update.message.reply_text(
                "⚠️ 请提供授权码，格式：\n<code>/code 你的授权码</code>",
                parse_mode=ParseMode.HTML,
            )
            return

        code = context.args[0].strip()
        status_msg = await update.message.reply_text("⏳ 正在与百度开放平台通信，交换访问令牌...")

        try:
            await self.auth_manager.exchange_code(code)
            uinfo = await self.baidu_client.get_user_info()
            quota = await self.baidu_client.get_quota()

            text = (
                "✅ <b>百度网盘账号绑定成功！</b>\n\n"
                f"👤 <b>用户名</b>: {html.escape(uinfo.baidu_name)} ({uinfo.vip_label})\n"
                f"💾 <b>网盘空间</b>: 已用 {quota.used_gb} GB / 总共 {quota.total_gb} GB\n\n"
                "现在您可以直接发送百度网盘分享链接进行转存与整理了！"
            )
            await status_msg.edit_text(text, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.exception("Failed to exchange code: %s", e)
            await status_msg.edit_text(f"❌ 绑定失败: {e}\n请确认授权码是否正确或已过期，重新使用 /login 获取。")

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /status command."""
        user = update.effective_user
        if not self._is_user_allowed(user.id):
            return

        status_msg = await update.message.reply_text("⏳ 正在获取网盘与系统状态...")

        try:
            uinfo = await self.baidu_client.get_user_info()
            quota = await self.baidu_client.get_quota()
            usage_percent = round((quota.used / quota.total * 100), 1) if quota.total > 0 else 0

            text = (
                "📊 <b>系统与网盘状态</b>\n\n"
                f"👤 <b>百度账号</b>: {html.escape(uinfo.baidu_name)}\n"
                f"🎖 <b>会员等级</b>: {uinfo.vip_label}\n"
                f"💽 <b>网盘空间</b>: {quota.used_gb} GB / {quota.total_gb} GB ({usage_percent}%)\n"
                f"🆓 <b>剩余空间</b>: {quota.free_gb} GB\n\n"
                f"🎬 <b>电影默认目录</b>: <code>{self.config.media.movie_dir}</code>\n"
                f"📺 <b>剧集默认目录</b>: <code>{self.config.media.tv_dir}</code>\n"
                f"🌐 <b>TMDB 语言</b>: <code>{self.config.tmdb.language}</code>"
            )
            await status_msg.edit_text(text, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.warning("Status check failed: %s", e)
            await status_msg.edit_text(
                f"⚠️ <b>未能获取百度网盘状态</b>\n\n"
                f"错误信息: {e}\n"
                f"💡 请先使用 /login 完成百度网盘 OAuth 绑定。"
            )

    async def settings_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /settings command."""
        user = update.effective_user
        if not self._is_user_allowed(user.id):
            return

        settings = await self.db.get_user_settings(user.id)
        auto_transfer = bool(settings.get("auto_transfer", self.config.media.auto_transfer))
        tmdb_lang = settings.get("tmdb_language", self.config.tmdb.language)

        text = (
            "⚙️ <b>偏好设置</b>\n\n"
            f"• <b>自动转存</b>: {'✅ 已开启 (无需手动确认)' if auto_transfer else '❌ 已关闭 (每次手动确认)'}\n"
            f"• <b>TMDB 刮削语言</b>: <code>{tmdb_lang}</code>\n"
            f"• <b>电影保存目录</b>: <code>{settings.get('movie_dir') or self.config.media.movie_dir}</code>\n"
            f"• <b>剧集保存目录</b>: <code>{settings.get('tv_dir') or self.config.media.tv_dir}</code>\n\n"
            "点击下方按钮进行切换或配置："
        )
        kb = build_settings_keyboard(auto_transfer, tmdb_lang)
        await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

    async def tasks_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /tasks command."""
        user = update.effective_user
        if not self._is_user_allowed(user.id):
            return

        tasks = await self.db.get_user_tasks(user.id, limit=8)
        if not tasks:
            await update.message.reply_text("📋 暂无转存与整理任务记录。")
            return

        status_icons = {
            "PENDING": "⏳ 等待中",
            "PROCESSING": "🔄 处理中",
            "COMPLETED": "✅ 已完成",
            "FAILED": "❌ 失败",
        }

        lines = ["📋 <b>最近任务记录</b>\n"]
        for t in tasks:
            status_str = status_icons.get(t["status"], t["status"])
            title = t.get("tmdb_title") or "未知媒体"
            year_str = f" ({t.get('year')})" if t.get("year") else ""
            lines.append(
                f"• <code>{t['task_id']}</code> | {status_str}\n"
                f"  🎬 {html.escape(title)}{year_str} [{t.get('media_type', '').upper()}]\n"
                f"  📊 文件: {t.get('processed_files', 0)}/{t.get('total_files', 0)}"
            )

        await update.message.reply_text("\n\n".join(lines), parse_mode=ParseMode.HTML)

    async def search_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /search <query>."""
        user = update.effective_user
        if not self._is_user_allowed(user.id):
            return

        if not context.args:
            await update.message.reply_text("用法: `/search <电影或剧集名称>`", parse_mode=ParseMode.MARKDOWN)
            return

        query = " ".join(context.args)
        status_msg = await update.message.reply_text(f"🔍 正在 TMDB 搜索: `{query}`...", parse_mode=ParseMode.MARKDOWN)

        try:
            results = await self.tmdb_client.search_multi(query)
            if not results:
                await status_msg.edit_text(f"未找到与 `{query}` 相关的影视条目。")
                return

            lines = [f"🔍 <b>TMDB 搜索结果:</b> <code>{html.escape(query)}</code>\n"]
            for idx, item in enumerate(results[:5], start=1):
                type_name = "电影" if item.media_type == "movie" else "电视剧"
                year_str = f" ({item.year})" if item.year else ""
                lines.append(
                    f"{idx}. <b>{html.escape(item.title)}</b>{year_str} [{type_name}]\n"
                    f"   TMDB ID: <code>{item.id}</code> | 评分: ⭐ {item.vote_average}\n"
                    f"   <i>{html.escape((item.overview[:60] + '...') if item.overview else '无简介')}</i>"
                )

            await status_msg.edit_text("\n\n".join(lines), parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.exception("Search failed: %s", e)
            await status_msg.edit_text(f"搜索失败: {e}")

    async def on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Process incoming messages to detect Baidu Pan share links (including forwarded Telegram posts)."""
        user = update.effective_user
        msg = update.message
        if not user or not msg or not self._is_user_allowed(user.id):
            return

        # 1. Extract complete text from message, caption, and embedded hyperlinks
        full_text = msg.text or msg.caption or ""
        all_entities = list(msg.entities or []) + list(msg.caption_entities or [])
        for ent in all_entities:
            if ent.type == "text_link" and ent.url:
                full_text += f"\n{ent.url}"

        if not full_text:
            return

        # 2. Parse Baidu share link & extraction code
        share_link = BaiduShareParser.parse(full_text)
        if not share_link:
            return  # Not a baidu share link message

        status_msg = await update.message.reply_text("🔍 检测到百度网盘分享链接，正在解析媒体信息...")

        try:
            # 3. Extract media title candidate from forwarded/complex message text
            import re
            lines = [l.strip() for l in full_text.splitlines() if l.strip()]
            candidate_titles = []
            for line in lines:
                if "baidu.com" in line.lower() or "pan.baidu" in line.lower():
                    continue
                if any(k in line for k in ("@", "频道", "群组", "关注", "交流", "http://", "https://")):
                    continue
                if any(k in line for k in ("简介", "介绍", "剧情", "夸克", "阿里", "迅雷", "115", "UC")):
                    continue
                # Strip leading tags (e.g. 资源名称：, 片名：, 剧名：)
                clean_l = re.sub(r"^(?:资源名称|影视名称|片名|剧名|名称|标题)[:：\s]*", "", line).strip()
                if clean_l:
                    candidate_titles.append(clean_l)

            raw_title = candidate_titles[0] if candidate_titles else ""
            detected_type = "auto"
            detected_year = None

            if not raw_title:
                # If no clear title line in message, inspect share content from Baidu Netdisk
                share_info = await self.baidu_client.get_share_content_info(share_link.clean_share_url, share_link.pwd)
                if share_info and share_info.get("items"):
                    first_item = share_info["items"][0]
                    raw_title = first_item.get("server_filename") or share_info.get("title", "")
                    if first_item.get("isdir") in (1, "1", True) or "剧" in share_info.get("title", ""):
                        detected_type = "tv"
                elif share_info and share_info.get("title"):
                    raw_title = share_info.get("title", "")

            if not raw_title:
                raw_title = full_text

            clean_raw = raw_title.split("/")[-1]
            parsed_media = MediaParser.parse_filename(clean_raw)
            search_query = parsed_media.cleaned_title or clean_raw
            if parsed_media.year:
                detected_year = parsed_media.year
            if detected_type == "auto":
                detected_type = parsed_media.media_type

            # 3. Search TMDB
            best_match = None
            results = []
            if getattr(self.tmdb_client, "api_key", None) and search_query and not search_query.startswith("http"):
                try:
                    results = await self.tmdb_client.search_multi(
                        query=search_query,
                        media_type=detected_type if detected_type in ("movie", "tv") else "auto",
                        year=detected_year,
                    )
                    if not results:
                        results = await self.tmdb_client.search_multi(query=search_query)
                    if results:
                        best_match = results[0]
                except Exception as e:
                    logger.warning("TMDB bot search notice: %s", e)

            # 4. Fallback if TMDB search has no result
            if not best_match:
                final_title = search_query if (search_query and not search_query.startswith("http")) else "百度网盘分享资源"
                final_type = detected_type if detected_type in ("movie", "tv") else "movie"
                best_match = TMDBMediaResult(
                    id=0,
                    title=final_title,
                    original_title=final_title,
                    year=detected_year,
                    media_type=final_type,
                    overview="百度网盘直接转存归档",
                    poster_url="",
                    vote_average=0.0,
                )
                results = [best_match]

            session_id = uuid.uuid4().hex[:10]
            self._sessions[session_id] = {
                "share_url": share_link.clean_share_url,
                "share_pwd": share_link.pwd,
                "parsed_media": parsed_media,
                "candidates": results,
                "current_tmdb": best_match,
                "media_type": best_match.media_type,
                "user_id": user.id,
            }

            # Check if user has auto-transfer enabled
            user_settings = await self.db.get_user_settings(user.id)
            if user_settings.get("auto_transfer", self.config.media.auto_transfer):
                task_id = await self.task_manager.enqueue_task(
                    telegram_user_id=user.id,
                    share_url=share_link.clean_share_url,
                    share_pwd=share_link.pwd,
                    tmdb_result=best_match,
                    media_type=best_match.media_type,
                )
                await status_msg.edit_text(
                    f"⚡ <b>已自动创建转存任务</b> (`{task_id}`)\n"
                    f"🎬 <b>媒体</b>: {best_match.display_name}\n"
                    f"📂 正在后台处理，完成后将通知您...",
                    parse_mode=ParseMode.HTML,
                )
                return

            # Display interactive preview card
            type_label = "🎬 电影" if best_match.media_type == "movie" else "📺 电视剧"
            caption = (
                f"🎯 <b>识别结果</b>\n\n"
                f"📌 <b>名称</b>: <b>{html.escape(best_match.title)}</b>\n"
                f"🔤 <b>原名</b>: {html.escape(best_match.original_title)}\n"
                f"📅 <b>年份</b>: {best_match.year or '未知'}\n"
                f"🏷 <b>分类</b>: {type_label}\n"
                f"⭐ <b>评分</b>: {best_match.vote_average}\n"
                f"🔑 <b>提取码</b>: <code>{share_link.pwd or '无'}</code>\n\n"
                f"📝 <b>简介</b>: <i>{html.escape((best_match.overview[:120] + '...') if best_match.overview else '无简介')}</i>"
            )

            kb = build_media_confirmation_keyboard(
                session_id=session_id,
                tmdb=best_match,
                current_type=best_match.media_type,
            )

            # If poster URL exists, try to send photo, else edit text
            if best_match.poster_url:
                try:
                    await status_msg.delete()
                    await update.message.reply_photo(
                        photo=best_match.poster_url,
                        caption=caption,
                        reply_markup=kb,
                        parse_mode=ParseMode.HTML,
                    )
                    return
                except Exception as e:
                    logger.warning("Failed to send poster photo: %s", e)

            await status_msg.edit_text(caption, reply_markup=kb, parse_mode=ParseMode.HTML)

        except Exception as e:
            logger.exception("Failed to parse and process share link: %s", e)
            await status_msg.edit_text(f"❌ 解析链接失败: {e}")

    async def on_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle inline button clicks."""
        query = update.callback_query
        await query.answer()
        data = query.data or ""
        user = update.effective_user

        if not self._is_user_allowed(user.id):
            return

        parts = data.split(":")
        action = parts[0]

        # ----------------------------------------------------------------------
        # Media Actions
        # ----------------------------------------------------------------------
        if action == "confirm":
            session_id = parts[1]
            media_type = parts[2]
            tmdb_id = int(parts[3])

            session = self._sessions.get(session_id)
            if not session:
                await query.edit_message_caption("⚠️ 会话已过期，请重新发送链接。") if query.message.photo else await query.edit_message_text("⚠️ 会话已过期，请重新发送链接。")
                return

            current_tmdb: TMDBMediaResult = session["current_tmdb"]

            # Enqueue task
            task_id = await self.task_manager.enqueue_task(
                telegram_user_id=user.id,
                share_url=session["share_url"],
                share_pwd=session["share_pwd"],
                tmdb_result=current_tmdb,
                media_type=media_type,
            )

            confirm_msg = (
                f"✅ <b>已加入转存队列</b> (`{task_id}`)\n\n"
                f"🎬 <b>媒体</b>: {current_tmdb.display_name}\n"
                f"🏷 <b>分类</b>: {'电视剧' if media_type == 'tv' else '电影'}\n"
                f"⏳ 后台正在为您转存并按照 TMDB 规范重命名归档，完成后将通知您！"
            )
            if query.message.photo:
                await query.edit_message_caption(caption=confirm_msg, parse_mode=ParseMode.HTML)
            else:
                await query.edit_message_text(text=confirm_msg, parse_mode=ParseMode.HTML)

            self._sessions.pop(session_id, None)

        elif action == "switch":
            session_id = parts[1]
            new_type = parts[2]
            session = self._sessions.get(session_id)
            if not session:
                return

            # Re-search or switch type
            parsed = session["parsed_media"]
            results = await self.tmdb_client.search_multi(
                query=parsed.cleaned_title,
                media_type=new_type,
                year=parsed.year,
            )
            if results:
                best = results[0]
                session["current_tmdb"] = best
                session["media_type"] = new_type
                session["candidates"] = results

                type_label = "🎬 电影" if new_type == "movie" else "📺 电视剧"
                caption = (
                    f"🎯 <b>识别结果 (已切换为 {type_label})</b>\n\n"
                    f"📌 <b>名称</b>: <b>{html.escape(best.title)}</b>\n"
                    f"🔤 <b>原名</b>: {html.escape(best.original_title)}\n"
                    f"📅 <b>年份</b>: {best.year or '未知'}\n"
                    f"⭐ <b>评分</b>: {best.vote_average}\n\n"
                    f"📝 <b>简介</b>: <i>{html.escape((best.overview[:120] + '...') if best.overview else '无简介')}</i>"
                )
                kb = build_media_confirmation_keyboard(session_id, best, new_type)
                if query.message.photo:
                    await query.edit_message_caption(caption=caption, reply_markup=kb, parse_mode=ParseMode.HTML)
                else:
                    await query.edit_message_text(text=caption, reply_markup=kb, parse_mode=ParseMode.HTML)

        elif action == "more":
            session_id = parts[1]
            session = self._sessions.get(session_id)
            if not session:
                return

            candidates = session.get("candidates", [])
            kb = build_search_selection_keyboard(session_id, candidates)
            select_text = "🔍 <b>请从以下 TMDB 候选结果中选择：</b>"
            if query.message.photo:
                await query.edit_message_caption(caption=select_text, reply_markup=kb, parse_mode=ParseMode.HTML)
            else:
                await query.edit_message_text(text=select_text, reply_markup=kb, parse_mode=ParseMode.HTML)

        elif action == "select":
            session_id = parts[1]
            media_type = parts[2]
            tmdb_id = int(parts[3])
            session = self._sessions.get(session_id)
            if not session:
                return

            if media_type == "tv":
                selected = await self.tmdb_client.get_tv_details(tmdb_id)
            else:
                selected = await self.tmdb_client.get_movie_details(tmdb_id)

            session["current_tmdb"] = selected
            session["media_type"] = media_type

            type_label = "🎬 电影" if media_type == "movie" else "📺 电视剧"
            caption = (
                f"🎯 <b>已选择媒体</b>\n\n"
                f"📌 <b>名称</b>: <b>{html.escape(selected.title)}</b>\n"
                f"🔤 <b>原名</b>: {html.escape(selected.original_title)}\n"
                f"📅 <b>年份</b>: {selected.year or '未知'}\n"
                f"🏷 <b>分类</b>: {type_label}\n"
                f"⭐ <b>评分</b>: {selected.vote_average}\n\n"
                f"📝 <b>简介</b>: <i>{html.escape((selected.overview[:120] + '...') if selected.overview else '无简介')}</i>"
            )
            kb = build_media_confirmation_keyboard(session_id, selected, media_type)
            if query.message.photo:
                await query.edit_message_caption(caption=caption, reply_markup=kb, parse_mode=ParseMode.HTML)
            else:
                await query.edit_message_text(text=caption, reply_markup=kb, parse_mode=ParseMode.HTML)

        elif action == "cancel":
            session_id = parts[1]
            self._sessions.pop(session_id, None)
            if query.message.photo:
                await query.edit_message_caption(caption="❌ 已取消该操作。")
            else:
                await query.edit_message_text(text="❌ 已取消该操作。")

        # ----------------------------------------------------------------------
        # Settings Actions
        # ----------------------------------------------------------------------
        elif action == "set_toggle_auto":
            settings = await self.db.get_user_settings(user.id)
            current_val = bool(settings.get("auto_transfer", self.config.media.auto_transfer))
            new_val = not current_val
            await self.db.save_user_setting(user.id, auto_transfer=new_val)

            tmdb_lang = settings.get("tmdb_language", self.config.tmdb.language)
            text = (
                "⚙️ <b>偏好设置 (已更新)</b>\n\n"
                f"• <b>自动转存</b>: {'✅ 已开启 (无需手动确认)' if new_val else '❌ 已关闭 (每次手动确认)'}\n"
                f"• <b>TMDB 刮削语言</b>: <code>{tmdb_lang}</code>\n"
                f"• <b>电影保存目录</b>: <code>{settings.get('movie_dir') or self.config.media.movie_dir}</code>\n"
                f"• <b>剧集保存目录</b>: <code>{settings.get('tv_dir') or self.config.media.tv_dir}</code>"
            )
            kb = build_settings_keyboard(new_val, tmdb_lang)
            await query.edit_message_text(text=text, reply_markup=kb, parse_mode=ParseMode.HTML)

        elif action == "close_settings":
            await query.edit_message_text("✅ 设置菜单已关闭。")

    def register(self, app: Application) -> None:
        """Register all handlers to python-telegram-bot application."""
        app.add_handler(CommandHandler("start", self.start_command))
        app.add_handler(CommandHandler("help", self.help_command))
        app.add_handler(CommandHandler(["login", "auth"], self.login_command))
        app.add_handler(CommandHandler("code", self.code_command))
        app.add_handler(CommandHandler(["status", "quota"], self.status_command))
        app.add_handler(CommandHandler("settings", self.settings_command))
        app.add_handler(CommandHandler("tasks", self.tasks_command))
        app.add_handler(CommandHandler("search", self.search_command))
        app.add_handler(CallbackQueryHandler(self.on_callback_query))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_message))
