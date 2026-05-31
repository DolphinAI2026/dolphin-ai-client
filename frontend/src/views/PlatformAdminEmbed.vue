<template>
  <section class="platform-admin-embed">
    <iframe
      :key="iframeSrc"
      class="embed-frame"
      :src="iframeSrc"
      title="平台管理"
      @load="loading = false"
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
 * 这样 /admin/mcp 和 /platform-admin 两条路径视觉完全一致。
 */
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const userStore = useUserStore()
const loading = ref(true)

const adminPath = computed(() => {
  const raw = route.params.pathMatch
  const parts = Array.isArray(raw) ? raw : raw ? [String(raw)] : []
  const path = `/${parts.filter(Boolean).join('/')}`.replace(/\/+/g, '/')
  return path === '/' || path === '/status' ? '/mcp' : path
})

const iframeSrc = computed(() => {
  const token = localStorage.getItem('token') || ''
  const params = new URLSearchParams({ embed: '1' })
  if (token) params.set('handoff_token', token)

  return `${window.location.origin}/admin${adminPath.value}?${params.toString()}`
})

watch(iframeSrc, () => {
  loading.value = true
})

// v3 2026-05-20 fix (code review #P1): postMessage listener 加 origin 检查 + cleanup
// 之前 missing origin check 任意 iframe 都能触发 redirect
// missing cleanup 导致组件 unmount 后 listener 累积
function handleAdminMessage(event: MessageEvent) {
  // 只接受来自 admin-spa iframe 的同 host message
  // admin-spa 由 backend 挂载到同源 /admin/
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
}

onMounted(() => {
  if (typeof window === 'undefined') return
  window.addEventListener('message', handleAdminMessage)

  // 兼容老 userStore 用法（保留兜底以防其他地方 watch tenantId）
  if (!userStore.tenantId) {
    userStore.fetchAvailableTenants().catch(() => {})
  }
})

onBeforeUnmount(() => {
  if (typeof window === 'undefined') return
  window.removeEventListener('message', handleAdminMessage)
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
