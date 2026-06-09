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
      <article class="summary-card auth-summary-card">
        <div class="summary-label">认证方式</div>
        <div class="summary-value-row">
          <strong class="auth-header-text">{{ authHeaderText }}</strong>
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
          <span>外部 MCP 使用页面配置的 key；管理台测试使用登录态</span>
        </div>
        <div class="panel-actions">
          <button v-if="!editingKeys" type="button" class="secondary-button" @click="startEditKeys">编辑</button>
          <button v-if="editingKeys" type="button" class="secondary-button" @click="cancelEditKeys">取消</button>
          <button v-if="editingKeys" type="button" class="copy-button" :disabled="savingKeys" @click="saveKeys(false)">
            {{ savingKeys ? '保存中...' : '保存' }}
          </button>
          <button type="button" class="copy-button" :disabled="savingKeys" @click="saveKeys(true)">生成 key</button>
        </div>
      </div>
      <div class="key-grid">
        <div>
          <span>当前模式</span>
          <strong>标准 MCP 接入</strong>
        </div>
        <div>
          <span>配置来源</span>
          <strong :class="accessInfo?.source === 'database' ? 'success-text' : 'warn-text'">{{ keySourceLabel }}</strong>
        </div>
        <div>
          <span>状态</span>
          <strong :class="primaryMcpKey ? 'success-text' : 'warn-text'">{{ primaryMcpKey ? '启用' : '未配置' }}</strong>
        </div>
        <div class="key-config-row">
          <span>MCP Keys</span>
          <textarea
            v-if="editingKeys"
            v-model="keyDraft"
            class="key-editor"
            rows="4"
            placeholder="每行一个 key，也可以用英文逗号分隔"
          />
          <strong v-else class="key-value" :class="{ 'muted-text': !primaryMcpKey }">{{ primaryMcpKey || '未配置' }}</strong>
        </div>
        <p>外部 Agent 调标准 MCP 服务时使用这里配置的 key。测试工具时由主后端注入当前平台管理用户的 Builder 租户身份。</p>
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
import { ElMessage } from 'element-plus'
import { CopyDocument } from '@element-plus/icons-vue'
import { apiGet, apiPut } from '@/api/client'

interface ServiceRow {
  name: string
  code: string
  transport: string
  url: string
  publicUrl: string
  adminUrl: string
  tools: number
  status: string
  exampleTool: string
}

interface ToolItem {
  name: string
  description?: string
  inputSchema?: any
  input_schema?: any
}

interface McpAccessInfo {
  has_key?: boolean
  primary_key?: string
  keys?: string[]
  auth_header?: string
  source?: string
}

const SUPPORT_TRIAGE_TOOL_NAME = 'record_support_triage'

const router = useRouter()
const origin = (import.meta.env.VITE_MCP_PUBLIC_BASE || window.location.origin).replace(/\/$/, '')
const copiedExample = ref(false)
const accessInfo = ref<McpAccessInfo | null>(null)
const editingKeys = ref(false)
const savingKeys = ref(false)
const keyDraft = ref('')

const primaryMcpKey = computed(() => (accessInfo.value?.primary_key || '').trim())
const keySourceLabel = computed(() => {
  if (accessInfo.value?.source === 'database') return '页面配置'
  if (accessInfo.value?.source === 'env') return '环境变量兜底'
  return '未配置'
})
const authHeaderText = computed(() => (
  accessInfo.value?.auth_header
  || (primaryMcpKey.value ? `Authorization: Bearer ${primaryMcpKey.value}` : 'MCP key 未配置')
))
const requestExample = computed(() => [
  `POST ${services.value[0].publicUrl}`,
  'Content-Type: application/json',
  primaryMcpKey.value ? `Authorization: Bearer ${primaryMcpKey.value}` : 'Authorization: Bearer <MCP key 未配置>',
  '# 兼容 Dolphin 网关：也可使用 X-API-Key 或 X-AI-GW-KEY',
  '',
  'MCP 客户端会自动发送 initialize / tools/list / tools/call，不需要手写 tool_name。',
].join('\n'))

