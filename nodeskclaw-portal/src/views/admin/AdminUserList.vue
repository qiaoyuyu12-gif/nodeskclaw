<!-- 全局用户列表页：搜索框 + 分页表格 + 行点击进详情 + 重置密码 + 启用/禁用 -->
<template>
  <div class="p-6 space-y-4">
    <h2 class="text-2xl font-semibold">用户管理</h2>
    <!-- 搜索框：回车触发重新加载 -->
    <input
      v-model="q"
      class="border rounded px-2 py-1 text-sm w-64"
      placeholder="按 email/name 搜索"
      @keyup.enter="reload(1)"
    />
    <table class="w-full text-sm">
      <thead><tr>
        <th>Email</th><th>姓名</th><th>超管</th><th>启用</th><th>所属组织数</th><th>创建时间</th><th>操作</th>
      </tr></thead>
      <tbody>
        <!-- 每行点击跳转用户详情；操作列阻止冒泡避免意外导航 -->
        <tr v-for="u in users" :key="u.id" class="hover:bg-gray-50 cursor-pointer"
            @click="$router.push(`/admin/users/${u.id}`)">
          <td>{{ u.email }}</td>
          <td>{{ u.name ?? '-' }}</td>
          <td>{{ u.is_super_admin ? '是' : '否' }}</td>
          <td>{{ u.is_active ? '是' : '否' }}</td>
          <td>{{ u.org_count }}</td>
          <td>{{ u.created_at }}</td>
          <td @click.stop>
            <button @click="onReset(u)">重置密码</button>
            <button @click="onToggleActive(u)">{{ u.is_active ? '禁用' : '启用' }}</button>
          </td>
        </tr>
      </tbody>
    </table>
    <!-- 分页控件 -->
    <div class="flex gap-2 items-center">
      <button :disabled="page === 1" @click="reload(page - 1)">上一页</button>
      <span class="text-sm">第 {{ page }} 页 / 共 {{ Math.ceil(total / pageSize) }} 页</span>
      <button :disabled="page * pageSize >= total" @click="reload(page + 1)">下一页</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAdminApi, type AdminUser } from '@/services/adminApi'

const api = useAdminApi()
// 搜索关键词、当前页、每页大小、总数、用户列表
const q = ref('')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const users = ref<AdminUser[]>([])

// 加载指定页数据，默认加载当前页
async function reload(p = page.value) {
  page.value = p
  const res = await api.fetchUsers({ q: q.value || undefined, page: p, pageSize: pageSize.value })
  users.value = res.data
  total.value = res.pagination.total
}
onMounted(() => reload(1))

// 重置密码：二次确认后调用接口，用 alert 展示临时密码（T24 UserDetail 有更精致弹窗）
async function onReset(u: AdminUser) {
  if (!confirm(`为 ${u.email} 重置密码？将生成一次性临时密码。`)) return
  const { temp_password } = await api.resetUserPassword(u.id)
  window.alert(`临时密码：${temp_password}\n请复制并交付用户，关闭后无法再次查看。`)
}

// 切换用户启用/禁用状态后刷新列表
async function onToggleActive(u: AdminUser) {
  await api.updateUser(u.id, { is_active: !u.is_active })
  await reload()
}
</script>
