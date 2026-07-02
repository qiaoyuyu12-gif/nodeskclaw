# Skill 下载功能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在技能市场列表页为每个 skill 卡片增加"下载到本地"按钮，点击后将 skill 打包为 ZIP 文件（格式与 upload-folder 完全对称）并触发浏览器下载。

**Architecture:** 后端新增 `GET /genes/{gene_slug}/download` 接口，从 Gene.manifest 字段反向重建文件树后用 Python `zipfile` 内存打包，返回 StreamingResponse。前端在 GeneMarket.vue 每张卡片右上角添加下载图标按钮，通过 fetch blob 触发浏览器文件保存。

**Tech Stack:** Python `zipfile` + `io.BytesIO`、FastAPI `StreamingResponse`、Vue 3 Composition API、lucide-vue-next `FolderDown` 图标

---

## 文件改动清单

| 文件 | 操作 | 职责 |
|------|------|------|
| `nodeskclaw-backend/app/api/genes.py` | 修改 | 新增 download 路由 |
| `nodeskclaw-portal/src/stores/gene.ts` | 修改 | 新增 downloadGene 函数 |
| `nodeskclaw-portal/src/views/GeneMarket.vue` | 修改 | 新增下载按钮及交互逻辑 |
| `nodeskclaw-portal/src/i18n/locales/zh-CN.ts` | 修改 | 新增下载按钮文案 |

---

## Task 1: 后端 — 新增 download 接口

**Files:**
- Modify: `nodeskclaw-backend/app/api/genes.py`

### 背景
Gene 的 `manifest` 字段（Text列，JSON字符串）包含完整文件内容：
- `manifest.skill.content` → SKILL.md 原文
- `manifest.scripts` → `{filename: content}` Python 脚本
- `manifest.assets` → `{relative_path: content}` 资源文件
- `manifest.references` → `{relative_path: content}` 参考资料

下载接口反向重建这些文件打包为 ZIP，结构与上传完全对称。

- [ ] **Step 1: 在 genes.py 顶部补充 import**

找到 genes.py 的现有 import 区块，在其中添加（如已有则跳过）：

```python
import io
import json
import zipfile

from fastapi.responses import StreamingResponse
```

- [ ] **Step 2: 在 `GET /genes/{gene_slug}` 接口之后插入 download 路由**

在 `genes.py` 中找到 `async def get_gene(gene_slug: str, ...)` 函数结束后，插入以下代码：

