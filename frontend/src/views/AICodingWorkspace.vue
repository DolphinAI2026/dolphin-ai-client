<template>
  <BuilderFrame :breadcrumbs="[{ label: 'AI Coding' }, { label: wsId || '—' }]">
    <div v-if="!wsId" class="aic-empty">缺少工作区 ID（请从应用列表进入或新建 AI 应用）</div>
    <div v-else class="aic-shell">
      <section class="aic-chat" :style="{ flexBasis: chatWidth + 'px' }">
        <VibeChatPanel ref="chatRef" :workspace-id="wsId" />
        <div class="aic-resizer" @mousedown="startResize"></div>
      </section>
      <section class="aic-work">
        <WorkspaceTabs :workspace-id="wsId" />
      </section>
    </div>
  </BuilderFrame>
</template>

<script setup lang="ts">
import { ref, computed, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import BuilderFrame from '@/components/BuilderFrame.vue'
import VibeChatPanel from '@/components/vibe-coding/VibeChatPanel.vue'
import WorkspaceTabs from '@/components/ai-coding/WorkspaceTabs.vue'

const route = useRoute()
const wsId = computed<string>(() => String(route.params.wsId || ''))
const chatRef = ref<any>(null)

const chatWidth = ref(440)
let cleanupResize: (() => void) | null = null
function startResize(e: MouseEvent) {
  e.preventDefault()
  document.body.style.userSelect = 'none'
  document.body.style.cursor = 'ew-resize'
  const startX = e.clientX
  const startW = chatWidth.value
  const onMove = (ev: MouseEvent) => {
    chatWidth.value = Math.max(340, Math.min(720, startW + ev.clientX - startX))
  }
  const onUp = () => {
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
    document.body.style.userSelect = ''
    document.body.style.cursor = ''
    cleanupResize = null
  }
  cleanupResize = onUp
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}
onUnmounted(() => cleanupResize?.())
</script>

<style scoped>
.aic-shell { display: flex; height: 100%; min-height: 0; flex: 1 1 auto; overflow: hidden; }
.aic-chat { position: relative; flex: 0 0 auto; border-right: 1px solid var(--line); display: flex; flex-direction: column; min-width: 0; overflow: hidden; }
.aic-resizer { position: absolute; top: 0; right: -3px; width: 6px; height: 100%; cursor: col-resize; z-index: 10; }
.aic-resizer:hover { background: var(--brand-soft); }
.aic-work { flex: 1 1 auto; min-width: 0; overflow: hidden; display: flex; flex-direction: column; }
.aic-empty { padding: 40px; color: var(--text-3); font-size: 14px; }
</style>
