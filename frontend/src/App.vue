<script setup lang="ts">
import { computed } from 'vue'
import { RouterView, useRoute } from 'vue-router'
import HelpAssistant from '@/components/HelpAssistant.vue'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const userStore = useUserStore()

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
  <!-- v3 2026-05-20: REVERT — 之前 <transition>+<Suspense> 包 RouterView
       导致 ChatPage/CodingPage 等 multi-root template (comment + div fragment)
       的页面 render fail，/marketplace 整页空白。

       Vue <Transition> 只能动画 single-root element，fragment 会报：
       "Component inside <Transition> renders non-element root node that
       cannot be animated."

       移除 transition + Suspense 恢复原状。skeleton fallback CSS 在 style.css
       保留但不再触发（无害死代码，下次想加 skeleton 必须先确保所有 routed
       components 是 single-root template）。 -->
  <RouterView />
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
