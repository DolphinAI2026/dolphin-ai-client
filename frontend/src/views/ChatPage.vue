<template>
  <div class="chat-page">
    <TopBar
      :title="store.currentApp?.app_name || 'aPaaS Builder AI'"
      show-hamburger
      @toggle-sidebar="chatSidebarCollapsed = !chatSidebarCollapsed"
    >
      <template #center>
        <div class="mode-switcher">
          <button class="mode-btn" :class="{ active: activeView === 'builder' }" @click="activeView = 'builder'">
            <span>🤖</span> 智能搭建
          </button>
          <button
            v-if="SHOW_PLATFORM_CONFIG && store.currentApp?.apaas_app_id"
            class="mode-btn"
            :class="{ active: activeView === 'platform' }"
            @click="switchToPlatform"
          >
            <span>🛠️</span> 辅助搭建
          </button>
          <button
            v-if="store.currentApp?.apaas_app_id"
            class="mode-btn"
            :class="{ active: activeView === 'coding' }"
            @click="activeView = 'coding'"
          >
            <span>💻</span> 智能开发
          </button>
        </div>
      </template>
      <template #actions>
        <button
          v-if="SHOW_PLATFORM_CONFIG && activeView === 'platform' && platformIframeUrl"
          class="top-bar-icon-btn"
          @click="openPlatformNewTab"
          title="在新窗口打开"
        >↗</button>
      </template>
    </TopBar>

    <div class="main-area">
      <!-- 左侧应用列表侧栏 -->
      <AppSidebar
        :collapsed="chatSidebarCollapsed"
        :items="sidebarAppItems"
        :current-app-id="existingAppId"
        @toggle="chatSidebarCollapsed = !chatSidebarCollapsed"
        @select="onSidebarAppSelect"
        @new-app="handleNewApp"
      />

      <!-- 内容区域 -->
      <div class="content-area">

      <!-- 平台配置 iframe（v-show 保持不销毁） -->
      <div v-show="SHOW_PLATFORM_CONFIG && activeView === 'platform'" class="platform-iframe-container">
        <div v-if="platformLoading" class="platform-loading">
          <span class="loading-spinner">⟳</span> 加载平台配置...
        </div>
        <div v-else-if="platformError" class="platform-error">
          <p>{{ platformError }}</p>
          <div class="platform-error-actions">
            <button class="platform-retry-btn" @click="loadPlatformUrl">重试</button>
            <button class="platform-open-btn" @click="openPlatformNewTab">在新窗口打开</button>
          </div>
        </div>
        <template v-else-if="platformIframeUrl">
          <div v-if="platformLoginHint" class="platform-login-hint">
            <span>💡 首次使用请在下方登录平台（账号: <b>{{ platformLoginHint }}</b>）</span>
            <button class="hint-nav-btn" @click="navigateIframeToApp" title="登录后点击跳转到应用配置页">🔄 跳转到应用</button>
            <button class="hint-dismiss-btn" @click="platformLoginHint = ''">✕</button>
          </div>
          <iframe
            ref="platformIframeRef"
            :src="platformIframeUrl"
            class="platform-iframe"
            frameborder="0"
            allow="clipboard-read; clipboard-write"
            @error="onIframeError"
          ></iframe>
        </template>
      </div>

      <!-- 智能开发内容区 — iframe 嵌入 CodingPage -->
      <div v-show="activeView === 'coding'" class="coding-content">
        <iframe
          v-if="codingIframeUrl"
          :src="codingIframeUrl"
          class="coding-embed-frame"
          allow="clipboard-read; clipboard-write"
        ></iframe>
      </div>

      <!-- 智能搭建内容区（横向布局） -->
      <div v-show="!SHOW_PLATFORM_CONFIG || activeView === 'builder'" class="builder-content">
      <!-- 左侧对话区 -->
      <div class="chat-side">
        <div v-if="appParsedMode" class="doc-view-wrap">
          <div class="doc-view-head">
            <div class="doc-view-title">功能设计文档</div>
            <div class="doc-view-file">{{ lastParsedFilename || `${store.preview.appName || '未命名应用'}.md` }}</div>
          </div>
          <div class="doc-view-body" v-html="renderedLatestDocHtml"></div>
          <div v-if="!latestDocContent.trim()" class="doc-view-empty">
            暂无可展示的文档正文，可在需求分析中重新生成后查看。
          </div>
        </div>
        <div v-else class="messages" ref="messagesRef">
          <div v-for="(msg, idx) in messages" :key="idx" class="chat-bubble" :class="msg.role">
            <div class="bubble-inner">
              <div v-if="msg.role === 'assistant'" class="agent-label">
                <span>{{ agents[msg.agent || 'builder']?.icon }}</span>
                <span>{{ agents[msg.agent || 'builder']?.name }}</span>
              </div>
              <div class="bubble-content" :class="msg.role" v-html="formatContent(msg.content)"></div>
            </div>
          </div>
          <div v-if="isTyping" class="chat-bubble assistant">
            <div class="bubble-inner">
              <div class="bubble-content assistant">
                <span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>
              </div>
            </div>
          </div>
          <!-- 设计文档结构化卡片（requirements 模式生成完成后显示） -->
          <div v-if="docResultForCard" class="chat-bubble assistant">
            <div class="bubble-inner" style="max-width:90%">
              <DesignDocCard
                :doc-result="docResultForCard"
                :confirming="confirmingDoc"
                @confirm="confirmDocAndBuild"
                @edit="ElMessage.info('编辑功能即将推出')"
              />
            </div>
          </div>
          <!-- 编码冲突修复输入 -->
          <div v-if="activeConflict" class="chat-bubble assistant">
            <div class="bubble-inner">
              <div class="agent-label"><span>🤖</span><span>智能搭建</span></div>
              <div class="bubble-content assistant conflict-resolve-box">
                <div class="conflict-label">请输入新编码替换 <code>{{ activeConflict.current_code }}</code>：</div>
                <div class="conflict-input-row">
                  <input
                    v-model="activeConflict.newCode"
                    class="conflict-input"
                    placeholder="输入新编码，如 xxx_v2"
                    @keydown.enter="resolveConflictAndRetry"
                    :disabled="activeConflict.resolving"
                  />
                  <button class="conflict-btn confirm" @click="resolveConflictAndRetry" :disabled="activeConflict.resolving">
                    {{ activeConflict.resolving ? '修复中...' : '确认修复' }}
                  </button>
                  <button class="conflict-btn cancel" @click="cancelConflict" :disabled="activeConflict.resolving">取消</button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 配置就绪后的操作栏 -->
        <div v-if="readyForGenerate" class="gen-action-bar">
          <button
            v-if="deployAllDone || store.currentApp?.status === 'completed'"
            class="gen-btn done"
            @click="openDeployPanel"
          >✅ 已部署 · 查看记录</button>
          <button
            v-else
            class="gen-btn"
            :disabled="generating"
            @click="startGenerate"
          >{{ generating ? '创建中...' : deployAppId ? '⚡ 重新部署' : '⚡ 开始生成' }}</button>
        </div>

        <div v-if="!appParsedMode" class="input-bar">
          <div class="input-card">
            <div class="input-card-top">
              <label v-if="!isRequirementsMode" class="upload-btn" title="上传功能设计文档(.md)">
                <input type="file" accept=".md" @change="handleDocUpload" style="display:none" />
                <svg width="18" height="18" viewBox="0 0 18 18" fill="none"><path d="M15.5 8.5l-6.4 6.4a3.5 3.5 0 01-5-5l6.4-6.4a2.2 2.2 0 013.1 3.1L7.2 13a.9.9 0 01-1.3-1.3l5.5-5.5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>
              </label>
              <textarea
                v-model="inputText"
                @keydown.enter.exact.prevent="sendMessage"
                @keydown.enter.shift.exact="inputText += '\n'"
                :placeholder="isRequirementsMode ? '描述您的业务需求...' : '输入消息，或上传设计文档...'"
                rows="1"
                ref="inputRef"
                @input="autoResizeTextarea"
              ></textarea>
              <button class="send-btn" :class="{ disabled: !inputText.trim() }" @click="sendMessage">
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M14 2L7 9M14 2l-4.5 12-2-5.5L2 6.5 14 2z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>
              </button>
            </div>
            <div class="input-card-bottom">
              <div class="input-card-spacer"></div>
              <el-select
                v-model="selectedBuilderModelId"
                class="input-model-select"
                popper-class="model-select-dropdown"
                size="small"
                placeholder="模型"
                :loading="builderModelLoading"
                :disabled="builderModelLoading || updatingBuilderModel || builderModelOptions.length === 0"
                @change="handleBuilderModelChange"
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
            </div>
          </div>
        </div>
      </div>


      <!-- 第三栏：部署面板（requirements 模式下隐藏，builder 模式或配置就绪后显示） -->
      <div class="deploy-side" :class="{ open: activeView === 'builder' && (!isRequirementsMode || parseReady) }">
        <div v-if="appParsedMode" class="parsed-side-card">
          <div class="parsed-side-title">解析结果</div>
          <div class="parsed-side-row">应用名称：{{ store.preview.appName || '未命名应用' }}</div>
          <div class="parsed-side-row">应用编码：<code>{{ displayAppCode }}</code></div>
          <div class="parsed-side-row">模型：{{ store.preview.models.length }} 个</div>
          <div class="parsed-side-row">字典：{{ store.preview.dicts.length }} 个</div>
          <div class="parsed-side-row">角色：{{ store.preview.roles.length }} 个</div>
          <div class="parsed-side-brief">模型：{{ modelNamesText }}</div>
          <div class="parsed-side-brief">字典：{{ dictNamesText }}</div>
          <div class="parsed-side-brief">角色：{{ roleNamesText }}</div>
        </div>
        <div class="deploy-header">
          <div>
            <div class="deploy-title">部署到平台</div>
            <div class="deploy-desc">{{ deploySteps.length }} 个步骤</div>
          </div>
          <button v-if="false" class="deploy-close" @click="deployOpen = false">✕</button>
        </div>
        <div class="deploy-progress">
          <div class="dp-track"><div class="dp-fill" :style="{ width: deployPercent + '%' }"></div></div>
          <span class="dp-meta">{{ deployDoneCount }}/{{ deploySteps.length }}</span>
        </div>
        <div v-if="!appParsedMode" class="deploy-actions">
          <button class="dp-run-all" :disabled="deployRunningAll || deployExecuting !== null || deployAllDone" @click="deployRunAll">
            {{ deployAllDone ? '✓ 全部完成' : deployRunningAll ? '执行中...' : '▶ 一键执行' }}
          </button>
        </div>
        <div class="deploy-groups">
          <template v-for="(group, gi) in deployGroups" :key="gi">
            <div class="dg" :class="{ done: group.allDone, err: group.hasError }">
              <div class="dg-hd">
                <span class="dg-icon">{{ group.icon }}</span>
                <span class="dg-name">{{ group.title }}</span>
                <span class="dg-badge" :class="group.allDone ? 'done' : group.hasError ? 'err' : ''">
                  {{ group.allDone ? '完成' : group.hasError ? '失败' : group.doneCount + '/' + group.steps.length }}
                </span>
              </div>
              <div v-for="s in group.steps" :key="s.key" class="ds" :class="[s.status, { running: deployExecuting === s.key }]">
                <div class="ds-dot" :class="[s.status, { pulse: deployExecuting === s.key }]">
                  <template v-if="s.status === 'completed'">✓</template>
                  <template v-else-if="s.status === 'error'">!</template>
                </div>
                <div class="ds-body">
                  <div class="ds-name">{{ s.label.replace(/^创建(模型|表单): /, '') }}</div>
                  <div v-if="s.error" class="ds-err">{{ s.error }}</div>
                </div>
                <div class="ds-act">
                  <span v-if="deployExecuting === s.key" class="ds-spin"></span>
                  <button v-else-if="s.status === 'completed'" class="ds-btn redo" :disabled="deployRunningAll" @click="deployRedo(s.key)">↻</button>
                  <button v-else-if="s.status === 'error'" class="ds-btn retry" :disabled="deployRunningAll" @click="deployExec(s.key)">重试</button>
                  <button v-else-if="s.deps_met" class="ds-btn run" :disabled="deployRunningAll" @click="deployExec(s.key)">执行</button>
                  <span v-else class="ds-lock">🔒</span>
                </div>
              </div>
            </div>
          </template>
        </div>
        <div v-if="deployAllDone" class="deploy-done">
          🎉 部署完成！<button class="deploy-done-btn" @click="openInPlatform">查看应用 →</button>
          <button class="deploy-log-btn" @click="showApiLogs = true">📋 API日志</button>
        </div>
      </div><!-- /deploy-side -->
    </div><!-- /builder-content -->
      </div><!-- /content-area -->
    </div><!-- /main-area -->

    <!-- Modals (在 chat-page 根元素下) -->
    <ConnectModal v-model="store.showConnectModal" />
    <EnvSelectModal v-model="showEnvSelect" @selected="onEnvSelected" />
    <el-dialog v-model="showApiLogs" title="API 调用日志" width="80%" :append-to-body="true">
      <div class="api-logs-header">
        <el-select v-model="apiLogFilter" placeholder="筛选步骤" clearable size="small" style="width:200px">
          <el-option label="全部" value="" />
          <el-option label="仅失败" value="failed" />
        </el-select>
        <span class="api-logs-count">共 {{ apiLogs.length }} 条记录</span>
      </div>
      <div class="api-logs-table">
        <table>
          <thead>
            <tr><th>时间</th><th>步骤</th><th>API</th><th>状态</th><th>耗时</th><th>结果</th></tr>
          </thead>
          <tbody>
            <tr v-for="log in apiLogs" :key="log.id" :class="{ error: !log.success }">
              <td class="log-time">{{ log.created_at?.slice(11, 19) }}</td>
              <td class="log-step">{{ log.step_key }}</td>
              <td class="log-url" :title="log.url">{{ log.url?.split('/').pop() }}</td>
              <td class="log-status" :class="log.success ? 'ok' : 'fail'">{{ log.response_status }}</td>
              <td class="log-ms">{{ log.elapsed_ms }}ms</td>
              <td class="log-result">{{ log.success ? '✓' : log.error_message?.slice(0, 40) }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="apiLogs.length === 0" class="api-logs-empty">暂无日志</div>
      </div>
    </el-dialog>
  </div><!-- /chat-page -->
</template>

<script setup lang="ts">
import { API_PREFIX } from '@/utils/request'
import { ref, reactive, computed, nextTick, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ArrowLeft, Promotion } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { usePreviewStore } from '@/stores/preview'
import { useUserStore } from '@/stores/user'
import { applicationApi } from '@/api/application'
// codingApi / consumeSseResponse no longer needed — coding tab uses iframe
import { incrementalApi, type DiffResponse, type ExecuteResponse } from '@/api/incremental'
import { conversationApi, type ConversationWithApp } from '@/api/conversation'
import { marked } from 'marked'
import ConnectModal from '@/components/ConnectModal.vue'
import EnvSelectModal from '@/components/EnvSelectModal.vue'
import AppSidebar from '@/components/AppSidebar.vue'
import type { AppItem } from '@/components/AppSidebar.vue'
import { platformEnvApi } from '@/api/platformEnv'
import request from '@/utils/request'
import type { Message } from '@/types'
import ThemeToggle from '@/components/ThemeToggle.vue'
import TopBar from '@/components/TopBar.vue'
import { llmConfigApi, type BuilderModelOption } from '@/api/llmConfig'
import DesignDocCard from '@/components/DesignDocCard.vue'
import { requirementsApi } from '@/api/requirements'
import { convertConfig } from '@/api/conversation'

const router = useRouter()
const route = useRoute()
const store = usePreviewStore()
const userStore = useUserStore()
const parsedAppCode = ref('')
const loadedAppCode = ref('')
const lastParsedFilename = ref('')
const latestDocContent = ref('')
const readyForGenerate = computed(() => !!store.currentApp && parseReady.value)
const appParsedMode = computed(() => route.query.app_mode === 'parsed')
const displayAppCode = computed(() => parsedAppCode.value || loadedAppCode.value || buildAppCode(store.preview.appName))
const renderedLatestDocHtml = computed(() => renderMarkdown(latestDocContent.value || ''))
const modelNamesText = computed(() => {
  const names = store.preview.models.map((m: any) => m?.name).filter(Boolean)
  return names.length ? names.slice(0, 8).join('、') + (names.length > 8 ? ` 等 ${names.length} 项` : '') : '暂无'
})
const dictNamesText = computed(() => {
  const names = store.preview.dicts.map((d: any) => d?.name).filter(Boolean)
  return names.length ? names.slice(0, 8).join('、') + (names.length > 8 ? ` 等 ${names.length} 项` : '') : '暂无'
})
const roleNamesText = computed(() => {
  const names = store.preview.roles.map((r: any) => r?.name).filter(Boolean)
  return names.length ? names.slice(0, 8).join('、') + (names.length > 8 ? ` 等 ${names.length} 项` : '') : '暂无'
})

const handleNewApp = () => {
  router.push('/chat?mode=requirements')
}

// ── 用户头像菜单 ──
const handleUserCommand = (command: string) => {
  if (command === 'logout') {
    userStore.logout()
    router.push('/login')
  } else if (command === 'apps') {
    router.push('/apps')
  } else if (command === 'envs') {
    router.push('/platform-envs')
  }
}

// ── 左侧应用侧栏 ──
const chatSidebarCollapsed = ref(localStorage.getItem('chat-sidebar-collapsed') === 'true')
watch(() => chatSidebarCollapsed.value, (v) => {
  localStorage.setItem('chat-sidebar-collapsed', String(v))
})

const sidebarAppItems = computed<AppItem[]>(() => {
  // 只显示有关联应用的会话（过滤空对话）
  return conversationList.value
    .filter(conv => conv.app_id && conv.app_name)
    .map(conv => ({
      id: conv.app_id!,
      label: conv.app_name!,
      status: conv.local_status,
      timeLabel: formatConvTime(conv.created_at),
      appId: conv.app_id,
      conversationId: conv.id,
      apaasAppId: conv.apaas_app_id,
    }))
})

const onSidebarAppSelect = (app: AppItem) => {
  if (app.appId) {
    router.push({ path: '/chat', query: { app_id: String(app.appId), app_mode: 'parsed' } })
  } else if (app.conversationId) {
    loadConversation(app.conversationId)
  }
}

const messagesRef = ref<HTMLElement>()
const inputRef = ref<HTMLTextAreaElement>()
const inputText = ref('')
const isTyping = ref(false)

function autoResizeTextarea() {
  const el = inputRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 160) + 'px'
}
const currentAgent = ref('requirements')
const SHOW_PLATFORM_CONFIG = true
const builderModelOptions = ref<BuilderModelOption[]>([])
const builderModelLoading = ref(false)
const updatingBuilderModel = ref(false)
const selectedBuilderModelId = ref<number | null>(null)
const persistedBuilderModelId = ref<number | null>(null)
const defaultBuilderModelId = computed(() =>
  builderModelOptions.value.find(option => option.is_default)?.id
  ?? builderModelOptions.value[0]?.id
  ?? null
)
const builderModelHint = computed(() => {
  if (builderModelLoading.value) return '正在加载可用模型...'
  if (builderModelOptions.value.length === 0) return '未配置可用模型，请前往环境管理配置'
  if (conversationId.value) return '切换后仅影响后续对话与生成配置'
  return '首条消息会使用当前选择的模型'
})

const normalizeBuilderModelId = (modelId?: number | null): number | null => {
  const ids = new Set(builderModelOptions.value.map(option => option.id))
  if (modelId != null && ids.has(modelId)) return modelId
  return defaultBuilderModelId.value
}

const applyBuilderModelSelection = (modelId?: number | null) => {
  const normalized = normalizeBuilderModelId(modelId)
  selectedBuilderModelId.value = normalized
  persistedBuilderModelId.value = conversationId.value ? normalized : null
}

const formatBuilderModelOption = (option: BuilderModelOption): string => option.config_name

