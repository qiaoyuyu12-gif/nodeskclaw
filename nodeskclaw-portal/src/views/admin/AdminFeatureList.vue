<!-- 功能开关列表页：主表格 + 右侧抽屉展示 org override 详情 + 添加 override 表单 -->
<template>
  <div class="p-6 space-y-4">
    <h2 class="text-2xl font-semibold">功能开关</h2>

    <!-- 主功能列表表格，行点击打开覆盖抽屉 -->
    <table class="w-full text-sm">
      <thead>
        <tr class="text-left border-b">
          <th class="pb-2 pr-4">Feature</th>
          <th class="pb-2 pr-4">名称</th>
          <th class="pb-2 pr-4">描述</th>
          <th class="pb-2 pr-4">默认</th>
          <th class="pb-2">覆盖</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="f in features"
          :key="f.feature_id"
          class="hover:bg-muted/50 cursor-pointer border-b"
          @click="openDrawer(f)"
        >
          <td class="py-2 pr-4 font-mono text-xs">{{ f.feature_id }}</td>
          <td class="py-2 pr-4">{{ f.name }}</td>
          <td class="py-2 pr-4 text-muted-foreground">{{ f.description }}</td>
          <td class="py-2 pr-4">{{ f.default_enabled ? '开' : '关' }}</td>
          <td class="py-2">{{ f.override_count }} 个组织</td>
        </tr>
      </tbody>
    </table>

    <!-- 右侧抽屉：显示选中 feature 的 org override 列表 + 添加表单 -->
    <aside
      v-if="drawerFeature"
      class="fixed top-0 right-0 h-full w-[520px] bg-card shadow-xl border-l border-border p-6 overflow-auto z-50"
    >
      <!-- 抽屉标题栏：左侧标题、右侧添加按钮和关闭按钮 -->
      <div class="flex justify-between items-center mb-3">
        <h3 class="text-lg font-semibold">{{ drawerFeature.feature_id }} 的组织覆盖</h3>
        <div class="flex gap-2">
          <!-- 未展开表单时显示「+ 添加 override」按钮 -->
          <button
            v-if="!showAddForm"
            class="text-sm border border-border rounded px-3 py-1 hover:bg-muted"
            @click="onOpenAddForm"
          >
            + 添加 override
          </button>
          <button class="text-sm text-muted-foreground" @click="closeDrawer">关闭</button>
        </div>
      </div>

      <!-- 添加 override 内嵌表单：选组织 + 状态 + 理由 -->
      <div v-if="showAddForm" class="mb-4 p-3 border border-border rounded bg-muted/30">
        <div class="space-y-2">
          <!-- 组织选择：过滤掉已有 override 的组织 -->
          <div>
            <label class="text-xs text-muted-foreground">组织</label>
            <select
              v-model="addForm.orgId"
              class="w-full border border-border rounded px-2 py-1 bg-background text-sm"
            >
              <option value="">选择组织...</option>
              <option v-for="org in availableOrgs" :key="org.id" :value="org.id">
                {{ org.name }} ({{ org.slug }})
              </option>
            </select>
          </div>
          <!-- 状态选择：强制开 / 强制关 -->
          <div>
            <label class="text-xs text-muted-foreground">状态</label>
            <select
              v-model="addForm.enabled"
              class="w-full border border-border rounded px-2 py-1 bg-background text-sm"
            >
              <option :value="true">强制开</option>
              <option :value="false">强制关</option>
            </select>
          </div>
          <!-- 理由输入（可选） -->
          <div>
            <label class="text-xs text-muted-foreground">理由 (可选)</label>
            <input
              v-model="addForm.reason"
              type="text"
              placeholder="试点 / 临时关闭 ..."
              class="w-full border border-border rounded px-2 py-1 bg-background text-sm"
            />
          </div>
          <!-- 表单操作按钮：取消 / 提交 -->
          <div class="flex gap-2 justify-end">
            <button class="text-sm text-muted-foreground" @click="onCancelAddForm">取消</button>
            <button
              :disabled="!addForm.orgId || submitting"
              class="text-sm bg-primary text-primary-foreground rounded px-3 py-1 disabled:opacity-50"
              @click="onSubmitAddForm"
            >
              {{ submitting ? '提交中...' : '提交' }}
            </button>
          </div>
        </div>
      </div>

      <!-- 覆盖列表为空时的提示 -->
      <p v-if="overrides.length === 0" class="text-sm text-muted-foreground/70">暂无组织覆盖。</p>

      <!-- override 列表表格：显示 org_name 和 set_by_name 而非 ID -->
      <table v-else class="w-full text-sm">
        <thead>
          <tr class="text-left text-muted-foreground border-b border-border">
            <th class="py-2 pr-3">组织</th>
            <th class="pr-3">状态</th>
            <th class="pr-3">理由</th>
            <th class="pr-3">操作人</th>
            <th class="pr-3">时间</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="o in overrides" :key="o.org_id" class="border-b border-border/50">
            <!-- 优先显示 org_name，降级显示 org_id -->
            <td class="py-2 pr-3">{{ o.org_name || o.org_id }}</td>
            <td class="pr-3">{{ o.enabled ? '强制开' : '强制关' }}</td>
            <td class="pr-3 text-muted-foreground">{{ o.reason ?? '-' }}</td>
            <!-- 优先显示 set_by_name（操作人姓名/邮箱），降级显示 - -->
            <td class="pr-3 text-muted-foreground">{{ o.set_by_name ?? '-' }}</td>
            <td class="pr-3 text-muted-foreground/70 text-xs">{{ o.set_at }}</td>
            <!-- 清除该 org 的 feature override -->
            <td>
              <button class="text-destructive hover:underline text-xs" @click="onClear(o)">清除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </aside>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useAdminApi, type AdminFeatureItem, type AdminOrg } from '@/services/adminApi'

