# RFC 0001 v2：RBAC 基础设施 + 双写（参考 MOM Cloud 8 表方案）

| 项 | 内容 |
|---|---|
| 状态 | 待评审（v2 取代 v1） |
| 关联计划 | `~/.claude/plans/skill-ai-glimmering-crystal.md` |
| 参考方案 | `docs/权限控制配置.md`（MOM Cloud v1.0） |
| 影响版本 | CE / EE |
| Alembic 起点 | `ec27348942b6`（当前 head） |
| 风险评级 | 中（表数翻倍，但不切读取路径） |

---

## 0. 与 v1 的差异速览

| 维度 | v1（已废弃） | v2（本 RFC） |
|---|---|---|
| 权限点存储 | 独立 `permissions` 表 | 合并到 `menus.perms` 字段 |
| 菜单系统 | 无 | 引入 `menus`（M/C/F） |
| 应用入口控制 | 无 | 引入 `apps` |
| 角色标识 | `code` | `role_key`（MOM 命名） |
| API 命名 | `has_permission` / `require_permission` | `has_perms` / `require_perms` |
| 超管保护 | 隐式 | 显式 `assert_not_super_admin` / `assert_not_admin_role` |
| `/auth/me` 响应 | 不变 | 增量 `rbac` 子对象 |
| 总表数 | 5 | 8 + 1（含审计） |

v2 在 v1 基础上**完整对齐 MOM Cloud 的 RBAC 实现**，同时保留 DeskClaw 的四级 scope 扩展（platform/org/workspace/instance）以适配跨级权限继承。

---

## 1. 目标与非目标

### 1.1 目标
- 建立**符合 MOM Cloud 风格的 RBAC 数据模型**：`roles` / `menus` / `apps` 三主表 + `subject_roles` / `role_menus` / `role_apps` 三关联表 + `permission_audit_logs` 审计
- 沿用 MOM 命名规范：`role_key`、`perms`（`module:resource:action`）、`app_code`（`PORTAL`/`ADMIN`/...）
- 提供统一权限查询入口 `has_perms(subject, perms_code, scope)`，支持 user/agent 主体
- 提供 `require_perms(...)` FastAPI 依赖（与现有 `require_org_admin` 并存）
- 提供 `assert_not_super_admin()` / `assert_not_admin_role()` 超管保护工具（仅工具，第一期不接业务）
- `/auth/me` 响应**增量**返回 `rbac.role_keys` / `rbac.perms` / `rbac.app_codes`，为第二期前端切换打地基
- 现有所有权限字段（`User.is_super_admin` / `OrgMembership.role` / `AdminMembership.role` / `WorkspaceMember.role`）**继续作为权威读取源**，同步**双写**到 `subject_roles`

### 1.2 非目标（后续期次）
- 第二期：前端动态菜单切换（`routes.ts` 改造、`filterAuthRoutesByRoles/AppCode`、`useAuth().hasAuth()`）
- 第二期：替换 `require_org_admin` / `require_org_member_role` / `require_org_role` 全部依赖
- 第二期：把 `assert_not_super_admin` 接入业务（用户管理 / 角色管理）
- 第二期：Agent 独立身份表
- 永不引入：部门 `sys_dept` + `data_scope`（DeskClaw 无部门概念）
- 永不引入：菜单树 `type=M/C` 数据 seed（前端尚未切动态菜单，仅在第二期前置后再 seed）
- 第三期才考虑：Redis 共享 RBAC 缓存

---

## 2. 现状对齐（基于代码勘察）

| 现状 | 文件 | v2 处理方式 |
|---|---|---|
| `User.is_super_admin: bool` | `app/models/user.py` | 保留；seed 双写 `subject_roles(role=platform_super)` |
| `OrgMembership.role` 枚举 | `app/models/org_membership.py:11` | 保留；seed + 运行时双写 `subject_roles(role=org_{role})` |
| `AdminMembership.role` | `app/models/admin_membership.py:18` | 保留；seed + 运行时双写 `subject_roles(role=platform_admin, scope=org)` |
| `WorkspaceMember.role` + `permissions: JSON` | `app/models/workspace_member.py` | role 字段双写到 `subject_roles(role=workspace_{role})`；自定义 `permissions` JSON v2 期内不动 |
| `AuthActor(actor_type, actor_id, actor_name)` ContextVar | `app/core/security.py:24-32` | **直接作为 RBAC subject 来源** |
| `operation_audit_logs` 表已存在 | 迁移 `b3f7c1a29e04` | 不复用为权限决策日志（语义不同），独立建 `permission_audit_logs` |
| `AppException` / `ForbiddenError` 体系 | `app/core/exceptions.py` | 新增 `PermissionDeniedError(ForbiddenError)` |
| FeatureGate CE/EE 分支 | `app/core/feature_gate.py` | 不变；RBAC 在两种模式均启用 |

---

## 3. 数据模型

### 3.1 ER 概览

```
┌───────────┐   ┌─────────────────┐
│ apps      │ M:N│ role_apps       │
│  app_code │◀──┤  role_id        │
│  app_url  │   │  app_id         │
└───────────┘   └─────────┬───────┘
                          │
                          │ M:N
┌──────────────────┐  ┌───▼──────┐   M:N   ┌───────────────┐
│ subject_roles    │  │ roles    │◀────────┤ role_menus    │
│  subject_type    │  │  role_key│         │  role_id      │
│  subject_id      │M:N│ scope    │         │  menu_id      │
│  role_id         ├──┤  status  │         └───────┬───────┘
│  scope_type      │  │  org_id  │                 │
│  scope_id        │  └──────────┘                 │ M:N
│  granted_by      │                               │
│  expires_at      │                          ┌────▼──────────┐
└──────────────────┘                          │ menus         │
                                              │  menu_type    │
       ┌───────────────────────┐              │  (M / C / F)  │
       │ permission_audit_logs │              │  perms        │
       │  subject_*            │  (default off)  │  app_code  │
       │  perms_code           │              │  parent_id    │
       │  decision             │              └───────────────┘
       └───────────────────────┘
```

### 3.2 表 DDL

> 全部继承 `BaseModel`：UUID(String(36)) PK + 时间戳 + 软删。
> 唯一索引全部 partial（`postgresql_where=text("deleted_at IS NULL")`）。
> 部分字段附加 CHECK 约束（PostgreSQL 强制）。

