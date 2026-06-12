<template>
  <BuilderFrame :breadcrumbs="[{ label: 'DevOps' }, { label: currentLabel }]">
    <main class="builder-page devops-page">
      <div class="devops-shell">
        <aside
          class="devops-side"
          :class="{ collapsed: sideCollapsed }"
          aria-label="DevOps 导航"
        >
          <div class="side-head">
            <div v-if="!sideCollapsed" class="side-eyebrow">DevOps</div>
            <button
              class="side-collapse-btn"
              type="button"
              :title="sideCollapsed ? '展开导航' : '收起导航'"
              @click="toggleSide"
            >{{ sideCollapsed ? '»' : '«' }}</button>
          </div>
          <button
            v-for="item in nav"
            :key="item.key"
            class="side-link"
            :class="{ active: active === item.key }"
            type="button"
            :title="sideCollapsed ? `${item.label} — ${item.description}` : ''"
            @click="selectTab(item.key)"
          >
            <component :is="item.icon" class="side-icon" />
            <span v-if="!sideCollapsed" class="side-copy">
              <strong>{{ item.label }}</strong>
              <small>{{ item.description }}</small>
            </span>
            <span v-if="navBadge(item.key) !== null" class="nav-count">{{ navBadge(item.key) }}</span>
          </button>
        </aside>

        <section class="devops-main">
          <header class="devops-header">
            <div class="header-copy">
              <div class="builder-section-kicker">{{ currentKicker }}</div>
              <h1>{{ currentLabel }}</h1>
              <p>{{ currentDescription }}</p>
            </div>
            <div class="header-actions">
              <label class="app-select">
                <span>应用</span>
                <select
                  v-if="appOptions.length"
                  v-model.number="selectedApplicationId"
                  @change="onAppChange"
                >
                  <option v-for="app in appOptions" :key="app.id" :value="app.id">
                    {{ app.app_name }}
                  </option>
                </select>
                <button
                  v-else
                  class="devops-button ghost"
                  type="button"
                  @click="$router.push('/chat')"
                  title="去 AI 搭建创建第一个应用"
                >+ 创建应用</button>
              </label>
              <button
                v-if="selectedApplicationId"
                class="devops-button primary"
                type="button"
                :disabled="creatingProposal || !canCreateProposal"
                @click="openCreateProposal"
                title="把最新 draft SPEC 作为提案发布（无 draft 时会提示）"
              >
                {{ creatingProposal ? '创建中…' : '+ 创建提案' }}
              </button>
              <button class="devops-button ghost" type="button" :disabled="loading" @click="refreshAll">
                <Refresh />
                {{ loading ? '刷新中' : '刷新' }}
              </button>
            </div>
          </header>

          <section class="mvp-banner" aria-label="DevOps 版本提示">
            <strong>DevOps MVP 版</strong>
            <span>持续迭代中，当前先覆盖提案、Git、流水线和审批视图，运行数据会逐步接入。</span>
          </section>

          <section class="summary-grid" aria-label="DevOps 总览指标">
            <article class="summary-card selected">
              <span class="summary-label">当前应用</span>
              <strong>{{ selectedAppName }}</strong>
              <p>{{ selectedAppMeta }}</p>
              <div v-if="selectedApp" class="card-quick-links">
                <button class="quick-link" type="button" @click="goToBuilder" title="去 AI 搭建编辑 SPEC">
                  编辑 SPEC →
                </button>
                <button class="quick-link" type="button" @click="goToApps" title="返回应用列表">
                  应用列表 →
                </button>
                <a
                  v-if="selectedApp.apaas_url"
                  :href="selectedApp.apaas_url"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="quick-link"
                  title="在平台打开"
                >平台 ↗</a>
              </div>
            </article>
            <article class="summary-card">
              <span class="summary-label">待处理提案</span>
              <strong>{{ actionableProposalCount }}</strong>
              <p>{{ approvedCount }} 个已批准，{{ openReviewCount }} 个待评审</p>
            </article>
            <article class="summary-card">
              <span class="summary-label">Git 状态</span>
              <strong>{{ gitStatusLabel }}</strong>
              <p>{{ gitStatusHint }}</p>
            </article>
            <article class="summary-card">
              <span class="summary-label">交付状态</span>
              <strong>{{ deliveryStateLabel }}</strong>
              <p>{{ latestActivityLabel }}</p>
            </article>
          </section>

          <template v-if="active === 'overview'">
            <section class="overview-layout">
              <section class="devops-panel primary-panel">
                <div class="panel-head">
                  <div>
                    <span class="panel-kicker">Delivery Track</span>
                    <h2>交付轨道</h2>
                  </div>
                  <button class="devops-button" type="button" @click="selectTab('proposals')">
                    查看提案
                  </button>
                </div>
                <ol class="delivery-steps">
                  <li v-for="step in deliverySteps" :key="step.key" :class="`step-${step.state}`">
                    <span class="step-index">{{ step.index }}</span>
                    <div>
                      <strong>{{ step.title }}</strong>
                      <p>{{ step.description }}</p>
                    </div>
                    <span class="step-state">{{ step.label }}</span>
                  </li>
                </ol>
              </section>

              <section class="devops-panel">
                <div class="panel-head">
                  <div>
                    <span class="panel-kicker">Recent Work</span>
                    <h2>最近活动</h2>
                  </div>
                  <span class="panel-count">{{ runRows.length }} 条</span>
                </div>
                <div v-if="runRows.length" class="activity-list">
                  <button
                    v-for="row in runRows.slice(0, 5)"
                    :key="row.id"
                    class="activity-row"
                    type="button"
                    @click="goToProposal(row.id)"
                  >
                    <span class="activity-dot" :class="row.tone" />
                    <span>
                      <strong>{{ row.title }}</strong>
                      <small>{{ row.statusText }} · {{ row.time }}</small>
                    </span>
                  </button>
                </div>
                <div v-else class="empty-state compact">
                  <strong>暂无运行记录</strong>
                  <p>当应用产生 proposal、apply 或 Git 同步动作后，会出现在这里。</p>
                </div>
              </section>
            </section>
          </template>

          <template v-else-if="active === 'proposals'">
            <section class="devops-panel">
              <div class="panel-head">
                <div>
                  <span class="panel-kicker">Change Proposals</span>
                  <h2>变更提案</h2>
                </div>
                <div class="status-filter" role="tablist" aria-label="提案状态筛选">
                  <button
                    v-for="status in statusFilters"
                    :key="status.key"
                    type="button"
                    :class="{ active: statusFilter === status.key }"
                    @click="statusFilter = status.key"
                  >
                    {{ status.label }}
                    <span>{{ countByStatus(status.key) }}</span>
                  </button>
                </div>
              </div>
              <div class="table-wrap">
                <table class="devops-table">
                  <thead>
                    <tr>
                      <th>标题</th>
                      <th>状态</th>
                      <th>提案者</th>
                      <th>创建时间</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="proposal in filteredProposals" :key="proposal.id">
                      <td>
                        <strong>{{ proposal.title }}</strong>
                        <small>{{ proposal.draft_spec_id }}</small>
                      </td>
                      <td>
                        <span class="status-badge" :class="`status-${proposal.status}`">
                          {{ STATUS_DISPLAY_NAMES[proposal.status] || proposal.status }}
                        </span>
                      </td>
                      <td>用户 {{ proposal.created_by }}</td>
                      <td>{{ formatDate(proposal.created_at) }}</td>
                      <td>
                        <button class="row-action" type="button" @click="goToProposal(proposal.id)">
                          查看
                        </button>
                      </td>
                    </tr>
                    <tr v-if="!filteredProposals.length">
                      <td colspan="5">
                        <div class="empty-state table-empty">
                          <strong>暂无匹配提案</strong>
                          <p>切换状态筛选，或回到搭建工作台创建新的 SPEC 变更。</p>
                        </div>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>
          </template>

          <template v-else-if="active === 'apply-history'">
            <section class="devops-panel">
              <div class="panel-head">
                <div>
                  <span class="panel-kicker">Apply History</span>
                  <h2>Apply 历史</h2>
                </div>
                <span class="panel-count">{{ appliedProposals.length }} 条</span>
              </div>
              <ol v-if="appliedProposals.length" class="timeline">
                <li v-for="proposal in appliedProposals" :key="proposal.id">
                  <span class="timeline-dot ok" />
                  <div>
                    <strong>{{ proposal.title }}</strong>
                    <p>{{ formatDate(proposal.applied_at) }} · SPEC {{ proposal.draft_spec_id }}</p>
                  </div>
                  <button class="row-action" type="button" @click="goToProposal(proposal.id)">查看</button>
                </li>
              </ol>
              <div v-else class="empty-state">
                <strong>还没有 Apply 记录</strong>
                <p>已批准的提案执行 apply 后，会沉淀到这里作为发布前审计线索。</p>
              </div>
            </section>
          </template>

          <template v-else-if="active === 'git-repo'">
            <section class="git-layout">
              <section class="devops-panel git-card">
                <div class="panel-head">
                  <div>
                    <span class="panel-kicker">Repository</span>
                    <h2>Git 仓库</h2>
                  </div>
                  <span class="status-badge" :class="gitBadgeClass">{{ gitStatusLabel }}</span>
                </div>

                <dl class="git-fields">
                  <div>
                    <dt>Provider</dt>
                    <dd>{{ selectedApp?.git_provider || '未配置' }}</dd>
                  </div>
                  <div>
                    <dt>仓库 URL</dt>
                    <dd>
                      <a
                        v-if="selectedApp?.git_repo_url"
                        :href="selectedApp.git_repo_url"
                        target="_blank"
                        rel="noreferrer"
                      >
                        {{ selectedApp.git_repo_url }}
                      </a>
                      <span v-else>尚未初始化</span>
                    </dd>
                  </div>
                  <div>
                    <dt>默认分支</dt>
                    <dd>{{ selectedApp?.git_default_branch || 'main' }}</dd>
                  </div>
                  <div>
                    <dt>漂移检测</dt>
                    <dd>{{ driftStatusText }}</dd>
                  </div>
                </dl>

                <div class="git-actions">
                  <button class="devops-button primary" type="button" :disabled="!selectedProjectId" @click="goToProjectGit">
                    <LinkIcon />
                    Git 设置
                  </button>
                  <button
                    class="devops-button"
                    type="button"
                    :disabled="!selectedApplicationId || hasGitRepo || initializingRepo"
                    @click="initRepo"
                  >
                    <Promotion />
                    {{ initializingRepo ? '初始化中' : '初始化仓库' }}
                  </button>
                  <button
                    class="devops-button ghost"
                    type="button"
                    :disabled="!hasGitRepo || driftLoading"
                    @click="loadDriftStatus"
                  >
                    <Refresh />
                    检测漂移
                  </button>
                </div>
              </section>

              <section class="devops-panel">
                <div class="panel-head">
                  <div>
                    <span class="panel-kicker">Integration Notes</span>
                    <h2>接入状态</h2>
                  </div>
                </div>
                <ul class="integration-list">
                  <li :class="{ done: Boolean(selectedProjectId) }">
                    <Check />
                    <span>应用已归属项目</span>
                  </li>
                  <li :class="{ done: Boolean(selectedApp?.git_provider) }">
                    <Check />
                    <span>项目已绑定 Git Provider</span>
                  </li>
                  <li :class="{ done: hasGitRepo }">
                    <Check />
                    <span>应用仓库已初始化</span>
                  </li>
                  <li :class="{ done: driftStatus?.drift === false }">
                    <Check />
                    <span>Builder SPEC 与 Git HEAD 一致</span>
                  </li>
                </ul>
              </section>
            </section>
          </template>

          <template v-else-if="active === 'pipelines'">
            <section class="devops-panel">
              <div class="panel-head">
                <div>
                  <span class="panel-kicker">Pipeline</span>
                  <h2>流水线</h2>
                </div>
                <span class="panel-count">由当前应用状态推导</span>
              </div>
              <div class="pipeline-board">
                <article v-for="stage in pipelineStages" :key="stage.key" class="pipeline-stage" :class="stage.state">
                  <span class="stage-icon"><component :is="stage.icon" /></span>
                  <strong>{{ stage.title }}</strong>
                  <p>{{ stage.description }}</p>
                </article>
              </div>
            </section>
          </template>

          <template v-else-if="active === 'runs'">
            <section class="devops-panel">
              <div class="panel-head">
                <div>
                  <span class="panel-kicker">Runs</span>
                  <h2>运行历史</h2>
                </div>
                <span class="panel-count">{{ runRows.length }} 条</span>
              </div>
              <div class="table-wrap">
                <table class="devops-table">
                  <thead>
                    <tr>
                      <th>任务</th>
                      <th>类型</th>
                      <th>状态</th>
                      <th>分支 / SPEC</th>
                      <th>时间</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in runRows" :key="row.id">
                      <td><strong>{{ row.title }}</strong></td>
                      <td>{{ row.kind }}</td>
                      <td><span class="status-badge" :class="row.statusClass">{{ row.statusText }}</span></td>
                      <td><code>{{ row.ref }}</code></td>
                      <td>{{ row.time }}</td>
                    </tr>
                    <tr v-if="!runRows.length">
                      <td colspan="5">
                        <div class="empty-state table-empty">
                          <strong>暂无运行记录</strong>
                          <p>后续接入部署执行器后，这里可以展示真实 pipeline run。</p>
                        </div>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>
          </template>

          <template v-else-if="active === 'envs'">
            <section class="env-grid">
              <article class="devops-panel env-card current">
                <span class="panel-kicker">Current Binding</span>
                <h2>{{ selectedApp?.env_name || '未绑定平台环境' }}</h2>
                <p>{{ selectedApp?.env_status || '当前应用还没有可读的环境状态。' }}</p>
                <button class="devops-button" type="button" @click="router.push('/platform-envs?tab=envs')">
                  管理环境
                </button>
              </article>
              <article v-if="platformEnvs.length === 0 && !loadingEnvs" class="devops-panel env-card env-empty">
                <strong>当前 tenant 暂无平台环境</strong>
                <p>到「设置 → 环境」添加得帆云平台地址 + 凭证后，应用就能部署到这些环境。</p>
                <button class="devops-button" type="button" @click="router.push('/platform-envs?tab=envs')">
                  添加环境
                </button>
              </article>
              <article
                v-for="env in platformEnvs"
                :key="env.id"
                class="devops-panel env-card"
                :class="{ active: env.is_default }"
              >
                <div class="env-title">
                  <strong>{{ env.env_name }}</strong>
                  <span
                    class="builder-dot"
                    :class="{
                      ok: env.status === 'connected',
                      warn: env.status !== 'connected',
                    }"
                    :title="env.status"
                  />
                </div>
                <p>
                  <code class="env-url">{{ env.base_url }}</code>
                </p>
                <p class="env-meta">
                  {{ env.is_default ? '默认环境' : '' }}
                  <span v-if="env.is_default && env.status === 'connected'"> · </span>
                  {{ env.status === 'connected' ? '已连接' : '未连接' }}
                </p>
              </article>
            </section>
          </template>

          <template v-else-if="active === 'approvals'">
            <section class="devops-panel">
              <div class="panel-head">
                <div>
                  <span class="panel-kicker">Approvals · 全租户</span>
                  <h2>审批中心</h2>
                </div>
                <div class="panel-actions">
                  <span class="panel-count">{{ approvalRows.length }} 条</span>
                  <button
                    class="devops-button ghost"
                    type="button"
                    :disabled="loadingApprovals"
                    @click="loadApprovals"
                  >{{ loadingApprovals ? '刷新中…' : '刷新' }}</button>
                </div>
              </div>
              <div v-if="approvalRows.length" class="approval-list">
                <button
                  v-for="proposal in approvalRows"
                  :key="proposal.id"
                  class="approval-row global"
                  type="button"
                  @click="goToProposal(proposal.id)"
                >
                  <span class="status-badge" :class="`status-${proposal.status}`">
                    {{ STATUS_DISPLAY_NAMES[proposal.status] || proposal.status }}
                  </span>
                  <div class="approval-row-main">
                    <strong>{{ proposal.title }}</strong>
                    <small>
                      <span v-if="proposal.app_name" class="approval-app">{{ proposal.app_name }}</span>
                      <span>{{ formatDate(proposal.created_at) }}</span>
                    </small>
                  </div>
                </button>
              </div>
              <div v-else-if="loadingApprovals" class="empty-state">
                <strong>正在加载…</strong>
              </div>
              <div v-else class="empty-state">
                <strong>没有待处理审批</strong>
                <p>当前 tenant 下还没有待评审、需修改或已批准未 apply 的提案。在左侧任一应用「+ 创建提案」即可看到。</p>
              </div>
            </section>
          </template>
        </section>
      </div>
    </main>

    <!-- 创建提案 dialog -->
    <BaseDialog
      :visible="proposalDialogVisible"
      title="创建提案"
      :confirm-text="creatingProposal ? '创建中…' : '创建提案'"
      cancel-text="取消"
      @confirm="submitCreateProposal"
      @cancel="closeCreateProposalDialog"
    >
      <p class="dialog-hint">
        把当前应用最新的 SPEC draft 作为提案发布。后端会自动跑第一道门校验，校验通过即进入审批流程。
      </p>
      <label class="dialog-field">
        <span>提案标题</span>
        <input
          v-model="proposalForm.title"
          class="dialog-input"
          placeholder="如：为 X 模块加 Y 字段"
          maxlength="200"
          :disabled="creatingProposal"
          @keydown.enter="submitCreateProposal"
        />
      </label>
      <label class="dialog-field">
        <span>简要说明（可选）</span>
        <textarea
          v-model="proposalForm.description"
          class="dialog-input dialog-textarea"
          placeholder="说一下这次变更的目的、影响范围或验收点"
          rows="4"
          :disabled="creatingProposal"
        ></textarea>
      </label>
    </BaseDialog>
  </BuilderFrame>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import type { Component } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Check,
  Files,
  Link as LinkIcon,
  Monitor,
  Operation,
  Promotion,
  Refresh,
  Warning,
} from '@element-plus/icons-vue'
import BuilderFrame from '@/components/BuilderFrame.vue'
import BaseDialog from '@/components/BaseDialog.vue'
import { applicationApi } from '@/api/application'
import { gitConnectionApi, type DriftStatus } from '@/api/gitConnection'
import { platformEnvApi, type PlatformEnv } from '@/api/platformEnv'
import { proposalsApi } from '@/api/proposals'
import type { MergedApplication } from '@/types'
import { type ProposalStatus, type ProposalSummary, STATUS_DISPLAY_NAMES } from '@/types/proposal'

