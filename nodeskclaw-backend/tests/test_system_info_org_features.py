"""验证 GET /system/info 在已登录且已选组织时按组织 override 合并 feature 列表；
未登录时保持原有 edition 级默认值不变。"""
import uuid

import pytest
from httpx import AsyncClient

from app.core.security import get_current_user_optional
from app.main import app
from app.models.org_membership import OrgMembership, OrgRole
from app.models.organization import Organization
from app.models.organization_feature_override import OrganizationFeatureOverride
from app.models.user import User
from tests.conftest import TestSessionLocal


def _override_user(user: User | None):
    app.dependency_overrides[get_current_user_optional] = lambda: user


def _clear_override():
    app.dependency_overrides.pop(get_current_user_optional, None)


def _find_feature(features: list[dict], feature_id: str) -> dict:
    return next(f for f in features if f["id"] == feature_id)


@pytest.mark.asyncio
async def test_unauthenticated_returns_edition_default(client: AsyncClient):
    resp = await client.get("/api/v1/system/info")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "edition" in data
    assert "features" in data


@pytest.mark.asyncio
async def test_authenticated_no_override_keeps_edition_default(client: AsyncClient):
    suffix = uuid.uuid4().hex[:8]
    async with TestSessionLocal() as db:
        org = Organization(name=f"org-si-{suffix}", slug=f"org-si-{suffix}")
        db.add(org)
        await db.flush()
        user = User(
            email=f"user-si-{suffix}@example.com", name="user-si",
            password_hash="x", current_org_id=org.id,
        )
        db.add(user)
        await db.flush()
        db.add(OrgMembership(org_id=org.id, user_id=user.id, role=OrgRole.member))
        await db.commit()
        await db.refresh(user)

    _override_user(user)
    try:
        resp = await client.get("/api/v1/system/info")
        assert resp.status_code == 200, resp.text
        feat = _find_feature(resp.json()["features"], "multi_org")
        assert feat["enabled"] is True
    finally:
        _clear_override()


@pytest.mark.asyncio
async def test_authenticated_with_override_merges_org_value(client: AsyncClient):
    suffix = uuid.uuid4().hex[:8]
    async with TestSessionLocal() as db:
        org = Organization(name=f"org-si2-{suffix}", slug=f"org-si2-{suffix}")
        db.add(org)
        await db.flush()
        user = User(
            email=f"user-si2-{suffix}@example.com", name="user-si2",
            password_hash="x", current_org_id=org.id,
        )
        db.add(user)
        await db.flush()
        db.add(OrgMembership(org_id=org.id, user_id=user.id, role=OrgRole.member))
        db.add(OrganizationFeatureOverride(
            org_id=org.id, feature_id="multi_org", enabled=False,
            set_by_user_id=user.id,
        ))
        await db.commit()
        await db.refresh(user)

    _override_user(user)
    try:
        resp = await client.get("/api/v1/system/info")
        assert resp.status_code == 200, resp.text
        feat = _find_feature(resp.json()["features"], "multi_org")
        assert feat["enabled"] is False
    finally:
        _clear_override()
