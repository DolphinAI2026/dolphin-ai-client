<template><div class="ha-sdk-host" /></template>

<script setup lang="ts">
import { onMounted } from 'vue'
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
  }
}

const SDK_ID = 'dolphin-agent-sdk-script'

interface DolphinConfig {
  server_url: string
  agent_code: string
  tenant_id: string
  access_token: string
}

async function bootOnce() {
  // window 级单例：跨 HMR / 跨组件实例都只 init 一次，避免 dolphin SDK 把浮窗挂多份
  if (window.__dolphinInited) return

  // ai-builder 登录后向后端拿 dolphin SDK 配置（access_token 不下发到前端 build）
  if (!localStorage.getItem('token')) return  // 未登录，浮窗等下次

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

onMounted(() => { void bootOnce() })
</script>

<style scoped>
.ha-sdk-host { display: none; }
</style>
