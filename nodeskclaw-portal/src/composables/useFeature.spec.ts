import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
// tests/setup.ts 里对 @/stores/auth 有全局 vi.mock（供其他组件测试使用的精简
// stub，不含 systemInfo 字段），会导致本文件里对 authStore.systemInfo 的赋值
// 被 useFeature/useEdition 内部各自新建的 mock 实例吞掉。这里显式 unmock 换回
// 真实 store + 真实 pinia，才能测到 systemInfo 的真实读值逻辑。
vi.unmock('@/stores/auth')
import { useAuthStore } from '@/stores/auth'
import { useFeature, useEdition } from './useFeature'

describe('useFeature', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('returns false when systemInfo is not loaded yet', () => {
    const { isEnabled } = useFeature('knowledge_base')
    expect(isEnabled.value).toBe(false)
  })

  it('EE edition + org override disabled -> isEnabled is false (not short-circuited to true)', () => {
    const authStore = useAuthStore()
    authStore.systemInfo = {
      edition: 'ee',
      version: '1.0.0',
      features: [{ id: 'knowledge_base', name: '知识库', enabled: false }],
    }
    const { isEnabled } = useFeature('knowledge_base')
    expect(isEnabled.value).toBe(false)
  })

  it('EE edition + feature enabled -> isEnabled is true', () => {
    const authStore = useAuthStore()
    authStore.systemInfo = {
      edition: 'ee',
      version: '1.0.0',
      features: [{ id: 'knowledge_base', name: '知识库', enabled: true }],
    }
    const { isEnabled } = useFeature('knowledge_base')
    expect(isEnabled.value).toBe(true)
  })

  it('feature not present in the list defaults to enabled (unregistered = uncontrolled)', () => {
    const authStore = useAuthStore()
    authStore.systemInfo = { edition: 'ee', version: '1.0.0', features: [] }
    const { isEnabled } = useFeature('unregistered_feature')
    expect(isEnabled.value).toBe(true)
  })
})

describe('useEdition', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('exposes the edition and isEE flag from systemInfo', () => {
    const authStore = useAuthStore()
    authStore.systemInfo = { edition: 'ee', version: '1.0.0', features: [] }
    const { edition, isEE } = useEdition()
    expect(edition.value).toBe('ee')
    expect(isEE.value).toBe(true)
  })
})
