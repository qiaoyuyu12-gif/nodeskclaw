# Gene 技能名称查重 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 personal/org/public 三个 scope 分别做技能（Gene）名称查重，同 scope 内不允许出现 trim+忽略大小写后相同的技能名称。

**Architecture:** 应用层预检查（新增 `get_gene_by_name_in_scope`，接入 `create_gene()` 和 `fork_gene_to_library()`）+ 数据库 3 条 partial unique index 兜底（`genes` 表按 scope 分别对 `lower(trim(name))` 建唯一索引），预检查命中直接 `ConflictError`（409），DB 层竞态兜底同样转换为 `ConflictError`。

**Tech Stack:** FastAPI + SQLAlchemy 2.0 (async) + asyncpg + Alembic，PostgreSQL partial/functional unique index。

**关联设计文档：** `docs/superpowers/specs/2026-07-10-gene-name-dedup-design.md`

---

### Task 1: 数据库 — 新增 3 条 partial unique index

**Files:**
- Modify: `nodeskclaw-backend/app/models/gene.py:1-20`（imports）、`:74-84`（`Gene.__table_args__`）
- Create: `nodeskclaw-backend/alembic/versions/<autogen_hash>_add_gene_name_dedup_indexes.py`

- [ ] **Step 1: 修改 `app/models/gene.py` 的 import，加入 `text`**

将文件顶部的 import 块：

```python
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
```

改为：

```python
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
```

- [ ] **Step 2: 在 `Gene.__table_args__` 中新增 3 条 partial unique index**

把 `app/models/gene.py:74-84` 的：

```python
class Gene(BaseModel):
    __tablename__ = "genes"
    __table_args__ = (
        Index(
            "uq_genes_slug_org_active",
            "slug",
            "org_id",
            unique=True,
            postgresql_where="deleted_at IS NULL",
        ),
    )
```

改为：

```python
class Gene(BaseModel):
    __tablename__ = "genes"
    __table_args__ = (
        Index(
            "uq_genes_slug_org_active",
            "slug",
            "org_id",
            unique=True,
            postgresql_where="deleted_at IS NULL",
        ),
        # 以下 3 条按 scope 分别对技能名称（trim + 忽略大小写）做唯一约束，
        # 与 get_gene_by_name_in_scope() 的应用层预检查语义一一对应，
        # 作为并发场景下的最后一道防线（防止两个请求同时通过预检查）。
        Index(
            "uq_genes_name_personal_active",
            text("lower(trim(name))"),
            "created_by",
            unique=True,
            postgresql_where="deleted_at IS NULL AND visibility = 'personal'",
        ),
        Index(
            "uq_genes_name_org_active",
            text("lower(trim(name))"),
            "org_id",
            unique=True,
            postgresql_where="deleted_at IS NULL AND visibility = 'org_private'",
        ),
        Index(
            "uq_genes_name_public_active",
            text("lower(trim(name))"),
            unique=True,
            postgresql_where="deleted_at IS NULL AND visibility = 'public'",
        ),
    )
```

- [ ] **Step 3: 生成 Alembic migration（禁止手写 revision ID）**

Run（WSL）:
```bash
wsl -e bash -lc "cd /mnt/c/Users/gg102/my_project/nodeskclaw/nodeskclaw-backend && uv run alembic revision --autogenerate -m 'add gene name dedup partial unique indexes'"
```

命令会在 `alembic/versions/` 下生成一个新文件，形如 `<hash>_add_gene_name_dedup_partial_unique_.py`。

- [ ] **Step 4: 核对生成的 migration 内容，若与预期不符则手动修正**

打开生成的文件，`upgrade()` 函数应该只包含新增的 3 条索引（不应包含 `uq_genes_slug_org_active`，它已存在于基线迁移中，autogenerate 不应重复生成）。预期内容：

```python
def upgrade() -> None:
    op.create_index(
        'uq_genes_name_personal_active', 'genes',
        [sa.text('lower(trim(name))'), 'created_by'],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND visibility = 'personal'"),
    )
    op.create_index(
        'uq_genes_name_org_active', 'genes',
        [sa.text('lower(trim(name))'), 'org_id'],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND visibility = 'org_private'"),
    )
    op.create_index(
        'uq_genes_name_public_active', 'genes',
        [sa.text('lower(trim(name))')],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND visibility = 'public'"),
    )


def downgrade() -> None:
    op.drop_index('uq_genes_name_public_active', table_name='genes', postgresql_where=sa.text("deleted_at IS NULL AND visibility = 'public'"))
    op.drop_index('uq_genes_name_org_active', table_name='genes', postgresql_where=sa.text("deleted_at IS NULL AND visibility = 'org_private'"))
    op.drop_index('uq_genes_name_personal_active', table_name='genes', postgresql_where=sa.text("deleted_at IS NULL AND visibility = 'personal'"))
```

若 autogenerate 生成的内容与上面不一致（例如漏掉 `postgresql_where`，或把 3 条索引都识别成了 diff 之外的内容），直接用上面的代码手动替换 `upgrade()`/`downgrade()` 函数体，**保留 autogenerate 生成的 `revision`/`down_revision` 头部不动**。

- [ ] **Step 5: 存量重名数据检测（迁移前置检查）**

