<template>
  <div class="coding-page">
    <!-- Header -->
    <header class="coding-header">
      <div class="header-left">
        <el-button text @click="$router.push('/')">
          <el-icon><ArrowLeft /></el-icon>
        </el-button>
        <h3 class="header-title">Vibe Coding</h3>
        <el-tag v-if="codingStore.workspace" size="small" type="info">
          {{ codingStore.workspace.project_name }}
        </el-tag>
      </div>
      <div class="header-right">
        <el-button
          v-if="codingStore.workspace"
          size="small"
          @click="openInVSCode"
          class="header-btn"
        >
          <el-icon><FolderOpened /></el-icon> 在 VS Code 中打开
        </el-button>
        <el-button
          v-if="codingStore.workspace"
          size="small"
          type="success"
          @click="debugProject"
          :loading="isDebugging"
          class="header-btn"
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
        <el-button
          v-if="codingStore.workspace"
          size="small"
          @click="showWorkspaceList = true"
          class="header-btn"
        >
          <el-icon><Menu /></el-icon>
        </el-button>
      </div>
    </header>

    <!-- Chat Area (full width, scrollable) -->
    <div class="chat-area" ref="chatAreaRef">
      <!-- Welcome message when no workspace -->
      <div v-if="!codingStore.workspace && codingStore.messages.length === 0" class="welcome">
        <div class="welcome-icon">&#x2728;</div>
        <h2>描述你想要的组件</h2>
        <p class="welcome-desc">告诉我你想开发什么，我会自动创建项目、生成代码、安装依赖并启动开发服务器。</p>
        <div class="suggestions">
          <button
            v-for="s in suggestions"
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
      <div class="input-wrapper">
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
          :loading="codingStore.isProcessing"
          @click="sendMessage"
          :disabled="!userInput.trim() || codingStore.isProcessing"
          circle
        >
          <el-icon v-if="!codingStore.isProcessing"><TopRight /></el-icon>
        </el-button>
      </div>
      <div class="input-hint">Ctrl + Enter 发送</div>
    </div>

    <!-- Workspace List Dialog -->
    <el-dialog v-model="showWorkspaceList" title="我的工作区" width="520px" class="ws-dialog">
      <!-- 新建工作区按钮 -->
      <div class="ws-actions">
        <el-button type="primary" size="small" @click="startNewWorkspace" style="width:100%">
          <el-icon><Plus /></el-icon> 新建工作区
        </el-button>
      </div>

      <div v-if="existingWorkspaces.length === 0" style="text-align:center;color:#999;padding:20px;">
        暂无工作区
      </div>
      <div v-else>
        <div
          v-for="ws in existingWorkspaces"
          :key="ws.id"
          class="workspace-item"
          @click="openExistingWorkspace(ws); showWorkspaceList = false"
        >
          <div class="ws-info">
            <span class="ws-name">{{ ws.project_name }}</span>
            <span class="ws-type">{{ ws.project_type }}</span>
          </div>
          <div class="ws-actions-right">
            <el-tag size="small" :type="ws.status === 'ready' ? 'success' : 'warning'">{{ ws.status }}</el-tag>
            <el-button
              size="small"
              type="danger"
              text
              @click.stop="deleteWorkspace(ws)"
              class="ws-delete-btn"
            >删除</el-button>
          </div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, FolderOpened, Upload, Menu, TopRight, Monitor, Plus } from '@element-plus/icons-vue'
import { useCodingStore } from '@/stores/coding'
import type { PipelineStep, ChatMessage } from '@/stores/coding'
import { useUserStore } from '@/stores/user'
import { codingApi } from '@/api/coding'
import type { GeneratedFile, WorkspaceInfo } from '@/api/coding'

const router = useRouter()
const route = useRoute()
const codingStore = useCodingStore()
const userStore = useUserStore()

const userInput = ref('')
const chatAreaRef = ref<HTMLElement>()
const scrollAnchor = ref<HTMLElement>()

const existingWorkspaces = ref<WorkspaceInfo[]>([])
const showWorkspaceList = ref(false)
const isPublishing = ref(false)
const isDebugging = ref(false)

// ============ Suggestions ============

const suggestions = [
  '开发一个头像上传组件，支持裁剪和预览',
  '做一个数据查询表格页面，带搜索和分页',
  '实现一个日期范围选择器组件',
  '创建一个审批流程页面',
]

const inputPlaceholder = computed(() => {
  if (codingStore.workspace) {
    return '描述你的修改需求... (Ctrl+Enter 发送)'
  }
  return '描述你想开发的组件或页面... (Ctrl+Enter 发送)'
})

// ============ Lifecycle ============

