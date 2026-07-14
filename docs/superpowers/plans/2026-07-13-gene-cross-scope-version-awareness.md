# Gene 跨 Scope 版本感知 Implementation Plan (v2，对齐设计文档 v6)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户能感知到个人库相较于组织库/公共市场（同一血缘）是否有更新版本；组织库/公共市场内容只能通过 fork 进入并可被审核后的 fork 覆盖同步。

**Architecture:** 新增 `Gene.lineage_group_id` 标记"同一血缘的三向副本"，复用 `Gene.version` 做语义化版本比较；`/genes/upload-folder`、`/genes/manual` 收紧为只接受 `target=personal`；`fork_gene_to_library()` 新增 `overwrite` 支持，personal 目标立即执行、org/public 目标写入新表 `gene_overwrite_submissions` 暂存，管理员审核通过才真正生效；版本落后检测只在个人库一侧计算（单向）。

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + Alembic（后端），Vue 3 + Pinia + TypeScript（前端）。

**规范来源：** `docs/superpowers/specs/2026-07-13-gene-cross-scope-version-awareness-design.md`（v6，已批准；文档顶部"已知架构局限"一节记录了本设计接受的过渡性局限，实现时不需要处理，已跟踪为 Task #14 独立重构）

---

## 涉及文件总览

| 文件 | 类型 | 职责 |
|---|---|---|
| `nodeskclaw-backend/app/core/version_compare.py` | 新建 | 语义化版本号解析 + 比较（Python） |
| `nodeskclaw-backend/tests/test_version_compare.py` | 新建 | 上面这个工具的单测 |
| `nodeskclaw-backend/app/models/gene.py` | 修改 | `Gene` 新增 `lineage_group_id` 字段 + 索引 |
| `nodeskclaw-backend/app/models/gene_overwrite_submission.py` | 新建 | `GeneOverwriteSubmission` 模型 |
| `nodeskclaw-backend/app/models/__init__.py` | 修改 | 注册新模型 |
| `nodeskclaw-backend/alembic/versions/<hash>_add_gene_lineage_and_overwrite_submission.py` | 新建 | 迁移：加列 + 并查集回填 + 建新表 |
| `nodeskclaw-backend/app/schemas/gene.py` | 修改 | `ForkGeneRequest` 新增 `overwrite`；新增 `GeneOverwriteSubmissionReview` 请求体 |
| `nodeskclaw-backend/app/services/gene_service.py` | 修改 | 核心逻辑：见下方各任务 |
| `nodeskclaw-backend/app/api/genes.py` | 修改 | 上传入口收紧 `target`；fork 接口透传 `overwrite`；新增覆盖提交审核接口；待审核列表合并 |
| `nodeskclaw-backend/tests/test_gene_lineage_version_awareness.py` | 新建 | 血缘传播 + 落后检测测试 |
| `nodeskclaw-backend/tests/test_gene_overwrite_submission_review.py` | 新建 | 覆盖审核暂存的提交/批准/拒绝/过期竞态测试 |
| `nodeskclaw-backend/tests/test_gene_upload_target_restriction.py` | 新建 | 上传目标收敛测试 |
| `nodeskclaw-portal/src/utils/semver.ts` | 新建 | 语义化版本号解析 + 比较 + 建议下一版本号（TypeScript） |
| `nodeskclaw-portal/src/utils/semver.spec.ts` | 新建 | 上面这个工具的单测 |
| `nodeskclaw-portal/src/services/skills.ts` | 修改 | `uploadFolder` 新增 `version` 参数 |
| `nodeskclaw-portal/src/stores/gene.ts` | 修改 | `forkGene` 新增 `overwrite` 参数；`GeneItem` 新增 `newer_sibling_versions` 字段 |
| `nodeskclaw-portal/src/views/GeneMarket.vue` | 修改 | 上传目标选择器移除 org/public；覆盖弹窗加版本号输入；fork 覆盖交互；个人库卡片角标 |

---

## Phase 1：基础设施（版本号比较工具 + 数据模型）

### Task 1: 后端语义化版本号比较工具

**Files:**
- Create: `nodeskclaw-backend/app/core/version_compare.py`
- Test: `nodeskclaw-backend/tests/test_version_compare.py`

- [ ] **Step 1: 写失败的测试**

```python
"""tests/test_version_compare.py"""
from app.core.version_compare import compare_versions, parse_version


def test_parse_version_valid():
    assert parse_version("1.10.2") == (1, 10, 2)


def test_parse_version_invalid_formats():
    assert parse_version("latest") is None
    assert parse_version("v1.0.0") is None
    assert parse_version("1.0") is None


def test_compare_versions_numeric_not_lexicographic():
    assert compare_versions("1.10.0", "1.9.0") == 1
    assert compare_versions("1.9.0", "1.10.0") == -1


def test_compare_versions_equal():
    assert compare_versions("1.0.0", "1.0.0") == 0


def test_compare_versions_invalid_returns_none():
    assert compare_versions("bad", "1.0.0") is None
    assert compare_versions("1.0.0", "bad") is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd nodeskclaw-backend && uv run pytest tests/test_version_compare.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.core.version_compare'`

- [ ] **Step 3: 实现**

```python
"""nodeskclaw-backend/app/core/version_compare.py

语义化版本号解析与比较工具。只识别 "X.Y.Z" 前缀（X/Y/Z 为非负整数），
不支持 pre-release/build metadata 后缀，够用即可。
"""

from __future__ import annotations

import re

_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def parse_version(version: str) -> tuple[int, int, int] | None:
    """解析 "X.Y.Z" 版本号为 (major, minor, patch) 整数元组。

    不合法格式返回 None，调用方自行决定降级策略：写入路径应该直接拒绝，
    读取路径应该跳过比较，不能装作知道谁新谁旧。
    """
    match = _SEMVER_RE.match(version.strip())
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def compare_versions(a: str, b: str) -> int | None:
    """比较两个版本号。a 更新返回 1，b 更新返回 -1，相等返回 0；

    任一个解析失败返回 None（调用方不能把 None 当成"相等"处理）。
    """
    parsed_a = parse_version(a)
    parsed_b = parse_version(b)
    if parsed_a is None or parsed_b is None:
        return None
    if parsed_a == parsed_b:
        return 0
    return 1 if parsed_a > parsed_b else -1
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd nodeskclaw-backend && uv run pytest tests/test_version_compare.py -v`
Expected: 5 passed

- [ ] **Step 5: ruff check + Commit**

```bash
cd nodeskclaw-backend && uv run ruff check app/core/version_compare.py tests/test_version_compare.py
git add nodeskclaw-backend/app/core/version_compare.py nodeskclaw-backend/tests/test_version_compare.py
git commit -m "feat(backend): 新增语义化版本号比较工具"
```

---

### Task 2: 前端语义化版本号比较工具

**Files:**
- Create: `nodeskclaw-portal/src/utils/semver.ts`
- Test: `nodeskclaw-portal/src/utils/semver.spec.ts`

- [ ] **Step 1: 写失败的测试**

```typescript
// nodeskclaw-portal/src/utils/semver.spec.ts
import { describe, it, expect } from 'vitest'
import { parseVersion, compareVersions, suggestNextPatch } from './semver'

describe('semver', () => {
  it('parses a valid X.Y.Z version', () => {
    expect(parseVersion('1.10.2')).toEqual([1, 10, 2])
  })

  it('returns null for invalid formats', () => {
    expect(parseVersion('latest')).toBeNull()
    expect(parseVersion('v1.0.0')).toBeNull()
    expect(parseVersion('1.0')).toBeNull()
  })

  it('compares numerically, not lexicographically', () => {
    expect(compareVersions('1.10.0', '1.9.0')).toBe(1)
    expect(compareVersions('1.9.0', '1.10.0')).toBe(-1)
  })

  it('treats equal versions as 0', () => {
    expect(compareVersions('1.0.0', '1.0.0')).toBe(0)
  })

  it('returns null when either version is invalid', () => {
    expect(compareVersions('bad', '1.0.0')).toBeNull()
    expect(compareVersions('1.0.0', 'bad')).toBeNull()
  })

  it('suggests the next patch version', () => {
    expect(suggestNextPatch('1.0.0')).toBe('1.0.1')
    expect(suggestNextPatch('2.3.9')).toBe('2.3.10')
  })

  it('suggestNextPatch falls back to the input when unparseable', () => {
    expect(suggestNextPatch('latest')).toBe('latest')
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd nodeskclaw-portal && node node_modules/vitest/vitest.mjs run src/utils/semver.spec.ts`
Expected: FAIL，找不到模块 `./semver`

- [ ] **Step 3: 实现**

```typescript
// nodeskclaw-portal/src/utils/semver.ts
/**
 * 语义化版本号解析与比较工具，只认 "X.Y.Z" 格式，逻辑跟后端
 * app/core/version_compare.py 保持一致。
 */

const SEMVER_RE = /^(\d+)\.(\d+)\.(\d+)$/

export function parseVersion(version: string): [number, number, number] | null {
  const match = SEMVER_RE.exec(version.trim())
  if (!match) return null
  return [Number(match[1]), Number(match[2]), Number(match[3])]
}

export function compareVersions(a: string, b: string): number | null {
  const parsedA = parseVersion(a)
  const parsedB = parseVersion(b)
  if (!parsedA || !parsedB) return null
  for (let i = 0; i < 3; i++) {
    if (parsedA[i] !== parsedB[i]) return parsedA[i] > parsedB[i] ? 1 : -1
  }
  return 0
}

/** 在当前版本号基础上建议下一个 patch 版本，解析失败时原样返回，不瞎猜。 */
export function suggestNextPatch(version: string): string {
  const parsed = parseVersion(version)
  if (!parsed) return version
  const [major, minor, patch] = parsed
  return `${major}.${minor}.${patch + 1}`
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd nodeskclaw-portal && node node_modules/vitest/vitest.mjs run src/utils/semver.spec.ts`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add nodeskclaw-portal/src/utils/semver.ts nodeskclaw-portal/src/utils/semver.spec.ts
git commit -m "feat(portal): 新增语义化版本号比较工具"
```

---

### Task 3: Gene 模型新增 `lineage_group_id` 字段

**Files:**
- Modify: `nodeskclaw-backend/app/models/gene.py`

- [ ] **Step 1: 在 `Gene` 类里加字段**

在 `nodeskclaw-backend/app/models/gene.py` 的 `Gene` 类里，找到 `parent_gene_id` 字段定义（约第 126-128 行）：

```python
    parent_gene_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("genes.id"), nullable=True
    )
```

在它后面新增：

```python
    # 血缘分组 key：同一血缘下的 personal/org/public 三向副本共享同一个值，
    # 不是外键、不要求指向一条现存活的行，只是一个不透明的分组标识。
    # 由 create_gene()/fork_gene_to_library() 在创建时传播（见 gene_service.py），
    # 历史数据由迁移脚本按 parent_gene_id 连通分量回填。
    lineage_group_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True,
    )
```

- [ ] **Step 2: 确认没有语法错误**

Run: `cd nodeskclaw-backend && uv run python -c "from app.models.gene import Gene; print(Gene.__table__.c.lineage_group_id)"`
Expected: 输出 `genes.lineage_group_id`，无报错

- [ ] **Step 3: Commit**

```bash
git add nodeskclaw-backend/app/models/gene.py
git commit -m "feat(backend): Gene 模型新增 lineage_group_id 字段"
```

---

### Task 4: 新建 `GeneOverwriteSubmission` 模型

**Files:**
- Create: `nodeskclaw-backend/app/models/gene_overwrite_submission.py`
- Modify: `nodeskclaw-backend/app/models/__init__.py`

- [ ] **Step 1: 查看 `app/models/__init__.py` 里现有模型的注册模式**

Run: `grep -n "from app.models" nodeskclaw-backend/app/models/__init__.py | tail -5`

确认现有模型（如 `org_required_gene.py` 的 `OrgRequiredGene`）的导入写法，新模型按同样模式加进去。

- [ ] **Step 2: 创建模型文件**

```python
"""nodeskclaw-backend/app/models/gene_overwrite_submission.py

Fork 覆盖 org/public scope 时的审核暂存记录。genes 表的 partial unique
index（uq_genes_name_org_active / uq_genes_slug_org_active）语义是"同一
scope 内任意时刻只能有一条未软删的同名/同 slug 记录"，不区分审核状态——
如果不软删旧行就先插入一条同名的 pending 新行，会直接撞上这两条唯一索引。
所以待审核的覆盖内容放在这张独立的表里，不占用 genes 表的唯一索引位置，
approve 时才把内容真正搬进 genes 表（同时软删旧行）。
"""

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class GeneOverwriteSubmission(BaseModel):
    __tablename__ = "gene_overwrite_submissions"
    __table_args__ = (
        Index("ix_gene_overwrite_submissions_target_gene_id", "target_gene_id"),
        Index("ix_gene_overwrite_submissions_review_status", "review_status"),
    )

    # 本次提交打算替换掉的那一条 Gene.id（也就是 fork_gene_to_library 里的
    # existing_name）。approve 时会把这一行软删。
    target_gene_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("genes.id"), nullable=False,
    )
    # fork 源头 gene 的 id；本地来源时有值，外部聚合器来源时为空
    source_gene_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("genes.id"), nullable=True,
    )
    # 继承自 source，approve 时原样赋给新插入的 Gene 行
    lineage_group_id: Mapped[str] = mapped_column(String(36), nullable=False)

    # 以下字段是本次提交要写入的完整内容快照，approve 时原样搬进新的 Gene 行，
    # 字段类型跟 Gene 对应字段保持一致
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    short_description: Mapped[str | None] = mapped_column(String(256), nullable=True)
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(32), nullable=True)
    version: Mapped[str] = mapped_column(String(16), nullable=False)
    manifest: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    dependencies: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array
    synergies: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array

    # 目标归属（resolve_target_attrs 算出来的）
    visibility: Mapped[str] = mapped_column(String(16), nullable=False)
    org_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=True,
    )
    created_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True,
    )

    # 复用 GeneReviewStatus 的字符串值：pending_owner -> approved/rejected
    review_status: Mapped[str] = mapped_column(String(16), nullable=False)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 没有 is_published 字段——这张表里的记录永远代表"还没生效的提议"，
    # approve 之后内容被搬进 genes 表，is_published 才有意义。
