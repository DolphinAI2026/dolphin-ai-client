<template>
  <WorkbenchShell>
    <div class="ra-page">
      <div v-if="loading" class="ra-loading">
        <span class="spinner">⟳</span>
        <span>加载 AI 需求分析助手...</span>
      </div>

      <div v-else-if="!agentCode" class="ra-not-configured">
        <div class="ra-not-configured-icon">⚙️</div>
        <div class="ra-not-configured-title">尚未配置 AI 需求分析助手</div>
        <div class="ra-not-configured-hint">
          请联系管理员在 backend <code>.env</code> 中设置
          <code>DOLPHIN_REQUIREMENTS_AGENT_CODE</code> 后重启后端服务。
        </div>
      </div>

      <div v-else class="ra-split">
        <div class="ra-chat-pane">
          <DolphinAgentEmbed :agent-code="agentCode" title="AI 需求分析助手" />
        </div>
        <div class="ra-artifact-pane">
          <div class="ra-artifact-header">
            <span class="ra-art-title">📄 设计文档</span>
            <span v-if="docState === 'auto'" class="ra-art-badge auto">自动同步 ✓</span>
            <span v-else-if="docState === 'manual'" class="ra-art-badge manual">手动粘贴</span>
            <span v-else class="ra-art-badge empty">等待 agent 输出</span>
          </div>

          <div class="ra-artifact-meta" v-if="hasDoc">
            <input
              v-model="docFileName"
              class="ra-art-filename"
              placeholder="文件名（如 sales-order-design.md）"
            />
            <span v-if="docScore > 0" class="ra-art-score" :class="docScoreClass">
              自检 {{ docScore }}/100
            </span>
          </div>

          <div class="ra-artifact-body">
            <div v-if="!hasDoc" class="ra-empty-guide">
              <div class="ra-empty-icon">⏳</div>
              <div class="ra-empty-title">等 agent 写完，自动同步到这里</div>
              <ol class="ra-empty-steps">
                <li>左侧跟需求分析助手对话，让它产出完整 6 章 markdown 设计文档</li>
                <li>每 5 秒自动从 dolphin 拉一次最新对话，识别到 markdown 块就自动 fill</li>
                <li>右上角徽章变绿色「自动同步 ✓」表示拿到了；自检分数也会显示</li>
                <li>点右下角 <strong>→ Builder</strong> 一键创建 / 更新应用</li>
              </ol>
              <div class="ra-empty-hint">
                💡 没等到也可以直接粘贴 markdown 到编辑框（自动抓取兜底）。
              </div>
              <textarea
                v-model="docMd"
                class="ra-empty-textarea"
                placeholder="⬇ 在这里粘贴 markdown 设计文档..."
                spellcheck="false"
                @input="onUserEdit"
              />
            </div>
            <div v-else class="ra-art-doc">
              <div class="ra-art-tabs">
                <button
                  class="ra-tab"
                  :class="{ active: viewMode === 'preview' }"
                  @click="viewMode = 'preview'"
                >👁 渲染</button>
                <button
                  class="ra-tab"
                  :class="{ active: viewMode === 'edit' }"
                  @click="viewMode = 'edit'"
                >✏️ 编辑</button>
                <span class="ra-tab-meta">{{ docMd.length }} 字符</span>
              </div>
              <div
                v-if="viewMode === 'preview'"
                class="ra-art-preview markdown-body"
                v-html="renderedMd"
              />
              <textarea
                v-else
                v-model="docMd"
                class="ra-art-textarea"
                spellcheck="false"
                @input="onUserEdit"
              />
            </div>
          </div>

          <div class="ra-artifact-footer">
            <button class="ra-btn-secondary" :disabled="!hasDoc" @click="copyMd">
              {{ copyState }}
            </button>
            <button class="ra-btn-secondary" :disabled="!hasDoc" @click="downloadMd">
              下载
            </button>
            <button class="ra-btn-secondary" :disabled="!hasDoc" @click="clearMd">
              清空
            </button>
            <button
              class="ra-btn-primary"
              :disabled="!hasDoc || sendingToBuilder"
              @click="sendToBuilder"
            >
              {{ sendingToBuilder ? '处理中...' : '→ Builder' }}
            </button>
          </div>
        </div>
      </div>

      <ChooseAppTargetDialog
        v-model="chooseDialogVisible"
        :filename="chooseDialogFilename"
        :suggested-name="chooseDialogSuggestedName"
        :candidates="chooseDialogCandidates"
        :loading="chooseDialogLoading"
        @confirm="handleChooseConfirm"
      />
    </div>
  </WorkbenchShell>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { marked } from 'marked'
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import DolphinAgentEmbed from '@/components/DolphinAgentEmbed.vue'
import ChooseAppTargetDialog from '@/components/ChooseAppTargetDialog.vue'
import request from '@/utils/request'
import { applicationApi } from '@/api/application'
import { usePreviewStore } from '@/stores/preview'

