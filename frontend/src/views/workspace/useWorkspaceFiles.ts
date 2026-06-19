import { ref, computed, type Ref } from 'vue'
import { listWorkspaceFiles, getWorkspaceChanges } from '@/api/coding'
import { buildFileTree, type TreeNode } from '@/views/coding/fileTree'

export function useWorkspaceFiles(wsId: Ref<string | null>) {
  const tree = ref<TreeNode[]>([])
  const changes = ref<any>(null)
  const selected = ref<string | null>(null)
  const loading = ref(false)
  const error = ref('')

  const changed = computed<Set<string>>(() => {
    const files = changes.value?.enabled ? (changes.value.files || []) : []
    return new Set(files.map((f: any) => f.path))
  })

  async function load() {
    const id = wsId.value
    if (!id) { tree.value = []; changes.value = null; error.value = ''; return }
    loading.value = true; error.value = ''
    try {
      const [files, ch] = await Promise.all([
        listWorkspaceFiles(id),
        getWorkspaceChanges(id).catch(() => null),
      ])
      tree.value = buildFileTree(files || [])
      changes.value = ch
    } catch (e: any) {
      error.value = e?.message || '加载工作区失败'
      tree.value = []
    } finally {
      loading.value = false
    }
  }

  function select(path: string) { selected.value = path }

  return { tree, changes, changed, selected, loading, error, load, select }
}
