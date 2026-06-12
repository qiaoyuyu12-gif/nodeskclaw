"""NanoBot channel plugin -- integrates with NanoBot's channel system via entry_points."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

logger = logging.getLogger("nodeskclaw_tunnel_bridge.nanobot")

try:
    from nanobot.bus.events import OutboundMessage
    from nanobot.bus.queue import MessageBus
    from nanobot.channels.base import BaseChannel
except ImportError:
    BaseChannel = object  # type: ignore[assignment,misc]
    OutboundMessage = object  # type: ignore[assignment,misc]
    MessageBus = object  # type: ignore[assignment,misc]


class NoDeskClawChannel(BaseChannel):  # type: ignore[misc]
    """NanoBot channel that connects to NoDeskClaw tunnel for workspace group chat."""

    name = "nodeskclaw"
    display_name = "NoDeskClaw"

    def __init__(self, config: Any, bus: MessageBus) -> None:
        super().__init__(config, bus)
        self._no_reply_ids: set[str] = set()
        self._tunnel_task: asyncio.Task | None = None
        self._workspace_id: str = ""

    async def start(self) -> None:
        if hasattr(self, "_client") and self._client:
            logger.warning("NoDeskClaw channel: stopping previous tunnel client before restart")
            await self._client.close()

        from .client import TunnelCallbacks, TunnelClient

        callbacks = TunnelCallbacks(
            on_auth_ok=lambda: logger.info("NoDeskClaw channel: tunnel authenticated"),
            on_auth_error=lambda reason: logger.error("NoDeskClaw channel: tunnel auth failed: %s", reason),
            on_close=lambda: logger.warning("NoDeskClaw channel: tunnel connection closed"),
            on_reconnecting=lambda attempt: logger.info("NoDeskClaw channel: tunnel reconnecting (attempt #%d)", attempt),
        )
        self._client = TunnelClient(on_chat_request=self._handle_chat_request, callbacks=callbacks)
        self._running = True
        logger.info("NoDeskClaw channel starting tunnel client...")
        await self._client.run_forever()

    async def stop(self) -> None:
        self._running = False
        if hasattr(self, "_client"):
            await self._client.close()

    async def send(self, msg: OutboundMessage) -> None:
        """Fallback: called by NanoBot when a non-streaming response is ready.

        正常路径已由 _handle_chat_request 直接流式调用本地 gateway 完成，
        此方法仅作保底——若 gateway 调用失败回退到 NanoBot 消息总线时触发。
        """
        chat_id = getattr(msg, "chat_id", "")

        if chat_id in self._no_reply_ids:
            self._no_reply_ids.discard(chat_id)
            return

        # 仅在 _handle_chat_request 未处理该请求时（回退场景）才通过此路径发送
        req_info = self._pending_fallback_requests.pop(chat_id, None)
        if not req_info:
            return

        reply_to, trace_id = req_info
        content = getattr(msg, "content", "") or ""

        if content:
            await self._client.send_response_chunk(reply_to, trace_id, content)
        await self._client.send_response_done(reply_to, trace_id)

    async def send_collaboration(self, target: str, text: str) -> None:
        await self._client.send_collaboration(
            self._workspace_id, self._client.instance_id, target, text,
        )

    async def list_peers(self) -> list[dict]:
        return await self._client.list_peers(self._workspace_id)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

    # 回退用：仅当 gateway 流式调用失败时使用 NanoBot 消息总线
    @property
    def _pending_fallback_requests(self) -> dict[str, tuple[str, str]]:
        if not hasattr(self, "_pending_fb"):
            self._pending_fb: dict[str, tuple[str, str]] = {}
        return self._pending_fb

    async def _handle_chat_request(
        self,
        request_id: str,
        trace_id: str,
        messages: list[dict[str, Any]],
        workspace_id: str,
        no_reply: bool,
    ) -> None:
        if workspace_id:
            self._workspace_id = workspace_id

        gateway_port = int(os.environ.get("OPENCLAW_GATEWAY_PORT", "3000"))
        gateway_url = f"http://localhost:{gateway_port}/v1/chat/completions"
        token = self._client._token
        model = os.environ.get("OPENCLAW_DEFAULT_MODEL", "openclaw/main")
        session_key = f"workspace:{workspace_id}" if workspace_id else None

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
        if session_key:
            headers["X-OpenClaw-Session-Key"] = session_key

        if no_reply:
            # 上下文注入：用极小 token 数触发，不等待响应
            self._no_reply_ids.add(request_id)
            asyncio.create_task(self._inject_context_no_reply(
                gateway_url, headers, model, messages, request_id, trace_id,
            ))
            return

        # 直接流式调用本地 gateway，逐 token 转发 chunk
        streamed = await self._stream_from_gateway(
            gateway_url, headers, model, messages, request_id, trace_id,
        )

        if not streamed:
            # gateway 不可达或失败 → 回退到 NanoBot 消息总线
            logger.warning(
                "NoDeskClaw channel: gateway streaming failed for %s, falling back to NanoBot bus",
                request_id,
            )
            user_content = _extract_full_content(messages)
            session_key_nb = f"nodeskclaw:{workspace_id}" if workspace_id else None
            self._pending_fallback_requests[request_id] = (request_id, trace_id)
            await self._handle_message(
                sender_id="workspace_user",
                chat_id=request_id,
                content=user_content,
                session_key=session_key_nb,
            )

    async def _stream_from_gateway(
        self,
        url: str,
        headers: dict[str, str],
        model: str,
        messages: list[dict[str, Any]],
        request_id: str,
        trace_id: str,
    ) -> bool:
        """调用本地 gateway 流式接口，逐 token 发送 chunk。返回 True 表示成功完成。"""
        try:
            import httpx
        except ImportError:
            logger.warning("NoDeskClaw channel: httpx not installed, cannot stream from gateway")
            return False

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5, read=600, write=10, pool=10)) as client:
                async with client.stream(
                    "POST",
                    url,
                    json={"model": model, "messages": messages, "stream": True},
                    headers=headers,
                ) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        logger.warning(
                            "NoDeskClaw channel: gateway returned %d: %s",
                            resp.status_code, body[:200],
                        )
                        return False

                    has_content = False
                    data_accum = ""

                    async for line in resp.aiter_lines():
                        if line.startswith("data: "):
                            part = line[6:]
                            data_accum = (data_accum + "\n" + part) if data_accum else part
                            continue
                        if line.strip() == "" and data_accum:
                            if data_accum.strip() == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data_accum)
                                content: str = (
                                    chunk.get("choices", [{}])[0]
                                    .get("delta", {})
                                    .get("content", "")
                                )
                                if content:
                                    has_content = True
                                    await self._client.send_response_chunk(request_id, trace_id, content)
                            except (json.JSONDecodeError, IndexError, KeyError) as e:
                                logger.debug("NoDeskClaw channel: SSE parse error: %s", e)
                            data_accum = ""

                    if has_content:
                        await self._client.send_response_done(request_id, trace_id)
                    else:
                        await self._client.send_response_error(request_id, trace_id, "empty_response")
                    return True

        except Exception as exc:
            logger.error("NoDeskClaw channel: gateway stream error for %s: %s", request_id, exc)
            return False

    async def _inject_context_no_reply(
        self,
        url: str,
        headers: dict[str, str],
        model: str,
        messages: list[dict[str, Any]],
        request_id: str,
        trace_id: str,
    ) -> None:
        """no_reply 模式：发送极小 max_tokens 请求注入上下文，不流式输出。"""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                await client.post(
                    url,
                    json={"model": model, "messages": messages, "stream": False, "max_tokens": 1},
                    headers=headers,
                )
        except Exception as exc:
            logger.debug("NoDeskClaw channel: no_reply context injection failed: %s", exc)
        finally:
            await self._client.send_response_done(request_id, trace_id)


def _extract_full_content(messages: list[dict[str, Any]]) -> str:
    """Concatenate all message contents so system prompt reaches NanoBot."""
    return "\n\n".join(
        msg.get("content", "") for msg in messages if msg.get("content")
    )
