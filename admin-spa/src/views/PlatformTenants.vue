<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1>aPaaS 租户</h1>
        <p>默认展示最近一次登录或人工刷新同步到本地的租户；需要更新时再手动刷新。</p>
      </div>
      <div class="page-actions">
        <el-select v-model="selectedAdminId" placeholder="选择平台管理员" style="width: 220px">
          <el-option
            v-for="item in admins"
            :key="item.id"
            :label="`${item.name}（${item.account}）`"
            :value="item.id"
          />
        </el-select>
        <el-input v-model="keyword" placeholder="租户名称/编码" clearable style="width: 200px" />
        <el-button @click="syncTenants()" :loading="loading" type="primary">刷新租户</el-button>
      </div>
    </div>

    <el-alert
      v-if="error"
      :title="error"
      type="error"
      show-icon
      :closable="false"
      style="margin-bottom: 16px"
    />

    <el-alert
      v-if="!admins.length"
      title="未读取到可用的平台管理员身份，请先用 aPaaS 平台管理员账号登录。"
      type="warning"
      show-icon
      :closable="false"
      style="margin-bottom: 16px"
    />

    <el-card>
      <template #header>租户列表</template>
      <el-table :data="rows" v-loading="loading" stripe empty-text="暂无租户数据">
        <el-table-column label="租户名称" min-width="180">
          <template #default="{ row }">{{ pick(row, ['tenantName', 'name', 'tenant_name']) }}</template>
        </el-table-column>
        <el-table-column label="租户 ID" min-width="180">
          <template #default="{ row }">{{ pick(row, ['id', 'tenantId', 'tenant_id']) }}</template>
        </el-table-column>
        <el-table-column label="租户编码" min-width="150">
          <template #default="{ row }">{{ pick(row, ['tenantCode', 'code', 'tenant_code']) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            {{ formatStatus(pick(row, ['status', 'state'])) }}
          </template>
        </el-table-column>
      </el-table>
    </el-card>

  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiGet } from '@/api/client'

interface AdminRow {
  id: string
  name: string
  account: string
  is_default: boolean
  status: string
  token_fingerprint?: string
}

const admins = ref<AdminRow[]>([])
const selectedAdminId = ref('')
const rows = ref<any[]>([])
const keyword = ref('')
const loading = ref(false)
const error = ref('')

function pick(row: any, keys: string[]) {
  for (const key of keys) {
    if (row?.[key] !== undefined && row?.[key] !== null && row?.[key] !== '') return row[key]
  }
  return ''
}

function formatStatus(value: any) {
  if (value === 1 || value === '1' || value === 'ENABLE' || value === 'enabled') return '启用'
  if (value === 0 || value === '0' || value === 'DISABLE' || value === 'disabled') return '禁用'
  return value || '-'
}

async function loadAdmins() {
  const resp = await apiGet<{ items: AdminRow[] }>('/mcp-platform/apaas-admins')
  admins.value = resp.items || []
  selectedAdminId.value = selectedAdminId.value || admins.value.find((x) => x.is_default)?.id || admins.value[0]?.id || ''
}

async function loadLocalTenants() {
  loading.value = true
  error.value = ''
  try {
    const resp = await apiGet<{ items: any[]; synced?: { tenants?: number; envs?: number } }>('/mcp-platform/apaas-tenants', {
      keyword: keyword.value,
      local_only: true,
      page_size: 500,
    })
    rows.value = resp.items || []
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function syncTenants(options: { silent?: boolean } = {}) {
  loading.value = true
  error.value = ''
  try {
    const resp = await apiGet<{ items: any[]; synced?: { tenants?: number; envs?: number } }>('/mcp-platform/apaas-tenants', {
      admin_id: selectedAdminId.value || undefined,
      keyword: keyword.value,
      page_size: 100,
    })
    rows.value = resp.items || []
    const synced = resp.synced || {}
    if (!options.silent) {
      ElMessage.success(`已刷新 ${rows.value.length} 个租户，同步本地 ${synced.tenants ?? 0} 个租户 / ${synced.envs ?? 0} 个环境`)
    }
    await loadAdmins()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '刷新失败'
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadAdmins()
  await loadLocalTenants()
})
</script>

<style scoped>
.page { max-width: 1600px; margin: 0 auto; }
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 20px;
  gap: 16px;
  flex-wrap: wrap;
}
.page-header h1 { margin: 0 0 4px; font-size: 20px; }
.page-header p { margin: 0; font-size: 13px; color: #66756d; }
.page-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
</style>
