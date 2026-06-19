<!-- frontend/src/views/workspace/ChatPane.vue
     统一工作区 Phase 1 — 中央对话面板

     镜像 AppAssistantPanel.vue 的结构，差异：
     1. 通用对话：appId: ref(null)（不锁应用）
     2. 产物事件抛给外壳：@open-artifact="(a) => emit('open-artifact', a)"（不在本组件开抽屉）
     3. props { sessionId }：watch sessionId → loadSession(id)（切会话不重挂）
     4. props { workspaceId }：构造 viewContext 注入代码工作区上下文
     5. emit 'open-artifact' / 'session-changed'
     6. 历史/新建/产物按钮已删（外壳 SessionSidebar / ToolMenu 接管） -->
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import AgentConversation from '@/components/common/AgentConversation.vue'
import AgentRunTraceDrawer from '@/components/common/AgentRunTraceDrawer.vue'
import UnifiedChatComposer from '@/components/common/UnifiedChatComposer.vue'
import BuilderModelPicker from '@/components/common/BuilderModelPicker.vue'
import { useAiChatSession } from '@/composables/useAiChatSession'
import { aiChatApi } from '@/api/aiChat'
import { listSkills } from '@/api/skills'
import { llmConfigApi, type BuilderModelOption } from '@/api/llmConfig'
import type { AgentMessage } from '@/components/common/agent-conversation/types'
import type { UnifiedChatAttachment } from '@/components/common/chatComposer'
import { isImageFile } from '@/utils/pasteImages'

const props = defineProps<{
  /** 外壳传入的会话 id（null = 新建对话） */
  sessionId: number | null
  /** 外壳传入的工作区 id（workspace 态注入代码工作区上下文） */
  workspaceId?: string | null
}>()

const emit = defineEmits<{
  /** 用户点开产物卡片 → 通知外壳（PanelHost 的 ArtifactPanel 承载） */
  (e: 'open-artifact', artifact: any): void
  /** 会话 id 变化 → 通知外壳（切会话 / 新建） */
  (e: 'session-changed', id: number | null): void
}>()

// ─── unified 会话引擎（通用对话：appId = null，不锁应用） ───
const appId = ref<number | null>(null)
const selectedLlmId = ref<number | null>(null)
const llmOptions = ref<BuilderModelOption[]>([])

// 工作区上下文：有 workspaceId 时注入代码开发提示
const viewContext = computed<string | null>(() =>
  props.workspaceId
    ? '当前在代码工作区 ' + props.workspaceId + ' 做二次开发。需要读/改/运行代码时,workspace 工具一律用此 ws_id。'
    : null,
)

const {
  currentSession,
  agentMessages,
  typing,
  typingSeconds,
  sending,
  currentRunId,
  loadSessions,
  loadSession,
  newSession,
  send,
  stop,
} = useAiChatSession({
  appId,
  selectedLlmId,
  viewContext,
})

// ─── watch sessionId prop → composable loadSession ───
watch(
  () => props.sessionId,
  async (id) => {
    if (id == null) {
      newSession()
      return
    }
    if (currentSession.value?.id === id) return
    try {
      await loadSession(id)
      syncSelectedLlmFromSession()
    } catch (e: any) {
      ElMessage.error(e?.message || '加载会话失败')
    }
  },
)

// ─── 通知外壳会话变化 ───
watch(
  () => currentSession.value?.id ?? null,
  (id) => emit('session-changed', id),
)

// ─── 输入框 ───
const inputText = ref('')
const pendingFiles = ref<File[]>([])

const composerAttachments = computed<UnifiedChatAttachment[]>(() =>
  pendingFiles.value.map((file, index) => ({
    id: index,
    name: file.name,
    kind: isImageFile(file) ? 'image' : 'file',
  })),
)

function onComposerFilesPicked(files: File[]) {
  if (files.length) pendingFiles.value = [...pendingFiles.value, ...files]
}

function removePendingFileByIndex(_: UnifiedChatAttachment, index: number) {
  pendingFiles.value = pendingFiles.value.filter((_, i) => i !== index)
}

// ─── 可用技能（@ 引用） ───
const availableSkills = ref<{ name: string; description: string }[]>([])
onMounted(() => {
  listSkills().then((s) => { availableSkills.value = s }).catch(() => {})
})

function onSkillPicked(name: string) {
  const prefix = `请使用技能 ${name}：`
  inputText.value = inputText.value ? `${prefix}${inputText.value}` : prefix
}

async function doSend() {
  const text = inputText.value.trim()
  if ((!text && pendingFiles.value.length === 0) || sending.value) return
  const files = pendingFiles.value.slice()
  inputText.value = ''
  pendingFiles.value = []
  try {
    await send(text, files.length ? files : undefined)
  } catch (e: any) {
    ElMessage.error(e?.message || '发送失败')
  }
}

async function onStop() {
  try {
    await stop()
  } catch {
    /* ignore */
  }
}

