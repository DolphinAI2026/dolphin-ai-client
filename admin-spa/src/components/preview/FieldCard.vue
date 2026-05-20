<template>
  <div class="field-card" :class="{ full: isFullWidth }">
    <div class="label">
      {{ name }}<span v-if="isTrue(field.required)" class="req"> *</span>
      <div class="flags">
        <span v-if="isTrue(field.readonly)" class="flag flag-grey">只读</span>
        <span v-if="isTrue(field.hidden)" class="flag flag-grey">隐藏</span>
        <span v-if="isTrue(field.listShow)" class="flag flag-blue">列表</span>
        <span v-if="isTrue(field.searchable) || isTrue(field.queryable)" class="flag flag-orange">查询</span>
      </div>
    </div>
    <div class="comp" :class="compClass">
      <span class="comp-text">{{ compPlaceholder }}</span>
      <span v-if="compIcon" class="comp-icon">{{ compIcon }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ field: any }>()

const name = computed(() => props.field.name || props.field.fieldName || props.field.label || '—')
const type = computed(() => String(props.field.type || props.field.componentType || '').trim())

const isFullWidth = computed(() =>
  ['关联表单', '附件上传', '富文本', '多行输入', '签名', '地理位置', '子表'].some(k => type.value.includes(k)),
)

const compClass = computed(() => {
  const t = type.value
  if (t.includes('下拉') || t.includes('单选') || t.includes('选择') || t.includes('部门') || t.includes('人员')) return 'select'
  if (t.includes('日期') || t.includes('时间')) return 'date'
  if (t.includes('附件') || t.includes('上传')) return 'upload'
  if (t.includes('关联表单')) return 'reflink'
  if (t.includes('多行') || t.includes('富文本')) return 'textarea'
  if (t.includes('开关') || t.includes('布尔')) return 'switch'
  if (t.includes('金额') || t.includes('数字') || t.includes('数值')) return 'number'
  return ''
})

const compIcon = computed(() => {
  const t = type.value
  if (t.includes('下拉') || t.includes('单选')) return '▾'
  if (t.includes('日期') || t.includes('时间')) return '📅'
  if (t.includes('附件')) return '📎'
  return ''
})

const compPlaceholder = computed(() => {
  const t = type.value
  if (props.field.dictCode) return `${props.field.dictCode} 字典`
  if (props.field.refModel || props.field.targetModel) {
    const ref = props.field.refModel || props.field.targetModel
    const refField = props.field.refField || props.field.targetField
    return `${t} → ${ref}${refField ? '.' + refField : ''}`
  }
  if (t.includes('关联表单')) return '展示关联数据'
  if (t.includes('附件')) return '📎 点击上传 / 拖拽文件'
  if (t.includes('日期')) return '请选择日期时间'
  if (t.includes('金额')) return '¥ 0.00'
  if (t.includes('单据号')) return '自动生成'
  if (t.includes('多行') || t.includes('富文本')) return ''
  return t || '请输入'
})

function isTrue(v: any): boolean {
  if (typeof v === 'boolean') return v
  if (typeof v === 'string') return ['是', 'true', '1', 'yes'].includes(v.trim().toLowerCase())
  return false
}
</script>

<style scoped>
.field-card {
  background: #fafafa;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 10px 14px;
}
.field-card.full { grid-column: 1 / -1; }
.label {
  font-size: 12px;
  color: #606266;
  margin-bottom: 6px;
  display: flex;
  align-items: center;
}
.label .req { color: #f56c6c; margin-right: auto; }
.flags { margin-left: auto; display: flex; gap: 4px; }
.flag {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 8px;
  font-size: 10px;
}
.flag-grey { background: #e9e9eb; color: #909399; }
.flag-blue { background: #d9ecff; color: #409eff; }
.flag-orange { background: #faecd8; color: #e6a23c; }
.comp {
  background: #fff;
  border: 1px solid #dcdfe6;
  border-radius: 3px;
  padding: 8px 12px;
  min-height: 32px;
  color: #c0c4cc;
  font-size: 13px;
  display: flex;
  align-items: center;
}
.comp .comp-text { flex: 1; }
.comp.upload {
  border-style: dashed;
  justify-content: center;
  color: #909399;
  padding: 16px;
  min-height: 60px;
}
.comp.textarea { min-height: 60px; align-items: flex-start; }
.comp.reflink {
  border-style: dashed;
  color: #409eff;
  background: #fafcff;
}
.comp.switch::after {
  content: '○';
  margin-left: auto;
  color: #909399;
}
</style>
