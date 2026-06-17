<template>
  <BuilderFrame :breadcrumbs="[{ label: '自开发资产库' }]">
    <main class="catalog-page builder-page">
      <section class="catalog-header page-head" aria-label="自开发资产库">
        <div class="catalog-title-block">
          <h1 class="page-title">自开发资产库</h1>
          <p class="page-subtitle">统一查看代码工作区、组件包和后端接口资产。</p>
        </div>

        <div class="catalog-header-side">
          <button class="catalog-import-action" type="button" @click="openImportDialog">
            <AppIcon name="inbox" :size="14" />
            <span>导入源码</span>
          </button>
          <button v-if="isDesktop" class="catalog-import-action catalog-import-action--secondary" type="button" @click="openLocalFolder">
            <AppIcon name="folder" :size="14" />
            <span>打开本地文件夹</span>
          </button>

          <div v-if="!loading && visibleWorkspaces.length" class="catalog-summary" aria-label="资产概览">
            <div v-for="item in headerStats" :key="item.label" class="catalog-summary-item">
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
            </div>
          </div>
        </div>
      </section>

      <section class="catalog-toolbar" aria-label="资产筛选">
        <div class="catalog-tabs" role="tablist" aria-label="资产类型">
          <button
            v-for="tab in tabs"
            :key="tab.value"
            class="catalog-tab"
            :class="{ active: activeTab === tab.value }"
            type="button"
            role="tab"
            :aria-selected="activeTab === tab.value"
            @click="activeTab = tab.value"
          >
            <span>{{ tab.label }}</span>
            <span v-if="tabCounts[tab.value]" class="catalog-tab-count">{{ tabCounts[tab.value] }}</span>
          </button>
        </div>

        <div class="catalog-toolbar-right">
          <el-input v-model="searchQ" placeholder="搜资产名 / 包名 / 应用" clearable size="small" class="catalog-search" />
          <el-select v-model="statusFilter" size="small" class="catalog-select">
            <el-option v-for="o in statusOptions" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
          <el-select
            v-if="!appId && appOptions.length"
            v-model="appFilter"
            size="small"
            class="catalog-select"
            clearable
            placeholder="全部应用"
          >
            <el-option v-for="o in appOptions" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>

          <div class="catalog-view-toggle" aria-label="视图切换">
            <button
              class="catalog-view-btn"
              :class="{ active: viewMode === 'list' }"
              type="button"
              title="列表视图"
              @click="viewMode = 'list'"
            >
              <el-icon><List /></el-icon>
            </button>
            <button
              class="catalog-view-btn"
              :class="{ active: viewMode === 'grid' }"
              type="button"
              title="卡片视图"
              @click="viewMode = 'grid'"
            >
              <el-icon><Grid /></el-icon>
            </button>
          </div>
        </div>
      </section>

      <section class="catalog-content" :class="`is-${viewMode}`">
        <div v-if="loading" class="catalog-state">
          <SkeletonCard :lines="3" with-avatar with-footer />
        </div>
        <div v-else-if="filteredWorkspaces.length === 0" class="catalog-state">
          <EmptyState
            :title="searchQ || statusFilter !== 'all' || appFilter ? '没有匹配的自开发资产' : '暂无自开发资产'"
            :desc="searchQ || statusFilter !== 'all' || appFilter ? '调整筛选条件后再试。' : '从 AI Coding 生成组件、页面或后端接口后，会在这里统一管理。'"
            :variant="searchQ || statusFilter !== 'all' || appFilter ? 'filtered' : 'first'"
          >
            <template #icon>
              <AppIcon name="coding" :size="22" />
            </template>
          </EmptyState>
        </div>

        <div v-else-if="viewMode === 'list'" class="catalog-table">
          <div class="catalog-table-head">
            <span>资产</span>
            <span>类型</span>
            <span>状态</span>
            <span>所属应用</span>
            <span>更新</span>
            <span aria-hidden="true"></span>
          </div>

          <div
            v-for="ws in pagedWorkspaces"
            :key="ws.id"
            class="catalog-row"
            role="button"
            tabindex="0"
            @click="openWorkspace(ws)"
            @keyup.enter="openWorkspace(ws)"
          >
            <div class="catalog-row-asset">
              <span class="asset-avatar" :style="workspaceAccentStyle(ws)">{{ workspaceInitial(ws) }}</span>
              <span class="catalog-row-main">
                <strong>{{ workspaceDisplayName(ws) }}</strong>
                <span class="catalog-row-meta">
                  <code>{{ workspaceCodeName(ws) || ws.project_name }}</code>
                </span>
              </span>
            </div>

            <div class="catalog-row-type">
              <span class="catalog-type-pill" :data-kind="workspaceGroupKey(ws.project_type)">
                <span class="catalog-type-dot" aria-hidden="true"></span>
                {{ workspaceGroupLabel(ws.project_type) }}
              </span>
            </div>
            <div class="catalog-row-status">
              <BaseBadge :variant="workspaceStatusVariant(ws.status)" size="sm">{{ workspaceStatusLabel(ws.status) }}</BaseBadge>
            </div>
            <div class="catalog-row-app" @click.stop>
              <span v-if="workspaceAppName(ws)">{{ workspaceAppName(ws) }}</span>
              <button v-else class="catalog-bind-app" type="button" @click="openBindDialog(ws)">绑定应用</button>
            </div>
            <div class="catalog-row-updated">{{ workspaceUpdatedLabel(ws) }}</div>
            <div class="catalog-row-actions" @click.stop>
              <button class="catalog-mini-action primary" type="button" @click="openWorkspace(ws)">
                <AppIcon name="coding" :size="13" />
                <span>打开</span>
              </button>
              <button class="catalog-mini-action" type="button" @click="downloadWorkspace(ws, 'src')">
                <AppIcon name="download" :size="13" />
                <span>源码</span>
              </button>
            </div>
          </div>
        </div>

        <div v-else class="catalog-card-grid">
          <article
            v-for="ws in pagedWorkspaces"
            :key="ws.id"
            class="catalog-card"
            @click="openWorkspace(ws)"
          >
            <div class="catalog-card-top">
              <span class="asset-avatar large" :style="workspaceAccentStyle(ws)">{{ workspaceInitial(ws) }}</span>
              <BaseBadge :variant="workspaceStatusVariant(ws.status)" size="sm">{{ workspaceStatusLabel(ws.status) }}</BaseBadge>
            </div>
            <h2>{{ workspaceDisplayName(ws) }}</h2>
            <div class="catalog-card-code">
              <code>{{ workspaceCodeName(ws) || ws.project_name }}</code>
              <BaseTag :tone="workspaceGroupKey(ws.project_type) === 'backend' ? 'brand' : 'neutral'">
                {{ workspaceGroupLabel(ws.project_type) }}
              </BaseTag>
              <span>{{ workspaceUpdatedLabel(ws) }}</span>
            </div>
            <div class="catalog-card-meta">
              <span v-if="workspaceAppName(ws)">所属应用：{{ workspaceAppName(ws) }}</span>
              <button v-else class="catalog-bind-app" type="button" @click.stop="openBindDialog(ws)">绑定应用</button>
            </div>
            <div class="catalog-card-actions" @click.stop>
              <button class="catalog-mini-action primary" type="button" @click="openWorkspace(ws)">
                <AppIcon name="coding" :size="13" />
                <span>打开</span>
              </button>
              <button class="catalog-mini-action" type="button" @click="downloadWorkspace(ws, 'src')">
                <AppIcon name="download" :size="13" />
                <span>源码</span>
              </button>
            </div>
          </article>
        </div>
      </section>

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
    </main>
  </BuilderFrame>

  <!-- 点击工作区进入原生代码工作区。 -->

  <el-dialog v-model="bindDialogOpen" title="绑定所属应用" width="380px" :append-to-body="true">
    <p class="bind-dialog-hint">把「{{ bindTarget ? workspaceDisplayName(bindTarget) : '' }}」归属到一个应用，应用详情的交付资产里就能看到它。</p>
    <el-select v-model="bindAppId" placeholder="选择应用" style="width: 100%">
      <el-option v-for="(name, id) in appNameMap" :key="id" :label="name" :value="Number(id)" />
    </el-select>
    <template #footer>
      <el-button @click="bindDialogOpen = false">取消</el-button>
      <el-button type="primary" :disabled="!bindAppId" :loading="binding" @click="confirmBindApp">绑定</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="importDialogOpen" title="导入自开发源码" width="460px" :append-to-body="true">
    <div class="import-dialog-body">
      <button class="import-file-picker" type="button" @click="triggerImportFileInput">
        <AppIcon name="archive" :size="20" />
        <span class="import-file-text">
          <strong>{{ importFile ? importFile.name : '选择源码 zip' }}</strong>
          <span>仅支持从自开发资产下载或同规范打包的 .zip</span>
        </span>
      </button>
      <input
        ref="importFileInputRef"
        class="import-file-input"
        type="file"
        accept=".zip"
        @change="onImportFileChange"
      >

      <el-input v-model="importDisplayName" placeholder="展示名，可选" clearable />
      <el-select v-model="importProjectType" placeholder="自动识别资产类型" clearable style="width: 100%">
        <el-option v-for="option in importProjectTypeOptions" :key="option.value" :label="option.label" :value="option.value" />
      </el-select>
      <el-select v-model="importAppId" placeholder="可选：绑定应用" clearable filterable style="width: 100%">
        <el-option v-for="option in allAppOptions" :key="option.value" :label="option.label" :value="option.value" />
      </el-select>
    </div>
    <template #footer>
      <el-button @click="importDialogOpen = false">取消</el-button>
      <el-button type="primary" :disabled="!importFile" :loading="importing" @click="confirmImportSource">导入</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Grid, List } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import AppIcon from '@/components/common/AppIcon.vue'
