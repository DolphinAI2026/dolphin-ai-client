<script setup lang="ts">
import { useSpecStore } from '@/stores/spec'
import type { Goal } from '@/types/spec'
import { ElMessage } from 'element-plus'

const props = defineProps<{ goal: Goal }>()
const spec = useSpecStore()

// Goal uses singleton-style item update; we treat code as fixed sentinel "_goal"
async function confirm() {
  try {
    // PUT /spec/{id}/items/role/_goal won't work — goal isn't a "role". Goal confirmation
    // is intentionally NOT in the items REST surface for Phase α. Frontend handles by
    // mutating the role-equivalent through a dedicated path or just hides the button.
    // For Phase β: skip confirm action; goal flips to confirmed=true through LLM tool call.
    ElMessage.info('应用目标在 SPEC 流程中由 AI 自动采纳（暂不支持手动采纳按钮）')
  } catch (e: unknown) {
    ElMessage.error(String(e))
  }
}

// Keep references used by template-only refs satisfied
void confirm
void props
void spec
</script>

<template>
  <article class="spec-card goal-card" :class="{ confirmed: goal.confirmed }">
    <header class="spec-card-header">
      <h3 class="spec-card-title">{{ goal.title }}</h3>
      <span v-if="goal.confirmed" class="spec-card-status">✓ 已采纳</span>
    </header>
    <p class="spec-card-desc"><strong>业务问题：</strong>{{ goal.business_problem }}</p>
    <p class="spec-card-desc"><strong>系统简介：</strong>{{ goal.summary }}</p>
  </article>
</template>

<style scoped>
.spec-card {
  border: 1px solid var(--t-border-subtle);
  border-radius: 12px;
  padding: 14px 16px;
  background: var(--t-bg-panel);
}
.goal-card {
  box-shadow: inset 3px 0 0 var(--t-brand);
}
.goal-card.confirmed {
  border-color: var(--t-border-strong);
  box-shadow: inset 3px 0 0 var(--t-success);
}
.spec-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}
.spec-card-title {
  margin: 0;
  color: var(--t-text-primary);
  font-size: 15px;
  line-height: 1.35;
}
.spec-card-desc {
  margin: 5px 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--t-text-secondary);
}
.spec-card-desc strong {
  color: var(--t-text-primary);
  font-weight: 600;
}
.spec-card-status {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 8px;
  border: 1px solid var(--t-border-subtle);
  border-radius: 999px;
  background: var(--t-success-subtle);
  color: var(--t-success);
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
}
</style>
