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
├── AdminFeatureMatrix.vue  # 新增 — Feature × 组织 矩阵
└── AdminAuditLog.vue       # 新增 — 审计日志查询
```

### 3.2 前端路由

```
/admin                      → AdminLayout（守卫：requireSuperAdmin + edition==='ee'）
  ├── orgs                  → AdminOrgList
  ├── orgs/:id              → AdminOrgDetail
  ├── users                 → AdminUserList
  ├── users/:id             → AdminUserDetail
  ├── features              → AdminFeatureMatrix
  └── audit                 → AdminAuditLog
```

### 3.3 后端目录

```
ee/backend/api/admin/
├── organizations.py        # 已有 — 追加成员端点
├── users.py                # 新增
├── features.py             # 新增
└── audit.py                # 新增
```

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
- `operation_audit_log`：直接复用，无需新字段

### 4.3 Alembic 迁移

```bash
uv run alembic revision --autogenerate -m "add organization_feature_overrides"
```

仅新增表，不修改现有字段，零回退风险。

### 4.4 FeatureGate 改造

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
DELETE /admin/users/:id                     # 软删 user + 级联软删其所有 OrgMembership
```

### 5.3 Feature 控制（features.py）

```
GET    /admin/features                      # features.yaml 全量 + edition 默认
GET    /admin/orgs/:id/features             # effective + override 状态
PUT    /admin/orgs/:id/features/:feature_id body: {enabled, reason?}
DELETE /admin/orgs/:id/features/:feature_id
```

### 5.4 审计（audit.py）

```
GET    /admin/audit?actor=&action=&from=&to=&page=&size=
```

### 5.5 密码重置实现要点

- `secrets.token_urlsafe(12)` 生成 16 字符临时密码
- 写库：`password_hash = hash(temp)`、`must_change_password = True`
- 响应仅在内存中返回明文一次，**不进入审计 before/after**
- 审计仅记录 "重置了用户 X 的密码" 事件本身

### 5.6 自我保护守卫

API 层和数据库约束双重保证：

- 不能停用自己（is_active=False）
- 不能撤销自己 is_super_admin
- 不能删除自己
- 不能让系统失去"最后一个超管"

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

### 6.6 AdminFeatureMatrix.vue（新增）

- 行：feature
- 列：组织（数量多时分页/筛选）
- 单元格四态：✓ 默认开 / ✗ 默认关 / ● 开（覆盖） / ○ 关（覆盖）
- 点击单元格 → 修改弹窗
- 备选视图：选定单一组织看其所有 feature

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

### 7.2 临时密码安全

- HTTPS 一次性返回
- 服务端不日志明文、不审计明文
- 前端 `navigator.clipboard` 复制，弹窗关闭即丢
- 登录后 `must_change_password=True` 触发 `ForceChangePassword.vue`

## 8. 测试策略

### 8.1 后端

- 每个新 endpoint 一个 pytest 用例（位于 `ee/backend/api/admin/test_*.py`）
- 覆盖：正向路径 / 非超管 403 / 自删自护 / 边界（空列表/不存在 ID）
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
| 矩阵视图组织过多时性能差 | 默认按组织分页 + 优先组织维度视图 |
| 误操作"最后一个超管" | API 层 + 服务层双重检查 |
| 临时密码被误复制粘贴 | 弹窗强提示 + 复制后无再次获取入口 |

未决事项（不阻断本期，留待后续）：

- 多角色 RBAC（仅留字段，本期不启用）
- 邮件通知超管动作（依赖 SMTP 可用性，本期不做）
- 批量操作（批量启用/禁用用户）
