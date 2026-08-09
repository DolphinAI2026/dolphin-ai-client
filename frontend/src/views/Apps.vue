<template>
  <BuilderFrame :breadcrumbs="[{ label: pageTitle }]">
    <main class="apps-page builder-page">
      <section class="apps-header page-head" aria-label="应用概览">
        <div class="apps-title-block">
          <h1 class="page-title">{{ pageTitle }}</h1>
          <p class="page-subtitle">{{ pageSubtitle }}</p>
        </div>
      </section>

      <section class="apps-toolbar" aria-label="应用筛选和视图切换">
        <div class="apps-status-filter">
          <span class="apps-filter-label">状态</span>
          <el-select
            v-model="activeTab"
            class="apps-status-select"
            size="small"
            aria-label="应用状态"
          >
            <el-option
              v-for="tab in tabs"
              :key="tab.value"
              :label="`${tab.label}（${tab.count}）`"
              :value="tab.value"
            />
          </el-select>
        </div>

        <div class="apps-toolbar-right">
          <el-input v-model="searchQ" placeholder="搜应用名 / 编码" clearable size="small" style="width: 200px" />
          <button v-if="!isCodeMode" class="btn btn-secondary apps-toolbar-action" type="button" @click="importDialogOpen = true">
            <el-icon><Download /></el-icon>
            <span>导入应用</span>
          </button>
          <button v-if="!isCodeMode" class="btn btn-primary apps-toolbar-action" type="button" @click="startNewApp">
            <el-icon><Plus /></el-icon>
            <span>{{ newAppLabel }}</span>
          </button>
          <button v-if="isCodeMode" class="btn btn-secondary apps-toolbar-action" type="button" @click="openSystemAssistant">
            <AppIcon name="sparkles" :size="14" />
            <span>系统助手</span>
          </button>
          <button v-if="isCodeMode" class="btn btn-primary apps-toolbar-action" type="button" @click="startNewCodeApp">
            <el-icon><Plus /></el-icon>
            <span>{{ codeApplicationSource === 'local' ? '新建本地应用' : '新建远程应用' }}</span>
          </button>
          <button v-if="isCodeMode" class="btn btn-secondary apps-toolbar-action" type="button" @click="refreshApps(true)">
            <el-icon><Refresh /></el-icon>
            <span>刷新</span>
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
        <div v-if="loading" class="apps-state apps-empty-v2">
          <SkeletonCard :lines="3" with-avatar with-footer />
        </div>
        <div v-else-if="codeListError" class="apps-state apps-source-error">
          <strong>{{ codeApplicationSource === 'local' ? '本地应用暂时无法加载' : '远程应用暂时无法加载' }}</strong>
          <span>{{ codeListError }}</span>
          <button class="btn btn-secondary btn-sm" type="button" @click="refreshApps(true)">重试</button>
        </div>
        <div v-else-if="filteredApps.length === 0" class="apps-state apps-empty-v2">
          <EmptyState
            :title="emptyTitle"
            :desc="emptyDesc"
          >
            <template #icon>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                <rect x="3" y="3" width="7" height="7"/>
                <rect x="14" y="3" width="7" height="7"/>
                <rect x="14" y="14" width="7" height="7"/>
                <rect x="3" y="14" width="7" height="7"/>
              </svg>
            </template>
            <template #cta>
              <button v-if="!isCodeMode" class="btn btn-primary btn-sm apps-empty-cta" type="button" @click="startNewApp">
                <el-icon><Plus /></el-icon>
                <span>{{ newAppLabel }}</span>
              </button>
              <button v-else class="btn btn-primary btn-sm apps-empty-cta" type="button" @click="startNewCodeApp">
                <el-icon><Plus /></el-icon>
                <span>{{ codeApplicationSource === 'local' ? '新建本地应用' : '新建远程应用' }}</span>
              </button>
            </template>
          </EmptyState>
        </div>

        <div v-else-if="viewMode === 'list'" class="apps-table">
          <div class="apps-table-head">
            <span>应用</span>
            <span>{{ isCodeMode ? '位置' : '组成' }}</span>
            <span>更新</span>
            <span class="apps-table-actions-head">操作</span>
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
                  <BaseTag v-if="isCodeMode" :tone="isLocalCodeApplication(app) ? 'neutral' : 'brand'">
                    {{ isLocalCodeApplication(app) ? '本地' : '远程' }}
                  </BaseTag>
                  <BaseTag v-else :tone="app.app_type === 'ai-code' ? 'brand' : 'neutral'">{{ app.app_type === 'ai-code' ? 'AI 代码' : '低代码' }}</BaseTag>
                  <template v-if="!isCodeMode && latestHistory(app)">
                    <span class="apps-dot-sep"></span>
                    <button class="apps-history-link" type="button" @click.stop="openLatestConversation(app)">
                      最近：{{ latestHistoryTitle(app) }}
                    </button>
                  </template>
                </span>
              </span>
            </div>

            <!-- Fix 14 (2026-05-21): 列表视图加 "组成" 一列展示模型/表单/角色/字典 4 项核心元数据，
                 解决"列表 vs 卡片信息密度落差"问题。无数据应用占位 - 不打扰阅读节奏。 -->
            <div class="apps-row-metrics">
              <span v-if="isCodeMode" class="apps-code-location" :title="codeApplicationLocation(app)">
                {{ codeApplicationLocation(app) }}
              </span>
              <template v-else-if="hasAppStats(app)">
                <span class="apps-metric-chip" :title="`${app.models || 0} 模型`"><strong>{{ app.models || 0 }}</strong>模型</span>
                <span class="apps-metric-chip" :title="`${app.forms || 0} 表单`"><strong>{{ app.forms || 0 }}</strong>表单</span>
                <span class="apps-metric-chip" :title="`${app.roles || 0} 角色`"><strong>{{ app.roles || 0 }}</strong>角色</span>
                <span class="apps-metric-chip" :title="`${app.dicts || 0} 字典`"><strong>{{ app.dicts || 0 }}</strong>字典</span>
              </template>
              <span v-else class="apps-metrics-empty">-</span>
            </div>

            <div class="apps-row-updated">{{ appUpdatedLabel(app) }}</div>

            <div class="apps-row-actions" @click.stop>
              <button class="apps-mini-action" type="button" @click="openDialog(app)">
                <AppIcon name="message" :size="13" />
                <span>{{ isCodeMode ? '打开' : '对话' }}</span>
              </button>
              <button v-if="!isCodeMode" class="apps-mini-action" type="button" @click="openDeliveryAssets(app)">
                <AppIcon name="files" :size="13" />
                <span>资产</span>
              </button>
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
              <BaseBadge :variant="stageBadgeVariant(app)">{{ appStage(app).label }}</BaseBadge>
            </div>
            <h2>{{ app.app_name }}</h2>
            <div class="apps-card-code">
              <code>{{ app.app_code || `app-${app.id}` }}</code>
              <BaseTag v-if="isCodeMode" :tone="isLocalCodeApplication(app) ? 'neutral' : 'brand'">
                {{ isLocalCodeApplication(app) ? '本地' : '远程' }}
              </BaseTag>
              <BaseTag v-else :tone="app.app_type === 'ai-code' ? 'brand' : 'neutral'">{{ app.app_type === 'ai-code' ? 'AI 代码' : '低代码' }}</BaseTag>
              <span>{{ appUpdatedLabel(app) }}</span>
            </div>
            <div v-if="isCodeMode" class="apps-card-location" :title="codeApplicationLocation(app)">
              {{ codeApplicationLocation(app) }}
            </div>
            <div v-if="hasAppStats(app)" class="apps-card-stats">
              <span>{{ app.models || 0 }} 模型</span>
              <span>{{ app.forms || 0 }} 表单</span>
              <span>{{ app.roles || 0 }} 角色</span>
              <span>{{ app.dicts || 0 }} 字典</span>
            </div>
            <button
              v-if="!isCodeMode && latestHistory(app)"
              class="apps-card-history"
              type="button"
              @click.stop="openLatestConversation(app)"
            >
              <span>{{ latestHistoryTitle(app) }}</span>
              <small>{{ latestHistoryMeta(app) }}</small>
            </button>
            <!-- Fix 15 (2026-05-21): 卡片 actions 区
                 - "对话" 主按钮 (primary blue)
                 - 阶段性次要动作: 构建/发布 (primary, 跟阶段挂钩)
                 - "⋯" 更多菜单: 查看 SPEC / 进入应用 / 删除 (ghost) -->
            <div class="apps-card-actions" @click.stop>
              <button class="apps-mini-action primary" type="button" @click="openDialog(app)">
                <AppIcon name="message" :size="13" />
                <span>{{ isCodeMode ? '打开' : '对话' }}</span>
              </button>
              <button v-if="!isCodeMode" class="apps-mini-action" type="button" @click="openDeliveryAssets(app)">
                <AppIcon name="files" :size="13" />
                <span>资产</span>
              </button>
              <button v-if="canBuildApp(app)" class="apps-mini-action" type="button" @click="buildApp(app)">构建</button>
              <button
                v-if="canPublishApp(app)"
                class="apps-mini-action"
                type="button"
                :disabled="isPublishingApp(app)"
                @click="publishApp(app)"
              >
                {{ isPublishingApp(app) ? '发布中' : '发布' }}
              </button>
              <el-dropdown
                v-if="hasCardMoreActions(app)"
                trigger="click"
                placement="bottom-end"
                @command="(cmd: 'spec' | 'platform' | 'history' | 'delete') => onCardMoreCommand(app, cmd)"
              >
                <button class="apps-mini-action apps-more-action" type="button" title="更多操作" aria-label="更多操作">
                  <el-icon><MoreFilled /></el-icon>
                </button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item v-if="canViewSpec(app)" command="spec">查看 SPEC</el-dropdown-item>
                    <el-dropdown-item v-if="canOpenInPlatform(app)" command="platform">进入应用 ↗</el-dropdown-item>
                    <el-dropdown-item v-if="canViewDeployHistory(app)" command="history"><AppIcon name="scroll" :size="14" /> 部署历史</el-dropdown-item>
                    <el-dropdown-item v-if="canDeleteApp(app)" command="delete" divided class="apps-more-danger">删除应用</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
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
    <ImportAppDialog v-if="!isCodeMode" v-model="importDialogOpen" @imported="refreshApps" />

    <!-- 2026-05-24: 部署历史抽屉 (Agent C 实现 + 主分支补卡片菜单入口) -->
    <DeployHistoryDrawer
      v-if="deployHistoryApp"
      v-model:open="deployHistoryOpen"
      :application-id="Number(deployHistoryApp.id)"
      :app-name="deployHistoryApp.app_name"
      @rolled-back="() => refreshApps()"
    />

    <el-drawer
      v-model="deliveryAssetsOpen"
      direction="rtl"
      size="min(520px, 100vw)"
      :with-header="false"
      :append-to-body="true"
    >
      <div class="apps-assets-drawer">
        <header class="apps-assets-head">
          <div>
            <span class="apps-assets-kicker">交付资产</span>
            <h2>{{ deliveryAssetsData?.app.app_name || deliveryAssetsApp?.app_name || '应用资产' }}</h2>
            <p>{{ deliveryAssetsSubtitle }}</p>
          </div>
          <button class="apps-assets-close" type="button" title="关闭" @click="deliveryAssetsOpen = false">
            ×
          </button>
        </header>

        <div v-if="deliveryAssetsLoading" class="apps-assets-loading">
          <SkeletonCard :lines="4" with-footer />
        </div>

        <template v-else-if="deliveryAssetsData">
          <div class="apps-assets-summary" aria-label="交付资产概览">
            <div v-for="section in deliveryAssetSections" :key="section.key" class="apps-assets-summary-item">
              <span>{{ section.label }}</span>
              <strong>{{ section.count }}</strong>
            </div>
          </div>

          <section
            v-for="section in deliveryAssetSections"
            :key="section.key"
            class="apps-assets-section"
          >
            <header>
              <span class="apps-assets-section-icon">
                <AppIcon :name="assetSectionIcon(section.key)" :size="15" />
              </span>
              <div>
                <h3>{{ section.label }}</h3>
                <p>{{ section.description }}</p>
              </div>
              <BaseBadge :variant="section.count ? 'info' : 'neutral'" size="sm">{{ section.count }}</BaseBadge>
              <button
                v-if="section.key === 'dev_workspaces'"
                class="apps-assets-section-link"
                type="button"
                @click="openWorkspaceCatalogForApp"
              >在资产库中查看</button>
            </header>

            <div v-if="section.items.length === 0" class="apps-assets-empty">暂无</div>

            <article
              v-for="item in section.items"
              :key="item.key"
              class="apps-assets-item"
            >
              <div class="apps-assets-item-main">
                <div class="apps-assets-item-title">
                  <strong>{{ item.title }}</strong>
                  <span v-if="assetItemMetaLabel(item)">{{ assetItemMetaLabel(item) }}</span>
                </div>
                <p v-if="item.preview">{{ item.preview }}</p>

                <dl v-if="item.kind === 'generated_summary'" class="apps-assets-kv">
                  <div><dt>模型</dt><dd>{{ item.meta?.models ?? 0 }}</dd></div>
                  <div><dt>表单</dt><dd>{{ item.meta?.forms ?? 0 }}</dd></div>
                  <div><dt>角色</dt><dd>{{ item.meta?.roles ?? 0 }}</dd></div>
                  <div><dt>字典</dt><dd>{{ item.meta?.dicts ?? 0 }}</dd></div>
                </dl>

                <ul v-if="Array.isArray(item.meta?.cases)" class="apps-assets-cases">
                  <li v-for="testCase in item.meta.cases" :key="testCase.title">
                    <strong>{{ testCase.title }}</strong>
                    <span>{{ testCase.expected }}</span>
                  </li>
                </ul>
              </div>

              <button
                v-if="canOpenDeliveryAssetItem(item)"
                class="apps-assets-item-action"
                type="button"
                @click="openDeliveryAssetItem(item)"
              >
                {{ deliveryAssetActionLabel(item) }}
              </button>
            </article>
          </section>
        </template>

        <div v-else class="apps-assets-empty state">暂无交付资产</div>
      </div>
    </el-drawer>

  </BuilderFrame>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Download, Grid, List, MoreFilled, Plus, Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import AppIcon from '@/components/common/AppIcon.vue'
