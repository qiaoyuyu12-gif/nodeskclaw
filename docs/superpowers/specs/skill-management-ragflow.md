# 企业技能管理平台 × RAGFlow 集成设计

**状态**: 设计中  
**日期**: 2026-05-14  
**方案**: A — RAGFlow 直连网关模式

---

## 背景与目标

在现有 DeskClaw 管理平台基础上扩展，构建企业技能管理能力：

1. **AI Agent 技能管理** — 管理 Gene 技能包，将 RAGFlow 知识库绑定到 Agent 实例
2. **员工知识技能管理** — 员工通过 Portal 自助发起 RAG 问答，消费企业知识库

RAGFlow 作为纯后端 API，不向员工暴露界面。知识来源包括内部文档（Word/PDF）和业务系统数据（ERP/CRM/HR）。

---

## 整体架构

```
nodeskclaw-portal (Vue 3)
  ├── 管理员视图：知识库管理 / Gene 技能绑定 / 员工技能分配
  └── 员工视图：技能搜索 / RAG 问答入口

nodeskclaw-backend (FastAPI)
  ├── 现有模块（不改动）
  └── 新增 app/skill/ 模块
        ├── routers/
        ├── services/
        │   ├── skill_service.py
        │   ├── ragflow_adapter.py
        │   └── kb_service.py
        └── models/
            ├── KnowledgeBase
            ├── SkillDefinition
            └── AgentSkillBinding

RAGFlow（独立部署）
  └── HTTP API 被 ragflow_adapter 调用
      ├── 知识库 CRUD（/api/v1/datasets）
      ├── 文档上传/同步
      └── 检索问答（/api/v1/retrieval）
```

**数据流**：员工 Portal 发起问答 → `skill_service` 查找绑定知识库 → `ragflow_adapter` 调用 RAGFlow 检索 → 结果注入 Agent 上下文 → 返回回答。

---

## 数据模型

### `knowledge_bases`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | |
| org_id | FK | 归属组织 |
| name | str | 知识库名称 |
| ragflow_kb_id | str | RAGFlow 侧 dataset ID |
| ragflow_endpoint | str | RAGFlow 服务地址 |
| api_key_encrypted | bytes | AES-256-GCM 加密（复用现有加密工具） |
| source_type | enum | `doc` / `system` / `mixed` |
| deleted_at | datetime | 软删除 |

### `skill_definitions`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | |
| org_id | FK | |
| name | str | 技能名称 |
| type | enum | `rag_query` / `gene` / `composite` |
| kb_id | FK nullable | 关联知识库（`rag_query` 类型必填） |
| config | JSONB | 检索 top_k、prompt 模板等 |
| deleted_at | datetime | 软删除 |

### `agent_skill_bindings`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | |
| instance_id | FK | DeskClaw 实例 |
| skill_id | FK | 技能定义 |
| enabled | bool | 是否启用 |
| created_by | FK | 操作管理员 |
| deleted_at | datetime | 软删除 |

唯一约束：`(instance_id, skill_id)` 使用 Partial Unique Index（`WHERE deleted_at IS NULL`）。

---

## API 端点

### 知识库管理（管理员）

```
POST   /api/v1/knowledge-bases
GET    /api/v1/knowledge-bases
PATCH  /api/v1/knowledge-bases/{id}
DELETE /api/v1/knowledge-bases/{id}          # 软删除
POST   /api/v1/knowledge-bases/{id}/sync     # 触发文档同步到 RAGFlow
```

### 技能定义（管理员）

```
POST   /api/v1/skills
GET    /api/v1/skills                        # 支持 type 过滤
PATCH  /api/v1/skills/{id}
DELETE /api/v1/skills/{id}                   # 软删除
POST   /api/v1/skills/{id}/bind              # 绑定到 Agent 实例
DELETE /api/v1/skills/{id}/bind/{instance_id}
```

### 技能使用（员工）

```
GET    /api/v1/skills/my                     # 查看自己可用技能
POST   /api/v1/skills/{id}/query             # 发起 RAG 问答
```

权限：管理员端点加 `require_admin` 依赖，员工端点验证 JWT 即可。

`GET /api/v1/skills/my`：返回 org 内所有 `enabled=true` 的技能（不限于特定实例）。

`POST /api/v1/skills/{id}/query`：RAGFlow 不可用时返回降级响应（HTTP 200，`data.degraded=true`，`message` 提示用户稍后重试），不返回 503。

---

## 前端改动（nodeskclaw-portal）

### 路由

```
/skills                          # 员工：技能卡片 + RAG 问答入口
/admin/knowledge-bases           # 管理员：知识库管理
/admin/skills                    # 管理员：技能定义管理
/admin/skills/bind               # 管理员：技能绑定到 Agent 实例
```

### 组件

```
src/views/skills/
  SkillListView.vue
  admin/
    KnowledgeBaseListView.vue
    KnowledgeBaseFormView.vue
    SkillDefinitionListView.vue
    SkillBindingView.vue

src/components/skills/
  RagQueryDialog.vue             # 员工问答对话框
  KbSyncStatus.vue               # 同步状态徽章（idle/syncing/error）
```

导航：侧边栏"工作区"下新增"技能库"入口；管理员侧边栏新增"知识库管理"。图标使用 `lucide-vue-next`（`BookOpen`、`Brain`）。

---

## 实施阶段

| 阶段 | 内容 | 优先级 |
|------|------|--------|
| P0 | 数据模型 + Alembic 迁移 | 必须 |
| P0 | `ragflow_adapter.py` 封装 RAGFlow API | 必须 |
| P1 | 知识库管理 API + Admin 前端 | 必须 |
| P1 | 技能定义 + 绑定 API | 必须 |
| P2 | 员工 Portal 问答界面 | 必须 |
| P3 | 文档同步（业务系统对接） | 后续迭代 |
