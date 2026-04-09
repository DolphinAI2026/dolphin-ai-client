<template>
  <WorkbenchShell>
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
      <!-- Main Content: Welcome or IDE -->
      <div class="main-content">
        <!-- 非嵌入模式顶部工具栏：返回 + Chat/IDE 切换 -->
        <div
          v-if="!embeddedAppId && (ideUrl || streamMessages.length > 0)"
          class="content-view-toggle-bar"
        >
          <!-- 左：返回首页 -->
          <button class="toggle-bar-back-btn" @click="startNewWorkspace" title="返回首页">
            <el-icon :size="14"><ArrowLeft /></el-icon>
            <span>返回</span>
          </button>

          <!-- 中：Chat / IDE 切换 -->
          <div class="view-toggle">
            <button
              class="view-toggle-btn"
              :class="{ active: activeView === 'chat' }"
              @click="activeView = 'chat'"
            >
              <el-icon :size="13"><ChatDotRound /></el-icon>
              <span class="view-toggle-label">对话</span>
            </button>
            <button
              class="view-toggle-btn"
              :class="{ active: activeView === 'ide', disabled: !ideUrl }"
              :disabled="!ideUrl"
              @click="ideUrl && (activeView = 'ide')"
            >
              <el-icon :size="13"><Monitor /></el-icon>
              <span class="view-toggle-label">IDE</span>
            </button>
          </div>

          <!-- 右：占位，保持切换居中 -->
          <div class="toggle-bar-placeholder"></div>
        </div>

        <!-- Welcome State -->
        <div v-if="!ideUrl && !isStreaming && streamMessages.length === 0" class="welcome-pane">
          <div class="welcome-inner">
            <div class="welcome-hero">
              <div class="welcome-icon">&#x2728;</div>
              <h2 class="welcome-title">AI Coding</h2>
              <p class="welcome-desc">用AI快速开发</p>

              <!-- Input Area (centered) -->
              <div class="welcome-input-area">
                <div class="coding-model-bar">
                  <div class="coding-model-meta">
                    <span class="coding-model-label">当前模型</span>
                    <span v-if="codingModelOptions.length === 0" class="coding-model-tip">
                      未配置可用模型，<router-link to="/platform-envs" style="color:var(--t-brand);text-decoration:underline">前往环境管理配置</router-link>
                    </span>
                    <span v-else class="coding-model-tip">{{ codingModelHint }}</span>
                  </div>
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
                  <div class="composer-topline">
                    <div class="coding-model-inline">
                      <el-popover
                        v-model:visible="codingModelPopoverVisible"
                        placement="bottom-start"
                        trigger="click"
                        :width="360"
                        popper-class="coding-model-popover"
                        :disabled="codingModelLoading || updatingCodingModel || codingModelOptions.length === 0"
                      >
                        <template #reference>
                          <button
                            type="button"
                            class="coding-model-trigger"
                            :class="{ 'is-open': codingModelPopoverVisible, 'is-disabled': codingModelLoading || updatingCodingModel || codingModelOptions.length === 0 }"
                            :disabled="codingModelLoading || updatingCodingModel || codingModelOptions.length === 0"
                            aria-label="选择模型"
                          >
                            <div class="coding-model-trigger-content">
                              <div class="coding-model-trigger-main">
                                <span class="coding-model-trigger-name">{{ selectedCodingModelOption?.config_name || '选择模型' }}</span>
                              </div>
                              <el-icon class="coding-model-trigger-icon">
                                <ArrowDown />
                              </el-icon>
                            </div>
                          </button>
                        </template>
                        <div class="coding-model-panel">
                          <button
                            v-for="option in codingModelOptions"
                            :key="option.id"
                            type="button"
                            class="coding-model-panel-option"
                            :class="{ 'is-active': selectedCodingModelValue === toCodingModelValue(option.id) }"
                            @click="selectCodingModel(option)"
                          >
                            <div class="coding-model-panel-option-head">
                              <span class="coding-model-panel-option-name">{{ option.config_name }}</span>
                              <span v-if="option.is_default" class="coding-model-panel-option-default">默认</span>
                            </div>
                            <span class="coding-model-panel-option-meta">
                              {{ formatCodingModelProvider(option.provider) }} / {{ option.model }}
                            </span>
                          </button>
                        </div>
                      </el-popover>
                      <span class="coding-model-tip">{{ codingModelHint }}</span>
                    </div>
                  </div>
                  <div class="input-mainline">
                    <el-button
                      text
                      class="attach-btn"
                      @click="fileInputRef?.click()"
                      :disabled="isCreating"
                      title="上传附件"
                    >
                      <el-icon :size="18"><Paperclip /></el-icon>
                    </el-button>
                    <div class="composer-text-zone">
                      <el-input
                        v-model="userInput"
                        type="textarea"
                        :rows="1"
                        :autosize="{ minRows: 1, maxRows: 5 }"
                        placeholder="描述你想开发的内容，告诉我你想开发什么，我会自动创建项目并打开 AI 代码编辑器"
                        @keydown.ctrl.enter="sendMessage"
                        @keydown.meta.enter="sendMessage"
                        :disabled="isCreating"
                        resize="none"
                      />
                    </div>
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
                </div>
              </div>
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

            <div v-if="sceneSuggestions[activeSceneCategory]?.length" class="scene-suggestion-grid">
              <button
                v-for="suggestion in sceneSuggestions[activeSceneCategory]"
                :key="suggestion"
                class="scene-suggestion-card"
                @click="sendSuggestion(suggestion)"
              >
                {{ suggestion }}
              </button>
            </div>

            <div class="workspace-showcase">
              <div class="workspace-showcase-header">
                <div>
                  <h3 class="workspace-showcase-title">我的自开发文件</h3>
                </div>
                <button
                  v-if="existingWorkspaces.length > 0"
                  class="workspace-showcase-more"
                  @click="openWorkspaceCatalogPage"
                >
                  <span>查看全部</span>
                  <span aria-hidden="true">→</span>
                </button>
              </div>

              <div v-if="workspaceShowcaseItems.length > 0" class="workspace-cards-grid">
                <article
                  v-for="ws in workspaceShowcaseItems"
                  :key="ws.id"
                  class="workspace-card"
                  @click="openExistingWorkspace(ws)"
                >
                  <div class="workspace-card-head">
                    <div class="workspace-card-copy">
                      <div class="workspace-card-name">{{ workspaceDisplayName(ws) }}</div>
                      <div class="workspace-card-meta-row">
                        <span v-if="workspaceCodeName(ws)" class="workspace-card-code">{{ workspaceCodeName(ws) }}</span>
                      </div>
                    </div>
                    <span class="workspace-card-type">{{ workspaceTypeLabel(ws.project_type) }}</span>
                  </div>
                  <div class="workspace-card-footer">
                    <div class="workspace-card-meta">
                      <span>文件类型：{{ workspaceTypeLabel(ws.project_type) }}</span>
                      <span>包名：{{ workspaceCodeName(ws) || ws.project_name }}</span>
                    </div>
                    <div class="workspace-card-actions">
                      <button
                        class="workspace-card-action workspace-card-action-primary"
                        title="进入开发"
                        @click.stop="openExistingWorkspace(ws)"
                      >
                        <svg class="workspace-card-action-icon" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                          <path d="M5.25 3.5L11 8L5.25 12.5V3.5Z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" />
                        </svg>
                      </button>
                      <button
                        :class="['workspace-card-action', { 'is-loading': uploadingWsId === ws.id }]"
                        :title="uploadingWsId === ws.id ? '上传中...' : '上传组件包'"
                        :disabled="uploadingWsId === ws.id"
                        @click.stop="uploadWorkspaceCard(ws)"
                      >
                        <svg v-if="uploadingWsId !== ws.id" class="workspace-card-action-icon" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                          <path d="M8 10V4.25" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
                          <path d="M5.75 6.5L8 4.25L10.25 6.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
                          <path d="M4 10.25V11.25C4 11.9404 4.55964 12.5 5.25 12.5H10.75C11.4404 12.5 12 11.9404 12 11.25V10.25" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
                        </svg>
                        <svg v-else class="workspace-card-action-icon spin" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                          <circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="1.5" stroke-dasharray="28 10" stroke-linecap="round" />
                        </svg>
                      </button>
                      <button
                        class="workspace-card-action"
                        title="下载源码"
                        @click.stop="downloadWorkspaceArtifact(ws, 'src')"
                      >
                        <svg class="workspace-card-action-icon" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                          <path d="M8 4V9.75" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
                          <path d="M10.25 7.5L8 9.75L5.75 7.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
                          <path d="M4 10.25V11.25C4 11.9404 4.55964 12.5 5.25 12.5H10.75C11.4404 12.5 12 11.9404 12 11.25V10.25" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
                        </svg>
                      </button>
                    </div>
                  </div>
                </article>
              </div>

              <div v-else class="workspace-showcase-empty">
                暂无自开发文件，先描述一个需求，我们会自动创建项目。
              </div>
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

              <!-- AI 显式消息（brainstorm 提案等，始终展开，Markdown 渲染） -->
              <template v-else-if="msg.type === 'message'">
                <div class="msg-ai-message">
                  <div class="ai-message-body markdown-body" v-html="renderMarkdown(msg.content)"></div>
                </div>
              </template>

              <!-- AI 思考过程（可折叠） -->
              <template v-else-if="msg.type === 'thinking'">
                <div class="msg-thinking-card" :class="{ 'is-collapsed': msg.collapsed }">
                  <div class="thinking-card-header" @click="msg.collapsed = !msg.collapsed">
                    <svg class="thinking-card-icon" viewBox="0 0 16 16" fill="none">
                      <circle cx="8" cy="8" r="6.5" stroke="currentColor" stroke-width="1.2"/>
                      <path d="M8 5v3.5l2 1.5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>
                    </svg>
                    <span class="thinking-card-label">思考过程</span>
                    <span class="thinking-card-chars">{{ msg.content.length }} 字</span>
                    <svg class="thinking-card-chevron" :class="{ rotated: !msg.collapsed }" viewBox="0 0 16 16" fill="none">
                      <path d="M4 6l4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                  </div>
                  <div v-show="!msg.collapsed" class="thinking-card-body">
                    <span class="thinking-text markdown-body" v-html="renderMarkdown(msg.content)"></span>
                    <span v-if="idx === streamMessages.length - 1 && isStreaming" class="thinking-cursor">|</span>
                  </div>
                </div>
              </template>

              <!-- 状态消息 -->
              <template v-else-if="msg.type === 'status'">
                <div class="msg-status">
                  <span class="status-dot"></span>
                  {{ msg.content }}
                </div>
              </template>

              <!-- 文件写入 -->
              <template v-else-if="msg.type === 'file_write'">
                <div class="msg-file-card">
                  <div class="file-card-header" @click="msg.collapsed = !msg.collapsed">
                    <span class="file-card-op file-card-op--new">+</span>
                    <span class="file-card-name">{{ msg.fileName }}</span>
                    <span class="file-card-badge file-card-badge--new">新建</span>
                    <svg class="file-card-chevron" :class="{ rotated: !msg.collapsed }" viewBox="0 0 16 16" fill="none">
                      <path d="M4 6l4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                  </div>
                  <div v-if="!msg.collapsed && msg.fileContent" class="file-card-code">
                    <pre><code>{{ msg.fileContent }}</code></pre>
                  </div>
                </div>
              </template>

              <!-- 文件编辑 -->
              <template v-else-if="msg.type === 'file_edit'">
                <div class="msg-file-card">
                  <div class="file-card-header" @click="msg.collapsed = !msg.collapsed">
                    <span class="file-card-op file-card-op--edit">~</span>
                    <span class="file-card-name">{{ msg.fileName }}</span>
                    <span class="file-card-badge file-card-badge--edit">修改</span>
                    <svg class="file-card-chevron" :class="{ rotated: !msg.collapsed }" viewBox="0 0 16 16" fill="none">
                      <path d="M4 6l4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                  </div>
                  <div v-if="!msg.collapsed && msg.fileContent" class="file-card-code">
                    <pre><code>{{ msg.fileContent }}</code></pre>
                  </div>
                </div>
              </template>

              <!-- 工具调用（读文件/扫描/搜索等） -->
              <template v-else-if="msg.type === 'tool'">
                <div class="msg-tool-row">
                  <span class="tool-row-text">{{ msg.content }}</span>
                </div>
              </template>

              <!-- 命令执行 -->
              <template v-else-if="msg.type === 'command'">
                <div class="msg-command-card">
                  <div class="command-card-header">
                    <span class="command-prompt">$</span>
                    <span class="command-text">{{ msg.content.split('\n')[0] }}</span>
                  </div>
                  <pre v-if="msg.content.includes('\n')" class="command-output">{{ msg.content.split('\n').slice(1).join('\n') }}</pre>
                </div>
              </template>

              <!-- 错误 -->
              <template v-else-if="msg.type === 'error'">
                <div class="msg-error-card">
                  <span class="error-icon">⚠</span>
                  {{ msg.content }}
                </div>
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
            @load="onIdeFrameLoad"
            @error="onIdeFrameError"
          ></iframe>
          <!-- Loading overlay — stays until iframe fires load event -->
          <div v-if="!ideLoaded" class="ide-loading-overlay">
            <div class="ide-loading-content">
              <template v-if="ideLoadError">
                <div class="ide-error-icon">⚠️</div>
                <span>{{ ideLoadError }}</span>
                <button class="ide-retry-btn" @click="retryIdeLoad">重新加载</button>
              </template>
              <template v-else>
                <div class="ide-loading-spinner"></div>
                <span>{{ ideLoadingText }}</span>
              </template>
            </div>
          </div>
        </div>
      </div>

      <!-- 嵌入模式：右侧可收起工具面板 -->
      <aside v-if="embeddedAppId" class="embedded-panel" :class="{ collapsed: embeddedPanelCollapsed }">
        <!-- 收起态：只显示展开按钮 -->
        <button class="embedded-panel-toggle" @click="embeddedPanelCollapsed = !embeddedPanelCollapsed" :title="embeddedPanelCollapsed ? '展开工具栏' : '收起工具栏'">
          <el-icon :size="14"><Expand v-if="embeddedPanelCollapsed" /><Fold v-else /></el-icon>
        </button>
        <!-- 展开态：工具按钮 -->
        <template v-if="!embeddedPanelCollapsed">
          <div v-if="ideUrl || streamMessages.length > 0" class="embedded-panel-group">
            <button
              class="embedded-panel-btn"
              :class="{ active: activeView === 'chat' }"
              @click="activeView = 'chat'"
              title="对话记录"
            >
              <el-icon :size="16"><ChatDotRound /></el-icon>
            </button>
            <button
              class="embedded-panel-btn"
              :class="{ active: activeView === 'ide', disabled: !ideUrl }"
              :disabled="!ideUrl"
              @click="ideUrl && (activeView = 'ide')"
              title="代码编辑器"
            >
              <el-icon :size="16"><Monitor /></el-icon>
            </button>
          </div>
          <div v-if="codingStore.workspace" class="embedded-panel-group">
            <button class="embedded-panel-btn" :disabled="isDownloading" @click="downloadCode" title="下载代码">
              <el-icon :size="16"><Download /></el-icon>
            </button>
            <button class="embedded-panel-btn danger" @click="deleteCurrentWorkspace" title="删除工作区">
              <el-icon :size="16"><Delete /></el-icon>
            </button>
          </div>
        </template>
      </aside>
    </div>
  </WorkbenchShell>

  <EnvSelectModal v-model="showUploadEnvModal" @selected="onUploadEnvSelected" />
