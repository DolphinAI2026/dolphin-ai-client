<!-- frontend/src/components/v2/ConfigAssistantPanel.vue
     Right-column panel for post-deploy `/chat?app_id=X` — users chat in
     natural language to adjust an already-deployed application.

     2026-05-24 (refactor #9): 1207 行单文件 → 5 子组件 + 4 composables 拆分:
     - ConfigAssistantHeader.vue       (标题 + 副标题 + 模型选择 dropdown — Agent B)
     - ConfigAssistantViewport.vue     (MJPEG mini preview)
     - ConfigAssistantMessages.vue     (主消息区 + plan card + hero CTA + change_plan info)
     - ConfigAssistantInput.vue        (输入框 + send btn)
     - ConfigAssistantSessionDrawer.vue (会话历史抽屉 — Agent A, 主容器集成于本文件)
     - composables/useConfigChat.ts    (messages / send / SSE 消费 / extractPlan / sessionId)
     - composables/useDynamicExamples.ts (例子 chip 按真实 SPEC 动态生成)
     - composables/useViewportStream.ts  (MJPEG 流 URL)
     - composables/usePanelResize.ts     (PointerEvent + setPointerCapture 拖宽)

     2026-05-24 (Agent A + B 集成):
     - sessionId 持久化 (useConfigChat 内, sticky from 'started' SSE event)
     - 新对话 / 历史抽屉 (SessionDrawer + drawerOpen state)
     - modelId v-model (Header dropdown, localStorage 持久化 key apaas-config-assistant-model-v1)

     props / emit / localStorage key 兼容老版本, ChatPage.vue 不动. -->
<script setup lang="ts">
import { computed, onMounted, onUpdated, ref, toRef, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import ConfigAssistantHeader from './config-assistant/ConfigAssistantHeader.vue'
import ConfigAssistantViewport from './config-assistant/ConfigAssistantViewport.vue'
import ConfigAssistantMessages from './config-assistant/ConfigAssistantMessages.vue'
import ConfigAssistantInput from './config-assistant/ConfigAssistantInput.vue'
import ConfigAssistantSessionDrawer from './config-assistant/ConfigAssistantSessionDrawer.vue'

import { useConfigChat } from './config-assistant/composables/useConfigChat'
import { useDynamicExamples } from './config-assistant/composables/useDynamicExamples'
import { useViewportStream } from './config-assistant/composables/useViewportStream'
import { usePanelResize } from './config-assistant/composables/usePanelResize'

import { configChatApi } from '@/api/configChat'

const props = defineProps<{
  applicationId: number
  appName?: string
}>()

const emit = defineEmits<{
  /** 2026-05-21 Phase 2: 完成态 hero CTA 触发父组件刷新 iframe */
  (e: 'refresh-iframe'): void
}>()

// 拖宽 — 学 super-agents-dev PointerEvent + setPointerCapture, 比老 mousedown 稳
const { panelWidth, isResizing, onResizeStart } = usePanelResize({
  storageKey: 'apaas-config-assistant-width-v1',
  defaultWidth: 420,
  minWidth: 320,
  maxWidth: 880,
})

// MJPEG viewport
const appIdRef = toRef(props, 'applicationId')
const { viewportEnabled, viewportStreamUrl, openViewportFull } = useViewportStream(appIdRef)

// 动态例子 chip (按当前应用真实 SPEC 生成)
const { examples } = useDynamicExamples(appIdRef)

// 2026-05-24 Agent B 集成: modelId 持久化, 跟 Header v-model 绑
const MODEL_KEY = 'apaas-config-assistant-model-v1'
const modelId = ref<number | null>((() => {
  const v = localStorage.getItem(MODEL_KEY)
  if (!v || v === 'null' || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) && n > 0 ? n : null
})())
watch(modelId, (v) => {
  try {
    localStorage.setItem(MODEL_KEY, v == null ? '' : String(v))
  } catch {
    /* private mode */
  }
})

// Chat 核心逻辑 — scrollerRef 在 onMounted 后 querySelector 注入
const scrollerRef = ref<HTMLElement | null>(null)
const {
  messages,
  input,
  sending,
  send,
  pickExample,
  // Agent A 新增 exports
  sessionId,
  clearMessages,
  loadHistory,
} = useConfigChat({
  applicationId: appIdRef,
  scrollerRef,
  modelId, // Agent B
})

// 2026-05-24 Agent A 集成: 历史会话抽屉
const drawerOpen = ref(false)
const drawerRef = ref<InstanceType<typeof ConfigAssistantSessionDrawer> | null>(null)

async function onDelete(sid: number) {
  try {
    await ElMessageBox.confirm('确定删除这条会话?', '删除会话', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await configChatApi.deleteSession(sid)
    if (sid === sessionId.value) clearMessages()
    drawerRef.value?.reload()
    ElMessage.success('已删除')
  } catch (e: any) {
    ElMessage.error(e?.message || '删除失败')
  }
}

async function onRename(sid: number, title: string) {
  try {
    await configChatApi.updateSessionTitle(sid, title)
    drawerRef.value?.reload()
  } catch (e: any) {
    ElMessage.error(e?.message || '改标题失败')
  }
}

async function onSelectSession(sid: number) {
  drawerOpen.value = false
  try {
    await loadHistory(sid)
  } catch (e: any) {
    ElMessage.error(e?.message || '加载历史失败')
  }
}

function onNewSession() {
  drawerOpen.value = false
  clearMessages()
}

const emptyHint = computed(
  () => `配置「${props.appName ?? '应用'}」— 描述你想调整的字段、流程、权限...`,
)

onMounted(() => {
  const el = document.querySelector('.config-assistant .ca-scroll') as HTMLElement | null
  if (el) scrollerRef.value = el
})

// 兜底: 每次 updated 也强同步一次 ref (防 Messages remount 时 ref 丢)
onUpdated(() => {
  if (!scrollerRef.value) {
    const el = document.querySelector('.config-assistant .ca-scroll') as HTMLElement | null
    if (el) scrollerRef.value = el
  }
})
</script>

<template>
  <aside
    class="config-assistant"
    data-design="v2"
    :class="{ 'is-resizing': isResizing }"
    :style="{ width: panelWidth + 'px' }"
  >
    <!-- 左边缘拖拽 handle -->
    <div class="ca-resize-handle" @pointerdown="onResizeStart" title="拖拽调整宽度" />

    <!-- 顶部 actions: 新对话 / 历史 (固定在 panel 顶部右上角) -->
    <div class="ca-top-actions">
      <button
        class="ca-top-btn"
        title="新对话"
        @click="onNewSession"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 5v14M5 12h14" />
        </svg>
      </button>
      <button
        class="ca-top-btn"
        title="历史对话"
        @click="drawerOpen = true"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M3 7h18M3 12h18M3 17h18" />
        </svg>
      </button>
    </div>

    <ConfigAssistantHeader :app-name="appName" v-model:model-id="modelId" />

    <ConfigAssistantViewport
      :enabled="viewportEnabled"
      :stream-url="viewportStreamUrl"
      @toggle="viewportEnabled = $event"
      @open-full="openViewportFull"
    />

    <ConfigAssistantMessages
      :messages="messages"
      :examples="examples"
      :sending="sending"
      :empty-hint="emptyHint"
      @pick-example="pickExample"
      @refresh-iframe="emit('refresh-iframe')"
    />

    <ConfigAssistantInput
      v-model="input"
      :sending="sending"
      @send="send"
    />

    <!-- 会话历史抽屉 (Agent A 新组件, 主容器集成) -->
    <ConfigAssistantSessionDrawer
      ref="drawerRef"
      v-model:open="drawerOpen"
      :application-id="applicationId"
      :current-session-id="sessionId"
      @select="onSelectSession"
      @new="onNewSession"
      @delete="onDelete"
      @rename="onRename"
    />
  </aside>
</template>

<style scoped>
.config-assistant {
  position: relative;
  display: flex;
  flex-direction: column;
  height: 100%;
  border-left: 1px solid var(--line);
  background: var(--surface);
  flex-shrink: 0;
  overflow: hidden;
}

.config-assistant.is-resizing {
  cursor: ew-resize;
  user-select: none;
}

/* ─── 拖拽 handle (左边缘 5px) ───────────────────────────── */
.ca-resize-handle {
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

.ca-resize-handle:hover,
.config-assistant.is-resizing .ca-resize-handle {
  background: var(--brand-ring, var(--brand));
  opacity: 0.4;
}

/* ─── 顶部 actions (新对话 / 历史) ────────────────────────── */
.ca-top-actions {
  position: absolute;
  top: 8px;
  right: 10px;
  display: flex;
  gap: 4px;
  z-index: 5;
}

.ca-top-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  border: 1px solid var(--line);
  border-radius: var(--r-2, 4px);
  background: var(--surface);
  color: var(--text-3);
  cursor: pointer;
  transition: all 0.12s ease;
}

.ca-top-btn:hover {
  border-color: var(--brand);
  color: var(--brand);
}
</style>
