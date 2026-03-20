<template>
  <div class="coding-page">
    <!-- 顶部工具栏 -->
    <header class="coding-header">
      <div class="header-left">
        <el-button text @click="$router.push('/')">
          <el-icon><ArrowLeft /></el-icon>
        </el-button>
        <h3 class="header-title">Vibe Coding</h3>
        <el-tag v-if="codingStore.workspace" size="small" type="info">
          {{ codingStore.workspace.project_name }}
        </el-tag>
        <el-tag v-if="codingStore.workspaceStatus" size="small" :type="statusTagType">
          {{ statusText }}
        </el-tag>
      </div>
      <div class="header-right">
        <el-button v-if="codingStore.workspace" size="small" @click="showWorkspaceList = true">
          <el-icon><FolderOpened /></el-icon> 工作区
        </el-button>
        <el-button v-if="codingStore.generatedFiles.length" size="small" @click="downloadProject">
          <el-icon><Download /></el-icon> 下载代码
        </el-button>
      </div>
    </header>

    <!-- ============ 初始化向导（无工作区时） ============ -->
    <div v-if="!codingStore.workspace" class="init-wizard">
      <div class="wizard-container">
        <div class="wizard-header">
          <h2>创建自开发项目</h2>
          <p>选择项目类型并命名，系统会自动生成符合 aPaaS 规范的脚手架</p>
        </div>

        <!-- 已有工作区列表 -->
        <div v-if="existingWorkspaces.length > 0" class="existing-workspaces">
          <div class="section-label">继续已有项目</div>
          <div class="workspace-list">
            <div
              v-for="ws in existingWorkspaces"
              :key="ws.id"
              class="workspace-item"
              @click="openExistingWorkspace(ws)"
            >
              <span class="ws-icon">{{ projectTypeIcons[ws.project_type] || '📦' }}</span>
              <div class="ws-info">
                <span class="ws-name">{{ ws.project_name }}</span>
                <span class="ws-type">{{ projectTypeLabels[ws.project_type] }}</span>
              </div>
              <el-tag size="small" :type="ws.status === 'ready' ? 'success' : 'warning'">{{ ws.status }}</el-tag>
            </div>
          </div>
          <div class="divider-text">或创建新项目</div>
        </div>

        <!-- 项目类型选择 -->
        <div class="type-selector">
          <div class="section-label">项目类型</div>
          <div class="type-grid">
            <div
              v-for="pt in projectTypes"
              :key="pt.value"
              :class="['type-card', { selected: newProjectType === pt.value }]"
              @click="newProjectType = pt.value"
            >
              <div class="type-icon">{{ pt.icon }}</div>
              <div class="type-name">{{ pt.label }}</div>
              <div class="type-desc">{{ pt.desc }}</div>
            </div>
          </div>
        </div>

        <!-- 项目名称 -->
        <div class="name-input-section">
          <div class="section-label">项目名称</div>
          <el-input
            v-model="newProjectName"
            placeholder="例如: avatar-upload, smart-dispatch"
            size="large"
            @keydown.enter="createProject"
          >
            <template #prepend>{{ projectNamePrefix }}</template>
          </el-input>
        </div>

        <!-- 创建按钮 -->
        <el-button
          type="primary"
          size="large"
          class="create-btn"
          :loading="isCreating"
          :disabled="!newProjectName.trim() || !newProjectType"
          @click="createProject"
        >
          创建项目并初始化脚手架
        </el-button>
      </div>
    </div>

    <!-- ============ 工作区主界面 ============ -->
    <div v-else class="coding-main">
      <!-- 左侧：对话面板 -->
      <div class="panel-chat">
        <div class="panel-section-title">AI 对话</div>

        <!-- 对话消息 -->
        <div ref="messagesRef" class="messages-area">
          <!-- 初始提示 -->
          <div v-if="codingStore.messages.length === 0" class="welcome-message">
            <div class="message message-assistant">
              <div class="message-avatar">🤖</div>
              <div class="message-content">
                项目 <strong>{{ codingStore.workspace?.project_name }}</strong> 已创建，脚手架已就绪。<br><br>
                你可以直接描述需求，我会帮你修改和生成代码。例如：<br>
                <span class="suggestion" @click="userInput = suggestion" v-for="suggestion in quickSuggestions" :key="suggestion">
                  「{{ suggestion }}」
                </span>
              </div>
            </div>
          </div>

          <div
            v-for="(msg, idx) in codingStore.messages"
            :key="idx"
            :class="['message', `message-${msg.role}`]"
          >
            <div class="message-avatar">{{ msg.role === 'user' ? '👤' : '🤖' }}</div>
            <div class="message-content">
              <div v-if="msg.role === 'assistant'" v-html="renderMarkdown(msg.content)"></div>
              <div v-else>{{ msg.content }}</div>
            </div>
          </div>
          <!-- 流式输出 -->
          <div v-if="codingStore.isGenerating" class="message message-assistant">
            <div class="message-avatar">🤖</div>
            <div class="message-content">
              <div v-html="renderMarkdown(codingStore.streamContent)"></div>
              <span class="typing-cursor">▊</span>
            </div>
          </div>
        </div>

        <!-- 输入框 -->
        <div class="input-area">
          <el-input
            v-model="userInput"
            type="textarea"
            :rows="3"
            :placeholder="inputPlaceholder"
            @keydown.enter.ctrl="sendMessage"
            :disabled="codingStore.isGenerating"
          />
          <el-button
            type="primary"
            :loading="codingStore.isGenerating"
            @click="sendMessage"
            :disabled="!userInput.trim()"
          >
            发送
          </el-button>
        </div>
      </div>

      <!-- 中间：代码编辑器 + 预览 -->
      <div class="panel-editor">
        <div class="panel-section-title">
          <div class="editor-tabs">
            <button
              :class="['editor-tab', { active: editorMode === 'code' }]"
              @click="editorMode = 'code'"
            >
              代码
            </button>
            <button
              :class="['editor-tab', { active: editorMode === 'preview' }]"
              @click="editorMode = 'preview'"
              :disabled="!codingStore.generatedFiles.length"
            >
              预览
            </button>
          </div>
          <span v-if="editorMode === 'code' && codingStore.activeFilePath" class="active-file-path">
            {{ codingStore.activeFilePath }}
          </span>
          <span v-if="editorMode === 'preview'" class="preview-hint">
            沙箱预览 (Vue 2 + Element UI + Mock aPaaS)
          </span>
        </div>

        <!-- 文件标签（代码模式） -->
        <div v-if="editorMode === 'code' && codingStore.generatedFiles.length" class="file-tabs">
          <div
            v-for="file in codingStore.generatedFiles"
            :key="file.path"
            :class="['file-tab', { active: file.path === codingStore.activeFilePath }]"
            @click="codingStore.activeFilePath = file.path"
            :title="file.path"
          >
            <span class="file-icon">{{ getFileIcon(file.language) }}</span>
            <span class="file-name">{{ getFileName(file.path) }}</span>
          </div>
        </div>

        <!-- 预览文件选择（预览模式） -->
        <div v-if="editorMode === 'preview' && previewableFiles.length > 1" class="file-tabs">
          <div
            v-for="file in previewableFiles"
            :key="file.path"
            :class="['file-tab', { active: file.path === previewFilePath }]"
            @click="previewFilePath = file.path"
            :title="file.path"
          >
            <span class="file-icon">{{ getFileIcon(file.language) }}</span>
            <span class="file-name">{{ getFileName(file.path) }}</span>
          </div>
        </div>

        <!-- 代码展示区 -->
        <div v-show="editorMode === 'code'" class="code-area">
          <div v-if="!codingStore.generatedFiles.length" class="empty-state">
            <div class="empty-icon">💻</div>
            <p>在左侧对话中描述需求，AI 会修改工作区文件</p>
          </div>
          <div v-else class="code-editor-wrapper">
            <div class="code-toolbar">
              <el-button size="small" text @click="copyCode">
                <el-icon><CopyDocument /></el-icon> 复制
              </el-button>
            </div>
            <pre class="code-content"><code>{{ codingStore.activeFileContent }}</code></pre>
          </div>
        </div>

        <!-- 预览区域 -->
        <div v-show="editorMode === 'preview'" class="preview-area">
          <div v-if="!codingStore.generatedFiles.length" class="empty-state">
            <div class="empty-icon">👁️</div>
            <p>生成代码后可在此预览组件效果</p>
          </div>
          <iframe
            v-else
            ref="previewIframeRef"
            :srcdoc="previewHtml"
            class="preview-iframe"
            sandbox="allow-scripts allow-same-origin"
          ></iframe>
        </div>
      </div>

      <!-- 右侧：文件树 + 操作 -->
      <div class="panel-sidebar">
        <div class="panel-section-title">
          项目结构
          <el-button size="small" text @click="refreshWorkspaceFiles" style="margin-left:auto;">
            刷新
          </el-button>
        </div>

        <!-- 工作区操作按钮 -->
        <div class="workspace-actions">
          <el-button size="small" @click="installDeps" :loading="isInstalling" :disabled="isInstalling">
            npm install
          </el-button>
          <el-button size="small" @click="buildProject" :loading="isBuilding" :disabled="isBuilding">
            构建
          </el-button>
        </div>

        <!-- 文件树（层级） -->
        <div class="file-tree">
          <div v-if="!codingStore.workspaceFiles.length" class="empty-state-small">
            暂无文件
          </div>
          <div v-else>
            <template v-for="node in fileTree" :key="node.path">
              <div
                v-if="node.type === 'dir'"
                v-show="!isFileHidden(node.path + '/x')"
                :class="['tree-dir', { collapsed: collapsedDirs.has(node.path) }]"
              >
                <div class="tree-dir-header" @click="toggleDir(node.path)" :style="{ paddingLeft: (node.depth * 14 + 8) + 'px' }">
                  <span class="tree-arrow">{{ collapsedDirs.has(node.path) ? '▸' : '▾' }}</span>
                  <span class="tree-dir-icon">📁</span>
                  <span class="tree-dir-name">{{ node.name }}</span>
                </div>
              </div>
              <div
                v-else
                v-show="!isFileHidden(node.path)"
                :class="['tree-item', { active: node.path === codingStore.activeFilePath }]"
                @click="openWorkspaceFile(node.path)"
                :style="{ paddingLeft: (node.depth * 14 + 8) + 'px' }"
              >
                <span class="tree-icon">{{ getFileIcon(detectLanguage(node.path)) }}</span>
                <span class="tree-path">{{ node.name }}</span>
              </div>
            </template>
          </div>
        </div>

        <!-- 校验结果 -->
        <div v-if="codingStore.validationErrors.length" class="validation-section">
          <div class="panel-section-title validation-title">
            ⚠️ 规范校验
          </div>
          <div class="validation-list">
            <div v-for="(err, idx) in codingStore.validationErrors" :key="idx" class="validation-item">
              {{ err }}
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 工作区列表弹窗 -->
    <el-dialog v-model="showWorkspaceList" title="我的工作区" width="500px">
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
          <span class="ws-icon">{{ projectTypeIcons[ws.project_type] || '📦' }}</span>
          <div class="ws-info">
            <span class="ws-name">{{ ws.project_name }}</span>
            <span class="ws-type">{{ projectTypeLabels[ws.project_type] }}</span>
          </div>
          <el-tag size="small" :type="ws.status === 'ready' ? 'success' : 'warning'">{{ ws.status }}</el-tag>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Download, CopyDocument, FolderOpened } from '@element-plus/icons-vue'
