import { defineStore } from 'pinia'
import { ref } from 'vue'
import { preferencesApi, type UserPreference } from '@/api/preferences'

export const useUserPreferenceStore = defineStore('userPreference', () => {
  const pref = ref<UserPreference | null>(null)
  const loading = ref(false)

  async function fetch() {
    if (loading.value) return
    loading.value = true
    try {
      pref.value = await preferencesApi.get()
    } finally {
      loading.value = false
    }
  }

  async function setMode(mode: 'simple' | 'pro') {
    pref.value = await preferencesApi.update(mode)
  }

  return { pref, fetch, setMode }
})