marked.setOptions({ breaks: true, gfm: true })

const router = useRouter()
const previewStore = usePreviewStore()

const loading = ref(true)
const agentCode = ref('')

interface DolphinConfig {
  requirements_agent_code?: string
}

// ── ArtifactPanel state ──────────────────────────────────────────────
const docMd = ref('')
const docFileName = ref('')
const docScore = ref(0)
const docPendingId = ref<string | null>(null)
const docSource = ref<'auto' | 'manual' | ''>('')
const viewMode = ref<'preview' | 'edit'>('preview')

const renderedMd = computed(() => {
  if (!docMd.value) return ''
  try {
    return marked.parse(docMd.value) as string
  } catch {
    return `<pre>${docMd.value}</pre>`
  }
})

const hasDoc = computed(() => !!docMd.value.trim())
const docState = computed<'auto' | 'manual' | 'empty'>(() => {
  if (!hasDoc.value) return 'empty'
  return docSource.value === 'auto' ? 'auto' : 'manual'
})
const docScoreClass = computed(() => {
  if (docScore.value >= 95) return 'high'
  if (docScore.value >= 90) return 'mid'
  return 'low'
})
const emptyPlaceholder = computed(() => {
  return [
    '在左侧跟需求分析助手对话，让它整合需求并产出标准 6 章 markdown 设计文档。',
    '',
    'agent 输出后会自动同步到这里；',
    '也可以手动把 ```markdown code block 里的内容粘贴到这里，',
    '然后点右下角「→ Builder」一键创建 / 更新应用。',
  ].join('\n')
})

// ── 自动模式：5s 轮询 backend cache ──
let pollTimer: number | null = null
async function pollLatestDoc() {
  if (!agentCode.value) return
  try {
    const res = await request.get<unknown, {
      has_doc?: boolean
      pending_id?: string
      file_name?: string
      md_content?: string
      score?: number
    }>('/requirements/latest-doc')
    if (!res?.has_doc) return
    // 已是当前展示的版本，跳过
    if (res.pending_id === docPendingId.value) return
    // 用户在本地已手动改过且非空 → 不覆盖（避免抢用户输入）
    if (docSource.value === 'manual' && hasDoc.value) return
    docMd.value = res.md_content || ''
    docFileName.value = res.file_name || 'design-doc.md'
    docScore.value = res.score || 0
    docPendingId.value = res.pending_id || null
    docSource.value = 'auto'
    ElMessage.success(`AI 已生成新版设计文档（${res.file_name}）`)
  } catch (e) {
    // 静默 — 没拿到就保持当前 UI
  }
}

function onUserEdit() {
  // 用户在 textarea 真正键入/粘贴时调用 — 切到 manual 模式
  // auto fill 是 ref 直接赋值，不会触发 @input，所以不会被误切
  if (docSource.value === 'auto') {
    docSource.value = 'manual'
    docPendingId.value = null  // 用户改了，原 cache 失效
  } else if (docSource.value === '') {
    docSource.value = 'manual'
  }
}

// ── 工具栏 actions ──
const copyState = ref('复制')
async function copyMd() {
  try {
    await navigator.clipboard.writeText(docMd.value)
    copyState.value = '已复制 ✓'
    setTimeout(() => { copyState.value = '复制' }, 1500)
  } catch {
    copyState.value = '复制失败'
    setTimeout(() => { copyState.value = '复制' }, 1500)
  }
}

