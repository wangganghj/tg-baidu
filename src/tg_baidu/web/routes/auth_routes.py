"""
Baidu Account Cookie Authentication API routes.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...baidu.client import parse_and_clean_cookie

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["auth"])


class CookieAuthRequest(BaseModel):
    cookie: str


@router.get("/api/auth/status")
async def get_auth_status(request: Request) -> Dict[str, Any]:
    """Get current Baidu account and connection status."""
    baidu_client = request.app.state.baidu_client
    db = request.app.state.db
    config = request.app.state.config

    token_record = await db.get_baidu_token()
    if token_record:
        if token_record.get("cookie") and not baidu_client.cookie:
            baidu_client.set_cookie(token_record["cookie"])
        elif token_record.get("bduss") and not baidu_client.bduss:
            baidu_client.set_cookie(token_record["bduss"])

    is_configured = baidu_client.is_configured()

    uinfo_dict = None
    quota_dict = None
    error_msg = None

    if is_configured:
        try:
            uinfo = await baidu_client.get_user_info()
            uinfo_dict = {
                "baidu_name": uinfo.baidu_name,
                "netdisk_name": uinfo.netdisk_name,
                "uk": uinfo.uk,
                "vip_type": uinfo.vip_type,
                "vip_label": uinfo.vip_label,
                "avatar_url": uinfo.avatar_url,
            }
        except Exception as e:
            error_msg = str(e)
            logger.warning("Failed to fetch user info: %s", e)

        try:
            quota = await baidu_client.get_quota()
            usage_percent = round((quota.used / quota.total * 100), 1) if quota.total > 0 else 0.0
            quota_dict = {
                "total_bytes": quota.total,
                "used_bytes": quota.used,
                "free_bytes": quota.free,
                "total_gb": quota.total_gb,
                "used_gb": quota.used_gb,
                "free_gb": quota.free_gb,
                "usage_percent": usage_percent,
            }
        except Exception as e:
            if not error_msg:
                error_msg = str(e)
            logger.warning("Failed to fetch quota info: %s", e)

    return {
        "is_authenticated": is_configured and (uinfo_dict is not None or quota_dict is not None),
        "is_configured": is_configured,
        "cookie_hint": (baidu_client.bduss[:8] + "..." + baidu_client.bduss[-4:]) if len(baidu_client.bduss) > 12 else (baidu_client.bduss or "已设置"),
        "user_info": uinfo_dict,
        "quota": quota_dict,
        "error": error_msg,
    }


@router.post("/api/auth/cookie")
async def save_cookie(payload: CookieAuthRequest, request: Request) -> Dict[str, Any]:
    """Save and verify Baidu Netdisk Cookie or BDUSS."""
    db = request.app.state.db
    baidu_client = request.app.state.baidu_client
    config = request.app.state.config

    raw_input = (payload.cookie or "").strip()
    if not raw_input:
        raise HTTPException(status_code=400, detail="请输入百度网盘 Cookie 或 BDUSS。")

    cookie_str, bduss, stoken, _ = parse_and_clean_cookie(raw_input)
    if not bduss and not cookie_str:
        raise HTTPException(status_code=400, detail="未能识别有效的 Cookie 或 BDUSS，请检查输入格式。")

    # Update runtime client
    baidu_client.set_cookie(raw_input)
    config.baidu.cookie = cookie_str
    config.baidu.bduss = bduss
    config.baidu.stoken = stoken

    try:
        # Save to database
        await db.save_baidu_cookie(cookie=cookie_str, bduss=bduss, stoken=stoken)
        await db.save_system_setting("baidu_cookie", cookie_str)
        await db.save_system_setting("baidu_bduss", bduss)
        await db.save_system_setting("baidu_stoken", stoken)
        config.save_yaml("data/config.yaml")

        # Verify connectivity
        uinfo = await baidu_client.get_user_info()
        return {
            "success": True,
            "message": f"百度网盘连接成功: {uinfo.baidu_name} ({uinfo.vip_label})",
            "user": {
                "baidu_name": uinfo.baidu_name,
                "vip_label": uinfo.vip_label,
            },
        }
    except Exception as e:
        logger.exception("Cookie verification failed: %s", e)
        err_msg = str(e)
        if "-6" in err_msg or "errno=-6" in err_msg or "过期" in err_msg or "无效" in err_msg:
            detail_msg = "Cookie / BDUSS 验证无效或已过期 (errno=-6)。请确保当前浏览器已登录 pan.baidu.com，并复制最新 Cookie。"
        else:
            detail_msg = f"连接失败: {err_msg}"
        raise HTTPException(status_code=400, detail=detail_msg)


@router.post("/api/auth/logout")
async def logout(request: Request) -> Dict[str, bool]:
    """Clear stored Cookie and disconnect."""
    db = request.app.state.db
    config = request.app.state.config
    baidu_client = request.app.state.baidu_client

    await db.delete_baidu_token()
    await db.save_system_setting("baidu_cookie", "")
    await db.save_system_setting("baidu_bduss", "")
    await db.save_system_setting("baidu_stoken", "")

    config.baidu.cookie = ""
    config.baidu.bduss = ""
    config.baidu.stoken = ""
    baidu_client.set_cookie("")
    config.save_yaml("data/config.yaml")
    return {"success": True}


class WebLoginRequest(BaseModel):
    password: str


@router.get("/api/auth/web-status")
async def get_web_auth_status(request: Request) -> Dict[str, Any]:
    """Get current client's Web authentication and IP whitelist status."""
    from ..auth_helper import (
        get_client_ip,
        is_ip_whitelisted,
        is_request_authenticated,
    )
    config = request.app.state.config
    client_ip = get_client_ip(request)
    has_password = bool(config.web.auth_password and config.web.auth_password.strip())
    is_whitelisted = is_ip_whitelisted(client_ip, config.web.ip_whitelist)
    is_authed, reason = is_request_authenticated(request)

    return {
        "has_password": has_password,
        "is_whitelisted": is_whitelisted,
        "is_authenticated": is_authed,
        "auth_reason": reason,
        "client_ip": client_ip,
        "ip_whitelist": config.web.ip_whitelist,
    }


@router.post("/api/auth/web-login")
async def web_login(payload: WebLoginRequest, request: Request) -> Dict[str, Any]:
    """Verify web password and set session cookie."""
    from fastapi.responses import JSONResponse
    from ..auth_helper import (
        SESSION_COOKIE_NAME,
        generate_session_token,
    )

    config = request.app.state.config
    auth_password = (config.web.auth_password or "").strip()

    if not auth_password:
        return {"success": True, "message": "未启用密码保护"}

    if payload.password != auth_password:
        raise HTTPException(status_code=401, detail="访问密码错误，请重试。")

    token = generate_session_token(auth_password, config.web.session_secret, expiry_days=30)
    response = JSONResponse({
        "success": True,
        "message": "登录成功",
        "token": token,
    })
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=30 * 86400,
        httponly=True,
        samesite="lax",
    )
    return response


@router.post("/api/auth/web-logout")
async def web_logout() -> Dict[str, Any]:
    """Clear session cookie and log out of web dashboard."""
    from fastapi.responses import JSONResponse
    from ..auth_helper import SESSION_COOKIE_NAME

    response = JSONResponse({"success": True, "message": "已退出登录"})
    response.delete_cookie(key=SESSION_COOKIE_NAME)
    return response
