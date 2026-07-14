"""Gene Evolution Ecosystem API routes."""

import hashlib
import io
import json
import logging
import posixpath
import re
import zipfile

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_org, get_db
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.security import get_current_user
from app.models.base import not_deleted
from app.models.gene import Gene
from app.models.user import User
from app.schemas.common import ApiResponse, PaginatedResponse, Pagination
from app.schemas.gene import (
    ApplyGenomeRequest,
    CreateGeneRequest,
    EffectivenessRequest,
    ForkGeneRequest,
    GeneCreateRequest,
    GenomeCreateRequest,
    InstallGeneRequest,
    LearningCallbackPayload,
    ManualGeneCreate,
    PublishVariantRequest,
    RatingRequest,
    ReviewRequest,
    UninstallGeneRequest,
    UpdateGeneRequest,
    UpdateGenomeRequest,
    UploadTarget,
)
from app.services import gene_service

logger = logging.getLogger(__name__)
router = APIRouter()

# Gene 文件夹上传限制：防止无限制大文件/大量文件耗尽内存与存储
# （genes.manifest 是 Text 列，上传内容最终会整包塞进去）
_MAX_UPLOAD_FILE_SIZE = 10 * 1024 * 1024   # 单文件 10MB
_MAX_UPLOAD_TOTAL_SIZE = 50 * 1024 * 1024  # 总大小 50MB
_UPLOAD_READ_CHUNK_SIZE = 1024 * 1024      # 分块读取粒度：边读边判断大小上限，避免超大文件被整体读入内存后才拒绝
_MAX_UPLOAD_FILE_COUNT = 500                # 单次最多 500 个文件

# 与 schemas/gene.py 里 GeneCreateRequest.slug 的正则保持一致
_SLUG_DISALLOWED_CHARS_RE = re.compile(r"[^a-zA-Z0-9_-]")


def _slugify_gene_name(name: str) -> str:
    """把技能名转成合法 slug（只允许 [a-zA-Z0-9_-]，见 schemas/gene.py 的校验正则）。

    技能名很多是中文（如"业务操作指引编写"），过滤非法字符后可能整段被删空，
    这种情况下用名称的确定性哈希摘要兜底——同一个名字每次都生成同一个 slug，
    保证重复上传同名技能时 create_gene 的 (slug, org_id) 冲突/覆盖判定仍然生效。
    """
    lowered = name.strip().lower().replace(" ", "-")
    safe = _SLUG_DISALLOWED_CHARS_RE.sub("", lowered).strip("-_")
    if safe:
        return safe[:64]
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:12]
    return f"gene-{digest}"


def _validate_gene_callback_auth(
    payload: LearningCallbackPayload,
    mode: str,
    sig: str | None,
    instance_id: str | None,
) -> None:
    if sig or instance_id:
        if not sig or not instance_id:
            raise BadRequestError("回调签名参数不完整")
        if payload.instance_id != instance_id:
            raise BadRequestError("回调实例与签名参数不匹配")
        if not gene_service.verify_gene_callback_signature(payload, mode, sig):
            raise BadRequestError("回调签名无效")
        return

    if not settings.ALLOW_LEGACY_GENE_CALLBACKS:
        raise BadRequestError("缺少回调签名参数")

    logger.warning(
        "Allowing legacy unsigned gene callback mode=%s task_id=%s instance_id=%s",
        mode,
        payload.task_id,
        payload.instance_id,
    )


# ═══════════════════════════════════════════════════
#  Gene Market
# ═══════════════════════════════════════════════════