function downloadMd() {
  const blob = new Blob([docMd.value], { type: 'text/markdown' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = docFileName.value || 'design-doc.md'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function clearMd() {
  docMd.value = ''
  docFileName.value = ''
  docScore.value = 0
  docPendingId.value = null
  docSource.value = ''
}

// ── → Builder：复用 ChooseAppTargetDialog 链路 ──
const chooseDialogVisible = ref(false)
const chooseDialogLoading = ref(false)
const chooseDialogCandidates = ref<Array<{ id: number; app_name: string; app_code: string; status: string; apaas_app_id?: string | null; updated_at?: string | null }>>([])
const chooseDialogFilename = ref('')
const chooseDialogSuggestedName = ref('')
const chooseDialogContent = ref('')
const sendingToBuilder = ref(false)

function extractAppNameFromMd(md: string): string {
  if (!md) return ''
  const m = md.match(/^\s*#\s+([^\n]+?)\s*$/m)
  if (m) return m[1].trim().slice(0, 60)
  return ''
}
function fallbackNameFromFilename(filename: string): string {
  return (filename || '')
    .replace(/\.(md|markdown)$/i, '')
    .replace(/[-_\s]*(设计文档|需求文档|设计说明|需求说明|design|spec)$/i, '')
    .trim()
}

async function sendToBuilder() {
  if (!hasDoc.value) return
  sendingToBuilder.value = true
  try {
    // 如果是自动模式有 pending_id → 顺带 consume 一下，避免下次轮询又显示同一份
    if (docSource.value === 'auto' && docPendingId.value) {
      try {
        await request.post(`/requirements/consume-doc/${docPendingId.value}`)
      } catch { /* 不影响主流程 */ }
    }
    const filename = docFileName.value || 'design-doc.md'
    chooseDialogFilename.value = filename
    chooseDialogContent.value = docMd.value
    const inferred = extractAppNameFromMd(docMd.value) || fallbackNameFromFilename(filename)
    chooseDialogSuggestedName.value = inferred
    chooseDialogCandidates.value = []
    chooseDialogVisible.value = true
    if (inferred) {
      chooseDialogLoading.value = true
      try {
        chooseDialogCandidates.value = await applicationApi.matchByName(inferred, 5)
      } catch { /* 列表为空也能用「新建」 */ }
      chooseDialogLoading.value = false
    }
  } finally {
    sendingToBuilder.value = false
  }
}

function handleChooseConfirm(payload: { mode: 'new' } | { mode: 'update'; appId: number; appName: string }) {
  if (payload.mode === 'new') {
    previewStore.pendingMarkdown = {
      filename: chooseDialogFilename.value,
      content: chooseDialogContent.value,
      sourceSessionId: null,
    }
    ElMessage.success('已发送，正在打开 Builder 创建新应用...')
    router.push({ path: '/chat', query: { from: 'aichat' } })
  } else {
    previewStore.pendingDocUpdate = {
      appId: payload.appId,
      filename: chooseDialogFilename.value,
      content: chooseDialogContent.value,
      sourceSessionId: null,
    }
    ElMessage.success(`已发送，正在打开应用 #${payload.appId} 走更新流程...`)
    router.push({ path: '/chat', query: { app_id: String(payload.appId), from: 'aichat' } })
  }
}

// ── 生命周期 ──
onMounted(async () => {
  try {
    const cfg = await request.get<unknown, DolphinConfig>('/dolphin/config')
    agentCode.value = cfg?.requirements_agent_code || ''
  } catch (e) {
    console.warn('[RequirementsAssistant] /dolphin/config failed', e)
  } finally {
    loading.value = false
  }
  // 进页就拉一次，之后 5s 轮询
  if (agentCode.value) {
    await pollLatestDoc()
    pollTimer = window.setInterval(pollLatestDoc, 5000)
  }
})

onBeforeUnmount(() => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
})
</script>

<style scoped>
.ra-page {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  background: var(--t-bg, #fff);
}
.ra-loading,
.ra-not-configured {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--t-text-muted);
  font-size: 14px;
}
.ra-not-configured-icon {
  font-size: 36px;
  opacity: 0.7;
}
.ra-not-configured-title {
  font-size: 15px;
  color: var(--t-text-primary);
  font-weight: 600;
}
.ra-not-configured-hint {
  font-size: 13px;
  text-align: center;
  max-width: 480px;
  line-height: 1.6;
}
.ra-not-configured-hint code {
  background: var(--t-bg-input);
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 12px;
}

/* ── 左右分屏 ── */
.ra-split {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 0;
}
.ra-chat-pane {
  flex: 0 0 60%;
  min-width: 0;
  border-right: 1px solid var(--t-border-subtle);
  display: flex;
  flex-direction: column;
}
.ra-artifact-pane {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: var(--t-bg-subtle, #fafafa);
}

/* ── ArtifactPanel ── */
.ra-artifact-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--t-border-subtle);
}
.ra-art-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--t-text-primary);
  flex: 1;
}
.ra-art-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  font-weight: 500;
}
.ra-art-badge.auto {
  color: #047857;
  background: #d1fae5;
}
.ra-art-badge.manual {
  color: #1d4ed8;
  background: #dbeafe;
}
.ra-art-badge.empty {
  color: #6b7280;
  background: #e5e7eb;
}

