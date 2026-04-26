<template>
  <BuilderFrame :breadcrumbs="[{ label: '提案', href: '/devops' }, { label: detail?.title || proposalId }]">
    <div v-if="loading" class="loading">加载中…</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <main v-else-if="detail" class="proposal-detail">
      <DriftBanner v-if="driftStatus?.drift" :status="driftStatus" @resolve="onResolveDrift" />
      <header class="detail-header">
        <h1>{{ detail.title }}</h1>
        <span class="status-badge" :class="`status-${detail.status}`">
          {{ STATUS_DISPLAY_NAMES[detail.status] || detail.status }}
        </span>
        <a v-if="detail.git_pr_url" :href="detail.git_pr_url" target="_blank" class="builder-btn git-pr-btn">
          查看 PR ↗
        </a>
      </header>

      <div class="detail-body">
        <!-- 左：description + draft 摘要 -->
        <section class="left-pane">
          <h3>描述</h3>
          <div class="description-md">{{ detail.description || '（无描述）' }}</div>

          <h3>变更内容（v1：摘要）</h3>
          <div v-if="detail.apply_plan" class="apply-summary">
            <p>共 {{ detail.apply_plan.ops.length }} 个变更：</p>
            <ul>
              <li v-for="(op, idx) in detail.apply_plan.ops" :key="idx">
                <span class="reversibility-badge" :class="`reversibility-${op.reversibility}`">
                  {{ reversibilityLabel(op.reversibility) }}
                </span>
                <code>{{ op.kind }}</code> {{ op.target }}
              </li>
            </ul>
          </div>
          <p v-else class="muted">尚未生成 apply_plan（须先 approve）。</p>
        </section>

        <!-- 右：validation + reviews + action -->
        <aside class="right-pane">
          <section class="validation-card">
            <h3>第一道门校验</h3>
            <div v-if="detail.validation_report">
              <div v-for="(check, name) in validationChecks" :key="name" class="check-row">
                <span :class="check.ok ? 'check-pass' : 'check-fail'">
                  {{ check.ok ? '✓' : '✗' }}
                </span>
                <strong>{{ checkLabel(String(name)) }}</strong>
                <ul v-if="check.issues.length">
                  <li v-for="(i, idx) in check.issues" :key="idx">{{ i }}</li>
                </ul>
              </div>
            </div>
            <div v-else class="muted">尚未校验</div>
            <button class="builder-btn" @click="onRefreshValidation" :disabled="refreshing">
              {{ refreshing ? '校验中...' : '重新校验' }}
            </button>
          </section>

          <section class="reviews-card">
            <h3>评审 ({{ detail.reviews.length }})</h3>
            <div v-for="r in detail.reviews" :key="r.id" class="review-item">
              <div>
                <strong>用户 {{ r.reviewer_id }}</strong>
                <span class="action-badge" :class="`action-${r.action}`">{{ actionLabel(r.action) }}</span>
                <span class="muted">{{ formatDate(r.created_at) }}</span>
              </div>
              <p v-if="r.body" class="review-body">{{ r.body }}</p>
            </div>
            <p v-if="!detail.reviews.length" class="muted">暂无评审</p>

            <div v-if="canReview" class="review-form">
              <textarea v-model="reviewBody" placeholder="评审意见（可选）" rows="3" />
              <div class="review-actions">
                <button class="builder-btn" @click="onComment">留言</button>
                <button class="builder-btn builder-btn-danger" @click="onRequestChanges" :disabled="!canApprove">请求修改</button>
                <button class="builder-btn builder-btn-primary" @click="onApprove" :disabled="!canApprove">
                  批准
                </button>
              </div>
              <p v-if="!canApprove" class="muted small">
                {{ isCreator ? '不能审阅自己的提案' : '需 maintainer 以上角色才能批准' }}
              </p>
            </div>
          </section>

          <section v-if="detail.status === 'approved'" class="apply-card">
            <h3>Apply</h3>
            <button class="builder-btn builder-btn-primary apply-btn" @click="onApply" :disabled="applying">
              {{ applying ? 'apply 中...' : 'Apply 到 canonical' }}
            </button>
          </section>

          <section v-if="detail.status === 'applied'" class="applied-card">
            <h3>已 apply</h3>
            <p>@ {{ formatDate(detail.applied_at) }}</p>
            <p v-if="appliedGitTag" class="git-tag-row">
              Git tag: <code>{{ appliedGitTag }}</code>
            </p>
            <details v-if="executorResult && executorResult.journal?.length">
              <summary>平台部署详情（{{ executorResult.journal.length }} 个资源）</summary>
              <ul class="journal-list">
                <li v-for="(entry, idx) in executorResult.journal" :key="idx">
                  <span class="journal-icon">{{ entry.platform_id ? '✓' : '✗' }}</span>
                  <code>{{ entry.operation }} {{ entry.resource_type }}:{{ entry.resource_code }}</code>
                  <span v-if="entry.platform_id" class="muted small">(id: {{ entry.platform_id }})</span>
                </li>
              </ul>
            </details>
          </section>

          <section v-if="detail.status === 'apply_failed'" class="apply-failed-card">
            <h3>apply 失败</h3>
            <p>{{ failedReason }}</p>
            <details v-if="executorResult?.errors?.length">
              <summary>错误列表（{{ executorResult.errors.length }} 条）</summary>
              <ul class="error-list">
                <li v-for="(err, idx) in executorResult.errors" :key="idx">{{ err }}</li>
              </ul>
            </details>
            <p v-if="fixupProposalId" class="fixup-link">
              🔧 系统已自动创建 fix-up proposal：
              <button class="builder-btn builder-btn-primary" type="button" @click="goToProposal(fixupProposalId)">
                查看 fix-up
              </button>
            </p>
          </section>

          <section v-if="detail.status === 'draft'" class="draft-card">
            <p class="muted">草稿状态：待 promote 到 open 后才可评审</p>
          </section>
        </aside>
      </div>

      <!-- 不可逆确认 modal -->
      <div v-if="confirmModal" class="modal-backdrop" @click.self="confirmModal = null">
        <div class="modal">
          <h3>⚠ 包含不可逆操作</h3>
          <p>下列变更 apply 后<strong>无法直接撤销</strong>，请仔细确认：</p>
          <ul class="irreversible-list">
            <li v-for="(op, idx) in confirmModal" :key="idx">
              <code>{{ op.kind }}</code> {{ op.target }}
            </li>
          </ul>
          <div class="modal-actions">
            <button class="builder-btn" @click="confirmModal = null">取消</button>
            <button class="builder-btn builder-btn-danger" @click="onConfirmApply" :disabled="applying">
              确认 apply 不可逆变更
            </button>
          </div>
        </div>
      </div>
    </main>
  </BuilderFrame>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import BuilderFrame from '@/components/BuilderFrame.vue'
