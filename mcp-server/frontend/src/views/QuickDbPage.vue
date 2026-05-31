<!-- frontend/src/views/QuickDbPage.vue
  「DB 问数」快速接入 wizard — 4 步把一个数据库 → 完整低代码应用：
    1. DB 连接：host/port/db/user/pass + 类型 + [测试连接] → 拿到全表清单
    2. 表多选：勾选要接入的表（智能默认跳过 SPRING_* / flyway_* 等框架表）
    3. 业务描述：一句话告诉 AI 这是什么系统（驱动字段语义推断）+ 选模板风格
    4. 生成：实时进度条 + 完成后跳应用页

  当前阶段：UI 骨架 + 后端 stub。真实 endpoint 见 step4 注释里的 TODO 清单。
  复用：ShellTopBar / WorkbenchShell / RailSidebar 全 layout；Element Plus 表单组件；platformEnvApi 模式（凭证保存）。
-->
<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import ShellTopBar from '@/components/v2/ShellTopBar.vue'
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import { quickDbApi, type TableHealth } from '@/api/quickDb'
import { usePreviewStore } from '@/stores/preview'

// Agent 2 创建的 dbConnections API — 用懒加载 + try/catch 包裹避免 module 还没就位时崩。
// 即便 import 失败，"新建连接"主流程仍可用，只是切到"已有连接"会拿不到列表。
type DbConnection = {
  id: number
  name: string
  db_type: string
  host: string
  port: number
  database: string
  username: string
  created_at?: string
}
type DbConnectionApi = {
  list: () => Promise<DbConnection[]>
  create: (payload: any) => Promise<DbConnection>
  tables: (id: number) => Promise<{ tables: Array<{ name: string; fields: number }>; classifications?: any }>
}
let dbConnectionApi: DbConnectionApi | null = null
async function ensureDbConnectionApi(): Promise<DbConnectionApi | null> {
  if (dbConnectionApi) return dbConnectionApi
  try {
    const mod: any = await import(/* @vite-ignore */ '@/api/dbConnections')
    dbConnectionApi = mod.dbConnectionApi ?? mod.default ?? null
  } catch { dbConnectionApi = null }
  return dbConnectionApi
}

const route = useRoute()
const router = useRouter()
const previewStore = usePreviewStore()

// 4 步 wizard
type Step = 1 | 2 | 3 | 4
const step = ref<Step>(1)

// Step 1: DB 连接 — 大小写跟 aPaaS UI dropdown 对齐
type DbType = 'MYSQL' | 'PostgreSQL' | 'SQLServer' | 'ORACLE' | 'DAMENG' | 'KingBase'
const dbForm = ref<{
  type: DbType
  host: string
  port: string
  database: string
  username: string
  password: string
  alias: string
}>({
  type: 'MYSQL',
  host: '',
  port: '3306',
  database: '',
  username: '',
  password: '',
  alias: '',
})
const testing = ref(false)
const testError = ref('')

const PORT_DEFAULTS: Record<DbType, string> = {
  MYSQL: '3306', PostgreSQL: '5432', SQLServer: '1433', ORACLE: '1521', DAMENG: '5236', KingBase: '54321',
}
function onTypeChange(t: DbType) {
  dbForm.value.type = t
  // 只在 port 还是默认值时跟随类型切换
  if (Object.values(PORT_DEFAULTS).includes(dbForm.value.port)) {
    dbForm.value.port = PORT_DEFAULTS[t]
  }
}

const canTest = computed(() => {
  // 已有连接模式：只要选了一条就能往下
  if (sourceMode.value === 'existing') return selectedConnectionId.value !== null
  // 新建模式：6 字段都得有
  return !!dbForm.value.host && !!dbForm.value.port && !!dbForm.value.database
    && !!dbForm.value.username && !!dbForm.value.password
})

// Step 1 顶部切换：新建连接 vs 选择已有连接（从"数据库连接管理"复用）
type SourceMode = 'new' | 'existing'
const sourceMode = ref<SourceMode>('new')
const existingConnections = ref<DbConnection[]>([])
const selectedConnectionId = ref<number | null>(null)
const loadingExisting = ref(false)
// 新建模式下勾上 → wizard 跑前先把这个连接存到"数据库连接"以便复用
const saveAsNew = ref(true)

async function loadExistingConnections() {
  const api = await ensureDbConnectionApi()
  if (!api) { existingConnections.value = []; return }
  loadingExisting.value = true
  try {
    existingConnections.value = await api.list()
  } catch {
    existingConnections.value = []
  } finally {
    loadingExisting.value = false
  }
}

