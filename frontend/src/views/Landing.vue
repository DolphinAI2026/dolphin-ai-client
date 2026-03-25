<template>
  <div class="landing">
    <!-- Nav -->
    <nav class="nav-bar">
      <div class="nav-left">
        <div class="logo-box">A</div>
        <span class="logo-text">aPaaS Builder AI</span>
      </div>
      <div class="nav-center">
        <button class="nav-link" @click="router.push('/apps')">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>
          我的应用
        </button>
        <button class="nav-link" @click="router.push('/coding')">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
          AI Coding
        </button>
        <!-- 组件市场 - 暂时隐藏
        <button class="nav-link" @click="router.push('/marketplace')">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
          组件市场
        </button>
        -->
        <button class="nav-link" @click="router.push('/platform-envs')">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          环境管理
        </button>
      </div>
      <div class="nav-right">
        <el-dropdown @command="handleUserCommand">
          <button class="user-btn">
            <div class="user-avatar">{{ userStore.user?.username?.charAt(0).toUpperCase() || 'U' }}</div>
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item disabled>
                <div class="user-info">
                  <div class="info-label">用户</div>
                  <div class="info-value">{{ userStore.user?.username }}</div>
                </div>
              </el-dropdown-item>
              <el-dropdown-item disabled v-if="userStore.tenantName">
                <div class="user-info">
                  <div class="info-label">租户</div>
                  <div class="info-value">{{ userStore.tenantName }}</div>
                </div>
              </el-dropdown-item>
              <el-dropdown-item divided command="logout">
                <span style="color: #ef4444;">退出登录</span>
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </nav>

    <!-- Main content -->
    <div class="main-scroll">
      <div class="center-area">
        <!-- Hero -->
        <div class="hero">
          <div class="hero-sparkle"><svg width="48" height="48" viewBox="0 0 24 24" fill="none"><path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" fill="url(#starGrad)" stroke="none"/><defs><linearGradient id="starGrad" x1="2" y1="2" x2="22" y2="22"><stop offset="0%" stop-color="#c4b5fd"/><stop offset="100%" stop-color="#7c3aed"/></linearGradient></defs></svg></div>
          <h1 class="hero-title">aPaaS Builder AI</h1>
          <p class="hero-desc">用 AI 构建企业级低代码应用</p>
        </div>

        <!-- Input box -->
        <div class="input-box">
          <div class="input-row">
            <label class="upload-btn" title="上传设计文档 (.md)">
              <input type="file" accept=".md" @change="handleDocUpload" hidden />
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
            </label>
            <input
              v-model="inputText"
              @keydown.enter="startChat"
              placeholder="描述你想要的应用，或上传设计文档..."
            />
            <button class="send-btn" @click="startChat" :disabled="!inputText.trim()">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
            </button>
          </div>
        </div>

        <!-- Templates -->
        <div class="section">
          <div class="section-header">
            <h3 class="section-title">从模板开始</h3>
            <el-button size="small" text @click="showTemplateManager = true">管理模板</el-button>
          </div>
          <div class="templates">
            <button v-for="t in templates" :key="t.code" class="tpl-card" :class="{ loading: templateLoading === t.code }" @click="startWithTemplate(t)">
              <div class="tpl-icon">
                <svg v-if="t.icon === 'users'" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#a78bfa" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
                <svg v-else-if="t.icon === 'wrench'" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#60a5fa" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>
                <svg v-else-if="t.icon === 'clipboard'" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#34d399" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1" ry="1"/><line x1="8" y1="10" x2="16" y2="10"/><line x1="8" y1="14" x2="16" y2="14"/><line x1="8" y1="18" x2="12" y2="18"/></svg>
              </div>
              <div class="tpl-name">{{ t.name }}</div>
              <div class="tpl-desc">{{ t.description }}</div>
            </button>
          </div>
        </div>

        <!-- 我的应用已移至导航栏 -->
      </div>
    </div>

    <TemplateManager v-model="showTemplateManager" @updated="reloadTemplates" />
    <ConnectModal v-model="previewStore.showConnectModal" />
    <ProjectSettingsModal
      v-model="showProjectModal"
      :project="editingProject"
      @saved="onProjectSaved"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { usePreviewStore } from '@/stores/preview'
import { useUserStore } from '@/stores/user'
import request from '@/utils/request'
import { applicationApi } from '@/api/application'
import { projectsApi, type Project } from '@/api/projects'
import ConnectModal from '@/components/ConnectModal.vue'
import ProjectSettingsModal from '@/components/ProjectSettingsModal.vue'
import TemplateManager from '@/components/TemplateManager.vue'
import type { MergedApplication } from '@/types'

const router = useRouter()
const previewStore = usePreviewStore()
const userStore = useUserStore()
const inputText = ref('')
const apps = ref<MergedApplication[]>([])
const projects = ref<Project[]>([])
const showProjectModal = ref(false)
const showTemplateManager = ref(false)
const editingProject = ref<Project | null>(null)

interface TemplateItem {
  code: string
  name: string
  icon: string
  description: string
  category: string
}
const templates = ref<TemplateItem[]>([])
const templateLoading = ref<string | null>(null) // 正在加载的模板 code

onMounted(async () => {
  try {
    projects.value = await projectsApi.list()
  } catch (e) { /* ignore */ }
  // 加载模板列表
  try {
    templates.value = await request.get<any, TemplateItem[]>('/templates')
  } catch (e) { /* ignore */ }
})

const openCreateProject = () => {
  editingProject.value = null
  showProjectModal.value = true
}

const openEditProject = (p: Project) => {
  editingProject.value = p
  showProjectModal.value = true
}

const onProjectSaved = async () => {
  showProjectModal.value = false
  projects.value = await projectsApi.list()
}

const goToProject = (p: Project) => {
  router.push(`/project/${p.id}`)
}

const deleteProject = async (p: Project) => {
  try {
    await ElMessageBox.confirm(`确定删除应用「${p.name}」？此操作不可撤销。`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
    await projectsApi.delete(p.id)
    ElMessage.success('删除成功')
    projects.value = await projectsApi.list()
  } catch (e) {
    // 取消或错误
  }
}

const reloadTemplates = async () => {
  try {
    templates.value = await request.get<any, TemplateItem[]>('/templates')
  } catch (e) { /* ignore */ }
}

const startChat = () => {
  const text = inputText.value.trim()
  if (!text) return
  router.push({ path: '/chat', query: { prompt: text } })
}

const startWithTemplate = async (tpl: TemplateItem) => {
  templateLoading.value = tpl.code
  try {
    // 获取模板完整 MD 内容
    const detail = await request.get<any, { content: string; name: string }>(`/templates/${tpl.code}`)
    // 构造 File 对象，复用已有文档上传流程
    const blob = new Blob([detail.content], { type: 'text/markdown' })
    const file = new File([blob], `${tpl.code}.md`, { type: 'text/markdown' })
    previewStore.pendingFile = file
    router.push('/chat')
  } catch (e) {
    ElMessage.error('加载模板失败')
  } finally {
    templateLoading.value = null
  }
}

const handleDocUpload = (e: Event) => {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  target.value = ''

  if (!file.name.endsWith('.md')) {
    ElMessage.warning('目前仅支持 .md 格式文件')
    return
  }

  // 存文件到 store，跳转到 chat 页面，由 ChatPage 处理解析
  previewStore.pendingFile = file
  router.push('/chat')
}

const handleUserCommand = (command: string) => {
  if (command === 'logout') {
    userStore.logout()
    ElMessage.success('已退出登录')
    router.push('/login')
  }
}
</script>

<style scoped>
/* ── CSS Variables ── */
.landing {
  --bg-base: #141418;
  --bg-nav: rgba(26, 26, 32, 0.82);
  --bg-card: #1e1e26;
  --bg-card-hover: #28283a;
  --bg-input: #252530;
  --bg-elevated: #28283a;
  --border-subtle: rgba(255, 255, 255, 0.08);
  --border-hover: rgba(255, 255, 255, 0.14);
  --text-primary: rgba(255, 255, 255, 0.92);
  --text-secondary: rgba(255, 255, 255, 0.55);
  --text-tertiary: rgba(255, 255, 255, 0.35);
  --accent-gradient: linear-gradient(135deg, #7c3aed, #6366f1);
  --accent-purple: #7c3aed;
  --accent-indigo: #6366f1;
  --accent-glow: rgba(124, 58, 237, 0.18);
  --radius-sm: 8px;
  --radius-md: 12px;
  --radius-lg: 16px;
  --radius-xl: 20px;
}

/* ── Layout ── */
.landing {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-base);
  color: var(--text-primary);
}

.main-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 0 24px 60px;
}

.center-area {
  max-width: 800px;
  width: 100%;
  margin: 0 auto;
}

/* ── Nav ── */
.nav-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 24px;
  background: var(--bg-nav);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-bottom: 1px solid var(--border-subtle);
  position: sticky;
  top: 0;
  z-index: 100;
}

