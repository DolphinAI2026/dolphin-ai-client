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
              <div v-if="!filteredTables.length" class="empty">没匹配到表</div>
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
.quick-db { overflow-y: auto; height: 100%; background: var(--bg-app); flex: 1; min-height: 0; }
.page-pad { padding: 36px 32px 80px; max-width: 880px; margin: 0 auto; }
.hero { text-align: center; margin-bottom: 28px; }
.db-badge { display: inline-flex; align-items: center; gap: 6px; height: 34px; padding: 0 14px; border-radius: 999px; background: var(--amber-bg); color: var(--amber); font-weight: 600; font-size: 13px; border: 1px solid var(--amber-bg); margin-bottom: 12px; }
.hero-title { font-size: 28px; font-weight: 700; color: var(--text); letter-spacing: -0.02em; line-height: 1.2; margin: 0 0 10px; }
.hero-title .hl { color: var(--amber); }
.hero-sub { font-size: 13px; color: var(--text-2); }

/* Steps */
.steps { display: flex; align-items: center; justify-content: center; gap: 10px; margin-bottom: 24px; }
.step-node { display: inline-flex; align-items: center; gap: 8px; padding: 8px 14px; border-radius: 999px; background: var(--surface); border: 1px solid var(--border); color: var(--text-3); transition: all 0.18s; }
.step-node.active { background: var(--amber-bg); color: var(--amber); border-color: var(--amber); }
.step-node.done { color: var(--emerald); border-color: var(--emerald); background: var(--emerald-bg); }
.step-num { width: 22px; height: 22px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; background: currentColor; color: var(--surface); font-size: 12px; font-weight: 700; }
.step-label { font-size: 12.5px; font-weight: 500; }
.step-arrow { color: var(--text-4); font-size: 14px; }
.step-arrow.done { color: var(--emerald); }

/* Card */
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 28px; box-shadow: var(--shadow-md); margin-bottom: 18px; }
.step-body { min-height: 280px; }

/* Forms */
.form-row { margin-bottom: 18px; }
.form-row > label { display: block; font-size: 12.5px; font-weight: 600; color: var(--text); margin-bottom: 8px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px 16px; }
.form-cell { display: flex; flex-direction: column; gap: 6px; }
.form-cell label { font-size: 12px; color: var(--text-2); font-weight: 500; }
.form-cell input, .form-row textarea {
  width: 100%; padding: 8px 12px; border: 1px solid var(--border); border-radius: 8px;
  background: var(--surface); color: var(--text); font-size: 13px; font-family: inherit; outline: none;
  transition: border-color 0.14s;
}
.form-cell input:focus, .form-row textarea:focus { border-color: var(--amber); }
.form-row textarea { resize: vertical; min-height: 80px; }

.db-types { display: flex; gap: 8px; flex-wrap: wrap; }
.db-type-pill {
  padding: 6px 14px; border-radius: 8px; border: 1px solid var(--border); background: var(--surface);
  cursor: pointer; font-family: inherit; font-size: 12.5px; font-weight: 500; color: var(--text-2);
  transition: all 0.14s;
}
.db-type-pill.active { background: var(--amber-bg); color: var(--amber); border-color: var(--amber); }
.db-type-pill:disabled { opacity: 0.5; cursor: not-allowed; }

