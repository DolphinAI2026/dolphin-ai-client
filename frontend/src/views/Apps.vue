<template>
  <BuilderFrame :breadcrumbs="[{ label: '应用' }]">
    <main class="apps-page builder-page">
      <section class="apps-header page-head">
        <div>
          <h1 class="page-title">我的应用</h1>
          <p class="page-subtitle">{{ appsSummary }}</p>
        </div>
      </section>

      <section class="apps-toolbar" aria-label="应用筛选和视图切换">
        <div class="apps-tabs" role="tablist" aria-label="应用状态">
          <button
            v-for="tab in tabs"
            :key="tab.value"
            class="apps-tab"
            :class="{ active: activeTab === tab.value }"
            type="button"
            role="tab"
            :aria-selected="activeTab === tab.value"
            @click="activeTab = tab.value"
          >
            <span>{{ tab.label }}</span>
            <span v-if="tab.count" class="apps-tab-count">{{ tab.count }}</span>
          </button>
        </div>

        <div class="apps-toolbar-right">
          <button class="btn btn-secondary apps-toolbar-action" type="button" @click="importDialogOpen = true">
            <el-icon><Download /></el-icon>
            <span>导入应用</span>
          </button>
          <button class="btn btn-primary apps-toolbar-action" type="button" @click="router.push('/')">
            <el-icon><Plus /></el-icon>
            <span>新建应用</span>
          </button>

          <div class="apps-view-toggle" aria-label="视图切换">
            <button
              class="apps-view-btn"
              :class="{ active: viewMode === 'list' }"
              type="button"
              title="列表视图"
              @click="viewMode = 'list'"
            >
              <el-icon><List /></el-icon>
            </button>
            <button
              class="apps-view-btn"
              :class="{ active: viewMode === 'card' }"
              type="button"
              title="卡片视图"
              @click="viewMode = 'card'"
            >
              <el-icon><Grid /></el-icon>
            </button>
          </div>
        </div>
      </section>

      <section class="apps-content" :class="`is-${viewMode}`">
        <div v-if="loading" class="apps-state">加载中...</div>
        <div v-else-if="filteredApps.length === 0" class="apps-state apps-empty-v2">
          <span class="apps-state-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none">
              <rect x="4" y="4" width="6" height="6" rx="1.4" />
              <rect x="14" y="4" width="6" height="6" rx="1.4" />
              <rect x="4" y="14" width="6" height="6" rx="1.4" />
              <rect x="14" y="14" width="6" height="6" rx="1.4" />
            </svg>
          </span>
          <strong>暂无应用</strong>
          <span>从首页新建应用后，会在这里继续构建、部署和查看历史对话。</span>
          <button class="btn btn-primary btn-sm apps-empty-cta" type="button" @click="router.push('/')">
            <el-icon><Plus /></el-icon>
            <span>新建应用</span>
          </button>
        </div>

        <div v-else-if="viewMode === 'list'" class="apps-table">
          <div class="apps-table-head">
            <span>应用</span>
            <span>阶段</span>
            <span>进度</span>
            <span>更新</span>
            <span aria-hidden="true"></span>
          </div>

          <div
            v-for="app in pagedApps"
            :key="app.id"
            class="apps-row"
            role="button"
            tabindex="0"
            @click="openApp(app)"
            @keyup.enter="openApp(app)"
          >
            <div class="apps-row-app">
              <span class="apps-avatar" :style="appAccentStyle(app)">{{ appIconInitial(app) }}</span>
              <span class="apps-row-main">
                <strong>{{ app.app_name }}</strong>
                <span class="apps-row-meta">
                  <code>{{ app.app_code || `app-${app.id}` }}</code>
                  <template v-if="latestHistory(app)">
                    <span class="apps-dot-sep"></span>
                    <button class="apps-history-link" type="button" @click.stop="openLatestConversation(app)">
                      最近：{{ latestHistoryTitle(app) }}
                    </button>
                  </template>
                </span>
              </span>
            </div>

            <div class="apps-row-stage">
              <span class="apps-stage-pill" :class="appStage(app).tone">{{ appStage(app).label }}</span>
            </div>

            <div class="apps-row-progress">
              <span class="apps-progress-track">
                <span class="apps-progress-bar" :class="appStage(app).tone" :style="{ width: `${appProgress(app)}%` }"></span>
              </span>
              <span>{{ appProgress(app) }}%</span>
            </div>

            <div class="apps-row-updated">{{ appUpdatedLabel(app) }}</div>

            <div class="apps-row-actions" @click.stop>
              <button class="apps-mini-action" type="button" @click="openDialog(app)">对话</button>
              <button v-if="canBuildApp(app)" class="apps-mini-action primary" type="button" @click="buildApp(app)">构建</button>
              <button
                v-if="canPublishApp(app)"
                class="apps-mini-action primary"
                type="button"
                :disabled="isPublishingApp(app)"
                @click="publishApp(app)"
              >
                {{ isPublishingApp(app) ? '发布中' : '发布' }}
              </button>
              <button v-if="canDeleteApp(app)" class="apps-mini-action danger" type="button" @click="confirmDelete(app)">删除</button>
            </div>
          </div>
        </div>

        <div v-else class="apps-card-grid">
          <article
            v-for="app in pagedApps"
            :key="app.id"
            class="apps-card"
            @click="openApp(app)"
          >
            <div class="apps-card-top">
              <span class="apps-avatar large" :style="appAccentStyle(app)">{{ appIconInitial(app) }}</span>
              <span class="apps-stage-pill" :class="appStage(app).tone">{{ appStage(app).label }}</span>
            </div>
            <h2>{{ app.app_name }}</h2>
            <div class="apps-card-code">
              <code>{{ app.app_code || `app-${app.id}` }}</code>
              <span>{{ appUpdatedLabel(app) }}</span>
            </div>
            <div class="apps-card-progress">
              <span class="apps-progress-track">
                <span class="apps-progress-bar" :class="appStage(app).tone" :style="{ width: `${appProgress(app)}%` }"></span>
              </span>
              <span>{{ appProgress(app) }}%</span>
            </div>
            <div v-if="hasAppStats(app)" class="apps-card-stats">
              <span>{{ app.models || 0 }} 模型</span>
              <span>{{ app.forms || 0 }} 表单</span>
              <span>{{ app.roles || 0 }} 角色</span>
              <span>{{ app.dicts || 0 }} 字典</span>
            </div>
            <button
              v-if="latestHistory(app)"
              class="apps-card-history"
              type="button"
              @click.stop="openLatestConversation(app)"
            >
              <span>{{ latestHistoryTitle(app) }}</span>
              <small>{{ latestHistoryMeta(app) }}</small>
            </button>
            <div class="apps-card-actions" @click.stop>
              <button class="apps-mini-action" type="button" @click="openDialog(app)">对话</button>
              <button v-if="canBuildApp(app)" class="apps-mini-action primary" type="button" @click="buildApp(app)">构建</button>
              <button
                v-if="canPublishApp(app)"
                class="apps-mini-action primary"
                type="button"
                :disabled="isPublishingApp(app)"
                @click="publishApp(app)"
              >
                {{ isPublishingApp(app) ? '发布中' : '发布' }}
              </button>
              <button v-if="canDeleteApp(app)" class="apps-mini-action danger" type="button" @click="confirmDelete(app)">删除</button>
            </div>
          </article>
        </div>

        <!-- 分页：超过 1 页才显示，列表 / 卡片视图共用 -->
        <div v-if="filteredApps.length > PAGE_SIZE" class="apps-pagination">
          <el-pagination
            v-model:current-page="currentPage"
            :page-size="PAGE_SIZE"
            :total="filteredApps.length"
            layout="total, prev, pager, next, jumper"
            background
            small
          />
        </div>
      </section>
    </main>

    <!-- 导入应用弹窗 -->
    <ImportAppDialog v-model="importDialogOpen" @imported="refreshApps" />

  </BuilderFrame>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Download, Grid, List, Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { handleError } from '@/utils/errorHandler'
