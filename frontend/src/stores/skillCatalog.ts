import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { skillCatalogApi, type SkillCatalogItem } from '@/api/skillCatalog'

export const useSkillCatalogStore = defineStore('skill-catalog', () => {
  const skills = ref<SkillCatalogItem[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  const byCategory = computed(() => {
    const out: Record<string, SkillCatalogItem[]> = {}
    for (const s of skills.value) {
      ;(out[s.category] ||= []).push(s)
    }
    return out
  })

  async function fetchCatalog() {
    loading.value = true
    try { skills.value = (await skillCatalogApi.list()).skills }
    catch (e: any) { error.value = e?.message || 'fetch catalog failed' }
    finally { loading.value = false }
  }

  return { skills, byCategory, loading, error, fetchCatalog }
})
