<template>
  <div class="coding-page">
    <!-- Header -->
    <header class="coding-header">
      <div class="header-left">
        <el-button text @click="$router.push('/chat')">
          <el-icon><ArrowLeft /></el-icon>
        </el-button>
        <h3 class="header-title">复杂开发智能体</h3>
        <el-tag
          v-if="codingStore.workspace"
          size="small"
          type="info"
          :title="workspaceTooltip(codingStore.workspace)"
        >
          {{ workspaceDisplayName(codingStore.workspace) }}
        </el-tag>
      </div>
      <div class="header-right">
        <ThemeToggle />
        <!-- 组件市场 - 暂时隐藏
        <el-button
          size="small"
          @click="$router.push('/marketplace')"
          class="header-btn"
        >
          <el-icon><Goods /></el-icon> 组件市场
        </el-button>
        -->
        <el-button
          v-if="codingStore.workspace"
          size="small"
          class="header-btn"
          @click="openInWebIDE()"
        >
          <el-icon><FolderOpened /></el-icon> 在 IDE 中打开
        </el-button>
        <el-button
          v-if="codingStore.workspace"
          size="small"
          type="success"
          :loading="isDebugging"
          class="header-btn"
          @click="handlePreview"
        >
          <el-icon><Monitor /></el-icon> Debug 预览
        </el-button>
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

    <div class="coding-body" :class="codingBodyClasses">
      <!-- Left Sidebar: Workspace List -->
      <aside class="workspace-sidebar">
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
                <div class="sidebar-ws-name" :title="workspaceTooltip(ws)">{{ workspaceDisplayName(ws) }}</div>
                <div v-if="workspaceCodeName(ws)" class="sidebar-ws-code">{{ workspaceCodeName(ws) }}</div>
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
      </aside>

      <!-- Main Content -->
      <div class="main-content">
    <div class="chat-area">
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
            <details v-if="msg.thinkingSummary" class="thinking-summary">
              <summary class="thinking-summary-header">思路摘要</summary>
              <div class="thinking-summary-body" v-html="renderLiveHtml(msg.thinkingSummary)"></div>
            </details>
            <details v-if="msg.activityFeed && msg.activityFeed.length" class="thinking-summary execution-trace">
              <summary class="thinking-summary-header">执行过程</summary>
              <div class="agent-activity-feed">
                <div
                  v-for="item in msg.activityFeed"
                  :key="item.id"
                  class="agent-activity-item"
                  :class="item.tone"
                >
                  <span class="agent-activity-badge">{{ item.label }}</span>
                  <span class="agent-activity-text">{{ item.description }}</span>
                </div>
              </div>
            </details>
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
            <div v-if="streamThinkingRaw || visibleLiveActivities.length || currentRunningStep" class="agent-live-panel">
              <div class="agent-live-header">
                <span class="agent-live-pulse"></span>
                <span>{{ liveStatusLabel }}</span>
              </div>
              <div v-if="liveStatusMeta" class="agent-live-meta">{{ liveStatusMeta }}</div>
              <div v-if="renderedThinkingHtml" class="agent-thinking-card">
                <div class="agent-thinking-title">当前思路</div>
                <div class="agent-thinking-text" v-html="renderedThinkingHtml"></div>
              </div>
              <div v-if="visibleLiveActivities.length" class="agent-activity-feed">
                <div
                  v-for="item in visibleLiveActivities"
                  :key="item.id"
                  class="agent-activity-item"
                  :class="item.tone"
                >
                  <span class="agent-activity-badge">{{ item.label }}</span>
                  <span class="agent-activity-text">{{ item.description }}</span>
                </div>
              </div>
            </div>
            <!-- Streaming text -->
            <div v-if="codingStore.streamContent" class="stream-log-label">执行日志</div>
            <div v-if="codingStore.streamContent" class="msg-text stream-log" v-html="renderedStreamHtml"></div>
            <span v-if="codingStore.streamContent || renderedThinkingHtml" class="typing-cursor">&#9608;</span>
            <div v-if="!codingStore.streamContent && !renderedThinkingHtml && !visibleLiveActivities.length && !codingStore.currentPipelineSteps.some(s => s.status === 'running')" class="thinking-dots">
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

      <!-- Preview Panel -->
      <aside v-if="showPreviewPanel" class="preview-panel" :class="previewPanelClasses">
        <div class="preview-panel-header">
          <div class="preview-panel-heading">
            <span class="preview-panel-title">{{ previewPanelTitle }}</span>
            <span v-if="codingStore.workspace" class="preview-panel-subtitle">{{ workspaceDisplayName(codingStore.workspace) }}</span>
          </div>
          <div class="preview-panel-actions">
            <el-button text size="small" :disabled="previewLoading" @click="refreshPreview" title="刷新预览">
              <el-icon><RefreshRight /></el-icon>
            </el-button>
            <el-button text size="small" @click="closePreviewPanel" title="关闭">
              ✕
            </el-button>
          </div>
        </div>
        <div v-if="previewLoading" class="preview-panel-loading">
          <div class="preview-panel-loading-card">
            <div class="preview-panel-loading-title">正在同步预览</div>
            <div class="preview-panel-loading-desc">正在为当前工作区构建最新预览环境，请稍候。</div>
          </div>
        </div>
        <iframe
          v-else-if="previewUrl"
          :key="previewKey"
          :src="previewUrl"
          class="preview-panel-iframe"
          frameborder="0"
          sandbox="allow-scripts allow-same-origin allow-popups"
        ></iframe>
        <div v-else class="preview-panel-empty">
          <div class="preview-panel-empty-title">预览尚未准备好</div>
          <div class="preview-panel-empty-desc">点击上方“Debug 预览”后，这里会显示当前工作区的实时效果。</div>
        </div>
      </aside>

    </div>
  </div>