import { handleError } from '@/utils/errorHandler'
import { isDesktop, openExternal } from '@/utils/desktop'
import { applicationApi, type ApplicationDeliveryAssetItem, type ApplicationDeliveryAssetsResponse } from '@/api/application'
import {
  codeRuntimeApi,
  type CodeApplication,
  type CodeApplicationSource,
} from '@/api/codeRuntime'
import { conversationApi, type ConversationWithApp } from '@/api/conversation'
import { useCodeApplicationsStore } from '@/stores/codeApplications'
import { isCodeRoutePath } from '@/stores/mode'
import { useUserStore } from '@/stores/user'
import BuilderFrame from '@/components/BuilderFrame.vue'
import ImportAppDialog from '@/components/ImportAppDialog.vue'
import DeployHistoryDrawer from '@/components/v2/DeployHistoryDrawer.vue'
import EmptyState from '@/components/states/EmptyState.vue'
import SkeletonCard from '@/components/states/SkeletonCard.vue'
import BaseBadge from '@/components/BaseBadge.vue'
import BaseTag from '@/components/BaseTag.vue'
import type { MergedApplication } from '@/types'

type AppTab = 'all' | 'active' | 'deployed' | 'draft'
type ViewMode = 'list' | 'card'
type AppStage = {
  group: Exclude<AppTab, 'all'>
  label: string
  tone: 'active' | 'success' | 'draft' | 'danger'
}

