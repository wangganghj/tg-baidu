"""
OAuth2 and Baidu Account API routes.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["auth"])


class CodeAuthRequest(BaseModel):
    code: str


class DirectTokenRequest(BaseModel):
    access_token: str
    refresh_token: Optional[str] = ""
    bduss: Optional[str] = ""
    stoken: Optional[str] = ""


@router.get("/api/auth/status")
async def get_auth_status(request: Request) -> Dict[str, Any]:
    """Get current Baidu account and authorization status."""
    baidu_client = request.app.state.baidu_client
    db = request.app.state.db
    config = request.app.state.config

    token_record = await db.get_baidu_token()
    is_authenticated = bool(token_record and token_record.get("access_token")) or bool(config.baidu.access_token)

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
        "token_record": {
            "expires_at": token_record.get("expires_at") if token_record else None,
            "has_refresh_token": bool(token_record and token_record.get("refresh_token")),
            "scope": token_record.get("scope") if token_record else None,
        } if token_record else None,
        "user_info": uinfo_dict,
        "quota": quota_dict,
        "error": error_msg,
    }


@router.get("/api/auth/login-url")
async def get_login_url(request: Request) -> Dict[str, str]:
    """Get Baidu OAuth authorization URL."""
    auth_manager = request.app.state.auth_manager
    # Redirect back to the web server callback if available, or oob
    url = auth_manager.get_authorization_url()
    return {"url": url}


@router.post("/api/auth/code")
async def submit_auth_code(payload: CodeAuthRequest, request: Request) -> Dict[str, Any]:
    """Exchange authorization code for token."""
    auth_manager = request.app.state.auth_manager
    baidu_client = request.app.state.baidu_client

    if not payload.code.strip():
        raise HTTPException(status_code=400, detail="Authorization code cannot be empty.")

    try:
        data = await auth_manager.exchange_code(payload.code.strip())
        uinfo = await baidu_client.get_user_info()
        return {
            "success": True,
            "message": f"Successfully authorized as {uinfo.baidu_name}",
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
    """Save manually provided Access Token or Cookie."""
    db = request.app.state.db
    baidu_client = request.app.state.baidu_client

    if not payload.access_token.strip() and not payload.bduss.strip():
        raise HTTPException(status_code=400, detail="Access Token or BDUSS is required.")

    try:
        await db.save_baidu_token(
            access_token=payload.access_token.strip(),
            refresh_token=payload.refresh_token.strip() if payload.refresh_token else "",
            bduss=payload.bduss.strip() if payload.bduss else "",
            stoken=payload.stoken.strip() if payload.stoken else "",
        )
        baidu_client.bduss = payload.bduss.strip() if payload.bduss else ""
        baidu_client.stoken = payload.stoken.strip() if payload.stoken else ""
        uinfo = await baidu_client.get_user_info()
        return {
            "success": True,
            "message": f"Successfully configured token for {uinfo.baidu_name}",
        }
    except Exception as e:
        logger.exception("Token verification failed: %s", e)
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
    await db.delete_baidu_token()
    return {"success": True}