const api = useAdminApi()

// 功能列表数据
const features = ref<AdminFeatureItem[]>([])
// 当前打开抽屉对应的 feature，null 表示抽屉关闭
const drawerFeature = ref<AdminFeatureItem | null>(null)
// 当前抽屉中展示的 override 列表（含 org_name/set_by_name）
const overrides = ref<any[]>([])

// 全量组织列表，惰性加载（首次打开抽屉时拉取）
const allOrgs = ref<AdminOrg[]>([])

// 添加表单展示状态
const showAddForm = ref(false)
// 添加表单字段：组织 ID、是否开启、理由
const addForm = ref({ orgId: '', enabled: true, reason: '' })
// 表单提交中状态（防重复提交）
const submitting = ref(false)

// 可选组织：过滤掉已有 override 的组织，避免重复设置
const availableOrgs = computed(() => {
  const usedIds = new Set(overrides.value.map((o) => o.org_id))
  return allOrgs.value.filter((o) => !usedIds.has(o.id))
})

// 初始化加载所有 feature
onMounted(async () => {
  features.value = await api.fetchFeatures()
})

// 点击行：打开抽屉并拉取该 feature 的 org override 列表（含 org_name/set_by_name）
async function openDrawer(f: AdminFeatureItem) {
  drawerFeature.value = f
  showAddForm.value = false
  const res = await api.fetchFeatureOverrides(f.feature_id)
  overrides.value = res.data
  // 惰性加载组织列表：仅首次打开抽屉时拉取，避免重复请求
  if (allOrgs.value.length === 0) {
    allOrgs.value = await api.fetchOrgs()
  }
}

// 关闭抽屉并重置表单状态
function closeDrawer() {
  drawerFeature.value = null
  showAddForm.value = false
}

// 展开添加 override 表单并重置字段
function onOpenAddForm() {
  addForm.value = { orgId: '', enabled: true, reason: '' }
  showAddForm.value = true
}

// 取消添加，收起表单
function onCancelAddForm() {
  showAddForm.value = false
}

// 提交添加 override 表单
async function onSubmitAddForm() {
  if (!drawerFeature.value || !addForm.value.orgId) return
  submitting.value = true
  try {
    await api.setOrgFeature(
      addForm.value.orgId,
      drawerFeature.value.feature_id,
      addForm.value.enabled,
      addForm.value.reason || undefined,
    )
    showAddForm.value = false
    // 刷新抽屉数据 + 主表格 override_count
    await openDrawer(drawerFeature.value)
    features.value = await api.fetchFeatures()
  } catch (e: unknown) {
    const err = e as { response?: { data?: { message?: string } } }
    alert(err?.response?.data?.message || '添加失败')
  } finally {
    submitting.value = false
  }
}

// 清除某 org 的 override，之后刷新抽屉和主表格
async function onClear(o: any) {
  if (!drawerFeature.value) return
  if (!confirm(`确认清除 ${o.org_name || o.org_id} 的 override?`)) return
  try {
    await api.clearOrgFeature(o.org_id, drawerFeature.value.feature_id)
    await openDrawer(drawerFeature.value)
    // 刷新主表格 override_count
    features.value = await api.fetchFeatures()
  } catch (e: unknown) {
    const err = e as { response?: { data?: { message?: string } } }
    alert(err?.response?.data?.message || '清除失败')
  }
}
</script>
