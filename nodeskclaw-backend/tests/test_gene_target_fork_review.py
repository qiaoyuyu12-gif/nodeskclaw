"""验证 gene_service 的 target/fork/审核新逻辑。

覆盖范围：
  - resolve_target_attrs：personal/org/public 三种 target 派生字段正确
  - resolve_target_attrs：必要参数缺失时抛 BadRequestError
  - review_gene：非组织 admin 非超管返回 403
  - review_gene：组织 admin 审核 pending_owner → approved（单步直审）
  - fork_gene_to_library：非公共/未审核的 gene 不可 fork
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.core.exceptions import BadRequestError
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
    def __init__(self, user_id: str, is_super_admin: bool = False):
        self.id = user_id
        self.is_super_admin = is_super_admin


class _FakeGene:
    def __init__(
        self,
        gene_id: str = "g-1",
        org_id: str | None = "org-1",
        review_status: str = GeneReviewStatus.pending_owner,
        visibility: str = "org_private",
    ):
        self.id = gene_id
        self.org_id = org_id
        self.review_status = review_status
        self.visibility = visibility
        self.is_published = False
        self.created_by_instance_id = None


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


# ─── fork_gene_to_library 边界 ───────────────────────────────────────


@pytest.mark.asyncio
async def test_fork_rejects_non_public_source():
    """非 visibility=public 或未审核通过的 gene 不可 fork。"""
    source = _FakeGene(
        review_status=GeneReviewStatus.pending_owner,
        visibility="org_private",
    )
    source.slug = "skill-x"
    db = AsyncMock()
    gene_result = MagicMock()
    gene_result.scalar_one_or_none.return_value = source
    db.execute = AsyncMock(return_value=gene_result)

    with pytest.raises(BadRequestError):
        await gene_service.fork_gene_to_library(
            db, "skill-x", "personal",
            user_id="u-1", org_id=None,
        )


@pytest.mark.asyncio
async def test_fork_rejects_invalid_target():
    """fork 目标只能是 personal / org，public 不允许。"""
    db = AsyncMock()
    with pytest.raises(BadRequestError):
        await gene_service.fork_gene_to_library(
            db, "skill-x", "public",
            user_id="u-1", org_id="org-1",
        )
