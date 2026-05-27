<!-- nodeskclaw-portal/src/views/admin/AdminAuditLog.vue -->
<template>
  <div class="p-6 space-y-4">
    <h2 class="text-2xl font-semibold">审计日志</h2>

    <!-- 筛选区：actor 输入、action 下拉、时间范围、查询按钮 -->
    <div class="flex gap-2 text-sm">
      <input v-model="actor" placeholder="actor_id" class="border rounded px-2 py-1" />
      <select v-model="action" class="border rounded px-2 py-1">
        <option value="">所有动作</option>
        <option v-for="a in actionOptions" :key="a" :value="a">{{ a }}</option>
      </select>
      <input v-model="fromTs" type="datetime-local" class="border rounded px-2 py-1" />
      <input v-model="toTs" type="datetime-local" class="border rounded px-2 py-1" />
      <button @click="reload(1)" class="border px-3 py-1 rounded">查询</button>
    </div>

    <!-- 日志表格：时间 / 操作人 / 动作 / 目标 / 状态，点击行展开 details JSON -->
    <table class="w-full text-sm">
      <thead>
        <tr>
          <th class="text-left py-1">时间</th>
          <th class="text-left py-1">操作人</th>
          <th class="text-left py-1">动作</th>
          <th class="text-left py-1">目标</th>
          <th class="text-left py-1">状态</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="r in rows" :key="r.id">
          <!-- 主行：点击切换 details 展开/收起 -->
          <tr class="hover:bg-gray-50 cursor-pointer" @click="toggle(r.id)">
            <td class="py-1">{{ r.created_at }}</td>
            <td class="py-1">{{ r.actor_name ?? r.actor_id }}</td>
            <td class="py-1">{{ r.action }}</td>
            <td class="py-1">{{ r.target_type }}:{{ r.target_id }}</td>
            <td class="py-1">{{ r.details?.status ?? '-' }}</td>
          </tr>
          <!-- 展开行：以 pre 展示 details JSON，使用 Set 判断是否展开 -->
          <tr v-if="expanded.has(r.id)">
            <td colspan="5">
              <pre class="bg-gray-50 p-3 text-xs overflow-auto">{{ JSON.stringify(r.details, null, 2) }}</pre>
            </td>
          </tr>
        </template>
      </tbody>
    </table>

    <!-- 分页控件 -->
    <div class="flex gap-2 items-center text-sm">
      <button :disabled="page === 1" @click="reload(page - 1)" class="border px-2 py-1 rounded disabled:opacity-40">上一页</button>
      <span>第 {{ page }} 页 / {{ Math.ceil(total / pageSize) || 1 }}</span>
      <button :disabled="page * pageSize >= total" @click="reload(page + 1)" class="border px-2 py-1 rounded disabled:opacity-40">下一页</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAdminApi, type AdminAuditRow } from '@/services/adminApi'

const api = useAdminApi()

// 筛选条件
const actor = ref('')
const action = ref('')
const fromTs = ref('')
const toTs = ref('')

// 下拉选项：从后端拉取可用动作枚举
const actionOptions = ref<string[]>([])

// 表格数据和分页状态
const rows = ref<AdminAuditRow[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

// 展开状态：使用 Set 存储已展开行的 id，保证不可变更新
const expanded = ref<Set<string>>(new Set())

/** 加载指定页数据；筛选条件变化时传 p=1 重置到第一页 */
async function reload(p = page.value) {
  page.value = p
  const res = await api.fetchAuditLogs({
    actor: actor.value || undefined,
    action: action.value || undefined,
    from: fromTs.value || undefined,
    to: toTs.value || undefined,
    page: p,
    pageSize: pageSize.value,
  })
  rows.value = res.data
  total.value = res.pagination.total
}

/** 切换指定行的展开/收起状态（不可变 Set 更新） */
function toggle(id: string) {
  const next = new Set(expanded.value)
  next.has(id) ? next.delete(id) : next.add(id)
  expanded.value = next
}

onMounted(async () => {
  // 初始化：并行拉取动作选项和第一页日志
  actionOptions.value = await api.fetchAuditActions()
  await reload(1)
})
</script>
