"""RBAC 角色 ↔ 应用关联表 `role_apps`。

对齐 MOM `sys_role_app`。决定角色可访问哪些应用入口（PORTAL/ADMIN/OPEN_API/MCP_GATEWAY）。
前端门户页据此渲染应用卡片，路由守卫据此校验用户能否进入特定子系统。
"""

from sqlalchemy import ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class RoleApp(BaseModel):
    """角色 ↔ 应用关联。"""

    __tablename__ = "role_apps"
    __table_args__ = (
        # 同一角色不重复绑定同一应用
        Index(
            "uq_role_apps",
            "role_id",
            "app_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    # 角色 ID
    role_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("roles.id"), nullable=False,
    )
    # 应用 ID
    app_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("apps.id"), nullable=False,
    )
