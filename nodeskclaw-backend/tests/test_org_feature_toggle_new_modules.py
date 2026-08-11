"""验证 6 个核心模块（协作空间/实例/技能市场/自动化/外部Agent/知识库）的
主入口路由都已经挂上对应的 require_feature 门控：关闭 override 后 403，
默认（无 override）时正常放行。"""
import uuid

import pytest
from httpx import AsyncClient

from app.core.security import get_current_user
from app.main import app
from app.models.org_membership import OrgMembership, OrgRole
from app.models.organization import Organization
from app.models.organization_feature_override import OrganizationFeatureOverride
from app.models.user import User
from app.services import registry_aggregator
from app.services.local_adapter import LocalAdapter
from tests.conftest import TestSessionLocal


@pytest.fixture(autouse=True)
async def _init_registry_aggregator():
    """GET /api/v1/genes（visibility=None）内部经 gene_service.list_genes()
    调用 registry_aggregator.get_aggregator()；测试用的 ASGITransport 不会
    触发 app lifespan（app/main.py 里的 registry_aggregator.init() 只在真实
    启动时执行），必须在测试里现场初始化，用法与既有的
    tests/test_gene_lineage_version_awareness.py 保持一致，避免污染同进程内
    其它测试模块的全局单例。"""
    registry_aggregator.init([LocalAdapter(session_factory=TestSessionLocal)])
    yield
    await registry_aggregator.close()


def _override_user(user: User):
    app.dependency_overrides[get_current_user] = lambda: user


def _clear_override():
    app.dependency_overrides.pop(get_current_user, None)


async def _make_org_admin(suffix: str) -> tuple[User, Organization]:
    async with TestSessionLocal() as db:
        org = Organization(name=f"org-ft-{suffix}", slug=f"org-ft-{suffix}")
        db.add(org)
        await db.flush()
        user = User(
            email=f"user-ft-{suffix}@example.com", name="user-ft",
            password_hash="x", current_org_id=org.id,
        )
        db.add(user)
        await db.flush()
        db.add(OrgMembership(org_id=org.id, user_id=user.id, role=OrgRole.admin))
        await db.commit()
        await db.refresh(user)
        await db.refresh(org)
        return user, org


async def _disable_feature(org_id: str, feature_id: str, set_by_user_id: str):
    async with TestSessionLocal() as db:
        db.add(OrganizationFeatureOverride(
            org_id=org_id, feature_id=feature_id, enabled=False,
            set_by_user_id=set_by_user_id,
        ))
        await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "feature_id,method,path",
    [
        ("workspace", "GET", "/api/v1/workspaces"),
        ("instance", "GET", "/api/v1/instances"),
        ("gene_market", "GET", "/api/v1/genes"),
        ("automation", "GET", "/api/v1/automation-tasks"),
        ("external_agent", "GET", "/api/v1/external-agents"),
        ("knowledge_base", "GET", "/api/v1/knowledge-bases"),
    ],
)
async def test_module_enabled_by_default(client: AsyncClient, feature_id, method, path):
    suffix = uuid.uuid4().hex[:8] + feature_id[:4]
    user, _org = await _make_org_admin(suffix)

    _override_user(user)
    try:
        resp = await client.request(method, path)
        assert resp.status_code != 403, resp.text
    finally:
        _clear_override()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "feature_id,method,path",
    [
        ("workspace", "GET", "/api/v1/workspaces"),
        ("instance", "GET", "/api/v1/instances"),
        ("gene_market", "GET", "/api/v1/genes"),
        ("automation", "GET", "/api/v1/automation-tasks"),
        ("external_agent", "GET", "/api/v1/external-agents"),
        ("knowledge_base", "GET", "/api/v1/knowledge-bases"),
    ],
)
async def test_module_disabled_via_org_override(client: AsyncClient, feature_id, method, path):
    suffix = uuid.uuid4().hex[:8] + feature_id[:4]
    user, org = await _make_org_admin(suffix)
    await _disable_feature(org.id, feature_id, user.id)

    _override_user(user)
    try:
        resp = await client.request(method, path)
        assert resp.status_code == 403, resp.text
        # 全局 HTTPException handler（app/core/exceptions.py）会把 exc.detail
        # 拍平进顶层字段，响应体不含 "detail" key，故直接取顶层 message_key。
        assert resp.json()["message_key"] == "errors.feature.disabled"
    finally:
        _clear_override()
