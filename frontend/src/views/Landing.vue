<template>
  <WorkbenchShell>
    <main class="main">
      <div class="bg"></div>
      <div class="content">
        <div class="hero">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none">
            <path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 17l-6.2 4.3 2.4-7.4L2 9.4h7.6L12 2z" fill="#8A82E8" opacity="0.92"/>
          </svg>
          <div class="hero-title">aPaaS Builder AI</div>
          <div class="hero-sub">用 AI 构建企业级低代码应用</div>
        </div>

        <div class="dual-entry">
          <button class="mode-card" :class="{ active: mode==='strict' }" @click="mode='strict'">
            <div class="mode-icon strict">
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><rect x="3" y="2" width="10" height="12" rx="1.5" stroke="#534AB7" stroke-width="1.3"/><path d="M5 6h6M5 8.5h4" stroke="#534AB7" stroke-width="1.2" stroke-linecap="round"/></svg>
            </div>
            <div class="mode-title">文档解析生成</div>
            <div class="mode-desc">上传设计文档，严格按内容生成，不补充字段或角色</div>
            <div class="mode-badge badge-strict">精准还原</div>
          </button>

          <button class="mode-card" :class="{ active: mode==='ai' }" @click="mode='ai'">
            <div class="mode-icon ai">
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M8 2a6 6 0 100 12A6 6 0 008 2z" stroke="#1D9E75" stroke-width="1.3"/><path d="M5.5 9c.5.8 1.4 1.3 2.5 1.3s2-.5 2.5-1.3M6 6.5h.01M10 6.5h.01" stroke="#1D9E75" stroke-width="1.4" stroke-linecap="round"/></svg>
            </div>
            <div class="mode-title">AI 智能生成</div>
            <div class="mode-desc">描述需求或上传文档，AI 进一步分析补全，可对话完善</div>
            <div class="mode-badge badge-ai">AI 增强</div>
          </button>
        </div>

        <div class="input-zone">
          <div class="input-box">
            <input class="input-text" v-model="inputText" :placeholder="inputPlaceholder" @keydown.enter="goChat(inputText.trim())" />
            <div class="input-bottom">
              <label class="upload-btn">
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M6 1v7M2.5 4.5L6 8l3.5-3.5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/><path d="M1 10.5h10" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>
                上传文档
                <input type="file" accept=".md,.pdf,.docx,.doc,.txt,.markdown" @change="handleDocUpload" hidden />
              </label>
              <button class="send-btn" @click="goChat(inputText.trim())">
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M1 6h10M6 1l5 5-5 5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>
                {{ sendLabel }}
              </button>
            </div>
          </div>
        </div>

        <div class="body-content">
          <div class="stats-row">
            <div class="stat-card">
              <div class="stat-label">已搭建应用</div>
              <div class="stat-num">{{ recentApps.length }}</div>
              <div class="stat-sub">最近 +{{ Math.min(3, recentApps.length) }}</div>
            </div>
            <div class="stat-card">
              <div class="stat-label">AI 对话次数</div>
              <div class="stat-num">{{ recentSessions.length }}</div>
              <div class="stat-sub">本周 +{{ Math.min(24, recentSessions.length) }}</div>
            </div>
            <div class="stat-card">
              <div class="stat-label">已生成模块数</div>
              <div class="stat-num">{{ generatedModules }}</div>
              <div class="stat-sub">昨日 +{{ Math.min(8, generatedModules) }}</div>
            </div>
          </div>

          <div>
            <div class="section-header">
              <span class="section-title">已搭建应用</span>
              <button class="view-all-link" @click="navigateTo('/apps')">查看全部 →</button>
            </div>
            <div class="app-grid">
              <button v-for="(app,idx) in recentApps.slice(0,6)" :key="app.id" class="app-card" @click="openApp(app)">
                <div class="app-card-header">
                  <div class="app-dot" :class="idx===1 ? 'teal' : idx===2 ? 'amber' : 'purple'">{{ idx===1 ? '💰' : idx===2 ? '⚙️' : '📋' }}</div>
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
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '@/utils/request'
import { usePreviewStore } from '@/stores/preview'
import { useUserStore } from '@/stores/user'
import { conversationApi, type ConversationWithApp } from '@/api/conversation'
import { applicationApi } from '@/api/application'
import type { AppItem } from '@/components/AppSidebar.vue'
import WorkbenchShell from '@/components/WorkbenchShell.vue'

