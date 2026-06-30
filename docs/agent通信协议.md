# DeskClaw 外部 Agent 接入规范

> 本文档面向外部 Agent 开发者，描述如何将 Agent 服务接入 DeskClaw 平台。

---

## 协议选择

DeskClaw 支持两种接入协议，根据 Agent 架构选择其一：

| 协议 | 适用场景 | 平台调用的核心接口 |
|---|---|---|
| **NAP**（NoDeskClaw Agent Protocol） | Agent 无自带会话管理，平台传递完整对话历史 | `POST /stream` |
| **Custom**（自定义协议） | Agent 自带会话管理和历史存储，平台只传最新一条消息 | `POST /chat` |

---

## 通用接口（两种协议均需实现）

### `GET /health` — 连通性检测

平台注册和 Sync 时调用，验证服务可达。

**Response（HTTP 200）：**
```json
{
  "status": "ok",
  "timestamp": 1719000000
}
```

`status` 必须为 `"ok"`，否则平台标记为不可达。

---

### `GET /meta` — Agent 元数据

平台执行 Sync 时调用，返回的字段会自动同步到平台卡片展示。

**Response（HTTP 200）：**
```json
{
  "protocol_version": "1.0",
  "agent_id": "your-agent-id",
  "name": "Agent 名称",
  "description": "Agent 功能描述",
  "version": "1.0.0",
  "capabilities": ["代码审查", "数据分析", "知识问答"]
}
```

| 字段 | 必须 | 说明 |
|---|---|---|
| `capabilities` | 是 | 能力标签数组，展示在平台卡片上 |
| `description` | 否 | 覆盖平台侧填写的描述 |

---

## 协议一：NAP（NoDeskClaw Agent Protocol）

**特点**：平台管理会话历史，每次请求携带完整对话记录。Agent 无需自行存储历史。

### `POST /stream` — 流式聊天

**Request Header：**
```
Content-Type: application/json
Authorization: Bearer <api_key>   # 平台配置了 api_key 时携带
```

**Request Body：**
```json
{
  "protocol_version": "1.0",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "session_id": "用于多轮记忆的会话ID",
  "user_id": "发起请求的用户ID",
  "organization_id": "组织ID",
  "messages": [
    {"role": "user", "content": "你好"},
    {"role": "assistant", "content": "你好！有什么可以帮你？"},
    {"role": "user", "content": "帮我分析这份数据"}
  ],
  "metadata": {
    "source": "nodeskclaw"
  }
}
```

| 字段 | 必须 | 说明 |
|---|---|---|
| `protocol_version` | 是 | 固定 `"1.0"` |
| `request_id` | 是 | 本次请求唯一 UUID |
| `session_id` | 是 | 多轮会话 ID |
| `user_id` | 是 | 平台用户 ID |
| `organization_id` | 否 | 平台组织 ID |
| `messages` | 是 | 完整对话历史，role 为 `user`/`assistant` |
| `metadata.source` | 否 | 固定为 `"nodeskclaw"` |

**Response：SSE 流（`Content-Type: text/event-stream`）**

| 事件 | data 格式 | 必须 | 说明 |
|---|---|---|---|
| `thinking` | 纯文本 | 否 | 推理过程片段，平台折叠展示；须在所有 `message` 前发送 |
| `message` | 纯文本 | 是 | 回复文本片段，平台逐块追加展示 |
| `done` | 任意（如 `complete`） | 是 | 结束信号 |
| `error` | `{"code": "...", "message": "..."}` | — | 出错时发送 |

**完整示例（含推理链路）：**
```
event: thinking
data: 用户询问库存问题，需要先查询 ERP 数据...

event: thinking
data: 已获取数据，发现 3 项物料库存不足。

event: message
data: 根据您的数据，库存不足的物料有 3 项。

event: done
data: complete
```

**最简示例：**
```
event: message
data: 好的，我来帮你分析。

event: done
data: complete
```

**错误示例：**
```
event: error
data: {"code": "MODEL_TIMEOUT", "message": "LLM 推理超时，请重试"}
```

**FastAPI 最小实现：**
```python
import asyncio, time, uuid
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI()

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": int(time.time())}

@app.get("/meta")
async def meta():
    return {
        "protocol_version": "1.0",
        "agent_id": "my-nap-agent",
        "name": "我的 Agent",
        "description": "功能描述",
        "version": "1.0.0",
        "capabilities": ["能力1", "能力2"]
    }

@app.post("/stream")
async def stream(payload: dict):
    async def generate():
        # 可选：先输出推理过程
        yield "event: thinking\ndata: 正在分析问题...\n\n"
        # 调用 LLM，流式输出回复
        reply = "这是 Agent 的回复内容"
        for chunk in reply:
            yield f"event: message\ndata: {chunk}\n\n"
            await asyncio.sleep(0.02)
        yield "event: done\ndata: complete\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
```

---

## 协议二：Custom（自定义协议）

**特点**：Agent 自带会话管理和历史存储。平台只传最新一条用户消息 + session_id，历史记忆由 Agent 内部维护。支持技能（Skill）调用和执行状态推送。

### `POST /chat` — 流式聊天（核心接口）

