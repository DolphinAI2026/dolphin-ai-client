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
  <!-- v3 2026-05-20: 简单 RouterView，无 <Transition>/<Suspense> 包裹。
       commit 5f1f1e2 revert 了之前的 wrap 写法（route fragment-template 不可动画）。
       未来想加 page transition 必须先：
         1. ChatPage/CodingPage 等模板第一个子节点是 HTML 注释 → 改成 single root
         2. 不要套 <Suspense> 在 <Transition> 内（多 slot 不能动画） -->
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
