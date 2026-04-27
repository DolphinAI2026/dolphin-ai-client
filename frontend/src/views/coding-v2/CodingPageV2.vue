<template>
  <div class="v2-page">
    <!-- ── TopBar ── -->
    <header class="topbar">
      <div class="topbar-left">
        <router-link to="/" class="back-btn">
          <el-icon :size="14"><ArrowLeft /></el-icon>
          <span class="back-label">返回</span>
        </router-link>
        <div class="brand">智能开发 V2</div>
        <div v-if="store.conversationId" class="conv-id">#{{ store.conversationId }}</div>
      </div>

      <!-- Chat / IDE 切换（始终显示；IDE 在 workspace 未创建时禁用） -->
      <div class="view-toggle">
        <button
          class="view-toggle-btn"
          :class="{ active: activeView === 'chat' }"
          @click="activeView = 'chat'"
        >
          <el-icon :size="13"><ChatDotRound /></el-icon>
          <span class="view-toggle-label">对话</span>
        </button>
        <button
          class="view-toggle-btn"
          :class="{ active: activeView === 'ide', disabled: !store.workspaceId }"
          :disabled="!store.workspaceId"
          :title="!store.workspaceId ? '工作区尚未创建，完成首次代码生成后可用' : ''"
          @click="store.workspaceId && onSwitchToIde()"
        >
          <el-icon :size="13"><Monitor /></el-icon>
          <span class="view-toggle-label">IDE</span>
        </button>
      </div>

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
      v-show="activeView === 'chat'"
      class="chat-area"
      :confirm-submitting="confirmingSpec"
      :retrying="retrying"
      @confirm-spec="onConfirmSpec"
      @open-ide="onSwitchToIde"
      @retry-coding="onRetryCoding"
    />

    <!-- ── IDE 内嵌 iframe ── -->
    <div v-if="activeView === 'ide'" class="ide-pane">
      <iframe
        v-if="ideUrl"
        :key="ideUrl"
        :src="ideUrl"
        class="ide-frame"
        frameborder="0"
        @load="ideLoaded = true"
      />
      <div v-if="!ideUrl || !ideLoaded" class="ide-loading-overlay">
        <template v-if="ideLoadError">
          <div class="ide-err-icon">⚠️</div>
          <span>{{ ideLoadError }}</span>
          <button class="ide-retry-btn" @click="onSwitchToIde">重新加载</button>
        </template>
        <template v-else>
          <div class="ide-loading-spinner"></div>
          <span>正在加载 IDE...</span>
        </template>
      </div>
    </div>

    <!-- ── 输入栏（仅 chat 视图） ──
         禁用规则：
         1. phase = aborted —— 整个对话死了
         2. specRefineInFlight=true 且没有待答问题 —— 后端正在 iterate 中，
            再发一条会触发并发 task 造成 Spec 状态混乱；
            如果有 pendingAskUser，输入是用来答题的，必须可用。
    -->
    <InputBar
      v-show="activeView === 'chat'"
      :pending-ask-user="store.pendingAskUser"
      :submitting="sendingMessage"
      :disabled="store.phase === 'aborted' || (store.specRefineInFlight && !store.pendingAskUser)"
      :disabled-reason="inputDisabledReason"
      @send="onSend"
      @answer="onAnswer"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, ChatDotRound, Monitor } from '@element-plus/icons-vue'
import {
  confirmSpec as apiConfirmSpec,
  getConversationWorkspace,
  getIdeUrl,
  getSpec as apiGetSpec,
  sendCodingMessage,
  startCodingFromSpec,
  type SendMessageResponse,
} from '@/api/codingV2'
import { llmConfigApi } from '@/api/llmConfig'
import ChatFlow from '@/components/coding-v2/ChatFlow.vue'
import InputBar from '@/components/coding-v2/InputBar.vue'
import { useCodingV2Store } from '@/stores/codingV2'
import { SseClient } from '@/utils/sseClient'

const route = useRoute()
const router = useRouter()
const store = useCodingV2Store()

// 两个独立 loading 状态：
// - sendingMessage: 用户发送聊天消息（文本 / chip 回答 / 纠正 Spec 等）
// - confirmingSpec: 用户点"✅ 确认生成代码"按钮
// 以前这两个共用一个 `submitting` ref，导致纠正 Spec 假设（onSend）时，
// 页面上的 SpecPreview 确认按钮也会变 loading + 文案改成"正在启动生成…"，
// 误导用户以为代码已经开始生成。分开后：发消息只让 InputBar 禁用，
// 确认按钮 loading 仅由真正点击确认触发。
const sendingMessage = ref(false)
const confirmingSpec = ref(false)
const retrying = ref(false)
let sse: SseClient | null = null

// 输入框禁用时的提示文案（传给 InputBar 当 placeholder）
const inputDisabledReason = computed(() => {
  if (store.phase === 'aborted') return '对话已中断'
  if (store.specRefineInFlight && !store.pendingAskUser) {
    return 'AI 正在处理你的上一条消息，请稍候…'
  }
  return null
})

