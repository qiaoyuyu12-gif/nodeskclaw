# Skill Forget 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为所有技能类型（Hub 无 InstanceGene、Emerged）添加遗忘功能，通过新增 `DELETE /instances/{id}/skills/{skill_name}` 接口覆盖现有 `uninstall_gene` 无法处理的场景。

**Architecture:** 后端新增 `delete_skill_by_name` service 函数和 DELETE API 端点，直接操作 Pod 文件系统删除技能目录，同时清理 DB 记录（若存在）。前端 store 增加 `deleteSkillByName` 方法，`InstanceGenes.vue` 在 emerged 卡片和无 instance_gene 的 hub 卡片上加遗忘按钮，复用现有 confirm dialog。

**Tech Stack:** Python 3.12 + FastAPI + SQLAlchemy（后端）、Vue 3 + TypeScript + Pinia（前端）

---

## 文件改动总览

| 文件 | 操作 |
|------|------|
| `nodeskclaw-backend/tests/test_delete_skill_by_name.py` | 新建（单元测试） |
| `nodeskclaw-backend/app/services/gene_service.py` | 修改（新增 `delete_skill_by_name`） |
| `nodeskclaw-backend/app/api/genes.py` | 修改（新增 DELETE 路由） |
| `nodeskclaw-portal/src/stores/gene.ts` | 修改（新增 `deleteSkillByName`） |
| `nodeskclaw-portal/src/views/InstanceGenes.vue` | 修改（改造 `confirmForget` + 新增按钮） |

---

### Task 1：后端 service 函数（TDD）

**Files:**
- Create: `nodeskclaw-backend/tests/test_delete_skill_by_name.py`
- Modify: `nodeskclaw-backend/app/services/gene_service.py`

- [ ] **Step 1.1：写失败测试**

新建文件 `nodeskclaw-backend/tests/test_delete_skill_by_name.py`：

```python
"""验证 delete_skill_by_name 的核心行为（单元测试，mock db + remote_fs）。

测试矩阵：
  - 技能存在，有活跃 InstanceGene → 删文件 + 软删 IG + install_count-1 + 记录 evolution
  - 技能存在，无 InstanceGene → 删文件 + 记录 evolution（不出错）
  - skill_name 格式非法 → BadRequestError（在 API 层校验，不进入 service）
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class _FakeGene:
    def __init__(self, gene_id: str, slug: str, install_count: int = 3):
        self.id = gene_id
        self.slug = slug
        self.name = f"Gene {slug}"
        self.manifest = None
        self.install_count = install_count


class _FakeInstanceGene:
    def __init__(self, ig_id: str, gene_id: str):
        self.id = ig_id
        self.gene_id = gene_id
        self.installed_version = "1.0.0"
        self.usage_count = 5
        self._deleted = False

    def soft_delete(self) -> None:
        self._deleted = True


class _FakeInstance:
    def __init__(self):
        self.id = "inst-1"
        self.runtime = "openclaw"


def _make_db(gene: _FakeGene | None, ig: _FakeInstanceGene | None) -> AsyncMock:
    """构造 mock db，按 delete_skill_by_name 的查询顺序返回预设值。

    查询顺序：
      1. select(InstanceGene, Gene) — 按 gene.slug == skill_name 找 IG
    """
    db = AsyncMock()
    db.commit = AsyncMock()
    db.add = MagicMock()

    ig_gene_result = MagicMock()
    if ig is not None and gene is not None:
        ig_gene_result.first.return_value = (ig, gene)
    else:
        ig_gene_result.first.return_value = None
    db.execute = AsyncMock(return_value=ig_gene_result)
    return db


@pytest.mark.asyncio
async def test_delete_skill_with_instance_gene():
    """技能有活跃 InstanceGene → 软删 IG，install_count 递减，提交。"""
    from app.services.gene_service import delete_skill_by_name

    gene = _FakeGene("gene-1", "my-skill", install_count=3)
    ig = _FakeInstanceGene("ig-1", "gene-1")
    instance = _FakeInstance()
    db = _make_db(gene, ig)

    mock_fs = AsyncMock()
    mock_adapter = MagicMock()
    mock_adapter.remove_skill = AsyncMock()
    mock_adapter.post_remove_cleanup = AsyncMock()

    # _fire_task 用 side_effect=lambda c: c.close() 防止 unawaited coroutine 警告
    with (
        patch("app.services.gene_service.get_instance", AsyncMock(return_value=instance)),
        patch("app.services.gene_service._get_gene_install_adapter", return_value=mock_adapter),
        patch("app.services.gene_service.remote_fs") as mock_rfs,
        patch("app.services.gene_service._record_evolution", AsyncMock()),
        patch("app.services.gene_service._fire_task", side_effect=lambda c: c.close()),
        patch("app.services.gene_service._get_instance_workspace_ids", AsyncMock(return_value=[])),
    ):
        mock_rfs.return_value.__aenter__ = AsyncMock(return_value=mock_fs)
        mock_rfs.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await delete_skill_by_name(db, "inst-1", "my-skill", org_id=None)

    assert result == {"deleted": True, "skill_name": "my-skill"}
    mock_adapter.remove_skill.assert_awaited_once_with(mock_fs, "my-skill")
    mock_adapter.post_remove_cleanup.assert_awaited_once_with(mock_fs, "my-skill")
    assert ig._deleted is True
    assert gene.install_count == 2  # 3 - 1
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_delete_skill_without_instance_gene():
    """技能无 InstanceGene → 只删文件，不报错。"""
    from app.services.gene_service import delete_skill_by_name

    instance = _FakeInstance()
    db = _make_db(gene=None, ig=None)

    mock_fs = AsyncMock()
    mock_adapter = MagicMock()
    mock_adapter.remove_skill = AsyncMock()
    mock_adapter.post_remove_cleanup = AsyncMock()

    with (
        patch("app.services.gene_service.get_instance", AsyncMock(return_value=instance)),
        patch("app.services.gene_service._get_gene_install_adapter", return_value=mock_adapter),
        patch("app.services.gene_service.remote_fs") as mock_rfs,
        patch("app.services.gene_service._record_evolution", AsyncMock()),
        patch("app.services.gene_service._fire_task", side_effect=lambda c: c.close()),
        patch("app.services.gene_service._get_instance_workspace_ids", AsyncMock(return_value=[])),
    ):
        mock_rfs.return_value.__aenter__ = AsyncMock(return_value=mock_fs)
        mock_rfs.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await delete_skill_by_name(db, "inst-1", "emerged-skill", org_id=None)

    assert result == {"deleted": True, "skill_name": "emerged-skill"}
    mock_adapter.remove_skill.assert_awaited_once_with(mock_fs, "emerged-skill")
    db.commit.assert_awaited()
```

