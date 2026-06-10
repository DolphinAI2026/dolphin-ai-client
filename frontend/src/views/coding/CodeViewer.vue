<template>
  <div class="code-viewer">
    <header v-if="filePath" class="cv-head">
      <AppIcon :name="fileIcon" :size="14" :stroke="1.9" class="cv-head-icon" />
      <span class="cv-path" :title="filePath || ''">
        <span v-if="dir" class="cv-path-dir">&lrm;{{ dir }}/&lrm;</span><span class="cv-path-name">{{ baseName }}</span>
      </span>
      <span v-if="diff" class="cv-badge">改动</span>
      <span v-if="decompiled" class="cv-badge" :title="`由 ${decompiler} 反编译,非原始源码`">反编译视图</span>
    </header>
    <div class="cv-body" ref="bodyRef">
      <FileCard
        v-if="diff"
        action="edit"
        :file-name="filePath || ''"
        :file-content="diff.fileContent"
        :old-content="diff.oldContent"
      />
      <div v-else-if="loading" class="cv-state">
        <span class="cv-spinner" />
        <span>加载中…</span>
      </div>
      <div v-else-if="binary" class="cv-state cv-binary">
        <AppIcon :name="fileIcon" :size="30" :stroke="1.5" />
        <span class="cv-binary-name">{{ baseName }}</span>
        <span class="cv-binary-hint">{{ binaryHint }}</span>
        <button class="cv-download" :disabled="downloading" @click="downloadFile">
          <AppIcon name="download" :size="14" :stroke="1.9" />
          <span>{{ downloading ? '下载中…' : '下载文件' }}</span>
        </button>
      </div>
      <div v-else-if="error" class="cv-state cv-state-error">
        <AppIcon name="warning" :size="18" />
        <span>{{ error }}</span>
        <button class="cv-retry" @click="load">重试</button>
      </div>
      <div v-else-if="filePath" class="cv-code" v-html="html" />
      <div v-else class="cv-state cv-empty">
        <AppIcon name="file" :size="26" :stroke="1.5" />
        <span>从左侧选择文件查看代码</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import FileCard from '@/components/FileCard.vue'
import AppIcon from '@/components/common/AppIcon.vue'
import { readWorkspaceFile, downloadWorkspaceFileRaw } from '@/api/coding'
import { highlightCode } from './shikiHighlight'
import type { FileChange } from './workspaceChanges'

const BINARY_EXT = new Set([
  'zip', 'tar', 'gz', 'tgz', 'rar', '7z',
  'png', 'jpg', 'jpeg', 'gif', 'webp', 'ico', 'bmp',
  'pdf', 'woff', 'woff2', 'ttf', 'eot', 'otf',
  'mp4', 'mp3', 'wav', 'mov', 'avi',
  'exe', 'bin', 'so', 'dll', 'jar',
  'psd', 'sketch', 'xlsx', 'xls', 'docx', 'doc', 'ppt', 'pptx',
])

const props = defineProps<{
  wsId: string
  filePath: string | null
  diff?: FileChange | null
  dark?: boolean
}>()

const html = ref('')
const loading = ref(false)
const error = ref('')
const binary = ref(false)
const binaryHint = ref('二进制文件，不支持预览')
const decompiled = ref(false)
const decompiler = ref('')
const downloading = ref(false)
const bodyRef = ref<HTMLElement>()

const isBinaryExt = computed(() => BINARY_EXT.has(baseName.value.split('.').pop()?.toLowerCase() || ''))

