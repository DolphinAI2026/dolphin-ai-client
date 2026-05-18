/**
 * useAIChatBlueprintStore — caches the parsed SPEC for AIChatPage's right panel.
 *
 * AIChatPage watches the currently-open artifact content and calls
 * `parseFromContent(content)`. The store dedups by content length+prefix hash so
 * watch loops don't re-hit the backend on identical content. The resulting
 * ParsedSpec feeds AppBlueprintPanel directly (after snake_case → camelCase
 * shape mapping done in the page).
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { specsV2Api, type ParsedSpec } from '@/api/specsV2'

export const useAIChatBlueprintStore = defineStore('ai-chat-blueprint', () => {
  const parsed = ref<ParsedSpec | null>(null)
  const lastContentHash = ref<string>('')
  const loading = ref(false)
  const error = ref<string>('')

  async function parseFromContent(content: string) {
    if (!content) {
      parsed.value = null
      lastContentHash.value = ''
      error.value = ''
      return
    }
    // Cheap dedup: length + first 200 chars — same as content for practical purposes
    const hash = String(content.length) + ':' + content.slice(0, 200)
    if (hash === lastContentHash.value && parsed.value) return
    lastContentHash.value = hash
    loading.value = true
    error.value = ''
    try {
      parsed.value = await specsV2Api.parseMd(content)
    } catch (e: any) {
      parsed.value = null
      error.value = e?.message || String(e) || '解析失败'
    } finally {
      loading.value = false
    }
  }

  function clear() {
    parsed.value = null
    lastContentHash.value = ''
    error.value = ''
  }

  const isEmpty = computed(
    () =>
      !parsed.value ||
      (parsed.value.models.length === 0 &&
        parsed.value.forms.length === 0 &&
        parsed.value.flows.length === 0 &&
        parsed.value.roles.length === 0 &&
        parsed.value.dicts.length === 0),
  )

  return { parsed, loading, error, isEmpty, parseFromContent, clear }
})
