"""
Baidu Netdisk OAuth 2.0 Token Manager and Device Code Authorization.
"""

from __future__ import annotations

import logging
import time
import urllib.parse
from typing import Any, Dict, Optional
import httpx

from ..core.database import Database

logger = logging.getLogger(__name__)

BAIDU_OAUTH_AUTH_URL = "https://openapi.baidu.com/oauth/2.0/authorize"
BAIDU_OAUTH_TOKEN_URL = "https://openapi.baidu.com/oauth/2.0/token"
BAIDU_OAUTH_DEVICE_CODE_URL = "https://openapi.baidu.com/oauth/2.0/device/code"
BAIDU_DEFAULT_REDIRECT_URI = "https://openapi.baidu.com/oauth/2.0/login_success"


class BaiduAuthManager:
    """Manages Baidu Netdisk OAuth2 tokens, authorization flow, and auto-refresh."""

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        redirect_uri: str = "oob",
        db: Optional[Database] = None,
        user_identifier: str = "default",
    ):
        self.app_key = app_key.strip()
        self.app_secret = app_secret.strip()
        self.redirect_uri = redirect_uri.strip() if redirect_uri else "oob"
        self.db = db
        self.user_identifier = user_identifier

    def get_authorization_url(
        self,
        scope: str = "basic,netdisk",
        display: str = "page",
    ) -> str:
        """
        Generate Baidu OAuth2 login authorization URL.
        User opens this URL in browser, authorizes, and copies the code.
        """
        if not self.app_key:
            raise ValueError(
                "百度 AppKey (Client ID) 未配置！请先在【设置】中填入 AppKey 与 AppSecret，或直接使用 Token/BDUSS 登录。"
            )

        # Standard Baidu OAuth redirect URI: 'oob' or 'https://openapi.baidu.com/oauth/2.0/login_success'
        target_redirect = self.redirect_uri
        if target_redirect == "oob":
            target_redirect = BAIDU_DEFAULT_REDIRECT_URI

        params = {
            "response_type": "code",
            "client_id": self.app_key,
            "redirect_uri": target_redirect,
            "scope": scope,
            "display": display,
        }
        return f"{BAIDU_OAUTH_AUTH_URL}?{urllib.parse.urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: Optional[str] = None) -> Dict[str, Any]:
        """
        Exchange authorization code for access_token and refresh_token.
        """
        if not self.app_key or not self.app_secret:
            raise ValueError("百度 AppKey 或 AppSecret 未配置，无法交换 Token。")

        target_redirect = redirect_uri or self.redirect_uri
        if target_redirect == "oob":
            target_redirect = BAIDU_DEFAULT_REDIRECT_URI

        params = {
            "grant_type": "authorization_code",
            "code": code.strip(),
            "client_id": self.app_key,
            "client_secret": self.app_secret,
            "redirect_uri": target_redirect,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                BAIDU_OAUTH_TOKEN_URL,
                data=params,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            data = resp.json()

            if "error" in data:
                error_desc = data.get("error_description", data.get("error"))
                logger.error("Baidu OAuth token exchange failed: %s (raw: %s)", error_desc, data)
                raise ValueError(f"OAuth 错误: {error_desc}")

            access_token = data.get("access_token", "")
            refresh_token = data.get("refresh_token", "")
            expires_in = float(data.get("expires_in", 2592000))
            scope = data.get("scope", "")

            if self.db:
                await self.db.save_baidu_token(
                    access_token=access_token,
                    refresh_token=refresh_token,
                    expires_in=expires_in,
                    scope=scope,
                    user_identifier=self.user_identifier,
                )

            logger.info("Successfully obtained Baidu OAuth access token.")
            return data

    async def get_device_code(self, scope: str = "basic,netdisk") -> Dict[str, Any]:
        """
        Request a Device Code for QR code or verification code login.
        """
        if not self.app_key:
            raise ValueError("百度 AppKey 未配置，无法获取设备码。")

        params = {
            "response_type": "device_code",
            "client_id": self.app_key,
            "scope": scope,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                BAIDU_OAUTH_DEVICE_CODE_URL,
                data=params,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            data = resp.json()
            if "error" in data:
                error_desc = data.get("error_description", data.get("error"))
                raise ValueError(f"获取设备码失败: {error_desc}")
            return data

    async def poll_device_token(self, device_code: str) -> Dict[str, Any]:
        """
        Poll token for device code authorization.
        """
        params = {
            "grant_type": "device_token",
            "code": device_code.strip(),
            "client_id": self.app_key,
            "client_secret": self.app_secret,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                BAIDU_OAUTH_TOKEN_URL,
                data=params,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            data = resp.json()
            if "error" in data:
                error_code = data.get("error")
                error_desc = data.get("error_description", error_code)
                return {"success": False, "error": error_code, "description": error_desc}

            access_token = data.get("access_token", "")
            refresh_token = data.get("refresh_token", "")
            expires_in = float(data.get("expires_in", 2592000))
            scope = data.get("scope", "")

            if self.db:
                await self.db.save_baidu_token(
                    access_token=access_token,
                    refresh_token=refresh_token,
                    expires_in=expires_in,
                    scope=scope,
                    user_identifier=self.user_identifier,
                )

            return {"success": True, "data": data}

    async def refresh_access_token(
        self, refresh_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Refresh access token using refresh_token.
        """
        r_token = refresh_token
        if not r_token and self.db:
            token_record = await self.db.get_baidu_token(self.user_identifier)
            if token_record:
                r_token = token_record.get("refresh_token")

        if not r_token:
            raise ValueError("没有可用的 refresh_token 进行续期。")

        params = {
            "grant_type": "refresh_token",
            "refresh_token": r_token.strip(),
            "client_id": self.app_key,
            "client_secret": self.app_secret,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                BAIDU_OAUTH_TOKEN_URL,
                data=params,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            data = resp.json()

            if "error" in data:
                error_desc = data.get("error_description", data.get("error"))
                logger.error("Baidu OAuth token refresh failed: %s", error_desc)
                raise ValueError(f"OAuth 续期错误: {error_desc}")

            access_token = data.get("access_token", "")
            new_refresh_token = data.get("refresh_token", r_token)
            expires_in = float(data.get("expires_in", 2592000))
            scope = data.get("scope", "")

            if self.db:
                await self.db.save_baidu_token(
                    access_token=access_token,
                    refresh_token=new_refresh_token,
                    expires_in=expires_in,
                    scope=scope,
                    user_identifier=self.user_identifier,
                )

            logger.info("Successfully refreshed Baidu OAuth access token.")
            return data

    async def get_valid_access_token(
        self, fallback_token: str = ""
    ) -> Optional[str]:
        """
        Retrieve a valid access token from database, refreshing automatically if close to expiry.
        """
        if not self.db:
            return fallback_token or None

        record = await self.db.get_baidu_token(self.user_identifier)
        if not record or not record.get("access_token"):
            return fallback_token or None

        access_token = record["access_token"]
        expires_at = record["expires_at"]
        refresh_token = record.get("refresh_token")

        # Check if expired or expiring within 1 hour (3600 seconds)
        if time.time() >= (expires_at - 3600):
            if refresh_token and self.app_key and self.app_secret:
                try:
                    logger.info("Access token near expiry; refreshing automatically...")
                    refreshed = await self.refresh_access_token(refresh_token)
                    return refreshed.get("access_token")
                except Exception as e:
                    logger.warning("Auto-refresh failed, using existing token: %s", e)
            else:
                logger.warning("Token expired and auto-refresh not possible.")

        return access_token
