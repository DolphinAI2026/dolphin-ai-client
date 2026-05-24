<!-- frontend/src/components/v2/config-assistant/ConfigAssistantHeader.vue
     2026-05-24 从 ConfigAssistantPanel.vue 拆出 (refactor #9).
     最薄一层 — 标题 + 副标题. 跟 super-agents-dev assistant-header.vue 一致命名. -->
<script setup lang="ts">
defineProps<{ appName?: string }>()
</script>

<template>
  <header class="ca-head">
    <div class="ca-title">配置助手</div>
    <div class="ca-sub">
      {{ appName ? `调整「${appName}」` : '调整已部署应用' }}
    </div>
  </header>
</template>

<style scoped>
.ca-head {
  padding: 14px 16px 10px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-2);
}

.ca-title {
  font-size: 13px;
  font-weight: var(--fw-semibold, 600);
  color: var(--text);
}

.ca-sub {
  margin-top: 3px;
  font-size: 11.5px;
  color: var(--text-3);
}
</style>
