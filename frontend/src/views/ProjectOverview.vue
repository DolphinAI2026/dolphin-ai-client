<template>
  <div class="project-overview">
    <!-- Header -->
    <header class="po-header">
      <div class="header-left">
        <button class="back-btn" @click="router.push('/')" title="返回首页">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>
        </button>
        <div class="header-info">
          <h1 class="project-name">{{ project?.name || '加载中...' }}</h1>
          <p class="project-desc" v-if="project?.description">{{ project.description }}</p>
        </div>
      </div>
      <div class="header-right">
        <span class="conn-status" :class="project?.platform_connected ? 'connected' : 'disconnected'">
          <span class="conn-dot"></span>
          {{ project?.platform_connected ? '已连接' : '未连接' }}
        </span>
        <button class="settings-btn" @click="openSettings" title="项目设置">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
        </button>
      </div>
    </header>

    <!-- Main content -->
    <div class="po-scroll">
      <div class="po-content">
        <!-- Entry Cards -->
        <div class="entry-cards">
          <div class="entry-card" @click="goToAppBuilder">
            <div class="entry-icon build-icon">
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
                <path d="M2 20h20L12 4 2 20z" stroke="url(#buildGrad)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
                <path d="M12 20V10" stroke="url(#buildGrad)" stroke-width="1.5" stroke-linecap="round"/>
                <path d="M7 20l5-7 5 7" stroke="url(#buildGrad)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
                <defs>
                  <linearGradient id="buildGrad" x1="2" y1="4" x2="22" y2="20">
                    <stop offset="0%" stop-color="#c4b5fd"/>
                    <stop offset="100%" stop-color="#7c3aed"/>
                  </linearGradient>
                </defs>
              </svg>
            </div>
            <div class="entry-body">
              <div class="entry-title">应用搭建</div>
              <div class="entry-subtitle">对话式配置应用</div>
              <div class="entry-tags">模型 · 表单 · 流程</div>
            </div>
            <div class="entry-action">
              <span class="action-text">进入</span>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>
            </div>
          </div>

          <div class="entry-card" @click="goToCoding">
            <div class="entry-icon coding-icon">
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
                <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" fill="url(#codeGrad)"/>
                <defs>
                  <linearGradient id="codeGrad" x1="3" y1="2" x2="22" y2="22">
                    <stop offset="0%" stop-color="#fbbf24"/>
                    <stop offset="100%" stop-color="#f59e0b"/>
                  </linearGradient>
                </defs>
              </svg>
            </div>
            <div class="entry-body">
              <div class="entry-title">组件开发</div>
              <div class="entry-subtitle">AI 自开发代码</div>
              <div class="entry-tags">组件 · 页面 · 接口</div>
            </div>
            <div class="entry-action">
              <span class="action-text">进入</span>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>
            </div>
          </div>

          <div class="entry-card" @click="goToPageDev">
            <div class="entry-icon page-icon">
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z" stroke="url(#pageGrad)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
                <polyline points="14 2 14 8 20 8" stroke="url(#pageGrad)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
                <line x1="8" y1="13" x2="16" y2="13" stroke="url(#pageGrad)" stroke-width="1.5" stroke-linecap="round"/>
                <line x1="8" y1="17" x2="13" y2="17" stroke="url(#pageGrad)" stroke-width="1.5" stroke-linecap="round"/>
                <defs>
                  <linearGradient id="pageGrad" x1="4" y1="2" x2="20" y2="22">
                    <stop offset="0%" stop-color="#34d399"/>
                    <stop offset="100%" stop-color="#059669"/>
                  </linearGradient>
                </defs>
              </svg>
            </div>
            <div class="entry-body">
              <div class="entry-title">页面开发</div>
              <div class="entry-subtitle">AI 自开发页面</div>
              <div class="entry-tags">菜单页面 · 弹窗 · 数据查询</div>
            </div>
            <div class="entry-action">
              <span class="action-text">进入</span>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>
            </div>
          </div>
        </div>

        <!-- Workspaces -->
        <div class="section">
          <h3 class="section-title">工作区</h3>
          <div class="workspace-list" v-if="workspaces.length > 0">
            <div v-for="ws in workspaces" :key="ws.id" class="workspace-row">
              <div class="ws-info">
                <span class="ws-name">{{ ws.project_name }}</span>
                <span class="ws-type">{{ ws.project_type }}</span>
                <span class="ws-status" :class="ws.status">{{ ws.status }}</span>
              </div>
              <button class="ws-action-btn" @click="openWorkspace(ws)" title="打开工作区">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/></svg>
              </button>
            </div>
          </div>
          <div v-else class="empty-hint">
            <span>暂无工作区</span>
          </div>
        </div>

        <!-- Team Members -->
        <div class="section">
          <h3 class="section-title">团队成员</h3>
          <div class="members-row">
            <div class="member-avatars">
              <div
                v-for="m in members"
                :key="m.id"
                class="member-avatar"
                :title="`${m.username} (${m.role})`"
              >
                {{ m.username?.charAt(0).toUpperCase() }}
              </div>
            </div>
            <button class="manage-btn" @click="openSettings">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              管理
            </button>
          </div>
        </div>
      </div>
    </div>

    <ProjectSettingsModal
      v-model="showSettingsModal"
      :project="project"
      @saved="onProjectSaved"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { projectsApi, type Project, type ProjectMember } from '@/api/projects'
import type { WorkspaceInfo } from '@/api/coding'
import ProjectSettingsModal from '@/components/ProjectSettingsModal.vue'

const route = useRoute()
const router = useRouter()

const project = ref<Project | null>(null)
const workspaces = ref<WorkspaceInfo[]>([])
const members = ref<ProjectMember[]>([])
const showSettingsModal = ref(false)

const projectId = Number(route.params.id)

onMounted(async () => {
  await loadProject()
  loadWorkspaces()
  loadMembers()
})

const loadProject = async () => {
  try {
    project.value = await projectsApi.get(projectId)
  } catch {
    router.push('/')
  }
}

const loadWorkspaces = async () => {
  try {
    workspaces.value = await projectsApi.listWorkspaces(projectId)
  } catch { /* ignore */ }
}

const loadMembers = async () => {
  try {
    members.value = await projectsApi.listMembers(projectId)
  } catch { /* ignore */ }
}

const goToAppBuilder = () => {
  router.push({ path: '/chat', query: { project_id: String(projectId) } })
}

const goToCoding = () => {
  localStorage.setItem('coding_last_project_id', String(projectId))
  router.push({ path: '/coding', query: { project_id: String(projectId) } })
}

const goToPageDev = () => {
  localStorage.setItem('coding_last_project_id', String(projectId))
  router.push({ path: '/coding', query: { project_id: String(projectId), type: 'page' } })
}

const openWorkspace = (ws: WorkspaceInfo) => {
  localStorage.setItem('coding_last_project_id', String(projectId))
  router.push({ path: '/coding', query: { project_id: String(projectId), workspace_id: ws.id } })
}

const openSettings = () => {
  showSettingsModal.value = true
}

const onProjectSaved = async () => {
  showSettingsModal.value = false
  await loadProject()
}
</script>

<style scoped>
.project-overview {
  --bg-base: #0a0a0a;
  --bg-card: #111111;
  --bg-card-hover: #161616;
  --bg-elevated: #1a1a1a;
  --border-subtle: rgba(255, 255, 255, 0.06);
  --border-hover: rgba(255, 255, 255, 0.12);
  --text-primary: #f5f5f5;
  --text-secondary: rgba(255, 255, 255, 0.55);
  --text-tertiary: rgba(255, 255, 255, 0.35);
  --accent-gradient: linear-gradient(135deg, #7c3aed, #6366f1);
  --accent-purple: #7c3aed;
  --radius-sm: 8px;
  --radius-md: 12px;
  --radius-lg: 16px;

  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-base);
  color: var(--text-primary);
}

/* ── Header ── */
.po-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 24px;
  background: rgba(10, 10, 10, 0.8);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border-subtle);
  position: sticky;
  top: 0;
  z-index: 100;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
}

