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
                {{ loading ? '加载中…' : '暂无沙箱' }}
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
    await sandboxApi.start(s.workspace_id)
    ElMessage.success('已启动')
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
.sandbox-page {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 24px 28px;
  gap: 16px;
  background: var(--t-bg-base, #f6f8fc);
  color: var(--t-text-primary, #0f172a);
  overflow: auto;
}

.sb-head {
  display: grid;
  grid-template-columns: 1fr auto auto;
  gap: 24px;
  align-items: center;
}
.sb-title h1 {
  margin: 4px 0 6px;
  font-size: 22px;
  font-weight: 700;
}
.sb-kicker {
  font-size: 11px;
  letter-spacing: 0.12em;
  font-weight: 700;
  color: var(--t-brand, #6366f1);
}
.sb-desc {
  margin: 0;
  font-size: 13px;
  color: var(--t-text-secondary, #526179);
}
.sb-stats {
  display: flex;
  gap: 12px;
}
.sb-stat {
  border: 1px solid var(--t-border-subtle, rgba(116, 128, 171, 0.16));
  border-radius: 10px;
  padding: 10px 18px;
  background: var(--t-bg-elevated, #fff);
  text-align: center;
}
.sb-stat strong {
  display: block;
  font-size: 20px;
  font-weight: 700;
  color: var(--t-text-primary);
}
.sb-stat span {
  font-size: 11px;
  color: var(--t-text-muted);
}
.sb-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}
.sb-auto {
  font-size: 12px;
  color: var(--t-text-secondary);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}
.sb-btn {
  border: 1px solid var(--t-border-subtle, rgba(116, 128, 171, 0.18));
  border-radius: 8px;
  padding: 6px 14px;
  background: var(--t-bg-elevated, #fff);
  color: var(--t-text-primary);
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  transition: background 0.15s;
}
.sb-btn:hover:not(:disabled) {
  background: var(--t-bg-soft, rgba(15, 23, 42, 0.06));
}
.sb-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.sb-btn.sm {
  padding: 4px 10px;
  font-size: 12px;
}
.sb-btn.danger {
  color: #b91c1c;
  border-color: rgba(239, 68, 68, 0.32);
}
.sb-btn.danger:hover:not(:disabled) {
  background: rgba(239, 68, 68, 0.06);
}
.sb-btn.primary {
  color: #15803d;
  border-color: rgba(34, 197, 94, 0.36);
}
.sb-btn.primary:hover:not(:disabled) {
  background: rgba(34, 197, 94, 0.08);
}
.sandbox-page.theme-dark .sb-btn.primary {
  color: #4ade80;
  border-color: rgba(34, 197, 94, 0.42);
}
.sandbox-page.theme-dark .sb-btn.primary:hover:not(:disabled) {
  background: rgba(34, 197, 94, 0.10);
}

.sb-table-wrap {
  border: 1px solid var(--t-border-subtle, rgba(116, 128, 171, 0.16));
  border-radius: 12px;
  background: var(--t-bg-elevated, #fff);
  overflow: hidden;
}
.sb-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.sb-table th {
  text-align: left;
  padding: 10px 14px;
  background: var(--t-bg-soft, rgba(15, 23, 42, 0.04));
  font-weight: 600;
  color: var(--t-text-secondary);
  font-size: 11.5px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  border-bottom: 1px solid var(--t-border-subtle, rgba(116, 128, 171, 0.14));
}
.sb-table td {
  padding: 10px 14px;
  border-bottom: 1px solid var(--t-border-soft, rgba(116, 128, 171, 0.10));
  vertical-align: middle;
}
.sb-table tr:last-child td {
  border-bottom: none;
}
.sb-table tr.is-running {
  background: rgba(34, 197, 94, 0.04);
}
.sb-empty {
  text-align: center;
  padding: 48px;
  color: var(--t-text-muted);
}
.sb-ws-title {
  font-weight: 600;
  color: var(--t-brand, #6366f1);
  cursor: pointer;
  text-decoration: none;
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sb-ws-title:hover {
  text-decoration: underline;
}
.sb-ws-id {
  font-size: 11px;
  color: var(--t-text-muted);
  font-family: ui-monospace, monospace;
}
.sb-status {
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 11.5px;
  font-weight: 600;
}
.sb-status.status-running {
  background: rgba(34, 197, 94, 0.12);
  color: #15803d;
}
.sb-status.status-exited,
.sb-status.status-paused {
  background: rgba(148, 163, 184, 0.16);
  color: #475569;
}
.sb-status.status-created {
  background: rgba(245, 158, 11, 0.16);
  color: #b45309;
}
.sb-status.status-none {
  background: rgba(148, 163, 184, 0.10);
  color: var(--t-text-muted);
}
.sb-ports {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 4px;
}
.sb-port-chip {
  font-family: ui-monospace, monospace;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(99, 102, 241, 0.10);
  color: var(--t-brand, #6366f1);
}
.sb-time {
  font-size: 12px;
  color: var(--t-text-secondary);
  white-space: nowrap;
}
.sb-row-actions {
  display: flex;
  gap: 6px;
  flex-wrap: nowrap;
}
.sb-muted {
  color: var(--t-text-muted);
  font-size: 12px;
}
.sb-foot {
  font-size: 11.5px;
  color: var(--t-text-muted);
}

/* dark theme */
.sandbox-page.theme-dark .sb-stat,
.sandbox-page.theme-dark .sb-btn,
.sandbox-page.theme-dark .sb-table-wrap {
  background: #111318;
  border-color: rgba(148, 163, 184, 0.14);
  color: rgba(226, 232, 240, 0.86);
}
.sandbox-page.theme-dark .sb-table th {
  background: rgba(255, 255, 255, 0.04);
  color: rgba(226, 232, 240, 0.7);
}
.sandbox-page.theme-dark .sb-table tr.is-running {
  background: rgba(34, 197, 94, 0.06);
}
</style>
