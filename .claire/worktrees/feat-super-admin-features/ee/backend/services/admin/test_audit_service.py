"""audit_service.with_audit 行为测试。

覆盖三条路径：
  1. 成功路径 → 写入 success 审计行
  2. 失败路径 → 写入 failed 审计行并重新 raise
  3. 裸字符串 action → TypeError / ValueError 被拦截
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.admin_action import AdminAction
from app.models.operation_audit_log import OperationAuditLog
from ee.backend.services.admin import audit_service


@pytest.mark.asyncio
async def test_with_audit_success_writes_row(db_session, super_admin_user):
    """成功路径：with_audit 退出后应写入一条审计记录，字段值符合预期。"""
    async with audit_service.with_audit(
        db_session,
        action=AdminAction.ORG_CREATE,
        actor=super_admin_user,
        target_type="org",
        target_id="org-1",
        before=None,
        after={"name": "foo"},
        details={"reason": "test"},
    ):
        pass

    rows = (await db_session.execute(select(OperationAuditLog))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.action == "org.create"
    assert row.target_type == "org"
    assert row.target_id == "org-1"
    assert row.actor_id == super_admin_user.id
    assert row.details["after"] == {"name": "foo"}
    assert row.details["reason"] == "test"


@pytest.mark.asyncio
async def test_with_audit_failure_writes_failure_row(db_session, super_admin_user):
    """失败路径：异常发生时写入 status=failed 审计行，并重新 raise 原始异常。"""
    with pytest.raises(RuntimeError):
        async with audit_service.with_audit(
            db_session,
            action=AdminAction.ORG_DELETE,
            actor=super_admin_user,
            target_type="org",
            target_id="org-1",
        ):
            raise RuntimeError("boom")

    rows = (await db_session.execute(select(OperationAuditLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].details["status"] == "failed"
    assert "boom" in rows[0].details["error"]


@pytest.mark.asyncio
async def test_only_enum_action_accepted(db_session, super_admin_user):
    """字符串 action 必须被运行时校验拦截，不允许写入裸字符串审计。"""
    with pytest.raises((TypeError, ValueError)):
        async with audit_service.with_audit(
            db_session,
            action="org.create",  # 故意传裸字符串
            actor=super_admin_user,
            target_type="org",
            target_id="x",
        ):
            pass