import { applicationApi } from '@/api/application'
import { conversationApi, type ConversationWithApp } from '@/api/conversation'
import BuilderFrame from '@/components/BuilderFrame.vue'
import ImportAppDialog from '@/components/ImportAppDialog.vue'
import type { MergedApplication } from '@/types'

type AppTab = 'all' | 'active' | 'deployed' | 'draft'
type ViewMode = 'list' | 'card'
type AppStage = {
  group: Exclude<AppTab, 'all'>
  label: string
  tone: 'active' | 'success' | 'draft' | 'danger'
  progress: number
}

const router = useRouter()
const apps = ref<MergedApplication[]>([])
const appHistoryMap = ref<Record<number, ConversationWithApp[]>>({})
const loading = ref(true)
const activeTab = ref<AppTab>('all')
const viewMode = ref<ViewMode>('list')
const importDialogOpen = ref(false)
const publishingIds = ref<Set<number>>(new Set())

const tabDefinitions: Array<{ label: string; value: AppTab }> = [
  { label: '全部', value: 'all' },
  { label: '进行中', value: 'active' },
  { label: '已部署', value: 'deployed' },
  { label: '草稿', value: 'draft' },
]

const APP_ACCENTS = ['#5871e8', '#2aa871', '#d28b16', '#14aeb8', '#e35a49', '#8a65d9']

