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
          placeholder="按姓名或账号搜索"
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
          <template #empty>
            <EmptyState
              :variant="(filterQ || filterRole || filterTenant) ? 'filtered' : 'first'"
              :title="(filterQ || filterRole || filterTenant) ? '没有匹配的成员' : '还没有成员'"
              :desc="(filterQ || filterRole || filterTenant) ? '换个关键词，或清空筛选条件查看所有成员。' : '添加成员，分配角色（管理员 / 开发者 / 查看者），让团队一起协作。'"
            >
              <template #icon>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="20" y1="8" x2="20" y2="14"/><line x1="23" y1="11" x2="17" y2="11"/></svg>
              </template>
              <template v-if="filterQ || filterRole || filterTenant" #cta>
                <el-button @click="() => { filterQ = ''; filterRole = ''; filterTenant = '' }">清空筛选</el-button>
              </template>
              <template v-else #cta>
                <el-button type="primary" @click="openInviteDialog">添加用户</el-button>
              </template>
            </EmptyState>
          </template>
          <el-table-column label="姓名 / 账号" min-width="220">
            <template #default="{ row }">
              <div class="user-identity">
                <strong>{{ userDisplayName(row) }}</strong>
                <span v-if="row.username !== userDisplayName(row)">{{ row.username }}</span>
              </div>
            </template>
          </el-table-column>
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
          <el-table-column label="操作" width="120" fixed="right">
            <template #default="{ row }">
              <el-button
                v-if="canResetPassword(row)"
                link
                type="primary"
                size="small"
                @click="openResetPwd(row)"
              >重置密码</el-button>
              <span v-else class="row-action-disabled">-</span>
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

      <!-- 重置密码对话框 -->
      <el-dialog v-model="resetPwdVisible" :title="`重置密码 — ${resetPwdTarget ? userDisplayName(resetPwdTarget) : ''}`" width="420px">
        <el-form label-position="top">
          <el-form-item label="新密码" required>
            <el-input
              v-model="resetPwdForm.new_password"
              type="password"
              show-password
              placeholder="6-128 位"
              maxlength="128"
            />
          </el-form-item>
          <el-form-item label="确认新密码" required>
            <el-input
              v-model="resetPwdForm.confirm"
              type="password"
              show-password
              placeholder="再输一遍"
              maxlength="128"
            />
          </el-form-item>
          <div class="form-hint">
            重置后旧密码立即失效；用户已签发的登录会话在 token 过期前仍可继续使用。
            请通过安全渠道把新密码告诉本人。
          </div>
        </el-form>
        <template #footer>
          <el-button @click="resetPwdVisible = false">取消</el-button>
          <el-button type="primary" :loading="resetPwdSaving" @click="submitResetPwd">确认重置</el-button>
        </template>
      </el-dialog>

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
import EmptyState from '@/components/states/EmptyState.vue'
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

// 重置密码对话框
const resetPwdVisible = ref(false)
const resetPwdTarget = ref<TenantUser | null>(null)
const resetPwdSaving = ref(false)
const resetPwdForm = ref({ new_password: '', confirm: '' })

function userDisplayName(row: Pick<TenantUser, 'username' | 'display_name'>): string {
  return row.display_name || row.username
}

function canResetPassword(row: TenantUser): boolean {
  // 不能改自己（自己改密码走个人设置）
  if (row.id === userStore.user?.id) return false
  if (isPlatformAdmin.value) return true
  // tenant_admin 不能改平台管理员
  if (row.is_platform_admin) return false
  // tenant_admin 才有权（普通成员看不到这页一般）
  return userStore.tenantRole === 'tenant_admin'
}

function openResetPwd(row: TenantUser) {
  resetPwdTarget.value = row
  resetPwdForm.value = { new_password: '', confirm: '' }
  resetPwdVisible.value = true
}

async function submitResetPwd() {
  if (!resetPwdTarget.value) return
  const pw = resetPwdForm.value.new_password.trim()
  if (pw.length < 6 || pw.length > 128) {
    ElMessage.warning('密码长度需在 6-128 位之间'); return
  }
  if (pw !== resetPwdForm.value.confirm.trim()) {
    ElMessage.warning('两次输入的密码不一致'); return
  }
  resetPwdSaving.value = true
  try {
    await authApi.resetUserPassword(resetPwdTarget.value.id, pw)
    resetPwdVisible.value = false
    ElMessage.success(`「${userDisplayName(resetPwdTarget.value)}」密码已重置，请通过安全渠道告知用户`)
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || err?.message || '重置失败')
  } finally {
    resetPwdSaving.value = false
  }
}

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
    if (q) {
      const haystack = `${u.display_name || ''} ${u.username || ''}`.toLowerCase()
      if (!haystack.includes(q)) return false
    }
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
    ElMessage.success(`已更新 ${userDisplayName(user)} 的角色`)
  } catch (error: any) {
    ElMessage.error(error.message || '更新角色失败')
  }
}

