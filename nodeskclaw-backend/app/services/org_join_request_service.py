"""组织加入申请服务层。

涵盖五个核心操作：
1. create_join_request：用户按 org_slug 提交申请
2. list_my_join_requests：用户查看自己的申请历史
3. cancel_my_join_request：用户主动撤回 pending 申请
4. list_pending_for_reviewer：审核者拉取待审列表（按角色 scoping）
5. review_join_request：审核者通过/拒绝单条申请

权限模型参考 gene_service.get_pending_review_genes / review_gene：
- 平台超管：可见所有 org 的 pending；可审核任意
- 任意组织 admin：仅可见/审核其管理的 org 下的 pending
- 普通用户：可提交申请、查/撤回自己的申请；不可见他人申请

approve 时会创建 OrgMembership(role='member') 并触发 on_member_joined hook。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import hooks
from app.models.base import not_deleted
from app.models.org_join_request import OrgJoinRequest, OrgJoinRequestStatus
from app.models.org_membership import OrgMembership, OrgRole
from app.models.organization import Organization
from app.models.user import User
from app.schemas.org_join_request import JoinRequestInfo
from app.services.member_hooks import get_member_hook

logger = logging.getLogger(__name__)


# ── 内部辅助 ──────────────────────────────────────────────


async def _attach_identity(
    db: AsyncSession,
    items: list[OrgJoinRequest],
) -> list[JoinRequestInfo]:
    """批量给申请列表注入申请者 name/email 和组织 name/slug，避免 N+1。

    参考 gene_service._attach_uploader_identity 的实现：一次性按所有 user_id /
    org_id 批量拿 User、Organization，失效行（已删除等）保持 None，前端三级回退。
    """
    if not items:
        return []

    user_ids = {it.user_id for it in items}
    org_ids = {it.org_id for it in items}

    # 一次性批量查申请者身份
    user_rows = (await db.execute(
        select(User.id, User.name, User.email).where(User.id.in_(user_ids))
    )).all()
    user_by_id = {row[0]: (row[1], row[2]) for row in user_rows}

    # 一次性批量查目标组织信息
    org_rows = (await db.execute(
        select(Organization.id, Organization.name, Organization.slug).where(
            Organization.id.in_(org_ids),
        )
    )).all()
    org_by_id = {row[0]: (row[1], row[2]) for row in org_rows}

    result: list[JoinRequestInfo] = []
    for it in items:
        info = JoinRequestInfo.model_validate(it)
        u = user_by_id.get(it.user_id)
        if u:
            info.requester_name, info.requester_email = u
        o = org_by_id.get(it.org_id)
        if o:
            info.org_name, info.org_slug = o
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


# ── 用户侧 ────────────────────────────────────────────────


async def create_join_request(
    db: AsyncSession,
    user: User,
    org_slug: str,
    reason: str | None,
) -> JoinRequestInfo:
    """用户按组织 slug 提交加入申请。

    校验链：slug 存在且组织未停用 → 用户未加入该组织 → 同 org 无 pending → 写入。
    并发场景下 partial unique 索引会兜底（违反时返回 409）。
    """
    slug = (org_slug or "").strip()
    if not slug:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": 40040,
                "message_key": "errors.join_org.slug_required",
                "message": "请填写组织标识",
            },
        )

    # 1. 按 slug 查组织：Organization.slug 是全局 unique，正常 first() 即可
    org = (await db.execute(
        select(Organization).where(
            Organization.slug == slug,
            not_deleted(Organization),
        )
    )).scalars().first()
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": 40440,
                "message_key": "errors.join_org.org_not_found",
                "message": "未找到对应组织",
            },
        )

    # 2. 组织停用拒绝接收新申请
    if not org.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": 40341,
                "message_key": "errors.join_org.org_inactive",
                "message": "该组织已停用，无法申请加入",
            },
        )

    # 3. 已是该组织成员 → 409
    existing_member = (await db.execute(
        select(OrgMembership).where(
            OrgMembership.user_id == user.id,
            OrgMembership.org_id == org.id,
            not_deleted(OrgMembership),
        )
    )).scalar_one_or_none()
    if existing_member is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": 40940,
                "message_key": "errors.join_org.already_member",
                "message": "您已是该组织成员",
            },
        )

    # 4. 已有 pending 申请 → 409（不重复打扰审核者）
    existing_pending = (await db.execute(
        select(OrgJoinRequest).where(
            OrgJoinRequest.user_id == user.id,
            OrgJoinRequest.org_id == org.id,
            OrgJoinRequest.status == OrgJoinRequestStatus.pending,
            not_deleted(OrgJoinRequest),
        )
    )).scalar_one_or_none()
    if existing_pending is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": 40941,
                "message_key": "errors.join_org.already_pending",
                "message": "已存在待审核的申请，请耐心等待",
            },
        )

    # 5. 写入新申请
    req = OrgJoinRequest(
        user_id=user.id,
        org_id=org.id,
        reason=(reason or "").strip() or None,
        status=OrgJoinRequestStatus.pending,
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)

    # 操作审计：用户提交申请
    await hooks.emit(
        "operation_audit",
        action="org.join_request.submitted",
        target_type="org_join_request",
        target_id=req.id,
        actor_id=user.id,
        org_id=org.id,
    )

    infos = await _attach_identity(db, [req])
    return infos[0]


async def list_my_join_requests(
    db: AsyncSession,
    user: User,
) -> list[JoinRequestInfo]:
    """列出我自己提交的全部申请（含历史终态），按时间倒序。"""
    rows = (await db.execute(
        select(OrgJoinRequest)
        .where(
            OrgJoinRequest.user_id == user.id,
            not_deleted(OrgJoinRequest),
        )
        .order_by(OrgJoinRequest.created_at.desc())
    )).scalars().all()
    return await _attach_identity(db, list(rows))


async def cancel_my_join_request(
    db: AsyncSession,
    user: User,
    request_id: str,
) -> None:
    """申请者本人撤回 pending 申请：status → cancelled + soft_delete。

    非本人或非 pending 状态 → 403/409。"""
    req = (await db.execute(
        select(OrgJoinRequest).where(
            OrgJoinRequest.id == request_id,
            not_deleted(OrgJoinRequest),
        )
    )).scalar_one_or_none()
    if req is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": 40441,
                "message_key": "errors.join_org.request_not_found",
                "message": "申请不存在",
            },
        )
    if req.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": 40342,
                "message_key": "errors.join_org.not_owner",
                "message": "只能撤回自己提交的申请",
            },
        )
    if req.status != OrgJoinRequestStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": 40942,
                "message_key": "errors.join_org.not_pending",
                "message": "申请已完结，无法撤回",
            },
        )

    req.status = OrgJoinRequestStatus.cancelled
    req.soft_delete()
    await db.commit()

    await hooks.emit(
        "operation_audit",
        action="org.join_request.cancelled",
        target_type="org_join_request",
        target_id=req.id,
        actor_id=user.id,
        org_id=req.org_id,
    )


# ── 审核者侧 ──────────────────────────────────────────────


async def list_pending_for_reviewer(
    db: AsyncSession,
    current_user: User,
) -> list[JoinRequestInfo]:
    """按审核者权限过滤待审申请，参考 gene_service.get_pending_review_genes。

    - super_admin：全部 pending
    - 任意 OrgRole.admin：仅其管理的 org 下的 pending
    - 普通用户：空列表
    """
    # 超管 → 全部
    if getattr(current_user, "is_super_admin", False):
        rows = (await db.execute(
            select(OrgJoinRequest)
            .where(
                OrgJoinRequest.status == OrgJoinRequestStatus.pending,
                not_deleted(OrgJoinRequest),
            )
            .order_by(OrgJoinRequest.created_at.desc())
        )).scalars().all()
        return await _attach_identity(db, list(rows))

    # 普通用户 → 拿其作为 admin 的所有 org_id
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
        select(OrgJoinRequest)
        .where(
            OrgJoinRequest.status == OrgJoinRequestStatus.pending,
            OrgJoinRequest.org_id.in_(admin_org_ids),
            not_deleted(OrgJoinRequest),
        )
        .order_by(OrgJoinRequest.created_at.desc())
    )).scalars().all()
    return await _attach_identity(db, list(rows))


async def review_join_request(
    db: AsyncSession,
    current_user: User,
    request_id: str,
    action: str,
    note: str | None,
) -> JoinRequestInfo:
    """审核者通过/拒绝单条 pending 申请。

    权限：当前用户必须是该 request.org_id 的 OrgRole.admin，或平台超管。
    approve 流程：
      1. 校验申请仍是 pending
      2. 校验目标组织仍存在且 active
      3. 幂等创建 OrgMembership(role='member')；如已存在则跳过
      4. 状态置 approved + 回填 reviewed_by/reviewed_at/review_note
      5. 触发 on_member_joined hook + operation_audit
    reject 流程：仅状态置 rejected + 回填审核信息 + operation_audit。
    """
    if action not in ("approve", "reject"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": 40041,
                "message_key": "errors.join_org.invalid_action",
                "message": "审核动作无效",
            },
        )

    req = (await db.execute(
        select(OrgJoinRequest).where(
            OrgJoinRequest.id == request_id,
            not_deleted(OrgJoinRequest),
        )
    )).scalar_one_or_none()
    if req is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": 40441,
                "message_key": "errors.join_org.request_not_found",
                "message": "申请不存在",
            },
        )

    # 状态校验：仅 pending 可审核
    if req.status != OrgJoinRequestStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": 40942,
                "message_key": "errors.join_org.not_pending",
                "message": "该申请已被处理",
            },
        )

    # 权限校验：超管或目标组织 admin
    is_super = getattr(current_user, "is_super_admin", False)
    if not is_super and not await _is_org_admin(db, current_user.id, req.org_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": 40343,
                "message_key": "errors.join_org.not_reviewer",
                "message": "您无权审核该组织的申请",
            },
        )

    now = datetime.now(timezone.utc)
    note_clean = (note or "").strip() or None

    if action == "approve":
        # 目标组织仍可用？停用组织不应再放人进来
        org = (await db.execute(
            select(Organization).where(
                Organization.id == req.org_id,
                not_deleted(Organization),
            )
        )).scalar_one_or_none()
        if org is None or not org.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error_code": 40341,
                    "message_key": "errors.join_org.org_inactive",
                    "message": "目标组织已停用，无法批准",
                },
            )

        # 幂等：如该用户已是成员（并发场景），跳过插入
        existing_member = (await db.execute(
            select(OrgMembership).where(
                OrgMembership.user_id == req.user_id,
                OrgMembership.org_id == req.org_id,
                not_deleted(OrgMembership),
            )
        )).scalar_one_or_none()
        if existing_member is None:
            db.add(OrgMembership(
                user_id=req.user_id,
                org_id=req.org_id,
                role=OrgRole.member,
            ))

        req.status = OrgJoinRequestStatus.approved
    else:
        req.status = OrgJoinRequestStatus.rejected

    req.reviewed_by = current_user.id
    req.reviewed_at = now
    req.review_note = note_clean
    await db.commit()
    await db.refresh(req)

    # 操作审计（无论 approve/reject 都记录）
    await hooks.emit(
        "operation_audit",
        action=f"org.join_request.{req.status}",
        target_type="org_join_request",
        target_id=req.id,
        actor_id=current_user.id,
        org_id=req.org_id,
        details={"requester_id": req.user_id, "note": note_clean},
    )

    # approve 才触发成员钩子，并仅在新建 membership 时调用
    if req.status == OrgJoinRequestStatus.approved:
        try:
            await get_member_hook().on_member_joined(
                req.org_id, req.user_id, OrgRole.member,
            )
        except Exception:
            logger.exception(
                "on_member_joined hook failed: org=%s user=%s",
                req.org_id, req.user_id,
            )

    infos = await _attach_identity(db, [req])
    return infos[0]