#### 3.2.1 `roles`

| 列 | 类型 | 约束 / 默认 | 说明 |
|---|---|---|---|
| id | VARCHAR(36) | PK | |
| role_key | VARCHAR(64) | UNIQUE(partial) | 如 `platform_super` / `org_admin` / `workspace_owner` |
| role_name | VARCHAR(128) | NOT NULL | 显示名 |
| role_sort | INT | DEFAULT 0 | 排序 |
| scope | VARCHAR(16) | NOT NULL，CHECK in (`platform`,`org`,`workspace`,`instance`) | 角色作用域类型 |
| status | VARCHAR(8) | DEFAULT 'active' | `active` / `disabled` |
| is_system | BOOLEAN | DEFAULT TRUE | 系统内置不可删 |
| org_id | VARCHAR(36) | FK→organizations.id NULL | 自定义角色归属 |
| description | TEXT | NULL | |
| created_at / updated_at / deleted_at | | | |

索引：`uq_roles_role_key_active`、`ix_roles_scope`、`ix_roles_org_id`

#### 3.2.2 `menus`（菜单 + 按钮 + 权限点三合一）

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | VARCHAR(36) | PK | |
| menu_name | VARCHAR(64) | NOT NULL | i18n key 或显示名 |
| parent_id | VARCHAR(36) | NULL | 树形父节点 |
| order_num | INT | DEFAULT 0 | |
| path | VARCHAR(200) | NULL | 前端路由路径（type=C） |
| component | VARCHAR(255) | NULL | Vue 组件路径（type=C） |
| menu_type | CHAR(1) | NOT NULL，CHECK in (`M`,`C`,`F`) | `M`=目录 / `C`=菜单 / `F`=按钮 |
| visible | CHAR(1) | DEFAULT '0' | `0`=显示 / `1`=隐藏 |
| status | CHAR(1) | DEFAULT '0' | `0`=正常 / `1`=停用 |
| perms | VARCHAR(100) | NULL，CHECK (`menu_type<>'F' OR perms IS NOT NULL`) | 权限标识，`module:resource:action` |
| icon | VARCHAR(100) | NULL | Iconify 名 |
| app_code | VARCHAR(50) | NULL | 所属应用，NULL=全应用共享 |
| created_at / updated_at / deleted_at | | | |

索引：
- `uq_menus_perms_active`（perms，partial: `deleted_at IS NULL AND perms IS NOT NULL`）
- `ix_menus_parent_id`、`ix_menus_app_code`、`ix_menus_type`

#### 3.2.3 `apps`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | VARCHAR(36) | PK | |
| app_code | VARCHAR(50) | UNIQUE(partial) | `PORTAL` / `ADMIN` / `OPEN_API` / `MCP_GATEWAY` |
| app_name | VARCHAR(100) | NOT NULL | 显示名 |
| app_icon | VARCHAR(200) | NULL | |
| app_url | VARCHAR(500) | NOT NULL | 入口 URL |
| app_desc | VARCHAR(500) | NULL | |
| sort_order | INT | DEFAULT 0 | |
| status | CHAR(1) | DEFAULT '0' | |
| created_at / updated_at / deleted_at | | | |

索引：`uq_apps_app_code_active`、`ix_apps_status`

#### 3.2.4 `subject_roles`（MOM `sys_user_role` 的 DeskClaw 扩展版）

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | VARCHAR(36) | PK | |
| subject_type | VARCHAR(8) | NOT NULL，CHECK in (`user`,`agent`) | |
| subject_id | VARCHAR(36) | NOT NULL，indexed | user.id 或 instance.id |
| role_id | VARCHAR(36) | FK→roles.id NOT NULL | |
| scope_type | VARCHAR(16) | NOT NULL，CHECK in (`platform`,`org`,`workspace`,`instance`) | |
| scope_id | VARCHAR(36) | NULL（platform 时） | |
| granted_by | VARCHAR(36) | FK→users.id NULL | |
| granted_reason | VARCHAR(128) | NULL | 如 `seed:org_membership` |
| expires_at | DateTime | NULL | |
| created_at / updated_at / deleted_at | | | |

索引：
- `uq_subject_roles_active`（subject_type, subject_id, role_id, scope_type, scope_id, partial）
- `ix_subject_roles_subject`（subject_type, subject_id）
- `ix_subject_roles_scope`（scope_type, scope_id）
- `ix_subject_roles_expires`（expires_at，partial: `expires_at IS NOT NULL`）

#### 3.2.5 `role_menus`

| 列 | 类型 | 约束 |
|---|---|---|
| id | VARCHAR(36) | PK |
| role_id | VARCHAR(36) | FK→roles.id NOT NULL |
| menu_id | VARCHAR(36) | FK→menus.id NOT NULL |
| created_at / updated_at / deleted_at | | |

索引：`uq_role_menus`（role_id, menu_id, partial）、`ix_role_menus_role_id`、`ix_role_menus_menu_id`

#### 3.2.6 `role_apps`

| 列 | 类型 | 约束 |
|---|---|---|
| id | VARCHAR(36) | PK |
| role_id | VARCHAR(36) | FK→roles.id NOT NULL |
| app_id | VARCHAR(36) | FK→apps.id NOT NULL |
| created_at / updated_at / deleted_at | | |

索引：`uq_role_apps`（role_id, app_id, partial）

#### 3.2.7 `permission_audit_logs`（默认关闭）

| 列 | 类型 | 说明 |
|---|---|---|
| id | VARCHAR(36) | PK |
| subject_type | VARCHAR(8) | user / agent |
| subject_id | VARCHAR(36) | |
| perms_code | VARCHAR(100) | 被检查的权限标识 |
| scope_type | VARCHAR(16) | |
| scope_id | VARCHAR(36) | NULL |
| decision | VARCHAR(8) | `allow` / `deny` |
| reason | VARCHAR(255) | 命中的 role_key 或拒绝原因 |
| request_id | VARCHAR(36) | 关联 X-Request-Id |
| created_at | DateTime | |

索引：`ix_pal_subject`（subject_type, subject_id, created_at DESC）、`ix_pal_decision`、`ix_pal_created_at`

---

## 4. Alembic 迁移骨架

