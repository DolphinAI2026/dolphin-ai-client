<template>
  <BuilderFrame :breadcrumbs="[{ label: '设置' }, { label: '成员管理' }]">
    <template #actions>
      <el-button @click="loadAll" :loading="loading">刷新</el-button>
      <el-button type="primary" @click="dialogVisible = true">添加用户</el-button>
    </template>
    <div class="tenant-users-page builder-page">
      <div class="tenant-users-header">
        <div>
          <h1>成员管理</h1>
          <p>管理当前组织内的普通用户、租户角色和启停状态。</p>
        </div>
      </div>

      <div class="tenant-users-panel">
        <el-table v-loading="loading" :data="users" stripe>
          <el-table-column prop="username" label="用户名" min-width="180" />
          <el-table-column label="组织角色" min-width="180">
            <template #default="{ row }">
              <el-select
                :model-value="row.role_code || ''"
                size="small"
                style="width: 150px"
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
                @change="(val: boolean) => updateStatus(row, val)"
              />
            </template>
          </el-table-column>
          <el-table-column label="权限视图" min-width="150">
            <template #default="{ row }">
              <el-tag
                :type="row.tenant_role === 'tenant_admin' ? 'warning' : row.tenant_role === 'developer' ? 'primary' : 'info'"
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
      </div>

      <el-dialog v-model="dialogVisible" title="添加用户到当前组织" width="460px">
        <el-form :model="inviteForm" label-position="top">
          <el-form-item label="用户名" required>
            <el-input v-model="inviteForm.username" placeholder="已有账号会直接加入当前组织" />
          </el-form-item>
          <el-form-item label="初始密码">
            <el-input v-model="inviteForm.password" type="password" show-password placeholder="仅当账号不存在时需要填写" />
          </el-form-item>
          <el-form-item label="组织角色">
            <el-select v-model="inviteForm.role_code" style="width: 100%">
              <el-option
                v-for="role in roles"
                :key="role.role_code"
                :label="role.role_name"
                :value="role.role_code"
              />
            </el-select>
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
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import BuilderFrame from '@/components/BuilderFrame.vue'
import { authApi, type TenantRoleOption, type TenantUser } from '@/api/auth'

const loading = ref(false)
const saving = ref(false)
const users = ref<TenantUser[]>([])
const roles = ref<TenantRoleOption[]>([])
const dialogVisible = ref(false)
const inviteForm = ref({
  username: '',
  password: '',
  role_code: 'R_developer',
})

function roleLabel(role: TenantUser['tenant_role']) {
  if (role === 'tenant_admin') return '租户管理员'
  if (role === 'developer') return '开发者'
  if (role === 'viewer') return '查看者'
  return '成员'
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
    if (!inviteForm.value.role_code && roleList.length > 0) {
      inviteForm.value.role_code = roleList[0].role_code
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
    })
    users.value = [...users.value.filter(item => item.id !== created.id), created]
    dialogVisible.value = false
    inviteForm.value = {
      username: '',
      password: '',
      role_code: roles.value[0]?.role_code || 'R_developer',
    }
    await loadAll()
    ElMessage.success('用户已加入当前组织')
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
</style>
