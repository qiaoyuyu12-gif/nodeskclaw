from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.models.message_queue import MessageQueueItem
from app.services.runtime.retention import cleanup_consumed_queue_items

TEST_DATABASE_URL = "postgresql+asyncpg://nodeskclaw:nodeskclaw123@localhost:5432/nodeskclaw_rbac_test"
engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def require_test_db():
    try:
        async with engine.connect():
            yield
    except Exception:
        pytest.skip("PostgreSQL test database is not available")


@pytest.mark.asyncio
async def test_cleanup_consumed_queue_items_uses_soft_delete(require_test_db):
    async with TestSessionLocal() as db:
        now = datetime.now(timezone.utc)
        delivered_old = MessageQueueItem(
            id="mq-delivered-old",
            target_node_id="node-1",
            workspace_id="ws-1",
            status="delivered",
            created_at=now - timedelta(days=10),
            scheduled_at=now - timedelta(days=10),
            envelope={"type": "test"},
        )
        delivered_recent = MessageQueueItem(
            id="mq-delivered-recent",
            target_node_id="node-1",
            workspace_id="ws-1",
            status="delivered",
            created_at=now - timedelta(days=1),
            scheduled_at=now - timedelta(days=1),
            envelope={"type": "test"},
        )
        pending_old = MessageQueueItem(
            id="mq-pending-old",
            target_node_id="node-1",
            workspace_id="ws-1",
            status="pending",
            created_at=now - timedelta(days=10),
            scheduled_at=now - timedelta(days=10),
            envelope={"type": "test"},
        )
        db.add_all([delivered_old, delivered_recent, pending_old])
        await db.commit()

        count = await cleanup_consumed_queue_items(db, retention_days=7)
        await db.commit()

        assert count == 1

        rows = (
            await db.execute(
                select(MessageQueueItem).where(
                    MessageQueueItem.id.in_([
                        "mq-delivered-old",
                        "mq-delivered-recent",
                        "mq-pending-old",
                    ])
                )
            )
        ).scalars().all()
        by_id = {row.id: row for row in rows}

        assert len(by_id) == 3
        assert by_id["mq-delivered-old"].deleted_at is not None
        assert by_id["mq-delivered-recent"].deleted_at is None
        assert by_id["mq-pending-old"].deleted_at is None
