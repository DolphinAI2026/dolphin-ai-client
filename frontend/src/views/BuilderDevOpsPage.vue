<template>
  <BuilderFrame :breadcrumbs="[{ label: 'DevOps' }, { label: currentLabel }]">
    <main class="devops-layout">
      <aside class="devops-side">
        <div class="side-label">DevOps</div>
        <button
          v-for="item in nav"
          :key="item.key"
          class="side-link"
          :class="{ active: active === item.key }"
          type="button"
          @click="active = item.key"
        >
          <component :is="item.icon" />
          {{ item.label }}
        </button>
      </aside>

      <section class="devops-main">
        <div class="builder-section-head">
          <div>
            <div class="builder-section-kicker">{{ kickerText }}</div>
            <h1 class="builder-section-title">{{ currentLabel }}</h1>
            <p class="builder-section-sub">{{ subText }}</p>
          </div>
          <div v-if="appOptions.length > 1 && (active === 'proposals' || active === 'apply-history')" class="app-select">
            <select v-model.number="selectedApplicationId" @change="onAppChange">
              <option v-for="a in appOptions" :key="a.id" :value="a.id">{{ a.app_name }}</option>
            </select>
          </div>
        </div>

        <!-- Proposals tab -->
        <template v-if="active === 'proposals'">
          <section class="builder-panel">
            <div class="status-filter">
              <button
                v-for="s in statusFilters"
                :key="s.key"
                type="button"
                :class="{ active: statusFilter === s.key }"
                @click="statusFilter = s.key"
              >
                {{ s.label }} ({{ countByStatus(s.key) }})
              </button>
            </div>
            <table class="builder-table">
              <thead>
                <tr><th>标题</th><th>状态</th><th>提案者</th><th>创建时间</th><th>操作</th></tr>
              </thead>
              <tbody>
                <tr v-for="p in filteredProposals" :key="p.id">
                  <td><strong>{{ p.title }}</strong></td>
                  <td>
                    <span class="status-badge" :class="`status-${p.status}`">
                      {{ STATUS_DISPLAY_NAMES[p.status] || p.status }}
                    </span>
                  </td>
                  <td>用户 {{ p.created_by }}</td>
                  <td>{{ formatDate(p.created_at) }}</td>
                  <td>
                    <button class="builder-btn" type="button" @click="goToProposal(p.id)">查看</button>
                  </td>
                </tr>
                <tr v-if="!filteredProposals.length">
                  <td colspan="5" class="empty">暂无提案</td>
                </tr>
              </tbody>
            </table>
          </section>
        </template>

        <!-- Apply History tab -->
        <template v-if="active === 'apply-history'">
          <section class="builder-panel">
            <table class="builder-table">
              <thead>
                <tr><th>标题</th><th>提案者</th><th>Apply 时间</th><th>对应 SPEC</th></tr>
              </thead>
              <tbody>
                <tr v-for="p in appliedProposals" :key="p.id">
                  <td><strong>{{ p.title }}</strong></td>
                  <td>用户 {{ p.created_by }}</td>
                  <td>{{ formatDate(p.applied_at) }}</td>
                  <td><code>{{ p.draft_spec_id }}</code></td>
                </tr>
                <tr v-if="!appliedProposals.length">
                  <td colspan="4" class="empty">尚无 apply 历史</td>
                </tr>
              </tbody>
            </table>
          </section>
        </template>

        <!-- 老 mock tabs：环境拓扑 -->
        <template v-if="active === 'envs'">
          <section class="env-flow">
            <article v-for="env in demoEnvironments" :key="env.key" class="builder-panel env-card">
              <div class="env-card-title">
                <span>{{ env.name }}</span>
                <span class="builder-dot" :class="{ warn: env.status === 'approval', ok: env.status === 'healthy' }" />
              </div>
              <div class="env-card-meta">{{ env.version }} · {{ env.apps }} apps · {{ env.status }}</div>
            </article>
          </section>
        </template>

        <!-- 老 mock tabs：流水线 / 运行历史 -->
        <template v-if="active === 'pipelines' || active === 'runs'">
          <section class="builder-panel">
            <table class="builder-table">
              <thead>
                <tr><th>流水线</th><th>应用</th><th>分支</th><th>状态</th><th>成功率</th><th>最后运行</th></tr>
              </thead>
              <tbody>
                <tr v-for="pipeline in demoPipelines" :key="pipeline.name">
                  <td><strong>{{ pipeline.name }}</strong></td>
                  <td>{{ pipeline.app }}</td>
                  <td style="font-family: var(--b-mono)">{{ pipeline.branch }}</td>
                  <td>
                    <span class="builder-tag">
                      <span class="builder-dot" :class="pipeline.status === '失败' ? 'err' : pipeline.status === '运行中' ? '' : 'ok'" />
                      {{ pipeline.status }}
                    </span>
                  </td>
                  <td style="font-family: var(--b-mono)">{{ pipeline.success }}</td>
                  <td>{{ pipeline.time }}</td>
                </tr>
              </tbody>
            </table>
          </section>
        </template>

        <!-- 老 mock tabs：审批中心 -->
        <template v-if="active === 'approvals'">
          <section class="builder-panel">
            <p class="empty">审批中心 — 跨应用待我审批的 proposal 列表（Phase B 预留，待 Phase C 接入）</p>
          </section>
        </template>
      </section>
    </main>
  </BuilderFrame>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Check, Files, Operation, Promotion } from '@element-plus/icons-vue'
