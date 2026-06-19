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
          <ChatPane :session-id="currentSessionId"
            @open-artifact="onOpenArtifact" @session-changed="onSessionChanged" />
        </div>
        <div v-if="activePanelId" class="ws-panel">
          <PanelHost :active-panel-id="activePanelId"
            :binding="currentBinding" :session-id="currentSessionId" :artifact="openArtifact"
            @close="activePanelId = null" />
        </div>
      </div>
    </main>
  </div>
</template>
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import SessionSidebar from '@/components/common/SessionSidebar.vue'
import ToolMenu from './ToolMenu.vue'
import PanelHost from './PanelHost.vue'
import ChatPane from './ChatPane.vue'
import { registerPhase1Panels } from './panels'
import { toSessionItems, type WorkspaceSession } from './sessionList'
import { rawId } from './binding'
import type { Binding } from './binding'
import { useAiChatSession } from '@/composables/useAiChatSession'

registerPhase1Panels()
const { sessions, loadSessions } = useAiChatSession({ appId: ref(null) })

const currentSessionId = ref<number | null>(null)
const activePanelId = ref<string | null>(null)
const openArtifact = ref<any>(null)
const asideCollapsed = ref(false)
// Phase 1 仅通用对话; Phase 2/3 由会话真实 binding 驱动
const currentBinding = ref<Binding>({ kind: 'none' })

const wsSessions = computed<WorkspaceSession[]>(() =>
  sessions.value.map(s => ({ id: s.id, title: s.title, binding: { kind: 'none' },
    updated_at: s.updated_at, created_at: s.created_at })))
const sessionItems = computed(() => toSessionItems(wsSessions.value, Date.now()))
const activeSidebarId = computed(() => (currentSessionId.value ? `chat:${currentSessionId.value}` : null))

function onOpenPanel(id: string) { activePanelId.value = id }
function onOpenArtifact(a: any) { openArtifact.value = a; activePanelId.value = 'artifacts' }
function onSelect(id: string | number) { currentSessionId.value = Number(rawId(String(id))) }
function onSessionChanged(id: number) { currentSessionId.value = id; loadSessions() }
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
/* 工具面板停靠右侧,仅打开时存在 */
.ws-panel {
  flex-shrink: 0;
  width: 40%;
  min-width: 320px;
  max-width: 560px;
  border-left: 1px solid var(--line);
  overflow: auto;
  background: var(--surface);
}
</style>
