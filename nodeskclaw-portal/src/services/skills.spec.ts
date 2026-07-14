// nodeskclaw-portal/src/services/skills.spec.ts
// 验证 skillApi.uploadFolder 对 version 参数的处理：
// 1. 传入非空 version 时，请求 URL 必须携带 version=<value>
// 2. 不传 version（undefined）时，请求 URL 不应出现 version 参数
import { describe, it, expect, vi, beforeEach } from 'vitest'
import api from './api'
import { skillApi } from './skills'

// 构造一个最小可用的 FileList：借助浏览器/DOM 实现的 DataTransfer 来生成真实 FileList 实例，
// 避免手写假对象导致 Array.from(files) 行为与真实环境不一致
function buildFileList(fileNames: string[]): FileList {
  const dataTransfer = new DataTransfer()
  for (const name of fileNames) {
    dataTransfer.items.add(new File(['content'], name))
  }
  return dataTransfer.files
}

describe('skillApi.uploadFolder', () => {
  // 每个用例前清空 mock 调用记录，避免上一个用例的调用参数串到下一个断言里
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('appends version to the URL when a version is provided', async () => {
    const files = buildFileList(['a.md'])
    await skillApi.uploadFolder(files, true, 'personal', '2.0.0')

    const postMock = api.post as ReturnType<typeof vi.fn>
    const calledUrl = postMock.mock.calls[0][0] as string
    expect(calledUrl).toContain('version=2.0.0')
    expect(calledUrl).toContain('overwrite=true')
    expect(calledUrl).toContain('target=personal')
  })

  it('omits version from the URL when no version is provided', async () => {
    const files = buildFileList(['a.md'])
    await skillApi.uploadFolder(files, false, 'personal')

    const postMock = api.post as ReturnType<typeof vi.fn>
    const calledUrl = postMock.mock.calls[0][0] as string
    expect(calledUrl).not.toContain('version=')
    expect(calledUrl).not.toContain('overwrite=')
  })

  it('omits version from the URL when version is an explicit empty string', async () => {
    // if (version) 的判空写法应把空字符串视为"未提供"，不应产出 version= 这种空值参数
    const files = buildFileList(['a.md'])
    await skillApi.uploadFolder(files, false, 'personal', '')

    const postMock = api.post as ReturnType<typeof vi.fn>
    const calledUrl = postMock.mock.calls[0][0] as string
    expect(calledUrl).not.toContain('version=')
  })
})
