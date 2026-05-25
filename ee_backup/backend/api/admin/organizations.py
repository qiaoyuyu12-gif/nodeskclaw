"""Admin - Organization Management API (EE).

平台超管对所有租户组织进行 CRUD 操作。
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_feature, require_super_admin_dep
from app.core.security import get_current_user
from app.models.admin_membership import AdminMembership
from app.models.cluster import Cluster
from app.models.instance import Instance, InstanceStatus
from app.models.organization import Organization
from app.models.user import User
from app.schemas.organization import OrgInfo
from app.services.org.factory import get_org_provider

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Schema ──────────────────────────────────────────────────

class AdminOrgCreate(BaseModel):
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
    instance_count: int = 0
    total_cpu: str = "0"
    total_mem: str = "0"
    storage_used: str = "0"

    model_config = {"from_attributes": True}


# ── Endpoints ────────────────────────────────────────────────

@router.get("", response_model=list[AdminOrgInfo])
async def list_all_orgs(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    """列出所有组织（超管）。"""
    result = await db.execute(
        select(Organization).where(Organization.deleted_at.is_(None))
    )
    orgs = result.scalars().all()

    infos = []
    for org in orgs:
        info = AdminOrgInfo.model_validate(org)

        # 统计实例数
        count_result = await db.execute(
            select(func.count(Instance.id)).where(
                Instance.org_id == org.id,
                Instance.deleted_at.is_(None),
                Instance.status.in_([InstanceStatus.running, InstanceStatus.deploying]),
            )
        )
        info.instance_count = count_result.scalar_one() or 0

        # 统计资源使用
        used_result = await db.execute(
            select(
                func.coalesce(func.sum(Instance.cpu_limit), 0),
                func.coalesce(func.sum(Instance.mem_limit), 0),
                func.coalesce(func.sum(Instance.storage_size), 0),
            ).where(
                Instance.org_id == org.id,
                Instance.deleted_at.is_(None),
                Instance.status.in_([InstanceStatus.running, InstanceStatus.deploying]),
            )
        )
        used_cpu, used_mem, used_storage = used_result.one()
        info.total_cpu = f"{used_cpu}"
        info.total_mem = f"{used_mem}Gi"
        info.storage_used = f"{used_storage}Gi"

        infos.append(info)

    return infos


@router.post("", response_model=AdminOrgInfo)
async def create_org(
    body: AdminOrgCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    """创建组织（超管）。"""
    # 检查 slug 唯一性
    existing = await db.execute(
        select(Organization).where(Organization.slug == body.slug, Organization.deleted_at.is_(None))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": 40001, "message": "Slug 已存在"},
        )

    org = Organization(
        name=body.name,
        slug=body.slug,
        plan=body.plan,
        max_instances=body.max_instances,
        max_cpu_total=body.max_cpu_total,
        max_mem_total=body.max_mem_total,
        max_storage_total=body.max_storage_total,
        max_collaboration_depth=body.max_collaboration_depth,
        cluster_id=body.cluster_id,
        is_active=True,
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)

    logger.info("超管 %s 创建组织 %s (id=%s)", admin.id, org.name, org.id)
    return AdminOrgInfo.model_validate(org)


@router.get("/{org_id}", response_model=AdminOrgInfo)
async def get_org(
    org_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    """获取组织详情（超管）。"""
    result = await db.execute(
        select(Organization).where(Organization.id == org_id, Organization.deleted_at.is_(None))
    )
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="组织不存在")

    info = AdminOrgInfo.model_validate(org)

    count_result = await db.execute(
        select(func.count(Instance.id)).where(
            Instance.org_id == org.id,
            Instance.deleted_at.is_(None),
            Instance.status.in_([InstanceStatus.running, InstanceStatus.deploying]),
        )
    )
    info.instance_count = count_result.scalar_one() or 0

    used_result = await db.execute(
        select(
            func.coalesce(func.sum(Instance.cpu_limit), 0),
            func.coalesce(func.sum(Instance.mem_limit), 0),
            func.coalesce(func.sum(Instance.storage_size), 0),
        ).where(
            Instance.org_id == org.id,
            Instance.deleted_at.is_(None),
            Instance.status.in_([InstanceStatus.running, InstanceStatus.deploying]),
        )
    )
    used_cpu, used_mem, used_storage = used_result.one()
    info.total_cpu = f"{used_cpu}"
    info.total_mem = f"{used_mem}Gi"
    info.storage_used = f"{used_storage}Gi"

    return info


@router.put("/{org_id}", response_model=AdminOrgInfo)
async def update_org(
    org_id: str,
    body: AdminOrgUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    """更新组织（超管）。"""
    result = await db.execute(
        select(Organization).where(Organization.id == org_id, Organization.deleted_at.is_(None))
    )
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="组织不存在")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(org, key, value)

    await db.commit()
    await db.refresh(org)

    logger.info("超管 %s 更新组织 %s", admin.id, org_id)
    return AdminOrgInfo.model_validate(org)


@router.delete("/{org_id}")
async def delete_org(
    org_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    """删除组织（超管）。"""
    result = await db.execute(
        select(Organization).where(Organization.id == org_id, Organization.deleted_at.is_(None))
    )
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="组织不存在")

    # 检查是否有运行中的实例
    inst_count = await db.execute(
        select(func.count(Instance.id)).where(
            Instance.org_id == org_id,
            Instance.deleted_at.is_(None),
            Instance.status.in_([InstanceStatus.running, InstanceStatus.deploying]),
        )
    )
    if inst_count.scalar_one() > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": 40002, "message": "组织下仍有运行中的实例，请先删除"},
        )

    org.deleted_at = datetime.utcnow()
    await db.commit()

    logger.info("超管 %s 删除组织 %s", admin.id, org_id)
    return {"message": "组织已删除"}