文件：`nodeskclaw-backend/alembic/versions/<auto>_rbac_phase1_mom_style.py`

```python
"""rbac phase1 mom style: roles / menus / apps / subject_roles / role_menus / role_apps / audit"""
from typing import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "<auto>"
down_revision: str | Sequence[str] | None = "ec27348942b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. roles
    op.create_table(
        "roles",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("role_key", sa.String(64), nullable=False),
        sa.Column("role_name", sa.String(128), nullable=False),
        sa.Column("role_sort", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("status", sa.String(8), nullable=False, server_default="active"),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "scope in ('platform','org','workspace','instance')",
            name="ck_roles_scope",
        ),
    )
    op.create_index("uq_roles_role_key_active", "roles", ["role_key"],
                    unique=True, postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_roles_scope", "roles", ["scope"])
    op.create_index("ix_roles_org_id", "roles", ["org_id"])

    # 2. menus
    op.create_table(
        "menus",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("menu_name", sa.String(64), nullable=False),
        sa.Column("parent_id", sa.String(36), nullable=True),
        sa.Column("order_num", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("path", sa.String(200), nullable=True),
        sa.Column("component", sa.String(255), nullable=True),
        sa.Column("menu_type", sa.String(1), nullable=False),
        sa.Column("visible", sa.String(1), nullable=False, server_default="0"),
        sa.Column("status", sa.String(1), nullable=False, server_default="0"),
        sa.Column("perms", sa.String(100), nullable=True),
        sa.Column("icon", sa.String(100), nullable=True),
        sa.Column("app_code", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("menu_type in ('M','C','F')", name="ck_menus_menu_type"),
        sa.CheckConstraint("menu_type<>'F' OR perms IS NOT NULL", name="ck_menus_button_perms"),
    )
    op.create_index("uq_menus_perms_active", "menus", ["perms"], unique=True,
                    postgresql_where=sa.text("deleted_at IS NULL AND perms IS NOT NULL"))
    op.create_index("ix_menus_parent_id", "menus", ["parent_id"])
    op.create_index("ix_menus_app_code", "menus", ["app_code"])
    op.create_index("ix_menus_type", "menus", ["menu_type"])

    # 3. apps
    op.create_table(
        "apps",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("app_code", sa.String(50), nullable=False),
        sa.Column("app_name", sa.String(100), nullable=False),
        sa.Column("app_icon", sa.String(200), nullable=True),
        sa.Column("app_url", sa.String(500), nullable=False),
        sa.Column("app_desc", sa.String(500), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(1), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_apps_app_code_active", "apps", ["app_code"], unique=True,
                    postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_apps_status", "apps", ["status"])

    # 4. subject_roles
    op.create_table(
        "subject_roles",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("subject_type", sa.String(8), nullable=False),
        sa.Column("subject_id", sa.String(36), nullable=False),
        sa.Column("role_id", sa.String(36), sa.ForeignKey("roles.id"), nullable=False),
        sa.Column("scope_type", sa.String(16), nullable=False),
        sa.Column("scope_id", sa.String(36), nullable=True),
        sa.Column("granted_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("granted_reason", sa.String(128), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("subject_type in ('user','agent')", name="ck_subject_roles_subject_type"),
        sa.CheckConstraint("scope_type in ('platform','org','workspace','instance')",
                           name="ck_subject_roles_scope_type"),
    )
    op.create_index("uq_subject_roles_active", "subject_roles",
                    ["subject_type", "subject_id", "role_id", "scope_type", "scope_id"],
                    unique=True, postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_subject_roles_subject", "subject_roles", ["subject_type", "subject_id"])
    op.create_index("ix_subject_roles_scope", "subject_roles", ["scope_type", "scope_id"])
    op.create_index("ix_subject_roles_expires", "subject_roles", ["expires_at"],
                    postgresql_where=sa.text("expires_at IS NOT NULL"))

    # 5. role_menus
    op.create_table(
        "role_menus",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("role_id", sa.String(36), sa.ForeignKey("roles.id"), nullable=False),
        sa.Column("menu_id", sa.String(36), sa.ForeignKey("menus.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_role_menus", "role_menus", ["role_id", "menu_id"], unique=True,
                    postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_role_menus_role_id", "role_menus", ["role_id"])
    op.create_index("ix_role_menus_menu_id", "role_menus", ["menu_id"])

    # 6. role_apps
    op.create_table(
        "role_apps",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("role_id", sa.String(36), sa.ForeignKey("roles.id"), nullable=False),
        sa.Column("app_id", sa.String(36), sa.ForeignKey("apps.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_role_apps", "role_apps", ["role_id", "app_id"], unique=True,
                    postgresql_where=sa.text("deleted_at IS NULL"))

    # 7. permission_audit_logs
    op.create_table(
        "permission_audit_logs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("subject_type", sa.String(8), nullable=False),
        sa.Column("subject_id", sa.String(36), nullable=False),
        sa.Column("perms_code", sa.String(100), nullable=False),
        sa.Column("scope_type", sa.String(16), nullable=False),
        sa.Column("scope_id", sa.String(36), nullable=True),
        sa.Column("decision", sa.String(8), nullable=False),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("request_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pal_subject", "permission_audit_logs",
                    ["subject_type", "subject_id", "created_at"])
    op.create_index("ix_pal_decision", "permission_audit_logs", ["decision"])
    op.create_index("ix_pal_created_at", "permission_audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("permission_audit_logs")
    op.drop_table("role_apps")
    op.drop_table("role_menus")
    op.drop_table("subject_roles")
    op.drop_table("apps")
    op.drop_table("menus")
    op.drop_table("roles")
```

> 与现有迁移一致，生产/CI/dev 统一 PostgreSQL，CHECK 约束有效。

---

## 5. 内置数据（seed）

### 5.1 内置应用

| app_code | app_name | app_url | sort |
|---|---|---|---|
| `PORTAL` | DeskClaw 用户门户 | `/portal/home` | 10 |
| `ADMIN` | DeskClaw 管理后台 | `/admin/home` | 20 |
| `OPEN_API` | OpenAPI 调用 | `/api/v1` | 30 |
| `MCP_GATEWAY` | MCP 协议网关 | `/mcp` | 40 |

### 5.2 内置角色

