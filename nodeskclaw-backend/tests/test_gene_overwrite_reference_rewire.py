"""验证 create_gene() 覆盖上传后，指向旧 Gene 行的"当前生效状态"引用会被正确重接。

背景：覆盖上传是"软删旧行 + 插入一条全新 id 的新行"，不是原地更新。已安装该
技能的实例（InstanceGene.gene_id）、已被组织强制要求安装的技能
（OrgRequiredGene.gene_id）在覆盖前都是指向旧行的，如果不重接，旧行被软删
之后，这些引用会因为查询过滤 `Gene.deleted_at IS NULL` 而"查不到人"，导致
已安装技能从实例技能列表里消失、组织强制要求的技能列表也跟着丢记录。

用真实 PostgreSQL 测试库（与 test_gene_name_dedup.py 一致的模式），因为要
验证的是跨表引用重接的真实落库行为，mock 掉 db 无法覆盖这一点。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.models.cluster import Cluster
from app.models.gene import InstanceGene, InstanceGeneStatus
from app.models.instance import Instance
from app.models.org_required_gene import OrgRequiredGene
from app.models.organization import Organization
from app.models.user import User
from app.schemas.gene import GeneCreateRequest
from app.services.gene_service import (
    create_gene,
    get_gene_installed_instance_ids,
    get_instance_genes,
)

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


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _minimal_req(name: str, slug: str, *, visibility: str = "personal", overwrite: bool = False) -> GeneCreateRequest:
    return GeneCreateRequest(name=name, slug=slug, visibility=visibility, overwrite=overwrite)


async def _create_instance(db: AsyncSession, user: User) -> Instance:
    cluster = Cluster(id=_uid("cluster"), name="Cluster", created_by=user.id)
    instance = Instance(
        id=_uid("inst"),
        name="Agent",
        slug=_uid("agent"),
        cluster_id=cluster.id,
        namespace="default",
        image_version="latest",
        created_by=user.id,
    )
    db.add_all([cluster, instance])
    await db.commit()
    return instance


@pytest.mark.asyncio
async def test_overwrite_rewires_installed_instance_gene_reference(require_test_db):
    """覆盖上传后，已安装该技能的实例引用应指向新行，而不是被软删的旧行。"""
    async with TestSessionLocal() as db:
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add(user)
        await db.commit()
        instance = await _create_instance(db, user)

        old = await create_gene(
            db, _minimal_req("客服助手", "customer-bot"),
            user_id=user.id, org_id=None, visibility="personal",
        )
        old_gene_id = old["id"]

        ig = InstanceGene(
            instance_id=instance.id,
            gene_id=old_gene_id,
            status=InstanceGeneStatus.installed,
            installed_version="1.0.0",
        )
        db.add(ig)
        await db.commit()

        new = await create_gene(
            db, _minimal_req("客服助手", "customer-bot", overwrite=True),
            user_id=user.id, org_id=None, visibility="personal",
        )
        new_gene_id = new["id"]
        assert new_gene_id != old_gene_id

        await db.refresh(ig)
        assert ig.gene_id == new_gene_id

        # 实例技能列表不应该因为覆盖而"丢"掉这条已安装记录
        items = await get_instance_genes(db, instance.id)
        assert any(item["gene_id"] == new_gene_id for item in items)

        # "已安装到 N 个实例" 的计数应该按新 slug 正确统计到，而不是归零
        installed_instance_ids = await get_gene_installed_instance_ids(db, "customer-bot")
        assert instance.id in installed_instance_ids


@pytest.mark.asyncio
async def test_overwrite_rewires_org_required_gene_reference(require_test_db):
    """覆盖上传后，组织强制要求该技能的记录应指向新行，而不是被软删的旧行。"""
    async with TestSessionLocal() as db:
        org = Organization(id=_uid("org"), name="Org A", slug=_uid("org-a"))
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add_all([org, user])
        await db.commit()

        old = await create_gene(
            db, _minimal_req("团队助手", "team-bot", visibility="org_private"),
            user_id=user.id, org_id=org.id, visibility="org_private",
        )
        old_gene_id = old["id"]

        rg = OrgRequiredGene(org_id=org.id, gene_id=old_gene_id)
        db.add(rg)
        await db.commit()

        new = await create_gene(
            db, _minimal_req("团队助手", "team-bot", visibility="org_private", overwrite=True),
            user_id=user.id, org_id=org.id, visibility="org_private",
        )
        new_gene_id = new["id"]
        assert new_gene_id != old_gene_id

        await db.refresh(rg)
        assert rg.gene_id == new_gene_id


@pytest.mark.asyncio
async def test_overwrite_without_existing_references_is_a_noop(require_test_db):
    """覆盖一个没有任何实例安装、没有任何组织强制要求的技能，重接逻辑应安全跳过，不报错。"""
    async with TestSessionLocal() as db:
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add(user)
        await db.commit()

        await create_gene(
            db, _minimal_req("无引用助手", "no-ref-bot"),
            user_id=user.id, org_id=None, visibility="personal",
        )
        result = await create_gene(
            db, _minimal_req("无引用助手", "no-ref-bot", overwrite=True),
            user_id=user.id, org_id=None, visibility="personal",
        )
        assert result["name"] == "无引用助手"
