import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '@/services/api'
import { useAuthStore } from './auth'

export interface OrgInfo {
  id: string
  name: string
  slug: string
  plan: string
  max_instances: number
  max_cpu_total: string
  max_mem_total: string
  max_storage_total: string
  max_collaboration_depth: number
  cluster_id: string | null
  cluster_name?: string | null
  is_active: boolean
  member_count: number
  created_at: string
  updated_at: string
}

export interface MemberInfo {
  id: string
  user_id: string
  org_id: string
  role: string
  is_super_admin: boolean
  user_name: string | null
  user_email: string | null
  user_avatar_url: string | null
  created_at: string
}

export interface OrgUsage {
  instance_count: number
  instance_limit: number
  cpu_used: string
  cpu_limit: string
  mem_used: string
  mem_limit: string
  storage_used: string
  storage_limit: string
}

export const useOrgStore = defineStore('org', () => {
  const currentOrg = ref<OrgInfo | null>(null)
  const myOrgs = ref<OrgInfo[]>([])
  const members = ref<MemberInfo[]>([])
  const usage = ref<OrgUsage | null>(null)
  const loading = ref(false)

  const currentOrgId = computed(() => currentOrg.value?.id ?? null)

  async function fetchMyOrg() {
    try {
      const res = await api.get('/orgs/my')
      const orgs: OrgInfo[] = res.data.data ?? []
      myOrgs.value = orgs

      const authStore = useAuthStore()
      if (authStore.user?.current_org_id) {
        currentOrg.value = orgs.find(o => o.id === authStore.user!.current_org_id) ?? null
      }
      if (!currentOrg.value && orgs.length > 0) {
        currentOrg.value = orgs[0]
      }
    } catch (e) {
      console.warn('[orgStore] fetchMyOrg 失败:', e)
    }
  }

  async function fetchCurrentOrg() {
    try {
      const res = await api.get('/orgs/current')
      currentOrg.value = res.data.data
    } catch (e) {
      console.warn('[orgStore] fetchCurrentOrg 失败:', e)
    }
  }

  // 切换当前组织：成功后整页 reload，让所有依赖 current_org_id 的 store
  // （实例列表、技能市场等）都用干净状态重新拉取，避免遗漏某个 store 没刷新
  // 导致旧组织数据残留
  async function switchOrg(orgId: string) {
    const res = await api.post(`/orgs/switch/${orgId}`)
    return res.data.data
  }

  async function updateOrgName(name: string) {
    const res = await api.put('/orgs/current/name', { name })
    currentOrg.value = res.data.data
    return res.data.data
  }

  async function updateCollaborationDepth(depth: number) {
    const res = await api.put('/orgs/current/collaboration-depth', { max_collaboration_depth: depth })
    currentOrg.value = res.data.data
    return res.data.data
  }

  // ── 成员管理 ──

  async function fetchMembers() {
    if (!currentOrgId.value) return
    loading.value = true
    try {
      const res = await api.get(`/orgs/${currentOrgId.value}/members`)
      members.value = res.data.data ?? []
    } finally {
      loading.value = false
    }
  }

  async function addMember(userId: string, role: string = 'member') {
    if (!currentOrgId.value) return
    const res = await api.post(`/orgs/${currentOrgId.value}/members`, { user_id: userId, role })
    members.value.push(res.data.data)
    return res.data.data
  }

  async function updateMemberRole(membershipId: string, role: string) {
    if (!currentOrgId.value) return
    const res = await api.put(`/orgs/${currentOrgId.value}/members/${membershipId}`, { role })
    const idx = members.value.findIndex(m => m.id === membershipId)
    if (idx >= 0) members.value[idx] = res.data.data
    return res.data.data
  }

  async function removeMember(membershipId: string) {
    if (!currentOrgId.value) return
    await api.delete(`/orgs/${currentOrgId.value}/members/${membershipId}`)
    members.value = members.value.filter(m => m.id !== membershipId)
  }

  // ── 用量 ──

  async function fetchUsage() {
    loading.value = true
    try {
      const res = await api.get('/billing/usage')
      usage.value = res.data.data
    } catch (err: unknown) {
      // billing 未实现时后端会返回 404；前端将 usage 置空，由模板隐藏用量卡片，避免页面崩溃
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 404) {
        usage.value = null
      } else {
        throw err
      }
    } finally {
      loading.value = false
    }
  }

  return {
    currentOrg,
    currentOrgId,
    myOrgs,
    members,
    usage,
    loading,
    fetchMyOrg,
    fetchCurrentOrg,
    switchOrg,
    updateOrgName,
    updateCollaborationDepth,
    fetchMembers,
    addMember,
    updateMemberRole,
    removeMember,
    fetchUsage,
  }
})
