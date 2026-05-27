"""feature_admin_service 行为测试。

测试覆盖：
- set_override 写入新行，resolve_org_feature 返回 override 状态
- set_override 传入未知 feature_id 时抛出 422/AdminErrorCode
- clear_override 软删 override 行，resolve 回落到 default
- resolve_org_feature 无 override 时返回 default 状态
"""

import pytest

from ee.backend.services.admin import feature_admin_service
from ee.backend.services.admin.errors import AdminErrorCode
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_set_override_creates_row(db_session, super_admin_user, sample_org):
    """set_override 写入 override 后，resolve_org_feature 应返回 override 状态。"""
    await feature_admin_service.set_override(
        db_session,
        admin=super_admin_user,
        org_id=sample_org.id,
        feature_id="multi_org",
        enabled=True,
        reason="试点",
    )
    await db_session.commit()
    state = await feature_admin_service.resolve_org_feature(
        db_session, org_id=sample_org.id, feature_id="multi_org"
    )
    assert state["enabled"] is True
    assert state["source"] == "override"
    assert state["reason"] == "试点"


@pytest.mark.asyncio
async def test_set_override_unknown_feature_id_rejected(db_session, super_admin_user, sample_org):
    """set_override 传入不存在的 feature_id 时应抛出 HTTPException，detail 含 FEATURE_ID_UNKNOWN。"""
    with pytest.raises(HTTPException) as exc:
        await feature_admin_service.set_override(
            db_session,
            admin=super_admin_user,
            org_id=sample_org.id,
            feature_id="not_a_real_feature_id_zzz",
            enabled=True,
            reason=None,
        )
    assert exc.value.detail["error_code"] == int(AdminErrorCode.FEATURE_ID_UNKNOWN)


@pytest.mark.asyncio
async def test_clear_override_softdeletes_row(db_session, super_admin_user, sample_org):
    """clear_override 软删 override 后，resolve_org_feature 应回落到 default。"""
    await feature_admin_service.set_override(
        db_session, admin=super_admin_user, org_id=sample_org.id,
        feature_id="multi_org", enabled=True, reason=None,
    )
    await db_session.commit()
    await feature_admin_service.clear_override(
        db_session, admin=super_admin_user, org_id=sample_org.id, feature_id="multi_org",
    )
    await db_session.commit()
    state = await feature_admin_service.resolve_org_feature(
        db_session, org_id=sample_org.id, feature_id="multi_org"
    )
    assert state["source"] == "default"


@pytest.mark.asyncio
async def test_resolve_default_when_no_override(db_session, sample_org):
    """无 override 时，resolve_org_feature 应返回 source=default 并包含 default_enabled 字段。"""
    state = await feature_admin_service.resolve_org_feature(
        db_session, org_id=sample_org.id, feature_id="multi_org"
    )
    assert state["source"] == "default"
    assert "default_enabled" in state
