<template>
  <aside v-if="visible" class="deploy-side" :class="{ open }">
    <div class="deploy-header">
      <div>
        <div class="deploy-title-row">
          <div class="deploy-title">{{ title }}</div>
          <span v-if="showLiveBadge" class="deploy-live-badge">执行中</span>
        </div>
        <div class="deploy-desc">{{ description }}</div>
        <div v-if="currentStepLabel" class="deploy-current-step">{{ currentStepLabel }}</div>
      </div>
      <div class="deploy-header-actions">
        <button
          v-if="canRetryAll"
          class="deploy-retry-all-btn"
          type="button"
          :disabled="retryAllDisabled"
          title="重置失败步骤并继续执行所有未完成步骤"
          @click="$emit('retry-all')"
        >
          <span class="deploy-retry-all-icon" aria-hidden="true">↻</span>
          一键重跑
        </button>
        <button v-if="showClose" class="deploy-close" aria-label="关闭部署面板" @click="$emit('close')">×</button>
      </div>
    </div>

    <div v-if="showUpdateProgress" class="deploy-progress">
      <div class="dp-track"><div class="dp-fill" :style="{ width: `${updateExecutionPercent}%` }"></div></div>
      <span class="dp-meta">{{ updateExecutionDoneCount }}/{{ updateExecutionTotalCount || 0 }}</span>
    </div>
    <div v-if="showDeployProgress" class="deploy-progress">
      <div class="dp-track"><div class="dp-fill" :style="{ width: `${deployPercent}%` }"></div></div>
      <span class="dp-meta">{{ deployDoneCount }}/{{ deploySteps.length || 0 }}</span>
    </div>

    <div v-if="showConflict" class="deploy-conflict-card">
      <div class="deploy-conflict-title">检测到编码冲突</div>
      <div class="deploy-conflict-copy">
        {{ activeConflict?.model_name }} 的编码 <code>{{ activeConflict?.current_code }}</code> 已存在，已切回左侧对话区等待你确认最新编码。
      </div>
    </div>
    <div v-if="showDeployError" class="deploy-conflict-card error-card">
      <div class="deploy-conflict-title">执行失败</div>
      <div class="deploy-conflict-copy">{{ deployLastError }}</div>
    </div>

    <div v-if="isUpdateExecutionMode" class="deploy-groups">
      <div v-for="group in updateExecutionGroups" :key="group.key" class="dg" :class="{ done: group.allDone, current: group.hasCurrent, err: group.hasError }">
        <div class="dg-hd">
          <span class="dg-icon"><AppIcon :name="group.icon" :size="14" /></span>
          <span class="dg-name">{{ group.title }}</span>
          <span class="dg-badge" :class="group.allDone ? 'done' : group.hasError ? 'err' : ''">{{ group.doneCount }}/{{ group.items.length }}</span>
        </div>
        <div v-for="item in group.items" :key="item.id" class="ds" :class="{ [item.status]: true, current: item.status === 'current' }">
          <div class="ds-dot" :class="item.status === 'current' ? 'pulse' : item.status">
            <span v-if="item.status === 'completed'"><AppIcon name="check" :size="12" /></span>
            <span v-else-if="item.status === 'error'">!</span>
          </div>
          <div class="ds-body">
            <div class="ds-name">{{ item.label }}</div>
            <div v-if="item.detail" class="ds-err">{{ item.detail }}</div>
          </div>
        </div>
      </div>
    </div>

    <div v-else-if="isUpdateReviewMode" class="deploy-groups update-review-groups">
      <div v-for="group in updateReviewGroups" :key="group.title" class="dg update">
        <div class="dg-hd">
          <span class="dg-icon"><AppIcon :name="group.icon" :size="14" /></span>
          <span class="dg-name">{{ group.title }}</span>
          <span class="dg-badge">{{ group.items.length }}</span>
        </div>
        <div v-for="item in group.items" :key="item.key" class="update-change-row">
          <div class="update-change-copy">
            <div class="update-change-title">{{ item.name }}</div>
            <div class="update-change-meta">{{ item.code }}</div>
          </div>
          <span class="change-badge mini" :class="item.badge.tone">{{ item.badge.label }}</span>
        </div>
      </div>
      <div v-if="updateReviewGroups.length === 0" class="doc-version-empty">本次更新未检测到可执行变更</div>
    </div>

    <div v-else-if="deployOpen && !isUpdateExecutionMode" class="deploy-groups">
      <div v-for="group in deployGroups" :key="group.title" class="dg" :class="{ done: group.allDone, err: group.hasError, current: group.steps.some((step: any) => step.key === deployExecuting) }">
        <div class="dg-hd">
          <span class="dg-icon"><AppIcon :name="group.icon" :size="14" /></span>
          <span class="dg-name">{{ group.title }}</span>
          <span class="dg-badge" :class="group.allDone ? 'done' : group.hasError ? 'err' : ''">{{ group.doneCount }}/{{ group.steps.length }}</span>
        </div>
        <div v-for="step in group.steps" :key="step.key" class="ds" :class="{ [step.status]: true, current: deployExecuting === step.key }">
          <div class="ds-dot" :class="deployExecuting === step.key ? 'pulse' : step.status">
            <span v-if="step.status === 'completed'"><AppIcon name="check" :size="12" /></span>
            <span v-else-if="step.status === 'error'">!</span>
          </div>
          <div class="ds-body">
            <div class="ds-name">{{ step.label }}</div>
            <div v-if="step.error" class="ds-err">{{ step.error }}</div>
          </div>
          <div class="ds-act">
            <span v-if="deployExecuting === step.key" class="ds-spin"></span>
            <button v-else-if="step.status === 'error'" class="ds-btn retry" @click="$emit('redo', step.key)">重试</button>
            <button v-else-if="step.status !== 'completed' && step.deps_met" class="ds-btn run" @click="$emit('exec', step.key)">执行</button>
            <span v-else-if="!step.deps_met && step.status !== 'completed'" class="ds-lock"><AppIcon name="lock" :size="12" /></span>
          </div>
        </div>
      </div>
      <div v-if="deployAllDone" class="deploy-done">
        部署已完成
        <button class="deploy-done-btn" @click="$emit('open-platform')">查看应用</button>
      </div>
    </div>

    <div v-if="executionLogs.length" class="deploy-log-card compact" :class="{ expanded: logExpanded }">
      <button class="deploy-log-header toggle" type="button" @click="$emit('update:logExpanded', !logExpanded)">
        <div class="deploy-log-title-wrap">
          <span>执行日志</span>
          <span class="deploy-log-count">{{ executionLogs.length }} 条</span>
        </div>
        <div class="deploy-log-summary">
          <span class="deploy-log-summary-text">{{ latestExecutionLog?.message || '暂无日志' }}</span>
          <span class="deploy-log-toggle">{{ logExpanded ? '收起' : '展开' }}</span>
        </div>
      </button>
      <div v-if="logExpanded" class="deploy-log-list">
        <div v-for="log in executionLogs" :key="log.id" class="deploy-log-item" :class="log.level">
          <div class="deploy-log-meta">
            <span class="deploy-log-level">{{ log.levelLabel }}</span>
            <span class="deploy-log-time">{{ log.time }}</span>
          </div>
          <div class="deploy-log-text">{{ log.message }}</div>
        </div>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import AppIcon from '@/components/common/AppIcon.vue'

