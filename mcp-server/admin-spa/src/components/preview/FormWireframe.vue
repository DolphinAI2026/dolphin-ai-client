<template>
  <div class="form-wireframe">
    <div class="wf-title">{{ form.name || form.formName }}</div>
    <div class="wf-desc">
      <span v-if="form.description || form.formDesc">{{ form.description || form.formDesc }} · </span>
      绑定主表 <code>{{ mainModel }}</code>
    </div>

    <div class="wf-meta">
      <span>主表字段 <b>{{ mainFields.length }}</b></span>
      <span>子表 <b>{{ subForms.length }}</b></span>
      <span>必填字段 <b>{{ mainFields.filter(f => isTrue(f.required)).length }}</b></span>
    </div>

    <div class="cap-row">
      <el-tag
        v-for="cap in capabilities"
        :key="cap.key"
        size="small"
        :type="cap.key === 'import' && cap.on ? 'warning' : cap.on ? 'success' : 'info'"
        effect="plain"
      >
        {{ cap.label }}
      </el-tag>
    </div>

    <div class="wf-section-title">主表字段</div>
    <div class="wf-grid">
      <FieldCard v-for="(f, i) in mainFields" :key="i" :field="f" />
    </div>

    <template v-if="subForms.length">
      <template v-for="(sub, sIdx) in subForms" :key="sIdx">
        <div class="wf-section-title">
          子表区域：{{ sub.label }}
          <span v-if="sub.model" class="sub-meta">· 绑定 <code>{{ sub.model }}</code> · {{ sub.fields.length }} 字段</span>
        </div>
        <div class="subtable">
          <table>
            <thead>
              <tr>
                <th v-for="(f, i) in sub.fields" :key="i">
                  {{ f.name || f.fieldName || f.label }}<span v-if="isTrue(f.required)" class="req"> *</span>
                  <span v-if="isTrue(f.readonly)" class="flag-mini">只读</span>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr><td v-for="i in sub.fields.length" :key="i">—</td></tr>
              <tr><td v-for="i in sub.fields.length" :key="i">—</td></tr>
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

const mainFields = computed<any[]>(() =>
  (props.form?.fields || props.form?.components || []).filter((field: any) => (field.sectionType || 'main') !== 'sub'),
)

const subForms = computed(() => {
  const groups: Record<string, any[]> = {}
  for (const field of (props.form?.fields || props.form?.components || [])) {
    if (field.sectionType === 'sub') {
      const label = field.subTableLabel || field.subFormName || '子表'
      if (!groups[label]) groups[label] = []
      groups[label].push(field)
    }
  }
  const grouped = Object.entries(groups).map(([label, fields]) => ({
    label,
    model: fields[0]?.modelCode || fields[0]?.tableModelCode || '',
    fields,
  }))
  const legacy = (props.form?.subForms || []).map((sub: any) => ({
    label: sub.name || sub.subFormName || '子表',
    model: sub.modelCode || sub.bindModel || '',
    fields: sub.fields || sub.components || [],
  }))
  return [...grouped, ...legacy]
})

const capabilities = computed(() => {
  const rules = rulesForForm()
  return [
    { key: 'view', label: '查看', on: hasOp(rules, ['view']) || rules.some(r => r.canView) },
    { key: 'add', label: '新增', on: hasOp(rules, ['add', 'create']) || rules.some(r => r.canAdd || r.canCreate) },
    { key: 'edit', label: '编辑', on: hasOp(rules, ['edit']) || rules.some(r => r.canEdit) },
    { key: 'delete', label: '删除', on: hasOp(rules, ['delete']) || rules.some(r => r.canDelete) },
    { key: 'import', label: '可导入', on: rules.some(r => r.canImport) },
    { key: 'export', label: '可导出', on: hasOp(rules, ['export']) || rules.some(r => r.canExport) },
  ]
})

function rulesForForm(): any[] {
  const code = props.form?.code || props.form?.formCode
  const name = props.form?.name || props.form?.formName
  const permissions = props.spec?.permissions || []
  const rules: any[] = []
  for (const item of permissions) {
    const key = item.formCode || item.form_code || item.form
    if (key === code || key === name) rules.push(...(item.rules || item.permissionRules || []))
  }
  return rules
}

function hasOp(rules: any[], ops: string[]): boolean {
  return rules.some(rule => {
    if (rule.op === 'all') return true
    const arr = Array.isArray(rule.op) ? rule.op : String(rule.op || '').split(/[,+]/).map(x => x.trim())
    return ops.some(op => arr.includes(op))
  })
}

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
.cap-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 10px 0 14px;
}
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
.sub-meta {
  color: #909399;
  font-weight: normal;
  letter-spacing: 0;
}
.sub-meta code {
  background: #f4f4f5;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 12px;
  color: #5e6d82;
}
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
