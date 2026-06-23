"""TransportMiddleware — delivers messages according to the DeliveryPlan via TransportAdapters."""

from __future__ import annotations

import asyncio
import logging
import time

from app.services.runtime.messaging.pipeline import MessageMiddleware, NextFn, PipelineContext
from app.services.runtime.transport.base import DeliveryResult

logger = logging.getLogger(__name__)

MAX_RETRY = 3

# 同一节点离线告警的最小间隔（秒）。防止 circuit half_open 每 30s 循环探活
# 都向前端推送 agent:error 事件，导致聊天气泡持续堆积。
_OFFLINE_BROADCAST_COOLDOWN_S = 300  # 5 分钟
_last_offline_broadcast: dict[str, float] = {}  # key: "workspace_id:node_id"


class TransportMiddleware(MessageMiddleware):
    async def process(self, ctx: PipelineContext, next_fn: NextFn) -> None:
        plan = ctx.delivery_plan
        if plan is None:
            logger.warning("TransportMiddleware: no delivery plan, skipping transport")
            await next_fn(ctx)
            return

        resolved = plan.resolved_targets
        if not resolved:
            logger.info(
                "TransportMiddleware: no resolved targets for envelope %s (mode=%s)",
                ctx.envelope.id, plan.mode,
            )
            await next_fn(ctx)
            return

        logger.debug(
            "TransportMiddleware: delivering envelope %s to %d targets (mode=%s)",
            ctx.envelope.id, len(resolved), plan.mode,
        )

        from app.services.runtime.registries.transport_registry import TRANSPORT_REGISTRY

        tasks = []
        for target in resolved:
            transport_id = target.transport or "agent"
            spec = TRANSPORT_REGISTRY.get(transport_id)
            if spec is None or spec.adapter is None:
                logger.warning(
                    "TransportMiddleware: no adapter for transport '%s', skipping target %s",
                    transport_id, target.node_id,
                )
                ctx.delivery_results.append(DeliveryResult(
                    success=False, target_node_id=target.node_id,
                    transport=transport_id, error="transport_not_found",
                ))
                continue

            tasks.append(self._deliver_one(
                spec.adapter, ctx, target.node_id, transport_id,
            ))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    logger.error("TransportMiddleware: delivery exception: %s", r)
                    ctx.delivery_results.append(DeliveryResult(
                        success=False, target_node_id="unknown",
                        error=str(r),
                    ))
                elif isinstance(r, DeliveryResult):
                    ctx.delivery_results.append(r)

        sender_id = ctx.envelope.data.sender.id if ctx.envelope.data and ctx.envelope.data.sender else ""
        if ctx.db:
            from app.services.runtime.messaging.middlewares.circuit_breaker import (
                record_failure,
                record_success,
            )
            from app.services.runtime.telemetry import record_edge_latency, record_edge_message
            for r in ctx.delivery_results:
                try:
                    if r.success:
                        await record_success(ctx.db, r.target_node_id, ctx.workspace_id)
                    else:
                        await record_failure(ctx.db, r.target_node_id, ctx.workspace_id)
                except Exception as e:
                    logger.warning("Failed to update circuit state for %s: %s", r.target_node_id, e)

                record_edge_message(sender_id, r.target_node_id, ctx.workspace_id)
                if r.latency_ms:
                    record_edge_latency(r.latency_ms / 1000, sender_id, r.target_node_id, ctx.workspace_id)
            await ctx.db.flush()

        failed = [r for r in ctx.delivery_results if not r.success]
        if failed and ctx.delivery_plan and ctx.delivery_plan.topology_version > 0:
            from app.services.runtime.route_cache import route_table
            if route_table.is_stale(ctx.workspace_id, ctx.delivery_plan.topology_version):
                logger.info(
                    "Topology changed since plan v%d, marking failures for re-route",
                    ctx.delivery_plan.topology_version,
                )
                ctx.extra["topology_stale"] = True

        if failed:
            await self._handle_failures(ctx, failed)

        ctx.extra["delivered"] = True
        await next_fn(ctx)

    async def _deliver_one(
        self, adapter, ctx: PipelineContext, target_node_id: str, transport_id: str,
    ) -> DeliveryResult:
        from app.services.runtime.messaging.envelope import Priority
        from app.services.runtime.messaging.middlewares.rate_limit import check_receiver_rate

        priority = ctx.envelope.data.priority if ctx.envelope.data else Priority.NORMAL
        allowed, action = check_receiver_rate(target_node_id, priority=priority)

        if not allowed:
            if action == "drop":
                logger.info("Receiver rate drop for background msg -> %s", target_node_id)
                return DeliveryResult(
                    success=False, target_node_id=target_node_id,
                    transport=transport_id, error="receiver_rate_dropped",
                )
            logger.warning("Receiver rate limit exceeded for %s (action=%s)", target_node_id, action)
            return DeliveryResult(
                success=False, target_node_id=target_node_id,
                transport=transport_id, error="receiver_rate_limited",
            )

        if action == "alert":
            logger.warning("Critical msg exceeded receiver rate for %s, delivering with alert", target_node_id)

        try:
            return await adapter.deliver(
                ctx.envelope,
                target_node_id,
                workspace_id=ctx.workspace_id,
                db=ctx.db,
            )
        except TypeError:
            return await adapter.deliver(
                ctx.envelope,
                target_node_id,
                workspace_id=ctx.workspace_id,
            )

    async def _handle_failures(
        self, ctx: PipelineContext, failed: list[DeliveryResult],
    ) -> None:
        """Enqueue failed deliveries for retry or move to DLQ."""
        db = ctx.db
        if db is None:
            return

        from app.services.runtime.messaging.queue import NO_RETRY_ERRORS

        retried_targets: list[str] = ctx.extra.setdefault("retried_targets", [])
        dead_lettered_targets: list[str] = ctx.extra.setdefault("dead_lettered_targets", [])

        for result in failed:
            if result.error in NO_RETRY_ERRORS:
                try:
                    from app.models.dead_letter import DeadLetter

                    dl = DeadLetter(
                        message_id=ctx.envelope.id,
                        target_node_id=result.target_node_id,
                        workspace_id=ctx.workspace_id,
                        envelope=ctx.envelope.to_dict(),
                        last_error=result.error or "",
                        attempt_count=0,
                        recoverable=False,
                    )
                    db.add(dl)
                    await db.flush()
                    dead_lettered_targets.append(result.target_node_id)
                    logger.warning(
                        "Non-retriable error '%s', moved to DLQ: %s -> %s",
                        result.error, ctx.envelope.id, result.target_node_id,
                    )
                except Exception as e:
                    logger.error("Failed to write dead letter: %s", e)

                if result.error == "instance_not_connected_locally":
                    await self._broadcast_offline_error(db, ctx.workspace_id, result)
                continue

            retry_count = ctx.extra.get(f"retry:{result.target_node_id}", 0)
            if retry_count < MAX_RETRY:
                try:
                    from app.services.runtime.messaging.envelope import Priority
                    from app.services.runtime.messaging.queue import enqueue

                    priority = ctx.envelope.data.priority if ctx.envelope.data else Priority.NORMAL
                    await enqueue(
                        db,
                        target_node_id=result.target_node_id,
                        workspace_id=ctx.workspace_id,
                        priority=priority,
                        envelope=ctx.envelope.to_dict(),
                    )
                    retried_targets.append(result.target_node_id)
                    logger.info(
                        "Enqueued retry %d for %s -> %s",
                        retry_count + 1, ctx.envelope.id, result.target_node_id,
                    )
                except Exception as e:
                    logger.error("Failed to enqueue retry: %s", e)
            else:
                try:
                    from app.models.dead_letter import DeadLetter

                    dl = DeadLetter(
                        message_id=ctx.envelope.id,
                        target_node_id=result.target_node_id,
                        workspace_id=ctx.workspace_id,
                        envelope=ctx.envelope.to_dict(),
                        last_error=result.error or "",
                        attempt_count=retry_count,
                        recoverable=True,
                    )
                    db.add(dl)
                    await db.flush()
                    dead_lettered_targets.append(result.target_node_id)
                    logger.warning(
                        "Moved to DLQ: %s -> %s after %d retries",
                        ctx.envelope.id, result.target_node_id, retry_count,
                    )
                except Exception as e:
                    logger.error("Failed to write dead letter: %s", e)

    async def _broadcast_offline_error(
        self, db, workspace_id: str, result: DeliveryResult,
    ) -> None:
        # 冷却期内不重复广播，避免 circuit half_open 每 30s 探活失败时向前端疯狂推错误气泡
        # 注意：不能用 get(key, 0.0) 作为"从未广播"的默认值——CI 容器刚启动时
        # time.monotonic() 本身可能 < 300s，导致 now - 0.0 < 300 误判为冷却期内。
        key = f"{workspace_id}:{result.target_node_id}"
        now = time.monotonic()
        if key in _last_offline_broadcast and now - _last_offline_broadcast[key] < _OFFLINE_BROADCAST_COOLDOWN_S:
            return
        _last_offline_broadcast[key] = now

        try:
            from sqlalchemy import select

            from app.models.base import not_deleted
            from app.models.node_card import NodeCard

            stmt = select(NodeCard).where(
                NodeCard.node_id == result.target_node_id,
                NodeCard.workspace_id == workspace_id,
                not_deleted(NodeCard),
            )
            card = (await db.execute(stmt)).scalar_one_or_none()
            agent_name = card.name if card else result.target_node_id

            from app.api.workspaces import broadcast_event

            broadcast_event(workspace_id, "agent:error", {
                "instance_id": result.target_node_id,
                "agent_name": agent_name,
                "error": "instance_not_connected_locally",
                "error_detail": None,
            })
        except Exception as e:
            logger.error("Failed to broadcast offline error for %s: %s", result.target_node_id, e)
