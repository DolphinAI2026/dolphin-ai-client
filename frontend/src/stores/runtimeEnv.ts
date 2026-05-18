import { defineStore } from 'pinia'
import { ref } from 'vue'
import { runtimeEnvApi, type RuntimeEnv } from '@/api/runtimeEnv'

export const useRuntimeEnvStore = defineStore('runtime-env', () => {
  const environments = ref<RuntimeEnv[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchEnvironments() {
    loading.value = true
    error.value = null
    try {
      environments.value = (await runtimeEnvApi.list()).environments
    } catch (e: any) {
      error.value = e?.message || 'fetch env failed'
    } finally {
      loading.value = false
    }
  }

  return { environments, loading, error, fetchEnvironments }
})