const tabs = computed(() =>
  tabDefinitions.map(tab => ({
    ...tab,
    count: apps.value.filter(app => matchesTab(app, tab.value)).length,
  })),
)

const filteredApps = computed(() => {
  return [...apps.value]
    .filter(app => matchesTab(app, activeTab.value))
    .sort((a, b) => appTimeMs(b.updated_at || b.created_at) - appTimeMs(a.updated_at || a.created_at))
})

// 分页：每页 10 个，切换 tab 时自动回第 1 页
const PAGE_SIZE = 10
const currentPage = ref(1)
const pagedApps = computed(() => {
  const start = (currentPage.value - 1) * PAGE_SIZE
  return filteredApps.value.slice(start, start + PAGE_SIZE)
})
watch(activeTab, () => { currentPage.value = 1 })
// filteredApps 数量缩到当前页之外（比如删了某个 app）→ 回到合法页
watch(filteredApps, list => {
  const lastPage = Math.max(1, Math.ceil(list.length / PAGE_SIZE))
  if (currentPage.value > lastPage) currentPage.value = lastPage
})

const deployedCount = computed(() => apps.value.filter(app => appStage(app).group === 'deployed').length)
const activeCount = computed(() => apps.value.filter(app => appStage(app).group === 'active').length)
const appsSummary = computed(() => `${apps.value.length} 个应用 · ${deployedCount.value} 个已部署 · ${activeCount.value} 个进行中`)

function matchesTab(app: MergedApplication, tab: AppTab) {
  if (tab === 'all') return true
  return appStage(app).group === tab
}

function appStage(app: MergedApplication): AppStage {
  if (app.local_status === 'completed' || app.apaas_app_id) {
    return { group: 'deployed', label: '部署', tone: 'success', progress: 100 }
  }
  if (app.local_status === 'generating') {
    return { group: 'active', label: '配置生成', tone: 'active', progress: 76 }
  }
  if (app.local_status === 'updating') {
    return { group: 'active', label: '更新中', tone: 'active', progress: 62 }
  }
  if (app.local_status === 'failed') {
    return { group: 'draft', label: '需求理解', tone: 'danger', progress: 18 }
  }
  if (hasAppStats(app)) {
    return { group: 'active', label: 'SPEC 设计', tone: 'active', progress: 42 }
  }
  return { group: 'draft', label: '需求理解', tone: 'draft', progress: 12 }
}

function appProgress(app: MergedApplication) {
  return appStage(app).progress
}

function normalizeTimestamp(value?: string | null) {
  if (!value) return ''
  const normalized = String(value).trim()
  const hasTimezone = /(?:z|[+-]\d{2}:?\d{2})$/i.test(normalized)
  const isDateTime = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(normalized)
  return isDateTime && !hasTimezone ? `${normalized.replace(' ', 'T')}Z` : normalized
}

function appTimeMs(value?: string | null) {
  const normalized = normalizeTimestamp(value)
  if (!normalized) return 0
  const time = new Date(normalized).getTime()
  return Number.isFinite(time) ? time : 0
}

function hasAppStats(app: MergedApplication) {
  return Boolean((app.models || 0) + (app.forms || 0) + (app.roles || 0) + (app.dicts || 0))
}

function appNumericId(app: MergedApplication) {
  const raw = Number(app.id)
  return Number.isFinite(raw) ? raw : null
}

function isGeneratedApp(app: MergedApplication) {
  return Boolean(
    app.apaas_app_id ||
    app.local_status === 'completed' ||
    app.status === 'completed'
  )
}

