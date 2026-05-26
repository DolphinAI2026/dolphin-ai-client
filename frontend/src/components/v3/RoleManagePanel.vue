<!-- RoleManagePanel.vue — Native 角色权限 (矩阵 view + 列表 view 切换).

  2026-05-26 design-v4 Phase D: 顶部 toggle 切矩阵 (默认) / 角色列表 2 view.

  矩阵 view: 角色 × 资源 (页面/数据/流程/应用设置) 4 状态 chip (all/rw/r/none).
  列表 view: 老 master-detail 保留 (左角色 list + 右成员 table).

  数据源:
    - 矩阵 view: /role-resource-matrix endpoint (一次拉全)
    - 列表 view: /section-content/roles endpoint (老兼容)

  cell click → dropdown 改状态 (本 session 只改 local state + 提示 P2 真接).
-->
<template>
  <section class="rmp" aria-label="角色权限">
    <!-- ── Header ─────────────────────────────────────────────── -->
    <header class="rmp-page-head">
      <div class="rmp-head-meta">
        <h1 class="rmp-page-title">角色权限</h1>
        <p class="rmp-page-stat" v-if="!loading && !error">
          <span><b>{{ roles.length }}</b> 角色</span>
          <span class="rmp-dot">·</span>
          <span><b>{{ totalResourceCount }}</b> 授权对象</span>
          <span class="rmp-dot">·</span>
          <span><b>{{ totalMemberCount }}</b> 成员</span>
        </p>
        <p v-else-if="error" class="rmp-page-stat err">{{ error }}</p>
        <p v-else class="rmp-page-stat">加载中…</p>
      </div>
      <div class="rmp-head-actions">
        <!-- 视图 toggle -->
        <div class="rmp-view-toggle" role="group" aria-label="切换视图">
          <button
            type="button"
            class="rmp-toggle-btn"
            :class="{ active: viewMode === 'matrix' }"
            @click="setView('matrix')"
          >矩阵</button>
          <button
            type="button"
            class="rmp-toggle-btn"
            :class="{ active: viewMode === 'list' }"
            @click="setView('list')"
          >角色列表</button>
        </div>
        <button class="rmp-btn rmp-btn-ghost" disabled title="P2 真接 AI 推荐">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/>
          </svg>
          AI 建议
        </button>
        <button class="rmp-btn rmp-btn-primary" @click="onAddRole">+ 新增角色</button>
      </div>
    </header>

    <!-- ── Matrix view ────────────────────────────────────────── -->
    <div v-if="viewMode === 'matrix'" class="rmp-matrix-wrap">
      <div v-if="matrixLoading" class="rmp-state">加载权限矩阵…</div>
      <div v-else-if="matrixError" class="rmp-state rmp-state-err">
        {{ matrixError }}
        <button class="rmp-btn rmp-btn-ghost" @click="loadMatrix">重试</button>
      </div>
      <div v-else-if="!hasMatrixData" class="rmp-state rmp-state-empty">
        <div class="rmp-empty-illustration">🛡️</div>
        <p>暂无角色或资源</p>
        <p class="hint">先创建角色 + 部署应用, 再回这里配权限</p>
      </div>
      <template v-else>
        <div class="rmp-matrix-scroll">
          <table class="rmp-matrix-table">
            <colgroup>
              <col class="rmp-mat-col-role" />
              <col v-for="r in pageResources" :key="`pc-${r.id}`" class="rmp-mat-col-cell" />
              <col v-for="r in dataResources" :key="`dc-${r.id}`" class="rmp-mat-col-cell" />
              <col v-for="r in processResources" :key="`xc-${r.id}`" class="rmp-mat-col-cell" />
              <col v-for="r in appSettingResources" :key="`ac-${r.code}`" class="rmp-mat-col-cell" />
            </colgroup>

            <!-- 分组 header 行 (跨 col 大类) -->
            <thead>
              <tr class="rmp-mat-group-row">
                <th class="rmp-mat-corner" rowspan="2">
                  <span class="rmp-mat-corner-text">角色 \ 资源</span>
                </th>
                <th v-if="pageResources.length" :colspan="pageResources.length" class="rmp-mat-group rmp-mat-g-page">
                  <span class="rmp-mat-group-label">页面</span>
                  <span class="rmp-mat-group-n">{{ pageResources.length }}</span>
                </th>
                <th v-if="dataResources.length" :colspan="dataResources.length" class="rmp-mat-group rmp-mat-g-data">
                  <span class="rmp-mat-group-label">数据</span>
                  <span class="rmp-mat-group-n">{{ dataResources.length }}</span>
                </th>
                <th v-if="processResources.length" :colspan="processResources.length" class="rmp-mat-group rmp-mat-g-process">
                  <span class="rmp-mat-group-label">流程</span>
                  <span class="rmp-mat-group-n">{{ processResources.length }}</span>
                </th>
                <th v-if="appSettingResources.length" :colspan="appSettingResources.length" class="rmp-mat-group rmp-mat-g-app">
                  <span class="rmp-mat-group-label">应用设置</span>
                  <span class="rmp-mat-group-n">{{ appSettingResources.length }}</span>
                </th>
              </tr>
              <!-- 资源 header 行 -->
              <tr class="rmp-mat-sub-row">
                <th
                  v-for="r in pageResources"
                  :key="`ph-${r.id}`"
                  class="rmp-mat-resource rmp-mat-g-page"
                  :title="r.name + (r.code ? ' (' + r.code + ')' : '')"
                >
                  <span class="rmp-mat-rname">{{ r.name || '—' }}</span>
                </th>
                <th
                  v-for="r in dataResources"
                  :key="`dh-${r.id}`"
                  class="rmp-mat-resource rmp-mat-g-data"
                  :title="r.name + (r.code ? ' (' + r.code + ')' : '')"
                >
                  <span class="rmp-mat-rname">{{ r.name || '—' }}</span>
                </th>
                <th
                  v-for="r in processResources"
                  :key="`xh-${r.id}`"
                  class="rmp-mat-resource rmp-mat-g-process"
                  :title="r.name + (r.code ? ' (' + r.code + ')' : '')"
                >
                  <span class="rmp-mat-rname">{{ r.name || '—' }}</span>
                </th>
                <th
                  v-for="r in appSettingResources"
                  :key="`ah-${r.code}`"
                  class="rmp-mat-resource rmp-mat-g-app"
                  :title="r.name"
                >
                  <span class="rmp-mat-rname">{{ r.name }}</span>
                </th>
              </tr>
            </thead>

            <!-- 角色行 -->
            <tbody>
              <tr v-for="role in roles" :key="role.role_id" class="rmp-mat-role-row">
                <td class="rmp-mat-role-cell">
                  <div class="rmp-mat-role-info">
                    <span class="rmp-mat-role-avatar" :data-i="firstChar(role.role_name)">{{ firstChar(role.role_name) }}</span>
                    <div class="rmp-mat-role-text">
                      <span class="rmp-mat-role-name">{{ role.role_name || '(未命名)' }}</span>
                      <span class="rmp-mat-role-count">{{ role.member_count }} 人</span>
                    </div>
                  </div>
                </td>
                <td
                  v-for="r in pageResources"
                  :key="`pcl-${role.role_id}-${r.id}`"
                  class="rmp-mat-cell"
                  :class="cellClass(role.role_id, r.id)"
                  @click="onCellClick(role.role_id, r.id, $event)"
                  role="button"
                  tabindex="0"
                  :title="cellTitle(role.role_id, r.id)"
                >
                  <span class="rmp-mat-chip">{{ cellLabel(role.role_id, r.id) }}</span>
                </td>
                <td
                  v-for="r in dataResources"
                  :key="`dcl-${role.role_id}-${r.id}`"
                  class="rmp-mat-cell"
                  :class="cellClass(role.role_id, r.id)"
                  @click="onCellClick(role.role_id, r.id, $event)"
                  role="button"
                  tabindex="0"
                  :title="cellTitle(role.role_id, r.id)"
                >
                  <span class="rmp-mat-chip">{{ cellLabel(role.role_id, r.id) }}</span>
                </td>
                <td
                  v-for="r in processResources"
                  :key="`xcl-${role.role_id}-${r.id}`"
                  class="rmp-mat-cell"
                  :class="cellClass(role.role_id, r.id)"
                  @click="onCellClick(role.role_id, r.id, $event)"
                  role="button"
                  tabindex="0"
                  :title="cellTitle(role.role_id, r.id)"
                >
                  <span class="rmp-mat-chip">{{ cellLabel(role.role_id, r.id) }}</span>
                </td>
                <td
                  v-for="r in appSettingResources"
                  :key="`acl-${role.role_id}-${r.code}`"
                  class="rmp-mat-cell"
                  :class="cellClass(role.role_id, r.id)"
                  @click="onCellClick(role.role_id, r.id, $event)"
                  role="button"
                  tabindex="0"
                  :title="cellTitle(role.role_id, r.id)"
                >
                  <span class="rmp-mat-chip">{{ cellLabel(role.role_id, r.id) }}</span>
                </td>
              </tr>
              <tr v-if="!roles.length">
                <td :colspan="1 + totalResourceCount" class="rmp-mat-empty-row">
                  暂无角色 — 用 AI 助手对话新建
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 图例 -->
        <footer class="rmp-legend">
          <div class="rmp-legend-items">
            <span class="rmp-legend-chip rmp-perm-all"><span class="rmp-mat-chip">X</span> 全部</span>
            <span class="rmp-legend-chip rmp-perm-rw"><span class="rmp-mat-chip">RW</span> 读写</span>
            <span class="rmp-legend-chip rmp-perm-r"><span class="rmp-mat-chip">R</span> 只读</span>
            <span class="rmp-legend-chip rmp-perm-none"><span class="rmp-mat-chip">-</span> 禁止</span>
          </div>
          <p class="rmp-legend-hint" v-if="isMock">
            * 当前矩阵为推断值 (基于角色名). 真权限 P2 接入 aPaaS list_apaas_form_permissions.
          </p>
        </footer>
      </template>

      <!-- Cell perm dropdown -->
      <div
        v-if="dropdownOpen"
        class="rmp-perm-menu"
        :style="{ left: dropdownPos.x + 'px', top: dropdownPos.y + 'px' }"
        @click.stop
      >
        <button
          v-for="opt in PERM_OPTIONS"
          :key="opt.value"
          class="rmp-perm-opt"
          :class="{ active: opt.value === dropdownCurrent }"
          @click="onPermSelect(opt.value)"
        >
          <span class="rmp-mat-chip" :class="`rmp-perm-${opt.value}`">{{ opt.label }}</span>
          <span class="rmp-perm-opt-name">{{ opt.name }}</span>
        </button>
      </div>
    </div>

    <!-- ── List view (master-detail 老 UI) ───────────────────────── -->
    <div v-else class="rmp-list-wrap">
      <div class="rmp-master">
        <header class="rmp-master-head">
          <span class="rmp-master-title">角色管理</span>
          <span v-if="roles.length" class="rmp-master-count">{{ roles.length }}</span>
        </header>

        <div class="rmp-master-search">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" />
          </svg>
          <input v-model="search" placeholder="搜索角色" />
        </div>

        <div v-if="loading" class="rmp-state">加载角色…</div>
        <div v-else-if="error" class="rmp-state rmp-state-err">{{ error }}</div>
        <ul v-else-if="filteredRoles.length" class="rmp-master-list" role="list">
          <li
            v-for="r in filteredRoles"
            :key="r.role_id"
            class="rmp-master-item"
            :class="{ active: r.role_id === selectedRoleId }"
            @click="selectRole(r.role_id)"
          >
            <span class="rmp-master-item-name">{{ r.role_name || '(未命名)' }}</span>
            <span v-if="r.role_code" class="rmp-master-item-code">{{ r.role_code }}</span>
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
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onBeforeUnmount, reactive } from 'vue'
import request from '@/utils/request'

