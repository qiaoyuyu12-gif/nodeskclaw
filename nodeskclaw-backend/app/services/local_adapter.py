"""Local database adapter — queries PostgreSQL genes table directly.

Core adapter for pure local mode: when no external registries are configured,
this is the only adapter in the aggregator and provides full functionality
with zero network dependency.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.base import not_deleted
from app.models.gene import Gene
from app.services.registry_adapter import (
    RegistryAdapter,
    RegistrySearchResult,
    RegistrySkillDetail,
    RegistrySkillItem,
)

logger = logging.getLogger(__name__)


def _json_loads(raw: str | None) -> list | dict | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _gene_to_item(gene: Gene) -> RegistrySkillItem:
    return RegistrySkillItem(
        slug=gene.slug,
        name=gene.name,
        description=gene.description,
        short_description=gene.short_description,
        version=gene.version,
        tags=_json_loads(gene.tags) or [],
        category=gene.category,
        source=gene.source,
        source_ref=gene.source_ref,
        icon=gene.icon,
        install_count=gene.install_count,
        avg_rating=gene.avg_rating,
        effectiveness_score=gene.effectiveness_score,
        is_featured=gene.is_featured,
        review_status=gene.review_status,
        is_published=gene.is_published,
        manifest=_json_loads(gene.manifest),
        dependencies=_json_loads(gene.dependencies) or [],
        synergies=_json_loads(gene.synergies) or [],
        parent_gene_id=gene.parent_gene_id,
        created_by_instance_id=gene.created_by_instance_id,
        created_by=gene.created_by,
        org_id=gene.org_id,
        visibility=getattr(gene, "visibility", "public"),
        created_at=gene.created_at,
        updated_at=gene.updated_at,
        source_registry="local",
        source_registry_name="本地",
        local_id=gene.id,
    )


class LocalAdapter(RegistryAdapter):
    """Adapter that queries the local PostgreSQL ``genes`` table."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        super().__init__(
            registry_id="local",
            registry_name="本地",
            base_url=None,
        )
        self._session_factory = session_factory

    async def search_skills(
        self,
        *,
        keyword: str | None = None,
        tag: str | None = None,
        category: str | None = None,
        source: str | None = None,
        visibility: str | None = None,
        org_id: str | None = None,
        sort: str = "popularity",
        page: int = 1,
        page_size: int = 20,
    ) -> RegistrySearchResult | None:
        # 个人 library 不通过聚合器查询（personal 走 gene_service._list_genes_local 直查）
        if visibility == "personal":
            return RegistrySearchResult(items=[], total=0)

        async with self._session_factory() as db:
            base = select(Gene).where(not_deleted(Gene), Gene.is_published.is_(True))

            if visibility == "org_private":
                base = base.where(Gene.visibility == "org_private", Gene.org_id == org_id)
            elif visibility == "public":
                # 公共市场：审核通过 OR 历史无审核态（review_status IS NULL，兼容老数据）
                base = base.where(
                    Gene.visibility == "public",
                    or_(
                        Gene.review_status == "approved",
                        Gene.review_status.is_(None),
                    ),
                )
            elif org_id:
                base = base.where(
                    or_(
                        and_(
                            Gene.visibility == "public",
                            or_(
                                Gene.review_status == "approved",
                                Gene.review_status.is_(None),
                            ),
                        ),
                        and_(Gene.visibility == "org_private", Gene.org_id == org_id),
                    )
                )

            if keyword:
                base = base.where(
                    Gene.name.ilike(f"%{keyword}%") | Gene.slug.ilike(f"%{keyword}%")
                )
            if tag:
                base = base.where(Gene.tags.ilike(f'%"{tag}"%'))
            if category:
                base = base.where(Gene.category == category)
            if source:
                base = base.where(Gene.source == source)

            count_q = select(func.count()).select_from(base.subquery())
            total = (await db.execute(count_q)).scalar() or 0

            sort_map = {
                "popularity": Gene.install_count.desc(),
                "rating": Gene.avg_rating.desc(),
                "effectiveness": Gene.effectiveness_score.desc(),
                "newest": Gene.created_at.desc(),
            }
            base = base.order_by(sort_map.get(sort, Gene.install_count.desc()))
            base = base.offset((page - 1) * page_size).limit(page_size)

            result = await db.execute(base)
            genes = result.scalars().all()
            items = [_gene_to_item(g) for g in genes]
            return RegistrySearchResult(items=items, total=total)

    async def get_skill(self, slug: str) -> RegistrySkillDetail | None:
        async with self._session_factory() as db:
            # fork 三向后同 slug 可在 personal/org/public 多 scope 并存
            # （DB partial unique index 是 `(slug, org_id)`）。这里只用于
            # 详情页"按 slug 拿任一条"的 fallback，所以用 .first() 兜底，
            # 避免 MultipleResultsFound 把 aggregator 整条链路吞成 None。
            stmt = select(Gene).where(not_deleted(Gene), Gene.slug == slug)
            result = await db.execute(stmt)
            gene = result.scalars().first()
            if not gene:
                return None
            item = _gene_to_item(gene)
            return RegistrySkillDetail(**item.model_dump())

    async def get_manifest(self, slug: str, version: str | None = None) -> dict | None:
        async with self._session_factory() as db:
            # 同上：多 scope 同 slug 时取首条 manifest，避免 MultipleResultsFound
            stmt = select(Gene.manifest).where(not_deleted(Gene), Gene.slug == slug)
            result = await db.execute(stmt)
            raw = result.scalars().first()
            return _json_loads(raw) if raw else None

    async def get_featured(self, limit: int = 10) -> list[RegistrySkillItem] | None:
        async with self._session_factory() as db:
            stmt = (
                select(Gene)
                .where(not_deleted(Gene), Gene.is_published.is_(True))
                .order_by(Gene.install_count.desc())
                .limit(limit)
            )
            result = await db.execute(stmt)
            genes = result.scalars().all()
            return [_gene_to_item(g) for g in genes]

    async def get_tags(self) -> list[dict] | None:
        async with self._session_factory() as db:
            stmt = select(Gene.tags).where(
                not_deleted(Gene),
                Gene.is_published.is_(True),
                Gene.tags.isnot(None),
            )
            result = await db.execute(stmt)
            all_tags: dict[str, int] = {}
            for (raw_tags,) in result.all():
                parsed = _json_loads(raw_tags)
                if isinstance(parsed, list):
                    for t in parsed:
                        if isinstance(t, str) and t:
                            all_tags[t] = all_tags.get(t, 0) + 1
            return [{"tag": k, "count": v} for k, v in sorted(all_tags.items(), key=lambda x: -x[1])]

    async def get_synergies(self, slug: str) -> list[dict] | None:
        async with self._session_factory() as db:
            stmt = select(Gene.synergies).where(not_deleted(Gene), Gene.slug == slug)
            result = await db.execute(stmt)
            # 多 scope 同 slug 并存时取首条，避免 MultipleResultsFound
            raw = result.scalars().first()
            parsed = _json_loads(raw) if raw else None
            return parsed if isinstance(parsed, list) else None

    async def publish_skill(self, manifest: dict) -> dict | None:
        return None

    async def report_install(self, slug: str) -> bool:
        async with self._session_factory() as db:
            stmt = select(Gene).where(not_deleted(Gene), Gene.slug == slug)
            result = await db.execute(stmt)
            # 多 scope 同 slug 并存时给首条记账即可（install_count 是聚合量）
            gene = result.scalars().first()
            if gene:
                gene.install_count = (gene.install_count or 0) + 1
                await db.commit()
                return True
            return False

    async def report_effectiveness(
        self, slug: str, metric_type: str, value: float
    ) -> bool:
        return False
