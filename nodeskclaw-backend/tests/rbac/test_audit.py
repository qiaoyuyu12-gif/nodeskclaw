"""RBAC 审计开关 RBAC_AUDIT_ENABLED 行为。"""

import asyncio

import pytest
from sqlalchemy import func, select

from app.core.rbac.audit import log_decision_async
from app.core.rbac.scope import RbacScope
from app.models.rbac.permission_audit_log import PermissionAuditLog

from tests.rbac.conftest import TestSessionLocal


@pytest.mark.asyncio
async def test_audit_disabled_does_not_write(require_test_db, monkeypatch):
    """RBAC_AUDIT_ENABLED=False 时不写入。"""
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "RBAC_AUDIT_ENABLED", False)

    await log_decision_async(
        subject_type="user", subject_id="user-audit-1",
        perms_code="org:read", scope=RbacScope.org("org-audit-1"),
        decision="allow", reason="org_admin", request_id="req-1",
    )
    # 让 fire-and-forget 的 task 有机会执行
    await asyncio.sleep(0.1)

    async with TestSessionLocal() as db:
        count = (await db.execute(
            select(func.count()).select_from(PermissionAuditLog).where(
                PermissionAuditLog.subject_id == "user-audit-1",
            )
        )).scalar_one()
        assert count == 0


@pytest.mark.asyncio
async def test_audit_enabled_writes_record(require_test_db, monkeypatch):
    """RBAC_AUDIT_ENABLED=True 时写入一条 permission_audit_log。"""
    from app.core.config import settings as app_settings
    from app.core.rbac import audit as audit_mod
    from tests.rbac.conftest import TestSessionLocal

    monkeypatch.setattr(app_settings, "RBAC_AUDIT_ENABLED", True)
    # log_decision_async 内部默认用 app.core.deps.async_session_factory（指向应用主库），
    # 测试时改用 rbac fixture 的测试库 session_factory，避免连错库
    monkeypatch.setattr(audit_mod, "async_session_factory", TestSessionLocal)

    await log_decision_async(
        subject_type="user", subject_id="user-audit-2",
        perms_code="gene:publish",
        scope=RbacScope.org("org-audit-2"),
        decision="deny", reason="no_matching_role", request_id="req-2",
    )
    # 等异步 task 完成入库
    await asyncio.sleep(0.3)

    async with TestSessionLocal() as db:
        rows = (await db.execute(
            select(PermissionAuditLog).where(
                PermissionAuditLog.subject_id == "user-audit-2",
            )
        )).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.perms_code == "gene:publish"
        assert row.decision == "deny"
        assert row.reason == "no_matching_role"
        assert row.request_id == "req-2"
        assert row.scope_type == "org"
        assert row.scope_id == "org-audit-2"
