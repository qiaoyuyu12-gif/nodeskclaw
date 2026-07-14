"""nodeskclaw-backend/tests/test_gene_upload_target_restriction.py

验证直接上传入口只接受 target=personal，org/public（含管理员/超管）一律拒绝。
用 httpx AsyncClient 走真实路由，跟项目里其他 API 层测试的风格一致（复用
tests/conftest.py 里已经配好的 `client` fixture和 get_db override）。
"""
from __future__ import annotations

import io

import pytest

# 注意：genes.py 里实际是 `from app.core.security import get_current_user`
# 再 `Depends(get_current_user)`，dependency_overrides 必须覆盖同一个函数对象，
# 所以这里要从 app.core.security 导入，而不是 app.core.deps（deps.py 只有一个
# 延迟导入用的私有 helper _get_current_user_dep，没有模块级 get_current_user）。
from app.core.security import get_current_user
from app.main import app


class _FakeUser:
    """最小可用的伪用户，覆盖上传接口用到的字段。"""

    id = "u1"
    current_org_id = "org1"
    is_super_admin = False


class _FakeSuperAdmin:
    """伪超管用户：用于验证超管也没有 target 限制的豁免。"""

    id = "admin1"
    current_org_id = "org1"
    is_super_admin = True


@pytest.mark.asyncio
async def test_upload_folder_rejects_org_target(client):
    # 普通用户尝试 target=org 直接上传，应无条件被拒绝（400）
    app.dependency_overrides[get_current_user] = lambda: _FakeUser()
    try:
        files = {"files": ("SKILL.md", io.BytesIO(b"# skill\ncontent"), "text/markdown")}
        resp = await client.post("/api/v1/genes/upload-folder?target=org", files=files)
        assert resp.status_code == 400
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_upload_folder_rejects_org_target_even_for_super_admin(client):
    # 超管尝试 target=public 直接上传，同样应被拒绝，不允许豁免
    # （产品决策：保证组织内技能血缘，管理员也不能绕过 fork 流程直接上传到组织/公共库）
    app.dependency_overrides[get_current_user] = lambda: _FakeSuperAdmin()
    try:
        files = {"files": ("SKILL.md", io.BytesIO(b"# skill\ncontent"), "text/markdown")}
        resp = await client.post("/api/v1/genes/upload-folder?target=public", files=files)
        assert resp.status_code == 400
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_manual_gene_rejects_org_target(client):
    # /genes/manual 走 JSON body，同样只能 target=personal
    app.dependency_overrides[get_current_user] = lambda: _FakeUser()
    try:
        payload = {
            "name": "测试技能",
            "slug": "test-skill-manual-target",
            "description": "desc",
            "skill_content": "# skill\ncontent",
            "instance_id": "inst-1",
            "target": "org",
        }
        resp = await client.post("/api/v1/genes/manual", json=payload)
        assert resp.status_code == 400
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_manual_gene_rejects_org_target_even_for_super_admin(client):
    # 与 upload-folder 对称：超管走 /genes/manual 尝试 target=public 同样应被拒绝
    app.dependency_overrides[get_current_user] = lambda: _FakeSuperAdmin()
    try:
        payload = {
            "name": "测试技能",
            "slug": "test-skill-manual-target-admin",
            "description": "desc",
            "skill_content": "# skill\ncontent",
            "instance_id": "inst-1",
            "target": "public",
        }
        resp = await client.post("/api/v1/genes/manual", json=payload)
        assert resp.status_code == 400
    finally:
        app.dependency_overrides.pop(get_current_user, None)
