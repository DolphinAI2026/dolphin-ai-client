<template>
  <WorkbenchShell>
    <main class="main">
      <div class="bg"></div>
      <header class="landing-topbar">
        <div class="landing-breadcrumbs">
          <span>aPaaS Builder</span>
          <span>/</span>
          <strong>新建</strong>
        </div>
        <div class="landing-topbar-spacer"></div>
        <button class="landing-command" type="button" @click="openCommandPalette">
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <circle cx="7" cy="7" r="4.2" stroke="currentColor" stroke-width="1.4" />
            <path d="m10.2 10.2 2.8 2.8" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
          </svg>
          <span>搜索应用、模型、对话...</span>
          <kbd>⌘K</kbd>
        </button>
        <div v-if="userStore.isTenantAdmin" class="landing-admin-actions">
          <button type="button" @click="navigateTo('/tenant-users')">成员管理</button>
          <button type="button" @click="navigateTo('/platform-envs?tab=envs')">平台环境</button>
        </div>
      </header>
      <div class="landing" :style="landingModeVars">
        <div class="landing-bg"></div>

        <div class="brand-mark">
          <div class="brand-glyph">{{ landingGlyph }}</div>
          <div class="brand-eyebrow">{{ currentLandingMode.eyebrow }}</div>
        </div>

        <section class="brand-copy">
          <h1 class="brand-title">
            <span>{{ currentLandingMode.tagline }}</span>
            <em>{{ landingTitleSuffix }}</em>
          </h1>
          <p class="brand-sub">{{ currentLandingMode.desc }}</p>
        </section>

        <div class="mode-switcher" aria-label="AI 入口模式">
          <button
            v-for="mode in landingModeList"
            :key="mode.key"
            type="button"
            class="mode-tab"
            :class="{ active: landingMode === mode.key }"
            :aria-pressed="landingMode === mode.key"
            @click="landingMode = mode.key; focusLandingInput()"
          >
            <span class="mode-tab-icon">{{ mode.icon }}</span>
            <span class="mode-tab-label">{{ mode.label }}</span>
            <span class="mode-tab-zh">{{ mode.zh }}</span>
            <span v-if="landingMode === mode.key" class="mode-tab-dot"></span>
          </button>
        </div>

        <section class="composer">
          <div class="composer-shell ai-surface">
            <div class="composer-mode-bar">
              <span class="composer-mode-label">
                <span>{{ currentLandingMode.icon }}</span>
                {{ currentLandingMode.label }} · {{ currentLandingMode.zh }}
              </span>
            </div>

            <div class="composer-body"
                 :class="{ 'is-dragover': landingMode === 'chat' && isCoworkDragover }"
                 @dragenter.prevent="landingMode === 'chat' && (isCoworkDragover = true)"
                 @dragover.prevent="landingMode === 'chat' && (isCoworkDragover = true)"
                 @dragleave.prevent="isCoworkDragover = false"
                 @drop.prevent="landingMode === 'chat' && handleCoworkDrop($event)">
              <div v-if="landingMode === 'chat' && pendingChatFiles.length" class="composer-attach-list">
                <span v-for="(f, idx) in pendingChatFiles" :key="idx" class="attach-chip">
                  <span class="attach-chip-icon">{{ /\.(png|jpe?g|gif|webp)$/i.test(f.name) ? '🖼️' : '📄' }}</span>
                  <span class="attach-chip-name">{{ f.name }}</span>
                  <button class="attach-chip-x" type="button" @click="pendingChatFiles.splice(idx, 1)" aria-label="移除">×</button>
                </span>
              </div>
              <textarea
                ref="landingTextareaRef"
                v-model="landingInput"
                class="composer-input"
                :placeholder="currentLandingMode.placeholder"
                @keydown="handleLandingKeydown"
              ></textarea>
              <!-- 2026-05-17: 砍掉跟 desc 重复的 drop-hint，材料类型已在 brand-sub 说明 -->
            </div>

            <div class="composer-toolbar">
              <template v-if="landingMode === 'chat'">
                <button class="chip" type="button" @click="chatFilesInputRef?.click()">📎 附加附件</button>
                <button class="chip" type="button" @click="prdInputRef?.click()">📂 上传文档</button>
                <button class="chip" type="button" @click="showImportDialog = true">引用项目</button>
                <button class="chip template-chip" type="button" @click="openTemplateFromComposer">文档模板</button>
              </template>
              <button v-else-if="landingMode === 'code'" class="chip" type="button" @click="navigateTo('/coding?type=apaas-custom-dev')">选择应用</button>
              <button v-else-if="landingMode === 'online'" class="chip" type="button" @click="navigateTo('/vibe-coding/new')">导入 Git 仓库</button>

              <div class="toolbar-spacer"></div>

              <button class="landing-submit" type="button" :disabled="!landingInput.trim() && !(landingMode === 'chat' && pendingChatFiles.length)" @click="submitLanding">
                <span>↗</span>
                {{ currentLandingMode.cta }}
                <span class="submit-kbd">⌘↵</span>
              </button>
            </div>
          </div>
        </section>

        <input ref="prdInputRef" type="file" multiple accept=".md,.markdown,.pdf,.doc,.docx,.txt,.xlsx,.xls,.csv,image/*" hidden @change="handleLandingDocUpload" />
        <input ref="chatFilesInputRef" type="file" multiple hidden @change="handleChatFilesSelected" />
        <div v-if="landingNotice" class="landing-toast">{{ landingNotice }}</div>
      </div>
    </main>
  </WorkbenchShell>

  <ImportAppDialog v-model="showImportDialog" @imported="loadApps" />

  <el-dialog v-model="profileDialogVisible" title="我的信息" width="460px" destroy-on-close>
    <div class="profile-block">
      <div class="profile-hero">
        <div class="profile-avatar">{{ userInitial }}</div>
        <div class="profile-identity">
          <div class="profile-name">{{ userDisplayName }}</div>
          <div class="profile-subtitle">aPaaS Builder AI 用户</div>
        </div>
      </div>
      <div class="profile-row">
        <span class="profile-label">账号</span>
        <span class="profile-value">{{ userStore.user?.username || '-' }}</span>
      </div>
      <div class="profile-row">
        <span class="profile-label">密码</span>
        <span class="profile-value">••••••••</span>
      </div>
    </div>

    <div class="password-form">
      <div class="profile-title">修改密码</div>
      <el-input v-model="passwordForm.oldPassword" type="password" show-password placeholder="当前密码" class="pwd-input" />
      <el-input v-model="passwordForm.newPassword" type="password" show-password placeholder="新密码（至少6位）" class="pwd-input" />
      <el-input v-model="passwordForm.confirmPassword" type="password" show-password placeholder="确认新密码" class="pwd-input" />
    </div>

    <template #footer>
      <el-button @click="profileDialogVisible = false">关闭</el-button>
      <el-button type="primary" :loading="changingPassword" @click="submitChangePassword">保存修改</el-button>
    </template>
  </el-dialog>

  <el-dialog
    v-model="templatePreviewVisible"
    :title="templatePreview?.name || '模板预览'"
    width="1120px"
    class="template-preview-dialog"
    destroy-on-close
  >
    <div class="template-preview-head">
      <div class="template-preview-meta">
        <span>{{ templatePreview?.filename || '-' }}</span>
        <span>{{ templatePreview?.category || '通用模板' }}</span>
      </div>
      <div class="template-preview-desc">{{ templatePreview?.description || '按此模板补齐章节后即可上传解析。' }}</div>
    </div>

    <div v-if="templatePreviewLoading" class="template-preview-empty">
      正在加载模板内容...
    </div>
    <div v-else-if="templatePreviewParsedDoc" class="template-preview-structured structured-doc-host">
      <StructuredDocRenderer :doc-result="templatePreviewParsedDoc" />
    </div>
    <pre v-else class="template-preview-body">{{ templatePreview?.content || '' }}</pre>

    <template #footer>
      <el-button @click="templatePreviewVisible = false">关闭</el-button>
      <el-button type="primary" :disabled="!templatePreview" @click="templatePreview && downloadTemplate(templatePreview)">
        下载模板
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { handleError } from '@/utils/errorHandler'
import request from '@/utils/request'
import { usePreviewStore } from '@/stores/preview'
import { useUserStore } from '@/stores/user'
import { conversationApi, type ConversationWithApp } from '@/api/conversation'
import { applicationApi } from '@/api/application'
import { llmConfigApi, type BuilderModelOption } from '@/api/llmConfig'
import type { AppItem } from '@/components/AppSidebar.vue'
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import ImportAppDialog from '@/components/ImportAppDialog.vue'
import StructuredDocRenderer from '@/components/StructuredDocRenderer.vue'
import { standardDocMdToStructuredDoc } from '@/utils/structuredDoc'

