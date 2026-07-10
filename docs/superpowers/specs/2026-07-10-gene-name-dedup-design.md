# Gene 技能名称查重设计

**日期**：2026-07-10
**状态**：已确认，待实施

---

## 问题描述

`genes` 表目前只有 `(slug, org_id)` 的 partial unique index（`uq_genes_slug_org_active`），`name` 字段完全没有唯一性约束。三个创建入口都不做 name 查重：

- `/genes/upload-folder`（`upload_gene_folder`）：slug 由 `_slugify_gene_name(name)` 自动派生（中文名走确定性哈希兜底），name 本身重复与否不影响 slug 生成结果的唯一性判断
- `/genes/manual`：slug 由前端直接传入，name 无任何校验
- `POST /genes/{gene_identifier}/fork`（`fork_gene_to_library`）：只在目标 `org_id` 内查 slug 冲突，冲突则自动加 `-fork-{uuid6}` 后缀，从不检查 name

结果是同一 scope 内可以出现多个同名但 slug 不同的技能（例如手动指定不同 slug，或 fork 时自动改名），造成用户混淆。

---

## 查重范围（按 scope 分别查重，不跨 scope）

| Scope | 唯一性范围 | 说明 |
|---|---|---|
| personal | 同一用户（`created_by`）自己的 personal 技能内 | 不同用户各自的 personal 库互不影响 |
| org | 同一 `org_id` 内 | 不同组织可以有同名技能 |
| public | 全局唯一 | 公共市场是单一命名空间 |

匹配规则：`trim` 后忽略大小写比较（如 `"Customer Bot"` 与 `" customer bot "` 视为同名）。

---

## 处理方式

检测到同 scope 内已存在同名技能 → **硬阻止**，抛 `ConflictError`（HTTP 409），复用现有 409 处理链路，不新增前端分支。`overwrite=True` 时跳过检查，走现有软删旧记录再插入的覆盖逻辑（与 slug 的 overwrite 语义一致）。

Fork 场景（`fork_gene_to_library`）：目标 scope 已存在同名技能时同样硬阻止，**不再**沿用"slug 自动加后缀"来绕开重名——因为这与"防止重名出现"的需求本身矛盾。

---

## 方案：应用层预检查 + 数据库唯一索引兜底

### 数据库改动

新增 3 条 partial unique index（`visibility` 是 `String(16)` 列，非 Postgres 原生 enum，可直接在 `postgresql_where` 里用字符串比较）：

```python
# personal：按 (小写trim后的name, created_by) 唯一，仅限 visibility='personal'
op.create_index(
    'uq_genes_name_personal_active', 'genes',
    [sa.text('lower(trim(name))'), 'created_by'],
    unique=True,
    postgresql_where=sa.text("deleted_at IS NULL AND visibility = 'personal'"),
)

# org：按 (小写trim后的name, org_id) 唯一，仅限 visibility='org_private'
op.create_index(
    'uq_genes_name_org_active', 'genes',
    [sa.text('lower(trim(name))'), 'org_id'],
    unique=True,
    postgresql_where=sa.text("deleted_at IS NULL AND visibility = 'org_private'"),
)

# public：按小写trim后的name全局唯一，仅限 visibility='public'
op.create_index(
    'uq_genes_name_public_active', 'genes',
    [sa.text('lower(trim(name))')],
    unique=True,
    postgresql_where=sa.text("deleted_at IS NULL AND visibility = 'public'"),
)
```

通过 `uv run alembic revision --autogenerate` 生成 revision（禁止手写 ID），随后检查自动生成的迁移是否准确表达上述 3 条索引（`autogenerate` 对函数表达式索引的识别不一定完整，需要人工核对/补充）。

**存量数据风险**：若线上已存在同 scope 同名的历史脏数据，建表迁移会失败。实施前先跑一次性检测查询（按 scope 分组 `lower(trim(name))` 找 `count > 1`），如果发现历史重名数据，将结果报告给用户决定如何处理（不做自动改名/删除，避免误伤不了解语义的历史数据）。

### 应用层预检查

`gene_service.py` 新增：