const baseName = computed(() => props.filePath?.split('/').pop() || '')
const dir = computed(() => {
  const p = props.filePath || ''
  const i = p.lastIndexOf('/')
  return i >= 0 ? p.slice(0, i) : ''
})
const fileIcon = computed(() => {
  const ext = baseName.value.split('.').pop()?.toLowerCase() || ''
  if (['md', 'mdc', 'txt'].includes(ext)) return 'doc'
  if (['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'ico'].includes(ext)) return 'image'
  if (['json', 'yaml', 'yml', 'config'].includes(ext)) return 'settings'
  return 'file'
})

async function load() {
  html.value = ''
  error.value = ''
  binary.value = false
  binaryHint.value = '二进制文件，不支持预览'
  decompiled.value = false
  decompiler.value = ''
  if (props.diff || !props.filePath || !props.wsId) return
  // 已知二进制扩展名直接走下载面板,不去拉文本(避免 utf-8 解码报错)
  if (isBinaryExt.value) { binary.value = true; return }
  loading.value = true
  try {
    const res = await readWorkspaceFile(props.wsId, props.filePath)
    decompiled.value = !!res.decompiled
    decompiler.value = res.decompiler || ''
    html.value = await highlightCode(res.content, props.filePath, !!props.dark)
    // 换文件时把滚动复位到左上角,避免沿用上一个文件的横/纵滚动位置
    await nextTick()
    if (bodyRef.value) { bodyRef.value.scrollTop = 0; bodyRef.value.scrollLeft = 0 }
  } catch (e: any) {
    const detail = String(e?.response?.data?.detail || e?.message || '')
    const isClassFile = baseName.value.toLowerCase().endsWith('.class')
    // 后端读 utf-8 失败 = 其实是二进制文件 → 也走下载面板,不显示红色报错
    // .class 反编译失败同理,落下载面板并带上后端的人话原因
    if (isClassFile || /codec|decode byte|utf-8/i.test(detail)) {
      binary.value = true
      if (isClassFile && detail) binaryHint.value = detail
    } else {
      error.value = detail || '读取文件失败'
    }
  } finally {
    loading.value = false
  }
}

async function downloadFile() {
  if (!props.filePath || !props.wsId || downloading.value) return
  downloading.value = true
  try {
    const blob = await downloadWorkspaceFileRaw(props.wsId, props.filePath)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = baseName.value
    document.body.appendChild(a)
    a.click()
    a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch {
    /* 下载失败，忽略 */
  } finally {
    downloading.value = false
  }
}

watch(() => [props.wsId, props.filePath, props.diff, props.dark], load, { immediate: true })
</script>

<style scoped>
.code-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-width: 0;
  overflow: hidden;
  background: var(--bg, #fff);
}
.cv-head {
  display: flex;
  align-items: center;
  gap: 7px;
  flex: none;
  padding: 8px 14px;
  border-bottom: 1px solid var(--line, rgba(0, 0, 0, 0.07));
  background: var(--bg-sub, var(--bg, #fff));
}
.cv-head-icon { flex: none; color: var(--fg-faint, #999); }
.cv-path {
  display: inline-flex;
  align-items: baseline;
  font-family: var(--font-mono, monospace);
  font-size: var(--fs-sm, 12.5px);
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
}
/* 目录段从左侧省略(direction:rtl 截断技巧, &lrm; 防斜杠跳位), 文件名永不截断 */
.cv-path-dir {
  color: var(--fg-faint, #aaa);
  flex: 0 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  direction: rtl;
}
.cv-path-name { color: var(--fg, #222); font-weight: 500; flex: none; }
.cv-badge {
  flex: none;
  font-size: var(--fs-xs, 11px);
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--ai-soft, var(--brand-soft, rgba(99, 102, 241, 0.12)));
  color: var(--ai, var(--brand, #4f46e5));
  font-weight: 500;
}
.cv-body { flex: 1; min-height: 0; min-width: 0; overflow: auto; }
.cv-code { padding: 6px 0 14px; width: max-content; min-width: 100%; }
.cv-code :deep(.shiki) { background: transparent !important; margin: 0; }
.cv-code :deep(.shiki code) { counter-reset: ln; display: block; font-family: var(--font-mono, monospace); font-size: 12.5px; line-height: 1.45; }
.cv-code :deep(.shiki .line) {
  display: block;
  white-space: pre;
  padding-right: 16px;
}
/* 行号 = 固定左侧 gutter(sticky),横向滚动时不跟着滚走(对标 Codex/VS Code) */
.cv-code :deep(.shiki .line)::before {
  counter-increment: ln;
  content: counter(ln);
  position: sticky;
  left: 0;
  z-index: 1;
  display: inline-block;
  width: 2.6em;
  margin-right: 1.1em;
  padding-right: 0.7em;
  text-align: right;
  color: var(--fg-faint, #bbb);
  background: var(--bg, #fff);
  user-select: none;
}
.cv-code :deep(.shiki .line:hover)::before { color: var(--fg-dim, #888); }
.cv-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  height: 100%;
  color: var(--fg-faint, #aaa);
  font-size: var(--fs-sm, 13px);
}
.cv-empty :deep(.app-icon) { opacity: 0.5; }
.cv-binary :deep(.app-icon) { opacity: 0.6; }
.cv-binary-name { color: var(--fg, #333); font-weight: 500; font-family: var(--font-mono, monospace); font-size: var(--fs-sm, 13px); }
.cv-binary-hint { font-size: var(--fs-xs, 12px); }
.cv-download {
  margin-top: 4px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 16px;
  border: 1px solid var(--line-strong, var(--line, rgba(0, 0, 0, 0.15)));
  border-radius: var(--r-sm, 6px);
  background: var(--bg, #fff);
  color: var(--brand-ink, var(--brand, #4f46e5));
  font-size: var(--fs-sm, 13px);
  cursor: pointer;
  transition: background 0.12s var(--ease, ease);
}
.cv-download:hover:not(:disabled) { background: var(--brand-soft, rgba(99, 102, 241, 0.1)); }
.cv-download:disabled { opacity: 0.6; cursor: default; }
.cv-state-error { color: var(--err, #ef4444); }
.cv-retry {
  padding: 4px 14px;
  border: 1px solid var(--line, rgba(0, 0, 0, 0.12));
  border-radius: var(--r-sm, 6px);
  background: var(--bg, #fff);
  color: var(--fg, #333);
  font-size: var(--fs-sm, 13px);
  cursor: pointer;
}
.cv-retry:hover { background: var(--bg-hover, rgba(0, 0, 0, 0.04)); }
.cv-spinner {
  width: 18px; height: 18px;
  border: 2px solid var(--line, rgba(0, 0, 0, 0.15));
  border-top-color: var(--brand, #6366f1);
  border-radius: 50%;
  animation: cv-spin 0.7s linear infinite;
}
@keyframes cv-spin { to { transform: rotate(360deg); } }
</style>
