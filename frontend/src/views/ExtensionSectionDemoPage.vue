<template>
  <div class="ext-demo-page">
    <header class="ext-demo-header">
      <h1>Extension Section — Demo (PR6)</h1>
      <p class="ext-demo-hint">
        SPEC v2 §2 Section E0 — 扩展开发跳走卡片 + WebSocket / 轮询通知.
        本页只验证组件本身, ChatPage 接入在 PR2b.
      </p>

      <div class="ext-demo-controls">
        <label>
          App ID:
          <input v-model.number="appId" type="number" min="1" />
        </label>
        <label>
          aPaaS App ID:
          <input v-model="apaasAppId" type="text" />
        </label>
        <label>
          Env ID:
          <input v-model.number="envId" type="number" min="0" />
        </label>
        <label>
          轮询间隔 (ms):
          <input v-model.number="pollIntervalMs" type="number" min="0" step="1000" />
        </label>
        <label class="ext-demo-checkbox">
          <input v-model="showDebug" type="checkbox" />
          显示 SSE / 轮询调试信息
        </label>
      </div>

      <div class="ext-demo-controls">
        <button class="ext-demo-btn" :disabled="!appId" @click="sendMockNotify">
          模拟外部更新通知 → 触发 SSE banner
        </button>
        <span v-if="lastNotifyResult" class="ext-demo-result">{{ lastNotifyResult }}</span>
      </div>
    </header>

    <main class="ext-demo-main">
      <ExtensionSectionPanel
        v-if="appId"
        :key="`${appId}-${envId}`"
        :app-id="appId"
        :apaas-app-id="apaasAppId"
        :env-id="envId"
        :poll-interval-ms="pollIntervalMs"
        :show-debug="showDebug"
        :platform-dev-kit-url="platformDevKitUrl"
        @navigated="onNavigated"
        @external-update="onExternalUpdate"
        @republished="onRepublished"
      />
      <div v-else class="ext-demo-empty">填一个 App ID 加载组件.</div>
    </main>

    <aside class="ext-demo-log">
      <h3>事件日志</h3>
      <ul>
        <li v-for="(entry, idx) in eventLog" :key="idx">
          <code>{{ entry.ts }}</code>
          <strong>{{ entry.tag }}</strong>
          <span>{{ entry.detail }}</span>
        </li>
      </ul>
      <div v-if="!eventLog.length" class="ext-demo-empty">还没有事件 — 点上面"模拟外部更新通知".</div>
    </aside>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import ExtensionSectionPanel from '@/components/v2/ExtensionSectionPanel.vue'
import extensionApi, { type ExtensionUpdateEvent } from '@/api/extension'

const appId = ref<number>(1)
const apaasAppId = ref('mock-apaas-app-id-0001')
const envId = ref<number>(1)
const pollIntervalMs = ref<number>(30000)
const showDebug = ref(true)
const platformDevKitUrl = ref('https://example.apaas.example.com/platform/admin/dev-kit-manager?appId=mock')

const lastNotifyResult = ref('')
interface LogEntry { ts: string; tag: string; detail: string }
const eventLog = ref<LogEntry[]>([])

function pushLog(tag: string, detail: string) {
  eventLog.value.unshift({ ts: new Date().toLocaleTimeString(), tag, detail })
  if (eventLog.value.length > 30) eventLog.value.length = 30
}

function onNavigated(target: 'ai-coding' | 'platform-dev-kit') {
  pushLog('navigated', `target=${target}`)
}

function onExternalUpdate(payload: ExtensionUpdateEvent) {
  pushLog('external-update', JSON.stringify(payload))
}

function onRepublished(version: string) {
  pushLog('republished', `version=${version}`)
}

async function sendMockNotify() {
  if (!appId.value) return
  try {
    const resp = await extensionApi.notifyExtensionUpdate(appId.value, {
      event_type: 'dev_kit_published',
      payload: {
        kit_id: `mock-kit-${Date.now()}`,
        kit_name: 'mock-component.zip',
        from_workspace: 'ws_demo',
      },
    })
    lastNotifyResult.value = `delivered=${resp.delivered}`
    pushLog('mock-notify-sent', `delivered=${resp.delivered}`)
  } catch (e: any) {
    lastNotifyResult.value = `error: ${e?.message || e}`
    pushLog('mock-notify-error', String(e?.message || e))
  }
}
</script>

<style scoped>
.ext-demo-page {
  display: grid;
  grid-template-columns: 1fr 300px;
  grid-template-rows: auto 1fr;
  gap: 16px;
  min-height: 100vh;
  padding: 24px;
  background: var(--t-bg-base, #f0f4ff);
}
.ext-demo-header {
  grid-column: 1 / -1;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px 20px;
  background: var(--t-bg-panel, #ffffff);
  border-radius: 12px;
  box-shadow: var(--t-shadow-sm, 0 1px 2px rgba(0, 0, 0, 0.04));
}
.ext-demo-header h1 {
  margin: 0;
  font-size: 22px;
  color: var(--t-text-primary, #1e293b);
}
.ext-demo-hint {
  margin: 0;
  font-size: 13px;
  color: var(--t-text-secondary, #64748b);
}
.ext-demo-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  padding-top: 8px;
}
.ext-demo-controls label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--t-text-secondary, #64748b);
}
.ext-demo-controls input[type="text"],
.ext-demo-controls input[type="number"] {
  font-size: 12px;
  padding: 4px 8px;
  border: 1px solid var(--t-border-strong, rgba(99, 102, 241, 0.15));
  border-radius: 6px;
  background: var(--t-bg-input, #f5f7fc);
  color: var(--t-text-primary, #1e293b);
  min-width: 120px;
}
.ext-demo-checkbox {
  cursor: pointer;
}
.ext-demo-btn {
  padding: 6px 14px;
  background: var(--t-brand-text, #4f6ef7);
  color: #fff;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
}
.ext-demo-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.ext-demo-btn:hover:not(:disabled) {
  filter: brightness(1.08);
}
.ext-demo-result {
  font-size: 11px;
  color: var(--t-text-muted, #94a3b8);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.ext-demo-main {
  grid-column: 1;
  grid-row: 2;
}
.ext-demo-log {
  grid-column: 2;
  grid-row: 2;
  background: var(--t-bg-panel, #ffffff);
  border-radius: 12px;
  padding: 14px 16px;
  font-size: 12px;
  color: var(--t-text-secondary, #64748b);
  box-shadow: var(--t-shadow-sm, 0 1px 2px rgba(0, 0, 0, 0.04));
  max-height: calc(100vh - 200px);
  overflow-y: auto;
}
.ext-demo-log h3 {
  margin: 0 0 8px;
  font-size: 13px;
  color: var(--t-text-primary, #1e293b);
}
.ext-demo-log ul {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.ext-demo-log li {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 6px 8px;
  background: var(--t-bg-base, #f0f4ff);
  border-radius: 6px;
}
.ext-demo-log code {
  font-size: 10px;
  color: var(--t-text-muted, #94a3b8);
}
.ext-demo-log strong {
  font-size: 12px;
  color: var(--t-brand-text, #4f6ef7);
}
.ext-demo-log span {
  font-size: 11px;
  color: var(--t-text-secondary, #64748b);
  word-break: break-all;
}

.ext-demo-empty {
  padding: 24px;
  font-size: 13px;
  color: var(--t-text-muted, #94a3b8);
  text-align: center;
}
</style>
