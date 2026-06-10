"""超管保护 assert_not_super_admin / assert_not_admin_role 行为。"""

import pytest

from app.core.exceptions import ForbiddenError
from app.core.rbac.admin_guard import (
    assert_not_admin_role,
    assert_not_super_admin,
    is_super_admin_user,
)
from app.models.organization import Organization
from app.models.rbac.role import Role
from app.models.user import User
from app.services.rbac_sync import grant_role
from app.startup.seed_rbac import seed_rbac

from tests.rbac.conftest import TestSessionLocal


async def _prepare(db, *, super_id: str, normal_id: str):
    """造一个 super + 一个 normal 用户。"""
    db.add_all([
        User(id=super_id, name="S", username=f"s-{super_id}"),
        User(id=normal_id, name="N", username=f"n-{normal_id}"),
    ])
    await db.flush()
    await grant_role(
        db, subject_type="user", subject_id=super_id,
        role_key="platform_super",
        scope_type="platform", scope_id=None,
        granted_reason="test_super",
    )
    await db.commit()


@pytest.mark.asyncio
async def test_is_super_admin_user_detects_grant(require_test_db, session_factory):
    """is_super_admin_user 命中 platform_super 授权。"""
    await seed_rbac(session_factory)
    async with TestSessionLocal() as db:
        await _prepare(db, super_id="user-super-x", normal_id="user-normal-x")
        assert await is_super_admin_user(db, "user-super-x") is True
        assert await is_super_admin_user(db, "user-normal-x") is False


@pytest.mark.asyncio
async def test_assert_not_super_admin_blocks_non_super(
    require_test_db, session_factory,
):
    """非超管尝试操作超管 → ForbiddenError。"""
    await seed_rbac(session_factory)
    async with TestSessionLocal() as db:
        await _prepare(db, super_id="user-super-y", normal_id="user-normal-y")
        with pytest.raises(ForbiddenError):
            await assert_not_super_admin(
                db,
                current_user_id="user-normal-y",
                target_user_id="user-super-y",
            )


@pytest.mark.asyncio
async def test_assert_not_super_admin_super_can_operate_super(
    require_test_db, session_factory,
):
    """超管操作超管允许（无异常）。"""
    await seed_rbac(session_factory)
    async with TestSessionLocal() as db:
        await _prepare(db, super_id="user-super-z", normal_id="user-normal-z")
        # 自己是超管，目标也是超管 → 允许
        await assert_not_super_admin(
            db,
            current_user_id="user-super-z",
            target_user_id="user-super-z",
        )


@pytest.mark.asyncio
async def test_assert_not_admin_role_blocks_super_role(
    require_test_db, session_factory,
):
    """非超管尝试操作 platform_super 角色 → ForbiddenError。"""
    await seed_rbac(session_factory)
    async with TestSessionLocal() as db:
        await _prepare(db, super_id="user-super-w", normal_id="user-normal-w")
        from sqlalchemy import select
        super_role = (await db.execute(
            select(Role).where(Role.role_key == "platform_super")
        )).scalar_one()
        with pytest.raises(ForbiddenError):
            await assert_not_admin_role(
                db,
                current_user_id="user-normal-w",
                target_role_id=super_role.id,
            )


@pytest.mark.asyncio
async def test_assert_not_admin_role_allows_non_super_role(
    require_test_db, session_factory,
):
    """非超管操作非 platform_super 角色 → 允许。"""
    await seed_rbac(session_factory)
    async with TestSessionLocal() as db:
        await _prepare(db, super_id="user-super-v", normal_id="user-normal-v")
        from sqlalchemy import select
        member_role = (await db.execute(
            select(Role).where(Role.role_key == "org_member")
        )).scalar_one()
        # 普通角色对非超管不限制
        await assert_not_admin_role(
            db,
            current_user_id="user-normal-v",
            target_role_id=member_role.id,
        )