type NavKey = 'overview' | 'proposals' | 'apply-history' | 'git-repo' | 'pipelines' | 'runs' | 'envs' | 'approvals'
type StatusFilter = ProposalStatus | 'all'
type StepState = 'done' | 'active' | 'waiting' | 'warning'

interface NavItem {
  key: NavKey
  label: string
  description: string
  icon: Component
}

interface PipelineStage {
  key: string
  title: string
  description: string
  icon: Component
  state: StepState
}

interface RunRow {
  id: string
  title: string
  kind: string
  statusText: string
  statusClass: string
  ref: string
  time: string
  tone: 'ok' | 'warn' | 'err' | 'neutral'
}

const route = useRoute()
const router = useRouter()

const nav: NavItem[] = [
  { key: 'overview', label: '总览', description: '交付状态与阻塞点', icon: Operation },
  { key: 'proposals', label: '提案', description: '评审应用变更', icon: Promotion },
  { key: 'apply-history', label: 'Apply 历史', description: '已落库的变更', icon: Files },
  { key: 'git-repo', label: 'Git 仓库', description: '仓库与漂移状态', icon: LinkIcon },
  { key: 'pipelines', label: '流水线', description: '从提案到发布', icon: Operation },
  { key: 'runs', label: '运行历史', description: '审计与执行记录', icon: Files },
  { key: 'envs', label: '环境拓扑', description: '平台环境绑定', icon: Monitor },
  { key: 'approvals', label: '审批中心', description: '待处理事项', icon: Check },
]

