<template>
  <div class="coding-page">
    <!-- Header (嵌入模式隐藏) -->
    <header v-if="!embeddedAppId" class="coding-header">
      <div class="header-left">
        <el-button text @click="$router.push('/chat')">
          <el-icon><ArrowLeft /></el-icon>
        </el-button>
        <h3 class="header-title">AI Coding</h3>
        <el-tag
          v-if="codingStore.workspace"
          size="small"
          type="info"
          :title="workspaceTooltip(codingStore.workspace)"
          class="header-ws-tag"
        >
          {{ workspaceDisplayName(codingStore.workspace) }}
        </el-tag>
      </div>
      <div class="header-right">
        <ThemeToggle />
        <template v-if="codingStore.workspace">
          <!-- 调试功能暂时隐藏 -->
          <!-- <el-button
            size="small"
            class="header-btn"
            @click="showEnvPicker = true; loadPlatformEnvs()"
            title="浏览器预览"
          >
            <el-icon><Monitor /></el-icon>
          </el-button> -->
          <el-button
            size="small"
            type="success"
            :loading="isDownloading"
            class="header-btn"
            @click="downloadCode"
            title="下载代码"
          >
            <el-icon><Download /></el-icon>
          </el-button>
          <el-button
            size="small"
            type="danger"
            text
            class="header-btn"
            @click="deleteCurrentWorkspace"
            title="删除当前工作区"
          >
            <el-icon><Delete /></el-icon>
          </el-button>
        </template>
      </div>
    </header>

    <!-- Env Picker Dialog -->
    <el-dialog v-model="showEnvPicker" title="选择调试平台环境" width="500px" :append-to-body="true">
      <div v-if="platformEnvs.length === 0" style="text-align:center;color:#999;padding:20px;">
        暂无平台环境，请先到<el-link type="primary" @click="$router.push('/platform-envs')">环境管理</el-link>添加
      </div>
      <div v-else style="display:flex;flex-direction:column;gap:12px;">
        <div
          v-for="env in platformEnvs"
          :key="env.id"
          style="border:1px solid #dcdfe6;border-radius:8px;padding:16px;cursor:pointer;transition:all 0.2s;"
          :style="{ borderColor: env.status === 'connected' ? '#67c23a' : '#dcdfe6' }"
          @click="openBrowserPreviewWithEnv(env)"
        >
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <strong>{{ env.env_name }}</strong>
            <el-tag v-if="env.status === 'connected'" type="success" size="small">已连接</el-tag>
            <el-tag v-else type="info" size="small">未连接</el-tag>
          </div>
          <div style="color:#999;font-size:12px;margin-top:6px;">{{ env.base_url }}</div>
        </div>
      </div>
    </el-dialog>

    <div class="coding-body">
      <!-- Left Sidebar: Workspace List -->
      <aside class="workspace-sidebar" :class="{ collapsed: sidebarCollapsed }">
        <!-- Collapsed: only icons -->
        <div v-if="sidebarCollapsed" class="sidebar-collapsed-content">
          <button class="sidebar-toggle-btn" @click="sidebarCollapsed = false" title="展开侧栏">
            <el-icon :size="16"><Expand /></el-icon>
          </button>
          <button class="sidebar-icon-btn" @click="startNewWorkspace" title="新建工作区">
            <el-icon :size="16"><Plus /></el-icon>
          </button>
          <div class="sidebar-collapsed-divider"></div>
          <button
            v-for="ws in existingWorkspaces.slice(0, 8)"
            :key="ws.id"
            class="sidebar-icon-ws"
            :class="{ active: codingStore.workspace?.id === ws.id }"
            :title="workspaceDisplayName(ws)"
            @click="openExistingWorkspace(ws)"
          >{{ (workspaceDisplayName(ws) || '?')[0] }}</button>
        </div>

        <!-- Expanded: full list -->
        <template v-else>
          <div class="sidebar-section-header">
            <span class="sidebar-title">工作区</span>
            <div class="sidebar-header-actions">
              <button class="sidebar-action-btn sidebar-add-btn" @click="startNewWorkspace" title="新建工作区">
                <el-icon :size="14"><Plus /></el-icon>
              </button>
              <button class="sidebar-action-btn" @click="sidebarCollapsed = true" title="收起侧栏">
                <el-icon :size="14"><Fold /></el-icon>
              </button>
            </div>
          </div>
          <div class="sidebar-list">
            <template v-for="group in groupedWorkspaces" :key="group.key">
              <div class="sidebar-group-header" @click="toggleGroup(group.key)">
                <span class="sidebar-group-icon">{{ group.icon }}</span>
                <span class="sidebar-group-label">{{ group.label }}</span>
                <span class="sidebar-group-count">{{ group.items.length }}</span>
                <span class="sidebar-group-arrow" :class="{ collapsed: collapsedGroups.has(group.key) }">
                  <el-icon :size="10"><ArrowRight /></el-icon>
                </span>
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
                  <button class="sidebar-ws-del" @click.stop="deleteWorkspace(ws)" title="删除">&#215;</button>
                </div>
              </template>
            </template>
            <div v-if="existingWorkspaces.length === 0" class="sidebar-empty">
              暂无工作区
            </div>
          </div>
        </template>
      </aside>

      <!-- Main Content: Welcome or IDE -->
      <div class="main-content">
        <!-- Welcome State -->
        <div v-if="!ideUrl" class="welcome-pane">
          <div class="welcome-inner">
            <div class="welcome-icon">&#x2728;</div>
            <h2 class="welcome-title">描述你想开发的内容</h2>
            <p class="welcome-desc">告诉我你想开发什么，我会自动创建项目并打开 AI 代码编辑器。</p>

            <!-- Input Area (centered) -->
            <div class="welcome-input-area">
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
                  :disabled="isCreating"
                  title="上传附件"
                >
                  <el-icon :size="18"><Paperclip /></el-icon>
                </el-button>
                <el-input
                  v-model="userInput"
                  type="textarea"
                  :rows="2"
                  :autosize="{ minRows: 2, maxRows: 6 }"
                  placeholder="描述你想开发的组件或页面... (Ctrl+Enter 发送)"
                  @keydown.ctrl.enter="sendMessage"
                  @keydown.meta.enter="sendMessage"
                  :disabled="isCreating"
                  resize="none"
                />
                <el-button
                  type="primary"
                  class="send-btn"
                  :loading="isCreating || isUploading"
                  @click="sendMessage"
                  :disabled="(!userInput.trim() && !attachedFile) || isCreating"
                  circle
                >
                  <el-icon v-if="!isCreating && !isUploading"><TopRight /></el-icon>
                </el-button>
              </div>
              <div class="input-hint">Ctrl + Enter 发送 | 粘贴截图或点击回形针添加附件</div>
            </div>

            <!-- Scene Category Chips -->
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

            <!-- Suggestion Cards -->
            <div class="suggestions-grid">
              <button
                v-for="s in activeSuggestions"
                :key="s"
                class="suggestion-card"
                @click="sendSuggestion(s)"
              >
                {{ s }}
              </button>
            </div>

            <!-- Creating overlay -->
            <div v-if="isCreating" class="creating-overlay">
              <div class="creating-spinner"></div>
              <p class="creating-text">{{ creatingStatus }}</p>
            </div>
          </div>
        </div>

        <!-- IDE State (with loading overlay) -->
        <div v-else class="ide-pane">
          <iframe
            v-if="ideUrl"
            :key="ideUrl"
            :src="ideUrl"
            class="ide-frame"
            allow="clipboard-read; clipboard-write"
            @load="ideLoaded = true"
          ></iframe>
          <!-- Loading overlay — stays until iframe fires load event -->
          <div v-if="!ideLoaded" class="ide-loading-overlay">
            <div class="ide-loading-content">
              <div class="ide-loading-spinner"></div>
              <span>正在加载 IDE...</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { API_PREFIX } from '@/utils/request'
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, ArrowRight, Download, TopRight, Plus, Paperclip, Monitor, Delete, Fold, Expand } from '@element-plus/icons-vue'
import { useCodingStore } from '@/stores/coding'
import { platformEnvApi, type PlatformEnv } from '@/api/platformEnv'
import { useUserStore } from '@/stores/user'
import { codingApi } from '@/api/coding'
import type { WorkspaceInfo, UploadResult } from '@/api/coding'
import { consumeSseResponse } from '@/utils/sse'
import ThemeToggle from '@/components/ThemeToggle.vue'