```

- [ ] **Step 3: 注册到 `app/models/__init__.py`**

按 Step 1 看到的模式，加一行（放在其他 gene 相关模型附近）：

```python
from app.models.gene_overwrite_submission import GeneOverwriteSubmission  # noqa: F401
```

- [ ] **Step 4: 确认没有语法错误**

Run: `cd nodeskclaw-backend && uv run python -c "from app.models.gene_overwrite_submission import GeneOverwriteSubmission; print(GeneOverwriteSubmission.__tablename__)"`
Expected: 输出 `gene_overwrite_submissions`，无报错

- [ ] **Step 5: Commit**

```bash
git add nodeskclaw-backend/app/models/gene_overwrite_submission.py nodeskclaw-backend/app/models/__init__.py
git commit -m "feat(backend): 新增 GeneOverwriteSubmission 模型"
```

---

### Task 5: Alembic 迁移 —— `lineage_group_id` 回填 + 建新表

**Files:**
- Create: `nodeskclaw-backend/alembic/versions/<hash>_add_gene_lineage_and_overwrite_submission.py`

- [ ] **Step 1: 生成迁移骨架（禁止手写 revision ID）**

Run: `cd nodeskclaw-backend && uv run alembic revision -m "add gene lineage group id and overwrite submission"`

记下命令输出的文件路径和自动生成的 `revision`/`down_revision` 值。

- [ ] **Step 2: 写迁移内容**

打开上一步生成的文件，把内容替换成（保留自动生成的 `revision`/`down_revision`/`branch_labels`/`depends_on`）：

```python
"""add gene lineage group id and overwrite submission

Revision ID: <保留自动生成的值>
Revises: <保留自动生成的值>
Create Date: <保留自动生成的值>
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import table, column, String

revision = "<保留自动生成的值>"
down_revision = "<保留自动生成的值>"
branch_labels = None
depends_on = None


def _find(parent: dict[str, str], x: str) -> str:
    root = x
    while parent[root] != root:
        root = parent[root]
    while parent[x] != root:
        parent[x], x = root, parent[x]
    return root


def _union(parent: dict[str, str], a: str, b: str) -> None:
    ra, rb = _find(parent, a), _find(parent, b)
    if ra == rb:
        return
    if ra < rb:
        parent[rb] = ra
    else:
        parent[ra] = rb


def upgrade() -> None:
    # ── 1. lineage_group_id：加列 + 并查集回填 ──────────────────────────
    op.add_column("genes", sa.Column("lineage_group_id", sa.String(36), nullable=True))
    op.create_index("ix_genes_lineage_group_id", "genes", ["lineage_group_id"])

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, parent_gene_id FROM genes")).fetchall()

    parent: dict[str, str] = {}
    for row in rows:
        parent.setdefault(row.id, row.id)
        if row.parent_gene_id:
            parent.setdefault(row.parent_gene_id, row.parent_gene_id)
            _union(parent, row.id, row.parent_gene_id)

    group_members: dict[str, list[str]] = {}
    for row in rows:
        root = _find(parent, row.id)
        group_members.setdefault(root, []).append(row.id)

    genes_table = table("genes", column("id", sa.String), column("lineage_group_id", sa.String))
    for root, members in group_members.items():
        conn.execute(
            genes_table.update().where(genes_table.c.id.in_(members)).values(lineage_group_id=root)
        )

    op.alter_column("genes", "lineage_group_id", nullable=False)

    # ── 2. gene_overwrite_submissions 新表 ───────────────────────────────
    op.create_table(
        "gene_overwrite_submissions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("target_gene_id", sa.String(36), sa.ForeignKey("genes.id"), nullable=False),
        sa.Column("source_gene_id", sa.String(36), sa.ForeignKey("genes.id"), nullable=True),
        sa.Column("lineage_group_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("short_description", sa.String(256), nullable=True),
        sa.Column("category", sa.String(32), nullable=True),
        sa.Column("tags", sa.Text(), nullable=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("source_ref", sa.String(512), nullable=True),
        sa.Column("icon", sa.String(32), nullable=True),
        sa.Column("version", sa.String(16), nullable=False),
        sa.Column("manifest", sa.Text(), nullable=True),
        sa.Column("dependencies", sa.Text(), nullable=True),
        sa.Column("synergies", sa.Text(), nullable=True),
        sa.Column("visibility", sa.String(16), nullable=False),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("review_status", sa.String(16), nullable=False),
        sa.Column("reject_reason", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_gene_overwrite_submissions_target_gene_id",
        "gene_overwrite_submissions", ["target_gene_id"],
    )
    op.create_index(
        "ix_gene_overwrite_submissions_review_status",
        "gene_overwrite_submissions", ["review_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_gene_overwrite_submissions_review_status", table_name="gene_overwrite_submissions")
    op.drop_index("ix_gene_overwrite_submissions_target_gene_id", table_name="gene_overwrite_submissions")
    op.drop_table("gene_overwrite_submissions")
    op.drop_index("ix_genes_lineage_group_id", table_name="genes")
    op.drop_column("genes", "lineage_group_id")
```

- [ ] **Step 3: 本地库跑一遍迁移，确认能升级也能降级**

Run（需要本地 Postgres 已启动，参考 `docker start nodeskclaw-postgres`）：
```bash
cd nodeskclaw-backend && uv run alembic upgrade head
```
Expected: 无报错，`genes` 表出现 `lineage_group_id` 列（`NOT NULL`），`gene_overwrite_submissions` 表存在

Run: `uv run alembic downgrade -1 && uv run alembic upgrade head`
Expected: 降级、再升级都无报错

- [ ] **Step 4: 补一个并查集回填正确性测试**

```python
"""nodeskclaw-backend/tests/test_gene_lineage_migration_backfill.py

验证并查集回填逻辑本身（不依赖 alembic 运行时，直接测试同样的算法），
覆盖链式 fork、多分支 fork、孤立节点三种历史数据形状。
"""
from __future__ import annotations


def _find(parent: dict[str, str], x: str) -> str:
    root = x
    while parent[root] != root:
        root = parent[root]
    while parent[x] != root:
        parent[x], x = root, parent[x]
    return root


def _union(parent: dict[str, str], a: str, b: str) -> None:
    ra, rb = _find(parent, a), _find(parent, b)
    if ra == rb:
        return
    if ra < rb:
        parent[rb] = ra
    else:
        parent[ra] = rb


def _compute_groups(rows: list[tuple[str, str | None]]) -> dict[str, str]:
    parent: dict[str, str] = {}
    for gene_id, parent_gene_id in rows:
        parent.setdefault(gene_id, gene_id)
        if parent_gene_id:
            parent.setdefault(parent_gene_id, parent_gene_id)
            _union(parent, gene_id, parent_gene_id)
    return {gene_id: _find(parent, gene_id) for gene_id, _ in rows}


def test_chain_fork_all_in_one_group():
    rows = [("A", None), ("B", "A"), ("C", "B")]
    groups = _compute_groups(rows)
    assert groups["A"] == groups["B"] == groups["C"]


def test_multi_branch_fork_all_in_one_group():
    rows = [("P", None), ("OrgA", "P"), ("OrgB", "P")]
    groups = _compute_groups(rows)
    assert groups["OrgA"] == groups["P"]
    assert groups["OrgB"] == groups["P"]


def test_isolated_node_gets_own_group():
    rows = [("Standalone", None)]
    groups = _compute_groups(rows)
    assert groups["Standalone"] == "Standalone"


def test_two_unrelated_lineages_stay_separate():
    rows = [("A", None), ("B", "A"), ("X", None), ("Y", "X")]
    groups = _compute_groups(rows)
    assert groups["A"] == groups["B"]
    assert groups["X"] == groups["Y"]
    assert groups["A"] != groups["X"]
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd nodeskclaw-backend && uv run pytest tests/test_gene_lineage_migration_backfill.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add nodeskclaw-backend/alembic/versions/*_add_gene_lineage_and_overwrite_submission.py nodeskclaw-backend/tests/test_gene_lineage_migration_backfill.py
git commit -m "feat(backend): 新增 lineage_group_id 回填与 gene_overwrite_submissions 表迁移"
```

---

## Phase 2：上传目标收敛

### Task 6: `/genes/upload-folder`、`/genes/manual` 只接受 `target=personal`

**Files:**
- Modify: `nodeskclaw-backend/app/api/genes.py`（`upload_gene_folder`、`create_manual_gene`）

- [ ] **Step 1: 写失败的测试**

```python
"""nodeskclaw-backend/tests/test_gene_upload_target_restriction.py

验证直接上传入口只接受 target=personal，org/public（含管理员/超管）一律拒绝。
用 httpx AsyncClient 走真实路由，跟项目里其他 API 层测试的风格一致。
"""
from __future__ import annotations

import io

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_upload_folder_rejects_org_target(monkeypatch):
    from app.core.deps import get_current_user

    class _FakeUser:
        id = "u1"
        current_org_id = "org1"
        is_super_admin = False

    app.dependency_overrides[get_current_user] = lambda: _FakeUser()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            files = {"files": ("SKILL.md", io.BytesIO(b"# skill\ncontent"), "text/markdown")}
            resp = await client.post("/api/v1/genes/upload-folder?target=org", files=files)
            assert resp.status_code == 400
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_upload_folder_rejects_org_target_even_for_super_admin(monkeypatch):
    from app.core.deps import get_current_user

    class _FakeSuperAdmin:
        id = "admin1"
        current_org_id = "org1"
        is_super_admin = True

    app.dependency_overrides[get_current_user] = lambda: _FakeSuperAdmin()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            files = {"files": ("SKILL.md", io.BytesIO(b"# skill\ncontent"), "text/markdown")}
            resp = await client.post("/api/v1/genes/upload-folder?target=public", files=files)
            assert resp.status_code == 400
    finally:
        app.dependency_overrides.pop(get_current_user, None)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd nodeskclaw-backend && uv run pytest tests/test_gene_upload_target_restriction.py -v`
Expected: FAIL（目前 `target=org`/`target=public` 会被正常接受，不会返回 400）

- [ ] **Step 3: 修改 `upload_gene_folder`**

在 `nodeskclaw-backend/app/api/genes.py` 的 `upload_gene_folder` 函数体最前面（`if target != "personal" and not current_user.current_org_id:` 那一行之前），加一段校验：

```python
    if target != "personal":
        raise BadRequestError(
            "直接上传只能进入个人库，组织库/公共市场的内容请先上传到个人库、"
            "再通过 fork 覆盖同步过去",
            message_key="errors.gene.upload_target_must_be_personal",
        )
```

删掉原来紧跟着的 `if target != "personal" and not current_user.current_org_id: raise BadRequestError("上传到组织或公共市场前需先加入组织")` 这一行——现在 `target != "personal"` 已经在上一步被拒绝了，这行代码永远走不到，属于死代码。

- [ ] **Step 4: 修改 `create_manual_gene`**

在 `create_manual_gene` 函数体最前面（`if req.target != "personal" and not current_user.current_org_id:` 那一行之前），加同样的校验：

```python
    if req.target != "personal":
        raise BadRequestError(
            "直接上传只能进入个人库，组织库/公共市场的内容请先上传到个人库、"
            "再通过 fork 覆盖同步过去",
            message_key="errors.gene.upload_target_must_be_personal",
        )
```

同样删掉原来紧跟着的、现在永远走不到的旧校验行。

- [ ] **Step 5: 运行测试确认通过**

Run: `cd nodeskclaw-backend && uv run pytest tests/test_gene_upload_target_restriction.py -v`
Expected: 2 passed

- [ ] **Step 6: 跑一遍既有的上传相关回归测试**

Run: `cd nodeskclaw-backend && uv run pytest tests/test_gene_upload_limits.py -q`
Expected: 全部通过（这些测试原本应该都用 `target=personal` 或不传 `target`，不受这次收紧影响；如果有测试显式传了 `target=org`/`target=public` 导致失败，需要把测试改成先上传到 personal 再走 fork，或者如果那条测试的目的就是测上传大小限制、跟 target 无关，直接把 target 改成 personal 即可，不要绕过这次的限制）

- [ ] **Step 7: ruff check + Commit**

```bash
cd nodeskclaw-backend && uv run ruff check app/api/genes.py tests/test_gene_upload_target_restriction.py
git add nodeskclaw-backend/app/api/genes.py nodeskclaw-backend/tests/test_gene_upload_target_restriction.py
git commit -m "feat(backend): 上传入口收紧为只接受 target=personal"
```

---

## Phase 3：血缘传播

### Task 7: `create_gene()` 传播 `lineage_group_id` + 覆盖分支版本号校验

**Files:**
- Modify: `nodeskclaw-backend/app/services/gene_service.py:754-839`（`create_gene` 函数，具体行号以当前文件为准，先搜索 `async def create_gene` 定位）

- [ ] **Step 1: 写失败的测试**

新建 `nodeskclaw-backend/tests/test_gene_lineage_version_awareness.py`：

```python
"""验证 Gene.lineage_group_id 的传播规则、create_gene() 覆盖分支的版本号
校验，以及个人库单向落后检测。

