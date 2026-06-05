<template>
  <div class="config-diff">
    <div class="diff-header">
      <h3>配置变更</h3>
      <span class="diff-summary">{{ summary }}</span>
    </div>

    <div v-if="!hasChanges" class="no-changes">
      <span class="icon"><AppIcon name="check" :size="20" /></span>
      <span>配置无变更</span>
    </div>

    <div v-else class="diff-content">
      <!-- 选择操作栏 -->
      <div v-if="selectable" class="selection-bar">
        <span class="selection-info">已选 {{ selectedCount }}/{{ totalChanges }} 项</span>
        <button class="btn-link" @click="selectAll">全选</button>
        <button class="btn-link" @click="deselectAll">取消全选</button>
      </div>

      <!-- 角色变更 -->
      <div v-if="roleChanges.length > 0" class="diff-section">
        <div class="section-title">
          <span class="icon"><AppIcon name="user" :size="16" /></span>
          <span>角色变更 ({{ roleChanges.length }})</span>
        </div>
        <div class="change-list">
          <div v-for="change in roleChanges" :key="change.code" class="change-item-wrapper">
            <div
              class="change-item clickable"
              :class="change.change_type"
              @click="toggleExpand('role', change.code)"
            >
              <input
                v-if="selectable"
                type="checkbox"
                class="change-checkbox"
                :checked="isSelected('role', change.code)"
                @click.stop="toggleSelection('role', change.code)"
              />
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
          <span class="icon"><AppIcon name="book-open" :size="16" /></span>
          <span>字典变更 ({{ dictChanges.length }})</span>
        </div>
        <div class="change-list">
          <div v-for="change in dictChanges" :key="change.code" class="change-item-wrapper">
            <div
              class="change-item clickable"
              :class="change.change_type"
              @click="toggleExpand('dict', change.code)"
            >
              <input
                v-if="selectable"
                type="checkbox"
                class="change-checkbox"
                :checked="isSelected('dict', change.code)"
                @click.stop="toggleSelection('dict', change.code)"
              />
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
          <span class="icon"><AppIcon name="bar-chart" :size="16" /></span>
          <span>模型变更 ({{ modelChanges.length }})</span>
        </div>
        <div class="change-list">
          <div v-for="change in modelChanges" :key="change.code" class="change-item-wrapper">
            <div
              class="change-item clickable"
              :class="change.change_type"
              @click="toggleExpand('model', change.code)"
            >
              <input
                v-if="selectable"
                type="checkbox"
                class="change-checkbox"
                :checked="isSelected('model', change.code)"
                @click.stop="toggleSelection('model', change.code)"
              />
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
          <span class="icon"><AppIcon name="edit" :size="16" /></span>
          <span>表单变更 ({{ formChanges.length }})</span>
        </div>
        <div class="change-list">
          <div v-for="change in formChanges" :key="change.code" class="change-item-wrapper">
            <div
              class="change-item clickable"
              :class="change.change_type"
              @click="toggleExpand('form', change.code)"
            >
              <input
                v-if="selectable"
                type="checkbox"
                class="change-checkbox"
                :checked="isSelected('form', change.code)"
                @click.stop="toggleSelection('form', change.code)"
              />
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
          <span class="icon"><AppIcon name="zap" :size="16" /></span>
          <span>流程变更 ({{ processChanges.length }})</span>
        </div>
        <div class="change-list">
          <div v-for="change in processChanges" :key="change.code" class="change-item-wrapper">
            <div
              class="change-item clickable"
              :class="change.change_type"
              @click="toggleExpand('process', change.code)"
            >
              <input
                v-if="selectable"
                type="checkbox"
                class="change-checkbox"
                :checked="isSelected('process', change.code)"
                @click.stop="toggleSelection('process', change.code)"
              />
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
          <span class="icon"><AppIcon name="warning" :size="16" /></span>
          <span>注意事项</span>
        </div>
        <ul class="warning-list">
          <li v-for="(warning, idx) in warnings" :key="idx">{{ warning }}</li>
        </ul>
      </div>

      <!-- 不支持的变更 -->
      <div v-if="unsupportedChanges.length > 0" class="unsupported-section">
        <div class="section-title unsupported">
          <span class="icon"><AppIcon name="ban" :size="16" /></span>
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
import { ref, computed, watch } from 'vue'
import type { ChangeItem, DictChange, ModelChange, FormChange } from '@/api/incremental'
import SideBySideDiff from './SideBySideDiff.vue'
import AppIcon from '@/components/common/AppIcon.vue'

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
  selectable?: boolean  // 是否启用选择模式
}