Run（WSL，用 psql 或已连接的测试库）：
```bash
wsl -e bash -lc "cd /mnt/c/Users/gg102/my_project/nodeskclaw/nodeskclaw-backend && uv run python -c \"
import asyncio
from sqlalchemy import text
from app.core.database import engine

async def check():
    async with engine.connect() as conn:
        for scope_sql in [
            \\\"SELECT lower(trim(name)) n, created_by, count(*) FROM genes WHERE deleted_at IS NULL AND visibility='personal' GROUP BY 1,2 HAVING count(*)>1\\\",
            \\\"SELECT lower(trim(name)) n, org_id, count(*) FROM genes WHERE deleted_at IS NULL AND visibility='org_private' GROUP BY 1,2 HAVING count(*)>1\\\",
            \\\"SELECT lower(trim(name)) n, count(*) FROM genes WHERE deleted_at IS NULL AND visibility='public' GROUP BY 1 HAVING count(*)>1\\\",
        ]:
            result = await conn.execute(text(scope_sql))
            rows = result.fetchall()
            if rows:
                print('发现重名:', rows)

asyncio.run(check())
\""
```

若脚本打印出"发现重名"，**停下来向用户报告具体重复的 name/scope**，不要自行改名或删除，等待用户决定处理方式后再继续 Step 6。若无输出，说明无历史脏数据，继续下一步。

- [ ] **Step 6: 应用 migration**

Run（WSL）:
```bash
wsl -e bash -lc "cd /mnt/c/Users/gg102/my_project/nodeskclaw/nodeskclaw-backend && uv run alembic upgrade head"
```
Expected: 命令成功退出，无报错（若 Step 5 发现重名且未处理，这一步会因唯一约束冲突而失败，属预期行为）。

- [ ] **Step 7: Commit**

```bash
git add nodeskclaw-backend/app/models/gene.py nodeskclaw-backend/alembic/versions/
git commit -m "$(cat <<'EOF'
feat(backend): 新增 Gene 名称按 scope 查重的唯一索引

按 personal(按用户)/org(按组织)/public(全局) 三个 scope 分别对
lower(trim(name)) 建 partial unique index，作为应用层查重预检查
之外的数据库并发安全网。
EOF
)"
```

---

### Task 2: `get_gene_by_name_in_scope` 查询函数

**Files:**
- Modify: `nodeskclaw-backend/app/services/gene_service.py`（imports、新增函数）
- Test: `nodeskclaw-backend/tests/test_gene_name_dedup.py`（新建）

- [ ] **Step 1: 修改 imports**

把 `app/services/gene_service.py` 顶部：

```python
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
```

改为（新增 `IntegrityError`）：

```python
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
```

把：

```python
from app.models.gene import (
    EffectMetricType,
    EvolutionEvent,
    EvolutionEventType,
    Gene,
    GeneEffectLog,
    GeneRating,
    GeneReviewStatus,
    GeneSource,
    Genome,
    GenomeRating,
    InstanceGene,
    InstanceGeneStatus,
)
```

改为（新增 `ContentVisibility`）：

```python
from app.models.gene import (
    ContentVisibility,
    EffectMetricType,
    EvolutionEvent,
    EvolutionEventType,
    Gene,
    GeneEffectLog,
    GeneRating,
    GeneReviewStatus,
    GeneSource,
    Genome,
    GenomeRating,
    InstanceGene,
    InstanceGeneStatus,
)
```

- [ ] **Step 2: 写失败的测试（新建 `tests/test_gene_name_dedup.py`）**

```python
"""验证 Gene 按 scope（personal/org/public）分别查重的逻辑。

背景：genes 表原本只有 (slug, org_id) 唯一约束，name 完全没有唯一性校验，
导致同一 scope 下可以出现多个同名但 slug 不同的技能。本文件覆盖：
  - get_gene_by_name_in_scope 按 scope 精确查重
  - create_gene 接入 name 查重（含 overwrite 场景）
  - fork_gene_to_library 接入 name 查重
  - 并发竞态下 IntegrityError 被正确转换成 ConflictError

用真实 PostgreSQL 测试库（与 test_org_member_soft_delete.py 一致的模式），
因为要验证的是数据库唯一索引的真实约束行为，mock 掉 db 无法覆盖这一点。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import ConflictError
from app.models.organization import Organization
from app.models.user import User
from app.schemas.gene import GeneCreateRequest
from app.services.gene_service import create_gene, get_gene_by_name_in_scope

TEST_DATABASE_URL = "postgresql+asyncpg://nodeskclaw:nodeskclaw123@localhost:5432/nodeskclaw_rbac_test"
engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def require_test_db():
    try:
        async with engine.connect():
            yield
    except Exception:
        pytest.skip("PostgreSQL test database is not available")


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.mark.asyncio
async def test_get_gene_by_name_in_scope_returns_none_when_absent(require_test_db):
    async with TestSessionLocal() as db:
        result = await get_gene_by_name_in_scope(
            db, "不存在的技能", visibility="public",
        )
        assert result is None
```

- [ ] **Step 3: 运行测试确认失败（缺函数）**

Run:
```bash
wsl -e bash -lc "cd /mnt/c/Users/gg102/my_project/nodeskclaw/nodeskclaw-backend && uv run pytest tests/test_gene_name_dedup.py -v"
```
Expected: `ImportError: cannot import name 'get_gene_by_name_in_scope'`

- [ ] **Step 4: 实现 `get_gene_by_name_in_scope`**

在 `app/services/gene_service.py` 中，紧跟在 `get_gene_by_slug_in_scope` 函数之后（第 691 行后、`async def create_gene` 之前）插入：

