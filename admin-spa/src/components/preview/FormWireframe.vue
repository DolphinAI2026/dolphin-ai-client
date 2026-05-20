<template>
  <div class="form-wireframe">
    <div class="wf-title">{{ form.name || form.formName }}</div>
    <div class="wf-desc">
      <span v-if="form.description || form.formDesc">{{ form.description || form.formDesc }} · </span>
      绑定主表 <code>{{ mainModel }}</code>
    </div>

    <div class="wf-meta">
      <span>主表字段 <b>{{ mainFields.length }}</b></span>
      <span>子表 <b>{{ (form.subForms || []).length }}</b></span>
      <span>必填字段 <b>{{ mainFields.filter(f => isTrue(f.required)).length }}</b></span>
    </div>

    <div class="wf-section-title">主表字段</div>
    <div class="wf-grid">
      <FieldCard v-for="(f, i) in mainFields" :key="i" :field="f" />
    </div>

    <template v-if="form.subForms && form.subForms.length">
      <template v-for="(sub, sIdx) in form.subForms" :key="sIdx">
        <div class="wf-section-title">子表区域：{{ sub.name || sub.subFormName }}</div>
        <div class="subtable">
          <table>
            <thead>
              <tr>
                <th v-for="(f, i) in (sub.fields || sub.components || [])" :key="i">
                  {{ f.name || f.fieldName || f.label }}<span v-if="isTrue(f.required)" class="req"> *</span>
                  <span v-if="isTrue(f.readonly)" class="flag-mini">只读</span>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr><td v-for="i in (sub.fields || sub.components || []).length" :key="i">—</td></tr>
              <tr><td v-for="i in (sub.fields || sub.components || []).length" :key="i">—</td></tr>
            </tbody>
          </table>
        </div>
      </template>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import FieldCard from './FieldCard.vue'

const props = defineProps<{ form: any; spec: any }>()

const mainModel = computed(() =>
  props.form?.mainModel || props.form?.modelCode || props.form?.bindModel || '—',
)

const mainFields = computed<any[]>(() => props.form?.fields || props.form?.components || [])

function isTrue(v: any): boolean {
  if (typeof v === 'boolean') return v
  if (typeof v === 'string') return ['是', 'true', '1', 'yes'].includes(v.trim().toLowerCase())
  return false
}
</script>

<style scoped>
.form-wireframe {}
.wf-title { font-size: 18px; font-weight: 600; margin: 0 0 6px; }
.wf-desc { color: #909399; font-size: 13px; margin-bottom: 16px; }
.wf-desc code {
  background: #f4f4f5;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 12px;
  color: #5e6d82;
}
.wf-meta {
  display: flex;
  gap: 18px;
  padding: 12px 16px;
  background: #f0f9eb;
  border-left: 3px solid #67c23a;
  border-radius: 3px;
  margin-bottom: 16px;
  font-size: 12px;
  color: #606266;
}
.wf-meta b { color: #303133; }
.wf-section-title {
  font-size: 13px;
  color: #909399;
  padding: 12px 0 8px;
  border-bottom: 1px dashed #dcdfe6;
  margin-bottom: 14px;
  letter-spacing: 1px;
}
.wf-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px 20px;
  margin-bottom: 20px;
}
.subtable {
  background: #fafafa;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 12px;
  margin-bottom: 16px;
}
.subtable table { width: 100%; border-collapse: collapse; }
.subtable th {
  background: #f0f2f5;
  padding: 8px 10px;
  font-size: 12px;
  text-align: left;
  border: 1px solid #dcdfe6;
}
.subtable td {
  padding: 8px 10px;
  border: 1px solid #ebeef5;
  background: #fff;
  color: #c0c4cc;
  font-size: 12px;
}
.req { color: #f56c6c; }
.flag-mini {
  display: inline-block;
  background: #e9e9eb;
  color: #909399;
  font-size: 10px;
  padding: 0 4px;
  border-radius: 2px;
  margin-left: 4px;
}
</style>
