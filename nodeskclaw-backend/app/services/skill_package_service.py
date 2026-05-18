# app/services/skill_package_service.py
"""Parse and store skill packages uploaded as ZIP archives.

A skill package is a ZIP file containing at minimum a ``skill.md`` file with
YAML frontmatter that declares the skill's metadata:

    ---
    name: 产品文档问答
    type: rag_query
    kb_id: <uuid>          # required for rag_query
    config:
      top_k: 5
    ---

    Optional markdown description body follows here.

Any additional files in the ZIP (scripts, assets, etc.) are extracted and
stored alongside the metadata.
"""
import io
import logging
import zipfile
from pathlib import Path

import yaml

from app.core.exceptions import BadRequestError

logger = logging.getLogger(__name__)

_SKILL_MD = "skill.md"
_REQUIRED_FIELDS = {"name", "type"}
_VALID_TYPES = {"rag_query", "gene", "composite"}


def parse_skill_package(data: bytes) -> dict:
    """Parse a ZIP package and return extracted skill metadata.

    Returns a dict with keys: name, type, kb_id (optional), config (dict),
    description (str, the non-frontmatter body of skill.md).

    Raises BadRequestError on any structural or validation problem.
    """
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise BadRequestError("上传的文件不是有效的 ZIP 包")

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        skill_md_path = _find_skill_md(names)
        if skill_md_path is None:
            raise BadRequestError("ZIP 包中未找到 skill.md 文件")

        raw = zf.read(skill_md_path).decode("utf-8")

    return _parse_skill_md(raw)


def _find_skill_md(names: list[str]) -> str | None:
    for name in names:
        if Path(name).name == _SKILL_MD:
            return name
    return None


def _parse_skill_md(raw: str) -> dict:
    """Split YAML frontmatter from Markdown body and validate required fields."""
    if not raw.startswith("---"):
        raise BadRequestError("skill.md 必须以 YAML frontmatter（---）开头")

    parts = raw.split("---", 2)
    if len(parts) < 3:
        raise BadRequestError("skill.md frontmatter 格式错误，缺少结束的 ---")

    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as exc:
        raise BadRequestError(f"skill.md frontmatter YAML 解析失败: {exc}") from exc

    if not isinstance(meta, dict):
        raise BadRequestError("skill.md frontmatter 必须是 YAML 映射（key: value）格式")

    missing = _REQUIRED_FIELDS - meta.keys()
    if missing:
        raise BadRequestError(f"skill.md 缺少必填字段: {', '.join(sorted(missing))}")

    skill_type = str(meta.get("type", ""))
    if skill_type not in _VALID_TYPES:
        raise BadRequestError(f"type 必须是 {', '.join(sorted(_VALID_TYPES))} 之一")

    if skill_type == "rag_query" and not meta.get("kb_id"):
        raise BadRequestError("type 为 rag_query 时 kb_id 为必填项")

    config = meta.get("config", {})
    if not isinstance(config, dict):
        raise BadRequestError("skill.md 中的 config 必须是 YAML 映射格式")

    description = parts[2].strip() if len(parts) > 2 else ""

    return {
        "name": str(meta["name"]).strip(),
        "type": skill_type,
        "kb_id": str(meta["kb_id"]).strip() if meta.get("kb_id") else None,
        "config": config,
        "description": description,
    }


def save_package(org_id: str, skill_name: str, data: bytes, storage_root: str) -> str:
    """Extract ZIP contents to ``<storage_root>/skills/<org_id>/<slug>/`` and return the path.

    Returns the relative path string stored in skill_definitions.package_path.
    """
    import re
    slug = re.sub(r"[^\w\-]", "_", skill_name.lower())[:64]
    dest = Path(storage_root) / "skills" / org_id / slug
    dest.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for member in zf.infolist():
            member_path = dest / Path(member.filename).name
            if member.is_dir():
                continue
            member_path.write_bytes(zf.read(member.filename))

    return str(dest)