const routeTab = String(route.query.tab || 'overview')
const active = ref<NavKey>(isNavKey(routeTab) ? routeTab : 'overview')
const appOptions = ref<Array<{ id: number; app_name: string }>>([])
const appsCache = ref<MergedApplication[]>([])
const selectedApplicationId = ref<number | null>(null)
const proposals = ref<ProposalSummary[]>([])
const driftStatus = ref<DriftStatus | null>(null)
const loading = ref(false)
const driftLoading = ref(false)
const initializingRepo = ref(false)
const statusFilter = ref<StatusFilter>('all')
const ready = ref(false)

const statusFilters: Array<{ key: StatusFilter; label: string }> = [
  { key: 'all', label: '全部' },
  { key: 'open', label: '待评审' },
  { key: 'changes_requested', label: '需修改' },
  { key: 'approved', label: '已批准' },
  { key: 'apply_failed', label: '失败' },
  { key: 'applied', label: '已 Apply' },
  { key: 'closed', label: '已关闭' },
]

const currentNav = computed(() => nav.find(item => item.key === active.value) ?? nav[0])
const currentLabel = computed(() => currentNav.value.label)
const currentDescription = computed(() => currentNav.value.description)
const currentKicker = computed(() => {
  if (active.value === 'git-repo') return 'Repository'
  if (active.value === 'pipelines') return 'Pipeline'
  if (active.value === 'runs') return 'Runs'
  return 'DevOps'
})