const router = useRouter()
const previewStore = usePreviewStore()
const userStore = useUserStore()

interface TemplateFile {
  code: string
  name: string
  icon?: string
  description?: string
  category?: string
  filename: string
  updated_at?: string
}

interface TemplateDetail extends TemplateFile {
  content: string
}

// 2026-05-17: 合并 chat / cowork — AIChatPage 底层早已合并，Landing 表层之前
// 分两个 mode 是历史遗留 UI。chat 是文字主、cowork 是文件主，agent 看附件情况
// 自动切流程，统一入口 UX 更清晰。
type LandingModeKey = 'chat' | 'code' | 'online'

interface LandingModeConfig {
  key: LandingModeKey
  label: string
  zh: string
  tagline: string
  titleSuffix: string
  eyebrow: string
  desc: string
  color: string
  colorSoft: string
  colorInk: string
  icon: string
  placeholder: string
  cta: string
}

const PENDING_CODING_KEY = 'ai_builder_pending_coding'
const PENDING_VIBE_PROMPT_KEY = 'vibe_coding_pending_prompt'

const landingModeList: LandingModeConfig[] = [
  {
    key: 'chat',
    label: 'AI 对话',
    zh: '需求梳理 / 文档整合',
    tagline: '把想法 / 材料给 AI',
    titleSuffix: '整理成设计文档，直进 Builder',
    eyebrow: 'APAAS CHAT AI · DESIGN + BUILD',
    desc: '支持 PDF / Word / Excel / 截图 / .md，单 .md 直接走 Builder 秒级生成。',
    color: 'oklch(60% 0.16 220)',
    colorSoft: 'oklch(96% 0.03 220)',
    colorInk: 'oklch(42% 0.15 220)',
    icon: '💬',
    placeholder: '描述你想做的应用，或把材料拖进来…',
    cta: '开始聊需求',
  },
  {
    key: 'code',
    label: '睿鲸AI',
    zh: 'Coding',
    tagline: 'AI 帮你做二开',
    titleSuffix: '把需求变成平台组件、页面和接口',
    eyebrow: 'RUIJING AI CODING',
    desc: '面向得帆低代码扩展：描述组件 / 页面 / 接口，AI 创建工作区辅助构建。',
    color: 'oklch(62% 0.15 185)',
    colorSoft: 'oklch(96% 0.03 185)',
    colorInk: 'oklch(42% 0.14 185)',
    icon: '{}',
    placeholder: '描述你想开发的内容。例如：做一个头像上传组件，支持裁剪、预览、上传失败重试，并输出可接入表单的组件。',
    cta: '进入睿鲸AI Coding',
  },
  {
    key: 'online',
    label: 'Vibe Coding',
    zh: '全代码',
    tagline: 'AI 帮你改全代码',
    titleSuffix: '导入 Git 仓库，在云工作区里开发',
    eyebrow: 'VIBE CODING · CLOUD WORKSPACE',
    desc: '导入 GitHub / GitLab 项目，AI 在沙箱里改代码、跑测试、开 PR。',
    color: 'oklch(60% 0.18 292)',
    colorSoft: 'oklch(96% 0.035 292)',
    colorInk: 'oklch(45% 0.18 292)',
    icon: '</>',
    placeholder: '描述你要处理的代码任务。例如：导入 supplier-portal 仓库，把首页改成供应商风险看板，跑完测试后提交一个 PR。',
    cta: '进入 Vibe Coding',
  },
]
const fallbackLandingMode: LandingModeConfig = landingModeList[0]!

const recentSessions = ref<ConversationWithApp[]>([])
const recentApps = ref<AppItem[]>([])
const generatedModules = ref(0)
const totalAppsCount = ref(0)
const totalConversationCount = ref(0)
const profileDialogVisible = ref(false)
const showImportDialog = ref(false)
const changingPassword = ref(false)
const passwordForm = ref({ oldPassword: '', newPassword: '', confirmPassword: '' })
const templateFiles = ref<TemplateFile[]>([])
const templatePreviewVisible = ref(false)
const templatePreviewLoading = ref(false)
const templatePreview = ref<TemplateDetail | null>(null)
const templatePreviewParsedDoc = ref<any | null>(null)
const templateCache = new Map<string, TemplateDetail>()
const builderModelOptions = ref<BuilderModelOption[]>([])
const builderModelLoading = ref(false)
const selectedLandingModelId = ref<number | null>(null)
const landingMode = ref<LandingModeKey>('chat')
const landingInput = ref('')
const landingNotice = ref('')
const isCoworkDragover = ref(false)
const landingTextareaRef = ref<HTMLTextAreaElement | null>(null)
const prdInputRef = ref<HTMLInputElement | null>(null)
const chatFilesInputRef = ref<HTMLInputElement | null>(null)
const pendingChatFiles = ref<File[]>([])

const currentLandingMode = computed<LandingModeConfig>(() => (
  landingModeList.find(item => item.key === landingMode.value) ?? fallbackLandingMode
))
const landingGlyph = computed(() => {
  if (landingMode.value === 'online') return '</>'
  if (landingMode.value === 'code') return '{}'
  return 'AI'
})
const landingTitleSuffix = computed(() => currentLandingMode.value.titleSuffix)
const landingModeVars = computed<Record<string, string>>(() => ({
  '--landing-mode-color': currentLandingMode.value.color,
  '--landing-mode-soft': currentLandingMode.value.colorSoft,
  '--landing-mode-ink': currentLandingMode.value.colorInk,
}))
const userInitial = computed(() => (userStore.user?.username || 'A').slice(0, 1))
const userDisplayName = computed(() => (userStore.user as any)?.nickname || userStore.user?.username || 'admin')
const defaultLandingModelId = computed(() =>
  builderModelOptions.value.find(option => option.is_default)?.id
  ?? builderModelOptions.value[0]?.id
  ?? null
)
function formatDate(dateStr: string) {
  if (!dateStr) return '今天'
  const d = new Date(dateStr)
  return `${d.getMonth() + 1}月${d.getDate()}日`
}

function navigateTo(path: string) {
  router.push(path)
}

function openCommandPalette() {
  window.dispatchEvent(new CustomEvent('builder:open-command'))
}

function focusLandingInput() {
  requestAnimationFrame(() => landingTextareaRef.value?.focus())
}

function handleLandingKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
    event.preventDefault()
    submitLanding()
  }
}

function handleLandingDocUpload(event: Event) {
  const target = event.target as HTMLInputElement
  const files = Array.from(target.files || [])
  target.value = ''
  if (!files.length) return
  acceptCoworkFiles(files)
}

function handleCoworkDrop(event: DragEvent) {
  isCoworkDragover.value = false
  const files = Array.from(event.dataTransfer?.files || [])
  if (!files.length) return
  acceptCoworkFiles(files)
}

function acceptCoworkFiles(files: File[]) {
  // 2026-05-17: chat / cowork 合并后保留这个名字（被多处 callback 引用），
  // 行为不变：单 .md → Builder 直传快路；其它（含多文件） → AI-Chat 整合。
  previewStore.pendingBuilderModelId = selectedLandingModelId.value

  if (files.length === 1 && /\.(md|markdown)$/i.test(files[0].name)) {
    // 标准 md 快路：直接进 Builder 解析（query.from=upload 让 router 守卫放行）
    previewStore.pendingFile = files[0]
    router.push({ path: '/chat', query: { from: 'upload' } })
    return
  }

  // 其它格式（或多文件）→ AI-Chat 自动整合（mode=cowork 仅作底层 hint）
  previewStore.pendingAiChatFiles = files
  router.push({ path: '/ai-chat', query: { mode: 'cowork' } })
}

function handleChatFilesSelected(e: Event) {
  const input = e.target as HTMLInputElement
  if (!input.files) return
  pendingChatFiles.value.push(...Array.from(input.files))
  input.value = ''
}

