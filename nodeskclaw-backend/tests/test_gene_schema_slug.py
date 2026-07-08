"""校验 Gene slug 的字符白名单：slug 会作为 skill 目录名拼进远程 exec 命令
（见 nfs_mount.py），必须在 API 边界拒绝含 shell 元字符/路径穿越字符的 slug。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.gene import GeneCreateRequest, ManualGeneCreate


@pytest.mark.parametrize("slug", [
    "x'; touch /tmp/pwned; echo '",
    "../../etc/passwd",
    "foo bar",
    "foo/bar",
])
def test_gene_create_request_rejects_unsafe_slug(slug):
    with pytest.raises(ValidationError):
        GeneCreateRequest(name="x", slug=slug)


def test_gene_create_request_accepts_safe_slug():
    req = GeneCreateRequest(name="x", slug="my-skill_v1")
    assert req.slug == "my-skill_v1"


@pytest.mark.parametrize("slug", [
    "x'; touch /tmp/pwned; echo '",
    "../../etc/passwd",
])
def test_manual_gene_create_rejects_unsafe_slug(slug):
    with pytest.raises(ValidationError):
        ManualGeneCreate(
            name="x", slug=slug, skill_content="# x", instance_id="inst-1",
        )


def test_manual_gene_create_accepts_safe_slug():
    req = ManualGeneCreate(
        name="x", slug="my-skill_v1", skill_content="# x", instance_id="inst-1",
    )
    assert req.slug == "my-skill_v1"
