<template>
  <div class="coding-v2-layout">
    <!-- 左栏：对话简介 + 对话输入 -->
    <aside class="sidebar">
      <div class="sidebar-header">
        <router-link to="/" class="back-link">← 返回</router-link>
        <h2>智能开发 V2</h2>
      </div>

      <div class="phase-indicator">
        <div class="phase-track">
          <div
            v-for="p in phaseList"
            :key="p.value"
            :class="['phase-dot', {
              active: p.value === store.phase,
              past: isPast(p.value),
            }]"
            :title="p.label"
          >
            <span class="dot-icon">{{ isPast(p.value) ? '✓' : p.num }}</span>
            <span class="dot-label">{{ p.label }}</span>
          </div>
        </div>
      </div>

      <div class="conv-info" v-if="store.conversationId">
        <div><span class="k">对话 ID</span>#{{ store.conversationId }}</div>
        <div><span class="k">状态</span><code>{{ store.phase }}</code></div>
        <div v-if="store.currentSpecId">
          <span class="k">Spec</span><code>{{ store.currentSpecId.slice(0, 12) }}…</code>
          <span v-if="store.currentSpec"> v{{ store.currentSpec.provenance.version }}</span>
        </div>
        <div>
          <span class="k">SSE</span>
          <span :class="store.sseConnected ? 'ok' : 'off'">
            {{ store.sseConnected ? '● 已连接' : '○ 未连接' }}
          </span>
        </div>
      </div>

      <div class="composer">
        <textarea
          v-model="input"
          :disabled="submitting || !store.canSendMessage"
          placeholder="说说你要做什么..."
          rows="4"
          @keydown.ctrl.enter="onSubmit"
          @keydown.meta.enter="onSubmit"
        ></textarea>
        <div class="composer-row">
          <span class="hint">Ctrl/⌘+Enter 发送</span>
          <button class="send-btn" :disabled="submitting || !input.trim()" @click="onSubmit">
            {{ submitting ? '发送中...' : '发送' }}
          </button>
        </div>
      </div>
    </aside>

    <!-- 主内容区：按 phase 切面板 -->
    <main class="main">
      <div v-if="store.sseLastError" class="global-error">
        <span>⚠️ {{ store.sseLastError }}</span>
        <button @click="store.sseLastError = null">×</button>
      </div>

      <!-- Iteration banner（跨所有 phase） -->
      <IterationBanner
        v-if="store.lastIterationBanner"
        :banner="store.lastIterationBanner"
      />

      <!-- 反问气泡（UNDERSTAND 阶段常驻） -->
      <div v-if="store.askUserBubbles.length" class="bubbles">
        <AskUserCard
          v-for="b in store.askUserBubbles"
          :key="b.id"
          :bubble="b"
          :submitting="submitting"
          @answer="onAnswer"
        />
      </div>

      <!-- Phase-driven 主面板 -->
      <section class="phase-panel" :class="'panel-' + store.mainPanel">
        <div v-if="store.mainPanel === 'idle'" class="idle-panel">
          <div class="idle-icon">🚀</div>
          <h3>开始一个新需求</h3>
          <p>在左侧输入你的需求，我会通过结构化对话帮你理清楚，然后生成代码。</p>
        </div>

        <BrainstormProgress
          v-else-if="store.mainPanel === 'brainstorm-progress'"
          :tool-traces="brainstormTraces"
          :pending-bubble="store.pendingAskUser"
        />

        <SpecPreview
          v-else-if="store.mainPanel === 'spec-preview' && store.currentSpec"
          :envelope="store.currentSpec"
          allow-actions
          @confirm="onConfirmSpec"
          @cancel="onCancelSpec"
        />

        <div v-else-if="store.mainPanel === 'scaffold-progress'" class="scaffold-panel">
          <div class="scaffold-spinner">
            <div class="spinner"></div>
            <div>
              <div class="title">📦 正在创建工作区...</div>
              <div class="subtitle">拉取模板、安装依赖</div>
            </div>
          </div>
        </div>

        <CodingProgress
          v-else-if="store.mainPanel === 'coding-progress'"
          :tool-traces="codingTraces"
          :files="store.filesWritten"
          :streamed-text="store.streamedText"
        />

        <VerificationReportPanel
          v-else-if="store.mainPanel === 'verification-report' && store.lastVerificationReport"
          :report="store.lastVerificationReport"
        />

        <div v-else-if="store.mainPanel === 'done'" class="done-panel">
          <div class="done-icon">🎉</div>
          <h3>完成！</h3>
          <p v-if="store.lastVerificationReport">
            {{ store.lastVerificationReport.passed_count }} / {{ store.lastVerificationReport.items.length }} 条验收点通过
          </p>
          <p>你可以在下方对话继续迭代，或打开工作区查看代码。</p>

          <button
            v-if="store.workspaceId"
            class="open-ide-btn"
            :disabled="ideLoading"
            @click="openIde"
          >
            {{ ideLoading ? '加载中...' : '🖥️ 打开 IDE' }}
          </button>

          <!-- 显示最终 report -->
          <VerificationReportPanel
            v-if="store.lastVerificationReport"
            :report="store.lastVerificationReport"
          />

          <!-- 显示最终 spec -->
          <SpecPreview v-if="store.currentSpec" :envelope="store.currentSpec" />
        </div>

        <div v-else-if="store.mainPanel === 'failed'" class="failed-panel">
          <div class="failed-icon">💥</div>
          <h3>{{ store.phase === 'aborted' ? '已取消' : '执行失败' }}</h3>
          <p v-if="store.sseLastError">{{ store.sseLastError }}</p>
          <p>你可以在下方对话重试，或返回首页新建对话。</p>
        </div>
      </section>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  confirmSpec as apiConfirmSpec,
  getConversationWorkspace,
  getIdeUrl,
  getSpec as apiGetSpec,
  sendCodingMessage,
  startCodingFromSpec,
  type Phase,
  type SendMessageResponse,
} from '@/api/codingV2'
import AskUserCard from '@/components/coding-v2/AskUserCard.vue'
import BrainstormProgress from '@/components/coding-v2/BrainstormProgress.vue'
import CodingProgress from '@/components/coding-v2/CodingProgress.vue'
import IterationBanner from '@/components/coding-v2/IterationBanner.vue'
import SpecPreview from '@/components/coding-v2/SpecPreview.vue'
import VerificationReportPanel from '@/components/coding-v2/VerificationReportPanel.vue'
import { useCodingV2Store } from '@/stores/codingV2'
import { SseClient, type SseEvent } from '@/utils/sseClient'

