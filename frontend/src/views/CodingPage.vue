<template>
  <BuilderFrame :breadcrumbs="[]" :class="{ 'is-embedded': embedMode }">
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
      <SessionSidebar
        v-if="!embedMode && !embeddedAppId"
        module-name="AI 编码"
        brand-color="#6366f1"
        :sessions="sidebarCodingItems"
        :active-id="sidebarCodingActiveId"
        :new-label="'+ 新建组件'"
        collapse-key="coding:aside-collapsed"
        :empty-hint="'还没有组件，点上面新建一个'"
        @select="onSidebarCodingSelect"
        @create="onSidebarCodingCreate"
        @delete="onSidebarCodingDelete"
        :enable-rename="false"
      />
      <!-- Main Content: 对话流 (B 重构 2026-05-17): 合并 Welcome / Chat / IDE -->
      <div class="main-content">
        <!-- 顶右工具抽屉按钮 (替代 view-toggle-bar): 文件 / IDE / 编辑 -->
        <div
          v-if="!embeddedAppId && (ideUrl || streamMessages.length > 0)"
          class="canvas-actions"
        >
          <button class="canvas-actions-back" @click="startNewWorkspace" title="返回首页">
            <el-icon :size="14"><ArrowLeft /></el-icon>
            <span>返回</span>
          </button>
          <div class="canvas-actions-right">
            <button class="canvas-action-btn" @click="filesDrawerOpen = true" title="文件">
              <span>📋</span>
              <span class="canvas-action-label">文件</span>
            </button>
            <button
              class="canvas-action-btn"
              :class="{ disabled: !canOpenIdeView }"
              :disabled="!canOpenIdeView"
              :title="webIdeUnavailable ? '当前环境未配置 Web IDE' : 'IDE 编辑器'"
              @click="openIdeDrawer"
            >
              <el-icon :size="13"><Monitor /></el-icon>
              <span class="canvas-action-label">IDE</span>
            </button>
            <button class="canvas-action-btn" @click="editDrawerOpen = true" title="设置">
              <span>⚙️</span>
              <span class="canvas-action-label">设置</span>
            </button>
            <button
              class="canvas-action-btn"
              :class="{ active: showCodingArtifactPanel }"
              @click="toggleCodingArtifactPanel"
              :title="showCodingArtifactPanel ? '隐藏产物面板' : '查看产物 / 接入说明'"
            >
              <span>📦</span>
              <span class="canvas-action-label">产物</span>
              <span v-if="codingArtifactsHasAny" class="cap-count-pill">{{ codingArtifacts.new.length + codingArtifacts.modified.length }}</span>
            </button>
          </div>
        </div>

        <!-- Welcome State (Codex-like command center) - 2026-05-17 B 重构：
             去掉 ideUrl 阻塞 + 加 !codingStore.workspace 兜底（选了 ws 后即使 streamMessages 空也要进 chat 视图，
             不再 Welcome 永远显示 regression） -->
        <div v-if="!isStreaming && streamMessages.length === 0 && !codingStore.workspace" class="welcome-pane">
          <div class="welcome-inner" :style="codingLandingVars">

            <section class="qc-section coding-command-center">
              <input
                ref="fileInputRef"
                type="file"
                accept=".md,.pdf,.docx,.txt,.png,.jpg,.jpeg"
                style="display: none"
                @change="handleFileSelect"
              />

              <div class="coding-command-copy">
                <p class="coding-command-kicker">睿鲸AI CODING</p>
                <h1 class="coding-command-title">你想开发什么？</h1>
                <p class="coding-command-subtitle">描述组件、页面、接口或脚本，AI 会先形成开发任务，再创建工作区。</p>
              </div>

              <div class="qc-shell ai-surface">
                <div class="qc-row" @paste="handlePaste">
                  <textarea
                    v-model="userInput"
                    class="qc-input"
                    :placeholder="`问 AI 开发一个 ${activeSceneCategoryLabel}，例如：项目总览分析页面…`"
                    rows="1"
                    @keydown.enter.exact.prevent="sendMessage"
                    @keydown.meta.enter.prevent="sendMessage"
                    @keydown.ctrl.enter.prevent="sendMessage"
                    :disabled="isCreating"
                  ></textarea>
                  <button
                    type="button"
                    class="qc-submit"
                    :disabled="(!userInput.trim() && !attachedFile) || isCreating"
                    @click="sendMessage"
                    title="进入开发 (Enter)"
                  >
                    <span v-if="!isCreating && !isUploading" class="qc-submit-arrow">↗</span>
                    <span v-else class="composer-submit-spinner" />
                  </button>
                </div>

                <!-- 附件预览 -->
                <div v-if="attachedFile" class="qc-attach">
                  <div v-if="attachedPreviewUrl" class="qc-attach-thumb">
                    <img :src="attachedPreviewUrl" alt="preview" />
                    <button class="qc-attach-remove" @click="removeAttachment">&times;</button>
                  </div>
                  <div v-else class="qc-attach-file">
                    <span class="qc-attach-icon">&#128196;</span>
                    <span class="qc-attach-name">{{ attachedFile.name }}</span>
                    <button class="qc-attach-remove" @click="removeAttachment">&times;</button>
                  </div>
                </div>

                <!-- Toolbar：附件 + 类型 + 模型 -->
                <div class="qc-toolbar">
                  <button
                    type="button"
                    class="qc-chip qc-icon-only"
                    @click="fileInputRef?.click()"
                    :disabled="isCreating"
                    title="附加文件"
                  >📎</button>

                  <!-- 2026-05-17 C 改造: 删项目类型 chip (默认 PC 组件，agent 看 prompt 自动推断) -->

                  <!-- 模型选择 -->
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
                        class="qc-chip"
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

                  <div class="qc-spacer"></div>

                  <span class="qc-kbd-hint">Enter / ⌘↵</span>
                </div>
              </div>

              <p v-if="topSuggestions.length" class="qc-hints">
                <span class="qc-hints-label">试试</span>
                <template v-for="(s, i) in topSuggestions" :key="s">
                  <button type="button" class="qc-hint-item" @click="sendSuggestion(s)">{{ s }}</button>
                  <span v-if="i < topSuggestions.length - 1" class="qc-hint-sep">·</span>
                </template>
              </p>
            </section>

            <div class="workspace-showcase">
              <div class="workspace-showcase-header">
                <div>
                  <h3 class="workspace-showcase-title">已开发组件</h3>
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
                暂无已开发组件。先描述一个开发需求，我们会创建工作区并保留交付记录。
              </div>
            </div>
          </div>
        </div>

        <!-- Stream Pane (对话流视图 - 2026-05-17 B 重构：永远显示，IDE/文件改抽屉) -->
        <div v-else class="stream-pane">
          <AgentConversation
            :messages="agentMessages"
            :typing="isStreaming"
            empty-title=""
            empty-hint=""
          >
            <template #custom="{ message }">
              <template v-if="streamCustom(message)?.sm">
                <!-- thinking -->
                <template v-if="streamCustom(message).sm.type === 'thinking'">
                  <div class="msg-thinking-card" :class="{ 'is-collapsed': streamCustom(message).sm.collapsed }">
                    <div class="thinking-card-header" @click="streamCustom(message).sm.collapsed = !streamCustom(message).sm.collapsed">
                      <svg class="thinking-card-icon" viewBox="0 0 16 16" fill="none">
                        <circle cx="8" cy="8" r="6.5" stroke="currentColor" stroke-width="1.2"/>
                        <path d="M8 5v3.5l2 1.5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>
                      </svg>
                      <span class="thinking-card-label">思考过程</span>
                      <span class="thinking-card-chars">{{ streamCustom(message).sm.content.length }} 字</span>
                      <svg class="thinking-card-chevron" :class="{ rotated: !streamCustom(message).sm.collapsed }" viewBox="0 0 16 16" fill="none">
                        <path d="M4 6l4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                      </svg>
                    </div>
                    <div v-show="!streamCustom(message).sm.collapsed" class="thinking-card-body">
                      <span class="thinking-text markdown-body" v-html="renderMarkdown(streamCustom(message).sm.content)"></span>
                      <span v-if="streamCustom(message).isLast && isStreaming" class="thinking-cursor">|</span>
                    </div>
                  </div>
                </template>
                <!-- status -->
                <template v-else-if="streamCustom(message).sm.type === 'status'">
                  <div v-if="streamCustom(message).sm.stepDone" class="msg-step-badge">
                    <svg class="step-badge-icon" viewBox="0 0 16 16" fill="none">
                      <circle cx="8" cy="8" r="7" fill="currentColor" opacity="0.15"/>
                      <path d="M5 8l2.5 2.5L11 5.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                    <span>{{ streamCustom(message).sm.content }}</span>
                  </div>
                  <div v-else class="msg-status" :class="{ 'status-progress': streamCustom(message).sm.content.endsWith('...') }">
                    <span class="status-content">{{ streamCustom(message).sm.content }}</span>
                  </div>
                </template>
                <!-- file_write / file_edit -->
                <template v-else-if="['file_write', 'file_edit'].includes(streamCustom(message).sm.type)">
                  <FileCard
                    :action="streamCustom(message).sm.type === 'file_write' ? 'write' : 'edit'"
                    :file-name="streamCustom(message).sm.fileName"
                    :file-content="streamCustom(message).sm.fileContent"
                    :collapsed="streamCustom(message).sm.collapsed"
                    @toggle="streamCustom(message).sm.collapsed = !streamCustom(message).sm.collapsed"
                  />
                </template>
                <!-- tool -->
                <template v-else-if="streamCustom(message).sm.type === 'tool'">
                  <div class="msg-tool-row" :class="{ 'has-result': streamCustom(message).sm.result }">
                    <div class="tool-row-header" @click="streamCustom(message).sm.result && (streamCustom(message).sm.resultCollapsed = !streamCustom(message).sm.resultCollapsed)">
                      <span class="tool-row-text">{{ streamCustom(message).sm.content }}</span>
                      <svg v-if="streamCustom(message).sm.result" class="tool-row-chevron" :class="{ rotated: !streamCustom(message).sm.resultCollapsed }" viewBox="0 0 16 16" fill="none">
                        <path d="M4 6l4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                      </svg>
                    </div>
                    <div v-if="streamCustom(message).sm.result && !streamCustom(message).sm.resultCollapsed" class="tool-row-result">
                      <pre>{{ streamCustom(message).sm.result }}</pre>
                    </div>
                  </div>
                </template>
                <!-- command -->
                <template v-else-if="streamCustom(message).sm.type === 'command'">
                  <div class="msg-command-card">
                    <div class="command-card-header">
                      <span class="command-prompt">$</span>
                      <span class="command-text">{{ streamCustom(message).sm.content.split('\n')[0] }}</span>
                    </div>
                    <pre v-if="streamCustom(message).sm.content.includes('\n')" class="command-output">{{ streamCustom(message).sm.content.split('\n').slice(1).join('\n') }}</pre>
                  </div>
                </template>
              </template>
            </template>

            <template #list-suffix>
              <div v-if="!isStreaming && pendingIdeUrl" class="stream-actions">
                <button class="open-ide-btn" @click="openPendingIde">
                  <span class="ide-btn-icon">&#x1F4BB;</span>
                  打开代码编辑器
                </button>
                <span class="stream-actions-hint">在编辑器中查看和修改 AI 生成的代码</span>
              </div>
            </template>
          </AgentConversation>

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
              <VoiceInputButton v-model="userInput" :llm-config-id="selectedCodingModelOption?.id ?? null" />
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

      </div>

      <!-- 2026-05-17 B 重构：IDE iframe 全屏抽屉 (size=100% 用户拍板 — 80% 露左 NavRail 干扰)
           Element Plus 2.x 砍掉 custom-class，用 body-class 直接打类到 .el-drawer__body —
           append-to-body=true teleport 到 body 后 scoped CSS 失效，必须配合 <style>（非 scoped）规则。 -->
      <el-drawer
        v-model="ideDrawerOpen"
        title="IDE 编辑器"
        direction="rtl"
        size="100%"
        body-class="coding-ide-drawer-body"
        :append-to-body="true"
        :destroy-on-close="false"
      >
        <div class="ide-pane">
          <iframe
            v-if="ideUrl"
            :key="ideUrl"
            :src="ideUrl"
            class="ide-frame"
            allow="clipboard-read; clipboard-write"
            @load="onIdeFrameLoad"
            @error="onIdeFrameError"
          ></iframe>
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
      </el-drawer>

      <!-- 文件抽屉：显示 workspace 文件列表 (P0 留 stub，P1 接 ws files API) -->
      <el-drawer v-model="filesDrawerOpen" title="工作区文件" direction="rtl" size="40%" body-class="coding-files-drawer-body" :append-to-body="true">
        <div class="files-drawer-body">
          <p style="color:#999;font-size:13px;padding:16px;">
            📋 文件浏览 MVP — 当前展示 workspace 元信息，详细文件树后续接入。
          </p>
          <div v-if="codingStore.workspace" style="padding:0 16px;">
            <div style="margin-bottom:12px;"><strong>名称：</strong>{{ codingStore.workspace.display_name || codingStore.workspace.name }}</div>
            <div style="margin-bottom:12px;"><strong>类型：</strong>{{ codingStore.workspace.project_type }}</div>
            <div style="margin-bottom:12px;"><strong>关联应用：</strong>{{ codingStore.workspace.apaas_app_name || '-' }}</div>
            <div style="margin-bottom:12px;"><strong>更新时间：</strong>{{ codingStore.workspace.updated_at }}</div>
          </div>
          <div v-else style="padding:16px;color:#999;">还没有打开工作区</div>
        </div>
      </el-drawer>

      <!-- 设置抽屉：workspace 操作 (删除 / 同步 / 下载等) -->
      <el-drawer v-model="editDrawerOpen" title="工作区设置" direction="rtl" size="40%" body-class="coding-edit-drawer-body" :append-to-body="true">
        <div class="edit-drawer-body" style="padding:16px;display:flex;flex-direction:column;gap:12px;">
          <button v-if="codingStore.workspace" class="canvas-action-btn" :disabled="isDownloading" @click="downloadCode">
            <el-icon :size="14"><Download /></el-icon>
            <span>下载源码 zip</span>
          </button>
          <button
            v-if="codingStore.workspace && currentAppGitRepoUrl"
            class="canvas-action-btn"
            :disabled="syncingToRepo"
            @click="onSyncToRepo"
          >
            <span>{{ syncingToRepo ? '同步中...' : 'Sync 到关联 Git 仓库' }}</span>
          </button>
          <button
            v-if="codingStore.workspace && canDeleteWorkspace(codingStore.workspace)"
            class="canvas-action-btn"
            style="color:#ef4444;"
            @click="deleteCurrentWorkspace"
          >
            <el-icon :size="14"><Delete /></el-icon>
            <span>删除工作区</span>
          </button>
          <div v-if="!codingStore.workspace" style="color:#999;">还没有打开工作区</div>
        </div>
      </el-drawer>

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
              v-if="codingStore.workspace && currentAppGitRepoUrl"
              class="embedded-panel-btn"
              :disabled="syncingToRepo"
              @click="onSyncToRepo"
              :title="syncingToRepo ? 'Syncing...' : 'Sync to repo'"
            >
              <span class="sync-btn-label">{{ syncingToRepo ? 'Syncing...' : 'Sync to repo' }}</span>
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

      <!-- v2 redesign: 右侧产物清单 + 接入说明面板
           替代「不可能实现的实时预览」。低代码自开发组件不支持平台内预览，
           只能通过编译打包 → 发布到组件市场 → 在表单设计器引用的流程上线。 -->
      <aside
        v-if="showCodingArtifactPanel"
        class="coding-artifact-panel"
      >
        <div class="cap-note">
          提示：低代码自开发组件不支持实时预览。生成产物会发布到组件市场，在表单设计器中引用。
        </div>
        <div class="cap-tabs">
          <button
            type="button"
            class="cap-tab"
            :class="{ active: codingArtifactTab === 'files' }"
            @click="codingArtifactTab = 'files'"
          >产物清单</button>
          <button
            type="button"
            class="cap-tab"
            :class="{ active: codingArtifactTab === 'integrate' }"
            @click="codingArtifactTab = 'integrate'"
          >接入说明</button>
        </div>

        <!-- 产物清单 tab -->
        <div v-if="codingArtifactTab === 'files'" class="cap-scroll">
          <template v-if="codingArtifactsHasAny">
            <template v-if="codingArtifacts.new.length > 0">
              <div class="cap-section-head">
                <span class="cap-badge cap-badge-emerald">新增 {{ codingArtifacts.new.length }}</span>
              </div>
              <div
                v-for="(f, idx) in codingArtifacts.new"
                :key="'cn-' + idx + '-' + f.path"
                class="cap-file"
              >
                <span class="cap-file-path" :title="f.path">{{ f.path }}</span>
                <span class="cap-file-size">{{ f.size }}</span>
                <span class="cap-file-diff">
                  <span class="add">+{{ f.diffAdd }}</span>
                  <span v-if="f.diffDel > 0" class="del">-{{ f.diffDel }}</span>
                </span>
                <span v-if="f.writing" class="cap-spinner" aria-hidden="true" />
                <span v-else class="cap-badge cap-badge-new">NEW</span>
              </div>
            </template>
            <template v-if="codingArtifacts.modified.length > 0">
              <div class="cap-section-head">
                <span class="cap-badge cap-badge-amber">修改 {{ codingArtifacts.modified.length }}</span>
              </div>
              <div
                v-for="(f, idx) in codingArtifacts.modified"
                :key="'cm-' + idx + '-' + f.path"
                class="cap-file"
              >
                <span class="cap-file-path" :title="f.path">{{ f.path }}</span>
                <span class="cap-file-size">{{ f.size }}</span>
                <span class="cap-file-diff">
                  <span class="add">+{{ f.diffAdd }}</span>
                  <span v-if="f.diffDel > 0" class="del">-{{ f.diffDel }}</span>
                </span>
                <span v-if="f.writing" class="cap-spinner" aria-hidden="true" />
              </div>
            </template>
          </template>
          <div v-else class="cap-empty">
            <p>暂无产物。</p>
            <p class="cap-empty-hint">在左侧对话区描述需求，AI 会自动写入文件，产物会出现在这里。</p>
          </div>
        </div>

        <!-- 接入说明 tab -->
        <div v-else class="cap-scroll">
          <div class="cap-guide">
            <div class="cap-guide-step">
              <div class="cap-guide-num">1</div>
              <div>
                <div class="cap-guide-title">编译打包</div>
                <div class="cap-guide-desc">
                  运行 <code>npm run build:component</code> 生成 UMD bundle。
                </div>
              </div>
            </div>
            <div class="cap-guide-step">
              <div class="cap-guide-num">2</div>
              <div>
                <div class="cap-guide-title">发布到组件市场</div>
                <div class="cap-guide-desc">
                  通过 CI 流水线发布到当前租户的组件市场，发布后绑定到自开发组件库。
                </div>
              </div>
            </div>
            <div class="cap-guide-step">
              <div class="cap-guide-num">3</div>
              <div>
                <div class="cap-guide-title">在表单设计器中引用</div>
                <div class="cap-guide-desc">
                  在表单设计器的「自开发组件」面板中按 <code>code</code> 引用。
                </div>
              </div>
            </div>
          </div>
        </div>
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
import type { WorkspaceInfo, ReplayStreamMessage } from '@/api/coding'
import { gitConnectionApi } from '@/api/gitConnection'
import { applicationApi } from '@/api/application'
import { useThemeStore } from '@/stores/theme'
import BuilderFrame from '@/components/BuilderFrame.vue'
import EnvSelectModal from '@/components/EnvSelectModal.vue'
import FileCard from '@/components/FileCard.vue'
import SessionSidebar, { type SessionItem as SidebarSessionItem } from '@/components/common/SessionSidebar.vue'
import AgentConversation from '@/components/common/AgentConversation.vue'
import VoiceInputButton from '@/components/common/VoiceInputButton.vue'
import type { AgentMessage } from '@/components/common/agent-conversation/types'
import { useCodingModel } from './coding/useCodingModel'
import { useStreamMessages, renderMarkdown } from './coding/useStreamMessages'
import { useIdeManager } from './coding/useIdeManager'
import { useCodingWorkspace } from './coding/useCodingWorkspace'
import { useCodingPipeline } from './coding/useCodingPipeline'