import { useCodingStore } from '@/stores/coding'
import { useUserStore } from '@/stores/user'
import { codingApi } from '@/api/coding'
import type { CodingScene, GeneratedFile, WorkspaceInfo } from '@/api/coding'

const router = useRouter()
const route = useRoute()
const codingStore = useCodingStore()
const userStore = useUserStore()

const userInput = ref('')
const messagesRef = ref<HTMLElement>()
const previewIframeRef = ref<HTMLIFrameElement>()
const editorMode = ref<'code' | 'preview'>('code')
const previewFilePath = ref('')

// ============ 初始化向导状态 ============
const newProjectType = ref('form-component')
const newProjectName = ref('')
const isCreating = ref(false)
const existingWorkspaces = ref<WorkspaceInfo[]>([])
const showWorkspaceList = ref(false)
const isInstalling = ref(false)
const isBuilding = ref(false)

const projectTypes = [
  { value: 'form-component', label: '表单组件', icon: '🧩', desc: '自定义表单字段组件' },
  { value: 'form-page', label: '菜单页面', icon: '📄', desc: '自定义菜单页面' },
  { value: 'form-list', label: '列表视图', icon: '📋', desc: '自定义列表展示' },
  { value: 'backend-api', label: '后端接口', icon: '⚙️', desc: 'Java SpringBoot 接口' },
]

