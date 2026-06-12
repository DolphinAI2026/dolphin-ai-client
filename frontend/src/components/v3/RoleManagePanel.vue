<!-- RoleManagePanel.vue — Native 角色权限 只读 (矩阵 view + 列表 view 切换) + 深链低代码后台.

  2026-05-26 design-v4 Phase D: 顶部 toggle 切矩阵 (默认) / 角色列表 2 view.

  矩阵 view: 角色 × 资源 (页面/数据/流程/应用设置) 4 状态 chip (all/rw/r/none), 只读展示.
  列表 view: 老 master-detail 保留 (左角色 list + 右成员 table), 只读展示.

  2026-06-04: 去内嵌编辑 — 纯只读 (矩阵 + 成员展示), 改角色 / 权限 / 成员走配置助手对话,
    或点上方「打开低代码后台」(OpenLowcodeBackendButton) 进 apaas 原生编辑器新标签页.
    删 editMode preview/edit 切换 + cell click dropdown + 新增角色 / 添加成员 + 矩阵写调用.
    保留 matrix / list 两个查看 view 切换 (只是查看方式, 非编辑).

  数据源:
    - 矩阵 view: /role-resource-matrix endpoint (一次拉全, GET 只读)
    - 列表 view: /section-content/roles endpoint (老兼容, GET 只读)
-->
<template>
  <section class="rmp" aria-label="角色权限">
    <!-- O2: 业务视角 banner -->
    <div class="rmp-biz-banner" role="note">
      <span class="rmp-biz-banner-icon" aria-hidden="true"><AppIcon name="sparkles" :size="16" /></span>
      <span class="rmp-biz-banner-text">
        业务视角预览 — 这是应用的<strong>角色权限</strong>状态. 改角色 / 权限用配置助手对话.
      </span>
    </div>

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
        <OpenLowcodeBackendButton
          :app-id="props.appId"
          title="在低代码后台编辑角色权限"
        />
        <!-- 视图 toggle (matrix / list) — 查看方式切换 (非编辑) -->
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
      </div>
    </header>

    <!-- ── Matrix view ────────────────────────────────────────── -->
    <div v-if="viewMode === 'matrix'" class="rmp-matrix-wrap rmp-matrix-wrap-preview">
      <SkeletonCard v-if="matrixLoading" :lines="5" />
      <ErrorCard
        v-else-if="matrixError"
        level="err"
        title="加载失败"
        :message="matrixError"
        :actions="[{ label: '重试', onClick: reload }]"
      />
      <EmptyState
        v-else-if="!hasMatrixData"
        title="暂无角色或资源"
        desc="先创建角色 + 部署应用, 再回这里配权限"
      >
        <template #icon><AppIcon name="shield" :size="32" /></template>
      </EmptyState>
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
                  :title="cellTitle(role.role_id, r.id)"
                >
                  <span class="rmp-mat-chip">{{ cellLabel(role.role_id, r.id) }}</span>
                </td>
                <td
                  v-for="r in dataResources"
                  :key="`dcl-${role.role_id}-${r.id}`"
                  class="rmp-mat-cell"
                  :class="cellClass(role.role_id, r.id)"
                  :title="cellTitle(role.role_id, r.id)"
                >
                  <span class="rmp-mat-chip">{{ cellLabel(role.role_id, r.id) }}</span>
                </td>
                <td
                  v-for="r in processResources"
                  :key="`xcl-${role.role_id}-${r.id}`"
                  class="rmp-mat-cell"
                  :class="cellClass(role.role_id, r.id)"
                  :title="cellTitle(role.role_id, r.id)"
                >
                  <span class="rmp-mat-chip">{{ cellLabel(role.role_id, r.id) }}</span>
                </td>
                <td
                  v-for="r in appSettingResources"
                  :key="`acl-${role.role_id}-${r.code}`"
                  class="rmp-mat-cell"
                  :class="cellClass(role.role_id, r.id)"
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

        <div v-if="loading" class="rmp-master-skel"><SkeletonCard :lines="5" /></div>
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
          <div class="rmp-detail-empty-icon"><AppIcon name="users" :size="48" /></div>
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
                    <div class="empty-illustration"><AppIcon name="clipboard" :size="36" /></div>
                    <p>暂无数据</p>
                    <p class="hint">用配置助手对话添加成员, 或点上方「打开低代码后台」</p>
                  </td>
                </tr>
                <tr v-for="(m, i) in members" :key="m.account || i">
                  <td class="check"><input type="checkbox" /></td>
                  <td>{{ m.name || '—' }}</td>
                  <td class="mono">{{ m.account || '—' }}</td>
                  <td>{{ m.phone || '—' }}</td>
                  <td>{{ m.email || '—' }}</td>
                  <td class="ops">
                    <button class="rmp-icon-btn" disabled><AppIcon name="more" :size="14" /></button>
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
import { ref, computed, watch, reactive } from 'vue'
import request from '@/utils/request'
import SkeletonCard from '@/components/states/SkeletonCard.vue'
import OpenLowcodeBackendButton from '@/components/v3/OpenLowcodeBackendButton.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import ErrorCard from '@/components/states/ErrorCard.vue'
import AppIcon from '@/components/common/AppIcon.vue'

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
type MatrixData = Record<string, Record<string, PermValue>>