function resolvePublicMcpUrl(apiPath: string) {
  const raw = (apiPath || '').trim()
  if (/^https?:\/\//i.test(raw)) return raw
  return `${origin}${raw.startsWith('/') ? raw : `/${raw}`}`
}

const services = ref<ServiceRow[]>([
  {
    name: '主 MCP 工具服务',
    code: 'apaas-builder-mcp',
    transport: 'Streamable HTTP',
    url: '/api/mcp/mcp',
    publicUrl: resolvePublicMcpUrl('/api/mcp/mcp'),
    adminUrl: '/api/admin/mcp/tools',
    tools: 0,
    status: 'checking',
    exampleTool: 'list_platform_envs',
  },
  {
    name: '问题分诊记录 MCP',
    code: 'support-triage',
    transport: 'Streamable HTTP',
    url: '/api/support-triage-mcp/mcp',
    publicUrl: resolvePublicMcpUrl('/api/support-triage-mcp/mcp'),
    adminUrl: '/api/admin/mcp/support-triage-tools',
    tools: 0,
    status: 'checking',
    exampleTool: 'record_support_triage',
  },
])

function openTester(row: ServiceRow) {
  router.push({ path: '/tester', query: { service: row.code } })
}

function statusLabel(status: string) {
  if (status === 'online') return '在线'
  if (status === 'missing') return '工具未加载'
  if (status === 'checking') return '检测中'
  return '检测失败'
}

async function copyText(value: string, message: string) {
  await navigator.clipboard.writeText(value).catch(() => null)
  ElMessage.success(message)
}

// v3 2026-05-21 UED 报告 P2: 复制按钮反馈 + 始终复制完整 key (不受脱敏影响)
async function onCopyRequestExample() {
  await copyText(requestExample.value, '请求示例已复制')
  copiedExample.value = true
  setTimeout(() => { copiedExample.value = false }, 1600)
}

function syncDraftFromAccessInfo() {
  keyDraft.value = (accessInfo.value?.keys || []).join('\n')
}

function startEditKeys() {
  syncDraftFromAccessInfo()
  editingKeys.value = true
}

function cancelEditKeys() {
  syncDraftFromAccessInfo()
  editingKeys.value = false
}

async function saveKeys(generate: boolean) {
  savingKeys.value = true
  try {
    accessInfo.value = await apiPut<McpAccessInfo>('/admin/mcp/access-info', {
      keys: keyDraft.value,
      generate,
    })
    syncDraftFromAccessInfo()
    editingKeys.value = false
    ElMessage.success(generate ? '已生成并保存新 key' : 'MCP key 已保存')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || 'MCP key 保存失败')
  } finally {
    savingKeys.value = false
  }
}

onMounted(async () => {
  try {
    accessInfo.value = await apiGet<McpAccessInfo>('/admin/mcp/access-info')
    syncDraftFromAccessInfo()
  } catch {
    accessInfo.value = { has_key: false, primary_key: '', keys: [], auth_header: '', source: 'none' }
    syncDraftFromAccessInfo()
  }

  let inprocessTools: ToolItem[] = []
  try {
    const data = await apiGet<any>('/admin/mcp/tools')
    inprocessTools = Array.isArray(data?.tools) ? data.tools : []
    services.value[0].tools = inprocessTools.length
    services.value[0].status = inprocessTools.length ? 'online' : 'missing'
  } catch {
    services.value[0].status = 'pending'
  }

  try {
    const triage = await apiGet<any>('/admin/mcp/support-triage-tools')
    const triageTools = Array.isArray(triage?.tools) ? triage.tools : []
    services.value[1].tools = triageTools.length
    services.value[1].status = triageTools.length ? 'online' : 'missing'
  } catch {
    const triageFromInprocess = inprocessTools.filter((tool) => tool?.name === SUPPORT_TRIAGE_TOOL_NAME)
    services.value[1].tools = triageFromInprocess.length
    services.value[1].status = triageFromInprocess.length ? 'online' : 'pending'
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

.auth-header-text {
  overflow: visible !important;
  white-space: normal !important;
  overflow-wrap: anywhere;
  line-height: 1.45;
  font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace);
  font-size: 12px !important;
}

.icon-copy,
.copy-button,
.danger-button,
.secondary-button,
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

.copy-button:disabled,
.secondary-button:disabled {
  cursor: not-allowed;
  opacity: 0.65;
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

.danger-button,
.secondary-button {
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

.secondary-button:hover {
  background: var(--brand-soft);
  color: var(--brand);
  border-color: var(--brand-ring);
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

.key-config-row {
  grid-column: 1 / -1;
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

.warn-text {
  color: var(--warn) !important;
}

.muted-text {
  color: var(--text-3) !important;
}

.key-value {
  overflow: visible !important;
  white-space: normal !important;
  overflow-wrap: anywhere;
  font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace);
  font-size: 12px !important;
  line-height: 1.45;
}

.key-editor {
  width: 100%;
  min-height: 92px;
  margin-top: 8px;
  resize: vertical;
  border: 1px solid var(--line);
  border-radius: var(--r-2, 6px);
  background: var(--surface);
  color: var(--text);
  padding: 9px 10px;
  font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace);
  font-size: 12px;
  line-height: 1.55;
  outline: none;
}

.key-editor:focus {
  border-color: var(--brand-ring);
  box-shadow: 0 0 0 3px var(--brand-soft);
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
html[data-theme="dark"] .secondary-button,
html[data-theme="dark"] .ghost-button {
  background: var(--surface);
}
html[data-theme="dark"] .key-grid div {
  background: var(--surface);
}
html[data-theme="dark"] .key-editor {
  background: var(--surface);
}
html[data-theme="dark"] .headers-panel pre {
  background: var(--surface-3);
}
</style>
