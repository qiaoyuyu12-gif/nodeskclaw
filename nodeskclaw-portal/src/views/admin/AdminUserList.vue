<!-- 全局用户列表页：搜索框 + 分页表格 + 行点击进详情 + 重置密码 + 启用/禁用 -->
<template>
  <div class="p-6 space-y-4">
    <h2 class="text-2xl font-semibold">用户管理</h2>

    <!-- 搜索框 -->
    <input
      v-model="q"
      class="border border-border rounded-md px-3 py-1.5 text-sm w-64 bg-background focus:outline-none focus:ring-1 focus:ring-primary"
      placeholder="按 email / name 搜索"
      @keyup.enter="reload(1)"
    />

    <!-- 用户表格 -->
    <div class="rounded-lg border border-border overflow-hidden">
      <table class="w-full text-sm border-collapse">
        <thead class="bg-muted/50">
          <tr>
            <th class="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground uppercase tracking-wide w-[35%]">用户</th>
            <th class="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground uppercase tracking-wide w-[10%]">状态</th>
            <th class="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground uppercase tracking-wide w-[10%]">组织数</th>
            <th class="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground uppercase tracking-wide w-[20%]">创建时间</th>
            <th class="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground uppercase tracking-wide w-[25%]">操作</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-border">
          <tr
            v-for="u in users"
            :key="u.id"
            class="hover:bg-muted/30 cursor-pointer transition-colors"
            @click="$router.push(`/admin/users/${u.id}`)"
          >
            <td class="px-4 py-3">
              <div class="font-medium flex items-center gap-2">
                {{ u.name || '-' }}
                <span
                  v-if="u.is_super_admin"
                  class="text-xs px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-600 dark:text-amber-400 font-medium"
                >
                  超管
                </span>
              </div>
              <div class="text-xs text-muted-foreground">{{ u.email }}</div>
            </td>
            <td class="px-4 py-3">
              <span
                class="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium"
                :class="u.is_active
                  ? 'bg-green-500/15 text-green-600 dark:text-green-400'
                  : 'bg-muted text-muted-foreground'"
              >
                {{ u.is_active ? '启用' : '禁用' }}
              </span>
            </td>
            <td class="px-4 py-3 text-muted-foreground">{{ u.org_count }}</td>
            <td class="px-4 py-3 text-muted-foreground text-xs">{{ u.created_at }}</td>
            <td class="px-4 py-3" @click.stop>
              <div class="flex items-center gap-1.5">
                <button
                  class="text-xs px-2 py-1 rounded border border-border hover:border-primary/50 hover:text-primary transition-colors"
                  @click="onReset(u)"
                >
                  重置密码
                </button>
                <button
                  class="text-xs px-2 py-1 rounded border transition-colors"
                  :class="u.is_active
                    ? 'border-destructive/40 text-destructive hover:bg-destructive/10'
                    : 'border-border hover:border-primary/50 hover:text-primary'"
                  @click="onToggleActive(u)"
                >
                  {{ u.is_active ? '禁用' : '启用' }}
                </button>
              </div>
            </td>
          </tr>
          <tr v-if="users.length === 0">
            <td colspan="5" class="px-4 py-8 text-center text-sm text-muted-foreground">暂无用户</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 分页控件 -->
    <div class="flex gap-2 items-center text-sm">
      <button
        class="px-3 py-1 rounded border border-border text-sm disabled:opacity-40 hover:border-primary/50 hover:text-primary transition-colors"
        :disabled="page === 1"
        @click="reload(page - 1)"
      >
        上一页
      </button>
      <span class="text-muted-foreground">第 {{ page }} 页 / 共 {{ Math.ceil(total / pageSize) || 1 }} 页</span>
      <button
        class="px-3 py-1 rounded border border-border text-sm disabled:opacity-40 hover:border-primary/50 hover:text-primary transition-colors"
        :disabled="page * pageSize >= total"
        @click="reload(page + 1)"
      >
        下一页
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAdminApi, type AdminUser } from '@/services/adminApi'

const api = useAdminApi()
const q = ref('')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const users = ref<AdminUser[]>([])

async function reload(p = page.value) {
  page.value = p
  const res = await api.fetchUsers({ q: q.value || undefined, page: p, pageSize: pageSize.value })
  users.value = res.data
  total.value = res.pagination.total
}
onMounted(() => reload(1))

async function onReset(u: AdminUser) {
  if (!confirm(`为 ${u.email} 重置密码？将生成一次性临时密码。`)) return
  const { temp_password } = await api.resetUserPassword(u.id)
  window.alert(`临时密码：${temp_password}\n请复制并交付用户，关闭后无法再次查看。`)
}

async function onToggleActive(u: AdminUser) {
  await api.updateUser(u.id, { is_active: !u.is_active })
  await reload()
}
</script>
