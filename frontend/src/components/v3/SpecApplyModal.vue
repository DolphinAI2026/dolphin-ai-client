<!-- SpecApplyModal.vue — design-v4 设计 tab "确认并生成" modal.

  跟 mockup 视图 ③ 100% 对齐 (`docs/internal/design-tab-mockup-2026-05-27.html`).

  flow:
    1. visible=true 时拉 plan: GET /applications/{appId}/spec/apply-plan
       → groups (4-6 分组) + total_steps + estimated_seconds
    2. 渲染 modal head + body (4 分组 change-item 列表) + warn banner + foot
    3. 点 "✨ 确认并生成 (N 步) →" → POST /applications/{appId}/spec/apply
       → 进度态 (step i / N + 当前 MCP 工具名 + spinner)
    4. 完成 emit 'applied', frontend 显成功 toast / 刷新草稿状态
    5. 失败显错误 + "回滚草稿 (P5)" placeholder

  设计 token: design-v3-tokens.css (var(--brand) / var(--surface) / var(--warn) 等)
  视觉: 强严照 mockup .apply-modal .change-group .change-item .typ.add 等 class

  ⚠️ MVP 后端是 dry-run (不真调 MCP, 只 sleep). 接通后:
    - foot 加 "回滚草稿" btn (用 deployed_section_ids)
    - 进度态用 SSE 实时显 (现在阻塞 N*1.5s 一次返)
    - "仅保存 SPEC" 也连后端 (现在直接 emit close, 草稿已存)
-->
<template>
  <Teleport to="body">
    <transition name="sam-fade">
      <div
        v-if="visible"
        class="sam-backdrop"
        role="dialog"
        aria-modal="true"
        aria-labelledby="sam-title"
        @click.self="onCancel"
      >
        <div class="sam-modal" :class="{ 'sam-modal--running': running }">

          <!-- ── head ───────────────────────────────────────────────────── -->
          <div class="sam-head">
            <h3 id="sam-title">
              <AppIcon name="sparkles" :size="16" /> 确认并生成
            </h3>
            <p v-if="loading">正在加载草稿差异…</p>
            <p v-else-if="loadError">加载失败: {{ loadError }}</p>
            <p v-else-if="plan && plan.total_steps === 0">
              当前 SPEC 草稿跟生产一致, 无需 apply.
            </p>
            <p v-else-if="plan">
              AI 将按这版 SPEC 草稿生成 apaas 平台配置.
              以下 {{ plan.total_steps }} 步 MCP 操作 (预计 ~{{ plan.estimated_seconds }} 秒):
            </p>
          </div>

          <!-- ── body ───────────────────────────────────────────────────── -->
          <div class="sam-body">

            <!-- loading skeleton -->
            <div v-if="loading" class="sam-loading">
              <div class="sam-skel"></div>
              <div class="sam-skel"></div>
              <div class="sam-skel" style="width: 60%;"></div>
            </div>

            <!-- 错误态 -->
            <div v-else-if="loadError" class="sam-error">
              <p>{{ loadError }}</p>
              <button class="sam-btn-mini" type="button" @click="loadPlan">重试</button>
            </div>

            <!-- 空态 -->
            <div v-else-if="plan && plan.total_steps === 0" class="sam-empty">
              <p><AppIcon name="inbox" :size="14" /> 当前 SPEC 草稿跟已部署生产版本一致, 没有需要 apply 的改动.</p>
              <p class="sam-empty-hint">
                先用「设计」tab 内嵌 chat 改改 SPEC, 草稿写入后再回来 apply.
              </p>
            </div>

            <!-- plan: groups + items (视图 ③ 主体) -->
            <template v-else-if="plan">
              <div
                v-for="g in plan.groups"
                :key="g.section_type"
                class="sam-group"
              >
                <h4>
                  {{ g.title }}
                  <span class="sam-group-ct">{{ g.spec_section_ref }}</span>
                </h4>
                <div
                  v-for="(it, idx) in g.items"
                  :key="`${g.section_type}-${idx}`"
                  class="sam-item"
                  :class="{
                    'sam-item--running': running && stepIndex === itemAbsoluteIdx(g, idx),
                    'sam-item--done': running && stepIndex > itemAbsoluteIdx(g, idx),
                  }"
                >
                  <span class="sam-typ" :class="`sam-typ--${it.typ_color || 'mod'}`">{{ it.typ }}</span>
                  <!-- desc 含 <strong> 标签, 用 v-html 渲染. 后端控制内容 (无 user input). -->
                  <span class="sam-desc" v-html="it.desc"></span>
                  <span class="sam-mcp">{{ it.mcp_tool }}</span>

                  <!-- 进度指示器 (仅 running 时显示) -->
                  <span
                    v-if="running && stepIndex === itemAbsoluteIdx(g, idx)"
                    class="sam-step-indicator"
                    aria-label="正在执行"
                  >
                    <span class="sam-spinner" aria-hidden="true"></span>
                  </span>
                  <span
                    v-else-if="running && stepIndex > itemAbsoluteIdx(g, idx)"
                    class="sam-step-indicator sam-step-indicator--done"
                    aria-label="已完成"
                  ><AppIcon name="check" :size="12" /></span>
                </div>
              </div>

              <!-- 警告 banner -->
              <div v-if="plan.total_steps > 0" class="sam-warn-banner">
                <AppIcon name="warning" :size="12" />
                上线后立即生效, 失败自动回滚草稿不动. 已部署版本会留 1 周做 rollback 兜底.
              </div>
            </template>

            <!-- 执行错误 banner -->
            <div v-if="applyError" class="sam-error-banner">
              <p>
                <strong>执行失败:</strong> {{ applyError }}
              </p>
              <button class="sam-btn-mini" disabled title="P5 接入">回滚草稿 (P5)</button>
            </div>

            <!-- 执行完成 banner -->
            <div v-if="applyResult && !applyError" class="sam-ok-banner">
              <AppIcon name="check-circle" :size="12" />
              已完成 {{ applyResult.applied_steps }} / {{ applyResult.total_steps }} 步
              (耗时 {{ Math.round((applyResult.duration_ms || 0) / 100) / 10 }} 秒,
              模式: {{ applyResult.mode }})
            </div>
          </div>

          <!-- ── foot ───────────────────────────────────────────────────── -->
          <div class="sam-foot">
            <button
              class="sam-btn-mini"
              type="button"
              :disabled="running"
              @click="onCancel"
            >取消</button>
            <button
              class="sam-btn-mini"
              type="button"
              :disabled="running || loading"
              @click="onSaveOnly"
              title="不 apply 到 apaas — 草稿已经写入"
            >仅保存 SPEC</button>
            <button
              class="sam-cta"
              type="button"
              :disabled="loading || !!loadError || running || !plan || plan.total_steps === 0 || !!applyResult"
              @click="onApply"
            >
              <span v-if="running">
                执行中… {{ stepIndex + 1 }} / {{ plan?.total_steps || 0 }}
              </span>
              <span v-else-if="applyResult">
                已完成
              </span>
              <span v-else>
                <AppIcon name="sparkles" :size="13" />
                确认并生成 ({{ plan?.total_steps || 0 }} 步) →
              </span>
            </button>
          </div>
        </div>
      </div>
    </transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import request from '@/utils/request'
