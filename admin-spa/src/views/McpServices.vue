<template>
  <div class="mcp-page">
    <section class="mcp-hero">
      <div>
        <h1>MCP 接入</h1>
        <p>统一使用一组接入凭证，下面展示当前部署提供的 5 个 MCP 服务入口。</p>
      </div>
    </section>

    <section class="summary-grid">
      <article class="summary-card">
        <div class="summary-label">管理端地址</div>
        <div class="summary-value-row">
          <strong>{{ origin }}</strong>
          <button type="button" class="icon-copy" aria-label="复制管理端地址" @click="copyText(origin, '管理端地址已复制')">
            <el-icon><CopyDocument /></el-icon>
          </button>
        </div>
      </article>
      <article class="summary-card">
        <div class="summary-label">认证请求头</div>
        <div class="summary-value-row">
          <strong>{{ authHeaderText }}</strong>
          <button type="button" class="icon-copy" aria-label="复制认证请求头" @click="copyText(authHeaderText, '认证请求头已复制')">
            <el-icon><CopyDocument /></el-icon>
          </button>
        </div>
      </article>
    </section>

    <section class="service-panel">
      <div class="panel-head">
        <div>
          <strong>MCP 服务清单</strong>
          <span>{{ services.length }} 个服务入口</span>
        </div>
      </div>
      <div class="service-table">
        <div class="table-head">
          <span>服务</span>
          <span>协议</span>
          <span>URL</span>
          <span>工具数</span>
          <span>状态</span>
          <span>操作</span>
        </div>
        <div v-for="service in services" :key="service.code" class="service-row">
          <div>
            <div class="service-name">{{ service.name }}</div>
            <div class="service-code">{{ service.code }}</div>
          </div>
          <span class="transport">{{ service.transport }}</span>
          <div class="url-cell">
            <code>{{ service.publicUrl }}</code>
            <button type="button" class="icon-copy" :aria-label="`复制${service.name}地址`" @click="copyText(service.publicUrl, '服务地址已复制')">
              <el-icon><CopyDocument /></el-icon>
            </button>
          </div>
          <span class="tool-count">{{ service.tools }} <small class="tool-count-unit">个工具</small></span>
          <span class="status-pill" :class="service.status">{{ service.status === 'online' ? '在线' : '待接入' }}</span>
          <button type="button" class="test-button" @click="openTester(service)">测试与工具</button>
        </div>
      </div>
    </section>

    <section class="headers-panel">
      <div class="panel-head">
        <div>
          <strong>接入参数</strong>
          <span>客户端请求示例</span>
        </div>
        <div class="panel-actions">
          <button type="button" class="ghost-button" @click="showFullKey = !showFullKey" :aria-label="showFullKey ? '隐藏完整凭证' : '显示完整凭证'">
            <el-icon><View v-if="!showFullKey" /><Hide v-else /></el-icon>
            {{ showFullKey ? '隐藏完整凭证' : '显示完整凭证' }}
          </button>
          <button type="button" class="copy-button" :class="{ 'copy-button-success': copiedExample }" @click="onCopyRequestExample">
            <el-icon><CopyDocument /></el-icon>
            {{ copiedExample ? '已复制 ✓' : '复制' }}
          </button>
        </div>
      </div>
      <pre>{{ requestExample }}</pre>
    </section>

    <section class="key-panel">
      <div class="panel-head">
        <div>
          <strong>接入凭证</strong>
          <span>用于访问上方 MCP 服务入口</span>
        </div>
        <div class="panel-actions">
          <button type="button" class="copy-button" :class="{ 'copy-button-success': copiedKey }" @click="onCopyKey">
            <el-icon><CopyDocument /></el-icon>
            {{ copiedKey ? '已复制 ✓' : '复制凭证' }}
          </button>
          <button type="button" class="danger-button" @click="onResetKey">重置凭证</button>
        </div>
      </div>
      <div class="key-grid">
        <div>
          <span>当前凭证指纹</span>
          <strong>{{ currentKey.fingerprint }}</strong>
        </div>
        <div>
          <span>状态</span>
          <strong class="success-text">启用</strong>
        </div>
        <p>凭证用于客户端准入；真实业务身份和租户仍由调用工具时传入的 aPaaS 用户凭证与租户 ID 决定。</p>
      </div>
    </section>
  </div>
