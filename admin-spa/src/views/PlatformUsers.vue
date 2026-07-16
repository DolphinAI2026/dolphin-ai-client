<template>
  <div class="page members-page">
    <div class="page-header">
      <div>
        <h1>成员管理</h1>
        <p>成员来自 Control Plane、aPaaS 或本地同步；可在这里维护账号与 aPaaS 租户的绑定关系。</p>
      </div>
      <div class="page-actions">
        <el-input v-model="keyword" class="search-input" clearable placeholder="搜索姓名、账号、租户、身份" />
        <el-button @click="load" :loading="loading">刷新</el-button>
      </div>
    </div>

    <section class="summary-grid">
      <article class="summary-card">
        <span>成员总数</span>
        <strong>{{ filteredMembers.length }}</strong>
      </article>
      <article class="summary-card">
        <span>平台管理员</span>
        <strong>{{ filteredPlatformAdmins.length }}</strong>
      </article>
      <article class="summary-card">
        <span>租户管理员</span>
        <strong>{{ filteredTenantMembers.length }}</strong>
      </article>
    </section>

    <section class="member-panel">
      <div class="panel-head">
        <div>
          <strong>平台管理员</strong>
          <span>平台级身份，不归属到某个租户</span>
        </div>
      </div>
      <el-table :data="filteredPlatformAdmins" v-loading="membersLoading" stripe empty-text="暂无平台管理员">
        <el-table-column label="姓名" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">{{ userDisplayName(row) }}</template>
        </el-table-column>
        <el-table-column label="账号" prop="username" min-width="180" show-overflow-tooltip />
        <el-table-column label="来源" width="120">
          <template #default="{ row }">
            <el-tag :type="accountSourceTag(row)" size="small">{{ accountSourceLabel(row) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="aPaaS 绑定" min-width="190" show-overflow-tooltip>
          <template #default="{ row }">
            <span :class="row.apaas_bound ? 'bind-ok' : 'bind-missing'">
              {{ row.apaas_bound ? row.apaas_tenant_id : '未绑定' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="身份" min-width="150">
          <template #default="{ row }">
            <el-tag type="success" size="small">{{ roleLabel(row) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'" size="small">{{ row.is_active ? '启用' : '禁用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" prop="created_at" min-width="190" show-overflow-tooltip />
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openBindDialog(row)">绑定 aPaaS</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <section class="member-panel">
      <div class="panel-head">
        <div>
          <strong>租户管理员</strong>
          <span>一个账号只算一个成员，多个租户会合并到租户列</span>
        </div>
      </div>
      <el-table :data="filteredTenantMembers" v-loading="membersLoading" stripe empty-text="暂无租户管理员">
        <el-table-column label="姓名" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">{{ userDisplayName(row) }}</template>
        </el-table-column>
        <el-table-column label="账号" prop="username" min-width="180" show-overflow-tooltip />
        <el-table-column label="来源" width="120">
          <template #default="{ row }">
            <el-tag :type="accountSourceTag(row)" size="small">{{ accountSourceLabel(row) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="租户" min-width="260" show-overflow-tooltip>
          <template #default="{ row }">{{ row.tenant_summary || row.tenant_name || '未加入租户' }}</template>
        </el-table-column>
        <el-table-column label="aPaaS 绑定" min-width="190" show-overflow-tooltip>
          <template #default="{ row }">
            <span :class="row.apaas_bound ? 'bind-ok' : 'bind-missing'">
              {{ row.apaas_bound ? row.apaas_tenant_id : '未绑定' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="身份" min-width="150">
          <template #default="{ row }">
            <el-tag :type="roleTag(row)" size="small">{{ roleLabel(row) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'" size="small">{{ row.is_active ? '启用' : '禁用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" prop="created_at" min-width="190" show-overflow-tooltip />
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openBindDialog(row)">绑定 aPaaS</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog
      v-model="bindDialogVisible"
      title="绑定 aPaaS 账号"
      width="460px"
      destroy-on-close
      @closed="resetBindDialog"
    >
      <div v-if="bindTarget" class="bind-summary">
        <strong>{{ userDisplayName(bindTarget) }}</strong>
        <span>{{ bindTarget.username }} · {{ accountSourceLabel(bindTarget) }}</span>
      </div>
      <el-form label-position="top" @submit.prevent>
        <el-form-item label="aPaaS 账号">
          <el-input v-model="bindForm.username" autocomplete="off" placeholder="请输入 aPaaS 账号" />
        </el-form-item>
        <el-form-item label="aPaaS 密码">
          <el-input
            v-model="bindForm.password"
            autocomplete="new-password"
            placeholder="请输入 aPaaS 密码"
            show-password
            type="password"
          />
        </el-form-item>
        <el-form-item label="aPaaS 租户 ID">
          <el-input v-model="bindForm.apaas_tenant_id" clearable placeholder="留空使用该账号默认租户" />
          <p class="bind-help">只在账号可登录多个租户或需要指定租户时填写。</p>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="bindDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="binding" @click="submitBinding">保存绑定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiGet, apiPost } from '@/api/client'

interface MemberRow {
  id: number
  username: string
  display_name?: string | null
  is_active: boolean
  is_platform_admin: boolean
  tenant_name?: string | null
  tenant_summary?: string | null
  tenant_role: string
  role_name?: string | null
  created_at?: string | null
  account_source?: string | null
  apaas_user_id?: string | null
  apaas_tenant_id?: string | null
  coding_user_id?: string | null
  apaas_bound?: boolean
}

const members = ref<MemberRow[]>([])
const keyword = ref('')
const loading = ref(false)
const membersLoading = ref(false)
const bindDialogVisible = ref(false)
const binding = ref(false)
const bindTarget = ref<MemberRow | null>(null)
const bindForm = ref({
  username: '',
  password: '',
  apaas_tenant_id: '',
})

const filteredMembers = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return members.value
  return members.value.filter((row) => [
    row.display_name,
    row.username,
    row.tenant_name,
    row.tenant_summary,
    row.apaas_tenant_id,
    accountSourceLabel(row),
    roleLabel(row),
  ].some((value) => String(value || '').toLowerCase().includes(kw)))
})

const filteredPlatformAdmins = computed(() => filteredMembers.value.filter((row) => row.is_platform_admin))
const filteredTenantMembers = computed(() => filteredMembers.value.filter((row) => !row.is_platform_admin))

async function loadMembers() {
  membersLoading.value = true
  try {
    members.value = await apiGet<MemberRow[]>('/auth/tenant-users')
  } catch (e: any) {
    members.value = []
    ElMessage.error(e?.response?.data?.detail || e?.message || '加载成员失败')
  } finally {
    membersLoading.value = false
  }
}

async function load() {
  loading.value = true
  try {
    await loadMembers()
  } finally {
    loading.value = false
  }
}

function userDisplayName(row: Pick<MemberRow, 'username' | 'display_name'>) {
  return row.display_name || row.username
}

function roleLabel(row: Pick<MemberRow, 'is_platform_admin' | 'tenant_role'>) {
  return row.is_platform_admin || row.tenant_role === 'platform_admin' ? '平台管理员' : '租户管理员'
}

function roleTag(row: Pick<MemberRow, 'is_platform_admin' | 'tenant_role'>) {
  return row.is_platform_admin || row.tenant_role === 'platform_admin' ? 'success' : 'warning'
}

function accountSourceLabel(row: Pick<MemberRow, 'account_source'>) {
  const source = row.account_source || 'apaas'
  if (source === 'coding') return 'Control Plane'
  if (source === 'apaas') return 'aPaaS'
  if (source === 'desktop') return '本地账号'
  return source
}

function accountSourceTag(row: Pick<MemberRow, 'account_source'>) {
  const source = row.account_source || 'apaas'
  if (source === 'coding') return 'warning'
  if (source === 'apaas') return 'success'
  return 'info'
}

function openBindDialog(row: MemberRow) {
  bindTarget.value = row
  bindForm.value = {
    username: row.apaas_bound ? '' : row.username,
    password: '',
    apaas_tenant_id: row.apaas_tenant_id || '',
  }
  bindDialogVisible.value = true
}

function resetBindDialog() {
  bindTarget.value = null
  bindForm.value = { username: '', password: '', apaas_tenant_id: '' }
}

async function submitBinding() {
  if (!bindTarget.value) return
  const username = bindForm.value.username.trim()
  const password = bindForm.value.password
  const apaasTenantId = bindForm.value.apaas_tenant_id.trim()
  if (!username) {
    ElMessage.warning('请输入 aPaaS 账号')
    return
  }
  if (!password) {
    ElMessage.warning('请输入 aPaaS 密码')
    return
  }
  binding.value = true
  try {
    const updated = await apiPost<MemberRow>(`/auth/users/${bindTarget.value.id}/apaas-binding`, {
      username,
      password,
      apaas_tenant_id: apaasTenantId || undefined,
    })
    members.value = members.value.map((row) => (row.id === updated.id ? updated : row))
    ElMessage.success('aPaaS 账号已绑定')
    bindDialogVisible.value = false
    await loadMembers()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '绑定失败')
  } finally {
    binding.value = false
  }
}

onMounted(load)
</script>

<style scoped>
/* v3 token 化 · 2026-05-20 — visual refresh only. template/script untouched.
   Tokens: design-v3-tokens.css. v2 紫色全 swap 到 v3 slate ramp + line + surface。 */
/* v3 2026-05-21 — 跟 frontend 密度对齐：max-width/h1/page-header/summary-card/panel-head
   都交给 density-align.css 全局规则。本 scoped 只保留 admin-spa 特有的 search-input 宽度
   + member-panel container + el-table token 设置。 */
.members-page {
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
  justify-content: flex-end;
}
.search-input { width: 240px; }
.bind-ok {
  color: var(--text-2);
  font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace);
  font-size: 12px;
}
.bind-missing {
  color: var(--text-4);
}
.bind-summary {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 12px;
  margin-bottom: 14px;
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  background: var(--surface-2);
}
.bind-summary span,
.bind-help {
  color: var(--text-3);
  font-size: 12px;
}
.bind-help {
  margin: 6px 0 0;
  line-height: 1.5;
}
.summary-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}
.member-panel {
  overflow: hidden;
  margin-top: 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-4, 12px);
  background: var(--surface);
  box-shadow: var(--sh-1);
}
.panel-head {
  /* density-align.css 全局已统一 min-height/padding/title — 仅保留 layout */
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  border-bottom: 1px solid var(--line);
}
.member-panel :deep(.el-table) {
  --el-table-header-bg-color: var(--surface-2);
  --el-table-header-text-color: var(--text-3);
  --el-table-text-color: var(--text-2);
  --el-table-row-hover-bg-color: var(--surface-2);
  --el-table-border-color: var(--line);
}
.member-panel :deep(.el-table th.el-table__cell) {
  font-weight: var(--fw-semibold, 600);
  font-size: 12px;
  letter-spacing: 0.02em;
}
@media (max-width: 860px) {
  .summary-grid { grid-template-columns: 1fr; }
  .search-input { width: 100%; }
}
</style>
