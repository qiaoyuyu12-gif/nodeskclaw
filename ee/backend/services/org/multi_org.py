"""MultiOrgProvider — EE 多组织模式。

用户可属于多个组织，通过 user.current_org_id 切换上下文。
支持组织创建、OAuth 开通、成员邀请。
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


class MultiOrgProvider(OrgProvider):
    """EE 多组织模式：用户通过 current_org_id 切换组织上下文。"""

    async def resolve_org_for_user(
        self, user: User, db: AsyncSession,
    ) -> Any:
        """按 OrgMembership 校验当前组织上下文，避免 current_org_id 指向用户不再是
        成员的组织（被踢出 / 主动退出后切换状态未同步）造成「组织信息错位 + 成员列表 403」。

        EE 与 CE 的差异：current_org_id 失效时不自动 fallback 到任意组织，而是
        返回 None 让前端走「选择组织」流程，符合多组织语义。
        """
        from app.models.base import not_deleted
        from app.models.org_membership import OrgMembership
        from app.models.organization import Organization

        if not user.current_org_id:
            return None  # 用户尚未选择组织

        # 组织存在 + 处于激活 + 用户确实是其在册成员，三者缺一不可
        result = await db.execute(
            select(Organization)
            .join(OrgMembership, OrgMembership.org_id == Organization.id)
            .where(
                Organization.id == user.current_org_id,
                not_deleted(Organization),
                Organization.is_active.is_(True),
                OrgMembership.user_id == user.id,
                not_deleted(OrgMembership),
            )
        )
        return result.scalars().first()

    async def ensure_user_has_org(
        self, user: User, db: AsyncSession,
    ) -> None:
        # EE 模式：不做自动分配，用户需被邀请或通过 OAuth 加入组织
        pass

    def is_multi_org(self) -> bool:
        return True