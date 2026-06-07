<template>
  <div class="mcp-page">
    <section class="mcp-hero">
      <div>
        <h1>MCP 接入</h1>
        <p>平台管理直接使用 ai-builder backend 进程内 MCP 工具，便于本地单独测试。</p>
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
        <div class="summary-label">认证方式</div>
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
            <div class="url-stack">
              <code>{{ service.publicUrl }}</code>
              <span v-if="service.exampleTool" class="tool-hint">tool_name: {{ service.exampleTool }}</span>
            </div>
            <button type="button" class="icon-copy" :aria-label="`复制${service.name}地址`" @click="copyText(service.publicUrl, '服务地址已复制')">
              <el-icon><CopyDocument /></el-icon>
            </button>
          </div>
          <span class="tool-count">{{ service.tools }} <small class="tool-count-unit">个工具</small></span>
          <span class="status-pill" :class="service.status">{{ statusLabel(service.status) }}</span>
          <button type="button" class="test-button" @click="openTester(service)">测试与工具</button>
        </div>
      </div>
    </section>

    <section class="headers-panel">
      <div class="panel-head">
        <div>
          <strong>接入参数</strong>
          <span>管理端请求示例</span>
        </div>
        <div class="panel-actions">
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
          <span>当前改为平台管理登录态访问</span>
        </div>
        <div class="panel-actions">
          <button type="button" class="danger-button" @click="onResetKey">说明</button>
        </div>
      </div>
      <div class="key-grid">
        <div>
          <span>当前模式</span>
          <strong>同进程工具</strong>
        </div>
        <div>
          <span>状态</span>
          <strong class="success-text">启用</strong>
        </div>
        <p>测试工具时由主后端注入当前平台管理用户的 Builder 租户身份，不再要求独立 8004 MCP 服务或 MCP_API_KEY。</p>
      </div>
    </section>
  </div>
</template>

<!--
Request example:
POST {{ services[0].publicUrl }}
Content-Type: application/json
Authorization: Bearer &lt;平台管理登录态&gt;
-->

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CopyDocument } from '@element-plus/icons-vue'
import { apiGet } from '@/api/client'

interface ServiceRow {
  name: string
  code: string
  transport: string
  url: string
  publicUrl: string
  tools: number
  status: string
  exampleTool: string
}

const router = useRouter()
const origin = window.location.origin
const copiedExample = ref(false)

const authHeaderText = computed(() => 'Authorization: Bearer <平台管理登录态>')
const requestExample = computed(() => [
  `POST ${services.value[0].publicUrl}`,
  'Content-Type: application/json',
  authHeaderText.value,
  '',
  JSON.stringify({ tool_name: services.value[0].exampleTool, args: {} }, null, 2),
].join('\n'))

function resolvePublicMcpUrl(apiPath: string) {
  const raw = (apiPath || '').trim()
  if (/^https?:\/\//i.test(raw)) return raw
  return `${origin}${raw.startsWith('/') ? raw : `/${raw}`}`
}

const services = ref<ServiceRow[]>([
  {
    name: '同进程工具服务',
    code: 'ai-builder-inprocess',
    transport: 'FastMCP in-process',
    url: '/api/admin/mcp/call',
    publicUrl: resolvePublicMcpUrl('/api/admin/mcp/call'),
    tools: 111,
    status: 'online',
    exampleTool: 'list_platform_envs',
  },
  {
    name: '问题分诊记录 MCP',
    code: 'support-triage',
    transport: 'FastMCP in-process',
    url: '/api/admin/mcp/call',
    publicUrl: resolvePublicMcpUrl('/api/admin/mcp/call'),
    tools: 1,
    status: 'online',
    exampleTool: 'record_support_triage',
  },
])

function openTester(row: ServiceRow) {
  router.push({ path: '/tester', query: { service: row.code } })
}

function statusLabel(status: string) {
  if (status === 'online') return '在线'
  if (status === 'missing') return '工具未加载'
  return '检测失败'
}

async function copyText(value: string, message: string) {
  await navigator.clipboard.writeText(value).catch(() => null)
  ElMessage.success(message)
}

// v3 2026-05-21 UED 报告 P2: 复制按钮反馈 + 始终复制完整 key (不受脱敏影响)
async function onCopyRequestExample() {
  const fullExample = [
    `POST ${services.value[0].publicUrl}`,
    'Content-Type: application/json',
    'Authorization: Bearer <平台管理登录态>',
    '',
    JSON.stringify({ tool_name: services.value[0].exampleTool, args: {} }, null, 2),
  ].join('\n')
  await copyText(fullExample, '请求示例已复制')
  copiedExample.value = true
  setTimeout(() => { copiedExample.value = false }, 1600)
}

function onResetKey() {
  ElMessageBox.alert(
    '当前平台管理测试台调用同进程 MCP 工具，不再使用独立 MCP_API_KEY。外部客户端接入如需恢复，可再单独接回 HTTP MCP 服务。',
    '同进程 MCP',
    { confirmButtonText: '知道了' },
  )
}

onMounted(async () => {
  try {
    const data = await apiGet<any>('/admin/mcp/tools')
    const tools = Array.isArray(data?.tools) ? data.tools : []
    services.value[0].tools = tools.length || services.value[0].tools
    const hasSupportTriage = tools.some((item: any) => item?.name === 'record_support_triage')
    services.value[1].tools = hasSupportTriage ? 1 : 0
    services.value[1].status = hasSupportTriage ? 'online' : 'missing'
  } catch {
    services.value[1].status = 'pending'
  }
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

.url-stack {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.tool-hint {
  overflow: hidden;
  color: var(--text-3);
  font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace);
  font-size: 10.5px;
  text-overflow: ellipsis;
  white-space: nowrap;
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

.status-pill.missing,
.status-pill.pending {
  color: var(--warn);
  background: var(--warn-soft);
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