// ─── Types ────────────────────────────────────────────────────────────────
interface RoleRow {
  role_id: string
  role_code: string
  role_name: string
  member_count: number
}
interface MemberRow {
  account?: string
  name?: string
  phone?: string
  email?: string
}
interface ResourceRow {
  id: string
  code?: string | null
  name: string
}
type PermValue = 'all' | 'rw' | 'r' | 'none'
type ResourceType = 'form' | 'model' | 'process' | 'app_setting'
type MatrixData = Record<string, Record<string, PermValue>>

// 单 cell 改动 dirty 状态 — key: "roleId::resourceId".
interface DirtyCell {
  roleId: string
  resourceId: string
  resourceType: ResourceType
  before: PermValue
  after: PermValue
}
// 单 cell 保存状态 — key 同上. status: 'saving' / 'failed'. 成功后清掉.
type CellSaveStatus = 'saving' | 'failed'

// ─── Const ────────────────────────────────────────────────────────────────
const PERM_OPTIONS: { value: PermValue; label: string; name: string }[] = [
  { value: 'all', label: 'X', name: '全部权限' },
  { value: 'rw', label: 'RW', name: '读写' },
  { value: 'r', label: 'R', name: '只读' },
  { value: 'none', label: '-', name: '禁止' },
]

const PERM_LABELS: Record<PermValue, string> = {
  all: 'X',
  rw: 'RW',
  r: 'R',
  none: '-',
}