function appWorkspaceQuery(app: MergedApplication) {
  const appId = String(appNumericId(app) ?? app.id)
  if (isGeneratedApp(app)) {
    return { app_id: appId, tab: 'spec', workspace: 'update' }
  }
  return { app_id: appId }
}

function openApp(app: MergedApplication) {
  // WorkspaceShell is not a complete editing surface yet. Keep the primary
  // application entry on ChatPage, which owns app-scoped SPEC/edit/deploy flow.
  router.push({ path: '/chat', query: appWorkspaceQuery(app) })
}

function openDialog(app: MergedApplication) {
  router.push({ path: '/chat', query: appWorkspaceQuery(app) })
}

function hasDesignOutput(app: MergedApplication) {
  return Boolean(hasAppStats(app) || app.config_preview || app.canonical_spec_id || app.conversation_id)
}

function canBuildApp(app: MergedApplication) {
  if (app.source !== 'local') return false
  if (app.apaas_app_id || app.local_status === 'completed') return false
  if (app.local_status === 'generating' || app.local_status === 'updating') return false
  return hasDesignOutput(app) || app.local_status === 'draft' || app.local_status === 'failed'
}

function buildApp(app: MergedApplication) {
  router.push({ path: '/chat', query: { deploy_app_id: String(app.id) } })
}

function canPublishApp(app: MergedApplication) {
  return app.source === 'local' && Boolean(app.apaas_app_id)
}

function isPublishingApp(app: MergedApplication) {
  const appId = appNumericId(app)
  return appId != null && publishingIds.value.has(appId)
}

async function publishApp(app: MergedApplication) {
  const appId = appNumericId(app)
  if (appId == null || isPublishingApp(app)) return
  publishingIds.value = new Set([...publishingIds.value, appId])
  try {
    await applicationApi.publish(appId)
    ElMessage.success('已发布')
    await refreshApps()
  } catch (error) {
    handleError(error, { fallback: '发布失败' })
  } finally {
    const next = new Set(publishingIds.value)
    next.delete(appId)
    publishingIds.value = next
  }
}

function openConversation(app: MergedApplication, item?: ConversationWithApp) {
  if (!item) return
  router.push(`/chat/${item.id}?app_id=${app.id}`)
}

function latestHistory(app: MergedApplication) {
  return appHistory(app)[0] || null
}

function openLatestConversation(app: MergedApplication) {
  openConversation(app, latestHistory(app) || undefined)
}

function latestHistoryTitle(app: MergedApplication) {
  const item = latestHistory(app)
  return item ? historyTitle(item) : ''
}

function latestHistoryMeta(app: MergedApplication) {
  const item = latestHistory(app)
  return item ? `${historySummary(item)} · ${historyTime(item)}` : ''
}

function appHistory(app: MergedApplication) {
  const id = appNumericId(app)
  if (id == null) return []
  return appHistoryMap.value[id] || []
}

function historyTitle(item: ConversationWithApp) {
  return item.title || item.app_name || '历史对话'
}

function historyTime(item: ConversationWithApp) {
  return relativeTime(item.updated_at || item.created_at)
}

function historySummary(item: ConversationWithApp) {
  const count = Number(item.message_count || 0)
  return count > 0 ? `${count} 条消息` : '无消息详情'
}

function buildAppHistoryMap(list: ConversationWithApp[]) {
  const next: Record<number, ConversationWithApp[]> = {}
  for (const item of list) {
    const appId = Number(item.app_id)
    if (!Number.isFinite(appId)) continue
    if (!next[appId]) next[appId] = []
    next[appId].push(item)
  }
  for (const key of Object.keys(next)) {
    const items = next[Number(key)] || []
    next[Number(key)] = items
      .sort((a, b) => appTimeMs(b.updated_at || b.created_at) - appTimeMs(a.updated_at || a.created_at))
      .slice(0, 3)
  }
  return next
}

function nameHash(name: string): number {
  let h = 0
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0
  return h
}

function appIconInitial(app: MergedApplication): string {
  const appName = String(app.app_name || '').trim()
  const appCode = String(app.app_code || '').trim()
  const source = appName || appCode || 'A'
  const chars = Array.from(source)
  const first = chars.find(char => char.trim()) || 'A'
  return /[a-z]/.test(first) ? first.toUpperCase() : first
}

