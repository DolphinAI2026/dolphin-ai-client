<template>
  <section class="audit-explorer">
    <div class="filters">
      <el-date-picker
        v-model="range"
        type="datetimerange"
        range-separator="至"
        start-placeholder="开始时间"
        end-placeholder="结束时间"
      />
      <el-input v-model="actorId" placeholder="操作者 ID" clearable />
      <el-input
        v-if="!applicationId"
        v-model="applicationFilter"
        placeholder="应用 ID"
        clearable
      />
      <el-select v-model="eventType" clearable placeholder="事件">
        <el-option
          v-for="option in eventOptions"
          :key="option.value"
          :label="option.label"
          :value="option.value"
        />
      </el-select>
      <el-select v-model="result" clearable placeholder="结果">
        <el-option label="成功" value="success" />
        <el-option label="失败" value="failure" />
        <el-option label="拒绝" value="denied" />
      </el-select>
      <el-button type="primary" @click="reload">查询</el-button>
    </div>

    <el-table class="desktop-table" v-loading="loading" :data="items" @row-click="openDetail">
      <el-table-column label="时间" width="180">
        <template #default="{ row }">{{ formatAuditTime(row.occurred_at) }}</template>
      </el-table-column>
      <el-table-column prop="actor_name" label="操作者" width="130" />
      <el-table-column v-if="!applicationId" prop="application_id" label="应用" width="90" />
      <el-table-column label="事件" min-width="190">
        <template #default="{ row }">{{ eventTypeLabel(row.event_type) }}</template>
      </el-table-column>
      <el-table-column prop="target_id" label="目标" width="110" />
      <el-table-column label="结果" width="90">
        <template #default="{ row }">
          <el-tag :type="resultTone(row.result)" size="small" effect="plain">
            {{ resultLabel(row.result) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="request_id" label="Request ID" min-width="150" />
    </el-table>

    <div v-loading="loading" class="mobile-list">
      <button
        v-for="item in items"
        :key="item.id"
        class="mobile-item"
        type="button"
        @click="openDetail(item)"
      >
        <span class="mobile-item-head">
          <strong>{{ eventTypeLabel(item.event_type) }}</strong>
          <el-tag :type="resultTone(item.result)" size="small" effect="plain">
            {{ resultLabel(item.result) }}
          </el-tag>
        </span>
        <span>{{ formatAuditTime(item.occurred_at) }}</span>
        <span>{{ item.actor_name || `用户 ${item.actor_id || '-'}` }}</span>
        <span v-if="!applicationId">应用 {{ item.application_id || '-' }}</span>
        <span>目标 {{ item.target_id || '-' }}</span>
      </button>
    </div>

    <div v-if="error" class="state">
      <span>{{ error }}</span>
      <el-button @click="reload">重试</el-button>
    </div>
    <div v-else-if="!loading && !items.length" class="state">
      当前条件下暂无审计日志
    </div>

    <div class="pager">
      <span class="pager-total">共 {{ total }} 条</span>
      <el-button :disabled="!cursorHistory.length || loading" @click="previousPage">
        上一页
      </el-button>
      <el-button :disabled="!nextCursor || loading" @click="nextPage">
        下一页
      </el-button>
    </div>

    <el-drawer v-model="detailOpen" title="审计详情" size="min(520px, 100vw)">
      <div v-if="detailLoading" class="state">正在读取审计详情</div>
      <div v-else-if="detailError" class="state detail-error">
        <span>{{ detailError }}</span>
        <el-button v-if="detailRow" @click="openDetail(detailRow)">重试</el-button>
      </div>
      <dl v-else-if="selected" class="detail">
        <template v-for="(value, key) in selected" :key="key">
          <dt>{{ detailLabel(String(key)) }}</dt>
          <dd><pre>{{ renderDetailValue(String(key), value) }}</pre></dd>
        </template>
      </dl>
    </el-drawer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { auditLogsApi, type AuditLogItem } from '@/api/auditLogs'

const props = defineProps<{ applicationId?: number }>()

const eventOptions = [
  { value: 'application_member.direct_add', label: '直接添加应用成员' },
  { value: 'application_member.role_changed', label: '调整应用成员角色' },
  { value: 'application_member.removed', label: '移除应用成员' },
]

const eventLabels = Object.fromEntries(eventOptions.map(option => [option.value, option.label]))
const resultLabels: Record<string, string> = {
  success: '成功',
  failure: '失败',
  denied: '拒绝',
}
const detailLabels: Record<string, string> = {
  id: '日志 ID',
  occurred_at: '发生时间',
  tenant_id: '租户 ID',
  application_id: '应用 ID',
  actor_id: '操作者 ID',
  actor_name: '操作者',
  event_type: '事件',
  target_type: '目标类型',
  target_id: '目标 ID',
  result: '结果',
  failure_reason: '失败原因',
  ip_address: 'IP 地址',
  request_id: 'Request ID',
  correlation_id: 'Correlation ID',
  before_value: '变更前',
  after_value: '变更后',
}

const items = ref<AuditLogItem[]>([])
const nextCursor = ref<string | null>(null)
const currentCursor = ref<string | null>(null)
const cursorHistory = ref<Array<string | null>>([])
const total = ref(0)
const loading = ref(false)
const error = ref('')

const range = ref<[Date, Date] | null>(null)
const actorId = ref('')
const applicationFilter = ref('')
const eventType = ref('')
const result = ref('')

const detailOpen = ref(false)
const detailLoading = ref(false)
const detailError = ref('')
const detailRow = ref<AuditLogItem | null>(null)
const selected = ref<AuditLogItem | null>(null)

function queryParams(cursor?: string | null) {
  return {
    application_id: props.applicationId ? undefined : (applicationFilter.value || undefined),
    occurred_from: range.value?.[0].toISOString(),
    occurred_to: range.value?.[1].toISOString(),
    actor_id: actorId.value || undefined,
    event_type: eventType.value || undefined,
    result: result.value || undefined,
    cursor: cursor || undefined,
    limit: 50,
  }
}

async function load(cursor?: string | null) {
  loading.value = true
  error.value = ''
  try {
    const page = props.applicationId
      ? await auditLogsApi.listApplication(props.applicationId, queryParams(cursor))
      : await auditLogsApi.list(queryParams(cursor))
    items.value = page.items
    nextCursor.value = page.next_cursor || null
    total.value = page.total
    currentCursor.value = cursor || null
    return true
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '读取审计日志失败'
    return false
  } finally {
    loading.value = false
  }
}

async function reload() {
  cursorHistory.value = []
  await load(null)
}

async function nextPage() {
  if (!nextCursor.value) return
  const previousCursor = currentCursor.value
  if (await load(nextCursor.value)) cursorHistory.value.push(previousCursor)
}

async function previousPage() {
  const cursor = cursorHistory.value[cursorHistory.value.length - 1]
  if (cursor === undefined) return
  if (await load(cursor)) cursorHistory.value.pop()
}

async function openDetail(row: AuditLogItem) {
  detailRow.value = row
  selected.value = null
  detailError.value = ''
  detailLoading.value = true
  detailOpen.value = true
  try {
    selected.value = props.applicationId
      ? await auditLogsApi.getApplication(props.applicationId, row.id)
      : await auditLogsApi.get(row.id)
  } catch (reason) {
    detailError.value = reason instanceof Error ? reason.message : '读取审计详情失败'
  } finally {
    detailLoading.value = false
  }
}

function formatAuditTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value || '-'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date)
}