const router = useRouter()
const previewStore = usePreviewStore()
const userStore = useUserStore()

const mode = ref<'strict' | 'ai'>('strict')
const inputText = ref('')
const recentSessions = ref<ConversationWithApp[]>([])
const recentApps = ref<AppItem[]>([])
const generatedModules = ref(0)
const profileDialogVisible = ref(false)
const changingPassword = ref(false)
const passwordForm = ref({ oldPassword: '', newPassword: '', confirmPassword: '' })

const userInitial = computed(() => (userStore.user?.username || 'A').slice(0, 1))
const userDisplayName = computed(() => (userStore.user as any)?.nickname || userStore.user?.username || 'admin')
const inputPlaceholder = computed(() =>
  mode.value === 'strict'
    ? '上传设计文档，我将严格按照文档结构生成，不做额外补充...'
    : '描述你的需求，或上传文档让 AI 进一步分析完善...'
)
const sendLabel = computed(() => (mode.value === 'strict' ? '解析生成' : 'AI 生成'))

function normalizeSessionTitle(title?: string) {
  const raw = String(title || '').trim()
  if (!raw) return 'aPaaS Builder AI 会话'
  return raw.length > 24 ? `${raw.slice(0, 24)}...` : raw
}

function formatDate(dateStr: string) {
  if (!dateStr) return '今天'
  const d = new Date(dateStr)
  return `${d.getMonth() + 1}月${d.getDate()}日`
}

function navigateTo(path: string) {
  router.push(path)
}

function goChat(prompt = '') {
  const trimmed = prompt.trim()
  if (trimmed) {
    router.push({ path: '/chat', query: { prompt: trimmed } })
  } else {
    router.push('/chat')
  }
}

function handleDocUpload(e: Event) {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  target.value = ''
  previewStore.pendingFile = file
  router.push('/chat')
}

function openApp(app: AppItem) {
  router.push({ path: '/chat', query: { app_id: String(app.id) } })
}

