import { describe, it, expect, vi } from 'vitest'
import { computed } from 'vue'
import { mount } from '@vue/test-utils'
import OrgInfo from './OrgInfo.vue'

const currentOrg = {
  id: 'org-a',
  name: 'Org A',
  slug: 'org-a',
  plan: 'free',
  max_instances: 1,
  max_cpu_total: '4',
  max_mem_total: '8Gi',
  max_storage_total: '500Gi',
  max_collaboration_depth: 3,
  cluster_id: null,
  cluster_name: null,
  is_active: true,
  member_count: 1,
  created_at: '2026-05-01',
  updated_at: '2026-05-01',
}

const myOrgs = [currentOrg, { ...currentOrg, id: 'org-b', name: 'Org B', slug: 'org-b' }]

let multiOrgEnabled = true
const switchOrgMock = vi.fn().mockResolvedValue({ id: 'org-b', name: 'Org B' })

vi.mock('@/stores/org', () => ({
  useOrgStore: () => ({
    currentOrg,
    myOrgs,
    usage: null,
    fetchCurrentOrg: vi.fn(),
    fetchMyOrg: vi.fn(),
    switchOrg: switchOrgMock,
    fetchUsage: vi.fn(),
  }),
}))
vi.mock('@/stores/cluster', () => ({
  useClusterStore: () => ({
    clusters: [],
    fetchClusters: vi.fn(),
  }),
}))
vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), warning: vi.fn() }),
}))
vi.mock('@/composables/useFeature', () => ({
  useEdition: () => ({ isEE: computed(() => false) }),
  useFeature: (id: string) => ({ isEnabled: computed(() => (id === 'multi_org' ? multiOrgEnabled : false)) }),
}))
vi.mock('@/i18n/error', () => ({
  resolveApiErrorMessage: (_e: unknown, fallback: string) => fallback,
}))

describe('OrgInfo 组织切换', () => {
  it('multi_org 未启用时不渲染切换组织的下拉/按钮', async () => {
    multiOrgEnabled = false
    const wrapper = mount(OrgInfo)
    await new Promise(r => setTimeout(r))

    expect(wrapper.find('select').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('orgSettings.switchOrgButton')
  })

  it('multi_org 启用时渲染下拉选项，选中当前组织时切换按钮禁用', async () => {
    multiOrgEnabled = true
    const wrapper = mount(OrgInfo)
    await new Promise(r => setTimeout(r))

    const select = wrapper.find('select')
    expect(select.exists()).toBe(true)
    expect(select.findAll('option')).toHaveLength(2)

    const button = wrapper.find('button.bg-primary.text-primary-foreground')
    expect((button.element as HTMLButtonElement).disabled).toBe(true)
  })

  it('选中其他组织后点击切换按钮，调用 switchOrg 并触发页面刷新', async () => {
    multiOrgEnabled = true
    const reloadSpy = vi.fn()
    Object.defineProperty(window, 'location', {
      value: { reload: reloadSpy },
      writable: true,
    })

    const wrapper = mount(OrgInfo)
    await new Promise(r => setTimeout(r))

    const select = wrapper.find('select')
    await select.setValue('org-b')

    const button = wrapper.find('button.bg-primary.text-primary-foreground')
    expect((button.element as HTMLButtonElement).disabled).toBe(false)
    await button.trigger('click')
    await new Promise(r => setTimeout(r))

    expect(switchOrgMock).toHaveBeenCalledWith('org-b')
    expect(reloadSpy).toHaveBeenCalled()
  })
})
