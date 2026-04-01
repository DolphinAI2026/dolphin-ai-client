<template>
  <div class="coding-page">
    <!-- Header (嵌入模式隐藏) -->
    <header v-if="!embeddedAppId" class="coding-header">
      <div class="header-left">
        <el-button text @click="$router.push('/chat')">
          <el-icon><ArrowLeft /></el-icon>
        </el-button>
        <h3 class="header-title">AI Coding</h3>
        <el-tag
          v-if="codingStore.workspace"
          size="small"
          type="info"
          :title="workspaceTooltip(codingStore.workspace)"
          class="header-ws-tag"
        >
          {{ workspaceDisplayName(codingStore.workspace) }}
        </el-tag>
      </div>
      <div class="header-right">
        <!-- Chat / IDE 切换按钮（有 IDE URL 时显示） -->
        <div v-if="ideUrl || streamMessages.length > 0" class="view-toggle">
          <button
            class="view-toggle-btn"
            :class="{ active: activeView === 'chat' }"
            @click="activeView = 'chat'"
            title="对话记录"
          >
            <el-icon :size="16"><ChatDotRound /></el-icon>
            <span class="view-toggle-label">Chat</span>
          </button>
          <button
            class="view-toggle-btn"
            :class="{ active: activeView === 'ide', disabled: !ideUrl }"
            :disabled="!ideUrl"
            @click="ideUrl && (activeView = 'ide')"
            title="代码编辑器"
          >
            <el-icon :size="16"><Monitor /></el-icon>
            <span class="view-toggle-label">IDE</span>
          </button>
        </div>
        <ThemeToggle />
        <template v-if="codingStore.workspace">
          <!-- 调试功能暂时隐藏 -->
          <!-- <el-button
            size="small"
            class="header-btn"
            @click="showEnvPicker = true; loadPlatformEnvs()"
            title="浏览器预览"
          >
            <el-icon><Monitor /></el-icon>
          </el-button> -->
          <el-button
            size="small"
            type="success"
            :loading="isDownloading"
            class="header-btn"
            @click="downloadCode"
            title="下载代码"
          >
            <el-icon><Download /></el-icon>
          </el-button>
          <el-button
            size="small"
            type="danger"
            text
            class="header-btn"
            @click="deleteCurrentWorkspace"
            title="删除当前工作区"
          >
            <el-icon><Delete /></el-icon>
          </el-button>
        </template>
      </div>
    </header>

    <!-- 嵌入模式浮动工具栏（智能开发 tab 内使用） -->
    <div v-if="embeddedAppId" class="embedded-toolbar">
      <div v-if="ideUrl || streamMessages.length > 0" class="view-toggle">
        <button
          class="view-toggle-btn"
          :class="{ active: activeView === 'chat' }"
          @click="activeView = 'chat'"
          title="对话记录"
        >
          <el-icon :size="14"><ChatDotRound /></el-icon>
          <span class="view-toggle-label">Chat</span>
        </button>
        <button
          class="view-toggle-btn"
          :class="{ active: activeView === 'ide', disabled: !ideUrl }"
          :disabled="!ideUrl"
          @click="ideUrl && (activeView = 'ide')"
          title="代码编辑器"
        >
          <el-icon :size="14"><Monitor /></el-icon>
          <span class="view-toggle-label">IDE</span>
        </button>
      </div>
      <el-tag
        v-if="codingStore.workspace"
        size="small"
        type="info"
        class="embedded-ws-tag"
      >
        {{ workspaceDisplayName(codingStore.workspace) }}
      </el-tag>
      <template v-if="codingStore.workspace">
        <el-button
          size="small"
          type="success"
          :loading="isDownloading"
          @click="downloadCode"
          title="下载代码"
          circle
        >
          <el-icon><Download /></el-icon>
        </el-button>
        <el-button
          size="small"
          type="danger"
          text
          @click="deleteCurrentWorkspace"
          title="删除当前工作区"
          circle
        >
          <el-icon><Delete /></el-icon>
        </el-button>
      </template>
    </div>

    <!-- Env Picker Dialog -->
    <el-dialog v-model="showEnvPicker" title="选择调试平台环境" width="500px" :append-to-body="true">
      <div v-if="platformEnvs.length === 0" style="text-align:center;color:#999;padding:20px;">
        暂无平台环境，请先到<el-link type="primary" @click="$router.push('/platform-envs')">环境管理</el-link>添加
      </div>
      <div v-else style="display:flex;flex-direction:column;gap:12px;">
        <div
          v-for="env in platformEnvs"
          :key="env.id"
          style="border:1px solid #dcdfe6;border-radius:8px;padding:16px;cursor:pointer;transition:all 0.2s;"
          :style="{ borderColor: env.status === 'connected' ? '#67c23a' : '#dcdfe6' }"
          @click="openBrowserPreviewWithEnv(env)"
        >
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <strong>{{ env.env_name }}</strong>
            <el-tag v-if="env.status === 'connected'" type="success" size="small">已连接</el-tag>
            <el-tag v-else type="info" size="small">未连接</el-tag>
          </div>
          <div style="color:#999;font-size:12px;margin-top:6px;">{{ env.base_url }}</div>
        </div>
      </div>
    </el-dialog>

    <div class="coding-body">
      <!-- Left Sidebar: Workspace List -->
      <aside class="workspace-sidebar" :class="{ collapsed: sidebarCollapsed }">
        <!-- Collapsed: only icons -->
        <div v-if="sidebarCollapsed" class="sidebar-collapsed-content">
          <button class="sidebar-toggle-btn" @click="sidebarCollapsed = false" title="展开侧栏">
            <el-icon :size="16"><Expand /></el-icon>
          </button>
          <button class="sidebar-icon-btn" @click="startNewWorkspace" title="新建工作区">
            <el-icon :size="16"><Plus /></el-icon>
          </button>
          <div class="sidebar-collapsed-divider"></div>
          <button
            v-for="ws in existingWorkspaces.slice(0, 8)"
            :key="ws.id"
            class="sidebar-icon-ws"
            :class="{ active: codingStore.workspace?.id === ws.id }"
            :title="workspaceDisplayName(ws)"
            @click="openExistingWorkspace(ws)"
          >{{ (workspaceDisplayName(ws) || '?')[0] }}</button>
        </div>

        <!-- Expanded: full list -->
        <template v-else>
          <div class="sidebar-section-header">
            <span class="sidebar-title">工作区</span>
            <div class="sidebar-header-actions">
              <button class="sidebar-action-btn sidebar-add-btn" @click="startNewWorkspace" title="新建工作区">
                <el-icon :size="14"><Plus /></el-icon>
              </button>
              <button class="sidebar-action-btn" @click="sidebarCollapsed = true" title="收起侧栏">
                <el-icon :size="14"><Fold /></el-icon>
              </button>
            </div>
          </div>
          <div class="sidebar-list">
            <template v-for="group in groupedWorkspaces" :key="group.key">
              <div class="sidebar-group-header" @click="toggleGroup(group.key)">
                <span class="sidebar-group-icon">{{ group.icon }}</span>
                <span class="sidebar-group-label">{{ group.label }}</span>
                <span class="sidebar-group-count">{{ group.items.length }}</span>
                <span class="sidebar-group-arrow" :class="{ collapsed: collapsedGroups.has(group.key) }">
                  <el-icon :size="10"><ArrowRight /></el-icon>
                </span>
              </div>
              <template v-if="!collapsedGroups.has(group.key)">
                <div
                  v-for="ws in group.items"
                  :key="ws.id"
                  class="sidebar-ws-item"
                  :class="{ active: codingStore.workspace?.id === ws.id }"
                  @click="openExistingWorkspace(ws)"
                >
                  <div class="sidebar-ws-name" :title="workspaceTooltip(ws)">{{ workspaceDisplayName(ws) }}</div>
                  <div v-if="workspaceCodeName(ws)" class="sidebar-ws-code">{{ workspaceCodeName(ws) }}</div>
                  <button class="sidebar-ws-del" @click.stop="deleteWorkspace(ws)" title="删除">&#215;</button>
                </div>
              </template>
            </template>
            <div v-if="existingWorkspaces.length === 0" class="sidebar-empty">
              暂无工作区
            </div>
          </div>
        </template>
      </aside>

      <!-- Main Content: Welcome or IDE -->
      <div class="main-content">
        <!-- Welcome State -->
        <div v-if="!ideUrl && !isStreaming && streamMessages.length === 0" class="welcome-pane">
          <div class="welcome-inner">
            <div class="welcome-icon">&#x2728;</div>
            <h2 class="welcome-title">描述你想开发的内容</h2>
            <p class="welcome-desc">告诉我你想开发什么，我会自动创建项目并打开 AI 代码编辑器。</p>

            <!-- Input Area (centered) -->
            <div class="welcome-input-area">
              <div class="coding-model-bar">
                <div class="coding-model-meta">
                  <span class="coding-model-label">当前模型</span>
                  <span class="coding-model-tip">{{ codingModelHint }}</span>
                </div>
                <el-select
                  v-model="selectedCodingModelValue"
                  class="coding-model-select"
                  popper-class="model-select-dropdown coding-model-dropdown"
                  size="large"
                  placeholder="选择模型"
                  :disabled="codingModelLoading || updatingCodingModel || codingModelOptions.length === 0"
                  @change="handleCodingModelChange"
                >
                  <el-option
                    v-for="option in codingModelOptions"
                    :key="option.id"
                    :label="formatCodingModelOption(option)"
                    :value="toCodingModelValue(option.id)"
                  >
                    <div class="coding-model-option-row">
                      <div class="coding-model-option-top">
                        <span class="coding-model-option-name">{{ option.config_name }}</span>
                        <div class="coding-model-option-tags">
                          <span class="coding-model-option-provider">{{ formatCodingModelProvider(option.provider) }}</span>
                          <span v-if="option.is_default" class="coding-model-option-default">默认</span>
                        </div>
                      </div>
                      <span class="coding-model-option-meta">{{ option.model }}</span>
                    </div>
                  </el-option>
                </el-select>
              </div>

              <!-- Attachment Preview -->
              <div v-if="attachedFile" class="attachment-preview">
                <div v-if="attachedPreviewUrl" class="attachment-thumb">
                  <img :src="attachedPreviewUrl" alt="preview" />
                  <button class="attachment-remove" @click="removeAttachment">&times;</button>
                </div>
                <div v-else class="attachment-file">
                  <span class="attachment-file-icon">&#128196;</span>
                  <span class="attachment-file-name">{{ attachedFile.name }}</span>
                  <button class="attachment-remove" @click="removeAttachment">&times;</button>
                </div>
              </div>

              <div class="input-wrapper" @paste="handlePaste">
                <input
                  ref="fileInputRef"
                  type="file"
                  accept=".md,.pdf,.docx,.txt,.png,.jpg,.jpeg"
                  style="display: none"
                  @change="handleFileSelect"
                />
                <el-button
                  text
                  class="attach-btn"
                  @click="fileInputRef?.click()"
                  :disabled="isCreating"
                  title="上传附件"
                >
                  <el-icon :size="18"><Paperclip /></el-icon>
                </el-button>
                <el-input
                  v-model="userInput"
                  type="textarea"
                  :rows="2"
                  :autosize="{ minRows: 2, maxRows: 6 }"
                  placeholder="描述你想开发的组件或页面... (Ctrl+Enter 发送)"
                  @keydown.ctrl.enter="sendMessage"
                  @keydown.meta.enter="sendMessage"
                  :disabled="isCreating"
                  resize="none"
                />
                <el-button
                  type="primary"
                  class="send-btn"
                  :loading="isCreating || isUploading"
                  @click="sendMessage"
                  :disabled="(!userInput.trim() && !attachedFile) || isCreating"
                  circle
                >
                  <el-icon v-if="!isCreating && !isUploading"><TopRight /></el-icon>
                </el-button>
              </div>
              <div class="input-hint">Ctrl + Enter 发送 | 粘贴截图或点击回形针添加附件</div>
            </div>

            <!-- Scene Category Chips -->
            <div class="scene-tabs">
              <button
                v-for="cat in sceneCategories"
                :key="cat.key"
                class="scene-tab"
                :class="{ active: activeSceneCategory === cat.key }"
                @click="activeSceneCategory = cat.key"
              >
                <span class="scene-tab-icon">{{ cat.icon }}</span>
                {{ cat.label }}
              </button>
            </div>

            <!-- Suggestion Cards -->
            <div class="suggestions-grid">
              <button
                v-for="s in activeSuggestions"
                :key="s"
                class="suggestion-card"
                @click="sendSuggestion(s)"
              >
                {{ s }}
              </button>
            </div>

          </div>
        </div>

        <!-- Stream Pane (对话流视图 - Chat 模式) -->
        <div v-else-if="activeView === 'chat'" class="stream-pane">
          <div class="stream-messages" ref="streamContainerRef">
            <div
              v-for="(msg, idx) in streamMessages"
              :key="idx"
              class="stream-msg"
              :class="'msg-' + msg.type"
            >
              <!-- 用户消息 -->
              <template v-if="msg.type === 'user'">
                <div class="msg-user-bubble">{{ msg.content }}</div>
              </template>

              <!-- AI 思考 -->
              <template v-else-if="msg.type === 'thinking'">
                <div class="msg-thinking">
                  <span class="msg-thinking-text">{{ msg.content }}</span>
                  <span v-if="idx === streamMessages.length - 1 && isStreaming" class="thinking-cursor">|</span>
                </div>
              </template>

              <!-- 状态消息 -->
              <template v-else-if="msg.type === 'status'">
                <div class="msg-status">{{ msg.content }}</div>
              </template>

              <!-- 文件写入 -->
              <template v-else-if="msg.type === 'file_write'">
                <div class="msg-file-write">
                  <div class="file-header" @click="msg.collapsed = !msg.collapsed">
                    <span class="file-icon">+</span>
                    <span class="file-name">{{ msg.fileName }}</span>
                    <span class="file-badge">新建</span>
                    <span class="file-toggle">{{ msg.collapsed ? '&#9654;' : '&#9660;' }}</span>
                  </div>
                  <div v-if="!msg.collapsed && msg.fileContent" class="file-code-block">
                    <pre><code>{{ msg.fileContent }}</code></pre>
                  </div>
                </div>
              </template>

              <!-- 文件编辑 -->
              <template v-else-if="msg.type === 'file_edit'">
                <div class="msg-file-edit">
                  <div class="file-header" @click="msg.collapsed = !msg.collapsed">
                    <span class="file-icon">~</span>
                    <span class="file-name">{{ msg.fileName }}</span>
                    <span class="file-badge edit-badge">修改</span>
                    <span class="file-toggle">{{ msg.collapsed ? '&#9654;' : '&#9660;' }}</span>
                  </div>
                  <div v-if="!msg.collapsed && msg.fileContent" class="file-code-block">
                    <pre><code>{{ msg.fileContent }}</code></pre>
                  </div>
                </div>
              </template>

              <!-- 工具调用 -->
              <template v-else-if="msg.type === 'tool'">
                <div class="msg-tool">{{ msg.content }}</div>
              </template>

              <!-- 命令执行 -->
              <template v-else-if="msg.type === 'command'">
                <div class="msg-command">
                  <span class="cmd-icon">$</span>
                  <span class="cmd-text">{{ msg.content }}</span>
                </div>
              </template>

              <!-- 错误 -->
              <template v-else-if="msg.type === 'error'">
                <div class="msg-error">{{ msg.content }}</div>
              </template>
            </div>

            <!-- 流式加载指示器 -->
            <div v-if="isStreaming" class="stream-loading">
              <span class="stream-dot"></span>
              <span class="stream-dot"></span>
              <span class="stream-dot"></span>
            </div>

            <!-- 完成后的操作区域 -->
            <div v-if="!isStreaming && pendingIdeUrl" class="stream-actions">
              <button class="open-ide-btn" @click="openPendingIde">
                <span class="ide-btn-icon">&#x1F4BB;</span>
                打开代码编辑器
              </button>
              <span class="stream-actions-hint">在编辑器中查看和修改 AI 生成的代码</span>
            </div>
          </div>

          <!-- Chat 底部输入框（非流式时可用） -->
          <div v-if="!isStreaming" class="chat-input-bar">
            <!-- 附件预览 -->
            <div v-if="attachedFile" class="chat-attachment-preview">
              <div v-if="attachedPreviewUrl" class="attachment-thumb">
                <img :src="attachedPreviewUrl" alt="preview" />
                <button class="attachment-remove" @click="removeAttachment">&times;</button>
              </div>
              <div v-else class="attachment-file">
                <span class="attachment-file-icon">&#128196;</span>
                <span class="attachment-file-name">{{ attachedFile.name }}</span>
                <button class="attachment-remove" @click="removeAttachment">&times;</button>
              </div>
            </div>
            <div class="chat-input-wrapper" @paste="handlePaste">
              <input
                ref="chatFileInputRef"
                type="file"
                accept=".md,.pdf,.docx,.txt,.png,.jpg,.jpeg"
                style="display: none"
                @change="handleFileSelect"
              />
              <el-button
                text
                class="attach-btn"
                @click="chatFileInputRef?.click()"
                :disabled="isCreating"
                title="上传附件"
              >
                <el-icon :size="16"><Paperclip /></el-icon>
              </el-button>
              <el-input
                v-model="userInput"
                type="textarea"
                :rows="1"
                :autosize="{ minRows: 1, maxRows: 4 }"
                placeholder="继续描述修改需求... (Ctrl+Enter 发送)"
                @keydown.ctrl.enter="sendMessage"
                @keydown.meta.enter="sendMessage"
                :disabled="isCreating"
                resize="none"
                class="chat-input"
              />
              <el-button
                type="primary"
                class="send-btn"
                :loading="isCreating"
                @click="sendMessage"
                :disabled="!userInput.trim() || isCreating"
                circle
                size="small"
              >
                <el-icon v-if="!isCreating"><TopRight /></el-icon>
              </el-button>
            </div>
          </div>
        </div>

        <!-- IDE State (with loading overlay) -->
        <div v-else class="ide-pane">
          <iframe
            v-if="ideUrl"
            :key="ideUrl"
            :src="ideUrl"
            class="ide-frame"
            allow="clipboard-read; clipboard-write"
            @load="ideLoaded = true"
          ></iframe>
          <!-- Loading overlay — stays until iframe fires load event -->
          <div v-if="!ideLoaded" class="ide-loading-overlay">
            <div class="ide-loading-content">
              <div class="ide-loading-spinner"></div>
              <span>正在加载 IDE...</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { API_PREFIX } from '@/utils/request'
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, ArrowRight, Download, TopRight, Plus, Paperclip, Monitor, Delete, Fold, Expand, ChatDotRound } from '@element-plus/icons-vue'
import { useCodingStore } from '@/stores/coding'
import { platformEnvApi, type PlatformEnv } from '@/api/platformEnv'
import { useUserStore } from '@/stores/user'
import { codingApi } from '@/api/coding'
import type { WorkspaceInfo, UploadResult, ReplayStreamMessage } from '@/api/coding'
import { harnessApi } from '@/api/harness'
import { conversationApi } from '@/api/conversation'
import { llmConfigApi, type BuilderModelOption } from '@/api/llmConfig'
import { consumeSseResponse } from '@/utils/sse'
import ThemeToggle from '@/components/ThemeToggle.vue'

