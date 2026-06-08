"""验证两个紧急修复的回归保护：

1. local_adapter.get_skill / get_manifest 在多 scope 同 slug 时不再抛
   MultipleResultsFound（commit e57b168 修了 gene_service 同名函数，
   但当时 adapter 路径漏改 → 详情页拿不到 personal gene 显示空白）。
2. _test_docker_connection 在 Windows SelectorEventLoop（asyncio
   subprocess 抛 NotImplementedError）时回退到同步 subprocess，避免
   被通用 except Exception 吞成 message=""，前端 toast 显示「连接失败:」。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import BadRequestError


# ─── 1. local_adapter 多 scope 同 slug 不再 500 ───────────────────────


@pytest.mark.asyncio
async def test_local_adapter_get_skill_uses_first_when_multiple_rows():
    """同 slug 在 personal/org/public 三 scope 并存时，local adapter 必须
    用 .scalars().first() 兜底，不能再用 scalar_one_or_none()。
    """
    from app.services import local_adapter as la_module

    # 准备一条最小可用 Gene 行（用 MagicMock 即可，_gene_to_item 会读字段）
    gene = MagicMock()
    gene.id = "g-1"
    gene.slug = "skill-x"
    gene.name = "Skill X"
    gene.description = "desc"
    gene.short_description = "short"
    gene.category = None
    gene.tags = None
    gene.icon = None
    gene.version = "1.0.0"
    gene.manifest = None
    gene.dependencies = None
    gene.synergies = None
    gene.install_count = 0
    gene.avg_rating = 0.0
    gene.is_featured = False
    gene.parent_gene_id = None
    gene.created_by_instance_id = None
    gene.org_id = None
    gene.visibility = "personal"
    gene.review_status = None
    gene.is_published = True
    gene.created_by = "u-1"
    gene.created_at = None
    gene.updated_at = None
    gene.source_ref = None
    gene.source = "manual"
    gene.effectiveness_score = 0.0

    # 构造 db.execute 返回：scalars().first() = gene；
    # scalar_one_or_none 显式抛错以便发现回退到旧实现
    from sqlalchemy.exc import MultipleResultsFound

    scalars = MagicMock()
    scalars.first.return_value = gene
    result = MagicMock()
    result.scalars.return_value = scalars
    result.scalar_one_or_none.side_effect = MultipleResultsFound(
        "must not be called",
    )

    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)

    # 模拟 async with self._session_factory() as db: ...
    @asynccontextmanager
    async def fake_factory():
        yield db

    adapter = la_module.LocalAdapter(session_factory=fake_factory)

    # 用一个尽量薄的 _gene_to_item 替身，避免依赖项目内复杂序列化逻辑
    with patch.object(la_module, "_gene_to_item", return_value=MagicMock(
        model_dump=MagicMock(return_value={
            "slug": "skill-x", "name": "Skill X", "description": "desc",
            "short_description": "short", "category": None, "tags": [],
            "icon": None, "version": "1.0.0", "manifest": {},
            "dependencies": [], "synergies": [], "install_count": 0,
            "avg_rating": 0.0, "is_featured": False, "parent_gene_id": None,
            "created_by_instance_id": None, "org_id": None,
            "visibility": "personal", "review_status": None,
            "is_published": True, "created_by": "u-1", "created_at": None,
            "updated_at": None, "source_ref": None, "source": "manual",
            "effectiveness_score": 0.0, "source_registry": "local",
            "source_registry_name": "local", "local_id": "g-1",
        }),
    )):
        detail = await adapter.get_skill("skill-x")

    assert detail is not None
    scalars.first.assert_called_once()
    result.scalar_one_or_none.assert_not_called()


# ─── 2. _test_docker_connection 在 Windows 下回退同步路径 ─────────────


@pytest.mark.asyncio
async def test_test_docker_connection_falls_back_on_not_implemented():
    """asyncio.create_subprocess_exec 抛 NotImplementedError 时，应该走
    _probe_docker_sync 兜底；探测成功 → ok=True。绝不能被通用 except
    Exception 吞成 message=""。
    """
    from app.services import cluster_service as cs

    cluster = MagicMock()
    cluster.compute_provider = "docker"
    db = AsyncMock()

    async def _raise_not_implemented(*_args, **_kwargs):
        raise NotImplementedError()

    async def _probe_ok():
        return None  # 同步路径成功

    with patch.object(cs.asyncio, "create_subprocess_exec", side_effect=_raise_not_implemented), \
         patch.object(cs, "_probe_docker_sync", side_effect=_probe_ok):
        result = await cs._test_docker_connection(cluster, db)

    assert result.ok is True
    assert result.message is None or "" not in (result.message or "")


@pytest.mark.asyncio
async def test_test_docker_connection_propagates_sync_probe_error():
    """同步回退失败时，BadRequestError.message 应该原样回传给前端，
    不能再次被吞成空字符串。"""
    from app.services import cluster_service as cs

    cluster = MagicMock()
    cluster.compute_provider = "docker"
    db = AsyncMock()

    async def _raise_not_implemented(*_args, **_kwargs):
        raise NotImplementedError()

    async def _probe_fail():
        raise BadRequestError(
            message="无法连接 Docker daemon，请确认 Docker Desktop 正在运行",
            message_key="errors.cluster.docker_socket_unavailable",
        )

    with patch.object(cs.asyncio, "create_subprocess_exec", side_effect=_raise_not_implemented), \
         patch.object(cs, "_probe_docker_sync", side_effect=_probe_fail):
        result = await cs._test_docker_connection(cluster, db)

    assert result.ok is False
    assert "Docker daemon" in (result.message or "")
