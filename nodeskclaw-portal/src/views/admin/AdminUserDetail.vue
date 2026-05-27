<!-- nodeskclaw-portal/src/views/admin/AdminUserDetail.vue -->
<!-- 用户详情页：展示基本信息、状态切换（二次确认）、重置密码（临时密码弹窗） -->
<template>
  <div class="p-6 space-y-6 max-w-2xl">
    <!-- 返回列表 -->
    <RouterLink to="/admin/users" class="text-sm text-gray-500">← 返回用户列表</RouterLink>

    <!-- 用户邮箱标题 -->
    <h2 class="text-2xl font-semibold" v-if="user">{{ user.email }}</h2>

    <!-- 基本信息键值表 -->
    <dl v-if="user" class="grid grid-cols-2 gap-y-2 text-sm">
      <dt>姓名</dt><dd>{{ user.name ?? '-' }}</dd>
      <dt>创建时间</dt><dd>{{ user.created_at }}</dd>
      <dt>所属组织数</dt><dd>{{ user.org_count }}</dd>
      <dt>需强制改密</dt><dd>{{ user.must_change_password ? '是' : '否' }}</dd>
    </dl>

    <!-- 状态切换：启用 / 超管（勾选前弹二次确认） -->
    <div class="flex gap-3 items-center" v-if="user">
      <label class="flex items-center gap-2 text-sm">
        <input type="checkbox" :checked="user.is_active" @change="toggle('is_active')" />
        启用
      </label>
      <label class="flex items-center gap-2 text-sm">
        <input type="checkbox" :checked="user.is_super_admin" @change="toggle('is_super_admin')" />
        超管
      </label>
    </div>

    <!-- 重置密码按钮 -->
    <button class="border px-3 py-1 rounded" @click="onReset" v-if="user">重置密码</button>

    <!-- 临时密码弹窗：复制后才可关闭 -->
    <div v-if="tempPwd" class="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div class="bg-white p-6 rounded shadow w-96 space-y-3">
        <h3 class="text-lg font-semibold">临时密码（仅本次可见）</h3>
        <!-- 临时密码展示区，可全选复制 -->
        <pre class="bg-gray-100 px-3 py-2 select-all">{{ tempPwd }}</pre>
        <div class="flex gap-2">
          <!-- 点击复制到剪贴板，并标记 copied=true -->
          <button @click="copy" class="border px-3 py-1 rounded">复制</button>
          <!-- 必须先复制（copied=true）才能点击关闭 -->
          <button @click="close" :disabled="!copied" class="border px-3 py-1 rounded disabled:opacity-40">
            我已记下
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAdminApi, type AdminUser } from '@/services/adminApi'

// 接收路由传入的用户 id
interface Props { id: string }
const props = defineProps<Props>()

const api = useAdminApi()
const user = ref<AdminUser | null>(null)   // 当前用户数据
const tempPwd = ref<string | null>(null)   // 临时密码（弹窗展示用）
const copied = ref(false)                   // 是否已复制（守卫关闭按钮）

// 页面挂载时拉取用户详情
onMounted(async () => { user.value = await api.fetchUser(props.id) })

// 切换 is_active / is_super_admin，先弹二次确认再提交
async function toggle(key: 'is_active' | 'is_super_admin') {
  if (!user.value) return
  const newVal = !user.value[key]
  if (!confirm(`确认将 ${key}=${newVal}？`)) return
  await api.updateUser(user.value.id, { [key]: newVal } as any)
  // 刷新最新状态
  user.value = await api.fetchUser(props.id)
}

// 重置密码：二次确认 → 调接口 → 展示临时密码弹窗
async function onReset() {
  if (!user.value) return
  if (!confirm(`为 ${user.value.email} 重置密码？`)) return
  const r = await api.resetUserPassword(user.value.id)
  tempPwd.value = r.temp_password
  copied.value = false
}

// 复制临时密码到剪贴板，标记 copied
async function copy() {
  if (!tempPwd.value) return
  await navigator.clipboard.writeText(tempPwd.value)
  copied.value = true
}

// 关闭弹窗（必须 copied=true 才允许调用）
function close() { tempPwd.value = null }
</script>
