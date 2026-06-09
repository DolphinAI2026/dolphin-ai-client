<template>
  <div class="update-steps">
    <div class="steps-header">
      <h3>增量更新</h3>
      <span class="steps-status" :class="overallStatus">
        {{ statusLabel }}
      </span>
    </div>

    <div class="steps-list">
      <div v-for="(step, idx) in steps" :key="step.key" class="step-item" :class="step.status">
        <div class="step-icon">
          <span v-if="step.status === 'completed'" class="icon-done"><AppIcon name="check" :size="14" /></span>
          <span v-else-if="step.status === 'running'" class="icon-running"><AppIcon name="refresh" :size="14" /></span>
          <span v-else-if="step.status === 'error'" class="icon-error"><AppIcon name="x" :size="14" /></span>
          <span v-else class="icon-pending">{{ idx + 1 }}</span>
        </div>
        <div class="step-content">
          <div class="step-label">{{ step.label }}</div>
          <div v-if="step.details" class="step-details">{{ step.details }}</div>
          <div v-if="step.error" class="step-error">{{ step.error }}</div>
        </div>
      </div>
    </div>

    <div v-if="results && Object.keys(results).length > 0" class="results-section">
      <div class="results-title">执行结果</div>
      <div v-for="(items, category) in results" :key="category" class="result-category">
        <div v-if="items.length > 0" class="category-label">{{ categoryLabel(category) }}</div>
        <ul v-if="items.length > 0">
          <li v-for="(item, idx) in items" :key="idx">{{ item }}</li>
        </ul>
      </div>
    </div>

    <div v-if="errors && errors.length > 0" class="errors-section">
      <div class="errors-title">错误信息</div>
      <ul>
        <li v-for="(error, idx) in errors" :key="idx">{{ error }}</li>
      </ul>
    </div>

    <div v-if="warnings && warnings.length > 0" class="warnings-section">
      <div class="warnings-title">警告信息</div>
      <ul>
        <li v-for="(warning, idx) in warnings" :key="idx">{{ warning }}</li>
      </ul>
    </div>

    <div class="steps-actions">
      <button v-if="!executing && overallStatus !== 'completed'" class="btn-execute" @click="$emit('execute')">
        开始更新
      </button>
      <button v-if="executing" class="btn-cancel" @click="$emit('cancel')">
        取消
      </button>
      <button v-if="overallStatus === 'completed'" class="btn-close" @click="$emit('close')">
        完成
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import AppIcon from '@/components/common/AppIcon.vue'

interface Step {
  key: string
  label: string
  status: 'pending' | 'running' | 'completed' | 'error'
  details?: string
  error?: string
}

interface Props {
  steps: Step[]
  executing?: boolean
  results?: Record<string, string[]>
  errors?: string[]
  warnings?: string[]
}

const props = withDefaults(defineProps<Props>(), {
  executing: false,
  results: () => ({}),
  errors: () => [],
  warnings: () => []
})

defineEmits<{
  execute: []
  cancel: []
  close: []
}>()

const overallStatus = computed(() => {
  if (props.steps.some(s => s.status === 'error')) return 'error'
  if (props.steps.every(s => s.status === 'completed')) return 'completed'
  if (props.steps.some(s => s.status === 'running')) return 'running'
  return 'pending'
})

const statusLabel = computed(() => {
  switch (overallStatus.value) {
    case 'completed': return '已完成'
    case 'running': return '执行中'
    case 'error': return '执行失败'
    default: return '待执行'
  }
})

const categoryLabel = (category: string) => {
  const labels: Record<string, string> = {
    roles: '角色',
    dicts: '字典',
    models: '模型',
    forms: '表单',
    processes: '流程'
  }
  return labels[category] || category
}
</script>

<style scoped lang="less">
.update-steps {
  background: var(--t-bg-panel);
  border-radius: 12px;
  padding: 16px;
  color: var(--t-text-primary);
}

.steps-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--t-border-strong);
}

.steps-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
}

.steps-status {
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 500;
}

.steps-status.pending {
  background: rgba(156, 163, 175, 0.2);
  color: #9ca3af;
}

.steps-status.running {
  background: rgba(59, 130, 246, 0.2);
  color: var(--t-info);
}

.steps-status.completed {
  background: rgba(74, 222, 128, 0.2);
  color: var(--t-success);
}

.steps-status.error {
  background: rgba(248, 113, 113, 0.2);
  color: var(--t-danger);
}

.steps-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.step-item {
  display: flex;
  gap: 12px;
  padding: 12px;
  background: var(--t-bg-subtle);
  border-radius: 8px;
  transition: all 0.2s;
}

.step-item.running {
  background: rgba(59, 130, 246, 0.1);
  border: 1px solid rgba(59, 130, 246, 0.3);
}

.step-item.completed {
  background: rgba(74, 222, 128, 0.1);
}

.step-item.error {
  background: rgba(248, 113, 113, 0.1);
  border: 1px solid rgba(248, 113, 113, 0.3);
}

.step-icon {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  font-size: 14px;
  font-weight: 600;
  flex-shrink: 0;
}

.icon-pending {
  background: rgba(156, 163, 175, 0.2);
  color: #9ca3af;
}

.icon-running {
  background: rgba(59, 130, 246, 0.2);
  color: var(--t-info);
  animation: spin 1s linear infinite;
}

.icon-done {
  background: rgba(74, 222, 128, 0.2);
  color: var(--t-success);
}

.icon-error {
  background: rgba(248, 113, 113, 0.2);
  color: var(--t-danger);
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.step-content {
  flex: 1;
}

.step-label {
  font-weight: 500;
  margin-bottom: 4px;
}

.step-details {
  font-size: 12px;
  color: var(--t-text-secondary);
}

.step-error {
  font-size: 12px;
  color: var(--t-danger);
  margin-top: 4px;
}

.results-section,
.errors-section,
.warnings-section {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--t-border-strong);
}

.results-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--t-success);
  margin-bottom: 8px;
}

.errors-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--t-danger);
  margin-bottom: 8px;
}

.warnings-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--t-warning);
  margin-bottom: 8px;
}

.result-category {
  margin-bottom: 8px;
}

.category-label {
  font-size: 12px;
  color: var(--t-text-secondary);
  margin-bottom: 4px;
}

.results-section ul,
.errors-section ul,
.warnings-section ul {
  margin: 0;
  padding-left: 20px;
  font-size: 13px;
}

.results-section li {
  color: var(--t-success);
  margin-bottom: 2px;
}

.errors-section li {
  color: var(--t-danger);
  margin-bottom: 2px;
}

.warnings-section li {
  color: var(--t-warning);
  margin-bottom: 2px;
}

.steps-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--t-border-strong);
}

.btn-execute,
.btn-close {
  padding: 8px 20px;
  background: var(--t-brand-gradient);
  border: none;
  border-radius: 6px;
  color: #fff;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-execute:hover,
.btn-close:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px var(--t-brand-glow);
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
</style>
