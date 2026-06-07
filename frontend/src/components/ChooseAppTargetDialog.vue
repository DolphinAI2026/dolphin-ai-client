<template>
  <el-dialog
    v-model="visible"
    title="把设计文档送到 Builder"
    width="520px"
    :close-on-click-modal="false"
    class="choose-app-target-dialog"
  >
    <p class="choose-hint">
      文档：<strong>{{ filename }}</strong>
    </p>
    <p class="choose-hint" v-if="suggestedName">
      推断应用名：<strong>{{ suggestedName }}</strong>
    </p>
    <p class="choose-hint" v-if="suggestedCode">
      推断应用编码：<strong>{{ suggestedCode }}</strong>
    </p>

    <div v-if="loading" class="loading-row">正在查找匹配的现有应用...</div>

    <template v-else>
      <div class="section-label">在租户内找到 {{ candidates.length }} 个重复或相近的应用：</div>
      <div class="cand-list" v-if="candidates.length > 0">
        <div
          v-for="app in candidates"
          :key="app.id"
          class="cand-option"
          :class="{ selected: selected === app.id }"
          @click="selected = app.id"
        >
          <div class="cand-icon"><AppIcon name="package" :size="18" /></div>
          <div class="cand-detail">
            <div class="cand-name">
              {{ app.app_name }}
              <span v-for="reason in reasonLabels(app)" :key="reason" class="cand-tag">{{ reason }}</span>
            </div>
            <div class="cand-meta">
              <span>{{ app.app_code }}</span>
              <span class="dot">·</span>
              <span>{{ statusLabel(app.status) }}</span>
              <span v-if="app.updated_at" class="dot">·</span>
              <span v-if="app.updated_at">{{ formatTime(app.updated_at) }}</span>
            </div>
            <div v-if="app.name_will_change" class="cand-warning">
              编码相同；更新后现有应用名称会改为「{{ suggestedName }}」。
            </div>
          </div>
          <div v-if="selected === app.id" class="cand-check"><AppIcon name="check" :size="16" /></div>
        </div>
      </div>
      <div v-else class="no-cand">没有找到重复或相近的应用，将创建新应用。</div>
    </template>

    <template #footer>
      <el-button @click="onCancel">取消</el-button>
      <el-button
        v-if="candidates.length > 0"
        :disabled="!selected"
        @click="onConfirmUpdate"
      >更新到选中应用</el-button>
      <el-button type="primary" @click="onConfirmNew">{{ candidates.length > 0 ? '不更新，仍新建' : '新建应用' }}</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import AppIcon from '@/components/common/AppIcon.vue'

interface CandidateApp {
  id: number
  app_name: string
  app_code: string
  status: string
  apaas_app_id?: string | null
  updated_at?: string | null
  match_reasons?: string[]
  name_will_change?: boolean
}

const props = defineProps<{
  filename: string
  suggestedName: string
  suggestedCode: string
  candidates: CandidateApp[]
  loading: boolean
}>()

const visible = defineModel<boolean>({ default: false })

const emit = defineEmits<{
  (e: 'confirm', payload: { mode: 'new' } | { mode: 'update'; appId: number; appName: string }): void
  (e: 'cancel'): void
}>()

const selected = ref<number | null>(null)

watch(visible, (val) => {
  if (val) selected.value = null
})

function statusLabel(s: string): string {
  return ({
    draft: '草稿',
    generating: '生成中',
    updating: '更新中',
    completed: '已部署',
    failed: '失败',
  } as Record<string, string>)[s] || s
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso)
    const now = new Date()
    const diffMs = now.getTime() - d.getTime()
    const day = 24 * 3600_000
    if (diffMs < day) return '今天'
    if (diffMs < 2 * day) return '昨天'
    if (diffMs < 7 * day) return `${Math.floor(diffMs / day)} 天前`
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  } catch { return '' }
}

function reasonLabels(app: CandidateApp): string[] {
  const reasons = new Set(app.match_reasons || [])
  const labels: string[] = []
  if (reasons.has('code_exact')) labels.push('编码相同')
  if (reasons.has('name_exact')) labels.push('名称相同')
  if (reasons.has('name_similar')) labels.push('名称相近')
  return labels
}

function onCancel() {
  visible.value = false
  emit('cancel')
}

function onConfirmNew() {
  visible.value = false
  emit('confirm', { mode: 'new' })
}

function onConfirmUpdate() {
  if (!selected.value) return
  const app = props.candidates.find(a => a.id === selected.value)
  if (!app) return
  visible.value = false
  emit('confirm', { mode: 'update', appId: app.id, appName: app.app_name })
}
</script>

<style scoped>
.choose-hint {
  color: var(--t-text-secondary);
  font-size: 13px;
  margin: 0 0 8px;
}
.section-label {
  color: var(--t-text-muted);
  font-size: 12px;
  margin: 12px 0 8px;
}
.loading-row {
  color: var(--t-text-muted);
  font-size: 13px;
  padding: 24px 0;
  text-align: center;
}
.cand-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 320px;
  overflow-y: auto;
}
.cand-option {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  background: var(--t-bg-input);
  border: 1px solid var(--t-border-subtle);
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.15s;
}
.cand-option:hover {
  background: var(--t-bg-panel-hover);
  border-color: var(--t-brand-glow);
}
.cand-option.selected {
  border-color: var(--t-brand);
  background: var(--t-brand-subtle);
}
.cand-icon {
  font-size: 18px;
  flex-shrink: 0;
}
.cand-detail {
  flex: 1;
  min-width: 0;
}
.cand-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--t-text-primary);
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.cand-tag {
  display: inline-flex;
  align-items: center;
  height: 18px;
  padding: 0 6px;
  border-radius: 4px;
  background: rgba(37, 99, 235, 0.12);
  color: var(--t-brand);
  font-size: 11px;
  font-weight: 600;
  line-height: 18px;
}
.cand-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--t-text-muted);
  margin-top: 2px;
}
.cand-warning {
  color: #b45309;
  font-size: 12px;
  line-height: 1.45;
  margin-top: 6px;
}
.dot { opacity: 0.5; }
.cand-check {
  color: var(--t-brand);
  font-size: 16px;
  font-weight: 700;
  flex-shrink: 0;
}
.no-cand {
  color: var(--t-text-muted);
  font-size: 13px;
  padding: 16px 0;
  text-align: center;
}
.cand-list::-webkit-scrollbar { width: 5px; }
.cand-list::-webkit-scrollbar-track { background: transparent; }
.cand-list::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.08); border-radius: 3px; }
</style>

<style>
.el-dialog.choose-app-target-dialog {
  background: var(--t-bg-panel) !important;
  color: var(--t-text-primary);
  border: 1px solid var(--t-border-subtle);
  border-radius: 16px;
}
.el-dialog.choose-app-target-dialog .el-dialog__header {
  border-bottom: 1px solid var(--t-border-subtle);
  padding: 16px 20px;
}
.el-dialog.choose-app-target-dialog .el-dialog__title {
  color: var(--t-text-primary) !important;
  font-size: 15px;
  font-weight: 600;
}
.el-dialog.choose-app-target-dialog .el-dialog__headerbtn .el-dialog__close {
  color: var(--t-text-muted);
}
.el-dialog.choose-app-target-dialog .el-dialog__body {
  padding: 16px 20px 4px;
}
.el-dialog.choose-app-target-dialog .el-dialog__footer {
  border-top: 1px solid var(--t-border-subtle);
  padding: 14px 20px;
}
</style>
