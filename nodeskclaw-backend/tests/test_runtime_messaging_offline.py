"""Tests for offline agent delivery failure handling.

Covers:
- NO_RETRY_ERRORS membership
- TransportMiddleware._handle_failures skipping enqueue for non-retriable errors
- agent:error SSE broadcast for offline agents
- Normal transient errors still enqueued for retry
- failure_recovery health log ordering
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.runtime.messaging.envelope import (
    MessageData,
    MessageEnvelope,
    MessageSender,
    SenderType,
)
from app.services.runtime.messaging.middlewares.transport import (
    TransportMiddleware,
)
from app.services.runtime.messaging.pipeline import PipelineContext
from app.services.runtime.messaging.queue import NO_RETRY_ERRORS
from app.services.runtime.transport.base import DeliveryResult


def _make_ctx(workspace_id: str = "ws-1", db=None) -> PipelineContext:
    envelope = MessageEnvelope(
        id="msg-001",
        data=MessageData(
            sender=MessageSender(id="user-1", type=SenderType.USER, name="Alice"),
        ),
    )
    return PipelineContext(
        envelope=envelope,
        workspace_id=workspace_id,
        db=db,
    )


class TestNoRetryErrors:
    def test_instance_not_connected_locally_in_no_retry(self):
        assert "instance_not_connected_locally" in NO_RETRY_ERRORS

    def test_existing_errors_preserved(self):
        assert "node_card_not_found" in NO_RETRY_ERRORS
        assert "instance_not_found" in NO_RETRY_ERRORS
        assert "workspace_isolation_violation" in NO_RETRY_ERRORS

    def test_transient_errors_not_in_set(self):
        assert "some_transient_network_error" not in NO_RETRY_ERRORS
        assert "" not in NO_RETRY_ERRORS


class TestHandleFailuresNonRetriable:
    @pytest.fixture
    def middleware(self):
        return TransportMiddleware()

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_non_retriable_skips_enqueue_writes_dlq(self, middleware, mock_db):
        ctx = _make_ctx(db=mock_db)
        failed = [
            DeliveryResult(
                success=False,
                target_node_id="agent-offline",
                error="instance_not_connected_locally",
            ),
        ]

        with patch.object(
            middleware, "_broadcast_offline_error", new_callable=AsyncMock,
        ) as mock_broadcast:
            await middleware._handle_failures(ctx, failed)

            mock_broadcast.assert_awaited_once_with(mock_db, "ws-1", failed[0])

        assert "agent-offline" in ctx.extra.get("dead_lettered_targets", [])
        assert "agent-offline" not in ctx.extra.get("retried_targets", [])
        mock_db.add.assert_called_once()
        dl = mock_db.add.call_args[0][0]
        assert dl.last_error == "instance_not_connected_locally"
        assert dl.recoverable is False

    @pytest.mark.asyncio
    async def test_transient_error_still_enqueued(self, middleware, mock_db):
        ctx = _make_ctx(db=mock_db)
        failed = [
            DeliveryResult(
                success=False,
                target_node_id="agent-flaky",
                error="connection_timeout",
            ),
        ]

        with patch(
            "app.services.runtime.messaging.queue.enqueue",
            new_callable=AsyncMock,
        ) as mock_enqueue:
            await middleware._handle_failures(ctx, failed)

            mock_enqueue.assert_awaited_once()

        assert "agent-flaky" in ctx.extra.get("retried_targets", [])
        assert "agent-flaky" not in ctx.extra.get("dead_lettered_targets", [])

    @pytest.mark.asyncio
    async def test_other_no_retry_error_no_broadcast(self, middleware, mock_db):
        """Non-retriable errors other than instance_not_connected_locally skip
        enqueue but do NOT broadcast agent:error."""
        ctx = _make_ctx(db=mock_db)
        failed = [
            DeliveryResult(
                success=False,
                target_node_id="agent-gone",
                error="instance_not_found",
            ),
        ]

        with patch.object(
            middleware, "_broadcast_offline_error", new_callable=AsyncMock,
        ) as mock_broadcast:
            await middleware._handle_failures(ctx, failed)

            mock_broadcast.assert_not_awaited()

        assert "agent-gone" in ctx.extra.get("dead_lettered_targets", [])


class TestBroadcastOfflineError:
    @pytest.fixture
    def middleware(self):
        return TransportMiddleware()

    @pytest.mark.asyncio
    async def test_broadcasts_with_agent_name_from_nodecard(self, middleware):
        mock_card = MagicMock()
        mock_card.name = "高级开发python"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_card

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = DeliveryResult(
            success=False,
            target_node_id="agent-abc",
            error="instance_not_connected_locally",
        )

        with patch(
            "app.api.workspaces.broadcast_event",
            new_callable=AsyncMock,
        ) as mock_broadcast:
            await middleware._broadcast_offline_error(mock_db, "ws-1", result)

            mock_broadcast.assert_called_once_with("ws-1", "agent:error", {
                "instance_id": "agent-abc",
                "agent_name": "高级开发python",
                "error": "instance_not_connected_locally",
                "error_detail": None,
            })

    @pytest.mark.asyncio
    async def test_falls_back_to_node_id_when_no_card(self, middleware):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = DeliveryResult(
            success=False,
            target_node_id="agent-xyz",
            error="instance_not_connected_locally",
        )

        with patch(
            "app.api.workspaces.broadcast_event",
            new_callable=AsyncMock,
        ) as mock_broadcast:
            await middleware._broadcast_offline_error(mock_db, "ws-1", result)

            mock_broadcast.assert_called_once_with("ws-1", "agent:error", {
                "instance_id": "agent-xyz",
                "agent_name": "agent-xyz",
                "error": "instance_not_connected_locally",
                "error_detail": None,
            })


class TestHealthLogOrdering:
    @pytest.mark.asyncio
    async def test_log_shows_old_then_new_status(self, caplog):
        mock_card = MagicMock()
        mock_card.node_id = "agent-1"
        mock_card.status = "active"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_card]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        mock_tunnel = AsyncMock()
        mock_tunnel.health_check = AsyncMock(return_value=False)

        with patch("app.services.tunnel.tunnel_adapter", mock_tunnel):
            import logging

            from app.services.runtime.failure_recovery import _update_agent_health

            with caplog.at_level(logging.INFO, logger="app.services.runtime.failure_recovery"):
                await _update_agent_health(mock_db)

        assert "active -> unhealthy" in caplog.text
        assert "unhealthy -> unhealthy" not in caplog.text
        assert mock_card.status == "unhealthy"
