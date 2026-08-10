<script setup lang="ts">
import { computed } from 'vue'
import AppIcon from '@/components/common/AppIcon.vue'
import type {
  SystemAssistantBaselineNode,
  SystemAssistantBootstrap,
  SystemAssistantBaselineStatus,
} from '@/api/systemAssistant'

const props = withDefaults(defineProps<{
  bootstrap: SystemAssistantBootstrap
  compact?: boolean
}>(), {
  compact: false,
})

const nodeIcons: Record<string, string> = {
  workspace: 'folder',
  environment: 'monitor',
  capability: 'puzzle',
  knowledge: 'book-open',
  skill: 'sparkles',
  governance: 'shield',
  templates: 'package',
}

const statusLabels: Record<SystemAssistantBaselineStatus, string> = {
  ready: '已就绪',
  partial: '待补充',
  missing: '未建立',
  stale: '需更新',
  unavailable: '暂不可读',
  not_needed: '无需配置',
}

const visibleNodes = computed(() => props.bootstrap.baseline_snapshot.nodes)
const readyCount = computed(() => visibleNodes.value.filter(node => node.status === 'ready' || node.status === 'not_needed').length)
const attentionCount = computed(() => visibleNodes.value.length - readyCount.value)
const generatedAt = computed(() => {
  const value = props.bootstrap.baseline_snapshot.generated_at
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString('zh-CN', { hour12: false })
})

function nodeSummary(node: SystemAssistantBaselineNode): string {
  if (node.items.length) return `${node.items.length} 项可见`
  if (node.metadata.reason === 'tenant_admin_required') return '需要管理员权限'
  if (node.source_status === 'unavailable') return '来源尚未接入'
  return statusLabels[node.status]
}
</script>

<template>
  <section v-if="compact" class="baseline-compact" aria-label="企业 Code 基线摘要">
    <span class="baseline-compact-mark"><AppIcon name="sparkles" :size="14" /></span>
    <span class="baseline-compact-title">企业 Code 基线</span>
    <span class="baseline-compact-summary">{{ readyCount }} 项就绪，{{ attentionCount }} 项待处理</span>
  </section>

  <section v-else class="baseline" aria-label="企业 Code 基线">
    <div class="baseline-intro">
      <span class="baseline-mark"><AppIcon name="sparkles" :size="20" /></span>
      <div>
        <p class="baseline-kicker">系统助手</p>
        <h1>从企业现状出发，完善你的 Code 能力</h1>
        <p class="baseline-copy">
          我会先读取当前工程、环境、能力、知识和治理边界，再处理你指定的任务。技术栈以实际工程为准。
        </p>
      </div>
    </div>

    <div class="baseline-grid">
      <div
        v-for="node in visibleNodes"
        :key="node.id"
        class="baseline-node"
        :class="`is-${node.status}`"
      >
        <span class="baseline-node-icon"><AppIcon :name="nodeIcons[node.id] || 'box'" :size="16" /></span>
        <span class="baseline-node-copy">
          <strong>{{ node.label }}</strong>
          <small>{{ nodeSummary(node) }}</small>
        </span>
        <span class="baseline-node-status">{{ statusLabels[node.status] }}</span>
      </div>
    </div>

    <p v-if="generatedAt" class="baseline-time">基线更新时间：{{ generatedAt }}</p>
  </section>
</template>

<style scoped>
.baseline {
  width: min(820px, calc(100% - 36px));
  margin: 38px auto 22px;
  color: var(--text);
}

.baseline-intro {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  padding: 0 4px 22px;
}

.baseline-mark {
  width: 42px;
  height: 42px;
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  border-radius: 8px;
  background: color-mix(in srgb, var(--brand) 14%, var(--surface));
  color: var(--brand);
}

.baseline-kicker {
  margin: 1px 0 5px;
  color: var(--brand);
  font-size: 12px;
  font-weight: 600;
}

.baseline h1 {
  margin: 0;
  font-size: 24px;
  line-height: 1.25;
  font-weight: 650;
  letter-spacing: 0;
}

.baseline-copy {
  max-width: 680px;
  margin: 9px 0 0;
  color: var(--text-3);
  font-size: 13.5px;
  line-height: 1.65;
}

.baseline-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
}

.baseline-node {
  min-width: 0;
  min-height: 64px;
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--line);
}

.baseline-node:nth-child(odd) {
  border-right: 1px solid var(--line);
}

.baseline-node:nth-last-child(-n + 2) {
  border-bottom: 0;
}

.baseline-node-icon {
  width: 30px;
  height: 30px;
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  border-radius: 7px;
  background: var(--surface-2);
  color: var(--text-3);
}

.baseline-node.is-ready .baseline-node-icon,
.baseline-node.is-not_needed .baseline-node-icon {
  background: color-mix(in srgb, var(--success, #16a34a) 12%, var(--surface));
  color: var(--success, #15803d);
}

.baseline-node.is-partial .baseline-node-icon,
.baseline-node.is-stale .baseline-node-icon,
.baseline-node.is-missing .baseline-node-icon {
  background: color-mix(in srgb, var(--warning, #d97706) 12%, var(--surface));
  color: var(--warning, #b45309);
}

.baseline-node-copy {
  min-width: 0;
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 3px;
}

.baseline-node-copy strong {
  overflow: hidden;
  color: var(--text);
  font-size: 13px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.baseline-node-copy small {
  overflow: hidden;
  color: var(--text-4);
  font-size: 11.5px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.baseline-node-status {
  flex: 0 0 auto;
  color: var(--text-4);
  font-size: 11.5px;
}

.baseline-time {
  margin: 8px 4px 0;
  color: var(--text-4);
  font-size: 11px;
}

.baseline-compact {
  width: min(820px, calc(100% - 36px));
  min-height: 44px;
  margin: 16px auto 4px;
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 8px 10px 8px 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: color-mix(in srgb, var(--surface-2) 72%, var(--surface));
}

.baseline-compact-mark {
  color: var(--brand);
}

.baseline-compact-title {
  color: var(--text);
  font-size: 12.5px;
  font-weight: 600;
}

.baseline-compact-summary {
  min-width: 0;
  flex: 1;
  color: var(--text-4);
  font-size: 11.5px;
}

@media (max-width: 760px) {
  .baseline {
    width: calc(100% - 24px);
    margin-top: 24px;
  }

  .baseline-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .baseline-node,
  .baseline-node:nth-child(odd),
  .baseline-node:nth-last-child(-n + 2) {
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }

  .baseline-node:last-child {
    border-bottom: 0;
  }

  .baseline-compact {
    width: calc(100% - 24px);
  }

  .baseline-compact-summary {
    display: none;
  }
}
</style>
