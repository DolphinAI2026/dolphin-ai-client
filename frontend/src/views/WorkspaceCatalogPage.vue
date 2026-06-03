<template>
  <WorkbenchShell>
    <div class="catalog-main">
      <section class="catalog-header" aria-label="自开发资产库">
        <div>
          <h1>自开发资产库</h1>
          <p>组件、页面、后端接口</p>
        </div>
      </section>

      <section class="catalog-toolbar" aria-label="资产筛选">
        <div class="catalog-filter-bar">
          <div class="filter-tabs">
            <button
              v-for="tab in tabs"
              :key="tab.value"
              :class="['filter-tab', { active: activeTab === tab.value }]"
              @click="activeTab = tab.value"
            >
              {{ tab.label }}
              <span class="tab-count" v-if="tabCounts[tab.value]">{{ tabCounts[tab.value] }}</span>
            </button>
          </div>
          <div class="catalog-query">
            <el-input v-model="searchQ" placeholder="搜名称 / 包名 / 应用" clearable size="small" class="query-search" />
            <el-select v-model="statusFilter" size="small" class="query-select">
              <el-option v-for="o in statusOptions" :key="o.value" :label="o.label" :value="o.value" />
            </el-select>
            <el-select v-if="!appId && appOptions.length" v-model="appFilter" size="small" class="query-select" clearable placeholder="全部应用">
              <el-option v-for="o in appOptions" :key="o.value" :label="o.label" :value="o.value" />
            </el-select>
          </div>
          <div class="view-toggle">
            <button :class="['toggle-btn', { active: viewMode === 'grid' }]" @click="viewMode = 'grid'" title="卡片视图">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>
            </button>
            <button :class="['toggle-btn', { active: viewMode === 'list' }]" @click="viewMode = 'list'" title="行视图">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
            </button>
          </div>
        </div>
      </section>

      <div class="catalog-content" :class="viewMode">
        <div v-if="loading" class="empty-state">加载中...</div>
        <div v-else-if="filteredWorkspaces.length === 0" class="empty-state">
          还没有自开发资产
        </div>

        <template v-else-if="viewMode === 'grid'">
          <article
            v-for="ws in pagedWorkspaces"
            :key="ws.id"
            class="grid-card"
            @click="openWorkspace(ws)"
          >
            <div class="grid-card-top">
              <div class="grid-card-main">
                <div class="grid-card-copy">
                  <h3 class="grid-card-name">{{ workspaceDisplayName(ws) }}</h3>
                  <div class="grid-card-meta">
                    <span v-if="workspaceCodeName(ws)" class="card-code">{{ workspaceCodeName(ws) }}</span>
                  </div>
                </div>
              </div>
              <div class="grid-card-badges">
                <span v-if="workspaceAppName(ws)" class="app-badge">应用：{{ workspaceAppName(ws) }}</span>
                <span class="source-badge">{{ workspaceGroupLabel(ws.project_type) }}</span>
                <span class="card-status">{{ workspaceStatusLabel(ws.status) }}</span>
              </div>
            </div>
            <div class="grid-card-footer">
              <div class="grid-card-stats">
                <span>文件类型：{{ workspaceGroupLabel(ws.project_type) }}</span>
                <span>包名：{{ workspaceCodeName(ws) || ws.project_name }}</span>
              </div>
              <div class="grid-card-actions" @click.stop>
                <button class="action-btn primary" @click.stop="openWorkspace(ws)" title="打开 IDE">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                </button>
                <button :class="['action-btn', { 'is-loading': uploadingWsId === ws.id }]" @click.stop="uploadWorkspace(ws)" :disabled="uploadingWsId === ws.id" :title="uploadingWsId === ws.id ? '上传中...' : '上传组件包'">
                  <svg v-if="uploadingWsId !== ws.id" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                  <svg v-else width="13" height="13" class="spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9" stroke-dasharray="42 15"/></svg>
                </button>
                <button class="action-btn" @click.stop="downloadWorkspace(ws, 'src')" title="下载源码">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                </button>
              </div>
            </div>
          </article>
        </template>

        <template v-else>
          <el-table :data="pagedWorkspaces" stripe class="ws-table" @row-click="(row) => openWorkspace(row)">
            <el-table-column label="名称" min-width="170">
              <template #default="{ row }"><span class="ws-table-name">{{ workspaceDisplayName(row) }}</span></template>
            </el-table-column>
            <el-table-column label="包名" min-width="150">
              <template #default="{ row }">{{ workspaceCodeName(row) || row.project_name }}</template>
            </el-table-column>
            <el-table-column label="类型" width="110">
              <template #default="{ row }">{{ workspaceGroupLabel(row.project_type) }}</template>
            </el-table-column>
            <el-table-column label="所属应用" min-width="130">
              <template #default="{ row }">{{ workspaceAppName(row) || '—' }}</template>
            </el-table-column>
            <el-table-column label="状态" width="92">
              <template #default="{ row }">{{ workspaceStatusLabel(row.status) }}</template>
            </el-table-column>
            <el-table-column label="更新时间" width="150">
              <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="132" fixed="right">
              <template #default="{ row }">
                <div class="ws-table-actions" @click.stop>
                  <button class="action-btn primary" @click.stop="openWorkspace(row)" title="打开 IDE">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                  </button>
                  <button :class="['action-btn', { 'is-loading': uploadingWsId === row.id }]" @click.stop="uploadWorkspace(row)" :disabled="uploadingWsId === row.id" :title="uploadingWsId === row.id ? '上传中...' : '上传组件包'">
                    <svg v-if="uploadingWsId !== row.id" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                    <svg v-else width="14" height="14" class="spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9" stroke-dasharray="42 15"/></svg>
                  </button>
                  <button class="action-btn" @click.stop="downloadWorkspace(row, 'src')" title="下载源码">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                  </button>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </template>
      </div>

      <div v-if="!loading && filteredWorkspaces.length > pageSize" class="catalog-pagination">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :total="filteredWorkspaces.length"
          :page-sizes="[12, 24, 48, 96]"
          layout="total, sizes, prev, pager, next, jumper"
          background
        />
      </div>
    </div>
  </WorkbenchShell>

  <EnvSelectModal v-model="showEnvModal" @selected="onEnvSelected" />

  <!-- 全屏 IDE 抽屉：点击工作区直接进 code-server 看/改代码（不再跳 Coding 工作台） -->
  <WorkspaceIdeDrawer ref="ideDrawer" />
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import EnvSelectModal from '@/components/EnvSelectModal.vue'
import { codingApi, type WorkspaceInfo } from '@/api/coding'
import { applicationApi } from '@/api/application'
import { platformEnvApi } from '@/api/platformEnv'
import WorkspaceIdeDrawer from '@/components/common/WorkspaceIdeDrawer.vue'

