<template>
  <section class="ai-builder-panel">
    <article class="builder-studio-card">
      <div class="entry-mode-switcher" role="tablist" aria-label="AI 入口模式">
        <button
          v-for="item in builderModes"
          :key="item.key"
          class="entry-mode-btn"
          :class="{ active: builderMode === item.key }"
          type="button"
          @click="setBuilderMode(item.key)"
        >
          <span class="entry-mode-label">{{ item.label }}</span>
          <span class="entry-mode-zh">{{ item.zh }}</span>
        </button>
      </div>

      <div class="panel-eyebrow">{{ currentBuilderMode.eyebrow }}</div>
      <div class="panel-title-row">
        <div class="panel-title-copy">
          <h2 class="panel-title">{{ currentBuilderMode.title }}</h2>
          <p class="panel-subtitle">
            {{ currentBuilderMode.subtitle }}
          </p>
        </div>
      </div>

      <div class="conversation-shell">
        <div class="ai-prompt-card">
          <div class="ai-prompt-avatar">AI</div>
          <div class="ai-prompt-copy">
            <div class="ai-prompt-title">直接告诉我你要做什么系统，或者上传已有文档。</div>
            <div class="ai-prompt-text">
              先不用自己判断该走智能搭建还是智能开发。AI 会先理解需求，再整理出统一设计文档。
            </div>
          </div>
        </div>

        <div class="composer-card">
          <label class="input-block">
            <span class="input-label">对话输入</span>
            <textarea
              v-model="businessInput"
              class="panel-textarea composer-textarea"
              :placeholder="currentBuilderMode.placeholder"
              rows="6"
            ></textarea>
          </label>

          <div class="composer-actions-row">
            <div class="upload-row">
              <input
                ref="fileInputRef"
                type="file"
                accept=".md,.markdown,.txt,.pdf,.doc,.docx,.png,.jpg,.jpeg,.gif,.webp"
                hidden
                @change="handleFileSelect"
              />
              <button class="upload-trigger" type="button" @click="fileInputRef?.click()">
                <span class="upload-trigger-icon">+</span>
                <span>上传需求文档 / PRD / SOW</span>
              </button>
              <div class="upload-hint">文档也会被 AI 作为同一轮需求输入来理解。</div>
            </div>
            <div class="composer-footer-actions">
              <button
                v-if="builderMode === 'cowork'"
                class="secondary-inline-action"
                type="button"
                @click="advancedOpen = !advancedOpen"
              >
                {{ advancedOpen ? '收起高级补充' : '补充项目 / 模型 / 自开发关注点' }}
              </button>
              <button class="secondary-action compact-action" type="button" :disabled="isGenerating" @click="resetPanel">
                清空
              </button>
              <button
                class="primary-action compact-action"
                type="button"
                :disabled="isGenerating || (!businessInput.trim() && !attachedFile)"
                @click="handleModeSubmit"
              >
                {{ isGenerating ? 'AI 正在理解需求...' : currentBuilderMode.cta }}
              </button>
            </div>
          </div>
        </div>
      </div>

      <div v-if="advancedOpen && builderMode === 'cowork'" class="advanced-panel">
        <div class="advanced-panel-head">
          <div class="advanced-panel-title">高级补充</div>
          <div class="advanced-panel-subtitle">可选：绑定协作项目、切换分析模型，或补充你已经知道需要自开发的部分。</div>
        </div>
        <div class="composer-context-row">
          <div class="field-group">
            <span class="field-label">目标项目</span>
            <el-select
              v-model="selectedProjectId"
              clearable
              filterable
              placeholder="可选，绑定到某个协作项目"
              class="field-select"
            >
              <el-option
                v-for="project in projects"
                :key="project.id"
                :label="project.name"
                :value="project.id"
              />
            </el-select>
          </div>
          <div class="field-group">
            <span class="field-label">分析模型</span>
            <el-select
              v-model="selectedBuilderModelId"
              class="field-select"
              popper-class="model-select-dropdown"
              placeholder="选择模型"
              :loading="builderModelLoading"
              :disabled="builderModelLoading || builderModelOptions.length === 0"
            >
              <el-option
                v-for="option in builderModelOptions"
                :key="option.id"
                :label="option.config_name"
                :value="option.id"
              >
                <div class="builder-model-option-row">
                  <span class="builder-model-option-name">{{ option.config_name }}</span>
                  <span class="builder-model-option-meta">{{ option.provider }} / {{ option.model }}</span>
                </div>
              </el-option>
            </el-select>
          </div>
        </div>
        <label class="input-block">
          <span class="input-label">自开发关注点</span>
          <textarea
            v-model="codingFocus"
            class="panel-textarea panel-textarea-secondary"
            placeholder="如果你已经知道哪些部分可能需要自开发，可以补充给 AI，例如：复杂页面、专用组件、外部接口、统计看板等。"
            rows="4"
          ></textarea>
        </label>
      </div>

      <div v-if="attachedFile" class="attached-file-card">
        <div class="attached-file-main">
          <div class="attached-file-name">{{ attachedFile.name }}</div>
          <div class="attached-file-meta">
            {{ formatFileSize(attachedFile.size) }}
            <span v-if="attachedFile.type">· {{ attachedFile.type }}</span>
          </div>
        </div>
        <button class="attached-file-remove" type="button" @click="clearAttachedFile">移除</button>
      </div>

    </article>

    <article class="builder-result-card">
      <div class="result-header">
        <div>
          <div class="panel-eyebrow">AI 判断结果</div>
          <h3 class="result-title">{{ resultTitle }}</h3>
        </div>
        <div class="result-status-chip" :class="{ running: isGenerating, ready: !!docResult }">
          {{ resultStatusLabel }}
        </div>
      </div>

      <div v-if="isGenerating || !docResult" class="status-list">
        <div
          v-for="(item, index) in statusItems"
          :key="`${index}-${item.label}`"
          class="status-item"
          :class="item.state"
        >
          <span class="status-dot"></span>
          <div class="status-copy">
            <div class="status-label">{{ item.label }}</div>
            <div v-if="item.detail" class="status-detail">{{ item.detail }}</div>
          </div>
        </div>
      </div>

      <div v-if="errorMessage && (isGenerating || !docResult)" class="error-banner">{{ errorMessage }}</div>

      <div v-if="combinedSummary && !docResult" class="summary-card">
        <div class="summary-title">AI 需求理解</div>
        <div class="summary-body markdown-body" v-html="renderMarkdown(combinedSummary)"></div>
      </div>

      <template v-if="docResult">
        <div class="summary-card">
          <div class="summary-title">AI 需求理解</div>
          <div class="summary-body markdown-body" v-html="renderMarkdown(combinedSummary)"></div>
        </div>

        <div class="design-doc-card">
          <div class="section-kicker">统一设计文档</div>
          <div class="design-doc-title">AI 已把需求拆成“配置部分”和“自开发部分”</div>
          <div class="design-doc-grid">
            <article class="design-section-card">
              <div class="design-section-label">配置部分</div>
              <div class="design-section-title">{{ builderScopeMetric }}</div>
              <div class="design-section-text">{{ builderScopeSummary }}</div>
              <div class="design-section-points">
                <div
                  v-for="(point, index) in configHighlights"
                  :key="`config-${index}-${point}`"
                  class="design-point"
                >
                  {{ point }}
                </div>
              </div>
            </article>
            <article class="design-section-card design-section-card-accent">
              <div class="design-section-label">自开发部分</div>
              <div class="design-section-title">{{ codingScopeMetric }}</div>
              <div class="design-section-text">{{ codingScopeSummary }}</div>
              <div class="design-section-points">
                <div
                  v-for="(point, index) in customDevHighlights"
                  :key="`coding-${index}-${point}`"
                  class="design-point"
                >
                  {{ point }}
                </div>
              </div>
            </article>
          </div>
        </div>

        <div class="plan-card">
          <div class="section-kicker">确认后 AI 会这样生成应用</div>
          <div class="plan-list">
            <div
              v-for="(step, index) in executionPlan"
              :key="`${index}-${step.title}`"
              class="plan-step"
            >
              <div class="plan-step-index">{{ String(index + 1).padStart(2, '0') }}</div>
              <div class="plan-step-copy">
                <div class="plan-step-title">{{ step.title }}</div>
                <div class="plan-step-text">{{ step.detail }}</div>
              </div>
            </div>
          </div>
        </div>

        <div class="cta-card">
          <div class="cta-copy">
            <div class="section-kicker">确认设计文档</div>
            <div class="cta-title">{{ primaryActionTitle }}</div>
            <div class="cta-text">{{ primaryActionText }}</div>
          </div>
          <div class="dispatch-row">
            <button class="dispatch-btn" type="button" @click="handlePrimaryAction">
              {{ primaryActionLabel }}
            </button>
            <button
              v-if="showCodingAction"
              class="dispatch-btn ghost"
              type="button"
              @click="dispatchToCoding"
            >
              直接看开发任务
            </button>
            <button
              class="dispatch-btn ghost"
              type="button"
              @click="detailsExpanded = !detailsExpanded"
            >
              {{ detailsExpanded ? '收起内部细节' : '查看内部细节' }}
            </button>
          </div>
        </div>

        <div v-if="detailsExpanded" class="details-panel">
          <div v-if="errorMessage" class="error-banner subtle">{{ errorMessage }}</div>

          <div class="details-block">
            <div class="section-kicker">分析过程</div>
            <div class="status-list compact">
              <div
                v-for="(item, index) in statusItems"
                :key="`detail-${index}-${item.label}`"
                class="status-item"
                :class="item.state"
              >
                <span class="status-dot"></span>
                <div class="status-copy">
                  <div class="status-label">{{ item.label }}</div>
                  <div v-if="item.detail" class="status-detail">{{ item.detail }}</div>
                </div>
              </div>
            </div>
          </div>

          <div class="result-tabs">
            <button
              v-for="tab in resultTabs"
              :key="tab.key"
              type="button"
              class="result-tab"
              :class="{ active: activeTab === tab.key }"
              @click="activeTab = tab.key"
            >
              {{ tab.label }}
            </button>
          </div>

          <div v-if="activeTab === 'structure'" class="result-surface structured-surface">
            <StructuredDocRenderer :doc-result="docResult" />
          </div>
          <pre v-else-if="activeTab === 'builder'" class="result-surface result-pre">{{ builderMarkdown }}</pre>
          <pre v-else class="result-surface result-pre">{{ codingBrief }}</pre>

          <div class="download-row">
            <button class="download-link" type="button" @click="downloadBuilderMarkdown">
              下载 Builder Markdown
            </button>
            <button class="download-link" type="button" @click="downloadCodingBrief">
              下载 Coding Brief
            </button>
          </div>
        </div>
      </template>

      <div v-else class="empty-state">
        <div class="empty-state-title">先告诉 AI 你想交付什么</div>
        <div class="empty-state-text">
          这里不会先堆一排工具入口。
          <br />
          AI 会先理解业务目标，再判断平台搭建与自开发边界，最后给出一个明确的下一步。
        </div>
      </div>
    </article>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { llmConfigApi, type BuilderModelOption } from '@/api/llmConfig'
