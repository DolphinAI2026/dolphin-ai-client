<!-- frontend/src/views/workspace/ChatPane.vue
     统一工作区 Phase 1 — 中央对话面板

     镜像 AppAssistantPanel.vue 的结构，差异：
     1. 通用对话：appId: ref(null)（不锁应用）
     2. 产物事件抛给外壳：@open-artifact="(a) => emit('open-artifact', a)"（不在本组件开抽屉）
     3. props { sessionId }：watch sessionId → loadSession(id)（切会话不重挂）
     4. emit 'open-artifact' / 'session-changed' -->
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import AgentConversation from '@/components/common/AgentConversation.vue'
import AgentRunTraceDrawer from '@/components/common/AgentRunTraceDrawer.vue'
import UnifiedChatComposer from '@/components/common/UnifiedChatComposer.vue'
import BuilderModelPicker from '@/components/common/BuilderModelPicker.vue'
import { useAiChatSession } from '@/composables/useAiChatSession'
import { aiChatApi, type AIChatSession } from '@/api/aiChat'
import { listSkills } from '@/api/skills'
import { llmConfigApi, type BuilderModelOption } from '@/api/llmConfig'
import type { AgentMessage } from '@/components/common/agent-conversation/types'
import type { UnifiedChatAttachment } from '@/components/common/chatComposer'
import { isImageFile } from '@/utils/pasteImages'

const props = defineProps<{
  /** 外壳传入的会话 id（null = 新建对话） */
  sessionId: number | null
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

const {
  currentSession,
  sessions,
  agentMessages,
  artifacts,
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

// ─── 会话历史抽屉 ───
const drawerOpen = ref(false)

async function openDrawer() {
  drawerOpen.value = true
  try {
    await loadSessions()
  } catch (e: any) {
    ElMessage.error(e?.message || '加载会话失败')
  }
}

async function onSelectSession(s: AIChatSession) {
  drawerOpen.value = false
  if (currentSession.value && currentSession.value.id === s.id) return
  try {
    await loadSession(s.id)
    syncSelectedLlmFromSession()
  } catch (e: any) {
    ElMessage.error(e?.message || '加载历史失败')
  }
}

function onNewSession() {
  drawerOpen.value = false
  newSession()
}

async function onDeleteSession(s: AIChatSession) {
  try {
    await aiChatApi.deleteSession(s.id)
  } catch (e: any) {
    ElMessage.error(e?.message || '删除失败')
    return
  }
  if (currentSession.value && currentSession.value.id === s.id) newSession()
  try {
    await loadSessions()
  } catch {
    /* ignore */
  }
  ElMessage.success('已删除')
}

function fmtSessionTime(t: string | null): string {
  if (!t) return ''
  try {
    const d = new Date(t)
    if (Number.isNaN(d.getTime())) return ''
    return d.toLocaleString()
  } catch {
    return ''
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

// ─── 产物计数（头部按钮用） ───
const uniqueArtifactCount = computed(() => {
  const names = new Set(artifacts.value.map(a => a.filename))
  return names.size
})

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
        <!-- 产物数量入口（外壳承载产物面板，点击通知外壳） -->
        <button
          v-if="artifacts.length > 0"
          class="cp-top-btn cp-artifact-btn"
          title="查看产物"
          @click="emit('open-artifact', artifacts[artifacts.length - 1])"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
          </svg>
          <span class="cp-artifact-badge">{{ uniqueArtifactCount }}</span>
        </button>
        <!-- Trace 入口 -->
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
        <!-- 历史会话 -->
        <button class="cp-top-btn" title="历史对话" @click="openDrawer">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 7h18M3 12h18M3 17h18" />
          </svg>
        </button>
        <!-- 新对话 -->
        <button class="cp-top-btn" title="新对话" @click="onNewSession">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 5v14M5 12h14" />
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

    <!-- 会话历史抽屉 -->
    <el-drawer
      v-model="drawerOpen"
      title="历史对话"
      direction="rtl"
      size="360px"
      :append-to-body="true"
    >
      <div class="cp-drawer">
        <button class="cp-drawer-new" type="button" @click="onNewSession">+ 新对话</button>
        <div v-if="!sessions.length" class="cp-drawer-empty">还没有会话</div>
        <ul v-else class="cp-drawer-list">
          <li
            v-for="s in sessions"
            :key="s.id"
            class="cp-drawer-item"
            :class="{ active: currentSession && currentSession.id === s.id }"
            @click="onSelectSession(s)"
          >
            <div class="cp-drawer-item-main">
              <div class="cp-drawer-item-title">{{ s.title || '未命名会话' }}</div>
              <div class="cp-drawer-item-time">{{ fmtSessionTime(s.updated_at || s.created_at) }}</div>
            </div>
            <button
              class="cp-drawer-del"
              type="button"
              title="删除"
              @click.stop="onDeleteSession(s)"
            >×</button>
          </li>
        </ul>
      </div>
    </el-drawer>

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
.cp-artifact-btn {
  width: auto;
  padding: 0 8px;
  gap: 4px;
}
.cp-artifact-badge {
  font-size: 10px;
  font-weight: 600;
  min-width: 16px;
  height: 16px;
  line-height: 16px;
  text-align: center;
  border-radius: 8px;
  background: var(--brand);
  color: #fff;
  display: inline-block;
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

/* ─── 会话历史抽屉 ────────────────────────────────────────── */
.cp-drawer {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.cp-drawer-new {
  align-self: stretch;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
  color: var(--brand);
  font-family: inherit;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.12s ease;
}
.cp-drawer-new:hover {
  border-color: var(--brand);
  background: color-mix(in srgb, var(--brand) 6%, var(--surface));
}
.cp-drawer-empty {
  padding: 24px 8px;
  text-align: center;
  font-size: 12.5px;
  color: var(--text-3);
}
.cp-drawer-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.cp-drawer-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.12s ease;
}
.cp-drawer-item:hover {
  background: var(--surface-2, rgba(116, 128, 171, 0.06));
}
.cp-drawer-item.active {
  background: var(--brand-soft, rgba(99, 102, 241, 0.1));
}
.cp-drawer-item-main {
  flex: 1;
  min-width: 0;
}
.cp-drawer-item-title {
  font-size: 13px;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cp-drawer-item-time {
  margin-top: 2px;
  font-size: 11px;
  color: var(--text-3);
}
.cp-drawer-del {
  flex-shrink: 0;
  border: 0;
  background: transparent;
  color: var(--text-3);
  cursor: pointer;
  font-size: 16px;
  line-height: 1;
  padding: 2px 6px;
  border-radius: 6px;
}
.cp-drawer-del:hover {
  color: var(--err);
  background: var(--err-soft);
}
</style>
