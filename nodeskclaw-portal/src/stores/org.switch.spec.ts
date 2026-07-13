import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import api from '@/services/api'
import { useOrgStore } from './org'

describe('org store switchOrg', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('posts to the correct switch endpoint with the target org id', async () => {
    const store = useOrgStore()
    await store.switchOrg('org-b')

    expect(api.post).toHaveBeenCalledWith('/orgs/switch/org-b')
  })

  it('returns the switched org data from the response', async () => {
    ;(api.post as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      data: { code: 0, data: { id: 'org-b', name: 'Org B' } },
    })
    const store = useOrgStore()
    const result = await store.switchOrg('org-b')

    expect(result).toEqual({ id: 'org-b', name: 'Org B' })
  })
})