</template>

<script setup lang="ts">
import { API_PREFIX } from '@/utils/request'
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowDown, ArrowLeft, Download, TopRight, Paperclip, Monitor, Delete, Fold, Expand, ChatDotRound } from '@element-plus/icons-vue'
import { useCodingStore } from '@/stores/coding'
import { platformEnvApi, type PlatformEnv } from '@/api/platformEnv'
import { useUserStore } from '@/stores/user'
import { codingApi } from '@/api/coding'
import type { WorkspaceInfo, UploadResult, ReplayStreamMessage } from '@/api/coding'
import { harnessApi } from '@/api/harness'
import { conversationApi } from '@/api/conversation'
import { llmConfigApi, type BuilderModelOption } from '@/api/llmConfig'
import { consumeSseResponse } from '@/utils/sse'
import { marked } from 'marked'
import ThemeToggle from '@/components/ThemeToggle.vue'
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import EnvSelectModal from '@/components/EnvSelectModal.vue'

const route = useRoute()
const router = useRouter()
const codingStore = useCodingStore()
const userStore = useUserStore()

// ============ Core State ============
const userInput = ref('')
const ideUrl = ref<string | null>(null)
const ideLoaded = ref(false)
const ideLoadError = ref('')
const ideLoadingText = ref('正在连接 IDE...')
let ideLoadTimer: ReturnType<typeof setTimeout> | null = null
const isCreating = ref(false)
const creatingStatus = ref('')
const codingModelOptions = ref<BuilderModelOption[]>([])
const codingModelLoading = ref(false)
const updatingCodingModel = ref(false)
const selectedCodingModelValue = ref<string | null>(null)
const persistedCodingModelValue = ref<string | null>(null)
const codingModelPopoverVisible = ref(false)

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