const projectTypeLabels: Record<string, string> = {
  'form-component': '表单组件',
  'form-page': '菜单页面',
  'form-list': '列表视图',
  'backend-api': '后端接口',
}

const projectTypeIcons: Record<string, string> = {
  'form-component': '🧩',
  'form-page': '📄',
  'form-list': '📋',
  'backend-api': '⚙️',
}

const projectNamePrefix = computed(() => {
  const prefixes: Record<string, string> = {
    'form-component': 'form-component-',
    'form-page': 'form-page-',
    'form-list': 'form-list-',
    'backend-api': 'backend-api-',
  }
  return prefixes[newProjectType.value] || ''
})

const quickSuggestions = computed(() => {
  const type = codingStore.workspace?.project_type
  if (type === 'form-component') {
    return ['实现一个头像上传组件', '添加一个日期范围选择器', '做一个富文本编辑器组件']
  } else if (type === 'form-page') {
    return ['添加一个数据查询表格页面', '增加新增和编辑弹窗功能', '添加搜索筛选条件']
  } else if (type === 'form-list') {
    return ['自定义列表列渲染', '添加行操作按钮', '实现批量操作功能']
  } else if (type === 'backend-api') {
    return ['添加分页查询接口', '增加新增和删除接口', '添加Excel导出功能']
  }
  return ['描述你要开发的功能']
})

const statusText = computed(() => {
  const map: Record<string, string> = {
    creating: '创建中...',
    installing: '安装依赖中...',
    ready: '就绪',
    building: '构建中...',
    error: '异常',
  }
  return map[codingStore.workspaceStatus] || codingStore.workspaceStatus
})

const statusTagType = computed(() => {
  const map: Record<string, string> = {
    creating: 'warning',
    installing: 'warning',
    ready: 'success',
    building: 'warning',
    error: 'danger',
  }
  return (map[codingStore.workspaceStatus] || 'info') as any
})

const inputPlaceholder = computed(() => {
  return '描述你的开发需求，AI 会直接修改工作区文件... (Ctrl+Enter 发送)'
})

// ============ 生命周期 ============

onMounted(async () => {
  // 加载用户已有工作区
  try {
    existingWorkspaces.value = await codingApi.listWorkspaces()
  } catch (e) {
    console.error('获取工作区列表失败:', e)
  }

  // 如果有 workspace_id 参数，直接打开
  const wsId = route.query.workspace_id as string
  if (wsId) {
    await openWorkspaceById(wsId)
  }

  // 如果有对话ID参数，恢复对话
  const convId = route.query.conversation_id
  if (convId) {
    await restoreConversation(Number(convId))
  }
})

// ============ 工作区操作 ============

async function createProject() {
  if (!newProjectName.value.trim() || !newProjectType.value || isCreating.value) return

  isCreating.value = true
  try {
    const ws = await codingApi.createWorkspace(newProjectType.value, newProjectName.value.trim())
    codingStore.setWorkspace(ws)

    // 加载脚手架文件到编辑器
    await loadWorkspaceFiles(ws.id)

    ElMessage.success('项目创建成功，脚手架已就绪')
  } catch (error: any) {
    ElMessage.error(`创建失败: ${error.message}`)
  } finally {
    isCreating.value = false
  }
}

async function openExistingWorkspace(ws: WorkspaceInfo) {
  await openWorkspaceById(ws.id)
}

async function openWorkspaceById(wsId: string) {
  try {
    const ws = await codingApi.getWorkspace(wsId)
    codingStore.setWorkspace(ws)
    await loadWorkspaceFiles(wsId)
    // 加载工作区的历史对话
    await loadWorkspaceConversation(wsId)
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
          codingStore.addMessage({ role: msg.role, content: msg.content })
        }
      }
    }
  } catch {
    // 无历史对话，忽略
  }
}

async function loadWorkspaceFiles(wsId: string) {
  try {
    const files = await codingApi.listFiles(wsId)
    codingStore.workspaceFiles = files

    // 加载所有文件内容到编辑器
    const generatedFiles: GeneratedFile[] = []
    for (const fp of files) {
      try {
        const { content } = await codingApi.readFile(wsId, fp)
        generatedFiles.push({
          path: fp,
          content,
          language: detectLanguage(fp),
        })
      } catch {
        // skip unreadable files
      }
    }
    codingStore.setFiles(generatedFiles)
  } catch (error: any) {
    console.error('加载文件失败:', error)
  }
}

