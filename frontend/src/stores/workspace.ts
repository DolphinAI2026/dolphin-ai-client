import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { workStateApi, type WorkState } from '@/api/workState'

export const useWorkspaceStore = defineStore('workspace', () => {
  const state = ref<WorkState | null>(null)
  const loading = ref(false)
  const error = ref('')

  const effectiveMode = computed(() => state.value?.effective_mode ?? 'simple')
  const application = computed(() => state.value?.application ?? null)

  async function load(applicationId: number) {
    loading.value = true
    error.value = ''
    try {
      state.value = await workStateApi.get(applicationId)
    } catch (e: any) {
      error.value = e?.response?.data?.detail || e?.message || 'load failed'
      state.value = null
    } finally {
      loading.value = false
    }
  }

  async function refresh() {
    if (state.value?.application?.id) {
      await load(state.value.application.id)
    }
  }

  function reset() {
    state.value = null
    error.value = ''
  }

  return { state, loading, error, effectiveMode, application, load, refresh, reset }
})
