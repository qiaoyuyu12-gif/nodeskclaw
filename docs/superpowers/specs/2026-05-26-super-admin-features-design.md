# 超管后台功能丰富 — 设计文档

- 日期：2026-05-26
- 范围：EE 版超管后台（/admin/*）
- 状态：设计已确认，待实现计划

## 1. 背景与目标

现有超管后台仅有 `AdminOrgList.vue` + `ee/backend/api/admin/organizations.py`，能力局限于组织 CRUD（编辑按钮在前端尚未实现）。本期目标是把超管后台扩展为可用的运维控制台，覆盖：

1. 组织管理增强（编辑、查看详情、查看组织成员）
2. 用户管理（全局用户列表 + 组织内成员管理）
3. 用户密码重置
4. 功能模块（Feature）的组织级暴露开关
5. 全部超管动作的审计留痕

非目标：

- 多角色 RBAC（仅保留单一超管角色，模型字段预留）
- 用户主动找回密码 / SSO 流程（不变）
- CE 版本暴露这些新能力（仅 EE）

## 2. 关键决策

| # | 决策 | 理由 |
|---|---|---|
| 1 | 一次性交付 4 项能力 | 用户明确要求 |
| 2 | 单一超管角色 | YAGNI，模型字段保留扩展空间 |
| 3 | 密码重置 = 生成随机临时密码 | 不依赖 SMTP；用户下次登录强制改密 |
| 4 | Feature 组织级覆盖 | 默认 edition_features 之上叠加 org override，无全局覆盖层 |
| 5 | 全局用户 + 组织成员双视图 | 覆盖两种典型运维场景 |
| 6 | 复用 operation_audit_log 不限频 | 现成基础设施，无需 2FA |
| 7 | 侧边栏布局 + 嵌套路由 | 信息密度高，二级页面自然 |

## 3. 整体架构

### 3.1 前端目录

```
nodeskclaw-portal/src/views/admin/
├── AdminLayout.vue         # 侧边栏 + <router-view>
├── AdminOrgList.vue        # 已存在 — 增强编辑、行点击进详情
├── AdminOrgDetail.vue      # 新增 — Overview / Members / Features 三 tab
├── AdminUserList.vue       # 新增 — 全局用户搜索 + 分页
├── AdminUserDetail.vue     # 新增 — 状态切换 + 密码重置
├── AdminFeatureList.vue    # 新增 — Feature 列表（默认值 + 覆盖计数 + 抽屉查看覆盖明细）
└── AdminAuditLog.vue       # 新增 — 审计日志查询
```

### 3.2 前端路由

```
/admin                      → AdminLayout（守卫：requireSuperAdmin + edition==='ee'）
  ├── orgs                  → AdminOrgList
  ├── orgs/:id              → AdminOrgDetail
  ├── users                 → AdminUserList
  ├── users/:id             → AdminUserDetail
  ├── features              → AdminFeatureList
  └── audit                 → AdminAuditLog
```

### 3.3 后端目录

```
ee/backend/api/admin/              # 路由层 — 仅做参数解析、调用 service、组装响应
├── organizations.py               # 已有 — 追加成员端点
├── users.py                       # 新增
├── features.py                    # 新增
└── audit.py                       # 新增

ee/backend/services/admin/         # 业务层 — 守卫、审计、级联、合并逻辑
├── __init__.py
├── org_admin_service.py           # 组织 CRUD + 成员管理 + 配额校验
├── user_admin_service.py          # 用户启停、超管位、密码重置、自我保护
├── feature_admin_service.py       # FeatureGate 合并、override CRUD
└── audit_service.py               # 统一审计写入 + 查询，封装 with audit_context
```

endpoint 仅负责：

```python
@router.put("/users/{user_id}")
async def update_user(
    user_id: str,
    body: AdminUserUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin_dep),
):
    return await user_admin_service.update_user(db, admin, user_id, body)
```

所有规则（不能停用自己、不能撤销自己 super_admin、不能删除最后一个超管、级联软删 OrgMembership、override 合并、审计落库）全部在 service 层，endpoint 不做 if/else。

### 3.4 鉴权链

每个 admin endpoint：

```python
dependencies=[
    Depends(require_feature("platform_admin")),
    Depends(require_super_admin_dep),
]
```

## 4. 数据模型变更

### 4.1 新增表 `organization_feature_overrides`

```python
class OrganizationFeatureOverride(BaseModel):
    __tablename__ = "organization_feature_overrides"
    __table_args__ = (
        Index("uq_org_feature", "org_id", "feature_id",
              unique=True, postgresql_where=text("deleted_at IS NULL")),
    )
    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"))
    feature_id: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255))
    set_by_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
```

### 4.2 复用已有字段

- `users.is_super_admin`、`users.is_active`、`users.password_hash`、`users.must_change_password`
- `BaseModel.deleted_at`（已存在的软删字段）
- `operation_audit_log`：直接复用，无需新字段

### 4.2.1 新增字段 `users.deleted_by`

仅在 `users` 表新增 `deleted_by: String(36) | None`，记录是哪个超管执行的软删。其他表本期不引入该字段（无超管删除场景）。

### 4.3 软删级联策略（重要）

超管删除用户时：

**软删（设置 deleted_at + users.deleted_by）：**
- `users` 行本身
- 该用户的所有 `OrgMembership`（移除组织关系）
- 该用户的所有 `AdminMembership`（移除平台管理身份）
- `user_llm_key`、`user_llm_config`（属用户私有配置）

**保留不动（数据完整性 / 审计可追溯性）：**
- `operation_audit_log`（所有审计记录，含他人对该用户的操作）
- `conversation` / `workspace_message` / `workspace_task` / `workspace_deploy`（业务历史）
- `event_log` / `deploy_record` / `llm_usage_log` / `decision_record`（运行历史）
- `instance_member`（实例成员历史）
- 任何外键指向该 user_id 的业务数据

读取时业务层不联表过滤 `user.deleted_at IS NULL`；前端展示时若用户已删除，显示 "已注销用户"。该用户名/邮箱本身仍保留在 users 行中以便回溯。

**禁止物理删除**：本期不提供任何 hard delete 入口。

### 4.4 Alembic 迁移

```bash
uv run alembic revision --autogenerate -m "add organization_feature_overrides and users.deleted_by"
```

新增 1 张表 + `users.deleted_by` 单列。不修改其他字段，零数据回退风险。

### 4.5 FeatureGate 改造

```python
async def is_enabled(feature_id: str, org_id: str | None = None) -> bool:
    if org_id:
        row = await db.execute(
            select(OrganizationFeatureOverride.enabled).where(
                OrganizationFeatureOverride.org_id == org_id,
                OrganizationFeatureOverride.feature_id == feature_id,
                OrganizationFeatureOverride.deleted_at.is_(None),
            )
        )
        v = row.scalar_one_or_none()
        if v is not None:
            return v
    return _edition_default(feature_id)  # 现有逻辑
```

启动期对孤儿 feature_id（不在 features.yaml 中）输出告警日志，不自动清理。

## 5. 后端 API

全部以 `/admin` 为前缀，全部受双守卫，全部落审计。

### 5.0 响应契约（统一遵循项目现有约定）

**分页响应（所有列表端点必须）**：复用 `app/schemas/common.py::PaginatedResponse`：

```json
{
  "code": 0,
  "error_code": null,
  "message_key": null,
  "message": "success",
  "data": [...],
  "pagination": { "page": 1, "page_size": 20, "total": 123 }
}
```

不允许自定义 `items / size / nextCursor` 等字段名。

**单体响应**：复用 `ApiResponse[T]`，data 为对象。

**错误响应**：复用全站约定 `HTTPException(detail={error_code, message_key, message})`：

```json
{
  "detail": {
    "error_code": 40901,
    "message_key": "errors.admin.last_super_admin_forbidden",
    "message": "Cannot remove the last super admin"
  }
}
```

字段约束：
- `error_code` 为 **int**（与全站一致；不引入字符串型 code，避免双标）
- `message_key` 命名规范：`errors.<domain>.<reason>`，前端 i18n 缺失时回退 `message`
- 语义化由 `message_key` 表达；前端按 `message_key` 走分支判断而非 `error_code` 数值

**本期 error_code 分配区段**（避免与现网冲突）：

| 区段 | 含义 |
|---|---|
| 40901–40919 | 自我保护类（停用自己、撤销自己超管、删除自己、删除最后超管） |
| 40920–40939 | 组织管理类（slug 冲突、有运行实例、组织最后 admin） |
| 40940–40959 | 用户管理类（用户不存在、邮箱冲突、user 已被删除） |
| 40960–40979 | Feature override 类（feature_id 不在 yaml、override 不存在） |
| 40980–40999 | 审计类（非法 action value、时间范围非法） |

新增错误码必须在 PR 描述中列出，并同步 zh-CN + en i18n。

### 5.1 组织成员（追加到 organizations.py）

操作对象：`OrgMembership` 表（已存在）。role 取值来自现有 `OrgRole` 枚举：`admin` / `operator` / `member`。

```
GET    /admin/orgs/:id/members
POST   /admin/orgs/:id/members              body: {user_id, role: "admin"|"operator"|"member"}
PUT    /admin/orgs/:id/members/:user_id     body: {role}
DELETE /admin/orgs/:id/members/:user_id     # 软删 OrgMembership
```

注：本期不操作 `AdminMembership`（平台管理后台成员表），仅操作业务层 `OrgMembership`。

### 5.2 全局用户（users.py）

```
GET    /admin/users?q=&page=&size=
GET    /admin/users/:id
PUT    /admin/users/:id                     body: {is_active?, is_super_admin?}
POST   /admin/users/:id/reset-password      response: {temp_password}
DELETE /admin/users/:id                     # 软删 user + OrgMembership + AdminMembership + 私有配置；保留业务历史与审计
```

### 5.3 Feature 控制（features.py）

```
GET    /admin/features                      # features.yaml 全量 + edition 默认 + 各 feature 的 override 计数
GET    /admin/features/:feature_id/overrides?page=&size=    # 该 feature 的 override 明细（分页）
GET    /admin/orgs/:id/features             # 某组织所有 feature 的 effective + override 状态
PUT    /admin/orgs/:id/features/:feature_id body: {enabled, reason?}
DELETE /admin/orgs/:id/features/:feature_id
```

**`/admin/orgs/:id/features` 单条返回结构**（前端不再猜来源）：

```json
{
  "feature_id": "knowledge_base",
  "enabled": true,
  "source": "override",          // "default" | "override"
  "default_enabled": false,      // edition_features 中的默认值
  "reason": "试点用户提前启用",   // 仅 source=override 时有
  "set_by_user_id": "...",
  "set_at": "2026-05-26T08:00:00Z"
}
```

`GET /admin/features` 列表项：

```json
{
  "feature_id": "knowledge_base",
  "name": "Knowledge Base",
  "description": "...",
  "default_enabled": false,
  "override_count": 3            // 该 feature 上有 override 的组织数
}
```

前端只看 `source` 字段判断状态，不依据"是否存在 override 行"做隐式推断。

### 5.4 审计（audit.py）

```
GET    /admin/audit?actor=&action=&from=&to=&page=&size=    # action 取自 AdminAction enum value
GET    /admin/audit/actions                                  # 返回所有 AdminAction value，供前端筛选下拉
```

### 5.5 密码重置实现要点

- `secrets.token_urlsafe(12)` 生成 16 字符临时密码
- 写库：`password_hash = hash(temp)`、`must_change_password = True`
- 响应仅在内存中返回明文一次，**不进入审计 before/after**
- 审计仅记录 "重置了用户 X 的密码" 事件本身

### 5.6 自我保护守卫

**全部位于 `user_admin_service` / `org_admin_service` 中**，endpoint 不重复实现。校验失败统一抛 `HTTPException(409)`，前端按 `error_code` 显示本地化提示。

- 不能停用自己（is_active=False）
- 不能撤销自己 is_super_admin
- 不能删除自己
- 不能让系统失去"最后一个超管"（service 层查询计数 + 数据库 partial unique index 兜底）

### 5.7 Service 层关键契约

| Service 方法 | 守卫 | 审计 | 备注 |
|---|---|---|---|
| `org_admin_service.create_org` | slug 唯一 | create | — |
| `org_admin_service.update_org` | — | update（diff） | — |
| `org_admin_service.delete_org` | 无运行中实例 | delete | 软删 |
| `org_admin_service.add_member` | user 存在；非重复 | member.add | 复用 OrgMembership |
| `org_admin_service.remove_member` | 非组织最后 admin | member.remove | 软删 |
| `user_admin_service.update_user` | 自我保护 + 最后超管 | update | — |
| `user_admin_service.reset_password` | — | password_reset（不含明文） | 返回 temp_password |
| `user_admin_service.delete_user` | 自我保护 + 最后超管 | delete | 按 §4.3 软删白名单级联，业务/审计数据保留 |
| `feature_admin_service.set_override` | feature_id 在 yaml | override.set | — |
| `feature_admin_service.clear_override` | — | override.clear | — |
| `feature_admin_service.resolve` | — | — | FeatureGate 调用入口 |

`audit_service.with_audit(action, resource, **fields)` 作为 async context manager，包裹 service 方法体；失败抛异常时写"失败"审计。

## 6. 前端页面

### 6.1 AdminLayout.vue

- 顶部：返回门户按钮 + 当前用户名 + 退出
- 侧边栏：Orgs / Users / Features / Audit 四个一级入口
- 路由守卫：双重 `requireSuperAdmin` + edition==='ee'

### 6.2 AdminOrgList.vue（增强）

- 现有：列表、搜索、创建、删除
- 新增：编辑按钮真正工作 → 弹窗修改 plan/quota/cluster
- 新增：行点击跳 AdminOrgDetail

### 6.3 AdminOrgDetail.vue（新增）

- Tab Overview：基础字段 + quota 实际用量
- Tab Members：成员表（user / role / joined_at）+ 添加/改角色/移除
- Tab Features：该组织所有 feature，三态显示（默认开/默认关/被覆盖），下拉切换：跟随默认 / 强制开 / 强制关 + 理由

### 6.4 AdminUserList.vue（新增）

- 搜索框 + 分页表格
- 列：email / name / is_super_admin / is_active / 所属组织数 / created_at
- 行操作：详情 / 重置密码 / 启用-禁用切换

### 6.5 AdminUserDetail.vue（新增）

- 基本信息（email 不可改）
- 开关：is_super_admin / is_active（二次确认）
- 重置密码按钮 → 弹窗显示临时密码 + 复制按钮 + "我已记下"才能关闭
- 所属组织列表（链接到 AdminOrgDetail）

### 6.6 AdminFeatureList.vue（新增）

不做"全矩阵"。视图以 feature 为主轴，加载量恒定（features.yaml 条目数级别）：

- 列表行（来自 features.yaml）：
  - feature_id / name / description
  - edition 默认值（开/关 chip）
  - **覆盖计数**：`N orgs override`（点击可展开）
- 点击行 → 右侧抽屉，仅显示**该 feature 上存在 override 的组织**（按 updated_at 倒序，分页）
  - 每条：org_name / 状态（强制开/关）/ reason / set_by / set_at / 清除按钮
  - 顶部 "添加 override" → 选组织 → 选状态 + 理由
- 不在抽屉里展示"未覆盖的组织"——那是组织视图的事
- 反向入口已存在：`AdminOrgDetail.vue` 的 Features tab 提供"以组织为主轴"的视图

数据接口配套（修改 §5.3）：

```
GET    /admin/features                      # features.yaml 全量 + edition 默认 + 各 feature 的 override 计数
GET    /admin/features/:feature_id/overrides?page=&size=    # 该 feature 的 override 列表（仅 N 条，分页）
GET    /admin/orgs/:id/features             # 该组织全量 feature 状态（保留，供 AdminOrgDetail 使用）
PUT    /admin/orgs/:id/features/:feature_id body: {enabled, reason?}
DELETE /admin/orgs/:id/features/:feature_id
```

**性能契约**：

- AdminFeatureList 单次加载 = O(features) ≤ 50 行
- 抽屉一次加载 = O(覆盖数 × pageSize)，默认 pageSize=20
- 不在任何视图中加载 `features × orgs` 全集

### 6.7 AdminAuditLog.vue（新增）

- 时间倒序表格：time / actor / action / target / ip
- 筛选：actor / action 类型 / 时间区间
- 行展开看 before/after JSON

### 6.8 前端 API client

`nodeskclaw-portal/src/services/adminApi.ts` 扩展，新增方法：

- `fetchOrgMembers / setOrgMember / removeOrgMember`
- `fetchUsers / fetchUser / updateUser / resetPassword / deleteUser`
- `fetchFeatures / fetchOrgFeatures / setOrgFeature / clearOrgFeature`
- `fetchAuditLogs`

CE 模式仅保留组织 CRUD，新方法在 CE 入口不渲染。

### 6.9 i18n

- 前端新增键到 `admin.*` 命名空间（zh-CN + en）
- 后端错误统一 `message_key` + `message`

## 7. 安全与审计

### 7.1 审计动作清单

写入入口统一在 `audit_service.with_audit(...)`；service 方法不直接调 `db.add(OperationAuditLog)`。

**A. 超管动作（在新 admin endpoint 中触发）**

| 动作 | resource_type | before/after |
|---|---|---|
| 创建组织 | org | null / 快照 |
| 修改组织 | org | diff |
| 删除组织（软删） | org | 快照 / null |
| 加/改/移除成员 | org_member | role 变化 |
| 修改用户标志 | user | 标志变化 |
| 重置密码 | user | **不记录密码** |
| 设置 feature override | feature_override | 默认 → 覆盖 |
| 清除 feature override | feature_override | 覆盖 → 默认 |

`with audit_context(action="...", ...):` 装饰每个 endpoint；异常时写"失败"审计。

**B. 最低安全审计（本期补，所有用户路径触发）**

| 动作 | resource_type | 字段 | 触发点 |
|---|---|---|---|
| 登录成功 | auth | actor_id / ip / user_agent | `app/api/auth.py` 登录成功路径 |
| 登录失败 | auth | attempted_email / ip / user_agent / reason | `app/api/auth.py` 登录失败路径 |
| 登出 | auth | actor_id / ip | `app/api/auth.py` 登出路径 |

登录失败时 `actor_id` 写占位符 `"anonymous"`、`actor_type` 写 `"anonymous"`（`operation_audit_log.actor_id` 当前为 NOT NULL，不修改 schema 以最小侵入），`details.attempted_email` 必填便于排查爆破。**禁止把密码/Token 写入审计**。

非本期：业务操作全量审计、敏感数据访问审计、API key 使用审计 → 留 `advanced_audit` feature 单独立项。

### 7.1.1 AdminAction Enum（强约束）

所有审计动作必须走 enum，**禁止任何裸字符串调用 `audit_service.with_audit("...")`**。`mypy` / 代码评审强制此规则。

位置：`nodeskclaw-backend/app/models/admin_action.py`

```python
from enum import Enum

class AdminAction(str, Enum):
    # 组织
    ORG_CREATE          = "org.create"
    ORG_UPDATE          = "org.update"
    ORG_DELETE          = "org.delete"
    # 组织成员
    ORG_MEMBER_ADD      = "org_member.add"
    ORG_MEMBER_UPDATE   = "org_member.update"
    ORG_MEMBER_REMOVE   = "org_member.remove"
    # 用户
    USER_UPDATE         = "user.update"
    USER_RESET_PASSWORD = "user.reset_password"
    USER_DELETE         = "user.delete"
    # Feature override
    FEATURE_OVERRIDE_SET   = "feature_override.set"
    FEATURE_OVERRIDE_CLEAR = "feature_override.clear"
    # 安全（最低审计）
    AUTH_LOGIN_SUCCESS  = "auth.login_success"
    AUTH_LOGIN_FAILED   = "auth.login_failed"
    AUTH_LOGOUT         = "auth.logout"
```

值采用 `domain.verb` 格式，方便前端按前缀分组筛选、i18n 按值映射。

**约束**：
- 写入：`audit_service.with_audit(action: AdminAction, ...)` 签名只收 enum，类型检查兜底
- 数据库：`operation_audit_log.action` 列仍为 String(255)（兼容历史 + 业务全量审计将来扩展），但本期写入路径只允许 `AdminAction.value`
- 查询：`/admin/audit?action=` 接受 enum value 字符串，后端再解析回 enum；非法 value → 400
- 前端 `actionOptions` 数组直接从后端 `GET /admin/audit/actions` 拉取（返回 enum value 列表），避免前端硬编码

**i18n 映射**（前端 `admin.audit.actions[<value>]`）：

```jsonc
{
  "admin.audit.actions.org.create": "创建组织",
  "admin.audit.actions.user.reset_password": "重置用户密码",
  "admin.audit.actions.auth.login_failed": "登录失败",
  // ...每个 enum value 一条
}
```

新增 enum 值时必须同步：
1. `AdminAction` enum
2. zh-CN + en i18n
3. 审计单测

CI / 代码评审检查项：审计相关 PR diff 中必须同时改这三处，否则打回。

### 7.2 临时密码安全

- HTTPS 一次性返回
- 服务端不日志明文、不审计明文
- 前端 `navigator.clipboard` 复制，弹窗关闭即丢
- 登录后 `must_change_password=True` 触发 `ForceChangePassword.vue`

### 7.3 审计保留期与清理 Job

- **保留期：90 天**（physical delete）
- 实现：新增 `AuditRetentionRunner`，沿用现有 `ScheduleRunner` 异步轮询模式
  - 位置：`nodeskclaw-backend/app/services/audit_retention_runner.py`
  - 频率：每天 03:00 本地时间（低峰）跑一次
  - 行为：`DELETE FROM operation_audit_log WHERE created_at < NOW() - INTERVAL '90 days'`
  - **物理删除**（审计本身已是只追加，超期数据无价值，节省存储）
  - 单次 batch 上限 10 万行，超出分批，避免锁表
- 启动钩子：在 `main.py` 现有 `lifespan` 中追加 `AuditRetentionRunner.start()` / `stop()`
- 监控：每次清理后写一条 INFO log `[audit_retention] deleted N rows older than 90d`
- 配置项：在 `.env.example` 增加 `AUDIT_RETENTION_DAYS=90`（默认 90）和 `AUDIT_RETENTION_ENABLED=true`

## 8. 测试策略

### 8.1 后端

- **Service 层测试为主**（`ee/backend/services/admin/test_*.py`）：直接调 service 方法，覆盖所有守卫分支、级联、合并、审计写入
- **Endpoint 层测试**：仅做 happy path + 鉴权 403（不重复测业务规则）
- FeatureGate 单测：覆盖三态优先级

### 8.2 前端

- 每个新视图一个 vitest 渲染测试
- 关键交互：搜索触发请求、按钮触发 API、错误展示 toast

### 8.3 覆盖率目标

后端 ≥80%，前端关键路径有渲染测试。

## 9. 发布与回退

### 9.1 发布顺序

1. Alembic 迁移（只加表）
2. 后端 API + 单测
3. 前端页面 + i18n + 渲染测试
4. 文档：`docs/admin/super-admin-guide.md` 操作手册（独立 PR）

### 9.2 回退

- 前端：删除新 `/admin/*` 路由，旧 `/admin/orgs` 不受影响
- 后端：保留新表，下线新路由
- 数据：feature override 表保留无副作用，无需 down 迁移

## 10. 风险与未决事项

| 风险 | 缓解 |
|---|---|
| features.yaml id 变更导致孤儿 override | 启动期日志告警，不自动清理 |
| 矩阵视图组织过多时性能差 | 不做矩阵视图。Feature 列表 + 抽屉，加载量恒定 O(features) |
| 误操作"最后一个超管" | API 层 + 服务层双重检查 |
| 临时密码被误复制粘贴 | 弹窗强提示 + 复制后无再次获取入口 |

未决事项（不阻断本期，留待后续）：

- 多角色 RBAC（仅留字段，本期不启用）
- 邮件通知超管动作（依赖 SMTP 可用性，本期不做）
- 批量操作（批量启用/禁用用户）
- 业务操作全量审计 + 导出 + 不可篡改归档 → `advanced_audit` feature
