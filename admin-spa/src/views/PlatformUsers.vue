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