const loadBuilderModelOptions = async () => {
  builderModelLoading.value = true
  try {
    builderModelOptions.value = await llmConfigApi.listOptions('builder')
    selectedBuilderModelId.value = normalizeBuilderModelId(selectedBuilderModelId.value)
    if (conversationId.value) {
      persistedBuilderModelId.value = normalizeBuilderModelId(persistedBuilderModelId.value)
    }
  } catch (e) {
    console.error('获取 builder 模型列表失败:', e)
    builderModelOptions.value = []
    selectedBuilderModelId.value = null
    persistedBuilderModelId.value = null
  } finally {
    builderModelLoading.value = false
  }
}

const syncBuilderModelFromConversation = async (cid: number) => {
  try {
    const conversation = await conversationApi.get(cid)
    applyBuilderModelSelection(conversation.selected_llm_config_id)
    // Sync agent_type for requirements mode detection
    if (conversation.agent_type) {
      currentAgent.value = conversation.agent_type
    }

    const convIdx = conversationList.value.findIndex(item => item.id === cid)
    if (convIdx >= 0) {
      const currentConversation = conversationList.value[convIdx]
      if (currentConversation) {
        currentConversation.selected_llm_config_id = conversation.selected_llm_config_id ?? null
      }
    }
  } catch (e) {
    console.warn('恢复会话模型失败:', e)
    applyBuilderModelSelection(null)
  }
}

const handleBuilderModelChange = async (nextValue: number | null) => {
  selectedBuilderModelId.value = nextValue
  if (!conversationId.value) return

  const previousValue = persistedBuilderModelId.value
  updatingBuilderModel.value = true
  try {
    const updated = await conversationApi.updateModel(conversationId.value, nextValue)
    const normalized = normalizeBuilderModelId(updated.selected_llm_config_id)
    selectedBuilderModelId.value = normalized
    persistedBuilderModelId.value = normalized

    const convIdx = conversationList.value.findIndex(item => item.id === conversationId.value)
    if (convIdx >= 0) {
      const currentConversation = conversationList.value[convIdx]
      if (currentConversation) {
        currentConversation.selected_llm_config_id = updated.selected_llm_config_id ?? null
      }
    }
  } catch (e: any) {
    selectedBuilderModelId.value = normalizeBuilderModelId(previousValue)
    ElMessage.error(e?.response?.data?.detail || '切换模型失败')
  } finally {
    updatingBuilderModel.value = false
  }
}

// ── 应用计数（导航栏徽标） ──
const appCount = ref(0)
const fetchAppCount = async () => {
  try {
    const apps = await applicationApi.list() as any[]
    appCount.value = apps.length
  } catch { /* ignore */ }
}

// ── 平台配置 iframe ──
const activeView = ref<'builder' | 'platform' | 'coding'>('builder')

// ── 智能开发（iframe 嵌入 CodingPage） ──
const codingIframeUrl = computed(() => {
  const appId = existingAppId.value || route.query.app_id
  const base = import.meta.env.BASE_URL.replace(/\/$/, '')
  return appId ? `${base}/coding?app_id=${appId}` : `${base}/coding`
})

// ── 平台配置 iframe ──
const platformIframeUrl = ref('')
const platformAppUrl = ref('')  // 应用配置页 URL（登录后跳转用）
const platformLoading = ref(false)
const platformError = ref('')
const platformLoginHint = ref('')
const platformIframeRef = ref<HTMLIFrameElement | null>(null)

const loadPlatformUrl = async () => {
  if (!existingAppId.value) return
  platformLoading.value = true
  platformError.value = ''
  try {
    // 获取平台真实 URL，iframe 直连平台
    const data = await platformEnvApi.getEmbedUrl(existingAppId.value)
    const { url, username } = data as any
    platformIframeUrl.value = url
    platformAppUrl.value = url
    // 首次使用需要在 iframe 中登录平台（登录一次后 cookie 保持）
    if (username) {
      platformLoginHint.value = `首次使用请在下方登录平台（账号: ${username}），登录后自动进入应用配置`
    }
  } catch (e: any) {
    platformError.value = e?.response?.data?.detail || e?.message || '获取平台链接失败'
  } finally {
    platformLoading.value = false
  }
}

const switchToPlatform = () => {
  activeView.value = 'platform'
  if (!platformIframeUrl.value) {
    loadPlatformUrl()
  }
}

const navigateIframeToApp = () => {
  if (platformIframeRef.value && platformAppUrl.value) {
    platformIframeRef.value.src = platformAppUrl.value
    platformLoginHint.value = ''
  }
}

const openPlatformNewTab = () => {
  if (platformAppUrl.value || platformIframeUrl.value) {
    window.open(platformAppUrl.value || platformIframeUrl.value, '_blank')
  }
}

const onIframeError = () => {
  platformError.value = '平台页面加载失败，可能不支持 iframe 嵌入'
}

// 字段类型图标映射（兜底，防止后端返回中文导致竖排）
const FIELD_ICON_MAP: Record<string, string> = {
  '单据号': '#', '单行输入': 'T', '多行输入': '¶',
  '手机号码': 'P', '电子邮箱': '@', '下拉单选': '▼',
  '下拉多选': '☰', '数据单选': '⇢', '数据多选': '⇢', '日期时间': 'D',
  '金额': '¥', '数字': 'N', '附件上传': '⊕',
  '开关': '⊘', '人员选择': '⊙', '部门选择': '⊙',
  '地理位置': '◎', '子表': '▦', '地区地址': '◎',
  '单选框': '○', '多选框': '☐', '富文本': 'R',
  '超链接': '⊕', '证件号': '#', '签名': 'S',
}
const getFieldIcon = (f: any) => {
  // 如果 icon 是单字符或已是合法符号，直接用
  if (f.icon && f.icon.length <= 2) return f.icon
  // 否则从 type 映射
  return FIELD_ICON_MAP[f.type] || FIELD_ICON_MAP[f.icon] || 'T'
}

const agents: Record<string, { name: string; icon: string }> = {
  builder: { name: '智能搭建', icon: '🤖' },
  requirements: { name: '需求分析', icon: '📋' },
  assistant: { name: '辅助开发智能体', icon: '🛠️' },
  developer: { name: '复杂开发智能体', icon: '💻' }
}

if (store.previewTab === 'workflow') {
  store.previewTab = 'overview'
}

const messages = reactive<Message[]>([
  { id: 0, role: 'assistant', agent: 'builder', content: '你好！我是 aPaaS 智能搭建，可以帮你通过对话的方式在得帆云平台上快速搭建应用。\n\n你可以告诉我想要创建什么系统，我会帮你理清需求并自动生成。\n\n比如：\n• "我想做一个客户管理系统"\n• "帮我搭建一个项目管理应用"\n• "创建一个售后服务工单系统"', created_at: '' }
])

const scrollToBottom = () => { nextTick(() => { if (messagesRef.value) messagesRef.value.scrollTop = messagesRef.value.scrollHeight }) }

// 从AI回复中提取JSON配置（只支持 preview 完整配置）
const extractPreviewData = (content: string) => {
  // 提取所有 ```json 块
  const allMatches = [...content.matchAll(/```json\s*([\s\S]*?)```/g)]
  if (allMatches.length === 0) return

  for (const match of allMatches) {
    try {
      const parsed = JSON.parse((match[1] || '').trim())
      console.log('extractPreviewData: parsed type =', parsed.type, parsed)

      // 完整配置模式
      if (parsed.type === 'preview' && parsed.data) {
        if (store.preview.models.length > 0) {
          console.warn('已有配置，忽略 LLM 重复输出的完整 JSON')
          continue
        }
        store.currentApp = { name: parsed.data.appName, status: 'draft' }
        store.preview.appName = parsed.data.appName || ''
        store.preview.roles = parsed.data.roles || []
        store.preview.dicts = parsed.data.dicts || []
        store.preview.models = parsed.data.models || []
        store.preview.workflows = parsed.data.workflows || []
        store.preview.permissions = parsed.data.permissions || []

        // 自动创建 Application（如果还没有）
        if (!existingAppId.value && parsed.data.appName) {
          applicationApi.autoCreate({
            app_name: parsed.data.appName,
            config_preview: parsed.data,
            conversation_id: conversationId.value || undefined,
          }).then(result => {
            existingAppId.value = result.app_id
            router.replace({ query: { ...route.query, app_id: String(result.app_id) } })
            console.log(`Auto-created app: id=${result.app_id}, is_new=${result.is_new}`)
          }).catch(e => {
            console.error('Auto-create application failed:', e)
          })
        }
        continue
      }

    } catch (e) {
      console.error('Failed to parse JSON block:', e)
    }
  }
}

// ── Patch 校验 & 自动修复 ──

const VALID_PATCH_OPS = new Set([
  'add_dict', 'update_dict', 'remove_dict',
  'add_field', 'update_field', 'remove_field',
  'add_model', 'remove_model',
  'add_role', 'remove_role',
  'add_workflow', 'update_workflow', 'remove_workflow',
  'add_permission', 'update_permission', 'remove_permission', 'set_permissions',
])

const generateCode = (name: string): string => {
  if (!name) return 'c_' + Math.random().toString(36).slice(2, 9)
  const ascii = name.replace(/[^a-zA-Z0-9_]/g, '').toLowerCase()
  return ascii.length >= 2 ? ascii : 'c_' + Math.random().toString(36).slice(2, 9)
}

const validateAndFixActions = (actions: any[]): any[] => {
  return actions.filter((action, i) => {
    if (!action || typeof action !== 'object') {
      console.warn(`Patch action[${i}]: 不是对象，已跳过`)
      return false
    }
    if (!action.op || !VALID_PATCH_OPS.has(action.op)) {
      console.warn(`Patch action[${i}]: 未知操作 '${action.op}'，已跳过`)
      return false
    }
    // remove 操作需要 target
    if (action.op.startsWith('remove_') && !action.target) {
      console.warn(`Patch action[${i}] (${action.op}): 缺失 target，已跳过`)
      return false
    }
    // add 操作需要 value
    if (action.op.startsWith('add_') && !action.value) {
      console.warn(`Patch action[${i}] (${action.op}): 缺失 value，已跳过`)
      return false
    }
    // field 操作需要 model
    if (['add_field', 'update_field', 'remove_field'].includes(action.op) && !action.model) {
      console.warn(`Patch action[${i}] (${action.op}): 缺失 model，已跳过`)
      return false
    }
    // 自动修复 value 中缺失的 code
    if (action.value && typeof action.value === 'object') {
      if (action.value.name && !action.value.code) {
        action.value.code = generateCode(action.value.name)
        console.log(`Patch action[${i}]: 自动生成 code '${action.value.code}'`)
      }
      // 修复 fields 中的 code
      if (Array.isArray(action.value.fields)) {
        for (const f of action.value.fields) {
          if (f && f.name && !f.code) {
            f.code = generateCode(f.name)
          }
        }
      }
      // 修复 options 中的 code
      if (Array.isArray(action.value.options)) {
        for (const opt of action.value.options) {
          if (opt && opt.name && !opt.code) {
            opt.code = generateCode(opt.name)
          }
        }
      }
    }
    return true
  })
}

// 应用 patch 操作到 store.preview
const applyPatch = (actions: any[]) => {
  for (const action of actions) {
    const { op, value, target, model } = action
    try {
      switch (op) {
        case 'add_dict':
          store.preview.dicts.push(value)
          break
        case 'update_dict': {
          const dict = store.preview.dicts.find(d => d.name === target)
          if (dict && value) Object.assign(dict, value)
          break
        }
        case 'remove_dict':
          store.preview.dicts = store.preview.dicts.filter(d => d.name !== target)
          break
        case 'add_field': {
          const m = store.preview.models.find(m => m.name === model)
          if (m) m.fields.push(value)
          break
        }
        case 'update_field': {
          const m2 = store.preview.models.find(m => m.name === model)
          if (m2) {
            const f = m2.fields.find(f => f.name === target)
            if (f && value) Object.assign(f, value)
          }
          break
        }
        case 'remove_field': {
          const m3 = store.preview.models.find(m => m.name === model)
          if (m3) m3.fields = m3.fields.filter(f => f.name !== target)
          break
        }
        case 'add_model':
          store.preview.models.push(value)
          break
        case 'remove_model':
          store.preview.models = store.preview.models.filter(m => m.name !== target)
          break
        case 'add_role':
          store.preview.roles.push(value)
          break
        case 'remove_role':
          store.preview.roles = store.preview.roles.filter(r => r.name !== target)
          break
        case 'add_workflow':
          store.preview.workflows.push(value)
          break
        case 'update_workflow': {
          const wf = store.preview.workflows.find(w => w.name === target)
          if (wf) Object.assign(wf, value)
          else store.preview.workflows.push({ name: target, ...value })
          break
        }
        case 'remove_workflow':
          store.preview.workflows = store.preview.workflows.filter(w => w.name !== target)
          break
        case 'add_permission':
          store.preview.permissions.push(value)
          break
        case 'update_permission': {
          const perm = store.preview.permissions.find(p => p.form === target)
          if (perm && value) Object.assign(perm, value)
          else store.preview.permissions.push({ form: target, ...value })
          break
        }
        case 'remove_permission':
          store.preview.permissions = store.preview.permissions.filter(p => p.form !== target)
          break
        case 'set_permissions':
          // 批量设置所有权限（替换整个数组）
          store.preview.permissions = value || []
          break
        default:
          console.warn(`Unknown patch op: ${op}`)
      }
    } catch (e) {
      console.error(`Patch action failed: ${op}`, e)
    }
  }
  // 标记配置已更新
  if (!store.currentApp) {
    store.currentApp = { name: store.preview.appName, status: 'draft' }
  }
}

// ── 直接编辑配置（不走 LLM）──

const addRole = () => {
  const name = prompt('角色名称（中文）：')
  if (!name) return
  const code = prompt('角色编码（英文，如 role_admin）：', `role_${name}`)
  if (!code) return
  store.preview.roles.push({ name, code })
}

const removeRole = (idx: number) => {
  const r = store.preview.roles[idx]
  if (!r) return
  if (confirm(`删除角色「${r.name}」？`)) {
    store.preview.roles.splice(idx, 1)
  }
}

const addDict = () => {
  const name = prompt('字典名称（中文）：')
  if (!name) return
  const code = prompt('字典编码（英文，如 dict_status）：', `dict_${name}`)
  if (!code) return
  const optsStr = prompt('选项（逗号分隔，如：选项A,选项B,选项C）：')
  const options = optsStr ? optsStr.split(/[,，]/).map((s, i) => ({ name: s.trim(), code: `opt_${i}` })) : []
  store.preview.dicts.push({ name, code, options })
}

const editDict = (idx: number) => {
  const d = store.preview.dicts[idx]
  if (!d) return
  const currentOpts = d.options?.map((o: any) => typeof o === 'string' ? o : o.name).join('，') || ''
  const newOpts = prompt(`编辑「${d.name}」的选项（逗号分隔）：`, currentOpts)
  if (newOpts === null) return
  d.options = newOpts.split(/[,，]/).filter(s => s.trim()).map((s, i) => ({
    name: s.trim(),
    code: (d.options?.[i] as any)?.code || `opt_${i}`
  }))
}

const removeDict = (idx: number) => {
  const d = store.preview.dicts[idx]
  if (!d) return
  if (confirm(`删除字典「${d.name}」？`)) {
    store.preview.dicts.splice(idx, 1)
  }
}

const conversationId = ref<number | null>(null)
const existingAppId = ref<number | null>(null)  // 从"继续完善"进来时，关联的已有应用ID
const generating = ref(false)

// ── Requirements mode ──
const isRequirementsMode = computed(() => currentAgent.value === 'requirements')
const docResultForCard = ref<any>(null)       // doc_result JSON for DesignDocCard
const generatingDoc = ref(false)               // 正在生成设计文档
const confirmingDoc = ref(false)               // 正在确认转换配置
const showEnvSelect = ref(false)
const selectedEnvId = ref<number | null>(null)
const showApiLogs = ref(false)
const apiLogs = ref<any[]>([])
const apiLogFilter = ref('')

watch(showApiLogs, async (val) => {
  if (val && existingAppId.value) {
    try {
      const params = new URLSearchParams({ page: '1', page_size: '200' })
      if (apiLogFilter.value === 'failed') params.set('success', 'false')
      const res = await request.get(`/applications/${existingAppId.value}/api-logs?${params}`)
      apiLogs.value = (res as any).items || []
    } catch { apiLogs.value = [] }
  }
})

const onEnvSelected = (envId: number) => {
  selectedEnvId.value = envId
  showEnvSelect.value = false
  // 继续生成流程
  startGenerateWithEnv(envId)
}

// ── 对话历史 ──
const conversationList = ref<ConversationWithApp[]>([])
const selectedConversationId = ref<number | null>(null)

const getConversationLabel = (conv: ConversationWithApp) => {
  if (conv.app_name) return conv.app_name
  const title = conv.title || '新对话'
  return title.length > 30 ? title.slice(0, 30) + '...' : title
}

