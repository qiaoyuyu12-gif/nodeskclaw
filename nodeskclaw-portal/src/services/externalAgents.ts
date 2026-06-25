import api from './api'

// 附件基础信息（不含 URL）
export interface AttachmentItem {
  name: string
  size: number
  content_type: string
  storage_key: string
}

// 附件信息（含访问 URL，用于消息展示）
export interface AttachmentItemWithUrl extends AttachmentItem {
  url: string
}

// 附件上传接口返回结构
export interface AttachmentUploadResponse {
  storage_key: string
  name: string
  size: number
  content_type: string
  url: string
}

// 聊天会话
export interface ChatSession {
  id: string
  agent_id: string
  user_id: string
  org_id: string
  title: string | null
  created_at: string
  updated_at: string
}

// 聊天消息
export interface ChatMessage {
  id: string
  session_id: string
  role: 'user' | 'assistant'
  content: string
  attachments: AttachmentItemWithUrl[] | null
  created_at: string
}

export interface ExternalAgent {
  id: string
  org_id: string
  name: string
  description: string | null
  endpoint: string
  protocol: 'openai_compatible' | 'custom'
  capabilities: string[]
  icon_emoji: string | null
  theme_color: string | null
  is_reachable: boolean
  last_checked_at: string | null
  created_at: string
  updated_at: string
}

export interface ExternalAgentCreate {
  name: string
  endpoint: string
  api_key?: string
  protocol?: 'openai_compatible' | 'custom'
  description?: string
  capabilities?: string[]
  icon_emoji?: string
  theme_color?: string
}

export interface ExternalAgentUpdate {
  name?: string
  endpoint?: string
  api_key?: string
  protocol?: 'openai_compatible' | 'custom'
  description?: string
  capabilities?: string[]
  icon_emoji?: string
  theme_color?: string
}

export const externalAgentApi = {
  list: (): Promise<ExternalAgent[]> =>
    api.get<{ data: ExternalAgent[] }>('/external-agents').then((r) => r.data.data ?? []),

  create: (body: ExternalAgentCreate): Promise<ExternalAgent> =>
    api.post<{ data: ExternalAgent }>('/external-agents', body).then((r) => r.data.data),

  update: (id: string, body: ExternalAgentUpdate): Promise<ExternalAgent> =>
    api.patch<{ data: ExternalAgent }>(`/external-agents/${id}`, body).then((r) => r.data.data),

  remove: (id: string): Promise<void> =>
    api.delete(`/external-agents/${id}`).then(() => undefined),

  sync: (id: string): Promise<{ reachable: boolean; agent_id: string }> =>
    api
      .post<{ data: { reachable: boolean; agent_id: string } }>(`/external-agents/${id}/sync`)
      .then((r) => r.data.data),

  /** 向外部 Agent 发送消息，返回原生 Response 用于 SSE 流读取。 */
  async chatStream(
    agentId: string,
    message: string,
    sessionId: string,
    attachments?: AttachmentItemWithUrl[],
  ): Promise<Response> {
    const token = localStorage.getItem('portal_token')
    return fetch(`/api/v1/external-agents/${agentId}/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        message,
        session_id: sessionId,
        attachments: attachments ?? [],
      }),
    })
  },

  /** 上传附件到指定 Agent，返回附件元信息及访问 URL。 */
  async uploadAttachment(agentId: string, file: File): Promise<AttachmentUploadResponse> {
    const token = localStorage.getItem('portal_token')
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(`/api/v1/external-agents/${agentId}/attachments/upload`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: form,
    })
    if (!res.ok) throw new Error(`上传失败: ${res.status}`)
    const json = await res.json()
    return json.data as AttachmentUploadResponse
  },

  /** 获取指定 Agent 的会话列表。 */
  async listSessions(agentId: string): Promise<ChatSession[]> {
    const token = localStorage.getItem('portal_token')
    const res = await fetch(`/api/v1/external-agents/${agentId}/sessions`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!res.ok) throw new Error(`加载会话列表失败: ${res.status}`)
    const json = await res.json()
    return json.data as ChatSession[]
  },

  /** 为指定 Agent 创建新会话。 */
  async createSession(agentId: string): Promise<ChatSession> {
    const token = localStorage.getItem('portal_token')
    const res = await fetch(`/api/v1/external-agents/${agentId}/sessions`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!res.ok) throw new Error(`创建会话失败: ${res.status}`)
    const json = await res.json()
    return json.data as ChatSession
  },

  /** 删除指定 Agent 下的某条会话。 */
  async deleteSession(agentId: string, sessionId: string): Promise<void> {
    const token = localStorage.getItem('portal_token')
    await fetch(`/api/v1/external-agents/${agentId}/sessions/${sessionId}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    })
  },

  /** 获取指定会话的消息历史。 */
  async getMessages(agentId: string, sessionId: string): Promise<ChatMessage[]> {
    const token = localStorage.getItem('portal_token')
    const res = await fetch(
      `/api/v1/external-agents/${agentId}/sessions/${sessionId}/messages`,
      { headers: { Authorization: `Bearer ${token}` } },
    )
    if (!res.ok) throw new Error(`加载消息历史失败: ${res.status}`)
    const json = await res.json()
    return json.data as ChatMessage[]
  },
}