const route = useRoute()
const codingStore = useCodingStore()
const userStore = useUserStore()

// ============ Core State ============
const userInput = ref('')
const ideUrl = ref<string | null>(null)
const ideLoaded = ref(false)
const isCreating = ref(false)
const creatingStatus = ref('正在创建工作区...')
const allWorkspaces = ref<WorkspaceInfo[]>([])
const embeddedAppId = computed(() => (route.query.app_id as string) || '')
const existingWorkspaces = computed(() => {
  if (!embeddedAppId.value) return allWorkspaces.value
  return allWorkspaces.value.filter((ws: any) => String(ws.project_id || '') === embeddedAppId.value)
})
const isDownloading = ref(false)
const sidebarCollapsed = ref(false)

// ============ Attachment State ============
const attachedFile = ref<File | null>(null)
const attachedPreviewUrl = ref<string | null>(null)
const isUploading = ref(false)
const fileInputRef = ref<HTMLInputElement>()

// ============ Env Picker ============
const showEnvPicker = ref(false)
const platformEnvs = ref<PlatformEnv[]>([])

// ============ Workspace Grouping ============
const collapsedGroups = ref(new Set<string>())

const wsTypeGroupMap: Record<string, { key: string; icon: string; label: string; order: number }> = {
  'form-component':   { key: 'component-pc',     icon: '\uD83E\uDDE9', label: 'PC \u7EC4\u4EF6',     order: 1 },
  'mobile-component': { key: 'component-mobile', icon: '\uD83D\uDCF1', label: '\u79FB\u52A8\u7AEF\u7EC4\u4EF6',  order: 2 },
  'menu-page':        { key: 'page-pc',          icon: '\uD83D\uDDA5\uFE0F', label: 'PC \u9875\u9762',     order: 3 },
  'form-page':        { key: 'page-pc',          icon: '\uD83D\uDDA5\uFE0F', label: 'PC \u9875\u9762',     order: 3 },
  'mobile-page':      { key: 'page-mobile',      icon: '\uD83D\uDCF1', label: '\u79FB\u52A8\u7AEF\u9875\u9762',  order: 4 },
  'form-list':        { key: 'list-view',         icon: '\uD83D\uDCCB', label: '\u5217\u8868\u89C6\u56FE',   order: 5 },
  'layout':           { key: 'layout',            icon: '\uD83D\uDCD0', label: '\u5E94\u7528\u5E03\u5C40',   order: 6 },
  'plugin':           { key: 'plugin',            icon: '\uD83D\uDD0C', label: '\u6269\u5C55\u63D2\u4EF6',   order: 7 },
  'backend-api':      { key: 'backend',           icon: '\u2699\uFE0F', label: '\u540E\u7AEF\u63A5\u53E3',   order: 8 },
  'script':           { key: 'script',            icon: '\u26A1', label: '\u811A\u672C/\u4E8B\u4EF6',  order: 9 },
  'script-js':        { key: 'script',            icon: '\u26A1', label: '\u811A\u672C/\u4E8B\u4EF6',  order: 9 },
  'script-python':    { key: 'script',            icon: '\u26A1', label: '\u811A\u672C/\u4E8B\u4EF6',  order: 9 },
  'script-groovy':    { key: 'script',            icon: '\u26A1', label: '\u811A\u672C/\u4E8B\u4EF6',  order: 9 },
  'business-dialog':  { key: 'dialog',            icon: '\uD83D\uDCAC', label: '\u4E1A\u52A1\u5F39\u7A97',   order: 10 },
  'ui-style':         { key: 'style',             icon: '\uD83C\uDFA8', label: 'UI \u6837\u5F0F',   order: 11 },
  'list-custom-module': { key: 'list-module',     icon: '\uD83D\uDCCA', label: '\u5217\u8868\u6A21\u5757',   order: 12 },
  'web-login':        { key: 'login',             icon: '\uD83D\uDD11', label: '\u767B\u5F55\u9875',     order: 13 },
  'backend-feign':    { key: 'backend',           icon: '\uD83D\uDD17', label: '\u5916\u90E8\u8C03\u7528',  order: 8 },
  'backend-scheduled':{ key: 'backend',           icon: '\u23F0', label: '\u5B9A\u65F6\u4EFB\u52A1',  order: 8 },
}

