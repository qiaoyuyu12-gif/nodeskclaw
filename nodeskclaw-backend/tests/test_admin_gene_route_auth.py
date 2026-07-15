"""安全回归测试：/api/v1/admin/genes、/api/v1/admin/genomes 路由权限校验。

背景：gene_router 被同时挂载到 api_router（无 admin 校验）和 admin_router
（有 require_org_role("admin") 校验），但 genes.py 内部路由用字面量
"/admin/genes" 前缀，导致这些接口实际由无校验的挂载点提供服务——任何登录
用户都能调用 POST/PUT/DELETE /api/v1/admin/genes、/api/v1/admin/genomes，
不受 admin_router 的 dependencies=[Depends(require_org_role("admin"))] 约束。

修复方式：直接在这 6 个路由函数上加 Depends(require_org_role("admin"))，
不再依赖 router 挂载位置这个脆弱前提。同时修复 admin_create_gene /
admin_create_genome 里 current_user.org_id（User 模型上不存在该字段，
应为 current_user.current_org_id）导致的 AttributeError 500 崩溃。

本测试直接命中真实的 require_org_role 依赖链（AdminMembership 真实建表 +
真实查询），而不是绕过它做浅层 mock——因为这是权限校验代码，浅层 mock
无法证明修复真的生效。
"""

from uuid import uuid4

import pytest

from app.core.security import get_current_user
from app.main import app
from app.models.admin_membership import AdminMembership
from app.models.gene import Gene, Genome
from app.models.organization import Organization
from app.models.user import User
from tests.conftest import TestSessionLocal


@pytest.fixture
async def org():
    """一个干净的组织，用于挂载用户 / AdminMembership / Gene / Genome。"""
    suffix = uuid4().hex[:8]
    organization = Organization(
        id=f"org-agra-{suffix}", name="Admin Gene Route Auth Org", slug=f"agra-org-{suffix}",
    )
    async with TestSessionLocal() as db:
        db.add(organization)
        await db.commit()
    return organization


@pytest.fixture
async def non_admin_user(org):
    """在 org 内、但没有 AdminMembership 记录的普通登录用户。"""
    suffix = uuid4().hex[:8]
    user = User(
        id=f"user-agra-plain-{suffix}",
        name="Plain User",
        email=f"agra-plain-{suffix}@example.com",
        username=f"agra-plain-{suffix}",
        password_hash="x",
        current_org_id=org.id,
    )
    async with TestSessionLocal() as db:
        db.add(user)
        await db.commit()
    return user


@pytest.fixture
async def no_org_user():
    """完全没有 current_org_id 的登录用户（未加入任何组织）。"""
    suffix = uuid4().hex[:8]
    user = User(
        id=f"user-agra-noorg-{suffix}",
        name="No Org User",
        email=f"agra-noorg-{suffix}@example.com",
        username=f"agra-noorg-{suffix}",
        password_hash="x",
        current_org_id=None,
    )
    async with TestSessionLocal() as db:
        db.add(user)
        await db.commit()
    return user


@pytest.fixture
async def admin_user(org):
    """在 org 内、拥有 AdminMembership(role="admin") 的合法管理员。"""
    suffix = uuid4().hex[:8]
    user = User(
        id=f"user-agra-admin-{suffix}",
        name="Admin User",
        email=f"agra-admin-{suffix}@example.com",
        username=f"agra-admin-{suffix}",
        password_hash="x",
        current_org_id=org.id,
    )
    membership = AdminMembership(
        id=f"admin-membership-agra-{suffix}",
        user_id=user.id,
        org_id=org.id,
        role="admin",
    )
    async with TestSessionLocal() as db:
        db.add_all([user, membership])
        await db.commit()
    return user


@pytest.fixture
async def existing_gene(org):
    """一条真实存在的 Gene 行，供 update/delete 成功路径测试使用。"""
    suffix = uuid4().hex[:8]
    gene_id = f"gene-agra-{suffix}"
    gene = Gene(
        id=gene_id,
        name=f"Agra Test Gene {suffix}",
        slug=f"agra-test-gene-{suffix}",
        source="official",
        version="1.0.0",
        org_id=org.id,
        # lineage_group_id 是 NOT NULL 且无 Python 级默认值的血缘分组标识，
        # 直接走 ORM 构造必须显式给值（正常创建路径由 gene_service 生成）。
        lineage_group_id=gene_id,
    )
    async with TestSessionLocal() as db:
        db.add(gene)
        await db.commit()
    return gene


@pytest.fixture
async def existing_genome(org):
    """一条真实存在的 Genome 行，供 update/delete 成功路径测试使用。"""
    suffix = uuid4().hex[:8]
    genome = Genome(
        id=f"genome-agra-{suffix}",
        name=f"Agra Test Genome {suffix}",
        slug=f"agra-test-genome-{suffix}",
        org_id=org.id,
    )
    async with TestSessionLocal() as db:
        db.add(genome)
        await db.commit()
    return genome


