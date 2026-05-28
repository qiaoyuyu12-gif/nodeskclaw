"""Feature override endpoint — 超管管理组织级功能开关。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_super_admin_dep
from app.models.user import User
from app.schemas.common import ApiResponse, PaginatedResponse, Pagination
from ee.backend.services.admin import feature_admin_service

router = APIRouter()


class FeatureOverrideIn(BaseModel):
    """设置 feature override 的请求体。"""

    enabled: bool
    reason: str | None = None


@router.get("/features", response_model=ApiResponse[list[dict]])
async def list_features(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    """列出所有 feature + 各 feature 的有效 override 数量。"""
    return ApiResponse[list[dict]](
        data=await feature_admin_service.list_features_with_override_count(db)
    )


@router.get(
    "/features/{feature_id}/overrides",
    response_model=PaginatedResponse[dict],
)
async def list_feature_overrides(
    feature_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    """列出指定 feature 在所有组织上的有效 override（分页），含 org_name 与 set_by_name。"""
    data, total = await feature_admin_service.list_overrides_for_feature(
        db, feature_id=feature_id, page=page, page_size=page_size,
    )
    return PaginatedResponse[dict](
        data=data,
        pagination=Pagination(page=page, page_size=page_size, total=total),
    )


@router.get("/orgs/{org_id}/features", response_model=ApiResponse[list[dict]])
async def list_org_features(
    org_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    """列出指定组织的所有 feature effective 状态。"""
    return ApiResponse[list[dict]](
        data=await feature_admin_service.list_org_features(db, org_id=org_id)
    )


@router.put("/orgs/{org_id}/features/{feature_id}", response_model=ApiResponse[dict])
async def set_org_feature(
    org_id: str,
    feature_id: str,
    body: FeatureOverrideIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    """为指定组织设置 feature override，并返回 effective 状态。"""
    await feature_admin_service.set_override(
        db, admin=admin, org_id=org_id, feature_id=feature_id,
        enabled=body.enabled, reason=body.reason,
    )
    await db.commit()
    return ApiResponse[dict](
        data=await feature_admin_service.resolve_org_feature(
            db, org_id=org_id, feature_id=feature_id
        )
    )


@router.delete("/orgs/{org_id}/features/{feature_id}", response_model=ApiResponse[dict])
async def clear_org_feature(
    org_id: str,
    feature_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    """清除指定组织的 feature override，回落 edition 默认值。"""
    await feature_admin_service.clear_override(
        db, admin=admin, org_id=org_id, feature_id=feature_id,
    )
    await db.commit()
    return ApiResponse[dict](
        data=await feature_admin_service.resolve_org_feature(
            db, org_id=org_id, feature_id=feature_id
        )
    )
