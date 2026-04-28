<template>
  <div class="members-panel">
    <header class="members-hero">
      <div>
        <p class="members-eyebrow">成员与权限</p>
        <h3>{{ title }}</h3>
        <p class="members-subtitle">
          组织用户统一开户，应用成员只负责本应用的协作边界。
        </p>
      </div>
      <div class="members-hero-actions">
        <span class="current-role">当前权限：{{ ROLE_DISPLAY_NAMES[currentRole] }}</span>
        <button
          v-if="canOpenUserManagement"
          class="builder-btn"
          type="button"
          @click="props.openUserManagement?.()"
        >
          用户管理
        </button>
        <button
          v-if="canManage"
          class="builder-btn builder-btn-primary"
          type="button"
          @click="openInvite"
        >
          邀请成员
        </button>
      </div>
    </header>

    <section class="permission-grid" aria-label="角色权限边界">
      <article v-for="item in roleCards" :key="item.role" class="permission-card">
        <span class="role-dot" :class="item.role"></span>
        <strong>{{ item.name }}</strong>
        <p>{{ item.scope }}</p>
      </article>
    </section>

    <section v-if="showInvite" class="invite-card">
      <div class="invite-card-head">
        <div>
          <strong>邀请应用成员</strong>
          <p>只能选择当前组织内启用的用户。新账号请先在用户管理中创建。</p>
        </div>
        <button class="icon-close" type="button" aria-label="关闭邀请" @click="showInvite = false">×</button>
      </div>
      <div class="invite-fields">
        <label>
          <span>组织用户</span>
          <select v-model.number="inviteUserId" :disabled="loadingUserOptions || filteredUserOptions.length === 0">
            <option :value="0">{{ loadingUserOptions ? '加载用户中...' : '选择要加入应用的用户' }}</option>
            <option v-for="u in filteredUserOptions" :key="u.id" :value="u.id">
              {{ u.username }}
            </option>
          </select>
        </label>
        <label>
          <span>应用角色</span>
          <select v-model="inviteRole">
            <option v-for="r in inviteRoleOptions" :key="r" :value="r">
              {{ ROLE_DISPLAY_NAMES[r] }}
            </option>
          </select>
        </label>
        <button
          class="builder-btn builder-btn-primary invite-submit"
          type="button"
          :disabled="inviteLoading || !inviteUserId"
          @click="onInvite"
        >
          {{ inviteLoading ? '邀请中...' : '邀请' }}
        </button>
      </div>
      <p v-if="filteredUserOptions.length === 0 && !loadingUserOptions" class="invite-empty">
        当前没有可邀请的组织用户。
        <button v-if="canOpenUserManagement" type="button" @click="props.openUserManagement?.()">去用户管理添加</button>
      </p>
      <p v-if="inviteError" class="error">{{ inviteError }}</p>
    </section>

    <div v-if="!canManage" class="readonly-note">
      当前应用角色为 {{ ROLE_DISPLAY_NAMES[currentRole] }}，成员列表只读。
    </div>

    <section class="members-table-shell">
      <div class="members-table-head">
        <span>用户</span>
        <span>应用角色</span>
        <span>来源</span>
        <span>组织状态</span>
        <span>加入时间</span>
        <span>操作</span>
      </div>
      <div v-if="loadingMembers" class="members-state">加载成员中...</div>
      <div v-else-if="!members.length" class="members-state">暂无成员</div>
      <template v-else>
        <article v-for="m in members" :key="m.user_id" class="member-row">
          <div class="member-user">
            <span class="member-avatar">{{ userInitial(m.username) }}</span>
            <div>
              <strong>{{ m.username }}</strong>
              <small>ID {{ m.user_id }}</small>
            </div>
          </div>
          <div>
            <select
              v-if="canEditRole(m)"
              class="role-select"
              :value="m.role"
              :disabled="roleUpdatingUserId === m.user_id"
              @change="onRoleChange(m, ($event.target as HTMLSelectElement).value)"
            >
              <option v-for="r in editableRoles" :key="r" :value="r">
                {{ ROLE_DISPLAY_NAMES[r] }}
              </option>
            </select>
            <span v-else class="role-pill" :class="m.role">{{ ROLE_DISPLAY_NAMES[m.role] || m.role }}</span>
          </div>
          <div>
            <span class="source-pill" :class="String(m.source || 'none')">{{ sourceLabel(m) }}</span>
          </div>
          <div class="org-status">
            <span class="status-dot" :class="{ off: !isTenantUserActive(m) }"></span>
            <span>{{ tenantStatusLabel(m) }}</span>
            <small v-if="m.tenant_role_name">{{ m.tenant_role_name }}</small>
          </div>
          <div class="joined-at">{{ formatDate(m.created_at) }}</div>
          <div class="member-actions">
            <button
              v-if="canRemove(m)"
              class="builder-btn builder-btn-danger"
              type="button"
              @click="onRemove(m)"
            >
              移除
            </button>
            <span v-else class="action-muted">{{ actionHint(m) }}</span>
          </div>
        </article>
      </template>
    </section>

    <BaseDialog
      :visible="removeDialogVisible"
      title="移除成员"
      :message="pendingRemove ? `确认移除 ${pendingRemove.username} 的应用直邀权限？` : ''"
      dangerous
      confirm-text="移除"
      @confirm="confirmRemove"
      @cancel="cancelRemove"
    />
    <BaseToast :visible="toastVisible" :message="toastMessage" :type="toastType" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, watch } from 'vue'
