<!-- DatasourcesView.vue — 数据源统一管理 (design-v4 Phase H3, 2026-05-26).

  替换 G3 stub. 复用现有 endpoint, 不新加 backend:
    - DB 连接 → /api/db-connections (dbConnectionApi)
    - aPaaS 环境 → /api/platform-envs (platformEnvApi)
    - API 接入 / 文件源 → P5 占位

  视觉对齐 DataSchemaEditor.vue:
    - 顶部 header (32px title + stats line + 右上 action)
    - sub-tab nav (active 蓝 border-bottom)
    - table (var(--surface) bg + var(--line) border + 12.5px header)
    - 严格 design-v3 token (--brand / --surface / --line / --text*)

  操作 (P3 内可点):
    - DB tab: "管理" link 跳 /db-connections 老页 (编辑/测试/删完整)
    - aPaaS tab: "管理" link 跳 /platform-envs 老页

  不动现有 /db-connections /platform-envs 老页, 这里只读 + 跳走.
-->
<template>
  <main class="ds-page">
    <!-- 顶部 header -->
    <header class="ds-head">
      <div class="ds-head-meta">
        <h1 class="ds-title">数据源</h1>
        <p class="ds-stats">
          <span>{{ dbCount }} 个 DB 连接</span>
          <span class="ds-stat-sep">·</span>
          <span>{{ envCount }} 个 aPaaS 环境</span>
          <span class="ds-stat-sep">·</span>
          <span class="ds-stat-muted">0 个 API 接入</span>
        </p>
      </div>
      <div class="ds-head-actions">
        <button
          class="ds-btn ds-btn-ghost"
          title="用 AI 直接问数据 — 拖入数据源, 让 AI 跑 SQL / 生成报表"
          @click="goQuickDb"
        >
          <span class="ds-btn-icon">✨</span>
          DB 问数 (AI)
        </button>
        <button class="ds-btn ds-btn-primary" @click="goManageDb">
          <span class="ds-btn-icon">+</span>
          新增数据源
        </button>
      </div>
    </header>

    <!-- 4 sub-tab -->
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

    <!-- DB 连接 -->
    <section v-if="subTab === 'db'" class="ds-section">
      <div v-if="dbLoading" class="ds-state">加载中…</div>
      <div v-else-if="dbError" class="ds-state ds-state-err">
        {{ dbError }}
        <button class="ds-btn ds-btn-ghost" @click="loadDb">重试</button>
      </div>
      <div v-else-if="dbConnections.length === 0" class="ds-empty">
        <div class="ds-empty-icon">🗄️</div>
        <h3>暂无 DB 连接</h3>
        <p>添加 MySQL / PostgreSQL / Oracle 等连接, 让 AI 直接读存量数据.</p>
        <button class="ds-btn ds-btn-primary" @click="goManageDb">前往管理</button>
      </div>
      <div v-else class="ds-table-wrap">
        <table class="ds-table">
          <thead>
            <tr>
              <th class="num">#</th>
              <th class="col-name">名称</th>
              <th class="col-type">类型</th>
              <th class="col-host">Host</th>
              <th class="col-port">Port</th>
              <th class="col-db">数据库</th>
              <th class="col-status">状态</th>
              <th class="col-ops">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(c, i) in dbConnections" :key="c.id">
              <td class="num">{{ i + 1 }}</td>
              <td class="col-name">
                <div class="ds-cell-name">{{ c.name }}</div>
                <div v-if="c.description" class="ds-cell-desc">{{ c.description }}</div>
              </td>
              <td class="col-type">
                <span class="ds-badge ds-badge-db mono">{{ c.db_type }}</span>
              </td>
              <td class="col-host mono">{{ c.host }}</td>
              <td class="col-port mono">{{ c.port }}</td>
              <td class="col-db mono">{{ c.database }}</td>
              <td class="col-status">
                <span class="ds-status-chip" :class="dbStatusClass(c)">
                  {{ dbStatusLabel(c) }}
                </span>
              </td>
              <td class="col-ops">
                <button
                  class="ds-link-btn"
                  :disabled="testingDbId === c.id"
                  @click="testDb(c)"
                  title="测试连接"
                >
                  {{ testingDbId === c.id ? '测试中…' : '测试' }}
                </button>
                <button class="ds-link-btn" @click="goManageDb" title="跳转编辑">编辑</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- aPaaS 环境 -->
    <section v-else-if="subTab === 'env'" class="ds-section">
      <div v-if="envLoading" class="ds-state">加载中…</div>
      <div v-else-if="envError" class="ds-state ds-state-err">
        {{ envError }}
        <button class="ds-btn ds-btn-ghost" @click="loadEnv">重试</button>
      </div>
      <div v-else-if="platformEnvs.length === 0" class="ds-empty">
        <div class="ds-empty-icon">🔗</div>
        <h3>暂无 aPaaS 环境</h3>
        <p>添加得帆云环境 (trial / 公司部署), 让 AI 直接读应用 / 发布到 aPaaS.</p>
        <button class="ds-btn ds-btn-primary" @click="goManageEnv">前往管理</button>
      </div>
      <div v-else class="ds-table-wrap">
        <table class="ds-table">
          <thead>
            <tr>
              <th class="num">#</th>
              <th class="col-name">名称 (alias)</th>
              <th class="col-url">URL</th>
              <th class="col-tenant">租户</th>
              <th class="col-user">登录用户</th>
              <th class="col-status">状态</th>
              <th class="col-default">默认</th>
              <th class="col-ops">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(e, i) in platformEnvs" :key="e.id">
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
                <button
                  class="ds-link-btn"
                  :disabled="testingEnvId === e.id"
                  @click="testEnv(e)"
                  title="测试连接"
                >
                  {{ testingEnvId === e.id ? '测试中…' : '测试' }}
                </button>
                <button class="ds-link-btn" @click="goManageEnv" title="跳转管理">管理</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- API 接入 (P5) -->
    <section v-else-if="subTab === 'api'" class="ds-section">
      <div class="ds-empty">
        <div class="ds-empty-icon">🔌</div>
        <h3>API 接入</h3>
        <p>P5 接入 — 接 REST / GraphQL 第三方接口, 让 AI 像查数据表一样调外部 API.</p>
      </div>
    </section>

    <!-- 文件源 (P5) -->
    <section v-else class="ds-section">
      <div class="ds-empty">
        <div class="ds-empty-icon">📄</div>
        <h3>文件源</h3>
        <p>P5 接入 — 接 Excel / CSV / 飞书表格等文件源, 自动同步为可读数据表.</p>
      </div>
    </section>
  </main>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { dbConnectionApi, type DbConnection } from '@/api/dbConnections'
