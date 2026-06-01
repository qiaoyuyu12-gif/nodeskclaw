import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import AdminFeatureList from './AdminFeatureList.vue'

// mock adminApi，返回一条 feature 和一个组织
vi.mock('@/services/adminApi', () => ({
  useAdminApi: () => ({
    fetchFeatures: vi.fn().mockResolvedValue([{
      feature_id: 'knowledge_base', name: 'KB', description: '...',
      default_enabled: false, override_count: 2,
    }]),
    fetchFeatureOverrides: vi.fn().mockResolvedValue({
      data: [
        {
          org_id: 'org-1',
          org_name: 'Acme Corp',
          feature_id: 'knowledge_base',
          enabled: true,
          reason: '试点',
          set_by_user_id: 'user-1',
          set_by_name: '张三',
          set_at: '2026-05-28T10:00:00',
        },
      ],
      pagination: { page: 1, page_size: 20, total: 1 },
    }),
    fetchOrgs: vi.fn().mockResolvedValue([
      { id: 'org-2', name: 'Beta Inc', slug: 'beta' },
    ]),
  }),
}))

describe('AdminFeatureList', () => {
  it('renders feature rows with override count', async () => {
    const wrapper = mount(AdminFeatureList, { global: { stubs: ['router-link'] } })
    await flushPromises()
    // 表格行中包含 feature_id 和覆盖数量
    expect(wrapper.text()).toContain('knowledge_base')
    expect(wrapper.text()).toContain('2')
  })

  it('shows add override form when button is clicked', async () => {
    const wrapper = mount(AdminFeatureList, { global: { stubs: ['router-link'] } })
    await flushPromises()

    // 点击功能行打开抽屉
    const row = wrapper.find('tbody tr')
    await row.trigger('click')
    await flushPromises()

    // 抽屉打开后显示「+ 添加 override」按钮
    const addBtn = wrapper.find('button[onClick]')
    const buttons = wrapper.findAll('button')
    const addOverrideBtn = buttons.find(b => b.text().includes('添加 override'))
    expect(addOverrideBtn).toBeTruthy()

    // 点击按钮，表单应显示
    await addOverrideBtn!.trigger('click')
    await flushPromises()

    // 表单中应有「提交」按钮
    const submitBtn = wrapper.findAll('button').find(b => b.text() === '提交')
    expect(submitBtn).toBeTruthy()
  })

  it('displays org_name and set_by_name in override list', async () => {
    const wrapper = mount(AdminFeatureList, { global: { stubs: ['router-link'] } })
    await flushPromises()

    // 点击行打开抽屉
    const row = wrapper.find('tbody tr')
    await row.trigger('click')
    await flushPromises()

    // 列表中应显示 org_name（而非 org_id）和 set_by_name
    expect(wrapper.text()).toContain('Acme Corp')
    expect(wrapper.text()).toContain('张三')
  })
})
