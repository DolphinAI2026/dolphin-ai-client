<!-- frontend/src/components/v2/config-assistant/ConfigAssistantHeader.vue
     2026-05-24 #1 从 ConfigAssistantPanel.vue 拆出 (refactor #9).
     2026-05-31: 顶部收敛为标题 + 应用上下文；模型选择改走默认配置，
                  不再占据配置助手主流程。 -->
<script setup lang="ts">
defineProps<{
  appName?: string
}>()
</script>

<template>
  <header class="ca-head">
    <div class="ca-title-row">
      <div>
        <div class="ca-title">配置助手</div>
        <div class="ca-sub">
          {{ appName ? `调整「${appName}」` : '调整已部署应用' }}
        </div>
      </div>
    </div>

  </header>
</template>

<style scoped>
.ca-head {
  padding: 16px 132px 14px 14px;
  border-bottom: 1px solid var(--line);
  background: linear-gradient(135deg, var(--surface) 0%, var(--brand-soft, #eef4ff) 100%);
}

.ca-title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.ca-title {
  font-size: 18px;
  font-weight: var(--fw-bold, 700);
  color: var(--text);
}

.ca-sub {
  margin-top: 6px;
  font-size: 12.5px;
  color: var(--text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