.nav-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.logo-box {
  width: 30px;
  height: 30px;
  background: var(--accent-gradient);
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-weight: 700;
  font-size: 13px;
}

.logo-text {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: -0.01em;
}

/* ── Nav Center Links ── */
.nav-center {
  display: flex;
  align-items: center;
  gap: 4px;
}

.nav-link {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border: none;
  background: none;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  border-radius: var(--radius-sm);
  transition: all 0.2s;
}

.nav-link:hover {
  color: var(--text-primary);
  background: rgba(255, 255, 255, 0.06);
}

.nav-right {
  display: flex;
  align-items: center;
}

.user-btn {
  display: flex;
  align-items: center;
  background: none;
  border: none;
  cursor: pointer;
  padding: 4px;
  border-radius: 50%;
  transition: box-shadow 0.2s;
}

.user-btn:hover {
  box-shadow: 0 0 0 2px var(--border-hover);
}

.user-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--accent-gradient);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 600;
}

.user-info { padding: 4px 0; }
.info-label { font-size: 11px; color: var(--text-tertiary); margin-bottom: 2px; }
.info-value { font-size: 13px; color: var(--text-primary); font-weight: 500; }

/* ── Hero ── */
.hero {
  text-align: center;
  padding: 56px 0 40px;
  position: relative;
}

