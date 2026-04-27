<template>
  <WorkbenchShell>
    <div class="catalog-main">
      <div class="filter-bar">
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
        <div class="view-toggle">
          <button :class="['toggle-btn', { active: viewMode === 'grid' }]" @click="viewMode = 'grid'" title="卡片视图">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>
          </button>
          <button :class="['toggle-btn', { active: viewMode === 'list' }]" @click="viewMode = 'list'" title="列表视图">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
          </button>
        </div>
      </div>

      <div class="catalog-content" :class="viewMode">
        <div v-if="loading" class="empty-state">加载中...</div>
        <div v-else-if="filteredWorkspaces.length === 0" class="empty-state">暂无组件</div>

        <template v-else-if="viewMode === 'grid'">
          <article
            v-for="ws in filteredWorkspaces"
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
                <button class="action-btn primary" @click.stop="openWorkspace(ws)" title="进入开发">
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
          <article
            v-for="ws in filteredWorkspaces"
            :key="`list-${ws.id}`"
            class="list-card"
            @click="openWorkspace(ws)"
          >
            <div class="card-header">
              <div class="card-left">
                <div class="card-info">
                  <div class="card-name-row">
                    <h3>{{ workspaceDisplayName(ws) }}</h3>
                    <span class="source-badge">{{ workspaceGroupLabel(ws.project_type) }}</span>
                    <span class="card-status">{{ workspaceStatusLabel(ws.status) }}</span>
                  </div>
                  <div class="card-meta">
                    <span v-if="workspaceCodeName(ws)" class="card-code">{{ workspaceCodeName(ws) }}</span>
                  </div>
                </div>
              </div>
              <div class="card-actions" @click.stop>
                <button class="action-btn primary" @click.stop="openWorkspace(ws)" title="进入开发">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                </button>
                <button :class="['action-btn', { 'is-loading': uploadingWsId === ws.id }]" @click.stop="uploadWorkspace(ws)" :disabled="uploadingWsId === ws.id" :title="uploadingWsId === ws.id ? '上传中...' : '上传组件包'">
                  <svg v-if="uploadingWsId !== ws.id" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                  <svg v-else width="14" height="14" class="spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9" stroke-dasharray="42 15"/></svg>
                </button>
                <button class="action-btn" @click.stop="downloadWorkspace(ws, 'src')" title="下载源码">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                </button>
              </div>
            </div>
            <div class="card-stats">
              <span>文件类型：{{ workspaceGroupLabel(ws.project_type) }}</span>
              <span>包名：{{ workspaceCodeName(ws) || ws.project_name }}</span>
            </div>
          </article>
        </template>
      </div>
    </div>
  </WorkbenchShell>

  <EnvSelectModal v-model="showEnvModal" @selected="onEnvSelected" />
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import EnvSelectModal from '@/components/EnvSelectModal.vue'
import { codingApi, type WorkspaceInfo } from '@/api/coding'
import { platformEnvApi } from '@/api/platformEnv'

const router = useRouter()
const route = useRoute()
const loading = ref(true)
const workspaces = ref<WorkspaceInfo[]>([])
const activeTab = ref('all')
const viewMode = ref<'grid' | 'list'>('grid')
const appId = computed(() => String(route.query.app_id || ''))

// 上传组件包相关状态
const uploadingWsId = ref<string | null>(null)
const showEnvModal = ref(false)
const pendingUploadWs = ref<WorkspaceInfo | null>(null)

const groupMap: Record<string, { key: string; label: string }> = {
  'form-component-dual': { key: 'component-pc', label: '双端组件' },
  'menu-page': { key: 'page-pc', label: 'PC页面' },
  'form-page': { key: 'page-pc', label: 'PC页面' },
  'form-list': { key: 'list-view', label: '列表视图' },
  layout: { key: 'layout', label: '应用布局' },
  plugin: { key: 'plugin', label: '扩展插件' },
  'backend-api': { key: 'backend', label: '后端接口' },
  'backend-feign': { key: 'backend-feign', label: '外部调用' },
  'backend-scheduled': { key: 'backend-scheduled', label: '定时任务' },
}

const tabs = [
  { label: '全部', value: 'all' },
  { label: 'PC组件', value: 'component-pc' },
  { label: 'PC页面', value: 'page-pc' },
  { label: '列表视图', value: 'list-view' },
  { label: '应用布局', value: 'layout' },
]

const visibleWorkspaces = computed(() => {
  if (!appId.value) return workspaces.value
  return workspaces.value.filter(ws => String(ws.project_id || '') === appId.value)
})

