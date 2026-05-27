"""Admin - Organization Management API (EE).

平台超管对所有租户组织进行 CRUD 操作。
业务规则（slug 唯一校验、运行中实例拦截、审计）全部下沉到 org_admin_service。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_super_admin_dep
from app.models.instance import Instance, InstanceStatus
from app.models.organization import Organization
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.organization import OrgInfo
from ee.backend.services.admin import org_admin_service

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Schema ──────────────────────────────────────────────────

class AdminOrgCreate(BaseModel):
    """创建组织请求体。"""
    name: str = Field(..., min_length=1, max_length=128)
    slug: str = Field(..., min_length=1, max_length=128)
    plan: str = Field(default="free")
    max_instances: int = Field(default=1, ge=1)
    max_cpu_total: str = Field(default="4")
    max_mem_total: str = Field(default="8Gi")
    max_storage_total: str = Field(default="500Gi")
    max_collaboration_depth: int = Field(default=3, ge=1)
    cluster_id: str | None = None


class AdminOrgUpdate(BaseModel):
    """更新组织请求体（全部字段可选）。"""
    name: str | None = None
    plan: str | None = None
    is_active: bool | None = None
    max_instances: int | None = None
    max_cpu_total: str | None = None
    max_mem_total: str | None = None
    max_storage_total: str | None = None
    max_collaboration_depth: int | None = None
    cluster_id: str | None = None


class AdminOrgInfo(OrgInfo):
    """组织信息（含实例 & 资源聚合统计）。"""
    instance_count: int = 0
    total_cpu: str = "0"
    total_mem: str = "0"
    storage_used: str = "0"

    model_config = {"from_attributes": True}


# ── 内部辅助 ─────────────────────────────────────────────────

async def _enrich_org_stats(db: AsyncSession, info: AdminOrgInfo, org_id: str) -> None:
    """填充组织的实例数量与资源用量（查询装饰，不含业务规则）。"""
    # 统计活跃实例数
    count_result = await db.execute(
        select(func.count(Instance.id)).where(
            Instance.org_id == org_id,
            Instance.deleted_at.is_(None),
            Instance.status.in_([InstanceStatus.running, InstanceStatus.deploying]),
        )
    )
    info.instance_count = count_result.scalar_one() or 0

    # 统计 CPU / 内存 / 存储用量
    used_result = await db.execute(
        select(
            func.coalesce(func.sum(Instance.cpu_limit), 0),
            func.coalesce(func.sum(Instance.mem_limit), 0),
            func.coalesce(func.sum(Instance.storage_size), 0),
        ).where(
            Instance.org_id == org_id,
            Instance.deleted_at.is_(None),
            Instance.status.in_([InstanceStatus.running, InstanceStatus.deploying]),
        )
    )
    used_cpu, used_mem, used_storage = used_result.one()
    info.total_cpu = f"{used_cpu}"
    info.total_mem = f"{used_mem}Gi"
    info.storage_used = f"{used_storage}Gi"


# ── Endpoints ────────────────────────────────────────────────

@router.get("", response_model=ApiResponse[list[AdminOrgInfo]])
async def list_all_orgs(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    """列出所有组织（超管）。"""
    result = await db.execute(
        select(Organization).where(Organization.deleted_at.is_(None))
    )
    orgs = result.scalars().all()

    infos: list[AdminOrgInfo] = []
    for org in orgs:
        info = AdminOrgInfo.model_validate(org)
        await _enrich_org_stats(db, info, org.id)
        infos.append(info)

    return ApiResponse[list[AdminOrgInfo]](data=infos)


@router.post("", response_model=ApiResponse[AdminOrgInfo])
async def create_org(
    body: AdminOrgCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    """超管创建组织（业务规则全部在 service 层）。"""
    org = await org_admin_service.create_org(
        db,
        admin=admin,
        name=body.name,
        slug=body.slug,
        plan=body.plan,
        max_instances=body.max_instances,
        max_cpu_total=body.max_cpu_total,
        max_mem_total=body.max_mem_total,
        max_storage_total=body.max_storage_total,
        max_collaboration_depth=body.max_collaboration_depth,
        cluster_id=body.cluster_id,
    )
    await db.commit()
    await db.refresh(org)
    return ApiResponse[AdminOrgInfo](data=AdminOrgInfo.model_validate(org))


@router.get("/{org_id}", response_model=ApiResponse[AdminOrgInfo])
async def get_org(
    org_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    """获取组织详情（超管）。"""
    org = await org_admin_service.get_org(db, org_id=org_id)

    info = AdminOrgInfo.model_validate(org)
    await _enrich_org_stats(db, info, org.id)

    return ApiResponse[AdminOrgInfo](data=info)


@router.put("/{org_id}", response_model=ApiResponse[AdminOrgInfo])
async def update_org(
    org_id: str,
    body: AdminOrgUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    """超管更新组织（业务规则全部在 service 层）。"""
    org = await org_admin_service.update_org(
        db, admin=admin, org_id=org_id, patch=body.model_dump(exclude_unset=True)
    )
    await db.commit()
    await db.refresh(org)
    return ApiResponse[AdminOrgInfo](data=AdminOrgInfo.model_validate(org))


@router.delete("/{org_id}", response_model=ApiResponse[dict])
async def delete_org(
    org_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    """超管删除组织（业务规则全部在 service 层）。"""
    await org_admin_service.delete_org(db, admin=admin, org_id=org_id)
    await db.commit()
    return ApiResponse[dict](data={"deleted": True})
