"""迁移 skill_definitions 数据到 genes 表。

将 skill_definitions 表中的已有数据迁移到 genes 表（source=manual），
并将 agent_skill_bindings 迁移到 instance_genes 表。

运行方式：uv run alembic runmigrations -d nodeskclaw-backend
或直接：cd nodeskclaw-backend && uv run python -m app.services.migrate_skills_to_genes
"""

import asyncio
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.models.skill_definition import SkillDefinition
from app.models.agent_skill_binding import AgentSkillBinding
from app.models.gene import Gene, InstanceGene, GeneSource, ContentVisibility
from app.services.gene_service import _json_dumps

logger = logging.getLogger(__name__)


async def migrate_skill_to_gene(db: AsyncSession, skill: SkillDefinition) -> Gene | None:

    slug = skill.name.lower().replace(" ", "-")[:64]

    gene = Gene(
        name=skill.name,
        slug=slug,
        description=skill.description,
        short_description=(skill.description or "")[:256] if skill.description else None,
        category=skill.type,
        source=GeneSource.manual,
        manifest=_json_dumps(skill.manifest),
        is_published=True,
        visibility=ContentVisibility.org_private,
        created_by=None,
        org_id=skill.org_id,
    )
    db.add(gene)
    return gene


async def migrate_binding_to_instance_gene(
    db: AsyncSession, binding: AgentSkillBinding, gene_id: str
) -> InstanceGene | None:
    """将单个 AgentSkillBinding 迁移为 InstanceGene 记录。"""
    ig = InstanceGene(
        instance_id=binding.instance_id,
        gene_id=gene_id,
        status="installed",
    )
    db.add(ig)
    return ig


async def run_migration():
    """执行迁移。"""
    async with get_db_session() as db:
        # 迁移所有未删除的 SkillDefinition
        result = await db.execute(
            select(SkillDefinition).where(SkillDefinition.deleted_at.is_(None))
        )
        skills = result.scalars().all()

        logger.info("开始迁移 %d 个 SkillDefinition 到 genes 表", len(skills))
        slug_to_gene_id = {}

        for skill in skills:
            slug = skill.name.lower().replace(" ", "-")[:64]
            gene = await migrate_skill_to_gene(db, skill)
            await db.flush()
            slug_to_gene_id[skill.id] = gene.id
            logger.info("迁移 SkillDefinition '%s' -> Gene '%s' (id=%s)", skill.name, gene.name, gene.id)

        await db.commit()
        logger.info("genes 表迁移完成，共 %d 条", len(slug_to_gene_id))

        # 迁移 AgentSkillBinding 到 InstanceGene
        result = await db.execute(
            select(AgentSkillBinding).where(AgentSkillBinding.deleted_at.is_(None))
        )
        bindings = result.scalars().all()

        logger.info("开始迁移 %d 个 AgentSkillBinding 到 instance_genes 表", len(bindings))
        for binding in bindings:
            gene_id = slug_to_gene_id.get(binding.skill_id)
            if gene_id:
                ig = await migrate_binding_to_instance_gene(db, binding, gene_id)
                logger.info(
                    "迁移 AgentSkillBinding skill=%s instance=%s -> InstanceGene gene=%s",
                    binding.skill_id, binding.instance_id, gene_id)
            else:
                logger.warning(
                    "AgentSkillBinding skill_id=%s 无对应 Gene，跳过",
                    binding.skill_id)

        await db.commit()
        logger.info("instance_genes 表迁移完成，共 %d 条", len(bindings))
        logger.info("迁移全部完成")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    asyncio.run(run_migration())
