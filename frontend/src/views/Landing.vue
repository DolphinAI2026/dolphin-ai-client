<template>
  <WorkbenchShell>
    <main class="main">
      <div class="bg"></div>
      <div class="content">
        <div class="hero">
          <div class="hero-mark" aria-hidden="true">
            <svg width="34" height="34" viewBox="0 0 24 24" fill="none">
              <path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 17l-6.2 4.3 2.4-7.4L2 9.4h7.6L12 2z" fill="#7D72F6"/>
            </svg>
          </div>
          <div class="hero-title">aPaaS Builder AI</div>
          <div class="hero-sub">两种搭建路径，覆盖从标准文档导入到 AI 对话生成的完整应用设计流程</div>
        </div>

        <div class="upload-workbench upload-entry-grid">
          <section class="upload-feature-card">
            <div class="entry-head">
              <div class="entry-copy">
                <div class="card-tag">设计文档</div>
                <div class="upload-title">上传 Markdown 设计文档</div>
                <div class="entry-subtitle">
                  已有标准设计文档时，从这里直接进入解析和搭建流程。
                </div>
              </div>
              <div class="entry-side-note">模板预览 / 拖拽上传 / 直接解析</div>
            </div>

            <div
              v-if="templateFiles.length"
              class="template-inline-section"
              :class="{ dragging: uploadDragging }"
              @dragover.prevent="uploadDragging = true"
              @dragleave.prevent="uploadDragging = false"
              @drop.prevent="handleFileDrop"
            >
              <div class="template-inline-head">
                <div class="template-inline-label">默认模板</div>
                <div class="landing-model-picker">
                  <span class="landing-model-label">解析模型</span>
                  <el-select
                    v-model="selectedLandingModelId"
                    class="landing-model-select"
                    popper-class="model-select-dropdown"
                    size="small"
                    placeholder="选择模型"
                    :loading="builderModelLoading"
                    :disabled="builderModelLoading || builderModelOptions.length === 0"
                  >
                    <el-option
                      v-for="option in builderModelOptions"
                      :key="option.id"
                      :label="formatBuilderModelOption(option)"
                      :value="option.id"
                    >
                      <div class="builder-model-option-row">
                        <span class="builder-model-option-name">{{ option.config_name }}</span>
                        <span class="builder-model-option-meta">{{ option.provider }} / {{ option.model }}</span>
                      </div>
                    </el-option>
                  </el-select>
                  <span class="landing-model-hint">{{ landingModelHint }}</span>
                </div>
              </div>

              <article v-for="template in templateFiles" :key="template.code" class="template-item template-item-inline template-item-compact">
                <div class="template-icon" aria-hidden="true">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                    <path d="M8 4.5h6l4 4V19a1.5 1.5 0 0 1-1.5 1.5h-8A1.5 1.5 0 0 1 7 19V6A1.5 1.5 0 0 1 8.5 4.5Z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" />
                    <path d="M14 4.5V9h4" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" />
                    <path d="M9.5 13h5M9.5 16h5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
                  </svg>
                </div>

                <div class="template-main">
                  <div class="template-topline">
                    <div class="template-name">{{ template.name }}</div>
                    <span class="template-category">{{ template.category || '通用模板' }}</span>
                  </div>
                  <div class="template-summary">{{ template.description || '用于快速搭建设计文档结构。' }}</div>
                  <div class="template-meta">
                    <span>{{ template.filename }}</span>
                    <span>Markdown</span>
                    <span>{{ formatTemplateUpdatedAt(template.updated_at) }}</span>
                  </div>
                </div>

                <div class="template-actions">
                  <button class="template-action ghost" type="button" @click="previewTemplate(template)">预览</button>
                  <button class="template-action ghost" type="button" @click="downloadTemplate(template)">下载模板</button>
                  <label class="template-action solid template-upload-btn">
                    上传文档
                    <input type="file" accept=".md,text/markdown" @change="handleDocUpload" hidden />
                  </label>
                </div>
              </article>
            </div>

            <div v-else class="template-empty template-empty-inline">
              暂无可展示的模板文件，请先在模板管理中补充模板。
            </div>

            <div class="upload-footnote">
              <span>仅支持 Markdown 功能设计文档，上传后会自动跳转到解析页面。</span>
            </div>
          </section>

          <section class="upload-feature-card ai-entry-card">
            <div class="entry-head entry-head-compact">
              <div class="entry-copy">
                <div class="card-tag">AI生成</div>
                <div class="upload-title">通过 AI 对话生成设计文档</div>
              </div>
              <div class="entry-side-note">从模糊需求到标准文档</div>
            </div>
            <div class="ai-entry-body">
              <div class="ai-entry-visual" aria-hidden="true">
                <div class="ai-orbit ai-orbit-large"></div>
                <div class="ai-orbit ai-orbit-small"></div>
                <div class="ai-entry-core">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                    <path d="M12 3 14.4 9.6 21 12l-6.6 2.4L12 21l-2.4-6.6L3 12l6.6-2.4L12 3Z" fill="currentColor"/>
                  </svg>
                </div>
              </div>
              <div class="ai-entry-copy">
                <div class="ai-entry-heading">从需求对话开始</div>
                <div class="ai-entry-desc">
                  用对话先把业务目标、角色、模型和表单梳理清楚，再由系统自动生成标准设计文档并进入搭建流程。
                </div>
              </div>
              <div class="ai-entry-steps">
                <div class="ai-entry-step">
                  <span class="ai-entry-step-index">01</span>
                  <span class="ai-entry-step-text">逐步补充需求，不用一次写全</span>
                </div>
                <div class="ai-entry-step">
                  <span class="ai-entry-step-index">02</span>
                  <span class="ai-entry-step-text">自动生成标准设计文档</span>
                </div>
                <div class="ai-entry-step">
                  <span class="ai-entry-step-index">03</span>
                  <span class="ai-entry-step-text">确认后继续进入应用搭建</span>
                </div>
              </div>
              <div class="ai-entry-actions">
                <button class="ai-entry-cta" type="button" @click="startAIGenerate">
                  <span>进入 AI 生成</span>
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                    <path d="M3 8h9" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
                    <path d="m8.5 3.5 4 4-4 4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>
                  </svg>
                </button>
                <div class="ai-entry-note">进入对话模式后，可边聊边生成设计文档。</div>
              </div>
            </div>
          </section>
        </div>

        <div class="body-content">
          <div class="stats-row">
            <div class="stat-card">
              <div class="stat-label">已搭建应用</div>
              <div class="stat-num">{{ totalAppsCount }}</div>
            </div>
            <div class="stat-card">
              <div class="stat-label">AI 对话次数</div>
              <div class="stat-num">{{ totalConversationCount }}</div>
            </div>
            <div class="stat-card">
              <div class="stat-label">已生成模块数</div>
              <div class="stat-num">{{ generatedModules }}</div>
            </div>
          </div>

          <div>
            <div class="section-header">
              <span class="section-title">已搭建应用</span>
              <div class="section-actions">
                <button class="import-link" @click="showImportDialog = true">
                  <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M6 1v8M2.5 5.5L6 9l3.5-3.5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/><path d="M1 11h10" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>
                  从平台导入
                </button>
                <button class="view-all-link" @click="navigateTo('/apps')">查看全部 →</button>
              </div>
            </div>
            <div class="app-grid">
              <button v-for="(app,idx) in recentApps.slice(0,6)" :key="app.id" class="app-card" @click="openApp(app)">
                <div class="app-card-header">
                  <div class="app-dot" :class="idx===1 ? 'teal' : idx===2 ? 'amber' : 'purple'">{{ (app.label || 'A').slice(0, 1).toUpperCase() }}</div>
                  <div>
                    <div class="app-name">{{ app.label }}</div>
                    <div class="app-time">{{ app.timeLabel }}更新</div>
                  </div>
                </div>
                <span class="app-status" :class="app.status==='processing' ? 'building' : 'done'">{{ app.status==='processing' ? '构建中' : '已生成' }}</span>
              </button>
            </div>
          </div>
        </div>
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
    <div v-else-if="templatePreviewParsedDoc" class="template-preview-structured">
      <pre v-if="templatePreviewIntro" class="template-preview-body template-preview-intro">{{ templatePreviewIntro }}</pre>
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
import { ElMessage, ElMessageBox } from 'element-plus'
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
const uploadDragging = ref(false)
const templateCache = new Map<string, TemplateDetail>()
const builderModelOptions = ref<BuilderModelOption[]>([])
const builderModelLoading = ref(false)
const selectedLandingModelId = ref<number | null>(null)
const templatePreviewIntro = computed(() => {
  const content = templatePreview.value?.content || ''
  if (!content) return ''
  const normalized = content.replace(/\r\n/g, '\n')
  const marker = normalized.search(/^##\s+[一二三四五六七八九十]+、/m)
  if (marker <= 0) return ''
  return normalized.slice(0, marker).trim()
})

const userInitial = computed(() => (userStore.user?.username || 'A').slice(0, 1))
const userDisplayName = computed(() => (userStore.user as any)?.nickname || userStore.user?.username || 'admin')
const defaultLandingModelId = computed(() =>
  builderModelOptions.value.find(option => option.is_default)?.id
  ?? builderModelOptions.value[0]?.id
  ?? null
)
const landingModelHint = computed(() => {
  if (builderModelLoading.value) return '正在加载模型...'
  if (builderModelOptions.value.length === 0) return '未配置可用模型'
  return '上传时使用当前模型'
})

function formatDate(dateStr: string) {
  if (!dateStr) return '今天'
  const d = new Date(dateStr)
  return `${d.getMonth() + 1}月${d.getDate()}日`
}

function navigateTo(path: string) {
  router.push(path)
}

function isMarkdownFile(file: File) {
  return /\.md$/i.test(file.name)
}

function normalizeLandingModelId(modelId?: number | null) {
  const ids = new Set(builderModelOptions.value.map(option => option.id))
  if (modelId != null && ids.has(modelId)) return modelId
  return defaultLandingModelId.value
}

function formatBuilderModelOption(option: BuilderModelOption) {
  return option.config_name
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

function startDocUpload(file: File) {
  if (!isMarkdownFile(file)) {
    ElMessage.warning('当前仅支持上传 .md 格式的功能设计文档')
    return
  }
  previewStore.pendingBuilderModelId = selectedLandingModelId.value
  previewStore.pendingFile = file
  router.push('/chat')
}

function startAIGenerate() {
  previewStore.pendingBuilderModelId = selectedLandingModelId.value
  router.push({ path: '/chat', query: { mode: 'requirements' } })
}

function handleDocUpload(e: Event) {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  target.value = ''
  if (!file) return
  startDocUpload(file)
}

function handleFileDrop(e: DragEvent) {
  uploadDragging.value = false
  const file = e.dataTransfer?.files?.[0]
  if (!file) return
  startDocUpload(file)
}

function openApp(app: AppItem) {
  router.push({ path: '/chat', query: { app_id: String(app.id) } })
}

function sortTemplateFiles(list: TemplateFile[]) {
  return [...list].sort((a, b) => {
    const timeDiff = new Date(b.updated_at || 0).getTime() - new Date(a.updated_at || 0).getTime()
    if (timeDiff !== 0) return timeDiff
    return a.name.localeCompare(b.name, 'zh-CN')
  })
}

function formatTemplateUpdatedAt(value?: string) {
  if (!value) return '最近更新未知'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '最近更新未知'
  const yyyy = date.getFullYear()
  const mm = `${date.getMonth() + 1}`.padStart(2, '0')
  const dd = `${date.getDate()}`.padStart(2, '0')
  const hh = `${date.getHours()}`.padStart(2, '0')
  const mi = `${date.getMinutes()}`.padStart(2, '0')
  return `最近更新 ${yyyy}-${mm}-${dd} ${hh}:${mi}`
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

async function previewTemplate(template: TemplateFile) {
  try {
    templatePreviewVisible.value = true
    templatePreviewLoading.value = true
    templatePreviewParsedDoc.value = null
    templatePreview.value = await getTemplateDetail(template)
    templatePreviewParsedDoc.value = standardDocMdToStructuredDoc(templatePreview.value.content)
  } catch (error: any) {
    if (!templatePreview.value) {
      templatePreviewVisible.value = false
      handleError(error, { fallback: '加载模板失败' })
      return
    }
  } finally {
    templatePreviewLoading.value = false
  }
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

async function logoutWithConfirm() {
  try {
    await ElMessageBox.confirm('确认退出当前账号吗？', '退出登录', {
      confirmButtonText: '退出登录',
      cancelButtonText: '取消',
      type: 'warning'
    })
    userStore.logout()
    router.push('/login')
  } catch {
    // 用户取消
  }
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
  --surface-strong: rgba(255, 255, 255, 0.88);
  --surface-soft: rgba(255, 255, 255, 0.72);
  --surface-muted: rgba(245, 247, 255, 0.88);
  --stroke-soft: rgba(83, 74, 183, 0.16);
  --stroke-strong: rgba(83, 74, 183, 0.26);
  --text-strong: #26215C;
  --text-secondary: #534AB7;
  --text-muted: #716CB2;
  --accent: #4B43A2;
  --accent-soft: #EEEDFE;
  --shadow-soft: 0 18px 40px rgba(78, 71, 147, 0.08);
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
}
.bg { position: absolute; inset: 0; background: linear-gradient(160deg, #EEEDFE 0%, #E6F1FB 45%, #E1F5EE 100%); z-index: 0; }
.content { flex: 1; overflow-y: auto; position: relative; z-index: 1; }

.hero {
  padding: 28px 24px 18px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}
.hero-mark {
  width: 58px;
  height: 58px;
  border-radius: 20px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.92), rgba(238, 237, 254, 0.88));
  box-shadow:
    inset 0 0 0 1px rgba(125, 114, 246, 0.12),
    0 18px 36px rgba(103, 96, 180, 0.10);
}
.hero-title {
  font-size: 25px;
  font-weight: 700;
  color: var(--text-strong);
  letter-spacing: -0.04em;
}
.hero-sub {
  max-width: 680px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-secondary);
  opacity: 0.88;
}

.upload-workbench {
  padding: 0 24px;
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

.body-content { padding: 14px 24px 22px; display: flex; flex-direction: column; gap: 16px; }
.stats-row { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.stat-card { background: rgba(255,255,255,0.78); border: 0.5px solid rgba(255,255,255,0.92); border-radius: 20px; padding: 14px 16px; box-shadow: 0 14px 34px rgba(78, 71, 147, 0.05); }
.stat-label { font-size: 11px; color: #534AB7; margin-bottom: 5px; opacity: 0.8; }
.stat-num { font-size: 20px; font-weight: 500; color: #26215C; }
.stat-sub { font-size: 11px; color: #3B6D11; margin-top: 2px; }

.section-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.section-title { font-size: 13px; font-weight: 500; color: #26215C; }
.section-actions { display: flex; align-items: center; gap: 12px; }
.import-link { border: none; background: transparent; color: #6d73d5; font-size: 12px; font-weight: 500; cursor: pointer; padding: 0; display: flex; align-items: center; gap: 4px; }
.import-link:hover { color: #534AB7; }
.view-all-link { border: none; background: transparent; color: #6d73d5; font-size: 12px; font-weight: 500; cursor: pointer; padding: 0; }
.view-all-link:hover { color: #534AB7; }
.app-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.app-card { background: rgba(255,255,255,0.78); border: 0.5px solid rgba(255,255,255,0.92); border-radius: 20px; padding: 14px; cursor: pointer; text-align: left; box-shadow: 0 14px 34px rgba(78, 71, 147, 0.04); }
.app-card-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.app-dot { width: 28px; height: 28px; border-radius: 7px; display: flex; align-items: center; justify-content: center; font-size: 13px; flex-shrink: 0; }
.app-dot { font-weight: 700; color: #4c419f; }
.app-dot.purple { background: #EEEDFE; }
.app-dot.teal { background: #E1F5EE; }
.app-dot.amber { background: #FAEEDA; }
.app-name { font-size: 12px; font-weight: 500; color: #26215C; }
.app-time { font-size: 11px; color: #534AB7; opacity: 0.6; margin-top: 1px; }
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
  .upload-entry-grid,
  .stats-row,
  .app-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 780px) {
  .hero,
  .upload-workbench,
  .body-content {
    padding-left: 18px;
    padding-right: 18px;
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
    padding-top: 26px;
    gap: 8px;
  }
  .hero-mark {
    width: 54px;
    height: 54px;
    border-radius: 20px;
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
</style>
