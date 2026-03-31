<template>
  <div class="landing">
    <!-- Nav -->
    <nav class="nav-bar">
      <div class="nav-left">
        <div class="logo-box">A</div>
        <span class="logo-text">aPaaS Builder AI</span>
      </div>
      <div class="nav-center">
        <el-dropdown @command="handleNewApp" trigger="click">
          <button class="nav-link nav-link-primary">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            新建应用
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="requirements">
                <div class="new-app-item">
                  <strong>从需求分析开始</strong>
                  <span>与 AI 对话梳理需求，生成设计文档</span>
                </div>
              </el-dropdown-item>
              <el-dropdown-item command="direct">
                <div class="new-app-item">
                  <strong>直接描述搭建</strong>
                  <span>跳过需求分析，直接进入搭建</span>
                </div>
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <button class="nav-link" @click="router.push('/apps')">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>
          我的应用
        </button>
        <button class="nav-link" @click="router.push('/coding')">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
          AI Coding
        </button>
        <button class="nav-link" @click="router.push('/platform-envs')">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          环境管理
        </button>
      </div>
      <div class="nav-right">
        <ThemeToggle />
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
          <div class="hero-sparkle"><svg width="48" height="48" viewBox="0 0 24 24" fill="none"><path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" fill="url(#starGrad)" stroke="none"/><defs><linearGradient id="starGrad" x1="2" y1="2" x2="22" y2="22"><stop offset="0%" stop-color="#c7d2fe"/><stop offset="100%" stop-color="#6366f1"/></linearGradient></defs></svg></div>
          <h1 class="hero-title">aPaaS Builder AI</h1>
          <p class="hero-desc">用 AI 构建企业级低代码应用</p>
        </div>

        <!-- Input box -->
        <div class="input-box">
          <div class="input-row">
            <label class="upload-btn" title="上传需求文档 (.md/.pdf/.docx/.txt)">
              <input type="file" accept=".md,.pdf,.docx,.doc,.txt,.markdown" @change="handleDocUpload" hidden />
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

        <!-- 历史对话 -->
        <div v-if="recentSessions.length > 0" class="section">
          <div class="section-header">
            <h3 class="section-title">最近对话</h3>
            <button class="see-all-btn" @click="router.push('/requirements')">查看全部</button>
          </div>
          <div class="history-list">
            <div
              v-for="s in recentSessions"
              :key="s.id"
              class="history-item"
              @click="router.push(`/requirements/${s.id}`)"
            >
              <div class="history-icon">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
              </div>
              <div class="history-info">
                <span class="history-title">{{ s.title }}</span>
                <span class="history-meta">{{ formatDate(s.updated_at) }}</span>
              </div>
              <el-tag v-if="s.has_doc" size="small" type="success" style="flex-shrink:0">已生成</el-tag>
            </div>
          </div>
        </div>
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
import { ElMessage } from 'element-plus'
import { usePreviewStore } from '@/stores/preview'
import { useUserStore } from '@/stores/user'
import request from '@/utils/request'
import { projectsApi, type Project } from '@/api/projects'
import ConnectModal from '@/components/ConnectModal.vue'
import ProjectSettingsModal from '@/components/ProjectSettingsModal.vue'
import TemplateManager from '@/components/TemplateManager.vue'
import ThemeToggle from '@/components/ThemeToggle.vue'
import { requirementsApi, type RequirementsSession } from '@/api/requirements'

const router = useRouter()
const previewStore = usePreviewStore()
const userStore = useUserStore()
const inputText = ref('')
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
const templateLoading = ref<string | null>(null)
const recentSessions = ref<RequirementsSession[]>([])

function formatDate(dateStr: string): string {
  const d = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小时前`
  return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}

onMounted(async () => {
  try {
    projects.value = await projectsApi.list()
  } catch (e) { /* ignore */ }
  try {
    templates.value = await request.get<any, TemplateItem[]>('/templates')
  } catch (e) { /* ignore */ }
  try {
    const sessions = await requirementsApi.listSessions()
    recentSessions.value = sessions.slice(0, 6)
  } catch (e) { /* ignore */ }
})

const onProjectSaved = async () => {
  showProjectModal.value = false
  projects.value = await projectsApi.list()
}

const reloadTemplates = async () => {
  try {
    templates.value = await request.get<any, TemplateItem[]>('/templates')
  } catch (e) { /* ignore */ }
}

const startChat = () => {
  const text = inputText.value.trim()
  if (!text) return
  // 先经过需求分析页面确认
  router.push({ path: '/requirements', query: { prompt: text } })
}

const startWithTemplate = async (tpl: TemplateItem) => {
  templateLoading.value = tpl.code
  try {
    // 获取模板完整 MD 内容
    const detail = await request.get<any, { content: string; name: string }>(`/templates/${tpl.code}`)
    // 构造 File 对象，先经过需求分析页面确认
    const blob = new Blob([detail.content], { type: 'text/markdown' })
    const file = new File([blob], `${tpl.code}.md`, { type: 'text/markdown' })
    previewStore.pendingFile = file
    router.push('/requirements')
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

  // 先经过需求分析页面确认（支持所有格式）
  previewStore.pendingFile = file
  router.push('/requirements')
}

const handleNewApp = (command: string) => {
  if (command === 'requirements') {
    router.push('/requirements')
  } else if (command === 'direct') {
    router.push('/chat')
  }
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
/* ── Layout ── */
.landing {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--t-bg-base);
  color: var(--t-text-primary);
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
  background: var(--t-bg-nav);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-bottom: 1px solid var(--t-border-subtle);
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
  background: var(--t-brand-gradient);
  border-radius: var(--t-radius-sm);
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
  color: var(--t-text-primary);
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
  color: var(--t-text-secondary);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  border-radius: var(--t-radius-sm);
  transition: all 0.2s;
}

.nav-link:hover {
  color: var(--t-text-primary);
  background: var(--t-border-subtle);
}

.nav-link-primary {
  background: var(--t-brand-gradient);
  color: #fff !important;
  padding: 6px 14px;
}
.nav-link-primary:hover {
  opacity: 0.9;
  background: var(--t-brand-gradient) !important;
  color: #fff !important;
}

.new-app-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 2px 0;
}
.new-app-item strong {
  font-size: 13px;
  color: var(--t-text-primary);
}
.new-app-item span {
  font-size: 11px;
  color: var(--t-text-secondary);
}

.nav-right {
  display: flex;
  align-items: center;
  gap: 12px;
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
  box-shadow: 0 0 0 2px var(--t-border-strong);
}

.user-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--t-brand-gradient);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 600;
}

.user-info { padding: 4px 0; }
.info-label { font-size: 11px; color: var(--t-text-muted); margin-bottom: 2px; }
.info-value { font-size: 13px; color: var(--t-text-primary); font-weight: 500; }

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
  background: radial-gradient(ellipse at center, var(--t-brand-subtle) 0%, var(--t-brand-subtle) 40%, transparent 70%);
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
  position: relative;
  z-index: 1;
}
html[data-theme="dark"] .hero-title {
  background: linear-gradient(135deg, #e0e0e0 0%, #ffffff 40%, var(--t-brand-light) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
html[data-theme="light"] .hero-title {
  background: linear-gradient(135deg, #1e293b 0%, #334155 40%, var(--t-brand) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.hero-desc {
  font-size: 16px;
  color: var(--t-text-secondary);
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
  background: var(--t-bg-input);
  border: 1px solid var(--t-border-subtle);
  border-radius: var(--t-radius-xl);
  padding: 10px 10px 10px 20px;
  transition: border-color 0.2s, box-shadow 0.2s;
  min-height: 56px;
}

.input-row:focus-within {
  border-color: var(--t-brand-glow);
  box-shadow: 0 0 0 3px var(--t-brand-glow);
}

.input-row input {
  flex: 1;
  border: none;
  outline: none;
  font-size: 15px;
  color: var(--t-text-primary);
  background: transparent;
  min-width: 0;
}

.input-row input::placeholder {
  color: var(--t-text-muted);
}

.upload-btn {
  cursor: pointer;
  padding: 6px;
  border-radius: var(--t-radius-sm);
  transition: background 0.2s;
  color: var(--t-text-muted);
  display: flex;
  align-items: center;
  justify-content: center;
}

.upload-btn:hover {
  background: var(--t-bg-panel-hover);
  color: var(--t-text-secondary);
}

.send-btn {
  width: 40px;
  height: 40px;
  border-radius: var(--t-radius-md);
  border: none;
  background: var(--t-brand-gradient);
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
  background: var(--t-bg-panel);
  border: 1px solid var(--t-border-subtle);
  border-radius: var(--t-radius-lg);
  padding: 20px;
  cursor: pointer;
  transition: transform 0.2s, border-color 0.2s, box-shadow 0.2s, background 0.2s;
  display: flex;
  align-items: center;
  gap: 14px;
}

.entry-card:hover {
  transform: translateY(-2px);
  background: var(--t-bg-panel-hover);
  border-color: var(--t-border-strong);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
}

.entry-icon {
  width: 44px;
  height: 44px;
  border-radius: var(--t-radius-md);
  background: var(--t-bg-panel-hover);
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
  color: var(--t-text-primary);
  margin-bottom: 3px;
}

.entry-desc {
  font-size: 12px;
  color: var(--t-text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.entry-arrow {
  color: var(--t-text-muted);
  flex-shrink: 0;
  transition: transform 0.2s;
}

.entry-card:hover .entry-arrow {
  transform: translateX(2px);
  color: var(--t-text-secondary);
}

/* ── Sections ── */
.section {
  margin-bottom: 48px;
}

.section-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--t-text-muted);
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

/* ── History ── */
.see-all-btn {
  font-size: 12px;
  color: var(--t-brand-primary);
  background: none;
  border: none;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
  transition: background 0.15s;
}
.see-all-btn:hover { background: var(--t-brand-subtle); }

.history-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.history-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  background: var(--t-bg-panel);
  border: 1px solid var(--t-border-subtle);
  border-radius: var(--t-radius-md);
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}
.history-item:hover {
  background: var(--t-bg-panel-hover);
  border-color: var(--t-brand-glow);
}
.history-icon {
  width: 32px; height: 32px;
  background: var(--t-brand-subtle);
  border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  color: var(--t-brand-primary);
  flex-shrink: 0;
}
.history-info {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.history-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--t-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.history-meta {
  font-size: 11px;
  color: var(--t-text-muted);
}

/* ── Templates ── */
.templates {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.tpl-card {
  background: var(--t-bg-panel);
  border: 1px solid var(--t-border-subtle);
  border-radius: var(--t-radius-md);
  padding: 18px;
  text-align: left;
  cursor: pointer;
  transition: transform 0.2s, border-color 0.3s, box-shadow 0.3s, background 0.2s;
  color: inherit;
}

.tpl-card:hover {
  transform: translateY(-2px);
  background: var(--t-bg-panel-hover);
  border-color: var(--t-brand-glow);
  box-shadow: 0 6px 24px var(--t-brand-subtle), 0 4px 16px rgba(0, 0, 0, 0.2);
}

.tpl-icon {
  font-size: 26px;
  margin-bottom: 10px;
}

.tpl-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--t-text-primary);
}

.tpl-desc {
  font-size: 11px;
  color: var(--t-text-muted);
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
  color: var(--t-brand);
  background: none;
  border: 1px solid var(--t-brand-subtle);
  border-radius: var(--t-radius-sm);
  padding: 6px 14px;
  cursor: pointer;
  transition: background 0.2s, border-color 0.2s;
}

.create-btn:hover {
  background: var(--t-brand-subtle);
  border-color: var(--t-brand-glow);
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
  background: var(--t-bg-panel);
  border: 1px solid var(--t-border-subtle);
  border-radius: var(--t-radius-md);
  padding: 14px 18px;
  cursor: pointer;
  transition: transform 0.2s, border-color 0.2s, box-shadow 0.2s, background 0.2s;
}

.app-row:hover {
  transform: translateY(-1px);
  background: var(--t-bg-panel-hover);
  border-color: var(--t-border-strong);
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
  background: var(--t-success);
  box-shadow: 0 0 8px rgba(16, 185, 129, 0.4);
}

.app-status-dot.disconnected {
  background: var(--t-border-strong);
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
  color: var(--t-text-primary);
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
  background: var(--t-border-subtle);
  color: var(--t-text-muted);
}

.app-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 3px;
}

.app-platform {
  font-size: 12px;
  color: var(--t-text-secondary);
}

.app-date {
  font-size: 11px;
  color: var(--t-text-muted);
}

.settings-btn {
  background: none;
  border: none;
  color: var(--t-text-muted);
  cursor: pointer;
  padding: 6px;
  border-radius: var(--t-radius-sm);
  transition: background 0.2s, color 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
}

.settings-btn:hover {
  background: var(--t-bg-panel-hover);
  color: var(--t-text-secondary);
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
  color: var(--t-text-muted);
  font-size: 13px;
  padding: 40px 20px;
  background: var(--t-bg-panel);
  border: 1px dashed var(--t-border-subtle);
  border-radius: var(--t-radius-md);
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
  background: var(--t-border-subtle);
  border-radius: 3px;
}

.main-scroll::-webkit-scrollbar-thumb:hover {
  background: var(--t-border-strong);
}
</style>