watch(sourceMode, (m) => {
  if (m === 'existing' && existingConnections.value.length === 0) {
    void loadExistingConnections()
  }
  // 切换模式时清空连接 test 错误，避免错误信息错配
  testError.value = ''
})

// 选已有连接时 prefill 表单 — password 留空（后端用已加密的密码），placeholder 提示
function onSelectExisting(id: number) {
  selectedConnectionId.value = id
  const c = existingConnections.value.find(x => x.id === id)
  if (!c) return
  dbForm.value = {
    type: (c.db_type as DbType) || 'MYSQL',
    host: c.host,
    port: String(c.port),
    database: c.database,
    username: c.username,
    password: '',  // 不 prefill，后端用 saved password
    alias: c.name,
  }
}

// Step 2: 表清单。health/badge/reason 来自后端 table_classifier；前端默认勾
// green/yellow，不勾 red/skip。这样大部分用户开箱即能跑，框架/审计表也不会
// 误进 SPEC。
interface TableInfo {
  name: string
  fields: number
  suggestSkip: boolean   // 兜底：分类器没返回时用前端 prefix 规则
  selected: boolean
  health?: TableHealth
  badge?: string
  reason?: string
}
const tables = ref<TableInfo[]>([])
const tableSearch = ref('')

// fallback：分类器缺失时按前端 prefix 规则降级判断"建议跳过"。
const FRAMEWORK_PREFIXES = ['SPRING_', 'flyway_', 'qrtz_', 'shedlock_', 'act_', 'oauth_']
function isFrameworkTable(name: string) {
  return FRAMEWORK_PREFIXES.some(p => name.toLowerCase().startsWith(p.toLowerCase()))
}

const filteredTables = computed(() => {
  const q = tableSearch.value.trim().toLowerCase()
  if (!q) return tables.value
  return tables.value.filter(t => t.name.toLowerCase().includes(q))
})
const selectedCount = computed(() => tables.value.filter(t => t.selected).length)

function toggleAllVisible(checked: boolean) {
  filteredTables.value.forEach(t => { t.selected = checked })
}

// Step 3: 业务描述 + 风格
const businessHint = ref<string>(typeof route.query.hint === 'string' ? route.query.hint : '')
type StyleId = 'oa' | 'dashboard' | 'mobile'
const style = ref<StyleId>('oa')
const STYLES: { id: StyleId; label: string; desc: string }[] = [
  { id: 'oa',        label: 'OA 风',        desc: '侧边树菜单 + 主表单页，给后台办公场景' },
  { id: 'dashboard', label: 'Dashboard 风', desc: '卡片仪表盘 + 列表，给数据展示场景' },
  { id: 'mobile',    label: '移动友好',     desc: '响应式简化布局，手机平板都好用' },
]

// Step 4: 进度日志。现在只展示 build-spec 调用 + 跳转过程，不再有长流程。
interface ProgressEvent {
  ts: number
  level: 'info' | 'ok' | 'warn' | 'err'
  text: string
}
const progress = ref<ProgressEvent[]>([])
const generating = ref(false)

function pushProgress(level: ProgressEvent['level'], text: string) {
  progress.value.push({ ts: Date.now(), level, text })
}

// ─── 网络层 ────────────────────────────────────────────────────────
// 共享：把后端 tables + classifications 转成前端 TableInfo
function applyTablesPayload(
  payload: { name: string; fields: number }[],
  classifications?: Record<string, { health: TableHealth; badge?: string; reason?: string }>
) {
  const cls = classifications || {}
  tables.value = payload.map(t => {
    const c = cls[t.name]
    if (c) {
      return {
        name: t.name,
        fields: t.fields,
        suggestSkip: c.health === 'skip',
        selected: c.health === 'green' || c.health === 'yellow',
        health: c.health,
        badge: c.badge,
        reason: c.reason,
      }
    }
    return {
      name: t.name,
      fields: t.fields,
      suggestSkip: isFrameworkTable(t.name),
      selected: !isFrameworkTable(t.name),
    }
  })
}