const formatConvTime = (dateStr: string) => {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`
  if (diff < 86400000) return '今天'
  if (diff < 172800000) return '昨天'
  return `${d.getMonth() + 1}/${d.getDate()}`
}

const fetchConversationList = async () => {
  try {
    conversationList.value = await conversationApi.listWithApps({ agent_type: 'builder' })
    // 同步选中状态
    if (conversationId.value) {
      selectedConversationId.value = conversationId.value
    }
  } catch (e) {
    console.error('获取对话列表失败:', e)
  }
}

const loadConversation = async (cid: number) => {
  resetConversationWorkspace()
  conversationId.value = cid
  selectedConversationId.value = cid
  await syncBuilderModelFromConversation(cid)

  messages.splice(0, messages.length)

  try {
    const historyMessages = await conversationApi.getMessages(cid)
    if (historyMessages && historyMessages.length > 0) {
      for (const msg of historyMessages) {
        if (msg.role === 'system') {
          extractPreviewData(msg.content)
          continue
        }
        messages.push({
          id: msg.id,
          role: msg.role as any,
          agent: msg.role === 'assistant' ? 'builder' : undefined,
          content: msg.content,
          created_at: msg.created_at
        })
        if (msg.role === 'assistant') {
          extractPreviewData(msg.content)
        }
      }
      scrollToBottom()
    } else {
      // 空对话，显示欢迎消息
      messages.push({ id: 0, role: 'assistant', agent: 'builder', content: '你好！我是 aPaaS 智能搭建，可以帮你通过对话的方式在得帆云平台上快速搭建应用。\n\n你可以告诉我想要创建什么系统，我会帮你理清需求并自动生成。', created_at: '' })
    }

    // 恢复关联的应用配置
    if (!store.preview.appName && store.preview.models.length === 0) {
      try {
        const apps = await applicationApi.list() as any[]
        const linkedApp = apps.find((a: any) => a.conversation_id === cid && a.config_preview)
        if (linkedApp?.config_preview) {
          const data = linkedApp.config_preview.data || linkedApp.config_preview
          store.preview.appName = data.appName || ''
          store.preview.models = data.models || []
          store.preview.dicts = data.dicts || []
          store.preview.roles = data.roles || []
          store.preview.workflows = data.workflows || []
          store.preview.permissions = data.permissions || []
          store.currentApp = { name: store.preview.appName, status: 'draft' }
          if (linkedApp.id && typeof linkedApp.id === 'number') {
            existingAppId.value = linkedApp.id
          }
        }
      } catch { /* ignore */ }
    }

    // 更新 URL
    router.replace(`/chat/${cid}`)
  } catch (e) {
    console.error('加载对话失败:', e)
    messages.push({ id: 0, role: 'assistant', agent: 'builder', content: '加载对话历史失败，请重试。', created_at: '' })
  }
}

const onConversationSwitch = (newId: number) => {
  if (newId && newId !== conversationId.value) {
    loadConversation(newId)
  }
}

const startNewConversation = () => {
  resetConversationWorkspace()
  conversationId.value = null
  selectedConversationId.value = null
  persistedBuilderModelId.value = null
  selectedBuilderModelId.value = defaultBuilderModelId.value
  messages.splice(0, messages.length)
  messages.push({ id: 0, role: 'assistant', agent: 'builder', content: '你好！我是 aPaaS 智能搭建，可以帮你通过对话的方式在得帆云平台上快速搭建应用。\n\n你可以告诉我想要创建什么系统，我会帮你理清需求并自动生成。\n\n比如：\n• "我想做一个客户管理系统"\n• "帮我搭建一个项目管理应用"\n• "创建一个售后服务工单系统"', created_at: '' })
  router.replace('/chat')
}

// ── 文档版本 ──
interface DocVersion {
  id: number
  version: number
  filename: string
  summary: string
  raw_content: string
  created_at: string
}
const docVersions = ref<DocVersion[]>([])
const docVersionsLoading = ref(false)
const docPreviewVisible = ref(false)
const docPreviewContent = ref('')
const docPreviewTitle = ref('')
const docDiffVisible = ref(false)
const docDiffLeft = ref('')
const docDiffRight = ref('')
const docDiffLeftTitle = ref('')
const docDiffRightTitle = ref('')
// docUploadInputRef removed — upload is via chat input only

const fetchDocVersions = async () => {
  docVersionsLoading.value = true
  try {
    let res: any
    if (existingAppId.value) {
      res = await applicationApi.getDocVersions(existingAppId.value)
    } else if (conversationId.value) {
      res = await applicationApi.getDocVersionsByConversation(conversationId.value)
    } else {
      docVersionsLoading.value = false
      return
    }
    const versions = Array.isArray(res) ? res : (res?.versions || res?.data || [])
    docVersions.value = versions
  } catch (e) {
    console.error('Failed to fetch doc versions', e)
  } finally {
    docVersionsLoading.value = false
  }
}

const loadLatestDocForApp = async (appId: number) => {
  try {
    const verRes: any = await applicationApi.getDocVersions(appId)
    const versions = Array.isArray(verRes) ? verRes : (verRes?.versions || verRes?.data || [])
    const latest = [...versions].sort((a: any, b: any) => (b.version || 0) - (a.version || 0))[0]
    if (latest?.filename) lastParsedFilename.value = latest.filename
    latestDocContent.value = latest?.raw_content || ''
    if (!parsedAppCode.value && !loadedAppCode.value && latestDocContent.value) {
      const codeFromDoc = extractAppCodeFromText(latestDocContent.value)
      if (codeFromDoc) parsedAppCode.value = codeFromDoc
    }
  } catch {
    // ignore
  }
}

const formatDocTime = (dateStr: string) => {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const openDocPreview = (ver: DocVersion) => {
  docPreviewTitle.value = `V${ver.version} — ${ver.filename}`
  docPreviewContent.value = ver.raw_content || '（无内容）'
  docPreviewVisible.value = true
}

const openDocDiff = (ver: DocVersion) => {
  const prevVer = docVersions.value.find(v => v.version === ver.version - 1)
  if (!prevVer) return
  docDiffLeftTitle.value = `V${prevVer.version} — ${prevVer.filename}`
  docDiffRightTitle.value = `V${ver.version} — ${ver.filename}`
  docDiffLeft.value = prevVer.raw_content || ''
  docDiffRight.value = ver.raw_content || ''
  docDiffVisible.value = true
}

const computeLineDiff = (oldText: string, newText: string) => {
  const oldLines = oldText.split('\n')
  const newLines = newText.split('\n')
  // Simple LCS-based diff
  const m = oldLines.length, n = newLines.length
  const dp: number[][] = Array.from({ length: m + 1 }, () => Array(n + 1).fill(0))
  for (let i = 1; i <= m; i++) {
    const currentRow = dp[i]
    const prevRow = dp[i - 1]
    if (!currentRow || !prevRow) continue
    for (let j = 1; j <= n; j++) {
      const prevDiag = prevRow[j - 1] ?? 0
      const prevUp = prevRow[j] ?? 0
      const prevLeft = currentRow[j - 1] ?? 0
      currentRow[j] = oldLines[i - 1] === newLines[j - 1] ? prevDiag + 1 : Math.max(prevUp, prevLeft)
    }
  }

  const leftResult: { text: string; type: 'same' | 'removed' }[] = []
  const rightResult: { text: string; type: 'same' | 'added' }[] = []
  let i = m, j = n
  const leftTmp: typeof leftResult = []
  const rightTmp: typeof rightResult = []
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && oldLines[i - 1] === newLines[j - 1]) {
      leftTmp.push({ text: oldLines[i - 1] || '', type: 'same' })
      rightTmp.push({ text: newLines[j - 1] || '', type: 'same' })
      i--; j--
    } else if (j > 0 && (i === 0 || (dp[i]?.[j - 1] ?? 0) >= (dp[i - 1]?.[j] ?? 0))) {
      leftTmp.push({ text: '', type: 'same' })
      rightTmp.push({ text: newLines[j - 1] || '', type: 'added' })
      j--
    } else {
      leftTmp.push({ text: oldLines[i - 1] || '', type: 'removed' })
      rightTmp.push({ text: '', type: 'same' })
      i--
    }
  }
  leftTmp.reverse()
  rightTmp.reverse()
  return { left: leftTmp, right: rightTmp }
}

const docDiffResult = computed(() => {
  if (!docDiffLeft.value && !docDiffRight.value) return { left: [], right: [] }
  return computeLineDiff(docDiffLeft.value, docDiffRight.value)
})

// 变更摘要：从 diff 的新增行中提取结构化变更（章节标题、表单、字典、角色等）
const diffChangeSummary = computed(() => {
  const changes: { type: string; text: string }[] = []
  const addedLines = docDiffResult.value.right.filter(l => l.type === 'added').map(l => l.text.trim()).filter(Boolean)
  const removedLines = docDiffResult.value.left.filter(l => l.type === 'removed').map(l => l.text.trim()).filter(Boolean)

  // 提取新增的章节标题
  for (const line of addedLines) {
    if (line.startsWith('##')) {
      changes.push({ type: 'added', text: line.replace(/^#+\s*/, '') })
    } else if (line.startsWith('|') && line.includes('【新增】')) {
      const cells = line.split('|').map(c => c.trim()).filter(Boolean)
      changes.push({ type: 'added', text: cells[0] || line })
    } else if (line.includes('【新增') || line.includes('新增')) {
      const clean = line.replace(/^[\s|*-]+/, '').replace(/\*\*/g, '')
      if (clean.length < 60) changes.push({ type: 'added', text: clean })
    }
  }

  // 提取删除的章节
  for (const line of removedLines) {
    if (line.startsWith('##')) {
      changes.push({ type: 'removed', text: line.replace(/^#+\s*/, '') })
    }
  }

  // 提取修改的行（新增中包含已有章节名称的）
  for (const line of addedLines) {
    if (line.startsWith('|') && !line.includes('【新增】') && !line.startsWith('|--') && !line.startsWith('| 字')) {
      const cells = line.split('|').map(c => c.trim()).filter(Boolean)
      if (cells.length >= 2 && cells.some(c => c.includes('**'))) {
        changes.push({ type: 'modified', text: `${cells[0]}: 选项变更` })
      }
    }
  }

  // 去重
  const seen = new Set<string>()
  return changes.filter(c => {
    const key = c.type + c.text
    if (seen.has(key)) return false
    seen.add(key)
    return true
  }).slice(0, 30)
})

// triggerDocUpload / handleDocVersionUpload removed — doc upload is via chat input only

// ── 部署面板 ──
interface DeployStep { key: string; label: string; status: 'pending' | 'completed' | 'error'; deps_met: boolean; error?: string; result?: any }
const deployOpen = ref(false)
const deployAppId = ref<number | null>(null)
const deploySteps = ref<DeployStep[]>([])
const deployExecuting = ref<string | null>(null)
const deployRunningAll = ref(false)

// ── 编码冲突修复 ──
interface ConflictState {
  step: string
  model_name: string
  current_code: string
  message: string
  newCode: string
  resolving: boolean
}
const activeConflict = ref<ConflictState | null>(null)

const deployDoneCount = computed(() => deploySteps.value.filter(s => s.status === 'completed').length)
const deployPercent = computed(() => deploySteps.value.length ? Math.round(deployDoneCount.value / deploySteps.value.length * 100) : 0)
const deployAllDone = computed(() => deploySteps.value.length > 0 && deployDoneCount.value === deploySteps.value.length)
const parseReady = ref(false)

function buildAppCode(name: string): string {
  const ascii = (name || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  if (ascii) return ascii
  return `app-${Date.now().toString(36)}`
}

function pickAppCode(data: any): string {
  return (
    data?.appCode ||
    data?.app_code ||
    data?.app_info?.code ||
    data?.appInfo?.code ||
    ''
  )
}

function pickAppName(data: any): string {
  return (
    data?.appName ||
    data?.app_name ||
    data?.app_info?.name ||
    data?.appInfo?.name ||
    ''
  )
}

function extractAppCodeFromText(text: string): string {
  if (!text) return ''
  const patterns = [
    /应用编码[：:\s`]*([A-Za-z][A-Za-z0-9_-]{1,63})/i,
    /app[_\s-]?code[：:\s`]*([A-Za-z][A-Za-z0-9_-]{1,63})/i,
    /"code"\s*:\s*"([A-Za-z][A-Za-z0-9_-]{1,63})"/i,
  ]
  for (const p of patterns) {
    const m = text.match(p)
    if (m?.[1]) return m[1]
  }
  return ''
}

function resetConversationWorkspace() {
  store.reset()
  store.pendingFile = null
  store.pendingMarkdown = null
  existingAppId.value = null
  parsedAppCode.value = ''
  loadedAppCode.value = ''
  lastParsedFilename.value = ''
  latestDocContent.value = ''
  parseReady.value = false
  generating.value = false
  showEnvSelect.value = false
  selectedEnvId.value = null
  activeConflict.value = null
  isTyping.value = false
  showApiLogs.value = false
  apiLogs.value = []
  apiLogFilter.value = ''

  activeView.value = 'builder'
  platformIframeUrl.value = ''
  platformAppUrl.value = ''
  platformLoading.value = false
  platformError.value = ''
  platformLoginHint.value = ''

  docVersions.value = []
  docVersionsLoading.value = false
  docPreviewVisible.value = false
  docPreviewContent.value = ''
  docPreviewTitle.value = ''
  docDiffVisible.value = false
  docDiffLeft.value = ''
  docDiffRight.value = ''
  docDiffLeftTitle.value = ''
  docDiffRightTitle.value = ''

  deployOpen.value = false
  deployAppId.value = null
  deploySteps.value = []
  deployExecuting.value = null
  deployRunningAll.value = false
}

const deployGroups = computed(() => {
  const defs = [
    { title: '初始化', icon: '🚀', test: (s: DeployStep) => s.key === 'create_app' },
    { title: '角色', icon: '👥', test: (s: DeployStep) => s.key.startsWith('create_role:') || s.key === 'create_roles_dicts' },
    { title: '数据字典', icon: '📖', test: (s: DeployStep) => s.key.startsWith('create_dict:') },
    { title: '数据模型', icon: '🗃', test: (s: DeployStep) => s.key.startsWith('create_model:') },
    { title: '表单配置', icon: '📋', test: (s: DeployStep) => s.key.startsWith('create_form:') },
    { title: '权限配置', icon: '🔐', test: (s: DeployStep) => s.key === 'configure_permissions' },
  ]
  return defs.map(d => {
    const ss = deploySteps.value.filter(d.test)
    return { ...d, steps: ss, allDone: ss.length > 0 && ss.every(s => s.status === 'completed'), hasError: ss.some(s => s.status === 'error'), doneCount: ss.filter(s => s.status === 'completed').length }
  }).filter(d => d.steps.length > 0)
})

async function openDeployPanel() {
  if (existingAppId.value) {
    deployAppId.value = existingAppId.value
    deployOpen.value = true
    await loadDeployStatus()
  }
}

async function openInPlatform() {
  if (SHOW_PLATFORM_CONFIG && store.currentApp?.apaas_app_id) {
    switchToPlatform()
    return
  }
  router.push('/apps')
}

async function loadDeployStatus() {
  if (!deployAppId.value) return
  try {
    const resp = await applicationApi.getStepStatus(deployAppId.value)
    deploySteps.value = resp.steps || []
  } catch { /* ignore */ }
}

async function deployExec(key: string) {
  if (!deployAppId.value) return
  deployExecuting.value = key
  try {
    const resp = await applicationApi.executeStep(deployAppId.value, key)
    if (resp.status === 'conflict' && resp.conflict) {
      handleConflict(resp, key)
    } else if (resp.status === 'error') {
      // create_app 失败且涉及编码问题，弹出编码修改框
      if (key === 'create_app' && resp.error && (resp.error.includes('编码') || resp.error.includes('code') || resp.error.includes('Code'))) {
        try {
          const { value: newCode } = await ElMessageBox.prompt(
            `创建失败：${resp.error}\n\n请输入新的应用编码（如 asset-manage）：`,
            '修改应用编码',
            {
              inputValue: 'app-' + Date.now().toString(36),
              inputPattern: /^[a-zA-Z][a-zA-Z0-9\-]*$/,
              inputErrorMessage: '编码只能包含英文字母、数字和连字符(-)，且以字母开头',
              confirmButtonText: '重试',
              cancelButtonText: '取消'
            }
          )
          if (newCode) {
            // 更新后端应用编码
            await request.patch(`/applications/${deployAppId.value}/code`, { app_code: newCode })
            // 重置步骤并重试
            await applicationApi.resetStep(deployAppId.value, key)
            await loadDeployStatus()
            deployExecuting.value = null
            await deployExec(key)
            return
          }
        } catch { /* cancelled */ }
      } else {
        ElMessage.error(resp.error || '失败')
      }
    }
  } catch (e: any) { ElMessage.error(e.message || '失败') }
  finally { deployExecuting.value = null; await loadDeployStatus() }
}

async function deployRedo(key: string) {
  if (!deployAppId.value) return
  await applicationApi.resetStep(deployAppId.value, key)
  await loadDeployStatus()
  await deployExec(key)
}

async function deployRunAll() {
  if (!deployAppId.value || deployRunningAll.value || deployExecuting.value !== null || deployAllDone.value) return

  deployRunningAll.value = true
  try {
    for (const s of deploySteps.value) {
      if (s.status === 'completed') continue
      await loadDeployStatus()
      const fresh = deploySteps.value.find(x => x.key === s.key)
      if (!fresh?.deps_met) continue
      deployExecuting.value = s.key
      const resp = await applicationApi.executeStep(deployAppId.value, s.key)
      await loadDeployStatus()
      if (resp.status === 'conflict' && resp.conflict) {
        handleConflict(resp, s.key)
        deployExecuting.value = null
        return  // 暂停，等用户修复冲突后可再次一键执行
      }
      if (resp.status === 'error') {
        ElMessage.error(resp.error + '，已暂停')
        deployExecuting.value = null
        return
      }
    }
    deployExecuting.value = null
    ElMessage.success('全部完成！')
  } catch (e: any) {
    ElMessage.error(e.message || '失败')
  } finally {
    deployExecuting.value = null
    deployRunningAll.value = false
    await loadDeployStatus()
  }
}
function handleConflict(resp: any, stepKey: string) {
  const c = resp.conflict
  // 在对话区显示冲突信息
  messages.push({
    id: Date.now(),
    role: 'assistant',
    agent: 'builder',
    content: `\u26a0\ufe0f **编码冲突**：${c.model_name}的编码 \`${c.current_code}\` 在平台上已存在。\n\n请在下方输入一个新的编码来替换它：`,
    created_at: new Date().toISOString(),
  })
  scrollToBottom()
  // 设置冲突状态
  activeConflict.value = {
    step: stepKey,
    model_name: c.model_name,
    current_code: c.current_code,
    message: c.message,
    newCode: c.current_code + '_v2',
    resolving: false,
  }
}

async function resolveConflictAndRetry() {
  if (!activeConflict.value || !deployAppId.value) return
  const c = activeConflict.value
  if (!c.newCode.trim()) { ElMessage.warning('请输入新编码'); return }
  if (c.newCode === c.current_code) { ElMessage.warning('新编码不能和旧编码相同'); return }

  c.resolving = true
  try {
    await applicationApi.resolveConflict(deployAppId.value, {
      step: c.step,
      model_name: c.model_name,
      old_code: c.current_code,
      new_code: c.newCode,
    })
    // 在对话区显示修复成功
    messages.push({
      id: Date.now(),
      role: 'assistant',
      agent: 'builder',
      content: `\u2705 编码已更新：\`${c.current_code}\` \u2192 \`${c.newCode}\`\n\n正在重试该步骤...`,
      created_at: new Date().toISOString(),
    })
    scrollToBottom()
    const conflictStep = c.step
    activeConflict.value = null
    // 重新加载配置预览（编码已变）
    try {
      const appData = await applicationApi.get(deployAppId.value) as any
      if (appData.config_preview) {
        const cfg = typeof appData.config_preview === 'string' ? JSON.parse(appData.config_preview) : appData.config_preview
        const d = cfg.data || cfg
        store.preview = { appName: appData.app_name, models: d.models || [], roles: d.roles || [], dicts: d.dicts || [], workflows: d.workflows || [], permissions: d.permissions || [] }
      }
    } catch { /* ignore */ }
    // 自动重试
    await deployExec(conflictStep)
  } catch (e: any) {
    ElMessage.error(e.message || '修复失败')
  } finally {
    if (activeConflict.value) activeConflict.value.resolving = false
  }
}

function cancelConflict() {
  activeConflict.value = null
  messages.push({
    id: Date.now(),
    role: 'assistant',
    agent: 'builder',
    content: '\u274c 已取消编码修复。你可以在部署面板中点击"重试"来重新执行该步骤。',
    created_at: new Date().toISOString(),
  })
  scrollToBottom()
}

const startGenerate = async () => {
  // 检查是否已部署到平台（有 apaas_app_id）
  if (existingAppId.value) {
    const existingApp = await applicationApi.get(existingAppId.value)
    if ((existingApp as any).apaas_app_id) {
      // 先检查是否有未完成的步骤 — 如果有，直接打开部署面板继续
      try {
        const stepStatus = await applicationApi.getStepStatus(existingAppId.value)
        const steps = stepStatus.steps || []
        const hasIncomplete = steps.some((s: any) => s.status !== 'completed')
        if (hasIncomplete) {
          // 有未完成步骤，直接打开部署面板继续
          deployAppId.value = existingAppId.value
          deployOpen.value = true
          await loadDeployStatus()
          return
        }
      } catch { /* ignore */ }
      // 已全部完成，打开部署面板查看
      deployAppId.value = existingAppId.value
      deployOpen.value = true
      await loadDeployStatus()
      return
    }
    // 应用已绑定环境？直接继续
    if ((existingApp as any).platform_env_id) {
      selectedEnvId.value = (existingApp as any).platform_env_id
    }
  }

  // 检查是否有可用环境
  if (!selectedEnvId.value) {
    try {
      const envs = await platformEnvApi.list()
      const defaultEnv = envs.find(e => e.is_default && e.status === 'connected')
      if (defaultEnv) {
        selectedEnvId.value = defaultEnv.id
      } else if (envs.some(e => e.status === 'connected')) {
        // 有已连接环境但没默认，弹出选择
        showEnvSelect.value = true
        return
      } else {
        // 没有任何已连接环境
        ElMessage.warning('请先连接平台环境')
        store.showConnectModal = true
        return
      }
    } catch {
      ElMessage.warning('请先连接平台环境')
      store.showConnectModal = true
      return
    }
  }

  await startGenerateWithEnv(selectedEnvId.value!)
}

const startGenerateWithEnv = async (envId: number) => {
  generating.value = true
  try {
    const appCode = parsedAppCode.value || buildAppCode(store.preview.appName)

    const payload = {
      conversation_id: conversationId.value || 0,
      app_name: store.preview.appName,
      app_code: appCode,
      description: store.preview.appName,
      platform_env_id: envId,
      config_preview: {
        type: 'preview',
        data: { ...store.preview }
      }
    }

    let newAppId: number
    if (existingAppId.value) {
      const app = await applicationApi.update(existingAppId.value, payload)
      newAppId = (app as any).id
      loadedAppCode.value = (app as any).app_code || appCode
    } else {
      const app = await applicationApi.create(payload)
      newAppId = (app as any).id
      existingAppId.value = newAppId
      loadedAppCode.value = (app as any).app_code || appCode
    }
    parsedAppCode.value = parsedAppCode.value || loadedAppCode.value || appCode
    // 不跳转，在本页打开部署面板
    deployAppId.value = newAppId
    deployOpen.value = true
    await loadDeployStatus()
  } catch (e: any) {
    ElMessage.error('创建应用失败: ' + (e.message || ''))
  } finally {
    generating.value = false
  }
}

