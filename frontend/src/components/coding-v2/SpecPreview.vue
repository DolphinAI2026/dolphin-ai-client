<template>
  <div class="spec-doc">

    <!-- ── 文档头 ── -->
    <div class="doc-head">
      <div class="doc-title-row">
        <span class="doc-title-icon">📋</span>
        <span class="doc-title-text">设计方案确认</span>
        <span class="conf-badge" :class="confClass">置信度 {{ confPct }}% · {{ confLabel }}</span>
      </div>

      <div class="doc-meta">
        <span class="meta-item">
          <span class="meta-key">组件名称：</span>
          <span class="meta-val">{{ envelope.identity.display_name }}</span>
          <code class="meta-code">{{ envelope.identity.code_name }}</code>
        </span>
        <span v-if="envelope.identity.widget_code" class="meta-sep">代码标识：</span>
        <code v-if="envelope.identity.widget_code" class="meta-widget">{{ envelope.identity.widget_code }}</code>
        <span class="meta-scene" :class="'scene-' + envelope.scene_type">{{ sceneLabel }}</span>
        <span class="meta-ver">v{{ envelope.provenance.version }}</span>
      </div>

      <div class="doc-purpose">
        <span class="meta-key">功能概述：</span>{{ envelope.intent.core_purpose }}
      </div>
      <div v-if="envelope.intent.original_requirement" class="doc-req">
        <span class="meta-key">原始需求：</span>{{ envelope.intent.original_requirement }}
      </div>
    </div>

    <!-- ── 验收点 ── -->
    <div class="doc-section">
      <div class="sec-title">验收点</div>
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
      <div class="sec-title">约束</div>
      <div v-if="constraintsHard.length" class="constraint-group">
        <div class="c-label">🔒 硬约束</div>
        <ul><li v-for="(c, i) in constraintsHard" :key="i" class="c-hard">{{ c }}</li></ul>
      </div>
      <div v-if="constraintsSoft.length" class="constraint-group">
        <div class="c-label">💡 软约束</div>
        <ul><li v-for="(c, i) in constraintsSoft" :key="i" class="c-soft">{{ c }}</li></ul>
      </div>
    </div>

    <!-- ── JSON 查看 ── -->
    <div class="json-row">
      <button class="json-btn" @click="showJson = !showJson">
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
/* ── 容器 ── */
.spec-doc {
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  overflow: hidden;
  font-size: 14px;
}

/* ── 文档头 ── */
.doc-head {
  padding: 20px 24px 18px;
  border-bottom: 1px solid #e5e7eb;
  display: flex;
  flex-direction: column;
  gap: 10px;
  background: #fafafa;
}

.doc-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.doc-title-icon { font-size: 15px; }
.doc-title-text {
  font-size: 14px;
  font-weight: 600;
  color: #374151;
  flex: 1;
}
.conf-badge {
  font-size: 12px;
  padding: 2px 10px;
  border-radius: 999px;
  font-weight: 500;
}
.conf-ok   { background: #d1fae5; color: #065f46; }
.conf-warn { background: #fef3c7; color: #92400e; }
.conf-low  { background: #fee2e2; color: #b91c1c; }

.doc-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 14px;
  color: #111827;
}
.meta-item {
  display: flex;
  align-items: center;
  gap: 4px;
}
.meta-key {
  color: #6b7280;
  font-size: 13px;
}
.meta-val {
  font-weight: 500;
  color: #111827;
}
.meta-code {
  font-family: 'Menlo', 'Monaco', monospace;
  font-size: 12px;
  color: #5b21b6;
  background: #f3f0ff;
  padding: 1px 6px;
  border-radius: 4px;
}
.meta-sep {
  color: #6b7280;
  font-size: 13px;
  margin-left: 4px;
}
.meta-widget {
  font-family: 'Menlo', 'Monaco', monospace;
  font-size: 12px;
  color: #1d4ed8;
  background: #dbeafe;
  padding: 1px 6px;
  border-radius: 4px;
}
.meta-scene {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 4px;
  margin-left: 4px;
}
.scene-web_component_dual { background: #f3e8ff; color: #6d28d9; }
.scene-web_page            { background: #dbeafe; color: #1d4ed8; }
.scene-mobile_page         { background: #cffafe; color: #0e7490; }
.scene-backend_api         { background: #d1fae5; color: #065f46; }
.scene-backend_feign       { background: #fef3c7; color: #92400e; }
.scene-backend_scheduled   { background: #f3f4f6; color: #374151; }

.meta-ver {
  font-size: 12px;
  color: #9ca3af;
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  padding: 1px 7px;
  border-radius: 4px;
}

.doc-purpose {
  font-size: 14px;
  color: #374151;
  line-height: 1.7;
}
.doc-req {
  font-size: 13px;
  color: #9ca3af;
  line-height: 1.6;
}

/* ── Section ── */
.doc-section {
  padding: 20px 24px;
  border-bottom: 1px solid #f3f4f6;
}

.sec-title {
  font-size: 14px;
  font-weight: 700;
  color: #111827;
  margin-bottom: 14px;
}

/* ── 验收点 ── */
.ac-list {
  margin: 0;
  padding-left: 22px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.ac-list li {
  font-size: 14px;
  color: #374151;
  line-height: 1.7;
}

/* ── 约束 ── */
.constraint-group { margin-bottom: 12px; }
.constraint-group:last-child { margin-bottom: 0; }
.c-label { font-size: 13px; font-weight: 500; color: #6b7280; margin-bottom: 6px; }
.constraint-group ul { margin: 0; padding-left: 20px; }
.constraint-group ul li { font-size: 14px; line-height: 1.7; padding: 3px 0; }
.c-hard { color: #b91c1c; }
.c-soft { color: #92400e; }

/* ── JSON ── */
.json-row { padding: 10px 24px; }
.json-btn {
  background: transparent;
  border: 1px dashed #d1d5db;
  color: #9ca3af;
  padding: 4px 12px;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
  transition: all 120ms;
}
.json-btn:hover { background: #f9fafb; color: #374151; border-style: solid; }

.raw-json {
  margin: 0 24px 12px;
  background: #0f172a;
  border-radius: 6px;
  padding: 12px 14px;
  color: #e2e8f0;
  font-size: 11px;
  font-family: 'Menlo', 'Monaco', monospace;
  max-height: 360px;
  overflow: auto;
}
.raw-fallback {
  margin: 16px 24px;
  background: #0f172a;
  border-radius: 6px;
  padding: 12px 14px;
}
.raw-fallback summary { color: #94a3b8; font-size: 12px; cursor: pointer; }
.raw-fallback pre { margin: 8px 0 0; color: #e2e8f0; font-size: 11px; font-family: 'Menlo', 'Monaco', monospace; max-height: 300px; overflow: auto; }

/* ── 操作按钮 ── */
.doc-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 16px 24px;
  background: #fafafa;
  border-top: 1px solid #f3f4f6;
}
.btn {
  padding: 8px 20px;
  border-radius: 7px;
  border: none;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
  transition: all 120ms;
}
.btn-ghost { background: transparent; color: #6b7280; border: 1px solid #e5e7eb; }
.btn-ghost:hover { background: #f3f4f6; color: #111827; }
.btn-confirm { background: #10b981; color: white; }
.btn-confirm:hover { background: #059669; }
</style>