const PERM_FULL_NAMES: Record<PermValue, string> = {
  all: '全部权限',
  rw: '读写',
  r: '只读',
  none: '禁止',
}

// ─── Props / State ────────────────────────────────────────────────────────
const props = defineProps<{
  appId: number
}>()

const viewMode = ref<'matrix' | 'list'>('matrix')

// 共享角色 list (两个 view 都用) — 用 matrix endpoint 的 roles 数据.
const roles = ref<RoleRow[]>([])
const loading = ref(false)
const error = ref('')

// list view 状态
const search = ref('')
const selectedRoleId = ref<string>('')
const members = ref<MemberRow[]>([])
const memberSearch = ref('')

// matrix view 状态
const matrixLoading = ref(false)
const matrixError = ref('')
const pageResources = ref<ResourceRow[]>([])
const dataResources = ref<ResourceRow[]>([])
const processResources = ref<ResourceRow[]>([])
const appSettingResources = ref<ResourceRow[]>([])
const matrix = reactive<MatrixData>({})
// initialMatrix — load 时 snapshot 当前矩阵, 用于 dirty diff 计算.
const initialMatrix: MatrixData = {}
const isMock = ref(true)

// dropdown 状态
const dropdownOpen = ref(false)
const dropdownCurrent = ref<PermValue>('rw')
const dropdownPos = reactive({ x: 0, y: 0 })
const dropdownTarget = reactive({ roleId: '', resourceId: '', resourceType: 'form' as ResourceType })