const uploadDocFile = async (file: File) => {
  const fileText = await file.text()
  const codeFromDoc = extractAppCodeFromText(fileText)
  if (codeFromDoc) {
    parsedAppCode.value = codeFromDoc
  }

  const userMsgId = Date.now()
  messages.push({ id: userMsgId, role: 'user', content: `📄 上传设计文档: ${file.name}`, created_at: '' })

  // 结构化进度状态
  const progressMsgId = userMsgId + 1
  const phases = reactive<Record<string, { icon: string, label: string, status: string, detail: string }>>({
    skeleton: { icon: '📋', label: '提取骨架', status: 'pending', detail: '' },
    dicts: { icon: '📖', label: '字典选项', status: 'pending', detail: '' },
    models: { icon: '🗃', label: '模型字段', status: 'pending', detail: '' },
    complete: { icon: '✨', label: '拼装配置', status: 'pending', detail: '' },
  })

  const buildProgressContent = () => {
    const lines = [`**📄 解析文档：${file.name}**\n`]
    const code = parsedAppCode.value || loadedAppCode.value
    if (code) lines.push(`应用编码：\`${code}\``)
    for (const [, p] of Object.entries(phases)) {
      const icon = p.status === 'done' ? '✅' : p.status === 'running' ? '🔄' : '○'
      lines.push(`${icon} **${p.label}**　${p.detail}`)
    }
    return lines.join('\n')
  }

  messages.push({ id: progressMsgId, role: 'assistant', agent: 'builder', content: buildProgressContent(), created_at: '' })
  scrollToBottom()

  try {
    const token = localStorage.getItem('token')
    const formData = new FormData()
    formData.append('file', file)

    const response = await fetch(`${API_PREFIX}/applications/upload-doc-with-conversation`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}` },
      body: formData
    })

    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: '请求失败' }))
      throw new Error(err.detail || '文档上传失败')
    }

    const reader = response.body?.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let finalResult: any = null

    while (reader) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      let currentEvent = ''
      for (const line of lines) {
        if (line.startsWith('event:')) {
          currentEvent = line.slice(6).trim()
        } else if (line.startsWith('data:')) {
          const dataStr = line.slice(5).trim()
          if (!dataStr) continue
          try {
            const data = JSON.parse(dataStr)

            if (currentEvent === 'progress') {
              const msg = data.message || ''
              // 解析 [phase] message 格式
              const phaseMatch = msg.match(/^\[(\w+)\]\s*(.*)/)
              if (phaseMatch) {
                const [, phase, detail] = phaseMatch
                if (phases[phase]) {
                  phases[phase].status = 'running'
                  phases[phase].detail = detail

                  // 如果当前 phase 完成了
                  if (detail.includes('完成')) {
                    phases[phase].status = 'done'
                  }
                }
              }

              // 实时更新预览：字典批次
              if (data.batch && Array.isArray(data.batch)) {
                const phaseKey = phaseMatch?.[1] || ''
                if (phaseKey === 'dicts') {
                  for (const d of data.batch) {
                    if (!store.preview.dicts.find((x: any) => x.code === d.code)) {
                      store.preview.dicts.push(d)
                    }
                  }
                } else if (phaseKey === 'models') {
                  for (const m of data.batch) {
                    if (!store.preview.models.find((x: any) => x.code === m.code)) {
                      store.preview.models.push(m)
                    }
                  }
                } else if (phaseKey === 'workflows') {
                  for (const w of data.batch) {
                    store.preview.workflows.push(w)
                  }
                } else if (phaseKey === 'permissions') {
                  if (!store.preview.permissions) store.preview.permissions = []
                  for (const p of data.batch) {
                    const existing = store.preview.permissions.find((x: any) => x.form === p.form)
                    if (existing) Object.assign(existing, p)
                    else store.preview.permissions.push(p)
                  }
                }
              }

              // 骨架完成时设置基础信息
              if (data.data) {
                const skeletonName = pickAppName(data.data)
                const skeletonCode = pickAppCode(data.data)
                if (skeletonName && !store.preview.appName) {
                  store.preview.appName = skeletonName
                  store.currentApp = { name: skeletonName, status: 'draft' }
                }
                if (skeletonCode) {
                  parsedAppCode.value = skeletonCode
                } else if (!parsedAppCode.value && store.preview.appName) {
                  parsedAppCode.value = buildAppCode(store.preview.appName)
                }
                if (!store.preview.roles.length && Array.isArray(data.data.roles)) {
                  store.preview.roles = data.data.roles
                }
              }

              // 更新进度消息
              const pmsg = messages.find(m => m.id === progressMsgId)
              if (pmsg) {
                pmsg.content = buildProgressContent()
              }
              scrollToBottom()

            } else if (currentEvent === 'done') {
              finalResult = data
            } else if (currentEvent === 'error') {
              throw new Error(data.message || '文档解析失败')
            }
          } catch (parseErr: any) {
            if (parseErr.message && !parseErr.message.includes('JSON')) throw parseErr
          }
        }
      }
    }

    // 完成：更新进度消息为最终总结
    const pmsg = messages.find(m => m.id === progressMsgId)

    if (finalResult) {
      conversationId.value = finalResult.conversation_id
      router.replace(`/chat/${finalResult.conversation_id}`)
      lastParsedFilename.value = file.name
      latestDocContent.value = fileText

      // 最终更新 store
      const previewData = finalResult.preview?.data || finalResult.preview
      const appName = pickAppName(previewData)
      const appCode = pickAppCode(previewData)
      if (previewData?.appName || previewData?.models || appName || appCode) {
        store.currentApp = { name: appName || store.preview.appName || '未命名应用', status: 'draft' }
        store.preview.appName = appName || store.preview.appName || ''
        parsedAppCode.value = appCode || parsedAppCode.value || buildAppCode(store.preview.appName)
        store.preview.roles = previewData.roles || []
        store.preview.dicts = previewData.dicts || []
        store.preview.models = previewData.models || []
        store.preview.workflows = previewData.workflows || []
        store.preview.permissions = previewData.permissions || []
      }

      // 文档上传完成后自动创建 Application（如果还没有）
      if (!existingAppId.value && store.preview.appName) {
        try {
          const result = await applicationApi.autoCreate({
            app_name: store.preview.appName,
            config_preview: { ...store.preview },
            conversation_id: conversationId.value || undefined,
          })
          existingAppId.value = result.app_id
          loadedAppCode.value = result.app_code || ''
          parsedAppCode.value = parsedAppCode.value || loadedAppCode.value
          router.replace({ query: { ...route.query, app_id: String(result.app_id) } })
          console.log(`Doc upload auto-created app: id=${result.app_id}, is_new=${result.is_new}`)
        } catch (e) {
          console.warn('文档上传后自动创建应用失败:', e)
        }
      }

      // 文档上传完成后自动刷新文档版本列表
      fetchDocVersions()

      // 替换进度消息为完成总结
      const completePhase = phases.complete
      if (pmsg && completePhase) {
        completePhase.status = 'done'
        completePhase.detail = `${store.preview.models.length} 模型, ${store.preview.dicts.length} 字典, ${store.preview.roles.length} 角色`
        parseReady.value = true
        pmsg.content = buildProgressContent() + '\n\n配置已就绪，请点击下方「开始生成」。'
      }
    } else if (pmsg) {
      pmsg.content += '\n\n⚠️ 解析完成但未获取到配置数据'
    }
  } catch (err: any) {
    const pmsg = messages.find(m => m.id === progressMsgId)
    if (pmsg) {
      pmsg.content += `\n\n❌ 解析失败: ${err?.message || '未知错误'}`
    } else {
      messages.push({ id: Date.now(), role: 'assistant', agent: 'builder', content: `文档解析失败: ${err?.message || '未知错误'}`, created_at: '' })
    }
  }
  scrollToBottom()
}

const handleDocUpload = async (e: Event) => {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  target.value = '' // reset for re-upload
  await uploadDocFile(file)
}

// ── 上传文档新版本并分析变更（占位，保留以备将来使用）──
const handleDocVersionUpload = async (file: File, appId: number) => {
  const userMsgId = Date.now()
  messages.push({ id: userMsgId, role: 'user', content: `📄 上传文档新版本: ${file.name}`, created_at: '' })

  const progressMsgId = userMsgId + 1
  messages.push({
    id: progressMsgId,
    role: 'assistant',
    agent: 'builder',
    content: '正在分析文档变更...',
    created_at: ''
  })
  scrollToBottom()

  try {
    // 如果没有会话ID，自动创建一个关联到当前应用
    if (!conversationId.value) {
      try {
        const newConv = await conversationApi.create({
          agent_type: 'builder',
          ...(selectedBuilderModelId.value != null ? { selected_llm_config_id: selectedBuilderModelId.value } : {}),
        })
        conversationId.value = newConv.id
        selectedConversationId.value = newConv.id
        applyBuilderModelSelection(newConv.selected_llm_config_id)
      } catch {
        throw new Error('创建会话失败')
      }
    }
    const token = localStorage.getItem('token')
    const formData = new FormData()
    formData.append('file', file)
    formData.append('conversation_id', conversationId.value.toString())

    const url = applicationApi.uploadDocVersionUrl(appId)
    const response = await fetch(url, {
      method: 'POST',
      headers: token ? { 'Authorization': `Bearer ${token}` } : {},
      body: formData
    })

    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: '请求失败' }))
      throw new Error(err.detail || '文档上传失败')
    }

    const reader = response.body?.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let changePlanData: any = null

    while (reader) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      let currentEvent = ''
      for (const line of lines) {
        if (line.startsWith('event:')) {
          currentEvent = line.slice(6).trim()
        } else if (line.startsWith('data:')) {
          const dataStr = line.slice(5).trim()
          if (!dataStr) continue
          try {
            const data = JSON.parse(dataStr)

            if (currentEvent === 'progress') {
              const pmsg = messages.find(m => m.id === progressMsgId)
              if (pmsg) {
                const step = data.step || data.phase || ''
                const msg = data.message || ''
                const icon = step === 'indexing' ? '📑' : step === 'parsing' ? '🔍' : step === 'diffing' ? '📊' : '⏳'
                pmsg.content = `${icon} ${msg}`
              }
              scrollToBottom()
            } else if (currentEvent === 'done') {
              changePlanData = data.change_plan || data
              // P0: 用 V2 配置更新 preview store
              if (data.parsed_config) {
                const pc = data.parsed_config.data || data.parsed_config
                store.preview.appName = pc.appName || store.preview.appName
                store.preview.models = pc.models || []
                store.preview.dicts = pc.dicts || []
                store.preview.roles = pc.roles || []
                store.preview.workflows = pc.workflows || []
                store.preview.permissions = pc.permissions || []
                store.currentApp = { name: store.preview.appName, status: 'draft' }
              }
            } else if (currentEvent === 'error') {
              throw new Error(data.message || '文档分析失败')
            }
          } catch (parseErr: any) {
            if (parseErr.message && !parseErr.message.includes('JSON')) throw parseErr
          }
        }
      }
    }

    // 处理变更计划
    if (changePlanData) {
      // 确保 actions 有 selected 属性
      if (changePlanData.actions) {
        changePlanData.actions = changePlanData.actions.map((a: any) => ({
          ...a,
          selected: a.selected !== undefined ? a.selected : true
        }))
      }
      // 映射后端字段名到前端期望的字段名
      const toVersion = changePlanData.version || 1
      store.changePlan = {
        ...changePlanData,
        id: changePlanData.change_plan_id || changePlanData.id,
        fromVersion: changePlanData.is_first_version ? 0 : (toVersion - 1),
        toVersion: toVersion,
        diffSummary: changePlanData.diff || changePlanData.diffSummary,
      }
      store.showChangePlan = true

      const pmsg = messages.find(m => m.id === progressMsgId)
      if (pmsg) {
        // op 格式为 add_model, add_dict, modify_field, remove_role 等
        const addCount = changePlanData.actions?.filter((a: any) => a.op?.startsWith('add')).length || 0
        const modCount = changePlanData.actions?.filter((a: any) => a.op?.startsWith('modify') || a.op?.startsWith('update')).length || 0
        const delCount = changePlanData.actions?.filter((a: any) => a.op?.startsWith('remove') || a.op?.startsWith('delete')).length || 0
        pmsg.content = `📊 文档变更分析完成：新增 ${addCount} 项，修改 ${modCount} 项，删除 ${delCount} 项。\n\n请在右侧面板确认要执行的变更。`
      }
    } else {
      const pmsg = messages.find(m => m.id === progressMsgId)
      if (pmsg) {
        pmsg.content = '文档分析完成，未发现配置变更。'
      }
    }
  } catch (err: any) {
    const pmsg = messages.find(m => m.id === progressMsgId)
    if (pmsg) {
      pmsg.content = `❌ 文档变更分析失败: ${err?.message || '未知错误'}`
    } else {
      messages.push({
        id: Date.now(),
        role: 'assistant',
        agent: 'builder',
        content: `文档变更分析失败: ${err?.message || '未知错误'}`,
        created_at: ''
      })
    }
  }
  scrollToBottom()
}

const executeChangePlan = async () => {
  if (!store.changePlan || !existingAppId.value) return
  const appId = existingAppId.value
  const planId = store.changePlan.id

  executingChangePlan.value = true

  // 构建 selections
  const selections: Record<string, boolean> = {}
  store.changePlan.actions.forEach(a => {
    selections[a.id] = a.selected
  })

  const execMsgId = Date.now()
  messages.push({
    id: execMsgId,
    role: 'assistant',
    agent: 'builder',
    content: '正在执行变更计划...',
    created_at: ''
  })
  scrollToBottom()

  try {
    // 先提交 selections
    await applicationApi.updateSelections(appId, planId, selections)

    // SSE 执行
    const token = localStorage.getItem('token')
    const url = applicationApi.executeChangePlanUrl(appId, planId)
    const response = await fetch(url, {
      method: 'POST',
      headers: token ? { 'Authorization': `Bearer ${token}` } : {}
    })

    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: '请求失败' }))
      throw new Error(err.detail || '执行失败')
    }

    const reader = response.body?.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let updatedConfig: any = null

    while (reader) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      let currentEvent = ''
      for (const line of lines) {
        if (line.startsWith('event:')) {
          currentEvent = line.slice(6).trim()
        } else if (line.startsWith('data:')) {
          const dataStr = line.slice(5).trim()
          if (!dataStr) continue
          try {
            const data = JSON.parse(dataStr)

            if (currentEvent === 'progress') {
              const emsg = messages.find(m => m.id === execMsgId)
              if (emsg) {
                const msg = data.message || ''
                const step = data.step || ''
                const icon = data.status === 'done' ? '✅' : '⏳'
                emsg.content = `${icon} ${msg || step}`
              }
              scrollToBottom()
            } else if (currentEvent === 'done') {
              updatedConfig = data.updated_config || data.config || data
            } else if (currentEvent === 'error') {
              throw new Error(data.message || '执行失败')
            }
          } catch (parseErr: any) {
            if (parseErr.message && !parseErr.message.includes('JSON')) throw parseErr
          }
        }
      }
    }

    // 完成：更新 store
    if (updatedConfig) {
      const previewData = updatedConfig.data || updatedConfig
      if (previewData.appName || previewData.models) {
        store.preview.appName = previewData.appName || store.preview.appName
        store.preview.roles = previewData.roles || store.preview.roles
        store.preview.dicts = previewData.dicts || store.preview.dicts
        store.preview.models = previewData.models || store.preview.models
        store.preview.workflows = previewData.workflows || store.preview.workflows
        store.preview.permissions = previewData.permissions || store.preview.permissions
      }
    }

    const emsg = messages.find(m => m.id === execMsgId)
    if (emsg) {
      emsg.content = `✅ 变更计划执行完成！已选 ${changePlanSelectedCount.value} 项变更已应用。`
    }

    // 关闭面板
    store.showChangePlan = false
    store.changePlan = null
  } catch (err: any) {
    const emsg = messages.find(m => m.id === execMsgId)
    if (emsg) {
      emsg.content = `❌ 变更执行失败: ${err?.message || '未知错误'}`
    }
  } finally {
    executingChangePlan.value = false
  }
  scrollToBottom()
}

// ── 分阶段生成配置 ──
const assembling = ref(false)
const assembleMessage = ref('')

const startAssembleConfig = async () => {
  if (!conversationId.value) {
    await createConversation()
  }
  if (!conversationId.value) return

  assembling.value = true
  assembleMessage.value = '正在分析需求...'

  // 收集最近的用户消息作为需求
  const userMessages = messages.filter(m => m.role === 'user').map(m => m.content)
  const prompt = userMessages.join('\n') || '请根据对话内容生成应用配置'

  try {
    const token = localStorage.getItem('token')
    const response = await fetch(`${API_PREFIX}/chat/generate-config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({ conversation_id: conversationId.value, message: prompt })
    })

    if (!response.ok) throw new Error('请求失败')

    const reader = response.body?.getReader()
    const decoder = new TextDecoder()
    if (!reader) throw new Error('无法读取响应')

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      const chunk = decoder.decode(value, { stream: true })
      for (const line of chunk.split('\n')) {
        if (!line.startsWith('data: ')) continue
        try {
          const evt = JSON.parse(line.slice(6))

          if (evt.phase && evt.message) {
            assembleMessage.value = evt.message
          }

          // 骨架完成 → 显示模型名和字典名（占位）
          if (evt.phase === 'skeleton' && evt.status === 'done' && evt.data) {
            const sk = evt.data
            store.preview.appName = sk.appName || ''
            store.preview.roles = sk.roles || []
            // 用骨架的 dict_names 创建空字典占位
            store.preview.dicts = (sk.dict_names || []).map((d: any) => ({
              name: d.name, code: d.code, options: []
            }))
            // 用骨架的 model_names 创建空模型占位
            store.preview.models = (sk.model_names || []).map((m: any) => ({
              name: m.name, code: m.code, fields: []
            }))
            store.currentApp = { name: store.preview.appName, status: 'draft' }
          }

          // 字典批次完成 → 更新对应字典的选项
          if (evt.phase === 'dicts' && evt.batch) {
            for (const newDict of evt.batch) {
              const existing = store.preview.dicts.find(
                (d: any) => d.code === newDict.code || d.name === newDict.name
              )
              if (existing) {
                existing.options = newDict.options || []
                if (newDict.code) existing.code = newDict.code
              } else {
                store.preview.dicts.push(newDict)
              }
            }
          }

          // 模型批次完成 → 更新对应模型的字段
          if (evt.phase === 'models' && evt.batch) {
            for (const newModel of evt.batch) {
              const existing = store.preview.models.find(
                (m: any) => m.code === newModel.code || m.name === newModel.name
              )
              if (existing) {
                existing.fields = newModel.fields || []
                if (newModel.code) existing.code = newModel.code
              } else {
                store.preview.models.push(newModel)
              }
            }
          }

          // 流程批次完成 → 更新 workflows
          if (evt.phase === 'workflows' && evt.batch) {
            for (const wf of evt.batch) {
              const existing = store.preview.workflows.find((w: any) => w.name === wf.name || w.form === wf.form)
              if (existing) Object.assign(existing, wf)
              else store.preview.workflows.push(wf)
            }
          }

          // 权限批次完成 → 更新 permissions
          if (evt.phase === 'permissions' && evt.batch) {
            if (!store.preview.permissions) store.preview.permissions = []
            for (const p of evt.batch) {
              const existing = store.preview.permissions.find((x: any) => x.form === p.form)
              if (existing) Object.assign(existing, p)
              else store.preview.permissions.push(p)
            }
          }

          // 完整配置 → 最终覆盖
          if (evt.phase === 'complete' && evt.data) {
            const d = evt.data
            store.preview.appName = d.appName || store.preview.appName
            store.preview.roles = d.roles || store.preview.roles
            store.preview.dicts = d.dicts || store.preview.dicts
            store.preview.models = d.models || store.preview.models
            store.preview.workflows = d.workflows || []
            store.preview.permissions = d.permissions || []
            store.currentApp = { name: store.preview.appName, status: 'draft' }
          }

          if (evt.type === 'done') break

        } catch (e) { /* ignore parse errors */ }
      }
    }

    // 添加完成消息到对话
    messages.push({
      id: Date.now(), role: 'assistant', agent: 'builder',
      content: `配置生成完成！${store.preview.models.length} 个模型、${store.preview.dicts.length} 个字典、${store.preview.roles.length} 个角色。\n\n可以直接编辑右侧预览，或点击 **开始生成** 部署到平台。`,
      created_at: ''
    })
    scrollToBottom()

  } catch (e: any) {
    ElMessage.error(`配置生成失败: ${e.message}`)
  } finally {
    assembling.value = false
    assembleMessage.value = ''
  }
}

