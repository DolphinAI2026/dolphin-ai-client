<template>
  <div class="config-diff">
    <div class="diff-header">
      <h3>配置变更</h3>
      <span class="diff-summary">{{ summary }}</span>
    </div>

    <div v-if="!hasChanges" class="no-changes">
      <span class="icon">✓</span>
      <span>配置无变更</span>
    </div>

    <div v-else class="diff-content">
      <!-- 角色变更 -->
      <div v-if="roleChanges.length > 0" class="diff-section">
        <div class="section-title">
          <span class="icon">👤</span>
          <span>角色变更 ({{ roleChanges.length }})</span>
        </div>
        <div class="change-list">
          <div v-for="change in roleChanges" :key="change.code" class="change-item-wrapper">
            <div
              class="change-item clickable"
              :class="change.change_type"
              @click="toggleExpand('role', change.code)"
            >
              <span class="change-tag" :class="change.change_type">
                {{ changeTypeLabel(change.change_type) }}
              </span>
              <span class="change-name">{{ change.name }}</span>
              <span class="change-code">({{ change.code }})</span>
              <span class="expand-icon">{{ isExpanded('role', change.code) ? '▼' : '▶' }}</span>
            </div>
            <div v-if="isExpanded('role', change.code)" class="change-detail">
              <SideBySideDiff
                :old-value="change.old_value"
                :new-value="change.new_value"
                resource-type="role"
              />
            </div>
          </div>
        </div>
      </div>

      <!-- 字典变更 -->
      <div v-if="dictChanges.length > 0" class="diff-section">
        <div class="section-title">
          <span class="icon">📖</span>
          <span>字典变更 ({{ dictChanges.length }})</span>
        </div>
        <div class="change-list">
          <div v-for="change in dictChanges" :key="change.code" class="change-item-wrapper">
            <div
              class="change-item clickable"
              :class="change.change_type"
              @click="toggleExpand('dict', change.code)"
            >
              <span class="change-tag" :class="change.change_type">
                {{ changeTypeLabel(change.change_type) }}
              </span>
              <span class="change-name">{{ change.name }}</span>
              <span v-if="change.option_changes && change.option_changes.length > 0" class="option-changes">
                ({{ change.option_changes.length }} 个选项变更)
              </span>
              <span class="expand-icon">{{ isExpanded('dict', change.code) ? '▼' : '▶' }}</span>
            </div>
            <div v-if="isExpanded('dict', change.code)" class="change-detail">
              <SideBySideDiff
                :old-value="change.old_value"
                :new-value="change.new_value"
                resource-type="dict"
                :nested-changes="change.option_changes"
                nested-label="字典选项变更"
                nested-type="option"
              />
            </div>
          </div>
        </div>
      </div>

      <!-- 模型变更 -->
      <div v-if="modelChanges.length > 0" class="diff-section">
        <div class="section-title">
          <span class="icon">📊</span>
          <span>模型变更 ({{ modelChanges.length }})</span>
        </div>
        <div class="change-list">
          <div v-for="change in modelChanges" :key="change.code" class="change-item-wrapper">
            <div
              class="change-item clickable"
              :class="change.change_type"
              @click="toggleExpand('model', change.code)"
            >
              <span class="change-tag" :class="change.change_type">
                {{ changeTypeLabel(change.change_type) }}
              </span>
              <span class="change-name">{{ change.name }}</span>
              <span v-if="change.field_changes && change.field_changes.length > 0" class="field-changes">
                ({{ change.field_changes.length }} 个字段变更)
              </span>
              <span class="expand-icon">{{ isExpanded('model', change.code) ? '▼' : '▶' }}</span>
            </div>
            <div v-if="isExpanded('model', change.code)" class="change-detail">
              <SideBySideDiff
                :old-value="change.old_value"
                :new-value="change.new_value"
                resource-type="model"
                :nested-changes="change.field_changes"
                nested-label="模型字段变更"
                nested-type="field"
              />
            </div>
          </div>
        </div>
      </div>

      <!-- 表单变更 -->
      <div v-if="formChanges.length > 0" class="diff-section">
        <div class="section-title">
          <span class="icon">📝</span>
          <span>表单变更 ({{ formChanges.length }})</span>
        </div>
        <div class="change-list">
          <div v-for="change in formChanges" :key="change.code" class="change-item-wrapper">
            <div
              class="change-item clickable"
              :class="change.change_type"
              @click="toggleExpand('form', change.code)"
            >
              <span class="change-tag" :class="change.change_type">
                {{ changeTypeLabel(change.change_type) }}
              </span>
              <span class="change-name">{{ change.name }}</span>
              <span v-if="change.component_changes && change.component_changes.length > 0" class="component-changes">
                ({{ change.component_changes.length }} 个组件变更)
              </span>
              <span class="expand-icon">{{ isExpanded('form', change.code) ? '▼' : '▶' }}</span>
            </div>
            <div v-if="isExpanded('form', change.code)" class="change-detail">
              <!-- 组件变更详情 -->
              <div v-if="change.component_changes && change.component_changes.length > 0" class="component-changes-detail">
                <div class="nested-label">组件变更</div>
                <div class="nested-list">
                  <div
                    v-for="comp in change.component_changes"
                    :key="comp.code"
                    class="nested-item"
                    :class="comp.change_type"
                  >
                    <span class="change-tag small" :class="comp.change_type">
                      {{ changeTypeLabel(comp.change_type) }}
                    </span>
                    <span class="comp-label">{{ comp.name }}</span>
                    <span class="comp-type">[{{ formatComponentType(comp.component_type) }}]</span>
                    <span v-if="comp.is_sub_table" class="sub-table-badge">子表</span>
                    <span v-if="comp.table_model_code && !comp.is_sub_table" class="sub-table-badge child">
                      {{ comp.table_model_code }}
                    </span>
                    <span v-if="comp.changed_properties && comp.changed_properties.length > 0" class="changed-props">
                      变更: {{ comp.changed_properties.join(', ') }}
                    </span>
                  </div>
                </div>
              </div>
              <SideBySideDiff
                :old-value="change.old_value"
                :new-value="change.new_value"
                resource-type="form"
              />
            </div>
          </div>
        </div>
      </div>

      <!-- 流程变更 -->
      <div v-if="processChanges.length > 0" class="diff-section">
        <div class="section-title">
          <span class="icon">⚡</span>
          <span>流程变更 ({{ processChanges.length }})</span>
        </div>
        <div class="change-list">
          <div v-for="change in processChanges" :key="change.code" class="change-item-wrapper">
            <div
              class="change-item clickable"
              :class="change.change_type"
              @click="toggleExpand('process', change.code)"
            >
              <span class="change-tag" :class="change.change_type">
                {{ changeTypeLabel(change.change_type) }}
              </span>
              <span class="change-name">{{ change.name }}</span>
              <span class="expand-icon">{{ isExpanded('process', change.code) ? '▼' : '▶' }}</span>
            </div>
            <div v-if="isExpanded('process', change.code)" class="change-detail">
              <SideBySideDiff
                :old-value="change.old_value"
                :new-value="change.new_value"
                resource-type="process"
              />
            </div>
          </div>
        </div>
      </div>

      <!-- 警告 -->
      <div v-if="warnings.length > 0" class="warnings-section">
        <div class="section-title warning">
          <span class="icon">⚠️</span>
          <span>注意事项</span>
        </div>
        <ul class="warning-list">
          <li v-for="(warning, idx) in warnings" :key="idx">{{ warning }}</li>
        </ul>
      </div>

      <!-- 不支持的变更 -->
      <div v-if="unsupportedChanges.length > 0" class="unsupported-section">
        <div class="section-title unsupported">
          <span class="icon">🚫</span>
          <span>不支持的变更</span>
        </div>
        <ul class="unsupported-list">
          <li v-for="(item, idx) in unsupportedChanges" :key="idx">{{ item }}</li>
        </ul>
      </div>
    </div>

    <!-- 操作按钮 -->
    <div v-if="hasChanges && showActions" class="diff-actions">
      <button class="btn-cancel" @click="$emit('cancel')">取消</button>
      <button class="btn-execute" :disabled="executing" @click="$emit('execute')">
        {{ executing ? '执行中...' : '确认更新' }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { ChangeItem, DictChange, ModelChange, FormChange } from '@/api/incremental'
import SideBySideDiff from './SideBySideDiff.vue'

interface Props {
  hasChanges: boolean
  summary: string
  roleChanges: ChangeItem[]
  dictChanges: DictChange[]
  modelChanges: ModelChange[]
  formChanges: FormChange[]
  processChanges: ChangeItem[]
  warnings: string[]
  unsupportedChanges: string[]
  showActions?: boolean
  executing?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  showActions: true,
  executing: false
})

