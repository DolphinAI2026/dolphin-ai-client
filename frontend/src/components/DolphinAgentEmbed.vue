<template>
  <div class="dolphin-agent-embed">
    <!-- 当前应用上下文提示条 — "新对话" 用 dolphin 自带的 sidebar 按钮，不再重复 -->
    <div v-if="appId" class="dolphin-ctx-bar">
      <span class="ctx-icon" aria-hidden="true">📌</span>
      <span class="ctx-text">
        当前在编辑 <strong>{{ appName || `应用 #${appId}` }}</strong>
        <code>#{{ appId }}</code>
      </span>
      <button
        type="button"
        class="ctx-copy-btn"
        :title="copyButtonTitle"
        @click="copyContext"
      >{{ copyState }}</button>
    </div>

    <iframe
      v-if="iframeSrc"
      ref="iframeRef"
      :key="props.appId || 0"
      :src="iframeSrc"
      class="dolphin-agent-iframe"
      :title="title || 'AI 助手'"
      :style="{ opacity: ctxInjected ? 1 : 0.6 }"
    />
    <div v-else class="dolphin-loading">
      <span class="spinner">⟳</span>
      <span>加载 AI 助手...</span>
    </div>
    <div v-if="iframeSrc && !ctxInjected" class="dolphin-ctx-syncing">
      <span class="spinner">⟳</span>
      <span>正在告诉 AI 助手当前应用…</span>
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

// 进入或切换应用时，每次都让 backend 在 dolphin 里开一个含 ctx 的新 session
// （不缓存）—— dolphin embed iframe resume 的是 dolphin user 最近 session，
// 跨 app 共享。如果不每次 inject，刷新时 dolphin 会显示其他 app 留下的最近
// session，用户看到的对话历史就不对了。
//
// 历史会话不会丢：dolphin sidebar 历史对话区按 project 归类能看到，用户想
// 接续旧对话手动点 sidebar 即可。
const ctxInjected = ref(false)

async function injectAppContext() {
  if (!props.appId) {
    ctxInjected.value = true
    return
  }
  // 等 ai-builder backend current_app state 同步好（让 mcp 调用能反查真实租户）
  await new Promise(r => setTimeout(r, 300))
  try {
    await request.post('/dolphin/init-app-context', {
      app_id: props.appId,
      app_name: props.appName || '',
    })
  } catch (err) {
    console.warn('[DolphinAgentEmbed] init-app-context failed', err)
  } finally {
    ctxInjected.value = true
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

onMounted(async () => {
  window.addEventListener('message', onMessage)
  await loadConfig()
  await injectAppContext()
})

onBeforeUnmount(() => {
  window.removeEventListener('message', onMessage)
})

// 切应用时重新注入 ctx → iframe 会 resume 新 session（含新 ctx）
watch(() => props.appId, async (newId, oldId) => {
  if (oldId !== newId) {
    ctxInjected.value = false
    await injectAppContext()
  }
})

// 上下文复制：把 "当前编辑应用 #X (Y)" copy 到剪贴板，方便用户直接粘贴到对话
const copyState = ref('复制上下文')
const copyButtonTitle = computed(() => '点击复制 "当前应用 #X (名字)" 到剪贴板，发给 AI 助手时粘贴一下即可。')
async function copyContext() {
  if (!props.appId) return
  const ctx = `当前编辑应用 #${props.appId}（${props.appName || '未命名'}），请基于这个应用回答。`
  try {
    await navigator.clipboard.writeText(ctx)
    copyState.value = '已复制 ✓'
    setTimeout(() => { copyState.value = '复制上下文' }, 1500)
  } catch {
    copyState.value = '复制失败'
    setTimeout(() => { copyState.value = '复制上下文' }, 1500)
  }
}
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

.dolphin-ctx-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: linear-gradient(135deg, #f3eefe 0%, #e9deff 100%);
  border-bottom: 1px solid #c4b5fd;
  font-size: 12px;
  color: #4c1d95;
  flex-shrink: 0;
}

.dolphin-ctx-bar .ctx-icon {
  font-size: 14px;
}

.dolphin-ctx-bar .ctx-text {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.dolphin-ctx-bar .ctx-text strong {
  font-weight: 600;
  margin: 0 2px;
}

.dolphin-ctx-bar .ctx-text code {
  background: rgba(124, 58, 237, 0.12);
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 11px;
  margin-left: 2px;
}

.dolphin-ctx-bar .ctx-copy-btn {
  border: 1px solid #c4b5fd;
  background: #fff;
  color: #6d28d9;
  padding: 3px 10px;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
}

.dolphin-ctx-bar .ctx-copy-btn:hover {
  background: #f3eefe;
  border-color: #a78bfa;
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

.dolphin-ctx-syncing {
  position: absolute;
  bottom: 12px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 6px;
  background: rgba(124, 58, 237, 0.92);
  color: #fff;
  font-size: 12px;
  padding: 5px 12px;
  border-radius: 16px;
  z-index: 10;
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
