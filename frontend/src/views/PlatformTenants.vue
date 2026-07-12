<template>
  <BuilderFrame :breadcrumbs="[{ label: '平台' }, { label: '租户管理' }]">
    <template #actions>
      <el-button @click="load" :loading="loading">刷新</el-button>
      <el-button type="primary" @click="openCreate">新建租户</el-button>
    </template>
    <div class="platform-tenants-page builder-page">
      <div class="platform-tenants-header">
        <div>
          <h1>租户管理</h1>
          <p>面向 ToB 本地部署。每个租户对应一个客户/业务部门，用于隔离成员、应用和平台环境。</p>
        </div>
      </div>

      <!-- Dashboard 卡片区 -->
      <div v-if="dashboard" class="dashboard-grid">
        <div class="dashboard-card">
          <div class="dashboard-card-label">活跃租户</div>
          <div class="dashboard-card-value">{{ dashboard.tenants_active }}</div>
        </div>
        <div class="dashboard-card">
          <div class="dashboard-card-label">低代码应用</div>
          <div class="dashboard-card-value">{{ dashboard.totals.applications.used }}</div>
        </div>
        <div class="dashboard-card">
          <div class="dashboard-card-label">代码工作区</div>
          <div class="dashboard-card-value">{{ dashboard.totals.workspaces.used }}</div>
        </div>
        <div class="dashboard-card">
          <div class="dashboard-card-label">自开发组件</div>
          <div class="dashboard-card-value">{{ dashboard.totals.components.used }}</div>
        </div>
        <div class="dashboard-card">
          <div class="dashboard-card-label">成员（活跃）</div>
          <div class="dashboard-card-value">{{ dashboard.totals.members }}</div>
        </div>
      </div>

      <!-- 搜索栏 -->
      <div class="filter-bar">
        <el-input
          v-model="filterQ"
          placeholder="按名称 / 编码搜索"
          clearable
          style="width: 280px"
          @clear="load"
          @keyup.enter="load"
        />
        <el-select v-model="filterStatus" placeholder="全部状态" clearable style="width: 160px" @change="load">
          <el-option label="只看启用" :value="1" />
          <el-option label="只看禁用" :value="0" />
        </el-select>
        <el-button @click="load" :loading="loading">应用筛选</el-button>
      </div>

      <div class="platform-tenants-panel">
        <el-table
          v-loading="loading"
          :data="tenants"
          stripe
          row-key="id"
          @row-click="onRowClick"
          highlight-current-row
        >
          <template #empty>
            <EmptyState
              :variant="(filterQ || filterStatus !== null) ? 'filtered' : 'first'"
              :title="(filterQ || filterStatus !== null) ? '没有匹配的租户' : '还没有租户'"
              :desc="(filterQ || filterStatus !== null) ? '换个关键词，或清空筛选条件查看全部。' : '新建第一个租户，开始为客户/业务部门管理应用。'"
            >
              <template #icon>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 21h18"/><path d="M5 21V7l8-4v18"/><path d="M19 21V11l-6-4"/><path d="M9 9v.01"/><path d="M9 12v.01"/><path d="M9 15v.01"/></svg>
              </template>
              <template v-if="filterQ || filterStatus !== null" #cta>
                <el-button @click="() => { filterQ = ''; filterStatus = null; load() }">清空筛选</el-button>
              </template>
              <template v-else #cta>
                <el-button type="primary" @click="openCreate">新建租户</el-button>
              </template>
            </EmptyState>
          </template>
          <el-table-column prop="tenant_name" label="租户名称" min-width="180" />
          <el-table-column prop="tenant_code" label="租户编码" min-width="160">
            <template #default="{ row }">
              <code class="tenant-code">{{ row.tenant_code }}</code>
            </template>
          </el-table-column>
          <el-table-column prop="member_count" label="成员数" width="80" align="right" />
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-switch
                :model-value="row.status === 1"
                @change="(val: boolean) => toggleStatus(row, val)"
                @click.stop
              />
            </template>
          </el-table-column>
          <el-table-column label="联系人" min-width="160">
            <template #default="{ row }">
              <span v-if="row.contact_name || row.contact_email">
                {{ row.contact_name || '-' }}
                <span v-if="row.contact_email" class="tenant-email"> · {{ row.contact_email }}</span>
              </span>
              <span v-else class="tenant-muted">-</span>
            </template>
          </el-table-column>
          <el-table-column label="创建时间" min-width="170">
            <template #default="{ row }">
              {{ formatDate(row.created_at) }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="220" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click.stop="openEdit(row)">编辑</el-button>
              <el-button link type="primary" size="small" @click.stop="openDetail(row)">详情</el-button>
              <el-button
                link
                size="small"
                :disabled="row.id === userStore.tenantId"
                @click.stop="setDefault(row)"
              >设为默认</el-button>
              <el-button link type="danger" size="small" @click.stop="confirmDelete(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- 创建对话框 -->
      <el-dialog v-model="createVisible" title="新建租户" width="480px">
        <el-form :model="createForm" label-position="top">
          <el-form-item label="租户名称" required>
            <el-input v-model="createForm.tenant_name" placeholder="如「华润电力」" maxlength="128" />
          </el-form-item>
          <el-form-item label="租户编码" required>
            <el-input v-model="createForm.tenant_code" placeholder="小写字母、数字、_、- ，唯一不可改" maxlength="64" />
          </el-form-item>
          <el-form-item label="联系人姓名">
            <el-input v-model="createForm.contact_name" maxlength="64" />
          </el-form-item>
          <el-form-item label="联系人邮箱">
            <el-input v-model="createForm.contact_email" maxlength="128" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="createVisible = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="submitCreate">创建</el-button>
        </template>
      </el-dialog>

      <!-- 编辑对话框 -->
      <el-dialog v-model="editVisible" :title="`编辑租户 — ${editTarget?.tenant_name || ''}`" width="480px">
        <el-form :model="editForm" label-position="top">
          <el-form-item label="租户名称" required>
            <el-input v-model="editForm.tenant_name" maxlength="128" />
          </el-form-item>
          <el-form-item label="租户编码（不可改）">
            <el-input :model-value="editTarget?.tenant_code" disabled />
          </el-form-item>
          <el-form-item label="联系人姓名">
            <el-input v-model="editForm.contact_name" maxlength="64" />
          </el-form-item>
          <el-form-item label="联系人邮箱">
            <el-input v-model="editForm.contact_email" maxlength="128" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="editVisible = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="submitEdit">保存</el-button>
        </template>
      </el-dialog>

      <!-- 详情抽屉 -->
      <el-drawer
        v-model="detailVisible"
        :title="detailTarget ? `${detailTarget.tenant_name}（${detailTarget.tenant_code}）` : ''"
        size="420px"
        direction="rtl"
      >
        <div v-if="detailTarget" class="tenant-detail">
          <div class="detail-section">
            <h4>资源使用</h4>
            <div v-if="detailLoading" class="detail-muted">加载中…</div>
            <div v-else-if="detailUsage" class="usage-grid">
              <div class="usage-row">
                <span class="usage-label">低代码应用</span>
                <span class="usage-value">{{ detailUsage.applications.used }} 个</span>
              </div>
              <div class="usage-row">
                <span class="usage-label">代码工作区</span>
                <span class="usage-value">{{ detailUsage.workspaces.used }} 个</span>
              </div>
              <div class="usage-row">
                <span class="usage-label">自开发组件</span>
                <span class="usage-value">{{ detailUsage.components.used }} 个</span>
              </div>
              <div class="usage-row">
                <span class="usage-label">活跃成员</span>
                <span class="usage-value">{{ detailUsage.members }} 人</span>
              </div>
            </div>
          </div>

          <div class="detail-section">
            <h4>基本信息</h4>
            <dl class="detail-dl">
              <dt>状态</dt><dd>{{ detailTarget.status === 1 ? '启用' : '已禁用' }}</dd>
              <dt>联系人</dt><dd>{{ detailTarget.contact_name || '-' }}</dd>
              <dt>邮箱</dt><dd>{{ detailTarget.contact_email || '-' }}</dd>
              <dt>创建时间</dt><dd>{{ formatDate(detailTarget.created_at) }}</dd>
            </dl>
          </div>

          <div class="detail-section">
            <div class="detail-section-header">
              <h4>成员（{{ detailMembers.length }}）</h4>
              <el-button size="small" type="primary" @click="openAddMember">添加成员</el-button>
            </div>
            <div v-if="detailMembersLoading" class="detail-muted">加载中…</div>
            <ul v-else-if="detailMembers.length > 0" class="member-list">
              <li v-for="m in detailMembers" :key="m.user_id" class="member-row">
                <div class="member-info">
                  <span class="member-username">
                    {{ userDisplayName(m) }}
                    <span v-if="m.is_default" class="member-default" title="该用户的默认租户">默认</span>
                  </span>
                  <span class="member-meta">
                    <span v-if="m.username !== userDisplayName(m)">{{ m.username }}</span>
                    <span v-if="m.is_platform_admin" class="member-platform">平台管理员</span>
                    <span v-if="!m.is_active" class="member-inactive">已禁用</span>
                  </span>
                </div>
                <div class="member-actions">
                  <el-select
                    :model-value="m.role_code || ''"
                    size="small"
                    style="width: 130px"
                    @change="(val: string) => changeMemberRole(m, val)"
                  >
                    <el-option label="租户管理员" value="R_tenant_admin" />
                    <el-option label="开发者" value="R_developer" />
                    <el-option label="查看者" value="R_viewer" />
                  </el-select>
                  <el-button
                    link
                    type="danger"
                    size="small"
                    @click="confirmRemoveMember(m)"
                  >移除</el-button>
                </div>
              </li>
            </ul>
            <div v-else class="detail-muted">该租户还没有成员，点「添加成员」加入第一个用户。</div>
          </div>
        </div>
      </el-drawer>

      <!-- 添加成员对话框：从已有平台账号选；选不到才允许新建 -->
      <el-dialog v-model="addMemberVisible" :title="`添加成员到 ${detailTarget?.tenant_name || ''}`" width="460px">
        <el-form :model="addMemberForm" label-position="top">
          <el-form-item label="选择账号" required>
            <el-select
              v-model="addMemberForm.username"
              filterable
              :allow-create="addMemberAllowCreate"
              :placeholder="addMemberAllowCreate ? '搜索已有账号或输入新账号名' : '搜索已有账号'"
              style="width: 100%"
              :loading="platformUsersLoading"
            >
              <el-option
                v-for="u in availablePlatformUsers"
                :key="u.id"
                :label="`${userDisplayName(u)} ${u.username}`"
                :value="u.username"
              >
                <span>{{ userDisplayName(u) }}</span>
                <span v-if="u.username !== userDisplayName(u)" class="member-account-option">{{ u.username }}</span>
                <span v-if="u.is_platform_admin" class="member-platform" style="margin-left:8px;">平台管理员</span>
              </el-option>
            </el-select>
            <div class="form-hint">
              <el-checkbox v-model="addMemberAllowCreate">列表里没有？允许新建账号</el-checkbox>
            </div>
          </el-form-item>
          <el-form-item v-if="addMemberAllowCreate && !isExistingUsername" label="初始密码" required>
            <el-input v-model="addMemberForm.password" type="password" show-password placeholder="新建账号必填" />
          </el-form-item>
          <el-form-item label="角色">
            <el-select v-model="addMemberForm.role_code" style="width: 100%">
              <el-option label="租户管理员（R_tenant_admin）" value="R_tenant_admin" />
              <el-option label="开发者（R_developer）" value="R_developer" />
              <el-option label="查看者（R_viewer）" value="R_viewer" />
            </el-select>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="addMemberVisible = false">取消</el-button>
          <el-button type="primary" :loading="memberSaving" @click="submitAddMember">添加</el-button>
        </template>
      </el-dialog>
    </div>
  </BuilderFrame>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import BuilderFrame from '@/components/BuilderFrame.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import { computed } from 'vue'
import {
  authApi,
  type PlatformUserItem,
  type TenantAdminItem,
  type TenantCreatePayload,
  type TenantDashboard,
  type TenantMemberAddPayload,
  type TenantMemberItem,
  type TenantUpdatePayload,
  type TenantUsage,
} from '@/api/auth'
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()

const loading = ref(false)
const saving = ref(false)
const tenants = ref<TenantAdminItem[]>([])

// 筛选 & dashboard
const filterQ = ref('')
const filterStatus = ref<0 | 1 | null>(null)
const dashboard = ref<TenantDashboard | null>(null)

// 创建
const createVisible = ref(false)
const createForm = ref<TenantCreatePayload>({
  tenant_name: '',
  tenant_code: '',
  contact_name: '',
  contact_email: '',
})

// 编辑
const editVisible = ref(false)
const editTarget = ref<TenantAdminItem | null>(null)
const editForm = ref<TenantUpdatePayload>({})

// 详情抽屉
const detailVisible = ref(false)
const detailTarget = ref<TenantAdminItem | null>(null)
const detailUsage = ref<TenantUsage | null>(null)
const detailLoading = ref(false)

// 成员
const detailMembers = ref<TenantMemberItem[]>([])
const detailMembersLoading = ref(false)
const addMemberVisible = ref(false)
const memberSaving = ref(false)
const addMemberForm = ref<TenantMemberAddPayload>({
  username: '',
  password: '',
  role_code: 'R_developer',
})
const addMemberAllowCreate = ref(false)
const platformUsers = ref<PlatformUserItem[]>([])
const platformUsersLoading = ref(false)

// 已经是当前租户成员的账号不重复展示
const availablePlatformUsers = computed(() => {
  const memberSet = new Set(detailMembers.value.map((m) => m.username))
  return platformUsers.value.filter((u) => !memberSet.has(u.username))
})

const isExistingUsername = computed(() =>
  platformUsers.value.some((u) => u.username === addMemberForm.value.username)
)

function userDisplayName(user: { username: string; display_name?: string | null }) {
  return user.display_name || user.username
}

async function load() {
  loading.value = true
  try {
    const params: { q?: string; status?: 0 | 1 } = {}
    if (filterQ.value.trim()) params.q = filterQ.value.trim()
    if (filterStatus.value === 0 || filterStatus.value === 1) params.status = filterStatus.value
    tenants.value = await authApi.listAllTenants(params)
  } catch (err: any) {
    ElMessage.error(err?.message || '加载租户失败')
  } finally {
    loading.value = false
  }
}

async function loadDashboard() {
  try {
    dashboard.value = await authApi.getTenantDashboard()
  } catch {
    dashboard.value = null
  }
}

async function setDefault(row: TenantAdminItem) {
  try {
    await authApi.setMyDefaultTenant(row.id)
    ElMessage.success(`「${row.tenant_name}」已设为你的默认租户（下次登录自动进入）`)
  } catch (err: any) {
    ElMessage.error(err?.message || '设为默认失败')
  }
}

function openCreate() {
  createForm.value = {
    tenant_name: '',
    tenant_code: '',
    contact_name: '',
    contact_email: '',
  }
  createVisible.value = true
}

async function submitCreate() {
  if (!createForm.value.tenant_name?.trim()) {
    ElMessage.warning('请输入租户名称'); return
  }
  if (!createForm.value.tenant_code?.trim()) {
    ElMessage.warning('请输入租户编码'); return
  }
  saving.value = true
  try {
    const created = await authApi.createTenant(createForm.value)
    tenants.value = [created, ...tenants.value]
    createVisible.value = false
    ElMessage.success(`租户「${created.tenant_name}」已创建`)
  } catch (err: any) {
    ElMessage.error(err?.message || '创建租户失败')
  } finally {
    saving.value = false
  }
}

function openEdit(row: TenantAdminItem) {
  editTarget.value = row
  editForm.value = {
    tenant_name: row.tenant_name,
    contact_name: row.contact_name || '',
    contact_email: row.contact_email || '',
  }
  editVisible.value = true
}

async function submitEdit() {
  if (!editTarget.value) return
  if (!editForm.value.tenant_name?.trim()) {
    ElMessage.warning('租户名称不能为空'); return
  }
  saving.value = true
  try {
    const updated = await authApi.updateTenant(editTarget.value.id, editForm.value)
    const idx = tenants.value.findIndex((t) => t.id === updated.id)
    if (idx >= 0) tenants.value[idx] = updated
    editVisible.value = false
    ElMessage.success('已保存')
  } catch (err: any) {
    ElMessage.error(err?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

function onRowClick(row: TenantAdminItem) {
  openDetail(row)
}

async function openDetail(row: TenantAdminItem) {
  detailTarget.value = row
  detailVisible.value = true
  detailUsage.value = null
  detailMembers.value = []
  detailLoading.value = true
  detailMembersLoading.value = true
  try {
    const [usage, members] = await Promise.all([
      authApi.getTenantUsage(row.id),
      authApi.listTenantMembers(row.id),
    ])
    detailUsage.value = usage
    detailMembers.value = members
  } catch (err: any) {
    ElMessage.error(err?.message || '加载详情失败')
  } finally {
    detailLoading.value = false
    detailMembersLoading.value = false
  }
}

async function openAddMember() {
  addMemberForm.value = { username: '', password: '', role_code: 'R_developer' }
  addMemberAllowCreate.value = false
  addMemberVisible.value = true
  // 拉平台账号列表（去掉已加入本租户的）
  platformUsersLoading.value = true
  try {
    platformUsers.value = await authApi.listPlatformUsers()
  } catch {
    platformUsers.value = []
  } finally {
    platformUsersLoading.value = false
  }
}

async function submitAddMember() {
  if (!detailTarget.value) return
  if (!addMemberForm.value.username?.trim()) {
    ElMessage.warning('请选择或输入用户名'); return
  }
  // 新建账号必须有密码（已存在账号后端不要求密码）
  if (addMemberAllowCreate.value && !isExistingUsername.value && !addMemberForm.value.password?.trim()) {
    ElMessage.warning('新建账号需要填写初始密码'); return
  }
  memberSaving.value = true
  try {
    const m = await authApi.addTenantMember(detailTarget.value.id, addMemberForm.value)
    // 已有就替换、新增就追加
    const idx = detailMembers.value.findIndex((x) => x.user_id === m.user_id)
    if (idx >= 0) detailMembers.value[idx] = m
    else detailMembers.value.push(m)
    addMemberVisible.value = false
    ElMessage.success(`成员「${m.username}」已加入`)
    // 同步刷新 usage（成员数变了）
    if (detailTarget.value) {
      detailUsage.value = await authApi.getTenantUsage(detailTarget.value.id)
    }
  } catch (err: any) {
    ElMessage.error(err?.message || '添加成员失败')
  } finally {
    memberSaving.value = false
  }
}

async function changeMemberRole(m: TenantMemberItem, roleCode: string) {
  if (!detailTarget.value || !roleCode || roleCode === m.role_code) return
  try {
    const updated = await authApi.updateTenantMemberRole(detailTarget.value.id, m.user_id, roleCode)
    const idx = detailMembers.value.findIndex((x) => x.user_id === updated.user_id)
    if (idx >= 0) detailMembers.value[idx] = updated
    ElMessage.success(`「${updated.username}」角色已改为${memberRoleLabel(updated.tenant_role)}`)
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || err?.message || '改角色失败')
  }
}

async function confirmRemoveMember(m: TenantMemberItem) {
  if (!detailTarget.value) return
  try {
    await ElMessageBox.confirm(
      `把成员「${m.username}」从租户「${detailTarget.value.tenant_name}」移除？该用户的账号本身不会被删，只是失去该租户的访问。`,
      '移除成员',
      { type: 'warning', confirmButtonText: '移除', cancelButtonText: '取消' },
    )
  } catch { return }
  try {
    await authApi.removeTenantMember(detailTarget.value.id, m.user_id)
    detailMembers.value = detailMembers.value.filter((x) => x.user_id !== m.user_id)
    ElMessage.success('已移除')
    if (detailTarget.value) {
      detailUsage.value = await authApi.getTenantUsage(detailTarget.value.id)
    }
  } catch (err: any) {
    ElMessage.error(err?.message || '移除失败')
  }
}

function memberRoleLabel(role: string): string {
  return ({
    platform_admin: '平台管理员',
    tenant_admin: '租户管理员',
    developer: '开发者',
    viewer: '只读',
    member: '普通成员',
  } as Record<string, string>)[role] || role
}
function memberRoleTag(role: string): 'primary' | 'success' | 'info' | 'warning' {
  if (role === 'tenant_admin' || role === 'platform_admin') return 'warning'
  if (role === 'developer') return 'success'
  if (role === 'viewer') return 'info'
  return 'primary'
}

async function toggleStatus(row: TenantAdminItem, val: boolean) {
  try {
    const updated = await authApi.updateTenantStatus(row.id, (val ? 1 : 0) as 0 | 1)
    Object.assign(row, updated)
    ElMessage.success(val ? '已启用' : '已禁用')
  } catch (err: any) {
    ElMessage.error(err?.message || '更新状态失败')
  }
}

async function confirmDelete(row: TenantAdminItem) {
  // 第一步：尝试无 force 删除，看后端返回的残留情况
  try {
    await ElMessageBox.confirm(
      `确认删除租户「${row.tenant_name}」吗？租户内的应用 / 工作区 / 组件不会自动删除。`,
      '删除租户',
      { type: 'warning', confirmButtonText: '继续', cancelButtonText: '取消' },
    )
  } catch { return }

  try {
    await authApi.deleteTenant(row.id, false)
    tenants.value = tenants.value.filter((t) => t.id !== row.id)
    ElMessage.success(`租户「${row.tenant_name}」已删除`)
    return
  } catch (err: any) {
    const detail = err?.response?.data?.detail || err?.detail
    if (detail && typeof detail === 'object' && detail.residual) {
      const r = detail.residual as Record<string, number>
      const summary = `应用 ${r.applications} / 工作区 ${r.workspaces} / 组件 ${r.components} / 成员 ${r.members}`
      try {
        await ElMessageBox.confirm(
          `${detail.message}。当前残留：${summary}。\n\n确认级联删除应用 / 组件 / 成员关系？workspace 文件需事后手动清理 _online_coding/${row.id}/`,
          '强制删除',
          { type: 'error', confirmButtonText: '强制删除', cancelButtonText: '取消' },
        )
      } catch { return }
      try {
        await authApi.deleteTenant(row.id, true)
        tenants.value = tenants.value.filter((t) => t.id !== row.id)
        ElMessage.success(`租户「${row.tenant_name}」已强制删除`)
      } catch (err2: any) {
        ElMessage.error(err2?.message || '删除失败')
      }
    } else {
      ElMessage.error(err?.message || '删除失败')
    }
  }
}

function formatDate(value?: string | null): string {
  if (!value) return '-'
  try {
    return new Date(value).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return value
  }
}

onMounted(() => {
  load()
  loadDashboard()
})
</script>

<style scoped>
/* v3 redesign · 2026-05-20 — visual refresh only.
   Preserved: template (BuilderFrame + el-table + dialogs + drawer), script (CRUD/dashboard).
   Refreshed: dashboard cards, near-limit banner, filter-bar, table chrome via :deep,
              tenant-code mono-pill, role-pill / member-platform / member-default
              to v3 tokens. el-table structure not touched — only stripe / hover /
              header / border colors via Element CSS vars. */

.platform-tenants-page {
  padding: 24px;
  font-family: var(--font-sans);
  color: var(--text);
}

.platform-tenants-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  margin-bottom: 20px;
}
.platform-tenants-header h1 {
  font-size: var(--t-h2);          /* 24px */
  font-weight: var(--fw-bold);
  letter-spacing: -0.02em;
  color: var(--text);
  margin: 0 0 6px;
}
.platform-tenants-header p {
  color: var(--text-3);
  font-size: 13.5px;
  line-height: 1.55;
  margin: 0;
  max-width: 720px;
}

/* ── Dashboard 5-card grid ───────────────────────────────────── */
.dashboard-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.dashboard-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-4);
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  transition: border-color 0.16s var(--ease), box-shadow 0.16s var(--ease);
}
.dashboard-card:hover {
  border-color: var(--brand-ring);
  box-shadow: var(--sh-2);
}
.dashboard-card-label {
  font-size: 11.5px;
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  font-weight: var(--fw-medium);
}
.dashboard-card-value {
  font-size: 24px;
  font-weight: var(--fw-bold);
  letter-spacing: -0.02em;
  font-feature-settings: 'tnum';
  color: var(--text);
}
.dashboard-card-suffix {
  font-size: 13px;
  font-weight: var(--fw-regular);
  color: var(--text-3);
  margin-left: 4px;
}

