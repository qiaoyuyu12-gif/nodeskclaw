"""RBAC 主体（用户/Agent）↔ 角色 授权表 `subject_roles`。

对 MOM `sys_user_role` 的 DeskClaw 扩展：
1. `subject_type` 区分 `user`（人类用户）和 `agent`（AI 实例）两类主体；
2. 引入 `scope_type` + `scope_id` 二元组以表达四级作用域，例如
   「用户 U 在 org=O 下拥有 org_admin 角色」「Agent A 在 workspace=W 下拥有 executor 角色」；
3. 支持 `expires_at` 临时授权过期。

一条记录 = 一次授权。同一主体可在不同 scope 下被授予相同角色（例如同时是
org=O1 的 admin 和 org=O2 的 admin），由唯一索引五元组保证不重复。

platform scope 的 scope_id 固定为 NULL，表示「全局生效」。
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class SubjectType:
    """主体类型枚举值（与 `AuthActor.actor_type` 对齐）。"""

    # 人类用户，subject_id = users.id
    USER = "user"
    # AI Agent / 实例，subject_id = instances.id（第二期会切换为独立 agent_identities）
    AGENT = "agent"


class SubjectRole(BaseModel):
    """主体 ↔ 角色授权记录。"""

    __tablename__ = "subject_roles"
    __table_args__ = (
        # 五元组未软删唯一：同主体在同 scope 下不会被授予同一角色两次
        Index(
            "uq_subject_roles_active",
            "subject_type",
            "subject_id",
            "role_id",
            "scope_type",
            "scope_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # 按主体查询所有授权（resolver 主要路径）
        Index("ix_subject_roles_subject", "subject_type", "subject_id"),
        # 按 scope 反查授权
        Index("ix_subject_roles_scope", "scope_type", "scope_id"),
        # 仅对临时授权建索引，便于定时清理过期记录
        Index(
            "ix_subject_roles_expires",
            "expires_at",
            postgresql_where=text("expires_at IS NOT NULL"),
        ),
        # CHECK 强制主体类型与作用域类型合法
        CheckConstraint(
            "subject_type in ('user','agent')",
            name="ck_subject_roles_subject_type",
        ),
        CheckConstraint(
            "scope_type in ('platform','org','workspace','instance')",
            name="ck_subject_roles_scope_type",
        ),
    )

    # 主体类型：user / agent（与 AuthActor.actor_type 对齐）
    subject_type: Mapped[str] = mapped_column(String(8), nullable=False)
    # 主体 ID：user.id 或 instance.id（不加外键以便兼容跨表）
    subject_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # 关联角色
    role_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("roles.id"), nullable=False,
    )
    # 作用域类型：platform / org / workspace / instance
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # 作用域 ID：platform 时为 NULL；其余指向 org_id / workspace_id / instance_id
    scope_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # 授权人 user.id（seed 写入时为 NULL）
    granted_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True,
    )
    # 授权原因，例如 seed:org_membership / manual_grant
    granted_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # 临时授权过期时间，NULL 表示永久
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
