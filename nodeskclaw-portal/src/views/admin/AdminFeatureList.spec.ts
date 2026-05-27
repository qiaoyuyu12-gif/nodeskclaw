import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import AdminFeatureList from './AdminFeatureList.vue'

// mock adminApi，返回一条 feature 数据
vi.mock('@/services/adminApi', () => ({
  useAdminApi: () => ({
    fetchFeatures: vi.fn().mockResolvedValue([{
      feature_id: 'knowledge_base', name: 'KB', description: '...',
      default_enabled: false, override_count: 2,
    }]),
    fetchFeatureOverrides: vi.fn().mockResolvedValue({
      data: [], pagination: { page: 1, page_size: 20, total: 0 },
    }),
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
})
