"""external_agent_adapter.py：与外部 Agent 服务通信的 HTTP 适配器。

支持协议：
  - openai_compatible：标准 OpenAI Chat Completions API（POST /v1/chat/completions）
  - custom：自定义协议（POST {endpoint}/chat，GET {endpoint}/health）
"""

import logging
from collections.abc import AsyncIterator

import httpx

logger = logging.getLogger(__name__)

# 连接验证超时（秒）
_VERIFY_TIMEOUT = 10.0
# 聊天流式超时：connect 10s，总 120s（等待 LLM 推理）
_CHAT_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=5.0)


async def verify_connection(endpoint: str, api_key: str | None, protocol: str) -> bool:
    """验证外部 Agent 服务是否可达。

    openai_compatible：调用 GET /v1/models，不要求 200（401 也算可达，说明服务在线）
    custom：调用 GET {endpoint}/health，期望 200
    """
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=_VERIFY_TIMEOUT) as client:
            if protocol == "openai_compatible":
                # /v1/models 可能返回 200（无鉴权）或 401（有鉴权），均视为服务可达
                resp = await client.get(
                    f"{endpoint}/v1/models",
                    headers=headers,
                )
                return resp.status_code in (200, 401, 403)
            else:
                resp = await client.get(
                    f"{endpoint}/health",
                    headers=headers,
                )
                return resp.status_code == 200
    except Exception:
        logger.debug("External agent connection check failed: %s", endpoint, exc_info=True)
        return False


async def chat_stream(
    endpoint: str,
    api_key: str | None,
    protocol: str,
    messages: list[dict],
) -> AsyncIterator[str]:
    """向外部 Agent 发起流式聊天，逐块 yield 文本内容。

    openai_compatible：POST /v1/chat/completions，stream=True
    custom：POST {endpoint}/chat，期望纯文本流或 data: 行格式
    """
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    if protocol == "openai_compatible":
        url = f"{endpoint}/v1/chat/completions"
        payload = {"model": "default", "messages": messages, "stream": True}
    else:
        url = f"{endpoint}/chat"
        payload = {"messages": messages, "stream": True}

    async with httpx.AsyncClient(timeout=_CHAT_TIMEOUT) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                # SSE 格式：data: {...}
                if line.startswith("data:"):
                    raw = line[len("data:"):].strip()
                    if raw == "[DONE]":
                        return
                    try:
                        import json
                        chunk = json.loads(raw)
                        if protocol == "openai_compatible":
                            # OpenAI delta 格式
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            text = delta.get("content", "")
                        else:
                            text = chunk.get("content", "")
                        if text:
                            yield text
                    except Exception:
                        # 非 JSON 行直接当文本输出
                        yield raw
                else:
                    # custom 协议可能直接输出文本行
                    if protocol == "custom" and line:
                        yield line
