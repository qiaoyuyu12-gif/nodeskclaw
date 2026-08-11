# app/api/knowledge_bases.py
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import hooks
from app.core.deps import get_db, require_feature, require_org_admin, require_org_member_role
from app.schemas.common import ApiResponse
from app.schemas.skill import KnowledgeBaseCreate, KnowledgeBaseResponse, KnowledgeBaseUpdate
from app.services import kb_service, ragflow_adapter

router = APIRouter(dependencies=[Depends(require_feature("knowledge_base"))])


@router.post("", response_model=ApiResponse[KnowledgeBaseResponse])
async def create_kb(
    body: KnowledgeBaseCreate,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_org_member_role("operator")),
):
    user, org = auth
    kb = await kb_service.create_knowledge_base(
        org_id=org.id,
        name=body.name,
        ragflow_endpoint=body.ragflow_endpoint,
        ragflow_kb_id=body.ragflow_kb_id,
        api_key=body.api_key,
        source_type=body.source_type,
        db=db,
    )
    await hooks.emit("operation_audit", action="knowledge_base.created", target_type="knowledge_base", target_id=kb.id, actor_id=user.id, org_id=org.id, details={"name": body.name})
    return ApiResponse(data=KnowledgeBaseResponse.model_validate(kb))


@router.get("", response_model=ApiResponse[list[KnowledgeBaseResponse]])
async def list_kbs(
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_org_member_role("member")),
):
    user, org = auth
    kbs = await kb_service.list_knowledge_bases(org_id=org.id, db=db)
    return ApiResponse(data=[KnowledgeBaseResponse.model_validate(kb) for kb in kbs])


@router.patch("/{kb_id}", response_model=ApiResponse[KnowledgeBaseResponse])
async def update_kb(
    kb_id: str,
    body: KnowledgeBaseUpdate,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_org_member_role("operator")),
):
    user, org = auth
    updates = body.model_dump(exclude_none=True)
    kb = await kb_service.update_knowledge_base(
        kb_id=kb_id, org_id=org.id, updates=updates, db=db
    )
    await hooks.emit("operation_audit", action="knowledge_base.updated", target_type="knowledge_base", target_id=kb_id, actor_id=user.id, org_id=org.id)
    return ApiResponse(data=KnowledgeBaseResponse.model_validate(kb))


@router.delete("/{kb_id}", response_model=ApiResponse[None])
async def delete_kb(
    kb_id: str,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_org_admin),
):
    user, org = auth
    await kb_service.delete_knowledge_base(kb_id=kb_id, org_id=org.id, db=db)
    await hooks.emit("operation_audit", action="knowledge_base.deleted", target_type="knowledge_base", target_id=kb_id, actor_id=user.id, org_id=org.id)
    return ApiResponse(data=None)


@router.post("/{kb_id}/sync", response_model=ApiResponse[dict])
async def sync_kb(
    kb_id: str,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_org_member_role("operator")),
):
    user, org = auth
    kb = await kb_service.get_knowledge_base(kb_id=kb_id, org_id=org.id, db=db)
    api_key = kb_service.get_decrypted_api_key(kb)
    reachable = await ragflow_adapter.verify_connection(
        kb.ragflow_endpoint, api_key, kb.ragflow_kb_id
    )
    # 持久化 sync 结果，供 agent KB 选择器过滤「已连接」状态
    kb.is_reachable = reachable
    kb.last_checked_at = datetime.now(timezone.utc)
    await db.commit()
    await hooks.emit("operation_audit", action="knowledge_base.synced", target_type="knowledge_base", target_id=kb_id, actor_id=user.id, org_id=org.id, details={"reachable": reachable})
    return ApiResponse(data={"reachable": reachable, "kb_id": kb_id})


@router.get("/{kb_id}/documents", response_model=ApiResponse[dict])
async def list_kb_documents(
    kb_id: str,
    page: int = 1,
    page_size: int = 30,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_org_member_role("member")),
):
    """预览知识库文档列表，代理 RAGFlow API 避免前端直接持有 API Key。"""
    user, org = auth
    kb = await kb_service.get_knowledge_base(kb_id=kb_id, org_id=org.id, db=db)
    api_key = kb_service.get_decrypted_api_key(kb)
    data = await ragflow_adapter.list_documents(
        kb.ragflow_endpoint, api_key, kb.ragflow_kb_id, page, page_size
    )
    return ApiResponse(data=data)
