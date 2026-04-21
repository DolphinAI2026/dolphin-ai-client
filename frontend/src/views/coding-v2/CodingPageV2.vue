<template>
  <div class="v2-page">
    <!-- ── TopBar ── -->
    <header class="topbar">
      <div class="topbar-left">
        <router-link to="/" class="back-btn">
          <span class="back-arrow">←</span>
          <span class="back-label">返回</span>
        </router-link>
        <div class="brand">智能开发 V2</div>
        <div v-if="store.conversationId" class="conv-id">#{{ store.conversationId }}</div>
      </div>

      <!-- 水平阶段步骤 -->
      <nav class="phase-steps">
        <div
          v-for="(p, i) in phaseList"
          :key="p.value"
          :class="['step', { active: p.value === store.phase, past: isPast(p.value) }]"
        >
          <div class="step-dot">
            <span v-if="isPast(p.value)">✓</span>
            <span v-else>{{ p.num }}</span>
          </div>
          <span class="step-label">{{ p.label }}</span>
          <div v-if="i < phaseList.length - 1" class="step-line" />
        </div>
      </nav>

      <div class="topbar-right">
        <span class="sse-dot" :class="store.sseConnected ? 'sse-ok' : 'sse-off'" />
        <span class="sse-label">{{ store.sseConnected ? 'SSE' : '未连接' }}</span>
      </div>
    </header>

    <!-- ── 全局错误条 ── -->
    <Transition name="fade">
      <div v-if="store.sseLastError" class="global-error">
        <span>⚠️ {{ store.sseLastError }}</span>
        <button @click="store.sseLastError = null">×</button>
      </div>
    </Transition>

    <!-- ── 聊天流 ── -->
    <ChatFlow
      class="chat-area"
      @confirm-spec="onConfirmSpec"
      @cancel-spec="onCancelSpec"
      @open-ide="openIde"
    />

    <!-- ── 输入栏 ── -->
    <InputBar
      :pending-ask-user="store.pendingAskUser"
      :submitting="submitting"
      :disabled="store.phase === 'aborted'"
      @send="onSend"
      @answer="onAnswer"
    />
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, watch } from 'vue'
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
import ChatFlow from '@/components/coding-v2/ChatFlow.vue'
import InputBar from '@/components/coding-v2/InputBar.vue'
import { useCodingV2Store } from '@/stores/codingV2'
import { SseClient } from '@/utils/sseClient'
import { ref } from 'vue'

const route = useRoute()
const router = useRouter()
const store = useCodingV2Store()

const submitting = ref(false)
let sse: SseClient | null = null

// phase 列表（TopBar 水平步骤用）
const phaseList: Array<{ value: Phase; label: string; num: number }> = [
  { value: 'understand', label: '理解', num: 1 },
  { value: 'confirm', label: '确认', num: 2 },
  { value: 'scaffold', label: '脚手架', num: 3 },
  { value: 'generate', label: '生成', num: 4 },
  { value: 'verify', label: '验收', num: 5 },
  { value: 'done', label: '完成', num: 6 },
]

function isPast(p: Phase): boolean {
  const order: Phase[] = ['idle', 'understand', 'confirm', 'scaffold', 'generate', 'verify', 'done']
  const cur = order.indexOf(store.phase)
  const tgt = order.indexOf(p)
  if (store.phase === 'done') return cur >= tgt
  return cur > tgt
}

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

// currentSpecId 变化时自动拉取 spec
watch(
  () => store.currentSpecId,
  (id) => {
    if (id && !store.currentSpec) loadCurrentSpec()
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
      } catch { /* 非致命 */ }
    }
  },
)

// route 参数变化（从 URL 切换对话）
watch(
  () => route.params.conversationId,
  async (newId) => {
    const n = parseInt(String(newId ?? ''), 10)
    if (Number.isFinite(n) && n > 0 && n !== store.conversationId) {
      await attachToConversation(n)
    }
  },
)