```python
async def get_gene_by_name_in_scope(
    db: AsyncSession,
    name: str,
    *,
    visibility: str,
    org_id: str | None = None,
    created_by: str | None = None,
) -> Gene | None:
    """按 (trim+忽略大小写的 name, scope) 精确定位一条未删除 gene。

    与 3 条 uq_genes_name_* partial unique index 语义一一对应：
      - personal：按 (小写trim后的 name, created_by) 判重
      - org_private：按 (小写trim后的 name, org_id) 判重
      - public：全局按小写trim后的 name 判重，不再附加 org_id/created_by 条件

    用 first() 而非 scalar_one_or_none()——理论上 scope 内不会有多条，但按
    项目既有踩坑经验（同 slug 跨 scope 并存过 MultipleResultsFound），一律
    用 first() 更保守。
    """
    normalized = name.strip().lower()
    stmt = select(Gene).where(
        func.lower(func.trim(Gene.name)) == normalized,
        Gene.visibility == visibility,
        not_deleted(Gene),
    )
    if visibility == ContentVisibility.personal:
        stmt = stmt.where(Gene.created_by == created_by)
    elif visibility == ContentVisibility.org_private:
        stmt = stmt.where(Gene.org_id == org_id)
    result = await db.execute(stmt)
    return result.scalars().first()
```

- [ ] **Step 5: 运行测试确认通过**

Run:
```bash
wsl -e bash -lc "cd /mnt/c/Users/gg102/my_project/nodeskclaw/nodeskclaw-backend && uv run pytest tests/test_gene_name_dedup.py -v"
```
Expected: `1 passed`

- [ ] **Step 6: Commit**

```bash
git add nodeskclaw-backend/app/services/gene_service.py nodeskclaw-backend/tests/test_gene_name_dedup.py
git commit -m "$(cat <<'EOF'
feat(backend): 新增 get_gene_by_name_in_scope 按 scope 查重函数

与新增的 3 条 uq_genes_name_* partial unique index 语义对应，
personal 按 created_by、org 按 org_id、public 全局做 name 精确匹配
（trim + 忽略大小写）。
EOF
)"
```

---

### Task 3: `create_gene()` 接入 name 查重

**Files:**
- Modify: `nodeskclaw-backend/app/services/gene_service.py:694-742`（`create_gene`）
- Test: `nodeskclaw-backend/tests/test_gene_name_dedup.py`

- [ ] **Step 1: 追加失败的测试**

在 `tests/test_gene_name_dedup.py` 末尾追加：