async function testConnection(): Promise<void> {
  testing.value = true
  testError.value = ''
  try {
    // 分支 A：已有连接 → 拉表清单（后端用已加密密码解密后测连接）
    if (sourceMode.value === 'existing' && selectedConnectionId.value !== null) {
      const api = await ensureDbConnectionApi()
      if (!api) {
        testError.value = '数据库连接管理 API 还没就位，请稍后再试或切换"新建连接"模式'
        return
      }
      const resp = await api.tables(selectedConnectionId.value)
      if (!resp.tables || !resp.tables.length) {
        testError.value = '连上了但没找到任何业务表（database 是空的？）'
        return
      }
      applyTablesPayload(resp.tables, resp.classifications)
      step.value = 2
      return
    }
    // 分支 B：新建连接 → 沿用现有 quickDbApi.testConnection 逻辑
    const resp = await quickDbApi.testConnection({
      type: dbForm.value.type,
      host: dbForm.value.host.trim(),
      port: Number(dbForm.value.port) || 0,
      database: dbForm.value.database.trim(),
      username: dbForm.value.username.trim(),
      password: dbForm.value.password,
      alias: dbForm.value.alias.trim() || undefined,
    })
    if (!resp.ok) {
      testError.value = resp.error || '连接失败（后端未返回错误信息）'
      return
    }
    if (!resp.tables.length) {
      testError.value = '连上了但没找到任何业务表（database 是空的？）'
      return
    }
    applyTablesPayload(resp.tables, resp.classifications)
    step.value = 2
  } catch (e: any) {
    testError.value = e?.response?.data?.detail || e?.message || String(e)
  } finally {
    testing.value = false
  }
}

async function startGeneration(): Promise<void> {
  // Step 4 现在的流程：调一次 build-spec 拿 markdown → 包成 File 塞
  // previewStore.pendingFile → 跳 /chat → ChatPage 的 uploadDocFile 接管，
  // 后续走主线 generator_v2 建应用。这条路跟"从 Landing 上传 .md"完全一致，
  // 不再在 quick-db wizard 里跑自实现 orchestrator。
  generating.value = true
  progress.value = []
  const picked = tables.value.filter(t => t.selected).map(t => t.name)
  try {
    // 新建模式 + 勾了"同时保存到数据库连接"→ wizard 跑前先存一份，失败不阻塞
    if (sourceMode.value === 'new' && saveAsNew.value) {
      const api = await ensureDbConnectionApi()
      if (api) {
        try {
          pushProgress('info', '同步保存连接到「数据库连接」…')
          await api.create({
            name: dbForm.value.alias.trim() || `${dbForm.value.type}@${dbForm.value.host}`,
            db_type: dbForm.value.type,
            host: dbForm.value.host.trim(),
            port: Number(dbForm.value.port) || 0,
            database: dbForm.value.database.trim(),
            username: dbForm.value.username.trim(),
            password: dbForm.value.password,
          })
          pushProgress('ok', '✓ 已保存到「数据库连接」')
        } catch (e: any) {
          pushProgress('warn', '保存连接失败（不影响后续生成）：' + (e?.response?.data?.detail || e?.message || String(e)))
        }
      }
    }
    pushProgress('info', `生成 SPEC 文档中…（${picked.length} 张表）`)
    // 二分支：已有连接模式传 connection_id（后端解密保存的密码），避免前端 password 为空
    // 新建模式传 db 凭证（用户刚填的）
    const buildReq: any = {
      tables: picked,
      hint: businessHint.value.trim(),
      style: style.value,
    }
    if (sourceMode.value === 'existing' && selectedConnectionId.value !== null) {
      buildReq.connection_id = selectedConnectionId.value
    } else {
      buildReq.db = {
        type: dbForm.value.type,
        host: dbForm.value.host.trim(),
        port: Number(dbForm.value.port) || 0,
        database: dbForm.value.database.trim(),
        username: dbForm.value.username.trim(),
        password: dbForm.value.password,
        alias: dbForm.value.alias.trim() || undefined,
      }
    }
    const resp = await quickDbApi.buildSpec(buildReq)
    if (!resp.ok || !resp.spec_md) {
      pushProgress('err', '生成失败：' + (resp.error || '后端未返回 spec_md'))
      return
    }
    pushProgress('ok', `✓ SPEC 已生成（${resp.spec_md.length} 字符，app_code=${resp.app_code}）`)
    pushProgress('ok', '✓ 准备跳转到 SPEC 编辑器…')

    // 把 spec_md 包成 File，复用 Landing 的"上传 .md"流程：
    //   ChatPage onMounted 看到 previewStore.pendingFile → 调 uploadDocFile
    const file = new File([resp.spec_md], `${resp.app_code}.md`, { type: 'text/markdown' })
    previewStore.pendingFile = file
    setTimeout(() => {
      router.push({ path: '/chat', query: { from: 'upload' } })
    }, 800)
  } catch (e: any) {
    pushProgress('err', '生成失败：' + (e?.response?.data?.detail || e?.message || String(e)))
  } finally {
    generating.value = false
  }
}

