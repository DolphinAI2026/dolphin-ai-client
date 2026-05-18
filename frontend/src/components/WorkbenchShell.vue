<template>
  <div class="workbench-shell" data-design="v2" :data-theme="theme.mode">
    <RailSidebar v-if="showNav" />
    <div class="workbench-main">
      <slot />
    </div>
    <BuilderCommandPalette />
    <!-- HelpAssistant 已抬到 App.vue 顶层挂一次，避免随路由切换重复 init -->
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import RailSidebar from '@/components/v2/RailSidebar.vue'
import BuilderCommandPalette from '@/components/BuilderCommandPalette.vue'
import { useThemeStore } from '@/stores/theme'

const route = useRoute()
const theme = useThemeStore()
const showNav = computed(() => route.query.embed_nav !== '0')
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
</style>
