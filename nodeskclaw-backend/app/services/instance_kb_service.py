"""实例与知识库关联服务：管理 AI 员工的外挂知识库配置。"""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.models.instance_knowledge_base import InstanceKnowledgeBase
from app.models.knowledge_base import KnowledgeBase


async def list_instance_kbs(instance_id: str, db: AsyncSession) -> list[InstanceKnowledgeBase]:
    """返回指定实例已绑定的知识库列表（含嵌套 KnowledgeBase 对象）。"""
    result = await db.execute(
        select(InstanceKnowledgeBase)
        .options(selectinload(InstanceKnowledgeBase.kb))
        .where(
            InstanceKnowledgeBase.instance_id == instance_id,
            InstanceKnowledgeBase.deleted_at.is_(None),
        )
        .order_by(InstanceKnowledgeBase.created_at.desc())
    )
    return list(result.scalars().all())


async def attach_kb(
    instance_id: str,
    kb_id: str,
    org_id: str,
    user_id: str,
    db: AsyncSession,
) -> InstanceKnowledgeBase:
    """绑定知识库到实例，要求 KB 已 sync 验证通过且属于同一组织。"""
    # 验证知识库存在、属于同 org
    kb_result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.org_id == org_id,
            KnowledgeBase.deleted_at.is_(None),
        )
    )
    kb = kb_result.scalar_one_or_none()
    if kb is None:
        raise NotFoundError(message="知识库不存在或不属于当前组织", message_key="errors.kb.not_found")
    if not kb.is_reachable:
        raise BadRequestError(
            message="知识库尚未通过连接验证，请先执行 Sync",
            message_key="errors.kb.not_reachable",
        )

    # 检查是否已绑定
    existing = await db.execute(
        select(InstanceKnowledgeBase).where(
            InstanceKnowledgeBase.instance_id == instance_id,
            InstanceKnowledgeBase.kb_id == kb_id,
            InstanceKnowledgeBase.deleted_at.is_(None),
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise ConflictError(message="该知识库已绑定到此实例", message_key="errors.kb.already_attached")

    binding = InstanceKnowledgeBase(
        instance_id=instance_id,
        kb_id=kb_id,
        enabled=True,
        created_by=user_id,
    )
    db.add(binding)
    await db.commit()
    await db.refresh(binding)
    # 加载关联 KB 对象供序列化使用
    await db.refresh(binding, ["kb"])
    return binding


async def detach_kb(instance_id: str, kb_id: str, db: AsyncSession) -> None:
    """解绑知识库，软删除绑定记录。"""
    result = await db.execute(
        select(InstanceKnowledgeBase).where(
            InstanceKnowledgeBase.instance_id == instance_id,
            InstanceKnowledgeBase.kb_id == kb_id,
            InstanceKnowledgeBase.deleted_at.is_(None),
        )
    )
    binding = result.scalar_one_or_none()
    if binding is None:
        raise NotFoundError(message="该知识库未绑定到此实例", message_key="errors.kb.not_attached")
    binding.soft_delete()
    await db.commit()
