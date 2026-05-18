<template>
  <WorkbenchShell>
    <section class="builder-view">
      <!-- Forward both the page breadcrumbs and the #actions slot into the v2
           topbar so the 7 pages that already wrap themselves in BuilderFrame
           (Apps / TenantUsers / PlatformTenants / PlatformEnvs / McpToolsPage /
           OnlineCodingPage / OnlineCodingWorkspacePage) keep their action
           buttons / chips / workspace toolbars rendered in the topbar. -->
      <!-- NOTE: the legacy `#center` slot is intentionally NOT forwarded —
           grep confirms only TopBar-based pages (ChatPage / MarketplacePage)
           consume `#center`, never BuilderFrame, so there is nothing to wire. -->
      <ShellTopBar :breadcrumbs="breadcrumbs">
        <template #actions><slot name="actions" /></template>
      </ShellTopBar>
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