// dirty cell 跟踪 — key: roleId::resourceId.
const dirtyCells = reactive<Record<string, DirtyCell>>({})
// per-cell save status (saving / failed). key 同 dirtyCells.
const cellSaveStatus = reactive<Record<string, CellSaveStatus>>({})
// 全局 save 进度.
const saving = ref(false)
const saveProgress = reactive({ done: 0, total: 0 })

// ─── Computed ─────────────────────────────────────────────────────────────
const filteredRoles = computed(() => {
  const kw = search.value.trim().toLowerCase()
  if (!kw) return roles.value
  return roles.value.filter(r =>
    (r.role_name || '').toLowerCase().includes(kw)
    || (r.role_code || '').toLowerCase().includes(kw),
  )
})

const selectedRole = computed(() => roles.value.find(r => r.role_id === selectedRoleId.value))
const selectedRoleName = computed(() => selectedRole.value?.role_name || '')
const selectedRoleCode = computed(() => selectedRole.value?.role_code || '')

const totalResourceCount = computed(
  () => pageResources.value.length + dataResources.value.length
       + processResources.value.length + appSettingResources.value.length,
)
const totalMemberCount = computed(
  () => roles.value.reduce((sum, r) => sum + (r.member_count || 0), 0),
)
const hasMatrixData = computed(
  () => roles.value.length > 0 && totalResourceCount.value > 0,
)
const dirtyCellCount = computed(() => Object.keys(dirtyCells).length)
const failedCellCount = computed(
  () => Object.values(cellSaveStatus).filter(s => s === 'failed').length,
)

// resourceTypeOf — 给 resourceId 反查它属于哪个 ResourceType.
// 这里用 4 个 resources list 做 lookup, 不需要 backend 字段.
function resourceTypeOf(resourceId: string): ResourceType | null {
  if (pageResources.value.some(r => r.id === resourceId)) return 'form'
  if (dataResources.value.some(r => r.id === resourceId)) return 'model'
  if (processResources.value.some(r => r.id === resourceId)) return 'process'
  if (appSettingResources.value.some(r => r.id === resourceId)) return 'app_setting'
  return null
}

function cellKey(roleId: string, resourceId: string): string {
  return `${roleId}::${resourceId}`
}

// ─── Helpers ──────────────────────────────────────────────────────────────
function firstChar(name: string): string {
  if (!name) return '?'
  const trimmed = name.trim()
  if (!trimmed) return '?'
  return Array.from(trimmed)[0] || '?'
}

function cellLabel(roleId: string, resourceId: string): string {
  const perm = matrix[roleId]?.[resourceId] || 'none'
  return PERM_LABELS[perm as PermValue] || '-'
}

function cellClass(roleId: string, resourceId: string): string {
  const perm = matrix[roleId]?.[resourceId] || 'none'
  const key = cellKey(roleId, resourceId)
  const classes = [`rmp-perm-${perm}`]
  if (dirtyCells[key]) classes.push('rmp-cell-dirty')
  const status = cellSaveStatus[key]
  if (status === 'saving') classes.push('rmp-cell-saving')
  if (status === 'failed') classes.push('rmp-cell-failed')
  return classes.join(' ')
}

function cellTitle(roleId: string, resourceId: string): string {
  const perm = (matrix[roleId]?.[resourceId] || 'none') as PermValue
  const key = cellKey(roleId, resourceId)
  const status = cellSaveStatus[key]
  if (status === 'failed') {
    return `${PERM_FULL_NAMES[perm]} — 上次保存失败, 点击重选`
  }
  const rtype = resourceTypeOf(resourceId)
  if (rtype && rtype !== 'form') {
    return `${PERM_FULL_NAMES[perm]} — ${rtype} 类型权限改动 P5 接入, 暂不真存`
  }
  if (dirtyCells[key]) return `${PERM_FULL_NAMES[perm]} — 未保存, 点击修改`
  return `${PERM_FULL_NAMES[perm]} — 点击修改`
}

// ─── View toggle ──────────────────────────────────────────────────────────
function setView(mode: 'matrix' | 'list') {
  viewMode.value = mode
  closeDropdown()
  // 切到 list 时如果 selectedRoleId 没设, 默认选第一
  if (mode === 'list' && !selectedRoleId.value && roles.value.length > 0) {
    selectRole(roles.value[0].role_id)
  }
}

