"""Admin - Platform-managed Model Provider Keys (EE).

平台超管为指定组织下发/维护 LLM Key（is_platform_managed=True）。
组织 portal 端可见但只能勾选 allowed_models / 切换 is_active，敏感字段由本路由维护。

设计要点：
- 路由前缀已含完整 /orgs/{org_id}/platform-providers，挂载到 ee_admin_router
- 双守卫：上层 ee_admin_router 提供 require_feature(platform_admin) + require_super_admin_dep
- 唯一约束 (org_id, provider) WHERE deleted_at IS NULL：POST 若已存在软删行则复活，避免 race 409
- 所有写操作进 operation_audit，action 命名 platform_provider.{created/updated/deleted}
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import hooks
from app.core.deps import get_db
from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import get_current_user
from app.models.base import not_deleted
from app.models.org_llm_key import OrgModelProvider
from app.models.organization import Organization
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.llm import OrgModelProviderInfo
from app.services.codex_provider import mask_personal_key

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Schema ──────────────────────────────────────────────────


def _normalize_base_url(v: str | None) -> str | None:
    """与 app.schemas.llm._normalize_base_url 保持一致：缺协议时补 https://。"""
    if not v or not v.strip():
        return v
    v = v.strip()
    if not v.startswith(("http://", "https://")):
        v = f"https://{v}"
    return v


class PlatformProviderCreate(BaseModel):
    """平台超管下发平台托管 Key 的请求体。"""
    provider: str = Field(..., max_length=32)
    label: str | None = Field(None, max_length=128)
    api_key: str
    base_url: str | None = None
    api_type: str | None = None
    org_token_limit: int | None = None
    system_token_limit: int | None = None
    skip_ssl_verify: bool = False
    allowed_models: list[str] | None = None

    _normalize_base_url_field = field_validator("base_url", mode="before")(_normalize_base_url)


class PlatformProviderUpdate(BaseModel):
    """更新平台托管 Key（全字段可选）。is_platform_managed 不允许在此变更。"""
    label: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    api_type: str | None = None
    org_token_limit: int | None = None
    system_token_limit: int | None = None
    is_active: bool | None = None
    allowed_models: list[str] | None = None
    skip_ssl_verify: bool | None = None

    _normalize_base_url_field = field_validator("base_url", mode="before")(_normalize_base_url)


# ── 内部辅助 ─────────────────────────────────────────────────


def _mask(provider: str, key: str) -> str:
    return mask_personal_key(provider, key)


def _to_info(k: OrgModelProvider) -> OrgModelProviderInfo:
    """将 ORM 转为 DTO；admin 视图 usage_total_tokens 不在此处聚合，置 0。"""
    return OrgModelProviderInfo(
        id=k.id,
        org_id=k.org_id,
        provider=k.provider,
        label=k.label,
        api_key_masked=_mask(k.provider, k.api_key),
        base_url=k.base_url,
        api_type=k.api_type,
        org_token_limit=k.org_token_limit,
        system_token_limit=k.system_token_limit,
        is_active=k.is_active,
        skip_ssl_verify=k.skip_ssl_verify,
        allowed_models=k.allowed_models,
        is_platform_managed=k.is_platform_managed,
        usage_total_tokens=0,
        created_by=k.created_by,
    )


async def _get_org_or_404(db: AsyncSession, org_id: str) -> Organization:
    """校验目标组织存在且未软删，不存在直接 404。"""
    res = await db.execute(
        select(Organization).where(
            Organization.id == org_id,
            Organization.deleted_at.is_(None),
        )
    )
    org = res.scalar_one_or_none()
    if org is None:
        raise NotFoundError("组织不存在")
    return org


async def _find_existing_row(
    db: AsyncSession, org_id: str, provider: str, include_deleted: bool = False,
) -> OrgModelProvider | None:
    """按 (org_id, provider) 查找模型供应商行。

    include_deleted=True 时连软删行也返回，用于 POST 复活路径。
    """
    stmt = select(OrgModelProvider).where(
        OrgModelProvider.org_id == org_id,
        OrgModelProvider.provider == provider,
    )
    if not include_deleted:
        stmt = stmt.where(not_deleted(OrgModelProvider))
    res = await db.execute(stmt.limit(1))
    return res.scalar_one_or_none()


# ── Endpoints ────────────────────────────────────────────────


@router.get(
    "/orgs/{org_id}/platform-providers",
    response_model=ApiResponse[list[OrgModelProviderInfo]],
)
async def list_platform_providers(
    org_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_user),  # 上层路由已注入 super_admin 守卫
):
    """列出某组织的全部平台托管 Key（不含组织 BYOK 行）。"""
    await _get_org_or_404(db, org_id)
    res = await db.execute(
        select(OrgModelProvider)
        .where(
            OrgModelProvider.org_id == org_id,
            OrgModelProvider.is_platform_managed.is_(True),
            not_deleted(OrgModelProvider),
        )
        .order_by(OrgModelProvider.created_at)
    )
    return ApiResponse(data=[_to_info(k) for k in res.scalars().all()])


