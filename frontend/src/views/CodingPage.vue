<template>
  <div class="coding-page">
    <!-- Header -->
    <header class="coding-header">
      <div class="header-left">
        <el-button text @click="$router.push('/chat')">
          <el-icon><ArrowLeft /></el-icon>
        </el-button>
        <h3 class="header-title">复杂开发智能体</h3>
        <el-tag v-if="codingStore.workspace" size="small" type="info">
          {{ codingStore.workspace.project_name }}
        </el-tag>
      </div>
      <div class="header-right">
        <el-button
          size="small"
          @click="$router.push('/marketplace')"
          class="header-btn"
        >
          <el-icon><Goods /></el-icon> 组件市场
        </el-button>
        <el-button
          v-if="codingStore.workspace"
          size="small"
          @click="openInVSCode"
          class="header-btn"
        >
          <el-icon><FolderOpened /></el-icon> 在 VS Code 中打开
        </el-button>
        <el-dropdown
          v-if="codingStore.workspace"
          split-button
          type="success"
          size="small"
          :loading="isDebugging"
          class="header-btn debug-dropdown"
          @click="handleDebug('app')"
          @command="handleDebug"
        >
          <el-icon><Monitor /></el-icon> Debug 预览
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="app">应用调试（看效果）</el-dropdown-item>
              <el-dropdown-item command="platform">平台调试（设计器）</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-button
          v-if="codingStore.workspace"
          size="small"
          type="primary"
          @click="publishProject"
          :loading="isPublishing"
          class="header-btn"
        >
          <el-icon><Upload /></el-icon> 打包发布
        </el-button>
      </div>
    </header>

    <div class="coding-body">
      <!-- Left Sidebar: Project → Workspace Tree -->
      <aside class="workspace-sidebar">
        <!-- Project Selector -->
        <div class="sidebar-header">
          <el-select
            v-model="currentProjectId"
            placeholder="选择应用"
            size="small"
            class="project-select"
            @change="onProjectChange"
          >
            <el-option
              v-for="p in projects"
              :key="p.id"
              :label="p.name"
              :value="p.id"
            />
          </el-select>
          <el-button size="small" type="primary" text @click="showCreateProject">
            <el-icon><Plus /></el-icon>
          </el-button>
        </div>

        <!-- Platform Status -->
        <div v-if="currentProject" class="sidebar-platform-status">
          <div class="platform-status-row">
            <span class="platform-dot" :class="currentProject.platform_connected ? 'connected' : 'disconnected'"></span>
            <span class="platform-label">{{ currentProject.platform_connected ? '平台已连接' : '未连接平台' }}</span>
          </div>
          <el-button size="small" text class="platform-config-btn" @click="showProjectSettings">
            配置平台环境
          </el-button>
        </div>

        <!-- No Project Prompt -->
        <div v-if="projects.length === 0" class="sidebar-empty-project">
          <div class="empty-icon">&#128194;</div>
          <div class="empty-text">创建你的第一个应用</div>
          <el-button size="small" type="primary" @click="showCreateProject">新建应用</el-button>
        </div>

        <!-- Workspace List (under selected project) -->
        <template v-if="currentProject">
          <div class="sidebar-section-header">
            <span class="sidebar-title">工作区</span>
            <el-button size="small" type="primary" text @click="startNewWorkspace">
              <el-icon><Plus /></el-icon>
            </el-button>
          </div>
          <div class="sidebar-list">
            <template v-for="group in groupedWorkspaces" :key="group.key">
              <div class="sidebar-group-header" @click="toggleGroup(group.key)">
                <span class="sidebar-group-icon">{{ group.icon }}</span>
                <span class="sidebar-group-label">{{ group.label }}</span>
                <span class="sidebar-group-count">{{ group.items.length }}</span>
                <span class="sidebar-group-arrow" :class="{ collapsed: collapsedGroups.has(group.key) }">‹</span>
              </div>
              <template v-if="!collapsedGroups.has(group.key)">
                <div
                  v-for="ws in group.items"
                  :key="ws.id"
                  class="sidebar-ws-item"
                  :class="{ active: codingStore.workspace?.id === ws.id }"
                  @click="openExistingWorkspace(ws)"
                >
                  <div class="sidebar-ws-name">{{ ws.project_name }}</div>
                  <div class="sidebar-ws-meta">
                    <el-button
                      size="small"
                      type="danger"
                      text
                      @click.stop="deleteWorkspace(ws)"
                      class="sidebar-ws-del"
                    >×</el-button>
                  </div>
                </div>
              </template>
            </template>
            <div v-if="existingWorkspaces.length === 0" class="sidebar-empty">
              暂无工作区，发消息自动创建
            </div>
          </div>
        </template>

        <!-- Project Actions (bottom) -->
        <div v-if="currentProject" class="sidebar-footer">
          <el-button size="small" text type="danger" @click="deleteProject" class="sidebar-delete-btn">
            删除应用
          </el-button>
        </div>
      </aside>

      <!-- Project Settings Modal -->
      <ProjectSettingsModal
        v-model="projectSettingsVisible"
        :project="editingProject"
        @saved="onProjectSaved"
      />

      <!-- Main Content -->
      <div class="main-content">
    <div class="chat-area" ref="chatAreaRef">
      <!-- Welcome message when no workspace -->
      <div v-if="!codingStore.workspace && codingStore.messages.length === 0" class="welcome">
        <div class="welcome-icon">&#x2728;</div>
        <h2>描述你想开发的内容</h2>
        <p class="welcome-desc">告诉我你想开发什么，我会自动创建项目、生成代码、安装依赖并启动开发服务器。</p>

        <!-- Scene Category Tabs -->
        <div class="scene-tabs">
          <button
            v-for="cat in sceneCategories"
            :key="cat.key"
            class="scene-tab"
            :class="{ active: activeSceneCategory === cat.key }"
            @click="activeSceneCategory = cat.key"
          >
            <span class="scene-tab-icon">{{ cat.icon }}</span>
            {{ cat.label }}
          </button>
        </div>

        <div class="suggestions">
          <button
            v-for="s in activeSuggestions"
            :key="s"
            class="suggestion-btn"
            @click="sendSuggestion(s)"
          >
            {{ s }}
          </button>
        </div>
      </div>

      <!-- Messages -->
      <div v-for="(msg, idx) in codingStore.messages" :key="idx" class="message" :class="msg.role">
        <!-- User message -->
        <div v-if="msg.role === 'user'" class="user-msg">
          <div class="msg-avatar user-avatar">U</div>
          <div class="msg-bubble user-bubble">{{ msg.content }}</div>
        </div>

        <!-- Assistant message with pipeline steps -->
        <div v-if="msg.role === 'assistant'" class="assistant-msg">
          <div class="msg-avatar assistant-avatar">AI</div>
          <div class="msg-bubble assistant-bubble">
            <!-- Pipeline progress (if present) -->
            <div v-if="msg.pipelineSteps && msg.pipelineSteps.length" class="pipeline-steps">
              <div
                v-for="step in msg.pipelineSteps"
                :key="step.name"
                class="step"
                :class="step.status"
              >
                <span class="step-icon">{{ stepIcon(step) }}</span>
                <span class="step-label">{{ step.label }}</span>
              </div>
            </div>
            <!-- Debug screenshots -->
            <div v-if="msg.screenshots && msg.screenshots.length" class="debug-screenshots">
              <div class="screenshot-header">Debug 截图</div>
              <img v-for="(url, i) in msg.screenshots" :key="i" :src="url" class="debug-screenshot" @click="previewScreenshot(url)" />
            </div>
            <!-- Text content -->
            <div v-if="msg.textContent" class="msg-text" v-html="renderMarkdown(msg.textContent)"></div>
            <!-- 内嵌组件预览 -->
            <div v-if="msg.fileNames && msg.fileNames.length && msg.previewHtml" class="inline-preview">
              <div class="preview-header">
                <span class="preview-icon">👁</span> 组件预览
                <el-button size="small" text @click="msg._previewCollapsed = !msg._previewCollapsed">
                  {{ msg._previewCollapsed ? '展开' : '收起' }}
                </el-button>
              </div>
              <iframe
                v-show="!msg._previewCollapsed"
                :srcdoc="msg.previewHtml"
                class="preview-iframe"
                sandbox="allow-scripts allow-same-origin"
              ></iframe>
            </div>
            <!-- File change summary -->
            <div v-if="msg.fileNames && msg.fileNames.length" class="file-summary">
              <span class="file-summary-icon">&#128196;</span>
              已更新 {{ msg.fileNames.length }} 个文件：{{ msg.fileNames.join(', ') }}
            </div>
          </div>
        </div>
      </div>

      <!-- Streaming / Processing indicator -->
      <div v-if="codingStore.isProcessing" class="message assistant">
        <div class="assistant-msg">
          <div class="msg-avatar assistant-avatar">AI</div>
          <div class="msg-bubble assistant-bubble">
            <!-- Live pipeline steps -->
            <div v-if="codingStore.currentPipelineSteps.length" class="pipeline-steps">
              <div
                v-for="step in codingStore.currentPipelineSteps"
                :key="step.name"
                class="step"
                :class="step.status"
              >
                <span class="step-icon">{{ stepIcon(step) }}</span>
                <span class="step-label">{{ step.label }}</span>
              </div>
            </div>
            <!-- Streaming text -->
            <div v-if="codingStore.streamContent" class="msg-text" v-html="renderMarkdown(codingStore.streamContent)"></div>
            <span v-if="codingStore.streamContent" class="typing-cursor">&#9608;</span>
            <div v-if="!codingStore.streamContent && !codingStore.currentPipelineSteps.some(s => s.status === 'running')" class="thinking-dots">
              <span></span><span></span><span></span>
            </div>
          </div>
        </div>
      </div>

      <!-- Scroll anchor -->
      <div ref="scrollAnchor"></div>
    </div>

    <!-- Input Area (bottom) -->
    <div class="input-area">
      <!-- Attachment Preview -->
      <div v-if="attachedFile" class="attachment-preview">
        <div v-if="attachedPreviewUrl" class="attachment-thumb">
          <img :src="attachedPreviewUrl" alt="preview" />
          <button class="attachment-remove" @click="removeAttachment">&times;</button>
        </div>
        <div v-else class="attachment-file">
          <span class="attachment-file-icon">&#128196;</span>
          <span class="attachment-file-name">{{ attachedFile.name }}</span>
          <button class="attachment-remove" @click="removeAttachment">&times;</button>
        </div>
      </div>

      <div class="input-wrapper" @paste="handlePaste">
        <!-- Hidden file input -->
        <input
          ref="fileInputRef"
          type="file"
          accept=".md,.pdf,.docx,.txt,.png,.jpg,.jpeg"
          style="display: none"
          @change="handleFileSelect"
        />
        <el-button
          text
          class="attach-btn"
          @click="fileInputRef?.click()"
          :disabled="codingStore.isProcessing"
          title="上传附件"
        >
          <el-icon :size="18"><Paperclip /></el-icon>
        </el-button>
        <el-input
          v-model="userInput"
          type="textarea"
          :rows="2"
          :autosize="{ minRows: 1, maxRows: 6 }"
          :placeholder="inputPlaceholder"
          @keydown.ctrl.enter="sendMessage"
          @keydown.meta.enter="sendMessage"
          :disabled="codingStore.isProcessing"
          resize="none"
        />
        <el-button
          type="primary"
          class="send-btn"
          :loading="codingStore.isProcessing || isUploading"
          @click="sendMessage"
          :disabled="(!userInput.trim() && !attachedFile) || codingStore.isProcessing"
          circle
        >
          <el-icon v-if="!codingStore.isProcessing && !isUploading"><TopRight /></el-icon>
        </el-button>
      </div>
      <div class="input-hint">Ctrl + Enter 发送 | 粘贴截图或点击回形针添加附件</div>
    </div>

      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, FolderOpened, Upload, Menu, TopRight, Monitor, Plus, Setting, Paperclip, Goods } from '@element-plus/icons-vue'
