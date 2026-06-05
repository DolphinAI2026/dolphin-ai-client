<!-- frontend/src/components/v2/AppAssistantPanel.vue
     2026-06-04 (Task C2/C3 — config-assistant → unified 引擎统一)

     ChatPage 右栏「配置助手」的统一引擎替身：用 useAiChatSession composable 把 AI Builder
     unified 那套「会话 + SSE 流式 + 工具卡 + ask 卡 + artifact 卡 + 每条回复 run_id」核心逻辑
     drive 起来，复用共享的 AgentConversation 渲染器。会话锁定在传入的 applicationId 上
     （建会话带 app_id、loadSessions 按 app_id 过滤），一套引擎覆盖 配置 + codegen + 会话 +
     产出物 + trace。

     ⚠️ ADDITIVE：本组件不替换 ConfigAssistantPanel 的引用 —— 由 controller 单独做一行 tag swap
     （<ConfigAssistantPanel> → <AppAssistantPanel>）。为了让 swap 是真·一行，本组件的 props /
     events 跟 ChatPage 当前传给 ConfigAssistantPanel 的**完全同名**：
       props: applicationId / appName / currentSection / currentSectionTab / designerSub
       emits: refresh-iframe / close / upload-doc

     没有前端单测 runner，验证只能靠 `npm run build:nocheck` 编译；reactivity / binding bug 只会
     在 live 测试时暴露。 -->
<script setup lang="ts">
import { computed, onMounted, ref, toRef, watch, type Ref } from 'vue'
import { ElMessage } from 'element-plus'

import AgentConversation from '@/components/common/AgentConversation.vue'
import AgentRunTraceDrawer from '@/components/common/AgentRunTraceDrawer.vue'
import { usePanelResize } from './config-assistant/composables/usePanelResize'
import { useAiChatSession } from '@/composables/useAiChatSession'
import { aiChatApi, type AIChatSession } from '@/api/aiChat'
import type { AgentMessage } from '@/components/common/agent-conversation/types'

// props/emit 跟 ChatPage 当前传给 ConfigAssistantPanel 的完全同名，保证 controller 一行 tag swap。
const props = defineProps<{
  /** 锁定的应用 id（post-deploy 时由 ChatPage resolvedAppId 传，可能为 null） */
  applicationId: number | null
  appName?: string
  /** SectionNav 当前 section 软引导（透传给 unified 后端 section 字段） */
  currentSection?: string | null
  /** 当前 sub-tab（保留兼容 ChatPage 契约，本组件目前仅透传 section 不做 chip 矩阵） */
  currentSectionTab?: string | null
  /** design tab 选中菜单后的 designer sub（保留兼容 ChatPage 契约） */
  designerSub?: string | null
  /** 当前选中的菜单名（来自 ChatPage selectedApaasMenuName） */
  selectedMenuName?: string | null
  /** 当前选中的菜单 id（来自 ChatPage selectedApaasMenuId） */
  selectedMenuId?: string | null
}>()

const emit = defineEmits<{
  /** 工具成功改了配置 → 通知父组件刷新 iframe / 重建原生 panel（C3） */
  (e: 'refresh-iframe'): void
  /** 收起助手回到 FAB */
  (e: 'close'): void
  /** 上传新设计文档更新应用（保留兼容，由父 ChatPage 触发 diff/审核流程） */
  (e: 'upload-doc'): void
}>()

// ─── 拖宽 —— 复用 config 的 usePanelResize；maxWidth 拉大到 1200 给 codegen diff 留空间 ───
const { panelWidth, isResizing, onResizeStart } = usePanelResize({
  storageKey: 'apaas-app-assistant-width-v1',
  defaultWidth: 420,
  minWidth: 320,
  maxWidth: 1200,
})

// ─── unified 会话引擎 ───
// applicationId 可能是 null（ChatPage resolvedAppId 在没 app_id 时给 null）。composable 接受
// Ref<number | null | undefined>，建会话带 app_id、loadSessions 按它过滤。
const appIdRef = toRef(props, 'applicationId')
const sectionRef = toRef(props, 'currentSection')
// 当前视图上下文：「菜单名」+「设计器 tab」组合成人话字符串，透传到后端注入 app-context 系统提示。
const viewContext = computed<string | null>(() => {
  const name = props.selectedMenuName
  if (!name) return null
  const sub = props.designerSub === 'form' ? '表单设计器'
    : props.designerSub === 'list' ? '列表设计器'
    : props.designerSub === 'process' ? '流程设计器'
    : (props.currentSectionTab || props.currentSection || '')
  return `「${name}」${sub ? '（' + sub + '）' : ''}`
})
// 模型选择：unified 引擎下暂不暴露选择器（ensureSession 不传 selectedLlmId → 后端走会话默认 / 平台配置）。
const selectedLlmId = ref<number | null>(null)

