"""No-op gene installation adapter for runtimes that don't yet have specific logic.

Used as a fallback for NanoBot and any future runtimes that
haven't implemented their own GeneInstallAdapter yet. Deploys skills and
scripts to generic paths without runtime-specific config management.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.services.runtime.gene_install_adapter import (
    GeneInstallAdapter,
    sanitize_skill_file_path,
)

if TYPE_CHECKING:
    from app.services.nfs_mount import RemoteFS

logger = logging.getLogger(__name__)

SKILLS_DIR_REL = ".deskclaw/skills"
SCRIPTS_DIR_REL = ".deskclaw/tools"


class NoopGeneInstallAdapter(GeneInstallAdapter):

    async def deploy_skill(
        self, fs: RemoteFS, skill_name: str, content: str, description: str = "",
    ) -> None:
        await fs.mkdir(f"{SKILLS_DIR_REL}/{skill_name}")
        await fs.write_text(f"{SKILLS_DIR_REL}/{skill_name}/SKILL.md", content)

    async def deploy_skill_files(
        self, fs: RemoteFS, skill_name: str, files: dict[str, str | dict],
    ) -> None:
        # 与 OpenClaw 适配器行为一致：附属文件按相对路径写入技能目录
        from app.services.skill_package_service import decode_binary_entry, is_binary_entry

        for rel_path, content in (files or {}).items():
            safe_path = sanitize_skill_file_path(rel_path)
            if safe_path is None:
                logger.warning("deploy_skill_files: 非法相对路径已跳过: %s", rel_path)
                continue
            target = f"{SKILLS_DIR_REL}/{skill_name}/{safe_path}"
            if is_binary_entry(content):
                try:
                    data = decode_binary_entry(content)
                except ValueError as exc:
                    logger.warning("deploy_skill_files: %s %s，已跳过", rel_path, exc)
                    continue
                if data:
                    await fs.write_binary(target, data)
                continue
            if not isinstance(content, str) or not content:
                continue
            await fs.write_text(target, content)

    async def allow_tools(self, fs: RemoteFS, tool_names: list[str]) -> None:
        if tool_names:
            logger.warning(
                "NoopGeneInstallAdapter: allow_tools(%s) called but no runtime-specific "
                "implementation — tools may not be available to the agent",
                tool_names,
            )

    async def deploy_scripts(self, fs: RemoteFS, scripts: dict[str, str]) -> None:
        if not scripts:
            return
        await fs.mkdir(SCRIPTS_DIR_REL)
        for filename, content in scripts.items():
            await fs.write_text(f"{SCRIPTS_DIR_REL}/{filename}", content)

    async def apply_config(self, fs: RemoteFS, config_patch: dict) -> None:
        if config_patch:
            logger.warning(
                "NoopGeneInstallAdapter: apply_config called but no runtime-specific "
                "implementation — config patch dropped: %s",
                list(config_patch.keys()),
            )

    async def invalidate_cache(self, fs: RemoteFS, skill_name: str, event: str = "installed") -> None:
        logger.debug("NoopGeneInstallAdapter: cache invalidation not implemented for skill=%s", skill_name)

    async def remove_skill(self, fs: RemoteFS, skill_name: str) -> None:
        await fs.remove(f"{SKILLS_DIR_REL}/{skill_name}")

    async def post_remove_cleanup(self, fs: RemoteFS, skill_name: str) -> None:
        logger.debug(
            "NoopGeneInstallAdapter: post_remove_cleanup skipped for skill=%s "
            "(no runtime-specific cleanup logic)",
            skill_name,
        )
