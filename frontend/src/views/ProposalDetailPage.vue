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
    <BaseToast :visible="toastVisible" :message="toastMessage" :type="toastType" />
  </BuilderFrame>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import BuilderFrame from '@/components/BuilderFrame.vue'
import DriftBanner from '@/components/DriftBanner.vue'
import BaseToast from '@/components/BaseToast.vue'
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

// Phase F Task 12b: BaseToast 替原生 alert
const toastVisible = ref(false)
const toastMessage = ref('')
const toastType = ref<'info' | 'success' | 'warn' | 'error'>('error')
let toastTimer: ReturnType<typeof setTimeout> | null = null
function showToast(message: string, type: 'info' | 'success' | 'warn' | 'error' = 'error') {
  toastMessage.value = message
  toastType.value = type
  toastVisible.value = true
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toastVisible.value = false }, 3000)
}

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
    showToast(e?.response?.data?.detail || e?.message || '校验失败', 'error')
  } finally {
    refreshing.value = false
  }
}

async function onComment() {
  if (!reviewBody.value.trim()) {
    showToast('请填写留言内容', 'warn')
    return
  }
  try {
    await proposalsApi.review(proposalId.value, 'comment', reviewBody.value)
    reviewBody.value = ''
    await refresh()
  } catch (e: any) {
    showToast(e?.response?.data?.detail || e?.message || '留言失败', 'error')
  }
}

async function onRequestChanges() {
  try {
    await proposalsApi.review(proposalId.value, 'request_changes', reviewBody.value || undefined)
    reviewBody.value = ''
    await refresh()
  } catch (e: any) {
    showToast(e?.response?.data?.detail || e?.message || '请求修改失败', 'error')
  }
}

