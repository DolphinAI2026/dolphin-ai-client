<template>
  <div class="side-by-side-diff">
    <!-- 并排对比区域 -->
    <div class="diff-panels">
      <!-- 左侧：旧版本 -->
      <div class="panel old-panel">
        <div class="panel-title">旧版本</div>
        <div class="panel-content" v-if="oldValue && Object.keys(oldValue).length > 0">
          <div
            v-for="key in displayFields"
            :key="key"
            class="field-row"
            :class="{ changed: isFieldChanged(key), deleted: isFieldDeleted(key) }"
          >
            <span class="field-key">{{ fieldLabel(key) }}</span>
            <span class="field-value">{{ formatValue(oldValue[key]) }}</span>
          </div>
        </div>
        <div class="panel-empty" v-else>
          <span class="empty-text">（新增资源）</span>
        </div>
      </div>

      <!-- 右侧：新版本 -->
      <div class="panel new-panel">
        <div class="panel-title">新版本</div>
        <div class="panel-content" v-if="newValue && Object.keys(newValue).length > 0">
          <div
            v-for="key in displayFields"
            :key="key"
            class="field-row"
            :class="{ changed: isFieldChanged(key), added: isFieldAdded(key) }"
          >
            <span class="field-key">{{ fieldLabel(key) }}</span>
            <span class="field-value">{{ formatValue(newValue[key]) }}</span>
          </div>
        </div>
        <div class="panel-empty" v-else>
          <span class="empty-text">（已删除）</span>
        </div>
      </div>
    </div>

    <!-- 嵌套变更（字典选项 / 模型字段） -->
    <div v-if="nestedChanges && nestedChanges.length > 0" class="nested-changes">
      <div class="nested-title">{{ nestedLabel }}</div>
      <div v-for="nested in nestedChanges" :key="nested.code" class="nested-item">
        <div class="nested-header">
          <span class="change-tag" :class="nested.change_type">
            {{ changeTypeLabel(nested.change_type) }}
          </span>
          <span class="nested-name">{{ nested.name }}</span>
          <span class="nested-code">({{ nested.code }})</span>
        </div>
        <SideBySideDiff
          :old-value="nested.old_value"
          :new-value="nested.new_value"
          :resource-type="nestedType"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  oldValue?: Record<string, any>
  newValue?: Record<string, any>
  resourceType?: 'role' | 'dict' | 'model' | 'form' | 'process' | 'option' | 'field'
  nestedChanges?: Array<{
    name: string
    code: string
    change_type: 'added' | 'modified' | 'deleted'
    old_value?: Record<string, any>
    new_value?: Record<string, any>
  }>
  nestedLabel?: string
  nestedType?: 'option' | 'field'
}

const props = withDefaults(defineProps<Props>(), {
  resourceType: 'dict',
  nestedLabel: '子项变更',
  nestedType: 'option'
})

// 字段标签映射
const fieldLabels: Record<string, string> = {
  // 角色字段
  roleName: '角色名称',
  roleCode: '角色编码',
  name: '名称',
  code: '编码',

  // 字典字段
  dictionaryName: '字典名称',
  dictionaryCode: '字典编码',

  // 字典选项字段
  valueName: '选项名称',
  valueCode: '选项编码',
  valueOrder: '排序',

  // 模型字段
  modelName: '模型名称',
  modelCode: '模型编码',
  modelType: '模型类型',

  // 模型字段属性
  fieldName: '字段名称',
  fieldCode: '字段编码',
  fieldType: '字段类型',
  required: '是否必填',
  fieldStatus: '字段状态',

  // 表单字段
  formName: '表单名称',
  formCode: '表单编码',

  // 流程字段
  processName: '流程名称',
  processCode: '流程编码',
}

// 需要隐藏的字段（内部字段或复杂对象）
const hiddenFields = new Set([
  'id', 'remote_id', 'menu_id', 'model_code', 'dict_code', 'form_code',
  'components', 'fields', 'values', 'options', 'dataModelFields',
  'createTime', 'updateTime', 'creator', 'updater', 'tenantId', 'appId'
])