import BuilderFrame from '@/components/BuilderFrame.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import SkeletonCard from '@/components/states/SkeletonCard.vue'
import BaseBadge from '@/components/BaseBadge.vue'
import BaseTag from '@/components/BaseTag.vue'
import { codingApi, bindWorkspaceApp, type WorkspaceInfo } from '@/api/coding'
import { applicationApi } from '@/api/application'

const isDesktop = __DESKTOP__

const route = useRoute()
const router = useRouter()
const loading = ref(true)
const workspaces = ref<WorkspaceInfo[]>([])
const activeTab = ref('all')
const viewMode = ref<'grid' | 'list'>('list')
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
const importProjectTypeOptions = [
  { label: '自开发页面', value: 'form-page' },
  { label: '自开发组件', value: 'form-component-dual' },
  { label: '自定义列表', value: 'form-list' },
  { label: '后端接口', value: 'backend-api' },
]

const ASSET_ACCENTS = ['#1D4ED8', '#047857', '#B45309', '#0E7490', '#C2410C', '#7C3AED']

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
const allAppOptions = computed(() =>
  Object.entries(appNameMap.value).map(([value, label]) => ({ value: Number(value), label })),
)

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

const latestWorkspaceUpdatedLabel = computed(() => {
  const latest = visibleWorkspaces.value
    .map(ws => new Date(ws.updated_at || '').getTime())
    .filter(Number.isFinite)
    .sort((a, b) => b - a)[0]
  return latest ? relativeTime(new Date(latest).toISOString()) : '-'
})

