<!-- frontend/src/views/v2/RuntimePage.vue -->
<!--
  Runtime & Release — 运行与发布
  One page, three tabs:
    1. 流水线   — CI/CD runs (master-detail)
    2. 平台环境 — dev / test / prod aPaaS connections
    3. 部署历史 — every deployment with rollback action

  Seed data inline (verbatim from $DESIGN_SRC/data.js lines 608-731). All
  action buttons are UI stubs (ElMessage.info) until backend wires land.
  See docs/superpowers/plans/2026-05-18-apaas-builder-redesign-p0-p1.md (P2 — Task #10).
-->
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import { useRuntimeEnvStore } from '@/stores/runtimeEnv'
import { useRuntimePipelineStore } from '@/stores/runtimePipeline'
import { useRuntimeDeploymentStore } from '@/stores/runtimeDeployment'
import type { PipelineRun } from '@/api/runtimePipeline'

// Pipeline + PipelineStage types now come from `@/api/runtimePipeline`
// (snake_case `duration_s`). Inline `Pipeline`/`PipelineStage` interfaces +
// `PIPELINES` seed array removed — see useRuntimePipelineStore below.

// Environment type now comes from `@/api/runtimeEnv` (`RuntimeEnv`). Replaced
// inline `Environment` interface + `ENVIRONMENTS` seed array — see
// useRuntimeEnvStore below.

// Deployment type now comes from `@/api/runtimeDeployment` (snake_case
// `app_code`). Inline `Deployment` interface + `DEPLOYMENTS` seed array
// removed — see useRuntimeDeploymentStore below.

// Environments: real backend (Pinia store) — replaces the inline ENVIRONMENTS seed.
const envStore = useRuntimeEnvStore()
// Pipelines + Deployments: real backend (Pinia store) — replaces the inline
// PIPELINES + DEPLOYMENTS seed arrays. Backed by /api/runtime/{pipelines,deployments}.
const pipelineStore = useRuntimePipelineStore()
const deploymentStore = useRuntimeDeploymentStore()
onMounted(() => {
  envStore.fetchEnvironments()
  pipelineStore.fetchPipelines()
  deploymentStore.fetchDeployments()
})

// Pipeline stage statuses come straight from the backend as plain strings
// ('done' / 'running' / 'failed' / 'pending' / 'skip'). No local type needed.

const router = useRouter()

const tab = ref<'pipelines' | 'envs' | 'history'>('pipelines')
const selectedRunId = ref<string>('')
// Auto-select the first pipeline once the store finishes its first fetch.
const cur = computed<PipelineRun | null>(() => {
  const list = pipelineStore.pipelines
  if (!list.length) return null
  const hit = list.find(p => p.id === selectedRunId.value)
  return hit || list[0]
})

// ─── Stats strip ─────────────────────────────────────────────────────────
const stats = computed(() => {
  const pipes = pipelineStore.pipelines
  const deps = deploymentStore.deployments
  const failedRuns = pipes.filter(p => p.status === 'failed').length
  const runningRuns = pipes.filter(p => p.status === 'running').length
  // Today = backend formatted time is "HH:MM" only (no "/" no "昨天").
  const todayDeps = deps.filter(d => d.time && !d.time.includes('/') && !d.time.includes('昨天')).length
  return [
    { label: '今日构建',   v: String(pipes.length), sub: `${failedRuns} 失败 · ${runningRuns} 进行中`, tone: 'brand' as const, icon: 'zap' },
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

interface StatusMeta { label: string; cls: string }

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

const TABS = computed(() => [
  { k: 'pipelines' as const, l: '流水线',   c: pipelineStore.pipelines.length,        ic: 'zap' },
  { k: 'envs'      as const, l: '平台环境', c: envStore.environments.length,          ic: 'admin' },
  { k: 'history'   as const, l: '部署历史', c: deploymentStore.deployments.length,    ic: 'book' },
])

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
    <div class="page">
      <div class="page-pad">
        <!-- Page head -->
        <div class="page-head">
          <div>
            <h1 class="page-title">运行与发布</h1>
            <div class="page-subtitle">
              统一查看：CI/CD 流水线、得帆云 dev / test / prod 三套环境、所有应用与组件的部署历史。
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
              v-for="p in pipelineStore.pipelines"
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
                {{ p.duration_s > 0 ? formatDuration(p.duration_s) : '—' }}
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
            <template v-if="cur">
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
                        <template v-if="s.status === 'done'">{{ formatDuration(s.duration_s) }}</template>
                        <template v-else-if="s.status === 'running'">{{ formatDuration(s.duration_s) }} …</template>
                        <template v-else-if="s.status === 'failed'">{{ formatDuration(s.duration_s) }}</template>
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
            </template>
            <div v-else style="font-size: 12px; color: var(--text-3); padding: 24px 0; text-align: center;">
              {{ pipelineStore.loading ? '正在加载流水线…' : '暂无流水线记录' }}
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
              v-for="e in envStore.environments"
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
                  <div class="rt-env-val truncate">{{ e.tenant_name }}</div>
                  <div class="mono" style="font-size: 10.5px; color: var(--text-3);">{{ e.tenant }}</div>
                </div>
                <div>
                  <div class="rt-env-label">已部署应用</div>
                  <div class="rt-env-val">{{ e.deployed_apps }} 个</div>
                </div>
                <div>
                  <div class="rt-env-label">API Key 到期</div>
                  <div class="rt-env-val" :style="{ color: e.key_warn ? 'var(--amber)' : undefined }">
                    <span v-if="e.key_warn" class="icon" style="vertical-align: -1px; margin-right: 4px;" v-html="renderIcon('bell', 11)" />
                    {{ e.key_expiry }}
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
              v-for="d in deploymentStore.deployments"
              :key="d.id"
              class="rt-table-row"
            >
              <div style="flex: 1.3; min-width: 0;">
                <div class="rt-row-name" style="font-weight: 500;">{{ d.app }}</div>
                <div class="rt-row-meta">
                  <span class="mono">{{ d.app_code }}</span>
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
/* v3 redesign · 2026-05-20 — visual refresh only, template/script untouched.
   v2 indigo-violet + emerald/sky/amber/rose ramps → v3 tokens.
   4-tier weights, 5-tier sizes, r-/sh-/ease tokens, a11y rings.
   Status color routing:
     emerald → ok      amber → warn
     rose    → err     sky   → info (brand-blue softened) */

/* Page chrome */
.page { overflow-y: auto; min-height: 0; background: var(--bg-app); height: 100%; flex: 1; }
.page-pad { padding: 28px 32px 40px; max-width: 1320px; margin: 0 auto; }
.page-head { display: flex; align-items: flex-end; justify-content: space-between; gap: var(--s-4); margin-bottom: 22px; }
.page-title { font-size: var(--t-h2); font-weight: var(--fw-semibold); color: var(--text); letter-spacing: -0.02em; line-height: 1.2; margin: 0; }
.page-subtitle { font-size: var(--t-body); color: var(--text-2); margin-top: var(--s-1); max-width: 760px; line-height: 1.55; }
.page-subtitle b { color: var(--text); font-weight: var(--fw-semibold); }

/* Buttons */
.btn {
  display: inline-flex; align-items: center; justify-content: center; gap: var(--s-2);
  height: 32px; padding: 0 14px; border-radius: var(--r-3);
  font-size: var(--t-body); font-weight: var(--fw-medium); cursor: pointer;
  border: 1px solid transparent; background: transparent; color: var(--text); font-family: inherit;
  white-space: nowrap;
  transition: background 0.14s var(--ease), border-color 0.14s var(--ease), box-shadow 0.14s var(--ease), color 0.14s var(--ease);
}
.btn-sm { height: 26px; padding: 0 10px; font-size: var(--t-mono); border-radius: var(--r-2); }
.btn-primary { background: var(--brand); color: #fff; box-shadow: var(--sh-brand); }
.btn-primary:hover { background: var(--brand-hover); box-shadow: 0 10px 24px -8px var(--brand-glow); }
.btn-primary:disabled { background: var(--surface-3); color: var(--text-3); cursor: not-allowed; box-shadow: none; }
.btn-secondary { background: var(--surface); border-color: var(--line-strong); }
.btn-secondary:hover { border-color: var(--brand-ring); color: var(--brand); background: var(--brand-soft); }
.btn:focus-visible { outline: 2px solid var(--line-focus); outline-offset: 2px; }
.btn .icon { display: inline-flex; align-items: center; }
.btn .icon :deep(svg) { display: block; }

.icon-btn {
  display: inline-grid; place-items: center; width: 24px; height: 24px;
  border-radius: var(--r-2); border: 1px solid transparent; background: transparent;
  color: var(--text-3); cursor: pointer;
  transition: background 0.14s var(--ease), color 0.14s var(--ease);
}
.icon-btn:hover { background: var(--brand-soft); color: var(--brand); }
.icon-btn:focus-visible { outline: 2px solid var(--line-focus); outline-offset: 2px; }
.icon-btn :deep(svg) { display: block; }

/* Cards */
.card { background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-4); box-shadow: var(--sh-1); }
.card-pad { padding: var(--s-4); }

/* Section action link */
.section-action {
  background: transparent; border: 0; cursor: pointer;
  color: var(--brand-text); font-size: var(--t-mono); font-weight: var(--fw-medium); font-family: inherit;
  padding: 2px 4px; border-radius: var(--r-1);
  transition: color 0.14s var(--ease);
}
.section-action:hover { color: var(--brand); }
.section-action:focus-visible { outline: 2px solid var(--line-focus); outline-offset: 2px; }

/* Badges */
.badge {
  display: inline-flex; align-items: center; gap: var(--s-1);
  height: 20px; padding: 0 7px; border-radius: var(--r-1);
  font-size: var(--t-micro); font-weight: var(--fw-medium);
  background: var(--surface-3); color: var(--text-2);
  border: 1px solid transparent;
}
.badge-brand   { background: var(--brand-soft); color: var(--brand-text); }
.badge-emerald { background: var(--ok-soft); color: var(--ok); }
.badge-amber   { background: var(--warn-soft); color: var(--warn); }
.badge-rose    { background: var(--err-soft); color: var(--err); }
.badge-sky     { background: var(--info-soft); color: var(--info); }
.badge-skip    { background: var(--surface-3); color: var(--text-3); }
.badge-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.badge .icon { display: inline-flex; align-items: center; }
.badge .icon :deep(svg) { display: block; }

/* ───── Stats strip (.mcp-summary) ───── */
.mcp-summary {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--s-3);
  margin-top: var(--s-1); margin-bottom: var(--s-1);
}
.mcp-summary-card {
  display: flex; align-items: center; gap: var(--s-3);
  padding: 14px 16px; background: var(--surface);
  border: 1px solid var(--line); border-radius: var(--r-4);
  box-shadow: var(--sh-1);
}
.mcp-summary-icon {
  width: 36px; height: 36px; border-radius: var(--r-3);
  display: grid; place-items: center; flex-shrink: 0;
}
.mcp-summary-icon :deep(svg) { display: block; }
.mcp-summary-icon.mcp-tone-ok    { background: var(--ok-soft); color: var(--ok); }
.mcp-summary-icon.mcp-tone-brand { background: var(--brand-soft); color: var(--brand-text); }
.mcp-summary-icon.mcp-tone-info  { background: var(--info-soft); color: var(--info); }
.mcp-summary-icon.mcp-tone-warn  { background: var(--warn-soft); color: var(--warn); }
.mcp-summary-v { font-size: var(--t-h2); font-weight: var(--fw-semibold); line-height: 1; letter-spacing: -0.015em; color: var(--text); }
.mcp-summary-l { font-size: var(--t-mono); color: var(--text-2); margin-top: var(--s-1); }

/* ───── Tabs (.apps-tabs) ───── */
.apps-tabs {
  display: flex; align-items: center; gap: var(--s-1);
  border-bottom: 1px solid var(--line); padding-bottom: 0;
}
.apps-tab {
  display: inline-flex; align-items: center; gap: var(--s-2);
  height: 36px; padding: 0 14px;
  background: transparent; border: none; border-bottom: 2px solid transparent;
  color: var(--text-2); font-size: var(--t-body); font-weight: var(--fw-medium);
  cursor: pointer; font-family: inherit;
  transition: color 0.14s var(--ease), border-color 0.14s var(--ease);
}
.apps-tab .icon { display: inline-flex; align-items: center; }
.apps-tab .icon :deep(svg) { display: block; }
.apps-tab:hover { color: var(--text); }
.apps-tab.active { color: var(--brand-text); border-bottom-color: var(--brand); }
.apps-tab:focus-visible { outline: 2px solid var(--line-focus); outline-offset: 2px; }
.apps-tab-count {
  font-size: 10.5px; font-weight: var(--fw-semibold);
  padding: 1px 6px; background: var(--surface-3);
  color: var(--text-3); border-radius: var(--r-full);
}
.apps-tab.active .apps-tab-count { background: var(--brand); color: #fff; }

/* ───── Banner inside tabs ───── */
.rt-banner {
  display: flex; align-items: center; gap: var(--s-3);
  padding: var(--s-3) 14px; background: var(--brand-soft); color: var(--brand-text);
  border: 1px solid var(--brand-ring); border-radius: var(--r-4);
}
.rt-banner b { font-weight: var(--fw-semibold); color: var(--brand-text); }
.rt-banner > div { flex: 1; font-size: var(--t-small); line-height: 1.55; }
.rt-banner .icon { display: inline-flex; align-items: center; }
.rt-banner .icon :deep(svg) { display: block; }

/* ───── Generic table rows ───── */
.rt-table-head {
  display: flex; align-items: center; gap: var(--s-3);
  padding: 10px 16px; background: var(--surface-2);
  border-bottom: 1px solid var(--line);
  font-size: var(--t-micro); font-weight: var(--fw-semibold); letter-spacing: 0.04em;
  color: var(--text-3); text-transform: uppercase;
}
.rt-table-row {
  display: flex; align-items: center; gap: var(--s-3);
  padding: var(--s-3) 16px; border-bottom: 1px solid var(--line);
  background: var(--surface);
  transition: background 0.14s var(--ease);
}
.rt-table-row:last-child { border-bottom: none; }
.rt-table-row:hover { background: var(--surface-2); }
.rt-pipe-row {
  width: 100%; cursor: pointer; text-align: left;
  border: none; border-bottom: 1px solid var(--line);
  font-family: inherit; color: var(--text);
}
.rt-pipe-row.active { background: var(--brand-soft); }
.rt-pipe-row:focus-visible { outline: 2px solid var(--line-focus); outline-offset: -2px; }
.rt-row-name { display: flex; align-items: center; gap: var(--s-2); font-size: var(--t-body); color: var(--text); }
.rt-row-meta {
  display: flex; align-items: center; gap: var(--s-2);
  margin-top: 2px; font-size: var(--t-micro); color: var(--text-3); flex-wrap: wrap;
}
.rt-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.rt-dot-active    { background: var(--ok); }
.rt-dot-idle      { background: var(--warn); }
.rt-dot-recycling { background: var(--err); }
.truncate { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* ───── Resource bars ───── */
.rt-resbar { display: flex; flex-direction: column; gap: 2px; margin-bottom: var(--s-1); }
.rt-resbar.is-small .rt-resbar-track { height: 3px; }
.rt-resbar-track { height: 4px; background: var(--surface-3); border-radius: 2px; overflow: hidden; }
.rt-resbar-fill  { height: 100%; border-radius: 2px; transition: width 0.2s var(--ease); }
.rt-resbar-brand { background: var(--brand); }
.rt-resbar-amber { background: var(--warn); }
.rt-resbar-rose  { background: var(--err); }
.rt-resbar-label { font-size: 10.5px; color: var(--text-3); font-family: var(--font-mono); }
.rt-resbar.is-dim .rt-resbar-fill { opacity: 0.5; }

/* ───── Pipeline detail layout ───── */
.rt-pipeline-layout {
  display: grid; grid-template-columns: 1.2fr 1fr; gap: var(--s-4); margin-top: var(--s-4);
  min-height: 0;
}
.rt-run-detail { background: var(--surface); }
.rt-run-head {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: var(--s-3); margin-bottom: var(--s-4);
}
.rt-run-title {
  font-size: 15px; font-weight: var(--fw-semibold); letter-spacing: -0.005em;
  display: flex; align-items: center; gap: var(--s-2);
}
.rt-run-id { font-size: var(--t-mono); color: var(--text-3); font-weight: var(--fw-medium); }

/* Stage chain */
.rt-stages { display: flex; align-items: stretch; flex-wrap: wrap; gap: 0; }
.rt-stage {
  display: flex; align-items: flex-start; gap: 10px;
  padding: var(--s-2) var(--s-3); border-radius: var(--r-3); min-width: 0; flex: 1 1 0;
}
.rt-stage-dot {
  width: 22px; height: 22px; border-radius: 50%; flex-shrink: 0;
  display: grid; place-items: center; color: #fff;
}
.rt-stage-dot :deep(svg) { display: block; }
.rt-stage-done    .rt-stage-dot { background: var(--ok); }
.rt-stage-running .rt-stage-dot { background: var(--brand); }
.rt-stage-failed  .rt-stage-dot { background: var(--err); }
.rt-stage-skip    .rt-stage-dot { background: var(--surface-3); color: var(--text-4); }
.rt-stage-pending .rt-stage-dot { background: var(--surface-3); color: var(--text-4); }
.rt-stage-body { flex: 1; min-width: 0; }
.rt-stage-name { font-size: var(--t-small); font-weight: var(--fw-medium); color: var(--text); }
.rt-stage-dur { font-size: 10.5px; color: var(--text-3); margin-top: 2px; }
.rt-stage-error { font-size: 10.5px; color: var(--err); margin-top: 3px; line-height: 1.4; }
.rt-stage-conn { width: 16px; height: 1px; background: var(--line-strong); align-self: center; flex-shrink: 0; }
.coding-tab-spinner {
  width: 10px; height: 10px;
  border: 2px solid #fff; border-top-color: transparent;
  border-radius: 50%;
  animation: codingSpin 0.8s linear infinite;
}
@keyframes codingSpin { to { transform: rotate(360deg); } }

/* ───── Failure log card ───── */
.rt-log {
  margin-top: var(--s-4); border: 1px solid var(--err); border-radius: var(--r-3);
  background: var(--err-soft); overflow: hidden;
}
.rt-log-head {
  display: flex; align-items: center; gap: var(--s-2);
  padding: var(--s-2) var(--s-3); border-bottom: 1px solid var(--err);
  font-size: var(--t-mono); font-weight: var(--fw-semibold); color: var(--err);
}
.rt-log-head .icon { display: inline-flex; align-items: center; }
.rt-log-head .icon :deep(svg) { display: block; }
.rt-log-body {
  margin: 0; padding: 10px 14px;
  font-size: var(--t-micro); color: var(--text);
  white-space: pre; overflow-x: auto;
  background: var(--surface);
}
.rt-log-foot {
  display: flex; align-items: center; gap: var(--s-2);
  padding: var(--s-2) var(--s-3); border-top: 1px solid var(--err);
  flex-wrap: wrap;
}
.landing-pill {
  background: var(--brand); color: #fff; border: none;
  padding: 3px 10px; border-radius: var(--r-full);
  font-size: var(--t-micro); font-weight: var(--fw-medium); cursor: pointer; font-family: inherit;
  transition: background 0.14s var(--ease);
}
.landing-pill:hover { background: var(--brand-hover); }
.landing-pill:focus-visible { outline: 2px solid var(--line-focus); outline-offset: 2px; }

/* ───── Environment cards ───── */
.rt-env-grid {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--s-4);
  margin-top: var(--s-4);
}
.rt-env-card {
  border: 1px solid var(--line); border-radius: var(--r-4);
  background: var(--surface); padding: 0; overflow: hidden;
  box-shadow: var(--sh-1); display: flex; flex-direction: column;
}
.rt-env-head { display: flex; align-items: center; gap: var(--s-3); padding: 14px 16px; }
.rt-env-stripe { width: 4px; height: 32px; border-radius: 2px; }
.rt-env-dev  .rt-env-stripe { background: var(--text-4); }
.rt-env-test .rt-env-stripe { background: var(--info); }
.rt-env-prod .rt-env-stripe { background: var(--err); }
.rt-env-titles { flex: 1; min-width: 0; }
.rt-env-name {
  font-size: 15px; font-weight: var(--fw-semibold); color: var(--text);
  display: flex; align-items: center;
}
.rt-env-host {
  font-size: var(--t-micro); color: var(--text-3); margin-top: var(--s-1);
  display: flex; align-items: center; gap: var(--s-2); flex-wrap: wrap;
}
.rt-env-status { display: inline-flex; align-items: center; gap: var(--s-1); font-weight: var(--fw-medium); }
.rt-env-status-ok    { color: var(--ok); }
.rt-env-status-warn  { color: var(--warn); }
.rt-env-status-dot   { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.rt-env-grid-meta {
  display: grid; grid-template-columns: 1fr 1fr; gap: var(--s-3);
  padding: 0 16px 14px;
}
.rt-env-label {
  font-size: 10.5px; font-weight: var(--fw-semibold); letter-spacing: 0.04em;
  color: var(--text-3); text-transform: uppercase; margin-bottom: var(--s-1);
}
.rt-env-val { font-size: var(--t-small); color: var(--text); }
.rt-env-actions {
  display: flex; gap: var(--s-2);
  padding: var(--s-3) 16px; border-top: 1px solid var(--line);
  background: var(--surface-2); flex-wrap: wrap;
}

/* Env chips (history table) */
.rt-env-chip { font-size: 10.5px; font-weight: var(--fw-semibold); padding: 2px var(--s-2); border-radius: var(--r-1); }
.rt-env-chip-dev  { background: var(--surface-3); color: var(--text-2); }
.rt-env-chip-test { background: var(--info-soft); color: var(--info); }
.rt-env-chip-prod { background: var(--err-soft); color: var(--err); }

.mono { font-family: var(--font-mono); }
</style>