import { projectsApi, type Project } from '@/api/projects'
import { requirementsApi, type AnalysisResult } from '@/api/requirements'
import { usePreviewStore } from '@/stores/preview'
import StructuredDocRenderer from '@/components/StructuredDocRenderer.vue'
import { renderMarkdown } from '@/utils/requirements'
import {
  buildBuilderMarkdownFilename,
  buildCodingBriefFilename,
} from '@/utils/aiBuilder'

type ResultTabKey = 'structure' | 'builder' | 'coding'
type StatusState = 'idle' | 'running' | 'done' | 'error'
type BuilderModeKey = 'chat' | 'cowork' | 'code'

interface StatusItem {
  label: string
  detail?: string
  state: StatusState
}

interface PendingCodingPayload {
  message: string
  projectId: number | null
  sceneCategory: string
}

const PENDING_CODING_KEY = 'ai_builder_pending_coding'

const router = useRouter()
const previewStore = usePreviewStore()

const builderModelOptions = ref<BuilderModelOption[]>([])
const builderModelLoading = ref(false)
const selectedBuilderModelId = ref<number | null>(null)

const projects = ref<Project[]>([])
const selectedProjectId = ref<number | null>(null)

const businessInput = ref('')
const codingFocus = ref('')
const advancedOpen = ref(false)
const builderMode = ref<BuilderModeKey>('cowork')
const attachedFile = ref<File | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)

