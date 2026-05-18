import { defineStore } from 'pinia'
import { ref } from 'vue'
import { specsV2Api, type SpecListItem } from '@/api/specsV2'

export const useSpecsV2Store = defineStore('specs-v2', () => {
  const specs = ref<SpecListItem[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchSpecs() {
    loading.value = true
    error.value = null
    try {
      specs.value = (await specsV2Api.list()).specs
    } catch (e: any) {
      error.value = e?.message || 'fetch specs failed'
    } finally {
      loading.value = false
    }
  }

  return { specs, loading, error, fetchSpecs }
})
