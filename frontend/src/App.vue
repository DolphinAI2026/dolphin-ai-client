<script setup lang="ts">
import { computed, watch } from 'vue'
import { RouterView, useRoute } from 'vue-router'
import HelpAssistant from '@/components/HelpAssistant.vue'
import { useUserStore } from '@/stores/user'
import { useTabsStore } from '@/stores/tabs'

const route = useRoute()
const userStore = useUserStore()
const tabsStore = useTabsStore()

// 同步当前路由到 tab activeId（用户按浏览器后退/前进 / 手动改 URL 时）
watch(
  () => route.fullPath,
  (path) => tabsStore.syncFromRoute(path),
  { immediate: true },
)

// 助手浮窗在顶层挂一次（路由切换不重新挂）：登录前 / 嵌入模式 / iframe 内都不挂
function isInIframe(): boolean {
  if (typeof window === 'undefined') return false
  try { return window.self !== window.top } catch { return true }
}
const showAssistant = computed(() => {
  if (!userStore.token) return false
  if (route.path === '/login' || route.path === '/tenant-select') return false
  if (route.query.embed_nav === '0') return false
  if (route.query.embed === 'app_chat') return false
  if (isInIframe()) return false
  return true
})
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
  <HelpAssistant v-if="showAssistant" />
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