const filteredWorkspaces = computed(() => {
  if (activeTab.value === 'all') return visibleWorkspaces.value
  return visibleWorkspaces.value.filter(ws => groupMap[ws.project_type]?.key === activeTab.value)
})

const tabCounts = computed(() => {
  const counts: Record<string, number> = {}
  for (const tab of tabs) {
    counts[tab.value] = tab.value === 'all'
      ? visibleWorkspaces.value.length
      : visibleWorkspaces.value.filter(ws => groupMap[ws.project_type]?.key === tab.value).length
  }
  return counts
})

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

async function openWorkspace(ws: WorkspaceInfo) {
  await router.push({
    path: '/coding',
    query: {
      ...(appId.value ? { app_id: appId.value } : {}),
      workspace_id: ws.id,
    },
  })
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
    workspaces.value = await codingApi.listWorkspaces()
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.catalog-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.filter-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 24px 0;
  max-width: 1200px;
  margin: 0 auto;
  width: 100%;
}

.filter-tabs {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.filter-tab {
  background: transparent;
  border: none;
  padding: 7px 16px;
  font-size: 13px;
  color: #6a7997;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  border-radius: 8px;
  transition: all 0.15s ease;
}

.filter-tab:hover {
  background: rgba(228, 233, 247, 0.8);
  color: #31405f;
}

.filter-tab.active {
  background: rgba(99, 102, 241, 0.12);
  color: #5b6ef3;
  font-weight: 600;
}

.tab-count {
  font-size: 11px;
  min-width: 20px;
  padding: 0 7px;
  border-radius: 999px;
  background: rgba(99, 102, 241, 0.1);
  color: #7b88a8;
  line-height: 20px;
  text-align: center;
}

.view-toggle {
  display: flex;
  gap: 2px;
  background: rgba(236, 240, 250, 0.95);
  border-radius: 8px;
  padding: 2px;
}

.toggle-btn {
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 6px;
  background: none;
  color: #7b88a8;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s ease;
}

.toggle-btn.active {
  background: rgba(99, 102, 241, 0.12);
  color: #5b6ef3;
}

.catalog-content {
  flex: 1;
  overflow-y: auto;
  max-width: 1200px;
  margin: 0 auto;
  width: 100%;
  padding: 16px 24px 60px;
}

.catalog-content.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 14px;
  align-content: start;
}

.grid-card,
.list-card {
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid rgba(226, 231, 246, 0.88);
  box-shadow: none;
  cursor: pointer;
  transition: all 0.2s ease;
}

.grid-card:hover,
.list-card:hover {
  background: rgba(255, 255, 255, 0.96);
  border-color: rgba(99, 102, 241, 0.18);
  box-shadow: 0 4px 20px rgba(99, 102, 241, 0.08);
  transform: translateY(-2px);
}

.grid-card {
  padding: 18px;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
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
  gap: 4px;
  min-width: 0;
}

.grid-card-badges,
.card-name-row {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.grid-card-badges {
  justify-content: flex-end;
  max-width: 120px;
}

.source-badge,
.card-status {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
}

.source-badge {
  background: rgba(238, 240, 252, 0.9);
  color: #7b88a8;
}

.card-status {
  background: rgba(224, 248, 232, 0.9);
  color: #39b56c;
}

.grid-card-name,
.card-name-row h3 {
  margin: 0;
  font-size: 15px;
  line-height: 1.3;
  color: #1f2a44;
  word-break: break-word;
}

.grid-card-meta,
.card-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  color: #95a2bf;
  font-size: 11px;
}

.grid-card-footer {
  margin-top: 2px;
  padding-top: 8px;
  border-top: 1px solid rgba(229, 233, 247, 0.9);
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
}

.card-code {
  padding: 0 7px;
  border-radius: 10px;
  background: rgba(241, 243, 252, 0.95);
}

.grid-card-stats,
.card-stats {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
  color: #95a2bf;
  font-size: 11px;
}

.grid-card-actions,
.card-actions {
  display: flex;
  gap: 4px;
}

.action-btn {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  border: 1px solid rgba(226, 231, 246, 0.9);
  background: #fff;
  color: #7b88a8;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.action-btn.primary {
  color: #5b6ef3;
  border-color: rgba(99, 102, 241, 0.2);
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
  gap: 6px;
}

.empty-state {
  min-height: 220px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #8b97b2;
  font-size: 14px;
}

@media (max-width: 1200px) {
  .catalog-content.grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@media (max-width: 900px) {
  .filter-bar {
    padding: 14px 16px 8px;
  }

  .catalog-content {
    padding: 8px 16px 20px;
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
</style>
