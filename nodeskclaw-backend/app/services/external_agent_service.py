"""ExternalAgent 的业务逻辑层：CRUD + API Key 加解密。"""

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.security import decrypt_sensitive, encrypt_sensitive
from app.models.external_agent import ExternalAgent

logger = logging.getLogger(__name__)


async def create_external_agent(
    org_id: str,
    name: str,
    endpoint: str,
    protocol: str,
    api_key: str | None,
    description: str | None,
    capabilities: list[str],
    icon_emoji: str | None,
    theme_color: str | None,
    db: AsyncSession,
) -> ExternalAgent:
    agent = ExternalAgent(
        org_id=org_id,
        name=name,
        endpoint=endpoint.rstrip("/"),
        protocol=protocol,
        api_key_encrypted=encrypt_sensitive(api_key) if api_key else None,
        description=description,
        capabilities=json.dumps(capabilities, ensure_ascii=False),
        icon_emoji=icon_emoji,
        theme_color=theme_color,
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return agent


async def list_external_agents(org_id: str, db: AsyncSession) -> list[ExternalAgent]:
    result = await db.execute(
        select(ExternalAgent)
        .where(ExternalAgent.org_id == org_id, ExternalAgent.deleted_at.is_(None))
        .order_by(ExternalAgent.created_at.desc())
    )
    return list(result.scalars().all())


async def get_external_agent(agent_id: str, org_id: str, db: AsyncSession) -> ExternalAgent:
    result = await db.execute(
        select(ExternalAgent).where(
            ExternalAgent.id == agent_id,
            ExternalAgent.org_id == org_id,
            ExternalAgent.deleted_at.is_(None),
        )
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise NotFoundError("external_agent", agent_id)
    return agent


def get_decrypted_api_key(agent: ExternalAgent) -> str | None:
    """解密 API Key；未配置时返回 None。"""
    if not agent.api_key_encrypted:
        return None
    return decrypt_sensitive(agent.api_key_encrypted)


def get_capabilities(agent: ExternalAgent) -> list[str]:
    """从 JSON 字段解析能力标签列表。"""
    if not agent.capabilities:
        return []
    try:
        return json.loads(agent.capabilities)
    except Exception:
        return []


async def update_external_agent(
    agent_id: str,
    org_id: str,
    updates: dict,
    db: AsyncSession,
) -> ExternalAgent:
    agent = await get_external_agent(agent_id, org_id, db)

    # API Key 单独处理：需重新加密
    if "api_key" in updates:
        new_key = updates.pop("api_key")
        if new_key:
            agent.api_key_encrypted = encrypt_sensitive(new_key)

    # capabilities 列表转 JSON 字符串
    if "capabilities" in updates:
        updates["capabilities"] = json.dumps(updates["capabilities"], ensure_ascii=False)

    # endpoint 去除尾部斜杠
    if "endpoint" in updates and updates["endpoint"]:
        updates["endpoint"] = updates["endpoint"].rstrip("/")

    for key, value in updates.items():
        setattr(agent, key, value)

    await db.commit()
    await db.refresh(agent)
    return agent


async def delete_external_agent(agent_id: str, org_id: str, db: AsyncSession) -> None:
    agent = await get_external_agent(agent_id, org_id, db)
    agent.soft_delete()
    await db.commit()