const router = useRouter()
const route = useRoute()
const user = useUserStore()
const codeApplications = useCodeApplicationsStore()
const apps = ref<MergedApplication[]>([])
const appHistoryMap = ref<Record<number, ConversationWithApp[]>>({})
const loading = ref(true)
const activeTab = ref<AppTab>('all')
const viewMode = ref<ViewMode>('list')
const searchQ = ref('')
const importDialogOpen = ref(false)
const publishingIds = ref<Set<number>>(new Set())
const codeListError = ref('')
const handledCodeCreateIntent = ref('')
let refreshAppsSeq = 0

const isCodeMode = computed(() => isCodeRoutePath(route.path))
const codeApplicationSources: Array<{ label: string; value: CodeApplicationSource }> = [
  { label: '本地应用', value: 'local' },
  { label: '远程应用', value: 'remote' },
]
const codeApplicationSource = ref<CodeApplicationSource>(
  'remote',
)
const pageTitle = computed(() => isCodeMode.value ? 'Code 应用' : '我的应用')
const pageSubtitle = computed(() =>
  isCodeMode.value
    ? (codeApplicationSource.value === 'local'
        ? '本机项目，点击应用直接进入 Code 工作台。'
        : '当前远程租户中的全代码应用。')
    : '统一查看低代码应用状态、资产组成和最近更新。',
)
const emptyTitle = computed(() => isCodeMode.value
  ? (codeApplicationSource.value === 'local' ? '暂无本地应用' : '暂无远程应用')
  : '暂无应用')
const emptyDesc = computed(() =>
  isCodeMode.value
    ? (codeApplicationSource.value === 'local'
        ? '创建本地应用后，会在这里继续开发。'
        : '当前远程租户中没有可见应用。')
    : '从首页新建应用后，会在这里继续构建、部署和查看历史对话。',
)
const newAppLabel = computed(() => '新建应用')

const tabDefinitions: Array<{ label: string; value: AppTab }> = [
  { label: '全部', value: 'all' },
  { label: '进行中', value: 'active' },
  { label: '已部署', value: 'deployed' },
  { label: '草稿', value: 'draft' },
]

// Fix 16 (2026-05-21): 扩展调色板 — 让每个应用图标按 (name|code|id) hash 落到不同颜色，
// 而不是被 stage tone 强行同色（之前 deployed 全绿、draft 全灰）。6 色覆盖蓝 / 绿 / 琥珀 /
// 青 / 珊瑚 / 紫，与 v3 token 调性吻合（不直接用 token 是因为 token 在 :root，inline
// style 无法解析 var()）。
const APP_ACCENTS = ['#1D4ED8', '#047857', '#B45309', '#0E7490', '#C2410C', '#7C3AED']

const tabs = computed(() =>
  tabDefinitions.map(tab => ({
    ...tab,
    count: apps.value.filter(app => matchesTab(app, tab.value)).length,
  })),
)

const filteredApps = computed(() => {
  const q = searchQ.value.trim().toLowerCase()
  return [...apps.value]
    .filter(app => matchesTab(app, activeTab.value))
    .filter(app => {
      if (!q) return true
      const name = (app.app_name || '').toLowerCase()
      const code = String((app as any).app_code || '').toLowerCase()
      return name.includes(q) || code.includes(q)
    })
    .sort((a, b) => appTimeMs(b.updated_at || b.created_at) - appTimeMs(a.updated_at || a.created_at))
})

// 分页：每页 10 个，切换 tab 时自动回第 1 页
const PAGE_SIZE = 10
const currentPage = ref(1)
const pagedApps = computed(() => {
  const start = (currentPage.value - 1) * PAGE_SIZE
  return filteredApps.value.slice(start, start + PAGE_SIZE)
})
watch([activeTab, searchQ], () => { currentPage.value = 1 })
// filteredApps 数量缩到当前页之外（比如删了某个 app）→ 回到合法页
watch(filteredApps, list => {
  const lastPage = Math.max(1, Math.ceil(list.length / PAGE_SIZE))
  if (currentPage.value > lastPage) currentPage.value = lastPage
})

const deployedCount = computed(() => apps.value.filter(app => appStage(app).group === 'deployed').length)
const activeCount = computed(() => apps.value.filter(app => appStage(app).group === 'active').length)

function startNewApp() {
  if (isCodeMode.value) {
    void startNewCodeApp()
    return
  }
  router.push('/')
}

function startNewCodeApp() {
  router.push('/code/new')
}

function openSystemAssistant() {
  router.push('/code/system-assistant')
}

async function handleLocalApplicationCreated(application: CodeApplication) {
  ElMessage.success('本地应用已创建')
  await refreshApps(true)
  await openCodeSessionForApp(application)
}

function clearCodeCreateQuery() {
  if (route.query.create == null) return
  const query = { ...route.query }
  delete query.create
  router.replace({ path: route.path, query }).catch(() => {})
}

async function handleCodeCreateIntent() {
  if (!isCodeMode.value || route.path !== '/code/apps' || route.query.create == null) return
  const raw = Array.isArray(route.query.create) ? route.query.create[0] : route.query.create
  const token = String(raw || '1')
  if (handledCodeCreateIntent.value === token) return
  handledCodeCreateIntent.value = token
  startNewCodeApp()
  clearCodeCreateQuery()
}

function isLocalCodeApplication(app: MergedApplication) {
  return app.source === 'desktop-local' || String((app as any).external_application_id || '').startsWith('local-')
}

function codeApplicationLocation(app: MergedApplication) {
  if (isLocalCodeApplication(app)) return String((app as any).local_workspace_path || '本地项目')
  const owner = (app as any).owner
  return String(owner?.displayName || owner?.name || '远程租户')
}

function matchesTab(app: MergedApplication, tab: AppTab) {
  if (tab === 'all') return true
  return appStage(app).group === tab
}

