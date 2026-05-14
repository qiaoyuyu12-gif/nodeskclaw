# app/services/kb_service.py
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.security import decrypt_sensitive, encrypt_sensitive
from app.models.knowledge_base import KnowledgeBase

logger = logging.getLogger(__name__)


async def create_knowledge_base(
    org_id: str,
    name: str,
    ragflow_endpoint: str,
    ragflow_kb_id: str,
    api_key: str,
    source_type: str,
    db: AsyncSession,
) -> KnowledgeBase:
    kb = KnowledgeBase(
        org_id=org_id,
        name=name,
        ragflow_endpoint=ragflow_endpoint,
        ragflow_kb_id=ragflow_kb_id,
        api_key_encrypted=encrypt_sensitive(api_key),
        source_type=source_type,
    )
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return kb


async def list_knowledge_bases(org_id: str, db: AsyncSession) -> list[KnowledgeBase]:
    result = await db.execute(
        select(KnowledgeBase)
        .where(KnowledgeBase.org_id == org_id, KnowledgeBase.deleted_at.is_(None))
        .order_by(KnowledgeBase.created_at.desc())
    )
    return list(result.scalars().all())


async def get_knowledge_base(kb_id: str, org_id: str, db: AsyncSession) -> KnowledgeBase:
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.org_id == org_id,
            KnowledgeBase.deleted_at.is_(None),
        )
    )
    kb = result.scalar_one_or_none()
    if kb is None:
        raise NotFoundError("knowledge_base", kb_id)
    return kb


def get_decrypted_api_key(kb: KnowledgeBase) -> str:
    return decrypt_sensitive(kb.api_key_encrypted)


async def update_knowledge_base(
    kb_id: str,
    org_id: str,
    updates: dict,
    db: AsyncSession,
) -> KnowledgeBase:
    kb = await get_knowledge_base(kb_id, org_id, db)
    remaining = {k: v for k, v in updates.items() if k != "api_key"}
    if "api_key" in updates:
        kb.api_key_encrypted = encrypt_sensitive(updates["api_key"])
    for key, value in remaining.items():
        setattr(kb, key, value)
    await db.commit()
    await db.refresh(kb)
    return kb


async def delete_knowledge_base(kb_id: str, org_id: str, db: AsyncSession) -> None:
    kb = await get_knowledge_base(kb_id, org_id, db)
    kb.soft_delete()
    await db.commit()
