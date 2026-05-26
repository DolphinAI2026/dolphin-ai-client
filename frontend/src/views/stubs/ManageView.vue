<!-- ManageView.vue — 平台管理统一入口 (design-v4 Phase I1, 2026-05-26).

  替换 G3 stub. 复用现有 endpoint:
    - 应用 → /api/applications (applicationApi.list)
    - 环境 → /api/platform-envs (platformEnvApi.list)
    - 用户 → 当前无 tenant-wide list endpoint, placeholder + 跳 /admin
    - 租户 → 当前无 list endpoint (各 user 只在自己 tenant), placeholder + 跳 /admin

  视觉对齐 DatasourcesView.vue (H3 pattern).

  4 sub-tab: 应用 / 用户 / 租户 / 环境.

  P6 留尾: 接 tenant_users 列表 + 跨 tenant admin 视图 (需平台管理员权限).
-->
<template>
  <main class="ds-page">
    <header class="ds-head">
      <div class="ds-head-meta">
        <h1 class="ds-title">应用管理</h1>
        <p class="ds-stats">
          <span>{{ appCount }} 个应用</span>
          <span class="ds-stat-sep">·</span>
          <span>{{ envCount }} 个环境</span>
          <span class="ds-stat-sep">·</span>
          <span class="ds-stat-muted">用户/租户 → /admin</span>
        </p>
      </div>
      <div class="ds-head-actions">
        <button class="ds-btn ds-btn-ghost" @click="goAdmin">
          <span class="ds-btn-icon">↗</span>
          打开管理后台
        </button>
      </div>
    </header>

    <div class="ds-subnav" role="tablist">
      <button
        v-for="t in SUB_TABS"
        :key="t.code"
        class="ds-subnav-tab"
        :class="{ active: subTab === t.code }"
        role="tab"
        :aria-selected="subTab === t.code"
        @click="subTab = t.code"
      >
        {{ t.label }}
        <span v-if="t.count !== undefined" class="ds-subnav-count">{{ t.count }}</span>
      </button>
    </div>

    <!-- 应用 -->
    <section v-if="subTab === 'apps'" class="ds-section">
      <div v-if="appLoading" class="ds-state">加载中…</div>
      <div v-else-if="appError" class="ds-state ds-state-err">
        {{ appError }}
        <button class="ds-btn ds-btn-ghost" @click="loadApps">重试</button>
      </div>
      <div v-else-if="apps.length === 0" class="ds-empty">
        <div class="ds-empty-icon">📦</div>
        <h3>暂无应用</h3>
        <p>从首页发起需求, AI 会自动生成应用配置.</p>
        <button class="ds-btn ds-btn-primary" @click="goLanding">前往新建</button>
      </div>
      <div v-else class="ds-table-wrap">
        <table class="ds-table">
          <thead>
            <tr>
              <th class="num">#</th>
              <th class="col-name">应用名</th>
              <th class="col-code">Code</th>
              <th class="col-source">来源</th>
              <th class="col-env">环境</th>
              <th class="col-time">更新时间</th>
              <th class="col-status">状态</th>
              <th class="col-ops">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(a, i) in apps" :key="a.id">
              <td class="num">{{ i + 1 }}</td>
              <td class="col-name">
                <div class="ds-cell-name">{{ a.app_name }}</div>
                <div v-if="a.description" class="ds-cell-desc">{{ a.description }}</div>
              </td>
              <td class="col-code mono">{{ a.app_code || '—' }}</td>
              <td class="col-source">
                <span class="ds-badge ds-badge-src mono">{{ a.source.toUpperCase() }}</span>
              </td>
              <td class="col-env muted">{{ a.env_name || '—' }}</td>
              <td class="col-time mono muted">{{ formatTime(a.updated_at) }}</td>
              <td class="col-status">
                <span class="ds-status-chip" :class="appStatusClass(a)">
                  {{ appStatusLabel(a) }}
                </span>
              </td>
              <td class="col-ops">
                <button class="ds-link-btn" @click="openApp(a)" title="进入应用">打开</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- 用户 -->
    <section v-else-if="subTab === 'users'" class="ds-section">
      <div class="ds-empty">
        <div class="ds-empty-icon">👥</div>
        <h3>用户管理</h3>
        <p>P6 接入 — 当前 tenant 内用户列表 + 角色/邀请管理.</p>
        <p class="ds-empty-hint">临时入口: 管理后台 /admin/users</p>
        <button class="ds-btn ds-btn-primary" @click="goAdminUsers">前往管理后台</button>
      </div>
    </section>

    <!-- 租户 -->
    <section v-else-if="subTab === 'tenants'" class="ds-section">
      <div class="ds-empty">
        <div class="ds-empty-icon">🏢</div>
        <h3>租户管理</h3>
        <p>P6 接入 — 跨租户列表 (需平台管理员权限).</p>
        <p class="ds-empty-hint">临时入口: 管理后台 /admin/tenants</p>
        <button class="ds-btn ds-btn-primary" @click="goAdminTenants">前往管理后台</button>
      </div>
    </section>

    <!-- 环境 -->
    <section v-else class="ds-section">
      <div v-if="envLoading" class="ds-state">加载中…</div>
      <div v-else-if="envError" class="ds-state ds-state-err">
        {{ envError }}
        <button class="ds-btn ds-btn-ghost" @click="loadEnvs">重试</button>
      </div>
      <div v-else-if="envs.length === 0" class="ds-empty">
        <div class="ds-empty-icon">🔗</div>
        <h3>暂无环境</h3>
        <p>添加 aPaaS 平台环境 (trial / 公司部署), 让 AI 直接读应用 / 发布到 aPaaS.</p>
        <button class="ds-btn ds-btn-primary" @click="goEnvManage">前往管理</button>
      </div>
      <div v-else class="ds-table-wrap">
        <table class="ds-table">
          <thead>
            <tr>
              <th class="num">#</th>
              <th class="col-name">名称</th>
              <th class="col-url">URL</th>
              <th class="col-tenant">租户</th>
              <th class="col-user">登录用户</th>
              <th class="col-status">状态</th>
              <th class="col-default">默认</th>
              <th class="col-ops">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(e, i) in envs" :key="e.id">
              <td class="num">{{ i + 1 }}</td>
              <td class="col-name">
                <div class="ds-cell-name">{{ e.env_name }}</div>
              </td>
              <td class="col-url mono">{{ trimUrl(e.base_url) }}</td>
              <td class="col-tenant mono">{{ e.platform_tenant_id }}</td>
              <td class="col-user mono muted">{{ e.username || '—' }}</td>
              <td class="col-status">
                <span class="ds-status-chip" :class="envStatusClass(e)">
                  {{ envStatusLabel(e) }}
                </span>
              </td>
              <td class="col-default">
                <span v-if="e.is_default" class="ds-badge ds-badge-primary">默认</span>
                <span v-else class="ds-empty-cell">—</span>
              </td>
              <td class="col-ops">
                <button class="ds-link-btn" @click="goEnvManage" title="跳转管理">管理</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </main>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { applicationApi } from '@/api/application'
