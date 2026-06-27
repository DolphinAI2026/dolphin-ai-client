<template>
  <!-- 已在 WorkbenchShell 内(如 CapabilitiesHubPage 内嵌)→ 不再套第二层壳, 只渲染内容, 避免双左栏 -->
  <WorkbenchShell v-if="!nested">
    <section class="builder-view">
      <div v-if="$slots.actions" class="builder-page-actions">
        <slot name="actions" />
      </div>
      <slot />
    </section>
  </WorkbenchShell>
  <section v-else class="builder-view">
    <div v-if="$slots.actions" class="builder-page-actions">
      <slot name="actions" />
    </div>
    <slot />
  </section>
</template>

<script setup lang="ts">
import { inject } from 'vue'
import WorkbenchShell from '@/components/WorkbenchShell.vue'

defineProps<{
  breadcrumbs: Array<{ label: string; to?: string }>
}>()

// 外层若已是 WorkbenchShell(provide inWorkbenchShell)则本 BuilderFrame 不再套壳
const nested = inject<boolean>('inWorkbenchShell', false)
</script>

<style scoped>
/* 让 builder-view 自身 flex column 撑满 workbench-main，slot 内的页面 main flex:1 自然占满剩余
   高度——避免子页面用 calc(100vh - Npx) 这种脆弱算法时算错留白 */
.builder-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.builder-page-actions {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  padding: 8px 16px 0;
  background: transparent;
}
</style>
