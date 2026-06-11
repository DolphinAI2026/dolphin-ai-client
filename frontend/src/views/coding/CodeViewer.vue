<template>
  <div class="code-viewer">
    <header v-if="filePath" class="cv-head">
      <AppIcon :name="fileIcon" :size="14" :stroke="1.9" class="cv-head-icon" />
      <span class="cv-path" :title="filePath || ''">
        <span v-if="dir" class="cv-path-dir">&lrm;{{ dir }}/&lrm;</span><span class="cv-path-name">{{ baseName }}</span>
      </span>
      <template v-if="change">
        <span class="cv-counts">
          <span v-if="change.additions" class="cv-counts-add">+{{ change.additions }}</span>
          <span v-if="change.deletions" class="cv-counts-del">−{{ change.deletions }}</span>
        </span>
        <button type="button" class="cv-accept" title="接受此文件变更" @click="emitAcceptChange">接受此文件</button>
        <div v-if="change.status !== 'D'" class="cv-toggle" role="tablist" aria-label="查看模式">
          <button class="cv-toggle-btn" :class="{ active: viewMode === 'diff' }" @click="setMode('diff')">对比</button>
          <button class="cv-toggle-btn" :class="{ active: viewMode === 'full' }" @click="setMode('full')">全文</button>
        </div>
        <span v-else class="cv-badge cv-badge-del">已删除</span>
      </template>
      <span v-else-if="diff" class="cv-badge">改动</span>
      <span v-if="decompiled" class="cv-badge" :title="`由 ${decompiler} 反编译,非原始源码`">反编译视图</span>
    </header>
    <!-- 选中代码浮动引用按钮(fixed 定位,跟选区) -->
    <button
      v-if="quoteBtn"
      class="cv-quote-btn"
      :style="{ left: quoteBtn.x + 'px', top: quoteBtn.y + 'px' }"
      @mousedown.prevent
      @click="emitQuote"
    >引用到对话</button>
    <div class="cv-body" ref="bodyRef" @mouseup="onBodyMouseUp" @scroll.passive="quoteBtn = null">
      <!-- git 基线对比模式 -->
      <template v-if="showGitDiff">
        <div v-if="gitLoading" class="cv-state">
          <span class="cv-spinner" />
          <span>加载对比中…</span>
        </div>
        <div v-else-if="gitBinary" class="cv-state">
          <AppIcon :name="fileIcon" :size="26" :stroke="1.5" />
          <span>二进制文件改动，不支持对比</span>
        </div>
        <DiffView v-else-if="gitDiff" :diff="gitDiff" />
        <div v-else class="cv-state">
          <AppIcon name="file" :size="26" :stroke="1.5" />
          <span>相对基线无改动</span>
        </div>
      </template>
      <FileCard
        v-else-if="diff && hasInlineDiff"
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
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import FileCard from '@/components/FileCard.vue'
import AppIcon from '@/components/common/AppIcon.vue'
import { readWorkspaceFile, downloadWorkspaceFileRaw, getWorkspaceFileDiff, type WorkspaceChangeEntry } from '@/api/coding'
import { highlightCode } from './shikiHighlight'
import DiffView from './DiffView.vue'
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
  /** git 基线改动(优先于 diff): 有则默认进对比模式,可切全文 */
  change?: WorkspaceChangeEntry | null
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

// ── git 基线对比模式 ──
const viewMode = ref<'diff' | 'full'>('full')
const gitDiff = ref('')
const gitBinary = ref(false)
const gitLoading = ref(false)
const showGitDiff = computed(() => !!props.change && viewMode.value === 'diff')

function setMode(m: 'diff' | 'full') {
  if (viewMode.value === m) return
  viewMode.value = m
  void refresh()
}

async function loadGitDiff() {
  if (!props.wsId || !props.filePath) return
  gitLoading.value = true
  gitDiff.value = ''
  gitBinary.value = false
  try {
    const res = await getWorkspaceFileDiff(props.wsId, props.filePath)
    gitBinary.value = !!res.binary
    gitDiff.value = res.enabled ? res.diff : ''
    await nextTick()
    if (bodyRef.value) { bodyRef.value.scrollTop = 0; bodyRef.value.scrollLeft = 0 }
  } catch {
    gitDiff.value = ''
  } finally {
    gitLoading.value = false
  }
}

async function refresh() {
  if (showGitDiff.value) { await loadGitDiff(); return }
  await load()
}

// ── 选中代码 → 引用到对话 ──
const emit = defineEmits<{
  (e: 'quote', payload: { path: string; startLine: number | null; endLine: number | null; text: string }): void
  (e: 'accept-change', path: string): void
}>()

