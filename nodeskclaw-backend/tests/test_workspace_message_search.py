from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.models.organization import Organization
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_message import WorkspaceMessage
from app.services.workspace_message_service import search_messages

TEST_DATABASE_URL = "postgresql+asyncpg://nodeskclaw:nodeskclaw123@localhost:5432/nodeskclaw_rbac_test"
engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def require_test_db():
    try:
        async with engine.connect():
            yield
    except Exception:
        pytest.skip("PostgreSQL test database is not available")


@pytest.mark.asyncio
async def test_search_messages_filters_keyword_and_time_range():
    async with TestSessionLocal() as db:
        org = Organization(id="org-1", name="Test Org", slug="test-org")
        user = User(id="user-1", name="Tester", username="tester")
        workspace = Workspace(
            id="ws-1",
            org_id=org.id,
            name="Desk",
            description="",
            color="#000000",
            icon="bot",
            created_by=user.id,
        )
        db.add_all([org, user, workspace])

        now = datetime.now(timezone.utc)
        db.add_all([
            WorkspaceMessage(
                id="msg-1",
                workspace_id=workspace.id,
                sender_type="user",
                sender_id="user-1",
                sender_name="Alice",
                content="Discuss launch plan",
                message_type="chat",
                created_at=now - timedelta(days=2),
            ),
            WorkspaceMessage(
                id="msg-2",
                workspace_id=workspace.id,
                sender_type="agent",
                sender_id="agent-1",
                sender_name="Planner",
                content="Launch checklist ready",
                message_type="chat",
                created_at=now - timedelta(hours=12),
            ),
            WorkspaceMessage(
                id="msg-3",
                workspace_id=workspace.id,
                sender_type="user",
                sender_id="user-2",
                sender_name="Bob",
                content="Budget sync tomorrow",
                message_type="chat",
                created_at=now - timedelta(hours=1),
            ),
            WorkspaceMessage(
                id="msg-4",
                workspace_id=workspace.id,
                sender_type="user",
                sender_id="user-3",
                sender_name="Archived",
                content="Launch archive",
                message_type="chat",
                created_at=now - timedelta(minutes=30),
                deleted_at=now - timedelta(minutes=5),
            ),
        ])
        await db.commit()

        messages = await search_messages(
            db,
            workspace.id,
            q="launch",
            from_at=now - timedelta(days=1),
            to_at=now,
            limit=20,
        )

        assert [message.id for message in messages] == ["msg-2"]


@pytest.mark.asyncio
async def test_search_messages_matches_sender_name_and_returns_chronological_order():
    async with TestSessionLocal() as db:
        org = Organization(id="org-2", name="Test Org 2", slug="test-org-2")
        user = User(id="user-10", name="Tester", username="tester-2")
        workspace = Workspace(
            id="ws-2",
            org_id=org.id,
            name="Desk 2",
            description="",
            color="#111111",
            icon="bot",
            created_by=user.id,
        )
        db.add_all([org, user, workspace])

        now = datetime.now(timezone.utc)
        db.add_all([
            WorkspaceMessage(
                id="msg-a",
                workspace_id=workspace.id,
                sender_type="agent",
                sender_id="agent-a",
                sender_name="Planner Bot",
                content="First update",
                message_type="chat",
                created_at=now - timedelta(minutes=20),
            ),
            WorkspaceMessage(
                id="msg-b",
                workspace_id=workspace.id,
                sender_type="agent",
                sender_id="agent-b",
                sender_name="Planner Bot",
                content="Second update",
                message_type="chat",
                created_at=now - timedelta(minutes=10),
            ),
        ])
        await db.commit()

        messages = await search_messages(db, workspace.id, q="planner", limit=20)

        assert [message.id for message in messages] == ["msg-a", "msg-b"]
