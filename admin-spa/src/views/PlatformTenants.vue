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
        <el-input
          v-model="searchQuery"
          placeholder="搜索租户名称/编码/ID"
          clearable
          style="width: 240px"
        />
        <el-button
          @click="syncTenants()"
          :loading="loading"
          :disabled="!selectedAdminId"
          type="primary"
          title="从 aPaaS 拉取最新租户列表（与搜索独立）"
        >
          刷新租户
        </el-button>
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

    <el-card class="admin-card">
      <template #header>
        <div class="card-head">
          <div>
            <span>平台管理员账号</span>
            <span class="card-meta">后端登录 aPaaS 并维护 Token</span>
          </div>
          <el-button type="primary" size="small" @click="openCreateAdmin">新增账号</el-button>
        </div>
      </template>
      <el-table :data="admins" v-loading="adminsLoading" stripe empty-text="暂无平台管理员账号">
        <el-table-column prop="name" label="名称" min-width="150" />
        <el-table-column prop="account" label="登录账号" min-width="180" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="row.status === 'connected' ? 'success' : 'info'" effect="plain">
              {{ row.status === 'connected' ? '已连接' : '未连接' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="默认" width="80">
          <template #default="{ row }">{{ row.is_default ? '是' : '-' }}</template>
        </el-table-column>
        <el-table-column label="最近登录" min-width="170">
          <template #default="{ row }">{{ formatDate(row.last_login_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="260" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" :loading="row._logging" @click="loginAdmin(row)">测试登录</el-button>
            <el-button link type="primary" @click="openEditAdmin(row)">编辑</el-button>
            <el-button v-if="!row.is_default" link @click="setDefaultAdmin(row)">设为默认</el-button>
            <el-button link type="danger" @click="deleteAdmin(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card class="tenant-card">
      <template #header>
        <div class="card-head">
          <span>租户列表</span>
          <span class="card-meta">
            共 {{ rows.length }} 条<template v-if="searchQuery">（过滤后 {{ filteredTenants.length }}）</template>
          </span>
        </div>
      </template>
      <el-table :data="pagedTenants" v-loading="loading" stripe empty-text="暂无租户数据">
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
        <el-table-column label="环境绑定" min-width="250">
          <template #default="{ row }">
            <div class="binding-cell">
              <el-tag :type="row.environmentBound ? 'success' : 'warning'" effect="plain">
                {{ row.environmentBound ? '已绑定' : '未绑定' }}
              </el-tag>
              <span class="binding-tenant-id">{{ row.platformTenantId || '-' }}</span>
              <el-button
                link
                type="primary"
                :disabled="!admins.length"
                @click="openBinding(row)"
              >
                {{ row.environmentBound ? '修改绑定' : '绑定环境' }}
              </el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <div class="pagination-wrap">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :total="filteredTenants.length"
          :page-sizes="[20, 50, 100, 200]"
          layout="total, sizes, prev, pager, next, jumper"
          background
          small
        />
      </div>
    </el-card>

    <el-dialog
      v-model="adminDialogVisible"
      :title="editingAdminId ? '编辑平台管理员账号' : '新增平台管理员账号'"
      width="480px"
      :close-on-click-modal="false"
    >
      <el-form :model="adminForm" label-position="top">
        <el-form-item label="名称" required>
          <el-input v-model="adminForm.name" placeholder="如：试用环境管理员" maxlength="80" />
        </el-form-item>
        <el-form-item label="aPaaS 登录账号" required>
          <el-input v-model="adminForm.account" autocomplete="off" />
        </el-form-item>
        <el-form-item :label="editingAdminId ? '密码（留空则不修改）' : '密码'" :required="!editingAdminId">
          <el-input v-model="adminForm.password" type="password" show-password autocomplete="new-password" />
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="adminForm.is_default">设为默认账号</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="adminDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="adminSaving" @click="saveAdmin">保存并登录</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="bindingVisible"
      :title="`环境绑定 — ${pick(bindingTarget, ['tenantName', 'tenant_name']) || ''}`"
      width="520px"
      :close-on-click-modal="false"
    >
      <el-form :model="bindingForm" label-position="top">
        <el-form-item label="平台管理员账号" required>
          <el-select v-model="bindingForm.admin_id" style="width: 100%" placeholder="选择平台管理员">
            <el-option
              v-for="item in admins"
              :key="item.id"
              :label="`${item.name}（${item.account}）`"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="aPaaS 地址" required>
          <el-input
            v-model="bindingForm.base_url"
            placeholder="https://apaas.example.com/backend"
            autocomplete="off"
          />
        </el-form-item>
        <el-form-item label="aPaaS 租户 ID" required>
          <el-input v-model="bindingForm.platform_tenant_id" autocomplete="off" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="bindingVisible = false">取消</el-button>
        <el-button type="primary" :loading="bindingSaving" @click="saveBinding">保存绑定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiDel, apiGet, apiPost, apiPut } from '@/api/client'

interface AdminRow {
  id: string
  name: string
  account: string
  base_url?: string
  is_default: boolean
  status: string
  last_login_at?: string | null
  _logging?: boolean
}

const admins = ref<AdminRow[]>([])
const adminsLoading = ref(false)
const selectedAdminId = ref('')
const rows = ref<any[]>([])
const searchQuery = ref('')
const loading = ref(false)
const error = ref('')
const adminDialogVisible = ref(false)
const adminSaving = ref(false)
const editingAdminId = ref('')
const editingAdminAccount = ref('')
const bindingVisible = ref(false)
const bindingSaving = ref(false)
const bindingTarget = ref<any | null>(null)
const adminForm = ref({
  name: '',
  account: '',
  password: '',
  is_default: false,
})
const bindingForm = ref({
  admin_id: '',
  base_url: '',
  platform_tenant_id: '',
})

// 客户端分页 + 实时搜索（rows 已经一次性拉全 page_size=500，搜索/翻页都本地处理）
const currentPage = ref(1)
const pageSize = ref(20)

const filteredTenants = computed(() => {
  const kw = searchQuery.value.trim().toLowerCase()
  if (!kw) return rows.value
  return rows.value.filter((row) => {
    const fields = [
      pick(row, ['tenantName', 'name', 'tenant_name']),
      pick(row, ['id', 'tenantId', 'tenant_id']),
      pick(row, ['tenantCode', 'code', 'tenant_code']),
      pick(row, ['status', 'state']),
    ]
    return fields.some((v) => String(v ?? '').toLowerCase().includes(kw))
  })
})

const pagedTenants = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredTenants.value.slice(start, start + pageSize.value)
})