// 进入下一步前的校验
function next() {
  if (step.value === 1) {
    if (!canTest.value) { ElMessage.warning('请填完整 DB 连接信息'); return }
    void testConnection()
  } else if (step.value === 2) {
    if (selectedCount.value === 0) { ElMessage.warning('至少勾一张表'); return }
    step.value = 3
  } else if (step.value === 3) {
    step.value = 4
    void startGeneration()
  }
}
function prev() {
  if (step.value === 1) router.push('/')
  else step.value = (step.value - 1) as Step
}

const STEPS = [
  { n: 1, label: 'DB 连接' },
  { n: 2, label: '选择表' },
  { n: 3, label: '业务描述' },
  { n: 4, label: '生成应用' },
] as const

onMounted(() => {
  if (businessHint.value) {
    // 来自 Landing 已经填了 hint，但仍从 step 1 起步
  }
})
</script>

<template>
  <WorkbenchShell>
    <ShellTopBar />
    <div class="page quick-db">
      <div class="page-pad">
        <div class="hero">
          <div class="db-badge">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/><path d="M3 12a9 3 0 0 0 18 0"/></svg>
            <span>DB 问数</span>
          </div>
          <h1 class="hero-title">把数据库交给 AI，<span class="hl">5 分钟变成可用系统</span></h1>
          <div class="hero-sub">填一次连接 · 勾要接入的表 · 一句话描述业务 · 30 秒内拿到完整 CRUD + AI 问数</div>
        </div>

        <!-- Step indicator -->
        <div class="steps">
          <template v-for="(s, i) in STEPS" :key="s.n">
            <div class="step-node" :class="{ active: step === s.n, done: step > s.n }">
              <div class="step-num">{{ s.n }}</div>
              <div class="step-label">{{ s.label }}</div>
            </div>
            <div v-if="i < STEPS.length - 1" class="step-arrow" :class="{ done: step > s.n }">→</div>
          </template>
        </div>

        <!-- Card body -->
        <div class="card">
          <!-- Step 1: DB 连接 -->
          <div v-if="step === 1" class="step-body">
            <!-- 顶部 segmented：新建连接 / 选择已有连接 -->
            <div class="source-mode-row">
              <button
                class="source-pill"
                :class="{ active: sourceMode === 'new' }"
                @click="sourceMode = 'new'"
                type="button"
              >新建连接</button>
              <button
                class="source-pill"
                :class="{ active: sourceMode === 'existing' }"
                @click="sourceMode = 'existing'"
                type="button"
              >选择已有连接</button>
            </div>

            <!-- 已有连接模式：dropdown 选择 + 自动 prefill -->
            <div v-if="sourceMode === 'existing'" class="form-row">
              <label>从「数据库连接」选择</label>
              <el-select
                v-model="selectedConnectionId"
                :placeholder="loadingExisting ? '加载中…' : (existingConnections.length ? '请选择一个已保存的连接' : '还没有保存的连接')"
                :loading="loadingExisting"
                :disabled="!existingConnections.length && !loadingExisting"
                style="width: 100%"
                @change="(id: number) => onSelectExisting(id)"
              >
                <el-option
                  v-for="c in existingConnections"
                  :key="c.id"
                  :label="`${c.name} — ${c.db_type}@${c.host}:${c.port}/${c.database}`"
                  :value="c.id"
                />
              </el-select>
              <div v-if="!existingConnections.length && !loadingExisting" class="hint">
                还没有保存的连接 — 切到「新建连接」做一次后，勾上"同时保存"即可复用。
                或进
                <a class="link-inline" href="javascript:void(0)" @click="router.push('/db-connections')">数据库连接管理</a>
                单独添加。
              </div>
            </div>

            <!-- 共享：DB 类型 + 6 字段表单 — 新建模式可编辑；已有模式只读展示，密码占位为"使用已保存的密码" -->
            <div class="form-row">
              <label>数据库类型</label>
              <div class="db-types">
                <button v-for="t in (['MYSQL','PostgreSQL','SQLServer','ORACLE','DAMENG','KingBase'] as DbType[])" :key="t"
                  class="db-type-pill" :class="{ active: dbForm.type === t }" @click="onTypeChange(t)"
                  :disabled="sourceMode === 'existing'">
                  {{ t }}
                </button>
              </div>
            </div>
            <div class="form-grid">
              <div class="form-cell"><label>主机</label><input v-model="dbForm.host" type="text" placeholder="例：10.0.0.5 / db.internal" :readonly="sourceMode === 'existing'" /></div>
              <div class="form-cell"><label>端口</label><input v-model="dbForm.port" type="text" :placeholder="PORT_DEFAULTS[dbForm.type]" :readonly="sourceMode === 'existing'" /></div>
              <div class="form-cell"><label>数据库名</label><input v-model="dbForm.database" type="text" placeholder="例：erp_finance" :readonly="sourceMode === 'existing'" /></div>
              <div class="form-cell"><label>别名（可选）</label><input v-model="dbForm.alias" type="text" placeholder="给这个连接起个名字" :readonly="sourceMode === 'existing'" /></div>
              <div class="form-cell"><label>用户名</label><input v-model="dbForm.username" type="text" autocomplete="off" :readonly="sourceMode === 'existing'" /></div>
              <div class="form-cell">
                <label>密码</label>
                <input v-model="dbForm.password" type="password" autocomplete="new-password"
                  :placeholder="sourceMode === 'existing' ? '使用已保存的密码' : ''"
                  :readonly="sourceMode === 'existing'" />
              </div>
            </div>

            <!-- 新建模式专属：勾上 → wizard 跑前先存进「数据库连接」 -->
            <label v-if="sourceMode === 'new'" class="save-as-new">
              <input type="checkbox" v-model="saveAsNew" />
              <span>同时保存到「数据库连接」以便复用</span>
            </label>

            <div v-if="testError" class="err-msg">{{ testError }}</div>
            <div class="hint">所有凭证只用于建模阶段，写入 aPaaS 数据源后通过得帆云权限体系隔离访问。</div>
          </div>

          <!-- Step 2: 表多选 -->
          <div v-else-if="step === 2" class="step-body">
            <div class="row-between">
              <div class="muted">共发现 <b>{{ tables.length }}</b> 张表，已勾选 <b>{{ selectedCount }}</b> 张</div>
              <input class="search" v-model="tableSearch" type="text" placeholder="搜表名…" />
            </div>
            <div class="bulk-actions">
              <button class="link-btn" @click="toggleAllVisible(true)">全选当前</button>
              <button class="link-btn" @click="toggleAllVisible(false)">全不选</button>
              <span class="muted">💡 框架表（SPRING_* / flyway_* 等）已默认跳过</span>
            </div>
            <div class="table-list">
              <label
                v-for="t in filteredTables"
                :key="t.name"
                class="table-row"
                :class="['health-' + (t.health || (t.suggestSkip ? 'skip' : 'green')), { skip: t.suggestSkip }]"
              >
                <input type="checkbox" v-model="t.selected" />
                <span class="table-name">{{ t.name }}</span>
                <span class="table-meta">{{ t.fields }} 字段</span>
                <span v-if="t.badge" class="health-tag" :title="t.reason || ''">{{ t.badge }}</span>
                <span v-else-if="t.suggestSkip" class="health-tag">建议跳过</span>
              </label>
              <div v-if="!filteredTables.length" class="empty">
                <EmptyState
                  :variant="tableSearch ? 'filtered' : 'first'"
                  :title="tableSearch ? '没有匹配的表' : '这个库里没有可用的业务表'"
                  :desc="tableSearch
                    ? `没找到 “${tableSearch}”。换个关键词或清空搜索看全部。`
                    : '所有表都被分类为框架表 / 审计表 / 无主键 / 关联表。换个 schema 试试，或者直接在对话里描述。'"
                >
                  <template #icon>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                  </template>
                  <template v-if="tableSearch" #cta>
                    <el-button @click="tableSearch = ''">清空搜索</el-button>
                  </template>
                </EmptyState>
              </div>
            </div>
          </div>

          <!-- Step 3: 业务描述 + 风格 -->
          <div v-else-if="step === 3" class="step-body">
            <div class="form-row">
              <label>一句话描述这是什么系统 <span class="muted">（AI 据此推断字段语义、优先级、表间关系）</span></label>
              <textarea v-model="businessHint" rows="3" placeholder="例：这是我们公司 ERP 财务模块的只读副本，主要给财务团队查账+做月报…" />
            </div>
            <div class="form-row">
              <label>选模板风格</label>
              <div class="styles">
                <button v-for="s in STYLES" :key="s.id" class="style-card" :class="{ active: style === s.id }" @click="style = s.id">
                  <div class="style-label">{{ s.label }}</div>
                  <div class="style-desc">{{ s.desc }}</div>
                </button>
              </div>
            </div>
          </div>

          <!-- Step 4: 生成 SPEC + 跳转 -->
          <div v-else-if="step === 4" class="step-body">
            <div v-if="generating" class="gen-status">
              <div class="spinner" />
              <span>生成 SPEC 文档…</span>
            </div>
            <div class="progress-log">
              <div v-for="(e, i) in progress" :key="i" class="log-line" :class="'lv-' + e.level">
                {{ e.text }}
              </div>
              <div v-if="!progress.length" class="muted">准备开始…</div>
            </div>
          </div>
        </div>

        <!-- Footer nav -->
        <div class="foot-nav">
          <button class="btn btn-ghost" @click="prev" :disabled="generating">{{ step === 1 ? '返回首页' : '上一步' }}</button>
          <div class="step-meta">{{ step }} / 4</div>
          <button v-if="step < 4" class="btn btn-primary" :disabled="testing || (step === 1 && !canTest)" @click="next">
            {{ step === 1 ? (testing ? '测试中…' : '测试连接 →') : step === 3 ? '生成 SPEC →' : '下一步 →' }}
          </button>
          <span v-else class="step-meta">{{ generating ? '生成中…' : 'SPEC 已生成，跳转中…' }}</span>
        </div>
      </div>
    </div>
  </WorkbenchShell>
