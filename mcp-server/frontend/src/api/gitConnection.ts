import request from '@/utils/request'

export interface GitConnection {
  id: number
  project_id: number
  provider: 'gitlab' | 'github'
  host: string
  group_id_or_org: string
  status: string
}

export interface ConnectGitPATRequest {
  provider: 'gitlab' | 'github'
  host: string
  access_token: string
  group_id_or_org: string
}

export interface InitRepoResponse {
  git_repo_url: string
  full_path: string
}

export interface DriftStatus {
  drift: boolean
  git_sha?: string
  builder_sha?: string
  reason?: string
}

export interface SyncWorkspaceResponse {
  status: string
  branch?: string
  commit_sha?: string
  file_count?: number
}

export const gitConnectionApi = {
  get(projectId: number): Promise<GitConnection | null> {
    return request.get<any, GitConnection | null>(`/projects/${projectId}/git-connection`)
  },
  connectPAT(projectId: number, body: ConnectGitPATRequest): Promise<GitConnection> {
    return request.post<any, GitConnection>(`/projects/${projectId}/git-connection`, body)
  },
  disconnect(projectId: number) {
    return request.delete<any, { status: string }>(`/projects/${projectId}/git-connection`)
  },
  initRepo(applicationId: number): Promise<InitRepoResponse> {
    return request.post<any, InitRepoResponse>(`/applications/${applicationId}/git-init`, {})
  },
  driftStatus(applicationId: number): Promise<DriftStatus> {
    return request.get<any, DriftStatus>(`/applications/${applicationId}/drift-status`)
  },
  resolveDrift(applicationId: number, direction: 'git_to_builder' | 'builder_to_git') {
    return request.post<any, any>(`/applications/${applicationId}/resolve-drift`, { direction })
  },
  syncWorkspace(applicationId: number, workspaceId: string): Promise<SyncWorkspaceResponse> {
    return request.post<any, SyncWorkspaceResponse>(
      `/applications/${applicationId}/workspaces/${workspaceId}/sync-to-repo`, {}
    )
  },
}
