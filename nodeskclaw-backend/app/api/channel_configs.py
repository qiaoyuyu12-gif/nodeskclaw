"""Channel configuration API endpoints for Portal instances."""

import io
import json
import logging
import tarfile
import zipfile

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.channel_api_errors import channel_http_error
from app.core.deps import get_current_org, get_db
from app.models.base import not_deleted
from app.models.instance import Instance
from app.schemas.channel import (
    ChannelConfigsUpdate,
    DeployRepoChannelRequest,
    InstallNpmChannelRequest,
)
from app.schemas.common import ApiResponse
from app.services.channel_config_service import (
    CHANNEL_SCHEMAS,
    REPO_CHANNEL_PLUGINS,
    deploy_repo_channel,
    discover_available_channels,
    install_npm_channel,
    read_channel_configs,
    upload_channel_plugin,
    write_channel_configs,
)
from app.services.unified_channel_schema import get_channel_schema

logger = logging.getLogger(__name__)
router = APIRouter()


def _ok(data=None, message: str = "success"):
    return {"code": 0, "message": message, "data": data}


async def _get_instance(instance_id: str, org_id: str, db: AsyncSession) -> Instance:
    result = await db.execute(
        select(Instance).where(
            Instance.id == instance_id,
            Instance.org_id == org_id,
            not_deleted(Instance),
        )
    )
    instance = result.scalar_one_or_none()
    if not instance:
        raise channel_http_error(404, 40460, "errors.instance.not_found", "实例不存在")
    return instance


