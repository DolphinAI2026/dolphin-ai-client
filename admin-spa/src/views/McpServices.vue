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
        <div class="summary-label">服务入口</div>
        <div class="summary-value-row">
          <strong>{{ services.length }} 个 MCP 服务</strong>
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
          <span class="tool-count">{{ service.tools }}</span>
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
        <button type="button" class="copy-button" @click="copyText(requestExample, '接入参数已复制')">
          <el-icon><CopyDocument /></el-icon>
          复制
        </button>
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
          <button type="button" class="copy-button" @click="onCopyKey">
            <el-icon><CopyDocument /></el-icon>
            复制凭证
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
import { computed, onMounted, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CopyDocument } from '@element-plus/icons-vue'
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

const authHeaderText = computed(() => currentKey.value ? `Authorization: Bearer ${currentKey.value}` : 'Authorization: Bearer <MCP_API_KEY>')
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
.mcp-page {
  max-width: 1440px;
  margin: 0 auto;
  padding: 8px 0 56px;
  color: #17162f;
}

.mcp-hero {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 22px;
}

h1 {
  margin: 0;
  font-size: 32px;
  line-height: 1.2;
  font-weight: 820;
}

.mcp-hero p {
  max-width: 940px;
  margin: 14px 0 0;
  color: #5f5a7c;
  font-size: 16px;
  line-height: 1.7;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 18px;
  margin-bottom: 20px;
}

.summary-card,
.service-panel,
.headers-panel,
.key-panel {
  border: 1px solid #ded9eb;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 10px 24px rgba(34, 30, 70, 0.07);
}

.summary-card {
  min-width: 0;
  min-height: 94px;
  padding: 20px 22px;
}

.summary-label {
  color: #8a85a5;
  font-size: 13px;
  font-weight: 720;
}

.summary-value-row {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
}

.summary-value-row strong {
  min-width: 0;
  overflow: hidden;
  color: #17162f;
  font-size: 16px;
  font-weight: 820;
  text-overflow: ellipsis;
  white-space: nowrap;
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
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  border: 1px solid #ded9eb;
  border-radius: 9px;
  color: #5750d8;
  background: #fff;
}

.icon-copy:hover {
  background: #eeeaff;
}

.service-panel,
.headers-panel,
.key-panel {
  overflow: hidden;
  margin-top: 20px;
}

.panel-head {
  min-height: 62px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 0 22px;
  border-bottom: 1px solid #ece8f6;
  background: #f3f0fb;
}

.panel-head strong {
  color: #17162f;
  font-size: 17px;
  font-weight: 820;
}

.panel-head span {
  margin-left: 10px;
  color: #8a85a5;
  font-size: 13px;
  font-weight: 700;
}

.service-table {
  padding: 0 22px 20px;
}

.table-head,
.service-row {
  display: grid;
  grid-template-columns: minmax(180px, 1fr) 150px minmax(360px, 1.5fr) 86px 96px 124px;
  align-items: center;
  gap: 16px;
}

.table-head {
  height: 54px;
  color: #8a85a5;
  font-size: 14px;
  font-weight: 760;
}

.service-row {
  min-height: 74px;
  padding: 12px 14px;
  border-top: 1px solid #ece8f6;
  border-radius: 12px;
}

.service-row:hover {
  background: #fbfaff;
}

.service-name {
  color: #17162f;
  font-size: 15px;
  font-weight: 820;
}

.service-code {
  margin-top: 5px;
  color: #8a85a5;
  font-size: 12px;
}

.transport,
.tool-count {
  color: #625d82;
  font-weight: 700;
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
  color: #7a719d;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-pill {
  width: max-content;
  padding: 4px 10px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 760;
}

.status-pill.online {
  color: #159f78;
  background: #effaf7;
}

.test-button,
.copy-button {
  min-height: 36px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 0 13px;
  border-radius: 9px;
  color: #fff;
  background: linear-gradient(180deg, #766bf1, #5750d8);
  font-size: 13px;
  font-weight: 760;
  box-shadow: 0 10px 22px rgba(87, 80, 216, 0.18);
}

.danger-button {
  min-height: 36px;
  padding: 0 13px;
  border: 1px solid #f3d4d4;
  border-radius: 9px;
  color: #d93d3d;
  background: #fff;
  font-size: 13px;
  font-weight: 760;
}

.headers-panel pre {
  margin: 0;
  white-space: pre-wrap;
  color: #d7ffe8;
  background: #17211d;
  padding: 22px;
  line-height: 1.8;
}

.panel-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.key-grid {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) minmax(140px, 0.6fr) minmax(320px, 1.4fr);
  gap: 16px;
  padding: 22px;
}

.key-grid div {
  min-width: 0;
  padding: 16px;
  border: 1px solid #ece8f6;
  border-radius: 12px;
  background: #fbfaff;
}

.key-grid span {
  display: block;
  color: #8a85a5;
  font-size: 13px;
  font-weight: 720;
}

.key-grid strong {
  display: block;
  margin-top: 8px;
  overflow: hidden;
  color: #17162f;
  font-size: 16px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.success-text {
  color: #159f78 !important;
}

.key-grid p {
  margin: 0;
  align-self: center;
  color: #625d82;
  font-size: 14px;
  line-height: 1.7;
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
</style>