// ─── 模型选择 ───
function syncSelectedLlmFromSession() {
  const sessionLlm = currentSession.value?.selected_llm_config_id ?? null
  const ids = new Set(llmOptions.value.map(o => o.id))
  selectedLlmId.value = sessionLlm != null && ids.has(sessionLlm)
    ? sessionLlm
    : (llmOptions.value.find(o => o.is_default)?.id ?? null)
}

async function loadLlmOptions() {
  try {
    const opts = await llmConfigApi.listOptions('builder')
    llmOptions.value = (opts || []) as BuilderModelOption[]
    syncSelectedLlmFromSession()
  } catch {
    llmOptions.value = []
    selectedLlmId.value = null
  }
}

async function onChangeLlm() {
  if (!currentSession.value) return
  try {
    const updated = await aiChatApi.updateSession(currentSession.value.id, {
      selected_llm_config_id: selectedLlmId.value ?? 0,
    })
    currentSession.value.selected_llm_config_id = updated.selected_llm_config_id
  } catch (e: any) {
    ElMessage.error(e?.message || '切换模型失败')
  }
}

// ─── Trace 抽屉 ───
const traceDrawerVisible = ref(false)
const tracePreferRunId = ref<string | null>(null)

function onOpenTrace(message: AgentMessage) {
  const rid = (message?.meta as any)?.run_id
  if (!rid) return
  tracePreferRunId.value = rid
  traceDrawerVisible.value = true
}

function openSessionTrace() {
  tracePreferRunId.value = currentRunId.value
  traceDrawerVisible.value = true
}

// ─── 初始化 ───
onMounted(() => {
  void loadLlmOptions()
  void loadSessions().catch(() => {})
  // 若初始 sessionId 已指定，加载它
  if (props.sessionId != null) {
    void loadSession(props.sessionId).then(() => syncSelectedLlmFromSession()).catch(() => {})
  }
})
</script>

<template>
  <div class="chat-pane">
    <!-- 顶部 header -->
    <header class="cp-header">
      <div class="cp-header-info">
        <div class="cp-header-title">AI 对话</div>
      </div>
      <div class="cp-top-actions">
        <!-- Trace 入口（外壳无等价，保留） -->
        <button
          v-if="currentSession"
          class="cp-top-btn"
          title="查看 Agent 活动"
          @click="openSessionTrace"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
          </svg>
        </button>
      </div>
    </header>

    <!-- 对话区 — 产物事件抛给外壳，不在本组件开抽屉 -->
    <AgentConversation
      class="cp-conversation"
      :messages="agentMessages"
      :typing="typing"
      :typing-seconds="typingSeconds"
      :tool-grouping="true"
      empty-title="AI 对话"
      empty-hint="输入你的问题或需求"
      @open-trace="onOpenTrace"
      @open-artifact="(a) => emit('open-artifact', a)"
      @answer-ask="(opt) => send(opt)"
    />

    <!-- 输入区 -->
    <div class="cp-input-area">
      <UnifiedChatComposer
        v-model="inputText"
        :attachments="composerAttachments"
        :sending="sending"
        :send-disabled="!inputText.trim() && pendingFiles.length === 0"
        :multiple="true"
        placeholder="输入消息..."
        hint=""
        sending-hint=""
        :skills="availableSkills"
        @send="doSend"
        @stop="onStop"
        @files-picked="onComposerFilesPicked"
        @skill-picked="onSkillPicked"
        @remove-attachment="removePendingFileByIndex"
      >
        <template #footer-left>
          <BuilderModelPicker
            v-model="selectedLlmId"
            :options="llmOptions"
            title="切换模型"
            @change="onChangeLlm"
          />
        </template>
      </UnifiedChatComposer>
    </div>

    <!-- Trace 抽屉 -->
    <AgentRunTraceDrawer
      v-model="traceDrawerVisible"
      :session-id="currentSession?.id ?? null"
      :prefer-run-id="tracePreferRunId"
    />
  </div>
</template>

<style scoped>
.chat-pane {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--surface);
  overflow: hidden;
}

/* ─── header ─────────────────────────────────────────────── */
.cp-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 14px 10px 18px;
  border-bottom: 1px solid var(--line);
  flex-shrink: 0;
}
.cp-header-info {
  flex: 1;
  min-width: 0;
}
.cp-header-title {
  font-size: 13px;
  font-weight: var(--fw-semibold, 600);
  color: var(--text);
}
.cp-top-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.cp-top-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  padding: 0;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
  color: var(--text-3);
  cursor: pointer;
  transition: all 0.12s ease;
}
.cp-top-btn:hover {
  border-color: var(--brand);
  color: var(--brand);
}

/* ─── 对话区 ──────────────────────────────────────────────── */
.cp-conversation {
  flex: 1;
  min-height: 0;
}

/* ─── 输入区 ──────────────────────────────────────────────── */
.cp-input-area {
  flex-shrink: 0;
  padding: 10px 12px 12px;
  border-top: 1px solid var(--line);
  background: var(--surface);
}
</style>