import { useCodingStore } from '@/stores/coding'
import type { PipelineStep, ChatMessage } from '@/stores/coding'
import { useUserStore } from '@/stores/user'
import { codingApi } from '@/api/coding'
import type { GeneratedFile, WorkspaceInfo, UploadResult } from '@/api/coding'
import { projectsApi } from '@/api/projects'
import type { Project } from '@/api/projects'
import ProjectSettingsModal from '@/components/ProjectSettingsModal.vue'

const router = useRouter()
const route = useRoute()
const codingStore = useCodingStore()
const userStore = useUserStore()

const userInput = ref('')
const chatAreaRef = ref<HTMLElement>()
const scrollAnchor = ref<HTMLElement>()

// 页面类型：从 URL query 读取，page=页面开发，否则=组件开发
const devType = computed(() => route.query.type === 'page' ? 'page' : 'component')
const isPageDev = computed(() => devType.value === 'page')

const existingWorkspaces = ref<WorkspaceInfo[]>([])
const isPublishing = ref(false)
const isDebugging = ref(false)

// ============ Workspace Grouping ============
const collapsedGroups = ref(new Set<string>())

const wsTypeGroupMap: Record<string, { key: string; icon: string; label: string; order: number }> = {
  'form-component':   { key: 'component-pc',     icon: '🧩', label: 'PC 组件',     order: 1 },
  'mobile-component': { key: 'component-mobile', icon: '📱', label: '移动端组件',  order: 2 },
  'menu-page':        { key: 'page-pc',          icon: '🖥️', label: 'PC 页面',     order: 3 },
  'form-page':        { key: 'page-pc',          icon: '🖥️', label: 'PC 页面',     order: 3 },
  'mobile-page':      { key: 'page-mobile',      icon: '📱', label: '移动端页面',  order: 4 },
  'form-list':        { key: 'list-view',         icon: '📋', label: '列表视图',   order: 5 },
  'layout':           { key: 'layout',            icon: '📐', label: '应用布局',   order: 6 },
  'plugin':           { key: 'plugin',            icon: '🔌', label: '扩展插件',   order: 7 },
  'backend-api':      { key: 'backend',           icon: '⚙️', label: '后端接口',   order: 8 },
  'script':           { key: 'script',            icon: '⚡', label: '脚本/事件',  order: 9 },
  'script-js':        { key: 'script',            icon: '⚡', label: '脚本/事件',  order: 9 },
  'script-python':    { key: 'script',            icon: '⚡', label: '脚本/事件',  order: 9 },
  'script-groovy':    { key: 'script',            icon: '⚡', label: '脚本/事件',  order: 9 },
  'business-dialog':  { key: 'dialog',            icon: '💬', label: '业务弹窗',   order: 10 },
  'ui-style':         { key: 'style',             icon: '🎨', label: 'UI 样式',   order: 11 },
  'list-custom-module': { key: 'list-module',     icon: '📊', label: '列表模块',   order: 12 },
  'web-login':        { key: 'login',             icon: '🔑', label: '登录页',     order: 13 },
}

const groupedWorkspaces = computed(() => {
  const groups: Record<string, { key: string; icon: string; label: string; order: number; items: WorkspaceInfo[] }> = {}
  for (const ws of existingWorkspaces.value) {
    const mapping = wsTypeGroupMap[ws.project_type] || { key: 'other', icon: '📦', label: '其他', order: 99 }
    if (!groups[mapping.key]) {
      groups[mapping.key] = { ...mapping, items: [] }
    }
    groups[mapping.key].items.push(ws)
  }
  return Object.values(groups).sort((a, b) => a.order - b.order)
})

function toggleGroup(key: string) {
  if (collapsedGroups.value.has(key)) {
    collapsedGroups.value.delete(key)
  } else {
    collapsedGroups.value.add(key)
  }
}

// ============ Attachment state ============
const attachedFile = ref<File | null>(null)
const attachedPreviewUrl = ref<string | null>(null)
const isUploading = ref(false)
const fileInputRef = ref<HTMLInputElement>()

// ============ Projects ============
const projects = ref<Project[]>([])
const currentProjectId = ref<number | null>(null)
const projectSettingsVisible = ref(false)
const editingProject = ref<Project | null>(null)

const currentProject = computed(() => {
  if (!currentProjectId.value) return null
  return projects.value.find(p => p.id === currentProjectId.value) || null
})