```python
def _minimal_req(name: str, slug: str, *, visibility: str = "public", overwrite: bool = False) -> GeneCreateRequest:
    return GeneCreateRequest(name=name, slug=slug, visibility=visibility, overwrite=overwrite)


@pytest.mark.asyncio
async def test_create_gene_rejects_duplicate_name_in_same_personal_scope(require_test_db):
    async with TestSessionLocal() as db:
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add(user)
        await db.commit()

        await create_gene(
            db, _minimal_req("客服助手", "customer-bot-1", visibility="personal"),
            user_id=user.id, org_id=None, visibility="personal",
        )

        with pytest.raises(ConflictError):
            await create_gene(
                db, _minimal_req(" 客服助手 ", "customer-bot-2", visibility="personal"),
                user_id=user.id, org_id=None, visibility="personal",
            )


@pytest.mark.asyncio
async def test_create_gene_allows_same_name_for_different_users_in_personal_scope(require_test_db):
    async with TestSessionLocal() as db:
        user_a = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        user_b = User(id=_uid("user"), name="Bob", username=_uid("bob"))
        db.add_all([user_a, user_b])
        await db.commit()

        await create_gene(
            db, _minimal_req("客服助手", "a-customer-bot", visibility="personal"),
            user_id=user_a.id, org_id=None, visibility="personal",
        )
        result = await create_gene(
            db, _minimal_req("客服助手", "b-customer-bot", visibility="personal"),
            user_id=user_b.id, org_id=None, visibility="personal",
        )
        assert result["name"] == "客服助手"


@pytest.mark.asyncio
async def test_create_gene_rejects_duplicate_name_in_same_org(require_test_db):
    async with TestSessionLocal() as db:
        org = Organization(id=_uid("org"), name="Org A", slug=_uid("org-a"))
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add_all([org, user])
        await db.commit()

        await create_gene(
            db, _minimal_req("团队助手", "team-bot-1", visibility="org_private"),
            user_id=user.id, org_id=org.id, visibility="org_private",
        )
        with pytest.raises(ConflictError):
            await create_gene(
                db, _minimal_req("团队助手", "team-bot-2", visibility="org_private"),
                user_id=user.id, org_id=org.id, visibility="org_private",
            )


@pytest.mark.asyncio
async def test_create_gene_allows_same_name_in_different_orgs(require_test_db):
    async with TestSessionLocal() as db:
        org_a = Organization(id=_uid("org"), name="Org A", slug=_uid("org-a"))
        org_b = Organization(id=_uid("org"), name="Org B", slug=_uid("org-b"))
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add_all([org_a, org_b, user])
        await db.commit()

        await create_gene(
            db, _minimal_req("团队助手", "a-team-bot", visibility="org_private"),
            user_id=user.id, org_id=org_a.id, visibility="org_private",
        )
        result = await create_gene(
            db, _minimal_req("团队助手", "b-team-bot", visibility="org_private"),
            user_id=user.id, org_id=org_b.id, visibility="org_private",
        )
        assert result["name"] == "团队助手"


@pytest.mark.asyncio
async def test_create_gene_rejects_duplicate_name_in_public_market(require_test_db):
    async with TestSessionLocal() as db:
        org = Organization(id=_uid("org"), name="Org A", slug=_uid("org-a"))
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add_all([org, user])
        await db.commit()

        await create_gene(
            db, _minimal_req("公开助手", "public-bot-1", visibility="public"),
            user_id=user.id, org_id=org.id, visibility="public",
        )
        with pytest.raises(ConflictError):
            await create_gene(
                db, _minimal_req("公开助手", "public-bot-2", visibility="public"),
                user_id=user.id, org_id=org.id, visibility="public",
            )


@pytest.mark.asyncio
async def test_create_gene_overwrite_allows_same_name(require_test_db):
    async with TestSessionLocal() as db:
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add(user)
        await db.commit()

        await create_gene(
            db, _minimal_req("客服助手", "customer-bot", visibility="personal"),
            user_id=user.id, org_id=None, visibility="personal",
        )
        result = await create_gene(
            db, _minimal_req("客服助手", "customer-bot", visibility="personal", overwrite=True),
            user_id=user.id, org_id=None, visibility="personal",
        )
        assert result["name"] == "客服助手"


@pytest.mark.asyncio
async def test_create_gene_integrity_error_on_commit_becomes_conflict_error(require_test_db, monkeypatch):
    """模拟并发竞态：预检查都通过后，commit 阶段才因唯一索引冲突而失败。"""
    from app.services import gene_service

    async with TestSessionLocal() as db:
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add(user)
        await db.commit()

        async def _boom():
            from sqlalchemy.exc import IntegrityError
            raise IntegrityError("INSERT", {}, Exception("uq_genes_name_personal_active"))

        monkeypatch.setattr(db, "commit", _boom)

        with pytest.raises(ConflictError):
            await create_gene(
                db, _minimal_req("竞态助手", "race-bot", visibility="personal"),
                user_id=user.id, org_id=None, visibility="personal",
            )
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```bash
wsl -e bash -lc "cd /mnt/c/Users/gg102/my_project/nodeskclaw/nodeskclaw-backend && uv run pytest tests/test_gene_name_dedup.py -v"
```
Expected: 新增的用例全部 FAIL（`create_gene` 还没有做 name 查重，也没有 catch `IntegrityError`）

- [ ] **Step 3: 修改 `create_gene()`**

把 `app/services/gene_service.py:694-742` 的：

```python
async def create_gene(
    db: AsyncSession, req: GeneCreateRequest, user_id: str | None = None, org_id: str | None = None,
    visibility: str | None = None,
    review_status: str | None = None,
) -> dict:
    # 冲突判定按 (slug, org_id) 进行，对齐 partial unique index `uq_genes_slug_org_active`。
    # personal scope（org_id IS NULL）下，索引允许多个用户共用同 slug，因此用 created_by
    # 进一步限定到"当前用户的 personal 同 slug"，避免误报。
    existing = await get_gene_by_slug_in_scope(
        db, req.slug, org_id=org_id, created_by=user_id,
    )
    if existing:
        if req.overwrite:
            # 覆盖模式：软删除该 scope 内的旧基因，再创建新基因
            existing.soft_delete()
            await db.commit()
        else:
            raise ConflictError(f"基因 slug '{req.slug}' 已存在")

    _validate_skill_metadata(req.manifest, req.short_description, req.description)

    gene = Gene(
        name=req.name,
        slug=req.slug,
        description=req.description,
        short_description=req.short_description,
        category=req.category,
        tags=_json_dumps(req.tags),
        source=req.source,
        source_ref=req.source_ref,
        icon=req.icon,
        version=req.version,
        manifest=_json_dumps(req.manifest),
        dependencies=_json_dumps(req.dependencies),
        synergies=_json_dumps(req.synergies),
        is_featured=req.is_featured,
        is_published=req.is_published,
        visibility=visibility or req.visibility,
        review_status=review_status,
        created_by=user_id,
        org_id=org_id,
        # 标记为本地创建，确保前端"删除/编辑"等仅对本地 gene 显示的入口可见
        # （外部 registry 同步走 genehub_client，自带 registry_id；不进此路径）
        source_registry="local",
    )
    db.add(gene)
    await db.commit()
    await db.refresh(gene)
    return _gene_to_dict(gene)
```

改为：

```python
async def create_gene(
    db: AsyncSession, req: GeneCreateRequest, user_id: str | None = None, org_id: str | None = None,
    visibility: str | None = None,
    review_status: str | None = None,
) -> dict:
    resolved_visibility = visibility or req.visibility

    # 冲突判定按 (slug, org_id) 进行，对齐 partial unique index `uq_genes_slug_org_active`。
    # personal scope（org_id IS NULL）下，索引允许多个用户共用同 slug，因此用 created_by
    # 进一步限定到"当前用户的 personal 同 slug"，避免误报。
    existing = await get_gene_by_slug_in_scope(
        db, req.slug, org_id=org_id, created_by=user_id,
    )
    # 名称查重按 scope 分别进行（personal 按用户、org 按组织、public 全局），
    # 对齐新增的 3 条 uq_genes_name_* partial unique index。
    existing_name = await get_gene_by_name_in_scope(
        db, req.name, visibility=resolved_visibility, org_id=org_id, created_by=user_id,
    )
    if existing or existing_name:
        if req.overwrite:
            # 覆盖模式：软删除该 scope 内命中的旧基因（slug 和 name 命中的可能是
            # 同一行，也可能是两行，两个都要软删，避免插入新行时任一唯一索引冲突）
            if existing:
                existing.soft_delete()
            if existing_name and existing_name is not existing:
                existing_name.soft_delete()
            await db.commit()
        elif existing:
            raise ConflictError(f"基因 slug '{req.slug}' 已存在")
        else:
            raise ConflictError(f"技能名称 '{req.name}' 已存在")

    _validate_skill_metadata(req.manifest, req.short_description, req.description)

    gene = Gene(
        name=req.name,
        slug=req.slug,
        description=req.description,
        short_description=req.short_description,
        category=req.category,
        tags=_json_dumps(req.tags),
        source=req.source,
        source_ref=req.source_ref,
        icon=req.icon,
        version=req.version,
        manifest=_json_dumps(req.manifest),
        dependencies=_json_dumps(req.dependencies),
        synergies=_json_dumps(req.synergies),
        is_featured=req.is_featured,
        is_published=req.is_published,
        visibility=resolved_visibility,
        review_status=review_status,
        created_by=user_id,
        org_id=org_id,
        # 标记为本地创建，确保前端"删除/编辑"等仅对本地 gene 显示的入口可见
        # （外部 registry 同步走 genehub_client，自带 registry_id；不进此路径）
        source_registry="local",
    )
    db.add(gene)
    try:
        await db.commit()
    except IntegrityError as e:
        # 极小概率竞态：两个请求同时通过了上面的预检查。DB 唯一索引在此兜底，
        # 统一转换成 ConflictError，不暴露内部约束名等实现细节。
        await db.rollback()
        raise ConflictError(f"基因 slug '{req.slug}' 或名称 '{req.name}' 已存在") from e
    await db.refresh(gene)
    return _gene_to_dict(gene)
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```bash
wsl -e bash -lc "cd /mnt/c/Users/gg102/my_project/nodeskclaw/nodeskclaw-backend && uv run pytest tests/test_gene_name_dedup.py -v"
```
Expected: 全部 PASS

