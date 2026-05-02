import request from '@/utils/request'

export interface SandboxInfo {
  workspace_id: string
  title: string
  user_id: number
  tenant_id: number
  owner_username?: string | null
  container_status?: string | null
  ports: Record<number, number>
  listening_ports: number[]
  created_at?: string | null
  updated_at?: string | null
}

export interface SandboxListResponse {
  sandboxes: SandboxInfo[]
  scope: 'user' | 'tenant' | 'platform'
  total: number
}

export const sandboxApi = {
  list() {
    return request.get<any, SandboxListResponse>('/online-coding/sandboxes')
  },
  stop(workspaceId: string) {
    return request.post<any, { ok: boolean; status: string }>(`/online-coding/sandboxes/${workspaceId}/stop`)
  },
  remove(workspaceId: string) {
    return request.delete<any, { ok: boolean; status: string }>(`/online-coding/sandboxes/${workspaceId}`)
  },
}