import { platformEnvApi, type PlatformEnv } from '@/api/platformEnv'
import type { MergedApplication } from '@/types'

type SubCode = 'apps' | 'users' | 'tenants' | 'envs'

const router = useRouter()
const subTab = ref<SubCode>('apps')

// ─── 应用 ────────────────────────────────────────────────────────────────
const apps = ref<MergedApplication[]>([])
const appLoading = ref(true)
const appError = ref('')

async function loadApps() {
  appLoading.value = true
  appError.value = ''
  try {
    const list = await applicationApi.list()
    apps.value = list || []
  } catch (e: any) {
    appError.value = e?.response?.data?.detail || e?.message || '加载失败'
    apps.value = []
  } finally {
    appLoading.value = false
  }
}

function formatTime(t?: string): string {
  if (!t) return '—'
  // 简单 ISO → 日期
  const d = new Date(t)
  if (isNaN(d.getTime())) return t
  return d.toISOString().slice(0, 10)
}

function appStatusClass(a: MergedApplication): string {
  if (a.status === 'completed' || a.status === 'ready') return 'ok'
  if (a.status === 'failed' || a.status === 'error') return 'err'
  return 'unverified'
}
function appStatusLabel(a: MergedApplication): string {
  const s = a.status || ''
  if (s === 'completed') return '已部署'
  if (s === 'ready')     return '就绪'
  if (s === 'draft')     return '草稿'
  if (s === 'generating') return '生成中'
  if (s === 'failed')    return '失败'
  if (s === 'error')     return '错误'
  return s || '—'
}

