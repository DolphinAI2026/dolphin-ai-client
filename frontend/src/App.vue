<script setup lang="ts">
import { onMounted } from 'vue'
import { RouterView, type RouteLocationNormalized } from 'vue-router'
import { checkAndPromptUpdate } from '@/utils/desktop'

onMounted(() => {
  // 仅桌面端;启动静默检查,有新版才弹窗(在线版 checkAndPromptUpdate 是 no-op)。
  void checkAndPromptUpdate({ silentIfNone: true })
})

/**
 * KeepAlive 只保留 /ai-chat 系列一个 singleton 实例，其余路由一律不缓存。
 *
 * 2026-06-08 删多 Tab 体系：原本 <KeepAlive :max="10"> 按 fullPath 缓存最多 10
 * 个路由实例（每个应用 /chat?app_id=N 一个），切回去时显示的是旧缓存实例 ——
 * 这正是"切换渲染"看到陈旧/错乱内容的根源。现在其余路由不缓存，每次进入都重新
 * mount + 重新拉数据 = 始终新鲜渲染。
 *
 * 唯一例外是 /ai-chat：它的 SSE 流式生成依赖实例不被 remount。
 *   - Landing.submit() 推 /ai-chat?prompt=X → AIChatPage mount → onMounted 创
 *     session → router.replace('/ai-chat/N') → fullPath 变。若此时 remount，
 *     老 instance 里 in-flight 的 onSend() / SSE listener 全报废 → UI 永远不显示
 *     agent 工作状态（见 2026-05-21 修复）。
 *   - 修法：/（首页）、/ai-chat 与 /ai-chat/:id 走同一个 KeepAlive，key 恒为
 *     singleton，fullPath 变也不 remount；session 切换由组件内部 watch
 *     route.params.id → loadSession(id) 处理。
 *   - 离开这些路由去别的路由会销毁这个 KeepAlive（实例释放），再回来是新鲜
 *     mount —— 这是期望行为，不影响上面的 session 创建流。
 *
 * 2026-06-08 修回归：首页 '/' 与 '/ai-chat' 是**同一个 AIChatPage 组件**（router
 *   path '/' name Home → AIChatPage）。之前 isAiChatRoute 只认 /ai-chat*，漏了
 *   '/'，于是「应用资产库 → AI Builder 菜单(='/') → 发消息」时：onDraftSend 建会话
 *   后 router.replace('/ai-chat/N') 把路由从 '/'(v-else 分支) 跨到 '/ai-chat/N'
 *   (KeepAlive 分支) → 组件**整个 remount**，in-flight 的 onSend()/SSE 全报废 →
 *   currentSession 变 null、助手回复+工具卡片不显示。把 '/' 一并纳入即修。
 */
// '/' 与 '/ai-chat' 同为 AIChatPage, 走同一 SSE 保活单例(见下方长注释)。
function isAiChatRoute(r: RouteLocationNormalized): boolean {
  return r.path === '/' || r.path === '/ai-chat' || r.path.startsWith('/ai-chat/')
}

function isWorkspaceRoute(r: RouteLocationNormalized): boolean {
  return r.path === '/workspace' || r.path.startsWith('/workspace/')
}

// /coding 用稳定 key 复用实例: 换会话/工作区只变 query, 不再整页 remount(根除「切会话闪一下」)。
// 会话切换由 CodingPage 监听 route.query 原地处理(类比 ai-chat 的 route.params.id watch)。
// 离开 /coding 仍正常卸载(不进 KeepAlive), 保持原有 SSE 生命周期。
function isCodingRoute(r: RouteLocationNormalized): boolean {
  return r.path === '/coding'
}
</script>

<template>
  <!-- 2026-06-08 删多 Tab 后：只有 /ai-chat 系列走 KeepAlive（singleton key 防
       SSE listener 被 remount 干掉，见 isAiChatRoute 注释）；其余路由直接渲染、
       每次进入都重新 mount —— 根除多实例缓存导致的"切换渲染"陈旧内容。-->
  <RouterView v-slot="{ Component }">
    <KeepAlive v-if="isAiChatRoute($route)">
      <component :is="Component" key="ai-chat-singleton" />
    </KeepAlive>
    <KeepAlive v-else-if="isWorkspaceRoute($route)">
      <component :is="Component" key="workspace-singleton" />
    </KeepAlive>
    <!-- /coding: 稳定 key, query 变化(换会话/工作区)复用实例不 remount → 不闪 -->
    <component v-else-if="isCodingRoute($route)" :is="Component" key="coding-stable" />
    <component v-else :is="Component" :key="$route.fullPath" />
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
  /* v3: use --font-sans token (self-host Geist Sans + 系统 CJK), with system fallback */
  font-family: var(--font-sans, -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Segoe UI', 'Microsoft YaHei', sans-serif);
}
</style>