// ─── Const ────────────────────────────────────────────────────────────────
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
const isMock = ref(true)

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
  return `rmp-perm-${perm}`
}

// 只读 — 恒显权限全名 (不再有 dirty/failed/"点击修改" 编辑态文案).
function cellTitle(roleId: string, resourceId: string): string {
  const perm = (matrix[roleId]?.[resourceId] || 'none') as PermValue
  return PERM_FULL_NAMES[perm]
}

// ─── View toggle ──────────────────────────────────────────────────────────
function setView(mode: 'matrix' | 'list') {
  viewMode.value = mode
  // 切到 list 时如果 selectedRoleId 没设, 默认选第一
  if (mode === 'list' && !selectedRoleId.value && roles.value.length > 0) {
    selectRole(roles.value[0].role_id)
  }
}

// ─── Matrix loading ───────────────────────────────────────────────────────
async function loadMatrix(opts: { force?: boolean } = {}) {
  if (!props.appId) return
  matrixLoading.value = true
  matrixError.value = ''
  try {
    // force=true 跳过后端 180s 缓存 — 重试/写后刷新必须绕过, 否则命中缓存返改前 stale。
    const url = `/applications/${props.appId}/role-resource-matrix${opts.force ? '?force=true' : ''}`
    const resp = await request.get<any, any>(url)
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
    const m = (resp.matrix || {}) as MatrixData
    for (const [roleId, row] of Object.entries(m)) {
      const inner: Record<string, PermValue> = {}
      for (const [resourceId, perm] of Object.entries(row || {})) {
        inner[resourceId] = (perm as PermValue) || 'none'
      }
      matrix[roleId] = inner
    }
    isMock.value = Boolean(resp.is_mock)

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
async function loadRolesOnly(opts: { force?: boolean } = {}) {
  if (!props.appId) return
  loading.value = true
  error.value = ''
  try {
    const url = `/applications/${props.appId}/section-content/roles${opts.force ? '?force=true' : ''}`
    const resp = await request.get<any, any>(url)
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

// ─── Lifecycle ────────────────────────────────────────────────────────────
async function load(opts: { force?: boolean } = {}) {
  if (!props.appId) return
  await loadMatrix(opts)
  // 矩阵 endpoint 失败时降级拉单独 roles list 让 list view 仍可用.
  if (matrixError.value && roles.value.length === 0) {
    await loadRolesOnly(opts)
  } else {
    loading.value = false
  }
}

// 初始加载 / 切应用走缓存(性能); 重试/写后刷新走 force(见 reload)。
watch(() => props.appId, () => load(), { immediate: true })

/** 用户主动刷新 — 绕过 180s 缓存重打 aPaaS。模板 "重试" 按钮 + 写后刷新都走这。 */
function reload() {
  void load({ force: true })
}
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

/* ── O2: 业务视角 banner ─────────────────────────────────────────── */
.rmp-biz-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: var(--s-3) var(--s-4);
  margin: var(--s-4) 28px 0;
  background: var(--brand-soft);
  color: var(--brand);
  border: 1px solid var(--brand);
  border-left: 4px solid var(--brand);
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.5;
  flex-shrink: 0;
}
.rmp-biz-banner-icon {
  font-size: 16px;
  line-height: 1;
  flex-shrink: 0;
}
.rmp-biz-banner-text {
  flex: 1;
  color: var(--text-2);
}
.rmp-biz-banner-text strong {
  color: var(--brand);
  font-weight: 600;
}

/* 只读 matrix — cell 不可 hover 改 (恒只读样式, 静态挂 .rmp-matrix-wrap-preview) */
.rmp-matrix-wrap-preview .rmp-mat-cell {
  cursor: default;
}
.rmp-matrix-wrap-preview .rmp-mat-cell:hover {
  background: var(--surface);
  box-shadow: none;
}
.rmp-matrix-wrap-preview .rmp-mat-role-row:hover .rmp-mat-cell:not(:hover) {
  background: var(--surface);
}

/* ── Page header ───────────────────────────────────────────────── */
.rmp-page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--s-4);
  padding: var(--s-5) 28px var(--s-4);
  border-bottom: 1px solid var(--line);
  background: var(--surface);
  flex-shrink: 0;
}
.rmp-head-meta {
  display: flex;
  flex-direction: column;
  gap: var(--s-1);
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
  gap: var(--s-2);
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
  gap: var(--s-2);
  flex-shrink: 0;
}

/* ── View toggle ───────────────────────────────────────────────── */
.rmp-view-toggle {
  display: inline-flex;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 2px;
  margin-right: var(--s-1);
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
  color: var(--text-inverse);
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
  padding: var(--s-5) 28px var(--s-2);
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
  padding: 0 var(--s-3);
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
  margin-right: var(--s-1);
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
  padding: 6px var(--s-1);
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
  padding: 0 var(--s-1);
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
  padding: 0 var(--s-2);
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
  padding: var(--s-10) var(--s-4);
  color: var(--text-4);
  font-size: 13px;
  background: var(--surface);
}

/* ── Legend ────────────────────────────────────────────────────── */
.rmp-legend {
  flex-shrink: 0;
  padding: 14px var(--s-1) var(--s-3);
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

/* ── State (loading / error / empty) ──────────────────────────── */
.rmp-state {
  padding: 36px var(--s-4);
  text-align: center;
  color: var(--text-3);
  font-size: 13px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--s-3);
}
.rmp-state-err { color: var(--err); }
.rmp-state-empty { color: var(--text-3); }
.rmp-state-empty .hint {
  margin-top: var(--s-1);
  font-size: 12px;
  color: var(--text-4);
}
.rmp-master-skel {
  padding: var(--s-3);
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
  gap: var(--s-2);
  padding: 14px var(--s-4);
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
  padding: 1px var(--s-2);
  border-radius: 999px;
}

.rmp-master-search {
  position: relative;
  padding: var(--s-2) var(--s-3);
  flex-shrink: 0;
}
.rmp-master-search input {
  width: 100%;
  height: 30px;
  padding: 0 var(--s-3) 0 var(--s-8);
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
  padding: var(--s-1) var(--s-2);
  flex: 1;
  overflow-y: auto;
}
.rmp-master-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px var(--s-3);
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
  gap: var(--s-3);
}
.rmp-detail-empty-icon { font-size: 48px; }
.rmp-detail-empty p { margin: 0; font-size: 14px; }

.rmp-detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--s-4);
  margin-bottom: var(--s-5);
  padding-bottom: var(--s-5);
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
  padding: 2px var(--s-2);
  font-size: 12px;
  font-family: var(--font-mono);
  background: var(--surface-2);
  border-radius: 4px;
  color: var(--text-3);
}

.rmp-detail-actions {
  display: flex;
  align-items: center;
  gap: var(--s-2);
}
.rmp-detail-search {
  height: 32px;
  width: 200px;
  padding: 0 var(--s-3);
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
  padding: 11px var(--s-4);
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
  padding: var(--s-3) var(--s-4);
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
  padding: 56px var(--s-4);
  color: var(--text-4);
}
.rmp-table .empty .empty-illustration {
  font-size: 36px;
  opacity: 0.6;
  margin-bottom: var(--s-2);
}
.rmp-table .empty .hint {
  margin-top: var(--s-2);
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
