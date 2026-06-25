import type { AIChatSession } from '@/api/aiChat'
import type { CodingConversation } from '@/api/coding'
import type { AppMode } from '@/stores/mode'

/**
 * 左栏会话项的归一形态。三模式共用全局左栏(参考 Claude Code 单一左栏):
 * builder/agent 模式展示 AI Builder 会话(aiChatApi),code 模式展示 coding 会话
 * (codingApi)——两套不同的会话系统,归一成同一形态后由 RailSidebar 统一分组渲染。
 */
export interface RailSession {
  id: number
  title: string
  updatedAt?: string
  /** 用于「按应用」分组(coding 会话暂无,落「未关联应用」) */
  appName?: string
}

export function normalizeAiSessions(sessions: AIChatSession[] | null | undefined): RailSession[] {
  return (sessions || []).map((s) => ({
    id: s.id,
    title: s.title || '未命名会话',
    updatedAt: s.updated_at ?? undefined,
    appName: s.generation?.app_name || undefined,
  }))
}

export function normalizeCodingSessions(conversations: CodingConversation[] | null | undefined): RailSession[] {
  return (conversations || []).map((c) => ({
    id: c.id,
    title: c.title || `开发会话 #${c.id}`,
    updatedAt: c.updated_at || c.created_at,
    appName: undefined,
  }))
}

export interface RailSessionTarget {
  path: string
  query?: Record<string, string>
}

/**
 * 点击左栏会话该导航去哪。
 * - 所有模式统一走 /ai-chat/:id(KeepAlive 单例,组件内 watch route.params.id 切会话)
 * - code 会话也走 /ai-chat/:id — AIChatPage 按 session.mode==='code' 自动挂 CodexPanelHost。
 */
export function railSessionTarget(_mode: AppMode, id: number): RailSessionTarget {
  return { path: `/ai-chat/${id}` }
}

/** 当前路由是否正停在该会话上(高亮)。统一看 /ai-chat/:id path。 */
export function isRailSessionActive(
  _mode: AppMode,
  id: number,
  route: { path: string; query: Record<string, unknown> },
): boolean {
  return route.path === `/ai-chat/${id}`
}

/** 删除当前正在看的会话后,该回退到哪。 */
export function railSessionFallback(_mode: AppMode): string {
  return '/'
}
