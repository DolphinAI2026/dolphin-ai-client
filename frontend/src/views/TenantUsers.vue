<template>
  <BuilderFrame :breadcrumbs="[{ label: '设置' }, { label: '成员管理' }]">
    <template #actions>
      <el-button @click="loadAll" :loading="loading">刷新</el-button>
      <el-button type="primary" @click="openInviteDialog">添加用户</el-button>
    </template>
    <div class="tenant-users-page builder-page">
      <div class="tenant-users-header">
        <div>
          <h1>{{ pageTitle }}</h1>
          <p>{{ pageDesc }}</p>
          <p class="tenant-users-note">{{ pageNote }}</p>
        </div>
      </div>

      <div class="tenant-users-filter">
        <el-input
          v-model="filterQ"
          placeholder="按用户名搜索"
          clearable
          style="width: 240px"
        />
        <el-select
          v-if="isPlatformAdmin"
          v-model="filterTenant"
          filterable
          clearable
          placeholder="按所属组织过滤"
          style="width: 220px"
        >
          <el-option
            v-for="opt in tenantFilterOptions"
            :key="opt.value"
            :label="`${opt.label}（${opt.count}）`"
            :value="opt.value"
          />
        </el-select>
        <el-select v-model="filterRole" clearable placeholder="按权限视图过滤" style="width: 180px">
          <el-option label="平台超级管理员" value="platform_admin" />
          <el-option label="租户管理员" value="tenant_admin" />
          <el-option label="开发者" value="developer" />
          <el-option label="查看者" value="viewer" />
          <el-option label="普通成员" value="member" />
        </el-select>
        <span class="tenant-users-summary">
          共 {{ filteredUsers.length }} 条{{ filteredUsers.length !== users.length ? `（已从 ${users.length} 条过滤）` : '' }}
        </span>
      </div>

      <div class="tenant-users-panel">
        <el-table v-loading="loading" :data="pagedUsers" stripe>
          <el-table-column prop="username" label="用户名" min-width="180" />
          <el-table-column v-if="isPlatformAdmin" label="所属组织" min-width="220">
            <template #default="{ row }">
              {{ row.tenant_summary || row.tenant_name || '-' }}
            </template>
          </el-table-column>
          <el-table-column label="组织角色" min-width="180">
            <template #default="{ row }">
              <el-select
                :model-value="row.role_code || ''"
                size="small"
                style="width: 150px"
                :disabled="isPlatformAdmin && row.id === userStore.user?.id"
                @change="(val: string) => updateRole(row, val)"
              >
                <el-option
                  v-for="role in roles"
                  :key="role.role_code"
                  :label="role.role_name"
                  :value="role.role_code"
                />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="成员状态" width="140">
            <template #default="{ row }">
              <el-switch
                :model-value="row.tenant_status === 1"
                :disabled="isPlatformAdmin && row.id === userStore.user?.id"
                @change="(val: boolean) => updateStatus(row, val)"
              />
            </template>
          </el-table-column>
          <el-table-column label="权限视图" min-width="150">
            <template #default="{ row }">
              <el-tag
                :type="roleTagType(row.tenant_role)"
                size="small"
              >
                {{ roleLabel(row.tenant_role) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="加入时间" min-width="180">
            <template #default="{ row }">
              {{ formatDate(row.joined_at || row.created_at) }}
            </template>
          </el-table-column>
        </el-table>

        <div class="tenant-users-pager">
          <el-pagination
            v-model:current-page="currentPage"
            v-model:page-size="pageSize"
            :total="filteredUsers.length"
            :page-sizes="[10, 20, 50, 100]"
            layout="total, sizes, prev, pager, next, jumper"
            background
          />
        </div>
      </div>

      <el-dialog v-model="dialogVisible" :title="isPlatformAdmin ? '添加平台账号' : '添加用户到当前组织'" width="480px">
        <el-form :model="inviteForm" label-position="top">
          <el-form-item label="用户名" required>
            <el-input v-model="inviteForm.username" placeholder="输入已有用户名，例如 mars；账号不存在时会新建" />
          </el-form-item>
          <el-form-item label="初始密码">
            <el-input v-model="inviteForm.password" type="password" show-password placeholder="仅当账号不存在时需要填写" />
          </el-form-item>
          <el-form-item label="平台角色">
            <el-select v-model="inviteForm.role_code" style="width: 100%">
              <el-option
                v-for="role in roles"
                :key="role.role_code"
                :label="role.role_name"
                :value="role.role_code"
              />
            </el-select>
          </el-form-item>
          <el-form-item v-if="isPlatformAdmin" label="加入到租户（可选）">
            <el-select
              v-model="inviteForm.tenant_id"
              filterable
              clearable
              placeholder="不选则只建账号、不绑组织（用户登录后看不到任何业务）"
              style="width: 100%"
              :loading="tenantsLoading"
            >
              <el-option
                v-for="t in availableTenants"
                :key="t.id"
                :label="`${t.tenant_name}（${t.tenant_code}）`"
                :value="t.id"
              />
            </el-select>
            <div class="form-hint">
              选了租户后，账号会自动以「开发者」角色加入；之后可在「租户管理 → 详情」里改角色。
            </div>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="dialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="inviteUser">添加</el-button>
        </template>
      </el-dialog>
    </div>
  </BuilderFrame>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import BuilderFrame from '@/components/BuilderFrame.vue'
import { authApi, type TenantAdminItem, type TenantRoleOption, type TenantUser } from '@/api/auth'
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()
const loading = ref(false)
const saving = ref(false)
const users = ref<TenantUser[]>([])
const roles = ref<TenantRoleOption[]>([])
const dialogVisible = ref(false)
const inviteForm = ref<{
  username: string
  password: string
  role_code: string
  tenant_id?: number
}>({
  username: '',
  password: '',
  role_code: 'R_developer',
  tenant_id: undefined,
})

// 仅 platform_admin 用：account 添加时可选关联租户
const availableTenants = ref<TenantAdminItem[]>([])
const tenantsLoading = ref(false)

// 列表过滤 + 分页
const filterQ = ref('')
const filterTenant = ref('')
const filterRole = ref('')
const currentPage = ref(1)
const pageSize = ref(20)

// 提取所有出现过的"所属组织"做下拉选项（按出现次数排序，每个组织带计数）
const tenantFilterOptions = computed(() => {
  const counts = new Map<string, number>()
  for (const u of users.value) {
    const summary = (u.tenant_summary || u.tenant_name || '').trim()
    if (!summary) continue
    // 一个用户可能属多个组织（"体验租户、白客松比赛"），按顿号拆开
    for (const name of summary.split(/[、,，]/).map((s) => s.trim()).filter(Boolean)) {
      counts.set(name, (counts.get(name) || 0) + 1)
    }
  }
  return Array.from(counts.entries())
    .sort((a, b) => b[1] - a[1])
    .map(([label, count]) => ({ label, value: label, count }))
})

const filteredUsers = computed(() => {
  const q = filterQ.value.trim().toLowerCase()
  const tenant = filterTenant.value.trim()
  const role = filterRole.value.trim()
  return users.value.filter((u) => {
    if (q && !u.username.toLowerCase().includes(q)) return false
    if (tenant) {
      const summary = (u.tenant_summary || u.tenant_name || '')
      if (!summary.includes(tenant)) return false
    }
    if (role && u.tenant_role !== role) return false
    return true
  })
})

const pagedUsers = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredUsers.value.slice(start, start + pageSize.value)
})

