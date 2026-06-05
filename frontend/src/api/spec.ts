import request from '@/utils/request'
import type { Spec, Phase, ItemType, ItemAction } from '@/types/spec'

export interface CreateSpecRequest {
  application_id?: number | null
}

export interface CreateSpecResponse {
  id: string
  phase: Phase
}

export const specApi = {
  create(body: CreateSpecRequest = {}) {
    return request.post<any, CreateSpecResponse>('/spec', body) as unknown as Promise<CreateSpecResponse>
  },
  get(specId: string) {
    return request.get<any, Spec>(`/spec/${specId}`) as unknown as Promise<Spec>
  },
  transitionPhase(specId: string, target: Phase, reason = 'user request') {
    return request.put<any, Spec>(`/spec/${specId}/phase`, { target, reason }) as unknown as Promise<Spec>
  },
  updateItem(
    specId: string,
    itemType: ItemType,
    itemCode: string,
    action: ItemAction,
    payload: Record<string, unknown> = {}
  ) {
    return request.put<any, Spec>(
      `/spec/${specId}/items/${itemType}/${itemCode}`,
      { action, payload }
    ) as unknown as Promise<Spec>
  },
}