const props = withDefaults(defineProps<Props>(), {
  showActions: true,
  executing: false,
  selectable: false,
})

const emit = defineEmits<{
  cancel: []
  execute: []
  'selection-change': [selected: { type: string; code: string; change_type: string }[]]
}>()

// ── 选择状态 ──
const selectedKeys = ref<Set<string>>(new Set())

const makeKey = (type: string, code: string) => `${type}:${code}`

// 初始化：全选
watch(() => [props.roleChanges, props.dictChanges, props.modelChanges, props.formChanges, props.processChanges], () => {
  if (!props.selectable) return
  const keys = new Set<string>()
  for (const c of props.roleChanges) keys.add(makeKey('role', c.code))
  for (const c of props.dictChanges) keys.add(makeKey('dict', c.code))
  for (const c of props.modelChanges) keys.add(makeKey('model', c.code))
  for (const c of props.formChanges) keys.add(makeKey('form', c.code))
  for (const c of props.processChanges) keys.add(makeKey('process', c.code))
  selectedKeys.value = keys
}, { immediate: true })

const isSelected = (type: string, code: string) => selectedKeys.value.has(makeKey(type, code))

const toggleSelection = (type: string, code: string) => {
  const key = makeKey(type, code)
  const newSet = new Set(selectedKeys.value)
  if (newSet.has(key)) newSet.delete(key)
  else newSet.add(key)
  selectedKeys.value = newSet
  emitSelection()
}

const selectAll = () => {
  const keys = new Set<string>()
  for (const c of props.roleChanges) keys.add(makeKey('role', c.code))
  for (const c of props.dictChanges) keys.add(makeKey('dict', c.code))
  for (const c of props.modelChanges) keys.add(makeKey('model', c.code))
  for (const c of props.formChanges) keys.add(makeKey('form', c.code))
  for (const c of props.processChanges) keys.add(makeKey('process', c.code))
  selectedKeys.value = keys
  emitSelection()
}

const deselectAll = () => {
  selectedKeys.value = new Set()
  emitSelection()
}

const totalChanges = computed(() =>
  props.roleChanges.length + props.dictChanges.length +
  props.modelChanges.length + props.formChanges.length + props.processChanges.length
)

const selectedCount = computed(() => selectedKeys.value.size)

const emitSelection = () => {
  const selected: { type: string; code: string; change_type: string }[] = []
  const collect = (type: string, changes: ChangeItem[]) => {
    for (const c of changes) {
      if (selectedKeys.value.has(makeKey(type, c.code))) {
        selected.push({ type, code: c.code, change_type: c.change_type })
      }
    }
  }
  collect('role', props.roleChanges)
  collect('dict', props.dictChanges)
  collect('model', props.modelChanges)
  collect('form', props.formChanges)
  collect('process', props.processChanges)
  emit('selection-change', selected)
}

defineExpose({ getSelectedChanges: () => {
  const selected: { type: string; code: string; change_type: string }[] = []
  const collect = (type: string, changes: ChangeItem[]) => {
    for (const c of changes) {
      if (selectedKeys.value.has(makeKey(type, c.code))) {
        selected.push({ type, code: c.code, change_type: c.change_type })
      }
    }
  }
  collect('role', props.roleChanges)
  collect('dict', props.dictChanges)
  collect('model', props.modelChanges)
  collect('form', props.formChanges)
  collect('process', props.processChanges)
  return selected
}})

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
    'FORM_DEPARTMENT_SELECT': '部门选择',
  }
  return typeMap[type] || type.replace('FORM_', '').replace('_', ' ')
}
</script>

