import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { CodingScene, GeneratedFile, CodingConversation, WorkspaceInfo } from '@/api/coding'

export interface PipelineStep {
  name: string
  label: string
  status: 'pending' | 'running' | 'done' | 'error'
  message?: string
}

export interface ChatActivityItem {
  id: number
  label: string
  description: string
  tone: 'default' | 'success' | 'error'
}

export interface ChatMessage {
  id?: number
  role: 'user' | 'assistant' | 'system'
  content: string
  files?: GeneratedFile[]
  pipelineSteps?: PipelineStep[]
  textContent?: string
  textHtml?: string
  fileNames?: string[]
  thinkingSummary?: string
  thinkingHtml?: string
  previewHtml?: string
  screenshots?: string[]
  activityFeed?: ChatActivityItem[]
  _previewCollapsed?: boolean
  created_at?: string
}

export const useCodingStore = defineStore('coding', () => {
  // 当前场景
  const currentScene = ref<CodingScene | null>(null)
  const scenes = ref<CodingScene[]>([])

  // 工作区
  const workspace = ref<WorkspaceInfo | null>(null)
  const workspaceFiles = ref<string[]>([])
  const workspaceStatus = ref<string>('')
  const workspacePath = ref<string | null>(null)

  // 对话
  const conversationId = ref<number | null>(null)
  const conversations = ref<CodingConversation[]>([])
  const messages = ref<ChatMessage[]>([])

  // 生成的文件（编辑器中展示的文件内容）
  const generatedFiles = ref<GeneratedFile[]>([])
  const activeFilePath = ref<string>('')
  const validationErrors = ref<string[]>([])

  // 状态
  const isGenerating = ref(false)
  const isProcessing = ref(false)
  const streamContent = ref('')

  // Pipeline
  const currentPipelineSteps = ref<PipelineStep[]>([])

  // Serve
  const serveUrl = ref<string | null>(null)
  const serveRunning = ref(false)

  // 对话驱动的当前运行预览（run_result/autofix_round 写入，预览位读）
  const activePreview = ref<{
    dev_url: string; status: string; errors: string[]; capture_available: boolean; round: number | null; source?: string
  } | null>(null)
  // 预览每跑一次就 +1(agent run_workspace_preview 的 run_result 写入时递增)。
  // CodingPage 监听它强制切到「预览」位 —— 即使 dev_url 没变也切(自愈轮不递增, 不打扰)。
  const previewEpoch = ref(0)

  // Token 用量（done 事件写入, 新会话/reset 清空）
  const tokenUsage = ref<{ input: number; output: number; contextTokens: number; contextBudget: number } | null>(null)
  const contextWarnDismissed = ref(false)

  // 当前选中文件的内容
  const activeFileContent = computed(() => {
    const file = generatedFiles.value.find(f => f.path === activeFilePath.value)
    return file?.content ?? ''
  })

  const activeFileLanguage = computed(() => {
    const file = generatedFiles.value.find(f => f.path === activeFilePath.value)
    return file?.language ?? 'text'
  })

  function setScene(scene: CodingScene) {
    currentScene.value = scene
  }

  function setWorkspace(ws: WorkspaceInfo) {
    workspace.value = ws
    workspaceFiles.value = ws.files || []
    workspaceStatus.value = ws.status
  }

  function setFiles(files: GeneratedFile[]) {
    generatedFiles.value = files
    if (files.length > 0 && !activeFilePath.value) {
      activeFilePath.value = files[0]?.path || ''
    }
  }

  function updateFileContent(path: string, content: string) {
    const file = generatedFiles.value.find(f => f.path === path)
    if (file) {
      file.content = content
    }
  }

  function addMessage(msg: ChatMessage) {
    messages.value.push(msg)
  }

  function setMessages(nextMessages: ChatMessage[]) {
    messages.value = nextMessages
  }

  // 后端/脚本类项目不需要 npm install 和 dev server
  const NO_NPM_PROJECT_TYPES = new Set([
    'backend-api', 'backend-feign', 'backend-scheduled',
    'script', 'script-js', 'script-python', 'script-groovy',
  ])

  function initPipelineSteps(isNewWorkspace: boolean, projectType?: string | null) {
    const needsNpm = !projectType || !NO_NPM_PROJECT_TYPES.has(projectType)
    if (isNewWorkspace) {
      const steps: PipelineStep[] = [
        { name: 'create_workspace', label: '创建工作区', status: 'pending' },
        { name: 'generate', label: '生成代码', status: 'pending' },
      ]
      if (needsNpm) {
        steps.push(
          { name: 'install', label: '安装依赖', status: 'pending' },
          { name: 'serve', label: '启动服务', status: 'pending' },
        )
      }
      currentPipelineSteps.value = steps
    } else {
      currentPipelineSteps.value = [
        { name: 'generate', label: '生成代码', status: 'pending' },
      ]
    }
  }

  function updatePipelineStep(stepName: string, status: PipelineStep['status'], message?: string) {
    const step = currentPipelineSteps.value.find(s => s.name === stepName)
    if (step) {
      step.status = status
      if (message) step.message = message
    }
  }

  function reset() {
    currentScene.value = null
    workspace.value = null
    workspaceFiles.value = []
    workspaceStatus.value = ''
    workspacePath.value = null
    conversationId.value = null
    messages.value = []
    generatedFiles.value = []
    activeFilePath.value = ''
    validationErrors.value = []
    isGenerating.value = false
    isProcessing.value = false
    streamContent.value = ''
    currentPipelineSteps.value = []
    serveUrl.value = null
    serveRunning.value = false
    tokenUsage.value = null
    contextWarnDismissed.value = false
  }

  return {
    currentScene, scenes,
    workspace, workspaceFiles, workspaceStatus, workspacePath,
    conversationId, conversations, messages,
    generatedFiles, activeFilePath, activeFileContent, activeFileLanguage,
    validationErrors, isGenerating, isProcessing, streamContent,
    currentPipelineSteps, serveUrl, serveRunning, activePreview, previewEpoch,
    tokenUsage, contextWarnDismissed,
    setScene, setWorkspace, setFiles, updateFileContent, addMessage, setMessages,
    initPipelineSteps, updatePipelineStep, reset,
  }
})
