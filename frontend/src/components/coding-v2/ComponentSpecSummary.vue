<template>
  <div class="comp-spec">

    <!-- ── 数据 ── -->
    <div v-if="data" class="doc-section">
      <div class="sec-label">数据</div>
      <table class="kv-table">
        <colgroup>
          <col style="width: 90px" />
          <col />
        </colgroup>
        <tbody>
          <tr>
            <td class="kv-key">BOF 类型</td>
            <td><code class="code-tag">{{ data.bof_type }}</code></td>
          </tr>
          <tr v-if="data.component_model_field?.length">
            <td class="kv-key">存储字段</td>
            <td>
              <code
                v-for="f in data.component_model_field"
                :key="f"
                class="code-tag field-chip"
              >{{ f }}</code>
            </td>
          </tr>
          <tr>
            <td class="kv-key">值形态</td>
            <td><code class="code-tag">{{ data.form_value_shape }}</code></td>
          </tr>
          <tr v-if="data.default_value !== undefined">
            <td class="kv-key">默认值</td>
            <td><code class="code-tag">{{ data.default_value }}</code></td>
          </tr>
          <tr v-if="data.storage_note">
            <td class="kv-key">备注</td>
            <td class="kv-note">{{ data.storage_note }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- ── 配置项 ── -->
    <div v-if="configProps.length" class="doc-section">
      <div class="sec-label">配置项（{{ configProps.length }}）</div>
      <table class="prop-table">
        <colgroup>
          <col style="width: 130px" />
          <col style="width: 80px" />
          <col style="width: 200px" />
          <col style="width: 80px" />
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
              <span v-if="cp.required" class="req-dot" title="必填">*</span>
            </td>
            <td><code class="type-code">{{ cp.type }}</code></td>
            <td>
              <code class="editor-code">{{ cp.ui_editor }}</code>
              <span v-if="cp.is_custom_editor" class="custom-tag">自定义</span>
            </td>
            <td><code class="default-code">{{ fmtDefault(cp.default) }}</code></td>
            <td class="desc-cell">{{ cp.label }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- ── 渲染场景 ── -->
    <div v-if="scenesRequired.length || scenesOptional.length" class="doc-section">
      <div class="sec-label">渲染场景</div>
      <div class="scenes-wrap">
        <template v-if="scenesRequired.length">
          <span class="scenes-group-label">必需</span>
          <span v-for="s in scenesRequired" :key="s" class="scene-chip required">{{ s }}</span>
        </template>
        <template v-if="scenesOptional.length">
          <span class="scenes-group-label" :style="scenesRequired.length ? 'margin-left:12px' : ''">可选</span>
          <span v-for="s in scenesOptional" :key="s" class="scene-chip">{{ s }}</span>
        </template>
      </div>
    </div>

    <!-- ── 平台钩子 ── -->
    <div v-if="hooks" class="doc-section">
      <div class="sec-label">平台钩子</div>
      <table class="kv-table">
        <colgroup>
          <col style="width: 90px" />
          <col />
        </colgroup>
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
    </div>

    <!-- ── 三方依赖 ── -->
    <div v-if="thirdPartyDeps.length" class="doc-section">
      <div class="sec-label">三方依赖</div>
      <div class="dep-wrap">
        <code v-for="d in thirdPartyDeps" :key="d" class="dep-chip">{{ d }}</code>
      </div>
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
  padding: 14px 20px;
  border-bottom: 1px solid #f3f4f6;
}
.doc-section:last-child { border-bottom: none; }

.sec-label {
  font-size: 12px;
  font-weight: 600;
  color: #6b7280;
  margin-bottom: 10px;
  padding-left: 8px;
  border-left: 3px solid #8b5cf6;
  line-height: 1;
}

/* ── 键值表 ── */
.kv-table {
  width: 100%;
  border-collapse: collapse;
}
.kv-table td {
  padding: 6px 8px 6px 0;
  border-bottom: 1px solid #f9fafb;
  vertical-align: middle;
  font-size: 13px;
  color: #1f2937;
}
.kv-table tr:last-child td { border-bottom: none; }
.kv-key {
  color: #9ca3af;
  font-size: 12px;
  padding-right: 12px;
  white-space: nowrap;
}
.kv-note { color: #9ca3af; font-size: 12px; }

/* ── 配置项表 ── */
.prop-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.prop-table thead tr {
  background: #f5f3ff;
}
.prop-table th {
  padding: 7px 10px 7px 0;
  text-align: left;
  font-size: 11px;
  font-weight: 600;
  color: #7c3aed;
  border-bottom: 2px solid #ede9fe;
  white-space: nowrap;
}
.prop-table th:first-child { padding-left: 0; }
.prop-table td {
  padding: 7px 10px 7px 0;
  border-bottom: 1px solid #f3f4f6;
  vertical-align: middle;
  color: #374151;
}
.prop-table tr:last-child td { border-bottom: none; }
.prop-table tbody tr:hover { background: #fafafa; }

.prop-key {
  font-weight: 500;
  color: #111827;
}
.req-dot {
  color: #ef4444;
  font-weight: 700;
  margin-left: 2px;
}
.type-code { color: #7c3aed; }
.editor-code { color: #374151; }
.default-code { color: #6b7280; }
.desc-cell { color: #4b5563; font-size: 12px; }

.custom-tag {
  margin-left: 5px;
  padding: 1px 5px;
  border-radius: 3px;
  background: #fef3c7;
  color: #92400e;
  font-size: 10px;
}

/* ── 通用 code ── */
.code-tag {
  background: #f3f4f6;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 12px;
  font-family: 'Menlo', 'Monaco', monospace;
  color: #374151;
}
.field-chip { margin-right: 5px; }
code {
  background: #f3f4f6;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 12px;
  font-family: 'Menlo', 'Monaco', monospace;
  color: #374151;
}

/* ── 场景 ── */
.scenes-wrap {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.scenes-group-label { font-size: 12px; color: #9ca3af; }
.scene-chip {
  padding: 2px 9px;
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

/* ── 钩子 ── */
.val-yes { color: #059669; font-size: 13px; }
.val-no  { color: #9ca3af; font-size: 13px; }

/* ── 依赖 ── */
.dep-wrap { display: flex; gap: 8px; flex-wrap: wrap; }
.dep-chip {
  background: #f3f4f6;
  color: #374151;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-family: 'Menlo', 'Monaco', monospace;
  border: 1px solid #e5e7eb;
}
</style>
