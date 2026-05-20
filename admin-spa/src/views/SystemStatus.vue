<template>
  <div class="platform-page">
    <section class="platform-hero">
      <div>
        <h1>平台管理</h1>
        <p>复用当前管理后台：MCP 服务、平台环境、模型、成员和租户都在这里配置，Builder 前台只消费配置结果。</p>
      </div>
      <el-button type="primary" class="refresh-button" :loading="loading" @click="load">
        刷新状态
      </el-button>
    </section>

    <section class="overview-grid">
      <article v-for="card in cards" :key="card.title" class="overview-card">
        <div class="card-icon" :class="card.tone">
          <el-icon><component :is="card.icon" /></el-icon>
        </div>
        <div>
          <h2>{{ card.title }}</h2>
          <p>{{ card.desc }}</p>
        </div>
        <span class="card-value">{{ card.value }}</span>
      </article>
    </section>

    <section class="service-panel">
      <div class="table-head">
        <span>MCP 服务</span>
        <span>状态</span>
        <span>工具数</span>
        <span>接入地址</span>
        <span></span>
      </div>
      <div v-for="service in services" :key="service.code" class="service-row">
        <div>
          <strong>{{ service.name }}</strong>
          <p>{{ service.desc }}</p>
        </div>
        <span class="status-pill" :class="service.status">{{ service.statusText }}</span>
        <span class="tool-count">{{ service.tools }} 工具</span>
        <code>{{ service.publicUrl }}</code>
        <div class="row-actions">
          <el-button text size="small" @click="openTester(service.code)">
            <el-icon><VideoPlay /></el-icon>
          </el-button>
          <el-button text size="small" @click="copy(service.publicUrl)">
            <el-icon><CopyDocument /></el-icon>
          </el-button>
        </div>
      </div>
    </section>

    <section class="activity-panel">
      <div class="section-title">
        <strong>最近活动</strong>
        <span>实时</span>
      </div>
      <div class="activity-list">
        <div v-for="item in activities" :key="item.title" class="activity-item">
          <span class="activity-time">{{ item.time }}</span>
          <div :class="['activity-mark', item.tone]"></div>
          <div>
            <strong>{{ item.title }}</strong>
            <p>{{ item.meta }}</p>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, markRaw, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { API_BASE_URL, apiGet } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import {
  Cloudy,
  Connection,
  CopyDocument,
  Cpu,
  Lightning,
  Monitor,
  User,
  VideoPlay,
} from '@element-plus/icons-vue'

interface ServiceRow {
  name: string
  code: string
  desc: string
  publicUrl: string
  tools: number
  status: 'connected' | 'warning' | 'disabled'
  statusText: string
}

const router = useRouter()
const auth = useAuthStore()
const loading = ref(false)
const health = ref('')
const origin = window.location.origin

function resolvePublicMcpUrl(apiPath: string) {
  const apiBase = API_BASE_URL.replace(/\/+$/, '')
  if (apiPath.startsWith('/api/')) return `${origin}${apiBase}${apiPath.slice('/api'.length)}`
  return `${origin}${apiPath}`
}

const services: ServiceRow[] = [
  {
    name: '得帆云 aPaaS Tools',
    code: 'apaas-builder-mcp',
    desc: '官方 MCP，提供应用 / 模型 / 表单 / 权限 / 部署等工具。',
    publicUrl: resolvePublicMcpUrl('/api/mcp/mcp'),
    tools: 33,
    status: 'connected',
    statusText: '已连接',
  },
  {
    name: 'AI Builder 场景服务',
    code: 'apaas-builder-config',
    desc: '把需求、设计文档和上下文整理为可构建应用。',
    publicUrl: resolvePublicMcpUrl('/api/mcp-builder/mcp'),
    tools: 14,
    status: 'connected',
    statusText: '已连接',
  },
  {
    name: 'AI Coding 工作区',
    code: 'apaas-builder-coding',
    desc: '生成页面、组件和后端接口，并发布到组件市场。',
    publicUrl: resolvePublicMcpUrl('/api/mcp-coding/mcp'),
    tools: 23,
    status: 'connected',
    statusText: '已连接',
  },
  {
    name: 'Vibe 开发服务',
    code: 'apaas-builder-vibe',
    desc: '提供代码工作区、变更应用和调试辅助能力。',
    publicUrl: resolvePublicMcpUrl('/api/mcp-vibe/mcp'),
    tools: 9,
    status: 'connected',
    statusText: '已连接',
  },
  {
    name: '设计解析服务',
    code: 'apaas-builder-design',
    desc: '解析设计稿、截图和文档，生成构建上下文。',
    publicUrl: resolvePublicMcpUrl('/api/mcp-design/mcp'),
    tools: 4,
    status: 'connected',
    statusText: '已连接',
  },
]

