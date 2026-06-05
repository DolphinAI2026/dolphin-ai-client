<!-- LogsPanel.vue — 应用日志 (design-v4 K4).

  替 ChatPage.vue 顶部 5 tab 中 "日志" tab 的 placeholder.
  4 sub-tab: 部署历史 / 操作日志 / AI 行为 / 错误日志.
  数据源: GET /api/applications/{id}/logs/{kind} (kind: deploy / operation / ai / error).
-->
<template>
  <section class="lp" aria-label="应用日志">
    <header class="lp-head">
      <div class="lp-head-meta">
        <h1 class="lp-title">应用日志</h1>
        <p class="lp-stats">
          <span>{{ totalCount }} 条</span>
          <span v-if="errorCount > 0" class="lp-stat-sep">·</span>
          <span v-if="errorCount > 0" class="lp-stat-err">{{ errorCount }} 错误</span>
        </p>
      </div>
      <div class="lp-head-actions">
        <button class="lp-btn lp-btn-ghost" :disabled="loading" @click="() => reload()">
          <span class="lp-btn-icon">⟲</span> 刷新
        </button>
        <label class="lp-toggle">
          <input v-model="autoRefresh" type="checkbox" />
          自动刷新 (5s)
        </label>
      </div>
    </header>

    <div class="lp-subnav" role="tablist">
      <button
        v-for="sub in SUB_TABS"
        :key="sub.code"
        class="lp-subnav-tab"
        :class="{ active: kind === sub.code }"
        role="tab"
        :aria-selected="kind === sub.code"
        @click="switchKind(sub.code)"
      >
        {{ sub.label }}
        <span v-if="sub.code === 'error' && errorCount > 0" class="lp-tab-badge">{{ errorCount }}</span>
      </button>
    </div>

    <div v-if="loading" class="lp-state">
      <div class="lp-spinner" /> 加载中…
    </div>
    <div v-else-if="error" class="lp-state lp-state-err">
      ⚠️ {{ error }}
      <button class="lp-btn lp-btn-ghost" @click="() => reload()">重试</button>
    </div>
    <div v-else-if="items.length === 0" class="lp-state">
      <div class="lp-state-icon">📋</div>
      <p>暂无{{ currentSubLabel }}记录</p>
      <p class="hint">用配置助手或部署应用触发动作后会有日志</p>
    </div>
    <template v-else>
      <div class="lp-table-wrap">
        <table class="lp-table">
          <thead>
            <tr>
              <th class="col-time">时间</th>
              <th class="col-type">类型</th>
              <th class="col-user">用户</th>
              <th class="col-summary">详情</th>
              <th class="col-status">状态</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(it, i) in items"
              :key="(it.id || i) + '-' + it.timestamp"
              class="lp-row"
              @click="openDetails(it)"
            >
              <td class="col-time mono">{{ formatRelative(it.timestamp) }}</td>
              <td class="col-type">
                <span class="lp-type-chip">{{ it.type || '—' }}</span>
              </td>
              <td class="col-user">{{ it.user || '系统' }}</td>
              <td class="col-summary">{{ it.summary || '—' }}</td>
              <td class="col-status">
                <span
                  class="lp-status-chip"
                  :class="`lp-status-${normalizeStatus(it.status)}`"
                >{{ statusLabel(it.status) }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="hasMore" class="lp-footer">
        <button class="lp-btn lp-btn-ghost" @click="loadMore">加载更多</button>
      </div>
    </template>

    <!-- Details modal -->
    <teleport to="body">
      <div v-if="detailItem" class="lp-modal-backdrop" @click.self="detailItem = null">
        <div class="lp-modal">
          <div class="lp-modal-head">
            <h3>{{ detailItem.type }} 详情</h3>
            <button class="lp-modal-close" @click="detailItem = null">×</button>
          </div>
          <div class="lp-modal-body">
            <div class="lp-modal-row"><label>时间</label><div>{{ detailItem.timestamp }}</div></div>
            <div class="lp-modal-row"><label>用户</label><div>{{ detailItem.user || '系统' }}</div></div>
            <div class="lp-modal-row"><label>类型</label><div>{{ detailItem.type }}</div></div>
            <div class="lp-modal-row"><label>状态</label><div>{{ statusLabel(detailItem.status) }}</div></div>
            <div class="lp-modal-row"><label>摘要</label><div>{{ detailItem.summary }}</div></div>
            <div v-if="detailItem.details" class="lp-modal-row lp-modal-row-full">
              <label>详情</label>
              <pre class="lp-modal-pre">{{ JSON.stringify(detailItem.details, null, 2) }}</pre>
            </div>
          </div>
        </div>
      </div>
    </teleport>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import request from '@/utils/request'

interface LogItem {
  id?: string
  timestamp: string
  type: string
  user?: string
  summary: string
  status: string
  details?: any
}

const props = defineProps<{
  appId: number
}>()

const SUB_TABS = [
  { code: 'deploy', label: '部署历史' },
  { code: 'operation', label: '操作日志' },
  { code: 'ai', label: 'AI 行为' },
  { code: 'error', label: '错误日志' },
]

const kind = ref<string>('deploy')
const items = ref<LogItem[]>([])
const totalCount = ref(0)
const errorCount = ref(0)
const hasMore = ref(false)
const page = ref(1)
const loading = ref(false)
const error = ref('')
const autoRefresh = ref(false)
const detailItem = ref<LogItem | null>(null)
let refreshTimer: number | null = null

const currentSubLabel = computed(() => SUB_TABS.find(s => s.code === kind.value)?.label || '')

async function reload(append = false) {
  if (!props.appId) return
  loading.value = true
  error.value = ''
  try {
    const resp = await request.get<any, any>(
      `/applications/${props.appId}/logs/${kind.value}?page=${page.value}&page_size=50`,
    )
    if (resp?.ok) {
      const newItems = (resp.items || []) as LogItem[]
      items.value = append ? [...items.value, ...newItems] : newItems
      totalCount.value = resp.total || newItems.length
      errorCount.value = resp.error_count || 0
      hasMore.value = !!resp.has_more
    } else {
      error.value = resp?.message || resp?.error_code || '加载失败'
    }
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '网络错误'
  } finally {
    loading.value = false
  }
}

function switchKind(k: string) {
  if (kind.value === k) return
  kind.value = k
  page.value = 1
  reload()
}

function loadMore() {
  page.value += 1
  reload(true)
}

function openDetails(it: LogItem) {
  detailItem.value = it
}

function normalizeStatus(s?: string): string {
  const lo = (s || '').toLowerCase()
  if (lo.includes('success') || lo === 'completed' || lo === 'ok') return 'ok'
  if (lo.includes('fail') || lo === 'error' || lo === 'failed') return 'err'
  if (lo.includes('progress') || lo === 'pending' || lo === 'running') return 'pending'
  return 'neutral'
}

function statusLabel(s?: string): string {
  const n = normalizeStatus(s)
  if (n === 'ok') return '成功'
  if (n === 'err') return '失败'
  if (n === 'pending') return '进行中'
  return s || '—'
}

function formatRelative(ts: string): string {
  if (!ts) return '—'
  try {
    const t = new Date(ts).getTime()
    const diff = Date.now() - t
    if (diff < 60_000) return '刚刚'
    if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
    if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`
    if (diff < 604_800_000) return `${Math.floor(diff / 86_400_000)} 天前`
    return new Date(ts).toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch {
    return ts
  }
}

watch(() => props.appId, () => { page.value = 1; reload() }, { immediate: true })
watch(autoRefresh, (on) => {
  if (on) {
    refreshTimer = window.setInterval(() => reload(), 5000)
  } else if (refreshTimer !== null) {
    window.clearInterval(refreshTimer)
    refreshTimer = null
  }
})
onBeforeUnmount(() => {
  if (refreshTimer !== null) window.clearInterval(refreshTimer)
})
</script>

<style scoped>
.lp {
  font-family: var(--font-sans);
  color: var(--text);
  background: var(--bg);
  height: 100%;
  display: flex;
  flex-direction: column;
  font-feature-settings: 'cv11', 'ss01';
  overflow: hidden;
}

.lp-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 20px 32px;
  border-bottom: 1px solid var(--line);
  background: var(--surface);
}
.lp-title {
  margin: 0 0 4px;
  font-size: 22px;
  font-weight: 600;
  color: var(--text);
}
.lp-stats {
  margin: 0;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  color: var(--text-3);
}
.lp-stat-sep { color: var(--text-4); }
.lp-stat-err { color: var(--err); font-weight: 500; }
.lp-head-actions { display: flex; gap: 8px; align-items: center; }
.lp-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  color: var(--text-2);
  cursor: pointer;
}

.lp-subnav {
  display: flex;
  gap: 4px;
  padding: 0 32px;
  border-bottom: 1px solid var(--line);
  background: var(--surface);
}
.lp-subnav-tab {
  position: relative;
  padding: 11px 14px;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-3);
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
  transition: color 0.12s, border-color 0.12s;
}
.lp-subnav-tab:hover { color: var(--text-2); }
.lp-subnav-tab.active {
  color: var(--brand);
  border-bottom-color: var(--brand);
  font-weight: 600;
}
.lp-tab-badge {
  display: inline-block;
  margin-left: 4px;
  padding: 0 6px;
  font-size: 11px;
  background: var(--err);
  color: #fff;
  border-radius: 999px;
}

.lp-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--text-3);
  font-size: 13px;
  padding: 48px 16px;
}
.lp-state-icon { font-size: 36px; opacity: 0.6; }
.lp-state .hint { font-size: 12px; color: var(--text-4); }
.lp-state-err { color: var(--err); }
.lp-spinner {
  width: 18px; height: 18px;
  border: 2px solid var(--line-strong);
  border-top-color: var(--brand);
  border-radius: 50%;
  animation: lp-spin 0.9s linear infinite;
}
@keyframes lp-spin { to { transform: rotate(360deg); } }

.lp-table-wrap {
  flex: 1;
  overflow: auto;
  padding: 16px 32px;
}
.lp-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
}
.lp-table th {
  text-align: left;
  padding: 11px 14px;
  background: var(--surface-2);
  font-weight: 500;
  color: var(--text-3);
  font-size: 12px;
  border-bottom: 1px solid var(--line);
  position: sticky;
  top: 0;
}
.lp-table td {
  padding: 11px 14px;
  border-bottom: 1px solid var(--line);
}
.lp-row { cursor: pointer; }
.lp-row:hover td { background: var(--surface-2); }
.col-time { width: 110px; color: var(--text-3); }
.col-type { width: 100px; }
.col-user { width: 100px; color: var(--text-2); }
.col-status { width: 80px; text-align: center; }
.mono { font-family: var(--font-mono); font-size: 12px; }

.lp-type-chip {
  display: inline-block;
  padding: 1.5px 8px;
  border-radius: 4px;
  background: var(--brand-soft);
  color: var(--brand);
  font-size: 11.5px;
  font-weight: 500;
}
.lp-status-chip {
  display: inline-block;
  padding: 1.5px 10px;
  border-radius: 999px;
  font-size: 11.5px;
  font-weight: 500;
}
.lp-status-ok { background: var(--ok-soft); color: var(--ok); }
.lp-status-err { background: var(--err-soft); color: var(--err); }
.lp-status-pending { background: var(--brand-soft); color: var(--brand); }
.lp-status-neutral { background: var(--surface-2); color: var(--text-3); }

.lp-btn {
  height: 30px;
  padding: 0 14px;
  border-radius: 6px;
  font-size: 12.5px;
  font-family: inherit;
  cursor: pointer;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--text);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.lp-btn:disabled { opacity: 0.55; cursor: not-allowed; }
.lp-btn-ghost:hover:not(:disabled) {
  border-color: var(--brand);
  color: var(--brand);
}
.lp-btn-icon { font-size: 13px; line-height: 1; }

.lp-footer {
  padding: 16px;
  display: flex;
  justify-content: center;
}

/* Modal */
.lp-modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(11, 27, 63, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.lp-modal {
  width: 600px;
  max-width: 90vw;
  max-height: 80vh;
  background: var(--surface);
  border: 1px solid var(--line-strong);
  border-radius: 14px;
  box-shadow: var(--sh-3);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.lp-modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  border-bottom: 1px solid var(--line);
}
.lp-modal-head h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
}
.lp-modal-close {
  background: transparent;
  border: none;
  font-size: 22px;
  color: var(--text-3);
  cursor: pointer;
  width: 28px;
  height: 28px;
  border-radius: 4px;
}
.lp-modal-close:hover { background: var(--surface-2); color: var(--text); }

.lp-modal-body {
  padding: 14px 18px 18px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.lp-modal-row {
  display: grid;
  grid-template-columns: 80px 1fr;
  gap: 12px;
  font-size: 12.5px;
}
.lp-modal-row label { color: var(--text-3); }
.lp-modal-row-full { grid-template-columns: 1fr; }
.lp-modal-pre {
  font-family: var(--font-mono);
  font-size: 11.5px;
  background: var(--surface-2);
  padding: 12px;
  border-radius: 6px;
  overflow-x: auto;
  max-height: 300px;
  margin: 0;
}
</style>