</template>

<style scoped>
/* v3 redesign · 2026-05-20 — visual refresh only, template/script untouched.
   Preserved (don't change):
     - All selector names + 4-step wizard structure (step 1/2/3/4)
     - source-mode segmented (.source-mode-row / .source-pill) for new|existing
     - 6 DB type pills (.db-type-pill) — MYSQL/PostgreSQL/SQLServer/ORACLE/DAMENG/KingBase
     - 7-rule health badge classes (.health-green / .health-yellow / .health-red / + skip)
     - readonly field visual degradation for existing-connection mode
     - .lv-info / .lv-ok / .lv-warn / .lv-err progress log color rail
   Refreshed:
     - Amber/emerald accent → brand (--brand / --brand-soft) for active states.
       Status states still use ok/warn/err per their semantics.
     - Borders: --border → --line (intent clarity; same value via v2→v3 alias)
     - Radius normalised to --r-2 (6) / --r-3 (8) / --r-4 (12) per v3 token system
     - Step bar (per spec 06.2 規範): active=brand-soft, done=ok-soft, pending=neutral
       — "不要 4 色花，按步骤推进色"
     - Shadows via --sh-2 (card) + --sh-brand (primary hover)
     - transition unified to 0.14s var(--ease)
     - mono font uses --font-mono (Inter alias)
*/

