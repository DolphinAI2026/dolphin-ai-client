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
.platform-page {
  max-width: 1440px;
  margin: 0 auto;
  padding: 8px 0 56px;
  color: #17162f;
}

.platform-hero {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 24px;
}

h1 {
  margin: 0;
  font-size: 32px;
  line-height: 1.2;
  font-weight: 820;
}

.platform-hero p {
  max-width: 980px;
  margin: 16px 0 0;
  color: #5f5a7c;
  font-size: 16px;
  line-height: 1.7;
}

.refresh-button {
  height: 42px;
  padding: 0 18px;
  border: 0;
  border-radius: 9px;
  font-weight: 760;
  background: linear-gradient(180deg, #766bf1, #5750d8);
  box-shadow: 0 14px 28px rgba(87, 80, 216, 0.24);
}

.overview-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 18px;
  margin-bottom: 24px;
}

.overview-card {
  min-height: 104px;
  display: grid;
  grid-template-columns: 52px minmax(0, 1fr) auto;
  align-items: center;
  gap: 16px;
  padding: 20px;
  border: 1px solid #ded9eb;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 10px 24px rgba(34, 30, 70, 0.07);
}

.card-icon {
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
  border-radius: 9px;
  font-size: 18px;
}

.tone-green { color: #13a778; background: #eaf8f3; }
.tone-purple { color: #5750d8; background: #efedff; }
.tone-blue { color: #1889c7; background: #eaf5ff; }
.tone-orange { color: #dd7a13; background: #fff1e5; }

.overview-card h2 {
  margin: 0 0 6px;
  color: #17162f;
  font-size: 18px;
  font-weight: 820;
}

.overview-card p {
  margin: 0;
  color: #8a85a5;
  font-size: 14px;
}

.card-value {
  justify-self: end;
  padding: 4px 10px;
  border: 1px solid #e2def0;
  border-radius: 8px;
  color: #625d82;
  background: #fff;
  font-weight: 760;
  white-space: nowrap;
}

.service-panel,
.activity-panel {
  overflow: hidden;
  border: 1px solid #ded9eb;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 10px 24px rgba(34, 30, 70, 0.07);
}

.table-head,
.service-row {
  display: grid;
  grid-template-columns: minmax(260px, 1.25fr) 160px 140px minmax(320px, 1fr) 96px;
  align-items: center;
  gap: 18px;
}

.table-head {
  height: 54px;
  padding: 0 24px;
  color: #8a85a5;
  background: #f3f0fb;
  font-size: 14px;
  font-weight: 760;
}

.service-row {
  min-height: 76px;
  padding: 14px 24px;
  border-top: 1px solid #ece8f6;
}

.service-row strong {
  color: #17162f;
  font-size: 16px;
  font-weight: 820;
}

.service-row p {
  margin: 6px 0 0;
  color: #8a85a5;
  font-size: 13px;
}

.status-pill {
  width: max-content;
  padding: 4px 10px;
  border-radius: 7px;
  font-size: 13px;
  font-weight: 760;
}

.status-pill.connected {
  color: #159f78;
  background: #effaf7;
}

.status-pill.warning {
  color: #f04444;
  background: #fff0f0;
}

.status-pill.disabled {
  color: #dd7a13;
  background: #fff1e5;
}

.tool-count {
  color: #625d82;
  font-weight: 720;
}

code {
  min-width: 0;
  overflow: hidden;
  color: #7a719d;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row-actions {
  display: flex;
  justify-content: flex-end;
  gap: 4px;
}

.activity-panel {
  margin-top: 24px;
  padding: 24px;
}

.section-title {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 18px;
}

.section-title strong {
  font-size: 18px;
}

.section-title span {
  color: #8a85a5;
  font-size: 13px;
}

.activity-list {
  display: grid;
}

.activity-item {
  display: grid;
  grid-template-columns: 52px 4px minmax(0, 1fr);
  gap: 18px;
  min-height: 58px;
  padding: 10px 0;
  border-top: 1px solid #ece8f6;
}

.activity-item:first-child {
  border-top: 0;
}

.activity-time {
  color: #7a719d;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.activity-mark {
  width: 4px;
  border-radius: 99px;
  background: #5750d8;
}

.activity-mark.green { background: #1fb994; }
.activity-mark.blue { background: #1f9be0; }
.activity-mark.purple { background: #5750d8; }

.activity-item strong {
  color: #17162f;
  font-size: 15px;
}

.activity-item p {
  margin: 6px 0 0;
  color: #8a85a5;
  font-size: 13px;
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
</style>
