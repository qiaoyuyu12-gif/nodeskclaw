"""Feature override endpoint 测试。"""

import pytest

# Feature 路由注册在 /api/v1/admin
ADMIN_URL = "/api/v1/admin"


@pytest.mark.asyncio
async def test_list_features_returns_override_count(async_client, super_admin_token):
    """GET /admin/features 应返回含 override_count 的 feature 列表。"""
    resp = await async_client.get(
        f"{ADMIN_URL}/features",
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    for item in body["data"]:
        assert "feature_id" in item
        assert "default_enabled" in item
        assert "override_count" in item


@pytest.mark.asyncio
async def test_set_then_clear_override(async_client, super_admin_token, sample_org):
    """PUT 设置 override 后 source == override；DELETE 清除后返回 200。"""
    set_resp = await async_client.put(
        f"{ADMIN_URL}/orgs/{sample_org.id}/features/multi_org",
        json={"enabled": True, "reason": "试点"},
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert set_resp.status_code == 200
    assert set_resp.json()["data"]["source"] == "override"
    clear_resp = await async_client.delete(
        f"{ADMIN_URL}/orgs/{sample_org.id}/features/multi_org",
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert clear_resp.status_code == 200
