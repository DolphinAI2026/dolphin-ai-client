<script setup lang="ts">
import { watch } from 'vue'
import { RouterView, useRoute } from 'vue-router'
import { useTabsStore } from '@/stores/tabs'

// 2026-05-21 dolphin agent 浮窗 (HelpAssistant) 暂时下线 — 用户决策：
// 现 /ai-chat 内置 gpt-5.5 加 MCP 工具能力后，浮窗 dolphin agent 变冗余。
// 后端 dolphin_sso 路由 + HelpAssistant.vue + DolphinAgentEmbed 文件全保留可逆。

const route = useRoute()
const tabsStore = useTabsStore()

watch(
  () => route.fullPath,
  (path) => tabsStore.syncFromRoute(path),
  { immediate: true },
)
</script>

<template>
  <!-- KeepAlive 包 RouterView — tab 切换时缓存路由组件 instance，避免重 mount + 重加载。
       :max="10" 限制最多缓存 10 个 vnode（LRU），防内存爆。
       :key 用 route.fullPath 让相同 component 不同 app_id 各自缓存
       (例：/chat?app_id=4 vs /chat?app_id=5 是 2 个独立缓存 entry)。-->
  <RouterView v-slot="{ Component }">
    <KeepAlive :max="10">
      <component :is="Component" :key="$route.fullPath" />
    </KeepAlive>
  </RouterView>
</template>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html, body, #app {
  height: 100%;
  /* v3: use --font-sans token (Inter + Noto Sans SC), with system fallback */
  font-family: var(--font-sans, 'Inter', 'Noto Sans SC', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif);
}
</style>