import {
  type ApplicationMember,
  type ProjectMemberView,
  type ProjectRole,
  type MemberUserOption,
  ROLE_DISPLAY_NAMES,
  normalizeRole,
  roleAtLeast,
} from '@/types/collaboration'
import BaseDialog from '@/components/BaseDialog.vue'
import BaseToast from '@/components/BaseToast.vue'

type AnyMember = (ApplicationMember | ProjectMemberView) & {
  source?: string
  is_active?: boolean
  tenant_status?: number | null
  tenant_role_name?: string | null
}

const props = defineProps<{
  title: string
  currentRole: ProjectRole
  currentUserId?: number | null
  loadMembers: () => Promise<AnyMember[]>
  loadUserOptions?: () => Promise<MemberUserOption[]>
  invite: (req: { username?: string; user_id?: number; role: ProjectRole }) => Promise<void>
  updateRole: (userId: number, role: ProjectRole) => Promise<void>
  remove: (userId: number) => Promise<void>
  openUserManagement?: () => void
  canOpenUserManagement?: boolean
}>()

const members = ref<AnyMember[]>([])
const userOptions = ref<MemberUserOption[]>([])
const showInvite = ref(false)
const inviteUserId = ref(0)
const inviteRole = ref<ProjectRole>('contributor')
const inviteError = ref('')
const inviteLoading = ref(false)
const loadingMembers = ref(false)
const loadingUserOptions = ref(false)
const roleUpdatingUserId = ref<number | null>(null)

const removeDialogVisible = ref(false)
const pendingRemove = ref<AnyMember | null>(null)
const toastVisible = ref(false)
const toastMessage = ref('')
const toastType = ref<'info' | 'success' | 'warn' | 'error'>('error')

let toastTimer: ReturnType<typeof setTimeout> | null = null
function showToast(message: string, type: 'info' | 'success' | 'warn' | 'error' = 'error') {
  toastMessage.value = message
  toastType.value = type
  toastVisible.value = true
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toastVisible.value = false }, 3000)
}

const currentRole = computed(() => normalizeRole(props.currentRole))
const canManage = computed(() => roleAtLeast(currentRole.value, 'maintainer'))
const canOpenUserManagement = computed(() => props.canOpenUserManagement !== false && !!props.openUserManagement)

const roleCards = [
  { role: 'owner', name: '所有者', scope: '成员角色、删除、发布、应用配置全权负责' },
  { role: 'maintainer', name: '管理员', scope: '可发布、邀请协作者和查看者、移除低权限直邀成员' },
  { role: 'contributor', name: '协作者', scope: '可编辑 SPEC、对话生成和配置内容' },
  { role: 'viewer', name: '查看者', scope: '只读查看应用、SPEC 与构建结果' },
] as const