const route = useRoute()
const codingStore = useCodingStore()
const userStore = useUserStore()

// ============ Core State ============
const userInput = ref('')
const ideUrl = ref<string | null>(null)
const ideLoaded = ref(false)
const isCreating = ref(false)
const creatingStatus = ref('')
const codingModelOptions = ref<BuilderModelOption[]>([])
const codingModelLoading = ref(false)
const updatingCodingModel = ref(false)
const selectedCodingModelValue = ref<string | null>(null)
const persistedCodingModelValue = ref<string | null>(null)

const toCodingModelValue = (configId: number | null | undefined) =>
  configId != null ? `llmcfg:${configId}` : null

const parseCodingModelConfigId = (modelValue?: string | null): number | null => {
  if (!modelValue?.startsWith('llmcfg:')) return null
  const parsed = Number(modelValue.slice('llmcfg:'.length))
  return Number.isFinite(parsed) ? parsed : null
}

const defaultCodingModelValue = computed(() =>
  toCodingModelValue(codingModelOptions.value.find(option => option.is_default)?.id)
  ?? toCodingModelValue(codingModelOptions.value[0]?.id)
  ?? null
)

const codingModelHint = computed(() => {
  if (codingModelLoading.value) return '正在加载可用模型...'
  if (codingModelOptions.value.length === 0) return '未配置可用模型，请前往环境管理配置'
  if (codingStore.conversationId) return '切换后仅影响后续开发与打开 IDE 的默认模型'
  return '首条消息会使用当前选择的模型'
})