// 计算要显示的字段列表
const displayFields = computed(() => {
  const oldKeys = props.oldValue ? Object.keys(props.oldValue) : []
  const newKeys = props.newValue ? Object.keys(props.newValue) : []
  const allKeys = [...new Set([...oldKeys, ...newKeys])]

  return allKeys.filter(key => {
    // 过滤隐藏字段
    if (hiddenFields.has(key)) return false
    // 过滤空值字段
    const oldVal = props.oldValue?.[key]
    const newVal = props.newValue?.[key]
    if (oldVal === undefined && newVal === undefined) return false
    if (oldVal === null && newVal === null) return false
    // 过滤复杂对象
    if (typeof oldVal === 'object' && oldVal !== null && !Array.isArray(oldVal)) return false
    if (typeof newVal === 'object' && newVal !== null && !Array.isArray(newVal)) return false
    return true
  })
})

// 获取字段标签
const fieldLabel = (key: string): string => {
  return fieldLabels[key] || key
}

// 格式化值
const formatValue = (value: any): string => {
  if (value === undefined || value === null) return '—'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (Array.isArray(value)) return `[${value.length} 项]`
  return String(value)
}

// 判断字段是否有变更
const isFieldChanged = (key: string): boolean => {
  const oldVal = props.oldValue?.[key]
  const newVal = props.newValue?.[key]
  return oldVal !== newVal
}

// 判断字段是否为新增（旧版本没有，新版本有）
const isFieldAdded = (key: string): boolean => {
  const oldVal = props.oldValue?.[key]
  const newVal = props.newValue?.[key]
  return (oldVal === undefined || oldVal === null) && newVal !== undefined && newVal !== null
}

// 判断字段是否为删除（旧版本有，新版本没有）
const isFieldDeleted = (key: string): boolean => {
  const oldVal = props.oldValue?.[key]
  const newVal = props.newValue?.[key]
  return oldVal !== undefined && oldVal !== null && (newVal === undefined || newVal === null)
}

// 变更类型标签
const changeTypeLabel = (type: string): string => {
  switch (type) {
    case 'added': return '新增'
    case 'modified': return '修改'
    case 'deleted': return '删除'
    default: return type
  }
}
</script>

<style scoped lang="less">
.side-by-side-diff {
  margin-top: 8px;
}

.diff-panels {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.panel {
  background: rgba(0, 0, 0, 0.2);
  border-radius: 8px;
  overflow: hidden;
}

.panel-title {
  padding: 8px 12px;
  font-size: 12px;
  font-weight: 500;
  color: #888;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.old-panel .panel-title {
  background: rgba(248, 113, 113, 0.1);
  color: #f87171;
}

.new-panel .panel-title {
  background: rgba(74, 222, 128, 0.1);
  color: #4ade80;
}

.panel-content {
  padding: 8px 12px;
}

.panel-empty {
  padding: 24px 12px;
  text-align: center;
}

.empty-text {
  color: #666;
  font-size: 13px;
}

.field-row {
  display: flex;
  justify-content: space-between;
  padding: 4px 0;
  font-size: 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.03);
}

.field-row:last-child {
  border-bottom: none;
}

.field-row.changed {
  background: rgba(251, 191, 36, 0.1);
  margin: 0 -12px;
  padding: 4px 12px;
}

.field-row.added {
  background: rgba(74, 222, 128, 0.1);
  margin: 0 -12px;
  padding: 4px 12px;
}

.field-row.deleted {
  background: rgba(248, 113, 113, 0.1);
  margin: 0 -12px;
  padding: 4px 12px;
}

.field-key {
  color: #888;
  flex-shrink: 0;
}

.field-value {
  color: #e0e0e0;
  text-align: right;
  word-break: break-all;
}

.field-row.deleted .field-value {
  text-decoration: line-through;
  color: #f87171;
}

.field-row.added .field-value {
  color: #4ade80;
}

/* 嵌套变更 */
.nested-changes {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}

.nested-title {
  font-size: 12px;
  color: #888;
  margin-bottom: 8px;
}

.nested-item {
  background: rgba(255, 255, 255, 0.03);
  border-radius: 6px;
  padding: 8px;
  margin-bottom: 8px;
}

.nested-item:last-child {
  margin-bottom: 0;
}

.nested-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.change-tag {
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: 500;
}

.change-tag.added {
  background: rgba(74, 222, 128, 0.2);
  color: #4ade80;
}

.change-tag.modified {
  background: rgba(251, 191, 36, 0.2);
  color: #fbbf24;
}

.change-tag.deleted {
  background: rgba(248, 113, 113, 0.2);
  color: #f87171;
}

.nested-name {
  font-size: 12px;
  font-weight: 500;
  color: #e0e0e0;
}

.nested-code {
  font-size: 11px;
  color: #666;
}
</style>