const headerStats = computed(() => [
  { label: '资产', value: String(visibleWorkspaces.value.length) },
  {
    label: '已生成',
    value: String(visibleWorkspaces.value.filter(ws => workspaceStatusKey(ws.status) === 'ready').length),
  },
  { label: '最近更新', value: latestWorkspaceUpdatedLabel.value },
])

// 手动绑定所属应用(存量迁移工作区没有会话绑定, 自动回填覆盖不到)
const bindDialogOpen = ref(false)
const bindTarget = ref<WorkspaceInfo | null>(null)
const bindAppId = ref<number | null>(null)
const binding = ref(false)
const importDialogOpen = ref(false)
const importFileInputRef = ref<HTMLInputElement | null>(null)
const importFile = ref<File | null>(null)
const importDisplayName = ref('')
const importProjectType = ref('')
const importAppId = ref<number | null>(null)
const importing = ref(false)

function openBindDialog(ws: WorkspaceInfo) {
  bindTarget.value = ws
  bindAppId.value = null
  bindDialogOpen.value = true
}

async function confirmBindApp() {
  if (!bindTarget.value || !bindAppId.value) return
  binding.value = true
  try {
    await bindWorkspaceApp(bindTarget.value.id, bindAppId.value)
    ;(bindTarget.value as any).project_id = bindAppId.value
    ElMessage.success('已绑定所属应用')
    bindDialogOpen.value = false
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '绑定失败')
  } finally {
    binding.value = false
  }
}

