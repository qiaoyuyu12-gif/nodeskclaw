import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import AdminOrgDetail from './AdminOrgDetail.vue'

// 模拟 adminApi，返回固定的组织数据、空成员、空 feature 列表
vi.mock('@/services/adminApi', () => ({
  useAdminApi: () => ({
    fetchOrg: vi.fn().mockResolvedValue({
      id: 'o1', name: 'Org1', slug: 'org-1', plan: 'free', is_active: true,
      max_instances: 1, max_cpu_total: '4', max_mem_total: '8Gi',
      max_storage_total: '500Gi', max_collaboration_depth: 3,
      cluster_id: null, cluster_name: null, instance_count: 0,
      total_cpu: '0', total_mem: '0', storage_used: '0',
      created_at: '2026-05-01', updated_at: '2026-05-01',
    }),
    fetchOrgMembers: vi.fn().mockResolvedValue([]),
    fetchOrgFeatures: vi.fn().mockResolvedValue([]),
  }),
}))

describe('AdminOrgDetail', () => {
  it('renders all three tabs', async () => {
    const wrapper = mount(AdminOrgDetail, {
      props: { id: 'o1' },
      global: { stubs: ['router-link'] },
    })
    await new Promise(r => setTimeout(r, 10))
    expect(wrapper.text()).toContain('概览')
    expect(wrapper.text()).toContain('成员')
    expect(wrapper.text()).toContain('功能开关')
  })
})
