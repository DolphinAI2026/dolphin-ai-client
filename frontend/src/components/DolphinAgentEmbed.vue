<template>
  <div class="dolphin-agent-embed">
    <iframe
      v-if="iframeSrc"
      ref="iframeRef"
      :src="iframeSrc"
      class="dolphin-agent-iframe"
      :title="title || 'AI 助手'"
    />
    <div v-else class="dolphin-loading">
      <span class="spinner">⟳</span>
      <span>加载 AI 助手...</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import request from '@/utils/request'

interface DolphinConfig {
  server_url: string
  agent_code: string
  app_adjust_agent_code: string
  tenant_id: string
  access_token: string
}

const props = defineProps<{
  /** 用哪个 agent code；不传则用 app_adjust_agent_code（应用调整助手） */
  agentCode?: string
  /** 当前应用上下文 */
  appId?: number | null
  appName?: string
  title?: string
}>()

const cfg = ref<DolphinConfig | null>(null)
const iframeRef = ref<HTMLIFrameElement | null>(null)

const iframeSrc = computed(() => {
  if (!cfg.value) return ''
  const code = props.agentCode || cfg.value.app_adjust_agent_code || cfg.value.agent_code
  if (!code) return ''
  // dolphin 提供的 iframe 入口路径
  const url = new URL(`${cfg.value.server_url}/embed/agent/${code}/chat`)
  // 把当前应用上下文带进 query，dolphin agent 自身可以读到
  if (props.appId) url.searchParams.set('app_id', String(props.appId))
  if (props.appName) url.searchParams.set('app_name', props.appName)
  return url.toString()
})

async function loadConfig() {
  if (!localStorage.getItem('token')) return
  try {
    cfg.value = await request.get<unknown, DolphinConfig>('/dolphin/config')
  } catch (err) {
    console.warn('[DolphinAgentEmbed] /dolphin/config failed', err)
  }
}

// 监听 dolphin iframe 的 ready 消息，发送 auth token
function onMessage(event: MessageEvent) {
  if (!cfg.value) return
  // dolphin iframe 来源校验
  const allowedOrigin = new URL(cfg.value.server_url).origin
  if (event.origin !== allowedOrigin) return
  if (event.data?.type !== 'ready') return
  iframeRef.value?.contentWindow?.postMessage({
    type: 'auth',
    token: cfg.value.access_token,
    tenantId: cfg.value.tenant_id,
  }, allowedOrigin)
}

onMounted(() => {
  window.addEventListener('message', onMessage)
  loadConfig()
})

onBeforeUnmount(() => {
  window.removeEventListener('message', onMessage)
})

// 应用切换时不重建 iframe，只通过 postMessage 通知 dolphin 上下文变化
watch(() => [props.appId, props.appName], () => {
  if (!cfg.value || !iframeRef.value?.contentWindow) return
  const origin = new URL(cfg.value.server_url).origin
  iframeRef.value.contentWindow.postMessage({
    type: 'context',
    app_id: props.appId || null,
    app_name: props.appName || '',
  }, origin)
})
</script>

<style scoped>
.dolphin-agent-embed {
  width: 100%;
  height: 100%;
  position: relative;
  background: var(--b-bg, #fff);
  display: flex;
  flex-direction: column;
}

.dolphin-agent-iframe {
  flex: 1;
  width: 100%;
  height: 100%;
  border: 0;
  display: block;
}

.dolphin-loading {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #8a9099;
  font-size: 14px;
}

.spinner {
  display: inline-block;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