用真实 PostgreSQL 测试库（与 test_gene_name_dedup.py 一致的模式）。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import ConflictError
from app.models.user import User
from app.schemas.gene import GeneCreateRequest
from app.services.gene_service import create_gene

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


def _req(name: str, slug: str, *, version: str = "1.0.0", overwrite: bool = False) -> GeneCreateRequest:
    return GeneCreateRequest(name=name, slug=slug, visibility="personal", version=version, overwrite=overwrite)


@pytest.mark.asyncio
async def test_fresh_create_gets_own_lineage_group_id(require_test_db):
    async with TestSessionLocal() as db:
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add(user)
        await db.commit()

        result = await create_gene(
            db, _req("客服助手", "customer-bot"),
            user_id=user.id, org_id=None, visibility="personal",
        )
        assert result["id"] is not None


@pytest.mark.asyncio
async def test_overwrite_inherits_old_lineage_group_id(require_test_db):
    async with TestSessionLocal() as db:
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add(user)
        await db.commit()

        await create_gene(
            db, _req("客服助手", "customer-bot", version="1.0.0"),
            user_id=user.id, org_id=None, visibility="personal",
        )
        from app.models.gene import Gene
        from sqlalchemy import select
        old = (await db.execute(select(Gene).where(Gene.slug == "customer-bot"))).scalar_one()
        old_lineage_group_id = old.lineage_group_id

        await create_gene(
            db, _req("客服助手", "customer-bot", version="1.0.1", overwrite=True),
            user_id=user.id, org_id=None, visibility="personal",
        )
        new = (await db.execute(
            select(Gene).where(Gene.slug == "customer-bot", Gene.deleted_at.is_(None))
        )).scalar_one()
        assert new.lineage_group_id == old_lineage_group_id
        assert new.version == "1.0.1"


@pytest.mark.asyncio
async def test_overwrite_allows_same_version_number(require_test_db):
    async with TestSessionLocal() as db:
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add(user)
        await db.commit()

        await create_gene(
            db, _req("客服助手", "customer-bot", version="1.0.0"),
            user_id=user.id, org_id=None, visibility="personal",
        )
        result = await create_gene(
            db, _req("客服助手", "customer-bot", version="1.0.0", overwrite=True),
            user_id=user.id, org_id=None, visibility="personal",
        )
        assert result["version"] == "1.0.0"


@pytest.mark.asyncio
async def test_overwrite_rejects_version_regression(require_test_db):
    async with TestSessionLocal() as db:
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add(user)
        await db.commit()

        await create_gene(
            db, _req("客服助手", "customer-bot", version="1.2.0"),
            user_id=user.id, org_id=None, visibility="personal",
        )
        with pytest.raises(ConflictError):
            await create_gene(
                db, _req("客服助手", "customer-bot", version="1.1.0", overwrite=True),
                user_id=user.id, org_id=None, visibility="personal",
            )


@pytest.mark.asyncio
async def test_overwrite_rejects_invalid_version_format(require_test_db):
    async with TestSessionLocal() as db:
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add(user)
        await db.commit()

        await create_gene(
            db, _req("客服助手", "customer-bot", version="1.0.0"),
            user_id=user.id, org_id=None, visibility="personal",
        )
        with pytest.raises(ConflictError):
            await create_gene(
                db, _req("客服助手", "customer-bot", version="latest", overwrite=True),
                user_id=user.id, org_id=None, visibility="personal",
            )
```

- [ ] **Step 2: 运行测试确认失败**

Run: `docker start nodeskclaw-postgres; cd nodeskclaw-backend && uv run pytest tests/test_gene_lineage_version_awareness.py -v`

逐个单独跑（真实 DB 测试批量跑有已知的 pytest-asyncio 事件循环 flaky，跟本次改动无关）。`test_overwrite_inherits_old_lineage_group_id` 会因为 `lineage_group_id` 列不存在报错（如果 Task 3-5 已完成，改成因为 `create_gene` 还没写入这个字段导致断言失败）；`test_overwrite_rejects_version_regression`/`test_overwrite_rejects_invalid_version_format` 应该失败（现在没有版本号校验，覆盖会直接成功）。

- [ ] **Step 3: 修改 `create_gene()`**

先搜索确认当前行号：`grep -n "^async def create_gene" nodeskclaw-backend/app/services/gene_service.py`

在文件顶部导入区加一行：

```python
from app.core.version_compare import compare_versions
```

把 `create_gene()` 函数体改成（在原有基础上插入 `lineage_group_id`/版本号校验相关代码，其余逻辑不变）：

```python
async def create_gene(
    db: AsyncSession, req: GeneCreateRequest, user_id: str | None = None, org_id: str | None = None,
    visibility: str | None = None,
    review_status: str | None = None,
) -> dict:
    resolved_visibility = visibility or req.visibility

    existing = await get_gene_by_slug_in_scope(
        db, req.slug, org_id=org_id, created_by=user_id,
    )
    existing_name = await get_gene_by_name_in_scope(
        db, req.name, visibility=resolved_visibility, org_id=org_id, created_by=user_id,
    )
    if existing is not None and existing_name is not None and existing_name is not existing:
        raise ConflictError(f"技能名称 '{req.name}' 已存在")
    old_gene_id: str | None = None
    lineage_group_id: str | None = None
    if existing or existing_name:
        if req.overwrite:
            target = existing or existing_name
            if target:
                # 版本号必须大于等于旧版本号，只拦截"倒退"这一种情况；
                # 保持原版本号不变是合法操作（表示"内容没有实质变化"），
                # 版本号解析失败时 compare_versions 返回 None，一律拒绝。
                cmp = compare_versions(req.version, target.version)
                if cmp is None:
                    raise ConflictError(f"版本号格式不合法：'{req.version}'")
                if cmp < 0:
                    raise ConflictError(
                        f"新版本号 '{req.version}' 低于当前版本 '{target.version}'，不允许版本倒退"
                    )
                old_gene_id = target.id
                lineage_group_id = target.lineage_group_id
                target.soft_delete()
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
        source_registry="local",
    )
    gene.lineage_group_id = lineage_group_id if lineage_group_id is not None else gene.id
    db.add(gene)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise ConflictError(f"基因 slug '{req.slug}' 或名称 '{req.name}' 已存在") from e
    await db.refresh(gene)

    if old_gene_id is not None:
        await _rewire_gene_references(db, old_gene_id, gene.id)

    return _gene_to_dict(gene)
```

- [ ] **Step 4: 运行测试确认通过**

Run（逐个单独跑）: `docker start nodeskclaw-postgres; cd nodeskclaw-backend && uv run pytest tests/test_gene_lineage_version_awareness.py::test_fresh_create_gets_own_lineage_group_id -v` 等 5 个测试
Expected: 全部 PASS

- [ ] **Step 5: 跑一遍既有回归测试**

Run（逐个单独跑）: `tests/test_gene_name_dedup.py::test_create_gene_overwrite_allows_same_name`、`test_create_gene_overwrite_succeeds_when_only_name_hits_no_slug_match`、`test_create_gene_overwrite_rejects_when_name_hits_unrelated_row`
Expected: 全部 PASS（这几个测试两次调用都没传 `version`，默认值对默认值，"大于等于"校验不会拦截）

- [ ] **Step 6: ruff check + Commit**

```bash
cd nodeskclaw-backend && uv run ruff check app/services/gene_service.py tests/test_gene_lineage_version_awareness.py
git add nodeskclaw-backend/app/services/gene_service.py nodeskclaw-backend/tests/test_gene_lineage_version_awareness.py
git commit -m "feat(backend): create_gene 传播 lineage_group_id 并校验覆盖版本号"
```

---

### Task 8: `publish_variant()` / `handle_creation_callback()` 独立成组

**Files:**
- Modify: `nodeskclaw-backend/app/services/gene_service.py`（`publish_variant`、`handle_creation_callback`）

- [ ] **Step 1: 写失败的测试**

在 `test_gene_lineage_version_awareness.py` 追加：

```python
@pytest.mark.asyncio
async def test_publish_variant_gets_independent_lineage_group_id(require_test_db):
    """variant 是进化出的新技能，不应该继承父技能的 lineage_group_id。"""
    from app.models.cluster import Cluster
    from app.models.gene import Gene, InstanceGene
    from app.models.instance import Instance
    from app.services.gene_service import publish_variant

    async with TestSessionLocal() as db:
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add(user)
        await db.commit()

        cluster = Cluster(id=_uid("cluster"), name="Cluster", created_by=user.id)
        instance = Instance(
            id=_uid("inst"), name="Agent", slug=_uid("agent"), cluster_id=cluster.id,
            namespace="default", image_version="latest", created_by=user.id,
        )
        db.add_all([cluster, instance])
        await db.commit()

        parent = Gene(name="原始助手", slug=_uid("parent-skill"))
        db.add(parent)
        await db.commit()
        parent_lineage_group_id = parent.lineage_group_id

        ig = InstanceGene(
            instance_id=instance.id, gene_id=parent.id,
            learning_output="一些深度学习产出的经验内容",
        )
        db.add(ig)
        await db.commit()

        await publish_variant(db, instance.id, parent.id)

        from sqlalchemy import select
        variant = (await db.execute(
            select(Gene).where(Gene.parent_gene_id == parent.id)
        )).scalar_one()
        assert variant.lineage_group_id != parent_lineage_group_id
        assert variant.lineage_group_id == variant.id
```

- [ ] **Step 2: 运行测试确认失败**

Run: `docker start nodeskclaw-postgres; cd nodeskclaw-backend && uv run pytest tests/test_gene_lineage_version_awareness.py::test_publish_variant_gets_independent_lineage_group_id -v`
Expected: FAIL（`Gene(...)` 构造时没有设置 `lineage_group_id`，NOT NULL 约束会在 commit 时报错）

- [ ] **Step 3: 修改 `publish_variant()` 和 `handle_creation_callback()`**

搜索定位：`grep -n "^async def publish_variant\|^async def handle_creation_callback" nodeskclaw-backend/app/services/gene_service.py`

在 `publish_variant()` 里，`variant = Gene(...)` 构造语句结束、`db.add(variant)` 之前，加一行：

```python
    # variant 是 AI 进化出的新技能，不是"同一个技能换了个 scope"，
    # 不继承父技能的 lineage_group_id，用自己的新 id 单独成组。
    variant.lineage_group_id = variant.id
    db.add(variant)
```

在 `handle_creation_callback()` 里，`gene = Gene(...)` 构造语句结束、`db.add(gene)` 之前，同样加一行：

```python
    gene.lineage_group_id = gene.id
    db.add(gene)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `docker start nodeskclaw-postgres; cd nodeskclaw-backend && uv run pytest tests/test_gene_lineage_version_awareness.py::test_publish_variant_gets_independent_lineage_group_id -v`
Expected: PASS

- [ ] **Step 5: 跑一遍既有回归测试**

Run（逐个单独跑）: `tests/test_gene_name_dedup.py::test_publish_variant_rejects_duplicate_name_in_public_scope`、`test_creation_callback_rejects_duplicate_name_in_public_scope`、`test_publish_variant_integrity_error_on_commit_becomes_conflict_error`
Expected: 全部 PASS

- [ ] **Step 6: ruff check + Commit**

```bash
cd nodeskclaw-backend && uv run ruff check app/services/gene_service.py tests/test_gene_lineage_version_awareness.py
git add nodeskclaw-backend/app/services/gene_service.py nodeskclaw-backend/tests/test_gene_lineage_version_awareness.py
git commit -m "feat(backend): variant 创建路径独立成组，不继承父技能血缘"
```

---

## Phase 4：Fork 覆盖 + 审核暂存

### Task 9: `fork_gene_to_library()` 传播血缘 + 无关行保护 + 版本号三态

**Files:**
- Modify: `nodeskclaw-backend/app/services/gene_service.py`（`fork_gene_to_library` 函数）
- Modify: `nodeskclaw-backend/app/schemas/gene.py`（`ForkGeneRequest`）

- [ ] **Step 1: 写失败的测试**

在 `test_gene_lineage_version_awareness.py` 追加（先在文件顶部补 `from app.models.organization import Organization` 之类的必要 import，跟已有测试保持一致的风格）：

