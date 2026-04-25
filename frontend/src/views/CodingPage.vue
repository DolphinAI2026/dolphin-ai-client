<template>
  <BuilderFrame :breadcrumbs="[{ label: '智能开发' }]">
    <!-- Env Picker Dialog -->
    <el-dialog v-model="showEnvPicker" title="选择调试平台环境" width="500px" :append-to-body="true">
      <div v-if="platformEnvs.length === 0" style="text-align:center;color:#999;padding:20px;">
        <template v-if="userStore.isTenantAdmin">
          暂无平台环境，请先到<el-link type="primary" @click="$router.push('/platform-envs')">环境管理</el-link>添加
        </template>
        <template v-else>
          当前账号没有环境管理权限，请联系租户管理员配置可用环境。
        </template>
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
            <el-icon :size="16"><ArrowLeft /></el-icon>
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
              :class="{ active: activeView === 'ide', disabled: !canOpenIdeView }"
              :disabled="!canOpenIdeView"
              :title="webIdeUnavailable ? '当前环境未配置 Web IDE' : 'IDE'"
              @click="switchToIdeView"
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
            <!-- 参考首页 Landing 风格的 hero -->
            <div class="coding-landing-hero" :style="codingLandingVars">
              <div class="coding-landing-bg"></div>

              <section class="brand-copy">
                <h1 class="brand-title">
                  <span class="brand-glyph-inline">{}</span>
                  <span>AI 帮你写代码</span>
                </h1>
                <p class="brand-sub">描述组件、页面或接口，AI 帮你打开 Coding 工作区。</p>
              </section>

              <section class="composer">
                <div class="composer-shell ai-surface">
                  <div class="composer-mode-bar">
                    <span class="composer-mode-label">
                      <span>{}</span>
                      Code · 智能开发
                    </span>
                  </div>

                  <input
                    ref="fileInputRef"
                    type="file"
                    accept=".md,.pdf,.docx,.txt,.png,.jpg,.jpeg"
                    style="display: none"
                    @change="handleFileSelect"
                  />

                  <!-- 附件预览 -->
                  <div v-if="attachedFile" class="composer-attachment">
                    <div v-if="attachedPreviewUrl" class="composer-attachment-thumb">
                      <img :src="attachedPreviewUrl" alt="preview" />
                      <button class="composer-attachment-remove" @click="removeAttachment">&times;</button>
                    </div>
                    <div v-else class="composer-attachment-file">
                      <span class="composer-attachment-file-icon">&#128196;</span>
                      <span class="composer-attachment-file-name">{{ attachedFile.name }}</span>
                      <button class="composer-attachment-remove" @click="removeAttachment">&times;</button>
                    </div>
                  </div>

                  <div class="composer-body" @paste="handlePaste">
                    <textarea
                      v-model="userInput"
                      class="composer-input"
                      placeholder="描述你想开发的内容。例如：做一个头像上传组件，支持裁剪、预览、上传失败重试，并输出可接入表单的组件。"
                      @keydown.ctrl.enter="sendMessage"
                      @keydown.meta.enter="sendMessage"
                      :disabled="isCreating"
                    ></textarea>
                  </div>

                  <div class="composer-toolbar">
                    <button
                      type="button"
                      class="chip"
                      @click="fileInputRef?.click()"
                      :disabled="isCreating"
                      title="上传附件"
                    >＋ 附加文件</button>

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
                          class="chip composer-model-chip"
                          :class="{ 'is-open': codingModelPopoverVisible, 'is-disabled': codingModelLoading || updatingCodingModel || codingModelOptions.length === 0 }"
                          :disabled="codingModelLoading || updatingCodingModel || codingModelOptions.length === 0"
                          aria-label="选择模型"
                        >
                          <span>{{ selectedCodingModelOption?.config_name || '选择模型' }}</span>
                          <el-icon><ArrowDown /></el-icon>
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

                    <div class="toolbar-spacer"></div>

                    <button
                      type="button"
                      class="landing-submit"
                      :disabled="(!userInput.trim() && !attachedFile) || isCreating"
                      @click="sendMessage"
                    >
                      <span v-if="!isCreating && !isUploading">↗</span>
                      <span v-else class="composer-submit-spinner" />
                      进入开发
                      <span class="submit-kbd">⌘↵</span>
                    </button>
                  </div>
                </div>
              </section>
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
                  <h3 class="workspace-showcase-title">最近自开发工作区</h3>
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
                    <div class="workspace-card-actions">
                      <button
                        :class="['workspace-card-action', 'workspace-card-action-primary', { 'is-loading': openingWsId === ws.id }]"
                        :title="openingWsId === ws.id ? '打开中...' : '进入开发'"
                        :disabled="openingWsId === ws.id"
                        @click.stop="openExistingWorkspace(ws)"
                      >
                        <svg v-if="openingWsId !== ws.id" class="workspace-card-action-icon" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                          <path d="M5.25 3.5L11 8L5.25 12.5V3.5Z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" />
                        </svg>
                        <svg v-else class="workspace-card-action-icon spin" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                          <circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="1.5" stroke-dasharray="28 10" stroke-linecap="round" />
                        </svg>
                      </button>
                      <button
                        v-if="canUploadWorkspace(ws)"
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
                        :class="['workspace-card-action', { 'is-loading': downloadingWsId === ws.id }]"
                        :title="downloadingWsId === ws.id ? '下载中...' : '下载源码'"
                        :disabled="downloadingWsId === ws.id"
                        @click.stop="downloadWorkspaceArtifact(ws, 'src')"
                      >
                        <svg v-if="downloadingWsId !== ws.id" class="workspace-card-action-icon" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                          <path d="M8 4V9.75" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
                          <path d="M10.25 7.5L8 9.75L5.75 7.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
                          <path d="M4 10.25V11.25C4 11.9404 4.55964 12.5 5.25 12.5H10.75C11.4404 12.5 12 11.9404 12 11.25V10.25" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
                        </svg>
                        <svg v-else class="workspace-card-action-icon spin" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                          <circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="1.5" stroke-dasharray="28 10" stroke-linecap="round" />
                        </svg>
                      </button>
                      <button
                        v-if="canDeleteWorkspace(ws)"
                        :class="['workspace-card-action', 'workspace-card-action-danger', { 'is-loading': deletingWsId === ws.id }]"
                        :title="deletingWsId === ws.id ? '删除中...' : '删除工作区'"
                        :disabled="deletingWsId === ws.id || openingWsId === ws.id || downloadingWsId === ws.id || uploadingWsId === ws.id"
                        @click.stop="deleteWorkspace(ws)"
                      >
                        <svg v-if="deletingWsId !== ws.id" class="workspace-card-action-icon" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                          <path d="M3 4.5H13" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
                          <path d="M6 4.5V3.25C6 2.83579 6.33579 2.5 6.75 2.5H9.25C9.66421 2.5 10 2.83579 10 3.25V4.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
                          <path d="M4.5 4.5L5 12.25C5.03 12.8 5.5 13.25 6.05 13.25H9.95C10.5 13.25 10.97 12.8 11 12.25L11.5 4.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
                          <path d="M6.75 7V11" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
                          <path d="M9.25 7V11" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
                        </svg>
                        <svg v-else class="workspace-card-action-icon spin" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                          <circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="1.5" stroke-dasharray="28 10" stroke-linecap="round" />
                        </svg>
                      </button>
                    </div>
                  </div>
                </article>
              </div>

              <div v-else class="workspace-showcase-empty">
                暂无自开发工作区。先描述一个开发需求，我们会先生成开发 SPEC。
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
                <div class="msg-user-bubble user-markdown markdown-body" v-html="renderMarkdown(msg.content)"></div>
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
              <template v-else-if="msg.type === 'status' && !msg.hidden">
                <!-- 步骤完成 badge 芯片 -->
                <div v-if="msg.stepDone" class="msg-step-badge">
                  <svg class="step-badge-icon" viewBox="0 0 16 16" fill="none">
                    <circle cx="8" cy="8" r="7" fill="currentColor" opacity="0.15"/>
                    <path d="M5 8l2.5 2.5L11 5.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                  </svg>
                  <span>{{ msg.content }}</span>
                </div>
                <!-- 普通状态文字 -->
                <div v-else class="msg-status" :class="{ 'status-progress': msg.content.endsWith('...') }">
                  <span class="status-content">{{ msg.content }}</span>
                </div>
              </template>

              <!-- 文件写入 / 文件编辑 -->
              <template v-else-if="msg.type === 'file_write' || msg.type === 'file_edit'">
                <FileCard
                  :action="msg.type === 'file_write' ? 'write' : 'edit'"
                  :file-name="msg.fileName"
                  :file-content="msg.fileContent"
                  :collapsed="msg.collapsed"
                  @toggle="msg.collapsed = !msg.collapsed"
                />
              </template>

              <!-- 工具调用（读文件/扫描/搜索等，含可折叠结果） -->
              <template v-else-if="msg.type === 'tool'">
                <div class="msg-tool-row" :class="{ 'has-result': msg.result }">
                  <div class="tool-row-header" @click="msg.result && (msg.resultCollapsed = !msg.resultCollapsed)">
                    <span class="tool-row-text">{{ msg.content }}</span>
                    <svg v-if="msg.result" class="tool-row-chevron" :class="{ rotated: !msg.resultCollapsed }" viewBox="0 0 16 16" fill="none">
                      <path d="M4 6l4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                  </div>
                  <div v-if="msg.result && !msg.resultCollapsed" class="tool-row-result">
                    <pre>{{ msg.result }}</pre>
                  </div>
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
                <div class="msg-error-row">
                  <svg class="error-row-icon" viewBox="0 0 16 16" fill="none">
                    <circle cx="8" cy="8" r="7" stroke="currentColor" stroke-width="1.4"/>
                    <path d="M8 5v3.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
                    <circle cx="8" cy="11" r="0.75" fill="currentColor"/>
                  </svg>
                  <span class="error-row-text">{{ msg.content }}</span>
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
              :class="{ active: activeView === 'ide', disabled: !canOpenIdeView }"
              :disabled="!canOpenIdeView"
              @click="switchToIdeView"
              :title="webIdeUnavailable ? '当前环境未配置 Web IDE' : '代码编辑器'"
            >
              <el-icon :size="16"><Monitor /></el-icon>
            </button>
          </div>
          <div v-if="codingStore.workspace" class="embedded-panel-group">
            <button class="embedded-panel-btn" :disabled="isDownloading" @click="downloadCode" title="下载代码">
              <el-icon :size="16"><Download /></el-icon>
            </button>
            <button
              v-if="codingStore.workspace && canDeleteWorkspace(codingStore.workspace)"
              class="embedded-panel-btn danger"
              @click="deleteCurrentWorkspace"
              title="删除工作区"
            >
              <el-icon :size="16"><Delete /></el-icon>
            </button>
          </div>
        </template>
      </aside>
    </div>
  </BuilderFrame>

  <EnvSelectModal v-model="showUploadEnvModal" @selected="onUploadEnvSelected" />
