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
        from app.models.organization import Organization

        if not user.current_org_id:
            return None  # 用户尚未选择组织

        result = await db.execute(
            select(Organization).where(
                Organization.id == user.current_org_id,
                Organization.deleted_at.is_(None),
                Organization.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def ensure_user_has_org(
        self, user: User, db: AsyncSession,
    ) -> None:
        # EE 模式：不做自动分配，用户需被邀请或通过 OAuth 加入组织
        pass

    def is_multi_org(self) -> bool:
        return True