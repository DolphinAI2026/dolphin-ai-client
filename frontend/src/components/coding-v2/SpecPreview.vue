<template>
  <!--
    SpecPreview = 一个具体版本的 Spec 卡片。

    "操作按钮可点不可点"完全由 cardData 自身的状态决定，无任何全局 flag 参与：
    - isLatest=true && !isConfirmed → 显示"✅ 确认生成代码"按钮
    - isLatest=true && isConfirmed   → 显示"✓ 已用于生成代码"标签（不可再点）
    - isLatest=false                 → 显示"已被 v{N} 替代"标签 + 默认折叠

    refining 是纯视觉信号（最新卡顶部挂"正在生成新版…"提示），不影响按钮逻辑。
  -->
  <div
    class="spec-card"
    :class="{
      'is-superseded': !cardData.isLatest,
      'is-confirmed': cardData.isConfirmed,
      'is-collapsed': isCollapsed,
    }"
  >
    <!-- ── 顶部 header（永远显示，点可折叠/展开） ── -->
    <div class="card-header" @click="toggleCollapse">
      <div class="header-left">
        <span class="version-badge" :class="versionBadgeClass">v{{ cardData.version }}</span>
        <span class="header-title">设计方案</span>
        <span v-if="cardData.parent_version" class="parent-hint">基于 v{{ cardData.parent_version }}</span>
        <span v-if="statusLabel" class="status-tag" :class="statusClass">{{ statusLabel }}</span>
      </div>
      <div class="header-right">
        <span v-if="envelope" class="conf-badge" :class="confClass">置信度 {{ confPct }}%</span>
        <button class="collapse-btn" :title="isCollapsed ? '展开' : '折叠'">
          <span>{{ isCollapsed ? '▸' : '▾' }}</span>
        </button>
      </div>
    </div>

    <!-- ── rationale 横条（trivial / iterate 时显示 LLM 说的修改原因） ── -->
    <div v-if="cardData.rationale" class="rationale-bar">
      <span class="rationale-icon">💬</span>
      <span class="rationale-text">{{ cardData.rationale }}</span>
    </div>

    <!-- ── refining 提示条（仅最新未确认卡） ── -->
    <div v-if="showRefiningHint" class="refining-bar">
      <span class="refining-spinner" />
      <span>AI 正在根据你的最新消息生成新版方案，新版到达后会出现在下方。</span>
    </div>

    <!-- ── 主体内容（折叠时隐藏） ── -->
    <div v-if="!isCollapsed" class="card-body">

      <!-- envelope 还没拉到：骨架屏 -->
      <div v-if="!envelope" class="skeleton">
        <div class="skel-line w-60" />
        <div class="skel-line w-90" />
        <div class="skel-line w-75" />
        <div class="skel-line w-50" />
      </div>

      <template v-else>
        <!-- 元信息 -->
        <div class="meta-row">
          <span class="meta-item">
            <span class="meta-key">组件名称：</span>
            <span class="meta-val">{{ envelope.identity.display_name }}</span>
            <code class="meta-code">{{ envelope.identity.code_name }}</code>
          </span>
          <code v-if="envelope.identity.widget_code" class="meta-widget">{{ envelope.identity.widget_code }}</code>
          <span class="meta-scene" :class="'scene-' + envelope.scene_type">{{ sceneLabel }}</span>
        </div>

        <div class="purpose-row">
          <span class="meta-key">功能概述：</span>{{ envelope.intent.core_purpose }}
        </div>
        <div v-if="envelope.intent.original_requirement" class="req-row">
          <span class="meta-key">原始需求：</span>{{ envelope.intent.original_requirement }}
        </div>

        <!-- 验收点 -->
        <section class="sec">
          <div class="sec-title">验收点</div>
          <ol class="ac-list">
            <li v-for="(ac, i) in envelope.intent.acceptance_criteria" :key="i">{{ ac }}</li>
          </ol>
        </section>

        <!-- 默认假设 -->
        <OpenQuestionsPanel :questions="envelope.provenance.open_questions || []" />

        <!-- 场景特定内容 -->
        <ComponentSpecSummary v-if="envelope.scene_type === 'web_component_dual'" :spec="envelope.spec" />
        <PageSpecSummary v-else-if="envelope.scene_type === 'web_page' || envelope.scene_type === 'mobile_page'" :spec="envelope.spec" />
        <BackendApiSpecSummary v-else-if="envelope.scene_type.startsWith('backend_')" :spec="envelope.spec" />
        <details v-else class="raw-fallback">
          <summary>原始 spec JSON</summary>
          <pre>{{ formattedSpec }}</pre>
        </details>

        <!-- 约束 -->
        <section v-if="constraintsHard.length || constraintsSoft.length" class="sec">
          <div class="sec-title">约束</div>
          <div v-if="constraintsHard.length" class="constraint-group">
            <div class="c-label">🔒 硬约束</div>
            <ul><li v-for="(c, i) in constraintsHard" :key="i" class="c-hard">{{ c }}</li></ul>
          </div>
          <div v-if="constraintsSoft.length" class="constraint-group">
            <div class="c-label">💡 软约束</div>
            <ul><li v-for="(c, i) in constraintsSoft" :key="i" class="c-soft">{{ c }}</li></ul>
          </div>
        </section>

        <!-- JSON 查看 -->
        <div class="json-row">
          <button class="json-btn" @click="showJson = !showJson">
            {{ showJson ? '收起' : '👁 查看' }}完整 JSON
          </button>
        </div>
        <pre v-if="showJson" class="raw-json">{{ formattedEnvelope }}</pre>
      </template>
    </div>

    <!-- ── 操作区（按状态切文案/可点性） ── -->
    <div v-if="!isCollapsed" class="card-actions">
      <!--
        优先级：
        1. refining（这张卡是最新但 AI 在生成新版）→ 隐藏按钮，挂状态块
        2. isConfirmed → 已用于代码生成（绿色标签）
        3. !isLatest → 已被新版替代（灰色标签）
        4. 其他（最新 + 未确认 + AI 没在生成新版）→ 显示确认按钮
      -->
      <div v-if="showRefiningHint" class="status-block status-refining">
        <span class="refining-spinner" />
        <span>AI 正在生成新版本，请稍候</span>
      </div>
      <div v-else-if="cardData.isConfirmed" class="status-block status-confirmed">
        <span class="status-icon">✓</span>
        <span>已用于代码生成</span>
      </div>
      <div v-else-if="!cardData.isLatest" class="status-block status-superseded">
        <span class="status-icon">↪</span>
        <span v-if="latestVersion">已被 v{{ latestVersion }} 替代</span>
        <span v-else>已是历史版本</span>
      </div>
      <button
        v-else
        class="btn btn-confirm"
        :disabled="!envelope || submitting"
        @click="$emit('confirm', cardData.spec_id)"
      >
        <span v-if="submitting" class="btn-spinner" />
        <span>{{ confirmLabel }}</span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { SpecCardData } from '@/stores/codingV2'