const inviteRoleOptions = computed<ProjectRole[]>(() => {
  if (currentRole.value === 'owner') return ['maintainer', 'contributor', 'viewer']
  return ['contributor', 'viewer']
})

const editableRoles = computed<ProjectRole[]>(() => ['maintainer', 'contributor', 'viewer'])

const filteredUserOptions = computed(() => {
  const existing = new Set(members.value.map(m => m.user_id))
  return userOptions.value.filter(u => !existing.has(u.id))
})

function sourceLabel(m: AnyMember): string {
  if (!m.source) return '未知'
  return ({ creator: '创建者', inherited: '项目继承', direct: '应用直邀' } as Record<string, string>)[m.source] || m.source
}

function isTenantUserActive(m: AnyMember) {
  return m.is_active !== false && m.tenant_status !== 0
}

function tenantStatusLabel(m: AnyMember) {
  if (m.is_active === false) return '账号停用'
  if (m.tenant_status === 0) return '组织停用'
  if (m.tenant_status == null) return '组织用户'
  return '启用'
}

function canEditRole(m: AnyMember): boolean {
  if (currentRole.value !== 'owner') return false
  if (m.role === 'owner') return false
  if (m.source !== 'direct') return false
  return true
}

function canRemove(m: AnyMember): boolean {
  if (!canManage.value) return false
  if (m.role === 'owner') return false
  if (m.source !== 'direct') return false
  if (props.currentUserId && m.user_id === props.currentUserId) return false
  if (m.role === 'maintainer' && currentRole.value !== 'owner') return false
  return true
}

function actionHint(m: AnyMember) {
  if (m.role === 'owner') return '所有者'
  if (m.source === 'inherited') return '项目内管理'
  if (m.source === 'creator') return '创建者'
  if (m.user_id === props.currentUserId) return '当前用户'
  if (m.role === 'maintainer' && currentRole.value !== 'owner') return '需所有者'
  if (!canManage.value) return '只读'
  return '—'
}

function formatDate(value?: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 16)
  return date.toLocaleString()
}

function userInitial(username: string) {
  const first = Array.from(String(username || 'U').trim())[0] || 'U'
  return /[a-z]/.test(first) ? first.toUpperCase() : first
}

async function refresh() {
  loadingMembers.value = true
  try {
    members.value = await props.loadMembers()
  } catch (e) {
    console.error('[MembersPanel] loadMembers failed', e)
    members.value = []
    showToast('成员列表加载失败', 'error')
  } finally {
    loadingMembers.value = false
  }
}

async function ensureUserOptions() {
  if (!props.loadUserOptions || userOptions.value.length) return
  loadingUserOptions.value = true
  try {
    userOptions.value = await props.loadUserOptions()
  } catch (e) {
    console.error('[MembersPanel] loadUserOptions failed', e)
    showToast('组织用户加载失败', 'error')
  } finally {
    loadingUserOptions.value = false
  }
}

async function openInvite() {
  showInvite.value = true
  inviteError.value = ''
  inviteUserId.value = 0
  inviteRole.value = inviteRoleOptions.value[0] || 'contributor'
  await ensureUserOptions()
}

async function onRoleChange(m: AnyMember, newRole: string) {
  roleUpdatingUserId.value = m.user_id
  try {
    const role = normalizeRole(newRole)
    await props.updateRole(m.user_id, role)
    await refresh()
    showToast('角色已更新', 'success')
  } catch (e: any) {
    showToast(e?.response?.data?.detail || e?.message || '更新角色失败', 'error')
    await refresh()
  } finally {
    roleUpdatingUserId.value = null
  }
}

function onRemove(m: AnyMember) {
  pendingRemove.value = m
  removeDialogVisible.value = true
}

function cancelRemove() {
  removeDialogVisible.value = false
  pendingRemove.value = null
}

async function confirmRemove() {
  const m = pendingRemove.value
  removeDialogVisible.value = false
  if (!m) return
  try {
    await props.remove(m.user_id)
    await refresh()
    showToast('成员已移除', 'success')
  } catch (e: any) {
    showToast(e?.response?.data?.detail || e?.message || '移除失败', 'error')
  } finally {
    pendingRemove.value = null
  }
}

