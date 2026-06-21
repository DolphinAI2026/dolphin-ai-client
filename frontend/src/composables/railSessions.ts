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
 * - builder/agent → /ai-chat/:id(KeepAlive 单例,组件内 watch route.params.id 切会话)
 * - code → /coding?conversation_id=N。coding 会话选中 ≠ 简单跳转(可能要解析 workspace),
 *   交给 CodingPage onMounted 消费 conversation_id;/coding 非 KeepAlive 且 key=fullPath,
 *   query 变化会整页重挂载 → onMounted 再跑一次恢复该会话/工作区。
 */
export function railSessionTarget(mode: AppMode, id: number): RailSessionTarget {
  if (mode === 'code') {
    return { path: '/coding', query: { conversation_id: String(id) } }
  }
  return { path: `/ai-chat/${id}` }
}

/** 当前路由是否正停在该会话上(高亮)。code 看 query.conversation_id,其余看 path。 */
export function isRailSessionActive(
  mode: AppMode,
  id: number,
  route: { path: string; query: Record<string, unknown> },
): boolean {
  if (mode === 'code') {
    return String(route.query?.conversation_id ?? '') === String(id)
  }
  return route.path === `/ai-chat/${id}`
}

/** 删除当前正在看的会话后,该回退到哪。 */
export function railSessionFallback(mode: AppMode): string {
  return mode === 'code' ? '/coding' : '/'
}
