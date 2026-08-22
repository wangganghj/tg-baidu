"""
OAuth2, Device Code, BDUSS Cookie, and Baidu Account API routes.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from ...baidu.client import clean_bduss_string

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["auth"])


class CodeAuthRequest(BaseModel):
    code: str


class DirectTokenRequest(BaseModel):
    access_token: Optional[str] = ""
    refresh_token: Optional[str] = ""
    bduss: Optional[str] = ""
    stoken: Optional[str] = ""


class QuickAppKeyRequest(BaseModel):
    app_key: str
    app_secret: str
    redirect_uri: Optional[str] = "https://openapi.baidu.com/oauth/2.0/login_success"


class DevicePollRequest(BaseModel):
    device_code: str


@router.get("/api/auth/status")
async def get_auth_status(request: Request) -> Dict[str, Any]:
    """Get current Baidu account and authorization status."""
    baidu_client = request.app.state.baidu_client
    db = request.app.state.db
    config = request.app.state.config
    auth_manager = request.app.state.auth_manager

    token_record = await db.get_baidu_token()
    if token_record:
        if token_record.get("bduss") and not baidu_client.bduss:
            baidu_client.bduss = token_record["bduss"]
        if token_record.get("stoken") and not baidu_client.stoken:
            baidu_client.stoken = token_record["stoken"]

    has_token = bool(token_record and token_record.get("access_token")) or bool(config.baidu.access_token)
    has_bduss = bool(token_record and token_record.get("bduss")) or bool(baidu_client.bduss)
    is_authenticated = has_token or has_bduss

    uinfo_dict = None
    quota_dict = None
    error_msg = None

    if is_authenticated:
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
        "is_authenticated": is_authenticated and uinfo_dict is not None,
        "auth_type": "bduss" if has_bduss and not has_token else "oauth",
        "has_app_key": bool(auth_manager.app_key),
        "app_key_hint": auth_manager.app_key[:4] + "..." if len(auth_manager.app_key) > 6 else auth_manager.app_key,
        "token_record": {
            "expires_at": token_record.get("expires_at") if token_record else None,
            "has_refresh_token": bool(token_record and token_record.get("refresh_token")),
            "has_bduss": bool(token_record and token_record.get("bduss")),
            "scope": token_record.get("scope") if token_record else None,
        } if token_record else None,
        "user_info": uinfo_dict,
        "quota": quota_dict,
        "error": error_msg,
    }


@router.get("/api/auth/login-url")
async def get_login_url(request: Request) -> Dict[str, Any]:
    """Get Baidu OAuth authorization URL."""
    auth_manager = request.app.state.auth_manager
    if not auth_manager.app_key:
        return {
            "has_app_key": False,
            "url": None,
            "message": "尚未配置百度 AppKey (Client ID)。请先配置 AppKey，或直接粘贴 Access Token / BDUSS 登录。",
        }

    try:
        url = auth_manager.get_authorization_url()
        return {"has_app_key": True, "url": url}
    except Exception as e:
        return {"has_app_key": False, "url": None, "message": str(e)}


@router.post("/api/auth/set-app-key")
async def set_app_key(payload: QuickAppKeyRequest, request: Request) -> Dict[str, Any]:
    """Quickly configure Baidu AppKey and AppSecret."""
    auth_manager = request.app.state.auth_manager
    config = request.app.state.config

    if not payload.app_key.strip():
        raise HTTPException(status_code=400, detail="AppKey 不能为空。")

    auth_manager.app_key = payload.app_key.strip()
    auth_manager.app_secret = payload.app_secret.strip()
    if payload.redirect_uri:
        auth_manager.redirect_uri = payload.redirect_uri.strip()

    config.baidu.app_key = auth_manager.app_key
    config.baidu.app_secret = auth_manager.app_secret
    config.baidu.redirect_uri = auth_manager.redirect_uri

    return {
        "success": True,
        "message": "百度 AppKey 与 Secret 保存成功！",
        "login_url": auth_manager.get_authorization_url(),
    }


@router.post("/api/auth/code")
async def submit_auth_code(payload: CodeAuthRequest, request: Request) -> Dict[str, Any]:
    """Exchange authorization code for token."""
    auth_manager = request.app.state.auth_manager
    baidu_client = request.app.state.baidu_client

    if not payload.code.strip():
        raise HTTPException(status_code=400, detail="授权码 (Code) 不能为空。")

    if not auth_manager.app_key:
        raise HTTPException(status_code=400, detail="尚未配置 AppKey，无法通过授权码交换 Token。请先配置 AppKey 或直接输入 Access Token。")

    try:
        data = await auth_manager.exchange_code(payload.code.strip())
        uinfo = await baidu_client.get_user_info()
        return {
            "success": True,
            "message": f"成功绑定百度账号: {uinfo.baidu_name}",
            "user": {
                "baidu_name": uinfo.baidu_name,
                "vip_label": uinfo.vip_label,
            },
        }
    except Exception as e:
        logger.exception("Code exchange failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/auth/token")
async def submit_direct_token(payload: DirectTokenRequest, request: Request) -> Dict[str, Any]:
    """Save manually provided Access Token or BDUSS Cookie directly."""
    db = request.app.state.db
    baidu_client = request.app.state.baidu_client
    config = request.app.state.config

    token_val = (payload.access_token or "").strip()
    bduss_val = clean_bduss_string(payload.bduss or "")
    stoken_val = (payload.stoken or "").strip()

    if not token_val and not bduss_val:
        raise HTTPException(status_code=400, detail="Access Token 与 BDUSS 不能同时为空。")

    try:
        # Update in-memory client
        if bduss_val:
            baidu_client.bduss = bduss_val
            config.baidu.bduss = bduss_val
        if stoken_val:
            baidu_client.stoken = stoken_val
            config.baidu.stoken = stoken_val
        if token_val:
            baidu_client.fallback_token = token_val
            config.baidu.access_token = token_val

        # Save to database
        await db.save_baidu_token(
            access_token=token_val,
            refresh_token=(payload.refresh_token or "").strip(),
            bduss=bduss_val,
            stoken=stoken_val,
        )

        uinfo = await baidu_client.get_user_info()
        return {
            "success": True,
            "message": f"账号验证成功: {uinfo.baidu_name} ({uinfo.vip_label})",
            "user": {
                "baidu_name": uinfo.baidu_name,
                "vip_label": uinfo.vip_label,
            },
        }
    except Exception as e:
        logger.exception("Token verification failed: %s", e)
        err_msg = str(e)
        if "-6" in err_msg or "errno=-6" in err_msg:
            detail_text = "BDUSS 验证无效或已过期 (errno=-6)。请重新在浏览器登录 pan.baidu.com 并复制最新的 BDUSS Value。"
        else:
            detail_text = f"验证失败: {err_msg}"
        raise HTTPException(status_code=400, detail=detail_text)


@router.post("/api/auth/device-code")
async def request_device_code(request: Request) -> Dict[str, Any]:
    """Request a Device Code for QR code or verification code login."""
    auth_manager = request.app.state.auth_manager
    try:
        return await auth_manager.get_device_code()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/auth/device-poll")
async def poll_device_code(payload: DevicePollRequest, request: Request) -> Dict[str, Any]:
    """Poll device code authorization status."""
    auth_manager = request.app.state.auth_manager
    baidu_client = request.app.state.baidu_client
    try:
        res = await auth_manager.poll_device_token(payload.device_code)
        if res.get("success"):
            uinfo = await baidu_client.get_user_info()
            res["user"] = {
                "baidu_name": uinfo.baidu_name,
                "vip_label": uinfo.vip_label,
            }
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/oauth/callback")
async def oauth_callback(
    request: Request,
    code: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
) -> RedirectResponse:
    """Handle OAuth redirect callback from Baidu login."""
    if error:
        return RedirectResponse(url=f"/?auth_error={error}")

    if code:
        auth_manager = request.app.state.auth_manager
        try:
            await auth_manager.exchange_code(code)
            return RedirectResponse(url="/?auth_success=1")
        except Exception as e:
            return RedirectResponse(url=f"/?auth_error={str(e)}")

    return RedirectResponse(url="/")


@router.post("/api/auth/logout")
async def logout(request: Request) -> Dict[str, bool]:
    """Clear stored tokens."""
    db = request.app.state.db
    config = request.app.state.config
    baidu_client = request.app.state.baidu_client

    await db.delete_baidu_token()
    config.baidu.access_token = ""
    config.baidu.refresh_token = ""
    config.baidu.bduss = ""
    baidu_client.bduss = ""
    baidu_client.stoken = ""
    baidu_client.fallback_token = ""
    return {"success": True}