@router.get("/{instance_id}/available-channels")
async def list_available_channels(
    instance_id: str,
    org_ctx=Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """扫描实例 Pod 返回可用 Channel 列表。"""
    _, org = org_ctx
    instance = await _get_instance(instance_id, org.id, db)
    runtime = instance.runtime or "openclaw"
    channels = await discover_available_channels(instance, db)

    for ch in channels:
        schema = get_channel_schema(ch["id"], runtime_id=runtime)
        if schema:
            ch["schema"] = schema

    repo_channels = []
    if runtime == "openclaw":
        for cid, info in REPO_CHANNEL_PLUGINS.items():
            if not any(c["id"] == cid for c in channels):
                repo_channels.append({
                    "id": cid,
                    "label": info["dir_name"],
                    "description": f"Project repo: {info['dir_name']}",
                    "origin": "repo",
                    "order": 1000,
                    "has_schema": cid in CHANNEL_SCHEMAS,
                })

    return _ok(channels + repo_channels)


@router.get("/{instance_id}/channel-configs")
async def get_channel_configs(
    instance_id: str,
    org_ctx=Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """读取实例当前已配置的 Channel（排除系统 Channel）。"""
    _, org = org_ctx
    instance = await _get_instance(instance_id, org.id, db)
    configs = await read_channel_configs(instance, db)
    return _ok(configs)


@router.put("/{instance_id}/channel-configs")
async def update_channel_configs(
    instance_id: str,
    body: ChannelConfigsUpdate,
    org_ctx=Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """写入 Channel 配置并重启 OpenClaw。"""
    _, org = org_ctx
    instance = await _get_instance(instance_id, org.id, db)
    result = await write_channel_configs(instance, db, body.configs)
    return _ok(result)


@router.get("/{instance_id}/channel-schema/{channel_id}")
async def get_channel_schema_endpoint(
    instance_id: str,
    channel_id: str,
    org_ctx=Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """获取指定 Channel 的配置表单 Schema。"""
    _, org = org_ctx
    instance = await _get_instance(instance_id, org.id, db)
    runtime = instance.runtime or "openclaw"
    schema = get_channel_schema(channel_id, runtime_id=runtime)
    return _ok({"channel_id": channel_id, "runtime": runtime, "schema": schema})


@router.post("/{instance_id}/channels/install")
async def install_channel_npm(
    instance_id: str,
    body: InstallNpmChannelRequest,
    org_ctx=Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """通过 npm 安装第三方 Channel 插件。"""
    _, org = org_ctx
    instance = await _get_instance(instance_id, org.id, db)
    result = await install_npm_channel(instance, db, body.package_name)
    return _ok(result)


@router.post("/{instance_id}/channels/deploy-repo")
async def deploy_channel_from_repo(
    instance_id: str,
    body: DeployRepoChannelRequest,
    org_ctx=Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """从项目仓库部署自研 Channel 插件到实例。"""
    _, org = org_ctx
    instance = await _get_instance(instance_id, org.id, db)
    result = await deploy_repo_channel(instance, db, body.channel_id)
    return _ok(result)


@router.post("/{instance_id}/channels/upload")
async def upload_channel(
    instance_id: str,
    file: UploadFile = File(...),
    org_ctx=Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """上传 Channel 插件文件（tgz/zip）到实例。"""
    _, org = org_ctx
    instance = await _get_instance(instance_id, org.id, db)

    if not file.filename:
        raise channel_http_error(400, 40060, "errors.channel.empty_filename", "文件名不能为空")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise channel_http_error(400, 40061, "errors.channel.file_too_large", "文件大小不能超过 10MB")

    plugin_files: dict[str, str] = {}
    plugin_id = ""

    try:
        if file.filename.endswith(".tgz") or file.filename.endswith(".tar.gz"):
            plugin_files, plugin_id = _extract_tgz(content)
        elif file.filename.endswith(".zip"):
            plugin_files, plugin_id = _extract_zip(content)
        else:
            raise channel_http_error(400, 40062, "errors.channel.unsupported_format", "仅支持 .tgz / .tar.gz / .zip 格式")
    except HTTPException:
        raise
    except Exception as e:
        raise channel_http_error(400, 40063, "errors.channel.extract_failed", f"文件解压失败: {e}")

    if not plugin_id:
        raise channel_http_error(400, 40064, "errors.channel.missing_plugin_manifest", "插件缺少 openclaw.plugin.json 或未定义 channels")

    result = await upload_channel_plugin(instance, db, plugin_files, plugin_id)
    return _ok(result)


def _extract_tgz(content: bytes) -> tuple[dict[str, str], str]:
    """Extract .tgz/.tar.gz and return (files_dict, plugin_id)."""
    files: dict[str, str] = {}
    plugin_id = ""
    buf = io.BytesIO(content)
    with tarfile.open(fileobj=buf, mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            f = tar.extractfile(member)
            if f is None:
                continue
            text = f.read().decode("utf-8", errors="replace")
            parts = member.name.split("/", 1)
            rel_path = parts[1] if len(parts) > 1 else parts[0]
            # 拒绝 .. 穿越与绝对路径，防止恶意压缩包写穿到目标目录之外（zip-slip）
            if rel_path.startswith("/") or any(seg == ".." for seg in rel_path.split("/")):
                raise ValueError(f"压缩包包含非法路径: {member.name}")
            files[rel_path] = text

    plugin_id = _parse_plugin_id(files)
    return files, plugin_id


def _extract_zip(content: bytes) -> tuple[dict[str, str], str]:
    """Extract .zip and return (files_dict, plugin_id)."""
    files: dict[str, str] = {}
    plugin_id = ""
    buf = io.BytesIO(content)
    with zipfile.ZipFile(buf) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            text = zf.read(info).decode("utf-8", errors="replace")
            parts = info.filename.split("/", 1)
            rel_path = parts[1] if len(parts) > 1 else parts[0]
            if rel_path:
                # 拒绝 .. 穿越与绝对路径，防止恶意压缩包写穿到目标目录之外（zip-slip）
                if rel_path.startswith("/") or any(seg == ".." for seg in rel_path.split("/")):
                    raise ValueError(f"压缩包包含非法路径: {info.filename}")
                files[rel_path] = text

    plugin_id = _parse_plugin_id(files)
    return files, plugin_id


def _parse_plugin_id(files: dict[str, str]) -> str:
    """Extract plugin_id from openclaw.plugin.json in the extracted files."""
    manifest_text = files.get("openclaw.plugin.json", "")
    if not manifest_text:
        return ""
    try:
        manifest = json.loads(manifest_text)
        channels = manifest.get("channels", [])
        if channels:
            return channels[0]
        return manifest.get("id", "")
    except json.JSONDecodeError:
        return ""