/* ── Near-limit banner (warn soft) ───────────────────────────── */
.near-limit-banner {
  margin-bottom: 16px;
  padding: 10px 14px;
  background: var(--warn-soft);
  border: 1px solid var(--warn);
  border-radius: var(--r-3);
  font-size: 13px;
  color: var(--text);
  line-height: 1.55;
}
.near-limit-banner strong { color: var(--warn); font-weight: var(--fw-semibold); }
.near-limit-link {
  color: var(--warn);
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 2px;
  font-weight: var(--fw-medium);
}
.near-limit-link:hover { color: var(--err); }

/* ── Filter bar — boxed surface card per design spec ─────────── */
.filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  margin-bottom: 14px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-4);
}

/* ── Table panel ─────────────────────────────────────────────── */
.platform-tenants-panel {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-4);
  overflow: hidden;
}

/* Element Plus table — only override colors via CSS vars,
   don't change structure (cell padding, fixed-col, row hover model). */
.platform-tenants-panel :deep(.el-table) {
  --el-table-header-bg-color: var(--surface-2);
  --el-table-header-text-color: var(--text-2);
  --el-table-bg-color: var(--surface);
  --el-table-tr-bg-color: var(--surface);
  --el-table-row-hover-bg-color: var(--surface-2);
  --el-table-current-row-bg-color: var(--brand-soft);
  --el-table-border-color: var(--line);
  --el-table-text-color: var(--text);
  background: var(--surface);
  font-size: 13px;
  color: var(--text);
}
.platform-tenants-panel :deep(.el-table th.el-table__cell) {
  background: var(--surface-2);
  color: var(--text-2);
  font-weight: var(--fw-semibold);
  font-size: 11.5px;
  letter-spacing: 0.02em;
  border-bottom: 1px solid var(--line);
}
.platform-tenants-panel :deep(.el-table td.el-table__cell) {
  border-bottom: 1px solid var(--line);
  color: var(--text);
}
/* Kill default stripe — spec uses no zebra */
.platform-tenants-panel :deep(.el-table--striped .el-table__body tr.el-table__row--striped td.el-table__cell) {
  background: var(--surface);
}
.platform-tenants-panel :deep(.el-table__body tr:hover > td.el-table__cell) {
  background: var(--surface-2);
}