const route = useRoute()
const ideDrawer = ref<InstanceType<typeof WorkspaceIdeDrawer>>()
const loading = ref(true)
const workspaces = ref<WorkspaceInfo[]>([])
const activeTab = ref('all')
const viewMode = ref<'grid' | 'list'>('grid')
const appId = computed(() => String(route.query.app_id || ''))
const appNameMap = ref<Record<number, string>>({})

// 查询 + 分页（纯前端；workspaces 全量返回、量小）
const searchQ = ref('')
const statusFilter = ref('all')
const appFilter = ref('')
const currentPage = ref(1)
const pageSize = ref(12)
const statusOptions = [
  { label: '全部状态', value: 'all' },
  { label: '已生成', value: 'ready' },
  { label: '生成中', value: 'building' },
  { label: '本地', value: 'local' },
]

// 上传组件包相关状态
const uploadingWsId = ref<string | null>(null)
const showEnvModal = ref(false)
const pendingUploadWs = ref<WorkspaceInfo | null>(null)

const groupMap: Record<string, { key: string; label: string }> = {
  'form-component': { key: 'component', label: '组件' },
  'form-component-dual': { key: 'component', label: '双端组件' },
  'menu-page': { key: 'page', label: '页面' },
  'form-page': { key: 'page', label: '页面' },
  'form-list': { key: 'page', label: '页面' },
  plugin: { key: 'plugin', label: '扩展插件' },
  'backend-api': { key: 'backend', label: '后端接口' },
  'backend-feign': { key: 'backend', label: '后端接口' },
  'backend-scheduled': { key: 'backend', label: '后端接口' },
}

const tabs = [
  { label: '全部', value: 'all' },
  { label: '组件', value: 'component' },
  { label: '页面', value: 'page' },
  { label: '后端接口', value: 'backend' },
]