const selectedApp = computed(() => {
  if (!selectedApplicationId.value) return null
  return appsCache.value.find(app => Number(app.id) === selectedApplicationId.value) ?? null
})

const selectedProjectId = computed(() => selectedApp.value?.project_id ?? null)
const selectedAppName = computed(() => selectedApp.value?.app_name || '未选择应用')
const selectedAppMeta = computed(() => {
  if (!selectedApp.value) return '暂无可用应用'
  const app = selectedApp.value
  const parts = [
    app.status ? `状态 ${app.status}` : '',
    app.env_name ? `环境 ${app.env_name}` : '',
    app.updated_at ? `更新 ${formatDate(app.updated_at)}` : '',
  ].filter(Boolean)
  return parts.join(' · ') || app.app_code || '应用信息待补充'
})

const hasGitRepo = computed(() => Boolean(selectedApp.value?.git_repo_url))
/** 能否创建提案：选中应用即可（draft 是否存在由后端 promote 时校验，无 draft 返回 422 由前端 toast 提示） */
const canCreateProposal = computed(() => Boolean(selectedApp.value))
const openReviewCount = computed(() => proposals.value.filter(p => p.status === 'open').length)
const approvedCount = computed(() => proposals.value.filter(p => p.status === 'approved').length)
const appliedCount = computed(() => proposals.value.filter(p => p.status === 'applied').length)
const actionableProposalCount = computed(() =>
  proposals.value.filter(p => ['open', 'changes_requested', 'approved', 'apply_failed'].includes(p.status)).length
)
/** 全局待处理审批（跨应用，actionable=true）；进入 approvals tab 自动加载 */
const globalApprovals = ref<Array<ProposalSummary & { application_id: number; app_name?: string; app_code?: string }>>([])
const loadingApprovals = ref(false)
const approvalRows = computed(() => globalApprovals.value)

const filteredProposals = computed(() => {
  const rows = statusFilter.value === 'all'
    ? proposals.value
    : proposals.value.filter(p => p.status === statusFilter.value)
  return [...rows].sort((a, b) => {
    const at = new Date(a.created_at || 0).getTime()
    const bt = new Date(b.created_at || 0).getTime()
    return bt - at
  })
})

const appliedProposals = computed(() =>
  proposals.value
    .filter(p => p.status === 'applied')
    .slice()
    .sort((a, b) => new Date(b.applied_at || 0).getTime() - new Date(a.applied_at || 0).getTime())
)

const gitStatusLabel = computed(() => {
  if (!selectedApp.value) return '未选择'
  if (!hasGitRepo.value) return '未初始化'
  if (driftStatus.value?.drift) return '存在漂移'
  if (driftStatus.value?.drift === false) return '已同步'
  return '已绑定'
})

const gitStatusHint = computed(() => {
  if (!selectedApp.value) return '请先选择应用'
  if (!selectedProjectId.value) return '应用尚未归属项目，无法接入 Git'
  if (!hasGitRepo.value) return '可从 Git 设置初始化应用仓库'
  if (driftStatus.value?.drift) return 'Git HEAD 与 Builder canonical SPEC 不一致'
  if (driftStatus.value?.reason) return driftStatus.value.reason
  return selectedApp.value.git_default_branch || 'main'
})

const gitBadgeClass = computed(() => {
  if (!hasGitRepo.value) return 'status-draft'
  if (driftStatus.value?.drift) return 'status-changes_requested'
  if (driftStatus.value?.drift === false) return 'status-applied'
  return 'status-open'
})

const driftStatusText = computed(() => {
  if (!hasGitRepo.value) return '仓库初始化后可检测'
  if (driftLoading.value) return '检测中'
  if (!driftStatus.value) return '尚未检测'
  if (driftStatus.value.drift) return `有漂移：Git ${shortSha(driftStatus.value.git_sha)} / Builder ${shortSha(driftStatus.value.builder_sha)}`
  if (driftStatus.value.drift === false) return `一致：${shortSha(driftStatus.value.git_sha || driftStatus.value.builder_sha)}`
  return driftStatus.value.reason || '未返回漂移结果'
})

const deliveryStateLabel = computed(() => {
  if (!selectedApp.value) return '待选择'
  if (approvedCount.value > 0) return '待 Apply'
  if (openReviewCount.value > 0) return '待评审'
  if (appliedCount.value > 0 && hasGitRepo.value) return '可发布'
  if (!hasGitRepo.value) return '待接 Git'
  return '空闲'
})

const latestActivityLabel = computed(() => {
  const latest = [...proposals.value].sort((a, b) => {
    const at = new Date(a.applied_at || a.created_at || 0).getTime()
    const bt = new Date(b.applied_at || b.created_at || 0).getTime()
    return bt - at
  })[0]
  if (!latest) return '暂无提案活动'
  const time = latest.applied_at || latest.created_at
  return `${STATUS_DISPLAY_NAMES[latest.status]} · ${formatDate(time)}`
})

const deliverySteps = computed(() => [
  {
    key: 'proposal',
    index: '01',
    title: '变更提案',
    description: proposals.value.length ? `${proposals.value.length} 个 proposal 已进入 DevOps 队列` : '暂无可交付变更',
    label: proposals.value.length ? '已进入' : '等待',
    state: proposals.value.length ? 'done' : 'waiting',
  },
  {
    key: 'review',
    index: '02',
    title: '评审审批',
    description: openReviewCount.value
      ? `${openReviewCount.value} 个 proposal 等待评审`
      : approvedCount.value || appliedCount.value
        ? '评审链路已通过'
        : '暂无待评审事项',
    label: openReviewCount.value ? '进行中' : approvedCount.value || appliedCount.value ? '通过' : '等待',
    state: openReviewCount.value ? 'active' : approvedCount.value || appliedCount.value ? 'done' : 'waiting',
  },
  {
    key: 'apply',
    index: '03',
    title: 'Apply 到 Canonical',
    description: approvedCount.value
      ? `${approvedCount.value} 个已批准 proposal 可以执行 apply`
      : appliedCount.value
        ? `${appliedCount.value} 个变更已落库`
        : '等待已批准变更',
    label: approvedCount.value ? '待执行' : appliedCount.value ? '完成' : '等待',
    state: approvedCount.value ? 'active' : appliedCount.value ? 'done' : 'waiting',
  },
  {
    key: 'git',
    index: '04',
    title: 'Git 同步',
    description: hasGitRepo.value ? gitStatusHint.value : '仓库未初始化，无法沉淀分支与 tag',
    label: hasGitRepo.value ? gitStatusLabel.value : '未接入',
    state: driftStatus.value?.drift ? 'warning' : hasGitRepo.value ? 'done' : 'waiting',
  },
] as Array<{ key: string; index: string; title: string; description: string; label: string; state: StepState }>)