import { platformEnvApi, type PlatformEnv } from '@/api/platformEnv'

type SubCode = 'db' | 'env' | 'api' | 'file'

const router = useRouter()

const subTab = ref<SubCode>('db')

// ─── DB 连接 ────────────────────────────────────────────────────────────────
const dbConnections = ref<DbConnection[]>([])
const dbLoading = ref(true)
const dbError = ref('')
const testingDbId = ref<number | null>(null)

async function loadDb() {
  dbLoading.value = true
  dbError.value = ''
  try {
    const list = await dbConnectionApi.list()
    dbConnections.value = Array.isArray(list) ? list : []
  } catch (e: any) {
    dbError.value = e?.response?.data?.detail || e?.message || '加载失败'
    dbConnections.value = []
  } finally {
    dbLoading.value = false
  }
}

async function testDb(c: DbConnection) {
  testingDbId.value = c.id
  try {
    const res = await dbConnectionApi.test(c.id)
    if (res.ok) {
      ElMessage.success(`连接成功, 发现 ${res.table_count} 张表`)
      c.status = 'active'
      c.table_count = res.table_count
      c.last_tested_at = new Date().toISOString()
    } else {
      ElMessage.error(res.error || '连接失败')
      c.status = 'disconnected'
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '测试失败')
  } finally {
    testingDbId.value = null
  }
}

function dbStatusClass(c: DbConnection): string {
  if (!c.last_tested_at) return 'unverified'
  return c.status === 'active' ? 'ok' : 'err'
}
function dbStatusLabel(c: DbConnection): string {
  if (!c.last_tested_at) return '未验证'
  return c.status === 'active' ? '已连接' : '断开'
}

function goQuickDb() {
  router.push('/quick-db')
}

function goManageDb() {
  router.push('/db-connections')
}

// ─── aPaaS 环境 ─────────────────────────────────────────────────────────────
const platformEnvs = ref<PlatformEnv[]>([])
const envLoading = ref(true)
const envError = ref('')
const testingEnvId = ref<number | null>(null)

