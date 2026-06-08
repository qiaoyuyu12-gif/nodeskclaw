"""SingleOrgProvider — CE 单组织模式。

系统维护一个唯一的默认组织，所有用户自动归属。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.org.provider import OrgProvider

if TYPE_CHECKING:
    from app.models.user import User

logger = logging.getLogger(__name__)

DEFAULT_ORG_SLUG = "default"
DEFAULT_ORG_NAME = "Default Organization"


class SingleOrgProvider(OrgProvider):

    async def resolve_org_for_user(
        self, user: User, db: AsyncSession,
    ) -> Any:
        """解析用户所在组织，严格按 OrgMembership 校验，避免 current_org_id 跟实际归属脱节。

        历史 bug：当 user.current_org_id 指向一个 user 不是 member 的 org 时，
        旧实现会直接返回该 org，导致前端组织信息卡片显示错位 + 成员列表 403。

        新流程：
          1. current_org_id 存在且用户确实是该 org 成员 → 返回
          2. current_org_id 失效（org 已删 / 用户不是 member）→ 按 OrgMembership
             找该用户实际归属的首个 org，并修正 user.current_org_id
          3. 用户完全没有 OrgMembership → CE 单组织兜底（_get_or_create_default）
        """
        from app.models.organization import Organization

        if user.current_org_id:
            org = await self._get_org_if_member(db, user.id, user.current_org_id)
            if org:
                return org

        # current_org_id 失效：按 membership 找首个实际归属的 org
        actual = await self._resolve_first_membership_org(db, user.id)
        if actual:
            user.current_org_id = actual.id
            await db.commit()
            logger.info(
                "CE 模式：用户 %s 的 current_org_id 与 OrgMembership 不一致，"
                "已自动修正为 %s", user.id, actual.id,
            )
            return actual

        return await self._get_or_create_default(db)

    async def _get_org_if_member(
        self, db: AsyncSession, user_id: str, org_id: str,
    ) -> Any:
        """仅当 user 是该 org 未删除成员时才返回 Organization，否则返回 None。"""
        from app.models.base import not_deleted
        from app.models.org_membership import OrgMembership
        from app.models.organization import Organization

        # 一条 join 查询：确保 org 存在 + user 是 member
        result = await db.execute(
            select(Organization)
            .join(OrgMembership, OrgMembership.org_id == Organization.id)
            .where(
                Organization.id == org_id,
                not_deleted(Organization),
                OrgMembership.user_id == user_id,
                not_deleted(OrgMembership),
            )
        )
        return result.scalars().first()

    async def _resolve_first_membership_org(
        self, db: AsyncSession, user_id: str,
    ) -> Any:
        """按时间倒序找 user 实际归属的首个未删除 org（用于 current_org_id 失效兜底）。"""
        from app.models.base import not_deleted
        from app.models.org_membership import OrgMembership
        from app.models.organization import Organization

        result = await db.execute(
            select(Organization)
            .join(OrgMembership, OrgMembership.org_id == Organization.id)
            .where(
                OrgMembership.user_id == user_id,
                not_deleted(OrgMembership),
                not_deleted(Organization),
            )
            .order_by(OrgMembership.created_at.asc())
            .limit(1)
        )
        return result.scalars().first()

    async def ensure_user_has_org(
        self, user: User, db: AsyncSession,
    ) -> None:
        org = await self._get_or_create_default(db)

        from app.models.base import not_deleted
        from app.models.org_membership import OrgMembership, OrgRole

        result = await db.execute(
            select(OrgMembership).where(
                OrgMembership.user_id == user.id,
                OrgMembership.org_id == org.id,
                not_deleted(OrgMembership),
            )
        )
        if not result.scalar_one_or_none():
            db.add(OrgMembership(
                user_id=user.id, org_id=org.id, role=OrgRole.admin,
            ))
            # RBAC 双写：org_admin grant 到 subject_roles
            from app.services.rbac_sync import grant_role
            await grant_role(
                db, subject_type="user", subject_id=user.id,
                role_key="org_admin", scope_type="org", scope_id=org.id,
                granted_reason="single_org_auto_join",
            )
            logger.info("CE 模式：自动将用户 %s 加入默认组织", user.id)

        user.current_org_id = org.id
        await db.commit()

    def is_multi_org(self) -> bool:
        return False

    async def _get_or_create_default(self, db: AsyncSession) -> Any:
        """CE 单组织模式兜底：返回系统中第一个存在的活跃组织；都没有时才新建。

        历史实现按 slug='default' 硬查，但 seed 已将默认 slug 改为从
        INIT_ADMIN_ACCOUNT 派生（如 "admin"），按旧逻辑会找不到 → 二次创建一条
        重复组织。改为"取首个活跃组织"，与 CE 单组织语义一致，且兼容已被
        rename 的组织。
        """
        from app.models.organization import Organization

        result = await db.execute(
            select(Organization).where(
                Organization.deleted_at.is_(None),
            ).order_by(Organization.created_at.asc()).limit(1)
        )
        org = result.scalar_one_or_none()
        if org:
            return org

        # 真正首启动 + seed 未跑（极少见，例如测试环境）才走到这里；
        # 名字保留旧 hardcode，由 seed.py 后续 rename 阶段统一处理
        org = Organization(
            name=DEFAULT_ORG_NAME,
            slug=DEFAULT_ORG_SLUG,
            is_active=True,
        )
        db.add(org)
        await db.commit()
        await db.refresh(org)
        logger.info("CE 模式：自动创建默认组织 id=%s", org.id)
        return org
