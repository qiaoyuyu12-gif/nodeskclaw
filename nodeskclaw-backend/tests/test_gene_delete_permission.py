"""验证 delete_user_gene 的权限校验与级联软删 InstanceGene 的逻辑（单元测试，mock db）。

测试矩阵：
  - 非上传者、非 org admin、非超管 → 403
  - 超管 → 允许（软删成功）
  - 上传者本人 → 允许（软删成功）
  - 有 active InstanceGene 引用时 → 级联软删，不再返回 409
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException


# ─── Fake 对象 ────────────────────────────────────────────────────────────────

class _FakeUser:
    """模拟 User 对象，仅保留 id 与 is_super_admin 字段。"""

    def __init__(self, user_id: str, is_super_admin: bool = False):
        self.id = user_id
        self.is_super_admin = is_super_admin


class _FakeGene:
    """模拟 Gene 对象，提供 soft_delete 方法。"""

    def __init__(self, gene_id: str, created_by: str | None, org_id: str | None = None):
        self.id = gene_id
        self.created_by = created_by
        self.org_id = org_id
        self._deleted = False

    def soft_delete(self) -> None:
        """软删除标记。"""
        self._deleted = True


class _FakeInstanceGene:
    """模拟 InstanceGene 对象，提供 soft_delete 方法。"""

    def __init__(self, instance_id: str):
        self.instance_id = instance_id
        self._deleted = False

    def soft_delete(self) -> None:
        self._deleted = True


# ─── 辅助：构造 mock AsyncSession ─────────────────────────────────────────────

def _make_db(gene: _FakeGene | None, instance_refs: list[_FakeInstanceGene], membership=None) -> AsyncMock:
    """构造一个 AsyncMock 的 db session，按查询顺序返回预设结果。

    查询顺序：
      1. select(Gene) → gene
      2. select(OrgMembership) → membership（若 gene.org_id 非空）
      3. select(InstanceGene) → instance_refs（InstanceGene 行对象列表）
    """
    db = AsyncMock()
    db.commit = AsyncMock()

    execute_results: list[MagicMock] = []

    # 第 1 次：Gene 查询
    gene_result = MagicMock()
    gene_result.scalar_one_or_none.return_value = gene
    execute_results.append(gene_result)

    if gene is not None:
        # 第 2 次（仅在 gene.org_id 非空时触发）：OrgMembership 查询
        if gene.org_id:
            membership_result = MagicMock()
            membership_result.scalar_one_or_none.return_value = membership
            execute_results.append(membership_result)

        # 第 3 次（若到达级联软删阶段）：InstanceGene 查询
        refs_result = MagicMock()
        refs_result.scalars.return_value.all.return_value = instance_refs
        execute_results.append(refs_result)

    db.execute = AsyncMock(side_effect=execute_results)
    return db


# ─── 测试用例 ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_gene_forbidden_non_uploader_non_admin():
    """非上传者、非 org admin、非超管 → HTTPException 403。"""
    from app.services.gene_service import delete_user_gene

    gene = _FakeGene("gene-1", created_by="other-user-id", org_id=None)
    user = _FakeUser("current-user-id", is_super_admin=False)
    # org_id=None，无 membership 查询；直接进入权限拒绝分支
    db = _make_db(gene, instance_refs=[])

    with pytest.raises(HTTPException) as exc_info:
        await delete_user_gene(db, "gene-1", current_user=user)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["error_code"] == 40316


@pytest.mark.asyncio
async def test_delete_gene_allowed_super_admin():
    """超管无论是否为上传者，均允许删除。"""
    from app.services.gene_service import delete_user_gene

    gene = _FakeGene("gene-2", created_by="other-user-id", org_id=None)
    user = _FakeUser("super-admin-id", is_super_admin=True)
    db = _make_db(gene, instance_refs=[])

    result = await delete_user_gene(db, "gene-2", current_user=user)

    assert result == {"deleted": True, "id": "gene-2", "cascaded_instance_genes": 0}
    assert gene._deleted is True


@pytest.mark.asyncio
async def test_delete_gene_allowed_uploader():
    """上传者本人可删除自己上传的 gene。"""
    from app.services.gene_service import delete_user_gene

    gene = _FakeGene("gene-3", created_by="uploader-id", org_id=None)
    user = _FakeUser("uploader-id", is_super_admin=False)
    db = _make_db(gene, instance_refs=[])

    result = await delete_user_gene(db, "gene-3", current_user=user)

    assert result == {"deleted": True, "id": "gene-3", "cascaded_instance_genes": 0}
    assert gene._deleted is True


@pytest.mark.asyncio
async def test_delete_gene_cascades_instance_refs():
    """有 active 实例引用时：级联软删 InstanceGene，不再返回 409。"""
    from app.services.gene_service import delete_user_gene

    gene = _FakeGene("gene-4", created_by="uploader-id", org_id=None)
    user = _FakeUser("uploader-id", is_super_admin=False)
    refs = [_FakeInstanceGene("inst-a"), _FakeInstanceGene("inst-b")]
    db = _make_db(gene, instance_refs=refs)

    result = await delete_user_gene(db, "gene-4", current_user=user)

    assert result == {"deleted": True, "id": "gene-4", "cascaded_instance_genes": 2}
    assert gene._deleted is True
    # 所有引用 InstanceGene 都被一起软删
    assert all(ref._deleted for ref in refs)


@pytest.mark.asyncio
async def test_delete_gene_not_found():
    """gene 不存在时 → NotFoundError。"""
    from app.core.exceptions import NotFoundError
    from app.services.gene_service import delete_user_gene

    user = _FakeUser("any-user-id", is_super_admin=True)
    db = _make_db(None, instance_refs=[])  # Gene 查询返回 None

    with pytest.raises(NotFoundError):
        await delete_user_gene(db, "nonexistent-gene", current_user=user)
