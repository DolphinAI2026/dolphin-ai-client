<template>
  <BuilderFrame :breadcrumbs="[{ label: 'AI Coding' }]">
    <template #actions>
      <span v-if="appId" class="aicoding-app-chip">应用 #{{ appId }}</span>
    </template>

    <div v-if="!appId" class="aicoding-empty">
      请带应用进入：<code>/ai-coding/&lt;appId&gt;</code>
    </div>
    <div v-else class="aicoding-shell">
      <!-- 左：对话栏（Task 7 接 SpecChatPanel） -->
      <section class="aicoding-chat" :style="{ flexBasis: chatWidth + 'px' }">
        <div class="aicoding-chat-placeholder">左对话（Task 7 接 SpecChatPanel）</div>
        <div class="aicoding-resizer" @mousedown="startResize"></div>
      </section>

      <!-- 右：6 Tab 工作区 -->
      <section class="aicoding-work">
        <WorkspaceTabs :app-id="appId" />
      </section>
    </div>
  </BuilderFrame>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import BuilderFrame from '@/components/BuilderFrame.vue'
import WorkspaceTabs from '@/components/ai-coding/WorkspaceTabs.vue'

const route = useRoute()

const appId = computed<number | null>(() => {
  const raw = route.params.appId
  const n = Number(Array.isArray(raw) ? raw[0] : raw)
  return Number.isFinite(n) && n > 0 ? n : null
})

const chatWidth = ref(420)

function startResize(e: MouseEvent) {
  const startX = e.clientX
  const startW = chatWidth.value
  const onMove = (ev: MouseEvent) => {
    chatWidth.value = Math.max(320, Math.min(720, startW + ev.clientX - startX))
  }
  const onUp = () => {
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
  }
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}
</script>

<style scoped>
.aicoding-shell {
  display: flex;
  height: 100%;
  min-height: 0;
  flex: 1 1 auto;
  overflow: hidden;
}

.aicoding-chat {
  position: relative;
  flex: 0 0 auto;
  border-right: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
}

.aicoding-chat-placeholder {
  padding: 24px;
  color: var(--text-3);
  font-size: 13px;
}

.aicoding-resizer {
  position: absolute;
  top: 0;
  right: -3px;
  width: 6px;
  height: 100%;
  cursor: col-resize;
  z-index: 10;
}

.aicoding-resizer:hover {
  background: var(--brand-soft-2);
}

.aicoding-work {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.aicoding-empty {
  padding: 40px;
  color: var(--text-3);
  font-size: 14px;
}

.aicoding-app-chip {
  font-size: 12px;
  color: var(--text-3);
  padding: 2px 8px;
  background: var(--surface-3);
  border-radius: 12px;
}
</style>
