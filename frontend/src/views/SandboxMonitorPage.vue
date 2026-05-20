<template>
  <WorkbenchShell>
    <div class="sandbox-page" :class="themeStore.isDark ? 'theme-dark' : 'theme-light'">
      <header class="sb-head">
        <div class="sb-title">
          <span class="sb-kicker">VIBE CODING</span>
          <h1>沙箱监控</h1>
          <p class="sb-desc">{{ scopeDesc }}</p>
        </div>
        <div class="sb-stats">
          <div class="sb-stat">
            <strong>{{ runningCount }}</strong>
            <span>运行中</span>
          </div>
          <div class="sb-stat">
            <strong>{{ stoppedCount }}</strong>
            <span>已停止</span>
          </div>
          <div class="sb-stat">
            <strong>{{ data.total }}</strong>
            <span>总计</span>
          </div>
        </div>
        <div class="sb-actions">
          <label class="sb-auto">
            <input type="checkbox" v-model="autoRefresh" />
            <span>自动刷新（5s）</span>
          </label>
          <button class="sb-btn" @click="fetchList" :disabled="loading">
            <span v-if="loading">刷新中…</span>
            <span v-else>↻ 刷新</span>
          </button>
        </div>
      </header>

      <section class="sb-table-wrap">
        <table class="sb-table">
          <thead>
            <tr>
              <th>Workspace</th>
              <th v-if="data.scope !== 'user'">Owner</th>
              <th v-if="data.scope === 'platform'">Tenant</th>
              <th>状态</th>
              <th>端口映射</th>
              <th>更新时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!data.sandboxes.length">
              <td :colspan="colspan" class="sb-empty">
                <SkeletonCard v-if="loading" :lines="3" with-footer />
                <EmptyState
                  v-else
                  title="暂无沙箱"
                  desc="还没有任何 Vibe Coding 工作区在运行。去对话里告诉 AI 你要做什么，它会帮你启动。"
                >
                  <template #icon>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></svg>
                  </template>
                </EmptyState>
              </td>
            </tr>
            <tr
              v-for="s in data.sandboxes"
              :key="s.workspace_id"
              :class="{ 'is-running': s.container_status === 'running' }"
            >
              <td>
                <div class="sb-ws-title" @click="openWorkspace(s.workspace_id)" :title="s.workspace_id">
                  {{ s.title }}
                </div>
                <div class="sb-ws-id">{{ s.workspace_id }}</div>
              </td>
              <td v-if="data.scope !== 'user'">
                {{ s.owner_username || `user#${s.user_id}` }}
              </td>
              <td v-if="data.scope === 'platform'">
                #{{ s.tenant_id }}
              </td>
              <td>
                <span class="sb-status" :class="`status-${s.container_status || 'none'}`">
                  {{ statusLabel(s.container_status) }}
                </span>
              </td>
              <td>
                <span v-if="!Object.keys(s.ports).length" class="sb-muted">—</span>
                <span v-else class="sb-ports">
                  <span v-for="(hp, cp) in s.ports" :key="cp" class="sb-port-chip">
                    {{ cp }} → :{{ hp }}
                  </span>
                </span>
              </td>
              <td class="sb-time">{{ formatTime(s.updated_at) }}</td>
              <td>
                <div class="sb-row-actions">
                  <button
                    v-if="s.container_status !== 'running'"
                    class="sb-btn sm primary"
                    @click="onStart(s)"
                    :disabled="busyMap[s.workspace_id]"
                  >启动</button>
                  <button
                    v-if="s.container_status === 'running'"
                    class="sb-btn sm"
                    @click="onStop(s)"
                    :disabled="busyMap[s.workspace_id]"
                  >停止</button>
                  <button
                    v-if="s.container_status && s.container_status !== 'none'"
                    class="sb-btn sm danger"
                    @click="onRemove(s)"
                    :disabled="busyMap[s.workspace_id]"
                  >删除容器</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <footer class="sb-foot">
        <span class="sb-muted">
          停止：保留容器壳（node_modules 等不丢，下次复用）。
          删除容器：彻底清理（容器层数据丢，workspace 用户代码不动）。
        </span>
      </footer>
    </div>
  </WorkbenchShell>
</template>

<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import SkeletonCard from '@/components/states/SkeletonCard.vue'
import { useThemeStore } from '@/stores/theme'
import { sandboxApi, type SandboxInfo, type SandboxListResponse } from '@/api/sandboxes'

const themeStore = useThemeStore()
const router = useRouter()