const pipelineStages = computed<PipelineStage[]>(() => [
  {
    key: 'spec',
    title: 'SPEC 回灌',
    description: proposals.value.length ? '已有变更进入 proposal 阶段' : '等待 AI Builder 生成变更提案',
    icon: Files,
    state: proposals.value.length ? 'done' : 'waiting',
  },
  {
    key: 'review',
    title: '评审审批',
    description: openReviewCount.value ? `${openReviewCount.value} 个 proposal 待评审` : '无阻塞审批',
    icon: Check,
    state: openReviewCount.value ? 'active' : 'done',
  },
  {
    key: 'apply',
    title: 'Apply 执行',
    description: approvedCount.value ? `${approvedCount.value} 个已批准变更待 apply` : `${appliedCount.value} 个变更已执行`,
    icon: Operation,
    state: approvedCount.value ? 'active' : appliedCount.value ? 'done' : 'waiting',
  },
  {
    key: 'git',
    title: 'Git 沉淀',
    description: hasGitRepo.value ? gitStatusHint.value : '待初始化仓库',
    icon: LinkIcon,
    state: driftStatus.value?.drift ? 'warning' : hasGitRepo.value ? 'done' : 'waiting',
  },
  {
    key: 'deploy',
    title: '发布环境',
    description: selectedApp.value?.env_name ? `目标环境 ${selectedApp.value.env_name}` : '等待平台环境绑定',
    icon: Monitor,
    state: selectedApp.value?.env_name ? 'done' : 'waiting',
  },
])

const runRows = computed<RunRow[]>(() =>
  [...proposals.value]
    .sort((a, b) => {
      const at = new Date(a.applied_at || a.created_at || 0).getTime()
      const bt = new Date(b.applied_at || b.created_at || 0).getTime()
      return bt - at
    })
    .map(proposal => {
      const isApplied = proposal.status === 'applied'
      const failed = proposal.status === 'apply_failed'
      return {
        id: proposal.id,
        title: proposal.title,
        kind: isApplied || failed ? 'Apply' : 'Proposal',
        statusText: STATUS_DISPLAY_NAMES[proposal.status] || proposal.status,
        statusClass: `status-${proposal.status}`,
        ref: isApplied ? proposal.draft_spec_id : `spec/proposal-${proposal.id.slice(0, 8)}`,
        time: formatDate(proposal.applied_at || proposal.created_at),
        tone: failed ? 'err' : isApplied ? 'ok' : proposal.status === 'approved' ? 'warn' : 'neutral',
      }
    })
)

function isNavKey(value: string): value is NavKey {
  return nav.some(item => item.key === value)
}

function selectTab(key: NavKey) {
  active.value = key
}

function navBadge(key: NavKey): number | null {
  if (key === 'proposals') return proposals.value.length
  if (key === 'apply-history') return appliedProposals.value.length
  if (key === 'approvals') return approvalRows.value.length
  if (key === 'git-repo') return hasGitRepo.value ? 1 : 0
  return null
}

function countByStatus(key: StatusFilter): number {
  if (key === 'all') return proposals.value.length
  return proposals.value.filter(p => p.status === key).length
}