</template>

<script setup lang="ts">
import { API_PREFIX } from '@/utils/request'
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, ArrowLeft, Download, TopRight, Paperclip, Monitor, Delete, Fold, Expand, ChatDotRound } from '@element-plus/icons-vue'
import { useCodingStore } from '@/stores/coding'
import { platformEnvApi, type PlatformEnv } from '@/api/platformEnv'
import { useUserStore } from '@/stores/user'
import { codingApi, isIdeUnavailableError } from '@/api/coding'
import type { WorkspaceInfo, UploadResult, ReplayStreamMessage } from '@/api/coding'
import { harnessApi } from '@/api/harness'
import { conversationApi } from '@/api/conversation'
import { llmConfigApi, type BuilderModelOption } from '@/api/llmConfig'
import { consumeSseResponse } from '@/utils/sse'
import { useThemeStore } from '@/stores/theme'
import BuilderFrame from '@/components/BuilderFrame.vue'
import EnvSelectModal from '@/components/EnvSelectModal.vue'
import FileCard from '@/components/FileCard.vue'
import { useCodingModel } from './coding/useCodingModel'
import { useStreamMessages, formatSceneType, renderMarkdown } from './coding/useStreamMessages'
import { useIdeManager } from './coding/useIdeManager'
import { useCodingWorkspace } from './coding/useCodingWorkspace'
import { useCodingPipeline } from './coding/useCodingPipeline'

const route = useRoute()
const router = useRouter()
const codingStore = useCodingStore()
const userStore = useUserStore()
const themeStore = useThemeStore()

// ============ Core State ============
const userInput = ref('')
const isCreating = ref(false)
const creatingStatus = ref('')

// 参考首页 Landing 的 code 模式色板
const codingLandingVars: Record<string, string> = {
  '--landing-mode-color': 'oklch(67% 0.14 255)',
  '--landing-mode-soft': 'oklch(95% 0.03 255)',
  '--landing-mode-ink': 'oklch(50% 0.17 255)',
}

// ── IDE iframe 管理（已抽成 composable）──
const {
  ideUrl,
  ideLoaded,
  ideLoadError,
  ideLoadingText,
  pendingIdeUrl,
  activeView,
  setIdeUrl,
  onIdeFrameLoad,
  onIdeFrameError,
  retryIdeLoad,
  openPendingIde,
} = useIdeManager()

const webIdeUnavailable = ref(false)
const ideUnavailableNotified = ref(false)
const canOpenIdeView = computed(() => (
  !webIdeUnavailable.value &&
  (!!ideUrl.value || !!pendingIdeUrl.value || !!codingStore.workspace)
))

function setWebIdeUnavailable() {
  webIdeUnavailable.value = true
  pendingIdeUrl.value = null
  ideUrl.value = null
  if (activeView.value === 'ide') activeView.value = 'chat'
}

