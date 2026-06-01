"""超管全局用户管理 endpoint 测试。

覆盖：
- 分页列表含 pagination 字段
- 重置密码返回 temp_password
- 非超管调用 update_user 返回 403
"""

from __future__ import annotations

import pytest

# 超管用户管理路由注册在 /api/v1/admin/users
USERS_URL = "/api/v1/admin/users"


@pytest.mark.asyncio
async def test_list_users_paginated(async_client, super_admin_token):
    """超管查询用户列表，响应体包含 pagination 且 page == 1。"""
    resp = await async_client.get(
        f"{USERS_URL}?page=1&page_size=10",
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "pagination" in body
    assert body["pagination"]["page"] == 1


@pytest.mark.asyncio
async def test_reset_password_returns_temp(async_client, super_admin_token, sample_user):
    """超管重置用户密码，响应体 data.temp_password 非空。"""
    resp = await async_client.post(
        f"{USERS_URL}/{sample_user.id}/reset-password",
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["temp_password"]


@pytest.mark.asyncio
async def test_update_user_403_for_normal(async_client, normal_user_token, sample_user):
    """非超管调用 update_user 应返回 403。"""
    resp = await async_client.put(
        f"{USERS_URL}/{sample_user.id}",
        json={"is_active": False},
        headers={"Authorization": f"Bearer {normal_user_token}"},
    )
    assert resp.status_code == 403
