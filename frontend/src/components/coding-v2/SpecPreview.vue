<template>
  <div class="spec-doc">

    <!-- ── 文档头 ── -->
    <div class="doc-head">
      <div class="head-row1">
        <span class="doc-name">{{ envelope.identity.display_name }}</span>
        <span class="head-chips">
          <code class="chip chip-code">{{ envelope.identity.code_name }}</code>
          <code v-if="envelope.identity.widget_code" class="chip chip-widget">
            {{ envelope.identity.widget_code }}
          </code>
          <span class="chip chip-scene" :class="'scene-' + envelope.scene_type">{{ sceneLabel }}</span>
          <span class="chip chip-ver">v{{ envelope.provenance.version }}</span>
        </span>
      </div>

      <!-- 置信度 -->
      <div class="conf-row">
        <div class="conf-bar-wrap">
          <div class="conf-bar" :class="confClass" :style="{ width: confPct + '%' }" />
        </div>
        <span class="conf-pct">置信度 {{ confPct }}%</span>
        <span class="conf-badge" :class="confClass">{{ confLabel }}</span>
      </div>

      <p class="doc-purpose">{{ envelope.intent.core_purpose }}</p>
      <p v-if="envelope.intent.original_requirement" class="doc-req">
        <span class="req-label">原始需求</span>{{ envelope.intent.original_requirement }}
      </p>
    </div>

    <!-- ── 验收点 ── -->
    <div class="doc-section">
      <div class="sec-label">验收点</div>
      <ol class="ac-list">
        <li v-for="(ac, i) in envelope.intent.acceptance_criteria" :key="i">{{ ac }}</li>
      </ol>
    </div>

    <!-- ── 默认假设 ── -->
    <OpenQuestionsPanel :questions="envelope.provenance.open_questions || []" />

    <!-- ── 场景特定内容 ── -->
    <ComponentSpecSummary v-if="envelope.scene_type === 'web_component_dual'" :spec="envelope.spec" />
    <PageSpecSummary v-else-if="envelope.scene_type === 'web_page' || envelope.scene_type === 'mobile_page'" :spec="envelope.spec" />
    <BackendApiSpecSummary v-else-if="envelope.scene_type.startsWith('backend_')" :spec="envelope.spec" />
    <details v-else class="raw-fallback">
      <summary>原始 spec JSON</summary>
      <pre>{{ formattedSpec }}</pre>
    </details>

    <!-- ── 约束 ── -->
    <div v-if="constraintsHard.length || constraintsSoft.length" class="doc-section">
      <div class="sec-label">约束</div>
      <div v-if="constraintsHard.length" class="constraint-group hard">
        <span class="c-prefix">🔒 硬约束</span>
        <ul><li v-for="(c, i) in constraintsHard" :key="i">{{ c }}</li></ul>
      </div>
      <div v-if="constraintsSoft.length" class="constraint-group soft">
        <span class="c-prefix">💡 软约束</span>
        <ul><li v-for="(c, i) in constraintsSoft" :key="i">{{ c }}</li></ul>
      </div>
    </div>

    <!-- ── JSON 查看 ── -->
    <div class="json-row">
      <button class="json-btn" @click="showJson = !showJson">
        {{ showJson ? '收起' : '👁 查看' }}完整 JSON
      </button>
    </div>
    <pre v-if="showJson" class="raw-json">{{ formattedEnvelope }}</pre>

    <!-- ── 操作按钮（confirm 阶段） ── -->
    <div v-if="allowActions" class="doc-actions">
      <button class="btn btn-ghost" @click="$emit('cancel')">取消</button>
      <button class="btn btn-confirm" @click="$emit('confirm')">✅ 确认生成代码</button>
    </div>

  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { SpecEnvelope } from '@/api/codingV2'
import OpenQuestionsPanel from './OpenQuestionsPanel.vue'
import ComponentSpecSummary from './ComponentSpecSummary.vue'
import PageSpecSummary from './PageSpecSummary.vue'
import BackendApiSpecSummary from './BackendApiSpecSummary.vue'

const props = defineProps<{
  envelope: SpecEnvelope
  allowActions?: boolean
}>()

defineEmits<{
  (e: 'confirm'): void
  (e: 'cancel'): void
}>()

const showJson = ref(false)

const sceneLabel = computed(() => {
  const map: Record<string, string> = {
    web_component_dual: '双端组件',
    web_page: 'PC 页面',
    mobile_page: '移动页面',
    backend_api: '后端接口',
    backend_feign: '外部接口',
    backend_scheduled: '定时任务',
  }
  return map[props.envelope.scene_type] || props.envelope.scene_type
})

const confPct = computed(() =>
  Math.round(Math.max(0, Math.min(1, props.envelope.provenance.confidence)) * 100),
)
const confClass = computed(() => {
  const c = props.envelope.provenance.confidence
  if (c >= 0.75) return 'conf-ok'
  if (c >= 0.5) return 'conf-warn'
  return 'conf-low'
})
const confLabel = computed(() => {
  const c = props.envelope.provenance.confidence
  if (c >= 0.75) return '高'
  if (c >= 0.5) return '中'
  return '低'
})

const constraintsHard = computed<string[]>(() => (props.envelope.spec as any)?.constraints_hard || [])
const constraintsSoft = computed<string[]>(() => (props.envelope.spec as any)?.constraints_soft || [])

const formattedEnvelope = computed(() => JSON.stringify(props.envelope, null, 2))
const formattedSpec = computed(() => JSON.stringify(props.envelope.spec, null, 2))
</script>

<style scoped>
/* ── 容器 ── */
.spec-doc {
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  overflow: hidden;
  font-size: 13px;
}

