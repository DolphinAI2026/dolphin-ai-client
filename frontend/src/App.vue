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
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
}
</style>
