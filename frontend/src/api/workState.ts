import request from '@/utils/request'
import type { ProjectRole } from '@/types/collaboration'
import type { ProposalSummary } from '@/types/proposal'

export interface WorkStateMember {
  user_id: number
  username: string
  role: ProjectRole
  source: 'creator' | 'inherited' | 'direct'
}

export interface WorkState {
  application: {
    id: number
    app_name: string
    app_code: string
    status: string
    platform_url: string | null
    apaas_app_id: string | null
    default_mode: 'simple' | 'pro' | null
  }
  current_draft: {
    id: string
    version: number
    completeness_confirmed: number
    completeness_total: number
    updated_at: string
  } | null
  canonical: {
    id: string
    version: number
    kind: string
    commit_sha: string | null
    updated_at: string
  } | null
  open_proposals: ProposalSummary[]
  applied_history: ProposalSummary[]
  git: {
    repo_url: string
    provider: string | null
    default_branch: string | null
    connected: boolean
  } | null
  members: WorkStateMember[]
  effective_mode: 'simple' | 'pro'
  user_role_on_app: ProjectRole
  user_pref_mode: 'simple' | 'pro'
}

export const workStateApi = {
  get(applicationId: number): Promise<WorkState> {
    return request.get<any, WorkState>(`/applications/${applicationId}/work-state`)
  },
}