.quick-db {
  overflow-y: auto;
  height: 100%;
  background: var(--bg-app, var(--bg));
  flex: 1;
  min-height: 0;
}
.page-pad { padding: 36px 32px 80px; max-width: 880px; margin: 0 auto; }

/* ── Hero ─────────────────────────────────────────────────── */
.hero { text-align: center; margin-bottom: 28px; }
.db-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 30px;
  padding: 0 12px;
  border-radius: var(--r-full, 999px);
  background: var(--brand-soft);
  color: var(--brand);
  font-weight: var(--fw-semibold, 600);
  font-size: 12.5px;
  border: 1px solid var(--brand-ring);
  margin-bottom: 12px;
}
.hero-title {
  font-size: 28px;
  font-weight: var(--fw-bold, 700);
  color: var(--text);
  letter-spacing: -0.02em;
  line-height: 1.2;
  margin: 0 0 10px;
}
.hero-title .hl { color: var(--brand); }
.hero-sub { font-size: 13px; color: var(--text-2); }

/* ── Step indicator (per spec 06.2 規範 "按步骤推进色") ───── */
.steps {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  margin-bottom: 24px;
}
.step-node {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  border-radius: var(--r-full, 999px);
  background: var(--surface);
  border: 1px solid var(--line);
  color: var(--text-3);
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.step-node.active {
  background: var(--brand-soft);
  color: var(--brand);
  border-color: var(--brand);
}
.step-node.done {
  background: var(--ok-soft);
  color: var(--ok);
  border-color: var(--ok);
}
.step-num {
  width: 22px;
  height: 22px;
  border-radius: var(--r-full, 999px);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: currentColor;
  color: var(--surface);
  font-size: 11px;
  font-weight: var(--fw-bold, 700);
  font-family: var(--font-mono);
}
.step-label { font-size: 12.5px; font-weight: var(--fw-medium, 500); }
.step-arrow { color: var(--text-4); font-size: 14px; }
.step-arrow.done { color: var(--ok); }

/* ── Card ─────────────────────────────────────────────────── */
.card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-4, 12px);
  padding: 28px;
  box-shadow: var(--sh-2);
  margin-bottom: 18px;
}
.step-body { min-height: 280px; }