function appAccentStyle(app: MergedApplication) {
  const stage = appStage(app)
  if (stage.tone === 'draft') return { background: '#aab5c5' }
  if (stage.tone === 'danger') return { background: '#d14a61' }
  if (stage.tone === 'success') return { background: '#2aa871' }
  const seed = app.app_name || app.app_code || String(app.id)
  return { background: APP_ACCENTS[nameHash(seed) % APP_ACCENTS.length] }
}

function appUpdatedLabel(app: MergedApplication) {
  return relativeTime(app.updated_at || app.created_at)
}

function relativeTime(value?: string | null) {
  if (!value) return '-'
  const time = appTimeMs(value)
  if (!Number.isFinite(time)) return String(value).slice(0, 16)
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

function canDeleteApp(app: MergedApplication) {
  if (app.source !== 'local') return false
  if (app.apaas_app_id || app.local_status === 'completed') return false
  return app.local_status !== 'generating' && app.local_status !== 'updating'
}

function deleteTooltip(app: MergedApplication) {
  if (canDeleteApp(app)) return '删除'
  if (app.source !== 'local') return '平台应用不允许删除'
  if (app.apaas_app_id || app.local_status === 'completed' || app.local_status === 'generating' || app.local_status === 'updating') return '已构建应用不允许删除'
  return '当前状态不允许删除'
}

async function confirmDelete(app: MergedApplication) {
  if (!canDeleteApp(app)) {
    ElMessage.warning(deleteTooltip(app))
    return
  }
  try {
    await ElMessageBox.confirm(`确定删除「${app.app_name}」？此操作不可恢复。`, '删除应用', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await applicationApi.delete(Number(app.id))
    apps.value = apps.value.filter(item => item.id !== app.id)
    ElMessage.success('已删除')
  } catch (error: any) {
    if (error === 'cancel' || error === 'close' || error?.action === 'cancel' || error?.action === 'close') return
    handleError(error, { fallback: '删除失败' })
  }
}

async function refreshApps() {
  loading.value = true
  try {
    const [list, conversations] = await Promise.all([
      applicationApi.list({ include_remote: false }),
      conversationApi.listWithApps({ agent_type: 'builder' }).catch(() => []),
    ])
    apps.value = Array.isArray(list) ? list : []
    appHistoryMap.value = buildAppHistoryMap(Array.isArray(conversations) ? conversations : [])
  } catch (error) {
    handleError(error, { fallback: '应用列表加载失败' })
  } finally {
    loading.value = false
  }
}

onMounted(() => { refreshApps() })
</script>

<style scoped>
.apps-create-btn {
  height: 34px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border: 1px solid #4357e8;
  border-radius: 10px;
  background: linear-gradient(135deg, #5a6cff, #4154e8);
  color: #fff;
  padding: 0 14px;
  font-size: 12px;
  font-weight: 760;
  cursor: pointer;
  box-shadow: 0 10px 22px rgba(65, 84, 232, 0.20);
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}

.apps-create-btn:hover {
  transform: translateY(-1px);
  background: linear-gradient(135deg, #6677ff, #4b5df2);
  box-shadow: 0 14px 28px rgba(65, 84, 232, 0.26);
}

:global(html[data-theme="dark"]) .apps-create-btn,
:global(html[data-theme="dark"]) .apps-mini-action.primary {
  background: linear-gradient(135deg, #7b88ff, #5265ff) !important;
  border-color: rgba(154, 168, 255, 0.48) !important;
  color: #ffffff !important;
  box-shadow: 0 12px 26px rgba(82, 101, 255, 0.30) !important;
}

:global(html[data-theme="dark"]) .apps-create-btn:hover,
:global(html[data-theme="dark"]) .apps-mini-action.primary:hover {
  background: linear-gradient(135deg, #8a96ff, #6273ff) !important;
  border-color: rgba(181, 190, 255, 0.62) !important;
  color: #ffffff !important;
}

.apps-pagination {
  display: flex;
  justify-content: flex-end;
  padding: 16px 4px 4px;
}

.apps-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 22px 28px 32px;
}

.apps-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  max-width: 1160px;
  width: 100%;
  margin: 0 auto;
}

.apps-header h1 {
  margin: 0;
  color: var(--b-text);
  font-size: 24px;
  line-height: 1.25;
  font-weight: 750;
  letter-spacing: 0;
}

.apps-header p {
  margin: 6px 0 0;
  color: var(--b-text-muted);
  font-size: 13px;
}

.apps-toolbar {
  max-width: 1160px;
  width: 100%;
  margin: 8px auto 2px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.apps-toolbar-right {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-shrink: 0;
}

.apps-toolbar-action {
  height: 40px;
  padding: 0 18px;
  border-radius: 10px;
  font-size: 15px;
  font-weight: 760;
}

.apps-tabs,
.apps-view-toggle {
  display: inline-flex;
  align-items: center;
  border: 1px solid var(--b-line);
  border-radius: var(--b-radius-md);
  background: var(--b-bg-sub);
  padding: 2px;
}

.apps-tab {
  min-width: 58px;
  height: 30px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--b-text-muted);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 0 10px;
}

.apps-tab.active {
  background: var(--b-panel);
  color: var(--b-text);
  font-weight: 650;
  box-shadow: var(--b-shadow-xs);
}

.apps-tab-count {
  min-width: 18px;
  padding: 1px 6px;
  border-radius: 999px;
  background: var(--b-brand-soft);
  color: var(--b-brand);
  font-family: var(--b-mono);
  font-size: 11px;
  line-height: 15px;
}

.apps-view-toggle {
  flex-shrink: 0;
}

.apps-view-btn {
  width: 32px;
  height: 26px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--b-text-muted);
  display: grid;
  place-items: center;
  cursor: pointer;
}

.apps-view-btn.active {
  background: var(--b-panel);
  color: var(--b-text);
  box-shadow: var(--b-shadow-xs);
}

.apps-content {
  max-width: 1160px;
  width: 100%;
  margin: 0 auto;
}

.apps-state {
  min-height: 340px;
  border: 1px solid var(--b-line);
  border-radius: var(--b-radius-md);
  background: var(--b-panel);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--b-text-muted);
  font-size: 13px;
  text-align: center;
}

.apps-state strong {
  color: var(--b-text);
  font-size: 14px;
}

.apps-state-icon {
  width: 38px;
  height: 38px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  background: linear-gradient(180deg, var(--brand, #6d5df6), var(--brand-hover, #5b4ee6));
  color: #fff;
  box-shadow: 0 14px 28px var(--brand-ring, rgba(109, 93, 246, 0.18));
}

.apps-state-icon svg {
  width: 20px;
  height: 20px;
}

.apps-state-icon rect {
  fill: currentColor;
}

.apps-table {
  overflow: hidden;
  border: 1px solid var(--b-line);
  border-radius: var(--b-radius-md);
  background: var(--b-panel);
}

.apps-table-head,
.apps-row {
  display: grid;
  grid-template-columns: minmax(320px, 1.35fr) minmax(120px, 0.58fr) minmax(150px, 0.58fr) minmax(110px, 0.45fr) minmax(360px, 0.9fr);
  align-items: center;
  column-gap: 18px;
}

.apps-table-head {
  min-height: 32px;
  padding: 0 12px;
  border-bottom: 1px solid var(--b-line);
  color: var(--b-text-muted);
  font-size: 13px;
}

.apps-row {
  min-height: 56px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--b-line);
  color: var(--b-text);
  cursor: pointer;
  transition: background 0.15s ease;
  outline: none;
}

.apps-row:last-child {
  border-bottom: 0;
}

.apps-row:hover,
.apps-row:focus-visible {
  background: var(--b-panel-soft);
}

.apps-row-app {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 11px;
}

.apps-avatar {
  width: 30px;
  height: 30px;
  flex: 0 0 auto;
  border-radius: 7px;
  display: grid;
  place-items: center;
  color: #fff;
  font-size: 13px;
  font-weight: 750;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.18);
}

.apps-avatar.large {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  font-size: 18px;
}

.apps-row-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.apps-row-main strong {
  min-width: 0;
  color: var(--b-text);
  font-size: 14px;
  font-weight: 700;
  line-height: 1.2;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.apps-row-meta {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 7px;
  color: var(--b-text-muted);
  font-size: 12px;
}

.apps-row-meta code,
.apps-card-code code {
  border-radius: 4px;
  background: var(--b-bg-sub);
  color: var(--b-text-muted);
  padding: 2px 5px;
  font-family: var(--b-mono);
  font-size: 11px;
  line-height: 1;
}

.apps-dot-sep {
  width: 3px;
  height: 3px;
  border-radius: 999px;
  background: var(--b-text-faint);
}

.apps-history-link {
  min-width: 0;
  border: 0;
  background: transparent;
  color: var(--b-text-muted);
  font: inherit;
  font-size: 12px;
  padding: 0;
  cursor: pointer;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.apps-history-link:hover {
  color: var(--b-text);
}

.apps-stage-pill {
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--b-line);
  border-radius: 6px;
  background: var(--b-bg-sub);
  color: var(--b-text-muted);
  padding: 0 9px;
  font-size: 12px;
  font-weight: 650;
  white-space: nowrap;
}

.apps-stage-pill.active {
  background: var(--b-brand-soft);
  color: var(--b-brand-ink);
  border-color: rgba(79, 110, 247, 0.18);
}

.apps-stage-pill.success {
  background: var(--b-teal-soft);
  color: var(--b-teal);
  border-color: rgba(15, 159, 143, 0.16);
}

.apps-stage-pill.danger {
  background: var(--b-red-soft);
  color: var(--b-red);
  border-color: rgba(209, 74, 97, 0.16);
}

.apps-row-progress,
.apps-card-progress {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 9px;
  color: var(--b-text-muted);
  font-family: var(--b-mono);
  font-size: 12px;
}

.apps-progress-track {
  width: 80px;
  height: 3px;
  border-radius: 999px;
  background: var(--b-bg-sub);
  overflow: hidden;
}

.apps-progress-bar {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--b-ink);
}

.apps-progress-bar.active {
  background: var(--b-ink);
}

.apps-progress-bar.success {
  background: var(--b-teal);
}

.apps-progress-bar.draft {
  background: #aab5c5;
}

.apps-progress-bar.danger {
  background: var(--b-red);
}

.apps-row-updated {
  color: var(--b-text-muted);
  font-size: 13px;
}

.apps-row-actions {
  display: flex;
  justify-content: flex-end;
  gap: 9px;
  flex-wrap: wrap;
}

.apps-card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(286px, 1fr));
  gap: 14px;
}