/* Table action buttons — link style, no chrome */
.platform-tenants-panel :deep(.el-button.is-link) {
  color: var(--brand);
  font-weight: var(--fw-medium);
  font-size: 12px;
}
.platform-tenants-panel :deep(.el-button.is-link:hover) {
  color: var(--brand-hover);
}
.platform-tenants-panel :deep(.el-button.is-link.el-button--danger) {
  color: var(--err);
}
.platform-tenants-panel :deep(.el-button.is-link.el-button--danger:hover) {
  color: var(--err);
  opacity: 0.85;
}

/* Tenant code cell — mono mini-pill */
.tenant-code {
  display: inline-block;
  font-family: var(--font-mono);
  font-size: 11.5px;
  background: var(--surface-3);
  padding: 2px 6px;
  border-radius: var(--r-1);
  color: var(--text-2);
}
.tenant-email { color: var(--text-3); font-size: 12px; }
.tenant-muted { color: var(--text-4); }

/* ── Detail drawer ──────────────────────────────────────────── */
.tenant-detail {
  padding: 0 8px 16px;
  font-family: var(--font-sans);
  color: var(--text);
}
.detail-section { margin-bottom: 24px; }
.detail-section h4 {
  font-size: 11.5px;
  font-weight: var(--fw-semibold);
  color: var(--text-2);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin: 0 0 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--line);
}
.usage-grid {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.usage-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  padding: 4px 0;
}
.usage-label { color: var(--text-2); }
.usage-value {
  font-weight: var(--fw-semibold);
  color: var(--text);
  font-feature-settings: 'tnum';
}
.detail-dl {
  display: grid;
  grid-template-columns: 92px 1fr;
  gap: 8px 12px;
  font-size: 13px;
  margin: 0;
}
.detail-dl dt { color: var(--text-3); }
.detail-dl dd { margin: 0; color: var(--text); }
.detail-muted { color: var(--text-3); font-size: 13px; }
.detail-section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--line);
  margin-bottom: 12px;
  padding-bottom: 8px;
}
.detail-section-header h4 {
  margin: 0;
  border: 0;
  padding: 0;
  font-size: 11.5px;
  font-weight: var(--fw-semibold);
  color: var(--text-2);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

/* ── Member list (inside detail drawer) ──────────────────────── */
.member-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}
.member-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 0;
  border-bottom: 1px solid var(--line);
}
.member-row:last-child { border-bottom: 0; }
.member-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.member-username {
  font-size: 13px;
  font-weight: var(--fw-medium);
  color: var(--text);
}
.member-account-option {
  margin-left: 8px;
  color: var(--text-3);
  font-size: 12px;
}
.member-meta {
  display: flex;
  gap: 6px;
  align-items: center;
  font-size: 12px;
  color: var(--text-3);
}
.member-platform {
  display: inline-flex;
  padding: 2px 7px;
  border-radius: var(--r-1);
  font-size: 11px;
  font-weight: var(--fw-semibold);
  background: var(--err-soft);
  color: var(--err);
  letter-spacing: 0.02em;
}
.member-inactive { color: var(--err); font-weight: var(--fw-medium); }
.member-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.member-default {
  display: inline-block;
  margin-left: 4px;
  font-size: 10px;
  font-weight: var(--fw-semibold);
  color: var(--brand);
  background: var(--brand-soft);
  padding: 1px 6px;
  border-radius: var(--r-1);
  vertical-align: middle;
  letter-spacing: 0.02em;
}
.form-hint {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.5;
}