function eventTypeLabel(value: string) {
  return eventLabels[value] || value || '-'
}

function resultLabel(value: string) {
  return resultLabels[value] || value || '-'
}

function resultTone(value: string) {
  if (value === 'success') return 'success'
  if (value === 'denied') return 'warning'
  return 'danger'
}

function detailLabel(key: string) {
  return detailLabels[key] || key
}

function renderDetailValue(key: string, value: unknown) {
  if (key === 'occurred_at' && typeof value === 'string') return formatAuditTime(value)
  if (key === 'event_type' && typeof value === 'string') return eventTypeLabel(value)
  if (key === 'result' && typeof value === 'string') return resultLabel(value)
  if (value == null || value === '') return '-'
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2)
}

onMounted(reload)
</script>

<style scoped>
.audit-explorer {
  display: flex;
  min-height: 0;
  flex-direction: column;
  gap: 12px;
}

.filters {
  display: grid;
  grid-template-columns: minmax(300px, 2fr) repeat(4, minmax(120px, 1fr)) auto;
  gap: 8px;
}

.pager {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.mobile-list {
  display: none;
}

.pager-total {
  margin-right: auto;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px;
  color: var(--el-text-color-secondary);
}

.detail-error {
  color: var(--el-color-danger);
}

.detail {
  display: grid;
  grid-template-columns: 130px minmax(0, 1fr);
  gap: 0;
  border-top: 1px solid var(--el-border-color);
}

dt,
dd {
  min-width: 0;
  margin: 0;
  padding: 10px;
  border-bottom: 1px solid var(--el-border-color);
}

dt {
  color: var(--el-text-color-secondary);
}

pre {
  overflow-wrap: anywhere;
  margin: 0;
  white-space: pre-wrap;
}

@media (max-width: 1100px) {
  .filters {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 640px) {
  .filters {
    grid-template-columns: 1fr;
  }

  .filters :deep(.el-date-editor),
  .filters :deep(.el-input),
  .filters :deep(.el-select),
  .filters :deep(.el-button) {
    width: 100%;
    min-width: 0;
  }

  .desktop-table {
    display: none;
  }

  .mobile-list {
    display: grid;
    gap: 8px;
  }

  .mobile-item {
    display: grid;
    min-width: 0;
    gap: 5px;
    padding: 12px;
    color: var(--el-text-color-regular);
    text-align: left;
    background: var(--el-fill-color-blank);
    border: 1px solid var(--el-border-color);
    border-radius: 6px;
  }

  .mobile-item-head {
    display: flex;
    min-width: 0;
    align-items: flex-start;
    justify-content: space-between;
    gap: 8px;
  }

  .mobile-item-head strong {
    overflow-wrap: anywhere;
  }

  .pager {
    flex-wrap: wrap;
  }

  .pager-total {
    width: 100%;
  }

  .detail {
    grid-template-columns: 96px minmax(0, 1fr);
  }
}
</style>
