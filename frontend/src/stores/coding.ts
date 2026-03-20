import { defineStore } from 'pinia'
import { ref, reactive, computed } from 'vue'
import type { CodingScene, GeneratedFile, CodingConversation, WorkspaceInfo } from '@/api/coding'

export interface CodingMessage {
  id?: number
  role: 'user' | 'assistant' | 'system'
  content: string
  files?: GeneratedFile[]
  created_at?: string
}

export const useCodingStore = defineStore('coding', () => {
  // 当前场景
  const currentScene = ref<CodingScene | null>(null)
  const scenes = ref<CodingScene[]>([])

  // 工作区
  const workspace = ref<WorkspaceInfo | null>(null)
  const workspaceFiles = ref<string[]>([])       // 工作区文件路径列表
  const workspaceStatus = ref<string>('')         // creating | installing | ready | building | error

  // 对话
  const conversationId = ref<number | null>(null)
  const conversations = ref<CodingConversation[]>([])
  const messages = ref<CodingMessage[]>([])

  // 生成的文件（编辑器中展示的文件内容）
  const generatedFiles = ref<GeneratedFile[]>([])
  const activeFilePath = ref<string>('')
  const validationErrors = ref<string[]>([])

  // 状态
  const isGenerating = ref(false)
  const streamContent = ref('')

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
    // 切换工作区时清空对话和编辑器状态
    conversationId.value = null
    messages.value = []
    generatedFiles.value = []
    activeFilePath.value = ''
    validationErrors.value = []
    isGenerating.value = false
    streamContent.value = ''
  }

  function setFiles(files: GeneratedFile[]) {
    generatedFiles.value = files
    if (files.length > 0 && !activeFilePath.value) {
      activeFilePath.value = files[0].path
    }
  }

  function updateFileContent(path: string, content: string) {
    const file = generatedFiles.value.find(f => f.path === path)
    if (file) {
      file.content = content
    }
  }

  function addMessage(msg: CodingMessage) {
    messages.value.push(msg)
  }

  function reset() {
    currentScene.value = null
    workspace.value = null
    workspaceFiles.value = []
    workspaceStatus.value = ''
    conversationId.value = null
    messages.value = []
    generatedFiles.value = []
    activeFilePath.value = ''
    validationErrors.value = []
    isGenerating.value = false
    streamContent.value = ''
  }

  return {
    currentScene, scenes,
    workspace, workspaceFiles, workspaceStatus,
    conversationId, conversations, messages,
    generatedFiles, activeFilePath, activeFileContent, activeFileLanguage,
    validationErrors, isGenerating, streamContent,
    setScene, setWorkspace, setFiles, updateFileContent, addMessage, reset,
  }
})
