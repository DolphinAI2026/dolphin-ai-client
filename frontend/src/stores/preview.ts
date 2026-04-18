import { defineStore } from 'pinia'
import { ref, reactive } from 'vue'
import type { PreviewData, GenProgress } from '@/types'

// 应用名的"默认/占位"值集合——任何一处写入落到这些值上都视为"还没拿到真名"，应该被忽略
// 以避免上游（LLM/加载旧记录/路由切换等）用默认值覆盖掉已经正确的 preview.appName
const APP_NAME_DEFAULTS = new Set(['', '未命名应用', '业务应用', '应用'])

export const usePreviewStore = defineStore('preview', () => {
  // currentApp 只保留应用元数据（id/status/apaas 关联），名字请统一从 preview.appName 读
  const currentApp = ref<{ id?: number; status: string; apaas_app_id?: string } | null>(null)
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
    forms: [],
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

  /**
   * 统一的 preview.appName 写入入口。
   *
   * 过滤策略：
   *   - 空串 / "未命名应用" / "业务应用" / "应用" 一律不写入
   *     （避免 LLM/加载旧记录/路由切换用默认值覆盖掉正确的值）
   *   - 传 { force: true } 时强制写入，用于明确的 reset 场景
   *
   * 返回 true 表示实际写入，false 表示被过滤。
   */
  function setAppName(raw: unknown, options: { force?: boolean } = {}): boolean {
    const candidate = String(raw ?? '').trim()
    if (options.force) {
      preview.appName = candidate
      return true
    }
    if (!candidate || APP_NAME_DEFAULTS.has(candidate)) {
      return false
    }
    preview.appName = candidate
    return true
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
    preview.forms = []
    preview.workflows = []
    preview.permissions = []
    resetGenProgress()
  }

  return {
    currentApp, previewTab, previewFormIdx, connected, showConnectModal, pendingFile, pendingBuilderModelId, pendingMarkdown, showChangePlan, changePlan,
    preview, genProgress,
    resetGenProgress, reset, setAppName
  }
})