// ── Chat / IDE 视图切换 ──
const activeView = ref<'chat' | 'ide'>('chat')
const ideUrl = ref<string | null>(null)
const ideLoaded = ref(false)
const ideLoadError = ref<string | null>(null)

// ── 生命周期 ──
onMounted(async () => {
  // 拉 LLM 可选列表（三个 agent 共用）
  if (store.modelOptions.length === 0) {
    try {
      const opts = await llmConfigApi.listOptions('coding')
      store.modelOptions = opts.map(o => ({
        id: o.id,
        config_name: o.config_name,
        provider: o.provider,
        model: o.model,
        is_default: o.is_default,
      }))
      // 默认选中 is_default 那条
      const def = opts.find(o => o.is_default)
      if (def && store.selectedModelId == null) {
        store.selectedModelId = def.id
      }
    } catch (e) {
      console.warn('拉取 llm-configs/options 失败（非致命）', e)
    }
  }
  const convId = parseInt(String(route.params.conversationId ?? ''), 10)
  if (Number.isFinite(convId) && convId > 0) {
    await attachToConversation(convId)
  }
})

onBeforeUnmount(() => {
  sse?.stop()
})

// 任何"还没拉到 envelope"的 Spec 卡 → 自动 fetch（包括版本切换 / 新版到货 / 页面刷新回放）
watch(
  () => store.specVersions.map(c => `${c.spec_id}:${c.envelope ? 1 : 0}`).join(','),
  () => {
    for (const card of store.specVersions) {
      if (!card.envelope) loadSpecEnvelope(card.spec_id)
    }
  },
  { immediate: true },
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
  // 任何有卡但 envelope 为 null 的版本，开始拉
  for (const card of store.specVersions) {
    if (!card.envelope) loadSpecEnvelope(card.spec_id)
  }
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
      // pushSpecVersion 会推一张 envelope=null 的新卡，下面的 watch 会自动触发拉取
      // 这里不再手动拉了，避免双拉。
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
  // 刷新 / 切会话后前端 chatMessages 是空的，但 localStorage 里 lastSeenSeq 可能还停在
  // 上次的最后一个事件；此时必须从 0 回放整个历史，否则聊天流一片空白。
  // 只有当前端已经有历史（例如 live 会话断线自动重连）才保留 seq，做增量续传。
  if (store.chatMessages.length === 0) {
    sse.resetSeq()
  }
  sse.start()
}

// 防止同一 spec_id 被并发拉两次（watch + attachToConversation 都会触发）
const _envelopeFetching = new Set<string>()
async function loadSpecEnvelope(specId: string) {
  if (_envelopeFetching.has(specId)) return
  _envelopeFetching.add(specId)
  try {
    const detail = await apiGetSpec(specId)
    store.setSpec(detail.envelope)
  } catch (e) {
    console.warn('loadSpecEnvelope failed for', specId, e)
  } finally {
    _envelopeFetching.delete(specId)
  }
}

