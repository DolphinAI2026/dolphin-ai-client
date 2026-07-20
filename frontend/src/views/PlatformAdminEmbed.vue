<template>
  <section class="platform-admin-embed">
    <iframe
      ref="frameRef"
      :key="iframeSrc"
      class="embed-frame"
      :src="iframeSrc"
      title="平台管理"
      @load="handleFrameLoad"
    />
    <div v-if="loading" class="embed-loading">正在加载平台管理...</div>
  </section>
</template>

<script setup lang="ts">
/*
 * v3 2026-05-20 — 拆掉自己的 toolbar
 * 之前：embed-toolbar (logo + 面包屑 + 7 nav 按钮 + 返回工作台 + 退出登录) + iframe
 * 现在：纯 iframe 全屏。admin-spa AdminLayout 自己渲染 sidebar + header
 *
 * 配合 admin-spa/src/components/AdminLayout.vue 改动：
 * - 不再 v-if="!embedded" 隐藏 sidebar/header（永远显）
 * - embedded 模式下 header 多出 "← 返回工作台" 按钮跳父窗口
 *
 * 这样 /ai-builder/admin/mcp 和 /platform-admin 两条路径视觉完全一致。
 */
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { getCommittedAuthTokenOrThrow } from '@/utils/request'
import { buildPlatformAdminIframeSrc, resolvePlatformAdminPath } from './platformAdminEmbedState'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const loading = ref(true)
const frameRef = ref<HTMLIFrameElement | null>(null)
let readinessTimer: number | undefined
let loadingFallbackTimer: number | undefined

const adminPath = computed(() => {
  const raw = route.params.pathMatch
  return resolvePlatformAdminPath(Array.isArray(raw) ? raw.map(String) : raw ? String(raw) : undefined)
})

const iframeSrc = computed(() => {
  return buildPlatformAdminIframeSrc({
    origin: window.location.origin,
    baseUrl: import.meta.env.BASE_URL || '/',
    adminPath: adminPath.value,
    token: getCommittedAuthTokenOrThrow(),
  })
})

function clearLoadingTimers() {
  if (readinessTimer) {
    window.clearTimeout(readinessTimer)
    readinessTimer = undefined
  }
  if (loadingFallbackTimer) {
    window.clearTimeout(loadingFallbackTimer)
    loadingFallbackTimer = undefined
  }
}

function probeFrameReady() {
  try {
    const doc = frameRef.value?.contentDocument
    const appRoot = doc?.querySelector('#app')
    if (appRoot?.firstElementChild || doc?.body?.innerText?.trim()) {
      loading.value = false
      clearLoadingTimers()
      return
    }
  } catch {
    // Same-origin in normal deployment; keep the fallback for unusual proxy setups.
  }
  readinessTimer = window.setTimeout(probeFrameReady, 250)
}

function scheduleLoadingProbe() {
  if (typeof window === 'undefined') return
  clearLoadingTimers()
  loading.value = true
  readinessTimer = window.setTimeout(probeFrameReady, 250)
  loadingFallbackTimer = window.setTimeout(() => {
    loading.value = false
    clearLoadingTimers()
  }, 10000)
}

function handleFrameLoad() {
  probeFrameReady()
}

watch(iframeSrc, () => {
  scheduleLoadingProbe()
})

// v3 2026-05-20 fix (code review #P1): postMessage listener 加 origin 检查 + cleanup
// 之前 missing origin check 任意 iframe 都能触发 redirect
// missing cleanup 导致组件 unmount 后 listener 累积
function handleAdminMessage(event: MessageEvent) {
  // 只接受来自 admin-spa iframe 的同 host message
  // admin-spa 由 backend 挂载到同源 /ai-builder/admin/
  const adminOriginAllowed = (() => {
    try {
      const adminUrl = new URL(iframeSrc.value)
      return event.origin === adminUrl.origin
    } catch {
      return false
    }
  })()
  if (!adminOriginAllowed) return
  if (event.data?.type === 'admin-return-workspace') {
    window.location.href = `${import.meta.env.BASE_URL || '/ai-builder/'}`
  }
  if (event.data?.type === 'admin-logout') {
    userStore.logout()
    try { localStorage.removeItem('admin_token') } catch { /* ignore */ }
    router.push({ path: '/login' })
  }
}

onMounted(() => {
  if (typeof window === 'undefined') return
  window.addEventListener('message', handleAdminMessage)
  scheduleLoadingProbe()

  // 兼容老 userStore 用法（保留兜底以防其他地方 watch tenantId）
  if (!userStore.tenantId) {
    userStore.fetchAvailableTenants().catch(() => {})
  }
})

onBeforeUnmount(() => {
  if (typeof window === 'undefined') return
  window.removeEventListener('message', handleAdminMessage)
  clearLoadingTimers()
})
</script>

<style scoped>
/* v3 2026-05-20 — 极简纯 iframe wrapper */
.platform-admin-embed {
  position: relative;
  height: 100vh;
  width: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg, #F8FAFC);
}

.embed-frame {
  flex: 1;
  width: 100%;
  border: 0;
  display: block;
  background: var(--surface);
}

.embed-loading {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  background: var(--surface-overlay, rgba(255, 255, 255, 0.8));
  color: var(--text-2);
  font-size: 13px;
  font-weight: 500;
  z-index: 10;
  backdrop-filter: blur(2px);
}
</style>
