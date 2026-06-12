<!-- frontend/src/components/v2/AppAssistantPanel.vue
     2026-06-04 (Task C2/C3 — config-assistant → unified 引擎统一)

     ChatPage 右栏「配置助手」的统一引擎替身：用 useAiChatSession composable 把 AI Builder
     unified 那套「会话 + SSE 流式 + 工具卡 + ask 卡 + artifact 卡 + 每条回复 run_id」核心逻辑
     drive 起来，复用共享的 AgentConversation 渲染器。会话锁定在传入的 applicationId 上
     （建会话带 app_id、loadSessions 按 app_id 过滤），一套引擎覆盖 配置 + codegen + 会话 +
     产出物 + trace。

     props: applicationId / appName / currentSection / currentSectionTab / designerSub
     emits: refresh-iframe / close / upload-doc

     没有前端单测 runner，验证只能靠 `npm run build:nocheck` 编译；reactivity / binding bug 只会
     在 live 测试时暴露。 -->
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, toRef, watch, type Ref } from 'vue'
import { ElMessage } from 'element-plus'

import AgentConversation from '@/components/common/AgentConversation.vue'
import AgentRunTraceDrawer from '@/components/common/AgentRunTraceDrawer.vue'
import UnifiedChatComposer from '@/components/common/UnifiedChatComposer.vue'
import { usePanelResize } from './config-assistant/composables/usePanelResize'
import { useAiChatSession } from '@/composables/useAiChatSession'
import { aiChatApi, type AIChatSession } from '@/api/aiChat'
import { llmConfigApi, type BuilderModelOption } from '@/api/llmConfig'
import { renderMd } from '@/utils/markdown'
import { isImageFile } from '@/utils/pasteImages'
import type { AgentMessage } from '@/components/common/agent-conversation/types'
import type { UnifiedChatAttachment } from '@/components/common/chatComposer'

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
  /** 全屏展开/收缩切换 */
  (e: 'update:expanded', value: boolean): void
}>()

// ─── 展开/收缩 ───
const expanded = defineModel<boolean>('expanded', { default: false })
function toggleExpand() {
  expanded.value = !expanded.value
}

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
// 模型选择：跟 AIChatPage 一致 —— 拉 builder 模型列表，底部选择器切换，落到会话
// （ensureSession 建会话带上、切换时 updateSession 落库）。
const selectedLlmId = ref<number | null>(null)
const llmOptions = ref<BuilderModelOption[]>([])
const modelMenuOpen = ref(false)
const modelPickerRef = ref<HTMLElement | null>(null)
const selectedLlmName = computed(() => {
  const selected = llmOptions.value.find(option => option.id === selectedLlmId.value)
  return selected?.config_name || '默认模型'
})

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
  appId: appIdRef,
  section: sectionRef,
  viewContext: viewContext as Ref<string | null | undefined>,
  selectedLlmId,
})

// ─── 输入框 —— 复用共享 UnifiedChatComposer（自动撑高 / Shift+Enter 换行 / 附件 / 停止） ───
const inputText = ref('')
const pendingFiles = ref<File[]>([])
// 待发附件映射成 composer 的展示模型（图片走缩略 kind=image）。
const composerAttachments = computed<UnifiedChatAttachment[]>(() =>
  pendingFiles.value.map((file, index) => ({
    id: index,
    name: file.name,
    kind: isImageFile(file) ? 'image' : 'file',
  })),
)

