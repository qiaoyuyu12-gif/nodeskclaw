"""审计 90 天保留清理测试。"""

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.operation_audit_log import OperationAuditLog
from app.services.audit_retention_runner import purge_expired_audit_logs


@pytest.mark.asyncio
async def test_purge_deletes_older_than_threshold(db_session):
    """超期记录（95 天前）应被删除，未超期记录（10 天前）应保留。"""
    old = OperationAuditLog(
        id=str(uuid.uuid4()),
        action="org.create",
        target_type="org",
        target_id="x",
        actor_type="user",
        actor_id="u",
        created_at=datetime.utcnow() - timedelta(days=95),
    )
    recent = OperationAuditLog(
        id=str(uuid.uuid4()),
        action="org.create",
        target_type="org",
        target_id="y",
        actor_type="user",
        actor_id="u",
        created_at=datetime.utcnow() - timedelta(days=10),
    )
    db_session.add_all([old, recent])
    await db_session.commit()

    deleted = await purge_expired_audit_logs(db_session, retention_days=90, batch_limit=100_000)
    await db_session.commit()

    rows = (await db_session.execute(select(OperationAuditLog))).scalars().all()
    assert deleted >= 1
    ids = {r.id for r in rows}
    assert recent.id in ids
    assert old.id not in ids


@pytest.mark.asyncio
async def test_purge_returns_zero_when_no_expired(db_session):
    """无超期记录时返回 0。"""
    recent = OperationAuditLog(
        id=str(uuid.uuid4()),
        action="user.login",
        target_type="user",
        target_id="u1",
        actor_type="user",
        actor_id="u1",
        created_at=datetime.utcnow() - timedelta(days=5),
    )
    db_session.add(recent)
    await db_session.commit()

    deleted = await purge_expired_audit_logs(db_session, retention_days=90, batch_limit=100_000)
    await db_session.commit()

    assert deleted == 0
