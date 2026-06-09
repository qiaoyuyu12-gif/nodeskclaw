from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.api.storage import _resolve_storage_cluster
from app.core.exceptions import BadRequestError, NotFoundError
from app.models import Base
from app.models.cluster import Cluster
from app.models.organization import Organization
from app.models.user import User

TEST_DATABASE_URL = "postgresql+asyncpg://nodeskclaw:nodeskclaw123@localhost:5432/nodeskclaw_rbac_test"

engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(scope="module", autouse=True)
async def setup_db():
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception:
        yield False
        return

    yield True

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _seed_clusters(db: AsyncSession) -> tuple[str, str, str]:
    suffix = uuid4().hex[:8]
    org = Organization(id=f"org-storage-scope-{suffix}", name="Storage Scope Org", slug=f"storage-scope-org-{suffix}")
    outsider_org = Organization(
        id=f"org-storage-outsider-{suffix}", name="Outsider Org", slug=f"storage-scope-outsider-{suffix}",
    )
    user = User(
        id=f"user-storage-scope-{suffix}",
        name="Storage Scope User",
        email=f"storage-scope-{suffix}@example.com",
        username=f"storage-scope-{suffix}",
        password_hash="x",
    )
    db.add_all([org, outsider_org, user])

    cluster_a = Cluster(
        id=f"cluster-storage-a-{suffix}",
        name="Cluster A",
        org_id=org.id,
        created_by=user.id,
        compute_provider="k8s",
        status="connected",
    )
    cluster_b = Cluster(
        id=f"cluster-storage-b-{suffix}",
        name="Cluster B",
        org_id=org.id,
        created_by=user.id,
        compute_provider="k8s",
        status="connected",
    )
    outsider = Cluster(
        id=f"cluster-storage-outsider-{suffix}",
        name="Outsider Cluster",
        org_id=outsider_org.id,
        created_by=user.id,
        compute_provider="k8s",
        status="connected",
    )
    db.add_all([cluster_a, cluster_b, outsider])
    await db.commit()
    return org.id, cluster_a.id, outsider.id


@pytest.mark.asyncio
async def test_resolve_storage_cluster_requires_explicit_cluster_in_multi_cluster_org(setup_db):
    if not setup_db:
        pytest.skip("test database unavailable")

    async with TestSessionLocal() as db:
        org_id, _, _ = await _seed_clusters(db)

        with pytest.raises(BadRequestError) as exc:
            await _resolve_storage_cluster(db, None, org_id)

        assert exc.value.message_key == "errors.cluster.id_required"


@pytest.mark.asyncio
async def test_resolve_storage_cluster_filters_by_org_and_cluster_id(setup_db):
    if not setup_db:
        pytest.skip("test database unavailable")

    async with TestSessionLocal() as db:
        org_id, cluster_id, outsider_cluster_id = await _seed_clusters(db)

        cluster = await _resolve_storage_cluster(db, cluster_id, org_id)

        assert cluster is not None
        assert cluster.id == cluster_id

        with pytest.raises(NotFoundError) as exc:
            await _resolve_storage_cluster(db, outsider_cluster_id, org_id)

        assert exc.value.message_key == "errors.cluster.not_found"
