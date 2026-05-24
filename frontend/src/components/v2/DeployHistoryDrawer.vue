<template>
  <Teleport to="body">
    <transition name="dh-fade">
      <div
        v-if="open"
        class="dh-overlay"
        @click.self="closeDrawer"
      >
        <transition name="dh-slide">
          <aside v-if="open" class="dh-drawer" role="dialog" :aria-label="title">
            <header class="dh-header">
              <div class="dh-title-block">
                <h2 class="dh-title">{{ title }}</h2>
                <p v-if="appName" class="dh-subtitle">{{ appName }}</p>
              </div>
              <button class="dh-close" type="button" @click="closeDrawer" aria-label="关闭">×</button>
            </header>

            <div class="dh-toolbar">
              <button
                class="dh-btn dh-btn-ghost"
                type="button"
                :disabled="loading"
                @click="loadRecords(true)"
              >
                {{ loading ? '刷新中…' : '刷新' }}
              </button>
              <span class="dh-count">共 {{ total }} 条</span>
            </div>

            <div class="dh-body">
              <div v-if="loading && records.length === 0" class="dh-empty">
                <div class="dh-spinner"></div>
                <span>加载中…</span>
              </div>
              <div v-else-if="!loading && records.length === 0" class="dh-empty">
                <div class="dh-empty-icon">📜</div>
                <p>尚无部署记录</p>
                <span class="dh-empty-hint">第一次部署后这里会出现历史版本</span>
              </div>

              <ul v-else class="dh-list">
                <li
                  v-for="rec in records"
                  :key="rec.id"
                  class="dh-item"
                  :class="['dh-item-' + rec.status, { expanded: expandedId === rec.id }]"
                >
                  <div class="dh-item-head" @click="toggleExpand(rec.id)">
                    <div class="dh-item-left">
                      <div class="dh-item-row">
                        <span class="dh-status-badge" :class="'dh-status-' + rec.status">
                          {{ statusLabel(rec.status) }}
                        </span>
                        <span class="dh-type-badge" :class="'dh-type-' + rec.deploy_type">
                          {{ typeLabel(rec.deploy_type) }}
                        </span>
                        <span v-if="rec.version_label" class="dh-version">
                          {{ rec.version_label }}
                        </span>
                      </div>
                      <div class="dh-item-meta">
                        <span class="dh-time">{{ formatTime(rec.created_at) }}</span>
                        <span v-if="rec.snapshot_version" class="dh-snap">
                          SPEC v{{ rec.snapshot_version }}
                        </span>
                        <span v-if="rec.apaas_app_id_after" class="dh-aid">
                          aPaaS#{{ rec.apaas_app_id_after }}
                        </span>
                      </div>
                      <div v-if="rec.snapshot_summary" class="dh-summary">
                        {{ rec.snapshot_summary }}
                      </div>
                    </div>
                    <div class="dh-item-right">
                      <button
                        v-if="canRollback(rec)"
                        class="dh-btn dh-btn-primary dh-btn-sm"
                        type="button"
                        :disabled="rollingBack"
                        @click.stop="confirmRollback(rec)"
                      >
                        回滚到这版
                      </button>
                      <span class="dh-chevron" :class="{ rotated: expandedId === rec.id }">▾</span>
                    </div>
                  </div>

                  <div v-if="expandedId === rec.id" class="dh-item-detail">
                    <div v-if="loadingDetailId === rec.id" class="dh-detail-loading">加载详情…</div>
                    <template v-else>
                      <div v-if="rec.error_message" class="dh-error-block">
                        <div class="dh-error-title">错误信息</div>
                        <pre class="dh-error-text">{{ rec.error_message }}</pre>
                      </div>
                      <div v-if="detailMap[rec.id]?.event_log?.length" class="dh-events-block">
                        <div class="dh-events-title">部署事件（{{ detailMap[rec.id].event_log.length }} 条）</div>
                        <div class="dh-events-list">
                          <div
                            v-for="(evt, idx) in detailMap[rec.id].event_log.slice(0, 20)"
                            :key="idx"
                            class="dh-event-row"
                          >
                            <span class="dh-event-type">{{ evt.type || evt.stage || 'event' }}</span>
                            <span class="dh-event-msg">{{ summarizeEvent(evt) }}</span>
                          </div>
                          <div
                            v-if="detailMap[rec.id].event_log.length > 20"
                            class="dh-event-more"
                          >
                            …还有 {{ detailMap[rec.id].event_log.length - 20 }} 条未展示
                          </div>
                        </div>
                      </div>
                      <div v-if="detailMap[rec.id]?.snapshot_content" class="dh-snap-block">
                        <div class="dh-snap-title">
                          SPEC 快照
                          <span class="dh-snap-hint">{{ formatBytes(rec.snapshot_size) }}</span>
                        </div>
                        <pre class="dh-snap-preview">{{ snapPreview(detailMap[rec.id].snapshot_content) }}</pre>
                      </div>
                      <div v-if="!rec.error_message && !detailMap[rec.id]?.event_log?.length && !detailMap[rec.id]?.snapshot_content" class="dh-empty-detail">
                        本条记录无附加详情
                      </div>
                    </template>
                  </div>
                </li>
              </ul>

              <div v-if="hasMore" class="dh-load-more">
                <button class="dh-btn dh-btn-ghost" type="button" :disabled="loading" @click="loadMore">
                  {{ loading ? '加载中…' : '加载更多' }}
                </button>
              </div>
            </div>
          </aside>
        </transition>
      </div>
    </transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, watch, computed, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { applicationApi } from '@/api/application'