| role_key | scope | role_sort | 对应历史字段 |
|---|---|---|---|
| `platform_super` | platform | 0 | `User.is_super_admin=True` |
| `platform_admin` | org | 10 | `AdminMembership.role='admin'` |
| `org_admin` | org | 20 | `OrgMembership.role='admin'` |
| `org_operator` | org | 30 | `OrgMembership.role='operator'` |
| `org_member` | org | 40 | `OrgMembership.role='member'` |
| `workspace_owner` | workspace | 50 | `WorkspaceMember.role='owner'` |
| `workspace_editor` | workspace | 60 | `WorkspaceMember.role='editor'` |
| `workspace_viewer` | workspace | 70 | `WorkspaceMember.role='viewer'` |
| `agent_workspace_executor` | workspace | 80 | Agent 默认（第二期生效） |

### 5.3 内置 menus（仅 type=F 按钮权限点）

> 第一期 **不 seed 菜单树（M/C）**，避免前端误以为已切动态菜单。

| perms | menu_name | app_code | 归属角色（role_key） |
|---|---|---|---|
| `org:read` | rbac.menu.org_read | PORTAL | org_member / org_operator / org_admin / platform_super |
| `org:update` | rbac.menu.org_update | ADMIN | org_admin / platform_super |
| `org:member:invite` | rbac.menu.org_invite | PORTAL | org_admin / platform_super |
| `org:member:remove` | rbac.menu.org_remove | PORTAL | org_admin / platform_super |
| `org:llm_key:manage` | rbac.menu.llm_key | ADMIN | org_admin / platform_super |
| `gene:read` | rbac.menu.gene_read | PORTAL | org_member / org_operator / org_admin / platform_super |
| `gene:publish` | rbac.menu.gene_publish | PORTAL | org_admin / platform_super |
| `gene:review` | rbac.menu.gene_review | ADMIN | org_admin / platform_super |
| `workspace:read` | rbac.menu.ws_read | PORTAL | workspace_viewer / workspace_editor / workspace_owner |
| `workspace:update` | rbac.menu.ws_update | PORTAL | workspace_editor / workspace_owner |
| `workspace:delete` | rbac.menu.ws_delete | PORTAL | workspace_owner / org_admin / platform_super |
| `workspace:member:invite` | rbac.menu.ws_invite | PORTAL | workspace_owner / org_admin / platform_super |
| `workspace:chat:send` | rbac.menu.ws_chat | PORTAL | workspace_viewer / workspace_editor / workspace_owner / agent_workspace_executor |
| `instance:read` | rbac.menu.inst_read | ADMIN | org_member / org_operator / org_admin / platform_super |
| `instance:deploy` | rbac.menu.inst_deploy | ADMIN | org_admin / platform_super |
| `platform:cluster:manage` | rbac.menu.cluster | ADMIN | platform_super |

### 5.4 内置角色 × apps

| role_key | apps |
|---|---|
| `platform_super` | PORTAL, ADMIN, OPEN_API, MCP_GATEWAY |
| `platform_admin` | PORTAL, ADMIN |
| `org_admin` | PORTAL, ADMIN |
| `org_operator` | PORTAL |
| `org_member` | PORTAL |
| `workspace_owner` | PORTAL |
| `workspace_editor` | PORTAL |
| `workspace_viewer` | PORTAL |
| `agent_workspace_executor` | OPEN_API, MCP_GATEWAY |

---

## 6. 权限解析规则

`has_perms(subject_type, subject_id, perms_code, scope)` 内部步骤：

1. 加载主体所有未过期、未软删的 `subject_roles` → `[(role_key, scope_type, scope_id)]`
2. 加载这些角色的 `role_menus → menus.perms` 集合
3. 按 scope 匹配规则过滤可用角色：
   - `scope_type == 'platform'` → 任意目标 scope 都覆盖（`platform_super` 走此路径自然全通）
   - `scope_type == 'org'` 且持有 `org_admin` / `platform_admin` → 自动覆盖该 org 下的 `workspace` / `instance` scope（DeskClaw 特色）
   - 其余按 `(scope_type, scope_id)` 严格相等
4. 若 `perms_code` 在任一覆盖角色的 perms 集合中 → allow + 返回命中 role_key
5. 否则 → deny + reason=`no_matching_role` 或 `no_matching_perms`

---

## 7. 代码骨架

### 7.1 模型层 `app/models/rbac/`

```
app/models/rbac/
├── __init__.py
├── role.py
├── menu.py
├── app.py
├── subject_role.py
├── role_menu.py
├── role_app.py
└── permission_audit_log.py
```

`menu.py` 示例：

```python
"""RBAC 菜单 / 按钮 / 权限点（与 MOM sys_menu 对齐）。

menu_type：
  - M: 目录（树形容器）
  - C: 菜单（对应前端路由）
  - F: 按钮（仅承载 perms，无路由）

perms 在 type=F 时必填，命名规范 `module:resource:action`。
app_code 关联到 apps.app_code；NULL 表示全应用共享。
"""

from sqlalchemy import CheckConstraint, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class MenuType:
    DIRECTORY = "M"
    PAGE = "C"
    BUTTON = "F"


class Menu(BaseModel):
    __tablename__ = "menus"
    __table_args__ = (
        Index(
            "uq_menus_perms_active", "perms",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND perms IS NOT NULL"),
        ),
        Index("ix_menus_parent_id", "parent_id"),
        Index("ix_menus_app_code", "app_code"),
        Index("ix_menus_type", "menu_type"),
        CheckConstraint("menu_type in ('M','C','F')", name="ck_menus_menu_type"),
        CheckConstraint(
            "menu_type<>'F' OR perms IS NOT NULL", name="ck_menus_button_perms",
        ),
    )

    menu_name: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    order_num: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    path: Mapped[str | None] = mapped_column(String(200), nullable=True)
    component: Mapped[str | None] = mapped_column(String(255), nullable=True)
    menu_type: Mapped[str] = mapped_column(String(1), nullable=False)
    visible: Mapped[str] = mapped_column(String(1), default="0", nullable=False)
    status: Mapped[str] = mapped_column(String(1), default="0", nullable=False)
    perms: Mapped[str | None] = mapped_column(String(100), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(100), nullable=True)
    app_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
```

`subject_role.py` 与 v1 等价（保留多 scope）。`app.py` / `role_menu.py` / `role_app.py` 同构略。