async function updateStatus(user: TenantUser, enabled: boolean) {
  try {
    const updated = await authApi.updateTenantUserStatus(user.id, enabled ? 1 : 0)
    users.value = users.value.map(item => (item.id === user.id ? updated : item))
    ElMessage.success(`${enabled ? '已启用' : '已禁用'} ${userDisplayName(user)}`)
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
/* v3 redesign · 2026-05-20 — visual refresh only.
   Preserved: template (BuilderFrame + el-table + inline el-select / el-switch /
              el-tag / el-pagination + 2 dialogs), script (CRUD + role/status mutation).
   Refreshed: page header, filter-bar boxed surface, el-table colors via :deep,
              inline role select 24px / r-1 / surface-2, el-tag 5-color mapping
              (platform_admin=err / tenant_admin=brand / developer=ok / viewer=text-3 /
               member=neutral), el-pagination active solid brand. */

.tenant-users-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 24px;
  font-family: var(--font-sans);
  color: var(--text);
}

.tenant-users-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 4px;
}
.tenant-users-actions {
  display: flex;
  gap: 10px;
}
.tenant-users-header h1 {
  margin: 0 0 6px;
  font-size: var(--t-h2);          /* 24px */
  font-weight: var(--fw-bold);
  letter-spacing: -0.02em;
  color: var(--text);
}
.tenant-users-header p {
  margin: 0;
  color: var(--text-3);
  font-size: 13.5px;
  line-height: 1.55;
  max-width: 720px;
}
.tenant-users-header .tenant-users-note {
  margin-top: 4px;
  color: var(--text-4);
  font-size: 12.5px;
}

/* ── Filter bar — boxed surface card ─────────────────────────── */
.tenant-users-filter {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  margin-bottom: 0;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-4);
  flex-wrap: wrap;
}
.tenant-users-summary {
  font-size: 12px;
  color: var(--text-3);
  margin-left: auto;
  font-feature-settings: 'tnum';
}

/* ── Table panel ─────────────────────────────────────────────── */
.tenant-users-panel {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-4);
  overflow: hidden;
}

/* Element Plus table — only override colors via CSS vars,
   no structural change (don't touch cell padding / fixed-col / scroll). */
.tenant-users-panel :deep(.el-table) {
  --el-table-header-bg-color: var(--surface-2);
  --el-table-header-text-color: var(--text-2);
  --el-table-bg-color: var(--surface);
  --el-table-tr-bg-color: var(--surface);
  --el-table-row-hover-bg-color: var(--surface-2);
  --el-table-border-color: var(--line);
  --el-table-text-color: var(--text);
  background: var(--surface);
  font-size: 13px;
  color: var(--text);
}
.tenant-users-panel :deep(.el-table th.el-table__cell) {
  background: var(--surface-2);
  color: var(--text-2);
  font-weight: var(--fw-semibold);
  font-size: 11.5px;
  letter-spacing: 0.02em;
  border-bottom: 1px solid var(--line);
}
.tenant-users-panel :deep(.el-table td.el-table__cell) {
  border-bottom: 1px solid var(--line);
  color: var(--text);
}
/* Kill default stripe — spec uses no zebra */
.tenant-users-panel :deep(.el-table--striped .el-table__body tr.el-table__row--striped td.el-table__cell) {
  background: var(--surface);
}
.tenant-users-panel :deep(.el-table__body tr:hover > td.el-table__cell) {
  background: var(--surface-2);
}

/* Inline role select in row — 24px h, r-1, surface-2 ground */
.tenant-users-panel :deep(.el-table .el-select .el-select__wrapper) {
  min-height: 24px;
  padding: 0 8px;
  background: var(--surface-2);
  border-radius: var(--r-1);
  box-shadow: 0 0 0 1px var(--line);
  font-size: 12px;
}
.tenant-users-panel :deep(.el-table .el-select .el-select__wrapper:hover) {
  box-shadow: 0 0 0 1px var(--brand-ring);
}
.tenant-users-panel :deep(.el-table .el-select .el-select__wrapper.is-focused) {
  box-shadow: 0 0 0 1px var(--brand);
}
.tenant-users-panel :deep(.el-table .el-select .el-select__placeholder),
.tenant-users-panel :deep(.el-table .el-select .el-select__selected-item) {
  color: var(--text);
  font-size: 12px;
}

/* el-switch — accent on brand */
.tenant-users-panel :deep(.el-switch.is-checked .el-switch__core) {
  background-color: var(--brand);
  border-color: var(--brand);
}

/* Row action links — link style, no button chrome */
.tenant-users-panel :deep(.el-button.is-link) {
  color: var(--brand);
  font-weight: var(--fw-medium);
  font-size: 12px;
}
.tenant-users-panel :deep(.el-button.is-link:hover) {
  color: var(--brand-hover);
}
.tenant-users-panel :deep(.el-button.is-link.el-button--danger) {
  color: var(--err);
}