- [ ] **Step 5: 跑一次现有 gene 相关测试确认没有回归**

Run:
```bash
wsl -e bash -lc "cd /mnt/c/Users/gg102/my_project/nodeskclaw/nodeskclaw-backend && uv run pytest tests/test_gene_slugify.py tests/test_gene_schema_slug.py tests/test_gene_upload_limits.py tests/test_gene_delete_permission.py -v"
```
Expected: 全部 PASS（这些测试目前 mock db 或走无冲突路径，不应受影响）

- [ ] **Step 6: Commit**

```bash
git add nodeskclaw-backend/app/services/gene_service.py nodeskclaw-backend/tests/test_gene_name_dedup.py
git commit -m "$(cat <<'EOF'
feat(backend): create_gene 接入技能名称查重

按 scope（personal/org/public）分别校验 name 是否已存在，命中直接
409 ConflictError；overwrite=true 时软删旧记录后允许覆盖。commit
阶段新增 IntegrityError 捕获，作为预检查之外的并发竞态兜底。
EOF
)"
```

---

### Task 4: `fork_gene_to_library()` 接入 name 查重

**Files:**
- Modify: `nodeskclaw-backend/app/services/gene_service.py:3520-3536`（`fork_gene_to_library`）
- Modify: `nodeskclaw-backend/tests/test_gene_target_fork_review.py`（`_make_fork_db` 辅助函数 + 新增测试）

- [ ] **Step 1: 修改 `_make_fork_db` 测试辅助函数，插入 name 查重的 mock 步骤**

把 `tests/test_gene_target_fork_review.py:232-279` 的：

```python
def _make_fork_db(
    source: _FakeGene | None,
    *,
    membership=None,
    has_slug_conflict: bool = False,
    is_target_admin: bool = False,
    has_target_org: bool = True,
) -> MagicMock:
    """构造 fork 流程所需的 mock db。

    调用顺序（取决于路径）：
      0. is_user_admin_of_org → OrgMembership(user, target_org, role=admin)
         仅当非超管且 effective_org_id 不为 None 时才会真的 SQL 查询
      1. select(Gene) by id → source
      2. （仅当非超管且源为 org scope 时）select(OrgMembership) → membership
      3. select(Gene) for slug 冲突 → existing
    db.add 为同步 MagicMock；db.commit / db.refresh 为 AsyncMock。
    """
    db = MagicMock()

    side_effects: list[MagicMock] = []

    # 0. is_user_admin_of_org 查询（target_org 存在 + 非超管才走到 SQL）
    if has_target_org:
        admin_result = MagicMock()
        admin_result.scalar_one_or_none.return_value = MagicMock() if is_target_admin else None
        side_effects.append(admin_result)

    # 1. 源 gene 查询
    src_result = MagicMock()
    src_result.scalar_one_or_none.return_value = source
    side_effects.append(src_result)

    # 2. OrgMembership（仅在测试构造时显式标记）
    if membership is not None or (source is not None and getattr(source, "_expect_membership_query", False)):
        m_result = MagicMock()
        m_result.scalar_one_or_none.return_value = membership
        side_effects.append(m_result)

    # 3. slug 冲突查询
    conflict_result = MagicMock()
    conflict_result.scalar_one_or_none.return_value = MagicMock() if has_slug_conflict else None
    side_effects.append(conflict_result)

    db.execute = AsyncMock(side_effect=side_effects)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db
```

改为（新增 `has_name_conflict` 参数 + 第 3 步 name 查重 mock，插在 slug 冲突查询之前，对应生产代码里 name 检查先于 slug 改名逻辑）：

