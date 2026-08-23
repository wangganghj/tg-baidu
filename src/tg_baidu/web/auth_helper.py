"""
Authentication and IP whitelist helper for Web Dashboard.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
import time
from typing import List, Optional, Tuple
from fastapi import Request

logger = logging.getLogger(__name__)

SESSION_COOKIE_NAME = "tg_baidu_session"


def get_client_ip(request: Request) -> str:
    """Extract real client IP address considering reverse proxies."""
    # 1. Check X-Forwarded-For header (first hop)
    x_forwarded_for = request.headers.get("X-Forwarded-For")
    if x_forwarded_for:
        client_ip = x_forwarded_for.split(",")[0].strip()
        if client_ip:
            return client_ip

    # 2. Check X-Real-IP header
    x_real_ip = request.headers.get("X-Real-IP")
    if x_real_ip:
        return x_real_ip.strip()

    # 3. Fallback to client host from socket
    if request.client and request.client.host:
        return request.client.host.strip()

    return "127.0.0.1"


def is_ip_whitelisted(client_ip: str, whitelist: List[str]) -> bool:
    """
    Check if client IP matches any IP or CIDR subnet in whitelist.
    Supports single IPs (e.g. 192.168.1.100, ::1) and CIDR subnets (e.g. 192.168.1.0/24, 10.0.0.0/8).
    """
    if not client_ip or not whitelist:
        return False

    try:
        c_ip = ipaddress.ip_address(client_ip.strip())
    except ValueError:
        return False

    for item in whitelist:
        raw = item.strip()
        if not raw:
            continue
        try:
            if "/" in raw:
                net = ipaddress.ip_network(raw, strict=False)
                if c_ip in net:
                    return True
            else:
                target_ip = ipaddress.ip_address(raw)
                if c_ip == target_ip:
                    return True
        except ValueError:
            continue

    return False


def get_session_secret(config_secret: str, auth_password: str) -> str:
    """Derive secret key for signing session tokens."""
    if config_secret:
        return config_secret
    # Deterministic secret derived from password + salt
    return hashlib.sha256(f"tg_baidu_salt_{auth_password}".encode()).hexdigest()


def generate_session_token(password: str, secret: str, expiry_days: int = 30) -> str:
    """Generate a HMAC signed session token with expiry timestamp."""
    exp = int(time.time()) + expiry_days * 86400
    derived_secret = get_session_secret(secret, password)
    raw_payload = f"{password}:{derived_secret}:{exp}"
    signature = hmac.new(derived_secret.encode(), raw_payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{signature}.{exp}"


def verify_session_token(token: Optional[str], password: str, secret: str) -> bool:
    """Verify session token signature and check for expiration."""
    if not token or "." not in token:
        return False

    parts = token.split(".", 1)
    if len(parts) != 2:
        return False

    sig, exp_str = parts
    try:
        exp = int(exp_str)
    except ValueError:
        return False

    if time.time() > exp:
        return False  # Expired

    derived_secret = get_session_secret(secret, password)
    raw_payload = f"{password}:{derived_secret}:{exp}"
    expected_sig = hmac.new(derived_secret.encode(), raw_payload.encode(), hashlib.sha256).hexdigest()[:32]

    return hmac.compare_digest(sig, expected_sig)


def is_request_authenticated(request: Request) -> Tuple[bool, str]:
    """
    Evaluate whether the request is authorized.
    Returns (is_authenticated, reason):
    - reason: "no_password_set" | "ip_whitelisted" | "valid_session" | "unauthorized"
    """
    config = getattr(request.app.state, "config", None)
    if not config or not config.web.auth_password:
        return True, "no_password_set"

    auth_password = config.web.auth_password.strip()
    if not auth_password:
        return True, "no_password_set"

    # 1. Check IP Whitelist Bypass
    client_ip = get_client_ip(request)
    if is_ip_whitelisted(client_ip, config.web.ip_whitelist):
        return True, "ip_whitelisted"

    # 2. Check Cookie
    cookie_token = request.cookies.get(SESSION_COOKIE_NAME)
    if verify_session_token(cookie_token, auth_password, config.web.session_secret):
        return True, "valid_session"

    # 3. Check Authorization Bearer Header
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        header_token = auth_header[7:].strip()
        if verify_session_token(header_token, auth_password, config.web.session_secret):
            return True, "valid_session"

    return False, "unauthorized"
