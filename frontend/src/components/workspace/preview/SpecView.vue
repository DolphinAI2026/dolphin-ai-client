<template>
  <div class="spec-view">
    <div v-if="!draftSpecId" class="empty">
      <p class="muted">尚无草稿，去 chat 开始 AI 编辑</p>
    </div>
    <div v-else class="spec-meta">
      <p>Spec: <code>{{ draftSpecId }}</code></p>
      <p class="muted small">v1 占位：完整 SPEC 编辑界面在 ChatPanel 老页面里。后续 task 抽出 SpecCanvas 嵌入此处。</p>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  draftSpecId: string | null
}>()
</script>

<style scoped>
.spec-view { padding: 16px; height: 100%; }
.empty { display: flex; align-items: center; justify-content: center; height: 100%; color: var(--fg-muted); }
.spec-meta code { background: var(--bg-inset); padding: 2px 6px; border-radius: 3px; font-family: var(--b-mono, monospace); }
.muted { color: var(--fg-muted); font-size: 12px; }
.small { font-size: 11px; }
</style>
