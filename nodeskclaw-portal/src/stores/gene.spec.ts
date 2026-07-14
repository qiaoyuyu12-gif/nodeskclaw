// nodeskclaw-portal/src/stores/gene.spec.ts
// 验证 useGeneStore().forkGene 对 overwrite 参数的处理：
// 1. 显式传入 overwrite=true 时，POST body 必须携带 overwrite: true
// 2. 不传 overwrite（沿用旧的 2 参调用形式）时，POST body 必须携带默认值 overwrite: false
//    （保证旧调用方在新增该参数后行为不变，向后兼容）
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import api from '@/services/api'
import { useGeneStore } from './gene'

describe('gene store forkGene', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('posts overwrite: true when explicitly requested', async () => {
    const store = useGeneStore()
    await store.forkGene('gene-1', 'org', true)

    expect(api.post).toHaveBeenCalledWith('/genes/gene-1/fork', { target: 'org', overwrite: true })
  })

  it('defaults overwrite to false for the legacy 2-arg call form', async () => {
    const store = useGeneStore()
    await store.forkGene('gene-1', 'personal')

    expect(api.post).toHaveBeenCalledWith('/genes/gene-1/fork', { target: 'personal', overwrite: false })
  })
})
