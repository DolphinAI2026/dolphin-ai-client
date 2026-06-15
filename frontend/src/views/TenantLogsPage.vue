<template>
  <BuilderFrame :breadcrumbs="[{ label: '租户日志分析' }]">
    <main class="tenant-log-page builder-page">
      <section class="tenant-log-header page-head" aria-label="租户日志分析">
        <div>
          <h1 class="page-title">租户日志分析</h1>
          <p class="page-subtitle">基于低代码租户操作日志，查看发布、权限、自开发和关键配置变更。</p>
        </div>
        <button class="tenant-log-refresh" type="button" :disabled="loading" @click="reload">
          <AppIcon name="refresh" :size="14" />
          <span>刷新</span>
        </button>
      </section>

      <section class="tenant-log-toolbar" aria-label="日志筛选">
        <el-input
          v-model="keyword"
          class="tenant-log-search"
          clearable
          size="small"
          placeholder="搜索操作对象"
          @keyup.enter="reload"
        />
        <el-select v-model="operationType" class="tenant-log-select" size="small" placeholder="操作类型">
          <el-option label="全部操作" value="all" />
          <el-option v-for="type in operationTypes" :key="type.value" :label="type.label" :value="type.value" />
        </el-select>
        <el-select v-model="functionMenu" class="tenant-log-select" size="small" placeholder="功能菜单">
          <el-option label="全部菜单" value="all" />
          <el-option v-for="menu in functionMenus" :key="menu.value" :label="menu.label" :value="menu.value" />
        </el-select>
        <button class="tenant-log-query" type="button" :disabled="loading" @click="reload">查询</button>
      </section>

      <section class="tenant-log-analysis" aria-label="低代码变更洞察">
        <div class="analysis-copy">
          <span>低代码变更洞察</span>
          <strong>{{ analysis?.summary || '暂无低代码日志分析结果' }}</strong>
        </div>
        <div class="analysis-metrics">
          <div>
            <span>日志</span>
            <strong>{{ totalCount }}</strong>
          </div>
          <div>
            <span>风险</span>
            <strong>{{ analysis?.risk_total || 0 }}</strong>
          </div>
          <div>
            <span>高风险</span>
            <strong>{{ analysis?.high_risk_total || 0 }}</strong>
          </div>
        </div>
      </section>

      <section class="tenant-log-content">
        <div v-if="loading" class="tenant-log-state">
          <div class="tenant-log-spinner" />
          <span>正在读取租户日志...</span>
        </div>
        <div v-else-if="error" class="tenant-log-state is-error">
          <AppIcon name="warning" :size="16" />
          <span>{{ error }}</span>
        </div>
        <div v-else-if="items.length === 0" class="tenant-log-state">
          <AppIcon name="clipboard" :size="28" />
          <span>当前条件下暂无低代码租户日志</span>
        </div>

        <div v-else class="tenant-log-table">
          <div class="tenant-log-table-head">
            <span>时间</span>
            <span>类型</span>
            <span>功能菜单</span>
            <span>操作对象</span>
            <span>操作描述</span>
            <span>操作人</span>
            <span>风险</span>
          </div>
          <div v-for="item in items" :key="item.id || item.timestamp + item.summary" class="tenant-log-row">
            <span class="mono">{{ formatTime(item.timestamp) }}</span>
            <span><em class="type-chip">{{ item.type || '操作' }}</em></span>
            <span>{{ item.details?.function_menu || '-' }}</span>
            <span class="truncate" :title="item.details?.operation_object">{{ item.details?.operation_object || '-' }}</span>
            <span class="truncate" :title="item.details?.operation_description">{{ item.details?.operation_description || item.summary }}</span>
            <span>{{ item.user || '系统' }}</span>
            <span><em class="risk-chip" :data-risk="item.details?.risk_level">{{ riskLabel(item.details?.risk_level) }}</em></span>
          </div>
        </div>
      </section>
    </main>
  </BuilderFrame>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import BuilderFrame from '@/components/BuilderFrame.vue'
import AppIcon from '@/components/common/AppIcon.vue'
import request from '@/utils/request'
import type { LogItem } from '@/components/v3/logsPanelData'

const operationTypes = [
  { label: '登录', value: 'LOGIN' },
  { label: '登出', value: 'LOGIN_OUT' },
  { label: '新增', value: 'ADD' },
  { label: '编辑', value: 'EDIT' },
  { label: '删除', value: 'DELETE' },
  { label: '启用', value: 'ENABLE' },
  { label: '禁用', value: 'DISABLE' },
  { label: '导入', value: 'IMPORT' },
  { label: '下载', value: 'DOWNLOAD' },
  { label: '开启', value: 'OPEN' },
  { label: '关闭', value: 'CLOSE' }
]
const functionMenus = [
  { label: '登录模块', value: 'LOGIN_MODULE' },
  { label: '自开发管理', value: 'SELF_DEVELOPMENT_MANAGEMENT' },
  { label: '应用管理', value: 'APPLICATION_MANAGEMENT' },
  { label: '角色管理', value: 'ROLE_MANAGEMENT' },
  { label: '菜单功能', value: 'APP_MENU' },
  { label: '访问权限', value: 'APP_ACCESS' },
  { label: '自开发配置', value: 'SELF_DEVELOPMENT_CONFIGURATION' },
  { label: '业务事件', value: 'BUSINESS_EVENT' }
]