async function refreshWorkspaceFiles() {
  if (!codingStore.workspace) return
  await loadWorkspaceFiles(codingStore.workspace.id)
  ElMessage.success('已刷新')
}

async function openWorkspaceFile(filePath: string) {
  codingStore.activeFilePath = filePath
  // 如果文件还没加载内容，从后端读取
  const existing = codingStore.generatedFiles.find(f => f.path === filePath)
  if (!existing && codingStore.workspace) {
    try {
      const { content } = await codingApi.readFile(codingStore.workspace.id, filePath)
      codingStore.generatedFiles.push({
        path: filePath,
        content,
        language: detectLanguage(filePath),
      })
    } catch (e: any) {
      ElMessage.error(`读取文件失败: ${e.message}`)
    }
  }
}

async function installDeps() {
  if (!codingStore.workspace) return
  isInstalling.value = true
  codingStore.workspaceStatus = 'installing'
  try {
    const result = await codingApi.installDeps(codingStore.workspace.id)
    if (result.status === 'ok' || result.status === 'skip') {
      ElMessage.success(result.message)
      codingStore.workspaceStatus = 'ready'
    } else {
      ElMessage.error(result.message)
      codingStore.workspaceStatus = 'error'
    }
  } catch (error: any) {
    ElMessage.error(`安装失败: ${error.message}`)
    codingStore.workspaceStatus = 'error'
  } finally {
    isInstalling.value = false
  }
}

async function buildProject() {
  if (!codingStore.workspace) return
  isBuilding.value = true
  codingStore.workspaceStatus = 'building'
  try {
    const result = await codingApi.buildProject(codingStore.workspace.id)
    if (result.status === 'ok') {
      ElMessage.success(result.message)
      codingStore.workspaceStatus = 'ready'
    } else {
      ElMessage.error(result.message)
      codingStore.workspaceStatus = 'error'
    }
  } catch (error: any) {
    ElMessage.error(`构建失败: ${error.message}`)
    codingStore.workspaceStatus = 'error'
  } finally {
    isBuilding.value = false
  }
}

// ============ AI 对话 ============