function formatDate(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function shortSha(value?: string | null): string {
  if (!value) return '—'
  return value.slice(0, 8)
}

function syncQuery(next: Partial<Record<string, string>>) {
  router.replace({
    query: {
      ...route.query,
      ...next,
    },
  }).catch(() => {
    // Ignore NavigationDuplicated style failures.
  })
}

async function loadApps() {
  const apps = await applicationApi.list()
  appsCache.value = apps
  appOptions.value = apps
    .map(app => ({ id: Number(app.id), app_name: app.app_name }))
    .filter(app => Number.isFinite(app.id) && app.id > 0)

  const queryAppId = Number(route.query.application_id)
  const nextAppId = appOptions.value.find(app => app.id === queryAppId)?.id ?? appOptions.value[0]?.id ?? null
  selectedApplicationId.value = nextAppId
}

async function loadProposals() {
  if (!selectedApplicationId.value) {
    proposals.value = []
    return
  }
  proposals.value = await proposalsApi.list(selectedApplicationId.value)
}

/** 平台环境列表（环境拓扑 tab 用） */
const platformEnvs = ref<PlatformEnv[]>([])
const loadingEnvs = ref(false)
async function loadPlatformEnvs() {
  loadingEnvs.value = true
  try {
    const list = await platformEnvApi.list()
    platformEnvs.value = Array.isArray(list) ? list : []
  } catch (error) {
    console.error('Load platform envs failed', error)
    platformEnvs.value = []
  } finally {
    loadingEnvs.value = false
  }
}

/** 跨应用审批中心：拉所有 actionable 的提案 */
async function loadApprovals() {
  loadingApprovals.value = true
  try {
    const list = await proposalsApi.listAll({ actionable: true })
    globalApprovals.value = Array.isArray(list) ? list : []
  } catch (error) {
    console.error('Load approvals failed', error)
    globalApprovals.value = []
  } finally {
    loadingApprovals.value = false
  }
}

async function loadDriftStatus() {
  if (!selectedApplicationId.value || !hasGitRepo.value) {
    driftStatus.value = null
    return
  }
  driftLoading.value = true
  try {
    driftStatus.value = await gitConnectionApi.driftStatus(selectedApplicationId.value)
  } catch (error) {
    console.error('Load drift status failed', error)
    driftStatus.value = null
  } finally {
    driftLoading.value = false
  }
}

async function refreshCurrentApp() {
  await loadProposals()
  await loadDriftStatus()
}

async function refreshAll() {
  loading.value = true
  try {
    await loadApps()
    await refreshCurrentApp()
  } catch (error) {
    console.error('Refresh DevOps page failed', error)
    ElMessage.error('刷新 DevOps 数据失败')
  } finally {
    loading.value = false
  }
}

async function initRepo() {
  if (!selectedApplicationId.value || hasGitRepo.value) return
  initializingRepo.value = true
  try {
    await gitConnectionApi.initRepo(selectedApplicationId.value)
    ElMessage.success('Git 仓库已初始化')
    await refreshAll()
  } catch (error) {
    console.error('Init repo failed', error)
    ElMessage.error('初始化失败，请先确认项目已绑定 Git Token')
  } finally {
    initializingRepo.value = false
  }
}

const creatingProposal = ref(false)

// 左侧二级导航收起（与 SessionSidebar 体验一致）
const SIDE_COLLAPSED_KEY = 'devops:side-collapsed'
const sideCollapsed = ref<boolean>(localStorage.getItem(SIDE_COLLAPSED_KEY) === '1')
function toggleSide() {
  sideCollapsed.value = !sideCollapsed.value
  try { localStorage.setItem(SIDE_COLLAPSED_KEY, sideCollapsed.value ? '1' : '0') } catch { /* ignore */ }
}

/** 创建提案：BaseDialog 单页表单 — 同屏填 title + description */
const proposalDialogVisible = ref(false)
const proposalForm = ref({ title: '', description: '' })

function openCreateProposal() {
  if (!selectedApplicationId.value) {
    ElMessage.warning('请先选择应用')
    return
  }
  proposalForm.value = {
    title: `${selectedAppName.value} - 变更提案`,
    description: '',
  }
  proposalDialogVisible.value = true
}

function closeCreateProposalDialog() {
  if (creatingProposal.value) return
  proposalDialogVisible.value = false
}

async function submitCreateProposal() {
  if (creatingProposal.value || !selectedApplicationId.value) return
  const title = proposalForm.value.title.trim()
  if (!title) {
    ElMessage.warning('标题不能为空')
    return
  }
  const description = proposalForm.value.description.trim()
  creatingProposal.value = true
  try {
    const res = await proposalsApi.promote(selectedApplicationId.value, {
      title,
      description: description || undefined,
    })
    proposalDialogVisible.value = false
    ElMessage.success(`提案已创建（${STATUS_DISPLAY_NAMES[res.status as ProposalStatus] || res.status}）`)
    selectTab('proposals')
    await loadProposals()
    if (res.id) {
      router.push(`/proposals/${res.id}`).catch(() => {})
    }
  } catch (error: any) {
    const detail = error?.response?.data?.detail
    ElMessage.error(detail || error?.message || '提案创建失败')
  } finally {
    creatingProposal.value = false
  }
}

function onAppChange() {
  if (!ready.value) return
  syncQuery({ application_id: selectedApplicationId.value ? String(selectedApplicationId.value) : '' })
  refreshCurrentApp().catch(error => {
    console.error('Reload selected app failed', error)
    ElMessage.error('加载应用 DevOps 数据失败')
  })
}

function goToProposal(id: string) {
  router.push(`/proposals/${id}`)
}

function goToProjectGit() {
  if (!selectedProjectId.value) {
    ElMessage.warning('当前应用尚未归属项目')
    return
  }
  router.push(`/project/${selectedProjectId.value}/git`)
}

function goToBuilder() {
  if (!selectedApplicationId.value) return
  const app = selectedApp.value
  const isGenerated = !!(app?.apaas_app_id || app?.local_status === 'completed' || app?.status === 'completed')
  const query: Record<string, string> = { app_id: String(selectedApplicationId.value) }
  if (isGenerated) {
    query.tab = 'spec'
    query.workspace = 'update'
  }
  router.push({ path: '/chat', query }).catch(() => {})
}

function goToApps() {
  router.push('/apps').catch(() => {})
}

watch(active, tab => {
  syncQuery({ tab })
  if (tab === 'approvals') loadApprovals()
  if (tab === 'envs') loadPlatformEnvs()
})

watch(() => route.query.tab, value => {
  const next = String(value || 'overview')
  if (isNavKey(next) && next !== active.value) {
    active.value = next
  }
})

watch(selectedApplicationId, () => {
  if (ready.value) onAppChange()
})

onMounted(async () => {
  loading.value = true
  // 1) 先单独加载应用列表 — 失败时区分"后端未连接 vs 接口报错"，不阻塞页面渲染
  try {
    await loadApps()
  } catch (error: any) {
    console.error('Load applications failed', error)
    const status = error?.response?.status
    const detail = error?.response?.data?.detail
    if (!status) {
      ElMessage.error({
        message: '后端未连接 — 请确认 backend dev server 已启动',
        duration: 5000,
      })
    } else if (status >= 500) {
      ElMessage.error({
        message: `后端报错（${status}）：${detail || '请查看 backend 日志'}`,
        duration: 5000,
      })
    } else {
      ElMessage.warning(detail || `加载应用列表失败（${status}）`)
    }
    appOptions.value = []
    appsCache.value = []
  }
  ready.value = true
  // 全局审批中心数据后台拉，无需阻塞
  loadApprovals()
  // 2) 选了应用才尝试加载 proposal/git；失败也不阻塞主流程
  if (selectedApplicationId.value) {
    try {
      await refreshCurrentApp()
    } catch (error) {
      console.error('Refresh current app failed', error)
      ElMessage.warning('该应用的提案/Git 数据加载失败，可点右上角刷新重试')
    }
  }
  loading.value = false
})
</script>

<style scoped>
.devops-page {
  padding: 28px 32px;
}

.devops-shell {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  gap: 28px;
  max-width: 1480px;
  margin: 0 auto;
}

.devops-side {
  min-height: calc(100vh - 118px);
  padding: 14px 12px;
  background: color-mix(in srgb, var(--b-panel) 74%, var(--b-bg-sub));
  border-right: 1px solid var(--b-line);
  width: 240px;
  flex-shrink: 0;
  transition: width 0.18s ease;
}
.devops-side.collapsed {
  width: 60px;
  padding: 14px 8px;
}
.side-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  padding: 0 6px;
}
.side-collapse-btn {
  background: transparent;
  border: none;
  color: var(--b-text-faint);
  font-size: 14px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 6px;
  line-height: 1;
}
.side-collapse-btn:hover {
  background: color-mix(in srgb, var(--b-text) 6%, transparent);
  color: var(--b-text);
}
.devops-side.collapsed .side-head {
  justify-content: center;
}
.devops-side.collapsed .side-link {
  grid-template-columns: 20px auto;
  padding: 10px 8px;
  min-height: 44px;
  justify-content: center;
}
.devops-side.collapsed .nav-count {
  position: absolute;
  top: 4px;
  right: 4px;
  min-width: 16px;
  height: 16px;
  font-size: 10px;
}
.devops-side.collapsed .side-link {
  position: relative;
}

.side-eyebrow,
.builder-section-kicker,
.panel-kicker,
.summary-label {
  color: var(--b-text-faint);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: uppercase;
}

.side-eyebrow {
  padding: 0 14px 12px;
}

.side-link {
  width: 100%;
  min-height: 54px;
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  padding: 10px 12px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--b-text-muted);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}

.side-link:hover {
  background: color-mix(in srgb, var(--b-text) 6%, transparent);
  color: var(--b-text);
}

.side-link.active {
  background: var(--b-brand-soft);
  border-color: color-mix(in srgb, var(--b-brand) 16%, transparent);
  color: var(--b-brand-ink);
}

.side-icon {
  width: 16px;
  height: 16px;
}

.side-copy {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.side-copy strong {
  color: currentColor;
  font-size: 14px;
  line-height: 1.2;
}

.side-copy small {
  color: var(--b-text-faint);
  font-size: 11px;
  line-height: 1.2;
}

.nav-count {
  min-width: 22px;
  height: 20px;
  display: inline-grid;
  place-items: center;
  padding: 0 6px;
  border-radius: 999px;
  background: var(--b-panel);
  color: var(--b-text-muted);
  font-size: 11px;
  font-weight: 700;
  box-shadow: var(--b-shadow-xs);
}

.devops-main {
  min-width: 0;
}

.devops-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 18px;
  margin-bottom: 18px;
}

.header-copy h1 {
  margin: 6px 0 4px;
  color: var(--b-text);
  font-size: 28px;
  line-height: 1.14;
}

.header-copy p {
  margin: 0;
  color: var(--b-text-muted);
  font-size: 14px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.mvp-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
  padding: 10px 12px;
  border: 1px solid color-mix(in srgb, var(--b-brand) 18%, var(--b-line));
  border-radius: 8px;
  background: color-mix(in srgb, var(--b-brand-soft) 60%, var(--b-panel));
  color: var(--b-text-muted);
  font-size: 13px;
  line-height: 1.5;
}

.mvp-banner strong {
  flex: 0 0 auto;
  color: var(--b-brand-ink);
  font-size: 13px;
}

.mvp-banner span {
  min-width: 0;
}