import OpenQuestionsPanel from './OpenQuestionsPanel.vue'
import ComponentSpecSummary from './ComponentSpecSummary.vue'
import PageSpecSummary from './PageSpecSummary.vue'
import BackendApiSpecSummary from './BackendApiSpecSummary.vue'

const props = defineProps<{
  cardData: SpecCardData
  /** 当前最新版的版本号（用于非 latest 卡显示"已被 vN 替代"），由父组件传入 */
  latestVersion?: number | null
  /** 用户点了确认按钮、HTTP 还在飞 */
  submitting?: boolean
  /** 最新且未确认 + 用户已发了 refine 消息但新版还没到 → 顶部展示一条提示 */
  refining?: boolean
}>()

defineEmits<{
  (e: 'confirm', specId: string): void
}>()

const showJson = ref(false)
// 折叠状态：组件内本地 ref，初始值跟 cardData.collapsed；用户点击时只动本地，
// 不写回 store（避免回放/外部状态变化把用户操作覆盖掉）。
// 但若 cardData.collapsed 从 false → true（外部把这张卡折叠掉，比如它被新版替代），
// 同步翻一下，让"被替代"动作有视觉反馈。
const isCollapsed = ref(props.cardData.collapsed)
watch(
  () => props.cardData.collapsed,
  (v) => { isCollapsed.value = v },
)
function toggleCollapse() { isCollapsed.value = !isCollapsed.value }

