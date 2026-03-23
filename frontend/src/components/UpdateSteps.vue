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
          <span v-if="step.status === 'completed'" class="icon-done">✓</span>
          <span v-else-if="step.status === 'running'" class="icon-running">⟳</span>
          <span v-else-if="step.status === 'error'" class="icon-error">✕</span>
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

<style scoped>
.update-steps {
  background: #1a1a2e;
  border-radius: 12px;
  padding: 16px;
  color: #e0e0e0;
}

.steps-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid rgba(255,255,255,0.1);
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
  color: #3b82f6;
}

.steps-status.completed {
  background: rgba(74, 222, 128, 0.2);
  color: #4ade80;
}

.steps-status.error {
  background: rgba(248, 113, 113, 0.2);
  color: #f87171;
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
  background: rgba(255,255,255,0.03);
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
  color: #3b82f6;
  animation: spin 1s linear infinite;
}

.icon-done {
  background: rgba(74, 222, 128, 0.2);
  color: #4ade80;
}

.icon-error {
  background: rgba(248, 113, 113, 0.2);
  color: #f87171;
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
  color: #888;
}

.step-error {
  font-size: 12px;
  color: #f87171;
  margin-top: 4px;
}

.results-section,
.errors-section,
.warnings-section {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid rgba(255,255,255,0.1);
}

.results-title {
  font-size: 14px;
  font-weight: 500;
  color: #4ade80;
  margin-bottom: 8px;
}

.errors-title {
  font-size: 14px;
  font-weight: 500;
  color: #f87171;
  margin-bottom: 8px;
}

.warnings-title {
  font-size: 14px;
  font-weight: 500;
  color: #fbbf24;
  margin-bottom: 8px;
}

.result-category {
  margin-bottom: 8px;
}

.category-label {
  font-size: 12px;
  color: #888;
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
  color: #4ade80;
  margin-bottom: 2px;
}

.errors-section li {
  color: #f87171;
  margin-bottom: 2px;
}

.warnings-section li {
  color: #fbbf24;
  margin-bottom: 2px;
}

.steps-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid rgba(255,255,255,0.1);
}

.btn-execute,
.btn-close {
  padding: 8px 20px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
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
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.4);
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
</style>
