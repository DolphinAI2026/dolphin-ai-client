<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1>调用日志</h1>
        <p>记录 MCP 服务调用结果，便于追踪鉴权、租户身份、工具参数和异常原因。</p>
      </div>
    </div>

    <div class="toolbar">
      <div class="toolbar-filters">
        <el-select
          v-model="filterServices"
          multiple
          collapse-tags
          collapse-tags-tooltip
          placeholder="服务（多选）"
          clearable
          style="width: 220px"
        >
          <el-option v-for="s in serviceOptions" :key="s" :label="s" :value="s" />
        </el-select>
        <el-select v-model="filterStatus" placeholder="状态" style="width: 140px">
          <el-option label="全部" value="all" />
          <el-option label="成功" value="success" />
          <el-option label="失败" value="error" />
        </el-select>
        <el-date-picker
          v-model="filterRange"
          type="datetimerange"
          range-separator="至"
          start-placeholder="开始时间"
          end-placeholder="结束时间"
          value-format="YYYY-MM-DDTHH:mm:ss"
          clearable
          style="width: 360px"
        />
        <el-input
          v-model="filterKeyword"
          placeholder="搜索工具 / 租户 ID / 错误"
          clearable
          style="width: 240px"
        />
      </div>
      <div class="toolbar-actions">
        <span class="result-count">
          共 {{ logs.length }} 条<template v-if="hasActiveFilter">（过滤后 {{ filteredLogs.length }}）</template>
        </span>
        <el-button @click="resetFilters" :disabled="!hasActiveFilter">重置筛选</el-button>
        <el-button @click="loadLogs" :loading="loading" type="primary" :icon="Refresh">
          刷新
        </el-button>
      </div>
    </div>

    <el-empty
      v-if="filteredLogs.length === 0"
      :description="logs.length === 0 ? '暂无调用日志' : '当前筛选条件下没有匹配的日志'"
    >
      <template #description>
        <div class="empty-copy">
          <template v-if="logs.length === 0">
            暂无调用记录。工具调用后会自动出现在这里 ·
            也可以从
            <router-link to="/tester" class="empty-link">[MCP 测试台]</router-link>
            触发一次试调用看效果。
          </template>
          <template v-else>
            当前筛选条件下没有匹配的日志，<a class="empty-link" @click.prevent="resetFilters">重置筛选</a>查看全部。
          </template>
        </div>
      </template>
    </el-empty>

    <el-table v-else :data="filteredLogs" stripe v-loading="loading">
      <el-table-column type="expand" width="44">
        <template #default="{ row }">
          <div class="log-detail">
            <div>
              <h3>工具参数</h3>
              <pre>{{ pretty(row.request_arguments || row.request_params || {}) }}</pre>
            </div>
            <div>
              <h3>Header 摘要</h3>
              <pre>{{ pretty(row.request_headers || {}) }}</pre>
            </div>
            <div>
              <h3>错误 / 响应</h3>
              <pre>{{ row.error || '-' }}</pre>
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="时间" prop="time" width="190" show-overflow-tooltip />
      <el-table-column label="服务" prop="service" width="180" show-overflow-tooltip />
      <el-table-column label="工具 / RPC" min-width="180" show-overflow-tooltip>
        <template #default="{ row }">
          {{ row.tool || row.rpc_method || '-' }}
        </template>
      </el-table-column>
      <el-table-column label="参数" min-width="240" show-overflow-tooltip>
        <template #default="{ row }">
          {{ compact(row.request_arguments || row.request_params) }}
        </template>
      </el-table-column>
      <el-table-column label="租户 ID" prop="apaas_tenant_id" width="190" show-overflow-tooltip />
      <el-table-column label="状态码" prop="status_code" width="90" />
      <el-table-column label="结果" width="100">
        <template #default="{ row }">
          <el-tag :type="row.success ? 'success' : 'danger'">
            {{ row.success ? '成功' : '失败' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="错误" prop="error" min-width="220" show-overflow-tooltip />
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { apiGet } from '@/api/client'

const logs = ref<any[]>([])
const loading = ref(false)

// 筛选条件（前端 client-side filter — 后端 /mcp-platform/call-logs 只接 limit 参数）
const filterServices = ref<string[]>([])
const filterStatus = ref<'all' | 'success' | 'error'>('all')
const filterRange = ref<[string, string] | null>(null)
const filterKeyword = ref('')

const serviceOptions = computed(() => {
  const set = new Set<string>(['ai-builder-inprocess', 'support-triage'])
  for (const row of logs.value) {
    if (row.service) set.add(row.service)
  }
  return Array.from(set).sort()
})

const hasActiveFilter = computed(() =>
  filterServices.value.length > 0
  || filterStatus.value !== 'all'
  || !!filterRange.value
  || filterKeyword.value.trim() !== '',
)

const filteredLogs = computed(() => {
  let result = logs.value
  if (filterServices.value.length > 0) {
    const allow = new Set(filterServices.value)
    result = result.filter((row) => allow.has(row.service))
  }
  if (filterStatus.value === 'success') {
    result = result.filter((row) => row.success === true)
  } else if (filterStatus.value === 'error') {
    result = result.filter((row) => row.success === false)
  }
  if (filterRange.value && filterRange.value[0] && filterRange.value[1]) {
    const start = filterRange.value[0]
    const end = filterRange.value[1]
    result = result.filter((row) => {
      const t = String(row.time || '')
      return t >= start && t <= end
    })
  }
  const kw = filterKeyword.value.trim().toLowerCase()
  if (kw) {
    result = result.filter((row) => {
      const haystack = [
        row.tool,
        row.rpc_method,
        row.apaas_tenant_id,
        row.error,
        row.service,
      ].map((v) => String(v || '').toLowerCase()).join(' ')
      return haystack.includes(kw)
    })
  }
  return result
})

function pretty(value: any) {
  if (value == null || value === '') return '-'
  if (typeof value === 'string') return value
  return JSON.stringify(value, null, 2)
}

function compact(value: any) {
  if (!value) return '-'
  const text = typeof value === 'string' ? value : JSON.stringify(value)
  return text.length > 120 ? `${text.slice(0, 120)}...` : text
}

function resetFilters() {
  filterServices.value = []
  filterStatus.value = 'all'
  filterRange.value = null
  filterKeyword.value = ''
}

async function loadLogs() {
  loading.value = true
  try {
    const resp = await apiGet<{ items: any[] }>('/mcp-platform/call-logs', { limit: 200 }).catch(() => ({ items: [] }))
    logs.value = resp.items || []
  } finally {
    loading.value = false
  }
}

onMounted(loadLogs)
</script>

<style scoped>
/* v3 token 化 · 2026-05-20 — visual refresh only. template/script untouched. */
/* v3 2026-05-21 — 跟 frontend 密度对齐：max-width/h1/page-header/toolbar padding
   都交给 density-align.css 全局规则。本 scoped 只保留 layout + log-detail。 */
.page {
  color: var(--text);
  font-family: var(--font-sans);
}
.page-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
}
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  background: var(--surface);
  box-shadow: var(--sh-1);
}
.toolbar-filters {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.result-count {
  color: var(--text-3);
  font-size: 12px;
  font-weight: var(--fw-medium, 500);
  margin-right: 4px;
}
.empty-copy {
  max-width: 560px;
  margin: 0 auto;
  color: var(--text-3);
  font-size: 13px;
  line-height: 1.7;
}
.empty-link {
  color: var(--brand, var(--text));
  text-decoration: underline;
  text-underline-offset: 2px;
  cursor: pointer;
}
.log-detail {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1fr);
  gap: 12px;
  padding: 12px 16px;
}
.log-detail h3 {
  margin: 0 0 8px;
  font-size: 12.5px;
  font-weight: var(--fw-semibold, 600);
  color: var(--text);
  letter-spacing: 0.02em;
}
.log-detail pre {
  margin: 0;
  max-height: 260px;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: var(--r-2, 6px);
  padding: 10px;
  background: var(--surface-2);
  color: var(--text);
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
  font-size: 11.5px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