const createConversation = async () => {
  const token = localStorage.getItem('token')
  const res = await fetch(`${API_PREFIX}/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
    body: JSON.stringify({
      agent_type: currentAgent.value,
      ...(selectedBuilderModelId.value != null ? { selected_llm_config_id: selectedBuilderModelId.value } : {}),
    })
  })
  if (res.ok) {
    const data = await res.json()
    conversationId.value = data.id
    selectedConversationId.value = data.id
    applyBuilderModelSelection(data.selected_llm_config_id)
    // 更新 URL，刷新后能恢复对话
    router.replace(`/chat/${data.id}`)
    // 刷新对话列表
    fetchConversationList()
  }
}

const sendMessage = async () => {
  if (!inputText.value.trim()) return
  const text = inputText.value.trim()
  inputText.value = ''
  messages.push({ id: Date.now(), role: 'user', content: text, created_at: '' })
  scrollToBottom()
  isTyping.value = true

  // 如果还没有对话，先创建
  if (!conversationId.value) {
    await createConversation()
  }

  if (!conversationId.value) {
    isTyping.value = false
    messages.push({ id: Date.now(), role: 'assistant', agent: currentAgent.value, content: '创建对话失败，请重试。', created_at: '' })
    scrollToBottom()
    return
  }

  // 调用后端API
  try {
    const token = localStorage.getItem('token')
    // 统一使用 /chat/send，后端根据 conversation.agent_type 选择 system prompt
    const chatUrl = `${API_PREFIX}/chat/send`
    const chatBody = JSON.stringify({
      conversation_id: conversationId.value,
      message: text,
      ...(isRequirementsMode.value ? {} : (store.preview.appName ? { current_config: { ...store.preview } } : {}))
    })
    const response = await fetch(chatUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: chatBody
    })

    if (!response.ok) throw new Error('发送失败')

    const reader = response.body?.getReader()
    const decoder = new TextDecoder()
    let assistantContent = ''

    if (!reader) throw new Error('无法读取响应')

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      const chunk = decoder.decode(value, { stream: true })
      const lines = chunk.split('\n')

      for (const line of lines) {
        if (line.startsWith('data: ') || line.startsWith('data:')) {
          const dataStr = line.startsWith('data: ') ? line.slice(6) : line.slice(5)
          if (!dataStr.trim()) continue
          try {
            const parsed = JSON.parse(dataStr)

            // 统一 SSE 格式: {"type": "message|thinking|done", "data": "..."}
            if (parsed.type === 'thinking') {
              // AI 正在思考
            } else if (parsed.type === 'message') {
              isTyping.value = false
              assistantContent += parsed.data
              const lastMsg = messages[messages.length - 1]
              if (lastMsg && lastMsg.role === 'assistant' && lastMsg.agent === currentAgent.value && lastMsg.id === -1) {
                lastMsg.content = assistantContent
              } else {
                messages.push({ id: -1, role: 'assistant', agent: currentAgent.value, content: assistantContent, created_at: '' })
              }
              scrollToBottom()
            } else if (parsed.type === 'done') {
              isTyping.value = false
              const lastMsg = messages[messages.length - 1]
              if (lastMsg && lastMsg.id === -1) lastMsg.id = Date.now()
              if (isRequirementsMode.value) {
                // 检测 AI 回复标记
                const hasBuildTrigger = assistantContent.includes('<!-- TRIGGER_BUILD -->')
                const hasDesignComplete = assistantContent.includes('<!-- DESIGN_COMPLETE -->')
                if (hasBuildTrigger || hasDesignComplete) {
                  // 清理标记
                  if (lastMsg) {
                    lastMsg.content = assistantContent
                      .replace('<!-- TRIGGER_BUILD -->', '')
                      .replace('<!-- DESIGN_COMPLETE -->', '')
                      .trim()
                  }
                  if (hasBuildTrigger) {
                    // 用户确认了，触发完整的生成流程
                    triggerFullBuildPipeline()
                  } else {
                    // 设计文档完成，后台生成 JSON 等用户确认
                    generateDocInBackground()
                  }
                }
              } else {
                extractPreviewData(assistantContent)
                if (!store.currentApp && assistantContent.length > 50) {
                  const appNameMatch = assistantContent.match(/搭建.*?[**](.+?)[**]/)
                  if (appNameMatch) {
                    store.currentApp = { name: appNameMatch[1] || '', status: 'talking' }
                  }
                }
              }
            }
          } catch (e) { /* ignore parse errors */ }
        }
      }
    }
  } catch (error) {
    console.error('Send error:', error)
    isTyping.value = false
    messages.push({ id: Date.now(), role: 'assistant', agent: currentAgent.value, content: '发送失败，请重试。', created_at: '' })
    scrollToBottom()
  }
}

// ── Requirements: 完整生成流程（用户确认后触发） ──
// generate-doc → convert-config → create app → show deploy panel
const triggerFullBuildPipeline = async () => {
  if (!conversationId.value || generatingDoc.value) return
  generatingDoc.value = true

  // 添加进度消息
  const progressMsgId = Date.now()
  messages.push({
    id: progressMsgId,
    role: 'assistant',
    agent: 'requirements',
    content: '⏳ 正在解析需求，生成应用配置...',
    created_at: '',
  })
  scrollToBottom()

  try {
    // Step 1: Generate structured JSON from conversation
    const token = localStorage.getItem('token') || ''
    const url = requirementsApi.generateDocUrl(conversationId.value)
    const response = await fetch(url, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    })
    if (!response.ok) throw new Error(`生成文档失败: HTTP ${response.status}`)

    const reader = response.body?.getReader()
    if (!reader) throw new Error('无法读取响应流')
    const decoder = new TextDecoder()
    let buffer = ''
    let docResult: any = null

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        if (line.startsWith('data:')) {
          try {
            const data = JSON.parse(line.slice(5).trim())
            if (data.doc_result) docResult = data.doc_result
          } catch { /* ignore */ }
        }
      }
    }

    if (!docResult) throw new Error('未能生成设计文档')

    // Update progress
    const pMsg = messages.find(m => m.id === progressMsgId)
    if (pMsg) pMsg.content = '⏳ 正在转换为应用配置...'
    scrollToBottom()

    // Step 2: Convert AnalysisResult → AppConfig
    const appConfig = await convertConfig(docResult)

    // Step 3: Switch to builder mode
    await conversationApi.updateAgentType(conversationId.value, 'builder')
    currentAgent.value = 'builder'

    // Step 4: Populate preview store
    store.preview = {
      appName: appConfig.appName || '',
      roles: appConfig.roles || [],
      dicts: appConfig.dicts || [],
      models: appConfig.models || [],
      workflows: appConfig.workflows || [],
      permissions: appConfig.permissions || [],
    }
    parsedAppCode.value = appConfig.appCode || ''
    parseReady.value = true

    // Step 5: Create application
    const appCode = appConfig.appCode || buildAppCode(appConfig.appName || '新应用')
    const payload = {
      conversation_id: conversationId.value,
      app_name: appConfig.appName || '新应用',
      app_code: appCode,
      config_preview: { type: 'preview', data: { ...store.preview } },
    }
    const created = await applicationApi.create(payload)
    existingAppId.value = created.id
    store.currentApp = { name: appConfig.appName || '', status: 'ready' }

    // Step 6: Update progress message
    if (pMsg) {
      pMsg.content = `✅ 应用配置已生成！\n\n已提取 **${appConfig.models?.length || 0}** 个数据模型、**${appConfig.dicts?.length || 0}** 个字典、**${appConfig.roles?.length || 0}** 个角色。\n\n点击右侧「▶ 一键执行」将应用部署到平台。`
      pMsg.agent = 'builder'
    }

    // Step 7: Update URL and show deploy panel
    router.replace(`/chat/${conversationId.value}?app_id=${created.id}`)
    fetchConversationList()
    scrollToBottom()

    ElMessage.success('应用配置生成完成！')
  } catch (e: any) {
    const pMsg = messages.find(m => m.id === progressMsgId)
    if (pMsg) pMsg.content = `❌ 生成失败: ${e.message || '未知错误'}。请重试。`
    ElMessage.error('生成失败: ' + (e.message || '未知错误'))
  } finally {
    generatingDoc.value = false
    scrollToBottom()
  }
}

// ── Requirements: 后台生成结构化 JSON（AI 输出可读文档后自动触发） ──
const generateDocInBackground = async () => {
  if (!conversationId.value || generatingDoc.value) return
  generatingDoc.value = true

  const token = localStorage.getItem('token') || ''
  // 使用 requirements 的 generate-doc 端点（从对话历史生成 JSON）
  const url = requirementsApi.generateDocUrl(conversationId.value)

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)

    const reader = response.body?.getReader()
    if (!reader) throw new Error('无法读取响应流')
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.startsWith('data:')) {
          const dataStr = line.slice(5).trim()
          if (!dataStr) continue
          try {
            const data = JSON.parse(dataStr)
            if (data.doc_result) {
              docResultForCard.value = data.doc_result
            }
          } catch { /* ignore */ }
        }
      }
    }

    if (docResultForCard.value) {
      scrollToBottom()
    }
  } catch (e: any) {
    console.error('Background doc generation failed:', e)
    // 静默失败，不打断用户
  } finally {
    generatingDoc.value = false
  }
}

// ── Requirements: 流式生成设计文档（作为对话消息） ──
const generateDocInChat = async () => {
  if (!conversationId.value || generatingDoc.value) return
  generatingDoc.value = true
  docResultForCard.value = null
  isTyping.value = true
  scrollToBottom()

  const token = localStorage.getItem('token') || ''
  const url = requirementsApi.generateDocChatUrl(conversationId.value)

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)

    const reader = response.body?.getReader()
    if (!reader) throw new Error('无法读取响应流')
    const decoder = new TextDecoder()
    let buffer = ''
    let assistantContent = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.startsWith('event:')) {
          // event line handled below via data
        } else if (line.startsWith('data:')) {
          const dataStr = line.slice(5).trim()
          if (!dataStr) continue
          try {
            const data = JSON.parse(dataStr)
            // Phase 1: streaming text content
            if (data.content) {
              isTyping.value = false
              assistantContent += data.content
              const lastMsg = messages[messages.length - 1]
              if (lastMsg && lastMsg.role === 'assistant' && lastMsg.id === -1) {
                lastMsg.content = assistantContent
              } else {
                messages.push({ id: -1, role: 'assistant', agent: 'requirements', content: assistantContent, created_at: '' })
              }
              scrollToBottom()
            }
            // Phase 2: structured JSON result
            if (data.doc_result) {
              docResultForCard.value = data.doc_result
              // Finalize the streaming message
              const lastMsg = messages[messages.length - 1]
              if (lastMsg && lastMsg.id === -1) lastMsg.id = Date.now()
            }
          } catch { /* ignore */ }
        }
      }
    }

    isTyping.value = false
    if (!docResultForCard.value) {
      messages.push({ id: Date.now(), role: 'assistant', agent: 'requirements', content: '设计文档生成失败，请重试。', created_at: '' })
    }
    scrollToBottom()
  } catch (e: any) {
    isTyping.value = false
    ElMessage.error('生成失败: ' + (e.message || '未知错误'))
    messages.push({ id: Date.now(), role: 'assistant', agent: 'requirements', content: '生成失败，请重试。', created_at: '' })
  } finally {
    generatingDoc.value = false
    scrollToBottom()
  }
}

// ── Requirements: 确认设计文档 → 转换为 AppConfig → 切换到 builder 模式 ──
const confirmDocAndBuild = async () => {
  if (!docResultForCard.value || !conversationId.value) return
  confirmingDoc.value = true

  try {
    // Step 1: Convert AnalysisResult → AppConfig (no LLM)
    const appConfig = await convertConfig(docResultForCard.value)

    // Step 2: Switch conversation to builder mode
    await conversationApi.updateAgentType(conversationId.value, 'builder')
    currentAgent.value = 'builder'

    // Step 3: Populate preview store
    store.preview = {
      appName: appConfig.appName || '',
      roles: appConfig.roles || [],
      dicts: appConfig.dicts || [],
      models: appConfig.models || [],
      workflows: appConfig.workflows || [],
      permissions: appConfig.permissions || [],
    }
    parsedAppCode.value = appConfig.appCode || ''
    parseReady.value = true

    // Step 4: Create/update application record
    const appCode = appConfig.appCode || buildAppCode(appConfig.appName || '新应用')
    const payload = {
      conversation_id: conversationId.value,
      app_name: appConfig.appName || '新应用',
      app_code: appCode,
      config_preview: { type: 'preview', data: { ...store.preview } },
    }
    const created = await applicationApi.create(payload)
    existingAppId.value = created.id
    store.currentApp = { name: appConfig.appName || '', status: 'ready' }

    // Step 5: Add confirmation message
    messages.push({
      id: Date.now(),
      role: 'assistant',
      agent: 'builder',
      content: `配置已就绪！已提取 ${appConfig.models?.length || 0} 个模型、${appConfig.dicts?.length || 0} 个字典、${appConfig.roles?.length || 0} 个角色。\n\n请点击下方「开始生成」将应用部署到平台。`,
      created_at: '',
    })

    docResultForCard.value = null  // Clear card
    scrollToBottom()
    ElMessage.success('设计文档已确认，进入搭建模式')

    // Update URL
    router.replace(`/chat/${conversationId.value}?app_id=${created.id}`)
    fetchConversationList()
  } catch (e: any) {
    ElMessage.error('转换失败: ' + (e.message || '未知错误'))
  } finally {
    confirmingDoc.value = false
  }
}

const renderMarkdown = (t: string) => {
  if (!t) return '<p>（无内容）</p>'
  return marked.parse(t, { breaks: true, gfm: true }) as string
}

const formatContent = (t: string) => {
  // 过滤 <think> 思考内容
  let text = t.replace(/<think>[\s\S]*?<\/think>/g, '')
  // 隐藏JSON代码块，只显示文字部分
  text = text.replace(/```json[\s\S]*?```/g, '')
  // 清理多余空行
  text = text.replace(/\n{3,}/g, '\n\n').trim()
  return text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>').replace(/• /g, '<span style="color:#818cf8;margin-right:4px">•</span> ')
}

onMounted(async () => {
  // 检查平台连接状态
  try {
    const token = localStorage.getItem('token')
    if (token) {
      const res = await fetch(`${API_PREFIX}/apaas/status`, {
        headers: { 'Authorization': `Bearer ${token}` }
      })
      if (res.ok) {
        const data = await res.json()
        store.connected = data.connected
      }
    }
  } catch (e) { /* ignore */ }

  await loadBuilderModelOptions()

  // ── 优先通过 app_id 加载应用（应用为锚点）──
  const appIdParam = route.query.app_id as string
  if (appIdParam) {
    const aid = Number(appIdParam)
    if (aid) {
      existingAppId.value = aid
      try {
        const app = await applicationApi.get(aid) as any
        // 恢复配置
        if (app.config_preview) {
          const data = app.config_preview.data || app.config_preview
          store.preview.appName = data.appName || app.app_name || ''
          store.preview.models = data.models || []
          store.preview.dicts = data.dicts || []
          store.preview.roles = data.roles || []
          store.preview.workflows = data.workflows || []
          store.preview.permissions = data.permissions || []
          store.currentApp = { name: store.preview.appName, status: app.status || 'ready', apaas_app_id: app.apaas_app_id }
          parseReady.value = store.preview.models.length > 0
        }
        loadedAppCode.value = app.app_code || ''
        parsedAppCode.value = parsedAppCode.value || loadedAppCode.value
        await loadLatestDocForApp(aid)
        console.log(`Loaded app ${aid}: ${app.app_name}, status=${app.status}, conv=${app.conversation_id}`)
        // 加载关联对话的历史消息
        if (app.conversation_id) {
          conversationId.value = app.conversation_id
          selectedConversationId.value = app.conversation_id
          await syncBuilderModelFromConversation(app.conversation_id)
          if (!appParsedMode.value) {
            const historyMessages = await conversationApi.getMessages(app.conversation_id)
            if (historyMessages?.length) {
              messages.splice(0, messages.length)
              for (const msg of historyMessages) {
                if (msg.role === 'system') continue
                messages.push({ id: msg.id, role: msg.role as any, agent: msg.role === 'assistant' ? 'builder' : undefined, content: msg.content, created_at: msg.created_at })
              }
              scrollToBottom()
            }
          }
        }
        console.log(`Loaded app ${aid}: ${app.app_name}`)
      } catch (e) {
        console.error('Failed to load application:', e)
      }
    }
  }
  // ── 兼容旧链接：通过 conversation_id 加载 ──
  else {
    const idParam = route.params.id as string
    if (idParam) {
      const cid = Number(idParam)
      if (!isNaN(cid)) {
        conversationId.value = cid
        try {
          await syncBuilderModelFromConversation(cid)
          // 加载历史消息
          const historyMessages = await conversationApi.getMessages(cid)
          if (historyMessages && historyMessages.length > 0) {
            messages.splice(0, messages.length)
            for (const msg of historyMessages) {
              if (msg.role === 'system') {
                extractPreviewData(msg.content)
                continue
              }
              messages.push({
                id: msg.id,
                role: msg.role as any,
                agent: msg.role === 'assistant' ? 'builder' : undefined,
                content: msg.content,
                created_at: msg.created_at
              })
              if (msg.role === 'assistant') {
                extractPreviewData(msg.content)
              }
            }
            scrollToBottom()
          }
          // 查找关联的应用
          if (!existingAppId.value) {
            try {
              const apps = await applicationApi.list() as any[]
              const linkedApp = apps.find((a: any) => a.conversation_id === cid && a.config_preview)
              if (linkedApp?.config_preview) {
                const data = linkedApp.config_preview.data || linkedApp.config_preview
                store.preview.appName = data.appName || ''
                store.preview.models = data.models || []
                store.preview.dicts = data.dicts || []
                store.preview.roles = data.roles || []
                store.preview.workflows = data.workflows || []
                store.preview.permissions = data.permissions || []
                store.currentApp = { name: store.preview.appName, status: 'draft' }
                parseReady.value = store.preview.models.length > 0
                existingAppId.value = linkedApp.id
                loadedAppCode.value = linkedApp.app_code || ''
                parsedAppCode.value = parsedAppCode.value || loadedAppCode.value
                await loadLatestDocForApp(linkedApp.id)
                // 更新 URL 为 app_id 模式
                router.replace({ path: '/chat', query: { app_id: String(linkedApp.id) } })
                console.log('Migrated to app-centric URL:', linkedApp.id)
              }
            } catch (e2) {
              console.warn('Failed to recover config from app:', e2)
            }
          }
        } catch (e) {
          console.error('Failed to load conversation history:', e)
        }
      }
    }
  }

  // 从 /generate/:id 重定向过来，自动打开部署面板
  const deployParam = route.query.deploy_app_id as string
  if (deployParam) {
    const aid = Number(deployParam)
    if (aid) {
      deployAppId.value = aid
      existingAppId.value = aid
      deployOpen.value = true
      loadDeployStatus()
      // 加载应用信息到预览
      try {
        const app = await applicationApi.get(aid) as any
        if (app.config_preview) {
          const data = app.config_preview.data || app.config_preview
          store.preview.appName = data.appName || app.app_name || ''
          store.preview.models = data.models || []
          store.preview.dicts = data.dicts || []
          store.preview.roles = data.roles || []
          store.currentApp = { name: store.preview.appName, status: app.status || 'ready' }
          parseReady.value = store.preview.models.length > 0
        }
        loadedAppCode.value = app.app_code || ''
        parsedAppCode.value = parsedAppCode.value || loadedAppCode.value
        await loadLatestDocForApp(aid)
        // 加载关联的对话
        if (app.conversation_id) {
          conversationId.value = app.conversation_id
          await syncBuilderModelFromConversation(app.conversation_id)
          if (!appParsedMode.value) {
            const historyMessages = await conversationApi.getMessages(app.conversation_id)
            if (historyMessages?.length) {
              messages.splice(0, messages.length)
              for (const msg of historyMessages) {
                if (msg.role === 'system') continue
                messages.push({ id: msg.id, role: msg.role as any, agent: msg.role === 'assistant' ? 'builder' : undefined, content: msg.content, created_at: msg.created_at })
              }
            }
          }
        }
      } catch { /* ignore */ }
    }
  }

  // ── 新对话：自动进入 requirements 模式 ──
  // 如果没有加载到已有对话（无 app_id, 无 conversation_id），创建 requirements 对话
  if (!conversationId.value && !store.pendingMarkdown && !store.pendingFile) {
    const token = localStorage.getItem('token')
    const res = await fetch(`${API_PREFIX}/conversations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({
        agent_type: 'requirements',
        ...(selectedBuilderModelId.value != null ? { selected_llm_config_id: selectedBuilderModelId.value } : {}),
      })
    })
    if (res.ok) {
      const data = await res.json()
      conversationId.value = data.id
      selectedConversationId.value = data.id
      currentAgent.value = 'requirements'
      router.replace(`/chat/${data.id}`)
      messages.push({
        id: Date.now(),
        role: 'assistant',
        agent: 'requirements',
        content: '您好！请描述一下您想要搭建的应用。\n\n比如："我想做一个客户管理系统"、"帮我搭建一个项目管理应用"',
        created_at: '',
      })
    }
  }

  const prompt = route.query.prompt as string
  if (prompt && !appParsedMode.value) {
    inputText.value = prompt
    nextTick(() => sendMessage())
  }

  // 从需求分析页带过来的 markdown 文档
  if (store.pendingMarkdown) {
    const pending = store.pendingMarkdown
    store.pendingMarkdown = null
    resetConversationWorkspace()
    messages.splice(0, messages.length)
    const file = new File([pending.content], pending.filename, { type: 'text/markdown' })
    await nextTick()
    await uploadDocFile(file)
  }

  // 从 Landing 页带过来的待解析文件
  if (store.pendingFile) {
    const file = store.pendingFile
    store.pendingFile = null
    resetConversationWorkspace()
    messages.splice(0, messages.length)
    await nextTick()
    await uploadDocFile(file)
  }

  // 同步对话历史选中
  if (conversationId.value) {
    selectedConversationId.value = conversationId.value
  } else {
    selectedBuilderModelId.value = defaultBuilderModelId.value
  }

  // 加载对话历史列表
  fetchConversationList()

  // 加载应用计数
  fetchAppCount()
})