async function submitLanding() {
  // cowork 模式没有主 CTA（dropzone 自己是行动入口），不会进这里
  const prompt = landingInput.value.trim()

  if (!prompt && !(landingMode.value === 'chat' && pendingChatFiles.value.length)) {
    ElMessage.warning('请先输入你要做什么')
    return
  }

  previewStore.pendingBuilderModelId = selectedLandingModelId.value

  if (landingMode.value === 'chat') {
    // 把附件交给 store，AIChatPage 建会话后会自动 upload 到该会话
    if (pendingChatFiles.value.length) {
      previewStore.pendingAiChatFiles = pendingChatFiles.value.slice()
      pendingChatFiles.value = []
    }
    await router.push({ path: '/ai-chat', query: prompt ? { prompt } : {} })
    return
  }

  if (landingMode.value === 'online') {
    // 把完整 prompt 暂存到 sessionStorage，跳到 vibe coding 列表页带 autocreate=1
    // OnlineCodingWorkspacePage 检测到会自动建 workspace + 把 prompt 缓存供 chat 首发
    sessionStorage.setItem(PENDING_VIBE_PROMPT_KEY, prompt)
    await router.push({ path: '/vibe-coding', query: { autocreate: '1' } })
    return
  }

  if (landingMode.value === 'code') {
    sessionStorage.setItem(PENDING_CODING_KEY, JSON.stringify({
      message: prompt,
      projectId: null,
      sceneCategory: 'page-pc',
    }))
    await router.push({
      path: '/coding',
      query: {
        from_ai_builder: '1',
        type: 'apaas-custom-dev',
      },
    })
  }
}

function normalizeLandingModelId(modelId?: number | null) {
  const ids = new Set(builderModelOptions.value.map(option => option.id))
  if (modelId != null && ids.has(modelId)) return modelId
  return defaultLandingModelId.value
}

async function loadBuilderModelOptions() {
  builderModelLoading.value = true
  try {
    builderModelOptions.value = await llmConfigApi.listOptions('builder')
    selectedLandingModelId.value = normalizeLandingModelId(
      previewStore.pendingBuilderModelId ?? selectedLandingModelId.value
    )
  } catch {
    builderModelOptions.value = []
    selectedLandingModelId.value = null
  } finally {
    builderModelLoading.value = false
  }
}

function sortTemplateFiles(list: TemplateFile[]) {
  return [...list].sort((a, b) => {
    const timeDiff = new Date(b.updated_at || 0).getTime() - new Date(a.updated_at || 0).getTime()
    if (timeDiff !== 0) return timeDiff
    return a.name.localeCompare(b.name, 'zh-CN')
  })
}

async function loadTemplateFiles() {
  try {
    const templates = await request.get<any, TemplateFile[]>('/templates')
    const sortedTemplates = sortTemplateFiles(Array.isArray(templates) ? templates : [])
    const latestTemplate = sortedTemplates[0]
    templateFiles.value = latestTemplate ? [latestTemplate] : []
  } catch {
    templateFiles.value = []
  }
}

async function getTemplateDetail(template: TemplateFile) {
  const cached = templateCache.get(template.code)
  if (cached) return cached

  const detail = await request.get<any, TemplateDetail>(`/templates/${template.code}`)
  const fullDetail = {
    ...template,
    ...detail,
  }
  templateCache.set(template.code, fullDetail)
  return fullDetail
}

async function openTemplatePreview(template: TemplateFile) {
  templatePreviewVisible.value = true
  templatePreviewLoading.value = true
  templatePreview.value = { ...template, content: '' }
  templatePreviewParsedDoc.value = null

  try {
    const detail = await getTemplateDetail(template)
    templatePreview.value = detail
    try {
      templatePreviewParsedDoc.value = standardDocMdToStructuredDoc(detail.content)
    } catch {
      templatePreviewParsedDoc.value = null
    }
  } catch (error: any) {
    templatePreviewVisible.value = false
    handleError(error, { fallback: '加载模板失败' })
  } finally {
    templatePreviewLoading.value = false
  }
}

async function openTemplateFromComposer() {
  if (!templateFiles.value.length) {
    await loadTemplateFiles()
  }
  const template = templateFiles.value[0]
  if (!template) {
    ElMessage.warning('暂无可用文档模板')
    return
  }
  await openTemplatePreview(template)
}

async function downloadTemplate(template: TemplateFile) {
  try {
    const detail = 'content' in template ? template as TemplateDetail : await getTemplateDetail(template)
    const blob = new Blob([detail.content], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = detail.filename || `${detail.code}.md`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  } catch (error: any) {
    handleError(error, { fallback: '下载模板失败' })
  }
}

function mapApplicationToCard(app: any): AppItem {
  return {
    id: app.id,
    label: app.app_name || app.appName || '未命名应用',
    status: app.local_status || app.status || 'draft',
    timeLabel: formatDate(app.updated_at || app.created_at || ''),
    appId: typeof app.id === 'number' ? app.id : Number(app.id),
    conversationId: app.conversation_id,
    apaasAppId: app.apaas_app_id,
  }
}

function mapConversationToAppCard(conv: ConversationWithApp): AppItem {
  return {
    id: conv.app_id as number,
    label: conv.app_name || '未命名应用',
    status: conv.local_status || 'completed',
    timeLabel: formatDate(conv.updated_at || conv.created_at),
    appId: conv.app_id,
    conversationId: conv.id,
    apaasAppId: conv.apaas_app_id,
  }
}

function buildFallbackAppsFromConversations(list: ConversationWithApp[]) {
  const appMap = new Map<number, ConversationWithApp>()

  for (const conv of list) {
    if (!conv.app_id || !conv.app_name) continue
    const existing = appMap.get(conv.app_id)
    const convTime = new Date(conv.updated_at || conv.created_at || 0).getTime()
    const existingTime = existing ? new Date(existing.updated_at || existing.created_at || 0).getTime() : -1

    if (!existing || convTime > existingTime) {
      appMap.set(conv.app_id, conv)
    }
  }

  return Array.from(appMap.values()).sort((a, b) => {
    const ta = new Date(a.updated_at || a.created_at || 0).getTime()
    const tb = new Date(b.updated_at || b.created_at || 0).getTime()
    return tb - ta
  })
}

function resetPasswordForm() {
  passwordForm.value = { oldPassword: '', newPassword: '', confirmPassword: '' }
}

async function submitChangePassword() {
  const { oldPassword, newPassword, confirmPassword } = passwordForm.value
  if (!oldPassword || !newPassword || !confirmPassword) {
    ElMessage.warning('请完整填写修改密码信息')
    return
  }
  if (newPassword.length < 6) {
    ElMessage.warning('新密码长度不能少于 6 位')
    return
  }
  if (newPassword !== confirmPassword) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }

  try {
    changingPassword.value = true
    await request.post('/auth/change-password', {
      old_password: oldPassword,
      new_password: newPassword
    })
    ElMessage.success('密码修改成功，请重新登录')
    profileDialogVisible.value = false
    resetPasswordForm()
    userStore.logout()
    router.push('/login')
  } catch (error: any) {
    const status = error?.response?.status
    const detail = error?.response?.data?.detail
    if (status === 404 || status === 405) {
      ElMessage.warning('当前环境暂未开放修改密码接口，请联系管理员')
      return
    }
    ElMessage.error(detail || '修改密码失败，请稍后重试')
  } finally {
    changingPassword.value = false
  }
}

async function loadApps() {
  const [list, apps] = await Promise.all([
    conversationApi.listWithApps({ agent_type: 'builder' }).catch(() => []),
    applicationApi.list({ include_remote: true }).catch(() => []),
    loadTemplateFiles(),
    loadBuilderModelOptions(),
  ])

  totalConversationCount.value = list.length
  recentSessions.value = list.slice(0, 8)

  const appRecords = Array.isArray(apps)
    ? apps
        .filter((app: any) => app?.id && app?.app_name)
        .sort((a: any, b: any) => {
          const ta = new Date(a.updated_at || a.created_at || 0).getTime()
          const tb = new Date(b.updated_at || b.created_at || 0).getTime()
          return tb - ta
        })
        .map(mapApplicationToCard)
    : []

  const fallbackApps = buildFallbackAppsFromConversations(list).map(mapConversationToAppCard)
  const sourceApps = appRecords.length ? appRecords : fallbackApps

  totalAppsCount.value = sourceApps.length
  recentApps.value = sourceApps.slice(0, 6)

  generatedModules.value = (Array.isArray(apps) && apps.length ? apps : list).reduce((sum: number, item: any) => {
    const data = item.config_preview?.data || item.config_preview || {}
    return sum + (Array.isArray(data.models) ? data.models.length : 0)
  }, 0)
}

onMounted(loadApps)
</script>

<style scoped>
* { box-sizing: border-box; margin: 0; padding: 0; }