import BuilderFrame from '@/components/BuilderFrame.vue'
import { demoEnvironments, demoPipelines } from '@/data/builderMock'
import { proposalsApi } from '@/api/proposals'
import { applicationApi } from '@/api/application'
import { type ProposalSummary, STATUS_DISPLAY_NAMES } from '@/types/proposal'

const route = useRoute()
const router = useRouter()

const active = ref<string>(String(route.query.tab || 'proposals'))
const nav = [
  { key: 'proposals', label: '提案', icon: Promotion },
  { key: 'apply-history', label: 'Apply 历史', icon: Files },
  { key: 'pipelines', label: '流水线', icon: Operation },
  { key: 'runs', label: '运行历史', icon: Files },
  { key: 'envs', label: '环境拓扑', icon: Operation },
  { key: 'approvals', label: '审批中心', icon: Check },
]

const currentLabel = computed(() => nav.find(item => item.key === active.value)?.label ?? '提案')
const kickerText = computed(() => {
  if (active.value === 'proposals') return 'Change Proposals'
  if (active.value === 'apply-history') return 'Apply History'
  return 'DevOps'
})
const subText = computed(() => {
  if (active.value === 'proposals') return '查看和评审应用的变更提案'
  if (active.value === 'apply-history') return '已 apply 到 canonical 的提案时间线'
  return '用 mock 数据先把部署、环境和审批链路跑通'
})

const appOptions = ref<{ id: number; app_name: string }[]>([])
const selectedApplicationId = ref<number | null>(null)
const proposals = ref<ProposalSummary[]>([])
const statusFilter = ref<string>('all')

const statusFilters = [
  { key: 'all', label: '全部' },
  { key: 'open', label: '待评审' },
  { key: 'changes_requested', label: '需修改' },
  { key: 'approved', label: '已批准' },
  { key: 'applied', label: '已 apply' },
  { key: 'closed', label: '已关闭' },
]

const filteredProposals = computed(() => {
  if (statusFilter.value === 'all') return proposals.value
  return proposals.value.filter(p => p.status === statusFilter.value)
})

const appliedProposals = computed(() =>
  proposals.value
    .filter(p => p.status === 'applied')
    .slice()
    .sort((a, b) =>
      new Date(b.applied_at || 0).getTime() - new Date(a.applied_at || 0).getTime()
    )
)

function countByStatus(key: string): number {
  if (key === 'all') return proposals.value.length
  return proposals.value.filter(p => p.status === key).length
}

