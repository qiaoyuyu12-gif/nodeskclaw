import api from './api'

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
  chatStream: (
    id: string,
    messages: Array<{ role: string; content: string }>,
    sessionId?: string,
  ): Promise<Response> =>
    fetch(`/api/v1/external-agents/${id}/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${localStorage.getItem('portal_token') ?? ''}`,
      },
      body: JSON.stringify({ messages, session_id: sessionId }),
    }),
}