function routeAppId(): number | null {
  const id = Number(appId.value)
  return Number.isFinite(id) && id > 0 ? id : null
}

function openImportDialog() {
  importFile.value = null
  importDisplayName.value = ''
  importProjectType.value = ''
  importAppId.value = routeAppId()
  if (importFileInputRef.value) importFileInputRef.value.value = ''
  importDialogOpen.value = true
}

function triggerImportFileInput() {
  importFileInputRef.value?.click()
}

function onImportFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0] ?? null
  if (file && !file.name.toLowerCase().endsWith('.zip')) {
    ElMessage.error('只支持 .zip 源码包')
    input.value = ''
    importFile.value = null
    return
  }
  importFile.value = file
  if (file && !importDisplayName.value.trim()) {
    importDisplayName.value = file.name.replace(/\.zip$/i, '')
  }
}

async function confirmImportSource() {
  if (!importFile.value) {
    ElMessage.warning('请先选择源码 zip')
    return
  }
  importing.value = true
  try {
    const imported = await codingApi.importZipToWorkspace(importFile.value, {
      project_type: importProjectType.value || undefined,
      project_id: importAppId.value || undefined,
      display_name: importDisplayName.value.trim() || undefined,
    })
    if (importAppId.value) imported.project_id = importAppId.value
    workspaces.value = [imported, ...workspaces.value.filter(ws => ws.id !== imported.id)]
    activeTab.value = 'all'
    searchQ.value = ''
    statusFilter.value = 'all'
    appFilter.value = ''
    currentPage.value = 1
    importDialogOpen.value = false
    ElMessage.success('源码已导入自开发资产库')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '导入失败')
  } finally {
    importing.value = false
  }
}

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

function workspaceGroupKey(projectType: string) {
  return groupMap[projectType]?.key || 'other'
}

function workspaceStatusLabel(status: string) {
  if (status === 'ready') return '已生成'
  if (status === 'building') return '生成中'
  return '本地'
}

