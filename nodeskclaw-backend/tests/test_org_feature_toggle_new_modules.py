"""验证 6 个核心模块（协作空间/实例/技能市场/自动化/外部Agent/知识库）的
主入口路由都已经挂上对应的 require_feature 门控：关闭 override 后 403，
默认（无 override）时正常放行。"""
import uuid

import pytest
from httpx import AsyncClient

from app.core.security import get_current_user, get_current_user_or_agent
from app.main import app
from app.models.org_membership import OrgMembership, OrgRole
from app.models.organization import Organization
from app.models.organization_feature_override import OrganizationFeatureOverride
from app.models.user import User
from app.models.workspace import Workspace
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


async def _make_org_admin_with_workspace(suffix: str) -> tuple[User, Organization, Workspace]:
    """给 finding-1 回归测试用：额外造一个真实 Workspace（不建 Blackboard 行，
    因为这里只关心请求是否被 workspace 门控拦在 403，不关心业务数据是否存在）。"""
    user, org = await _make_org_admin(suffix)
    async with TestSessionLocal() as db:
        ws = Workspace(org_id=org.id, name=f"ws-ft-{suffix}", created_by=user.id)
        db.add(ws)
        await db.commit()
        await db.refresh(ws)
        return user, org, ws


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


# ── 回归测试：workspaces.py 的 "workspace" 门控必须是逐路由而非路由器级 ──────
#
# 背景（final review finding）：Task 5 曾把 require_feature("workspace") 挂在
# `router = APIRouter(dependencies=[...])` 上，导致文件里所有路由（含约 20 个
# 允许 AI 实例用 proxy_token 通过 get_current_user_or_agent 回调、以及 1 个
# SSE 用 get_current_user_from_query 走 query token 的路由）在到达各自的鉴权
# 逻辑之前就被这个仅认 JWT header 的门控拦成 401。修复方式是把门控从路由器级
# 收窄到逐个端点，只挂在纯 JWT 鉴权的端点上，AI/SSE 路由完全不挂。
#
# 下面用 GET /{workspace_id}/blackboard（AI 可回调、走 get_current_user_or_agent）
# 验证关闭组织 "workspace" 开关后它仍然可达（不会被功能门控拦成 403），
# 与同一开关关闭后 GET /api/v1/workspaces（纯 JWT，上面 test_module_disabled_via_org_override
# 已覆盖）确实返回 403 形成对照。

def _override_user_or_agent(user: User):
    app.dependency_overrides[get_current_user_or_agent] = lambda: user


def _clear_override_user_or_agent():
    app.dependency_overrides.pop(get_current_user_or_agent, None)


@pytest.mark.asyncio
async def test_workspace_feature_gate_does_not_block_agent_reachable_routes(client: AsyncClient):
    """关闭 "workspace" 组织开关后，纯 JWT 端点应 403；但 AI/SSE 可达的
    get_current_user_or_agent 端点必须完全不受这个开关影响（既不 401 也不
    403 errors.feature.disabled），这是本次 finding 1 修复要保证的核心行为。"""
    suffix = uuid.uuid4().hex[:8]
    user, org, workspace = await _make_org_admin_with_workspace(suffix)
    await _disable_feature(org.id, "workspace", user.id)

    # 对照组：纯 JWT 端点（本次仍在门控名单内）必须仍然 403
    _override_user(user)
    try:
        resp = await client.get("/api/v1/workspaces")
        assert resp.status_code == 403, resp.text
        assert resp.json()["message_key"] == "errors.feature.disabled"
    finally:
        _clear_override()

    # 目标组：get_current_user_or_agent 端点（AI 可回调，本次刻意不挂门控）
    # 必须不被 403 errors.feature.disabled 拦下。业务层面因为测试没建
    # Blackboard 行，预期会继续走到 404 blackboard_not_found，但绝不能是
    # feature 门控产生的 403 ——这正是本次要验证的回归点。
    _override_user_or_agent(user)
    try:
        resp = await client.get(f"/api/v1/workspaces/{workspace.id}/blackboard")
        assert resp.status_code != 403 or resp.json().get("message_key") != "errors.feature.disabled", resp.text
    finally:
        _clear_override_user_or_agent()


