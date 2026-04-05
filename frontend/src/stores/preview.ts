import { defineStore } from 'pinia'
import { ref, reactive } from 'vue'
import type { PreviewData, GenProgress } from '@/types'

export const usePreviewStore = defineStore('preview', () => {
  const currentApp = ref<{ name: string; status: string; apaas_app_id?: string } | null>(null)
  const previewTab = ref('overview')
  const previewFormIdx = ref(0)
  const connected = ref(false)
  const showConnectModal = ref(false)
  const pendingFile = ref<File | null>(null)  // 从 Landing 页带过来的待解析文件
  const pendingBuilderModelId = ref<number | null>(null)  // 从 Landing 页带到 Chat 的 builder 模型
  const pendingMarkdown = ref<{ filename: string; content: string } | null>(null)  // 从需求分析页带到 Chat 的设计文档
  const showChangePlan = ref(false)
  const changePlan = ref<any | null>(null)

  const preview = reactive<PreviewData>({
    appName: '',
    roles: [],
    dicts: [],
    models: [],
    workflows: [],
    permissions: []
  })

  const defaultStages = () => [
    { name: '解析配置', status: 'pending' as const, steps: [] as string[] },
    { name: '公共资源（角色+字典）', status: 'pending' as const, steps: [] as string[] },
    { name: '创建数据模型', status: 'pending' as const, steps: [] as string[] },
    { name: '创建表单+绑定字典', status: 'pending' as const, steps: [] as string[] },
    { name: '配置权限', status: 'pending' as const, steps: [] as string[] },
  ]

  const genProgress = reactive<GenProgress>({
    stage: 0,
    stages: defaultStages()
  })

  function resetGenProgress() {
    genProgress.stage = 0
    genProgress.stages = defaultStages()
  }

  function reset() {
    currentApp.value = null
    previewTab.value = 'overview'
    previewFormIdx.value = 0
    pendingBuilderModelId.value = null
    showChangePlan.value = false
    changePlan.value = null
    preview.appName = ''
    preview.roles = []
    preview.dicts = []
    preview.models = []
    preview.workflows = []
    preview.permissions = []
    resetGenProgress()
  }

  return {
    currentApp, previewTab, previewFormIdx, connected, showConnectModal, pendingFile, pendingBuilderModelId, pendingMarkdown, showChangePlan, changePlan,
    preview, genProgress,
    resetGenProgress, reset
  }
})