import AppIcon from '@/components/common/AppIcon.vue'

// ── props / emits ─────────────────────────────────────────────────────────

const props = defineProps<{
  appId: number
  visible: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'applied', result: ApplyResult): void
}>()

// ── plan / apply 数据结构 (跟 backend spec_apply.py 对齐) ────────────────

interface ChangeItem {
  typ: string                // e.g. "+模型" / "+字段" / "~关系"
  typ_color?: 'add' | 'del' | 'mod'  // 决定 chip 颜色 (绿/红/蓝)
  desc: string               // 含 <strong> bold (后端控制, 无 user input)
  mcp_tool: string           // e.g. "create_apaas_app_model"
}

interface ChangeGroup {
  section_type: string
  title: string              // e.g. "数据模型"
  spec_section_ref: string   // e.g. "spec_sections.models"
  items: ChangeItem[]
}

interface ApplyPlan {
  ok: boolean
  app_id: number
  groups: ChangeGroup[]
  total_steps: number
  estimated_seconds: number
}

interface ApplyResult {
  ok: boolean
  app_id: number
  mode: string               // 'dry-run' (MVP) / 'live' (P5)
  total_steps: number
  applied_steps: number
  results: Array<{
    ok: boolean
    mcp_tool?: string
    desc?: string
    mode?: string
    error?: string
  }>
  duration_ms: number
  message?: string
}

// ── reactive state ────────────────────────────────────────────────────────

const loading = ref(false)
const loadError = ref<string | null>(null)
const plan = ref<ApplyPlan | null>(null)

const running = ref(false)
const stepIndex = ref(0)        // 当前执行到第几步 (0-indexed)
const applyError = ref<string | null>(null)
const applyResult = ref<ApplyResult | null>(null)

// ── 加载 plan ─────────────────────────────────────────────────────────────

async function loadPlan() {
  loading.value = true
  loadError.value = null
  plan.value = null
  applyError.value = null
  applyResult.value = null
  stepIndex.value = 0

  try {
    const resp = await request.get<ApplyPlan>(`/applications/${props.appId}/spec/apply-plan`)
    plan.value = resp.data
  } catch (e: any) {
    loadError.value = e?.response?.data?.detail || e?.message || String(e)
  } finally {
    loading.value = false
  }
}

