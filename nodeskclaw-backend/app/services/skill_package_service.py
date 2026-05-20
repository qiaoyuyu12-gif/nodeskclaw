# app/services/skill_package_service.py
"""解析并存储技能包。

支持两种上传方式：
1. ZIP 压缩包：包含 skill.md 及相关文件（原有方式）
2. 文件夹（多文件 multipart）：直接上传文件夹内所有文件，
   系统将其序列化为 manifest JSON，agent 可直接读取命中。

skill.md 格式示例（YAML frontmatter + Markdown 描述体）：

    ---
    name: 产品文档问答
    type: rag_query          # 支持 rag_query / gene / composite / tool
    kb_id: <uuid>            # rag_query 类型必填
    config:
      top_k: 5
    ---

    （可选）Markdown 格式的技能描述...

文件夹结构约定（tool 类型）：

    my-skill/
    ├── skill.md             # 技能声明（必需）
    ├── main.py              # 入口脚本（type=tool 时必需）
    ├── utils.py             # 辅助脚本（可选）
    ├── assets/              # 资源文件（可选，内联进 manifest）
    └── reference/           # 参考资料（可选，内联进 manifest）

manifest JSON 结构（存储在 skill_definitions.manifest 列）：

    {
      "entry":      "main.py",                  // 入口脚本文件名
      "scripts":    {"main.py": "..."},          // Python 脚本字典
      "assets":     {"assets/data.json": "..."}, // 资源文件字典
      "references": {"reference/guide.md": "..."} // 参考资料字典
    }
"""
import io
import logging
import zipfile
from pathlib import Path

import yaml

from app.core.exceptions import BadRequestError

logger = logging.getLogger(__name__)

# skill.md 文件名约定
_SKILL_MD = "skill.md"
# skill.md frontmatter 必填字段
_REQUIRED_FIELDS = {"name", "type"}
# 支持的技能类型：tool 是文件夹上传新增的 Python 工具类型
_VALID_TYPES = {"rag_query", "gene", "composite", "tool"}

# 认定为 Python 脚本的文件扩展名
_SCRIPT_EXTS = {".py"}
# 资源目录前缀
_ASSET_PREFIX = "assets/"
# 参考资料目录前缀
_REFERENCE_PREFIX = "reference/"


def parse_skill_package(data: bytes) -> dict:
    """解析 ZIP 格式技能包，返回技能元数据字典。

    返回字段：name, type, kb_id（可选）, config（dict）,
    description（Markdown 描述体）。
    若结构或校验不通过则抛 BadRequestError。
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


def parse_skill_folder(files: dict[str, bytes]) -> dict:
    """解析文件夹上传的多个文件，返回技能元数据 + manifest 字典。

    参数 files：{文件相对路径: 文件内容字节}，来自 multipart 上传。
    除基础元数据字段外，额外返回 manifest 键，其值包含：
      - entry：入口脚本文件名（type=tool 时必需）
      - scripts：{filename: 脚本内容字符串}
      - assets：{相对路径: 文件内容字符串}
      - references：{相对路径: 文件内容字符串}
    """
    # 1. 从文件集合中查找 skill.md
    skill_md_content = _find_skill_md_in_files(files)
    if skill_md_content is None:
        raise BadRequestError("上传的文件中未找到 skill.md")

    # 2. 解析 skill.md frontmatter + 描述体
    meta = _parse_skill_md(skill_md_content.decode("utf-8"))

    # 3. 按目录分类其余文件，构建 manifest
    scripts: dict[str, str] = {}
    assets: dict[str, str] = {}
    references: dict[str, str] = {}

    for rel_path, content in files.items():
        # 跳过 skill.md 本身（已解析）
        if Path(rel_path).name == _SKILL_MD:
            continue

        suffix = Path(rel_path).suffix.lower()

        if suffix in _SCRIPT_EXTS:
            # Python 脚本：存入 scripts，键为纯文件名
            scripts[Path(rel_path).name] = _safe_decode(content, rel_path)
        elif rel_path.startswith(_ASSET_PREFIX) or "/assets/" in rel_path:
            # assets/ 目录下的资源文件
            assets[rel_path] = _safe_decode(content, rel_path)
        elif rel_path.startswith(_REFERENCE_PREFIX) or "/reference/" in rel_path:
            # reference/ 目录下的参考资料
            references[rel_path] = _safe_decode(content, rel_path)
        else:
            # 其余文件归入 assets
            assets[rel_path] = _safe_decode(content, rel_path)

    # 4. type=tool 时校验必有入口脚本
    config = meta.get("config", {})
    if meta["type"] == "tool":
        entry = config.get("entry", "main.py")
        if entry not in scripts:
            if scripts:
                # 自动选取第一个脚本作为入口
                entry = next(iter(scripts))
                logger.info("tool 类型未在 config.entry 中指定入口，自动选取 %s", entry)
            else:
                raise BadRequestError("type 为 tool 时文件夹内必须包含至少一个 .py 脚本")
        config = {**config, "entry": entry}
        meta["config"] = config

    # 5. 构建 manifest：将所有文件内联序列化供 agent 使用
    manifest: dict = {}
    if meta["type"] == "tool":
        manifest["entry"] = config.get("entry", "")
    if scripts:
        manifest["scripts"] = scripts
    if assets:
        manifest["assets"] = assets
    if references:
        manifest["references"] = references

    meta["manifest"] = manifest
    return meta


def _find_skill_md(names: list[str]) -> str | None:
    """在 ZIP 文件名列表中找到 skill.md 的路径。"""
    for name in names:
        if Path(name).name == _SKILL_MD:
            return name
    return None


def _find_skill_md_in_files(files: dict[str, bytes]) -> bytes | None:
    """在文件字典中找到 skill.md 的内容。"""
    for rel_path, content in files.items():
        if Path(rel_path).name == _SKILL_MD:
            return content
    return None


def _safe_decode(content: bytes, path: str) -> str:
    """将文件内容安全解码为字符串；二进制文件跳过并记录警告。"""
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        logger.warning("文件 %s 无法以 UTF-8 解码，已跳过", path)
        return ""


def _parse_skill_md(raw: str) -> dict:
    """将 skill.md 内容解析为元数据字典。

    格式要求：文件须以 YAML frontmatter（---）开头，
    frontmatter 下方为可选的 Markdown 描述体。
    """
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

    # 校验必填字段
    missing = _REQUIRED_FIELDS - meta.keys()
    if missing:
        raise BadRequestError(f"skill.md 缺少必填字段: {', '.join(sorted(missing))}")

    skill_type = str(meta.get("type", ""))
    if skill_type not in _VALID_TYPES:
        raise BadRequestError(f"type 必须是 {', '.join(sorted(_VALID_TYPES))} 之一")

    # rag_query 类型必须指定 kb_id
    if skill_type == "rag_query" and not meta.get("kb_id"):
        raise BadRequestError("type 为 rag_query 时 kb_id 为必填项")

    config = meta.get("config", {})
    if not isinstance(config, dict):
        raise BadRequestError("skill.md 中的 config 必须是 YAML 映射格式")

    # 描述体为 frontmatter 后面的 Markdown 内容
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