.back-btn {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-subtle);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: background 0.2s, border-color 0.2s, color 0.2s;
}

.back-btn:hover {
  background: var(--bg-elevated);
  border-color: var(--border-hover);
  color: var(--text-primary);
}

.header-info {
  min-width: 0;
}

.project-name {
  font-size: 18px;
  font-weight: 600;
  margin: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.project-desc {
  font-size: 12px;
  color: var(--text-tertiary);
  margin: 2px 0 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 400px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}

.conn-status {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 500;
  padding: 4px 12px;
  border-radius: 20px;
}

.conn-status.connected {
  color: #34d399;
  background: rgba(16, 185, 129, 0.1);
}

.conn-status.disconnected {
  color: var(--text-tertiary);
  background: rgba(255, 255, 255, 0.04);
}

.conn-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.conn-status.connected .conn-dot {
  background: #10b981;
  box-shadow: 0 0 6px rgba(16, 185, 129, 0.5);
}

.conn-status.disconnected .conn-dot {
  background: rgba(255, 255, 255, 0.2);
}

.settings-btn {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-subtle);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s, border-color 0.2s, color 0.2s;
}

.settings-btn:hover {
  background: var(--bg-elevated);
  border-color: var(--border-hover);
  color: var(--text-primary);
}

/* ── Scroll Area ── */
.po-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 0 24px 60px;
}

