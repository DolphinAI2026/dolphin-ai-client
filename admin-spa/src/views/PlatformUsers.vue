<template>
  <div class="page members-page">
    <div class="page-header">
      <div>
        <h1>成员管理</h1>
        <p>成员来源于 aPaaS 登录镜像，平台管理员和租户成员分开展示；账号、密码和权限仍以 aPaaS 为准。</p>
      </div>
      <div class="page-actions">
        <el-input v-model="keyword" class="search-input" clearable placeholder="搜索账号、租户、角色" />
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
        <span>租户成员</span>
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
        <el-table-column label="账号" prop="username" min-width="180" show-overflow-tooltip />
        <el-table-column label="身份" min-width="150">
          <template #default="{ row }">
            <el-tag type="success" size="small">{{ roleLabel(row.tenant_role, row.role_name) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'" size="small">{{ row.is_active ? '启用' : '禁用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" prop="created_at" min-width="190" show-overflow-tooltip />
      </el-table>
    </section>

    <section class="member-panel">
      <div class="panel-head">
        <div>
          <strong>租户成员</strong>
          <span>一个账号只算一个成员，多个租户会合并到租户列</span>
        </div>
      </div>
      <el-table :data="filteredTenantMembers" v-loading="membersLoading" stripe empty-text="暂无租户成员">
        <el-table-column label="账号" prop="username" min-width="180" show-overflow-tooltip />
        <el-table-column label="租户" min-width="260" show-overflow-tooltip>
          <template #default="{ row }">{{ row.tenant_summary || row.tenant_name || '未加入租户' }}</template>
        </el-table-column>
        <el-table-column label="身份" min-width="150">
          <template #default="{ row }">
            <el-tag :type="roleTag(row.tenant_role)" size="small">{{ roleLabel(row.tenant_role, row.role_name) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'" size="small">{{ row.is_active ? '启用' : '禁用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" prop="created_at" min-width="190" show-overflow-tooltip />
      </el-table>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiGet } from '@/api/client'

interface MemberRow {
  id: number
  username: string
  is_active: boolean
  is_platform_admin: boolean
  tenant_name?: string | null
  tenant_summary?: string | null
  tenant_role: string
  role_name?: string | null
  created_at?: string | null
}

const members = ref<MemberRow[]>([])
const keyword = ref('')
const loading = ref(false)
const membersLoading = ref(false)

const filteredMembers = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return members.value
  return members.value.filter((row) => [
    row.username,
    row.tenant_name,
    row.tenant_summary,
    row.tenant_role,
    row.role_name,
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

function roleLabel(role: string, roleName?: string | null) {
  if (role === 'platform_admin') return '平台管理员'
  if (role === 'tenant_admin') return roleName || '租户管理员'
  if (role === 'developer') return roleName || '开发者'
  if (role === 'viewer') return roleName || '查看者'
  return roleName || '成员'
}

function roleTag(role: string) {
  if (role === 'platform_admin') return 'success'
  if (role === 'tenant_admin') return 'warning'
  if (role === 'developer') return 'primary'
  return 'info'
}

onMounted(load)
</script>

<style scoped>
/* v3 token 化 · 2026-05-20 — visual refresh only. template/script untouched.
   Tokens: design-v3-tokens.css. v2 紫色全 swap 到 v3 slate ramp + line + surface。 */
.members-page {
  max-width: 1440px;
  margin: 0 auto;
  padding: 8px 0 56px;
  color: var(--text);
  font-family: var(--font-sans);
}
.page-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 22px;
  flex-wrap: wrap;
}
.page-header h1 {
  margin: 0;
  color: var(--text);
  font-size: 22px;
  line-height: 1.25;
  font-weight: var(--fw-bold, 700);
  letter-spacing: -0.01em;
}
.page-header p {
  max-width: 900px;
  margin: 8px 0 0;
  color: var(--text-3);
  font-size: 13.5px;
  line-height: 1.55;
}
.page-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.search-input { width: 280px; }
.search-input :deep(.el-input__wrapper) {
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--r-2, 6px);
  box-shadow: none;
  height: 32px;
}
.search-input :deep(.el-input__wrapper.is-focus) {
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-ring);
}
.summary-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.summary-card {
  min-height: auto;
  padding: 14px 16px;
  border: 1px solid var(--line);
  border-radius: var(--r-4, 12px);
  background: var(--surface);
  box-shadow: var(--sh-1);
}
.summary-card span {
  display: block;
  color: var(--text-3);
  font-size: 11px;
  font-weight: var(--fw-medium, 500);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.summary-card strong {
  display: block;
  margin-top: 4px;
  color: var(--text);
  font-size: 22px;
  line-height: 1.1;
  font-weight: var(--fw-bold, 700);
  letter-spacing: -0.02em;
  font-feature-settings: 'tnum';
}
.member-panel {
  overflow: hidden;
  margin-top: 16px;
  border: 1px solid var(--line);
  border-radius: var(--r-4, 12px);
  background: var(--surface);
  box-shadow: var(--sh-1);
}
.panel-head {
  min-height: 52px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 0 18px;
  border-bottom: 1px solid var(--line);
  background: var(--surface);
}
.panel-head strong {
  color: var(--text);
  font-size: 13.5px;
  font-weight: var(--fw-semibold, 600);
}
.panel-head span {
  margin-left: 8px;
  color: var(--text-3);
  font-size: 12px;
  font-weight: var(--fw-medium, 500);
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
