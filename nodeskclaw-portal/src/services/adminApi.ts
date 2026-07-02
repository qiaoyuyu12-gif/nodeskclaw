// Admin API client for portal — calls EE admin endpoints when edition=ee,
// falls back to CE /organizations endpoint in CE mode.
import api from '@/services/api'
import type { AxiosInstance } from 'axios'

// ── 分页元数据 ─────────────────────────────────────────

interface AdminPagination {
  total: number
  page: number
  page_size: number
}

// ── 用户管理类型 ───────────────────────────────────────

export interface AdminUser {
  id: string
  email: string
  name: string
  is_active: boolean
  is_super_admin: boolean
  must_change_password: boolean
  created_at: string
  org_count: number
}

export interface AdminUserPatch {
  is_active?: boolean
}

// ── 用户组织成员关系 ────────────────────────────────────

export interface AdminUserOrg {
  org_id: string
  org_name: string
  org_slug: string
  role: OrgMemberRole
  joined_at: string
}

// ── 组织成员类型 ───────────────────────────────────────

export type OrgMemberRole = 'admin' | 'operator' | 'member'

export interface AdminOrgMember {
  user_id: string
  role: OrgMemberRole
  joined_at: string
  user_email: string
  user_name: string
}

// ── Feature 类型 ───────────────────────────────────────

export type FeatureSource = 'default' | 'override'

export interface AdminFeatureItem {
  feature_id: string
  name: string
  description: string
  default_enabled: boolean
  override_count: number
}

export interface AdminOrgFeatureState {
  feature_id: string
  enabled: boolean
  source: FeatureSource
  default_enabled: boolean
  reason?: string
  set_by_user_id?: string
  set_at?: string
}

// ── 审计日志类型 ───────────────────────────────────────

export interface AdminAuditRow {
  id: string
  action: string
  actor_id: string
  actor_name: string
  actor_type: string
  target_type: string
  target_id: string
  org_id: string
  details: Record<string, unknown>
  created_at: string
}

export interface AdminOrg {
  id: string
  name: string
  slug: string
  plan: string
  is_active: boolean
  max_instances: number
  max_cpu_total: string
  max_mem_total: string
  max_storage_total: string
  max_collaboration_depth: number
  cluster_id: string | null
  cluster_name: string | null
  instance_count: number
  total_cpu: string
  total_mem: string
  storage_used: string
  created_at: string
  updated_at: string
  member_count?: number
}

export interface AdminOrgCreate {
  name: string
  slug: string
  plan?: string
  max_instances?: number
  max_cpu_total?: string
  max_mem_total?: string
  max_storage_total?: string
  max_collaboration_depth?: number
  cluster_id?: string | null
}

export interface AdminOrgUpdate {
  name?: string
  plan?: string
  is_active?: boolean
  max_instances?: number
  max_cpu_total?: string
  max_mem_total?: string
  max_storage_total?: string
  max_collaboration_depth?: number
  cluster_id?: string | null
}