function openApp(a: MergedApplication) {
  // local app → /chat?app_id=N; remote-only → 跳 apps 列表
  if (Number.isFinite(Number(a.id))) {
    router.push({ path: '/chat', query: { app_id: String(a.id) } })
  } else {
    router.push('/apps')
  }
}

// ─── 环境 ────────────────────────────────────────────────────────────────
const envs = ref<PlatformEnv[]>([])
const envLoading = ref(true)
const envError = ref('')

async function loadEnvs() {
  envLoading.value = true
  envError.value = ''
  try {
    const list = await platformEnvApi.list()
    envs.value = list || []
  } catch (e: any) {
    envError.value = e?.response?.data?.detail || e?.message || '加载失败'
    envs.value = []
  } finally {
    envLoading.value = false
  }
}

function envStatusClass(e: PlatformEnv): string {
  return e.status === 'connected' ? 'ok' : (e.status === 'disconnected' ? 'err' : 'unverified')
}
function envStatusLabel(e: PlatformEnv): string {
  if (e.status === 'connected') return '已连接'
  if (e.status === 'disconnected') return '断开'
  return e.status || '未验证'
}

function trimUrl(u: string): string {
  if (!u) return ''
  return u.replace(/^https?:\/\//, '').replace(/\/$/, '')
}

// ─── 跳转 ────────────────────────────────────────────────────────────────
function goAdmin() { router.push('/admin') }
function goAdminUsers() { router.push('/admin/users') }
function goAdminTenants() { router.push('/admin/tenants') }
function goEnvManage() { router.push('/platform-envs') }
function goLanding() { router.push('/landing') }

// ─── stats ───────────────────────────────────────────────────────────────
const appCount = computed(() => apps.value.length)
const envCount = computed(() => envs.value.length)

const SUB_TABS = computed<{ code: SubCode; label: string; count?: number }[]>(() => [
  { code: 'apps', label: '应用', count: apps.value.length },
  { code: 'users', label: '用户', count: undefined },
  { code: 'tenants', label: '租户', count: undefined },
  { code: 'envs', label: '环境', count: envs.value.length },
])

onMounted(() => {
  loadApps()
  loadEnvs()
})
</script>

<style scoped>
.ds-page {
  font-family: var(--font-sans);
  color: var(--text);
  padding: 28px 36px;
  background: var(--bg);
  min-height: 100%;
  overflow-y: auto;
  font-feature-settings: 'cv11', 'ss01';
}

.ds-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 18px;
  padding-bottom: 18px;
  border-bottom: 1px solid var(--line);
}
.ds-head-meta { flex: 1; min-width: 0; }
.ds-title {
  margin: 0 0 8px;
  font-size: 32px;
  font-weight: 600;
  color: var(--text);
  letter-spacing: -0.5px;
  line-height: 1.2;
}
.ds-stats {
  margin: 0;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-3);
  flex-wrap: wrap;
}
.ds-stat-sep { color: var(--text-4); }
.ds-stat-muted { color: var(--text-4); }
.ds-head-actions { display: flex; gap: 8px; flex-shrink: 0; }

.ds-btn {
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
  gap: 5px;
  transition: background 0.12s, border-color 0.12s, color 0.12s;
}
.ds-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.ds-btn-ghost {
  background: var(--surface);
  border-color: var(--line-strong);
  color: var(--text);
}
.ds-btn-ghost:hover:not(:disabled) {
  border-color: var(--brand);
  color: var(--brand);
}
.ds-btn-primary { background: var(--brand); color: #fff; }
.ds-btn-primary:hover:not(:disabled) { background: var(--brand-hover); }
.ds-btn-icon { font-size: 13px; line-height: 1; }

.ds-subnav {
  display: flex;
  gap: 4px;
  margin-bottom: 14px;
  border-bottom: 1px solid var(--line);
}
.ds-subnav-tab {
  height: 36px;
  padding: 0 14px;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-3);
  font-size: 13px;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  transition: color 0.12s, border-color 0.12s;
  margin-bottom: -1px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.ds-subnav-tab:hover { color: var(--text); }
.ds-subnav-tab.active {
  color: var(--brand);
  border-bottom-color: var(--brand);
}
.ds-subnav-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 18px;
  min-width: 18px;
  padding: 0 6px;
  background: var(--surface-2);
  color: var(--text-3);
  border-radius: 9px;
  font-size: 11px;
  font-weight: 600;
  font-family: var(--font-mono);
}
.ds-subnav-tab.active .ds-subnav-count {
  background: var(--brand-soft);
  color: var(--brand);
}

