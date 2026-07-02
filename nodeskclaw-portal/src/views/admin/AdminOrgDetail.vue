<!-- 组织详情页 — Overview / Members / Features 三 tab -->
<template>
  <div class="p-6 space-y-6">
    <!-- 返回导航 -->
    <div class="flex items-center gap-2">
      <RouterLink to="/admin/orgs" class="text-sm text-muted-foreground hover:text-foreground">
        ← 返回组织列表
      </RouterLink>
    </div>
    <h2 class="text-2xl font-semibold" v-if="org">{{ org.name }}</h2>

    <!-- Tab 切换 -->
    <div class="flex gap-2 border-b">
      <button
        v-for="t in tabs"
        :key="t.value"
        class="px-3 py-2 text-sm"
        :class="active === t.value ? 'border-b-2 border-primary text-primary' : 'text-muted-foreground hover:text-foreground'"
        @click="active = t.value"
      >
        {{ t.label }}
      </button>
    </div>

    <!-- 概览：基础字段 + 配额用量 -->
    <section v-if="active === 'overview'" v-show="org">
      <dl class="grid grid-cols-2 gap-y-2 text-sm">
        <dt>Slug</dt><dd>{{ org?.slug }}</dd>
        <dt>Plan</dt><dd>{{ org?.plan }}</dd>
        <dt>实例数</dt><dd>{{ org?.instance_count }} / {{ org?.max_instances }}</dd>
        <dt>CPU</dt><dd>{{ org?.total_cpu }} / {{ org?.max_cpu_total }}</dd>
        <dt>内存</dt><dd>{{ org?.total_mem }} / {{ org?.max_mem_total }}</dd>
        <dt>存储</dt><dd>{{ org?.storage_used }} / {{ org?.max_storage_total }}</dd>
      </dl>
    </section>

    <!-- 成员：列表 + 角色下拉 + 移除按钮 -->
    <section v-else-if="active === 'members'">
      <div class="rounded-lg border border-border overflow-hidden">
        <table class="w-full text-sm border-collapse">
          <thead class="bg-muted/50">
            <tr>
              <th class="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground uppercase tracking-wide w-[40%]">用户</th>
              <th class="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground uppercase tracking-wide w-[15%]">角色</th>
              <th class="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground uppercase tracking-wide w-[25%]">加入时间</th>
              <th class="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground uppercase tracking-wide w-[20%]">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-border">
            <tr v-for="m in members" :key="m.user_id" class="hover:bg-muted/30 transition-colors">
              <td class="px-4 py-3">
                <div class="font-medium">{{ m.user_name || '-' }}</div>
                <div class="text-xs text-muted-foreground">{{ m.user_email || m.user_id }}</div>
              </td>
              <td class="px-4 py-3">
                <select
                  :value="m.role"
                  class="text-sm border border-border rounded px-2 py-1 bg-background focus:outline-none focus:ring-1 focus:ring-primary"
                  @change="onRoleChange(m, $event)"
                >
                  <option value="admin">admin</option>
                  <option value="operator">operator</option>
                  <option value="member">member</option>
                </select>
              </td>
              <td class="px-4 py-3 text-muted-foreground">{{ m.joined_at }}</td>
              <td class="px-4 py-3">
                <button
                  class="text-xs px-2.5 py-1 rounded border border-destructive/40 text-destructive hover:bg-destructive/10 transition-colors"
                  @click="onRemove(m)"
                >
                  移除
                </button>
              </td>
            </tr>
            <tr v-if="members.length === 0">
              <td colspan="4" class="px-4 py-8 text-center text-sm text-muted-foreground">暂无成员</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- 功能开关：状态/来源/原因 + 强制开/关/恢复默认 -->
    <section v-else>
      <div class="rounded-lg border border-border overflow-hidden">
        <table class="w-full text-sm border-collapse">
          <thead class="bg-muted/50">
            <tr>
              <th class="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground uppercase tracking-wide w-[25%]">Feature</th>
              <th class="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground uppercase tracking-wide w-[10%]">状态</th>
              <th class="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground uppercase tracking-wide w-[20%]">来源</th>
              <th class="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground uppercase tracking-wide w-[20%]">原因</th>
              <th class="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground uppercase tracking-wide w-[25%]">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-border">
            <tr v-for="f in features" :key="f.feature_id" class="hover:bg-muted/30 transition-colors">
              <td class="px-4 py-3 font-mono text-xs">{{ f.feature_id }}</td>
              <td class="px-4 py-3">
                <span
                  class="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium"
                  :class="f.enabled
                    ? 'bg-green-500/15 text-green-600 dark:text-green-400'
                    : 'bg-muted text-muted-foreground'"
                >
                  {{ f.enabled ? '开' : '关' }}
                </span>
              </td>
              <td class="px-4 py-3 text-muted-foreground">
                <span>{{ f.source }}</span>
                <span class="ml-1 text-xs">（默认 {{ f.default_enabled ? '开' : '关' }}）</span>
              </td>
              <td class="px-4 py-3 text-muted-foreground text-xs">{{ f.reason ?? '-' }}</td>
              <td class="px-4 py-3">
                <div class="flex items-center gap-1.5">
                  <button
                    class="text-xs px-2 py-1 rounded border border-border hover:border-primary/50 hover:text-primary transition-colors"
                    @click="onSetFeature(f, true)"
                  >
                    强制开
                  </button>
                  <button
                    class="text-xs px-2 py-1 rounded border border-border hover:border-destructive/50 hover:text-destructive transition-colors"
                    @click="onSetFeature(f, false)"
                  >
                    强制关
                  </button>
                  <button
                    v-if="f.source === 'override'"
                    class="text-xs px-2 py-1 rounded border border-border text-muted-foreground hover:text-foreground transition-colors"
                    @click="onClearFeature(f)"
                  >
                    恢复默认
                  </button>
                </div>
              </td>
            </tr>
            <tr v-if="features.length === 0">
              <td colspan="5" class="px-4 py-8 text-center text-sm text-muted-foreground">暂无功能开关数据</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAdminApi, type AdminOrg, type AdminOrgMember, type AdminOrgFeatureState } from '@/services/adminApi'