const data = ref<SandboxListResponse>({ sandboxes: [], scope: 'user', total: 0 })
const loading = ref(false)
const autoRefresh = ref(true)
const busyMap = ref<Record<string, boolean>>({})
let refreshTimer: ReturnType<typeof setInterval> | null = null

const scopeDesc = computed(() => {
  switch (data.value.scope) {
    case 'platform':
      return '平台管理员视角 — 所有租户的所有 sandbox'
    case 'tenant':
      return '租户管理员视角 — 本租户内所有用户的 sandbox'
    default:
      return '只显示你自己创建的 sandbox'
  }
})

const colspan = computed(() => {
  let n = 5
  if (data.value.scope !== 'user') n += 1
  if (data.value.scope === 'platform') n += 1
  return n
})

const runningCount = computed(() =>
  data.value.sandboxes.filter(s => s.container_status === 'running').length,
)
const stoppedCount = computed(() =>
  data.value.sandboxes.filter(s =>
    s.container_status && s.container_status !== 'running',
  ).length,
)

function statusLabel(s?: string | null): string {
  if (!s) return '未启动'
  return ({
    running: '运行中',
    exited: '已停止',
    created: '已创建',
    paused: '已暂停',
    none: '未启动',
  } as Record<string, string>)[s] || s
}

function formatTime(t?: string | null): string {
  if (!t) return ''
  try {
    const d = new Date(t)
    if (Number.isNaN(d.getTime())) return t
    const now = Date.now()
    const diffMs = now - d.getTime()
    const min = Math.floor(diffMs / 60000)
    if (min < 1) return '刚刚'
    if (min < 60) return `${min} 分钟前`
    if (min < 60 * 24) return `${Math.floor(min / 60)} 小时前`
    return d.toLocaleString('zh-CN', { hour12: false })
  } catch {
    return t
  }
}

async function fetchList() {
  loading.value = true
  try {
    const r = await sandboxApi.list()
    data.value = r
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

async function onStart(s: SandboxInfo) {
  busyMap.value[s.workspace_id] = true
  try {
    const r = await sandboxApi.start(s.workspace_id)
    const restored = r?.restored_commands || []
    if (restored.length) {
      ElMessage.success(`已启动 — 自动恢复了 ${restored.length} 个后台服务（${restored[0].slice(0, 40)}${restored[0].length > 40 ? '…' : ''}${restored.length > 1 ? ' 等' : ''}）`)
    } else {
      ElMessage.success('已启动 — 暂无之前的后台服务记录，需回 chat 让 agent 重新启动 dev server')
    }
    // 给容器内服务一点时间起来再刷新
    setTimeout(() => { fetchList() }, 3000)
    await fetchList()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '启动失败')
  } finally {
    busyMap.value[s.workspace_id] = false
  }
}

async function onStop(s: SandboxInfo) {
  try {
    await ElMessageBox.confirm(
      `停止 sandbox「${s.title}」？容器会保留，下次访问时复用 node_modules。`,
      '停止 sandbox',
      { confirmButtonText: '停止', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  busyMap.value[s.workspace_id] = true
  try {
    await sandboxApi.stop(s.workspace_id)
    ElMessage.success('已停止')
    await fetchList()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '停止失败')
  } finally {
    busyMap.value[s.workspace_id] = false
  }
}

async function onRemove(s: SandboxInfo) {
  try {
    await ElMessageBox.confirm(
      `彻底删除 sandbox 容器「${s.title}」？容器层数据会丢失（包括已装的 node_modules，下次需要重装），但 workspace 里的用户代码不动。`,
      '删除 sandbox 容器',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning',
        confirmButtonClass: 'el-button--danger',
      },
    )
  } catch {
    return
  }
  busyMap.value[s.workspace_id] = true
  try {
    await sandboxApi.remove(s.workspace_id)
    ElMessage.success('已删除容器')
    await fetchList()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '删除失败')
  } finally {
    busyMap.value[s.workspace_id] = false
  }
}

function openWorkspace(workspaceId: string) {
  router.push(`/vibe-coding/workspaces/${workspaceId}`)
}

function startTimer() {
  stopTimer()
  if (!autoRefresh.value) return
  refreshTimer = setInterval(() => {
    if (!loading.value) fetchList()
  }, 5000)
}
function stopTimer() {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
}

onMounted(async () => {
  await fetchList()
  startTimer()
})
onBeforeUnmount(stopTimer)

import { watch } from 'vue'
watch(autoRefresh, () => {
  startTimer()
})
</script>

<style scoped>
/* v3 redesign · 2026-05-20 — visual refresh only, template/script untouched.
   Preserved (don't change):
     - WorkbenchShell wrapper + all .sb-* class names
     - 3-scope (user/tenant/platform) column visibility (API-driven, not UI toggle)
     - busyMap row disable behaviour
     - footer semantic note "停止 vs 删除容器"
     - dark theme rules (re-pointed at v3 tokens; same selector contract)
   Refreshed:
     - All hex → v3 tokens (--brand / --surface / --line / --text / --ok / --warn / --err)
     - Stats numbers 20px → 24px 700 with tnum
     - running stat colored --ok; stopped goes muted --text-3
     - Auto-refresh checkbox uses accent-color: var(--brand)
     - Table head bg --surface-2 + 11.5px 600 letter-spacing
     - Status pill: 5px left dot (currentColor) + status-tinted soft bg
     - Workspace cell stacked (--text title + mono --text-3 id)
     - Port chip --surface-3 + mono 10.5px + r-1
     - Row actions render as link-style buttons (start/stop = brand; delete = err)
*/
.sandbox-page {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 24px 28px;
  gap: 18px;
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-sans);
  overflow: auto;
}

