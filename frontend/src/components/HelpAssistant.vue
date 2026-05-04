<template><div class="ha-sdk-host" /></template>

<script setup lang="ts">
import { onMounted, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useUserStore } from '@/stores/user'
import request from '@/utils/request'

declare global {
  interface Window {
    DolphinAgent?: {
      init: (config: Record<string, unknown>) => void
      destroy?: () => void
      open?: () => void
      close?: () => void
      toggle?: () => void
    }
    __dolphinInited?: boolean
    __dolphinInitedFor?: string  // 当前 init 对应的 ai-builder token，切账号时不一致就 reinit
  }
}

const SDK_ID = 'dolphin-agent-sdk-script'

interface DolphinConfig {
  server_url: string
  agent_code: string
  tenant_id: string
  access_token: string
  dolphin_user_id?: number | null
}

async function fetchConfigAndInit() {
  const aibToken = localStorage.getItem('token') || ''
  if (!aibToken) return  // 未登录，浮窗等下次

  // 已经为当前账号 init 过了 — 不重复
  if (window.__dolphinInited && window.__dolphinInitedFor === aibToken) return

  // 切账号 / 切租户 / token 刷新：先拆掉旧浮窗
  if (window.__dolphinInited && window.DolphinAgent?.destroy) {
    try { window.DolphinAgent.destroy() } catch (e) { /* ignore */ }
  }
  window.__dolphinInited = false
  window.__dolphinInitedFor = ''

  let cfg: DolphinConfig
  try {
    cfg = await request.get<unknown, DolphinConfig>('/dolphin/config')
  } catch (err) {
    console.warn('[HelpAssistant] /dolphin/config 失败：', err)
    return
  }
  if (!cfg?.access_token || !cfg?.agent_code) {
    console.warn('[HelpAssistant] dolphin 配置不完整，跳过初始化')
    return
  }

  window.__dolphinInited = true
  window.__dolphinInitedFor = aibToken

  const init = () => {
    if (!window.DolphinAgent) return
    window.DolphinAgent.init({
      serverUrl: cfg.server_url,
      agentCode: cfg.agent_code,
      _jwt: cfg.access_token,
      _tenantId: cfg.tenant_id,
      buttonText: 'AI-Builder 使用助手',
      theme: 'light',
      width: 440,
      height: 680,
    })
  }

  if (window.DolphinAgent) {
    init()
    return
  }
  const existing = document.getElementById(SDK_ID) as HTMLScriptElement | null
  if (existing) {
    existing.addEventListener('load', init, { once: true })
    return
  }
  const s = document.createElement('script')
  s.id = SDK_ID
  s.src = `${cfg.server_url}/embed/sdk.js`
  s.async = true
  s.onload = init
  document.body.appendChild(s)
}

onMounted(() => {
  void fetchConfigAndInit()
  // 切账号 / 切租户：user store token 变化 → destroy + 重 init
  // 浮窗里显示的就是新账号在 dolphin 镜像账号的身份，不再串号
  const userStore = useUserStore()
  const { token } = storeToRefs(userStore)
  watch(token, () => { void fetchConfigAndInit() })
})
</script>

<style scoped>
.ha-sdk-host { display: none; }
</style>
