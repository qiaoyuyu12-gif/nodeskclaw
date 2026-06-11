"""Admin - Plan Management API (EE).

平台超管对套餐进行 CRUD 操作。
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_super_admin_dep
from app.core.security import get_current_user
from app.models.admin_membership import AdminMembership
from app.models.user import User
from ee.backend.models.plan import Plan

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Schema ──────────────────────────────────────────────────

class PlanCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=32)
    display_name: str = Field(..., min_length=1, max_length=64)
    description: str | None = None
    max_instances: int = Field(default=1, ge=1)
    max_cpu_per_instance: str = Field(default="2")
    max_mem_per_instance: str = Field(default="4Gi")
    max_storage_per_instance: str = Field(default="100Gi")
    max_total_cpu: str = Field(default="8")
    max_total_mem: str = Field(default="16Gi")
    max_total_storage: str = Field(default="500Gi")
    allowed_specs: list[str] = Field(default_factory=list)
    features: dict = Field(default_factory=dict)
    dedicated_cluster: bool = False
    price_monthly: int = Field(default=0, ge=0)
    price_yearly: int | None = None
    is_active: bool = True
    sort_order: int = 0


class PlanUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    max_instances: int | None = None
    max_cpu_per_instance: str | None = None
    max_mem_per_instance: str | None = None
    max_storage_per_instance: str | None = None
    max_total_cpu: str | None = None
    max_total_mem: str | None = None
    max_total_storage: str | None = None
    allowed_specs: list[str] | None = None
    features: dict | None = None
    dedicated_cluster: bool | None = None
    price_monthly: int | None = None
    price_yearly: int | None = None
    is_active: bool | None = None
    sort_order: int | None = None


class PlanInfo(BaseModel):
    id: str
    name: str
    display_name: str
    description: str | None = None
    max_instances: int
    max_cpu_per_instance: str
    max_mem_per_instance: str
    max_storage_per_instance: str
    max_total_cpu: str
    max_total_mem: str
    max_total_storage: str
    allowed_specs: list[str]
    features: dict
    dedicated_cluster: bool
    price_monthly: int
    price_yearly: int | None = None
    is_active: bool
    sort_order: int

    model_config = {"from_attributes": True}


# ── Endpoints ────────────────────────────────────────────────

@router.get("", response_model=list[PlanInfo])
async def list_plans(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    """列出所有套餐（超管）。"""
    result = await db.execute(
        select(Plan).order_by(Plan.sort_order, Plan.name)
    )
    plans = result.scalars().all()
    return [PlanInfo.model_validate(p) for p in plans]


@router.post("", response_model=PlanInfo)
async def create_plan(
    body: PlanCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    """创建套餐（超管）。"""
    # 检查 name 唯一性
    existing = await db.execute(
        select(Plan).where(Plan.name == body.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": 40001, "message": "套餐名称已存在"},
        )

    plan = Plan(**body.model_dump())
    db.add(plan)
    await db.commit()
    await db.refresh(plan)

    logger.info("超管 %s 创建套餐 %s", admin.id, plan.name)
    return PlanInfo.model_validate(plan)


@router.get("/{plan_name}", response_model=PlanInfo)
async def get_plan(
    plan_name: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    """获取套餐详情（超管）。"""
    result = await db.execute(
        select(Plan).where(Plan.name == plan_name)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="套餐不存在")
    return PlanInfo.model_validate(plan)


@router.put("/{plan_name}", response_model=PlanInfo)
async def update_plan(
    plan_name: str,
    body: PlanUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    """更新套餐（超管）。"""
    result = await db.execute(
        select(Plan).where(Plan.name == plan_name)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="套餐不存在")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(plan, key, value)

    plan.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(plan)

    logger.info("超管 %s 更新套餐 %s", admin.id, plan_name)
    return PlanInfo.model_validate(plan)


@router.delete("/{plan_name}")
async def delete_plan(
    plan_name: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    """删除套餐（超管）。"""
    from app.models.organization import Organization

    result = await db.execute(
        select(Plan).where(Plan.name == plan_name)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="套餐不存在")

    # 检查是否有组织正在使用此套餐
    usage_result = await db.execute(
        select(Organization).where(
            Organization.plan == plan_name,
            Organization.deleted_at.is_(None),
        )
    )
    if usage_result.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": 40002, "message": "有组织正在使用此套餐，无法删除"},
        )

    await db.delete(plan)
    await db.commit()

    logger.info("超管 %s 删除套餐 %s", admin.id, plan_name)
    return {"message": "套餐已删除"}