const isGenerating = ref(false)
const errorMessage = ref('')
const requirementDigest = ref('')
const generatedSummary = ref('')
const docResult = ref<AnalysisResult | null>(null)
const builderMarkdown = ref('')
const codingBrief = ref('')
const recommendedSceneCategory = ref('page-pc')
const activeTab = ref<ResultTabKey>('structure')
const detailsExpanded = ref(false)

const statusItems = ref<StatusItem[]>([
  { label: '等待输入业务需求或上传文档', state: 'idle' },
  { label: '系统会先做统一需求收口', state: 'idle' },
  { label: '随后导出 Builder Markdown 与 Coding Brief', state: 'idle' },
])

const resultTabs = [
  { key: 'structure' as ResultTabKey, label: '完整设计文档' },
  { key: 'builder' as ResultTabKey, label: '配置生成文档' },
  { key: 'coding' as ResultTabKey, label: '自开发任务文档' },
]

const builderModes = [
  {
    key: 'chat' as BuilderModeKey,
    label: 'Chat',
    zh: '问答 / 操作',
    eyebrow: 'Chat',
    title: '直接进入 Chat 工作台',
    subtitle: '适合问业务数据、查流程、操作已有应用，输入会带到真实 Chat 工作台里继续处理。',
    placeholder: '比如：上季度华东销售额是多少？工单 #2408 为什么卡住了？',
    cta: '进入 Chat',
  },
  {
    key: 'cowork' as BuilderModeKey,
    label: 'CoWork',
    zh: '协同构建',
    eyebrow: 'AI Builder',
    title: '先用对话讲清楚你要交付什么',
    subtitle: 'AI 会先生成统一设计文档，再拆成“配置部分”和“自开发部分”。你确认之后，系统再继续生成完整的低代码应用。',
    placeholder: '比如：做一个设备巡检系统，巡检员录入巡检记录，主管审核并查看统计分析。',
    cta: '发送给 AI',
  },
  {
    key: 'code' as BuilderModeKey,
    label: 'Code',
    zh: '直接写码',
    eyebrow: 'AI Coding',
    title: '直接进入 IDE 编码',
    subtitle: '适合已有项目或明确的自开发任务。输入会进入真实 AI Coding 工作台，由当前工程的开发链路继续执行。',
    placeholder: '比如：给 CRM 加一个按筛选条件导出 Excel 的 Hook，字段按当前筛选。',
    cta: '进入 IDE',
  },
]

const currentBuilderMode = computed(() => (
  builderModes.find(item => item.key === builderMode.value) ?? builderModes[1]
))

const combinedSummary = computed(() => {
  const parts = [requirementDigest.value.trim(), generatedSummary.value.trim()].filter(Boolean)
  return parts.join('\n\n---\n\n')
})

const sceneLabelMap: Record<string, string> = {
  'component-pc': 'PC 组件扩展',
  'page-pc': 'PC 页面扩展',
  'component-mobile': '移动端组件',
  'page-mobile': '移动端页面',
  backend: '后端接口与服务',
}

const appName = computed(() => docResult.value?.app_info?.name?.trim() || '当前应用')
const roleCount = computed(() => docResult.value?.roles?.length || 0)
const tableCount = computed(() => docResult.value?.tables?.length || 0)
const flowCount = computed(() => docResult.value?.flows?.length || 0)
const hasExplicitCodingFocus = computed(() => Boolean(codingFocus.value.trim()))
const recommendedSceneLabel = computed(() => sceneLabelMap[recommendedSceneCategory.value] || '自定义扩展')

const builderScopeMetric = computed(() => {
  const parts = [
    roleCount.value ? `${roleCount.value} 个角色` : '',
    tableCount.value ? `${tableCount.value} 个模型` : '',
    flowCount.value ? `${flowCount.value} 条流程` : '',
  ].filter(Boolean)
  return parts.length ? parts.join(' / ') : '基础业务骨架'
})

const builderScopeSummary = computed(() => {
  const parts = [
    roleCount.value ? `已识别 ${roleCount.value} 个角色` : '',
    tableCount.value ? `${tableCount.value} 个核心业务对象` : '',
    flowCount.value ? `${flowCount.value} 条关键流程` : '',
  ].filter(Boolean)
  if (parts.length) {
    return `AI 先用平台搭建把 ${parts.join('、')} 的业务骨架拉起来。`
  }
  return 'AI 会先用平台搭建整理角色、数据结构、表单和基础权限，避免一开始就进入自由编码。'
})

const configHighlights = computed(() => {
  const items = [
    roleCount.value ? `角色与组织分工已进入配置设计` : '',
    tableCount.value ? `核心模型与字段结构会优先走低代码配置` : '',
    flowCount.value ? `关键流程会优先由平台流程能力承接` : '',
    '权限矩阵和基础页面会先由配置生成',
  ].filter(Boolean)
  return items.slice(0, 4)
})