const {
  currentSession,
  sessions,
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
  appId: appIdRef,
  section: sectionRef,
  viewContext: viewContext as Ref<string | null | undefined>,
  selectedLlmId,
})

// ─── 输入框 ───
const inputText = ref('')
const fileInputRef = ref<HTMLInputElement | null>(null)
const pendingFiles = ref<File[]>([])

function onPickFiles() {
  fileInputRef.value?.click()
}
function onFilesChosen(e: Event) {
  const el = e.target as HTMLInputElement
  const files = el.files ? Array.from(el.files) : []
  if (files.length) pendingFiles.value = [...pendingFiles.value, ...files]
  // 清空原生 input，方便重复选同名文件
  el.value = ''
}
function removePendingFile(idx: number) {
  pendingFiles.value = pendingFiles.value.filter((_, i) => i !== idx)
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

function onInputKeydown(e: KeyboardEvent) {
  // Enter 发送，Shift+Enter 换行（与 unified 输入习惯一致）
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    void doSend()
  }
}

async function onStop() {
  try {
    await stop()
  } catch {
    /* ignore */
  }
}

// ─── 会话抽屉（历史 / 新对话） ───
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

// ─── Trace 抽屉（复用共享 AgentRunTraceDrawer） ───
const traceDrawerVisible = ref(false)
const tracePreferRunId = ref<string | null>(null)

// 每条回复脚注「查看本次 trace」
function onOpenTrace(message: AgentMessage) {
  const rid = (message?.meta as any)?.run_id
  if (!rid) return
  tracePreferRunId.value = rid
  traceDrawerVisible.value = true
}
// 会话级「Agent 活动」入口（默认选最近一次 run）
function openSessionTrace() {
  tracePreferRunId.value = currentRunId.value
  traceDrawerVisible.value = true
}

// ─── C3：工具成功改配置 → emit refresh-iframe ───
// 复用 config 的规则（ConfigAssistantMessages.vue ~L38-49 + useConfigChat.ts ~L15）：
// 工具名匹配 /^(update_|create_|add_|delete_|disable_|set_)/ 且 status==='success'。
// 这里映射到 useAiChatSession 产出的 AgentMessage 形状：tool 项是 { kind:'tool', tool:{ name, status } }
// （composable 已把 tool_group 拆成单条 tool，所以只需扫 kind==='tool'）。
// 用 Set<string> 按工具 message id 去重，避免 agentMessages 每次重算重复 emit；
// 略延 200ms 给 platform 端 API 真正落库（对齐 config）。
const MODIFY_TOOL_PATTERN = /^(update_|create_|add_|delete_|disable_|set_)/
const _autoRefreshed = new Set<string>()

watch(
  agentMessages,
  (msgs) => {
    for (const m of msgs) {
      if (m.kind !== 'tool' || !m.tool) continue
      if (m.tool.status !== 'success') continue
      if (!MODIFY_TOOL_PATTERN.test(m.tool.name)) continue
      const key = String(m.id)
      if (_autoRefreshed.has(key)) continue
      _autoRefreshed.add(key)
      // apaas 写后读有传播延迟：写工具已成功(原生编辑器即时生效),但 get_apaas_form_detail
      // 读接口要一会儿才追上。早刷一次(快路径)+ 晚刷一次(等 apaas 读追上写),否则重挂的
      // GET form detail 拿到改前 stale(实测:原生后台已必填、中间预览没变)。
      setTimeout(() => emit('refresh-iframe'), 250)
      setTimeout(() => emit('refresh-iframe'), 2000)
    }
  },
  { deep: true },
)

// ─── 切应用：重置会话 + 重新拉历史（去重表也清，避免旧 app 的 tool id 误判） ───
watch(
  () => props.applicationId,
  () => {
    _autoRefreshed.clear()
    newSession()
    void loadSessions().catch(() => { /* ignore */ })
  },
)

// 上下文卡片标题/副标题（沿用 config 的人话化映射，给用户「锁定在哪个应用/区域」的感知）
const SECTION_LABELS: Record<string, string> = {
  ui: '功能页面',
  design: '功能页面',
  data: '数据配置',
  logic: '流程配置',
  permission: '权限配置',
  perm: '权限配置',
  log: '操作记录',
}
const DESIGNER_SUB_LABELS: Record<string, string> = {
  form: '表单设计',
  list: '列表设计',
  process: '流程设计',
  data: '数据 schema',
  perm: '权限',
}
const contextTitle = computed(() => {
  const sub = (props.designerSub || '').trim()
  if (sub && DESIGNER_SUB_LABELS[sub]) return DESIGNER_SUB_LABELS[sub]
  const section = (props.currentSection || '').trim()
  return SECTION_LABELS[section] || (props.appName || '当前应用')
})