### 7.2 核心库 `app/core/rbac/`

```
app/core/rbac/
├── __init__.py            # 暴露 has_perms / require_perms / RbacScope / assert_*
├── scope.py               # RbacScope 数据类
├── resolver.py            # has_perms 主逻辑
├── decorators.py          # require_perms FastAPI 依赖
├── cache.py               # 进程内 LRU + TTL
├── audit.py               # 异步落 permission_audit_logs
├── admin_guard.py         # assert_not_super_admin / assert_not_admin_role
└── exceptions.py          # PermissionDeniedError
```

**`scope.py`**：

```python
"""RBAC 作用域上下文。"""

from dataclasses import dataclass
from typing import Literal

ScopeType = Literal["platform", "org", "workspace", "instance"]


@dataclass(frozen=True)
class RbacScope:
    type: ScopeType
    id: str | None = None
    # workspace/instance scope 在 org-admin 跨级判定时需要的关联 org_id；
    # 仅作元数据传给 resolver，None 表示调用方未提供（resolver 退化为严格匹配）
    parent_org_id: str | None = None

    @classmethod
    def platform(cls) -> "RbacScope":
        return cls(type="platform", id=None)

    @classmethod
    def org(cls, org_id: str) -> "RbacScope":
        return cls(type="org", id=org_id)

    @classmethod
    def workspace(cls, workspace_id: str, *, org_id: str | None = None) -> "RbacScope":
        return cls(type="workspace", id=workspace_id, parent_org_id=org_id)

    @classmethod
    def instance(cls, instance_id: str, *, org_id: str | None = None) -> "RbacScope":
        return cls(type="instance", id=instance_id, parent_org_id=org_id)
```

**`resolver.py`** 关键函数：

```python
"""权限解析。"""

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac.cache import get_cached_grants, set_cached_grants
from app.core.rbac.scope import RbacScope
from app.models.rbac.menu import Menu
from app.models.rbac.role import Role
from app.models.rbac.role_menu import RoleMenu
from app.models.rbac.subject_role import SubjectRole


# 跨级 bypass：org 级管理身份对该 org 下任意 workspace/instance 自动放行
_ORG_ADMIN_ROLES: frozenset[str] = frozenset({"org_admin", "platform_admin"})


async def _load_grants(
    db: AsyncSession, subject_type: str, subject_id: str,
) -> list[tuple[str, str, str | None]]:
    """返回 [(role_key, scope_type, scope_id), ...]，命中缓存优先。"""
    cached = get_cached_grants(subject_type, subject_id)
    if cached is not None:
        return cached
    stmt = (
        select(Role.role_key, SubjectRole.scope_type, SubjectRole.scope_id)
        .join(SubjectRole, SubjectRole.role_id == Role.id)
        .where(
            SubjectRole.subject_type == subject_type,
            SubjectRole.subject_id == subject_id,
            SubjectRole.deleted_at.is_(None),
            Role.deleted_at.is_(None),
        )
    )
    rows = (await db.execute(stmt)).all()
    grants = [(r.role_key, r.scope_type, r.scope_id) for r in rows]
    set_cached_grants(subject_type, subject_id, grants)
    return grants


async def _load_role_perms(
    db: AsyncSession, role_keys: Iterable[str],
) -> dict[str, set[str]]:
    keys = list(set(role_keys))
    if not keys:
        return {}
    stmt = (
        select(Role.role_key, Menu.perms)
        .join(RoleMenu, RoleMenu.role_id == Role.id)
        .join(Menu, Menu.id == RoleMenu.menu_id)
        .where(
            Role.role_key.in_(keys),
            Role.deleted_at.is_(None),
            RoleMenu.deleted_at.is_(None),
            Menu.deleted_at.is_(None),
            Menu.perms.is_not(None),
        )
    )
    rows = (await db.execute(stmt)).all()
    result: dict[str, set[str]] = {k: set() for k in keys}
    for rk, p in rows:
        result.setdefault(rk, set()).add(p)
    return result


def _grant_covers_target(grant_scope_type, grant_scope_id, target: RbacScope,
                         role_key: str) -> bool:
    """grant 作用域是否覆盖目标 scope。

    覆盖规则（DeskClaw 四级 scope 特色）：
    1. platform grant 覆盖任意 scope
    2. 同 scope_type + id 严格相等
    3. org grant + org_admin/platform_admin 角色 + target 是该 org 下的
       workspace/instance（需 parent_org_id 提供）→ 跨级覆盖
    """
    if grant_scope_type == "platform":
        return True
    if grant_scope_type == target.type and grant_scope_id == target.id:
        return True
    if (
        grant_scope_type == "org"
        and role_key in _ORG_ADMIN_ROLES
        and target.type in ("workspace", "instance")
        and target.parent_org_id is not None
        and grant_scope_id == target.parent_org_id
    ):
        return True
    return False


async def has_perms(
    db: AsyncSession, *,
    subject_type: str, subject_id: str,
    perms_code: str, scope: RbacScope,
) -> tuple[bool, str | None]:
    """检查主体是否拥有 perms_code，返回 (allowed, matched_role_key)。"""
    grants = await _load_grants(db, subject_type, subject_id)
    if not grants:
        return False, None
    matching = [
        rk for rk, st, sid in grants
        if _grant_covers_target(st, sid, scope, rk)
    ]
    if not matching:
        return False, None
    role_perms = await _load_role_perms(db, matching)
    for rk in matching:
        if perms_code in role_perms.get(rk, set()):
            return True, rk
    return False, None
```

**`decorators.py`**：