function appStage(app: MergedApplication): AppStage {
  if (app.local_status === 'completed' || app.apaas_app_id) {
    return { group: 'deployed', label: '部署', tone: 'success' }
  }
  if (app.local_status === 'generating') {
    return { group: 'active', label: '配置生成', tone: 'active' }
  }
  if (app.local_status === 'updating') {
    return { group: 'active', label: '更新中', tone: 'active' }
  }
  if (app.local_status === 'failed') {
    return { group: 'draft', label: '需求理解', tone: 'danger' }
  }
  // 有结构化数据 (config_preview 解析出 model/form/role/dict) = SPEC 已就绪，等部署
  // 之前误用"SPEC 设计"让用户以为还在设计，改成"待部署"更准确反映状态
  if (hasAppStats(app)) {
    return { group: 'active', label: '待部署', tone: 'active' }
  }
  return { group: 'draft', label: '需求理解', tone: 'draft' }
}

// stage tone → BaseBadge variant（纯展示映射，供模板用，保留 union 类型）
function stageBadgeVariant(app: MergedApplication): 'success' | 'warn' | 'error' | 'info' | 'neutral' {
  const tone = appStage(app).tone
  return tone === 'success' ? 'success'
    : tone === 'active' ? 'warn'
    : tone === 'danger' ? 'error'
    : 'neutral'
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

async function openCodeSessionForApp(app: MergedApplication) {
  const externalApplicationId = String((app as any).external_application_id || app.id || '').trim()
  if (!externalApplicationId) {
    ElMessage.warning('Code 应用缺少 applicationId')
    return
  }
  try {
    const created = await codeRuntimeApi.createSessionFromExternalApp({
      external_application_id: externalApplicationId,
      app_name: app.app_name,
      app_code: app.app_code,
    })
    window.dispatchEvent(new CustomEvent('code-rail-refresh'))
    router.push(`/code/${created.public_id}`)
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '创建 Code 会话失败')
  }
}

function openApp(app: MergedApplication) {
  if (isCodeMode.value) {
    void openCodeSessionForApp(app)
    return
  }
  // 打开应用进「应用工作室」(/chat?app_id) —— 低代码配置场景(表单/数据/流程/权限 + SPEC/部署)。
  // 二次开发(给该应用写代码)是应用内的上下文动作，不在这里入口。
  const query = appWorkspaceQuery(app)
  router.push({ path: '/chat', query })
}

function openDialog(app: MergedApplication) {
  if (isCodeMode.value) {
    void openCodeSessionForApp(app)
    return
  }
  // Builder 模式走跟 openApp 一样的 tab 化逻辑
  openApp(app)
}

/* ── Fix 15 (2026-05-21): 卡片视图 "更多" 菜单 ───────────────────────────
   "对话" 仍是主按钮 + 旁边 "⋯" 弹 ElDropdown，提供 3 项次要动作：
   - 查看 SPEC：跳 ChatPage tab=spec（hasDesignOutput 才显示）
   - 进入应用：apaas_url 存在则新开标签页进入 aPaaS（apaas_app_id 才显示）
   - 删除应用：canDeleteApp 才显示，触发原有 confirmDelete 二次确认
   每项 v-if 控制可见性，菜单本身只在至少有 1 个动作可执行时才挂出。  */
function canViewSpec(app: MergedApplication) {
  if (isCodeMode.value) return false
  return hasDesignOutput(app)
}

function openSpec(app: MergedApplication) {
  const appId = String(appNumericId(app) ?? app.id)
  const query: Record<string, string> = { app_id: appId, tab: 'spec' }
  if (isGeneratedApp(app)) query.workspace = 'update'
  router.push({ path: '/chat', query })
}

function canOpenInPlatform(app: MergedApplication) {
  if (isCodeMode.value) return false
  return Boolean(app.apaas_url)
}

function openInPlatform(app: MergedApplication) {
  if (!app.apaas_url) {
    ElMessage.info('该应用尚未部署到 aPaaS 平台')
    return
  }
  void openExternal(app.apaas_url)
}

function hasCardMoreActions(app: MergedApplication) {
  return canViewSpec(app) || canOpenInPlatform(app) || canViewDeployHistory(app) || canDeleteApp(app)
}

// 2026-05-24: 部署历史入口 (Agent C, 主分支补集成)
function canViewDeployHistory(app: MergedApplication) {
  if (isCodeMode.value) return false
  return app.source === 'local' && Boolean(app.id)
}

const deployHistoryOpen = ref(false)
const deployHistoryApp = ref<MergedApplication | null>(null)
const deliveryAssetsOpen = ref(false)
const deliveryAssetsLoading = ref(false)
const deliveryAssetsApp = ref<MergedApplication | null>(null)
const deliveryAssetsData = ref<ApplicationDeliveryAssetsResponse | null>(null)

const deliveryAssetSections = computed(() => deliveryAssetsData.value?.sections || [])
const deliveryAssetsSubtitle = computed(() => {
  const data = deliveryAssetsData.value
  if (!data) return '需求、设计、构建与验收资产'
  const total = Object.values(data.summary || {}).reduce((sum, count) => sum + Number(count || 0), 0)
  return `${total} 项资产 · ${data.app.app_code || '未命名编码'}`
})

function openDeployHistory(app: MergedApplication) {
  deployHistoryApp.value = app
  deployHistoryOpen.value = true
}

function onCardMoreCommand(app: MergedApplication, cmd: 'spec' | 'platform' | 'history' | 'delete') {
  if (cmd === 'spec') openSpec(app)
  else if (cmd === 'platform') openInPlatform(app)
  else if (cmd === 'history') openDeployHistory(app)
  else if (cmd === 'delete') confirmDelete(app)
}

async function openDeliveryAssets(app: MergedApplication) {
  const appId = appNumericId(app)
  if (appId == null) return
  deliveryAssetsApp.value = app
  deliveryAssetsOpen.value = true
  deliveryAssetsLoading.value = true
  deliveryAssetsData.value = null
  try {
    deliveryAssetsData.value = await applicationApi.getDeliveryAssets(appId)
  } catch (error) {
    handleError(error, { fallback: '交付资产加载失败' })
  } finally {
    deliveryAssetsLoading.value = false
  }
}

function assetSectionIcon(key: string) {
  if (key === 'dev_workspaces') return 'coding'
  if (key === 'requirements') return 'clipboard'
  if (key === 'design_docs') return 'file'
  if (key === 'ui_designs') return 'palette'
  if (key === 'build_inventory') return 'box'
  if (key === 'acceptance_cases') return 'check-circle'
  return 'files'
}

function assetItemMetaLabel(item: ApplicationDeliveryAssetItem) {
  const parts: string[] = []
  if (item.version) parts.push(`v${item.version}`)
  if (item.format) parts.push(String(item.format).toUpperCase())
  if (item.source === 'generated') parts.push('生成')
  return parts.join(' · ')
}

function canOpenDeliveryAssetItem(item: ApplicationDeliveryAssetItem) {
  if (item.kind === 'dev_workspace') return Boolean(item.meta?.workspace_id)
  return Boolean(item.kind === 'document_version' || item.meta?.session_id || item.meta?.conversation_id)
}