```python
class _FakeUser:
    def __init__(self, id_: str, org_id: str | None, is_super_admin: bool = False):
        self.id = id_
        self.is_super_admin = is_super_admin
        self.current_org_id = org_id


@pytest.mark.asyncio
async def test_fork_inherits_source_lineage_group_id_and_version(require_test_db):
    from app.models.gene import Gene
    from app.models.organization import Organization
    from app.services.gene_service import fork_gene_to_library
    from sqlalchemy import select

    async with TestSessionLocal() as db:
        org = Organization(id=_uid("org"), name="Org A", slug=_uid("org-a"))
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add_all([org, user])
        await db.commit()

        source = Gene(name="客服助手", slug=_uid("customer-bot"), visibility="public", version="1.2.0")
        db.add(source)
        await db.commit()
        source_lineage_group_id = source.lineage_group_id

        result = await fork_gene_to_library(
            db, source.id, "org", current_user=_FakeUser(user.id, org.id), org_id=org.id,
        )
        forked = (await db.execute(select(Gene).where(Gene.id == result["id"]))).scalar_one()
        assert forked.lineage_group_id == source_lineage_group_id
        assert forked.version == "1.2.0"


@pytest.mark.asyncio
async def test_fork_overwrite_rejects_unrelated_lineage_regardless_of_flag(require_test_db):
    from app.models.gene import Gene
    from app.models.organization import Organization
    from app.services.gene_service import fork_gene_to_library

    async with TestSessionLocal() as db:
        org = Organization(id=_uid("org"), name="Org A", slug=_uid("org-a"))
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add_all([org, user])
        await db.commit()

        source = Gene(name="撞名助手", slug=_uid("source-skill"), visibility="public", version="2.0.0")
        unrelated_in_org = Gene(
            name="撞名助手", slug=_uid("unrelated-skill"), visibility="org_private",
            org_id=org.id, created_by=user.id, version="1.0.0",
        )
        db.add_all([source, unrelated_in_org])
        await db.commit()

        with pytest.raises(ConflictError):
            await fork_gene_to_library(
                db, source.id, "org", current_user=_FakeUser(user.id, org.id),
                org_id=org.id, overwrite=True,
            )

        from sqlalchemy import select
        still_there = (await db.execute(
            select(Gene).where(Gene.id == unrelated_in_org.id, Gene.deleted_at.is_(None))
        )).scalar_one_or_none()
        assert still_there is not None


@pytest.mark.asyncio
async def test_fork_overwrite_personal_target_executes_immediately(require_test_db):
    """personal 目标不需要审核，版本校验通过后立即软删旧行、插入新行。"""
    from app.models.gene import Gene
    from app.services.gene_service import fork_gene_to_library
    from sqlalchemy import select

    async with TestSessionLocal() as db:
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add(user)
        await db.commit()

        source = Gene(name="团队助手", slug=_uid("team-bot"), visibility="public", version="1.0.0")
        db.add(source)
        await db.commit()

        forked = await fork_gene_to_library(
            db, source.id, "personal", current_user=_FakeUser(user.id, None), org_id=None,
        )
        old_id = forked["id"]

        source_row = (await db.execute(select(Gene).where(Gene.id == source.id))).scalar_one()
        source_row.version = "1.1.0"
        await db.commit()

        result = await fork_gene_to_library(
            db, source.id, "personal", current_user=_FakeUser(user.id, None),
            org_id=None, overwrite=True,
        )
        assert result["version"] == "1.1.0"
        assert result["id"] != old_id

        old_row = (await db.execute(
            select(Gene).where(Gene.id == old_id, Gene.deleted_at.is_(None))
        )).scalar_one_or_none()
        assert old_row is None  # personal 目标立即软删，不走审核暂存
```

- [ ] **Step 2: 运行测试确认失败**

Run（逐个单独跑）: `docker start nodeskclaw-postgres; cd nodeskclaw-backend && uv run pytest tests/test_gene_lineage_version_awareness.py::test_fork_inherits_source_lineage_group_id_and_version -v`（以此类推）
Expected: 全部 FAIL（`fork_gene_to_library()` 还没有 `overwrite` 参数）

- [ ] **Step 3: 给 `ForkGeneRequest` 加 `overwrite` 字段**

在 `nodeskclaw-backend/app/schemas/gene.py`，把：

```python
class ForkGeneRequest(BaseModel):
    """从公共市场 fork 一份 gene 到个人/组织 library。"""

    # 仅允许 fork 到 personal / org，公共市场副本不能直接 fork（要走 publish_to_market）
    target: ForkTarget
```

改成：

```python
class ForkGeneRequest(BaseModel):
    """从公共市场 fork 一份 gene 到个人/组织 library。"""

    # 仅允许 fork 到 personal / org，公共市场副本不能直接 fork（要走 publish_to_market）
    target: ForkTarget
    # 目标 scope 已有同名且同血缘的技能时，是否覆盖
    overwrite: bool = False
```

- [ ] **Step 4: 修改 `fork_gene_to_library()`**

先搜索确认当前行号：`grep -n "^async def fork_gene_to_library" nodeskclaw-backend/app/services/gene_service.py`

在文件顶部导入区（如果 Task 7 已经加过 `from app.core.version_compare import compare_versions` 就不用重复加）确认已有这行导入。

把函数签名：

```python
async def fork_gene_to_library(
    db: AsyncSession,
    source_identifier: str,
    target: str,
    *,
    current_user,
    org_id: str | None = None,
) -> dict:
```

改成：

```python
async def fork_gene_to_library(
    db: AsyncSession,
    source_identifier: str,
    target: str,
    *,
    current_user,
    org_id: str | None = None,
    overwrite: bool = False,
) -> dict:
```

把"2.5. 名称查重"部分：

```python
    existing_name = await get_gene_by_name_in_scope(
        db, source_name,
        visibility=attrs["visibility"],
        org_id=attrs["org_id"],
        created_by=attrs["created_by"],
    )
    if existing_name is not None:
        raise ConflictError(f"技能名称 '{source_name}' 已存在")
```

改成：

```python
    existing_name = await get_gene_by_name_in_scope(
        db, source_name,
        visibility=attrs["visibility"],
        org_id=attrs["org_id"],
        created_by=attrs["created_by"],
    )
    if existing_name is not None:
        # 名字撞车但血缘不相关：不管 overwrite 是否为 True，一律拒绝，
        # 避免把一个毫不相关的技能误覆盖掉。
        if source is None or existing_name.lineage_group_id != source.lineage_group_id:
            raise ConflictError(f"技能名称 '{source_name}' 已存在")
        if not overwrite:
            raise ConflictError(f"技能名称 '{source_name}' 已存在")
        # 同血缘，且调用方确认要覆盖：按版本号三态处理。
        cmp = compare_versions(source.version, existing_name.version)
        if cmp is None:
            raise ConflictError(f"版本号格式不合法：源 '{source.version}' 或目标 '{existing_name.version}'")
        if cmp == 0:
            raise ConflictError(
                "已是最新版本，无需同步",
                message_key="errors.gene.fork_already_up_to_date",
            )
        if cmp < 0:
            raise ConflictError(
                f"目标版本 '{existing_name.version}' 比源头版本 '{source.version}' 更新，无法覆盖为旧版本",
                message_key="errors.gene.fork_version_regression",
            )
        # 版本校验通过：personal 目标立即执行；org/public 目标走审核暂存（Task 10）
        if target == "personal":
            old_gene_id = existing_name.id
            source_lineage_group_id = source.lineage_group_id
            existing_name.soft_delete()
            await db.commit()
        else:
            return await _submit_gene_overwrite(
                db, source=source, target_gene=existing_name, attrs=attrs,
                new_slug=new_slug_placeholder_computed_below,
            )
```

**注意**：上面这段伪代码里 `new_slug` 在原函数里是"3. 计算副本 slug"那一步才算出来的，而"2.5 名称查重"在原函数里位于"3. 计算副本 slug"**之前**——需要调整顺序：先把"3. 计算副本 slug"这部分挪到"2.5 名称查重"前面（或者把 2.5 需要用到的 `existing_name`/覆盖判断整体挪到 3 之后），确保写代码时 `new_slug` 变量已经存在。具体做法：保留原来的步骤顺序（2.5 在 3 之前），仅在 2.5 里为 `existing_name.lineage_group_id == source.lineage_group_id` 且 `overwrite=True` 且版本校验通过的情况打一个本地变量标记（如 `pending_overwrite_target = existing_name`），继续往下走到步骤 3 算出 `new_slug`，构造完 `fork = Gene(...)` 对象（先不 `db.add`/`commit`）之后，再根据 `pending_overwrite_target`/`target` 分两条路径处理：

```python
    # 步骤 3（计算 new_slug）和构造 fork = Gene(...) 对象照原样保留，只是先不要
    # db.add(fork)/db.commit()，构造完 Gene 对象后先设置好 lineage_group_id：
    fork.lineage_group_id = source.lineage_group_id if source is not None else fork.id

    if pending_overwrite_target is not None and target != "personal":
        # org/public 目标：不落 genes 表，改成写入 GeneOverwriteSubmission（Task 10）
        return await _create_gene_overwrite_submission(
            db, target_gene=pending_overwrite_target, fork_gene=fork, attrs=attrs,
        )

    if pending_overwrite_target is not None and target == "personal":
        # personal 目标：立即软删旧行
        old_gene_id = pending_overwrite_target.id
        pending_overwrite_target.soft_delete()

    db.add(fork)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise ConflictError(f"基因 slug '{new_slug}' 或名称 '{source_name}' 已存在") from e
    await db.refresh(fork)

    if pending_overwrite_target is not None:
        await _rewire_gene_references(db, old_gene_id, fork.id)

    return _gene_to_dict(fork)
```

这一步的具体代码整合方式，请实现时以"保留原函数已有的步骤顺序（权限校验 → 名称查重判断覆盖资格 → 计算 slug → 构造 Gene 对象 → 提交）"为准，重点是：**`existing_name` 的血缘/版本判断要在构造新 `Gene` 对象之前完成**（这样才能在真正冲突的情况下尽早 raise，不用先构造好对象再抛弃），**真正的 `db.add`/`commit`/软删要在最后统一处理**（这样才能在"org/public 目标"分支里改成调用 `_create_gene_overwrite_submission` 而不触碰 `genes` 表）。

- [ ] **Step 5: 运行测试确认通过（先只跑 personal 目标和无关行保护这两个，org/public 目标的测试在 Task 10 完成后再跑）**

Run（逐个单独跑）: `test_fork_inherits_source_lineage_group_id_and_version`、`test_fork_overwrite_rejects_unrelated_lineage_regardless_of_flag`、`test_fork_overwrite_personal_target_executes_immediately`
Expected: 全部 PASS

- [ ] **Step 6: 跑一遍 fork 的 mock 回归测试**

Run: `cd nodeskclaw-backend && uv run pytest tests/test_gene_target_fork_review.py -q`
Expected: 32 passed（如果 mock 夹具构造的 Gene 对象没有 `lineage_group_id` 属性导致报错，给对应 mock 补上这个属性）

- [ ] **Step 7: ruff check + Commit**

```bash
cd nodeskclaw-backend && uv run ruff check app/services/gene_service.py app/schemas/gene.py tests/test_gene_lineage_version_awareness.py
git add nodeskclaw-backend/app/services/gene_service.py nodeskclaw-backend/app/schemas/gene.py nodeskclaw-backend/tests/test_gene_lineage_version_awareness.py
git commit -m "feat(backend): fork_gene_to_library 支持 overwrite（personal 立即执行分支）"
```

---

### Task 10: 覆盖提交暂存 —— `_create_gene_overwrite_submission()`

**Files:**
- Modify: `nodeskclaw-backend/app/services/gene_service.py`

- [ ] **Step 1: 写失败的测试**

在 `test_gene_lineage_version_awareness.py` 追加：