// ── 监听 route.query.app_id 变化，实现侧栏点击切换应用 ──
watch(() => route.query.app_id, async (newAppId, oldAppId) => {
  if (!newAppId || newAppId === oldAppId) return
  const aid = Number(newAppId)
  if (!aid || aid === existingAppId.value) return

  // 重置当前状态
  existingAppId.value = aid
  messages.splice(0, messages.length)
  store.preview.models = []
  store.preview.dicts = []
  store.preview.roles = []
  store.currentApp = null
  latestDocContent.value = ''
  conversationId.value = null
  activeView.value = 'builder'

  try {
    const app = await applicationApi.get(aid) as any
    if (app.config_preview) {
      const data = app.config_preview.data || app.config_preview
      store.preview.appName = data.appName || app.app_name || ''
      store.preview.models = data.models || []
      store.preview.dicts = data.dicts || []
      store.preview.roles = data.roles || []
      store.preview.workflows = data.workflows || []
      store.preview.permissions = data.permissions || []
      store.currentApp = { name: store.preview.appName, status: app.status || 'ready', apaas_app_id: app.apaas_app_id }
      parseReady.value = store.preview.models.length > 0
    }
    loadedAppCode.value = app.app_code || ''
    parsedAppCode.value = loadedAppCode.value
    await loadLatestDocForApp(aid)
    if (app.conversation_id) {
      conversationId.value = app.conversation_id
      selectedConversationId.value = app.conversation_id
      if (!appParsedMode.value) {
        const historyMessages = await conversationApi.getMessages(app.conversation_id)
        if (historyMessages?.length) {
          for (const msg of historyMessages) {
            if (msg.role === 'system') continue
            messages.push({ id: msg.id, role: msg.role as any, agent: msg.role === 'assistant' ? 'builder' : undefined, content: msg.content, created_at: msg.created_at })
          }
          scrollToBottom()
        }
      }
    }
  } catch (e) {
    console.error('Failed to switch app:', e)
  }
})

// 切换到文档 tab 时自动加载版本列表
watch(() => store.previewTab, (tab) => {
  if (tab === 'workflow') {
    store.previewTab = 'overview'
    return
  }
  if (tab === 'docs' && (existingAppId.value || conversationId.value) && docVersions.value.length === 0) {
    fetchDocVersions()
  }
})
watch(existingAppId, (id) => {
  if (id && store.previewTab === 'docs') {
    fetchDocVersions()
  }
})
watch(conversationId, (id) => {
  if (id && store.previewTab === 'docs' && !existingAppId.value) {
    fetchDocVersions()
  }
})
</script>

<style scoped>
/* ══════════════════════════════════════════════
   Theme — uses CSS custom properties (var(--t-*))
   for light/dark theme support.
   See theme definition for variable values.
   ══════════════════════════════════════════════ */

.chat-page { height: 100vh; display: flex; flex-direction: column; background: var(--t-bg-base); color: var(--t-text-primary); }

/* ── 导航栏 ── */
/* ── 精简顶栏 ── */
.top-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 12px;
  flex-shrink: 0;
  background: var(--t-bg-nav);
  border-bottom: 1px solid var(--t-border-subtle);
  min-height: 42px;
}
.top-bar-left, .top-bar-right { display: flex; align-items: center; gap: 8px; }
.sidebar-hamburger {
  width: 32px; height: 32px; border: none; border-radius: 6px;
  background: transparent; color: var(--t-text-secondary); cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: all 0.15s ease;
}
.sidebar-hamburger:hover { background: var(--t-bg-elevated); color: var(--t-text-primary); }
.top-bar-home {
  background: none; border: none; cursor: pointer; padding: 0;
  display: flex; align-items: center; transition: opacity 0.15s;
}
.top-bar-home:hover { opacity: 0.8; }
.top-bar-logo {
  width: 26px; height: 26px; border-radius: 6px;
  background: var(--t-brand-gradient); color: #fff;
  font-weight: 700; font-size: 11px;
  display: flex; align-items: center; justify-content: center;
}
.top-bar-app-name {
  font-size: 13px; font-weight: 500; color: var(--t-text-secondary);
  max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.mode-switcher { display: flex; gap: 2px; background: var(--t-bg-input); border-radius: 10px; padding: 3px; border: 1px solid var(--t-border-subtle); }
.mode-btn {
  display: flex; align-items: center; gap: 5px; padding: 5px 14px; border-radius: 8px;
  font-size: 12px; font-weight: 500; background: none; border: none;
  color: var(--t-text-muted); cursor: pointer; transition: all 0.2s;
}
.mode-btn:hover { color: var(--t-text-primary); }
.mode-btn.active { background: var(--t-bg-panel); color: var(--t-brand-text); font-weight: 600; box-shadow: var(--t-shadow-sm); }
.top-bar-icon-btn {
  width: 28px; height: 28px; border: none; border-radius: 6px;
  background: transparent; color: var(--t-text-muted); cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  font-size: 14px; transition: all 0.15s;
}
.top-bar-icon-btn:hover { background: var(--t-bg-elevated); color: var(--t-text-primary); }
.user-avatar-btn {
  width: 30px; height: 30px; border-radius: 50%;
  background: var(--t-brand-gradient); color: #fff; border: none;
  font-weight: 700; font-size: 12px; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: opacity 0.15s;
}
.user-avatar-btn:hover { opacity: 0.85; }
.user-menu-info { display: flex; flex-direction: column; gap: 1px; }
.user-menu-label { font-size: 10px; color: var(--t-text-muted); }
.user-menu-value { font-size: 13px; color: var(--t-text-primary); }

/* ── 主区域 ── */
.main-area { flex: 1; display: flex; flex-direction: row; overflow: hidden; position: relative; }
.content-area { flex: 1; display: flex; flex-direction: column; overflow: hidden; min-width: 0; }

/* ── 智能搭建内容区（横向布局） ── */
.builder-content { flex: 1; display: flex; overflow: hidden; min-height: 0; }

/* ── 左侧对话 ── */
.chat-side { flex: 1; display: flex; flex-direction: column; min-width: 0; min-width: 320px; }
.app-mode-placeholder {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--t-text-secondary);
  border: 1px dashed var(--t-border-subtle);
  border-radius: 12px;
  margin: 16px;
}
.doc-view-wrap {
  flex: 1;
  border: 1px solid var(--t-border-subtle);
  border-radius: 12px;
  margin: 12px;
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow: auto;
  background: var(--t-bg-panel);
  box-shadow: var(--t-shadow-sm);
}
.doc-view-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--t-border-subtle);
}
.doc-view-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--t-text-primary);
}
.doc-view-file {
  font-size: 12px;
  color: var(--t-text-muted);
  max-width: 58%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.doc-view-body {
  flex: 1;
  overflow: auto;
  padding: 4px 2px;
  color: var(--t-text-primary);
  line-height: 1.65;
  font-size: 14px;
}
.doc-view-body :deep(h1),
.doc-view-body :deep(h2),
.doc-view-body :deep(h3) {
  margin: 10px 0 8px;
  color: var(--t-text-primary);
}
.doc-view-body :deep(p),
.doc-view-body :deep(li) {
  color: var(--t-text-primary);
}
.doc-view-body :deep(code) {
  color: var(--t-brand-text);
  background: var(--t-brand-subtle);
  border: 1px solid var(--t-border-subtle);
  border-radius: 4px;
  padding: 1px 4px;
}
.doc-view-empty {
  margin-top: auto;
  color: var(--t-text-muted);
  font-size: 13px;
}
.parsed-side-card {
  margin: 12px 12px 10px;
  padding: 14px 16px;
  border-radius: 12px;
  border: 1px solid var(--t-border-subtle);
  background: var(--t-bg-panel);
  box-shadow: var(--t-shadow-sm);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.parsed-side-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--t-text-primary);
  margin-bottom: 2px;
}
.parsed-side-row {
  font-size: 13px;
  color: var(--t-text-primary);
}
.parsed-side-row code {
  color: var(--t-brand-text);
  background: var(--t-brand-subtle);
  border: 1px solid var(--t-border-subtle);
  border-radius: 6px;
  padding: 1px 6px;
}
.parsed-side-brief {
  font-size: 12px;
  color: var(--t-text-muted);
}
@media (max-width: 1180px) {
  .doc-view-head {
    flex-direction: column;
    align-items: flex-start;
  }
}

/* (agent-tabs removed — replaced by mode-switcher in top-bar) */

/* 消息区 */
/* ── 对话历史栏 ── */
.conversation-history-bar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 4px 16px; flex-shrink: 0;
  background: transparent; border-bottom: 1px solid var(--t-border-subtle);
}
.conv-history-left {
  display: flex; align-items: center; gap: 10px;
}
.conv-history-label {
  font-size: 11px; color: var(--t-text-muted); white-space: nowrap; font-weight: 400;
}
.conv-history-select {
  width: 300px;
}
.conv-history-select :deep(.el-select__wrapper),
.conv-history-select :deep(.el-input__wrapper),
.conv-history-select :deep(.el-select__wrapper.is-focused),
.conv-history-select :deep(.el-select__wrapper.is-hovering) {
  background: transparent !important; border: 1px solid var(--t-border-subtle) !important;
  box-shadow: none !important; border-radius: 8px !important; height: 28px;
}
.conv-history-select :deep(.el-select__wrapper.is-hovering) {
  border-color: var(--t-border-strong) !important;
}
.conv-history-select :deep(.el-select__wrapper.is-focused) {
  border-color: var(--t-brand-glow) !important;
}
.conv-history-select :deep(.el-select__selection) {
  color: var(--t-text-primary) !important;
}
.conv-history-select :deep(.el-select__placeholder),
.conv-history-select :deep(.el-select__placeholder.is-transparent) {
  color: var(--t-text-muted) !important;
}
.conv-history-select :deep(.el-select__caret),
.conv-history-select :deep(.el-select__suffix) {
  color: var(--t-text-muted) !important;
}
.conv-history-select :deep(.el-select__selected-item .el-tag) {
  background: transparent !important; border: none !important; color: var(--t-text-primary) !important;
}
.conv-history-select :deep(.el-input__wrapper:hover) {
  border-color: var(--t-border-strong) !important;
}
.conv-history-select :deep(.el-input__wrapper.is-focus),
.conv-history-select :deep(.el-input.is-focus .el-input__wrapper) {
  border-color: var(--t-brand-glow) !important; box-shadow: none !important;
}
.conv-history-select :deep(.el-select__tags),
.conv-history-select :deep(.el-tag) {
  background: transparent !important;
}
.conv-history-select :deep(.el-tag .el-tag__content) {
  color: var(--t-text-primary) !important;
}
.conv-history-select :deep(.el-select__input) {
  background: transparent !important; color: var(--t-text-primary) !important;
}
.conv-history-select :deep(.el-select__placeholder) {
  color: var(--t-text-muted) !important;
}
.conv-history-select :deep(.el-select__selected-item) {
  color: var(--t-text-primary) !important;
}
.conv-history-select :deep(.el-input__inner) {
  color: var(--t-text-primary) !important; font-size: 12px !important;
}
.conv-history-select :deep(.el-input__suffix) {
  color: var(--t-text-muted) !important;
}
.conv-history-select :deep(.el-select-dropdown) {
  background: var(--t-bg-panel) !important; border: 1px solid var(--t-border-subtle) !important;
  border-radius: 10px !important;
}
.conv-history-select :deep(.el-select-dropdown__item) {
  color: var(--t-text-secondary) !important; font-size: 12px !important;
  padding: 6px 12px !important;
}
.conv-history-select :deep(.el-select-dropdown__item.is-selected) {
  color: var(--t-brand-light) !important; font-weight: 600;
}
.conv-history-select :deep(.el-select-dropdown__item:hover),
.conv-history-select :deep(.el-select-dropdown__item.hover) {
  background: var(--t-brand-subtle) !important;
}
.conv-history-select :deep(.el-popper.is-light) {
  background: var(--t-bg-panel) !important; border: 1px solid var(--t-border-subtle) !important;
}
.conv-history-select :deep(.el-popper.is-light .el-popper__arrow::before) {
  background: var(--t-bg-panel) !important; border-color: var(--t-border-subtle) !important;
}
.conv-option-row {
  display: flex; justify-content: space-between; align-items: center; width: 100%; gap: 12px;
}
.conv-option-title {
  flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.conv-option-time {
  flex-shrink: 0; font-size: 11px; color: var(--t-text-muted);
}
.conv-new-btn {
  all: unset; cursor: pointer; font-size: 11px; font-weight: 400;
  color: var(--t-text-muted); padding: 3px 10px; border-radius: 6px;
  border: 1px solid var(--t-border-subtle); transition: all 0.2s;
  white-space: nowrap;
}
.conv-new-btn:hover {
  color: var(--t-brand-light); background: var(--t-brand-subtle); border-color: rgba(167,139,250,0.2);
}

.messages { flex: 1; overflow-y: auto; padding: 16px 20px; background: var(--t-bg-base); }
.chat-bubble { margin-bottom: 16px; animation: fadeUp 0.3s ease-out; }
.chat-bubble.user { display: flex; justify-content: flex-end; }
.chat-bubble.assistant { display: flex; justify-content: flex-start; }
.bubble-inner { max-width: 80%; }
.agent-label { display: flex; align-items: center; gap: 4px; font-size: 11px; color: var(--t-text-muted); margin-bottom: 4px; }
.bubble-content { padding: 10px 14px; border-radius: 14px; font-size: 13px; line-height: 1.6; }
.bubble-content.user {
  background: var(--t-brand-gradient);
  color: #fff; border-bottom-right-radius: 4px;
}
.bubble-content.assistant {
  background: var(--t-bg-panel); border: 1px solid var(--t-border-subtle);
  color: var(--t-text-primary); border-bottom-left-radius: 4px;
  box-shadow: var(--t-shadow-sm);
}
@keyframes fadeUp { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }

.typing-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--t-text-muted); display: inline-block; animation: pulseDot 1.4s infinite ease-in-out both; margin-right: 3px; }
.typing-dot:nth-child(1) { animation-delay: -0.32s; }
.typing-dot:nth-child(2) { animation-delay: -0.16s; }
@keyframes pulseDot { 0%,80%,100% { transform: scale(0); } 40% { transform: scale(1); } }

/* 底部输入框 */
/* ── Input bar (Claude-style card) ── */
.input-bar {
  padding: 0 16px 16px;
  background: var(--t-bg-base);
  flex-shrink: 0;
  display: flex;
  justify-content: center;
}
.input-card {
  width: 100%;
  background: var(--t-bg-panel);
  border: 1px solid var(--t-border-subtle);
  border-radius: 16px;
  overflow: hidden;
  box-shadow: var(--t-shadow-sm);
  transition: border-color 0.2s, box-shadow 0.2s;
}
.input-card:focus-within {
  border-color: var(--t-brand);
  box-shadow: 0 0 0 3px var(--t-brand-subtle);
}
.input-card-top {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 10px 12px;
}
.upload-btn {
  cursor: pointer;
  color: var(--t-text-muted);
  display: flex;
  align-items: center;
  padding: 4px;
  border-radius: 6px;
  transition: color 0.15s;
  flex-shrink: 0;
}
.upload-btn:hover { color: var(--t-text-primary); }
.input-card-top textarea {
  flex: 1;
  border: none;
  background: transparent;
  resize: none;
  outline: none;
  font-size: 14px;
  line-height: 1.5;
  color: var(--t-text-primary);
  min-height: 22px;
  max-height: 160px;
  overflow-y: auto;
  padding: 2px 0;
  font-family: inherit;
}
.input-card-top textarea::placeholder { color: var(--t-text-muted); }
.send-btn {
  width: 32px; height: 32px; border-radius: 8px;
  background: var(--t-text-primary);
  color: var(--t-bg-base);
  border: none; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
  transition: opacity 0.15s;
}
.send-btn.disabled { opacity: 0.2; cursor: not-allowed; }
.send-btn:hover:not(.disabled) { opacity: 0.8; }
.input-card-bottom {
  display: flex;
  align-items: center;
  padding: 4px 12px 8px;
  border-top: 1px solid var(--t-border-subtle);
}
.input-card-spacer { flex: 1; }
.input-model-select {
  width: 160px;
}
.input-model-select :deep(.el-select__wrapper) {
  min-height: 26px;
  border-radius: 8px;
  background: transparent;
  border: 1px solid var(--t-border-subtle);
  box-shadow: none;
  font-size: 12px;
}
.input-model-select :deep(.el-select__wrapper:hover) {
  border-color: var(--t-border-strong);
}

@media (max-width: 960px) {
  .builder-model-bar {
    flex-direction: column;
    align-items: stretch;
  }
  .builder-model-select {
    width: 100%;
  }
}

