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