<style scoped lang="less">
.config-diff {
  background: var(--t-bg-panel);
  border-radius: 12px;
  padding: 16px;
  color: var(--t-text-primary);
}

.diff-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--t-border-strong);
}

.diff-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
}

.diff-summary {
  font-size: 13px;
  color: var(--t-text-secondary);
}

.no-changes {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 32px;
  color: var(--t-success);
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
  color: var(--t-warning);
}

.section-title.unsupported {
  color: var(--t-danger);
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
  background: var(--t-bg-subtle);
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
  color: var(--t-text-muted);
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
  color: var(--t-success);
}

.change-tag.modified {
  background: rgba(251, 191, 36, 0.2);
  color: var(--t-warning);
}

.change-tag.deleted {
  background: rgba(248, 113, 113, 0.2);
  color: var(--t-danger);
}

.change-name {
  font-weight: 500;
}

.change-code {
  color: var(--t-text-secondary);
  font-size: 12px;
}

.option-changes,
.field-changes,
.component-changes {
  color: var(--t-text-secondary);
  font-size: 12px;
}

.component-changes-detail {
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--t-border-strong);
}

.nested-label {
  font-size: 12px;
  color: var(--t-text-secondary);
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
  background: var(--t-bg-subtle);
  border-radius: 4px;
  font-size: 12px;
}

.nested-item.added {
  border-left: 2px solid var(--t-success);
}

.nested-item.modified {
  border-left: 2px solid var(--t-warning);
}

.nested-item.deleted {
  border-left: 2px solid var(--t-danger);
}

.change-tag.small {
  padding: 1px 6px;
  font-size: 10px;
}

.comp-label {
  font-weight: 500;
  color: var(--t-text-primary);
}

.comp-type {
  color: #6b7280;
  font-size: 11px;
}

.sub-table-badge {
  padding: 1px 6px;
  background: var(--t-brand-subtle);
  color: var(--t-brand-light);
  border-radius: 3px;
  font-size: 10px;
}

.sub-table-badge.child {
  background: rgba(99, 102, 241, 0.15);
  color: var(--t-brand-light);
}

.changed-props {
  color: var(--t-warning);
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
  color: var(--t-warning);
  margin-bottom: 4px;
}

.unsupported-list li {
  color: var(--t-danger);
  margin-bottom: 4px;
}

.diff-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--t-border-strong);
}

.btn-cancel {
  padding: 8px 16px;
  background: transparent;
  border: 1px solid var(--t-border-strong);
  border-radius: 6px;
  color: var(--t-text-secondary);
  cursor: pointer;
  transition: all 0.2s;
}

.btn-cancel:hover {
  border-color: rgba(255,255,255,0.4);
  color: #fff;
}

.btn-execute {
  padding: 8px 20px;
  background: var(--t-brand-gradient);
  border: none;
  border-radius: 6px;
  color: #fff;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-execute:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px var(--t-brand-glow);
}

.btn-execute:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.selection-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  margin-bottom: 12px;
  background: rgba(99, 102, 241, 0.1);
  border-radius: 6px;
  font-size: 13px;
}

.selection-info {
  color: #a5b4fc;
  font-weight: 500;
}

.btn-link {
  background: none;
  border: none;
  color: var(--t-brand-light);
  cursor: pointer;
  font-size: 12px;
  padding: 2px 6px;
  border-radius: 4px;
  transition: all 0.2s;
}

.btn-link:hover {
  background: rgba(99, 102, 241, 0.2);
  color: #a5b4fc;
}

.change-checkbox {
  width: 16px;
  height: 16px;
  cursor: pointer;
  accent-color: var(--t-brand-light);
  flex-shrink: 0;
}
</style>
