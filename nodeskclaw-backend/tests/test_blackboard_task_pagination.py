from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.api import workspaces as workspace_api
from app.main import app
from app.models.organization import Organization
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_task import WorkspaceTask
from app.schemas.workspace import TaskInfo
from app.services.workspace_service import list_tasks, list_tasks_paginated

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


@pytest.fixture
def override_workspace_auth():
    dep = workspace_api._get_current_user_or_agent_dep()
    app.dependency_overrides[dep] = lambda: SimpleNamespace(id="user-1")
    yield
    app.dependency_overrides.pop(dep, None)


async def _seed_workspace_tasks(db: AsyncSession) -> str:
    now = datetime.now(timezone.utc)
    org = Organization(id="org-task-pagination", name="Task Org", slug="task-org-pagination")
    user = User(id="user-task-pagination", name="Tester", username="tester-task-pagination")
    workspace = Workspace(
        id="ws-task-pagination",
        org_id=org.id,
        name="Task Desk",
        description="",
        color="#111111",
        icon="bot",
        created_by=user.id,
    )
    db.add_all([org, user, workspace])
    db.add_all([
        WorkspaceTask(
            id="task-pending",
            workspace_id=workspace.id,
            title="Pending task",
            status="pending",
            priority="medium",
            created_at=now - timedelta(days=3),
            updated_at=now - timedelta(days=3),
        ),
        WorkspaceTask(
            id="task-done-active",
            workspace_id=workspace.id,
            title="Done active",
            status="done",
            priority="high",
            completed_at=now - timedelta(hours=2),
            created_at=now - timedelta(days=2),
            updated_at=now - timedelta(hours=2),
        ),
        WorkspaceTask(
            id="task-archived-old",
            workspace_id=workspace.id,
            title="Archived old",
            status="archived",
            priority="medium",
            archived_at=now - timedelta(days=1),
            archived_from_status="done",
            created_at=now - timedelta(days=4),
            updated_at=now - timedelta(days=1),
        ),
        WorkspaceTask(
            id="task-archived-new",
            workspace_id=workspace.id,
            title="Archived new",
            status="archived",
            priority="medium",
            archived_at=now - timedelta(hours=1),
            archived_from_status="done",
            created_at=now - timedelta(days=1),
            updated_at=now - timedelta(hours=1),
        ),
        WorkspaceTask(
            id="task-archived-deleted",
            workspace_id=workspace.id,
            title="Archived deleted",
            status="archived",
            priority="low",
            archived_at=now - timedelta(minutes=30),
            archived_from_status="done",
            created_at=now - timedelta(days=1),
            updated_at=now - timedelta(minutes=30),
            deleted_at=now - timedelta(minutes=5),
        ),
    ])
    await db.commit()
    return workspace.id