/* ── 文档头 ── */
.doc-head {
  padding: 16px 20px 14px;
  border-bottom: 2px solid #f3f4f6;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.head-row1 {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.doc-name {
  font-size: 18px;
  font-weight: 700;
  color: #111827;
  letter-spacing: -0.01em;
}

.head-chips {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.chip {
  display: inline-flex;
  align-items: center;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  font-family: inherit;
  white-space: nowrap;
}
.chip-code {
  font-family: 'Menlo', 'Monaco', monospace;
  background: #ede9fe;
  color: #5b21b6;
  border: 1px solid #ddd6fe;
}
.chip-widget {
  font-family: 'Menlo', 'Monaco', monospace;
  background: #dbeafe;
  color: #1e40af;
  border: 1px solid #bfdbfe;
}
.chip-scene {
  font-weight: 500;
}
.scene-web_component_dual { background: #f3e8ff; color: #6d28d9; border: 1px solid #e9d5ff; }
.scene-web_page            { background: #dbeafe; color: #1d4ed8; border: 1px solid #bfdbfe; }
.scene-mobile_page         { background: #cffafe; color: #0e7490; border: 1px solid #a5f3fc; }
.scene-backend_api         { background: #d1fae5; color: #065f46; border: 1px solid #a7f3d0; }
.scene-backend_feign       { background: #fef3c7; color: #92400e; border: 1px solid #fde68a; }
.scene-backend_scheduled   { background: #f3f4f6; color: #374151; border: 1px solid #e5e7eb; }

.chip-ver {
  background: #f9fafb;
  color: #9ca3af;
  border: 1px solid #e5e7eb;
  font-variant-numeric: tabular-nums;
}

/* ── 置信度 ── */
.conf-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.conf-bar-wrap {
  width: 100px;
  height: 6px;
  background: #e5e7eb;
  border-radius: 3px;
  overflow: hidden;
  flex-shrink: 0;
}
.conf-bar {
  height: 100%;
  border-radius: 3px;
  transition: width 300ms ease;
}
.conf-ok  .conf-bar, .conf-bar.conf-ok  { background: #10b981; }
.conf-warn .conf-bar, .conf-bar.conf-warn { background: #f59e0b; }
.conf-low  .conf-bar, .conf-bar.conf-low  { background: #ef4444; }

.conf-pct { font-size: 12px; color: #6b7280; font-variant-numeric: tabular-nums; }

.conf-badge {
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 999px;
}
.conf-badge.conf-ok   { background: #d1fae5; color: #047857; }
.conf-badge.conf-warn { background: #fef3c7; color: #92400e; }
.conf-badge.conf-low  { background: #fee2e2; color: #b91c1c; }

.doc-purpose {
  margin: 0;
  font-size: 13px;
  color: #374151;
  line-height: 1.6;
}
.doc-req {
  margin: 0;
  font-size: 12px;
  color: #9ca3af;
  line-height: 1.5;
}
.req-label {
  display: inline-block;
  margin-right: 6px;
  color: #d1d5db;
}

/* ── Section ── */
.doc-section {
  padding: 14px 20px;
  border-bottom: 1px solid #f3f4f6;
}
.sec-label {
  font-size: 12px;
  font-weight: 600;
  color: #6b7280;
  margin-bottom: 10px;
  padding-left: 8px;
  border-left: 3px solid #8b5cf6;
  line-height: 1;
}

/* ── 验收点 ── */
.ac-list {
  margin: 0;
  padding-left: 20px;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.ac-list li {
  font-size: 13px;
  color: #1f2937;
  line-height: 1.6;
}

/* ── 约束 ── */
.constraint-group { margin-bottom: 10px; }
.constraint-group:last-child { margin-bottom: 0; }
.c-prefix { font-size: 12px; color: #6b7280; font-weight: 500; }
.constraint-group ul { margin: 5px 0 0; padding-left: 20px; }
.constraint-group ul li { font-size: 13px; line-height: 1.6; padding: 2px 0; }
.hard ul li { color: #b91c1c; }
.soft ul li { color: #92400e; }

/* ── JSON ── */
.json-row { padding: 8px 20px; }
.json-btn {
  background: transparent;
  border: 1px dashed #d1d5db;
  color: #9ca3af;
  padding: 3px 10px;
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
  transition: all 120ms;
}
.json-btn:hover { background: #f9fafb; color: #374151; border-style: solid; }

.raw-json {
  margin: 0 20px 12px;
  background: #0f172a;
  border-radius: 6px;
  padding: 10px 14px;
  color: #e2e8f0;
  font-size: 11px;
  font-family: 'Menlo', 'Monaco', monospace;
  max-height: 360px;
  overflow: auto;
}
.raw-fallback {
  margin: 12px 20px;
  background: #0f172a;
  border-radius: 6px;
  padding: 10px 14px;
}
.raw-fallback summary { color: #94a3b8; font-size: 12px; cursor: pointer; }
.raw-fallback pre { margin: 8px 0 0; color: #e2e8f0; font-size: 11px; font-family: 'Menlo', 'Monaco', monospace; max-height: 300px; overflow: auto; }

/* ── 操作按钮 ── */
.doc-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 12px 20px;
  background: #fafafa;
  border-top: 1px solid #f3f4f6;
}
.btn {
  padding: 8px 18px;
  border-radius: 7px;
  border: none;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  transition: all 120ms;
}
.btn-ghost {
  background: transparent;
  color: #6b7280;
  border: 1px solid #e5e7eb;
}
.btn-ghost:hover { background: #f3f4f6; color: #111827; }
.btn-confirm { background: #10b981; color: white; }
.btn-confirm:hover { background: #059669; }
</style>