const route = useRoute()
const router = useRouter()
const codingStore = useCodingStore()

// Embed mode (?embed=true) used by WorkspaceShell CodeView iframe
// (Phase F Task 9): hides nav rail + topbar via .is-embedded CSS hack.
const embedMode = computed(() => route.query.embed === 'true')
const userStore = useUserStore()
const themeStore = useThemeStore()

// ============ Core State ============
const userInput = ref('')
const isCreating = ref(false)

// Code mode uses the same calm blue family as the workbench primary action.
const codingLandingVars: Record<string, string> = {
  '--landing-mode-color': '#6f7ff2',
  '--landing-mode-soft': 'rgba(111, 127, 242, 0.10)',
  '--landing-mode-ink': '#4c5fda',
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

// 2026-05-17 B 重构：抽屉式 IDE / 文件 / 设置 (替代独立 view-toggle)
const ideDrawerOpen = ref(false)
const filesDrawerOpen = ref(false)
const editDrawerOpen = ref(false)

async function openIdeDrawer() {
  // 没 ideUrl 先 fetch (复用 switchToIdeView 老逻辑)，然后弹抽屉
  if (!ideUrl.value && !pendingIdeUrl.value) {
    await switchToIdeView()  // 内部会 set ideUrl
  } else if (pendingIdeUrl.value) {
    await openPendingIde()
  }
  if (ideUrl.value) {
    ideDrawerOpen.value = true
  }
}

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

// ── AgentConversation 公共契约映射（保留 streamMessages 原 reactive 对象，slot 直接引用 meta.streamMsg） ──
const agentMessages = computed<AgentMessage[]>(() => {
  const list = streamMessages.value
  const out: AgentMessage[] = []
  for (let i = 0; i < list.length; i++) {
    const msg = list[i]!
    if (msg.type === 'status' && msg.hidden) continue
    if (msg.type === 'user') {
      out.push({ id: 'sm' + i, kind: 'user', content: msg.content })
    } else if (msg.type === 'message') {
      out.push({ id: 'sm' + i, kind: 'assistant', content: msg.content })
    } else if (msg.type === 'error') {
      out.push({ id: 'sm' + i, kind: 'error', content: msg.content })
    } else {
      // thinking / status / file_write / file_edit / tool / command — 走 #custom slot
      const isLast = i === list.length - 1
      out.push({
        id: 'sm' + i,
        kind: 'custom',
        meta: { streamMsg: msg, isLast },
      })
    }
  }
  return out
})

// 把 AgentMessage.meta 解出 streamMsg + isLast — 给 #custom slot 用（避开 TS 严格检查）
function streamCustom(message: AgentMessage): { sm: any; isLast: boolean } {
  const meta = (message.meta || {}) as { streamMsg?: any; isLast?: boolean }
  return { sm: meta.streamMsg || {}, isLast: !!meta.isLast }
}

// ── v2 redesign: 产物清单 / 接入说明 面板 ──
// 把 streamMessages 里的 file_write / file_edit 整成 new/modified 两组，
// 提供给右侧 CodingArtifactPanel 渲染。最后一条 file_write 在 isStreaming
// 时视为「正在写入」展示 spinner。
const codingArtifactTab = ref<'files' | 'integrate'>('files')

function _formatSize(content: string | undefined | null): string {
  const bytes = content ? new Blob([content]).size : 0
  if (bytes < 1024) return `${bytes} B`
  return `${(bytes / 1024).toFixed(1)} KB`
}

interface CodingArtifactItem {
  path: string
  size: string
  diffAdd: number
  diffDel: number
  writing?: boolean
}

const codingArtifacts = computed<{ new: CodingArtifactItem[]; modified: CodingArtifactItem[]; writingPath: string | null }>(() => {
  const list = streamMessages.value || []
  const newMap = new Map<string, CodingArtifactItem>()
  const modMap = new Map<string, CodingArtifactItem>()
  let writingPath: string | null = null

  for (let i = 0; i < list.length; i++) {
    const m = list[i] as any
    if (!m || (m.type !== 'file_write' && m.type !== 'file_edit')) continue
    const path = (m.fileName || '').trim()
    if (!path) continue
    const content = m.fileContent || ''
    // 粗略 diff：write = 全新增，edit = 行数估算
    const lines = content ? content.split('\n').length : 0
    const item: CodingArtifactItem = {
      path,
      size: _formatSize(content),
      diffAdd: m.type === 'file_write' ? lines : Math.max(1, Math.floor(lines * 0.6)),
      diffDel: m.type === 'file_write' ? 0 : Math.max(0, Math.floor(lines * 0.2)),
    }
    if (m.type === 'file_write') {
      newMap.set(path, item)
    } else {
      // 若 same path 之前是 write，仍归到 new（首次写入优先）
      if (!newMap.has(path)) modMap.set(path, item)
    }
    // 最后一条且仍在 streaming → 当前正在写入
    if (isStreaming.value && i === list.length - 1) {
      writingPath = path
      item.writing = true
    }
  }

  return {
    new: Array.from(newMap.values()),
    modified: Array.from(modMap.values()),
    writingPath,
  }
})

const codingArtifactsHasAny = computed(() =>
  codingArtifacts.value.new.length > 0 || codingArtifacts.value.modified.length > 0
)

// 用户主动 toggle 显示右栏（即使没产物也可以查看接入说明）
const codingArtifactPanelManuallyOpen = ref(false)

// 是否显示产物面板：
// 1) 有产物文件（写入中或写完） → 自动展开
// 2) 正在 streaming → 自动展开（产物随时可能开始出现）
// 3) 用户主动 toggle → 展开
// 否则折叠，让中间 chat 全宽显示，避免空"暂无产物"占地（image #21 vs #22 设计反馈）
const showCodingArtifactPanel = computed(() => {
  if (embeddedAppId.value) return false
  if (codingArtifactsHasAny.value) return true
  if (isStreaming.value) return true
  if (codingArtifactPanelManuallyOpen.value) return true
  return false
})

const toggleCodingArtifactPanel = () => {
  codingArtifactPanelManuallyOpen.value = !codingArtifactPanelManuallyOpen.value
}

// ── 左侧 SessionSidebar 适配 ──
const sidebarCodingItems = computed<SidebarSessionItem[]>(() =>
  (existingWorkspaces.value || []).map((ws: any) => ({
    id: ws.id,
    title: workspaceDisplayName(ws) || ws.id,
    meta: workspaceCodeName(ws) || undefined,
  }))
)
const sidebarCodingActiveId = computed<string | null>(() => codingStore.workspace?.id || null)

async function onSidebarCodingSelect(id: string | number) {
  const wsId = String(id)
  if (sidebarCodingActiveId.value === wsId) return
  if (openingWsId.value) return
  openingWsId.value = wsId
  try {
    await openWorkspaceById(wsId)
  } finally {
    openingWsId.value = null
  }
}
function onSidebarCodingCreate() {
  startNewWorkspace()
}
async function onSidebarCodingDelete(s: SidebarSessionItem) {
  const target = (existingWorkspaces.value || []).find((w: any) => w.id === s.id)
  if (!target) return
  try {
    await ElMessageBox.confirm(`删除组件「${s.title}」吗？该工作区会一并清理。`, '删除组件', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
      confirmButtonClass: 'el-button--danger',
    })
    deletingWsId.value = target.id
    await codingApi.deleteWorkspace(target.id)
    allWorkspaces.value = allWorkspaces.value.filter((w: any) => w.id !== target.id)
    if (codingStore.workspace?.id === target.id) {
      startNewWorkspace()
    }
    ElMessage.success('已删除')
  } catch {
    /* user cancelled */
  } finally {
    deletingWsId.value = null
  }
}

