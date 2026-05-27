"""组织 admin endpoint happy-path 与鉴权测试（业务规则不在 endpoint 层重复）。"""

from __future__ import annotations

import pytest

# EE 超管路由注册在 /api/v1/admin/orgs
ORGS_URL = "/api/v1/admin/orgs"


@pytest.mark.asyncio
async def test_create_org_happy(async_client, super_admin_token):
    """超管可创建组织，响应体包含 data.slug。"""
    resp = await async_client.post(
        ORGS_URL,
        json={"name": "test-org", "slug": "test-org", "plan": "free"},
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["slug"] == "test-org"


@pytest.mark.asyncio
async def test_create_org_403_for_non_admin(async_client, normal_user_token):
    """非超管调用创建组织接口应返回 403。"""
    resp = await async_client.post(
        ORGS_URL,
        json={"name": "test-org", "slug": "test-org"},
        headers={"Authorization": f"Bearer {normal_user_token}"},
    )
    assert resp.status_code == 403
