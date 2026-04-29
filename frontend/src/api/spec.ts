import request from '@/utils/request'
import type { Spec, Phase, ItemType, ItemAction } from '@/types/spec'

export interface CreateSpecRequest {
  application_id?: number | null
}

export interface CreateSpecResponse {
  id: string
  phase: Phase
}

export interface GenerateConfigResponse {
  spec: Spec
  config: Record<string, unknown>
}

export const specApi = {
  create(body: CreateSpecRequest = {}) {
    return request.post<CreateSpecResponse>('/spec', body)
  },
  get(specId: string) {
    return request.get<Spec>(`/spec/${specId}`)
  },
  transitionPhase(specId: string, target: Phase, reason = 'user request') {
    return request.put<Spec>(`/spec/${specId}/phase`, { target, reason })
  },
  confirmAll(specId: string) {
    return request.put<Spec>(`/spec/${specId}/confirm-all`, {})
  },
  generateConfig(specId: string) {
    return request.post<GenerateConfigResponse>(`/spec/${specId}/generate-config`, {})
  },
  updateItem(
    specId: string,
    itemType: ItemType,
    itemCode: string,
    action: ItemAction,
    payload: Record<string, unknown> = {}
  ) {
    return request.put<Spec>(
      `/spec/${specId}/items/${itemType}/${itemCode}`,
      { action, payload }
    )
  },
}
