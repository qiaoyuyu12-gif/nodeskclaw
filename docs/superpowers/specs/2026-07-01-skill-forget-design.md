# 技能遗忘功能设计

**日期**：2026-07-01  
**状态**：已确认，待实施

---

## 问题描述

AI 员工（DeskClaw 实例）的技能列表中，以下两类技能无法被遗忘：

1. **Hub 技能（从基因市场安装）**：当 Pod 文件系统中存在技能文件，但数据库中无活跃的 `InstanceGene` 记录时，`GET /instances/{id}/skills` 返回 `instance_gene: null`。前端遗忘按钮被包裹在 `v-if="item.instance_gene"` 中，导致按钮不显示。

2. **Emerged 技能（AI 员工自主创建）**：类型为 `emerged` 的技能没有 `gene` 也没有 `instance_gene` 字段，前端卡片完全没有遗忘按钮。

---

## 解决方案（方案 A）

新增一个"按技能名称直接删除"的后端接口，覆盖所有无 `instance_gene` 的场景。有 `instance_gene` 的 Hub 技能继续走现有 `uninstall_gene` 流程。

---

## 后端设计

### 新接口：`DELETE /instances/{instance_id}/skills/{skill_name}`

**位置**：`nodeskclaw-backend/app/api/genes.py`

**权限**：复用现有 `get_current_org` 依赖，通过 `get_instance` 校验实例归属。

**流程**：

```
1. 校验 skill_name 格式（复用现有 _SAFE_SKILL_NAME 正则，仅允许 [a-zA-Z0-9_-]）
2. get_instance(instance_id, db, org_id) 校验实例归属
3. 连接 Pod 文件系统，调用：
   - adapter.remove_skill(fs, skill_name)
   - adapter.post_remove_cleanup(fs, skill_name)
4. 查库找对应 InstanceGene（通过 Gene.slug == skill_name 或 manifest skill.name == skill_name）
5. 若找到活跃 InstanceGene：
   - ig.soft_delete()
   - gene.install_count = max(0, gene.install_count - 1)
6. 记录 EvolutionEvent(event_type="forgotten", gene_name=skill_name, gene_slug=skill_name)
7. db.commit()
8. 触发实例重启（fire_task restart_instance）
9. 广播 WebSocket 事件（GENES_UPDATED）
10. 返回 {"deleted": true, "skill_name": skill_name}
```

**错误处理**：
- `skill_name` 格式非法 → 400 BadRequestError
- 实例不属于当前 org → 403/404（由 `get_instance` 处理）
- Pod 连接失败 → 502（由现有 remote_fs 错误处理覆盖）

**新增 Service 函数**：`gene_service.delete_skill_by_name(db, instance_id, skill_name, org_id)`

---

## 前端设计

### Store（`nodeskclaw-portal/src/stores/gene.ts`）

新增方法：

```typescript
async function deleteSkillByName(instanceId: string, skillName: string) {
  const res = await api.delete(`/instances/${instanceId}/skills/${skillName}`)
  return res.data.data
}
```

同时在 return 中暴露 `deleteSkillByName`。

### InstanceGenes.vue（`nodeskclaw-portal/src/views/InstanceGenes.vue`）

**`confirmForget` 函数改造**：按有无 `instance_gene` 分两条路：

```typescript
async function confirmForget() {
  if (!forgetTarget.value || !isConfirmed.value) return
  const ig = forgetTarget.value.instance_gene
  forgetting.value = true
  try {
    if (ig?.gene_id) {
      // 有 InstanceGene：走现有流程
      await store.uninstallGene(instanceId.value, ig.gene_id)
    } else {
      // 无 InstanceGene（hub 无记录 或 emerged）：按文件名删除
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

**Emerged 技能卡片**：在卡片右侧加遗忘按钮（`lines 482-505`）：

```html
<!-- 在 emerged 卡片右侧 -->
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

**Hub 技能卡（无 `instance_gene`）**：在 `v-if="item.instance_gene"` 的外层或并列加一个 else 分支，当无 `instance_gene` 时显示遗忘按钮：

```html
<!-- Hub 卡片右侧 actions -->
<div v-if="item.instance_gene" class="flex items-center gap-2 shrink-0">
  <!-- 现有按钮保持不变 -->
</div>
<!-- 新增：无 instance_gene 时的兜底遗忘按钮 -->
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

---

## 涉及文件

| 文件 | 改动类型 |
|------|---------|
| `nodeskclaw-backend/app/api/genes.py` | 新增 DELETE 端点 |
| `nodeskclaw-backend/app/services/gene_service.py` | 新增 `delete_skill_by_name` service 函数 |
| `nodeskclaw-portal/src/stores/gene.ts` | 新增 `deleteSkillByName` 方法 |
| `nodeskclaw-portal/src/views/InstanceGenes.vue` | 改造 `confirmForget`，新增 emerged/无IG 按钮 |

---

## 不在范围内

- Meta 遗忘流程（有 meta-learning 基因时让 Agent 决策）：新接口走直接删除，不触发 Agent 回调。Emerged 技能本来就没有对应 Gene 记录，没有 meta 流程可走。
- 批量遗忘
- i18n 新 key：复用现有 `instanceGenes.forget`、`instanceGenes.forgetSubmitted`、`instanceGenes.forgetFailed`
