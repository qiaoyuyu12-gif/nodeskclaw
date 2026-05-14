# app/api/skills.py
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_org_admin
from app.core.security import get_current_user
from app.schemas.common import ApiResponse
from app.schemas.skill import (
    BindRequest,
    QueryRequest,
    QueryResponse,
    SkillCreate,
    SkillResponse,
    SkillUpdate,
)
from app.services import skill_service

router = APIRouter()


@router.get("/my", response_model=ApiResponse[list[SkillResponse]])
async def my_skills(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    if not user.current_org_id:
        return ApiResponse(data=[])
    skills = await skill_service.list_my_skills(org_id=user.current_org_id, db=db)
    return ApiResponse(data=[SkillResponse.model_validate(s) for s in skills])


@router.post("/{skill_id}/query", response_model=ApiResponse[QueryResponse])
async def query_skill(
    skill_id: str,
    body: QueryRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    if not user.current_org_id:
        return ApiResponse(data=QueryResponse(degraded=True, message="用户未加入组织"))
    result = await skill_service.query_skill(
        skill_id=skill_id, org_id=user.current_org_id, question=body.question, db=db
    )
    return ApiResponse(data=QueryResponse(**result))


@router.post("", response_model=ApiResponse[SkillResponse])
async def create_skill(
    body: SkillCreate,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_org_admin),
):
    user, org = auth
    skill = await skill_service.create_skill(
        org_id=org.id,
        name=body.name,
        skill_type=body.type,
        kb_id=body.kb_id,
        config=body.config,
        db=db,
    )
    return ApiResponse(data=SkillResponse.model_validate(skill))


@router.get("", response_model=ApiResponse[list[SkillResponse]])
async def list_skills(
    skill_type: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_org_admin),
):
    user, org = auth
    skills = await skill_service.list_skills(org_id=org.id, skill_type=skill_type, db=db)
    return ApiResponse(data=[SkillResponse.model_validate(s) for s in skills])


@router.patch("/{skill_id}", response_model=ApiResponse[SkillResponse])
async def update_skill(
    skill_id: str,
    body: SkillUpdate,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_org_admin),
):
    user, org = auth
    skill = await skill_service.update_skill(
        skill_id=skill_id, org_id=org.id, updates=body.model_dump(exclude_none=True), db=db
    )
    return ApiResponse(data=SkillResponse.model_validate(skill))


@router.delete("/{skill_id}", response_model=ApiResponse[None])
async def delete_skill(
    skill_id: str,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_org_admin),
):
    user, org = auth
    await skill_service.delete_skill(skill_id=skill_id, org_id=org.id, db=db)
    return ApiResponse(data=None)


@router.post("/{skill_id}/bind", response_model=ApiResponse[None])
async def bind_skill(
    skill_id: str,
    body: BindRequest,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_org_admin),
):
    user, org = auth
    await skill_service.bind_skill(
        skill_id=skill_id, instance_id=body.instance_id, created_by=user.id, db=db
    )
    return ApiResponse(data=None)


@router.delete("/{skill_id}/bind/{instance_id}", response_model=ApiResponse[None])
async def unbind_skill(
    skill_id: str,
    instance_id: str,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_org_admin),
):
    user, org = auth
    await skill_service.unbind_skill(skill_id=skill_id, instance_id=instance_id, db=db)
    return ApiResponse(data=None)
