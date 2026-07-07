"""OpenClaw-specific gene installation adapter.

Handles:
- Skill file deployment to .openclaw/skills/{name}/SKILL.md with YAML frontmatter
- tool_allow whitelist management in openclaw.json
- Python script deployment to ~/.deskclaw/tools/
- Config merging into openclaw.json
- Skill snapshot invalidation + evolution notification injection
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from app.services.runtime.gene_install_adapter import (
    GeneInstallAdapter,
    sanitize_skill_file_path,
)
from app.utils.jsonc import (
    deep_merge_config,
    ensure_channel_plugin_integrity,
    ensure_exec_security,
    parse_config_json,
)

if TYPE_CHECKING:
    from app.services.nfs_mount import RemoteFS

logger = logging.getLogger(__name__)


class OpenClawGeneInstallAdapter(GeneInstallAdapter):

    def __init__(
        self,
        config_rel_path: str = ".openclaw/openclaw.json",
        skills_dir_rel: str = ".openclaw/skills",
        skills_extra_dir: str = "/root/.openclaw/skills",
        scripts_dir_rel: str = ".deskclaw/tools",
    ):
        self._config_path = config_rel_path
        self._skills_dir = skills_dir_rel
        self._skills_extra_dir = skills_extra_dir
        self._scripts_dir = scripts_dir_rel

    async def deploy_skill(
        self, fs: RemoteFS, skill_name: str, content: str, description: str = "",
    ) -> None:
        if not content.lstrip().startswith("---"):
            desc = description or f"Skill: {skill_name}"
            front_matter = f"---\nname: {skill_name}\ndescription: {desc}\n---\n\n"
            content = front_matter + content

        await fs.mkdir(f"{self._skills_dir}/{skill_name}")
        await fs.write_text(f"{self._skills_dir}/{skill_name}/SKILL.md", content)
        await self._ensure_skills_discovery(fs)

    async def deploy_skill_files(
        self, fs: RemoteFS, skill_name: str, files: dict[str, str | dict],
    ) -> None:
        # 将 reference/example/assets 等附属文件按相对路径写入技能目录，
        # 保证 agent 在实例内能读到 SKILL.md 之外的完整技能包内容
        from app.services.skill_package_service import decode_binary_entry, is_binary_entry

        for rel_path, content in (files or {}).items():
            safe_path = sanitize_skill_file_path(rel_path)
            if safe_path is None:
                logger.warning("deploy_skill_files: 非法相对路径已跳过: %s", rel_path)
                continue
            target = f"{self._skills_dir}/{skill_name}/{safe_path}"
            # 二进制条目（.docx 等）：base64 解码后按字节写入
            if is_binary_entry(content):
                try:
                    data = decode_binary_entry(content)
                except ValueError as exc:
                    logger.warning("deploy_skill_files: %s %s，已跳过", rel_path, exc)
                    continue
                if data:
                    await fs.write_binary(target, data)
                continue
            # 历史数据中二进制文件曾被解码为空字符串，跳过避免写出空文件
            if not isinstance(content, str) or not content:
                continue
            await fs.write_text(target, content)

    async def allow_tools(self, fs: RemoteFS, tool_names: list[str]) -> None:
        if not tool_names:
            return
        try:
            config = await self._read_config(fs)
        except ValueError:
            logger.warning("allow_tools: openclaw.json 解析失败，跳过 tool_allow 写入")
            return
        tools = config.setdefault("tools", {})
        allow = tools.get("allow", [])
        if not isinstance(allow, list):
            allow = []
        existing_set = set(allow)
        for name in tool_names:
            if name not in existing_set:
                allow.append(name)
                existing_set.add(name)
        tools["allow"] = allow
        await self._write_config(fs, config)

    async def deploy_scripts(self, fs: RemoteFS, scripts: dict[str, str]) -> None:
        if not scripts:
            return
        await fs.mkdir(self._scripts_dir)
        for filename, content in scripts.items():
            await fs.write_text(f"{self._scripts_dir}/{filename}", content)

    async def apply_config(self, fs: RemoteFS, config_patch: dict) -> None:
        if not config_patch:
            return
        try:
            config = await self._read_config(fs)
        except ValueError:
            logger.warning("apply_config: openclaw.json 解析失败，跳过配置合并写入")
            return
        deep_merge_config(config, config_patch)
        await self._write_config(fs, config)

    async def invalidate_cache(self, fs: RemoteFS, skill_name: str, event: str = "installed") -> None:
        from app.services.openclaw_session import (
            inject_evolution_notification,
            invalidate_skill_snapshots,
        )
        await invalidate_skill_snapshots(fs)
        await inject_evolution_notification(fs, skill_name, event)

    async def remove_skill(self, fs: RemoteFS, skill_name: str) -> None:
        await fs.remove(f"{self._skills_dir}/{skill_name}")

    async def post_remove_cleanup(self, fs: RemoteFS, skill_name: str) -> None:
        from app.services.openclaw_session import (
            ensure_skills_discovery,
            inject_evolution_notification,
            invalidate_skill_snapshots,
        )
        await ensure_skills_discovery(fs)
        await invalidate_skill_snapshots(fs)
        await inject_evolution_notification(fs, skill_name, "uninstalled")

    async def _ensure_skills_discovery(self, fs: RemoteFS) -> None:
        try:
            config = await self._read_config(fs)
        except ValueError:
            logger.warning("_ensure_skills_discovery: openclaw.json 解析失败，跳过写入")
            return
        skills = config.setdefault("skills", {})
        load = skills.setdefault("load", {})
        extra_dirs = load.setdefault("extraDirs", [])
        if self._skills_extra_dir not in extra_dirs:
            extra_dirs.append(self._skills_extra_dir)
            await self._write_config(fs, config)

    async def _read_config(self, fs: RemoteFS) -> dict:
        """Read and parse openclaw.json with JSONC fallback.

        Raises ValueError if the file is truly corrupt (not just JSONC).
        """
        raw = await fs.read_text(self._config_path)
        if raw is None:
            return {}
        return parse_config_json(raw)

    async def _write_config(self, fs: RemoteFS, config: dict) -> None:
        ensure_exec_security(config)
        ensure_channel_plugin_integrity(config)
        await fs.write_text(
            self._config_path,
            json.dumps(config, indent=2, ensure_ascii=False),
        )
