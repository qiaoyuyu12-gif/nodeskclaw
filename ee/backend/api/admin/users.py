"""超管全局用户管理 endpoint。

所有业务规则（自我保护、最后超管守卫、级联软删等）均在 user_admin_service 中实现，
本层保持 thin：仅负责参数绑定、调用 service、返回统一响应。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func as sa_func
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_super_admin_dep
from app.models.org_membership import OrgMembership
from app.models.user import User
from app.schemas.common import ApiResponse, PaginatedResponse, Pagination
from ee.backend.services.admin import user_admin_service

router = APIRouter()


class AdminUserInfo(BaseModel):
    """超管视角的用户信息，包含组织数量统计。"""

    id: str
    email: str | None = None
    name: str
    is_active: bool
    is_super_admin: bool
    must_change_password: bool
    created_at: datetime
    org_count: int = 0

    model_config = {"from_attributes": True}


class AdminUserPatch(BaseModel):
    """用户可更新字段（仅允许 is_active / is_super_admin）。"""

    is_active: bool | None = None
    is_super_admin: bool | None = None


@router.get("", response_model=PaginatedResponse[AdminUserInfo])
async def list_users(
    q: str | None = Query(None, description="按邮箱或姓名模糊搜索"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    """分页查询全局用户列表，支持按邮箱/姓名搜索，批量统计每用户的组织数量。"""
    # 基础查询：排除软删用户
    stmt = select(User).where(User.deleted_at.is_(None))
    count_stmt = select(sa_func.count(User.id)).where(User.deleted_at.is_(None))

    # 可选模糊搜索：邮箱或姓名
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(User.email.ilike(like), User.name.ilike(like)))
        count_stmt = count_stmt.where(or_(User.email.ilike(like), User.name.ilike(like)))

    # 总数统计
    total = (await db.execute(count_stmt)).scalar_one()

    # 分页查询，按创建时间倒序
    rows = (
        await db.execute(
            stmt.order_by(User.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    # 批量统计每用户的 org_count（避免 N+1 查询）
    ids = [u.id for u in rows]
    if ids:
        counts = dict(
            (
                await db.execute(
                    select(OrgMembership.user_id, sa_func.count(OrgMembership.id))
                    .where(
                        OrgMembership.user_id.in_(ids),
                        OrgMembership.deleted_at.is_(None),
                    )
                    .group_by(OrgMembership.user_id)
                )
            ).all()
        )
    else:
        counts = {}

    # 组装响应，补充 org_count
    data = []
    for u in rows:
        info = AdminUserInfo.model_validate(u)
        info.org_count = counts.get(u.id, 0)
        data.append(info)

    return PaginatedResponse[AdminUserInfo](
        data=data,
        pagination=Pagination(page=page, page_size=page_size, total=total),
    )


@router.get("/{user_id}", response_model=ApiResponse[AdminUserInfo])
async def get_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    """按 ID 查询单个用户详情；不存在或已软删则返回 AdminErrorCode.USER_NOT_FOUND。"""
    u = (
        await db.execute(
            select(User).where(User.id == user_id, User.deleted_at.is_(None))
        )
    ).scalar_one_or_none()

    if not u:
        # 通过 raise_admin_error 抛出统一错误，而非裸 HTTPException
        from ee.backend.services.admin.errors import AdminErrorCode, raise_admin_error
        raise_admin_error(
            AdminErrorCode.USER_NOT_FOUND,
            message_key="errors.admin.user_not_found",
            message="User not found",
        )

    return ApiResponse[AdminUserInfo](data=AdminUserInfo.model_validate(u))


@router.put("/{user_id}", response_model=ApiResponse[AdminUserInfo])
async def update_user(
    user_id: str,
    body: AdminUserPatch,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    """更新用户 is_active / is_super_admin；service 自动拦截自我保护场景。"""
    u = await user_admin_service.update_user(
        db,
        admin=admin,
        user_id=user_id,
        patch=body.model_dump(exclude_unset=True),
    )
    await db.commit()
    await db.refresh(u)
    return ApiResponse[AdminUserInfo](data=AdminUserInfo.model_validate(u))


@router.post("/{user_id}/reset-password", response_model=ApiResponse[dict])
async def reset_password(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    """重置指定用户密码，返回明文临时密码；用户下次登录时强制修改。"""
    temp = await user_admin_service.reset_password(db, admin=admin, user_id=user_id)
    await db.commit()
    return ApiResponse[dict](data={"temp_password": temp})


@router.delete("/{user_id}", response_model=ApiResponse[dict])
async def delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    """软删除指定用户，并级联软删关联数据（OrgMembership、AdminMembership 等）。"""
    await user_admin_service.delete_user(db, admin=admin, user_id=user_id)
    await db.commit()
    return ApiResponse[dict](data={"deleted": True})
