# app/api/skills.py
from fastapi import APIRouter, Depends, Query, UploadFile, File
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
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


@router.post("/upload", response_model=ApiResponse[SkillResponse])
async def upload_skill_package(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_org_admin),
):
    """通过 ZIP 压缩包上传技能（原有方式）。"""
    user, org = auth
    data = await file.read()
    skill = await skill_service.create_skill_from_package(
        org_id=org.id,
        zip_data=data,
        storage_root=settings.LOCAL_STORAGE_DIR or "/app/data",
        db=db,
    )
    return ApiResponse(data=SkillResponse.model_validate(skill))


@router.post("/upload-folder", response_model=ApiResponse[SkillResponse])
async def upload_skill_folder(
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_org_admin),
):
    """通过文件夹（多文件 multipart）上传技能。

    将所有文件（skill.md + Python 脚本 + assets + references）
    内联序列化为 manifest JSON 存入数据库，agent 可直接读取命中。
    前端使用 <input webkitdirectory> 选择文件夹后，把文件夹内所有
    文件作为多字段 multipart 发送到此端点。
    """
    user, org = auth

    # 第一遍：收集所有原始路径，用于检测顶层文件夹前缀
    raw_entries: list[tuple[str, UploadFile]] = []
    for upload_file in files:
        raw = (upload_file.filename or "").replace("\\", "/").strip("/")
        if raw:
            raw_entries.append((raw, upload_file))

    if not raw_entries:
        from app.core.exceptions import BadRequestError
        raise BadRequestError("未收到任何文件")

    # 检测是否需要剥离顶层文件夹前缀
    # webkitdirectory 上传时，所有路径都以文件夹名开头（如 my-skill/main.py）
    # 若全部路径都包含 "/"，且第一段相同，则剥离该前缀
    all_first = {p.split("/", 1)[0] for p, _ in raw_entries if "/" in p}
    has_uniform_prefix = (
        len(all_first) == 1 and all("/" in p for p, _ in raw_entries)
    )
    strip_prefix = (all_first.pop() + "/") if has_uniform_prefix else ""

    # 第二遍：读取文件内容，按规范化路径构建字典
    files_dict: dict[str, bytes] = {}
    for raw, upload_file in raw_entries:
        # 剥离顶层文件夹前缀（仅 webkitdirectory 统一前缀时）
        rel_path = raw[len(strip_prefix):] if strip_prefix and raw.startswith(strip_prefix) else raw
        files_dict[rel_path] = await upload_file.read()

    skill = await skill_service.create_skill_from_files(
        org_id=org.id,
        files=files_dict,
        db=db,
    )
    return ApiResponse(data=SkillResponse.model_validate(skill))


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