```python
@pytest.mark.asyncio
async def test_fork_overwrite_org_target_creates_submission_not_gene(require_test_db):
    """org/public 目标：版本校验通过后只创建 GeneOverwriteSubmission，
    existing_name 那一行完全不受影响。"""
    from app.models.gene import Gene
    from app.models.gene_overwrite_submission import GeneOverwriteSubmission
    from app.models.organization import Organization
    from app.services.gene_service import fork_gene_to_library
    from sqlalchemy import select

    async with TestSessionLocal() as db:
        org = Organization(id=_uid("org"), name="Org X", slug=_uid("org-x"))
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add_all([org, user])
        await db.commit()

        source = Gene(name="团队助手", slug=_uid("team-bot"), visibility="public", version="1.0.0")
        db.add(source)
        await db.commit()

        forked = await fork_gene_to_library(
            db, source.id, "org", current_user=_FakeUser(user.id, org.id), org_id=org.id,
        )
        target_id = forked["id"]

        source_row = (await db.execute(select(Gene).where(Gene.id == source.id))).scalar_one()
        source_row.version = "1.1.0"
        await db.commit()

        result = await fork_gene_to_library(
            db, source.id, "org", current_user=_FakeUser(user.id, org.id),
            org_id=org.id, overwrite=True,
        )
        assert result.get("kind") == "overwrite_submission"

        # existing_name（原本 org 那条 v1.0.0）完全不受影响
        target_row = (await db.execute(
            select(Gene).where(Gene.id == target_id, Gene.deleted_at.is_(None))
        )).scalar_one_or_none()
        assert target_row is not None
        assert target_row.version == "1.0.0"

        submission = (await db.execute(
            select(GeneOverwriteSubmission).where(GeneOverwriteSubmission.target_gene_id == target_id)
        )).scalar_one()
        assert submission.version == "1.1.0"
        assert submission.review_status == "pending_owner"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `docker start nodeskclaw-postgres; cd nodeskclaw-backend && uv run pytest tests/test_gene_lineage_version_awareness.py::test_fork_overwrite_org_target_creates_submission_not_gene -v`
Expected: FAIL（`_create_gene_overwrite_submission` 还不存在）

- [ ] **Step 3: 实现 `_create_gene_overwrite_submission()`**

在 `gene_service.py` 里，`fork_gene_to_library()` 函数定义之前，新增：

```python
async def _create_gene_overwrite_submission(
    db: AsyncSession,
    *,
    target_gene: Gene,
    fork_gene: Gene,
    attrs: dict,
) -> dict:
    """org/public 目标的 fork 覆盖：不落 genes 表，写入待审核的 GeneOverwriteSubmission。

    真正的软删旧行 + 插入新行，等 review_gene_overwrite_submission() 批准
    那一刻才执行——这样审核拒绝时 target_gene 完全不受影响。
    """
    from app.models.gene_overwrite_submission import GeneOverwriteSubmission

    submission = GeneOverwriteSubmission(
        target_gene_id=target_gene.id,
        source_gene_id=fork_gene.parent_gene_id,
        lineage_group_id=fork_gene.lineage_group_id,
        name=fork_gene.name,
        slug=fork_gene.slug,
        description=fork_gene.description,
        short_description=fork_gene.short_description,
        category=fork_gene.category,
        tags=fork_gene.tags,
        source=fork_gene.source,
        source_ref=fork_gene.source_ref,
        icon=fork_gene.icon,
        version=fork_gene.version,
        manifest=fork_gene.manifest,
        dependencies=fork_gene.dependencies,
        synergies=fork_gene.synergies,
        visibility=attrs["visibility"],
        org_id=attrs["org_id"],
        created_by=attrs["created_by"],
        review_status=GeneReviewStatus.pending_owner,
    )
    db.add(submission)
    await db.commit()
    await db.refresh(submission)
    return {
        "kind": "overwrite_submission",
        "submission_id": submission.id,
        "target_gene_id": target_gene.id,
        "proposed_version": submission.version,
    }