// composer 的附件按钮 / 粘贴截图都 emit files-picked → 累积到 pendingFiles。
function onComposerFilesPicked(files: File[]) {
  if (files.length) pendingFiles.value = [...pendingFiles.value, ...files]
}
function removePendingFileByIndex(_: UnifiedChatAttachment, index: number) {
  pendingFiles.value = pendingFiles.value.filter((_, i) => i !== index)
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

// ─── 模型选择 —— 拉 builder 模型列表 + 切换落库（对齐 AIChatPage） ───
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
  // 没当前会话：只留本地，作为下次 ensureSession 的默认模型。
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

function toggleModelMenu() {
  if (!llmOptions.value.length) return
  modelMenuOpen.value = !modelMenuOpen.value
}

async function chooseModel(id: number | null) {
  selectedLlmId.value = id
  modelMenuOpen.value = false
  await onChangeLlm()
}

function closeModelMenuOnOutside(event: MouseEvent) {
  const root = modelPickerRef.value
  if (!root || !modelMenuOpen.value) return
  if (event.target instanceof Node && root.contains(event.target)) return
  modelMenuOpen.value = false
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

// ─── 产物（设计文档 md）查看抽屉 ───
// AgentConversation 的 artifact 卡 emit('open-artifact', artifact)；AIChatPage 走自己的
// 右栏面板，这里(嵌在 ChatPage 右栏)没有那套，自带一个抽屉渲染全文。否则点卡片无反应。
// 头部「设计文档 N」按钮：点击打开最新版产物。
const uniqueArtifactCount = computed(() => {
  const names = new Set(artifacts.value.map(a => a.filename))
  return names.size
})
function openLatestArtifact() {
  if (!artifacts.value.length) return
  // 取最新版(id 最大的那条)
  const latest = [...artifacts.value].sort((a, b) => (b.id ?? 0) - (a.id ?? 0))[0]
  onOpenArtifact({
    filename: latest.filename,
    version: latest.version,
    preview: latest.preview || latest.content?.slice(0, 200) || '',
  })
}

const artifactDrawerVisible = ref(false)
const artifactName = ref('')
const artifactContent = ref('')
const artifactLoading = ref(false)
async function onOpenArtifact(artifact: any) {
  if (!artifact) return
  artifactName.value = artifact.filename || '设计文档'
  artifactContent.value = ''
  artifactDrawerVisible.value = true
  if (!currentSession.value) {
    artifactContent.value = artifact.preview || ''
    return
  }
  artifactLoading.value = true
  try {
    const ver =
      artifact.version != null && !Number.isNaN(Number(artifact.version))
        ? Number(artifact.version)
        : undefined
    const detail = await aiChatApi.getArtifact(currentSession.value.id, artifact.filename, ver)
    artifactContent.value = detail.content || artifact.preview || ''
  } catch {
    ElMessage.error('加载设计文档失败')
    artifactContent.value = artifact.preview || ''
  } finally {
    artifactLoading.value = false
  }
}
function copyArtifact() {
  if (!artifactContent.value) return
  navigator.clipboard
    .writeText(artifactContent.value)
    .then(() => ElMessage.success('已复制'))
    .catch(() => {})
}
function downloadArtifact() {
  if (!artifactContent.value) return
  const blob = new Blob([artifactContent.value], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = artifactName.value || 'document.md'
  a.click()
  URL.revokeObjectURL(url)
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
      // 单次 emit 即可:apaas 写后读有 ~数秒传播延迟(写工具已成功、原生编辑器即时生效,
      // 但 detailPageConfigById 读接口要一会儿才追上)。这里只发一次刷新信号,
      // 真正"跨越延迟窗口的静默多档重试"在 FormDesignerPanel(refreshNonce 驱动)里做。
      setTimeout(() => emit('refresh-iframe'), 200)
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
  void loadLlmOptions()
  void loadSessions().catch(() => { /* ignore */ })
  document.addEventListener('click', closeModelMenuOnOutside)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', closeModelMenuOnOutside)
})
</script>

<template>
  <aside
    class="app-assistant"
    :class="{ 'is-resizing': isResizing, 'is-expanded': expanded }"
    :style="expanded ? undefined : { width: panelWidth + 'px' }"
  >
    <!-- 左边缘拖拽 handle（展开态隐藏） -->
    <div v-if="!expanded" class="aa-resize-handle" @pointerdown="onResizeStart" title="拖拽调整宽度" />

    <!-- 顶部 actions: 会话列表 / 新对话 / Agent 活动 / 关闭 -->
    <header class="aa-header">
      <div class="aa-header-info">
        <div class="aa-header-title">AI Builder</div>
        <div class="aa-header-sub" :title="contextTitle">{{ contextTitle }}</div>
      </div>
      <div class="aa-top-actions">
        <button
          v-if="artifacts.length > 0"
          class="aa-top-btn aa-artifact-btn"
          title="查看设计文档"
          @click="openLatestArtifact"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
          </svg>
          <span class="aa-artifact-badge">{{ uniqueArtifactCount }}</span>
        </button>
        <button
          v-if="currentSession"
          class="aa-top-btn aa-trace-btn"
          title="查看本次会话的 Agent 活动 / Trace"
          @click="openSessionTrace"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
          </svg>
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
        <button
          class="aa-top-btn"
          :title="expanded ? '收缩为侧栏' : '展开全屏'"
          @click="toggleExpand"
        >
          <svg v-if="!expanded" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="15 3 21 3 21 9" /><polyline points="9 21 3 21 3 15" />
            <line x1="21" y1="3" x2="14" y2="10" /><line x1="3" y1="21" x2="10" y2="14" />
          </svg>
          <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="4 14 10 14 10 20" /><polyline points="20 10 14 10 14 4" />
            <line x1="14" y1="10" x2="21" y2="3" /><line x1="3" y1="21" x2="10" y2="14" />
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
      @open-artifact="onOpenArtifact"
      @answer-ask="(opt) => send(opt)"
    />

    <!-- 输入区 — 复用共享 UnifiedChatComposer（撑高 / Shift+Enter 换行 / 附件 / 模型选择 / 停止） -->
    <div class="aa-input-area">
      <UnifiedChatComposer
        v-model="inputText"
        :attachments="composerAttachments"
        :sending="sending"
        :send-disabled="!inputText.trim() && pendingFiles.length === 0"
        :multiple="true"
        placeholder="描述配置或开发需求..."
        hint=""
        sending-hint=""
        @send="doSend"
        @stop="onStop"
        @files-picked="onComposerFilesPicked"
        @remove-attachment="removePendingFileByIndex"
      >
        <template #footer-left>
          <div v-if="llmOptions.length" ref="modelPickerRef" class="aa-model-picker">
            <button
              type="button"
              class="aa-model-trigger"
              :class="{ 'is-open': modelMenuOpen }"
              title="切换模型"
              aria-haspopup="listbox"
              :aria-expanded="modelMenuOpen"
              @click.stop="toggleModelMenu"
              @keydown.esc.stop="modelMenuOpen = false"
            >
              <span class="aa-model-trigger-text">{{ selectedLlmName }}</span>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="m6 9 6 6 6-6" />
              </svg>
            </button>
            <div v-if="modelMenuOpen" class="aa-model-menu" role="listbox">
              <button
                type="button"
                class="aa-model-option"
                :class="{ 'is-selected': selectedLlmId === null }"
                role="option"
                :aria-selected="selectedLlmId === null"
                @click.stop="chooseModel(null)"
              >
                <span>默认模型</span>
              </button>
              <button
                v-for="m in llmOptions"
                :key="m.id"
                type="button"
                class="aa-model-option"
                :class="{ 'is-selected': selectedLlmId === m.id }"
                role="option"
                :aria-selected="selectedLlmId === m.id"
                @click.stop="chooseModel(m.id)"
              >
                <span>{{ m.config_name }}</span>
              </button>
            </div>
          </div>
        </template>
      </UnifiedChatComposer>
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

    <!-- 设计文档（artifact md）查看抽屉 -->
    <el-drawer
      v-model="artifactDrawerVisible"
      :title="artifactName"
      direction="rtl"
      size="680px"
      :append-to-body="true"
    >
      <div class="aa-art-drawer">
        <div v-if="artifactLoading" class="aa-art-loading">加载中…</div>
        <template v-else>
          <div class="aa-art-actions">
            <button class="aa-art-copy" type="button" @click="copyArtifact">复制全文</button>
            <button class="aa-art-copy" type="button" @click="downloadArtifact">下载</button>
          </div>
          <div
            v-if="artifactContent"
            class="aa-art-md md"
            v-html="renderMd(artifactContent)"
          ></div>
          <div v-else class="aa-art-empty">文档内容为空</div>
        </template>
      </div>
    </el-drawer>
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
/* 展开态：撑满父容器剩余宽度 */
.app-assistant.is-expanded {
  flex: 1;
  min-width: 0;
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
  font-size: 13px;
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
/* 设计文档按钮：比普通 top-btn 宽一点以容纳 badge */
.aa-artifact-btn {
  width: auto;
  padding: 0 8px;
  gap: 4px;
}
.aa-artifact-badge {
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

/* ─── 对话区 ──────────────────────────────────────────── */
.aa-conversation {
  flex: 1;
  min-height: 0;
}
/* 这是窄右栏，整体字号比 AIChatPage 主对话缩一档（:deep 覆盖共享 AgentConversation，
   作用域仅限本面板，不影响 AIChatPage） */
.aa-conversation :deep(.ac-bubble) { font-size: 12.5px; }
.aa-conversation :deep(.ac-text h2) { font-size: 14px; }
.aa-conversation :deep(.ac-text h3) { font-size: 13px; }

/* ─── 输入区 —— UnifiedChatComposer 容器 ─────────────────── */
.aa-input-area {
  flex-shrink: 0;
  padding: 10px 12px 12px;
  border-top: 1px solid var(--line);
  background: var(--surface);
}
/* 窄栏里输入区优先保持一行工具栏，不显示快捷键说明。 */
.aa-input-area :deep(.ucc) {
  gap: 8px;
}
.aa-input-area :deep(.ucc-box) {
  border-radius: 10px;
}
.aa-input-area :deep(.ucc-input) {
  min-height: 34px;
  padding: 10px 12px 3px;
  font-size: 13px;
  line-height: 1.4;
}
.aa-input-area :deep(.ucc-footer) {
  flex-wrap: nowrap;
  gap: 8px;
  min-height: 32px;
  padding: 0 10px 10px;
}
.aa-input-area :deep(.ucc-footer-left) {
  flex: 0 1 auto;
  width: auto;
  max-width: min(220px, 58%);
  overflow: visible;
}
.aa-input-area :deep(.ucc-footer-right) {
  display: none;
}
.aa-input-area :deep(.ucc-attach) {
  width: 32px;
  min-height: 32px;
  padding: 0;
  justify-content: center;
}
.aa-input-area :deep(.ucc-send) {
  width: 42px;
  height: 42px;
  min-height: 42px;
}

/* 底部模型选择器（自定义菜单，避免原生 select 白底/系统高亮割裂） */
.aa-model-picker {
  position: relative;
  flex: 0 0 auto;
  width: clamp(118px, 14vw, 156px);
  min-width: 118px;
  max-width: 156px;
  z-index: 4;
}
.aa-model-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  width: 100%;
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text-3);
  height: 28px;
  padding: 0 8px 0 9px;
  border-radius: 6px;
  font-family: inherit;
  font-size: 11.5px;
  line-height: 1;
  cursor: pointer;
  outline: none;
  transition: border-color 0.16s ease, color 0.16s ease, background 0.16s ease;
}
.aa-model-trigger-text {
  min-width: 0;
  flex: 1 1 auto;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  text-align: left;
}
.aa-model-trigger:hover,
.aa-model-trigger.is-open {
  border-color: var(--brand);
  color: var(--text);
  background: color-mix(in srgb, var(--brand) 8%, transparent);
}
.aa-model-trigger svg {
  flex: 0 0 auto;
  opacity: 0.82;
  transition: transform 0.16s ease;
}
.aa-model-trigger.is-open svg {
  transform: rotate(180deg);
}
.aa-model-menu {
  position: absolute;
  left: 0;
  bottom: calc(100% + 6px);
  width: 100%;
  min-width: 156px;
  padding: 4px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: color-mix(in srgb, var(--surface) 94%, #050b18);
  box-shadow: 0 16px 36px rgba(0, 0, 0, 0.32);
}
.aa-model-option {
  display: flex;
  align-items: center;
  width: 100%;
  min-height: 28px;
  padding: 0 8px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--text-3);
  font: inherit;
  font-size: 12px;
  text-align: left;
  cursor: pointer;
}
.aa-model-option span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.aa-model-option:hover {
  background: color-mix(in srgb, var(--brand) 13%, transparent);
  color: var(--text);
}
.aa-model-option.is-selected {
  background: color-mix(in srgb, var(--brand) 18%, transparent);
  color: var(--brand-2);
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
  color: var(--err);
  background: var(--err-soft);
}

/* ─── 设计文档（artifact md）查看抽屉 ─── */
.aa-art-drawer { padding: 4px 2px 24px; }
.aa-art-loading, .aa-art-empty {
  padding: 40px 0; text-align: center; color: var(--text-3); font-size: 13px;
}
.aa-art-actions { display: flex; justify-content: flex-end; margin-bottom: 10px; }
.aa-art-copy {
  appearance: none; border: 1px solid var(--line); background: var(--surface-2);
  color: var(--text-2); padding: 4px 12px; font-size: 12px; border-radius: 6px;
  cursor: pointer; transition: color .15s, border-color .15s;
}
.aa-art-copy:hover { color: var(--text); border-color: var(--text-3); }
.aa-art-md {
  font-size: 13px; line-height: 1.7; color: var(--text);
  white-space: normal; word-break: break-word;
}
.aa-art-md :deep(h1) { font-size: 18px; margin: 16px 0 8px; font-weight: 600; }
.aa-art-md :deep(h2) { font-size: 15px; margin: 14px 0 6px; font-weight: 600; }
.aa-art-md :deep(h3) { font-size: 13.5px; margin: 12px 0 6px; font-weight: 600; }
.aa-art-md :deep(p) { margin: 0 0 8px; }
.aa-art-md :deep(ul), .aa-art-md :deep(ol) { margin: 4px 0 10px 20px; padding: 0; }
.aa-art-md :deep(li) { margin-bottom: 2px; }
.aa-art-md :deep(table) { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 12px; }
.aa-art-md :deep(th), .aa-art-md :deep(td) { border: 1px solid var(--line); padding: 5px 9px; }
.aa-art-md :deep(th) { background: var(--surface-2); }
.aa-art-md :deep(code) {
  background: var(--surface-2); padding: 1px 6px; border-radius: 3px; color: #f0824a;
  font-family: ui-monospace, Menlo, monospace; font-size: 11.5px;
}
.aa-art-md :deep(pre) {
  background: var(--surface-2); border: 1px solid var(--line);
  border-radius: 6px; padding: 10px 12px; overflow-x: auto;
}
.aa-art-md :deep(pre code) { background: transparent; padding: 0; color: var(--text); }
.aa-art-md :deep(a) { color: var(--brand); }
.aa-art-md :deep(blockquote) {
  border-left: 3px solid var(--line); padding-left: 10px;
  color: var(--text-3); margin: 8px 0;
}
</style>