const props = withDefaults(defineProps<{
  visible: boolean
  deployOpen: boolean
  isUpdateReviewMode: boolean
  isUpdateExecutionMode: boolean
  updateExecutionAllDone: boolean
  currentUpdateExecutionLabel: string
  currentDeployStep: any | null
  deployAllDone: boolean
  deployRunningAll: boolean
  deployExecuting: string | null
  deployLastError: string
  activeConflict: any | null
  canRetryAll: boolean
  updateExecutionPercent: number
  updateExecutionDoneCount: number
  updateExecutionTotalCount: number
  deployPercent: number
  deployDoneCount: number
  deploySteps: any[]
  updateExecutionGroups: any[]
  updateReviewGroups: any[]
  deployGroups: any[]
  executionLogs: any[]
  latestExecutionLog: any | null
  logExpanded: boolean
  diffSummary?: string
}>(), {
  diffSummary: '',
})

defineEmits<{
  (e: 'close'): void
  (e: 'retry-all'): void
  (e: 'redo', key: string): void
  (e: 'exec', key: string): void
  (e: 'open-platform'): void
  (e: 'update:logExpanded', value: boolean): void
}>()

const open = computed(() => props.deployOpen || props.isUpdateReviewMode || props.isUpdateExecutionMode)
const title = computed(() => props.isUpdateExecutionMode ? '更新进度' : props.isUpdateReviewMode ? '更新概览' : '创建过程')
const description = computed(() => {
  if (props.isUpdateExecutionMode) return props.updateExecutionAllDone ? '本次更新已执行完成' : '仅展示本次增量更新涉及的步骤'
  if (props.isUpdateReviewMode) return props.diffSummary || '本次仅展示与上一版设计文档对比出的更新项'
  if (props.deployAllDone) return '已完成全部创建步骤'
  if (props.deployRunningAll || props.deployExecuting) return '正在执行创建步骤'
  if (props.deployOpen) return '可手动执行未完成步骤，失败项可点击重试'
  return '创建过程会保留在这里，可手动执行或重试步骤'
})
const currentStepLabel = computed(() => props.isUpdateExecutionMode ? props.currentUpdateExecutionLabel : (props.currentDeployStep?.label || ''))
const showLiveBadge = computed(() => props.isUpdateExecutionMode || !!props.currentDeployStep)
const showClose = computed(() => !props.isUpdateReviewMode && !props.isUpdateExecutionMode)
const retryAllDisabled = computed(() => props.deployRunningAll || props.deployExecuting !== null)
const showUpdateProgress = computed(() => props.isUpdateExecutionMode)
const showDeployProgress = computed(() => props.deployOpen && !props.isUpdateReviewMode && !props.isUpdateExecutionMode)
const showConflict = computed(() => props.deployOpen && props.activeConflict && !props.isUpdateReviewMode && !props.isUpdateExecutionMode)
const showDeployError = computed(() => props.deployOpen && props.deployLastError && !props.isUpdateReviewMode && !props.isUpdateExecutionMode)
</script>