@router.post(
    "/orgs/{org_id}/platform-providers",
    response_model=ApiResponse[OrgModelProviderInfo],
)
async def create_platform_provider(
    org_id: str,
    body: PlatformProviderCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_user),
):
    """下发平台托管 Key。

    若已存在同 provider 的活跃行：返回 409（请走 PATCH）。
    若存在软删行：复活（清 deleted_at）并按新参数覆写，避免唯一约束 race。
    """
    await _get_org_or_404(db, org_id)

    # 先查活跃行
    active = await _find_existing_row(db, org_id, body.provider, include_deleted=False)
    if active is not None:
        raise ConflictError(
            f"{body.provider} 已存在平台托管或组织自带 Key，请改用 PATCH 更新",
            "errors.platform_provider.already_exists",
        )

    # 查软删行做复活
    soft_deleted = await _find_existing_row(db, org_id, body.provider, include_deleted=True)
    if soft_deleted is not None:
        # 复活：清 deleted_at + 覆写字段 + 标记为平台托管
        soft_deleted.deleted_at = None
        soft_deleted.label = body.label
        soft_deleted.api_key = body.api_key
        soft_deleted.base_url = body.base_url
        soft_deleted.api_type = body.api_type
        soft_deleted.org_token_limit = body.org_token_limit
        soft_deleted.system_token_limit = body.system_token_limit
        soft_deleted.skip_ssl_verify = body.skip_ssl_verify
        soft_deleted.allowed_models = body.allowed_models
        soft_deleted.is_platform_managed = True
        soft_deleted.is_active = True
        soft_deleted.created_by = admin.id
        key = soft_deleted
        revived = True
    else:
        key = OrgModelProvider(
            org_id=org_id,
            provider=body.provider,
            label=body.label,
            api_key=body.api_key,
            base_url=body.base_url,
            api_type=body.api_type,
            org_token_limit=body.org_token_limit,
            system_token_limit=body.system_token_limit,
            skip_ssl_verify=body.skip_ssl_verify,
            allowed_models=body.allowed_models,
            is_platform_managed=True,
            created_by=admin.id,
        )
        db.add(key)
        revived = False

    await db.commit()
    await db.refresh(key)
    logger.info(
        "平台 Key 下发: org=%s provider=%s revived=%s by=%s",
        org_id, body.provider, revived, admin.id,
    )
    await hooks.emit(
        "operation_audit",
        action="platform_provider.created",
        target_type="model_provider",
        target_id=key.id,
        actor_id=admin.id,
        org_id=org_id,
    )
    return ApiResponse(data=_to_info(key))


@router.patch(
    "/orgs/{org_id}/platform-providers/{key_id}",
    response_model=ApiResponse[OrgModelProviderInfo],
)
async def update_platform_provider(
    org_id: str,
    key_id: str,
    body: PlatformProviderUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_user),
):
    """平台超管更新平台托管 Key 的任意字段；is_platform_managed 强制保持 True。"""
    await _get_org_or_404(db, org_id)
    res = await db.execute(
        select(OrgModelProvider).where(
            OrgModelProvider.id == key_id,
            OrgModelProvider.org_id == org_id,
            OrgModelProvider.is_platform_managed.is_(True),
            not_deleted(OrgModelProvider),
        )
    )
    key = res.scalar_one_or_none()
    if key is None:
        raise NotFoundError("平台托管 Key 不存在")

    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(key, field, val)
    # 防御性兜底：即使 schema 未暴露 is_platform_managed，也确保始终为 True
    key.is_platform_managed = True

    await db.commit()
    await db.refresh(key)
    logger.info("平台 Key 更新: org=%s key=%s by=%s", org_id, key_id, admin.id)
    await hooks.emit(
        "operation_audit",
        action="platform_provider.updated",
        target_type="model_provider",
        target_id=key_id,
        actor_id=admin.id,
        org_id=org_id,
    )
    return ApiResponse(data=_to_info(key))


@router.delete(
    "/orgs/{org_id}/platform-providers/{key_id}",
    response_model=ApiResponse,
)
async def delete_platform_provider(
    org_id: str,
    key_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_user),
):
    """平台超管软删除平台托管 Key（设置 deleted_at）。"""
    await _get_org_or_404(db, org_id)
    res = await db.execute(
        select(OrgModelProvider).where(
            OrgModelProvider.id == key_id,
            OrgModelProvider.org_id == org_id,
            OrgModelProvider.is_platform_managed.is_(True),
            not_deleted(OrgModelProvider),
        )
    )
    key = res.scalar_one_or_none()
    if key is None:
        raise NotFoundError("平台托管 Key 不存在")

    key.soft_delete()
    await db.commit()
    logger.info("平台 Key 软删: org=%s key=%s by=%s", org_id, key_id, admin.id)
    await hooks.emit(
        "operation_audit",
        action="platform_provider.deleted",
        target_type="model_provider",
        target_id=key_id,
        actor_id=admin.id,
        org_id=org_id,
    )
    return ApiResponse(message="已删除")