- [ ] **Step 1.2：运行测试，确认失败**

```bash
cd nodeskclaw-backend
uv run pytest tests/test_delete_skill_by_name.py -v
```

预期：`ImportError` 或 `AttributeError: module has no attribute 'delete_skill_by_name'`

- [ ] **Step 1.3：在 `gene_service.py` 末尾实现 `delete_skill_by_name`**

打开 `nodeskclaw-backend/app/services/gene_service.py`，在文件末尾（`uninstall_gene` 函数之后，约第 2541 行后）添加：

```python
async def _restart_instance_bg(instance_id: str) -> None:
    """后台重启实例（独立 db session，避免使用请求上下文的 session）。"""
    from app.core.deps import async_session_factory
    from app.services.instance_service import restart_instance

    async with async_session_factory() as db:
        await restart_instance(instance_id, db)


async def delete_skill_by_name(
    db: AsyncSession,
    instance_id: str,
    skill_name: str,
    org_id: str | None = None,
) -> dict:
    """按技能名称直接从 Pod 删除技能目录，同时清理 DB 记录（若存在）。

    用于 emerged 技能和无活跃 InstanceGene 的 hub 技能。
    """
    instance = await get_instance(instance_id, db, org_id)

    # 查找匹配 skill_name 的 InstanceGene（通过 gene.slug == skill_name）
    ig_result = await db.execute(
        select(InstanceGene, Gene)
        .join(Gene, InstanceGene.gene_id == Gene.id)
        .where(
            InstanceGene.instance_id == instance_id,
            Gene.slug == skill_name,
            not_deleted(InstanceGene),
            Gene.deleted_at.is_(None),
        )
    )
    row = ig_result.first()
    ig: InstanceGene | None = row[0] if row else None
    gene: Gene | None = row[1] if row else None

    # 删除 Pod 文件系统中的技能目录
    adapter = _get_gene_install_adapter(instance.runtime)
    async with remote_fs(instance, db) as fs:
        await adapter.remove_skill(fs, skill_name)
        await adapter.post_remove_cleanup(fs, skill_name)

    # 清理 DB 记录（若存在）
    if ig is not None and gene is not None:
        ig.soft_delete()
        gene.install_count = max(0, gene.install_count - 1)

    gene_name = gene.name if gene else skill_name
    await _record_evolution(
        db, instance_id, EvolutionEventType.forgotten,
        gene_name,
        gene_slug=skill_name,
        gene_id=gene.id if gene else None,
        details={"method": "direct_by_name"},
    )
    await db.commit()

    ws_ids = await _get_instance_workspace_ids(db, instance_id)
    from app.api.workspaces import broadcast_event
    for ws_id in ws_ids:
        broadcast_event(ws_id, "gene:forgotten", {
            "instance_id": instance_id,
            "skill_name": skill_name,
            "gene_name": gene_name,
        })

    _fire_task(_restart_instance_bg(instance_id))
    logger.info("delete_skill_by_name: skill=%s instance=%s", skill_name, instance_id)
    return {"deleted": True, "skill_name": skill_name}
```

