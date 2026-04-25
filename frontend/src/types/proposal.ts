import type { ProjectRole } from './collaboration'

export type ProposalStatus =
  | 'draft' | 'open' | 'changes_requested'
  | 'approved' | 'applying' | 'applied' | 'apply_failed' | 'closed'

export type ReviewAction = 'approve' | 'request_changes' | 'comment'
export type Reversibility = 'green' | 'yellow' | 'red'

export interface ValidationCheckResult {
  ok: boolean
  issues: string[]
}

export interface ValidationReport {
  ok: boolean
  completeness: ValidationCheckResult
  consistency: ValidationCheckResult
  naming: ValidationCheckResult
  markdown: ValidationCheckResult
}

export interface ApplyOp {
  kind: string
  target: string
  detail: Record<string, any>
  reversibility: Reversibility
}

export interface ApplyPlan {
  ops: ApplyOp[]
  has_irreversible: boolean
  rebase_required: boolean
  rebase_reason: string | null
  issues: string[]
}

export interface Review {
  id: number
  reviewer_id: number
  action: ReviewAction
  body: string | null
  created_at: string | null
}

export interface ProposalSummary {
  id: string
  title: string
  status: ProposalStatus
  created_by: number
  created_at: string | null
  applied_at: string | null
  draft_spec_id: string
  base_canonical_spec_id: string | null
}

export interface ProposalDetail extends ProposalSummary {
  application_id: number
  description: string | null
  validation_report: ValidationReport | null
  apply_plan: ApplyPlan | null
  apply_log: Record<string, any> | null
  git_branch: string | null
  git_pr_url: string | null
  updated_at: string | null
  reviews: Review[]
}

export const STATUS_DISPLAY_NAMES: Record<ProposalStatus, string> = {
  draft: '草稿',
  open: '待评审',
  changes_requested: '需修改',
  approved: '已批准',
  applying: '执行中',
  applied: '已 apply',
  apply_failed: 'apply 失败',
  closed: '已关闭',
}

// re-export for convenience（避免 unused import 警告）
export type { ProjectRole }
