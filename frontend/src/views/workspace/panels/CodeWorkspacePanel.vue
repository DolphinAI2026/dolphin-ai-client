<template>
  <div class="code-ws-panel">
    <div class="cwp-tree">
      <FileTree
        :tree="tree"
        :changed="changed"
        :changes="changes"
        :selected="selected"
        :ws-id="wsId || ''"
        @select="(p) => { select(p); focusLine = null }"
        @select-line="(p) => { select(p.path); focusLine = p.line }"
      />
    </div>
    <div class="cwp-view">
      <CodeViewer
        v-if="selected && wsId"
        :ws-id="wsId"
        :file-path="selected"
        :change="selectedChange"
        :focus-line="focusLine"
      />
      <div v-else class="cwp-empty">选择左侧文件查看代码 / 改动</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, onMounted } from 'vue'
import FileTree from '@/views/coding/FileTree.vue'
import CodeViewer from '@/views/coding/CodeViewer.vue'
import { useWorkspaceFiles } from '../useWorkspaceFiles'
import type { Binding } from '../binding'
import type { WorkspaceChangeEntry } from '@/api/coding'

const props = defineProps<{ binding: Binding; sessionId?: number | null; artifact?: any }>()

const wsId = computed(() => (props.binding.kind === 'workspace' ? props.binding.workspaceId : null))

const { tree, changes, changed, selected, select, load } = useWorkspaceFiles(wsId)
const focusLine = ref<number | null>(null)

const selectedChange = computed<WorkspaceChangeEntry | null>(() => {
  const files: WorkspaceChangeEntry[] = changes.value?.files || []
  return files.find((f) => f.path === selected.value) ?? null
})

watch(wsId, () => { void load() }, { immediate: false })
onMounted(() => { void load() })
</script>

<style scoped>
.code-ws-panel {
  display: flex;
  height: 100%;
  min-height: 0;
}
.cwp-tree {
  width: 40%;
  min-width: 220px;
  max-width: 360px;
  border-right: 1px solid var(--line);
  overflow: auto;
}
.cwp-view {
  flex: 1;
  min-width: 0;
  overflow: auto;
}
.cwp-empty {
  padding: 24px;
  opacity: 0.5;
}
</style>