async function sendMessage() {
  const message = userInput.value.trim()
  if (!message || codingStore.isGenerating) return

  userInput.value = ''
  codingStore.addMessage({ role: 'user', content: message })
  codingStore.isGenerating = true
  codingStore.streamContent = ''

  await nextTick()
  scrollToBottom()

  try {
    const token = userStore.token
    const body: Record<string, any> = {
      message,
      scene_type: sceneTypeFromProjectType(codingStore.workspace?.project_type),
      conversation_id: codingStore.conversationId,
      app_id: route.query.app_id as string || null,
      workspace_id: codingStore.workspace?.id || null,
    }

    const response = await fetch('/api/coding/generate-stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify(body),
    })

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`)
    }

    const reader = response.body?.getReader()
    const decoder = new TextDecoder()
    let fullContent = ''

    if (reader) {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        const text = decoder.decode(value, { stream: true })
        const lines = text.split('\n')

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const data = line.slice(6).trim()
          if (!data || data === '[DONE]') continue

          try {
            const parsed = JSON.parse(data)

            if (parsed.type === 'scene_detected') {
              codingStore.conversationId = parsed.conversation_id
            } else if (parsed.type === 'content') {
              fullContent += parsed.content
              codingStore.streamContent = fullContent
              scrollToBottom()
            } else if (parsed.type === 'done') {
              codingStore.conversationId = parsed.conversation_id
            }
          } catch {
            // skip unparseable lines
          }
        }
      }
    }

    // 流式结束，解析文件
    codingStore.addMessage({ role: 'assistant', content: fullContent })

    // 从回复中提取文件并写入工作区
    const files = parseFilesFromContent(fullContent)
    if (files.length > 0 && codingStore.workspace) {
      // 写入工作区
      for (const file of files) {
        try {
          await codingApi.writeFile(codingStore.workspace.id, file.path, file.content)
        } catch (e) {
          console.error(`写入文件失败: ${file.path}`, e)
        }
      }

      // 更新编辑器中的文件
      for (const file of files) {
        const existing = codingStore.generatedFiles.find(f => f.path === file.path)
        if (existing) {
          existing.content = file.content
        } else {
          codingStore.generatedFiles.push(file)
        }
        // 也更新文件列表
        if (!codingStore.workspaceFiles.includes(file.path)) {
          codingStore.workspaceFiles.push(file.path)
        }
      }

      // 激活第一个变更的文件
      codingStore.activeFilePath = files[0].path
    }

    // 检查元数据（校验结果）
    const metaMatch = fullContent.match(/<!--GENERATION_META:(.*?)-->/)
    if (metaMatch) {
      try {
        const meta = JSON.parse(metaMatch[1])
        if (meta.validation_errors?.length) {
          codingStore.validationErrors = meta.validation_errors
        }
      } catch {}
    }
  } catch (error: any) {
    ElMessage.error(`生成失败: ${error.message}`)
    codingStore.addMessage({ role: 'assistant', content: `生成失败: ${error.message}` })
  } finally {
    codingStore.isGenerating = false
    codingStore.streamContent = ''
  }
}

function sceneTypeFromProjectType(projectType?: string): string | null {
  const map: Record<string, string> = {
    'form-component': 'web_component',
    'form-page': 'web_page',
    'form-list': 'web_list_view',
    'backend-api': 'backend_api',
  }
  return projectType ? map[projectType] || null : null
}

// ============ 文件解析 ============

function parseFilesFromContent(content: string): GeneratedFile[] {
  const files: GeneratedFile[] = []
  // 支持 ```file:path 和 ```language:path 两种格式
  const regex = /```(?:file|[\w]+):([^\n]+)\n([\s\S]*?)```/g
  let match
  while ((match = regex.exec(content)) !== null) {
    const path = match[1].trim()
    const fileContent = match[2].trim()
    if (path && fileContent) {
      files.push({
        path,
        content: fileContent,
        language: detectLanguage(path),
      })
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

async function restoreConversation(conversationId: number) {
  try {
    codingStore.conversationId = conversationId
    const messages = await codingApi.getMessages(conversationId)
    for (const msg of messages) {
      codingStore.addMessage({
        id: msg.id,
        role: msg.role,
        content: msg.content,
        created_at: msg.created_at,
      })
      if (msg.role === 'assistant') {
        const files = parseFilesFromContent(msg.content)
        if (files.length > 0) {
          codingStore.setFiles(files)
        }
      }
    }
  } catch (e) {
    console.error('恢复对话失败:', e)
  }
}

// ============ 文件树（层级） ============

interface TreeNode {
  type: 'file' | 'dir'
  name: string
  path: string   // 对于 dir 是目录前缀，对于 file 是完整路径
  depth: number
}

const collapsedDirs = ref<Set<string>>(new Set())

const fileTree = computed<TreeNode[]>(() => {
  const files = codingStore.workspaceFiles
  if (!files.length) return []

  const nodes: TreeNode[] = []
  const seenDirs = new Set<string>()

  for (const fp of files.sort()) {
    const parts = fp.split('/')
    // 添加目录节点
    for (let i = 0; i < parts.length - 1; i++) {
      const dirPath = parts.slice(0, i + 1).join('/')
      if (!seenDirs.has(dirPath)) {
        seenDirs.add(dirPath)
        nodes.push({ type: 'dir', name: parts[i], path: dirPath, depth: i })
      }
    }
    // 添加文件节点
    nodes.push({ type: 'file', name: parts[parts.length - 1], path: fp, depth: parts.length - 1 })
  }

  return nodes
})

function toggleDir(dirPath: string) {
  const newSet = new Set(collapsedDirs.value)
  if (newSet.has(dirPath)) {
    newSet.delete(dirPath)
  } else {
    newSet.add(dirPath)
  }
  collapsedDirs.value = newSet
}

function isFileHidden(filePath: string): boolean {
  // 如果任何父目录被折叠则隐藏
  const parts = filePath.split('/')
  for (let i = 1; i < parts.length; i++) {
    const parentDir = parts.slice(0, i).join('/')
    if (collapsedDirs.value.has(parentDir)) return true
  }
  return false
}

// ============ UI 工具 ============

function getFileName(path: string): string {
  return path.split('/').pop() || path
}

function getFileIcon(language: string): string {
  const icons: Record<string, string> = {
    vue: '💚', javascript: '📒', typescript: '💙', json: '📋',
    css: '🎨', scss: '🎨', java: '☕', python: '🐍',
    groovy: '☕', xml: '📄', html: '🌐', text: '📄',
  }
  return icons[language] || '📄'
}

function renderMarkdown(content: string): string {
  return content
    .replace(/```file:([^\n]+)\n([\s\S]*?)```/g, '<div class="code-block"><div class="code-block-header">$1</div><pre><code>$2</code></pre></div>')
    .replace(/```(\w+)\n([\s\S]*?)```/g, '<pre class="code-inline"><code>$2</code></pre>')
    .replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')
    .replace(/\n/g, '<br>')
}

async function copyCode() {
  const content = codingStore.activeFileContent
  if (content) {
    await navigator.clipboard.writeText(content)
    ElMessage.success('已复制到剪贴板')
  }
}

function downloadProject() {
  const files = codingStore.generatedFiles
  if (!files.length) return

  if (files.length === 1) {
    const blob = new Blob([files[0].content], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = getFileName(files[0].path)
    a.click()
    URL.revokeObjectURL(url)
    return
  }

  let combined = ''
  for (const file of files) {
    combined += `\n${'='.repeat(60)}\n`
    combined += `// 文件: ${file.path}\n`
    combined += `${'='.repeat(60)}\n\n`
    combined += file.content
    combined += '\n'
  }
  const blob = new Blob([combined], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${codingStore.workspace?.project_name || 'apaas-custom-code'}.txt`
  a.click()
  URL.revokeObjectURL(url)
}

// ============ 预览相关 ============

function isPreviewable(file: GeneratedFile): boolean {
  if (file.path.endsWith('.vue')) return true
  if (file.path.endsWith('.js') && (
    file.content.includes('template:') ||
    file.content.includes('<template>') ||
    (file.content.includes('export default') && (file.content.includes('mixins') || file.content.includes('data(') || file.content.includes('render(')))
  )) return true
  return false
}

const previewableFiles = computed(() =>
  codingStore.generatedFiles.filter(f => isPreviewable(f))
)

function parseSFC(content: string) {
  const templateMatch = content.match(/<template>([\s\S]*?)<\/template>/)
  const scriptMatch = content.match(/<script>([\s\S]*?)<\/script>/)
  const styleMatch = content.match(/<style[^>]*>([\s\S]*?)<\/style>/)

  const template = templateMatch ? templateMatch[1].trim() : ''
  const scriptRaw = scriptMatch ? scriptMatch[1] : ''
  const style = styleMatch ? styleMatch[1] : ''

  const processedScript = scriptRaw
    .replace(/import\s+[\s\S]*?from\s+['"][^'"]*['"]\s*;?/g, '')
    .replace(/export\s+default\s*\{/, 'var __component__ = {')
    .trim()

  return { template, script: processedScript, style }
}

function parseJSComponent(content: string) {
  let script = content
    .replace(/import\s+[\s\S]*?from\s+['"][^'"]*['"]\s*;?/g, '')
    .trim()

  const templateLiteralMatch = script.match(/template\s*:\s*`([\s\S]*?)`/)
  const templateStringMatch = script.match(/template\s*:\s*'([\s\S]*?)'/)
  const template = templateLiteralMatch ? templateLiteralMatch[1]
    : templateStringMatch ? templateStringMatch[1]
    : ''

  script = script
    .replace(/export\s+default\s*\{/, 'var __component__ = {')
    .trim()

  if (!script.includes('__component__')) {
    script = script.replace(/module\.exports\s*=\s*\{/, 'var __component__ = {')
  }

  return { template, script, style: '' }
}

const previewHtml = computed(() => {
  const files = codingStore.generatedFiles
  if (!files.length) return ''

  const targetPath = previewFilePath.value
  const previewFile = files.find(f => f.path === targetPath && isPreviewable(f))
    || files.find(f => f.path.endsWith('.vue') && f.path.includes('edit'))
    || files.find(f => f.path.endsWith('.vue') && !f.path.includes('read'))
    || files.find(f => f.path.endsWith('.vue'))
    || files.find(f => f.path.endsWith('.js') && f.path.includes('/edit/') && isPreviewable(f))
    || files.find(f => f.path.endsWith('.js') && isPreviewable(f) && !f.path.includes('/read/') && !f.path.endsWith('/index.js'))
    || previewableFiles.value[0]

  if (!previewFile) return '<html><body style="color:#888;text-align:center;padding:40px;font-family:sans-serif;"><p>没有可预览的组件文件</p><p style="font-size:12px;color:#aaa;">需要生成包含 template 的 .vue 或 .js 文件</p></body></html>'

  if (!previewFilePath.value && previewFile) {
    previewFilePath.value = previewFile.path
  }

  const isVue = previewFile.path.endsWith('.vue')
  const parsed = isVue ? parseSFC(previewFile.content) : parseJSComponent(previewFile.content)
  const isReadMode = previewFile.path.includes('/read/') || previewFile.path.includes('-read')

  return buildSandboxHtml(parsed.template, parsed.script, parsed.style, isReadMode)
})

function buildSandboxHtml(template: string, script: string, style: string, isReadMode: boolean): string {
  const safeTemplate = template.replace(/\\/g, '\\\\').replace(/`/g, '\\`').replace(/\$\{/g, '\\${')

  return `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="stylesheet" href="https://unpkg.com/element-ui@2.15.14/lib/theme-chalk/index.css">
  <script src="https://unpkg.com/vue@2.7.16/dist/vue.js"><\/script>
  <script src="https://unpkg.com/element-ui@2.15.14/lib/index.js"><\/script>
  <style>
    * { box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      padding: 24px;
      margin: 0;
      background: #fff;
      color: #333;
    }
    .preview-header {
      margin-bottom: 20px;
      padding-bottom: 12px;
      border-bottom: 1px solid #eee;
    }
    .preview-header h3 { margin: 0 0 4px; font-size: 16px; color: #333; }
    .preview-header p { margin: 0; font-size: 12px; color: #999; }
    .preview-form { max-width: 600px; }
    .x-proxy-form-item { margin-bottom: 16px; }
    .el-form-item { margin-bottom: 16px; }
    ${style}
  </style>
</head>
<body>
  <div id="app">
    <div class="preview-header">
      <h3>${isReadMode ? '只读模式预览' : '编辑模式预览'}</h3>
      <p>aPaaS 沙箱环境 · Vue 2 + Element UI · Mock 平台组件</p>
    </div>
    <div class="preview-form">
      <el-form label-width="100px" label-position="top">
        <preview-component></preview-component>
      </el-form>
    </div>
  </div>

  <script>
    var FormWidgetConfigMixin = {
      props: {
        widget: {
          type: Object,
          default: function() {
            return { code: 'demo_field', name: '示例字段', label: '示例字段', config: { placeholder: '请输入' }, isInTable: false };
          }
        },
        validatorRules: { type: Array, default: function() { return []; } },
        disabled: { type: Boolean, default: false },
        formType: { type: String, default: '${isReadMode ? 'read' : 'edit'}' },
        formReadonly: { type: Boolean, default: ${isReadMode} },
        formDisabled: { type: Boolean, default: false },
        showRequired: { type: Boolean, default: false },
        validateKey: { type: String, default: '' },
        validateInfo: { type: Object, default: function() { return {}; } }
      },
      data: function() {
        return {
          formValue: ''
        };
      },
      methods: {
        handleValueChange: function(val) {
          this.formValue = val;
          this.$emit('value-change', { code: this.widget.code, value: val });
        }
      }
    };

    Vue.component('x-proxy-form-item', {
      props: {
        widget: { type: Object, default: function() { return { name: '字段', label: '字段' }; } },
        isInTable: { type: Boolean, default: false },
        showRequired: { type: Boolean, default: false },
        label: { type: String, default: '' },
        formType: { type: String, default: 'edit' },
        validatorRules: { type: Array, default: function() { return []; } },
        validateKey: { type: String, default: '' },
        validateInfo: { type: Object, default: function() { return {}; } }
      },
      template: '<div class="x-proxy-form-item"><el-form-item :label="label || (widget && widget.label) || (widget && widget.name)" :rules="validatorRules"><slot></slot></el-form-item></div>'
    });

    Vue.component('x-ag-grid', {
      props: { rowKey: String, tableData: Array, colConfigs: Array, pagination: Object },
      template: '<div class="x-ag-grid-mock"><el-table :data="tableData" border style="width:100%"><el-table-column v-for="col in colConfigs" :key="col.field" :prop="col.field" :label="col.headerName"></el-table-column></el-table><el-pagination v-if="pagination" layout="total,prev,pager,next" :total="pagination.total" :page-size="pagination.pageSize" :current-page="pagination.currentPage" @current-change="$emit(\\\'current-page-change\\\', $event)" @size-change="$emit(\\\'size-change\\\', $event)" style="margin-top:16px;"></el-pagination></div>'
    });

    try {
      ${script}

      if (__component__) {
        if (__component__.mixins) {
          __component__.mixins = __component__.mixins.map(function(m) {
            if (m === undefined || m === null || typeof m === 'string') return FormWidgetConfigMixin;
            return m;
          });
        } else {
          __component__.mixins = [FormWidgetConfigMixin];
        }

        var tpl = \`${safeTemplate}\`;
        if (tpl && tpl.trim()) {
          __component__.template = tpl;
        }
        if (!__component__.template) {
          __component__.template = '<div style="color:#999;padding:20px;">组件未定义 template</div>';
        }

        Vue.component('preview-component', __component__);
        new Vue({ el: '#app' });
      }
    } catch(e) {
      document.getElementById('app').innerHTML =
        '<div style="color:#e74c3c;padding:20px;">' +
        '<h3>预览渲染出错</h3>' +
        '<pre style="background:#f8f8f8;padding:12px;border-radius:4px;font-size:12px;overflow:auto;">' +
        e.message + '\\n\\n' + e.stack +
        '</pre></div>';
    }
  <\/script>
</body>
</html>`;
}