const route = useRoute()
const router = useRouter()
const store = useCodingV2Store()

const input = ref('')
const submitting = ref(false)
const ideLoading = ref(false)

let sse: SseClient | null = null

// phase 列表（UI 展示用；不含终态）
const phaseList: Array<{ value: Phase; label: string; num: number }> = [
  { value: 'understand', label: '理解', num: 1 },
  { value: 'confirm', label: '确认', num: 2 },
  { value: 'scaffold', label: '搭脚手架', num: 3 },
  { value: 'generate', label: '生成', num: 4 },
  { value: 'verify', label: '验收', num: 5 },
  { value: 'done', label: '完成', num: 6 },
]

function isPast(p: Phase): boolean {
  const order: Phase[] = [
    'idle', 'understand', 'confirm', 'scaffold', 'generate', 'verify', 'done',
  ]
  const currentIdx = order.indexOf(store.phase)
  const targetIdx = order.indexOf(p)
  return currentIdx > targetIdx
}

// ── 按 agent 过滤 trace ──
const brainstormTraces = computed(() =>
  store.toolTraces.filter((t) => t.agent === 'brainstorm'),
)
const codingTraces = computed(() =>
  store.toolTraces.filter((t) => t.agent === 'coding'),
)

// ── 生命周期 ──
onMounted(async () => {
  const convId = parseInt(String(route.params.conversationId ?? ''), 10)
  if (Number.isFinite(convId) && convId > 0) {
    await attachToConversation(convId)
  }
})

onBeforeUnmount(() => {
  sse?.stop()
})

// currentSpecId 变化时自动拉取 spec 数据（SSE onEvent 是 fire-and-forget，
// 加 watch 作为保底：只要 specId 有值且 spec 还没加载就触发一次拉取）
watch(
  () => store.currentSpecId,
  (id) => {
    if (id && !store.currentSpec) {
      loadCurrentSpec()
    }
  },
)

// phase 变为 done 时，若 workspaceId 还没拿到，主动拉一次
watch(
  () => store.phase,
  async (p) => {
    if (p === 'done' && !store.workspaceId && store.conversationId) {
      try {
        const res = await getConversationWorkspace(store.conversationId)
        if (res.workspace_id) store.workspaceId = res.workspace_id
      } catch { /* 非致命，按钮只是不显示 */ }
    }
  },
)