const normalizeCodingModelValue = (modelValue?: string | null): string | null => {
  const values = new Set(codingModelOptions.value.map(option => toCodingModelValue(option.id)).filter(Boolean) as string[])
  if (modelValue && values.has(modelValue)) return modelValue
  return defaultCodingModelValue.value
}

const applyCodingModelSelection = (configId?: number | null) => {
  const normalized = normalizeCodingModelValue(toCodingModelValue(configId))
  selectedCodingModelValue.value = normalized
  persistedCodingModelValue.value = codingStore.conversationId ? normalized : null
}

const formatCodingModelOption = (option: BuilderModelOption): string => option.config_name

const formatCodingModelProvider = (provider: string): string => {
  const labels: Record<string, string> = {
    minimax: 'MiniMax',
    qwen: 'Qwen',
    gpt: 'GPT',
    codex: 'Codex',
    sonnet: 'Sonnet',
    opus: 'Opus',
    openai: 'OpenAI',
    anthropic: 'Anthropic',
  }
  return labels[provider] || provider
}

const loadCodingModelOptions = async () => {
  codingModelLoading.value = true
  try {
    codingModelOptions.value = await llmConfigApi.listOptions('coding')
    selectedCodingModelValue.value = normalizeCodingModelValue(selectedCodingModelValue.value)
    if (codingStore.conversationId) {
      persistedCodingModelValue.value = normalizeCodingModelValue(persistedCodingModelValue.value)
    }
  } catch (e) {
    console.error('获取 coding 模型列表失败:', e)
    codingModelOptions.value = []
    selectedCodingModelValue.value = null
    persistedCodingModelValue.value = null
  } finally {
    codingModelLoading.value = false
  }
}

const handleCodingModelChange = async (nextValue: string | null) => {
  selectedCodingModelValue.value = nextValue
  if (!codingStore.conversationId) return

  const previousValue = persistedCodingModelValue.value
  updatingCodingModel.value = true
  try {
    const updated = await conversationApi.updateModel(
      codingStore.conversationId,
      parseCodingModelConfigId(nextValue),
    )
    const normalized = normalizeCodingModelValue(toCodingModelValue(updated.selected_llm_config_id))
    selectedCodingModelValue.value = normalized
    persistedCodingModelValue.value = normalized
  } catch (e: any) {
    selectedCodingModelValue.value = normalizeCodingModelValue(previousValue)
    ElMessage.error(e?.response?.data?.detail || '切换模型失败')
  } finally {
    updatingCodingModel.value = false
  }
}

// ============ Stream Messages (对话流) ============
interface StreamMessage {
  type: 'user' | 'thinking' | 'tool' | 'file_write' | 'file_edit' | 'command' | 'status' | 'error'
  content: string
  fileName?: string
  fileContent?: string
  collapsed?: boolean
  timestamp: number
}
const streamMessages = ref<StreamMessage[]>([])
const isStreaming = ref(false)
const streamContainerRef = ref<HTMLElement>()
const pendingIdeUrl = ref<string | null>(null)
const activeView = ref<'chat' | 'ide'>('chat')