const embeddedPanelCollapsed = ref(false)

// ── Phase D Task 6：Sync workspace → repo ──
const syncingToRepo = ref(false)
const currentAppGitRepoUrl = ref<string | null>(null)

async function loadCurrentAppGitRepo() {
  const appIdRaw = embeddedAppId.value
  if (!appIdRaw) {
    currentAppGitRepoUrl.value = null
    return
  }
  const appId = Number(appIdRaw)
  if (!Number.isFinite(appId)) {
    currentAppGitRepoUrl.value = null
    return
  }
  try {
    const app = await applicationApi.get(appId)
    currentAppGitRepoUrl.value = app?.git_repo_url || null
  } catch {
    currentAppGitRepoUrl.value = null
  }
}

async function onSyncToRepo() {
  const ws = codingStore.workspace
  const appIdRaw = embeddedAppId.value
  if (!ws || !appIdRaw) return
  const appId = Number(appIdRaw)
  if (!Number.isFinite(appId)) {
    ElMessage.error('应用 ID 不合法')
    return
  }
  syncingToRepo.value = true
  try {
    const result = await gitConnectionApi.syncWorkspace(appId, ws.id)
    ElMessage.success(
      `Sync 成功：commit ${result.commit_sha?.slice(0, 7) || '?'} on ${result.branch || '?'}（${result.file_count ?? 0} 个文件）`
    )
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || 'Sync 失败')
  } finally {
    syncingToRepo.value = false
  }
}

