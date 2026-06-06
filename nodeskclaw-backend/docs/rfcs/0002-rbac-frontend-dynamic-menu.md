# RFC 0002：前端动态菜单 + 替换 require_org_admin（第二期）

> **状态：占位 / 待立项**
>
> 本文档是 RFC 0001（RBAC 基础设施 + 双写）的后续期次。第一期上线并稳定运行 ≥ 1 周、对账无漂移后，方可启动本期。

## 1. 范围

### 1.1 后端
- 把 `app/core/deps.py` 中 `require_org_admin` / `require_org_member` / `require_org_member_role` / `require_org_role` 全部替换为 RFC 0001 §12 表中的 `require_perms(...)` 等价调用
- 把 `app/services/workspace_member_service.py:check_workspace_access` 改为内部调用 `has_perms`
- 把 `app/services/workspace_actor_access.py` 中 Agent 无条件放行的逻辑改为严格按 `agent_workspace_executor` 角色判定
- 接入超管保护：在 `user_service` / 角色管理 API 入口调用 RFC 0001 `assert_not_super_admin` / `assert_not_admin_role`
- 新增 `agent_identities` 表，让 Agent 拥有独立身份 ID（不再回落到 `Instance.created_by`），并在 `subject_roles` 中以 `subject_type='agent'` 单独授权
- 把现有 `WorkspaceMember.permissions: JSON` 自定义权限也双写到 RBAC（通过自定义 org-level role 实现）

### 1.2 前端
- 在 `nodeskclaw-portal` 与 `ee/nodeskclaw-frontend` 中：
  - 消费 `/auth/me` 中 `rbac.role_keys` / `rbac.perms` / `rbac.app_codes` 字段
  - 新增 `useAuth().hasAuth(perms_code)` 组合式函数（对齐 MOM `useAuth()`）
  - 在路由 `meta.roles` 基础上新增 `meta.perms`、`meta.appCode` 字段
  - 实现 `filterAuthRoutesByPerms()` / `filterAuthRoutesByAppCode()`
  - 实现 `createAppContextGuard`：根据 URL 自动检测当前 `app_code`，参照 MOM `app-context.ts`
- 完整 seed `menus` 表 `type=M/C` 数据，作为侧边栏来源
- 新增 `GET /api/menus/tree?app_code=...` 接口，返回当前用户在该应用下可见的菜单树

## 2. 依赖

- ✅ RFC 0001 全部交付物上线
- ✅ `subject_roles` 数据与 legacy 字段对账无漂移（连续 7 天）
- ✅ `permission_audit_logs` 至少灰度开启 1 周，确认 deny 率符合预期
- ✅ Debug API 验证可列出任意 subject 角色继承链

## 3. 风险

- **路由改造范围广**：DeskClaw Portal 当前是「全量静态路由 + i18n」，切换为动态菜单需要逐模块灰度
- **EE Admin 同步改造**：`ee/nodeskclaw-frontend` 使用 shadcn-vue，菜单组件结构与 Portal 不同
- **Agent 身份切换不向后兼容**：现有 Agent 调用必须先迁移到独立身份

## 4. 验收标准

- 所有现存业务接口的鉴权行为零变化（通过完整回归测试）
- `require_org_admin` 等老依赖在代码中完全清零（grep 验证）
- 前端 `useAuth().hasAuth("gene:publish")` 在按钮上工作
- 侧边栏菜单从后端 `/api/menus/tree` 拉取，与静态路由 hybrid 模式至少灰度 2 周

## 5. 立项前需澄清

- 是否需要支持「自定义角色」？（MOM 支持自定义 `sys_role` + `sys_role_menu` 绑定）
- 自定义权限点是否限定在 org scope？或允许跨 org 共享？
- 是否引入「角色继承」（role inherits role）？MOM 没有此机制，但 OPA / Casbin 通常有

> 以上澄清在第一期上线后启动本期前回答。
