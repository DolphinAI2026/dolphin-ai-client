<!-- frontend/src/views/v2/RuntimePage.vue -->
<!--
  Runtime & Release — 运行与发布
  One page, four tabs:
    1. 沙箱     — code-server / 睿鲸 containers per workspace
    2. 流水线   — CI/CD runs (master-detail)
    3. 平台环境 — dev / test / prod aPaaS connections
    4. 部署历史 — every deployment with rollback action

  Seed data inline (verbatim from $DESIGN_SRC/data.js lines 608-731). All
  action buttons are UI stubs (ElMessage.info) until backend wires land.
  See docs/superpowers/plans/2026-05-18-apaas-builder-redesign-p0-p1.md (P2 — Task #10).
-->
<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import ShellTopBar from '@/components/v2/ShellTopBar.vue'

type SandboxStatus = 'active' | 'idle' | 'recycling'
type PipelineStatus = 'running' | 'success' | 'failed' | 'pending' | 'skip'
type EnvId = 'dev' | 'test' | 'prod'

interface Sandbox {
  id: string
  name: string
  workspace: string
  flavor: '睿鲸' | 'Vibe'
  user: string
  cpu: number
  cpuMax: number
  mem: number
  memMax: number
  disk: number
  idle: string
  status: SandboxStatus
  ttl: string
  created: string
  image: string
}

interface PipelineStage {
  name: string
  status: PipelineStatus
  durationS: number
  error?: string
}

interface Pipeline {
  id: string
  name: string
  source: string
  trigger: string
  user: string
  time: string
  durationS: number
  status: PipelineStatus
  branch?: string
  commit?: string
  env?: EnvId
  stages: PipelineStage[]
}

interface Environment {
  id: EnvId
  name: string
  endpoint: string
  tenant: string
  tenantName: string
  health: 'ok' | 'warn'
  heartbeat: string
  deployedApps: number
  default: boolean
  keyExpiry: string
  keyWarn?: boolean
}

interface Deployment {
  id: string
  app: string
  appCode: string
  env: EnvId
  version: string
  user: string
  time: string
  status: PipelineStatus
  changes: string
  duration: string
  error?: string
}

// Seed data — verbatim from $DESIGN_SRC/data.js (lines 608-731).
const SANDBOXES: Sandbox[] = [
  {
    id: 'sbx-7f3a', name: '差旅报销表单', workspace: 'ws-1', flavor: '睿鲸',
    user: 'marshub', cpu: 1.2, cpuMax: 2, mem: 1.8, memMax: 4, disk: 0.6,
    idle: '0 min', status: 'active', ttl: '剩余 1h 58m', created: '今天 14:22', image: 'node:20-alpine + apaas-bridge',
  },
  {
    id: 'sbx-2b1c', name: 'apaas-builder-ai · frontend', workspace: 'vibe', flavor: 'Vibe',
    user: 'marshub', cpu: 0.4, cpuMax: 4, mem: 3.1, memMax: 8, disk: 2.4,
    idle: '0 min', status: 'active', ttl: '剩余 47 min', created: '今天 13:50', image: 'code-server 4.112.0',
  },
  {
    id: 'sbx-9e44', name: '客户工单看板', workspace: 'ws-2', flavor: '睿鲸',
    user: 'marshub', cpu: 0.0, cpuMax: 2, mem: 0.4, memMax: 4, disk: 0.3,
    idle: '12 min', status: 'idle', ttl: '剩余 1h 48m', created: '今天 10:10', image: 'node:20-alpine + apaas-bridge',
  },
  {
    id: 'sbx-c821', name: '资产分类树选择器', workspace: 'ws-3', flavor: '睿鲸',
    user: '李宁', cpu: 0.0, cpuMax: 2, mem: 0.0, memMax: 4, disk: 0.5,
    idle: '4h 02m', status: 'recycling', ttl: '即将回收', created: '昨天 18:21', image: 'node:20-alpine + apaas-bridge',
  },
  {
    id: 'sbx-d115', name: '审批流时间线组件', workspace: 'ws-x', flavor: '睿鲸',
    user: '周航', cpu: 1.8, cpuMax: 2, mem: 3.4, memMax: 4, disk: 0.9,
    idle: '0 min', status: 'active', ttl: '剩余 26 min', created: '今天 13:14', image: 'node:20-alpine + apaas-bridge',
  },
]

const PIPELINES: Pipeline[] = [
  {
    id: 'run-1284', name: '差旅报销表单', source: '睿鲸 · ws-1', trigger: '自动', user: 'AI',
    time: '14:22', durationS: 0, status: 'running', branch: 'apaas-form-component',
    stages: [
      { name: 'Lint', status: 'done' as unknown as PipelineStatus, durationS: 4 },
      { name: 'Build UMD', status: 'done' as unknown as PipelineStatus, durationS: 23 },
      { name: 'Unit Test', status: 'running', durationS: 12 },
      { name: 'E2E', status: 'pending', durationS: 0 },
      { name: '发布到组件市场', status: 'pending', durationS: 0 },
    ],
  },
  {
    id: 'run-1283', name: '资产管理系统 · 增量部署', source: '智能搭建 · 资产管理系统', trigger: '手动', user: 'marshub',
    time: '13:58', durationS: 142, status: 'success', env: 'test',
    stages: [
      { name: '解析 diff', status: 'done' as unknown as PipelineStatus, durationS: 8 },
      { name: '校验配置', status: 'done' as unknown as PipelineStatus, durationS: 14 },
      { name: '调用 aPaaS API', status: 'done' as unknown as PipelineStatus, durationS: 96 },
      { name: '回归校验', status: 'done' as unknown as PipelineStatus, durationS: 24 },
    ],
  },
  {
    id: 'run-1282', name: 'apaas-builder-ai · frontend', source: 'Vibe · sbx-2b1c · main', trigger: 'git push', user: 'marshub',
    time: '13:32', durationS: 86, status: 'success', branch: 'main', commit: 'a3f9b21',
    stages: [
      { name: 'Lint', status: 'done' as unknown as PipelineStatus, durationS: 6 },
      { name: 'Build (vite)', status: 'done' as unknown as PipelineStatus, durationS: 42 },
      { name: 'Unit Test', status: 'done' as unknown as PipelineStatus, durationS: 18 },
      { name: '部署到 staging', status: 'done' as unknown as PipelineStatus, durationS: 20 },
    ],
  },
  {
    id: 'run-1281', name: '客户工单看板', source: '睿鲸 · ws-2', trigger: '自动', user: 'AI',
    time: '10:48', durationS: 67, status: 'failed', branch: 'apaas-form-page',
    stages: [
      { name: 'Lint', status: 'done' as unknown as PipelineStatus, durationS: 5 },
      { name: 'Build UMD', status: 'failed', durationS: 62, error: 'SyntaxError: Unexpected token (form-list/index.vue:48)' },
      { name: 'Unit Test', status: 'skip', durationS: 0 },
      { name: '发布到组件市场', status: 'skip', durationS: 0 },
    ],
  },
  {
    id: 'run-1280', name: '生产工单调度 · 全量部署', source: '智能搭建', trigger: '手动', user: 'marshub',
    time: '昨天 18:14', durationS: 312, status: 'success', env: 'prod',
    stages: [
      { name: '解析配置', status: 'done' as unknown as PipelineStatus, durationS: 12 },
      { name: '校验', status: 'done' as unknown as PipelineStatus, durationS: 8 },
      { name: '调用 aPaaS API', status: 'done' as unknown as PipelineStatus, durationS: 268 },
      { name: '回归校验', status: 'done' as unknown as PipelineStatus, durationS: 24 },
    ],
  },
  {
    id: 'run-1279', name: '人员选择组件 v3.2.1', source: '睿鲸 · 王琪', trigger: '手动', user: '王琪',
    time: '昨天 16:02', durationS: 88, status: 'success', branch: 'apaas-form-component',
    stages: [
      { name: 'Lint', status: 'done' as unknown as PipelineStatus, durationS: 4 },
      { name: 'Build UMD', status: 'done' as unknown as PipelineStatus, durationS: 28 },
      { name: 'Unit Test', status: 'done' as unknown as PipelineStatus, durationS: 32 },
      { name: 'E2E', status: 'done' as unknown as PipelineStatus, durationS: 14 },
      { name: '发布到组件市场', status: 'done' as unknown as PipelineStatus, durationS: 10 },
    ],
  },
]

const ENVIRONMENTS: Environment[] = [
  {
    id: 'dev', name: '开发环境', endpoint: 'https://apaas-dev.definesys.cn/backend',
    tenant: '743906758237356033', tenantName: '得帆云示例租户（开发）',
    health: 'ok', heartbeat: '30s 前', deployedApps: 9, default: false, keyExpiry: '2027-01-15',
  },
  {
    id: 'test', name: '测试环境', endpoint: 'https://apaas-test.definesys.cn/backend',
    tenant: '743906758237356033', tenantName: '得帆云示例租户（测试）',
    health: 'ok', heartbeat: '1m 前', deployedApps: 7, default: true, keyExpiry: '2027-01-15',
  },
  {
    id: 'prod', name: '生产环境', endpoint: 'https://apaas-poc.definesys.cn/backend',
    tenant: '743906758237356033', tenantName: '得帆云示例租户',
    health: 'warn', heartbeat: '1m 前', deployedApps: 12, default: false, keyExpiry: '2026-05-31', keyWarn: true,
  },
]

const DEPLOYMENTS: Deployment[] = [
  { id: 'dep-209', app: '资产管理系统', appCode: 'asset_mgr',    env: 'test', version: 'v1.4.3', user: 'marshub', time: '14:24', status: 'success', changes: '增量：+ 报废审批节点 · 字段 +2', duration: '2m 22s' },
  { id: 'dep-208', app: '差旅报销表单', appCode: 'asset_mgr',    env: 'prod', version: 'v0.9.4', user: 'AI',      time: '13:32', status: 'success', changes: '组件发布：v0.9.4', duration: '1m 46s' },
  { id: 'dep-207', app: '客户工单中心', appCode: 'cs_ticket',    env: 'test', version: 'v2.1.0', user: 'marshub', time: '09:08', status: 'success', changes: '调整 SLA 字段', duration: '1m 12s' },
  { id: 'dep-206', app: '生产工单调度', appCode: 'mfg_work',     env: 'prod', version: 'v1.0.0', user: 'marshub', time: '昨天',  status: 'success', changes: '首次全量部署', duration: '5m 12s' },
  { id: 'dep-205', app: '客户工单看板', appCode: 'ws-2',         env: 'test', version: 'v0.0.1', user: 'AI',      time: '昨天',  status: 'failed',  changes: '组件构建失败', duration: '1m 07s', error: 'SyntaxError' },
  { id: 'dep-204', app: '资产管理系统', appCode: 'asset_mgr',    env: 'prod', version: 'v1.4.2', user: 'marshub', time: '5/16',  status: 'success', changes: '增量：+ 盘点结果字典', duration: '2m 08s' },
  { id: 'dep-203', app: '合同审批',     appCode: 'contract_v3',  env: 'dev',  version: 'v0.1.0', user: 'marshub', time: '5/15',  status: 'success', changes: '草稿试部署', duration: '0m 58s' },
]

// `done` is a PipelineStage-only status not in the PipelineStatus union — use a relaxed type.
type StageStatus = PipelineStatus | 'done'
type Stage = Omit<PipelineStage, 'status'> & { status: StageStatus }
type Pipe = Omit<Pipeline, 'stages'> & { stages: Stage[] }

const router = useRouter()

const tab = ref<'sandboxes' | 'pipelines' | 'envs' | 'history'>('sandboxes')
const selectedRunId = ref<string>(PIPELINES[0].id)
const cur = computed<Pipe>(
  () => (PIPELINES as unknown as Pipe[]).find(p => p.id === selectedRunId.value) || (PIPELINES as unknown as Pipe[])[0]
)

// ─── Stats strip ─────────────────────────────────────────────────────────
const stats = computed(() => {
  const activeSb = SANDBOXES.filter(s => s.status === 'active').length
  const failedRuns = PIPELINES.filter(p => p.status === 'failed').length
  const runningRuns = PIPELINES.filter(p => p.status === 'running').length
  const todayDeps = DEPLOYMENTS.filter(d => !d.time.includes('/') && !d.time.includes('昨天')).length
  return [
    { label: '运行中沙箱', v: String(activeSb), sub: `共 ${SANDBOXES.length} 个 · 平均空闲 18 min`, tone: 'ok' as const, icon: 'check' },
    { label: '今日构建',   v: String(PIPELINES.length), sub: `${failedRuns} 失败 · ${runningRuns} 进行中`, tone: 'brand' as const, icon: 'zap' },
    { label: '今日部署',   v: String(todayDeps), sub: '生产 1 · 测试 2', tone: 'info' as const, icon: 'cloud' },
    { label: '生产健康度', v: '99.8%', sub: '过去 7 天', tone: 'warn' as const, icon: 'shield' },
  ]
})

// ─── Helpers ─────────────────────────────────────────────────────────────
function envLabel(e: string): string {
  return e === 'dev' ? '开发' : e === 'test' ? '测试' : e === 'prod' ? '生产' : e
}

function formatDuration(s: number): string {
  if (s < 60) return s + 's'
  const m = Math.floor(s / 60)
  const r = s - m * 60
  return `${m}m ${r}s`
}

function resourceTone(value: number): 'brand' | 'amber' | 'rose' {
  const v = Math.max(0, Math.min(1, value))
  if (v > 0.85) return 'rose'
  if (v > 0.6)  return 'amber'
  return 'brand'
}

function resourcePct(value: number): string {
  const v = Math.max(0, Math.min(1, value))
  return (v * 100) + '%'
}

interface StatusMeta { label: string; cls: string }
function sandboxStatusMeta(s: SandboxStatus): StatusMeta {
  return ({
    active:    { label: '运行中', cls: 'badge-emerald' },
    idle:      { label: '空闲',   cls: 'badge-amber' },
    recycling: { label: '回收中', cls: 'badge-rose' },
  } as Record<SandboxStatus, StatusMeta>)[s]
}

function pipelineStatusMeta(s: string): StatusMeta {
  const map: Record<string, StatusMeta> = {
    running: { label: '进行中', cls: 'badge-brand' },
    success: { label: '成功',   cls: 'badge-emerald' },
    failed:  { label: '失败',   cls: 'badge-rose' },
    pending: { label: '排队中', cls: 'badge-amber' },
    skip:    { label: '跳过',   cls: 'badge-skip' },
  }
  return map[s] || { label: s, cls: 'badge-skip' }
}

// ─── Action handlers (stubs) ─────────────────────────────────────────────
function notImpl(action: string) {
  ElMessage.info(`${action} 即将上线`)
}

function onOpenSandbox(sbx: Sandbox) {
  if (sbx.flavor === 'Vibe') {
    router.push('/vibe')
  } else {
    router.push('/coding')
  }
}

function onOpenCodingWorkspace() {
  router.push('/coding')
}

// ─── Icon set — copy from $DESIGN_SRC/shell.jsx (lines 14-75) ───────────
const ICONS: Record<string, string> = {
  cloud:    '<path d="M18 18a4 4 0 0 0 0-8 6 6 0 0 0-12 1 4 4 0 0 0 0 8z"/>',
  zap:      '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
  admin:    '<path d="M12 2 4 5v7c0 5 3.5 8.5 8 10 4.5-1.5 8-5 8-10V5z"/><path d="M9 12l2 2 4-4"/>',
  book:     '<path d="M4 5a2 2 0 0 1 2-2h13v18H6a2 2 0 0 1 0-4h13"/><path d="M9 7h6"/>',
  check:    '<path d="m5 13 4 4 10-10"/>',
  refresh:  '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
  gear:     '<path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/><path d="M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z"/>',
  plus:     '<path d="M12 5v14"/><path d="M5 12h14"/>',
  trash:    '<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6 7v13h12V7"/><path d="M10 11v6"/><path d="M14 11v6"/>',
  more:     '<circle cx="12" cy="12" r="1.2" fill="currentColor" stroke="none"/><circle cx="5" cy="12" r="1.2" fill="currentColor" stroke="none"/><circle cx="19" cy="12" r="1.2" fill="currentColor" stroke="none"/>',
  external: '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><path d="M15 3h6v6"/><path d="M10 14 21 3"/>',
  chevronR: '<path d="m9 6 6 6-6 6"/>',
  bell:     '<path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10 21a2 2 0 0 0 4 0"/>',
  shield:   '<path d="M12 2 4 5v7c0 5 3.5 8.5 8 10 4.5-1.5 8-5 8-10V5z"/>',
}
function renderIcon(name: string, size = 16) {
  const inner = ICONS[name] || ''
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`
}

const TABS = [
  { k: 'sandboxes' as const, l: '沙箱',     c: SANDBOXES.length,    ic: 'cloud' },
  { k: 'pipelines' as const, l: '流水线',   c: PIPELINES.length,    ic: 'zap' },
  { k: 'envs'      as const, l: '平台环境', c: ENVIRONMENTS.length, ic: 'admin' },
  { k: 'history'   as const, l: '部署历史', c: DEPLOYMENTS.length,  ic: 'book' },
]

// Failure log content for the selected run (lifted verbatim from design source).
const FAILURE_LOG = `  ▸ npm run build:component --name=客户工单看板
  ▸ vite v5.4.2 building...
  × form-list/index.vue:48:14
       SyntaxError: Unexpected token "}" in template
       46 |   :data="list"
       47 |   :sla-threshold="threshold"
    ▶ 48 |   @sort="onSort}    ← 缺少右引号
       49 | />`
</script>

<template>
  <WorkbenchShell>
    <ShellTopBar />
    <div class="page">
      <div class="page-pad">
        <!-- Page head -->
        <div class="page-head">
          <div>
            <h1 class="page-title">运行与发布</h1>
            <div class="page-subtitle">
              统一查看：睿鲸 / Vibe 沙箱、CI/CD 流水线、得帆云 dev / test / prod 三套环境、所有应用与组件的部署历史。
            </div>
          </div>
          <div style="display: flex; gap: 8px;">
            <button class="btn btn-secondary" @click="notImpl('配置策略')">
              <span class="icon" v-html="renderIcon('book', 13)" /> 配置策略
            </button>
            <button class="btn btn-secondary" @click="notImpl('强制刷新')">
              <span class="icon" v-html="renderIcon('refresh', 13)" /> 强制刷新
            </button>
          </div>
        </div>

        <!-- Stats strip -->
        <div class="mcp-summary">
          <div v-for="s in stats" :key="s.label" class="mcp-summary-card">
            <div :class="['mcp-summary-icon', `mcp-tone-${s.tone}`]" v-html="renderIcon(s.icon, 16)" />
            <div>
              <div class="mcp-summary-v">{{ s.v }}</div>
              <div class="mcp-summary-l">{{ s.label }}</div>
              <div style="font-size: 11px; color: var(--text-3); margin-top: 2px;">{{ s.sub }}</div>
            </div>
          </div>
        </div>

        <!-- Tabs -->
        <div class="apps-tabs" style="margin-top: 20px;">
          <button
            v-for="t in TABS"
            :key="t.k"
            :class="['apps-tab', { active: tab === t.k }]"
            @click="tab = t.k"
          >
            <span class="icon" v-html="renderIcon(t.ic, 13)" /> {{ t.l }}
            <span class="apps-tab-count">{{ t.c }}</span>
          </button>
        </div>

        <!-- ───────────────────── Tab: Sandboxes ───────────────────── -->
        <div v-if="tab === 'sandboxes'" style="margin-top: 14px;">
          <div class="rt-banner">
            <span class="icon" v-html="renderIcon('cloud', 14)" />
            <div>
              <b>沙箱托管在阿里云 ECS 集群。</b>
              睿鲸沙箱用于组件构建（2C/4G 默认），Vibe 沙箱用于 code-server 编辑（4C/8G 默认）。
              空闲 2 小时后自动回收，活动时 TTL 自动续期。
            </div>
            <button class="btn btn-secondary btn-sm" @click="notImpl('配置策略')">
              <span class="icon" v-html="renderIcon('gear', 12)" /> 配置策略
            </button>
          </div>

          <div class="card" style="padding: 0; overflow: hidden; margin-top: 14px;">
            <div class="rt-table-head">
              <div style="flex: 1.6;">沙箱</div>
              <div style="width: 90px;">类型</div>
              <div style="width: 220px;">CPU / 内存 / 磁盘</div>
              <div style="width: 100px;">空闲</div>
              <div style="width: 120px;">TTL</div>
              <div style="width: 100px;">状态</div>
              <div style="width: 110px; text-align: right;">操作</div>
            </div>
            <div
              v-for="s in SANDBOXES"
              :key="s.id"
              class="rt-table-row"
            >
              <div style="flex: 1.6; min-width: 0;">
                <div class="rt-row-name">
                  <span :class="['rt-dot', `rt-dot-${s.status}`]" />
                  <span style="font-weight: 500;">{{ s.name }}</span>
                </div>
                <div class="rt-row-meta">
                  <span class="mono">{{ s.id }}</span>
                  <span>·</span>
                  <span>{{ s.user }}</span>
                  <span>·</span>
                  <span class="mono" style="color: var(--text-3);">{{ s.image }}</span>
                </div>
              </div>
              <div style="width: 90px;">
                <span :class="['badge', s.flavor === '睿鲸' ? 'badge-brand' : 'badge-emerald']">{{ s.flavor }}</span>
              </div>
              <div style="width: 220px;">
                <!-- Resource bars (inline ResourceBar component) -->
                <div class="rt-resbar">
                  <div class="rt-resbar-track">
                    <div :class="['rt-resbar-fill', `rt-resbar-${resourceTone(s.cpu / s.cpuMax)}`]" :style="{ width: resourcePct(s.cpu / s.cpuMax) }" />
                  </div>
                  <div class="rt-resbar-label">{{ s.cpu.toFixed(1) }} / {{ s.cpuMax }} vCPU</div>
                </div>
                <div class="rt-resbar is-small">
                  <div class="rt-resbar-track">
                    <div :class="['rt-resbar-fill', `rt-resbar-${resourceTone(s.mem / s.memMax)}`]" :style="{ width: resourcePct(s.mem / s.memMax) }" />
                  </div>
                  <div class="rt-resbar-label">{{ s.mem.toFixed(1) }} / {{ s.memMax }} GB</div>
                </div>
                <div class="rt-resbar is-small is-dim">
                  <div class="rt-resbar-track">
                    <div :class="['rt-resbar-fill', `rt-resbar-${resourceTone(s.disk / 10)}`]" :style="{ width: resourcePct(s.disk / 10) }" />
                  </div>
                  <div class="rt-resbar-label">{{ s.disk.toFixed(1) }} GB 磁盘</div>
                </div>
              </div>
              <div :style="{ width: '100px', fontSize: '12.5px', color: s.idle === '0 min' ? 'var(--emerald)' : 'var(--text-3)' }">
                {{ s.idle === '0 min' ? '● 活动中' : s.idle }}
              </div>
              <div :style="{ width: '120px', fontSize: '12px', color: s.status === 'recycling' ? 'var(--rose)' : 'var(--text-2)' }" class="mono">
                {{ s.ttl }}
              </div>
              <div style="width: 100px;">
                <span :class="['badge', sandboxStatusMeta(s.status).cls]">
                  <span class="badge-dot" />{{ sandboxStatusMeta(s.status).label }}
                </span>
              </div>
              <div style="width: 110px; display: flex; justify-content: flex-end; gap: 4px;">
                <button class="btn btn-secondary btn-sm" @click="onOpenSandbox(s)">打开</button>
                <button class="icon-btn" style="width: 26px; height: 26px;" title="重启" @click="notImpl('重启')" v-html="renderIcon('refresh', 12)" />
                <button class="icon-btn" style="width: 26px; height: 26px; color: var(--rose);" title="终止" @click="notImpl('终止')" v-html="renderIcon('trash', 12)" />
              </div>
            </div>
          </div>
        </div>

        <!-- ───────────────────── Tab: Pipelines ───────────────────── -->
        <div v-if="tab === 'pipelines'" class="rt-pipeline-layout">
          <div class="card" style="padding: 0; overflow: hidden;">
            <div class="rt-table-head">
              <div style="width: 12px;" />
              <div style="flex: 1;">流水线</div>
              <div style="width: 72px;">来源</div>
              <div style="width: 64px; text-align: right;">耗时</div>
              <div style="width: 80px;">状态</div>
            </div>
            <button
              v-for="p in PIPELINES"
              :key="p.id"
              :class="['rt-table-row', 'rt-pipe-row', { active: selectedRunId === p.id }]"
              @click="selectedRunId = p.id"
            >
              <div style="width: 12px; color: var(--text-4); display: inline-flex; align-items: center;">
                <span v-if="selectedRunId === p.id" v-html="renderIcon('chevronR', 11)" />
              </div>
              <div style="flex: 1; min-width: 0;">
                <div class="rt-row-name">
                  <span style="font-weight: 500;" class="truncate">{{ p.name }}</span>
                  <span :class="['badge', p.trigger === '自动' ? 'badge-brand' : 'badge-skip']" style="flex-shrink: 0;">{{ p.trigger }}</span>
                </div>
                <div class="rt-row-meta">
                  <span class="mono">#{{ p.id.replace('run-', '') }}</span>
                  <template v-if="p.commit">
                    <span>·</span>
                    <span class="mono">{{ p.commit }}</span>
                  </template>
                  <template v-if="p.branch">
                    <span>·</span>
                    <span class="truncate">{{ p.branch }}</span>
                  </template>
                  <template v-if="p.env">
                    <span>·</span>
                    <span>{{ envLabel(p.env) }}</span>
                  </template>
                  <span>·</span>
                  <span>{{ p.time }}</span>
                </div>
              </div>
              <div style="width: 72px; font-size: 11px; color: var(--text-3);" class="truncate">{{ p.source }}</div>
              <div style="width: 64px; font-size: 12px; color: var(--text-2); text-align: right;" class="mono">
                {{ p.durationS > 0 ? formatDuration(p.durationS) : '—' }}
              </div>
              <div style="width: 80px;">
                <span :class="['badge', pipelineStatusMeta(p.status).cls]">
                  <span class="badge-dot" />{{ pipelineStatusMeta(p.status).label }}
                </span>
              </div>
            </button>
          </div>

          <!-- Run detail -->
          <div class="card card-pad rt-run-detail">
            <div class="rt-run-head">
              <div>
                <div class="rt-run-title">
                  {{ cur.name }}
                  <span class="mono rt-run-id">#{{ cur.id.replace('run-', '') }}</span>
                </div>
                <div style="font-size: 12px; color: var(--text-3); margin-top: 4px; display: flex; gap: 6px; align-items: center; flex-wrap: wrap;">
                  <span :class="['badge', pipelineStatusMeta(cur.status).cls]">
                    <span class="badge-dot" />{{ pipelineStatusMeta(cur.status).label }}
                  </span>
                  <span>·</span>
                  <span>{{ cur.source }}</span>
                  <span>·</span>
                  <span>由 <b>{{ cur.user }}</b> {{ cur.trigger === '自动' ? '自动触发' : '手动触发' }}</span>
                  <span>·</span>
                  <span>{{ cur.time }}</span>
                </div>
              </div>
              <div style="display: flex; gap: 6px;">
                <button class="btn btn-secondary btn-sm" @click="notImpl('查看日志')">
                  <span class="icon" v-html="renderIcon('book', 12)" /> 查看日志
                </button>
                <button v-if="cur.status === 'failed'" class="btn btn-primary btn-sm" @click="notImpl('重试')">
                  <span class="icon" v-html="renderIcon('refresh', 12)" /> 重试
                </button>
              </div>
            </div>

            <!-- Stage chain -->
            <div class="rt-stages">
              <template v-for="(s, i) in cur.stages" :key="i">
                <div :class="['rt-stage', `rt-stage-${s.status}`]">
                  <div class="rt-stage-dot">
                    <span v-if="s.status === 'done'" v-html="renderIcon('check', 11)" />
                    <span v-else-if="s.status === 'running'" class="coding-tab-spinner" />
                    <span v-else-if="s.status === 'failed'" style="font-weight: 700; font-size: 12px;">!</span>
                    <span v-else style="width: 5px; height: 5px; border-radius: 50%; background: currentColor; display: block;" />
                  </div>
                  <div class="rt-stage-body">
                    <div class="rt-stage-name">{{ s.name }}</div>
                    <div class="rt-stage-dur mono">
                      <template v-if="s.status === 'done'">{{ formatDuration(s.durationS) }}</template>
                      <template v-else-if="s.status === 'running'">{{ formatDuration(s.durationS) }} …</template>
                      <template v-else-if="s.status === 'failed'">{{ formatDuration(s.durationS) }}</template>
                      <template v-else-if="s.status === 'skip'">已跳过</template>
                      <template v-else>—</template>
                    </div>
                    <div v-if="s.error" class="rt-stage-error mono">{{ s.error }}</div>
                  </div>
                </div>
                <div v-if="i < cur.stages.length - 1" class="rt-stage-conn" />
              </template>
            </div>

            <div v-if="cur.status === 'failed'" class="rt-log">
              <div class="rt-log-head">
                <span class="icon" style="color: var(--rose);" v-html="renderIcon('bell', 12)" />
                <span>构建失败 · 关键日志</span>
                <button class="section-action" style="margin-left: auto;" @click="notImpl('查看完整日志')">查看完整日志 →</button>
              </div>
              <pre class="rt-log-body mono">{{ FAILURE_LOG }}</pre>
              <div class="rt-log-foot">
                <span style="font-size: 11px; color: var(--text-3);">提示：你可以在</span>
                <button class="landing-pill" @click="onOpenCodingWorkspace">睿鲸 ws-2 工作区</button>
                <span style="font-size: 11px; color: var(--text-3);">里让 AI 修复并重新生成</span>
              </div>
            </div>
          </div>
        </div>

        <!-- ───────────────────── Tab: Environments ───────────────────── -->
        <div v-if="tab === 'envs'" style="margin-top: 14px;">
          <div class="rt-banner">
            <span class="icon" v-html="renderIcon('cloud', 14)" />
            <div>
              <b>本租户固定对接 1 套得帆云租户。</b>
              同一租户下配置 3 个环境（dev / test / prod），用于隔离开发、测试、生产。
              默认部署到「测试环境」，确认无误后晋级到生产。
            </div>
            <button class="btn btn-secondary btn-sm" @click="notImpl('添加环境')">
              <span class="icon" v-html="renderIcon('plus', 12)" /> 添加环境
            </button>
          </div>

          <div class="rt-env-grid">
            <div
              v-for="e in ENVIRONMENTS"
              :key="e.id"
              :class="['rt-env-card', `rt-env-${e.id}`]"
            >
              <div class="rt-env-head">
                <div class="rt-env-stripe" />
                <div class="rt-env-titles">
                  <div class="rt-env-name">
                    {{ e.name }}
                    <span v-if="e.default" class="badge badge-brand" style="margin-left: 6px;">默认</span>
                  </div>
                  <div class="rt-env-host">
                    <span :class="['rt-env-status', `rt-env-status-${e.health}`]">
                      <span class="rt-env-status-dot" /> {{ e.health === 'ok' ? '健康' : '需关注' }}
                    </span>
                    <span>·</span>
                    <span>心跳 {{ e.heartbeat }}</span>
                  </div>
                </div>
                <button class="icon-btn" style="width: 28px; height: 28px;" title="测试连接" @click="notImpl('测试连接')" v-html="renderIcon('refresh', 14)" />
              </div>

              <div class="rt-env-grid-meta">
                <div>
                  <div class="rt-env-label">Endpoint</div>
                  <div class="rt-env-val mono truncate">{{ e.endpoint }}</div>
                </div>
                <div>
                  <div class="rt-env-label">租户</div>
                  <div class="rt-env-val truncate">{{ e.tenantName }}</div>
                  <div class="mono" style="font-size: 10.5px; color: var(--text-3);">{{ e.tenant }}</div>
                </div>
                <div>
                  <div class="rt-env-label">已部署应用</div>
                  <div class="rt-env-val">{{ e.deployedApps }} 个</div>
                </div>
                <div>
                  <div class="rt-env-label">API Key 到期</div>
                  <div class="rt-env-val" :style="{ color: e.keyWarn ? 'var(--amber)' : undefined }">
                    <span v-if="e.keyWarn" class="icon" style="vertical-align: -1px; margin-right: 4px;" v-html="renderIcon('bell', 11)" />
                    {{ e.keyExpiry }}
                  </div>
                </div>
              </div>

              <div class="rt-env-actions">
                <button class="btn btn-secondary btn-sm" @click="notImpl('打开 aPaaS')">
                  <span class="icon" v-html="renderIcon('external', 12)" /> 打开 aPaaS
                </button>
                <button class="btn btn-secondary btn-sm" @click="notImpl('配置')">
                  <span class="icon" v-html="renderIcon('gear', 12)" /> 配置
                </button>
                <button class="btn btn-primary btn-sm" :disabled="e.id === 'prod'" @click="notImpl('晋级')">
                  晋级从 {{ e.id === 'dev' ? 'dev' : 'test' }} →
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- ───────────────────── Tab: Deployment history ───────────────────── -->
        <div v-if="tab === 'history'" style="margin-top: 14px;">
          <div class="card" style="padding: 0; overflow: hidden;">
            <div class="rt-table-head">
              <div style="flex: 1.3;">应用 / 组件</div>
              <div style="width: 70px;">环境</div>
              <div style="width: 80px;">版本</div>
              <div style="flex: 1.4;">变更</div>
              <div style="width: 70px;">触发者</div>
              <div style="width: 70px;">耗时</div>
              <div style="width: 70px;">状态</div>
              <div style="width: 100px; text-align: right;">操作</div>
            </div>
            <div
              v-for="d in DEPLOYMENTS"
              :key="d.id"
              class="rt-table-row"
            >
              <div style="flex: 1.3; min-width: 0;">
                <div class="rt-row-name" style="font-weight: 500;">{{ d.app }}</div>
                <div class="rt-row-meta">
                  <span class="mono">{{ d.appCode }}</span>
                  <span>·</span>
                  <span class="mono">{{ d.id }}</span>
                  <span>·</span>
                  <span>{{ d.time }}</span>
                </div>
              </div>
              <div style="width: 70px;">
                <span :class="['rt-env-chip', `rt-env-chip-${d.env}`]">{{ envLabel(d.env) }}</span>
              </div>
              <div style="width: 80px;" class="mono">{{ d.version }}</div>
              <div :style="{ flex: 1.4, fontSize: '12px', color: d.status === 'failed' ? 'var(--rose)' : 'var(--text-2)' }" class="truncate">
                {{ d.changes }}<span v-if="d.error" class="mono" style="color: var(--rose); margin-left: 6px;">· {{ d.error }}</span>
              </div>
              <div style="width: 70px; font-size: 12px; color: var(--text-2);" class="truncate">{{ d.user }}</div>
              <div style="width: 70px; font-size: 12px; color: var(--text-3);" class="mono">{{ d.duration }}</div>
              <div style="width: 70px;">
                <span :class="['badge', pipelineStatusMeta(d.status).cls]">
                  <span class="badge-dot" />{{ pipelineStatusMeta(d.status).label }}
                </span>
              </div>
              <div style="width: 100px; display: flex; justify-content: flex-end; gap: 4px;">
                <button
                  v-if="d.status === 'success' && d.env !== 'dev'"
                  class="btn btn-secondary btn-sm"
                  title="回滚至上一版本"
                  @click="notImpl('回滚')"
                >
                  <span class="icon" v-html="renderIcon('refresh', 11)" /> 回滚
                </button>
                <button class="icon-btn" style="width: 26px; height: 26px;" title="更多" @click="notImpl('更多操作')" v-html="renderIcon('more', 14)" />
              </div>
            </div>
          </div>

          <div style="display: flex; justify-content: center; margin-top: 14px;">
            <button class="btn btn-secondary btn-sm" @click="notImpl('加载更早历史')">加载更早历史</button>
          </div>
        </div>

      </div>
    </div>
  </WorkbenchShell>
</template>

<style scoped>
/* Page chrome — same as IndustryPage / AgentsPage. */
.page { overflow-y: auto; min-height: 0; background: var(--bg-app); height: 100%; flex: 1; }
.page-pad { padding: 28px 32px 40px; max-width: 1320px; margin: 0 auto; }
.page-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin-bottom: 22px; }
.page-title { font-size: 22px; font-weight: 600; color: var(--text); letter-spacing: -0.02em; line-height: 1.2; margin: 0; }
.page-subtitle { font-size: 13px; color: var(--text-2); margin-top: 4px; max-width: 760px; line-height: 1.55; }
.page-subtitle b { color: var(--text); font-weight: 600; }

/* Buttons */
.btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  height: 32px; padding: 0 14px; border-radius: 8px;
  font-size: 13px; font-weight: 500; cursor: pointer;
  border: 1px solid transparent; background: transparent; color: var(--text); font-family: inherit;
  white-space: nowrap; transition: background 0.12s, border-color 0.12s, box-shadow 0.12s;
}
.btn-sm { height: 26px; padding: 0 10px; font-size: 12px; border-radius: 6px; }
.btn-primary { background: var(--brand); color: #fff; box-shadow: 0 1px 2px rgba(28, 21, 73, 0.16), inset 0 -1px 0 rgba(0, 0, 0, 0.15); }
.btn-primary:hover { background: var(--brand-hover); box-shadow: 0 2px 6px var(--brand-ring); }
.btn-primary:disabled { background: var(--surface-3); color: var(--text-3); cursor: not-allowed; box-shadow: none; }
.btn-secondary { background: var(--surface); border-color: var(--border-strong); }
.btn-secondary:hover { border-color: var(--text-4); }
.btn .icon { display: inline-flex; align-items: center; }
.btn .icon :deep(svg) { display: block; }

.icon-btn {
  display: inline-grid; place-items: center; width: 24px; height: 24px;
  border-radius: 6px; border: 1px solid transparent; background: transparent;
  color: var(--text-3); cursor: pointer; transition: background 0.14s, color 0.14s;
}
.icon-btn:hover { background: var(--surface-3); color: var(--text); }
.icon-btn :deep(svg) { display: block; }

/* Cards */
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; box-shadow: var(--shadow-xs); }
.card-pad { padding: 16px; }

/* Section action link */
.section-action {
  background: transparent; border: 0; cursor: pointer;
  color: var(--brand-text); font-size: 12px; font-weight: 500; font-family: inherit;
  padding: 2px 4px; border-radius: 4px;
}
.section-action:hover { color: var(--brand); }

/* Badges */
.badge {
  display: inline-flex; align-items: center; gap: 4px;
  height: 20px; padding: 0 7px; border-radius: 5px;
  font-size: 11px; font-weight: 500;
  background: var(--surface-3); color: var(--text-2);
  border: 1px solid transparent;
}
.badge-brand   { background: var(--brand-soft); color: var(--brand-text); }
.badge-emerald { background: var(--emerald-bg); color: var(--emerald); }
.badge-amber   { background: var(--amber-bg);   color: var(--amber); }
.badge-rose    { background: var(--rose-bg);    color: var(--rose); }
.badge-sky     { background: var(--sky-bg);     color: var(--sky); }
.badge-skip    { background: var(--surface-3); color: var(--text-3); }
.badge-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.badge .icon { display: inline-flex; align-items: center; }
.badge .icon :deep(svg) { display: block; }

/* ───── Stats strip (.mcp-summary) ───── */
.mcp-summary {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px;
  margin-top: 4px; margin-bottom: 4px;
}
.mcp-summary-card {
  display: flex; align-items: center; gap: 12px;
  padding: 14px 16px; background: var(--surface);
  border: 1px solid var(--border); border-radius: 12px;
  box-shadow: var(--shadow-xs);
}
.mcp-summary-icon {
  width: 36px; height: 36px; border-radius: 9px;
  display: grid; place-items: center; flex-shrink: 0;
}
.mcp-summary-icon :deep(svg) { display: block; }
.mcp-summary-icon.mcp-tone-ok    { background: var(--emerald-bg); color: var(--emerald); }
.mcp-summary-icon.mcp-tone-brand { background: var(--brand-soft); color: var(--brand-text); }
.mcp-summary-icon.mcp-tone-info  { background: var(--sky-bg);     color: var(--sky); }
.mcp-summary-icon.mcp-tone-warn  { background: var(--amber-bg);   color: var(--amber); }
.mcp-summary-v { font-size: 22px; font-weight: 600; line-height: 1; letter-spacing: -0.015em; color: var(--text); }
.mcp-summary-l { font-size: 12px; color: var(--text-2); margin-top: 4px; }

/* ───── Tabs (.apps-tabs) ───── */
.apps-tabs {
  display: flex; align-items: center; gap: 4px;
  border-bottom: 1px solid var(--border); padding-bottom: 0;
}
.apps-tab {
  display: inline-flex; align-items: center; gap: 6px;
  height: 36px; padding: 0 14px;
  background: transparent; border: none; border-bottom: 2px solid transparent;
  color: var(--text-2); font-size: 13px; font-weight: 500;
  cursor: pointer; font-family: inherit;
}
.apps-tab .icon { display: inline-flex; align-items: center; }
.apps-tab .icon :deep(svg) { display: block; }
.apps-tab:hover { color: var(--text); }
.apps-tab.active { color: var(--brand-text); border-bottom-color: var(--brand); }
.apps-tab-count {
  font-size: 10.5px; font-weight: 600;
  padding: 1px 6px; background: var(--surface-3);
  color: var(--text-3); border-radius: 999px;
}
.apps-tab.active .apps-tab-count { background: var(--brand); color: #fff; }

/* ───── Banner inside tabs ───── */
.rt-banner {
  display: flex; align-items: center; gap: 12px;
  padding: 12px 14px; background: var(--ai-soft); color: var(--ai-text);
  border: 1px solid var(--ai-soft-2); border-radius: 10px;
}
.rt-banner b { font-weight: 600; color: var(--ai-text); }
.rt-banner > div { flex: 1; font-size: 12.5px; line-height: 1.55; }
.rt-banner .icon { display: inline-flex; align-items: center; }
.rt-banner .icon :deep(svg) { display: block; }

/* ───── Generic table rows ───── */
.rt-table-head {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 16px; background: var(--surface-2);
  border-bottom: 1px solid var(--border);
  font-size: 11px; font-weight: 600; letter-spacing: 0.04em;
  color: var(--text-3); text-transform: uppercase;
}
.rt-table-row {
  display: flex; align-items: center; gap: 12px;
  padding: 12px 16px; border-bottom: 1px solid var(--border);
  background: var(--surface);
}
.rt-table-row:last-child { border-bottom: none; }
.rt-table-row:hover { background: var(--surface-2); }
.rt-pipe-row {
  width: 100%; cursor: pointer; text-align: left;
  border: none; border-bottom: 1px solid var(--border);
  font-family: inherit; color: var(--text);
}
.rt-pipe-row.active { background: var(--brand-soft); }
.rt-row-name { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text); }
.rt-row-meta {
  display: flex; align-items: center; gap: 6px;
  margin-top: 2px; font-size: 11px; color: var(--text-3); flex-wrap: wrap;
}
.rt-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.rt-dot-active    { background: var(--emerald); }
.rt-dot-idle      { background: var(--amber); }
.rt-dot-recycling { background: var(--rose); }
.truncate { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* ───── Resource bars ───── */
.rt-resbar { display: flex; flex-direction: column; gap: 2px; margin-bottom: 4px; }
.rt-resbar.is-small .rt-resbar-track { height: 3px; }
.rt-resbar-track { height: 4px; background: var(--surface-3); border-radius: 2px; overflow: hidden; }
.rt-resbar-fill  { height: 100%; border-radius: 2px; transition: width 0.2s; }
.rt-resbar-brand { background: var(--brand); }
.rt-resbar-amber { background: var(--amber); }
.rt-resbar-rose  { background: var(--rose); }
.rt-resbar-label { font-size: 10.5px; color: var(--text-3); font-family: var(--d-font-mono); }
.rt-resbar.is-dim .rt-resbar-fill { opacity: 0.5; }

/* ───── Pipeline detail layout ───── */
.rt-pipeline-layout {
  display: grid; grid-template-columns: 1.2fr 1fr; gap: 14px; margin-top: 14px;
  min-height: 0;
}
.rt-run-detail { background: var(--surface); }
.rt-run-head {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: 12px; margin-bottom: 16px;
}
.rt-run-title {
  font-size: 15px; font-weight: 600; letter-spacing: -0.005em;
  display: flex; align-items: center; gap: 8px;
}
.rt-run-id { font-size: 12px; color: var(--text-3); font-weight: 500; }

/* Stage chain */
.rt-stages { display: flex; align-items: stretch; flex-wrap: wrap; gap: 0; }
.rt-stage {
  display: flex; align-items: flex-start; gap: 10px;
  padding: 8px 12px; border-radius: 8px; min-width: 0; flex: 1 1 0;
}
.rt-stage-dot {
  width: 22px; height: 22px; border-radius: 50%; flex-shrink: 0;
  display: grid; place-items: center; color: #fff;
}
.rt-stage-dot :deep(svg) { display: block; }
.rt-stage-done    .rt-stage-dot { background: var(--emerald); }
.rt-stage-running .rt-stage-dot { background: var(--brand); }
.rt-stage-failed  .rt-stage-dot { background: var(--rose); }
.rt-stage-skip    .rt-stage-dot { background: var(--surface-3); color: var(--text-4); }
.rt-stage-pending .rt-stage-dot { background: var(--surface-3); color: var(--text-4); }
.rt-stage-body { flex: 1; min-width: 0; }
.rt-stage-name { font-size: 12.5px; font-weight: 500; color: var(--text); }
.rt-stage-dur { font-size: 10.5px; color: var(--text-3); margin-top: 2px; }
.rt-stage-error { font-size: 10.5px; color: var(--rose); margin-top: 3px; line-height: 1.4; }
.rt-stage-conn { width: 16px; height: 1px; background: var(--border-strong); align-self: center; flex-shrink: 0; }
.coding-tab-spinner {
  width: 10px; height: 10px;
  border: 2px solid #fff; border-top-color: transparent;
  border-radius: 50%;
  animation: codingSpin 0.8s linear infinite;
}
@keyframes codingSpin { to { transform: rotate(360deg); } }

/* ───── Failure log card ───── */
.rt-log {
  margin-top: 14px; border: 1px solid var(--rose); border-radius: 8px;
  background: var(--rose-bg); overflow: hidden;
}
.rt-log-head {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 12px; border-bottom: 1px solid var(--rose);
  font-size: 12px; font-weight: 600; color: var(--rose);
}
.rt-log-head .icon { display: inline-flex; align-items: center; }
.rt-log-head .icon :deep(svg) { display: block; }
.rt-log-body {
  margin: 0; padding: 10px 14px;
  font-size: 11px; color: var(--text);
  white-space: pre; overflow-x: auto;
  background: var(--surface);
}
.rt-log-foot {
  display: flex; align-items: center; gap: 6px;
  padding: 8px 12px; border-top: 1px solid var(--rose);
  flex-wrap: wrap;
}
.landing-pill {
  background: var(--brand); color: #fff; border: none;
  padding: 3px 10px; border-radius: 999px;
  font-size: 11px; font-weight: 500; cursor: pointer; font-family: inherit;
}
.landing-pill:hover { background: var(--brand-hover); }

/* ───── Environment cards ───── */
.rt-env-grid {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px;
  margin-top: 14px;
}
.rt-env-card {
  border: 1px solid var(--border); border-radius: 12px;
  background: var(--surface); padding: 0; overflow: hidden;
  box-shadow: var(--shadow-xs); display: flex; flex-direction: column;
}
.rt-env-head { display: flex; align-items: center; gap: 10px; padding: 14px 16px; }
.rt-env-stripe { width: 4px; height: 32px; border-radius: 2px; }
.rt-env-dev  .rt-env-stripe { background: var(--text-4); }
.rt-env-test .rt-env-stripe { background: var(--sky); }
.rt-env-prod .rt-env-stripe { background: var(--rose); }
.rt-env-titles { flex: 1; min-width: 0; }
.rt-env-name {
  font-size: 15px; font-weight: 600; color: var(--text);
  display: flex; align-items: center;
}
.rt-env-host {
  font-size: 11px; color: var(--text-3); margin-top: 4px;
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
}
.rt-env-status { display: inline-flex; align-items: center; gap: 4px; font-weight: 500; }
.rt-env-status-ok    { color: var(--emerald); }
.rt-env-status-warn  { color: var(--amber); }
.rt-env-status-dot   { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.rt-env-grid-meta {
  display: grid; grid-template-columns: 1fr 1fr; gap: 10px;
  padding: 0 16px 14px;
}
.rt-env-label {
  font-size: 10.5px; font-weight: 600; letter-spacing: 0.04em;
  color: var(--text-3); text-transform: uppercase; margin-bottom: 4px;
}
.rt-env-val { font-size: 12.5px; color: var(--text); }
.rt-env-actions {
  display: flex; gap: 6px;
  padding: 12px 16px; border-top: 1px solid var(--border);
  background: var(--surface-2); flex-wrap: wrap;
}

/* Env chips (history table) */
.rt-env-chip { font-size: 10.5px; font-weight: 600; padding: 2px 8px; border-radius: 4px; }
.rt-env-chip-dev  { background: var(--surface-3); color: var(--text-2); }
.rt-env-chip-test { background: var(--sky-bg);    color: var(--sky); }
.rt-env-chip-prod { background: var(--rose-bg);   color: var(--rose); }

.mono { font-family: var(--d-font-mono, ui-monospace, SFMono-Regular, Menlo, monospace); }
</style>
