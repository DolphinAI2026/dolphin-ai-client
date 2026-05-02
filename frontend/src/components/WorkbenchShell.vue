<template>
  <div class="workbench-shell">
    <BuilderNavRail v-if="showNav" />
    <div class="workbench-main">
      <slot />
    </div>
    <BuilderCommandPalette />
    <HelpAssistant v-if="showNav" />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import BuilderNavRail from '@/components/BuilderNavRail.vue'
import BuilderCommandPalette from '@/components/BuilderCommandPalette.vue'
import HelpAssistant from '@/components/HelpAssistant.vue'

const route = useRoute()
const showNav = computed(() => route.query.embed_nav !== '0')
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