// ─── Matrix loading ───────────────────────────────────────────────────────
async function loadMatrix() {
  if (!props.appId) return
  matrixLoading.value = true
  matrixError.value = ''
  try {
    const resp = await request.get<any, any>(
      `/applications/${props.appId}/role-resource-matrix`,
    )
    if (!resp?.ok) {
      matrixError.value = resp?.message || resp?.error_code || '加载矩阵失败'
      return
    }
    // 同步 roles 共享 state.
    roles.value = (resp.roles || []).map((r: any) => ({
      role_id: String(r.role_id || ''),
      role_code: String(r.role_code || ''),
      role_name: String(r.role_name || ''),
      member_count: Number(r.member_count || 0),
    })).filter((r: RoleRow) => r.role_id)

    pageResources.value = (resp.resources?.page || []).map(normResource)
    dataResources.value = (resp.resources?.data || []).map(normResource)
    processResources.value = (resp.resources?.process || []).map(normResource)
    appSettingResources.value = (resp.resources?.app_setting || []).map(normResource)

    // matrix reactive replace.
    for (const k of Object.keys(matrix)) delete matrix[k]
    for (const k of Object.keys(initialMatrix)) delete initialMatrix[k]
    const m = (resp.matrix || {}) as MatrixData
    for (const [roleId, row] of Object.entries(m)) {
      const inner: Record<string, PermValue> = {}
      const initialInner: Record<string, PermValue> = {}
      for (const [resourceId, perm] of Object.entries(row || {})) {
        const p = (perm as PermValue) || 'none'
        inner[resourceId] = p
        initialInner[resourceId] = p
      }
      matrix[roleId] = inner
      initialMatrix[roleId] = initialInner
    }
    isMock.value = Boolean(resp.is_mock)

    // 清 dirty + per-cell save 状态 — reload 完一切归零.
    for (const k of Object.keys(dirtyCells)) delete dirtyCells[k]
    for (const k of Object.keys(cellSaveStatus)) delete cellSaveStatus[k]

    error.value = ''
  } catch (e: any) {
    matrixError.value = e?.response?.data?.detail || e?.message || '网络错误'
  } finally {
    matrixLoading.value = false
  }
}

function normResource(r: any): ResourceRow {
  return {
    id: String(r?.id || ''),
    code: r?.code ? String(r.code) : null,
    name: String(r?.name || '—'),
  }
}

