<script setup lang="ts">
import { watch } from 'vue'
import { RouterView, useRoute, type RouteLocationNormalized } from 'vue-router'
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

/**
 * KeepAlive 实例 key 的派生规则。
 *
 * 2026-05-21 修 Landing → /ai-chat 跳转 UI 空白 bug：
 *   - 原本 :key="$route.fullPath" — 每次 fullPath 变都新 mount
 *   - Landing.submit() 推 /ai-chat?prompt=X → AIChatPage mount → onMounted
 *     创 session → router.replace('/ai-chat/N') → fullPath 变 → KeepAlive
 *     unmount 旧 instance + mount 新 instance → 老 instance 里 in-flight 的
 *     onSend() / SSE listener 全报废 → UI 永远不显示 agent 工作状态
 *   - 修法：把 /ai-chat 和 /ai-chat/:id 视为同一个 singleton cache entry，
 *     session 切换由组件内部 loadSession(id) 处理（不依赖 remount）
 *   - 副作用：直接改 URL 到 /ai-chat/X 不会触发组件 remount，
 *     需要 AIChatPage 自己 watch route.params.id 重新 loadSession
 *
 * 其他路由 (/chat?app_id=X 多个应用 / /coding / /vibe-coding)
 * 还是按 fullPath 区分 cache entry — 不同 app_id = 不同 instance 是合理的。
 */
function keepAliveKey(r: RouteLocationNormalized): string {
  if (r.path === '/ai-chat' || r.path.startsWith('/ai-chat/')) {
    return '/ai-chat-singleton'
  }
  return r.fullPath
}
</script>

<template>
  <!-- KeepAlive 包 RouterView — tab 切换时缓存路由组件 instance，避免重 mount + 重加载。
       :max="10" 限制最多缓存 10 个 vnode（LRU），防内存爆。
       :key 见 keepAliveKey()：默认 route.fullPath，但 /ai-chat 系列共用一个
       singleton 防 SSE listener 被 remount 干掉。-->
  <RouterView v-slot="{ Component }">
    <KeepAlive :max="10">
      <component :is="Component" :key="keepAliveKey($route)" />
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