// visible 变 true 时拉 plan; 变 false 时重置 (下次开重新拉)
watch(
  () => props.visible,
  (v) => {
    if (v) {
      loadPlan()
    } else {
      // reset (避免再次开看见上次结果)
      plan.value = null
      loadError.value = null
      running.value = false
      stepIndex.value = 0
      applyError.value = null
      applyResult.value = null
    }
  },
)

// ── 执行 apply ────────────────────────────────────────────────────────────

async function onApply() {
  if (!plan.value || plan.value.total_steps === 0) return

  running.value = true
  applyError.value = null
  applyResult.value = null
  stepIndex.value = 0

  // 用 setInterval 跟着 backend sleep 1.5s/step 的节奏 step 进度.
  // 简单可视化 — 不是真 SSE, 但 1.5s 一跳给用户感觉.
  // (P5 改 SSE 后这个 interval 改成事件驱动)
  const stepIntervalMs = Math.max(500, plan.value.estimated_seconds * 1000 / Math.max(1, plan.value.total_steps))
  const intervalHandle = window.setInterval(() => {
    if (stepIndex.value < (plan.value?.total_steps ?? 0) - 1) {
      stepIndex.value += 1
    }
  }, stepIntervalMs)

  try {
    const resp = await request.post<ApplyResult>(
      `/applications/${props.appId}/spec/apply`,
      { dry_run: true },
    )
    window.clearInterval(intervalHandle)
    applyResult.value = resp.data
    stepIndex.value = resp.data.total_steps  // tick 到 done
    emit('applied', resp.data)
  } catch (e: any) {
    window.clearInterval(intervalHandle)
    applyError.value = e?.response?.data?.detail || e?.message || String(e)
  } finally {
    running.value = false
  }
}

// ── "仅保存 SPEC" — MVP 直接关 (草稿已在 spec_sections 表) ─────────────

function onSaveOnly() {
  // 草稿已经在 spec_sections 表 (spec_chat 写入). 不调后端, 直接关.
  // P5: 若加 spec_sections.locked_for_apply 之类的状态, 这里要写一笔 unlock.
  emit('close')
}

// ── 取消 ──────────────────────────────────────────────────────────────────

function onCancel() {
  if (running.value) return  // 执行中不能关
  emit('close')
}

// ── 进度指示用 helper: 算 item 在整 plan 里的绝对 index ──────────────────

function itemAbsoluteIdx(group: ChangeGroup, localIdx: number): number {
  if (!plan.value) return -1
  let acc = 0
  for (const g of plan.value.groups) {
    if (g.section_type === group.section_type) {
      return acc + localIdx
    }
    acc += g.items.length
  }
  return acc + localIdx
}
</script>

<style scoped>
/* ───── Modal backdrop / 容器 ───── */
.sam-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.5);
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.sam-modal {
  width: 680px;
  max-width: 92vw;
  max-height: 80vh;
  background: var(--surface);
  border-radius: 12px;
  box-shadow: 0 24px 48px rgba(0, 0, 0, 0.2);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', sans-serif;
}

.sam-modal--running {
  /* 微弱发光: 跑的时候提示用户 modal 在干活 */
  box-shadow: 0 24px 48px rgba(0, 0, 0, 0.2),
              0 0 0 2px var(--brand-ring, rgba(29, 78, 216, 0.18));
}

/* ───── head ───── */
.sam-head {
  padding: 16px 20px;
  border-bottom: 1px solid var(--line);
}
.sam-head h3 {
  font-size: 16px;
  font-weight: 600;
  margin: 0;
  color: var(--text);
}
.sam-head p {
  font-size: 13px;
  color: var(--text-3);
  margin: 4px 0 0;
  line-height: 1.5;
}

/* ───── body ───── */
.sam-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}

/* ───── group ───── */
.sam-group {
  margin-bottom: 16px;
}
.sam-group h4 {
  font-size: 13px;
  font-weight: 600;
  margin: 0 0 6px;
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text);
}
.sam-group-ct {
  font-family: var(--font-mono, 'SF Mono', Menlo, monospace);
  font-size: 11px;
  color: var(--text-4);
  font-weight: 400;
}