import DriftBanner from '@/components/DriftBanner.vue'
import { proposalsApi } from '@/api/proposals'
import { gitConnectionApi, type DriftStatus } from '@/api/gitConnection'
import {
  type ProposalDetail, type ApplyOp, type Reversibility,
  type ApplyLogV2, type ExecutorResult,
  STATUS_DISPLAY_NAMES,
} from '@/types/proposal'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const proposalId = computed(() => String(route.params.id))
const loading = ref(true)
const error = ref('')
const detail = ref<ProposalDetail | null>(null)
const refreshing = ref(false)
const applying = ref(false)
const reviewBody = ref('')
const confirmModal = ref<ApplyOp[] | null>(null)
const driftStatus = ref<DriftStatus | null>(null)

const applyLog = computed<ApplyLogV2 | null>(() => {
  const al = detail.value?.apply_log
  return al ? (al as ApplyLogV2) : null
})

const executorResult = computed<ExecutorResult | null>(() => applyLog.value?.executor_result || null)
const fixupProposalId = computed<string | null>(() => applyLog.value?.fixup_proposal_id || null)
const appliedGitTag = computed<string | null>(() => applyLog.value?.git_tag || null)
const failedReason = computed<string>(() =>
  applyLog.value?.failure_reason || applyLog.value?.error || '未知错误'
)

function goToProposal(proposalId: string) {
  router.push(`/proposals/${proposalId}`)
}

const validationChecks = computed(() => {
  if (!detail.value?.validation_report) return {}
  const r = detail.value.validation_report
  return {
    completeness: r.completeness,
    consistency: r.consistency,
    naming: r.naming,
    markdown: r.markdown,
  }
})

