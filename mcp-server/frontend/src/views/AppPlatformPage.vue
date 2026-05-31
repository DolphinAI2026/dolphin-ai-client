<template>
  <WorkbenchShell>
    <div class="app-platform-page">
      <header class="app-platform-bar">
        <button class="app-platform-back" @click="$router.push('/apps')" title="返回应用列表">
          <span aria-hidden="true">←</span>
        </button>
        <span class="app-platform-breadcrumb">应用 / </span>
        <span class="app-platform-title">{{ appName || `#${appIdNum}` }}</span>
        <span class="app-platform-id">#{{ appIdNum }}</span>
        <span
          v-if="contextInjected"
          class="app-platform-ai-hint"
          title="AI 伴侣（右下角浮窗）已感知到当前应用，可直接对话调整字段/表单/权限等"
        >
          <span aria-hidden="true">✨</span> AI 伴侣已就绪
        </span>
        <span class="app-platform-spacer" />
        <a
          v-if="apaasUrl"
          class="app-platform-newtab"
          :href="apaasUrl"
          target="_blank"
          rel="noopener noreferrer"
          title="在新窗口打开（脱离 ai-builder 框架）"
        >↗</a>
      </header>

      <div v-if="loading" class="app-platform-loading">
        <span class="spinner">⟳</span>
        <span>加载低代码后台...</span>
      </div>

      <div v-else-if="error" class="app-platform-error">
        <p>{{ error }}</p>
        <button @click="loadApp" class="retry-btn">重试</button>
      </div>

      <iframe
        v-else-if="apaasUrl"
        :src="apaasUrl"
        class="app-platform-iframe"
        frameborder="0"
        allow="clipboard-read; clipboard-write"
      />

      <div v-else class="app-platform-error">
        <p>应用尚未部署到 apaas 平台，无 apaas_url 可嵌入。</p>
        <button @click="$router.push(`/ai-copilot?app_id=${appIdNum}`)" class="retry-btn">
          → 进 AI 伴侣调整应用
        </button>
      </div>
    </div>
  </WorkbenchShell>
</template>

<script setup lang="ts">
/**
 * 应用低代码后台嵌入页 — 已部署应用从应用列表点进，看到的就是这页：
 *   ai-builder 框架（左侧 NavRail）+ 中间 apaas 真实低代码后台 iframe。
 *
 * 设计原则：保持极简轻量，避开 ChatPage 那个又慢又复杂的双源加载页。
 * 不挂 dolphin embed（用户要 AI 调整应用走 /ai-copilot?app_id=X，那边专门做对话）。
 *
 * iframe 用 apaas 真实域名 URL（不走 platform_proxy），加载速度等同直接打开
 * apaas 站。首次访问可能要在 apaas 登录一次，后续 SSO 接通后无感。
 */
import { computed, ref, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import request from '@/utils/request'

defineOptions({ name: 'AppPlatformPage' })

const route = useRoute()
const loading = ref(true)
const error = ref('')
const appName = ref('')
const apaasUrl = ref('')
const contextInjected = ref(false)  // init-app-context 是否成功写入 backend state

const appIdNum = computed(() => {
  const raw = route.params.appId
  const v = Array.isArray(raw) ? raw[0] : raw
  const n = Number(v)
  return Number.isFinite(n) && n > 0 ? n : 0
})

interface AppMeta {
  id: number
  app_name?: string
  apaas_url?: string
  apaas_app_id?: string | null
  status?: string
}

async function loadApp() {
  if (!appIdNum.value) {
    error.value = '应用 ID 无效'
    loading.value = false
    return
  }
  loading.value = true
  error.value = ''
  try {
    const res = await request.get<unknown, AppMeta>(`/applications/${appIdNum.value}`)
    appName.value = res?.app_name || ''
    apaasUrl.value = res?.apaas_url || ''
    if (!apaasUrl.value && !res?.apaas_app_id) {
      error.value = '应用尚未部署到 apaas 平台'
    }
    // ★ 关键：把 (user, app_id) 写到 backend current_app state，让右下角 dolphin
    // 浮窗里聊天时 MCP 工具能反查到"用户当前在编辑哪个应用"。否则 agent 调
    // get_application 不传 app_id 时拿不到 app_id 反查（_resolve_app_id 0 走默认）。
    // init-app-context 同时会确保 dolphin project_id / session_id 持久化映射，
    // 即使浮窗 SDK 自己开 session（不用我们反查的 session_id），current_app state
    // 写好了 agent 调 mcp 工具就能感知当前应用。
    if (apaasUrl.value || appName.value) {
      // 静默调用，失败不影响主流程；agent 拿不到 app_id 时只是无 context 兜底
      contextInjected.value = false
      try {
        await request.post('/dolphin/init-app-context', {
          app_id: appIdNum.value,
          app_name: appName.value || '',
        })
        contextInjected.value = true
      } catch (err) {
        console.warn('[AppPlatformPage] init-app-context 失败（不影响主流程）：', err)
      }
    }
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '加载应用信息失败'
  } finally {
    loading.value = false
  }
}

onMounted(loadApp)
watch(appIdNum, loadApp)
</script>

<style scoped>
.app-platform-page {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  background: var(--t-bg, #fff);
}

.app-platform-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  border-bottom: 1px solid var(--t-border-subtle, #e5e7eb);
  background: var(--t-bg-panel, #fafbfc);
  flex-shrink: 0;
  font-size: 14px;
}

.app-platform-back {
  width: 28px;
  height: 28px;
  border: 0;
  background: transparent;
  color: var(--t-text-secondary, #6b7280);
  font-size: 18px;
  cursor: pointer;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.app-platform-back:hover {
  background: var(--t-bg-hover, #f3f4f6);
  color: var(--t-text-primary, #111827);
}

.app-platform-breadcrumb {
  color: var(--t-text-muted, #9ca3af);
}

.app-platform-title {
  color: var(--t-text-primary, #111827);
  font-weight: 600;
}

.app-platform-id {
  color: var(--t-text-muted, #9ca3af);
  font-size: 12px;
  font-family: ui-monospace, SFMono-Regular, monospace;
  margin-left: 4px;
}

.app-platform-ai-hint {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: 12px;
  padding: 3px 10px;
  background: linear-gradient(135deg, rgba(124, 58, 237, 0.08), rgba(99, 102, 241, 0.08));
  border: 1px solid rgba(124, 58, 237, 0.2);
  border-radius: 12px;
  font-size: 12px;
  color: #6d28d9;
  cursor: help;
}

.app-platform-spacer { flex: 1; }

.app-platform-newtab {
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  text-decoration: none;
  color: var(--t-text-secondary, #6b7280);
  font-size: 16px;
}
.app-platform-newtab:hover {
  background: var(--t-bg-hover, #f3f4f6);
  color: var(--t-text-primary, #111827);
}

.app-platform-loading,
.app-platform-error {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--t-text-muted, #9ca3af);
  font-size: 14px;
}

.app-platform-error p {
  color: var(--t-text-secondary, #6b7280);
}

.retry-btn {
  padding: 6px 16px;
  border-radius: 6px;
  border: 1px solid var(--t-border, #d1d5db);
  background: #fff;
  color: var(--t-text-primary, #111827);
  cursor: pointer;
  font-size: 13px;
}
.retry-btn:hover {
  background: var(--t-bg-hover, #f3f4f6);
}

.spinner {
  display: inline-block;
  font-size: 24px;
  animation: spin 1s linear infinite;
  color: var(--t-brand, #6366f1);
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.app-platform-iframe {
  flex: 1;
  width: 100%;
  border: 0;
  display: block;
  min-height: 0;
}
</style>
