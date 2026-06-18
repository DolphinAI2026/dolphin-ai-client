<template>
  <div class="artifact-panel">
    <div v-if="loading" class="aa-art-loading">加载中…</div>
    <template v-else>
      <div class="aa-art-actions">
        <button class="aa-art-copy" type="button" @click="copyContent">复制全文</button>
        <button class="aa-art-copy" type="button" @click="downloadContent">下载</button>
      </div>
      <div
        v-if="content && storage !== 'html'"
        class="aa-art-md md"
        v-html="renderMd(content)"
      ></div>
      <!-- HTML 产物: 不给 allow-scripts，防止越权读 token -->
      <iframe
        v-else-if="content && storage === 'html'"
        class="aa-art-iframe"
        :srcdoc="content"
        sandbox="allow-same-origin"
      ></iframe>
      <div v-else class="aa-art-empty">文档内容为空</div>
    </template>
  </div>
</template>
<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { aiChatApi } from '@/api/aiChat'
import { renderMd } from '@/utils/markdown'

const props = defineProps<{
  sessionId: number | null
  artifact: any
}>()

const content = ref('')
const loading = ref(false)
const storage = ref<string>('text')

async function loadArtifact() {
  if (!props.artifact) return
  const name: string = props.artifact.filename || '设计文档'
  storage.value = props.artifact.storage || 'text'
  const ver =
    props.artifact.version != null && !Number.isNaN(Number(props.artifact.version))
      ? Number(props.artifact.version)
      : undefined

  // 二进制产物(storage='file'): 无文本正文, 提示下载
  if (storage.value === 'file') {
    content.value = `**${name}** 是二进制产物，点上方「下载」获取文件。`
    return
  }

  if (props.sessionId == null) {
    content.value = props.artifact.preview || ''
    return
  }

  loading.value = true
  try {
    const detail = await aiChatApi.getArtifact(props.sessionId, props.artifact.filename, ver)
    content.value = detail.content || props.artifact.preview || ''
  } catch {
    ElMessage.error('加载设计文档失败')
    content.value = props.artifact.preview || ''
  } finally {
    loading.value = false
  }
}

function copyContent() {
  if (!content.value) return
  navigator.clipboard
    .writeText(content.value)
    .then(() => ElMessage.success('已复制'))
    .catch(() => {})
}

function downloadContent() {
  const name: string = props.artifact?.filename || 'document.md'
  const ver =
    props.artifact?.version != null && !Number.isNaN(Number(props.artifact?.version))
      ? Number(props.artifact?.version)
      : undefined
  // 二进制产物走后端下载端点
  if (storage.value === 'file' && props.sessionId != null) {
    const a = document.createElement('a')
    a.href = aiChatApi.artifactDownloadUrl(props.sessionId, name, ver)
    a.download = name
    a.click()
    return
  }
  if (!content.value) return
  const blob = new Blob([content.value], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}

onMounted(loadArtifact)
watch(() => props.artifact, loadArtifact, { deep: true })
</script>

<style scoped>
.artifact-panel { padding: 4px 2px 24px; overflow: auto; height: 100%; }
.aa-art-loading, .aa-art-empty {
  padding: 40px 0; text-align: center; color: var(--text-3); font-size: 13px;
}
.aa-art-actions { display: flex; justify-content: flex-end; margin-bottom: 10px; }
.aa-art-copy {
  appearance: none; border: 1px solid var(--line); background: var(--surface-2);
  color: var(--text-2); padding: 4px 12px; font-size: 12px; border-radius: 6px;
  cursor: pointer; transition: color .15s, border-color .15s;
  margin-left: 8px;
}
.aa-art-copy:hover { color: var(--text); border-color: var(--text-3); }
.aa-art-md {
  font-size: 13px; line-height: 1.7; color: var(--text);
  white-space: normal; word-break: break-word;
}
.aa-art-md :deep(h1) { font-size: 18px; margin: 16px 0 8px; font-weight: 600; }
.aa-art-md :deep(h2) { font-size: 15px; margin: 14px 0 6px; font-weight: 600; }
.aa-art-md :deep(h3) { font-size: 13.5px; margin: 12px 0 6px; font-weight: 600; }
.aa-art-md :deep(p) { margin: 0 0 8px; }
.aa-art-md :deep(ul), .aa-art-md :deep(ol) { margin: 4px 0 10px 20px; padding: 0; }
.aa-art-md :deep(li) { margin-bottom: 2px; }
.aa-art-md :deep(table) { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 12px; }
.aa-art-md :deep(th), .aa-art-md :deep(td) { border: 1px solid var(--line); padding: 5px 9px; }
.aa-art-md :deep(th) { background: var(--surface-2); }
.aa-art-md :deep(code) {
  background: var(--surface-2); padding: 1px 6px; border-radius: 3px; color: #f0824a;
  font-family: ui-monospace, Menlo, monospace; font-size: 11.5px;
}
.aa-art-md :deep(pre) {
  background: var(--surface-2); border: 1px solid var(--line);
  border-radius: 6px; padding: 10px 12px; overflow-x: auto;
}
.aa-art-md :deep(pre code) { background: transparent; padding: 0; color: var(--text); }
.aa-art-md :deep(a) { color: var(--brand); }
.aa-art-md :deep(blockquote) {
  border-left: 3px solid var(--line); padding-left: 10px;
  color: var(--text-3); margin: 8px 0;
}
.aa-art-iframe {
  width: 100%; height: 100%; min-height: 400px; border: none;
  border-radius: 6px; background: var(--surface-2);
}
</style>
