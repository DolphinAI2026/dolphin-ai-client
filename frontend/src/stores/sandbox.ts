import { defineStore } from 'pinia'
import { ref } from 'vue'
import { runtimeSandboxApi, type RuntimeSandbox } from '@/api/sandbox'

export const useRuntimeSandboxStore = defineStore('runtime-sandbox', () => {
  const sandboxes = ref<RuntimeSandbox[]>([])
  const total = ref(0)
  const activeCount = ref(0)
  const idleCount = ref(0)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchSandboxes() {
    loading.value = true
    error.value = null
    try {
      const r = await runtimeSandboxApi.list()
      sandboxes.value = r.sandboxes
      total.value = r.total
      activeCount.value = r.active
      idleCount.value = r.idle_count
    } catch (e: any) {
      error.value = e?.message || 'fetch sandboxes failed'
    } finally {
      loading.value = false
    }
  }

  return { sandboxes, total, activeCount, idleCount, loading, error, fetchSandboxes }
})
