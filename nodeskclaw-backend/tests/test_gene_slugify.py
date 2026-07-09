"""校验 upload-folder 自动派生 slug 的逻辑（app.api.genes._slugify_gene_name）。

背景：GeneCreateRequest.slug 加了字符白名单正则后（见 test_gene_schema_slug.py），
upload_gene_folder 原来 `meta["name"].lower().replace(" ", "-")` 直接把技能名当 slug，
中文技能名（如"业务操作指引编写"）过滤后不含任何 ASCII 字母数字，slug 变成空字符串，
触发 pydantic ValidationError，导致上传接口 500。
"""

from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from app.api.genes import _slugify_gene_name
from app.schemas.gene import GeneCreateRequest

_SLUG_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


def test_ascii_name_slugified_as_before():
    assert _slugify_gene_name("My Cool Skill") == "my-cool-skill"


@pytest.mark.parametrize("name", [
    "业务操作指引编写",
    "中文",
    "！！！",
    "😀😀😀",
])
def test_non_ascii_name_falls_back_to_deterministic_hash_slug(name):
    slug = _slugify_gene_name(name)
    assert _SLUG_PATTERN.match(slug), f"slug {slug!r} 不满足 schema 白名单正则"
    # 兜底 slug 每次都要一致，保证同名技能重复上传时 create_gene 仍能命中冲突/覆盖判定
    assert _slugify_gene_name(name) == slug


def test_mixed_name_keeps_ascii_part_and_drops_illegal_chars():
    slug = _slugify_gene_name("客户 Support Bot")
    assert _SLUG_PATTERN.match(slug)
    assert "support" in slug and "bot" in slug


def test_slugify_result_always_accepted_by_schema():
    for name in ["业务操作指引编写", "My Cool Skill", "😀", "a b/c'd"]:
        req = GeneCreateRequest(name=name, slug=_slugify_gene_name(name))
        assert req.slug


def test_empty_or_whitespace_name_still_produces_valid_slug():
    slug = _slugify_gene_name("   ")
    assert _SLUG_PATTERN.match(slug)
