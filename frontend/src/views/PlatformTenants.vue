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
          <p>仅平台管理员可见。新建租户后，被邀请的用户成员关系仍需在「组织用户」里逐个加入。</p>
        </div>
      </div>

      <div class="platform-tenants-panel">
        <el-table v-loading="loading" :data="tenants" stripe>
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
          <el-table-column prop="member_count" label="成员数" width="90" align="right" />
          <el-table-column prop="max_applications" label="应用上限" width="100" align="right" />
          <el-table-column label="状态" width="120">
            <template #default="{ row }">
              <el-switch
                :model-value="row.status === 1"
                @change="(val: boolean) => toggleStatus(row, val)"
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
          <el-table-column label="创建时间" min-width="180">
            <template #default="{ row }">
              {{ formatDate(row.created_at) }}
            </template>
          </el-table-column>
        </el-table>
      </div>

      <el-dialog v-model="createVisible" title="新建租户" width="480px">
        <el-form :model="form" label-position="top">
          <el-form-item label="租户名称" required>
            <el-input v-model="form.tenant_name" placeholder="如「华润电力」" maxlength="128" />
          </el-form-item>
          <el-form-item label="租户编码" required>
            <el-input
              v-model="form.tenant_code"
              placeholder="小写字母、数字、_、- ，唯一不可改"
              maxlength="64"
            />
          </el-form-item>
          <el-form-item label="套餐">
            <el-select v-model="form.plan_type" style="width: 100%">
              <el-option label="Free" value="free" />
              <el-option label="Pro" value="pro" />
              <el-option label="Enterprise" value="enterprise" />
            </el-select>
          </el-form-item>
          <el-form-item label="应用数量上限">
            <el-input-number v-model="form.max_applications" :min="1" :max="10000" :step="10" style="width: 100%" />
          </el-form-item>
          <el-form-item label="联系人姓名">
            <el-input v-model="form.contact_name" maxlength="64" />
          </el-form-item>
          <el-form-item label="联系人邮箱">
            <el-input v-model="form.contact_email" maxlength="128" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="createVisible = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="submitCreate">创建</el-button>
        </template>
      </el-dialog>
    </div>
  </BuilderFrame>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import BuilderFrame from '@/components/BuilderFrame.vue'
import { authApi, type TenantAdminItem, type TenantCreatePayload } from '@/api/auth'

const loading = ref(false)
const saving = ref(false)
const tenants = ref<TenantAdminItem[]>([])
const createVisible = ref(false)
const form = ref<TenantCreatePayload>({
  tenant_name: '',
  tenant_code: '',
  plan_type: 'free',
  max_applications: 100,
  contact_name: '',
  contact_email: '',
})

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
  form.value = {
    tenant_name: '',
    tenant_code: '',
    plan_type: 'free',
    max_applications: 100,
    contact_name: '',
    contact_email: '',
  }
  createVisible.value = true
}

async function submitCreate() {
  if (!form.value.tenant_name?.trim()) {
    ElMessage.warning('请输入租户名称')
    return
  }
  if (!form.value.tenant_code?.trim()) {
    ElMessage.warning('请输入租户编码')
    return
  }
  saving.value = true
  try {
    const created = await authApi.createTenant(form.value)
    tenants.value = [created, ...tenants.value]
    createVisible.value = false
    ElMessage.success(`租户「${created.tenant_name}」已创建`)
  } catch (err: any) {
    ElMessage.error(err?.message || '创建租户失败')
  } finally {
    saving.value = false
  }
}

async function toggleStatus(row: TenantAdminItem, val: boolean) {
  const target = val ? 1 : 0
  try {
    const updated = await authApi.updateTenantStatus(row.id, target as 0 | 1)
    Object.assign(row, updated)
    ElMessage.success(val ? '已启用' : '已禁用')
  } catch (err: any) {
    ElMessage.error(err?.message || '更新状态失败')
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
.tenant-email {
  color: var(--t-text-muted);
  font-size: 12px;
}
.tenant-muted {
  color: var(--t-text-muted);
}
</style>
