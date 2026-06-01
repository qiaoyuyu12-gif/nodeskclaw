"""org_admin_service CRUD + 成员管理测试。

覆盖三个核心场景：
  1. slug 冲突时 create_org 抛 ORG_SLUG_CONFLICT
  2. 含运行中实例时 delete_org 抛 ORG_HAS_RUNNING_INSTANCES
  3. create_org 成功后写入 "org.create" 审计记录
"""

import pytest
from fastapi import HTTPException

from ee.backend.services.admin import org_admin_service
from ee.backend.services.admin.errors import AdminErrorCode


@pytest.mark.asyncio
async def test_create_org_slug_conflict(db_session, super_admin_user, sample_org):
    """slug 已存在时，create_org 必须抛 409 + ORG_SLUG_CONFLICT 错误码。"""
    with pytest.raises(HTTPException) as exc:
        await org_admin_service.create_org(
            db_session,
            admin=super_admin_user,
            name="dup",
            slug=sample_org.slug,  # 复用已存在 slug，触发冲突
            plan="free",
            max_instances=1,
            max_cpu_total="4",
            max_mem_total="8Gi",
            max_storage_total="500Gi",
            max_collaboration_depth=3,
            cluster_id=None,
        )
    assert exc.value.detail["error_code"] == int(AdminErrorCode.ORG_SLUG_CONFLICT)


@pytest.mark.asyncio
async def test_delete_org_with_running_instances_blocked(
    db_session, super_admin_user, sample_org_with_running_instance
):
    """含运行中实例的组织不允许删除，必须抛 409 + ORG_HAS_RUNNING_INSTANCES 错误码。"""
    with pytest.raises(HTTPException) as exc:
        await org_admin_service.delete_org(
            db_session,
            admin=super_admin_user,
            org_id=sample_org_with_running_instance.id,
        )
    assert exc.value.detail["error_code"] == int(AdminErrorCode.ORG_HAS_RUNNING_INSTANCES)


@pytest.mark.asyncio
async def test_create_org_writes_audit(db_session, super_admin_user):
    """create_org 成功后，必须在 operation_audit_logs 中写入 action="org.create" 的记录。"""
    from sqlalchemy import select

    from app.models.operation_audit_log import OperationAuditLog

    # 执行创建
    org = await org_admin_service.create_org(
        db_session,
        admin=super_admin_user,
        name="new",
        slug="new-org-1",
        plan="free",
        max_instances=1,
        max_cpu_total="4",
        max_mem_total="8Gi",
        max_storage_total="500Gi",
        max_collaboration_depth=3,
        cluster_id=None,
    )
    await db_session.commit()

    # 验证审计行存在
    audits = (
        await db_session.execute(
            select(OperationAuditLog).where(OperationAuditLog.target_id == org.id)
        )
    ).scalars().all()
    assert any(a.action == "org.create" for a in audits)


@pytest.mark.asyncio
async def test_add_member_duplicate_rejected(db_session, super_admin_user, sample_org, sample_user):
    """同一用户重复添加到同一组织时，第二次必须抛 409 + ORG_MEMBER_DUPLICATE 错误码。"""
    # 第一次成功添加
    await org_admin_service.add_member(
        db_session, admin=super_admin_user, org_id=sample_org.id,
        user_id=sample_user.id, role="member",
    )
    await db_session.commit()
    # 第二次重复添加，应被拦截
    with pytest.raises(HTTPException) as exc:
        await org_admin_service.add_member(
            db_session, admin=super_admin_user, org_id=sample_org.id,
            user_id=sample_user.id, role="member",
        )
    assert exc.value.detail["error_code"] == int(AdminErrorCode.ORG_MEMBER_DUPLICATE)


@pytest.mark.asyncio
async def test_remove_last_org_admin_rejected(db_session, super_admin_user, sample_org_with_single_admin):
    """移除 org 最后一个 admin 成员时，必须抛 409 + ORG_LAST_ADMIN_FORBIDDEN 错误码。"""
    org, admin_user = sample_org_with_single_admin
    with pytest.raises(HTTPException) as exc:
        await org_admin_service.remove_member(
            db_session, admin=super_admin_user, org_id=org.id, user_id=admin_user.id,
        )
    assert exc.value.detail["error_code"] == int(AdminErrorCode.ORG_LAST_ADMIN_FORBIDDEN)
