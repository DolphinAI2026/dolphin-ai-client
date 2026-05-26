<!-- RoleManagePanel.vue — Native 角色管理 (master-detail layout).

  2026-05-26 design-v3 P1-N5: 权限 tab + 角色 sub-tab 选中, 右侧主区域显本面板.
  视觉跟原 apaas 角色管理页对齐: 左侧角色列表 + 右侧成员 table.

  数据源: section-content/roles (已有)
  P0 简化: 成员列表暂空表 + 提示用 AI 助手对话 (apaas 角色成员需独立 API).
-->
<template>
  <section class="rmp" aria-label="角色管理">
    <div class="rmp-master">
      <header class="rmp-master-head">
        <span class="rmp-master-title">角色管理</span>
        <span v-if="roles.length" class="rmp-master-count">{{ roles.length }}</span>
      </header>

      <div class="rmp-master-search">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>
        </svg>
        <input v-model="search" placeholder="搜索角色" />
      </div>

      <div v-if="loading" class="rmp-state">加载角色…</div>
      <div v-else-if="error" class="rmp-state rmp-state-err">{{ error }}</div>
      <ul v-else-if="filteredRoles.length" class="rmp-master-list" role="list">
        <li
          v-for="r in filteredRoles"
          :key="r.id"
          class="rmp-master-item"
          :class="{ active: r.id === selectedRoleId }"
          @click="selectRole(r.id)"
        >
          <span class="rmp-master-item-name">{{ r.name || '(未命名)' }}</span>
          <span v-if="r.code" class="rmp-master-item-code">{{ r.code }}</span>
        </li>
      </ul>
      <div v-else class="rmp-state rmp-state-empty">
        <p v-if="search">无匹配「{{ search }}」</p>
        <p v-else>暂无角色</p>
        <p class="hint">用配置助手对话新建</p>
      </div>
    </div>

    <div class="rmp-detail">
      <div v-if="!selectedRoleId" class="rmp-detail-empty">
        <div class="rmp-detail-empty-icon">👥</div>
        <p>从左侧选择一个角色, 这里显该角色的成员</p>
      </div>
      <template v-else>
        <header class="rmp-detail-head">
          <div>
            <h2 class="rmp-detail-title">{{ selectedRoleName || '角色' }}</h2>
            <p v-if="selectedRoleCode" class="rmp-detail-sub">
              <span class="rmp-code">{{ selectedRoleCode }}</span>
            </p>
          </div>
          <div class="rmp-detail-actions">
            <input
              v-model="memberSearch"
              class="rmp-detail-search"
              placeholder="搜索姓名 / 账号"
            />
            <button class="rmp-btn rmp-btn-primary" @click="onAddMember">+ 添加成员</button>
          </div>
        </header>

        <div class="rmp-table-wrap">
          <table class="rmp-table">
            <thead>
              <tr>
                <th class="check"><input type="checkbox" disabled /></th>
                <th>姓名</th>
                <th>账号</th>
                <th>手机号</th>
                <th>邮箱</th>
                <th class="ops">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="members.length === 0">
                <td colspan="6" class="empty">
                  <div class="empty-illustration">📋</div>
                  <p>暂无数据</p>
                  <p class="hint">点击「+ 添加成员」, 或用配置助手对话添加</p>
                </td>
              </tr>
              <tr v-for="(m, i) in members" :key="m.account || i">
                <td class="check"><input type="checkbox" /></td>
                <td>{{ m.name || '—' }}</td>
                <td class="mono">{{ m.account || '—' }}</td>
                <td>{{ m.phone || '—' }}</td>
                <td>{{ m.email || '—' }}</td>
                <td class="ops">
                  <button class="rmp-icon-btn" disabled>⋯</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import request from '@/utils/request'

interface RoleRow {
  id: string
  name: string
  code: string
  extra?: any
}
interface MemberRow {
  account?: string
  name?: string
  phone?: string
  email?: string
}

const props = defineProps<{
  appId: number
}>()

const roles = ref<RoleRow[]>([])
const loading = ref(false)
const error = ref('')
const search = ref('')

const selectedRoleId = ref<string>('')
const members = ref<MemberRow[]>([])
const memberSearch = ref('')

const filteredRoles = computed(() => {
  const kw = search.value.trim().toLowerCase()
  if (!kw) return roles.value
  return roles.value.filter(r =>
    (r.name || '').toLowerCase().includes(kw)
    || (r.code || '').toLowerCase().includes(kw),
  )
})

const selectedRole = computed(() => roles.value.find(r => r.id === selectedRoleId.value))
const selectedRoleName = computed(() => selectedRole.value?.name || '')
const selectedRoleCode = computed(() => selectedRole.value?.code || '')

function onAddMember() {
  alert('添加成员 — 当前请用右侧配置助手对话:\n"给运维专员A角色添加用户XX"')
}

async function load() {
  if (!props.appId) return
  loading.value = true
  error.value = ''
  try {
    const resp = await request.get<any, any>(
      `/applications/${props.appId}/section-content/roles`,
    )
    if (resp?.ok) {
      roles.value = (resp.items || []) as RoleRow[]
      if (!selectedRoleId.value && roles.value.length > 0) {
        selectRole(roles.value[0].id)
      }
    } else {
      error.value = resp?.message || resp?.error_code || '加载失败'
    }
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '网络错误'
  } finally {
    loading.value = false
  }
}

