import request from '@/utils/request'
import type {
  ProposalSummary, ProposalDetail, ApplyPlan, Review, ReviewAction,
} from '@/types/proposal'

export interface PromoteRequest {
  title: string
  description?: string
  draft_spec_id: string
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

export const proposalsApi = {
  promote(applicationId: number, body: PromoteRequest): Promise<PromoteResponse> {
    return request.post<any, PromoteResponse>(`/applications/${applicationId}/proposals`, body)
  },
  list(applicationId: number, status?: string): Promise<ProposalSummary[]> {
    const params = status ? `?status=${encodeURIComponent(status)}` : ''
    return request.get<any, ProposalSummary[]>(`/applications/${applicationId}/proposals${params}`)
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