// 代码生成完成后自动切换到预览
watch(() => codingStore.generatedFiles.length, (newLen, oldLen) => {
  if (newLen > 0 && oldLen === 0) {
    const hasPreviewable = codingStore.generatedFiles.some(f => isPreviewable(f))
    if (hasPreviewable) {
      editorMode.value = 'preview'
      previewFilePath.value = ''
    }
  }
})

function scrollToBottom() {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  })
}

// 清理
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

/* Header */
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

/* ============ 初始化向导 ============ */
.init-wizard {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow-y: auto;
  padding: 40px 20px;
}
.wizard-container {
  max-width: 640px;
  width: 100%;
}
.wizard-header {
  text-align: center;
  margin-bottom: 32px;
}
.wizard-header h2 {
  font-size: 24px;
  font-weight: 700;
  margin: 0 0 8px;
  background: linear-gradient(135deg, #667eea, #764ba2);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}
.wizard-header p {
  color: #888;
  font-size: 14px;
  margin: 0;
}

.section-label {
  font-size: 13px;
  font-weight: 600;
  color: #aaa;
  margin-bottom: 10px;
}

/* 已有工作区 */
.existing-workspaces {
  margin-bottom: 24px;
}
.workspace-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 16px;
}
.workspace-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: #151515;
  border: 1px solid #222;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}
.workspace-item:hover {
  border-color: #667eea;
  background: #1a1a2e;
}
.ws-icon { font-size: 20px; }
.ws-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.ws-name { font-size: 13px; font-weight: 500; }
.ws-type { font-size: 11px; color: #888; }

.divider-text {
  text-align: center;
  color: #555;
  font-size: 12px;
  margin: 16px 0;
  position: relative;
}
.divider-text::before,
.divider-text::after {
  content: '';
  position: absolute;
  top: 50%;
  width: 40%;
  height: 1px;
  background: #222;
}
.divider-text::before { left: 0; }
.divider-text::after { right: 0; }

/* 项目类型选择 */
.type-selector {
  margin-bottom: 20px;
}
.type-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}
.type-card {
  padding: 16px 12px;
  border: 1px solid #222;
  border-radius: 10px;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
}
.type-card:hover {
  border-color: #444;
  background: #151515;
}
.type-card.selected {
  border-color: #667eea;
  background: #1a1a2e;
  box-shadow: 0 0 0 1px #667eea;
}
.type-icon {
  font-size: 28px;
  margin-bottom: 6px;
}
.type-name {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 4px;
}
.type-desc {
  font-size: 11px;
  color: #888;
}

/* 名称输入 */
.name-input-section {
  margin-bottom: 24px;
}
.name-input-section :deep(.el-input__wrapper) {
  background: #151515;
  box-shadow: 0 0 0 1px #2a2a2a inset;
}
.name-input-section :deep(.el-input__inner) {
  color: #e0e0e0;
}
.name-input-section :deep(.el-input-group__prepend) {
  background: #1a1a1a;
  color: #888;
  border-color: #2a2a2a;
}

.create-btn {
  width: 100%;
  height: 44px;
  font-size: 15px;
}

/* ============ 主体区域 ============ */
.coding-main {
  flex: 1;
  display: flex;
  overflow: hidden;
}

/* Chat Panel */
.panel-chat {
  width: 380px;
  min-width: 320px;
  display: flex;
  flex-direction: column;
  border-right: 1px solid #1e1e1e;
  background: #0d0d0d;
}

.panel-section-title {
  padding: 10px 16px;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: #888;
  border-bottom: 1px solid #1a1a1a;
  display: flex;
  align-items: center;
  gap: 8px;
}

/* Messages */
.messages-area {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}
.message {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}
.message-avatar {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  flex-shrink: 0;
}
.message-content {
  flex: 1;
  font-size: 13px;
  line-height: 1.6;
  overflow-wrap: break-word;
}
.message-user .message-content {
  background: #1a1a2e;
  padding: 8px 12px;
  border-radius: 8px;
}

.suggestion {
  display: inline-block;
  margin: 4px 4px 4px 0;
  padding: 4px 10px;
  background: #1a1a2e;
  border: 1px solid #333;
  border-radius: 12px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}
.suggestion:hover {
  border-color: #667eea;
  background: #222244;
}

.typing-cursor {
  animation: blink 1s infinite;
  color: #667eea;
}
@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

/* Input */
.input-area {
  padding: 12px;
  border-top: 1px solid #1a1a1a;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.input-area :deep(.el-textarea__inner) {
  background: #151515;
  border-color: #2a2a2a;
  color: #e0e0e0;
  resize: none;
}
.input-area :deep(.el-textarea__inner:focus) {
  border-color: #667eea;
}

/* Editor Panel */
.panel-editor {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

/* Editor mode tabs */
.editor-tabs {
  display: flex;
  gap: 2px;
}
.editor-tab {
  padding: 4px 14px;
  font-size: 12px;
  font-weight: 500;
  color: #666;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}
.editor-tab:hover:not(:disabled) {
  color: #aaa;
  background: #1a1a1a;
}
.editor-tab.active {
  color: #667eea;
  background: #1a1a2e;
  border-color: #333;
}
.editor-tab:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.preview-hint {
  font-weight: 400;
  color: #10b981;
  font-size: 11px;
  margin-left: auto;
}

.active-file-path {
  font-weight: 400;
  color: #667eea;
  font-size: 11px;
  margin-left: auto;
}

/* Preview */
.preview-area {
  flex: 1;
  overflow: hidden;
  background: #fff;
  border-radius: 0;
}
.preview-iframe {
  width: 100%;
  height: 100%;
  border: none;
  background: #fff;
}

.file-tabs {
  display: flex;
  overflow-x: auto;
  border-bottom: 1px solid #1a1a1a;
  background: #0d0d0d;
}
.file-tab {
  padding: 6px 14px;
  font-size: 12px;
  color: #888;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 4px;
  transition: all 0.2s;
}
.file-tab:hover {
  color: #ccc;
  background: #151515;
}
.file-tab.active {
  color: #e0e0e0;
  border-bottom-color: #667eea;
  background: #111;
}
.file-icon { font-size: 12px; }
.file-name { font-size: 12px; }

.code-area {
  flex: 1;
  overflow: auto;
  position: relative;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #555;
}
.empty-icon {
  font-size: 48px;
  margin-bottom: 16px;
}
.empty-state p {
  font-size: 14px;
}

.code-editor-wrapper {
  height: 100%;
  display: flex;
  flex-direction: column;
}
.code-toolbar {
  display: flex;
  justify-content: flex-end;
  padding: 4px 8px;
  border-bottom: 1px solid #1a1a1a;
  background: #0d0d0d;
}
.code-content {
  flex: 1;
  margin: 0;
  padding: 16px;
  font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace;
  font-size: 13px;
  line-height: 1.6;
  color: #d4d4d4;
  background: #0a0a0a;
  overflow: auto;
  tab-size: 2;
  white-space: pre;
}

/* Sidebar */
.panel-sidebar {
  width: 280px;
  min-width: 240px;
  border-left: 1px solid #1e1e1e;
  background: #0d0d0d;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

.workspace-actions {
  padding: 8px 12px;
  display: flex;
  gap: 6px;
  border-bottom: 1px solid #1a1a1a;
}

.file-tree {
  flex: 1;
  padding: 4px 0;
  overflow-y: auto;
}
.tree-dir-header {
  padding: 3px 8px;
  font-size: 12px;
  color: #ccc;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 4px;
  user-select: none;
}
.tree-dir-header:hover {
  background: #1a1a1a;
}
.tree-arrow {
  font-size: 10px;
  color: #666;
  width: 12px;
  text-align: center;
  flex-shrink: 0;
}
.tree-dir-icon {
  font-size: 12px;
  flex-shrink: 0;
}
.tree-dir-name {
  font-size: 12px;
  font-weight: 500;
}
.tree-item {
  padding: 3px 8px;
  font-size: 12px;
  color: #aaa;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 4px;
}
.tree-item:hover {
  background: #1a1a1a;
}
.tree-item.active {
  background: #1a1a2e;
  color: #667eea;
}
.tree-icon { font-size: 12px; flex-shrink: 0; }
.tree-path { font-size: 11px; }

.empty-state-small {
  padding: 16px;
  text-align: center;
  color: #555;
  font-size: 12px;
}

/* Validation */
.validation-section {
  border-top: 1px solid #1a1a1a;
}
.validation-title {
  color: #f0a020 !important;
}
.validation-list {
  padding: 8px;
}
.validation-item {
  padding: 6px 8px;
  font-size: 11px;
  color: #f0a020;
  background: #1a1a0e;
  border-radius: 4px;
  margin-bottom: 4px;
}

/* Markdown code blocks in chat */
.message-content :deep(.code-block) {
  margin: 8px 0;
  border: 1px solid #222;
  border-radius: 6px;
  overflow: hidden;
}
.message-content :deep(.code-block-header) {
  padding: 4px 10px;
  font-size: 11px;
  color: #888;
  background: #151515;
  border-bottom: 1px solid #222;
}
.message-content :deep(.code-block pre) {
  margin: 0;
  padding: 10px;
  font-size: 12px;
  overflow-x: auto;
}
.message-content :deep(.code-inline) {
  margin: 8px 0;
  padding: 10px;
  background: #111;
  border-radius: 4px;
  font-size: 12px;
  overflow-x: auto;
}
.message-content :deep(.inline-code) {
  background: #222;
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 12px;
}

/* Scrollbar */
::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
::-webkit-scrollbar-track {
  background: transparent;
}
::-webkit-scrollbar-thumb {
  background: #333;
  border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover {
  background: #555;
}
</style>
