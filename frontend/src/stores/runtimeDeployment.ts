import { defineStore } from 'pinia'
import { ref } from 'vue'
import { runtimeDeploymentApi, type Deployment } from '@/api/runtimeDeployment'

export const useRuntimeDeploymentStore = defineStore('runtime-deployment', () => {
  const deployments = ref<Deployment[]>([])
  const total = ref(0)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchDeployments() {
    loading.value = true
    error.value = null
    try {
      const r = await runtimeDeploymentApi.list()
      deployments.value = r.deployments
      total.value = r.total
    } catch (e: any) {
      error.value = e?.message || 'fetch deployments failed'
    } finally {
      loading.value = false
    }
  }

  return { deployments, total, loading, error, fetchDeployments }
})
