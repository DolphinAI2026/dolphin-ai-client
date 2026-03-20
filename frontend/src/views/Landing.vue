<template>
  <div class="landing">
    <nav class="nav-bar">
      <div class="nav-left">
        <div class="logo-box">A</div>
        <span class="logo-text">aPaaS Builder AI</span>
        <span class="badge">Beta</span>
      </div>
      <div class="nav-right">
        <button class="connect-btn" @click="previewStore.showConnectModal = true">
          <span class="dot" :class="{ active: previewStore.connected }"></span>
          <span>{{ previewStore.connected ? '已连接得帆云' : '未连接' }}</span>
        </button>
        <el-dropdown @command="handleUserCommand">
          <button class="user-btn">
            <div class="user-avatar">{{ userStore.user?.username?.charAt(0).toUpperCase() || 'U' }}</div>
            <span class="user-name">{{ userStore.user?.username }}</span>
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

    <div class="center-area">
      <div class="hero">
        <div class="hero-logo">A</div>
        <h1>aPaaS Builder AI</h1>
        <p>用对话的方式，在得帆云平台上搭建你的应用</p>
      </div>

      <div class="input-box">
        <div class="input-row">
          <label class="upload-btn" title="上传设计文档 (.md)">
            <input type="file" accept=".md" @change="handleDocUpload" hidden />
            📄
          </label>
          <input
            v-model="inputText"
            @keydown.enter="startChat"
            placeholder="描述你想要的应用，或上传设计文档..."
          />
          <button class="send-btn" @click="startChat" :disabled="!inputText.trim()">➤</button>
        </div>
      </div>

      <!-- Vibe Coding 入口 -->
      <div class="section">
        <div class="coding-entry" @click="router.push('/coding')">
          <div class="coding-entry-left">
            <div class="coding-logo">⚡</div>
            <div>
              <div class="coding-title">Vibe Coding</div>
              <div class="coding-desc">用自然语言生成aPaaS自开发代码 - 组件、页面、接口、脚本</div>
            </div>
          </div>
          <span class="coding-arrow">→</span>
        </div>
      </div>

      <div class="section">
        <h3>从模板开始</h3>
        <div class="templates">
          <button v-for="t in templates" :key="t.name" class="tpl-card" @click="startWithTemplate(t.prompt)">
            <div class="tpl-icon">{{ t.icon }}</div>
            <div class="tpl-name">{{ t.name }}</div>
            <div class="tpl-desc">{{ t.desc }}</div>
          </button>
        </div>
      </div>

      <div class="section">
        <div class="section-header">
          <h3>我的应用</h3>
          <button class="link-btn" @click="router.push('/apps')">查看全部</button>
        </div>
        <div class="app-list" v-if="apps.length > 0">
          <div v-for="a in apps" :key="a.id" class="app-row" @click="router.push('/apps')">
            <div class="app-row-left">
              <div class="app-icon" :class="a.source === 'remote' ? 'remote' : a.source === 'linked' ? 'linked' : a.local_status === 'completed' ? 'success' : 'generating'">
                {{ a.source === 'remote' ? '☁️' : a.source === 'linked' ? '🔗' : a.local_status === 'completed' ? '✓' : '⟳' }}
              </div>
              <div>
                <div class="app-name-row">
                  <span class="app-name">{{ a.app_name }}</span>
                  <span class="source-tag" :class="a.source">{{ a.source === 'local' ? '本地' : a.source === 'remote' ? '平台' : '已同步' }}</span>
                </div>
                <div class="app-date">{{ a.updated_at?.slice(0, 16) }}</div>
              </div>
            </div>
            <div class="app-stats">
              <span>{{ a.models || 0 }} 模型</span>
              <span>{{ a.forms || 0 }} 表单</span>
            </div>
          </div>
        </div>
        <div v-else class="empty-hint">暂无应用，开始对话创建你的第一个应用</div>
      </div>
    </div>

    <ConnectModal v-model="previewStore.showConnectModal" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { usePreviewStore } from '@/stores/preview'