function deliveryAssetActionLabel(item: ApplicationDeliveryAssetItem) {
  if (item.kind === 'dev_workspace') return '打开工作区'
  if (item.kind === 'document_version') return '查看'
  if (item.meta?.session_id) return '对话'
  if (item.meta?.conversation_id) return '查看'
  return '打开'
}

function openWorkspaceCatalogForApp() {
  const app = deliveryAssetsApp.value
  if (!app) return
  router.push({ path: '/workspace-catalog', query: { app_id: String(appNumericId(app) ?? app.id) } })
}

function openDeliveryAssetItem(item: ApplicationDeliveryAssetItem) {
  const app = deliveryAssetsApp.value
  if (!app) return
  const appId = String(appNumericId(app) ?? app.id)
  if (item.kind === 'dev_workspace' && item.meta?.workspace_id) {
    // SP2b T9: 落统一外壳 /ai-chat 的 code 会话(不再走独立 /coding)。
    router.push({ path: '/ai-chat', query: { workspace_id: String(item.meta.workspace_id), mode: 'code' } })
    return
  }
  if (item.kind === 'document_version' || item.meta?.conversation_id) {
    router.push({ path: '/chat', query: { app_id: appId, tab: 'spec' } })
    return
  }
  if (item.meta?.session_id) {
    router.push({ path: `/ai-chat/${item.meta.session_id}`, query: { app_id: appId } })
  }
}

function hasDesignOutput(app: MergedApplication) {
  return Boolean(hasAppStats(app) || app.config_preview || app.canonical_spec_id || app.conversation_id)
}

function canBuildApp(app: MergedApplication) {
  if (isCodeMode.value) return false
  if (app.source !== 'local') return false
  if (app.apaas_app_id || app.local_status === 'completed') return false
  if (app.local_status === 'generating' || app.local_status === 'updating') return false
  return hasDesignOutput(app) || app.local_status === 'draft' || app.local_status === 'failed'
}

function buildApp(app: MergedApplication) {
  router.push({ path: '/chat', query: { deploy_app_id: String(app.id) } })
}

function canPublishApp(app: MergedApplication) {
  if (isCodeMode.value) return false
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
  // Fix 16 (2026-05-21): icon 颜色按 (app_name|app_code|id) hash 映射到 APP_ACCENTS
  // 6 色调色板，让不同应用的图标视觉可区分。只对 "失败" 这一种强信号保留红色（用户
  // 一眼能挑出风险应用），其余阶段（success/active/draft）全部按 hash 走调色板。
  if (appStage(app).tone === 'danger') return { background: '#d14a61' }
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

async function refreshApps(forceCode = false) {
  const seq = ++refreshAppsSeq
  const codeMode = isCodeMode.value
  const source = codeApplicationSource.value
  loading.value = true
  codeListError.value = ''
  try {
    const codeList = codeMode
      ? codeApplications.load(
          { tenantId: user.tenantId || 0, tenantEpoch: 0 },
          { source: codeApplicationSource.value, pageSize: 100 },
          { force: forceCode },
        )
      : applicationApi.list({ include_remote: false, app_type: 'low-code' })
    const [list, conversations] = await Promise.all([
      codeList,
      codeMode ? Promise.resolve([]) : conversationApi.listWithApps({ agent_type: 'builder' }).catch(() => []),
    ])
    if (seq !== refreshAppsSeq || codeMode !== isCodeMode.value || source !== codeApplicationSource.value) return
    apps.value = Array.isArray(list) ? list : (list?.items || [])
    appHistoryMap.value = buildAppHistoryMap(Array.isArray(conversations) ? conversations : [])
  } catch (error) {
    if (seq !== refreshAppsSeq || codeMode !== isCodeMode.value || source !== codeApplicationSource.value) return
    if (codeMode) {
      const typedError = error as any
      codeListError.value = typedError?.response?.data?.detail || typedError?.message || '应用列表加载失败'
      apps.value = []
    } else {
      handleError(error, { fallback: '应用列表加载失败' })
    }
  } finally {
    if (seq === refreshAppsSeq) loading.value = false
  }
}

onMounted(() => {
  void refreshApps()
  void handleCodeCreateIntent()
})
watch(isCodeMode, () => {
  activeTab.value = 'all'
  currentPage.value = 1
  void refreshApps()
})
watch(codeApplicationSource, source => {
  if (!isCodeMode.value) return
  if (isDesktop && source !== 'remote') {
    codeApplicationSource.value = 'remote'
    return
  }
  apps.value = []
  activeTab.value = 'all'
  currentPage.value = 1
  void refreshApps()
})
watch(() => route.fullPath, () => {
  void handleCodeCreateIntent()
})
</script>

<style scoped>
/* v3 redesign · 2026-05-20 — visual refresh only, template/script untouched.
   Preserved (don't change):
     - BuilderFrame wrap + apps-header / apps-toolbar / apps-content layout
     - 4 tabs (全部/进行中/已部署/草稿) + tab-count pill
     - list / card viewMode toggle + apps-table grid columns
     - apps-avatar inline appAccentStyle gradient (per-app accent color)
     - 4 stage tones (active / success / draft / danger) — appStage tone class
     - progress bar mirrors stage tone
     - el-pagination + ImportAppDialog
     - mobile @media (max-width: 860px) layout
     - .modal + .builder-btn legacy classes (used by other dialogs in this view)
   Refreshed:
     - v2 紫 (#5b5bd6 / #4357e8 / linear gradients) → v3 brand (--blue-700 #1D4ED8) single color
     - All --b-* aliases → v3 --surface / --line / --text / --brand
     - font-weight 750/760/850 → var(--fw-bold) 700 / 650 → var(--fw-semibold) 600
     - radius 7/8/10/12 → var(--r-2) 6 / var(--r-3) 8 / var(--r-4) 12
     - transition unified to 0.14s var(--ease)
     - stage-pill tone 4 colors mapped to v3 status tokens
     - progress fill tone mirrors stage with v3 status tokens
     - empty-state icon: glow gradient → flat brand-soft + brand border
     - mini-action.primary: --b-ink (dark grey) → --brand (blue)
     - dark theme block dropped legacy gradient overrides (v3 tokens auto-handle dark)
*/

.apps-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 20px 28px 32px;
}