const keyword = ref('')
const operationType = ref('all')
const functionMenu = ref('all')
const items = ref<LogItem[]>([])
const analysis = ref<any | null>(null)
const totalCount = ref(0)
const loading = ref(false)
const error = ref('')

async function reload() {
  loading.value = true
  error.value = ''
  try {
    const params: Record<string, string | number> = { page: 1, page_size: 50 }
    if (keyword.value.trim()) params.keyword = keyword.value.trim()
    if (operationType.value !== 'all') params.operation_type = operationType.value
    if (functionMenu.value !== 'all') params.function_menu = functionMenu.value
    const resp = await request.get<any, any>('/tenant-logs', { params })
    if (!resp?.ok) throw new Error(resp?.message || '读取日志失败')
    items.value = resp.items || []
    analysis.value = resp.analysis || null
    totalCount.value = Number(resp.total || items.value.length)
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '读取日志失败'
    items.value = []
    analysis.value = null
    totalCount.value = 0
  } finally {
    loading.value = false
  }
}

function formatTime(ts?: string) {
  if (!ts) return '-'
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ts
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function riskLabel(risk?: string) {
  if (risk === 'high') return '高风险'
  if (risk === 'medium') return '需关注'
  return '正常'
}

watch([operationType, functionMenu], () => reload())
onMounted(() => reload())
</script>

<style scoped>
.tenant-log-page {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 28px 36px;
  color: var(--text);
  overflow: hidden;
}
.tenant-log-header,
.tenant-log-toolbar,
.tenant-log-analysis,
.tenant-log-content {
  border: 1px solid var(--line);
  background: var(--surface);
  border-radius: 8px;
}
.tenant-log-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 24px 28px;
}
.tenant-log-refresh,
.tenant-log-query {
  height: 34px;
  border: 1px solid var(--brand);
  border-radius: 6px;
  background: var(--brand);
  color: white;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 14px;
  cursor: pointer;
}
.tenant-log-refresh:disabled,
.tenant-log-query:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.tenant-log-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 18px;
}
.tenant-log-search { max-width: 340px; }
.tenant-log-select { width: 160px; }
.tenant-log-analysis {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 16px 18px;
}
.analysis-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.analysis-copy span,
.analysis-metrics span {
  color: var(--text-3);
  font-size: 12px;
}
.analysis-copy strong {
  color: var(--text);
  font-size: 14px;
  font-weight: 500;
}
.analysis-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(86px, 1fr));
  gap: 8px;
}
.analysis-metrics div {
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface-2);
}
.analysis-metrics strong {
  display: block;
  margin-top: 3px;
  font-size: 18px;
}
.tenant-log-content {
  flex: 1;
  min-height: 0;
  overflow: auto;
}
.tenant-log-state {
  height: 100%;
  min-height: 260px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--text-3);
  font-size: 13px;
}
.tenant-log-state.is-error { color: var(--err); }
.tenant-log-spinner {
  width: 18px;
  height: 18px;
  border: 2px solid var(--line-strong);
  border-top-color: var(--brand);
  border-radius: 50%;
  animation: tenant-log-spin 0.8s linear infinite;
}
@keyframes tenant-log-spin { to { transform: rotate(360deg); } }
.tenant-log-table {
  min-width: 980px;
}
.tenant-log-table-head,
.tenant-log-row {
  display: grid;
  grid-template-columns: 110px 82px 126px minmax(180px, 1.2fr) minmax(240px, 1.5fr) 96px 86px;
  align-items: center;
  gap: 12px;
}
.tenant-log-table-head {
  position: sticky;
  top: 0;
  z-index: 1;
  padding: 12px 18px;
  background: var(--surface-2);
  color: var(--text-3);
  border-bottom: 1px solid var(--line);
  font-size: 12px;
  font-weight: 500;
}
.tenant-log-row {
  padding: 13px 18px;
  border-bottom: 1px solid var(--line);
  font-size: 13px;
}
.tenant-log-row:hover { background: var(--surface-2); }
.mono {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-3);
}
.truncate {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.type-chip,
.risk-chip {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 8px;
  border-radius: 999px;
  font-style: normal;
  font-size: 12px;
}
.type-chip {
  color: var(--brand);
  background: var(--brand-soft);
}
.risk-chip { color: var(--ok); background: var(--ok-soft); }
.risk-chip[data-risk='medium'] { color: var(--warn); background: var(--warn-soft); }
.risk-chip[data-risk='high'] { color: var(--err); background: var(--err-soft); }
</style>
