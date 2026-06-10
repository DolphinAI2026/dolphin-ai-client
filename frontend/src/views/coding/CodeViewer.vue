<template>
  <div class="code-viewer">
    <div class="cv-path">{{ filePath || '未选择文件' }}</div>
    <div class="cv-body">
      <FileCard
        v-if="diff"
        action="edit"
        :file-name="filePath || ''"
        :file-content="diff.fileContent"
        :old-content="diff.oldContent"
      />
      <div v-else-if="loading" class="cv-hint">加载中…</div>
      <div v-else-if="error" class="cv-hint cv-error">{{ error }} <button @click="load">重试</button></div>
      <div v-else-if="filePath" class="cv-code" v-html="html" />
      <div v-else class="cv-hint">从左侧选择文件查看</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import FileCard from '@/components/FileCard.vue'
import { readWorkspaceFile } from '@/api/coding'
import { highlightCode } from './shikiHighlight'
import type { FileChange } from './workspaceChanges'

const props = defineProps<{
  wsId: string
  filePath: string | null
  diff?: FileChange | null
  dark?: boolean
}>()

const html = ref('')
const loading = ref(false)
const error = ref('')

async function load() {
  html.value = ''
  error.value = ''
  if (props.diff || !props.filePath || !props.wsId) return
  loading.value = true
  try {
    const res = await readWorkspaceFile(props.wsId, props.filePath)
    html.value = await highlightCode(res.content, props.filePath, !!props.dark)
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '读取文件失败'
  } finally {
    loading.value = false
  }
}

watch(() => [props.wsId, props.filePath, props.diff, props.dark], load, { immediate: true })
</script>

<style scoped>
.code-viewer { display: flex; flex-direction: column; height: 100%; min-width: 0; }
.cv-path { padding: 6px 12px; border-bottom: 0.5px solid var(--ac-border, rgba(0,0,0,.1)); font-family: monospace; font-size: 12px; color: var(--ac-text-secondary, #888); }
.cv-body { flex: 1; overflow: auto; padding: 8px 0; }
.cv-code :deep(pre) { margin: 0; padding: 0 12px; font-size: 12px; line-height: 1.7; background: transparent !important; }
.cv-hint { padding: 16px; color: var(--ac-text-secondary, #888); font-size: 13px; }
.cv-error { color: var(--ac-danger, #f56c6c); }
</style>
