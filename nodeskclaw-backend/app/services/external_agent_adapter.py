"""external_agent_adapter.py：与外部 Agent 服务通信的 HTTP 适配器。

支持协议：
  - openai_compatible：标准 OpenAI Chat Completions API（POST /v1/chat/completions）
  - custom：mom_agent 兼容格式（POST /chat，SSE 命名事件）
  - nap：NoDeskClaw Agent Protocol v1.0（POST /stream，SSE 命名事件）
"""

import json
import logging
import subprocess
import uuid
from collections.abc import AsyncIterator
from urllib.parse import urlparse, urlunparse

import httpx

logger = logging.getLogger(__name__)

# 连接验证超时（秒）
_VERIFY_TIMEOUT = 10.0
# 聊天流式超时：connect 10s，总 120s（等待 LLM 推理）
_CHAT_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=5.0)


def _get_wsl_host_ip() -> str | None:
    """获取 WSL 宿主机（Windows）的可路由 IP 地址。

    优先从默认路由网关获取：`ip route show default` → 第三字段（via <IP>）。
    这是 WSL2 NAT 网络下 Windows 宿主机的实际地址（通常 172.x.x.1）。
    /etc/resolv.conf nameserver 是 DNS 虚拟 IP，不能用于建立 TCP 连接，仅作备用。
    """
    # 方法1：从默认路由网关获取（最可靠）
    try:
        result = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True, text=True, timeout=2,
        )
        for line in result.stdout.splitlines():
            parts = line.split()
            # 格式：default via <gateway_ip> dev eth0 ...
            if len(parts) >= 3 and parts[0] == "default" and parts[1] == "via":
                return parts[2]
    except Exception:
        pass

    # 方法2：回退到 /etc/resolv.conf nameserver（旧版 WSL 或 mirrored 模式）
    try:
        with open("/etc/resolv.conf") as f:
            for line in f:
                if line.startswith("nameserver"):
                    ip = line.split()[1].strip()
                    # 过滤掉 WSL2 DNS stub（10.255.255.254）
                    if ip != "10.255.255.254":
                        return ip
    except OSError:
        pass

    return None


def _resolve_wsl_endpoint(endpoint: str) -> str:
    """WSL 环境下将 127.0.0.1/localhost 映射到 Windows 宿主机 IP。

    WSL2 NAT 模式下，127.0.0.1 是 WSL loopback，无法访问 Windows 服务。
    宿主机 IP 通过默认路由网关获取（`ip route show default`）。
    """
    # 检测是否在 WSL 环境中运行
    try:
        with open("/proc/sys/kernel/osrelease") as f:
            osrelease = f.read().lower()
    except OSError:
        return endpoint

    if "microsoft" not in osrelease and "wsl" not in osrelease:
        return endpoint

    parsed = urlparse(endpoint)
    if parsed.hostname not in ("127.0.0.1", "localhost"):
        return endpoint

    host_ip = _get_wsl_host_ip()
    if not host_ip:
        return endpoint

    port = f":{parsed.port}" if parsed.port else ""
    new_netloc = f"{host_ip}{port}"
    resolved = urlunparse(parsed._replace(netloc=new_netloc))
    logger.info("WSL 环境：将 %s 重映射为 %s", endpoint, resolved)
    return resolved


async def verify_connection(endpoint: str, api_key: str | None, protocol: str) -> bool:
    """验证外部 Agent 服务是否可达。

    openai_compatible：调用 GET /v1/models，不要求 200（401 也算可达，说明服务在线）
    custom：调用 GET {endpoint}/health，期望 200
    nap：调用 GET {endpoint}/health，期望响应体 {"status": "ok"}
    """
    # WSL 环境下自动将 127.0.0.1/localhost 映射到 Windows 宿主机 IP
    endpoint = _resolve_wsl_endpoint(endpoint)
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        # trust_env=False：不走系统代理（HTTP_PROXY 等），直连 Agent 服务
        async with httpx.AsyncClient(timeout=_VERIFY_TIMEOUT, trust_env=False) as client:
            if protocol == "openai_compatible":
                # /v1/models 可能返回 200（无鉴权）或 401（有鉴权），均视为服务可达
                resp = await client.get(
                    f"{endpoint}/v1/models",
                    headers=headers,
                )
                return resp.status_code in (200, 401, 403)
            elif protocol == "nap":
                # NAP 要求 /health 返回 {"status": "ok"}
                resp = await client.get(f"{endpoint}/health", headers=headers)
                if resp.status_code != 200:
                    return False
                try:
                    return resp.json().get("status") == "ok"
                except Exception:
                    return False
            else:
                resp = await client.get(
                    f"{endpoint}/health",
                    headers=headers,
                )
                return resp.status_code == 200
    except Exception:
        logger.warning("External agent connection check failed: %s", endpoint, exc_info=True)
        return False


async def fetch_meta(endpoint: str, api_key: str | None) -> dict:
    """调用 NAP GET /meta，返回 Agent 元数据。

    用于 sync 端点自动同步 capabilities / description 等字段。
    """
    # WSL 环境下自动将 127.0.0.1/localhost 映射到 Windows 宿主机 IP
    endpoint = _resolve_wsl_endpoint(endpoint)
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # trust_env=False：不走系统代理，直连 Agent 服务
    async with httpx.AsyncClient(timeout=_VERIFY_TIMEOUT, trust_env=False) as client:
        resp = await client.get(f"{endpoint}/meta", headers=headers)
        resp.raise_for_status()
        return resp.json()


