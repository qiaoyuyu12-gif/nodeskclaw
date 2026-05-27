import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import AdminAuditLog from './AdminAuditLog.vue'

// mock adminApi，提供固定的审计动作列表和日志数据
vi.mock('@/services/adminApi', () => ({
  useAdminApi: () => ({
    fetchAuditActions: vi.fn().mockResolvedValue(['org.create', 'user.update']),
    fetchAuditLogs: vi.fn().mockResolvedValue({
      data: [{
        id: 'a1', action: 'org.create',
        actor_id: 'u1', actor_name: 'admin@example.com', actor_type: 'user',
        target_type: 'org', target_id: 'o1', org_id: 'o1',
        details: { status: 'success' },
        created_at: '2026-05-01T10:00:00Z',
      }],
      pagination: { page: 1, page_size: 20, total: 1 },
    }),
  }),
}))

describe('AdminAuditLog', () => {
  it('renders rows', async () => {
    const wrapper = mount(AdminAuditLog, { global: { stubs: ['router-link'] } })
    await flushPromises()
    // 表格中应显示动作名和操作人邮箱
    expect(wrapper.text()).toContain('org.create')
    expect(wrapper.text()).toContain('admin@example.com')
  })
})
