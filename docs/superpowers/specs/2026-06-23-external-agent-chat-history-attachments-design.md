# 外部 Agent 聊天记录持久化 + 附件上传设计

**日期**: 2026-06-23  
**状态**: 已批准，待实现  
**范围**: nodeskclaw-backend + nodeskclaw-portal

---

## 背景

外部 Agent 聊天当前仅在前端内存维护消息，页面刷新即丢失，且不支持附件传递。本方案新增两张数据库表实现多会话持久化，并新增附件上传能力将文件 URL 传递给外部 Agent。

---

## 数据库设计

### 新增表：`external_agent_chat_sessions`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | |
| org_id | VARCHAR(36) | 所属组织 |
| agent_id | VARCHAR(36) FK | → external_agents.id，CASCADE DELETE |
| user_id | VARCHAR(36) | 会话归属用户 |
| title | VARCHAR(200) | 取第一条用户消息前 50 字自动生成 |
| created_at | TIMESTAMP | |
| updated_at | TIMESTAMP | 每次新消息写入时更新，用于列表排序 |
| deleted_at | TIMESTAMP | 软删除 |

索引：`(agent_id, user_id, deleted_at)`

### 新增表：`external_agent_messages`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | |
| session_id | VARCHAR(36) FK | → external_agent_chat_sessions.id，CASCADE DELETE |
| role | VARCHAR(16) | `user` 或 `assistant` |
| content | TEXT | 消息正文 |
| attachments | JSONB | nullable，格式见下 |
| created_at | TIMESTAMP | |

`attachments` 元素结构（**只存 `storage_key`，不存 URL**）：
```json
{
  "name": "chart.png",
  "size": 102400,
  "content_type": "image/png",
  "storage_key": "external-agents/org1/uuid/chart.png"
}
```

presigned URL 不持久化，原因：presigned URL 有有效期，存入 DB 后历史记录加载时 URL 已失效。`GET /sessions/{id}/messages` 返回消息时，后端遍历每条 user message 的 attachments，调 `storage_service.generate_presigned_url(storage_key)` 实时生成 URL 注入响应，前端始终拿到有效 URL。

无软删除字段（跟随 session 级联删除）。

---

## 后端 API

### 附件上传（新增）

```
POST /api/v1/external-agents/attachments/upload
权限: 已登录用户
Content-Type: multipart/form-data
Body: file (UploadFile，≤20MB)

Response 200:
{
  "storage_key": "external-agents/{org_id}/{uuid}/{filename}",
  "name": "chart.png",
  "size": 102400,
  "content_type": "image/png",
  "url": "https://presigned-url..."   // 仅供本次发送使用，不持久化到 DB
}
```

复用 `storage_service`，存储路径前缀 `external-agents/{org_id}/`。

### 会话管理（新增）

```
GET  /api/v1/external-agents/{agent_id}/sessions
     → 当前用户的会话列表，按 updated_at 倒序，软删除过滤

POST /api/v1/external-agents/{agent_id}/sessions
     → 创建空会话，title 暂为空，发送第一条消息后异步更新

DELETE /api/v1/external-agents/{agent_id}/sessions/{session_id}
     → 软删除（设置 deleted_at）
```

### 消息历史（新增）

```
GET /api/v1/external-agents/{agent_id}/sessions/{session_id}/messages
    → 按 created_at 升序返回全部消息
    → 鉴权：session.user_id 必须为当前用户，且 session.agent_id 与路径一致
```

### 聊天接口（已有，扩展）

```
POST /api/v1/external-agents/{agent_id}/chat
Body:
{
  "message": "帮我分析这张图",
  "session_id": "<UUID>",           // 必填，关联到数据库 session
  "attachments": [                   // 新增，可为空数组；url 由前端上传后临时持有
    {
      "name": "chart.png",
      "size": 102400,
      "content_type": "image/png",
      "storage_key": "...",
      "url": "https://..."           // 用于本次转发给外部 Agent，不写入 DB
    }
  ]
}
```

