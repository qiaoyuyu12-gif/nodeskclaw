# app/services/test_kb_service.py
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_create_knowledge_base_encrypts_api_key():
    db = AsyncMock()
    db.add = MagicMock()

    with patch("app.services.kb_service.encrypt_sensitive", return_value="encrypted-key"):
        from app.services.kb_service import create_knowledge_base

        kb = await create_knowledge_base(
            org_id="org-1",
            name="My KB",
            ragflow_endpoint="http://ragflow:9380",
            ragflow_kb_id="kb-abc",
            api_key="plain-secret",
            source_type="doc",
            db=db,
        )

    assert kb.name == "My KB"
    assert kb.api_key_encrypted == "encrypted-key"
    assert kb.org_id == "org-1"
    db.add.assert_called_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_knowledge_base_soft_deletes():
    existing_kb = MagicMock()
    existing_kb.soft_delete = MagicMock()
    db = AsyncMock()

    with patch("app.services.kb_service.get_knowledge_base", return_value=existing_kb):
        from app.services.kb_service import delete_knowledge_base

        await delete_knowledge_base("kb-1", "org-1", db)

    existing_kb.soft_delete.assert_called_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_decrypted_api_key_decrypts():
    kb = MagicMock()
    kb.api_key_encrypted = "encrypted-value"

    with patch("app.services.kb_service.decrypt_sensitive", return_value="plain-key"):
        from app.services.kb_service import get_decrypted_api_key

        result = await get_decrypted_api_key(kb)

    assert result == "plain-key"
