<template>
  <div class="spec-preview">
    <div class="header">
      <div class="title-row">
        <span class="badge" :class="'scene-' + envelope.scene_type">{{ sceneLabel }}</span>
        <h2 class="title">{{ envelope.identity.display_name }}</h2>
        <span class="version">v{{ envelope.provenance.version }}</span>
      </div>
      <ConfidenceIndicator :confidence="envelope.provenance.confidence" />
    </div>

    <div class="meta">
      <div><span class="k">code_name</span><code>{{ envelope.identity.code_name }}</code></div>
      <div v-if="envelope.identity.widget_code">
        <span class="k">widget_code</span><code>{{ envelope.identity.widget_code }}</code>
      </div>
      <div><span class="k">核心目的</span>{{ envelope.intent.core_purpose }}</div>
      <div class="original">
        <span class="k">原始需求</span><span class="q">{{ envelope.intent.original_requirement }}</span>
      </div>
    </div>

    <section class="block ac-block">
      <h3>验收点（Acceptance Criteria）</h3>
      <ol class="ac-list">
        <li v-for="(ac, i) in envelope.intent.acceptance_criteria" :key="i">{{ ac }}</li>
      </ol>
    </section>

    <OpenQuestionsPanel :questions="envelope.provenance.open_questions || []" />

    <!-- 场景特定 -->
    <ComponentSpecSummary v-if="envelope.scene_type === 'web_component_dual'" :spec="envelope.spec" />
    <PageSpecSummary v-else-if="envelope.scene_type === 'web_page' || envelope.scene_type === 'mobile_page'" :spec="envelope.spec" />
    <BackendApiSpecSummary v-else-if="envelope.scene_type.startsWith('backend_')" :spec="envelope.spec" />
    <details v-else class="raw-spec">
      <summary>原始 spec JSON</summary>
      <pre>{{ formattedSpec }}</pre>
    </details>

    <!-- 约束 -->
    <section
      v-if="constraintsHard.length || constraintsSoft.length"
      class="block constraints"
    >
      <h3>约束</h3>
      <div v-if="constraintsHard.length" class="hard">
        <div class="clabel">🔒 硬约束</div>
        <ul><li v-for="(c, i) in constraintsHard" :key="i">{{ c }}</li></ul>
      </div>
      <div v-if="constraintsSoft.length" class="soft">
        <div class="clabel">💡 软约束</div>
        <ul><li v-for="(c, i) in constraintsSoft" :key="i">{{ c }}</li></ul>
      </div>
    </section>

    <div class="json-toggle">
      <button class="toggle-btn" @click="showJson = !showJson">
        {{ showJson ? '隐藏' : '👁️ 查看' }}完整 JSON
      </button>
    </div>
    <details :open="showJson" v-if="showJson" class="raw-json">
      <summary>Spec Envelope JSON</summary>
      <pre>{{ formattedEnvelope }}</pre>
    </details>

    <div class="actions">
      <button v-if="allowActions" class="btn btn-secondary" @click="$emit('cancel')">
        ❌ 取消
      </button>
      <button v-if="allowActions" class="btn btn-primary" @click="$emit('confirm')">
        ✅ 确认生成代码
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { SpecEnvelope } from '@/api/codingV2'
import ConfidenceIndicator from './ConfidenceIndicator.vue'
import OpenQuestionsPanel from './OpenQuestionsPanel.vue'
import ComponentSpecSummary from './ComponentSpecSummary.vue'
import PageSpecSummary from './PageSpecSummary.vue'
import BackendApiSpecSummary from './BackendApiSpecSummary.vue'

const props = defineProps<{
  envelope: SpecEnvelope
  allowActions?: boolean  // CONFIRM phase 时 true
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
    backend_feign: '外部接口调用',
    backend_scheduled: '定时任务',
  }
  return map[props.envelope.scene_type] || props.envelope.scene_type
})

const constraintsHard = computed<string[]>(() => (props.envelope.spec as any)?.constraints_hard || [])
const constraintsSoft = computed<string[]>(() => (props.envelope.spec as any)?.constraints_soft || [])

const formattedEnvelope = computed(() => JSON.stringify(props.envelope, null, 2))
const formattedSpec = computed(() => JSON.stringify(props.envelope.spec, null, 2))
</script>

<style scoped>
.spec-preview {
  background: white;
  border-radius: 12px;
  padding: 20px 24px;
  border: 1px solid #e5e7eb;
  display: flex;
  flex-direction: column;
  gap: 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}
.header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid #f3f4f6;
}
.title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.title { margin: 0; font-size: 18px; color: #111827; }
.badge {
  padding: 3px 10px;
  border-radius: 6px;
  font-size: 12px;
  color: white;
  font-weight: 500;
}
.scene-web_component_dual { background: #8b5cf6; }
.scene-web_page { background: #3b82f6; }
.scene-mobile_page { background: #06b6d4; }
.scene-backend_api { background: #10b981; }
.scene-backend_feign { background: #f59e0b; }
.scene-backend_scheduled { background: #6b7280; }
.version {
  padding: 2px 8px;
  background: #f3f4f6;
  border-radius: 999px;
  color: #6b7280;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
.meta { display: flex; flex-direction: column; gap: 6px; font-size: 13px; color: #374151; }
.meta > div { display: flex; gap: 6px; align-items: flex-start; }
.k { min-width: 80px; color: #6b7280; font-size: 12px; flex-shrink: 0; }
.original .q { color: #4b5563; font-style: italic; }
code {
  background: #f3f4f6;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 12px;
  color: #0f172a;
}
.block h3 {
  font-size: 14px;
  margin: 0 0 8px;
  color: #1f2937;
  font-weight: 600;
}
.ac-list {
  margin: 0;
  padding-left: 22px;
  color: #374151;
  font-size: 13px;
}
.ac-list li { padding: 3px 0; }
.constraints {
  background: #f9fafb;
  border-radius: 8px;
  padding: 12px 14px;
}
.constraints ul { margin: 4px 0; padding-left: 22px; font-size: 13px; }
.clabel { font-size: 12px; color: #6b7280; margin-top: 6px; }
.clabel:first-child { margin-top: 0; }
.hard ul li { color: #b91c1c; }
.soft ul li { color: #92400e; }
.json-toggle { text-align: right; }
.toggle-btn {
  background: transparent;
  border: 1px dashed #d1d5db;
  color: #6b7280;
  padding: 4px 12px;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
}
.toggle-btn:hover { background: #f9fafb; color: #111827; }
.raw-json, .raw-spec {
  background: #0f172a;
  border-radius: 6px;
  padding: 12px;
}
.raw-json summary, .raw-spec summary {
  color: #cbd5e1;
  font-size: 12px;
  cursor: pointer;
  margin-bottom: 8px;
}
.raw-json pre, .raw-spec pre {
  margin: 0;
  color: #e2e8f0;
  font-size: 11px;
  font-family: Menlo, Monaco, monospace;
  max-height: 400px;
  overflow: auto;
}
.actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding-top: 12px;
  border-top: 1px solid #f3f4f6;
}
.btn {
  padding: 8px 16px;
  border-radius: 6px;
  border: none;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
}
.btn-primary { background: #10b981; color: white; }
.btn-primary:hover { background: #059669; }
.btn-secondary { background: #f3f4f6; color: #374151; border: 1px solid #e5e7eb; }
.btn-secondary:hover { background: #e5e7eb; }
</style>