</template>

<!--
Request example:
POST {{ services[0].publicUrl }}
Content-Type: application/json
Authorization: Bearer &lt;MCP_API_KEY&gt;
X-APaaS-Token: &lt;当前 aPaaS 用户凭证&gt;
X-APaaS-Tenant-Id: &lt;租户 ID&gt;
-->

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CopyDocument, View, Hide } from '@element-plus/icons-vue'
import { API_BASE_URL, apiGet } from '@/api/client'

interface ServiceRow {
  name: string
  code: string
  transport: string
  url: string
  publicUrl: string
  tools: number
  status: string
}

const router = useRouter()
const origin = window.location.origin
const currentKey = reactive({
  value: '',
  fingerprint: '-',
})

// v3 2026-05-21 UED 报告 P1: Bearer Token 默认脱敏 + toggle 显示
const showFullKey = ref(false)
const copiedExample = ref(false)
const copiedKey = ref(false)

function maskKey(key: string): string {
  if (!key) return '<MCP_API_KEY>'
  if (key.length <= 12) return key
  return `${key.slice(0, 8)}...${key.slice(-6)}`
}

const displayKey = computed(() => showFullKey.value ? currentKey.value : maskKey(currentKey.value))
const authHeaderText = computed(() => currentKey.value ? `Authorization: Bearer ${displayKey.value}` : 'Authorization: Bearer <MCP_API_KEY>')
const requestExample = computed(() => [
  `POST ${services[0].publicUrl}`,
  'Content-Type: application/json',
  authHeaderText.value,
  'X-APaaS-Token: <当前 aPaaS 用户凭证>',
  'X-APaaS-Tenant-Id: <租户 ID>',
].join('\n'))

function resolvePublicMcpUrl(apiPath: string) {
  const apiBase = API_BASE_URL.replace(/\/+$/, '')
  if (apiPath.startsWith('/api/')) {
    return `${origin}${apiBase}${apiPath.slice('/api'.length)}`
  }
  return `${origin}${apiPath}`
}

const services: ServiceRow[] = [
  {
    name: '主工具服务',
    code: 'apaas-builder-mcp',
    transport: 'Streamable HTTP',
    url: '/api/mcp/mcp',
    publicUrl: resolvePublicMcpUrl('/api/mcp/mcp'),
    tools: 33,
    status: 'online',
  },
  {
    name: 'Builder 场景服务',
    code: 'apaas-builder-config',
    transport: 'Streamable HTTP',
    url: '/api/mcp-builder/mcp',
    publicUrl: resolvePublicMcpUrl('/api/mcp-builder/mcp'),
    tools: 14,
    status: 'online',
  },
  {
    name: 'Coding 工作区服务',
    code: 'apaas-builder-coding',
    transport: 'Streamable HTTP',
    url: '/api/mcp-coding/mcp',
    publicUrl: resolvePublicMcpUrl('/api/mcp-coding/mcp'),
    tools: 23,
    status: 'online',
  },
  {
    name: 'Vibe 开发服务',
    code: 'apaas-builder-vibe',
    transport: 'Streamable HTTP',
    url: '/api/mcp-vibe/mcp',
    publicUrl: resolvePublicMcpUrl('/api/mcp-vibe/mcp'),
    tools: 9,
    status: 'online',
  },
  {
    name: '设计解析服务',
    code: 'apaas-builder-design',
    transport: 'Streamable HTTP',
    url: '/api/mcp-design/mcp',
    publicUrl: resolvePublicMcpUrl('/api/mcp-design/mcp'),
    tools: 4,
    status: 'online',
  },
]

function openTester(row: ServiceRow) {
  router.push({ path: '/tester', query: { service: row.code } })
}

async function copyText(value: string, message: string) {
  await navigator.clipboard.writeText(value).catch(() => null)
  ElMessage.success(message)
}

async function onCopyKey() {
  if (!currentKey.value) {
    ElMessage.warning('当前未读取到 MCP 接入凭证')
    return
  }
  const value = `Bearer ${currentKey.value}`
  await copyText(value, '当前接入凭证已复制')
  copiedKey.value = true
  setTimeout(() => { copiedKey.value = false }, 1600)
}