const quoteBtn = ref<{ x: number; y: number } | null>(null)
let pendingQuote: { startLine: number | null; endLine: number | null; text: string } | null = null

function onBodyMouseUp() {
  // 等浏览器把选区定下来再读
  requestAnimationFrame(captureSelection)
}

function captureSelection() {
  quoteBtn.value = null
  if (!props.filePath || !bodyRef.value) return
  const sel = window.getSelection()
  if (!sel || sel.isCollapsed || sel.rangeCount === 0) return
  const range = sel.getRangeAt(0)
  if (!bodyRef.value.contains(range.commonAncestorContainer)) return
  const text = sel.toString().replace(/\n+$/, '')
  if (!text.trim()) return
  pendingQuote = { ...lineRangeOf(range), text }
  const rect = range.getBoundingClientRect()
  quoteBtn.value = { x: rect.left + rect.width / 2, y: rect.bottom + 6 }
}

// 全文视图按 .line 序号；diff 视图读行号 gutter(优先新行号)
function lineRangeOf(range: Range): { startLine: number | null; endLine: number | null } {
  const lineOf = (node: Node): number | null => {
    const el = node instanceof Element ? node : node.parentElement
    if (!el || !bodyRef.value) return null
    const full = el.closest('.shiki .line')
    if (full) {
      const all = Array.from(bodyRef.value.querySelectorAll('.shiki .line'))
      const i = all.indexOf(full)
      return i >= 0 ? i + 1 : null
    }
    const row = el.closest('.dv-row')
    if (row) {
      const no = row.querySelector('.dv-no-new')?.textContent?.trim()
        || row.querySelector('.dv-no-old')?.textContent?.trim()
      const n = parseInt(no || '', 10)
      return Number.isFinite(n) ? n : null
    }
    return null
  }
  let a = lineOf(range.startContainer)
  let b = lineOf(range.endContainer)
  if (a != null && b != null && a > b) [a, b] = [b, a]
  return { startLine: a, endLine: b }
}

function emitQuote() {
  if (!pendingQuote || !props.filePath) return
  emit('quote', { path: props.filePath, ...pendingQuote })
  quoteBtn.value = null
  pendingQuote = null
  window.getSelection()?.removeAllRanges()
}

function emitAcceptChange() {
  if (props.filePath) emit('accept-change', props.filePath)
}

function onDocSelectionChange() {
  const sel = window.getSelection()
  if (!sel || sel.isCollapsed) quoteBtn.value = null
}
document.addEventListener('selectionchange', onDocSelectionChange)
onUnmounted(() => document.removeEventListener('selectionchange', onDocSelectionChange))

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
const hasInlineDiff = computed(() => !!(props.diff?.fileContent || props.diff?.oldContent))

