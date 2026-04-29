import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { specApi } from '@/api/spec'
import type { Spec, Phase, ItemType, ItemAction } from '@/types/spec'

export const useSpecStore = defineStore('spec', () => {
  const current = ref<Spec | null>(null)
  const loading = ref(false)
  const lastError = ref<string | null>(null)

  const phase = computed<Phase | null>(() => current.value?.phase ?? null)
  const completeness = computed(() => current.value?.completeness ?? null)
  const pendingDecisions = computed(() => current.value?.decisions_pending ?? [])
  const blockingDecisions = computed(() =>
    pendingDecisions.value.filter((d) => d.blocking && !d.resolved)
  )

  async function load(specId: string) {
    loading.value = true
    lastError.value = null
    try {
      current.value = await specApi.get(specId)
    } catch (e: unknown) {
      lastError.value = e instanceof Error ? e.message : String(e)
      current.value = null
    } finally {
      loading.value = false
    }
  }

  async function create(applicationId: number | null = null): Promise<string> {
    const resp = await specApi.create({ application_id: applicationId })
    return resp.id
  }

  async function transitionPhase(target: Phase, reason = 'user request') {
    if (!current.value) return
    try {
      current.value = await specApi.transitionPhase(current.value.id, target, reason)
    } catch (e: unknown) {
      lastError.value = e instanceof Error ? e.message : String(e)
      throw e
    }
  }

  async function updateItem(
    type: ItemType,
    code: string,
    action: ItemAction,
    payload: Record<string, unknown> = {}
  ) {
    if (!current.value) return
    try {
      current.value = await specApi.updateItem(current.value.id, type, code, action, payload)
    } catch (e: unknown) {
      lastError.value = e instanceof Error ? e.message : String(e)
      throw e
    }
  }

  /** Apply a `spec_patch` SSE event payload directly to the store
   * (saves a round-trip to GET /spec/{id} after every LLM tool call). */
  function applyPatch(specPayload: Spec) {
    current.value = specPayload
  }

  function reset() {
    current.value = null
    lastError.value = null
  }

  return {
    current,
    loading,
    lastError,
    phase,
    completeness,
    pendingDecisions,
    blockingDecisions,
    load,
    create,
    transitionPhase,
    updateItem,
    applyPatch,
    reset,
  }
})
