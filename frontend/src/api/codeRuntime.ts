import request from '@/utils/request'
import type { AIChatSession } from '@/api/aiChat'
import type { MergedApplication } from '@/types'

// This owner must change with any automatic activate retry added by the client.
export const CODE_RUNTIME_ACTIVATION_RETRY_DELAYS_MS = [] as const

export interface CodeApplication extends MergedApplication {
  id: string
  external_application_id: string
  source: 'd-ai-code'
  app_type: 'ai-code'
  repository?: Record<string, any> | null
  owner?: Record<string, any> | null
}

export interface CodeApplicationListResponse {
  items: CodeApplication[]
  page: number
  pageSize: number
  total: number
  source: 'd-ai-code'
}

export interface CreateCodeApplicationRequest {
  app_name: string
  app_code: string
  seed_project_id?: string | null
}

export interface CodeRuntimeOpenResponse {
  session_id: string
  app_id: number | null
  external_application_id: string
  workspace_id?: string | null
  sandbox_instance_id?: string | null
  runtime_session_id?: string | null
  external_base_path: string
  embed_url: string
  cache_profile?: 'normal' | 'performance'
  browser_hot_frames?: number
  server_warm_sandboxes_per_user?: number
}

export interface CodeAgentSessionRecord {
  runtimeSessionId: string
  title?: string | null
  summary?: string | null
  state?: string | null
  model?: string | null
  createdAt?: string | null
  updatedAt?: string | null
  lastActiveAt?: string | null
  current?: boolean | null
  deletedAt?: string | null
  capabilityStale?: boolean | null
  codexSessionResumable?: boolean | null
}

export interface CodeRailHistoryApp {
  shell_session_id: string
  external_application_id: string
  app_name?: string | null
  app_code?: string | null
  runtime_session_id?: string | null
  sessions: CodeAgentSessionRecord[]
  error?: string | null
}

export interface CodeRailHistoryResponse {
  apps: CodeRailHistoryApp[]
}

export interface CodeAgentSessionActivateResponse {
  shell_session_id: string
  runtime_session_id: string
  session?: Record<string, any> | null
}

export function resolveCodeRuntimeEmbedUrl(url: string, baseUrl = import.meta.env.BASE_URL): string {
  if (!url.startsWith('/api/code-runtime/')) return url
  const base = String(baseUrl || '/').replace(/\/+$/, '')
  return `${base === '/' ? '' : base}${url}`
}

export const codeRuntimeApi = {
  listApplications(params?: { keyword?: string; provisionStatus?: string; page?: number; pageSize?: number }) {
    return request.get<any, CodeApplicationListResponse>('/code/applications', { params })
  },
  createApplication(body: CreateCodeApplicationRequest) {
    return request.post<any, CodeApplication>('/code/applications', body)
  },
  createSessionFromApp(appId: number, body?: { title?: string; selected_llm_config_id?: number | null }) {
    return request.post<any, AIChatSession>('/code/sessions/from-app', {
      app_id: appId,
      ...(body?.title ? { title: body.title } : {}),
      ...(body?.selected_llm_config_id != null ? { selected_llm_config_id: body.selected_llm_config_id } : {}),
    })
  },
  createSessionFromExternalApp(
    app: { external_application_id: string; app_name?: string | null; app_code?: string | null },
    body?: { title?: string; selected_llm_config_id?: number | null },
  ) {
    return request.post<any, AIChatSession>('/code/sessions/from-external-app', {
      external_application_id: app.external_application_id,
      ...(app.app_name ? { app_name: app.app_name } : {}),
      ...(app.app_code ? { app_code: app.app_code } : {}),
      ...(body?.title ? { title: body.title } : {}),
      ...(body?.selected_llm_config_id != null ? { selected_llm_config_id: body.selected_llm_config_id } : {}),
    })
  },
  async openSession(sessionRef: number | string) {
    const encodedSessionRef = encodeURIComponent(String(sessionRef))
    const opened = await request.post<any, CodeRuntimeOpenResponse>(`/code/sessions/${encodedSessionRef}/open`)
    return {
      ...opened,
      embed_url: resolveCodeRuntimeEmbedUrl(opened.embed_url),
    }
  },
  listRailHistory() {
    return request.get<any, CodeRailHistoryResponse>('/code/rail/history')
  },
  listAgentSessions(shellSessionId: string) {
    return request.get<any, { sessions: CodeAgentSessionRecord[] }>(
      `/code-runtime/${shellSessionId}/shell/agent-sessions`,
    )
  },
  createAgentSession(shellSessionId: string) {
    // 外层工作台尚未持有 iframe 的 Runtime Cookie，必须复用 Builder 登录态。
    const encodedShellSessionId = encodeURIComponent(shellSessionId)
    return request.post<any, CodeAgentSessionActivateResponse>(
      `/code/sessions/${encodedShellSessionId}/agent-sessions`,
    )
  },
  activateAgentSession(shellSessionId: string, runtimeSessionId: string) {
    const encodedShellSessionId = encodeURIComponent(shellSessionId)
    return request.post<any, CodeAgentSessionActivateResponse>(
      `/code/sessions/${encodedShellSessionId}/agent-sessions/${encodeURIComponent(runtimeSessionId)}/activate`,
    )
  },
  deleteAgentSession(shellSessionId: string, runtimeSessionId: string) {
    const encodedShellSessionId = encodeURIComponent(shellSessionId)
    return request.delete<any, { ok?: boolean }>(
      `/code/sessions/${encodedShellSessionId}/agent-sessions/${encodeURIComponent(runtimeSessionId)}`,
    )
  },
}