```python
async def get_gene_by_name_in_scope(
    db: AsyncSession,
    name: str,
    *,
    visibility: str,
    org_id: str | None = None,
    created_by: str | None = None,
) -> Gene | None:
    """按 (trim+忽略大小写的 name, scope) 精确定位一条未删除 gene，与新增的
    3 条 partial unique index 语义一一对应。用 first() 而非 scalar_one_or_none()
    ——理论上 scope 内不会有多条，但按项目既有踩坑经验（同 slug 跨 scope 并存过
    MultipleResultsFound），一律用 first() 更保守。
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
    # public：不再附加 org_id/created_by 条件，全局唯一
    result = await db.execute(stmt)
    return result.scalars().first()
```

`create_gene()` 在 slug 冲突检查之后、插入前调用：

```python
existing_name = await get_gene_by_name_in_scope(
    db, req.name, visibility=visibility or req.visibility,
    org_id=org_id, created_by=user_id,
)
if existing_name and not req.overwrite:
    raise ConflictError(f"技能名称 '{req.name}' 已存在")
```

（`overwrite=True` 复用已有的 slug 覆盖分支，不重复触发一次覆盖逻辑；两个检查共用同一个 `existing`/`overwrite` 判断入口，具体在实施阶段整理成一次性的"存在性判断 + 覆盖或拒绝"代码块。）

**DB 层兜底**：`db.add(gene); await db.commit()` 包一层：

```python
try:
    await db.commit()
except IntegrityError as e:
    await db.rollback()
    if "uq_genes_name_" in str(e.orig):
        raise ConflictError(f"技能名称 '{req.name}' 已存在") from e
    raise
```

> 说明：现有 slug 保护目前**没有**捕获 `IntegrityError`（纯靠应用层预检查，DB 唯一索引只是"理论上的最后防线"，真发生竞态会直接 500）。这次为 name 新增 `IntegrityError` 捕获是比现有 slug 保护更完善的做法，只作用于新增的 name 校验路径，不改动、不重构现有 slug 相关代码。

### 三个入口的接入

- **`/genes/manual`**：自动获得保护（检查内嵌 `create_gene`）
- **`/genes/upload-folder`**：循环内逐个调用 `create_gene`，命中同名会在该技能这一条抛错中止；批量上传里前面已成功入库的技能不回滚——这是现有 slug 冲突时就有的既有行为（非事务性批处理），本次不改变
- **`fork_gene_to_library`**：在 `gene_service.py:3522` 计算 `new_slug` 之前，先用目标 scope 的 `attrs["visibility"] / attrs["org_id"] / attrs["created_by"]` 调 `get_gene_by_name_in_scope`，命中 → `raise ConflictError(f"技能名称 '{source_name}' 已存在")`。原有"slug 自动加 `-fork-{uuid6}` 后缀"逻辑保留（万一 name 唯一但 slug 因历史原因冲突时兜底），但不再是唯一的重名规避手段

---

## 涉及文件

| 文件 | 改动类型 |
|---|---|
| `nodeskclaw-backend/alembic/versions/<new>.py` | 新增 3 条 partial unique index 迁移 |
| `nodeskclaw-backend/app/services/gene_service.py` | 新增 `get_gene_by_name_in_scope`；`create_gene()` 接入 name 检查 + `IntegrityError` 兜底；`fork_gene_to_library()` 接入 name 检查 |
| `nodeskclaw-backend/tests/test_gene_name_dedup.py`（新建） | 覆盖下方测试计划 |

---

## 测试计划

- personal 内同名（含 trim/大小写变体）→ `ConflictError`
- 不同用户 personal 同名 → 允许
- org 内同名 → `ConflictError`；不同 org 同名 → 允许
- public 内同名 → `ConflictError`
- fork 到已有同名的目标 scope → `ConflictError`（不再自动改名绕开）
- `overwrite=True` 时同名允许覆盖（软删旧记录）
- 并发竞态：mock DB 提交阶段抛 `IntegrityError`（约束名含 `uq_genes_name_`）→ 服务层正确转换为 `ConflictError`，且非该约束的其它 `IntegrityError` 原样抛出

---

## 不在范围内

- 不改动 `name` 字段类型/长度约束本身，只新增表达式唯一索引
- 不做"相似名称"模糊查重（如编辑距离），只做 trim+忽略大小写的精确匹配
- 不处理迁移前的存量重名脏数据清洗（发现即报告，不自动处理）
- 不改动现有 slug 唯一性保护的实现方式（不补 `IntegrityError` 捕获、不做任何重构）