async function attachToConversation(convId: number) {
  store.attachConversation(convId)
  startSse(convId)
  // 若已有 spec，拉全量
  if (store.currentSpecId && !store.currentSpec) {
    await loadCurrentSpec()
  }
  // 若已是 done 且没有 workspaceId，主动拉
  if (store.phase === 'done' && !store.workspaceId) {
    try {
      const res = await getConversationWorkspace(convId)
      if (res.workspace_id) store.workspaceId = res.workspace_id
    } catch { /* ignore */ }
  }
}

function startSse(convId: number) {
  sse?.stop()
  sse = new SseClient({
    conversationId: convId,
    onEvent: async (ev) => {
      store.ingestEvent(ev)
      // 有新 spec_id 时拉全量 envelope
      if (
        (ev.type === 'brainstorm.spec_emitted' || ev.type === 'iteration.trivial_patched')
        && ev.data?.spec_id
      ) {
        store.currentSpecId = ev.data.spec_id ?? ev.data.new_spec_id
        await loadCurrentSpec()
      }
    },
    onOpen: () => { store.sseConnected = true },
    onClose: (reason) => {
      store.sseConnected = false
      if (reason === 'max_reconnect_exceeded') {
        store.sseLastError = 'SSE 多次重连失败，请刷新页面重试'
      }
    },
    onSeqJump: (expected, got) => {
      console.warn(`[SSE] seq jumped: expected ${expected}, got ${got}`)
    },
  })
  sse.start()
}

async function loadCurrentSpec() {
  if (!store.currentSpecId) return
  try {
    const detail = await apiGetSpec(store.currentSpecId)
    store.setSpec(detail.envelope)
  } catch (e) {
    console.warn('loadCurrentSpec failed', e)
  }
}

// ── 用户操作 ──
async function onSubmit() {
  const text = input.value.trim()
  if (!text || submitting.value) return
  submitting.value = true
  try {
    const resp: SendMessageResponse = await sendCodingMessage({
      conversation_id: store.conversationId,
      message: text,
    })
    // 首次发消息会创建 conversation，URL 对应更新
    if (!store.conversationId) {
      await router.replace({ name: 'CodingV2', params: { conversationId: String(resp.conversation_id) } })
      await attachToConversation(resp.conversation_id)
    }
    input.value = ''
    // phase 由 SSE 反馈更新；这里乐观更新一下
    store.phase = resp.phase
    if (resp.session_id) {
      if (resp.action.includes('brainstorm')) {
        store.activeBrainstormSessionId = resp.session_id
      }
    }
  } catch (e: any) {
    store.sseLastError = `发送失败：${e?.response?.data?.detail ?? e?.message ?? e}`
  } finally {
    submitting.value = false
  }
}

async function onAnswer(payload: { bubbleId: string; answer: string; p1_key?: string | null }) {
  // 答案就是一条新消息（后端把 understand phase 里文本当用户追答）
  store.markAskUserAnswered(payload.bubbleId, payload.answer)
  input.value = payload.answer
  await onSubmit()
}

async function onConfirmSpec() {
  if (!store.currentSpecId) return
  submitting.value = true
  try {
    const resp = await apiConfirmSpec(store.currentSpecId)
    // 再调 start-coding（两步分离：confirm 只改 phase；start-coding 真正启动 coding task）
    await startCodingFromSpec(store.currentSpecId)
    store.phase = resp.phase_hint === 'already_confirmed' ? 'generate' :
      resp.phase_hint === 'scaffold' ? 'scaffold' : 'generate'
  } catch (e: any) {
    store.sseLastError = `确认失败：${e?.response?.data?.detail ?? e?.message ?? e}`
  } finally {
    submitting.value = false
  }
}

function onCancelSpec() {
  // MVP：取消就是回到 UNDERSTAND 让用户继续说
  input.value = ''
  store.phase = 'understand'
}

async function openIde() {
  if (!store.workspaceId || ideLoading.value) return
  ideLoading.value = true
  try {
    const { ide_url } = await getIdeUrl(store.workspaceId, store.conversationId)
    window.open(ide_url, '_blank')
  } catch (e: any) {
    store.sseLastError = `IDE 链接获取失败：${e?.response?.data?.detail ?? e?.message ?? e}`
  } finally {
    ideLoading.value = false
  }
}