**Request Header：**
```
Content-Type: application/json
Authorization: Bearer <api_key>   # 平台配置了 api_key 时携带
```

**Request Body：**
```json
{
  "session_id": "用于多轮记忆的会话UUID",
  "user_id": "发起请求的用户ID",
  "message": "用户输入的消息文本",
  "skill": "skill名称 或 null",
  "thinking": true
}
```

| 字段 | 必须 | 说明 |
|---|---|---|
| `session_id` | 是 | 多轮会话 ID，同一对话保持一致 |
| `user_id` | 是 | 平台用户 ID |
| `message` | 是 | 用户本次输入的消息 |
| `skill` | 否 | 指定使用某个 Skill；不指定传 `null` |
| `thinking` | 否 | `true` 时 Agent 输出推理过程（`event: thought`） |

**Response：SSE 流（`Content-Type: text/event-stream`）**

| 事件 | data 格式 | 说明 |
|---|---|---|
| `thought` | 纯文本 | 推理/思考过程片段（`thinking: true` 时产生），平台折叠展示 |
| `answer` | 纯文本 | 回答文本片段，平台逐块追加展示 |
| `status` | `{"stage": "...", "label": "...", "ok": true}` | 执行步骤状态（工具调用、检索等），平台目前忽略 |
| `done` | 任意 | 结束信号 |
| `error` | `{"error": "错误描述"}` | 出错时发送 |

**完整示例（含推理链路和执行状态）：**
```
event: thought
data: 用户询问 BOM 缺料情况，需要调用 ERP 查询接口。

event: thought
data: 查询到 A001、B002、C003 三项物料库存不足。

event: status
data: {"stage": "tool_call", "label": "查询 ERP 库存", "ok": true}

event: answer
data: 根据当前库存数据，

event: answer
data: 以下 3 项物料存在缺料风险：A001、B002、C003。

event: done
data: complete
```

**无推理链路的最简示例：**
```
event: answer
data: 好的，我来帮你。

event: done
data: complete
```

**FastAPI 最小实现：**
```python
import asyncio, time
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI()

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": int(time.time())}

@app.get("/meta")
async def meta():
    return {
        "protocol_version": "1.0",
        "agent_id": "my-custom-agent",
        "name": "我的 Agent",
        "description": "功能描述",
        "version": "1.0.0",
        "capabilities": ["能力1", "能力2"]
    }

@app.post("/chat")
async def chat(payload: dict):
    session_id = payload.get("session_id")
    user_id = payload.get("user_id")
    message = payload.get("message", "")
    thinking = payload.get("thinking", False)

    async def generate():
        if thinking:
            yield "event: thought\ndata: 正在分析问题...\n\n"
        # 调用 LLM，流式输出回答
        reply = "这是 Agent 的回答内容"
        for chunk in reply:
            yield f"event: answer\ndata: {chunk}\n\n"
            await asyncio.sleep(0.02)
        yield "event: done\ndata: complete\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
```

---

### 可选接口（Custom 协议推荐实现）

平台目前不调用这些接口，但 Agent 自身聊天 UI 需要它们。未来平台可能接入。

#### `GET /history/sessions` — 会话列表

```
GET /history/sessions?user_id=<uuid>&limit=20&offset=0
```

**Response：**
```json
[
  {
    "session_id": "uuid",
    "title": "对话标题",
    "updated_at": "2026-06-30T10:00:00Z",
    "message_count": 12
  }
]
```

#### `GET /history/sessions/{session_id}/messages` — 会话历史消息

```
GET /history/sessions/{session_id}/messages?user_id=<uuid>
```

**Response：**
```json
[
  {"role": "user", "content": "你好"},
  {"role": "assistant", "content": "你好！有什么可以帮你？", "thinking": "思考过程..."}
]
```

#### `DELETE /history/sessions/{session_id}` — 删除会话

```
DELETE /history/sessions/{session_id}?user_id=<uuid>
```

#### `GET /skills` — Skill 列表

```
GET /skills
```

**Response：**
```json
[
  {"name": "skill名称", "description": "Skill 功能描述"}
]
```

#### `POST /skills/upload` — 上传 Skill 文件

```
POST /skills/upload
Content-Type: multipart/form-data
字段名: file（接受 .md 文件）
```

---

## 平台注册流程

1. **填写信息**：Agent 名称、Endpoint（如 `http://your-agent:8300`）、API Key（可选）、协议选 **NAP** 或 **Custom**
2. **点击 Sync**：平台依次调 `GET /health` → `GET /meta`，自动同步 capabilities 和 description
3. **发起对话**：
   - NAP 协议 → 平台调 `POST /stream`，携带完整对话历史
   - Custom 协议 → 平台调 `POST /chat`，携带 `session_id + user_id + message + thinking: true`

---

## 选择建议

| 情况 | 推荐协议 |
|---|---|
| Agent 基于 LangGraph / LlamaIndex / 自研框架，无内置会话存储 | **NAP** |
| Agent 自带数据库存历史、有 Skill 系统、有自己的聊天 UI | **Custom** |
| Agent 基于 OpenAI / Azure OpenAI API 直接封装 | **NAP** 或 `openai_compatible` |