.main {
  --surface-strong: rgba(255, 255, 255, 0.96);
  --surface-soft: rgba(255, 255, 255, 0.86);
  --surface-muted: rgba(248, 250, 252, 0.94);
  --stroke-soft: rgba(15, 23, 42, 0.10);
  --stroke-strong: rgba(15, 23, 42, 0.16);
  --text-strong: #111827;
  --text-secondary: #334155;
  --text-muted: #64748b;
  --accent: #111827;
  --accent-soft: #f1f5f9;
  --shadow-soft: 0 18px 38px rgba(15, 23, 42, 0.06);
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
}
.bg { position: absolute; inset: 0; background: #f4f6fa; z-index: 0; }
.content {
  flex: 1;
  overflow-y: auto;
  position: relative;
  z-index: 1;
  padding: 0 22px 28px;
}

.landing-topbar {
  position: relative;
  z-index: 2;
  height: 52px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 16px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.08);
  background: rgba(255, 255, 255, 0.92);
}

.landing-breadcrumbs {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
  color: #64748b;
  font-size: 13px;
  font-weight: 600;
}

.landing-breadcrumbs strong {
  color: #111827;
  font-weight: 700;
}

.landing-topbar-spacer {
  flex: 1;
  min-width: 16px;
}

.landing-command {
  height: 32px;
  width: 420px;
  max-width: 42vw;
  border: 1px solid rgba(15, 23, 42, 0.10);
  border-radius: 8px;
  background: #f8fafc;
  color: #64748b;
  display: inline-flex;
  align-items: center;
  justify-content: space-between;
  gap: 9px;
  padding: 0 9px;
  cursor: pointer;
  font-size: 12px;
  min-width: 0;
}

.landing-command span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.landing-command:hover {
  background: #fff;
  color: #111827;
}

.landing-command kbd {
  flex-shrink: 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 10px;
  line-height: 1;
  padding: 3px 5px;
  border-radius: 4px;
  border: 1px solid rgba(15, 23, 42, 0.10);
  background: #fff;
  color: #64748b;
}

.landing-admin-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.landing-admin-actions button {
  height: 34px;
  padding: 0 14px;
  border: 1px solid rgba(68, 91, 214, 0.20);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.86);
  color: #24314f;
  font-size: 12px;
  font-weight: 760;
  cursor: pointer;
  box-shadow: 0 10px 24px rgba(51, 65, 85, 0.07);
  transition: transform 0.18s ease, border-color 0.18s ease, background 0.18s ease, color 0.18s ease;
}

.landing-admin-actions button:hover {
  transform: translateY(-1px);
  border-color: rgba(68, 91, 214, 0.32);
  color: #3858d6;
  background: #f8faff;
}

.landing {
  flex: 1;
  min-height: 0;
  position: relative;
  z-index: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 30px;
  padding: 34px 32px 38px;
  background: #fbfcfe;
}

.landing-bg {
  position: absolute;
  inset: 0;
  pointer-events: none;
  background-image:
    radial-gradient(rgba(54, 128, 198, 0.07) 1px, transparent 1px),
    radial-gradient(rgba(82, 74, 190, 0.055) 1px, transparent 1px);
  background-size: 32px 32px, 64px 64px;
  background-position: 0 0, 16px 16px;
  mask-image: radial-gradient(ellipse 800px 600px at center 40%, black, transparent);
}

.landing-bg::after {
  content: '';
  position: absolute;
  inset: 0;
  background: radial-gradient(ellipse 600px 300px at center 30%, color-mix(in srgb, var(--landing-mode-color) 12%, transparent), transparent);
}

.brand-mark {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  position: relative;
  z-index: 1;
}

.brand-glyph {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  background: linear-gradient(135deg, var(--landing-mode-color), var(--landing-mode-ink));
  color: #fff;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 18px;
  font-weight: 800;
  letter-spacing: 0;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.12), 0 0 0 1px rgba(15, 23, 42, 0.12);
}

.brand-eyebrow {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
  line-height: 1;
  color: var(--landing-mode-ink);
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.brand-copy {
  position: relative;
  z-index: 1;
  max-width: 720px;
  text-align: center;
}

.brand-title {
  margin: 0;
  font-size: 40px;
  line-height: 1.1;
  font-weight: 650;
  letter-spacing: 0;
  color: #111827;
}

.brand-title span {
  color: var(--landing-mode-color);
}

.brand-title em {
  margin-left: 12px;
  display: inline-block;
  font-style: normal;
  color: #111827;
}

.brand-sub {
  margin: 12px auto 0;
  max-width: 560px;
  color: #667085;
  font-size: 14px;
  line-height: 1.55;
}

.mode-switcher {
  position: relative;
  z-index: 1;
  display: inline-flex;
  gap: 2px;
  padding: 4px;
  border-radius: 10px;
  border: 0.5px solid #d8dee8;
  background: #fff;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04), 0 0 0 0.5px rgba(15, 23, 42, 0.04);
}

.mode-tab {
  min-width: 132px;
  min-height: 38px;
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  border-radius: 7px;
  border: 0.5px solid transparent;
  background: transparent;
  color: #667085;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.18s ease;
}

.mode-tab-static {
  cursor: default;
}

.mode-tab:hover:not(.active) {
  background: #f5f7fb;
  color: #111827;
}

.mode-tab.active {
  border-color: var(--landing-mode-color);
  background: var(--landing-mode-soft);
  color: var(--landing-mode-ink);
  font-weight: 650;
}

.mode-tab-icon,
.composer-mode-label span {
  display: inline-flex;
  width: 16px;
  align-items: center;
  justify-content: center;
  color: currentColor;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
}

.mode-tab-label {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.mode-tab-zh {
  margin-left: auto;
  color: currentColor;
  font-size: 11px;
  opacity: 0.68;
  white-space: nowrap;
}

.mode-tab-dot {
  position: absolute;
  top: 6px;
  right: 6px;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--landing-mode-color);
}

.composer {
  width: 100%;
  max-width: 760px;
  position: relative;
  z-index: 1;
}

.composer-shell {
  overflow: hidden;
  border-radius: 12px;
  border: 0.5px solid #d1d8e5;
  background: #fff;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08), 0 0 0 1px color-mix(in srgb, var(--landing-mode-color) 14%, transparent);
  transition: box-shadow 0.18s ease, border-color 0.18s ease;
}

.composer-shell:focus-within {
  border-color: color-mix(in srgb, var(--landing-mode-color) 54%, #d1d8e5);
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.10), 0 0 0 3px color-mix(in srgb, var(--landing-mode-color) 16%, transparent);
}

.ai-surface {
  position: relative;
}

.ai-surface::before {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  background-image: radial-gradient(color-mix(in srgb, var(--landing-mode-color) 8%, transparent) 1px, transparent 1px);
  background-size: 20px 20px;
  opacity: 0.5;
  mask-image: radial-gradient(ellipse at center, black 30%, transparent 70%);
}

.composer-mode-bar {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  border-bottom: 0.5px solid color-mix(in srgb, var(--landing-mode-color) 22%, #d8dee8);
  background: var(--landing-mode-soft);
  color: var(--landing-mode-ink);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.composer-mode-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
}

.kbd-inline,
.submit-kbd {
  display: inline-flex;
  min-width: 16px;
  align-items: center;
  justify-content: center;
  padding: 0 5px;
  border-radius: 3px;
  border: 0.5px solid #d8dee8;
  background: #fff;
  color: #667085;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 9px;
  line-height: 14px;
}

.composer-body {
  position: relative;
  z-index: 1;
  padding: 14px 16px 10px;
  border-radius: 12px;
  transition: background-color 0.15s ease, box-shadow 0.15s ease;
}

.composer-body.is-dragover {
  background-color: var(--landing-mode-soft, oklch(96% 0.03 220));
  box-shadow: inset 0 0 0 2px var(--landing-mode-color, oklch(60% 0.16 220));
}

.composer-drop-hint {
  margin-top: 8px;
  padding: 6px 10px;
  font-size: 12px;
  color: #98a2b3;
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.02);
  user-select: none;
}

.composer-input {
  width: 100%;
  min-height: 72px;
  max-height: 240px;
  border: 0;
  outline: 0;
  resize: none;
  background: transparent;
  color: #111827;
  font-size: 14px;
  line-height: 1.55;
  font-family: inherit;
}

.composer-input::placeholder {
  color: #98a2b3;
}

.composer-dropzone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 120px;
  padding: 20px;
  border: 1.5px dashed #c5cee0;
  border-radius: 14px;
  background: linear-gradient(180deg, rgba(99, 102, 241, 0.03), rgba(99, 102, 241, 0));
  cursor: pointer;
  transition: border-color 0.18s, background 0.18s, transform 0.18s;
  user-select: none;
}

