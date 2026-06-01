import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import AdminOrgList from './AdminOrgList.vue'

// Mock adminApi
vi.mock('@/services/adminApi', () => ({
  useAdminApi: () => ({
    fetchOrgs: vi.fn().mockResolvedValue([
      {
        id: 'o1',
        name: 'Org1',
        slug: 'org-1',
        plan: 'free',
        is_active: true,
        max_instances: 1,
        max_cpu_total: '4',
        max_mem_total: '8Gi',
        max_storage_total: '500Gi',
        max_collaboration_depth: 3,
        cluster_id: null,
        cluster_name: null,
        instance_count: 0,
        total_cpu: '0',
        total_mem: '0',
        storage_used: '0',
        created_at: '2026-05-01',
        updated_at: '2026-05-01',
      },
    ]),
    createOrg: vi.fn(),
    updateOrg: vi.fn(),
    deleteOrg: vi.fn(),
  }),
}))

// Mock 依赖 composables
vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), warning: vi.fn() }),
}))
vi.mock('@/composables/useFeature', () => ({
  useFeature: () => ({ isEnabled: vi.fn().mockReturnValue(true) }),
}))
vi.mock('@/i18n/error', () => ({
  resolveApiErrorMessage: (_e: unknown, fallback: string) => fallback,
}))
vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (k: string) => k }),
}))
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

describe('AdminOrgList', () => {
  it('renders org rows', async () => {
    const wrapper = mount(AdminOrgList, {
      global: { stubs: ['router-link'] },
    })
    // 等待 fetchOrgs promise resolve
    await new Promise(r => setTimeout(r))
    expect(wrapper.text()).toContain('Org1')
  })

  it('edit button opens modal with prefilled data', async () => {
    const wrapper = mount(AdminOrgList, {
      global: { stubs: ['router-link'] },
    })
    await new Promise(r => setTimeout(r))

    // 点击编辑按钮
    const editBtn = wrapper.find('button[title="admin.common.edit"]')
    await editBtn.trigger('click')

    // 弹窗应显示并预填 name（找 placeholder 为 namePlaceholder 的输入框）
    expect(wrapper.text()).toContain('admin.orgs.editTitle')
    const nameInput = wrapper.find('input[placeholder="admin.orgs.namePlaceholder"]')
    expect((nameInput.element as HTMLInputElement).value).toBe('Org1')
  })
})