</template>

<script setup lang="ts">
import { API_PREFIX } from '@/utils/request'
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, FolderOpened, Upload, TopRight, Monitor, Plus, Paperclip, RefreshRight } from '@element-plus/icons-vue'
import { useCodingStore } from '@/stores/coding'
import type { PipelineStep, ChatActivityItem, ChatMessage } from '@/stores/coding'
import { useUserStore } from '@/stores/user'
import { codingApi } from '@/api/coding'
import type { GeneratedFile, WorkspaceInfo, UploadResult } from '@/api/coding'
import { consumeSseResponse } from '@/utils/sse'
import ThemeToggle from '@/components/ThemeToggle.vue'

const route = useRoute()
const codingStore = useCodingStore()
const userStore = useUserStore()

const userInput = ref('')
const scrollAnchor = ref<HTMLElement>()

const existingWorkspaces = ref<WorkspaceInfo[]>([])
const isPublishing = ref(false)
const isDebugging = ref(false)
const showPreviewPanel = ref(false)
const previewLoading = ref(false)
const previewUrl = ref<string | null>(null)
const previewKey = ref(0) // 用于刷新 iframe
const previewWorkspaceId = ref<string | null>(null)
const previewProjectType = ref<string>('')
const effectivePreviewProjectType = computed(() => previewProjectType.value || codingStore.workspace?.project_type || '')
const previewPanelTitle = computed(() => {
  const projectType = effectivePreviewProjectType.value
  if (projectType === 'mobile-component') return '📱 移动端组件预览'
  if (projectType === 'mobile-page') return '📱 移动端页面预览'
  if (projectType === 'layout') return '📐 布局预览'
  if (projectType === 'menu-page' || projectType === 'form-page') return '🖥️ 页面预览'
  return '📦 组件预览'
})
const codingBodyClasses = computed(() => ({
  'has-preview': showPreviewPanel.value,
  'has-page-preview': showPreviewPanel.value && ['menu-page', 'form-page', 'layout'].includes(effectivePreviewProjectType.value),
  'has-mobile-preview': showPreviewPanel.value && (effectivePreviewProjectType.value === 'mobile-page' || effectivePreviewProjectType.value === 'mobile-component'),
}))
const previewPanelClasses = computed(() => ({
  'is-page-preview': ['menu-page', 'form-page', 'layout'].includes(effectivePreviewProjectType.value),
  'is-mobile-preview': effectivePreviewProjectType.value === 'mobile-page' || effectivePreviewProjectType.value === 'mobile-component',
}))
const SSE_DEBUG = import.meta.env.DEV
const streamThinkingRaw = ref('')
const liveClock = ref(Date.now())
const lastStreamEventAt = ref(0)
const lastProgressEventAt = ref(0)

type LiveActivityTone = ChatActivityItem['tone']
type LiveActivityItem = ChatActivityItem

const streamActivities = ref<LiveActivityItem[]>([])

function normalizeThinkingText(raw: string): string {
  return raw
    .replace(/<\/?think>/g, '')
    .replace(/\r\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

function renderLiveHtml(raw: string): string {
  if (!raw) return ''
  return raw
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\n/g, '<br>')
}

// 流式内容直接渲染，完成后再做 markdown
const renderedStreamHtml = computed(() => renderLiveHtml(codingStore.streamContent))
const visibleLiveActivities = computed(() => streamActivities.value.slice(-6))
const currentRunningStep = computed(() => codingStore.currentPipelineSteps.find(step => step.status === 'running') || null)
const effectiveThinkingText = computed(() => {
  const normalized = normalizeThinkingText(streamThinkingRaw.value)
  if (normalized) return normalized

  const latestActivity = visibleLiveActivities.value[visibleLiveActivities.value.length - 1]
  if (latestActivity) {
    if (latestActivity.label === '处理中') {
      return '我正在等待新的工具结果或下一步分析，很快继续推进。'
    }
    return `我正在处理这一步：${latestActivity.label}。${latestActivity.description || '很快会同步结果。'}`
  }

  if (currentRunningStep.value) {
    return `我正在${currentRunningStep.value.label}，很快会继续同步具体动作。`
  }

  return ''
})
const renderedThinkingHtml = computed(() => renderLiveHtml(effectiveThinkingText.value))
const liveStatusLabel = computed(() => {
  if (normalizeThinkingText(streamThinkingRaw.value)) return 'AI 正在分析实现方案'
  if (visibleLiveActivities.value.length) return 'AI 正在执行开发动作'
  if (currentRunningStep.value) return `AI 正在${currentRunningStep.value.label}`
  return 'AI 正在处理中'
})
const idleSeconds = computed(() => {
  if (!codingStore.isProcessing || !lastProgressEventAt.value) return 0
  return Math.max(0, Math.floor((liveClock.value - lastProgressEventAt.value) / 1000))
})
const liveStatusMeta = computed(() => {
  if (!codingStore.isProcessing) return ''
  if (idleSeconds.value < 4) return '持续接收执行反馈中'
  if (currentRunningStep.value) {
    return `已等待 ${idleSeconds.value}s，当前还在${currentRunningStep.value.label}阶段，通常是在等待模型返回下一步。`
  }
  if (visibleLiveActivities.value.length) {
    return `已等待 ${idleSeconds.value}s，没有卡住，通常是在等待下一轮分析或命令执行完成。`
  }
  return `已等待 ${idleSeconds.value}s，连接仍然保持中。`
})

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
    const group = groups[mapping.key]
    if (group) {
      group.items.push(ws)
    }
  }
  return Object.values(groups).sort((a, b) => a.order - b.order)
})

function workspaceDisplayName(ws: WorkspaceInfo | null | undefined) {
  if (!ws) return ''
  return ws.display_name?.trim() || ws.project_name
}

