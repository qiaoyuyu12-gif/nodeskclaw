# NoDeskClaw Agent Protocol (NAP) v1.0 — 接入规范

> 本文档描述外部 Agent 服务需要实现的接口，供平台（NoDeskClaw）调用。

## 必须实现的接口

| Method | Path | 用途 |
|---|---|---|
| GET | `/health` | 连通性检测 |
| GET | `/meta` | 元数据（sync 时自动拉取） |
| POST | `/stream` | 流式聊天（SSE） |

---

## 1. `GET /health`

**返回（HTTP 200）：**
```json
{
  "status": "ok",
  "timestamp": 1719000000
}
```

`status` 字段必须是 `"ok"`，否则平台判定不可达。

---

## 2. `GET /meta`

平台执行 sync 操作时调用，返回的 `capabilities` 和 `description` 会自动写入数据库展示在卡片上。

**返回（HTTP 200）：**
```json
{
  "protocol_version": "1.0",
  "agent_id": "your-agent-id",
  "name": "Agent 名称",
  "description": "Agent 功能描述",
  "version": "1.0.0",
  "runtime": "langgraph",
  "capabilities": ["代码审查", "SQL生成", "数据分析"]
}
```

| 字段 | 必须 | 说明 |
|---|---|---|
| `capabilities` | 是 | 字符串数组，平台卡片展示用 |
| `description` | 否 | 会覆盖平台侧填写的描述 |

---

## 3. `POST /stream`

### 请求 Header

```
Content-Type: application/json
Authorization: Bearer <api_key>   # 如果平台配置了 api_key
```

### 请求 Body

```json
{
  "protocol_version": "1.0",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "session_id": "用于多轮记忆的会话ID",
  "user_id": "发起请求的用户ID",
  "organization_id": "组织ID",
  "messages": [
    {"role": "user", "content": "你好"},
    {"role": "assistant", "content": "你好！"},
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
| `session_id` | 是 | 多轮会话 ID，同一对话保持一致 |
| `user_id` | 是 | 平台用户 ID |
| `organization_id` | 否 | 平台组织 ID |
| `messages` | 是 | 完整对话历史，role 为 `user`/`assistant`/`system`/`tool` |
| `metadata.source` | 否 | 固定为 `"nodeskclaw"` |

### 响应：SSE 流

**Content-Type:** `text/event-stream`

```
event: message
data: 这是回复的第一段文本

event: message
data: 这是第二段文本

event: done
data: complete
```

#### 事件类型

| 事件 | data 格式 | 必须 | 说明 |
|---|---|---|---|
| `thinking` | 纯文本字符串 | 否 | 推理/思考过程文本片段，平台折叠展示；必须在所有 `message` 事件之前发送 |
| `message` | 纯文本字符串 | 是 | 回复文本片段，平台逐块拼接展示 |
| `done` | 任意（如 `complete`） | 是 | 结束信号，必须发送 |
| `error` | `{"code": "ERROR_CODE", "message": "错误描述"}` | — | 错误时发送，平台展示 message |

**注意：`thinking` 和 `message` 事件的 data 均为纯文本，不是 JSON。**

#### 完整示例（含推理链路）

```
event: thinking
data: 用户询问库存问题，需要先查询 ERP 数据...

event: thinking
data: 已获取数据，发现 3 项物料库存不足。

event: message
data: 根据您的数据，

event: message
data: 我发现以下问题：

event: message
data: 库存不足的物料有 3 项。

event: done
data: complete
```

#### 无推理链路的最简示例

event: message
data: 我发现以下问题：

event: message
data: 库存不足的物料有 3 项。

event: done
data: complete
```

#### 错误示例

```
event: error
data: {"code": "MODEL_TIMEOUT", "message": "LLM 推理超时，请重试"}
```

---

## FastAPI 最小实现示例

```python
import asyncio
import time
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
        "agent_id": "my-agent",
        "name": "我的 Agent",
        "description": "功能描述",
        "version": "1.0.0",
        "capabilities": ["能力1", "能力2"]
    }

@app.post("/stream")
async def stream(payload: dict):
    async def generate():
        messages = payload.get("messages", [])
        # 可选：先发送推理过程（thinking 事件必须早于 message 事件）
        yield "event: thinking\ndata: 正在分析用户问题...\n\n"
        # 在这里调用你的 LLM / 业务逻辑
        reply = "这是来自外部 Agent 的回复"
        for chunk in reply.split("，"):
            yield f"event: message\ndata: {chunk}，\n\n"
            await asyncio.sleep(0.05)
        yield "event: done\ndata: complete\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
```

---

## 平台侧注册流程

1. 在平台填写：Agent 名称、Endpoint（如 `http://your-agent:8000`）、API Key（可选）、协议选 **NAP**
2. 点击「Sync」→ 平台依次调 `/health` → `/meta`，自动同步 capabilities
3. 用户发起聊天 → 平台调 `POST /stream`，SSE 实时展示
