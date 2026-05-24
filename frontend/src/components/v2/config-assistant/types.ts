// frontend/src/components/v2/config-assistant/types.ts
//
// 2026-05-24 拆分 ConfigAssistantPanel.vue 重构产物 (refactor #9).
// 共享类型定义 — 让 5 个子组件 + composables 复用同一份契约.

import type { ChangePlanPreview, ConfigChatToolTrace } from '@/api/configChat'

export interface ChatMsg {
  id: number
  role: 'user' | 'assistant'
  content: string
  change_plan?: ChangePlanPreview | null
  actions_summary?: string[]
  tool_trace?: ConfigChatToolTrace[]
  // streaming 状态相关（运行时动态加，TS optional 兼容）
  streaming?: boolean
  progressLog?: string[]
}

export interface Example {
  id: string
  text: string
}