function notifyWebIdeUnavailable(message = '当前环境未配置 Web IDE，已保持在对话模式继续开发') {
  setWebIdeUnavailable()
  if (!ideUnavailableNotified.value) {
    ElMessage.info(message)
    ideUnavailableNotified.value = true
  }
}

function setWebIdeAvailable() {
  webIdeUnavailable.value = false
  ideUnavailableNotified.value = false
}

async function switchToIdeView() {
  if (webIdeUnavailable.value) {
    notifyWebIdeUnavailable()
    return
  }

  if (ideUrl.value) {
    setWebIdeAvailable()
    activeView.value = 'ide'
    return
  }

  if (pendingIdeUrl.value) {
    setWebIdeAvailable()
    await openPendingIde()
    return
  }

  const workspace = codingStore.workspace
  if (!workspace) {
    ElMessage.info('当前还没有可打开的 IDE 工作区')
    return
  }

  try {
    const { ide_url } = await codingApi.getIdeUrl(workspace.id, codingStore.conversationId, themeStore.mode)
    setWebIdeAvailable()
    await setIdeUrl(ide_url)
    activeView.value = 'ide'
  } catch (error: any) {
    if (isIdeUnavailableError(error)) {
      notifyWebIdeUnavailable()
      return
    }
    ElMessage.warning(error?.response?.data?.detail || error?.message || 'IDE URL 获取失败')
  }
}

// ── Coding 模型选择（已抽成 composable）──
const {
  codingModelOptions,
  codingModelLoading,
  updatingCodingModel,
  selectedCodingModelValue,
  persistedCodingModelValue,
  codingModelPopoverVisible,
  selectedCodingModelOption,
  codingModelHint,
  codingModelSummary,
  toCodingModelValue,
  normalizeCodingModelValue,
  applyCodingModelSelection,
  formatCodingModelProvider,
  loadCodingModelOptions,
  handleCodingModelChange,
  selectCodingModel,
} = useCodingModel()

// ============ Stream Messages (对话流) ============
// ── 对话流消息（已抽成 composable）──
const {
  streamMessages,
  isStreaming,
  streamContainerRef,
  scrollStreamToBottom,
  addStreamMsg,
  appendToLastThinking,
  appendToLastCommand,
  completeStepMsg,
  addStepRunningMsg,
  restoreReplayStreamMessages,
} = useStreamMessages()

// ── 工作区列表和元信息展示（已抽成 composable）──
const {
  allWorkspaces,
  isDownloading,
  downloadingWsId,
  embeddedProjectId,
  embeddedAppId,
  existingWorkspaces,
  workspaceShowcaseItems,
  workspaceDisplayName,
  workspaceCodeName,
  workspaceTooltip,
  workspaceTypeLabel,
  downloadWorkspaceArtifact,
} = useCodingWorkspace()

/** 正在打开的工作区 id（卡片级 loading 标记，防止重复点击） */
const openingWsId = ref<string | null>(null)
/** 正在删除的工作区 id */
const deletingWsId = ref<string | null>(null)

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


// ============ Upload to Platform ============
const uploadingWsId = ref<string | null>(null)
const showUploadEnvModal = ref(false)
const pendingUploadWs = ref<WorkspaceInfo | null>(null)

function canUploadWorkspace(ws: WorkspaceInfo) {
  return ws.permissions?.upload_to_platform !== false
}

function canDeleteWorkspace(ws: WorkspaceInfo) {
  return ws.permissions?.delete !== false
}

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
  { key: 'component-mobile', icon: '\uD83D\uDCF1', label: 'Mobile\u7EC4\u4EF6' },
  { key: 'page-mobile', icon: '\uD83D\uDCF1', label: 'Mobile\u9875\u9762' },
  { key: 'backend', icon: '\u2699\uFE0F', label: '\u540E\u7AEF\u63A5\u53E3' },
]

const sceneSuggestions: Record<string, string[]> = {
  'component-pc': [
    '开发一个头像上传组件，支持裁剪和预览',
    '实现一个日期范围选择器组件',
    '做一个评分组件，支持半星和自定义颜色',
    '创建一个图表分析组件，支持柱状图和饼图',
  ],
  'page-pc': [
    '做一个项目进度甘特图页面，复用低代码任务表单服务',
    '做一个数据查询表格页面，带搜索和分页',
    '开发一个供应商管理弹窗选择页面',
    '创建一个项目分析图表页面，包含统计卡片和趋势图',
  ],
  'component-mobile': [
    '开发一个移动端签名板组件',
    '做一个移动端图片选择上传组件',
    '实现一个移动端级联选择器组件',
    '创建一个移动端评分组件',
  ],
  'page-mobile': [
    '做一个移动端数据查询列表页面',
    '开发一个移动端审批详情页面',
    '创建一个移动端任务看板页面',
    '做一个移动端个人信息编辑页面',
  ],
  backend: [
    '开发一个自定义数据查询接口',
    '做一个批量导入的后端接口',
    '创建一个报表统计的后端API',
  ],
}

const activeSceneCategory = ref('component-pc')
const pendingSceneCategory = ref<string | null>(null)

const sceneCategoryToProjectType: Record<string, string> = {
  'component-pc': 'form-component',
  'page-pc': 'menu-page',
  'component-mobile': 'mobile-component',
  'page-mobile': 'mobile-page',
  backend: 'backend-api',
}

const AI_BUILDER_PENDING_CODING_KEY = 'ai_builder_pending_coding'

async function maybeConsumeAiBuilderDispatch() {
  if (route.query.from_ai_builder !== '1') return
  if (route.query.workspace_id || route.query.ws) return
  if (streamMessages.value.length > 0 || isCreating.value || isStreaming.value) return

  const raw = sessionStorage.getItem(AI_BUILDER_PENDING_CODING_KEY)
  if (!raw) return

  let payload: { message?: string; projectId?: number | null; sceneCategory?: string } | null = null
  try {
    payload = JSON.parse(raw)
  } catch {
    sessionStorage.removeItem(AI_BUILDER_PENDING_CODING_KEY)
    return
  }

  if (!payload?.message?.trim()) {
    sessionStorage.removeItem(AI_BUILDER_PENDING_CODING_KEY)
    return
  }

  sessionStorage.removeItem(AI_BUILDER_PENDING_CODING_KEY)

  if (payload.projectId) {
    localStorage.setItem('coding_last_project_id', String(payload.projectId))
  }
  if (payload.sceneCategory && sceneSuggestions[payload.sceneCategory]?.length) {
    activeSceneCategory.value = payload.sceneCategory
    pendingSceneCategory.value = payload.sceneCategory
  }

  userInput.value = payload.message.trim()
  await nextTick()
  await sendMessage()
}

// ============ Lifecycle ============

onMounted(async () => {
  // 申请浏览器通知权限（用于开发 SPEC 生成后提醒用户）
  if ('Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission()
  }

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
    await maybeConsumeAiBuilderDispatch()
  }
})

onUnmounted(() => {
  // cleanup if needed
})

// ============ Workspace Operations ============

