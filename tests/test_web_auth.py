"""
Unit tests for Web authentication and IP whitelist logic.
"""

from tg_baidu.web.auth_helper import (
    generate_session_token,
    is_ip_whitelisted,
    verify_session_token,
)


def test_is_ip_whitelisted_single_ip():
    whitelist = ["127.0.0.1", "192.168.1.100", "::1"]
    assert is_ip_whitelisted("127.0.0.1", whitelist) is True
    assert is_ip_whitelisted("192.168.1.100", whitelist) is True
    assert is_ip_whitelisted("192.168.1.101", whitelist) is False
    assert is_ip_whitelisted("8.8.8.8", whitelist) is False
    assert is_ip_whitelisted("", whitelist) is False


def test_is_ip_whitelisted_cidr_subnets():
    whitelist = ["192.168.1.0/24", "10.0.0.0/8"]
    assert is_ip_whitelisted("192.168.1.1", whitelist) is True
    assert is_ip_whitelisted("192.168.1.254", whitelist) is True
    assert is_ip_whitelisted("192.168.2.1", whitelist) is False
    assert is_ip_whitelisted("10.50.100.200", whitelist) is True
    assert is_ip_whitelisted("172.16.0.1", whitelist) is False


def test_session_token_generation_and_verification():
    password = "SuperSecretPassword123"
    secret = "random_salt_secret"

    token = generate_session_token(password, secret, expiry_days=7)
    assert token is not None
    assert "." in token

    # Verification with correct password & secret
    assert verify_session_token(token, password, secret) is True

    # Verification with wrong password
    assert verify_session_token(token, "WrongPassword", secret) is False

    # Verification with invalid token format
    assert verify_session_token("invalid_token", password, secret) is False
    assert verify_session_token("", password, secret) is False