```python
"""require_perms FastAPI 依赖。"""

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.rbac.audit import log_decision_async
from app.core.rbac.resolver import has_perms
from app.core.rbac.scope import RbacScope, ScopeType
from app.core.security import get_auth_actor, get_current_user_or_agent


def require_perms(
    perms_code: str,
    *,
    scope_type: ScopeType = "org",
    scope_param: str | None = None,
    parent_org_param: str | None = "org_id",
):
    """生成权限检查依赖。

    用法：
        @router.post(
            "/{org_id}/workspaces/{workspace_id}/delete",
            dependencies=[Depends(require_perms(
                "workspace:delete",
                scope_type="workspace",
                scope_param="workspace_id",
                parent_org_param="org_id",
            ))],
        )

    参数：
        perms_code: 权限标识，`module:resource:action`
        scope_type: 作用域类型
        scope_param: 从 path_params 取 scope_id 的键名；platform 不需要
        parent_org_param: 用于跨级 bypass：当 scope_type 是 workspace/instance 时，
                          指定 path 中 org_id 参数名，用于让 org_admin 自动覆盖
    """

    async def _check(
        request: Request,
        db: AsyncSession = Depends(get_db),
        user=Depends(get_current_user_or_agent),
    ) -> None:
        actor = get_auth_actor()
        actor_type, actor_id = (
            (actor.actor_type, actor.actor_id) if actor else ("user", user.id)
        )

        if scope_type == "platform":
            scope = RbacScope.platform()
        else:
            scope_id = (
                request.path_params.get(scope_param) if scope_param else None
            )
            if scope_id is None and scope_type == "org":
                scope_id = user.current_org_id
            if not scope_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error_code": 40010,
                        "message_key": "errors.rbac.scope_missing",
                        "message": f"权限检查缺少 {scope_type} 作用域",
                    },
                )
            parent_org_id = (
                request.path_params.get(parent_org_param)
                if parent_org_param else None
            )
            scope = RbacScope(type=scope_type, id=scope_id, parent_org_id=parent_org_id)

        allowed, matched = await has_perms(
            db,
            subject_type=actor_type, subject_id=actor_id,
            perms_code=perms_code, scope=scope,
        )

        await log_decision_async(
            subject_type=actor_type, subject_id=actor_id,
            perms_code=perms_code, scope=scope,
            decision="allow" if allowed else "deny",
            reason=matched or "no_matching_role",
            request_id=request.headers.get("X-Request-Id"),
        )

        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error_code": 40330,
                    "message_key": "errors.rbac.permission_denied",
                    "message": f"缺少权限 {perms_code}",
                },
            )

    return _check
```

**`cache.py`** / **`audit.py`** 与 v1 相同，仅改名：`get_cached_roles` → `get_cached_grants`，`permission_code` → `perms_code`。

**`admin_guard.py`**（对齐 MOM §9 保护策略）：

```python
"""超级管理员保护：照搬 MOM checkNotSuperAdmin / checkNotAdminRole 思路。

第一期仅提供工具函数，不强制接入业务；第二期接入 user_service / role 管理 API。
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError
from app.models.rbac.role import Role
from app.models.rbac.subject_role import SubjectRole

SUPER_ROLE_KEY = "platform_super"


async def is_super_admin_user(db: AsyncSession, user_id: str) -> bool:
    stmt = (
        select(SubjectRole.id)
        .join(Role, Role.id == SubjectRole.role_id)
        .where(
            SubjectRole.subject_type == "user",
            SubjectRole.subject_id == user_id,
            SubjectRole.deleted_at.is_(None),
            Role.role_key == SUPER_ROLE_KEY,
            Role.deleted_at.is_(None),
        )
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none() is not None


async def assert_not_super_admin(
    db: AsyncSession, *, current_user_id: str, target_user_id: str,
) -> None:
    """非超管不允许操作超管用户。"""
    if await is_super_admin_user(db, current_user_id):
        return  # 自己就是超管，允许
    if await is_super_admin_user(db, target_user_id):
        raise ForbiddenError(
            message="不允许操作超级管理员用户",
            message_key="errors.rbac.cannot_operate_super_admin",
        )


async def assert_not_admin_role(
    db: AsyncSession, *, current_user_id: str, target_role_id: str,
) -> None:
    """非超管不允许编辑 / 删除超管角色。"""
    if await is_super_admin_user(db, current_user_id):
        return
    role = (await db.execute(
        select(Role).where(Role.id == target_role_id, Role.deleted_at.is_(None))
    )).scalar_one_or_none()
    if role is not None and role.role_key == SUPER_ROLE_KEY:
        raise ForbiddenError(
            message="不允许操作超级管理员角色",
            message_key="errors.rbac.cannot_operate_super_role",
        )
```

### 7.3 异常补充 `app/core/exceptions.py`

```python
class PermissionDeniedError(ForbiddenError):
    """RBAC 权限决策被拒。"""

    def __init__(self, perms_code: str):
        super().__init__(
            message=f"缺少权限 {perms_code}",
            message_key="errors.rbac.permission_denied",
        )
```

---

## 8. Seed 设计 `app/startup/seed_rbac.py`

幂等 seed，入口 `await seed_rbac(session_factory)`。在 `app/startup/seed.py` 的 `run_seed()` 末尾追加：

```python
await seed_rbac(session_factory)
```

内部步骤：

```python
async def seed_rbac(session_factory):
    await _seed_apps(session_factory)
    await _seed_roles(session_factory)
    await _seed_menus_buttons_only(session_factory)
    await _seed_role_menus(session_factory)
    await _seed_role_apps(session_factory)
    await _backfill_subject_roles_from_legacy(session_factory)
```

### 8.1 `_seed_apps`

按 §5.1 写入 4 个内置应用，按 `app_code` upsert。

### 8.2 `_seed_roles`

按 §5.2 写入 9 个内置角色，按 `role_key` upsert。删除已不在内置列表中、`is_system=true` 的旧角色（防遗留）。

### 8.3 `_seed_menus_buttons_only`

按 §5.3 仅 seed 16 个 `type=F` 按钮记录，按 `perms` upsert。
**菜单树 type=M/C 第一期不 seed**，避免前端误以为已动态化。

### 8.4 `_seed_role_menus`

按 §5.3 「归属角色」列把 role × menu 全量绑定。先 reset 系统角色的所有 role_menus 再插入（系统数据一致性）。

### 8.5 `_seed_role_apps`

按 §5.4 写入角色 × 应用绑定，同上 reset + insert。

### 8.6 `_backfill_subject_roles_from_legacy`

把现有字段一次性映射到 `subject_roles`：

