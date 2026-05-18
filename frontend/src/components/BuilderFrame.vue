<template>
  <WorkbenchShell>
    <section class="builder-view">
      <ShellTopBar />
      <!-- Legacy slots `center` / `actions` and the `breadcrumbs` prop are
           preserved on the API to avoid breaking the ~10 pages that wrap
           themselves in BuilderFrame, but ShellTopBar (v2) replaces the
           BuilderTopBar visual. Slots are no-ops in v2 chrome until Session 5+
           rebuilds the per-page action surfaces. -->
      <slot />
    </section>
  </WorkbenchShell>
</template>

<script setup lang="ts">
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import ShellTopBar from '@/components/v2/ShellTopBar.vue'

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