.po-content {
  max-width: 800px;
  width: 100%;
  margin: 0 auto;
  padding-top: 32px;
}

/* ── Entry Cards ── */
.entry-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 48px;
}

.entry-card {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  padding: 28px 24px;
  cursor: pointer;
  transition: transform 0.2s, border-color 0.2s, box-shadow 0.2s;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.entry-card:hover {
  transform: translateY(-2px);
  border-color: var(--border-hover);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
}

.entry-icon {
  width: 52px;
  height: 52px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.build-icon {
  background: rgba(124, 58, 237, 0.1);
}

.coding-icon {
  background: rgba(251, 191, 36, 0.1);
}

.page-icon {
  background: rgba(52, 211, 153, 0.1);
}

.entry-body {
  flex: 1;
}

.entry-title {
  font-size: 17px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.entry-subtitle {
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 6px;
}

.entry-tags {
  font-size: 12px;
  color: var(--text-tertiary);
}

.entry-action {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  font-weight: 500;
  color: var(--accent-purple);
  transition: gap 0.2s;
}

.entry-card:hover .entry-action {
  gap: 6px;
}

.action-text {
  opacity: 0.85;
}

.entry-card:hover .action-text {
  opacity: 1;
}

/* ── Sections ── */
.section {
  margin-bottom: 40px;
}

.section-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin: 0 0 16px;
}

/* ── Workspace List ── */
.workspace-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.workspace-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  padding: 12px 16px;
  transition: border-color 0.2s;
}

.workspace-row:hover {
  border-color: var(--border-hover);
}

.ws-info {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.ws-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
}

.ws-type {
  font-size: 11px;
  color: var(--text-tertiary);
  background: rgba(255, 255, 255, 0.04);
  padding: 2px 8px;
  border-radius: 4px;
}

.ws-status {
  font-size: 11px;
  font-weight: 500;
  padding: 2px 8px;
  border-radius: 4px;
}

.ws-status.ready {
  color: #34d399;
  background: rgba(16, 185, 129, 0.1);
}

.ws-status.building,
.ws-status.pending {
  color: #fbbf24;
  background: rgba(251, 191, 36, 0.1);
}

.ws-status.error {
  color: #f87171;
  background: rgba(248, 113, 113, 0.1);
}

.ws-action-btn {
  background: none;
  border: none;
  color: var(--text-tertiary);
  cursor: pointer;
  padding: 6px;
  border-radius: var(--radius-sm);
  transition: background 0.2s, color 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
}

.ws-action-btn:hover {
  background: var(--bg-elevated);
  color: var(--text-secondary);
}

/* ── Members ── */
.members-row {
  display: flex;
  align-items: center;
  gap: 16px;
}

.member-avatars {
  display: flex;
  align-items: center;
}

.member-avatar {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: var(--accent-gradient);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 600;
  border: 2px solid var(--bg-base);
  margin-left: -8px;
  flex-shrink: 0;
}

.member-avatar:first-child {
  margin-left: 0;
}

.manage-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
  background: none;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  padding: 5px 12px;
  cursor: pointer;
  transition: background 0.2s, border-color 0.2s, color 0.2s;
}

.manage-btn:hover {
  background: var(--bg-elevated);
  border-color: var(--border-hover);
  color: var(--text-primary);
}

/* ── Empty ── */
.empty-hint {
  text-align: center;
  color: var(--text-tertiary);
  font-size: 13px;
  padding: 28px 20px;
  background: var(--bg-card);
  border: 1px dashed rgba(255, 255, 255, 0.08);
  border-radius: var(--radius-md);
}

/* ── Scrollbar ── */
.po-scroll::-webkit-scrollbar {
  width: 6px;
}

.po-scroll::-webkit-scrollbar-track {
  background: transparent;
}

.po-scroll::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.08);
  border-radius: 3px;
}

.po-scroll::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.15);
}
</style>