- [ ] **Step 1.4：运行测试，确认通过**

```bash
cd nodeskclaw-backend
uv run pytest tests/test_delete_skill_by_name.py -v
```

预期：`2 passed`

- [ ] **Step 1.5：提交**

```bash
git add nodeskclaw-backend/tests/test_delete_skill_by_name.py \
        nodeskclaw-backend/app/services/gene_service.py
git commit -m "feat(gene): 新增 delete_skill_by_name service 函数"
```

---

### Task 2：后端 API 端点

**Files:**
- Modify: `nodeskclaw-backend/app/api/genes.py`（在现有 skill 路由附近添加，约第 476 行后）

- [ ] **Step 2.1：写集成测试（smoke 级别）**

打开 `nodeskclaw-backend/tests/test_smoke.py`，在文件末尾追加：

```python
def test_delete_skill_route_exists():
    """确保 DELETE /instances/{id}/skills/{name} 路由已注册。"""
    from app.main import app
    from fastapi.testclient import TestClient

    routes = {r.path for r in app.routes}
    assert "/api/v1/instances/{instance_id}/skills/{skill_name}" in routes
```

- [ ] **Step 2.2：运行测试，确认失败**

```bash
cd nodeskclaw-backend
uv run pytest tests/test_smoke.py::test_delete_skill_route_exists -v
```

预期：`AssertionError`（路由不存在）

- [ ] **Step 2.3：在 `genes.py` 添加 DELETE 端点**

打开 `nodeskclaw-backend/app/api/genes.py`，在 `update_skill_content` 端点（`@router.put("/instances/{instance_id}/skills/{skill_name}/content")`）之后添加：

```python
@router.delete("/instances/{instance_id}/skills/{skill_name}")
async def delete_skill_by_name(
    instance_id: str,
    skill_name: str,
    db: AsyncSession = Depends(get_db),
    org_ctx=Depends(get_current_org),
):
    """按技能名称从 Pod 删除技能目录（支持 emerged 和无 InstanceGene 的 hub 技能）。"""
    if not _SAFE_SKILL_NAME.match(skill_name):
        raise BadRequestError(message="skill_name 包含非法字符")
    _current_user, org = org_ctx
    result = await gene_service.delete_skill_by_name(db, instance_id, skill_name, org_id=org.id)
    return ApiResponse(data=result)
```

- [ ] **Step 2.4：确认 `BadRequestError` 已在 `genes.py` 中导入**

查看文件顶部的 import：
```bash
grep -n "BadRequestError" nodeskclaw-backend/app/api/genes.py | head -3
```

若不在，找到 exceptions import 行（通常已有其他异常），补充 `BadRequestError`：
```python
from app.core.exceptions import ..., BadRequestError
```

- [ ] **Step 2.5：运行 smoke 测试，确认通过**

```bash
cd nodeskclaw-backend
uv run pytest tests/test_smoke.py::test_delete_skill_route_exists -v
```

预期：`1 passed`

- [ ] **Step 2.6：代码检查**

```bash
cd nodeskclaw-backend
uv run ruff check app/api/genes.py app/services/gene_service.py
```

预期：无错误。若有，执行 `uv run ruff check --fix ...` 后确认无剩余。

- [ ] **Step 2.7：提交**

```bash
git add nodeskclaw-backend/app/api/genes.py \
        nodeskclaw-backend/tests/test_smoke.py
git commit -m "feat(gene): 新增 DELETE /instances/{id}/skills/{skill_name} 端点"
```

---

### Task 3：前端 Store 新增 `deleteSkillByName`

**Files:**
- Modify: `nodeskclaw-portal/src/stores/gene.ts`

- [ ] **Step 3.1：在 `gene.ts` 中添加方法**

打开 `nodeskclaw-portal/src/stores/gene.ts`，在 `uninstallGene` 函数（约第 328 行）之后添加：

```typescript
async function deleteSkillByName(instanceId: string, skillName: string) {
  const res = await api.delete(`/instances/${instanceId}/skills/${skillName}`)
  return res.data.data
}
```

- [ ] **Step 3.2：在 return 对象中暴露 `deleteSkillByName`**

找到 return 块中 `uninstallGene,` 所在行（约第 583 行），在其下方添加：

```typescript
deleteSkillByName,
```

- [ ] **Step 3.3：运行前端类型检查**

