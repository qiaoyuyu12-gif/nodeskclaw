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

    一次性查询该 org 所有 override，再在内存中与默认值 merge，消除 N+1。
    """
    # 单次查询该 org 所有未软删 override，按 feature_id 建立字典
    overrides = {
        row.feature_id: row
        for row in (
            await db.execute(
                select(OrganizationFeatureOverride).where(
                    OrganizationFeatureOverride.org_id == org_id,
                    OrganizationFeatureOverride.deleted_at.is_(None),
                )
            )
        ).scalars().all()
    }
    out: list[dict[str, Any]] = []
    for fid in sorted(_all_feature_ids()):
        default = _default_enabled(fid)
        row = overrides.get(fid)
        if row is None:
            out.append({
                "feature_id": fid,
                "enabled": default,
                "source": "default",
                "default_enabled": default,
            })
        else:
            out.append({
                "feature_id": fid,
                "enabled": row.enabled,
                "source": "override",
                "default_enabled": default,
                "reason": row.reason,
                "set_by_user_id": row.set_by_user_id,
                "set_at": row.updated_at.isoformat() if row.updated_at else None,
            })
    return out


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
) -> tuple[list[dict], int]:
    """某 feature 上的所有有效 override（分页），含 org_name 与 set_by_name。

    先校验 feature_id 合法性，再 JOIN Organization + User 一次性查询，
    返回 (list[dict], total_count)，dict 含 org_name 和 set_by_name 供前端展示。
    """
    from app.models.organization import Organization

    if feature_id not in _all_feature_ids():
        raise_admin_error(
            AdminErrorCode.FEATURE_ID_UNKNOWN,
            message_key="errors.admin.feature_id_unknown",
            message=f"Unknown feature_id: {feature_id}",
        )

    # 统计总数（不带 join，效率更高）
    total = (
        await db.execute(
            select(sa_func.count(OrganizationFeatureOverride.id)).where(
                OrganizationFeatureOverride.feature_id == feature_id,
                OrganizationFeatureOverride.deleted_at.is_(None),
            )
        )
    ).scalar_one()

    # JOIN Organization + User，一次查询获取 org_name 和操作人信息
    stmt = (
        select(
            OrganizationFeatureOverride,
            Organization.name.label("org_name"),
            User.name.label("user_name"),
            User.email.label("user_email"),
        )
        .join(Organization, OrganizationFeatureOverride.org_id == Organization.id)
        .outerjoin(User, OrganizationFeatureOverride.set_by_user_id == User.id)
        .where(
            OrganizationFeatureOverride.feature_id == feature_id,
            OrganizationFeatureOverride.deleted_at.is_(None),
        )
        .order_by(OrganizationFeatureOverride.updated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.execute(stmt)).all()

    # 构造 dict 列表，set_by_name 优先取 user.name，再取 user.email，最后降级为 user_id
    data = [
        {
            "org_id": r.OrganizationFeatureOverride.org_id,
            "org_name": r.org_name,
            "feature_id": feature_id,
            "enabled": r.OrganizationFeatureOverride.enabled,
            "reason": r.OrganizationFeatureOverride.reason,
            "set_by_user_id": r.OrganizationFeatureOverride.set_by_user_id,
            "set_by_name": (
                r.user_name
                or r.user_email
                or r.OrganizationFeatureOverride.set_by_user_id
            ),
            "set_at": (
                r.OrganizationFeatureOverride.updated_at.isoformat()
                if r.OrganizationFeatureOverride.updated_at
                else None
            ),
        }
        for r in rows
    ]
    return data, total


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
