<template>
  <div class="enterprise-auth-panel">
    <div class="enterprise-auth-heading">
      <div>
        <h2>企业认证绑定</h2>
        <p>维护 Builder 与企业认证源之间的账号映射和优先级。</p>
      </div>
      <el-button type="primary" :icon="Plus" @click="openCreateAccount">
        新增账号
      </el-button>
    </div>

    <el-alert
      v-if="status"
      class="enterprise-auth-status"
      :type="status.binding_enabled ? 'success' : 'warning'"
      :closable="false"
      show-icon
    >
      <template #title>
        绑定能力{{ status.binding_enabled ? '已启用' : '未启用' }}
      </template>
      <span>
        当前认证模式：{{ providerLabel(status.auth_provider) }}
        <template v-if="!status.binding_enabled">。可维护配置，但运行时不会解析账号绑定。</template>
      </span>
    </el-alert>

    <section class="enterprise-auth-section" aria-labelledby="enterprise-account-title">
      <div class="section-heading">
        <div>
          <h3 id="enterprise-account-title">认证账号</h3>
          <span>{{ accounts.length }} 个账号</span>
        </div>
      </div>

      <div class="auth-table-shell">
        <el-table
          v-loading="loading"
          :data="accounts"
          row-key="id"
          empty-text="暂无企业认证账号"
        >
          <el-table-column label="认证源" width="128">
            <template #default="{ row }">
              <el-tag size="small" effect="plain" :type="providerTagType(row.provider)">
                {{ providerLabel(row.provider) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="服务地址" min-width="210">
            <template #default="{ row }">
              <span class="cell-ellipsis" :title="row.base_url">{{ row.base_url }}</span>
            </template>
          </el-table-column>
          <el-table-column label="租户" min-width="170">
            <template #default="{ row }">
              <div class="stacked-cell">
                <span>{{ row.tenant_name || row.tenant_ref }}</span>
                <code v-if="row.tenant_name">{{ row.tenant_ref }}</code>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="account" label="账号" min-width="145" />
          <el-table-column label="状态" width="112">
            <template #default="{ row }">
              <el-tag size="small" effect="light" :type="statusTagType(row.status)">
                {{ statusLabel(row.status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="最后校验" min-width="166">
            <template #default="{ row }">
              <span class="muted-cell">{{ formatDate(row.last_verified_at) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="最近错误" min-width="190">
            <template #default="{ row }">
              <el-tooltip
                v-if="row.last_error"
                :content="sanitizeEnterpriseAuthLastError(row.last_error, 240)"
                placement="top"
              >
                <span class="error-cell">
                  {{ sanitizeEnterpriseAuthLastError(row.last_error, 48) }}
                </span>
              </el-tooltip>
              <span v-else class="muted-cell">-</span>
            </template>
          </el-table-column>
          <el-table-column label="启用" width="76" align="center">
            <template #default="{ row }">
              <el-switch
                :model-value="row.status !== 'disabled'"
                :loading="busyAction === `account:${row.id}`"
                @change="(value: boolean) => toggleAccount(row, value)"
              />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="146" fixed="right" align="center">
            <template #default="{ row }">
              <div class="icon-actions">
                <el-tooltip content="编辑账号" placement="top">
                  <el-button
                    text
                    circle
                    :icon="Edit"
                    aria-label="编辑账号"
                    @click="openEditAccount(row)"
                  />
                </el-tooltip>
                <el-tooltip content="连接测试" placement="top">
                  <el-button
                    text
                    circle
                    :icon="Connection"
                    aria-label="连接测试"
                    :disabled="row.status === 'disabled'"
                    :loading="busyAction === `test:${row.id}`"
                    @click="testAccount(row)"
                  />
                </el-tooltip>
                <el-tooltip content="删除账号" placement="top">
                  <el-button
                    text
                    circle
                    type="danger"
                    :icon="Delete"
                    aria-label="删除账号"
                    @click="confirmDeleteAccount(row)"
                  />
                </el-tooltip>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </section>

    <section class="enterprise-auth-section" aria-labelledby="enterprise-binding-title">
      <div class="section-heading">
        <div>
          <h3 id="enterprise-binding-title">账号绑定</h3>
          <span>{{ bindings.length }} 条绑定</span>
        </div>
        <el-button :icon="Link" :disabled="accounts.length < 2" @click="openCreateBinding">
          新增绑定
        </el-button>
      </div>

      <div class="auth-table-shell">
        <el-table
          v-loading="loading"
          :data="bindings"
          row-key="id"
          empty-text="暂无企业认证绑定"
        >
          <el-table-column label="左侧账号" min-width="245">
            <template #default="{ row }">
              <div class="binding-account">
                <el-tag size="small" effect="plain" :type="providerTagType(row.left_account.provider)">
                  {{ providerLabel(row.left_account.provider) }}
                </el-tag>
                <div class="binding-account-text">
                  <span>{{ row.left_account.account }}</span>
                  <small>{{ accountDetail(row.left_account) }}</small>
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="右侧账号" min-width="245">
            <template #default="{ row }">
              <div class="binding-account">
                <el-tag size="small" effect="plain" :type="providerTagType(row.right_account.provider)">
                  {{ providerLabel(row.right_account.provider) }}
                </el-tag>
                <div class="binding-account-text">
                  <span>{{ row.right_account.account }}</span>
                  <small>{{ accountDetail(row.right_account) }}</small>
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="priority" label="优先级" width="94" align="right" />
          <el-table-column label="启用" width="84" align="center">
            <template #default="{ row }">
              <el-switch
                :model-value="row.enabled"
                :loading="busyAction === `binding:${row.id}`"
                @change="(value: boolean) => toggleBinding(row, value)"
              />
            </template>
          </el-table-column>
          <el-table-column label="更新时间" min-width="166">
            <template #default="{ row }">
              <span class="muted-cell">{{ formatDate(row.updated_at) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="104" fixed="right" align="center">
            <template #default="{ row }">
              <div class="icon-actions">
                <el-tooltip content="编辑绑定" placement="top">
                  <el-button
                    text
                    circle
                    :icon="Edit"
                    aria-label="编辑绑定"
                    @click="openEditBinding(row)"
                  />
                </el-tooltip>
                <el-tooltip content="删除绑定" placement="top">
                  <el-button
                    text
                    circle
                    type="danger"
                    :icon="Delete"
                    aria-label="删除绑定"
                    @click="confirmDeleteBinding(row)"
                  />
                </el-tooltip>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </section>

    <el-dialog
      v-model="accountDialogVisible"
      :title="accountEditingId ? '编辑认证账号' : '新增认证账号'"
      width="min(560px, calc(100vw - 32px))"
      destroy-on-close
    >
      <el-form :model="accountForm" label-position="top" @submit.prevent>
        <div class="dialog-grid">
          <el-form-item label="认证源" required>
            <el-select v-model="accountForm.provider">
              <el-option label="aPaaS" value="apaas" />
              <el-option label="Control Plane" value="control_plane" />
            </el-select>
          </el-form-item>
          <el-form-item label="启用状态">
            <el-switch v-model="accountForm.enabled" active-text="启用" inactive-text="停用" />
          </el-form-item>
        </div>
        <el-form-item label="服务地址" required>
          <el-input
            v-model="accountForm.base_url"
            placeholder="https://enterprise.example.com"
            maxlength="255"
          />
        </el-form-item>
        <div class="dialog-grid">
          <el-form-item label="租户标识" required>
            <el-input v-model="accountForm.tenant_ref" maxlength="128" />
          </el-form-item>
          <el-form-item label="租户名称">
            <el-input v-model="accountForm.tenant_name" maxlength="255" />
          </el-form-item>
        </div>
        <el-form-item label="账号" required>
          <el-input v-model="accountForm.account" maxlength="128" autocomplete="off" />
        </el-form-item>
        <el-form-item
          :label="accountPasswordLabel"
          :required="accountPasswordRequired"
        >
          <el-input
            v-model="accountForm.password"
            type="password"
            show-password
            autocomplete="new-password"
            maxlength="4096"
            :placeholder="accountPasswordPlaceholder"
          />
          <div v-if="accountIdentityChanged" class="form-hint">
            身份来源变化需重新输入密码
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="accountDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="busyAction === 'account-save'" @click="submitAccount">
          保存
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="bindingDialogVisible"
      :title="bindingEditingId ? '编辑账号绑定' : '新增账号绑定'"
      width="min(560px, calc(100vw - 32px))"
      destroy-on-close
    >
      <el-form :model="bindingForm" label-position="top" @submit.prevent>
        <el-form-item label="左侧账号" required>
          <el-select
            v-model="bindingForm.left_account_id"
            filterable
            placeholder="选择左侧账号"
          >
            <el-option
              v-for="account in accounts"
              :key="account.id"
              :label="accountOptionLabel(account)"
              :value="account.id"
              :disabled="disabledBindingAccountIds('left').has(account.id)"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="右侧账号" required>
          <el-select
            v-model="bindingForm.right_account_id"
            filterable
            placeholder="选择右侧账号"
          >
            <el-option
              v-for="account in accounts"
              :key="account.id"
              :label="accountOptionLabel(account)"
              :value="account.id"
              :disabled="disabledBindingAccountIds('right').has(account.id)"
            />
          </el-select>
        </el-form-item>
        <div class="dialog-grid">
          <el-form-item label="优先级" required>
            <el-input-number
              v-model="bindingForm.priority"
              :min="0"
              :controls="false"
              class="full-width"
            />
          </el-form-item>
          <el-form-item label="启用状态">
            <el-switch v-model="bindingForm.enabled" active-text="启用" inactive-text="停用" />
          </el-form-item>
        </div>
        <el-alert
          v-if="selectedBindingAccounts && !bindingPairAllowed"
          title="绑定两侧必须来自不同认证源"
          type="error"
          :closable="false"
          show-icon
        />
      </el-form>
      <template #footer>
        <el-button @click="bindingDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="busyAction === 'binding-save'"
          :disabled="!bindingPairAllowed"
          @click="submitBinding"
        >
          保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Connection, Delete, Edit, Link, Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  buildEnterpriseAuthAccountUpdatePayload,
  enterpriseAuthApi,
  hasEnterpriseAuthIdentitySourceChanged,
  isEnterpriseAuthBindingPairAllowed,
  sanitizeEnterpriseAuthLastError,
  type EnterpriseAuthAccount,
  type EnterpriseAuthAccountFormValue,
  type EnterpriseAuthAccountSummary,
  type EnterpriseAuthBinding,
  type EnterpriseAuthIdentitySource,
  type EnterpriseAuthProvider,
  type EnterpriseAuthStatus,
} from '@/api/enterpriseAuth'
import { extractErrorMessage } from '@/utils/errorHandler'

type BindingSide = 'left' | 'right'

interface BindingFormValue {
  left_account_id: number | null
  right_account_id: number | null
  priority: number
  enabled: boolean
}

const loading = ref(false)
const status = ref<EnterpriseAuthStatus | null>(null)
const accounts = ref<EnterpriseAuthAccount[]>([])
const bindings = ref<EnterpriseAuthBinding[]>([])
const busyAction = ref('')

const accountDialogVisible = ref(false)
const accountEditingId = ref<number | null>(null)
const accountForm = ref<EnterpriseAuthAccountFormValue>(emptyAccountForm())
const accountOriginalIdentity = ref<EnterpriseAuthIdentitySource | null>(null)

const bindingDialogVisible = ref(false)
const bindingEditingId = ref<number | null>(null)
const bindingForm = ref<BindingFormValue>(emptyBindingForm())

const selectedLeftAccount = computed(() =>
  accounts.value.find((account) => account.id === bindingForm.value.left_account_id))
const selectedRightAccount = computed(() =>
  accounts.value.find((account) => account.id === bindingForm.value.right_account_id))
const selectedBindingAccounts = computed(() =>
  Boolean(selectedLeftAccount.value && selectedRightAccount.value))
const bindingPairAllowed = computed(() =>
  isEnterpriseAuthBindingPairAllowed(selectedLeftAccount.value, selectedRightAccount.value))
const accountIdentityChanged = computed(() => Boolean(
  accountOriginalIdentity.value
  && hasEnterpriseAuthIdentitySourceChanged(
    accountOriginalIdentity.value,
    accountForm.value,
  ),
))
const accountPasswordRequired = computed(() =>
  !accountEditingId.value || accountIdentityChanged.value)
const accountPasswordLabel = computed(() => {
  if (!accountEditingId.value) return '密码'
  return accountIdentityChanged.value
    ? '密码（身份来源变化需重新输入密码）'
    : '密码（留空则保持原密码）'
})
const accountPasswordPlaceholder = computed(() => {
  if (!accountEditingId.value) return '请输入认证密码'
  return accountIdentityChanged.value
    ? '身份来源变化需重新输入密码'
    : '留空则保持原密码'
})

function emptyAccountForm(): EnterpriseAuthAccountFormValue {
  return {
    provider: 'apaas',
    base_url: '',
    tenant_ref: '',
    tenant_name: '',
    account: '',
    password: '',
    enabled: true,
  }
}

function emptyBindingForm(): BindingFormValue {
  return {
    left_account_id: null,
    right_account_id: null,
    priority: 100,
    enabled: true,
  }
}

function providerLabel(provider: string): string {
  if (provider === 'apaas') return 'aPaaS'
  if (provider === 'control_plane' || provider === 'coding') return 'Control Plane'
  return provider || '-'
}

function providerTagType(
  provider: EnterpriseAuthProvider | string,
): 'primary' | 'success' {
  return provider === 'apaas' ? 'success' : 'primary'
}

function statusLabel(value: string): string {
  return ({
    connected: '已连接',
    unverified: '待校验',
    error: '异常',
    disabled: '已停用',
  } as Record<string, string>)[value] || value
}

function statusTagType(
  value: string,
): 'success' | 'warning' | 'danger' | 'info' {
  if (value === 'connected') return 'success'
  if (value === 'error') return 'danger'
  if (value === 'disabled') return 'info'
  return 'warning'
}

function formatDate(value?: string | null): string {
  if (!value) return '-'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime())
    ? value
    : parsed.toLocaleString('zh-CN', { hour12: false })
}

function accountOptionLabel(account: EnterpriseAuthAccountSummary): string {
  const tenant = account.tenant_name || account.tenant_ref
  return `${providerLabel(account.provider)} · ${tenant} · ${account.account}`
}

function accountDetail(account: EnterpriseAuthAccountSummary): string {
  return `${account.tenant_name || account.tenant_ref} · ${account.base_url}`
}

function authErrorMessage(error: unknown, fallback: string): string {
  const topLevelMessage = (
    error as { response?: { data?: { message?: unknown } } }
  )?.response?.data?.message
  return extractErrorMessage(
    typeof topLevelMessage === 'string' ? topLevelMessage : error,
  ) || fallback
}

function upsertAccount(updated: EnterpriseAuthAccount) {
  const index = accounts.value.findIndex((item) => item.id === updated.id)
  if (index >= 0) accounts.value[index] = updated
  else accounts.value = [...accounts.value, updated].sort((a, b) => a.id - b.id)
}

function upsertBinding(updated: EnterpriseAuthBinding) {
  const index = bindings.value.findIndex((item) => item.id === updated.id)
  if (index >= 0) bindings.value[index] = updated
  else bindings.value = [...bindings.value, updated]
  bindings.value = [...bindings.value].sort((a, b) =>
    a.priority - b.priority
    || a.left_account_id - b.left_account_id
    || a.right_account_id - b.right_account_id)
}

async function loadBindings() {
  bindings.value = await enterpriseAuthApi.listBindings()
}

async function refresh() {
  loading.value = true
  try {
    const [nextStatus, nextAccounts, nextBindings] = await Promise.all([
      enterpriseAuthApi.getStatus(),
      enterpriseAuthApi.listAccounts(),
      enterpriseAuthApi.listBindings(),
    ])
    status.value = nextStatus
    accounts.value = nextAccounts
    bindings.value = nextBindings
  } catch (error) {
    ElMessage.error(authErrorMessage(error, '加载企业认证配置失败'))
  } finally {
    loading.value = false
  }
}

function openCreateAccount() {
  accountEditingId.value = null
  accountOriginalIdentity.value = null
  accountForm.value = emptyAccountForm()
  accountDialogVisible.value = true
}

function openEditAccount(account: EnterpriseAuthAccount) {
  accountEditingId.value = account.id
  accountOriginalIdentity.value = {
    provider: account.provider,
    base_url: account.base_url,
    account: account.account,
  }
  accountForm.value = {
    provider: account.provider,
    base_url: account.base_url,
    tenant_ref: account.tenant_ref,
    tenant_name: account.tenant_name || '',
    account: account.account,
    password: '',
    enabled: account.status !== 'disabled',
  }
  accountDialogVisible.value = true
}

function validateAccountForm(): boolean {
  if (!accountForm.value.base_url.trim()) {
    ElMessage.warning('请输入服务地址')
    return false
  }
  if (!accountForm.value.tenant_ref.trim()) {
    ElMessage.warning('请输入租户标识')
    return false
  }
  if (!accountForm.value.account.trim()) {
    ElMessage.warning('请输入账号')
    return false
  }
  if (accountPasswordRequired.value && !accountForm.value.password.trim()) {
    ElMessage.warning(
      accountIdentityChanged.value
        ? '身份来源变化需重新输入密码'
        : '请输入认证密码',
    )
    return false
  }
  return true
}

async function submitAccount() {
  if (!validateAccountForm()) return
  busyAction.value = 'account-save'
  try {
    const editingId = accountEditingId.value
    const updated = editingId
      ? await enterpriseAuthApi.updateAccount(
        editingId,
        buildEnterpriseAuthAccountUpdatePayload(accountForm.value),
      )
      : await enterpriseAuthApi.createAccount({
        provider: accountForm.value.provider,
        base_url: accountForm.value.base_url.trim(),
        tenant_ref: accountForm.value.tenant_ref.trim(),
        tenant_name: accountForm.value.tenant_name.trim() || null,
        account: accountForm.value.account.trim(),
        password: accountForm.value.password,
        enabled: accountForm.value.enabled,
      })
    upsertAccount(updated)
    await loadBindings()
    accountDialogVisible.value = false
    ElMessage.success(editingId ? '认证账号已更新' : '认证账号已创建')
  } catch (error) {
    ElMessage.error(authErrorMessage(error, '保存认证账号失败'))
  } finally {
    busyAction.value = ''
  }
}

async function testAccount(account: EnterpriseAuthAccount) {
  busyAction.value = `test:${account.id}`
  try {
    const updated = await enterpriseAuthApi.testAccount(account.id)
    upsertAccount(updated)
    await loadBindings()
    ElMessage.success('连接测试通过')
  } catch (error) {
    await refresh()
    ElMessage.error(authErrorMessage(error, '连接测试失败'))
  } finally {
    busyAction.value = ''
  }
}

async function toggleAccount(account: EnterpriseAuthAccount, enabled: boolean) {
  busyAction.value = `account:${account.id}`
  try {
    const updated = await enterpriseAuthApi.updateAccount(account.id, { enabled })
    upsertAccount(updated)
    await loadBindings()
    ElMessage.success(enabled ? '认证账号已启用' : '认证账号已停用')
  } catch (error) {
    ElMessage.error(authErrorMessage(error, '更新账号状态失败'))
  } finally {
    busyAction.value = ''
  }
}

async function confirmDeleteAccount(account: EnterpriseAuthAccount) {
  try {
    await ElMessageBox.confirm(
      `删除账号「${account.account}」会同时删除包含该账号的绑定，是否继续？`,
      '删除认证账号',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  busyAction.value = `account:${account.id}`
  try {
    await enterpriseAuthApi.deleteAccount(account.id)
    accounts.value = accounts.value.filter((item) => item.id !== account.id)
    bindings.value = bindings.value.filter((item) =>
      item.left_account_id !== account.id && item.right_account_id !== account.id)
    ElMessage.success('认证账号已删除')
  } catch (error) {
    ElMessage.error(authErrorMessage(error, '删除认证账号失败'))
  } finally {
    busyAction.value = ''
  }
}

function openCreateBinding() {
  bindingEditingId.value = null
  bindingForm.value = emptyBindingForm()
  bindingDialogVisible.value = true
}

function openEditBinding(binding: EnterpriseAuthBinding) {
  bindingEditingId.value = binding.id
  bindingForm.value = {
    left_account_id: binding.left_account_id,
    right_account_id: binding.right_account_id,
    priority: binding.priority,
    enabled: binding.enabled,
  }
  bindingDialogVisible.value = true
}

function disabledBindingAccountIds(side: BindingSide): Set<number> {
  const oppositeId = side === 'left'
    ? bindingForm.value.right_account_id
    : bindingForm.value.left_account_id
  const opposite = accounts.value.find((account) => account.id === oppositeId)
  if (!opposite) return new Set()
  return new Set(
    accounts.value
      .filter((account) =>
        account.id === opposite.id || account.provider === opposite.provider)
      .map((account) => account.id),
  )
}

async function submitBinding() {
  if (!bindingPairAllowed.value) {
    ElMessage.warning('绑定两侧必须来自不同认证源')
    return
  }
  const leftAccountId = bindingForm.value.left_account_id
  const rightAccountId = bindingForm.value.right_account_id
  if (leftAccountId === null || rightAccountId === null) return
  busyAction.value = 'binding-save'
  try {
    const payload = {
      left_account_id: leftAccountId,
      right_account_id: rightAccountId,
      priority: bindingForm.value.priority,
      enabled: bindingForm.value.enabled,
    }
    const editingId = bindingEditingId.value
    const updated = editingId
      ? await enterpriseAuthApi.updateBinding(editingId, payload)
      : await enterpriseAuthApi.createBinding(payload)
    upsertBinding(updated)
    bindingDialogVisible.value = false
    ElMessage.success(editingId ? '账号绑定已更新' : '账号绑定已创建')
  } catch (error) {
    ElMessage.error(authErrorMessage(error, '保存账号绑定失败'))
  } finally {
    busyAction.value = ''
  }
}

async function toggleBinding(binding: EnterpriseAuthBinding, enabled: boolean) {
  busyAction.value = `binding:${binding.id}`
  try {
    const updated = await enterpriseAuthApi.updateBinding(binding.id, { enabled })
    upsertBinding(updated)
    ElMessage.success(enabled ? '账号绑定已启用' : '账号绑定已停用')
  } catch (error) {
    ElMessage.error(authErrorMessage(error, '更新绑定状态失败'))
  } finally {
    busyAction.value = ''
  }
}

async function confirmDeleteBinding(binding: EnterpriseAuthBinding) {
  try {
    await ElMessageBox.confirm(
      `删除「${binding.left_account.account} ↔ ${binding.right_account.account}」绑定？`,
      '删除账号绑定',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  busyAction.value = `binding:${binding.id}`
  try {
    await enterpriseAuthApi.deleteBinding(binding.id)
    bindings.value = bindings.value.filter((item) => item.id !== binding.id)
    ElMessage.success('账号绑定已删除')
  } catch (error) {
    ElMessage.error(authErrorMessage(error, '删除账号绑定失败'))
  } finally {
    busyAction.value = ''
  }
}

defineExpose({ refresh })

onMounted(refresh)
</script>

<style scoped>
.enterprise-auth-panel { min-width: 0; color: var(--text); }
.enterprise-auth-heading,
.section-heading,
.section-heading > div { display: flex; align-items: center; }
.enterprise-auth-heading {
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 16px;
}
.enterprise-auth-heading h2 {
  margin: 0 0 4px;
  font-size: 20px;
  font-weight: var(--fw-bold);
}
.enterprise-auth-heading p {
  margin: 0;
  color: var(--text-3);
  font-size: 13px;
  line-height: 1.5;
}
.enterprise-auth-status { margin-bottom: 20px; border-radius: 6px; }
.enterprise-auth-section + .enterprise-auth-section { margin-top: 24px; }
.section-heading {
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 10px;
}
.section-heading > div { gap: 10px; }
.section-heading h3 {
  margin: 0;
  font-size: 15px;
  font-weight: var(--fw-semibold);
}
.section-heading span { color: var(--text-3); font-size: 12px; }
.auth-table-shell {
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
}
.auth-table-shell :deep(.el-table) {
  width: 100%;
  min-width: 0;
  --el-table-header-bg-color: var(--surface-2);
  --el-table-header-text-color: var(--text-2);
  --el-table-border-color: var(--line);
  --el-table-row-hover-bg-color: var(--surface-2);
  font-size: 13px;
}
.auth-table-shell :deep(.el-table th.el-table__cell) {
  padding: 9px 0;
  font-size: 12px;
  font-weight: var(--fw-semibold);
}
.auth-table-shell :deep(.el-table td.el-table__cell) { padding: 8px 0; }
.auth-table-shell :deep(.el-table__inner-wrapper::before) { display: none; }
.cell-ellipsis {
  display: block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.error-cell {
  display: block;
  overflow: hidden;
  color: var(--err);
  font-size: 11.5px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.stacked-cell,
.binding-account-text {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}
.stacked-cell code,
.binding-account-text small,
.muted-cell {
  color: var(--text-3);
  font-size: 11.5px;
}
.stacked-cell code { font-family: var(--font-mono); }
.icon-actions,
.binding-account { display: flex; align-items: center; }
.icon-actions { justify-content: center; gap: 2px; }
.icon-actions :deep(.el-button) {
  width: 30px;
  height: 30px;
  margin: 0;
}
.binding-account { min-width: 0; gap: 8px; }
.binding-account-text span,
.binding-account-text small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dialog-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 16px;
}
.dialog-grid :deep(.el-select),
.dialog-grid :deep(.el-input-number),
.enterprise-auth-panel :deep(.el-form-item .el-select) { width: 100%; }
.full-width { width: 100%; }
.form-hint { margin-top: 4px; color: var(--warn); font-size: 12px; }
@media (max-width: 720px) {
  .enterprise-auth-heading {
    align-items: flex-start;
    flex-direction: column;
  }
  .enterprise-auth-heading .el-button { width: 100%; }
  .dialog-grid {
    grid-template-columns: minmax(0, 1fr);
    gap: 0;
  }
}
</style>