def test_gated_and_ungated_endpoint_sets_match_finding_1_classification():
    """静态兜底：直接检查 app 路由表，确认 workspaces.py 里被判定为「AI/SSE 可达」
    的 20 个端点（用 get_current_user_or_agent 或 get_current_user_from_query）
    的 dependant.dependencies 树里确实不含 require_feature() 产生的依赖闭包
    （app/core/deps.py 里命名为 _check_feature），router 本身（APIRouter()）
    也不再挂全局门控。比起再拼凑一次完整的 proxy_token HTTP 集成测试（需要
    真实 Instance + proxy_token 鉴权链路，与本次改动本身关系不大），这个测试
    直接对着最终装配好的路由树断言，对"逐路由门控"这件事本身覆盖更精确。"""
    from app.core.security import get_current_user_from_query

    # finding 1 清单里明确要求保持不挂门控的 20 个端点（AI 可回调 / SSE）
    ungated_paths = {
        ("GET", "/api/v1/workspaces/{workspace_id}/blackboard"),
        ("PUT", "/api/v1/workspaces/{workspace_id}/blackboard"),
        ("PATCH", "/api/v1/workspaces/{workspace_id}/blackboard/sections"),
        ("GET", "/api/v1/workspaces/{workspace_id}/blackboard/tasks"),
        ("POST", "/api/v1/workspaces/{workspace_id}/blackboard/tasks"),
        ("PUT", "/api/v1/workspaces/{workspace_id}/blackboard/tasks/{task_id}"),
        ("POST", "/api/v1/workspaces/{workspace_id}/blackboard/tasks/{task_id}/archive"),
        ("GET", "/api/v1/workspaces/{workspace_id}/blackboard/objectives"),
        ("POST", "/api/v1/workspaces/{workspace_id}/blackboard/objectives"),
        ("PUT", "/api/v1/workspaces/{workspace_id}/blackboard/objectives/{objective_id}"),
        ("GET", "/api/v1/workspaces/{workspace_id}/performance"),
        ("POST", "/api/v1/workspaces/{workspace_id}/performance/collect"),
        ("GET", "/api/v1/workspaces/{workspace_id}/performance/agents"),
        ("GET", "/api/v1/workspaces/{workspace_id}/members"),
        ("GET", "/api/v1/workspaces/{workspace_id}/files/{file_id}/download"),
        ("GET", "/api/v1/workspaces/{workspace_id}/messages"),
        ("POST", "/api/v1/workspaces/{workspace_id}/collaboration/send"),
        ("GET", "/api/v1/workspaces/{workspace_id}/collaboration-timeline"),
        ("GET", "/api/v1/workspaces/{workspace_id}/agents/{instance_id}/collaboration-messages"),
        ("GET", "/api/v1/workspaces/{workspace_id}/events"),
    }
    assert len(ungated_paths) == 20

    def _route_dependency_callables(route) -> set:
        return {d.call for d in route.dependant.dependencies}

    checked = 0
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not path.startswith("/api/v1/workspaces") or not methods:
            continue
        for method in methods:
            if method == "HEAD":
                continue
            key = (method, path)
            if key not in ungated_paths:
                continue
            checked += 1
            deps = _route_dependency_callables(route)
            dep_names = {getattr(d, "__name__", "") for d in deps}
            # require_feature() 内部闭包命名为 _check_feature（见 app/core/deps.py）
            assert "_check_feature" not in dep_names, f"{key} 不应挂 require_feature 门控"
            # 允许 get_current_user_or_agent 或 get_current_user_from_query，
            # 但不能是纯 get_current_user（否则说明分类判断错了）
            assert (
                get_current_user_or_agent in deps or get_current_user_from_query in deps
            ), f"{key} 应该走 agent/SSE 可达的鉴权依赖"

    assert checked == len(ungated_paths), (
        f"应该在路由表里精确匹配到 {len(ungated_paths)} 个 ungated 端点，实际匹配到 {checked} 个，"
        "说明上面手写的 path 列表和真实路由对不上，需要核对 workspaces.py"
    )