/* ── Forms ────────────────────────────────────────────────── */
.form-row { margin-bottom: 18px; }
.form-row > label {
  display: block;
  font-size: 12px;
  font-weight: var(--fw-semibold, 600);
  color: var(--text-2);
  margin-bottom: 8px;
}
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px 16px; }
.form-cell { display: flex; flex-direction: column; gap: 6px; }
.form-cell label {
  font-size: 12px;
  color: var(--text-2);
  font-weight: var(--fw-semibold, 600);
}
.form-cell input,
.form-row textarea {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-2, 6px);
  background: var(--surface);
  color: var(--text);
  font-size: 13px;
  font-family: inherit;
  outline: none;
  transition: border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              box-shadow 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.form-cell input:hover:not([readonly]),
.form-row textarea:hover {
  border-color: var(--line-strong);
}
.form-cell input:focus,
.form-row textarea:focus {
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-ring);
}
.form-row textarea { resize: vertical; min-height: 80px; }

/* 6 DB type pills — one tone per spec 06.1 規範 (mono font + brand-soft active) */
.db-types { display: flex; gap: 8px; flex-wrap: wrap; }
.db-type-pill {
  padding: 6px 12px;
  border-radius: var(--r-2, 6px);
  border: 1px solid var(--line);
  background: var(--surface);
  cursor: pointer;
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: var(--fw-medium, 500);
  color: var(--text-2);
  letter-spacing: 0.01em;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.db-type-pill:hover:not(:disabled):not(.active) {
  background: var(--surface-2);
  border-color: var(--line-strong);
  color: var(--text);
}
.db-type-pill.active {
  background: var(--brand-soft);
  color: var(--brand);
  border-color: var(--brand);
}
.db-type-pill:disabled { opacity: 0.5; cursor: not-allowed; }

/* Step 1 顶部 segmented 切换：新建 / 选已有 */
.source-mode-row {
  display: inline-flex;
  padding: 3px;
  border-radius: var(--r-3, 8px);
  background: var(--surface-2);
  border: 1px solid var(--line);
  margin-bottom: 18px;
}
.source-pill {
  padding: 7px 18px;
  border-radius: var(--r-2, 6px);
  border: none;
  background: transparent;
  font-size: 12.5px;
  font-weight: var(--fw-medium, 500);
  color: var(--text-2);
  cursor: pointer;
  font-family: inherit;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              box-shadow 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.source-pill.active {
  background: var(--surface);
  color: var(--brand);
  font-weight: var(--fw-semibold, 600);
  box-shadow: var(--sh-1);
}
.source-pill:hover:not(.active) { color: var(--text); }

/* readonly 字段视觉降级 */
.form-cell input[readonly] {
  background: var(--surface-2);
  color: var(--text-3);
  cursor: default;
}

/* 新建模式下"同时保存"checkbox */
.save-as-new {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 14px;
  font-size: 12.5px;
  color: var(--text-2);
  cursor: pointer;
  user-select: none;
}
.save-as-new input[type="checkbox"] {
  cursor: pointer;
  accent-color: var(--brand);
}

.link-inline {
  color: var(--brand);
  text-decoration: underline;
  text-underline-offset: 2px;
  cursor: pointer;
}
.link-inline:hover { color: var(--brand-hover); }

.hint { font-size: 12px; color: var(--text-3); margin-top: 12px; line-height: 1.5; }
.err-msg {
  font-size: 12.5px;
  color: var(--err);
  background: var(--err-soft);
  padding: 8px 12px;
  border-radius: var(--r-2, 6px);
  margin-top: 12px;
  border: 1px solid color-mix(in srgb, var(--err) 18%, transparent);
}
.muted { color: var(--text-3); font-size: 12.5px; }

/* ── Step 2 — table picker ──────────────────────────────── */
.row-between {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.search {
  padding: 6px 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-2, 6px);
  background: var(--surface);
  color: var(--text);
  font-size: 12.5px;
  font-family: inherit;
  outline: none;
  width: 200px;
  transition: border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              box-shadow 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.search:focus {
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-ring);
}
.bulk-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}
.link-btn {
  background: none;
  border: none;
  color: var(--brand);
  font-size: 12.5px;
  font-weight: var(--fw-medium, 500);
  cursor: pointer;
  padding: 0;
  font-family: inherit;
}
.link-btn:hover { text-decoration: underline; color: var(--brand-hover); }

.table-list {
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  max-height: 360px;
  overflow-y: auto;
  background: var(--surface);
}
.table-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--line);
  cursor: pointer;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.table-row:last-child { border-bottom: none; }
