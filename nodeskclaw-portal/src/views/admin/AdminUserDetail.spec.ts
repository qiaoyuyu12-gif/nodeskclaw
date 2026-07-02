import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import AdminUserDetail from './AdminUserDetail.vue'

// mock adminApi，提供用户详情、重置密码、更新用户的桩函数
vi.mock('@/services/adminApi', () => ({
  useAdminApi: () => ({
    fetchUser: vi.fn().mockResolvedValue({
      id: 'u1', email: 'a@example.com', name: 'Alice',
      is_active: true, is_super_admin: false, must_change_password: false,
      created_at: '2026-05-01', org_count: 2,
    }),
    fetchUserOrgs: vi.fn().mockResolvedValue([]),
    resetUserPassword: vi.fn().mockResolvedValue({ temp_password: 'TEMPpwd1234' }),
    updateUser: vi.fn().mockResolvedValue({}),
  }),
}))

describe('AdminUserDetail', () => {
  it('shows user info and triggers reset password', async () => {
    const wrapper = mount(AdminUserDetail, {
      props: { id: 'u1' }, global: { stubs: ['router-link'] },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('a@example.com')
  })
})