const envelope = computed(() => props.cardData.envelope)

const showRefiningHint = computed(
  () => !!props.refining && props.cardData.isLatest && !props.cardData.isConfirmed,
)

// 状态徽章
const statusLabel = computed<string | null>(() => {
  if (props.cardData.isConfirmed) return '已用于代码生成'
  if (props.cardData.isLatest) return '最新'
  return '历史'
})
const statusClass = computed(() => {
  if (props.cardData.isConfirmed) return 'tag-confirmed'
  if (props.cardData.isLatest) return 'tag-latest'
  return 'tag-history'
})
const versionBadgeClass = computed(() => {
  if (props.cardData.isConfirmed) return 'ver-confirmed'
  if (props.cardData.isLatest) return 'ver-latest'
  return 'ver-history'
})

// 确认按钮文案
const confirmLabel = computed(() => {
  if (props.submitting) return '正在启动生成…'
  if (props.refining) return '正在更新 Spec…'
  return '✅ 确认生成代码'
})

// envelope 派生（只在 envelope 存在时计算）
const sceneLabel = computed(() => {
  const e = envelope.value
  if (!e) return ''
  const map: Record<string, string> = {
    web_component_dual: '双端组件',
    web_page: 'PC 页面',
    mobile_page: '移动页面',
    backend_api: '后端接口',
    backend_feign: '外部接口',
    backend_scheduled: '定时任务',
  }
  return map[e.scene_type] || e.scene_type
})
const confPct = computed(() => {
  const e = envelope.value
  if (!e) return 0
  return Math.round(Math.max(0, Math.min(1, e.provenance.confidence)) * 100)
})
const confClass = computed(() => {
  const e = envelope.value
  if (!e) return 'conf-low'
  const c = e.provenance.confidence
  if (c >= 0.75) return 'conf-ok'
  if (c >= 0.5) return 'conf-warn'
  return 'conf-low'
})

const constraintsHard = computed<string[]>(() => (envelope.value?.spec as any)?.constraints_hard || [])
const constraintsSoft = computed<string[]>(() => (envelope.value?.spec as any)?.constraints_soft || [])

const formattedEnvelope = computed(() => envelope.value ? JSON.stringify(envelope.value, null, 2) : '')
const formattedSpec = computed(() => envelope.value ? JSON.stringify(envelope.value.spec, null, 2) : '')
</script>

<style scoped>
/* ── 卡片容器 ── */
.spec-card {
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  overflow: hidden;
  font-size: 14px;
  transition: border-color 200ms, opacity 200ms, background 200ms;
}
.spec-card.is-superseded {
  border-color: #e5e7eb;
  background: #fafafa;
  opacity: 0.78;
}
.spec-card.is-confirmed {
  border-color: #a7f3d0;
  background: #f0fdf4;
  opacity: 1;
}

/* ── Header ── */
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 18px;
  cursor: pointer;
  user-select: none;
  background: rgba(0,0,0,0.015);
  border-bottom: 1px solid #f3f4f6;
}
.is-collapsed .card-header { border-bottom: none; }
.spec-card.is-confirmed .card-header { background: rgba(16,185,129,0.06); }

