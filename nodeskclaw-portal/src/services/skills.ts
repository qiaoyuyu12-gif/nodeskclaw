import api from './api'

export interface KnowledgeBase {
  id: string
  org_id: string
  name: string
  ragflow_kb_id: string
  ragflow_endpoint: string
  source_type: 'doc' | 'system' | 'mixed'
  created_at: string
  updated_at: string
}

export interface KnowledgeBaseCreate {
  name: string
  ragflow_endpoint: string
  ragflow_kb_id: string
  api_key: string
  source_type: 'doc' | 'system' | 'mixed'
}

export interface KnowledgeBaseUpdate {
  name?: string
  ragflow_endpoint?: string
  ragflow_kb_id?: string
  api_key?: string
  source_type?: 'doc' | 'system' | 'mixed'
}

/** manifest 内联序列化结构：agent 命中时读取 */
export interface SkillManifest {
  entry?: string                      // 入口脚本文件名（tool 类型）
  scripts?: Record<string, string>    // {filename: 脚本内容}
  assets?: Record<string, string>     // {相对路径: 资源内容}
  references?: Record<string, string> // {相对路径: 参考资料内容}
}

export interface Skill {
  id: string
  org_id: string
  name: string
  type: 'rag_query' | 'gene' | 'composite' | 'tool' | 'prompt'
  kb_id: string | null
  config: Record<string, unknown>
  enabled: boolean
  description: string | null
  package_path: string | null
  /** 文件夹上传后内联序列化的完整 JSON，供 agent 直接命中使用 */
  manifest: SkillManifest | null
  created_at: string
}

export interface SkillCreate {
  name: string
  type: 'rag_query' | 'gene' | 'composite' | 'tool' | 'prompt'
  kb_id?: string
  config?: Record<string, unknown>
}

export interface SkillUpdate {
  name?: string
  kb_id?: string
  config?: Record<string, unknown>
  enabled?: boolean
}

export interface QueryResult {
  degraded: boolean
  message: string | null
  results: Array<{ content: string; score?: number; [key: string]: unknown }>
}

export const kbApi = {
  list: () =>
    api.get<{ data: KnowledgeBase[] }>('/knowledge-bases').then((r) => r.data.data),

  create: (body: KnowledgeBaseCreate) =>
    api.post<{ data: KnowledgeBase }>('/knowledge-bases', body).then((r) => r.data.data),

  update: (id: string, body: KnowledgeBaseUpdate) =>
    api.patch<{ data: KnowledgeBase }>(`/knowledge-bases/${id}`, body).then((r) => r.data.data),

  remove: (id: string) => api.delete(`/knowledge-bases/${id}`),
}

export const skillApi = {
  listAdmin: (type?: string) =>
    api
      .get<{ data: Skill[] }>('/skills', { params: type ? { skill_type: type } : {} })
      .then((r) => r.data.data),

  listMy: () => api.get<{ data: Skill[] }>('/skills/my').then((r) => r.data.data),

  create: (body: SkillCreate) =>
    api.post<{ data: Skill }>('/skills', body).then((r) => r.data.data),

  /** ZIP 压缩包上传（原有方式） */
  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.post<{ data: Skill }>('/skills/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then((r) => r.data.data)
  },

  /**
   * 文件夹上传：将 webkitdirectory 选中的所有文件发送到 /upload-folder。
   * 每个文件使用 webkitRelativePath 作为 filename（保留目录结构），
   * 后端自动剥离顶层文件夹名并序列化为 manifest JSON。
   */
  uploadFolder: (files: FileList) => {
    const form = new FormData()
    for (const file of Array.from(files)) {
      // webkitRelativePath 示例：my-skill/main.py，后端会剥离 my-skill/ 前缀
      const relPath = (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name
      form.append('files', file, relPath)
    }
    return api.post<{ data: Skill }>('/skills/upload-folder', form).then((r) => r.data.data)
  },

  update: (id: string, body: SkillUpdate) =>
    api.patch<{ data: Skill }>(`/skills/${id}`, body).then((r) => r.data.data),

  remove: (id: string) => api.delete(`/skills/${id}`),

  bind: (skillId: string, instanceId: string) =>
    api.post(`/skills/${skillId}/bind`, { instance_id: instanceId }),

  unbind: (skillId: string, instanceId: string) =>
    api.delete(`/skills/${skillId}/bind/${instanceId}`),

  query: (skillId: string, question: string) =>
    api
      .post<{ data: QueryResult }>(`/skills/${skillId}/query`, { question })
      .then((r) => r.data.data),
}
