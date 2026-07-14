"""Gene Evolution Ecosystem service: CRUD, install/learn engine, rating, evolution."""

import asyncio
import hashlib
import hmac
import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Coroutine
from urllib.parse import urlencode

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_nodeskclaw_webhook_base_url, settings
from app.core.exceptions import AppException, BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.core.version_compare import compare_versions
from app.models.base import not_deleted
from app.models.corridor import HumanHex
from app.models.gene import (
    ContentVisibility,
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
from app.models.gene_overwrite_submission import GeneOverwriteSubmission
from app.models.instance import Instance, InstanceStatus
from app.models.org_required_gene import OrgRequiredGene
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


async def _compute_newer_sibling_versions(
    db: AsyncSession,
    genes: list[Gene],
    *,
    user_id: str | None,
) -> dict[str, list[dict]]:
    """单向检测：只为 visibility=personal 的 Gene 计算"组织库/公共市场是否
    比它新"，org_private/public 的 Gene 恒为空数组，不查询、不计算。

    注意：假定 `genes` 列表中的 personal gene 全部属于同一个 `user_id`
    （当前唯一调用方 `_list_genes_local` 按 created_by==user_id 过滤后才会
    传进来，天然满足）；如果未来有新调用方传入混合多用户的 gene 列表，这里的
    `member_org_ids` 圈定逻辑就不再准确，需要按 gene 逐个求其所有者的
    member_org_ids，而不是复用同一份。
    """
    # 只挑出个人库的 gene，org_private/public 直接跳过（单向检测，设计明确要求）
    personal_genes = [g for g in genes if g.visibility == ContentVisibility.personal]
    if not personal_genes:
        return {}

    lineage_group_ids = {g.lineage_group_id for g in personal_genes}

    # 查出当前用户所属的所有组织，用于圈定"哪些 org_private 副本对该用户可见"
    # ——同血缘技能可能被多个 org fork 过，但只有用户实际所在的 org 才算"可见的落后提示来源"
    member_org_ids: set[str] = set()
    if user_id:
        from app.models.org_membership import OrgMembership
        rows = await db.execute(
            select(OrgMembership.org_id).where(
                OrgMembership.user_id == user_id, not_deleted(OrgMembership),
            )
        )
        member_org_ids = {r[0] for r in rows.all()}

    # public：审核通过 OR 历史无审核态（review_status IS NULL，向后兼容老数据），
    # 与 _list_genes_local / LocalAdapter.search_skills 的 public 分支保持一致；
    # org_private：不需要 review_status 检查（org 内部可见性本身就是审核对象），
    # 只需 is_published 兜底——与 _list_genes_local 对 org_private 的处理一致
    public_filter = and_(
        Gene.visibility == ContentVisibility.public,
        or_(
            Gene.review_status == GeneReviewStatus.approved,
            Gene.review_status.is_(None),
        ),
    )
    org_private_filter = (
        and_(Gene.visibility == ContentVisibility.org_private, Gene.org_id.in_(member_org_ids))
        if member_org_ids else False
    )
    visibility_filter = or_(public_filter, org_private_filter)
    result = await db.execute(
        select(Gene.id, Gene.lineage_group_id, Gene.visibility, Gene.org_id, Gene.version)
        .where(
            Gene.lineage_group_id.in_(lineage_group_ids),
            not_deleted(Gene),
            # 关键：待审核（pending_owner/pending_admin）或被拒绝的 sibling 一律
            # 不应该出现在"落后提示"里——这些内容在产品其它任何地方都不可见/不可
            # fork，提示用户"有更新版本"但点不到会造成困惑（复现场景：fork 到
            # org 但不 bypass_review，走默认 pending_owner + is_published=False）
            Gene.is_published.is_(True),
            Gene.visibility.in_([ContentVisibility.org_private, ContentVisibility.public]),
            visibility_filter,
        )
    )
    candidates = result.all()

    # 批量查组织名，避免 N+1
    org_ids_needing_name = {row.org_id for row in candidates if row.visibility == ContentVisibility.org_private and row.org_id}
    org_names: dict[str, str] = {}
    if org_ids_needing_name:
        from app.models.organization import Organization
        org_rows = await db.execute(select(Organization.id, Organization.name).where(Organization.id.in_(org_ids_needing_name)))
        org_names = {r.id: r.name for r in org_rows.all()}

    by_group: dict[str, list] = {}
    for row in candidates:
        by_group.setdefault(row.lineage_group_id, []).append(row)

    output: dict[str, list[dict]] = {}
    for gene in personal_genes:
        siblings = by_group.get(gene.lineage_group_id, [])
        newer = []
        for row in siblings:
            cmp_result = compare_versions(row.version, gene.version)
            if cmp_result is not None and cmp_result > 0:
                newer.append({
                    "visibility": row.visibility,
                    "org_id": row.org_id,
                    "org_name": org_names.get(row.org_id) if row.org_id else None,
                    "version": row.version,
                })
        output[gene.id] = newer
    return output


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
        # org_private/public 结果恒为空数组：单向落后检测只对 personal 计算，
        # 这条聚合器路径（list_genes 除 personal 外全部走这里）需要同步给出
        # 静态默认值，否则前端拿不到这个 key（详见 _compute_newer_sibling_versions）
        "newer_sibling_versions": [],
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
    # 单向落后检测：只对 personal 可见性计算（_compute_newer_sibling_versions
    # 内部会自行跳过非 personal 的 gene，这里统一调用简化调用方逻辑）
    newer_versions_by_id = await _compute_newer_sibling_versions(db, genes, user_id=user_id)
    items = []
    for g in genes:
        item = _gene_to_dict(g)
        item["newer_sibling_versions"] = newer_versions_by_id.get(g.id, [])
        items.append(item)
    return items, total


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


async def _assert_user_can_view_gene_by_slug(
    db: AsyncSession,
    slug: str,
    current_user,
) -> None:
    """跨组织可见性守卫：按 slug 查 DB 中是否存在 org_private / personal 命中条目，
    如果有且不属于当前用户/组织，抛 403。

    可见性规则：
      - personal：仅作者本人 + 平台超管可见
      - org_private：仅 org 成员 + 平台超管可见（用 current_user.current_org_id 判定）
      - public（含 aggregator 远程仓库）：任何登录用户可见
      - DB 完全不存在该 slug（纯远程公共仓库的 skill）：放行

    若同 slug 在多个 scope 并存（fork 三向架构允许），任一 scope 命中用户 → 放行。
    所有 scope 均不可见 → 403。
    """
    # super_admin 直接放行：审核 / 故障排查需要全域可见
    if getattr(current_user, "is_super_admin", False):
        return

    # 列出 DB 中所有同 slug 未删除条目
    rows = (await db.execute(
        select(Gene).where(Gene.slug == slug, not_deleted(Gene))
    )).scalars().all()

    if not rows:
        # DB 中无此 slug → 视为远程公共仓库 skill，放行
        return

    user_id = current_user.id
    user_org_id = getattr(current_user, "current_org_id", None)

    for gene in rows:
        vis = gene.visibility
        if vis == "public":
            return
        if vis == "personal" and gene.created_by == user_id:
            return
        if vis == "org_private" and user_org_id and gene.org_id == user_org_id:
            return

    # 所有同 slug 条目都不属于当前用户/组织
    raise ForbiddenError(
        "您无权查看该技能基因",
        message_key="errors.gene.cross_org_forbidden",
    )


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


async def get_gene_by_name_in_scope(
    db: AsyncSession,
    name: str,
    *,
    visibility: str,
    org_id: str | None = None,
    created_by: str | None = None,
) -> Gene | None:
    """按 (trim+忽略大小写的 name, scope) 精确定位一条未删除 gene。

    与 3 条 uq_genes_name_* partial unique index 语义一一对应：
      - personal：按 (小写trim后的 name, created_by) 判重
      - org_private：按 (小写trim后的 name, org_id) 判重
      - public：全局按小写trim后的 name 判重，不再附加 org_id/created_by 条件

    用 first() 而非 scalar_one_or_none()——理论上 scope 内不会有多条，但按
    项目既有踩坑经验（同 slug 跨 scope 并存过 MultipleResultsFound），一律
    用 first() 更保守。
    """
    normalized = name.strip().lower()
    stmt = select(Gene).where(
        func.lower(func.trim(Gene.name)) == normalized,
        Gene.visibility == visibility,
        not_deleted(Gene),
    )
    if visibility == ContentVisibility.personal:
        stmt = stmt.where(Gene.created_by == created_by)
    elif visibility == ContentVisibility.org_private:
        stmt = stmt.where(Gene.org_id == org_id)
    result = await db.execute(stmt)
    return result.scalars().first()


async def _rewire_gene_references(db: AsyncSession, old_gene_id: str, new_gene_id: str) -> None:
    """覆盖上传软删旧 Gene、插入新 id 新行后，把指向旧行的"当前生效状态"引用

    批量改指向新行，避免旧行被软删之后，已安装该技能的实例、已强制要求该
    技能的组织，因为 join 时过滤 `Gene.deleted_at IS NULL` 而把这些记录
    "丢"掉（`get_instance_genes()` / 组织强制技能列表等场景）。

    只重接 InstanceGene（已装技能）、OrgRequiredGene（组织强制要求技能）
    这两类"当前生效状态"引用，不改 GeneRating / GeneEffectLog 等历史记录——
    那些是针对当时具体内容给出的评分/效果数据，不该被静默转嫁到新内容上。
    """
    await db.execute(
        update(InstanceGene)
        .where(InstanceGene.gene_id == old_gene_id, not_deleted(InstanceGene))
        .values(gene_id=new_gene_id)
    )
    await db.execute(
        update(OrgRequiredGene)
        .where(OrgRequiredGene.gene_id == old_gene_id, not_deleted(OrgRequiredGene))
        .values(gene_id=new_gene_id)
    )
    await db.commit()


async def create_gene(
    db: AsyncSession, req: GeneCreateRequest, user_id: str | None = None, org_id: str | None = None,
    visibility: str | None = None,
    review_status: str | None = None,
) -> dict:
    resolved_visibility = visibility or req.visibility

    # 冲突判定按 (slug, org_id) 进行，对齐 partial unique index `uq_genes_slug_org_active`。
    # personal scope（org_id IS NULL）下，索引允许多个用户共用同 slug，因此用 created_by
    # 进一步限定到"当前用户的 personal 同 slug"，避免误报。
    existing = await get_gene_by_slug_in_scope(
        db, req.slug, org_id=org_id, created_by=user_id,
    )
    # 名称查重按 scope 分别进行（personal 按用户、org 按组织、public 全局），
    # 对齐新增的 3 条 uq_genes_name_* partial unique index。
    existing_name = await get_gene_by_name_in_scope(
        db, req.name, visibility=resolved_visibility, org_id=org_id, created_by=user_id,
    )
    if existing is not None and existing_name is not None and existing_name is not existing:
        # slug 和 name 分别命中了两条不同的行：这才是真正的"无关行"冲突，
        # overwrite 的语义只是"允许覆盖 slug 命中的那一条"，不能顺带删掉
        # 一条名字撞车但完全无关的记录，因此即使 overwrite=True 也直接拒绝。
        #
        # 注意 existing 为 None（slug 没命中任何行）时不能进这个分支：
        # 技能名称转 slug 是确定性生成的（见 _slugify_gene_name），若旧记录
        # 是通过其他入口（如手动创建）用不同规则生成的 slug，重新上传时会
        # 出现"slug 查不到、但 name 精确命中旧记录"的情况——这里 existing_name
        # 就是唯一需要覆盖的目标，不是无关行，必须走下面的覆盖逻辑。
        raise ConflictError(f"技能名称 '{req.name}' 已存在")
    old_gene_id: str | None = None
    # 覆盖时继承旧行的血缘分组 id，让 personal/org/public 三向副本、以及
    # 同一血缘下的历次覆盖版本能够被关联到一起；全新创建则在下面用新行
    # 自己的 id 作为血缘起点。
    old_lineage_group_id: str | None = None
    if existing or existing_name:
        if req.overwrite:
            # 覆盖模式：existing 和 existing_name 此时要么是同一行，要么只有
            # 一个非 None（slug 对不上但 name 精确命中了同一技能的旧记录），
            # 软删这一行即可，不会误删无关记录。
            target = existing or existing_name
            if target:
                # 版本号校验：覆盖只允许 >= 当前版本号（同版本号覆盖也放行，
                # 属于产品侧明确决策"1.A"），禁止版本倒退；任一侧格式不合法
                # 也直接拒绝，不能装作知道谁新谁旧。必须在软删旧行之前校验，
                # 校验失败时不能产生任何副作用。
                cmp_result = compare_versions(req.version, target.version)
                if cmp_result is None:
                    raise ConflictError(f"版本号格式不合法：'{req.version}'")
                if cmp_result < 0:
                    raise ConflictError(
                        f"新版本号 '{req.version}' 低于当前版本 '{target.version}'，不允许版本倒退"
                    )
                # 覆盖会软删旧行、插入一条全新 id 的新行，已安装/已被组织
                # 强制要求的记录引用的是旧 id，先记下来，插入新行后重接。
                # lineage_group_id 也必须在 soft_delete 之前读取——软删本身
                # 不会清空该字段，但这里保持"先读后删"的顺序更保险。
                old_gene_id = target.id
                old_lineage_group_id = target.lineage_group_id
                target.soft_delete()
            await db.commit()
        elif existing:
            raise ConflictError(f"基因 slug '{req.slug}' 已存在")
        else:
            raise ConflictError(f"技能名称 '{req.name}' 已存在")

    _validate_skill_metadata(req.manifest, req.short_description, req.description)

    # lineage_group_id 是 NOT NULL 列，必须和新行同时写入，因此这里显式生成
    # 新行的 id（而不是依赖 Column default 在 flush 时才生成），确保全新
    # 创建场景下 lineage_group_id 能取到"自己的 id"。
    new_gene_id = str(uuid.uuid4())
    gene = Gene(
        id=new_gene_id,
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
        visibility=resolved_visibility,
        review_status=review_status,
        created_by=user_id,
        org_id=org_id,
        # 标记为本地创建，确保前端"删除/编辑"等仅对本地 gene 显示的入口可见
        # （外部 registry 同步走 genehub_client，自带 registry_id；不进此路径）
        source_registry="local",
        lineage_group_id=old_lineage_group_id or new_gene_id,
    )
    db.add(gene)
    try:
        await db.commit()
    except IntegrityError as e:
        # 极小概率竞态：两个请求同时通过了上面的预检查。DB 唯一索引在此兜底，
        # 统一转换成 ConflictError，不暴露内部约束名等实现细节。
        await db.rollback()
        raise ConflictError(f"基因 slug '{req.slug}' 或名称 '{req.name}' 已存在") from e
    await db.refresh(gene)

    if old_gene_id is not None:
        await _rewire_gene_references(db, old_gene_id, gene.id)

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
                    await _apply_manifest_actions(fs, manifest, adapter, skill_name)
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
                    await _apply_manifest_actions(fs, manifest, adapter, skill_name)
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
    skill_name: str | None = None,
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

    # 文件夹上传的技能包附属文件（reference/example/assets 等）
    # 随 SKILL.md 一起部署到实例技能目录，否则 agent 只能读到 SKILL.md
    if skill_name:
        extra_files: dict[str, str] = {}
        for key in ("assets", "references"):
            value = manifest.get(key)
            if isinstance(value, dict):
                extra_files.update(value)
        if extra_files:
            await adapter.deploy_skill_files(fs, skill_name, extra_files)


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
            await _apply_manifest_actions(fs, manifest, adapter, skill_name)
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
            await _apply_manifest_actions(fs, manifest, adapter, gene_obj.slug)
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

    # 名称查重：下面插入的 variant 未显式传 visibility，落在模型默认的 public
    # scope，因此按 public scope 校验 name 是否已存在，与 create_gene() 的
    # 查重语义保持一致，命中直接拒绝，不静默改名。
    existing_name = await get_gene_by_name_in_scope(
        db, name, visibility=ContentVisibility.public,
    )
    if existing_name is not None:
        raise ConflictError(f"技能名称 '{name}' 已存在")

    # variant 是 AI 进化出的新技能，不是父技能"换了个 scope"的副本，不应
    # 继承父技能的 lineage_group_id。lineage_group_id 是 NOT NULL 列，必须
    # 和新行同时写入，因此显式生成新行的 id（而不是依赖 Column default 在
    # flush 时才生成），用自己的新 id 单独成组（与 create_gene() 全新创建
    # 场景的处理方式保持一致）。
    variant_id = str(uuid.uuid4())
    variant = Gene(
        id=variant_id,
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
        lineage_group_id=variant_id,
    )
    db.add(variant)

    ig.variant_published = True
    await _record_evolution(
        db, instance_id, EvolutionEventType.variant_published, parent.name,
        gene_slug=parent.slug, gene_id=gene_id,
        details={"variant_gene_id": variant.id, "variant_slug": slug},
    )
    try:
        await db.commit()
    except IntegrityError as e:
        # 极小概率竞态：预检查通过后，另一请求在 commit 之前抢先插入了同名
        # 变体。DB 唯一索引在此兜底，统一转换成 ConflictError。
        await db.rollback()
        raise ConflictError(f"技能名称 '{name}' 已存在") from e
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

    gene_name = meta.get("gene_name", f"agent-gene-{payload.task_id[:8]}")

    # 名称查重：下面插入的 gene 未显式传 visibility，落在模型默认的 public
    # scope，因此按 public scope 校验 name 是否已存在，命中直接拒绝。
    existing_name = await get_gene_by_name_in_scope(
        db, gene_name, visibility=ContentVisibility.public,
    )
    if existing_name is not None:
        raise ConflictError(f"技能名称 '{gene_name}' 已存在")

    # Agent 自主创造的新技能，是一条全新的血缘起点，不存在"父技能"可继承。
    # lineage_group_id 是 NOT NULL 列，必须和新行同时写入，因此显式生成新行
    # 的 id（而不是依赖 Column default 在 flush 时才生成），用自己的新 id
    # 单独成组（与 create_gene() 全新创建场景的处理方式保持一致）。
    new_gene_id = str(uuid.uuid4())
    gene = Gene(
        id=new_gene_id,
        name=gene_name,
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
        lineage_group_id=new_gene_id,
    )
    db.add(gene)
    try:
        await db.commit()
    except IntegrityError as e:
        # 极小概率竞态：预检查通过后，另一请求在 commit 之前抢先插入了同名
        # 基因。DB 唯一索引在此兜底，统一转换成 ConflictError。
        await db.rollback()
        raise ConflictError(f"技能名称 '{gene_name}' 已存在") from e
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


async def review_gene_overwrite_submission(
    db: AsyncSession,
    submission_id: str,
    action: str,
    reason: str | None = None,
    *,
    current_user=None,
) -> dict:
    """审核 fork 覆盖 org/public 的暂存提交。

    权限跟 review_gene() 完全一致（该 gene 所属 org 的 admin 或平台超管），
    但不复用 bypass_review——提交者自己是 admin 也必须显式调用这个函数才
    会生效，不会因为身份而自动跳过。
    """
    from app.models.org_membership import OrgMembership, OrgRole

    # ── 查提交记录 + 状态校验 ──────────────────────────────────────────
    # with_for_update() 对这一行加悲观锁：这张暂存表会被多个组织 admin 并发
    # 审核同一条提交（比单用户自己的 fork 覆盖并发概率高得多），如果没有行锁，
    # 两个 approve/reject 请求可能都在对方 commit 之前读到同一个 pending 状态，
    # 都通过下面的状态守卫，最终谁后 commit 谁的结果就"赢"——可能出现
    # "已批准并发布到注册表的 Gene 行，其提交记录却被覆盖标成 rejected"这种
    # 审计记录与实际数据库状态不一致的情况。加锁后，后到的请求会阻塞到前一个
    # 事务提交为止，再重新读到的就是已经终态的 approved/rejected，会被下面的
    # 状态守卫正确拦截。
    result = await db.execute(
        select(GeneOverwriteSubmission)
        .where(GeneOverwriteSubmission.id == submission_id, not_deleted(GeneOverwriteSubmission))
        .with_for_update()
    )
    submission = result.scalar_one_or_none()
    if not submission:
        raise NotFoundError("覆盖提交不存在")
    if submission.review_status not in (GeneReviewStatus.pending_owner, GeneReviewStatus.pending_admin):
        raise BadRequestError(f"当前状态 '{submission.review_status}' 不可审核")

    # ── 权限校验：超管 / 该提交所属 org 的 admin，与 review_gene() 保持一致 ──
    if current_user is not None and not getattr(current_user, "is_super_admin", False):
        membership = (await db.execute(
            select(OrgMembership).where(
                OrgMembership.user_id == current_user.id,
                OrgMembership.org_id == submission.org_id,
                OrgMembership.role == OrgRole.admin,
                OrgMembership.deleted_at.is_(None),
            )
        )).scalar_one_or_none()
        if membership is None:
            raise ForbiddenError(
                message="您无权审核此提交（需该技能所属组织的管理员）",
                message_key="errors.gene.review_forbidden",
            )

    if action == "reject":
        # 拒绝：只翻转提交记录本身的状态，绝不触碰 genes 表。
        # 注意：这里的状态守卫只放行 pending_owner/pending_admin（上面已校验），
        # 比 review_gene() 的 reject 分支（允许任意状态转 rejected）更严格——
        # 这是刻意的收紧，不是遗漏。review_gene() 面对的是单条 gene，谁改都是
        # 同一行；这里面对的是可被多个组织 admin 并发处理的暂存提交队列，
        # 一旦已经 approved/rejected 就是终态，不允许再被覆盖，否则会破坏
        # 审计记录与实际 genes 表状态的一致性。未来如无必要不要为了"跟
        # review_gene() 保持一致"而放宽这里。
        submission.review_status = GeneReviewStatus.rejected
        submission.reject_reason = reason
        await db.commit()
        return {"review_status": submission.review_status, "stale": False}

    if action != "approve":
        raise BadRequestError(f"未知审核动作: {action}")

    # ── 过期重新校验：提交后、审核前，target 可能已被另一条已批准提交替换掉，
    # 或者被别的流程软删。三种情况都视为"过期"，自动转 rejected 而不是报错，
    # 避免出现两条并发提交都想替换同一行时其中一条 500。
    target = (await db.execute(
        select(Gene).where(Gene.id == submission.target_gene_id, not_deleted(Gene))
    )).scalar_one_or_none()
    stale = (
        target is None
        or target.lineage_group_id != submission.lineage_group_id
        or compare_versions(submission.version, target.version) != 1
    )
    if stale:
        submission.review_status = GeneReviewStatus.rejected
        submission.reject_reason = "目标技能已发生变化，请重新提交"
        await db.commit()
        return {"review_status": submission.review_status, "stale": True}

    # ── 批准：软删旧行 + 插入新行，内容取自提交暂存的快照 ────────────────
    old_gene_id = target.id
    target.soft_delete()

    # lineage_group_id 是 NOT NULL 列，必须和新行同时写入，因此这里显式生成
    # 新行的 id 并把 id / lineage_group_id 一并传进 Gene(...) 构造函数
    # （Task 7/8/9 已验证：构造完再赋值属性不可靠，必须走构造函数参数）。
    new_gene_id = str(uuid.uuid4())
    new_gene = Gene(
        id=new_gene_id,
        name=submission.name,
        slug=submission.slug,
        description=submission.description,
        short_description=submission.short_description,
        category=submission.category,
        tags=submission.tags,
        source=submission.source,
        source_ref=submission.source_ref,
        icon=submission.icon,
        version=submission.version,
        manifest=submission.manifest,
        dependencies=submission.dependencies,
        synergies=submission.synergies,
        parent_gene_id=submission.source_gene_id,
        visibility=submission.visibility,
        org_id=submission.org_id,
        created_by=submission.created_by,
        is_published=True,
        review_status=GeneReviewStatus.approved,
        source_registry="local",
        lineage_group_id=submission.lineage_group_id,
    )
    db.add(new_gene)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise ConflictError(f"技能名称 '{submission.name}' 或 slug '{submission.slug}' 已存在") from e
    await db.refresh(new_gene)

    # 把 InstanceGene / OrgRequiredGene 等"当前生效状态"引用从旧行重接到新行，
    # 避免旧行软删后被 `Gene.deleted_at IS NULL` 过滤掉导致这些记录"查不到人"。
    await _rewire_gene_references(db, old_gene_id, new_gene.id)

    # 注意：上面软删旧行 + 插入新行 + _rewire_gene_references() 各自的 commit，
    # 与下面 submission.review_status = approved 这次 commit 不是同一个事务——
    # 如果进程在它们之间崩溃，new_gene 已经落库、is_published=True、且已重接
    # 好所有引用（也就是说新内容已经实际生效），但 submission 还停在
    # pending_owner/pending_admin。这比 fork_gene_to_library 里同类型的
    # 两次分开 commit（搜 "极小概率竞态" 附近）后果更差：那边最坏是短暂的
    # 引用悬空，这里则是 submission 的审核状态和 genes 表的真实状态永久不一致
    # ——而且如果有人这时候重试 approve，过期重新校验会发现 target（按已经
    # 被软删的旧 target_gene_id 查）已经不在了，误判成"目标技能已发生变化"
    # 而自动转 rejected，这个提示语在这种场景下是错的（不是别人动了 target，
    # 是这条提交自己上一次跑了一半）。目前不在本任务范围内做成原子操作或
    # 幂等重试，先在这里留痕，后续作为独立 follow-up 处理。
    submission.review_status = GeneReviewStatus.approved
    await db.commit()

    if new_gene.visibility == "public":
        _fire_task(_push_approved_gene_to_registry(new_gene))

    return {"review_status": submission.review_status, "stale": False, "gene_id": new_gene.id}


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
                # 同步补齐 reference/example 等附属文件，避免刷新后只剩 SKILL.md
                extra_files = {
                    **(manifest.get("assets") if isinstance(manifest.get("assets"), dict) else {}),
                    **(manifest.get("references") if isinstance(manifest.get("references"), dict) else {}),
                }
                if extra_files:
                    await adapter.deploy_skill_files(fs, skill_name, extra_files)

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
    """获取当前用户可审核的待审列表，合并展示新建 Gene（kind=new）与 fork
    覆盖 org/public 目标产生的 GeneOverwriteSubmission（kind=overwrite）。

    权限范围：
      - 平台超管：返回所有 pending_owner / pending_admin
      - 任意组织 admin：仅返回其作为 admin 的 org 下的待审条目
      - 其他用户（包括未传 current_user）：返回空列表

    与 review_gene / review_gene_overwrite_submission 的权限模型一致，
    避免列表里出现用户实际无权审核的条目。
    """
    # 兼容旧调用：未传 current_user 时退回到"全部"以便测试场景灵活，但
    # 这条路径 API 层不会走到（API 必传 current_user）。
    if current_user is None:
        gene_rows = (await db.execute(
            select(Gene).where(
                Gene.review_status.in_([GeneReviewStatus.pending_owner, GeneReviewStatus.pending_admin]),
                not_deleted(Gene),
            ).order_by(Gene.created_at.desc())
        )).scalars().all()
        submission_rows = (await db.execute(
            select(GeneOverwriteSubmission).where(
                GeneOverwriteSubmission.review_status.in_([GeneReviewStatus.pending_owner, GeneReviewStatus.pending_admin]),
                not_deleted(GeneOverwriteSubmission),
            ).order_by(GeneOverwriteSubmission.created_at.desc())
        )).scalars().all()
        return await _merge_pending_review_items(db, gene_rows, submission_rows)

    # 超管 → 全部
    if getattr(current_user, "is_super_admin", False):
        gene_rows = (await db.execute(
            select(Gene).where(
                Gene.review_status.in_([GeneReviewStatus.pending_owner, GeneReviewStatus.pending_admin]),
                not_deleted(Gene),
            ).order_by(Gene.created_at.desc())
        )).scalars().all()
        submission_rows = (await db.execute(
            select(GeneOverwriteSubmission).where(
                GeneOverwriteSubmission.review_status.in_([GeneReviewStatus.pending_owner, GeneReviewStatus.pending_admin]),
                not_deleted(GeneOverwriteSubmission),
            ).order_by(GeneOverwriteSubmission.created_at.desc())
        )).scalars().all()
        return await _merge_pending_review_items(db, gene_rows, submission_rows)

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

    gene_rows = (await db.execute(
        select(Gene).where(
            Gene.review_status.in_([GeneReviewStatus.pending_owner, GeneReviewStatus.pending_admin]),
            Gene.org_id.in_(admin_org_ids),
            not_deleted(Gene),
        ).order_by(Gene.created_at.desc())
    )).scalars().all()
    submission_rows = (await db.execute(
        select(GeneOverwriteSubmission).where(
            GeneOverwriteSubmission.review_status.in_([GeneReviewStatus.pending_owner, GeneReviewStatus.pending_admin]),
            GeneOverwriteSubmission.org_id.in_(admin_org_ids),
            not_deleted(GeneOverwriteSubmission),
        ).order_by(GeneOverwriteSubmission.created_at.desc())
    )).scalars().all()
    return await _merge_pending_review_items(db, gene_rows, submission_rows)


async def _merge_pending_review_items(
    db: AsyncSession,
    gene_rows: list[Gene],
    submission_rows: list,
) -> list[dict]:
    """把新建 Gene（kind=new）和覆盖提交（kind=overwrite）合并成一份待审列表。

    返回的每条 dict 都额外注入 created_by_name / created_by_email，前端
    审核中心展示用，避免 UI 直接显示 UUID。
    """
    new_items = await _attach_uploader_identity(db, [_gene_to_dict(g) for g in gene_rows])
    for item in new_items:
        item["kind"] = "new"

    # 覆盖提交需要额外带上目标 Gene 的当前名称/版本，供前端展示"旧版本 -> 新版本"。
    target_ids = {s.target_gene_id for s in submission_rows}
    target_genes: dict[str, Gene] = {}
    if target_ids:
        target_rows = (await db.execute(select(Gene).where(Gene.id.in_(target_ids)))).scalars().all()
        target_genes = {g.id: g for g in target_rows}

    overwrite_items = []
    for s in submission_rows:
        target = target_genes.get(s.target_gene_id)
        overwrite_items.append({
            "kind": "overwrite",
            "submission_id": s.id,
            "target_gene_id": s.target_gene_id,
            # 目标行理论上不该被删（覆盖流程只软删并同事务插入新行），但为防御
            # 极端时序问题（目标行在提交后、审核前被其他流程删除），回退到提交
            # 记录自身保存的 name 快照，避免 None 导致前端渲染报错。
            "target_gene_name": target.name if target else s.name,
            "target_gene_version": target.version if target else None,
            "proposed_version": s.version,
            "created_by": s.created_by,
            "created_at": s.created_at,
        })
    overwrite_items = await _attach_uploader_identity(db, overwrite_items)

    return new_items + overwrite_items


async def _attach_uploader_identity(
    db: AsyncSession,
    items: list[dict],
) -> list[dict]:
    """给一批 gene dict 批量注入 created_by_name / created_by_email。

    审核中心需要展示上传者的"人话名字"，但 _gene_to_dict 默认只回
    created_by（UUID）。这里一次性按所有 created_by 批量拿 User，
    避免 N+1 查询。失效用户（已删除/不存在）保持 None，前端回退到 UUID。
    """
    if not items:
        return items

    user_ids = {it.get("created_by") for it in items if it.get("created_by")}
    if not user_ids:
        return items

    from app.models.user import User

    rows = (await db.execute(
        select(User.id, User.name, User.email).where(User.id.in_(user_ids))
    )).all()
    by_id = {row[0]: (row[1], row[2]) for row in rows}

    for it in items:
        uid = it.get("created_by")
        if uid and uid in by_id:
            name, email = by_id[uid]
            it["created_by_name"] = name
            it["created_by_email"] = email
        else:
            it["created_by_name"] = None
            it["created_by_email"] = None
    return items


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
    bypass_review: bool = False,
) -> dict:
    """根据上传/Fork 目标 (personal/org/public) 派生 gene 行的归属字段。

    返回字典直接合并进 Gene(...) 构造或 GeneCreateRequest：
      - personal：归属个人，无需审核，立即可用
      - org：归属组织，pending_owner 等组织 admin 审核
      - public：归属上传者所在组织（用于追溯背书方），pending_owner 等组织 admin 审核

    bypass_review=True 时跳过 org/public 的待审环节，直接落 approved + is_published=True。
    用于操作者本身是目标 org 的 admin 或平台超管的场景 —— 自己审自己没有意义，
    与 review_gene 的权限模型保持一致（admin 反正能 approve）。
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
            "is_published": bypass_review,
            "review_status": GeneReviewStatus.approved if bypass_review else GeneReviewStatus.pending_owner,
        }
    if target == "public":
        if not org_id or not user_id:
            raise BadRequestError("public 目标必须提供 org_id 与 user_id（组织 admin 背书）")
        return {
            "visibility": "public",
            "org_id": org_id,
            "created_by": user_id,
            "is_published": bypass_review,
            "review_status": GeneReviewStatus.approved if bypass_review else GeneReviewStatus.pending_owner,
        }
    raise BadRequestError(f"未知上传目标: {target}")


async def is_user_admin_of_org(
    db: AsyncSession,
    *,
    user_id: str | None,
    org_id: str | None,
    is_super_admin: bool = False,
) -> bool:
    """判断用户对目标 org 是否拥有 admin 权限（含平台超管捷径）。

    用途：上传/fork 入口决定是否 bypass 审核流程。
    - 平台超管：对任意 org（含 None）一律 True
    - 否则：必须传 user_id + org_id，并存在未删除的 OrgMembership.role=admin
    - personal scope（org_id=None 且非超管）：返回 False —— 个人 scope 本身就免审，
      不需要也无法计算"是否 admin"。
    """
    if is_super_admin:
        return True
    if not user_id or not org_id:
        return False

    from app.models.org_membership import OrgMembership, OrgRole

    membership = (await db.execute(
        select(OrgMembership).where(
            OrgMembership.user_id == user_id,
            OrgMembership.org_id == org_id,
            OrgMembership.role == OrgRole.admin,
            OrgMembership.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    return membership is not None


async def _create_gene_overwrite_submission(
    db: AsyncSession,
    *,
    target_gene: Gene,
    fork_gene: Gene,
    attrs: dict,
) -> dict:
    """org/public 目标的 fork 覆盖：不落 genes 表，写入待审核的 GeneOverwriteSubmission。

    真正的软删旧行 + 插入新行，等 review_gene_overwrite_submission()（下一个
    任务）批准那一刻才执行——这样审核拒绝时 target_gene 完全不受影响。
    注意：fork_gene 此时只是内存中的临时 Gene(...) 对象，从未 db.add() /
    commit 过，这里只读取它身上的字段快照，绝不能把它自己落库。
    """
    # 把 fork_gene 上算好的完整内容字段原样搬进待审核暂存表
    submission = GeneOverwriteSubmission(
        target_gene_id=target_gene.id,
        source_gene_id=fork_gene.parent_gene_id,
        lineage_group_id=fork_gene.lineage_group_id,
        name=fork_gene.name,
        slug=fork_gene.slug,
        description=fork_gene.description,
        short_description=fork_gene.short_description,
        category=fork_gene.category,
        tags=fork_gene.tags,
        source=fork_gene.source,
        source_ref=fork_gene.source_ref,
        icon=fork_gene.icon,
        version=fork_gene.version,
        manifest=fork_gene.manifest,
        dependencies=fork_gene.dependencies,
        synergies=fork_gene.synergies,
        visibility=attrs["visibility"],
        org_id=attrs["org_id"],
        created_by=attrs["created_by"],
        review_status=GeneReviewStatus.pending_owner,
    )
    db.add(submission)
    await db.commit()
    await db.refresh(submission)
    return {
        "kind": "overwrite_submission",
        "submission_id": submission.id,
        "target_gene_id": target_gene.id,
        "proposed_version": submission.version,
    }


async def fork_gene_to_library(
    db: AsyncSession,
    source_identifier: str,
    target: str,
    *,
    current_user,  # app.models.user.User —— 取 id / is_super_admin / current_org_id
    org_id: str | None = None,
    overwrite: bool = False,
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

    overwrite（目标 scope 内已存在同名技能时如何处理）：
      - False（默认）：只要目标 scope 存在同名技能就直接 ConflictError，不做任何判断。
      - True：仅当同名技能与源头同血缘（lineage_group_id 一致）才允许覆盖，
        血缘不相关一律拒绝（不因 overwrite=True 而放行，防止误覆盖无关技能）；
        source 为 None（外部聚合器来源，无法判断血缘）同样一律拒绝。
        同血缘时按版本号三态处理：源版本更新 → 软删旧行、插入新行并立即执行；
        版本相同 → ConflictError(message_key="errors.gene.fork_already_up_to_date")；
        源版本更旧 → ConflictError(message_key="errors.gene.fork_version_regression")；
        版本号格式不合法 → ConflictError（无专属 message_key，与上面两个区分）。
    """
    if target not in ("personal", "org", "public"):
        raise BadRequestError("fork 目标必须是 personal / org / public 之一")

    # 目标归属：org_id 显式传入优先，否则取 current_user.current_org_id
    effective_org_id = org_id if org_id is not None else getattr(current_user, "current_org_id", None)

    # 操作者若是目标 org 的 admin 或平台超管 → bypass 待审环节
    bypass_review = await is_user_admin_of_org(
        db,
        user_id=current_user.id,
        org_id=effective_org_id,
        is_super_admin=getattr(current_user, "is_super_admin", False),
    )
    attrs = resolve_target_attrs(
        target,
        user_id=current_user.id,
        org_id=effective_org_id,
        bypass_review=bypass_review,
    )

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

    # ── 2.5. 名称查重：目标 scope 内已存在同名技能 ──────────────────────
    existing_name = await get_gene_by_name_in_scope(
        db, source_name,
        visibility=attrs["visibility"],
        org_id=attrs["org_id"],
        created_by=attrs["created_by"],
    )
    pending_overwrite_target: Gene | None = None
    if existing_name is not None:
        # 名字撞车但血缘不相关：不管 overwrite 是否为 True，一律拒绝，
        # 避免把一个毫不相关的技能误覆盖掉。source 为 None（外部聚合器来源）
        # 时也无法判断血缘，同样一律拒绝，不允许覆盖。
        if not overwrite or source is None or existing_name.lineage_group_id != source.lineage_group_id:
            raise ConflictError(f"技能名称 '{source_name}' 已存在")
        # 同血缘，且调用方确认要覆盖：按版本号三态处理
        cmp_result = compare_versions(source.version, existing_name.version)
        if cmp_result is None:
            raise ConflictError(f"版本号格式不合法：源 '{source.version}' 或目标 '{existing_name.version}'")
        if cmp_result == 0:
            raise ConflictError(
                "已是最新版本，无需同步",
                message_key="errors.gene.fork_already_up_to_date",
            )
        if cmp_result < 0:
            raise ConflictError(
                f"目标版本 '{existing_name.version}' 比源头版本 '{source.version}' 更新，无法覆盖为旧版本",
                message_key="errors.gene.fork_version_regression",
            )
        pending_overwrite_target = existing_name

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

    # lineage_group_id 是 NOT NULL 列，必须和新行同时写入，因此这里显式生成
    # 新行的 id（而不是依赖 Column default 在 flush 时才生成），与 create_gene()/
    # publish_variant() 保持一致的写法（Task 7/8 已验证：id/lineage_group_id 必须
    # 传进 Gene(...) 构造函数，而不是构造完再赋值属性）。fork 出来的副本继承源头
    # 的血缘分组，源头缺失（外部聚合器来源）时才退化为自己的新 id。
    new_fork_id = str(uuid.uuid4())
    fork = Gene(
        id=new_fork_id,
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
        lineage_group_id=source.lineage_group_id if source is not None else new_fork_id,
    )

    # org/public 目标的覆盖：不允许立即改 genes 表，改成写入待审核暂存
    # （见 _create_gene_overwrite_submission）。等审核通过才真正软删旧行 +
    # 插入新行；本函数到此为止，fork 这个内存对象永远不会被 db.add()。
    if pending_overwrite_target is not None and target != "personal":
        return await _create_gene_overwrite_submission(
            db, target_gene=pending_overwrite_target, fork_gene=fork, attrs=attrs,
        )

    # 覆盖模式：先记下旧行 id，再软删；插入新行成功后把 InstanceGene/OrgRequiredGene
    # 等"当前生效状态"引用重接到新行，避免旧行软删后这些记录被过滤丢失。
    # （personal 目标沿用 Task 9 的立即执行行为，未受本次改动影响。）
    old_gene_id: str | None = None
    if pending_overwrite_target is not None:
        old_gene_id = pending_overwrite_target.id
        pending_overwrite_target.soft_delete()

    db.add(fork)
    try:
        await db.commit()
    except IntegrityError as e:
        # 极小概率竞态：上面的 name/slug 预检查通过后，另一请求在 commit 之前
        # 抢先插入了同名/同 slug 的记录。DB 唯一索引在此兜底，统一转换成
        # ConflictError，模式与 create_gene() 保持一致。
        await db.rollback()
        raise ConflictError(f"基因 slug '{new_slug}' 或名称 '{source_name}' 已存在") from e
    await db.refresh(fork)

    if old_gene_id is not None:
        # 注意：上面软删旧行 + 插入新行的 commit，与这里 _rewire_gene_references()
        # 内部自己的 commit 不是同一个事务——如果进程在两次 commit 之间崩溃，
        # 旧行已软删但 InstanceGene/OrgRequiredGene 还指向旧 id，会造成短暂的
        # 引用悬空。这与 create_gene() 的覆盖分支是完全相同的既有模式（同样两次
        # 分开 commit），非本次改动引入的新问题，暂不在本任务范围内修复，
        # 后续会作为独立 follow-up 让两处调用点一起做成原子操作。
        await _rewire_gene_references(db, old_gene_id, fork.id)

    return _gene_to_dict(fork)


