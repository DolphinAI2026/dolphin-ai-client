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
          <p>面向 ToB 本地部署。每个租户对应一个客户/业务部门，在文件系统、应用、组件层都做配额隔离。</p>
        </div>
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
          <el-table-column prop="tenant_name" label="租户名称" min-width="180" />
          <el-table-column prop="tenant_code" label="租户编码" min-width="160">
            <template #default="{ row }">
              <code class="tenant-code">{{ row.tenant_code }}</code>
            </template>
          </el-table-column>
          <el-table-column prop="plan_type" label="套餐" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="planTagType(row.plan_type)">{{ planLabel(row.plan_type) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="member_count" label="成员数" width="80" align="right" />
          <el-table-column label="配额（应用 / 工作区 / 组件）" min-width="200" align="center">
            <template #default="{ row }">
              <span class="quota-cell">
                {{ row.max_applications }} <span class="quota-sep">/</span>
                {{ row.max_workspaces }} <span class="quota-sep">/</span>
                {{ row.max_components }}
              </span>
            </template>
          </el-table-column>
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
          <el-table-column label="操作" width="170" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click.stop="openEdit(row)">编辑</el-button>
              <el-button link type="primary" size="small" @click.stop="openDetail(row)">详情</el-button>
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
          <el-form-item label="套餐">
            <el-select v-model="createForm.plan_type" style="width: 100%">
              <el-option label="Free" value="free" />
              <el-option label="Pro" value="pro" />
              <el-option label="Enterprise" value="enterprise" />
            </el-select>
          </el-form-item>
          <el-form-item label="低代码应用数量上限">
            <el-input-number v-model="createForm.max_applications" :min="1" :max="10000" :step="10" style="width: 100%" />
          </el-form-item>
          <el-form-item label="Vibe Coding 工作区数量上限">
            <el-input-number v-model="createForm.max_workspaces" :min="0" :max="10000" :step="5" style="width: 100%" />
          </el-form-item>
          <el-form-item label="自开发组件数量上限">
            <el-input-number v-model="createForm.max_components" :min="0" :max="10000" :step="10" style="width: 100%" />
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
          <el-form-item label="套餐">
            <el-select v-model="editForm.plan_type" style="width: 100%">
              <el-option label="Free" value="free" />
              <el-option label="Pro" value="pro" />
              <el-option label="Enterprise" value="enterprise" />
            </el-select>
          </el-form-item>
          <el-form-item label="低代码应用数量上限">
            <el-input-number v-model="editForm.max_applications" :min="1" :max="10000" :step="10" style="width: 100%" />
          </el-form-item>
          <el-form-item label="Vibe Coding 工作区数量上限">
            <el-input-number v-model="editForm.max_workspaces" :min="0" :max="10000" :step="5" style="width: 100%" />
          </el-form-item>
          <el-form-item label="自开发组件数量上限">
            <el-input-number v-model="editForm.max_components" :min="0" :max="10000" :step="10" style="width: 100%" />
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
              <UsageBar label="低代码应用" :used="detailUsage.applications.used" :max="detailUsage.applications.max" />
              <UsageBar label="Vibe Coding 工作区" :used="detailUsage.workspaces.used" :max="detailUsage.workspaces.max" />
              <UsageBar label="自开发组件" :used="detailUsage.components.used" :max="detailUsage.components.max" />
              <div class="usage-row">
                <span class="usage-label">活跃成员</span>
                <span class="usage-value">{{ detailUsage.members }} 人</span>
              </div>
            </div>
          </div>

          <div class="detail-section">
            <h4>基本信息</h4>
            <dl class="detail-dl">
              <dt>套餐</dt><dd>{{ planLabel(detailTarget.plan_type) }}</dd>
              <dt>状态</dt><dd>{{ detailTarget.status === 1 ? '启用' : '已禁用' }}</dd>
              <dt>联系人</dt><dd>{{ detailTarget.contact_name || '-' }}</dd>
              <dt>邮箱</dt><dd>{{ detailTarget.contact_email || '-' }}</dd>
              <dt>创建时间</dt><dd>{{ formatDate(detailTarget.created_at) }}</dd>
            </dl>
          </div>

          <div class="detail-section detail-muted-tip">
            成员管理在下一版做（v2 第 3 波）。临时可切到该租户后到「组织用户」加成员。
          </div>
        </div>
      </el-drawer>
    </div>
  </BuilderFrame>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import BuilderFrame from '@/components/BuilderFrame.vue'
import {
  authApi,
  type TenantAdminItem,
  type TenantCreatePayload,
  type TenantUpdatePayload,
  type TenantUsage,
} from '@/api/auth'
import UsageBar from '@/components/UsageBar.vue'

const loading = ref(false)
const saving = ref(false)
const tenants = ref<TenantAdminItem[]>([])

// 创建
const createVisible = ref(false)
const createForm = ref<TenantCreatePayload>({
  tenant_name: '',
  tenant_code: '',
  plan_type: 'free',
  max_applications: 100,
  max_workspaces: 50,
  max_components: 100,
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

async function load() {
  loading.value = true
  try {
    tenants.value = await authApi.listAllTenants()
  } catch (err: any) {
    ElMessage.error(err?.message || '加载租户失败')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  createForm.value = {
    tenant_name: '',
    tenant_code: '',
    plan_type: 'free',
    max_applications: 100,
    max_workspaces: 50,
    max_components: 100,
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
    plan_type: row.plan_type as any,
    max_applications: row.max_applications,
    max_workspaces: row.max_workspaces,
    max_components: row.max_components,
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
  detailLoading.value = true
  try {
    detailUsage.value = await authApi.getTenantUsage(row.id)
  } catch (err: any) {
    ElMessage.error(err?.message || '加载详情失败')
  } finally {
    detailLoading.value = false
  }
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

function planLabel(plan: string): string {
  return ({ free: 'Free', pro: 'Pro', enterprise: 'Enterprise' } as Record<string, string>)[plan] || plan
}
function planTagType(plan: string): 'info' | 'success' | 'warning' {
  if (plan === 'enterprise') return 'warning'
  if (plan === 'pro') return 'success'
  return 'info'
}

function formatDate(value?: string | null): string {
  if (!value) return '-'
  try {
    return new Date(value).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return value
  }
}

onMounted(load)
</script>

<style scoped>
.platform-tenants-page {
  padding: 24px;
}
.platform-tenants-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  margin-bottom: 16px;
}
.platform-tenants-header h1 {
  font-size: 20px;
  font-weight: 600;
  margin: 0 0 6px;
}
.platform-tenants-header p {
  color: var(--t-text-muted);
  font-size: 13px;
  margin: 0;
}
.platform-tenants-panel {
  background: var(--t-bg-panel);
  border: 1px solid var(--t-border-subtle);
  border-radius: 10px;
  padding: 12px;
}
.tenant-code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  background: var(--t-bg-input);
  padding: 2px 6px;
  border-radius: 4px;
  color: var(--t-text-secondary);
}
.tenant-email { color: var(--t-text-muted); font-size: 12px; }
.tenant-muted { color: var(--t-text-muted); }
.quota-cell {
  font-variant-numeric: tabular-nums;
  font-size: 13px;
}
.quota-sep {
  color: var(--t-text-muted);
  margin: 0 2px;
}

.tenant-detail {
  padding: 0 8px 16px;
}
.detail-section {
  margin-bottom: 24px;
}
.detail-section h4 {
  font-size: 13px;
  font-weight: 600;
  color: var(--t-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin: 0 0 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--t-border-subtle);
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
.usage-label { color: var(--t-text-secondary); }
.usage-value { font-weight: 500; }
.detail-dl {
  display: grid;
  grid-template-columns: 92px 1fr;
  gap: 8px 12px;
  font-size: 13px;
  margin: 0;
}
.detail-dl dt {
  color: var(--t-text-muted);
}
.detail-dl dd {
  margin: 0;
  color: var(--t-text-primary);
}
.detail-muted {
  color: var(--t-text-muted);
  font-size: 13px;
}
.detail-muted-tip {
  font-size: 12px;
  color: var(--t-text-muted);
  background: var(--t-bg-input);
  padding: 10px 12px;
  border-radius: 6px;
}
</style>