.ra-artifact-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 16px;
  border-bottom: 1px solid var(--t-border-subtle);
  background: var(--t-bg, #fff);
}
.ra-art-filename {
  flex: 1;
  height: 28px;
  padding: 0 8px;
  font-size: 13px;
  border: 1px solid var(--t-border-subtle);
  border-radius: 4px;
  background: var(--t-bg, #fff);
  color: var(--t-text-primary);
}
.ra-art-score {
  font-size: 12px;
  padding: 3px 8px;
  border-radius: 4px;
  font-weight: 500;
  white-space: nowrap;
}
.ra-art-score.high { color: #047857; background: #d1fae5; }
.ra-art-score.mid  { color: #b45309; background: #fef3c7; }
.ra-art-score.low  { color: #b91c1c; background: #fee2e2; }

.ra-artifact-body {
  flex: 1;
  min-height: 0;
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.ra-empty-guide {
  background: linear-gradient(135deg, #eff6ff, #f0f9ff);
  border: 1px dashed #93c5fd;
  border-radius: 8px;
  padding: 16px 18px;
  flex-shrink: 0;
}
.ra-empty-icon {
  font-size: 24px;
  margin-bottom: 6px;
}
.ra-empty-title {
  font-size: 14px;
  font-weight: 600;
  color: #1e40af;
  margin-bottom: 10px;
}
.ra-empty-steps {
  margin: 0 0 10px 0;
  padding-left: 20px;
  font-size: 12.5px;
  color: #1e40af;
  line-height: 1.7;
}
.ra-empty-steps strong {
  color: #4338ca;
  background: #e0e7ff;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 12px;
}
.ra-empty-hint {
  font-size: 11.5px;
  color: #6b7280;
  border-top: 1px dashed #cbd5e1;
  padding-top: 8px;
  line-height: 1.55;
}
.ra-art-textarea {
  flex: 1;
  width: 100%;
  resize: none;
  border: 1px solid var(--t-border-subtle);
  border-radius: 6px;
  padding: 12px;
  font-family: 'SF Mono', 'JetBrains Mono', Menlo, Consolas, monospace;
  font-size: 12.5px;
  line-height: 1.65;
  color: var(--t-text-primary);
  background: var(--t-bg, #fff);
  outline: none;
  min-height: 200px;
}
.ra-empty-textarea {
  width: 100%;
  margin-top: 12px;
  min-height: 100px;
  resize: vertical;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  padding: 10px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.6;
  background: #fff;
  color: #1f2937;
  outline: none;
}
.ra-empty-textarea:focus {
  border-color: #6366f1;
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.15);
}

/* ── 渲染 / 编辑双模 tabs ── */
.ra-art-doc {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.ra-art-tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 8px;
  padding: 4px 4px;
  background: var(--t-bg-input, #f3f4f6);
  border-radius: 6px;
}
.ra-tab {
  padding: 4px 12px;
  font-size: 12.5px;
  border: none;
  background: transparent;
  color: var(--t-text-secondary);
  cursor: pointer;
  border-radius: 4px;
  transition: all 0.15s;
}
.ra-tab:hover { color: var(--t-text-primary); }
.ra-tab.active {
  background: var(--t-bg, #fff);
  color: var(--t-text-primary);
  font-weight: 500;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06);
}
.ra-tab-meta {
  margin-left: auto;
  padding-right: 8px;
  font-size: 11px;
  color: var(--t-text-muted);
}

/* ── markdown 渲染区（github-like） ── */
.ra-art-preview {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 16px 20px;
  background: var(--t-bg, #fff);
  border: 1px solid var(--t-border-subtle);
  border-radius: 6px;
  font-size: 13.5px;
  line-height: 1.7;
  color: var(--t-text-primary);
}
.ra-art-preview :deep(h1) {
  margin: 0 0 16px;
  font-size: 22px;
  font-weight: 700;
  border-bottom: 2px solid var(--t-border-subtle);
  padding-bottom: 10px;
}
.ra-art-preview :deep(h2) {
  margin: 22px 0 10px;
  font-size: 17px;
  font-weight: 600;
  color: #1d4ed8;
  padding-bottom: 4px;
  border-bottom: 1px solid var(--t-border-subtle);
}
.ra-art-preview :deep(h3) {
  margin: 16px 0 8px;
  font-size: 14.5px;
  font-weight: 600;
  color: var(--t-text-primary);
}
.ra-art-preview :deep(p) { margin: 8px 0; }
.ra-art-preview :deep(ul),
.ra-art-preview :deep(ol) { padding-left: 22px; margin: 6px 0; }
.ra-art-preview :deep(li) { margin: 3px 0; }
.ra-art-preview :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 10px 0;
  font-size: 12.5px;
}
.ra-art-preview :deep(th),
.ra-art-preview :deep(td) {
  border: 1px solid var(--t-border-subtle, #e5e7eb);
  padding: 6px 10px;
  text-align: left;
}
.ra-art-preview :deep(th) {
  background: var(--t-bg-input, #f9fafb);
  font-weight: 600;
}
.ra-art-preview :deep(tr:nth-child(even)) {
  background: var(--t-bg-subtle, #fafafa);
}
.ra-art-preview :deep(code) {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  background: var(--t-bg-input, #f3f4f6);
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 12px;
}
.ra-art-preview :deep(pre) {
  background: var(--t-bg-input, #f3f4f6);
  padding: 10px 12px;
  border-radius: 4px;
  overflow-x: auto;
}
.ra-art-preview :deep(pre code) {
  background: transparent;
  padding: 0;
}
.ra-art-preview :deep(blockquote) {
  border-left: 3px solid #cbd5e1;
  margin: 8px 0;
  padding: 4px 12px;
  color: var(--t-text-secondary);
  background: var(--t-bg-subtle, #fafafa);
}
.ra-art-textarea:focus {
  border-color: #6366f1;
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.15);
}

.ra-artifact-footer {
  display: flex;
  gap: 8px;
  padding: 10px 16px;
  border-top: 1px solid var(--t-border-subtle);
  background: var(--t-bg, #fff);
  justify-content: flex-end;
}
.ra-btn-secondary,
.ra-btn-primary {
  height: 32px;
  padding: 0 14px;
  border-radius: 4px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
  border: 1px solid transparent;
}
.ra-btn-secondary {
  background: var(--t-bg-input, #f3f4f6);
  border-color: var(--t-border-subtle, #d1d5db);
  color: var(--t-text-primary);
}
.ra-btn-secondary:hover:not(:disabled) {
  background: var(--t-bg-hover, #e5e7eb);
}
.ra-btn-primary {
  background: linear-gradient(135deg, #6366f1, #4f46e5);
  border-color: #4338ca;
  color: #fff;
  font-weight: 500;
}
.ra-btn-primary:hover:not(:disabled) {
  background: linear-gradient(135deg, #4f46e5, #4338ca);
}
.ra-btn-secondary:disabled,
.ra-btn-primary:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.spinner {
  display: inline-block;
  animation: spin 1s linear infinite;
  font-size: 16px;
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