const totalTools = computed(() => services.reduce((sum, service) => sum + service.tools, 0))
const healthText = computed(() => (health.value === 'ok' ? '正常' : health.value ? '需检查' : '检查中'))

const cards = computed(() => [
  {
    title: '系统状态',
    desc: '后端、数据库、MCP 服务健康检查',
    value: healthText.value,
    tone: health.value === 'ok' ? 'tone-green' : 'tone-orange',
    icon: markRaw(Cloudy),
  },
  {
    title: 'MCP 服务',
    desc: 'aPaaS 工具、Builder、Coding、设计解析',
    value: `${services.length} 个`,
    tone: 'tone-purple',
    icon: markRaw(Connection),
  },
  {
    title: 'MCP 测试',
    desc: '按服务调试工具调用，查看输入输出',
    value: '可用',
    tone: 'tone-blue',
    icon: markRaw(Lightning),
  },
  {
    title: '租户管理',
    desc: 'aPaaS 租户、管理员、启停状态',
    value: '同步',
    tone: 'tone-green',
    icon: markRaw(Monitor),
  },
  {
    title: 'LLM 配置',
    desc: '供应商、模型、API Key、默认模型',
    value: '1 个',
    tone: 'tone-purple',
    icon: markRaw(Cpu),
  },
  {
    title: '用户与租户',
    desc: '成员、角色、租户和启停状态',
    value: auth.user?.username || 'admin',
    tone: 'tone-orange',
    icon: markRaw(User),
  },
])

const activities = computed(() => [
  { time: '14:23', title: `MCP 服务 ${services[0].name} 可用`, meta: `共 ${totalTools.value} 个工具 · ${auth.user?.username || 'admin'}`, tone: 'green' },
  { time: '13:50', title: '模型配置已同步到 Builder 前台', meta: 'Default Tenant · admin', tone: 'purple' },
  { time: '11:02', title: '组件市场入口已连接 AI Coding', meta: 'AI Coding · 组件发布', tone: 'blue' },
])

async function load() {
  loading.value = true
  try {
    const resp = await apiGet<{ status: string }>('/health').catch(() => null)
    health.value = resp?.status || 'unreachable'
  } finally {
    loading.value = false
  }
}

function openTester(serviceCode: string) {
  router.push({ path: '/tester', query: { service: serviceCode } })
}

async function copy(value: string) {
  await navigator.clipboard.writeText(value).catch(() => null)
  ElMessage.success('接入地址已复制')
}

onMounted(load)
</script>

<style scoped>
/* v3 redesign · 2026-05-20 — visual refresh only, template/script untouched.
   Tokens: design-v3-tokens.css. Tone classes (script-bound) mapped to v3 soft palettes.
   Preserved semantic colors:
     - connected → ok (green = state)
     - warning → err (red = state)
     - disabled → warn (amber = state)
     - activity.green/blue/purple → ok/info/brand (state markers, not decoration) */
.platform-page {
  max-width: 1440px;
  margin: 0 auto;
  padding: 8px 0 56px;
  color: var(--text);
  font-family: var(--font-sans);
}

.platform-hero {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 22px;
}

h1 {
  margin: 0;
  font-size: 22px;
  line-height: 1.25;
  font-weight: var(--fw-bold, 700);
  color: var(--text);
  letter-spacing: -0.01em;
}

.platform-hero p {
  max-width: 980px;
  margin: 8px 0 0;
  color: var(--text-3);
  font-size: 13.5px;
  line-height: 1.55;
}