const groupedWorkspaces = computed(() => {
  const groups: Record<string, { key: string; icon: string; label: string; order: number; items: WorkspaceInfo[] }> = {}
  for (const ws of existingWorkspaces.value) {
    const mapping = wsTypeGroupMap[ws.project_type] || { key: 'other', icon: '\uD83D\uDCE6', label: '\u5176\u4ED6', order: 99 }
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

// ============ Scene Categories & Suggestions ============
const sceneCategories = [
  { key: 'component-pc', icon: '\uD83E\uDDE9', label: 'PC\u7EC4\u4EF6' },
  { key: 'component-mobile', icon: '\uD83D\uDCF1', label: '\u79FB\u52A8\u7AEF\u7EC4\u4EF6' },
  { key: 'page-pc', icon: '\uD83D\uDDA5\uFE0F', label: 'PC\u9875\u9762' },
  { key: 'page-mobile', icon: '\uD83D\uDCF1', label: '\u79FB\u52A8\u7AEF\u9875\u9762' },
  { key: 'layout', icon: '\uD83D\uDCD0', label: '\u5E94\u7528\u5E03\u5C40' },
  { key: 'plugin', icon: '\uD83D\uDD0C', label: '\u6269\u5C55\u63D2\u4EF6' },
  { key: 'script', icon: '\u26A1', label: '\u811A\u672C/\u4E8B\u4EF6' },
  { key: 'backend', icon: '\u2699\uFE0F', label: '\u540E\u7AEF\u63A5\u53E3' },
  { key: 'backend-feign', icon: '\uD83D\uDD17', label: '\u5916\u90E8\u8C03\u7528' },
  { key: 'backend-scheduled', icon: '\u23F0', label: '\u5B9A\u65F6\u4EFB\u52A1' },
]

const sceneSuggestions: Record<string, string[]> = {
  'component-pc': [
    '\u5F00\u53D1\u4E00\u4E2A\u5934\u50CF\u4E0A\u4F20\u7EC4\u4EF6\uFF0C\u652F\u6301\u88C1\u526A\u548C\u9884\u89C8',
    '\u5B9E\u73B0\u4E00\u4E2A\u65E5\u671F\u8303\u56F4\u9009\u62E9\u5668\u7EC4\u4EF6',
    '\u505A\u4E00\u4E2A\u8BC4\u5206\u7EC4\u4EF6\uFF0C\u652F\u6301\u534A\u661F\u548C\u81EA\u5B9A\u4E49\u989C\u8272',
    '\u521B\u5EFA\u4E00\u4E2A\u56FE\u8868\u5206\u6790\u7EC4\u4EF6\uFF0C\u652F\u6301\u67F1\u72B6\u56FE\u548C\u997C\u56FE',
  ],
  'component-mobile': [
    '\u505A\u4E00\u4E2A\u79FB\u52A8\u7AEF\u7B7E\u540D\u677F\u7EC4\u4EF6\uFF0C\u652F\u6301\u624B\u5199\u7B7E\u540D',
    '\u5F00\u53D1\u4E00\u4E2A\u79FB\u52A8\u7AEF\u56FE\u7247\u9009\u62E9\u7EC4\u4EF6\uFF0C\u652F\u6301\u62CD\u7167\u548C\u76F8\u518C',
    '\u5B9E\u73B0\u4E00\u4E2A\u79FB\u52A8\u7AEF\u5730\u7406\u4F4D\u7F6E\u9009\u62E9\u7EC4\u4EF6\uFF08Cube UI\uFF09',
    '\u4E3A\u5DF2\u6709PC\u8BC4\u5206\u7EC4\u4EF6\u5F00\u53D1\u5BF9\u5E94\u7684\u79FB\u52A8\u7AEF\u7248\u672C',
  ],
  'page-pc': [
    '\u505A\u4E00\u4E2A\u6570\u636E\u67E5\u8BE2\u8868\u683C\u9875\u9762\uFF0C\u5E26\u641C\u7D22\u548C\u5206\u9875',
    '\u5F00\u53D1\u4E00\u4E2A\u4F9B\u5E94\u5546\u7BA1\u7406\u5F39\u7A97\u9009\u62E9\u9875\u9762',
    '\u521B\u5EFA\u4E00\u4E2A\u9879\u76EE\u5206\u6790\u56FE\u8868\u9875\u9762',
    '\u505A\u4E00\u4E2A\u5BA1\u6279\u6D41\u7A0B\u9875\u9762\uFF0C\u652F\u6301\u591A\u7EA7\u5BA1\u6279',
  ],
  'page-mobile': [
    '\u505A\u4E00\u4E2A\u79FB\u52A8\u7AEF\u626B\u7801\u7B7E\u5230\u9875\u9762',
    '\u5F00\u53D1\u4E00\u4E2A\u79FB\u52A8\u7AEF\u5DE1\u68C0\u8BB0\u5F55\u9875\u9762',
    '\u521B\u5EFA\u4E00\u4E2A\u79FB\u52A8\u7AEF\u5BA1\u6279\u8BE6\u60C5\u9875\u9762',
    '\u505A\u4E00\u4E2A\u79FB\u52A8\u7AEF\u6570\u636E\u91C7\u96C6\u8868\u5355\u9875\u9762',
  ],
  layout: [
    '\u505A\u4E00\u4E2A\u5E26\u9876\u90E8\u516C\u544A\u680F\u7684\u81EA\u5B9A\u4E49\u5E03\u5C40',
    '\u521B\u5EFA\u4E00\u4E2A\u53CC\u680F\u5E03\u5C40\uFF0C\u5DE6\u4FA7\u83DC\u5355\u53EF\u6298\u53E0',
    '\u5F00\u53D1\u4E00\u4E2A\u6697\u8272\u4E3B\u9898\u7684\u81EA\u5B9A\u4E49\u5E94\u7528\u5E03\u5C40',
  ],
  plugin: [
    '\u5F00\u53D1\u4E00\u4E2A\u5E94\u7528\u8BE6\u60C5\u9875\u7684\u81EA\u5B9A\u4E49Tab\u63D2\u4EF6',
    '\u505A\u4E00\u4E2A\u81EA\u5B9A\u4E49\u9762\u677F\u6269\u5C55\uFF0C\u663E\u793A\u7EDF\u8BA1\u6570\u636E',
    '\u521B\u5EFA\u4E00\u4E2A\u7CFB\u7EDF\u901A\u77E5\u7BA1\u7406\u6269\u5C55\u63D2\u4EF6',
  ],
  script: [
    '\u5199\u4E00\u4E2AJavaScript\u524D\u7AEF\u811A\u672C\uFF0C\u8868\u5355\u63D0\u4EA4\u524D\u6821\u9A8C\u6570\u636E',
    '\u505A\u4E00\u4E2A\u4E1A\u52A1\u4E8B\u4EF6\u81EA\u5B9A\u4E49\u5F39\u7A97\uFF0C\u91C7\u96C6\u5BA1\u6279\u610F\u89C1',
    '\u5199\u4E00\u4E2A\u540E\u7AEFPython\u811A\u672C\u5904\u7406\u6570\u636E\u540C\u6B65',
    '\u5F00\u53D1\u4E00\u4E2A\u81EA\u5B9A\u4E49CSS\u6837\u5F0F\uFF0C\u7F8E\u5316\u8868\u5355\u754C\u9762',
  ],
  backend: [
    '\u5F00\u53D1\u4E00\u4E2A\u81EA\u5B9A\u4E49\u6570\u636E\u67E5\u8BE2\u63A5\u53E3',
    '\u505A\u4E00\u4E2A\u6279\u91CF\u5BFC\u5165\u7684\u540E\u7AEF\u63A5\u53E3',
    '\u521B\u5EFA\u4E00\u4E2A\u62A5\u8868\u7EDF\u8BA1\u7684\u540E\u7AEFAPI',
  ],
  'backend-feign': [
    '\u8C03\u7528\u5916\u90E8 ERP \u7CFB\u7EDF\u7684\u5E93\u5B58\u67E5\u8BE2\u63A5\u53E3',
    '\u96C6\u6210\u7B2C\u4E09\u65B9\u77ED\u4FE1\u670D\u52A1\u53D1\u9001\u901A\u77E5',
    '\u5BF9\u63A5\u5916\u90E8 OA \u7CFB\u7EDF\u83B7\u53D6\u4EBA\u5458\u4FE1\u606F',
    '\u8C03\u7528\u5916\u90E8\u5929\u6C14 API \u83B7\u53D6\u5B9E\u65F6\u6570\u636E',
  ],
  'backend-scheduled': [
    '\u6BCF\u5929\u51CC\u6668\u540C\u6B65\u5916\u90E8\u7CFB\u7EDF\u6570\u636E\u5230\u672C\u5730',
    '\u6BCF\u5C0F\u65F6\u68C0\u67E5\u5E76\u5904\u7406\u8D85\u65F6\u672A\u5B8C\u6210\u7684\u4EFB\u52A1',
    '\u6BCF\u5468\u751F\u6210\u5E76\u53D1\u9001\u4E1A\u52A1\u6C47\u603B\u62A5\u8868',
    '\u5B9A\u65F6\u6E05\u7406\u8FC7\u671F\u65E5\u5FD7\u548C\u4E34\u65F6\u6570\u636E',
  ],
}

const activeSceneCategory = ref('component-pc')
const pendingSceneCategory = ref<string | null>(null)

const activeSuggestions = computed(() => sceneSuggestions[activeSceneCategory.value] || [])

const sceneCategoryToProjectType: Record<string, string> = {
  'component-pc': 'form-component',
  'component-mobile': 'mobile-component',
  'page-pc': 'menu-page',
  'page-mobile': 'mobile-page',
  layout: 'layout',
  plugin: 'plugin',
  script: 'script',
  backend: 'backend-api',
  'backend-feign': 'backend-feign',
  'backend-scheduled': 'backend-scheduled',
}

// ============ Lifecycle ============

onMounted(async () => {
  try {
    allWorkspaces.value = await codingApi.listWorkspaces()
  } catch (e) {
    console.error('\u83B7\u53D6\u5DE5\u4F5C\u533A\u5217\u8868\u5931\u8D25:', e)
  }

  const wsId = (route.query.workspace_id || route.query.ws) as string
  if (wsId) {
    await openWorkspaceById(wsId)
  } else {
    const lastWsId = localStorage.getItem('coding_last_workspace_id')
    if (lastWsId && existingWorkspaces.value.some(w => w.id === lastWsId)) {
      await openWorkspaceById(lastWsId)
    }
  }
})

onUnmounted(() => {
  // cleanup if needed
})

// ============ Workspace Operations ============

async function openExistingWorkspace(ws: WorkspaceInfo) {
  await openWorkspaceById(ws.id)
}

// 设置 IDE URL — 先销毁旧 iframe 再创建新的，避免 code-server session 缓存
async function setIdeUrl(url: string) {
  ideLoaded.value = false  // 显示 loading overlay
  ideUrl.value = null  // 销毁旧 iframe
  await new Promise(r => setTimeout(r, 100))  // 等 DOM 更新
  ideUrl.value = url + (url.includes('?') ? '&' : '?') + '_t=' + Date.now()
  // ideLoaded 会在 iframe @load 事件触发时置 true
}

async function openWorkspaceById(wsId: string) {
  try {
    const ws = await codingApi.getWorkspace(wsId)
    codingStore.setWorkspace(ws)
    localStorage.setItem('coding_last_workspace_id', wsId)

    const { ide_url } = await codingApi.getIdeUrl(ws.id)
    await setIdeUrl(ide_url)
  } catch (error: any) {
    ElMessage.error(`打开工作区失败: ${error.message}`)
  }
}

function startNewWorkspace() {
  codingStore.reset()
  ideUrl.value = null
  ideLoaded.value = false
  localStorage.removeItem('coding_last_workspace_id')
}

async function deleteWorkspace(ws: WorkspaceInfo) {
  try {
    await codingApi.deleteWorkspace(ws.id)
    allWorkspaces.value = allWorkspaces.value.filter(w => w.id !== ws.id)
    if (codingStore.workspace?.id === ws.id) {
      codingStore.reset()
      ideUrl.value = null
      localStorage.removeItem('coding_last_workspace_id')
    }
    ElMessage.success('\u5DF2\u5220\u9664')
  } catch (e: any) {
    ElMessage.error(e.message || '\u5220\u9664\u5931\u8D25')
  }
}

async function deleteCurrentWorkspace() {
  if (!codingStore.workspace) return
  await deleteWorkspace(codingStore.workspace)
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

// ============ Send Message / Create Workspace ============

function sendSuggestion(text: string) {
  userInput.value = text
  pendingSceneCategory.value = activeSceneCategory.value
  sendMessage()
}

async function sendMessage() {
  const message = userInput.value.trim()
  if (!message && !attachedFile.value) return
  if (isCreating.value) return

  userInput.value = ''
  const currentAttachment = attachedFile.value
  const currentPreviewUrl = attachedPreviewUrl.value
  attachedFile.value = null
  attachedPreviewUrl.value = null

  isCreating.value = true
  creatingStatus.value = '\u6B63\u5728\u521B\u5EFA\u5DE5\u4F5C\u533A...'

  // Upload attachment if present
  let uploadResult: UploadResult | null = null
  if (currentAttachment) {
    try {
      isUploading.value = true
      uploadResult = await codingApi.uploadFile(currentAttachment, codingStore.workspace?.id)
    } catch (e: any) {
      ElMessage.error(`\u9644\u4EF6\u4E0A\u4F20\u5931\u8D25: ${e.message}`)
    } finally {
      isUploading.value = false
      if (currentPreviewUrl) URL.revokeObjectURL(currentPreviewUrl)
    }
  }

  // Build final message with attachment context
  let finalMessage = message
  if (uploadResult) {
    if (uploadResult.content) {
      finalMessage = `[\u9644\u4EF6\u6587\u6863: ${uploadResult.filename}]\n\`\`\`\n${uploadResult.content}\n\`\`\`\n\n${message}`
    } else {
      finalMessage = `${message}\n\n[\u9644\u4EF6\u56FE\u7247: ${uploadResult.filename}, \u5DF2\u4FDD\u5B58\u81F3: ${uploadResult.file_path}]`
    }
  }

  const _sceneKey = pendingSceneCategory.value || activeSceneCategory.value
  const _projectType = sceneCategoryToProjectType[_sceneKey] || route.query.type as string || null
  pendingSceneCategory.value = null

  try {
    const token = userStore.token

    const body: Record<string, any> = {
      message: finalMessage,
      workspace_id: codingStore.workspace?.id || null,
      conversation_id: codingStore.conversationId || null,
      app_id: (route.query.app_id as string) || null,
      project_id: embeddedAppId.value ? Number(embeddedAppId.value) : null,
      project_type: _projectType,
      quick_create: true,
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

    await consumeSseResponse(response, async ({ data }) => {
      const payload = data.trim()
      if (!payload || payload === '[DONE]') return

      try {
        const parsed = JSON.parse(payload)

        if (parsed.type === 'step') {
          if (parsed.step === 'create_workspace' && parsed.status === 'done' && parsed.data) {
            const wsData = {
              ...parsed.data,
              id: parsed.data.workspace_id || parsed.data.id,
            }
            codingStore.setWorkspace(wsData)
            codingStore.workspacePath = parsed.data.workspace_path || null
            localStorage.setItem('coding_last_workspace_id', wsData.id)
            creatingStatus.value = '\u5DE5\u4F5C\u533A\u5DF2\u521B\u5EFA\uFF0C\u6B63\u5728\u542F\u52A8 IDE...'
            try { allWorkspaces.value = await codingApi.listWorkspaces() } catch {}
          } else if (parsed.step === 'create_workspace' && parsed.status === 'running') {
            creatingStatus.value = '\u6B63\u5728\u521B\u5EFA\u5DE5\u4F5C\u533A...'
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
          if (parsed.ide_url) {
            setIdeUrl(parsed.ide_url)
          }
        }
      } catch {
        // skip unparseable events
      }
    }, { yieldEvery: 6 })

    // If we got a workspace but no IDE URL from SSE, fetch it now
    if (!ideUrl.value && codingStore.workspace) {
      try {
        const { ide_url } = await codingApi.getIdeUrl(codingStore.workspace.id)
        await setIdeUrl(ide_url)
      } catch (err: any) {
        ElMessage.warning(err?.message || 'IDE URL 获取失败')
      }
    }

    // Refresh workspace list
    if (codingStore.workspace) {
      try { allWorkspaces.value = await codingApi.listWorkspaces() } catch {}
    }

  } catch (error: any) {
    ElMessage.error(`\u5904\u7406\u5931\u8D25: ${error.message}`)
  } finally {
    isCreating.value = false
  }
}

// ============ Header Actions ============

async function loadPlatformEnvs() {
  try {
    platformEnvs.value = await platformEnvApi.list()
  } catch { /* ignore */ }
}

async function openBrowserPreviewWithEnv(env: PlatformEnv) {
  if (!codingStore.workspace) return
  showEnvPicker.value = false
  try {
    const { ide_url } = await codingApi.getIdeUrl(codingStore.workspace.id)
    const urlParams = new URLSearchParams(new URL(ide_url).search)
    const token = urlParams.get('vibe_ide_token') || ''
    const wsId = codingStore.workspace.id
    const platformBase = env.base_url.replace(/\/backend\/?$/, '')
    const loginUrl = platformBase
    const previewUrl = `${API_PREFIX.replace('/api', '')}/api/static/browser-preview.html?ws_id=${wsId}&token=${token}&initial_url=${encodeURIComponent(loginUrl)}`
    window.open(previewUrl, '_blank', 'noopener,noreferrer')
  } catch (err: any) {
    ElMessage.warning(err?.response?.data?.detail || err?.message || '\u6D4F\u89C8\u5668\u9884\u89C8\u6253\u5F00\u5931\u8D25')
  }
}

async function downloadCode() {
  if (!codingStore.workspace || isDownloading.value) return
  isDownloading.value = true
  try {
    await codingApi.downloadZip(codingStore.workspace.id, 'src')
    ElMessage.success('\u4EE3\u7801\u4E0B\u8F7D\u5DF2\u5F00\u59CB')
  } catch (error: any) {
    ElMessage.error(error.message || '\u4E0B\u8F7D\u5931\u8D25')
  } finally {
    isDownloading.value = false
  }
}

// ============ Watchers ============

watch(() => route.path, () => {
  if (!route.path.startsWith('/coding')) {
    codingStore.reset()
    ideUrl.value = null
  }
})
</script>

<style scoped>
/* ============================================================
   CodingPage — Project Launcher + Embedded IDE
   ============================================================ */

.coding-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  position: relative;
  background: var(--t-bg-base);
  color: var(--t-text-primary);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
}

/* ============ Header ============ */
.coding-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 22px;
  border-bottom: 1px solid var(--t-border-subtle);
  background: var(--t-bg-nav);
  backdrop-filter: blur(18px);
  min-height: 48px;
  flex-shrink: 0;
  box-shadow: var(--t-shadow-sm);
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

.header-ws-tag {
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
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

/* ============ Body Layout ============ */
.coding-body {
  display: flex;
  flex: 1;
  overflow: hidden;
  min-height: 0;
}

/* ============ Workspace Sidebar ============ */
.workspace-sidebar {
  width: 240px;
  flex-shrink: 0;
  border-right: 1px solid var(--t-border-subtle);
  transition: width 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  background: var(--t-bg-panel);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Collapsed sidebar */
.workspace-sidebar.collapsed {
  width: 48px;
}
.sidebar-collapsed-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 8px 0;
  gap: 4px;
}
.sidebar-collapsed-divider {
  width: 24px;
  height: 1px;
  background: var(--t-border-subtle);
  margin: 4px 0;
}
.sidebar-icon-btn {
  width: 32px;
  height: 32px;
  border: none;
  border-radius: var(--t-radius-sm);
  background: transparent;
  color: var(--t-text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s ease;
}
.sidebar-icon-btn:hover {
  background: var(--t-brand-subtle);
  color: var(--t-brand);
}
.sidebar-icon-ws {
  width: 32px;
  height: 32px;
  border: 1px solid var(--t-border-subtle);
  border-radius: var(--t-radius-sm);
  background: var(--t-bg-panel);
  color: var(--t-text-secondary);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s ease;
}
.sidebar-icon-ws:hover {
  border-color: var(--t-brand-light);
  color: var(--t-brand);
  background: var(--t-brand-subtle);
}
.sidebar-icon-ws.active {
  border-color: var(--t-brand);
  color: var(--t-brand);
  background: var(--t-brand-subtle);
  box-shadow: 0 0 0 1px var(--t-brand-glow);
}
.sidebar-toggle-btn {
  width: 32px;
  height: 32px;
  border: none;
  border-radius: var(--t-radius-sm);
  background: transparent;
  color: var(--t-text-muted);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s ease;
}
.sidebar-toggle-btn:hover {
  background: var(--t-bg-panel-hover);
  color: var(--t-text-primary);
}

.sidebar-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px 6px;
}
.sidebar-header-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}
.sidebar-action-btn {
  width: 28px;
  height: 28px;
  border: 1px solid var(--t-border-subtle);
  border-radius: 6px;
  background: var(--t-bg-panel);
  color: var(--t-text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s ease;
}
.sidebar-action-btn:hover {
  background: var(--t-bg-panel-hover);
  color: var(--t-text-primary);
  border-color: var(--t-border-strong);
}
.sidebar-add-btn {
  color: var(--t-brand);
  border-color: var(--t-brand-glow);
}
.sidebar-add-btn:hover {
  background: var(--t-brand-subtle);
  color: var(--t-brand-dark);
  border-color: var(--t-brand);
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
  padding: 10px 12px 16px;
}

.sidebar-group-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 10px 7px;
  cursor: pointer;
  user-select: none;
  margin-top: 8px;
  border-radius: 12px;
  transition: background 0.2s ease;
}

.sidebar-group-header:hover {
  background: var(--t-bg-subtle);
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
  background: var(--t-bg-subtle);
  padding: 2px 7px;
  border-radius: 999px;
  min-width: 18px;
  text-align: center;
}

.sidebar-group-arrow {
  color: var(--t-text-muted);
  transition: transform 0.2s ease;
  transform: rotate(90deg);
  display: flex;
  align-items: center;
}

.sidebar-group-arrow.collapsed {
  transform: rotate(0deg);
}

.sidebar-ws-item {
  padding: 10px 12px 8px;
  border-radius: var(--t-radius-sm);
  cursor: pointer;
  position: relative;
  margin-bottom: 6px;
  border: 1px solid transparent;
  background: transparent;
  transition: all 0.22s ease;
}

.sidebar-ws-item:hover {
  background: var(--t-bg-panel-hover);
  border-color: var(--t-border-strong);
}

.sidebar-ws-item.active {
  background: var(--t-brand-subtle);
  border-color: var(--t-brand-glow);
  box-shadow: inset 3px 0 0 var(--t-brand);
}

.sidebar-ws-name {
  font-size: 13px;
  color: var(--t-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 4px;
  font-weight: 600;
  line-height: 1.4;
}

.sidebar-ws-code {
  font-size: 11px;
  line-height: 1.3;
  color: var(--t-text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.sidebar-ws-del {
  position: absolute;
  top: 6px;
  right: 6px;
  width: 20px;
  height: 20px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--t-text-muted);
  font-size: 14px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: all 0.15s ease;
}
.sidebar-ws-del:hover {
  background: var(--t-danger-subtle);
  color: var(--t-danger);
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

/* ============ Main Content ============ */
.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
}

/* ============ Welcome Pane ============ */
.welcome-pane {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow-y: auto;
  background: radial-gradient(circle at top, var(--t-brand-subtle), transparent 40%);
}

.welcome-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  max-width: 700px;
  width: 100%;
  padding: 40px 24px;
  position: relative;
}

.welcome-icon {
  font-size: 48px;
  margin-bottom: 16px;
  filter: drop-shadow(0 0 24px var(--t-brand-glow));
}

.welcome-title {
  font-size: 32px;
  font-weight: 800;
  margin: 0 0 12px;
  background: var(--t-brand-gradient);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  letter-spacing: -0.02em;
}

.welcome-desc {
  color: var(--t-text-secondary);
  font-size: 15px;
  margin: 0 0 28px;
  line-height: 1.7;
  max-width: 460px;
}

/* ============ Welcome Input Area ============ */
.welcome-input-area {
  width: 100%;
  margin-bottom: 28px;
}

.input-wrapper {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  width: 100%;
  background: var(--t-bg-input);
  border: 1px solid var(--t-border-subtle);
  border-radius: 22px;
  padding: 12px 14px;
  transition: all 0.3s ease;
  box-shadow: var(--t-shadow-md);
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
  background: var(--t-danger-subtle);
  color: var(--t-danger);
}

.attachment-thumb .attachment-remove {
  position: absolute;
  top: -6px;
  right: -6px;
}

/* ============ Scene Tabs ============ */
.scene-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  margin-bottom: 20px;
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

/* ============ Suggestion Cards ============ */
.suggestions-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  width: 100%;
}

.suggestion-card {
  padding: 16px 18px;
  border-radius: 14px;
  border: 1px solid var(--t-border-subtle);
  background: var(--t-bg-elevated);
  color: var(--t-text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.25s ease;
  line-height: 1.5;
  text-align: left;
}

.suggestion-card:hover {
  border-color: var(--t-brand-glow);
  background: var(--t-brand-subtle);
  color: var(--t-text-primary);
  transform: translateY(-2px);
  box-shadow: 0 8px 20px var(--t-brand-glow);
}

/* ============ Creating Overlay ============ */
.creating-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: var(--t-bg-overlay);
  backdrop-filter: blur(8px);
  border-radius: 16px;
  z-index: 10;
}

.creating-spinner {
  width: 40px;
  height: 40px;
  border: 3px solid var(--t-border-subtle);
  border-top-color: var(--t-brand);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin-bottom: 16px;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.creating-text {
  color: var(--t-text-secondary);
  font-size: 14px;
  margin: 0;
}

/* ============ IDE Pane ============ */
.ide-pane {
  flex: 1;
  overflow: hidden;
  position: relative;
}
.ide-loading-overlay {
  position: absolute;
  inset: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--t-bg-base);
  transition: opacity 0.3s ease;
}
.ide-loading-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  color: var(--t-text-secondary);
  font-size: 14px;
}
.ide-loading-spinner {
  width: 36px;
  height: 36px;
  border: 3px solid var(--t-border-subtle);
  border-top-color: var(--t-brand);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.ide-frame {
  width: 100%;
  height: 100%;
  border: none;
}

/* ============ Scrollbar ============ */
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

.welcome-pane::-webkit-scrollbar {
  width: 5px;
}

.welcome-pane::-webkit-scrollbar-track {
  background: transparent;
}

.welcome-pane::-webkit-scrollbar-thumb {
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
  background: var(--t-success-subtle);
  border-color: var(--t-success);
  color: var(--t-success);
  transition: all 0.2s ease;
}

.coding-page :deep(.el-button--success:hover) {
  filter: brightness(1.15);
}
</style>
