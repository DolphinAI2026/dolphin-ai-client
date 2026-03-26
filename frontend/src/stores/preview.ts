import { defineStore } from 'pinia'
import { ref, reactive } from 'vue'
import type { PreviewData, GenProgress } from '@/types'
import type { DiffResponse } from '@/api/incremental'

export const usePreviewStore = defineStore('preview', () => {
  const currentApp = ref<{ name: string; status: string; apaas_app_id?: string } | null>(null)
  const previewTab = ref('overview')
  const previewFormIdx = ref(0)
  const connected = ref(false)
  const showConnectModal = ref(false)
  const pendingFile = ref<File | null>(null)  // 从 Landing 页带过来的待解析文件

  // 增量变更计划
  const changePlan = ref<{
    id: number
    fromVersion: number
    toVersion: number
    diffSummary: DiffResponse | null
    actions: Array<{
      id: string
      selected: boolean
      op: string
      target?: string
      model?: string
      value?: any
      description: string
    }>
    status: string
  } | null>(null)

  const showChangePlan = ref(false)

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
    changePlan.value = null
    showChangePlan.value = false
    preview.appName = ''
    preview.roles = []
    preview.dicts = []
    preview.models = []
    preview.workflows = []
    preview.permissions = []
    resetGenProgress()
  }

  return {
    currentApp, previewTab, previewFormIdx, connected, showConnectModal, pendingFile,
    preview, genProgress, changePlan, showChangePlan,
    resetGenProgress, reset
  }
})