/* ── Phase 6 · table density + filter UX tightening (append-only) ──
   Adds the visual nuances missing from the initial Phase 4 :deep block:
   - thead th padding 10px 14px (tighter, label-feel)
   - cell horizontal padding 14px
   - link button font-size 12.5 (was 12)
   - filter-bar summary count anchored right (margin-left: auto)
   No existing rule is rewritten; everything here adds new property
   declarations that take effect via natural cascade order. */

.platform-tenants-panel :deep(.el-table thead th.el-table__cell) {
  padding: 10px 14px;
}
.platform-tenants-panel :deep(.el-table .cell) {
  padding-left: 14px;
  padding-right: 14px;
}
.platform-tenants-panel :deep(.el-table .el-button.is-link) {
  font-size: 12.5px;
}

/* Sticky thead — only takes effect when el-table has height/max-height
   set (this template doesn't, so it's a no-op safety net for future
   height additions). Safe to keep as it does nothing without scroll. */
.platform-tenants-panel :deep(.el-table--scrollable-y .el-table__header-wrapper),
.platform-tenants-panel :deep(.el-table--scrollable-x .el-table__header-wrapper) {
  position: sticky;
  top: 0;
  z-index: 2;
  background: var(--surface-2);
}

/* Filter bar — summary count anchored right (template doesn't have one
   today, but if a future .filter-summary span is added it'll auto-right).
   Also bump radius from r-4 to keep consistent with Apps.vue toolbar. */
.filter-bar .filter-summary {
  margin-left: auto;
  color: var(--text-3);
  font-size: 12px;
  font-feature-settings: 'tnum';
}
</style>
