"""CE/EE Feature Gate — 运行时功能开关。

判断优先级：
  1. 环境变量 NODESKCLAW_EDITION（值为 ce 或 ee）— 最高优先
  2. 检测项目根目录下 ee/ 子目录是否存在

结果：
  - edition = "ee" -> 所有 feature 启用
  - edition = "ce" -> 仅 CE feature 启用

EE feature 清单从 features.yaml 加载，支持 ee/features.yaml 合并扩展。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(
    os.getenv("NODESKCLAW_ROOT", str(Path(__file__).resolve().parents[3]))
)
_FEATURES_YAML = _PROJECT_ROOT / "features.yaml"
_EE_DIR = _PROJECT_ROOT / "ee"
_EE_FEATURES_YAML = _EE_DIR / "features.yaml"


class FeatureGate:
    def __init__(self) -> None:
        self._edition: str = "ce"
        self._ee_feature_ids: set[str] = set()
        self._all_features: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        env_edition = os.getenv("NODESKCLAW_EDITION", "").lower().strip()
        if env_edition in ("ce", "ee"):
            self._edition = env_edition
        else:
            self._edition = "ee" if _EE_DIR.is_dir() else "ce"

        if _FEATURES_YAML.exists():
            with open(_FEATURES_YAML) as f:
                data = yaml.safe_load(f) or {}
            ee_features = data.get("edition_features", {}).get("ee", [])
            self._all_features.extend(ee_features)

        if self._edition == "ee" and _EE_FEATURES_YAML.exists():
            with open(_EE_FEATURES_YAML) as f:
                data = yaml.safe_load(f) or {}
            extra = data.get("edition_features", {}).get("ee", [])
            existing_ids = {f["id"] for f in self._all_features}
            for feat in extra:
                if feat["id"] not in existing_ids:
                    self._all_features.append(feat)

        self._ee_feature_ids = {f["id"] for f in self._all_features}

        logger.info(
            "FeatureGate: edition=%s%s, ee_features=%d",
            self._edition,
            " (env override)" if env_edition in ("ce", "ee") else "",
            len(self._ee_feature_ids),
        )

        # TODO(super-admin): 启动期对 organization_feature_overrides 中
        # 不属于 self._ee_feature_ids 的孤儿行输出告警日志。
        # 实施位置：app/main.py lifespan 启动钩子，调用一次性 audit。

    @property
    def edition(self) -> str:
        return self._edition

    @property
    def is_ee(self) -> bool:
        return self._edition == "ee"

    def is_enabled(self, feature_id: str) -> bool:
        if feature_id not in self._ee_feature_ids:
            return True
        return self._edition == "ee"

    def enabled_features(self) -> list[str]:
        if self._edition == "ee":
            return sorted(self._ee_feature_ids)
        return []

    def all_features(self) -> list[dict[str, Any]]:
        return [
            {**f, "enabled": self.is_enabled(f["id"])}
            for f in self._all_features
        ]


feature_gate = FeatureGate()


async def is_enabled_for_org(feature_id: str, org_id: str | None, db) -> bool:
    """组织级 override 优先；无 override 回落到 edition 默认。

    db: AsyncSession（运行时传入，避免在模块顶部循环依赖）。
    org_id 为 None 时直接使用 edition 默认值（不查数据库）。
    """
    if org_id is None:
        return feature_gate.is_enabled(feature_id)
    # 延迟 import 防循环
    from app.models.organization_feature_override import OrganizationFeatureOverride
    from sqlalchemy import select as _select
    row = await db.execute(
        _select(OrganizationFeatureOverride.enabled).where(
            OrganizationFeatureOverride.org_id == org_id,
            OrganizationFeatureOverride.feature_id == feature_id,
            OrganizationFeatureOverride.deleted_at.is_(None),
        )
    )
    v = row.scalar_one_or_none()
    if v is not None:
        return v
    return feature_gate.is_enabled(feature_id)