watch(() => embeddedAppId.value, () => {
  loadCurrentAppGitRepo()
}, { immediate: true })

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
    const env = connectedEnvs[0]
    if (env) {
      await doUploadWorkspace(ws, env.id)
    }
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

// Workspace-first 重设新增的派生状态
const activeSceneCategoryLabel = computed(() =>
  sceneCategories.find(c => c.key === activeSceneCategory.value)?.label || '组件'
)
const activeSceneCategoryIcon = computed(() =>
  sceneCategories.find(c => c.key === activeSceneCategory.value)?.icon || '🧩'
)
const topSuggestions = computed(() =>
  (sceneSuggestions[activeSceneCategory.value] || []).slice(0, 4)
)
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
      // 打开工作区默认进 chat 视图，IDE 由用户自己切（避免一进来就被 IDE iframe 接管屏幕）
      activeView.value = 'chat'
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
    if (!msg) continue
    const content = msg.content || ''
    if (msg.role === 'assistant' && content.startsWith('<!-- BRAINSTORM_PROPOSAL -->')) {
      // 找到这条 brainstorm 方案前一条 user（原始需求）
      for (let j = i - 1; j >= 0; j--) {
        const previous = messages[j]
        if (previous?.role === 'user') {
          addStreamMsg({ type: 'user', content: previous.content })
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

/* Embed mode (?embed=true): hide topbar so this view can be cleanly
 * iframed by WorkspaceShell (Phase F Task 9). NavRail is hidden via
 * the existing ?embed_nav=0 mechanism passed by the iframe URL. */
.is-embedded :deep(.builder-topbar) {
  display: none !important;
}

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

/* 2026-05-17 B 重构: canvas-actions 替代 content-view-toggle-bar */
.canvas-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px 8px;
  flex-shrink: 0;
  border-bottom: 1px solid var(--t-border-subtle);
  background: var(--t-bg-canvas, transparent);
}

.canvas-actions-back {
  display: flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 12px;
  border: 1px solid var(--t-border-subtle);
  border-radius: 8px;
  background: transparent;
  color: var(--t-text-secondary);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}
.canvas-actions-back:hover {
  background: var(--t-bg-elevated);
  color: var(--t-text-primary);
}

.canvas-actions-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.canvas-action-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 12px;
  border: 1px solid var(--t-border-subtle);
  border-radius: 8px;
  background: transparent;
  color: var(--t-text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.canvas-action-btn:hover:not(:disabled) {
  background: var(--t-bg-elevated);
  color: var(--t-text-primary);
  border-color: var(--t-brand-primary, #646cff);
}
.canvas-action-btn:disabled,
.canvas-action-btn.disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.canvas-action-btn.active {
  background: var(--t-brand-primary-subtle, rgba(91, 91, 214, 0.12));
  color: var(--t-brand-primary, #5b5bd6);
  border-color: var(--t-brand-primary, #5b5bd6);
}
.canvas-action-label {
  line-height: 1;
}
.cap-count-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 6px;
  border-radius: 9px;
  background: var(--t-brand-primary, #5b5bd6);
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  line-height: 1;
}

.toggle-bar-back-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  height: 34px;
  padding: 0 13px;
  border: 1px solid var(--t-border-subtle);
  border-radius: 8px;
  background: transparent;
  color: var(--t-text-secondary);
  font-size: 13px;
  font-weight: 600;
  line-height: 1;
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

.welcome-pane {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  background:
    radial-gradient(circle at 50% 8%, rgba(97, 112, 238, 0.12), transparent 30%),
    linear-gradient(rgba(97, 112, 238, 0.045) 1px, transparent 1px),
    linear-gradient(90deg, rgba(97, 112, 238, 0.045) 1px, transparent 1px),
    #f7f9fd;
  background-size: auto, 26px 26px, 26px 26px, auto;
}

.welcome-inner {
  width: min(100%, 1180px);
  min-height: 100%;
  margin: 0 auto;
  padding: 48px 28px 40px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 26px;
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

@media (max-width: 820px) {
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

/* ============ Quick Composer (Workspace-first 重设) ============ */
.qc-section {
  width: min(100%, 860px);
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
  flex-shrink: 0;
}

.coding-command-center {
  align-items: stretch;
}

.coding-command-copy {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  margin-bottom: 2px;
  text-align: center;
}

.coding-command-kicker {
  margin: 0;
  color: #6f7ff2;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.13em;
  text-transform: uppercase;
}

.coding-command-title {
  margin: 0;
  color: var(--t-text-primary);
  font-size: clamp(30px, 3.2vw, 42px);
  line-height: 1.12;
  font-weight: 760;
  letter-spacing: 0;
}

.coding-command-subtitle {
  margin: 0;
  max-width: 560px;
  color: var(--t-text-secondary);
  font-size: 13px;
  line-height: 1.65;
}

.qc-shell {
  width: 100%;
  border: 1px solid #dbe2ea;
  border-radius: 16px;
  background: #fff;
  overflow: hidden;
  box-shadow: 0 10px 28px rgba(15, 23, 42, 0.05);
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.qc-shell:focus-within {
  border-color: #c7d2fe;
  box-shadow: 0 0 0 3px rgba(111, 127, 242, 0.10);
}

.qc-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 17px 16px 8px 18px;
}

.qc-input {
  flex: 1;
  border: 0;
  outline: 0;
  resize: none;
  background: transparent;
  color: var(--t-text-primary);
  font-size: 15px;
  line-height: 1.55;
  font-family: inherit;
  min-height: 70px;
  max-height: 190px;
  padding: 0;
  font-weight: 500;
}

.qc-input::placeholder {
  color: #8b98ae;
}

.qc-submit {
  flex-shrink: 0;
  width: 42px;
  height: 42px;
  margin-top: 2px;
  border-radius: 12px;
  border: 0;
  background: #111827;
  color: #fff;
  font-size: 18px;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  box-shadow: none;
  transition: opacity 0.15s ease, transform 0.15s ease, background 0.15s ease;
}

.qc-submit:disabled {
  opacity: 0.34;
  cursor: not-allowed;
  box-shadow: none;
}

.qc-submit:not(:disabled):hover {
  transform: translateY(-1px);
  background: #020617;
}

.qc-submit-arrow {
  display: inline-block;
  transform: translate(-1px, 1px);
}

.qc-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 16px 15px 18px;
}

.qc-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 11px;
  border-radius: 10px;
  border: 1px solid #dbe2ea;
  background: #f8fafc;
  color: var(--t-text-secondary);
  font-size: 12px;
  font-weight: 650;
  cursor: pointer;
  transition: all 0.15s ease;
}

.qc-chip:not(:disabled):hover {
  color: var(--t-brand);
  border-color: var(--t-brand);
  background: var(--t-brand-subtle);
}

.qc-chip:disabled {
  opacity: 0.42;
  cursor: not-allowed;
}

.qc-icon-only {
  width: 32px;
  padding: 0;
  justify-content: center;
}

.qc-chip-type {
  font-weight: 500;
}

.qc-spacer {
  flex: 1;
}

.qc-kbd-hint {
  color: var(--t-text-muted);
  font-size: 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.qc-type-panel {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 4px;
}

.qc-type-option {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 7px 10px;
  border: 0;
  background: transparent;
  color: var(--t-text-primary);
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  text-align: left;
  transition: background 0.15s ease;
}

.qc-type-option:hover {
  background: var(--t-bg-panel-hover);
}

.qc-type-option.is-active {
  background: var(--t-brand-subtle);
  color: var(--t-brand);
  font-weight: 600;
}

.qc-attach {
  padding: 0 12px 8px;
}

.qc-attach-thumb {
  position: relative;
  display: inline-block;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--t-border-subtle);
}

.qc-attach-thumb img {
  display: block;
  max-width: 96px;
  max-height: 64px;
  object-fit: cover;
}

.qc-attach-file {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  background: var(--t-bg-input);
  color: var(--t-text-secondary);
  font-size: 12px;
}

.qc-attach-icon {
  font-size: 13px;
}

.qc-attach-name {
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.qc-attach-remove {
  margin-left: 4px;
  width: 18px;
  height: 18px;
  border-radius: 9px;
  border: 0;
  background: rgba(0, 0, 0, 0.06);
  color: inherit;
  cursor: pointer;
  font-size: 12px;
  line-height: 1;
}

.qc-hints {
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-start;
  align-items: center;
  gap: 8px;
  color: var(--t-text-muted);
  font-size: 12px;
  line-height: 1.4;
}

.qc-hints-label {
  flex-shrink: 0;
  margin-right: 2px;
  color: var(--t-text-muted);
  font-weight: 600;
}

.qc-hint-item {
  border: 1px solid #dbe2ea;
  background: #fff;
  color: #61708c;
  font-size: 12px;
  cursor: pointer;
  padding: 5px 9px;
  border-radius: 999px;
  transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease, transform 0.15s ease;
}

.qc-hint-item:hover {
  background: var(--landing-mode-soft);
  border-color: color-mix(in srgb, var(--landing-mode-color) 32%, transparent);
  color: var(--landing-mode-ink);
  transform: translateY(-1px);
}

.qc-hint-sep {
  color: var(--t-text-muted);
  opacity: 0.5;
  user-select: none;
}

@media (max-width: 760px) {
  .welcome-inner {
    padding: 30px 18px 28px;
    gap: 20px;
  }

  .coding-command-title {
    font-size: 30px;
  }

  .qc-section {
    width: 100%;
  }

  .qc-row {
    padding: 18px 14px 8px 16px;
    gap: 10px;
  }

  .qc-input {
    min-height: 86px;
    font-size: 16px;
  }

  .qc-submit {
    width: 42px;
    height: 42px;
    border-radius: 14px;
  }

  .qc-toolbar {
    align-items: flex-start;
    flex-wrap: wrap;
    padding: 0 14px 14px 16px;
  }

  .qc-spacer,
  .qc-kbd-hint {
    display: none;
  }

  .qc-hints {
    justify-content: flex-start;
  }
}

/* ============ Workspace Showcase ============ */
.workspace-showcase {
  width: min(100%, 1040px);
  margin: 2px auto 0;
  padding-top: 22px;
  border-top: 1px solid #dfe4ec;
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
  font-weight: 760;
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
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  width: 100%;
  align-items: stretch;
}

.workspace-card {
  border: 1px solid #dbe2ea;
  border-radius: 14px;
  background: #fff;
  padding: 14px 16px 12px;
  text-align: left;
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
  min-height: 112px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.workspace-card:hover {
  transform: translateY(-1px);
  border-color: #c7d2fe;
  box-shadow: 0 12px 24px rgba(15, 23, 42, 0.05);
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
  font-size: 13px;
  font-weight: 720;
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
  background: #f3f6fb;
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
  background: #f3f6fb;
  color: #647085;
  font-size: 9px;
  font-weight: 600;
  white-space: nowrap;
}

.workspace-card-footer {
  margin-top: auto;
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
  border: 1px solid #dbe2ea;
  background: #f8fafc;
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
  color: #4f6bff;
  border-color: #cfd8ff;
  background: #f4f6ff;
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

  .workspace-cards-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .workspace-catalog-grid {
    grid-template-columns: 1fr;
    gap: 10px;
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
  padding: 10px 15px;
  background: var(--t-brand);
  color: #fff;
  border-radius: 14px 14px 4px 14px;
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
  /* 2026-05-17: 抽屉化后 parent (el-drawer body) 不是 flex container，需绝对 100% 高 */
  width: 100%;
  height: 100%;
  min-height: 0;
}

/* 2026-05-17 IDE 抽屉规则已迁到下方非 scoped <style>：
   append-to-body=true 让 drawer teleport 到 body 外，scoped CSS 触不到。 */
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

/* 去掉装饰性圆点底纹 */
.ai-surface::before {
  display: none;
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

/* ============ v2 redesign: 产物清单 + 接入说明侧板 ============ */
.coding-artifact-panel {
  width: 380px;
  flex-shrink: 0;
  background: var(--surface, #fff);
  border-left: 1px solid var(--border, #e5e5ea);
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}
.cap-note {
  padding: 10px 14px;
  background: var(--ai-soft);
  color: var(--ai-text);
  font-size: 12px;
  border-bottom: 1px solid var(--ai-soft-2);
  line-height: 1.55;
}
.cap-tabs {
  display: flex;
  border-bottom: 1px solid var(--border, #e5e5ea);
  padding: 0 8px;
  flex-shrink: 0;
}
.cap-tab {
  height: 36px;
  padding: 0 12px;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-2, #4f4a6e);
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  font-family: inherit;
  transition: color 0.15s ease, border-color 0.15s ease;
}
.cap-tab:hover {
  color: var(--text, #1a1525);
}
.cap-tab.active {
  color: var(--brand-text);
  border-bottom-color: var(--brand, #6366f1);
}
.cap-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}
.cap-section-head {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--text-3, #837ea0);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  padding: 6px 4px;
  margin-top: 8px;
}
.cap-section-head:first-child {
  margin-top: 0;
}
.cap-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 18px;
  padding: 0 8px;
  border-radius: 9px;
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.02em;
  text-transform: none;
}
.cap-badge-emerald {
  background: var(--emerald-bg, rgba(16, 163, 127, 0.10));
  color: var(--emerald, #10A37F);
}
.cap-badge-amber {
  background: rgba(245, 158, 11, 0.12);
  color: #B45309;
}
.cap-badge-new {
  background: var(--emerald-bg, rgba(16, 163, 127, 0.10));
  color: var(--emerald, #10A37F);
  font-size: 9.5px;
  letter-spacing: 0.05em;
  height: 16px;
  padding: 0 6px;
}
.cap-file {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--surface-2, #FAF9FD);
  margin-bottom: 6px;
  border: 1px solid transparent;
  transition: border-color 0.15s ease;
}
.cap-file:hover {
  border-color: var(--border, #e5e5ea);
}
.cap-file-path {
  flex: 1;
  font-family: var(--d-font-mono, "JetBrains Mono", "SF Mono", "Menlo", "Consolas", monospace);
  font-size: 11.5px;
  color: var(--text, #1a1525);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cap-file-size {
  font-size: 10.5px;
  color: var(--text-3, #837ea0);
  font-family: var(--d-font-mono, monospace);
  flex-shrink: 0;
}
.cap-file-diff {
  font-size: 10.5px;
  font-family: var(--d-font-mono, monospace);
  flex-shrink: 0;
}
.cap-file-diff .add {
  color: var(--emerald, #10A37F);
}
.cap-file-diff .del {
  color: var(--rose, #DC2626);
  margin-left: 4px;
}
.cap-spinner {
  width: 10px;
  height: 10px;
  border: 2px solid var(--brand, #6366f1);
  border-top-color: transparent;
  border-radius: 50%;
  animation: capSpin 0.8s linear infinite;
  flex-shrink: 0;
}
@keyframes capSpin {
  to { transform: rotate(360deg); }
}
.cap-empty {
  text-align: center;
  padding: 40px 16px;
  color: var(--text-3, #837ea0);
  font-size: 12px;
}
.cap-empty p {
  margin: 0;
}
.cap-empty-hint {
  margin-top: 8px !important;
  font-size: 11px;
  line-height: 1.55;
}
.cap-guide {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 4px;
}
.cap-guide-step {
  background: var(--surface-2, #FAF9FD);
  border: 1px solid var(--border, #e5e5ea);
  border-radius: 10px;
  padding: 12px 14px;
  display: flex;
  gap: 10px;
}
.cap-guide-num {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: var(--brand-soft);
  color: var(--brand-text);
  font-size: 11px;
  font-weight: 700;
  display: grid;
  place-items: center;
  flex-shrink: 0;
}
.cap-guide-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text, #1a1525);
}
.cap-guide-desc {
  font-size: 11.5px;
  color: var(--text-2, #4f4a6e);
  margin-top: 4px;
  line-height: 1.55;
}
.cap-guide-desc code {
  font-family: var(--d-font-mono, monospace);
  background: var(--code-bg, #F6F4FB);
  color: var(--code-text, #4F4A6E);
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 11px;
}
</style>

<style>
/* 2026-05-17 IDE / 文件 / 设置抽屉 body padding 0：
   append-to-body=true → 必须用全局（非 scoped）CSS。
   body-class prop 把这些类直接打到 .el-drawer__body 上。 */
.coding-ide-drawer-body,
.coding-files-drawer-body,
.coding-edit-drawer-body {
  padding: 0 !important;
  display: flex !important;
  flex-direction: column;
  overflow: hidden;
}
.coding-ide-drawer-body > .ide-pane,
.coding-ide-drawer-body > .ide-pane > iframe {
  width: 100% !important;
  height: 100% !important;
  flex: 1 1 auto;
  min-height: 0;
  border: 0;
}

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
    radial-gradient(circle at 50% 6%, rgba(88, 105, 255, 0.16), transparent 30%),
    linear-gradient(rgba(124, 140, 255, 0.055) 1px, transparent 1px),
    linear-gradient(90deg, rgba(124, 140, 255, 0.055) 1px, transparent 1px),
    #090b10 !important;
  background-size: auto, 28px 28px, 28px 28px, auto !important;
}

html[data-theme="dark"] .coding-command-kicker {
  color: #9aa8ff !important;
}

html[data-theme="dark"] .coding-command-title {
  color: rgba(255, 255, 255, 0.94) !important;
}

html[data-theme="dark"] .coding-command-subtitle {
  color: rgba(212, 212, 216, 0.66) !important;
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
html[data-theme="dark"] .qc-shell,
html[data-theme="dark"] .qc-chip,
html[data-theme="dark"] .coding-model-trigger,
html[data-theme="dark"] .input-wrapper,
html[data-theme="dark"] .attach-btn,
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

html[data-theme="dark"] .qc-shell {
  background: #111318 !important;
  border-color: rgba(148, 163, 184, 0.14) !important;
  box-shadow: 0 18px 44px rgba(0, 0, 0, 0.22) !important;
}

html[data-theme="dark"] .input-wrapper:focus-within,
html[data-theme="dark"] .chat-input-wrapper:focus-within,
html[data-theme="dark"] .coding-model-trigger:hover:not(:disabled),
html[data-theme="dark"] .coding-model-trigger.is-open {
  border-color: rgba(124, 140, 255, 0.36) !important;
  box-shadow: 0 0 0 3px rgba(124, 140, 255, 0.12) !important;
}

html[data-theme="dark"] .qc-shell:focus-within {
  border-color: rgba(124, 140, 255, 0.36) !important;
  box-shadow:
    0 18px 44px rgba(0, 0, 0, 0.22),
    0 0 0 3px rgba(124, 140, 255, 0.12) !important;
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
html[data-theme="dark"] .qc-input,
html[data-theme="dark"] .chat-input-wrapper .chat-input .el-textarea__inner,
html[data-theme="dark"] .input-wrapper .el-textarea__inner {
  color: rgba(248, 250, 252, 0.94) !important;
}

html[data-theme="dark"] .qc-input::placeholder,
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

html[data-theme="dark"] .workspace-card-code,
html[data-theme="dark"] .workspace-card-type,
html[data-theme="dark"] .file-card-badge,
html[data-theme="dark"] .sidebar-group-count {
  background: rgba(148, 163, 184, 0.10) !important;
  border-color: rgba(148, 163, 184, 0.14) !important;
  color: rgba(203, 213, 225, 0.72) !important;
}

html[data-theme="dark"] .qc-submit {
  background: rgba(244, 244, 245, 0.94) !important;
  color: #111318 !important;
  box-shadow: none !important;
}

html[data-theme="dark"] .qc-submit:not(:disabled):hover {
  background: #ffffff !important;
}

html[data-theme="dark"] .qc-hints-label,
html[data-theme="dark"] .qc-kbd-hint,
html[data-theme="dark"] .qc-hint-sep {
  color: rgba(161, 161, 170, 0.58) !important;
}

html[data-theme="dark"] .qc-hint-item {
  background: transparent !important;
  border-color: transparent !important;
  color: rgba(212, 212, 216, 0.72) !important;
}

html[data-theme="dark"] .qc-hint-item:hover {
  background: rgba(124, 140, 255, 0.12) !important;
  border-color: rgba(124, 140, 255, 0.22) !important;
  color: #dbe3ff !important;
}

html[data-theme="dark"] .view-toggle-btn.active,
html[data-theme="dark"] .workspace-card-action-primary,
html[data-theme="dark"] .coding-model-panel-option.is-active {
  background: rgba(124, 140, 255, 0.14) !important;
  border-color: rgba(124, 140, 255, 0.30) !important;
  color: #b6c2ff !important;
}

html[data-theme="dark"] .msg-user-bubble {
  background: rgba(124, 140, 255, 0.18) !important;
  border: 1px solid rgba(124, 140, 255, 0.30) !important;
  color: rgba(248, 250, 252, 0.94) !important;
  box-shadow: none !important;
}

html[data-theme="dark"] .toggle-bar-back-btn {
  color: rgba(203, 213, 225, 0.74) !important;
  font-weight: 600 !important;
}

html[data-theme="dark"] .workspace-showcase {
  border-top-color: rgba(148, 163, 184, 0.12) !important;
}

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