.apps-card {
  min-height: 240px;
  border: 1px solid var(--b-line);
  border-radius: var(--b-radius-md);
  background: var(--b-panel);
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  cursor: pointer;
  transition: border-color 0.15s ease, box-shadow 0.15s ease, transform 0.15s ease;
}

.apps-card:hover {
  border-color: var(--b-line-strong);
  box-shadow: var(--b-shadow-sm);
  transform: translateY(-1px);
}

.apps-card-top,
.apps-card-actions,
.apps-card-code,
.apps-card-stats {
  display: flex;
  align-items: center;
}

.apps-card-top {
  justify-content: space-between;
  gap: 10px;
}

.apps-card h2 {
  margin: 2px 0 0;
  color: var(--b-text);
  font-size: 16px;
  line-height: 1.35;
  font-weight: 750;
}

.apps-card-code {
  gap: 8px;
  color: var(--b-text-muted);
  font-size: 12px;
}

.apps-card-stats {
  gap: 11px;
  flex-wrap: wrap;
  padding-top: 10px;
  border-top: 1px solid var(--b-line);
  color: var(--b-text-muted);
  font-size: 12px;
}

.apps-card-history {
  width: 100%;
  border: 1px solid var(--b-line);
  border-radius: var(--b-radius-md);
  background: var(--b-panel-soft);
  padding: 9px 10px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 3px;
  color: var(--b-text);
  text-align: left;
  cursor: pointer;
}

