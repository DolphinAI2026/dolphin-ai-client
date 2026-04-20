<template>
  <div class="comp-spec">
    <section v-if="data" class="block">
      <h3>数据</h3>
      <div class="kv">
        <div><span class="k">BOF 类型</span><code>{{ data.bof_type }}</code></div>
        <div><span class="k">存储字段</span><code>{{ (data.component_model_field || []).join(', ') }}</code></div>
        <div><span class="k">值形态</span><code>{{ data.form_value_shape }}</code></div>
        <div v-if="data.default_value !== undefined">
          <span class="k">默认值</span><code>{{ data.default_value }}</code>
        </div>
        <div v-if="data.storage_note" class="note">{{ data.storage_note }}</div>
      </div>
    </section>

    <section v-if="configProps.length" class="block">
      <h3>配置项（{{ configProps.length }}）</h3>
      <table class="config-table">
        <thead>
          <tr>
            <th>key</th>
            <th>type</th>
            <th>label</th>
            <th>默认</th>
            <th>必填</th>
            <th>UI editor</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(cp, i) in configProps" :key="i">
            <td><code>{{ cp.key }}</code></td>
            <td><code>{{ cp.type }}</code></td>
            <td>{{ cp.label }}</td>
            <td><code>{{ fmtDefault(cp.default) }}</code></td>
            <td>{{ cp.required ? '✓' : '' }}</td>
            <td>
              <code>{{ cp.ui_editor }}</code>
              <span v-if="cp.is_custom_editor" class="custom-tag">自定义</span>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <section v-if="scenesRequired.length || scenesOptional.length" class="block">
      <h3>渲染场景</h3>
      <div class="kv">
        <div v-if="scenesRequired.length">
          <span class="k">必需</span>
          <span v-for="s in scenesRequired" :key="s" class="scene-chip required">{{ s }}</span>
        </div>
        <div v-if="scenesOptional.length">
          <span class="k">可选</span>
          <span v-for="s in scenesOptional" :key="s" class="scene-chip">{{ s }}</span>
        </div>
      </div>
    </section>

    <section v-if="hooks" class="block">
      <h3>平台钩子</h3>
      <div class="kv">
        <div><span class="k">in_table</span>{{ hooks.in_table_supported ? '✓ 支持' : '✗' }}</div>
        <div><span class="k">search</span>{{ hooks.search_enabled ? '✓ 启用' : '✗ 关闭' }}</div>
        <div><span class="k">print</span>{{ hooks.print_enabled ? '✓ 启用' : '✗ 关闭' }}</div>
      </div>
    </section>

    <section v-if="thirdPartyDeps.length" class="block">
      <h3>三方依赖</h3>
      <ul class="dep-list">
        <li v-for="d in thirdPartyDeps" :key="d"><code>{{ d }}</code></li>
      </ul>
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
  if (v == null) return 'null'
  if (typeof v === 'string') return JSON.stringify(v)
  return String(v)
}
</script>

<style scoped>
.comp-spec { display: flex; flex-direction: column; gap: 16px; }
.block h3 {
  font-size: 14px;
  margin: 0 0 8px;
  color: #1f2937;
  font-weight: 600;
}
.kv { display: flex; flex-direction: column; gap: 6px; font-size: 13px; color: #374151; }
.kv > div { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.k { min-width: 80px; color: #6b7280; font-size: 12px; }
.note { color: #6b7280; font-size: 12px; margin-top: 4px; }
.config-table {
  width: 100%;
  font-size: 12px;
  border-collapse: collapse;
}
.config-table th {
  text-align: left;
  padding: 6px 8px;
  background: #f9fafb;
  border-bottom: 1px solid #e5e7eb;
  color: #6b7280;
  font-weight: 500;
}
.config-table td {
  padding: 6px 8px;
  border-bottom: 1px solid #f3f4f6;
}
code {
  background: #f3f4f6;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 12px;
  color: #0f172a;
}
.scene-chip {
  padding: 2px 8px;
  border-radius: 999px;
  background: #f3f4f6;
  color: #374151;
  font-size: 12px;
}
.scene-chip.required { background: #dbeafe; color: #1d4ed8; }
.custom-tag {
  margin-left: 6px;
  padding: 1px 6px;
  border-radius: 3px;
  background: #fef3c7;
  color: #92400e;
  font-size: 11px;
}
.dep-list { margin: 0; padding-left: 20px; color: #374151; font-size: 13px; }
</style>
