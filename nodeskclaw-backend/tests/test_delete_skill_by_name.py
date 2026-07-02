"""验证 delete_skill_by_name 的核心行为（单元测试，mock db + remote_fs）。

测试矩阵：
  - 技能存在，有活跃 InstanceGene → 删文件 + 软删 IG + install_count-1 + 记录 evolution
  - 技能存在，无 InstanceGene → 删文件 + 记录 evolution（不出错）
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class _FakeGene:
    def __init__(self, gene_id: str, slug: str, install_count: int = 3):
        self.id = gene_id
        self.slug = slug
        self.name = f"Gene {slug}"
        self.manifest = None
        self.install_count = install_count


class _FakeInstanceGene:
    def __init__(self, ig_id: str, gene_id: str):
        self.id = ig_id
        self.gene_id = gene_id
        self.installed_version = "1.0.0"
        self.usage_count = 5
        self._deleted = False

    def soft_delete(self) -> None:
        self._deleted = True


class _FakeInstance:
    def __init__(self):
        self.id = "inst-1"
        self.runtime = "openclaw"


def _make_db(gene: _FakeGene | None, ig: _FakeInstanceGene | None) -> AsyncMock:
    """构造 mock db，按 delete_skill_by_name 的查询顺序返回预设值。

    查询顺序：
      1. select(InstanceGene, Gene) — 按 gene.slug == skill_name 找 IG
    """
    db = AsyncMock()
    db.commit = AsyncMock()
    db.add = MagicMock()

    ig_gene_result = MagicMock()
    if ig is not None and gene is not None:
        ig_gene_result.first.return_value = (ig, gene)
    else:
        ig_gene_result.first.return_value = None
    db.execute = AsyncMock(return_value=ig_gene_result)
    return db


@pytest.mark.asyncio
async def test_delete_skill_with_instance_gene():
    """技能有活跃 InstanceGene → 软删 IG，install_count 递减，提交。"""
    from app.services.gene_service import delete_skill_by_name

    gene = _FakeGene("gene-1", "my-skill", install_count=3)
    ig = _FakeInstanceGene("ig-1", "gene-1")
    instance = _FakeInstance()
    db = _make_db(gene, ig)

    mock_fs = AsyncMock()
    mock_adapter = MagicMock()
    mock_adapter.remove_skill = AsyncMock()
    mock_adapter.post_remove_cleanup = AsyncMock()

    # _fire_task 用 side_effect=lambda c: c.close() 防止 unawaited coroutine 警告
    with (
        patch("app.services.gene_service.get_instance", AsyncMock(return_value=instance)),
        patch("app.services.gene_service._get_gene_install_adapter", return_value=mock_adapter),
        patch("app.services.gene_service.remote_fs") as mock_rfs,
        patch("app.services.gene_service._record_evolution", AsyncMock()),
        patch("app.services.gene_service._fire_task", side_effect=lambda c: c.close()),
        patch("app.services.gene_service._get_instance_workspace_ids", AsyncMock(return_value=[])),
    ):
        mock_rfs.return_value.__aenter__ = AsyncMock(return_value=mock_fs)
        mock_rfs.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await delete_skill_by_name(db, "inst-1", "my-skill", org_id=None)

    assert result == {"deleted": True, "skill_name": "my-skill"}
    mock_adapter.remove_skill.assert_awaited_once_with(mock_fs, "my-skill")
    mock_adapter.post_remove_cleanup.assert_awaited_once_with(mock_fs, "my-skill")
    assert ig._deleted is True
    assert gene.install_count == 2  # 3 - 1
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_delete_skill_without_instance_gene():
    """技能无 InstanceGene → 只删文件，不报错。"""
    from app.services.gene_service import delete_skill_by_name

    instance = _FakeInstance()
    db = _make_db(gene=None, ig=None)

    mock_fs = AsyncMock()
    mock_adapter = MagicMock()
    mock_adapter.remove_skill = AsyncMock()
    mock_adapter.post_remove_cleanup = AsyncMock()

    with (
        patch("app.services.gene_service.get_instance", AsyncMock(return_value=instance)),
        patch("app.services.gene_service._get_gene_install_adapter", return_value=mock_adapter),
        patch("app.services.gene_service.remote_fs") as mock_rfs,
        patch("app.services.gene_service._record_evolution", AsyncMock()),
        patch("app.services.gene_service._fire_task", side_effect=lambda c: c.close()),
        patch("app.services.gene_service._get_instance_workspace_ids", AsyncMock(return_value=[])),
    ):
        mock_rfs.return_value.__aenter__ = AsyncMock(return_value=mock_fs)
        mock_rfs.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await delete_skill_by_name(db, "inst-1", "emerged-skill", org_id=None)

    assert result == {"deleted": True, "skill_name": "emerged-skill"}
    mock_adapter.remove_skill.assert_awaited_once_with(mock_fs, "emerged-skill")
    mock_adapter.post_remove_cleanup.assert_awaited_once_with(mock_fs, "emerged-skill")
    db.commit.assert_awaited()