```python
def _make_fork_db(
    source: _FakeGene | None,
    *,
    membership=None,
    has_slug_conflict: bool = False,
    has_name_conflict: bool = False,
    is_target_admin: bool = False,
    has_target_org: bool = True,
) -> MagicMock:
    """构造 fork 流程所需的 mock db。

    调用顺序（取决于路径）：
      0. is_user_admin_of_org → OrgMembership(user, target_org, role=admin)
         仅当非超管且 effective_org_id 不为 None 时才会真的 SQL 查询
      1. select(Gene) by id → source
      2. （仅当非超管且源为 org scope 时）select(OrgMembership) → membership
      3. select(Gene) for name 查重（get_gene_by_name_in_scope）→ existing_name
      4. select(Gene) for slug 冲突 → existing
    db.add 为同步 MagicMock；db.commit / db.refresh 为 AsyncMock。
    """
    db = MagicMock()

    side_effects: list[MagicMock] = []

    # 0. is_user_admin_of_org 查询（target_org 存在 + 非超管才走到 SQL）
    if has_target_org:
        admin_result = MagicMock()
        admin_result.scalar_one_or_none.return_value = MagicMock() if is_target_admin else None
        side_effects.append(admin_result)

    # 1. 源 gene 查询
    src_result = MagicMock()
    src_result.scalar_one_or_none.return_value = source
    side_effects.append(src_result)

    # 2. OrgMembership（仅在测试构造时显式标记）
    if membership is not None or (source is not None and getattr(source, "_expect_membership_query", False)):
        m_result = MagicMock()
        m_result.scalar_one_or_none.return_value = membership
        side_effects.append(m_result)

    # 3. name 查重查询（get_gene_by_name_in_scope 用 .scalars().first()，
    # 与其它步骤的 .scalar_one_or_none() 链路不同，需要单独 mock）
    name_result = MagicMock()
    name_result.scalars.return_value.first.return_value = (
        MagicMock() if has_name_conflict else None
    )
    side_effects.append(name_result)

    # 4. slug 冲突查询
    conflict_result = MagicMock()
    conflict_result.scalar_one_or_none.return_value = MagicMock() if has_slug_conflict else None
    side_effects.append(conflict_result)

    db.execute = AsyncMock(side_effect=side_effects)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db
```

- [ ] **Step 2: 追加失败的测试**

在 `tests/test_gene_target_fork_review.py` 末尾（文件最后一个测试函数之后）追加：

```python
@pytest.mark.asyncio
async def test_fork_rejects_when_target_scope_has_same_name():
    """目标 scope 已存在同名技能：直接 ConflictError，不再自动改名绕开。"""
    source = _FakeGene(
        gene_id="g-personal",
        org_id=None,
        created_by="owner-id",
        visibility="personal",
        review_status=None,
        slug="my-skill",
        name="客服助手",
    )
    db = _make_fork_db(source, has_name_conflict=True)
    user = _FakeUser("owner-id", current_org_id="org-target")

    with pytest.raises(ConflictError):
        await gene_service.fork_gene_to_library(
            db, "my-skill", "org", current_user=user,
        )


@pytest.mark.asyncio
async def test_fork_allows_when_target_scope_has_no_same_name():
    """目标 scope 没有同名技能：正常 fork 成功（沿用已有的 slug 自动改名兜底）。"""
    source = _FakeGene(
        gene_id="g-personal",
        org_id=None,
        created_by="owner-id",
        visibility="personal",
        review_status=None,
        slug="my-skill",
        name="客服助手",
    )
    db = _make_fork_db(source, has_name_conflict=False, has_slug_conflict=True)
    user = _FakeUser("owner-id", current_org_id="org-target")

    result = await gene_service.fork_gene_to_library(
        db, "my-skill", "org", current_user=user,
    )
    assert result["name"] == "客服助手"
    assert result["slug"] != "my-skill"  # slug 冲突时仍走自动加后缀
```

`_FakeGene.__init__`（`tests/test_gene_target_fork_review.py:132-151`）目前没有 `name` 构造参数，`self.name` 是由 `slug` 自动派生的（`self.name = f"name-{slug}"`），上面两个新测试传了 `name="客服助手"` 会报 `unexpected keyword argument`，需要在下一步一并修正。

- [ ] **Step 3: 给 `_FakeGene` 加 `name` 构造参数**

把 `tests/test_gene_target_fork_review.py:132-151` 的：

```python
class _FakeGene:
    def __init__(
        self,
        gene_id: str = "g-1",
        org_id: str | None = "org-1",
        review_status: str = GeneReviewStatus.pending_owner,
        visibility: str = "org_private",
        created_by: str | None = "uploader",
        slug: str = "skill-x",
    ):
        self.id = gene_id
        self.org_id = org_id
        self.review_status = review_status
        self.visibility = visibility
        self.is_published = False
        self.created_by_instance_id = None
        self.created_by = created_by
        # fork 函数会读取一组 source_* 字段并复制
        self.slug = slug
        self.name = f"name-{slug}"
```

改为（新增 `name` 参数，不传时保持原有的自动派生行为，不影响其它已有测试）：

```python
class _FakeGene:
    def __init__(
        self,
        gene_id: str = "g-1",
        org_id: str | None = "org-1",
        review_status: str = GeneReviewStatus.pending_owner,
        visibility: str = "org_private",
        created_by: str | None = "uploader",
        slug: str = "skill-x",
        name: str | None = None,
    ):
        self.id = gene_id
        self.org_id = org_id
        self.review_status = review_status
        self.visibility = visibility
        self.is_published = False
        self.created_by_instance_id = None
        self.created_by = created_by
        # fork 函数会读取一组 source_* 字段并复制
        self.slug = slug
        self.name = name or f"name-{slug}"
```

- [ ] **Step 4: 运行测试确认失败**

Run:
```bash
wsl -e bash -lc "cd /mnt/c/Users/gg102/my_project/nodeskclaw/nodeskclaw-backend && uv run pytest tests/test_gene_target_fork_review.py -v"
```
Expected: 新增的 2 个测试 FAIL（`fork_gene_to_library` 还没有做 name 查重）；此前所有测试应仍然 PASS（因为 `has_name_conflict` 默认 False，新插入的 mock 结果对现有测试透明）

