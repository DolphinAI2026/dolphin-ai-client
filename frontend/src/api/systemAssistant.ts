import request from '@/utils/request'
import type { BuilderModelOption } from '@/api/llmConfig'

export type SystemAssistantBaselineStatus =
  | 'ready'
  | 'partial'
  | 'missing'
  | 'stale'
  | 'unavailable'
  | 'not_needed'

export type SystemAssistantSourceStatus = 'ready' | 'partial' | 'unavailable'

export interface SystemAssistantBaselineNode {
  id: string
  label: string
  status: SystemAssistantBaselineStatus
  source_status: SystemAssistantSourceStatus
  items: Array<Record<string, unknown>>
  metadata: Record<string, unknown>
}

export interface SystemAssistantRecommendedAction {
  id: string
  status: SystemAssistantBaselineStatus
  title: string
  reason: string
}

export interface SystemAssistantBootstrap {
  baseline_snapshot: {
    version: 'p0'
    readonly: true
    tenant_id: number
    generated_at: string
    nodes: SystemAssistantBaselineNode[]
    metadata: {
      plan_created: false
      dynamic_plan_source: 'not_available_in_p0'
      unavailable_sources: string[]
      partial_sources: string[]
    }
  }
  recommended_action: SystemAssistantRecommendedAction
  available_actions: string[]
  source_status: Record<string, SystemAssistantSourceStatus>
  execution: {
    configured_mode: 'local' | 'remote'
    remote_runtime_available: boolean
    local_directory_access: boolean
  }
}

export const systemAssistantApi = {
  getBootstrap(): Promise<SystemAssistantBootstrap> {
    return request.get<any, SystemAssistantBootstrap>('/system-assistant/bootstrap')
  },
  listModels(): Promise<BuilderModelOption[]> {
    return request.get<any, BuilderModelOption[]>('/system-assistant/models')
  },
}
