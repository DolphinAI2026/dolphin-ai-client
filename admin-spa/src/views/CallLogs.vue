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
.page { max-width: 1400px; margin: 0 auto; }
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 20px;
  gap: 16px;
}
.page-header h1 { margin: 0 0 4px; font-size: 20px; }
.page-header p { margin: 0; font-size: 13px; color: #66756d; }
.empty-copy {
  max-width: none;
  color: #66756d;
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
  font-size: 13px;
  color: #233129;
}
.log-detail pre {
  margin: 0;
  max-height: 260px;
  overflow: auto;
  border: 1px solid #dfe8e2;
  border-radius: 6px;
  padding: 10px;
  background: #f7faf8;
  color: #26352d;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
