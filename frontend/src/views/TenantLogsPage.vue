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

      <section class="tenant-log-overview" aria-label="低代码变更洞察">
        <div class="kpi-strip">
          <div class="kpi">
            <span>日志总数</span>
            <strong>{{ totalCount }}</strong>
          </div>
          <div class="kpi">
            <span>需关注（本页）</span>
            <strong class="is-warn">{{ analysis?.risk_total || 0 }}</strong>
          </div>
          <div class="kpi">
            <span>高风险（本页）</span>
            <strong class="is-err">{{ analysis?.high_risk_total || 0 }}</strong>
          </div>
          <div class="kpi">
            <span>变更域（本页）</span>
            <strong>{{ changeDomains.length }}</strong>
          </div>
        </div>
        <div class="overview-summary">
          <span class="overview-label">低代码变更洞察</span>
          <p>{{ analysis?.summary || '暂无低代码日志分析结果' }}</p>
          <div v-if="totalCount > items.length" class="overview-note">风险与洞察基于当前页统计，分页查看下一页会刷新。</div>
          <div v-if="changeDomains.length" class="domain-strip" aria-label="变更域">
            <em v-for="domain in changeDomains" :key="domain.key">{{ domain.label }} {{ domain.count }}</em>
          </div>
        </div>
      </section>

      <section class="tenant-log-toolbar" aria-label="日志筛选">
        <el-input
          v-model="keyword"
          class="tenant-log-search"
          clearable
          size="small"
          placeholder="搜索操作对象"
          @input="onKeywordInput"
          @keyup.enter="applyFilters"
        />
        <el-select v-model="operationType" class="tenant-log-select" size="small" placeholder="操作类型" @change="applyFilters">
          <el-option label="全部操作" value="all" />
          <el-option v-for="type in operationTypes" :key="type.value" :label="type.label" :value="type.value" />
        </el-select>
        <el-select v-model="functionMenu" class="tenant-log-select" size="small" placeholder="功能菜单" @change="applyFilters">
          <el-option label="全部菜单" value="all" />
          <el-option v-for="menu in functionMenus" :key="menu.value" :label="menu.label" :value="menu.value" />
        </el-select>
        <button class="tenant-log-query" type="button" :disabled="loading" @click="applyFilters">查询</button>
        <button class="tenant-log-reset" type="button" :disabled="loading" @click="resetFilters">重置</button>
      </section>

      <div class="tenant-log-body">
        <section class="tenant-log-table-card" aria-label="日志明细">
          <div class="card-head">
            <h2>日志明细</h2>
            <span v-if="!error">共 {{ totalCount }} 条 · 点击行查看详情</span>
          </div>

          <div v-if="error" class="tenant-log-state is-error">
            <AppIcon name="warning" :size="16" />
            <span>{{ error }}</span>
          </div>

          <template v-else>
            <div class="tenant-log-table-scroll">
              <el-table
                v-loading="loading"
                :data="items"
                class="tenant-log-table"
                height="100%"
                row-key="id"
                :empty-text="loading ? '正在读取租户日志…' : '当前条件下暂无低代码租户日志'"
                @row-click="openDetail"
              >
                <el-table-column label="时间" width="150">
                  <template #default="{ row }">
                    <span class="mono">{{ formatTime(row.timestamp) }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="类型" width="92">
                  <template #default="{ row }">
                    <el-tag size="small" type="primary" effect="light">{{ row.type || '操作' }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="功能菜单" min-width="128">
                  <template #default="{ row }">{{ row.details?.function_menu || '-' }}</template>
                </el-table-column>
                <el-table-column label="操作对象" min-width="180" show-overflow-tooltip>
                  <template #default="{ row }">{{ row.details?.operation_object || '-' }}</template>
                </el-table-column>
                <el-table-column label="操作描述" min-width="220" show-overflow-tooltip>
                  <template #default="{ row }">{{ row.details?.operation_description || row.summary }}</template>
                </el-table-column>
                <el-table-column label="操作人" width="116">
                  <template #default="{ row }">{{ row.user || '系统' }}</template>
                </el-table-column>
                <el-table-column label="风险" width="92">
                  <template #default="{ row }">
                    <el-tag size="small" effect="light" :type="riskTagType(row.details?.risk_level)">
                      {{ riskLabel(row.details?.risk_level) }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="详情" width="72" align="center">
                  <template #default="{ row }">
                    <el-button link size="small" class="row-detail-btn" @click.stop="openDetail(row)">详情</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </div>

            <div class="tenant-log-pagination">
              <el-pagination
                :current-page="page"
                :page-size="pageSize"
                :total="totalCount"
                :page-sizes="[20, 50, 100, 200]"
                :pager-count="5"
                :disabled="loading"
                small
                layout="sizes, prev, pager, next, jumper"
                background
                @current-change="onPageChange"
                @size-change="onSizeChange"
              />
            </div>
          </template>
        </section>

        <aside class="insight-sidebar" aria-label="风险处置">
          <section class="insight-panel risk-panel" aria-label="风险看板">
            <div class="insight-head">
              <AppIcon name="shield" :size="15" />
              <h3>风险看板</h3>
            </div>
            <div v-if="riskItems.length" class="risk-list">
              <article v-for="item in riskItems" :key="item.id" class="risk-item">
                <em class="risk-chip" :data-risk="item.details?.risk_level">
                  {{ riskLabel(item.details?.risk_level) }}
                </em>
                <div>
                  <strong>{{ item.details?.operation_object || item.summary }}</strong>
                  <span>{{ item.details?.risk_reason || '关键变更' }} · {{ item.user || '系统' }}</span>
                </div>
              </article>
            </div>
            <div v-else class="insight-empty">暂无需关注风险</div>
          </section>

          <section class="insight-panel timeline-panel" aria-label="变更时间线">
            <div class="insight-head">
              <AppIcon name="clock" :size="15" />
              <h3>变更时间线</h3>
            </div>
            <div v-if="timeline.length" class="timeline-list">
              <article v-for="event in timeline" :key="event.id || event.time + event.title" class="timeline-event">
                <i :data-risk="event.risk_level" />
                <div>
                  <span>{{ formatTime(event.time) }} · {{ event.operator || '系统' }}</span>
                  <strong>{{ event.title }}</strong>
                  <p>{{ event.description || event.operation_type }}</p>
                </div>
              </article>
            </div>
            <div v-else class="insight-empty">暂无变更时间线</div>
          </section>

          <section class="insight-panel recommendation-panel" aria-label="处置建议">
            <div class="insight-head">
              <AppIcon name="check-circle" :size="15" />
              <h3>处置建议</h3>
            </div>
            <div v-if="recommendations.length" class="recommendation-list">
              <article
                v-for="recommendation in recommendations"
                :key="recommendation.key + recommendation.target"
                class="recommendation-item"
                :data-severity="recommendation.severity"
              >
                <em>{{ recommendationSeverityLabel(recommendation.severity) }}</em>
                <div>
                  <strong>{{ recommendation.title }}</strong>
                  <span>{{ recommendation.target }}</span>
                  <p>{{ recommendation.action || recommendation.description }}</p>
                </div>
              </article>
            </div>
            <div v-else class="insight-empty">暂无处置建议</div>
          </section>
        </aside>
      </div>
    </main>

    <el-drawer
      v-model="detailOpen"
      title="日志详情"
      size="460px"
      :append-to-body="true"
    >
      <div v-if="detailItem" class="log-detail">
        <div class="log-detail-risk">
          <el-tag size="small" effect="light" :type="riskTagType(detailItem.details?.risk_level)">
            {{ riskLabel(detailItem.details?.risk_level) }}
          </el-tag>
          <span>{{ detailItem.details?.risk_reason || '常规操作' }}</span>
        </div>
        <dl class="log-detail-fields">
          <div v-for="field in detailFields" :key="field.label">
            <dt>{{ field.label }}</dt>
            <dd>{{ field.value }}</dd>
          </div>
        </dl>
        <div v-if="detailRaw" class="log-detail-raw">
          <div class="log-detail-raw-head">原始记录</div>
          <pre>{{ detailRaw }}</pre>
        </div>
      </div>
    </el-drawer>
  </BuilderFrame>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import BuilderFrame from '@/components/BuilderFrame.vue'
import AppIcon from '@/components/common/AppIcon.vue'
import request from '@/utils/request'
import type { LogItem } from '@/components/v3/logsPanelData'

type ChangeDomain = {
  key: string
  label: string
  count: number
}

type TimelineEvent = {
  id?: string
  time?: string
  title: string
  description?: string
  operation_type?: string
  operator?: string
  risk_level?: string
}

type Recommendation = {
  key: string
  title: string
  target: string
  description?: string
  action?: string
  severity?: 'low' | 'medium' | 'high' | string
  evidence_id?: string
}

type TenantLogAnalysis = {
  summary?: string
  risk_total?: number
  high_risk_total?: number
  risk_items?: LogItem[]
  change_domains?: ChangeDomain[]
  timeline?: TimelineEvent[]
  recommendations?: Recommendation[]
}

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
const analysis = ref<TenantLogAnalysis | null>(null)
const totalCount = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const error = ref('')
const detailOpen = ref(false)
const detailItem = ref<LogItem | null>(null)

const changeDomains = computed(() => analysis.value?.change_domains || [])
const riskItems = computed(() => analysis.value?.risk_items || [])
const timeline = computed<TimelineEvent[]>(() => {
  if (analysis.value?.timeline?.length) return analysis.value.timeline
  return items.value.slice(0, 12).map((item) => ({
    id: item.id,
    time: item.timestamp,
    title: item.details?.operation_object || item.summary || '低代码操作',
    description: item.details?.operation_description || item.summary || item.type,
    operation_type: item.type,
    operator: item.user,
    risk_level: item.details?.risk_level || 'low',
  }))
})
const recommendations = computed<Recommendation[]>(() => {
  if (analysis.value?.recommendations?.length) return analysis.value.recommendations
  if (riskItems.value.length) {
    const firstRisk = riskItems.value[0]
    return [
      {
        key: 'review_risk',
        title: '先复核风险操作',
        target: firstRisk.details?.operation_object || firstRisk.summary || '低代码操作',
        description: firstRisk.details?.risk_reason || '需关注变更',
        action: '核对是否为预期操作，必要时回滚配置或补审批记录。',
        severity: firstRisk.details?.risk_level || 'medium',
        evidence_id: firstRisk.id,
      },
      {
        key: 'trace_timeline',
        title: '按时间线回溯',
        target: timeline.value[0]?.title || '最近变更',
        description: '查看该操作前后的发布、权限和自开发配置变化。',
        action: '从变更时间线第一条开始向后核对关联操作。',
        severity: 'medium',
        evidence_id: timeline.value[0]?.id,
      },
    ]
  }
  if (timeline.value.length) {
    return [
      {
        key: 'trace_latest',
        title: '从最新变更回溯',
        target: timeline.value[0].title,
        description: timeline.value[0].description,
        action: '结合日志明细确认该对象是否连续被修改。',
        severity: timeline.value[0].risk_level || 'low',
        evidence_id: timeline.value[0].id,
      },
    ]
  }
  return []
})

const detailFields = computed(() => {
  const item = detailItem.value
  if (!item) return []
  const details = item.details || {}
  return [
    { label: '时间', value: formatTime(item.timestamp) },
    { label: '操作类型', value: item.type || '-' },
    { label: '功能菜单', value: details.function_menu || '-' },
    { label: '操作对象', value: details.operation_object || item.summary || '-' },
    { label: '操作描述', value: details.operation_description || item.summary || '-' },
    { label: '操作人', value: item.user || '系统' },
    { label: '风险等级', value: riskLabel(details.risk_level) },
    { label: '风险原因', value: details.risk_reason || '-' },
    { label: '变更域', value: details.resource_label || '-' },
  ]
})
const detailRaw = computed(() => {
  const raw = detailItem.value?.details?.raw
  if (!raw) return ''
  try {
    return JSON.stringify(raw, null, 2)
  } catch {
    return String(raw)
  }
})

async function reload() {
  loading.value = true
  error.value = ''
  try {
    const params: Record<string, string | number> = { page: page.value, page_size: pageSize.value }
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

let keywordTimer: ReturnType<typeof setTimeout> | null = null

function clearKeywordTimer() {
  if (keywordTimer) {
    clearTimeout(keywordTimer)
    keywordTimer = null
  }
}

function onKeywordInput() {
  clearKeywordTimer()
  keywordTimer = setTimeout(() => {
    keywordTimer = null
    applyFilters()
  }, 400)
}

function applyFilters() {
  clearKeywordTimer()
  page.value = 1
  reload()
}

function resetFilters() {
  clearKeywordTimer()
  keyword.value = ''
  operationType.value = 'all'
  functionMenu.value = 'all'
  page.value = 1
  reload()
}

function onPageChange(next: number) {
  page.value = next
  reload()
}

function onSizeChange(size: number) {
  pageSize.value = size
  page.value = 1
  reload()
}

function openDetail(row: LogItem) {
  detailItem.value = row
  detailOpen.value = true
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

function riskTagType(risk?: string): 'danger' | 'warning' | 'success' {
  if (risk === 'high') return 'danger'
  if (risk === 'medium') return 'warning'
  return 'success'
}

function recommendationSeverityLabel(severity?: string) {
  if (severity === 'high') return '优先'
  if (severity === 'medium') return '关注'
  return '建议'
}

onMounted(() => reload())
</script>

<style scoped>
.tenant-log-page {
  height: 100%;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px 22px;
  color: var(--text);
  overflow: hidden;
}
.tenant-log-header,
.tenant-log-overview,
.tenant-log-toolbar,
.tenant-log-table-card,
.insight-panel {
  border: 1px solid var(--line);
  background: var(--surface);
  border-radius: 10px;
}
.tenant-log-header {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 18px;
}
.tenant-log-header .page-title {
  margin: 0;
  font-size: 18px;
  font-weight: 650;
  line-height: 1.2;
}
.tenant-log-header .page-subtitle {
  margin: 4px 0 0;
  color: var(--text-3);
  font-size: 13px;
  line-height: 1.35;
}
.tenant-log-refresh,
.tenant-log-query,
.tenant-log-reset {
  height: 34px;
  border-radius: 7px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 0 16px;
  font-size: 13px;
  cursor: pointer;
  white-space: nowrap;
}
.tenant-log-refresh,
.tenant-log-query {
  border: 1px solid var(--brand);
  background: var(--brand);
  color: #fff;
}
.tenant-log-reset {
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--text-2);
}
.tenant-log-reset:hover:not(:disabled) {
  background: var(--surface-2);
}
.tenant-log-refresh:disabled,
.tenant-log-query:disabled,
.tenant-log-reset:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.tenant-log-overview {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 14px 18px;
}
.kpi-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}
.kpi {
  padding: 8px 14px;
  border-radius: 8px;
  background: var(--surface-2);
}
.kpi span {
  color: var(--text-3);
  font-size: 12px;
}
.kpi strong {
  display: block;
  margin-top: 2px;
  font-size: 24px;
  font-weight: 650;
  line-height: 1.1;
}
.kpi strong.is-warn { color: var(--warn); }
.kpi strong.is-err { color: var(--err); }
.overview-summary {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.overview-label {
  color: var(--text-3);
  font-size: 12px;
}
.overview-summary p {
  margin: 0;
  color: var(--text-2);
  font-size: 13px;
  line-height: 1.5;
}
.overview-note {
  color: var(--text-3);
  font-size: 12px;
  line-height: 1.4;
}
.domain-strip {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 2px;
}
.domain-strip em {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 8px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--surface-2);
  color: var(--text-2);
  font-size: 12px;
  font-style: normal;
}

.tenant-log-toolbar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  padding: 10px 14px;
}
.tenant-log-search { flex: 1 1 200px; max-width: 320px; }
.tenant-log-select { width: 150px; }

.tenant-log-body {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1.7fr) minmax(0, 1fr);
  gap: 14px;
  align-items: stretch;
}

.tenant-log-table-card {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.card-head {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 18px;
  border-bottom: 1px solid var(--line);
}
.tenant-log-table-scroll {
  flex: 1;
  min-height: 0;
}
.card-head h2 {
  margin: 0;
  font-size: 14px;
  font-weight: 650;
  color: var(--text);
}
.card-head span {
  color: var(--text-3);
  font-size: 12px;
}
.tenant-log-table {
  width: 100%;
}
.tenant-log-table :deep(.el-table) {
  --el-table-header-bg-color: var(--surface-2);
  --el-table-header-text-color: var(--text-2);
  --el-table-bg-color: var(--surface);
  --el-table-tr-bg-color: var(--surface);
  --el-table-row-hover-bg-color: var(--surface-2);
  --el-table-border-color: var(--line);
  --el-table-text-color: var(--text);
  background: var(--surface);
  font-size: 13px;
  color: var(--text);
}
.tenant-log-table :deep(.el-table th.el-table__cell) {
  font-size: 12px;
  font-weight: 600;
}
.tenant-log-table :deep(.el-table__row) {
  cursor: pointer;
}
.tenant-log-table :deep(.el-button.row-detail-btn) {
  height: auto;
  padding: 2px 6px;
  border: none;
  background: transparent;
  color: var(--brand);
  font-size: 13px;
}
.tenant-log-table :deep(.el-button.row-detail-btn:hover) {
  background: var(--brand-soft);
  color: var(--brand-hover);
}
.tenant-log-pagination {
  flex-shrink: 0;
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 18px;
  border-top: 1px solid var(--line);
}
.tenant-log-pagination :deep(.el-pagination) {
  flex-wrap: wrap;
  row-gap: 8px;
}
.mono {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-3);
}

.insight-sidebar {
  align-self: start;
  max-height: 100%;
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
}
.insight-panel {
  min-width: 0;
  display: flex;
  flex-direction: column;
  padding: 14px;
}
.recommendation-panel {
  border-color: color-mix(in srgb, var(--warn) 28%, var(--line));
}
.insight-head {
  display: flex;
  align-items: center;
  gap: 7px;
  color: var(--brand);
}
.insight-head h3 {
  margin: 0;
  color: var(--text);
  font-size: 13px;
  font-weight: 650;
}
.risk-list,
.timeline-list,
.recommendation-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 12px;
}
.risk-item {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 10px;
  align-items: start;
}
.risk-item strong,
.timeline-event strong,
.recommendation-item strong {
  display: block;
  overflow: hidden;
  color: var(--text);
  font-size: 13px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.risk-item span,
.timeline-event span,
.timeline-event p,
.recommendation-item span,
.recommendation-item p,
.insight-empty {
  color: var(--text-3);
  font-size: 12px;
  line-height: 1.45;
}
.timeline-event {
  display: grid;
  grid-template-columns: 10px minmax(0, 1fr);
  gap: 10px;
  align-items: start;
}
.timeline-event i {
  width: 8px;
  height: 8px;
  margin-top: 6px;
  border-radius: 50%;
  background: var(--ok);
  box-shadow: 0 0 0 4px var(--ok-soft);
}
.timeline-event i[data-risk='medium'] {
  background: var(--warn);
  box-shadow: 0 0 0 4px var(--warn-soft);
}
.timeline-event i[data-risk='high'] {
  background: var(--err);
  box-shadow: 0 0 0 4px var(--err-soft);
}
.timeline-event p {
  margin: 3px 0 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.recommendation-item {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 9px;
  padding: 7px 8px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface-2);
}
.recommendation-item[data-severity='medium'] {
  border-color: color-mix(in srgb, var(--warn) 32%, var(--line));
}
.recommendation-item[data-severity='high'] {
  border-color: color-mix(in srgb, var(--err) 38%, var(--line));
}
.recommendation-item em {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 36px;
  height: 22px;
  padding: 0 7px;
  border-radius: 999px;
  background: var(--ok-soft);
  color: var(--ok);
  font-size: 12px;
  font-style: normal;
  white-space: nowrap;
}
.recommendation-item[data-severity='medium'] em {
  background: var(--warn-soft);
  color: var(--warn);
}
.recommendation-item[data-severity='high'] em {
  background: var(--err-soft);
  color: var(--err);
}
.recommendation-item p {
  margin: 3px 0 0;
  color: var(--text);
}
.insight-empty {
  padding: 14px 0;
  text-align: center;
}

.risk-chip {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 8px;
  border-radius: 999px;
  font-style: normal;
  font-size: 12px;
  color: var(--ok);
  background: var(--ok-soft);
}
.risk-chip[data-risk='medium'] { color: var(--warn); background: var(--warn-soft); }
.risk-chip[data-risk='high'] { color: var(--err); background: var(--err-soft); }

.tenant-log-state {
  min-height: 220px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--text-3);
  font-size: 13px;
}
.tenant-log-state.is-error { color: var(--err); }

.log-detail {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.log-detail-risk {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-3);
  font-size: 12px;
}
.log-detail-fields {
  display: flex;
  flex-direction: column;
  gap: 0;
  margin: 0;
}
.log-detail-fields > div {
  display: grid;
  grid-template-columns: 88px minmax(0, 1fr);
  gap: 12px;
  padding: 9px 0;
  border-bottom: 1px solid var(--line);
}
.log-detail-fields dt {
  color: var(--text-3);
  font-size: 12px;
}
.log-detail-fields dd {
  margin: 0;
  color: var(--text);
  font-size: 13px;
  word-break: break-word;
}
.log-detail-raw-head {
  margin-bottom: 6px;
  color: var(--text-3);
  font-size: 12px;
}
.log-detail-raw pre {
  margin: 0;
  max-height: 280px;
  overflow: auto;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface-2);
  color: var(--text-2);
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

@media (max-width: 1100px) {
  .tenant-log-page { padding: 16px; overflow-y: auto; }
  .tenant-log-header {
    align-items: flex-start;
    flex-direction: column;
  }
  .kpi-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .tenant-log-body {
    flex: none;
    grid-template-columns: 1fr;
  }
  .tenant-log-table-scroll {
    height: 60vh;
  }
  .insight-sidebar {
    max-height: none;
    overflow: visible;
  }
  .tenant-log-toolbar {
    align-items: stretch;
  }
  .tenant-log-search,
  .tenant-log-select {
    width: 100%;
    max-width: none;
    flex-basis: auto;
  }
}
</style>