watch(
  () => route.params.conversationId,
  async (newId) => {
    const n = parseInt(String(newId ?? ''), 10)
    if (Number.isFinite(n) && n > 0 && n !== store.conversationId) {
      await attachToConversation(n)
    }
  },
)
</script>

<style scoped>
.coding-v2-layout {
  display: grid;
  grid-template-columns: 340px 1fr;
  height: 100vh;
  overflow: hidden;
  background: #f9fafb;
}
.sidebar {
  background: white;
  border-right: 1px solid #e5e7eb;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.sidebar-header {
  padding: 14px 18px;
  border-bottom: 1px solid #e5e7eb;
}
.back-link { color: #6b7280; text-decoration: none; font-size: 12px; }
.back-link:hover { color: #3b82f6; }
.sidebar-header h2 {
  margin: 4px 0 0;
  font-size: 16px;
  color: #111827;
}

.phase-indicator { padding: 14px 18px; border-bottom: 1px solid #e5e7eb; }
.phase-track {
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 12px;
}
.phase-dot {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #9ca3af;
}
.phase-dot.past { color: #065f46; }
.phase-dot.active { color: #1d4ed8; font-weight: 500; }
.dot-icon {
  width: 20px; height: 20px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  border: 1px solid currentColor;
}
.phase-dot.active .dot-icon { background: #3b82f6; color: white; border-color: #3b82f6; }
.phase-dot.past .dot-icon { background: #10b981; color: white; border-color: #10b981; }

.conv-info {
  padding: 14px 18px;
  border-bottom: 1px solid #e5e7eb;
  font-size: 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  color: #374151;
}
.conv-info .k { color: #6b7280; margin-right: 6px; }
.ok { color: #065f46; }
.off { color: #b91c1c; }

.composer {
  padding: 14px 18px;
  margin-top: auto;
  border-top: 1px solid #e5e7eb;
}
.composer textarea {
  width: 100%;
  resize: vertical;
  padding: 8px 10px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  font-size: 13px;
  font-family: inherit;
  box-sizing: border-box;
}
.composer textarea:focus { outline: none; border-color: #3b82f6; }
.composer textarea:disabled { background: #f9fafb; color: #9ca3af; }
.composer-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 8px;
}
.hint { font-size: 11px; color: #9ca3af; }
.send-btn {
  padding: 6px 16px;
  border-radius: 6px;
  background: #3b82f6;
  color: white;
  border: none;
  cursor: pointer;
  font-size: 13px;
}
.send-btn:hover:not(:disabled) { background: #2563eb; }
.send-btn:disabled { background: #d1d5db; cursor: not-allowed; }

.main {
  overflow-y: auto;
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.global-error {
  padding: 10px 14px;
  background: #fee2e2;
  border: 1px solid #fca5a5;
  border-radius: 6px;
  color: #991b1b;
  font-size: 13px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.global-error button {
  background: transparent;
  border: none;
  color: #991b1b;
  font-size: 18px;
  cursor: pointer;
}

.bubbles { display: flex; flex-direction: column; gap: 10px; }

.phase-panel { min-height: 200px; }
.idle-panel, .scaffold-panel, .done-panel, .failed-panel {
  background: white;
  border-radius: 12px;
  padding: 32px 28px;
  text-align: center;
  border: 1px solid #e5e7eb;
  display: flex;
  flex-direction: column;
  gap: 12px;
  align-items: center;
}
.idle-icon, .done-icon, .failed-icon { font-size: 40px; }
.done-icon { color: #10b981; }
.failed-icon { color: #ef4444; }
.done-panel { align-items: stretch; text-align: left; }
.done-panel h3, .done-panel p { text-align: center; margin: 0; }
.open-ide-btn {
  align-self: center;
  padding: 8px 22px;
  border-radius: 8px;
  background: #10b981;
  color: white;
  border: none;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
}
.open-ide-btn:hover:not(:disabled) { background: #059669; }
.open-ide-btn:disabled { background: #d1d5db; cursor: not-allowed; }

.scaffold-panel { flex-direction: row; justify-content: flex-start; text-align: left; }
.scaffold-spinner { display: flex; gap: 14px; align-items: center; }
.scaffold-spinner .spinner {
  width: 28px; height: 28px;
  border: 3px solid #e5e7eb;
  border-top-color: #f59e0b;
  border-radius: 50%;
  animation: spin 900ms linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.scaffold-spinner .title { font-weight: 500; }
.scaffold-spinner .subtitle { font-size: 12px; color: #6b7280; margin-top: 4px; }
</style>