function workspaceCodeName(ws: WorkspaceInfo | null | undefined) {
  if (!ws || !ws.project_name) return ''
  const displayName = workspaceDisplayName(ws)
  return displayName !== ws.project_name ? ws.project_name : ''
}

function workspaceTooltip(ws: WorkspaceInfo | null | undefined) {
  if (!ws) return ''
  const displayName = workspaceDisplayName(ws)
  const codeName = workspaceCodeName(ws)
  return codeName ? `${displayName}\n${codeName}` : displayName
}

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
  // Load all workspaces
  try {
    existingWorkspaces.value = await codingApi.listWorkspaces()
  } catch (e) {
    console.error('获取工作区列表失败:', e)
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

    if (showPreviewPanel.value) {
      await openPreviewForWorkspace(ws.id, { silent: true })
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
  resetLiveAgentStream()
  markLiveStreamEvent(false)
  startLiveClock()

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
      project_type: _projectType,
    }

    const response = await fetch(`${API_PREFIX}/coding/auto-pipeline`, {
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

    let fullContent = ''
    let changedFiles: string[] = []
    let currentScreenshots: string[] = []
    let thinkingBuffer = ''
    let thinkingSummary = ''
    let expectingFreshThinking = true
    debugSseLog('[SSE] Stream connected, reading events...')

    await consumeSseResponse(response, async ({ data }) => {
      const payload = data.trim()
      if (!payload || payload === '[DONE]') {
        return
      }

      try {
        const parsed = JSON.parse(payload)
        debugSseLog(`[SSE] type=${parsed.type}`, parsed.type === 'heartbeat' ? '' : parsed)
        markLiveStreamEvent(parsed.type !== 'heartbeat')

        let shouldPaint = false

        if (parsed.type === 'step') {
          codingStore.updatePipelineStep(parsed.step, parsed.status, parsed.message)

          const stepLabel = stepLabelForName(parsed.step)
          if (stepLabel && parsed.status !== 'pending') {
            const tone: LiveActivityTone = parsed.status === 'error'
              ? 'error'
              : (parsed.status === 'done' ? 'success' : 'default')
            const description = parsed?.data?.message || parsed.message || stepStatusText(parsed.status)
            pushLiveActivity(stepLabel, description, tone)
          }

          if (parsed.step === 'create_workspace' && parsed.status === 'done' && parsed.data) {
            const wsData = {
              ...parsed.data,
              id: parsed.data.workspace_id || parsed.data.id,
            }
            codingStore.setWorkspace(wsData)
            codingStore.workspacePath = parsed.data.workspace_path || null
            localStorage.setItem('coding_last_workspace_id', wsData.id)
            try { existingWorkspaces.value = await codingApi.listWorkspaces() } catch {}
          }

          if (parsed.step === 'serve' && parsed.status === 'done' && parsed.data) {
            codingStore.serveRunning = true
            codingStore.serveUrl = parsed.data.url || null
          }

          shouldPaint = true
        } else if (parsed.type === 'content') {
          fullContent += parsed.content
          codingStore.streamContent = fullContent
          shouldPaint = true
        } else if (parsed.type === 'agent_thinking_delta') {
          const chunk = typeof parsed.content === 'string' ? parsed.content : ''
          if (!chunk) return
          if (expectingFreshThinking) {
            thinkingBuffer = ''
            expectingFreshThinking = false
          }
          thinkingBuffer += chunk
          const normalized = normalizeThinkingText(thinkingBuffer)
          if (normalized) {
            thinkingSummary = normalized
            streamThinkingRaw.value = thinkingBuffer
            shouldPaint = true
          }
        } else if (parsed.type === 'agent_thinking') {
          const rawThinking = typeof parsed.content === 'string' ? parsed.content : ''
          if (!rawThinking) return
          if (expectingFreshThinking) {
            thinkingBuffer = rawThinking
            expectingFreshThinking = false
          } else if (normalizeThinkingText(rawThinking).length >= normalizeThinkingText(thinkingBuffer).length) {
            thinkingBuffer = rawThinking
          }
          const normalized = normalizeThinkingText(thinkingBuffer)
          if (normalized) {
            thinkingSummary = normalized
            streamThinkingRaw.value = thinkingBuffer
            shouldPaint = true
          }
        } else if (parsed.type === 'agent_tool') {
          const toolDisplay = parsed.tool_display || parsed.tool
          const preview = parsed.input_preview || ''
          fullContent += `\n🔧 **${toolDisplay}** \`${preview}\`\n`
          codingStore.streamContent = fullContent
          pushLiveActivity(toolDisplay, preview || '开始执行', 'default')
          expectingFreshThinking = true
          shouldPaint = true
        } else if (parsed.type === 'agent_result') {
          const preview = parsed.output_preview && parsed.output_preview !== '(empty)'
            ? (parsed.output_preview.length > 140 ? `${parsed.output_preview.substring(0, 140)}...` : parsed.output_preview)
            : '执行完成'
          if (parsed.is_error) {
            fullContent += `> ❌ ${parsed.output_preview}\n\n`
          } else if (parsed.output_preview && parsed.output_preview !== '(empty)') {
            const resultPreview = parsed.output_preview.length > 300
              ? parsed.output_preview.substring(0, 300) + '...'
              : parsed.output_preview
            fullContent += `> ✅ ${resultPreview}\n\n`
          } else {
            fullContent += '> ✅ 完成\n\n'
          }
          codingStore.streamContent = fullContent
          pushLiveActivity(
            parsed.tool_display || parsed.tool || '执行结果',
            preview,
            parsed.is_error ? 'error' : 'success',
          )
          expectingFreshThinking = true
          shouldPaint = true
        } else if (parsed.type === 'agent_command_output') {
          const chunk = typeof parsed.chunk === 'string' ? parsed.chunk : ''
          if (!chunk) return
          fullContent += chunk
          codingStore.streamContent = fullContent
          shouldPaint = true
        } else if (parsed.type === 'agent_done') {
          const turns = parsed.num_turns || '?'
          fullContent += `\n---\n✨ **Agent 完成** (${turns} 轮对话)\n`
          codingStore.streamContent = fullContent
          pushLiveActivity('完成', `Agent 已完成 ${turns} 轮对话`, 'success')
          shouldPaint = true
        } else if (parsed.type === 'agent_error') {
          fullContent += `\n❌ **Agent 错误**: ${parsed.message}\n`
          codingStore.streamContent = fullContent
          pushLiveActivity('错误', parsed.message || '发生未知错误', 'error')
          shouldPaint = true
        } else if (parsed.type === 'files') {
          if (parsed.files && Array.isArray(parsed.files)) {
            changedFiles = parsed.files
          }
        } else if (parsed.type === 'screenshot') {
          currentScreenshots.push(parsed.url)
        } else if (parsed.type === 'heartbeat') {
          if (!streamThinkingRaw.value && !visibleLiveActivities.value.length) {
            pushLiveActivity('处理中', '正在等待下一步分析或工具执行', 'default')
            shouldPaint = true
          }
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

        if (shouldPaint) {
          scrollToBottom()
          await nextTick()
          await waitForStreamPaint()
        }
      } catch {
        // skip unparseable events
      }
    }, { yieldEvery: 6 })

    debugSseLog('[SSE] Stream ended (consumeSseResponse finished)')

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
      thinkingSummary: thinkingSummary || effectiveThinkingText.value || undefined,
      pipelineSteps: [...codingStore.currentPipelineSteps],
      fileNames: changedFiles.map(f => getFileName(f)),
      previewHtml,
      screenshots: currentScreenshots.length > 0 ? currentScreenshots : undefined,
      activityFeed: streamActivities.value.map(item => ({ ...item })),
    }
    codingStore.addMessage(assistantMsg)

    // Refresh workspace file list
    if (codingStore.workspace) {
      try {
        existingWorkspaces.value = await codingApi.listWorkspaces()
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
    resetLiveAgentStream()
    stopLiveClock()
  }
}

// ============ Header Actions ============

async function openInWebIDE() {
  if (!codingStore.workspace) return
  try {
    const { ide_url } = await codingApi.getIdeUrl(codingStore.workspace.id)
    window.open(ide_url, '_blank')
  } catch (err: any) {
    const msg = err?.response?.data?.detail || err?.message || 'Web IDE 打开失败，请检查 CODE_SERVER_BASE_URL 配置'
    ElMessage.warning(msg)
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
    a.download = `${workspaceDisplayName(codingStore.workspace) || codingStore.workspace.project_name}.zip`
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
  closePreviewPanel()
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
      closePreviewPanel()
    }
    ElMessage.success('已删除')
  } catch (e: any) {
    ElMessage.error(e.message || '删除失败')
  }
}

async function openPreviewForWorkspace(wsId: string, options?: { silent?: boolean }) {
  if (!wsId || isDebugging.value) return
  const silent = options?.silent ?? false
  isDebugging.value = true
  previewLoading.value = true
  showPreviewPanel.value = true
  previewUrl.value = null
  previewWorkspaceId.value = wsId
  previewProjectType.value = codingStore.workspace?.project_type || previewProjectType.value
  try {
    const result = await codingApi.preview(wsId)
    if (result.status === 'ok') {
      // preview_url 已经是 /api/coding/... 格式，用 BASE_URL 拼接即可
      const basePath = import.meta.env.BASE_URL || '/'
      previewUrl.value = basePath + result.preview_url.replace(/^\//, '')
      previewWorkspaceId.value = wsId
      previewProjectType.value = result.project_type || codingStore.workspace?.project_type || ''
      previewKey.value++
      if (!silent) {
        ElMessage.success(result.build_message || '预览已就绪')
      }
    } else {
      previewUrl.value = null
      ElMessage.error('预览构建失败')
    }
  } catch (error: any) {
    previewUrl.value = null
    ElMessage.error(error?.response?.data?.detail || error.message || '预览失败')
  } finally {
    isDebugging.value = false
    previewLoading.value = false
  }
}

async function handlePreview() {
  if (!codingStore.workspace) return
  await openPreviewForWorkspace(codingStore.workspace.id)
}

async function refreshPreview() {
  const targetWsId = codingStore.workspace?.id || previewWorkspaceId.value
  if (!targetWsId) return
  await openPreviewForWorkspace(targetWsId, { silent: true })
}

function closePreviewPanel() {
  showPreviewPanel.value = false
  previewLoading.value = false
  previewUrl.value = null
  previewWorkspaceId.value = null
  previewProjectType.value = ''
}

// ============ File Parsing ============

function parseFilesFromContent(content: string): GeneratedFile[] {
  const files: GeneratedFile[] = []
  const regex = /```(?:file|[\w]+):([^\n]+)\n([\s\S]*?)```/g
  let match: RegExpExecArray | null
  while ((match = regex.exec(content)) !== null) {
    const path = match[1]?.trim() || ''
    const fileContent = match[2]?.trim() || ''
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

  const template = (templateMatch[1] || '')
    .replace(/<x-proxy-form-item[^>]*>/g, '<div class="mock-form-item">')
    .replace(/<\/x-proxy-form-item>/g, '</div>')

  let scriptBody = ''
  if (scriptMatch) {
    scriptBody = (scriptMatch[1] || '')
      .replace(/import\s+.*from\s+['"][^'"]+['"]/g, '')  // 移除 import
      .replace(/mixins:\s*\[[^\]]*\],?/g, '')             // 移除 mixins
      .replace(/export\s+default\s*/, 'var componentDef = ')
  }

  const style = styleMatch?.[1] || ''

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

function stepLabelForName(stepName: string): string {
  const current = codingStore.currentPipelineSteps.find(step => step.name === stepName)
  if (current?.label) return current.label

  const fallbackMap: Record<string, string> = {
    detect_scene: '识别场景',
    create_workspace: '创建工作区',
    generate: '生成代码',
    install: '安装依赖',
    serve: '启动服务',
    hot_reload: '热更新',
    debug: '调试验证',
    verify: 'AI 验证',
    build: '构建打包',
  }

  return fallbackMap[stepName] || stepName
}

function stepStatusText(status: PipelineStep['status']): string {
  switch (status) {
    case 'running': return '正在执行'
    case 'done': return '已完成'
    case 'error': return '执行失败'
    default: return '等待中'
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
  // Strip <think>...</think> tags (MiniMax thinking output)
  let safeContent = content.replace(/<think>[\s\S]*?<\/think>/g, '').replace(/<\/?think>/g, '')
  const backtickCount = (safeContent.match(/```/g) || []).length
  if (backtickCount % 2 !== 0) {
    // Odd number of ``` means unclosed block — add closing
    safeContent += '\n```'
  }

  // 先处理 file 代码块（可折叠，默认展开显示代码）
  let result = safeContent.replace(/```file:([^\n]+)\n([\s\S]*?)```/g, (_m, path: string, code: string) => {
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

function resetLiveAgentStream() {
  streamThinkingRaw.value = ''
  streamActivities.value = []
  liveClock.value = Date.now()
  lastStreamEventAt.value = 0
  lastProgressEventAt.value = 0
}

function pushLiveActivity(label: string, description: string, tone: LiveActivityTone = 'default') {
  streamActivities.value = [
    ...streamActivities.value,
    {
      id: Date.now() + streamActivities.value.length,
      label,
      description,
      tone,
    },
  ].slice(-10)
}

function markLiveStreamEvent(hasProgress = true) {
  const now = Date.now()
  liveClock.value = now
  lastStreamEventAt.value = now
  if (hasProgress) {
    lastProgressEventAt.value = now
  }
}

let liveClockTimer: ReturnType<typeof setInterval> | null = null

function startLiveClock() {
  if (liveClockTimer) return
  liveClockTimer = setInterval(() => {
    liveClock.value = Date.now()
  }, 1000)
}

function stopLiveClock() {
  if (!liveClockTimer) return
  clearInterval(liveClockTimer)
  liveClockTimer = null
}

function debugSseLog(...args: unknown[]) {
  if (SSE_DEBUG) {
    console.log(...args)
  }
}

function waitForStreamPaint(): Promise<void> {
  if (typeof window === 'undefined' || typeof window.requestAnimationFrame !== 'function') {
    return Promise.resolve()
  }

  return new Promise((resolve) => {
    window.requestAnimationFrame(() => resolve())
  })
}

let _scrollTimer: ReturnType<typeof setTimeout> | null = null
function scrollToBottom() {
  // Debounce scroll to avoid animation stacking during rapid SSE events
  if (_scrollTimer) clearTimeout(_scrollTimer)
  _scrollTimer = setTimeout(() => {
    nextTick(() => {
      scrollAnchor.value?.scrollIntoView({ behavior: 'auto' })
    })
  }, 100)
}

// Auto scroll when new messages appear
watch(() => codingStore.messages.length, () => {
  scrollToBottom()
})

// Cleanup on route change
watch(() => route.path, () => {
  if (!route.path.startsWith('/coding')) {
    codingStore.reset()
    resetLiveAgentStream()
    stopLiveClock()
  }
})

watch(() => codingStore.isProcessing, (processing) => {
  if (processing) {
    startLiveClock()
  } else {
    stopLiveClock()
  }
})

onUnmounted(() => {
  stopLiveClock()
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
  background: var(--t-bg-base);
  color: var(--t-text-primary);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
}

/* ============ Body Layout ============ */
.coding-body {
  display: flex;
  flex: 1;
  overflow: hidden;
  --workspace-sidebar-width: 228px;
  --preview-panel-width: 480px;
}

/* ============ Workspace Sidebar ============ */
.workspace-sidebar {
  width: var(--workspace-sidebar-width);
  flex-shrink: 0;
  border-right: 1px solid var(--t-border-subtle);
  background: var(--t-bg-base);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: width 0.22s ease;
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid var(--t-border-subtle);
  gap: 8px;
}

.sidebar-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--t-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.sidebar-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px 10px;
  transition: padding 0.22s ease;
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
  color: var(--t-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.03em;
  flex: 1;
}

.sidebar-group-count {
  font-size: 10px;
  color: var(--t-text-muted);
  background: var(--t-border-subtle);
  padding: 1px 6px;
  border-radius: 8px;
  min-width: 18px;
  text-align: center;
}

.sidebar-group-arrow {
  font-size: 12px;
  color: var(--t-text-muted);
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
  background: var(--t-brand-subtle);
  border-color: var(--t-brand-subtle);
}

.sidebar-ws-item.active {
  background: var(--t-bg-elevated);
  border-color: var(--t-brand-glow);
  box-shadow: 0 0 0 1px var(--t-brand-subtle) inset;
}

.sidebar-ws-name {
  font-size: 13px;
  color: var(--t-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 3px;
  font-weight: 500;
}

.sidebar-ws-code {
  font-size: 11px;
  line-height: 1.3;
  color: var(--t-text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
}

.coding-body.has-preview {
  --workspace-sidebar-width: 188px;
  --preview-panel-width: clamp(520px, 36vw, 680px);
}

.coding-body.has-preview.has-page-preview {
  --workspace-sidebar-width: 176px;
  --preview-panel-width: clamp(620px, 44vw, 860px);
}

.coding-body.has-preview.has-mobile-preview {
  --preview-panel-width: clamp(560px, 38vw, 720px);
}

.coding-body.has-preview .sidebar-section-header {
  padding: 10px 12px 6px;
}

.coding-body.has-preview .sidebar-list {
  padding: 8px;
}

.coding-body.has-preview .sidebar-group-header {
  padding: 7px 8px 5px;
  gap: 5px;
}

.coding-body.has-preview .sidebar-group-label {
  font-size: 10px;
}

.coding-body.has-preview .sidebar-ws-item {
  padding: 9px 10px;
  border-radius: 10px;
}

.coding-body.has-preview .sidebar-ws-name {
  font-size: 12px;
}

.coding-body.has-preview .sidebar-ws-code {
  font-size: 10px;
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
  color: var(--t-text-muted);
  font-size: 12px;
  padding: 24px 0;
}

/* ============ Project Selector ============ */
.project-select {
  flex: 1;
}
.project-select :deep(.el-input__wrapper) {
  background: var(--t-bg-elevated);
  border-color: var(--t-border-subtle);
  box-shadow: none;
  border-radius: 10px;
  transition: border-color 0.2s ease;
}
.project-select :deep(.el-input__wrapper:hover) {
  border-color: var(--t-brand-glow);
}
.project-select :deep(.el-input__wrapper.is-focus) {
  border-color: var(--t-brand);
  box-shadow: 0 0 0 2px var(--t-brand-subtle);
}
.project-select :deep(.el-input__inner) {
  color: var(--t-text-primary);
  font-size: 13px;
}

/* ============ Platform Status ============ */
.sidebar-platform-status {
  padding: 10px 16px;
  border-bottom: 1px solid var(--t-border-subtle);
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
  background: var(--t-success);
  box-shadow: 0 0 6px rgba(74, 222, 128, 0.4);
}
.platform-dot.disconnected {
  background: rgba(255, 255, 255, 0.2);
}
.platform-label {
  font-size: 11px;
  color: var(--t-text-secondary);
}
.platform-config-btn {
  font-size: 11px;
  padding: 0;
  color: var(--t-brand);
  transition: color 0.2s ease;
}
.platform-config-btn:hover {
  color: var(--t-brand-light);
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
  color: var(--t-text-muted);
  margin-bottom: 18px;
}

/* ============ Sidebar Footer ============ */
.sidebar-footer {
  padding: 10px 16px;
  border-top: 1px solid var(--t-border-subtle);
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
  border-bottom: 1px solid var(--t-border-subtle);
  background: var(--t-bg-base);
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
  background: var(--t-brand-gradient);
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
  border-color: var(--t-border-subtle);
  background: var(--t-bg-elevated);
  color: var(--t-text-secondary);
  border-radius: 10px;
  font-size: 13px;
  transition: all 0.2s ease;
}

.header-btn:hover {
  border-color: var(--t-brand-glow);
  background: var(--t-brand-subtle);
  color: var(--t-text-primary);
}

.debug-dropdown :deep(.el-button) {
  border-color: var(--t-border-subtle);
  background: var(--t-bg-elevated);
  color: var(--t-text-secondary);
  border-radius: 10px 0 0 10px;
  font-size: 13px;
}
.debug-dropdown :deep(.el-dropdown__caret-button) {
  border-color: var(--t-border-subtle);
  background: var(--t-bg-elevated);
  color: var(--t-text-secondary);
  border-radius: 0 10px 10px 0;
}
.debug-dropdown :deep(.el-button:hover),
.debug-dropdown :deep(.el-dropdown__caret-button:hover) {
  border-color: var(--t-brand-glow);
  background: var(--t-brand-subtle);
  color: var(--t-text-primary);
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
  filter: drop-shadow(0 0 24px var(--t-brand-glow));
}

.welcome h2 {
  font-size: 32px;
  font-weight: 800;
  margin: 0 0 14px;
  background: var(--t-brand-gradient);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  letter-spacing: -0.02em;
}

.welcome-desc {
  color: var(--t-text-secondary);
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
  border: 1px solid var(--t-border-subtle);
  background: transparent;
  color: var(--t-text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.scene-tab:hover {
  border-color: var(--t-brand-glow);
  color: var(--t-text-primary);
}

.scene-tab.active {
  border-color: var(--t-brand);
  background: var(--t-brand-subtle);
  color: var(--t-brand-light);
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
  border: 1px solid var(--t-border-subtle);
  background: var(--t-bg-elevated);
  color: var(--t-text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.25s ease;
  line-height: 1.4;
}

.suggestion-btn:hover {
  border-color: var(--t-brand-glow);
  background: var(--t-brand-subtle);
  color: var(--t-text-primary);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px var(--t-brand-subtle);
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
  background: var(--t-bg-panel-hover);
  color: var(--t-text-secondary);
  border: 1px solid var(--t-border-subtle);
}

.assistant-avatar {
  background: var(--t-brand-gradient);
  color: #fff;
  box-shadow: 0 2px 8px var(--t-brand-glow);
}

.msg-bubble {
  flex: 1;
  min-width: 0;
}

.user-bubble {
  background: var(--t-bg-elevated);
  border: 1px solid var(--t-border-subtle);
  border-radius: 14px;
  padding: 14px 18px;
  color: var(--t-text-primary);
  font-size: 14px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}

.assistant-bubble {
  padding: 6px 0;
  font-size: 14px;
  line-height: 1.75;
  color: var(--t-text-primary);
  border-left: 2px solid var(--t-brand-glow);
  padding-left: 16px;
}

/* ============ Pipeline Steps ============ */
.pipeline-steps {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
}

.agent-live-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 14px;
}

.agent-live-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--t-text-secondary);
  letter-spacing: 0.02em;
}

.agent-live-meta {
  margin-top: -2px;
  font-size: 12px;
  color: var(--t-text-muted);
  line-height: 1.6;
}

.agent-live-pulse {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--t-brand);
  box-shadow: 0 0 0 0 rgba(124, 58, 237, 0.45);
  animation: live-pulse 1.8s ease-in-out infinite;
}

.agent-thinking-card,
.thinking-summary {
  border: 1px solid rgba(124, 58, 237, 0.16);
  background: linear-gradient(180deg, rgba(124, 58, 237, 0.08), rgba(99, 102, 241, 0.04));
  border-radius: 14px;
  padding: 12px 14px;
}

.agent-thinking-title,
.thinking-summary-header {
  font-size: 12px;
  font-weight: 600;
  color: var(--t-brand-light);
  margin-bottom: 8px;
}

.thinking-summary {
  margin-bottom: 12px;
}

.thinking-summary-header {
  cursor: pointer;
  list-style: none;
  margin-bottom: 0;
}

.thinking-summary-header::-webkit-details-marker {
  display: none;
}

.thinking-summary-body,
.agent-thinking-text {
  margin-top: 8px;
  color: var(--t-text-primary);
  line-height: 1.75;
}

.agent-activity-feed {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.agent-activity-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid var(--t-border-subtle);
  background: rgba(255, 255, 255, 0.02);
}

.agent-activity-item.success {
  border-color: rgba(74, 222, 128, 0.22);
  background: rgba(74, 222, 128, 0.06);
}

.agent-activity-item.error {
  border-color: rgba(248, 113, 113, 0.22);
  background: rgba(248, 113, 113, 0.06);
}

.agent-activity-badge {
  flex-shrink: 0;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  line-height: 1.6;
  background: var(--t-brand-subtle);
  color: var(--t-brand-light);
}

.agent-activity-item.success .agent-activity-badge {
  background: rgba(74, 222, 128, 0.14);
  color: var(--t-success);
}

.agent-activity-item.error .agent-activity-badge {
  background: rgba(248, 113, 113, 0.14);
  color: #fda4af;
}

.agent-activity-text {
  color: var(--t-text-secondary);
  line-height: 1.65;
  word-break: break-word;
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
  background: var(--t-bg-subtle);
  color: var(--t-text-muted);
  border-color: var(--t-border-subtle);
}

.step.running {
  background: var(--t-brand-subtle);
  color: var(--t-brand-light);
  border-color: var(--t-brand-glow);
  animation: pulse-step 2s ease-in-out infinite;
}

.step.done {
  background: rgba(74, 222, 128, 0.08);
  color: var(--t-success);
  border-color: rgba(74, 222, 128, 0.2);
}

.step.error {
  background: rgba(248, 113, 113, 0.08);
  color: var(--t-danger);
  border-color: rgba(248, 113, 113, 0.2);
}

@keyframes pulse-step {
  0%, 100% {
    border-color: var(--t-brand-glow);
    box-shadow: 0 0 0 0 transparent;
  }
  50% {
    border-color: var(--t-brand);
    box-shadow: 0 0 8px var(--t-brand-subtle);
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

.stream-log-label {
  margin: 4px 0 8px;
  font-size: 11px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--t-text-muted);
}

.stream-log {
  padding-top: 2px;
}

.msg-text :deep(.code-block) {
  margin: 14px 0;
  border-radius: 12px;
  overflow: hidden;
  background: var(--t-bg-panel);
  border: 1px solid var(--t-border-subtle);
}

.msg-text :deep(.code-block-header) {
  padding: 10px 14px;
  background: var(--t-bg-subtle);
  font-size: 12px;
  color: var(--t-text-secondary);
  border-bottom: 1px solid var(--t-border-subtle);
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 8px;
  user-select: none;
  list-style: none;
  transition: background 0.2s ease;
}

.msg-text :deep(.code-block-header:hover) {
  background: var(--t-bg-subtle);
}

.msg-text :deep(.code-block-header::-webkit-details-marker) {
  display: none;
}

.msg-text :deep(.code-block-header::before) {
  content: '▶';
  font-size: 9px;
  color: var(--t-text-muted);
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
  color: var(--t-brand-light);
  font-family: 'SF Mono', Menlo, Consolas, monospace;
}

.msg-text :deep(.code-file-path) {
  color: var(--t-text-muted);
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px;
  flex: 1;
}

.msg-text :deep(.code-line-count) {
  color: var(--t-text-muted);
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
  color: var(--t-text-primary);
  line-height: 1.65;
}

.msg-text :deep(.code-inline) {
  margin: 8px 0;
  padding: 12px 14px;
  background: var(--t-bg-panel);
  border-radius: 10px;
  border: 1px solid var(--t-border-subtle);
  overflow-x: auto;
}

.msg-text :deep(.code-inline code) {
  font-size: 12.5px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  color: var(--t-text-primary);
}

.msg-text :deep(.inline-code) {
  background: var(--t-brand-subtle);
  padding: 2px 7px;
  border-radius: 6px;
  font-size: 12px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  color: var(--t-brand-light);
}

/* ============ Inline Preview ============ */
.inline-preview {
  margin: 14px 0;
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid var(--t-border-subtle);
  background: var(--t-bg-elevated);
}

.preview-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: var(--t-bg-subtle);
  border-bottom: 1px solid var(--t-border-subtle);
  font-size: 13px;
  color: var(--t-text-secondary);
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
  color: var(--t-text-secondary);
  margin-bottom: 10px;
  font-weight: 500;
}

.debug-screenshot {
  max-width: 100%;
  border-radius: 12px;
  border: 1px solid var(--t-border-subtle);
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
  background: var(--t-bg-elevated);
  border: 1px solid var(--t-border-subtle);
  font-size: 12px;
  color: var(--t-text-secondary);
}

.file-summary-icon {
  margin-right: 6px;
}

/* ============ Typing / Thinking ============ */
.typing-cursor {
  color: var(--t-brand);
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
  background: var(--t-brand);
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

@keyframes live-pulse {
  0% {
    box-shadow: 0 0 0 0 rgba(124, 58, 237, 0.45);
    transform: scale(0.95);
  }
  70% {
    box-shadow: 0 0 0 10px rgba(124, 58, 237, 0);
    transform: scale(1);
  }
  100% {
    box-shadow: 0 0 0 0 rgba(124, 58, 237, 0);
    transform: scale(0.95);
  }
}

/* ============ Input Area ============ */
.input-area {
  flex-shrink: 0;
  padding: 14px 28px 18px;
  border-top: 1px solid var(--t-border-subtle);
  background: var(--t-bg-base);
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
  background: var(--t-bg-elevated);
  border: 1px solid var(--t-border-subtle);
  border-radius: 16px;
  padding: 10px 14px;
  transition: all 0.3s ease;
}

.input-wrapper:focus-within {
  border-color: transparent;
  background: linear-gradient(var(--t-bg-elevated), var(--t-bg-elevated)) padding-box,
              var(--t-brand-gradient) border-box;
  border: 1px solid transparent;
  box-shadow: 0 0 16px var(--t-brand-subtle);
}

.input-wrapper :deep(.el-textarea__inner) {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
  color: var(--t-text-primary);
  font-size: 14px;
  line-height: 1.55;
  padding: 4px 0;
  resize: none;
}

.send-btn {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  background: var(--t-brand-gradient) !important;
  border: none !important;
  transition: all 0.2s ease;
}

.send-btn:hover:not(:disabled) {
  transform: scale(1.05);
  box-shadow: 0 2px 10px var(--t-brand-glow);
}

.send-btn:disabled {
  opacity: 0.4;
  background: var(--t-border-subtle) !important;
}

.attach-btn {
  flex-shrink: 0;
  color: var(--t-text-muted);
  padding: 4px;
  transition: color 0.2s ease;
}

.attach-btn:hover {
  color: var(--t-text-primary);
}

.input-hint {
  font-size: 11px;
  color: var(--t-text-muted);
  margin-top: 8px;
  letter-spacing: 0.01em;
}

/* ============ Attachment Preview ============ */
.attachment-preview {
  width: 100%;
  max-width: 780px;
  margin-bottom: 10px;
  padding: 10px 14px;
  background: var(--t-bg-elevated);
  border: 1px solid var(--t-border-subtle);
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
  border: 1px solid var(--t-border-subtle);
}

.attachment-file {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--t-text-secondary);
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
  background: var(--t-border-subtle);
  border: none;
  color: var(--t-text-secondary);
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
  color: var(--t-danger);
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
  background: var(--t-border-subtle);
  border-radius: 4px;
}

.chat-area::-webkit-scrollbar-thumb:hover {
  background: var(--t-border-strong);
}

.sidebar-list::-webkit-scrollbar {
  width: 4px;
}

.sidebar-list::-webkit-scrollbar-track {
  background: transparent;
}

.sidebar-list::-webkit-scrollbar-thumb {
  background: var(--t-border-subtle);
  border-radius: 4px;
}

/* ============ Element Plus Dark Overrides ============ */
.coding-page :deep(.el-tag--info) {
  background: var(--t-brand-subtle);
  border-color: var(--t-brand-glow);
  color: var(--t-brand-light);
}

.coding-page :deep(.el-button--primary) {
  background: var(--t-brand-gradient);
  border: none;
  transition: all 0.2s ease;
}

.coding-page :deep(.el-button--primary:hover) {
  box-shadow: 0 2px 10px var(--t-brand-glow);
  filter: brightness(1.1);
}

.coding-page :deep(.el-button--success) {
  background: rgba(74, 222, 128, 0.15);
  border-color: rgba(74, 222, 128, 0.3);
  color: var(--t-success);
  transition: all 0.2s ease;
}

.coding-page :deep(.el-button--success:hover) {
  background: rgba(74, 222, 128, 0.25);
  border-color: rgba(74, 222, 128, 0.45);
}

/* ============ Preview Panel ============ */
.preview-panel {
  width: var(--preview-panel-width);
  flex-shrink: 0;
  border-left: 1px solid var(--t-border-subtle);
  background: var(--t-bg-base);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: width 0.22s ease;
}

.preview-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid var(--t-border-subtle);
  background: var(--t-bg-elevated);
}

.preview-panel-heading {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.preview-panel-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--t-text-primary);
}

.preview-panel-subtitle {
  font-size: 11px;
  color: var(--t-text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.preview-panel-actions {
  display: flex;
  gap: 4px;
}

.preview-panel-loading,
.preview-panel-empty {
  flex: 1;
  padding: 18px;
  background:
    radial-gradient(circle at top, rgba(99, 102, 241, 0.08), transparent 36%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.02), transparent 58%),
    var(--t-bg-base);
}

.preview-panel-loading {
  display: flex;
  align-items: center;
  justify-content: center;
}

.preview-panel-loading-card,
.preview-panel-empty {
  border: 1px solid var(--t-border-subtle);
  border-radius: 18px;
  background: var(--t-bg-elevated);
  box-shadow: 0 12px 28px rgba(15, 23, 42, 0.12);
}

.preview-panel-loading-card {
  width: min(100%, 440px);
  padding: 24px 22px;
}

.preview-panel-loading-title,
.preview-panel-empty-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--t-text-primary);
  margin-bottom: 8px;
}

.preview-panel-loading-desc,
.preview-panel-empty-desc {
  font-size: 13px;
  line-height: 1.7;
  color: var(--t-text-secondary);
}

.preview-panel-empty {
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.preview-panel-iframe {
  flex: 1;
  width: 100%;
  border: none;
  background: #fff;
}
</style>
