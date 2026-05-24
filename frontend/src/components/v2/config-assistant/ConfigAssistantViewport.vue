<!-- frontend/src/components/v2/config-assistant/ConfigAssistantViewport.vue
     2026-05-21 Phase 3d Browser viewport mini preview MJPEG 流嵌入.
     2026-05-24 从 ConfigAssistantPanel.vue 拆出 (refactor #9). -->
<script setup lang="ts">
defineProps<{
  enabled: boolean
  streamUrl: string
}>()

const emit = defineEmits<{
  (e: 'toggle', value: boolean): void
  (e: 'open-full'): void
}>()
</script>

<template>
  <!-- MJPEG 流, <img> 浏览器原生解码自动播放. 扩展未连时显示 placeholder hint. -->
  <div class="ca-viewport" v-if="enabled">
    <div class="ca-viewport-head">
      <span class="ca-viewport-icon">🖥️</span>
      <span class="ca-viewport-label">AI 看到的画面 (2fps)</span>
      <button class="ca-viewport-toggle" @click="emit('toggle', false)" title="收起">×</button>
    </div>
    <img
      :src="streamUrl"
      class="ca-viewport-img"
      alt="agent browser viewport"
      @click="emit('open-full')"
    />
  </div>
  <button v-else class="ca-viewport-show-btn" @click="emit('toggle', true)">
    🖥️ 显示 AI 浏览器画面
  </button>
</template>

<style scoped>
.ca-viewport {
  padding: 8px 12px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-2);
}

.ca-viewport-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
  font-size: 11.5px;
  color: var(--text-3);
}

.ca-viewport-icon { font-size: 12px; }
.ca-viewport-label { flex: 1; letter-spacing: -0.005em; }
.ca-viewport-toggle {
  width: 16px;
  height: 16px;
  border: 0;
  background: transparent;
  color: var(--text-4);
  cursor: pointer;
  font-size: 14px;
  padding: 0;
}
.ca-viewport-toggle:hover { color: var(--text); }

.ca-viewport-img {
  display: block;
  width: 100%;
  height: auto;
  border-radius: var(--r-2, 4px);
  border: 1px solid var(--line);
  cursor: zoom-in;
}

.ca-viewport-show-btn {
  margin: 8px 12px 0;
  padding: 6px 10px;
  border: 1px dashed var(--line);
  border-radius: var(--r-2, 4px);
  background: transparent;
  color: var(--text-3);
  font-family: inherit;
  font-size: 11.5px;
  cursor: pointer;
  transition: all 0.12s ease;
  width: calc(100% - 24px);
}

.ca-viewport-show-btn:hover {
  border-color: var(--brand-ring, var(--brand));
  color: var(--brand);
}
</style>
