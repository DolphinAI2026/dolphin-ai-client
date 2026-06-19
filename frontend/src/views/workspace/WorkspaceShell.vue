<template>
  <div class="workspace-shell">
    <SessionSidebar
      module-name="工作区" brand-color="#f59e0b"
      :sessions="sessionItems" :active-id="activeSidebarId"
      collapse-key="workspace:aside-collapsed" new-label="+ 新会话"
      empty-hint="暂无会话,点上方新建"
      back-route="/" back-label="返回 AI Builder"
      :enable-rename="false" :enable-delete="false"
      @select="onSelect" @create="onCreate"
      @collapse-change="(v) => (asideCollapsed = v)" />
    <main class="ws-main">
      <header class="ws-top">
        <ToolMenu :binding="currentBinding" @open="onOpenPanel" />
      </header>
      <div class="ws-body" :class="{ 'has-panel': activePanelId }">
        <div class="ws-chat">
          <ChatPane :session-id="currentSessionId" :workspace-id="wsId" :app-id="appId"
            @open-artifact="onOpenArtifact" @session-changed="onSessionChanged"
            @workspace-detected="onWorkspaceDetected" />
        </div>
        <div v-if="activePanelId" class="ws-resizer" title="拖拽调整面板宽度" @pointerdown="onPanelResizeStart" />
        <div v-if="activePanelId" class="ws-panel" :style="{ width: wsPanelWidth + 'px' }">
          <PanelHost :active-panel-id="activePanelId"
            :binding="currentBinding" :session-id="currentSessionId" :artifact="openArtifact"
            @close="activePanelId = null" />
        </div>
      </div>
    </main>
  </div>
</template>
<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import SessionSidebar from '@/components/common/SessionSidebar.vue'
import ToolMenu from './ToolMenu.vue'
import PanelHost from './PanelHost.vue'
import ChatPane from './ChatPane.vue'
import { registerPhase1Panels } from './panels'
import { toSessionItems, type WorkspaceSession } from './sessionList'
import type { Binding } from './binding'
import { useAiChatSession } from '@/composables/useAiChatSession'
import { routeToBinding, parseSidebarSelect } from './workspaceRoute'
import { usePanelResize } from '@/components/v2/config-assistant/composables/usePanelResize'

registerPhase1Panels()
const route = useRoute()
const router = useRouter()
// 工具面板可拖拽调宽(handle 在面板左边界, 向左拖加宽) + localStorage 持久化
const { panelWidth: wsPanelWidth, onResizeStart: onPanelResizeStart } = usePanelResize({
  storageKey: 'workspace:panel-width', defaultWidth: 560, minWidth: 360, maxWidth: 1100, handleSide: 'left',
})
const { sessions, loadSessions } = useAiChatSession({ appId: ref(null) })

const currentSessionId = ref<number | null>(null)
const activePanelId = ref<string | null>(null)
const openArtifact = ref<any>(null)
const asideCollapsed = ref(false)
// Phase 2/3: 由 route.params.id + route.query.app_id 驱动; KeepAlive 单例切路由不 remount, 必须 watch
const currentBinding = ref<Binding>({ kind: 'none' })

watch([() => route.params.id, () => route.query.app_id], ([id, appIdRaw]) => {
  const s = typeof id === 'string' ? id : Array.isArray(id) ? (id[0] || '') : ''
  currentBinding.value = routeToBinding(s, appIdRaw)
}, { immediate: true })

// workspace 绑定时的 workspaceId, 传给 ChatPane 作 viewContext
const wsId = computed(() =>
  currentBinding.value.kind === 'workspace' ? currentBinding.value.workspaceId : null)

// app 绑定时的 appId, 传给 ChatPane
const appId = computed(() =>
  currentBinding.value.kind === 'app' ? currentBinding.value.appId : null)

const wsSessions = computed<WorkspaceSession[]>(() =>
  // wsSessions binding 暂仍 {kind:'none'}; 会话列表 binding 持久化非本期
  sessions.value.map(s => ({ id: s.id, title: s.title, binding: { kind: 'none' },
    updated_at: s.updated_at, created_at: s.created_at })))
const sessionItems = computed(() => toSessionItems(wsSessions.value, Date.now()))
const activeSidebarId = computed(() => (currentSessionId.value ? `chat:${currentSessionId.value}` : null))

function onOpenPanel(id: string) { activePanelId.value = id }
function onOpenArtifact(a: any) { openArtifact.value = a; activePanelId.value = 'artifacts' }
function onSelect(prefixedId: string | number) {
  const { kind, sessionId, workspaceId } = parseSidebarSelect(String(prefixedId))
  if (kind === 'workspace' && workspaceId) {
    router.push('/workspace/' + encodeURIComponent(workspaceId))
  } else if (kind === 'app' && sessionId !== null) {
    router.push({ path: '/workspace', query: { app_id: String(sessionId) } })
  } else {
    // none / chat: 保留原行为, sessionId 已确保是 number 不被 Number 化 workspace id
    currentSessionId.value = sessionId
  }
}
function onSessionChanged(id: number) { currentSessionId.value = id; loadSessions() }
// 对话里 agent 在某 workspace 干活 → 自动升级绑定(代码面板点亮)。不覆盖显式 app 绑定;
// 同 workspace 不动。重载后靠 ChatPane 重新检测自愈(无需改 URL)。
function onWorkspaceDetected(ws: string) {
  if (currentBinding.value.kind === 'app') return
  if (currentBinding.value.kind === 'workspace' && currentBinding.value.workspaceId === ws) return
  currentBinding.value = { kind: 'workspace', workspaceId: ws }
}
function onCreate() { currentSessionId.value = null }   // ChatPane 首条消息触发 ensureSession
onMounted(loadSessions)
</script>

<style scoped>
/* 五区布局: [会话栏 | 主区(顶部工具菜单 + 主体(对话 | 面板))] */
.workspace-shell {
  display: flex;
  height: 100vh;
  overflow: hidden;
  background: var(--surface);
}
.ws-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  height: 100%;
}
.ws-top {
  flex-shrink: 0;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding: 0 12px;
  border-bottom: 1px solid var(--line);
  background: var(--surface);
}
.ws-body {
  flex: 1;
  min-height: 0;
  display: flex;
}
/* 对话占主，撑满高度(ChatPane 自身 height:100%) */
.ws-chat {
  flex: 1;
  min-width: 0;
}
/* 对话↔面板 拖拽分隔条 */
.ws-resizer {
  flex-shrink: 0;
  width: 6px;
  cursor: col-resize;
  background: transparent;
  transition: background 0.15s;
}
.ws-resizer:hover,
.ws-resizer:active {
  background: var(--brand-soft, rgba(99, 102, 241, 0.3));
}
/* 工具面板停靠右侧,仅打开时存在。宽度由 usePanelResize 经 :style 控制(px, 可拖+持久化)。 */
.ws-panel {
  flex-shrink: 0;
  border-left: 1px solid var(--line);
  overflow: auto;
  background: var(--surface);
}
</style>
