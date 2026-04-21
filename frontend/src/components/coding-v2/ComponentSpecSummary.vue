<template>
  <div class="comp-spec">

    <!-- ── 数据存储 ── -->
    <div v-if="data" class="doc-section">
      <div class="sec-title">数据存储</div>
      <table class="data-table">
        <thead>
          <tr>
            <th>字段</th>
            <th>值</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td class="field-name">BOF 类型</td>
            <td><code class="val-code">{{ data.bof_type }}</code></td>
          </tr>
          <tr v-if="data.component_model_field?.length">
            <td class="field-name">存储字段</td>
            <td>
              <code
                v-for="f in data.component_model_field"
                :key="f"
                class="val-code field-chip"
              >{{ f }}</code>
            </td>
          </tr>
          <tr>
            <td class="field-name">值形态</td>
            <td><code class="val-code">{{ data.form_value_shape }}</code></td>
          </tr>
          <tr v-if="data.default_value !== undefined">
            <td class="field-name">默认值</td>
            <td><code class="val-code">{{ data.default_value }}</code></td>
          </tr>
          <tr v-if="data.storage_note">
            <td class="field-name">备注</td>
            <td class="field-note">{{ data.storage_note }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- ── 配置项 ── -->
    <div v-if="configProps.length" class="doc-section">
      <div class="sec-title">配置项（{{ configProps.length }}）</div>
      <table class="prop-table">
        <colgroup>
          <col style="width: 150px" />
          <col style="width: 90px" />
          <col style="width: 220px" />
          <col style="width: 90px" />
          <col />
        </colgroup>
        <thead>
          <tr>
            <th>属性</th>
            <th>数据类型</th>
            <th>UI 渲染</th>
            <th>默认值</th>
            <th>说明</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(cp, i) in configProps" :key="i">
            <td>
              <code class="prop-key">{{ cp.key }}</code>
              <span v-if="cp.required" class="req-mark">*</span>
            </td>
            <td><span class="type-text">{{ cp.type }}</span></td>
            <td><code class="editor-code">{{ cp.ui_editor }}</code></td>
            <td><code class="default-code">{{ fmtDefault(cp.default) }}</code></td>
            <td class="desc-cell">{{ cp.label }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- ── 渲染场景 ── -->
    <div v-if="scenesRequired.length || scenesOptional.length" class="doc-section">
      <div class="sec-title">渲染场景</div>
      <div class="scenes-wrap">
        <template v-if="scenesRequired.length">
          <span class="scenes-label">必需</span>
          <span v-for="s in scenesRequired" :key="s" class="scene-chip required">{{ s }}</span>
        </template>
        <template v-if="scenesOptional.length">
          <span class="scenes-label" :style="scenesRequired.length ? 'margin-left:12px' : ''">可选</span>
          <span v-for="s in scenesOptional" :key="s" class="scene-chip">{{ s }}</span>
        </template>
      </div>
    </div>

    <!-- ── 平台钩子 ── -->
    <div v-if="hooks" class="doc-section">
      <div class="sec-title">平台钩子</div>
      <table class="data-table">
        <thead>
          <tr><th>字段</th><th>值</th></tr>
        </thead>
        <tbody>
          <tr>
            <td class="field-name">表格内嵌</td>
            <td :class="hooks.in_table_supported ? 'val-yes' : 'val-no'">
              {{ hooks.in_table_supported ? '✓ 支持' : '— 不支持' }}
            </td>
          </tr>
          <tr>
            <td class="field-name">搜索</td>
            <td :class="hooks.search_enabled ? 'val-yes' : 'val-no'">
              {{ hooks.search_enabled ? '✓ 启用' : '— 关闭' }}
            </td>
          </tr>
          <tr>
            <td class="field-name">打印</td>
            <td :class="hooks.print_enabled ? 'val-yes' : 'val-no'">
              {{ hooks.print_enabled ? '✓ 启用' : '— 关闭' }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- ── 三方依赖 ── -->
    <div v-if="thirdPartyDeps.length" class="doc-section">
      <div class="sec-title">第三方依赖</div>
      <ul class="dep-list">
        <li v-for="d in thirdPartyDeps" :key="d">
          <code class="val-code">{{ d }}</code>
        </li>
      </ul>
    </div>

  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  spec: Record<string, any>
}>()

const data = computed(() => props.spec?.data)
const configProps = computed<any[]>(() => props.spec?.config_properties || [])
const scenesRequired = computed<string[]>(() => props.spec?.scenes_required || [])
const scenesOptional = computed<string[]>(() => props.spec?.scenes_optional || [])
const hooks = computed(() => props.spec?.platform_hooks)
const thirdPartyDeps = computed<string[]>(() => props.spec?.third_party_deps || [])

function fmtDefault(v: unknown): string {
  if (v == null) return '—'
  if (typeof v === 'string') return v || '""'
  return String(v)
}
</script>

<style scoped>
.comp-spec { display: flex; flex-direction: column; }

/* ── Section ── */
.doc-section {
  padding: 20px 24px;
  border-bottom: 1px solid #f0f0f0;
}
.doc-section:last-child { border-bottom: none; }

.sec-title {
  font-size: 14px;
  font-weight: 700;
  color: #111827;
  margin-bottom: 14px;
}

/* ── 数据存储表 ── */
.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  overflow: hidden;
}
.data-table thead tr {
  background: #f9fafb;
}
.data-table th {
  padding: 10px 14px;
  text-align: left;
  font-size: 12px;
  font-weight: 600;
  color: #6b7280;
  border-bottom: 1px solid #e5e7eb;
}
.data-table td {
  padding: 11px 14px;
  border-bottom: 1px solid #f3f4f6;
  vertical-align: middle;
}
.data-table tbody tr:last-child td { border-bottom: none; }
.data-table tbody tr:hover { background: #fafafa; }

.field-name {
  color: #374151;
  font-size: 13px;
  width: 140px;
  white-space: nowrap;
}
.field-note { color: #9ca3af; font-size: 12px; }

/* ── 配置项表 ── */
.prop-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  overflow: hidden;
}
.prop-table thead tr { background: #f9fafb; }
.prop-table th {
  padding: 10px 14px;
  text-align: left;
  font-size: 12px;
  font-weight: 600;
  color: #6b7280;
  border-bottom: 1px solid #e5e7eb;
}
.prop-table td {
  padding: 11px 14px;
  border-bottom: 1px solid #f3f4f6;
  vertical-align: middle;
}
.prop-table tbody tr:last-child td { border-bottom: none; }
.prop-table tbody tr:hover { background: #fafafa; }

.prop-key {
  font-family: 'Menlo', 'Monaco', monospace;
  font-size: 12px;
  color: #5b21b6;
  background: #f3f0ff;
  padding: 2px 6px;
  border-radius: 3px;
}
.req-mark { color: #ef4444; font-weight: 700; margin-left: 2px; }
.type-text { color: #374151; font-size: 13px; }
.editor-code {
  font-family: 'Menlo', 'Monaco', monospace;
  font-size: 11px;
  color: #1d4ed8;
  background: #eff6ff;
  padding: 2px 6px;
  border-radius: 3px;
}
.default-code {
  font-family: 'Menlo', 'Monaco', monospace;
  font-size: 12px;
  color: #6b7280;
  background: #f9fafb;
  padding: 2px 5px;
  border-radius: 3px;
}
.desc-cell { color: #374151; font-size: 13px; }

/* ── 通用 code 值 ── */
.val-code {
  font-family: 'Menlo', 'Monaco', monospace;
  font-size: 12px;
  color: #2563eb;
  background: transparent;
  padding: 0;
}
.field-chip { margin-right: 8px; }
.val-yes { color: #059669; font-size: 13px; }
.val-no  { color: #9ca3af; font-size: 13px; }

/* ── 场景 ── */
.scenes-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.scenes-label { font-size: 13px; color: #9ca3af; }
.scene-chip {
  padding: 3px 10px;
  border-radius: 999px;
  background: #f3f4f6;
  color: #374151;
  font-size: 12px;
  border: 1px solid #e5e7eb;
}
.scene-chip.required {
  background: #ede9fe;
  color: #5b21b6;
  border-color: #ddd6fe;
}

/* ── 依赖 ── */
.dep-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.dep-list li { display: flex; align-items: center; }
</style>
