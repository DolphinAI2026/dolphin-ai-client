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
        <el-table-column label="创建时间" prop="created_at" min-width="170" show-overflow-tooltip />
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
        <el-table-column label="创建时间" prop="created_at" min-width="170" show-overflow-tooltip />
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
.members-page { max-width: 1440px; margin: 0 auto; padding: 8px 0 56px; color: #17162f; }
.page-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; margin-bottom: 22px; flex-wrap: wrap; }
.page-header h1 { margin: 0; color: #17162f; font-size: 32px; line-height: 1.2; font-weight: 820; }
.page-header p { max-width: 900px; margin: 14px 0 0; color: #5f5a7c; font-size: 16px; line-height: 1.7; }
.page-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; justify-content: flex-end; }
.search-input { width: 280px; }
.summary-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; margin-bottom: 20px; }
.summary-card { min-height: 94px; padding: 20px; border: 1px solid #ded9eb; border-radius: 14px; background: rgba(255,255,255,.94); box-shadow: 0 10px 24px rgba(34,30,70,.07); }
.summary-card span { display: block; color: #8a85a5; font-size: 14px; font-weight: 720; }
.summary-card strong { display: block; margin-top: 8px; color: #17162f; font-size: 28px; line-height: 1.1; font-weight: 820; }
.member-panel { overflow: hidden; margin-top: 20px; border: 1px solid #ded9eb; border-radius: 16px; background: rgba(255,255,255,.94); box-shadow: 0 10px 24px rgba(34,30,70,.07); }
.panel-head { min-height: 62px; display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 0 22px; border-bottom: 1px solid #ece8f6; background: #f3f0fb; }
.panel-head strong { color: #17162f; font-size: 17px; font-weight: 820; }
.panel-head span { margin-left: 10px; color: #8a85a5; font-size: 13px; font-weight: 700; }
.member-panel :deep(.el-table) { --el-table-header-bg-color: #f3f0fb; --el-table-header-text-color: #8a85a5; --el-table-text-color: #5f5a7c; --el-table-row-hover-bg-color: #fbfaff; }
.member-panel :deep(.el-table th.el-table__cell) { font-weight: 760; }
@media (max-width: 860px) { .summary-grid { grid-template-columns: 1fr; } .search-input { width: 100%; } }
</style>
