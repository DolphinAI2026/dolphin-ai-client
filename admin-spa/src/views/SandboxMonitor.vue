<template>
  <div class="sandbox-monitor">
    <div class="page-header">
      <div>
        <h1>工作区</h1>
        <p>开发和调试用工作区，本页面只负责启动、停止、销毁和查看状态。</p>
      </div>
      <el-button @click="load" :loading="loading">刷新</el-button>
    </div>

    <el-alert
      v-if="error"
      :title="error"
      type="error"
      show-icon
      :closable="false"
      style="margin-bottom: 16px"
    />

    <el-table :data="rows" v-loading="loading" stripe>
      <el-table-column label="工作区 ID" prop="workspace_id" width="200" />
      <el-table-column label="租户" prop="tenant_id" width="80" />
      <el-table-column label="用户" prop="user_id" width="80" />
      <el-table-column label="项目" prop="project_name" />
      <el-table-column label="运行状态" width="120">
        <template #default="{ row }">
          <el-tag :type="statusType(row.container_status)">{{ row.container_status || '-' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="最近活跃" prop="last_active_at" width="180" />
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="onStart(row.workspace_id)" :disabled="row.container_status === 'running'">
            启动
          </el-button>
          <el-button size="small" type="warning" @click="onStop(row.workspace_id)" :disabled="row.container_status !== 'running'">
            停止
          </el-button>
          <el-button size="small" type="danger" @click="onDestroy(row.workspace_id)">
            销毁
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-alert
      v-if="!loading && rows.length === 0 && !error"
      title="当前无活跃沙箱"
      type="info"
      :closable="false"
      style="margin-top: 16px"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiGet, apiPost, apiDel } from '@/api/client'

interface SandboxRow {
  workspace_id: string
  tenant_id: number
  user_id: number
  project_name?: string
  container_status?: string
  last_active_at?: string
}

const loading = ref(false)
const error   = ref('')
const rows    = ref<SandboxRow[]>([])

function statusType(s: string | undefined) {
  if (s === 'running') return 'success'
  if (s === 'exited' || s === 'stopped') return 'info'
  if (s === 'created' || s === 'paused') return 'warning'
  return 'info'
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const resp = await apiGet<{ sandboxes: SandboxRow[] }>('/online-coding/sandboxes')
    rows.value = resp?.sandboxes || []
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function onStart(ws: string) {
  try {
    await apiPost(`/online-coding/sandboxes/${ws}/start`)
    ElMessage.success('已启动')
    load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '启动失败')
  }
}

async function onStop(ws: string) {
  try {
    await apiPost(`/online-coding/sandboxes/${ws}/stop`)
    ElMessage.success('已停止')
    load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '停止失败')
  }
}

async function onDestroy(ws: string) {
  await ElMessageBox.confirm(
    `确认销毁沙箱 ${ws}？容器会被删，源码目录保留。`,
    '确认销毁',
    { confirmButtonText: '销毁', cancelButtonText: '取消', type: 'warning' },
  ).catch(() => null).then(async (ok) => {
    if (!ok) return
    try {
      await apiDel(`/online-coding/sandboxes/${ws}`)
      ElMessage.success('已销毁')
      load()
    } catch (e: any) {
      ElMessage.error(e?.response?.data?.detail || '销毁失败')
    }
  })
}

onMounted(load)
</script>

<style scoped>
.sandbox-monitor { max-width: 1400px; margin: 0 auto; }
.page-header {
  margin-bottom: 20px;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.page-header h1 { margin: 0 0 4px; font-size: 20px; }
.page-header p  { margin: 0; font-size: 13px; color: #909399; }
</style>