async function openExistingWorkspace(ws: WorkspaceInfo) {
  if (openingWsId.value === ws.id) return  // 防止重复点击
  openingWsId.value = ws.id
  try {
    await openWorkspaceById(ws.id)
  } finally {
    openingWsId.value = null
  }
}

async function openWorkspaceCatalogPage() {
  await router.push({
    path: '/workspace-catalog',
    query: {
      ...(embeddedProjectId.value ? { project_id: embeddedProjectId.value } : {}),
      ...(embeddedAppId.value ? { app_id: embeddedAppId.value } : {}),
    },
  })
}

// 设置 IDE URL — 先销毁旧 iframe 再创建新的，避免 code-server session 缓存
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

    try {
      const { ide_url } = await codingApi.getIdeUrl(ws.id, workspaceConversation.conversation_id, themeStore.mode)
      setWebIdeAvailable()
      await setIdeUrl(ide_url)
      activeView.value = 'ide'
    } catch (error: any) {
      if (isIdeUnavailableError(error)) {
        notifyWebIdeUnavailable('当前环境未配置 Web IDE，已进入对话开发模式')
        return
      }
      throw error
    }
  } catch (error: any) {
    ElMessage.error(`打开工作区失败: ${error.message}`)
  }
}

/** 把后端保存的对话消息转换成 streamMessages 格式 */
function loadConversationHistory(
  messages: Array<{ role: string; content: string }>,
  replayStreamMessages: ReplayStreamMessage[] = [],
) {
  streamMessages.value = []

  // 先还原 brainstorm 阶段消息（messages 里有，stream_messages 通常不含）
  // 场景：messages 里会出现 "<!-- BRAINSTORM_PROPOSAL --> ..." 的 assistant 消息，
  // 它前面那条 user 是原始需求。stream_messages 里第一条 user 通常是"确认/revise"。
  // 所以这里只把 brainstorm 方案及之前的 user 预先插入，codegen 阶段的内容交给 replay 恢复。
  for (let i = 0; i < messages.length; i++) {
    const msg = messages[i]
    const content = msg.content || ''
    if (msg.role === 'assistant' && content.startsWith('<!-- BRAINSTORM_PROPOSAL -->')) {
      // 找到这条 brainstorm 方案前一条 user（原始需求）
      for (let j = i - 1; j >= 0; j--) {
        if (messages[j].role === 'user') {
          addStreamMsg({ type: 'user', content: messages[j].content })
          break
        }
      }
      // brainstorm 方案本体用 type:'message' 渲染（始终展开，Markdown）
      addStreamMsg({
        type: 'message',
        content: content.replace(/^<!-- BRAINSTORM_PROPOSAL -->/, '').trim(),
      })
      break
    }
  }

  // 有 codegen 阶段的 stream_messages 就 append 恢复（这是细节最丰富的路径）
  if (replayStreamMessages.length > 0) {
    restoreReplayStreamMessages(replayStreamMessages)
    return
  }

  // fallback：没有 stream_messages 时用 messages 整体重建
  //（通常是旧数据或生成失败的会话）
  streamMessages.value = []
  for (const msg of messages) {
    const content = msg.content || ''
    if (msg.role === 'user') {
      addStreamMsg({ type: 'user', content })
    } else if (msg.role === 'assistant') {
      if (content.startsWith('<!-- BRAINSTORM_PROPOSAL -->')) {
        addStreamMsg({
          type: 'message',
          content: content.replace(/^<!-- BRAINSTORM_PROPOSAL -->/, '').trim(),
        })
      } else {
        parseAssistantHistory(content)
      }
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
    // 工具结果成功: > ✅ ... — 文件写入/读取结果冗余，跳过不渲染
    else if (line.startsWith('> ✅')) {
      flushThinking()
      // 跳过: 文件卡片已经展示了写入/编辑信息，工具结果行不需要单独显示
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
  setWebIdeAvailable()
  ideUrl.value = null
  pendingIdeUrl.value = null
  ideLoaded.value = false
  streamMessages.value = []
  activeView.value = 'chat'
  localStorage.removeItem('coding_last_workspace_id')
}

async function deleteWorkspace(ws: WorkspaceInfo) {
  if (deletingWsId.value === ws.id) return  // 防止重复点击
  const displayName = workspaceDisplayName(ws) || ws.project_name
  try {
    await ElMessageBox.confirm(
      `确定要删除工作区「${displayName}」吗？\n\n此操作将：\n1. 停止该工作区所有正在运行的 npm run serve 进程\n2. 永久删除该工作区目录及所有文件\n\n此操作不可撤销！`,
      '危险操作确认',
      {
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
        type: 'warning',
        dangerouslyUseHTMLString: false,
        confirmButtonClass: 'el-button--danger',
      },
    )
  } catch {
    // 用户取消
    return
  }

  deletingWsId.value = ws.id
  try {
    await codingApi.deleteWorkspace(ws.id)
    allWorkspaces.value = allWorkspaces.value.filter(w => w.id !== ws.id)
    if (codingStore.workspace?.id === ws.id) {
      codingStore.reset()
      ideUrl.value = null
      pendingIdeUrl.value = null
      setWebIdeAvailable()
      localStorage.removeItem('coding_last_workspace_id')
    }
    ElMessage.success('已删除')
  } catch (e: any) {
    ElMessage.error(e.message || '删除失败')
  } finally {
    deletingWsId.value = null
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
// SSE handlers + upload + build request + consume SSE + load IDE URL + sendMessage / sendSuggestion
// 全部抽到 useCodingPipeline composable
const { sendMessage, sendSuggestion } = useCodingPipeline({
  model: { codingModelOptions, codingModelLoading, updatingCodingModel, selectedCodingModelValue, persistedCodingModelValue, codingModelPopoverVisible, selectedCodingModelOption, codingModelHint, codingModelSummary, toCodingModelValue, normalizeCodingModelValue, applyCodingModelSelection, loadCodingModelOptions, handleCodingModelChange, selectCodingModel } as any,
  stream: { streamMessages, isStreaming, streamContainerRef, scrollStreamToBottom, addStreamMsg, appendToLastThinking, appendToLastCommand, completeStepMsg, addStepRunningMsg, restoreReplayStreamMessages } as any,
  ide: { ideUrl, ideLoaded, ideLoadError, ideLoadingText, pendingIdeUrl, activeView, setIdeUrl, onIdeFrameLoad, onIdeFrameError, retryIdeLoad, openPendingIde } as any,
  workspace: { allWorkspaces, isDownloading, embeddedAppId, existingWorkspaces, workspaceShowcaseItems, workspaceDisplayName, workspaceCodeName, workspaceTooltip, workspaceTypeLabel, downloadWorkspaceArtifact } as any,
  activeSceneCategory,
  pendingSceneCategory,
  sceneCategoryToProjectType,
  userInput,
  attachedFile,
  attachedPreviewUrl,
  isUploading,
  isCreating,
  onIdeUnavailable: setWebIdeUnavailable,
  onIdeAvailable: setWebIdeAvailable,
})


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
    const { ide_url } = await codingApi.getIdeUrl(codingStore.workspace.id, codingStore.conversationId, themeStore.mode)
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

watch(() => themeStore.mode, async (mode) => {
  const workspace = codingStore.workspace
  if (!workspace || webIdeUnavailable.value) return
  try {
    const { ide_url } = await codingApi.getIdeUrl(workspace.id, codingStore.conversationId, mode)
    if (activeView.value === 'ide' && ideUrl.value) {
      await setIdeUrl(ide_url)
    } else {
      pendingIdeUrl.value = ide_url
    }
  } catch {
    // 主题同步失败不影响当前开发会话。
  }
})

watch(() => route.path, () => {
  if (!route.path.startsWith('/coding')) {
    codingStore.reset()
    ideUrl.value = null
    pendingIdeUrl.value = null
    setWebIdeAvailable()
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
  padding: 10px 16px 8px;
  flex-shrink: 0;
  border-bottom: 1px solid var(--t-border-subtle);
}

.toggle-bar-back-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 16px;
  border: 1px solid var(--t-border-subtle);
  border-radius: 8px;
  background: transparent;
  color: var(--t-text-secondary);
  font-size: 14px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.toggle-bar-back-btn:hover {
  background: var(--t-bg-elevated);
  color: var(--t-text-primary);
}

.toggle-bar-placeholder {
  width: 88px; /* 与返回按钮等宽，保持切换居中 */
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
  padding: 6px 14px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--t-text-tertiary);
  cursor: pointer;
  font-size: 13px;
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
  background: #fbfcfe;
}

.welcome-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  max-width: 1160px;
  width: 100%;
  min-height: 100%;
  padding: 8px 36px 32px;
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
  margin: 12px 0 8px;
  padding-bottom: 2px;
  scrollbar-width: none;
  flex-shrink: 0;
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
  gap: 8px;
  margin: 0 0 16px;
  padding-bottom: 2px;
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: none;
  flex-shrink: 0;
}

.scene-suggestion-grid::-webkit-scrollbar {
  display: none;
}

.scene-suggestion-card {
  flex: 0 0 auto;
  min-height: 32px;
  max-width: 360px;
  padding: 6px 14px;
  border-radius: 999px;
  border: 1px solid var(--t-border-subtle);
  background: var(--t-bg-input);
  color: var(--t-text-secondary);
  font-size: 12px;
  font-weight: 500;
  line-height: 1.35;
  white-space: nowrap;
  text-align: left;
  cursor: pointer;
  transition: transform 0.2s ease, border-color 0.2s ease, color 0.2s ease, background 0.2s ease;
}

.scene-suggestion-card:hover {
  transform: translateY(-1px);
  border-color: var(--t-brand);
  color: var(--t-brand);
  background: var(--t-brand-subtle);
}

/* ============ Workspace Showcase ============ */
.workspace-showcase {
  width: min(100%, 1280px);
  margin-top: 4px;
  padding-top: 16px;
  border-top: 1px solid var(--t-border-subtle);
  flex-shrink: 0;
}

.workspace-showcase-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
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
  border-radius: 12px;
  background: var(--t-bg-panel);
  padding: 12px 14px;
  text-align: left;
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.workspace-card:hover {
  transform: translateY(-1px);
  border-color: var(--t-brand);
  box-shadow: var(--t-shadow-md);
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
  /* 防御 display_name 偶尔是 chat 长片段，单行省略 */
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
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
  background: var(--t-bg-input);
  color: var(--t-text-muted);
  font-size: 10px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
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
  margin-top: 0;
  padding-top: 0;
  border-top: 0;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
}

.workspace-card-actions {
  display: flex;
  gap: 4px;
}

.workspace-card-action {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--t-border-subtle);
  background: var(--t-bg-input);
  color: var(--t-text-secondary);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.workspace-card-action-icon {
  width: 14px;
  height: 14px;
  display: block;
}

.workspace-card-action-primary {
  color: var(--t-brand);
  border-color: var(--t-brand-subtle);
  background: var(--t-brand-subtle);
}

.workspace-card-action:hover {
  color: var(--t-brand);
  border-color: var(--t-brand-glow);
  background: var(--t-brand-subtle);
}

.workspace-card-action-danger:hover {
  color: #f56c6c;
  border-color: rgba(245, 108, 108, 0.35);
  background: rgba(245, 108, 108, 0.08);
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
  gap: 3px;
}

/* 卡片类消息上下留一点额外间距，与状态行视觉分组 */
.msg-ai-message,
.msg-thinking-card,
.msg-file-card,
.msg-command-card,
.msg-error-row {
  margin-top: 6px;
  margin-bottom: 2px;
}

.stream-msg {
  display: flex;
  flex-direction: column;
  animation: fadeInUp 0.2s ease-out;
}

/* 用户消息行右对齐 */
.msg-user { align-items: flex-end; }

@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

/* 用户消息 */
.msg-user-bubble {
  max-width: 75%;
  padding: 10px 16px;
  background: var(--t-brand);
  color: #fff;
  border-radius: 16px 16px 4px 16px;
  font-size: 14px;
  line-height: 1.6;
  margin-bottom: 4px;
  box-shadow: 0 2px 8px var(--t-brand-glow);
  word-break: break-word;
}
/* 用户消息 Markdown 元素样式 */
.user-markdown p { margin: 0 0 6px; }
.user-markdown p:last-child { margin-bottom: 0; }
.user-markdown ul, .user-markdown ol { margin: 4px 0 6px 18px; padding: 0; }
.user-markdown li { margin: 2px 0; }
.user-markdown strong { color: #fff; font-weight: 600; }
.user-markdown em { color: rgba(255,255,255,0.9); }
.user-markdown a { color: rgba(255,255,255,0.85); text-decoration: underline; }
.user-markdown h1, .user-markdown h2, .user-markdown h3,
.user-markdown h4, .user-markdown h5, .user-markdown h6 {
  color: #fff;
  margin: 6px 0 4px;
  font-size: 14px;
  font-weight: 600;
  border-bottom: none;
}
.user-markdown code {
  background: rgba(255,255,255,0.2);
  color: #fff;
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 12.5px;
}

/* ---- AI 显式消息（设计方案等 Markdown 块） ---- */
.msg-ai-message {
  background: var(--t-bg-panel);
  border: 1px solid var(--t-border-strong);
  border-radius: var(--t-radius-sm);
  padding: 16px 20px;
  margin: 6px 0;
  box-shadow: var(--t-shadow-sm);
}

.ai-message-body.markdown-body {
  font-size: 14px;
  line-height: 1.7;
  color: var(--t-text-primary);
}

/* ---- Markdown 通用样式（复用于 ai-message 和 thinking） ---- */
.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3) {
  font-weight: 600;
  color: var(--t-text-primary);
  margin: 14px 0 6px;
  line-height: 1.4;
}
.markdown-body :deep(h1) { font-size: 17px; }
.markdown-body :deep(h2) { font-size: 15px; }
.markdown-body :deep(h3) { font-size: 14px; }

.markdown-body :deep(p) { margin: 6px 0; }

.markdown-body :deep(strong) {
  font-weight: 600;
  color: var(--t-text-primary);
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  padding-left: 22px;
  margin: 6px 0;
}
.markdown-body :deep(li) { margin: 3px 0; }

.markdown-body :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 10px 0;
  font-size: 13px;
}
.markdown-body :deep(th),
.markdown-body :deep(td) {
  border: 1px solid var(--t-border-strong);
  padding: 6px 12px;
  text-align: left;
}
.markdown-body :deep(th) {
  background: var(--t-bg-input);
  font-weight: 600;
  color: var(--t-text-primary);
}

.markdown-body :deep(code) {
  background: var(--t-bg-code);
  border-radius: 4px;
  padding: 1px 5px;
  font-family: 'SF Mono', 'Monaco', 'Menlo', monospace;
  font-size: 12px;
  color: var(--t-brand);
}
.markdown-body :deep(pre) {
  background: var(--t-bg-code);
  border-radius: 6px;
  padding: 12px 14px;
  overflow-x: auto;
  margin: 8px 0;
  border: 1px solid var(--t-border-subtle);
}
.markdown-body :deep(pre code) {
  background: none;
  padding: 0;
  color: var(--t-text-primary);
}
.markdown-body :deep(hr) {
  border: none;
  border-top: 1px solid var(--t-border-subtle);
  margin: 12px 0;
}
.markdown-body :deep(blockquote) {
  border-left: 3px solid var(--t-brand);
  padding-left: 12px;
  margin: 6px 0;
  color: var(--t-text-secondary);
}

/* ---- 思考过程卡片（可折叠） ---- */
.msg-thinking-card {
  border: 1px solid var(--t-border-subtle);
  border-radius: var(--t-radius-sm);
  overflow: hidden;
  margin: 4px 0;
  background: var(--t-bg-panel);
}

.thinking-card-header {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 7px 12px;
  cursor: pointer;
  user-select: none;
  transition: background 0.15s;
}
.thinking-card-header:hover {
  background: var(--t-bg-panel-hover);
}

.thinking-card-icon {
  width: 14px;
  height: 14px;
  color: var(--t-text-muted);
  flex-shrink: 0;
}

.thinking-card-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--t-text-secondary);
}

.thinking-card-chars {
  font-size: 11px;
  color: var(--t-text-muted);
  margin-left: 2px;
}

.thinking-card-chevron {
  width: 14px;
  height: 14px;
  color: var(--t-text-muted);
  margin-left: auto;
  transition: transform 0.2s;
  flex-shrink: 0;
}
.thinking-card-chevron.rotated {
  transform: rotate(180deg);
}

.thinking-card-body {
  padding: 10px 14px 12px;
  border-top: 1px solid var(--t-border-subtle);
  background: var(--t-bg-subtle);
}

.thinking-text {
  font-size: 13px;
  line-height: 1.65;
  color: var(--t-text-secondary);
  display: block;
}

.thinking-cursor {
  animation: blink 1s step-end infinite;
  color: var(--t-brand);
}
@keyframes blink { 50% { opacity: 0; } }

/* ---- 状态消息 ---- */
/* 进行中状态文字 */
.msg-status {
  font-size: 12px;
  color: var(--t-text-muted);
  padding: 1px 0;
  line-height: 1.5;
}
.status-dot { display: none; }
.status-content {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  word-break: break-all;
}

/* 步骤完成 badge 芯片 */
.msg-step-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 10px 3px 6px;
  border-radius: 20px;
  background: var(--t-success-subtle);
  color: var(--t-success);
  font-size: 12px;
  font-weight: 500;
  margin: 1px 0;
}
.step-badge-icon {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
}

/* ---- 工具调用行（含可折叠结果） ---- */
.msg-tool-row {
  border: 1px solid var(--t-border-subtle);
  border-radius: 6px;
  background: var(--t-bg-input);
  overflow: hidden;
  margin: 1px 0;
  display: inline-flex;
  flex-direction: column;
  max-width: 100%;
}
.tool-row-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
}
.msg-tool-row.has-result .tool-row-header {
  cursor: pointer;
}
.msg-tool-row.has-result .tool-row-header:hover {
  background: var(--t-bg-panel-hover);
}
.tool-row-text {
  font-size: 12px;
  color: var(--t-text-secondary);
  font-family: 'SF Mono', 'Monaco', 'Menlo', monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}