// 过滤变化时回到第一页
watch([filterQ, filterTenant, filterRole, pageSize], () => {
  currentPage.value = 1
})

async function loadTenantOptions() {
  if (!isPlatformAdmin.value) return
  tenantsLoading.value = true
  try {
    availableTenants.value = await authApi.listAllTenants({ status: 1 })
  } catch {
    availableTenants.value = []
  } finally {
    tenantsLoading.value = false
  }
}
const isPlatformAdmin = computed(() => userStore.tenantRole === 'platform_admin')
const pageTitle = computed(() => isPlatformAdmin.value ? '账号管理' : '成员管理')
const pageDesc = computed(() =>
  isPlatformAdmin.value
    ? '管理平台内全部账号的启停状态和最高权限。'
    : '管理当前组织内的普通用户、租户角色和启停状态。'
)
const pageNote = computed(() =>
  isPlatformAdmin.value
    ? '平台超级管理员可以查看全部组织账号；普通账号仍需加入具体组织后才能进入业务工作台。'
    : '自注册账号会先进入自己的独立组织；如需加入本组织，请用「添加用户」输入已有用户名。'
)

function roleLabel(role: TenantUser['tenant_role']) {
  if (role === 'platform_admin') return '平台超级管理员'
  if (role === 'tenant_admin') return '租户管理员'
  if (role === 'developer') return '开发者'
  if (role === 'viewer') return '查看者'
  return '成员'
}

function roleTagType(role: TenantUser['tenant_role']) {
  if (role === 'platform_admin') return 'danger'
  if (role === 'tenant_admin') return 'warning'
  if (role === 'developer') return 'primary'
  return 'info'
}

function formatDate(value?: string | null) {
  if (!value) return '-'
  return value.replace('T', ' ').slice(0, 19)
}