defineEmits<{
  cancel: []
  execute: []
}>()

// 展开状态管理
const expandedItems = ref<Set<string>>(new Set())

const getExpandKey = (type: string, code: string): string => {
  return `${type}:${code}`
}

const isExpanded = (type: string, code: string): boolean => {
  return expandedItems.value.has(getExpandKey(type, code))
}

const toggleExpand = (type: string, code: string): void => {
  const key = getExpandKey(type, code)
  if (expandedItems.value.has(key)) {
    expandedItems.value.delete(key)
  } else {
    expandedItems.value.add(key)
  }
}

const changeTypeLabel = (type: string) => {
  switch (type) {
    case 'added': return '新增'
    case 'modified': return '修改'
    case 'deleted': return '删除'
    default: return type
  }
}

const formatComponentType = (type?: string): string => {
  if (!type) return '未知'
  const typeMap: Record<string, string> = {
    'FORM_TEXT_INPUT': '文本',
    'FORM_NUMBER_INPUT': '数字',
    'FORM_SELECT': '下拉',
    'FORM_RADIO': '单选',
    'FORM_CHECKBOX': '多选',
    'FORM_DATE': '日期',
    'FORM_DATETIME': '日期时间',
    'FORM_TEXTAREA': '多行文本',
    'FORM_FILE': '文件',
    'FORM_IMAGE': '图片',
    'FORM_WIDGET_SON_TABLE': '子表',
    'FORM_SWITCH': '开关',
    'FORM_CASCADER': '级联',
    'FORM_USER_SELECT': '人员选择',
    'FORM_DEPT_SELECT': '部门选择',
  }
  return typeMap[type] || type.replace('FORM_', '').replace('_', ' ')
}
</script>