/* ── Header ─────────────────────────────────────────────────────── */
.sb-head {
  display: grid;
  grid-template-columns: 1fr auto auto;
  gap: 24px;
  align-items: center;
  padding: 18px 20px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-4, 12px);
  box-shadow: var(--sh-1);
}
.sb-title { min-width: 0; }
.sb-title h1 {
  margin: 6px 0 4px;
  font-size: 18px;
  font-weight: 600;
  color: var(--text);
  letter-spacing: -0.01em;
}
.sb-kicker {
  display: inline-block;
  font-size: 11px;
  letter-spacing: 0.14em;
  font-weight: 700;
  color: var(--brand);
  text-transform: uppercase;
}
.sb-desc {
  margin: 0;
  font-size: 12.5px;
  color: var(--text-3);
}

.sb-stats {
  display: flex;
  gap: 10px;
}
.sb-stat {
  min-width: 92px;
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  padding: 10px 16px;
  background: var(--surface);
  text-align: center;
}
.sb-stat strong {
  display: block;
  font-size: 24px;
  font-weight: 700;
  color: var(--text);
  line-height: 1.15;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.01em;
}
.sb-stat span {
  display: block;
  margin-top: 2px;
  font-size: 11px;
  color: var(--text-3);
  letter-spacing: 0.02em;
}
/* Stats are rendered in fixed order: running / stopped / total.
   Color via :nth-child so we keep the template untouched. */
.sb-stats .sb-stat:nth-child(1) strong { color: var(--ok); }
.sb-stats .sb-stat:nth-child(2) strong { color: var(--text-3); }

.sb-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}
.sb-auto {
  font-size: 12.5px;
  color: var(--text-2);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  user-select: none;
}
.sb-auto input[type="checkbox"] {
  width: 14px;
  height: 14px;
  margin: 0;
  accent-color: var(--brand);
  cursor: pointer;
}

/* ── Buttons (header refresh + row actions) ─────────────────────── */
.sb-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 30px;
  padding: 0 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-2, 6px);
  background: var(--surface);
  color: var(--text-2);
  cursor: pointer;
  font-size: 12.5px;
  font-weight: 500;
  font-family: inherit;
  transition: border-color 0.14s var(--ease),
              background 0.14s var(--ease),
              color 0.14s var(--ease);
}
.sb-btn:hover:not(:disabled) {
  color: var(--brand);
  border-color: var(--brand-ring);
  background: var(--brand-soft);
}
.sb-btn:focus-visible {
  outline: 2px solid var(--line-focus);
  outline-offset: 2px;
}
.sb-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