async def _restart_instance_bg(instance_id: str) -> None:
    """后台重启实例（独立 db session，避免使用请求上下文的 session）。"""
    from app.core.deps import async_session_factory
    from app.services.instance_service import restart_instance

    try:
        async with async_session_factory() as db:
            await restart_instance(instance_id, db)
    except Exception as e:
        logger.error("_restart_instance_bg: restart failed for instance=%s: %s", instance_id, e)


# 模块级引用，供 delete_skill_by_name 调用并允许单元测试 patch
# instance_service 不导入 gene_service，无循环导入风险
from app.services.instance_service import get_instance  # noqa: E402


async def delete_skill_by_name(
    db: AsyncSession,
    instance_id: str,
    skill_name: str,
    org_id: str | None = None,
) -> dict:
    """按技能名称直接从 Pod 删除技能目录，同时清理 DB 记录（若存在）。

    用于 emerged 技能和无活跃 InstanceGene 的 hub 技能。

    参数：
        db          — 当前请求 db session
        instance_id — 目标 AI 员工实例 ID
        skill_name  — 技能目录名（即 gene.slug）
        org_id      — 可选的组织 ID，用于实例鉴权
    返回：
        {"deleted": True, "skill_name": skill_name}
    """
    from app.api.workspaces import broadcast_event

    # 1. 鉴权并获取实例对象（内部抛 NotFoundError / ForbiddenError）
    instance = await get_instance(instance_id, db, org_id)

    # 2. 查找匹配 skill_name 的 InstanceGene（通过 gene.slug == skill_name）
    ig_result = await db.execute(
        select(InstanceGene, Gene)
        .join(Gene, InstanceGene.gene_id == Gene.id)
        .where(
            InstanceGene.instance_id == instance_id,
            Gene.slug == skill_name,
            not_deleted(InstanceGene),
            Gene.deleted_at.is_(None),
        )
    )
    row = ig_result.first()
    ig: InstanceGene | None = row[0] if row else None
    gene: Gene | None = row[1] if row else None

    # 3. 删除 Pod 文件系统中的技能目录（FS 失败时不执行 DB 更新）
    adapter = _get_gene_install_adapter(instance.runtime)
    try:
        async with remote_fs(instance, db) as fs:
            await adapter.remove_skill(fs, skill_name)
            await adapter.post_remove_cleanup(fs, skill_name)
    except Exception as e:
        logger.error(
            "delete_skill_by_name: fs error skill=%s instance=%s: %s",
            skill_name, instance_id, e,
        )
        raise BadRequestError("Pod 文件系统不可达，遗忘操作失败")

    # 4. 清理 DB 记录（若存在活跃 InstanceGene）
    if ig is not None and gene is not None:
        ig.soft_delete()
        gene.install_count = max(0, gene.install_count - 1)

    # 5. 记录 evolution 事件（无论 IG 是否存在）
    gene_name = gene.name if gene else skill_name
    await _record_evolution(
        db, instance_id, EvolutionEventType.forgotten,
        gene_name,
        gene_slug=skill_name,
        gene_id=gene.id if gene else None,
        details={"method": "direct_by_name"},
    )
    await db.commit()

    # 6. 广播 WebSocket 事件通知前端
    ws_ids = await _get_instance_workspace_ids(db, instance_id)
    for ws_id in ws_ids:
        broadcast_event(ws_id, "gene:forgotten", {
            "instance_id": instance_id,
            "skill_name": skill_name,
            "gene_name": gene_name,
        })

    # 7. 后台重启实例使配置生效
    _fire_task(_restart_instance_bg(instance_id))
    logger.info("delete_skill_by_name: skill=%s instance=%s", skill_name, instance_id)
    return {"deleted": True, "skill_name": skill_name}