// URL ?app_id=N 限定到具体应用 (从应用上下文跳过来的)；否则全部
const visibleWorkspaces = computed(() => {
  if (!appId.value) return workspaces.value
  return workspaces.value.filter(ws => String(ws.project_id || '') === appId.value)
})

const filteredWorkspaces = computed(() => {
  let pool = visibleWorkspaces.value
  if (activeTab.value !== 'all') {
    pool = pool.filter(ws => groupMap[ws.project_type]?.key === activeTab.value)
  }
  if (appFilter.value) {
    pool = pool.filter(ws => String(ws.project_id || '') === appFilter.value)
  }
  if (statusFilter.value !== 'all') {
    pool = pool.filter(ws => workspaceStatusKey(ws.status) === statusFilter.value)
  }
  const q = searchQ.value.trim().toLowerCase()
  if (q) {
    pool = pool.filter(ws =>
      workspaceDisplayName(ws).toLowerCase().includes(q)
      || (ws.project_name || '').toLowerCase().includes(q)
      || workspaceAppName(ws).toLowerCase().includes(q),
    )
  }
  return pool
})

const pagedWorkspaces = computed(() =>
  filteredWorkspaces.value.slice((currentPage.value - 1) * pageSize.value, currentPage.value * pageSize.value),
)

// 所属应用下拉（来自当前可见 workspaces 出现过的应用），无 ?app_id 限定时才显示
const appOptions = computed(() => {
  const seen = new Map<string, string>()
  for (const ws of visibleWorkspaces.value) {
    if (ws.project_id) seen.set(String(ws.project_id), workspaceAppName(ws))
  }
  return Array.from(seen, ([value, label]) => ({ value, label }))
})

watch([searchQ, statusFilter, appFilter, activeTab, appId], () => { currentPage.value = 1 })

const tabCounts = computed(() => {
  const counts: Record<string, number> = {}
  const pool = visibleWorkspaces.value
  for (const tab of tabs) {
    counts[tab.value] = tab.value === 'all'
      ? pool.length
      : pool.filter(ws => groupMap[ws.project_type]?.key === tab.value).length
  }
  return counts
})

function workspaceAppName(ws: WorkspaceInfo): string {
  if (!ws.project_id) return ''
  return appNameMap.value[ws.project_id] || `应用 #${ws.project_id}`
}

function workspaceDisplayName(ws: WorkspaceInfo) {
  return ws.display_name?.trim() || ws.project_name
}

function workspaceCodeName(ws: WorkspaceInfo) {
  const displayName = workspaceDisplayName(ws)
  return displayName !== ws.project_name ? ws.project_name : ''
}

function workspaceGroupLabel(projectType: string) {
  return groupMap[projectType]?.label || '其他'
}

function workspaceStatusLabel(status: string) {
  if (status === 'ready') return '已生成'
  if (status === 'building') return '生成中'
  return '本地'
}

function workspaceStatusKey(status: string) {
  if (status === 'ready') return 'ready'
  if (status === 'building') return 'building'
  return 'local'
}

function formatTime(iso?: string) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

function openWorkspace(ws: WorkspaceInfo) {
  // 直接在资产库内全屏打开该工作区的 Web IDE（code-server），不再跳 Coding 工作台
  ideDrawer.value?.openWorkspace(ws.id)
}

async function downloadWorkspace(ws: WorkspaceInfo, type: 'src' | 'dist') {
  try {
    await codingApi.downloadZip(ws.id, type)
  } catch (e: any) {
    ElMessage.error(e?.message || '下载失败')
  }
}

async function uploadWorkspace(ws: WorkspaceInfo) {
  uploadingWsId.value = ws.id

  let envs: Awaited<ReturnType<typeof platformEnvApi.list>>
  try {
    envs = await platformEnvApi.list()
  } catch {
    ElMessage.error('获取平台环境失败')
    uploadingWsId.value = null
    return
  }
  const connectedEnvs = envs.filter(e => e.status === 'connected')

  if (connectedEnvs.length === 0) {
    ElMessage.warning('没有可用的平台环境，请先在环境管理中配置并连接平台')
    uploadingWsId.value = null
    return
  }

  if (connectedEnvs.length === 1) {
    await doUpload(ws, connectedEnvs[0].id)
  } else {
    // 弹窗选择时先清 loading，由 doUpload 重新接管
    uploadingWsId.value = null
    pendingUploadWs.value = ws
    showEnvModal.value = true
  }
}

