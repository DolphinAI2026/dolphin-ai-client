<template>
  <div class="members-panel">
    <div class="members-header">
      <h3>{{ title }}</h3>
      <button v-if="canManage" class="builder-btn builder-btn-primary" type="button" @click="showInvite = true">
        + 邀请成员
      </button>
    </div>

    <table class="members-table">
      <thead>
        <tr>
          <th>用户名</th>
          <th>角色</th>
          <th>来源</th>
          <th>加入时间</th>
          <th v-if="canManage">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="m in members" :key="m.user_id">
          <td>{{ m.username }}</td>
          <td>
            <select
              v-if="canManage && canEditRole(m)"
              :value="m.role"
              @change="onRoleChange(m, ($event.target as HTMLSelectElement).value)"
            >
              <option v-for="r in editableRoles(m)" :key="r" :value="r">
                {{ ROLE_DISPLAY_NAMES[r] }}
              </option>
            </select>
            <span v-else>{{ ROLE_DISPLAY_NAMES[m.role] || m.role }}</span>
          </td>
          <td>{{ sourceLabel(m) }}</td>
          <td>{{ m.created_at ? new Date(m.created_at).toLocaleString() : '—' }}</td>
          <td v-if="canManage">
            <button
              v-if="canRemove(m)"
              class="builder-btn builder-btn-danger"
              type="button"
              @click="onRemove(m)"
            >
              移除
            </button>
          </td>
        </tr>
        <tr v-if="!members.length">
          <td :colspan="canManage ? 5 : 4" class="empty">暂无成员</td>
        </tr>
      </tbody>
    </table>

    <BaseDialog
      :visible="removeDialogVisible"
      title="移除成员"
      :message="pendingRemove ? `确认移除 ${pendingRemove.username}？` : ''"
      dangerous
      confirm-text="移除"
      @confirm="confirmRemove"
      @cancel="cancelRemove"
    />
    <BaseToast :visible="toastVisible" :message="toastMessage" :type="toastType" />

    <div v-if="showInvite" class="modal-backdrop" @click.self="showInvite = false">
      <div class="modal">
        <h4>邀请成员</h4>
        <label>
          用户名
          <input v-model="inviteUsername" type="text" placeholder="输入用户名" />
        </label>
        <label>
          角色
          <select v-model="inviteRole">
            <option v-for="r in inviteRoleOptions" :key="r" :value="r">
              {{ ROLE_DISPLAY_NAMES[r] }}
            </option>
          </select>
        </label>
        <p v-if="inviteError" class="error">{{ inviteError }}</p>
        <div class="modal-actions">
          <button class="builder-btn" type="button" @click="showInvite = false">取消</button>
          <button class="builder-btn builder-btn-primary" type="button" :disabled="!inviteUsername" @click="onInvite">
            邀请
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, watch } from 'vue'
import {
  type ApplicationMember,
  type ProjectMemberView,
  type ProjectRole,
  ROLE_DISPLAY_NAMES,
  normalizeRole,
  roleAtLeast,
} from '@/types/collaboration'
import BaseDialog from '@/components/BaseDialog.vue'
import BaseToast from '@/components/BaseToast.vue'

type AnyMember = (ApplicationMember | ProjectMemberView) & { source?: string }

const props = defineProps<{
  title: string
  /** 当前用户在该资源上的 effective role */
  currentRole: ProjectRole
  /** 拉成员列表的 callback */
  loadMembers: () => Promise<AnyMember[]>
  invite: (req: { username: string; role: ProjectRole }) => Promise<void>
  updateRole: (userId: number, role: ProjectRole) => Promise<void>
  remove: (userId: number) => Promise<void>
}>()

const members = ref<AnyMember[]>([])
const showInvite = ref(false)
const inviteUsername = ref('')
const inviteRole = ref<ProjectRole>('contributor')
const inviteError = ref('')

// Phase F Task 12a: BaseDialog/BaseToast 替原生 confirm/alert
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

const canManage = computed(() => roleAtLeast(props.currentRole, 'maintainer'))

const inviteRoleOptions = computed<ProjectRole[]>(() => {
  if (props.currentRole === 'owner') return ['maintainer', 'contributor', 'viewer']
  return ['contributor', 'viewer']
})

function sourceLabel(m: AnyMember): string {
  if (!m.source) return '—'
  return ({ creator: '创建者', inherited: '项目继承', direct: '直接邀请' } as Record<string, string>)[m.source] || m.source
}

function canEditRole(m: AnyMember): boolean {
  if (m.role === 'owner') return false
  if (m.source === 'inherited') return false
  return canManage.value
}

function editableRoles(_m: AnyMember): ProjectRole[] {
  if (props.currentRole === 'owner') return ['maintainer', 'contributor', 'viewer']
  return ['contributor', 'viewer']
}

function canRemove(m: AnyMember): boolean {
  if (m.role === 'owner') return false
  if (m.source === 'inherited' || m.source === 'creator') return false
  return canManage.value
}

async function refresh() {
  try {
    members.value = await props.loadMembers()
  } catch (e) {
    console.error('[MembersPanel] loadMembers failed', e)
  }
}

async function onRoleChange(m: AnyMember, newRole: string) {
  try {
    const role = normalizeRole(newRole)
    await props.updateRole(m.user_id, role)
    await refresh()
  } catch (e: any) {
    showToast(e?.response?.data?.detail || e?.message || '更新角色失败', 'error')
    await refresh()
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
  } catch (e: any) {
    showToast(e?.response?.data?.detail || e?.message || '移除失败', 'error')
  } finally {
    pendingRemove.value = null
  }
}

async function onInvite() {
  inviteError.value = ''
  try {
    await props.invite({ username: inviteUsername.value.trim(), role: inviteRole.value })
    showInvite.value = false
    inviteUsername.value = ''
    inviteRole.value = 'contributor'
    await refresh()
  } catch (e: any) {
    inviteError.value = e?.response?.data?.detail || e?.message || '邀请失败'
  }
}

onMounted(refresh)
watch(() => props.title, refresh)
</script>

<style scoped>
.members-panel { padding: 16px; }
.members-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.members-table { width: 100%; border-collapse: collapse; }
.members-table th, .members-table td { padding: 8px 12px; border-bottom: 1px solid var(--line); text-align: left; }
.members-table select { padding: 4px 8px; }
.empty { text-align: center; color: var(--fg-muted); padding: 24px; }
.modal-backdrop { position: fixed; inset: 0; background: var(--t-bg-overlay, rgba(0,0,0,.4)); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.modal { background: var(--bg-panel); color: var(--fg); padding: 24px; border-radius: 8px; min-width: 320px; box-shadow: var(--sh-pop); }
.modal label { display: block; margin: 12px 0; }
.modal input, .modal select { width: 100%; padding: 6px 8px; margin-top: 4px; background: var(--bg-inset); color: var(--fg); border: 1px solid var(--line); border-radius: 4px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
.error { color: var(--t-danger); font-size: 12px; }
.builder-btn-danger { background: var(--t-danger); color: var(--t-text-inverse, #fff); }
</style>