/* Purple ambient glow behind hero */
.hero::before {
  content: '';
  position: absolute;
  top: 10%;
  left: 50%;
  transform: translateX(-50%);
  width: 480px;
  height: 260px;
  background: radial-gradient(ellipse at center, rgba(124, 58, 237, 0.12) 0%, rgba(99, 102, 241, 0.06) 40%, transparent 70%);
  pointer-events: none;
  z-index: 0;
}

.hero-sparkle {
  font-size: 40px;
  margin-bottom: 16px;
  filter: saturate(1.2);
  position: relative;
  z-index: 1;
}

.hero-title {
  font-size: 36px;
  font-weight: 700;
  letter-spacing: -0.02em;
  margin: 0 0 10px;
  background: linear-gradient(135deg, #e0e0e0 0%, #ffffff 40%, #c4b5fd 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  position: relative;
  z-index: 1;
}

.hero-desc {
  font-size: 16px;
  color: var(--text-secondary);
  margin: 0;
  font-weight: 400;
  position: relative;
  z-index: 1;
}

/* ── Input Box ── */
.input-box {
  margin-bottom: 48px;
}

.input-row {
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--bg-input);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-xl);
  padding: 10px 10px 10px 20px;
  transition: border-color 0.2s, box-shadow 0.2s;
  min-height: 56px;
}

.input-row:focus-within {
  border-color: rgba(124, 58, 237, 0.45);
  box-shadow: 0 0 0 3px var(--accent-glow);
}

.input-row input {
  flex: 1;
  border: none;
  outline: none;
  font-size: 15px;
  color: var(--text-primary);
  background: transparent;
  min-width: 0;
}

.input-row input::placeholder {
  color: var(--text-tertiary);
}

.upload-btn {
  cursor: pointer;
  padding: 6px;
  border-radius: var(--radius-sm);
  transition: background 0.2s;
  color: var(--text-tertiary);
  display: flex;
  align-items: center;
  justify-content: center;
}

.upload-btn:hover {
  background: var(--bg-elevated);
  color: var(--text-secondary);
}

.send-btn {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-md);
  border: none;
  background: var(--accent-gradient);
  color: #fff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: opacity 0.2s, transform 0.15s;
}

.send-btn:hover:not(:disabled) {
  opacity: 0.9;
  transform: scale(1.04);
}

.send-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

/* ── Entry Cards ── */
.entry-cards {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-bottom: 48px;
}

.entry-card {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  padding: 20px;
  cursor: pointer;
  transition: transform 0.2s, border-color 0.2s, box-shadow 0.2s, background 0.2s;
  display: flex;
  align-items: center;
  gap: 14px;
}

.entry-card:hover {
  transform: translateY(-2px);
  background: var(--bg-card-hover);
  border-color: var(--border-hover);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
}