/* ── el-tag → role-pill 5-color (spec 07.3) ─────────────────────
   platform_admin = err   (red)
   tenant_admin   = brand (blue) — type="warning" in code
   developer      = ok    (green) — type="primary" in code
   viewer         = text-3 neutral — type="info" in code
   member         = neutral grey — type="primary" default fallback
*/
.tenant-users-panel :deep(.el-tag) {
  height: auto;
  padding: 2px 8px;
  border-radius: var(--r-1);
  font-size: 11px;
  font-weight: var(--fw-semibold);
  letter-spacing: 0.02em;
  border: 0;
  background: var(--surface-3);
  color: var(--text-2);
}
/* type=danger → platform_admin */
.tenant-users-panel :deep(.el-tag.el-tag--danger) {
  background: var(--err-soft);
  color: var(--err);
}
/* type=warning → tenant_admin */
.tenant-users-panel :deep(.el-tag.el-tag--warning) {
  background: var(--brand-soft);
  color: var(--brand);
}
/* type=success / type=primary → developer */
.tenant-users-panel :deep(.el-tag.el-tag--success),
.tenant-users-panel :deep(.el-tag.el-tag--primary) {
  background: var(--ok-soft);
  color: var(--ok);
}
/* type=info → viewer */
.tenant-users-panel :deep(.el-tag.el-tag--info) {
  background: var(--surface-3);
  color: var(--text-3);
}

/* ── el-pagination — active solid brand ────────────────────── */
.tenant-users-pager {
  display: flex;
  justify-content: flex-end;
  padding: 14px 14px 4px;
  background: var(--surface);
  border-top: 1px solid var(--line);
}
.tenant-users-pager :deep(.el-pagination) {
  --el-pagination-text-color: var(--text-2);
  --el-pagination-button-color: var(--text-2);
  --el-pagination-button-bg-color: var(--surface-2);
  --el-pagination-hover-color: var(--brand);
  --el-pagination-button-disabled-color: var(--text-4);
  --el-pagination-button-disabled-bg-color: var(--surface-2);
  font-feature-settings: 'tnum';
  font-size: 12.5px;
}
.tenant-users-pager :deep(.el-pagination.is-background .el-pager li) {
  background: var(--surface-2);
  color: var(--text-2);
  border-radius: var(--r-1);
}
.tenant-users-pager :deep(.el-pagination.is-background .el-pager li.is-active) {
  background: var(--brand);
  color: var(--text-inverse);
  font-weight: var(--fw-semibold);
}
.tenant-users-pager :deep(.el-pagination.is-background .btn-prev),
.tenant-users-pager :deep(.el-pagination.is-background .btn-next) {
  background: var(--surface-2);
  color: var(--text-2);
  border-radius: var(--r-1);
}

/* ── Form hint inside dialogs ────────────────────────────── */
.form-hint {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.5;
}

.row-action-disabled {
  color: var(--text-4);
  font-size: 12px;
}

.user-identity {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.user-identity strong,
.user-identity span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-identity strong {
  color: var(--text);
  font-size: 13px;
}

.user-identity span {
  color: var(--text-3);
  font-size: 12px;
}

/* ── Phase 6 · table density + filter UX tightening (append-only) ──
   Phase 4 already established the el-table token overrides; this block
   adds the missing density nuances (header padding, cell padding,
   sticky thead safety net, pagination polish, filter-bar count). */

.tenant-users-panel :deep(.el-table thead th.el-table__cell) {
  padding: 10px 14px;
}
.tenant-users-panel :deep(.el-table .cell) {
  padding-left: 14px;
  padding-right: 14px;
}
.tenant-users-panel :deep(.el-table .el-button.is-link) {
  font-size: 12.5px;
}

/* Sticky thead — no-op until template adds height/max-height; safe. */
.tenant-users-panel :deep(.el-table--scrollable-y .el-table__header-wrapper),
.tenant-users-panel :deep(.el-table--scrollable-x .el-table__header-wrapper) {
  position: sticky;
  top: 0;
  z-index: 2;
  background: var(--surface-2);
}

/* Pagination — active page gets brand solid, radius r-2 (was r-1) for
   consistency with v3 button radius. Phase 4 used r-1; tighten to r-2
   without rewriting Phase 4 rules (different selector specificity). */
.tenant-users-pager :deep(.el-pagination .btn-prev),
.tenant-users-pager :deep(.el-pagination .btn-next),
.tenant-users-pager :deep(.el-pagination.is-background .el-pager li),
.tenant-users-pager :deep(.el-pagination.is-background .btn-prev),
.tenant-users-pager :deep(.el-pagination.is-background .btn-next) {
  border-radius: var(--r-2, 6px);
}
.tenant-users-pager :deep(.el-pagination.is-background .el-pager li:not(.is-disabled).is-active) {
  background: var(--brand);
  color: var(--text-inverse, #fff);
}

/* Filter bar — already boxed in Phase 4; add a hover affordance to the
   wrapper to signal it's a contained surface. Original .tenant-users-filter
   keeps its border/padding/bg untouched. */
.tenant-users-filter:hover {
  border-color: var(--line-strong);
}
</style>