/* ── 右侧预览面板 ── */
.preview-side {
  flex: 1; background: var(--t-bg-panel); border-left: 1px solid var(--t-border-subtle);
  display: flex; flex-direction: column; min-width: 0; position: relative;
}
.preview-tabs { display: flex; border-bottom: 1px solid var(--t-border-subtle); padding: 0 8px; flex-shrink: 0; }
.ptab {
  padding: 10px 12px; font-size: 12px; font-weight: 500; border: none; background: none;
  color: var(--t-text-muted); cursor: pointer; border-bottom: 2px solid transparent;
  transition: color 0.2s;
}
.ptab:hover { color: var(--t-text-secondary); }
.ptab.active {
  color: var(--t-brand-light);
  border-image: var(--t-brand-gradient) 1;
  border-bottom-width: 2px; border-bottom-style: solid;
}
.preview-empty { padding: 24px; text-align: center; color: var(--t-text-muted); font-size: 13px; margin-top: 80px; }
.preview-empty .empty-icon { font-size: 40px; opacity: 0.3; margin-bottom: 12px; }
.preview-empty.small { margin-top: 0; padding: 32px; }
.preview-body { flex: 1; overflow-y: auto; }
.tab-content { padding: 16px; }

/* ── 文档版本 ── */
.doc-versions-tab { display: flex; flex-direction: column; gap: 12px; }
.doc-upload-bar { display: flex; align-items: center; justify-content: space-between; }
.doc-tab-title { font-size: 14px; font-weight: 600; color: var(--t-text-primary); }
.doc-upload-btn {
  padding: 6px 14px; font-size: 12px; font-weight: 500; border: none; border-radius: 8px;
  background: var(--t-brand-gradient); color: #fff; cursor: pointer;
  transition: opacity 0.2s;
}
.doc-upload-btn:hover { opacity: 0.85; }
.doc-version-list { display: flex; flex-direction: column; gap: 10px; }
.doc-version-card {
  border: 1px solid var(--t-border-subtle); border-radius: 12px; padding: 12px 14px;
  background: var(--t-bg-elevated); transition: border-color 0.2s;
}
.doc-version-card:hover { border-color: var(--t-brand-glow); }
.doc-ver-header { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.doc-ver-num {
  font-size: 13px; font-weight: 700;
  background: var(--t-brand-gradient);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
}
.doc-ver-filename { font-size: 13px; color: var(--t-text-primary); font-weight: 500; }
.doc-ver-meta { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.doc-ver-time { font-size: 11px; color: var(--t-text-muted); }
.doc-ver-summary { font-size: 11px; color: var(--t-text-secondary); }
.doc-ver-actions { display: flex; gap: 8px; }
.doc-action-btn {
  padding: 4px 10px; font-size: 11px; border-radius: 6px; cursor: pointer;
  border: 1px solid var(--t-border-subtle); background: var(--t-border-subtle);
  color: var(--t-text-secondary); transition: all 0.2s;
}
.doc-action-btn:hover { background: var(--t-border-subtle); color: #fff; }
.doc-action-btn.diff { border-color: var(--t-brand-glow); color: var(--t-brand-light); }
.doc-action-btn.diff:hover { background: var(--t-brand-subtle); }

/* 文档预览弹窗 */
:deep(.doc-preview-dialog) .el-dialog { background: var(--t-bg-panel); color: var(--t-text-primary); }
:deep(.doc-preview-dialog) .el-dialog__header { border-bottom: 1px solid var(--t-border-subtle); }
:deep(.doc-preview-dialog) .el-dialog__title { color: var(--t-text-primary); }
:deep(.doc-preview-dialog) .el-dialog__headerbtn .el-dialog__close { color: var(--t-text-secondary); }
.doc-preview-body {
  max-height: 70vh; overflow-y: auto; padding: 16px;
  font-size: 13px; line-height: 1.7; color: var(--t-text-primary);
  background: var(--t-bg-base); border-radius: 8px;
}
.doc-preview-body :deep(h1) { font-size: 20px; color: var(--t-text-primary); margin: 20px 0 12px; padding-bottom: 8px; border-bottom: 1px solid var(--t-border-subtle); }
.doc-preview-body :deep(h2) { font-size: 17px; color: var(--t-text-primary); margin: 18px 0 10px; }
.doc-preview-body :deep(h3) { font-size: 15px; color: var(--t-text-primary); margin: 14px 0 8px; }
.doc-preview-body :deep(h4) { font-size: 13px; color: var(--t-text-primary); margin: 10px 0 6px; }
.doc-preview-body :deep(p) { margin: 6px 0; }
.doc-preview-body :deep(ul), .doc-preview-body :deep(ol) { padding-left: 20px; margin: 6px 0; }
.doc-preview-body :deep(li) { margin: 3px 0; }
.doc-preview-body :deep(code) { background: var(--t-border-subtle); padding: 2px 6px; border-radius: 4px; font-size: 12px; }
.doc-preview-body :deep(pre) { background: var(--t-border-subtle); padding: 12px; border-radius: 8px; overflow-x: auto; }
.doc-preview-body :deep(table) { width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 12px; }
.doc-preview-body :deep(th) { background: var(--t-brand-subtle); color: var(--t-brand-light); text-align: left; padding: 8px 12px; border: 1px solid var(--t-border-subtle); font-weight: 600; }
.doc-preview-body :deep(td) { padding: 6px 12px; border: 1px solid var(--t-border-subtle); }
.doc-preview-body :deep(tr:hover td) { background: var(--t-bg-subtle); }
.doc-preview-body :deep(strong) { color: var(--t-text-primary); font-weight: 600; }
.doc-preview-body :deep(hr) { border: none; border-top: 1px solid var(--t-border-subtle); margin: 16px 0; }

/* 文档对比弹窗 */
:deep(.doc-diff-dialog) .el-dialog { background: var(--t-bg-panel); color: var(--t-text-primary); }
:deep(.doc-diff-dialog) .el-dialog__header { border-bottom: 1px solid var(--t-border-subtle); }
:deep(.doc-diff-dialog) .el-dialog__title { color: var(--t-text-primary); }
:deep(.doc-diff-dialog) .el-dialog__headerbtn .el-dialog__close { color: var(--t-text-secondary); }
.diff-summary-bar {
  display: flex; gap: 16px; padding: 10px 14px; margin-bottom: 12px;
  background: var(--t-border-subtle); border-radius: 10px; border: 1px solid var(--t-border-subtle);
}
.diff-stat { font-size: 13px; font-weight: 500; }
.diff-stat.added { color: var(--t-success); }
.diff-stat.removed { color: var(--t-danger); }
.diff-stat.unchanged { color: var(--t-text-muted); }
.doc-diff-container { display: flex; gap: 8px; max-height: 70vh; }

/* 变更摘要面板 */
.diff-changes-panel {
  width: 240px; flex-shrink: 0; display: flex; flex-direction: column;
  background: var(--t-border-subtle); border: 1px solid var(--t-border-subtle);
  border-radius: 10px; overflow: hidden;
}
.dcp-title {
  font-size: 12px; font-weight: 600; color: var(--t-text-secondary);
  padding: 10px 12px; border-bottom: 1px solid var(--t-border-subtle);
  background: var(--t-bg-subtle);
}
.dcp-list { flex: 1; overflow-y: auto; padding: 8px; }
.dcp-item {
  display: flex; align-items: flex-start; gap: 6px; padding: 5px 6px;
  font-size: 11px; line-height: 1.4; border-radius: 6px; margin-bottom: 2px;
}
.dcp-item.added { color: var(--t-success); background: rgba(52,211,153,0.06); }
.dcp-item.removed { color: var(--t-danger); background: rgba(248,113,113,0.06); }
.dcp-item.modified { color: var(--t-warning); background: rgba(251,191,36,0.06); }
.dcp-icon { font-weight: 700; flex-shrink: 0; width: 14px; text-align: center; }
.dcp-text { word-break: break-all; }
.dcp-empty { text-align: center; color: var(--t-text-muted); font-size: 11px; padding: 20px 0; }
.doc-diff-pane { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.doc-diff-pane-title {
  font-size: 12px; font-weight: 600; padding: 8px 12px;
  background: var(--t-border-subtle); border-radius: 8px 8px 0 0;
  color: var(--t-text-secondary); border: 1px solid var(--t-border-subtle);
  border-bottom: none;
}
.doc-diff-content {
  flex: 1; overflow-y: auto; background: var(--t-bg-base); border-radius: 0 0 8px 8px;
  border: 1px solid var(--t-border-subtle); font-size: 12px; font-family: 'Menlo', 'Monaco', monospace;
}
.doc-diff-line { display: flex; min-height: 20px; line-height: 20px; }
.doc-diff-lineno {
  width: 36px; text-align: right; padding-right: 8px; flex-shrink: 0;
  color: var(--t-text-muted); user-select: none;
}
.doc-diff-text { flex: 1; padding: 0 8px; white-space: pre-wrap; word-break: break-all; color: var(--t-text-secondary); }
.doc-diff-line.removed { background: rgba(239,68,68,0.12); }
.doc-diff-line.removed .doc-diff-text { color: #fca5a5; }
.doc-diff-line.added { background: rgba(34,197,94,0.12); }
.doc-diff-line.added .doc-diff-text { color: #86efac; }

/* ── 概览 ── */
.overview-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.overview-header h4 { font-size: 14px; font-weight: 600; color: var(--t-text-primary); margin: 0; }
.status-tag { font-size: 11px; padding: 2px 8px; border-radius: 10px; }
.status-tag.ready { background: rgba(16,185,129,0.15); color: var(--t-success); }
.status-tag.deployed { background: rgba(96,165,250,0.15); color: var(--t-info); }
.deployed-banner {
  display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; border-radius: 12px; font-size: 13px; font-weight: 500; margin-top: 8px;
  background: rgba(96,165,250,0.1); color: var(--t-info); border: 1px solid rgba(96,165,250,0.15);
}
.view-deploy-btn {
  background: none; border: 1px solid rgba(96,165,250,0.3); color: var(--t-info); cursor: pointer;
  font-size: 11px; padding: 3px 10px; border-radius: 6px; transition: all 0.2s;
}
.view-deploy-btn:hover { background: rgba(96,165,250,0.15); }
.deployed-link { background: none; border: none; color: var(--t-brand-light); cursor: pointer; font-size: 12px; text-decoration: underline; margin-left: 8px; }
.status-tag.talking { background: var(--t-brand-subtle); color: var(--t-brand-light); }
.stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(80px, 1fr)); gap: 8px; margin-bottom: 16px; }
.stat-card { border-radius: 12px; padding: 12px; text-align: center; border: 1px solid var(--t-border-subtle); }
.stat-card.indigo { background: var(--t-brand-subtle); }
.stat-card.emerald { background: rgba(16,185,129,0.1); }
.stat-card.amber { background: rgba(245,158,11,0.1); }
.stat-card.teal { background: rgba(20,184,166,0.1); }
.stat-card.purple { background: var(--t-brand-subtle); }
.stat-num { font-size: 20px; font-weight: 700; }
.stat-card.indigo .stat-num { color: var(--t-brand-light); }
.stat-card.teal .stat-num { color: #2dd4bf; }
.stat-card.emerald .stat-num { color: var(--t-success); }
.stat-card.amber .stat-num { color: var(--t-warning); }
.stat-card.purple .stat-num { color: var(--t-brand-light); }
.stat-label { font-size: 11px; color: var(--t-text-muted); }
.sub-section { margin-bottom: 16px; }
.sub-title { font-size: 12px; font-weight: 500; color: var(--t-text-secondary); margin-bottom: 8px; }
.tag-list { display: flex; flex-wrap: wrap; gap: 6px; }
.tag { font-size: 12px; background: var(--t-border-subtle); color: var(--t-text-secondary); padding: 4px 10px; border-radius: 6px; }
.dict-list { display: flex; flex-direction: column; gap: 6px; }
.dict-row { display: flex; align-items: center; gap: 6px; font-size: 12px; padding: 4px 8px; background: var(--t-border-subtle); border-radius: 6px; }
.dict-name { color: var(--t-text-primary); white-space: nowrap; }
.dict-opts { flex: 1; color: var(--t-text-muted); }
.dict-opts.empty { color: var(--t-danger); }
.edit-mini, .del-mini { background: none; border: none; cursor: pointer; font-size: 11px; padding: 2px; opacity: 0.3; transition: opacity 0.2s; flex-shrink: 0; color: var(--t-text-secondary); }
.dict-row:hover .edit-mini, .dict-row:hover .del-mini { opacity: 1; }
.add-mini { background: none; border: 1px dashed var(--t-border-strong); color: var(--t-text-muted); font-size: 11px; padding: 0 6px; border-radius: 4px; cursor: pointer; margin-left: 8px; transition: all 0.2s; }
.add-mini:hover { border-color: var(--t-brand); color: var(--t-brand-light); }
.tag.editable { cursor: pointer; transition: all 0.2s; }
.tag.editable:hover { background: rgba(239,68,68,0.15); color: var(--t-danger); }
.tag.empty { background: var(--t-bg-subtle); color: var(--t-text-muted); font-style: italic; }
.assemble-btn {
  width: 100%; padding: 10px; border: none; border-radius: 12px;
  font-size: 13px; font-weight: 500; cursor: pointer; margin-top: 8px;
  background: rgba(245,158,11,0.15); color: var(--t-warning);
  border: 1px solid rgba(245,158,11,0.2); transition: all 0.2s;
}
.assemble-btn:hover { background: rgba(245,158,11,0.25); transform: translateY(-1px); }
.assemble-progress {
  display: flex; align-items: center; gap: 8px; padding: 10px 12px;
  background: rgba(245,158,11,0.08); border: 1px solid rgba(245,158,11,0.15);
  border-radius: 12px; font-size: 12px; color: var(--t-warning); margin-top: 8px;
}
.assemble-spinner { animation: spin 1s linear infinite; display: inline-block; font-size: 16px; }
.gen-btn {
  width: 100%; padding: 10px;
  background: var(--t-brand-gradient);
  color: #fff; border: none; border-radius: 12px; font-size: 13px; font-weight: 500;
  cursor: pointer; margin-top: 8px; transition: transform 0.2s, box-shadow 0.2s;
}
.gen-btn:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 4px 16px var(--t-brand-glow); }
.gen-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* ── 模型 ── */
.model-card { border: 1px solid var(--t-border-subtle); border-radius: 12px; overflow: hidden; margin-bottom: 12px; background: var(--t-bg-panel); }
.model-header { display: flex; align-items: center; gap: 8px; padding: 10px 12px; background: var(--t-bg-subtle); font-size: 12px; }
.model-name { font-weight: 600; color: var(--t-text-primary); }
.model-code { margin-left: auto; font-size: 10px; color: var(--t-text-muted); font-family: monospace; }
.field-list { }
.field-row { display: flex; justify-content: space-between; align-items: center; padding: 0 12px; height: 44px; min-height: 44px; border-top: 1px solid var(--t-border-subtle); transition: background 0.15s; }
.field-row:hover { background: var(--t-bg-subtle); }
.field-left { display: flex; align-items: center; gap: 8px; min-width: 0; flex: 1; }
.field-icon { width: 24px; min-width: 24px; height: 24px; display: flex; align-items: center; justify-content: center; font-size: 12px; background: var(--t-border-subtle); border-radius: 6px; color: var(--t-text-muted); flex-shrink: 0; }
.field-name { font-size: 13px; color: var(--t-text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.req { color: var(--t-danger); font-size: 10px; margin-left: 2px; flex-shrink: 0; }
.field-right { display: flex; align-items: center; gap: 6px; flex-shrink: 0; margin-left: 12px; }
.ftag { font-size: 10px; padding: 2px 8px; border-radius: 4px; white-space: nowrap; line-height: 1.4; }
.ftag.dict { background: rgba(245,158,11,0.12); color: var(--t-warning); }
.ftag.ref { background: rgba(96,165,250,0.12); color: var(--t-info); }
.ftype { font-size: 11px; color: var(--t-text-muted); white-space: nowrap; }

/* 模型选择 */
.model-select-bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; padding: 8px 12px; background: var(--t-border-subtle); border-radius: 8px; }
.builder-model-bar { gap: 14px; border: 1px solid var(--t-border-subtle); background: var(--t-bg-elevated); border-radius: 12px; padding: 10px 14px; }
.builder-model-meta { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.builder-model-label { font-size: 12px; font-weight: 600; color: var(--t-text-primary); }
.builder-model-select { width: min(460px, 60%); flex-shrink: 0; }
.builder-model-select :deep(.el-select__wrapper) {
  min-height: 38px;
  border-radius: 12px;
  background: var(--t-bg-base);
  box-shadow: inset 0 0 0 1px var(--t-border-subtle);
}
.builder-model-select :deep(.el-select__selected-item),
.builder-model-select :deep(.el-select__placeholder) {
  color: var(--t-text-primary);
}
.builder-model-select :deep(.el-select__caret),
.builder-model-select :deep(.el-select__suffix) {
  color: var(--t-text-muted);
}
.builder-model-option-row { display: flex; flex-direction: column; align-items: flex-start; gap: 4px; padding: 4px 0; }
.builder-model-option-name { color: var(--t-text-primary); }
.builder-model-option-meta { font-size: 12px; color: var(--t-text-muted); }
.model-select-all { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--t-text-primary); cursor: pointer; }
.model-select-all input { accent-color: var(--t-brand); }
.model-select-tip { font-size: 11px; color: var(--t-text-muted); }
.model-checkbox { display: flex; align-items: center; cursor: pointer; }
.model-checkbox input { accent-color: var(--t-brand); width: 14px; height: 14px; }
.model-card.model-deselected { opacity: 0.35; }
.model-card.model-deselected:hover { opacity: 0.6; }

/* ── 表单 ── */
.form-selector { display: flex; gap: 4px; margin-bottom: 12px; overflow-x: auto; padding-bottom: 4px; }
.form-tab { font-size: 12px; padding: 4px 10px; border-radius: 8px; border: none; background: none; color: var(--t-text-muted); cursor: pointer; white-space: nowrap; transition: all 0.2s; }
.form-tab.active { background: var(--t-brand-subtle); color: var(--t-brand-light); font-weight: 500; }
.form-preview { border: 1px solid var(--t-border-subtle); border-radius: 12px; overflow: hidden; background: var(--t-bg-elevated); }
.form-title { background: var(--t-brand-subtle); padding: 8px 16px; font-size: 12px; font-weight: 600; color: var(--t-brand-light); border-bottom: 1px solid var(--t-brand-subtle); }
.form-fields-grid { padding: 16px; display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.form-field { min-width: 0; }
.form-field.full-width { grid-column: 1 / -1; }
.form-label { font-size: 12px; color: var(--t-text-secondary); margin-bottom: 4px; }
.form-mock { border: 1px solid var(--t-border-subtle); border-radius: 8px; padding: 6px 10px; font-size: 12px; color: var(--t-text-muted); background: var(--t-border-subtle); display: flex; justify-content: space-between; }
.form-mock.tall { min-height: 56px; }
.mock-auto { font-style: italic; color: var(--t-text-muted); }
.mock-arrow { color: var(--t-text-muted); }
.mock-link { color: var(--t-info); }
.mock-switch { color: var(--t-text-muted); font-size: 10px; letter-spacing: -1px; }

/* ── 子表 ── */
.subtable-wrapper { border: 1px solid var(--t-border-subtle); border-radius: 8px; overflow: hidden; }
.subtable { width: 100%; border-collapse: collapse; font-size: 12px; }
.subtable thead { background: var(--t-bg-subtle); }
.subtable th { padding: 6px 10px; text-align: left; font-weight: 500; color: var(--t-text-secondary); border-bottom: 1px solid var(--t-border-subtle); white-space: nowrap; }
.subtable td { padding: 6px 10px; border-bottom: 1px solid var(--t-border-subtle); color: var(--t-text-secondary); }
.subtable-idx { width: 32px; text-align: center; color: var(--t-text-muted); }
.subtable-op { width: 48px; text-align: center; }
.subtable-del { color: var(--t-danger); cursor: pointer; font-size: 11px; }
.subtable-placeholder { color: var(--t-text-muted); display: flex; justify-content: space-between; align-items: center; }
.subtable-data-selector { display: flex; justify-content: space-between; align-items: center; }
.subtable-add { padding: 8px; text-align: center; font-size: 12px; color: var(--t-brand-light); cursor: pointer; border-top: 1px dashed var(--t-border-subtle); transition: background 0.2s; }
.subtable-add:hover { background: var(--t-bg-subtle); }

/* ── 流程 ── */
.wf-card { border: 1px solid var(--t-border-subtle); border-radius: 12px; overflow: hidden; margin-bottom: 12px; background: var(--t-bg-elevated); }
.wf-header { display: flex; justify-content: space-between; padding: 8px 12px; background: var(--t-bg-subtle); }
.wf-name { font-size: 12px; font-weight: 600; color: var(--t-text-primary); }
.wf-form { font-size: 10px; color: var(--t-text-muted); }
.wf-nodes { display: flex; flex-direction: column; align-items: center; padding: 16px; gap: 4px; }
.wf-node { padding: 8px 16px; border-radius: 8px; font-size: 12px; font-weight: 500; text-align: center; min-width: 120px; }
.wf-node.start { background: rgba(16,185,129,0.12); color: var(--t-success); border-radius: 20px; }
.wf-node.approve { background: var(--t-brand-subtle); color: var(--t-brand-light); }
.wf-node.end { background: var(--t-border-subtle); color: var(--t-text-muted); border-radius: 20px; }
.wf-role { font-size: 10px; opacity: 0.7; margin-top: 2px; }
.wf-arrow { color: var(--t-text-muted); font-size: 12px; }

/* ── 权限 ── */
.perm-card { border: 1px solid var(--t-border-subtle); border-radius: 12px; overflow: hidden; margin-bottom: 12px; background: var(--t-bg-elevated); }
.perm-header { padding: 8px 12px; background: var(--t-bg-subtle); font-size: 12px; font-weight: 600; color: var(--t-text-primary); }
.perm-table { width: 100%; border-collapse: collapse; }
.perm-table th { font-size: 10px; color: var(--t-text-muted); font-weight: 500; text-align: left; padding: 6px 12px; border-bottom: 1px solid var(--t-border-subtle); }
.perm-table td { font-size: 12px; color: var(--t-text-secondary); padding: 6px 12px; border-bottom: 1px solid var(--t-border-subtle); }
.data-tag { font-size: 10px; padding: 2px 6px; border-radius: 4px; }
.data-tag.all { background: rgba(239,68,68,0.12); color: var(--t-danger); }
.data-tag.dept { background: rgba(245,158,11,0.12); color: var(--t-warning); }
.data-tag.self { background: rgba(96,165,250,0.12); color: var(--t-info); }

.connect-warn { padding: 16px; }
.connect-warn > div { background: rgba(245,158,11,0.08); border: 1px solid rgba(245,158,11,0.15); border-radius: 12px; padding: 12px; font-size: 12px; }
.warn-title { color: var(--t-warning); font-weight: 500; margin-bottom: 4px; }
.connect-warn p { color: rgba(245,158,11,0.7); margin: 0 0 8px; }
.warn-link { color: var(--t-warning); text-decoration: underline; background: none; border: none; cursor: pointer; font-size: 12px; }

/* ── 部署面板（第三栏） ── */
.deploy-side {
  width: 0; min-width: 0; overflow: hidden;
  background: var(--t-bg-base); border-left: 1px solid var(--t-border-subtle);
  display: flex; flex-direction: column; transition: width 0.3s ease, min-width 0.3s ease;
}
.deploy-side.open { width: 340px; min-width: 340px; }
@media (max-width: 1200px) {
  .deploy-side.open { position: absolute; right: 0; top: 0; bottom: 0; z-index: 20; width: 360px; min-width: 360px; box-shadow: -4px 0 24px rgba(0,0,0,0.4); }
}

.deploy-header { display: flex; justify-content: space-between; align-items: center; padding: 16px 16px 8px; }
.deploy-title { font-size: 14px; font-weight: 700; color: var(--t-text-primary); }
.deploy-desc { font-size: 11px; color: var(--t-text-muted); margin-top: 2px; }
.deploy-close { all: unset; cursor: pointer; color: var(--t-text-muted); font-size: 16px; padding: 4px; transition: color 0.2s; }
.deploy-close:hover { color: var(--t-text-secondary); }

.deploy-progress { padding: 0 16px 8px; display: flex; align-items: center; gap: 8px; }
.dp-track { flex: 1; height: 3px; background: var(--t-border-subtle); border-radius: 2px; overflow: hidden; }
.dp-fill { height: 100%; background: var(--t-brand-gradient); border-radius: 2px; transition: width 0.5s; }
.dp-meta { font-size: 10px; color: var(--t-text-muted); white-space: nowrap; }

.deploy-actions { padding: 0 16px 12px; }
.dp-run-all {
  width: 100%; padding: 8px;
  background: var(--t-brand-gradient);
  color: #fff; border: none; border-radius: 8px; font-size: 12px; cursor: pointer; font-weight: 500;
  transition: transform 0.2s, box-shadow 0.2s;
}
.dp-run-all:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 4px 12px var(--t-brand-glow); }
.dp-run-all:disabled { opacity: 0.35; cursor: not-allowed; background: var(--t-border-subtle); }

.deploy-groups { flex: 1; overflow-y: auto; padding: 0 12px 12px; }
.dg { background: var(--t-bg-elevated); border: 1px solid var(--t-border-subtle); border-radius: 12px; margin-bottom: 8px; overflow: hidden; }
.dg.done { border-color: rgba(16,185,129,0.25); }
.dg.err { border-color: rgba(239,68,68,0.25); }
.dg-hd { display: flex; align-items: center; gap: 6px; padding: 10px 14px; background: var(--t-bg-subtle); font-size: 12px; }
.dg-icon { font-size: 13px; }
.dg-name { font-weight: 600; color: var(--t-text-primary); flex: 1; }
.dg-badge { font-size: 9px; padding: 1px 6px; border-radius: 99px; font-weight: 600; background: var(--t-border-subtle); color: var(--t-text-muted); }
.dg-badge.done { background: rgba(16,185,129,0.12); color: var(--t-success); }
.dg-badge.err { background: rgba(239,68,68,0.12); color: var(--t-danger); }

.ds { display: flex; align-items: center; padding: 7px 14px; gap: 10px; font-size: 12px; }
.ds + .ds { border-top: 1px solid var(--t-border-subtle); }
.ds:hover { background: var(--t-bg-subtle); }
.ds-dot { width: 18px; height: 18px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 9px; font-weight: 700; color: #fff; flex-shrink: 0; }
.ds-dot.completed { background: var(--t-success); }
.ds-dot.error { background: var(--t-danger); }
.ds-dot.pending { background: var(--t-border-strong); width: 7px; height: 7px; margin: 0 5.5px; }
.ds-dot.pulse { background: var(--t-brand); animation: dpulse 1.5s infinite; }
@keyframes dpulse { 0%,100% { box-shadow: 0 0 0 0 var(--t-brand-glow); } 50% { box-shadow: 0 0 0 5px var(--t-brand-subtle); } }

.ds-body { flex: 1; min-width: 0; }
.ds-name { color: var(--t-text-primary); }
.ds.completed .ds-name { color: var(--t-text-muted); }
.ds.pending .ds-name { color: var(--t-text-muted); }
.ds-err { font-size: 10px; color: var(--t-danger); margin-top: 1px; }

.ds-act { flex-shrink: 0; }
.ds-btn { border: none; cursor: pointer; border-radius: 6px; font-weight: 500; font-size: 11px; transition: transform 0.2s; }
.ds-btn.run { padding: 3px 10px; background: var(--t-brand-gradient); color: #fff; }
.ds-btn.run:hover:not(:disabled) { transform: translateY(-1px); }
.ds-btn.retry { padding: 3px 10px; background: var(--t-danger); color: #fff; }
.ds-btn.redo { padding: 2px 5px; background: none; color: var(--t-text-muted); font-size: 14px; }
.ds-btn.redo:hover:not(:disabled) { color: var(--t-brand-light); }
.ds-btn:disabled { opacity: 0.35; cursor: not-allowed; }
.ds-spin { display: inline-block; width: 14px; height: 14px; border: 2px solid var(--t-border-subtle); border-top-color: var(--t-brand); border-radius: 50%; animation: spin 0.7s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.ds-lock { font-size: 11px; opacity: 0.15; }

.deploy-done { padding: 12px 16px; text-align: center; font-size: 13px; color: var(--t-success); font-weight: 500; }
.deploy-done-btn {
  background: var(--t-brand-gradient); color: #fff; border: none;
  border-radius: 6px; padding: 5px 12px; font-size: 12px; cursor: pointer; margin-left: 8px;
  transition: transform 0.2s;
}
.deploy-done-btn:hover { transform: translateY(-1px); }
.deploy-log-btn {
  background: none; border: 1px solid var(--t-border-subtle); color: var(--t-text-secondary);
  border-radius: 6px; padding: 5px 10px; font-size: 11px; cursor: pointer; margin-left: 6px;
}
.deploy-log-btn:hover { background: var(--t-bg-subtle); color: #fff; }

/* API 日志弹窗 */
.api-logs-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.api-logs-count { font-size: 12px; color: var(--t-text-muted); }
.api-logs-table { max-height: 500px; overflow-y: auto; }
.api-logs-table table { width: 100%; border-collapse: collapse; font-size: 12px; }
.api-logs-table th { text-align: left; padding: 8px 10px; color: var(--t-text-secondary); border-bottom: 1px solid var(--t-border-subtle); font-weight: 500; }
.api-logs-table td { padding: 6px 10px; border-bottom: 1px solid var(--t-border-subtle); color: var(--t-text-primary); }
.api-logs-table tr.error td { color: var(--t-danger); }
.api-logs-table tr:hover td { background: var(--t-bg-subtle); }
.log-time { font-family: monospace; color: var(--t-text-muted); }
.log-step { color: var(--t-brand-light); }
.log-url { max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.log-status.ok { color: var(--t-success); }
.log-status.fail { color: var(--t-danger); font-weight: 600; }
.log-ms { font-family: monospace; color: var(--t-text-secondary); }
.log-result { max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.api-logs-empty { text-align: center; padding: 40px; color: var(--t-text-muted); }

/* ── nav-right 项目按钮 ── */
.nav-link.active { background: var(--t-brand-subtle); color: var(--t-brand-light); }
.project-count {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 18px; height: 18px; padding: 0 5px;
  background: var(--t-brand-gradient); color: #fff; border-radius: 9px;
  font-size: 10px; font-weight: 600; margin-left: 4px;
}


/* ── 平台配置 iframe ── */
.platform-iframe-container {
  flex: 1; display: flex; flex-direction: column; min-height: 0;
}
.platform-tab-bar {
  display: flex; align-items: center; gap: 4px; padding: 4px 16px;
  border-bottom: 1px solid var(--t-border-subtle);
  flex-shrink: 0; background: rgba(0,0,0,0.3); height: 36px;
}
.platform-fullscreen-btn {
  all: unset; cursor: pointer; margin-left: auto; color: var(--t-text-muted);
  font-size: 16px; padding: 2px 8px; border-radius: 4px;
}
.platform-fullscreen-btn:hover { color: #fff; background: var(--t-border-subtle); }
.platform-login-hint {
  display: flex; align-items: center; gap: 12px; padding: 6px 16px;
  background: var(--t-brand-subtle); border-bottom: 1px solid var(--t-brand-subtle);
  font-size: 12px; color: var(--t-text-secondary); flex-shrink: 0;
}
.platform-login-hint b { color: var(--t-brand-light); }
.hint-nav-btn {
  margin-left: auto; background: var(--t-brand-gradient); color: #fff;
  border: none; border-radius: 6px; padding: 4px 12px; font-size: 12px; cursor: pointer;
  white-space: nowrap;
}
.hint-nav-btn:hover { opacity: 0.9; }
.hint-dismiss-btn {
  all: unset; cursor: pointer; color: var(--t-text-muted); font-size: 14px; padding: 2px;
}
.hint-dismiss-btn:hover { color: var(--t-text-secondary); }
.platform-iframe {
  width: 100%; height: 100%; border: none; background: #fff; flex: 1;
}
.platform-loading {
  flex: 1; display: flex; align-items: center; justify-content: center;
  color: var(--t-text-secondary); font-size: 14px; gap: 8px;
}
.platform-loading .loading-spinner {
  display: inline-block; animation: spin 1s linear infinite;
}
.platform-error {
  flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center;
  color: var(--t-text-secondary); gap: 16px; padding: 40px;
}
.platform-error p { margin: 0; font-size: 14px; text-align: center; max-width: 400px; }
.platform-error-actions { display: flex; gap: 12px; }
.platform-retry-btn, .platform-open-btn {
  padding: 8px 20px; border-radius: 8px; border: none; cursor: pointer;
  font-size: 13px; transition: transform 0.2s, box-shadow 0.2s;
}
.platform-retry-btn {
  background: var(--t-brand-gradient); color: #fff;
}
.platform-retry-btn:hover { transform: translateY(-1px); box-shadow: 0 4px 12px var(--t-brand-glow); }
.platform-open-btn {
  background: var(--t-border-subtle); color: var(--t-text-secondary); border: 1px solid var(--t-border-subtle);
}
.platform-open-btn:hover { background: var(--t-bg-subtle); }

/* ── 变更计划 overlay ── */
.change-plan-overlay {
  position: absolute;
  inset: 0;
  z-index: 20;
  background: var(--t-bg-base);
  display: flex;
  flex-direction: column;
  border-left: 1px solid var(--t-border-subtle);
}
.change-plan-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--t-border-subtle);
}
.change-plan-header h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--t-text-primary);
}
.change-plan-close {
  background: none;
  border: none;
  color: var(--t-text-muted);
  font-size: 18px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 4px;
}
.change-plan-close:hover {
  color: #fff;
  background: var(--t-border-subtle);
}
.change-plan-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px 20px;
}
.change-plan-diff {
  margin-bottom: 16px;
}
.change-group {
  margin-bottom: 16px;
}
.group-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--t-text-secondary);
  cursor: pointer;
  padding: 6px 0;
  user-select: none;
}
.group-title:hover { color: var(--t-text-primary); }
.group-arrow {
  display: inline-block;
  transition: transform 0.15s;
  font-size: 11px;
}
.group-arrow.expanded { transform: rotate(90deg); }
.change-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px 6px 18px;
  border-radius: 6px;
  font-size: 13px;
  color: var(--t-text-primary);
}
.change-item:hover { background: var(--t-bg-subtle); }
.change-checkbox {
  accent-color: var(--t-brand);
  width: 14px;
  height: 14px;
  cursor: pointer;
}
.change-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 4px;
  font-size: 13px;
  font-weight: 700;
  flex-shrink: 0;
}
.change-icon.add {
  background: rgba(16, 185, 129, 0.15);
  color: var(--t-success);
}
.change-icon.modify {
  background: rgba(234, 179, 8, 0.15);
  color: #eab308;
}
.change-icon.remove {
  background: rgba(239, 68, 68, 0.15);
  color: var(--t-danger);
}
.change-desc { flex: 1; line-height: 1.4; }
.change-plan-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 20px;
  border-top: 1px solid var(--t-border-subtle);
  flex-wrap: wrap;
}
.cp-btn {
  padding: 6px 14px;
  border-radius: 6px;
  border: 1px solid var(--t-border-strong);
  background: var(--t-bg-subtle);
  color: var(--t-text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.cp-btn:hover {
  background: var(--t-border-subtle);
  color: #fff;
}
.cp-btn.primary {
  background: var(--t-brand);
  border-color: var(--t-brand);
  color: #fff;
}
.cp-btn.primary:hover { background: #6d28d9; }
.cp-btn.primary:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.cp-count {
  font-size: 12px;
  color: var(--t-text-secondary);
  margin-left: auto;
  margin-right: 4px;
}
.change-plan-body::-webkit-scrollbar { width: 4px; }
.change-plan-body::-webkit-scrollbar-track { background: transparent; }
.change-plan-body::-webkit-scrollbar-thumb { background: var(--t-border-subtle); border-radius: 2px; }
.change-plan-body::-webkit-scrollbar-thumb:hover { background: var(--t-border-strong); }

/* 增量更新弹窗 */
.incremental-modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.incremental-modal {
  background: var(--t-bg-panel);
  border-radius: 16px;
  width: 90%;
  max-width: 600px;
  max-height: 80vh;
  overflow-y: auto;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.4);
}

.incremental-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--t-border-subtle);
}

.incremental-header h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: #fff;
}

.incremental-close {
  background: none;
  border: none;
  color: #888;
  font-size: 20px;
  cursor: pointer;
  padding: 4px;
  line-height: 1;
  transition: color 0.2s;
}

.incremental-close:hover {
  color: #fff;
}

.incremental-diff {
  padding: 16px 20px;
  border-bottom: 1px solid var(--t-border-subtle);
}

.incremental-steps {
  padding: 16px 20px;
}

/* ── 滚动条 ── */
.messages::-webkit-scrollbar,
.preview-body::-webkit-scrollbar,
.deploy-groups::-webkit-scrollbar,
.projects-list::-webkit-scrollbar { width: 4px; }
.messages::-webkit-scrollbar-track,
.preview-body::-webkit-scrollbar-track,
.deploy-groups::-webkit-scrollbar-track,
.projects-list::-webkit-scrollbar-track { background: transparent; }
.messages::-webkit-scrollbar-thumb,
.preview-body::-webkit-scrollbar-thumb,
.deploy-groups::-webkit-scrollbar-thumb,
.projects-list::-webkit-scrollbar-thumb { background: var(--t-border-subtle); border-radius: 2px; }
.messages::-webkit-scrollbar-thumb:hover,
.preview-body::-webkit-scrollbar-thumb:hover,
.deploy-groups::-webkit-scrollbar-thumb:hover,
.projects-list::-webkit-scrollbar-thumb:hover { background: var(--t-border-strong); }

/* 编码冲突修复 */
.conflict-resolve-box { padding: 4px 0; }
.conflict-label { margin-bottom: 8px; font-size: 13px; }
.conflict-label code { background: rgba(139, 92, 246, 0.2); color: var(--t-brand-light); padding: 1px 6px; border-radius: 4px; font-family: monospace; font-size: 12px; }
.conflict-input-row { display: flex; gap: 8px; align-items: center; }
.conflict-input { flex: 1; padding: 6px 10px; border: 1px solid var(--t-border-strong); border-radius: 6px; background: var(--t-border-subtle); color: #e2e8f0; font-size: 13px; font-family: monospace; outline: none; transition: border-color 0.2s; }
.conflict-input:focus { border-color: var(--t-brand); }
.conflict-input:disabled { opacity: 0.5; }
.conflict-btn { border: none; cursor: pointer; border-radius: 6px; font-size: 12px; font-weight: 500; padding: 6px 14px; transition: all 0.2s; }
.conflict-btn.confirm { background: var(--t-brand-gradient); color: #fff; }
.conflict-btn.confirm:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 2px 8px var(--t-brand-glow); }
.conflict-btn.cancel { background: var(--t-border-subtle); color: #94a3b8; }
.conflict-btn.cancel:hover:not(:disabled) { background: var(--t-bg-subtle); }
.conflict-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* ── 智能开发 tab (iframe embed) ── */
.coding-content {
  flex: 1; display: flex; flex-direction: column; overflow: hidden;
  min-height: 0; height: 100%;
}
.coding-embed-frame {
  flex: 1; width: 100%; height: 100%; border: none;
}

/* ── Requirements mode ── */
.req-action-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 16px 0;
}
.req-gen-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 6px 14px;
  background: var(--t-brand-gradient);
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}
.req-gen-btn:hover:not(:disabled) {
  opacity: 0.9;
  transform: translateY(-1px);
}
.req-gen-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.req-hint {
  font-size: 11px;
  color: var(--t-text-muted);
}
</style>
