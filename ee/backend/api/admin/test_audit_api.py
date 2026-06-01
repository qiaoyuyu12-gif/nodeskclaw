"""审计日志查询 endpoint 测试。"""

import pytest

# 路由注册在 /api/v1/admin
ADMIN_URL = "/api/v1/admin"


@pytest.mark.asyncio
async def test_audit_actions_returns_enum_values(async_client, super_admin_token):
    """GET /admin/audit/actions 应返回所有 AdminAction enum value。"""
    resp = await async_client.get(
        f"{ADMIN_URL}/audit/actions",
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert resp.status_code == 200
    values = resp.json()["data"]
    assert "org.create" in values
    assert "user.reset_password" in values
    assert "auth.login_failed" in values


@pytest.mark.asyncio
async def test_audit_list_paginated(async_client, super_admin_token):
    """GET /admin/audit 应返回含 pagination 的分页响应。"""
    resp = await async_client.get(
        f"{ADMIN_URL}/audit?page=1&page_size=5",
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert resp.status_code == 200
    assert "pagination" in resp.json()


@pytest.mark.asyncio
async def test_audit_invalid_action_rejected(async_client, super_admin_token):
    """非法 action 值应返回 409 + error_code=40980。"""
    resp = await async_client.get(
        f"{ADMIN_URL}/audit?action=not.a.real.action",
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == 40980