async def chat_stream(
    endpoint: str,
    api_key: str | None,
    protocol: str,
    messages: list[dict],
    session_id: str | None = None,
    user_id: str | None = None,
    organization_id: str | None = None,
) -> AsyncIterator[str]:
    """向外部 Agent 发起流式聊天，逐块 yield 文本内容。

    openai_compatible：POST /v1/chat/completions，stream=True
    custom：POST {endpoint}/chat，兼容 mom_agent 命名 SSE 事件格式
      请求：{"session_id": "...", "message": "最后一条用户消息"}
      响应：event: answer / event: done / event: error（SSE 命名事件）
    nap：POST {endpoint}/stream，NAP v1.0 标准格式
      请求：完整 NAP Request Schema（protocol_version / request_id / session_id / ...）
      响应：event: message / event: done / event: error（SSE 命名事件）
    """
    # WSL 环境下自动将 127.0.0.1/localhost 映射到 Windows 宿主机 IP
    endpoint = _resolve_wsl_endpoint(endpoint)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    if protocol == "openai_compatible":
        url = f"{endpoint}/v1/chat/completions"
        payload: dict = {"model": "default", "messages": messages, "stream": True}
        # trust_env=False：不走系统代理，直连 Agent 服务
        async with httpx.AsyncClient(timeout=_CHAT_TIMEOUT, trust_env=False) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                resp.raise_for_status()
                async for chunk in _parse_openai_sse(resp):
                    yield chunk

    elif protocol == "nap":
        url = f"{endpoint}/stream"
        payload = {
            "protocol_version": "1.0",
            "request_id": str(uuid.uuid4()),
            "session_id": session_id or str(uuid.uuid4()),
            "user_id": user_id or "anonymous",
            "organization_id": organization_id,
            "messages": messages,
            "metadata": {"source": "nodeskclaw"},
        }
        # trust_env=False：不走系统代理，直连 Agent 服务
        async with httpx.AsyncClient(timeout=_CHAT_TIMEOUT, trust_env=False) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                resp.raise_for_status()
                async for chunk in _parse_nap_sse(resp):
                    yield chunk

    else:
        # custom 协议（mom_agent 格式）
        # 只取最后一条 user 消息发给 agent，session 记忆由 agent 内部维护
        last_user_msg = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"),
            messages[-1]["content"] if messages else "",
        )
        url = f"{endpoint}/chat"
        payload = {
            "session_id": session_id or str(uuid.uuid4()),
            "message": last_user_msg,
        }
        # trust_env=False：不走系统代理，直连 Agent 服务
        async with httpx.AsyncClient(timeout=_CHAT_TIMEOUT, trust_env=False) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                resp.raise_for_status()
                async for chunk in _parse_named_sse(resp):
                    yield chunk


async def _parse_openai_sse(resp: httpx.Response) -> AsyncIterator[str]:
    """解析 OpenAI 兼容 SSE：data: {"choices":[{"delta":{"content":"..."}}]}"""
    async for line in resp.aiter_lines():
        if not line.startswith("data:"):
            continue
        raw = line[len("data:"):].strip()
        if raw == "[DONE]":
            return
        try:
            chunk = json.loads(raw)
            text = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
            if text:
                yield text
        except Exception:
            if raw:
                yield raw


async def _parse_nap_sse(resp: httpx.Response) -> AsyncIterator[str]:
    """解析 NAP v1.0 SSE 命名事件。

    格式：
        event: message
        data: 文本片段

        event: tool_call
        data: {...}   ← 忽略，仅透传 message 事件

        event: done
        data: complete

        event: error
        data: {"code": "...", "message": "..."}
    """
    current_event: str | None = None
    async for line in resp.aiter_lines():
        if not line:
            # 空行 = 事件结束
            current_event = None
            continue

        if line.startswith("event:"):
            current_event = line[len("event:"):].strip()
            continue

        if line.startswith("data:"):
            raw = line[len("data:"):].strip()

            if current_event == "message":
                if raw:
                    yield raw

            elif current_event == "done":
                return

            elif current_event == "error":
                try:
                    err = json.loads(raw)
                    # NAP 错误格式：{"code": "...", "message": "..."}
                    msg = err.get("message") or err.get("error", raw)
                    raise RuntimeError(msg)
                except json.JSONDecodeError:
                    raise RuntimeError(raw)


async def _parse_named_sse(resp: httpx.Response) -> AsyncIterator[str]:
    """解析命名 SSE 事件（mom_agent 格式）。

    格式：
        event: meta
        data: {...}

        event: answer
        data: 文本片段

        event: done
        data: {...}

        event: error
        data: {"error": "..."}
    """
    current_event: str | None = None
    async for line in resp.aiter_lines():
        if not line:
            # 空行 = 事件结束，重置当前事件类型
            current_event = None
            continue

        if line.startswith("event:"):
            current_event = line[len("event:"):].strip()
            continue

        if line.startswith("data:"):
            raw = line[len("data:"):].strip()

            if current_event == "answer":
                # answer 事件的 data 直接是文本片段（非 JSON）
                if raw:
                    yield raw

            elif current_event == "done":
                return

            elif current_event == "error":
                try:
                    err = json.loads(raw)
                    raise RuntimeError(err.get("error", raw))
                except json.JSONDecodeError:
                    raise RuntimeError(raw)

            elif current_event is None:
                # 兜底：无 event 标记时降级为 data-only 解析
                if raw == "[DONE]":
                    return
                try:
                    chunk = json.loads(raw)
                    text = chunk.get("content", "")
                    if text:
                        yield text
                except Exception:
                    if raw:
                        yield raw
