<template>
  <section class="workspace-opening" aria-live="polite">
    <div class="workspace-opening-heading">
      <span class="workspace-opening-mark" :class="{ failed: Boolean(error) }">
        <AppIcon :name="error ? 'warning' : 'coding'" :size="22" />
      </span>
      <div>
        <h1>{{ error ? '本地 Code 工作台未能打开' : '正在打开本地 Code 工作台' }}</h1>
        <p>{{ error ? '可在当前页面恢复后重试' : `已用时 ${elapsedSeconds} 秒` }}</p>
      </div>
    </div>

    <ol class="workspace-opening-steps">
      <li
        v-for="(step, index) in steps"
        :key="step.phase"
        :class="stepState(index)"
      >
        <span class="workspace-opening-state">
          <AppIcon v-if="stepState(index) === 'complete'" name="check" :size="15" />
          <AppIcon v-else-if="stepState(index) === 'failed'" name="x" :size="15" />
          <span v-else-if="stepState(index) === 'active'" class="workspace-opening-spinner" />
          <span v-else class="workspace-opening-dot" />
        </span>
        <span>{{ step.label }}</span>
      </li>
    </ol>

    <details v-if="error" class="workspace-opening-details">
      <summary>技术详情</summary>
      <pre>{{ error }}</pre>
    </details>

    <div v-if="error" class="workspace-opening-actions">
      <button type="button" class="primary" :disabled="busy" @click="emit('retry')">
        <AppIcon name="refresh" :size="14" />
        重试
      </button>
      <button v-if="canRestart" type="button" :disabled="busy" @click="emit('restart')">
        <AppIcon name="settings" :size="14" />
        重启本地环境
      </button>
      <button v-if="canRebind" type="button" :disabled="busy" @click="emit('rebind')">
        <AppIcon name="folder" :size="14" />
        重新绑定目录
      </button>
      <button type="button" :disabled="busy" @click="emit('back')">
        <AppIcon name="arrow-right" :size="14" class="workspace-opening-back-icon" />
        返回应用列表
      </button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AppIcon from '@/components/common/AppIcon.vue'
import type { CodeWorkspaceOpenPhase } from '@/api/codeRuntime'

const props = withDefaults(defineProps<{
  phase: CodeWorkspaceOpenPhase
  startedAt: number
  error?: string
  canRestart?: boolean
  canRebind?: boolean
  busy?: boolean
}>(), {
  error: '',
  canRestart: false,
  canRebind: false,
  busy: false,
})

const emit = defineEmits<{
  'retry': []
  'back': []
  'restart': []
  'rebind': []
}>()

const steps: Array<{ phase: CodeWorkspaceOpenPhase; label: string }> = [
  { phase: 'checking_project', label: '检查本地项目' },
  { phase: 'starting_runtime', label: '启动本地环境' },
  { phase: 'opening_workbench', label: '打开 Code 工作台' },
]
const now = ref(Date.now())
let elapsedTimer: number | undefined
const activeStepIndex = computed(() => Math.max(
  0,
  steps.findIndex(step => step.phase === props.phase),
))
const elapsedSeconds = computed(() => Math.max(
  0,
  Math.floor((now.value - props.startedAt) / 1000),
))

function stepState(index: number): 'complete' | 'active' | 'pending' | 'failed' {
  if (props.error && index === activeStepIndex.value) return 'failed'
  if (index < activeStepIndex.value) return 'complete'
  if (index === activeStepIndex.value) return 'active'
  return 'pending'
}

function startElapsedTimer() {
  if (elapsedTimer != null) window.clearInterval(elapsedTimer)
  now.value = Date.now()
  elapsedTimer = window.setInterval(() => {
    now.value = Date.now()
  }, 1000)
}

watch(() => props.startedAt, startElapsedTimer)
onMounted(startElapsedTimer)
onBeforeUnmount(() => {
  if (elapsedTimer != null) window.clearInterval(elapsedTimer)
})
</script>