const codingScopeMetric = computed(() => recommendedSceneLabel.value)

const codingScopeSummary = computed(() => {
  if (codingFocus.value.trim()) {
    return codingFocus.value.trim()
  }
  return `AI 判断这里主要是 ${recommendedSceneLabel.value} 的补充扩展，等业务骨架稳定后再进入更合适。`
})

const customDevHighlights = computed(() => {
  const items = [
    codingFocus.value.trim() ? '这部分会先整理成可执行的开发任务简报' : '',
    `推荐进入 ${recommendedSceneLabel.value} 场景继续生成`,
    '只处理平台配置承接不了的部分，避免过度自开发',
    '生成后的代码任务会继续挂在同一个项目上下文里',
  ].filter(Boolean)
  return items.slice(0, 4)
})

const executionPlan = computed(() => {
  const firstStep = {
    title: '先把业务骨架定下来',
    detail: `围绕 ${appName.value} 的角色、数据模型、表单和权限边界先生成可搭建骨架。`,
  }
  const secondStep = hasExplicitCodingFocus.value
    ? {
        title: '再处理必须自开发的部分',
        detail: `把 ${recommendedSceneLabel.value} 任务整理成可执行的 Coding Brief，避免用户自己判断技术路径。`,
      }
    : {
        title: '只在必要时再引入开发扩展',
        detail: '先验证平台配置是否足够，只有平台承接不了的部分才继续引入智能开发。',
      }
  const thirdStep = {
    title: '产物回到协作项目上下文',
    detail: '后续搭建结果、开发任务和发布动作都会继续落在同一个项目作用域里。',
  }
  return [firstStep, secondStep, thirdStep]
})

const primaryActionLabel = computed(() => (
  '确认设计文档并开始生成应用'
))

const primaryActionTitle = computed(() => (
  hasExplicitCodingFocus.value
    ? '确认后，AI 会先生成配置部分，再继续生成自开发部分'
    : '确认后，AI 会先完成配置生成，再判断是否需要继续自开发'
))

const primaryActionText = computed(() => (
  hasExplicitCodingFocus.value
    ? '这一步相当于确认统一设计文档。AI 会先用低代码配置生成主体应用，再把自开发部分交给智能开发继续补齐。'
    : '这一步会先启动配置生成。若平台配置不足以完整交付，AI 会继续拆出需要补充的自开发任务。'
))

const showCodingAction = computed(() => Boolean(codingBrief.value.trim()))

const resultStatusLabel = computed(() => {
  if (isGenerating.value) return 'AI 接管中'
  if (docResult.value) return '已给出方案'
  if (errorMessage.value) return '生成失败'
  return '等待接管'
})

const resultTitle = computed(() => {
  if (docResult.value?.app_info?.name) {
    return `${docResult.value.app_info.name} 的统一设计文档`
  }
  return '等待 AI 先理解这次任务'
})

function setStatus(next: StatusItem[]) {
  statusItems.value = next
}

function updateStatus(index: number, patch: Partial<StatusItem>) {
  const cloned = [...statusItems.value]
  const current = cloned[index]
  if (!current) return
  cloned[index] = { ...current, ...patch }
  statusItems.value = cloned
}

function resetOutputs() {
  errorMessage.value = ''
  requirementDigest.value = ''
  generatedSummary.value = ''
  docResult.value = null
  builderMarkdown.value = ''
  codingBrief.value = ''
  recommendedSceneCategory.value = 'page-pc'
  activeTab.value = 'structure'
  detailsExpanded.value = false
}

function toFriendlyFallbackMessage(raw: string | null | undefined) {
  const text = String(raw || '').toLowerCase()
  if (!text) return '当前分析模型暂不可用，已切换为基础分析模式。'
  if (text.includes('401') || text.includes('unauthorized') || text.includes('authorized_error')) {
    return '当前分析模型暂不可用，已切换为基础分析模式。'
  }
  if (text.includes('timeout')) {
    return '当前分析模型响应超时，已切换为基础分析模式。'
  }
  return '当前分析模型暂不可用，已切换为基础分析模式。'
}

function toFriendlyErrorMessage(raw: string | null | undefined) {
  const text = String(raw || '').toLowerCase()
  if (!text) return '统一方案生成失败，请稍后重试。'
  if (text.includes('401') || text.includes('unauthorized') || text.includes('authorized_error')) {
    return '当前分析模型不可用，请先检查模型配置。'
  }
  if (text.includes('timeout')) {
    return '当前分析模型响应超时，请稍后重试。'
  }
  return String(raw || '统一方案生成失败，请稍后重试。')
}

function resetPanel() {
  businessInput.value = ''
  codingFocus.value = ''
  advancedOpen.value = false
  clearAttachedFile()
  resetOutputs()
  setStatus([
    { label: '等待输入业务需求或上传文档', state: 'idle' },
    { label: 'AI 会先统一理解需求', state: 'idle' },
    { label: '随后拆成配置部分与自开发部分', state: 'idle' },
  ])
}

function setBuilderMode(mode: BuilderModeKey) {
  builderMode.value = mode
  if (mode !== 'cowork') {
    advancedOpen.value = false
  }
}

function clearAttachedFile() {
  attachedFile.value = null
  if (fileInputRef.value) {
    fileInputRef.value.value = ''
  }
}

function handleFileSelect(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  attachedFile.value = file
}

