/**
 * 智能开发 V2（Agent 架构）API 封装。
 *
 * 与老 api/coding.ts 区别：
 * - 新流水线（/api/coding/v2/message）+ 结构化 Spec + SSE 订阅
 * - 所有方法对应后端 coding_v2 / coding_v2_spec / sse 路由
 */
import request from '@/utils/request'
import { API_PREFIX } from '@/utils/request'

// ══════════════════════════════════════════════════════════════
// 枚举
// ══════════════════════════════════════════════════════════════

export type SceneType =
  | 'web_component_dual'
  | 'web_page'
  | 'mobile_page'
  | 'backend_api'
  | 'backend_feign'
  | 'backend_scheduled'

export type Phase =
  | 'idle'
  | 'understand'
  | 'confirm'
  | 'scaffold'
  | 'generate'
  | 'verify'
  | 'done'
  | 'failed'
  | 'aborted'

export type IterationLevel = 'trivial' | 'minor' | 'major' | 'cross_scene'

export type RouteAction =
  | 'start_brainstorm'
  | 'continue_brainstorm'
  | 'resume_brainstorm'
  | 'refine_brainstorm'
  | 'reject_message'
  | 'iterate'
  | 'restart'
  | 'start_coding'

// ══════════════════════════════════════════════════════════════
// Spec 结构（后端 schema 1.0 的 TS 镜像）
// ══════════════════════════════════════════════════════════════

export interface Provenance {
  brainstorm_session_id: string
  created_at: string
  created_by: 'agent' | 'user' | 'mixed'
  model?: string | null
  version: number
  parent_version?: number | null
  confidence: number
  open_questions: { question: string; assumed_answer: string }[]
}

export interface Identity {
  code_name: string
  display_name: string
  description_cn: string
  widget_code?: string | null
}

export interface Intent {
  original_requirement: string
  core_purpose: string
  acceptance_criteria: string[]
}

export interface SpecEnvelope {
  schema_version: '1.0'
  spec_id: string
  scene_type: SceneType
  provenance: Provenance
  identity: Identity
  intent: Intent
  spec: Record<string, any>   // 场景特定（ComponentSpec/PageSpec/BackendApiSpec）
  metadata?: Record<string, any>
  references?: Array<{ spec_id: string; relation: string; note?: string }>
}

export interface SpecSummary {
  spec_id: string
  scene_type: SceneType
  code_name: string
  widget_code?: string | null
  version: number
  parent_version?: number | null
  confidence: number
  created_by: string
  created_at: string
}

export interface SpecDetail extends SpecSummary {
  envelope: SpecEnvelope
}

// ══════════════════════════════════════════════════════════════
// /api/coding/v2/message
// ══════════════════════════════════════════════════════════════

export interface SendMessageRequest {
  conversation_id?: number | null
  message: string
  selected_model?: number | null
}

export interface SendMessageResponse {
  conversation_id: number
  action: RouteAction
  phase: Phase
  session_id?: string | null
  reason: string
  hint_subscribe_sse: string
}

export function sendCodingMessage(payload: SendMessageRequest): Promise<SendMessageResponse> {
  return request.post('/coding/v2/message', payload)
}

// ══════════════════════════════════════════════════════════════
// /api/coding/v2/spec/{id}/start-coding
// ══════════════════════════════════════════════════════════════

export interface StartCodingResponse {
  conversation_id: number
  spec_id: string
  phase: Phase
}

export function startCodingFromSpec(specId: string): Promise<StartCodingResponse> {
  return request.post(`/coding/v2/spec/${encodeURIComponent(specId)}/start-coding`)
}

// ══════════════════════════════════════════════════════════════
// /api/coding/v2/specs/*
// ══════════════════════════════════════════════════════════════

export function getSpec(specId: string): Promise<SpecDetail> {
  return request.get(`/coding/v2/specs/${encodeURIComponent(specId)}`)
}

export function listSpecVersions(specId: string): Promise<SpecSummary[]> {
  return request.get(`/coding/v2/specs/${encodeURIComponent(specId)}/versions`)
}

export interface ConfirmResponse {
  spec_id: string
  brainstorm_session_id: string
  conversation_id: number
  phase_hint: 'scaffold' | 'generate' | 'already_confirmed'
}

export function confirmSpec(specId: string): Promise<ConfirmResponse> {
  return request.post(`/coding/v2/specs/${encodeURIComponent(specId)}/confirm`)
}

export interface RefineResponse {
  brainstorm_session_id: string
  message: string
}

export function refineSpec(specId: string, instruction?: string): Promise<RefineResponse> {
  return request.post(`/coding/v2/specs/${encodeURIComponent(specId)}/refine`, {
    instruction: instruction ?? null,
  })
}

export interface RollbackResponse {
  new_spec_id: string
  new_version: number
  parent_version: number
  message: string
}

export function rollbackSpec(specId: string): Promise<RollbackResponse> {
  return request.post(`/coding/v2/specs/${encodeURIComponent(specId)}/rollback`)
}

// ══════════════════════════════════════════════════════════════
// SSE URL 构造器（EventSource 用）
// ══════════════════════════════════════════════════════════════

export function buildSseUrl(conversationId: number, lastSeenSeq: number = 0): string {
  return `${API_PREFIX}/sse/conversation/${conversationId}?last_seen_seq=${lastSeenSeq}`
}

// ══════════════════════════════════════════════════════════════
// IDE URL
// ══════════════════════════════════════════════════════════════

export function getIdeUrl(workspaceId: string, conversationId?: number | null): Promise<{ ide_url: string }> {
  return request.get(`/coding/workspace/${encodeURIComponent(workspaceId)}/ide-url`, {
    params: conversationId ? { conversation_id: conversationId } : undefined,
  })
}

export function getConversationWorkspace(conversationId: number): Promise<{ conversation_id: number; workspace_id: string | null }> {
  return request.get(`/coding/v2/conversations/${conversationId}/workspace`)
}