@router.get("/genes")
async def list_genes(
    keyword: str | None = None,
    tag: str | None = None,
    category: str | None = None,
    source: str | None = None,
    visibility: str | None = None,
    sort: str = "popularity",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    genes, total = await gene_service.list_genes(
        db, keyword=keyword, tag=tag, category=category, source=source,
        visibility=visibility, org_id=current_user.current_org_id,
        user_id=current_user.id,
        sort=sort, page=page, page_size=page_size,
    )
    return PaginatedResponse(
        data=genes,
        pagination=Pagination(page=page, page_size=page_size, total=total),
    )


@router.get("/genes/tags")
async def gene_tags(
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    tags = await gene_service.get_gene_tags(db)
    return ApiResponse(data=[t.model_dump() for t in tags])


@router.get("/genes/featured")
async def featured_genes(
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    genes = await gene_service.get_featured_genes(db, limit=limit)
    return ApiResponse(data=genes)


@router.post("/genes/upload-folder", response_model=ApiResponse[dict])
async def upload_gene_folder(
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    overwrite: bool = Query(False, description="是否覆盖已存在的同名基因"),
    target: UploadTarget = Query(
        "personal",
        description="上传目标：personal(个人 library) / org(组织 library, 需 admin 审核) / public(公共市场, 需 admin 审核)",
    ),
):
    """通过文件夹（多文件 multipart）上传本地 Gene。

    根据 target 派生归属字段：
      - personal：visibility=personal，归属当前用户，立即可用
      - org：visibility=org_private，归属当前组织，pending_owner 等审
      - public：visibility=public，归属当前组织，pending_owner 等审

    前端使用 <input webkitdirectory> 选择文件夹后上传。
    """
    from app.services import skill_package_service

    # 直接上传入口只接受 target=personal：为保证组织内技能的血缘关系，
    # 组织库/公共市场的内容必须先落地个人库，再通过 fork 覆盖同步过去，
    # 管理员/超管也没有例外（产品决策，见 2026-07-13 计划）
    if target != "personal":
        raise BadRequestError(
            "直接上传只能进入个人库，组织库/公共市场的内容请先上传到个人库、"
            "再通过 fork 覆盖同步过去",
            message_key="errors.gene.upload_target_must_be_personal",
        )

    # 收集文件（与 skills.py upload-folder 相同的前缀剥离逻辑）
    raw_entries: list[tuple[str, UploadFile]] = []
    for upload_file in files:
        raw = (upload_file.filename or "").replace("\\", "/").strip("/")
        if raw:
            raw_entries.append((raw, upload_file))

    if not raw_entries:
        raise BadRequestError("未收到任何文件")

    if len(raw_entries) > _MAX_UPLOAD_FILE_COUNT:
        raise BadRequestError(f"文件数量超过限制（最多 {_MAX_UPLOAD_FILE_COUNT} 个）")

    all_first = {p.split("/", 1)[0] for p, _ in raw_entries if "/" in p}
    has_uniform_prefix = (
        len(all_first) == 1 and all("/" in p for p, _ in raw_entries)
    )
    strip_prefix = (all_first.pop() + "/") if has_uniform_prefix else ""

    files_dict: dict[str, bytes] = {}
    total_size = 0
    for raw, upload_file in raw_entries:
        rel_path = raw[len(strip_prefix):] if strip_prefix and raw.startswith(strip_prefix) else raw
        # 分块读取：每读一块就立即检查单文件/总大小上限，一旦超限马上中止读取，
        # 避免恶意超大文件在被拒绝前就已整体读入内存（此前是 read() 全量读完才检查，防护形同虚设）
        chunks: list[bytes] = []
        file_size = 0
        while True:
            chunk = await upload_file.read(_UPLOAD_READ_CHUNK_SIZE)
            if not chunk:
                break
            file_size += len(chunk)
            if file_size > _MAX_UPLOAD_FILE_SIZE:
                raise BadRequestError(
                    f"文件 {raw} 超过单文件大小限制（{_MAX_UPLOAD_FILE_SIZE // (1024 * 1024)}MB）"
                )
            if total_size + file_size > _MAX_UPLOAD_TOTAL_SIZE:
                raise BadRequestError(
                    f"上传内容总大小超过限制（{_MAX_UPLOAD_TOTAL_SIZE // (1024 * 1024)}MB）"
                )
            chunks.append(chunk)
        total_size += file_size
        files_dict[rel_path] = b"".join(chunks)

    meta = skill_package_service.parse_skill_folder(files_dict)
    manifest = meta.get("manifest", {})

    # 构建 SKILL.md 内容用于 gene 展示（将 manifest 包装为 skill.content）
    skill_content = skill_package_service._find_skill_md_in_files(files_dict)
    skill_raw = skill_content.decode("utf-8") if skill_content else ""

    # target 在函数开头已被限定为 personal（其余值直接 400 拒绝），
    # 归属直接落到当前用户即可：resolve_target_attrs 的 personal 分支
    # 不读取 org_id/bypass_review，不必再查一次 is_user_admin_of_org
    # （org/public 的审核 bypass 判断只在 fork_gene_to_library 里发生）
    attrs = gene_service.resolve_target_attrs(
        target,
        user_id=current_user.id,
        org_id=None,
    )

    gene_req = GeneCreateRequest(
        name=meta["name"],
        slug=_slugify_gene_name(meta["name"]),
        description=meta.get("description", ""),
        short_description=meta.get("description", "")[:256] if meta.get("description") else None,
        source="manual",
        is_published=attrs["is_published"],
        visibility=attrs["visibility"],
        overwrite=overwrite,
        manifest={
            "skill": {
                "name": meta["name"],
                "content": skill_raw,
            },
            **{k: v for k, v in manifest.items() if k != "scripts"},
            "scripts": manifest.get("scripts", {}),
        },
    )

    gene_data = await gene_service.create_gene(
        db, gene_req,
        user_id=attrs["created_by"],
        org_id=attrs["org_id"],
        visibility=attrs["visibility"],
        review_status=attrs["review_status"],
    )
    return ApiResponse(data=gene_data)


@router.get("/genes/{gene_slug}")
async def get_gene(
    gene_slug: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 跨组织隔离：禁止用户通过 slug 直接拉取其他组织的 org_private gene 详情
    await gene_service._assert_user_can_view_gene_by_slug(db, gene_slug, current_user)
    gene = await gene_service.get_gene(db, gene_slug)
    return ApiResponse(data=gene)


def _to_bytes(value) -> bytes:
    """将 manifest 字段值安全转换为 bytes，容忍 None 和非字符串类型。

    二进制 base64 条目（.docx 等）还原为原始字节。
    """
    from app.services import skill_package_service

    if isinstance(value, bytes):
        return value
    if value is None:
        return b""
    if skill_package_service.is_binary_entry(value):
        try:
            return skill_package_service.decode_binary_entry(value)
        except ValueError:
            return b""
    return str(value).encode("utf-8")


@router.get("/genes/{gene_slug}/download")
async def download_gene(
    gene_slug: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """将技能打包为 ZIP 文件供下载，目录结构与 upload-folder 接口对称。"""
    # 权限校验：沿用 get_gene 的跨组织隔离规则
    await gene_service._assert_user_can_view_gene_by_slug(db, gene_slug, current_user)

    # 从数据库查询 Gene ORM 对象（需直接读取 manifest 原始字段）
    result = await db.execute(
        select(Gene).where(Gene.slug == gene_slug, not_deleted(Gene))
    )
    gene = result.scalars().first()
    if not gene:
        raise NotFoundError("技能不存在", "errors.gene.not_found")

    # 解析 manifest JSON（字段为 Text 列，存储为 JSON 字符串）
    try:
        manifest: dict = json.loads(gene.manifest or "{}")
    except json.JSONDecodeError:
        from app.core.exceptions import BadRequestError
        raise BadRequestError("技能数据格式损坏，无法下载", "errors.gene.manifest_corrupt")

    # 在内存中构建 ZIP，避免临时文件 I/O
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # SKILL.md：来自 manifest.skill.content
        skill_content: str = manifest.get("skill", {}).get("content", "")
        zf.writestr(f"{gene_slug}/SKILL.md", _to_bytes(skill_content))

        # scripts：键为纯文件名（如 main.py），放在 {slug}/ 根目录
        for fname, content in manifest.get("scripts", {}).items():
            safe_name = posixpath.basename(fname)
            if safe_name and safe_name != ".":
                zf.writestr(f"{gene_slug}/{safe_name}", _to_bytes(content))

        # assets：键为带子目录的相对路径（如 assets/data.json）
        for rel_path, content in manifest.get("assets", {}).items():
            safe_path = posixpath.normpath(rel_path).lstrip("/")
            if ".." not in safe_path.split("/"):
                zf.writestr(f"{gene_slug}/{safe_path}", _to_bytes(content))

        # references：键为带子目录的相对路径（如 reference/guide.md）
        for rel_path, content in manifest.get("references", {}).items():
            safe_path = posixpath.normpath(rel_path).lstrip("/")
            if ".." not in safe_path.split("/"):
                zf.writestr(f"{gene_slug}/{safe_path}", _to_bytes(content))

    # 计算 ZIP 大小并重置读取位置，用于填写 Content-Length 响应头
    buf.seek(0, 2)
    zip_size = buf.tell()
    buf.seek(0)
    # 对 slug 做安全处理，防止 Content-Disposition 注入，仅保留 slug 规范允许字符
    safe_slug = re.sub(r"[^a-zA-Z0-9_-]", "_", gene_slug)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_slug}.zip"',
            "Content-Length": str(zip_size),
        },
    )


@router.get("/genes/{gene_slug}/variants")
async def gene_variants(
    gene_slug: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await gene_service._assert_user_can_view_gene_by_slug(db, gene_slug, current_user)
    variants = await gene_service.get_gene_variants(db, gene_slug)
    return ApiResponse(data=variants)


@router.get("/genes/{gene_slug}/synergies")
async def gene_synergies(
    gene_slug: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await gene_service._assert_user_can_view_gene_by_slug(db, gene_slug, current_user)
    synergies = await gene_service.get_gene_synergies(db, gene_slug)
    return ApiResponse(data=synergies)


@router.get("/genes/{gene_slug}/genomes")
async def gene_genomes(
    gene_slug: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await gene_service._assert_user_can_view_gene_by_slug(db, gene_slug, current_user)
    data = await gene_service.get_gene_genomes(db, gene_slug)
    return ApiResponse(data=data)


@router.get("/genes/{gene_slug}/installed-instances")
async def gene_installed_instances(
    gene_slug: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await gene_service._assert_user_can_view_gene_by_slug(db, gene_slug, current_user)
    ids = await gene_service.get_gene_installed_instance_ids(db, gene_slug)
    return ApiResponse(data=ids)


@router.post("/genes/{gene_id}/rate")
async def rate_gene(
    gene_id: str,
    req: RatingRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await gene_service.rate_gene(db, gene_id, current_user.id, req.rating, req.comment)
    return ApiResponse(data=result)


# ═══════════════════════════════════════════════════
#  Genome Market
# ═══════════════════════════════════════════════════


@router.get("/genomes")
async def list_genomes(
    keyword: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    genomes, total = await gene_service.list_genomes(db, keyword=keyword, page=page, page_size=page_size)
    return PaginatedResponse(
        data=genomes,
        pagination=Pagination(page=page, page_size=page_size, total=total),
    )


@router.get("/genomes/featured")
async def featured_genomes(
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    genomes = await gene_service.get_featured_genomes(db, limit=limit)
    return ApiResponse(data=genomes)


@router.get("/genomes/{genome_id}")
async def get_genome(
    genome_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    genome = await gene_service.get_genome(db, genome_id)
    return ApiResponse(data=genome)


@router.post("/genomes/{genome_id}/rate")
async def rate_genome(
    genome_id: str,
    req: RatingRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await gene_service.rate_genome(db, genome_id, current_user.id, req.rating, req.comment)
    return ApiResponse(data=result)


# ═══════════════════════════════════════════════════
#  Instance Gene Management
# ═══════════════════════════════════════════════════


@router.get("/instances/{instance_id}/genes")
async def instance_genes(
    instance_id: str,
    db: AsyncSession = Depends(get_db),
    org_ctx=Depends(get_current_org),
):
    _current_user, org = org_ctx
    genes = await gene_service.get_instance_genes(db, instance_id, org.id)
    return ApiResponse(data=genes)


@router.get("/instances/{instance_id}/skills")
async def instance_skills(
    instance_id: str,
    db: AsyncSession = Depends(get_db),
    org_ctx=Depends(get_current_org),
):
    _current_user, org = org_ctx
    skills = await gene_service.get_instance_skills(db, instance_id, org.id)
    return ApiResponse(data=skills)


_SAFE_SKILL_NAME = re.compile(r"^[a-zA-Z0-9_-]+$")


class _SkillContentUpdate(BaseModel):
    content: str


@router.get("/instances/{instance_id}/skills/{skill_name}/content")
async def get_skill_content(
    instance_id: str,
    skill_name: str,
    db: AsyncSession = Depends(get_db),
    org_ctx=Depends(get_current_org),
):
    if not _SAFE_SKILL_NAME.match(skill_name):
        raise BadRequestError(message="skill_name 包含非法字符")

    _current_user, org = org_ctx
    from app.services.instance_service import get_instance
    instance = await get_instance(instance_id, db, org.id)

    from app.services.runtime.registries.runtime_registry import RUNTIME_REGISTRY
    spec = RUNTIME_REGISTRY.get(instance.runtime)
    skills_dir = spec.skills_dir_rel if spec else ".openclaw/skills"

    from app.services.nfs_mount import remote_fs
    async with remote_fs(instance, db) as fs:
        content = await fs.read_text(f"{skills_dir}/{skill_name}/SKILL.md")

    if content is None:
        raise NotFoundError(message=f"Skill '{skill_name}' 不存在")

    return ApiResponse(data={"skill_name": skill_name, "content": content})


@router.put("/instances/{instance_id}/skills/{skill_name}/content")
async def update_skill_content(
    instance_id: str,
    skill_name: str,
    body: _SkillContentUpdate,
    db: AsyncSession = Depends(get_db),
    org_ctx=Depends(get_current_org),
):
    if not _SAFE_SKILL_NAME.match(skill_name):
        raise BadRequestError(message="skill_name 包含非法字符")

    _current_user, org = org_ctx
    from app.services.instance_service import get_instance
    instance = await get_instance(instance_id, db, org.id)

    from app.services.runtime.registries.runtime_registry import RUNTIME_REGISTRY
    spec = RUNTIME_REGISTRY.get(instance.runtime)
    skills_dir = spec.skills_dir_rel if spec else ".openclaw/skills"

    from app.services.nfs_mount import remote_fs
    async with remote_fs(instance, db) as fs:
        existing = await fs.read_text(f"{skills_dir}/{skill_name}/SKILL.md")
        if existing is None:
            raise NotFoundError(message=f"Skill '{skill_name}' 不存在")
        await fs.write_text(f"{skills_dir}/{skill_name}/SKILL.md", body.content)

    return ApiResponse(data={"skill_name": skill_name, "updated": True})


@router.delete("/instances/{instance_id}/skills/{skill_name}")
async def delete_skill_by_name(
    instance_id: str,
    skill_name: str,
    db: AsyncSession = Depends(get_db),
    org_ctx=Depends(get_current_org),
):
    """按技能名称从 Pod 删除技能目录（支持 emerged 和无 InstanceGene 的 hub 技能）。"""
    if not _SAFE_SKILL_NAME.match(skill_name):
        raise BadRequestError(message="skill_name 包含非法字符")
    _current_user, org = org_ctx
    result = await gene_service.delete_skill_by_name(db, instance_id, skill_name, org_id=org.id)
    return ApiResponse(data=result)


@router.post("/instances/{instance_id}/genes/install")
async def install_gene(
    instance_id: str,
    req: InstallGeneRequest,
    db: AsyncSession = Depends(get_db),
    org_ctx=Depends(get_current_org),
):
    _current_user, org = org_ctx
    result = await gene_service.install_gene(db, instance_id, req.gene_slug, org_id=org.id)
    return ApiResponse(data=result)


@router.post("/instances/{instance_id}/genes/uninstall")
async def uninstall_gene(
    instance_id: str,
    req: UninstallGeneRequest,
    db: AsyncSession = Depends(get_db),
    org_ctx=Depends(get_current_org),
):
    _current_user, org = org_ctx
    result = await gene_service.uninstall_gene(db, instance_id, req.gene_id, org_id=org.id)
    return ApiResponse(data=result)


@router.post("/instances/{instance_id}/genomes/apply")
async def apply_genome(
    instance_id: str,
    req: ApplyGenomeRequest,
    db: AsyncSession = Depends(get_db),
    org_ctx=Depends(get_current_org),
):
    _current_user, org = org_ctx
    result = await gene_service.apply_genome(db, instance_id, req.genome_id, org.id)
    return ApiResponse(data=result)


# ═══════════════════════════════════════════════════
#  Evolution: Variant, Effectiveness, Creation
# ═══════════════════════════════════════════════════


@router.post("/instances/{instance_id}/genes/{gene_id}/publish-variant")
async def publish_variant(
    instance_id: str,
    gene_id: str,
    req: PublishVariantRequest,
    db: AsyncSession = Depends(get_db),
    org_ctx=Depends(get_current_org),
):
    _current_user, org = org_ctx
    await gene_service.get_instance_genes(db, instance_id, org.id)
    result = await gene_service.publish_variant(
        db, instance_id, gene_id, req.variant_name, req.variant_slug
    )
    return ApiResponse(data=result)


@router.post("/instances/{instance_id}/genes/{gene_id}/effectiveness")
async def log_effectiveness(
    instance_id: str,
    gene_id: str,
    req: EffectivenessRequest,
    db: AsyncSession = Depends(get_db),
    org_ctx=Depends(get_current_org),
):
    _current_user, org = org_ctx
    await gene_service.get_instance_genes(db, instance_id, org.id)
    result = await gene_service.log_effectiveness(
        db, instance_id, gene_id, req.metric_type, req.value, req.context
    )
    return ApiResponse(data=result)


@router.post("/instances/{instance_id}/genes/create")
async def create_gene_from_agent(
    instance_id: str,
    req: CreateGeneRequest,
    db: AsyncSession = Depends(get_db),
    org_ctx=Depends(get_current_org),
):
    _current_user, org = org_ctx
    result = await gene_service.trigger_gene_creation(db, instance_id, req.creation_prompt, org.id)
    return ApiResponse(data=result)


# ═══════════════════════════════════════════════════
#  Learning Plugin Callbacks (no auth - internal)
# ═══════════════════════════════════════════════════


@router.post("/genes/learning-callback")
async def learning_callback(
    payload: LearningCallbackPayload,
    sig: str | None = Query(None),
    instance_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    _validate_gene_callback_auth(payload, "learn", sig, instance_id)
    result = await gene_service.handle_learning_callback(db, payload)
    return ApiResponse(data=result)


@router.post("/genes/creation-callback")
async def creation_callback(
    payload: LearningCallbackPayload,
    sig: str | None = Query(None),
    instance_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    _validate_gene_callback_auth(payload, "create", sig, instance_id)
    result = await gene_service.handle_creation_callback(db, payload)
    return ApiResponse(data=result)


@router.post("/genes/forgetting-callback")
async def forgetting_callback(
    payload: LearningCallbackPayload,
    sig: str | None = Query(None),
    instance_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    _validate_gene_callback_auth(payload, "forget", sig, instance_id)
    result = await gene_service.handle_forgetting_callback(db, payload)
    return ApiResponse(data=result)


# ═══════════════════════════════════════════════════
#  Evolution Log
# ═══════════════════════════════════════════════════


@router.get("/instances/{instance_id}/evolution-log")
async def get_evolution_log(
    instance_id: str,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    org_ctx=Depends(get_current_org),
):
    _current_user, org = org_ctx
    events = await gene_service.get_evolution_log(db, instance_id, page, page_size, org.id)
    return ApiResponse(data=events)


# ═══════════════════════════════════════════════════
#  Admin
# ═══════════════════════════════════════════════════


@router.get("/admin/genes/stats")
async def admin_gene_stats(
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    stats = await gene_service.get_gene_stats(db)
    return ApiResponse(data=stats.model_dump())


@router.get("/admin/genes/pending-review")
async def admin_pending_review_genes(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 列表内容按权限过滤：超管全部 / 组织 admin 仅本组织 / 其他用户空列表
    genes = await gene_service.get_pending_review_genes(db, current_user=current_user)
    return ApiResponse(data=genes)


@router.get("/admin/genes/activity")
async def admin_gene_activity(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    activity = await gene_service.get_gene_activity(db, limit=limit)
    return ApiResponse(data=activity)


@router.get("/admin/genes/matrix")
async def admin_gene_matrix(
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    matrix = await gene_service.get_gene_matrix(db)
    return ApiResponse(data=matrix)


@router.get("/admin/genes/co-install")
async def admin_co_install(
    min_count: int = Query(2, ge=1),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    pairs = await gene_service.get_co_install_analysis(db, min_count=min_count)
    return ApiResponse(data=[p.model_dump() for p in pairs])


@router.get("/admin/genes")
async def admin_list_genes(
    keyword: str | None = None,
    category: str | None = None,
    is_published: bool | None = None,
    sort: str = "newest",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    genes, total = await gene_service.admin_list_genes(
        db, keyword=keyword, category=category, is_published=is_published,
        sort=sort, page=page, page_size=page_size,
    )
    return PaginatedResponse(
        data=genes,
        pagination=Pagination(page=page, page_size=page_size, total=total),
    )


@router.post("/admin/genes")
async def admin_create_gene(
    req: GeneCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    gene = await gene_service.create_gene(db, req, user_id=current_user.id, org_id=current_user.org_id)
    return ApiResponse(data=gene)


@router.put("/admin/genes/{gene_id}")
async def admin_update_gene(
    gene_id: str,
    req: UpdateGeneRequest,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    result = await gene_service.update_gene(db, gene_id, req)
    return ApiResponse(data=result)


@router.delete("/admin/genes/{gene_id}")
async def admin_delete_gene(
    gene_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    result = await gene_service.soft_delete_gene(db, gene_id)
    return ApiResponse(data=result)


@router.put("/admin/genes/{gene_id}/review")
async def admin_review_gene(
    gene_id: str,
    req: ReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 权限校验下沉到 service：仅 gene 所属 org 的 OrgRole.admin 或平台超管
    result = await gene_service.review_gene(
        db, gene_id, req.action, req.reason, current_user=current_user,
    )
    return ApiResponse(data=result)


@router.put("/admin/gene-overwrite-submissions/{submission_id}/review")
async def admin_review_gene_overwrite_submission(
    submission_id: str,
    req: ReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 权限校验下沉到 service：与 admin_review_gene 一致（该提交所属 org 的
    # OrgRole.admin 或平台超管），且不对提交者自身的 admin 身份做 bypass。
    result = await gene_service.review_gene_overwrite_submission(
        db, submission_id, req.action, req.reason, current_user=current_user,
    )
    return ApiResponse(data=result)


@router.get("/admin/genomes")
async def admin_list_genomes(
    keyword: str | None = None,
    is_published: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    genomes, total = await gene_service.admin_list_genomes(
        db, keyword=keyword, is_published=is_published,
        page=page, page_size=page_size,
    )
    return PaginatedResponse(
        data=genomes,
        pagination=Pagination(page=page, page_size=page_size, total=total),
    )


@router.post("/admin/genomes")
async def admin_create_genome(
    req: GenomeCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    genome = await gene_service.create_genome(db, req, user_id=current_user.id, org_id=current_user.org_id)
    return ApiResponse(data=genome)


@router.put("/admin/genomes/{genome_id}")
async def admin_update_genome(
    genome_id: str,
    req: UpdateGenomeRequest,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    result = await gene_service.update_genome(db, genome_id, req)
    return ApiResponse(data=result)


@router.delete("/admin/genomes/{genome_id}")
async def admin_delete_genome(
    genome_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    result = await gene_service.soft_delete_genome(db, genome_id)
    return ApiResponse(data=result)


# ═══════════════════════════════════════════════════
#  Manual Gene Creation & Publishing
# ═══════════════════════════════════════════════════


@router.post("/genes/manual")
async def create_manual_gene(
    req: ManualGeneCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 直接上传入口只接受 target=personal：为保证组织内技能的血缘关系，
    # 组织库/公共市场的内容必须先落地个人库，再通过 fork 覆盖同步过去，
    # 管理员/超管也没有例外（产品决策，见 2026-07-13 计划）
    if req.target != "personal":
        raise BadRequestError(
            "直接上传只能进入个人库，组织库/公共市场的内容请先上传到个人库、"
            "再通过 fork 覆盖同步过去",
            message_key="errors.gene.upload_target_must_be_personal",
        )

    # target 在函数开头已被限定为 personal（其余值直接 400 拒绝），
    # 归属直接落到当前用户即可：resolve_target_attrs 的 personal 分支
    # 不读取 org_id/bypass_review，不必再查一次 is_user_admin_of_org
    # （org/public 的审核 bypass 判断只在 fork_gene_to_library 里发生）
    attrs = gene_service.resolve_target_attrs(
        req.target,
        user_id=current_user.id,
        org_id=None,
    )

    gene_req = GeneCreateRequest(
        name=req.name,
        slug=req.slug,
        description=req.description,
        short_description=req.short_description,
        category=req.category,
        source="manual",
        is_published=attrs["is_published"],
        visibility=attrs["visibility"],
        manifest={"skill": {"name": req.slug, "content": req.skill_content}},
    )
    gene_data = await gene_service.create_gene(
        db, gene_req,
        user_id=attrs["created_by"],
        org_id=attrs["org_id"],
        visibility=attrs["visibility"],
        review_status=attrs["review_status"],
    )
    # 仅个人 library 时立即同步到 agent 实例；其他目标等审核通过后由用户自行 install
    if req.target == "personal":
        await gene_service.install_gene_prerestart(req.instance_id, req.slug)
    return ApiResponse(data=gene_data)


@router.post("/genes/{gene_identifier}/fork")
async def fork_gene(
    gene_identifier: str,
    req: ForkGeneRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """fork 一份 gene 到个人 / 组织 / 公共 library（三向支持）。

    gene_identifier:
      - 本地 gene：传 gene.id（UUID）。三向 fork 后同一个 slug 可能多 scope 并存，按 slug 查会冲突。
      - 外部 aggregator gene：传外部 slug，本地查不到时回退聚合器。

    - target=personal：副本归属当前用户，无需审核
    - target=org：副本归属当前组织，pending_owner 等组织 admin 审核
    - target=public：副本 visibility=public，归属当前组织，pending_owner 等组织 admin 审核

    权限校验由 service 层按源 scope 分支处理：
      - 个人技能仅本人可 fork；组织技能仅本组成员可 fork；公共技能任意用户可 fork
    """
    if req.target in ("org", "public") and not current_user.current_org_id:
        raise BadRequestError("fork 到组织 / 公共市场前需先加入组织")

    gene_data = await gene_service.fork_gene_to_library(
        db, gene_identifier, req.target,
        current_user=current_user,
        overwrite=req.overwrite,
    )
    return ApiResponse(data=gene_data)


@router.post("/genes/{gene_id}/publish-to-market")
async def publish_gene_to_market(
    gene_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await gene_service.publish_gene_to_market(
        db, gene_id, user_id=current_user.id,
    )
    return ApiResponse(data=result)


@router.delete("/genes/{gene_id}")
async def delete_gene(
    gene_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """用户删除自己上传的 skill / gene（上传者本人 / org admin / 超管均可操作）。

    权限和引用检查均由 gene_service.delete_user_gene 负责：
    - 403：无权删除
    - 409：有实例正在引用，需先卸载
    """
    result = await gene_service.delete_user_gene(db, gene_id, current_user=current_user)
    return ApiResponse(data=result)