.apps-card-history span {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}

.apps-card-history small {
  color: var(--b-text-muted);
  font-size: 12px;
}

.apps-card-actions {
  margin-top: auto;
  justify-content: flex-end;
  gap: 9px;
  flex-wrap: wrap;
}

.apps-mini-action {
  min-height: 36px;
  border: 1px solid var(--b-line);
  border-radius: 8px;
  background: var(--b-panel);
  color: var(--b-text-muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 0 15px;
  font-family: inherit;
  font-size: 14px;
  font-weight: 650;
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease, transform 0.15s ease;
}

.apps-mini-action:hover {
  border-color: var(--b-line-strong);
  color: var(--b-text);
  background: var(--b-bg-sub);
  transform: translateY(-1px);
}

.apps-mini-action span {
  display: inline-flex;
  align-items: center;
}

.apps-mini-action.primary {
  background: var(--b-ink);
  border-color: var(--b-ink);
  color: #fff;
}

.apps-mini-action.danger {
  color: var(--b-red);
}

.apps-mini-action:disabled {
  cursor: not-allowed;
  opacity: 0.62;
  transform: none;
}

@media (max-width: 860px) {
  .apps-page {
    padding: 18px 16px 28px;
  }

  .apps-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .apps-toolbar-right {
    flex-wrap: wrap;
    justify-content: flex-start;
  }

  .apps-tabs {
    width: 100%;
    overflow-x: auto;
  }

  .apps-view-toggle {
    align-self: auto;
  }

  .apps-table-head {
    display: none;
  }

  .apps-table {
    border: 0;
    background: transparent;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .apps-row {
    min-height: 0;
    border: 1px solid var(--b-line);
    border-radius: var(--b-radius-md);
    background: var(--b-panel);
    grid-template-columns: 1fr;
    row-gap: 10px;
    padding: 12px;
  }

  .apps-row-stage,
  .apps-row-progress,
  .apps-row-updated,
  .apps-row-actions {
    margin-left: 41px;
  }

  .apps-row-actions {
    justify-content: flex-start;
  }
}

/* Phase A: members dialog */
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(3, 7, 18, 0.64);
  backdrop-filter: blur(6px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 28px;
}
.modal {
  background: var(--b-panel);
  border: 1px solid var(--b-line);
  border-radius: var(--b-radius-md);
  min-width: min(480px, calc(100vw - 32px));
  max-width: min(960px, calc(100vw - 32px));
  max-height: min(86vh, 820px);
  overflow: auto;
  box-shadow: var(--b-shadow-lg);
}
.modal-large {
  width: min(960px, calc(100vw - 32px));
}
.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 14px;
  padding: 16px 18px;
  border-bottom: 1px solid var(--b-line);
}
.modal-header h3 {
  margin: 0;
  color: var(--b-text);
  font-size: 16px;
  font-weight: 750;
}
.builder-btn {
  height: 32px;
  padding: 0 12px;
  border: 1px solid var(--b-line);
  background: var(--b-bg-sub);
  color: var(--b-text);
  border-radius: var(--b-radius-sm);
  font: inherit;
  font-size: 12px;
  font-weight: 650;
  cursor: pointer;
}
.builder-btn-primary {
  background: var(--b-brand);
  color: #070a12;
  border-color: var(--b-brand);
}
.builder-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* --- v2 visual refresh: header + empty state + primary button (Task 6.2). Logic untouched. --- */
.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 6px;
}

