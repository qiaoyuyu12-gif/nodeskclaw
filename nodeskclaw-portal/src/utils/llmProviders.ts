import type { ModelItem } from '@/components/shared/ModelSelect.vue'

export const PROVIDERS = ['minimax-openai', 'minimax-anthropic', 'openai', 'anthropic', 'gemini', 'openrouter', 'codex'] as const

export const PROVIDER_LABELS: Record<string, string> = {
  codex: 'Codex CLI',
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  gemini: 'Google Gemini',
  openrouter: 'OpenRouter',
  'minimax-openai': 'MiniMax-OpenAI (CN)',
  'minimax-anthropic': 'MiniMax-Anthropic (CN)',
}

export const PROVIDER_DEFAULT_URLS: Record<string, string> = {
  codex: '',
  openai: 'https://api.openai.com/v1',
  anthropic: 'https://api.anthropic.com',
  gemini: 'https://generativelanguage.googleapis.com/v1',
  openrouter: 'https://openrouter.ai/api/v1',
  'minimax-openai': 'https://api.minimaxi.com/v1',
  'minimax-anthropic': 'https://api.minimaxi.com/anthropic',
}

export const BUILTIN_PROVIDERS = new Set(['codex', 'openai', 'anthropic', 'gemini', 'openrouter'])
export const ALL_KNOWN_PROVIDERS: Set<string> = new Set([...PROVIDERS])

export const isCodexProvider = (provider: string) => provider === 'codex'

// SYNC: 与 nodeskclaw-backend/app/services/codex_provider.py CODEX_MODELS[0] 保持同步
export const DEFAULT_CODEX_MODEL: ModelItem = { id: 'gpt-5.4', name: 'gpt-5.4' }

export function defaultModelForProvider(provider: string): ModelItem | null {
  return isCodexProvider(provider) ? { ...DEFAULT_CODEX_MODEL } : null
}