const isCreator = computed(() =>
  !!(detail.value && userStore.user?.id === detail.value.created_by)
)

const canReview = computed(() => {
  if (!detail.value) return false
  return ['open', 'changes_requested'].includes(detail.value.status)
})

const canApprove = computed(() => !isCreator.value)

function checkLabel(name: string): string {
  return ({
    completeness: '完整性', consistency: '一致性',
    naming: '命名', markdown: 'Markdown 渲染',
  } as Record<string, string>)[name] || name
}

function reversibilityLabel(r: Reversibility): string {
  return ({ green: '可逆', yellow: '部分可逆', red: '不可逆' } as Record<string, string>)[r] || r
}

function actionLabel(a: string): string {
  return ({ approve: '批准', request_changes: '请求修改', comment: '留言' } as Record<string, string>)[a] || a
}

function formatDate(s: string | null): string {
  return s ? new Date(s).toLocaleString() : '—'
}

async function refresh() {
  try {
    loading.value = true
    detail.value = await proposalsApi.get(proposalId.value)
    error.value = ''
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function onRefreshValidation() {
  refreshing.value = true
  try {
    detail.value = await proposalsApi.refreshValidation(proposalId.value)
  } catch (e: any) {
    alert(e?.response?.data?.detail || e?.message || '校验失败')
  } finally {
    refreshing.value = false
  }
}

async function onComment() {
  if (!reviewBody.value.trim()) {
    alert('请填写留言内容')
    return
  }
  try {
    await proposalsApi.review(proposalId.value, 'comment', reviewBody.value)
    reviewBody.value = ''
    await refresh()
  } catch (e: any) {
    alert(e?.response?.data?.detail || e?.message || '留言失败')
  }
}

async function onRequestChanges() {
  try {
    await proposalsApi.review(proposalId.value, 'request_changes', reviewBody.value || undefined)
    reviewBody.value = ''
    await refresh()
  } catch (e: any) {
    alert(e?.response?.data?.detail || e?.message || '请求修改失败')
  }
}

async function onApprove() {
  try {
    await proposalsApi.review(proposalId.value, 'approve', reviewBody.value || undefined)
    reviewBody.value = ''
    await refresh()
  } catch (e: any) {
    alert(e?.response?.data?.detail || e?.message || '批准失败')
  }
}

async function onApply() {
  applying.value = true
  try {
    const res = await proposalsApi.apply(proposalId.value, false)
    if (res.status === 'needs_confirmation' && res.apply_plan) {
      // 弹确认 modal
      confirmModal.value = res.apply_plan.ops.filter(o => o.reversibility === 'red')
      // 同时刷新 detail 以更新 apply_plan 显示
      await refresh()
    } else {
      await refresh()
    }
  } catch (e: any) {
    alert(e?.response?.data?.detail || e?.message || 'apply 失败')
  } finally {
    applying.value = false
  }
}

async function onConfirmApply() {
  applying.value = true
  try {
    await proposalsApi.apply(proposalId.value, true)
    confirmModal.value = null
    await refresh()
  } catch (e: any) {
    alert(e?.response?.data?.detail || e?.message || 'apply 失败')
  } finally {
    applying.value = false
  }
}

async function loadDriftStatus() {
  if (!detail.value?.application_id) {
    driftStatus.value = null
    return
  }
  try {
    driftStatus.value = await gitConnectionApi.driftStatus(detail.value.application_id)
  } catch {
    driftStatus.value = null
  }
}

function onResolveDrift() {
  alert('请到 Project Overview → Git 集成页面解决漂移（仅 owner 可操作）')
}

watch(() => detail.value?.application_id, () => {
  loadDriftStatus()
})

onMounted(refresh)
</script>

<style scoped>
.proposal-detail { padding: 24px; }
.detail-header { display: flex; align-items: center; gap: 12px; margin-bottom: 20px; }
.status-badge { padding: 4px 10px; border-radius: 12px; font-size: 12px; }
.status-draft { background: var(--bg-inset); color: var(--fg-muted); }
.status-open { background: var(--t-brand-subtle, rgba(79,110,247,0.08)); color: var(--brand); }
.status-changes_requested { background: var(--t-warning-subtle); color: var(--t-warning); }
.status-approved { background: var(--t-success-subtle); color: var(--t-success); }
.status-applying { background: var(--t-warning-subtle); color: var(--t-warning); }
.status-applied { background: var(--t-success-subtle); color: var(--t-success); }
.status-apply_failed { background: var(--t-danger-subtle); color: var(--t-danger); }
.status-closed { background: var(--bg-inset); color: var(--fg-muted); }

.detail-body { display: grid; grid-template-columns: 2fr 1fr; gap: 24px; }
.left-pane h3, .right-pane h3 { margin: 16px 0 8px; }
.description-md { white-space: pre-wrap; padding: 12px; background: var(--bg-inset); color: var(--fg); border-radius: 6px; }
.apply-summary ul { padding-left: 0; list-style: none; }
.apply-summary li { padding: 6px 0; border-bottom: 1px solid var(--line); }
.reversibility-badge { display: inline-block; padding: 2px 8px; border-radius: 8px; font-size: 11px; margin-right: 8px; color: var(--t-text-inverse, #fff); }
.reversibility-green { background: var(--t-success); }
.reversibility-yellow { background: var(--t-warning); color: var(--bg-ink); }
.reversibility-red { background: var(--t-danger); }

.validation-card, .reviews-card, .apply-card, .applied-card, .apply-failed-card, .draft-card {
  border: 1px solid var(--line); background: var(--bg-panel); padding: 16px; border-radius: 8px; margin-bottom: 16px;
}
.check-row { padding: 8px 0; }
.check-row ul { padding-left: 32px; color: var(--t-danger); font-size: 13px; }
.check-pass { color: var(--t-success); font-weight: bold; }
.check-fail { color: var(--t-danger); font-weight: bold; }

.review-item { padding: 8px 0; border-bottom: 1px solid var(--line); }
.action-badge { padding: 2px 8px; border-radius: 8px; font-size: 11px; margin: 0 6px; }
.action-approve { background: var(--t-success-subtle); color: var(--t-success); }
.action-request_changes { background: var(--t-danger-subtle); color: var(--t-danger); }
.action-comment { background: var(--bg-inset); color: var(--fg-muted); }
.review-body { margin-top: 4px; padding: 8px; background: var(--bg-inset); color: var(--fg); border-radius: 4px; }

.review-form { margin-top: 16px; }
.review-form textarea { width: 100%; padding: 8px; box-sizing: border-box; background: var(--bg-inset); color: var(--fg); border: 1px solid var(--line); border-radius: 4px; }
.review-actions { display: flex; gap: 8px; margin-top: 8px; }
.muted { color: var(--fg-muted); }
.small { font-size: 12px; }

.apply-btn { width: 100%; padding: 12px; }

.modal-backdrop { position: fixed; inset: 0; background: var(--t-bg-overlay, rgba(0,0,0,.5)); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.modal { background: var(--bg-panel); color: var(--fg); padding: 24px; border-radius: 8px; max-width: 600px; width: 90%; box-shadow: var(--sh-pop); }
.irreversible-list { padding-left: 20px; color: var(--t-danger); }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
.builder-btn-danger { background: var(--t-danger); color: var(--t-text-inverse, #fff); }
.loading, .error { padding: 48px; text-align: center; color: var(--fg-muted); }
.error { color: var(--t-danger); }

.git-pr-btn {
  margin-left: auto;
  font-size: 12px;
  padding: 4px 12px;
  border: 1px solid var(--brand);
  color: var(--brand);
  background: transparent;
  border-radius: 6px;
  text-decoration: none;
  font-weight: 500;
}
.git-pr-btn:hover { background: var(--brand-soft); }

.git-tag-row { margin-top: 6px; font-size: 12px; color: var(--fg-muted); }
.git-tag-row code {
  background: var(--bg-inset);
  color: var(--fg);
  padding: 1px 6px;
  border-radius: 4px;
  font-family: var(--b-mono, ui-monospace, SFMono-Regular, monospace);
}

.journal-list, .error-list { list-style: none; padding-left: 0; margin-top: 8px; }
.journal-list li, .error-list li { padding: 4px 0; border-bottom: 1px solid var(--line); display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.journal-icon { display: inline-block; width: 16px; }
.fixup-link {
  margin-top: 12px; padding: 12px;
  background: var(--t-warning-subtle); color: var(--t-warning);
  border-radius: 6px;
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
}
.error-list li { color: var(--t-danger); }
</style>