def _sample_task(task_id: str = "task-route") -> TaskInfo:
    now = datetime.now(timezone.utc)
    return TaskInfo(
        id=task_id,
        workspace_id="ws-route",
        title="Route task",
        description=None,
        status="done",
        priority="medium",
        assignee_instance_id=None,
        assignee_name=None,
        created_by_instance_id=None,
        estimated_value=None,
        actual_value=None,
        token_cost=None,
        blocker_reason=None,
        completed_at=now,
        archived_at=None,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_list_tasks_keeps_non_paginated_legacy_archived(require_test_db):
    async with TestSessionLocal() as db:
        workspace_id = await _seed_workspace_tasks(db)

        items = await list_tasks(db, workspace_id, status="done")

        assert [item.id for item in items] == [
            "task-archived-new",
            "task-done-active",
            "task-archived-old",
        ]
        assert all(item.status == "done" for item in items)


@pytest.mark.asyncio
async def test_list_tasks_paginated_active_done_excludes_legacy_archived(require_test_db):
    async with TestSessionLocal() as db:
        workspace_id = await _seed_workspace_tasks(db)

        items, total = await list_tasks_paginated(
            db,
            workspace_id,
            status="done",
            bucket="active",
            page=1,
            page_size=20,
        )

        assert total == 1
        assert [item.id for item in items] == ["task-done-active"]


@pytest.mark.asyncio
async def test_list_tasks_paginated_inactive_returns_archived_in_desc_order(require_test_db):
    async with TestSessionLocal() as db:
        workspace_id = await _seed_workspace_tasks(db)

        items, total = await list_tasks_paginated(
            db,
            workspace_id,
            bucket="inactive",
            page=1,
            page_size=20,
        )

        assert total == 2
        assert [item.id for item in items] == [
            "task-archived-new",
            "task-archived-old",
        ]
        assert all(item.archived_at is not None for item in items)


@pytest.mark.asyncio
async def test_task_list_route_returns_paginated_response_when_requested(client, monkeypatch, override_workspace_auth):
    async def _noop_check_workspace_member(*_args, **_kwargs):
        return None

    monkeypatch.setattr(workspace_api.wm_service, "check_workspace_member", _noop_check_workspace_member)
    paginated_mock = AsyncMock(return_value=([_sample_task()], 7))
    monkeypatch.setattr(workspace_api.workspace_service, "list_tasks_paginated", paginated_mock)

    response = await client.get(
        "/api/v1/workspaces/ws-route/blackboard/tasks",
        params={
            "paginated": "true",
            "status": "done",
            "bucket": "active",
            "page": 2,
            "page_size": 5,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"][0]["id"] == "task-route"
    assert body["pagination"] == {"page": 2, "page_size": 5, "total": 7}
    paginated_mock.assert_awaited_once_with(
        ANY,
        "ws-route",
        status="done",
        bucket="active",
        page=2,
        page_size=5,
    )


@pytest.mark.asyncio
async def test_task_list_route_keeps_array_response_without_paginated(client, monkeypatch, override_workspace_auth):
    async def _noop_check_workspace_member(*_args, **_kwargs):
        return None

    monkeypatch.setattr(workspace_api.wm_service, "check_workspace_member", _noop_check_workspace_member)
    list_mock = AsyncMock(return_value=[_sample_task("task-plain")])
    monkeypatch.setattr(workspace_api.workspace_service, "list_tasks", list_mock)

    response = await client.get(
        "/api/v1/workspaces/ws-route/blackboard/tasks",
        params={"status": "done"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"][0]["id"] == "task-plain"
    assert "pagination" not in body
    list_mock.assert_awaited_once_with(ANY, "ws-route", "done", True)


@pytest.mark.asyncio
async def test_list_tasks_paginated_column_done_includes_archived(require_test_db):
    async with TestSessionLocal() as db:
        workspace_id = await _seed_workspace_tasks(db)

        items, total = await list_tasks_paginated(
            db,
            workspace_id,
            status="done",
            bucket="column",
            page=1,
            page_size=20,
        )

        assert total == 3
        ids = [item.id for item in items]
        assert ids[0] == "task-done-active"
        assert set(ids[1:]) == {"task-archived-new", "task-archived-old"}


@pytest.mark.asyncio
async def test_list_tasks_paginated_column_pending_excludes_archived(require_test_db):
    async with TestSessionLocal() as db:
        workspace_id = await _seed_workspace_tasks(db)

        items, total = await list_tasks_paginated(
            db,
            workspace_id,
            status="pending",
            bucket="column",
            page=1,
            page_size=20,
        )

        assert total == 1
        assert [item.id for item in items] == ["task-pending"]


@pytest.mark.asyncio
async def test_list_tasks_paginated_column_requires_status(require_test_db):
    async with TestSessionLocal() as db:
        workspace_id = await _seed_workspace_tasks(db)

        items, total = await list_tasks_paginated(
            db,
            workspace_id,
            bucket="column",
            page=1,
            page_size=20,
        )

        assert total == 0
        assert items == []


@pytest.mark.asyncio
async def test_list_tasks_paginated_column_archived_task_status_mapped(require_test_db):
    async with TestSessionLocal() as db:
        workspace_id = await _seed_workspace_tasks(db)

        items, total = await list_tasks_paginated(
            db,
            workspace_id,
            status="done",
            bucket="column",
            page=1,
            page_size=20,
        )

        for item in items:
            assert item.status == "done"
        archived_items = [i for i in items if i.archived_at is not None]
        assert len(archived_items) == 2
