import request from '@/utils/request'

export interface OnlineCodingWorkspace {
  id: string
  repo_url?: string | null
  task: string
  user_id: number
  status: string
  sandbox_status: string
  created_at: string
  updated_at: string
  next_steps: string[]
  imported_at?: string | null
  branch?: string | null
  file_count: number
  files: string[]
  import_error?: string | null
  spec_draft?: string | null
  spec_confirmed?: boolean
}

export interface OnlineCodingFileContent {
  path: string
  content: string
  truncated: boolean
}

export type PreviewRuntimeStatus =
  | 'unsupported'
  | 'detected'
  | 'installing'
  | 'starting'
  | 'running'
  | 'stopped'
  | 'error'

export interface OnlinePreviewProject {
  workspace_id: string
  workspace_path: string
  working_dir: string
  supported: boolean
  status: PreviewRuntimeStatus
  package_manager: string
  install_command?: string[] | null
  start_command?: string[] | null
  build_command?: string[] | null
  reason?: string | null
}

export interface OnlinePreviewRuntime {
  workspace_id: string
  status: PreviewRuntimeStatus
  runner: string
  working_dir: string
  port?: number | null
  preview_url?: string | null
  pid?: number | null
  log_path?: string | null
  command?: string[] | null
  error?: string | null
  started_at?: string | null
  updated_at?: string | null
}

export interface OnlinePreviewStartResult {
  project: OnlinePreviewProject
  runtime: OnlinePreviewRuntime
}

export interface CreateOnlineCodingWorkspacePayload {
  repo_url?: string | null
  task?: string | null
  git_username?: string | null
  git_token?: string | null
}

export const onlineCodingApi = {
  createWorkspace(payload: CreateOnlineCodingWorkspacePayload) {
    return request.post<any, OnlineCodingWorkspace>('/online-coding/workspaces', payload)
  },

  importWorkspace(workspaceId: string, payload: CreateOnlineCodingWorkspacePayload) {
    return request.post<any, OnlineCodingWorkspace>(`/online-coding/workspaces/${workspaceId}/import`, payload)
  },

  listWorkspaces() {
    return request.get<any, OnlineCodingWorkspace[]>('/online-coding/workspaces')
  },

  getWorkspace(workspaceId: string) {
    return request.get<any, OnlineCodingWorkspace>(`/online-coding/workspaces/${workspaceId}`)
  },

  deleteWorkspace(workspaceId: string) {
    return request.delete<any, { ok: boolean }>(`/online-coding/workspaces/${workspaceId}`)
  },

  updateSpec(workspaceId: string, payload: { task?: string | null; spec_draft?: string | null; spec_confirmed?: boolean }) {
    return request.put<any, OnlineCodingWorkspace>(`/online-coding/workspaces/${workspaceId}/spec`, payload)
  },

  readFile(workspaceId: string, filePath: string) {
    return request.get<any, OnlineCodingFileContent>(`/online-coding/workspaces/${workspaceId}/file`, {
      params: { file_path: filePath },
    })
  },

  getIdeUrl(workspaceId: string, theme?: 'light' | 'dark', selectedModel?: string | null) {
    const params: Record<string, string> = {}
    if (theme) params.theme = theme
    if (selectedModel) params.selected_model = selectedModel
    return request.get<any, { ide_url: string }>(`/online-coding/workspaces/${workspaceId}/ide-url`, {
      params,
    })
  },

  detectPreviewRuntime(workspaceId: string) {
    return request.get<any, OnlinePreviewProject>(`/online-coding/workspaces/${workspaceId}/runtime/detect`)
  },

  startPreviewRuntime(workspaceId: string) {
    return request.post<any, OnlinePreviewStartResult>(
      `/online-coding/workspaces/${workspaceId}/runtime/start`,
      {},
      { timeout: 360000 },
    )
  },

  getPreviewRuntimeStatus(workspaceId: string) {
    return request.get<any, OnlinePreviewRuntime>(`/online-coding/workspaces/${workspaceId}/runtime/status`)
  },

  stopPreviewRuntime(workspaceId: string) {
    return request.post<any, OnlinePreviewRuntime>(`/online-coding/workspaces/${workspaceId}/runtime/stop`)
  },

  getPreviewRuntimeLogs(workspaceId: string, maxBytes = 16000) {
    return request.get<any, { workspace_id: string; logs: string }>(
      `/online-coding/workspaces/${workspaceId}/runtime/logs`,
      { params: { max_bytes: maxBytes } },
    )
  },
}
