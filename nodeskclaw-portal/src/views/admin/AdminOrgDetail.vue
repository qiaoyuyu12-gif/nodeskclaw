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
        :class="active === t.value ? 'border-b-2 border-blue-600 text-blue-600' : 'text-muted-foreground'"
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
      <table class="w-full text-sm">
        <thead><tr><th>用户</th><th>角色</th><th>加入时间</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="m in members" :key="m.user_id">
            <td>{{ m.user_email || m.user_id }}</td>
            <td>
              <!-- 角色下拉，变更即时保存 -->
              <select :value="m.role" @change="onRoleChange(m, $event)">
                <option value="admin">admin</option>
                <option value="operator">operator</option>
                <option value="member">member</option>
              </select>
            </td>
            <td>{{ m.joined_at }}</td>
            <td><button @click="onRemove(m)">移除</button></td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- 功能开关：状态/来源/原因 + 强制开/关/恢复默认 -->
    <section v-else>
      <table class="w-full text-sm">
        <thead><tr><th>Feature</th><th>状态</th><th>来源</th><th>原因</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="f in features" :key="f.feature_id">
            <td>{{ f.feature_id }}</td>
            <td>{{ f.enabled ? '开' : '关' }}</td>
            <td>{{ f.source }}（默认 {{ f.default_enabled ? '开' : '关' }}）</td>
            <td>{{ f.reason ?? '-' }}</td>
            <td>
              <button @click="onSetFeature(f, true)">强制开</button>
              <button @click="onSetFeature(f, false)">强制关</button>
              <!-- 仅 override 来源才可恢复默认 -->
              <button v-if="f.source === 'override'" @click="onClearFeature(f)">恢复默认</button>
            </td>
          </tr>
        </tbody>
      </table>
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
]
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
