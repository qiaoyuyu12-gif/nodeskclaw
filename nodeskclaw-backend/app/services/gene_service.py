"""Gene Evolution Ecosystem service: CRUD, install/learn engine, rating, evolution."""

import asyncio
import hashlib
import hmac
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Coroutine
from urllib.parse import urlencode

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_nodeskclaw_webhook_base_url, settings
from app.core.exceptions import AppException, BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.models.base import not_deleted
from app.models.corridor import HumanHex
from app.models.gene import (
    EffectMetricType,
    EvolutionEvent,
    EvolutionEventType,
    Gene,
    GeneEffectLog,
    GeneRating,
    GeneReviewStatus,
    GeneSource,
    Genome,
    GenomeRating,
    InstanceGene,
    InstanceGeneStatus,
)
from app.models.instance import Instance, InstanceStatus
from app.models.workspace_agent import WorkspaceAgent
from app.schemas.gene import (
    CoInstallPair,
    GeneCreateRequest,
    GeneStatsResponse,
    GenomeCreateRequest,
    LearningCallbackPayload,
    TagStats,
    UpdateGeneRequest,
    UpdateGenomeRequest,
)
from app.services.registry_aggregator import get_aggregator
from app.services.nfs_mount import RemoteFS, SkillScanError, remote_fs
from app.services.runtime.gene_install_adapter import GeneInstallAdapter

logger = logging.getLogger(__name__)


def _get_gene_install_adapter(runtime: str) -> GeneInstallAdapter:
    """Get the GeneInstallAdapter for a given runtime, falling back to NoopGeneInstallAdapter."""
    from app.services.runtime.registries.runtime_registry import RUNTIME_REGISTRY

    spec = RUNTIME_REGISTRY.get(runtime)
    if spec and spec.gene_install_adapter:
        return spec.gene_install_adapter
    from app.services.runtime.noop_gene_install_adapter import NoopGeneInstallAdapter
    return NoopGeneInstallAdapter()


async def _get_instance_workspace_ids(db: AsyncSession, instance_id: str) -> list[str]:
    """Get all workspace IDs for an instance."""
    result = await db.execute(
        select(WorkspaceAgent.workspace_id).where(
            WorkspaceAgent.instance_id == instance_id,
            WorkspaceAgent.deleted_at.is_(None),
        )
    )
    return [row[0] for row in result.all()]


_background_tasks: set[asyncio.Task] = set()


def _fire_task(coro: Coroutine) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


@asynccontextmanager
async def _instance_pg_advisory_lock(instance_id: str):
    """PostgreSQL advisory lock scoped to an instance, for serializing NFS operations.

    Uses session-level pg_advisory_lock/pg_advisory_unlock on a dedicated connection
    so the lock is held across the entire async block regardless of transaction boundaries.
    """
    from app.core.deps import async_session_factory

    lock_key = hash(instance_id) % (2**31)
    async with async_session_factory() as lock_db:
        await lock_db.execute(text("SELECT pg_advisory_lock(:key)"), {"key": lock_key})
        try:
            yield
        finally:
            await lock_db.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock_key})


def _json_loads(raw: str | None) -> list | dict | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _json_dumps(obj) -> str | None:
    if obj is None:
        return None
    return json.dumps(obj, ensure_ascii=False)


def _gene_callback_secret() -> str:
    return settings.GENE_CALLBACK_SECRET or settings.JWT_SECRET