function formatDate(s: string | null): string {
  return s ? new Date(s).toLocaleString() : '—'
}

function goToProposal(id: string) {
  router.push(`/proposals/${id}`)
}

async function loadApps() {
  try {
    const apps = await applicationApi.list()
    appOptions.value = (apps as any[])
      .map(a => ({ id: Number(a.id), app_name: a.app_name }))
      .filter(a => Number.isFinite(a.id) && a.id > 0)
    const queryAppId = Number(route.query.application_id)
    if (queryAppId && appOptions.value.find(a => a.id === queryAppId)) {
      selectedApplicationId.value = queryAppId
    } else if (appOptions.value.length > 0) {
      selectedApplicationId.value = appOptions.value[0].id
    }
  } catch (e) {
    console.error('Load apps failed', e)
  }
}

async function loadProposals() {
  if (!selectedApplicationId.value) {
    proposals.value = []
    return
  }
  try {
    proposals.value = await proposalsApi.list(selectedApplicationId.value)
  } catch (e) {
    console.error('Load proposals failed', e)
    proposals.value = []
  }
}

function onAppChange() {
  // 同步到 query string
  const newQuery = { ...route.query, application_id: String(selectedApplicationId.value || '') }
  router.replace({ query: newQuery }).catch(() => { /* ignore */ })
  loadProposals()
}

watch(selectedApplicationId, () => {
  loadProposals()
})

onMounted(async () => {
  await loadApps()
})
</script>

<style scoped>
.devops-layout { display: grid; grid-template-columns: 200px 1fr; gap: 24px; padding: 24px; }
.devops-side { display: flex; flex-direction: column; gap: 4px; }
.side-label { font-size: 12px; color: var(--b-muted, #888); margin-bottom: 8px; }
.side-link { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-radius: 6px; background: transparent; border: 0; cursor: pointer; text-align: left; }
.side-link.active { background: var(--b-primary-soft, #e7f1ff); color: var(--b-primary, #0067d6); }
.devops-main { min-width: 0; }
.builder-section-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.builder-section-kicker { font-size: 12px; color: var(--b-muted, #888); }
.builder-section-title { margin: 4px 0; }
.builder-section-sub { color: var(--b-muted, #888); font-size: 14px; }
.app-select select { padding: 6px 8px; }

.status-filter { display: flex; gap: 6px; margin-bottom: 12px; padding: 12px; flex-wrap: wrap; }
.status-filter button { padding: 4px 12px; border-radius: 12px; border: 1px solid var(--b-border, #ddd); background: white; cursor: pointer; }
.status-filter button.active { background: var(--b-primary, #0067d6); color: white; border-color: var(--b-primary, #0067d6); }

.builder-panel { background: white; border: 1px solid var(--b-border, #eee); border-radius: 8px; overflow: hidden; }
.builder-table { width: 100%; border-collapse: collapse; }
.builder-table th, .builder-table td { padding: 10px 16px; text-align: left; border-bottom: 1px solid var(--b-border, #eee); }
.empty { text-align: center; color: var(--b-muted, #888); padding: 24px; }

.status-badge { padding: 2px 8px; border-radius: 8px; font-size: 11px; }
.status-draft { background: #eee; }
.status-open { background: #cce5ff; }
.status-changes_requested { background: #ffe5b4; }
.status-approved { background: #d4edda; }
.status-applying { background: #fff3cd; }
.status-applied { background: #c3e6cb; }
.status-apply_failed { background: #f5c6cb; }
.status-closed { background: #ddd; }

.env-flow { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 16px; }
.env-card { padding: 16px; }
.env-card-title { display: flex; justify-content: space-between; align-items: center; }
.env-card-meta { font-size: 13px; color: var(--b-muted, #888); }
.builder-tag { display: inline-flex; gap: 4px; align-items: center; }
.builder-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--b-primary, #0067d6); display: inline-block; }
.builder-dot.ok { background: #28a745; }
.builder-dot.warn { background: #ffc107; }
.builder-dot.err { background: #dc3545; }
</style>