// v3 2026-05-21 UED 报告 P2: 复制按钮反馈 + 始终复制完整 key (不受脱敏影响)
async function onCopyRequestExample() {
  const fullExample = [
    `POST ${services[0].publicUrl}`,
    'Content-Type: application/json',
    currentKey.value ? `Authorization: Bearer ${currentKey.value}` : 'Authorization: Bearer <MCP_API_KEY>',
    'X-APaaS-Token: <当前 aPaaS 用户凭证>',
    'X-APaaS-Tenant-Id: <租户 ID>',
  ].join('\n')
  await copyText(fullExample, '接入参数已复制（含完整凭证）')
  copiedExample.value = true
  setTimeout(() => { copiedExample.value = false }, 1600)
}

function onResetKey() {
  ElMessageBox.alert(
    '重置凭证会让当前客户端配置立即失效，需要后端密钥持久化接口和审计日志支持后再启用。',
    '重置凭证',
    { confirmButtonText: '知道了' },
  )
}

onMounted(async () => {
  const resp = await apiGet<{ key: string; fingerprint?: string }>('/mcp-platform/mcp-access').catch(() => null)
  currentKey.value = resp?.key || ''
  currentKey.fingerprint = resp?.fingerprint || '-'
})
</script>

<style scoped>
/* v3 redesign · 2026-05-20 — visual refresh only, template/script untouched.
   Tokens: design-v3-tokens.css (var(--brand) blue ramp + slate text + line)
   Preserved: status-pill.online (green = state), success-text (green = state),
              danger-button (red = state). Replaced all v2 indigo-violet hex with
              tokens; replaced lavender panel-head bg with surface-2;
              4 white cards keep elevation via line + sh-1. */
/* v3 2026-05-21 — 跟 frontend 密度对齐：max-width/h1/mcp-hero/summary-card 全
   交给 density-align.css 全局规则。本 scoped 只保留布局 + 独有元素 (provider-mark
   类似) 的样式。 */
.mcp-page {
  color: var(--text);
  font-family: var(--font-sans);
}

.mcp-hero {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}

.summary-card,
.service-panel,
.headers-panel,
.key-panel {
  border: 1px solid var(--line);
  border-radius: var(--r-4, 12px);
  background: var(--surface);
  box-shadow: var(--sh-1);
}

.summary-card {
  min-width: 0;
}