/* Step 1 顶部 segmented 切换：新建 / 选已有 */
.source-mode-row {
  display: inline-flex;
  padding: 3px;
  border-radius: 10px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  margin-bottom: 18px;
}
.source-pill {
  padding: 7px 18px;
  border-radius: 7px;
  border: none;
  background: transparent;
  font-size: 12.5px;
  font-weight: 500;
  color: var(--text-2);
  cursor: pointer;
  font-family: inherit;
  transition: all 0.14s;
}
.source-pill.active {
  background: var(--surface);
  color: var(--amber);
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
.source-pill:hover:not(.active) { color: var(--text); }

/* readonly 字段视觉降级 */
.form-cell input[readonly] { background: var(--surface-2); color: var(--text-2); cursor: default; }

/* 新建模式下"同时保存"checkbox */
.save-as-new {
  display: flex; align-items: center; gap: 8px;
  margin-top: 14px; font-size: 12.5px; color: var(--text-2); cursor: pointer;
  user-select: none;
}
.save-as-new input[type="checkbox"] { cursor: pointer; }

.link-inline { color: var(--brand-text); text-decoration: underline; cursor: pointer; }

.hint { font-size: 12px; color: var(--text-3); margin-top: 12px; }
.err-msg { font-size: 12.5px; color: #dc2626; background: rgba(220, 38, 38, 0.08); padding: 8px 12px; border-radius: 8px; margin-top: 12px; }
.muted { color: var(--text-3); font-size: 12.5px; }

/* Step 2 */
.row-between { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.search { padding: 6px 12px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); color: var(--text); font-size: 12.5px; font-family: inherit; outline: none; width: 200px; }
.search:focus { border-color: var(--amber); }
.bulk-actions { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
.link-btn { background: none; border: none; color: var(--brand-text); font-size: 12.5px; cursor: pointer; padding: 0; font-family: inherit; }
.link-btn:hover { text-decoration: underline; }
.table-list { border: 1px solid var(--border); border-radius: 10px; max-height: 360px; overflow-y: auto; background: var(--surface); }
.table-row { display: flex; align-items: center; gap: 12px; padding: 8px 14px; border-bottom: 1px solid var(--border); cursor: pointer; transition: background 0.1s; }
.table-row:last-child { border-bottom: none; }
.table-row:hover { background: var(--surface-2); }
.table-row.skip { opacity: 0.55; }
.table-row.health-red { opacity: 0.75; }
.table-name { font-family: var(--d-font-mono, monospace); font-size: 12.5px; flex: 1; color: var(--text); }
.table-meta { font-size: 11.5px; color: var(--text-3); }
.health-tag { font-size: 11px; padding: 2px 8px; border-radius: 4px; background: var(--surface-2); color: var(--text-3); }
.table-row.health-green .health-tag { background: var(--emerald-bg); color: var(--emerald); }
.table-row.health-yellow .health-tag { background: var(--amber-bg); color: var(--amber); }
.table-row.health-red .health-tag { background: rgba(220, 38, 38, 0.10); color: #dc2626; }
.empty { padding: 24px; text-align: center; color: var(--text-3); font-size: 12.5px; }

/* Step 3 */
.styles { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.style-card { padding: 14px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); cursor: pointer; text-align: left; font-family: inherit; transition: all 0.14s; }
.style-card.active { border-color: var(--amber); background: var(--amber-bg); }
.style-label { font-size: 13px; font-weight: 600; color: var(--text); margin-bottom: 4px; }
.style-card.active .style-label { color: var(--amber); }
.style-desc { font-size: 11.5px; color: var(--text-3); line-height: 1.4; }

/* Step 4 */
.gen-status { display: flex; align-items: center; gap: 12px; padding: 18px; background: var(--amber-bg); border-radius: 10px; margin-bottom: 14px; color: var(--amber); font-weight: 500; }
.spinner { width: 18px; height: 18px; border: 2px solid var(--amber); border-top-color: transparent; border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.progress-log { background: var(--surface-2); border-radius: 8px; padding: 14px; max-height: 320px; overflow-y: auto; font-family: var(--d-font-mono, monospace); font-size: 12px; }
.log-line { padding: 3px 0; }
.lv-info { color: var(--text-2); }
.lv-ok { color: var(--emerald); }
.lv-warn { color: var(--amber); }
.lv-err { color: #dc2626; }

/* Footer nav */
.foot-nav { display: flex; align-items: center; gap: 16px; }
.foot-nav .btn-primary { margin-left: auto; }
.foot-nav .step-meta { color: var(--text-3); font-size: 12px; }
.foot-nav .btn-ghost + .step-meta { margin-left: auto; }
.foot-nav .step-meta + .btn-primary { margin-left: 0; }

.btn { display: inline-flex; align-items: center; gap: 6px; height: 36px; padding: 0 16px; border-radius: 8px; font-size: 13px; font-weight: 500; cursor: pointer; border: 1px solid transparent; background: transparent; color: var(--text); font-family: inherit; transition: all 0.12s; }
.btn-primary { background: var(--amber); color: white; }
.btn-primary:hover:not(:disabled) { opacity: 0.9; }
.btn-primary:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-ghost { color: var(--text-2); border-color: var(--border); }
.btn-ghost:hover:not(:disabled) { background: var(--surface-2); }
.btn-ghost:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
