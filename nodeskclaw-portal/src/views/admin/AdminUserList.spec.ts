import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import AdminUserList from './AdminUserList.vue'

// 模拟 adminApi 服务，返回一条测试用户数据
vi.mock('@/services/adminApi', () => ({
  useAdminApi: () => ({
    fetchUsers: vi.fn().mockResolvedValue({
      data: [{
        id: 'u1', email: 'a@example.com', name: null,
        is_active: true, is_super_admin: false, must_change_password: false,
        created_at: '2026-05-01', org_count: 2,
      }],
      pagination: { page: 1, page_size: 20, total: 1 },
    }),
  }),
}))

describe('AdminUserList', () => {
  it('renders users', async () => {
    const wrapper = mount(AdminUserList, { global: { stubs: ['router-link'] } })
    // 等待异步 fetchUsers 完成
    await new Promise(r => setTimeout(r, 10))
    expect(wrapper.text()).toContain('a@example.com')
  })
})