import { useUserStore } from '@/stores/user'
import { applicationApi } from '@/api/application'
import ConnectModal from '@/components/ConnectModal.vue'
import type { MergedApplication } from '@/types'

const router = useRouter()
const previewStore = usePreviewStore()
const userStore = useUserStore()
const inputText = ref('')
const apps = ref<MergedApplication[]>([])

const templates = [
  { icon: '👥', name: 'CRM客户管理', desc: '客户、联系人、跟进、合同', prompt: '我想做一个客户管理系统' },
  { icon: '🔧', name: '售后工单系统', desc: '工单、派单、执行、备件', prompt: '我想做一个售后服务工单系统' },
  { icon: '📋', name: '项目管理', desc: '项目、任务、里程碑、资源', prompt: '我想做一个项目管理系统' }
]

onMounted(async () => {
  try {
    const list = await applicationApi.list()
    apps.value = (Array.isArray(list) ? list : []).slice(0, 3)
  } catch (e) { /* ignore */ }
})

const startChat = () => {
  const text = inputText.value.trim()
  if (!text) return
  router.push({ path: '/chat', query: { prompt: text } })
}

const startWithTemplate = (prompt: string) => {
  router.push({ path: '/chat', query: { prompt } })
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
.landing { height: 100vh; display: flex; flex-direction: column; background: #f9fafb; }
.nav-bar { display: flex; justify-content: space-between; align-items: center; padding: 12px 24px; background: #fff; border-bottom: 1px solid #e5e7eb; }
.nav-left { display: flex; align-items: center; gap: 10px; }
.nav-right { display: flex; align-items: center; gap: 16px; }
.logo-box { width: 32px; height: 32px; background: #4f46e5; border-radius: 8px; display: flex; align-items: center; justify-content: center; color: #fff; font-weight: 700; font-size: 14px; }
.logo-text { font-size: 16px; font-weight: 600; color: #1f2937; }
.badge { font-size: 11px; background: #eef2ff; color: #4f46e5; padding: 2px 8px; border-radius: 10px; font-weight: 500; }
.connect-btn { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #6b7280; background: none; border: none; cursor: pointer; }
.connect-btn:hover { color: #374151; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: #d1d5db; }
.dot.active { background: #10b981; }

.user-btn { display: flex; align-items: center; gap: 8px; background: none; border: none; cursor: pointer; padding: 4px 8px; border-radius: 8px; transition: background 0.2s; }
.user-btn:hover { background: #f3f4f6; }
.user-avatar { width: 28px; height: 28px; border-radius: 50%; background: #4f46e5; color: #fff; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 600; }
.user-name { font-size: 13px; color: #374151; font-weight: 500; }

.user-info { padding: 4px 0; }
.info-label { font-size: 11px; color: #9ca3af; margin-bottom: 2px; }
.info-value { font-size: 13px; color: #1f2937; font-weight: 500; }

.center-area { flex: 1; display: flex; flex-direction: column; align-items: center; padding: 0 24px; max-width: 640px; width: 100%; margin: 0 auto; overflow-y: auto; }
.hero { text-align: center; margin: 40px 0 32px; }
.hero-logo { width: 64px; height: 64px; background: #4f46e5; border-radius: 16px; display: flex; align-items: center; justify-content: center; color: #fff; font-size: 24px; font-weight: 700; margin: 0 auto 20px; box-shadow: 0 8px 24px rgba(79,70,229,0.2); }
.hero h1 { font-size: 28px; font-weight: 700; color: #111827; margin: 0 0 8px; }
.hero p { font-size: 16px; color: #6b7280; margin: 0; }

.input-box { width: 100%; margin-bottom: 32px; }
.input-row { display: flex; align-items: center; gap: 8px; background: #fff; border: 1px solid #e5e7eb; border-radius: 16px; padding: 6px 6px 6px 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); transition: border-color 0.2s; }
.input-row:focus-within { border-color: #a5b4fc; box-shadow: 0 0 0 3px rgba(99,102,241,0.1); }
.input-row input { flex: 1; border: none; outline: none; font-size: 14px; color: #374151; background: transparent; }
.input-row input::placeholder { color: #9ca3af; }
.input-row input:disabled { opacity: 0.5; }

.upload-btn { cursor: pointer; font-size: 18px; padding: 4px 6px; border-radius: 8px; transition: background 0.2s; user-select: none; }
.upload-btn:hover { background: #f3f4f6; }

.send-btn { width: 36px; height: 36px; border-radius: 10px; border: none; background: #4f46e5; color: #fff; font-size: 16px; cursor: pointer; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.send-btn:hover:not(:disabled) { background: #4338ca; }
.send-btn:disabled { opacity: 0.4; cursor: not-allowed; }

.section { width: 100%; margin-bottom: 24px; }
.section h3 { font-size: 13px; font-weight: 500; color: #6b7280; margin: 0 0 12px; }
.section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.section-header h3 { margin: 0; }
.link-btn { font-size: 12px; color: #4f46e5; background: none; border: none; cursor: pointer; }

.templates { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.tpl-card { background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 16px; text-align: left; cursor: pointer; transition: all 0.2s; }
.tpl-card:hover { border-color: #a5b4fc; box-shadow: 0 2px 8px rgba(0,0,0,0.04); }
.tpl-icon { font-size: 24px; margin-bottom: 8px; }
.tpl-name { font-size: 13px; font-weight: 500; color: #1f2937; }
.tpl-desc { font-size: 11px; color: #9ca3af; margin-top: 4px; }

.app-list { display: flex; flex-direction: column; gap: 8px; }
.app-row { display: flex; justify-content: space-between; align-items: center; background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 12px 16px; cursor: pointer; transition: all 0.2s; }
.app-row:hover { border-color: #c7d2fe; }
.app-row-left { display: flex; align-items: center; gap: 12px; }
.app-icon { width: 32px; height: 32px; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 13px; }
.app-icon.success { background: #ecfdf5; color: #059669; }
.app-icon.generating { background: #fffbeb; color: #d97706; }
.app-name-row { display: flex; align-items: center; gap: 6px; }
.app-name { font-size: 13px; font-weight: 500; color: #1f2937; }
.source-tag { font-size: 10px; padding: 0 6px; border-radius: 8px; font-weight: 500; }
.source-tag.local { background: #f3f4f6; color: #6b7280; }
.source-tag.remote { background: #eff6ff; color: #2563eb; }
.source-tag.linked { background: #ecfdf5; color: #059669; }
.app-date { font-size: 11px; color: #9ca3af; }
.app-icon.remote { background: #eff6ff; color: #2563eb; }
.app-icon.linked { background: #ecfdf5; color: #059669; }
.app-stats { display: flex; gap: 16px; font-size: 12px; color: #9ca3af; }
.empty-hint { text-align: center; color: #9ca3af; font-size: 13px; padding: 24px; }

.coding-entry { display: flex; align-items: center; justify-content: space-between; background: linear-gradient(135deg, #1e1b4b, #312e81); border-radius: 16px; padding: 20px 24px; cursor: pointer; transition: all 0.3s; color: #fff; }
.coding-entry:hover { transform: translateY(-2px); box-shadow: 0 8px 24px rgba(79,70,229,0.3); }
.coding-entry-left { display: flex; align-items: center; gap: 16px; }
.coding-logo { width: 48px; height: 48px; background: rgba(255,255,255,0.15); border-radius: 12px; display: flex; align-items: center; justify-content: center; font-size: 24px; }
.coding-title { font-size: 16px; font-weight: 600; margin-bottom: 4px; }
.coding-desc { font-size: 12px; color: rgba(255,255,255,0.7); }
.coding-arrow { font-size: 20px; color: rgba(255,255,255,0.5); }
</style>