interface Props { id: string }
const props = defineProps<Props>()
const api = useAdminApi()

// tab 定义
const tabs = [
  { value: 'overview', label: '概览' },
  { value: 'members', label: '成员' },
  { value: 'features', label: '功能开关' },
] as const  // as const 让 value 成为字面量类型,与 active 的联合类型匹配
const active = ref<'overview' | 'members' | 'features'>('overview')

const org = ref<AdminOrg | null>(null)
const members = ref<AdminOrgMember[]>([])
const features = ref<AdminOrgFeatureState[]>([])

// 页面加载时并行拉取三类数据
onMounted(async () => {
  org.value = await api.fetchOrg(props.id)
  members.value = await api.fetchOrgMembers(props.id)
  features.value = await api.fetchOrgFeatures(props.id)
})

// 修改成员角色后刷新列表
async function onRoleChange(m: AdminOrgMember, ev: Event) {
  const role = (ev.target as HTMLSelectElement).value as AdminOrgMember['role']
  await api.updateOrgMember(props.id, m.user_id, role)
  members.value = await api.fetchOrgMembers(props.id)
}

// 移除成员后刷新列表
async function onRemove(m: AdminOrgMember) {
  if (!confirm(`移除 ${m.user_email}？`)) return
  await api.removeOrgMember(props.id, m.user_id)
  members.value = await api.fetchOrgMembers(props.id)
}

// 强制开/关 feature override
async function onSetFeature(f: AdminOrgFeatureState, enabled: boolean) {
  const reason = window.prompt('原因（可选）') || undefined
  await api.setOrgFeature(props.id, f.feature_id, enabled, reason)
  features.value = await api.fetchOrgFeatures(props.id)
}

// 清除 override，恢复 edition 默认值
async function onClearFeature(f: AdminOrgFeatureState) {
  await api.clearOrgFeature(props.id, f.feature_id)
  features.value = await api.fetchOrgFeatures(props.id)
}
</script>