// ============ Suggestions ============

// ============ Scene Categories & Suggestions ============
const sceneCategories = [
  { key: 'component-pc', icon: '🧩', label: 'PC组件' },
  { key: 'component-mobile', icon: '📱', label: '移动端组件' },
  { key: 'page-pc', icon: '🖥️', label: 'PC页面' },
  { key: 'page-mobile', icon: '📱', label: '移动端页面' },
  { key: 'layout', icon: '📐', label: '应用布局' },
  { key: 'plugin', icon: '🔌', label: '扩展插件' },
  { key: 'script', icon: '⚡', label: '脚本/事件' },
  { key: 'backend', icon: '⚙️', label: '后端接口' },
]

const sceneSuggestions: Record<string, string[]> = {
  'component-pc': [
    '开发一个头像上传组件，支持裁剪和预览',
    '实现一个日期范围选择器组件',
    '做一个评分组件，支持半星和自定义颜色',
    '创建一个图表分析组件，支持柱状图和饼图',
  ],
  'component-mobile': [
    '做一个移动端签名板组件，支持手写签名',
    '开发一个移动端图片选择组件，支持拍照和相册',
    '实现一个移动端地理位置选择组件（Cube UI）',
    '为已有PC评分组件开发对应的移动端版本',
  ],
  'page-pc': [
    '做一个数据查询表格页面，带搜索和分页',
    '开发一个供应商管理弹窗选择页面',
    '创建一个项目分析图表页面',
    '做一个审批流程页面，支持多级审批',
  ],
  'page-mobile': [
    '做一个移动端扫码签到页面',
    '开发一个移动端巡检记录页面',
    '创建一个移动端审批详情页面',
    '做一个移动端数据采集表单页面',
  ],
  layout: [
    '做一个带顶部公告栏的自定义布局',
    '创建一个双栏布局，左侧菜单可折叠',
    '开发一个暗色主题的自定义应用布局',
  ],
  plugin: [
    '开发一个应用详情页的自定义Tab插件',
    '做一个自定义面板扩展，显示统计数据',
    '创建一个系统通知管理扩展插件',
  ],
  script: [
    '写一个JavaScript前端脚本，表单提交前校验数据',
    '做一个业务事件自定义弹窗，采集审批意见',
    '写一个后端Python脚本处理数据同步',
    '开发一个自定义CSS样式，美化表单界面',
  ],
  backend: [
    '开发一个自定义数据查询接口',
    '做一个批量导入的后端接口',
    '创建一个报表统计的后端API',
  ],
}

const activeSceneCategory = ref('component-pc')
const pendingSceneCategory = ref<string | null>(null) // 点建议按钮时锁定的场景类别

const activeSuggestions = computed(() => sceneSuggestions[activeSceneCategory.value] || [])

// 场景分类 → 后端 project_type 映射
const sceneCategoryToProjectType: Record<string, string> = {
  'component-pc': 'form-component',
  'component-mobile': 'mobile-component',
  'page-pc': 'menu-page',
  'page-mobile': 'mobile-page',
  layout: 'layout',
  plugin: 'plugin',
  script: 'script',
  backend: 'backend-api',
}

const inputPlaceholder = computed(() => {
  if (codingStore.workspace) {
    return '描述你的修改需求... (Ctrl+Enter 发送)'
  }
  return '描述你想开发的组件或页面... (Ctrl+Enter 发送)'
})

// ============ Lifecycle ============

onMounted(async () => {
  // Load projects
  try {
    projects.value = await projectsApi.list()
  } catch (e) {
    console.error('获取项目列表失败:', e)
  }

  // Restore last selected project
  const lastProjectId = localStorage.getItem('coding_last_project_id')
  if (lastProjectId && projects.value.some(p => p.id === Number(lastProjectId))) {
    currentProjectId.value = Number(lastProjectId)
    await loadProjectWorkspaces()
  } else if (projects.value.length > 0) {
    currentProjectId.value = projects.value[0].id
    await loadProjectWorkspaces()
  } else {
    // No projects: load all workspaces (backward compatibility)
    try {
      existingWorkspaces.value = await codingApi.listWorkspaces()
    } catch (e) {
      console.error('获取工作区列表失败:', e)
    }
  }

  // If workspace_id in query, open it
  const wsId = (route.query.workspace_id || route.query.ws) as string
  if (wsId) {
    await openWorkspaceById(wsId)
  } else {
    const lastWsId = localStorage.getItem('coding_last_workspace_id')
    if (lastWsId && existingWorkspaces.value.some(w => w.id === lastWsId)) {
      await openWorkspaceById(lastWsId)
    }
  }

  // Restore conversation if specified
  const convId = route.query.conversation_id
  if (convId) {
    await restoreConversation(Number(convId))
  }
})

// ============ Project operations ============

async function loadProjectWorkspaces() {
  if (!currentProjectId.value) {
    existingWorkspaces.value = []
    return
  }
  try {
    // Load all user workspaces and filter by project_id
    const allWs = await codingApi.listWorkspaces()
    existingWorkspaces.value = allWs.filter(
      (ws: any) => ws.project_id === currentProjectId.value
    )
  } catch (e) {
    console.error('获取工作区列表失败:', e)
    existingWorkspaces.value = []
  }
}

async function onProjectChange(projectId: number) {
  currentProjectId.value = projectId
  localStorage.setItem('coding_last_project_id', String(projectId))
  codingStore.reset()
  localStorage.removeItem('coding_last_workspace_id')
  await loadProjectWorkspaces()
}

function showCreateProject() {
  editingProject.value = null
  projectSettingsVisible.value = true
}

function showProjectSettings() {
  editingProject.value = currentProject.value
  projectSettingsVisible.value = true
}

async function onProjectSaved(project: Project) {
  // Refresh project list
  try {
    projects.value = await projectsApi.list()
  } catch { /* ignore */ }

  // Select the saved project
  currentProjectId.value = project.id
  localStorage.setItem('coding_last_project_id', String(project.id))
  await loadProjectWorkspaces()
}

async function deleteProject() {
  if (!currentProject.value) return
  try {
    await projectsApi.delete(currentProject.value.id)
    projects.value = projects.value.filter(p => p.id !== currentProject.value!.id)
    localStorage.removeItem('coding_last_project_id')
    codingStore.reset()
    existingWorkspaces.value = []
    if (projects.value.length > 0) {
      currentProjectId.value = projects.value[0].id
      localStorage.setItem('coding_last_project_id', String(currentProjectId.value))
      await loadProjectWorkspaces()
    } else {
      currentProjectId.value = null
    }
    ElMessage.success('应用已删除')
  } catch (e: any) {
    ElMessage.error(e.message || '删除失败')
  }
}

// ============ Workspace operations ============

async function openExistingWorkspace(ws: WorkspaceInfo) {
  await openWorkspaceById(ws.id)
}

async function openWorkspaceById(wsId: string) {
  try {
    const ws = await codingApi.getWorkspace(wsId)
    codingStore.setWorkspace(ws)
    localStorage.setItem('coding_last_workspace_id', wsId)

    // Load conversation history
    await loadWorkspaceConversation(wsId)

    // Check serve status
    try {
      const serveStatus = await codingApi.getServeStatus(wsId)
      codingStore.serveRunning = serveStatus.running
      codingStore.serveUrl = serveStatus.url || null
    } catch {
      // ignore
    }
  } catch (error: any) {
    ElMessage.error(`打开工作区失败: ${error.message}`)
  }
}

async function loadWorkspaceConversation(wsId: string) {
  try {
    const data = await codingApi.getWorkspaceConversation(wsId)
    if (data.conversation_id) {
      codingStore.conversationId = data.conversation_id
      for (const msg of data.messages) {
        if (msg.role === 'user' || msg.role === 'assistant') {
          const chatMsg: ChatMessage = { role: msg.role, content: msg.content }
          if (msg.role === 'assistant') {
            chatMsg.textContent = msg.content
            const files = parseFilesFromContent(msg.content)
            if (files.length > 0) {
              chatMsg.fileNames = files.map(f => getFileName(f.path))
            }
          }
          codingStore.addMessage(chatMsg)
        }
      }
    }
  } catch {
    // no history, ignore
  }
}

