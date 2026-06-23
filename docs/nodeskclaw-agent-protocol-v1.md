# NoDeskClaw Agent Protocol (NAP) v1.0

---

# 1. Document Information

| Item          | Value                     |
| ------------- | ------------------------- |
| Document Name | NoDeskClaw Agent Protocol |
| Protocol Name | NAP                       |
| Version       | v1.0                      |
| Status        | Draft                     |

---

# 2. Background

NoDeskClaw aims to become an enterprise-level AI Agent Operating System.

The platform needs to support multiple agent runtimes:

* Goose
* LangGraph
* CrewAI
* AutoGen
* OpenAI Agent SDK
* Custom FastAPI Agents

Because each runtime uses different:

* Request schema
* Response schema
* Tool calling mechanism
* Streaming mechanism

A unified protocol is required.

---

# 3. Design Goals

## 3.1 Runtime Agnostic

Support all agent runtimes.

---

## 3.2 Multi-turn Conversation

Support:

* Single-turn chat
* Multi-turn conversation
* Session memory

---

## 3.3 Tool Calling

Support:

* Skill
* Tool
* MCP Server
* Workflow Step

---

## 3.4 Streaming

Support:

* HTTP
* SSE
* WebSocket

---

## 3.5 Enterprise Features

Support:

* User Management
* Organization Management
* Permission Control
* Usage Tracking
* Token Statistics
* Audit Logging

---

# 4. Standard APIs

NAP defines four standard APIs.

| Method | Path    | Description      |
| ------ | ------- | ---------------- |
| GET    | /health | Health check     |
| GET    | /meta   | Agent metadata   |
| POST   | /invoke | Sync invoke      |
| POST   | /stream | Streaming invoke |

---

# 5. Health API

## Request

```http
GET /health
```

---

## Response

```json
{
  "status": "ok",
  "timestamp": 1719000000
}
```

---

# 6. Meta API

## Request

```http
GET /meta
```

---

## Response

```json
{
  "protocol_version": "1.0",
  "agent_id": "bom-agent",
  "name": "BOM Analysis Agent",
  "description": "Material analysis and shortage prediction",
  "version": "1.0.0",
  "runtime": "langgraph",
  "model": "qwen3-32b",
  "capabilities": [
    "chat",
    "tool_call",
    "stream"
  ],
  "skills": [
    "inventory_query",
    "bom_query"
  ],
  "mcp_servers": [
    "erp-mcp",
    "mes-mcp"
  ]
}
```

---

# 7. Invoke API

## Request

```http
POST /invoke
Content-Type: application/json
```

---

## Request Schema

```json
{
  "protocol_version": "1.0",
  "request_id": "req-001",
  "session_id": "session-001",
  "user_id": "user-001",
  "organization_id": "org-001",
  "messages": [
    {
      "role": "user",
      "content": "Analyze shortage risk for next two weeks"
    }
  ],
  "context": {
    "conversation_id": "conv-001"
  },
  "tools": [],
  "metadata": {
    "source": "nodeskclaw"
  }
}
```

---

# 8. Request Fields

| Field            | Required | Description           |
| ---------------- | -------- | --------------------- |
| protocol_version | Yes      | Protocol version      |
| request_id       | Yes      | Unique request ID     |
| session_id       | Yes      | Session ID            |
| user_id          | Yes      | User ID               |
| organization_id  | No       | Organization ID       |
| messages         | Yes      | Conversation messages |
| context          | No       | Context               |
| tools            | No       | Available tools       |
| metadata         | No       | Extra info            |

---

# 9. Message Schema

```json
{
  "role": "user",
  "content": "hello"
}
```

Supported roles:

* system
* user
* assistant
* tool

---

# 10. Invoke Response

```json
{
  "success": true,
  "request_id": "req-001",
  "message": {
    "role": "assistant",
    "content": "Three materials are at shortage risk in next two weeks."
  },
  "tool_calls": [
    {
      "tool_name": "inventory_query",
      "status": "success"
    }
  ],
  "usage": {
    "prompt_tokens": 500,
    "completion_tokens": 200,
    "total_tokens": 700
  },
  "metadata": {
    "runtime": "langgraph"
  }
}
```

---

# 11. Tool Call Schema

```json
{
  "tool_calls": [
    {
      "id": "tool-001",
      "tool_name": "query_inventory",
      "input": {
        "material_code": "MAT-001"
      },
      "output": {
        "stock": 100
      },
      "status": "success"
    }
  ]
}
```

---

# 12. Error Schema

```json
{
  "success": false,
  "error": {
    "code": "MODEL_TIMEOUT",
    "message": "LLM request timeout"
  }
}
```

---

## Error Codes

| Code            | Description     |
| --------------- | --------------- |
| INVALID_REQUEST | Invalid request |
| MODEL_TIMEOUT   | Model timeout   |
| TOOL_FAILED     | Tool failed     |
| MCP_FAILED      | MCP failed      |
| INTERNAL_ERROR  | Internal error  |

---

# 13. Stream API

## Request

```http
POST /stream
```

Request body is same as `/invoke`.

---

## Response Type

```text
SSE
```

---

## Event Types

### Message Event

```text
event: message
data: hello
```

---

### Tool Call Event

```text
event: tool_call
data: {...}
```

---

### Done Event

```text
event: done
data: complete
```

---

# 14. Runtime Adapter Layer

Recommended architecture:

```text
NoDeskClaw
    ↓
Runtime Adapter Layer
    ↓
Goose
LangGraph
CrewAI
FastAPI
```

All runtimes must adapt to NAP.

---

# 15. Implementation Requirements

Required APIs:

* /health
* /meta
* /invoke

Optional:

* /stream

---

# 16. FastAPI Example

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
async def health():
    return {
        "status": "ok"
    }

@app.get("/meta")
async def meta():
    return {
        "agent_id": "demo-agent",
        "runtime": "fastapi"
    }

@app.post("/invoke")
async def invoke(payload: dict):
    return {
        "success": True,
        "message": {
            "role": "assistant",
            "content": "Hello from Agent"
        }
    }
```

---

# 17. NoDeskClaw Backend Integration

External agent registration process:

1. Call `/health`
2. Call `/meta`
3. Register metadata
4. Invoke `/invoke`

---

# 18. Versioning

Current version:

```text
NAP v1.0
```

Future versions:

* v2.0
* v3.0

Must maintain backward compatibility.

---

# 19. Final Goal

NAP is one of the core infrastructures of NoDeskClaw.

Based on NAP, NoDeskClaw can support:

* Agent Registry
* Agent Marketplace
* Runtime Adapter
* Workflow Engine
* Enterprise AI Agent Operating System
