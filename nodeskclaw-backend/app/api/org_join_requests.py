"""组织加入申请 API：用户提交 + 撤回 + 管理员审核。

路由分两组：
- 用户侧（/org-join-requests）：登录用户即可访问，受 multi_org feature gate 保护
- 管理员侧（/admin/org-join-requests）：服务层做 super_admin / 组织 admin 双重判断
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_feature
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.org_join_request import (
    JoinRequestCreate,
    JoinRequestInfo,
    JoinRequestReview,
)
from app.services import org_join_request_service

# 整个特性受 multi_org 控制：CE 默认关闭 → 全部 403
router = APIRouter(dependencies=[Depends(require_feature("multi_org"))])


# ── 用户侧 ────────────────────────────────────────────────


@router.post("/org-join-requests", response_model=ApiResponse[JoinRequestInfo])
async def submit_join_request(
    body: JoinRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """提交一条加入组织申请。"""
    data = await org_join_request_service.create_join_request(
        db, user=current_user, org_slug=body.org_slug, reason=body.reason,
    )
    return ApiResponse(data=data)


@router.get("/org-join-requests/my", response_model=ApiResponse[list[JoinRequestInfo]])
async def list_my_join_requests(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查看自己提交的全部申请（含历史）。"""
    data = await org_join_request_service.list_my_join_requests(db, current_user)
    return ApiResponse(data=data)


@router.delete("/org-join-requests/{request_id}", response_model=ApiResponse)
async def cancel_my_join_request(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """撤回自己提交的 pending 申请。"""
    await org_join_request_service.cancel_my_join_request(
        db, current_user, request_id,
    )
    return ApiResponse(message="申请已撤回")


# ── 审核者侧 ──────────────────────────────────────────────


@router.get(
    "/admin/org-join-requests/pending",
    response_model=ApiResponse[list[JoinRequestInfo]],
)
async def list_pending_join_requests(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """审核中心待审列表：超管全部 / 组织 admin 仅本组织 / 其他用户空。"""
    data = await org_join_request_service.list_pending_for_reviewer(db, current_user)
    return ApiResponse(data=data)


@router.put(
    "/admin/org-join-requests/{request_id}/review",
    response_model=ApiResponse[JoinRequestInfo],
)
async def review_join_request(
    request_id: str,
    body: JoinRequestReview,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """审核单条 pending 申请：approve 通过 / reject 拒绝。"""
    data = await org_join_request_service.review_join_request(
        db, current_user, request_id, body.action, body.note,
    )
    return ApiResponse(data=data)