.tool-row-chevron {
  width: 13px;
  height: 13px;
  color: var(--t-text-muted);
  flex-shrink: 0;
  transition: transform 0.2s;
}
.tool-row-chevron.rotated {
  transform: rotate(180deg);
}
.tool-row-result {
  border-top: 1px solid var(--t-border-subtle);
  background: var(--t-bg-code);
  padding: 8px 12px;
  max-height: 200px;
  overflow: auto;
}
.tool-row-result pre {
  margin: 0;
  font-size: 11px;
  line-height: 1.55;
  font-family: 'SF Mono', 'Monaco', 'Menlo', monospace;
  color: var(--t-text-secondary);
  white-space: pre-wrap;
  word-break: break-all;
}

/* ---- 文件卡片（写入 / 编辑） ---- */
.msg-file-card {
  border: 1px solid var(--t-border-subtle);
  border-radius: var(--t-radius-sm);
  overflow: hidden;
  margin: 4px 0;
  background: var(--t-bg-panel);
  box-shadow: var(--t-shadow-sm);
}

.file-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 12px;
  cursor: pointer;
  font-size: 12px;
  font-family: 'SF Mono', 'Monaco', 'Menlo', monospace;
  transition: background 0.15s;
  background: var(--t-bg-panel);
}
.file-card-header:hover {
  background: var(--t-bg-panel-hover);
}

