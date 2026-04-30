<template>
  <WorkbenchShell>
    <section class="builder-view">
      <BuilderTopBar :breadcrumbs="breadcrumbs">
        <template v-if="$slots.center" #center>
          <slot name="center" />
        </template>
        <template v-if="$slots.actions" #actions>
          <slot name="actions" />
        </template>
      </BuilderTopBar>
      <slot />
    </section>
  </WorkbenchShell>
</template>

<script setup lang="ts">
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import BuilderTopBar from '@/components/BuilderTopBar.vue'

defineProps<{
  breadcrumbs: Array<{ label: string; to?: string }>
}>()
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
</style>
