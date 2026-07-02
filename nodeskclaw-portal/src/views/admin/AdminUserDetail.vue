<!-- 用户详情页：基本信息 + 启用/禁用 + 重置密码 + 所属组织角色管理 -->
<template>
  <div class="p-6 space-y-6 max-w-3xl">
    <RouterLink to="/admin/users" class="text-sm text-muted-foreground hover:text-foreground">
      ← 返回用户列表
    </RouterLink>

    <div v-if="user" class="flex items-start justify-between">
      <div>
        <h2 class="text-2xl font-semibold flex items-center gap-2">
          {{ user.name || user.email }}
          <span
            v-if="user.is_super_admin"
            class="text-sm px-2 py-0.5 rounded bg-amber-500/15 text-amber-600 dark:text-amber-400 font-medium"
          >
            平台超管
          </span>
        </h2>
        <p class="text-sm text-muted-foreground mt-0.5">{{ user.email }}</p>
      </div>
      <button
        v-if="!user.is_super_admin"
        class="text-sm px-3 py-1.5 rounded border transition-colors"
        :class="user.is_active
          ? 'border-destructive/40 text-destructive hover:bg-destructive/10'
          : 'border-border hover:border-primary/50 hover:text-primary'"
        @click="toggleActive"
      >
        {{ user.is_active ? '禁用账号' : '启用账号' }}
      </button>
    </div>

    <!-- 基本信息 -->
    <div v-if="user" class="rounded-lg border border-border p-4">
      <dl class="grid grid-cols-2 gap-x-6 gap-y-2.5 text-sm">
        <dt class="text-muted-foreground">创建时间</dt>
        <dd>{{ user.created_at }}</dd>
        <dt class="text-muted-foreground">账号状态</dt>
        <dd>
          <span
            class="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium"
            :class="user.is_active
              ? 'bg-green-500/15 text-green-600 dark:text-green-400'
              : 'bg-muted text-muted-foreground'"
          >
            {{ user.is_active ? '正常' : '已禁用' }}
          </span>
        </dd>
        <dt class="text-muted-foreground">需强制改密</dt>
        <dd>{{ user.must_change_password ? '是' : '否' }}</dd>
        <dt class="text-muted-foreground">所属组织数</dt>
        <dd>{{ user.org_count }}</dd>
      </dl>
    </div>

    <!-- 重置密码 -->
    <div v-if="user">
      <button
        class="text-sm px-3 py-1.5 rounded border border-border hover:border-primary/50 hover:text-primary transition-colors"
        @click="onReset"
      >
        重置密码
      </button>
    </div>

    <!-- 所属组织及角色管理 -->
    <div v-if="user">
      <h3 class="text-base font-medium mb-3">所属组织</h3>
      <div class="rounded-lg border border-border overflow-hidden">
        <table class="w-full text-sm border-collapse">
          <thead class="bg-muted/50">
            <tr>
              <th class="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground uppercase tracking-wide w-[40%]">组织</th>
              <th class="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground uppercase tracking-wide w-[25%]">角色</th>
              <th class="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground uppercase tracking-wide w-[20%]">加入时间</th>
              <th class="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground uppercase tracking-wide w-[15%]">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-border">
            <tr v-for="m in userOrgs" :key="m.org_id" class="hover:bg-muted/30 transition-colors">
              <td class="px-4 py-3">
                <div class="font-medium">{{ m.org_name }}</div>
                <div class="text-xs text-muted-foreground">{{ m.org_slug }}</div>
              </td>
              <td class="px-4 py-3">
                <select
                  :value="m.role"
                  class="text-sm border border-border rounded px-2 py-1 bg-background focus:outline-none focus:ring-1 focus:ring-primary"
                  @change="onRoleChange(m, $event)"
                >
                  <option value="admin">admin（管理员）</option>
                  <option value="operator">operator（操作员）</option>
                  <option value="member">member（成员）</option>
                </select>
              </td>
              <td class="px-4 py-3 text-muted-foreground text-xs">{{ m.joined_at }}</td>
              <td class="px-4 py-3">
                <button
                  class="text-xs px-2.5 py-1 rounded border border-destructive/40 text-destructive hover:bg-destructive/10 transition-colors"
                  @click="onRemoveFromOrg(m)"
                >
                  移除
                </button>
              </td>
            </tr>
            <tr v-if="userOrgs.length === 0">
              <td colspan="4" class="px-4 py-8 text-center text-sm text-muted-foreground">未加入任何组织</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 临时密码弹窗 -->
    <div v-if="tempPwd" class="fixed inset-0 bg-background/80 flex items-center justify-center z-50">
      <div class="bg-card border border-border p-6 rounded-lg shadow-lg w-96 space-y-3">
        <h3 class="text-base font-semibold">临时密码（仅本次可见）</h3>
        <pre class="bg-muted px-3 py-2 rounded text-sm select-all font-mono">{{ tempPwd }}</pre>
        <div class="flex gap-2">
          <button
            class="text-sm px-3 py-1.5 rounded border border-border hover:border-primary/50 hover:text-primary transition-colors"
            @click="copy"
          >
            {{ copied ? '已复制' : '复制' }}
          </button>
          <button
            class="text-sm px-3 py-1.5 rounded border border-border disabled:opacity-40 transition-colors"
            :disabled="!copied"
            @click="close"
          >
            我已记下
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAdminApi, type AdminUser, type AdminUserOrg } from '@/services/adminApi'

interface Props { id: string }
const props = defineProps<Props>()

const api = useAdminApi()
const user = ref<AdminUser | null>(null)
const userOrgs = ref<AdminUserOrg[]>([])
const tempPwd = ref<string | null>(null)
const copied = ref(false)

onMounted(async () => {
  user.value = await api.fetchUser(props.id)
  userOrgs.value = await api.fetchUserOrgs(props.id)
})

async function toggleActive() {
  if (!user.value) return
  if (!confirm(`确认${user.value.is_active ? '禁用' : '启用'} ${user.value.email}？`)) return
  await api.updateUser(user.value.id, { is_active: !user.value.is_active })
  user.value = await api.fetchUser(props.id)
}

async function onRoleChange(m: AdminUserOrg, ev: Event) {
  const role = (ev.target as HTMLSelectElement).value as AdminUserOrg['role']
  await api.updateOrgMember(m.org_id, props.id, role)
  userOrgs.value = await api.fetchUserOrgs(props.id)
}

async function onRemoveFromOrg(m: AdminUserOrg) {
  if (!confirm(`将用户从组织「${m.org_name}」移除？`)) return
  await api.removeOrgMember(m.org_id, props.id)
  userOrgs.value = await api.fetchUserOrgs(props.id)
}

async function onReset() {
  if (!user.value) return
  if (!confirm(`为 ${user.value.email} 重置密码？`)) return
  const r = await api.resetUserPassword(user.value.id)
  tempPwd.value = r.temp_password
  copied.value = false
}

async function copy() {
  if (!tempPwd.value) return
  await navigator.clipboard.writeText(tempPwd.value)
  copied.value = true
}

function close() { tempPwd.value = null }
</script>
