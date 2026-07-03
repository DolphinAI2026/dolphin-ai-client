import type { AIChatSession } from '@/api/aiChat'
import type { CodeRailHistoryResponse } from '@/api/codeRuntime'
import type { CodingConversation } from '@/api/coding'
import type { AppMode } from '@/stores/mode'

/**
 * 左栏会话项的归一形态。三模式共用全局左栏(参考 Claude Code 单一左栏):
 * builder/agent 模式展示 AI Builder 会话(aiChatApi),code 模式展示 coding 会话
 * (codingApi)——两套不同的会话系统,归一成同一形态后由 RailSidebar 统一分组渲染。
 */
export interface RailSession {
  id: number | string
  title: string
  updatedAt?: string
  /** 用于「按应用」分组(coding 会话暂无,落「未关联应用」) */
  appName?: string
  source?: 'ai-chat' | 'code-agent' | 'code-shell'
  shellSessionId?: number
  runtimeSessionId?: string
  current?: boolean
}

export function normalizeAiSessions(
  sessions: AIChatSession[] | null | undefined,
  appNameById?: Map<number, string>,
): RailSession[] {
  const input = sessions || []
  const latestByExternalApp = new Map<string, AIChatSession>()

  for (const session of input) {
    const key = codeExternalAppKey(session)
    if (!key) continue
    const prev = latestByExternalApp.get(key)
    if (!prev || compareSessionFreshness(session, prev) > 0) {
      latestByExternalApp.set(key, session)
    }
  }

  const emittedExternalApps = new Set<string>()
  const deduped: AIChatSession[] = []
  for (const session of input) {
    const key = codeExternalAppKey(session)
    if (!key) {
      deduped.push(session)
      continue
    }
    if (emittedExternalApps.has(key)) continue
    emittedExternalApps.add(key)
    deduped.push(latestByExternalApp.get(key) || session)
  }

  return deduped.map((s) => ({
    id: s.id,
    title: s.title || '未命名会话',
    updatedAt: s.updated_at ?? undefined,
    // Builder 用生成产出的应用名 / 本地 app_id 反查；Code 用 d-ai-code 外部应用名。
    appName: s.generation?.app_name || s.external_app_name || (s.app_id ? appNameById?.get(s.app_id) : undefined) || undefined,
  }))
}

function codeExternalAppKey(session: AIChatSession): string {
  if (session.mode !== 'code') return ''
  return String(session.external_application_id || '').trim()
}

function compareSessionFreshness(a: AIChatSession, b: AIChatSession): number {
  const at = a.updated_at ? Date.parse(a.updated_at) : 0
  const bt = b.updated_at ? Date.parse(b.updated_at) : 0
  if (Number.isFinite(at) && Number.isFinite(bt) && at !== bt) return at - bt
  return Number(a.id || 0) - Number(b.id || 0)
}

export function normalizeCodingSessions(conversations: CodingConversation[] | null | undefined): RailSession[] {
  return (conversations || []).map((c) => ({
    id: c.id,
    title: c.title || `开发会话 #${c.id}`,
    updatedAt: c.updated_at || c.created_at,
    appName: undefined,
  }))
}

export function normalizeCodeRailHistory(history: CodeRailHistoryResponse | null | undefined): RailSession[] {
  const apps = history?.apps || []
  const out: RailSession[] = []
  for (const app of apps) {
    const shellSessionId = Number(app.shell_session_id)
    if (!Number.isFinite(shellSessionId) || shellSessionId <= 0) continue
    const appName = String(app.app_name || app.app_code || app.external_application_id || '未关联应用').trim()
    const runtimeSessions = app.sessions || []
    if (!runtimeSessions.length) {
      out.push({
        id: shellSessionId,
        title: `${appName} Code`,
        updatedAt: undefined,
        appName,
        shellSessionId,
        runtimeSessionId: undefined,
        current: false,
        source: 'code-shell',
      })
      continue
    }
    for (const session of runtimeSessions) {
      const runtimeSessionId = String(session.runtimeSessionId || '').trim()
      if (!runtimeSessionId || session.deletedAt) continue
      const title = String(session.title || '').trim() || fallbackRuntimeSessionTitle(runtimeSessionId)
      out.push({
        id: runtimeSessionId,
        title,
        updatedAt: session.lastActiveAt || session.updatedAt || session.createdAt || undefined,
        appName,
        shellSessionId,
        runtimeSessionId,
        current: Boolean(session.current),
        source: 'code-agent',
      })
    }
  }
  return out
}

function fallbackRuntimeSessionTitle(runtimeSessionId: string): string {
  const suffix = runtimeSessionId.replace(/^runtime-/, '').slice(0, 8)
  return suffix ? `会话 ${suffix}` : '新会话'
}

export interface RailSessionTarget {
  path: string
  query?: Record<string, string>
}

type RailSessionLike = RailSession | number

/**
 * 点击左栏会话该导航去哪。
 * - Builder/Agent 走 /ai-chat/:id
 * - Code 会话走 /code/:id，主区嵌入 d-ai-code Builder Runtime。
 */
export function railSessionTarget(mode: AppMode, session: RailSessionLike): RailSessionTarget {
  const item = typeof session === 'object' ? session : { id: session }
  if (mode === 'code' && isCodeAgentRailSession(item)) {
    return { path: `/code/${item.shellSessionId}`, query: { agent: item.runtimeSessionId } }
  }
  return { path: mode === 'code' ? `/code/${item.id}` : `/ai-chat/${item.id}` }
}

/** 当前路由是否正停在该会话上(高亮)。 */
export function isRailSessionActive(
  mode: AppMode,
  session: RailSessionLike,
  route: { path: string; query: Record<string, unknown> },
): boolean {
  const item = typeof session === 'object' ? session : { id: session }
  if (mode === 'code' && isCodeAgentRailSession(item)) {
    const activeAgent = route.query.agent
    return route.path === `/code/${item.shellSessionId}`
      && (activeAgent === item.runtimeSessionId || (!activeAgent && Boolean(item.current)))
  }
  return route.path === (mode === 'code' ? `/code/${item.id}` : `/ai-chat/${item.id}`)
}

function isCodeAgentRailSession(session: RailSession | { id: number | string }): session is RailSession & {
  source: 'code-agent'
  shellSessionId: number
  runtimeSessionId: string
} {
  return 'source' in session
    && session.source === 'code-agent'
    && Number.isFinite(Number(session.shellSessionId))
    && Boolean(session.runtimeSessionId)
}

/** 删除当前正在看的会话后,该回退到哪。 */
export function railSessionFallback(mode: AppMode): string {
  return mode === 'code' ? '/code/apps' : '/'
}