const selectedCodingModelOption = computed(() =>
  codingModelOptions.value.find(option => toCodingModelValue(option.id) === selectedCodingModelValue.value) ?? null
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

const codingModelSummary = computed(() => {
  if (codingModelLoading.value) return '正在加载可用模型...'
  if (!selectedCodingModelOption.value) return '请选择开发模型'
  return `${formatCodingModelProvider(selectedCodingModelOption.value.provider)} / ${selectedCodingModelOption.value.model}`
})

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

const selectCodingModel = async (option: BuilderModelOption) => {
  codingModelPopoverVisible.value = false
  const nextValue = toCodingModelValue(option.id)
  if (nextValue === selectedCodingModelValue.value) return
  await handleCodingModelChange(nextValue)
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

function renderMarkdown(content: string): string {
  if (!content) return ''
  try {
    return marked.parse(content) as string
  } catch {
    return content
  }
}

function addStreamMsg(msg: Omit<StreamMessage, 'timestamp'>) {
  // 过滤 thinking 类型中的 <think> 标签
  const cleaned = { ...msg }
  if (cleaned.type === 'thinking' && cleaned.content) {
    cleaned.content = cleanThinkTags(cleaned.content)
    if (!cleaned.content) return // 过滤后为空则不添加
  }
  // thinking 消息默认展开（collapsed 未设置时初始化为 false）
  if (cleaned.type === 'thinking' && cleaned.collapsed === undefined) {
    cleaned.collapsed = false
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
const workspaceShowcaseItems = computed(() => existingWorkspaces.value.slice(0, 6))
const isDownloading = ref(false)
const embeddedPanelCollapsed = ref(false)

// ============ Attachment State ============
const attachedFile = ref<File | null>(null)
const attachedPreviewUrl = ref<string | null>(null)
const isUploading = ref(false)
const fileInputRef = ref<HTMLInputElement>()
const chatFileInputRef = ref<HTMLInputElement>()

// ============ Env Picker ============
const showEnvPicker = ref(false)
const platformEnvs = ref<PlatformEnv[]>([])

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

function workspaceTypeLabel(projectType: string) {
  return wsTypeGroupMap[projectType]?.label || '其他'
}

async function downloadWorkspaceArtifact(ws: WorkspaceInfo, type: 'dist' | 'src') {
  try {
    await codingApi.downloadZip(ws.id, type)
  } catch (e: any) {
    ElMessage.error(e?.message || '下载失败')
  }
}

// ============ Upload to Platform ============
const uploadingWsId = ref<string | null>(null)
const showUploadEnvModal = ref(false)
const pendingUploadWs = ref<WorkspaceInfo | null>(null)

async function uploadWorkspaceCard(ws: WorkspaceInfo) {
  uploadingWsId.value = ws.id

  let envs: Awaited<ReturnType<typeof platformEnvApi.list>>
  try {
    envs = await platformEnvApi.list()
  } catch {
    ElMessage.error('获取平台环境失败')
    uploadingWsId.value = null
    return
  }
  const connectedEnvs = envs.filter(e => e.status === 'connected')

  if (connectedEnvs.length === 0) {
    ElMessage.warning('没有可用的平台环境，请先在环境管理中配置并连接平台')
    uploadingWsId.value = null
    return
  }

  if (connectedEnvs.length === 1) {
    await doUploadWorkspace(ws, connectedEnvs[0].id)
  } else {
    uploadingWsId.value = null
    pendingUploadWs.value = ws
    showUploadEnvModal.value = true
  }
}

async function doUploadWorkspace(ws: WorkspaceInfo, envId: number) {
  uploadingWsId.value = ws.id
  try {
    await codingApi.uploadToPlatform(ws.id, envId)
    ElMessage.success('上传成功')
  } catch (e: any) {
    ElMessage.error(e?.message || '上传失败')
  } finally {
    uploadingWsId.value = null
  }
}

function onUploadEnvSelected(envId: number) {
  if (pendingUploadWs.value) {
    doUploadWorkspace(pendingUploadWs.value, envId)
    pendingUploadWs.value = null
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
  // preconnect to code-server，减少 iframe 首次连接延迟
  try {
    const link = document.createElement('link')
    link.rel = 'preconnect'
    link.href = 'http://localhost:8080'
    document.head.appendChild(link)
  } catch {}

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
    selectedCodingModelValue.value = normalizeCodingModelValue(selectedCodingModelValue.value)
  }
})

onUnmounted(() => {
  // cleanup if needed
})

// ============ Workspace Operations ============

async function openExistingWorkspace(ws: WorkspaceInfo) {
  await openWorkspaceById(ws.id)
}

async function openWorkspaceCatalogPage() {
  await router.push({
    path: '/workspace-catalog',
    query: {
      ...(embeddedAppId.value ? { app_id: embeddedAppId.value } : {}),
    },
  })
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
  ideLoadError.value = ''
  ideLoadingText.value = '正在连接 IDE...'
  ideUrl.value = null  // 销毁旧 iframe
  await nextTick()  // 等 DOM 更新（替代硬编码 100ms 延迟）
  ideUrl.value = baseUrl + (baseUrl.includes('?') ? '&' : '?') + '_t=' + Date.now()
  // 启动 30 秒加载超时
  if (ideLoadTimer) clearTimeout(ideLoadTimer)
  ideLoadTimer = setTimeout(() => {
    if (!ideLoaded.value) {
      ideLoadError.value = 'IDE 加载超时，请检查 code-server 是否运行'
    }
  }, 30_000)
  // 2秒后更新提示文字
  setTimeout(() => {
    if (!ideLoaded.value && !ideLoadError.value) {
      ideLoadingText.value = '正在加载编辑器...'
    }
  }, 2000)
}

function onIdeFrameLoad() {
  ideLoaded.value = true
  ideLoadError.value = ''
  if (ideLoadTimer) { clearTimeout(ideLoadTimer); ideLoadTimer = null }
}

function onIdeFrameError() {
  ideLoadError.value = 'IDE 加载失败，code-server 可能未启动'
  if (ideLoadTimer) { clearTimeout(ideLoadTimer); ideLoadTimer = null }
}

function retryIdeLoad() {
  if (!ideUrl.value) return
  const base = ideUrl.value.replace(/[&?]_t=\d+$/, '')
  ideLoaded.value = false
  ideLoadError.value = ''
  ideLoadingText.value = '正在重新连接...'
  ideUrl.value = null
  nextTick(() => {
    ideUrl.value = base + (base.includes('?') ? '&' : '?') + '_t=' + Date.now()
    if (ideLoadTimer) clearTimeout(ideLoadTimer)
    ideLoadTimer = setTimeout(() => {
      if (!ideLoaded.value) {
        ideLoadError.value = '重试超时，请检查 code-server 状态'
      }
    }, 30_000)
  })
}

async function openPendingIde() {
  if (!pendingIdeUrl.value) return
  await setIdeUrl(pendingIdeUrl.value)
  pendingIdeUrl.value = null
  activeView.value = 'ide'
}

async function openWorkspaceById(wsId: string) {
  try {
    // 并行加载 workspace 信息和会话（减少 1 个 RTT）
    const [ws, workspaceConversation] = await Promise.all([
      codingApi.getWorkspace(wsId),
      codingApi.getWorkspaceConversation(wsId),
    ])
    codingStore.setWorkspace(ws)
    localStorage.setItem('coding_last_workspace_id', wsId)
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
  let sseParseErrors = 0  // SSE 解析错误计数
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
          // content 事件：来自 pipeline 的显式消息（如 brainstorm 提案），用 message 类型展示
          const text = (parsed.content || '') as string
          if (text.trim()) {
            addStreamMsg({ type: 'message', content: text })
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
      } catch (parseErr) {
        sseParseErrors++
        if (sseParseErrors <= 3) {
          console.warn(`[CodingPage] SSE parse error #${sseParseErrors}:`, parseErr)
        }
        if (sseParseErrors === 5) {
          ElMessage.warning('部分 SSE 事件解析失败，结果可能不完整')
        }
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
.content-view-toggle-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px 4px;
  flex-shrink: 0;
  border-bottom: 1px solid var(--t-border-subtle);
}

.toggle-bar-back-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border: 1px solid var(--t-border-subtle);
  border-radius: 6px;
  background: transparent;
  color: var(--t-text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.toggle-bar-back-btn:hover {
  background: var(--t-bg-elevated);
  color: var(--t-text-primary);
}

.toggle-bar-placeholder {
  width: 70px; /* 与返回按钮等宽，保持切换居中 */
}

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

/* ============ Embedded Panel (嵌入模式右侧可收起面板) ============ */
.embedded-panel {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 6px 4px;
  flex-shrink: 0;
  border-left: 1px solid var(--t-border-subtle);
  background: var(--t-bg-panel);
  transition: width 0.2s ease;
  width: 40px;
}
.embedded-panel.collapsed {
  width: 32px;
  padding: 6px 2px;
}
.embedded-panel-toggle {
  width: 28px;
  height: 28px;
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
.embedded-panel-toggle:hover {
  background: var(--t-bg-elevated);
  color: var(--t-text-primary);
}
.embedded-panel-group {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 4px 0;
  border-top: 1px solid var(--t-border-subtle);
  width: 100%;
}
.embedded-panel-btn {
  width: 30px;
  height: 30px;
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
.embedded-panel-btn:hover {
  background: var(--t-bg-elevated);
  color: var(--t-text-primary);
}
.embedded-panel-btn.active {
  background: var(--t-brand-primary);
  color: #fff;
}
.embedded-panel-btn.disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.embedded-panel-btn.danger:hover {
  color: var(--el-color-danger);
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
  align-items: stretch;
  justify-content: center;
  overflow-y: auto;
  background:
    radial-gradient(circle at top, rgba(101, 120, 255, 0.11), transparent 34%),
    linear-gradient(180deg, #f5f7ff 0%, #f7fbff 100%);
}

.welcome-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  max-width: 1160px;
  width: 100%;
  min-height: 100%;
  padding: 6px 36px 28px;
  position: relative;
}

.welcome-hero {
  width: 100%;
  min-height: clamp(328px, 46vh, 468px);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

.welcome-icon {
  font-size: 26px;
  margin-bottom: 8px;
  filter: drop-shadow(0 0 24px var(--t-brand-glow));
}

.welcome-title {
  font-size: 34px;
  font-weight: 800;
  margin: 0 0 10px;
  background: var(--t-brand-gradient);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  letter-spacing: -0.02em;
}

.welcome-desc {
  color: var(--t-text-secondary);
  font-size: 14px;
  margin: 0 0 16px;
  line-height: 1.6;
  max-width: 680px;
}

/* ============ Welcome Input Area ============ */
.welcome-input-area {
  width: min(100%, 1280px);
  margin-bottom: 12px;
}

.coding-model-tip {
  display: block;
  font-size: 10px;
  color: #8b98b3;
  line-height: 1.4;
}

.coding-model-trigger {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 212px;
  width: 258px;
  max-width: 100%;
  padding: 0 10px;
  min-height: 36px;
  border-radius: 12px;
  border: 2px solid rgba(97, 112, 238, 0.78);
  background: rgba(255, 255, 255, 0.92);
  box-shadow:
    0 8px 20px rgba(102, 115, 201, 0.08),
    inset 0 1px 0 rgba(255, 255, 255, 0.86);
  cursor: pointer;
  text-align: left;
  transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
}

.coding-model-trigger:hover:not(:disabled),
.coding-model-trigger.is-open {
  border-color: rgba(97, 112, 238, 0.96);
  box-shadow:
    0 12px 26px rgba(99, 102, 241, 0.12),
    inset 0 1px 0 rgba(255, 255, 255, 0.82);
}

.coding-model-trigger:hover:not(:disabled) {
  transform: translateY(-1px);
}

.coding-model-trigger.is-disabled {
  opacity: 0.62;
  cursor: not-allowed;
}

.coding-model-trigger-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
  width: 100%;
}

.coding-model-trigger-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.coding-model-trigger-name {
  color: #26314f;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.25;
}

.coding-model-trigger-meta {
  color: #7f8fae;
  font-size: 11px;
  font-weight: 600;
  line-height: 1.35;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.coding-model-trigger-icon {
  flex-shrink: 0;
  width: 18px;
  height: 18px;
  border-radius: 7px;
  color: #8a9abd;
  background: transparent;
  box-shadow: none;
  transition: transform 0.2s ease, color 0.2s ease;
}

.coding-model-trigger.is-open .coding-model-trigger-icon {
  transform: rotate(180deg);
  color: #6070d9;
}

.coding-model-panel {
  display: flex;
  flex-direction: column;
  gap: 0;
  padding: 8px;
}

.coding-model-panel-option {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  width: 100%;
  padding: 13px 14px;
  border: none;
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition: background 0.2s ease, transform 0.2s ease;
}

.coding-model-panel-option:hover {
  background: rgba(241, 244, 255, 0.88);
}

.coding-model-panel-option.is-active {
  background: linear-gradient(180deg, rgba(239, 243, 255, 0.96), rgba(232, 238, 252, 0.96));
  border-radius: 16px;
}

.coding-model-panel-option + .coding-model-panel-option {
  border-top: 1px solid rgba(122, 136, 178, 0.12);
}

.coding-model-panel-option-head {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.coding-model-panel-option-name {
  color: #26314f;
  font-size: 12px;
  font-weight: 700;
  line-height: 1.3;
}

.coding-model-panel-option-default {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 20px;
  padding: 0 8px;
  border-radius: 999px;
  background: rgba(99, 102, 241, 0.12);
  color: #5668da;
  font-size: 10px;
  font-weight: 700;
}

.coding-model-panel-option-meta {
  width: 100%;
  margin-top: 4px;
  color: #8190ab;
  font-size: 10px;
  font-weight: 600;
  line-height: 1.35;
}

:global(.coding-model-popover.el-popover.el-popper) {
  padding: 0;
  border-radius: 24px;
  border: 1px solid rgba(122, 136, 178, 0.16);
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 24px 52px rgba(95, 107, 153, 0.18);
  overflow: hidden;
}

.input-wrapper {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
  width: 100%;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.92), rgba(247, 249, 255, 0.9));
  border: 1px solid rgba(124, 138, 182, 0.14);
  border-radius: 24px;
  padding: 10px 14px 10px;
  transition: all 0.28s ease;
  box-shadow:
    0 24px 48px rgba(101, 113, 161, 0.1),
    inset 0 1px 0 rgba(255, 255, 255, 0.78);
  backdrop-filter: blur(14px);
}

.composer-topline {
  display: flex;
  align-items: flex-start;
  justify-content: flex-start;
  gap: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid rgba(123, 138, 178, 0.12);
}

.coding-model-inline {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
  min-width: 0;
}

.input-mainline {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 56px;
}

.input-wrapper:focus-within {
  border-color: rgba(112, 119, 233, 0.2);
  box-shadow:
    0 28px 60px rgba(89, 99, 158, 0.14),
    0 0 0 4px rgba(99, 102, 241, 0.07),
    inset 0 1px 0 rgba(255, 255, 255, 0.8);
}

.composer-text-zone {
  flex: 1;
  min-width: 0;
  padding: 0;
}

.composer-text-zone :deep(.el-textarea) {
  width: 100%;
}

.input-wrapper :deep(.el-textarea__inner) {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
  color: #42506b;
  font-size: 13px;
  line-height: 1.45;
  padding: 0;
  min-height: 22px !important;
  resize: none;
  font-weight: 500;
}

.input-wrapper :deep(.el-textarea__inner::placeholder) {
  color: #a6b2ca;
  font-weight: 500;
}

.send-btn {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  background: var(--t-brand-gradient) !important;
  border: none !important;
  box-shadow: 0 14px 24px rgba(99, 102, 241, 0.24);
  transition: all 0.2s ease;
}

.send-btn:hover:not(:disabled) {
  transform: translateY(-1px) scale(1.03);
  box-shadow: 0 18px 30px rgba(99, 102, 241, 0.28);
}

.send-btn:disabled {
  opacity: 0.55;
  background: linear-gradient(180deg, #e8ebf5, #d9deeb) !important;
  box-shadow: none;
}

.attach-btn {
  flex-shrink: 0;
  width: 34px;
  height: 34px;
  padding: 0;
  border-radius: 11px;
  color: #7f8fb0;
  background: rgba(255, 255, 255, 0.8);
  border: 1px solid rgba(123, 138, 178, 0.14);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.72);
  transition: all 0.2s ease;
}

.attach-btn:hover {
  color: #4f5f89;
  background: rgba(255, 255, 255, 0.95);
  border-color: rgba(102, 114, 220, 0.16);
  transform: translateY(-1px);
}

@media (max-width: 920px) {
  .coding-model-trigger {
    width: 100%;
    min-width: 0;
    max-width: none;
  }

  .welcome-hero {
    min-height: auto;
    justify-content: flex-start;
  }

  .composer-topline,
  .coding-model-inline {
    flex-direction: column;
    align-items: stretch;
  }

  .coding-model-tip {
    white-space: normal;
  }

  .input-wrapper {
    border-radius: 24px;
    padding: 12px;
  }

  .input-mainline {
    align-items: flex-end;
    min-height: 0;
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
  flex-wrap: nowrap;
  overflow-x: auto;
  gap: 8px;
  justify-content: flex-start;
  width: 100%;
  margin-bottom: 26px;
  padding-bottom: 4px;
  scrollbar-width: none;
}

.scene-tabs::-webkit-scrollbar {
  display: none;
}

.scene-tab {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px 14px;
  border-radius: 999px;
  border: 1px solid var(--t-border-subtle);
  background: transparent;
  color: var(--t-text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s ease;
  flex: 0 0 auto;
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
  font-size: 13px;
}

.scene-suggestion-grid {
  width: min(100%, 1280px);
  display: flex;
  gap: 10px;
  margin: -12px 0 14px;
  padding-bottom: 2px;
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: none;
}

.scene-suggestion-grid::-webkit-scrollbar {
  display: none;
}

.scene-suggestion-card {
  flex: 0 0 auto;
  min-height: 40px;
  max-width: 360px;
  padding: 0 18px;
  border-radius: 999px;
  border: 1px solid rgba(227, 232, 246, 0.72);
  background: rgba(255, 255, 255, 0.78);
  color: #73819d;
  font-size: 12px;
  font-weight: 600;
  line-height: 1.35;
  white-space: nowrap;
  text-align: left;
  cursor: pointer;
  box-shadow:
    0 6px 16px rgba(107, 118, 172, 0.04),
    inset 0 1px 0 rgba(255, 255, 255, 0.82);
  transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease, color 0.2s ease;
}

.scene-suggestion-card:hover {
  transform: translateY(-1px);
  border-color: rgba(112, 126, 238, 0.16);
  color: #55637f;
  box-shadow:
    0 10px 20px rgba(99, 102, 241, 0.06),
    inset 0 1px 0 rgba(255, 255, 255, 0.88);
}

/* ============ Workspace Showcase ============ */
.workspace-showcase {
  width: min(100%, 1280px);
  margin-top: 0;
}

.workspace-showcase-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
  width: 100%;
}

.workspace-showcase-title {
  margin: 0;
  color: var(--t-text-primary);
  font-size: 15px;
  font-weight: 650;
  line-height: 1.2;
  text-align: left;
}

.workspace-showcase-more {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: none;
  background: transparent;
  color: var(--t-brand);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  flex-shrink: 0;
  padding: 0;
  transition: color 0.2s ease, transform 0.2s ease;
}

.workspace-showcase-more:hover {
  transform: translateY(-1px);
  color: #5165ea;
}

.workspace-cards-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  width: 100%;
  align-items: stretch;
}

.workspace-card {
  border: 1px solid var(--t-border-subtle);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.9);
  padding: 13px;
  text-align: left;
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
  min-height: 134px;
  display: flex;
  flex-direction: column;
}

.workspace-card:hover {
  transform: translateY(-1px);
  border-color: var(--t-brand-glow);
  box-shadow: 0 8px 18px rgba(99, 102, 241, 0.1);
}

.workspace-catalog-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.workspace-card-catalog {
  min-height: 154px;
}

.workspace-catalog-empty {
  margin-top: 6px;
}

.workspace-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
}

.workspace-card-copy {
  min-width: 0;
  flex: 1;
}

.workspace-card-name {
  color: var(--t-text-primary);
  font-size: 12px;
  font-weight: 650;
  line-height: 1.35;
}

.workspace-card-meta-row {
  margin-top: 4px;
}

.workspace-card-code {
  display: inline-flex;
  align-items: center;
  height: 20px;
  padding: 0 7px;
  border-radius: 10px;
  background: rgba(241, 243, 252, 0.95);
  color: #95a2bf;
  font-size: 10px;
}

.workspace-card-type {
  display: inline-flex;
  align-items: center;
  padding: 0 7px;
  height: 20px;
  border-radius: 999px;
  background: var(--t-brand-subtle);
  color: var(--t-brand-light);
  font-size: 9px;
  font-weight: 600;
  white-space: nowrap;
}

.workspace-card-footer {
  margin-top: auto;
  padding-top: 8px;
  border-top: 1px solid rgba(229, 233, 247, 0.9);
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
}

.workspace-card-meta {
  display: flex;
  flex-direction: column;
  gap: 6px;
  color: var(--t-text-muted);
  font-size: 10px;
  line-height: 1.35;
}

.workspace-card-actions {
  display: flex;
  gap: 4px;
}

.workspace-card-action {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--t-border-subtle);
  background: #fff;
  color: var(--t-text-secondary);
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.workspace-card-action-icon {
  width: 16px;
  height: 16px;
  display: block;
}

.workspace-card-action-primary {
  color: var(--t-brand);
  border-color: rgba(99, 102, 241, 0.2);
}

.workspace-card-action:hover {
  color: var(--t-brand);
  border-color: var(--t-brand-glow);
  background: var(--t-brand-subtle);
}

.workspace-card-action:disabled,
.workspace-card-action.is-loading {
  opacity: 0.6;
  cursor: not-allowed;
  pointer-events: none;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.workspace-showcase-empty {
  width: 100%;
  padding: 16px;
  border: 1px dashed var(--t-border-subtle);
  border-radius: 16px;
  color: var(--t-text-muted);
  font-size: 12px;
  text-align: center;
}

@media (max-width: 1280px) {
  .workspace-catalog-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .scene-suggestion-grid {
    gap: 8px;
  }

  .workspace-cards-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .workspace-catalog-grid {
    grid-template-columns: 1fr;
    gap: 10px;
  }

  .scene-suggestion-grid {
    gap: 8px;
    margin: -10px 0 12px;
  }

  .scene-suggestion-card {
    min-height: 36px;
    max-width: 280px;
    padding: 0 14px;
    font-size: 11px;
  }

  .workspace-showcase-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .workspace-cards-grid {
    grid-template-columns: 1fr;
  }

  .workspace-card-footer {
    align-items: flex-start;
    flex-direction: column;
  }
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
  word-break: break-word;
}

.msg-thinking-text.markdown-body {
  display: block;
  white-space: normal;
}

.msg-thinking-text.markdown-body :deep(h1),
.msg-thinking-text.markdown-body :deep(h2),
.msg-thinking-text.markdown-body :deep(h3) {
  font-weight: 600;
  margin: 12px 0 6px;
  color: var(--t-text);
}
.msg-thinking-text.markdown-body :deep(h2) { font-size: 15px; }
.msg-thinking-text.markdown-body :deep(h3) { font-size: 14px; }

.msg-thinking-text.markdown-body :deep(p) {
  margin: 4px 0;
}

.msg-thinking-text.markdown-body :deep(strong) {
  font-weight: 600;
  color: var(--t-text);
}

.msg-thinking-text.markdown-body :deep(ul),
.msg-thinking-text.markdown-body :deep(ol) {
  padding-left: 20px;
  margin: 4px 0;
}

.msg-thinking-text.markdown-body :deep(li) {
  margin: 2px 0;
}

.msg-thinking-text.markdown-body :deep(table) {
  border-collapse: collapse;
  margin: 8px 0;
  font-size: 13px;
  width: 100%;
}

.msg-thinking-text.markdown-body :deep(th),
.msg-thinking-text.markdown-body :deep(td) {
  border: 1px solid var(--t-border, #e4e7ed);
  padding: 6px 10px;
  text-align: left;
}

.msg-thinking-text.markdown-body :deep(th) {
  background: var(--t-bg-secondary, #f5f7fa);
  font-weight: 600;
}

.msg-thinking-text.markdown-body :deep(code) {
  background: var(--t-bg-secondary, #f5f7fa);
  border-radius: 3px;
  padding: 1px 5px;
  font-family: monospace;
  font-size: 12px;
}

.msg-thinking-text.markdown-body :deep(pre) {
  background: var(--t-bg-secondary, #f5f7fa);
  border-radius: 6px;
  padding: 10px 14px;
  overflow-x: auto;
  margin: 8px 0;
}

.msg-thinking-text.markdown-body :deep(pre code) {
  background: none;
  padding: 0;
}

.msg-thinking-text.markdown-body :deep(hr) {
  border: none;
  border-top: 1px solid var(--t-border, #e4e7ed);
  margin: 10px 0;
}

.msg-thinking-text.markdown-body :deep(blockquote) {
  border-left: 3px solid var(--t-brand, #5b6af0);
  padding-left: 12px;
  margin: 6px 0;
  color: var(--t-text-secondary, #888);
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
.ide-error-icon {
  font-size: 32px;
  margin-bottom: 4px;
}
.ide-retry-btn {
  margin-top: 12px;
  padding: 8px 24px;
  border: 1px solid var(--t-brand, #646cff);
  border-radius: 8px;
  background: transparent;
  color: var(--t-brand, #646cff);
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}
.ide-retry-btn:hover {
  background: var(--t-brand, #646cff);
  color: #fff;
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