export function useAdminApi(http?: AxiosInstance) {
  const client = http ?? api

  async function fetchOrgs(): Promise<AdminOrg[]> {
    // CE mode: use /orgs endpoint
    const edition = await getEdition()
    if (edition === 'ce') {
      const res = await client.get('/orgs')
      const orgs = res.data.data ?? []
      // 映射 CE 数据结构到 AdminOrg 格式
      return orgs.map((org: any) => ({
        id: org.id,
        name: org.name,
        slug: org.slug,
        plan: org.plan || 'free',
        is_active: true,
        max_instances: org.max_instances || 1,
        max_cpu_total: org.max_cpu_total || '4',
        max_mem_total: org.max_mem_total || '8Gi',
        max_storage_total: org.max_storage_total || '500Gi',
        max_collaboration_depth: org.max_collaboration_depth || 3,
        cluster_id: org.cluster_id || null,
        cluster_name: org.cluster_name || null,
        instance_count: org.instance_count || 0,
        total_cpu: org.total_cpu || '0',
        total_mem: org.total_mem || '0',
        storage_used: org.storage_used || '0',
        created_at: org.created_at,
        updated_at: org.updated_at,
        member_count: org.member_count,
      }))
    }
    // EE mode: use /admin/orgs endpoint
    const res = await client.get('/admin/orgs')
    return res.data.data ?? []
  }

  async function fetchOrg(id: string): Promise<AdminOrg> {
    const edition = await getEdition()
    if (edition === 'ce') {
      const res = await client.get(`/orgs/${id}`)
      return res.data.data
    }
    const res = await client.get(`/admin/orgs/${id}`)
    return res.data.data
  }

  async function createOrg(data: AdminOrgCreate): Promise<AdminOrg> {
    const edition = await getEdition()
    if (edition === 'ce') {
      const res = await client.post('/orgs', data)
      return res.data.data
    }
    const res = await client.post('/admin/orgs', data)
    return res.data.data
  }

  async function updateOrg(id: string, data: AdminOrgUpdate): Promise<AdminOrg> {
    const edition = await getEdition()
    if (edition === 'ce') {
      const res = await client.put(`/orgs/${id}`, data)
      return res.data.data
    }
    const res = await client.put(`/admin/orgs/${id}`, data)
    return res.data.data
  }

  async function deleteOrg(id: string): Promise<void> {
    const edition = await getEdition()
    if (edition === 'ce') {
      await client.delete(`/orgs/${id}`)
      return
    }
    await client.delete(`/admin/orgs/${id}`)
  }

  // ── 用户管理 ──────────────────────────────────────────

  async function fetchUsers(params: {
    q?: string
    page?: number
    pageSize?: number
  }): Promise<{ data: AdminUser[]; pagination: AdminPagination }> {
    // 后端使用 page_size(snake_case),前端 pageSize → 显式转换避免参数被忽略
    const res = await client.get('/admin/users', {
      params: {
        q: params.q,
        page: params.page,
        page_size: params.pageSize,
      },
    })
    return res.data
  }

  async function fetchUser(id: string): Promise<AdminUser> {
    const res = await client.get(`/admin/users/${id}`)
    return res.data.data
  }

  async function updateUser(id: string, patch: AdminUserPatch): Promise<AdminUser> {
    const res = await client.put(`/admin/users/${id}`, patch)
    return res.data.data
  }

  async function resetUserPassword(id: string): Promise<{ temp_password: string }> {
    const res = await client.post(`/admin/users/${id}/reset-password`)
    return res.data.data
  }

  async function deleteUser(id: string): Promise<void> {
    await client.delete(`/admin/users/${id}`)
  }

  async function fetchUserOrgs(userId: string): Promise<AdminUserOrg[]> {
    const res = await client.get(`/admin/users/${userId}/orgs`)
    return res.data.data ?? []
  }

  // ── 组织成员管理 ───────────────────────────────────────

  async function fetchOrgMembers(orgId: string): Promise<AdminOrgMember[]> {
    const res = await client.get(`/admin/orgs/${orgId}/members`)
    return res.data.data ?? []
  }

  async function addOrgMember(
    orgId: string,
    userId: string,
    role: OrgMemberRole,
  ): Promise<AdminOrgMember> {
    const res = await client.post(`/admin/orgs/${orgId}/members`, { user_id: userId, role })
    return res.data.data
  }

  async function updateOrgMember(
    orgId: string,
    userId: string,
    role: OrgMemberRole,
  ): Promise<AdminOrgMember> {
    const res = await client.put(`/admin/orgs/${orgId}/members/${userId}`, { role })
    return res.data.data
  }

  async function removeOrgMember(orgId: string, userId: string): Promise<void> {
    await client.delete(`/admin/orgs/${orgId}/members/${userId}`)
  }

  // ── Feature 管理 ───────────────────────────────────────

  async function fetchFeatures(): Promise<AdminFeatureItem[]> {
    const res = await client.get('/admin/features')
    return res.data.data ?? []
  }

  async function fetchFeatureOverrides(
    featureId: string,
    page = 1,
    pageSize = 20,
  ): Promise<{ data: AdminOrgFeatureState[]; pagination: AdminPagination }> {
    const res = await client.get(`/admin/features/${featureId}/overrides`, {
      params: { page, page_size: pageSize },
    })
    return res.data
  }

  async function fetchOrgFeatures(orgId: string): Promise<AdminOrgFeatureState[]> {
    const res = await client.get(`/admin/orgs/${orgId}/features`)
    return res.data.data ?? []
  }

  async function setOrgFeature(
    orgId: string,
    featureId: string,
    enabled: boolean,
    reason?: string,
  ): Promise<AdminOrgFeatureState> {
    const res = await client.put(`/admin/orgs/${orgId}/features/${featureId}`, {
      enabled,
      reason,
    })
    return res.data.data
  }

  async function clearOrgFeature(orgId: string, featureId: string): Promise<AdminOrgFeatureState> {
    const res = await client.delete(`/admin/orgs/${orgId}/features/${featureId}`)
    return res.data.data
  }

  // ── 审计日志 ───────────────────────────────────────────

  async function fetchAuditActions(): Promise<string[]> {
    const res = await client.get('/admin/audit/actions')
    return res.data.data ?? []
  }

  async function fetchAuditLogs(params: {
    actor?: string
    action?: string
    from?: string
    to?: string
    page?: number
    pageSize?: number
  }): Promise<{ data: AdminAuditRow[]; pagination: AdminPagination }> {
    const res = await client.get('/admin/audit', { params })
    return res.data
  }

  return {
    fetchOrgs,
    fetchOrg,
    createOrg,
    updateOrg,
    deleteOrg,
    fetchUsers,
    fetchUser,
    updateUser,
    resetUserPassword,
    deleteUser,
    fetchUserOrgs,
    fetchOrgMembers,
    addOrgMember,
    updateOrgMember,
    removeOrgMember,
    fetchFeatures,
    fetchFeatureOverrides,
    fetchOrgFeatures,
    setOrgFeature,
    clearOrgFeature,
    fetchAuditActions,
    fetchAuditLogs,
  }
}

async function getEdition(): Promise<string> {
  try {
    const res = await api.get('/system/info')
    return res.data.edition ?? 'ce'
  } catch {
    return 'ce'
  }
}