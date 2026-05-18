import { defineStore } from 'pinia'
import { ref } from 'vue'
import { runtimePipelineApi, type PipelineRun } from '@/api/runtimePipeline'

export const useRuntimePipelineStore = defineStore('runtime-pipeline', () => {
  const pipelines = ref<PipelineRun[]>([])
  const total = ref(0)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchPipelines() {
    loading.value = true
    error.value = null
    try {
      const r = await runtimePipelineApi.list()
      pipelines.value = r.pipelines
      total.value = r.total
    } catch (e: any) {
      error.value = e?.message || 'fetch pipelines failed'
    } finally {
      loading.value = false
    }
  }

  return { pipelines, total, loading, error, fetchPipelines }
})
