import { computed, reactive } from 'vue'
import type { CodeApplication, CodeExecutionLocation } from '@/api/codeRuntime'
import type { CodeApplicationCacheScope } from '@/stores/codeApplications'
import { useCodeApplicationsStore } from '@/stores/codeApplications'
import { mergeCodeApplicationLocations } from '@/components/code/codeApplicationLocations'

interface SourceState {
  items: CodeApplication[]
  loading: boolean
  loaded: boolean
  error: string
}

export interface UnifiedCodeApplicationsOptions {
  desktop: boolean
  scope: () => CodeApplicationCacheScope
  deploymentId: () => string
}

function errorMessage(error: unknown): string {
  const typed = error as any
  return typed?.response?.data?.detail || typed?.message || '应用列表加载失败'
}

export function useUnifiedCodeApplications(options: UnifiedCodeApplicationsOptions) {
  const store = useCodeApplicationsStore()
  const local = reactive<SourceState>({ items: [], loading: false, loaded: false, error: '' })
  const remote = reactive<SourceState>({ items: [], loading: false, loaded: false, error: '' })
  const sourceState = { local, remote }
  let loadGeneration = 0

  const applications = computed(() => mergeCodeApplicationLocations(
    options.desktop ? local.items : [],
    remote.items,
    options.deploymentId(),
    { remoteSourceAvailable: !remote.error },
  ))
  const loading = computed(() => {
    const states = options.desktop ? [local, remote] : [remote]
    return states.some(state => state.loading) && states.every(state => state.items.length === 0)
  })

  async function loadSource(source: CodeExecutionLocation, force = false, generation = loadGeneration) {
    const state = sourceState[source]
    state.loading = true
    state.error = ''
    try {
      const page = await store.load(
        options.scope(),
        { source, pageSize: 100 },
        { force },
      )
      if (generation !== loadGeneration) return
      state.items = page.items || []
      state.loaded = true
    } catch (error) {
      if (generation !== loadGeneration) return
      state.error = errorMessage(error)
      state.loaded = true
    } finally {
      if (generation === loadGeneration) state.loading = false
    }
  }

  async function load(force = false) {
    const generation = ++loadGeneration
    const sources: CodeExecutionLocation[] = options.desktop ? ['local', 'remote'] : ['remote']
    await Promise.all(sources.map(source => loadSource(source, force, generation)))
  }

  function retry(source: CodeExecutionLocation) {
    return loadSource(source, true)
  }

  return { applications, loading, local, remote, load, retry }
}
