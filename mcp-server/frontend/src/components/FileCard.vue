<template>
  <div class="msg-file-card">
    <div class="file-card-header" @click="$emit('toggle')">
      <span class="file-card-op" :class="opClass">{{ opSymbol }}</span>
      <span class="file-card-name">{{ fileName }}</span>
      <span class="file-card-badge" :class="badgeClass">{{ badgeText }}</span>
      <svg class="file-card-chevron" :class="{ rotated: !collapsed }" viewBox="0 0 16 16" fill="none">
        <path d="M4 6l4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </div>
    <div v-if="!collapsed && fileContent" class="file-card-code">
      <pre><code>{{ fileContent }}</code></pre>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  /** 操作类型：write=新建、edit=修改 */
  action: 'write' | 'edit'
  fileName?: string
  fileContent?: string
  collapsed?: boolean
}>()

defineEmits<{ toggle: [] }>()

const opSymbol = computed(() => props.action === 'write' ? '+' : '~')
const opClass = computed(() => props.action === 'write' ? 'file-card-op--new' : 'file-card-op--edit')
const badgeText = computed(() => props.action === 'write' ? '新建' : '修改')
const badgeClass = computed(() => props.action === 'write' ? 'file-card-badge--new' : 'file-card-badge--edit')
</script>

<style scoped>
.msg-file-card {
  border: 1px solid var(--t-border-subtle);
  border-radius: var(--t-radius-sm);
  overflow: hidden;
  margin: 4px 0;
  background: var(--t-bg-panel);
  box-shadow: var(--t-shadow-sm);
}

.file-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 12px;
  cursor: pointer;
  font-size: 12px;
  font-family: 'SF Mono', 'Monaco', 'Menlo', monospace;
  transition: background 0.15s;
  background: var(--t-bg-panel);
}
.file-card-header:hover {
  background: var(--t-bg-panel-hover);
}

.file-card-op {
  font-weight: 700;
  font-size: 13px;
  width: 14px;
  text-align: center;
  flex-shrink: 0;
}
.file-card-op--new { color: var(--t-success); }
.file-card-op--edit { color: var(--t-warning); }

.file-card-name {
  flex: 1;
  color: var(--t-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-card-badge {
  font-size: 10px;
  font-weight: 500;
  padding: 2px 7px;
  border-radius: 10px;
  flex-shrink: 0;
}
.file-card-badge--new {
  background: var(--t-success-subtle);
  color: var(--t-success);
}
.file-card-badge--edit {
  background: var(--t-warning-subtle);
  color: var(--t-warning);
}

.file-card-chevron {
  width: 14px;
  height: 14px;
  color: var(--t-text-muted);
  flex-shrink: 0;
  transition: transform 0.2s;
}
.file-card-chevron.rotated {
  transform: rotate(180deg);
}

.file-card-code {
  border-top: 1px solid var(--t-border-subtle);
  max-height: 300px;
  overflow: auto;
  background: var(--t-bg-code);
}
.file-card-code pre {
  margin: 0;
  padding: 12px;
  font-size: 12px;
  line-height: 1.5;
  font-family: 'SF Mono', 'Monaco', 'Menlo', monospace;
  color: var(--t-text-primary);
  white-space: pre;
  overflow-x: auto;
}
</style>
