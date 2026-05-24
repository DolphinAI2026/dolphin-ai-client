<!-- frontend/src/components/v2/ConfigAssistantPanel.vue
     Right-column panel for post-deploy `/chat?app_id=X` — users chat in
     natural language to adjust an already-deployed application.

     2026-05-24 (refactor #9): 1207 行单文件 → 5 子组件 + 4 composables 拆分:
     - ConfigAssistantHeader.vue       (标题 + 副标题)
     - ConfigAssistantViewport.vue     (MJPEG mini preview)
     - ConfigAssistantMessages.vue     (主消息区 + plan card + hero CTA + change_plan info)
     - ConfigAssistantInput.vue        (输入框 + send btn)
     - composables/useConfigChat.ts    (messages / send / SSE 消费 / extractPlan)
     - composables/useDynamicExamples.ts (例子 chip 按真实 SPEC 动态生成)
     - composables/useViewportStream.ts  (MJPEG 流 URL)
     - composables/usePanelResize.ts     (PointerEvent + setPointerCapture 拖宽,
                                          学 super-agents-dev 模式 — 更稳, 兼容触屏)

     props / emit / localStorage key 兼容老版本, ChatPage.vue 不动. -->
<script setup lang="ts">
import { computed, onMounted, onUpdated, ref, toRef } from 'vue'

import ConfigAssistantHeader from './config-assistant/ConfigAssistantHeader.vue'
import ConfigAssistantViewport from './config-assistant/ConfigAssistantViewport.vue'
import ConfigAssistantMessages from './config-assistant/ConfigAssistantMessages.vue'
import ConfigAssistantInput from './config-assistant/ConfigAssistantInput.vue'

import { useConfigChat } from './config-assistant/composables/useConfigChat'
import { useDynamicExamples } from './config-assistant/composables/useDynamicExamples'
import { useViewportStream } from './config-assistant/composables/useViewportStream'
import { usePanelResize } from './config-assistant/composables/usePanelResize'

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

// Chat 核心逻辑 — scrollerRef 在 onMounted 后 querySelector 注入 (子组件 root ref
// 拿不到内部 .ca-scroll DOM, 用 querySelector 简单可靠)
const scrollerRef = ref<HTMLElement | null>(null)
const { messages, input, sending, send, pickExample } = useConfigChat({
  applicationId: appIdRef,
  scrollerRef,
})

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

    <ConfigAssistantHeader :app-name="appName" />

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
  /* touch-action: none 让触屏拖拽不滚 viewport (PointerEvent 配套) */
  touch-action: none;
}

.ca-resize-handle:hover,
.config-assistant.is-resizing .ca-resize-handle {
  background: var(--brand-ring, var(--brand));
  opacity: 0.4;
}
</style>