.file-card-op {
  font-weight: 700;
  font-size: 13px;
  width: 14px;
  text-align: center;
  flex-shrink: 0;
}
.file-card-op--new { color: var(--t-success); }
.file-card-op--edit { color: var(--t-warning); }

.file-card-name {
  flex: 1;
  color: var(--t-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-card-badge {
  font-size: 10px;
  font-weight: 500;
  padding: 2px 7px;
  border-radius: 10px;
  flex-shrink: 0;
}
.file-card-badge--new {
  background: var(--t-success-subtle);
  color: var(--t-success);
}
.file-card-badge--edit {
  background: var(--t-warning-subtle);
  color: var(--t-warning);
}

.file-card-chevron {
  width: 14px;
  height: 14px;
  color: var(--t-text-muted);
  flex-shrink: 0;
  transition: transform 0.2s;
}
.file-card-chevron.rotated {
  transform: rotate(180deg);
}

.file-card-code {
  border-top: 1px solid var(--t-border-subtle);
  max-height: 300px;
  overflow: auto;
  background: var(--t-bg-code);
}
.file-card-code pre {
  margin: 0;
  padding: 12px;
  font-size: 12px;
  line-height: 1.5;
  font-family: 'SF Mono', 'Monaco', 'Menlo', monospace;
  color: var(--t-text-primary);
  white-space: pre;
  overflow-x: auto;
}

/* ---- 命令执行卡片 ---- */
.msg-command-card {
  border: 1px solid var(--t-border-subtle);
  border-radius: 6px;
  overflow: hidden;
  margin: 2px 0;
  background: var(--t-bg-code);
}
.command-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 12px;
  font-size: 12px;
  font-family: 'SF Mono', 'Monaco', 'Menlo', monospace;
}
.command-prompt {
  color: var(--t-success);
  font-weight: 700;
  flex-shrink: 0;
}
.command-text {
  color: var(--t-text-secondary);
  word-break: break-all;
}
.command-output {
  margin: 0;
  padding: 6px 12px 8px 28px;
  font-size: 11px;
  line-height: 1.5;
  font-family: 'SF Mono', 'Monaco', 'Menlo', monospace;
  color: var(--t-text-muted);
  border-top: 1px solid var(--t-border-subtle);
  white-space: pre-wrap;
  word-break: break-word;
  overflow-x: auto;
}

/* ---- 错误行 ---- */
.msg-error-row {
  display: inline-flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 14px 8px 10px;
  border-radius: 10px;
  background: rgba(239, 68, 68, 0.07);
  color: var(--t-danger);
  font-size: 12.5px;
  margin: 2px 0;
  max-width: 100%;
}
.error-row-icon {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
  align-self: center;
}
.error-row-text {
  line-height: 1.6;
  word-break: break-word;
}

/* ---- 流式加载指示器 ---- */
.stream-loading {
  height: 2px;
  background: var(--t-border-subtle);
  border-radius: 2px;
  overflow: hidden;
  margin: 10px 4px 4px;
  position: relative;
}
.stream-dot {
  display: none;
}
.stream-loading::after {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  width: 35%;
  background: var(--t-brand);
  border-radius: 2px;
  animation: loadingSlide 1.6s infinite ease-in-out;
}
@keyframes loadingSlide {
  0%   { left: -35%; }
  100% { left: 100%; }
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
  padding: 10px 16px 14px;
  border-top: 1px solid var(--t-border-subtle);
  background: var(--t-bg-base);
}
.chat-input-wrapper {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  background: var(--t-bg-panel);
  border: 1px solid var(--t-border-strong);
  border-radius: 14px;
  padding: 6px 8px;
  transition: border-color 0.2s, box-shadow 0.2s;
  box-shadow: var(--t-shadow-sm);
}
.chat-input-wrapper:focus-within {
  border-color: var(--t-brand);
  box-shadow: 0 0 0 3px var(--t-brand-subtle);
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

/* ============ Landing-style Hero（精简版：减重 + 节奏统一） ============ */
.coding-landing-hero {
  position: relative;
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 8px 16px 4px;
  flex-shrink: 0;
}

/* 装饰性背景去掉，避免和下方 dashboard 冲突 */
.coding-landing-bg {
  display: none;
}

.brand-mark {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}

.brand-glyph {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  background: linear-gradient(135deg, var(--landing-mode-color), var(--landing-mode-ink));
  color: #fff;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 16px;
  font-weight: 700;
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.10), 0 0 0 1px rgba(15, 23, 42, 0.08);
}

.brand-eyebrow {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 10px;
  line-height: 1;
  color: var(--landing-mode-ink);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  opacity: 0.78;
}

.brand-copy {
  max-width: 640px;
  text-align: center;
}

.brand-title {
  margin: 0;
  font-size: 22px;
  line-height: 1.2;
  font-weight: 650;
  letter-spacing: -0.005em;
  color: var(--landing-mode-color);
  display: inline-flex;
  align-items: center;
  gap: 10px;
  justify-content: center;
}

.brand-glyph-inline {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  display: inline-grid;
  place-items: center;
  background: linear-gradient(135deg, var(--landing-mode-color), var(--landing-mode-ink));
  color: #fff;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 13px;
  font-weight: 700;
  line-height: 1;
  flex-shrink: 0;
}

.brand-sub {
  margin: 8px auto 0;
  max-width: 520px;
  color: var(--t-text-secondary);
  font-size: 13px;
  line-height: 1.55;
}

.composer {
  width: 100%;
  max-width: 720px;
}

.composer-shell {
  position: relative;
  overflow: hidden;
  border-radius: 10px;
  border: 1px solid var(--t-border-subtle);
  background: var(--t-bg-panel);
  box-shadow: var(--t-shadow-sm);
  transition: box-shadow 0.18s ease, border-color 0.18s ease;
}

.composer-shell:focus-within {
  border-color: color-mix(in srgb, var(--landing-mode-color) 38%, #d1d8e5);
  box-shadow: 0 8px 22px rgba(15, 23, 42, 0.06), 0 0 0 3px color-mix(in srgb, var(--landing-mode-color) 12%, transparent);
}

/* 去掉装饰性圆点底纹 */
.ai-surface::before {
  display: none;
}

.composer-mode-bar {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 12px;
  border-bottom: 1px solid var(--t-border-subtle);
  background: var(--t-bg-input);
  color: var(--t-text-secondary);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 10px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.composer-mode-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
}

.composer-mode-label > span:first-child {
  display: inline-flex;
  width: 16px;
  align-items: center;
  justify-content: center;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
}

.composer-attachment {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px 0;
}

.composer-attachment-thumb {
  position: relative;
  width: 60px;
  height: 60px;
  border-radius: 6px;
  overflow: hidden;
  border: 0.5px solid #d8dee8;
}

.composer-attachment-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.composer-attachment-file {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border-radius: 6px;
  border: 0.5px solid #d8dee8;
  background: #f8fafc;
  font-size: 12px;
  color: #667085;
}

.composer-attachment-file-icon {
  font-size: 14px;
}

.composer-attachment-file-name {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.composer-attachment-remove {
  width: 18px;
  height: 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 50%;
  background: rgba(15, 23, 42, 0.55);
  color: #fff;
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
}

.composer-attachment-thumb .composer-attachment-remove {
  position: absolute;
  top: 2px;
  right: 2px;
}

.composer-body {
  position: relative;
  z-index: 1;
  padding: 14px 16px 10px;
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

.chip:hover:not(:disabled) {
  background: #f1f4f9;
  color: #111827;
}

.chip:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.composer-model-chip {
  max-width: 280px;
}

.composer-model-chip > span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 240px;
}

.composer-model-chip.is-open {
  border-color: var(--landing-mode-color);
  color: var(--landing-mode-ink);
}

.toolbar-spacer {
  flex: 1;
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

.submit-kbd {
  display: inline-flex;
  min-width: 16px;
  align-items: center;
  justify-content: center;
  padding: 0 5px;
  border-radius: 3px;
  border: 0.5px solid rgba(255, 255, 255, 0.18);
  background: rgba(0, 0, 0, 0.18);
  color: #fff;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 9px;
  line-height: 14px;
}

.composer-submit-spinner {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  border: 1.5px solid rgba(255, 255, 255, 0.5);
  border-top-color: #fff;
  animation: composer-submit-spin 0.7s linear infinite;
}

@keyframes composer-submit-spin {
  to { transform: rotate(360deg); }
}
</style>

<style>
html[data-theme="dark"] .coding-page,
html[data-theme="dark"] .coding-body,
html[data-theme="dark"] .main-content,
html[data-theme="dark"] .welcome-pane,
html[data-theme="dark"] .stream-pane,
html[data-theme="dark"] .stream-messages,
html[data-theme="dark"] .ide-loading-overlay {
  background: #090b10 !important;
  color: rgba(248, 250, 252, 0.94) !important;
}

html[data-theme="dark"] .coding-header,
html[data-theme="dark"] .content-view-toggle-bar,
html[data-theme="dark"] .workspace-sidebar,
html[data-theme="dark"] .embedded-panel,
html[data-theme="dark"] .chat-input-bar {
  background: #0d1117 !important;
  border-color: rgba(148, 163, 184, 0.14) !important;
  box-shadow: none !important;
}

html[data-theme="dark"] .welcome-pane {
  background:
    radial-gradient(circle at top, rgba(124, 140, 255, 0.16), transparent 34%),
    linear-gradient(180deg, #090b10 0%, #0d1117 100%) !important;
}

html[data-theme="dark"] .welcome-title {
  background: linear-gradient(135deg, #a5b4fc, #f8fafc);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

html[data-theme="dark"] .welcome-desc,
html[data-theme="dark"] .coding-model-tip,
html[data-theme="dark"] .workspace-card-meta,
html[data-theme="dark"] .creating-text,
html[data-theme="dark"] .stream-actions-hint,
html[data-theme="dark"] .ide-loading-content {
  color: rgba(203, 213, 225, 0.68) !important;
}

html[data-theme="dark"] .view-toggle,
html[data-theme="dark"] .toggle-bar-back-btn,
html[data-theme="dark"] .header-btn,
html[data-theme="dark"] .coding-model-trigger,
html[data-theme="dark"] .input-wrapper,
html[data-theme="dark"] .attach-btn,
html[data-theme="dark"] .scene-suggestion-card,
html[data-theme="dark"] .workspace-card,
html[data-theme="dark"] .workspace-showcase-empty,
html[data-theme="dark"] .workspace-card-action,
html[data-theme="dark"] .chat-input-wrapper,
html[data-theme="dark"] .attachment-preview,
html[data-theme="dark"] .msg-ai-message,
html[data-theme="dark"] .msg-thinking-card,
html[data-theme="dark"] .msg-file-card,
html[data-theme="dark"] .msg-command-card,
html[data-theme="dark"] .msg-tool-row {
  background: #111318 !important;
  border-color: rgba(148, 163, 184, 0.14) !important;
  color: rgba(203, 213, 225, 0.72) !important;
  box-shadow: none !important;
}

html[data-theme="dark"] .input-wrapper:focus-within,
html[data-theme="dark"] .chat-input-wrapper:focus-within,
html[data-theme="dark"] .coding-model-trigger:hover:not(:disabled),
html[data-theme="dark"] .coding-model-trigger.is-open {
  border-color: rgba(124, 140, 255, 0.36) !important;
  box-shadow: 0 0 0 3px rgba(124, 140, 255, 0.12) !important;
}

html[data-theme="dark"] .composer-topline,
html[data-theme="dark"] .workspace-card-footer,
html[data-theme="dark"] .stream-actions,
html[data-theme="dark"] .thinking-card-body,
html[data-theme="dark"] .file-card-code,
html[data-theme="dark"] .command-output,
html[data-theme="dark"] .tool-row-result {
  background: #0d1117 !important;
  border-color: rgba(148, 163, 184, 0.14) !important;
}

html[data-theme="dark"] .coding-model-trigger-name,
html[data-theme="dark"] .coding-model-panel-option-name,
html[data-theme="dark"] .workspace-showcase-title,
html[data-theme="dark"] .workspace-card-name,
html[data-theme="dark"] .file-card-name,
html[data-theme="dark"] .ai-message-body.markdown-body,
html[data-theme="dark"] .markdown-body :is(h1, h2, h3, strong),
html[data-theme="dark"] .chat-input-wrapper .chat-input .el-textarea__inner,
html[data-theme="dark"] .input-wrapper .el-textarea__inner {
  color: rgba(248, 250, 252, 0.94) !important;
}

html[data-theme="dark"] .input-wrapper .el-textarea__inner::placeholder,
html[data-theme="dark"] .chat-input-wrapper .chat-input .el-textarea__inner::placeholder {
  color: rgba(148, 163, 184, 0.56) !important;
}

html[data-theme="dark"] .coding-model-trigger-meta,
html[data-theme="dark"] .coding-model-panel-option-meta,
html[data-theme="dark"] .thinking-text,
html[data-theme="dark"] .command-text,
html[data-theme="dark"] .command-output,
html[data-theme="dark"] .tool-row-text,
html[data-theme="dark"] .tool-row-result pre {
  color: rgba(203, 213, 225, 0.66) !important;
}

html[data-theme="dark"] .scene-tab,
html[data-theme="dark"] .workspace-card-code,
html[data-theme="dark"] .workspace-card-type,
html[data-theme="dark"] .file-card-badge,
html[data-theme="dark"] .sidebar-group-count {
  background: rgba(148, 163, 184, 0.10) !important;
  border-color: rgba(148, 163, 184, 0.14) !important;
  color: rgba(203, 213, 225, 0.72) !important;
}

html[data-theme="dark"] .scene-tab.active,
html[data-theme="dark"] .view-toggle-btn.active,
html[data-theme="dark"] .workspace-card-action-primary,
html[data-theme="dark"] .coding-model-panel-option.is-active {
  background: rgba(124, 140, 255, 0.14) !important;
  border-color: rgba(124, 140, 255, 0.30) !important;
  color: #b6c2ff !important;
}

html[data-theme="dark"] .scene-suggestion-card:hover,
html[data-theme="dark"] .workspace-card:hover,
html[data-theme="dark"] .workspace-card-action:hover,
html[data-theme="dark"] .coding-model-panel-option:hover {
  background: #1a1d24 !important;
  border-color: rgba(124, 140, 255, 0.26) !important;
  color: rgba(248, 250, 252, 0.92) !important;
}

html[data-theme="dark"] .send-btn:disabled {
  background: #1a1d24 !important;
  color: rgba(148, 163, 184, 0.58) !important;
  opacity: 0.72 !important;
}

html[data-theme="dark"] .workspace-card-action-danger:hover,
html[data-theme="dark"] .msg-error-row {
  background: rgba(248, 113, 113, 0.12) !important;
  border-color: rgba(248, 113, 113, 0.22) !important;
  color: #fca5a5 !important;
}

html[data-theme="dark"] .coding-model-popover.el-popover.el-popper {
  background: #111318 !important;
  border-color: rgba(148, 163, 184, 0.16) !important;
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.52) !important;
}
</style>
