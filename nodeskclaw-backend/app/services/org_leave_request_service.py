"""组织退出申请服务层。

与 org_join_request_service 对称的五个核心操作：
1. create_leave_request：成员对所属组织提交退出申请
2. list_my_leave_requests：用户查看自己的退出历史
3. cancel_my_leave_request：用户主动撤回 pending 退出申请
4. list_pending_for_reviewer：审核者按权限拉取待审列表
5. review_leave_request：审核者通过/拒绝

加入与退出的关键差别：
- approve 时执行 OrgMembership.soft_delete + on_member_removed hook
- 禁止"唯一 admin 退出"（避免组织无管理员）
- 禁止自审（审核者 ≠ 申请者）
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import hooks
from app.models.base import not_deleted
from app.models.org_leave_request import OrgLeaveRequest, OrgLeaveRequestStatus
from app.models.org_membership import OrgMembership, OrgRole
from app.models.organization import Organization
from app.models.user import User
from app.schemas.org_leave_request import LeaveRequestInfo
from app.services.member_hooks import get_member_hook

logger = logging.getLogger(__name__)


# ── 内部辅助 ──────────────────────────────────────────────


async def _attach_identity(
    db: AsyncSession,
    items: list[OrgLeaveRequest],
) -> list[LeaveRequestInfo]:
    """批量给退出申请注入申请者 name/email/当前角色 和组织 name/slug，避免 N+1。

    与 org_join_request_service._attach_identity 同模式，多取一个 OrgMembership.role
    供前端显示「申请退出者当前是 admin/member」。
    """
    if not items:
        return []

    user_ids = {it.user_id for it in items}
    org_ids = {it.org_id for it in items}

    user_rows = (await db.execute(
        select(User.id, User.name, User.email).where(User.id.in_(user_ids))
    )).all()
    user_by_id = {row[0]: (row[1], row[2]) for row in user_rows}

    org_rows = (await db.execute(
        select(Organization.id, Organization.name, Organization.slug).where(
            Organization.id.in_(org_ids),
        )
    )).all()
    org_by_id = {row[0]: (row[1], row[2]) for row in org_rows}

    # 批量查申请者在目标组织的当前角色（未被软删的 OrgMembership）
    member_rows = (await db.execute(
        select(OrgMembership.user_id, OrgMembership.org_id, OrgMembership.role).where(
            OrgMembership.user_id.in_(user_ids),
            OrgMembership.org_id.in_(org_ids),
            not_deleted(OrgMembership),
        )
    )).all()
    role_by_pair = {(row[0], row[1]): row[2] for row in member_rows}

    result: list[LeaveRequestInfo] = []
    for it in items:
        info = LeaveRequestInfo.model_validate(it)
        u = user_by_id.get(it.user_id)
        if u:
            info.requester_name, info.requester_email = u
        o = org_by_id.get(it.org_id)
        if o:
            info.org_name, info.org_slug = o
        info.requester_role = role_by_pair.get((it.user_id, it.org_id))
        result.append(info)
    return result


async def _is_org_admin(db: AsyncSession, user_id: str, org_id: str) -> bool:
    """判断 user_id 是否为 org_id 的组织管理员（OrgRole.admin）。"""
    result = await db.execute(
        select(OrgMembership).where(
            OrgMembership.user_id == user_id,
            OrgMembership.org_id == org_id,
            OrgMembership.role == OrgRole.admin,
            not_deleted(OrgMembership),
        )
    )
    return result.scalar_one_or_none() is not None


async def _count_active_admins(db: AsyncSession, org_id: str) -> int:
    """统计某组织当前 active admin 成员数（用于判断是否唯一 admin）。"""
    from sqlalchemy import func

    result = await db.execute(
        select(func.count(OrgMembership.id)).where(
            OrgMembership.org_id == org_id,
            OrgMembership.role == OrgRole.admin,
            not_deleted(OrgMembership),
        )
    )
    return int(result.scalar_one() or 0)


# ── 用户侧 ────────────────────────────────────────────────


async def create_leave_request(
    db: AsyncSession,
    user: User,
    org_id: str,
    reason: str | None,
) -> LeaveRequestInfo:
    """成员提交退出申请。

    校验链：组织存在 → 用户当前确实是该组织成员 → 无 pending 退出申请 → 写入。
    """
    org = (await db.execute(
        select(Organization).where(
            Organization.id == org_id,
            not_deleted(Organization),
        )
    )).scalar_one_or_none()
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": 40450,
                "message_key": "errors.leave_org.org_not_found",
                "message": "未找到对应组织",
            },
        )

    # 必须是该组织在册成员才能申请退出
    member = (await db.execute(
        select(OrgMembership).where(
            OrgMembership.user_id == user.id,
            OrgMembership.org_id == org_id,
            not_deleted(OrgMembership),
        )
    )).scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": 40350,
                "message_key": "errors.leave_org.not_member",
                "message": "您不是该组织成员，无法申请退出",
            },
        )

    # 已有 pending → 409
    existing = (await db.execute(
        select(OrgLeaveRequest).where(
            OrgLeaveRequest.user_id == user.id,
            OrgLeaveRequest.org_id == org_id,
            OrgLeaveRequest.status == OrgLeaveRequestStatus.pending,
            not_deleted(OrgLeaveRequest),
        )
    )).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": 40950,
                "message_key": "errors.leave_org.already_pending",
                "message": "已存在待审核的退出申请",
            },
        )

    req = OrgLeaveRequest(
        user_id=user.id,
        org_id=org_id,
        reason=(reason or "").strip() or None,
        status=OrgLeaveRequestStatus.pending,
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)

    await hooks.emit(
        "operation_audit",
        action="org.leave_request.submitted",
        target_type="org_leave_request",
        target_id=req.id,
        actor_id=user.id,
        org_id=org_id,
    )

    infos = await _attach_identity(db, [req])
    return infos[0]


async def list_my_leave_requests(
    db: AsyncSession,
    user: User,
) -> list[LeaveRequestInfo]:
    """列出我提交的全部退出申请（含历史终态）。"""
    rows = (await db.execute(
        select(OrgLeaveRequest)
        .where(
            OrgLeaveRequest.user_id == user.id,
            not_deleted(OrgLeaveRequest),
        )
        .order_by(OrgLeaveRequest.created_at.desc())
    )).scalars().all()
    return await _attach_identity(db, list(rows))


async def cancel_my_leave_request(
    db: AsyncSession,
    user: User,
    request_id: str,
) -> None:
    """申请者本人撤回 pending 退出申请：status → cancelled + soft_delete。"""
    req = (await db.execute(
        select(OrgLeaveRequest).where(
            OrgLeaveRequest.id == request_id,
            not_deleted(OrgLeaveRequest),
        )
    )).scalar_one_or_none()
    if req is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": 40451,
                "message_key": "errors.leave_org.request_not_found",
                "message": "退出申请不存在",
            },
        )
    if req.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": 40351,
                "message_key": "errors.leave_org.not_owner",
                "message": "只能撤回自己提交的退出申请",
            },
        )
    if req.status != OrgLeaveRequestStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": 40951,
                "message_key": "errors.leave_org.not_pending",
                "message": "申请已完结，无法撤回",
            },
        )

    req.status = OrgLeaveRequestStatus.cancelled
    req.soft_delete()
    await db.commit()

    await hooks.emit(
        "operation_audit",
        action="org.leave_request.cancelled",
        target_type="org_leave_request",
        target_id=req.id,
        actor_id=user.id,
        org_id=req.org_id,
    )


# ── 审核者侧 ──────────────────────────────────────────────


async def list_pending_for_reviewer(
    db: AsyncSession,
    current_user: User,
) -> list[LeaveRequestInfo]:
    """审核者权限过滤的退出申请列表（与 join 同 scoping 策略）。"""
    if getattr(current_user, "is_super_admin", False):
        rows = (await db.execute(
            select(OrgLeaveRequest)
            .where(
                OrgLeaveRequest.status == OrgLeaveRequestStatus.pending,
                not_deleted(OrgLeaveRequest),
            )
            .order_by(OrgLeaveRequest.created_at.desc())
        )).scalars().all()
        return await _attach_identity(db, list(rows))

    admin_org_rows = (await db.execute(
        select(OrgMembership.org_id).where(
            OrgMembership.user_id == current_user.id,
            OrgMembership.role == OrgRole.admin,
            not_deleted(OrgMembership),
        )
    )).all()
    admin_org_ids = [row[0] for row in admin_org_rows]
    if not admin_org_ids:
        return []

    rows = (await db.execute(
        select(OrgLeaveRequest)
        .where(
            OrgLeaveRequest.status == OrgLeaveRequestStatus.pending,
            OrgLeaveRequest.org_id.in_(admin_org_ids),
            not_deleted(OrgLeaveRequest),
        )
        .order_by(OrgLeaveRequest.created_at.desc())
    )).scalars().all()
    return await _attach_identity(db, list(rows))


async def review_leave_request(
    db: AsyncSession,
    current_user: User,
    request_id: str,
    action: str,
    note: str | None,
) -> LeaveRequestInfo:
    """审核者通过/拒绝退出申请。

    关键约束：
    1. 仅 pending 可审
    2. 审核者必须是该 org 的 admin（或超管）
    3. 审核者不能审自己的退出申请（防止 admin 自批自退）
    4. approve 前检查：若申请者是组织唯一 admin → 拒绝（要求先转让 admin）
    5. approve 时：软删 OrgMembership + on_member_removed hook
    """
    if action not in ("approve", "reject"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": 40051,
                "message_key": "errors.leave_org.invalid_action",
                "message": "审核动作无效",
            },
        )

    req = (await db.execute(
        select(OrgLeaveRequest).where(
            OrgLeaveRequest.id == request_id,
            not_deleted(OrgLeaveRequest),
        )
    )).scalar_one_or_none()
    if req is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": 40451,
                "message_key": "errors.leave_org.request_not_found",
                "message": "退出申请不存在",
            },
        )

    if req.status != OrgLeaveRequestStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": 40951,
                "message_key": "errors.leave_org.not_pending",
                "message": "该申请已被处理",
            },
        )

    is_super = getattr(current_user, "is_super_admin", False)
    if not is_super and not await _is_org_admin(db, current_user.id, req.org_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": 40352,
                "message_key": "errors.leave_org.not_reviewer",
                "message": "您无权审核该组织的退出申请",
            },
        )

    # 自审拦截：审核者不能审核自己的退出申请（防止 admin 自批自退）
    if current_user.id == req.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": 40353,
                "message_key": "errors.leave_org.self_review_forbidden",
                "message": "不能审核自己提交的退出申请，请联系其他管理员",
            },
        )

    now = datetime.now(timezone.utc)
    note_clean = (note or "").strip() or None

    if action == "approve":
        # 取当前 membership；如已不在册（被人捷足先登移除），幂等放行
        member = (await db.execute(
            select(OrgMembership).where(
                OrgMembership.user_id == req.user_id,
                OrgMembership.org_id == req.org_id,
                not_deleted(OrgMembership),
            )
        )).scalar_one_or_none()

        # 关键守卫：唯一 admin 不能退（避免组织变成无主）
        if member is not None and member.role == OrgRole.admin:
            admin_count = await _count_active_admins(db, req.org_id)
            if admin_count <= 1:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "error_code": 40952,
                        "message_key": "errors.leave_org.last_admin",
                        "message": "该成员是组织唯一管理员，请先将管理员转让给其他成员后再批准退出",
                    },
                )

        if member is not None:
            member.soft_delete()

        req.status = OrgLeaveRequestStatus.approved
    else:
        req.status = OrgLeaveRequestStatus.rejected

    req.reviewed_by = current_user.id
    req.reviewed_at = now
    req.review_note = note_clean
    await db.commit()
    await db.refresh(req)

    await hooks.emit(
        "operation_audit",
        action=f"org.leave_request.{req.status}",
        target_type="org_leave_request",
        target_id=req.id,
        actor_id=current_user.id,
        org_id=req.org_id,
        details={"requester_id": req.user_id, "note": note_clean},
    )

    if req.status == OrgLeaveRequestStatus.approved:
        try:
            await get_member_hook().on_member_removed(req.org_id, req.user_id)
        except Exception:
            logger.exception(
                "on_member_removed hook failed: org=%s user=%s",
                req.org_id, req.user_id,
            )

    infos = await _attach_identity(db, [req])
    return infos[0]