async function loadAll() {
  loading.value = true
  try {
    const [roleList, userList] = await Promise.all([
      authApi.listTenantRoles(),
      authApi.listTenantUsers(),
    ])
    roles.value = roleList
    users.value = userList
    const firstRoleCode = roleList[0]?.role_code
    if (isPlatformAdmin.value && inviteForm.value.role_code === 'R_developer') {
      inviteForm.value.role_code = 'normal_user'
    } else if (!inviteForm.value.role_code && firstRoleCode) {
      inviteForm.value.role_code = firstRoleCode
    }
  } catch (error: any) {
    ElMessage.error(error.message || '加载用户管理数据失败')
  } finally {
    loading.value = false
  }
}

async function updateRole(user: TenantUser, roleCode: string) {
  try {
    const updated = await authApi.updateTenantUserRole(user.id, roleCode)
    users.value = users.value.map(item => (item.id === user.id ? updated : item))
    ElMessage.success(`已更新 ${user.username} 的角色`)
  } catch (error: any) {
    ElMessage.error(error.message || '更新角色失败')
  }
}

async function updateStatus(user: TenantUser, enabled: boolean) {
  try {
    const updated = await authApi.updateTenantUserStatus(user.id, enabled ? 1 : 0)
    users.value = users.value.map(item => (item.id === user.id ? updated : item))
    ElMessage.success(`${enabled ? '已启用' : '已禁用'} ${user.username}`)
  } catch (error: any) {
    ElMessage.error(error.message || '更新状态失败')
  }
}

function openInviteDialog() {
  inviteForm.value = {
    username: '',
    password: '',
    role_code: isPlatformAdmin.value ? 'normal_user' : 'R_developer',
    tenant_id: undefined,
  }
  dialogVisible.value = true
  loadTenantOptions()
}

async function inviteUser() {
  if (!inviteForm.value.username.trim()) {
    ElMessage.warning('请输入用户名')
    return
  }
  saving.value = true
  try {
    const created = await authApi.inviteTenantUser({
      username: inviteForm.value.username.trim(),
      password: inviteForm.value.password.trim() || undefined,
      role_code: inviteForm.value.role_code,
      tenant_id: isPlatformAdmin.value ? inviteForm.value.tenant_id : undefined,
    })
    users.value = [...users.value.filter(item => item.id !== created.id), created]
    dialogVisible.value = false
    inviteForm.value = {
      username: '',
      password: '',
      role_code: isPlatformAdmin.value ? 'normal_user' : roles.value[0]?.role_code || 'R_developer',
      tenant_id: undefined,
    }
    await loadAll()
    if (isPlatformAdmin.value && inviteForm.value.tenant_id) {
      ElMessage.success('账号已创建并加入指定租户')
    } else {
      ElMessage.success('用户已加入当前组织')
    }
  } catch (error: any) {
    ElMessage.error(error.message || '添加用户失败')
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  loadAll()
})
</script>

<style scoped>
.tenant-users-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
  background: var(--b-bg);
}

.tenant-users-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.tenant-users-actions {
  display: flex;
  gap: 10px;
}

.tenant-users-header h1 {
  margin: 0;
  font-size: 18px;
  color: var(--b-text);
  letter-spacing: 0;
}

.tenant-users-header p {
  margin: 5px 0 0;
  color: var(--b-text-muted);
  font-size: 12px;
}

.tenant-users-header .tenant-users-note {
  color: var(--b-text-dim);
}

.tenant-users-panel {
  background: var(--b-panel);
  border: 1px solid var(--b-line);
  border-radius: 8px;
  padding: 10px;
  box-shadow: var(--b-shadow-xs);
}

.tenant-users-panel :deep(.el-table) {
  --el-table-header-bg-color: var(--b-panel-soft);
  --el-table-tr-bg-color: var(--b-panel);
  --el-table-row-hover-bg-color: var(--b-bg-sub);
  --el-table-border-color: var(--b-line);
  color: var(--b-text);
  font-size: 12px;
}

.tenant-users-panel :deep(.el-table th.el-table__cell) {
  color: var(--b-text-muted);
  font-weight: 700;
}

.tenant-users-panel :deep(.el-table td.el-table__cell) {
  color: var(--b-text);
}

:deep(.builder-topbar .el-button) {
  height: 30px;
  border-radius: 7px;
  font-size: 12px;
  font-weight: 700;
}

.form-hint {
  margin-top: 4px;
  font-size: 12px;
  color: var(--b-text-muted, #999);
  line-height: 1.5;
}

.tenant-users-filter {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.tenant-users-summary {
  font-size: 12px;
  color: var(--b-text-muted, #999);
  margin-left: auto;
}
.tenant-users-pager {
  display: flex;
  justify-content: flex-end;
  padding: 16px 8px 4px;
}
</style>
