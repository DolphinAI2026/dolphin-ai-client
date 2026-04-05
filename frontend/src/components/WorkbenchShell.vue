<template>
  <div class="workbench-shell">
    <GlobalNavRail />
    <div class="workbench-main">
      <slot />
    </div>
  </div>
</template>

<script setup lang="ts">
import GlobalNavRail from '@/components/GlobalNavRail.vue'
</script>

<style scoped>
.workbench-shell {
  height: 100vh;
  display: flex;
  background: var(--t-bg-base);
  color: var(--t-text-primary);
}

.workbench-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
</style>
