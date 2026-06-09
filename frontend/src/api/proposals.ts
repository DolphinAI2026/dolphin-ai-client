import request from '@/utils/request'
import type {
  ProposalSummary, ProposalDetail, ApplyPlan, Review, ReviewAction,
} from '@/types/proposal'

export interface PromoteRequest {
  title: string
  description?: string
  /** 不传时后端自动使用 application 当前 spec_id 作为 draft */
  draft_spec_id?: string
}

export interface PromoteResponse {
  id: string
  status: string
  validation_report: any
  title: string
}

export interface ApplyResponse {
  status: string
  apply_plan?: ApplyPlan
  success?: boolean
  failure_reason?: string
  apply_log?: any
}

export interface ProposalSummaryWithApp extends ProposalSummary {
  application_id: number
  app_name?: string
  app_code?: string
}

export const proposalsApi = {
  promote(applicationId: number, body: PromoteRequest): Promise<PromoteResponse> {
    return request.post<any, PromoteResponse>(`/applications/${applicationId}/proposals`, body)
  },
  list(applicationId: number, status?: string): Promise<ProposalSummary[]> {
    const params = status ? `?status=${encodeURIComponent(status)}` : ''
    return request.get<any, ProposalSummary[]>(`/applications/${applicationId}/proposals${params}`)
  },
  /** 跨应用列出当前 tenant 所有 proposal（审批中心用） */
  listAll(opts?: { status?: string; actionable?: boolean }): Promise<ProposalSummaryWithApp[]> {
    const params = new URLSearchParams()
    if (opts?.status) params.set('status', opts.status)
    if (opts?.actionable) params.set('actionable', 'true')
    const qs = params.toString()
    return request.get<any, ProposalSummaryWithApp[]>(`/proposals${qs ? '?' + qs : ''}`)
  },
  get(proposalId: string): Promise<ProposalDetail> {
    return request.get<any, ProposalDetail>(`/proposals/${proposalId}`)
  },
  update(proposalId: string, body: { title?: string; description?: string }) {
    return request.patch<any, any>(`/proposals/${proposalId}`, body)
  },
  refreshValidation(proposalId: string): Promise<ProposalDetail> {
    return request.post<any, ProposalDetail>(`/proposals/${proposalId}/refresh-validation`, {})
  },
  close(proposalId: string) {
    return request.post<any, any>(`/proposals/${proposalId}/close`, {})
  },
  review(proposalId: string, action: ReviewAction, body?: string): Promise<Review & { proposal_status: string }> {
    return request.post<any, any>(`/proposals/${proposalId}/reviews`, { action, body })
  },
  apply(proposalId: string, confirmIrreversible: boolean): Promise<ApplyResponse> {
    return request.post<any, ApplyResponse>(`/proposals/${proposalId}/apply`, {
      confirm_irreversible: confirmIrreversible,
    })
  },
}