async function onApprove() {
  try {
    await proposalsApi.review(proposalId.value, 'approve', reviewBody.value || undefined)
    reviewBody.value = ''
    await refresh()
  } catch (e: any) {
    showToast(e?.response?.data?.detail || e?.message || '批准失败', 'error')
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
    showToast(e?.response?.data?.detail || e?.message || 'apply 失败', 'error')
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
    showToast(e?.response?.data?.detail || e?.message || 'apply 失败', 'error')
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
  showToast('请到 Project Overview → Git 集成页面解决漂移（仅 owner 可操作）', 'info')
}

watch(() => detail.value?.application_id, () => {
  loadDriftStatus()
})

onMounted(refresh)
</script>

<style scoped>
/* v3 redesign · 2026-05-20 — token migration, template/script untouched.
   Legacy --t-* tokens (--t-brand-subtle / --t-success / --t-warning /
   --t-danger / --t-text-inverse) + v2 aliases (--bg-panel / --bg-inset /
   --fg / --fg-muted) → v3 (--brand / --ok / --warn / --err / --surface /
   --surface-2 / --text). Added :focus-visible rings.
*/
.proposal-detail { padding: 24px; color: var(--text); font-family: var(--font-sans, inherit); }
.detail-header { display: flex; align-items: center; gap: 12px; margin-bottom: 20px; }
.detail-header h1 { font-size: var(--t-h2, 24px); font-weight: var(--fw-bold, 700); color: var(--text); margin: 0; letter-spacing: -0.01em; }
.status-badge { padding: 4px 10px; border-radius: var(--r-full, 12px); font-size: 12px; font-weight: var(--fw-medium, 500); }
.status-draft { background: var(--surface-3); color: var(--text-3); }
.status-open { background: var(--brand-soft); color: var(--brand); }
.status-changes_requested { background: var(--warn-soft); color: var(--warn); }
.status-approved { background: var(--ok-soft); color: var(--ok); }
.status-applying { background: var(--warn-soft); color: var(--warn); }
.status-applied { background: var(--ok-soft); color: var(--ok); }
.status-apply_failed { background: var(--err-soft); color: var(--err); }
.status-closed { background: var(--surface-3); color: var(--text-3); }

.detail-body { display: grid; grid-template-columns: 2fr 1fr; gap: 24px; }
.left-pane h3, .right-pane h3 { margin: 16px 0 8px; font-size: var(--t-h3, 18px); font-weight: var(--fw-semibold, 600); color: var(--text); letter-spacing: -0.005em; }
.description-md { white-space: pre-wrap; padding: 12px; background: var(--surface-2); color: var(--text); border-radius: var(--r-2, 6px); font-size: var(--t-body, 14px); line-height: 1.55; }
.apply-summary ul { padding-left: 0; list-style: none; }
.apply-summary li { padding: 6px 0; border-bottom: 1px solid var(--line); color: var(--text-2); font-size: var(--t-body, 14px); }
.reversibility-badge { display: inline-block; padding: 2px 8px; border-radius: var(--r-3, 8px); font-size: 11px; margin-right: 8px; color: var(--text-inverse, #fff); font-weight: var(--fw-medium, 500); }
.reversibility-green { background: var(--ok); }
.reversibility-yellow { background: var(--warn); color: var(--text); }
.reversibility-red { background: var(--err); }

.validation-card, .reviews-card, .apply-card, .applied-card, .apply-failed-card, .draft-card {
  border: 1px solid var(--line); background: var(--surface); padding: 16px; border-radius: var(--r-3, 8px); margin-bottom: 16px; box-shadow: var(--sh-1);
}
.check-row { padding: 8px 0; font-size: var(--t-body, 14px); color: var(--text); }
.check-row ul { padding-left: 32px; color: var(--err); font-size: 13px; }
.check-pass { color: var(--ok); font-weight: var(--fw-bold, 700); }
.check-fail { color: var(--err); font-weight: var(--fw-bold, 700); }

.review-item { padding: 8px 0; border-bottom: 1px solid var(--line); }
.review-item strong { color: var(--text); font-weight: var(--fw-semibold, 600); }
.action-badge { padding: 2px 8px; border-radius: var(--r-3, 8px); font-size: 11px; margin: 0 6px; font-weight: var(--fw-medium, 500); }
.action-approve { background: var(--ok-soft); color: var(--ok); }
.action-request_changes { background: var(--err-soft); color: var(--err); }
.action-comment { background: var(--surface-3); color: var(--text-3); }
.review-body { margin-top: 4px; padding: 8px; background: var(--surface-2); color: var(--text); border-radius: var(--r-1, 4px); font-size: var(--t-body, 14px); }

.review-form { margin-top: 16px; }
.review-form textarea {
  width: 100%; padding: 8px; box-sizing: border-box;
  background: var(--surface); color: var(--text);
  border: 1px solid var(--line); border-radius: var(--r-2, 6px);
  font-family: inherit; font-size: var(--t-body, 14px);
  transition: border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.review-form textarea:focus { outline: none; border-color: var(--brand); box-shadow: 0 0 0 3px var(--brand-ring); }
.review-actions { display: flex; gap: 8px; margin-top: 8px; }
.muted { color: var(--text-3); }
.small { font-size: 12px; }

.apply-btn { width: 100%; padding: 12px; }

.modal-backdrop { position: fixed; inset: 0; background: rgba(11, 27, 63, 0.45); backdrop-filter: blur(2px); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.modal { background: var(--surface); color: var(--text); padding: 24px; border-radius: var(--r-4, 12px); max-width: 600px; width: 90%; box-shadow: var(--sh-5); border: 1px solid var(--line); }
.modal h3 { margin: 0 0 12px; color: var(--warn); font-size: var(--t-h3, 18px); font-weight: var(--fw-bold, 700); }
.irreversible-list { padding-left: 20px; color: var(--err); }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
.builder-btn-danger { background: var(--err); color: var(--text-inverse, #fff); border-color: var(--err); }
.builder-btn-danger:hover:not(:disabled) { filter: brightness(1.05); }
.loading, .error { padding: 48px; text-align: center; color: var(--text-3); font-size: var(--t-body, 14px); }
.error { color: var(--err); }

.git-pr-btn {
  margin-left: auto;
  font-size: 12px;
  padding: 4px 12px;
  border: 1px solid var(--brand);
  color: var(--brand);
  background: transparent;
  border-radius: var(--r-2, 6px);
  text-decoration: none;
  font-weight: var(--fw-medium, 500);
  transition: all 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.git-pr-btn:hover { background: var(--brand-soft); }
.git-pr-btn:focus-visible { outline: 2px solid var(--line-focus, var(--brand-ring)); outline-offset: 2px; }

.git-tag-row { margin-top: 6px; font-size: 12px; color: var(--text-3); }
.git-tag-row code {
  background: var(--surface-3);
  color: var(--text);
  padding: 1px 6px;
  border-radius: var(--r-1, 4px);
  font-family: var(--font-mono, ui-monospace, SFMono-Regular, monospace);
  font-size: var(--t-mono, 12px);
}

.journal-list, .error-list { list-style: none; padding-left: 0; margin-top: 8px; }
.journal-list li, .error-list li { padding: 4px 0; border-bottom: 1px solid var(--line); display: flex; gap: 8px; align-items: center; flex-wrap: wrap; font-size: var(--t-body, 14px); }
.journal-icon { display: inline-block; width: 16px; }
.fixup-link {
  margin-top: 12px; padding: 12px;
  background: var(--warn-soft); color: var(--warn);
  border-radius: var(--r-2, 6px);
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  font-size: var(--t-body, 14px); font-weight: var(--fw-medium, 500);
}
.error-list li { color: var(--err); }
</style>
