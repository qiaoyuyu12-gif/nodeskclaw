"""RBAC 角色定义表 `roles`。

对齐 MOM Cloud `sys_role` 的命名规范（role_key / role_name / role_sort），
并扩展 `scope` 字段以承载 DeskClaw 四级作用域（platform/org/workspace/instance）。

`role_key` 为系统全局唯一标识，例如 `platform_super` / `org_admin` / `workspace_owner`，
业务代码通过该字符串识别角色。`is_system=True` 的内置角色由 seed 写入，不允许通过 API 删除。
"""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class RoleScope:
    """角色作用域枚举值（与 `subject_roles.scope_type` 对齐，不强制 SQL Enum）。"""

    # 平台级：典型代表 platform_super，对任意目标 scope 检查都直接放行
    PLATFORM = "platform"
    # 组织级：典型代表 org_admin / org_member，跨级时可覆盖该 org 下 workspace/instance
    ORG = "org"
    # 工作区级：仅作用于具体 workspace
    WORKSPACE = "workspace"
    # 实例级：仅作用于具体 instance（DeskClaw 的 AI Agent 容器）
    INSTANCE = "instance"


class Role(BaseModel):
    """RBAC 角色。

    seed 写入的 9 个内置角色：platform_super / platform_admin / org_admin /
    org_operator / org_member / workspace_owner / workspace_editor / workspace_viewer /
    agent_workspace_executor。
    """

    __tablename__ = "roles"
    __table_args__ = (
        # role_key 全局唯一（按未软删过滤），允许同名角色软删后重建
        Index(
            "uq_roles_role_key_active",
            "role_key",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_roles_scope", "scope"),
        Index("ix_roles_org_id", "org_id"),
        # CHECK 强制 scope 合法，PostgreSQL 生效；SQLite 测试库需注意忽略
        CheckConstraint(
            "scope in ('platform','org','workspace','instance')",
            name="ck_roles_scope",
        ),
    )

    # 角色权限标识，业务代码判定的唯一依据
    role_key: Mapped[str] = mapped_column(String(64), nullable=False)
    # 角色显示名（可用于前端展示）
    role_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # 排序号，越小越靠前
    role_sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 角色作用域类型：platform/org/workspace/instance
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    # 状态：active / disabled
    status: Mapped[str] = mapped_column(String(8), nullable=False, default="active")
    # 系统内置角色标志，True 时不允许通过 API 删除
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 自定义角色归属 org；NULL 表示系统全局角色
    org_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=True,
    )
    # 角色说明（可选）
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