// ─── List view loading (fallback when matrix endpoint 失败时也用) ─────────
async function loadRolesOnly() {
  if (!props.appId) return
  loading.value = true
  error.value = ''
  try {
    const resp = await request.get<any, any>(
      `/applications/${props.appId}/section-content/roles`,
    )
    if (resp?.ok) {
      const items = (resp.items || []) as any[]
      // 老 endpoint 字段: id / name / code. 转 RoleRow.
      roles.value = items.map(it => ({
        role_id: String(it.id || ''),
        role_code: String(it.code || ''),
        role_name: String(it.name || ''),
        member_count: 0,
      })).filter(r => r.role_id)
      if (!selectedRoleId.value && roles.value.length > 0) {
        selectRole(roles.value[0].role_id)
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

// ─── Cell dropdown ────────────────────────────────────────────────────────
function onCellClick(roleId: string, resourceId: string, evt: MouseEvent) {
  if (saving.value) return  // 保存中禁止改
  const target = evt.currentTarget as HTMLElement
  if (!target) return
  const rect = target.getBoundingClientRect()
  // 计算相对 .rmp-matrix-wrap 容器
  const wrap = target.closest('.rmp-matrix-wrap') as HTMLElement | null
  const wrapRect = wrap?.getBoundingClientRect() || { left: 0, top: 0 } as any
  dropdownPos.x = rect.left - wrapRect.left
  dropdownPos.y = rect.bottom - wrapRect.top + 4
  dropdownTarget.roleId = roleId
  dropdownTarget.resourceId = resourceId
  dropdownTarget.resourceType = resourceTypeOf(resourceId) || 'form'
  dropdownCurrent.value = (matrix[roleId]?.[resourceId] || 'none') as PermValue
  dropdownOpen.value = true
}

function onPermSelect(perm: PermValue) {
  const { roleId, resourceId, resourceType } = dropdownTarget
  if (!roleId || !resourceId) {
    closeDropdown()
    return
  }
  const before = (matrix[roleId]?.[resourceId] || 'none') as PermValue
  // 本地 state 立即更新 (优化感知).
  if (!matrix[roleId]) matrix[roleId] = {}
  matrix[roleId][resourceId] = perm

  // dirty 跟踪: 跟 initialMatrix 比 (这里用 cellSaveStatus 之前 = before).
  // 若新值跟 initial 一致, 移出 dirty; 否则加 dirty.
  // initialMatrix 我们从 reload 时存的副本里查 — 这里简化: 跟 before 比即可.
  const key = cellKey(roleId, resourceId)
  const initial = initialMatrix[roleId]?.[resourceId] || 'none'
  if (perm === initial) {
    delete dirtyCells[key]
  } else {
    dirtyCells[key] = { roleId, resourceId, resourceType, before, after: perm }
  }
  // 清掉之前 failed 状态 — 用户重新选了
  if (cellSaveStatus[key] === 'failed') delete cellSaveStatus[key]
  closeDropdown()
}

function closeDropdown() {
  dropdownOpen.value = false
  dropdownTarget.roleId = ''
  dropdownTarget.resourceId = ''
}

function onDocClick(evt: MouseEvent) {
  if (!dropdownOpen.value) return
  const el = evt.target as HTMLElement
  // click 外部 → close. cell 自己点击会重新 open, 不冲突.
  if (el.closest('.rmp-perm-menu')) return
  if (el.closest('.rmp-mat-cell')) return
  closeDropdown()
}

// ─── Actions ──────────────────────────────────────────────────────────────
function onAddRole() {
  alert('新增角色 — 当前请用右侧配置助手对话:\n"新建一个审批人角色"')
}

function onAddMember() {
  alert('添加成员 — 当前请用右侧配置助手对话:\n"给运维专员A角色添加用户XX"')
}

// ─── Save matrix (Phase H1) ───────────────────────────────────────────────
// 串行 POST per dirty cell. form 类型真存 apaas, 其他 P5 跳过.
async function onSaveMatrix() {
  const allDirty = Object.values(dirtyCells)
  if (allDirty.length === 0) {
    alert('暂无未保存的权限改动')
    return
  }
  if (saving.value) return  // 防止双击

  // form 类型 = 真存; 其他 = 跳过 (P5).
  const formDirty = allDirty.filter(c => c.resourceType === 'form')
  const skipDirty = allDirty.filter(c => c.resourceType !== 'form')

  const okStr = window.confirm(
    `保存 ${formDirty.length} 个权限改动 — 真存到 aPaaS?\n`
    + (skipDirty.length > 0 ? `(另 ${skipDirty.length} 个 model/process/app_setting 改动 P5 接入, 本次跳过)\n` : '')
    + '\n注: 表单权限是覆盖式写入, 会保留其他角色的现有权限.',
  )
  if (!okStr) return

  if (formDirty.length === 0) {
    alert(`暂无 form 类型改动可保存 (${skipDirty.length} 个非 form 改动 P5 接入)`)
    return
  }

  saving.value = true
  saveProgress.done = 0
  saveProgress.total = formDirty.length

  let successCount = 0
  let failedCount = 0
  const failedKeys: string[] = []

  for (const cell of formDirty) {
    const key = cellKey(cell.roleId, cell.resourceId)
    cellSaveStatus[key] = 'saving'
    try {
      const resp = await request.post<any, any>(
        `/applications/${props.appId}/role-resource-matrix/cell`,
        {
          role_id: cell.roleId,
          resource_type: cell.resourceType,
          resource_id: cell.resourceId,
          permission: cell.after,
        },
      )
      if (resp?.ok) {
        successCount++
        delete dirtyCells[key]
        delete cellSaveStatus[key]
        // 把 initialMatrix 也更新 (新值现在已是 source of truth).
        if (!initialMatrix[cell.roleId]) initialMatrix[cell.roleId] = {}
        initialMatrix[cell.roleId][cell.resourceId] = cell.after
      } else {
        failedCount++
        failedKeys.push(key)
        cellSaveStatus[key] = 'failed'
        // eslint-disable-next-line no-console
        console.warn('保存 cell 失败', key, resp)
      }
    } catch (e: any) {
      failedCount++
      failedKeys.push(key)
      cellSaveStatus[key] = 'failed'
      // eslint-disable-next-line no-console
      console.error('保存 cell 异常', key, e)
    }
    saveProgress.done++
  }

  saving.value = false

  if (failedCount === 0) {
    alert(`已保存 ${successCount} 个权限改动`
      + (skipDirty.length > 0 ? ` (${skipDirty.length} 个非 form 跳过)` : ''))
    // 全成功 → reload 拉最新真值.
    await loadMatrix()
  } else if (successCount === 0) {
    alert(`全部 ${failedCount} 个保存失败 — 检查 console 详情 (失败 cell 红色高亮)`)
  } else {
    alert(`已保存 ${successCount}/${formDirty.length}, ${failedCount} 个失败 — 检查 console (失败 cell 红色高亮)`)
  }
}

// 丢弃未保存改动 — 回到 initialMatrix.
function onDiscardChanges() {
  if (Object.keys(dirtyCells).length === 0) return
  if (!window.confirm(`丢弃 ${Object.keys(dirtyCells).length} 个未保存改动?`)) return
  for (const [roleId, row] of Object.entries(initialMatrix)) {
    for (const [resourceId, perm] of Object.entries(row || {})) {
      if (!matrix[roleId]) matrix[roleId] = {}
      matrix[roleId][resourceId] = perm
    }
  }
  for (const k of Object.keys(dirtyCells)) delete dirtyCells[k]
  for (const k of Object.keys(cellSaveStatus)) delete cellSaveStatus[k]
}

// ─── Lifecycle ────────────────────────────────────────────────────────────
async function load() {
  if (!props.appId) return
  await loadMatrix()
  // 矩阵 endpoint 失败时降级拉单独 roles list 让 list view 仍可用.
  if (matrixError.value && roles.value.length === 0) {
    await loadRolesOnly()
  } else {
    loading.value = false
  }
}

watch(() => props.appId, () => load(), { immediate: true })

onMounted(() => {
  document.addEventListener('click', onDocClick)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick)
})
</script>

<style scoped>
.rmp {
  display: flex;
  flex-direction: column;
  font-family: var(--font-sans);
  background: var(--bg);
  height: 100%;
  overflow: hidden;
  font-feature-settings: 'cv11', 'ss01';
  color: var(--text);
}

/* ── Page header ───────────────────────────────────────────────── */
.rmp-page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 20px 28px 16px;
  border-bottom: 1px solid var(--line);
  background: var(--surface);
  flex-shrink: 0;
}
.rmp-head-meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}
.rmp-page-title {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: var(--text);
  letter-spacing: -0.01em;
}
.rmp-page-stat {
  margin: 0;
  font-size: 12.5px;
  color: var(--text-3);
  display: flex;
  align-items: center;
  gap: 8px;
}
.rmp-page-stat b {
  font-weight: 600;
  color: var(--text);
}
.rmp-page-stat.err { color: var(--err); }
.rmp-dot {
  color: var(--text-4);
  user-select: none;
}

.rmp-head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

/* ── View toggle ───────────────────────────────────────────────── */
.rmp-view-toggle {
  display: inline-flex;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 2px;
  margin-right: 4px;
}
.rmp-toggle-btn {
  height: 28px;
  padding: 0 14px;
  font-size: 12.5px;
  font-weight: 500;
  font-family: inherit;
  background: transparent;
  border: 0;
  border-radius: 6px;
  color: var(--text-3);
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
  white-space: nowrap;
}
.rmp-toggle-btn:hover {
  color: var(--text);
}
.rmp-toggle-btn.active {
  background: var(--surface);
  color: var(--brand);
  box-shadow: 0 1px 2px rgba(11, 27, 63, 0.06);
}

/* ── Btn ───────────────────────────────────────────────────────── */
.rmp-btn {
  height: 32px;
  padding: 0 14px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  border: 1px solid transparent;
  white-space: nowrap;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.rmp-btn-primary {
  background: var(--brand);
  color: #fff;
}
.rmp-btn-primary:hover { background: var(--brand-hover); }
.rmp-btn-ghost {
  background: var(--surface);
  border-color: var(--line);
  color: var(--text-2);
}
.rmp-btn-ghost:hover:not(:disabled) {
  border-color: var(--line-strong);
  color: var(--text);
}
.rmp-btn-ghost:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

/* ── Matrix view wrap ──────────────────────────────────────────── */
.rmp-matrix-wrap {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 20px 28px 8px;
  position: relative;
}

.rmp-matrix-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
  box-shadow: var(--sh-1);
}

/* ── Matrix table ──────────────────────────────────────────────── */
.rmp-matrix-table {
  border-collapse: separate;
  border-spacing: 0;
  font-size: 12.5px;
  width: 100%;
  table-layout: fixed;
}
.rmp-mat-col-role { width: 220px; }
.rmp-mat-col-cell { width: 76px; }

.rmp-matrix-table thead th {
  background: var(--surface-2);
  font-weight: 500;
  color: var(--text-2);
  position: sticky;
  z-index: 2;
}
.rmp-mat-group-row th { top: 0; }
.rmp-mat-sub-row th { top: 38px; }

.rmp-mat-corner {
  left: 0;
  z-index: 4 !important;
  background: var(--surface-2);
  border-right: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  text-align: left;
  padding: 10px 14px;
  vertical-align: middle;
  font-size: 12px;
  color: var(--text-3);
  font-weight: 500;
}
.rmp-mat-corner-text {
  white-space: nowrap;
}
.rmp-mat-group {
  height: 38px;
  padding: 0 12px;
  border-bottom: 1px solid var(--line);
  border-right: 1px dashed var(--line);
  text-align: center;
  display: table-cell;
  vertical-align: middle;
}
.rmp-mat-group-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
  margin-right: 4px;
}
.rmp-mat-group-n {
  font-size: 11px;
  color: var(--text-3);
  background: var(--surface-3);
  padding: 1px 6px;
  border-radius: 999px;
  font-weight: 500;
}
.rmp-mat-g-page .rmp-mat-group-label { color: var(--blue-700); }
.rmp-mat-g-data .rmp-mat-group-label { color: var(--text); }
.rmp-mat-g-process .rmp-mat-group-label { color: var(--text); }
.rmp-mat-g-app .rmp-mat-group-label { color: var(--text); }

