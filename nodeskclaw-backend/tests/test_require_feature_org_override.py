"""验证 require_feature() 按组织 override 生效：无 override 退回 edition 默认，
有 override 时优先生效；org_id 分别来自 URL path 参数和 user.current_org_id 两种取值路径。"""
import uuid

import pytest
from httpx import AsyncClient

from app.core.security import get_current_user
from app.main import app
from app.models.org_membership import OrgMembership, OrgRole
from app.models.organization import Organization
from app.models.organization_feature_override import OrganizationFeatureOverride
from app.models.user import User
from tests.conftest import TestSessionLocal


def _override_user(user: User):
    app.dependency_overrides[get_current_user] = lambda: user


def _clear_override():
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_no_override_falls_back_to_edition_default(client: AsyncClient):
    """org_id 取自 user.current_org_id（该路由无 org_id path 参数）；
    无 override 时，multi_org 在 EE edition 下默认启用，应正常返回 200。"""
    suffix = uuid.uuid4().hex[:8]
    async with TestSessionLocal() as db:
        org = Organization(name=f"org-rf-{suffix}", slug=f"org-rf-{suffix}")
        db.add(org)
        await db.flush()
        user = User(
            email=f"user-rf-{suffix}@example.com", name="user-rf",
            password_hash="x", current_org_id=org.id,
        )
        db.add(user)
        await db.flush()
        db.add(OrgMembership(org_id=org.id, user_id=user.id, role=OrgRole.member))
        await db.commit()
        await db.refresh(user)

    _override_user(user)
    try:
        resp = await client.get("/api/v1/org-join-requests/my")
        assert resp.status_code == 200, resp.text
    finally:
        _clear_override()


@pytest.mark.asyncio
async def test_org_override_disables_feature_via_current_org_id(client: AsyncClient):
    """同一路由（org_id 取自 current_org_id），给该组织加一条 multi_org=False 的
    override 后，应该从 200 变成 403。"""
    suffix = uuid.uuid4().hex[:8]
    async with TestSessionLocal() as db:
        org = Organization(name=f"org-rf2-{suffix}", slug=f"org-rf2-{suffix}")
        db.add(org)
        await db.flush()
        user = User(
            email=f"user-rf2-{suffix}@example.com", name="user-rf2",
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
        resp = await client.get("/api/v1/org-join-requests/my")
        assert resp.status_code == 403, resp.text
        # 全局 HTTPException handler（app/core/exceptions.py）会把 exc.detail
        # 拍平进顶层字段，响应体不含 "detail" key，故直接取顶层 message_key。
        assert resp.json()["message_key"] == "errors.feature.disabled"
    finally:
        _clear_override()


@pytest.mark.asyncio
async def test_org_id_resolved_from_path_param_when_present(client: AsyncClient):
    """org_smtp_config 挂在带 {org_id} path 参数的路由上，用超管身份验证
    org_id 优先从 URL path 取（而不是 current_org_id）：给目标组织加 override=False
    后，超管访问该组织的 smtp-config 应该 403，即便超管自己的 current_org_id 是别的组织。"""
    suffix = uuid.uuid4().hex[:8]
    async with TestSessionLocal() as db:
        org_other = Organization(name=f"org-rf3-other-{suffix}", slug=f"org-rf3-other-{suffix}")
        org_target = Organization(name=f"org-rf3-target-{suffix}", slug=f"org-rf3-target-{suffix}")
        db.add_all([org_other, org_target])
        await db.flush()
        admin_user = User(
            email=f"admin-rf3-{suffix}@example.com", name="admin-rf3",
            password_hash="x", current_org_id=org_other.id, is_super_admin=True,
        )
        db.add(admin_user)
        await db.flush()
        db.add(OrganizationFeatureOverride(
            org_id=org_target.id, feature_id="org_smtp_config", enabled=False,
            set_by_user_id=admin_user.id,
        ))
        await db.commit()
        await db.refresh(admin_user)
        await db.refresh(org_target)

    _override_user(admin_user)
    try:
        resp = await client.get(f"/api/v1/orgs/{org_target.id}/smtp-config")
        assert resp.status_code == 403, resp.text
        assert resp.json()["message_key"] == "errors.feature.disabled"
    finally:
        _clear_override()
