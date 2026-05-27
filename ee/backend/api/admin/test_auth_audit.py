"""auth 审计落库测试 — 登录成功 / 失败 / 登出三态。"""

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.password import hash_password
from app.models.operation_audit_log import OperationAuditLog
from app.models.user import User


# ── fixture ─────────────────────────────────────────────────

@pytest_asyncio.fixture
async def registered_user(db_session):
    """创建一个拥有明文密码 'correct-password' 的普通用户。"""
    user = User(
        name="Registered User",
        email="registered@example.com",
        password_hash=hash_password("correct-password"),
        is_active=True,
        is_super_admin=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


# ── 测试 ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_login_success_writes_audit(async_client, db_session, registered_user):
    """登录成功应写入 auth.login_success 审计行，actor_id == user.id。"""
    await async_client.post("/api/v1/auth/login", json={
        "email": registered_user.email,
        "password": "correct-password",
    })
    rows = (await db_session.execute(
        select(OperationAuditLog).where(
            OperationAuditLog.action == "auth.login_success"
        )
    )).scalars().all()
    assert rows, "登录成功后应存在 auth.login_success 审计行"
    assert rows[-1].actor_id == registered_user.id


@pytest.mark.asyncio
async def test_login_failure_writes_audit_without_password(
    async_client, db_session, registered_user
):
    """登录失败应写入 auth.login_failed 审计行，且 details 中绝不含密码明文。"""
    await async_client.post("/api/v1/auth/login", json={
        "email": registered_user.email,
        "password": "wrong-password",
    })
    rows = (await db_session.execute(
        select(OperationAuditLog).where(
            OperationAuditLog.action == "auth.login_failed"
        )
    )).scalars().all()
    assert rows, "登录失败后应存在 auth.login_failed 审计行"
    row = rows[-1]
    assert row.actor_type == "anonymous"
    assert row.actor_id == "anonymous"
    assert row.details.get("attempted_email") == registered_user.email
    # 密码明文严禁出现在 details 中
    payload = str(row.details)
    assert "wrong-password" not in payload


@pytest.mark.asyncio
async def test_logout_writes_audit(async_client, db_session, super_admin_user, super_admin_token):
    """登出应写入 auth.logout 审计行，actor_id == 当前用户 id。"""
    await async_client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    rows = (await db_session.execute(
        select(OperationAuditLog).where(
            OperationAuditLog.action == "auth.logout"
        )
    )).scalars().all()
    assert rows, "登出后应存在 auth.logout 审计行"
    assert rows[-1].actor_id == super_admin_user.id