def sign_gene_callback(task_id: str, instance_id: str, mode: str) -> str:
    payload = f"{task_id}:{instance_id}:{mode}"
    return hmac.new(
        _gene_callback_secret().encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()


def verify_gene_callback_signature(payload: LearningCallbackPayload, mode: str, sig: str) -> bool:
    expected = sign_gene_callback(payload.task_id, payload.instance_id, mode)
    return hmac.compare_digest(expected, sig)


def build_gene_callback_url(base_url: str, path: str, task_id: str, instance_id: str, mode: str) -> str:
    params = urlencode({
        "instance_id": instance_id,
        "sig": sign_gene_callback(task_id, instance_id, mode),
    })
    return f"{base_url}{path}?{params}"


def _truncate_text(text: str, limit: int = 120) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _build_skill_summary(gene_obj: Gene) -> str:
    raw = (gene_obj.short_description or gene_obj.description or "").strip()
    if not raw:
        return ""
    return _truncate_text(raw)


async def _notify_skill_learned_in_workspace(
    db: AsyncSession,
    *,
    instance: Instance,
    gene_obj: Gene,
    workspace_id: str | None,
) -> None:
    if not workspace_id:
        return

    try:
        from app.api.workspaces import broadcast_event
        from app.services.collaboration_service import (
            deliver_to_human,
            send_system_message_to_agents,
        )
        from app.services.corridor_router import get_agent_hex_in_workspace, get_reachable_endpoints

        hex_pos = await get_agent_hex_in_workspace(instance.id, workspace_id, db)
        if hex_pos is None:
            return

        reachable, _hooks = await get_reachable_endpoints(
            workspace_id, hex_pos[0], hex_pos[1], db,
        )
        if not reachable:
            return

        agent_ids: list[str] = []
        human_hex_ids: list[str] = []
        for endpoint in reachable:
            if endpoint.endpoint_type == "agent":
                if endpoint.entity_id and endpoint.entity_id != instance.id and endpoint.entity_id not in agent_ids:
                    agent_ids.append(endpoint.entity_id)
            elif endpoint.endpoint_type == "human":
                if endpoint.entity_id and endpoint.entity_id not in human_hex_ids:
                    human_hex_ids.append(endpoint.entity_id)

        audience_user_ids: list[str] = []
        if human_hex_ids:
            human_q = await db.execute(
                select(HumanHex.id, HumanHex.user_id).where(
                    HumanHex.id.in_(human_hex_ids),
                    not_deleted(HumanHex),
                )
            )
            user_id_by_hex = {row.id: row.user_id for row in human_q.all()}
            audience_user_ids = [
                user_id_by_hex[human_hex_id]
                for human_hex_id in human_hex_ids
                if user_id_by_hex.get(human_hex_id)
            ]

        if not agent_ids and not human_hex_ids:
            return

        agent_name = instance.agent_display_name or instance.name
        summary = _build_skill_summary(gene_obj)
        skill_label = f"{gene_obj.name}（{gene_obj.slug}）"
        human_message = f"我刚学会了 {skill_label}。"
        if summary:
            human_message += f" 主要用于：{summary}"

        agent_message = f"系统通知：{agent_name} 刚学会了 {skill_label}。"
        if summary:
            agent_message += f" 主要用于：{summary}。"
        agent_message += " 仅同步技能变化，无需回复；如无补充请回复 NO_REPLY。"

        for human_hex_id in human_hex_ids:
            try:
                await deliver_to_human(
                    workspace_id=workspace_id,
                    human_hex_id=human_hex_id,
                    source_name=agent_name,
                    message=human_message,
                )
            except Exception as exc:
                logger.warning(
                    "技能学习通知 human 失败 workspace=%s instance=%s human_hex=%s err=%s",
                    workspace_id,
                    instance.id,
                    human_hex_id,
                    exc,
                )

        if agent_ids:
            try:
                await send_system_message_to_agents(
                    workspace_id,
                    agent_ids,
                    agent_message,
                    db,
                )
            except Exception as exc:
                logger.warning(
                    "技能学习通知 agents 失败 workspace=%s instance=%s err=%s",
                    workspace_id,
                    instance.id,
                    exc,
                )

        if audience_user_ids:
            broadcast_event(workspace_id, "agent:skill_learned", {
                "instance_id": instance.id,
                "agent_name": agent_name,
                "gene_name": gene_obj.name,
                "gene_slug": gene_obj.slug,
                "summary": summary,
                "audience_user_ids": audience_user_ids,
            })
    except Exception as exc:
        logger.warning(
            "技能学习工作区通知失败 workspace=%s instance=%s gene=%s err=%s",
            workspace_id,
            instance.id,
            gene_obj.slug,
            exc,
        )


async def _record_evolution(
    db: AsyncSession,
    instance_id: str,
    event_type: EvolutionEventType,
    gene_name: str,
    gene_slug: str | None = None,
    gene_id: str | None = None,
    genome_id: str | None = None,
    details: dict | None = None,
) -> None:
    ev = EvolutionEvent(
        instance_id=instance_id,
        gene_id=gene_id,
        genome_id=genome_id,
        event_type=event_type.value,
        gene_name=gene_name,
        gene_slug=gene_slug,
        details=_json_dumps(details),
    )
    db.add(ev)


def _has_frontmatter(content: str) -> bool:
    """Check whether SKILL.md content begins with YAML front matter (``---``)."""
    return content.lstrip().startswith("---")


def _parse_skill_frontmatter(content: str) -> dict:
    """Extract YAML front matter from SKILL.md content as a dict."""
    import yaml

    stripped = content.lstrip()
    if not stripped.startswith("---"):
        return {}
    end = stripped.find("\n---", 3)
    if end == -1:
        return {}
    try:
        return yaml.safe_load(stripped[3:end]) or {}
    except Exception:
        return {}


def _skill_body(content: str) -> str:
    """Return the body of SKILL.md (everything after front matter)."""
    stripped = content.lstrip()
    if not stripped.startswith("---"):
        return content
    end = stripped.find("\n---", 3)
    if end == -1:
        return content
    return stripped[end + 4:].lstrip()


def _validate_skill_metadata(
    manifest: dict | None,
    short_description: str | None,
    description: str | None,
) -> None:
    """Reject gene creation when skill metadata is insufficient for runtime discovery.

    Most runtimes require YAML front matter (name + description) in SKILL.md.
    Either the skill content must already include front matter, or the gene
    must provide a description so the adapter can generate it during deployment.
    """
    if not manifest or "skill" not in manifest:
        return
    skill = manifest["skill"]
    content = skill.get("content", "")
    if _has_frontmatter(content):
        return
    if not (short_description or description):
        raise BadRequestError(
            "带 skill 的基因必须提供 short_description 或 description"
            "（OpenClaw 需要 YAML front matter 中的 description 字段来发现 skill）",
        )


def _gene_to_dict(gene: Gene) -> dict:
    return {
        "id": gene.id,
        "name": gene.name,
        "slug": gene.slug,
        "description": gene.description,
        "short_description": gene.short_description,
        "category": gene.category,
        "tags": _json_loads(gene.tags) or [],
        "source": gene.source,
        "source_ref": gene.source_ref,
        "icon": gene.icon,
        "version": gene.version,
        "manifest": _json_loads(gene.manifest),
        "dependencies": _json_loads(gene.dependencies) or [],
        "synergies": _json_loads(gene.synergies) or [],
        "parent_gene_id": gene.parent_gene_id,
        "created_by_instance_id": gene.created_by_instance_id,
        "install_count": gene.install_count,
        "avg_rating": gene.avg_rating,
        "effectiveness_score": gene.effectiveness_score,
        "is_featured": gene.is_featured,
        "review_status": gene.review_status,
        "is_published": gene.is_published,
        "created_by": gene.created_by,
        "org_id": gene.org_id,
        "visibility": getattr(gene, "visibility", "public"),
        "source_registry": getattr(gene, "source_registry", None),
        "created_at": gene.created_at,
        "updated_at": gene.updated_at,
    }


def _registry_item_to_dict(item) -> dict:
    """Convert a RegistrySkillItem to the dict format expected by frontends."""
    return {
        "id": item.local_id or item.slug,
        "name": item.name,
        "slug": item.slug,
        "description": item.description,
        "short_description": item.short_description,
        "category": item.category,
        "tags": item.tags or [],
        "source": item.source,
        "source_ref": item.source_ref,
        "icon": item.icon,
        "version": item.version or "",
        "manifest": item.manifest,
        "dependencies": item.dependencies or [],
        "synergies": item.synergies or [],
        "parent_gene_id": item.parent_gene_id,
        "created_by_instance_id": item.created_by_instance_id,
        "install_count": item.install_count,
        "avg_rating": item.avg_rating,
        "effectiveness_score": item.effectiveness_score,
        "is_featured": item.is_featured,
        "review_status": item.review_status,
        "is_published": item.is_published,
        "created_by": item.created_by,
        "org_id": item.org_id,
        "visibility": item.visibility,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "source_registry": item.source_registry,
        "source_registry_name": item.source_registry_name,
    }


def _genome_to_dict(genome: Genome) -> dict:
    return {
        "id": genome.id,
        "name": genome.name,
        "slug": genome.slug,
        "description": genome.description,
        "short_description": genome.short_description,
        "icon": genome.icon,
        "gene_slugs": _json_loads(genome.gene_slugs) or [],
        "config_override": _json_loads(genome.config_override),
        "install_count": genome.install_count,
        "avg_rating": genome.avg_rating,
        "is_featured": genome.is_featured,
        "is_published": genome.is_published,
        "created_by": genome.created_by,
        "org_id": genome.org_id,
        "created_at": genome.created_at,
    }


async def _enrich_genomes_tool_counts(db: AsyncSession, genome_dicts: list[dict]) -> list[dict]:
    all_slugs: set[str] = set()
    for gd in genome_dicts:
        all_slugs.update(gd.get("gene_slugs") or [])
    if not all_slugs:
        for gd in genome_dicts:
            gd["native_tool_count"] = 0
            gd["mcp_server_count"] = 0
        return genome_dicts

    result = await db.execute(
        select(Gene.slug, Gene.manifest).where(Gene.slug.in_(list(all_slugs)), not_deleted(Gene))
    )
    slug_tools: dict[str, tuple[int, int]] = {}
    for slug, manifest_raw in result.all():
        m = _json_loads(manifest_raw) if isinstance(manifest_raw, str) else (manifest_raw or {})
        ta = m.get("tool_allow", [])
        ms = m.get("mcp_servers", [])
        slug_tools[slug] = (
            len(ta) if isinstance(ta, list) else 0,
            len(ms) if isinstance(ms, list) else 0,
        )

    for gd in genome_dicts:
        native = 0
        mcp = 0
        for s in gd.get("gene_slugs") or []:
            counts = slug_tools.get(s, (0, 0))
            native += counts[0]
            mcp += counts[1]
        gd["native_tool_count"] = native
        gd["mcp_server_count"] = mcp
    return genome_dicts


# ═══════════════════════════════════════════════════
#  CRUD + Market Query
# ═══════════════════════════════════════════════════


async def _list_genes_local(
    db: AsyncSession,
    *,
    keyword: str | None = None,
    tag: str | None = None,
    category: str | None = None,
    source: str | None = None,
    visibility: str | None = None,
    org_id: str | None = None,
    user_id: str | None = None,
    sort: str = "popularity",
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    base = select(Gene).where(not_deleted(Gene), Gene.is_published.is_(True))

    if visibility == "personal":
        # 个人 library：必须按 created_by 过滤；user_id 为空时返回空集（避免越权）
        if not user_id:
            return [], 0
        base = base.where(Gene.visibility == "personal", Gene.created_by == user_id)
    elif visibility == "org_private":
        base = base.where(Gene.visibility == "org_private", Gene.org_id == org_id)
    elif visibility == "public":
        # 公共市场：审核通过 OR 历史无审核态（review_status IS NULL，向后兼容老数据）
        # 仅排除 pending_* / rejected 状态
        base = base.where(
            Gene.visibility == "public",
            or_(
                Gene.review_status == GeneReviewStatus.approved,
                Gene.review_status.is_(None),
            ),
        )
    elif org_id:
        base = base.where(
            or_(
                and_(
                    Gene.visibility == "public",
                    or_(
                        Gene.review_status == GeneReviewStatus.approved,
                        Gene.review_status.is_(None),
                    ),
                ),
                and_(Gene.visibility == "org_private", Gene.org_id == org_id),
            )
        )

    if keyword:
        base = base.where(Gene.name.ilike(f"%{keyword}%") | Gene.slug.ilike(f"%{keyword}%"))
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
    return [_gene_to_dict(g) for g in genes], total


async def list_genes(
    db: AsyncSession,
    *,
    keyword: str | None = None,
    tag: str | None = None,
    category: str | None = None,
    source: str | None = None,
    visibility: str | None = None,
    org_id: str | None = None,
    user_id: str | None = None,
    sort: str = "popularity",
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    # 个人 library 仅存在于本地 DB，不走聚合器（远程注册表没有个人数据）
    if visibility == "personal":
        return await _list_genes_local(
            db,
            keyword=keyword, tag=tag, category=category, source=source,
            visibility=visibility, org_id=org_id, user_id=user_id,
            sort=sort, page=page, page_size=page_size,
        )

    aggregator = get_aggregator()
    result = await aggregator.search(
        keyword=keyword, tag=tag, category=category, source=source,
        visibility=visibility, org_id=org_id,
        sort=sort, page=page, page_size=page_size,
    )
    items = [_registry_item_to_dict(item) for item in result.items]
    return items, result.total


async def get_gene(db: AsyncSession, slug: str) -> dict:
    aggregator = get_aggregator()
    detail = await aggregator.get_skill(slug)
    if not detail:
        raise NotFoundError("基因不存在")

    data = _registry_item_to_dict(detail)

    if detail.source_registry == "local" and detail.local_id:
        data["effectiveness_breakdown"] = await _get_effectiveness_breakdown(
            db, detail.local_id, detail.avg_rating
        )

    return data


async def get_gene_by_slug(db: AsyncSession, slug: str) -> Gene | None:
    """按 slug 返回任意一条未删除 gene。

    注意：在 fork 三向架构（personal/org/public）下，同一个 slug 可以在
    多个 scope 下并存（DB unique index 是 partial `(slug, org_id)`），
    所以这里只能用 `.first()` 取"任一条"。需要按 scope 精确定位时，
    请使用 get_gene_by_slug_in_scope。
    """
    result = await db.execute(
        select(Gene).where(Gene.slug == slug, not_deleted(Gene))
    )
    return result.scalars().first()


async def get_gene_by_slug_in_scope(
    db: AsyncSession,
    slug: str,
    *,
    org_id: str | None,
    created_by: str | None = None,
) -> Gene | None:
    """按 (slug, org_id) 精确定位一条未删除 gene，与 partial unique index 语义一致。

    - org_id 不为 None：组织或公共 scope，按 `slug + org_id + not_deleted` 唯一定位
    - org_id 为 None：personal scope。由于 unique index 在 org_id IS NULL 时
      不做唯一性约束（多个用户的同 slug personal 可并存），所以这里要按
      `created_by` 进一步限定为"该用户的 personal 同 slug"
    """
    stmt = select(Gene).where(Gene.slug == slug, not_deleted(Gene))
    if org_id is None:
        stmt = stmt.where(Gene.org_id.is_(None))
        if created_by is not None:
            stmt = stmt.where(Gene.created_by == created_by)
    else:
        stmt = stmt.where(Gene.org_id == org_id)
    result = await db.execute(stmt)
    return result.scalars().first()


async def create_gene(
    db: AsyncSession, req: GeneCreateRequest, user_id: str | None = None, org_id: str | None = None,
    visibility: str | None = None,
    review_status: str | None = None,
) -> dict:
    # 冲突判定按 (slug, org_id) 进行，对齐 partial unique index `uq_genes_slug_org_active`。
    # personal scope（org_id IS NULL）下，索引允许多个用户共用同 slug，因此用 created_by
    # 进一步限定到"当前用户的 personal 同 slug"，避免误报。
    existing = await get_gene_by_slug_in_scope(
        db, req.slug, org_id=org_id, created_by=user_id,
    )
    if existing:
        if req.overwrite:
            # 覆盖模式：软删除该 scope 内的旧基因，再创建新基因
            existing.soft_delete()
            await db.commit()
        else:
            raise ConflictError(f"基因 slug '{req.slug}' 已存在")

    _validate_skill_metadata(req.manifest, req.short_description, req.description)

    gene = Gene(
        name=req.name,
        slug=req.slug,
        description=req.description,
        short_description=req.short_description,
        category=req.category,
        tags=_json_dumps(req.tags),
        source=req.source,
        source_ref=req.source_ref,
        icon=req.icon,
        version=req.version,
        manifest=_json_dumps(req.manifest),
        dependencies=_json_dumps(req.dependencies),
        synergies=_json_dumps(req.synergies),
        is_featured=req.is_featured,
        is_published=req.is_published,
        visibility=visibility or req.visibility,
        review_status=review_status,
        created_by=user_id,
        org_id=org_id,
        # 标记为本地创建，确保前端"删除/编辑"等仅对本地 gene 显示的入口可见
        # （外部 registry 同步走 genehub_client，自带 registry_id；不进此路径）
        source_registry="local",
    )
    db.add(gene)
    await db.commit()
    await db.refresh(gene)
    return _gene_to_dict(gene)


async def get_gene_tags(db: AsyncSession) -> list[TagStats]:
    aggregator = get_aggregator()
    tags = await aggregator.get_tags()
    return [TagStats(tag=t.get("tag", ""), count=t.get("count", 0)) for t in tags]


async def get_featured_genes(db: AsyncSession, limit: int = 10) -> list[dict]:
    aggregator = get_aggregator()
    items = await aggregator.get_featured(limit)
    return [_registry_item_to_dict(item) for item in items]


async def get_gene_variants(db: AsyncSession, slug: str) -> list[dict]:
    gene = await get_gene_by_slug(db, slug)
    if not gene:
        return []
    result = await db.execute(
        select(Gene)
        .where(Gene.parent_gene_id == gene.id, not_deleted(Gene), Gene.is_published.is_(True))
        .order_by(Gene.effectiveness_score.desc())
    )
    return [_gene_to_dict(g) for g in result.scalars().all()]


async def get_gene_synergies(db: AsyncSession, slug: str) -> list[dict]:
    aggregator = get_aggregator()
    agg_synergies = await aggregator.get_synergies(slug)
    if agg_synergies is not None:
        return agg_synergies

    gene_obj = await get_gene_by_slug(db, slug)
    if not gene_obj:
        return []

    slugs = _json_loads(gene_obj.synergies) or []
    if not slugs:
        return []

    result = await db.execute(
        select(Gene).where(Gene.slug.in_(slugs), not_deleted(Gene), Gene.is_published.is_(True))
    )
    return [_gene_to_dict(g) for g in result.scalars().all()]


async def get_gene_genomes(db: AsyncSession, slug: str) -> list[dict]:
    """返回包含该基因的所有基因组（通过 gene_slugs JSON 数组匹配）。"""
    result = await db.execute(
        select(Genome).where(not_deleted(Genome), Genome.is_published.is_(True))
    )
    matched = []
    for g in result.scalars().all():
        gene_slugs = _json_loads(g.gene_slugs) or []
        if slug in gene_slugs:
            matched.append(_genome_to_dict(g))
    return await _enrich_genomes_tool_counts(db, matched)


# ── Genome CRUD ──────────────────────────────────


async def list_genomes(
    db: AsyncSession,
    *,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    base = select(Genome).where(not_deleted(Genome), Genome.is_published.is_(True))
    if keyword:
        base = base.where(Genome.name.ilike(f"%{keyword}%") | Genome.slug.ilike(f"%{keyword}%"))

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    base = base.order_by(Genome.install_count.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(base)
    items = await _enrich_genomes_tool_counts(db, [_genome_to_dict(g) for g in result.scalars().all()])
    return items, total


async def get_genome(db: AsyncSession, genome_id: str) -> dict:
    result = await db.execute(
        select(Genome).where(Genome.id == genome_id, not_deleted(Genome))
    )
    genome = result.scalar_one_or_none()
    if not genome:
        raise NotFoundError("基因组不存在")

    items = await _enrich_genomes_tool_counts(db, [_genome_to_dict(genome)])
    return items[0]


async def create_genome(
    db: AsyncSession, req: GenomeCreateRequest, user_id: str | None = None, org_id: str | None = None
) -> dict:
    genome = Genome(
        name=req.name,
        slug=req.slug,
        description=req.description,
        short_description=req.short_description,
        icon=req.icon,
        gene_slugs=_json_dumps(req.gene_slugs),
        config_override=_json_dumps(req.config_override),
        is_featured=req.is_featured,
        is_published=req.is_published,
        created_by=user_id,
        org_id=org_id,
    )
    db.add(genome)
    await db.commit()
    await db.refresh(genome)
    return _genome_to_dict(genome)


async def get_featured_genomes(db: AsyncSession, limit: int = 10) -> list[dict]:
    result = await db.execute(
        select(Genome)
        .where(not_deleted(Genome), Genome.is_published.is_(True), Genome.is_featured.is_(True))
        .order_by(Genome.install_count.desc())
        .limit(limit)
    )
    return await _enrich_genomes_tool_counts(db, [_genome_to_dict(g) for g in result.scalars().all()])


# ═══════════════════════════════════════════════════
#  Install / Learn Engine
# ═══════════════════════════════════════════════════


async def get_instance_genes(db: AsyncSession, instance_id: str, org_id: str | None = None) -> list[dict]:
    from app.services.instance_service import get_instance

    await get_instance(instance_id, db, org_id)
    q = (
        select(InstanceGene, Gene)
        .join(Gene, InstanceGene.gene_id == Gene.id)
        .where(
            InstanceGene.instance_id == instance_id,
            not_deleted(InstanceGene),
            Gene.deleted_at.is_(None),
        )
        .order_by(InstanceGene.created_at.desc())
    )
    result = await db.execute(q)
    rows = result.all()
    items = []
    for ig, gene in rows:
        d = {
            "id": ig.id,
            "instance_id": ig.instance_id,
            "gene_id": ig.gene_id,
            "genome_id": ig.genome_id,
            "status": ig.status,
            "installed_version": ig.installed_version,
            "learning_output": ig.learning_output,
            "config_snapshot": _json_loads(ig.config_snapshot),
            "agent_self_eval": ig.agent_self_eval,
            "usage_count": ig.usage_count,
            "variant_published": ig.variant_published,
            "installed_at": ig.installed_at,
            "created_at": ig.created_at,
            "gene": _gene_to_dict(gene),
        }
        items.append(d)
    return items


TRANSITIONAL_STATUSES = {
    InstanceGeneStatus.installing,
    InstanceGeneStatus.learning,
    InstanceGeneStatus.uninstalling,
    InstanceGeneStatus.forgetting,
}

STALE_TERMINAL_STATUSES = {
    InstanceGeneStatus.installed,
    InstanceGeneStatus.learn_failed,
    InstanceGeneStatus.failed,
    InstanceGeneStatus.simplified,
    InstanceGeneStatus.forget_failed,
}

CONTENT_PREVIEW_LEN = 200


def _ig_to_dict(ig: InstanceGene) -> dict:
    return {
        "id": ig.id,
        "instance_id": ig.instance_id,
        "gene_id": ig.gene_id,
        "genome_id": ig.genome_id,
        "status": ig.status,
        "installed_version": ig.installed_version,
        "learning_output": ig.learning_output,
        "config_snapshot": _json_loads(ig.config_snapshot),
        "agent_self_eval": ig.agent_self_eval,
        "usage_count": ig.usage_count,
        "variant_published": ig.variant_published,
        "installed_at": ig.installed_at,
        "created_at": ig.created_at,
    }


def _build_db_only_items(ig_rows: list) -> list[dict]:
    """DB-only 降级：scan_skills 失败时直接返回所有活跃 InstanceGene。"""
    items: list[dict] = []
    for ig, gene in ig_rows:
        manifest = _json_loads(gene.manifest) or {}
        skill_name = manifest.get("skill", {}).get("name", gene.slug)
        items.append({
            "type": "hub",
            "skill_name": skill_name,
            "name": gene.name,
            "description": gene.short_description or gene.description or "",
            "file_count": 0,
            "gene": _gene_to_dict(gene),
            "instance_gene": _ig_to_dict(ig),
        })
    return items


async def get_instance_skills(db: AsyncSession, instance_id: str, org_id: str | None = None) -> list[dict]:
    """Return the merged skill list driven by Pod filesystem + DB enrichment.

    Each item is typed ``hub`` (matched Gene Hub entry) or ``emerged``
    (only exists inside the Pod, not in the Hub).

    When ``scan_skills`` fails (SkillScanError), falls back to DB-only data
    without any stale-cleanup side effects.
    """
    from app.services.instance_service import get_instance

    instance = await get_instance(instance_id, db, org_id)

    ig_result = await db.execute(
        select(InstanceGene, Gene)
        .join(Gene, InstanceGene.gene_id == Gene.id)
        .where(
            InstanceGene.instance_id == instance_id,
            not_deleted(InstanceGene),
            Gene.deleted_at.is_(None),
        )
    )
    ig_rows = ig_result.all()

    from app.services.runtime.registries.runtime_registry import RUNTIME_REGISTRY
    spec = RUNTIME_REGISTRY.get(instance.runtime)
    skills_dir = spec.skills_dir_rel if spec else ".openclaw/skills"

    try:
        async with remote_fs(instance, db) as fs:
            pod_skills = await fs.scan_skills(skills_dir)
    except SkillScanError:
        logger.warning("scan_skills failed, returning DB-only data for %s", instance_id)
        return _build_db_only_items(ig_rows)

    pod_skill_names: set[str] = {s["name"] for s in pod_skills}

    skill_to_ig: dict[str, tuple[InstanceGene, Gene]] = {}
    for ig, gene in ig_rows:
        manifest = _json_loads(gene.manifest) or {}
        skill_name = manifest.get("skill", {}).get("name", gene.slug)
        skill_to_ig[skill_name] = (ig, gene)

    all_skill_names = list(pod_skill_names)
    gene_result = await db.execute(
        select(Gene).where(Gene.slug.in_(all_skill_names), not_deleted(Gene))
    )
    hub_genes: dict[str, Gene] = {g.slug: g for g in gene_result.scalars().all()}

    # Preload soft-deleted InstanceGenes for recovery (Fix C)
    deleted_result = await db.execute(
        select(InstanceGene)
        .where(InstanceGene.instance_id == instance_id, InstanceGene.deleted_at.is_not(None))
        .order_by(InstanceGene.deleted_at.desc())
    )
    deleted_ig_by_gene_id: dict[str, InstanceGene] = {}
    for dig in deleted_result.scalars().all():
        deleted_ig_by_gene_id.setdefault(dig.gene_id, dig)

    items: list[dict] = []
    seen_skill_names: set[str] = set()

    for skill_data in pod_skills:
        sname = skill_data["name"]
        content: str = skill_data.get("content", "")
        file_count: int = skill_data.get("file_count", 0)
        fm = _parse_skill_frontmatter(content)
        body = _skill_body(content)
        seen_skill_names.add(sname)

        ig_pair = skill_to_ig.get(sname)
        hub_gene = hub_genes.get(sname)
        if hub_gene is None and ig_pair is not None:
            hub_gene = ig_pair[1]

        if hub_gene is not None:
            ig_data = None
            if ig_pair:
                ig_data = _ig_to_dict(ig_pair[0])
            elif hub_gene.id in deleted_ig_by_gene_id:
                recovered = deleted_ig_by_gene_id[hub_gene.id]
                recovered.deleted_at = None
                logger.info(
                    "Recovered soft-deleted InstanceGene %s (gene=%s) — skill found in Pod",
                    recovered.id, hub_gene.slug,
                )
                ig_data = _ig_to_dict(recovered)
            items.append({
                "type": "hub",
                "skill_name": sname,
                "name": hub_gene.name,
                "description": hub_gene.short_description or hub_gene.description or "",
                "file_count": file_count,
                "gene": _gene_to_dict(hub_gene),
                "instance_gene": ig_data,
            })
        else:
            preview = body[:CONTENT_PREVIEW_LEN] + ("..." if len(body) > CONTENT_PREVIEW_LEN else "")
            items.append({
                "type": "emerged",
                "skill_name": sname,
                "name": fm.get("name", sname),
                "description": fm.get("description", ""),
                "file_count": file_count,
                "content_preview": preview,
                "full_content": content,
                "frontmatter": fm,
            })

    for sname, (ig, gene) in skill_to_ig.items():
        if sname in seen_skill_names:
            continue
        if ig.status in TRANSITIONAL_STATUSES:
            items.append({
                "type": "hub",
                "skill_name": sname,
                "name": gene.name,
                "description": gene.short_description or gene.description or "",
                "file_count": 0,
                "gene": _gene_to_dict(gene),
                "instance_gene": _ig_to_dict(ig),
            })
        elif ig.status in STALE_TERMINAL_STATUSES:
            logger.info(
                "Soft-deleting stale InstanceGene %s (gene=%s, status=%s) — skill not found in Pod",
                ig.id, gene.slug, ig.status,
            )
            ig.soft_delete()

    await db.commit()
    return items


async def get_gene_installed_instance_ids(db: AsyncSession, slug: str) -> list[str]:
    """Return instance IDs where this gene is currently installed."""
    gene = await get_gene_by_slug(db, slug)
    if not gene:
        return []
    result = await db.execute(
        select(InstanceGene.instance_id).where(
            InstanceGene.gene_id == gene.id,
            InstanceGene.status == InstanceGeneStatus.installed,
            not_deleted(InstanceGene),
        )
    )
    return [row[0] for row in result.all()]


async def _has_meta_learning(db: AsyncSession, instance_id: str) -> bool:
    """Check if instance has meta-learning gene installed."""
    result = await db.execute(
        select(InstanceGene)
        .join(Gene, InstanceGene.gene_id == Gene.id)
        .where(
            InstanceGene.instance_id == instance_id,
            Gene.slug == "meta-learning",
            InstanceGene.status == InstanceGeneStatus.installed,
            not_deleted(InstanceGene),
            Gene.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none() is not None


async def has_gene_installed(db: AsyncSession, instance_id: str, gene_slug: str) -> bool:
    """Check if instance has a specific gene installed (status=installed)."""
    result = await db.execute(
        select(InstanceGene.id)
        .join(Gene, InstanceGene.gene_id == Gene.id)
        .where(
            InstanceGene.instance_id == instance_id,
            Gene.slug == gene_slug,
            InstanceGene.status == InstanceGeneStatus.installed,
            not_deleted(InstanceGene),
            Gene.deleted_at.is_(None),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _has_pending_learning(db: AsyncSession, instance_id: str, exclude_ig_id: str) -> bool:
    """Check if the instance still has other InstanceGene records in learning status."""
    result = await db.execute(
        select(InstanceGene.id).where(
            InstanceGene.instance_id == instance_id,
            InstanceGene.status == InstanceGeneStatus.learning,
            InstanceGene.id != exclude_ig_id,
            not_deleted(InstanceGene),
        ).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _finish_learning_if_done(
    db: AsyncSession, instance_id: str, exclude_ig_id: str
) -> bool:
    """If no more genes are learning, restore instance status and return True (should restart)."""
    from app.services.instance_service import _broadcast_agent_status

    still_learning = await _has_pending_learning(db, instance_id, exclude_ig_id)
    if still_learning:
        return False

    instance = await db.get(Instance, instance_id)
    if instance and instance.status == InstanceStatus.learning:
        ws_ids = await _get_instance_workspace_ids(db, instance_id)
        _broadcast_agent_status(ws_ids, instance_id, "restarting")
    return True


async def install_gene(
    db: AsyncSession,
    instance_id: str,
    gene_slug: str,
    genome_id: str | None = None,
    org_id: str | None = None,
) -> dict:
    from app.api.workspaces import broadcast_event
    from app.services.instance_service import get_instance

    instance = await get_instance(instance_id, db, org_id)

    gene = await get_gene_by_slug(db, gene_slug)

    if not gene:
        raise NotFoundError(f"基因 '{gene_slug}' 不存在")

    result = await db.execute(
        select(InstanceGene).where(
            InstanceGene.instance_id == instance_id,
            InstanceGene.gene_id == gene.id,
            not_deleted(InstanceGene),
        )
    )
    existing_ig = result.scalar_one_or_none()
    if existing_ig:
        if existing_ig.status in (
            InstanceGeneStatus.installing,
            InstanceGeneStatus.learning,
            InstanceGeneStatus.failed,
            InstanceGeneStatus.learn_failed,
        ):
            existing_ig.soft_delete()
            await db.commit()
        else:
            raise ConflictError(f"基因 '{gene_slug}' 已学习")

    has_learning = await _has_meta_learning(db, instance_id)

    ig = InstanceGene(
        instance_id=instance_id,
        gene_id=gene.id,
        genome_id=genome_id,
        status=InstanceGeneStatus.learning if has_learning else InstanceGeneStatus.installing,
        installed_version=gene.version,
    )
    db.add(ig)
    gene.install_count += 1
    await db.commit()
    await db.refresh(ig)

    ws_ids = await _get_instance_workspace_ids(db, instance.id)

    if has_learning:
        from app.services.instance_service import _broadcast_agent_status
        instance.status = InstanceStatus.learning
        await db.commit()
        _broadcast_agent_status(ws_ids, instance_id, "learning")
        for ws_id in ws_ids:
            broadcast_event(ws_id, "gene:learn_start", {
                "instance_id": instance_id,
                "gene_slug": gene_slug,
            })
        _fire_task(
            _send_learning_task(instance.id, gene.id, ig.id)
        )
    else:
        for ws_id in ws_ids:
            broadcast_event(ws_id, "gene:install_start", {
                "instance_id": instance_id,
                "gene_slug": gene_slug,
            })
        _fire_task(
            _direct_install(instance.id, gene.id, ig.id)
        )

    return {
        "id": ig.id,
        "gene_slug": gene_slug,
        "status": ig.status,
        "method": "learning" if has_learning else "direct",
    }


async def install_gene_prerestart(instance_id: str, gene_slug: str) -> None:
    """Synchronously install a gene without triggering a restart.

    Uses its own DB session and advisory lock for isolation.
    Designed to be called from add_agent before _deploy_channel_plugin,
    so the subsequent restart picks up both the gene and channel plugin.
    """
    from app.core.deps import async_session_factory

    async with _instance_pg_advisory_lock(instance_id):
        async with async_session_factory() as db:
            gene = await get_gene_by_slug(db, gene_slug)

            if not gene:
                raise NotFoundError(f"基因 '{gene_slug}' 不存在")

            instance = await db.get(Instance, instance_id)
            if not instance:
                raise NotFoundError(f"实例 '{instance_id}' 不存在")

            existing = await db.execute(
                select(InstanceGene).where(
                    InstanceGene.instance_id == instance_id,
                    InstanceGene.gene_id == gene.id,
                    not_deleted(InstanceGene),
                )
            )
            existing_ig = existing.scalar_one_or_none()
            if existing_ig:
                if existing_ig.status == InstanceGeneStatus.installed:
                    return
                if existing_ig.status in (
                    InstanceGeneStatus.installing,
                    InstanceGeneStatus.failed,
                    InstanceGeneStatus.learn_failed,
                ):
                    existing_ig.soft_delete()
                    await db.commit()

            ig = InstanceGene(
                instance_id=instance_id,
                gene_id=gene.id,
                status=InstanceGeneStatus.installing,
                installed_version=gene.version,
            )
            db.add(ig)
            gene.install_count += 1
            await db.commit()
            await db.refresh(ig)

            try:
                aggregator = get_aggregator()
                agg_manifest = await aggregator.get_manifest(gene.slug)
                manifest = agg_manifest or _json_loads(gene.manifest) or {}
                skill = manifest.get("skill", {})
                adapter = _get_gene_install_adapter(instance.runtime)

                async with remote_fs(instance, db) as fs:
                    skill_name = skill.get("name", gene.slug)
                    skill_content = skill.get("content", "")
                    await adapter.deploy_skill(
                        fs, skill_name, skill_content,
                        gene.short_description or gene.description or "",
                    )
                    await _apply_manifest_actions(fs, manifest, adapter)
                    await adapter.invalidate_cache(fs, skill_name, "installed")

                ig.status = InstanceGeneStatus.installed
                ig.installed_at = datetime.now(timezone.utc)
                ig.config_snapshot = _json_dumps(
                    manifest.get("runtime_config") or manifest.get("openclaw_config")
                )
                await _record_evolution(
                    db, instance_id, EvolutionEventType.learned, gene.name,
                    gene_slug=gene.slug, gene_id=gene.id,
                    details={"version": gene.version, "learning_type": "direct"},
                )
                await db.commit()

                _fire_task(_report_install_to_registry(gene.slug, getattr(gene, "source_registry", None)))

                ws_ids = await _get_instance_workspace_ids(db, instance.id)
                for ws_id in ws_ids:
                    await _notify_skill_learned_in_workspace(
                        db,
                        instance=instance,
                        gene_obj=gene,
                        workspace_id=ws_id,
                    )
                    from app.api.workspaces import broadcast_event
                    broadcast_event(ws_id, "gene:installed", {
                        "instance_id": instance.id,
                        "gene_slug": gene.slug,
                        "method": "direct",
                    })

                logger.info(
                    "install_gene_prerestart: 基因 %s 已安装到实例 %s（不重启）",
                    gene_slug, instance.name,
                )
            except Exception as e:
                logger.error(
                    "install_gene_prerestart failed for gene %s on %s: %s",
                    gene_slug, instance.name, e,
                )
                try:
                    ig.status = InstanceGeneStatus.failed
                    await db.commit()
                except Exception:
                    logger.error("Failed to mark gene %s as failed", gene_slug)
                raise


async def _inject_mcp_servers(
    db: AsyncSession, instance_id: str, gene_id: str, mcp_servers: list[dict],
) -> None:
    """Auto-inject MCP servers from gene manifest into instance_mcp_servers."""
    import uuid
    from app.models.instance_mcp_server import InstanceMcpServer

    for mcp_def in mcp_servers:
        name = mcp_def.get("name", "")
        if not name:
            continue
        existing = await db.execute(
            select(InstanceMcpServer).where(
                InstanceMcpServer.instance_id == instance_id,
                InstanceMcpServer.name == name,
                not_deleted(InstanceMcpServer),
            ).limit(1)
        )
        if existing.scalar_one_or_none():
            continue
        mcp = InstanceMcpServer(
            id=str(uuid.uuid4()),
            instance_id=instance_id,
            name=name,
            transport=mcp_def.get("transport", "stdio"),
            command=mcp_def.get("command"),
            url=mcp_def.get("url"),
            args=mcp_def.get("args"),
            env=mcp_def.get("env"),
            source="gene",
            source_gene_id=gene_id,
        )
        db.add(mcp)
    await db.flush()


async def _direct_install(
    instance_id: str,
    gene_id: str,
    ig_id: str,
) -> None:
    from app.api.workspaces import broadcast_event
    from app.core.deps import async_session_factory
    from app.services.instance_service import restart_instance

    async with _instance_pg_advisory_lock(instance_id):
        async with async_session_factory() as db:
            ig = await db.get(InstanceGene, ig_id)
            gene = await db.get(Gene, gene_id)
            instance = await db.get(Instance, instance_id)
            if not ig or not gene or not instance:
                logger.error("_direct_install: record missing ig=%s gene=%s inst=%s", ig_id, gene_id, instance_id)
                return

            try:
                aggregator = get_aggregator()
                agg_manifest = await aggregator.get_manifest(gene.slug)
                manifest = agg_manifest or _json_loads(gene.manifest) or {}
                skill = manifest.get("skill", {})
                adapter = _get_gene_install_adapter(instance.runtime)

                async with remote_fs(instance, db) as fs:
                    skill_name = skill.get("name", gene.slug)
                    skill_content = skill.get("content", "")
                    await adapter.deploy_skill(
                        fs, skill_name, skill_content,
                        gene.short_description or gene.description or "",
                    )
                    await _apply_manifest_actions(fs, manifest, adapter)
                    await adapter.invalidate_cache(fs, skill_name, "installed")

                ig.status = InstanceGeneStatus.installed
                ig.installed_at = datetime.now(timezone.utc)
                ig.config_snapshot = _json_dumps(
                    manifest.get("runtime_config") or manifest.get("openclaw_config")
                )
                await _record_evolution(
                    db, instance_id, EvolutionEventType.learned, gene.name,
                    gene_slug=gene.slug, gene_id=gene_id,
                    details={"version": gene.version, "learning_type": "direct"},
                )
                await db.commit()

                _fire_task(_report_install_to_registry(gene.slug, getattr(gene, "source_registry", None)))

                should_restart = await _finish_learning_if_done(db, instance_id, ig_id)
                if should_restart:
                    await restart_instance(instance.id, db)

                ws_ids = await _get_instance_workspace_ids(db, instance.id)
                for ws_id in ws_ids:
                    await _notify_skill_learned_in_workspace(
                        db,
                        instance=instance,
                        gene_obj=gene,
                        workspace_id=ws_id,
                    )
                    broadcast_event(ws_id, "gene:installed", {
                        "instance_id": instance.id,
                        "gene_slug": gene.slug,
                        "method": "direct",
                    })
            except Exception as e:
                logger.error("Direct install failed for gene %s on %s: %s", gene.slug, instance.id, e)
                try:
                    ig.status = InstanceGeneStatus.failed
                    await db.commit()
                except Exception:
                    logger.error("Failed to mark gene install as failed for ig=%s", ig_id)


async def _send_learning_task(
    instance_id: str,
    gene_id: str,
    ig_id: str,
) -> None:
    """Send learning task to Learning Channel Plugin via webhook."""
    from app.core.deps import async_session_factory

    async with async_session_factory() as db:
        ig = await db.get(InstanceGene, ig_id)
        gene = await db.get(Gene, gene_id)
        instance = await db.get(Instance, instance_id)
        if not ig or not gene or not instance:
            logger.error("_send_learning_task: record missing ig=%s gene=%s inst=%s", ig_id, gene_id, instance_id)
            return

        aggregator = get_aggregator()
        agg_manifest = await aggregator.get_manifest(gene.slug)
        manifest = agg_manifest or _json_loads(gene.manifest) or {}
        skill = manifest.get("skill", {})
        learning = manifest.get("learning")

        callback_base = get_nodeskclaw_webhook_base_url()
        callback_url = build_gene_callback_url(
            callback_base,
            "/api/v1/genes/learning-callback",
            ig.id,
            instance.id,
            "learn",
        )

        gene_content = skill.get("content", "")
        force_deep = not _has_frontmatter(gene_content)

        payload: dict = {
            "mode": "learn",
            "task_id": ig.id,
            "gene_slug": gene.slug,
            "gene_content": gene_content,
            "learning": learning,
            "callback_url": callback_url,
            "force_deep_learn": force_deep,
            "gene_meta": {
                "name": gene.name,
                "description": gene.short_description or gene.description or "",
                "category": gene.category or "",
            },
        }

        if force_deep:
            ig.config_snapshot = _json_dumps({"force_deep_learn": True})
            await db.commit()

        from app.services.tunnel import tunnel_adapter

        if instance.id not in tunnel_adapter.connected_instances:
            logger.warning("Instance %s not connected via tunnel, falling back to direct install", instance.id)
            await _direct_install(instance.id, gene.id, ig.id)
            return

        try:
            await tunnel_adapter.send_learning_task(instance.id, payload)
            logger.info("Learning task sent for gene %s on %s", gene.slug, instance.id)
        except Exception as e:
            logger.error("Failed to send learning task via tunnel: %s, falling back to direct install", e)
            await _direct_install(instance.id, gene.id, ig.id)


async def _apply_manifest_actions(
    fs: RemoteFS, manifest: dict, adapter: GeneInstallAdapter,
) -> None:
    """Execute engineering actions using the runtime-specific adapter."""
    runtime_config = manifest.get("runtime_config") or manifest.get("openclaw_config")
    if runtime_config:
        await adapter.apply_config(fs, runtime_config)

    tool_allow = manifest.get("tool_allow")
    if tool_allow and isinstance(tool_allow, list):
        await adapter.allow_tools(fs, tool_allow)

    scripts = manifest.get("scripts")
    if scripts and isinstance(scripts, (list, dict)):
        await _deploy_gene_scripts(fs, scripts, adapter)


async def _deploy_gene_scripts(
    fs: RemoteFS, scripts: list[str] | dict[str, str], adapter: GeneInstallAdapter,
) -> None:
    """Deploy script files to the instance via adapter.

    Supports old format (list of filenames to load locally) and new format (dict of filename to content).
    """
    from pathlib import Path

    scripts_dir = Path(__file__).resolve().parent.parent / "data" / "gene_scripts"
    scripts_to_deploy: dict[str, str] = {}

    api_client_path = scripts_dir / "_api_client.py"
    if api_client_path.exists():
        scripts_to_deploy["_api_client.py"] = api_client_path.read_text()

    if isinstance(scripts, dict):
        for name, content in scripts.items():
            scripts_to_deploy[name] = content
    else:
        for name in scripts:
            script_path = scripts_dir / name
            if script_path.exists():
                scripts_to_deploy[name] = script_path.read_text()
            else:
                logger.warning("Gene script not found: %s", name)

    if scripts_to_deploy:
        await adapter.deploy_scripts(fs, scripts_to_deploy)





# ── Learning callback handler ────────────────────


async def handle_learning_callback(
    db: AsyncSession, payload: LearningCallbackPayload
) -> dict:
    from app.api.workspaces import broadcast_event
    from app.services.instance_service import get_instance, restart_instance

    ig = await db.execute(
        select(InstanceGene).where(InstanceGene.id == payload.task_id, not_deleted(InstanceGene))
    )
    ig_obj = ig.scalar_one_or_none()
    if not ig_obj:
        raise NotFoundError(f"学习任务 '{payload.task_id}' 不存在")
    if ig_obj.instance_id != payload.instance_id:
        raise BadRequestError("回调实例与学习任务不匹配")

    instance = await get_instance(ig_obj.instance_id, db)
    gene = await db.execute(
        select(Gene).where(Gene.id == ig_obj.gene_id, Gene.deleted_at.is_(None))
    )
    gene_obj = gene.scalar_one_or_none()
    if not gene_obj:
        raise NotFoundError("基因不存在")

    ws_ids = await _get_instance_workspace_ids(db, instance.id)
    for ws_id in ws_ids:
        broadcast_event(ws_id, "gene:learn_decided", {
            "instance_id": instance.id,
            "gene_slug": gene_obj.slug,
            "decision": payload.decision,
            "reason": payload.reason,
        })

    snapshot = _json_loads(ig_obj.config_snapshot) if ig_obj.config_snapshot else {}
    was_forced = snapshot.get("force_deep_learn", False) if isinstance(snapshot, dict) else False

    if payload.decision == "direct_install":
        if was_forced:
            logger.warning(
                "Agent chose direct_install despite force_deep_learn for gene %s on %s, "
                "falling back to auto-generated frontmatter install",
                gene_obj.slug, instance.id,
            )
        manifest = _json_loads(gene_obj.manifest) or {}
        skill = manifest.get("skill", {})
        gene_desc = gene_obj.short_description or gene_obj.description or ""
        skill_name = skill.get("name", gene_obj.slug)
        adapter = _get_gene_install_adapter(instance.runtime)
        async with remote_fs(instance, db) as fs:
            await adapter.deploy_skill(fs, skill_name, skill.get("content", ""), gene_desc)
            await _apply_manifest_actions(fs, manifest, adapter)
            await adapter.invalidate_cache(fs, skill_name, "installed")

        ig_obj.status = InstanceGeneStatus.installed
        ig_obj.installed_at = datetime.now(timezone.utc)

    elif payload.decision == "learned":
        content = payload.content or ""
        gene_desc = gene_obj.short_description or gene_obj.description or ""
        adapter = _get_gene_install_adapter(instance.runtime)
        async with remote_fs(instance, db) as fs:
            await adapter.deploy_skill(fs, gene_obj.slug, content, gene_desc)
            manifest = _json_loads(gene_obj.manifest) or {}
            await _apply_manifest_actions(fs, manifest, adapter)
            await adapter.invalidate_cache(fs, gene_obj.slug, "installed")

        ig_obj.status = InstanceGeneStatus.installed
        ig_obj.installed_at = datetime.now(timezone.utc)
        ig_obj.learning_output = content
        ig_obj.agent_self_eval = payload.self_eval

    elif payload.decision == "failed":
        ig_obj.status = InstanceGeneStatus.learn_failed
        await _record_evolution(
            db, instance.id, EvolutionEventType.learn_failed, gene_obj.name,
            gene_slug=gene_obj.slug, gene_id=gene_obj.id,
            details={"reason": payload.reason},
        )
        for ws_id in ws_ids:
            broadcast_event(ws_id, "gene:learn_failed", {
                "instance_id": instance.id,
                "gene_slug": gene_obj.slug,
                "reason": payload.reason,
            })
        await db.commit()

        should_restart = await _finish_learning_if_done(db, instance.id, ig_obj.id)
        if should_restart:
            await restart_instance(instance.id, db)

        return {"status": "learn_failed"}

    else:
        raise BadRequestError(f"未知决策: {payload.decision}")

    await _record_evolution(
        db, instance.id, EvolutionEventType.learned, gene_obj.name,
        gene_slug=gene_obj.slug, gene_id=gene_obj.id,
        details={"version": gene_obj.version, "learning_type": payload.decision},
    )
    await db.commit()

    should_restart = await _finish_learning_if_done(db, instance.id, ig_obj.id)
    if should_restart:
        await restart_instance(instance.id, db)

    _fire_task(_report_install_to_registry(gene_obj.slug, getattr(gene_obj, "source_registry", None)))

    for ws_id in ws_ids:
        await _notify_skill_learned_in_workspace(
            db,
            instance=instance,
            gene_obj=gene_obj,
            workspace_id=ws_id,
        )
        broadcast_event(ws_id, "gene:installed", {
            "instance_id": instance.id,
            "gene_slug": gene_obj.slug,
            "method": payload.decision,
        })

    return {"status": "installed", "method": payload.decision}


# ── Apply Genome ─────────────────────────────────


async def apply_genome(
    db: AsyncSession,
    instance_id: str,
    genome_id: str,
    org_id: str | None = None,
) -> dict:
    from app.services.instance_service import get_instance

    await get_instance(instance_id, db, org_id)
    genome_result = await db.execute(
        select(Genome).where(Genome.id == genome_id, not_deleted(Genome))
    )
    genome = genome_result.scalar_one_or_none()
    if not genome:
        raise NotFoundError("基因组不存在")

    gene_slugs = _json_loads(genome.gene_slugs) or []
    if not gene_slugs:
        return {"installed": [], "skipped": []}

    installed_q = await db.execute(
        select(Gene.slug)
        .join(InstanceGene, InstanceGene.gene_id == Gene.id)
        .where(
            InstanceGene.instance_id == instance_id,
            not_deleted(InstanceGene),
            Gene.deleted_at.is_(None),
        )
    )
    already_installed = {row[0] for row in installed_q}

    results = {"installed": [], "skipped": []}
    for slug in gene_slugs:
        if slug in already_installed:
            results["skipped"].append(slug)
            continue
        try:
            await install_gene(db, instance_id, slug, genome_id=genome.id, org_id=org_id)
            results["installed"].append(slug)
        except AppException:
            results["skipped"].append(slug)

    genome.install_count += 1
    await _record_evolution(
        db, instance_id, EvolutionEventType.genome_applied, genome.name,
        genome_id=genome.id,
        details={"genome_slug": genome.slug, "gene_slugs": gene_slugs, "installed": results["installed"], "skipped": results["skipped"]},
    )
    await db.commit()
    return results


# ═══════════════════════════════════════════════════
#  Rating + Effectiveness
# ═══════════════════════════════════════════════════


async def rate_gene(db: AsyncSession, gene_id: str, user_id: str, rating: int, comment: str | None = None) -> dict:
    existing = await db.execute(
        select(GeneRating).where(
            GeneRating.gene_id == gene_id,
            GeneRating.user_id == user_id,
            not_deleted(GeneRating),
        )
    )
    obj = existing.scalar_one_or_none()
    if obj:
        obj.rating = rating
        obj.comment = comment
    else:
        obj = GeneRating(gene_id=gene_id, user_id=user_id, rating=rating, comment=comment)
        db.add(obj)

    await db.commit()
    await _recalc_gene_rating(db, gene_id)
    return {"rating": rating}


async def rate_genome(db: AsyncSession, genome_id: str, user_id: str, rating: int, comment: str | None = None) -> dict:
    existing = await db.execute(
        select(GenomeRating).where(
            GenomeRating.genome_id == genome_id,
            GenomeRating.user_id == user_id,
            not_deleted(GenomeRating),
        )
    )
    obj = existing.scalar_one_or_none()
    if obj:
        obj.rating = rating
        obj.comment = comment
    else:
        obj = GenomeRating(genome_id=genome_id, user_id=user_id, rating=rating, comment=comment)
        db.add(obj)

    await db.commit()
    await _recalc_genome_rating(db, genome_id)
    return {"rating": rating}


async def _recalc_gene_rating(db: AsyncSession, gene_id: str) -> None:
    result = await db.execute(
        select(func.avg(GeneRating.rating)).where(
            GeneRating.gene_id == gene_id, not_deleted(GeneRating)
        )
    )
    avg = result.scalar() or 0.0
    gene_result = await db.execute(
        select(Gene).where(Gene.id == gene_id, Gene.deleted_at.is_(None))
    )
    gene = gene_result.scalar_one_or_none()
    if gene:
        gene.avg_rating = round(float(avg), 2)
        await db.commit()
        await _recalc_effectiveness_score(db, gene_id)


async def _recalc_genome_rating(db: AsyncSession, genome_id: str) -> None:
    result = await db.execute(
        select(func.avg(GenomeRating.rating)).where(
            GenomeRating.genome_id == genome_id, not_deleted(GenomeRating)
        )
    )
    avg = result.scalar() or 0.0
    genome_result = await db.execute(
        select(Genome).where(Genome.id == genome_id, Genome.deleted_at.is_(None))
    )
    genome = genome_result.scalar_one_or_none()
    if genome:
        genome.avg_rating = round(float(avg), 2)
        await db.commit()


async def log_effectiveness(
    db: AsyncSession,
    instance_id: str,
    gene_id: str,
    metric_type: str,
    value: float = 1.0,
    context: str | None = None,
) -> dict:
    from app.api.workspaces import broadcast_event

    log = GeneEffectLog(
        instance_id=instance_id,
        gene_id=gene_id,
        metric_type=metric_type,
        value=value,
        context=context,
    )
    db.add(log)

    ig_result = await db.execute(
        select(InstanceGene).where(
            InstanceGene.instance_id == instance_id,
            InstanceGene.gene_id == gene_id,
            not_deleted(InstanceGene),
        )
    )
    ig = ig_result.scalar_one_or_none()
    if ig:
        ig.usage_count += 1

    await db.commit()
    await _recalc_effectiveness_score(db, gene_id)

    gene_result = await db.execute(
        select(Gene).where(Gene.id == gene_id, Gene.deleted_at.is_(None))
    )
    gene = gene_result.scalar_one_or_none()

    instance_result = await db.execute(
        select(Instance).where(Instance.id == instance_id, Instance.deleted_at.is_(None))
    )
    instance = instance_result.scalar_one_or_none()
    if instance and gene:
        ws_ids = await _get_instance_workspace_ids(db, instance_id)
        for ws_id in ws_ids:
            broadcast_event(ws_id, "gene:effect_logged", {
                "instance_id": instance_id,
                "gene_slug": gene.slug,
                "metric_type": metric_type,
            })
        _fire_task(_report_effectiveness_to_registry(gene.slug, metric_type, value, getattr(gene, "source_registry", None)))

    return {"logged": True}


async def log_task_outcome(
    db: AsyncSession,
    assignee_instance_id: str,
    task_id: str,
    task_title: str,
    success: bool,
    failure_reason: str | None = None,
) -> int:
    """Write task_success effect logs for all installed genes on the assignee instance."""
    ig_result = await db.execute(
        select(InstanceGene).where(
            InstanceGene.instance_id == assignee_instance_id,
            InstanceGene.status == InstanceGeneStatus.installed,
            not_deleted(InstanceGene),
        )
    )
    installed_genes = ig_result.scalars().all()

    count = 0
    ctx = {"task_id": task_id, "title": task_title}
    if failure_reason:
        ctx["failure_reason"] = failure_reason
    context = json.dumps(ctx)
    for ig in installed_genes:
        await log_effectiveness(
            db,
            assignee_instance_id,
            ig.gene_id,
            metric_type=EffectMetricType.task_success,
            value=1.0 if success else 0.0,
            context=context,
        )
        count += 1
    return count


async def _report_install_to_registry(slug: str, source_registry: str | None = None) -> None:
    aggregator = get_aggregator()
    registry_id = source_registry or "local"
    await aggregator.report_install_to(registry_id, slug)


async def _report_effectiveness_to_registry(
    slug: str, metric_type: str, value: float, source_registry: str | None = None,
) -> None:
    aggregator = get_aggregator()
    registry_id = source_registry or "local"
    await aggregator.report_effectiveness_to(registry_id, slug, metric_type, value)


async def _recalc_effectiveness_score(db: AsyncSession, gene_id: str) -> None:
    """Recalculate effectiveness_score = rating 20% + self_eval 15% + usage 30% + task_success 35%."""
    gene_result = await db.execute(
        select(Gene).where(Gene.id == gene_id, Gene.deleted_at.is_(None))
    )
    gene = gene_result.scalar_one_or_none()
    if not gene:
        return

    user_rating_norm = gene.avg_rating / 5.0 if gene.avg_rating else 0.0

    agent_eval_result = await db.execute(
        select(func.avg(InstanceGene.agent_self_eval)).where(
            InstanceGene.gene_id == gene_id,
            InstanceGene.agent_self_eval.isnot(None),
            not_deleted(InstanceGene),
        )
    )
    agent_eval = agent_eval_result.scalar() or 0.0

    pos_result = await db.execute(
        select(func.count()).where(
            GeneEffectLog.gene_id == gene_id,
            GeneEffectLog.metric_type == EffectMetricType.user_positive,
        )
    )
    pos_count = pos_result.scalar() or 0

    neg_result = await db.execute(
        select(func.count()).where(
            GeneEffectLog.gene_id == gene_id,
            GeneEffectLog.metric_type == EffectMetricType.user_negative,
        )
    )
    neg_count = neg_result.scalar() or 0

    total = pos_count + neg_count
    usage_effect = (pos_count / total) if total > 0 else 0.5

    task_ok_result = await db.execute(
        select(func.count()).where(
            GeneEffectLog.gene_id == gene_id,
            GeneEffectLog.metric_type == EffectMetricType.task_success,
            GeneEffectLog.value >= 0.5,
        )
    )
    task_ok = task_ok_result.scalar() or 0

    task_fail_result = await db.execute(
        select(func.count()).where(
            GeneEffectLog.gene_id == gene_id,
            GeneEffectLog.metric_type == EffectMetricType.task_success,
            GeneEffectLog.value < 0.5,
        )
    )
    task_fail = task_fail_result.scalar() or 0

    task_total = task_ok + task_fail
    task_success_rate = (task_ok / task_total) if task_total > 0 else 0.5

    score = (
        user_rating_norm * 0.20
        + float(agent_eval) * 0.15
        + usage_effect * 0.30
        + task_success_rate * 0.35
    )
    gene.effectiveness_score = round(score, 4)
    await db.commit()


async def _get_effectiveness_breakdown(
    db: AsyncSession, gene_id: str, avg_rating: float
) -> dict:
    """Return the four components that make up effectiveness_score."""
    user_rating_norm = avg_rating / 5.0 if avg_rating else 0.0

    agent_eval_result = await db.execute(
        select(func.avg(InstanceGene.agent_self_eval)).where(
            InstanceGene.gene_id == gene_id,
            InstanceGene.agent_self_eval.isnot(None),
            not_deleted(InstanceGene),
        )
    )
    agent_eval = float(agent_eval_result.scalar() or 0.0)

    pos_result = await db.execute(
        select(func.count()).where(
            GeneEffectLog.gene_id == gene_id,
            GeneEffectLog.metric_type == EffectMetricType.user_positive,
        )
    )
    pos_count = pos_result.scalar() or 0

    neg_result = await db.execute(
        select(func.count()).where(
            GeneEffectLog.gene_id == gene_id,
            GeneEffectLog.metric_type == EffectMetricType.user_negative,
        )
    )
    neg_count = neg_result.scalar() or 0

    total = pos_count + neg_count
    usage_effect = (pos_count / total) if total > 0 else 0.5

    task_ok_result = await db.execute(
        select(func.count()).where(
            GeneEffectLog.gene_id == gene_id,
            GeneEffectLog.metric_type == EffectMetricType.task_success,
            GeneEffectLog.value >= 0.5,
        )
    )
    task_success_count = task_ok_result.scalar() or 0

    task_fail_result = await db.execute(
        select(func.count()).where(
            GeneEffectLog.gene_id == gene_id,
            GeneEffectLog.metric_type == EffectMetricType.task_success,
            GeneEffectLog.value < 0.5,
        )
    )
    task_fail_count = task_fail_result.scalar() or 0

    task_total = task_success_count + task_fail_count
    task_success_rate = (task_success_count / task_total) if task_total > 0 else 0.5

    return {
        "user_rating": round(user_rating_norm, 4),
        "agent_eval": round(agent_eval, 4),
        "usage_effect": round(usage_effect, 4),
        "positive_count": pos_count,
        "negative_count": neg_count,
        "task_success_rate": round(task_success_rate, 4),
        "task_success_count": task_success_count,
        "task_fail_count": task_fail_count,
    }


# ═══════════════════════════════════════════════════
#  Evolution: Variant publish, Agent creation, Uninstall
# ═══════════════════════════════════════════════════


async def publish_variant(
    db: AsyncSession,
    instance_id: str,
    gene_id: str,
    variant_name: str | None = None,
    variant_slug: str | None = None,
) -> dict:
    from app.api.workspaces import broadcast_event

    ig_result = await db.execute(
        select(InstanceGene).where(
            InstanceGene.instance_id == instance_id,
            InstanceGene.gene_id == gene_id,
            not_deleted(InstanceGene),
        )
    )
    ig = ig_result.scalar_one_or_none()
    if not ig:
        raise NotFoundError("未找到已学习的基因")
    if not ig.learning_output:
        raise BadRequestError("该基因未通过深度学习，无个性化内容可发布")
    if ig.variant_published:
        raise ConflictError("该基因的变体已发布")

    parent_gene = await db.execute(
        select(Gene).where(Gene.id == gene_id, Gene.deleted_at.is_(None))
    )
    parent = parent_gene.scalar_one_or_none()
    if not parent:
        raise NotFoundError("原始基因不存在")

    instance_result = await db.execute(
        select(Instance).where(Instance.id == instance_id, Instance.deleted_at.is_(None))
    )
    instance = instance_result.scalar_one_or_none()
    agent_display = instance.name if instance else instance_id[:8]

    slug = variant_slug or f"{parent.slug}-by-{agent_display.lower().replace(' ', '-')}"
    name = variant_name or f"{parent.name} (by {agent_display})"

    manifest = _json_loads(parent.manifest) or {}
    manifest["skill"] = {"name": slug, "content": ig.learning_output}

    variant_desc = f"AI 员工 {agent_display} 基于 {parent.name} 的进化版本"
    _validate_skill_metadata(manifest, parent.short_description, variant_desc)

    variant = Gene(
        name=name,
        slug=slug,
        description=variant_desc,
        short_description=parent.short_description,
        category=parent.category,
        tags=parent.tags,
        source=GeneSource.agent,
        icon=parent.icon,
        version="1.0.0",
        manifest=_json_dumps(manifest),
        dependencies=parent.dependencies,
        synergies=parent.synergies,
        parent_gene_id=gene_id,
        created_by_instance_id=instance_id,
        is_published=False,
        review_status=GeneReviewStatus.pending_admin,
    )
    db.add(variant)

    ig.variant_published = True
    await _record_evolution(
        db, instance_id, EvolutionEventType.variant_published, parent.name,
        gene_slug=parent.slug, gene_id=gene_id,
        details={"variant_gene_id": variant.id, "variant_slug": slug},
    )
    await db.commit()
    await db.refresh(variant)

    ws_ids = await _get_instance_workspace_ids(db, instance_id) if instance else []
    for ws_id in ws_ids:
        broadcast_event(ws_id, "gene:variant_published", {
            "instance_id": instance_id,
            "gene_slug": parent.slug,
            "variant_slug": slug,
        })

    return _gene_to_dict(variant)


async def trigger_gene_creation(
    db: AsyncSession,
    instance_id: str,
    creation_prompt: str | None = None,
    org_id: str | None = None,
) -> dict:
    from app.services.instance_service import get_instance

    instance = await get_instance(instance_id, db, org_id)
    import uuid

    task_id = str(uuid.uuid4())

    callback_base = get_nodeskclaw_webhook_base_url()
    callback_url = build_gene_callback_url(
        callback_base,
        "/api/v1/genes/creation-callback",
        task_id,
        instance.id,
        "create",
    )

    payload = {
        "mode": "create",
        "task_id": task_id,
        "creation_prompt": creation_prompt or "基于你的工作经验，总结出一个可复用的方法论并生成一个新的基因",
        "callback_url": callback_url,
    }

    from app.services.tunnel import tunnel_adapter

    if instance.id not in tunnel_adapter.connected_instances:
        raise BadRequestError("实例未通过隧道连接")

    try:
        await tunnel_adapter.send_learning_task(instance.id, payload)
    except Exception as e:
        raise AppException(code=50001, message=f"发送创造任务失败: {e}", status_code=500)

    return {"task_id": task_id, "status": "sent"}


async def handle_creation_callback(
    db: AsyncSession, payload: LearningCallbackPayload
) -> dict:
    from app.api.workspaces import broadcast_event

    if payload.decision != "created":
        return {"status": "ignored", "decision": payload.decision}

    meta = payload.meta or {}

    instance_result = await db.execute(
        select(Instance).where(
            Instance.id == payload.instance_id,
            Instance.deleted_at.is_(None),
        )
    )
    instance = instance_result.scalar_one_or_none()
    if instance is None:
        raise NotFoundError("实例不存在")

    gene_desc = meta.get("gene_description", "")
    gene_short_desc = gene_desc[:256] if gene_desc else None
    gene_manifest = {
        "skill": {"name": meta.get("gene_slug", f"agent-gene-{payload.task_id[:8]}"), "content": payload.content or ""}
    }

    _validate_skill_metadata(gene_manifest, gene_short_desc, gene_desc or None)

    gene = Gene(
        name=meta.get("gene_name", f"agent-gene-{payload.task_id[:8]}"),
        slug=meta.get("gene_slug", f"agent-gene-{payload.task_id[:8]}"),
        description=gene_desc,
        short_description=gene_short_desc,
        category=meta.get("suggested_category", ""),
        tags=_json_dumps(meta.get("suggested_tags", [])),
        source=GeneSource.agent,
        icon=meta.get("icon"),
        version="1.0.0",
        manifest=_json_dumps(gene_manifest),
        created_by_instance_id=payload.instance_id,
        is_published=False,
        review_status=GeneReviewStatus.pending_owner,
    )
    db.add(gene)
    await db.commit()
    await db.refresh(gene)

    ws_ids = await _get_instance_workspace_ids(db, payload.instance_id) if instance else []
    for ws_id in ws_ids:
        broadcast_event(ws_id, "gene:created", {
            "instance_id": payload.instance_id,
            "gene_slug": gene.slug,
            "gene_name": gene.name,
        })

    _fire_task(
        _push_created_gene_to_registry(
            gene_manifest,
            gene.slug,
            gene.name,
            gene_desc,
            meta,
            instance.runtime,
        )
    )

    return {"status": "created", "gene_id": gene.id, "slug": gene.slug}


async def _push_created_gene_to_registry(
    manifest: dict,
    slug: str,
    name: str,
    description: str,
    meta: dict,
    runtime: str,
) -> None:
    """Best-effort push of an Agent-created gene to default registry."""
    full_manifest = {
        "slug": slug,
        "name": name,
        "version": "1.0.0",
        "description": description,
        "short_description": (description[:256] if description else ""),
        "category": meta.get("suggested_category", "skill"),
        "tags": meta.get("suggested_tags", []),
        "icon": meta.get("icon"),
        "author": {"type": "agent", "name": "nodeskclaw"},
        "compatibility": [{"product": runtime or "openclaw", "min_version": "1.0.0"}],
        **manifest,
    }
    aggregator = get_aggregator()
    for adapter_id in aggregator.adapter_ids:
        if adapter_id != "local":
            result = await aggregator.publish_to(adapter_id, full_manifest)
            if result:
                logger.info("Agent-created gene %s pushed to %s", slug, adapter_id)
                return
    logger.info("Agent-created gene %s: no external registry to push to", slug)


async def _push_approved_gene_to_registry(gene: Gene) -> None:
    """Best-effort push when admin approves a gene (pending_admin -> approved)."""
    manifest = _json_loads(gene.manifest) or {}
    full_manifest = {
        "slug": gene.slug,
        "name": gene.name,
        "version": gene.version,
        "description": gene.description or "",
        "short_description": gene.short_description or "",
        "category": gene.category or "skill",
        "tags": _json_loads(gene.tags) or [],
        "icon": gene.icon,
        **manifest,
    }
    target = getattr(gene, "source_registry", None)
    aggregator = get_aggregator()
    if target and target != "local":
        result = await aggregator.publish_to(target, full_manifest)
        if result:
            logger.info("Approved gene %s pushed to %s", gene.slug, target)
            return
    for adapter_id in aggregator.adapter_ids:
        if adapter_id != "local":
            result = await aggregator.publish_to(adapter_id, full_manifest)
            if result:
                logger.info("Approved gene %s pushed to %s", gene.slug, adapter_id)
                return
    logger.info("Approved gene %s: no external registry to push to", gene.slug)


async def review_gene(
    db: AsyncSession,
    gene_id: str,
    action: str,
    reason: str | None = None,
    *,
    current_user=None,  # app.models.user.User 对象（API 层注入；保留 None 以兼容老调用）
) -> dict:
    """审核 gene。

    权限：当前用户必须是该 gene 所属 org 的 OrgRole.admin 或平台超管。
    个人 library（visibility=personal）无需审核，不应进入此函数。

    状态机（已简化为单步）：
      - pending_owner / pending_admin → approved（is_published=True，且若为公共可见性则推送注册表）
      - 任意状态 → rejected（is_published=False）
    """
    from fastapi import HTTPException, status

    from app.models.org_membership import OrgMembership, OrgRole

    result = await db.execute(select(Gene).where(Gene.id == gene_id, not_deleted(Gene)))
    gene = result.scalar_one_or_none()
    if not gene:
        raise NotFoundError("基因不存在")

    # ── 权限校验：超管 / 该 gene 所属 org 的 admin ────────────────────────
    if current_user is not None:
        allowed = False
        if getattr(current_user, "is_super_admin", False):
            allowed = True
        elif gene.org_id:
            membership = (await db.execute(
                select(OrgMembership).where(
                    OrgMembership.user_id == current_user.id,
                    OrgMembership.org_id == gene.org_id,
                    OrgMembership.role == OrgRole.admin,
                    OrgMembership.deleted_at.is_(None),
                )
            )).scalar_one_or_none()
            if membership:
                allowed = True
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error_code": 40317,
                    "message_key": "errors.gene.review_forbidden",
                    "message": "您无权审核此基因（需该基因所属组织的管理员）",
                },
            )

    # ── 状态机 ────────────────────────────────────────────────────────
    if action == "approve":
        if gene.review_status in (GeneReviewStatus.pending_owner, GeneReviewStatus.pending_admin):
            gene.review_status = GeneReviewStatus.approved
            gene.is_published = True
            # 仅公共可见性的 gene 需要推送到外部注册表
            if gene.visibility == "public":
                _fire_task(_push_approved_gene_to_registry(gene))
        else:
            raise BadRequestError(f"当前审核状态 '{gene.review_status}' 不可审核通过")
    elif action == "reject":
        gene.review_status = GeneReviewStatus.rejected
        gene.is_published = False
    else:
        raise BadRequestError(f"未知审核动作: {action}")

    await db.commit()
    return {"review_status": gene.review_status, "is_published": gene.is_published}


async def refresh_gene_skills(db: AsyncSession, gene_slugs: list[str]) -> dict:
    """Refresh SKILL.md on all instances that have the specified genes installed.

    Fetches the latest manifest from the registry aggregator (or local DB) and overwrites
    the skill file on each instance without changing InstanceGene status.
    """
    result = await db.execute(
        select(InstanceGene, Gene, Instance)
        .join(Gene, InstanceGene.gene_id == Gene.id)
        .join(Instance, InstanceGene.instance_id == Instance.id)
        .where(
            Gene.slug.in_(gene_slugs),
            InstanceGene.status == InstanceGeneStatus.installed,
            not_deleted(InstanceGene),
            not_deleted(Instance),
            Gene.deleted_at.is_(None),
        )
    )
    rows = result.all()

    refreshed: list[dict] = []
    failed: list[dict] = []

    for ig, gene, instance in rows:
        try:
            aggregator = get_aggregator()
            agg_manifest = await aggregator.get_manifest(gene.slug)
            manifest = agg_manifest or _json_loads(gene.manifest) or {}
            skill = manifest.get("skill", {})
            skill_name = skill.get("name", gene.slug)
            skill_content = skill.get("content", "")
            if not skill_content:
                continue

            adapter = _get_gene_install_adapter(instance.runtime)
            async with remote_fs(instance, db) as fs:
                await adapter.deploy_skill(
                    fs, skill_name, skill_content,
                    gene.short_description or gene.description or "",
                )

            refreshed.append({
                "instance_id": instance.id,
                "instance_name": instance.name,
                "gene_slug": gene.slug,
            })
        except Exception as e:
            logger.error(
                "refresh_gene_skills: instance=%s gene=%s error=%s",
                instance.name, gene.slug, e,
            )
            failed.append({
                "instance_id": instance.id,
                "instance_name": instance.name,
                "gene_slug": gene.slug,
                "error": str(e),
            })

    logger.info(
        "refresh_gene_skills: refreshed=%d failed=%d slugs=%s",
        len(refreshed), len(failed), gene_slugs,
    )
    return {"refreshed": refreshed, "failed": failed}


async def uninstall_gene(
    db: AsyncSession,
    instance_id: str,
    gene_id: str,
    org_id: str | None = None,
) -> dict:
    from app.services.instance_service import get_instance

    await get_instance(instance_id, db, org_id)

    ig_result = await db.execute(
        select(InstanceGene).where(
            InstanceGene.instance_id == instance_id,
            InstanceGene.gene_id == gene_id,
            not_deleted(InstanceGene),
        )
    )
    ig = ig_result.scalar_one_or_none()
    if not ig:
        raise NotFoundError("未找到已学习的基因")

    has_learning = await _has_meta_learning(db, instance_id)

    if has_learning:
        ig.status = InstanceGeneStatus.forgetting
        await db.commit()
        _fire_task(_send_forgetting_task(instance_id, gene_id, ig.id))
        return {"status": "forgetting", "method": "deep"}
    else:
        ig.status = InstanceGeneStatus.uninstalling
        await db.commit()
        _fire_task(_direct_uninstall(instance_id, gene_id, ig.id))
        return {"status": "uninstalling", "method": "direct"}


async def _direct_uninstall(
    instance_id: str,
    gene_id: str,
    ig_id: str,
) -> None:
    """Remove skill file and soft-delete InstanceGene without Agent involvement."""
    from app.core.deps import async_session_factory
    from app.services.instance_service import restart_instance

    async with _instance_pg_advisory_lock(instance_id):
        async with async_session_factory() as db:
            ig = await db.get(InstanceGene, ig_id)
            gene = await db.get(Gene, gene_id)
            instance = await db.get(Instance, instance_id)
            if not ig or not instance:
                logger.error("_direct_uninstall: record missing ig=%s inst=%s", ig_id, instance_id)
                return

            try:
                if gene:
                    manifest = _json_loads(gene.manifest) or {}
                    skill_name = manifest.get("skill", {}).get("name", gene.slug)
                    adapter = _get_gene_install_adapter(instance.runtime)
                    async with remote_fs(instance, db) as fs:
                        await adapter.remove_skill(fs, skill_name)
                        await adapter.post_remove_cleanup(fs, skill_name)

                ig.soft_delete()
                if gene:
                    gene.install_count = max(0, gene.install_count - 1)
                await _record_evolution(
                    db, instance_id, EvolutionEventType.forgotten,
                    gene.name if gene else "unknown",
                    gene_slug=gene.slug if gene else None,
                    gene_id=gene_id,
                    details={"version": ig.installed_version, "usage_count": ig.usage_count, "method": "direct"},
                )
                await db.commit()

                await restart_instance(instance.id, db)
                logger.info("Direct uninstall completed for gene %s on %s", gene_id, instance_id)
            except Exception as e:
                logger.error("Direct uninstall failed for gene %s on %s: %s", gene_id, instance_id, e)
                ig.status = InstanceGeneStatus.installed
                await db.commit()


async def _send_forgetting_task(
    instance_id: str,
    gene_id: str,
    ig_id: str,
) -> None:
    """Send forgetting task to Learning Channel Plugin via webhook."""
    from app.core.deps import async_session_factory

    async with async_session_factory() as db:
        ig = await db.get(InstanceGene, ig_id)
        gene = await db.get(Gene, gene_id)
        instance = await db.get(Instance, instance_id)
        if not ig or not gene or not instance:
            logger.error("_send_forgetting_task: record missing ig=%s gene=%s inst=%s", ig_id, gene_id, instance_id)
            return

        manifest = _json_loads(gene.manifest) or {}
        skill_content = manifest.get("skill", {}).get("content", "")

        callback_base = get_nodeskclaw_webhook_base_url()
        callback_url = build_gene_callback_url(
            callback_base,
            "/api/v1/genes/forgetting-callback",
            ig.id,
            instance.id,
            "forget",
        )

        payload = {
            "mode": "forget",
            "task_id": ig.id,
            "gene_slug": gene.slug,
            "gene_content": skill_content,
            "learning_output": ig.learning_output or "",
            "usage_count": ig.usage_count,
            "callback_url": callback_url,
        }

        from app.services.tunnel import tunnel_adapter

        if instance.id not in tunnel_adapter.connected_instances:
            logger.warning("Instance %s not connected via tunnel, falling back to direct uninstall", instance.id)
            await _direct_uninstall(instance.id, gene.id, ig.id)
            return

        try:
            await tunnel_adapter.send_learning_task(instance.id, payload)
            logger.info("Forgetting task sent for gene %s on %s", gene.slug, instance.id)
        except Exception as e:
            logger.error("Failed to send forgetting task via tunnel: %s, falling back to direct uninstall", e)
            await _direct_uninstall(instance.id, gene.id, ig.id)


# ── Forgetting callback handler ──────────────────


async def handle_forgetting_callback(
    db: AsyncSession, payload: LearningCallbackPayload
) -> dict:
    from app.api.workspaces import broadcast_event
    from app.services.instance_service import get_instance, restart_instance

    ig = await db.get(InstanceGene, payload.task_id)
    if not ig:
        raise NotFoundError(f"InstanceGene not found: {payload.task_id}")
    if ig.instance_id != payload.instance_id:
        raise BadRequestError("回调实例与遗忘任务不匹配")

    instance = await get_instance(ig.instance_id, db)
    gene_result = await db.execute(
        select(Gene).where(Gene.id == ig.gene_id, Gene.deleted_at.is_(None))
    )
    gene = gene_result.scalar_one_or_none()

    ws_ids = await _get_instance_workspace_ids(db, instance.id)

    gene_name = gene.name if gene else "unknown"
    gene_slug = gene.slug if gene else None

    if payload.decision == "forget_failed":
        ig.status = InstanceGeneStatus.forget_failed
        await _record_evolution(
            db, ig.instance_id, EvolutionEventType.forget_failed, gene_name,
            gene_slug=gene_slug, gene_id=ig.gene_id,
            details={"reason": payload.reason},
        )
        await db.commit()
        for ws_id in ws_ids:
            await broadcast_event(ws_id, "gene:forget_failed", {
                "instance_id": ig.instance_id,
                "gene_id": ig.gene_id,
                "reason": payload.reason,
            })
        return {"status": "forget_failed"}

    if payload.decision == "simplified" and gene:
        manifest = _json_loads(gene.manifest) or {}
        skill_name = manifest.get("skill", {}).get("name", gene.slug)
        content = payload.content or ""
        adapter = _get_gene_install_adapter(instance.runtime)
        async with remote_fs(instance, db) as fs:
            await adapter.deploy_skill(fs, skill_name, content, gene.short_description or "")
            await adapter.invalidate_cache(fs, skill_name, "uninstalled")

        ig.status = InstanceGeneStatus.simplified
        await _record_evolution(
            db, ig.instance_id, EvolutionEventType.simplified, gene_name,
            gene_slug=gene_slug, gene_id=ig.gene_id,
            details={
                "version": ig.installed_version,
                "usage_count": ig.usage_count,
                "simplified_reason": payload.reason,
                "method": "deep",
            },
        )
        await db.commit()

        should_restart = await _finish_learning_if_done(db, instance.id, ig.id)
        if should_restart:
            await restart_instance(instance.id, db)

        for ws_id in ws_ids:
            await broadcast_event(ws_id, "gene:simplified", {
                "instance_id": ig.instance_id,
                "gene_id": ig.gene_id,
                "gene_name": gene_name,
                "reason": payload.reason,
            })
        return {"status": "simplified"}

    # Default: "forgotten" -- complete removal
    if gene:
        manifest = _json_loads(gene.manifest) or {}
        skill_name = manifest.get("skill", {}).get("name", gene.slug)
        adapter = _get_gene_install_adapter(instance.runtime)
        async with remote_fs(instance, db) as fs:
            await adapter.remove_skill(fs, skill_name)
            await adapter.post_remove_cleanup(fs, skill_name)

    ig.soft_delete()
    if gene:
        gene.install_count = max(0, gene.install_count - 1)
    await _record_evolution(
        db, ig.instance_id, EvolutionEventType.forgotten, gene_name,
        gene_slug=gene_slug, gene_id=ig.gene_id,
        details={
            "version": ig.installed_version,
            "usage_count": ig.usage_count,
            "forgetting_summary": payload.content,
            "self_eval": payload.self_eval,
            "method": "deep",
        },
    )
    await db.commit()

    should_restart = await _finish_learning_if_done(db, instance.id, ig.id)
    if should_restart:
        await restart_instance(instance.id, db)

    for ws_id in ws_ids:
        await broadcast_event(ws_id, "gene:forgotten", {
            "instance_id": ig.instance_id,
            "gene_id": ig.gene_id,
            "gene_name": gene_name,
        })
    return {"status": "forgotten"}


# ═══════════════════════════════════════════════════
#  Evolution Log
# ═══════════════════════════════════════════════════


async def get_evolution_log(
    db: AsyncSession,
    instance_id: str,
    page: int = 1,
    page_size: int = 20,
    org_id: str | None = None,
) -> list[dict]:
    from app.services.instance_service import get_instance

    await get_instance(instance_id, db, org_id)
    offset = (page - 1) * page_size
    result = await db.execute(
        select(EvolutionEvent)
        .where(EvolutionEvent.instance_id == instance_id, not_deleted(EvolutionEvent))
        .order_by(EvolutionEvent.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    events = result.scalars().all()
    out = []
    for ev in events:
        details = _json_loads(ev.details)
        out.append({
            "id": ev.id,
            "instance_id": ev.instance_id,
            "event_type": ev.event_type,
            "gene_name": ev.gene_name,
            "gene_slug": ev.gene_slug,
            "gene_id": ev.gene_id,
            "genome_id": ev.genome_id,
            "details": details,
            "created_at": ev.created_at.isoformat() if ev.created_at else None,
        })
    return out


# ═══════════════════════════════════════════════════
#  Admin
# ═══════════════════════════════════════════════════


async def admin_list_genes(
    db: AsyncSession,
    *,
    keyword: str | None = None,
    category: str | None = None,
    is_published: bool | None = None,
    sort: str = "newest",
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    """Admin gene list -- includes unpublished, with extra fields."""
    base = select(Gene).where(not_deleted(Gene))

    if keyword:
        base = base.where(Gene.name.ilike(f"%{keyword}%") | Gene.slug.ilike(f"%{keyword}%"))
    if category:
        base = base.where(Gene.category == category)
    if is_published is not None:
        base = base.where(Gene.is_published.is_(is_published))

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    sort_map = {
        "newest": Gene.created_at.desc(),
        "popularity": Gene.install_count.desc(),
        "rating": Gene.avg_rating.desc(),
        "effectiveness": Gene.effectiveness_score.desc(),
    }
    base = base.order_by(sort_map.get(sort, Gene.created_at.desc()))
    base = base.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(base)
    return [_gene_to_dict(g) for g in result.scalars().all()], total


async def admin_list_genomes(
    db: AsyncSession,
    *,
    keyword: str | None = None,
    is_published: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    base = select(Genome).where(not_deleted(Genome))
    if keyword:
        base = base.where(Genome.name.ilike(f"%{keyword}%") | Genome.slug.ilike(f"%{keyword}%"))
    if is_published is not None:
        base = base.where(Genome.is_published.is_(is_published))

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    base = base.order_by(Genome.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(base)
    items = await _enrich_genomes_tool_counts(db, [_genome_to_dict(g) for g in result.scalars().all()])
    return items, total


async def update_gene(db: AsyncSession, gene_id: str, req: UpdateGeneRequest) -> dict:
    result = await db.execute(select(Gene).where(Gene.id == gene_id, not_deleted(Gene)))
    gene = result.scalar_one_or_none()
    if not gene:
        raise NotFoundError("基因不存在")

    updates = req.model_dump(exclude_unset=True)
    if "tags" in updates and updates["tags"] is not None:
        updates["tags"] = _json_dumps(updates["tags"])
    if "manifest" in updates and updates["manifest"] is not None:
        updates["manifest"] = _json_dumps(updates["manifest"])

    for field, value in updates.items():
        setattr(gene, field, value)

    await db.commit()
    await db.refresh(gene)
    return _gene_to_dict(gene)


async def soft_delete_gene(db: AsyncSession, gene_id: str) -> dict:
    result = await db.execute(select(Gene).where(Gene.id == gene_id, not_deleted(Gene)))
    gene = result.scalar_one_or_none()
    if not gene:
        raise NotFoundError("基因不存在")
    gene.soft_delete()
    await db.commit()
    return {"deleted": True}


async def delete_user_gene(
    db: AsyncSession,
    gene_id: str,
    *,
    current_user,  # app.models.user.User 对象
) -> dict:
    """用户级删除已上传的 skill / gene。

    权限策略（任一满足即可）：
      1. 上传者本人（gene.created_by == current_user.id）
      2. 当前组织的 admin（OrgMembership.role == OrgRole.admin）
      3. 超管（current_user.is_super_admin == True）

    删除策略：直接软删 gene 本身，并级联软删所有 active 的 InstanceGene 引用，
    使依赖该 gene 的 agent 实例也立即看不到该 skill；前端无需先卸载。

    Raises:
        NotFoundError: gene 不存在或已软删
        HTTPException 403: 无权删除
    """
    from fastapi import HTTPException, status

    from app.models.org_membership import OrgMembership, OrgRole

    # ── 1. 取 gene，不存在或已软删则 404 ──────────────────────────────────
    gene = (await db.execute(
        select(Gene).where(Gene.id == gene_id, not_deleted(Gene))
    )).scalar_one_or_none()
    if not gene:
        raise NotFoundError("基因不存在")

    # ── 2. 权限校验 ────────────────────────────────────────────────────────
    allowed = False

    if current_user.is_super_admin:
        # 超管直接放行
        allowed = True
    elif gene.created_by and gene.created_by == current_user.id:
        # 上传者本人
        allowed = True
    elif gene.org_id:
        # 检查当前用户是否为 gene 所属 org 的 admin
        membership = (await db.execute(
            select(OrgMembership).where(
                OrgMembership.user_id == current_user.id,
                OrgMembership.org_id == gene.org_id,
                OrgMembership.role == OrgRole.admin,
                OrgMembership.deleted_at.is_(None),
            )
        )).scalar_one_or_none()
        if membership:
            allowed = True

    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": 40316,
                "message_key": "errors.gene.delete_forbidden",
                "message": "您无权删除此基因（需是上传者或组织管理员）",
            },
        )

    # ── 2.5. 个人 scope 已被 Agent 加载时拒绝删除 ─────────────────────────
    # 判定：org_id 为空且 created_by 非空（即 target=personal 的归属规则）。
    # 若仍有 active InstanceGene 引用（deleted_at IS NULL），引导用户先在实例侧卸载，
    # 防止"个人技能被悄悄连根抹除"的非预期数据丢失。
    # 组织 / 公共 scope 不进入此分支，保留下方的级联软删行为。
    is_personal_scope = gene.org_id is None and gene.created_by is not None
    if is_personal_scope:
        in_use_count = (await db.execute(
            select(func.count()).select_from(InstanceGene).where(
                InstanceGene.gene_id == gene_id,
                InstanceGene.deleted_at.is_(None),
            )
        )).scalar() or 0
        if in_use_count > 0:
            raise ConflictError(
                message=f"该个人技能正被 {in_use_count} 个 Agent 加载，请先在对应实例卸载后再删除",
                message_key="errors.gene.personal_in_use_by_agent",
            )

    # ── 3. 级联软删所有 active InstanceGene 引用 ─────────────────────────
    # 查询所有依赖该 gene 的 active 实例安装记录
    refs_result = await db.execute(
        select(InstanceGene).where(
            InstanceGene.gene_id == gene_id,
            InstanceGene.deleted_at.is_(None),
        )
    )
    refs = refs_result.scalars().all()
    cascaded_count = len(refs)
    for ig in refs:
        ig.soft_delete()

    # ── 4. 软删 gene 本身 ───────────────────────────────────────────────────
    gene.soft_delete()
    await db.commit()
    return {"deleted": True, "id": gene_id, "cascaded_instance_genes": cascaded_count}


async def update_genome(db: AsyncSession, genome_id: str, req: UpdateGenomeRequest) -> dict:
    result = await db.execute(select(Genome).where(Genome.id == genome_id, not_deleted(Genome)))
    genome = result.scalar_one_or_none()
    if not genome:
        raise NotFoundError("基因组不存在")

    updates = req.model_dump(exclude_unset=True)
    if "gene_slugs" in updates and updates["gene_slugs"] is not None:
        updates["gene_slugs"] = _json_dumps(updates["gene_slugs"])
    if "config_override" in updates and updates["config_override"] is not None:
        updates["config_override"] = _json_dumps(updates["config_override"])

    for field, value in updates.items():
        setattr(genome, field, value)

    await db.commit()
    await db.refresh(genome)
    return _genome_to_dict(genome)


async def soft_delete_genome(db: AsyncSession, genome_id: str) -> dict:
    result = await db.execute(select(Genome).where(Genome.id == genome_id, not_deleted(Genome)))
    genome = result.scalar_one_or_none()
    if not genome:
        raise NotFoundError("基因组不存在")
    genome.soft_delete()
    await db.commit()
    return {"deleted": True}


async def get_gene_stats(db: AsyncSession) -> GeneStatsResponse:
    total = (await db.execute(
        select(func.count()).select_from(Gene).where(not_deleted(Gene))
    )).scalar() or 0

    total_installs = (await db.execute(
        select(func.coalesce(func.sum(Gene.install_count), 0)).where(not_deleted(Gene))
    )).scalar() or 0

    learning = (await db.execute(
        select(func.count()).select_from(InstanceGene).where(
            InstanceGene.status == InstanceGeneStatus.learning,
            not_deleted(InstanceGene),
        )
    )).scalar() or 0

    failed = (await db.execute(
        select(func.count()).select_from(InstanceGene).where(
            InstanceGene.status == InstanceGeneStatus.learn_failed,
            not_deleted(InstanceGene),
        )
    )).scalar() or 0

    agent_created = (await db.execute(
        select(func.count()).select_from(Gene).where(
            Gene.source == GeneSource.agent, not_deleted(Gene)
        )
    )).scalar() or 0

    return GeneStatsResponse(
        total_genes=total,
        total_installs=int(total_installs),
        learning_count=learning,
        failed_count=failed,
        agent_created_count=agent_created,
    )


async def get_pending_review_genes(
    db: AsyncSession,
    current_user=None,
) -> list[dict]:
    """获取当前用户可审核的待审 gene 列表。

    权限范围：
      - 平台超管：返回所有 pending_owner / pending_admin
      - 任意组织 admin：仅返回其作为 admin 的 org 下的待审 gene
      - 其他用户（包括未传 current_user）：返回空列表

    与 review_gene 的权限模型一致，避免列表里出现用户实际无权审核的条目。
    """
    # 兼容旧调用：未传 current_user 时退回到"全部"以便测试场景灵活，但
    # 这条路径 API 层不会走到（API 必传 current_user）。
    if current_user is None:
        result = await db.execute(
            select(Gene)
            .where(
                Gene.review_status.in_([
                    GeneReviewStatus.pending_owner,
                    GeneReviewStatus.pending_admin,
                ]),
                not_deleted(Gene),
            )
            .order_by(Gene.created_at.desc())
        )
        return [_gene_to_dict(g) for g in result.scalars().all()]

    # 超管 → 全部
    if getattr(current_user, "is_super_admin", False):
        result = await db.execute(
            select(Gene)
            .where(
                Gene.review_status.in_([
                    GeneReviewStatus.pending_owner,
                    GeneReviewStatus.pending_admin,
                ]),
                not_deleted(Gene),
            )
            .order_by(Gene.created_at.desc())
        )
        return [_gene_to_dict(g) for g in result.scalars().all()]

    # 普通用户 → 查其作为 admin 的所有 org_id
    from app.models.org_membership import OrgMembership, OrgRole

    admin_orgs_result = await db.execute(
        select(OrgMembership.org_id).where(
            OrgMembership.user_id == current_user.id,
            OrgMembership.role == OrgRole.admin,
            OrgMembership.deleted_at.is_(None),
        )
    )
    admin_org_ids = [row[0] for row in admin_orgs_result.all()]
    if not admin_org_ids:
        # 既不是超管也不是任何 org admin → 无可见待审项
        return []

    result = await db.execute(
        select(Gene)
        .where(
            Gene.review_status.in_([
                GeneReviewStatus.pending_owner,
                GeneReviewStatus.pending_admin,
            ]),
            Gene.org_id.in_(admin_org_ids),
            not_deleted(Gene),
        )
        .order_by(Gene.created_at.desc())
    )
    return [_gene_to_dict(g) for g in result.scalars().all()]


async def get_gene_activity(db: AsyncSession, limit: int = 50) -> list[dict]:
    result = await db.execute(
        select(GeneEffectLog, Gene.slug, Gene.name)
        .join(Gene, GeneEffectLog.gene_id == Gene.id)
        .where(Gene.deleted_at.is_(None))
        .order_by(GeneEffectLog.created_at.desc())
        .limit(limit)
    )
    items = []
    for log, slug, name in result:
        items.append({
            "id": log.id,
            "instance_id": log.instance_id,
            "gene_slug": slug,
            "gene_name": name,
            "metric_type": log.metric_type,
            "value": log.value,
            "context": log.context,
            "created_at": log.created_at,
        })
    return items


async def get_gene_matrix(db: AsyncSession) -> list[dict]:
    result = await db.execute(
        select(
            InstanceGene.instance_id,
            Gene.slug,
            InstanceGene.status,
        )
        .join(Gene, InstanceGene.gene_id == Gene.id)
        .where(not_deleted(InstanceGene), Gene.deleted_at.is_(None))
        .order_by(InstanceGene.instance_id, Gene.slug)
    )
    return [
        {"instance_id": r[0], "gene_slug": r[1], "status": r[2]}
        for r in result
    ]


async def get_co_install_analysis(db: AsyncSession, min_count: int = 2) -> list[CoInstallPair]:
    ig1 = InstanceGene.__table__.alias("ig1")
    ig2 = InstanceGene.__table__.alias("ig2")
    g1 = Gene.__table__.alias("g1")
    g2 = Gene.__table__.alias("g2")

    q = (
        select(
            g1.c.slug.label("gene_a_slug"),
            g2.c.slug.label("gene_b_slug"),
            func.count().label("co_count"),
        )
        .select_from(ig1)
        .join(ig2, (ig1.c.instance_id == ig2.c.instance_id) & (ig1.c.gene_id < ig2.c.gene_id))
        .join(g1, ig1.c.gene_id == g1.c.id)
        .join(g2, ig2.c.gene_id == g2.c.id)
        .where(
            ig1.c.deleted_at.is_(None),
            ig2.c.deleted_at.is_(None),
            g1.c.deleted_at.is_(None),
            g2.c.deleted_at.is_(None),
        )
        .group_by(g1.c.slug, g2.c.slug)
        .having(func.count() >= min_count)
        .order_by(func.count().desc())
    )
    result = await db.execute(q)
    return [
        CoInstallPair(gene_a_slug=r[0], gene_b_slug=r[1], co_install_count=r[2])
        for r in result
    ]


async def publish_gene_to_market(
    db: AsyncSession, gene_id: str, user_id: str | None = None,
) -> dict:
    """将组织/个人 library 中的 gene 提交到公共市场审核。

    流程：
      1. 校验来源（仅 manual / agent 可发布）
      2. 切换 visibility=public
      3. review_status=pending_owner（等待组织 admin 审核）
      4. is_published=False（审核通过前不在公共市场出现）
    """
    result = await db.execute(
        select(Gene).where(Gene.id == gene_id, not_deleted(Gene))
    )
    gene = result.scalar_one_or_none()
    if not gene:
        raise NotFoundError(f"技能基因不存在: {gene_id}")

    if gene.source not in ("manual", "agent"):
        raise ConflictError("仅 manual 或 agent 来源的技能基因可以发布到基因市场")

    if gene.visibility == "public" and gene.review_status == GeneReviewStatus.approved:
        raise ConflictError("该技能基因已在公共市场上架")

    gene.visibility = "public"
    gene.is_published = False
    gene.review_status = GeneReviewStatus.pending_owner

    event = EvolutionEvent(
        instance_id=gene.created_by_instance_id or "",
        event_type=EvolutionEventType.variant_published,
        gene_id=gene.id,
        gene_slug=gene.slug,
        gene_name=gene.name,
        details=json.dumps({"action": "publish_to_market", "user_id": user_id}),
    )
    db.add(event)
    await db.commit()

    return {
        "id": gene.id,
        "slug": gene.slug,
        "is_published": gene.is_published,
        "review_status": gene.review_status,
        "visibility": gene.visibility,
    }


# ═══════════════════════════════════════════════════
#  Target 解析 + Fork
# ═══════════════════════════════════════════════════


def resolve_target_attrs(
    target: str,
    *,
    user_id: str | None,
    org_id: str | None,
) -> dict:
    """根据上传/Fork 目标 (personal/org/public) 派生 gene 行的归属字段。

    返回字典直接合并进 Gene(...) 构造或 GeneCreateRequest：
      - personal：归属个人，无需审核，立即可用
      - org：归属组织，pending_owner 等组织 admin 审核
      - public：归属上传者所在组织（用于追溯背书方），pending_owner 等组织 admin 审核
    """
    if target == "personal":
        if not user_id:
            raise BadRequestError("personal 目标必须提供 user_id")
        return {
            "visibility": "personal",
            "org_id": None,
            "created_by": user_id,
            "is_published": True,
            "review_status": None,
        }
    if target == "org":
        if not org_id or not user_id:
            raise BadRequestError("org 目标必须提供 org_id 与 user_id")
        return {
            "visibility": "org_private",
            "org_id": org_id,
            "created_by": user_id,
            "is_published": False,
            "review_status": GeneReviewStatus.pending_owner,
        }
    if target == "public":
        if not org_id or not user_id:
            raise BadRequestError("public 目标必须提供 org_id 与 user_id（组织 admin 背书）")
        return {
            "visibility": "public",
            "org_id": org_id,
            "created_by": user_id,
            "is_published": False,
            "review_status": GeneReviewStatus.pending_owner,
        }
    raise BadRequestError(f"未知上传目标: {target}")


async def fork_gene_to_library(
    db: AsyncSession,
    source_identifier: str,
    target: str,
    *,
    current_user,  # app.models.user.User —— 取 id / is_super_admin / current_org_id
    org_id: str | None = None,
) -> dict:
    """从任意 scope（personal / org / public）fork 一份 gene 到 personal / org / public library。

    source_identifier:
      - 本地 gene：传 gene.id（UUID）。三向 fork 后同一个 slug 可能在 DB 中并存多条
        active 行（个人 / 组织 / 公共），按 slug 查会 MultipleResultsFound；按 id 唯一。
      - 外部 aggregator 来源：本地 DB 找不到时回退到聚合器，identifier 当作 slug 使用。

    权限规则（current_user.is_super_admin=True 时全部放行）：
      - 源是 personal（org_id IS NULL）：仅 gene.created_by == current_user.id 可 fork
      - 源是 org（org_id 非空且 visibility != public）：current_user 必须是该 org 的有效成员
      - 源是 public（visibility == public）：任意登录用户可 fork
    """
    if target not in ("personal", "org", "public"):
        raise BadRequestError("fork 目标必须是 personal / org / public 之一")

    # 目标归属：org_id 显式传入优先，否则取 current_user.current_org_id
    effective_org_id = org_id if org_id is not None else getattr(current_user, "current_org_id", None)
    attrs = resolve_target_attrs(target, user_id=current_user.id, org_id=effective_org_id)

    # ── 1. 优先本地 DB 按 gene.id 查源（UUID 唯一） ───────────────────
    source = (await db.execute(
        select(Gene).where(Gene.id == source_identifier, not_deleted(Gene))
    )).scalar_one_or_none()

    if source is not None:
        # ── 1a. 按源 scope 校验权限 ────────────────────────────────────
        # 源 scope 分类（与 resolve_target_attrs 落库规则严格对应）
        is_personal_source = source.org_id is None and source.created_by is not None
        is_public_source = source.visibility == "public"
        # 其余情形（org_id 非空且 visibility != public）视作 org scope
        is_org_source = (not is_personal_source) and (not is_public_source) and source.org_id is not None

        if not getattr(current_user, "is_super_admin", False):
            if is_personal_source:
                if source.created_by != current_user.id:
                    raise ForbiddenError(
                        message="仅本人可 fork 自己的个人技能",
                        message_key="errors.gene.fork_personal_forbidden",
                    )
            elif is_org_source:
                # 必须是该 org 的有效成员（任意角色）
                from app.models.org_membership import OrgMembership
                membership = (await db.execute(
                    select(OrgMembership).where(
                        OrgMembership.user_id == current_user.id,
                        OrgMembership.org_id == source.org_id,
                        OrgMembership.deleted_at.is_(None),
                    )
                )).scalar_one_or_none()
                if membership is None:
                    raise ForbiddenError(
                        message="仅本组织成员可 fork 该组织技能",
                        message_key="errors.gene.fork_org_forbidden",
                    )
            # is_public_source：任意登录用户均可，无须额外校验

        # 复制内容字段，slug 沿用源 slug 作为基准（冲突时下面追后缀）
        source_slug = source.slug
        source_name = source.name
        source_description = source.description
        source_short_description = source.short_description
        source_category = source.category
        source_tags = source.tags
        source_icon = source.icon
        source_version = source.version
        source_manifest = source.manifest
        source_dependencies = source.dependencies
        source_synergies = source.synergies
        source_parent_id: str | None = source.id
    else:
        # ── 2. 兜底：本地无此 id（外部聚合器来源），把 identifier 当 slug 查 ───
        try:
            detail = await get_aggregator().get_skill(source_identifier)
        except Exception:
            detail = None
        if detail is None:
            raise NotFoundError(f"源基因不存在: {source_identifier}")
        # 外部源默认视为公共（聚合器返回的就是外部市场内容），不再额外鉴权
        source_slug = source_identifier
        source_name = detail.name
        source_description = detail.description
        source_short_description = detail.short_description
        source_category = detail.category
        source_tags = _json_dumps(detail.tags or [])
        source_icon = detail.icon
        source_version = detail.version or "1.0.0"
        source_manifest = _json_dumps(detail.manifest or {})
        source_dependencies = _json_dumps(detail.dependencies or [])
        source_synergies = _json_dumps(detail.synergies or [])
        source_parent_id = None  # 外部源没有本地 id 可指

    # ── 3. 计算副本 slug：在目标 org_id 内重名时追加短后缀 ──────────
    import uuid

    new_slug = source_slug
    existing = await db.execute(
        select(Gene).where(
            Gene.slug == new_slug,
            Gene.org_id == attrs["org_id"],
            not_deleted(Gene),
        )
    )
    if existing.scalar_one_or_none() is not None:
        suffix = uuid.uuid4().hex[:6]
        new_slug = f"{source_slug}-fork-{suffix}"

    fork = Gene(
        name=source_name or source_slug,
        slug=new_slug,
        description=source_description,
        short_description=source_short_description,
        category=source_category,
        tags=source_tags,
        source=GeneSource.manual,
        source_ref=f"fork:{source_slug}",
        icon=source_icon,
        version=source_version,
        manifest=source_manifest,
        dependencies=source_dependencies,
        synergies=source_synergies,
        parent_gene_id=source_parent_id,
        visibility=attrs["visibility"],
        org_id=attrs["org_id"],
        created_by=attrs["created_by"],
        is_published=attrs["is_published"],
        review_status=attrs["review_status"],
        # fork 出来的副本是本地新行；source_registry 标 local 与 create_gene 保持一致
        source_registry="local",
    )
    db.add(fork)
    await db.commit()
    await db.refresh(fork)
    return _gene_to_dict(fork)
