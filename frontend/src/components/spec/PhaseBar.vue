<script setup lang="ts">
import { computed } from 'vue'
import type { Phase } from '@/types/spec'
import { useSpecStore } from '@/stores/spec'
import { ElMessage } from 'element-plus'

const spec = useSpecStore()

interface PhaseStep {
  key: Phase | 'review' | 'deploy'
  label: string
  status: 'done' | 'active' | 'pending'
  clickable: boolean
}

const steps = computed<PhaseStep[]>(() => {
  const p = spec.phase ?? 'gathering'
  const order: Phase[] = ['gathering', 'drafting', 'generating', 'ready']
  const currentIdx = order.indexOf(p)
  return [
    {
      key: 'gathering' as Phase,
      label: '理解需求',
      status: currentIdx > 0 ? 'done' : 'active',
      clickable: currentIdx > 0, // can rewind to gathering
    },
    {
      key: 'drafting' as Phase,
      label: 'SPEC 设计',
      status: currentIdx > 1 ? 'done' : currentIdx === 1 ? 'active' : 'pending',
      clickable: currentIdx >= 1,
    },
    {
      key: 'generating' as Phase,
      label: '配置生成',
      status: currentIdx >= 2 ? (currentIdx > 2 ? 'done' : 'active') : 'pending',
      clickable: false, // generating runs only when SPEC complete
    },
    { key: 'review', label: '验证确认', status: currentIdx > 2 ? 'done' : 'pending', clickable: false },
    { key: 'deploy', label: '部署', status: 'pending', clickable: false },
  ]
})

async function handleClick(step: PhaseStep) {
  if (!step.clickable || step.key === 'review' || step.key === 'deploy') return
  try {
    await spec.transitionPhase(step.key as Phase, '用户在 PhaseBar 点击切换')
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    ElMessage.warning(`无法切换到 ${step.label}：${msg}`)
  }
}
</script>

<template>
  <nav class="phase-bar" aria-label="搭建阶段">
    <button
      v-for="(step, idx) in steps"
      :key="step.key"
      class="phase-step"
      :class="[step.status, { clickable: step.clickable, disabled: !step.clickable }]"
      :disabled="!step.clickable"
      @click="handleClick(step)"
    >
      <span class="phase-index">{{ idx + 1 }}</span>
      <span class="phase-label">{{ step.label }}</span>
    </button>
  </nav>
</template>

<style scoped>
.phase-bar {
  display: flex;
  align-items: center;
  gap: 8px;
}
.phase-step {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: var(--t-radius-md);
  background: var(--t-bg-input);
  color: var(--t-text-secondary);
  border: 1px solid var(--t-border-subtle);
  cursor: pointer;
  font-size: 13px;
  transition: all 0.15s var(--t-ease, cubic-bezier(0.2, 0.9, 0.3, 1));
}
.phase-step.disabled { cursor: not-allowed; opacity: 0.55; }
.phase-step.active {
  background: var(--t-brand-subtle);
  color: var(--t-brand);
  border-color: var(--t-brand);
  font-weight: 600;
}
.phase-step.done {
  background: var(--t-success-subtle);
  color: var(--t-success);
  border-color: var(--t-success-subtle);
}
.phase-step.clickable:hover:not(.disabled) {
  background: var(--t-bg-panel-hover);
}
.phase-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.06);
  font-size: 11px;
  font-weight: 600;
}
.phase-step.active .phase-index { background: var(--t-brand); color: white; }
.phase-step.done .phase-index { background: var(--t-success); color: white; }
</style>