async function doUpload(ws: WorkspaceInfo, envId: number) {
  uploadingWsId.value = ws.id
  try {
    await codingApi.uploadToPlatform(ws.id, envId)
    ElMessage.success('上传成功')
  } catch (e: any) {
    ElMessage.error(e?.message || '上传失败')
  } finally {
    uploadingWsId.value = null
  }
}

function onEnvSelected(envId: number) {
  if (pendingUploadWs.value) {
    doUpload(pendingUploadWs.value, envId)
    pendingUploadWs.value = null
  }
}

onMounted(async () => {
  try {
    const [wsList, apps] = await Promise.all([
      codingApi.listWorkspaces(),
      applicationApi.list({ include_remote: false } as any).catch(() => [] as any[]),
    ])
    workspaces.value = wsList
    if (Array.isArray(apps)) {
      const map: Record<number, string> = {}
      for (const app of apps) {
        if (app?.id && (app.app_name || app.appName)) {
          map[Number(app.id)] = app.app_name || app.appName
        }
      }
      appNameMap.value = map
    }
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
/* v3 redesign · 2026-05-20 — visual refresh only, template/script untouched.
   v2 indigo-violet hex → v3 brand-blue token. 4-tier weights, 5-tier sizes,
   r-/sh-/ease tokens, a11y rings. Status pill uses --ok-soft / --ok semantics. */

.catalog-main {
  --catalog-x: clamp(24px, 3vw, 56px);
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 20px var(--catalog-x) 32px;
  overflow-y: auto;
  background: var(--bg-app);
}

.catalog-header {
  min-height: 86px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 24px;
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  background: var(--surface);
}

.catalog-header h1 {
  margin: 0;
  color: var(--text);
  font-size: 24px;
  line-height: 1.16;
  font-weight: var(--fw-bold, 700);
  letter-spacing: 0;
}

.catalog-header p {
  margin: 8px 0 0;
  color: var(--text-3);
  font-size: 13px;
}

.catalog-toolbar {
  display: flex;
  align-items: center;
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  background: var(--surface);
  overflow: hidden;
}

.catalog-filter-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-4);
  padding: 14px 16px;
  max-width: none;
  margin: 0;
  width: 100%;
}

.filter-tabs {
  display: flex;
  gap: var(--s-1);
  flex-wrap: wrap;
}

.filter-tab {
  background: transparent;
  border: none;
  min-height: 34px;
  padding: 0 14px;
  font-size: var(--t-body);
  color: var(--text-3);
  display: inline-flex;
  align-items: center;
  gap: var(--s-2);
  cursor: pointer;
  border-radius: var(--r-3);
  font-family: inherit;
  transition: background 0.14s var(--ease), color 0.14s var(--ease);
}

.filter-tab:hover {
  background: var(--surface-2);
  color: var(--text);
}

.filter-tab.active {
  background: var(--brand-soft);
  color: var(--brand-text);
  font-weight: var(--fw-semibold);
}

.filter-tab:focus-visible {
  outline: 2px solid var(--line-focus);
  outline-offset: 2px;
}

.tab-count {
  font-size: var(--t-micro);
  min-width: 20px;
  padding: 0 7px;
  border-radius: var(--r-full);
  background: var(--brand-soft);
  color: var(--text-3);
  line-height: 20px;
  text-align: center;
}

.filter-tab.active .tab-count {
  background: var(--brand);
  color: #fff;
}

.view-toggle {
  display: flex;
  gap: 2px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--r-3);
  padding: 2px;
}

.toggle-btn {
  width: 32px;
  height: 28px;
  border: none;
  border-radius: var(--r-2);
  background: none;
  color: var(--text-3);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.14s var(--ease), color 0.14s var(--ease);
}

.toggle-btn:hover {
  color: var(--text);
}

.toggle-btn.active {
  background: var(--surface);
  color: var(--brand);
  box-shadow: var(--sh-1);
}

.toggle-btn:focus-visible {
  outline: 2px solid var(--line-focus);
  outline-offset: 2px;
}

.catalog-content {
  flex: 0 0 auto;
  overflow: visible;
  max-width: none;
  margin: 0;
  width: 100%;
  padding: 4px 0 32px;
}