```bash
cd nodeskclaw-portal
npm run build 2>&1 | grep -E "error TS|ERROR"
```

预期：无 TypeScript 错误。

- [ ] **Step 3.4：提交**

```bash
git add nodeskclaw-portal/src/stores/gene.ts
git commit -m "feat(portal): store 新增 deleteSkillByName 方法"
```

---

### Task 4：前端 UI — `confirmForget` 改造 + 新增按钮

**Files:**
- Modify: `nodeskclaw-portal/src/views/InstanceGenes.vue`

- [ ] **Step 4.1：改造 `confirmForget` 函数**

打开 `nodeskclaw-portal/src/views/InstanceGenes.vue`，定位到 `confirmForget` 函数（约第 183 行）。

将现有函数替换为：

```typescript
async function confirmForget() {
  if (!forgetTarget.value || !isConfirmed.value) return
  const ig = forgetTarget.value.instance_gene
  forgetting.value = true
  try {
    if (ig?.gene_id) {
      // 有 InstanceGene：走现有 uninstall_gene 流程
      await store.uninstallGene(instanceId.value, ig.gene_id)
    } else {
      // 无 InstanceGene（emerged 或 hub 无记录）：按文件名删除
      await store.deleteSkillByName(instanceId.value, forgetTarget.value.skill_name)
    }
    forgetTarget.value = null
    await store.fetchInstanceSkills(instanceId.value)
    toast.success(t('instanceGenes.forgetSubmitted'))
  } catch {
    toast.error(t('instanceGenes.forgetFailed'))
  } finally {
    forgetting.value = false
  }
}
```

- [ ] **Step 4.2：在 Hub 技能卡片中补充无 `instance_gene` 时的遗忘按钮**

在模板中找到 Hub 卡片的 actions 区域（约第 439 行），现有内容：

```html
<div v-if="item.instance_gene" class="flex items-center gap-2 shrink-0">
  <!-- 现有按钮 -->
</div>
```

在这个 `div` 紧后面（**同级**，不要嵌套）追加 `v-else` 分支：

```html
<div v-else class="flex items-center gap-2 shrink-0">
  <button
    class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs text-destructive border border-destructive/30 hover:bg-destructive/10 transition-colors"
    @click.stop="openForgetDialog(item)"
  >
    <Trash2 class="w-3.5 h-3.5" />
    {{ t('instanceGenes.forget') }}
  </button>
</div>
```

- [ ] **Step 4.3：在 Emerged 技能卡片中添加遗忘按钮**

定位到 Emerged 卡片（约第 482 行），现有结构：

```html
<!-- Emerged gene card -->
<div v-else class="flex items-start justify-between gap-4">
  <div class="min-w-0 flex-1">
    <!-- 内容区 -->
  </div>
</div>
```

在 `<div class="min-w-0 flex-1">` 之后（与之并列，在 `</div>` 外层 `div` 关闭前）添加：

```html
  <div class="flex items-center gap-2 shrink-0">
    <button
      class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs text-destructive border border-destructive/30 hover:bg-destructive/10 transition-colors"
      @click.stop="openForgetDialog(item)"
    >
      <Trash2 class="w-3.5 h-3.5" />
      {{ t('instanceGenes.forget') }}
    </button>
  </div>
```

- [ ] **Step 4.4：类型检查**

```bash
cd nodeskclaw-portal
npm run build 2>&1 | grep -E "error TS|ERROR"
```

预期：无 TypeScript 错误。

- [ ] **Step 4.5：运行前端单元测试**

```bash
cd nodeskclaw-portal
npm run test -- --run
```

预期：全部通过（或与现有失败数相同，无新失败）。

- [ ] **Step 4.6：提交**

```bash
git add nodeskclaw-portal/src/views/InstanceGenes.vue
git commit -m "feat(portal): 为 emerged 和无 IG 的 hub 技能添加遗忘按钮"
```

---

## 验证 Checklist

完成以上 4 个 Task 后，逐项确认：

- [ ] `uv run pytest tests/test_delete_skill_by_name.py -v` → 2 passed
- [ ] `uv run pytest tests/test_smoke.py::test_delete_skill_route_exists -v` → 1 passed
- [ ] `uv run ruff check app/api/genes.py app/services/gene_service.py` → 无错误
- [ ] `npm run build` → 无 TS 错误
- [ ] Emerged 技能卡片右侧出现"遗忘"按钮
- [ ] Hub 技能（无 instance_gene 时）卡片右侧出现"遗忘"按钮
- [ ] 点击按钮后打开确认 dialog，输入技能名称后可确认
- [ ] 确认后调用 `DELETE /instances/{id}/skills/{skill_name}`，刷新列表后技能消失
