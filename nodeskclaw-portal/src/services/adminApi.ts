// Admin API client for portal — calls EE admin endpoints when edition=ee,
// falls back to CE /organizations endpoint in CE mode.
import api from '@/services/api'
import type { AxiosInstance } from 'axios'

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

  return {
    fetchOrgs,
    fetchOrg,
    createOrg,
    updateOrg,
    deleteOrg,
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