async function attachToConversation(convId: number) {
  store.attachConversation(convId)
  startSse(convId)
  if (store.currentSpecId && !store.currentSpec) await loadCurrentSpec()
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

// ── 用户发送消息 ──
// apiText: 发给后端的原始值（chip.value / 自由输入）
// displayText: 用户气泡展示的可读文字（chip.label；自由输入时与 apiText 相同）
async function onSend(apiText: string, displayText?: string) {
  if (!apiText || submitting.value) return
  submitting.value = true

  // 聊天流：如果是首条消息，插入"理解"阶段分割线
  const wasIdle = store.phase === 'idle' || !store.conversationId
  if (wasIdle) {
    store.addPhaseDivider('understand', '💬 理解需求')
  }
  store.addUserChatMessage(displayText ?? apiText)

  try {
    const resp: SendMessageResponse = await sendCodingMessage({
      conversation_id: store.conversationId,
      message: apiText,
    })
    if (!store.conversationId) {
      await router.replace({ name: 'CodingV2', params: { conversationId: String(resp.conversation_id) } })
      await attachToConversation(resp.conversation_id)
    }
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

// ── 选项回答（chips 点击） ──
async function onAnswer(payload: { bubbleId: string; answer: string; displayText: string; p1_key?: string | null }) {
  store.markAskUserAnswered(payload.bubbleId, payload.answer)
  // displayText（label）用于气泡，answer（value）发给后端
  await onSend(payload.answer, payload.displayText)
}

// ── Spec 确认 / 取消 ──
async function onConfirmSpec() {
  if (!store.currentSpecId) return
  submitting.value = true
  try {
    const resp = await apiConfirmSpec(store.currentSpecId)
    await startCodingFromSpec(store.currentSpecId)
    store.phase = resp.phase_hint === 'already_confirmed' ? 'generate'
      : resp.phase_hint === 'scaffold' ? 'scaffold' : 'generate'
  } catch (e: any) {
    store.sseLastError = `确认失败：${e?.response?.data?.detail ?? e?.message ?? e}`
  } finally {
    submitting.value = false
  }
}

function onCancelSpec() {
  store.phase = 'understand'
}

// ── IDE ──
async function openIde() {
  if (!store.workspaceId) return
  try {
    const { ide_url } = await getIdeUrl(store.workspaceId, store.conversationId)
    window.open(ide_url, '_blank')
  } catch (e: any) {
    store.sseLastError = `IDE 链接获取失败：${e?.response?.data?.detail ?? e?.message ?? e}`
  }
}
</script>

<style scoped>
/* ── 整体布局：全高 flex 列 ── */
.v2-page {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
  background: #f9fafb;
}

/* ── TopBar ── */
.topbar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 0 16px;
  height: 52px;
  background: white;
  border-bottom: 1px solid #e5e7eb;
  flex-shrink: 0;
  z-index: 10;
}
.topbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
.back-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  color: #6b7280;
  text-decoration: none;
  font-size: 13px;
  padding: 4px 8px;
  border-radius: 6px;
  transition: background 120ms, color 120ms;
}
.back-btn:hover { background: #f3f4f6; color: #111827; }
.back-arrow { font-size: 14px; }
.brand {
  font-size: 14px;
  font-weight: 600;
  color: #111827;
}
.conv-id {
  font-size: 12px;
  color: #9ca3af;
  background: #f3f4f6;
  padding: 2px 8px;
  border-radius: 999px;
}

/* ── 水平 phase steps ── */
.phase-steps {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0;
  overflow: hidden;
}
.step {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #9ca3af;
  font-size: 12px;
  flex-shrink: 0;
}
.step.past { color: #10b981; }
.step.active { color: #7c3aed; }
.step-dot {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  border: 1.5px solid currentColor;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  font-weight: 600;
  flex-shrink: 0;
}
.step.active .step-dot {
  background: #7c3aed;
  color: white;
  border-color: #7c3aed;
}
.step.past .step-dot {
  background: #10b981;
  color: white;
  border-color: #10b981;
}
.step-label { white-space: nowrap; }
.step-line {
  width: 28px;
  height: 1px;
  background: #e5e7eb;
  margin: 0 4px;
  flex-shrink: 0;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-shrink: 0;
}
.sse-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
.sse-ok { background: #10b981; }
.sse-off { background: #d1d5db; }
.sse-label { font-size: 11px; color: #9ca3af; }

/* ── 全局错误条 ── */
.global-error {
  padding: 8px 16px;
  background: #fee2e2;
  border-bottom: 1px solid #fca5a5;
  color: #991b1b;
  font-size: 13px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0;
}
.global-error button {
  background: transparent;
  border: none;
  color: #991b1b;
  font-size: 18px;
  cursor: pointer;
  line-height: 1;
}

/* ── 聊天区域（flex-grow，可滚动） ── */
.chat-area {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}

/* ── fade 动画 ── */
.fade-enter-active, .fade-leave-active { transition: opacity 200ms; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
