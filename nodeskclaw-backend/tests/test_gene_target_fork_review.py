"""验证 gene_service 的 target/fork/审核新逻辑。

覆盖范围：
  - resolve_target_attrs：personal/org/public 三种 target 派生字段正确
  - resolve_target_attrs：必要参数缺失时抛 BadRequestError
  - review_gene：非组织 admin 非超管返回 403
  - review_gene：组织 admin 审核 pending_owner → approved（单步直审）
  - fork_gene_to_library：三向（personal/org/public）+ 权限矩阵
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.core.exceptions import BadRequestError, ForbiddenError
from app.models.gene import GeneReviewStatus
from app.services import gene_service


# ─── resolve_target_attrs ────────────────────────────────────────────


def test_resolve_target_attrs_personal():
    """personal 目标：归属用户、无 org、立即可用、不审核。"""
    attrs = gene_service.resolve_target_attrs(
        "personal", user_id="u-1", org_id=None,
    )
    assert attrs["visibility"] == "personal"
    assert attrs["org_id"] is None
    assert attrs["created_by"] == "u-1"
    assert attrs["is_published"] is True
    assert attrs["review_status"] is None


def test_resolve_target_attrs_org():
    """org 目标：归属组织、组织私有可见、待 owner 审核。"""
    attrs = gene_service.resolve_target_attrs(
        "org", user_id="u-1", org_id="org-1",
    )
    assert attrs["visibility"] == "org_private"
    assert attrs["org_id"] == "org-1"
    assert attrs["is_published"] is False
    assert attrs["review_status"] == GeneReviewStatus.pending_owner


def test_resolve_target_attrs_public():
    """public 目标：公共可见、归属上传者组织（背书）、待 owner 审核。"""
    attrs = gene_service.resolve_target_attrs(
        "public", user_id="u-1", org_id="org-1",
    )
    assert attrs["visibility"] == "public"
    assert attrs["org_id"] == "org-1"
    assert attrs["is_published"] is False
    assert attrs["review_status"] == GeneReviewStatus.pending_owner


def test_resolve_target_attrs_personal_requires_user():
    """personal 没有 user_id 必须失败。"""
    with pytest.raises(BadRequestError):
        gene_service.resolve_target_attrs("personal", user_id=None, org_id=None)


def test_resolve_target_attrs_org_requires_org():
    """org 没有 org_id 必须失败。"""
    with pytest.raises(BadRequestError):
        gene_service.resolve_target_attrs("org", user_id="u-1", org_id=None)


def test_resolve_target_attrs_public_requires_org():
    """public 没有 org_id 必须失败（公共市场上传需组织背书）。"""
    with pytest.raises(BadRequestError):
        gene_service.resolve_target_attrs("public", user_id="u-1", org_id=None)


def test_resolve_target_attrs_unknown():
    """未知 target 抛 BadRequestError。"""
    with pytest.raises(BadRequestError):
        gene_service.resolve_target_attrs("invalid", user_id="u-1", org_id="org-1")


# ─── review_gene 权限矩阵 ────────────────────────────────────────────


class _FakeUser:
    def __init__(
        self,
        user_id: str,
        is_super_admin: bool = False,
        current_org_id: str | None = None,
    ):
        self.id = user_id
        self.is_super_admin = is_super_admin
        # fork_gene_to_library 会从 current_user.current_org_id 取目标 org 上下文
        self.current_org_id = current_org_id


class _FakeGene:
    def __init__(
        self,
        gene_id: str = "g-1",
        org_id: str | None = "org-1",
        review_status: str = GeneReviewStatus.pending_owner,
        visibility: str = "org_private",
        created_by: str | None = "uploader",
        slug: str = "skill-x",
    ):
        self.id = gene_id
        self.org_id = org_id
        self.review_status = review_status
        self.visibility = visibility
        self.is_published = False
        self.created_by_instance_id = None
        self.created_by = created_by
        # fork 函数会读取一组 source_* 字段并复制
        self.slug = slug
        self.name = f"name-{slug}"
        self.description = None
        self.short_description = None
        self.category = None
        self.tags = None
        self.icon = None
        self.version = "1.0.0"
        self.manifest = None
        self.dependencies = None
        self.synergies = None


def _make_review_db(gene, membership=None) -> AsyncMock:
    """构造 mock db：第 1 次 execute 返回 gene；第 2 次返回 OrgMembership。"""
    db = AsyncMock()
    gene_result = MagicMock()
    gene_result.scalar_one_or_none.return_value = gene

    membership_result = MagicMock()
    membership_result.scalar_one_or_none.return_value = membership

    db.execute = AsyncMock(side_effect=[gene_result, membership_result])
    db.commit = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_review_gene_forbidden_for_non_admin():
    """非该 org admin / 非超管的普通用户调用审核 → 403。"""
    gene = _FakeGene()
    db = _make_review_db(gene, membership=None)  # 不是 org admin
    user = _FakeUser("u-1", is_super_admin=False)

    with pytest.raises(HTTPException) as exc:
        await gene_service.review_gene(
            db, "g-1", "approve", current_user=user,
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_review_gene_super_admin_allowed():
    """平台超管可以审核任何 gene（不依赖 OrgMembership）。"""
    gene = _FakeGene(review_status=GeneReviewStatus.pending_owner)
    db = _make_review_db(gene, membership=None)
    user = _FakeUser("u-super", is_super_admin=True)

    # 平台超管路径下，service 不会查 OrgMembership，所以只有 1 次 execute（gene 查询）
    # 重新构造 db 只放一次结果
    db = AsyncMock()
    gene_result = MagicMock()
    gene_result.scalar_one_or_none.return_value = gene
    db.execute = AsyncMock(return_value=gene_result)
    db.commit = AsyncMock()

    result = await gene_service.review_gene(
        db, "g-1", "approve", current_user=user,
    )
    assert result["review_status"] == GeneReviewStatus.approved
    assert result["is_published"] is True
    assert gene.review_status == GeneReviewStatus.approved


@pytest.mark.asyncio
async def test_review_gene_org_admin_single_step_approve():
    """组织 admin 审核 pending_owner → 直接 approved（不再经过 pending_admin 中转）。"""
    gene = _FakeGene(review_status=GeneReviewStatus.pending_owner, visibility="org_private")
    fake_membership = MagicMock()  # 任意非 None 即视为 admin
    db = _make_review_db(gene, membership=fake_membership)
    user = _FakeUser("u-admin", is_super_admin=False)

    result = await gene_service.review_gene(
        db, "g-1", "approve", current_user=user,
    )
    assert result["review_status"] == GeneReviewStatus.approved
    assert result["is_published"] is True


# ─── fork_gene_to_library：三向 + 权限矩阵 ───────────────────────────


def _make_fork_db(
    source: _FakeGene | None,
    *,
    membership=None,
    has_slug_conflict: bool = False,
) -> MagicMock:
    """构造 fork 流程所需的 mock db。

    调用顺序（取决于路径）：
      1. select(Gene) by slug → source
      2. （仅当非超管且源为 org scope 时）select(OrgMembership) → membership
      3. select(Gene) for slug 冲突 → existing
    db.add 为同步 MagicMock；db.commit / db.refresh 为 AsyncMock。
    """
    db = MagicMock()

    side_effects: list[MagicMock] = []
    # 1. 源 gene 查询
    src_result = MagicMock()
    src_result.scalar_one_or_none.return_value = source
    side_effects.append(src_result)

    # 2. OrgMembership（仅在测试构造时显式标记）
    if membership is not None or (source is not None and getattr(source, "_expect_membership_query", False)):
        m_result = MagicMock()
        m_result.scalar_one_or_none.return_value = membership
        side_effects.append(m_result)

    # 3. slug 冲突查询
    conflict_result = MagicMock()
    conflict_result.scalar_one_or_none.return_value = MagicMock() if has_slug_conflict else None
    side_effects.append(conflict_result)

    db.execute = AsyncMock(side_effect=side_effects)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_fork_personal_by_owner_to_org():
    """个人技能 → 组织 library：上传者本人可 fork，落库为 pending_owner。"""
    source = _FakeGene(
        gene_id="g-personal",
        org_id=None,
        created_by="owner-id",
        visibility="personal",
        review_status=None,
        slug="my-skill",
    )
    db = _make_fork_db(source)
    user = _FakeUser("owner-id", current_org_id="org-target")

    result = await gene_service.fork_gene_to_library(
        db, "my-skill", "org", current_user=user,
    )

    assert result["visibility"] == "org_private"
    assert result["org_id"] == "org-target"
    assert result["review_status"] == GeneReviewStatus.pending_owner
    assert result["is_published"] is False
    assert result["created_by"] == "owner-id"
    assert result["parent_gene_id"] == "g-personal"


@pytest.mark.asyncio
async def test_fork_personal_by_non_owner_forbidden():
    """个人技能 → 任意目标：非本人禁止 fork。"""
    source = _FakeGene(
        gene_id="g-personal",
        org_id=None,
        created_by="owner-id",
        visibility="personal",
        slug="my-skill",
    )
    db = _make_fork_db(source)
    user = _FakeUser("other-user", current_org_id="org-target")

    with pytest.raises(ForbiddenError) as exc:
        await gene_service.fork_gene_to_library(
            db, "my-skill", "personal", current_user=user,
        )
    assert exc.value.message_key == "errors.gene.fork_personal_forbidden"


@pytest.mark.asyncio
async def test_fork_personal_to_public_by_owner():
    """个人技能 → 公共市场：本人可 fork，pending_owner 等审。"""
    source = _FakeGene(
        gene_id="g-personal",
        org_id=None,
        created_by="owner-id",
        visibility="personal",
        slug="my-skill",
    )
    db = _make_fork_db(source)
    user = _FakeUser("owner-id", current_org_id="org-target")

    result = await gene_service.fork_gene_to_library(
        db, "my-skill", "public", current_user=user,
    )

    assert result["visibility"] == "public"
    assert result["org_id"] == "org-target"  # 公共发布也要挂在背书 org 下
    assert result["review_status"] == GeneReviewStatus.pending_owner
    assert result["is_published"] is False


@pytest.mark.asyncio
async def test_fork_org_by_member_to_personal():
    """组织技能 → 个人 library：本组成员可 fork。"""
    source = _FakeGene(
        gene_id="g-org",
        org_id="org-A",
        created_by="some-uploader",
        visibility="org_private",
        slug="team-skill",
    )
    source._expect_membership_query = True
    db = _make_fork_db(source, membership=MagicMock())  # 非 None 表示是该组成员
    user = _FakeUser("member-id", current_org_id="org-A")

    result = await gene_service.fork_gene_to_library(
        db, "team-skill", "personal", current_user=user,
    )

    assert result["visibility"] == "personal"
    assert result["org_id"] is None
    assert result["created_by"] == "member-id"
    assert result["parent_gene_id"] == "g-org"


@pytest.mark.asyncio
async def test_fork_org_by_non_member_forbidden():
    """组织技能 → 任意目标：非本组成员 403。"""
    source = _FakeGene(
        gene_id="g-org",
        org_id="org-A",
        created_by="some-uploader",
        visibility="org_private",
        slug="team-skill",
    )
    source._expect_membership_query = True
    db = _make_fork_db(source, membership=None)  # membership 缺失
    user = _FakeUser("outsider-id", current_org_id="org-B")

    with pytest.raises(ForbiddenError) as exc:
        await gene_service.fork_gene_to_library(
            db, "team-skill", "personal", current_user=user,
        )
    assert exc.value.message_key == "errors.gene.fork_org_forbidden"


@pytest.mark.asyncio
async def test_fork_org_to_public_by_member():
    """组织技能 → 公共市场：本组成员可 fork，进入 pending_owner。"""
    source = _FakeGene(
        gene_id="g-org",
        org_id="org-A",
        created_by="some-uploader",
        visibility="org_private",
        slug="team-skill",
    )
    source._expect_membership_query = True
    db = _make_fork_db(source, membership=MagicMock())
    user = _FakeUser("member-id", current_org_id="org-A")

    result = await gene_service.fork_gene_to_library(
        db, "team-skill", "public", current_user=user,
    )

    assert result["visibility"] == "public"
    assert result["org_id"] == "org-A"
    assert result["review_status"] == GeneReviewStatus.pending_owner


@pytest.mark.asyncio
async def test_fork_public_to_personal_anyone():
    """公共技能 → 个人 library：任意登录用户可 fork（回归原行为）。"""
    source = _FakeGene(
        gene_id="g-public",
        org_id="some-org",  # 公共技能也会挂在背书 org 下
        created_by="some-uploader",
        visibility="public",
        slug="popular-skill",
    )
    db = _make_fork_db(source)
    # 与源不同组、非本人，仍可 fork（公共可见）
    user = _FakeUser("any-user", current_org_id=None)

    result = await gene_service.fork_gene_to_library(
        db, "popular-skill", "personal", current_user=user,
    )

    assert result["visibility"] == "personal"
    assert result["org_id"] is None
    assert result["created_by"] == "any-user"


@pytest.mark.asyncio
async def test_fork_rejects_invalid_target():
    """target 必须是 personal / org / public 之一。"""
    db = MagicMock()
    user = _FakeUser("u-1", current_org_id="org-1")
    with pytest.raises(BadRequestError):
        await gene_service.fork_gene_to_library(
            db, "skill-x", "invalid", current_user=user,
        )


# ─── get_pending_review_genes 权限过滤 ────────────────────────────────


@pytest.fixture
def _stub_gene_to_dict(monkeypatch):
    """避免 _FakeGene 缺少 ORM 列字段：把序列化函数替换成只取 id/org_id。"""
    monkeypatch.setattr(
        gene_service,
        "_gene_to_dict",
        lambda g: {"id": g.id, "org_id": g.org_id},
    )


def _make_pending_db(genes_to_return, *, admin_org_ids=None):
    """构造 mock db：
    - 超管路径：仅 1 次 execute（gene 列表）
    - 普通用户路径：第 1 次 execute 返回 admin org_id 列表，第 2 次返回 gene 列表
    admin_org_ids 不为 None 时启用普通用户路径。
    """
    db = AsyncMock()
    gene_result = MagicMock()
    gene_scalars = MagicMock()
    gene_scalars.all.return_value = genes_to_return
    gene_result.scalars.return_value = gene_scalars

    if admin_org_ids is None:
        # 超管路径
        db.execute = AsyncMock(return_value=gene_result)
    else:
        # 普通用户路径：先查 org_id 列表
        org_result = MagicMock()
        org_result.all.return_value = [(oid,) for oid in admin_org_ids]
        db.execute = AsyncMock(side_effect=[org_result, gene_result])
    return db


@pytest.mark.asyncio
async def test_pending_review_super_admin_sees_all(_stub_gene_to_dict):
    """超管：返回所有待审 gene，不查 OrgMembership。"""
    gene_a = _FakeGene(gene_id="g-a", org_id="org-1")
    gene_b = _FakeGene(gene_id="g-b", org_id="org-2")
    db = _make_pending_db([gene_a, gene_b])
    user = _FakeUser("u-super", is_super_admin=True)

    result = await gene_service.get_pending_review_genes(db, current_user=user)
    assert len(result) == 2
    # 超管只有 1 次 execute（无 OrgMembership 查询）
    assert db.execute.await_count == 1


@pytest.mark.asyncio
async def test_pending_review_org_admin_only_sees_own_org(_stub_gene_to_dict):
    """组织 admin：只返回作为 admin 的 org 下待审 gene。"""
    gene_in_scope = _FakeGene(gene_id="g-a", org_id="org-A")
    db = _make_pending_db([gene_in_scope], admin_org_ids=["org-A"])
    user = _FakeUser("u-admin", is_super_admin=False)

    result = await gene_service.get_pending_review_genes(db, current_user=user)
    assert len(result) == 1
    assert result[0]["id"] == "g-a"
    # 应有 2 次 execute：先查 admin org_id，再查 gene
    assert db.execute.await_count == 2


@pytest.mark.asyncio
async def test_pending_review_normal_user_returns_empty(_stub_gene_to_dict):
    """非超管、非任何 org admin：返回空列表，不查 gene 表。"""
    db = _make_pending_db([], admin_org_ids=[])  # 空 admin org 列表
    user = _FakeUser("u-normal", is_super_admin=False)

    result = await gene_service.get_pending_review_genes(db, current_user=user)
    assert result == []
    # 仅 1 次 execute（查 admin org_id，发现为空就提前返回）
    assert db.execute.await_count == 1


# ─── get_gene_by_slug：多 scope 并存时不再 MultipleResultsFound ────────


@pytest.mark.asyncio
async def test_get_gene_by_slug_returns_first_when_multiple_scopes_exist():
    """fork 三向落库后，同 slug 多条 gene 共存：旧实现的 scalar_one_or_none 会
    抛 MultipleResultsFound 让 upload-folder 500。修复后必须用 .first() 兜底。"""
    gene_personal = _FakeGene(gene_id="g-p", org_id=None, slug="dup-slug")
    gene_org = _FakeGene(gene_id="g-o", org_id="org-A", slug="dup-slug")

    db = AsyncMock()
    result_obj = MagicMock()
    scalars = MagicMock()
    scalars.first.return_value = gene_personal  # 任取首条
    # 防御：万一新实现误用 scalar_one_or_none 会直接抛 MultipleResultsFound
    from sqlalchemy.exc import MultipleResultsFound
    result_obj.scalar_one_or_none.side_effect = MultipleResultsFound(
        "should not be called",
    )
    result_obj.scalars.return_value = scalars
    db.execute = AsyncMock(return_value=result_obj)

    got = await gene_service.get_gene_by_slug(db, "dup-slug")
    assert got is gene_personal
    # 确认走的是 scalars().first() 路径
    scalars.first.assert_called_once()
    result_obj.scalar_one_or_none.assert_not_called()
    # 静默引用避免 lint 警告
    assert gene_org.slug == "dup-slug"