function selectRole(roleId: string) {
  selectedRoleId.value = roleId
  // P1 接 list_apaas_role_members endpoint. 当前空表显示.
  members.value = []
}

watch(() => props.appId, () => load(), { immediate: true })
</script>

<style scoped>
.rmp {
  display: flex;
  font-family: var(--font-sans);
  background: var(--bg);
  height: 100%;
  overflow: hidden;
  font-feature-settings: 'cv11', 'ss01';
}

.rmp-master {
  width: 240px;
  flex-shrink: 0;
  background: var(--surface);
  border-right: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.rmp-master-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--line);
  flex-shrink: 0;
}
.rmp-master-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}
.rmp-master-count {
  font-size: 11px;
  color: var(--text-3);
  background: var(--surface-2);
  padding: 1px 8px;
  border-radius: 999px;
}

.rmp-master-search {
  position: relative;
  padding: 8px 12px;
  flex-shrink: 0;
}
.rmp-master-search input {
  width: 100%;
  height: 30px;
  padding: 0 12px 0 32px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  font-size: 13px;
  font-family: inherit;
  outline: none;
}
.rmp-master-search input:focus { border-color: var(--brand); }
.rmp-master-search svg {
  position: absolute;
  left: 22px;
  top: 16px;
  color: var(--text-4);
  pointer-events: none;
}

.rmp-master-list {
  list-style: none;
  margin: 0;
  padding: 4px 8px;
  flex: 1;
  overflow-y: auto;
}
.rmp-master-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.12s;
  margin-bottom: 1px;
}
.rmp-master-item:hover { background: var(--surface-2); }
.rmp-master-item.active { background: var(--brand-soft); }
.rmp-master-item.active .rmp-master-item-name {
  color: var(--brand);
  font-weight: 600;
}
.rmp-master-item-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rmp-master-item-code {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-4);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rmp-detail {
  flex: 1;
  min-width: 0;
  padding: 28px 36px;
  overflow-y: auto;
}

.rmp-detail-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  height: 100%;
  color: var(--text-3);
  gap: 12px;
}
.rmp-detail-empty-icon { font-size: 48px; }
.rmp-detail-empty p { margin: 0; font-size: 14px; }

.rmp-detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
  padding-bottom: 20px;
  border-bottom: 1px solid var(--line);
}

.rmp-detail-title {
  margin: 0 0 6px;
  font-size: 20px;
  font-weight: 600;
  color: var(--text);
}
.rmp-detail-sub { margin: 0; }
.rmp-code {
  display: inline-block;
  padding: 2px 8px;
  font-size: 12px;
  font-family: var(--font-mono);
  background: var(--surface-2);
  border-radius: 4px;
  color: var(--text-3);
}

.rmp-detail-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.rmp-detail-search {
  height: 32px;
  width: 200px;
  padding: 0 12px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  font-size: 13px;
  font-family: inherit;
  outline: none;
}
.rmp-detail-search:focus { border-color: var(--brand); }
.rmp-detail-search::placeholder { color: var(--text-4); }

.rmp-btn {
  height: 32px;
  padding: 0 16px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  border: 1px solid transparent;
  white-space: nowrap;
}
.rmp-btn-primary {
  background: var(--brand);
  color: #fff;
}
.rmp-btn-primary:hover { background: var(--brand-hover); }

.rmp-table-wrap {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow: hidden;
  box-shadow: var(--sh-1);
}
.rmp-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.rmp-table th {
  text-align: left;
  padding: 11px 16px;
  background: var(--surface-2);
  font-weight: 500;
  color: var(--text-3);
  font-size: 12.5px;
  border-bottom: 1px solid var(--line);
  white-space: nowrap;
}
.rmp-table th.check { width: 40px; }
.rmp-table th.ops { width: 60px; text-align: center; }
.rmp-table td {
  padding: 12px 16px;
  border-bottom: 1px solid var(--line);
  vertical-align: middle;
}
.rmp-table tr:last-child td { border-bottom: none; }
.rmp-table .mono {
  font-family: var(--font-mono);
  font-size: 12.5px;
  color: var(--text-2);
}
.rmp-table .ops { text-align: center; }
.rmp-table .check { text-align: center; }
.rmp-table .empty {
  text-align: center;
  padding: 56px 16px;
  color: var(--text-4);
}
.rmp-table .empty .empty-illustration {
  font-size: 36px;
  opacity: 0.6;
  margin-bottom: 8px;
}
.rmp-table .empty .hint {
  margin-top: 8px;
  font-size: 12px;
}

.rmp-icon-btn {
  width: 26px;
  height: 26px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: 1px solid var(--line);
  border-radius: 4px;
  color: var(--text-3);
  cursor: pointer;
  font-size: 16px;
  line-height: 1;
}
.rmp-icon-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.rmp-state {
  padding: 32px 16px;
  text-align: center;
  color: var(--text-3);
  font-size: 13px;
}
.rmp-state-err { color: var(--err); }
.rmp-state-empty .hint {
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-4);
}
</style>