.summary-label {
  color: var(--text-3);
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.summary-value-row {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 6px;
}

.summary-value-row strong {
  min-width: 0;
  overflow: hidden;
  color: var(--text);
  font-size: 14px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
  letter-spacing: -0.005em;
}

.icon-copy,
.copy-button,
.danger-button,
.test-button {
  border: 0;
  cursor: pointer;
  font: inherit;
}

.icon-copy {
  flex: 0 0 auto;
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border: 1px solid var(--line);
  border-radius: var(--r-2, 6px);
  color: var(--text-2);
  background: var(--surface);
  font-size: 13px;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.icon-copy:hover {
  background: var(--brand-soft);
  color: var(--brand);
  border-color: var(--brand-ring);
}

.service-panel,
.headers-panel,
.key-panel {
  overflow: hidden;
  margin-top: 12px;
}

.panel-head {
  /* density-align.css 全局已统一 min-height/padding/title — 仅保留 layout */
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  border-bottom: 1px solid var(--line);
}

.service-table {
  padding: 0 14px 12px;
  background: var(--surface-2);
}

.table-head,
.service-row {
  display: grid;
  grid-template-columns: minmax(180px, 1fr) 150px minmax(360px, 1.5fr) 86px 96px 124px;
  align-items: center;
  gap: 14px;
}

.table-head {
  height: 36px;
  color: var(--text-3);
  font-size: 10.5px;
  font-weight: var(--fw-medium, 500);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.service-row {
  min-height: 52px;
  padding: 8px 12px;
  border-top: 1px solid var(--line);
  border-radius: var(--r-2, 6px);
}

.service-row:hover {
  background: var(--surface);
}

.service-name {
  color: var(--text);
  font-size: 13.5px;
  font-weight: 600;
  letter-spacing: -0.005em;
}

.service-code {
  margin-top: 3px;
  color: var(--text-3);
  font-size: 11px;
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
}

.transport,
.tool-count {
  color: var(--text-2);
  font-size: 12px;
  font-weight: 500;
}

/* v3 2026-05-20 UED 报告 P1: 工具数纯数字含义不清 — 加"个工具"label */
.tool-count {
  display: inline-flex;
  align-items: baseline;
  gap: 3px;
  font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace);
  font-variant-numeric: tabular-nums;
  font-weight: 600;
}
.tool-count-unit {
  color: var(--text-3);
  font-size: 10.5px;
  font-weight: 500;
  font-family: var(--font-sans, inherit);
  letter-spacing: 0.02em;
}

.url-cell {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}

code {
  min-width: 0;
  overflow: hidden;
  color: var(--text-2);
  font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-pill {
  width: max-content;
  padding: 2px 7px;
  border-radius: var(--r-1, 4px);
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.status-pill.online {
  color: var(--ok);
  background: var(--ok-soft);
}

.test-button,
.copy-button {
  min-height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 0 12px;
  border-radius: var(--r-2, 6px);
  color: var(--text-inverse, #fff);
  background: var(--brand);
  font-size: 12.5px;
  font-weight: 600;
  box-shadow: none;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.test-button:hover,
.copy-button:hover {
  background: var(--brand-hover);
}

/* v3 2026-05-21 UED 报告 P2: 复制按钮点击后绿色短反馈 */
.copy-button-success,
.copy-button-success:hover {
  background: var(--ok);
}

/* v3 2026-05-21 UED 报告 P1: 显示/隐藏凭证 toggle 用浅色 ghost 按钮（与主操作复制区分） */
.ghost-button {
  min-height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 0 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-2, 6px);
  color: var(--text-2);
  background: var(--surface);
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  font-family: inherit;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.ghost-button:hover {
  background: var(--brand-soft);
  color: var(--brand);
  border-color: var(--brand-ring);
}

.danger-button {
  min-height: 30px;
  padding: 0 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-2, 6px);
  color: var(--text-2);
  background: var(--surface);
  font-size: 12.5px;
  font-weight: 500;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.danger-button:hover {
  background: var(--err-soft);
  color: var(--err);
  border-color: var(--err);
}

.headers-panel pre {
  margin: 0;
  white-space: pre-wrap;
  color: var(--text-2);
  background: var(--surface-3);
  padding: 18px;
  line-height: 1.7;
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
  font-size: 12px;
  border-top: 1px solid var(--line);
}

.panel-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.key-grid {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) minmax(140px, 0.6fr) minmax(320px, 1.4fr);
  gap: 10px;
  padding: 14px;
  background: var(--surface-2);
}

.key-grid div {
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-2, 6px);
  background: var(--surface);
}

.key-grid span {
  display: block;
  color: var(--text-3);
  font-size: 10.5px;
  font-weight: 500;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.key-grid strong {
  display: block;
  margin-top: 6px;
  overflow: hidden;
  color: var(--text);
  font-size: 13.5px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
  letter-spacing: -0.005em;
}

.success-text {
  color: var(--ok) !important;
}

.key-grid p {
  margin: 0;
  align-self: center;
  color: var(--text-3);
  font-size: 12.5px;
  line-height: 1.6;
}

@media (max-width: 1180px) {
  .summary-grid {
    grid-template-columns: 1fr;
  }

  .table-head {
    display: none;
  }

  .service-row,
  .key-grid {
    grid-template-columns: 1fr;
  }

  .service-row {
    align-items: start;
  }
}

/* Dark theme overrides */
html[data-theme="dark"] .summary-card,
html[data-theme="dark"] .service-panel,
html[data-theme="dark"] .headers-panel,
html[data-theme="dark"] .key-panel {
  background: var(--surface);
  border-color: var(--line);
}
html[data-theme="dark"] .panel-head {
  background: var(--surface);
}
html[data-theme="dark"] .service-table,
html[data-theme="dark"] .key-grid {
  background: var(--surface-2);
}
html[data-theme="dark"] .service-row:hover {
  background: var(--surface);
}
html[data-theme="dark"] .icon-copy,
html[data-theme="dark"] .danger-button,
html[data-theme="dark"] .ghost-button {
  background: var(--surface);
}
html[data-theme="dark"] .key-grid div {
  background: var(--surface);
}
html[data-theme="dark"] .headers-panel pre {
  background: var(--surface-3);
}
</style>