.app-select {
  height: 34px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 0 10px;
  border: 1px solid var(--b-line);
  border-radius: 8px;
  background: var(--b-panel);
  color: var(--b-text-muted);
  font-size: 12px;
  box-shadow: var(--b-shadow-xs);
}

.app-select select {
  min-width: 180px;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--b-text);
  font: inherit;
}

.devops-button,
.row-action {
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  padding: 0 12px;
  border: 1px solid var(--b-line);
  border-radius: 8px;
  background: var(--b-panel);
  color: var(--b-text);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease, opacity 0.15s ease;
}

.devops-button svg,
.row-action svg {
  width: 14px;
  height: 14px;
}

.devops-button:hover,
.row-action:hover {
  background: var(--b-bg-sub);
  border-color: var(--b-line-strong);
}

.devops-button.primary {
  border-color: var(--b-brand);
  background: var(--b-brand);
  color: #fff;
}

.devops-button.ghost {
  background: transparent;
}

.devops-button:disabled,
.row-action:disabled {
  cursor: not-allowed;
  opacity: 0.48;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.summary-card {
  min-height: 112px;
  padding: 16px;
  border: 1px solid var(--b-line);
  border-radius: 8px;
  background: var(--b-panel);
  box-shadow: var(--b-shadow-xs);
}

.summary-card.selected {
  background: linear-gradient(180deg, color-mix(in srgb, var(--b-brand-soft) 70%, var(--b-panel)), var(--b-panel));
}

.summary-card strong {
  display: block;
  margin-top: 8px;
  color: var(--b-text);
  font-size: 22px;
  line-height: 1.2;
}

.summary-card p {
  margin: 7px 0 0;
  color: var(--b-text-muted);
  font-size: 12px;
  line-height: 1.5;
}

.card-quick-links {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.card-quick-links .quick-link {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 3px 9px;
  border: 1px solid var(--b-line);
  border-radius: 999px;
  background: var(--b-panel);
  color: var(--b-text-muted);
  font-size: 11px;
  cursor: pointer;
  text-decoration: none;
  transition: border-color 0.14s, color 0.14s, background 0.14s;
}
.card-quick-links .quick-link:hover {
  border-color: var(--b-brand);
  color: var(--b-brand-ink);
  background: var(--b-brand-soft);
}

.overview-layout,
.git-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(320px, 0.8fr);
  gap: 16px;
}

.devops-panel {
  border: 1px solid var(--b-line);
  border-radius: 8px;
  background: var(--b-panel);
  box-shadow: var(--b-shadow-xs);
  overflow: hidden;
}

.primary-panel {
  min-height: 420px;
}

.panel-head {
  min-height: 68px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 18px;
  border-bottom: 1px solid var(--b-line);
}

.panel-head h2 {
  margin: 4px 0 0;
  color: var(--b-text);
  font-size: 17px;
  line-height: 1.3;
}

.panel-count {
  color: var(--b-text-muted);
  font-size: 12px;
}

.delivery-steps {
  display: grid;
  gap: 12px;
  margin: 0;
  padding: 18px;
  list-style: none;
}

.delivery-steps li {
  display: grid;
  grid-template-columns: 48px minmax(0, 1fr) auto;
  gap: 14px;
  align-items: center;
  padding: 14px;
  border: 1px solid var(--b-line);
  border-radius: 8px;
  background: var(--b-panel-soft);
}

.step-index {
  width: 40px;
  height: 40px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  background: var(--b-bg-sub);
  color: var(--b-text-muted);
  font-family: var(--b-mono);
  font-size: 12px;
}

.delivery-steps strong {
  color: var(--b-text);
  font-size: 14px;
}

.delivery-steps p {
  margin: 4px 0 0;
  color: var(--b-text-muted);
  font-size: 12px;
}

.step-state {
  padding: 4px 8px;
  border-radius: 999px;
  background: var(--b-bg-sub);
  color: var(--b-text-muted);
  font-size: 12px;
}

.step-done .step-index,
.step-done .step-state {
  background: var(--b-teal-soft);
  color: var(--b-teal);
}

.step-active .step-index,
.step-active .step-state {
  background: var(--b-brand-soft);
  color: var(--b-brand-ink);
}

.step-warning .step-index,
.step-warning .step-state {
  background: var(--b-warn-soft);
  color: var(--b-warn);
}

.activity-list {
  display: grid;
  padding: 8px;
}

.activity-row,
.approval-row {
  width: 100%;
  display: grid;
  align-items: center;
  gap: 10px;
  padding: 11px 10px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--b-text);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.activity-row {
  grid-template-columns: 10px minmax(0, 1fr);
}

.approval-row.global {
  grid-template-columns: auto minmax(0, 1fr);
}
.approval-row-main {
  min-width: 0;
}
.approval-row-main small {
  display: inline-flex;
  gap: 8px;
  align-items: center;
}
.approval-app {
  display: inline-block;
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--b-brand-soft);
  color: var(--b-brand-ink);
  font-size: 11px;
  font-weight: 700;
}

.panel-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.activity-row:hover,
.approval-row:hover {
  background: var(--b-bg-sub);
}

.activity-row strong,
.approval-row strong {
  display: block;
  overflow: hidden;
  color: var(--b-text);
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.activity-row small,
.approval-row small {
  display: block;
  margin-top: 3px;
  color: var(--b-text-muted);
  font-size: 12px;
}

.activity-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: var(--b-text-faint);
}

.activity-dot.ok { background: var(--b-teal); }
.activity-dot.warn { background: var(--b-warn); }
.activity-dot.err { background: var(--b-red); }

.status-filter {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
}

.status-filter button {
  height: 28px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 9px;
  border: 1px solid var(--b-line);
  border-radius: 999px;
  background: transparent;
  color: var(--b-text-muted);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.status-filter button.active {
  border-color: var(--b-brand);
  background: var(--b-brand-soft);
  color: var(--b-brand-ink);
}

.table-wrap {
  overflow: auto;
}

.devops-table {
  width: 100%;
  border-collapse: collapse;
}

.devops-table th,
.devops-table td {
  padding: 13px 16px;
  border-bottom: 1px solid var(--b-line);
  color: var(--b-text);
  font-size: 13px;
  text-align: left;
  vertical-align: middle;
}

.devops-table th {
  background: var(--b-panel-soft);
  color: var(--b-text-muted);
  font-weight: 600;
}

.devops-table td small {
  display: block;
  margin-top: 3px;
  color: var(--b-text-faint);
  font-family: var(--b-mono);
  font-size: 11px;
}

.devops-table code {
  font-family: var(--b-mono);
  font-size: 12px;
  color: var(--b-text-muted);
}

.status-badge {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--b-bg-sub);
  color: var(--b-text-muted);
  font-size: 12px;
  white-space: nowrap;
}

.status-draft,
.status-closed {
  background: var(--b-bg-sub);
  color: var(--b-text-muted);
}

.status-open,
.status-applying {
  background: var(--b-brand-soft);
  color: var(--b-brand-ink);
}

.status-changes_requested,
.status-approved {
  background: var(--b-warn-soft);
  color: var(--b-warn);
}

.status-applied {
  background: var(--b-teal-soft);
  color: var(--b-teal);
}