type Status = 'in_progress' | 'success' | 'failed' | 'rolled_back'
type DeployType = 'deploy' | 'publish' | 'rollback'

interface DeployRecord {
  id: number
  app_id: number
  user_id: number
  version_label: string | null
  status: Status
  deploy_type: DeployType
  snapshot_artifact_id: number | null
  snapshot_version: number | null
  snapshot_summary: string | null
  snapshot_size: number | null
  apaas_app_id_before: string | null
  apaas_app_id_after: string | null
  error_message: string | null
  created_at: string | null
  completed_at: string | null
}

interface Props {
  applicationId: number
  open: boolean
  appName?: string
  title?: string
}

const props = withDefaults(defineProps<Props>(), {
  appName: '',
  title: '部署历史',
})

const emit = defineEmits<{
  'update:open': [v: boolean]
  'rolled-back': [recordId: number]
}>()

const records = ref<DeployRecord[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const rollingBack = ref(false)
const expandedId = ref<number | null>(null)
const loadingDetailId = ref<number | null>(null)
const detailMap = reactive<Record<number, any>>({})

const hasMore = computed(() => records.value.length < total.value)

function closeDrawer() {
  emit('update:open', false)
}

async function loadRecords(reset = false) {
  if (reset) {
    records.value = []
    total.value = 0
    page.value = 1
    expandedId.value = null
    Object.keys(detailMap).forEach(k => delete detailMap[Number(k)])
  }
  loading.value = true
  try {
    const res = await applicationApi.listDeployRecords(props.applicationId, {
      page: page.value,
      page_size: pageSize,
    })
    total.value = res.total
    if (page.value === 1) {
      records.value = res.items as DeployRecord[]
    } else {
      records.value.push(...(res.items as DeployRecord[]))
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '加载部署历史失败')
  } finally {
    loading.value = false
  }
}

async function loadMore() {
  page.value += 1
  await loadRecords(false)
}

async function loadDetail(rec: DeployRecord) {
  if (detailMap[rec.id]) return
  loadingDetailId.value = rec.id
  try {
    const detail = await applicationApi.getDeployRecord(props.applicationId, rec.id)
    detailMap[rec.id] = detail
  } catch (e: any) {
    ElMessage.error(e?.message || '加载部署详情失败')
  } finally {
    loadingDetailId.value = null
  }
}

function toggleExpand(id: number) {
  if (expandedId.value === id) {
    expandedId.value = null
  } else {
    expandedId.value = id
    const rec = records.value.find(r => r.id === id)
    if (rec) loadDetail(rec)
  }
}

function canRollback(rec: DeployRecord): boolean {
  // 只允许回滚到有 SPEC 快照、且成功完成过的非 rollback 记录
  if (!rec.snapshot_artifact_id) return false
  if (rec.deploy_type === 'rollback') return false
  if (rec.status === 'in_progress') return false
  return true
}

async function confirmRollback(rec: DeployRecord) {
  try {
    await ElMessageBox.confirm(
      `确定要把应用 SPEC 回滚到 ${rec.version_label || `record#${rec.id}`}（SPEC v${rec.snapshot_version}）吗？\n回滚后 SPEC 会被覆盖，需要重新点击"部署"才能推送到 aPaaS 平台。`,
      '确认回滚',
      {
        confirmButtonText: '回滚',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
  } catch {
    return  // 用户取消
  }
  rollingBack.value = true
  try {
    const res = await applicationApi.rollbackApplication(props.applicationId, rec.id)
    ElMessage.success(res.message || '回滚成功')
    emit('rolled-back', res.record_id)
    await loadRecords(true)
  } catch (e: any) {
    const detail = e?.response?.data?.detail || e?.message || '回滚失败'
    ElMessage.error(detail)
  } finally {
    rollingBack.value = false
  }
}

function statusLabel(s: Status): string {
  return {
    in_progress: '进行中',
    success: '成功',
    failed: '失败',
    rolled_back: '已回滚',
  }[s] || s
}

function typeLabel(t: DeployType): string {
  return {
    deploy: '部署',
    publish: '上线',
    rollback: '回滚',
  }[t] || t
}

function formatTime(iso: string | null): string {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    const pad = (n: number) => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
  } catch {
    return iso
  }
}

function formatBytes(n: number | null): string {
  if (!n) return ''
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(2)} MB`
}

function summarizeEvent(evt: any): string {
  if (!evt || typeof evt !== 'object') return String(evt)
  return evt.step || evt.message || evt.error || evt.status || JSON.stringify(evt).slice(0, 120)
}

function snapPreview(content: string): string {
  if (!content) return ''
  if (content.length > 2000) return content.slice(0, 2000) + '\n…（已截断）'
  return content
}

watch(() => props.open, (v) => {
  if (v) loadRecords(true)
})
</script>

<style scoped lang="less">
.dh-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  z-index: 2000;
  display: flex;
  justify-content: flex-end;
}

.dh-drawer {
  width: 480px;
  max-width: 100vw;
  height: 100vh;
  background: var(--t-bg-panel, #fff);
  color: var(--t-text-primary, #1a1a1a);
  display: flex;
  flex-direction: column;
  box-shadow: -16px 0 40px rgba(0, 0, 0, 0.18);
}

.dh-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 18px 20px 14px;
  border-bottom: 1px solid var(--t-border-subtle, #e5e7eb);
}

.dh-title-block {
  flex: 1;
}

.dh-title {
  margin: 0;
  font-size: 17px;
  font-weight: 600;
}

.dh-subtitle {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--t-text-muted, #6b7280);
}

.dh-close {
  background: transparent;
  border: none;
  font-size: 24px;
  line-height: 1;
  cursor: pointer;
  color: var(--t-text-muted, #6b7280);
  padding: 0 4px;

  &:hover {
    color: var(--t-text-primary, #1a1a1a);
  }
}

.dh-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 20px;
  border-bottom: 1px solid var(--t-border-subtle, #e5e7eb);
}

.dh-count {
  font-size: 12px;
  color: var(--t-text-muted, #6b7280);
}

.dh-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px 20px 24px;
}

.dh-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 60px 12px;
  color: var(--t-text-muted, #6b7280);
  font-size: 13px;
}

.dh-empty-icon {
  font-size: 36px;
  opacity: 0.4;
}

.dh-empty-hint {
  font-size: 11px;
  opacity: 0.7;
}

.dh-spinner {
  width: 28px;
  height: 28px;
  border: 2px solid rgba(99, 102, 241, 0.2);
  border-top-color: #6366f1;
  border-radius: 50%;
  animation: dh-spin 0.8s linear infinite;
}

@keyframes dh-spin {
  to { transform: rotate(360deg); }
}

.dh-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.dh-item {
  background: var(--t-bg-subtle, #f8fafc);
  border: 1px solid var(--t-border-subtle, #e5e7eb);
  border-radius: 10px;
  overflow: hidden;
  transition: border-color 0.15s;

  &:hover {
    border-color: var(--t-border-strong, #cbd5e1);
  }

  &.dh-item-success {
    border-left: 3px solid #10b981;
  }
  &.dh-item-failed {
    border-left: 3px solid #ef4444;
  }
  &.dh-item-in_progress {
    border-left: 3px solid #6366f1;
  }
  &.dh-item-rolled_back {
    border-left: 3px solid #f59e0b;
  }
}

.dh-item-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 12px 14px;
  cursor: pointer;
  gap: 12px;
}

.dh-item-left {
  flex: 1;
  min-width: 0;
}

.dh-item-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}

.dh-status-badge,
.dh-type-badge {
  font-size: 11px;
  padding: 2px 7px;
  border-radius: 4px;
  font-weight: 500;
}

.dh-status-success { background: rgba(16, 185, 129, 0.12); color: #059669; }
.dh-status-failed { background: rgba(239, 68, 68, 0.12); color: #dc2626; }
.dh-status-in_progress { background: rgba(99, 102, 241, 0.12); color: #4f46e5; }
.dh-status-rolled_back { background: rgba(245, 158, 11, 0.12); color: #d97706; }

.dh-type-deploy { background: rgba(59, 130, 246, 0.12); color: #2563eb; }
.dh-type-publish { background: rgba(139, 92, 246, 0.12); color: #7c3aed; }
.dh-type-rollback { background: rgba(245, 158, 11, 0.12); color: #d97706; }

.dh-version {
  font-size: 12px;
  font-weight: 500;
  color: var(--t-text-primary, #1a1a1a);
}

.dh-item-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 11px;
  color: var(--t-text-muted, #6b7280);
  flex-wrap: wrap;
}

.dh-snap,
.dh-aid {
  font-family: ui-monospace, SFMono-Regular, monospace;
  font-size: 10px;
  background: rgba(0, 0, 0, 0.04);
  padding: 1px 6px;
  border-radius: 3px;
}

.dh-summary {
  margin-top: 6px;
  font-size: 12px;
  color: var(--t-text-secondary, #4b5563);
  line-height: 1.5;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.dh-item-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.dh-chevron {
  font-size: 14px;
  color: var(--t-text-muted, #6b7280);
  transition: transform 0.2s;

  &.rotated {
    transform: rotate(180deg);
  }
}

.dh-btn {
  border: none;
  font-size: 12px;
  padding: 5px 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
  font-weight: 500;

  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
}

.dh-btn-sm {
  padding: 4px 10px;
  font-size: 11px;
}

.dh-btn-primary {
  background: #6366f1;
  color: #fff;

  &:hover:not(:disabled) { background: #4f46e5; }
}

.dh-btn-ghost {
  background: var(--t-bg-panel, #fff);
  border: 1px solid var(--t-border-subtle, #e5e7eb);
  color: var(--t-text-secondary, #4b5563);

  &:hover:not(:disabled) {
    border-color: var(--t-border-strong, #cbd5e1);
    color: var(--t-text-primary, #1a1a1a);
  }
}

.dh-item-detail {
  border-top: 1px solid var(--t-border-subtle, #e5e7eb);
  padding: 12px 14px;
  background: var(--t-bg-panel, #fff);
  font-size: 12px;
}

.dh-detail-loading {
  color: var(--t-text-muted, #6b7280);
  text-align: center;
  padding: 12px;
}

.dh-error-block,
.dh-events-block,
.dh-snap-block {
  margin-bottom: 12px;
  &:last-child { margin-bottom: 0; }
}

.dh-error-title,
.dh-events-title,
.dh-snap-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--t-text-muted, #6b7280);
  text-transform: uppercase;
  letter-spacing: 0.4px;
  margin-bottom: 6px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.dh-snap-hint {
  font-weight: 400;
  text-transform: none;
  letter-spacing: 0;
  font-size: 10px;
}

.dh-error-text,
.dh-snap-preview {
  margin: 0;
  padding: 8px 10px;
  background: rgba(0, 0, 0, 0.03);
  border-radius: 6px;
  font-family: ui-monospace, SFMono-Regular, monospace;
  font-size: 11px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 200px;
  overflow-y: auto;
}

.dh-error-text {
  color: #dc2626;
  background: rgba(239, 68, 68, 0.06);
}

.dh-events-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.dh-event-row {
  display: flex;
  gap: 8px;
  align-items: baseline;
  font-size: 11px;
  padding: 3px 0;
}

.dh-event-type {
  font-family: ui-monospace, SFMono-Regular, monospace;
  font-weight: 600;
  color: #6366f1;
  flex-shrink: 0;
  min-width: 60px;
}

.dh-event-msg {
  color: var(--t-text-secondary, #4b5563);
  overflow: hidden;
  text-overflow: ellipsis;
}

.dh-event-more {
  font-size: 10px;
  color: var(--t-text-muted, #6b7280);
  font-style: italic;
  padding-top: 4px;
}

.dh-empty-detail {
  text-align: center;
  color: var(--t-text-muted, #6b7280);
  padding: 8px;
  font-style: italic;
}

.dh-load-more {
  display: flex;
  justify-content: center;
  padding: 16px 0 0;
}

// Transitions
.dh-fade-enter-active,
.dh-fade-leave-active {
  transition: opacity 0.18s;
}
.dh-fade-enter-from,
.dh-fade-leave-to {
  opacity: 0;
}

.dh-slide-enter-active,
.dh-slide-leave-active {
  transition: transform 0.22s cubic-bezier(0.16, 1, 0.3, 1);
}
.dh-slide-enter-from,
.dh-slide-leave-to {
  transform: translateX(100%);
}
</style>