/** 清理模型输出中的 think 标签和多余空行 */
function cleanThinkTags(text: string): string {
  return text
    .replace(/<\/?think>/gi, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

function addStreamMsg(msg: Omit<StreamMessage, 'timestamp'>) {
  // 过滤 thinking 类型中的 <think> 标签
  const cleaned = { ...msg }
  if (cleaned.type === 'thinking' && cleaned.content) {
    cleaned.content = cleanThinkTags(cleaned.content)
    if (!cleaned.content) return // 过滤后为空则不添加
  }
  streamMessages.value.push({ ...cleaned, timestamp: Date.now() })
  // 自动滚动到底部
  nextTick(() => {
    const el = streamContainerRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function appendToLastThinking(text: string) {
  // delta 中也可能包含 <think> 标签片段，先追加再定期清理
  const msgs = streamMessages.value
  if (msgs.length > 0 && msgs[msgs.length - 1].type === 'thinking') {
    msgs[msgs.length - 1].content += text
    // 每次追加后清理标签（标签可能跨多个 delta 到达）
    msgs[msgs.length - 1].content = msgs[msgs.length - 1].content
      .replace(/<\/?think>/gi, '')
  } else {
    addStreamMsg({ type: 'thinking', content: text })
  }
  nextTick(() => {
    const el = streamContainerRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function appendToLastCommand(text: string) {
  const msgs = streamMessages.value
  if (msgs.length > 0 && msgs[msgs.length - 1].type === 'command') {
    msgs[msgs.length - 1].content += text
  } else {
    addStreamMsg({ type: 'command', content: text })
  }
  nextTick(() => {
    const el = streamContainerRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function restoreReplayStreamMessages(messages: ReplayStreamMessage[]) {
  streamMessages.value = messages.map((msg, index) => ({
    type: msg.type,
    content: msg.content || '',
    fileName: msg.fileName,
    fileContent: msg.fileContent,
    collapsed: msg.collapsed,
    timestamp: msg.timestamp || Date.now() + index,
  }))
  nextTick(() => {
    const el = streamContainerRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}
const allWorkspaces = ref<WorkspaceInfo[]>([])
const embeddedAppId = computed(() => (route.query.app_id as string) || '')
const existingWorkspaces = computed(() => {
  if (!embeddedAppId.value) return allWorkspaces.value
  return allWorkspaces.value.filter((ws: any) => String(ws.project_id || '') === embeddedAppId.value)
})
const isDownloading = ref(false)
const sidebarCollapsed = ref(false)

// ============ Attachment State ============
const attachedFile = ref<File | null>(null)
const attachedPreviewUrl = ref<string | null>(null)
const isUploading = ref(false)
const fileInputRef = ref<HTMLInputElement>()
const chatFileInputRef = ref<HTMLInputElement>()

// ============ Env Picker ============
const showEnvPicker = ref(false)
const platformEnvs = ref<PlatformEnv[]>([])

// ============ Workspace Grouping ============
const collapsedGroups = ref(new Set<string>())

const wsTypeGroupMap: Record<string, { key: string; icon: string; label: string; order: number }> = {
  'form-component':   { key: 'component-pc',     icon: '\uD83E\uDDE9', label: 'PC \u7EC4\u4EF6',     order: 1 },
  'menu-page':        { key: 'page-pc',          icon: '\uD83D\uDDA5\uFE0F', label: 'PC \u9875\u9762',     order: 2 },
  'form-page':        { key: 'page-pc',          icon: '\uD83D\uDDA5\uFE0F', label: 'PC \u9875\u9762',     order: 2 },
  'form-list':        { key: 'list-view',         icon: '\uD83D\uDCCB', label: '\u5217\u8868\u89C6\u56FE',   order: 3 },
  'layout':           { key: 'layout',            icon: '\uD83D\uDCD0', label: '\u5E94\u7528\u5E03\u5C40',   order: 4 },
  'plugin':           { key: 'plugin',            icon: '\uD83D\uDD0C', label: '\u6269\u5C55\u63D2\u4EF6',   order: 5 },
  'backend-api':      { key: 'backend',           icon: '\u2699\uFE0F', label: '\u540E\u7AEF\u63A5\u53E3',   order: 6 },
  'backend-feign':    { key: 'backend',           icon: '\uD83D\uDD17', label: '\u5916\u90E8\u8C03\u7528',  order: 6 },
  'backend-scheduled':{ key: 'backend',           icon: '\u23F0', label: '\u5B9A\u65F6\u4EFB\u52A1',  order: 6 },
}

const groupedWorkspaces = computed(() => {
  const groups: Record<string, { key: string; icon: string; label: string; order: number; items: WorkspaceInfo[] }> = {}
  for (const ws of existingWorkspaces.value) {
    const mapping = wsTypeGroupMap[ws.project_type] || { key: 'other', icon: '\uD83D\uDCE6', label: '\u5176\u4ED6', order: 99 }
    if (!groups[mapping.key]) {
      groups[mapping.key] = { ...mapping, items: [] }
    }
    const group = groups[mapping.key]
    if (group) {
      group.items.push(ws)
    }
  }
  return Object.values(groups).sort((a, b) => a.order - b.order)
})

function workspaceDisplayName(ws: WorkspaceInfo | null | undefined) {
  if (!ws) return ''
  return ws.display_name?.trim() || ws.project_name
}

function workspaceCodeName(ws: WorkspaceInfo | null | undefined) {
  if (!ws || !ws.project_name) return ''
  const displayName = workspaceDisplayName(ws)
  return displayName !== ws.project_name ? ws.project_name : ''
}

function workspaceTooltip(ws: WorkspaceInfo | null | undefined) {
  if (!ws) return ''
  const displayName = workspaceDisplayName(ws)
  const codeName = workspaceCodeName(ws)
  return codeName ? `${displayName}\n${codeName}` : displayName
}

function toggleGroup(key: string) {
  if (collapsedGroups.value.has(key)) {
    collapsedGroups.value.delete(key)
  } else {
    collapsedGroups.value.add(key)
  }
}

// ============ Scene Categories & Suggestions ============
const sceneCategories = [
  { key: 'component-pc', icon: '\uD83E\uDDE9', label: 'PC\u7EC4\u4EF6' },
  { key: 'page-pc', icon: '\uD83D\uDDA5\uFE0F', label: 'PC\u9875\u9762' },
  { key: 'list-view', icon: '\uD83D\uDCCB', label: '\u5217\u8868\u89C6\u56FE' },
  { key: 'layout', icon: '\uD83D\uDCD0', label: '\u5E94\u7528\u5E03\u5C40' },
  { key: 'plugin', icon: '\uD83D\uDD0C', label: '\u6269\u5C55\u63D2\u4EF6' },
  { key: 'backend', icon: '\u2699\uFE0F', label: '\u540E\u7AEF\u63A5\u53E3' },
  { key: 'backend-feign', icon: '\uD83D\uDD17', label: '\u5916\u90E8\u8C03\u7528' },
  { key: 'backend-scheduled', icon: '\u23F0', label: '\u5B9A\u65F6\u4EFB\u52A1' },
]

const sceneSuggestions: Record<string, string[]> = {
  'component-pc': [
    '\u5F00\u53D1\u4E00\u4E2A\u5934\u50CF\u4E0A\u4F20\u7EC4\u4EF6\uFF0C\u652F\u6301\u88C1\u526A\u548C\u9884\u89C8',
    '\u5B9E\u73B0\u4E00\u4E2A\u65E5\u671F\u8303\u56F4\u9009\u62E9\u5668\u7EC4\u4EF6',
    '\u505A\u4E00\u4E2A\u8BC4\u5206\u7EC4\u4EF6\uFF0C\u652F\u6301\u534A\u661F\u548C\u81EA\u5B9A\u4E49\u989C\u8272',
    '\u521B\u5EFA\u4E00\u4E2A\u56FE\u8868\u5206\u6790\u7EC4\u4EF6\uFF0C\u652F\u6301\u67F1\u72B6\u56FE\u548C\u997C\u56FE',
  ],
  'page-pc': [
    '\u505A\u4E00\u4E2A\u6570\u636E\u67E5\u8BE2\u8868\u683C\u9875\u9762\uFF0C\u5E26\u641C\u7D22\u548C\u5206\u9875',
    '\u5F00\u53D1\u4E00\u4E2A\u4F9B\u5E94\u5546\u7BA1\u7406\u5F39\u7A97\u9009\u62E9\u9875\u9762',
    '\u521B\u5EFA\u4E00\u4E2A\u9879\u76EE\u5206\u6790\u56FE\u8868\u9875\u9762',
    '\u505A\u4E00\u4E2A\u5BA1\u6279\u6D41\u7A0B\u9875\u9762\uFF0C\u652F\u6301\u591A\u7EA7\u5BA1\u6279',
  ],
  'list-view': [
    '\u81EA\u5B9A\u4E49\u4E00\u4E2A\u5361\u7247\u5F0F\u5217\u8868\u89C6\u56FE\uFF0C\u652F\u6301\u5207\u6362\u5361\u7247/\u8868\u683C\u6A21\u5F0F',
    '\u5F00\u53D1\u4E00\u4E2A\u5E26\u6811\u5F62\u5BFC\u822A\u7684\u5217\u8868\u89C6\u56FE',
    '\u505A\u4E00\u4E2A\u7518\u7279\u56FE\u5F0F\u7684\u9879\u76EE\u8FDB\u5EA6\u5217\u8868\u89C6\u56FE',
    '\u521B\u5EFA\u4E00\u4E2A\u770B\u677F\u5F0F\u7684\u4EFB\u52A1\u5217\u8868\u89C6\u56FE',
  ],
  layout: [
    '\u505A\u4E00\u4E2A\u5E26\u9876\u90E8\u516C\u544A\u680F\u7684\u81EA\u5B9A\u4E49\u5E03\u5C40',
    '\u521B\u5EFA\u4E00\u4E2A\u53CC\u680F\u5E03\u5C40\uFF0C\u5DE6\u4FA7\u83DC\u5355\u53EF\u6298\u53E0',
    '\u5F00\u53D1\u4E00\u4E2A\u6697\u8272\u4E3B\u9898\u7684\u81EA\u5B9A\u4E49\u5E94\u7528\u5E03\u5C40',
  ],
  plugin: [
    '\u5F00\u53D1\u4E00\u4E2A\u5E94\u7528\u8BE6\u60C5\u9875\u7684\u81EA\u5B9A\u4E49Tab\u63D2\u4EF6',
    '\u505A\u4E00\u4E2A\u81EA\u5B9A\u4E49\u9762\u677F\u6269\u5C55\uFF0C\u663E\u793A\u7EDF\u8BA1\u6570\u636E',
    '\u521B\u5EFA\u4E00\u4E2A\u7CFB\u7EDF\u901A\u77E5\u7BA1\u7406\u6269\u5C55\u63D2\u4EF6',
  ],
  backend: [
    '\u5F00\u53D1\u4E00\u4E2A\u81EA\u5B9A\u4E49\u6570\u636E\u67E5\u8BE2\u63A5\u53E3',
    '\u505A\u4E00\u4E2A\u6279\u91CF\u5BFC\u5165\u7684\u540E\u7AEF\u63A5\u53E3',
    '\u521B\u5EFA\u4E00\u4E2A\u62A5\u8868\u7EDF\u8BA1\u7684\u540E\u7AEFAPI',
  ],
  'backend-feign': [
    '\u8C03\u7528\u5916\u90E8 ERP \u7CFB\u7EDF\u7684\u5E93\u5B58\u67E5\u8BE2\u63A5\u53E3',
    '\u96C6\u6210\u7B2C\u4E09\u65B9\u77ED\u4FE1\u670D\u52A1\u53D1\u9001\u901A\u77E5',
    '\u5BF9\u63A5\u5916\u90E8 OA \u7CFB\u7EDF\u83B7\u53D6\u4EBA\u5458\u4FE1\u606F',
    '\u8C03\u7528\u5916\u90E8\u5929\u6C14 API \u83B7\u53D6\u5B9E\u65F6\u6570\u636E',
  ],
  'backend-scheduled': [
    '\u6BCF\u5929\u51CC\u6668\u540C\u6B65\u5916\u90E8\u7CFB\u7EDF\u6570\u636E\u5230\u672C\u5730',
    '\u6BCF\u5C0F\u65F6\u68C0\u67E5\u5E76\u5904\u7406\u8D85\u65F6\u672A\u5B8C\u6210\u7684\u4EFB\u52A1',
    '\u6BCF\u5468\u751F\u6210\u5E76\u53D1\u9001\u4E1A\u52A1\u6C47\u603B\u62A5\u8868',
    '\u5B9A\u65F6\u6E05\u7406\u8FC7\u671F\u65E5\u5FD7\u548C\u4E34\u65F6\u6570\u636E',
  ],
}

const activeSceneCategory = ref('component-pc')
const pendingSceneCategory = ref<string | null>(null)

const activeSuggestions = computed(() => sceneSuggestions[activeSceneCategory.value] || [])

const sceneCategoryToProjectType: Record<string, string> = {
  'component-pc': 'form-component',
  'page-pc': 'menu-page',
  'list-view': 'form-list',
  layout: 'layout',
  plugin: 'plugin',
  backend: 'backend-api',
  'backend-feign': 'backend-feign',
  'backend-scheduled': 'backend-scheduled',
}

// ============ Lifecycle ============

onMounted(async () => {
  try {
    const [workspaces] = await Promise.all([
      codingApi.listWorkspaces(),
      loadCodingModelOptions(),
    ])
    allWorkspaces.value = workspaces
  } catch (e) {
    console.error('\u521D\u59CB\u5316 AI Coding \u9875\u9762\u5931\u8D25:', e)
  }

  const wsId = (route.query.workspace_id || route.query.ws) as string
  if (wsId) {
    await openWorkspaceById(wsId)
  } else {
    const lastWsId = localStorage.getItem('coding_last_workspace_id')
    if (lastWsId && existingWorkspaces.value.some(w => w.id === lastWsId)) {
      await openWorkspaceById(lastWsId)
    } else {
      selectedCodingModelValue.value = normalizeCodingModelValue(selectedCodingModelValue.value)
    }
  }
})

onUnmounted(() => {
  // cleanup if needed
})

// ============ Workspace Operations ============

async function openExistingWorkspace(ws: WorkspaceInfo) {
  await openWorkspaceById(ws.id)
}

// 设置 IDE URL — 先销毁旧 iframe 再创建新的，避免 code-server session 缓存
async function setIdeUrl(url: string) {
  // 提取不含 cache-busting 参数的 base URL 做比较
  const baseUrl = url.replace(/[&?]_t=\d+$/, '')
  const currentBase = (ideUrl.value || '').replace(/[&?]_t=\d+$/, '')

  if (currentBase && currentBase === baseUrl) {
    // 同一个 URL — 不重建 iframe，保留 IDE 状态（Chat 历史、编辑器状态等）
    return
  }

  ideLoaded.value = false  // 显示 loading overlay
  ideUrl.value = null  // 销毁旧 iframe
  await new Promise(r => setTimeout(r, 100))  // 等 DOM 更新
  ideUrl.value = baseUrl + (baseUrl.includes('?') ? '&' : '?') + '_t=' + Date.now()
  // ideLoaded 会在 iframe @load 事件触发时置 true
}

async function openPendingIde() {
  if (!pendingIdeUrl.value) return
  await setIdeUrl(pendingIdeUrl.value)
  pendingIdeUrl.value = null
  activeView.value = 'ide'
}

async function openWorkspaceById(wsId: string) {
  try {
    const ws = await codingApi.getWorkspace(wsId)
    codingStore.setWorkspace(ws)
    localStorage.setItem('coding_last_workspace_id', wsId)
    const workspaceConversation = await codingApi.getWorkspaceConversation(ws.id)
    codingStore.conversationId = workspaceConversation.conversation_id
    applyCodingModelSelection(workspaceConversation.selected_llm_config_id)

    // 从后端加载历史消息填充到 streamMessages
    loadConversationHistory(
      workspaceConversation.messages,
      workspaceConversation.stream_messages || [],
    )

    const { ide_url } = await codingApi.getIdeUrl(ws.id, workspaceConversation.conversation_id)
    await setIdeUrl(ide_url)
    activeView.value = 'ide'
  } catch (error: any) {
    ElMessage.error(`打开工作区失败: ${error.message}`)
  }
}

/** 把后端保存的对话消息转换成 streamMessages 格式 */
function loadConversationHistory(
  messages: Array<{ role: string; content: string }>,
  replayStreamMessages: ReplayStreamMessage[] = [],
) {
  if (replayStreamMessages.length > 0) {
    restoreReplayStreamMessages(replayStreamMessages)
    return
  }
  streamMessages.value = []
  for (const msg of messages) {
    if (msg.role === 'user') {
      addStreamMsg({ type: 'user', content: msg.content })
    } else if (msg.role === 'assistant') {
      parseAssistantHistory(msg.content || '')
    }
  }
}

/** 解析后端保存的 assistant 历史文本，还原成对应的 stream message 类型 */
function parseAssistantHistory(text: string) {
  if (!text.trim()) return
  const lines = text.split('\n')
  let thinkingBuf = ''

  const flushThinking = () => {
    const t = thinkingBuf.trim()
    if (t) addStreamMsg({ type: 'thinking', content: t })
    thinkingBuf = ''
  }

  for (const line of lines) {
    // 工具调用: 🔧 **工具名** `preview`
    if (line.startsWith('🔧 **')) {
      flushThinking()
      const match = line.match(/🔧 \*\*(.+?)\*\*\s*`?(.+?)?`?$/)
      if (match) {
        addStreamMsg({ type: 'tool', content: `${match[1]} ${match[2] || ''}`.trim() })
      } else {
        addStreamMsg({ type: 'tool', content: line.replace(/🔧\s*/, '').replace(/\*\*/g, '') })
      }
    }
    // 工具结果成功: > ✅ ...
    else if (line.startsWith('> ✅')) {
      flushThinking()
      addStreamMsg({ type: 'status', content: '✅ ' + line.replace(/^>\s*✅\s*/, '') })
    }
    // 工具结果失败: > ❌ ...
    else if (line.startsWith('> ❌')) {
      flushThinking()
      addStreamMsg({ type: 'error', content: line.replace(/^>\s*❌\s*/, '') })
    }
    // Agent 完成: ✨ **Agent 完成** (N 轮对话)
    else if (line.includes('✨') && line.includes('Agent 完成')) {
      flushThinking()
      addStreamMsg({ type: 'status', content: '✅ 代码生成完成' })
    }
    // Agent 错误: ❌ **Agent 错误**: ...
    else if (line.startsWith('❌ **Agent')) {
      flushThinking()
      addStreamMsg({ type: 'error', content: line.replace(/❌\s*\*\*Agent 错误\*\*:\s*/, '') })
    }
    // 分隔线
    else if (line.trim() === '---') {
      flushThinking()
    }
    // 普通文本 → 思考内容
    else {
      thinkingBuf += line + '\n'
    }
  }
  flushThinking()
}

function startNewWorkspace() {
  codingStore.reset()
  persistedCodingModelValue.value = null
  selectedCodingModelValue.value = normalizeCodingModelValue(selectedCodingModelValue.value)
  ideUrl.value = null
  ideLoaded.value = false
  streamMessages.value = []
  activeView.value = 'chat'
  localStorage.removeItem('coding_last_workspace_id')
}

async function deleteWorkspace(ws: WorkspaceInfo) {
  try {
    await codingApi.deleteWorkspace(ws.id)
    allWorkspaces.value = allWorkspaces.value.filter(w => w.id !== ws.id)
    if (codingStore.workspace?.id === ws.id) {
      codingStore.reset()
      ideUrl.value = null
      localStorage.removeItem('coding_last_workspace_id')
    }
    ElMessage.success('\u5DF2\u5220\u9664')
  } catch (e: any) {
    ElMessage.error(e.message || '\u5220\u9664\u5931\u8D25')
  }
}

async function deleteCurrentWorkspace() {
  if (!codingStore.workspace) return
  await deleteWorkspace(codingStore.workspace)
}

// ============ Attachment Handling ============

function handlePaste(event: ClipboardEvent) {
  const items = event.clipboardData?.items
  if (!items) return
  for (const item of items) {
    if (item.type.startsWith('image/')) {
      event.preventDefault()
      const file = item.getAsFile()
      if (file) setAttachment(file)
      return
    }
  }
}

function handleFileSelect(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) setAttachment(file)
  input.value = ''
}

function setAttachment(file: File) {
  attachedFile.value = file
  if (file.type.startsWith('image/')) {
    attachedPreviewUrl.value = URL.createObjectURL(file)
  } else {
    attachedPreviewUrl.value = null
  }
}

function removeAttachment() {
  if (attachedPreviewUrl.value) {
    URL.revokeObjectURL(attachedPreviewUrl.value)
  }
  attachedFile.value = null
  attachedPreviewUrl.value = null
}

// ============ Send Message / Create Workspace ============

function sendSuggestion(text: string) {
  userInput.value = text
  pendingSceneCategory.value = activeSceneCategory.value
  sendMessage()
}

async function sendMessage() {
  const message = userInput.value.trim()
  if (!message && !attachedFile.value) return
  if (isCreating.value) return

  userInput.value = ''
  const currentAttachment = attachedFile.value
  const currentPreviewUrl = attachedPreviewUrl.value
  attachedFile.value = null
  attachedPreviewUrl.value = null

  isCreating.value = true
  isStreaming.value = true
  activeView.value = 'chat'
  // 保留历史消息，多轮之间加分隔
  if (streamMessages.value.length > 0) {
    addStreamMsg({ type: 'status', content: '───' })
  }
  addStreamMsg({ type: 'user', content: message })
  addStreamMsg({ type: 'status', content: codingStore.workspace ? '正在处理...' : '正在识别开发场景...' })

  try {
  // Upload attachment if present
  let uploadResult: UploadResult | null = null
  if (currentAttachment) {
    try {
      isUploading.value = true
      uploadResult = await codingApi.uploadFile(currentAttachment, codingStore.workspace?.id)
    } catch (e: any) {
      ElMessage.error(`\u9644\u4EF6\u4E0A\u4F20\u5931\u8D25: ${e.message}`)
    } finally {
      isUploading.value = false
      if (currentPreviewUrl) URL.revokeObjectURL(currentPreviewUrl)
    }
  }

  // Build final message with attachment context
  let finalMessage = message
  if (uploadResult) {
    if (uploadResult.content) {
      finalMessage = `[\u9644\u4EF6\u6587\u6863: ${uploadResult.filename}]\n\`\`\`\n${uploadResult.content}\n\`\`\`\n\n${message}`
    } else {
      finalMessage = `${message}\n\n[\u9644\u4EF6\u56FE\u7247: ${uploadResult.filename}, \u5DF2\u4FDD\u5B58\u81F3: ${uploadResult.file_path}]`
    }
  }

  const _sceneKey = pendingSceneCategory.value || activeSceneCategory.value
  const _projectType = sceneCategoryToProjectType[_sceneKey] || route.query.type as string || null
  pendingSceneCategory.value = null

    const token = userStore.token

  const body: Record<string, any> = {
      message: finalMessage,
      workspace_id: codingStore.workspace?.id || null,
      conversation_id: codingStore.conversationId || null,
      selected_model: selectedCodingModelValue.value || null,
      app_id: (route.query.app_id as string) || null,
      project_id: embeddedAppId.value ? Number(embeddedAppId.value) : null,
      project_type: _projectType,
      quick_create: false,
    }

    const response = await fetch(harnessApi.codingPipelineUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify(body),
    })

    if (!response.ok) {
      const errBody = await response.json().catch(() => ({ detail: `HTTP ${response.status}` }))
      throw new Error(errBody.detail || `HTTP ${response.status}`)
    }

    await consumeSseResponse(response, async ({ data }) => {
      const payload = data.trim()
      if (!payload || payload === '[DONE]') return

      try {
        const parsed = JSON.parse(payload)

        if (parsed.type === 'step') {
          const stepKey = parsed.step as string
          const stepStatus = parsed.status as string
          if (stepKey === 'detect_scene' && stepStatus === 'done') {
            addStreamMsg({ type: 'status', content: `\u2713 \u8BC6\u522B\u4E3A ${parsed.data?.scene_type || 'component'}` })
          } else if (stepKey === 'create_workspace') {
            if (stepStatus === 'running') {
              addStreamMsg({ type: 'status', content: '\u6B63\u5728\u521D\u59CB\u5316\u5DE5\u7A0B\u811A\u624B\u67B6...' })
            } else if (stepStatus === 'done' && parsed.data) {
              addStreamMsg({ type: 'status', content: '\u2713 \u5DE5\u7A0B\u811A\u624B\u67B6\u5DF2\u521D\u59CB\u5316' })
              const wsData = { ...parsed.data, id: parsed.data.workspace_id || parsed.data.id }
              codingStore.setWorkspace(wsData)
              codingStore.workspacePath = parsed.data.workspace_path || null
              localStorage.setItem('coding_last_workspace_id', wsData.id)
              try { allWorkspaces.value = await codingApi.listWorkspaces() } catch {}
            }
          } else if (stepKey === 'generate') {
            if (stepStatus === 'running') {
              addStreamMsg({ type: 'status', content: 'AI \u5F00\u59CB\u7F16\u5199\u4EE3\u7801...' })
            } else if (stepStatus === 'done') {
              addStreamMsg({ type: 'status', content: '\u2713 \u4EE3\u7801\u751F\u6210\u5B8C\u6210' })
            }
          }
        } else if (parsed.type === 'content') {
          // content 事件：如果最后一条 thinking 已经包含了相同内容（agent_thinking_delta 先到），跳过
          const text = (parsed.content || '') as string
          if (text.trim()) {
            const last = streamMessages.value[streamMessages.value.length - 1]
            if (!(last?.type === 'thinking' && last.content.includes(text.slice(0, 50)))) {
              addStreamMsg({ type: 'thinking', content: text })
            }
          }
        } else if (parsed.type === 'agent_tool') {
          const toolName = parsed.tool as string
          const toolArgs = parsed.args || {}
          const preview = (parsed.input_preview || '') as string
          if (toolName === 'write_file') {
            const filePath = (toolArgs.file_path || '') as string
            const fileName = filePath.split('/').pop() || preview
            const content = (toolArgs.content || '') as string
            addStreamMsg({
              type: 'file_write', content: '', fileName,
              fileContent: content || undefined, collapsed: true,
            })
          } else if (toolName === 'edit_file') {
            const filePath = (toolArgs.file_path || '') as string
            const fileName = filePath.split('/').pop() || preview
            const newStr = (toolArgs.new_string || '') as string
            addStreamMsg({
              type: 'file_edit', content: '', fileName,
              fileContent: newStr || undefined, collapsed: true,
            })
          } else if (toolName === 'run_command') {
            const cmd = (toolArgs.command || preview || '') as string
            addStreamMsg({ type: 'command', content: cmd })
          } else if (toolName === 'read_file') {
            addStreamMsg({ type: 'tool', content: `\uD83D\uDCC4 \u8BFB\u53D6 ${preview}` })
          } else if (toolName === 'glob_files') {
            addStreamMsg({ type: 'tool', content: `\uD83D\uDCC2 \u626B\u63CF ${preview || '\u9879\u76EE\u6587\u4EF6'}` })
          } else if (toolName === 'grep_search') {
            addStreamMsg({ type: 'tool', content: `\uD83D\uDD0D \u641C\u7D22 ${preview}` })
          }
        } else if (parsed.type === 'agent_command_output') {
          const chunk = (parsed.chunk || '') as string
          if (chunk) appendToLastCommand(chunk)
        } else if (parsed.type === 'agent_thinking') {
          // agent_thinking 是完整思考块，但 agent_thinking_delta 已经流式展示了同样内容
          // 只在没有活跃的 thinking 消息时才新增（避免重复）
          const text = (parsed.content || '') as string
          if (text.trim()) {
            const last = streamMessages.value[streamMessages.value.length - 1]
            if (!(last?.type === 'thinking' && last.content.includes(text.slice(0, 50)))) {
              addStreamMsg({ type: 'thinking', content: text })
            }
          }
        } else if (parsed.type === 'agent_thinking_delta') {
          const delta = (parsed.content || '') as string
          if (delta) appendToLastThinking(delta)
        } else if (parsed.type === 'agent_done') {
          addStreamMsg({ type: 'status', content: '\u2705 \u4EE3\u7801\u751F\u6210\u5B8C\u6210' })
        } else if (parsed.type === 'scene_detected') {
          codingStore.conversationId = parsed.conversation_id
        } else if (parsed.type === 'done') {
          isStreaming.value = false
          codingStore.conversationId = parsed.conversation_id
          if (parsed.conversation_id) {
            persistedCodingModelValue.value = normalizeCodingModelValue(selectedCodingModelValue.value)
          }
          if (parsed.workspace_id && !codingStore.workspace) {
            try {
              const ws = await codingApi.getWorkspace(parsed.workspace_id)
              codingStore.setWorkspace(ws)
              localStorage.setItem('coding_last_workspace_id', ws.id)
            } catch { /* ignore */ }
          }
          if (parsed.ide_url) {
            // 不自动跳转，保存 URL 让用户手动选择进入 IDE
            pendingIdeUrl.value = parsed.ide_url
            // 后台预加载 iframe（不切换视图）
            setIdeUrl(parsed.ide_url)
          }
        } else if (parsed.type === 'error') {
          addStreamMsg({ type: 'error', content: parsed.message || '\u53D1\u751F\u9519\u8BEF' })
          isStreaming.value = false
        }
      } catch {
        // skip unparseable events
      }
    }, { yieldEvery: 6 })

    // If we got a workspace but no IDE URL from SSE, fetch it and preload (don't auto-switch)
    if (!ideUrl.value && codingStore.workspace) {
      try {
        const { ide_url } = await codingApi.getIdeUrl(codingStore.workspace.id, codingStore.conversationId)
        pendingIdeUrl.value = ide_url
        await setIdeUrl(ide_url)
      } catch (err: any) {
        ElMessage.warning(err?.message || 'IDE URL 获取失败')
      }
    }

    // Refresh workspace list
    if (codingStore.workspace) {
      try { allWorkspaces.value = await codingApi.listWorkspaces() } catch {}
    }

  } catch (error: any) {
    addStreamMsg({ type: 'error', content: error.message || '\u53D1\u751F\u9519\u8BEF' })
    isStreaming.value = false
  } finally {
    isCreating.value = false
  }
}

// ============ Header Actions ============

async function loadPlatformEnvs() {
  try {
    platformEnvs.value = await platformEnvApi.list()
  } catch { /* ignore */ }
}

async function openBrowserPreviewWithEnv(env: PlatformEnv) {
  if (!codingStore.workspace) return
  showEnvPicker.value = false
  try {
    const { ide_url } = await codingApi.getIdeUrl(codingStore.workspace.id, codingStore.conversationId)
    const urlParams = new URLSearchParams(new URL(ide_url).search)
    const token = urlParams.get('vibe_ide_token') || ''
    const wsId = codingStore.workspace.id
    const platformBase = env.base_url.replace(/\/backend\/?$/, '')
    const loginUrl = platformBase
    const previewUrl = `${API_PREFIX.replace('/api', '')}/api/static/browser-preview.html?ws_id=${wsId}&token=${token}&initial_url=${encodeURIComponent(loginUrl)}`
    window.open(previewUrl, '_blank', 'noopener,noreferrer')
  } catch (err: any) {
    ElMessage.warning(err?.response?.data?.detail || err?.message || '\u6D4F\u89C8\u5668\u9884\u89C8\u6253\u5F00\u5931\u8D25')
  }
}

async function downloadCode() {
  if (!codingStore.workspace || isDownloading.value) return
  isDownloading.value = true
  try {
    await codingApi.downloadZip(codingStore.workspace.id, 'src')
    ElMessage.success('\u4EE3\u7801\u4E0B\u8F7D\u5DF2\u5F00\u59CB')
  } catch (error: any) {
    ElMessage.error(error.message || '\u4E0B\u8F7D\u5931\u8D25')
  } finally {
    isDownloading.value = false
  }
}

// ============ Watchers ============

watch(() => route.path, () => {
  if (!route.path.startsWith('/coding')) {
    codingStore.reset()
    ideUrl.value = null
  }
})
</script>

<style scoped>
/* ============================================================
   CodingPage — Project Launcher + Embedded IDE
   ============================================================ */

.coding-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  position: relative;
  background: var(--t-bg-base);
  color: var(--t-text-primary);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
}

/* ============ Header ============ */
.coding-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 22px;
  border-bottom: 1px solid var(--t-border-subtle);
  background: var(--t-bg-nav);
  backdrop-filter: blur(18px);
  min-height: 48px;
  flex-shrink: 0;
  box-shadow: var(--t-shadow-sm);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-title {
  font-size: 16px;
  font-weight: 700;
  background: var(--t-brand-gradient);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  margin: 0;
  letter-spacing: -0.01em;
}

.header-ws-tag {
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.header-btn {
  border-color: var(--t-border-subtle);
  background: var(--t-bg-elevated);
  color: var(--t-text-secondary);
  border-radius: 10px;
  font-size: 13px;
  transition: all 0.2s ease;
}

.header-btn:hover {
  border-color: var(--t-brand-glow);
  background: var(--t-brand-subtle);
  color: var(--t-text-primary);
}

/* ============ View Toggle (Chat / IDE) ============ */
.view-toggle {
  display: flex;
  align-items: center;
  background: var(--t-bg-elevated);
  border: 1px solid var(--t-border-subtle);
  border-radius: 8px;
  padding: 2px;
  gap: 0;
}
.view-toggle-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--t-text-tertiary);
  cursor: pointer;
  font-size: 12px;
  transition: all 0.2s ease;
}
.view-toggle-btn:hover:not(.disabled) {
  color: var(--t-text-secondary);
  background: var(--t-bg-subtle);
}
.view-toggle-btn.active {
  background: var(--t-brand-subtle);
  color: var(--t-brand-primary, #646cff);
  font-weight: 500;
}
.view-toggle-btn.disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.view-toggle-label {
  line-height: 1;
}

/* ============ Embedded Toolbar (嵌入模式浮动工具栏) ============ */
.embedded-toolbar {
  position: absolute;
  top: 8px;
  right: 12px;
  z-index: 100;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 10px;
  background: var(--t-bg-nav);
  border: 1px solid var(--t-border-subtle);
  border-radius: 10px;
  backdrop-filter: blur(12px);
  box-shadow: var(--t-shadow-sm);
}
.embedded-ws-tag {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ============ Body Layout ============ */
.coding-body {
  display: flex;
  flex: 1;
  overflow: hidden;
  min-height: 0;
}

/* ============ Workspace Sidebar ============ */
.workspace-sidebar {
  width: 240px;
  flex-shrink: 0;
  border-right: 1px solid var(--t-border-subtle);
  transition: width 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  background: var(--t-bg-panel);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Collapsed sidebar */
.workspace-sidebar.collapsed {
  width: 48px;
}
.sidebar-collapsed-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 8px 0;
  gap: 4px;
}
.sidebar-collapsed-divider {
  width: 24px;
  height: 1px;
  background: var(--t-border-subtle);
  margin: 4px 0;
}
.sidebar-icon-btn {
  width: 32px;
  height: 32px;
  border: none;
  border-radius: var(--t-radius-sm);
  background: transparent;
  color: var(--t-text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s ease;
}
.sidebar-icon-btn:hover {
  background: var(--t-brand-subtle);
  color: var(--t-brand);
}
.sidebar-icon-ws {
  width: 32px;
  height: 32px;
  border: 1px solid var(--t-border-subtle);
  border-radius: var(--t-radius-sm);
  background: var(--t-bg-panel);
  color: var(--t-text-secondary);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s ease;
}
.sidebar-icon-ws:hover {
  border-color: var(--t-brand-light);
  color: var(--t-brand);
  background: var(--t-brand-subtle);
}
.sidebar-icon-ws.active {
  border-color: var(--t-brand);
  color: var(--t-brand);
  background: var(--t-brand-subtle);
  box-shadow: 0 0 0 1px var(--t-brand-glow);
}
.sidebar-toggle-btn {
  width: 32px;
  height: 32px;
  border: none;
  border-radius: var(--t-radius-sm);
  background: transparent;
  color: var(--t-text-muted);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s ease;
}
.sidebar-toggle-btn:hover {
  background: var(--t-bg-panel-hover);
  color: var(--t-text-primary);
}

.sidebar-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px 6px;
}
.sidebar-header-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}
.sidebar-action-btn {
  width: 28px;
  height: 28px;
  border: 1px solid var(--t-border-subtle);
  border-radius: 6px;
  background: var(--t-bg-panel);
  color: var(--t-text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s ease;
}
.sidebar-action-btn:hover {
  background: var(--t-bg-panel-hover);
  color: var(--t-text-primary);
  border-color: var(--t-border-strong);
}
.sidebar-add-btn {
  color: var(--t-brand);
  border-color: var(--t-brand-glow);
}
.sidebar-add-btn:hover {
  background: var(--t-brand-subtle);
  color: var(--t-brand-dark);
  border-color: var(--t-brand);
}

.sidebar-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--t-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.sidebar-list {
  flex: 1;
  overflow-y: auto;
  padding: 10px 12px 16px;
}

.sidebar-group-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 10px 7px;
  cursor: pointer;
  user-select: none;
  margin-top: 8px;
  border-radius: 12px;
  transition: background 0.2s ease;
}

.sidebar-group-header:hover {
  background: var(--t-bg-subtle);
}

.sidebar-group-header:first-child {
  margin-top: 0;
}

.sidebar-group-icon {
  font-size: 13px;
}

.sidebar-group-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--t-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.03em;
  flex: 1;
}

.sidebar-group-count {
  font-size: 10px;
  color: var(--t-text-muted);
  background: var(--t-bg-subtle);
  padding: 2px 7px;
  border-radius: 999px;
  min-width: 18px;
  text-align: center;
}

.sidebar-group-arrow {
  color: var(--t-text-muted);
  transition: transform 0.2s ease;
  transform: rotate(90deg);
  display: flex;
  align-items: center;
}

.sidebar-group-arrow.collapsed {
  transform: rotate(0deg);
}

.sidebar-ws-item {
  padding: 10px 12px 8px;
  border-radius: var(--t-radius-sm);
  cursor: pointer;
  position: relative;
  margin-bottom: 6px;
  border: 1px solid transparent;
  background: transparent;
  transition: all 0.22s ease;
}

.sidebar-ws-item:hover {
  background: var(--t-bg-panel-hover);
  border-color: var(--t-border-strong);
}

.sidebar-ws-item.active {
  background: var(--t-brand-subtle);
  border-color: var(--t-brand-glow);
  box-shadow: inset 3px 0 0 var(--t-brand);
}

.sidebar-ws-name {
  font-size: 13px;
  color: var(--t-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 4px;
  font-weight: 600;
  line-height: 1.4;
}

.sidebar-ws-code {
  font-size: 11px;
  line-height: 1.3;
  color: var(--t-text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.sidebar-ws-del {
  position: absolute;
  top: 6px;
  right: 6px;
  width: 20px;
  height: 20px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--t-text-muted);
  font-size: 14px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: all 0.15s ease;
}
.sidebar-ws-del:hover {
  background: var(--t-danger-subtle);
  color: var(--t-danger);
}
.sidebar-ws-item:hover .sidebar-ws-del {
  opacity: 1;
}

.sidebar-empty {
  text-align: center;
  color: var(--t-text-muted);
  font-size: 12px;
  padding: 24px 0;
}

/* ============ Main Content ============ */
.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
}

/* ============ Welcome Pane ============ */
.welcome-pane {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow-y: auto;
  background: radial-gradient(circle at top, var(--t-brand-subtle), transparent 40%);
}

.welcome-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  max-width: 700px;
  width: 100%;
  padding: 40px 24px;
  position: relative;
}

.welcome-icon {
  font-size: 48px;
  margin-bottom: 16px;
  filter: drop-shadow(0 0 24px var(--t-brand-glow));
}

.welcome-title {
  font-size: 32px;
  font-weight: 800;
  margin: 0 0 12px;
  background: var(--t-brand-gradient);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  letter-spacing: -0.02em;
}

.welcome-desc {
  color: var(--t-text-secondary);
  font-size: 15px;
  margin: 0 0 28px;
  line-height: 1.7;
  max-width: 460px;
}

/* ============ Welcome Input Area ============ */
.welcome-input-area {
  width: 100%;
  margin-bottom: 28px;
}

.coding-model-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
  padding: 12px 14px;
  border: 1px solid var(--t-border-subtle);
  border-radius: 14px;
  background: var(--t-bg-elevated);
  box-shadow: var(--t-shadow-sm);
}

.coding-model-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.coding-model-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--t-text-primary);
}

.coding-model-tip {
  font-size: 11px;
  color: var(--t-text-muted);
}

.coding-model-select {
  width: min(460px, 60%);
  flex-shrink: 0;
}

.coding-model-select :deep(.el-select__wrapper) {
  min-height: 40px;
  border-radius: 12px;
  background: linear-gradient(180deg, var(--t-bg-panel), var(--t-bg-base));
  box-shadow: inset 0 0 0 1px var(--t-border-subtle), 0 8px 20px rgba(15, 23, 42, 0.04);
}
.coding-model-select :deep(.el-select__selected-item),
.coding-model-select :deep(.el-select__placeholder) {
  color: var(--t-text-primary);
}
.coding-model-select :deep(.el-select__caret),
.coding-model-select :deep(.el-select__suffix) {
  color: var(--t-text-muted);
}
.coding-model-select :deep(.el-select__wrapper.is-focused) {
  box-shadow: inset 0 0 0 1px var(--t-brand-glow), 0 0 0 4px rgba(99, 102, 241, 0.08);
}

.coding-model-option-row {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  width: 100%;
}

.coding-model-option-top {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.coding-model-option-name {
  color: var(--t-text-primary);
  font-size: 15px;
  font-weight: 600;
  line-height: 1.2;
}

.coding-model-option-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.coding-model-option-provider,
.coding-model-option-default {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.01em;
}

.coding-model-option-provider {
  background: var(--t-bg-subtle);
  color: var(--t-text-secondary);
  border: 1px solid var(--t-border-subtle);
}

.coding-model-option-default {
  background: rgba(99, 102, 241, 0.12);
  color: var(--t-brand-dark);
  border: 1px solid rgba(99, 102, 241, 0.14);
}

.coding-model-option-meta {
  font-size: 12px;
  color: var(--t-text-secondary);
  line-height: 1.35;
}

.input-wrapper {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  width: 100%;
  background: var(--t-bg-input);
  border: 1px solid var(--t-border-subtle);
  border-radius: 22px;
  padding: 12px 14px;
  transition: all 0.3s ease;
  box-shadow: var(--t-shadow-md);
}

.input-wrapper:focus-within {
  border-color: transparent;
  background: linear-gradient(var(--t-bg-elevated), var(--t-bg-elevated)) padding-box,
              var(--t-brand-gradient) border-box;
  border: 1px solid transparent;
  box-shadow: 0 0 16px var(--t-brand-subtle);
}

.input-wrapper :deep(.el-textarea__inner) {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
  color: var(--t-text-primary);
  font-size: 14px;
  line-height: 1.55;
  padding: 4px 0;
  resize: none;
}

.send-btn {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  background: var(--t-brand-gradient) !important;
  border: none !important;
  transition: all 0.2s ease;
}

.send-btn:hover:not(:disabled) {
  transform: scale(1.05);
  box-shadow: 0 2px 10px var(--t-brand-glow);
}

.send-btn:disabled {
  opacity: 0.4;
  background: var(--t-border-subtle) !important;
}

.attach-btn {
  flex-shrink: 0;
  color: var(--t-text-muted);
  padding: 4px;
  transition: color 0.2s ease;
}

.attach-btn:hover {
  color: var(--t-text-primary);
}

.input-hint {
  font-size: 11px;
  color: var(--t-text-muted);
  margin-top: 8px;
  letter-spacing: 0.01em;
}

@media (max-width: 920px) {
  .coding-model-bar {
    flex-direction: column;
    align-items: stretch;
  }

  .coding-model-select {
    width: 100%;
  }
}

/* ============ Attachment Preview ============ */
.attachment-preview {
  width: 100%;
  margin-bottom: 10px;
  padding: 10px 14px;
  background: var(--t-bg-elevated);
  border: 1px solid var(--t-border-subtle);
  border-radius: 14px;
  display: flex;
  align-items: center;
  gap: 10px;
}

.attachment-thumb {
  position: relative;
  display: inline-block;
}

.attachment-thumb img {
  width: 60px;
  height: 60px;
  object-fit: cover;
  border-radius: 10px;
  border: 1px solid var(--t-border-subtle);
}

.attachment-file {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--t-text-secondary);
  font-size: 13px;
}

.attachment-file-icon {
  font-size: 18px;
}

.attachment-file-name {
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.attachment-remove {
  background: var(--t-border-subtle);
  border: none;
  color: var(--t-text-secondary);
  cursor: pointer;
  font-size: 16px;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
  transition: all 0.2s ease;
}

.attachment-remove:hover {
  background: var(--t-danger-subtle);
  color: var(--t-danger);
}

.attachment-thumb .attachment-remove {
  position: absolute;
  top: -6px;
  right: -6px;
}

/* ============ Scene Tabs ============ */
.scene-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  margin-bottom: 20px;
}

.scene-tab {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 7px 14px;
  border-radius: 20px;
  border: 1px solid var(--t-border-subtle);
  background: transparent;
  color: var(--t-text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.scene-tab:hover {
  border-color: var(--t-brand-glow);
  color: var(--t-text-primary);
}

.scene-tab.active {
  border-color: var(--t-brand);
  background: var(--t-brand-subtle);
  color: var(--t-brand-light);
}

.scene-tab-icon {
  font-size: 14px;
}

/* ============ Suggestion Cards ============ */
.suggestions-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  width: 100%;
}

.suggestion-card {
  padding: 16px 18px;
  border-radius: 14px;
  border: 1px solid var(--t-border-subtle);
  background: var(--t-bg-elevated);
  color: var(--t-text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.25s ease;
  line-height: 1.5;
  text-align: left;
}

.suggestion-card:hover {
  border-color: var(--t-brand-glow);
  background: var(--t-brand-subtle);
  color: var(--t-text-primary);
  transform: translateY(-2px);
  box-shadow: 0 8px 20px var(--t-brand-glow);
}

/* ============ Stream Pane (对话流视图) ============ */
.stream-pane {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.stream-messages {
  flex: 1;
  overflow-y: auto;
  padding: 24px 40px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.stream-msg { animation: fadeInUp 0.2s ease-out; }

@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

/* 用户消息 */
.msg-user-bubble {
  align-self: flex-end;
  max-width: 80%;
  padding: 10px 16px;
  background: var(--t-brand);
  color: #fff;
  border-radius: 16px 16px 4px 16px;
  font-size: 14px;
  line-height: 1.5;
  margin-bottom: 8px;
}

/* AI 思考 */
.msg-thinking {
  font-size: 14px;
  color: var(--t-text);
  line-height: 1.6;
  padding: 4px 0;
  white-space: pre-wrap;
  word-break: break-word;
}

.thinking-cursor {
  animation: blink 1s step-end infinite;
  color: var(--t-brand);
}

@keyframes blink {
  50% { opacity: 0; }
}

/* 状态消息 */
.msg-status {
  font-size: 12px;
  color: var(--t-text-muted);
  padding: 4px 0;
}

/* 工具调用 */
.msg-tool {
  font-size: 12px;
  color: var(--t-text-muted);
  opacity: 0.7;
  padding: 2px 0;
}

/* 文件写入/编辑 */
.msg-file-write, .msg-file-edit {
  border: 1px solid var(--t-border-subtle);
  border-radius: 8px;
  overflow: hidden;
  margin: 4px 0;
}

.file-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  font-size: 13px;
  font-family: 'SF Mono', 'Monaco', 'Menlo', 'Consolas', monospace;
  transition: background 0.15s;
}

.file-header:hover {
  background: rgba(255, 255, 255, 0.04);
}

.file-icon {
  font-weight: 700;
  color: #52c41a;
  width: 16px;
  text-align: center;
}

.msg-file-edit .file-icon {
  color: #faad14;
}

.file-name {
  flex: 1;
  color: var(--t-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-badge {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 3px;
  background: rgba(82, 196, 26, 0.15);
  color: #52c41a;
}

.file-badge.edit-badge {
  background: rgba(250, 173, 20, 0.15);
  color: #faad14;
}

.file-toggle {
  font-size: 10px;
  color: var(--t-text-muted);
  opacity: 0.5;
}

.file-code-block {
  border-top: 1px solid var(--t-border-subtle);
  max-height: 300px;
  overflow: auto;
  background: rgba(0, 0, 0, 0.2);
}

.file-code-block pre {
  margin: 0;
  padding: 12px;
  font-size: 12px;
  line-height: 1.5;
  font-family: 'SF Mono', 'Monaco', 'Menlo', 'Consolas', monospace;
  color: var(--t-text);
  white-space: pre;
  overflow-x: auto;
}

/* 命令执行 */
.msg-command {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  font-size: 12px;
  font-family: 'SF Mono', 'Monaco', 'Menlo', 'Consolas', monospace;
  color: var(--t-text-muted);
  background: rgba(0, 0, 0, 0.15);
  border-radius: 6px;
  margin: 4px 0;
}

.cmd-icon {
  color: #52c41a;
  font-weight: 700;
}

.cmd-text {
  white-space: pre-wrap;
  word-break: break-word;
}

/* 错误 */
.msg-error {
  padding: 8px 12px;
  background: rgba(255, 77, 79, 0.1);
  border: 1px solid rgba(255, 77, 79, 0.3);
  border-radius: 6px;
  color: #ff4d4f;
  font-size: 13px;
}

/* 流式加载指示器 */
.stream-loading {
  display: flex;
  gap: 4px;
  padding: 8px 0;
}

.stream-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--t-brand);
  animation: dotPulse 1.4s infinite ease-in-out both;
}

.stream-dot:nth-child(1) { animation-delay: -0.32s; }
.stream-dot:nth-child(2) { animation-delay: -0.16s; }

@keyframes dotPulse {
  0%, 80%, 100% { transform: scale(0.4); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}

/* 完成后操作区域 */
.stream-actions {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 24px 0 16px;
  border-top: 1px solid var(--t-border-subtle);
  margin-top: 16px;
}

.open-ide-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 28px;
  background: var(--t-brand);
  color: #fff;
  border: none;
  border-radius: 10px;
  font-size: 15px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.open-ide-btn:hover {
  filter: brightness(1.1);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(124, 92, 252, 0.3);
}

.ide-btn-icon {
  font-size: 18px;
}

.stream-actions-hint {
  font-size: 12px;
  color: var(--t-text-muted);
  opacity: 0.6;
}

.creating-text {
  color: var(--t-text-secondary);
  font-size: 14px;
  margin: 0;
}

/* ============ Chat Input Bar (stream-pane 底部) ============ */
.chat-input-bar {
  flex-shrink: 0;
  padding: 12px 24px 16px;
  border-top: 1px solid var(--t-border-subtle);
  background: var(--t-bg-base);
}
.chat-input-wrapper {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  max-width: 800px;
  margin: 0 auto;
  background: var(--t-bg-elevated);
  border: 1px solid var(--t-border-subtle);
  border-radius: 12px;
  padding: 6px 8px;
  transition: border-color 0.2s;
}
.chat-input-wrapper:focus-within {
  border-color: var(--t-brand-primary, #646cff);
}
.chat-input-wrapper .attach-btn {
  flex-shrink: 0;
  color: var(--t-text-tertiary);
}
.chat-input-wrapper .chat-input {
  flex: 1;
}
.chat-input-wrapper .chat-input :deep(.el-textarea__inner) {
  background: transparent;
  border: none;
  box-shadow: none;
  padding: 4px 0;
  font-size: 14px;
  color: var(--t-text-primary);
  resize: none;
}
.chat-input-wrapper .send-btn {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
}

/* ============ IDE Pane ============ */
.ide-pane {
  flex: 1;
  overflow: hidden;
  position: relative;
}
.ide-loading-overlay {
  position: absolute;
  inset: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--t-bg-base);
  transition: opacity 0.3s ease;
}
.ide-loading-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  color: var(--t-text-secondary);
  font-size: 14px;
}
.ide-loading-spinner {
  width: 36px;
  height: 36px;
  border: 3px solid var(--t-border-subtle);
  border-top-color: var(--t-brand);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.ide-frame {
  width: 100%;
  height: 100%;
  border: none;
}

/* ============ Scrollbar ============ */
.sidebar-list::-webkit-scrollbar {
  width: 4px;
}

.sidebar-list::-webkit-scrollbar-track {
  background: transparent;
}

.sidebar-list::-webkit-scrollbar-thumb {
  background: var(--t-border-subtle);
  border-radius: 4px;
}

.welcome-pane::-webkit-scrollbar {
  width: 5px;
}

.welcome-pane::-webkit-scrollbar-track {
  background: transparent;
}

.welcome-pane::-webkit-scrollbar-thumb {
  background: var(--t-border-subtle);
  border-radius: 4px;
}

/* ============ Element Plus Dark Overrides ============ */
.coding-page :deep(.el-tag--info) {
  background: var(--t-brand-subtle);
  border-color: var(--t-brand-glow);
  color: var(--t-brand-light);
}

.coding-page :deep(.el-button--primary) {
  background: var(--t-brand-gradient);
  border: none;
  transition: all 0.2s ease;
}

.coding-page :deep(.el-button--primary:hover) {
  box-shadow: 0 2px 10px var(--t-brand-glow);
  filter: brightness(1.1);
}

.coding-page :deep(.el-button--success) {
  background: var(--t-success-subtle);
  border-color: var(--t-success);
  color: var(--t-success);
  transition: all 0.2s ease;
}

.coding-page :deep(.el-button--success:hover) {
  filter: brightness(1.15);
}
</style>