.refresh-button {
  height: 32px;
  padding: 0 14px;
  border: 0;
  border-radius: var(--r-2, 6px);
  font-size: 12.5px;
  font-weight: 600;
  background: var(--brand);
  color: var(--text-inverse, #fff);
  box-shadow: none;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.refresh-button:hover,
.refresh-button:focus {
  background: var(--brand-hover);
}

.overview-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.overview-card {
  min-height: auto;
  display: grid;
  grid-template-columns: 38px minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  border: 1px solid var(--line);
  border-radius: var(--r-4, 12px);
  background: var(--surface);
  box-shadow: var(--sh-1);
}

.card-icon {
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  border-radius: var(--r-3, 8px);
  font-size: 17px;
}

/* Tone classes — script emits tone-green/purple/blue/orange. Map to v3 soft palettes.
   Green/orange keep their semantic meaning (ok/warn). Purple/blue both map to brand-soft
   since v3 has only one brand color. */
.tone-green { color: var(--ok); background: var(--ok-soft); }
.tone-purple { color: var(--brand); background: var(--brand-soft); }
.tone-blue { color: var(--brand); background: var(--brand-soft); }
.tone-orange { color: var(--warn); background: var(--warn-soft); }

.overview-card h2 {
  margin: 0 0 3px;
  color: var(--text);
  font-size: 14px;
  font-weight: 600;
  letter-spacing: -0.005em;
}

.overview-card p {
  margin: 0;
  color: var(--text-3);
  font-size: 12px;
  line-height: 1.4;
}

.card-value {
  justify-self: end;
  padding: 3px 9px;
  border: 1px solid var(--line);
  border-radius: var(--r-1, 4px);
  color: var(--text-2);
  background: var(--surface);
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

.service-panel,
.activity-panel {
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: var(--r-4, 12px);
  background: var(--surface);
  box-shadow: var(--sh-1);
}

.table-head,
.service-row {
  display: grid;
  grid-template-columns: minmax(260px, 1.25fr) 160px 140px minmax(320px, 1fr) 96px;
  align-items: center;
  gap: 16px;
}

.table-head {
  height: 46px;
  padding: 0 18px;
  color: var(--text-3);
  background: var(--surface);
  border-bottom: 1px solid var(--line);
  font-size: 10.5px;
  font-weight: 500;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.service-row {
  min-height: 68px;
  padding: 12px 18px;
  border-top: 1px solid var(--line);
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.service-row:hover {
  background: var(--surface-2);
}

.service-row strong {
  color: var(--text);
  font-size: 13.5px;
  font-weight: 600;
  letter-spacing: -0.005em;
}

.service-row p {
  margin: 3px 0 0;
  color: var(--text-3);
  font-size: 12px;
  line-height: 1.4;
}

.status-pill {
  width: max-content;
  padding: 2px 7px;
  border-radius: var(--r-1, 4px);
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.status-pill.connected {
  color: var(--ok);
  background: var(--ok-soft);
}

.status-pill.warning {
  color: var(--err);
  background: var(--err-soft);
}

.status-pill.disabled {
  color: var(--warn);
  background: var(--warn-soft);
}

.tool-count {
  color: var(--text-2);
  font-size: 12px;
  font-weight: 500;
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

.row-actions {
  display: flex;
  justify-content: flex-end;
  gap: 4px;
}

.row-actions :deep(.el-button) {
  color: var(--text-2);
}
.row-actions :deep(.el-button:hover) {
  color: var(--brand);
  background: var(--brand-soft);
}

.activity-panel {
  margin-top: 16px;
  padding: 18px;
}

.section-title {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 14px;
}

.section-title strong {
  font-size: 13.5px;
  color: var(--text);
  font-weight: 600;
}

.section-title span {
  color: var(--text-3);
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.activity-list {
  display: grid;
}

.activity-item {
  display: grid;
  grid-template-columns: 52px 4px minmax(0, 1fr);
  gap: 14px;
  min-height: 54px;
  padding: 10px 0;
  border-top: 1px solid var(--line);
}

.activity-item:first-child {
  border-top: 0;
}

.activity-time {
  color: var(--text-3);
  font-family: var(--font-mono, 'JetBrains Mono', ui-monospace, monospace);
  font-size: 11px;
}

.activity-mark {
  width: 4px;
  border-radius: var(--r-full, 999px);
  background: var(--brand);
}

/* Activity tone markers — script emits green/blue/purple. State semantic mapping. */
.activity-mark.green { background: var(--ok); }
.activity-mark.blue { background: var(--info); }
.activity-mark.purple { background: var(--brand); }

.activity-item strong {
  color: var(--text);
  font-size: 13px;
  font-weight: 600;
}

.activity-item p {
  margin: 3px 0 0;
  color: var(--text-3);
  font-size: 12px;
  line-height: 1.4;
}

@media (max-width: 1180px) {
  .overview-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .table-head {
    display: none;
  }

  .service-row {
    grid-template-columns: 1fr;
    align-items: start;
  }

  .row-actions {
    justify-content: flex-start;
  }
}

@media (max-width: 760px) {
  .platform-hero {
    align-items: flex-start;
    flex-direction: column;
  }

  .overview-grid {
    grid-template-columns: 1fr;
  }
}

/* Dark theme overrides */
html[data-theme="dark"] .overview-card,
html[data-theme="dark"] .service-panel,
html[data-theme="dark"] .activity-panel {
  background: var(--surface);
  border-color: var(--line);
}
html[data-theme="dark"] .table-head {
  background: var(--surface);
}
html[data-theme="dark"] .service-row:hover {
  background: var(--surface-2);
}
html[data-theme="dark"] .card-value {
  background: var(--surface);
}
</style>
