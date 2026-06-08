"""RBAC 角色 ↔ 菜单（含按钮权限）关联表 `role_menus`。

对齐 MOM `sys_role_menu`。一条记录 = 一个角色被授予使用某个菜单 / 按钮的权限。
权限解析时通过 `roles → role_menus → menus.perms` 三层 join 得到角色拥有的全部权限点。
"""

from sqlalchemy import ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class RoleMenu(BaseModel):
    """角色 ↔ 菜单关联。"""

    __tablename__ = "role_menus"
    __table_args__ = (
        # 同一角色不重复绑定同一菜单
        Index(
            "uq_role_menus",
            "role_id",
            "menu_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # 反查：角色拥有哪些菜单（resolver 主路径）
        Index("ix_role_menus_role_id", "role_id"),
        # 反查：菜单被哪些角色拥有（用于权限审计）
        Index("ix_role_menus_menu_id", "menu_id"),
    )

    # 角色 ID
    role_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("roles.id"), nullable=False,
    )
    # 菜单 ID（可指向 M/C/F 任一类型）
    menu_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("menus.id"), nullable=False,
    )