/* ───── item (跟 mockup .change-item 严照齐) ───── */
.sam-item {
  padding: 8px 12px;
  background: var(--surface-2);
  border-left: 3px solid var(--brand);
  border-radius: 4px;
  font-size: 12px;
  margin-bottom: 4px;
  display: flex;
  align-items: center;
  gap: 8px;
  transition: background 0.2s, border-color 0.2s;
}
.sam-item--running {
  background: var(--brand-soft, #EFF4FF);
  border-left-color: var(--brand);
}
.sam-item--done {
  border-left-color: var(--ok, #10B981);
  opacity: 0.7;
}

.sam-typ {
  font-weight: 600;
  font-size: 10px;
  text-transform: uppercase;
  padding: 1px 6px;
  border-radius: 3px;
  flex-shrink: 0;
  color: var(--brand);
  background: var(--brand-soft, #EFF4FF);
}
.sam-typ--add {
  color: var(--ok, #10B981);
  background: var(--ok-soft, #D1FAE5);
}
.sam-typ--del {
  color: var(--err, #EF4444);
  background: var(--err-soft, #FEE2E2);
}
.sam-typ--mod {
  color: var(--brand);
  background: var(--brand-soft, #EFF4FF);
}

.sam-desc {
  color: var(--text);
  flex: 1;
  min-width: 0;
}
.sam-desc :deep(strong) {
  font-weight: 600;
  color: var(--text);
}

.sam-mcp {
  margin-left: auto;
  font-family: var(--font-mono, 'SF Mono', Menlo, monospace);
  font-size: 10px;
  color: var(--text-4);
  flex-shrink: 0;
}

.sam-step-indicator {
  flex-shrink: 0;
  width: 16px;
  height: 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: var(--brand);
}
.sam-step-indicator--done {
  color: var(--ok, #10B981);
}

.sam-spinner {
  display: inline-block;
  width: 12px;
  height: 12px;
  border: 2px solid var(--brand-soft, #EFF4FF);
  border-top-color: var(--brand);
  border-radius: 50%;
  animation: sam-spin 0.8s linear infinite;
}
@keyframes sam-spin {
  to { transform: rotate(360deg); }
}

/* ───── warn / error / ok banner ───── */
.sam-warn-banner {
  padding: 12px;
  background: var(--warn-soft, #FEF3C7);
  border-radius: 8px;
  font-size: 12px;
  color: var(--warn, #B45309);
  margin-top: 12px;
  line-height: 1.5;
}

.sam-error-banner {
  margin-top: 12px;
  padding: 12px;
  background: var(--err-soft, #FEE2E2);
  border-radius: 8px;
  font-size: 12px;
  color: var(--err, #B91C1C);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.sam-error-banner p { margin: 0; line-height: 1.5; }
.sam-error-banner .sam-btn-mini { align-self: flex-start; }

.sam-ok-banner {
  margin-top: 12px;
  padding: 12px;
  background: var(--ok-soft, #D1FAE5);
  border-radius: 8px;
  font-size: 12px;
  color: var(--ok, #047857);
  display: flex;
  align-items: center;
  gap: 8px;
  line-height: 1.5;
}

/* ───── loading / error / empty state ───── */
.sam-loading {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.sam-skel {
  height: 36px;
  background: linear-gradient(
    90deg,
    var(--surface-2) 0%,
    var(--surface-3) 50%,
    var(--surface-2) 100%
  );
  background-size: 200% 100%;
  animation: sam-skel-shimmer 1.5s ease infinite;
  border-radius: 4px;
}
@keyframes sam-skel-shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

.sam-error {
  padding: 16px;
  background: var(--err-soft, #FEE2E2);
  border-radius: 8px;
  color: var(--err, #B91C1C);
  font-size: 13px;
}
.sam-error p { margin: 0 0 8px; }

.sam-empty {
  padding: 32px 16px;
  text-align: center;
  color: var(--text-3);
}
.sam-empty p {
  margin: 0 0 8px;
  font-size: 14px;
  color: var(--text);
}
.sam-empty-hint { font-size: 12px; color: var(--text-3); }

/* ───── foot ───── */
.sam-foot {
  padding: 12px 20px;
  border-top: 1px solid var(--line);
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.sam-btn-mini {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: transparent;
  border: 1px solid var(--line);
  border-radius: 8px;
  font-size: 13px;
  color: var(--text);
  cursor: pointer;
  font-family: inherit;
  transition: all 0.15s;
}
.sam-btn-mini:hover:not(:disabled) {
  background: var(--surface-2);
  border-color: var(--line-strong);
}
.sam-btn-mini:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.sam-cta {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  background: var(--brand);
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  font-family: inherit;
  transition: all 0.15s;
}
.sam-cta:hover:not(:disabled) { background: var(--brand-hover); }
.sam-cta:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

/* ───── fade transition ───── */
.sam-fade-enter-active,
.sam-fade-leave-active {
  transition: opacity 0.2s ease;
}
.sam-fade-enter-active .sam-modal,
.sam-fade-leave-active .sam-modal {
  transition: transform 0.2s ease, opacity 0.2s ease;
}
.sam-fade-enter-from,
.sam-fade-leave-to {
  opacity: 0;
}
.sam-fade-enter-from .sam-modal,
.sam-fade-leave-to .sam-modal {
  transform: translateY(-12px) scale(0.98);
  opacity: 0;
}
</style>
