<template>
  <div class="comp-spec">

    <!-- ── 数据 ── -->
    <section v-if="data" class="doc-section">
      <h4 class="sec-heading">数据</h4>
      <table class="kv-table">
        <tbody>
          <tr>
            <td class="kv-key">BOF 类型</td>
            <td><code>{{ data.bof_type }}</code></td>
          </tr>
          <tr v-if="data.component_model_field?.length">
            <td class="kv-key">存储字段</td>
            <td>
              <code v-for="f in data.component_model_field" :key="f" class="field-chip">{{ f }}</code>
            </td>
          </tr>
          <tr>
            <td class="kv-key">值形态</td>
            <td><code>{{ data.form_value_shape }}</code></td>
          </tr>
          <tr v-if="data.default_value !== undefined">
            <td class="kv-key">默认值</td>
            <td><code>{{ data.default_value }}</code></td>
          </tr>
          <tr v-if="data.storage_note">
            <td class="kv-key">备注</td>
            <td class="note-cell">{{ data.storage_note }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- ── 配置项 ── -->
    <section v-if="configProps.length" class="doc-section">
      <h4 class="sec-heading">配置项（{{ configProps.length }}）</h4>
      <table class="prop-table">
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
              <span v-if="cp.required" class="req-mark" title="必填">*</span>
            </td>
            <td><code class="type-code">{{ cp.type }}</code></td>
            <td>
              <code>{{ cp.ui_editor }}</code>
              <span v-if="cp.is_custom_editor" class="custom-tag">自定义</span>
            </td>
            <td><code class="default-code">{{ fmtDefault(cp.default) }}</code></td>
            <td class="label-cell">{{ cp.label }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- ── 渲染场景 ── -->
    <section v-if="scenesRequired.length || scenesOptional.length" class="doc-section">
      <h4 class="sec-heading">渲染场景</h4>
      <div class="scenes-row">
        <template v-if="scenesRequired.length">
          <span class="scenes-label">必需</span>
          <span v-for="s in scenesRequired" :key="s" class="scene-chip required">{{ s }}</span>
        </template>
        <template v-if="scenesOptional.length">
          <span class="scenes-label optional-sep">可选</span>
          <span v-for="s in scenesOptional" :key="s" class="scene-chip">{{ s }}</span>
        </template>
      </div>
    </section>

    <!-- ── 平台钩子 ── -->
    <section v-if="hooks" class="doc-section">
      <h4 class="sec-heading">平台钩子</h4>
      <table class="kv-table">
        <tbody>
          <tr>
            <td class="kv-key">表格内嵌</td>
            <td :class="hooks.in_table_supported ? 'val-yes' : 'val-no'">
              {{ hooks.in_table_supported ? '✓ 支持' : '— 不支持' }}
            </td>
          </tr>
          <tr>
            <td class="kv-key">搜索</td>
            <td :class="hooks.search_enabled ? 'val-yes' : 'val-no'">
              {{ hooks.search_enabled ? '✓ 启用' : '— 关闭' }}
            </td>
          </tr>
          <tr>
            <td class="kv-key">打印</td>
            <td :class="hooks.print_enabled ? 'val-yes' : 'val-no'">
              {{ hooks.print_enabled ? '✓ 启用' : '— 关闭' }}
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- ── 三方依赖 ── -->
    <section v-if="thirdPartyDeps.length" class="doc-section">
      <h4 class="sec-heading">三方依赖</h4>
      <div class="dep-row">
        <code v-for="d in thirdPartyDeps" :key="d" class="dep-chip">{{ d }}</code>
      </div>
    </section>

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
.comp-spec {
  display: flex;
  flex-direction: column;
}

/* ── Section ── */
.doc-section {
  padding: 10px 18px 12px;
  border-bottom: 1px solid #f3f4f6;
}
.doc-section:last-child {
  border-bottom: none;
}
.sec-heading {
  font-size: 11px;
  font-weight: 600;
  color: #9ca3af;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin: 0 0 8px;
}

/* ── 键值表 ── */
.kv-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.kv-table tr:last-child td { border-bottom: none; }
.kv-table td {
  padding: 5px 10px 5px 0;
  border-bottom: 1px solid #f9fafb;
  vertical-align: top;
  color: #1f2937;
}
.kv-key {
  color: #6b7280;
  font-size: 12px;
  width: 80px;
  white-space: nowrap;
  flex-shrink: 0;
}
.note-cell { color: #6b7280; font-size: 12px; }
.field-chip {
  margin-right: 4px;
}

/* ── 属性表 ── */
.prop-table {
  width: 100%;
  font-size: 12px;
  border-collapse: collapse;
}
.prop-table th {
  text-align: left;
  padding: 5px 10px 5px 0;
  border-bottom: 1px solid #e5e7eb;
  color: #9ca3af;
  font-weight: 500;
  font-size: 11px;
  white-space: nowrap;
}
.prop-table td {
  padding: 6px 10px 6px 0;
  border-bottom: 1px solid #f3f4f6;
  vertical-align: top;
  color: #374151;
}
.prop-table tr:last-child td { border-bottom: none; }
.prop-key {
  color: #374151;
  font-weight: 500;
}
.req-mark {
  color: #ef4444;
  font-size: 12px;
  margin-left: 2px;
  font-weight: 700;
}
.type-code { color: #6d28d9; }
.default-code { color: #6b7280; }
.label-cell { color: #6b7280; }

/* ── code 通用 ── */
code {
  background: #f3f4f6;
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 11px;
  font-family: 'Menlo', 'Monaco', monospace;
  color: #374151;
}

.custom-tag {
  margin-left: 5px;
  padding: 1px 5px;
  border-radius: 3px;
  background: #fef3c7;
  color: #92400e;
  font-size: 10px;
}

/* ── 场景 ── */
.scenes-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.scenes-label {
  font-size: 12px;
  color: #9ca3af;
}
.optional-sep { margin-left: 4px; }
.scene-chip {
  padding: 2px 8px;
  border-radius: 999px;
  background: #f3f4f6;
  color: #374151;
  font-size: 12px;
}
.scene-chip.required { background: #dbeafe; color: #1d4ed8; }

/* ── 钩子 ── */
.val-yes { color: #059669; }
.val-no  { color: #9ca3af; }

/* ── 依赖 ── */
.dep-row { display: flex; gap: 8px; flex-wrap: wrap; }
.dep-chip {
  font-size: 12px;
  background: #f3f4f6;
  color: #374151;
}
</style>
