"""登录接口限流：滑动窗口计数器单测 + email_login 端点集成测试。"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.core.auth_rate_limit import (
    TooManyLoginAttemptsError,
    _failure_counters,
    check_login_rate_limit,
    get_client_ip,
    record_login_failure,
    reset_login_failures,
)


@pytest.fixture(autouse=True)
def _clear_counters():
    """每个测试前清空全局计数器，避免测试间互相污染。"""
    _failure_counters.clear()
    yield
    _failure_counters.clear()


# ─── get_client_ip ──────────────────────────────────────────────────


class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeRequest:
    def __init__(self, ip="1.2.3.4", headers: dict | None = None):
        self.client = _FakeClient(ip) if ip else None
        self.headers = headers or {}


def test_get_client_ip_prefers_x_forwarded_for():
    req = _FakeRequest(ip="10.0.0.1", headers={"x-forwarded-for": "203.0.113.5, 10.0.0.1"})
    assert get_client_ip(req) == "203.0.113.5"


def test_get_client_ip_falls_back_to_direct_client():
    req = _FakeRequest(ip="10.0.0.1")
    assert get_client_ip(req) == "10.0.0.1"


def test_get_client_ip_unknown_when_no_client():
    req = _FakeRequest(ip=None)
    assert get_client_ip(req) == "unknown"


# ─── 滑动窗口计数器 ──────────────────────────────────────────────────


def test_allows_up_to_max_attempts_then_blocks():
    key = "email:test@example.com"
    for _ in range(5):
        check_login_rate_limit(key)  # 前 5 次不应该抛异常
        record_login_failure(key)

    with pytest.raises(TooManyLoginAttemptsError):
        check_login_rate_limit(key)


def test_ip_and_account_keys_are_independent():
    ip_key, account_key = "ip:1.2.3.4", "email:a@example.com"
    for _ in range(5):
        record_login_failure(ip_key)  # 只打满 IP 计数器

    with pytest.raises(TooManyLoginAttemptsError):
        check_login_rate_limit(ip_key, account_key)

    # 账号维度本身没被打满，单独查它应该放行
    check_login_rate_limit(account_key)


def test_reset_clears_only_the_given_key():
    ip_key, account_key = "ip:1.2.3.4", "email:a@example.com"
    for _ in range(5):
        record_login_failure(ip_key, account_key)

    reset_login_failures(account_key)

    check_login_rate_limit(account_key)  # 账号维度已清空，放行
    with pytest.raises(TooManyLoginAttemptsError):
        check_login_rate_limit(ip_key)  # IP 维度未清，仍然拦截


def test_window_expiry_allows_retry(monkeypatch):
    key = "email:test@example.com"
    fake_now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: fake_now[0])

    for _ in range(5):
        record_login_failure(key)
    with pytest.raises(TooManyLoginAttemptsError):
        check_login_rate_limit(key)

    fake_now[0] += 61  # 超过 60 秒窗口期
    check_login_rate_limit(key)  # 应该自然放行


# ─── email_login 端点集成（mock auth_service + 审计）────────────────


@pytest.mark.asyncio
async def test_email_login_blocks_after_five_failures():
    from app.api.auth import email_login
    from app.schemas.auth import EmailLoginRequest

    request = _FakeRequest(ip="9.9.9.9")
    db = AsyncMock()
    body = EmailLoginRequest(email="victim@example.com", password="wrong")

    with patch("app.api.auth.auth_service.login_with_email", new=AsyncMock(
        side_effect=HTTPException(status_code=401, detail="invalid"),
    )), patch("app.api.auth._write_auth_audit", new=AsyncMock()):
        for _ in range(5):
            with pytest.raises(HTTPException) as exc_info:
                await email_login(body, request, db)
            assert exc_info.value.status_code == 401

        with pytest.raises(TooManyLoginAttemptsError):
            await email_login(body, request, db)


@pytest.mark.asyncio
async def test_email_login_success_resets_account_counter():
    from app.api.auth import email_login
    from app.schemas.auth import EmailLoginRequest

    request = _FakeRequest(ip="9.9.9.9")
    db = AsyncMock()
    body = EmailLoginRequest(email="user@example.com", password="wrong-then-right")

    fake_result = AsyncMock()
    fake_result.user.id = "u1"
    fake_result.user.email = "user@example.com"
    fake_result.user.current_org_id = None

    with patch("app.api.auth.auth_service.login_with_email", new=AsyncMock(
        side_effect=[HTTPException(status_code=401, detail="invalid")] * 4 + [fake_result],
    )), patch("app.api.auth._write_auth_audit", new=AsyncMock()), \
         patch("app.core.hooks.emit", new=AsyncMock()):
        for _ in range(4):
            with pytest.raises(HTTPException):
                await email_login(body, request, db)
        await email_login(body, request, db)  # 第 5 次成功，应清空账号计数器

    # 成功后账号计数器已清空，即使 IP 计数器已经有 4 次失败也不影响账号维度单独检查
    account_key = "email:user@example.com"
    check_login_rate_limit(account_key)
