"""
Baidu Netdisk OAuth 2.0 Token Manager.
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
        self.redirect_uri = redirect_uri.strip()
        self.db = db
        self.user_identifier = user_identifier

    def get_authorization_url(
        self,
        scope: str = "basic,netdisk",
        display: str = "popup",
    ) -> str:
        """
        Generate Baidu OAuth2 login authorization URL.
        User opens this URL in browser, authorizes, and copies the code.
        """
        params = {
            "response_type": "code",
            "client_id": self.app_key,
            "redirect_uri": self.redirect_uri,
            "scope": scope,
            "display": display,
            "qrcode": "1",
        }
        return f"{BAIDU_OAUTH_AUTH_URL}?{urllib.parse.urlencode(params)}"

    async def exchange_code(self, code: str) -> Dict[str, Any]:
        """
        Exchange authorization code for access_token and refresh_token.
        """
        params = {
            "grant_type": "authorization_code",
            "code": code.strip(),
            "client_id": self.app_key,
            "client_secret": self.app_secret,
            "redirect_uri": self.redirect_uri,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(BAIDU_OAUTH_TOKEN_URL, data=params)
            data = resp.json()

            if "error" in data:
                error_desc = data.get("error_description", data.get("error"))
                logger.error("Baidu OAuth token exchange failed: %s", error_desc)
                raise ValueError(f"OAuth error: {error_desc}")

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
            raise ValueError("No refresh_token available to refresh.")

        params = {
            "grant_type": "refresh_token",
            "refresh_token": r_token.strip(),
            "client_id": self.app_key,
            "client_secret": self.app_secret,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(BAIDU_OAUTH_TOKEN_URL, data=params)
            data = resp.json()

            if "error" in data:
                error_desc = data.get("error_description", data.get("error"))
                logger.error("Baidu OAuth token refresh failed: %s", error_desc)
                raise ValueError(f"OAuth refresh error: {error_desc}")

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
            if refresh_token:
                try:
                    logger.info("Access token near expiry; refreshing automatically...")
                    refreshed = await self.refresh_access_token(refresh_token)
                    return refreshed.get("access_token")
                except Exception as e:
                    logger.warning("Auto-refresh failed, using existing token: %s", e)
            else:
                logger.warning("Token expired and no refresh_token available.")

        return access_token