.ds-section { min-height: 200px; }
.ds-state {
  padding: 48px 0;
  text-align: center;
  color: var(--text-3);
  font-size: 13.5px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}
.ds-state-err { color: var(--err); }
.ds-empty {
  padding: 64px 24px;
  text-align: center;
  color: var(--text-3);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}
.ds-empty-icon { font-size: 48px; line-height: 1; }
.ds-empty h3 { margin: 0; font-size: 18px; font-weight: 600; color: var(--text); }
.ds-empty p { margin: 0; font-size: 13.5px; max-width: 460px; }
.ds-empty-hint { font-size: 12px !important; color: var(--text-4); margin-top: 4px; }

.ds-table-wrap {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow: hidden;
  box-shadow: var(--sh-1);
}
.ds-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  table-layout: fixed;
}
.ds-table th {
  text-align: left;
  padding: 11px 14px;
  background: var(--surface-2);
  font-weight: 500;
  color: var(--text-3);
  font-size: 12.5px;
  border-bottom: 1px solid var(--line);
  white-space: nowrap;
}
.ds-table th.num { width: 40px; text-align: center; }
.ds-table th.col-name { width: 200px; }
.ds-table th.col-code { width: 140px; }
.ds-table th.col-source { width: 100px; }
.ds-table th.col-env { width: 110px; }
.ds-table th.col-url { width: 220px; }
.ds-table th.col-tenant { width: 130px; }
.ds-table th.col-user { width: 110px; }
.ds-table th.col-time { width: 100px; }
.ds-table th.col-status { width: 80px; }
.ds-table th.col-default { width: 60px; text-align: center; }
.ds-table th.col-ops { width: 80px; text-align: center; }

.ds-table td {
  padding: 12px 14px;
  border-bottom: 1px solid var(--line);
  color: var(--text);
  vertical-align: middle;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ds-table tr:last-child td { border-bottom: none; }
.ds-table tr:hover td { background: var(--surface-2); }
.ds-table .num { color: var(--text-4); text-align: center; }
.ds-table .col-default { text-align: center; }
.ds-table .col-ops { text-align: center; }
.ds-table .mono {
  font-family: var(--font-mono);
  font-size: 12.5px;
  color: var(--text-2);
}
.ds-table .muted { color: var(--text-3); }

.ds-cell-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}
.ds-cell-desc {
  font-size: 11.5px;
  color: var(--text-4);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ds-empty-cell { color: var(--text-4); font-size: 12px; }

.ds-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 600;
  border-radius: 4px;
  white-space: nowrap;
  letter-spacing: 0.02em;
}
.ds-badge-src {
  background: var(--surface-2);
  color: var(--text-3);
  border: 1px solid var(--line);
}
.ds-badge-primary {
  background: var(--brand-soft);
  color: var(--brand);
}

.ds-status-chip {
  display: inline-block;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
  white-space: nowrap;
}
.ds-status-chip.ok       { background: var(--ok-soft);    color: var(--ok); }
.ds-status-chip.err      { background: var(--err-soft);   color: var(--err); }
.ds-status-chip.unverified { background: var(--warn-soft); color: var(--warn); }

.ds-link-btn {
  background: transparent;
  border: none;
  color: var(--brand);
  font-size: 12.5px;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  padding: 4px 6px;
  border-radius: 4px;
  transition: background 0.12s, color 0.12s;
}
.ds-link-btn:hover:not(:disabled) { background: var(--brand-soft); }
.ds-link-btn:disabled { color: var(--text-4); cursor: not-allowed; }
</style>
