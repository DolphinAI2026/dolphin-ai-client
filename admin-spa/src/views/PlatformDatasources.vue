<template>
  <div class="ds-page">
    <header class="ds-head">
      <div>
        <h1 class="ds-title">数据源</h1>
        <p class="ds-sub">
          {{ connections.length }} 个数据源
          <span v-if="activeCount > 0" class="ds-stat-ok"> · {{ activeCount }} 在线</span>
        </p>
      </div>
      <div class="ds-actions">
        <el-button :icon="Refresh" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openFullManage">
          完整管理 / 新增连接
        </el-button>
      </div>
    </header>

    <el-alert type="info" :closable="false" show-icon class="ds-tip">
      数据源管理已下沉到平台级 — 新增 / 编辑 / 测试连接 / 表清单等完整操作请用
      <el-link type="primary" @click="openFullManage">"完整管理"</el-link> 入口
      (跳到 ai-builder DbConnectionsPage 真页).
    </el-alert>

    <el-table v-loading="loading" :data="connections" stripe class="ds-table">
      <el-table-column prop="name" label="名称" min-width="180" />
      <el-table-column prop="db_type" label="类型" width="120">
        <template #default="{ row }">
          <el-tag size="small">{{ row.db_type }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="连接地址" min-width="240">
        <template #default="{ row }">
          <span class="mono">{{ row.host }}:{{ row.port }}/{{ row.database }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="username" label="用户名" width="140" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="表数" width="80" align="right">
        <template #default="{ row }">
          <span class="mono">{{ row.table_count ?? '-' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="160" align="center">
        <template #default="{ row }">
          <el-button size="small" :icon="Edit" @click="openFullManage(row.id)">编辑</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!loading && connections.length === 0" description="暂无数据源">
      <el-button type="primary" @click="openFullManage">添加第一个数据源</el-button>
    </el-empty>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Plus, Edit } from '@element-plus/icons-vue'
import { apiGet } from '@/api/client'

interface DbConn {
  id: number
  name: string
  db_type: string
  host: string
  port: number
  database: string
  username: string
  status?: string
  table_count?: number
}

const connections = ref<DbConn[]>([])
const loading = ref(false)

const activeCount = computed(() => connections.value.filter(c => c.status === 'active').length)

async function load() {
  loading.value = true
  try {
    const resp = await apiGet<any>('/db-connections')
    connections.value = Array.isArray(resp) ? resp : (resp?.items || resp?.data || [])
  } catch (e: any) {
    ElMessage.error('加载数据源失败: ' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

function openFullManage(connId?: number) {
  // admin-spa iframe 嵌在 ai-builder PlatformAdminEmbed 内, top 跳到 ai-builder /db-connections
  const targetPath = '/ai-builder/db-connections' + (connId && typeof connId === 'number' ? `?edit=${connId}` : '')
  if (window.top && window.top !== window.self) {
    window.top.location.href = targetPath
  } else {
    window.location.href = targetPath
  }
}

function statusTagType(s?: string): 'success' | 'danger' | 'warning' | 'info' {
  if (s === 'active') return 'success'
  if (s === 'error' || s === 'failed') return 'danger'
  if (s === 'pending') return 'warning'
  return 'info'
}

function statusLabel(s?: string): string {
  if (s === 'active') return '在线'
  if (s === 'error') return '错误'
  if (s === 'failed') return '失败'
  if (s === 'pending') return '待测'
  return s || '未知'
}

onMounted(load)
</script>

<style scoped>
.ds-page { padding: 24px 28px; }
.ds-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
}
.ds-title { margin: 0 0 4px; font-size: 22px; font-weight: 600; }
.ds-sub { margin: 0; font-size: 13px; color: #909399; }
.ds-stat-ok { color: #67c23a; }
.ds-actions { display: flex; gap: 8px; }
.ds-tip { margin-bottom: 16px; }
.ds-table { margin-top: 8px; }
.mono { font-family: 'SF Mono', Menlo, monospace; font-size: 12.5px; }
</style>