async function onInvite() {
  inviteError.value = ''
  if (!inviteUserId.value) {
    inviteError.value = '请选择组织用户'
    return
  }
  const selected = userOptions.value.find(u => u.id === inviteUserId.value)
  inviteLoading.value = true
  try {
    await props.invite({
      user_id: inviteUserId.value,
      username: selected?.username,
      role: inviteRole.value,
    })
    showInvite.value = false
    inviteUserId.value = 0
    inviteRole.value = 'contributor'
    await refresh()
    showToast('成员已邀请', 'success')
  } catch (e: any) {
    inviteError.value = e?.response?.data?.detail || e?.message || '邀请失败'
  } finally {
    inviteLoading.value = false
  }
}

onMounted(async () => {
  await refresh()
})
watch(() => props.title, async () => {
  await refresh()
  userOptions.value = []
  showInvite.value = false
})
watch(inviteRoleOptions, options => {
  if (!options.includes(inviteRole.value)) inviteRole.value = options[0] || 'contributor'
})
</script>

<style scoped>
.members-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 18px;
  color: var(--b-text);
}

.members-hero {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  align-items: flex-start;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--b-line);
}

.members-eyebrow {
  margin: 0 0 4px;
  color: var(--b-brand);
  font-size: 11px;
  font-weight: 750;
}

.members-hero h3 {
  margin: 0;
  color: var(--b-text);
  font-size: 18px;
  line-height: 1.3;
  font-weight: 760;
}

.members-subtitle {
  margin: 6px 0 0;
  color: var(--b-text-muted);
  font-size: 12px;
}

.members-hero-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
}

.current-role,
.role-pill,
.source-pill {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  border-radius: 999px;
  padding: 0 9px;
  border: 1px solid var(--b-line);
  background: var(--b-panel-soft);
  color: var(--b-text-muted);
  font-size: 11px;
  font-weight: 650;
  white-space: nowrap;
}

.permission-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.permission-card {
  min-height: 92px;
  border: 1px solid var(--b-line);
  border-radius: var(--b-radius-md);
  background: var(--b-panel-soft);
  padding: 12px;
}

.permission-card strong {
  display: block;
  margin-top: 8px;
  color: var(--b-text);
  font-size: 13px;
}

.permission-card p {
  margin: 5px 0 0;
  color: var(--b-text-muted);
  font-size: 11px;
  line-height: 1.55;
}

.role-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  display: block;
  background: var(--b-text-faint);
}

.role-dot.owner,
.role-pill.owner {
  background: rgba(210, 139, 22, 0.14);
  color: #d28b16;
  border-color: rgba(210, 139, 22, 0.28);
}

.role-dot.maintainer,
.role-pill.maintainer {
  background: rgba(79, 110, 247, 0.14);
  color: var(--b-brand);
  border-color: rgba(79, 110, 247, 0.28);
}

.role-dot.contributor,
.role-pill.contributor {
  background: var(--b-teal-soft);
  color: var(--b-teal);
  border-color: rgba(15, 159, 143, 0.24);
}

.role-dot.viewer,
.role-pill.viewer {
  background: var(--b-bg-sub);
  color: var(--b-text-muted);
}

.role-dot.owner,
.role-dot.maintainer,
.role-dot.contributor,
.role-dot.viewer {
  border: 0;
  padding: 0;
}

.invite-card,
.readonly-note,
.members-table-shell {
  border: 1px solid var(--b-line);
  border-radius: var(--b-radius-md);
  background: var(--b-panel);
}

.invite-card {
  padding: 14px;
}

.invite-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.invite-card-head strong {
  color: var(--b-text);
  font-size: 13px;
}

.invite-card-head p,
.invite-empty {
  margin: 4px 0 0;
  color: var(--b-text-muted);
  font-size: 11px;
}

.invite-fields {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(160px, 0.7fr) auto;
  align-items: end;
  gap: 10px;
}

.invite-fields label {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  color: var(--b-text-muted);
  font-size: 11px;
}

.invite-fields select,
.role-select {
  height: 32px;
  border: 1px solid var(--b-line);
  border-radius: var(--b-radius-sm);
  background: var(--b-bg-sub);
  color: var(--b-text);
  padding: 0 10px;
  font: inherit;
  font-size: 12px;
  outline: none;
}

