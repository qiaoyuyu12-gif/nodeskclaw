"""RBAC 菜单 / 按钮 / 权限点三合一表 `menus`（对齐 MOM `sys_menu`）。

菜单类型 `menu_type` 三种：
  - `M`(Directory)：目录节点，纯容器，无路由
  - `C`(Catalog/Page)：菜单页，对应前端路由
  - `F`(Function)：按钮 / 权限点，无路由，仅承载 `perms` 字符串

DeskClaw 第一期仅 seed `type=F` 按钮权限，不写入 `M/C` 菜单树
（前端仍走静态路由，菜单树等第二期再切动态）。

`perms` 命名规范：`module:resource:action`，例如 `gene:publish`、
`workspace:member:invite`、`platform:cluster:manage`。

`app_code` 关联到 `apps.app_code`，NULL 表示全应用共享。
"""

from sqlalchemy import (
    CheckConstraint,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class MenuType:
    """菜单类型枚举值（与表字段 menu_type 对齐）。"""

    # 目录：树形容器，无路由、无 perms
    DIRECTORY = "M"
    # 菜单：对应前端路由（path/component），可能也带 perms
    PAGE = "C"
    # 按钮：仅承载 perms 字符串，无路由
    BUTTON = "F"


class Menu(BaseModel):
    """RBAC 菜单 / 按钮 / 权限点表。"""

    __tablename__ = "menus"
    __table_args__ = (
        # perms 在「未软删 且 perms 非空」时唯一；M 目录节点 perms 可为 NULL 不参与唯一约束
        Index(
            "uq_menus_perms_active",
            "perms",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND perms IS NOT NULL"),
        ),
        Index("ix_menus_parent_id", "parent_id"),
        Index("ix_menus_app_code", "app_code"),
        Index("ix_menus_type", "menu_type"),
        # menu_type 必须是 M/C/F 三选一
        CheckConstraint(
            "menu_type in ('M','C','F')",
            name="ck_menus_menu_type",
        ),
        # 按钮类型必须提供 perms（其余类型可空）
        CheckConstraint(
            "menu_type<>'F' OR perms IS NOT NULL",
            name="ck_menus_button_perms",
        ),
    )

    # 菜单显示名 / i18n key
    menu_name: Mapped[str] = mapped_column(String(64), nullable=False)
    # 父节点 ID，根节点为 NULL；不加外键约束（容许跨表清理时灵活）
    parent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # 排序号
    order_num: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 前端路由路径（仅 type=C 时使用）
    path: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # 前端 Vue 组件路径（仅 type=C 时使用）
    component: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 菜单类型：M=目录 / C=菜单 / F=按钮
    menu_type: Mapped[str] = mapped_column(String(1), nullable=False)
    # 是否在侧边栏可见：'0'=显示 / '1'=隐藏
    visible: Mapped[str] = mapped_column(String(1), nullable=False, default="0")
    # 状态：'0'=正常 / '1'=停用
    status: Mapped[str] = mapped_column(String(1), nullable=False, default="0")
    # 权限标识，命名规范 module:resource:action
    perms: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 图标名（如 Iconify 名）
    icon: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 所属应用编码，NULL 表示全应用共享
    app_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
