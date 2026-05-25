// Admin API client for portal — calls EE admin endpoints when edition=ee.
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
    const res = await client.get('/admin/orgs')
    return res.data.data ?? []
  }

  async function fetchOrg(id: string): Promise<AdminOrg> {
    const res = await client.get(`/admin/orgs/${id}`)
    return res.data.data
  }

  async function createOrg(data: AdminOrgCreate): Promise<AdminOrg> {
    const res = await client.post('/admin/orgs', data)
    return res.data.data
  }

  async function updateOrg(id: string, data: AdminOrgUpdate): Promise<AdminOrg> {
    const res = await client.put(`/admin/orgs/${id}`, data)
    return res.data.data
  }

  async function deleteOrg(id: string): Promise<void> {
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