<template>
  <!-- v3 2026-05-20 cleanup (code review #P2-6): 删 :style="theme.accentVars"
       theme.ts 已删 accentVars (无 picker = 无 user-chosen accent)
       brand 色阶完全由 design-v3-tokens.css 的 :root --brand-* 提供 -->
  <div
    class="workbench-shell"
    :class="{ 'workbench-coding-focus': codingFocus }"
    :data-theme="theme.mode"
  >
    <RailSidebar v-if="showNav" />
    <div class="workbench-main">
      <slot />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import RailSidebar from '@/components/v2/RailSidebar.vue'
import { useThemeStore } from '@/stores/theme'

const route = useRoute()
const theme = useThemeStore()
const showNav = computed(() => route.query.embed_nav !== '0')
const codingFocus = computed(() =>
  route.path.endsWith('/coding') && !!route.query.workspace_id && showNav.value
)
</script>

<style scoped>
.workbench-shell {
  height: 100vh;
  width: 100%;
  display: flex;
  background: var(--bg-app);
  color: var(--text);
  overflow: hidden;
}

.workbench-main {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.workbench-coding-focus :deep(.rail:not(.rail-collapsed)) {
  width: 184px;
}

.workbench-coding-focus :deep(.rail-brand) {
  min-height: 54px;
  padding: 12px 12px 10px;
  gap: 8px;
}

.workbench-coding-focus :deep(.rail-title) {
  font-size: 15px;
}

.workbench-coding-focus :deep(.rail-title-sub) {
  font-size: 11px;
}

.workbench-coding-focus :deep(.rail-scroll) {
  padding: 6px 8px 8px;
}

.workbench-coding-focus :deep(.rail-item) {
  min-height: 34px;
  gap: 8px;
  padding: 0 8px;
}

.workbench-coding-focus :deep(.rail-foot) {
  padding: 8px 8px 10px;
}

.workbench-coding-focus :deep(.rail-console) {
  gap: 5px;
}

.workbench-coding-focus :deep(.tenant-switch),
.workbench-coding-focus :deep(.console-row),
.workbench-coding-focus :deep(.theme-row) {
  padding-inline: 8px;
}

.workbench-coding-focus :deep(.rail-title),
.workbench-coding-focus :deep(.rail-title-sub),
.workbench-coding-focus :deep(.rail-item-label),
.workbench-coding-focus :deep(.tenant-name),
.workbench-coding-focus :deep(.theme-row-label),
.workbench-coding-focus :deep(.rail-user-name),
.workbench-coding-focus :deep(.rail-user-status) {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

@media (max-width: 1280px) {
  .workbench-coding-focus :deep(.rail:not(.rail-collapsed)) {
    width: 176px;
  }
}
</style>
