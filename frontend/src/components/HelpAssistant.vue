<template><div class="ha-sdk-host" /></template>

<script setup lang="ts">
import { onMounted } from 'vue'

declare global {
  interface Window {
    DolphinAgent?: {
      init: (config: Record<string, unknown>) => void
      destroy?: () => void
      open?: () => void
      close?: () => void
      toggle?: () => void
    }
  }
}

const SDK_ID = 'dolphin-agent-sdk-script'
const SERVER = import.meta.env.VITE_DOLPHIN_SERVER_URL || 'https://dolphin.dfy.definesys.cn'
const AGENT = import.meta.env.VITE_DOLPHIN_AGENT_CODE || '77acab2f6f'
const JWT = import.meta.env.VITE_DOLPHIN_JWT
const TENANT = import.meta.env.VITE_DOLPHIN_TENANT_ID

let bootStarted = false

function bootOnce() {
  if (bootStarted) return
  bootStarted = true

  const init = () => {
    if (!window.DolphinAgent) return
    window.DolphinAgent.init({
      serverUrl: SERVER,
      agentCode: AGENT,
      _jwt: JWT,
      _tenantId: TENANT,
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
  s.src = `${SERVER}/embed/sdk.js`
  s.async = true
  s.onload = init
  document.body.appendChild(s)
}

onMounted(bootOnce)
</script>

<style scoped>
.ha-sdk-host { display: none; }
</style>
