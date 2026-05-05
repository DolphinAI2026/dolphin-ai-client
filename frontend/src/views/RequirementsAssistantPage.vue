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

      <div v-else class="ra-layout">
        <div class="ra-chat-fullwidth">
          <DolphinAgentEmbed :agent-code="agentCode" title="AI 需求分析助手" />
        </div>

        <!-- 底部 action bar：状态 + 一键 → Builder -->
        <div class="ra-action-bar" :class="{ 'has-doc': hasDoc }">
          <div class="ra-bar-status">
            <template v-if="hasDoc">
              <span class="ra-bar-badge auto">● 自动同步</span>
              <span class="ra-bar-icon">📄</span>
              <span class="ra-bar-filename" :title="docFileName">{{ docFileName }}</span>
              <span v-if="docScore > 0" class="ra-bar-score" :class="docScoreClass">
                自检 {{ docScore }}/100
              </span>
            </template>
            <template v-else>
              <span class="ra-bar-empty">⏳ 等 agent 在上方写完设计文档，会自动同步到下方按钮</span>
            </template>
          </div>
          <button
            class="ra-bar-btn"
            :disabled="!hasDoc || sendingToBuilder"
            @click="sendToBuilder"
          >
            <span class="ra-btn-arrow">→</span>
            <span>{{ sendingToBuilder ? '处理中...' : 'Builder' }}</span>
          </button>
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
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import DolphinAgentEmbed from '@/components/DolphinAgentEmbed.vue'
import ChooseAppTargetDialog from '@/components/ChooseAppTargetDialog.vue'
import request from '@/utils/request'
import { applicationApi } from '@/api/application'
import { usePreviewStore } from '@/stores/preview'

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
const showEditor = ref(false)

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

/* ── 全宽 chat + 底部 action bar ── */
.ra-layout {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.ra-chat-fullwidth {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.ra-action-bar {
  flex-shrink: 0;
  height: 56px;
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 0 20px;
  border-top: 1px solid var(--t-border-subtle);
  background: var(--t-bg, #fff);
  box-shadow: 0 -2px 12px rgba(0, 0, 0, 0.04);
}
.ra-action-bar.has-doc {
  background: linear-gradient(to right, #f5f3ff 0%, #fff 40%, #fff 100%);
}

.ra-bar-status {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  color: var(--t-text-secondary);
  min-width: 0;
  overflow: hidden;
}
.ra-bar-badge {
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 12px;
  font-weight: 500;
  flex-shrink: 0;
}
.ra-bar-badge.auto { color: #047857; background: #d1fae5; }

.ra-bar-icon { font-size: 16px; flex-shrink: 0; }
.ra-bar-filename {
  font-weight: 600;
  color: var(--t-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 320px;
}
.ra-bar-score {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 500;
  flex-shrink: 0;
}
.ra-bar-score.high { color: #047857; background: #d1fae5; }
.ra-bar-score.mid  { color: #b45309; background: #fef3c7; }
.ra-bar-score.low  { color: #b91c1c; background: #fee2e2; }
.ra-bar-empty {
  color: var(--t-text-muted);
  font-size: 13px;
}

.ra-bar-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 38px;
  padding: 0 22px;
  font-size: 14.5px;
  font-weight: 600;
  color: #fff;
  background: linear-gradient(135deg, #6366f1, #4338ca);
  border: 0;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.18s;
  box-shadow: 0 2px 6px rgba(67, 56, 202, 0.25);
  flex-shrink: 0;
}
.ra-bar-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 10px rgba(67, 56, 202, 0.35);
}
.ra-bar-btn:disabled {
  background: #d1d5db;
  color: #6b7280;
  cursor: not-allowed;
  box-shadow: none;
}
.ra-btn-arrow { font-size: 16px; }

/* ── 简化版 ArtifactPanel：状态条 + 大卡片 + 大 → Builder 按钮 ── */
.ra-card-status {
  display: flex;
  align-items: center;
  justify-content: center;
}
.ra-card-main {
  background: var(--t-bg, #fff);
  border-radius: 12px;
  padding: 18px 16px;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  border: 1px solid var(--t-border-subtle);
  flex-shrink: 0;
}
.ra-card-main.is-empty {
  background: linear-gradient(135deg, #f0f4ff, #fafbff);
  border: 1px dashed #c7d2fe;
}
.ra-card-icon {
  font-size: 32px;
  margin-bottom: 8px;
}
.ra-card-filename {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--t-text-primary);
  word-break: break-all;
  max-width: 100%;
  margin-bottom: 4px;
  line-height: 1.4;
}
.ra-card-stats {
  font-size: 12px;
  color: var(--t-text-secondary);
  margin-bottom: 16px;
}
.ra-card-stat-num {
  font-weight: 600;
  color: var(--t-text-primary);
}
.ra-card-stat-sep {
  margin: 0 6px;
  color: #cbd5e1;
}
.ra-card-score {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11.5px;
}
.ra-card-score.high { color: #047857; background: #d1fae5; }
.ra-card-score.mid  { color: #b45309; background: #fef3c7; }
.ra-card-score.low  { color: #b91c1c; background: #fee2e2; }
.ra-card-score strong { font-size: 13px; }

.ra-btn-builder {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  height: 44px;
  padding: 0 16px;
  font-size: 15px;
  font-weight: 600;
  color: #fff;
  background: linear-gradient(135deg, #6366f1, #4338ca);
  border: 0;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.18s;
  box-shadow: 0 2px 6px rgba(67, 56, 202, 0.25);
}
.ra-btn-builder:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 10px rgba(67, 56, 202, 0.35);
}
.ra-btn-builder:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.ra-btn-arrow {
  font-size: 17px;
  font-weight: 400;
}
.ra-card-builder-hint {
  margin-top: 6px;
  font-size: 11.5px;
  color: var(--t-text-muted);
}

.ra-card-tools {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
  width: 100%;
  margin-top: 16px;
}
.ra-tool-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 6px 8px;
  font-size: 12px;
  border: 1px solid var(--t-border-subtle);
  background: var(--t-bg, #fff);
  color: var(--t-text-secondary);
  border-radius: 5px;
  cursor: pointer;
  transition: all 0.15s;
}
.ra-tool-btn:hover {
  background: var(--t-bg-input);
  color: var(--t-text-primary);
}
.ra-tool-btn span { font-size: 11px; }

.ra-tool-btn-paste {
  width: 100%;
  margin-top: 16px;
  padding: 8px;
  font-size: 12.5px;
}

.ra-empty-cap {
  font-size: 14px;
  font-weight: 600;
  color: var(--t-text-primary);
  margin-bottom: 8px;
}
.ra-empty-sub {
  font-size: 12px;
  color: var(--t-text-secondary);
  line-height: 1.6;
}

.ra-card-editor {
  width: 100%;
  margin-top: 12px;
  min-height: 160px;
  resize: vertical;
  border: 1px solid var(--t-border-subtle);
  border-radius: 6px;
  padding: 10px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11.5px;
  line-height: 1.55;
  color: var(--t-text-primary);
  background: var(--t-bg, #fff);
  outline: none;
}
.ra-card-editor:focus {
  border-color: #6366f1;
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.15);
}

/* 旧 dead 样式留着不影响 */
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
  font-size: 11.5px;
  padding: 4px 12px;
  border-radius: 12px;
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