.apps-header {
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

.apps-title-block {
  min-width: 0;
}

.apps-header h1 {
  margin: 0;
  color: var(--text);
  font-size: 28px;
  line-height: 1.12;
  font-weight: var(--fw-bold, 700);
  letter-spacing: 0;
}

.apps-header p {
  margin: 8px 0 0;
  color: var(--text-3);
  font-size: 13px;
}

.apps-source-switch {
  flex: 0 0 auto;
  display: inline-grid;
  grid-template-columns: repeat(2, minmax(92px, 1fr));
  min-height: 36px;
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  background: var(--surface-2);
  padding: 2px;
}

.apps-source-switch button {
  min-width: 0;
  border: 0;
  border-radius: var(--r-2, 6px);
  background: transparent;
  color: var(--text-3);
  padding: 0 14px;
  font: inherit;
  font-size: 13px;
  font-weight: var(--fw-medium, 500);
  cursor: pointer;
}

.apps-source-switch button:hover:not(.active) {
  color: var(--text);
}

.apps-source-switch button.active {
  background: var(--surface);
  color: var(--brand);
  font-weight: var(--fw-semibold, 600);
  box-shadow: var(--sh-1);
}

.apps-toolbar {
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
}

.apps-toolbar-right {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-shrink: 0;
}

.apps-toolbar-action {
  height: 36px;
  padding: 0 16px;
  border-radius: var(--r-3, 8px);
  font-size: 13px;
  font-weight: var(--fw-semibold, 600);
}

/* ── Status filter ────────────────────────────────────────── */
.apps-status-filter {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
}

.apps-filter-label {
  color: var(--text-3);
  font-size: 12px;
  font-weight: var(--fw-medium, 500);
}

.apps-status-select {
  width: 156px;
}

.apps-status-select :deep(.el-select__wrapper) {
  min-height: 36px;
  border-radius: var(--r-3, 8px);
}

/* ── View toggle (list / card) ────────────────────────────── */
.apps-view-toggle {
  display: inline-flex;
  align-items: center;
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  background: var(--surface-2);
  padding: 2px;
  flex-shrink: 0;
}

.apps-view-btn {
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

.apps-view-btn:hover:not(.active) {
  color: var(--text);
}

.apps-view-btn.active {
  background: var(--surface);
  color: var(--brand);
  box-shadow: var(--sh-1);
}

.apps-content {
  max-width: 1240px;
  width: 100%;
  margin: 0 auto;
}

/* ── Empty / loading state ────────────────────────────────── */
.apps-state {
  min-height: 340px;
  border: 1px solid var(--line);
  border-radius: var(--r-4, 12px);
  background: var(--surface);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--text-3);
  font-size: 13px;
  text-align: center;
}

.apps-state strong {
  color: var(--text);
  font-size: 14.5px;
  font-weight: var(--fw-semibold, 600);
}

.apps-source-error span {
  max-width: min(560px, calc(100% - 40px));
  overflow-wrap: anywhere;
}

.apps-source-error .btn {
  margin-top: 8px;
}

.apps-state-icon {
  width: 56px;
  height: 56px;
  border-radius: var(--r-full, 999px);
  display: grid;
  place-items: center;
  background: var(--surface-2);
  color: var(--text-3);
  margin-bottom: 4px;
}

.apps-state-icon svg {
  width: 22px;
  height: 22px;
}

.apps-state-icon rect {
  fill: currentColor;
}

/* ── List view: table ─────────────────────────────────────── */
.apps-table {
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  background: var(--surface);
}

.apps-table-head,
.apps-row {
  display: grid;
  /* 列表视图优先保证应用名、组成数据和右侧操作在分屏宽度下稳定单行。 */
  grid-template-columns:
    minmax(260px, 1.55fr)  /* 应用 */
    minmax(180px, 0.9fr)   /* 组成 */
    76px                   /* 更新 */
    max-content;           /* 操作 */
  align-items: center;
  column-gap: 10px;
}

.apps-table-head {
  min-height: 40px;
  padding: 0 14px;
  border-bottom: 1px solid var(--line);
  color: var(--text-3);
  font-size: 12px;
  font-weight: var(--fw-medium, 500);
  background: var(--surface-2);
}

.apps-row {
  min-height: 64px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--line);
  color: var(--text);
  cursor: pointer;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
  outline: none;
}

.apps-row:last-child {
  border-bottom: 0;
}

.apps-row:hover,
.apps-row:focus-visible {
  background: color-mix(in srgb, var(--brand-soft) 28%, var(--surface));
}

.apps-row-app {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 11px;
}

/* avatar — appAccentStyle inline gradient drives the color via per-app accent;
   we set a fallback brand so the box never collapses when style is missing. */
.apps-avatar {
  width: 40px;
  height: 40px;
  flex: 0 0 auto;
  border-radius: var(--r-3, 8px);
  display: grid;
  place-items: center;
  background: var(--brand);
  color: var(--text-inverse, #fff);
  font-size: 13px;
  font-weight: var(--fw-bold, 700);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.18);
}

.apps-avatar.large {
  width: 44px;
  height: 44px;
  border-radius: var(--r-3, 8px);
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
  color: var(--text);
  font-size: 15px;
  font-weight: var(--fw-semibold, 600);
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
  color: var(--text-3);
  font-size: 12px;
}

.apps-row-meta code,
.apps-card-code code {
  border-radius: var(--r-1, 4px);
  background: var(--surface-2);
  color: var(--text-3);
  padding: 2px 6px;
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.2;
}

.apps-dot-sep {
  width: 3px;
  height: 3px;
  border-radius: var(--r-full, 999px);
  background: var(--text-4);
}

