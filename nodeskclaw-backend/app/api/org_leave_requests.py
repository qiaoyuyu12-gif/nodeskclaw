"""组织退出申请 API：用户提交 + 撤回 + 管理员审核。

与 org_join_requests.py 完全对称。两组路由：
- 用户侧（/org-leave-requests）
- 管理员侧（/admin/org-leave-requests）

整组受 multi_org feature gate 保护：CE 默认关闭。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_feature
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.org_leave_request import (
    LeaveRequestCreate,
    LeaveRequestInfo,
    LeaveRequestReview,
)
from app.services import org_leave_request_service

router = APIRouter(dependencies=[Depends(require_feature("multi_org"))])


# ── 用户侧 ────────────────────────────────────────────────


@router.post("/org-leave-requests", response_model=ApiResponse[LeaveRequestInfo])
async def submit_leave_request(
    body: LeaveRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """提交退出当前组织的申请。"""
    data = await org_leave_request_service.create_leave_request(
        db, user=current_user, org_id=body.org_id, reason=body.reason,
    )
    return ApiResponse(data=data)


@router.get("/org-leave-requests/my", response_model=ApiResponse[list[LeaveRequestInfo]])
async def list_my_leave_requests(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查看自己提交的退出申请历史。"""
    data = await org_leave_request_service.list_my_leave_requests(db, current_user)
    return ApiResponse(data=data)


@router.delete("/org-leave-requests/{request_id}", response_model=ApiResponse)
async def cancel_my_leave_request(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """撤回自己提交的 pending 退出申请。"""
    await org_leave_request_service.cancel_my_leave_request(db, current_user, request_id)
    return ApiResponse(message="退出申请已撤回")


# ── 审核者侧 ──────────────────────────────────────────────


@router.get(
    "/admin/org-leave-requests/pending",
    response_model=ApiResponse[list[LeaveRequestInfo]],
)
async def list_pending_leave_requests(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """审核中心退出申请待审列表。"""
    data = await org_leave_request_service.list_pending_for_reviewer(db, current_user)
    return ApiResponse(data=data)


@router.put(
    "/admin/org-leave-requests/{request_id}/review",
    response_model=ApiResponse[LeaveRequestInfo],
)
async def review_leave_request(
    request_id: str,
    body: LeaveRequestReview,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """审核单条退出申请：approve 软删 OrgMembership / reject 仅置状态。"""
    data = await org_leave_request_service.review_leave_request(
        db, current_user, request_id, body.action, body.note,
    )
    return ApiResponse(data=data)