.header-left, .header-right {
  display: flex; align-items: center; gap: 10px;
}

.version-badge {
  font-family: 'Menlo', monospace;
  font-size: 13px;
  font-weight: 600;
  padding: 2px 9px;
  border-radius: 6px;
  background: #f3f4f6;
  color: #4b5563;
}
.ver-latest { background: #dbeafe; color: #1d4ed8; }
.ver-confirmed { background: #d1fae5; color: #065f46; }
.ver-history { background: #f3f4f6; color: #6b7280; }

.header-title {
  font-size: 14px;
  font-weight: 600;
  color: #111827;
}
.parent-hint {
  font-size: 12px;
  color: #9ca3af;
}

.status-tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  font-weight: 500;
}
.tag-latest    { background: #dbeafe; color: #1d4ed8; }
.tag-confirmed { background: #d1fae5; color: #065f46; }
.tag-history   { background: #f3f4f6; color: #6b7280; }

.conf-badge {
  font-size: 12px;
  padding: 2px 10px;
  border-radius: 999px;
  font-weight: 500;
}
.conf-ok   { background: #d1fae5; color: #065f46; }
.conf-warn { background: #fef3c7; color: #92400e; }
.conf-low  { background: #fee2e2; color: #b91c1c; }

.collapse-btn {
  background: transparent;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 2px 9px;
  font-size: 11px;
  color: #6b7280;
  cursor: pointer;
}
.collapse-btn:hover { background: #f9fafb; color: #111827; }

/* ── rationale 横条 ── */
.rationale-bar {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px 18px;
  background: #fffbeb;
  border-bottom: 1px solid #fde68a;
  font-size: 13px;
  color: #92400e;
  line-height: 1.55;
}
.rationale-icon { font-size: 14px; flex-shrink: 0; }

/* ── refining 提示条 ── */
.refining-bar {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 18px;
  background: #eff6ff;
  border-bottom: 1px solid #bfdbfe;
  font-size: 13px;
  color: #1d4ed8;
}
.refining-spinner {
  width: 12px; height: 12px;
  border: 2px solid #bfdbfe;
  border-top-color: #1d4ed8;
  border-radius: 50%;
  animation: spin 700ms linear infinite;
}

/* ── 主体内容 ── */
.card-body {
  padding: 16px 0 0;
}

.skeleton {
  padding: 16px 24px;
  display: flex; flex-direction: column; gap: 10px;
}
.skel-line {
  height: 12px;
  background: linear-gradient(90deg, #f3f4f6 25%, #e5e7eb 50%, #f3f4f6 75%);
  background-size: 200% 100%;
  border-radius: 4px;
  animation: skeleton-shimmer 1.4s ease-in-out infinite;
}
.w-50 { width: 50%; } .w-60 { width: 60%; }
.w-75 { width: 75%; } .w-90 { width: 90%; }
@keyframes skeleton-shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

.meta-row {
  padding: 0 24px 8px;
  display: flex; align-items: center; flex-wrap: wrap; gap: 8px;
}
.meta-item { display: flex; align-items: center; gap: 4px; }
.meta-key  { color: #6b7280; font-size: 13px; }
.meta-val  { font-weight: 500; color: #111827; }
.meta-code {
  font-family: 'Menlo', monospace; font-size: 12px;
  color: #5b21b6; background: #f3f0ff; padding: 1px 6px; border-radius: 4px;
}
.meta-widget {
  font-family: 'Menlo', monospace; font-size: 12px;
  color: #1d4ed8; background: #dbeafe; padding: 1px 6px; border-radius: 4px;
}
.meta-scene { font-size: 12px; padding: 2px 8px; border-radius: 4px; }
.scene-web_component_dual { background: #f3e8ff; color: #6d28d9; }
.scene-web_page            { background: #dbeafe; color: #1d4ed8; }
.scene-mobile_page         { background: #cffafe; color: #0e7490; }
.scene-backend_api         { background: #d1fae5; color: #065f46; }
.scene-backend_feign       { background: #fef3c7; color: #92400e; }
.scene-backend_scheduled   { background: #f3f4f6; color: #374151; }

.purpose-row { padding: 4px 24px; font-size: 14px; color: #374151; line-height: 1.7; }
.req-row     { padding: 4px 24px 12px; font-size: 13px; color: #9ca3af; line-height: 1.6; }

.sec {
  padding: 16px 24px;
  border-top: 1px solid #f3f4f6;
}
.sec-title { font-size: 14px; font-weight: 700; color: #111827; margin-bottom: 12px; }

.ac-list { margin: 0; padding-left: 22px; display: flex; flex-direction: column; gap: 8px; }
.ac-list li { font-size: 14px; color: #374151; line-height: 1.7; }

.constraint-group { margin-bottom: 12px; }
.constraint-group:last-child { margin-bottom: 0; }
.c-label { font-size: 13px; font-weight: 500; color: #6b7280; margin-bottom: 6px; }
.constraint-group ul { margin: 0; padding-left: 20px; }
.constraint-group ul li { font-size: 14px; line-height: 1.7; padding: 3px 0; }
.c-hard { color: #b91c1c; }
.c-soft { color: #92400e; }

.json-row { padding: 12px 24px 8px; }
.json-btn {
  background: transparent; border: 1px dashed #d1d5db; color: #9ca3af;
  padding: 4px 12px; border-radius: 4px; font-size: 12px; cursor: pointer;
}
.json-btn:hover { background: #f9fafb; color: #374151; border-style: solid; }
.raw-json {
  margin: 0 24px 12px; background: #0f172a; border-radius: 6px;
  padding: 12px 14px; color: #e2e8f0; font-size: 11px;
  font-family: 'Menlo', monospace; max-height: 360px; overflow: auto;
}
.raw-fallback { margin: 16px 24px; background: #0f172a; border-radius: 6px; padding: 12px 14px; }
.raw-fallback summary { color: #94a3b8; font-size: 12px; cursor: pointer; }
.raw-fallback pre { margin: 8px 0 0; color: #e2e8f0; font-size: 11px; font-family: 'Menlo', monospace; max-height: 300px; overflow: auto; }

/* ── 操作区 ── */
.card-actions {
  display: flex; justify-content: flex-end; align-items: center;
  gap: 10px;
  padding: 14px 18px;
  background: #fafafa;
  border-top: 1px solid #f3f4f6;
}
.spec-card.is-confirmed .card-actions { background: rgba(16,185,129,0.06); }
.spec-card.is-superseded .card-actions { background: #f3f4f6; }

.btn {
  padding: 8px 20px; border-radius: 7px; border: none;
  cursor: pointer; font-size: 14px; font-weight: 500;
  transition: all 120ms;
}
.btn-confirm { background: #10b981; color: white; display: inline-flex; align-items: center; gap: 8px; }
.btn-confirm:hover:not(:disabled) { background: #059669; }
.btn-confirm:disabled { background: #a7f3d0; cursor: not-allowed; opacity: 0.85; }
.btn-spinner {
  width: 13px; height: 13px;
  border: 2px solid rgba(255,255,255,0.45);
  border-top-color: white; border-radius: 50%;
  animation: spin 600ms linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.status-block {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 7px 14px; border-radius: 7px;
  font-size: 13px; font-weight: 500;
}
.status-confirmed { background: #d1fae5; color: #065f46; }
.status-superseded { background: #f3f4f6; color: #6b7280; }
.status-refining   { background: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe; }
.status-icon { font-size: 14px; }
.status-refining .refining-spinner {
  width: 13px; height: 13px;
  border: 2px solid #bfdbfe;
  border-top-color: #1d4ed8;
  border-radius: 50%;
  animation: spin 700ms linear infinite;
}
</style>
