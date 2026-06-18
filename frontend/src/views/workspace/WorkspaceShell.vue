<template>
  <div class="workspace-shell">
    <SessionSidebar
      module-name="工作区" brand-color="#f59e0b"
      :sessions="sessionItems" :active-id="activeSidebarId"
      collapse-key="workspace:aside-collapsed" new-label="+ 新会话"
      empty-hint="暂无会话,点上方新建"
      :enable-rename="false" :enable-delete="false"
      @select="onSelect" @create="onCreate"
      @collapse-change="(v) => (asideCollapsed = v)" />
    <main class="ws-main">
      <header class="ws-top">
        <ToolMenu :binding="currentBinding" @open="onOpenPanel" />
      </header>
      <div class="ws-body" :class="{ 'has-panel': activePanelId }">
        <ChatPane :session-id="currentSessionId"
          @open-artifact="onOpenArtifact" @session-changed="onSessionChanged" />
        <PanelHost v-if="activePanelId" :active-panel-id="activePanelId"
          :binding="currentBinding" :session-id="currentSessionId" :artifact="openArtifact"
          @close="activePanelId = null" />
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