async function loadEnv() {
  envLoading.value = true
  envError.value = ''
  try {
    const list = await platformEnvApi.list()
    platformEnvs.value = Array.isArray(list) ? list : []
  } catch (e: any) {
    envError.value = e?.response?.data?.detail || e?.message || '加载失败'
    platformEnvs.value = []
  } finally {
    envLoading.value = false
  }
}

async function testEnv(e: PlatformEnv) {
  testingEnvId.value = e.id
  try {
    const res = await platformEnvApi.test(e.id)
    if (res.ok) {
      ElMessage.success(`连接成功 (${res.status})`)
      e.status = res.status
    } else {
      ElMessage.error(res.error || '连接失败')
      e.status = res.status || 'disconnected'
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || err?.message || '测试失败')
  } finally {
    testingEnvId.value = null
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

function goManageEnv() {
  router.push('/platform-envs')
}

// ─── 顶部统计 + sub-tab count ──────────────────────────────────────────────
const dbCount = computed(() => dbConnections.value.length)
const envCount = computed(() => platformEnvs.value.length)

const SUB_TABS = computed<{ code: SubCode; label: string; count?: number }[]>(() => [
  { code: 'db', label: 'DB 连接', count: dbConnections.value.length },
  { code: 'env', label: 'aPaaS 环境', count: platformEnvs.value.length },
  { code: 'api', label: 'API 接入', count: undefined },
  { code: 'file', label: '文件源', count: undefined },
])

onMounted(() => {
  loadDb()
  loadEnv()
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

/* ─── 表头 ─────────────────────────────────────────────────────────────── */
.ds-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 18px;
  padding-bottom: 18px;
  border-bottom: 1px solid var(--line);
}
.ds-head-meta {
  flex: 1;
  min-width: 0;
}
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
.ds-head-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

/* ─── btn ─────────────────────────────────────────────────────────────── */
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
.ds-btn-primary {
  background: var(--brand);
  color: #fff;
}
.ds-btn-primary:hover:not(:disabled) {
  background: var(--brand-hover);
}
.ds-btn-icon { font-size: 13px; line-height: 1; }

/* ─── sub-tab nav ──────────────────────────────────────────────────────── */
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

/* ─── section ──────────────────────────────────────────────────────────── */
.ds-section {
  min-height: 200px;
}
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
.ds-empty h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--text);
}
.ds-empty p {
  margin: 0;
  font-size: 13.5px;
  max-width: 460px;
}

/* ─── table ────────────────────────────────────────────────────────────── */
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
.ds-table th.col-name { width: 180px; }
.ds-table th.col-type { width: 110px; }
.ds-table th.col-host { width: 160px; }
.ds-table th.col-port { width: 70px; }
.ds-table th.col-db { width: 140px; }
.ds-table th.col-url { width: 240px; }
.ds-table th.col-tenant { width: 140px; }
.ds-table th.col-user { width: 120px; }
.ds-table th.col-status { width: 90px; }
.ds-table th.col-default { width: 60px; text-align: center; }
.ds-table th.col-ops { width: 130px; text-align: center; }

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
  white-space: nowrap;
}

.ds-empty-cell {
  color: var(--text-4);
  font-size: 12px;
}

/* ─── badge ────────────────────────────────────────────────────────────── */
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
.ds-badge-db {
  background: var(--brand-soft);
  color: var(--brand);
}
.ds-badge-primary {
  background: var(--brand-soft);
  color: var(--brand);
}

/* ─── status chip ──────────────────────────────────────────────────────── */
.ds-status-chip {
  display: inline-block;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
  white-space: nowrap;
}
.ds-status-chip.ok {
  background: var(--ok-soft);
  color: var(--ok);
}
.ds-status-chip.err {
  background: var(--err-soft);
  color: var(--err);
}
.ds-status-chip.unverified {
  background: var(--warn-soft);
  color: var(--warn);
}

/* ─── link-style 操作 btn ──────────────────────────────────────────────── */
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
.ds-link-btn:hover:not(:disabled) {
  background: var(--brand-soft);
}
.ds-link-btn:disabled {
  color: var(--text-4);
  cursor: not-allowed;
}
.ds-link-btn + .ds-link-btn {
  margin-left: 4px;
}
</style>