```python
@router.get("/genes/{gene_slug}/download")
async def download_gene(
    gene_slug: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """将技能打包为 ZIP 文件供下载，格式与 upload-folder 对称。"""
    # 复用现有可见性权限校验
    await gene_service._assert_user_can_view_gene_by_slug(db, gene_slug, current_user)

    # 直接查 ORM 对象以访问 manifest 字段
    from app.models.gene import Gene
    from app.models.base import not_deleted
    result = await db.execute(
        select(Gene).where(Gene.slug == gene_slug, not_deleted(Gene))
    )
    gene = result.scalars().first()
    if not gene:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("技能不存在", "errors.gene.not_found")

    manifest: dict = json.loads(gene.manifest or "{}")
    buf = io.BytesIO()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # SKILL.md
        skill_content: str = manifest.get("skill", {}).get("content", "")
        zf.writestr(f"{gene_slug}/SKILL.md", skill_content.encode("utf-8"))

        # Python 脚本（scripts 的键为纯文件名，如 main.py）
        for fname, content in manifest.get("scripts", {}).items():
            zf.writestr(f"{gene_slug}/{fname}", content.encode("utf-8"))

        # 资源文件（assets 的键为相对路径，如 assets/data.json）
        for rel_path, content in manifest.get("assets", {}).items():
            zf.writestr(f"{gene_slug}/{rel_path}", content.encode("utf-8"))

        # 参考资料（references 的键为相对路径，如 reference/guide.md）
        for rel_path, content in manifest.get("references", {}).items():
            zf.writestr(f"{gene_slug}/{rel_path}", content.encode("utf-8"))

    buf.seek(0)
    filename = f"{gene_slug}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

- [ ] **Step 3: 手动测试接口**

启动后端后，用 curl 或浏览器访问：
```
GET /api/v1/genes/{某个存在的gene_slug}/download
```
预期：返回 ZIP 文件，解压后有 `{slug}/SKILL.md`，内容与技能详情页一致。

- [ ] **Step 4: 提交**

```bash
git add app/api/genes.py
git commit -m "feat(gene): 新增 GET /genes/{slug}/download 接口，将 skill 打包为 ZIP"
```

---

## Task 2: 前端 Store — 新增 downloadGene 函数

**Files:**
- Modify: `nodeskclaw-portal/src/stores/gene.ts`

- [ ] **Step 1: 在 gene.ts 中找到现有 API 函数末尾，添加 downloadGene**

在 `forkGene` 或最后一个 async function 之后插入：

```typescript
async function downloadGene(slug: string): Promise<void> {
  // responseType blob 让 axios 返回二进制数据
  const response = await api.get(`/genes/${slug}/download`, { responseType: 'blob' })
  const url = URL.createObjectURL(response.data as Blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${slug}.zip`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
```

- [ ] **Step 2: 将 downloadGene 加入 store 的 return 对象**

找到 `return {` 块，添加 `downloadGene`：

```typescript
return {
  // ... 现有导出 ...
  downloadGene,
}
```

- [ ] **Step 3: 提交**

```bash
git add src/stores/gene.ts
git commit -m "feat(gene): store 新增 downloadGene，触发浏览器下载 ZIP"
```

---

## Task 3: 前端 UI — 技能卡片添加下载按钮

**Files:**
- Modify: `nodeskclaw-portal/src/views/GeneMarket.vue`

- [ ] **Step 1: 在 script setup 中引入 FolderDown 图标并声明状态**

在 GeneMarket.vue `<script setup>` 中找到已有的 lucide 图标 import（如 `import { Trash2, ... } from 'lucide-vue-next'`），添加 `FolderDown`：

```typescript
import { ..., FolderDown } from 'lucide-vue-next'
```

在现有的 `const forkingSlug = ref<string | null>(null)` 附近添加：

```typescript
const downloadingSlug = ref<string | null>(null)
```

- [ ] **Step 2: 添加 onDownloadGene 函数**

在现有 `onForkGene` 或 `onDeleteGene` 函数之后添加：

```typescript
async function onDownloadGene(gene: GeneItem) {
  if (downloadingSlug.value) return
  downloadingSlug.value = gene.slug
  try {
    await store.downloadGene(gene.slug)
  } catch (e) {
    console.error('下载技能失败', e)
  } finally {
    downloadingSlug.value = null
  }
}
```

- [ ] **Step 3: 在卡片 template 中添加下载按钮**

找到卡片内现有的删除按钮：
```vue
<button
  v-if="canDeleteGene(gene)"
  class="absolute top-2 right-2 p-1 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition z-10"
  ...
>
```

将其改为 `right-9`（向左移，为下载按钮让位），并在其**后面**插入下载按钮：

```vue
<!-- 删除按钮：有删除权限时显示，位置左移 -->
<button
  v-if="canDeleteGene(gene)"
  class="absolute top-2 right-9 p-1 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition z-10"
  :title="t('geneMarket.deleteGene')"
  @click.stop="onDeleteGene(gene)"
>
  <Trash2 class="w-4 h-4" />
</button>

<!-- 下载按钮：始终显示 -->
<button
  class="absolute top-2 right-2 p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition z-10"
  :title="t('geneMarket.downloadGene')"
  :disabled="downloadingSlug === gene.slug"
  @click.stop="onDownloadGene(gene)"
>
  <Loader2 v-if="downloadingSlug === gene.slug" class="w-4 h-4 animate-spin" />
  <FolderDown v-else class="w-4 h-4" />
</button>
```

- [ ] **Step 4: 确认 Loader2 已导入**

检查 lucide import 行是否包含 `Loader2`（卡片 Fork 按钮已用过它，通常已有）。若没有则添加：

```typescript
import { ..., Loader2, FolderDown } from 'lucide-vue-next'
```

- [ ] **Step 5: 提交**

```bash
git add src/views/GeneMarket.vue
git commit -m "feat(gene): 技能市场卡片添加下载到本地按钮"
```

---

## Task 4: i18n — 补充文案

**Files:**
- Modify: `nodeskclaw-portal/src/i18n/locales/zh-CN.ts`

- [ ] **Step 1: 找到 geneMarket 区块，添加 downloadGene 文案**

在 `zh-CN.ts` 中找到 `geneMarket: {` 块，在 `deleteGene` 附近添加：

```typescript
geneMarket: {
  // ... 现有文案 ...
  downloadGene: '下载到本地',
  // ...
}
```

- [ ] **Step 2: 提交**

```bash
git add src/i18n/locales/zh-CN.ts
git commit -m "feat(i18n): 新增技能下载按钮文案"
```

---

## 验证步骤

1. 启动后端和前端（`./dev.sh ce`）
2. 打开技能市场，能看到每张卡片右上角有 `FolderDown` 图标
3. 点击某个技能的下载按钮，浏览器弹出文件保存对话框，文件名为 `{slug}.zip`
4. 解压 ZIP，结构正确：`{slug}/SKILL.md` 内容与技能详情页一致
5. 将解压后的文件夹重新上传（`POST /genes/upload-folder`），能正常创建技能（验证对称性）
6. 点击期间按钮显示 loading spinner，完成后恢复正常