<style scoped>
.workspace-opening {
  position: relative;
  z-index: 3;
  width: min(520px, calc(100% - 40px));
  margin: auto;
  display: flex;
  flex-direction: column;
  gap: 24px;
  color: var(--text);
}

.workspace-opening-heading {
  display: flex;
  align-items: center;
  gap: 14px;
}

.workspace-opening-mark {
  width: 44px;
  height: 44px;
  flex: 0 0 44px;
  display: grid;
  place-items: center;
  border: 1px solid var(--brand-ring);
  border-radius: 8px;
  background: var(--brand-soft);
  color: var(--brand);
}

.workspace-opening-mark.failed {
  border-color: color-mix(in srgb, var(--err) 35%, var(--line));
  background: color-mix(in srgb, var(--err) 8%, var(--surface));
  color: var(--err);
}

.workspace-opening-heading h1,
.workspace-opening-heading p {
  margin: 0;
}

.workspace-opening-heading h1 {
  font-size: 18px;
  line-height: 26px;
  font-weight: var(--fw-semibold, 600);
  letter-spacing: 0;
}

.workspace-opening-heading p {
  margin-top: 3px;
  color: var(--text-3);
  font-size: 12px;
  line-height: 18px;
}

.workspace-opening-steps {
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  list-style: none;
}

.workspace-opening-steps li {
  position: relative;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 9px;
  color: var(--text-3);
  font-size: 12px;
  line-height: 18px;
  text-align: center;
}

.workspace-opening-steps li::before {
  content: '';
  position: absolute;
  top: 12px;
  right: 50%;
  width: 100%;
  height: 1px;
  background: var(--line);
  z-index: -1;
}

.workspace-opening-steps li:first-child::before {
  display: none;
}

.workspace-opening-steps li.complete,
.workspace-opening-steps li.active {
  color: var(--text);
}

.workspace-opening-steps li.failed {
  color: var(--err);
}

.workspace-opening-state {
  width: 24px;
  height: 24px;
  display: grid;
  place-items: center;
  border: 1px solid var(--line);
  border-radius: 50%;
  background: var(--surface);
}

.complete .workspace-opening-state {
  border-color: var(--ok, #16803c);
  color: var(--ok, #16803c);
}

.active .workspace-opening-state {
  border-color: var(--brand);
  color: var(--brand);
}

.failed .workspace-opening-state {
  border-color: var(--err);
  color: var(--err);
}

.workspace-opening-spinner {
  width: 10px;
  height: 10px;
  border: 2px solid color-mix(in srgb, var(--brand) 25%, transparent);
  border-top-color: var(--brand);
  border-radius: 50%;
  animation: workspace-opening-spin .8s linear infinite;
}

.workspace-opening-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--line-strong, var(--line));
}

.workspace-opening-details {
  border-top: 1px solid var(--line);
  padding-top: 12px;
  color: var(--text-3);
  font-size: 12px;
}

.workspace-opening-details summary {
  cursor: pointer;
}

.workspace-opening-details pre {
  margin: 10px 0 0;
  max-height: 140px;
  overflow: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  color: var(--text-2);
  font: 12px/1.5 var(--font-mono);
}

.workspace-opening-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.workspace-opening-actions button {
  min-height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 0 11px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  font: 500 12px/18px inherit;
  cursor: pointer;
}

.workspace-opening-actions button.primary {
  border-color: var(--brand);
  background: var(--brand);
  color: var(--text-inverse, #fff);
}

.workspace-opening-actions button:disabled {
  cursor: wait;
  opacity: .6;
}

.workspace-opening-back-icon {
  transform: rotate(180deg);
}

@keyframes workspace-opening-spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 560px) {
  .workspace-opening {
    gap: 20px;
  }

  .workspace-opening-steps li {
    font-size: 11px;
  }

  .workspace-opening-actions button {
    flex: 1 1 calc(50% - 4px);
  }
}

@media (prefers-reduced-motion: reduce) {
  .workspace-opening-spinner {
    animation: none;
  }
}
</style>