.rmp-mat-resource {
  height: 56px;
  padding: 6px 4px;
  border-bottom: 1px solid var(--line);
  border-right: 1px solid var(--line);
  text-align: center;
  vertical-align: middle;
  font-size: 11.5px;
  color: var(--text-2);
  font-weight: 500;
  background: var(--surface-2);
}
.rmp-mat-rname {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  line-height: 1.3;
  text-align: center;
  padding: 0 4px;
}

/* ── Matrix body rows ─────────────────────────────────────────── */
.rmp-mat-role-row {
  transition: background 0.12s;
}
.rmp-mat-role-row:hover { background: var(--surface-2); }

.rmp-mat-role-cell {
  position: sticky;
  left: 0;
  z-index: 1;
  background: var(--surface);
  border-right: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  padding: 10px 14px;
  vertical-align: middle;
}
.rmp-mat-role-row:hover .rmp-mat-role-cell { background: var(--surface-2); }

.rmp-mat-role-info {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.rmp-mat-role-avatar {
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  border-radius: 999px;
  background: var(--brand-soft);
  color: var(--brand);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
}
.rmp-mat-role-text {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.rmp-mat-role-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 160px;
}
.rmp-mat-role-count {
  font-size: 11px;
  color: var(--text-3);
}

.rmp-mat-cell {
  height: 36px;
  padding: 0;
  border-bottom: 1px solid var(--line);
  border-right: 1px solid var(--line);
  text-align: center;
  vertical-align: middle;
  cursor: pointer;
  transition: box-shadow 0.12s, background 0.12s;
  background: var(--surface);
  outline: none;
}
.rmp-mat-cell:hover {
  background: var(--brand-soft);
  box-shadow: inset 0 0 0 1px var(--brand);
}
.rmp-mat-cell:focus-visible {
  box-shadow: inset 0 0 0 2px var(--brand);
}
.rmp-mat-role-row:hover .rmp-mat-cell:not(:hover) {
  background: var(--surface-2);
}

/* ── Perm chips ────────────────────────────────────────────────── */
.rmp-mat-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 32px;
  height: 22px;
  padding: 0 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  font-family: var(--font-mono);
  letter-spacing: 0.02em;
  user-select: none;
}
.rmp-perm-all .rmp-mat-chip {
  background: var(--warn-soft);
  color: var(--warn);
}
.rmp-perm-rw .rmp-mat-chip {
  background: var(--brand-soft);
  color: var(--brand);
}
.rmp-perm-r .rmp-mat-chip {
  background: var(--surface-3);
  color: var(--text-2);
}
.rmp-perm-none .rmp-mat-chip {
  background: transparent;
  color: var(--text-4);
}