.invite-fields select:focus,
.role-select:focus {
  border-color: var(--b-brand);
  box-shadow: 0 0 0 2px var(--b-brand-soft);
}

.invite-submit {
  min-width: 80px;
}

.invite-empty button {
  border: 0;
  background: transparent;
  color: var(--b-brand);
  font: inherit;
  font-weight: 650;
  cursor: pointer;
}

.icon-close {
  width: 28px;
  height: 28px;
  border: 1px solid var(--b-line);
  border-radius: 7px;
  background: var(--b-bg-sub);
  color: var(--b-text-muted);
  cursor: pointer;
  font-size: 17px;
}

.readonly-note {
  padding: 10px 12px;
  color: var(--b-text-muted);
  font-size: 12px;
  background: var(--b-panel-soft);
}

.members-table-shell {
  overflow: hidden;
}

.members-table-head,
.member-row {
  display: grid;
  grid-template-columns: minmax(180px, 1.1fr) minmax(112px, 0.6fr) minmax(104px, 0.6fr) minmax(132px, 0.7fr) minmax(148px, 0.8fr) minmax(92px, 0.45fr);
  align-items: center;
  column-gap: 12px;
}

.members-table-head {
  min-height: 34px;
  padding: 0 14px;
  border-bottom: 1px solid var(--b-line);
  color: var(--b-text-muted);
  font-size: 11px;
  font-weight: 650;
}

.member-row {
  min-height: 64px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--b-line);
}

.member-row:last-child {
  border-bottom: 0;
}

.member-user {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 10px;
}

.member-avatar {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  background: var(--b-ink);
  color: #fff;
  font-size: 12px;
  font-weight: 750;
}

.member-user strong {
  display: block;
  color: var(--b-text);
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.member-user small,
.org-status small {
  display: block;
  color: var(--b-text-muted);
  font-size: 10px;
  margin-top: 2px;
}

.source-pill.direct {
  background: var(--b-brand-soft);
  color: var(--b-brand);
  border-color: rgba(79, 110, 247, 0.22);
}

.source-pill.inherited {
  background: var(--b-teal-soft);
  color: var(--b-teal);
  border-color: rgba(15, 159, 143, 0.2);
}

.source-pill.creator {
  background: rgba(210, 139, 22, 0.14);
  color: #d28b16;
  border-color: rgba(210, 139, 22, 0.24);
}

.org-status {
  min-width: 0;
  color: var(--b-text);
  font-size: 12px;
}

.status-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 999px;
  margin-right: 6px;
  background: var(--b-teal);
}

.status-dot.off {
  background: var(--b-red);
}

.joined-at,
.action-muted {
  color: var(--b-text-muted);
  font-size: 11px;
}

.member-actions {
  display: flex;
  justify-content: flex-end;
}

.members-state {
  min-height: 120px;
  display: grid;
  place-items: center;
  color: var(--b-text-muted);
  font-size: 12px;
}

.builder-btn {
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--b-line);
  border-radius: var(--b-radius-sm);
  background: var(--b-panel);
  color: var(--b-text);
  padding: 0 12px;
  font: inherit;
  font-size: 12px;
  font-weight: 650;
  cursor: pointer;
}

.builder-btn:hover {
  border-color: var(--b-line-strong);
  background: var(--b-panel-soft);
}

.builder-btn-primary {
  border-color: var(--b-brand);
  background: var(--b-brand);
  color: #070a12;
}

.builder-btn-primary:hover {
  background: #a5b4fc;
  border-color: #a5b4fc;
}

.builder-btn-danger {
  border-color: rgba(209, 74, 97, 0.32);
  background: var(--b-red-soft);
  color: var(--b-red);
}

.builder-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.error {
  margin: 10px 0 0;
  color: var(--b-red);
  font-size: 12px;
}

@media (max-width: 900px) {
  .members-hero {
    flex-direction: column;
  }

  .permission-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .invite-fields,
  .members-table-head,
  .member-row {
    grid-template-columns: 1fr;
    row-gap: 10px;
  }

  .members-table-head {
    display: none;
  }

  .member-actions {
    justify-content: flex-start;
  }
}
</style>