// 搜索内容变化时回到第 1 页，避免停留在已过滤后的越界页
watch(searchQuery, () => {
  currentPage.value = 1
})
watch(pageSize, () => {
  currentPage.value = 1
})

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

function formatDate(value?: string | null) {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

function errorMessage(e: any, fallback: string) {
  return e?.response?.data?.detail || e?.message || fallback
}

async function loadAdmins() {
  adminsLoading.value = true
  try {
    const resp = await apiGet<{ items: AdminRow[] }>('/mcp-platform/apaas-admins')
    admins.value = resp.items || []
    if (!admins.value.some((item) => item.id === selectedAdminId.value)) {
      selectedAdminId.value = admins.value.find((item) => item.is_default)?.id || admins.value[0]?.id || ''
    }
  } finally {
    adminsLoading.value = false
  }
}

function openCreateAdmin() {
  editingAdminId.value = ''
  editingAdminAccount.value = ''
  adminForm.value = {
    name: '',
    account: '',
    password: '',
    is_default: admins.value.length === 0,
  }
  adminDialogVisible.value = true
}

function openEditAdmin(row: AdminRow) {
  editingAdminId.value = row.id
  editingAdminAccount.value = row.account
  adminForm.value = {
    name: row.name,
    account: row.account,
    password: '',
    is_default: row.is_default,
  }
  adminDialogVisible.value = true
}

async function saveAdmin() {
  const name = adminForm.value.name.trim()
  const account = adminForm.value.account.trim()
  const password = adminForm.value.password
  if (!name || !account || (!editingAdminId.value && !password)) {
    ElMessage.warning('请填写名称、账号和密码')
    return
  }
  if (editingAdminId.value && account !== editingAdminAccount.value && !password) {
    ElMessage.warning('修改登录账号时必须重新填写密码')
    return
  }

  adminSaving.value = true
  try {
    let adminId = editingAdminId.value
    if (adminId) {
      const payload: Record<string, any> = {
        name,
        account,
        is_default: adminForm.value.is_default,
      }
      if (password) payload.password = password
      await apiPut(`/mcp-platform/apaas-admins/${editingAdminId.value}`, payload)
    } else {
      const created = await apiPost<AdminRow>('/mcp-platform/apaas-admins', {
        name,
        account,
        password,
        is_default: adminForm.value.is_default,
      })
      adminId = created.id
    }

    try {
      await apiPost(`/mcp-platform/apaas-admins/${adminId}/login`)
      ElMessage.success('账号已保存并登录')
    } catch (e: any) {
      ElMessage.warning(`账号已保存，但登录失败：${errorMessage(e, '请检查账号密码')}`)
    }
    selectedAdminId.value = adminId
    adminDialogVisible.value = false
    await loadAdmins()
  } catch (e: any) {
    ElMessage.error(errorMessage(e, '保存失败'))
  } finally {
    adminSaving.value = false
  }
}

async function loginAdmin(row: AdminRow) {
  row._logging = true
  try {
    await apiPost(`/mcp-platform/apaas-admins/${row.id}/login`)
    selectedAdminId.value = row.id
    ElMessage.success('aPaaS 登录成功')
    await loadAdmins()
  } catch (e: any) {
    ElMessage.error(errorMessage(e, '登录失败'))
  } finally {
    row._logging = false
  }
}

async function setDefaultAdmin(row: AdminRow) {
  try {
    await apiPut(`/mcp-platform/apaas-admins/${row.id}`, { is_default: true })
    selectedAdminId.value = row.id
    await loadAdmins()
    ElMessage.success('已设为默认账号')
  } catch (e: any) {
    ElMessage.error(errorMessage(e, '设置失败'))
  }
}

async function deleteAdmin(row: AdminRow) {
  try {
    await ElMessageBox.confirm(`确认删除账号“${row.account}”？`, '删除平台管理员账号', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
    await apiDel(`/mcp-platform/apaas-admins/${row.id}`)
    await loadAdmins()
    ElMessage.success('账号已删除')
  } catch (e: any) {
    if (e === 'cancel' || e === 'close') return
    ElMessage.error(errorMessage(e, '删除失败'))
  }
}

function openBinding(row: any) {
  const admin = admins.value.find((item) => item.id === selectedAdminId.value)
    || admins.value.find((item) => item.is_default)
    || admins.value[0]
  bindingTarget.value = row
  bindingForm.value = {
    admin_id: admin?.id || '',
    base_url: row.baseUrl || admin?.base_url || '',
    platform_tenant_id: row.platformTenantId || pick(row, ['tenantId', 'tenant_id']) || '',
  }
  bindingVisible.value = true
}

async function saveBinding() {
  if (
    !bindingTarget.value
    || !bindingForm.value.admin_id
    || !bindingForm.value.base_url.trim()
    || !bindingForm.value.platform_tenant_id.trim()
  ) {
    ElMessage.warning('请选择平台管理员并填写 aPaaS 地址和租户 ID')
    return
  }
  bindingSaving.value = true
  try {
    await apiPut(`/mcp-platform/apaas-tenants/${bindingTarget.value.localTenantId}/binding`, {
      admin_id: bindingForm.value.admin_id,
      base_url: bindingForm.value.base_url.trim(),
      platform_tenant_id: bindingForm.value.platform_tenant_id.trim(),
    })
    bindingVisible.value = false
    await loadLocalTenants()
    ElMessage.success('环境绑定已保存')
  } catch (e: any) {
    ElMessage.error(errorMessage(e, '环境绑定失败'))
  } finally {
    bindingSaving.value = false
  }
}

async function loadLocalTenants() {
  loading.value = true
  error.value = ''
  try {
    const resp = await apiGet<{ items: any[]; synced?: { tenants?: number; envs?: number } }>('/mcp-platform/apaas-tenants', {
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
      page_size: 500,
    })
    const remoteCount = resp.items?.length || 0
    const synced = resp.synced || {}
    await loadLocalTenants()
    if (!options.silent) {
      ElMessage.success(`已刷新 ${remoteCount} 个租户，同步本地 ${synced.tenants ?? 0} 个租户 / ${synced.envs ?? 0} 个环境`)
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
/* v3 token 化 · 2026-05-20 — visual refresh only. template/script untouched. */
/* v3 2026-05-21 — 跟 frontend 密度对齐：max-width/h1/page-header 都交给
   density-align.css 全局规则。本 scoped 只保留 layout + card-head/meta。 */
.page {
  color: var(--text);
  font-family: var(--font-sans);
}
.page-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}
.page-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.card-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}
.card-meta {
  color: var(--text-3);
  font-size: 12px;
  font-weight: var(--fw-medium, 500);
  margin-left: 10px;
}
.admin-card {
  margin-bottom: 16px;
}
.binding-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.binding-tenant-id {
  color: var(--text-3);
  font-family: var(--font-mono);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  padding: 12px 0 4px;
}
</style>