```python
async def _backfill_subject_roles_from_legacy(session_factory):
    async with session_factory() as db:
        # is_super_admin → platform_super
        for u in (await db.execute(
            select(User).where(User.is_super_admin.is_(True), User.deleted_at.is_(None))
        )).scalars():
            await rbac_sync.grant_role(
                db, subject_type="user", subject_id=u.id,
                role_key="platform_super",
                scope_type="platform", scope_id=None,
                granted_reason="seed:is_super_admin",
            )

        # OrgMembership.role → org_{role}
        for om in (await db.execute(
            select(OrgMembership).where(OrgMembership.deleted_at.is_(None))
        )).scalars():
            await rbac_sync.grant_role(
                db, subject_type="user", subject_id=om.user_id,
                role_key=f"org_{om.role}",
                scope_type="org", scope_id=om.org_id,
                granted_reason="seed:org_membership",
            )

        # AdminMembership → platform_admin
        for am in (await db.execute(
            select(AdminMembership).where(AdminMembership.deleted_at.is_(None))
        )).scalars():
            await rbac_sync.grant_role(
                db, subject_type="user", subject_id=am.user_id,
                role_key="platform_admin",
                scope_type="org", scope_id=am.org_id,
                granted_reason="seed:admin_membership",
            )

        # WorkspaceMember.role → workspace_{role}
        for wm in (await db.execute(
            select(WorkspaceMember).where(WorkspaceMember.deleted_at.is_(None))
        )).scalars():
            await rbac_sync.grant_role(
                db, subject_type="user", subject_id=wm.user_id,
                role_key=f"workspace_{wm.role}",
                scope_type="workspace", scope_id=wm.workspace_id,
                granted_reason="seed:workspace_member",
            )

        await db.commit()
```

幂等保证：`grant_role` 命中唯一索引时跳过。10k 行场景下估算 < 3s。
紧急逃生：`SKIP_RBAC_BACKFILL=true` 跳过 backfill（仅排障用）。

---

## 9. 双写适配器 `app/services/rbac_sync.py`

```python
"""业务写入 legacy 字段时同步维护 subject_roles。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac.cache import invalidate_subject
from app.models.rbac.role import Role
from app.models.rbac.subject_role import SubjectRole


async def grant_role(
    db: AsyncSession, *,
    subject_type: str, subject_id: str,
    role_key: str, scope_type: str, scope_id: str | None,
    granted_by: str | None = None, granted_reason: str | None = None,
) -> None:
    """幂等授予角色。"""
    role = (await db.execute(
        select(Role).where(Role.role_key == role_key, Role.deleted_at.is_(None))
    )).scalar_one_or_none()
    if role is None:
        raise RuntimeError(f"未知 RBAC 角色 {role_key}")
    exists = (await db.execute(
        select(SubjectRole).where(
            SubjectRole.subject_type == subject_type,
            SubjectRole.subject_id == subject_id,
            SubjectRole.role_id == role.id,
            SubjectRole.scope_type == scope_type,
            SubjectRole.scope_id == scope_id,
            SubjectRole.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if exists is not None:
        return
    db.add(SubjectRole(
        subject_type=subject_type, subject_id=subject_id,
        role_id=role.id, scope_type=scope_type, scope_id=scope_id,
        granted_by=granted_by, granted_reason=granted_reason,
    ))
    invalidate_subject(subject_type, subject_id)


async def revoke_role(
    db: AsyncSession, *,
    subject_type: str, subject_id: str,
    role_key: str, scope_type: str, scope_id: str | None,
) -> None:
    """幂等撤销（软删）。"""
    role = (await db.execute(
        select(Role).where(Role.role_key == role_key, Role.deleted_at.is_(None))
    )).scalar_one_or_none()
    if role is None:
        return
    row = (await db.execute(
        select(SubjectRole).where(
            SubjectRole.subject_type == subject_type,
            SubjectRole.subject_id == subject_id,
            SubjectRole.role_id == role.id,
            SubjectRole.scope_type == scope_type,
            SubjectRole.scope_id == scope_id,
            SubjectRole.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if row is None:
        return
    row.soft_delete()
    invalidate_subject(subject_type, subject_id)
```

业务侧调用点（与 plan §8 步骤 3 对齐）：

| 业务写入 | 服务文件 | 调用 |
|---|---|---|
| 创建 / 软删 / 更新 `OrgMembership` | `app/services/`（按 service 拆分实际位置） | `grant_role` / `revoke_role`，role_key=`org_{role}` |
| 创建 / 软删 `AdminMembership` | 同上 | `platform_admin`（scope=org） |
| 创建 / 软删 / 更新 `WorkspaceMember` | `app/services/workspace_member_service.py` | `workspace_{role}` |
| 改 `User.is_super_admin` | `app/services/user_service.py`（或对应位置） | True→grant；False→revoke `platform_super` |

---

## 10. `/auth/me` 增量

修改 `/auth/me` 接口（通常在 `app/api/auth.py`），响应增量增加 `rbac` 子对象：

```python
class MeResponse(BaseModel):
    id: str
    name: str
    # ...既有字段保持不变...
    rbac: RbacContext


class RbacContext(BaseModel):
    role_keys: list[str]
    perms: list[str]
    app_codes: list[str]


@router.get("/me")
async def me(user=Depends(get_current_user_unchecked), db=Depends(get_db)):
    base = await build_me_payload(user)            # 现有逻辑
    base["rbac"] = await get_login_rbac(db, user)  # 新增
    return base
```

`get_login_rbac` 内部按 plan §3 描述：解析 subject_roles → role_menus.perms + role_apps.app_code，结果按 `(subject_id)` 缓存 60s。

---

## 11. Settings 增量

`app/core/config.py`：

```python
RBAC_AUDIT_ENABLED: bool = False
RBAC_CACHE_TTL_SECONDS: int = 60
SKIP_RBAC_BACKFILL: bool = False  # 紧急逃生开关
```

同步加入 `.env.example`。

---

## 12. 替换映射表（第二期使用，本期备查）

| 旧依赖 | v2 等价 |
|---|---|
| `require_super_admin_dep` | `require_perms("platform:cluster:manage", scope_type="platform")` 或新增专用 platform 权限 |
| `require_org_admin` | `require_perms("org:update", scope_type="org", scope_param="org_id")` |
| `require_org_member` | `require_perms("org:read", scope_type="org", scope_param="org_id")` |
| `require_org_member_role("operator")` | 改造为按具体动作权限 |
| `require_org_role("admin")` | `require_perms("org:update", scope_type="org", scope_param="org_id")` |
| `check_workspace_access(ws, user, "manage_members")` | `require_perms("workspace:member:invite", scope_type="workspace", scope_param="workspace_id", parent_org_param="org_id")` |
| `check_workspace_access(ws, user, "edit_blackboard")` | `require_perms("workspace:update", scope_type="workspace", scope_param="workspace_id", parent_org_param="org_id")` |