.catalog-content.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--s-4);
  align-content: start;
}

.grid-card,
.list-card {
  border-radius: var(--r-5);
  background: var(--surface);
  border: 1px solid var(--line);
  box-shadow: var(--sh-1);
  cursor: pointer;
  transition: background 0.18s var(--ease), border-color 0.18s var(--ease), box-shadow 0.18s var(--ease), transform 0.18s var(--ease);
}

.grid-card:hover,
.list-card:hover {
  background: var(--surface);
  border-color: var(--brand-ring);
  box-shadow: var(--sh-3);
  transform: translateY(-2px);
}

.grid-card:focus-visible,
.list-card:focus-visible {
  outline: 2px solid var(--line-focus);
  outline-offset: 2px;
}

.grid-card {
  padding: 18px;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: var(--s-2);
}

.grid-card-top,
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 14px;
}

.grid-card-main {
  min-width: 0;
  flex: 1;
}

.grid-card-copy {
  display: flex;
  flex-direction: column;
  gap: var(--s-1);
  min-width: 0;
}

.grid-card-badges,
.card-name-row {
  display: flex;
  align-items: center;
  gap: var(--s-1);
  flex-wrap: wrap;
}

.grid-card-badges {
  justify-content: flex-end;
  max-width: 120px;
}

.app-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  font-size: var(--t-micro);
  font-weight: var(--fw-medium);
  background: var(--brand-soft);
  color: var(--brand-text);
  border: 1px solid var(--brand-ring);
  border-radius: var(--r-full);
  white-space: nowrap;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.source-badge,
.card-status {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 var(--s-2);
  border-radius: var(--r-full);
  font-size: var(--t-micro);
  font-weight: var(--fw-semibold);
}

.source-badge {
  background: var(--surface-3);
  color: var(--text-3);
}

.card-status {
  background: var(--ok-soft);
  color: var(--ok);
}

.grid-card-name,
.card-name-row h3 {
  margin: 0;
  font-size: 15px;
  line-height: 1.3;
  color: var(--text);
  font-weight: var(--fw-semibold);
  word-break: break-word;
}

.grid-card-meta,
.card-meta {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  flex-wrap: wrap;
  color: var(--text-3);
  font-size: var(--t-micro);
}

.grid-card-footer {
  margin-top: 2px;
  padding-top: var(--s-2);
  border-top: 1px solid var(--line);
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--s-3);
}

.card-code {
  padding: 0 7px;
  border-radius: var(--r-3);
  background: var(--surface-2);
  font-family: var(--font-mono);
}

.grid-card-stats,
.card-stats {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--s-2);
  color: var(--text-3);
  font-size: var(--t-micro);
}

.grid-card-actions,
.card-actions {
  display: flex;
  gap: var(--s-1);
}

.action-btn {
  width: 32px;
  height: 32px;
  border-radius: var(--r-3);
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--text-3);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.14s var(--ease), border-color 0.14s var(--ease), color 0.14s var(--ease);
}

.action-btn:hover {
  background: var(--brand-soft);
  border-color: var(--brand-ring);
  color: var(--brand);
}

.action-btn.primary {
  color: var(--brand);
  border-color: var(--brand-ring);
}

.action-btn:focus-visible {
  outline: 2px solid var(--line-focus);
  outline-offset: 2px;
}

