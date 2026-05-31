import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  industryApi,
  type IndustryPack,
  type OntologyResponse,
} from '@/api/industry'

/** Empty ontology used when the selected pack has no ontology rows yet. */
const EMPTY_ONTOLOGY: OntologyResponse = {
  pack: '',
  entities: [],
  relations: [],
  workflows: [],
  dictHighlight: [],
}

export const useIndustryStore = defineStore('industry', () => {
  const packs = ref<IndustryPack[]>([])
  const ontologyByPack = ref<Record<string, OntologyResponse>>({})
  const loading = ref(false)
  const ontologyLoading = ref(false)
  const error = ref<string | null>(null)

  const installedCount = computed(() => packs.value.filter(p => p.installed).length)

  function getOntology(packId: string): OntologyResponse {
    return ontologyByPack.value[packId] || EMPTY_ONTOLOGY
  }

  async function fetchPacks() {
    loading.value = true
    error.value = null
    try {
      const r = await industryApi.listPacks()
      packs.value = r.packs
    } catch (e: any) {
      error.value = e?.message || 'fetch industry packs failed'
    } finally {
      loading.value = false
    }
  }

  async function fetchOntology(packId: string) {
    ontologyLoading.value = true
    try {
      const r = await industryApi.getOntology(packId)
      ontologyByPack.value[packId] = r
    } catch (e: any) {
      error.value = e?.message || `fetch ontology ${packId} failed`
    } finally {
      ontologyLoading.value = false
    }
  }

  async function install(packId: string): Promise<boolean> {
    try {
      const r = await industryApi.install(packId)
      if (r.ok) {
        const p = packs.value.find(x => x.id === packId)
        if (p) p.installed = true
      }
      return r.ok && r.installed
    } catch (e: any) {
      error.value = e?.message || 'install pack failed'
      return false
    }
  }

  return {
    packs,
    ontologyByPack,
    loading,
    ontologyLoading,
    error,
    installedCount,
    getOntology,
    fetchPacks,
    fetchOntology,
    install,
  }
})