.entry-icon {
  width: 44px;
  height: 44px;
  border-radius: var(--radius-md);
  background: var(--bg-elevated);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  flex-shrink: 0;
}

.entry-body {
  flex: 1;
  min-width: 0;
}

.entry-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 3px;
}

.entry-desc {
  font-size: 12px;
  color: var(--text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.entry-arrow {
  color: var(--text-tertiary);
  flex-shrink: 0;
  transition: transform 0.2s;
}

.entry-card:hover .entry-arrow {
  transform: translateX(2px);
  color: var(--text-secondary);
}

/* ── Sections ── */
.section {
  margin-bottom: 48px;
}

.section-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin: 0 0 16px;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.section-header .section-title {
  margin: 0;
}

/* ── Templates ── */
.templates {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.tpl-card {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  padding: 18px;
  text-align: left;
  cursor: pointer;
  transition: transform 0.2s, border-color 0.3s, box-shadow 0.3s, background 0.2s;
  color: inherit;
}

.tpl-card:hover {
  transform: translateY(-2px);
  background: var(--bg-card-hover);
  border-color: rgba(124, 58, 237, 0.35);
  box-shadow: 0 6px 24px rgba(124, 58, 237, 0.1), 0 4px 16px rgba(0, 0, 0, 0.2);
}

.tpl-icon {
  font-size: 26px;
  margin-bottom: 10px;
}

.tpl-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.tpl-desc {
  font-size: 11px;
  color: var(--text-tertiary);
  margin-top: 4px;
  line-height: 1.5;
}

/* ── Create Button ── */
.create-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 500;
  color: var(--accent-purple);
  background: none;
  border: 1px solid rgba(124, 58, 237, 0.25);
  border-radius: var(--radius-sm);
  padding: 6px 14px;
  cursor: pointer;
  transition: background 0.2s, border-color 0.2s;
}

.create-btn:hover {
  background: rgba(124, 58, 237, 0.1);
  border-color: rgba(124, 58, 237, 0.4);
}

/* ── Project List ── */
.app-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.app-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  padding: 14px 18px;
  cursor: pointer;
  transition: transform 0.2s, border-color 0.2s, box-shadow 0.2s, background 0.2s;
}

.app-row:hover {
  transform: translateY(-1px);
  background: var(--bg-card-hover);
  border-color: var(--border-hover);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.18);
}

.app-row-left {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
}

.app-status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.app-status-dot.connected {
  background: #10b981;
  box-shadow: 0 0 8px rgba(16, 185, 129, 0.4);
}

.app-status-dot.disconnected {
  background: rgba(255, 255, 255, 0.15);
}

.app-info {
  min-width: 0;
}

.app-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.app-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
}

.conn-tag {
  font-size: 10px;
  padding: 1px 8px;
  border-radius: 10px;
  font-weight: 500;
  line-height: 1.6;
}

.conn-tag.linked {
  background: rgba(16, 185, 129, 0.12);
  color: #34d399;
}

.conn-tag.unlinked {
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-tertiary);
}

.app-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 3px;
}

.app-platform {
  font-size: 12px;
  color: var(--text-secondary);
}

.app-date {
  font-size: 11px;
  color: var(--text-tertiary);
}

.settings-btn {
  background: none;
  border: none;
  color: var(--text-tertiary);
  cursor: pointer;
  padding: 6px;
  border-radius: var(--radius-sm);
  transition: background 0.2s, color 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
}

.settings-btn:hover {
  background: var(--bg-elevated);
  color: var(--text-secondary);
}
.app-row-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}
.delete-btn:hover {
  color: #f56c6c !important;
  background: rgba(245, 108, 108, 0.1) !important;
}

/* ── Empty State ── */
.empty-hint {
  text-align: center;
  color: var(--text-tertiary);
  font-size: 13px;
  padding: 40px 20px;
  background: var(--bg-card);
  border: 1px dashed rgba(255, 255, 255, 0.1);
  border-radius: var(--radius-md);
}

.empty-icon {
  font-size: 32px;
  margin-bottom: 10px;
  opacity: 0.5;
}

/* ── Scrollbar ── */
.main-scroll::-webkit-scrollbar {
  width: 6px;
}

.main-scroll::-webkit-scrollbar-track {
  background: transparent;
}

.main-scroll::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.08);
  border-radius: 3px;
}

.main-scroll::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.15);
}
</style>
