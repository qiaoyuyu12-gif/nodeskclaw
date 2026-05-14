# app/services/skill_service.py
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError
from app.models.agent_skill_binding import AgentSkillBinding
from app.models.skill_definition import SkillDefinition
from app.services import kb_service, ragflow_adapter

logger = logging.getLogger(__name__)


async def create_skill(
    org_id: str,
    name: str,
    skill_type: str,
    kb_id: str | None,
    config: dict,
    db: AsyncSession,
) -> SkillDefinition:
    if skill_type == "rag_query" and not kb_id:
        raise BadRequestError("kb_id is required for rag_query skills")
    skill = SkillDefinition(
        org_id=org_id,
        name=name,
        type=skill_type,
        kb_id=kb_id,
        config=config,
    )
    db.add(skill)
    await db.commit()
    await db.refresh(skill)
    return skill


async def list_skills(
    org_id: str,
    skill_type: str | None,
    db: AsyncSession,
) -> list[SkillDefinition]:
    q = select(SkillDefinition).where(
        SkillDefinition.org_id == org_id,
        SkillDefinition.deleted_at.is_(None),
    )
    if skill_type:
        q = q.where(SkillDefinition.type == skill_type)
    result = await db.execute(q.order_by(SkillDefinition.created_at.desc()))
    return list(result.scalars().all())


async def get_skill(skill_id: str, org_id: str, db: AsyncSession) -> SkillDefinition:
    result = await db.execute(
        select(SkillDefinition).where(
            SkillDefinition.id == skill_id,
            SkillDefinition.org_id == org_id,
            SkillDefinition.deleted_at.is_(None),
        )
    )
    skill = result.scalar_one_or_none()
    if skill is None:
        raise NotFoundError("skill", skill_id)
    return skill


async def update_skill(
    skill_id: str,
    org_id: str,
    updates: dict,
    db: AsyncSession,
) -> SkillDefinition:
    skill = await get_skill(skill_id, org_id, db)
    for key, value in updates.items():
        setattr(skill, key, value)
    await db.commit()
    await db.refresh(skill)
    return skill


async def delete_skill(skill_id: str, org_id: str, db: AsyncSession) -> None:
    skill = await get_skill(skill_id, org_id, db)
    skill.soft_delete()
    await db.commit()


async def bind_skill(
    skill_id: str,
    instance_id: str,
    created_by: str,
    db: AsyncSession,
) -> AgentSkillBinding:
    binding = AgentSkillBinding(
        skill_id=skill_id,
        instance_id=instance_id,
        created_by=created_by,
    )
    db.add(binding)
    await db.commit()
    await db.refresh(binding)
    return binding


async def unbind_skill(skill_id: str, instance_id: str, db: AsyncSession) -> None:
    result = await db.execute(
        select(AgentSkillBinding).where(
            AgentSkillBinding.skill_id == skill_id,
            AgentSkillBinding.instance_id == instance_id,
            AgentSkillBinding.deleted_at.is_(None),
        )
    )
    binding = result.scalar_one_or_none()
    if binding is None:
        raise NotFoundError("binding", f"{skill_id}/{instance_id}")
    binding.soft_delete()
    await db.commit()


async def list_my_skills(org_id: str, db: AsyncSession) -> list[SkillDefinition]:
    result = await db.execute(
        select(SkillDefinition)
        .where(
            SkillDefinition.org_id == org_id,
            SkillDefinition.enabled.is_(True),
            SkillDefinition.deleted_at.is_(None),
        )
        .order_by(SkillDefinition.name)
    )
    return list(result.scalars().all())


async def query_skill(
    skill_id: str,
    org_id: str,
    question: str,
    db: AsyncSession,
) -> dict:
    try:
        skill = await get_skill(skill_id, org_id, db)
        if skill.type != "rag_query" or not skill.kb_id:
            raise BadRequestError("skill is not a rag_query type with a knowledge base")
        kb = await kb_service.get_knowledge_base(skill.kb_id, org_id, db)
        api_key = await kb_service.get_decrypted_api_key(kb)
        top_k = skill.config.get("top_k", 5) if skill.config else 5
        chunks = await ragflow_adapter.retrieve(
            kb.ragflow_endpoint, api_key, kb.ragflow_kb_id, question, top_k
        )
        return {"degraded": False, "message": None, "results": chunks}
    except BadRequestError:
        raise
    except Exception:
        logger.exception("RAGFlow query failed for skill %s", skill_id)
        return {"degraded": True, "message": "知识库暂时不可用，请稍后重试", "results": []}