.table-row:hover { background: var(--surface-2); }
.table-row input[type="checkbox"] { accent-color: var(--brand); }
.table-row.skip { opacity: 0.55; }
.table-row.health-red { opacity: 0.78; }
.table-name {
  font-family: var(--font-mono);
  font-size: 12.5px;
  flex: 1;
  color: var(--text);
  font-weight: var(--fw-medium, 500);
}
.table-meta {
  font-size: 11.5px;
  color: var(--text-3);
  font-family: var(--font-mono);
}

/* 7-class health badge — preserved class names + classification logic.
   Defaults to neutral (skip/framework); 4 status mappings override. */
.health-tag {
  display: inline-flex;
  align-items: center;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: var(--r-1, 4px);
  background: var(--surface-3);
  color: var(--text-3);
  font-weight: var(--fw-semibold, 600);
}
.table-row.health-green .health-tag { background: var(--ok-soft);   color: var(--ok); }
.table-row.health-yellow .health-tag { background: var(--warn-soft); color: var(--warn); }
.table-row.health-red .health-tag    { background: var(--err-soft);  color: var(--err); }
/* health-skip + suggestSkip fallback inherit the neutral default above */

.empty {
  padding: 24px;
  text-align: center;
  color: var(--text-3);
  font-size: 12.5px;
}

/* ── Step 3 — business hint + style picker ───────────────── */
.styles {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}
.style-card {
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  background: var(--surface);
  cursor: pointer;
  text-align: left;
  font-family: inherit;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              box-shadow 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.style-card:hover { border-color: var(--line-strong); background: var(--surface-2); }
.style-card.active {
  border-color: var(--brand);
  background: var(--brand-soft);
  box-shadow: 0 0 0 3px var(--brand-ring);
}
.style-label {
  font-size: 13px;
  font-weight: var(--fw-semibold, 600);
  color: var(--text);
  margin-bottom: 4px;
}
.style-card.active .style-label { color: var(--brand); }
.style-desc { font-size: 11.5px; color: var(--text-3); line-height: 1.5; }

/* ── Step 4 — generation log ─────────────────────────────── */
.gen-status {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  background: var(--brand-soft);
  border: 1px solid var(--brand-ring);
  border-radius: var(--r-3, 8px);
  margin-bottom: 14px;
  color: var(--brand);
  font-weight: var(--fw-medium, 500);
  font-size: 13px;
}
.spinner {
  width: 16px;
  height: 16px;
  border: 2px solid var(--brand);
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.progress-log {
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  padding: 14px;
  max-height: 320px;
  overflow-y: auto;
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.6;
}
.log-line { padding: 3px 0; }
.lv-info { color: var(--text-2); }
.lv-ok { color: var(--ok); }
.lv-warn { color: var(--warn); }
.lv-err { color: var(--err); }

/* ── Footer nav ─────────────────────────────────────────── */
.foot-nav {
  display: flex;
  align-items: center;
  gap: 16px;
}
.foot-nav .btn-primary { margin-left: auto; }
.foot-nav .step-meta {
  color: var(--text-3);
  font-size: 11.5px;
  font-family: var(--font-mono);
}
.foot-nav .btn-ghost + .step-meta { margin-left: auto; }
.foot-nav .step-meta + .btn-primary { margin-left: 0; }

.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 36px;
  padding: 0 18px;
  border-radius: var(--r-2, 6px);
  font-size: 13px;
  font-weight: var(--fw-medium, 500);
  cursor: pointer;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text);
  font-family: inherit;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              box-shadow 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.btn-primary {
  background: var(--brand);
  border-color: var(--brand);
  color: var(--text-inverse, #fff);
  font-weight: var(--fw-semibold, 600);
}
.btn-primary:hover:not(:disabled) {
  background: var(--brand-hover);
  border-color: var(--brand-hover);
  box-shadow: var(--sh-brand);
}
.btn-primary:disabled { opacity: 0.45; cursor: not-allowed; }
.btn-ghost {
  color: var(--text-2);
  border-color: var(--line);
  background: var(--surface);
}
.btn-ghost:hover:not(:disabled) {
  background: var(--brand-soft);
  color: var(--brand);
  border-color: var(--brand-ring);
}
.btn-ghost:disabled { opacity: 0.45; cursor: not-allowed; }

/* ── Dark theme tune ────────────────────────────────────── */
:global(html[data-theme="dark"]) .source-pill.active {
  background: var(--surface);
  box-shadow: var(--sh-2);
}
</style>