function formatFileSize(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

function applyDefaultModelSelection() {
  selectedBuilderModelId.value =
    builderModelOptions.value.find(option => option.is_default)?.id
    ?? builderModelOptions.value[0]?.id
    ?? null
}

async function loadBuilderModels() {
  builderModelLoading.value = true
  try {
    builderModelOptions.value = await llmConfigApi.listOptions('builder')
    applyDefaultModelSelection()
  } catch {
    builderModelOptions.value = []
    selectedBuilderModelId.value = null
  } finally {
    builderModelLoading.value = false
  }
}

async function loadProjects() {
  try {
    const list = await projectsApi.list()
    projects.value = list.filter(project => project.can_view !== false)
    const lastProjectId = Number(localStorage.getItem('coding_last_project_id') || '')
    if (lastProjectId && projects.value.some(project => project.id === lastProjectId)) {
      selectedProjectId.value = lastProjectId
    }
  } catch {
    projects.value = []
  }
}

async function generateUnifiedPlan() {
  if (!businessInput.value.trim() && !attachedFile.value) {
    ElMessage.warning('请先输入业务需求或上传需求文档')
    return
  }

  resetOutputs()
  isGenerating.value = true
  setStatus([
    { label: 'AI 已接管这次任务', state: 'running', detail: '正在建立统一上下文' },
    { label: '理解需求并生成统一设计文档', state: 'idle' },
    { label: '拆成配置部分与自开发部分', state: 'idle' },
    { label: '等待确认后开始生成应用', state: 'idle' },
  ])

  try {
    updateStatus(1, { state: 'running', detail: 'AI 正在理解业务需求并整理统一设计文档' })
    updateStatus(2, { state: 'running', detail: 'AI 正在拆出配置部分和自开发部分' })
    updateStatus(3, { state: 'running', detail: '正在整理确认后要执行的生成动作' })

    const result = await requirementsApi.unifiedPlan({
      business_input: businessInput.value,
      coding_focus: codingFocus.value,
      selected_llm_config_id: selectedBuilderModelId.value ?? undefined,
      project_id: selectedProjectId.value ?? undefined,
      file: attachedFile.value,
    })
    updateStatus(0, {
      state: 'done',
      detail: result.project_id
        ? `会话 #${result.session_id} 已创建，并绑定到项目上下文`
        : `会话 #${result.session_id} 已创建`,
    })

    requirementDigest.value = result.summary || ''
    generatedSummary.value = ''
    docResult.value = result.doc_result
    activeTab.value = 'structure'
    builderMarkdown.value = result.builder_markdown
    codingBrief.value = result.coding_brief
    recommendedSceneCategory.value = result.recommended_scene || 'page-pc'

    const fallbackMessage = toFriendlyFallbackMessage(result.fallback_reason)
    updateStatus(1, {
      state: result.used_fallback ? 'error' : 'done',
      detail: result.used_fallback ? fallbackMessage : '统一设计文档已经生成',
    })
    updateStatus(2, {
      state: 'done',
      detail: result.used_fallback ? '已切换到基础分析模式，先生成基础设计文档' : '配置部分与自开发部分已拆分完成',
    })
    updateStatus(3, {
      state: 'done',
      detail: '你确认设计文档后，AI 就会开始生成完整应用',
    })

    if (result.used_fallback) {
      errorMessage.value = fallbackMessage
      ElMessage.warning('当前分析模型暂不可用，已切换为基础分析模式')
      return
    }

    ElMessage.success('统一设计文档已生成')
  } catch (error: any) {
    const rawMessage = error?.response?.data?.detail || error?.message || '统一方案生成失败'
    const message = toFriendlyErrorMessage(rawMessage)
    errorMessage.value = message
    statusItems.value = statusItems.value.map(item => (
      item.state === 'running' ? { ...item, state: 'error', detail: message } : item
    ))
    ElMessage.error(message)
  } finally {
    isGenerating.value = false
  }
}

async function submitToChat() {
  const prompt = businessInput.value.trim()
  previewStore.pendingBuilderModelId = selectedBuilderModelId.value
  if (attachedFile.value) {
    previewStore.pendingFile = attachedFile.value
  }
  await router.push({
    path: '/chat',
    query: {
      ...(prompt ? { prompt } : {}),
      ...(selectedProjectId.value ? { project_id: String(selectedProjectId.value) } : {}),
    },
  })
}

async function submitToCode() {
  const prompt = businessInput.value.trim()
  const payload: PendingCodingPayload = {
    message: prompt || codingFocus.value.trim() || '从首页进入 AI Coding，请继续补充开发任务。',
    projectId: selectedProjectId.value,
    sceneCategory: recommendedSceneCategory.value,
  }
  sessionStorage.setItem(PENDING_CODING_KEY, JSON.stringify(payload))
  if (selectedProjectId.value) {
    localStorage.setItem('coding_last_project_id', String(selectedProjectId.value))
  }
  await router.push({
    path: '/coding',
    query: {
      from_ai_builder: '1',
      ...(selectedProjectId.value ? { project_id: String(selectedProjectId.value) } : {}),
    },
  })
}

async function handleModeSubmit() {
  if (builderMode.value === 'chat') {
    await submitToChat()
    return
  }
  if (builderMode.value === 'code') {
    await submitToCode()
    return
  }
  await generateUnifiedPlan()
}

function triggerDownload(content: string, filename: string) {
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

function downloadBuilderMarkdown() {
  if (!docResult.value || !builderMarkdown.value) return
  triggerDownload(builderMarkdown.value, buildBuilderMarkdownFilename(docResult.value))
}

function downloadCodingBrief() {
  if (!docResult.value || !codingBrief.value) return
  triggerDownload(codingBrief.value, buildCodingBriefFilename(docResult.value))
}

async function dispatchToBuilder() {
  if (!docResult.value || !builderMarkdown.value) return
  previewStore.pendingBuilderModelId = selectedBuilderModelId.value
  previewStore.pendingMarkdown = {
    filename: buildBuilderMarkdownFilename(docResult.value),
    content: builderMarkdown.value,
  }
  await router.push({
    path: '/chat',
    query: selectedProjectId.value ? { project_id: String(selectedProjectId.value) } : undefined,
  })
}

async function dispatchToCoding() {
  if (!docResult.value || !codingBrief.value) return
  const payload: PendingCodingPayload = {
    message: codingBrief.value,
    projectId: selectedProjectId.value,
    sceneCategory: recommendedSceneCategory.value,
  }
  sessionStorage.setItem(PENDING_CODING_KEY, JSON.stringify(payload))
  if (selectedProjectId.value) {
    localStorage.setItem('coding_last_project_id', String(selectedProjectId.value))
  }
  await router.push({
    path: '/coding',
    query: {
      from_ai_builder: '1',
      ...(selectedProjectId.value ? { project_id: String(selectedProjectId.value) } : {}),
    },
  })
}

async function handlePrimaryAction() {
  if (docResult.value && codingBrief.value) {
    const payload: PendingCodingPayload = {
      message: codingBrief.value,
      projectId: selectedProjectId.value,
      sceneCategory: recommendedSceneCategory.value,
    }
    sessionStorage.setItem(PENDING_CODING_KEY, JSON.stringify(payload))
  }
  await dispatchToBuilder()
}

onMounted(async () => {
  await Promise.all([
    loadBuilderModels(),
    loadProjects(),
  ])
})
</script>

<style scoped>
.ai-builder-panel {
  max-width: 1320px;
  margin: 0 auto;
  padding: 0;
  display: grid;
  grid-template-columns: minmax(0, 1.18fr) minmax(320px, 0.92fr);
  gap: 14px;
  align-items: stretch;
}

.builder-studio-card,
.builder-result-card {
  background: #fff;
  border: 1px solid rgba(15, 23, 42, 0.10);
  border-radius: 8px;
  box-shadow: 0 18px 38px rgba(15, 23, 42, 0.06);
}

.builder-studio-card {
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 18px;
  background: #fff;
}

.entry-mode-switcher {
  align-self: flex-start;
  display: inline-flex;
  gap: 3px;
  padding: 4px;
  border-radius: 8px;
  border: 1px solid rgba(15, 23, 42, 0.10);
  background: #f8fafc;
}

.entry-mode-btn {
  min-height: 38px;
  min-width: 122px;
  padding: 0 12px;
  border-radius: 6px;
  border: 1px solid transparent;
  background: transparent;
  color: #64748b;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-size: 12px;
  transition: background 0.18s ease, color 0.18s ease, border-color 0.18s ease;
}

.entry-mode-btn:hover {
  background: #fff;
  color: #111827;
}

.entry-mode-btn.active {
  background: #fff;
  border-color: rgba(15, 23, 42, 0.10);
  color: #111827;
  font-weight: 800;
}

.entry-mode-label {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
}

.entry-mode-zh {
  color: currentColor;
  font-size: 11px;
  opacity: 0.72;
  white-space: nowrap;
}

.builder-result-card {
  padding: 22px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: 0;
}

.panel-eyebrow {
  display: inline-flex;
  align-self: flex-start;
  padding: 5px 10px;
  border-radius: 6px;
  background: #f1f5f9;
  color: #334155;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0;
}

.panel-title-row {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
}

.panel-title-copy {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.panel-title {
  margin: 0;
  font-size: 24px;
  line-height: 1.18;
  color: #111827;
  letter-spacing: 0;
}

.panel-subtitle {
  margin: 10px 0 0;
  max-width: 700px;
  font-size: 13px;
  line-height: 1.7;
  color: #475569;
}

.panel-flow-badge {
  flex-shrink: 0;
  padding: 10px 12px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.9);
  color: #3f5ca8;
  font-size: 11px;
  font-weight: 700;
  box-shadow: inset 0 0 0 1px rgba(63, 92, 168, 0.08);
}

.panel-commitments {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.commitment-pill {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 54px;
  padding: 0 14px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.84);
  box-shadow: inset 0 0 0 1px rgba(83, 74, 183, 0.08);
  color: #3a356f;
  font-size: 12px;
  font-weight: 700;
  line-height: 1.5;
}

.commitment-index {
  width: 26px;
  height: 26px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: rgba(81, 71, 189, 0.1);
  color: #5147bd;
  font-size: 11px;
  font-weight: 800;
  flex-shrink: 0;
}

.panel-controls {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.conversation-shell {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.ai-prompt-card {
  display: flex;
  gap: 14px;
  align-items: flex-start;
  padding: 18px;
  border-radius: 8px;
  background: #f8fafc;
  border: 1px solid rgba(15, 23, 42, 0.08);
}

.ai-prompt-avatar {
  width: 38px;
  height: 38px;
  border-radius: 14px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, rgba(81, 71, 189, 0.14), rgba(111, 99, 239, 0.18));
  color: #5147bd;
  font-size: 12px;
  font-weight: 800;
  flex-shrink: 0;
}

.ai-prompt-copy {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.ai-prompt-title {
  font-size: 15px;
  line-height: 1.5;
  font-weight: 800;
  color: #26215c;
}

.ai-prompt-text {
  font-size: 12px;
  line-height: 1.75;
  color: #656094;
}

.composer-card,
.advanced-panel {
  padding: 18px;
  border-radius: 8px;
  background: #f8fafc;
  border: 1px solid rgba(15, 23, 42, 0.08);
}

.composer-card {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.advanced-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.advanced-panel-head {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.advanced-panel-title {
  font-size: 13px;
  font-weight: 800;
  color: #111827;
}

.advanced-panel-subtitle {
  font-size: 12px;
  line-height: 1.7;
  color: #64748b;
}

.composer-context-row {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.field-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.field-label,
.input-label {
  font-size: 12px;
  font-weight: 700;
  color: #334155;
}

.field-select {
  width: 100%;
}

.field-select :deep(.el-select__wrapper) {
  min-height: 42px;
  border-radius: 8px;
  background: #fff;
  box-shadow: inset 0 0 0 1px rgba(15, 23, 42, 0.10);
}

.builder-model-option-row {
  display: flex;
  flex-direction: column;
  line-height: 1.35;
}

.builder-model-option-name {
  font-size: 12px;
  font-weight: 600;
  color: #111827;
}

.builder-model-option-meta {
  font-size: 10px;
  color: #64748b;
}

.builder-input-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.input-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.panel-textarea {
  width: 100%;
  min-height: 156px;
  padding: 16px;
  border: 1px solid rgba(15, 23, 42, 0.10);
  border-radius: 8px;
  background: #fff;
  color: #111827;
  font-size: 13px;
  line-height: 1.75;
  resize: vertical;
  outline: none;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.panel-textarea:focus {
  border-color: rgba(17, 24, 39, 0.34);
  box-shadow: 0 0 0 4px rgba(15, 23, 42, 0.06);
}

.panel-textarea-secondary {
  background: #fff;
}

.composer-textarea {
  min-height: 132px;
}

.composer-actions-row {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.composer-footer-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}

.upload-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.upload-trigger {
  border: none;
  border-radius: 8px;
  padding: 0 16px;
  min-height: 46px;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  background: #eef2f7;
  color: #111827;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}

.upload-trigger-icon {
  width: 22px;
  height: 22px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: #fff;
}

.upload-hint {
  font-size: 12px;
  color: #64748b;
  line-height: 1.6;
}

.secondary-inline-action {
  border: none;
  min-height: 42px;
  padding: 0 14px;
  border-radius: 8px;
  background: #eef2f7;
  color: #111827;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}

.attached-file-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border-radius: 8px;
  background: #fff;
  border: 1px solid rgba(15, 23, 42, 0.10);
}

.attached-file-name {
  font-size: 13px;
  font-weight: 700;
  color: #111827;
}

.attached-file-meta {
  margin-top: 4px;
  font-size: 11px;
  color: #64748b;
}

.attached-file-remove {
  border: none;
  background: transparent;
  color: #334155;
  cursor: pointer;
  font-size: 12px;
  font-weight: 700;
}

.primary-action,
.secondary-action,
.dispatch-btn {
  border: none;
  border-radius: 8px;
  min-height: 50px;
  padding: 0 18px;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  transition: transform 180ms ease, opacity 180ms ease, box-shadow 180ms ease;
}

.primary-action,
.dispatch-btn {
  background: #111827;
  color: #fff;
  box-shadow: none;
}

.primary-action:hover,
.dispatch-btn:hover {
  transform: translateY(-1px);
}

.primary-action:disabled,
.secondary-action:disabled,
.dispatch-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

.secondary-action {
  background: #fff;
  color: #334155;
  border: 1px solid rgba(15, 23, 42, 0.10);
}

.compact-action {
  min-height: 42px;
  padding: 0 16px;
  font-size: 13px;
}

.pipeline-strip {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.pipeline-pill {
  display: inline-flex;
  align-items: center;
  min-height: 34px;
  padding: 0 12px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.82);
  color: #615ba9;
  font-size: 11px;
  font-weight: 700;
  box-shadow: inset 0 0 0 1px rgba(83, 74, 183, 0.08);
}

.result-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
}

.result-title {
  margin: 8px 0 0;
  font-size: 22px;
  line-height: 1.24;
  color: #26215c;
}

.result-status-chip {
  min-height: 34px;
  padding: 0 14px;
  border-radius: 999px;
  background: rgba(245, 247, 255, 0.92);
  color: #5e58a9;
  font-size: 12px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
}

.result-status-chip.running {
  background: rgba(81, 71, 189, 0.1);
  color: #5147bd;
}

.result-status-chip.ready {
  background: rgba(28, 164, 101, 0.12);
  color: #15714a;
}

.status-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.status-item {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 12px 14px;
  border-radius: 16px;
  background: rgba(245, 247, 255, 0.82);
  border: 1px solid rgba(83, 74, 183, 0.06);
}

.status-item.running {
  background: rgba(81, 71, 189, 0.08);
}

.status-item.done {
  background: rgba(225, 245, 238, 0.72);
}

.status-item.error {
  background: rgba(255, 239, 239, 0.82);
}

.status-dot {
  width: 10px;
  height: 10px;
  margin-top: 4px;
  border-radius: 999px;
  background: #b4afde;
  flex-shrink: 0;
}

.status-item.running .status-dot {
  background: #5147bd;
}

.status-item.done .status-dot {
  background: #1a8f5b;
}

.status-item.error .status-dot {
  background: #d44c4c;
}

.status-copy {
  min-width: 0;
}

.status-label {
  font-size: 13px;
  font-weight: 700;
  color: #2a255f;
}

.status-detail {
  margin-top: 4px;
  font-size: 11px;
  line-height: 1.6;
  color: #726da8;
}

.error-banner {
  padding: 12px 14px;
  border-radius: 16px;
  background: rgba(255, 239, 239, 0.84);
  color: #b33f3f;
  font-size: 12px;
  line-height: 1.7;
}

.error-banner.subtle {
  background: rgba(255, 248, 235, 0.9);
  color: #9b6b10;
}

.summary-card {
  padding: 16px;
  border-radius: 18px;
  background: linear-gradient(180deg, rgba(248, 249, 255, 0.96), rgba(255, 255, 255, 0.94));
  border: 1px solid rgba(83, 74, 183, 0.08);
}

.design-doc-card {
  padding: 18px;
  border-radius: 20px;
  background: rgba(250, 250, 255, 0.94);
  border: 1px solid rgba(83, 74, 183, 0.08);
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.design-doc-title {
  font-size: 19px;
  line-height: 1.4;
  font-weight: 800;
  color: #26215c;
}

.design-doc-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.design-section-card {
  padding: 16px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.82);
  border: 1px solid rgba(83, 74, 183, 0.08);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.design-section-card-accent {
  background: linear-gradient(145deg, rgba(81, 71, 189, 0.08), rgba(255, 255, 255, 0.92));
}

.design-section-label {
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: #6a66a3;
}

.design-section-title {
  font-size: 18px;
  line-height: 1.35;
  font-weight: 800;
  color: #26215c;
}

.design-section-text {
  font-size: 12px;
  line-height: 1.75;
  color: #605b92;
}

.design-section-points {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.design-point {
  padding: 10px 12px;
  border-radius: 14px;
  background: rgba(245, 247, 255, 0.88);
  color: #484275;
  font-size: 12px;
  line-height: 1.6;
}

.decision-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.decision-card {
  padding: 16px;
  border-radius: 18px;
  background: rgba(247, 248, 255, 0.92);
  border: 1px solid rgba(83, 74, 183, 0.08);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.decision-card-primary {
  background: linear-gradient(145deg, rgba(81, 71, 189, 0.1), rgba(255, 255, 255, 0.96));
  border-color: rgba(81, 71, 189, 0.12);
}

.decision-label,
.section-kicker {
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: #6a66a3;
}

.decision-title {
  font-size: 18px;
  line-height: 1.35;
  font-weight: 800;
  color: #26215c;
}

.decision-metric {
  font-size: 16px;
  line-height: 1.35;
  font-weight: 800;
  color: #2d3f84;
}

.decision-text {
  font-size: 12px;
  line-height: 1.7;
  color: #605b92;
}

.plan-card,
.cta-card,
.details-panel {
  padding: 18px;
  border-radius: 20px;
  background: rgba(250, 250, 255, 0.94);
  border: 1px solid rgba(83, 74, 183, 0.08);
}

.plan-list {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.plan-step {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.plan-step-index {
  width: 30px;
  height: 30px;
  border-radius: 999px;
  background: rgba(81, 71, 189, 0.08);
  color: #5147bd;
  font-size: 12px;
  font-weight: 800;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.plan-step-copy {
  min-width: 0;
}

.plan-step-title {
  font-size: 13px;
  font-weight: 800;
  color: #2a255f;
}

.plan-step-text {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.7;
  color: #6c679f;
}

.cta-card {
  display: flex;
  flex-direction: column;
  gap: 14px;
  background: linear-gradient(180deg, rgba(245, 247, 255, 0.96), rgba(255, 255, 255, 0.96));
}

.cta-copy {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.cta-title {
  font-size: 19px;
  line-height: 1.35;
  font-weight: 800;
  color: #26215c;
}

.cta-text {
  font-size: 13px;
  line-height: 1.75;
  color: #625d98;
}

.details-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.details-block {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.summary-title {
  margin-bottom: 10px;
  font-size: 13px;
  font-weight: 700;
  color: #5147bd;
}

.summary-body {
  color: #312b6b;
  font-size: 13px;
  line-height: 1.75;
}

.result-tabs {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.result-tab {
  border: none;
  border-radius: 14px;
  min-height: 38px;
  padding: 0 14px;
  background: rgba(245, 247, 255, 0.86);
  color: #5f5aa4;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}

.result-tab.active {
  background: rgba(81, 71, 189, 0.12);
  color: #5147bd;
}

.result-surface {
  min-height: 0;
  max-height: 580px;
  overflow: auto;
  border-radius: 18px;
  border: 1px solid rgba(83, 74, 183, 0.08);
  background: #f7f8ff;
  padding: 16px;
}

.structured-surface {
  padding: 10px;
}

.result-pre {
  margin: 0;
  color: #2a255f;
  font-size: 12px;
  line-height: 1.78;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: "SFMono-Regular", "Menlo", "Consolas", monospace;
}

.dispatch-row,
.download-row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.dispatch-btn.ghost {
  background: rgba(255, 255, 255, 0.9);
  color: #4f46b5;
  border: 1px solid rgba(83, 74, 183, 0.12);
  box-shadow: none;
}

.dispatch-btn.coding {
  background: linear-gradient(135deg, #2d7c72 0%, #43a291 100%);
}

.download-link {
  border: none;
  background: transparent;
  color: #5e58a9;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  padding: 0;
}

.empty-state {
  min-height: 320px;
  border-radius: 18px;
  border: 1px dashed rgba(83, 74, 183, 0.16);
  background: rgba(248, 249, 255, 0.68);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 10px;
  text-align: center;
  padding: 28px;
}

.empty-state-title {
  font-size: 18px;
  font-weight: 700;
  color: #2a255f;
}

.empty-state-text {
  font-size: 12px;
  line-height: 1.75;
  color: #736da9;
}

@media (max-width: 1100px) {
  .ai-builder-panel,
  .builder-input-grid,
  .panel-controls,
  .panel-commitments,
  .decision-grid,
  .composer-context-row,
  .design-doc-grid {
    grid-template-columns: 1fr;
  }

  .panel-title-row,
  .result-header {
    flex-direction: column;
  }
}

@media (max-width: 860px) {
  .entry-mode-switcher {
    width: 100%;
  }

  .entry-mode-btn {
    flex: 1;
    min-width: 0;
    justify-content: center;
  }

  .entry-mode-zh {
    display: none;
  }

  .commitment-pill {
    min-height: auto;
    padding: 12px 14px;
  }

  .composer-card,
  .advanced-panel,
  .plan-card,
  .cta-card,
  .details-panel,
  .design-doc-card {
    padding: 16px;
  }

  .ai-prompt-card {
    padding: 16px;
  }

  .composer-actions-row {
    align-items: flex-start;
  }

  .composer-footer-actions {
    width: 100%;
    justify-content: flex-start;
  }
}
</style>