async function load() {
  html.value = ''
  error.value = ''
  binary.value = false
  binaryHint.value = '二进制文件，不支持预览'
  decompiled.value = false
  decompiler.value = ''
  if ((hasInlineDiff.value && !props.change) || !props.filePath || !props.wsId) return
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

watch(
  () => [props.wsId, props.filePath, props.diff, props.change?.path, props.change?.status, props.dark],
  () => {
    // 有 git 改动默认进对比；删除的文件只有对比可看
    viewMode.value = props.change ? 'diff' : 'full'
    void refresh()
  },
  { immediate: true },
)
</script>

<style scoped>
.code-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-width: 0;
  overflow: hidden;
  background: var(--bg, #ffffff);
}
.cv-head {
  display: flex;
  align-items: center;
  gap: 7px;
  flex: none;
  min-height: 44px;
  padding: 9px 16px;
  border-bottom: 1px solid var(--line, rgba(0, 0, 0, 0.07));
  background: linear-gradient(180deg, var(--bg, #ffffff) 0%, var(--bg-sub, #f8fafc) 100%);
}
.cv-head-icon { flex: none; color: var(--fg-dim, #64748b); }
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
  color: var(--fg-faint, #94a3b8);
  flex: 0 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  direction: rtl;
}
.cv-path-name { color: var(--fg, #172033); font-weight: 650; flex: none; }
.cv-badge {
  flex: none;
  font-size: var(--fs-xs, 11px);
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--ai-soft, var(--brand-soft, rgba(99, 102, 241, 0.12)));
  color: var(--ai, var(--brand, #4f46e5));
  font-weight: 500;
}
.cv-badge-del {
  background: color-mix(in srgb, var(--t-danger, #e5484d) 12%, transparent);
  color: var(--t-danger, #e5484d);
}
.cv-counts {
  flex: none;
  display: inline-flex;
  gap: 6px;
  font-family: var(--font-mono, monospace);
  font-size: var(--fs-xs, 11px);
  font-weight: 600;
}
.cv-counts-add { color: var(--t-success, #16a34a); }
.cv-counts-del { color: var(--t-danger, #e5484d); }
.cv-toggle {
  flex: none;
  display: inline-flex;
  border: 1px solid var(--line, rgba(0, 0, 0, 0.1));
  border-radius: var(--r-md, 8px);
  overflow: hidden;
  background: var(--bg, #ffffff);
}
.cv-toggle-btn {
  padding: 2px 10px;
  border: none;
  background: transparent;
  color: var(--fg-dim, #666);
  font-size: var(--fs-xs, 11.5px);
  cursor: pointer;
  transition: background 0.12s var(--ease, ease), color 0.12s var(--ease, ease);
}
.cv-toggle-btn + .cv-toggle-btn { border-left: 1px solid var(--line, rgba(0, 0, 0, 0.1)); }
.cv-toggle-btn.active {
  background: var(--brand-soft, rgba(79, 110, 247, 0.10));
  color: var(--brand-ink, var(--brand, #4f46e5));
  font-weight: 650;
}
.cv-toggle-btn:hover:not(.active) { background: var(--bg-hover, rgba(0, 0, 0, 0.04)); }
.cv-accept {
  flex: none;
  margin-left: auto;
  padding: 2px 9px;
  min-height: 24px;
  border: 1px solid var(--line, rgba(0, 0, 0, 0.1));
  border-radius: var(--r-md, 8px);
  background: var(--bg, #ffffff);
  color: var(--brand-ink, var(--brand, #4f46e5));
  font-size: var(--fs-xs, 11.5px);
  font-weight: 650;
  cursor: pointer;
  transition: background 0.12s var(--ease, ease), border-color 0.12s var(--ease, ease);
}
.cv-accept:hover {
  border-color: color-mix(in srgb, var(--brand, #4f6ef7) 34%, var(--line, rgba(0, 0, 0, 0.1)));
  background: var(--brand-soft, rgba(79, 110, 247, 0.10));
}
.cv-body {
  flex: 1;
  min-height: 0;
  min-width: 0;
  overflow: auto;
  background: var(--bg, #ffffff);
}
.cv-quote-btn {
  position: fixed;
  z-index: 30;
  transform: translateX(-50%);
  padding: 4px 12px;
  border: 1px solid var(--line-strong, var(--line, rgba(0, 0, 0, 0.15)));
  border-radius: 999px;
  background: var(--bg, #fff);
  color: var(--brand-ink, var(--brand, #4f46e5));
  font-size: var(--fs-xs, 12px);
  font-weight: 500;
  cursor: pointer;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.14);
  transition: background 0.12s var(--ease, ease);
}
.cv-quote-btn:hover { background: var(--brand-soft, rgba(99, 102, 241, 0.1)); }
.cv-body :deep(.msg-file-card) {
  margin: 12px;
  border-color: var(--line, rgba(15, 23, 42, 0.08));
  box-shadow: 0 8px 22px rgba(15, 23, 42, 0.04);
}
.cv-code { padding: 10px 0 18px; width: max-content; min-width: 100%; }
.cv-code :deep(.shiki) { background: transparent !important; margin: 0; }
.cv-code :deep(.shiki code) { counter-reset: ln; display: block; font-family: var(--font-mono, monospace); font-size: 12.5px; line-height: 1.52; }
.cv-code :deep(.shiki .line) {
  display: block;
  white-space: pre;
  padding-right: 16px;
}
.cv-code :deep(.shiki .line:hover) {
  background: var(--bg-hover, rgba(79, 110, 247, 0.045));
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
  color: var(--fg-faint, #c0cad8);
  background: var(--bg, #ffffff);
  user-select: none;
}
.cv-code :deep(.shiki .line:hover)::before {
  color: var(--fg-dim, #718096);
  background: var(--bg-hover, #f5f8fd);
}
.cv-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  height: 100%;
  color: var(--fg-dim, #64748b);
  font-size: var(--fs-sm, 13px);
}
.cv-empty :deep(.app-icon),
.cv-binary :deep(.app-icon) {
  width: 46px;
  height: 46px;
  padding: 11px;
  box-sizing: border-box;
  border-radius: 12px;
  background: var(--bg-sub, #f1f5fb);
  color: var(--fg-dim, #64748b);
  opacity: 1;
}
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
