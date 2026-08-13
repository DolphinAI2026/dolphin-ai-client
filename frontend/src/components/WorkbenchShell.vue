<template>
  <!-- v3 2026-05-20 cleanup (code review #P2-6): 删 :style="theme.accentVars"
       theme.ts 已删 accentVars (无 picker = 无 user-chosen accent)
       brand 色阶完全由 design-v3-tokens.css 的 :root --brand-* 提供 -->
  <div
    class="workbench-shell"
    :data-theme="theme.mode"
  >
    <RailSidebar v-if="showNav" :collapsed="narrowViewport" />
    <div class="workbench-main">
      <slot />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, provide } from 'vue'
import { useRoute } from 'vue-router'
import RailSidebar from '@/components/v2/RailSidebar.vue'
import { useThemeStore } from '@/stores/theme'

const route = useRoute()
const theme = useThemeStore()
// `embed_nav=0` is only meaningful for the legacy CodingPage iframe.
// Never let that embedding flag hide the shared Code rail when navigating
// between the system assistant and normal Code application sessions.
const showNav = computed(() =>
  route.query.embed_nav !== '0' || !route.path.startsWith('/coding'),
)
const narrowViewport = typeof window !== 'undefined'
  && window.matchMedia('(max-width: 640px)').matches
// 标记「已在 WorkbenchShell 内」: 嵌套的 BuilderFrame 据此跳过再套一层壳(避免双左栏)。
// 用于 CapabilitiesHubPage 这种自己包 WorkbenchShell、内容里又渲染自带 BuilderFrame 的原生页的场景。
provide('inWorkbenchShell', true)
// 2026-06-21: 删「左栏随 workspace_id 变宽」逻辑 —— 换会话导航时中途路由没
// workspace_id 会让左栏 176↔224 闪一下(用户报「放大一下又缩小」)。对话优先后左栏恒定宽即可。
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

:deep(.rail.rail-collapsed) {
  width: 56px;
}
</style>
