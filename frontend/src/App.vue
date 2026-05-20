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
  <!-- v3 2026-05-20: 加 <Suspense> 包 async route component，配 <SkeletonCard> 兑底
       修 UED 报告 P0 — 之前组件市场 / DB 问数等懒加载路由黑屏 8s+ 问题。
       Suspense 内 <component> 默认显 fallback，组件加载完才切。 -->
  <RouterView v-slot="{ Component }">
    <transition name="page" mode="out-in">
      <Suspense :timeout="0">
        <template #default>
          <component :is="Component" />
        </template>
        <template #fallback>
          <div class="route-loading-fallback" role="status" aria-live="polite">
            <div class="route-loading-skeleton">
              <div class="rls-bar" style="width: 30%; height: 22px"></div>
              <div class="rls-bar" style="width: 60%; height: 14px; margin-top: 14px"></div>
              <div class="rls-grid">
                <div class="rls-card" v-for="i in 6" :key="i">
                  <div class="rls-bar" style="width: 38px; height: 38px; border-radius: 8px"></div>
                  <div class="rls-bar" style="width: 70%; height: 14px; margin-top: 14px"></div>
                  <div class="rls-bar" style="width: 90%; height: 10px; margin-top: 8px"></div>
                </div>
              </div>
            </div>
          </div>
        </template>
      </Suspense>
    </transition>
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

/* v3 Suspense fallback — skeleton 替代黑屏 8s+ 问题（UED 报告 P0）
   200ms 延迟显（防闪屏）+ 水平 shimmer 动画 */
.route-loading-fallback {
  width: 100%;
  height: 100vh;
  padding: 32px;
  background: var(--bg-app, linear-gradient(180deg, #F8FAFC 0%, #F1F5F9 100%));
  animation: route-loading-fade-in 0.18s ease 0.2s both;
}
.route-loading-skeleton {
  max-width: 1200px;
  margin: 0 auto;
}
.rls-bar {
  background: linear-gradient(90deg,
    var(--surface-2, #F8FAFC) 0%,
    var(--surface-3, #F1F5F9) 50%,
    var(--surface-2, #F8FAFC) 100%);
  background-size: 200% 100%;
  animation: rls-shimmer 1.4s ease-in-out infinite;
  border-radius: 4px;
}
.rls-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
  margin-top: 32px;
}
.rls-card {
  background: var(--surface, #FFFFFF);
  border: 1px solid var(--line, rgba(11, 27, 63, 0.08));
  border-radius: 12px;
  padding: 16px;
}
@keyframes route-loading-fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}
@keyframes rls-shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
</style>
