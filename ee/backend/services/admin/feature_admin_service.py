"""Feature override 服务：组织级覆盖 + FeatureGate 合并。

超管可以通过本服务为特定组织强制启用/关闭某个 Feature，
覆盖 edition 默认值。写操作全部经由 audit_service.with_audit
落库审计记录。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.feature_gate import feature_gate
from app.models.admin_action import AdminAction
from app.models.organization_feature_override import OrganizationFeatureOverride
from app.models.user import User
from ee.backend.services.admin import audit_service
from ee.backend.services.admin.errors import AdminErrorCode, raise_admin_error

logger = logging.getLogger(__name__)


def _all_feature_ids() -> set[str]:
    """从 FeatureGate 拿到所有合法 feature_id（features.yaml + ee/features.yaml）。"""
    return {f["id"] for f in feature_gate.all_features()}


def _default_enabled(feature_id: str) -> bool:
    """edition_features 默认值：EE 模式下所有 EE feature 启用，CE 模式下禁用。"""
    return feature_gate.is_enabled(feature_id)


async def resolve_org_feature(
    db: AsyncSession, *, org_id: str, feature_id: str
) -> dict[str, Any]:
    """返回单个 feature 在指定组织上的 effective 状态。

    返回结构：
      {feature_id, enabled, source, default_enabled, reason?, set_by_user_id?, set_at?}
    source = "override" 表示有超管 override，source = "default" 表示走 edition 默认。
    """
    row = (
        await db.execute(
            select(OrganizationFeatureOverride).where(
                OrganizationFeatureOverride.org_id == org_id,
                OrganizationFeatureOverride.feature_id == feature_id,
                OrganizationFeatureOverride.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    default = _default_enabled(feature_id)
    if row is None:
        return {
            "feature_id": feature_id,
            "enabled": default,
            "source": "default",
            "default_enabled": default,
        }
    return {
        "feature_id": feature_id,
        "enabled": row.enabled,
        "source": "override",
        "default_enabled": default,
        "reason": row.reason,
        "set_by_user_id": row.set_by_user_id,
        "set_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def list_org_features(db: AsyncSession, *, org_id: str) -> list[dict[str, Any]]:
    """该组织所有 feature 的 effective 状态（前端 AdminOrgDetail Features tab 使用）。

    按 feature_id 排序，逐一调用 resolve_org_feature 合并 override 与默认值。
    """
    return [
        await resolve_org_feature(db, org_id=org_id, feature_id=fid)
        for fid in sorted(_all_feature_ids())
    ]


async def list_features_with_override_count(db: AsyncSession) -> list[dict[str, Any]]:
    """所有 feature + 覆盖计数（前端 AdminFeatureList 使用）。

    返回每个 feature 的基本信息 + 当前有效 override 数量，
    用于在 feature 列表中直观展示哪些 feature 被超管定制过。
    """
    # 聚合各 feature_id 的有效 override 数
    counts = dict(
        (
            await db.execute(
                select(
                    OrganizationFeatureOverride.feature_id,
                    sa_func.count(OrganizationFeatureOverride.id),
                )
                .where(OrganizationFeatureOverride.deleted_at.is_(None))
                .group_by(OrganizationFeatureOverride.feature_id)
            )
        ).all()
    )
    out: list[dict[str, Any]] = []
    for f in feature_gate.all_features():
        out.append({
            "feature_id": f["id"],
            "name": f.get("name", f["id"]),
            "description": f.get("description", ""),
            "default_enabled": _default_enabled(f["id"]),
            "override_count": counts.get(f["id"], 0),
        })
    return out


async def list_overrides_for_feature(
    db: AsyncSession, *, feature_id: str, page: int = 1, page_size: int = 20
) -> tuple[list[OrganizationFeatureOverride], int]:
    """某 feature 上的所有有效 override（分页）。

    先校验 feature_id 合法性，再分页查询该 feature 的所有未软删 override 行。
    返回 (rows, total_count)。
    """
    if feature_id not in _all_feature_ids():
        raise_admin_error(
            AdminErrorCode.FEATURE_ID_UNKNOWN,
            message_key="errors.admin.feature_id_unknown",
            message=f"Unknown feature_id: {feature_id}",
        )
    base = select(OrganizationFeatureOverride).where(
        OrganizationFeatureOverride.feature_id == feature_id,
        OrganizationFeatureOverride.deleted_at.is_(None),
    )
    total = (
        await db.execute(
            select(sa_func.count(OrganizationFeatureOverride.id)).where(
                OrganizationFeatureOverride.feature_id == feature_id,
                OrganizationFeatureOverride.deleted_at.is_(None),
            )
        )
    ).scalar_one()
    rows = (
        await db.execute(
            base.order_by(OrganizationFeatureOverride.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return list(rows), total


async def set_override(
    db: AsyncSession,
    *,
    admin: User,
    org_id: str,
    feature_id: str,
    enabled: bool,
    reason: str | None,
) -> OrganizationFeatureOverride:
    """写入或更新 (org_id, feature_id) 的 override 记录，并写审计日志。

    若已存在未删除的 override，则就地更新 enabled/reason/set_by_user_id；
    否则新建一条 OrganizationFeatureOverride 记录。
    整个操作包裹在 audit_service.with_audit 中，确保审计落库。
    """
    # 校验 feature_id 合法性
    if feature_id not in _all_feature_ids():
        raise_admin_error(
            AdminErrorCode.FEATURE_ID_UNKNOWN,
            message_key="errors.admin.feature_id_unknown",
            message=f"Unknown feature_id: {feature_id}",
        )
    # 查找已存在的未删除 override
    existing = (
        await db.execute(
            select(OrganizationFeatureOverride).where(
                OrganizationFeatureOverride.org_id == org_id,
                OrganizationFeatureOverride.feature_id == feature_id,
                OrganizationFeatureOverride.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    # 记录操作前状态，用于审计 diff
    before = {
        "enabled": existing.enabled if existing else _default_enabled(feature_id),
        "source": "override" if existing else "default",
    }
    async with audit_service.with_audit(
        db,
        action=AdminAction.FEATURE_OVERRIDE_SET,
        actor=admin,
        target_type="feature_override",
        target_id=f"{org_id}:{feature_id}",
        org_id=org_id,
        before=before,
        after={"enabled": enabled, "source": "override", "reason": reason},
    ):
        if existing:
            # 就地更新已有 override
            existing.enabled = enabled
            existing.reason = reason
            existing.set_by_user_id = admin.id
            row = existing
        else:
            # 新建 override 记录
            row = OrganizationFeatureOverride(
                org_id=org_id,
                feature_id=feature_id,
                enabled=enabled,
                reason=reason,
                set_by_user_id=admin.id,
            )
            db.add(row)
        await db.flush()
    return row


async def clear_override(
    db: AsyncSession, *, admin: User, org_id: str, feature_id: str
) -> None:
    """软删除 (org_id, feature_id) 的 override 记录，并写审计日志。

    若不存在未删除的 override，抛出 FEATURE_OVERRIDE_NOT_FOUND 错误。
    软删后该组织该 feature 将回落到 edition 默认值。
    """
    existing = (
        await db.execute(
            select(OrganizationFeatureOverride).where(
                OrganizationFeatureOverride.org_id == org_id,
                OrganizationFeatureOverride.feature_id == feature_id,
                OrganizationFeatureOverride.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if not existing:
        raise_admin_error(
            AdminErrorCode.FEATURE_OVERRIDE_NOT_FOUND,
            message_key="errors.admin.feature_override_not_found",
            message="Override not found",
        )
    before = {"enabled": existing.enabled, "reason": existing.reason}
    async with audit_service.with_audit(
        db,
        action=AdminAction.FEATURE_OVERRIDE_CLEAR,
        actor=admin,
        target_type="feature_override",
        target_id=f"{org_id}:{feature_id}",
        org_id=org_id,
        before=before,
        after={"enabled": _default_enabled(feature_id), "source": "default"},
    ):
        # 软删：设置 deleted_at 时间戳，保留历史记录
        existing.deleted_at = datetime.utcnow()
        await db.flush()