async function restoreConversation(conversationId: number) {
  try {
    codingStore.conversationId = conversationId
    const messages = await codingApi.getMessages(conversationId)
    for (const msg of messages) {
      const chatMsg: ChatMessage = {
        id: msg.id,
        role: msg.role,
        content: msg.content,
        created_at: msg.created_at,
      }
      if (msg.role === 'assistant') {
        chatMsg.textContent = msg.content
        const files = parseFilesFromContent(msg.content)
        if (files.length > 0) {
          chatMsg.fileNames = files.map(f => getFileName(f.path))
        }
      }
      codingStore.addMessage(chatMsg)
    }
  } catch (e) {
    console.error('恢复对话失败:', e)
  }
}

// ============ Attachment Handling ============

function handlePaste(event: ClipboardEvent) {
  const items = event.clipboardData?.items
  if (!items) return
  for (const item of items) {
    if (item.type.startsWith('image/')) {
      event.preventDefault()
      const file = item.getAsFile()
      if (file) setAttachment(file)
      return
    }
  }
}

function handleFileSelect(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) setAttachment(file)
  // Reset so the same file can be re-selected
  input.value = ''
}

function setAttachment(file: File) {
  attachedFile.value = file
  if (file.type.startsWith('image/')) {
    attachedPreviewUrl.value = URL.createObjectURL(file)
  } else {
    attachedPreviewUrl.value = null
  }
}

function removeAttachment() {
  if (attachedPreviewUrl.value) {
    URL.revokeObjectURL(attachedPreviewUrl.value)
  }
  attachedFile.value = null
  attachedPreviewUrl.value = null
}

// ============ Send Message / Auto Pipeline ============

function sendSuggestion(text: string) {
  userInput.value = text
  // 记住当前选中的场景类别，用于传给后端
  pendingSceneCategory.value = activeSceneCategory.value
  sendMessage()
}

async function sendMessage() {
  const message = userInput.value.trim()
  if (!message && !attachedFile.value) return
  if (codingStore.isProcessing) return

  userInput.value = ''
  const currentAttachment = attachedFile.value
  const currentPreviewUrl = attachedPreviewUrl.value
  attachedFile.value = null
  attachedPreviewUrl.value = null

  // Show user message (include attachment indicator)
  const displayMsg = currentAttachment
    ? `${message}${message ? '\n' : ''}[附件: ${currentAttachment.name}]`
    : message
  codingStore.addMessage({ role: 'user', content: displayMsg })
  codingStore.isProcessing = true
  codingStore.streamContent = ''

  await nextTick()
  scrollToBottom()

  // Upload attachment if present
  let uploadResult: UploadResult | null = null
  if (currentAttachment) {
    try {
      isUploading.value = true
      uploadResult = await codingApi.uploadFile(currentAttachment, codingStore.workspace?.id)
    } catch (e: any) {
      ElMessage.error(`附件上传失败: ${e.message}`)
    } finally {
      isUploading.value = false
      if (currentPreviewUrl) URL.revokeObjectURL(currentPreviewUrl)
    }
  }

  // Build final message with attachment context
  let finalMessage = message
  if (uploadResult) {
    if (uploadResult.content) {
      // Text document: prepend content as context
      finalMessage = `[附件文档: ${uploadResult.filename}]\n\`\`\`\n${uploadResult.content}\n\`\`\`\n\n${message}`
    } else {
      // Image or binary file: mention path
      finalMessage = `${message}\n\n[附件图片: ${uploadResult.filename}, 已保存至: ${uploadResult.file_path}]`
    }
  }

  const isNewWorkspace = !codingStore.workspace
  const msgLower = (message || '').toLowerCase()
  const isDebugIntent = ['debug', '调试', '预览'].some(kw => msgLower.includes(kw))
  const isPublishIntent = ['发布', '打包', 'publish', 'build'].some(kw => msgLower.includes(kw))

  if (isDebugIntent && !isNewWorkspace) {
    codingStore.currentPipelineSteps = [
      { name: 'serve', label: '启动服务', status: 'pending' },
      { name: 'debug', label: '自动登录+截图', status: 'pending' },
      { name: 'verify', label: 'AI 验证', status: 'pending' },
    ]
  } else if (isPublishIntent && !isNewWorkspace) {
    codingStore.currentPipelineSteps = [
      { name: 'build', label: '构建打包', status: 'pending' },
    ]
  } else {
    codingStore.initPipelineSteps(isNewWorkspace)
  }

  try {
    const token = userStore.token
    // 确定 project_type：优先用点击建议时锁定的场景，其次用 URL query，最后用当前选中的 Tab
    const _sceneKey = pendingSceneCategory.value || activeSceneCategory.value
    const _projectType = sceneCategoryToProjectType[_sceneKey] || route.query.type as string || null
    pendingSceneCategory.value = null  // 重置

    const body: Record<string, any> = {
      message: finalMessage,
      workspace_id: codingStore.workspace?.id || null,
      conversation_id: codingStore.conversationId || null,
      app_id: (route.query.app_id as string) || null,
      project_id: currentProjectId.value || null,
      project_type: _projectType,
    }

    const response = await fetch('/api/coding/auto-pipeline', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify(body),
    })

    if (!response.ok) {
      const errBody = await response.json().catch(() => ({ detail: `HTTP ${response.status}` }))
      throw new Error(errBody.detail || `HTTP ${response.status}`)
    }

    const reader = response.body?.getReader()
    const decoder = new TextDecoder()
    let fullContent = ''
    let changedFiles: string[] = []
    let currentScreenshots: string[] = []

    if (reader) {
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || '' // keep incomplete line in buffer

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const data = line.slice(6).trim()
          if (!data || data === '[DONE]') continue

          try {
            const parsed = JSON.parse(data)

            if (parsed.type === 'step') {
              // Pipeline step event
              codingStore.updatePipelineStep(parsed.step, parsed.status, parsed.message)

              // If workspace was created, update store
              if (parsed.step === 'create_workspace' && parsed.status === 'done' && parsed.data) {
                // 后端返回 workspace_id，前端 store 需要 id
                const wsData = {
                  ...parsed.data,
                  id: parsed.data.workspace_id || parsed.data.id,
                }
                codingStore.setWorkspace(wsData)
                codingStore.workspacePath = parsed.data.workspace_path || null
                localStorage.setItem('coding_last_workspace_id', wsData.id)
                // 刷新左侧工作区列表
                try { await loadProjectWorkspaces() } catch {}

              }

              // If serve started, update store
              if (parsed.step === 'serve' && parsed.status === 'done' && parsed.data) {
                codingStore.serveRunning = true
                codingStore.serveUrl = parsed.data.url || null
              }

              scrollToBottom()
            } else if (parsed.type === 'content') {
              fullContent += parsed.content
              codingStore.streamContent = fullContent
              scrollToBottom()
            } else if (parsed.type === 'agent_thinking') {
              // Agent reasoning / text output
              fullContent += parsed.content + '\n'
              codingStore.streamContent = fullContent
              scrollToBottom()
            } else if (parsed.type === 'agent_tool') {
              // Agent tool call - show what tool is being used
              const toolDisplay = parsed.tool_display || parsed.tool
              const preview = parsed.input_preview || ''
              fullContent += `\n**${toolDisplay}**: ${preview}\n`
              codingStore.streamContent = fullContent
              scrollToBottom()
            } else if (parsed.type === 'agent_result') {
              // Agent tool result - show output preview
              if (parsed.is_error) {
                fullContent += `\n> Error: ${parsed.output_preview}\n`
              } else if (parsed.output_preview) {
                // Show truncated result for context
                const preview = parsed.output_preview.length > 200
                  ? parsed.output_preview.substring(0, 200) + '...'
                  : parsed.output_preview
                fullContent += `\n> ${preview}\n`
              }
              codingStore.streamContent = fullContent
              scrollToBottom()
            } else if (parsed.type === 'agent_done') {
              // Agent completed its loop
              if (parsed.result) {
                fullContent += '\n' + parsed.result + '\n'
                codingStore.streamContent = fullContent
              }
              if (parsed.cost_usd) {
                fullContent += `\n*Agent completed in ${parsed.num_turns || '?'} turns (cost: $${parsed.cost_usd.toFixed(4)})*\n`
                codingStore.streamContent = fullContent
              }
              scrollToBottom()
            } else if (parsed.type === 'agent_error') {
              // Agent error
              fullContent += `\n**Agent Error**: ${parsed.message}\n`
              codingStore.streamContent = fullContent
              scrollToBottom()
            } else if (parsed.type === 'files') {
              // File list from generation
              if (parsed.files && Array.isArray(parsed.files)) {
                changedFiles = parsed.files
              }
            } else if (parsed.type === 'screenshot') {
              // Store screenshot URL for display
              currentScreenshots.push(parsed.url)
            } else if (parsed.type === 'heartbeat') {
              // Agent 心跳，保持连接
              continue
            } else if (parsed.type === 'scene_detected') {
              codingStore.conversationId = parsed.conversation_id
            } else if (parsed.type === 'done') {
              codingStore.conversationId = parsed.conversation_id
              if (parsed.workspace_id && !codingStore.workspace) {
                try {
                  const ws = await codingApi.getWorkspace(parsed.workspace_id)
                  codingStore.setWorkspace(ws)
                  localStorage.setItem('coding_last_workspace_id', ws.id)
                } catch { /* ignore */ }
              }
            }
          } catch {
            // skip unparseable lines
          }
        }
      }
    }

    // Extract files from AI content if not provided via event
    if (changedFiles.length === 0) {
      const parsed = parseFilesFromContent(fullContent)
      changedFiles = parsed.map(f => f.path)
    }

    // Build preview HTML from generated edit.vue
    let previewHtml = ''
    if (changedFiles.length > 0) {
      const editFile = parseFilesFromContent(fullContent).find(f => f.path.includes('edit/') || f.path.includes('-edit.vue'))
      const settingFile = parseFilesFromContent(fullContent).find(f => f.path.includes('setting'))
      if (editFile) {
        previewHtml = buildPreviewHtml(editFile.content, settingFile?.content)
      }
    }

    // Build the assistant message
    const assistantMsg: ChatMessage = {
      role: 'assistant',
      content: fullContent,
      textContent: fullContent,
      pipelineSteps: [...codingStore.currentPipelineSteps],
      fileNames: changedFiles.map(f => getFileName(f)),
      previewHtml,
      screenshots: currentScreenshots.length > 0 ? currentScreenshots : undefined,
    } as any
    codingStore.addMessage(assistantMsg)

    // Refresh workspace file list
    if (codingStore.workspace) {
      try {
        await loadProjectWorkspaces()
      } catch { /* ignore */ }
    }

  } catch (error: any) {
    ElMessage.error(`处理失败: ${error.message}`)
    codingStore.addMessage({
      role: 'assistant',
      content: `处理失败: ${error.message}`,
      textContent: `处理失败: ${error.message}`,
    })
  } finally {
    codingStore.isProcessing = false
    codingStore.streamContent = ''
    codingStore.currentPipelineSteps = []
  }
}