- [ ] **Step 5: 修改 `fork_gene_to_library()` 接入 name 查重**

在 `app/services/gene_service.py:3520` 之后（`source_parent_id = None  # 外部源没有本地 id 可指` 这一行之后）、`# ── 3. 计算副本 slug：在目标 org_id 内重名时追加短后缀 ──────────`（第 3522 行）之前，插入：

```python
    # ── 2.5. 名称查重：目标 scope 内已存在同名技能则直接拒绝 ──────────
    # 与"防止重名出现"的需求本身矛盾，所以这里不像 slug 那样自动加后缀绕开，
    # 而是直接报错让用户自己决定改名或删除旧的。
    existing_name = await get_gene_by_name_in_scope(
        db, source_name,
        visibility=attrs["visibility"],
        org_id=attrs["org_id"],
        created_by=attrs["created_by"],
    )
    if existing_name is not None:
        raise ConflictError(f"技能名称 '{source_name}' 已存在")

```

- [ ] **Step 6: 运行测试确认通过**

Run:
```bash
wsl -e bash -lc "cd /mnt/c/Users/gg102/my_project/nodeskclaw/nodeskclaw-backend && uv run pytest tests/test_gene_target_fork_review.py -v"
```
Expected: 全部 PASS

- [ ] **Step 7: Commit**

```bash
git add nodeskclaw-backend/app/services/gene_service.py nodeskclaw-backend/tests/test_gene_target_fork_review.py
git commit -m "$(cat <<'EOF'
feat(backend): fork_gene_to_library 接入技能名称查重

从公共市场/组织/个人 fork 到目标 scope 时，若目标 scope 已存在同名
技能直接 409 ConflictError，不再沿用"slug 冲突自动加后缀"来绕开
重名（与查重需求本身矛盾）。slug 自动改名逻辑保留作为 slug 层面
的兜底。
EOF
)"
```

---

### Task 5: 全量回归测试

**Files:** 无新增/修改文件，仅验证

- [ ] **Step 1: 跑全部 gene 相关测试**

Run:
```bash
wsl -e bash -lc "cd /mnt/c/Users/gg102/my_project/nodeskclaw/nodeskclaw-backend && uv run pytest tests/ -k gene -v"
```
Expected: 全部 PASS，无 ERROR

- [ ] **Step 2: 跑全量后端测试套件确认无跨模块回归**

Run:
```bash
wsl -e bash -lc "cd /mnt/c/Users/gg102/my_project/nodeskclaw/nodeskclaw-backend && uv run pytest -v"
```
Expected: 全部 PASS（若有既存的、与本次改动无关的 flaky/skip 测试，记录下来但不需要本次修复）

- [ ] **Step 3: `ruff check` 静态检查**

Run:
```bash
wsl -e bash -lc "cd /mnt/c/Users/gg102/my_project/nodeskclaw/nodeskclaw-backend && uv run ruff check app/models/gene.py app/services/gene_service.py tests/test_gene_name_dedup.py tests/test_gene_target_fork_review.py"
```
Expected: 无报错

---

### Task 6: 补齐遗漏入口 + 修复覆盖误删（Task 5 整体 review 发现）

**Files:** `nodeskclaw-backend/app/services/gene_service.py`, `nodeskclaw-backend/tests/test_gene_name_dedup.py`

背景：Task 5 后对整个分支做了一次跨任务整体 review，发现 3 处遗漏：

- [x] **Step 1（Critical）：`publish_variant` 接入名称查重 + IntegrityError 兜底**

`publish_variant`（`gene_service.py:2178`）里 `Gene(...)` 插入未显式传 `visibility`，落在默认的 `public` scope。在 `variant = Gene(...)` 之前，对 `name` 做 `get_gene_by_name_in_scope(db, name, visibility=ContentVisibility.public)` 查重，命中则 `raise ConflictError(f"技能名称 '{name}' 已存在")`；`await db.commit()`（约第 2250 行）包 `try/except IntegrityError`，转 `ConflictError`，模式与 `create_gene()` 第 788-794 行一致。

- [x] **Step 2（Critical）：`handle_creation_callback` 接入名称查重 + IntegrityError 兜底**

`handle_creation_callback`（`gene_service.py:2306`）同样默认落 `public` scope。在 `gene = Gene(...)` 之前对 `meta.get("gene_name", ...)` 算出的最终 name 做同样查重+拒绝；`await db.commit()`（约第 2350 行）同样包 `try/except IntegrityError`。

- [x] **Step 3（Important）：修复 `create_gene` overwrite 分支误删无关行**

`gene_service.py:747-755`：当前 `existing`（按 slug 命中）和 `existing_name`（按 name 命中）为两条不同行时，`overwrite=True` 会把两条都软删——设计文档原意只是"跳过检查、复用 slug 覆盖逻辑"，不是主动删除一条不相关的记录。改为：`overwrite=True` 且 `existing_name is not None and existing_name is not existing` 时，仍然 `raise ConflictError`（覆盖的是 slug 命中的那条，不能顺带覆盖掉一条名字撞车但完全无关的记录）。

实现细节偏差（评审确认可接受）：这条检查落地时写成了对 `existing_name is not existing` 的无条件早退（不再嵌在 `if req.overwrite:` 分支内）。影响仅限一个未被计划文字覆盖、也未被测试覆盖的边界场景——`overwrite=False` 且 slug 命中行 A、name 命中另一条无关行 B 时，报错文案从"slug 已存在"变成"名称已存在"，两者都是 `ConflictError`，请求仍会被拒绝，无功能性影响。