**附件传递给外部 Agent 的格式**（URL 引用，追加到消息文本末尾）：
```
[用户消息正文]

附件:
- chart.png (image/png, 100KB): https://presigned-url...
- data.csv (text/csv, 32KB): https://presigned-url...
```

**落库时机**：SSE 流结束（收到 `done` 事件或连接关闭）后，通过 `asyncio.create_task` 异步批量写入 user message + assistant message，不阻塞流式响应。

**session title 生成**：写入 user message 时，若 session.title 为空，取 `message[:50]` 更新 title 并更新 `updated_at`。

---

## 前端改造（ExternalAgentChat.vue）

### 布局变化

```
┌─────────────────────────────────────────────────────┐
│  左侧会话栏 (240px)    │  右侧聊天区                  │
│  ┌──────────────────┐  │  ┌──────────────────────┐  │
│  │ [+ 新建对话]      │  │  │ Agent 名称 / 状态    │  │
│  ├──────────────────┤  │  ├──────────────────────┤  │
│  │ 会话 1  2小时前   │  │  │ 消息列表（含附件预览）│  │
│  │ 会话 2  昨天      │  │  ├──────────────────────┤  │
│  │ 会话 3  3天前     │  │  │ 附件预览卡片区        │  │
│  │ ...               │  │  │ ┌────┐ ┌────┐        │  │
│  │                   │  │  │ │图片│ │文件│ [×]    │  │
│  │                   │  │  │ └────┘ └────┘        │  │
│  │                   │  │  ├──────────────────────┤  │
│  │                   │  │  │ [📎] 输入框  [发送]  │  │
│  └──────────────────┘  │  └──────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

### 会话侧边栏

- 「新建对话」按钮：调 `POST /sessions`，清空聊天区，切换到新 session
- 历史会话列表：显示 title（截断 + 省略号）+ 相对时间
- 点击切换：调 `GET /sessions/{id}/messages` 回显历史消息
- hover 展示删除按钮，点击软删除并从列表移除

### 附件上传

- 输入框工具栏增加回形针图标（`lucide-vue-next` 的 `Paperclip`）
- 点击触发隐藏的 `<input type="file" multiple>`，支持图片和文件
- 选中后**立即上传**（`POST /attachments/upload`），上传中显示加载状态
- 上传成功后追加到 `pendingAttachments` 数组

### 附件预览卡片（输入框上方）

- 图片：100×72px 缩略图 + 文件名（截断）
- 文件：文件类型图标 + 文件名 + 大小（KB）
- 右上角 `×` 移除（从 `pendingAttachments` 删除，不删除已上传的 S3 文件）
- 发送后卡片区清空

### 消息气泡扩展

- 用户气泡：消息文本上方展示附件列表
  - 图片：缩略图，点击放大（lightbox）
  - 文件：图标 + 文件名，点击下载（跳转 URL）
- Assistant 气泡：渲染为 Markdown，文本中的 URL 自动 linkify 为可点击链接（外部 Agent 返回的文件地址直接可访问）

---

## 关键约束

- 文件大小上限：20MB（与现有 workspace 上传一致）
- 附件上传接口权限：已登录用户（无需 org admin）
- 附件 presigned URL **不存 DB**，由 `GET /sessions/{id}/messages` 返回时实时生成
- 外部 Agent 响应文本中包含的文件 URL 为直接可访问地址，前端 Markdown 渲染时 linkify 即可，无需特殊处理
- 聊天接口 `session_id` 变为必填（前端进入页面时自动创建 session）
- 软删除 session 后，其 messages 不物理删除，仅通过 `deleted_at` 过滤

---

## 不在本次范围内

- 附件管理（批量删除、用量统计）
- 会话搜索 / 关键词过滤
- storage_key 对应 S3 对象的生命周期管理（当前不主动删除）
- NAP / custom 协议专属的 attachments 字段（当前统一用文本 URL）