onMounted(() => {
  void loadSessions().catch(() => { /* ignore */ })
})
</script>

<template>
  <aside
    class="app-assistant"
    :class="{ 'is-resizing': isResizing }"
    :style="{ width: panelWidth + 'px' }"
  >
    <!-- 左边缘拖拽 handle -->
    <div class="aa-resize-handle" @pointerdown="onResizeStart" title="拖拽调整宽度" />

    <!-- 顶部 actions: 会话列表 / 新对话 / Agent 活动 / 关闭 -->
    <header class="aa-header">
      <div class="aa-header-info">
        <div class="aa-header-title">AI Builder</div>
        <div class="aa-header-sub" :title="contextTitle">{{ contextTitle }}</div>
      </div>
      <div class="aa-top-actions">
        <button
          v-if="currentSession"
          class="aa-top-btn aa-trace-btn"
          title="查看本次会话的 Agent 活动 / Trace"
          @click="openSessionTrace"
        >
          Agent 活动
        </button>
        <button class="aa-top-btn" title="历史对话" @click="openDrawer">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 7h18M3 12h18M3 17h18" />
          </svg>
        </button>
        <button class="aa-top-btn" title="新对话" @click="onNewSession">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 5v14M5 12h14" />
          </svg>
        </button>
        <button class="aa-top-btn" title="收起助手" @click="emit('close')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M18 6L6 18M6 6l12 12" />
          </svg>
        </button>
      </div>
    </header>

    <!-- 对话区 — 复用共享 AgentConversation 渲染器 -->
    <AgentConversation
      class="aa-conversation"
      :messages="agentMessages"
      :typing="typing"
      :typing-seconds="typingSeconds"
      :tool-grouping="true"
      empty-title="AI Builder"
      empty-hint="描述你想改的配置或要开发的功能"
      @open-trace="onOpenTrace"
      @answer-ask="(opt) => send(opt)"
    />

    <!-- 输入区 -->
    <div class="aa-input-area">
      <div v-if="pendingFiles.length" class="aa-attach-row">
        <span
          v-for="(f, i) in pendingFiles"
          :key="i"
          class="aa-attach-chip"
        >
          <span class="aa-attach-name">📎 {{ f.name }}</span>
          <button class="aa-attach-x" type="button" title="移除" @click="removePendingFile(i)">×</button>
        </span>
      </div>
      <div class="aa-input-box">
        <button
          class="aa-attach-btn"
          type="button"
          title="添加附件"
          :disabled="sending"
          @click="onPickFiles"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
          </svg>
        </button>
        <input
          ref="fileInputRef"
          type="file"
          multiple
          class="aa-file-input"
          @change="onFilesChosen"
        />
        <textarea
          v-model="inputText"
          class="aa-input"
          rows="1"
          placeholder="描述你想改的配置或要开发的功能…"
          @keydown="onInputKeydown"
        />
        <button
          v-if="sending"
          class="aa-send-btn aa-stop-btn"
          type="button"
          title="停止"
          @click="onStop"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
            <rect x="6" y="6" width="12" height="12" rx="2" />
          </svg>
        </button>
        <button
          v-else
          class="aa-send-btn"
          type="button"
          title="发送 (Enter)"
          :disabled="!inputText.trim() && pendingFiles.length === 0"
          @click="doSend"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" />
          </svg>
        </button>
      </div>
    </div>

    <!-- 会话历史抽屉（app-scoped：loadSessions 已按 applicationId 过滤） -->
    <el-drawer
      v-model="drawerOpen"
      title="历史对话"
      direction="rtl"
      size="360px"
      :append-to-body="true"
    >
      <div class="aa-drawer">
        <button class="aa-drawer-new" type="button" @click="onNewSession">+ 新对话</button>
        <div v-if="!sessions.length" class="aa-drawer-empty">还没有会话</div>
        <ul v-else class="aa-drawer-list">
          <li
            v-for="s in sessions"
            :key="s.id"
            class="aa-drawer-item"
            :class="{ active: currentSession && currentSession.id === s.id }"
            @click="onSelectSession(s)"
          >
            <div class="aa-drawer-item-main">
              <div class="aa-drawer-item-title">{{ s.title || '未命名会话' }}</div>
              <div class="aa-drawer-item-time">{{ fmtSessionTime(s.updated_at || s.created_at) }}</div>
            </div>
            <button
              class="aa-drawer-del"
              type="button"
              title="删除"
              @click.stop="onDeleteSession(s)"
            >×</button>
          </li>
        </ul>
      </div>
    </el-drawer>

    <!-- Trace 抽屉（复用共享组件） -->
    <AgentRunTraceDrawer
      v-model="traceDrawerVisible"
      :session-id="currentSession?.id ?? null"
      :prefer-run-id="tracePreferRunId"
    />
  </aside>
