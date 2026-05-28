"""feature_admin_service 行为测试。

测试覆盖：
- set_override 写入新行，resolve_org_feature 返回 override 状态
- set_override 传入未知 feature_id 时抛出 422/AdminErrorCode
- clear_override 软删 override 行，resolve 回落到 default
- resolve_org_feature 无 override 时返回 default 状态
- list_overrides_for_feature 返回含 org_name 和 set_by_name 的 dict 列表
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


@pytest.mark.asyncio
async def test_list_overrides_returns_org_name_and_set_by_name(
    db_session, super_admin_user, sample_org
):
    """验证 list_overrides_for_feature 响应含 org_name 和 set_by_name。

    创建一条 override 后，list 结果应：
    - total == 1
    - 包含 org_name（来自 Organization.name）
    - 包含 set_by_name（来自 User.name 或 User.email）
    """
    # 创建一个 override，操作人为 super_admin_user
    await feature_admin_service.set_override(
        db_session,
        admin=super_admin_user,
        org_id=sample_org.id,
        feature_id="multi_org",
        enabled=True,
        reason="test",
    )
    await db_session.commit()

    rows, total = await feature_admin_service.list_overrides_for_feature(
        db_session, feature_id="multi_org",
    )

    assert total == 1
    assert len(rows) == 1
    row = rows[0]

    # 验证基本字段
    assert row["org_id"] == sample_org.id
    assert row["feature_id"] == "multi_org"
    assert row["enabled"] is True
    assert row["reason"] == "test"
    assert row["set_by_user_id"] == super_admin_user.id

    # 验证 join 字段：org_name 来自 Organization，set_by_name 来自 User
    assert row["org_name"] == sample_org.name
    # set_by_name 应为操作人的 name 或 email（不为 None）
    assert row["set_by_name"] in (super_admin_user.name, super_admin_user.email)