function openConversation(sessionId: number | string) {
  router.push(`/chat/${sessionId}`)
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

function handleUserCommand(command: string | number | object) {
  if (command === 'profile') {
    profileDialogVisible.value = true
    return
  }
  if (command === 'logout') {
    logoutWithConfirm()
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

onMounted(async () => {
  const [list, apps] = await Promise.all([
    conversationApi.listWithApps({ agent_type: 'builder' }).catch(() => []),
    applicationApi.list({ include_remote: true }).catch(() => []),
  ])

  recentSessions.value = list.slice(0, 8)

  const appCards = Array.isArray(apps)
    ? apps
        .filter((app: any) => app?.id && app?.app_name)
        .sort((a: any, b: any) => {
          const ta = new Date(a.updated_at || a.created_at || 0).getTime()
          const tb = new Date(b.updated_at || b.created_at || 0).getTime()
          return tb - ta
        })
        .slice(0, 6)
        .map(mapApplicationToCard)
    : []

  recentApps.value = appCards.length
    ? appCards
    : list
        .filter((conv: any) => conv.app_id && conv.app_name)
        .slice(0, 6)
        .map((conv: any) => ({
          id: conv.app_id,
          label: conv.app_name,
          status: conv.local_status || 'completed',
          timeLabel: formatDate(conv.updated_at || conv.created_at),
          appId: conv.app_id,
          conversationId: conv.id,
          apaasAppId: conv.apaas_app_id,
        }))

  generatedModules.value = (Array.isArray(apps) && apps.length ? apps : list).reduce((sum: number, item: any) => {
    const data = item.config_preview?.data || item.config_preview || {}
    return sum + (Array.isArray(data.models) ? data.models.length : 0)
  }, 0)
})
</script>

<style scoped>
* { box-sizing: border-box; margin: 0; padding: 0; }

.main { flex: 1; display: flex; flex-direction: column; overflow: hidden; position: relative; }
.bg { position: absolute; inset: 0; background: linear-gradient(160deg, #EEEDFE 0%, #E6F1FB 45%, #E1F5EE 100%); z-index: 0; }
.content { flex: 1; overflow-y: auto; position: relative; z-index: 1; }

.hero { padding: 32px 28px 16px; text-align: center; }
.hero-title { font-size: 24px; font-weight: 500; color: #26215C; letter-spacing: -0.02em; margin-top: 8px; }
.hero-sub { font-size: 13px; color: #534AB7; margin-top: 5px; opacity: 0.85; }

.dual-entry { padding: 0 28px; display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.mode-card { background: rgba(255,255,255,0.82); border: 0.5px solid rgba(255,255,255,0.95); border-radius: 14px; padding: 16px; cursor: pointer; transition: border-color 0.15s, box-shadow 0.15s; display: flex; flex-direction: column; text-align: left; }
.mode-card:hover { border-color: rgba(83,74,183,0.3); }
.mode-card.active { border-color: rgba(83,74,183,0.42); background: rgba(255,255,255,0.95); box-shadow: 0 0 0 1px rgba(83,74,183,0.12); }
.mode-icon { width: 34px; height: 34px; border-radius: 9px; display: flex; align-items: center; justify-content: center; margin-bottom: 10px; flex-shrink: 0; }
.mode-icon.strict { background: #EEEDFE; }
.mode-icon.ai { background: #E1F5EE; }
.mode-title { font-size: 13px; font-weight: 500; color: #26215C; margin-bottom: 4px; }
.mode-desc { font-size: 11px; color: #534AB7; opacity: 0.7; line-height: 1.55; flex: 1; }
.mode-badge { display: inline-flex; margin-top: 10px; font-size: 11px; padding: 3px 8px; border-radius: 20px; align-self: flex-start; }
.badge-strict { background: #EEEDFE; color: #534AB7; }
.badge-ai { background: #E1F5EE; color: #0F6E56; }

.input-zone { padding: 10px 28px 0; }
.input-box { background: rgba(255,255,255,0.88); border: 0.5px solid rgba(83,74,183,0.2); border-radius: 14px; padding: 14px 16px; }
.input-text { width: 100%; border: none; outline: none; background: transparent; font-size: 13px; color: #26215C; line-height: 1.5; min-height: 20px; }
.input-text::placeholder { color: #9490C4; }
.input-bottom { display: flex; align-items: center; justify-content: space-between; margin-top: 20px; }
.upload-btn { display: flex; align-items: center; gap: 5px; padding: 6px 12px; border-radius: 8px; border: 0.5px solid rgba(83,74,183,0.25); font-size: 12px; color: #534AB7; cursor: pointer; background: rgba(255,255,255,0.7); }
.send-btn { display: flex; align-items: center; gap: 6px; padding: 7px 16px; background: #3C3489; color: #EEEDFE; border-radius: 8px; font-size: 12px; font-weight: 500; cursor: pointer; border: none; }

.body-content { padding: 16px 28px 24px; display: flex; flex-direction: column; gap: 18px; }
.stats-row { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.stat-card { background: rgba(255,255,255,0.75); border: 0.5px solid rgba(255,255,255,0.9); border-radius: var(--border-radius-lg); padding: 12px 14px; }
.stat-label { font-size: 11px; color: #534AB7; margin-bottom: 5px; opacity: 0.8; }
.stat-num { font-size: 20px; font-weight: 500; color: #26215C; }
.stat-sub { font-size: 11px; color: #3B6D11; margin-top: 2px; }

.section-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.section-title { font-size: 13px; font-weight: 500; color: #26215C; }
.view-all-link { border: none; background: transparent; color: #6d73d5; font-size: 12px; font-weight: 500; cursor: pointer; padding: 0; }
.view-all-link:hover { color: #534AB7; }
.app-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.app-card { background: rgba(255,255,255,0.75); border: 0.5px solid rgba(255,255,255,0.9); border-radius: var(--border-radius-lg); padding: 12px; cursor: pointer; text-align: left; }
.app-card-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.app-dot { width: 28px; height: 28px; border-radius: 7px; display: flex; align-items: center; justify-content: center; font-size: 13px; flex-shrink: 0; }
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

@media (max-width: 1080px) {
  .dual-entry,
  .stats-row,
  .app-grid {
    grid-template-columns: 1fr;
  }
}
</style>