<style scoped>
.deploy-side {
  width: 0;
  min-width: 0;
  overflow: hidden;
  background: var(--t-bg-base);
  border-left: 1px solid var(--t-border-subtle);
  display: flex;
  flex-direction: column;
  transition: width 0.3s ease, min-width 0.3s ease;
}
.deploy-side.open {
  width: 340px;
  min-width: 340px;
}
@media (max-width: 1200px) {
  .deploy-side.open {
    position: absolute;
    right: 0;
    top: 0;
    bottom: 0;
    z-index: 20;
    width: 360px;
    min-width: 360px;
    box-shadow: -4px 0 24px rgba(0, 0, 0, 0.4);
  }
}
.deploy-header { display: flex; justify-content: space-between; align-items: center; padding: 16px 16px 8px; }
.deploy-title-row { display: flex; align-items: center; gap: 8px; }
.deploy-title { font-size: 14px; font-weight: 700; color: var(--t-text-primary); }
.deploy-desc { font-size: 11px; color: var(--t-text-muted); margin-top: 2px; }
.deploy-live-badge {
  display: inline-flex;
  align-items: center;
  height: 20px;
  padding: 0 8px;
  border-radius: 999px;
  background: rgba(92, 115, 255, 0.1);
  color: var(--t-brand-text);
  font-size: 10px;
  font-weight: 700;
  box-shadow: 0 0 0 1px rgba(92, 115, 255, 0.08);
}
.deploy-current-step { margin-top: 6px; font-size: 12px; font-weight: 600; color: var(--t-text-primary); }
.deploy-close { all: unset; cursor: pointer; color: var(--t-text-muted); font-size: 16px; padding: 4px; transition: color 0.2s; }
.deploy-close:hover { color: var(--t-text-secondary); }
.deploy-header-actions { display: flex; align-items: center; gap: 8px; }
.deploy-retry-all-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: var(--t-brand-soft, rgba(90, 120, 255, 0.12));
  color: var(--t-brand, #5a78ff);
  border: 1px solid var(--t-brand-border, rgba(90, 120, 255, 0.35));
  border-radius: 6px;
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}
.deploy-retry-all-btn:hover:not(:disabled) {
  background: var(--t-brand-soft-strong, rgba(90, 120, 255, 0.2));
  border-color: var(--t-brand, #5a78ff);
}
.deploy-retry-all-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.deploy-retry-all-icon { font-size: 13px; line-height: 1; }
.deploy-progress { padding: 0 16px 8px; display: flex; align-items: center; gap: 8px; }
.dp-track { flex: 1; height: 3px; background: var(--t-border-subtle); border-radius: 2px; overflow: hidden; }
.dp-fill { height: 100%; background: var(--t-brand-gradient); border-radius: 2px; transition: width 0.5s; }
.dp-meta { font-size: 10px; color: var(--t-text-muted); white-space: nowrap; }
.deploy-conflict-card {
  margin: 0 16px 12px;
  padding: 12px;
  border-radius: 12px;
  background: rgba(255, 248, 246, 0.96);
  border: 1px solid rgba(239, 68, 68, 0.16);
}
.deploy-conflict-title { font-size: 13px; font-weight: 700; color: #b45309; margin-bottom: 6px; }
.deploy-conflict-copy { font-size: 12px; color: var(--t-text-secondary); line-height: 1.6; }
.deploy-conflict-copy code {
  padding: 1px 6px;
  border-radius: 999px;
  background: rgba(239, 68, 68, 0.08);
  color: #b91c1c;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.deploy-groups { flex: 1; overflow-y: auto; padding: 0 12px 12px; }
.dg { background: var(--t-bg-elevated); border: 1px solid var(--t-border-subtle); border-radius: 12px; margin-bottom: 8px; overflow: hidden; }
.dg.done { border-color: rgba(16, 185, 129, 0.25); }
.dg.err { border-color: rgba(239, 68, 68, 0.25); }
.dg.current { border-color: rgba(92, 115, 255, 0.22); box-shadow: 0 10px 24px rgba(92, 115, 255, 0.08); }
.dg-hd { display: flex; align-items: center; gap: 6px; padding: 10px 14px; background: var(--t-bg-subtle); font-size: 12px; }
.dg.current .dg-hd,
.dg.update .dg-hd { background: linear-gradient(180deg, var(--t-brand-subtle), color-mix(in srgb, var(--t-brand) 5%, transparent)); }
.update-review-groups { padding-top: 4px; }
.dg-icon { font-size: 13px; }
.dg-name { font-weight: 600; color: var(--t-text-primary); flex: 1; }
.dg-badge { font-size: 9px; padding: 1px 6px; border-radius: 99px; font-weight: 600; background: var(--t-border-subtle); color: var(--t-text-muted); }
.dg-badge.done { background: rgba(16, 185, 129, 0.12); color: var(--t-success); }
.dg-badge.err { background: rgba(239, 68, 68, 0.12); color: var(--t-danger); }
.update-change-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 10px 14px; }
.update-change-row + .update-change-row { border-top: 1px solid var(--t-border-subtle); }
.update-change-copy { min-width: 0; flex: 1; }
.update-change-title { font-size: 12px; font-weight: 600; color: var(--t-text-primary); }
.update-change-meta { margin-top: 3px; font-size: 10px; color: var(--t-text-muted); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.change-badge.mini {
  display: inline-flex;
  align-items: center;
  height: 20px;
  padding: 0 7px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 700;
}
.change-badge.create { background: rgba(16, 185, 129, 0.12); color: var(--t-success); }
.change-badge.update { background: rgba(92, 115, 255, 0.12); color: var(--t-brand-text); }
.change-badge.delete,
.change-badge.disable { background: rgba(239, 68, 68, 0.12); color: var(--t-danger); }
.doc-version-empty {
  border: 1px dashed var(--t-border-subtle);
  border-radius: 12px;
  padding: 16px;
  text-align: center;
  color: var(--t-text-muted);
  font-size: 12px;
}
.ds { display: flex; align-items: center; padding: 7px 14px; gap: 10px; font-size: 12px; }
.ds + .ds { border-top: 1px solid var(--t-border-subtle); }
.ds:hover { background: var(--t-bg-subtle); }
.ds.current { background: linear-gradient(90deg, rgba(92, 115, 255, 0.08), rgba(92, 115, 255, 0.02)); }
.ds-dot { width: 18px; height: 18px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 9px; font-weight: 700; color: #fff; flex-shrink: 0; }
.ds-dot.completed { background: var(--t-success); }
.ds-dot.error { background: var(--t-danger); }
.ds-dot.pending { background: var(--t-border-strong); width: 7px; height: 7px; margin: 0 5.5px; }
.ds-dot.pulse { background: var(--t-brand); animation: dpulse 1.5s infinite; }
@keyframes dpulse {
  0%, 100% { box-shadow: 0 0 0 0 var(--t-brand-glow); }
  50% { box-shadow: 0 0 0 5px var(--t-brand-subtle); }
}
.ds-body { flex: 1; min-width: 0; }
.ds-name { color: var(--t-text-primary); }
.ds.current .ds-name { color: var(--t-brand-text); font-weight: 700; }
.ds.completed .ds-name,
.ds.pending .ds-name { color: var(--t-text-muted); }
.ds-err { font-size: 10px; color: var(--t-danger); margin-top: 1px; }
.ds-act { flex-shrink: 0; }
.ds-btn { border: none; cursor: pointer; border-radius: 6px; font-weight: 500; font-size: 11px; transition: transform 0.2s; }
.ds-btn.run { padding: 3px 10px; background: var(--t-brand-gradient); color: #fff; }
.ds-btn.run:hover:not(:disabled) { transform: translateY(-1px); }
.ds-btn.retry { padding: 3px 10px; background: var(--t-danger); color: #fff; }
.ds-btn:disabled { opacity: 0.35; cursor: not-allowed; }
.ds-lock { font-size: 11px; opacity: 0.15; }
.ds-spin { display: inline-block; width: 14px; height: 14px; border: 2px solid var(--t-border-subtle); border-top-color: var(--t-brand); border-radius: 50%; animation: spin 0.7s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.deploy-done {
  padding: 12px 16px;
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 8px;
  text-align: left;
  font-size: 13px;
  color: var(--t-success);
  font-weight: 500;
}
.deploy-done-btn {
  background: var(--t-brand-gradient);
  color: #fff;
  border: none;
  border-radius: 6px;
  padding: 5px 12px;
  font-size: 12px;
  cursor: pointer;
  margin-left: 8px;
  transition: transform 0.2s;
}
.deploy-done-btn:hover { transform: translateY(-1px); }
.deploy-log-card {
  margin: 0 12px 12px;
  padding: 10px 12px;
  border-radius: 18px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  background: rgba(255, 255, 255, 0.9);
}
.deploy-log-card.compact { margin-top: 8px; }
.deploy-log-card.expanded { padding-bottom: 12px; }
.deploy-log-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; color: var(--t-text-primary); font-size: 13px; font-weight: 700; }
.deploy-log-header.toggle { width: 100%; padding: 0; border: none; background: transparent; cursor: pointer; text-align: left; }
.deploy-log-title-wrap { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.deploy-log-summary { min-width: 0; display: flex; align-items: center; justify-content: flex-end; gap: 10px; flex: 1; }
.deploy-log-summary-text { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--t-text-secondary); font-size: 12px; font-weight: 500; }
.deploy-log-toggle { color: var(--t-brand-text); font-size: 12px; font-weight: 700; }
.deploy-log-count { color: var(--t-text-muted); font-size: 11px; font-weight: 600; }
.deploy-log-list { display: flex; flex-direction: column; gap: 6px; max-height: 180px; overflow-y: auto; margin-top: 10px; }
.deploy-log-item { padding: 8px 10px; border-radius: 12px; border: 1px solid rgba(148, 163, 184, 0.12); background: rgba(248, 250, 252, 0.96); }
.deploy-log-item.info { border-color: rgba(92, 115, 255, 0.14); background: rgba(244, 247, 255, 0.96); }
.deploy-log-item.success { border-color: rgba(34, 197, 94, 0.16); background: rgba(240, 253, 244, 0.96); }
.deploy-log-item.error { border-color: rgba(225, 90, 90, 0.18); background: rgba(255, 245, 245, 0.96); }
.deploy-log-meta { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 2px; }
.deploy-log-level { font-size: 10px; font-weight: 700; color: var(--t-text-secondary); }
.deploy-log-time { font-size: 10px; color: var(--t-text-muted); }
.deploy-log-text { white-space: pre-wrap; word-break: break-word; color: var(--t-text-primary); font-size: 11px; line-height: 1.45; }
:global(html[data-theme="dark"]) .deploy-log-card,
:global(html[data-theme="dark"]) .deploy-log-item,
:global(html[data-theme="dark"]) .deploy-log-item.info,
:global(html[data-theme="dark"]) .deploy-log-item.success,
:global(html[data-theme="dark"]) .deploy-log-item.error {
  background: rgba(14, 21, 38, 0.88);
  border-color: rgba(116, 139, 196, 0.18);
}
:global(html[data-theme="dark"]) .deploy-side {
  background: #0b1220;
  border-left-color: rgba(126, 149, 197, 0.18);
}
</style>
