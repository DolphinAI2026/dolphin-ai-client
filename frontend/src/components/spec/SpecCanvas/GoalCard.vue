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
    ElMessage.info('应用目标在 SPEC 流程中由 AI 自动确认（暂不支持手动确认按钮）')
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
      <h3 class="spec-card-title">🎯 {{ goal.title }}</h3>
      <span v-if="goal.confirmed" class="spec-card-status">✓ 已确认</span>
    </header>
    <p class="spec-card-desc"><strong>业务问题：</strong>{{ goal.business_problem }}</p>
    <p class="spec-card-desc"><strong>系统简介：</strong>{{ goal.summary }}</p>
  </article>
</template>

<style scoped>
.goal-card {
  border-left: 4px solid var(--t-brand);
}
.goal-card.confirmed { border-left-color: var(--t-success); }
.spec-card-header { display: flex; align-items: baseline; justify-content: space-between; }
.spec-card-title { margin: 0 0 8px 0; font-size: 16px; }
.spec-card-desc { margin: 4px 0; font-size: 13px; color: var(--t-text-secondary); }
.spec-card-status { color: var(--t-success); font-size: 12px; font-weight: 600; }
</style>