</template>

<style scoped>
.app-assistant {
  position: relative;
  display: flex;
  flex-direction: column;
  height: 100%;
  border-left: 1px solid var(--line);
  background: var(--surface);
  flex-shrink: 0;
  overflow: hidden;
}

.app-assistant.is-resizing {
  cursor: ew-resize;
  user-select: none;
}

/* ─── 拖拽 handle (左边缘 5px) ───────────────────────────── */
.aa-resize-handle {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 5px;
  cursor: ew-resize;
  z-index: 10;
  transition: background 0.12s ease;
  touch-action: none;
}
.aa-resize-handle:hover,
.app-assistant.is-resizing .aa-resize-handle {
  background: var(--brand-ring, var(--brand));
  opacity: 0.4;
}

/* ─── 顶部 header ──────────────────────────────────────── */
.aa-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 14px 10px 18px;
  border-bottom: 1px solid var(--line);
  flex-shrink: 0;
}
.aa-header-info {
  min-width: 0;
  flex: 1;
}
.aa-header-title {
  font-size: 14px;
  font-weight: var(--fw-semibold, 600);
  color: var(--text);
}
.aa-header-sub {
  margin-top: 2px;
  font-size: 11px;
  color: var(--text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.aa-top-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.aa-top-btn {
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
.aa-top-btn:hover {
  border-color: var(--brand);
  color: var(--brand);
}
.aa-trace-btn {
  width: auto;
  padding: 0 10px;
  font-family: inherit;
  font-size: 12px;
}

/* ─── 对话区 ──────────────────────────────────────────── */
.aa-conversation {
  flex: 1;
  min-height: 0;
}

/* ─── 输入区 ──────────────────────────────────────────── */
.aa-input-area {
  flex-shrink: 0;
  padding: 10px 14px 14px;
  border-top: 1px solid var(--line);
  background: var(--surface);
}
.aa-attach-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}
.aa-attach-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border-radius: 999px;
  background: var(--surface-2, var(--surface));
  border: 1px solid var(--line);
  font-size: 11px;
  color: var(--text-2, var(--text));
  max-width: 100%;
}
.aa-attach-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 200px;
}
.aa-attach-x {
  border: 0;
  background: transparent;
  color: var(--text-3);
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
  padding: 0;
}
.aa-attach-x:hover {
  color: var(--err, #dc2626);
}
.aa-input-box {
  display: flex;
  align-items: flex-end;
  gap: 6px;
  padding: 6px 8px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--surface);
  transition: border-color 0.12s ease;
}
.aa-input-box:focus-within {
  border-color: var(--brand);
}
.aa-attach-btn,
.aa-send-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--text-3);
  cursor: pointer;
  transition: all 0.12s ease;
}
.aa-attach-btn:hover:not(:disabled) {
  color: var(--brand);
  background: color-mix(in srgb, var(--brand) 8%, var(--surface));
}
.aa-attach-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.aa-file-input {
  display: none;
}
.aa-input {
  flex: 1;
  min-width: 0;
  border: 0;
  outline: none;
  resize: none;
  background: transparent;
  color: var(--text);
  font-family: inherit;
  font-size: 13px;
  line-height: 1.5;
  max-height: 140px;
  padding: 6px 2px;
}
.aa-input::placeholder {
  color: var(--text-4, var(--text-3));
}
.aa-send-btn {
  background: var(--brand);
  color: var(--text-inverse, #fff);
}
.aa-send-btn:hover:not(:disabled) {
  opacity: 0.88;
}
.aa-send-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.aa-stop-btn {
  background: var(--err, #dc2626);
}
.aa-stop-btn:hover {
  opacity: 0.88;
}

/* ─── 会话抽屉 ────────────────────────────────────────── */
.aa-drawer {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.aa-drawer-new {
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
.aa-drawer-new:hover {
  border-color: var(--brand);
  background: color-mix(in srgb, var(--brand) 6%, var(--surface));
}
.aa-drawer-empty {
  padding: 24px 8px;
  text-align: center;
  font-size: 12.5px;
  color: var(--text-3);
}
.aa-drawer-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.aa-drawer-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.12s ease;
}
.aa-drawer-item:hover {
  background: var(--surface-2, rgba(116, 128, 171, 0.06));
}
.aa-drawer-item.active {
  background: var(--brand-soft, rgba(99, 102, 241, 0.1));
}
.aa-drawer-item-main {
  flex: 1;
  min-width: 0;
}
.aa-drawer-item-title {
  font-size: 13px;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.aa-drawer-item-time {
  margin-top: 2px;
  font-size: 11px;
  color: var(--text-3);
}
.aa-drawer-del {
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
.aa-drawer-del:hover {
  color: var(--err, #dc2626);
  background: rgba(220, 38, 38, 0.08);
}
</style>
