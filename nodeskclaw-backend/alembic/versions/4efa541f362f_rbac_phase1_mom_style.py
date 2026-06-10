"""rbac_phase1_mom_style

新建 7 张 RBAC 表（参考 MOM Cloud 设计 + DeskClaw 四级 scope 扩展）：
- roles：角色定义
- menus：菜单/按钮/权限点（M/C/F + perms）
- apps：应用入口
- subject_roles：主体（user/agent）↔ 角色，含 scope_type/scope_id
- role_menus：角色 ↔ 菜单关联
- role_apps：角色 ↔ 应用关联
- permission_audit_logs：权限决策审计

Revision ID: 4efa541f362f
Revises: fed0e4f7dfa9
Create Date: 2026-06-06 16:07:44.860322

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "4efa541f362f"
down_revision: Union[str, Sequence[str], None] = "fed0e4f7dfa9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: 建立 RBAC 第一期 7 张表。"""

    # 1. roles
    op.create_table(
        "roles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("role_key", sa.String(length=64), nullable=False),
        sa.Column("role_name", sa.String(length=128), nullable=False),
        sa.Column("role_sort", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=8), nullable=False, server_default="active"),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("org_id", sa.String(length=36), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "scope in ('platform','org','workspace','instance')",
            name="ck_roles_scope",
        ),
    )
    op.create_index(
        "uq_roles_role_key_active", "roles", ["role_key"],
        unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_roles_scope", "roles", ["scope"], unique=False)
    op.create_index("ix_roles_org_id", "roles", ["org_id"], unique=False)
    op.create_index("ix_roles_deleted_at", "roles", ["deleted_at"], unique=False)

    # 2. menus（菜单 + 按钮 + 权限点三合一）
    op.create_table(
        "menus",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("menu_name", sa.String(length=64), nullable=False),
        sa.Column("parent_id", sa.String(length=36), nullable=True),
        sa.Column("order_num", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("path", sa.String(length=200), nullable=True),
        sa.Column("component", sa.String(length=255), nullable=True),
        sa.Column("menu_type", sa.String(length=1), nullable=False),
        sa.Column("visible", sa.String(length=1), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=1), nullable=False, server_default="0"),
        sa.Column("perms", sa.String(length=100), nullable=True),
        sa.Column("icon", sa.String(length=100), nullable=True),
        sa.Column("app_code", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("menu_type in ('M','C','F')", name="ck_menus_menu_type"),
        sa.CheckConstraint("menu_type<>'F' OR perms IS NOT NULL", name="ck_menus_button_perms"),
    )
    op.create_index(
        "uq_menus_perms_active", "menus", ["perms"],
        unique=True, postgresql_where=sa.text("deleted_at IS NULL AND perms IS NOT NULL"),
    )
    op.create_index("ix_menus_parent_id", "menus", ["parent_id"], unique=False)
    op.create_index("ix_menus_app_code", "menus", ["app_code"], unique=False)
    op.create_index("ix_menus_type", "menus", ["menu_type"], unique=False)
    op.create_index("ix_menus_deleted_at", "menus", ["deleted_at"], unique=False)

    # 3. apps
    op.create_table(
        "apps",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("app_code", sa.String(length=50), nullable=False),
        sa.Column("app_name", sa.String(length=100), nullable=False),
        sa.Column("app_icon", sa.String(length=200), nullable=True),
        sa.Column("app_url", sa.String(length=500), nullable=False),
        sa.Column("app_desc", sa.String(length=500), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=1), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_apps_app_code_active", "apps", ["app_code"],
        unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_apps_status", "apps", ["status"], unique=False)
    op.create_index("ix_apps_deleted_at", "apps", ["deleted_at"], unique=False)

    # 4. subject_roles（MOM sys_user_role 的 DeskClaw 扩展版）
    op.create_table(
        "subject_roles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("subject_type", sa.String(length=8), nullable=False),
        sa.Column("subject_id", sa.String(length=36), nullable=False),
        sa.Column("role_id", sa.String(length=36), nullable=False),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("scope_id", sa.String(length=36), nullable=True),
        sa.Column("granted_by", sa.String(length=36), nullable=True),
        sa.Column("granted_reason", sa.String(length=128), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"]),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "subject_type in ('user','agent')",
            name="ck_subject_roles_subject_type",
        ),
        sa.CheckConstraint(
            "scope_type in ('platform','org','workspace','instance')",
            name="ck_subject_roles_scope_type",
        ),
    )
    op.create_index(
        "uq_subject_roles_active", "subject_roles",
        ["subject_type", "subject_id", "role_id", "scope_type", "scope_id"],
        unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_subject_roles_subject", "subject_roles",
        ["subject_type", "subject_id"], unique=False,
    )
    op.create_index(
        "ix_subject_roles_scope", "subject_roles",
        ["scope_type", "scope_id"], unique=False,
    )
    op.create_index(
        "ix_subject_roles_expires", "subject_roles", ["expires_at"],
        unique=False, postgresql_where=sa.text("expires_at IS NOT NULL"),
    )
    op.create_index("ix_subject_roles_deleted_at", "subject_roles", ["deleted_at"], unique=False)

    # 5. role_menus
    op.create_table(
        "role_menus",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("role_id", sa.String(length=36), nullable=False),
        sa.Column("menu_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"]),
        sa.ForeignKeyConstraint(["menu_id"], ["menus.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_role_menus", "role_menus", ["role_id", "menu_id"],
        unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_role_menus_role_id", "role_menus", ["role_id"], unique=False)
    op.create_index("ix_role_menus_menu_id", "role_menus", ["menu_id"], unique=False)
    op.create_index("ix_role_menus_deleted_at", "role_menus", ["deleted_at"], unique=False)

    # 6. role_apps
    op.create_table(
        "role_apps",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("role_id", sa.String(length=36), nullable=False),
        sa.Column("app_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"]),
        sa.ForeignKeyConstraint(["app_id"], ["apps.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_role_apps", "role_apps", ["role_id", "app_id"],
        unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_role_apps_deleted_at", "role_apps", ["deleted_at"], unique=False)

    # 7. permission_audit_logs（默认关闭，仅在 RBAC_AUDIT=true 时写入）
    op.create_table(
        "permission_audit_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("subject_type", sa.String(length=8), nullable=False),
        sa.Column("subject_id", sa.String(length=36), nullable=False),
        sa.Column("perms_code", sa.String(length=100), nullable=False),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("scope_id", sa.String(length=36), nullable=True),
        sa.Column("decision", sa.String(length=8), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("request_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pal_subject", "permission_audit_logs",
        ["subject_type", "subject_id", "created_at"], unique=False,
    )
    op.create_index("ix_pal_decision", "permission_audit_logs", ["decision"], unique=False)
    op.create_index("ix_pal_created_at", "permission_audit_logs", ["created_at"], unique=False)


def downgrade() -> None:
    """Downgrade schema: 按反序删除 7 张 RBAC 表。"""
    op.drop_index("ix_pal_created_at", table_name="permission_audit_logs")
    op.drop_index("ix_pal_decision", table_name="permission_audit_logs")
    op.drop_index("ix_pal_subject", table_name="permission_audit_logs")
    op.drop_table("permission_audit_logs")

    op.drop_index(
        "ix_role_apps_deleted_at", table_name="role_apps",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index(
        "uq_role_apps", table_name="role_apps",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_table("role_apps")

    op.drop_index(
        "ix_role_menus_deleted_at", table_name="role_menus",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index("ix_role_menus_menu_id", table_name="role_menus")
    op.drop_index("ix_role_menus_role_id", table_name="role_menus")
    op.drop_index(
        "uq_role_menus", table_name="role_menus",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_table("role_menus")

    op.drop_index("ix_subject_roles_deleted_at", table_name="subject_roles")
    op.drop_index(
        "ix_subject_roles_expires", table_name="subject_roles",
        postgresql_where=sa.text("expires_at IS NOT NULL"),
    )
    op.drop_index("ix_subject_roles_scope", table_name="subject_roles")
    op.drop_index("ix_subject_roles_subject", table_name="subject_roles")
    op.drop_index(
        "uq_subject_roles_active", table_name="subject_roles",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_table("subject_roles")

    op.drop_index("ix_apps_deleted_at", table_name="apps")
    op.drop_index("ix_apps_status", table_name="apps")
    op.drop_index(
        "uq_apps_app_code_active", table_name="apps",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_table("apps")

    op.drop_index("ix_menus_deleted_at", table_name="menus")
    op.drop_index("ix_menus_type", table_name="menus")
    op.drop_index("ix_menus_app_code", table_name="menus")
    op.drop_index("ix_menus_parent_id", table_name="menus")
    op.drop_index(
        "uq_menus_perms_active", table_name="menus",
        postgresql_where=sa.text("deleted_at IS NULL AND perms IS NOT NULL"),
    )
    op.drop_table("menus")

    op.drop_index("ix_roles_deleted_at", table_name="roles")
    op.drop_index("ix_roles_org_id", table_name="roles")
    op.drop_index("ix_roles_scope", table_name="roles")
    op.drop_index(
        "uq_roles_role_key_active", table_name="roles",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_table("roles")