onMounted(async () => {
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

// ============ Send Message / Auto Pipeline ============

function sendSuggestion(text: string) {
  userInput.value = text
  sendMessage()
}

async function sendMessage() {
  const message = userInput.value.trim()
  if (!message || codingStore.isProcessing) return

  userInput.value = ''
  codingStore.addMessage({ role: 'user', content: message })
  codingStore.isProcessing = true
  codingStore.streamContent = ''

  await nextTick()
  scrollToBottom()

  const isNewWorkspace = !codingStore.workspace
  const msgLower = message.toLowerCase()
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
    const body: Record<string, any> = {
      message,
      workspace_id: codingStore.workspace?.id || null,
      conversation_id: codingStore.conversationId || null,
      app_id: (route.query.app_id as string) || null,
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
            } else if (parsed.type === 'files') {
              // File list from generation
              if (parsed.files && Array.isArray(parsed.files)) {
                changedFiles = parsed.files
              }
            } else if (parsed.type === 'screenshot') {
              // Store screenshot URL for display
              currentScreenshots.push(parsed.url)
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
  showWorkspaceList.value = false
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

async function debugProject() {
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
        platform_url: 'https://apaas-dev8.dfy.definesys.cn/platform/',
        tenant_id: '566642786573484033',
        app_id: '806997227284201472',
      }),
    })
    const result = await resp.json()
    if (result.status === 'ok') {
      ElMessage.success('Debug 已启动！请在 Chromium 中登录平台后 F5 刷新')
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
.coding-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #0a0a0a;
  color: #e0e0e0;
}

/* ============ Header ============ */
.coding-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  border-bottom: 1px solid #1e1e1e;
  background: #111;
  height: 48px;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-title {
  font-size: 16px;
  font-weight: 600;
  background: linear-gradient(135deg, #667eea, #764ba2);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  margin: 0;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.header-btn {
  border-color: #333;
  background: #1a1a1a;
  color: #ccc;
}

.header-btn:hover {
  border-color: #555;
  background: #252525;
  color: #fff;
}

/* ============ Chat Area ============ */
.chat-area {
  flex: 1;
  overflow-y: auto;
  padding: 24px 0;
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
  max-width: 640px;
}

.welcome-icon {
  font-size: 48px;
  margin-bottom: 16px;
}

.welcome h2 {
  font-size: 28px;
  font-weight: 700;
  margin: 0 0 12px;
  background: linear-gradient(135deg, #667eea, #764ba2);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.welcome-desc {
  color: #888;
  font-size: 15px;
  margin: 0 0 32px;
  line-height: 1.6;
}

.suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: center;
}

.suggestion-btn {
  padding: 10px 18px;
  border-radius: 20px;
  border: 1px solid #2a2a2a;
  background: #151515;
  color: #ccc;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.suggestion-btn:hover {
  border-color: #667eea;
  background: #1a1a2e;
  color: #fff;
}

/* ============ Messages ============ */
.message {
  width: 100%;
  max-width: 760px;
  padding: 0 24px;
  margin-bottom: 24px;
}

.user-msg,
.assistant-msg {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.msg-avatar {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  flex-shrink: 0;
}

.user-avatar {
  background: #333;
  color: #fff;
}

.assistant-avatar {
  background: linear-gradient(135deg, #667eea, #764ba2);
  color: #fff;
}

.msg-bubble {
  flex: 1;
  min-width: 0;
}

.user-bubble {
  background: #1a1a2e;
  border-radius: 12px;
  padding: 12px 16px;
  color: #e0e0e0;
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.assistant-bubble {
  padding: 4px 0;
  font-size: 14px;
  line-height: 1.7;
  color: #d0d0d0;
}

/* ============ Pipeline Steps ============ */
.pipeline-steps {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.step {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 16px;
  font-size: 12px;
  font-weight: 500;
  border: 1px solid transparent;
}

.step.pending {
  background: #1a1a1a;
  color: #666;
  border-color: #2a2a2a;
}

.step.running {
  background: #1a1a2e;
  color: #667eea;
  border-color: #334;
  animation: pulse-border 1.5s ease-in-out infinite;
}

.step.done {
  background: #0d2818;
  color: #4ade80;
  border-color: #1a3a2a;
}

.step.error {
  background: #2a0d0d;
  color: #f87171;
  border-color: #3a1a1a;
}

@keyframes pulse-border {
  0%, 100% { border-color: #334; }
  50% { border-color: #667eea; }
}

.step-icon {
  font-size: 14px;
}

.step-label {
  white-space: nowrap;
}

/* ============ Message Text ============ */
.msg-text {
  word-break: break-word;
}

.msg-text :deep(.code-block) {
  margin: 12px 0;
  border-radius: 8px;
  overflow: hidden;
  background: #0d0d0d;
  border: 1px solid #1e1e1e;
}

.msg-text :deep(.code-block-header) {
  padding: 8px 12px;
  background: #151515;
  font-size: 12px;
  color: #999;
  border-bottom: 1px solid #1e1e1e;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 8px;
  user-select: none;
  list-style: none;
}

.msg-text :deep(.code-block-header::-webkit-details-marker) {
  display: none;
}

.msg-text :deep(.code-block-header::before) {
  content: '▶';
  font-size: 10px;
  color: #555;
  transition: transform 0.2s;
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
  color: #555;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px;
  flex: 1;
}

.msg-text :deep(.code-line-count) {
  color: #444;
  font-size: 11px;
  white-space: nowrap;
}

.msg-text :deep(.code-block pre) {
  margin: 0;
  padding: 12px 16px;
  overflow-x: auto;
  max-height: 400px;
  overflow-y: auto;
}

.msg-text :deep(.code-block code) {
  font-size: 12px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  color: #c0c0c0;
  line-height: 1.6;
}

.msg-text :deep(.code-inline) {
  margin: 8px 0;
  padding: 10px 12px;
  background: #111;
  border-radius: 6px;
  border: 1px solid #222;
  overflow-x: auto;
}

.msg-text :deep(.code-inline code) {
  font-size: 12px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  color: #c0c0c0;
}

.msg-text :deep(.inline-code) {
  background: #1a1a2e;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  color: #a78bfa;
}

/* ============ Inline Preview ============ */
.inline-preview {
  margin: 12px 0;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid #2a2a2a;
  background: #111;
}

.preview-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: #1a1a1a;
  border-bottom: 1px solid #2a2a2a;
  font-size: 13px;
  color: #aaa;
}

.preview-icon {
  font-size: 16px;
}

.preview-iframe {
  width: 100%;
  height: 280px;
  border: none;
  background: #fff;
  border-radius: 0 0 8px 8px;
}

/* ============ Debug Screenshots ============ */
.debug-screenshots {
  margin: 12px 0;
}

.screenshot-header {
  font-size: 12px;
  color: #888;
  margin-bottom: 8px;
}

.debug-screenshot {
  max-width: 100%;
  border-radius: 8px;
  border: 1px solid #2a2a2a;
  cursor: pointer;
  transition: opacity 0.2s;
}

.debug-screenshot:hover {
  opacity: 0.85;
}

/* ============ File Summary ============ */
.file-summary {
  margin-top: 10px;
  padding: 8px 12px;
  border-radius: 8px;
  background: #111;
  border: 1px solid #222;
  font-size: 12px;
  color: #888;
}

.file-summary-icon {
  margin-right: 4px;
}

/* ============ Typing / Thinking ============ */
.typing-cursor {
  color: #667eea;
  animation: blink 1s step-end infinite;
}

@keyframes blink {
  50% { opacity: 0; }
}

.thinking-dots {
  display: flex;
  gap: 4px;
  padding: 8px 0;
}

.thinking-dots span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #444;
  animation: thinking 1.4s ease-in-out infinite;
}

.thinking-dots span:nth-child(2) {
  animation-delay: 0.2s;
}

.thinking-dots span:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes thinking {
  0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
  40% { opacity: 1; transform: scale(1); }
}

/* ============ Input Area ============ */
.input-area {
  flex-shrink: 0;
  padding: 12px 24px 16px;
  border-top: 1px solid #1e1e1e;
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
  max-width: 760px;
  background: #151515;
  border: 1px solid #2a2a2a;
  border-radius: 16px;
  padding: 8px 12px;
  transition: border-color 0.2s;
}

.input-wrapper:focus-within {
  border-color: #667eea;
}

.input-wrapper :deep(.el-textarea__inner) {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
  color: #e0e0e0;
  font-size: 14px;
  line-height: 1.5;
  padding: 4px 0;
  resize: none;
}

.send-btn {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
}

.input-hint {
  font-size: 11px;
  color: #555;
  margin-top: 6px;
}

/* ============ Workspace Dialog ============ */
.ws-dialog :deep(.el-dialog) {
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
}

.workspace-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.2s;
  margin-bottom: 4px;
}

.workspace-item:hover {
  background: #252525;
}

.ws-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.ws-name {
  font-size: 14px;
  font-weight: 500;
  color: #e0e0e0;
}

.ws-type {
  font-size: 12px;
  color: #888;
}

.ws-actions {
  margin-bottom: 12px;
}

.ws-actions-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.ws-delete-btn {
  font-size: 12px;
  padding: 2px 6px;
}

/* ============ Scrollbar ============ */
.chat-area::-webkit-scrollbar {
  width: 6px;
}

.chat-area::-webkit-scrollbar-track {
  background: transparent;
}

.chat-area::-webkit-scrollbar-thumb {
  background: #2a2a2a;
  border-radius: 3px;
}

.chat-area::-webkit-scrollbar-thumb:hover {
  background: #3a3a3a;
}
</style>
