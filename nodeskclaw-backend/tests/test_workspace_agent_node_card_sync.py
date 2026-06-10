import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.models.cluster import Cluster
from app.models.instance import Instance
from app.models.node_card import NodeCard
from app.models.organization import Organization
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_agent import WorkspaceAgent
from app.schemas.workspace import UpdateAgentRequest
from app.services import workspace_service
import app.services.corridor_router as corridor_router

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
async def test_update_agent_syncs_node_card_position(monkeypatch: pytest.MonkeyPatch):
    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(corridor_router, "cascade_delete_connections", noop)
    monkeypatch.setattr(corridor_router, "auto_connect_hex", noop)

    async with TestSessionLocal() as db:
        org = Organization(id="org-agent-sync", name="Org", slug="org-agent-sync")
        user = User(id="user-agent-sync", name="Tester", username="tester-agent-sync")
        cluster = Cluster(
            id="cluster-agent-sync",
            name="Cluster",
            org_id=org.id,
            created_by=user.id,
        )
        workspace = Workspace(
            id="ws-agent-sync",
            org_id=org.id,
            name="Workspace",
            description="",
            color="#111111",
            icon="bot",
            created_by=user.id,
        )
        instance = Instance(
            id="inst-agent-sync",
            name="Agent",
            slug="agent-sync",
            cluster_id=cluster.id,
            namespace="default",
            image_version="latest",
            created_by=user.id,
            org_id=org.id,
            workspace_id=workspace.id,
            status="running",
        )
        agent = WorkspaceAgent(
            id="wa-agent-sync",
            workspace_id=workspace.id,
            instance_id=instance.id,
            hex_q=1,
            hex_r=0,
            display_name="Agent",
        )
        card = NodeCard(
            id="card-agent-sync",
            node_type="agent",
            node_id=instance.id,
            workspace_id=workspace.id,
            hex_q=1,
            hex_r=0,
            name="Agent",
        )
        db.add_all([org, user, cluster, workspace, instance, agent, card])
        await db.commit()

        updated = await workspace_service.update_agent(
            db,
            workspace.id,
            instance.id,
            UpdateAgentRequest(hex_q=3, hex_r=-1),
        )

        await db.refresh(card)
        assert updated is not None
        assert updated.hex_q == 3
        assert updated.hex_r == -1
        assert card.hex_q == 3
        assert card.hex_r == -1


@pytest.mark.asyncio
async def test_update_agent_syncs_node_card_name_on_rename(monkeypatch: pytest.MonkeyPatch):
    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(corridor_router, "cascade_delete_connections", noop)
    monkeypatch.setattr(corridor_router, "auto_connect_hex", noop)

    async with TestSessionLocal() as db:
        org = Organization(id="org-agent-rename", name="Org", slug="org-agent-rename")
        user = User(id="user-agent-rename", name="Tester", username="tester-agent-rename")
        cluster = Cluster(
            id="cluster-agent-rename",
            name="Cluster",
            org_id=org.id,
            created_by=user.id,
        )
        workspace = Workspace(
            id="ws-agent-rename",
            org_id=org.id,
            name="Workspace",
            description="",
            color="#111111",
            icon="bot",
            created_by=user.id,
        )
        instance = Instance(
            id="inst-agent-rename",
            name="Agent Origin",
            slug="agent-rename",
            cluster_id=cluster.id,
            namespace="default",
            image_version="latest",
            created_by=user.id,
            org_id=org.id,
            workspace_id=workspace.id,
            status="running",
        )
        agent = WorkspaceAgent(
            id="wa-agent-rename",
            workspace_id=workspace.id,
            instance_id=instance.id,
            hex_q=1,
            hex_r=0,
            display_name="Agent Origin",
        )
        card = NodeCard(
            id="card-agent-rename",
            node_type="agent",
            node_id=instance.id,
            workspace_id=workspace.id,
            hex_q=1,
            hex_r=0,
            name="Agent Origin",
        )
        db.add_all([org, user, cluster, workspace, instance, agent, card])
        await db.commit()

        updated = await workspace_service.update_agent(
            db,
            workspace.id,
            instance.id,
            UpdateAgentRequest(display_name="Agent Renamed"),
        )

        await db.refresh(card)
        assert updated is not None
        assert updated.display_name == "Agent Renamed"
        assert card.name == "Agent Renamed"