- [x] **Step 4（Important）：`fork_gene_to_library` 补 IntegrityError 兜底**

`gene_service.py:3627` 附近的 `await db.commit()` 包 `try/except IntegrityError`，转 `ConflictError`，与 Task 2.5 的预检查搭配形成完整防护，模式对齐 `create_gene()`。

- [x] **Step 5：补测试**

`tests/test_gene_name_dedup.py` 新增：
  - `test_publish_variant_rejects_duplicate_name_in_public_scope`
  - `test_creation_callback_rejects_duplicate_name_in_public_scope`
  - `test_create_gene_overwrite_rejects_when_name_hits_unrelated_row`（slug 命中行 A，name 命中另一行 B，overwrite=True 时应 ConflictError 且 B 不被软删）
  - `test_publish_variant_integrity_error_on_commit_becomes_conflict_error`（补充：code-quality review 发现 Step 1/2/4 新增的 IntegrityError 兜底分支本身完全没有测试覆盖，补一个 monkeypatch db.commit 的竞态测试，模式对齐 `create_gene` 已有的同类测试）

验证过程中发现并修复一处测试自身的 bug：`test_publish_variant_rejects_duplicate_name_in_public_scope` 里构造的 `parent` Gene 用了硬编码的 `name="原始助手"`（public scope 全局唯一），在被中断的历史测试进程留下脏数据、或与本次新增的竞态测试并行跑时会撞车报错。已改为 `f"原始助手-{_uid('n')}"` 随机化，两处硬编码同步修复。

- [x] **Step 6：跑测试 + `ruff check`，确认无回归**

`ruff check` 两个改动文件全部通过；4 个新增/修改测试逐一单独运行全部 PASSED；`test_gene_target_fork_review.py` 32/32 通过。批量跑 `test_gene_name_dedup.py` 全部用例时仍会触发 Task 5 已记录的、与本分支无关的 pytest-asyncio 双引擎事件循环 flaky（`attached to a different loop`），已在 Task 5 验证过在无关的既存文件上同样复现，不属于本次改动引入的问题。

- [x] **Step 7：commit**

`fix(backend): 补齐 Gene 名称查重遗漏入口，修复 overwrite 误删无关行`

---

### Task 6 补充修复：overwrite 误判"无关行"导致合法覆盖被拒绝（用户线上反馈）

**背景**：Task 6 commit（`6c6e82b`）落地后，用户反馈"点击同意覆盖后，仍然提示同名 skill 已存在，拒绝上传"——原本"检测到同名 → 提示是否覆盖 → 同意后带 `overwrite=true` 重新上传"的交互彻底失效。

**根因**：Step 3 加的无条件早退检查 `if existing_name is not None and existing_name is not existing: raise ConflictError(...)` 漏判了一种合法场景——`existing`（按 slug 命中）为 `None`、仅 `existing_name`（按 name 命中）非空。这在真实场景里很常见：`/genes/upload-folder` 的 slug 是按名称确定性生成的（`_slugify_gene_name`），但若旧记录是通过别的入口（如手动创建、slug 自定义）生成的、slug 规则不同，重新上传覆盖时 slug 查不到旧行，只有 name 能精确命中——这条 `existing_name` 就是唯一需要覆盖的目标，不是"无关行"。旧检查不区分"existing 为 None"和"existing 非 None 但指向不同行"，一律拒绝，导致合法覆盖也被挡下。

**修复**（`gene_service.py:747-763`）：
- 无关行拒绝条件补上 `existing is not None` 前置：只有 slug 和 name 分别命中两条**不同**且**都存在**的行时才是真正冲突，需要拒绝
- overwrite 分支软删目标从 `existing`（可能是 None）改为 `existing or existing_name`，恢复"existing 为 None 时软删 existing_name"的原有正确行为

**测试**：新增 `test_create_gene_overwrite_succeeds_when_only_name_hits_no_slug_match`（复现用户反馈场景：旧记录 slug 由手动创建生成，重新上传按名称生成的 slug 对不上，overwrite=True 应成功覆盖），验证前先确认该测试在修复前会失败（复现根因），修复后转绿；`test_create_gene_overwrite_rejects_when_name_hits_unrelated_row`（原有的真无关行拒绝场景）和 `test_create_gene_overwrite_allows_same_name`（slug/name 命中同一行）逐一单独验证仍然通过，确认修复没有削弱原有的误删防护。

**commit**：`fix(backend): 修复 overwrite 误判无关行导致合法覆盖被拒绝`

---

## 涉及文件总览

| 文件 | 改动类型 |
|---|---|
| `nodeskclaw-backend/app/models/gene.py` | 新增 3 条 partial unique index |
| `nodeskclaw-backend/alembic/versions/<new>.py` | 新增 migration |
| `nodeskclaw-backend/app/services/gene_service.py` | 新增 `get_gene_by_name_in_scope`；`create_gene()`/`fork_gene_to_library()` 接入查重 |
| `nodeskclaw-backend/tests/test_gene_name_dedup.py`（新建） | create_gene + get_gene_by_name_in_scope 的真实 DB 测试 |
| `nodeskclaw-backend/tests/test_gene_target_fork_review.py` | `_make_fork_db` 补 name 查重 mock；新增 2 个 fork 查重测试 |

## 不在范围内（同设计文档）

- 不改动 `name` 字段类型/长度约束本身
- 不做模糊/编辑距离查重，只做 trim+忽略大小写精确匹配
- 不处理迁移前存量重名数据（发现即报告，不自动处理）
- 不改动现有 slug 唯一性保护的实现方式
