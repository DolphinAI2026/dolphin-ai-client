<template>
  <div class="spec-doc">
    <!-- ── 文档头 ── -->
    <div class="doc-head">
      <div class="head-main">
        <span class="doc-name">{{ envelope.identity.display_name }}</span>
        <code class="code-chip chip-code">{{ envelope.identity.code_name }}</code>
        <code v-if="envelope.identity.widget_code" class="code-chip chip-widget">
          {{ envelope.identity.widget_code }}
        </code>
        <span class="scene-tag" :class="'scene-' + envelope.scene_type">{{ sceneLabel }}</span>
        <span class="ver-tag">v{{ envelope.provenance.version }}</span>
      </div>
      <div class="head-sub">
        <span class="confidence-inline" :class="confClass">
          <span class="conf-bar-wrap"><span class="conf-bar" :style="{ width: confPct + '%' }" /></span>
          <span class="conf-txt">置信度 {{ confPct }}%</span>
          <span class="conf-tag">{{ confLabel }}</span>
        </span>
      </div>
      <p class="doc-purpose">{{ envelope.intent.core_purpose }}</p>
      <p v-if="envelope.intent.original_requirement" class="doc-req">
        <span class="req-label">原始需求</span>{{ envelope.intent.original_requirement }}
      </p>
    </div>

    <!-- ── 验收点 ── -->
    <section class="doc-section">
      <h4 class="sec-heading">验收点</h4>
      <ol class="ac-list">
        <li v-for="(ac, i) in envelope.intent.acceptance_criteria" :key="i">{{ ac }}</li>
      </ol>
    </section>

    <!-- ── 默认假设 ── -->
    <OpenQuestionsPanel :questions="envelope.provenance.open_questions || []" />

    <!-- ── 场景特定 ── -->
    <ComponentSpecSummary v-if="envelope.scene_type === 'web_component_dual'" :spec="envelope.spec" />
    <PageSpecSummary v-else-if="envelope.scene_type === 'web_page' || envelope.scene_type === 'mobile_page'" :spec="envelope.spec" />
    <BackendApiSpecSummary v-else-if="envelope.scene_type.startsWith('backend_')" :spec="envelope.spec" />
    <details v-else class="raw-spec">
      <summary>原始 spec JSON</summary>
      <pre>{{ formattedSpec }}</pre>
    </details>

    <!-- ── 约束 ── -->
    <section v-if="constraintsHard.length || constraintsSoft.length" class="doc-section">
      <h4 class="sec-heading">约束</h4>
      <div v-if="constraintsHard.length" class="constraint-group">
        <span class="clabel">🔒 硬约束</span>
        <ul><li v-for="(c, i) in constraintsHard" :key="i" class="c-hard">{{ c }}</li></ul>
      </div>
      <div v-if="constraintsSoft.length" class="constraint-group">
        <span class="clabel">💡 软约束</span>
        <ul><li v-for="(c, i) in constraintsSoft" :key="i" class="c-soft">{{ c }}</li></ul>
      </div>
    </section>

    <!-- ── JSON 查看 ── -->
    <div class="json-toggle">
      <button class="toggle-btn" @click="showJson = !showJson">
        {{ showJson ? '收起' : '👁 查看' }}完整 JSON
      </button>
    </div>
    <pre v-if="showJson" class="raw-json">{{ formattedEnvelope }}</pre>

    <!-- ── 操作按钮 ── -->
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
/* ── 文档容器 ── */
.spec-doc {
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

/* ── 文档头 ── */
.doc-head {
  padding: 14px 18px 12px;
  border-bottom: 1px solid #f3f4f6;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.head-main {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
}
.doc-name {
  font-size: 16px;
  font-weight: 700;
  color: #111827;
}
.code-chip {
  font-size: 11px;
  font-family: 'Menlo', 'Monaco', monospace;
  padding: 2px 7px;
  border-radius: 4px;
}
.chip-code {
  background: #ede9fe;
  color: #5b21b6;
  border: 1px solid #ddd6fe;
}
.chip-widget {
  background: #dbeafe;
  color: #1e40af;
  border: 1px solid #bfdbfe;
}
.scene-tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  font-weight: 500;
}
.scene-web_component_dual { background: #f3e8ff; color: #6d28d9; }
.scene-web_page { background: #dbeafe; color: #1d4ed8; }
.scene-mobile_page { background: #cffafe; color: #0e7490; }
.scene-backend_api { background: #d1fae5; color: #065f46; }
.scene-backend_feign { background: #fef3c7; color: #92400e; }
.scene-backend_scheduled { background: #f3f4f6; color: #374151; }
.ver-tag {
  font-size: 11px;
  color: #9ca3af;
  padding: 2px 7px;
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 4px;
  font-variant-numeric: tabular-nums;
}

/* ── 置信度 ── */
.head-sub { display: flex; align-items: center; }
.confidence-inline {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
}
.conf-bar-wrap {
  width: 80px;
  height: 4px;
  background: #e5e7eb;
  border-radius: 2px;
  overflow: hidden;
}
.conf-bar {
  height: 100%;
  border-radius: 2px;
  transition: width 200ms;
}
.conf-ok .conf-bar { background: #10b981; }
.conf-warn .conf-bar { background: #f59e0b; }
.conf-low .conf-bar { background: #ef4444; }
.conf-txt { color: #6b7280; font-variant-numeric: tabular-nums; }
.conf-tag {
  padding: 1px 6px;
  border-radius: 999px;
  font-size: 11px;
}
.conf-ok .conf-tag { background: #d1fae5; color: #047857; }
.conf-warn .conf-tag { background: #fef3c7; color: #92400e; }
.conf-low .conf-tag { background: #fee2e2; color: #b91c1c; }

.doc-purpose {
  margin: 0;
  font-size: 13px;
  color: #374151;
  line-height: 1.55;
}
.doc-req {
  margin: 0;
  font-size: 12px;
  color: #6b7280;
  line-height: 1.55;
}
.req-label {
  display: inline-block;
  margin-right: 6px;
  color: #9ca3af;
}

/* ── 通用 section ── */
.doc-section {
  padding: 12px 18px;
  border-bottom: 1px solid #f3f4f6;
}
.sec-heading {
  font-size: 12px;
  font-weight: 600;
  color: #6b7280;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin: 0 0 8px;
}

/* ── 验收点 ── */
.ac-list {
  margin: 0;
  padding-left: 20px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.ac-list li {
  font-size: 13px;
  color: #1f2937;
  line-height: 1.55;
}

/* ── 约束 ── */
.constraint-group { margin-bottom: 8px; }
.constraint-group:last-child { margin-bottom: 0; }
.clabel { font-size: 12px; color: #6b7280; }
.constraint-group ul { margin: 4px 0 0; padding-left: 20px; }
.constraint-group ul li { font-size: 13px; line-height: 1.55; padding: 2px 0; }
.c-hard { color: #b91c1c; }
.c-soft { color: #92400e; }

/* ── JSON ── */
.json-toggle { padding: 8px 18px; }
.toggle-btn {
  background: transparent;
  border: 1px dashed #d1d5db;
  color: #6b7280;
  padding: 3px 10px;
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
}
.toggle-btn:hover { background: #f9fafb; color: #111827; }
.raw-json {
  margin: 0 18px 12px;
  background: #0f172a;
  border-radius: 6px;
  padding: 10px 12px;
  color: #e2e8f0;
  font-size: 11px;
  font-family: 'Menlo', 'Monaco', monospace;
  max-height: 360px;
  overflow: auto;
}
.raw-spec {
  margin: 0 18px 12px;
  background: #0f172a;
  border-radius: 6px;
  padding: 10px 12px;
}
.raw-spec summary { color: #94a3b8; font-size: 12px; cursor: pointer; }
.raw-spec pre {
  margin: 8px 0 0;
  color: #e2e8f0;
  font-size: 11px;
  font-family: 'Menlo', 'Monaco', monospace;
  max-height: 300px;
  overflow: auto;
}

/* ── 操作按钮 ── */
.doc-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 12px 18px;
  border-top: 1px solid #f3f4f6;
  background: #fafafa;
}
.btn {
  padding: 7px 16px;
  border-radius: 7px;
  border: none;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
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