.rmp-mat-empty-row {
  text-align: center;
  padding: 40px 16px;
  color: var(--text-4);
  font-size: 13px;
  background: var(--surface);
}

/* ── Legend ────────────────────────────────────────────────────── */
.rmp-legend {
  flex-shrink: 0;
  padding: 14px 4px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.rmp-legend-items {
  display: flex;
  gap: 18px;
  flex-wrap: wrap;
}
.rmp-legend-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-2);
}
.rmp-legend-hint {
  margin: 0;
  font-size: 11.5px;
  color: var(--text-4);
  font-style: italic;
}

/* ── Cell perm dropdown ────────────────────────────────────────── */
.rmp-perm-menu {
  position: absolute;
  z-index: 50;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  box-shadow: 0 10px 30px rgba(11, 27, 63, 0.16);
  padding: 4px;
  min-width: 140px;
  animation: rmp-fade-in 0.12s ease-out;
}
@keyframes rmp-fade-in {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}
.rmp-perm-opt {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  background: transparent;
  border: 0;
  padding: 8px 10px;
  border-radius: 5px;
  font-family: inherit;
  cursor: pointer;
  text-align: left;
}
.rmp-perm-opt:hover { background: var(--surface-2); }
.rmp-perm-opt.active { background: var(--brand-soft); }
.rmp-perm-opt-name {
  font-size: 12.5px;
  color: var(--text);
  font-weight: 500;
}

/* ── State (loading / error / empty) ──────────────────────────── */
.rmp-state {
  padding: 36px 16px;
  text-align: center;
  color: var(--text-3);
  font-size: 13px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}
.rmp-state-err { color: var(--err); }
.rmp-state-empty { color: var(--text-3); }
.rmp-state-empty .hint {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-4);
}
.rmp-empty-illustration {
  font-size: 36px;
  opacity: 0.7;
}

/* ─────────────────────────────────────────────────────────────────
   List view (master-detail) — 老 UI 保留
───────────────────────────────────────────────────────────────── */
.rmp-list-wrap {
  flex: 1;
  display: flex;
  min-height: 0;
  overflow: hidden;
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
</style>