function workspaceStatusVariant(status: string): 'success' | 'warn' | 'error' | 'info' | 'neutral' {
  if (status === 'ready') return 'success'
  if (status === 'building') return 'warn'
  return 'neutral'
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

function workspaceUpdatedLabel(ws: WorkspaceInfo) {
  return relativeTime(ws.updated_at)
}

function relativeTime(value?: string | null) {
  if (!value) return '-'
  const time = new Date(value).getTime()
  if (!Number.isFinite(time)) return formatTime(value)
  const diffMs = Date.now() - time
  if (diffMs < 60_000) return '刚刚'
  const minutes = Math.floor(diffMs / 60_000)
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  if (hours < 48) return '昨天'
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days} 天前`
  return String(value).slice(0, 10)
}

function nameHash(name: string): number {
  let h = 0
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0
  return h
}

function workspaceInitial(ws: WorkspaceInfo) {
  const source = workspaceDisplayName(ws) || workspaceCodeName(ws) || ws.project_name || 'C'
  const first = Array.from(source).find(char => char.trim()) || 'C'
  return /[a-z]/.test(first) ? first.toUpperCase() : first
}

function workspaceAccentStyle(ws: WorkspaceInfo) {
  const seed = `${workspaceDisplayName(ws)}|${workspaceCodeName(ws)}|${ws.id}`
  return { background: ASSET_ACCENTS[nameHash(seed) % ASSET_ACCENTS.length] }
}

function openWorkspace(ws: WorkspaceInfo) {
  // 打开原生代码工作区(CodingPage: 文件树 + 代码查看器 + 对话)
  router.push({ path: '/coding', query: { workspace_id: ws.id } }).catch(() => {})
}

async function openLocalFolder() {
  if (!__DESKTOP__) return
  const { open } = await import('@tauri-apps/plugin-dialog')
  const picked = await open({ directory: true, multiple: false, title: '选择要打开的项目文件夹' })
  if (!picked || typeof picked !== 'string') return
  try {
    await ElMessageBox.confirm(
      'AI 可在此文件夹内读写并运行命令（运行命令不受沙箱限制）。建议选用 git 管理或已备份的目录，以便误改可恢复。',
      '打开本地文件夹',
      { confirmButtonText: '我知道了，打开', cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }  // 用户取消确认
  try {
    const ws = await codingApi.openLocalFolder(picked)
    // 复用现有 openWorkspace 导航: router.push({ path: '/coding', query: { workspace_id: ws.ws_id } })
    router.push({ path: '/coding', query: { workspace_id: ws.ws_id } }).catch(() => {})
  } catch (e: any) {
    ElMessage.error(`打开失败: ${e?.response?.data?.detail || e?.message || e}`)
  }
}

async function downloadWorkspace(ws: WorkspaceInfo, type: 'src' | 'dist') {
  try {
    await codingApi.downloadZip(ws.id, type)
  } catch (e: any) {
    ElMessage.error(e?.message || '下载失败')
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
.catalog-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 20px 28px 32px;
}

.catalog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 92px;
  max-width: 1240px;
  width: 100%;
  box-sizing: border-box;
  margin: 0 auto;
  padding: 22px 28px;
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  background: var(--surface);
}

.catalog-title-block {
  min-width: 0;
}

.catalog-header-side {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  margin-left: auto;
  flex-shrink: 0;
}

.catalog-import-action {
  height: 36px;
  min-width: 104px;
  padding: 0 14px;
  border: 1px solid var(--brand);
  border-radius: var(--r-3, 8px);
  background: var(--brand);
  color: var(--text-inverse, #fff);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  font-family: inherit;
  font-size: 13px;
  font-weight: var(--fw-semibold, 600);
  white-space: nowrap;
  cursor: pointer;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.catalog-import-action:hover {
  background: var(--brand-hover);
  border-color: var(--brand-hover);
}

.catalog-import-action--secondary {
  background: var(--surface);
  border-color: var(--line);
  color: var(--text);
}

.catalog-import-action--secondary:hover {
  background: var(--brand-soft);
  border-color: var(--brand-ring);
  color: var(--brand);
}

.catalog-header h1 {
  margin: 0;
  color: var(--text);
  font-size: 28px;
  line-height: 1.12;
  font-weight: var(--fw-bold, 700);
  letter-spacing: 0;
}

.catalog-header p {
  margin: 8px 0 0;
  color: var(--text-3);
  font-size: 13px;
  line-height: 1.45;
}

.catalog-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(86px, auto));
  gap: 8px;
  flex-shrink: 0;
}

.catalog-summary-item {
  min-width: 86px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  background: color-mix(in srgb, var(--surface-2) 74%, var(--surface));
  box-sizing: border-box;
}

.catalog-summary-item span,
.catalog-summary-item strong {
  display: block;
  white-space: nowrap;
}

.catalog-summary-item span {
  color: var(--text-3);
  font-size: 11.5px;
  line-height: 1.3;
}

.catalog-summary-item strong {
  margin-top: 3px;
  color: var(--text);
  font-family: var(--font-mono);
  font-size: 16px;
  line-height: 1.2;
  font-weight: var(--fw-semibold, 600);
}

.catalog-toolbar {
  max-width: 1240px;
  width: 100%;
  margin: 0 auto 10px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 8px 10px 8px 14px;
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  background: var(--surface);
  box-sizing: border-box;
}

.catalog-tabs {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  border-bottom: 1px solid var(--line);
  padding: 0;
  background: transparent;
}

.catalog-tab {
  position: relative;
  flex: 0 0 auto;
  min-width: 58px;
  height: 36px;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: var(--text-3);
  font: inherit;
  font-size: 13px;
  font-weight: var(--fw-medium, 500);
  white-space: nowrap;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 0 14px;
  transition: color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.catalog-tab:hover:not(.active) {
  color: var(--text);
}

.catalog-tab.active {
  color: var(--brand);
  font-weight: var(--fw-semibold, 600);
}

.catalog-tab.active::after {
  content: '';
  position: absolute;
  left: 6px;
  right: 6px;
  bottom: -1px;
  height: 2px;
  background: var(--brand);
  border-radius: 1px;
}

.catalog-tab-count {
  min-width: 18px;
  padding: 1px 6px;
  border-radius: var(--r-full, 999px);
  background: var(--surface-2);
  color: var(--text-3);
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 15px;
}

.catalog-tab.active .catalog-tab-count {
  background: var(--brand-soft);
  color: var(--brand);
}

.catalog-toolbar-right {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-shrink: 0;
}

.catalog-search {
  width: 220px;
}

.catalog-select {
  width: 132px;
}

.catalog-view-toggle {
  display: inline-flex;
  align-items: center;
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  background: var(--surface-2);
  padding: 2px;
  flex-shrink: 0;
}

.catalog-view-btn {
  width: 32px;
  height: 28px;
  border: 0;
  border-radius: var(--r-2, 6px);
  background: transparent;
  color: var(--text-3);
  display: grid;
  place-items: center;
  cursor: pointer;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.catalog-view-btn:hover:not(.active) {
  color: var(--text);
}

.catalog-view-btn.active {
  background: var(--surface);
  color: var(--brand);
  box-shadow: var(--sh-1);
}

.catalog-content {
  max-width: 1240px;
  width: 100%;
  margin: 0 auto;
}

.catalog-state {
  min-height: 340px;
  border: 1px solid var(--line);
  border-radius: var(--r-4, 12px);
  background: var(--surface);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-3);
  text-align: center;
}

.catalog-table {
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  background: var(--surface);
}

.catalog-table-head,
.catalog-row {
  display: grid;
  grid-template-columns:
    minmax(250px, 1.45fr)
    minmax(76px, 0.28fr)
    minmax(74px, 0.26fr)
    minmax(90px, 0.38fr)
    minmax(82px, 0.3fr)
    minmax(152px, 0.4fr);
  align-items: center;
  column-gap: 12px;
}

.catalog-table-head {
  min-height: 36px;
  padding: 0 16px;
  border-bottom: 1px solid var(--line);
  color: var(--text-3);
  font-size: 12px;
  font-weight: var(--fw-medium, 500);
  background: var(--surface-2);
}

.catalog-row {
  position: relative;
  min-height: 58px;
  padding: 8px 16px;
  border-bottom: 1px solid var(--line);
  color: var(--text);
  cursor: pointer;
  outline: none;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.catalog-row:last-child {
  border-bottom: 0;
}

.catalog-row:hover,
.catalog-row:focus-visible {
  background: color-mix(in srgb, var(--brand-soft) 28%, var(--surface));
}

.catalog-row::before {
  content: '';
  position: absolute;
  left: 0;
  top: 10px;
  bottom: 10px;
  width: 3px;
  border-radius: 0 var(--r-full, 999px) var(--r-full, 999px) 0;
  background: var(--brand);
  opacity: 0;
  transition: opacity 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.catalog-row:hover::before,
.catalog-row:focus-visible::before {
  opacity: 1;
}

.catalog-row:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: -2px;
}

.catalog-row-asset {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 10px;
}

.asset-avatar {
  width: 34px;
  height: 34px;
  flex: 0 0 auto;
  border-radius: var(--r-3, 8px);
  display: grid;
  place-items: center;
  background: var(--brand);
  color: var(--text-inverse, #fff);
  font-size: 12px;
  font-weight: var(--fw-bold, 700);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.18);
}

.asset-avatar.large {
  width: 44px;
  height: 44px;
  border-radius: var(--r-3, 8px);
  font-size: 18px;
}

.catalog-row-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.catalog-row-main strong,
.catalog-card h2 {
  min-width: 0;
  color: var(--text);
  font-weight: var(--fw-semibold, 600);
  letter-spacing: 0;
}

.catalog-row-main strong {
  font-size: 14px;
  line-height: 1.2;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.catalog-row-meta,
.catalog-card-code {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 7px;
  color: var(--text-3);
  font-size: 11.5px;
}

.catalog-row-meta code,
.catalog-card-code code {
  display: inline-block;
  max-width: min(100%, 220px);
  border-radius: var(--r-1, 4px);
  background: var(--surface-2);
  color: var(--text-3);
  padding: 2px 6px;
  font-family: var(--font-mono);
  font-size: 10.5px;
  line-height: 1.2;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}

.catalog-row-type,
.catalog-row-app,
.catalog-row-updated {
  min-width: 0;
  color: var(--text-3);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.catalog-type-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 22px;
  max-width: 100%;
  padding: 0 8px;
  border: 1px solid var(--line);
  border-radius: var(--r-2, 6px);
  background: var(--surface-2);
  color: var(--text-2);
  font-size: 11.5px;
  font-weight: var(--fw-semibold, 600);
  white-space: nowrap;
}

.catalog-type-pill[data-kind='backend'] {
  border-color: var(--brand-ring);
  background: var(--brand-soft);
  color: var(--brand);
}

.catalog-type-dot {
  width: 5px;
  height: 5px;
  border-radius: var(--r-full, 999px);
  background: currentColor;
  opacity: 0.72;
  flex: 0 0 auto;
}

.catalog-row-actions {
  display: flex;
  justify-content: flex-end;
  gap: 7px;
  flex-wrap: nowrap;
}

.catalog-card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(286px, 1fr));
  gap: 14px;
}

.catalog-card {
  min-height: 194px;
  border: 1px solid var(--line);
  border-radius: var(--r-4, 12px);
  background: var(--surface);
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  cursor: pointer;
  box-shadow: var(--sh-1);
  transition: border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              box-shadow 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              transform 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.catalog-card:hover {
  border-color: var(--brand-ring);
  box-shadow: var(--sh-2);
  transform: translateY(-1px);
}

.catalog-card-top,
.catalog-card-actions {
  display: flex;
  align-items: center;
}

.catalog-card-top {
  justify-content: space-between;
  gap: 10px;
}

.catalog-card h2 {
  margin: 2px 0 0;
  font-size: 16px;
  line-height: 1.35;
}

.catalog-card-code {
  flex-wrap: wrap;
}

.catalog-card-code > span {
  font-size: 12px;
}

.catalog-card-meta {
  padding-top: 10px;
  border-top: 1px solid var(--line);
  color: var(--text-3);
  font-size: 12px;
}

.catalog-card-actions {
  margin-top: auto;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.catalog-mini-action {
  min-width: 62px;
  height: 30px;
  min-height: 30px;
  border: 1px solid var(--line);
  border-radius: var(--r-2, 6px);
  background: var(--surface);
  color: var(--text);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 0 10px;
  box-sizing: border-box;
  font-family: inherit;
  font-size: 12px;
  line-height: 1;
  font-weight: var(--fw-semibold, 600);
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}
.catalog-mini-action:not(.primary) {
  border-color: color-mix(in srgb, var(--brand) 34%, var(--line));
}
.catalog-mini-action:not(.primary) :deep(svg) {
  color: var(--brand);
}

.catalog-mini-action:hover {
  border-color: var(--brand-ring);
  color: var(--brand);
  background: var(--brand-soft);
}

.catalog-mini-action.primary {
  min-width: 72px;
  background: var(--brand);
  border-color: var(--brand);
  color: var(--text-inverse, #fff);
}

.catalog-mini-action.primary:hover {
  background: var(--brand-hover);
  border-color: var(--brand-hover);
  color: var(--text-inverse, #fff);
}

.catalog-mini-action:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.catalog-mini-action:disabled :deep(.app-icon) {
  animation: catalog-spin 1s linear infinite;
}

@keyframes catalog-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.catalog-pagination {
  display: flex;
  justify-content: flex-end;
  max-width: 1240px;
  width: 100%;
  box-sizing: border-box;
  margin: 0 auto;
  padding: 16px 4px 4px;
}

@media (max-width: 860px) {
  .catalog-page {
    padding: 18px 16px 28px;
  }

  .catalog-header {
    align-items: stretch;
    flex-direction: column;
    gap: 16px;
    min-height: 176px;
    padding: 18px;
  }

  .catalog-header h1 {
    font-size: 24px;
    line-height: 1.18;
  }

  .catalog-header p {
    font-size: 12.5px;
    line-height: 1.45;
  }

  .catalog-header-side {
    align-items: stretch;
    flex-direction: column;
    margin-left: 0;
  }

  .catalog-import-action {
    width: 100%;
  }

  .catalog-summary {
    width: 100%;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    margin-left: 0;
  }

  .catalog-summary-item {
    min-width: 0;
    padding: 8px;
  }

  .catalog-summary-item strong {
    overflow: hidden;
    text-overflow: ellipsis;
    font-size: 13px;
  }

  .catalog-toolbar {
    align-items: stretch;
    flex-direction: column;
    padding: 10px;
  }

  .catalog-toolbar-right {
    flex-wrap: wrap;
    justify-content: flex-start;
  }

  .catalog-search,
  .catalog-select {
    width: min(100%, 220px);
  }

  .catalog-tabs {
    width: 100%;
    overflow-x: auto;
  }

  .catalog-table-head {
    display: none;
  }

  .catalog-table {
    border: 0;
    background: transparent;
    box-shadow: none;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .catalog-row {
    min-height: 0;
    border: 1px solid var(--line);
    border-radius: var(--r-4, 12px);
    background: var(--surface);
    grid-template-columns: 1fr;
    row-gap: 10px;
    padding: 12px;
  }

  .catalog-row-type,
  .catalog-row-status,
  .catalog-row-app,
  .catalog-row-updated,
  .catalog-row-actions {
    margin-left: 51px;
  }

  .catalog-row-meta {
    flex-wrap: wrap;
  }

  .catalog-row-meta code {
    max-width: 170px;
  }

  .catalog-row-actions {
    justify-content: flex-start;
    flex-wrap: wrap;
    width: calc(100% - 51px);
    box-sizing: border-box;
  }

  .catalog-row-actions .catalog-mini-action {
    flex: 1 1 96px;
  }
}


.catalog-bind-app {
  padding: 2px 8px;
  border: 1px dashed var(--line-strong, rgba(0, 0, 0, 0.18));
  border-radius: 6px;
  background: transparent;
  color: var(--fg-dim, #888);
  font-size: 12px;
  cursor: pointer;
}
.catalog-bind-app:hover {
  color: var(--brand-ink, var(--brand, #4f46e5));
  border-color: color-mix(in srgb, var(--brand, #4f6ef7) 45%, transparent);
}
.bind-dialog-hint { margin: 0 0 12px; font-size: 13px; color: var(--fg-dim, #666); }

.import-dialog-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.import-file-picker {
  width: 100%;
  min-height: 72px;
  padding: 14px;
  border: 1px dashed var(--line-strong, rgba(116, 128, 171, 0.34));
  border-radius: var(--r-3, 8px);
  background: color-mix(in srgb, var(--surface-2) 70%, transparent);
  color: var(--text);
  display: flex;
  align-items: center;
  gap: 12px;
  text-align: left;
  cursor: pointer;
}

.import-file-picker:hover {
  border-color: var(--brand);
  background: color-mix(in srgb, var(--brand-soft) 30%, var(--surface));
}

.import-file-text {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.import-file-text strong,
.import-file-text span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.import-file-text strong {
  font-size: 13px;
  font-weight: var(--fw-semibold, 600);
}

.import-file-text span {
  color: var(--text-3);
  font-size: 12px;
}

.import-file-input {
  display: none;
}
</style>