<style scoped lang="less">
.config-diff {
  background: #1a1a2e;
  border-radius: 12px;
  padding: 16px;
  color: #e0e0e0;
}

.diff-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid rgba(255,255,255,0.1);
}

.diff-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
}

.diff-summary {
  font-size: 13px;
  color: #888;
}

.no-changes {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 32px;
  color: #4ade80;
  font-size: 14px;
}

.no-changes .icon {
  font-size: 20px;
}

.diff-section {
  margin-bottom: 16px;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 500;
  margin-bottom: 8px;
  color: #fff;
}

.section-title.warning {
  color: #fbbf24;
}

.section-title.unsupported {
  color: #f87171;
}

.section-title .icon {
  font-size: 16px;
}

.change-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.change-item-wrapper {
  display: flex;
  flex-direction: column;
}

.change-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: rgba(255,255,255,0.05);
  border-radius: 6px;
  font-size: 13px;
}

.change-item.clickable {
  cursor: pointer;
  transition: background 0.2s;
}

.change-item.clickable:hover {
  background: rgba(255,255,255,0.08);
}

.expand-icon {
  margin-left: auto;
  font-size: 10px;
  color: #666;
  transition: transform 0.2s;
}

.change-detail {
  padding: 12px;
  margin-top: 4px;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 6px;
  border-left: 3px solid rgba(99, 102, 241, 0.5);
}

.change-tag {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
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

.change-name {
  font-weight: 500;
}

.change-code {
  color: #888;
  font-size: 12px;
}

.option-changes,
.field-changes,
.component-changes {
  color: #888;
  font-size: 12px;
}

.component-changes-detail {
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid rgba(255,255,255,0.1);
}

.nested-label {
  font-size: 12px;
  color: #888;
  margin-bottom: 8px;
}

.nested-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.nested-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: rgba(255,255,255,0.03);
  border-radius: 4px;
  font-size: 12px;
}

.nested-item.added {
  border-left: 2px solid #4ade80;
}

.nested-item.modified {
  border-left: 2px solid #fbbf24;
}

.nested-item.deleted {
  border-left: 2px solid #f87171;
}

.change-tag.small {
  padding: 1px 6px;
  font-size: 10px;
}

.comp-label {
  font-weight: 500;
  color: #e0e0e0;
}

.comp-type {
  color: #6b7280;
  font-size: 11px;
}

.sub-table-badge {
  padding: 1px 6px;
  background: rgba(139, 92, 246, 0.2);
  color: #a78bfa;
  border-radius: 3px;
  font-size: 10px;
}

.sub-table-badge.child {
  background: rgba(99, 102, 241, 0.15);
  color: #818cf8;
}

.changed-props {
  color: #fbbf24;
  font-size: 11px;
  margin-left: auto;
}

.warning-list,
.unsupported-list {
  margin: 0;
  padding-left: 24px;
  font-size: 13px;
}

.warning-list li {
  color: #fbbf24;
  margin-bottom: 4px;
}

.unsupported-list li {
  color: #f87171;
  margin-bottom: 4px;
}

.diff-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid rgba(255,255,255,0.1);
}

.btn-cancel {
  padding: 8px 16px;
  background: transparent;
  border: 1px solid rgba(255,255,255,0.2);
  border-radius: 6px;
  color: #888;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-cancel:hover {
  border-color: rgba(255,255,255,0.4);
  color: #fff;
}

.btn-execute {
  padding: 8px 20px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border: none;
  border-radius: 6px;
  color: #fff;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-execute:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.4);
}

.btn-execute:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