---

## 13. 验收用例

测试文件位置 `nodeskclaw-backend/tests/rbac/`：

| 用例 | 覆盖点 |
|---|---|
| `test_seed_apps.py` | 4 个内置应用幂等 |
| `test_seed_roles.py` | 9 角色 + role_key 唯一 |
| `test_seed_menus.py` | 16 个 perms 写入 + CHECK 约束生效 |
| `test_seed_role_menus.py` | 角色 × 按钮 绑定关系 |
| `test_seed_role_apps.py` | 角色 × 应用 绑定 |
| `test_seed_backfill.py` | 给定历史 4 张 legacy 表 → subject_roles 行数预期 |
| `test_resolver_allow_deny.py` | has_perms 多场景 |
| `test_resolver_scope_inherit.py` | org_admin 自动覆盖 workspace（带 parent_org_id） |
| `test_resolver_super.py` | platform_super 全通 |
| `test_resolver_no_parent_org.py` | workspace scope 不提供 parent_org_id → 不跨级 |
| `test_cache.py` | LRU 命中 + 失效 |
| `test_rbac_sync.py` | grant_role / revoke_role 幂等 + 缓存失效 |
| `test_audit.py` | RBAC_AUDIT_ENABLED 开关 |
| `test_admin_guard.py` | assert_not_super_admin / assert_not_admin_role |
| `test_auth_me_rbac_payload.py` | `/auth/me` 响应包含 rbac 子对象 |
| `test_migration_roundtrip.py` | upgrade + downgrade + upgrade 闭环 |

**回归**：现有 `tests/` 全量必须保持绿色。

**手工冒烟**：
1. `./dev.sh ce`：登录 admin → `GET /auth/me` 验证 `rbac.app_codes` 包含 `PORTAL`、`ADMIN`
2. `./dev.sh ee`：登录 EE admin → `rbac.app_codes` 包含 4 个全部应用
3. Portal UI 邀请新成员 → 检查 `subject_roles` 表对应行已写入
4. `psql` 对账：`SELECT COUNT(*) FROM subject_roles WHERE deleted_at IS NULL` 应 ≈ `is_super_admin=true` 数 + `OrgMembership` 数 + `AdminMembership` 数 + `WorkspaceMember` 数

---

## 14. 风险与回滚

| 风险 | 缓解 |
|---|---|
| menus 表与现有静态路由不一致 | 第一期只 seed `type=F`，前端不动 |
| 大表 backfill 慢 | 进度日志 + `SKIP_RBAC_BACKFILL` 开关 |
| CHECK 约束在测试 DB（SQLite）失效 | 测试库统一切 PostgreSQL |
| 双写遗漏漂移 | 周对账脚本 `scripts/check_rbac_drift.py`，比对 4 张 legacy 表与 subject_roles |
| `/auth/me` 响应增量被前端 schema 校验拒绝 | 全部包在 `rbac` 子对象，未知字段前端默认忽略 |
| Alembic 升级失败 | 单事务 DDL，downgrade 完整 |

回滚：
1. `alembic downgrade <prev>` 删 7 张新表
2. 注释 `seed.py` 中 `await seed_rbac(...)`
3. `/auth/me` 响应去除 `rbac` 字段
4. `app/core/rbac/` / `app/services/rbac_sync.py` 保留无副作用

---

## 15. 文件清单与改动量

| 类别 | 文件 | 行数预估 |
|---|---|---|
| 新增 | `app/models/rbac/{role,menu,app,subject_role,role_menu,role_app,permission_audit_log}.py` + `__init__.py` | ~320 |
| 新增 | `app/core/rbac/{scope,resolver,decorators,cache,audit,admin_guard,exceptions}.py` + `__init__.py` | ~520 |
| 新增 | `app/services/rbac_sync.py` | ~140 |
| 新增 | `app/services/rbac_context_service.py`（`get_login_rbac`） | ~80 |
| 新增 | `app/startup/seed_rbac.py` | ~350 |
| 新增 | `alembic/versions/<auto>_rbac_phase1_mom_style.py` | ~260 |
| 新增 | `app/api/admin/rbac_debug.py`（只读 Debug API） | ~80 |
| 修改 | `app/core/config.py` / `app/core/exceptions.py` | +20 |
| 修改 | `app/startup/seed.py`（追加 1 行） | +2 |
| 修改 | `app/api/auth.py`（/me 增量） | +15 |
| 修改 | 各业务 service 双写调用 | +50 |
| 修改 | `app/models/__init__.py`（导出新模型） | +10 |
| 新增 | `tests/rbac/*.py`（共 16 个） | ~900 |
| 修改 | i18n 词条 `errors.rbac.*` | +20 |
| **总计** | | **约 2800 行新增代码 + 测试** |

---

## 16. 评审 Checklist

提交评审前作者自检：

- [ ] 所有新表都有 `deleted_at`，唯一索引都是 partial
- [ ] `menus.menu_type` CHECK + `menus.perms` 条件 CHECK 都生效
- [ ] Alembic `down_revision` 指向 `ec27348942b6`
- [ ] `subject_type` / `scope_type` 都有 CHECK 约束
- [ ] `has_perms()` 严格 2 次 SQL（subject 角色 + 角色权限），无 N+1
- [ ] grant/revoke 都触发 `invalidate_subject`
- [ ] CE / EE 两种模式 seed 都跑通，`subject_roles` 行数对齐预期
- [ ] `/auth/me` 响应包含 `rbac` 子对象，旧字段无变化
- [ ] i18n 词条 `errors.rbac.*` 中英双语都齐备
- [ ] PR 描述写明：本期**不修改**任何现有业务接口的鉴权行为

---

## 17. 下一期前置条件

第二期（前端动态菜单 + 替换 require_org_admin + Agent 身份）启动前提：
1. 第一期上线后至少观察 1 周，周对账无漂移
2. `subject_roles` 行数 vs legacy 字段差异 < 0.1%
3. Debug API 在 staging 验证可正确列出任意 subject 的角色继承
4. RFC 0002（前端动态菜单切换）评审通过