```

在 `fork_gene_to_library()` 里对应"org/public 目标"分支的代码里（Task 9 Step 4 写的位置），把调用改成：

```python
    if pending_overwrite_target is not None and target != "personal":
        return await _create_gene_overwrite_submission(
            db, target_gene=pending_overwrite_target, fork_gene=fork, attrs=attrs,
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `docker start nodeskclaw-postgres; cd nodeskclaw-backend && uv run pytest tests/test_gene_lineage_version_awareness.py::test_fork_overwrite_org_target_creates_submission_not_gene -v`
Expected: PASS

- [ ] **Step 5: ruff check + Commit**

```bash
cd nodeskclaw-backend && uv run ruff check app/services/gene_service.py tests/test_gene_lineage_version_awareness.py
git add nodeskclaw-backend/app/services/gene_service.py nodeskclaw-backend/tests/test_gene_lineage_version_awareness.py
git commit -m "feat(backend): fork 覆盖 org/public 目标改为写入 GeneOverwriteSubmission"
```

---

### Task 11: 审核确认 —— `review_gene_overwrite_submission()`

**Files:**
- Modify: `nodeskclaw-backend/app/services/gene_service.py`
- Create: `nodeskclaw-backend/tests/test_gene_overwrite_submission_review.py`

- [ ] **Step 1: 写失败的测试**

```python
"""nodeskclaw-backend/tests/test_gene_overwrite_submission_review.py

验证覆盖审核暂存的提交/批准/拒绝/过期竞态。
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.models.gene import Gene
from app.models.gene_overwrite_submission import GeneOverwriteSubmission
from app.models.instance import Instance
from app.models.cluster import Cluster
from app.models.gene import InstanceGene
from app.models.organization import Organization
from app.models.org_membership import OrgMembership, OrgRole
from app.models.user import User
from app.services.gene_service import (
    fork_gene_to_library,
    get_instance_genes,
    review_gene_overwrite_submission,
)

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


class _FakeUser:
    def __init__(self, id_: str, org_id: str | None, is_super_admin: bool = False):
        self.id = id_
        self.is_super_admin = is_super_admin
        self.current_org_id = org_id


async def _setup_org_with_admin(db: AsyncSession):
    org = Organization(id=_uid("org"), name="Org X", slug=_uid("org-x"))
    submitter = User(id=_uid("user"), name="Alice", username=_uid("alice"))
    admin = User(id=_uid("admin"), name="Admin", username=_uid("admin"))
    db.add_all([org, submitter, admin])
    await db.commit()
    membership = OrgMembership(org_id=org.id, user_id=admin.id, role=OrgRole.admin)
    db.add(membership)
    await db.commit()
    return org, submitter, admin


@pytest.mark.asyncio
async def test_approve_replaces_target_and_rewires_instance_gene(require_test_db):
    async with TestSessionLocal() as db:
        org, submitter, admin = await _setup_org_with_admin(db)

        source = Gene(name="团队助手", slug=_uid("team-bot"), visibility="public", version="1.0.0")
        db.add(source)
        await db.commit()

        forked = await fork_gene_to_library(
            db, source.id, "org", current_user=_FakeUser(submitter.id, org.id), org_id=org.id,
        )
        target_id = forked["id"]

        # 给这个组织的技能装一个实例，验证审核通过后引用会重接
        cluster = Cluster(id=_uid("cluster"), name="Cluster", created_by=submitter.id)
        instance = Instance(
            id=_uid("inst"), name="Agent", slug=_uid("agent"), cluster_id=cluster.id,
            namespace="default", image_version="latest", created_by=submitter.id,
        )
        db.add_all([cluster, instance])
        await db.commit()
        ig = InstanceGene(instance_id=instance.id, gene_id=target_id, status="installed")
        db.add(ig)
        await db.commit()

        source_row = (await db.execute(select(Gene).where(Gene.id == source.id))).scalar_one()
        source_row.version = "1.1.0"
        await db.commit()

        submit_result = await fork_gene_to_library(
            db, source.id, "org", current_user=_FakeUser(submitter.id, org.id),
            org_id=org.id, overwrite=True,
        )
        submission_id = submit_result["submission_id"]

        result = await review_gene_overwrite_submission(
            db, submission_id, "approve", current_user=_FakeUser(admin.id, org.id),
        )
        assert result["review_status"] == "approved"

        old_row = (await db.execute(
            select(Gene).where(Gene.id == target_id, Gene.deleted_at.is_(None))
        )).scalar_one_or_none()
        assert old_row is None  # 旧行已被软删

        new_row = (await db.execute(
            select(Gene).where(Gene.lineage_group_id == source_row.lineage_group_id, Gene.visibility == "org_private")
        )).scalar_one()
        assert new_row.version == "1.1.0"

        # InstanceGene 引用应该重接到新行
        items = await get_instance_genes(db, instance.id)
        assert any(item["gene_id"] == new_row.id for item in items)


@pytest.mark.asyncio
async def test_reject_leaves_target_untouched(require_test_db):
    async with TestSessionLocal() as db:
        org, submitter, admin = await _setup_org_with_admin(db)

        source = Gene(name="团队助手", slug=_uid("team-bot"), visibility="public", version="1.0.0")
        db.add(source)
        await db.commit()

        forked = await fork_gene_to_library(
            db, source.id, "org", current_user=_FakeUser(submitter.id, org.id), org_id=org.id,
        )
        target_id = forked["id"]

        source_row = (await db.execute(select(Gene).where(Gene.id == source.id))).scalar_one()
        source_row.version = "1.1.0"
        await db.commit()

        submit_result = await fork_gene_to_library(
            db, source.id, "org", current_user=_FakeUser(submitter.id, org.id),
            org_id=org.id, overwrite=True,
        )
        submission_id = submit_result["submission_id"]

        result = await review_gene_overwrite_submission(
            db, submission_id, "reject", reason="内容需要修改", current_user=_FakeUser(admin.id, org.id),
        )
        assert result["review_status"] == "rejected"

        target_row = (await db.execute(
            select(Gene).where(Gene.id == target_id, Gene.deleted_at.is_(None))
        )).scalar_one_or_none()
        assert target_row is not None
        assert target_row.version == "1.0.0"


@pytest.mark.asyncio
async def test_approve_stale_submission_auto_rejects(require_test_db):
    """提交后、审核前，target 已经被另一条已批准的提交替换掉——approve 应该
    自动转为 rejected，不报服务器错误，也不误伤已经替换成功的新行。"""
    async with TestSessionLocal() as db:
        org, submitter, admin = await _setup_org_with_admin(db)

        source = Gene(name="团队助手", slug=_uid("team-bot"), visibility="public", version="1.0.0")
        db.add(source)
        await db.commit()

        forked = await fork_gene_to_library(
            db, source.id, "org", current_user=_FakeUser(submitter.id, org.id), org_id=org.id,
        )

        source_row = (await db.execute(select(Gene).where(Gene.id == source.id))).scalar_one()
        source_row.version = "1.1.0"
        await db.commit()
        submit_1 = await fork_gene_to_library(
            db, source.id, "org", current_user=_FakeUser(submitter.id, org.id),
            org_id=org.id, overwrite=True,
        )

        source_row.version = "1.2.0"
        await db.commit()
        submit_2 = await fork_gene_to_library(
            db, source.id, "org", current_user=_FakeUser(submitter.id, org.id),
            org_id=org.id, overwrite=True,
        )

        # 先批准第二个提交（v1.2.0），target 行被替换
        await review_gene_overwrite_submission(
            db, submit_2["submission_id"], "approve", current_user=_FakeUser(admin.id, org.id),
        )

        # 再批准第一个提交（v1.1.0）：它的 target_gene_id 已经不是活跃行了，应该自动过期拒绝
        result = await review_gene_overwrite_submission(
            db, submit_1["submission_id"], "approve", current_user=_FakeUser(admin.id, org.id),
        )
        assert result["review_status"] == "rejected"
        assert result.get("stale") is True

        # 已经替换成功的新行（v1.2.0）不受影响
        from sqlalchemy import select as sa_select
        current = (await db.execute(
            sa_select(Gene).where(Gene.lineage_group_id == source_row.lineage_group_id, Gene.visibility == "org_private", Gene.deleted_at.is_(None))
        )).scalar_one()
        assert current.version == "1.2.0"


@pytest.mark.asyncio
async def test_approve_does_not_bypass_for_admin_submitter(require_test_db):
    """提交覆盖的人自己就是该组织 admin：submission 依然是 pending_owner，
    不会自动 approved，必须显式调用 approve。"""
    async with TestSessionLocal() as db:
        org = Organization(id=_uid("org"), name="Org Y", slug=_uid("org-y"))
        admin = User(id=_uid("admin"), name="Admin", username=_uid("admin"))
        db.add_all([org, admin])
        await db.commit()
        membership = OrgMembership(org_id=org.id, user_id=admin.id, role=OrgRole.admin)
        db.add(membership)
        await db.commit()

        source = Gene(name="团队助手", slug=_uid("team-bot"), visibility="public", version="1.0.0")
        db.add(source)
        await db.commit()

        await fork_gene_to_library(
            db, source.id, "org", current_user=_FakeUser(admin.id, org.id), org_id=org.id,
        )

        from sqlalchemy import select as sa_select
        source_row = (await db.execute(sa_select(Gene).where(Gene.id == source.id))).scalar_one()
        source_row.version = "1.1.0"
        await db.commit()

        submit_result = await fork_gene_to_library(
            db, source.id, "org", current_user=_FakeUser(admin.id, org.id),
            org_id=org.id, overwrite=True,
        )
        submission = (await db.execute(
            sa_select(GeneOverwriteSubmission).where(GeneOverwriteSubmission.id == submit_result["submission_id"])
        )).scalar_one()
        assert submission.review_status == "pending_owner"  # 没有因为提交者是 admin 而自动变成 approved
```

- [ ] **Step 2: 运行测试确认失败**

Run（逐个单独跑）
Expected: 全部 FAIL（`review_gene_overwrite_submission` 还不存在）

- [ ] **Step 3: 实现 `review_gene_overwrite_submission()`**

在 `gene_service.py` 里，`review_gene()` 函数（`async def review_gene(`）之后，新增：

```python
async def review_gene_overwrite_submission(
    db: AsyncSession,
    submission_id: str,
    action: str,
    reason: str | None = None,
    *,
    current_user=None,
) -> dict:
    """审核 fork 覆盖 org/public 的暂存提交。

    权限跟 review_gene() 完全一致（该 gene 所属 org 的 admin 或平台超管），
    但不复用 bypass_review——提交者自己是 admin 也必须显式调用这个函数才
    会生效，不会因为身份而自动跳过。
    """
    from app.models.gene_overwrite_submission import GeneOverwriteSubmission
    from app.models.org_membership import OrgMembership, OrgRole

    result = await db.execute(
        select(GeneOverwriteSubmission).where(
            GeneOverwriteSubmission.id == submission_id, not_deleted(GeneOverwriteSubmission),
        )
    )
    submission = result.scalar_one_or_none()
    if not submission:
        raise NotFoundError("覆盖提交不存在")
    if submission.review_status not in (GeneReviewStatus.pending_owner, GeneReviewStatus.pending_admin):
        raise BadRequestError(f"当前状态 '{submission.review_status}' 不可审核")

    if current_user is not None and not getattr(current_user, "is_super_admin", False):
        membership = (await db.execute(
            select(OrgMembership).where(
                OrgMembership.user_id == current_user.id,
                OrgMembership.org_id == submission.org_id,
                OrgMembership.role == OrgRole.admin,
                OrgMembership.deleted_at.is_(None),
            )
        )).scalar_one_or_none()
        if membership is None:
            raise ForbiddenError(
                message="您无权审核此提交（需该技能所属组织的管理员）",
                message_key="errors.gene.review_forbidden",
            )

    if action == "reject":
        submission.review_status = GeneReviewStatus.rejected
        submission.reject_reason = reason
        await db.commit()
        return {"review_status": submission.review_status, "stale": False}

    if action != "approve":
        raise BadRequestError(f"未知审核动作: {action}")

    # 过期重新校验：target 可能已经被别的已批准提交替换掉
    target = (await db.execute(
        select(Gene).where(Gene.id == submission.target_gene_id, not_deleted(Gene))
    )).scalar_one_or_none()
    stale = (
        target is None
        or target.lineage_group_id != submission.lineage_group_id
        or compare_versions(submission.version, target.version) != 1
    )
    if stale:
        submission.review_status = GeneReviewStatus.rejected
        submission.reject_reason = "目标技能已发生变化，请重新提交"
        await db.commit()
        return {"review_status": submission.review_status, "stale": True}

    old_gene_id = target.id
    target.soft_delete()

    new_gene = Gene(
        name=submission.name,
        slug=submission.slug,
        description=submission.description,
        short_description=submission.short_description,
        category=submission.category,
        tags=submission.tags,
        source=submission.source,
        source_ref=submission.source_ref,
        icon=submission.icon,
        version=submission.version,
        manifest=submission.manifest,
        dependencies=submission.dependencies,
        synergies=submission.synergies,
        parent_gene_id=submission.source_gene_id,
        visibility=submission.visibility,
        org_id=submission.org_id,
        created_by=submission.created_by,
        is_published=True,
        review_status=GeneReviewStatus.approved,
        source_registry="local",
    )
    new_gene.lineage_group_id = submission.lineage_group_id
    db.add(new_gene)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise ConflictError(f"技能名称 '{submission.name}' 或 slug '{submission.slug}' 已存在") from e
    await db.refresh(new_gene)

    await _rewire_gene_references(db, old_gene_id, new_gene.id)

    submission.review_status = GeneReviewStatus.approved
    await db.commit()

    if new_gene.visibility == "public":
        _fire_task(_push_approved_gene_to_registry(new_gene))

    return {"review_status": submission.review_status, "stale": False, "gene_id": new_gene.id}
```

- [ ] **Step 4: 运行测试确认通过**

Run（逐个单独跑）: 上面写的 4 个测试
Expected: 全部 PASS

- [ ] **Step 5: ruff check + Commit**

```bash
cd nodeskclaw-backend && uv run ruff check app/services/gene_service.py tests/test_gene_overwrite_submission_review.py
git add nodeskclaw-backend/app/services/gene_service.py nodeskclaw-backend/tests/test_gene_overwrite_submission_review.py
git commit -m "feat(backend): 新增 review_gene_overwrite_submission 审核确认逻辑"
```

---

### Task 12: 管理员待审核列表合并展示

**Files:**
- Modify: `nodeskclaw-backend/app/services/gene_service.py`（`get_pending_review_genes`）
- Modify: `nodeskclaw-backend/app/api/genes.py`（新增审核确认端点）

- [ ] **Step 1: 写失败的测试**

在 `test_gene_overwrite_submission_review.py` 追加：

```python
@pytest.mark.asyncio
async def test_pending_review_list_merges_new_and_overwrite_kinds(require_test_db):
    from app.services.gene_service import create_gene, get_pending_review_genes
    from app.schemas.gene import GeneCreateRequest

    async with TestSessionLocal() as db:
        org, submitter, admin = await _setup_org_with_admin(db)

        # 一条普通待审核（走 org 审核的场景需要另建一套，这里偷懒复用
        # create_gene 直接构造一条 pending_owner 的 Gene 模拟"普通待审核"）
        pending_gene_req = GeneCreateRequest(
            name="待审核技能", slug=_uid("pending-skill"), visibility="org_private",
        )
        await create_gene(
            db, pending_gene_req, user_id=submitter.id, org_id=org.id,
            visibility="org_private", review_status="pending_owner",
        )

        source = Gene(name="团队助手", slug=_uid("team-bot"), visibility="public", version="1.0.0")
        db.add(source)
        await db.commit()
        await fork_gene_to_library(
            db, source.id, "org", current_user=_FakeUser(submitter.id, org.id), org_id=org.id,
        )
        from sqlalchemy import select as sa_select
        source_row = (await db.execute(sa_select(Gene).where(Gene.id == source.id))).scalar_one()
        source_row.version = "1.1.0"
        await db.commit()
        await fork_gene_to_library(
            db, source.id, "org", current_user=_FakeUser(submitter.id, org.id),
            org_id=org.id, overwrite=True,
        )

        items = await get_pending_review_genes(db, current_user=_FakeUser(admin.id, org.id))
        kinds = {item["kind"] for item in items}
        assert kinds == {"new", "overwrite"}
        overwrite_item = next(item for item in items if item["kind"] == "overwrite")
        assert overwrite_item["target_gene_version"] == "1.0.0"
        assert overwrite_item["proposed_version"] == "1.1.0"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `docker start nodeskclaw-postgres; cd nodeskclaw-backend && uv run pytest tests/test_gene_overwrite_submission_review.py::test_pending_review_list_merges_new_and_overwrite_kinds -v`
Expected: FAIL（现在的返回结果里没有 `kind` 字段，也不包含覆盖提交）

- [ ] **Step 3: 修改 `get_pending_review_genes()`**

在 `get_pending_review_genes()` 函数的每个分支（超管 / 组织 admin / 兼容旧调用）返回之前，都改成先给普通 Gene 结果打上 `kind="new"`，再合并查询 `GeneOverwriteSubmission` 并打上 `kind="overwrite"`。具体做法：把函数最后统一改成调用一个新的辅助函数收尾，而不是在每个分支各自 `return`：

```python
async def get_pending_review_genes(
    db: AsyncSession,
    current_user=None,
) -> list[dict]:
    if current_user is None:
        gene_rows = (await db.execute(
            select(Gene).where(
                Gene.review_status.in_([GeneReviewStatus.pending_owner, GeneReviewStatus.pending_admin]),
                not_deleted(Gene),
            ).order_by(Gene.created_at.desc())
        )).scalars().all()
        submission_rows = (await db.execute(
            select(GeneOverwriteSubmission).where(
                GeneOverwriteSubmission.review_status.in_([GeneReviewStatus.pending_owner, GeneReviewStatus.pending_admin]),
                not_deleted(GeneOverwriteSubmission),
            ).order_by(GeneOverwriteSubmission.created_at.desc())
        )).scalars().all()
        return await _merge_pending_review_items(db, gene_rows, submission_rows)

    if getattr(current_user, "is_super_admin", False):
        gene_rows = (await db.execute(
            select(Gene).where(
                Gene.review_status.in_([GeneReviewStatus.pending_owner, GeneReviewStatus.pending_admin]),
                not_deleted(Gene),
            ).order_by(Gene.created_at.desc())
        )).scalars().all()
        submission_rows = (await db.execute(
            select(GeneOverwriteSubmission).where(
                GeneOverwriteSubmission.review_status.in_([GeneReviewStatus.pending_owner, GeneReviewStatus.pending_admin]),
                not_deleted(GeneOverwriteSubmission),
            ).order_by(GeneOverwriteSubmission.created_at.desc())
        )).scalars().all()
        return await _merge_pending_review_items(db, gene_rows, submission_rows)

    from app.models.org_membership import OrgMembership, OrgRole

    admin_orgs_result = await db.execute(
        select(OrgMembership.org_id).where(
            OrgMembership.user_id == current_user.id,
            OrgMembership.role == OrgRole.admin,
            OrgMembership.deleted_at.is_(None),
        )
    )
    admin_org_ids = [row[0] for row in admin_orgs_result.all()]
    if not admin_org_ids:
        return []

    gene_rows = (await db.execute(
        select(Gene).where(
            Gene.review_status.in_([GeneReviewStatus.pending_owner, GeneReviewStatus.pending_admin]),
            Gene.org_id.in_(admin_org_ids),
            not_deleted(Gene),
        ).order_by(Gene.created_at.desc())
    )).scalars().all()
    submission_rows = (await db.execute(
        select(GeneOverwriteSubmission).where(
            GeneOverwriteSubmission.review_status.in_([GeneReviewStatus.pending_owner, GeneReviewStatus.pending_admin]),
            GeneOverwriteSubmission.org_id.in_(admin_org_ids),
            not_deleted(GeneOverwriteSubmission),
        ).order_by(GeneOverwriteSubmission.created_at.desc())
    )).scalars().all()
    return await _merge_pending_review_items(db, gene_rows, submission_rows)


async def _merge_pending_review_items(
    db: AsyncSession,
    gene_rows: list[Gene],
    submission_rows: list,
) -> list[dict]:
    new_items = await _attach_uploader_identity(db, [_gene_to_dict(g) for g in gene_rows])
    for item in new_items:
        item["kind"] = "new"

    target_ids = {s.target_gene_id for s in submission_rows}
    target_genes: dict[str, Gene] = {}
    if target_ids:
        target_rows = (await db.execute(select(Gene).where(Gene.id.in_(target_ids)))).scalars().all()
        target_genes = {g.id: g for g in target_rows}

    overwrite_items = []
    for s in submission_rows:
        target = target_genes.get(s.target_gene_id)
        overwrite_items.append({
            "kind": "overwrite",
            "submission_id": s.id,
            "target_gene_id": s.target_gene_id,
            "target_gene_name": target.name if target else s.name,
            "target_gene_version": target.version if target else None,
            "proposed_version": s.version,
            "created_by": s.created_by,
            "created_at": s.created_at,
        })
    overwrite_items = await _attach_uploader_identity(db, overwrite_items)

    return new_items + overwrite_items
```

在文件顶部导入区加一行：

```python
from app.models.gene_overwrite_submission import GeneOverwriteSubmission
```

（如果 Task 10/11 已经用局部 import 的方式引入过，这里改成顶层 import 并删掉局部的重复 import，保持风格一致）

- [ ] **Step 4: 新增审核确认 API 端点**

在 `nodeskclaw-backend/app/api/genes.py` 里，`admin_review_gene`（`PUT /admin/genes/{gene_id}/review`）附近，新增：

```python
@router.put("/admin/gene-overwrite-submissions/{submission_id}/review")
async def admin_review_gene_overwrite_submission(
    submission_id: str,
    req: ReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await gene_service.review_gene_overwrite_submission(
        db, submission_id, req.action, req.reason, current_user=current_user,
    )
    return ApiResponse(data=result)
```

（`ReviewRequest` schema 应该已经存在，复用给 `admin_review_gene` 用的那个即可，检查 `app/schemas/gene.py` 确认字段是 `action`/`reason`）

- [ ] **Step 5: 运行测试确认通过**

Run: `docker start nodeskclaw-postgres; cd nodeskclaw-backend && uv run pytest tests/test_gene_overwrite_submission_review.py::test_pending_review_list_merges_new_and_overwrite_kinds -v`
Expected: PASS

- [ ] **Step 6: 跑一遍既有的 pending-review 回归测试（如果有）**

Run: `cd nodeskclaw-backend && grep -rl "get_pending_review_genes\|pending-review" tests/ | xargs -I{} echo {}`（先看看还有哪些既有测试覆盖这个函数，逐个跑一遍确认没有因为返回结构新增了 `kind` 字段而断言失败——如果有测试直接比较整个返回 list 的内容、没有考虑到新字段，需要更新断言加上 `kind: "new"`）

- [ ] **Step 7: ruff check + Commit**

```bash
cd nodeskclaw-backend && uv run ruff check app/services/gene_service.py app/api/genes.py tests/test_gene_overwrite_submission_review.py
git add nodeskclaw-backend/app/services/gene_service.py nodeskclaw-backend/app/api/genes.py nodeskclaw-backend/tests/test_gene_overwrite_submission_review.py
git commit -m "feat(backend): 待审核列表合并展示新建/覆盖两类记录，新增覆盖审核 API"
```

---

## Phase 5：落后检测（单向，仅个人库）

### Task 13: `newer_sibling_versions` 计算 + 接入列表查询

**Files:**
- Modify: `nodeskclaw-backend/app/services/gene_service.py`（新增函数 + 修改 `_list_genes_local`）

- [ ] **Step 1: 写失败的测试**

在 `test_gene_lineage_version_awareness.py` 追加：

```python
@pytest.mark.asyncio
async def test_list_genes_marks_newer_sibling_version_for_personal_gene(require_test_db):
    """场景：管理员更新了组织版本，A 的个人库应该看到落后提示。"""
    from app.models.gene import Gene
    from app.models.organization import Organization
    from app.models.org_membership import OrgMembership, OrgRole
    from app.services.gene_service import fork_gene_to_library, list_genes
    from sqlalchemy import select

    async with TestSessionLocal() as db:
        org = Organization(id=_uid("org"), name="Org X", slug=_uid("org-x"))
        user = User(id=_uid("user"), name="Alice", username=_uid("alice"))
        db.add_all([org, user])
        await db.commit()
        membership = OrgMembership(org_id=org.id, user_id=user.id, role=OrgRole.member)
        db.add(membership)
        await db.commit()

        personal = Gene(
            name="团队助手", slug=_uid("team-bot"), visibility="personal",
            created_by=user.id, version="1.0.0",
        )
        db.add(personal)
        await db.commit()

        await fork_gene_to_library(
            db, personal.id, "org", current_user=_FakeUser(user.id, org.id), org_id=org.id,
        )
        org_gene = (await db.execute(
            select(Gene).where(Gene.lineage_group_id == personal.lineage_group_id, Gene.visibility == "org_private")
        )).scalar_one()
        org_gene.version = "1.1.0"
        await db.commit()

        genes, _total = await list_genes(
            db, visibility="personal", org_id=None, user_id=user.id, page=1, page_size=20,
        )
        personal_item = next(g for g in genes if g["id"] == personal.id)
        assert personal_item["newer_sibling_versions"] == [
            {"visibility": "org_private", "org_id": org.id, "org_name": "Org X", "version": "1.1.0"},
        ]


@pytest.mark.asyncio
async def test_list_genes_no_badge_on_org_scope_even_if_personal_is_newer(require_test_db):
    """单向检测：即使个人库版本更新，组织库自己的卡片也不应该有任何提示。"""
    from app.models.gene import Gene
    from app.models.organization import Organization
    from app.services.gene_service import fork_gene_to_library, list_genes
    from sqlalchemy import select

    async with TestSessionLocal() as db:
        org = Organization(id=_uid("org"), name="Org Z", slug=_uid("org-z"))
        user = User(id=_uid("user"), name="Carol", username=_uid("carol"))
        db.add_all([org, user])
        await db.commit()

        personal = Gene(
            name="客服助手", slug=_uid("customer-bot"), visibility="personal",
            created_by=user.id, version="1.0.0",
        )
        db.add(personal)
        await db.commit()

        await fork_gene_to_library(
            db, personal.id, "org", current_user=_FakeUser(user.id, org.id), org_id=org.id,
        )

        personal_row = (await db.execute(select(Gene).where(Gene.id == personal.id))).scalar_one()
        personal_row.version = "1.2.0"
        await db.commit()

        genes, _total = await list_genes(
            db, visibility="org_private", org_id=org.id, user_id=user.id, page=1, page_size=20,
        )
        org_item = next(g for g in genes if g["visibility"] == "org_private")
        assert org_item["newer_sibling_versions"] == []


@pytest.mark.asyncio
async def test_list_genes_no_false_positive_right_after_fork(require_test_db):
    from app.models.gene import Gene
    from app.models.organization import Organization
    from app.services.gene_service import fork_gene_to_library, list_genes

    async with TestSessionLocal() as db:
        org = Organization(id=_uid("org"), name="Org Y", slug=_uid("org-y"))
        user = User(id=_uid("user"), name="Bob", username=_uid("bob"))
        db.add_all([org, user])
        await db.commit()

        personal = Gene(
            name="客服助手", slug=_uid("customer-bot"), visibility="personal",
            created_by=user.id, version="1.0.0",
        )
        db.add(personal)
        await db.commit()

        await fork_gene_to_library(
            db, personal.id, "org", current_user=_FakeUser(user.id, org.id), org_id=org.id,
        )

        genes, _total = await list_genes(
            db, visibility="personal", org_id=None, user_id=user.id, page=1, page_size=20,
        )
        personal_item = next(g for g in genes if g["id"] == personal.id)
        assert personal_item["newer_sibling_versions"] == []
```

- [ ] **Step 2: 运行测试确认失败**

Run（逐个单独跑）
Expected: FAIL，`KeyError: 'newer_sibling_versions'`

- [ ] **Step 3: 实现批量查询函数**

在 `_gene_to_dict` 函数（`def _gene_to_dict`）后面新增：

```python
async def _compute_newer_sibling_versions(
    db: AsyncSession,
    genes: list[Gene],
    *,
    user_id: str | None,
) -> dict[str, list[dict]]:
    """单向检测：只为 visibility=personal 的 Gene 计算"组织库/公共市场是否
    比它新"，org_private/public 的 Gene 恒为空数组，不查询、不计算。
    """
    personal_genes = [g for g in genes if g.visibility == ContentVisibility.personal]
    if not personal_genes:
        return {}

    lineage_group_ids = {g.lineage_group_id for g in personal_genes}

    member_org_ids: set[str] = set()
    if user_id:
        from app.models.org_membership import OrgMembership
        rows = await db.execute(
            select(OrgMembership.org_id).where(
                OrgMembership.user_id == user_id, not_deleted(OrgMembership),
            )
        )
        member_org_ids = {r[0] for r in rows.all()}

    visibility_filter = or_(
        Gene.visibility == ContentVisibility.public,
        and_(Gene.visibility == ContentVisibility.org_private, Gene.org_id.in_(member_org_ids)) if member_org_ids else False,
    )
    result = await db.execute(
        select(Gene.id, Gene.lineage_group_id, Gene.visibility, Gene.org_id, Gene.version)
        .where(
            Gene.lineage_group_id.in_(lineage_group_ids),
            not_deleted(Gene),
            Gene.visibility.in_([ContentVisibility.org_private, ContentVisibility.public]),
            visibility_filter,
        )
    )
    candidates = result.all()

    org_ids_needing_name = {row.org_id for row in candidates if row.visibility == ContentVisibility.org_private and row.org_id}
    org_names: dict[str, str] = {}
    if org_ids_needing_name:
        from app.models.organization import Organization
        org_rows = await db.execute(select(Organization.id, Organization.name).where(Organization.id.in_(org_ids_needing_name)))
        org_names = {r.id: r.name for r in org_rows.all()}

    by_group: dict[str, list] = {}
    for row in candidates:
        by_group.setdefault(row.lineage_group_id, []).append(row)

    output: dict[str, list[dict]] = {}
    for gene in personal_genes:
        siblings = by_group.get(gene.lineage_group_id, [])
        newer = []
        for row in siblings:
            cmp = compare_versions(row.version, gene.version)
            if cmp is not None and cmp > 0:
                newer.append({
                    "visibility": row.visibility,
                    "org_id": row.org_id,
                    "org_name": org_names.get(row.org_id) if row.org_id else None,
                    "version": row.version,
                })
        output[gene.id] = newer
    return output
```

- [ ] **Step 4: 接入 `_list_genes_local`**

找到 `_list_genes_local()` 结尾部分：

```python
    result = await db.execute(base)
    genes = result.scalars().all()
    return [_gene_to_dict(g) for g in genes], total
```

改成：

```python
    result = await db.execute(base)
    genes = result.scalars().all()
    newer_versions_by_id = await _compute_newer_sibling_versions(db, genes, user_id=user_id)
    items = []
    for g in genes:
        item = _gene_to_dict(g)
        item["newer_sibling_versions"] = newer_versions_by_id.get(g.id, [])
        items.append(item)
    return items, total
```

- [ ] **Step 5: 运行测试确认通过**

Run（逐个单独跑）: 上面 3 个测试
Expected: 全部 PASS

- [ ] **Step 6: 跑一遍 gene 市场列表相关的既有回归测试**

Run: `cd nodeskclaw-backend && uv run pytest tests/test_gene_target_fork_review.py -q`
Expected: 32 passed（如果有 mock 直接构造 `_gene_to_dict`/`_list_genes_local` 返回值、断言完整 dict 内容导致因为多了 `newer_sibling_versions` 字段而失败，按需给对应 mock/断言补上这个字段）

- [ ] **Step 7: ruff check + Commit**

```bash
cd nodeskclaw-backend && uv run ruff check app/services/gene_service.py tests/test_gene_lineage_version_awareness.py
git add nodeskclaw-backend/app/services/gene_service.py nodeskclaw-backend/tests/test_gene_lineage_version_awareness.py
git commit -m "feat(backend): 新增单向 newer_sibling_versions 落后检测，接入列表查询"
```

---

### Task 14: API 层 —— fork 接口透传 `overwrite`

**Files:**
- Modify: `nodeskclaw-backend/app/api/genes.py`（`fork_gene` 端点）

- [ ] **Step 1: 修改 `fork_gene`**

找到：

```python
@router.post("/genes/{gene_identifier}/fork")
async def fork_gene(
    gene_identifier: str,
    req: ForkGeneRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ...
    gene_data = await gene_service.fork_gene_to_library(
        db, gene_identifier, req.target,
        current_user=current_user,
    )
    return ApiResponse(data=gene_data)
```

改成：

```python
@router.post("/genes/{gene_identifier}/fork")
async def fork_gene(
    gene_identifier: str,
    req: ForkGeneRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ...
    gene_data = await gene_service.fork_gene_to_library(
        db, gene_identifier, req.target,
        current_user=current_user,
        overwrite=req.overwrite,
    )
    return ApiResponse(data=gene_data)
```

（`...` 表示保留原函数体中间的其他代码不变，只改最后这个调用）

- [ ] **Step 2: 确认没有语法错误**

Run: `cd nodeskclaw-backend && uv run python -c "import app.api.genes"`
Expected: 无报错

- [ ] **Step 3: ruff check + Commit**

```bash
cd nodeskclaw-backend && uv run ruff check app/api/genes.py
git add nodeskclaw-backend/app/api/genes.py
git commit -m "feat(backend): fork 接口透传 overwrite 参数"
```

---

## Phase 6：前端

### Task 15: `uploadFolder`/`forkGene` 支持版本号与 overwrite

**Files:**
- Modify: `nodeskclaw-portal/src/services/skills.ts`
- Modify: `nodeskclaw-portal/src/stores/gene.ts`

- [ ] **Step 1: 修改 `uploadFolder`（`services/skills.ts`）**

Run: `grep -n "uploadFolder:" nodeskclaw-portal/src/services/skills.ts`

把找到的函数改成新增 `version` 参数（做法跟以前一致）：

```typescript
  uploadFolder: (
    files: FileList,
    overwrite = false,
    target: UploadTarget = 'personal',
    version?: string,
  ) => {
    const form = new FormData()
    for (const file of Array.from(files)) {
      const relPath = (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name
      form.append('files', file, relPath)
    }
    const params = new URLSearchParams({ target })
    if (overwrite) params.set('overwrite', 'true')
    if (version) params.set('version', version)
    const url = `/genes/upload-folder?${params.toString()}`
    return api.post<{ data: Skill }>(url, form).then((r) => r.data.data)
  },
```

- [ ] **Step 2: 修改 `forkGene`（`stores/gene.ts`）**

Run: `grep -n "async function forkGene" nodeskclaw-portal/src/stores/gene.ts`

把找到的函数改成：

```typescript
  async function forkGene(
    geneIdentifier: string,
    target: 'personal' | 'org' | 'public',
    overwrite = false,
  ): Promise<GeneItem> {
    const res = await api.post(`/genes/${geneIdentifier}/fork`, { target, overwrite })
    return res.data.data
  }
```

- [ ] **Step 3: `GeneItem` 类型新增字段**

Run: `grep -n "interface GeneItem" nodeskclaw-portal/src/stores/gene.ts`

在 `GeneItem` interface 里加：

```typescript
  newer_sibling_versions: Array<{
    visibility: 'org_private' | 'public'
    org_id: string | null
    org_name: string | null
    version: string
  }>
```

- [ ] **Step 4: 类型检查**

Run: `cd nodeskclaw-portal && node node_modules/vue-tsc/bin/vue-tsc.js -b --noEmit`
Expected: 无报错（既有调用 `store.forkGene(id, target)` 只传两个参数，`overwrite` 有默认值 `false`，向后兼容）

- [ ] **Step 5: Commit**

```bash
git add nodeskclaw-portal/src/services/skills.ts nodeskclaw-portal/src/stores/gene.ts
git commit -m "feat(portal): uploadFolder 支持版本号，forkGene 支持 overwrite"
```

---

### Task 16: 移除上传目标里的组织/公共市场选项，覆盖弹窗加版本号输入

**Files:**
- Modify: `nodeskclaw-portal/src/views/GeneMarket.vue`

- [ ] **Step 1: 定位上传目标选择器**

Run: `grep -n "uploadTarget\|UploadTarget" nodeskclaw-portal/src/views/GeneMarket.vue | head -20`

找到渲染"上传目标"选择控件的地方（下拉框/单选组，具体标签请以搜索结果为准）。

- [ ] **Step 2: 移除 org/public 选项**

把渲染 `personal`/`org`/`public` 三个选项的地方改成只渲染 `personal`（如果这个选择器是一个下拉框循环渲染选项数组，直接把数组里的 `org`/`public` 条目删掉；如果 UI 上原本就有"上传到个人库/组织库/公共市场"的切换按钮组，改成只保留个人库这一个，其他两个入口不再显示——组织库/公共市场的内容现在只能从个人库 fork 过去，入口在技能详情页的"Fork"按钮，不在上传弹窗里）。

- [ ] **Step 3: 覆盖确认弹窗加版本号输入框**

Run: `grep -n "是否覆盖原基因\|handleLocalFolder" nodeskclaw-portal/src/views/GeneMarket.vue`

现状（`handleLocalFolder` 函数体内 catch 块）：

```typescript
  } catch (e: any) {
    if (e?.response?.status === 409) {
      const msg = e?.response?.data?.message || ''
      if (msg.includes('已存在') || msg.includes('already exists')) {
        const folderName = input.files[0]?.webkitRelativePath?.split('/')[0] || '该文件夹'
        const ok = confirm(`${folderName} 基因已存在，是否覆盖原基因？`)
        if (ok) {
          try {
            await skillApi.uploadFolder(input.files, true, uploadTarget.value)
            localSuccess.value = `基因已覆盖`
            showLocalUpload.value = false
            selectedLocalFiles.value = []
            await loadData()
          } catch (e2: any) {
            localError.value = e2?.response?.data?.message || '覆盖失败'
          }
        } else {
          localError.value = '已取消上传'
        }
      } else {
        localError.value = msg || '上传失败'
      }
    } else {
      localError.value = e instanceof Error ? e.message : '上传失败'
    }
  } finally {
```

改成：

```typescript
  } catch (e: any) {
    if (e?.response?.status === 409) {
      const msg = e?.response?.data?.message || ''
      if (msg.includes('已存在') || msg.includes('already exists')) {
        const folderName = input.files[0]?.webkitRelativePath?.split('/')[0] || '该文件夹'
        const existingVersion: string = e?.response?.data?.data?.version || '1.0.0'
        const suggested = suggestNextPatch(existingVersion)
        const ok = confirm(`${folderName} 基因已存在（当前版本 ${existingVersion}），是否覆盖原基因？`)
        if (ok) {
          const inputVersion = prompt('请输入本次覆盖的版本号（不改内容可保持原版本号不变）', suggested)
          if (inputVersion === null) {
            localError.value = '已取消上传'
            return
          }
          try {
            await skillApi.uploadFolder(input.files, true, uploadTarget.value, inputVersion)
            localSuccess.value = `基因已覆盖`
            showLocalUpload.value = false
            selectedLocalFiles.value = []
            await loadData()
          } catch (e2: any) {
            localError.value = e2?.response?.data?.message || '覆盖失败'
          }
        } else {
          localError.value = '已取消上传'
        }
      } else {
        localError.value = msg || '上传失败'
      }
    } else {
      localError.value = e instanceof Error ? e.message : '上传失败'
    }
  } finally {
```

在文件顶部 import 区加一行：

```typescript
import { suggestNextPatch } from '@/utils/semver'
```

**已知简化**：后端 409 响应目前不一定会在 `data.data` 里带上被覆盖那一行的当前 `version`，`existingVersion` 会退化成固定的 `'1.0.0'` 兜底。这是一个可以在这个 Task 完成后单独补的小优化（后端 `create_gene` 抛 `ConflictError` 时顺带查一次当前 `version` 塞进响应），不阻塞本任务先跑通整个流程。

- [ ] **Step 4: 类型检查 + 手动验证**

Run: `cd nodeskclaw-portal && node node_modules/vue-tsc/bin/vue-tsc.js -b --noEmit`
Expected: 无报错

手动验证（浏览器）：打开技能市场页，确认"上传"弹窗只能选个人库；上传一个技能，再上传一次同名技能，确认能看到覆盖确认对话框 + 版本号输入框。

- [ ] **Step 5: Commit**

```bash
git add nodeskclaw-portal/src/views/GeneMarket.vue
git commit -m "feat(portal): 上传目标收敛为仅个人库，覆盖弹窗新增版本号输入"
```

---

### Task 17: Fork 覆盖交互（冲突确认、已最新提示、提交等待审核提示）

**Files:**
- Modify: `nodeskclaw-portal/src/views/GeneMarket.vue`（`onForkGene` 函数）
- Modify: `nodeskclaw-portal/src/i18n/locales/zh-CN.ts`、`en-US.ts`

- [ ] **Step 1: 定位现有 fork 调用**

Run: `grep -n "onForkGene\|store.forkGene" nodeskclaw-portal/src/views/GeneMarket.vue`

- [ ] **Step 2: 改造 `onForkGene`**

现状（`onForkGene` 函数体）：

```typescript
async function onForkGene(gene: GeneItem, target: 'personal' | 'org' | 'public') {
  forkingSlug.value = gene.slug
  try {
    const forked = await store.forkGene(gene.id, target)
    const isApproved = forked?.review_status === 'approved'
    let successKey: string
    if (target === 'personal') {
      successKey = 'geneMarket.forkToPersonalSuccess'
    } else if (target === 'org') {
      successKey = isApproved ? 'geneMarket.forkToOrgImmediate' : 'geneMarket.forkToOrgSuccess'
    } else {
      successKey = isApproved ? 'geneMarket.forkToPublicImmediate' : 'geneMarket.forkToPublicSuccess'
    }
    toast.success(t(successKey))
    const visMatches =
      (target === 'personal' && selectedVisibility.value === 'personal') ||
      (target === 'org' && selectedVisibility.value === 'org_private') ||
      (target === 'public' && selectedVisibility.value === 'public')
    if (visMatches) await loadData()
  } catch (e: unknown) {
    toast.error(resolveApiErrorMessage(e, t('geneMarket.forkFailed')))
  } finally {
    forkingSlug.value = null
  }
}
```

改成：

```typescript
async function onForkGene(gene: GeneItem, target: 'personal' | 'org' | 'public', overwrite = false) {
  forkingSlug.value = gene.slug
  try {
    const forked = await store.forkGene(gene.id, target, overwrite)

    if ((forked as any)?.kind === 'overwrite_submission') {
      // org/public 目标命中覆盖：没有立即生效，等待管理员审核
      toast.success(t('geneMarket.forkOverwriteSubmitted'))
      forkingSlug.value = null
      return
    }

    const isApproved = forked?.review_status === 'approved'
    let successKey: string
    if (overwrite) {
      successKey = 'geneMarket.forkOverwriteSuccess'
    } else if (target === 'personal') {
      successKey = 'geneMarket.forkToPersonalSuccess'
    } else if (target === 'org') {
      successKey = isApproved ? 'geneMarket.forkToOrgImmediate' : 'geneMarket.forkToOrgSuccess'
    } else {
      successKey = isApproved ? 'geneMarket.forkToPublicImmediate' : 'geneMarket.forkToPublicSuccess'
    }
    toast.success(t(successKey))
    const visMatches =
      (target === 'personal' && selectedVisibility.value === 'personal') ||
      (target === 'org' && selectedVisibility.value === 'org_private') ||
      (target === 'public' && selectedVisibility.value === 'public')
    if (visMatches) await loadData()
  } catch (e: unknown) {
    const messageKey = (e as { response?: { data?: { message_key?: string } } })?.response?.data?.message_key
    if (messageKey === 'errors.gene.fork_already_up_to_date') {
      toast.success(t('geneMarket.forkAlreadyUpToDate'))
      return
    }
    if (!overwrite) {
      const msg = (e as { response?: { data?: { message?: string } } })?.response?.data?.message || ''
      if (msg.includes('已存在')) {
        const ok = confirm(t('geneMarket.forkConflictConfirm', { name: gene.name }))
        if (ok) {
          await onForkGene(gene, target, true)
          return
        }
      }
    }
    toast.error(resolveApiErrorMessage(e, t('geneMarket.forkFailed')))
  } finally {
    forkingSlug.value = null
  }
}
```

**注意**：`msg.includes('已存在')` 兜底判断跟 `handleLocalFolder` 现有的覆盖上传确认逻辑是同一个模式。真正决定"能不能覆盖"（血缘是否相同、版本号是否允许）的判断权始终在后端——前端这里只是"要不要弹出确认框重试"的粗筛，真正的校验结果还是会在重试请求里被后端拒绝，走到统一的 `toast.error` 分支。

- [ ] **Step 3: 补 i18n 词条**

Run: `grep -n "geneMarket:" nodeskclaw-portal/src/i18n/locales/zh-CN.ts`

在 `geneMarket` 节点里加：

```typescript
    forkOverwriteSuccess: "已覆盖为最新版本",
    forkOverwriteSubmitted: "已提交，等待管理员审核覆盖",
    forkAlreadyUpToDate: "已是最新版本，无需同步",
    forkConflictConfirm: "「{name}」已存在同名技能，是否覆盖为最新版本？",
```

在 `en-US.ts` 的 `geneMarket` 节点里加对应英文：

```typescript
    forkOverwriteSuccess: "Overwritten with the latest version",
    forkOverwriteSubmitted: "Submitted, waiting for admin review",
    forkAlreadyUpToDate: "Already up to date, no sync needed",
    forkConflictConfirm: "A skill named \"{name}\" already exists. Overwrite it with the latest version?",
```

- [ ] **Step 4: 类型检查**

Run: `cd nodeskclaw-portal && node node_modules/vue-tsc/bin/vue-tsc.js -b --noEmit`
Expected: 无报错

- [ ] **Step 5: 手动验证（浏览器）**

场景：把同一个技能 fork 到组织一次，管理员改一下组织版本号（走 Task 16 的覆盖上传流程更新个人库版本，再 fork 到组织覆盖），确认第二次 fork 弹出"是否覆盖"确认框，确认后 toast 提示"已提交，等待管理员审核覆盖"，而不是"覆盖成功"（因为这是 org 目标，需要审核）。

- [ ] **Step 6: Commit**

```bash
git add nodeskclaw-portal/src/views/GeneMarket.vue nodeskclaw-portal/src/i18n/locales/zh-CN.ts nodeskclaw-portal/src/i18n/locales/en-US.ts
git commit -m "feat(portal): fork 覆盖交互 —— 冲突确认、已最新提示、提交等待审核提示"
```

---

### Task 18: 个人库列表卡片展示 `newer_sibling_versions` 角标

**Files:**
- Modify: `nodeskclaw-portal/src/views/GeneMarket.vue`（技能卡片模板部分）

- [ ] **Step 1: 定位技能卡片模板**

Run: `grep -n "v-for=\"gene in\|gene\.name" nodeskclaw-portal/src/views/GeneMarket.vue | head -20`

- [ ] **Step 2: 加角标（只在个人库列表渲染，不需要额外判断 —— 后端对 org_private/public 的 Gene 恒返回空数组，天然不会渲染出角标）**

在技能卡片的名称/标题附近，加一段：

```html
<div v-if="gene.newer_sibling_versions?.length" class="flex flex-wrap gap-1 mt-1">
  <span
    v-for="(sibling, idx) in gene.newer_sibling_versions"
    :key="idx"
    class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-500/15 text-amber-500"
  >
    {{ sibling.org_name || '公共市场' }} 有 v{{ sibling.version }}
  </span>
</div>
```

- [ ] **Step 3: 类型检查 + 手动验证**

Run: `cd nodeskclaw-portal && node node_modules/vue-tsc/bin/vue-tsc.js -b --noEmit`
Expected: 无报错

手动验证：构造一个个人库落后于组织库的场景，刷新个人库页面，确认卡片上出现角标文案；切换到组织库页面，确认没有任何角标（哪怕组织库版本落后于某个人库）。

- [ ] **Step 4: Commit**

```bash
git add nodeskclaw-portal/src/views/GeneMarket.vue
git commit -m "feat(portal): 个人库技能卡片展示跨 scope 版本落后角标"
```

---

## 最终检查

- [ ] **全量跑一次后端测试**

Run: `docker start nodeskclaw-postgres; cd nodeskclaw-backend && uv run pytest tests/test_gene_lineage_version_awareness.py tests/test_gene_overwrite_submission_review.py tests/test_gene_upload_target_restriction.py tests/test_version_compare.py tests/test_gene_lineage_migration_backfill.py tests/test_gene_target_fork_review.py tests/test_gene_name_dedup.py tests/test_gene_overwrite_reference_rewire.py -q`

真实 DB 的测试文件批量跑可能触发已知的 pytest-asyncio flaky（跟本次改动无关），逐个单独跑确认真实通过情况。

- [ ] **全量跑一次前端测试**

Run: `cd nodeskclaw-portal && node node_modules/vitest/vitest.mjs run`
Expected: 全部通过

- [ ] **ruff check 全部改动文件**

Run: `cd nodeskclaw-backend && uv run ruff check app/ tests/test_gene_lineage_version_awareness.py tests/test_gene_overwrite_submission_review.py tests/test_gene_upload_target_restriction.py tests/test_version_compare.py tests/test_gene_lineage_migration_backfill.py`
Expected: All checks passed!

- [ ] **确认设计文档"已知架构局限"一节提到的事项不需要本次处理**

`lineage_group_id` 身份/版本/血缘三合一、覆盖权限没有显式 Maintainer 模型这些问题已经记录为 Task #14 的独立重构范围，本次实现不需要额外处理。