def _override_user(user: User):
    app.dependency_overrides[get_current_user] = lambda: user


def _clear_override():
    app.dependency_overrides.pop(get_current_user, None)


# ─── 无 AdminMembership 的用户必须被拒绝（403） ───────────────────────


@pytest.mark.asyncio
async def test_update_gene_without_admin_membership_returns_403(client, non_admin_user, existing_gene):
    _override_user(non_admin_user)
    try:
        response = await client.put(
            f"/api/v1/admin/genes/{existing_gene.id}",
            json={"name": "hacked-name"},
        )
    finally:
        _clear_override()

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_delete_gene_without_admin_membership_returns_403(client, non_admin_user, existing_gene):
    _override_user(non_admin_user)
    try:
        response = await client.delete(f"/api/v1/admin/genes/{existing_gene.id}")
    finally:
        _clear_override()

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_update_genome_without_admin_membership_returns_403(client, non_admin_user, existing_genome):
    _override_user(non_admin_user)
    try:
        response = await client.put(
            f"/api/v1/admin/genomes/{existing_genome.id}",
            json={"name": "hacked-genome-name"},
        )
    finally:
        _clear_override()

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_delete_genome_without_admin_membership_returns_403(client, non_admin_user, existing_genome):
    _override_user(non_admin_user)
    try:
        response = await client.delete(f"/api/v1/admin/genomes/{existing_genome.id}")
    finally:
        _clear_override()

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_update_gene_without_org_returns_400(client, no_org_user, existing_gene):
    """连 current_org_id 都没有的用户：require_org_role 应先于 403 返回 400。"""
    _override_user(no_org_user)
    try:
        response = await client.put(
            f"/api/v1/admin/genes/{existing_gene.id}",
            json={"name": "hacked-name"},
        )
    finally:
        _clear_override()

    assert response.status_code == 400


# ─── 合法 admin 仍然可以正常调用（确认没有把合法请求也一起挡住） ──────


@pytest.mark.asyncio
async def test_admin_can_update_gene(client, admin_user, existing_gene):
    _override_user(admin_user)
    try:
        response = await client.put(
            f"/api/v1/admin/genes/{existing_gene.id}",
            json={"name": "legit-updated-name"},
        )
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["name"] == "legit-updated-name"


@pytest.mark.asyncio
async def test_admin_can_delete_gene(client, admin_user, existing_gene):
    _override_user(admin_user)
    try:
        response = await client.delete(f"/api/v1/admin/genes/{existing_gene.id}")
    finally:
        _clear_override()

    assert response.status_code == 200
    assert response.json()["data"]["deleted"] is True


@pytest.mark.asyncio
async def test_admin_can_update_genome(client, admin_user, existing_genome):
    _override_user(admin_user)
    try:
        response = await client.put(
            f"/api/v1/admin/genomes/{existing_genome.id}",
            json={"name": "legit-updated-genome-name"},
        )
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["name"] == "legit-updated-genome-name"


@pytest.mark.asyncio
async def test_admin_can_delete_genome(client, admin_user, existing_genome):
    _override_user(admin_user)
    try:
        response = await client.delete(f"/api/v1/admin/genomes/{existing_genome.id}")
    finally:
        _clear_override()

    assert response.status_code == 200
    assert response.json()["data"]["deleted"] is True


# ─── create_gene / create_genome：current_user.org_id → current_org_id 修复 ──


@pytest.mark.asyncio
async def test_admin_create_gene_no_longer_crashes_on_org_id(client, admin_user):
    """修复前 current_user.org_id 不存在会直接 AttributeError → 500；
    修复后应改用 current_user.current_org_id 正常创建成功（200）。
    """
    suffix = uuid4().hex[:8]
    _override_user(admin_user)
    try:
        response = await client.post(
            "/api/v1/admin/genes",
            json={"name": f"Agra Create Gene {suffix}", "slug": f"agra-create-gene-{suffix}"},
        )
    finally:
        _clear_override()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["data"]["org_id"] == admin_user.current_org_id


@pytest.mark.asyncio
async def test_admin_create_genome_no_longer_crashes_on_org_id(client, admin_user):
    suffix = uuid4().hex[:8]
    _override_user(admin_user)
    try:
        response = await client.post(
            "/api/v1/admin/genomes",
            json={"name": f"Agra Create Genome {suffix}", "slug": f"agra-create-genome-{suffix}"},
        )
    finally:
        _clear_override()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["data"]["org_id"] == admin_user.current_org_id


@pytest.mark.asyncio
async def test_create_gene_without_admin_membership_returns_403(client, non_admin_user):
    """create 接口同样受影响的 6 条路由之一，非 admin 用户应被拒绝。"""
    suffix = uuid4().hex[:8]
    _override_user(non_admin_user)
    try:
        response = await client.post(
            "/api/v1/admin/genes",
            json={"name": f"Should Not Create {suffix}", "slug": f"should-not-create-{suffix}"},
        )
    finally:
        _clear_override()

    assert response.status_code == 403