.status-apply_failed {
  background: var(--b-red-soft);
  color: var(--b-red);
}

.empty-state {
  padding: 42px 18px;
  color: var(--b-text-muted);
  text-align: center;
}

.empty-state.compact {
  padding: 32px 16px;
}

.empty-state.table-empty {
  padding: 28px 16px;
}

.empty-state strong {
  display: block;
  color: var(--b-text);
  font-size: 14px;
}

.empty-state p {
  max-width: 420px;
  margin: 8px auto 0;
  font-size: 13px;
  line-height: 1.6;
}

.timeline {
  margin: 0;
  padding: 16px 18px;
  list-style: none;
}

.timeline li {
  display: grid;
  grid-template-columns: 14px minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  padding: 12px 0;
  border-bottom: 1px solid var(--b-line);
}

.timeline li:last-child {
  border-bottom: 0;
}

.timeline-dot {
  width: 9px;
  height: 9px;
  border-radius: 999px;
  background: var(--b-text-faint);
}

.timeline-dot.ok {
  background: var(--b-teal);
}

.timeline strong {
  color: var(--b-text);
  font-size: 14px;
}

.timeline p {
  margin: 4px 0 0;
  color: var(--b-text-muted);
  font-size: 12px;
}

.git-card {
  min-height: 360px;
}

.git-fields {
  display: grid;
  gap: 0;
  margin: 0;
  padding: 4px 18px 14px;
}

.git-fields div {
  display: grid;
  grid-template-columns: 110px minmax(0, 1fr);
  gap: 14px;
  padding: 14px 0;
  border-bottom: 1px solid var(--b-line);
}

.git-fields div:last-child {
  border-bottom: 0;
}

.git-fields dt {
  color: var(--b-text-muted);
  font-size: 12px;
}

.git-fields dd {
  min-width: 0;
  margin: 0;
  color: var(--b-text);
  font-size: 13px;
  word-break: break-word;
}

.git-fields a {
  color: var(--b-brand-ink);
  font-family: var(--b-mono);
  text-decoration: none;
}

.git-fields a:hover {
  text-decoration: underline;
}

.git-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 0 18px 18px;
}

.integration-list {
  display: grid;
  gap: 10px;
  margin: 0;
  padding: 16px 18px 18px;
  list-style: none;
}

.integration-list li {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--b-line);
  border-radius: 8px;
  background: var(--b-panel-soft);
  color: var(--b-text-muted);
  font-size: 13px;
}

.integration-list svg {
  width: 15px;
  height: 15px;
  color: var(--b-text-faint);
}

.integration-list li.done {
  border-color: color-mix(in srgb, var(--b-teal) 22%, var(--b-line));
  background: var(--b-teal-soft);
  color: var(--b-teal);
}

.integration-list li.done svg {
  color: var(--b-teal);
}

.pipeline-board {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
  padding: 18px;
}

.pipeline-stage {
  min-height: 154px;
  padding: 14px;
  border: 1px solid var(--b-line);
  border-radius: 8px;
  background: var(--b-panel-soft);
}

.stage-icon {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  margin-bottom: 12px;
  border-radius: 8px;
  background: var(--b-bg-sub);
  color: var(--b-text-muted);
}

.stage-icon svg {
  width: 17px;
  height: 17px;
}

.pipeline-stage strong {
  color: var(--b-text);
  font-size: 14px;
}

.pipeline-stage p {
  margin: 8px 0 0;
  color: var(--b-text-muted);
  font-size: 12px;
  line-height: 1.55;
}

.pipeline-stage.done .stage-icon {
  background: var(--b-teal-soft);
  color: var(--b-teal);
}

.pipeline-stage.active .stage-icon {
  background: var(--b-brand-soft);
  color: var(--b-brand-ink);
}

.pipeline-stage.warning .stage-icon {
  background: var(--b-warn-soft);
  color: var(--b-warn);
}

.env-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 14px;
}

.env-card {
  padding: 16px;
}

.env-card.current {
  grid-column: span 2;
}

.env-card h2 {
  margin: 8px 0 6px;
  color: var(--b-text);
  font-size: 18px;
}

.env-card p {
  margin: 0 0 14px;
  color: var(--b-text-muted);
  font-size: 13px;
}

.env-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.env-card.active {
  border-color: color-mix(in srgb, var(--b-brand) 30%, var(--b-line));
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--b-brand) 12%, transparent);
}
.env-card.env-empty {
  background: var(--b-bg-sub);
  border-style: dashed;
}
.env-url {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 1px 8px;
  border-radius: 6px;
  background: var(--b-bg-sub);
  color: var(--b-text-muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11.5px;
}
.env-meta {
  margin-top: 4px !important;
  font-size: 11.5px !important;
  color: var(--b-text-faint) !important;
}

.env-title strong {
  color: var(--b-text);
}

.builder-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: var(--b-brand);
}

.builder-dot.ok { background: var(--b-teal); }
.builder-dot.warn { background: var(--b-warn); }

.approval-list {
  display: grid;
  padding: 8px;
}

.approval-row {
  grid-template-columns: auto minmax(0, 1fr) auto;
}

@media (max-width: 1180px) {
  .devops-shell {
    grid-template-columns: 220px minmax(0, 1fr);
  }

  .summary-grid,
  .pipeline-board {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .overview-layout,
  .git-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .devops-page {
    padding: 16px;
  }

  .devops-shell {
    grid-template-columns: 1fr;
  }

  .devops-side {
    min-height: auto;
    border-right: 0;
    border-bottom: 1px solid var(--b-line);
  }

  .devops-header,
  .header-actions,
  .mvp-banner,
  .panel-head {
    align-items: stretch;
    flex-direction: column;
  }

  .summary-grid,
  .pipeline-board,
  .env-grid {
    grid-template-columns: 1fr;
  }

  .env-card.current {
    grid-column: auto;
  }

  .git-fields div,
  .delivery-steps li,
  .approval-row {
    grid-template-columns: 1fr;
  }
}

/* ── 创建提案 dialog 表单样式 ── */
.dialog-hint {
  margin: 0 0 14px;
  padding: 9px 12px;
  background: var(--b-brand-soft, var(--brand-soft, rgba(29, 78, 216, 0.07)));
  border: 1px solid color-mix(in srgb, var(--b-brand) 18%, transparent);
  border-radius: 8px;
  color: var(--b-text-muted);
  font-size: 12px;
  line-height: 1.55;
}
.dialog-field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin-bottom: 12px;
}
.dialog-field span {
  color: var(--b-text);
  font-size: 12px;
  font-weight: 700;
}
.dialog-input {
  width: 100%;
  padding: 9px 12px;
  border: 1px solid var(--b-line);
  border-radius: 8px;
  background: var(--b-panel);
  color: var(--b-text);
  font-family: inherit;
  font-size: 13px;
  line-height: 1.5;
  outline: none;
  transition: border-color 0.14s, box-shadow 0.14s;
}
.dialog-input:focus {
  border-color: color-mix(in srgb, var(--b-brand) 50%, transparent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--b-brand) 18%, transparent);
}
.dialog-input:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.dialog-textarea {
  resize: vertical;
  min-height: 90px;
  font-family: inherit;
}
</style>