.page-title {
  margin: 0;
  font-size: 22px;
  font-weight: 600;
  letter-spacing: -0.02em;
  line-height: 1.2;
  color: var(--text, var(--b-text));
}

.page-subtitle {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--text-2, var(--b-text-muted));
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 32px;
  padding: 0 14px;
  border-radius: 8px;
  font-family: inherit;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text, var(--b-text));
  transition: filter 0.15s ease, box-shadow 0.15s ease, transform 0.15s ease;
}

.btn-sm {
  height: 26px;
  padding: 0 10px;
  font-size: 12px;
  border-radius: 6px;
}

.btn-primary {
  background: var(--brand, #5b5bd6);
  color: #fff;
}

.btn-primary:hover {
  filter: brightness(1.06);
  box-shadow: 0 6px 16px rgba(91, 91, 214, 0.18);
}

.btn-secondary {
  background: var(--surface, var(--b-panel));
  color: var(--text, var(--b-text));
  border-color: var(--border, var(--b-line));
}

.btn-secondary:hover {
  background: var(--b-bg-sub);
  border-color: var(--b-line-strong);
}

.apps-new-btn {
  /* Sit in BuilderFrame's #actions slot — sized to match the existing topbar height. */
  height: 32px;
}

.apps-empty-v2 {
  border-style: dashed;
  border-color: var(--border-strong, var(--b-line-strong));
  background: var(--surface, var(--b-panel));
  padding: 32px 24px;
}

.apps-empty-cta {
  margin-top: 14px;
}
</style>
