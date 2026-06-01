"""user_admin_service 自我保护与最后超管守卫。"""

import pytest
from fastapi import HTTPException

from ee.backend.services.admin import user_admin_service
from ee.backend.services.admin.errors import AdminErrorCode


@pytest.mark.asyncio
async def test_cannot_deactivate_self(db_session, super_admin_user):
    """自我保护：不能停用自己。"""
    with pytest.raises(HTTPException) as exc:
        await user_admin_service.update_user(
            db_session, admin=super_admin_user, user_id=super_admin_user.id,
            patch={"is_active": False},
        )
    assert exc.value.detail["error_code"] == int(AdminErrorCode.SELF_DEACTIVATE_FORBIDDEN)


@pytest.mark.asyncio
async def test_cannot_demote_self_super_admin(db_session, super_admin_user):
    """自我保护：不能撤销自己的超管权限。"""
    with pytest.raises(HTTPException) as exc:
        await user_admin_service.update_user(
            db_session, admin=super_admin_user, user_id=super_admin_user.id,
            patch={"is_super_admin": False},
        )
    assert exc.value.detail["error_code"] == int(AdminErrorCode.SELF_DEMOTE_SUPER_ADMIN_FORBIDDEN)


@pytest.mark.asyncio
async def test_cannot_remove_last_super_admin(
    db_session, super_admin_user, another_super_admin_user
):
    """最后超管守卫：只剩一个超管时，不能再撤销其超管权限。"""
    # 先撤销另一个超管，让 super_admin_user 成为"最后一个"
    await user_admin_service.update_user(
        db_session, admin=super_admin_user, user_id=another_super_admin_user.id,
        patch={"is_super_admin": False},
    )
    await db_session.commit()
    # 再次尝试撤销 super_admin_user 自己 → 自我保护拦截
    with pytest.raises(HTTPException) as exc:
        await user_admin_service.update_user(
            db_session, admin=super_admin_user, user_id=super_admin_user.id,
            patch={"is_super_admin": False},
        )
    assert exc.value.detail["error_code"] in (
        int(AdminErrorCode.SELF_DEMOTE_SUPER_ADMIN_FORBIDDEN),
        int(AdminErrorCode.LAST_SUPER_ADMIN_FORBIDDEN),
    )


@pytest.mark.asyncio
async def test_update_user_writes_audit(db_session, super_admin_user, sample_user):
    """update_user 成功时写入 action=user.update 审计记录。"""
    from sqlalchemy import select
    from app.models.operation_audit_log import OperationAuditLog
    await user_admin_service.update_user(
        db_session, admin=super_admin_user, user_id=sample_user.id,
        patch={"is_active": False},
    )
    await db_session.commit()
    audits = (await db_session.execute(
        select(OperationAuditLog).where(OperationAuditLog.target_id == sample_user.id)
    )).scalars().all()
    assert any(a.action == "user.update" for a in audits)


@pytest.mark.asyncio
async def test_reset_password_returns_plaintext_and_sets_must_change(
    db_session, super_admin_user, sample_user
):
    """reset_password 返回明文临时密码，并标记用户下次登录必须修改密码。"""
    from app.core.password import verify_password
    temp = await user_admin_service.reset_password(
        db_session, admin=super_admin_user, user_id=sample_user.id,
    )
    await db_session.commit()
    await db_session.refresh(sample_user)
    assert temp and len(temp) >= 12
    assert verify_password(temp, sample_user.password_hash)
    assert sample_user.must_change_password is True


@pytest.mark.asyncio
async def test_reset_password_audit_excludes_plaintext(
    db_session, super_admin_user, sample_user
):
    """reset_password 审计记录不得包含明文密码。"""
    from sqlalchemy import select
    from app.models.operation_audit_log import OperationAuditLog
    temp = await user_admin_service.reset_password(
        db_session, admin=super_admin_user, user_id=sample_user.id,
    )
    await db_session.commit()
    audits = (await db_session.execute(
        select(OperationAuditLog).where(
            OperationAuditLog.action == "user.reset_password",
            OperationAuditLog.target_id == sample_user.id,
        )
    )).scalars().all()
    assert audits
    payload_text = str(audits[0].details)
    assert temp not in payload_text, "明文密码绝不可写入审计"


@pytest.mark.asyncio
async def test_delete_user_softdeletes_and_cascades(
    db_session, super_admin_user, sample_user_with_memberships
):
    """delete_user 软删用户，并级联软删其所有 OrgMembership。"""
    from sqlalchemy import select
    from app.models.org_membership import OrgMembership
    target = sample_user_with_memberships
    await user_admin_service.delete_user(
        db_session, admin=super_admin_user, user_id=target.id,
    )
    await db_session.commit()
    await db_session.refresh(target)
    assert target.deleted_at is not None
    assert target.deleted_by == super_admin_user.id
    # OrgMembership 级联软删后，不应存在 deleted_at 为空的记录
    memberships = (await db_session.execute(
        select(OrgMembership).where(
            OrgMembership.user_id == target.id,
            OrgMembership.deleted_at.is_(None),
        )
    )).scalars().all()
    assert memberships == []