// ============ Header Actions ============

async function openInVSCode() {
  if (!codingStore.workspace) return
  // 从后端获取工作区绝对路径
  try {
    const info = await codingApi.getWorkspace(codingStore.workspace.id)
    const absPath = info.workspace_path || `/Users/mars/Vibe Coding/apaas-builder-ai/workspaces/${codingStore.workspace.id}`
    // 尝试打开 VS Code（浏览器可能阻止 vscode:// 协议）
    window.location.href = `vscode://file${absPath}`
    // 同时复制路径到剪贴板作为备选
    try {
      await navigator.clipboard.writeText(absPath)
      ElMessage.success(`路径已复制: ${absPath}`)
    } catch {
      ElMessage.info(`VS Code 路径: ${absPath}`)
    }
  } catch {
    const fallbackPath = `/Users/mars/Vibe Coding/apaas-builder-ai/workspaces/${codingStore.workspace.id}`
    window.location.href = `vscode://file${fallbackPath}`
    ElMessage.info(`VS Code 路径: ${fallbackPath}`)
  }
}

async function publishProject() {
  if (!codingStore.workspace || isPublishing.value) return
  isPublishing.value = true
  try {
    const blob = await codingApi.publish(codingStore.workspace.id)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${codingStore.workspace.project_name}.zip`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('打包完成，已开始下载')
  } catch (error: any) {
    ElMessage.error(error.message || '发布失败')
  } finally {
    isPublishing.value = false
  }
}

function startNewWorkspace() {
  codingStore.reset()
  localStorage.removeItem('coding_last_workspace_id')
  // 回到欢迎页
}

async function deleteWorkspace(ws: WorkspaceInfo) {
  try {
    await codingApi.deleteWorkspace(ws.id)
    existingWorkspaces.value = existingWorkspaces.value.filter(w => w.id !== ws.id)
    // 如果删的是当前工作区，重置
    if (codingStore.workspace?.id === ws.id) {
      codingStore.reset()
      localStorage.removeItem('coding_last_workspace_id')
    }
    ElMessage.success('已删除')
  } catch (e: any) {
    ElMessage.error(e.message || '删除失败')
  }
}

function handleDebug(mode: string) {
  debugProject(mode as 'app' | 'platform')
}

async function debugProject(debugMode: 'app' | 'platform' = 'app') {
  if (!codingStore.workspace || isDebugging.value) return
  isDebugging.value = true
  try {
    const token = userStore.token
    const resp = await fetch(`/api/coding/workspace/${codingStore.workspace.id}/debug`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify({
        project_id: currentProjectId.value || null,
        platform_url: currentProject.value?.platform_url ? undefined : 'https://apaas-dev8.dfy.definesys.cn/platform/',
        tenant_id: currentProject.value?.platform_tenant_id || '566642786573484033',
        app_id: currentProject.value?.platform_app_id || '806997227284201472',
        debug_mode: debugMode,
      }),
    })
    const result = await resp.json()
    if (result.status === 'ok') {
      const modeLabel = debugMode === 'app' ? '应用前台' : '平台设计器'
      ElMessage.success(`Debug 已启动（${modeLabel}）！请在 Chromium 中登录后 F5 刷新`)
    } else {
      ElMessage.error(result.message || result.detail || 'Debug 启动失败')
    }
  } catch (error: any) {
    ElMessage.error(error.message || 'Debug 启动失败')
  } finally {
    isDebugging.value = false
  }
}

// ============ File Parsing ============

function parseFilesFromContent(content: string): GeneratedFile[] {
  const files: GeneratedFile[] = []
  const regex = /```(?:file|[\w]+):([^\n]+)\n([\s\S]*?)```/g
  let match
  while ((match = regex.exec(content)) !== null) {
    const path = match[1].trim()
    const fileContent = match[2].trim()
    if (path && fileContent) {
      files.push({ path, content: fileContent, language: detectLanguage(path) })
    }
  }
  return files
}

function detectLanguage(path: string): string {
  const extMap: Record<string, string> = {
    '.vue': 'vue', '.js': 'javascript', '.ts': 'typescript',
    '.json': 'json', '.css': 'css', '.scss': 'scss',
    '.java': 'java', '.py': 'python', '.groovy': 'groovy',
    '.xml': 'xml', '.html': 'html',
  }
  for (const [ext, lang] of Object.entries(extMap)) {
    if (path.endsWith(ext)) return lang
  }
  return 'text'
}

// ============ Preview Sandbox ============

function buildPreviewHtml(editVueContent: string, settingVueContent?: string): string {
  // 从 .vue SFC 中提取 template 和 script
  const templateMatch = editVueContent.match(/<template>([\s\S]*?)<\/template>/)
  const scriptMatch = editVueContent.match(/<script>([\s\S]*?)<\/script>/)
  const styleMatch = editVueContent.match(/<style[^>]*>([\s\S]*?)<\/style>/)

  if (!templateMatch) return ''

  const template = templateMatch[1]
    .replace(/<x-proxy-form-item[^>]*>/g, '<div class="mock-form-item">')
    .replace(/<\/x-proxy-form-item>/g, '</div>')

  let scriptBody = ''
  if (scriptMatch) {
    scriptBody = scriptMatch[1]
      .replace(/import\s+.*from\s+['"][^'"]+['"]/g, '')  // 移除 import
      .replace(/mixins:\s*\[[^\]]*\],?/g, '')             // 移除 mixins
      .replace(/export\s+default\s*/, 'var componentDef = ')
  }

  const style = styleMatch ? styleMatch[1] : ''

  // setting 组件预览
  let settingPreview = ''
  if (settingVueContent) {
    const stMatch = settingVueContent.match(/<template>([\s\S]*?)<\/template>/)
    if (stMatch) {
      settingPreview = `
        <div style="border-top:1px solid #eee;margin-top:16px;padding-top:12px;">
          <div style="font-size:12px;color:#999;margin-bottom:8px;">设置面板预览</div>
          <div id="setting-preview"></div>
        </div>`
    }
  }

  return `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <link rel="stylesheet" href="https://unpkg.com/element-ui@2.15.14/lib/theme-chalk/index.css">
  <script src="https://unpkg.com/vue@2.7.14/dist/vue.min.js"><\/script>
  <script src="https://unpkg.com/element-ui@2.15.14/lib/index.js"><\/script>
  <style>
    body { margin: 0; padding: 16px; font-family: -apple-system, sans-serif; background: #fff; }
    .mock-form-item { margin-bottom: 12px; }
    .mock-form-item label { display: block; font-size: 13px; color: #606266; margin-bottom: 4px; }
    ${style.replace(/:deep\(/g, '').replace(/\)/g, '')}
  </style>
</head>
<body>
  <div id="app">
    <div style="font-size:12px;color:#999;margin-bottom:12px;">编辑态预览 · aPaaS 沙箱</div>
    ${template}
    ${settingPreview}
  </div>
  <script>
    // Mock FormWidgetMixin data
    ${scriptBody || 'var componentDef = {}'}
    if (!componentDef.data) componentDef.data = function() { return {} }
    var origData = componentDef.data
    componentDef.data = function() {
      var d = typeof origData === 'function' ? origData.call(this) : (origData || {})
      d.formValue = d.formValue || ''
      return d
    }
    componentDef.computed = componentDef.computed || {}
    if (!componentDef.computed.formValue) {
      componentDef.computed.formValue = {
        get: function() { return this.$data._formValue || '' },
        set: function(v) { this.$set(this.$data, '_formValue', v) }
      }
    }
    componentDef.computed.widget = componentDef.computed.widget || function() { return { label: '示例字段', customComponentConfig: {} } }
    componentDef.computed.showRequired = componentDef.computed.showRequired || function() { return false }
    componentDef.computed.validatorRules = componentDef.computed.validatorRules || function() { return [] }
    componentDef.computed.validateKey = componentDef.computed.validateKey || function() { return '' }
    componentDef.computed.validateInfo = componentDef.computed.validateInfo || function() { return {} }
    componentDef.computed.webFormSettings = componentDef.computed.webFormSettings || function() { return {} }
    componentDef.computed.renderScene = componentDef.computed.renderScene || function() { return 'edit' }
    componentDef.computed.formData = componentDef.computed.formData || function() { return {} }
    componentDef.el = '#app'
    try { new Vue(componentDef) } catch(e) { document.getElementById('app').innerHTML = '<p style="color:#f56c6c">预览渲染失败: ' + e.message + '</p>' }
  <\/script>
</body>
</html>`
}

// ============ UI Helpers ============

function getFileName(path: string): string {
  return path.split('/').pop() || path
}

function stepIcon(step: PipelineStep): string {
  switch (step.status) {
    case 'pending': return '\u25CB'   // ○
    case 'running': return '\u25D4'   // ◔ (spinner-like)
    case 'done': return '\u2713'      // ✓
    case 'error': return '\u2717'     // ✗
    default: return '\u25CB'
  }
}

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function renderMarkdown(content: string): string {
  // 先处理 file 代码块（可折叠，默认展开显示代码）
  let result = content.replace(/```file:([^\n]+)\n([\s\S]*?)```/g, (_m, path: string, code: string) => {
    const fileName = path.trim().split('/').pop() || path.trim()
    const escapedCode = escapeHtml(code.trim())
    const lineCount = code.trim().split('\n').length
    return `<details class="code-block" open>
      <summary class="code-block-header">
        <span class="code-file-icon">📄</span>
        <span class="code-file-name">${escapeHtml(fileName)}</span>
        <span class="code-file-path">${escapeHtml(path.trim())}</span>
        <span class="code-line-count">${lineCount} 行</span>
      </summary>
      <pre><code>${escapedCode}</code></pre>
    </details>`
  })

  // 普通代码块
  result = result.replace(/```(\w*)\n([\s\S]*?)```/g, (_m, _lang: string, code: string) => {
    return `<pre class="code-inline"><code>${escapeHtml(code.trim())}</code></pre>`
  })

  // 行内代码
  result = result.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')
  // 粗体
  result = result.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  // 换行
  result = result.replace(/\n/g, '<br>')

  return result
}

function previewScreenshot(url: string) {
  window.open(url, '_blank')
}

function scrollToBottom() {
  nextTick(() => {
    scrollAnchor.value?.scrollIntoView({ behavior: 'smooth' })
  })
}

// Auto scroll when new messages appear
watch(() => codingStore.messages.length, () => {
  scrollToBottom()
})

// Cleanup on route change
watch(() => route.path, () => {
  if (!route.path.startsWith('/coding')) {
    codingStore.reset()
  }
})
</script>

<style scoped>
/* ============================================================
   CodingPage — Modern Dark Theme (MD3 aligned)
   Background: #0a0a0a | Sidebar: #111 | Card: #161622
   Brand gradient: linear-gradient(135deg, #7c3aed, #6366f1)
   ============================================================ */

.coding-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #0a0a0a;
  color: rgba(255, 255, 255, 0.9);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
}

/* ============ Body Layout ============ */
.coding-body {
  display: flex;
  flex: 1;
  overflow: hidden;
}

/* ============ Workspace Sidebar ============ */
.workspace-sidebar {
  width: 240px;
  flex-shrink: 0;
  border-right: 1px solid rgba(255, 255, 255, 0.06);
  background: #111;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  gap: 8px;
}

.sidebar-title {
  font-size: 11px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.4);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.sidebar-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px 10px;
}

.sidebar-group-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px 6px;
  cursor: pointer;
  user-select: none;
  margin-top: 4px;
}

.sidebar-group-header:first-child {
  margin-top: 0;
}

.sidebar-group-icon {
  font-size: 13px;
}

.sidebar-group-label {
  font-size: 11px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.45);
  text-transform: uppercase;
  letter-spacing: 0.03em;
  flex: 1;
}

.sidebar-group-count {
  font-size: 10px;
  color: rgba(255, 255, 255, 0.25);
  background: rgba(255, 255, 255, 0.06);
  padding: 1px 6px;
  border-radius: 8px;
  min-width: 18px;
  text-align: center;
}

.sidebar-group-arrow {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.25);
  transition: transform 0.2s ease;
  transform: rotate(-90deg);
}

.sidebar-group-arrow.collapsed {
  transform: rotate(-180deg);
}

.sidebar-ws-item {
  padding: 10px 12px;
  border-radius: 12px;
  cursor: pointer;
  margin-bottom: 4px;
  border: 1px solid transparent;
  transition: all 0.2s ease;
}

.sidebar-ws-item:hover {
  background: rgba(124, 58, 237, 0.08);
  border-color: rgba(124, 58, 237, 0.15);
}

.sidebar-ws-item.active {
  background: #161622;
  border-color: rgba(124, 58, 237, 0.3);
  box-shadow: 0 0 0 1px rgba(124, 58, 237, 0.15) inset;
}

.sidebar-ws-name {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.9);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 3px;
  font-weight: 500;
}

.sidebar-ws-meta {
  display: flex;
  align-items: center;
  justify-content: flex-end;
}

.sidebar-ws-del {
  font-size: 14px;
  padding: 0 4px;
  opacity: 0;
  transition: opacity 0.2s ease;
}

.sidebar-ws-item:hover .sidebar-ws-del {
  opacity: 1;
}

.sidebar-empty {
  text-align: center;
  color: rgba(255, 255, 255, 0.3);
  font-size: 12px;
  padding: 24px 0;
}

/* ============ Project Selector ============ */
.project-select {
  flex: 1;
}
.project-select :deep(.el-input__wrapper) {
  background: #161622;
  border-color: rgba(255, 255, 255, 0.06);
  box-shadow: none;
  border-radius: 10px;
  transition: border-color 0.2s ease;
}
.project-select :deep(.el-input__wrapper:hover) {
  border-color: rgba(124, 58, 237, 0.3);
}
.project-select :deep(.el-input__wrapper.is-focus) {
  border-color: #7c3aed;
  box-shadow: 0 0 0 2px rgba(124, 58, 237, 0.15);
}
.project-select :deep(.el-input__inner) {
  color: rgba(255, 255, 255, 0.9);
  font-size: 13px;
}

/* ============ Platform Status ============ */
.sidebar-platform-status {
  padding: 10px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
.platform-status-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.platform-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
.platform-dot.connected {
  background: #4ade80;
  box-shadow: 0 0 6px rgba(74, 222, 128, 0.4);
}
.platform-dot.disconnected {
  background: rgba(255, 255, 255, 0.2);
}
.platform-label {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.5);
}
.platform-config-btn {
  font-size: 11px;
  padding: 0;
  color: #7c3aed;
  transition: color 0.2s ease;
}
.platform-config-btn:hover {
  color: #a78bfa;
}

/* ============ Section Header ============ */
.sidebar-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px 6px;
}

/* ============ Empty Project Prompt ============ */
.sidebar-empty-project {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 20px;
  flex: 1;
}
.empty-icon {
  font-size: 36px;
  margin-bottom: 14px;
  opacity: 0.4;
}
.empty-text {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.4);
  margin-bottom: 18px;
}

/* ============ Sidebar Footer ============ */
.sidebar-footer {
  padding: 10px 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  margin-top: auto;
}
.sidebar-delete-btn {
  font-size: 11px;
  padding: 0;
  transition: color 0.2s ease;
}

/* ============ Main Content ============ */
.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
}

/* ============ Header ============ */
.coding-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  background: #111;
  height: 52px;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-title {
  font-size: 16px;
  font-weight: 700;
  background: linear-gradient(135deg, #7c3aed, #6366f1);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  margin: 0;
  letter-spacing: -0.01em;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.header-btn {
  border-color: rgba(255, 255, 255, 0.08);
  background: #161622;
  color: rgba(255, 255, 255, 0.7);
  border-radius: 10px;
  font-size: 13px;
  transition: all 0.2s ease;
}

.header-btn:hover {
  border-color: rgba(124, 58, 237, 0.3);
  background: rgba(124, 58, 237, 0.1);
  color: rgba(255, 255, 255, 0.95);
}

.debug-dropdown :deep(.el-button) {
  border-color: rgba(255, 255, 255, 0.08);
  background: #161622;
  color: rgba(255, 255, 255, 0.7);
  border-radius: 10px 0 0 10px;
  font-size: 13px;
}
.debug-dropdown :deep(.el-dropdown__caret-button) {
  border-color: rgba(255, 255, 255, 0.08);
  background: #161622;
  color: rgba(255, 255, 255, 0.7);
  border-radius: 0 10px 10px 0;
}
.debug-dropdown :deep(.el-button:hover),
.debug-dropdown :deep(.el-dropdown__caret-button:hover) {
  border-color: rgba(124, 58, 237, 0.3);
  background: rgba(124, 58, 237, 0.1);
  color: rgba(255, 255, 255, 0.95);
}

/* ============ Chat Area ============ */
.chat-area {
  flex: 1;
  overflow-y: auto;
  padding: 28px 0;
  display: flex;
  flex-direction: column;
  align-items: center;
}

/* ============ Welcome ============ */
.welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  flex: 1;
  padding: 60px 24px;
  text-align: center;
  max-width: 720px;
}

.welcome-icon {
  font-size: 52px;
  margin-bottom: 20px;
  filter: drop-shadow(0 0 24px rgba(124, 58, 237, 0.3));
}

.welcome h2 {
  font-size: 32px;
  font-weight: 800;
  margin: 0 0 14px;
  background: linear-gradient(135deg, #7c3aed, #6366f1);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  letter-spacing: -0.02em;
}

.welcome-desc {
  color: rgba(255, 255, 255, 0.5);
  font-size: 15px;
  margin: 0 0 24px;
  line-height: 1.7;
  max-width: 460px;
}

.scene-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  margin-bottom: 24px;
}

.scene-tab {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 7px 14px;
  border-radius: 20px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: transparent;
  color: rgba(255, 255, 255, 0.5);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.scene-tab:hover {
  border-color: rgba(124, 58, 237, 0.3);
  color: rgba(255, 255, 255, 0.8);
}

.scene-tab.active {
  border-color: rgba(124, 58, 237, 0.6);
  background: rgba(124, 58, 237, 0.15);
  color: #c4b5fd;
}

.scene-tab-icon {
  font-size: 14px;
}

.suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: center;
}

.suggestion-btn {
  padding: 11px 20px;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: #161622;
  color: rgba(255, 255, 255, 0.7);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.25s ease;
  line-height: 1.4;
}

.suggestion-btn:hover {
  border-color: rgba(124, 58, 237, 0.4);
  background: rgba(124, 58, 237, 0.1);
  color: rgba(255, 255, 255, 0.95);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(124, 58, 237, 0.15);
}

/* ============ Messages ============ */
.message {
  width: 100%;
  max-width: 780px;
  padding: 0 28px;
  margin-bottom: 24px;
}

.user-msg,
.assistant-msg {
  display: flex;
  gap: 14px;
  align-items: flex-start;
}

.msg-avatar {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  flex-shrink: 0;
  letter-spacing: -0.02em;
}

.user-avatar {
  background: #262630;
  color: rgba(255, 255, 255, 0.7);
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.assistant-avatar {
  background: linear-gradient(135deg, #7c3aed, #6366f1);
  color: #fff;
  box-shadow: 0 2px 8px rgba(124, 58, 237, 0.3);
}

.msg-bubble {
  flex: 1;
  min-width: 0;
}

.user-bubble {
  background: #161622;
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 14px;
  padding: 14px 18px;
  color: rgba(255, 255, 255, 0.9);
  font-size: 14px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}

.assistant-bubble {
  padding: 6px 0;
  font-size: 14px;
  line-height: 1.75;
  color: rgba(255, 255, 255, 0.82);
  border-left: 2px solid rgba(124, 58, 237, 0.25);
  padding-left: 16px;
}

/* ============ Pipeline Steps ============ */
.pipeline-steps {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
}

.step {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 500;
  border: 1px solid transparent;
  transition: all 0.2s ease;
  backdrop-filter: blur(4px);
}

.step.pending {
  background: rgba(255, 255, 255, 0.04);
  color: rgba(255, 255, 255, 0.35);
  border-color: rgba(255, 255, 255, 0.06);
}

.step.running {
  background: rgba(124, 58, 237, 0.12);
  color: #a78bfa;
  border-color: rgba(124, 58, 237, 0.25);
  animation: pulse-step 2s ease-in-out infinite;
}

.step.done {
  background: rgba(74, 222, 128, 0.08);
  color: #4ade80;
  border-color: rgba(74, 222, 128, 0.2);
}

.step.error {
  background: rgba(248, 113, 113, 0.08);
  color: #f87171;
  border-color: rgba(248, 113, 113, 0.2);
}

@keyframes pulse-step {
  0%, 100% {
    border-color: rgba(124, 58, 237, 0.25);
    box-shadow: 0 0 0 0 rgba(124, 58, 237, 0);
  }
  50% {
    border-color: rgba(124, 58, 237, 0.5);
    box-shadow: 0 0 8px rgba(124, 58, 237, 0.15);
  }
}

.step-icon {
  font-size: 13px;
  line-height: 1;
}

.step-label {
  white-space: nowrap;
}

/* ============ Message Text ============ */
.msg-text {
  word-break: break-word;
}

.msg-text :deep(.code-block) {
  margin: 14px 0;
  border-radius: 12px;
  overflow: hidden;
  background: #1a1a2e;
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.msg-text :deep(.code-block-header) {
  padding: 10px 14px;
  background: rgba(255, 255, 255, 0.03);
  font-size: 12px;
  color: rgba(255, 255, 255, 0.5);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 8px;
  user-select: none;
  list-style: none;
  transition: background 0.2s ease;
}

.msg-text :deep(.code-block-header:hover) {
  background: rgba(255, 255, 255, 0.05);
}

.msg-text :deep(.code-block-header::-webkit-details-marker) {
  display: none;
}

.msg-text :deep(.code-block-header::before) {
  content: '▶';
  font-size: 9px;
  color: rgba(255, 255, 255, 0.3);
  transition: transform 0.25s ease;
}

.msg-text :deep(.code-block[open] > .code-block-header::before) {
  transform: rotate(90deg);
}

.msg-text :deep(.code-file-icon) {
  font-size: 14px;
}

.msg-text :deep(.code-file-name) {
  font-weight: 600;
  color: #a78bfa;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
}

.msg-text :deep(.code-file-path) {
  color: rgba(255, 255, 255, 0.3);
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px;
  flex: 1;
}

.msg-text :deep(.code-line-count) {
  color: rgba(255, 255, 255, 0.25);
  font-size: 11px;
  white-space: nowrap;
}

.msg-text :deep(.code-block pre) {
  margin: 0;
  padding: 14px 18px;
  overflow-x: auto;
  max-height: 400px;
  overflow-y: auto;
}

.msg-text :deep(.code-block code) {
  font-size: 12.5px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  color: rgba(255, 255, 255, 0.78);
  line-height: 1.65;
}

.msg-text :deep(.code-inline) {
  margin: 8px 0;
  padding: 12px 14px;
  background: #1a1a2e;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  overflow-x: auto;
}

.msg-text :deep(.code-inline code) {
  font-size: 12.5px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  color: rgba(255, 255, 255, 0.78);
}

.msg-text :deep(.inline-code) {
  background: rgba(124, 58, 237, 0.12);
  padding: 2px 7px;
  border-radius: 6px;
  font-size: 12px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  color: #a78bfa;
}

/* ============ Inline Preview ============ */
.inline-preview {
  margin: 14px 0;
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: #161622;
}

.preview-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: rgba(255, 255, 255, 0.03);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  font-size: 13px;
  color: rgba(255, 255, 255, 0.6);
}

.preview-icon {
  font-size: 16px;
}

.preview-iframe {
  width: 100%;
  height: 280px;
  border: none;
  background: #fff;
  border-radius: 0 0 12px 12px;
}

/* ============ Debug Screenshots ============ */
.debug-screenshots {
  margin: 14px 0;
}

.screenshot-header {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.5);
  margin-bottom: 10px;
  font-weight: 500;
}

.debug-screenshot {
  max-width: 100%;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  cursor: pointer;
  transition: all 0.25s ease;
}

.debug-screenshot:hover {
  opacity: 0.9;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
}

/* ============ File Summary ============ */
.file-summary {
  margin-top: 12px;
  padding: 10px 14px;
  border-radius: 10px;
  background: #161622;
  border: 1px solid rgba(255, 255, 255, 0.06);
  font-size: 12px;
  color: rgba(255, 255, 255, 0.5);
}

.file-summary-icon {
  margin-right: 6px;
}

/* ============ Typing / Thinking ============ */
.typing-cursor {
  color: #7c3aed;
  animation: blink 1s step-end infinite;
}

@keyframes blink {
  50% { opacity: 0; }
}

.thinking-dots {
  display: flex;
  gap: 5px;
  padding: 10px 0;
}

.thinking-dots span {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #7c3aed;
  animation: thinking 1.4s ease-in-out infinite;
}

.thinking-dots span:nth-child(2) {
  animation-delay: 0.2s;
}

.thinking-dots span:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes thinking {
  0%, 80%, 100% { opacity: 0.2; transform: scale(0.7); }
  40% { opacity: 1; transform: scale(1); }
}

/* ============ Input Area ============ */
.input-area {
  flex-shrink: 0;
  padding: 14px 28px 18px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  background: #0a0a0a;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.input-wrapper {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  width: 100%;
  max-width: 780px;
  background: #161622;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 16px;
  padding: 10px 14px;
  transition: all 0.3s ease;
}

.input-wrapper:focus-within {
  border-color: transparent;
  background: linear-gradient(#161622, #161622) padding-box,
              linear-gradient(135deg, #7c3aed, #6366f1) border-box;
  border: 1px solid transparent;
  box-shadow: 0 0 16px rgba(124, 58, 237, 0.12);
}

.input-wrapper :deep(.el-textarea__inner) {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
  color: rgba(255, 255, 255, 0.9);
  font-size: 14px;
  line-height: 1.55;
  padding: 4px 0;
  resize: none;
}

.send-btn {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  background: linear-gradient(135deg, #7c3aed, #6366f1) !important;
  border: none !important;
  transition: all 0.2s ease;
}

.send-btn:hover:not(:disabled) {
  transform: scale(1.05);
  box-shadow: 0 2px 10px rgba(124, 58, 237, 0.4);
}

.send-btn:disabled {
  opacity: 0.4;
  background: rgba(255, 255, 255, 0.1) !important;
}

.attach-btn {
  flex-shrink: 0;
  color: rgba(255, 255, 255, 0.4);
  padding: 4px;
  transition: color 0.2s ease;
}

.attach-btn:hover {
  color: rgba(255, 255, 255, 0.8);
}

.input-hint {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.25);
  margin-top: 8px;
  letter-spacing: 0.01em;
}

/* ============ Attachment Preview ============ */
.attachment-preview {
  width: 100%;
  max-width: 780px;
  margin-bottom: 10px;
  padding: 10px 14px;
  background: #161622;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 14px;
  display: flex;
  align-items: center;
  gap: 10px;
}

.attachment-thumb {
  position: relative;
  display: inline-block;
}

.attachment-thumb img {
  width: 60px;
  height: 60px;
  object-fit: cover;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.attachment-file {
  display: flex;
  align-items: center;
  gap: 8px;
  color: rgba(255, 255, 255, 0.7);
  font-size: 13px;
}

.attachment-file-icon {
  font-size: 18px;
}

.attachment-file-name {
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.attachment-remove {
  background: rgba(255, 255, 255, 0.08);
  border: none;
  color: rgba(255, 255, 255, 0.5);
  cursor: pointer;
  font-size: 16px;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
  transition: all 0.2s ease;
}

.attachment-remove:hover {
  background: rgba(248, 113, 113, 0.2);
  color: #f87171;
}

.attachment-thumb .attachment-remove {
  position: absolute;
  top: -6px;
  right: -6px;
}

/* ============ Workspace Dialog ============ */
/* (old workspace dialog styles removed - now using sidebar) */

/* ============ Scrollbar ============ */
.chat-area::-webkit-scrollbar {
  width: 5px;
}

.chat-area::-webkit-scrollbar-track {
  background: transparent;
}

.chat-area::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.08);
  border-radius: 4px;
}

.chat-area::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.15);
}

.sidebar-list::-webkit-scrollbar {
  width: 4px;
}

.sidebar-list::-webkit-scrollbar-track {
  background: transparent;
}

.sidebar-list::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.06);
  border-radius: 4px;
}

/* ============ Element Plus Dark Overrides ============ */
.coding-page :deep(.el-tag--info) {
  background: rgba(124, 58, 237, 0.12);
  border-color: rgba(124, 58, 237, 0.2);
  color: #a78bfa;
}

.coding-page :deep(.el-button--primary) {
  background: linear-gradient(135deg, #7c3aed, #6366f1);
  border: none;
  transition: all 0.2s ease;
}

.coding-page :deep(.el-button--primary:hover) {
  box-shadow: 0 2px 10px rgba(124, 58, 237, 0.35);
  filter: brightness(1.1);
}

.coding-page :deep(.el-button--success) {
  background: rgba(74, 222, 128, 0.15);
  border-color: rgba(74, 222, 128, 0.3);
  color: #4ade80;
  transition: all 0.2s ease;
}

.coding-page :deep(.el-button--success:hover) {
  background: rgba(74, 222, 128, 0.25);
  border-color: rgba(74, 222, 128, 0.45);
}
</style>