// ── 用户发送消息 ──
// apiText: 发给后端的原始值（chip.value / 自由输入）
// displayText: 用户气泡展示的可读文字（chip.label；自由输入时与 apiText 相同）
async function onSend(apiText: string, displayText?: string) {
  if (!apiText || sendingMessage.value) return
  // 防御：InputBar 已经按 disabled 拦截了；这里再兜一层防绕过（直接 emit / 测试场景）
  if (store.specRefineInFlight && !store.pendingAskUser) {
    console.warn('onSend: refine 进行中且无待答问题，拒绝发送')
    return
  }
  sendingMessage.value = true

  // 聊天流：如果是首条消息，插入"理解"阶段分割线
  const wasIdle = store.phase === 'idle' || !store.conversationId
  if (wasIdle) {
    store.addPhaseDivider('understand', '💬 理解需求')
  }
  // displayText 是用户看到的 label（选项场景），apiText 是发给后端的 value
  store.addUserChatMessage(displayText ?? apiText, apiText)

  // CONFIRM 阶段点发送 = refine 意图，必然触发后端 iterate 分发改旧 Spec。
  // **发送前就锁住**旧 Spec 的确认按钮，否则在 HTTP POST 往返期间按钮仍可点，
  // 并发确认会和 iterate 任务冲突。flag 在 SSE 收到 brainstorm.spec_emitted /
  // iteration.trivial_patched / cross_scene_warning / iteration.failed 时清零；
  // 本地错误回退（catch 分支）也清零，避免永锁。
  const wasConfirmRefine = store.phase === 'confirm'
  if (wasConfirmRefine) {
    store.specRefineInFlight = true
  }

  try {
    const resp: SendMessageResponse = await sendCodingMessage({
      conversation_id: store.conversationId,
      message: apiText,
      selected_model: store.selectedModelId ?? undefined,
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
    // 如果响应不是 refine/iterate（理论上 CONFIRM 阶段只会是这两种之一），
    // 把 flag 放回去，避免锁住无关路径。
    if (
      wasConfirmRefine &&
      resp.action !== 'refine_brainstorm' &&
      resp.action !== 'iterate'
    ) {
      store.specRefineInFlight = false
    }
  } catch (e: any) {
    store.sseLastError = `发送失败：${e?.response?.data?.detail ?? e?.message ?? e}`
    // 请求失败：解锁，让用户可以继续操作
    if (wasConfirmRefine) store.specRefineInFlight = false
  } finally {
    sendingMessage.value = false
  }
}

// ── 选项回答（chips 点击） ──
async function onAnswer(payload: { bubbleId: string; answer: string; displayText: string; p1_key?: string | null }) {
  store.markAskUserAnswered(payload.bubbleId, payload.answer)
  // displayText（label）用于气泡，answer（value）发给后端
  await onSend(payload.answer, payload.displayText)
}

// ── Spec 确认 ──
// 接受 specId 参数：从 ChatFlow / SpecPreview 透传过来。理论上只有最新卡的按钮可点
// （SpecPreview 内部按 cardData.isLatest && !isConfirmed 控），但保险起见这里再校验。
async function onConfirmSpec(specId?: string) {
  const targetId = specId || store.currentSpecId
  if (!targetId) return
  // 校验：targetId 必须 = 当前最新版（防止 stale 事件 / UI 异常）
  if (targetId !== store.currentSpecId) {
    console.warn('confirmSpec: spec_id 不是当前最新版，忽略', targetId, '!==', store.currentSpecId)
    return
  }
  confirmingSpec.value = true
  try {
    const resp = await apiConfirmSpec(targetId)
    await startCodingFromSpec(targetId)
    store.phase = resp.phase_hint === 'already_confirmed' ? 'generate'
      : resp.phase_hint === 'scaffold' ? 'scaffold' : 'generate'
  } catch (e: any) {
    store.sseLastError = `确认失败：${e?.response?.data?.detail ?? e?.message ?? e}`
  } finally {
    confirmingSpec.value = false
  }
}

// ── 重新触发 coding（进程重启导致的悬挂任务兜底） ──
async function onRetryCoding() {
  if (!store.currentSpecId || retrying.value) return
  retrying.value = true
  // 先把失败卡 + 僵尸 verify-active 拿掉，否则重试了旧卡还在
  store.prepareRetry()
  store.phase = 'generate'
  try {
    await startCodingFromSpec(store.currentSpecId)
  } catch (e: any) {
    store.sseLastError = `重新触发失败：${e?.response?.data?.detail ?? e?.message ?? e}`
  } finally {
    retrying.value = false
  }
}

// ── IDE 切换 ──
async function onSwitchToIde() {
  if (!store.workspaceId) return
  activeView.value = 'ide'
  ideLoaded.value = false
  ideLoadError.value = null
  // 已有 URL 直接复用（避免每次切换都重新拉），否则现拉
  if (!ideUrl.value) {
    try {
      const { ide_url } = await getIdeUrl(store.workspaceId, store.conversationId)
      ideUrl.value = ide_url
    } catch (e: any) {
      ideLoadError.value = `IDE 链接获取失败：${e?.response?.data?.detail ?? e?.message ?? e}`
    }
  }
}

// workspaceId 变化时重置 ideUrl，强制下次重新拉
watch(() => store.workspaceId, () => { ideUrl.value = null; ideLoaded.value = false })
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

/* ── Chat / IDE 切换按钮 ── */
.view-toggle {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 2px;
  background: #f3f4f6;
  border-radius: 8px;
  padding: 3px;
  width: fit-content;
  margin: 0 auto;
}
.view-toggle-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 14px;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: #6b7280;
  font-size: 13px;
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
}
.view-toggle-btn:hover:not(.active):not(:disabled) {
  color: #111827;
  background: #e5e7eb;
}
.view-toggle-btn.active {
  background: white;
  color: #111827;
  font-weight: 500;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06);
}
.view-toggle-btn:disabled,
.view-toggle-btn.disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.view-toggle-label { white-space: nowrap; }

/* ── IDE pane ── */
.ide-pane {
  flex: 1;
  position: relative;
  min-height: 0;
  background: #f9fafb;
}
.ide-frame {
  width: 100%;
  height: 100%;
  border: none;
  background: white;
}
.ide-loading-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  color: #6b7280;
  font-size: 13px;
  background: #f9fafb;
}
.ide-loading-spinner {
  width: 28px;
  height: 28px;
  border: 2.5px solid #e5e7eb;
  border-top-color: #7c3aed;
  border-radius: 50%;
  animation: ide-spin 800ms linear infinite;
}
.ide-err-icon { font-size: 28px; }
.ide-retry-btn {
  margin-top: 4px;
  padding: 6px 16px;
  border-radius: 6px;
  background: #7c3aed;
  color: white;
  border: none;
  cursor: pointer;
  font-size: 13px;
}
.ide-retry-btn:hover { background: #6d28d9; }
@keyframes ide-spin { to { transform: rotate(360deg); } }

/* ── fade 动画 ── */
.fade-enter-active, .fade-leave-active { transition: opacity 200ms; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
