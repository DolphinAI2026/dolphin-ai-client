<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1>调用日志</h1>
        <p>记录 MCP 服务调用结果，便于追踪鉴权、租户身份、工具参数和异常原因。</p>
      </div>
    </div>

    <el-empty
      v-if="logs.length === 0"
      description="暂无调用日志"
    >
      <template #description>
        <div class="empty-copy">
          暂无调用记录。完成一次 MCP 测试或服务调用后，日志会展示请求服务、工具名称、租户身份、状态码和错误详情。
        </div>
      </template>
    </el-empty>

    <el-table v-else :data="logs" stripe>
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
      <el-table-column label="时间" prop="time" width="170" />
      <el-table-column label="服务" prop="service" width="180" />
      <el-table-column label="工具 / RPC" min-width="180">
        <template #default="{ row }">
          {{ row.tool || row.rpc_method || '-' }}
        </template>
      </el-table-column>
      <el-table-column label="参数" min-width="240" show-overflow-tooltip>
        <template #default="{ row }">
          {{ compact(row.request_arguments || row.request_params) }}
        </template>
      </el-table-column>
      <el-table-column label="租户 ID" prop="apaas_tenant_id" width="190" />
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
import { onMounted, ref } from 'vue'
import { apiGet } from '@/api/client'

const logs = ref<any[]>([])

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

async function loadLogs() {
  const resp = await apiGet<{ items: any[] }>('/mcp-platform/call-logs', { limit: 200 }).catch(() => ({ items: [] }))
  logs.value = resp.items || []
}

onMounted(loadLogs)
</script>

<style scoped>
/* v3 token 化 · 2026-05-20 — visual refresh only. template/script untouched. */
.page {
  max-width: 1400px;
  margin: 0 auto;
  color: var(--text);
  font-family: var(--font-sans);
}
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 20px;
  gap: 16px;
}
.page-header h1 {
  margin: 0 0 4px;
  font-size: 22px;
  line-height: 1.25;
  font-weight: var(--fw-bold, 700);
  letter-spacing: -0.01em;
  color: var(--text);
}
.page-header p {
  margin: 0;
  font-size: 13.5px;
  line-height: 1.55;
  color: var(--text-3);
}
.empty-copy {
  max-width: none;
  color: var(--text-3);
  font-size: 13px;
  line-height: 1.7;
  white-space: nowrap;
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