.action-btn:disabled,
.action-btn.is-loading {
  opacity: 0.6;
  cursor: not-allowed;
  pointer-events: none;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.catalog-content.list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.list-card {
  padding: 18px 20px;
}

.card-left,
.card-info {
  display: flex;
  gap: 14px;
  min-width: 0;
}

.card-info {
  flex-direction: column;
  gap: var(--s-2);
}

.empty-state {
  grid-column: 1 / -1;
  min-height: 260px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px;
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  background: var(--surface);
  color: var(--text-3);
  font-size: var(--t-body);
  text-align: center;
}

@media (max-width: 1200px) {
  .catalog-content.grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@media (max-width: 900px) {
  .catalog-main {
    --catalog-x: var(--s-4);
    padding-top: var(--s-4);
    padding-bottom: var(--s-4);
  }

  .catalog-header {
    min-height: 0;
    padding: 18px;
  }

  .catalog-filter-bar {
    align-items: flex-start;
    flex-direction: column;
    padding: 14px;
  }

  .catalog-content {
    padding: 0 0 var(--s-4);
  }

  .catalog-content.grid {
    grid-template-columns: 1fr;
    gap: 14px;
  }

  .grid-card {
    padding: 18px;
    min-height: 0;
  }

  .grid-card-footer {
    align-items: flex-start;
    flex-direction: column;
  }

  .grid-card-name,
  .card-name-row h3 {
    font-size: 14px;
  }
}

/* —— #4 资产库优化：查询栏 + 分页 + 表格视图 —— */
.catalog-query {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  justify-content: flex-end;
  min-width: 0;
}
.catalog-query .query-search { width: 220px; max-width: 40vw; }
.catalog-query .query-select { width: 132px; }

.catalog-pagination {
  display: flex;
  justify-content: flex-end;
  padding: 4px var(--catalog-x) 8px;
}

.ws-table { width: 100%; cursor: pointer; }
.ws-table-name { font-weight: var(--fw-semibold, 600); color: var(--text); }
.ws-table-actions { display: flex; gap: 6px; }

</style>

<style>

/* v3 dark theme — all explicit colors swapped to v3 dark tokens.
   The :root[data-theme="dark"] block in design-v3-tokens.css already remaps
   --surface / --text / --brand etc, so most rules can use the same vars. */

html[data-theme="dark"] .catalog-main {
  background: var(--bg) !important;
  color: var(--text) !important;
}

html[data-theme="dark"] .catalog-main .filter-tab {
  color: var(--text-3) !important;
}

html[data-theme="dark"] .catalog-main .filter-tab:hover {
  background: var(--surface-2) !important;
  color: var(--text) !important;
}

html[data-theme="dark"] .catalog-main .filter-tab.active {
  background: var(--brand-soft) !important;
  color: var(--brand-text) !important;
}

html[data-theme="dark"] .catalog-main .tab-count,
html[data-theme="dark"] .catalog-main .source-badge,
html[data-theme="dark"] .catalog-main .card-code {
  background: var(--surface-3) !important;
  border-color: var(--line) !important;
  color: var(--text-3) !important;
}

html[data-theme="dark"] .catalog-main .view-toggle {
  background: var(--surface-2) !important;
  border: 1px solid var(--line) !important;
}

html[data-theme="dark"] .catalog-main .toggle-btn {
  color: var(--text-3) !important;
}

html[data-theme="dark"] .catalog-main .toggle-btn.active {
  background: var(--brand-soft) !important;
  color: var(--brand-text) !important;
}

html[data-theme="dark"] .catalog-main .grid-card,
html[data-theme="dark"] .catalog-main .list-card {
  background: var(--surface) !important;
  border-color: var(--line) !important;
  box-shadow: var(--sh-1) !important;
}

html[data-theme="dark"] .catalog-main .grid-card:hover,
html[data-theme="dark"] .catalog-main .list-card:hover {
  background: var(--surface-2) !important;
  border-color: var(--brand-ring) !important;
  box-shadow: var(--sh-3) !important;
}

html[data-theme="dark"] .catalog-main .grid-card-name,
html[data-theme="dark"] .catalog-main .card-name-row h3 {
  color: var(--text) !important;
}

html[data-theme="dark"] .catalog-main .grid-card-meta,
html[data-theme="dark"] .catalog-main .card-meta,
html[data-theme="dark"] .catalog-main .grid-card-stats,
html[data-theme="dark"] .catalog-main .card-stats,
html[data-theme="dark"] .catalog-main .empty-state {
  color: var(--text-3) !important;
}

html[data-theme="dark"] .catalog-main .grid-card-footer {
  border-top-color: var(--line) !important;
}

html[data-theme="dark"] .catalog-main .card-status {
  background: var(--ok-soft) !important;
  color: var(--ok) !important;
}

html[data-theme="dark"] .catalog-main .action-btn {
  background: var(--surface-2) !important;
  border-color: var(--line) !important;
  color: var(--text-3) !important;
}

html[data-theme="dark"] .catalog-main .action-btn.primary {
  background: var(--brand-soft) !important;
  border-color: var(--brand-ring) !important;
  color: var(--brand-text) !important;
}

html[data-theme="dark"] .catalog-main .action-btn:hover {
  background: var(--brand-soft) !important;
  border-color: var(--brand-ring) !important;
  color: var(--brand-text) !important;
}
</style>