.composer-dropzone:hover,
.composer-dropzone:focus-visible {
  border-color: var(--landing-mode-color, #6366f1);
  background: rgba(99, 102, 241, 0.06);
  outline: none;
}

.composer-dropzone.is-dragover {
  border-color: var(--landing-mode-color, #6366f1);
  background: rgba(99, 102, 241, 0.1);
  transform: scale(1.005);
}

.dropzone-icon {
  font-size: 32px;
  line-height: 1;
}

.dropzone-title {
  font-size: 14px;
  font-weight: 600;
  color: #1f2937;
}

.dropzone-hint {
  font-size: 12px;
  color: #6b7280;
}

.composer-toolbar {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-top: 0.5px solid #e4e8f0;
  background: #f8fafc;
}

.chip {
  height: 24px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 0 8px;
  border-radius: 6px;
  border: 0.5px solid #d8dee8;
  background: #fff;
  color: #667085;
  cursor: pointer;
  font-size: 11px;
  white-space: nowrap;
}

.chip:hover {
  background: #f1f4f9;
  color: #111827;
}

.template-chip {
  color: var(--landing-mode-ink);
  border-color: color-mix(in srgb, var(--landing-mode-color) 28%, #d8dee8);
  background: color-mix(in srgb, var(--landing-mode-soft) 66%, #fff);
}

.chip-hint {
  font-size: 11px;
  color: #98a2b3;
  user-select: none;
}

.composer-attach-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 8px 12px 0;
}
.attach-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: var(--landing-mode-soft);
  border: 0.5px solid color-mix(in srgb, var(--landing-mode-color) 30%, #d8dee8);
  color: var(--landing-mode-ink);
  padding: 2px 6px 2px 8px;
  border-radius: 5px;
  font-size: 11px;
  max-width: 220px;
}
.attach-chip-icon { font-size: 11px; }
.attach-chip-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.attach-chip-x {
  appearance: none;
  background: none;
  border: none;
  color: inherit;
  cursor: pointer;
  padding: 0 2px;
  margin-left: 2px;
  opacity: 0.6;
}
.attach-chip-x:hover { opacity: 1; }

.toolbar-spacer {
  flex: 1;
}

.seg-ctrl {
  display: inline-flex;
  align-items: center;
  height: 26px;
  padding: 2px;
  gap: 1px;
  border-radius: 7px;
  border: 0.5px solid #d8dee8;
  background: #fff;
}

.seg-btn {
  height: 20px;
  padding: 0 8px;
  border: none;
  border-radius: 5px;
  background: transparent;
  color: #667085;
  cursor: pointer;
  font-size: 11px;
}

.seg-btn.active {
  background: #111827;
  color: #fff;
}

.landing-submit {
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 0 10px;
  border-radius: 6px;
  border: 0.5px solid var(--landing-mode-color);
  background: var(--landing-mode-color);
  color: #fff;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.landing-submit:disabled {
  opacity: 0.42;
  cursor: not-allowed;
}

.landing-submit .submit-kbd {
  border-color: rgba(255, 255, 255, 0.18);
  background: rgba(0, 0, 0, 0.18);
  color: #fff;
}

.landing-footnotes {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 16px;
  color: #98a2b3;
  font-size: 11px;
}

.landing-footnotes button {
  border: none;
  background: transparent;
  color: #667085;
  cursor: pointer;
  font-size: 11px;
}

.landing-footnotes button:hover {
  color: #111827;
}

.landing-toast {
  position: fixed;
  left: 50%;
  bottom: 24px;
  z-index: 20;
  transform: translateX(-50%);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 12px;
  border-radius: 6px;
  background: #111827;
  color: #fff;
  box-shadow: 0 16px 48px rgba(15, 23, 42, 0.16);
  font-size: 11px;
}

:global(html[data-theme="dark"]) .main {
  --surface-strong: rgba(17, 19, 24, 0.96);
  --surface-soft: rgba(17, 19, 24, 0.86);
  --surface-muted: rgba(13, 17, 23, 0.94);
  --stroke-soft: rgba(148, 163, 184, 0.14);
  --stroke-strong: rgba(148, 163, 184, 0.24);
  --text-strong: rgba(248, 250, 252, 0.94);
  --text-secondary: rgba(203, 213, 225, 0.70);
  --text-muted: rgba(148, 163, 184, 0.48);
  --accent: #f8fafc;
  --accent-soft: rgba(124, 140, 255, 0.14);
  --shadow-soft: 0 18px 38px rgba(0, 0, 0, 0.38);
}

:global(html[data-theme="dark"]) .bg,
:global(html[data-theme="dark"]) .landing {
  background: #090b10;
}

:global(html[data-theme="dark"]) .landing-topbar {
  border-bottom-color: rgba(148, 163, 184, 0.14);
  background: rgba(9, 11, 16, 0.94);
}

:global(html[data-theme="dark"]) .landing-breadcrumbs {
  color: rgba(203, 213, 225, 0.62);
}

:global(html[data-theme="dark"]) .landing-breadcrumbs strong,
:global(html[data-theme="dark"]) .brand-title,
:global(html[data-theme="dark"]) .brand-title em {
  color: rgba(248, 250, 252, 0.94);
}

:global(html[data-theme="dark"]) .landing-command {
  border-color: rgba(148, 163, 184, 0.18);
  background: #0d1117;
  color: rgba(203, 213, 225, 0.64);
}

:global(html[data-theme="dark"]) .landing-command:hover {
  background: #151922;
  color: rgba(248, 250, 252, 0.94);
}

:global(html[data-theme="dark"]) .landing-admin-actions button {
  border-color: rgba(148, 163, 184, 0.18);
  background: rgba(17, 19, 24, 0.86);
  color: rgba(226, 232, 240, 0.82);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
}

:global(html[data-theme="dark"]) .landing-admin-actions button:hover {
  border-color: rgba(124, 140, 255, 0.36);
  background: rgba(26, 29, 36, 0.96);
  color: rgba(248, 250, 252, 0.94);
}

:global(html[data-theme="dark"]) .landing-command kbd,
:global(html[data-theme="dark"]) .kbd-inline,
:global(html[data-theme="dark"]) .submit-kbd {
  border-color: rgba(148, 163, 184, 0.18);
  background: #111318;
  color: rgba(203, 213, 225, 0.62);
}

:global(html[data-theme="dark"]) .landing-bg {
  background-image:
    radial-gradient(rgba(124, 140, 255, 0.12) 1px, transparent 1px),
    radial-gradient(rgba(52, 211, 153, 0.06) 1px, transparent 1px);
}

:global(html[data-theme="dark"]) .brand-sub {
  color: rgba(203, 213, 225, 0.66);
}

:global(html[data-theme="dark"]) .brand-glyph {
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.40), 0 0 0 1px rgba(148, 163, 184, 0.18);
}

:global(html[data-theme="dark"]) .mode-switcher,
:global(html[data-theme="dark"]) .composer-shell,
:global(html[data-theme="dark"]) .seg-ctrl,
:global(html[data-theme="dark"]) .chip {
  border-color: rgba(148, 163, 184, 0.16);
  background: #111318;
  box-shadow: 0 0 0 0.5px rgba(148, 163, 184, 0.10);
}

:global(html[data-theme="dark"]) .mode-tab.active {
  border-color: color-mix(in srgb, var(--landing-mode-color) 62%, rgba(148, 163, 184, 0.24));
  background: rgba(124, 140, 255, 0.12);
}

:global(html[data-theme="dark"]) .composer-shell {
  box-shadow: 0 18px 50px rgba(0, 0, 0, 0.38), 0 0 0 1px color-mix(in srgb, var(--landing-mode-color) 18%, transparent);
}

:global(html[data-theme="dark"]) .composer-mode-bar {
  border-bottom-color: rgba(148, 163, 184, 0.14);
  background: rgba(124, 140, 255, 0.11);
}

:global(html[data-theme="dark"]) .composer-dropzone {
  border-color: #303d52;
  background: linear-gradient(180deg, rgba(99, 102, 241, 0.06), rgba(99, 102, 241, 0));
}
:global(html[data-theme="dark"]) .composer-dropzone:hover,
:global(html[data-theme="dark"]) .composer-dropzone.is-dragover {
  border-color: var(--landing-mode-color, #818cf8);
  background: rgba(99, 102, 241, 0.12);
}
:global(html[data-theme="dark"]) .dropzone-title {
  color: #e7ecf3;
}
:global(html[data-theme="dark"]) .dropzone-hint {
  color: #94a3b8;
}

:global(html[data-theme="dark"]) .composer-input {
  color: rgba(248, 250, 252, 0.94);
}

:global(html[data-theme="dark"]) .composer-input::placeholder {
  color: rgba(148, 163, 184, 0.56);
}

:global(html[data-theme="dark"]) .composer-toolbar {
  border-top-color: rgba(148, 163, 184, 0.14);
  background: #0d1117;
}

:global(html[data-theme="dark"]) .chip,
:global(html[data-theme="dark"]) .seg-btn,
:global(html[data-theme="dark"]) .landing-footnotes button {
  color: rgba(203, 213, 225, 0.64);
}

:global(html[data-theme="dark"]) .chip:hover {
  background: #1a1d24;
  color: rgba(248, 250, 252, 0.94);
}

:global(html[data-theme="dark"]) .template-chip {
  color: rgba(226, 232, 240, 0.88);
  border-color: color-mix(in srgb, var(--landing-mode-color) 44%, rgba(148, 163, 184, 0.16));
  background: color-mix(in srgb, var(--landing-mode-color) 12%, #111318);
}

:global(html[data-theme="dark"]) .seg-btn.active {
  background: #f8fafc;
  color: #090b10;
}

:global(html[data-theme="dark"]) .landing-submit .submit-kbd {
  border-color: rgba(255, 255, 255, 0.16);
  background: rgba(0, 0, 0, 0.26);
  color: #fff;
}

:global(html[data-theme="dark"]) .landing-footnotes {
  color: rgba(148, 163, 184, 0.45);
}

:global(html[data-theme="dark"]) .landing-footnotes button:hover {
  color: rgba(248, 250, 252, 0.94);
}

.hero {
  max-width: 1320px;
  margin: 18px auto 12px;
  padding: 0 2px;
  text-align: left;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
}

.hero-copy {
  min-width: 0;
  max-width: 760px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.hero-kicker {
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
}

.hero-title {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-strong);
  letter-spacing: 0;
}

.hero-sub {
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-secondary);
}

.hero-status {
  flex-shrink: 0;
  min-height: 30px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 0 10px;
  border: 1px solid rgba(15, 23, 42, 0.10);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.88);
  color: #475569;
  font-size: 12px;
  font-weight: 600;
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #22c55e;
  box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.14);
}

.legacy-entry-shell {
  max-width: 1320px;
  margin: 12px auto 0;
  padding: 16px 18px;
  border-radius: 8px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: rgba(255, 255, 255, 0.82);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.legacy-entry-copy {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.legacy-entry-label {
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: #6f67a9;
}

.legacy-entry-title {
  font-size: 13px;
  line-height: 1.7;
  color: #4c4775;
}

.legacy-entry-toggle {
  border: none;
  border-radius: 8px;
  min-height: 34px;
  padding: 0 16px;
  background: #eef2f7;
  color: #111827;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}

.upload-workbench {
  max-width: 1320px;
  margin: 0 auto;
  padding: 0;
  display: block;
}
.upload-entry-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(320px, 0.9fr);
  gap: 12px;
  align-items: stretch;
}
.upload-feature-card {
  background: var(--surface-strong);
  border: 1px solid rgba(255, 255, 255, 0.92);
  border-radius: 24px;
  box-shadow: 0 24px 60px rgba(78, 71, 147, 0.10);
  backdrop-filter: blur(12px);
  padding: 20px 22px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.entry-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.entry-head-compact {
  margin-bottom: 2px;
}
.entry-copy {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}
.entry-subtitle {
  max-width: 500px;
  font-size: 12px;
  line-height: 1.65;
  color: var(--text-muted);
}
.entry-side-note {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  min-height: 30px;
  padding: 0 11px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.78);
  box-shadow: inset 0 0 0 1px rgba(83, 74, 183, 0.10);
  color: var(--text-secondary);
  font-size: 10px;
  font-weight: 600;
}
.ai-entry-card {
  justify-content: space-between;
  position: relative;
  overflow: hidden;
  background:
    radial-gradient(circle at top right, rgba(107, 125, 255, 0.18), transparent 34%),
    radial-gradient(circle at bottom left, rgba(88, 201, 165, 0.10), transparent 32%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(246, 248, 255, 0.92));
}
.ai-entry-body {
  display: flex;
  flex-direction: column;
  gap: 18px;
  flex: 1;
  min-height: 0;
}
.ai-entry-visual {
  position: relative;
  width: 82px;
  height: 82px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.ai-orbit {
  position: absolute;
  border-radius: 999px;
  border: 1px solid rgba(90, 98, 203, 0.14);
  background: rgba(255, 255, 255, 0.42);
}
.ai-orbit-large {
  inset: 0;
  box-shadow: inset 0 0 20px rgba(115, 113, 255, 0.08);
}
.ai-orbit-small {
  inset: 12px;
}
.ai-entry-core {
  position: relative;
  z-index: 1;
  width: 44px;
  height: 44px;
  border-radius: 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #ffffff;
  background: linear-gradient(135deg, #5950c7 0%, #7b6eff 100%);
  box-shadow: 0 14px 28px rgba(91, 80, 199, 0.24);
}
.ai-entry-copy {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.ai-entry-heading {
  font-size: 20px;
  line-height: 1.2;
  font-weight: 700;
  color: var(--text-strong);
  letter-spacing: -0.03em;
}
.ai-entry-desc {
  font-size: 13px;
  line-height: 1.68;
  color: var(--text-muted);
}
.ai-entry-steps {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.ai-entry-step {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 40px;
  padding: 0 12px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.82);
  box-shadow:
    inset 0 0 0 1px rgba(83, 74, 183, 0.08),
    0 10px 24px rgba(90, 98, 203, 0.06);
}
.ai-entry-step-index {
  width: 28px;
  height: 28px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: rgba(81, 71, 189, 0.10);
  color: var(--accent);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.04em;
  flex-shrink: 0;
}
.ai-entry-step-text {
  font-size: 11px;
  font-weight: 600;
  line-height: 1.5;
  color: var(--text-secondary);
}
.ai-entry-actions {
  margin-top: auto;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
  padding-top: 4px;
  width: 100%;
}
.ai-entry-cta {
  min-height: 50px;
  width: 100%;
  justify-content: center;
  padding: 0 18px;
  border: none;
  border-radius: 16px;
  background: linear-gradient(135deg, #5147bd 0%, #6f63ef 100%);
  color: #fff;
  font-size: 14px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  box-shadow: 0 16px 30px rgba(81, 71, 189, 0.24);
  transition: transform 180ms ease, box-shadow 180ms ease, opacity 180ms ease;
}
.ai-entry-cta:hover {
  transform: translateY(-1px);
  box-shadow: 0 18px 34px rgba(81, 71, 189, 0.28);
}
.ai-entry-note {
  font-size: 11px;
  line-height: 1.6;
  color: var(--text-secondary);
  opacity: 0.82;
  max-width: 320px;
}
.card-tag {
  display: inline-flex;
  align-items: center;
  align-self: flex-start;
  padding: 4px 9px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--text-secondary);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.02em;
}
.upload-title {
  font-size: 17px;
  line-height: 1.25;
  font-weight: 700;
  color: var(--text-strong);
  max-width: none;
  letter-spacing: -0.02em;
}
.template-inline-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px 16px;
  border-radius: 20px;
  background: linear-gradient(180deg, rgba(245, 247, 255, 0.92), rgba(255, 255, 255, 0.9));
  border: 1px solid rgba(83, 74, 183, 0.10);
}
.template-inline-section.dragging {
  border-color: rgba(83, 74, 183, 0.34);
  box-shadow: inset 0 0 0 1px rgba(83, 74, 183, 0.08);
}
.template-inline-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}
.template-inline-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
}
.landing-model-picker {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}
.landing-model-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
}
.landing-model-select {
  width: 220px;
  max-width: 100%;
}
.landing-model-select :deep(.el-select__wrapper) {
  min-height: 36px;
  border-radius: 11px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: inset 0 0 0 1px rgba(83, 74, 183, 0.12);
}
.landing-model-select :deep(.el-select__selected-item) {
  font-size: 11px;
  color: var(--text-strong);
}
.landing-model-hint {
  font-size: 10px;
  line-height: 1.4;
  color: var(--text-muted);
}
.builder-model-option-row {
  display: flex;
  flex-direction: column;
  line-height: 1.35;
}
.builder-model-option-name {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-strong);
}
.builder-model-option-meta {
  font-size: 10px;
  color: var(--text-muted);
}
.upload-footnote {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 10px;
  font-size: 11px;
  line-height: 1.6;
  color: var(--text-muted);
}
.template-item {
  background: var(--surface-muted);
  border: 1px solid var(--stroke-soft);
  border-radius: 18px;
  padding: 14px 16px;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
}
.template-item-inline {
  background: rgba(255, 255, 255, 0.9);
}
.template-item-compact {
  gap: 14px;
}
.template-icon {
  width: 38px;
  height: 38px;
  border-radius: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--accent);
  background: rgba(238, 237, 254, 0.95);
  flex-shrink: 0;
}
.template-main {
  min-width: 0;
}
.template-topline {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
}
.template-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-strong);
}
.template-category {
  display: inline-flex;
  align-items: center;
  padding: 2px 7px;
  border-radius: 999px;
  background: rgba(225, 245, 238, 0.9);
  color: #16654E;
  font-size: 10px;
  font-weight: 600;
}
.template-summary {
  margin-top: 4px;
  font-size: 11px;
  line-height: 1.6;
  color: var(--text-muted);
}
.template-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 6px;
  font-size: 10px;
  color: var(--text-secondary);
  opacity: 0.82;
}
.template-actions {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.template-action {
  min-width: 72px;
  height: 38px;
  padding: 0 12px;
  border-radius: 12px;
  border: 1px solid transparent;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.16s ease, transform 0.16s ease;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.template-action:hover {
  transform: translateY(-1px);
}
.template-action.ghost {
  background: rgba(255, 255, 255, 0.92);
  border-color: rgba(83, 74, 183, 0.14);
  color: var(--text-secondary);
}
.template-action.solid {
  background: var(--accent);
  color: #F7F6FF;
}
.template-upload-btn {
  position: relative;
  overflow: hidden;
}
.template-empty {
  min-height: 124px;
  border-radius: 14px;
  border: 1px dashed var(--stroke-soft);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  font-size: 12px;
  line-height: 1.7;
  text-align: center;
  color: var(--text-muted);
}
.template-empty-inline {
  min-height: 84px;
  background: rgba(255, 255, 255, 0.7);
}

.body-content {
  max-width: 1320px;
  margin: 0 auto;
  padding: 14px 0 22px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.overview-shell {
  max-width: 1320px;
  margin: 14px auto 0;
  padding: 16px 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.82);
  border: 1px solid rgba(15, 23, 42, 0.08);
}
.overview-copy {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.overview-label {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0;
  color: #64748b;
}
.overview-title {
  font-size: 13px;
  line-height: 1.7;
  color: #334155;
}
.overview-toggle {
  border: none;
  background: #eef2f7;
  color: #111827;
  min-height: 34px;
  padding: 0 16px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  flex-shrink: 0;
}
.stats-row { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.stat-card { background: rgba(255,255,255,0.86); border: 1px solid rgba(15,23,42,0.08); border-radius: 8px; padding: 14px 16px; }
.stat-label { font-size: 11px; color: #64748b; margin-bottom: 5px; opacity: 0.9; }
.stat-num { font-size: 20px; font-weight: 600; color: #111827; }
.stat-sub { font-size: 11px; color: #3B6D11; margin-top: 2px; }

.section-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.section-title { font-size: 13px; font-weight: 600; color: #111827; }
.section-actions { display: flex; align-items: center; gap: 12px; }
.import-link { border: none; background: transparent; color: #334155; font-size: 12px; font-weight: 600; cursor: pointer; padding: 0; display: flex; align-items: center; gap: 4px; }
.import-link:hover { color: #111827; }
.view-all-link { border: none; background: transparent; color: #334155; font-size: 12px; font-weight: 600; cursor: pointer; padding: 0; }
.view-all-link:hover { color: #111827; }
.app-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.app-card { background: rgba(255,255,255,0.86); border: 1px solid rgba(15,23,42,0.08); border-radius: 8px; padding: 14px; cursor: pointer; text-align: left; }
.app-card-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.app-dot { width: 28px; height: 28px; border-radius: 7px; display: flex; align-items: center; justify-content: center; font-size: 13px; flex-shrink: 0; }
.app-dot { font-weight: 700; color: #4c419f; }
.app-dot.purple { background: #EEEDFE; }
.app-dot.teal { background: #E1F5EE; }
.app-dot.amber { background: #FAEEDA; }
.app-name { font-size: 12px; font-weight: 600; color: #111827; }
.app-time { font-size: 11px; color: #64748b; opacity: 0.8; margin-top: 1px; }
.app-status { display: inline-flex; font-size: 11px; padding: 2px 7px; border-radius: 20px; }
.app-status.done { background: #EAF3DE; color: #3B6D11; }
.app-status.building { background: #EEEDFE; color: #534AB7; }

.profile-block { padding: 4px 2px 12px; }
.profile-hero { display: flex; align-items: center; gap: 14px; padding: 8px 0 16px; }
.profile-avatar { width: 52px; height: 52px; border-radius: 50%; background: linear-gradient(135deg, #534AB7 0%, #7E76E6 100%); color: #fff; display: flex; align-items: center; justify-content: center; font-size: 20px; font-weight: 600; flex-shrink: 0; }
.profile-identity { min-width: 0; }
.profile-name { font-size: 18px; font-weight: 600; color: var(--color-text-primary); line-height: 1.2; }
.profile-subtitle { font-size: 12px; color: var(--color-text-tertiary); margin-top: 4px; }
.profile-row { display: flex; align-items: center; justify-content: space-between; border: 0.5px solid var(--color-border-tertiary); border-radius: 10px; padding: 10px 12px; margin-bottom: 8px; }
.profile-label { font-size: 13px; color: var(--color-text-secondary); }
.profile-value { font-size: 13px; color: var(--color-text-primary); font-weight: 500; }
.password-form { margin-top: 4px; }
.profile-title { font-size: 13px; font-weight: 500; color: var(--color-text-primary); margin-bottom: 10px; }
.pwd-input { margin-bottom: 10px; }

.template-preview-head {
  padding-bottom: 14px;
}
.template-preview-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--text-secondary);
}
.template-preview-desc {
  margin-top: 8px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-muted);
}
.template-preview-body {
  max-height: 58vh;
  overflow: auto;
  padding: 16px;
  border-radius: 14px;
  background: #F7F8FF;
  border: 1px solid rgba(83, 74, 183, 0.10);
  color: var(--text-strong);
  font-size: 12px;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: "SFMono-Regular", "Menlo", "Consolas", monospace;
}
.template-preview-structured {
  max-height: 68vh;
  overflow: auto;
  padding: 16px;
  border-radius: 14px;
  background: #F7F8FF;
  border: 1px solid rgba(83, 74, 183, 0.10);
}
.template-preview-dialog :deep(.el-dialog) {
  max-width: calc(100vw - 64px);
}
.template-preview-dialog :deep(.el-dialog__body) {
  padding-top: 12px;
}
.template-preview-structured :deep(.doc-table-wrap) {
  overflow-x: auto;
}
.template-preview-structured :deep(.doc-table) {
  width: max-content;
  min-width: 980px;
}
.template-preview-structured :deep(.doc-table th),
.template-preview-structured :deep(.doc-table td) {
  padding: 6px 8px;
  font-size: 11px;
  line-height: 1.55;
  white-space: nowrap;
}
.template-preview-structured :deep(.doc-table th) {
  font-size: 11px;
}
.template-preview-structured :deep(.doc-table th:last-child),
.template-preview-structured :deep(.doc-table td:last-child) {
  min-width: 180px;
  white-space: normal;
}
.template-preview-structured :deep(.doc-section-title) {
  font-size: 15px;
}
.template-preview-structured :deep(.doc-card-title) {
  font-size: 14px;
}
.template-preview-structured :deep(.doc-meta) {
  font-size: 12px;
}
.template-preview-empty {
  min-height: 180px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  font-size: 13px;
}

@media (max-width: 1180px) {
  .landing-command {
    width: 360px;
  }
  .upload-entry-grid,
  .stats-row,
  .app-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 780px) {
  .landing-topbar {
    height: auto;
    min-height: 52px;
    flex-direction: column;
    align-items: stretch;
    padding: 10px 12px;
  }
  .landing-command {
    width: 100%;
    max-width: none;
  }
  .landing-admin-actions {
    width: 100%;
  }
  .landing-admin-actions button {
    flex: 1;
  }
  .content {
    padding: 0 14px 22px;
  }
  .landing {
    justify-content: flex-start;
    gap: 22px;
    padding: 24px 16px 28px;
  }
  .brand-glyph {
    width: 42px;
    height: 42px;
    font-size: 18px;
  }
  .brand-title {
    font-size: 30px;
  }
  .brand-title em {
    display: block;
    margin: 6px 0 0;
  }
  .brand-sub {
    font-size: 13px;
  }
  .mode-switcher {
    width: 100%;
    max-width: 760px;
    display: grid;
    grid-template-columns: minmax(0, 1fr);
  }
  .mode-tab {
    min-width: 0;
    padding: 8px 9px;
  }
  .mode-tab-zh,
  .mode-tab-dot {
    display: none;
  }
  .composer-toolbar {
    align-items: flex-start;
    flex-wrap: wrap;
  }
  .toolbar-spacer {
    display: none;
  }
  .seg-ctrl {
    order: 10;
  }
  .landing-submit {
    margin-left: auto;
  }
  .landing-footnotes {
    flex-wrap: wrap;
    justify-content: center;
    gap: 10px;
  }
  .legacy-entry-shell {
    margin-top: 10px;
    flex-direction: column;
    align-items: stretch;
  }
  .overview-shell {
    margin-top: 10px;
    flex-direction: column;
    align-items: stretch;
  }
  .upload-feature-card {
    padding: 18px;
  }
  .upload-title {
    font-size: 17px;
  }
  .upload-footnote,
  .template-item,
  .template-actions,
  .section-header {
    align-items: flex-start;
  }
  .template-inline-head {
    flex-direction: column;
    align-items: flex-start;
  }
  .entry-head {
    flex-direction: column;
    align-items: flex-start;
  }
  .entry-side-note {
    width: 100%;
    justify-content: center;
  }
  .hero {
    margin-top: 14px;
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }
  .hero-status {
    width: 100%;
    justify-content: flex-start;
  }
  .hero-title {
    font-size: 22px;
  }
  .hero-sub {
    font-size: 13px;
    line-height: 1.65;
  }
  .ai-entry-heading {
    font-size: 18px;
  }
  .ai-entry-visual {
    width: 76px;
    height: 76px;
  }
  .ai-entry-step {
    min-height: 40px;
  }
  .ai-entry-cta {
    min-height: 50px;
    font-size: 14px;
  }
  .landing-model-picker {
    width: 100%;
    justify-content: flex-start;
  }
  .landing-model-select {
    width: 100%;
  }
  .template-item {
    grid-template-columns: 1fr;
  }
  .template-actions {
    width: 100%;
  }
  .template-action {
    flex: 1;
  }
  .section-header {
    flex-direction: column;
    gap: 8px;
  }
}

@media (max-height: 880px) {
  .landing {
    justify-content: flex-start;
  }
}
</style>

<style>
html[data-theme="dark"] .main {
  --surface-strong: rgba(17, 19, 24, 0.96);
  --surface-soft: rgba(17, 19, 24, 0.88);
  --surface-muted: rgba(13, 17, 23, 0.94);
  --stroke-soft: rgba(148, 163, 184, 0.14);
  --stroke-strong: rgba(148, 163, 184, 0.24);
  --text-strong: rgba(248, 250, 252, 0.94);
  --text-secondary: rgba(203, 213, 225, 0.70);
  --text-muted: rgba(148, 163, 184, 0.50);
  --accent: #f8fafc;
  --accent-soft: rgba(124, 140, 255, 0.14);
  --shadow-soft: 0 18px 44px rgba(0, 0, 0, 0.42);
}

html[data-theme="dark"] .main,
html[data-theme="dark"] .bg,
html[data-theme="dark"] .landing {
  background: #090b10 !important;
  color: rgba(248, 250, 252, 0.94);
}

html[data-theme="dark"] .landing-topbar {
  background: rgba(9, 11, 16, 0.96) !important;
  border-bottom-color: rgba(148, 163, 184, 0.14) !important;
}

html[data-theme="dark"] .landing-admin-actions button {
  background: rgba(17, 19, 24, 0.86) !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: rgba(226, 232, 240, 0.82) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04) !important;
}
html[data-theme="dark"] .landing-admin-actions button:hover {
  background: rgba(26, 29, 36, 0.96) !important;
  border-color: rgba(124, 140, 255, 0.36) !important;
  color: rgba(248, 250, 252, 0.94) !important;
}

html[data-theme="dark"] .landing-breadcrumbs {
  color: rgba(203, 213, 225, 0.64);
}

html[data-theme="dark"] .landing-breadcrumbs strong,
html[data-theme="dark"] .brand-title,
html[data-theme="dark"] .brand-title em {
  color: rgba(248, 250, 252, 0.94) !important;
}

html[data-theme="dark"] .template-preview-dialog .el-dialog {
  background: #10141b !important;
  border: 1px solid rgba(148, 163, 184, 0.16) !important;
  box-shadow: 0 26px 80px rgba(0, 0, 0, 0.54) !important;
}

html[data-theme="dark"] .template-preview-dialog .el-dialog__header {
  border-bottom: 1px solid rgba(148, 163, 184, 0.14) !important;
}

html[data-theme="dark"] .template-preview-dialog .el-dialog__title {
  color: rgba(248, 250, 252, 0.94) !important;
}

html[data-theme="dark"] .template-preview-dialog .el-dialog__headerbtn .el-dialog__close {
  color: rgba(203, 213, 225, 0.62) !important;
}

html[data-theme="dark"] .template-preview-head {
  color: rgba(203, 213, 225, 0.72);
}

html[data-theme="dark"] .template-preview-meta,
html[data-theme="dark"] .template-preview-desc,
html[data-theme="dark"] .template-preview-empty {
  color: rgba(148, 163, 184, 0.72) !important;
}

html[data-theme="dark"] .template-preview-structured,
html[data-theme="dark"] .template-preview-body {
  background: #0f131a !important;
  border-color: rgba(148, 163, 184, 0.16) !important;
  color: rgba(226, 232, 240, 0.88) !important;
}

html[data-theme="dark"] .landing-command,
html[data-theme="dark"] .mode-switcher,
html[data-theme="dark"] .composer-shell,
html[data-theme="dark"] .seg-ctrl,
html[data-theme="dark"] .chip {
  background: #111318 !important;
  border-color: rgba(148, 163, 184, 0.16) !important;
  color: rgba(203, 213, 225, 0.66) !important;
  box-shadow: 0 0 0 0.5px rgba(148, 163, 184, 0.10);
}

html[data-theme="dark"] .landing-command:hover,
html[data-theme="dark"] .chip:hover {
  background: #1a1d24 !important;
  color: rgba(248, 250, 252, 0.94) !important;
}

html[data-theme="dark"] .landing-command kbd,
html[data-theme="dark"] .kbd-inline,
html[data-theme="dark"] .submit-kbd {
  background: #0d1117 !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: rgba(203, 213, 225, 0.62) !important;
}

html[data-theme="dark"] .landing-bg {
  background-image:
    radial-gradient(rgba(124, 140, 255, 0.12) 1px, transparent 1px),
    radial-gradient(rgba(52, 211, 153, 0.06) 1px, transparent 1px) !important;
}

html[data-theme="dark"] .brand-sub {
  color: rgba(203, 213, 225, 0.66) !important;
}

html[data-theme="dark"] .brand-eyebrow,
html[data-theme="dark"] .mode-tab.active {
  color: #b6c2ff !important;
}

html[data-theme="dark"] .mode-tab.active {
  border-color: rgba(138, 162, 255, 0.72) !important;
  background: rgba(124, 140, 255, 0.14) !important;
}

html[data-theme="dark"] .composer-shell {
  box-shadow: 0 18px 52px rgba(0, 0, 0, 0.42), 0 0 0 1px rgba(138, 162, 255, 0.14) !important;
}

html[data-theme="dark"] .composer-mode-bar,
html[data-theme="dark"] .composer-toolbar {
  background: #0d1117 !important;
  border-color: rgba(148, 163, 184, 0.14) !important;
}

html[data-theme="dark"] .composer-input {
  color: rgba(248, 250, 252, 0.94) !important;
}

html[data-theme="dark"] .composer-input::placeholder {
  color: rgba(148, 163, 184, 0.56) !important;
}

html[data-theme="dark"] .seg-btn {
  color: rgba(203, 213, 225, 0.64) !important;
}

html[data-theme="dark"] .seg-btn.active {
  background: #f8fafc !important;
  color: #090b10 !important;
}

html[data-theme="dark"] .landing-footnotes,
html[data-theme="dark"] .landing-footnotes button {
  color: rgba(148, 163, 184, 0.58) !important;
}

html[data-theme="dark"] .landing-footnotes button:hover {
  color: rgba(248, 250, 252, 0.94) !important;
}
</style>