/* Row-action buttons render as plain links to keep the table calm. */
.sb-btn.sm {
  height: auto;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--brand);
  font-size: 12px;
  font-weight: 500;
  border-radius: 0;
}
.sb-btn.sm:hover:not(:disabled) {
  background: transparent;
  color: var(--brand-hover);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.sb-btn.sm.primary { color: var(--brand); }
.sb-btn.sm.primary:hover:not(:disabled) { color: var(--brand-hover); }
.sb-btn.sm.danger { color: var(--err); }
.sb-btn.sm.danger:hover:not(:disabled) {
  color: var(--err);
  opacity: 0.82;
}

/* ── Table ──────────────────────────────────────────────────────── */
.sb-table-wrap {
  border: 1px solid var(--line);
  border-radius: var(--r-4, 12px);
  background: var(--surface);
  overflow: hidden;
  box-shadow: var(--sh-1);
}
.sb-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.sb-table th {
  text-align: left;
  padding: 10px 16px;
  background: var(--surface-2);
  font-weight: 600;
  color: var(--text-3);
  font-size: 11.5px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  border-bottom: 1px solid var(--line);
}
.sb-table td {
  padding: 12px 16px;
  border-bottom: 1px solid var(--line);
  vertical-align: middle;
  color: var(--text-2);
}
.sb-table tr:last-child td { border-bottom: none; }
.sb-table tr.is-running { background: transparent; }
.sb-table tbody tr:hover { background: var(--surface-2); }

.sb-empty {
  text-align: center;
  padding: 56px 24px;
  color: var(--text-3);
  font-size: 13px;
}

/* Workspace cell — stacked title + mono id */
.sb-ws-title {
  font-weight: 500;
  color: var(--text);
  cursor: pointer;
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  letter-spacing: -0.005em;
}
.sb-ws-title:hover {
  color: var(--brand);
}
.sb-ws-id {
  margin-top: 2px;
  font-size: 10.5px;
  color: var(--text-3);
  font-family: var(--font-mono);
  letter-spacing: 0;
}

/* Status pill — 5px left dot in currentColor */
.sb-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px 3px 9px;
  border-radius: var(--r-full, 999px);
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0.01em;
  line-height: 1.4;
}
.sb-status::before {
  content: '';
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
  flex-shrink: 0;
}
.sb-status.status-running {
  background: var(--ok-soft);
  color: var(--ok);
}
.sb-status.status-exited,
.sb-status.status-paused {
  background: var(--surface-3);
  color: var(--text-3);
}
.sb-status.status-created {
  background: var(--warn-soft);
  color: var(--warn);
}
.sb-status.status-none {
  background: var(--surface-3);
  color: var(--text-3);
}

/* Port chips */
.sb-ports {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 4px;
}
.sb-port-chip {
  font-family: var(--font-mono);
  font-size: 10.5px;
  padding: 2px 6px;
  border-radius: var(--r-1, 4px);
  background: var(--surface-3);
  color: var(--text-2);
}

.sb-time {
  font-size: 12px;
  color: var(--text-3);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.sb-row-actions {
  display: flex;
  gap: 14px;
  flex-wrap: nowrap;
  align-items: center;
}
.sb-muted {
  color: var(--text-3);
  font-size: 12px;
}

/* ── Footer ─────────────────────────────────────────────────────── */
.sb-foot {
  font-size: 11.5px;
  color: var(--text-3);
  line-height: 1.6;
  padding: 0 4px;
}

/* ── Dark theme overrides (v3 tokens already shift via [data-theme]) ─ */
.sandbox-page.theme-dark .sb-head,
.sandbox-page.theme-dark .sb-stat,
.sandbox-page.theme-dark .sb-table-wrap {
  background: var(--surface);
  border-color: var(--line);
}
.sandbox-page.theme-dark .sb-btn {
  background: var(--surface);
  color: var(--text-2);
  border-color: var(--line);
}
.sandbox-page.theme-dark .sb-btn:hover:not(:disabled) {
  color: var(--brand);
  background: var(--brand-soft);
  border-color: var(--brand-ring);
}
.sandbox-page.theme-dark .sb-table th {
  background: var(--surface-2);
  color: var(--text-3);
}
.sandbox-page.theme-dark .sb-table tbody tr:hover {
  background: var(--surface-2);
}
.sandbox-page.theme-dark .sb-table tr.is-running {
  background: transparent;
}

/* ── Phase 6 · table density + filter UX tightening (append-only) ──
   .sb-table is a native HTML <table>, already styled by the block
   above. This block adds the missing density nuances:
   - sticky thead (works because .sb-table-wrap has overflow: hidden
     but the table itself can scroll within a parent .sandbox-page)
   - thead th letter-spacing slightly tighter (0.04em was a bit airy)
   - row vertical padding align with el-table (10/12 px)
   - cell-level transition for hover smoothness */

.sb-table thead th {
  position: sticky;
  top: 0;
  z-index: 2;
  background: var(--surface-2);
  letter-spacing: 0.04em;        /* keep readable, was 0.06 */
}
.sb-table tbody tr {
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

/* Dark variant of sticky thead — must repeat the bg because position
   sticky elements need an explicit bg to cover scrolled rows. */
.sandbox-page.theme-dark .sb-table thead th {
  background: var(--surface-2);
}
</style>