.apps-history-link {
  min-width: 0;
  border: 0;
  background: transparent;
  color: var(--brand);
  font: inherit;
  font-size: 12px;
  padding: 0;
  cursor: pointer;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.apps-history-link:hover {
  color: var(--brand-hover);
  text-decoration: underline;
}

/* ── Fix 14 (2026-05-21): 列表视图 "组成" 列 — 紧凑展示 M/F/R/D 4 项 ───── */
.apps-row-metrics {
  min-width: 0;
  display: flex;
  align-items: center;
  flex-wrap: nowrap;
  gap: 3px;
  color: var(--text-3);
  font-size: 11px;
  line-height: 1.4;
}

.apps-code-location,
.apps-card-location {
  min-width: 0;
  color: var(--text-3);
  font-family: var(--font-mono);
  font-size: 11.5px;
  line-height: 1.45;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.apps-code-location {
  display: block;
  max-width: 100%;
}

.apps-metric-chip {
  display: inline-flex;
  align-items: baseline;
  gap: 3px;
  padding: 2px 5px;
  border-radius: var(--r-1, 4px);
  background: var(--surface-2);
  color: var(--text-3);
  font-size: 10.5px;
  white-space: nowrap;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.apps-row:hover .apps-metric-chip {
  background: var(--surface);
}

.apps-metric-chip strong {
  color: var(--text);
  font-family: var(--font-mono);
  font-weight: var(--fw-semibold, 600);
  font-size: 10.5px;
  line-height: 1;
}

.apps-metrics-empty {
  color: var(--text-4);
  font-family: var(--font-mono);
  font-size: 12px;
}

.apps-row-updated {
  color: var(--text-3);
  font-size: 12.5px;
}

.apps-row-actions {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 0;
  flex-wrap: nowrap;
  min-width: 0;
  justify-self: end;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: var(--r-2, 6px);
  background: var(--surface);
}

.apps-table-actions-head {
  text-align: right;
}

/* ── Card view ────────────────────────────────────────────── */
.apps-card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(286px, 1fr));
  gap: 14px;
}

.apps-card {
  min-height: 240px;
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

.apps-card:hover {
  border-color: var(--brand-ring);
  box-shadow: var(--sh-2);
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
  color: var(--text);
  font-size: 16px;
  line-height: 1.35;
  font-weight: var(--fw-semibold, 600);
  letter-spacing: 0;
}

.apps-card-code {
  gap: 8px;
  color: var(--text-3);
  font-size: 12px;
}

.apps-card-location {
  width: 100%;
  border-top: 1px solid var(--line);
  padding-top: 10px;
}

.apps-card-stats {
  gap: 12px;
  flex-wrap: wrap;
  padding-top: 10px;
  border-top: 1px solid var(--line);
  color: var(--text-3);
  font-size: 11.5px;
}

.apps-card-history {
  width: 100%;
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  background: var(--surface-2);
  padding: 9px 10px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 3px;
  color: var(--text);
  text-align: left;
  cursor: pointer;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.apps-card-history:hover {
  background: var(--brand-soft);
  border-color: var(--brand-ring);
}

.apps-card-history span {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  font-weight: var(--fw-medium, 500);
}

.apps-card-history small {
  color: var(--text-3);
  font-size: 11.5px;
}

.apps-card-actions {
  margin-top: auto;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

/* ── Mini action buttons (对话 / 构建 / 发布 / 删除) ───────── */
.apps-mini-action {
  min-height: 30px;
  border: 1px solid var(--line);
  border-radius: var(--r-2, 6px);
  background: var(--surface);
  color: var(--text-2);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 0 10px;
  font-family: inherit;
  font-size: 12px;
  font-weight: var(--fw-medium, 500);
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.apps-row-actions .apps-mini-action {
  min-width: 0;
  height: 28px;
  min-height: 28px;
  border: 0;
  border-radius: 0;
  background: transparent;
  padding: 0 8px;
  gap: 4px;
  font-size: 11.5px;
}

.apps-row-actions .apps-mini-action + .apps-mini-action {
  border-left: 1px solid var(--line);
}

.apps-row-actions .apps-mini-action.primary {
  border-radius: 0;
}

.apps-mini-action:hover {
  border-color: var(--brand-ring);
  color: var(--brand);
  background: var(--brand-soft);
}

.apps-mini-action span {
  display: inline-flex;
  align-items: center;
}

.apps-mini-action.primary {
  background: var(--brand);
  border-color: var(--brand);
  color: var(--text-inverse, #fff);
}

.apps-mini-action.primary:hover {
  background: var(--brand-hover);
  border-color: var(--brand-hover);
  color: var(--text-inverse, #fff);
}

.apps-mini-action.danger {
  color: var(--err);
  border-color: var(--line);
  background: var(--surface);
}

.apps-mini-action.danger:hover {
  color: var(--err);
  background: var(--err-soft);
  border-color: var(--err-soft);
}

.apps-mini-action:disabled {
  cursor: not-allowed;
  opacity: 0.55;
  transform: none;
}

/* Fix 15 (2026-05-21): "⋯" 更多操作按钮 — 正方形 ghost icon button */
.apps-mini-action.apps-more-action {
  width: 30px;
  min-width: 30px;
  padding: 0;
  color: var(--text-3);
}

.apps-mini-action.apps-more-action:hover {
  color: var(--brand);
}

.apps-mini-action.apps-more-action .el-icon {
  font-size: 16px;
}

/* "删除应用" 菜单项标红 */
:deep(.apps-more-danger) {
  color: var(--err);
}
:deep(.apps-more-danger:hover) {
  color: var(--err);
  background: var(--err-soft);
}

.apps-pagination {
  display: flex;
  justify-content: flex-end;
  padding: 16px 4px 4px;
}

/* ── Delivery assets drawer ───────────────────────────────── */
.apps-assets-drawer {
  min-height: 100%;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 20px;
  background: var(--bg);
  color: var(--text);
}

.apps-assets-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--line);
}

.apps-assets-kicker {
  color: var(--brand);
  font-size: 12px;
  font-weight: var(--fw-semibold, 600);
}

.apps-assets-head h2 {
  margin: 4px 0 0;
  color: var(--text);
  font-size: 20px;
  line-height: 1.25;
  font-weight: var(--fw-bold, 700);
  letter-spacing: 0;
}

.apps-assets-head p {
  margin: 6px 0 0;
  color: var(--text-3);
  font-size: 12.5px;
}

.apps-assets-close {
  width: 30px;
  height: 30px;
  border: 1px solid var(--line);
  border-radius: var(--r-2, 6px);
  background: var(--surface);
  color: var(--text-3);
  display: grid;
  place-items: center;
  cursor: pointer;
  font-size: 20px;
  line-height: 1;
}

.apps-assets-close:hover {
  border-color: var(--brand-ring);
  color: var(--brand);
  background: var(--brand-soft);
}

.apps-assets-loading {
  padding: 8px 0;
}

.apps-assets-summary {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
}

.apps-assets-summary-item {
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  background: var(--surface);
  padding: 9px 8px;
}

.apps-assets-summary-item span {
  display: block;
  color: var(--text-3);
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.apps-assets-summary-item strong {
  display: block;
  margin-top: 4px;
  color: var(--text);
  font-family: var(--font-mono);
  font-size: 16px;
  line-height: 1;
}

.apps-assets-section {
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  background: var(--surface);
  overflow: hidden;
}

.apps-assets-section > header {
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  gap: 10px;
  padding: 12px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-2);
}

.apps-assets-section-icon {
  width: 28px;
  height: 28px;
  border-radius: var(--r-2, 6px);
  display: grid;
  place-items: center;
  background: var(--surface);
  color: var(--brand);
  border: 1px solid var(--line);
}

.apps-assets-section h3 {
  margin: 0;
  color: var(--text);
  font-size: 13.5px;
  line-height: 1.2;
  font-weight: var(--fw-semibold, 600);
}

.apps-assets-section p {
  margin: 3px 0 0;
  color: var(--text-3);
  font-size: 11.5px;
  line-height: 1.35;
}

.apps-assets-empty {
  padding: 16px;
  color: var(--text-4);
  font-size: 12px;
  text-align: center;
}

.apps-assets-empty.state {
  border: 1px solid var(--line);
  border-radius: var(--r-3, 8px);
  background: var(--surface);
}

.apps-assets-item {
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: start;
  gap: 12px;
  padding: 12px;
  border-bottom: 1px solid var(--line);
}

.apps-assets-item:last-child {
  border-bottom: 0;
}

.apps-assets-item-main {
  min-width: 0;
}

.apps-assets-item-title {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.apps-assets-item-title strong {
  min-width: 0;
  color: var(--text);
  font-size: 13px;
  font-weight: var(--fw-semibold, 600);
  line-height: 1.25;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.apps-assets-item-title span {
  flex: 0 0 auto;
  color: var(--text-4);
  font-size: 11px;
  font-family: var(--font-mono);
}

.apps-assets-item p {
  margin: 6px 0 0;
  color: var(--text-3);
  font-size: 12px;
  line-height: 1.5;
}

.apps-assets-section-link {
  flex: none;
  margin-left: 8px;
  padding: 2px 8px;
  border: none;
  background: transparent;
  color: var(--brand-ink, var(--brand, #4f46e5));
  font-size: 12px;
  cursor: pointer;
  border-radius: 6px;
}
.apps-assets-section-link:hover { background: var(--brand-soft, rgba(79, 110, 247, 0.08)); }

.apps-assets-item-action {
  min-height: 28px;
  border: 1px solid var(--line);
  border-radius: var(--r-2, 6px);
  background: var(--surface);
  color: var(--text-2);
  padding: 0 10px;
  font-family: inherit;
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
}

.apps-assets-item-action:hover {
  border-color: var(--brand-ring);
  color: var(--brand);
  background: var(--brand-soft);
}

.apps-code-create {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.apps-code-create label {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.apps-code-create label > span {
  color: var(--text-2);
  font-size: 12px;
  font-weight: var(--fw-semibold, 600);
}

.apps-assets-kv {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin: 10px 0 0;
}

.apps-assets-kv div {
  border-radius: var(--r-2, 6px);
  background: var(--surface-2);
  padding: 7px 8px;
}

.apps-assets-kv dt {
  color: var(--text-3);
  font-size: 11px;
}

.apps-assets-kv dd {
  margin: 3px 0 0;
  color: var(--text);
  font-family: var(--font-mono);
  font-size: 14px;
  font-weight: var(--fw-semibold, 600);
}

.apps-assets-cases {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 10px 0 0;
  padding: 0;
  list-style: none;
}

.apps-assets-cases li {
  border-left: 2px solid var(--brand-ring);
  padding-left: 9px;
}

.apps-assets-cases strong {
  display: block;
  color: var(--text);
  font-size: 12.5px;
  font-weight: var(--fw-semibold, 600);
}

.apps-assets-cases span {
  display: block;
  margin-top: 2px;
  color: var(--text-3);
  font-size: 12px;
  line-height: 1.45;
}

/* ── Responsive ───────────────────────────────────────────── */
@media (max-width: 1120px) {
  .apps-table-head {
    display: none;
  }

  .apps-table {
    border: 0;
    background: transparent;
    box-shadow: none;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .apps-row {
    min-height: 0;
    border: 1px solid var(--line);
    border-radius: var(--r-4, 12px);
    background: var(--surface);
    grid-template-columns: 1fr;
    row-gap: 10px;
    padding: 12px;
  }

  .apps-row-metrics,
  .apps-row-updated,
  .apps-row-actions {
    margin-left: 43px;
  }

  .apps-row-metrics {
    flex-wrap: wrap;
  }

  .apps-row-actions {
    justify-content: flex-start;
    flex-wrap: wrap;
  }
}

@media (max-width: 860px) {
  .apps-page {
    padding: 18px 16px 28px;
  }

  .apps-header {
    align-items: stretch;
    flex-direction: column;
    gap: 16px;
    min-height: 0;
    padding: 18px;
  }

  .apps-source-switch {
    width: 100%;
  }

  .apps-toolbar {
    align-items: stretch;
    flex-direction: column;
    padding: 10px;
  }

  .apps-toolbar-right {
    flex-wrap: wrap;
    justify-content: flex-start;
  }

  .apps-status-filter {
    width: 100%;
  }

  .apps-status-select {
    flex: 1;
    width: auto;
  }

  .apps-view-toggle {
    align-self: auto;
  }

}

/* ── Legacy modal (kept for any inline dialogs still using these classes) ── */
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(11, 27, 63, 0.55);
  backdrop-filter: blur(6px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 28px;
}
.modal {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-4, 12px);
  min-width: min(480px, calc(100vw - 32px));
  max-width: min(960px, calc(100vw - 32px));
  max-height: min(86vh, 820px);
  overflow: auto;
  box-shadow: var(--sh-4);
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
  border-bottom: 1px solid var(--line);
}
.modal-header h3 {
  margin: 0;
  color: var(--text);
  font-size: 16px;
  font-weight: var(--fw-semibold, 600);
}
.builder-btn {
  height: 32px;
  padding: 0 12px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--text);
  border-radius: var(--r-2, 6px);
  font: inherit;
  font-size: 12.5px;
  font-weight: var(--fw-medium, 500);
  cursor: pointer;
}
.builder-btn-primary {
  background: var(--brand);
  color: var(--text-inverse, #fff);
  border-color: var(--brand);
}
.builder-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ── Page head ────────────────────────────────────────────── */
.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 6px;
}

.page-title {
  margin: 0;
  font-size: var(--t-h2, 24px);
  font-weight: var(--fw-bold, 700);
  letter-spacing: 0;
  line-height: 1.2;
  color: var(--text);
}

.page-subtitle {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--text-3);
}

/* ── Buttons ──────────────────────────────────────────────── */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 32px;
  padding: 0 14px;
  border-radius: var(--r-3, 8px);
  font-family: inherit;
  font-size: 13px;
  font-weight: var(--fw-medium, 500);
  cursor: pointer;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text);
  transition: background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.btn-sm {
  height: 28px;
  padding: 0 12px;
  font-size: 12.5px;
  border-radius: var(--r-2, 6px);
}

.btn-primary {
  background: var(--brand);
  color: var(--text-inverse, #fff);
  border-color: var(--brand);
}

.btn-primary:hover {
  background: var(--brand-hover);
  border-color: var(--brand-hover);
}

.btn-secondary {
  background: var(--surface);
  color: var(--text-2);
  border-color: var(--line);
}

.btn-secondary:hover {
  background: var(--brand-soft);
  border-color: var(--brand-ring);
  color: var(--brand);
}

.apps-new-btn {
  /* Sit in BuilderFrame's #actions slot — sized to match the existing topbar height. */
  height: 32px;
}

.apps-empty-v2 {
  border-style: dashed;
  border-color: var(--line-strong);
  background: var(--surface);
  padding: 36px 24px;
}

.apps-empty-v2 strong {
  font-size: 14.5px;
  font-weight: var(--fw-semibold, 600);
  color: var(--text);
}

.apps-empty-v2 > span {
  color: var(--text-3);
  font-size: 13px;
  max-width: 360px;
}

.apps-empty-cta {
  margin-top: 14px;
}

/* ── Dark theme polish (rely mostly on v3 token cascade) ──── */
html[data-theme="dark"] .apps-row:hover,
html[data-theme="dark"] .apps-row:focus-visible {
  background: var(--surface-2);
}

html[data-theme="dark"] .apps-card:hover {
  border-color: var(--brand-ring);
}

html[data-theme="dark"] .apps-mini-action:hover {
  background: var(--brand-soft);
  color: var(--brand);
}

/* ── Phase 6 · table density + filter UX tightening (append-only) ──
   Apps.vue is a div-based custom table (not el-table). We tighten
   typography rhythm so it matches the el-table density in sibling pages
   (PlatformTenants / TenantUsers / DbConnections). All changes are
   visual-only via class selectors that already exist in the template. */

/* Header row — small, semibold, letter-spaced — matches v3 spec for
   el-table thead th. Original .apps-table-head sets fw-medium 500 +
   12px; tighten to 11.5px + 600 + letter-spacing 0.02em + uppercase
   color text-2 so the column labels read as labels, not body. */
.apps-table-head {
  font-size: 11.5px;
  font-weight: var(--fw-semibold, 600);
  letter-spacing: 0;
  color: var(--text-2);
  text-transform: none;
}

/* Tighter cell padding to match the 10-14px rhythm used by el-table cells.
   Original .apps-row uses 8px 14px which is already close; just align
   the head to the same horizontal padding for visual continuity. */
.apps-table-head {
  padding-left: 14px;
  padding-right: 14px;
}

/* Toolbar tabs row — wrap into a boxed filter-bar style only if the
   container is .apps-toolbar (already exists). Don't add background
   chrome (the tabs already sit on the page surface) but tighten the
   right-side cluster gap rhythm. */
.apps-toolbar {
  align-items: center;
}
.apps-toolbar-right {
  gap: 8px;          /* was 10px; matches v3 cluster rhythm */
}
</style>
