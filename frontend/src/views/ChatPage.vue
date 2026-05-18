<template>
  <WorkbenchShell>
  <!-- v2 redesign (Session 5): 3-column shell — left rail + center main + right blueprint.
       Existing chat-page-shell is moved INSIDE <main class="chat-main"> unchanged. -->
  <div class="chat-shell">
    <ChatConversationList
      v-if="!embedMode && !isPostDeploy"
      :conversations="v2ConversationItems"
      :current-id="v2CurrentConversationId"
      @open="onV2OpenConversation"
    />
    <main class="chat-main">
  <div class="chat-page-shell">
    <!-- dolphin 接管对话后 sidebar 跟 /apps 列表重复，整体隐藏 -->
    <SessionSidebar
      v-if="!embedMode && !useDolphinChat"
      module-name="AI 搭建"
      brand-color="#8b5cf6"
      :sessions="sidebarSessionItems"
      :active-id="sidebarActiveAppId"
      :new-label="'+ 新建应用'"
      back-route="/apps"
      back-label="返回应用"
      collapse-key="aibuilder:aside-collapsed"
      :empty-hint="'还没有应用，点上面新建一个'"
      @select="onSidebarSelectApp"
      @create="onSidebarCreateApp"
      @rename="onSidebarRenameApp"
      @delete="onSidebarDeleteApp"
    />
  <div class="chat-page">
    <TopBar v-if="!embedMode" title="" show-back :show-home="false" back-to="/apps">
      <template #center>
        <div class="top-bar-center builder-chat-top-center">
          <div class="builder-chat-crumbs">
            <button type="button" @click="router.push('/apps')">应用</button>
            <span>/</span>
            <span>{{ builderAppDisplayName || '新建应用' }}</span>
            <span>/</span>
            <strong>AI-Builder</strong>
          </div>
          <div v-if="showViewSwitcher && !useDolphinChat" class="mode-switcher">
            <button class="mode-btn" :class="{ active: activeView === 'builder' }" @click="setActiveView('builder')">
              <span class="mode-btn-icon" aria-hidden="true">
                <svg viewBox="0 0 16 16" fill="none">
                  <path d="M3.5 5.2h9M3.5 8h9M3.5 10.8h6.2" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
                  <circle cx="12.2" cy="10.8" r="1.2" fill="currentColor" />
                </svg>
              </span>
              <span>智能搭建</span>
            </button>
            <button v-if="SHOW_PLATFORM_CONFIG" class="mode-btn" :class="{ active: activeView === 'platform' }" @click="setActiveView('platform')">
              <span class="mode-btn-icon" aria-hidden="true">
                <svg viewBox="0 0 16 16" fill="none">
                  <rect x="2.3" y="3" width="11.4" height="8.4" rx="1.8" stroke="currentColor" stroke-width="1.3" />
                  <path d="M5.2 13h5.6" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" />
                </svg>
              </span>
              <span>辅助搭建</span>
            </button>
          </div>
          <!-- "查看应用"：应用部署完成后显示在顶部明显位置；点击在当前页切到
               aPaaS 平台 inline iframe（走 platform_proxy SSO 免登），不开新标签页
               以免丢失登录态。复用创建过程面板里同名按钮的 openInPlatform 逻辑。 -->
          <button
            v-if="deployAllDone && (store.currentApp?.apaas_app_id || platformDirectUrl)"
            type="button"
            class="mode-btn mode-btn-link"
            title="在当前页打开 aPaaS 平台查看/运行当前应用"
            @click="openInPlatform"
          >
            <span class="mode-btn-icon" aria-hidden="true">
              <svg viewBox="0 0 16 16" fill="none">
                <rect x="2.3" y="3" width="11.4" height="8.4" rx="1.8" stroke="currentColor" stroke-width="1.3" />
                <path d="M5.2 13h5.6" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" />
                <path d="M5 6.5l2.5 2 3.5-3.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </span>
            <span>查看应用</span>
          </button>
        </div>
      </template>
      <template #actions>
        <!-- "AI 调整" 按钮已删（dolphin embed 是默认入口），"部署到预览" 按钮已删
             （让 dolphin agent 调 publish_application 工具发布，统一对话 UX）-->
        <!-- 面板关闭时：顶部展示一个"展开产物面板"按钮；面板打开时由 SPEC 行内 .preview-panel-collapse 关闭，此处隐藏（合并成同一个 toggle） -->
        <button
          v-if="showBuilderArtifactToggle && !showAnyBuilderArtifactPanel"
          class="builder-top-action artifact icon-only"
          type="button"
          aria-label="打开产物面板"
          title="打开产物面板"
          @click="toggleArtifactPanel"
        >
          <span class="builder-top-action-icon" aria-hidden="true">
            <svg viewBox="0 0 16 16" fill="none">
              <rect x="2.3" y="3" width="11.4" height="10" rx="2" stroke="currentColor" stroke-width="1.3" />
              <path d="M8 3v10" stroke="currentColor" stroke-width="1.3" />
            </svg>
          </span>
        </button>
        <!-- "部署到预览"按钮已删 — dolphin 模式下让 agent 调 publish_application 工具发布。
             非 dolphin 模式（useDolphinChat=false 时回退老 SPEC chat 流程）保留兜底 -->
        <button
          v-if="!useDolphinChat && showStartDeployButton"
          class="builder-top-action primary"
          type="button"
          @click="startDeployFromTopbar"
          :disabled="assembling || generating || deployRunningAll || deployExecuting !== null || !hasPreviewContent"
        >
          部署到预览
        </button>
        <button v-else-if="!useDolphinChat && !showBuildHistoryButton" class="builder-top-action primary" type="button" @click="router.push('/devops')">
          运行流水线
        </button>
        <button
          v-if="SHOW_PLATFORM_CONFIG && activeView === 'platform' && platformIframeUrl"
          class="top-bar-icon-btn"
          @click="openPlatformNewTab"
          title="在新窗口打开"
        >↗</button>
      </template>
    </TopBar>
    <div v-if="!embedMode && !useDolphinChat" v-show="showBuilderPhaseStrip" class="builder-chat-phase-strip">
      <div class="builder-chat-agent">
        <span class="builder-chat-agent-dot"></span>
        <span>搭建智能体</span>
        <code>{{ selectedBuilderModelName }}</code>
      </div>
      <div class="builder-chat-phases" aria-label="搭建阶段">
        <div
          v-for="(phase, index) in builderPhaseSteps"
          :key="phase.key"
          class="builder-chat-phase"
          :class="phase.status"
        >
          <span>{{ index + 1 }}</span>
          {{ phase.label }}
        </div>
      </div>
      <div class="builder-chat-save-state">
        <span :class="['state-dot', builderLifecycleStatus.key]"></span>
        {{ builderStatusText }}
      </div>
    </div>
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
            :key="platformIframeKey"
            ref="platformIframeRef"
            :src="platformIframeUrl"
            class="platform-iframe"
            frameborder="0"
            allow="clipboard-read; clipboard-write"
            @load="onPlatformIframeLoad"
            @error="onIframeError"
          ></iframe>
        </template>
        <div v-else class="platform-error">
          <p>应用尚未部署到平台，无法打开辅助搭建</p>
          <div class="platform-error-actions">
            <button class="platform-retry-btn" @click="loadPlatformUrl">重试</button>
          </div>
        </div>
      </div>

      <!-- SPEC PhaseBar (Phase β: only when requirements agent is active) -->
      <div
        v-if="showSpecArtifactPanel"
        v-show="!SHOW_PLATFORM_CONFIG || activeView === 'builder'"
        class="spec-phasebar-strip"
      >
        <PhaseBar />
      </div>

      <!-- 智能搭建内容区（横向布局） -->
      <div
        v-show="!SHOW_PLATFORM_CONFIG || activeView === 'builder'"
        class="builder-content"
        :class="{
          'single-pane': !showBuilderChatSide,
          'artifacts-open': showAnyBuilderArtifactPanel,
          'artifacts-hidden': !showAnyBuilderArtifactPanel
        }"
      >
      <!-- 左侧对话区 -->
      <div v-if="showBuilderChatSide" class="chat-side">
        <!-- ★ Dolphin Agent 嵌入：等 backend current_app state 同步完成后才挂载，
             避免切 app 时 dolphin 拿到旧 app 的 ctx 跨应用污染。
             5 秒超时兜底，即使 sync 失败也允许加载（init-app-context endpoint
             内部也会强制写 state，二重保险）。 -->
        <DolphinAgentEmbed
          v-if="useDolphinChat && (!builderCurrentAppId || currentAppSynced || syncTimeoutFallback)"
          :app-id="builderCurrentAppId"
          :app-name="builderAppDisplayName"
          title="AI-Builder 应用调整助手"
        />
        <div v-else-if="useDolphinChat" class="dolphin-loading-pane">
          <span class="loading-dot"></span>
          <span>正在切换应用上下文…</span>
        </div>
        <template v-else>
        <div v-if="appParsedMode" class="doc-view-wrap">
          <div class="doc-view-head">
            <div class="doc-view-title">功能设计文档</div>
            <div class="doc-view-meta">
              <div class="doc-view-file">{{ lastParsedFilename || `${store.preview.appName || '功能设计文档'}.md` }}</div>
              <button class="doc-download-btn" @click="downloadCurrentDoc">下载 .md</button>
            </div>
          </div>
          <div v-if="liveStructuredDocResult" class="doc-preview-body structured-doc-host">
            <StructuredDocRenderer :doc-result="liveStructuredDocResult" />
          </div>
          <pre v-else-if="selectedDocDisplayContent" class="doc-preview-body plain-doc-fallback">{{ selectedDocDisplayContent }}</pre>
          <div v-else class="doc-view-empty">
            暂无可展示的文档内容，可重新上传文档后查看。
          </div>
        </div>
        <template v-else>
          <!-- Claude 风格：先纯对话。AI 判定需求收集足够（SPEC phase 离开 gathering）会自动展开三栏 -->
          <div v-if="useSpecMode && !specPanelExpanded" class="spec-cta-banner" role="note">
            <div class="spec-cta-text">
              <span class="spec-cta-icon" aria-hidden="true">💬</span>
              <span>告诉我你想搭建什么。我会先帮你梳理需求，准备好就自动生成设计文档。</span>
            </div>
          </div>
          <section v-if="showBuilderSpecBrief" class="builder-spec-brief" aria-label="当前 SPEC 摘要">
            <div class="builder-spec-brief-main">
              <span class="builder-spec-kicker">当前 SPEC</span>
              <strong>{{ specCompletenessScore }}% 完整</strong>
              <p>{{ specOverviewLead }}</p>
            </div>
            <div class="builder-spec-brief-stats">
              <button
                v-for="stat in specOverviewStats"
                :key="stat.key"
                type="button"
                @click="openArtifactPanel(stat.tab)"
              >
                <span>{{ stat.value }}</span>
                {{ stat.label }}
              </button>
            </div>
          </section>
          <div class="messages" ref="messagesRef">
            <div
              v-for="(msg, idx) in visibleMessages"
              :key="msg.id ?? `msg-${idx}`"
              class="chat-bubble"
              :class="[msg.role, { 'streaming-message': isStreamingAssistantMessage(msg) }]"
            >
              <div class="bubble-row" :class="msg.role">
                <div v-if="msg.role === 'assistant'" class="assistant-avatar" aria-hidden="true">AI</div>
                <div class="bubble-inner" :class="{ 'welcome-bubble': msg.role === 'assistant' && msg.content === BUILDER_WELCOME_MESSAGE }">
                  <div class="bubble-content" :class="msg.role" v-html="formatContent(msg.content)"></div>
                  <!-- 消息附带的 action 按钮组（如 DOC_NOT_STANDARD 错误的"返回 AI-Chat"）-->
                  <div v-if="(msg as any).actions?.length" class="bubble-actions">
                    <button
                      v-for="(action, ai) in (msg as any).actions"
                      :key="ai"
                      type="button"
                      class="bubble-action-btn"
                      :class="action.type"
                      @click="handleMessageAction(action)"
                    >{{ action.label }}</button>
                  </div>
                </div>
              </div>
            </div>
            <div v-if="isTyping" class="chat-bubble assistant">
              <div class="bubble-row assistant">
                <div class="assistant-avatar" aria-hidden="true">AI</div>
                <div class="bubble-inner">
                  <div class="bubble-content assistant typing-with-meta">
                    <span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>
                    <span v-if="sendingMessage && pendingDurationSec > 0" class="typing-meta">
                      AI 思考中 · {{ pendingDurationSec }}s
                    </span>
                  </div>
                </div>
              </div>
            </div>
            <!-- 编码冲突修复输入 -->
            <div v-if="activeConflict" class="chat-bubble assistant">
              <div class="bubble-row assistant">
                <div class="assistant-avatar" aria-hidden="true">AI</div>
                <div class="bubble-inner">
                  <div class="bubble-content assistant conflict-resolve-box">
                    <div class="conflict-label">检测到编码冲突，请确认最新编码（默认已补上 <code>V1</code>）</div>
                    <div class="conflict-input-row">
                      <input
                        v-model="activeConflict.newCode"
                        class="conflict-input"
                        placeholder="输入新编码，如 codeV1"
                        @keydown.enter="resolveConflictAndRetry"
                        :disabled="activeConflict.resolving"
                      />
                      <button class="conflict-btn confirm" @click="resolveConflictAndRetry" :disabled="activeConflict.resolving">
                        {{ activeConflict.resolving ? '修复中...' : '修复' }}
                      </button>
                      <button class="conflict-btn cancel" @click="cancelConflict" :disabled="activeConflict.resolving">取消</button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </template>

        <div v-if="showBuilderComposer" class="builder-workbench">
          <div class="builder-composer-shell">
            <div v-if="!appParsedMode" class="input-bar quick-edit-bar">
              <div class="input-card quick-edit-card">
                <div class="quick-edit-glow" aria-hidden="true"></div>
                <div class="composer-toolbar">
                  <el-select
                    v-model="selectedBuilderModelId"
                    class="builder-inline-model-select in-card"
                    popper-class="model-select-dropdown"
                    size="small"
                    placeholder="选择对话模型"
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
              <div class="builder-control-hint inside-card">{{ builderModelHint }}</div>
                <div class="input-card-top">
                <label class="upload-btn" title="上传对话附件（支持各类文档和图片）">
                  <input
                    ref="chatImageInputRef"
                    type="file"
                    multiple
                    accept=".md,.markdown,image/*"
                    @change="handleChatImageChange"
                    style="display:none"
                  />
                  <svg width="18" height="18" viewBox="0 0 18 18" fill="none"><path d="M15.5 8.5l-6.4 6.4a3.5 3.5 0 01-5-5l6.4-6.4a2.2 2.2 0 013.1 3.1L7.2 13a.9.9 0 01-1.3-1.3l5.5-5.5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>
                </label>
                <VoiceInputButton v-model="inputText" :llm-config-id="selectedBuilderModelId" />
                <textarea
                  v-model="inputText"
                  @keydown.enter.exact.prevent="sendMessage"
                  @keydown.enter.shift.exact="inputText += '\n'"
                  :placeholder="builderQuickPlaceholder"
                  rows="1"
                  ref="inputRef"
                  @input="autoResizeTextarea"
                  @paste="handleComposerPaste"
                ></textarea>
                <button
                  v-if="sendingMessage"
                  class="send-btn stop-btn"
                  type="button"
                  @click="stopSending"
                  title="中断"
                >
                  <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor"><rect x="3" y="3" width="8" height="8" rx="1.5"/></svg>
                </button>
                <button v-else class="send-btn" :class="{ disabled: !canSendMessage }" @click="sendMessage">
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M14 2L7 9M14 2l-4.5 12-2-5.5L2 6.5 14 2z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>
                </button>
              </div>
              <div v-if="pendingChatAttachments.length > 0" class="chat-attachment-preview-list">
                <div
                  v-for="(att, idx) in pendingChatAttachments"
                  :key="idx"
                  class="chat-attachment-preview"
                >
                  <img v-if="att.kind === 'image'" class="chat-attachment-preview-image" :src="att.previewUrl" :alt="att.file.name" />
                  <div v-else class="chat-attachment-preview-file">📄</div>
                  <div class="chat-attachment-preview-meta">
                    <div class="chat-attachment-preview-name">{{ att.file.name }}</div>
                    <div class="chat-attachment-preview-tip">{{ att.kind === 'image' ? '将随消息一起发送' : '将随消息一起发送' }}</div>
                  </div>
                  <button class="chat-attachment-remove" type="button" @click="removePendingChatAttachmentAt(idx)" aria-label="移除附件">×</button>
                </div>
              </div>
            </div>
          </div>
          </div>

        </div>
        </template>
      </div>

      <!-- v2 redesign (Session 5): right-side tabs panel hidden — replaced by
           AppBlueprintPanel mounted to the right of <main class="chat-main">.
           DOM disabled via v-if="false" so all bound reactives / computeds /
           store reads are preserved untouched (Session 6 may remove). -->
      <div v-if="false && showBuilderArtifactPanel" class="preview-side builder-result-side">
        <div v-show="!isUpdateReviewMode" class="builder-canvas-tabs">
          <button
            v-for="tab in builderCanvasTabs"
            :key="tab.key"
            type="button"
            class="builder-canvas-tab"
            :class="{ active: canvasTab === tab.key }"
            @click="openArtifactPanel(tab.key)"
          >
            <span>{{ tab.label }}</span>
            <em v-if="tab.badge">{{ tab.badge }}</em>
          </button>
        </div>
        <div class="preview-side-header">
          <div class="preview-side-heading">
            <div class="preview-side-heading-main">
              <div class="preview-side-title-row">
                <div class="preview-side-title">{{ builderAppDisplayName }}</div>
                <div class="preview-side-status inline-meta">
                  <code class="preview-app-code-chip inline">{{ displayAppCode }}</code>
                </div>
              </div>
            </div>
          </div>
          <div class="preview-side-actions">
            <button
              v-if="selectedDocDisplayContent"
              class="preview-side-cta secondary"
              @click="openCurrentDocFullscreen"
            >全屏查看</button>
            <button
              v-if="showUpdateButton"
              class="preview-side-cta secondary"
              @click="openAppChatDrawer"
              :disabled="updatingDocVersion || executingChangePlan || sendingMessage"
              title="在右侧抽屉里跟 AI 改 md，改完一键应用到 Builder"
            >💬 用 AI 调整应用</button>
            <button
              v-if="showExecuteUpdateButton"
              class="preview-side-cta secondary"
              @click="cancelChangePlanAction"
              :disabled="executingChangePlan"
              title="放弃本次变更，回滚到上一版本"
            >取消更新</button>
            <button
              v-if="showExecuteUpdateButton"
              class="preview-side-cta"
              @click="executeChangePlan"
              :disabled="executingChangePlan || !changePlanSelectedCount"
            >{{ executingChangePlan ? '更新中...' : '执行更新' }}</button>
            <button
              v-if="showStartDeployButton"
              class="preview-side-cta"
              @click="startDeployFromArtifact"
              :disabled="assembling || generating || deployRunningAll || deployExecuting !== null || !hasPreviewContent"
            >{{ generating || deployRunningAll || deployExecuting !== null ? '构建中...' : '开始构建' }}</button>
            <button
              v-if="showPublishButton"
              class="preview-side-cta success"
              @click="publishCurrentApp"
              :disabled="publishingApp || isAppOnline"
            >{{ publishingApp ? '上线中...' : isAppOnline ? '已上线' : '上线应用' }}</button>
            <button
              v-if="showBuildHistoryButton"
              class="preview-side-cta secondary"
              type="button"
              @click="openDeployPanel"
              :disabled="assembling || generating || deployRunningAll || deployExecuting !== null"
              title="查看创建过程 / 重试失败步骤"
            >创建过程</button>
            <button
              class="preview-panel-collapse"
              type="button"
              @click="closeArtifactPanel"
              title="收起产物面板"
              aria-label="收起产物面板"
            >
              <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
                <rect x="2.3" y="3" width="11.4" height="10" rx="2" stroke="currentColor" stroke-width="1.3" />
                <path d="M8 3v10" stroke="currentColor" stroke-width="1.3" />
                <path d="M6.1 6.2L4.3 8l1.8 1.8" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </button>
          </div>
        </div>
        <div class="preview-body">
          <!-- 文档版本：默认只展示当前版本，历史版本收进可展开列表 -->
          <div
            v-if="showBuilderPreview && canvasTab === 'spec' && !isUpdateReviewMode && displayDocVersions.length >= 2"
            class="doc-version-switcher"
          >
            <div class="doc-version-current-strip">
              <button
                v-if="selectedDocVersionItem"
                class="doc-version-current-main"
                type="button"
                @click="docVersionHistoryOpen = !docVersionHistoryOpen"
              >
                <span class="doc-version-current-badge">V{{ getDocDisplayVersion(selectedDocVersionItem) }}</span>
                <span class="doc-version-current-text">
                  <strong>{{ getDocDisplayFilename(selectedDocVersionItem) }}</strong>
                  <small>{{ selectedDocVersionItem.summary || '当前设计文档版本' }}</small>
                </span>
              </button>
              <div class="doc-version-current-actions">
                <button
                  v-if="selectedDocVersionItem && canCompareDocVersion(selectedDocVersionItem)"
                  class="doc-version-action"
                  type="button"
                  @click.stop="openDocDiff(selectedDocVersionItem)"
                >对比</button>
                <button
                  v-if="selectedDocVersionItem"
                  class="doc-version-action"
                  type="button"
                  @click.stop="downloadDocVersion(selectedDocVersionItem)"
                >下载</button>
                <button
                  class="doc-version-history-toggle"
                  type="button"
                  :aria-expanded="docVersionHistoryOpen"
                  @click="docVersionHistoryOpen = !docVersionHistoryOpen"
                >
                  版本记录 {{ displayDocVersions.length }}
                  <span aria-hidden="true">{{ docVersionHistoryOpen ? '收起' : '展开' }}</span>
                </button>
              </div>
            </div>
            <div v-if="docVersionHistoryOpen" class="doc-version-history-panel">
              <div
                v-for="ver in displayDocVersions"
                :key="ver.key"
                class="doc-version-history-row"
                :class="{ active: selectedDocVersionKey === ver.key }"
              >
                <button class="doc-version-history-main" type="button" @click="selectDocVersion(ver)">
                  <span class="doc-history-version">V{{ getDocDisplayVersion(ver) }}</span>
                  <span class="doc-history-copy">
                    <strong>{{ getDocDisplayFilename(ver) }}</strong>
                    <small>{{ ver.summary || '设计文档版本' }}</small>
                  </span>
                  <em v-if="selectedDocVersionKey === ver.key">当前查看</em>
                </button>
                <div class="doc-version-history-actions">
                  <button
                    v-if="canCompareDocVersion(ver)"
                    class="doc-version-mini-action"
                    type="button"
                    @click.stop="openDocDiff(ver)"
                  >对比</button>
                  <button
                    class="doc-version-mini-action"
                    type="button"
                    @click.stop="downloadDocVersion(ver)"
                  >下载</button>
                </div>
              </div>
            </div>
          </div>
          <div v-if="showBuilderPreview && canvasTab === 'spec'" class="tab-content spec-tab-content">
            <!-- 正常模式：单文档视图 -->
            <template v-if="!isUpdateReviewMode">
              <div v-if="liveStructuredDocResult" class="doc-version-content expanded doc-preview-body structured-doc-host">
                <StructuredDocRenderer :doc-result="liveStructuredDocResult" />
              </div>
              <pre v-else-if="selectedDocDisplayContent" class="doc-version-content expanded doc-preview-body plain-doc-fallback">{{ selectedDocDisplayContent }}</pre>
              <div v-else class="preview-empty small">暂无可展示的文档内容</div>
            </template>
            <!-- 更新审查模式：顶部变更 banner + 带 diff 高亮的单栏文档视图 -->
            <template v-else>
              <div v-if="updateReviewChangeSummary.length > 0" class="update-review-banner">
                <span class="update-review-banner-prefix">💡 本次更新变更</span>
                <span
                  v-for="item in updateReviewChangeSummary"
                  :key="item.label"
                  class="update-review-banner-chip"
                >{{ item.icon }} {{ item.label }} {{ item.count }}</span>
              </div>
              <div v-if="updateReviewRightDocResult" class="doc-version-content expanded doc-preview-body structured-doc-host">
                <StructuredDocDiffRenderer
                  :doc-result="updateReviewRightDocResult"
                  :diff-meta="updateReviewDiffMeta.right"
                />
              </div>
              <div v-else class="preview-empty small">暂无可展示的文档内容</div>
            </template>

          </div>
          <div v-else-if="canvasTab === 'base'" class="builder-canvas-panel">
            <div class="canvas-panel-head">
              <div>
                <h3>基础配置</h3>
                <p>集中查看应用角色和数据字典，避免散落在文档或表单里逐段查找。</p>
              </div>
              <span>{{ baseConfigCount }} 项</span>
            </div>
            <div class="canvas-basic-grid">
              <section class="canvas-basic-section">
                <div class="canvas-basic-section-head">
                  <strong>角色</strong>
                  <span>{{ canvasRoleItems.length }} 个</span>
                </div>
                <div v-if="canvasRoleItems.length" class="canvas-role-list">
                  <article v-for="(role, index) in canvasRoleItems" :key="canvasRoleKey(role, index)" class="canvas-role-card">
                    <div>
                      <strong>{{ canvasRoleName(role, index) }}</strong>
                      <code>{{ canvasRoleCode(role, index) }}</code>
                    </div>
                    <span>{{ canvasRoleScope(role) }}</span>
                  </article>
                </div>
                <div v-else class="preview-empty small">暂无角色定义。</div>
              </section>
              <section class="canvas-basic-section">
                <div class="canvas-basic-section-head">
                  <strong>数据字典</strong>
                  <span>{{ canvasDictItems.length }} 个</span>
                </div>
                <div v-if="canvasDictItems.length" class="canvas-dict-list">
                  <article v-for="(dict, index) in canvasDictItems" :key="canvasDictKey(dict, index)" class="canvas-dict-card">
                    <div class="canvas-dict-title">
                      <strong>{{ canvasDictName(dict, index) }}</strong>
                      <code>{{ canvasDictCode(dict, index) }}</code>
                    </div>
                    <div class="canvas-dict-options">
                      <span v-for="option in canvasDictOptions(dict).slice(0, 6)" :key="option.code">{{ option.name }}</span>
                      <em v-if="canvasDictOptions(dict).length > 6">+{{ canvasDictOptions(dict).length - 6 }}</em>
                    </div>
                  </article>
                </div>
                <div v-else class="preview-empty small">暂无数据字典。</div>
              </section>
            </div>
          </div>
          <div v-else-if="canvasTab === 'models'" class="builder-canvas-panel">
            <div class="canvas-panel-head">
              <div>
                <h3>数据模型</h3>
                <p>{{ modelNamesText }}</p>
              </div>
              <span>{{ canvasModelItems.length }} 项</span>
            </div>
            <div v-if="canvasModelItems.length" class="canvas-model-grid">
              <article v-for="(model, index) in canvasModelItems" :key="canvasModelKey(model, index)" class="canvas-model-card">
                <div class="canvas-model-title">
                  <strong>{{ canvasModelName(model) }}</strong>
                  <code>{{ canvasModelCode(model) }}</code>
                </div>
                <div class="canvas-model-meta">{{ canvasModelFields(model).length }} 字段 · {{ canvasModelKind(model) }}</div>
                <div class="canvas-field-list">
                  <span v-for="(field, fieldIndex) in canvasModelFields(model).slice(0, 6)" :key="canvasFieldKey(field, fieldIndex)">
                    {{ canvasFieldName(field) }}
                  </span>
                </div>
              </article>
            </div>
            <div v-else class="preview-empty small">暂无模型数据，继续在左侧补充需求或上传设计文档。</div>
          </div>
          <div v-else-if="canvasTab === 'forms'" class="builder-canvas-panel">
            <div class="canvas-panel-head">
              <div>
                <h3>表单草图</h3>
                <p>{{ dictNamesText }} · {{ roleNamesText }}</p>
              </div>
              <span>{{ formPreviewItems.length }} 张</span>
            </div>
            <div v-if="formPreviewItems.length" class="canvas-form-list">
              <article v-for="form in formPreviewItems" :key="form.code" class="canvas-form-card">
                <div class="canvas-form-head">
                  <strong>{{ form.name }}</strong>
                  <code>{{ form.code }}</code>
                </div>
                <div class="form-preview">
                  <div class="form-title">{{ form.modelName }} · {{ form.fieldCount }} 字段</div>
                  <div class="form-fields-grid">
                    <div v-for="field in form.previewFields" :key="field.code" class="form-field" :class="{ 'full-width': field.fullWidth }">
                      <div class="form-label">{{ field.name }}</div>
                      <div class="form-mock">
                        <span>{{ field.mockText }}</span>
                        <span v-if="field.mockIcon" class="mock-arrow">{{ field.mockIcon }}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </article>
            </div>
            <div v-else class="preview-empty small">暂无表单草图，生成配置后会展示字段布局。</div>
          </div>
          <div v-else-if="canvasTab === 'flow'" class="builder-canvas-panel">
            <div class="canvas-panel-head">
              <div>
                <h3>业务流程</h3>
                <p>这里只展示目标应用里的审批、流转和业务闭环，不展示平台内部构建步骤。</p>
              </div>
              <span>{{ businessFlowItems.length }} 条</span>
            </div>
            <div v-if="businessFlowItems.length" class="canvas-flow-list">
              <section v-for="flow in businessFlowItems" :key="flow.key" class="canvas-flow-group">
                <div class="canvas-flow-title">
                  <div>
                    <strong>{{ flow.name }}</strong>
                    <code v-if="flow.code">{{ flow.code }}</code>
                  </div>
                  <span>{{ flow.steps.length }} 步</span>
                </div>
                <p v-if="flow.description" class="canvas-flow-desc">{{ flow.description }}</p>
                <div v-for="step in flow.steps" :key="step.key" class="canvas-flow-step business">
                  <span class="flow-dot"></span>
                  <span>
                    <b>{{ step.action }}</b>
                    <small v-if="step.role">角色：{{ step.role }}</small>
                  </span>
                  <em>{{ step.status || step.step }}</em>
                </div>
              </section>
            </div>
            <div v-else class="preview-empty small">暂无业务流程定义。这里不会混入角色、字典、模型、表单等平台生成步骤。</div>
          </div>
          <div v-else-if="canvasTab === 'code'" class="builder-canvas-panel code-panel">
            <div class="canvas-panel-head">
              <div>
                <h3>开发边界</h3>
                <p>来自 SPEC 的开发边界会在这里形成后续 IDE 任务，避免把可配置内容误送去写代码。</p>
              </div>
              <span>{{ customDevelopmentSummary }}</span>
            </div>
            <div v-if="customDevelopmentItems.length" class="custom-dev-list">
              <article
                v-for="(item, index) in customDevelopmentItems"
                :key="`${item.type}-${item.name}-${index}`"
                class="custom-dev-card"
                :class="{ muted: !isActionableCustomDev(item) }"
              >
                <div class="custom-dev-card-head">
                  <div>
                    <span class="custom-dev-type">{{ customDevTypeLabel(item.type) }}</span>
                    <h4>{{ item.name }}</h4>
                  </div>
                  <span class="custom-dev-state">{{ isActionableCustomDev(item) ? '待进入 IDE' : '配置优先' }}</span>
                </div>
                <dl class="custom-dev-meta">
                  <div>
                    <dt>触发条件</dt>
                    <dd>{{ item.trigger }}</dd>
                  </div>
                  <div>
                    <dt>实现范围</dt>
                    <dd>{{ item.scope }}</dd>
                  </div>
                  <div>
                    <dt>验收口径</dt>
                    <dd>{{ item.acceptance }}</dd>
                  </div>
                </dl>
                <button
                  class="code-panel-button"
                  type="button"
                  :disabled="!isActionableCustomDev(item)"
                  @click="dispatchCustomDevToCoding(item, index)"
                >
                  {{ isActionableCustomDev(item) ? '生成 IDE 任务' : '暂无需开发扩展' }}
                </button>
              </article>
            </div>
            <div v-else class="custom-dev-empty">
              <strong>暂无强制开发扩展</strong>
              <span>当前 SPEC 可先由模型、表单、流程和权限配置覆盖；后续补充复杂组件、Hook、接口或看板时再进入 IDE。</span>
              <button class="code-panel-button secondary" type="button" @click="dispatchGeneralSpecToCoding">带当前 SPEC 进入 IDE</button>
            </div>
          </div>
          <div v-else class="preview-empty preview-empty-stage" :class="{ parsing: isDocParsing || generatingDoc }">
            <template v-if="isDocParsing">
              <div class="parsing-spinner"></div>
              <div class="preview-empty-title">正在解析文档...</div>
              <div class="preview-empty-copy">{{ docParsingStep || 'AI 正在分析文档内容，请稍候' }}</div>
            </template>
            <template v-else-if="generatingDoc">
              <div class="parsing-spinner"></div>
              <div class="preview-empty-title">正在生成结构化配置...</div>
              <div class="preview-empty-copy">AI 正在把对话整理成完整的设计文档，通常需要 1-2 分钟，请稍候</div>
            </template>
            <template v-else>
              <div class="preview-empty-icon" aria-hidden="true">
                <svg width="36" height="36" viewBox="0 0 24 24" fill="none">
                  <rect x="3" y="3" width="18" height="18" rx="4" stroke="currentColor" stroke-width="1.4"/>
                  <path d="M7 8h10M7 12h7M7 16h5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
                </svg>
              </div>
              <div class="preview-empty-title">还没有解析内容</div>
              <div class="preview-empty-copy single-line" style="display:inline-block;width:max-content;max-width:none;white-space:nowrap;">左侧输入需求后，AI 自动生成的设计文档将出现在这里，包含：</div>
              <div class="preview-empty-features">
                <div class="preview-empty-feature">
                  <span class="preview-empty-feature-dot"></span>
                  <span>业务目标与角色定义</span>
                </div>
                <div class="preview-empty-feature">
                  <span class="preview-empty-feature-dot"></span>
                  <span>功能模块清单</span>
                </div>
                <div class="preview-empty-feature">
                  <span class="preview-empty-feature-dot"></span>
                  <span>数据模型与字段</span>
                </div>
                <div class="preview-empty-feature">
                  <span class="preview-empty-feature-dot"></span>
                  <span>权限矩阵</span>
                </div>
              </div>
            </template>
          </div>
        </div>
        <div v-if="store.showChangePlan && store.changePlan && !isUpdateReviewMode" class="change-plan-overlay">
          <div class="change-plan-header">
            <h3>变更计划</h3>
            <button class="change-plan-close" type="button" @click="closeChangePlan" :disabled="executingChangePlan">×</button>
          </div>
          <div class="change-plan-body">
            <div class="change-plan-diff">
              {{ store.changePlan.diffSummary || `检测到 ${changePlanTotalCount} 项待更新内容` }}
            </div>
            <div v-for="group in changePlanGroups" :key="group.key" class="change-group">
              <div class="group-title">
                <span class="group-arrow expanded">▸</span>
                <span>{{ group.title }}</span>
                <span class="dg-badge">{{ group.actions.length }}</span>
              </div>
              <label v-for="action in group.actions" :key="action.id" class="change-item">
                <input v-model="action.selected" type="checkbox" class="change-checkbox" />
                <span class="change-icon" :class="changePlanActionTone(action)">{{ changePlanActionSymbol(action) }}</span>
                <span class="change-desc">{{ describeChangePlanAction(action) }}</span>
              </label>
            </div>
          </div>
          <div class="change-plan-footer">
            <button class="cp-btn" type="button" @click="toggleChangePlanSelection(true)" :disabled="executingChangePlan">全选</button>
            <button class="cp-btn" type="button" @click="toggleChangePlanSelection(false)" :disabled="executingChangePlan">清空</button>
            <span class="cp-count">已选 {{ changePlanSelectedCount }}/{{ changePlanTotalCount }}</span>
            <button class="cp-btn primary" type="button" @click="executeChangePlan" :disabled="executingChangePlan || changePlanSelectedCount === 0">
              {{ executingChangePlan ? '执行中...' : '执行更新' }}
            </button>
          </div>
        </div>
      </div>

      <aside v-if="!useSpecMode && showDeploySidebar" class="deploy-side" :class="{ open: deployOpen || isUpdateReviewMode || isUpdateExecutionMode }">
        <div class="deploy-header">
          <div>
            <div class="deploy-title-row">
              <div class="deploy-title">{{ isUpdateExecutionMode ? '更新进度' : isUpdateReviewMode ? '更新概览' : '创建过程' }}</div>
              <span v-if="isUpdateExecutionMode || currentDeployStep" class="deploy-live-badge">执行中</span>
            </div>
            <div class="deploy-desc">
              {{ isUpdateExecutionMode
                ? (updateExecutionAllDone ? '本次更新已执行完成' : '仅展示本次增量更新涉及的步骤')
                : isUpdateReviewMode
                ? (store.changePlan?.diffSummary || '本次仅展示与上一版设计文档对比出的更新项')
                : (deployAllDone ? '已完成全部创建步骤' : deployRunningAll || deployExecuting ? '正在执行创建步骤' : deployOpen ? '可手动执行未完成步骤，失败项可点击重试' : '创建过程会保留在这里，可手动执行或重试步骤')
              }}
            </div>
            <div v-if="isUpdateExecutionMode && currentUpdateExecutionLabel" class="deploy-current-step">{{ currentUpdateExecutionLabel }}</div>
            <div v-else-if="currentDeployStep" class="deploy-current-step">{{ currentDeployStep.label }}</div>
          </div>
          <div class="deploy-header-actions">
            <button
              v-if="canRetryAllDeploy"
              class="deploy-retry-all-btn"
              type="button"
              :disabled="deployRunningAll || deployExecuting !== null"
              @click="deployRetryAll"
              title="重置失败步骤并继续执行所有未完成步骤"
            >
              <span class="deploy-retry-all-icon" aria-hidden="true">↻</span>
              一键重跑
            </button>
            <button v-if="!isUpdateReviewMode && !isUpdateExecutionMode" class="deploy-close" @click="deployOpen = false" aria-label="关闭部署面板">×</button>
          </div>
        </div>
        <div v-if="isUpdateExecutionMode" class="deploy-progress">
          <div class="dp-track"><div class="dp-fill" :style="{ width: `${updateExecutionPercent}%` }"></div></div>
          <span class="dp-meta">{{ updateExecutionDoneCount }}/{{ updateExecutionTotalCount || 0 }}</span>
        </div>
        <div v-if="deployOpen && !isUpdateReviewMode && !isUpdateExecutionMode" class="deploy-progress">
          <div class="dp-track"><div class="dp-fill" :style="{ width: `${deployPercent}%` }"></div></div>
          <span class="dp-meta">{{ deployDoneCount }}/{{ deploySteps.length || 0 }}</span>
        </div>
        <div v-if="deployOpen && activeConflict && !isUpdateReviewMode && !isUpdateExecutionMode" class="deploy-conflict-card">
          <div class="deploy-conflict-title">检测到编码冲突</div>
          <div class="deploy-conflict-copy">{{ activeConflict.model_name }} 的编码 <code>{{ activeConflict.current_code }}</code> 已存在，已切回左侧对话区等待你确认最新编码。</div>
        </div>
        <div v-if="deployOpen && deployLastError && !isUpdateReviewMode && !isUpdateExecutionMode" class="deploy-conflict-card error-card">
          <div class="deploy-conflict-title">执行失败</div>
          <div class="deploy-conflict-copy">{{ deployLastError }}</div>
        </div>
        <div v-if="isUpdateExecutionMode" class="deploy-groups">
          <div v-for="group in updateExecutionGroups" :key="group.key" class="dg" :class="{ done: group.allDone, current: group.hasCurrent, err: group.hasError }">
            <div class="dg-hd">
              <span class="dg-icon">{{ group.icon }}</span>
              <span class="dg-name">{{ group.title }}</span>
              <span class="dg-badge" :class="group.allDone ? 'done' : group.hasError ? 'err' : ''">{{ group.doneCount }}/{{ group.items.length }}</span>
            </div>
            <div v-for="item in group.items" :key="item.id" class="ds" :class="{ [item.status]: true, current: item.status === 'current' }">
              <div class="ds-dot" :class="item.status === 'current' ? 'pulse' : item.status">
                <span v-if="item.status === 'completed'">✓</span>
                <span v-else-if="item.status === 'error'">!</span>
              </div>
              <div class="ds-body">
                <div class="ds-name">{{ item.label }}</div>
                <div v-if="item.detail" class="ds-err">{{ item.detail }}</div>
              </div>
            </div>
          </div>
        </div>
        <div v-else-if="isUpdateReviewMode" class="deploy-groups update-review-groups">
          <div v-for="group in updateReviewGroups" :key="group.title" class="dg update">
            <div class="dg-hd">
              <span class="dg-icon">{{ group.icon }}</span>
              <span class="dg-name">{{ group.title }}</span>
              <span class="dg-badge">{{ group.items.length }}</span>
            </div>
            <div v-for="item in group.items" :key="item.key" class="update-change-row">
              <div class="update-change-copy">
                <div class="update-change-title">{{ item.name }}</div>
                <div class="update-change-meta">{{ item.code }}</div>
              </div>
              <span class="change-badge mini" :class="item.badge.tone">{{ item.badge.label }}</span>
            </div>
          </div>
          <div v-if="updateReviewGroups.length === 0" class="doc-version-empty">本次更新未检测到可执行变更</div>
        </div>
        <div v-else-if="deployOpen && !isUpdateExecutionMode" class="deploy-groups">
          <div v-for="group in deployGroups" :key="group.title" class="dg" :class="{ done: group.allDone, err: group.hasError, current: group.steps.some(step => step.key === deployExecuting) }">
            <div class="dg-hd">
              <span class="dg-icon">{{ group.icon }}</span>
              <span class="dg-name">{{ group.title }}</span>
              <span class="dg-badge" :class="group.allDone ? 'done' : group.hasError ? 'err' : ''">{{ group.doneCount }}/{{ group.steps.length }}</span>
            </div>
            <div v-for="step in group.steps" :key="step.key" class="ds" :class="{ [step.status]: true, current: deployExecuting === step.key }">
              <div class="ds-dot" :class="deployExecuting === step.key ? 'pulse' : step.status">
                <span v-if="step.status === 'completed'">✓</span>
                <span v-else-if="step.status === 'error'">!</span>
              </div>
              <div class="ds-body">
                <div class="ds-name">{{ step.label }}</div>
                <div v-if="step.error" class="ds-err">{{ step.error }}</div>
              </div>
              <div class="ds-act">
                <span v-if="deployExecuting === step.key" class="ds-spin"></span>
                <button v-else-if="step.status === 'error'" class="ds-btn retry" @click="deployRedo(step.key)">重试</button>
                <button v-else-if="step.status !== 'completed' && step.deps_met" class="ds-btn run" @click="deployExec(step.key)">执行</button>
                <span v-else-if="!step.deps_met && step.status !== 'completed'" class="ds-lock">🔒</span>
              </div>
            </div>
          </div>
          <div v-if="deployAllDone" class="deploy-done">
            部署已完成
            <button class="deploy-done-btn" @click="openInPlatform">查看应用</button>
          </div>
        </div>
        <div v-if="executionLogs.length" class="deploy-log-card compact" :class="{ expanded: deployLogExpanded }">
          <button class="deploy-log-header toggle" type="button" @click="deployLogExpanded = !deployLogExpanded">
            <div class="deploy-log-title-wrap">
              <span>执行日志</span>
              <span class="deploy-log-count">{{ executionLogs.length }} 条</span>
            </div>
            <div class="deploy-log-summary">
              <span class="deploy-log-summary-text">{{ latestExecutionLog?.message || '暂无日志' }}</span>
              <span class="deploy-log-toggle">{{ deployLogExpanded ? '收起' : '展开' }}</span>
            </div>
          </button>
          <div v-if="deployLogExpanded" class="deploy-log-list">
            <div
              v-for="log in executionLogs"
              :key="log.id"
              class="deploy-log-item"
              :class="log.level"
            >
              <div class="deploy-log-meta">
                <span class="deploy-log-level">{{ log.levelLabel }}</span>
                <span class="deploy-log-time">{{ log.time }}</span>
              </div>
              <div class="deploy-log-text">{{ log.message }}</div>
            </div>
          </div>
        </div>
      </aside>

      <!-- SPEC three-pane (Phase β): replaces preview-side + deploy-aside when in spec mode -->
      <div v-if="showSpecArtifactPanel" class="spec-canvas-pane">
        <SpecCanvas />
      </div>
      <SpecInspector v-if="showSpecArtifactPanel" class="spec-inspector-pane" />
    </div><!-- /builder-content -->
    </div><!-- /content-area -->

    <!-- Modals (在 chat-page 根元素下) -->
    <ConnectModal v-model="store.showConnectModal" />
    <EnvSelectModal v-model="showEnvSelect" @selected="onEnvSelected" />
    <input ref="docVersionInputRef" type="file" accept=".md,.markdown" hidden @change="handleDocVersionInputChange" />
    <input ref="reparseInputRef" type="file" accept=".md,.pdf,.docx,.doc,.txt,.markdown" hidden @change="handleReparseInputChange" />
    <el-dialog v-model="docVersionPreviewVisible" :title="docVersionPreviewTitle" width="860px" class="doc-preview-dialog" destroy-on-close>
      <div v-if="docVersionPreviewStructuredResult" class="doc-preview-body structured-doc-host">
        <StructuredDocRenderer :doc-result="docVersionPreviewStructuredResult" />
      </div>
      <pre v-else class="doc-preview-body plain-doc-fallback">{{ docVersionPreviewContent }}</pre>
    </el-dialog>
    <el-dialog
      v-model="docFullscreenVisible"
      :title="docFullscreenTitle"
      width="96vw"
      top="2vh"
      class="doc-preview-dialog doc-preview-dialog-fullscreen"
      destroy-on-close
    >
      <div v-if="docFullscreenStructuredResult" class="doc-preview-body fullscreen structured-doc-host">
        <StructuredDocRenderer :doc-result="docFullscreenStructuredResult" />
      </div>
      <pre v-else class="doc-preview-body fullscreen plain-doc-fallback">{{ docFullscreenContent }}</pre>
    </el-dialog>
    <el-dialog v-model="docVersionDiffVisible" title="文档版本对比" width="1220px" class="doc-diff-dialog" destroy-on-close>
      <div class="diff-summary-bar">
        <span class="diff-stat added">新增 {{ docDiffStats.added }}</span>
        <span class="diff-stat removed">删除 {{ docDiffStats.removed }}</span>
        <span class="diff-stat modified">修改 {{ docDiffStats.modified }}</span>
        <span class="diff-stat unchanged">未变更 {{ docDiffStats.same }}</span>
      </div>
      <div class="doc-diff-container">
        <div class="diff-changes-panel">
          <div class="dcp-title">变更摘要</div>
          <div class="dcp-list">
            <div v-if="diffChangeSummary.length === 0" class="dcp-empty">暂无结构化摘要</div>
            <div v-for="(item, idx) in diffChangeSummary" :key="`${item.type}-${idx}`" class="dcp-item" :class="item.type">
              <span class="dcp-icon">{{ item.type === 'added' ? '+' : item.type === 'removed' ? '-' : '~' }}</span>
              <span class="dcp-text">{{ item.text }}</span>
            </div>
          </div>
        </div>
        <div class="doc-diff-pane">
          <div class="doc-diff-pane-title">{{ docVersionDiffLeftTitle }}</div>
          <div class="doc-diff-content">
            <div v-if="docVersionDiffLeftStructuredResult" class="doc-diff-structured structured-doc-host">
              <StructuredDocDiffRenderer :doc-result="docVersionDiffLeftStructuredResult" :diff-meta="structuredDocDiffMeta.left" />
            </div>
            <template v-else>
              <div
                v-for="(line, idx) in docDiffResult.left"
                :key="`left-${idx}`"
                class="doc-diff-line"
                :class="line.type"
              >
                <span class="doc-diff-lineno">{{ idx + 1 }}</span>
                <span class="doc-diff-text">{{ line.text || ' ' }}</span>
              </div>
            </template>
          </div>
        </div>
        <div class="doc-diff-pane">
          <div class="doc-diff-pane-title">{{ docVersionDiffRightTitle }}</div>
          <div class="doc-diff-content">
            <div v-if="docVersionDiffRightStructuredResult" class="doc-diff-structured structured-doc-host">
              <StructuredDocDiffRenderer :doc-result="docVersionDiffRightStructuredResult" :diff-meta="structuredDocDiffMeta.right" />
            </div>
            <template v-else>
              <div
                v-for="(line, idx) in docDiffResult.right"
                :key="`right-${idx}`"
                class="doc-diff-line"
                :class="line.type"
              >
                <span class="doc-diff-lineno">{{ idx + 1 }}</span>
                <span class="doc-diff-text">{{ line.text || ' ' }}</span>
              </div>
            </template>
          </div>
        </div>
      </div>
    </el-dialog>
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
    <el-dialog
      v-model="conflictDialogVisible"
      title="模型编码在平台已被占用"
      width="680px"
      class="conflict-dialog"
      :close-on-click-modal="false"
      :close-on-press-escape="false"
      :show-close="false"
      destroy-on-close
    >
      <div class="conflict-dialog-tip">
        以下模型的编码在平台其他应用中已存在，直接部署会失败。已为每项自动加
        <code>_V1</code> 后缀，你可以再编辑调整；确认后统一应用到配置。
      </div>
      <div class="conflict-dialog-table">
        <div class="conflict-row conflict-head">
          <div class="col-name">模型名</div>
          <div class="col-orig">原编码（已占用）</div>
          <div class="col-new">新编码</div>
        </div>
        <div v-for="(c, idx) in conflictList" :key="c.original_code" class="conflict-row">
          <div class="col-name">{{ c.name || '（未命名）' }}</div>
          <div class="col-orig"><code>{{ c.original_code }}</code></div>
          <div class="col-new">
            <el-input v-model="conflictList[idx].suggested_code" size="small" />
          </div>
        </div>
      </div>
      <template #footer>
        <button class="conflict-btn cancel" :disabled="conflictApplying" @click="cancelConflictResolve">取消构建</button>
        <button class="conflict-btn confirm" :disabled="conflictApplying" @click="confirmConflictRenames">
          {{ conflictApplying ? '应用中…' : '全部确认并继续' }}
        </button>
      </template>
    </el-dialog>
  </div><!-- /chat-page -->
  </div><!-- /chat-page-shell -->
    </main><!-- /chat-main -->

    <!-- v2 redesign (Session 5): right-column SPEC blueprint (pre-deploy only). -->
    <AppBlueprintPanel
      v-if="!embedMode && !isPostDeploy"
      :models="blueprintSpec.models"
      :forms="blueprintSpec.forms"
      :flows="blueprintSpec.flows"
      :roles="blueprintSpec.roles"
      :dicts="blueprintSpec.dicts"
      :industry-pack-name="currentIndustryPack?.name"
      :industry-object-count="currentIndustryPack?.objectCount"
      @deploy="openDeployModal"
    />
    <!-- 2026-05-19 post-deploy 形态：右侧改成配置助手，聊增量调整 -->
    <ConfigAssistantPanel
      v-else-if="!embedMode && isPostDeploy && resolvedAppId"
      :application-id="resolvedAppId"
      :app-name="builderAppDisplayName || ''"
    />
  </div><!-- /chat-shell -->

  <!-- 用 AI 调整应用：右侧抽屉嵌 AppChatPanel（同 Vue 实例 / 同主题，不跳页不 iframe） -->
  <el-drawer
    v-model="appChatDrawerOpen"
    direction="rtl"
    size="62%"
    :with-header="false"
    :destroy-on-close="false"
    class="app-chat-drawer"
  >
    <AppChatPanel
      :visible="appChatDrawerOpen"
      :app-id="existingAppId"
      :app-name="store.preview.appName || ''"
      @close="appChatDrawerOpen = false"
      @applied="onAppChatPanelApplied"
    />
  </el-drawer>

  <!-- dolphin 需求分析助手 deeplink (?from=requirements) 进来后的应用目标选择 -->
  <ChooseAppTargetDialog
    v-model="reqDialogVisible"
    :filename="reqDialogFilename"
    :suggested-name="reqDialogSuggestedName"
    :candidates="reqDialogCandidates"
    :loading="reqDialogLoading"
    @confirm="handleRequirementsConfirm"
  />

  <!-- Session 6: v2 deploy-confirm modal. Triggered by AppBlueprintPanel's @deploy. -->
  <DeployConfirmModal
    v-model="deployConfirmOpen"
    :app-name="store.preview.appName || ''"
    :app-code="displayAppCode || ''"
    :changes="deployChanges"
    :impacts="deployImpacts"
    @confirm="runDeploy"
  />

  </WorkbenchShell>
</template>

<script setup lang="ts">
import { API_PREFIX } from '@/utils/request'
import { ref, reactive, computed, nextTick, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { usePreviewStore } from '@/stores/preview'
import { useUserStore } from '@/stores/user'
import { applicationApi } from '@/api/application'
// codingApi / consumeSseResponse no longer needed — coding tab uses iframe
import { incrementalApi, type DiffResponse, type ExecuteResponse } from '@/api/incremental'
import { conversationApi, type ConversationWithApp } from '@/api/conversation'
import ConnectModal from '@/components/ConnectModal.vue'
import EnvSelectModal from '@/components/EnvSelectModal.vue'
import VoiceInputButton from '@/components/common/VoiceInputButton.vue'
import { platformEnvApi } from '@/api/platformEnv'
import request from '@/utils/request'
import { isApaasTokenError, handleError } from '@/utils/errorHandler'
import { resolveComponentLabel } from '@/utils/componentTypes'
import {
  formatParseMetaSummary,
  docExportComponentTypeLabel,
  docExportFieldCode,
  docExportBool,
  isSubTableComponent,
  docExportModelMaps,
  isAutoDocSummaryMessage,
  suggestNextConflictCode,
} from '@/utils/chatPage'
import {
  buildAppCode,
  pickAppCode,
  pickAppName,
  extractAppCodeFromText,
  extractAppNameFromText,
} from '@/utils/app'
import { buildPlatformProxyEntryUrl, repairPlatformIframe } from '@/utils/platformIframe'
import type { ConversationCreate, Message } from '@/types'
import TopBar from '@/components/TopBar.vue'
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import AppChatPanel from '@/components/AppChatPanel.vue'
import DolphinAgentEmbed from '@/components/DolphinAgentEmbed.vue'
import ChooseAppTargetDialog from '@/components/ChooseAppTargetDialog.vue'
import SessionSidebar, { type SessionItem as SidebarSessionItem } from '@/components/common/SessionSidebar.vue'
import StructuredDocRenderer from '@/components/StructuredDocRenderer.vue'
import StructuredDocDiffRenderer from '@/components/StructuredDocDiffRenderer.vue'
import { llmConfigApi, type BuilderModelOption } from '@/api/llmConfig'
import { convertConfig } from '@/api/conversation'
import { buildStructuredDocFromPreviewConfig } from '@/utils/structuredDoc'
import { computeStructuredDocDiff } from '@/utils/structuredDocDiff'
import { useSpecStore } from '@/stores/spec'
import PhaseBar from '@/components/spec/PhaseBar.vue'
import SpecCanvas from '@/components/spec/SpecCanvas.vue'
import SpecInspector from '@/components/spec/SpecInspector.vue'
// v2 redesign (Session 5): 3-column shell — left conversation rail + right SPEC blueprint.
// Existing center content unchanged; new components are pure presentation, no logic.
import ChatConversationList from '@/components/v2/ChatConversationList.vue'
import AppBlueprintPanel from '@/components/v2/AppBlueprintPanel.vue'
import ConfigAssistantPanel from '@/components/v2/ConfigAssistantPanel.vue'
import DeployConfirmModal from '@/components/v2/DeployConfirmModal.vue'
import { buildBlueprintSpec } from '@/views/chat/blueprint-adapter'

const router = useRouter()
const route = useRoute()
const embedMode = computed(() => route.query.embed === 'true')
const activeProjectId = computed(() => {
  const raw = Array.isArray(route.query.project_id) ? route.query.project_id[0] : route.query.project_id
  const parsed = Number(raw)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined
})

// ── 左侧 SessionSidebar：列出当前用户的应用作为"会话"列表 ──
const sidebarApps = ref<any[]>([])
const sidebarLoadedOnce = ref(false)
async function loadSidebarApps() {
  try {
    const apps = await applicationApi.list({ include_remote: false }) as any[]
    sidebarApps.value = Array.isArray(apps) ? apps : []
    sidebarLoadedOnce.value = true
  } catch (e) {
    // 静默失败：sidebar 是辅助导航，不应阻塞主流程
    sidebarLoadedOnce.value = true
  }
}
const sidebarActiveAppId = computed<number | null>(() => {
  const raw = route.query.app_id || route.params.id
  const v = Array.isArray(raw) ? raw[0] : raw
  const parsed = Number(v)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null
})
const sidebarSessionItems = computed<SidebarSessionItem[]>(() =>
  sidebarApps.value.map(app => ({
    id: app.id,
    title: app.app_name || app.name || `应用 #${app.id}`,
    meta: app.app_code || app.code || undefined,
  }))
)
// 与 Apps.vue 的 appWorkspaceQuery 对齐：已生成应用进 SPEC/Update 工作台，否则进搭建会话
function buildSidebarAppQuery(app: any): Record<string, string> {
  const appId = String(app.id)
  const isGenerated = !!(app.apaas_app_id || app.local_status === 'completed' || app.status === 'completed')
  if (isGenerated) return { app_id: appId, tab: 'spec', workspace: 'update' }
  return { app_id: appId }
}
function onSidebarSelectApp(id: string | number) {
  const appId = Number(id)
  if (!Number.isFinite(appId) || appId <= 0) return
  if (sidebarActiveAppId.value === appId) return
  const target = sidebarApps.value.find(a => Number(a.id) === appId)
  if (!target) return
  router.push({ path: '/chat', query: buildSidebarAppQuery(target) }).catch(() => {})
}
function onSidebarCreateApp() {
  router.push({ path: '/chat' }).catch(() => {})
}
async function onSidebarRenameApp(s: SidebarSessionItem) {
  try {
    const { value } = await ElMessageBox.prompt('重命名应用', '编辑名称', {
      inputValue: s.title,
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputValidator: v => (v && v.trim().length > 0 ? true : '名称不能为空'),
    })
    const newName = String(value || '').trim()
    const target = sidebarApps.value.find(x => x.id === Number(s.id))
    if (!target) return
    await applicationApi.update(Number(s.id), {
      app_name: newName,
      app_code: target.app_code || target.code || '',
    })
    target.app_name = newName
    ElMessage.success('已重命名')
  } catch {
    /* user cancelled */
  }
}
async function onSidebarDeleteApp(s: SidebarSessionItem) {
  try {
    await ElMessageBox.confirm(`确认删除应用「${s.title}」吗？此操作不可撤销。`, '删除应用', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
      confirmButtonClass: 'el-button--danger',
    })
    await applicationApi.delete(Number(s.id))
    sidebarApps.value = sidebarApps.value.filter(x => x.id !== Number(s.id))
    if (sidebarActiveAppId.value === Number(s.id)) {
      router.push({ path: '/chat' }).catch(() => {})
    }
    ElMessage.success('已删除')
  } catch {
    /* user cancelled */
  }
}
const store = usePreviewStore()
const userStore = useUserStore()
const specStore = useSpecStore()
const rightQuickInput = ref('')
const parsedAppCode = ref('')
const loadedAppCode = ref('')
const currentRemoteStatus = ref('')
const lastParsedFilename = ref('')
const latestDocContent = ref('')
const latestDocAppId = ref<number | null>(null)
const latestDocConversationId = ref<number | null>(null)
const latestParseMeta = ref<any | null>(null)
const readyForGenerate = computed(() => !!store.currentApp && parseReady.value)
const appParsedMode = computed(() => route.query.app_mode === 'parsed')
// 应用名统一从 store.preview.appName 读；为空就空着，不再回填默认占位
const builderAppDisplayName = computed(() => store.preview.appName || '')
// 当前正在编辑的 app id（来自 URL ?app_id=X 或 ?conversation_id=…）— "AI 调整应用"按钮用
const builderCurrentAppId = computed<number | null>(() => {
  const fromQuery = Number(route.query.app_id)
  if (Number.isFinite(fromQuery) && fromQuery > 0) return fromQuery
  if (existingAppId.value && existingAppId.value > 0) return existingAppId.value
  const fromStore = Number((store.currentApp as any)?.id)
  if (Number.isFinite(fromStore) && fromStore > 0) return fromStore
  return null
})

// 左侧对话区是否用 dolphin agent (a73e75cd81) 接管 — true 走 dolphin iframe，false 走原 SPEC chat
// 注：showBuilderChatSide=false 时整个 chat-side 块都不显示，这个 ref 当前无效。
// 保留 ref 因为别处（如顶上按钮 v-if）还在用它判断"是不是 dolphin 模式"。
const useDolphinChat = ref(true)

// 把"当前编辑的应用"上报给后端，让 dolphin agent 调 MCP 工具时不传 app_id 也能拿到
const currentAppSynced = ref(false)
// 5 秒超时兜底：sync 失败也允许 iframe 加载（init-app-context endpoint 内部
// 会再写一次 state，所以即使前端 sync 失败 dolphin 也能拿对当前应用）
const syncTimeoutFallback = ref(false)
async function syncCurrentAppToBackend() {
  // ★ 优先用 URL query 里的 app_id（最权威），不要 fallback 到 builderCurrentAppId
  // computed —— 它会回退到 store.currentApp，可能是切页前的旧值，导致 dolphin
  // 收到错误的 ctx app_id。
  const appIdFromQuery = Number(route.query.app_id)
  let appId: number | null = null
  if (Number.isFinite(appIdFromQuery) && appIdFromQuery > 0) {
    appId = appIdFromQuery
  } else {
    // 没 query 就 fallback computed（容错）
    try { appId = builderCurrentAppId.value } catch { return }
  }
  if (!appId) {
    currentAppSynced.value = false
    return
  }
  try {
    await request.post('/builder/current-app', {
      app_id: appId,
      app_name: builderAppDisplayName.value || '',
    })
    currentAppSynced.value = true
  } catch (err) {
    console.warn('[current-app sync] failed', err)
    currentAppSynced.value = false
  }
}
// 不用 immediate:true（会触发 TDZ）；改用普通 watch + onMounted 兜底首次同步
watch(() => [route.query.app_id, store.preview.appName], () => {
  currentAppSynced.value = false  // 切应用时立即清，避免旧 sync 状态误用
  syncTimeoutFallback.value = false
  void syncCurrentAppToBackend()
  // 5 秒后无论 sync 成败都允许 DolphinAgentEmbed 渲染
  setTimeout(() => { syncTimeoutFallback.value = true }, 5000)
})

// dolphin agent 改完应用后右侧不联动 — 轮询应用 updated_at 变了就重新加载 SPEC
// 注意：不用 watch(builderCurrentAppId, ...) — 直接 ref source 建立 watcher 会
// 在 setup 同步阶段触发 computed 求值，而 builderCurrentAppId 引用的 existingAppId
// 在文件后面才声明，会触发 TDZ。改成 polling 内部对比 _lastAppId 检测切换。
let _lastAppId: number | null = null
let _lastAppUpdatedAt = ''
let _appPollTimer: any = null
let _appPollVisHandler: (() => void) | null = null

// onMounted 调用：立刻 fetch 一次拿基线（不等第一次轮询）。原来的"首次轮询建基线"
// 设计有 bug — 如果 agent 在 mount 后、第一次轮询前改了 SPEC，第一次轮询会把
// 已经改过的 updated_at 写成基线 → 永远检测不到这次变化（30~60s 后才会感知到下一次变化）。
// 改成 onMounted 立刻拉一次 baseline，确保 baseline 是"最早可能"的时间点。
async function primeAppPollingBaseline() {
  let appId: number | null = null
  try { appId = builderCurrentAppId.value } catch { return }
  if (!appId || !useDolphinChat.value) return
  _lastAppId = appId
  try {
    const app: any = await applicationApi.get(appId)
    _lastAppUpdatedAt = String(app?.updated_at || app?.last_updated_at || '')
  } catch {
    _lastAppUpdatedAt = ''
  }
}
async function pollAppForChanges() {
  let appId: number | null = null
  try { appId = builderCurrentAppId.value } catch { return }
  if (!appId || !useDolphinChat.value) return
  // 切应用 → 重置基线（重新 prime 一次）
  if (appId !== _lastAppId) {
    _lastAppId = appId
    _lastAppUpdatedAt = ''
  }
  try {
    const app: any = await applicationApi.get(appId)
    const updatedAt = String(app?.updated_at || app?.last_updated_at || '')
    if (!_lastAppUpdatedAt) {
      _lastAppUpdatedAt = updatedAt
      return
    }
    if (updatedAt && updatedAt !== _lastAppUpdatedAt) {
      _lastAppUpdatedAt = updatedAt
      // SPEC 变了：右侧面板看的是 docVersions（来自 fetchDocVersions），重新拉一遍
      // 同时 store.preview 也写一遍，让 sidebar/header 等其它读 preview 的地方更新
      try {
        await fetchDocVersions()
      } catch {}
      const cpRaw = app?.config_preview
      if (cpRaw) {
        try {
          const cp = typeof cpRaw === 'string' ? JSON.parse(cpRaw) : cpRaw
          const data = cp?.data || cp
          if (data && typeof data === 'object') {
            if (data.appName) store.preview.appName = data.appName
            if (Array.isArray(data.models)) store.preview.models = data.models
            if (Array.isArray(data.forms)) store.preview.forms = data.forms
            if (Array.isArray(data.roles)) (store.preview as any).roles = data.roles
            if (Array.isArray(data.dicts)) (store.preview as any).dicts = data.dicts
            if (Array.isArray(data.permissions)) (store.preview as any).permissions = data.permissions
          }
        } catch {}
      }
      ElMessage.info({ message: 'AI 助手已更新应用配置，右侧已自动刷新', duration: 2500 })
    }
  } catch {
    // ignore
  }
}
function startAppPolling() {
  if (_appPollTimer) return
  // 5s 一次：原本是 5s（注释一直写 5s），但代码不知何时被改成 30s 导致用户感觉
  // "改完不刷新"。GET /applications/{id} ~17KB，5s 一次的带宽 = 3.4 KB/s 完全可以
  // 接受，agent 改 SPEC 是事件而不是连续流，5s 检测在用户感知边界内。
  // tab 切走时 visibilitychange 会暂停（被动节流）。
  _appPollTimer = setInterval(() => {
    if (document.visibilityState !== 'visible') return  // tab 不可见暂停
    void pollAppForChanges()
  }, 5000)
  // tab 切回前台时立刻补一次轮询 — 否则要等下一个 5s 周期。
  // 用户从 dolphin admin / 别的 tab 切回来的瞬间最可能想立刻看到右侧最新状态。
  _appPollVisHandler = () => {
    if (document.visibilityState === 'visible') {
      void pollAppForChanges()
    }
  }
  document.addEventListener('visibilitychange', _appPollVisHandler)
}
function stopAppPolling() {
  if (_appPollTimer) { clearInterval(_appPollTimer); _appPollTimer = null }
  if (_appPollVisHandler) {
    document.removeEventListener('visibilitychange', _appPollVisHandler)
    _appPollVisHandler = null
  }
}

// "AI 调整" 按钮：新窗口打开 dolphin 完整 chat 页（享受 dolphin 完整对话/历史/记忆/项目管理）
async function openDolphinFullChat() {
  const appId = builderCurrentAppId.value
  if (!appId) return
  try {
    const cfg = await request.get<unknown, {
      server_url: string
      app_adjust_agent_code: string
    }>('/dolphin/config')
    const code = cfg?.app_adjust_agent_code
    if (!code) {
      ElMessage.warning('Dolphin 应用调整助手未配置')
      return
    }
    const url = `${cfg.server_url}/agent/${code}/chat?app_id=${appId}&app_name=${encodeURIComponent(builderAppDisplayName.value || '')}`
    window.open(url, '_blank', 'noopener,noreferrer')
  } catch (err) {
    console.warn('[openDolphinFullChat] failed', err)
    ElMessage.error('打开 AI 调整助手失败')
  }
}
const chatGeneratedDocContent = computed(() => {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const msg = messages[i]
    if (!msg || msg.role !== 'assistant') continue
    const content = String(msg.content || '').trim()
    if (!content) continue
    if (content.includes('功能设计文档') && /^#\s+/m.test(content)) return content
    if (content.includes('## 一、') || content.includes('### 1.1')) return content
  }
  return ''
})
const currentDocAppCode = computed<string>(() => {
  const content: string = String(selectedDocDisplayContent.value || latestDocContent.value || chatGeneratedDocContent.value || '').trim()
  return content ? extractAppCodeFromText(content) : ''
})
const displayAppCode = computed<string>(() => currentDocAppCode.value || parsedAppCode.value || loadedAppCode.value || buildAppCode(store.preview.appName))
const currentPreviewConfigPayload = computed<any>(() => ({
  ...store.preview,
  appName: store.preview.appName || '',
  appCode: parsedAppCode.value || loadedAppCode.value || currentDocAppCode.value || buildAppCode(store.preview.appName),
  flows: (store.preview as any).flows || [],
  custom_development: (store.preview as any).custom_development || [],
}))

type CustomDevelopmentItem = {
  type: string
  name: string
  trigger: string
  scope: string
  acceptance: string
}

const customDevelopmentItems = computed<CustomDevelopmentItem[]>(() => {
  const currentItems = normalizeCustomDevelopmentItems(currentPreviewConfigPayload.value)
  if (currentItems.length) return currentItems
  return normalizeCustomDevelopmentItems(store.preview)
})

const actionableCustomDevelopmentItems = computed(() =>
  customDevelopmentItems.value.filter(item => isActionableCustomDev(item))
)

const customDevelopmentSummary = computed(() => {
  const total = customDevelopmentItems.value.length
  const actionable = actionableCustomDevelopmentItems.value.length
  if (actionable > 0) return `${actionable} 项待开发`
  if (total > 0) return '配置优先'
  return '暂无'
})

const modelNamesText = computed(() => {
  const names = store.preview.models.map((m: any) => m?.name).filter(Boolean)
  return names.length ? names.slice(0, 8).join('、') + (names.length > 8 ? ` 等 ${names.length} 项` : '') : '暂无'
})
const canvasModelItems = computed<any[]>(() => Array.isArray(store.preview.models) ? store.preview.models as any[] : [])
const canvasModelKey = (model: any, index: number) => model?.code || model?.name || `model-${index}`
const canvasModelName = (model: any) => model?.name || model?.code || '未命名模型'
const canvasModelCode = (model: any) => model?.code || '未设置编码'
const canvasModelKind = (model: any) => model?.table_type || model?.type || '主表'
const canvasModelFields = (model: any): any[] => Array.isArray(model?.fields) ? model.fields : []
const canvasFieldKey = (field: any, index: number) => field?.code || field?.name || `field-${index}`
const canvasFieldName = (field: any) => field?.name || field?.code || '未命名字段'
const dictNamesText = computed(() => {
  const names = store.preview.dicts.map((d: any) => d?.name).filter(Boolean)
  return names.length ? names.slice(0, 8).join('、') + (names.length > 8 ? ` 等 ${names.length} 项` : '') : '暂无'
})
const roleNamesText = computed(() => {
  const names = store.preview.roles.map((r: any) => r?.name).filter(Boolean)
  return names.length ? names.slice(0, 8).join('、') + (names.length > 8 ? ` 等 ${names.length} 项` : '') : '暂无'
})
const canvasRoleItems = computed<any[]>(() => Array.isArray(store.preview.roles) ? store.preview.roles as any[] : [])
const canvasDictItems = computed<any[]>(() => Array.isArray(store.preview.dicts) ? store.preview.dicts as any[] : [])
const baseConfigCount = computed(() => canvasRoleItems.value.length + canvasDictItems.value.length)
const canvasRoleKey = (role: any, index: number) => role?.code || role?.role_code || role?.name || `role-${index}`
const canvasRoleName = (role: any, index: number) => role?.name || role?.role_name || role?.code || `角色${index + 1}`
const canvasRoleCode = (role: any, index: number) => role?.code || role?.role_code || `role_${index + 1}`
const canvasRoleScope = (role: any) => {
  const scope = role?.scope || role?.data_scope || role?.dataScope || ''
  if (!scope) return '未配置范围'
  return getDataScopeLabel(scope).text
}
const canvasDictKey = (dict: any, index: number) => dict?.code || dict?.dict_code || dict?.name || `dict-${index}`
const canvasDictName = (dict: any, index: number) => dict?.name || dict?.dict_name || dict?.code || `字典${index + 1}`
const canvasDictCode = (dict: any, index: number) => dict?.code || dict?.dict_code || `dict_${index + 1}`
const canvasDictOptions = (dict: any) => normalizeDictOptions(dict)
const builderLifecycleStatus = computed(() => {
  if (deployAllDone.value || store.currentApp?.status === 'completed') {
    return { key: 'deployed', label: '已部署' as const }
  }
  if (parseReady.value || store.currentApp?.status === 'ready') {
    return { key: 'generated', label: '已生成' as const }
  }
  return { key: 'draft', label: '草稿' as const }
})
const isPlatformDeployed = computed(() =>
  builderLifecycleStatus.value.key === 'deployed' ||
  !!store.currentApp?.apaas_app_id ||
  store.currentApp?.status === 'completed'
)
// 2026-05-19 post-deploy 布局判定：当前应用已挂到 aPaaS（拿到 apaas_app_id）即视为
// 进入"配置助手"形态——左侧对话列表和右侧蓝图 panel 在这种状态下信息冗余，
// 改为 iframe 全宽 + 右侧 ConfigAssistantPanel 聊增量调整。pre-deploy 阶段保持
// 老的 3 列蓝图同步布局。判断仅依据 apaas_app_id（不依赖 deployAllDone — 后者只
// 在本 session 跑过部署流程才为 true，刷新页面后会丢）。
const isPostDeploy = computed(() => !!store.currentApp?.apaas_app_id)
// store.currentApp 这个 slice 只携带 status/apaas_app_id/remote_status，没有 id 字段；
// route 上的 app_id 是真应用 id，post-deploy 用它做 ConfigAssistantPanel 的 application-id。
const resolvedAppId = computed(() => {
  const fromQuery = route.query.app_id
  const raw = Array.isArray(fromQuery) ? fromQuery[0] : fromQuery
  const n = Number(raw)
  return Number.isFinite(n) && n > 0 ? n : null
})
const isAppOnline = computed(() =>
  currentRemoteStatus.value === 'ENABLE' ||
  currentRemoteStatus.value === '已上线'
)
const isAppPublishing = computed(() => {
  const status = String(currentRemoteStatus.value || '').toLowerCase()
  return status.includes('publish') || status.includes('上线中') || status.includes('publishing')
})
const isApplicationUpdateChatMode = ref(false)
const shouldDefaultOpenArtifactPanel = () => {
  const requestedView = Array.isArray(route.query.view) ? route.query.view[0] : route.query.view
  return requestedView !== 'platform' && requestedView !== 'coding'
}
const artifactPanelVisible = ref(shouldDefaultOpenArtifactPanel())
const showStartDeployButton = computed(() => !deployAllDone.value && !isPlatformDeployed.value)
const showBuildHistoryButton = computed(() =>
  !!existingAppId.value &&
  !showStartDeployButton.value &&
  !isUpdateReviewMode.value &&
  !isUpdateExecutionMode.value
)
const showPublishButton = computed(() =>
  isPlatformDeployed.value &&
  !isUpdateReviewMode.value &&
  !isAppPublishing.value
)
const showUpdateButton = computed(() => !!existingAppId.value && isPlatformDeployed.value && !isUpdateReviewMode.value)
const showExecuteUpdateButton = computed(() => isUpdateReviewMode.value && !!store.changePlan?.actions?.length)
const showBuilderArtifactPanel = computed(() =>
  artifactPanelVisible.value &&
  !useSpecMode.value &&
  (!SHOW_PLATFORM_CONFIG || activeView.value === 'builder')
)
const showSpecArtifactPanel = computed(() =>
  artifactPanelVisible.value &&
  useSpecMode.value &&
  specPanelExpanded.value &&
  !embedMode.value &&
  (!SHOW_PLATFORM_CONFIG || activeView.value === 'builder')
)
const showAnyBuilderArtifactPanel = computed(() =>
  showBuilderArtifactPanel.value || showSpecArtifactPanel.value
)
const showBuilderArtifactToggle = computed(() =>
  !embedMode.value &&
  (!SHOW_PLATFORM_CONFIG || activeView.value === 'builder')
)
const showBuilderPhaseStrip = computed(() =>
  (!SHOW_PLATFORM_CONFIG || activeView.value === 'builder') &&
  !useSpecMode.value &&
  showAnyBuilderArtifactPanel.value
)
// 2026-05-15 按 [[arch_decision_mcp_provider_2026_05_14]] "不再深度融合 ai_chat 等
// 内置 agent" 决策砍掉左侧 AI 助手对话区（DolphinAgentEmbed iframe）：用户只需点
// 右上角"开始构建"按钮即可。右侧 SPEC 区因 .single-pane class 自动 full-width。
// 老 computed 逻辑保留作 ref，下次彻底砍 chat-side block 时一并清。
// 2026-05-18 撤销 cf75367 "恢复 chat panel" — 用户拍板 md 预览区不要 AI 助手。
const showBuilderChatSide = computed(() => false)
const showBuilderComposer = computed(() => showBuilderChatSide.value)
const showDeployProgressInline = computed(() => deploySteps.value.length > 0 || deployOpen.value || isPlatformDeployed.value)
// 用户已决定废弃 "已部署应用版本化视图"：右侧永远显示文档（单文档或 diff），
// 不再区分 showDeployedVersionedView 模式。保留此处常量以便语义搜索，
// 但所有分支按 false 处理（= 渲染文档视图）。
const showDeploySidebar = computed(() =>
  isUpdateReviewMode.value ||
  isUpdateExecutionMode.value ||
  !isPlatformDeployed.value ||
  // 已部署的应用：用户点「创建过程」回看历史步骤时也要让 sidebar 出现。
  // 否则 openDeployPanel() 把 deployOpen 设 true 后这个 aside 仍未渲染，按钮看着没反应。
  deployOpen.value
)
const showViewSwitcher = computed(() =>
  !!existingAppId.value && (
    builderLifecycleStatus.value.key === 'deployed' ||
    !!store.currentApp?.apaas_app_id ||
    store.currentApp?.status === 'completed'
  )
)
const builderStatusText = computed(() => {
  if (deployAllDone.value) return '已完成'
  if (generating.value) return '生成中'
  if (parseReady.value) return '准备就绪'
  return '待完善'
})
const builderQuickPlaceholder = computed(() =>
  isApplicationUpdateChatMode.value
    ? '描述要更新的内容，例如：会议列表增加按部门筛选，并补一个导出报表...'
    : `补充或修改${'文档'}内容，例如：把${'文档'}再细化一下...`
)

type BuilderCanvasTabKey = 'spec' | 'base' | 'models' | 'forms' | 'flow' | 'code'

const builderCanvasTabKeys = new Set<BuilderCanvasTabKey>(['spec', 'base', 'models', 'forms', 'flow'])
const canvasTab = ref<BuilderCanvasTabKey>('spec')

const getRouteCanvasTab = () => {
  const raw = Array.isArray(route.query.tab) ? route.query.tab[0] : route.query.tab
  return builderCanvasTabKeys.has(raw as BuilderCanvasTabKey) ? raw as BuilderCanvasTabKey : null
}

watch(
  () => route.query.tab,
  value => {
    const raw = Array.isArray(value) ? value[0] : value
    if (builderCanvasTabKeys.has(raw as BuilderCanvasTabKey)) {
      canvasTab.value = raw as BuilderCanvasTabKey
      artifactPanelVisible.value = true
    }
  },
  { immediate: true }
)

watch(
  () => route.query.app_id,
  () => {
    if (!getRouteCanvasTab()) {
      artifactPanelVisible.value = shouldDefaultOpenArtifactPanel()
    }
  }
)

watch(
  () => route.params.id,
  () => {
    if (!getRouteCanvasTab()) {
      artifactPanelVisible.value = shouldDefaultOpenArtifactPanel()
    }
  }
)

function openArtifactPanel(tab?: BuilderCanvasTabKey) {
  if (tab) canvasTab.value = tab
  artifactPanelVisible.value = true
}

function closeArtifactPanel() {
  artifactPanelVisible.value = false
}

function toggleArtifactPanel() {
  artifactPanelVisible.value = !showAnyBuilderArtifactPanel.value
}

function startDeployFromTopbar() {
  openArtifactPanel('spec')
  startDeployFlow()
}

function startDeployFromArtifact() {
  openArtifactPanel('spec')
  startDeployFlow()
}

const builderPhaseSteps = computed(() => {
  const hasSpecDocument = !!docPreviewContent.value
    || !!docResultForCard.value
    || !!chatGeneratedDocContent.value
    || !!latestDocContent.value.trim()
  const configReady = hasStructuredPreviewData.value || parseReady.value
  const demandFinished = generatingDoc.value
    || isDocParsing.value
    || hasSpecDocument
    || configReady
    || currentAgent.value !== 'requirements'
  const specActive = generatingDoc.value || isDocParsing.value || (hasSpecDocument && !configReady)
  const specReady = (hasSpecDocument && configReady) || parseReady.value
  const deployed = deployAllDone.value || isPlatformDeployed.value
  return [
    { key: 'demand', label: '理解需求', status: demandFinished ? 'done' : 'active' },
    { key: 'spec', label: 'SPEC 设计', status: specReady ? 'done' : specActive ? 'active' : 'pending' },
    { key: 'config', label: '配置生成', status: configReady ? 'done' : generating.value || isDocParsing.value ? 'active' : 'pending' },
    { key: 'deploy', label: '部署', status: deployed ? 'done' : deployRunningAll.value || deployExecuting.value !== null ? 'active' : 'pending' },
  ]
})

type BusinessFlowStep = {
  key: string
  step: string
  action: string
  role: string
  status: string
}

type BusinessFlowItem = {
  key: string
  name: string
  code: string
  description: string
  steps: BusinessFlowStep[]
}

function workflowNodeStatusLabel(type: string) {
  const normalized = String(type || '').toLowerCase()
  if (normalized === 'start') return '开始'
  if (normalized === 'approve') return '审批'
  if (normalized === 'end') return '结束'
  return ''
}

function normalizeBusinessFlowItem(flow: any, flowIndex: number): BusinessFlowItem | null {
  if (!flow || typeof flow !== 'object') return null
  const name = String(flow.flow_name || flow.name || flow.workflowName || `流程 ${flowIndex + 1}`).trim()
  if (!name) return null
  const code = String(flow.flow_code || flow.code || flow.workflowCode || '').trim()
  const rawSteps = Array.isArray(flow.steps)
    ? flow.steps
    : Array.isArray(flow.nodes)
      ? flow.nodes
      : Array.isArray(flow.actions)
        ? flow.actions
        : []
  const steps = rawSteps
    .map((step: any, stepIndex: number) => {
      const stepNo = String(step?.step || step?.order || stepIndex + 1)
      const action = String(step?.action || step?.name || step?.label || '').trim()
      if (!action) return null
      const status = String(step?.status || step?.result || workflowNodeStatusLabel(step?.type) || '').trim()
      return {
        key: `${code || name}-${stepNo}-${stepIndex}`,
        step: stepNo,
        action,
        role: String(step?.role || step?.assignee || '').trim(),
        status,
      }
    })
    .filter(Boolean) as BusinessFlowStep[]
  if (!steps.length) return null
  return {
    key: `${code || name}-${flowIndex}`,
    name,
    code,
    description: String(flow.description || flow.remark || '').trim(),
    steps,
  }
}

const businessFlowItems = computed<BusinessFlowItem[]>(() => {
  const preview = store.preview as any
  const rawFlows = Array.isArray(docResultForCard.value?.flows) && docResultForCard.value.flows.length
    ? docResultForCard.value.flows
    : Array.isArray(preview.flows) && preview.flows.length
      ? preview.flows
      : Array.isArray(preview.workflows)
        ? preview.workflows
        : []
  return rawFlows
    .map((flow: any, index: number) => normalizeBusinessFlowItem(flow, index))
    .filter(Boolean) as BusinessFlowItem[]
})

const builderCanvasTabs = computed<Array<{ key: BuilderCanvasTabKey; label: string; badge: string }>>(() => [
  { key: 'spec', label: 'SPEC', badge: docPreviewAvailable.value ? 'v0.1' : '' },
  { key: 'base', label: '基础配置', badge: baseConfigCount.value ? String(baseConfigCount.value) : '' },
  { key: 'models', label: '模型', badge: store.preview.models.length ? String(store.preview.models.length) : '' },
  { key: 'forms', label: '表单', badge: formPreviewItems.value.length ? String(formPreviewItems.value.length) : '' },
  {
    key: 'flow',
    label: '业务流程',
    badge: businessFlowItems.value.length ? String(businessFlowItems.value.length) : '',
  },
])

const hasStructuredPreviewData = computed(() =>
  !!store.preview.appName
  || store.preview.roles.length > 0
  || store.preview.dicts.length > 0
  || store.preview.models.length > 0
  || formPreviewItems.value.length > 0
  || permissionPreviewItems.value.length > 0
)
const hasPreviewContent = computed(() =>
  hasStructuredPreviewData.value
  || !!docResultForCard.value
  || !!chatGeneratedDocContent.value
  || !!latestDocContent.value.trim()
)
const showBuilderPreview = computed(() =>
  hasPreviewContent.value && (
    !isRequirementsMode.value ||
    !!existingAppId.value ||
    parseReady.value ||
    isDocParsing.value   // 解析中也显示已有的部分数据
  )
)
const docPreviewContent = computed(() => String(selectedDocDisplayContent.value || '').trim())
const docPreviewAvailable = computed(() => !!docPreviewContent.value)
const publishingApp = ref(false)

const getDataScopeLabel = (scope: string) => {
  const normalized = (scope || '').toLowerCase()
  if (normalized.includes('all') || normalized.includes('全部')) return { text: '全部数据', className: 'all' }
  if (normalized.includes('dept') || normalized.includes('部门')) return { text: '部门数据', className: 'dept' }
  if (normalized.includes('self') || normalized.includes('本人') || normalized.includes('自己')) return { text: '本人数据', className: 'self' }
  return { text: scope || '未配置', className: '' }
}

const formPreviewItems = computed(() => {
  if ((store.preview.forms || []).length > 0) {
    return (store.preview.forms || []).map((form: any, idx: number) => {
      const components = Array.isArray(form?.components) ? form.components : []
      return {
        name: form?.formName || form?.name || `表单${idx + 1}`,
        code: form?.formCode || form?.code || `form_${idx + 1}`,
        modelName: form?.modelName || form?.bindModelName || form?.modelCode || `数据模型${idx + 1}`,
        modelCode: form?.modelCode || form?.bindModelCode || `model_${idx + 1}`,
        tableType: 'main',
        tableTypeLabel: '主表',
        fieldCount: components.length,
        fieldsText: components.length
          ? components.map((component: any) => component?.label || component?.name || component?.code || '未命名字段').slice(0, 8).join('、')
          : '暂无字段配置',
        previewFields: components.slice(0, 6).map((component: any, fieldIdx: number) => {
          // component 常常只有 modelField 没有独立 code，拆出来兜底
          const mf = String(component?.modelField || component?.model_field || '')
          const mfCode = mf.includes('.') ? mf.split('.', 2)[1] : ''
          return ({
          name: component?.label || component?.name || component?.code || mfCode || `字段${fieldIdx + 1}`,
          code: component?.code || component?.field_code || component?.fieldCode || mfCode || `field_${fieldIdx + 1}`,
          fullWidth: ['textarea', '文本域', '描述', '备注', 'rich'].some((keyword) => String(component?.componentType || component?.label || '').toLowerCase().includes(String(keyword).toLowerCase())),
          mockText: ['date', '日期', 'time', '时间'].some((keyword) => String(component?.componentType || '').toLowerCase().includes(String(keyword).toLowerCase()))
            ? '请选择'
            : ['select', 'enum', '字典', '下拉', 'radio', 'checkbox'].some((keyword) => String(component?.componentType || '').toLowerCase().includes(String(keyword).toLowerCase()))
              ? '请选择选项'
              : ['number', '金额', '数值'].some((keyword) => String(component?.componentType || '').toLowerCase().includes(String(keyword).toLowerCase()))
                ? '请输入数值'
                : '请输入内容',
          mockIcon: ['date', '日期', 'time', '时间', 'select', 'enum', '字典', '下拉'].some((keyword) => String(component?.componentType || '').toLowerCase().includes(String(keyword).toLowerCase())) ? '▾' : ''
          })
        })
      }
    })
  }

  return (store.preview.models || [])
    .filter((model: any) => !/sub|child|子表/.test(String(model?.table_type || model?.type || '').toLowerCase()))
    .map((model: any, idx: number) => ({
      name: model?.form_name || model?.name || `表单${idx + 1}`,
      code: model?.form_code || model?.code || `form_${idx + 1}`,
      modelName: model?.name || model?.code || `数据模型${idx + 1}`,
      modelCode: model?.code || `model_${idx + 1}`,
      tableType: String(model?.table_type || model?.type || '').toLowerCase(),
      tableTypeLabel: /sub|child|子表/.test(String(model?.table_type || model?.type || '').toLowerCase()) ? '子表' : '主表',
      fieldCount: Array.isArray(model?.fields) ? model.fields.length : 0,
      fieldsText: Array.isArray(model?.fields) && model.fields.length
        ? model.fields.map((field: any) => field?.name || field?.code || '未命名字段').slice(0, 8).join('、')
        : '暂无字段配置',
      previewFields: Array.isArray(model?.fields)
        ? model.fields.slice(0, 6).map((field: any, fieldIdx: number) => ({
            name: field?.name || field?.code || `字段${fieldIdx + 1}`,
            code: field?.code || `field_${fieldIdx + 1}`,
            fullWidth: ['textarea', '文本域', '描述', '备注'].some((keyword) => String(field?.type || field?.name || '').toLowerCase().includes(String(keyword).toLowerCase())),
            mockText: ['date', '日期', 'time', '时间'].some((keyword) => String(field?.type || '').toLowerCase().includes(String(keyword).toLowerCase()))
              ? '请选择'
              : ['select', 'enum', '字典', '下拉'].some((keyword) => String(field?.type || '').toLowerCase().includes(String(keyword).toLowerCase()))
                ? '请选择选项'
                : ['number', '金额', '数值'].some((keyword) => String(field?.type || '').toLowerCase().includes(String(keyword).toLowerCase()))
                  ? '请输入数值'
                  : '请输入内容',
            mockIcon: ['date', '日期', 'time', '时间', 'select', 'enum', '字典', '下拉'].some((keyword) => String(field?.type || '').toLowerCase().includes(String(keyword).toLowerCase())) ? '▾' : ''
          }))
        : []
    }))
})
const permissionPreviewItems = computed(() =>
  (store.preview.permissions || []).map((perm: any, idx: number) => {
    const rules = Array.isArray(perm?.roles) && perm.roles.length
      ? perm.roles
      : Array.isArray(perm?.rules) && perm.rules.length
        ? perm.rules
        : Array.isArray(perm?.permissions) && perm.permissions.length
          ? perm.permissions
          : []

    return {
      name: perm?.formName || perm?.form || perm?.table || perm?.name || `权限对象${idx + 1}`,
      code: perm?.formCode || perm?.form_code || perm?.table_code || perm?.code || `perm_${idx + 1}`,
      raw: perm,
      rows: rules.map((role: any, roleIdx: number) => {
        const rawActions = role?.actions || role?.operations || role?.permissions || role?.op || []
        const actions = Array.isArray(rawActions)
          ? rawActions
          : typeof rawActions === 'string' && rawActions
            ? [rawActions]
            : []
        const scopeInfo = getDataScopeLabel(role?.data_scope || role?.dataScope || role?.scope || role?.data || '')
        return {
          roleCode: role?.role_code || role?.roleCode || role?.code || role?.role || `role_${roleIdx + 1}`,
          roleName: role?.role_name || role?.roleName || role?.name || role?.role || `角色${roleIdx + 1}`,
          actionsText: actions.length ? actions.join('、') : '未配置',
          scopeText: scopeInfo.text,
          scopeClass: scopeInfo.className,
        }
      })
    }
  })
)

const specOverviewStats = computed<Array<{
  key: string
  label: string
  value: number
  helper: string
  tab: BuilderCanvasTabKey
}>>(() => [
  { key: 'base', label: '基础配置', value: baseConfigCount.value, helper: '角色/字典', tab: 'base' },
  { key: 'models', label: '模型', value: store.preview.models.length, helper: '数据对象', tab: 'models' },
  { key: 'forms', label: '表单', value: formPreviewItems.value.length, helper: '页面草图', tab: 'forms' },
  { key: 'flows', label: '业务流程', value: businessFlowItems.value.length, helper: '业务闭环', tab: 'flow' },
])

const specReadinessItems = computed(() => [
  {
    key: 'doc',
    label: '完整 SPEC 文档',
    ready: docPreviewAvailable.value,
    detail: docPreviewAvailable.value ? '右侧已生成可审阅的设计文档' : '需要先通过需求对话生成文档',
  },
  {
    key: 'config',
    label: '配置对象可落地',
    ready: baseConfigCount.value > 0 && store.preview.models.length > 0 && formPreviewItems.value.length > 0,
    detail: `${baseConfigCount.value} 项基础配置、${store.preview.models.length} 个模型、${formPreviewItems.value.length} 张表单`,
  },
  {
    key: 'flows',
    label: '业务流程可复核',
    ready: businessFlowItems.value.length > 0,
    detail: businessFlowItems.value.length ? `${businessFlowItems.value.length} 条业务流程已结构化` : '仍缺审批或流转定义',
  },
])

const specCompletenessScore = computed(() => {
  const items = specReadinessItems.value
  if (!items.length) return 0
  return Math.round((items.filter(item => item.ready).length / items.length) * 100)
})

const specPrimaryGaps = computed(() =>
  specReadinessItems.value.filter(item => !item.ready).slice(0, 2)
)

const specOverviewLead = computed(() => {
  if (!hasPreviewContent.value) return '左侧继续补充需求后，会在这里汇总 SPEC 覆盖情况。'
  if (specPrimaryGaps.value.length) {
    return `当前还需要补齐：${specPrimaryGaps.value.map(item => item.label).join('、')}。`
  }
  return `已覆盖 ${baseConfigCount.value} 项基础配置、${store.preview.models.length} 个模型、${formPreviewItems.value.length} 张表单和 ${businessFlowItems.value.length} 条业务流程。`
})

const showSpecOverview = computed(() => hasPreviewContent.value || hasStructuredPreviewData.value)
const showBuilderSpecBrief = computed(() =>
  showSpecOverview.value &&
  !appParsedMode.value &&
  !showBuilderArtifactToggle.value
)

const normalizeDictOptions = (dict: any) =>
  (dict?.options || dict?.values || []).map((item: any, idx: number) => (
    typeof item === 'string'
      ? { name: item, code: `opt_${idx + 1}` }
      : { name: item?.name || item?.item_name || item?.valueName || `选项${idx + 1}`, code: item?.code || item?.item_code || item?.valueCode || `opt_${idx + 1}` }
  ))

const summarizeDictOptions = (dict: any) => {
  const options = normalizeDictOptions(dict)
  if (!options.length) return '暂无选项'
  return options.slice(0, 6).map(option => option.name).join('、') + (options.length > 6 ? ` 等 ${options.length} 项` : '')
}

const getChangeBadgeMeta = (
  changeType: string,
  scope: 'role' | 'dict' | 'dict_option' | 'model' | 'field' | 'form' | 'component'
): ChangeBadgeMeta => {
  const normalized = String(changeType || '').toLowerCase()
  if (normalized === 'added') return { label: '创建', tone: 'create' }
  if (normalized === 'modified') return { label: '更新', tone: 'update' }
  if (normalized === 'deleted') {
    if (scope === 'dict' || scope === 'dict_option' || scope === 'field') {
      return { label: '禁用', tone: 'disable' }
    }
    return { label: '删除', tone: 'delete' }
  }
  return { label: '更新', tone: 'update' }
}

const buildFieldLikeItems = (change: any) => {
  const fieldChanges = Array.isArray(change?.field_changes) ? change.field_changes : []
  if (fieldChanges.length > 0) {
    return fieldChanges.map((field: any, idx: number) => ({
      key: `${change.code || change.name}-field-${field.code || idx}`,
      name: field.name || field.code || `字段${idx + 1}`,
      code: field.code || `field_${idx + 1}`,
      type: field.field_type || field.new_value?.fieldType || field.new_value?.type || field.old_value?.fieldType || field.old_value?.type || '文本',
      badge: getChangeBadgeMeta(field.change_type, 'field'),
    }))
  }
  const sourceFields = (change?.new_value?.fields || change?.new_value?.dataModelFields || change?.old_value?.fields || change?.old_value?.dataModelFields || [])
  return sourceFields.map((field: any, idx: number) => ({
    key: `${change.code || change.name}-field-source-${field.code || field.fieldCode || idx}`,
    name: field?.name || field?.fieldName || field?.code || field?.fieldCode || `字段${idx + 1}`,
    code: field?.code || field?.fieldCode || `field_${idx + 1}`,
    type: field?.type || field?.fieldType || '文本',
    badge: getChangeBadgeMeta(change.change_type, 'field'),
  }))
}

const updateRoleDiffItems = computed(() =>
  (updateResourceDiff.value?.role_changes || []).map((change: any, idx: number) => ({
    key: `role-${change.code || idx}`,
    name: change.name || change.code || `角色${idx + 1}`,
    code: change.code || `role_${idx + 1}`,
    badge: getChangeBadgeMeta(change.change_type, 'role'),
    description: getRoleDescription(change.new_value || change.old_value || {}),
  }))
)

const updateDictDiffItems = computed(() =>
  (updateResourceDiff.value?.dict_changes || []).map((change: any, idx: number) => {
    const optionChanges = Array.isArray(change.option_changes) && change.option_changes.length > 0
      ? change.option_changes.map((option: any, optionIdx: number) => ({
          key: `${change.code || idx}-opt-${option.code || optionIdx}`,
          name: option.name || option.code || `选项${optionIdx + 1}`,
          code: option.code || `opt_${optionIdx + 1}`,
          badge: getChangeBadgeMeta(option.change_type, 'dict_option'),
        }))
      : normalizeDictOptions(change.new_value || change.old_value).map((option: any, optionIdx: number) => ({
          key: `${change.code || idx}-source-opt-${option.code || optionIdx}`,
          name: option.name,
          code: option.code,
          badge: getChangeBadgeMeta(change.change_type, 'dict_option'),
        }))

    return {
      key: `dict-${change.code || idx}`,
      name: change.name || change.code || `字典${idx + 1}`,
      code: change.code || `dict_${idx + 1}`,
      badge: getChangeBadgeMeta(change.change_type, 'dict'),
      optionChanges,
    }
  })
)

const updateModelDiffItems = computed(() =>
  (updateResourceDiff.value?.model_changes || []).map((change: any, idx: number) => {
    const fields = buildFieldLikeItems(change)
    const summaryParts = [
      fields.filter((field: any) => field.badge.tone === 'create').length ? `创建 ${fields.filter((field: any) => field.badge.tone === 'create').length} 个字段` : '',
      fields.filter((field: any) => field.badge.tone === 'update').length ? `更新 ${fields.filter((field: any) => field.badge.tone === 'update').length} 个字段` : '',
      fields.filter((field: any) => field.badge.tone === 'disable').length ? `禁用 ${fields.filter((field: any) => field.badge.tone === 'disable').length} 个字段` : '',
    ].filter(Boolean)

    return {
      key: `model-${change.code || idx}`,
      name: change.name || change.code || `模型${idx + 1}`,
      code: change.code || `model_${idx + 1}`,
      badge: getChangeBadgeMeta(change.change_type, 'model'),
      fields,
      summary: summaryParts.join('，') || '本次模型结构发生变化',
    }
  })
)

const updateFormDiffItems = computed(() =>
  (updateResourceDiff.value?.form_changes || []).map((change: any, idx: number) => {
    const componentChanges = Array.isArray(change.component_changes) && change.component_changes.length > 0
      ? change.component_changes.map((component: any, compIdx: number) => ({
          key: `${change.code || idx}-comp-${component.code || compIdx}`,
          name: component.name || component.code || `组件${compIdx + 1}`,
          code: component.code || `component_${compIdx + 1}`,
          badge: getChangeBadgeMeta(component.change_type, 'component'),
          detail: component.model_field || component.table_model_code || component.component_type || '表单组件',
        }))
      : []

    return {
      key: `form-${change.code || idx}`,
      name: change.name || change.code || `表单${idx + 1}`,
      code: change.code || `form_${idx + 1}`,
      badge: getChangeBadgeMeta(change.change_type, 'form'),
      modelCode: change.model_code || change.new_value?.modelCode || '',
      componentChanges,
    }
  })
)





const updateReviewGroups = computed(() => [
  { title: '角色', icon: '👥', items: updateRoleDiffItems.value },
  { title: '数据字典', icon: '📖', items: updateDictDiffItems.value },
  { title: '数据模型', icon: '🗃', items: updateModelDiffItems.value },
  { title: '表单配置', icon: '📋', items: updateFormDiffItems.value },
].filter(group => group.items.length > 0))

const BUILDER_WELCOME_MESSAGE_ID = -10001
const BUILDER_WELCOME_MESSAGE = '你好！我是你的智能搭建助手。\n告诉我你想搭建什么，我会帮你梳理需求、生成设计文档，并引导你完成完整搭建流程。\n可以直接描述业务需求，也可以上传原型图或设计稿开始。'
function createWelcomeMessage(): Message {
  return {
    id: BUILDER_WELCOME_MESSAGE_ID,
    role: 'assistant',
    agent: 'requirements',
    content: BUILDER_WELCOME_MESSAGE,
    created_at: ''
  }
}

function isWelcomeMessage(msg: Message | undefined) {
  return !!msg && msg.role === 'assistant' && msg.content === BUILDER_WELCOME_MESSAGE
}

function resetMessagesToWelcome() {
  if (messages.length === 1 && isWelcomeMessage(messages[0])) return
  messages.splice(0, messages.length)
  messages.push(createWelcomeMessage())
}

const visibleMessages = computed(() => messages)

const focusQuickInput = () => {
  nextTick(() => {
    inputRef.value?.focus()
  })
}

const submitRightQuickEdit = () => {
  const prompt = rightQuickInput.value.trim()
  if (!prompt) return
  inputText.value = prompt
  rightQuickInput.value = ''
  sendMessage()
}

const messagesRef = ref<HTMLElement>()
const inputRef = ref<HTMLTextAreaElement>()
const chatImageInputRef = ref<HTMLInputElement>()
const inputText = ref('')
const isTyping = ref(false)
const sendingMessage = ref(false)
const streamingAssistantMessageId = ref<number | null>(null)
type PendingChatAttachment = { file: File; kind: 'image' | 'file'; previewUrl: string }
const pendingChatAttachments = ref<PendingChatAttachment[]>([])
const canSendMessage = computed(() => (!!inputText.value.trim() || pendingChatAttachments.value.length > 0) && !sendingMessage.value)

// AI 工作中状态 + 中断 — 让用户随时知道 AI 在干活、且能停下来
const currentAbortController = ref<AbortController | null>(null)
const pendingDurationSec = ref(0)
let _pendingDurationTimer: ReturnType<typeof setInterval> | null = null
watch(sendingMessage, (val) => {
  if (_pendingDurationTimer) {
    clearInterval(_pendingDurationTimer)
    _pendingDurationTimer = null
  }
  pendingDurationSec.value = 0
  if (val) {
    _pendingDurationTimer = setInterval(() => {
      pendingDurationSec.value += 1
    }, 1000)
  }
})
const stopSending = () => {
  currentAbortController.value?.abort()
  currentAbortController.value = null
  isTyping.value = false
  sendingMessage.value = false
  streamingAssistantMessageId.value = null
}

const escapeHtml = (value: string) => String(value || '')
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')
  .replace(/'/g, '&#39;')

const buildUserChatAttachmentContent = (
  text: string,
  attachments: PendingChatAttachment[]
) => {
  const parts: string[] = []
  if (text.trim()) parts.push(escapeHtml(text.trim()))
  for (const attachment of attachments) {
    if (attachment.kind === 'image') {
      parts.push(
        `<div class="chat-inline-upload">
        <div class="chat-inline-upload-head">
          <span class="chat-inline-upload-badge">截图</span>
          <span class="chat-inline-upload-name">${escapeHtml(attachment.file.name)}</span>
        </div>
        <img class="chat-inline-upload-image" src="${attachment.previewUrl}" alt="${escapeHtml(attachment.file.name)}" />
        <div class="chat-inline-upload-foot">发送后会带着这张图片一起参与对话</div>
      </div>`
      )
    } else {
      parts.push(
        `<div class="chat-inline-upload file">
          <div class="chat-inline-upload-head">
            <span class="chat-inline-upload-badge">附件</span>
            <span class="chat-inline-upload-name">${escapeHtml(attachment.file.name)}</span>
          </div>
          <div class="chat-inline-upload-file-row">
            <span class="chat-inline-upload-file-icon">📄</span>
            <span class="chat-inline-upload-file-tip">发送后会带着这个附件一起参与对话</span>
          </div>
        </div>`
      )
    }
  }
  return parts.join('\n\n')
}

const triggerChatImageUpload = () => {
  chatImageInputRef.value?.click()
}

const clearPendingChatAttachments = () => {
  for (const att of pendingChatAttachments.value) {
    if (att.previewUrl) URL.revokeObjectURL(att.previewUrl)
  }
  pendingChatAttachments.value = []
  if (chatImageInputRef.value) chatImageInputRef.value.value = ''
}

const removePendingChatAttachmentAt = (index: number) => {
  const removed = pendingChatAttachments.value[index]
  if (removed?.previewUrl) URL.revokeObjectURL(removed.previewUrl)
  pendingChatAttachments.value.splice(index, 1)
}

const attachPendingAttachmentFile = (file: File, kind: 'image' | 'file') => {
  const maxSize = kind === 'image' ? 10 * 1024 * 1024 : 20 * 1024 * 1024
  if (file.size > maxSize) {
    ElMessage.warning(kind === 'image' ? '图片大小请控制在 10MB 以内' : '附件大小请控制在 20MB 以内')
    return false
  }
  pendingChatAttachments.value.push({
    file,
    kind,
    previewUrl: kind === 'image' ? URL.createObjectURL(file) : '',
  })
  return true
}

const handleChatImageChange = (event: Event) => {
  const target = event.target as HTMLInputElement
  const fileList = Array.from(target.files || [])
  if (fileList.length === 0) return

  // 单 .md 走老的 doc upload 流程（保留 standard-doc 标准化检测路径）
  if (fileList.length === 1) {
    const onlyFile = fileList[0]
    const lowerName = onlyFile.name.toLowerCase()
    if (lowerName.endsWith('.md') || lowerName.endsWith('.markdown')) {
      handleDocUpload(event)
      return
    }
  }

  for (const f of fileList) {
    const kind = f.type.startsWith('image/') ? 'image' : 'file'
    attachPendingAttachmentFile(f, kind)
  }
  target.value = ''
}

const handleComposerPaste = (event: ClipboardEvent) => {
  const items = Array.from(event.clipboardData?.items || [])
  const imageItem = items.find(item => item.type.startsWith('image/'))
  if (!imageItem) return
  const file = imageItem.getAsFile()
  if (!file) return
  event.preventDefault()
  const ext = (file.type.split('/')[1] || 'png').replace('jpeg', 'jpg')
  const pastedFile = new File([file], `pasted-image-${Date.now()}.${ext}`, { type: file.type })
  attachPendingAttachmentFile(pastedFile, 'image')
}

function autoResizeTextarea() {
  const el = inputRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 160) + 'px'
}
const currentAgent = ref('requirements')
const SHOW_PLATFORM_CONFIG = true
const getAppViewStorageKey = (appId?: number | null) => appId ? `builder:last-active-view:${appId}` : ''
const persistAppActiveView = (view: 'builder' | 'platform' | 'coding') => {
  if (!existingAppId.value) return
  // 智能开发是一次性的工作区入口，不作为应用默认落点；否则从应用列表进入时会被旧状态带偏。
  if (view === 'coding') return
  localStorage.setItem(getAppViewStorageKey(existingAppId.value), view)
}
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
const selectedBuilderModelName = computed(() => {
  const selected = builderModelOptions.value.find(option => option.id === selectedBuilderModelId.value)
  return selected ? `${selected.config_name} / ${selected.model}` : '未配置模型'
})

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

const syncBuilderModelFromConversation = async (
  cid: number,
  options: { syncAgent?: boolean; syncSpec?: boolean } = {}
) => {
  const syncAgent = options.syncAgent ?? true
  const syncSpec = options.syncSpec ?? syncAgent
  try {
    const conversation = await conversationApi.get(cid)
    applyBuilderModelSelection(conversation.selected_llm_config_id)
    if (conversation.agent_type && syncAgent) {
      currentAgent.value = conversation.agent_type
    }
    // 已有应用详情以应用配置为锚点，不允许历史 requirements 对话异步切换整页视图。
    if (conversation.spec_id && syncSpec) {
      try { await specStore.load(conversation.spec_id) }
      catch (e) { console.warn('加载 SPEC 失败:', e) }
    } else {
      specStore.reset()
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
    if (existingAppId.value && e?.response?.status === 404) {
      try {
        const created = await conversationApi.create({
          agent_type: 'builder',
          ...(nextValue != null ? { selected_llm_config_id: nextValue } : {}),
        }) as any
        conversationId.value = created.id
        selectedConversationId.value = created.id
        currentAgent.value = 'builder'
        applyBuilderModelSelection(created.selected_llm_config_id ?? nextValue)
        router.replace({
          path: `/chat/${created.id}`,
          query: {
            ...route.query,
            ...(existingAppId.value ? { app_id: String(existingAppId.value) } : {}),
            view: 'builder',
          },
        })
        fetchConversationList()
        return
      } catch (createError) {
        console.error('模型切换时重建应用更新会话失败:', createError)
      }
    }
    selectedBuilderModelId.value = normalizeBuilderModelId(previousValue)
    handleError(e, { fallback: '切换模型失败' })
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

const loadUploadedDocumentSpec = async (specId?: string | null) => {
  let resolvedSpecId = specId || null

  if (!resolvedSpecId && conversationId.value) {
    try {
      const conversation = await conversationApi.get(conversationId.value)
      applyBuilderModelSelection(conversation.selected_llm_config_id)
      resolvedSpecId = conversation.spec_id || null
    } catch (e) {
      console.warn('文档上传后获取会话 SPEC 失败:', e)
    }
  }

  if (!resolvedSpecId) return false

  await specStore.load(resolvedSpecId)
  if (!specStore.current) {
    console.warn('文档上传后加载 SPEC 失败:', specStore.lastError || resolvedSpecId)
    return false
  }

  currentAgent.value = 'requirements'
  activeView.value = 'builder'
  parseReady.value = true
  openArtifactPanel('spec')
  return true
}

// ── 开发入口：统一跳转到独立开发页，AI-Builder 不再嵌入第二套开发界面 ──
const AI_BUILDER_PENDING_CODING_KEY = 'ai_builder_pending_coding'
const codingDispatchToken = ref('')

function buildCodingRouteQuery(dispatchToken = '') {
  const appId = existingAppId.value || route.query.app_id
  const query: Record<string, string> = {}
  if (appId) query.app_id = String(appId)
  if (activeProjectId.value) query.project_id = String(activeProjectId.value)
  if (dispatchToken) {
    query.from_ai_builder = '1'
    query.dispatch = dispatchToken
  }
  return query
}

function openCodingWorkspace(dispatchToken = '') {
  router.push({
    path: '/coding',
    query: buildCodingRouteQuery(dispatchToken),
  })
}

// ── 平台配置 iframe ──
const platformIframeUrl = ref('')
const platformIframeKey = ref(0)
const platformAppUrl = ref('')  // 应用配置页 URL（登录后跳转用）
const platformDirectUrl = ref('')
const platformLoading = ref(false)
const platformError = ref('')
const platformLoginHint = ref('')
const platformIframeRef = ref<HTMLIFrameElement | null>(null)
const platformIframeAppId = ref<number | null>(null)
const platformIframeRepairTimer = ref<number | null>(null)

const buildPlatformProxyUrl = (appId: number) => {
  return buildPlatformProxyEntryUrl(appId, userStore.token || localStorage.getItem('token') || '')
}

const clearPlatformIframeRepairTimer = () => {
  if (platformIframeRepairTimer.value !== null) {
    window.clearInterval(platformIframeRepairTimer.value)
    platformIframeRepairTimer.value = null
  }
}

const onPlatformIframeLoad = () => {
  clearPlatformIframeRepairTimer()

  // 检测后端返回的错误页（通过 body 上的标记 data 属性）
  try {
    const iframe = platformIframeRef.value
    const doc = iframe?.contentDocument
    if (doc?.body?.dataset?.proxyError) {
      const text = doc.querySelector('h3')?.textContent || '平台页面加载失败'
      platformIframeUrl.value = ''
      platformError.value = text
      return
    }
    const repaired = repairPlatformIframe(iframe)
    const hasPasswordInput = !!doc?.querySelector('input[type="password"]')
    if (repaired && hasPasswordInput && iframe?.contentWindow) {
      const localAuth = iframe.contentWindow.localStorage.getItem('__vuex__local') || ''
      const sessionAuth = iframe.contentWindow.sessionStorage.getItem('__vuex__session') || ''
      if (localAuth && localAuth !== sessionAuth) {
        iframe.contentWindow.sessionStorage.setItem('__vuex__session', localAuth)
        iframe.contentWindow.location.reload()
      }
    }
  } catch { /* 跨域页面无法访问 contentDocument，忽略 */ }
}

const refreshCurrentAppRemoteMeta = async (appId: number) => {
  try {
    const apps = await applicationApi.list({ include_remote: true }) as any[]
    const current = apps.find((item: any) => String(item.id) === String(appId))
    currentRemoteStatus.value = current?.remote_status || ''
    platformDirectUrl.value = current?.apaas_url || platformDirectUrl.value || ''
    if (current?.apaas_app_id && store.currentApp) {
      store.currentApp = { ...store.currentApp, apaas_app_id: current.apaas_app_id, status: current.local_status || store.currentApp.status, remote_status: current.remote_status }
    }
  } catch {
    currentRemoteStatus.value = ''
  }
}

const loadPlatformUrl = async () => {
  if (!existingAppId.value) {
    platformError.value = '当前应用未关联，无法打开辅助搭建'
    return
  }
  platformLoading.value = true
  platformError.value = ''
  platformIframeUrl.value = ''
  platformIframeKey.value += 1
  await Promise.resolve()  // 让 Vue 渲染一帧，显示 loading 旋转器
  try {
    const proxyUrl = buildPlatformProxyUrl(existingAppId.value)
    platformIframeUrl.value = proxyUrl
    platformAppUrl.value = proxyUrl
    platformIframeAppId.value = existingAppId.value
    platformLoginHint.value = ''
  } catch (e: any) {
    platformError.value = e?.response?.data?.detail || e?.message || '获取平台链接失败'
  } finally {
    platformLoading.value = false
  }
}

const switchToPlatform = () => {
  activeView.value = 'platform'
  loadPlatformUrl()
}

const navigateIframeToApp = () => {
  if (platformIframeRef.value && platformAppUrl.value) {
    platformIframeRef.value.src = platformAppUrl.value
    platformLoginHint.value = ''
  }
}

const openPlatformNewTab = () => {
  const appId = existingAppId.value || platformIframeAppId.value
  if (appId) {
    const proxyUrl = buildPlatformProxyUrl(Number(appId))
    platformAppUrl.value = proxyUrl
    window.open(proxyUrl, '_blank', 'noopener,noreferrer')
    return
  }

  if (platformAppUrl.value || platformIframeUrl.value) {
    window.open(platformAppUrl.value || platformIframeUrl.value, '_blank', 'noopener,noreferrer')
  }
}

const publishCurrentApp = async () => {
  if (!existingAppId.value || publishingApp.value) return
  publishingApp.value = true
  try {
    await applicationApi.publish(existingAppId.value)
    await refreshCurrentAppRemoteMeta(existingAppId.value)
    ElMessage.success('应用已上线')
  } catch (e: any) {
    const detail = e?.response?.data?.detail || e?.message || '上线失败'
    if (isApaasTokenError(String(detail))) {
      ElMessage.warning('平台登录已失效，请先重新连接平台环境')
      store.showConnectModal = true
    } else {
      ElMessage.error(detail)
    }
  } finally {
    publishingApp.value = false
  }
}

const onIframeError = () => {
  clearPlatformIframeRepairTimer()
  platformError.value = '平台页面加载失败，可能不支持 iframe 嵌入'
}

const setActiveView = (view: 'builder' | 'platform' | 'coding') => {
  if (view === 'platform') {
    switchToPlatform()
  } else {
    activeView.value = 'builder'
  }
  persistAppActiveView(activeView.value)
}

const isGeneratedApplication = (app: any) => {
  const status = String(app?.status || app?.local_status || '').toLowerCase()
  return Boolean(app?.apaas_app_id || status === 'completed')
}

const restoreActiveViewForApp = async (app: any) => {
  if (!app?.id) {
    activeView.value = 'builder'
    return
  }

  const isDeployed = !!app.apaas_app_id || app.status === 'completed'
  if (!isDeployed) {
    activeView.value = 'builder'
    return
  }

  const requestedView = Array.isArray(route.query.view) ? route.query.view[0] : route.query.view
  const storageKey = getAppViewStorageKey(app.id)
  if (!requestedView && localStorage.getItem(storageKey) === 'coding') {
    localStorage.removeItem(storageKey)
  }
  // 2026-05-19 post-deploy 默认进 platform iframe（中间区域），避免空白黑屏；
  // 仅当显式 ?view=builder 才回到 builder 视图。
  activeView.value = requestedView === 'builder' ? 'builder' : 'platform'
  if (activeView.value === 'platform' && existingAppId.value) {
    loadPlatformUrl()
  }
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
const getFieldKey = (field: any, idx: number) => field?.code || field?.name || `field_${idx + 1}`
const getFieldLabel = (field: any) => field?.name || field?.code || '未命名字段'
const getRoleDescription = (role: any) => role?.description || role?.summary || '暂无职责描述'
const getPrimaryText = (...values: any[]) => {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return ''
}
const getRoleCodeValue = (role: any, fallback = '') =>
  getPrimaryText(role?.code, role?.roleCode, role?.role_code, fallback)
const getRoleNameValue = (role: any, fallback = '') =>
  getPrimaryText(role?.name, role?.roleName, role?.role_name, fallback)
const getDictCodeValue = (dict: any, fallback = '') =>
  getPrimaryText(dict?.code, dict?.dictionaryCode, dict?.dictionary_code, fallback)
const getDictNameValue = (dict: any, fallback = '') =>
  getPrimaryText(dict?.name, dict?.dictionaryName, dict?.dictionary_name, fallback)
const getDictOptionCodeValue = (option: any, fallback = '') =>
  getPrimaryText(option?.code, option?.item_code, option?.itemCode, option?.valueCode, fallback)
const getDictOptionNameValue = (option: any, fallback = '') =>
  getPrimaryText(option?.name, option?.item_name, option?.itemName, option?.valueName, fallback)
const getModelCodeValue = (model: any, fallback = '') =>
  getPrimaryText(model?.code, model?.modelCode, model?.model_code, fallback)
const getModelNameValue = (model: any, fallback = '') =>
  getPrimaryText(model?.name, model?.modelName, model?.model_name, fallback)
const getFieldCodeValue = (field: any, fallback = '') =>
  getPrimaryText(field?.code, field?.fieldCode, field?.field_code, fallback)
const getFieldNameValue = (field: any, fallback = '') =>
  getPrimaryText(field?.name, field?.fieldName, field?.field_name, fallback)
const getFieldTypeValue = (field: any) =>
  getPrimaryText(field?.type, field?.fieldType, field?.field_type, '文本')
const getTableTypeLabel = (value: any) =>
  /sub|child|子表/.test(String(value || '').toLowerCase()) ? '子表' : '主表'
const getFormCodeValue = (form: any, fallback = '') =>
  getPrimaryText(form?.code, form?.formCode, form?.form_code, form?.menuCode, fallback)
const getFormNameValue = (form: any, fallback = '') =>
  getPrimaryText(form?.name, form?.formName, form?.form_name, fallback)
const getFormModelCodeValue = (form: any, fallback = '') =>
  getPrimaryText(
    form?.modelCode,
    form?.model_code,
    form?.tableModelCode,
    form?.table_model_code,
    Array.isArray(form?.allModelCodes) ? form.allModelCodes[0] : '',
    Array.isArray(form?.all_model_codes) ? form.all_model_codes[0] : '',
    fallback,
  )
const getFormComponentCodeValue = (component: any, fallback = '') =>
  getPrimaryText(component?.model_field, component?.modelField, component?.code, component?.componentCode, component?.component_code, fallback)
const getFormComponentNameValue = (component: any, fallback = '') =>
  getPrimaryText(component?.name, component?.label, component?.fieldName, component?.field_name, fallback)
const getFormComponentDetailValue = (component: any) => {
  const binding = getPrimaryText(component?.model_field, component?.modelField)
  const tableModel = getPrimaryText(component?.table_model_code, component?.tableModelCode)
  const componentType = getPrimaryText(component?.component_type, component?.componentType)
  const changedProps = Array.isArray(component?.changed_properties)
    ? component.changed_properties.filter(Boolean).join('、')
    : ''
  return getPrimaryText(
    binding ? `绑定 ${binding}` : '',
    tableModel ? `子表 ${tableModel}` : '',
    componentType ? `组件类型 ${componentType}` : '',
    changedProps ? `变更属性 ${changedProps}` : '',
    '表单组件',
  )
}
const getModelFieldSource = (model: any) =>
  Array.isArray(model?.fields)
    ? model.fields
    : Array.isArray(model?.dataModelFields)
      ? model.dataModelFields
      : []
const getFormComponentSource = (form: any) =>
  Array.isArray(form?.components)
    ? form.components
    : Array.isArray(form?.fields)
      ? form.fields
      : []
const agents: Record<string, { name: string; icon: string }> = {
  builder: { name: 'aPaaS Builder AI', icon: '🤖' },
  requirements: { name: 'aPaaS Builder AI', icon: '🤖' },
  assistant: { name: '辅助开发智能体', icon: '🛠️' },
  developer: { name: '复杂开发智能体', icon: '💻' }
}

if (store.previewTab === 'workflow') {
  store.previewTab = 'overview'
}

const messages = reactive<Message[]>([])
resetMessagesToWelcome()

const scrollToBottom = () => { nextTick(() => { if (messagesRef.value) messagesRef.value.scrollTop = messagesRef.value.scrollHeight }) }

const STREAMING_ASSISTANT_ID = -1

const isStreamingAssistantMessage = (msg: Message) =>
  msg.role === 'assistant' && msg.id === streamingAssistantMessageId.value

const findStreamingAssistantMessage = () => {
  const lastMsg = messages[messages.length - 1]
  if (lastMsg && lastMsg.role === 'assistant' && lastMsg.id === STREAMING_ASSISTANT_ID) {
    return lastMsg
  }
  return null
}

const setStreamingAssistantMessage = (content: string) => {
  const normalized = content.trim() || '正在处理...'
  isTyping.value = false
  streamingAssistantMessageId.value = STREAMING_ASSISTANT_ID
  const existing = findStreamingAssistantMessage()
  if (existing) {
    existing.content = normalized
  } else {
    messages.push({
      id: STREAMING_ASSISTANT_ID,
      role: 'assistant',
      agent: currentAgent.value,
      content: normalized,
      created_at: ''
    })
  }
  scrollToBottom()
}

const replaceOrAppendAssistantMessage = (content: string, agent = currentAgent.value) => {
  const existing = findStreamingAssistantMessage()
  if (existing) {
    existing.id = Date.now()
    existing.agent = agent
    existing.content = content
  } else {
    messages.push({
      id: Date.now(),
      role: 'assistant',
      agent,
      content,
      created_at: ''
    })
  }
  streamingAssistantMessageId.value = null
  isTyping.value = false
  scrollToBottom()
}

const clearChangePlanExecutionMessages = () => {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const content = String(messages[i]?.content || '')
    if (
      content === '正在执行变更计划...'
      || content.startsWith('⏳ ')
      || content.startsWith('✅ 变更计划执行完成！')
      || content.startsWith('❌ 变更执行失败:')
    ) {
      messages.splice(i, 1)
    }
  }
}

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
        store.currentApp = { status: 'draft' }
        store.setAppName(parsed.data.appName)
        store.preview.roles = parsed.data.roles || []
        store.preview.dicts = parsed.data.dicts || []
        store.preview.models = parsed.data.models || []
        store.preview.forms = parsed.data.forms || []
        store.preview.workflows = parsed.data.workflows || []
        store.preview.permissions = parsed.data.permissions || []
        setPreviewCustomDevelopment(parsed.data)

        // 自动创建 Application（如果还没有）
        if (!existingAppId.value && parsed.data.appName) {
          applicationApi.autoCreate({
            app_name: parsed.data.appName,
            config_preview: parsed.data,
            conversation_id: conversationId.value || undefined,
            project_id: activeProjectId.value,
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

const persistCurrentPreview = async () => {
  if (!existingAppId.value || !store.preview.appName) return
  try {
    const appCode = parsedAppCode.value || loadedAppCode.value || buildAppCode(store.preview.appName)
    const updated = await applicationApi.update(existingAppId.value, {
      conversation_id: conversationId.value || undefined,
      app_name: store.preview.appName,
      app_code: appCode,
      description: store.preview.appName,
      config_preview: { type: 'preview', data: currentPreviewConfigPayload.value }
    })
    loadedAppCode.value = (updated as any)?.app_code || appCode
  } catch (e) {
    console.warn('Failed to persist patched preview:', e)
  }
}

const extractPatchData = async (content: string) => {
  const allMatches = [...content.matchAll(/```json\s*([\s\S]*?)```/g)]
  if (allMatches.length === 0) return false

  let applied = false
  for (const match of allMatches) {
    try {
      const parsed = JSON.parse((match[1] || '').trim())
      if (parsed?.type !== 'patch' || !Array.isArray(parsed?.actions)) continue
      const actions = validateAndFixActions(parsed.actions)
      if (!actions.length) continue
      applyPatch(actions)
      applied = true
    } catch (e) {
      console.error('Failed to parse patch JSON block:', e)
    }
  }

  if (applied) {
    await persistCurrentPreview()
  }
  return applied
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
    store.currentApp = { status: 'draft' }
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

// AI-Builder 模块定位：基于文档生成/更新应用
// 用 AI 调整应用：在 Builder 同页内打开右侧抽屉装 AppChatPanel（同 Vue 实例 / 同主题，
// 不跳页不 iframe）。改完点抽屉里「应用最新 md 到 Builder」→ 走 upload-doc-version
const appChatDrawerOpen = ref(false)
function openAppChatDrawer() {
  if (!existingAppId.value) return
  appChatDrawerOpen.value = true
}
async function onAppChatPanelApplied(payload: { filename: string; content: string }) {
  if (!existingAppId.value || !payload.content?.trim()) return
  appChatDrawerOpen.value = false
  const file = new File([payload.content], payload.filename || `${store.preview.appName || 'app'}-设计文档.md`, {
    type: 'text/markdown',
  })
  try {
    await handleDocVersionUpload(file, existingAppId.value, {
      userMessageContent: '从 AI 对话拉取最新设计文档并应用',
      title: '应用最新 md',
      forceNewConversation: false,
    })
  } catch (err: any) {
    ElMessage.error(`应用失败：${err?.response?.data?.detail || err?.message || err}`)
  }
}

// 从 AIChat 跳过来时记录来源 (session_id, filename)；建应用成功后写 localStorage dedup 缓存，
// 同来源再点 → Builder 不会重复建
const pendingMdSource = ref<{ sessionId: number | string | null; filename: string } | null>(null)
const MD_TO_BUILDER_CACHE_KEY = 'mdToBuilderAppMap'
function recordMdToBuilderCache(appId: number | null | undefined) {
  if (!appId || !pendingMdSource.value || !pendingMdSource.value.sessionId) return
  const { sessionId, filename } = pendingMdSource.value
  pendingMdSource.value = null
  try {
    const raw = localStorage.getItem(MD_TO_BUILDER_CACHE_KEY)
    const map = raw ? JSON.parse(raw) : {}
    map[`${sessionId}::${filename}`] = appId
    localStorage.setItem(MD_TO_BUILDER_CACHE_KEY, JSON.stringify(map))
  } catch { /* ignore */ }
}

// ── Requirements mode ──
const isRequirementsMode = computed(() => currentAgent.value === 'requirements')
// 独立需求会话进入 SPEC 画布；已有应用详情固定使用构建预览，避免异步历史会话把页面切走。
const useSpecMode = computed(() => currentAgent.value === 'requirements' && !existingAppId.value)
// SPEC 三栏布局是否已展开（默认 false：先 Claude 风格纯对话）
// 与 useSpecMode 解耦：useSpecMode=true 时后端依然走 SPEC 状态机，只是前端默认收起 panel
// AI 自主判定信号（任一满足即展开）：
//   1. SPEC phase 离开 gathering（LLM 调了 transition_phase 工具）
//   2. spec 实质内容已被填充（goal/objects/roles/dicts 任一非空 → bootstrap_from_doc 已写入数据）
//   3. doc_pipeline 已把解析结果推到 store.preview（上传 md 时 specStore 还没建好的兜底信号）
const specPanelExpanded = ref(false)
const specHasMaterialContent = computed(() => {
  const s = specStore.current
  if (!s) return false
  return !!s.goal
    || (Array.isArray(s.objects) && s.objects.length > 0)
    || (Array.isArray(s.roles) && s.roles.length > 0)
    || (Array.isArray(s.dicts) && s.dicts.length > 0)
})
watch(
  [() => specStore.phase, specHasMaterialContent, hasStructuredPreviewData],
  ([newPhase, hasContent, hasPreview]) => {
    if (specPanelExpanded.value || !useSpecMode.value) return
    const phaseAdvanced = !!newPhase && newPhase !== 'gathering'
    if (phaseAdvanced || hasContent || hasPreview) {
      specPanelExpanded.value = true
    }
  },
  { immediate: true },
)
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

// ─────────── v2 redesign (Session 5) adapters ───────────
// 把现有 store.preview SPEC 适配到 AppBlueprintPanel 的 strict prop shape；
// ChatConversationList 接收 {id,title,updatedAt}[] —— 用现有 conversationList 映射。
const blueprintSpec = computed(() => buildBlueprintSpec(store.preview as any))
const currentIndustryPack = computed<{ name: string; objectCount: number } | null>(() => null)
const v2ConversationItems = computed(() => conversationList.value.map((c) => ({
  id: String(c.id),
  title: getConversationLabel(c),
  updatedAt: formatConvTime(c.updated_at || c.created_at || ''),
})))
const v2CurrentConversationId = computed(() => selectedConversationId.value != null ? String(selectedConversationId.value) : '')
function onV2OpenConversation(id: string) {
  const cid = Number(id)
  if (!Number.isFinite(cid)) return
  loadConversation(cid)
}
// Session 6: open the v2 deploy-confirm modal instead of firing the deploy
// immediately. The modal's `@confirm` event calls `runDeploy(env)` which still
// routes through the existing `startDeployFromArtifact()` path.
const deployConfirmOpen = ref(false)
const deployChanges = computed(() => ([] as { kind: '+' | '~' | '-'; what: string }[]))
const deployImpacts = computed(() => ({
  affectedUsers: 0,
  addedFlows: 0,
  needMigration: false,
  etaMinutes: 2,
}))
function openDeployModal() {
  deployConfirmOpen.value = true
}
function runDeploy(_env: 'dev' | 'test' | 'prod') {
  // TODO: pass `_env` through to startDeployFromArtifact when the backend
  // supports per-environment deploys. For now the existing handler always
  // deploys to the user's connected aPaaS env.
  startDeployFromArtifact()
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
        const normalizedContent = msg.role === 'assistant'
          ? normalizeLoadedAssistantContent(msg.content)
          : msg.content
        messages.push({
          id: msg.id,
          role: msg.role as any,
          agent: msg.role === 'assistant' ? 'builder' : undefined,
          content: normalizedContent,
          created_at: msg.created_at
        })
        if (msg.role === 'assistant') {
          extractPreviewData(normalizedContent)
        }
      }
      scrollToBottom()
    } else {
      // 空对话，显示欢迎消息
      currentAgent.value = 'requirements'
      resetMessagesToWelcome()
    }

    // 恢复关联的应用配置
    if (!store.preview.appName && store.preview.models.length === 0) {
      try {
        const apps = await applicationApi.list() as any[]
        const linkedApp = apps.find((a: any) => a.conversation_id === cid && a.config_preview)
        if (linkedApp?.config_preview) {
          const data = linkedApp.config_preview.data || linkedApp.config_preview
          store.setAppName(data.appName)
          store.preview.models = data.models || []
          store.preview.forms = data.forms || []
          store.preview.dicts = data.dicts || []
          store.preview.roles = data.roles || []
          store.preview.workflows = data.workflows || []
          store.preview.permissions = data.permissions || []
          setPreviewCustomDevelopment(data)
          store.currentApp = { status: 'draft' }
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
  currentAgent.value = 'requirements'
  resetMessagesToWelcome()
  router.replace('/chat')
}

// ── 文档版本 ──
interface DocVersion {
  id: number
  version: number
  filename: string
  summary: string
  raw_content: string
  parsed_config?: any
  created_at: string
  change_plans?: any[]
  display_version?: number
  display_filename?: string
}
interface DocVersionListItem extends DocVersion {
  key: string
  isVirtual?: boolean
}
interface ChangeBadgeMeta {
  label: string
  tone: 'create' | 'update' | 'delete' | 'disable'
}
const docVersions = ref<DocVersion[]>([])
const docVersionsLoading = ref(false)
const docVersionHistoryOpen = ref(false)
const updatingDocVersion = ref(false)
const executingChangePlan = ref(false)
const docVersionPreviewVisible = ref(false)
const docVersionPreviewContent = ref('')
const docVersionPreviewItem = ref<DocVersionListItem | null>(null)
const docVersionPreviewTitle = ref('')
const docFullscreenVisible = ref(false)
const docFullscreenContent = ref('')
const docFullscreenItem = ref<DocVersionListItem | null>(null)
const docFullscreenTitle = ref('')
const docVersionDiffVisible = ref(false)
const docVersionDiffLeft = ref('')
const docVersionDiffRight = ref('')
const docVersionDiffLeftTitle = ref('')
const docVersionDiffRightTitle = ref('')
const docVersionDiffLeftItem = ref<DocVersionListItem | null>(null)
const docVersionDiffRightItem = ref<DocVersionListItem | null>(null)
const expandedDocVersionKey = ref<string | null>(null)
const selectedDocVersionKey = ref<string | null>(null)
const deletingDocVersionId = ref<number | null>(null)
const currentDocVersionNumber = ref(1)
const docVersionInputRef = ref<HTMLInputElement>()
const reparseInputRef = ref<HTMLInputElement>()
const reparsing = ref(false)
const currentDocPreviewOverride = ref<DocVersionListItem | null>(null)
// docUploadInputRef removed — upload is via chat input only

const getDocDisplayVersion = (ver?: Pick<DocVersion, 'version' | 'display_version'> | null) =>
  Number(ver?.display_version || ver?.version || 0)

const getDocDisplayFilename = (ver?: Pick<DocVersion, 'filename' | 'display_filename'> | null) =>
  String(ver?.display_filename || ver?.filename || '').trim()

const sortedDocVersions = computed(() =>
  [...docVersions.value].sort((a, b) => (b.version || 0) - (a.version || 0))
)
const displayDocVersions = computed<DocVersionListItem[]>(() => {
  const versions = sortedDocVersions.value.map((ver, index, list) => {
    const normalizedVersion = getDocDisplayVersion(ver) || Math.max(1, list.length - index)
    const fallbackFilename = lastParsedFilename.value || `${store.preview.appName || '功能设计文档'}-V${normalizedVersion}.md`
    return {
      ...ver,
      display_version: normalizedVersion,
      display_filename: getDocDisplayFilename(ver) || fallbackFilename,
      filename: ver.filename || fallbackFilename,
      summary: ver.summary || '点击展开查看设计文档',
      raw_content: (ver.raw_content || '').trim(),
      key: `doc-version-${ver.id || normalizedVersion}-${index}`,
    }
  })

  if (versions.length > 0) return versions

  const fallbackContent = String(latestDocContent.value || '').trim()
  if (!fallbackContent) return []

  return [{
    id: -1,
    version: 1,
    filename: lastParsedFilename.value || `${store.preview.appName || '功能设计文档'}-V1.md`,
    summary: '初始版本，点击展开查看设计文档',
    raw_content: fallbackContent,
    created_at: '',
    key: 'doc-version-v1',
    isVirtual: true,
  }]
})
const currentDocVersionItem = computed<DocVersionListItem | null>(() => currentDocPreviewOverride.value || displayDocVersions.value[0] || null)
const currentDocVersion = computed(() => currentDocVersionNumber.value || getDocDisplayVersion(currentDocVersionItem.value) || 1)
const selectedDocVersionItem = computed<DocVersionListItem | null>(() => {
  if (currentDocPreviewOverride.value) return currentDocPreviewOverride.value
  if (selectedDocVersionKey.value) {
    const matched = displayDocVersions.value.find(item => item.key === selectedDocVersionKey.value)
    if (matched) return matched
  }
  return displayDocVersions.value[0] || null
})
const docVersionStructuredResult = (item?: Pick<DocVersion, 'parsed_config' | 'raw_content'> | null, fallbackConfig?: any) => {
  // appName 原则：优先用传入数据里的名字（历史 version 可能跟当前不同），
  // 否则回退到 store.preview.appName（store 的 setAppName 已过滤掉默认占位值）
  const parsed = item?.parsed_config?.data || item?.parsed_config
  if (parsed && typeof parsed === 'object') {
    return buildStructuredDocFromPreviewConfig(parsed, {
      appName: parsed.appName || store.preview.appName,
      appCode: parsed.appCode || extractAppCodeFromText(String(item?.raw_content || '')),
    })
  }
  if (fallbackConfig && typeof fallbackConfig === 'object') {
    return buildStructuredDocFromPreviewConfig(fallbackConfig, {
      appName: fallbackConfig.appName || store.preview.appName,
      appCode: fallbackConfig.appCode || displayAppCode.value,
    })
  }
  return null
}
const selectedDocStructuredResult = computed(() => {
  return docVersionStructuredResult(selectedDocVersionItem.value, hasStructuredPreviewData.value ? currentPreviewConfigPayload.value : null)
})
const liveStructuredDocResult = computed(() => (
  selectedDocStructuredResult.value || docResultForCard.value || null
))

const resolveDocDisplayContent = (item?: Pick<DocVersion, 'version' | 'raw_content' | 'parsed_config'> | null): string => {
  const raw = String(item?.raw_content || '').trim()
  if (raw) return raw

  const isCurrentVersion = !!item && getDocDisplayVersion(item) === Number(currentDocVersion.value || 0)
  if (isCurrentVersion && hasStructuredPreviewData.value) {
    const latestMarkdown = buildDocMarkdownFromPreview(currentPreviewConfigPayload.value).trim()
    if (latestMarkdown) return latestMarkdown
  }

  const rebuilt = item?.parsed_config ? buildDocMarkdownFromVersion(item as DocVersionListItem) : ''
  return rebuilt || String(latestDocContent.value || '').trim() || chatGeneratedDocContent.value
}

const selectedDocDisplayContent = computed<string>(() => resolveDocDisplayContent(selectedDocVersionItem.value))
const docVersionPreviewStructuredResult = computed(() => {
  return docVersionStructuredResult(docVersionPreviewItem.value)
})
const docFullscreenStructuredResult = computed(() => {
  return docVersionStructuredResult(docFullscreenItem.value, hasPreviewContent.value ? currentPreviewConfigPayload.value : null)
})
const docVersionDiffLeftStructuredResult = computed(() => {
  return docVersionStructuredResult(docVersionDiffLeftItem.value)
})
const docVersionDiffRightStructuredResult = computed(() => {
  return docVersionStructuredResult(docVersionDiffRightItem.value)
})
const structuredDocDiffMeta = computed(() => {
  return computeStructuredDocDiff(docVersionDiffLeftStructuredResult.value, docVersionDiffRightStructuredResult.value)
})
const showVersionManager = computed(() => !!existingAppId.value)
const isDocVersionTransientFix = (version: any) => {
  const filename = String(version?.filename || '').toLowerCase()
  const summary = String(version?.summary || '')
  return filename.includes('conflict-fix-v')
    || filename.includes('app-code-fix-v')
    || summary.includes('编码冲突修复')
    || summary.includes('应用编码修复')
}

const buildNormalizedDocVersionFilename = (filename: string, version: number) => {
  const raw = String(filename || '').trim()
  const fallbackBase = store.preview.appName || '功能设计文档'
  const withoutExt = raw.replace(/\.md$/i, '')
  const stripped = withoutExt
    .replace(/[-_ ]v\d+$/i, '')
    .replace(/v\d+$/i, '')
    .trim()
  const base = stripped || fallbackBase
  return `${base}-V${version}.md`
}

const normalizeDocVersionsForDisplay = (rawVersions: any[], rawCurrentVersion: number) => {
  const sortedAsc = [...rawVersions].sort((a: any, b: any) => (Number(a?.version) || 0) - (Number(b?.version) || 0))
  if (sortedAsc.length <= 1) {
    return {
      versions: sortedAsc,
      currentVersion: rawCurrentVersion || Number(sortedAsc[0]?.version || 0) || 0,
    }
  }

  let transientTailIndex = 0
  while (transientTailIndex + 1 < sortedAsc.length) {
    const next = sortedAsc[transientTailIndex + 1]
    const hasChangePlans = Array.isArray(next?.change_plans) && next.change_plans.length > 0
    if (hasChangePlans || !isDocVersionTransientFix(next)) break
    transientTailIndex += 1
  }

  const collapsedInitialChain = transientTailIndex > 0
    ? [sortedAsc[transientTailIndex], ...sortedAsc.slice(transientTailIndex + 1)]
    : sortedAsc

  const normalizedVersions = collapsedInitialChain.map((version: any, index: number) => ({
    ...version,
    display_version: index + 1,
    display_filename: buildNormalizedDocVersionFilename(String(version?.filename || ''), index + 1),
  }))

  let currentVersion = rawCurrentVersion
  if (currentVersion > 0) {
    const actualCurrent = collapsedInitialChain.findIndex((item: any) => Number(item?.version) === currentVersion)
    currentVersion = actualCurrent >= 0 ? actualCurrent + 1 : Number(normalizedVersions[0]?.display_version || 0)
  } else {
    currentVersion = Number(normalizedVersions[normalizedVersions.length - 1]?.display_version || normalizedVersions[0]?.display_version || 0)
  }

  return {
    versions: normalizedVersions.sort((a: any, b: any) => (Number(b?.version) || 0) - (Number(a?.version) || 0)),
    currentVersion,
  }
}

const getDocVersionsPayload = (raw: any) => {
  const rawVersions = Array.isArray(raw) ? raw : (raw?.versions || raw?.data || [])
  const rawCurrentVersion = Number(raw?.current_version ?? raw?.currentVersion ?? rawVersions?.[0]?.version ?? 0) || 0
  return normalizeDocVersionsForDisplay(rawVersions, rawCurrentVersion)
}

const findRestorableChangePlanId = (versions: any[], currentVersion?: number) => {
  const sortedVersions = [...versions].sort((a: any, b: any) => (Number(b?.version) || 0) - (Number(a?.version) || 0))
  const currentVersionItem = currentVersion
    ? sortedVersions.find((item: any) => getDocDisplayVersion(item) === Number(currentVersion))
    : null
  const scanList = currentVersionItem
    ? [currentVersionItem, ...sortedVersions.filter(item => item !== currentVersionItem)]
    : sortedVersions

  for (const version of scanList) {
    const plans = Array.isArray(version?.change_plans) ? version.change_plans : []
    const matchedPlan = plans.find((plan: any) => {
      const status = String(plan?.status || '').toLowerCase()
      return Number(plan?.from_version || 0) > 0 && (status === 'pending' || status === 'confirmed')
    })
    if (matchedPlan?.id) return Number(matchedPlan.id)
  }
  return null
}

const normalizeChangePlanState = (raw: any) => {
  if (!raw) return null
  const toVersion = Number(raw.to_version ?? raw.toVersion ?? raw.version ?? 1) || 1
  const fromVersion = Number(raw.from_version ?? raw.fromVersion ?? (raw.is_first_version ? 0 : Math.max(0, toVersion - 1))) || 0
  const diffSummary = raw.diff_summary ?? raw.diffSummary ?? raw.diff ?? null
  const resourceDiff = raw.resourceDiff ?? (diffSummary && typeof diffSummary === 'object' ? diffSummary : null)
  const diffSummaryText = typeof diffSummary === 'string' ? diffSummary : (resourceDiff?.summary || raw.summary || '')
  const actions = Array.isArray(raw.actions)
    ? raw.actions.map((action: any) => ({
        ...action,
        selected: action.selected !== undefined ? action.selected : true,
      }))
    : []

  return {
    ...raw,
    id: raw.change_plan_id || raw.id,
    fromVersion,
    toVersion,
    resourceDiff,
    diffSummary: diffSummaryText,
    actions,
    status: raw.status || 'pending',
  }
}

const applyChangePlanState = (raw: any) => {
  const normalized = normalizeChangePlanState(raw)
  store.changePlan = normalized
  store.showChangePlan = !!normalized
}

const clearChangePlanState = () => {
  store.showChangePlan = false
  store.changePlan = null
}

/** 用户主动取消更新：调后端回滚 + 清前端状态 */
const cancelChangePlanAction = async () => {
  const appId = existingAppId.value
  const planId = (store.changePlan as any)?.id
  if (appId && planId) {
    try {
      await applicationApi.cancelChangePlan(appId, planId)
    } catch (e: any) {
      console.error('取消变更计划失败', e)
      ElMessage.warning('取消失败，但已退出更新视图')
    }
  }
  clearChangePlanState()
  // 回滚后刷新版本列表和应用信息（状态从 updating → completed）
  await fetchDocVersions()
}

const isUpdateReviewMode = computed(() =>
  !!existingAppId.value && !!store.changePlan
)
const updateResourceDiff = computed<any | null>(() => {
  const diff = store.changePlan?.resourceDiff
  return diff && typeof diff === 'object' ? diff : null
})

// ── 更新审查：文档对比视图数据 ───────────────────────────────
// isUpdateReviewMode 下右侧不再展示"资源差异 card"，而是复用文档渲染：
// 顶部 banner + 单栏 StructuredDocDiffRenderer（基于 V1↔V2 文档对比
// 计算出的 diff-meta 做字段级高亮）。
const updateReviewV1DocItem = computed<DocVersionListItem | null>(() => {
  if (!isUpdateReviewMode.value) return null
  const fromVer = Number((store.changePlan as any)?.fromVersion ?? (store.changePlan as any)?.from_version ?? 0)
  if (!fromVer) return null
  return displayDocVersions.value.find(item => getDocDisplayVersion(item) === fromVer) || null
})

const updateReviewV2DocItem = computed<DocVersionListItem | null>(() => {
  if (!isUpdateReviewMode.value) return null
  const toVer = Number((store.changePlan as any)?.toVersion ?? (store.changePlan as any)?.to_version ?? 0)
  if (toVer) {
    const matched = displayDocVersions.value.find(item => getDocDisplayVersion(item) === toVer)
    if (matched) return matched
  }
  return displayDocVersions.value[0] || null
})

const updateReviewLeftDocResult = computed(() =>
  docVersionStructuredResult(updateReviewV1DocItem.value)
)

const updateReviewRightDocResult = computed(() =>
  docVersionStructuredResult(updateReviewV2DocItem.value, hasStructuredPreviewData.value ? currentPreviewConfigPayload.value : null)
)

const updateReviewDiffMeta = computed(() =>
  computeStructuredDocDiff(updateReviewLeftDocResult.value, updateReviewRightDocResult.value)
)

interface UpdateReviewBannerItem {
  icon: string
  label: string
  count: number
}

const updateReviewChangeSummary = computed<UpdateReviewBannerItem[]>(() => {
  if (!isUpdateReviewMode.value) return []
  return [
    { icon: '👥', label: '角色', count: updateRoleDiffItems.value.length },
    { icon: '📖', label: '字典', count: updateDictDiffItems.value.length },
    { icon: '🗃', label: '模型', count: updateModelDiffItems.value.length },
    { icon: '📋', label: '表单', count: updateFormDiffItems.value.length },
  ].filter(item => item.count > 0)
})
const docDiffStats = computed(() => ({
  added: docVersionDiffLeftStructuredResult.value || docVersionDiffRightStructuredResult.value
    ? structuredDocDiffMeta.value.stats.added
    : docDiffResult.value.right.filter(line => line.type === 'added').length,
  removed: docVersionDiffLeftStructuredResult.value || docVersionDiffRightStructuredResult.value
    ? structuredDocDiffMeta.value.stats.removed
    : docDiffResult.value.left.filter(line => line.type === 'removed').length,
  modified: docVersionDiffLeftStructuredResult.value || docVersionDiffRightStructuredResult.value
    ? structuredDocDiffMeta.value.stats.modified
    : 0,
  same: docVersionDiffLeftStructuredResult.value || docVersionDiffRightStructuredResult.value
    ? structuredDocDiffMeta.value.stats.same
    : docDiffResult.value.right.filter(line => line.type === 'same').length,
}))
const changePlanSelectedCount = computed(() =>
  Array.isArray(store.changePlan?.actions)
    ? store.changePlan.actions.filter((action: any) => action.selected !== false).length
    : 0
)
const changePlanTotalCount = computed(() =>
  Array.isArray(store.changePlan?.actions) ? store.changePlan.actions.length : 0
)
const changePlanGroups = computed(() => {
  const actions = Array.isArray(store.changePlan?.actions) ? store.changePlan.actions : []
  const groupDefs = [
    { key: 'roles', title: '角色', matcher: (op: string) => op.includes('role') },
    { key: 'dicts', title: '数据字典', matcher: (op: string) => op.includes('dict') },
    { key: 'models', title: '数据模型', matcher: (op: string) => op.includes('model') || op.includes('field') },
    { key: 'forms', title: '表单', matcher: (op: string) => op.includes('form') || op.includes('menu') },
    { key: 'permissions', title: '权限', matcher: (op: string) => op.includes('permission') },
    { key: 'other', title: '其他', matcher: (_op: string) => true },
  ]
  const groupMap = new Map(groupDefs.map(group => [group.key, { key: group.key, title: group.title, actions: [] as any[] }]))

  actions.forEach((action: any) => {
    const op = String(action.op || '').toLowerCase()
    const matchedGroup = groupDefs.find(group => group.key !== 'other' && group.matcher(op)) || groupDefs[groupDefs.length - 1]
    groupMap.get(matchedGroup.key)?.actions.push(action)
  })

  return Array.from(groupMap.values()).filter(group => group.actions.length > 0)
})

const getActionGroupKey = (action: any) => {
  const op = String(action?.op || '').toLowerCase()
  if (op.includes('role')) return 'roles'
  if (op.includes('dict')) return 'dicts'
  if (op.includes('model') || op.includes('field')) return 'models'
  if (op.includes('form') || op.includes('menu')) return 'forms'
  if (op.includes('permission')) return 'permissions'
  return 'other'
}

const buildUpdateExecutionItems = (actions: any[]) =>
  actions
    .filter((action: any) => action?.selected !== false)
    .map((action: any, index: number) => ({
      id: String(action.id || `update-action-${index}`),
      groupKey: getActionGroupKey(action),
      label: String(action.description || action.name || action.target || action.code || `步骤 ${index + 1}`),
      code: String(action.code || action.target || action.model || ''),
      op: String(action.op || ''),
      status: 'pending' as const,
      detail: '',
    }))

const completeCurrentUpdateExecutionItems = () => {
  updateExecutionItems.value = updateExecutionItems.value.map((item) =>
    item.status === 'current' ? { ...item, status: 'completed' } : item
  )
}

const markUpdateExecutionStage = (stage: string, stepText: string) => {
  const normalizedStage = String(stage || '').toLowerCase()
  const normalizedStepText = String(stepText || '')
  updateExecutionStage.value = normalizedStage
  updateExecutionStepText.value = normalizedStepText

  if (!updateExecutionItems.value.length) return

  let targetGroupKey = ''
  if (normalizedStage.includes('role')) targetGroupKey = 'roles'
  else if (normalizedStage.includes('dict')) targetGroupKey = 'dicts'
  else if (normalizedStage.includes('model')) targetGroupKey = 'models'
  else if (normalizedStage.includes('form')) targetGroupKey = 'forms'
  else if (normalizedStage.includes('permission') || normalizedStage.includes('process')) targetGroupKey = 'permissions'

  const matchName = normalizedStepText.split(':').slice(1).join(':').trim()
  let matched = false

  updateExecutionItems.value = updateExecutionItems.value.map((item) => {
    if (item.status === 'completed' || item.status === 'error') return item
    const sameGroup = !targetGroupKey || item.groupKey === targetGroupKey
    const textMatched = matchName && (item.label.includes(matchName) || item.code.includes(matchName))

    if (!matched && sameGroup && (textMatched || (!matchName && item.status === 'pending'))) {
      matched = true
      return { ...item, status: 'current', detail: normalizedStepText }
    }

    if (item.status === 'current') return { ...item, status: 'completed', detail: item.detail }
    return item
  })
}

function hydratePreviewFromConfig(rawConfig: any) {
  const data = rawConfig?.data || rawConfig
  if (!data || typeof data !== 'object') return false
  const hasConfig = !!data.appName
    || Array.isArray(data.models) && data.models.length > 0
    || Array.isArray(data.forms) && data.forms.length > 0
  if (!hasConfig) return false

  store.setAppName(data.appName)
  store.preview.models = data.models || []
  store.preview.forms = data.forms || []
  store.preview.dicts = data.dicts || []
  store.preview.roles = data.roles || []
  store.preview.workflows = data.workflows || []
  store.preview.permissions = data.permissions || []
  setPreviewCustomDevelopment(data)
  if (data.appCode) {
    parsedAppCode.value = data.appCode
  }
  if (!store.currentApp) {
    store.currentApp = { status: 'draft' }
  }
  parseReady.value = store.preview.models.length > 0 || store.preview.forms.length > 0
  return true
}

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
    const { versions, currentVersion } = getDocVersionsPayload(res)
    docVersions.value = versions
    currentDocVersionNumber.value = currentVersion || Number(versions?.[0]?.version || 1)
    currentDocPreviewOverride.value = null
    if (!selectedDocVersionKey.value || !displayDocVersions.value.some(item => item.key === selectedDocVersionKey.value)) {
      selectedDocVersionKey.value = displayDocVersions.value[0]?.key || null
    }
    if (!hasStructuredPreviewData.value && versions.length) {
      const sortedVersions = [...versions].sort((a: any, b: any) => (Number(b?.version) || 0) - (Number(a?.version) || 0))
      const latest = sortedVersions.find((item: any) => getDocDisplayVersion(item) === currentVersion) || sortedVersions[0]
      if (latest?.parsed_config && hydratePreviewFromConfig(latest.parsed_config)) {
        latestDocContent.value = latest.raw_content || ''
        latestDocAppId.value = existingAppId.value
        latestDocConversationId.value = conversationId.value
        if (latest?.filename || latest?.display_filename) lastParsedFilename.value = getDocDisplayFilename(latest)
      }
    }
  } catch (e) {
    console.error('Failed to fetch doc versions', e)
  } finally {
    docVersionsLoading.value = false
  }
}

const loadLatestDocForApp = async (appId: number) => {
  try {
    const verRes: any = await applicationApi.getDocVersions(appId)
    const { versions, currentVersion } = getDocVersionsPayload(verRes)
    docVersions.value = versions
    currentDocVersionNumber.value = currentVersion || Number(versions?.[0]?.version || 1)
    const sortedVersions = [...versions].sort((a: any, b: any) => (Number(b?.version) || 0) - (Number(a?.version) || 0))
    const latest = sortedVersions.find((item: any) => getDocDisplayVersion(item) === currentVersion) || sortedVersions[0]
    if (latest?.filename || latest?.display_filename) lastParsedFilename.value = getDocDisplayFilename(latest)
    latestDocContent.value = latest?.raw_content || ''
    latestDocAppId.value = appId
    latestDocConversationId.value = null
    if (latest?.parsed_config) {
      const parsed = latest.parsed_config?.data || latest.parsed_config
      store.setAppName(parsed?.appName)
      store.preview.models = parsed?.models || store.preview.models || []
      store.preview.forms = parsed?.forms || store.preview.forms || []
      store.preview.dicts = parsed?.dicts || store.preview.dicts || []
      store.preview.roles = parsed?.roles || store.preview.roles || []
      store.preview.workflows = parsed?.workflows || store.preview.workflows || []
      store.preview.permissions = parsed?.permissions || store.preview.permissions || []
      setPreviewCustomDevelopment(parsed)
      parseReady.value = store.preview.models.length > 0 || store.preview.forms.length > 0
    }
    currentDocPreviewOverride.value = null
    const selectedVersion = latest
      ? displayDocVersions.value.find(item => Number(item.id) === Number(latest.id) || getDocDisplayVersion(item) === getDocDisplayVersion(latest))
      : null
    selectedDocVersionKey.value = selectedVersion?.key || displayDocVersions.value[0]?.key || null
    if (!parsedAppCode.value && latest?.raw_content) {
      const codeFromDoc = extractAppCodeFromText(String(latest.raw_content || ''))
      if (codeFromDoc) parsedAppCode.value = codeFromDoc
    }
    return { versions, currentVersion }
  } catch {
    // ignore
  }
  return null
}

const restorePendingChangePlan = async (appId: number, docVersionResponse?: any) => {
  try {
    const payload = docVersionResponse || await applicationApi.getDocVersions(appId)
    const { versions, currentVersion } = getDocVersionsPayload(payload)
    const planId = findRestorableChangePlanId(versions, currentVersion)
    if (!planId) {
      clearChangePlanState()
      return false
    }

    const changePlanDetail = await applicationApi.getChangePlan(appId, planId)
    const normalized = normalizeChangePlanState(changePlanDetail)
    if (!normalized || normalized.fromVersion <= 0) {
      clearChangePlanState()
      return false
    }

    applyChangePlanState(changePlanDetail)
    deployOpen.value = true
    return true
  } catch (error) {
    console.error('Failed to restore pending change plan', error)
    clearChangePlanState()
    return false
  }
}

const formatDocTime = (dateStr: string) => {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const openDocPreview = (ver: DocVersion) => {
  docVersionPreviewTitle.value = `V${getDocDisplayVersion(ver)} — ${getDocDisplayFilename(ver)}`
  docVersionPreviewContent.value = resolveDocDisplayContent(ver) || '（无内容）'
  docVersionPreviewItem.value = (ver as DocVersionListItem) || null
  docVersionPreviewVisible.value = true
}

const openCurrentDocFullscreen = () => {
  const item = selectedDocVersionItem.value
  docFullscreenTitle.value = item
    ? `V${getDocDisplayVersion(item)} — ${getDocDisplayFilename(item) || `${store.preview.appName || '功能设计文档'}.md`}`
    : `${store.preview.appName || '功能设计文档'}`
  docFullscreenContent.value = resolveDocDisplayContent(item) || '（无内容）'
  docFullscreenItem.value = item || null
  docFullscreenVisible.value = true
}

const openDocDiff = (ver: DocVersion) => {
  const prevVer = displayDocVersions.value.find(item => getDocDisplayVersion(item) === getDocDisplayVersion(ver) - 1)
  if (!prevVer) return
  docVersionDiffLeftTitle.value = `V${getDocDisplayVersion(prevVer)} — ${getDocDisplayFilename(prevVer)}`
  docVersionDiffRightTitle.value = `V${getDocDisplayVersion(ver)} — ${getDocDisplayFilename(ver)}`
  docVersionDiffLeft.value = prevVer.raw_content || ''
  docVersionDiffRight.value = ver.raw_content || ''
  docVersionDiffLeftItem.value = prevVer as DocVersionListItem
  docVersionDiffRightItem.value = ver as DocVersionListItem
  docVersionDiffVisible.value = true
}

const canCompareDocVersion = (ver: DocVersion) =>
  !('isVirtual' in ver && ver.isVirtual) && displayDocVersions.value.some(item => getDocDisplayVersion(item) === getDocDisplayVersion(ver) - 1 && !!item.raw_content)

const isDocVersionExpanded = (ver: DocVersionListItem) => expandedDocVersionKey.value === ver.key

const toggleDocVersion = (ver: DocVersionListItem) => {
  expandedDocVersionKey.value = expandedDocVersionKey.value === ver.key ? null : ver.key
}

const selectDocVersion = (ver: DocVersionListItem) => {
  selectedDocVersionKey.value = ver.key
  expandedDocVersionKey.value = ver.key
  docVersionHistoryOpen.value = false
}

const deleteDocVersion = async (ver: DocVersionListItem) => {
  if (!existingAppId.value || ver.isVirtual) return
  try {
    await ElMessageBox.confirm(
      `确认删除文档版本 V${getDocDisplayVersion(ver)} 吗？删除后版本记录和关联变更计划将一并移除。`,
      '删除版本记录',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }

  deletingDocVersionId.value = ver.id
  try {
    await applicationApi.deleteDocVersion(existingAppId.value, ver.id)
    await loadLatestDocForApp(existingAppId.value)
    await fetchDocVersions()
    ElMessage.success(`已删除版本 V${getDocDisplayVersion(ver)}`)
  } catch (e: any) {
    handleError(e, { fallback: '删除版本失败' })
  } finally {
    deletingDocVersionId.value = null
  }
}

const startApplicationUpdateChat = () => {
  if (!existingAppId.value) return
  openArtifactPanel(getRouteCanvasTab() || 'spec')
  activeView.value = 'builder'
  isApplicationUpdateChatMode.value = true
  if (appParsedMode.value) {
    const nextQuery = { ...route.query }
    delete (nextQuery as any).app_mode
    router.replace({ path: route.path, query: nextQuery })
  }
  const hasUpdateGuide = messages.some(msg =>
    msg.role === 'assistant' && String(msg.content || '').includes('已进入应用更新模式')
  )
  if (!hasUpdateGuide) {
    messages.push({
      id: Date.now(),
      role: 'assistant',
      agent: 'builder',
      content: '已进入应用更新模式。你可以直接描述要改什么，我会基于当前 SPEC 生成新版设计文档，并进入变更计划确认；如果已有新版 Markdown，也可以通过附件上传后走文档对比。',
      created_at: ''
    })
  }
  nextTick(() => {
    inputRef.value?.focus()
    scrollToBottom()
  })
}

const enterGeneratedApplicationWorkspace = (app: any) => {
  if (!isGeneratedApplication(app)) return
  const requestedView = Array.isArray(route.query.view) ? route.query.view[0] : route.query.view
  if (requestedView === 'coding' || requestedView === 'platform') return
  // 2026-05-19 post-deploy 已通过 restoreActiveViewForApp 切到 platform iframe，
  // 不再自动进左侧 update chat 模式（Plan D：post-deploy 调整走右侧 ConfigAssistantPanel）
  if (activeView.value === 'platform') return
  startApplicationUpdateChat()
}

const triggerDocVersionUpload = () => {
  if (!existingAppId.value) return
  startApplicationUpdateChat()
  docVersionInputRef.value?.click()
}

const triggerReparse = () => {
  reparseInputRef.value?.click()
}

const handleReparseInputChange = async (e: Event) => {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  target.value = ''
  reparsing.value = true
  // 重置解析和部署状态，回到初始解析页面
  parseReady.value = false
  deploySteps.value = []
  deployOpen.value = false
  clearChangePlanState()
  try {
    await uploadDocFile(file)
  } finally {
    reparsing.value = false
  }
}

const handleDocVersionInputChange = async (e: Event) => {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  target.value = ''
  if (!file || !existingAppId.value) return
  if (!/\.md$/i.test(file.name)) {
    ElMessage.warning('当前仅支持上传 .md 格式的功能设计文档')
    return
  }
  // 清空旧对话，进入版本更新的独立对话
  messages.splice(0, messages.length)
  // 立即打开更新面板（先展示加载态，SSE 完成后替换真实数据）
  store.changePlan = { id: null, actions: [], resourceDiff: null, diffSummary: '正在分析文档变更...', fromVersion: 0, toVersion: 0, status: 'pending' } as any
  store.showChangePlan = true
  updatingDocVersion.value = true
  try {
    await handleDocVersionUpload(file, existingAppId.value)
  } finally {
    updatingDocVersion.value = false
  }
}

const closeChangePlan = () => {
  if (executingChangePlan.value) return
  clearChangePlanState()
}

const toggleChangePlanSelection = (checked: boolean) => {
  if (!Array.isArray(store.changePlan?.actions)) return
  store.changePlan.actions.forEach((action: any) => {
    action.selected = checked
  })
}

const changePlanActionTone = (action: any) => {
  const op = String(action?.op || '').toLowerCase()
  if (op.startsWith('add')) return 'add'
  if (op.startsWith('remove') || op.startsWith('delete')) return 'remove'
  return 'modify'
}

const changePlanActionSymbol = (action: any) => {
  const tone = changePlanActionTone(action)
  if (tone === 'add') return '+'
  if (tone === 'remove') return '-'
  return '~'
}

const describeChangePlanAction = (action: any) => {
  if (action?.summary) return action.summary
  const op = String(action?.op || '').toLowerCase()
  const verb = op.startsWith('add')
    ? '新增'
    : op.startsWith('remove') || op.startsWith('delete')
      ? '删除'
      : '更新'
  const name =
    action?.label ||
    action?.name ||
    action?.target ||
    action?.model ||
    action?.value?.name ||
    action?.value?.code ||
    action?.code ||
    '未命名项'
  return `${verb} ${name}`
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
  if (!docVersionDiffLeft.value && !docVersionDiffRight.value) return { left: [], right: [] }
  return computeLineDiff(docVersionDiffLeft.value, docVersionDiffRight.value)
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
interface UpdateExecutionItem {
  id: string
  groupKey: string
  label: string
  code: string
  op: string
  status: 'pending' | 'current' | 'completed' | 'error'
  detail?: string
}
interface ExecutionLogItem {
  id: string
  level: 'info' | 'success' | 'error'
  levelLabel: string
  time: string
  message: string
}
const deployOpen = ref(false)
const deployAppId = ref<number | null>(null)
const deploySteps = ref<DeployStep[]>([])
const deployExecuting = ref<string | null>(null)
const deployRunningAll = ref(false)
const deployLastError = ref('')
const executionLogs = ref<ExecutionLogItem[]>([])
const deployLogExpanded = ref(false)
const updateExecutionItems = ref<UpdateExecutionItem[]>([])
const updateExecutionStage = ref('')
const updateExecutionStepText = ref('')

// ── 编码冲突修复 ──
interface ConflictState {
  step: string
  model_name: string
  current_code: string
  message: string
  kind: 'entity' | 'app'
  resumeAll: boolean
  newCode: string
  resolving: boolean
}
const activeConflict = ref<ConflictState | null>(null)

const deployDoneCount = computed(() => deploySteps.value.filter(s => s.status === 'completed').length)
const deployPercent = computed(() => deploySteps.value.length ? Math.round(deployDoneCount.value / deploySteps.value.length * 100) : 0)
const deployAllDone = computed(() => deploySteps.value.length > 0 && deployDoneCount.value === deploySteps.value.length)
const canRetryAllDeploy = computed(() =>
  deployOpen.value
  && !isUpdateReviewMode.value
  && !isUpdateExecutionMode.value
  && deploySteps.value.length > 0
  && !deployAllDone.value
  && deploySteps.value.some(s => s.status === 'error' || s.status !== 'completed')
)
const currentDeployStep = computed(() =>
  deploySteps.value.find(step => step.key === deployExecuting.value) || null
)
const isUpdateExecutionMode = computed(() => executingChangePlan.value && updateExecutionItems.value.length > 0)
const updateExecutionDoneCount = computed(() => updateExecutionItems.value.filter(item => item.status === 'completed').length)
const updateExecutionTotalCount = computed(() => updateExecutionItems.value.length)
const updateExecutionPercent = computed(() => updateExecutionTotalCount.value ? Math.round(updateExecutionDoneCount.value / updateExecutionTotalCount.value * 100) : 0)
const updateExecutionAllDone = computed(() => updateExecutionTotalCount.value > 0 && updateExecutionDoneCount.value === updateExecutionTotalCount.value)
const latestExecutionLog = computed(() => executionLogs.value[0] || null)
const currentUpdateExecutionLabel = computed(() => {
  const current = updateExecutionItems.value.find(item => item.status === 'current')
  return current?.label || updateExecutionStepText.value || ''
})
const parseReady = ref(false)
const isDocParsing = ref(false)         // 文档解析进行中（右侧显示 loading）
const docParsingStep = ref('')          // 当前解析步骤描述

function syncCurrentDocFromPreview(summary = '当前构建后的最新文档', contentOverride = '') {
  const content = String(contentOverride || latestDocContent.value || '').trim()
  if (!content) return
  latestDocContent.value = content
  latestDocAppId.value = existingAppId.value
  latestDocConversationId.value = conversationId.value
  currentDocPreviewOverride.value = {
    id: currentDocVersion.value || -1,
    version: currentDocVersion.value || 1,
    filename: lastParsedFilename.value || `${store.preview.appName || '功能设计文档'}.md`,
    summary,
    raw_content: content,
    parsed_config: {
      ...currentPreviewConfigPayload.value,
      appName: currentPreviewConfigPayload.value.appName || store.preview.appName || '',
    },
    created_at: new Date().toISOString(),
    key: `doc-preview-sync-${Date.now()}`,
    isVirtual: true,
  }
}

function focusConflictInput() {
  nextTick(() => {
    const el = document.querySelector<HTMLInputElement>('.conflict-input')
    if (!el) return
    el.focus()
    el.select()
  })
}

function appendExecutionLog(level: ExecutionLogItem['level'], message: string) {
  const now = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  if (level === 'error' || level === 'success') {
    deployLogExpanded.value = true
  }
  executionLogs.value = [
    {
      id: `${now.getTime()}-${Math.random().toString(36).slice(2, 8)}`,
      level,
      levelLabel: level === 'error' ? '失败' : level === 'success' ? '完成' : '进行中',
      time: `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`,
      message,
    },
    ...executionLogs.value,
  ].slice(0, 20)
}

function settleExecutionLogs(level: ExecutionLogItem['level']) {
  const levelLabel = level === 'error' ? '失败' : level === 'success' ? '完成' : '进行中'
  executionLogs.value = executionLogs.value.map((log) => {
    if (log.level !== 'info') return log
    if (!/^开始执行创建过程$|^开始执行：/u.test(log.message)) return log
    return {
      ...log,
      level,
      levelLabel,
    }
  })
}

function resetExecutionLogs(expanded = false) {
  executionLogs.value = []
  deployLogExpanded.value = expanded
}

function openConflictInConversation(payload: {
  step: string
  modelName: string
  currentCode: string
  message: string
  kind?: 'entity' | 'app'
  resumeAll?: boolean
}) {
  const kind = payload.kind || 'entity'
  const suggestedCode = suggestNextConflictCode(payload.currentCode)
  activeView.value = 'builder'
  deployOpen.value = true
  messages.push({
    id: Date.now(),
    role: 'assistant',
    agent: 'builder',
    content: `⚠️ 检测到${payload.modelName}编码冲突：\`${payload.currentCode}\` 已存在。\n\n我先暂停当前创建过程。你可以确认建议编码 \`${suggestedCode}\`，也可以改成你想要的新编码，确认后我会继续执行。`,
    created_at: new Date().toISOString(),
  })
  scrollToBottom()
  activeConflict.value = {
    step: payload.step,
    model_name: payload.modelName,
    current_code: payload.currentCode,
    message: payload.message,
    kind,
    resumeAll: !!payload.resumeAll,
    newCode: suggestedCode,
    resolving: false,
  }
  focusConflictInput()
}

function resetConversationWorkspace() {
  store.reset()
  specStore.reset()
  store.showConnectModal = false
  store.pendingFile = null
  store.pendingMarkdown = null
  existingAppId.value = null
  parsedAppCode.value = ''
  loadedAppCode.value = ''
  currentRemoteStatus.value = ''
  lastParsedFilename.value = ''
  latestDocContent.value = ''
  latestDocAppId.value = null
  latestDocConversationId.value = null
  latestParseMeta.value = null
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
  platformIframeKey.value = 0
  platformAppUrl.value = ''
  platformDirectUrl.value = ''
  platformIframeAppId.value = null
  platformLoading.value = false
  platformError.value = ''
  platformLoginHint.value = ''

  docVersions.value = []
  docVersionsLoading.value = false
  docVersionPreviewVisible.value = false
  docVersionPreviewContent.value = ''
  docVersionPreviewItem.value = null
  docVersionPreviewTitle.value = ''
  docFullscreenVisible.value = false
  docFullscreenContent.value = ''
  docFullscreenItem.value = null
  docFullscreenTitle.value = ''
  docVersionDiffVisible.value = false
  docVersionDiffLeft.value = ''
  docVersionDiffRight.value = ''
  docVersionDiffLeftTitle.value = ''
  docVersionDiffRightTitle.value = ''
  docVersionDiffLeftItem.value = null
  docVersionDiffRightItem.value = null
  expandedDocVersionKey.value = null
  selectedDocVersionKey.value = null
  deletingDocVersionId.value = null
  currentDocVersionNumber.value = 1
  deployOpen.value = false
  deployAppId.value = null
  deploySteps.value = []
  deployExecuting.value = null
  deployRunningAll.value = false
  deployLastError.value = ''
  resetExecutionLogs()
  updateExecutionItems.value = []
  updateExecutionStage.value = ''
  updateExecutionStepText.value = ''
}

function resetPreviewForNewParse() {
  store.preview.models = []
  store.preview.forms = []
  store.preview.dicts = []
  store.preview.roles = []
  store.preview.workflows = []
  ;(store.preview as any).flows = []
  store.preview.permissions = []
  ;(store.preview as any).custom_development = []
  store.setAppName('', { force: true })
  store.currentApp = null
  latestDocContent.value = ''
  latestDocAppId.value = null
  latestDocConversationId.value = null
  lastParsedFilename.value = ''
  latestParseMeta.value = null
  parseReady.value = false
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

const updateExecutionGroups = computed(() => {
  const defs = [
    { key: 'roles', title: '角色', icon: '👥' },
    { key: 'dicts', title: '数据字典', icon: '📖' },
    { key: 'models', title: '数据模型', icon: '🗃' },
    { key: 'forms', title: '表单', icon: '📋' },
    { key: 'permissions', title: '权限', icon: '🔐' },
    { key: 'other', title: '其他', icon: '🧩' },
  ]
  return defs.map((def) => {
    const items = updateExecutionItems.value.filter(item => item.groupKey === def.key)
    return {
      ...def,
      items,
      doneCount: items.filter(item => item.status === 'completed').length,
      allDone: items.length > 0 && items.every(item => item.status === 'completed'),
      hasCurrent: items.some(item => item.status === 'current'),
      hasError: items.some(item => item.status === 'error'),
    }
  }).filter(group => group.items.length > 0)
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
    if (deploySteps.value.length && deploySteps.value.every(step => step.status === 'completed')) {
      deployLastError.value = ''
      await refreshCurrentAppRemoteMeta(deployAppId.value)
    }
  } catch { /* ignore */ }
}

function persistDeployError(stepLabel: string, detail: string) {
  const message = `${stepLabel} 失败：${detail}`
  deployLastError.value = message
  deployOpen.value = true
  settleExecutionLogs('error')
  appendExecutionLog('error', message)
  messages.push({
    id: Date.now(),
    role: 'assistant',
    agent: 'builder',
    content: `❌ 执行失败\n\n步骤：${stepLabel}\n原因：${detail}`,
    created_at: new Date().toISOString(),
  })
  scrollToBottom()
}

async function deployExec(key: string) {
  if (!deployAppId.value) return
  resetExecutionLogs()
  deployExecuting.value = key
  deployLastError.value = ''
  appendExecutionLog('info', `开始执行：${deploySteps.value.find(step => step.key === key)?.label || key}`)
  try {
    const resp = await applicationApi.executeStep(deployAppId.value, key)
    if (resp.status === 'conflict' && resp.conflict) {
      handleConflict(resp, key)
    } else if (resp.status === 'error') {
      // create_app 失败且涉及编码问题，回到对话区确认最新编码
      if (key === 'create_app' && resp.error && (resp.error.includes('编码') || resp.error.includes('code') || resp.error.includes('Code'))) {
        openConflictInConversation({
          step: key,
          modelName: '应用',
          currentCode: displayAppCode.value,
          message: resp.error,
          kind: 'app',
          resumeAll: false,
        })
        return
      } else {
        persistDeployError(deploySteps.value.find(step => step.key === key)?.label || key, resp.error || '失败')
        ElMessage.error(resp.error || '失败')
      }
    }
  } catch (e: any) {
    const detail = e?.response?.data?.detail || e?.message || '失败'
    if (isApaasTokenError(String(detail))) {
      ElMessage.warning('平台登录已失效，请先重新连接平台环境')
      store.showConnectModal = true
    } else {
      persistDeployError(deploySteps.value.find(step => step.key === key)?.label || key, detail)
      ElMessage.error(detail)
    }
  }
  finally { deployExecuting.value = null; await loadDeployStatus() }
}

async function deployRedo(key: string) {
  if (!deployAppId.value) return
  await applicationApi.resetStep(deployAppId.value, key)
  await loadDeployStatus()
  await deployExec(key)
}

// 一键重跑：把所有 error 步骤 reset 掉，然后从未完成步骤继续往下跑
async function deployRetryAll() {
  if (!deployAppId.value || deployRunningAll.value || deployExecuting.value !== null) return
  const erroredKeys = deploySteps.value.filter(s => s.status === 'error').map(s => s.key)
  for (const key of erroredKeys) {
    try { await applicationApi.resetStep(deployAppId.value, key) } catch { /* ignore */ }
  }
  if (erroredKeys.length) await loadDeployStatus()
  await deployRunAll()
}

async function deployRunAll() {
  if (!deployAppId.value || deployRunningAll.value || deployExecuting.value !== null || deployAllDone.value) return

  resetExecutionLogs()
  deployRunningAll.value = true
  deployLastError.value = ''
  appendExecutionLog('info', '开始执行创建过程')
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
        if (s.key === 'create_app' && resp.error && (resp.error.includes('编码') || resp.error.includes('code') || resp.error.includes('Code'))) {
          openConflictInConversation({
            step: s.key,
            modelName: '应用',
            currentCode: displayAppCode.value,
            message: resp.error,
            kind: 'app',
            resumeAll: true,
          })
          deployExecuting.value = null
          return
        }
        persistDeployError(s.label, resp.error || '失败')
        ElMessage.error(resp.error + '，已暂停')
        deployExecuting.value = null
        return
      }
    }
    deployExecuting.value = null
    settleExecutionLogs('success')
    appendExecutionLog('success', '全部创建步骤已完成')
    ElMessage.success('全部完成！')
  } catch (e: any) {
    const detail = e?.response?.data?.detail || e?.message || '失败'
    if (isApaasTokenError(String(detail))) {
      ElMessage.warning('平台登录已失效，请先重新连接平台环境')
      store.showConnectModal = true
    } else {
      persistDeployError(currentDeployStep.value?.label || '创建过程', detail)
      ElMessage.error(detail)
    }
  } finally {
    deployExecuting.value = null
    deployRunningAll.value = false
    await loadDeployStatus()
  }
}

async function loadDeployStatusAndRunAll() {
  await loadDeployStatus()
  if (!deploySteps.value.length || deployAllDone.value) return
  await deployRunAll()
}

function handleConflict(resp: any, stepKey: string) {
  const c = resp.conflict
  if (stepKey === 'create_app') {
    openConflictInConversation({
      step: stepKey,
      modelName: '应用',
      currentCode: displayAppCode.value || c.current_code || 'app_builder',
      message: c.message,
      kind: 'app',
      resumeAll: deployRunningAll.value,
    })
    return
  }
  openConflictInConversation({
    step: stepKey,
    modelName: c.model_name,
    currentCode: c.current_code,
    message: c.message,
    kind: 'entity',
    resumeAll: deployRunningAll.value,
  })
}

async function resolveConflictAndRetry() {
  const appId = deployAppId.value || existingAppId.value
  if (!activeConflict.value || !appId) return
  const c = activeConflict.value
  if (!c.newCode.trim()) { ElMessage.warning('请输入新编码'); return }
  if (c.newCode === c.current_code) { ElMessage.warning('新编码不能和旧编码相同'); return }
  if (c.kind === 'app' && !/^[a-zA-Z][a-zA-Z0-9\-]*$/.test(c.newCode.trim())) {
    ElMessage.warning('应用编码只能包含英文字母、数字和连字符(-)，且以字母开头')
    return
  }

  c.resolving = true
  try {
    let syncSummary = `构建冲突已修复，最新编码：${c.newCode}`
    if (c.kind === 'app') {
      await request.patch(`/applications/${appId}/code`, { app_code: c.newCode })
      await applicationApi.resetStep(appId, c.step)
      loadedAppCode.value = c.newCode
      parsedAppCode.value = c.newCode
      syncSummary = `应用编码已更新为 ${c.newCode}`
    } else {
      const resolveResp = await applicationApi.resolveConflict(appId, {
        step: c.step,
        model_name: c.model_name,
        old_code: c.current_code,
        new_code: c.newCode,
      })
      const resolvedPreview = resolveResp?.config_preview?.data || resolveResp?.config_preview
      if (resolvedPreview && typeof resolvedPreview === 'object') {
        store.preview = {
          appName: resolvedPreview.appName || resolveResp?.app_name || store.preview.appName || '',
          models: resolvedPreview.models || [],
          forms: resolvedPreview.forms || [],
          roles: resolvedPreview.roles || [],
          dicts: resolvedPreview.dicts || [],
          workflows: resolvedPreview.workflows || [],
          permissions: resolvedPreview.permissions || [],
          custom_development: normalizeCustomDevelopmentItems(resolvedPreview),
        }
        if (resolveResp?.app_code) {
          loadedAppCode.value = resolveResp.app_code
          parsedAppCode.value = resolveResp.app_code
        }
        parseReady.value = store.preview.models.length > 0 || store.preview.forms.length > 0
      }
      if (resolveResp?.doc_version) {
        await loadLatestDocForApp(deployAppId.value)
      }
    }
    // 在对话区显示修复成功
    messages.push({
      id: Date.now(),
      role: 'assistant',
      agent: 'builder',
      content: `\u2705 编码已更新：\`${c.current_code}\` \u2192 \`${c.newCode}\`\n\n我会用这个最新编码继续重试当前构建步骤。`,
      created_at: new Date().toISOString(),
    })
    scrollToBottom()
    const conflictStep = c.step
    activeConflict.value = null
    currentDocPreviewOverride.value = null
    // 自动重试
    await deployExec(conflictStep)
    if (c.resumeAll) {
      await deployRunAll()
    }
  } catch (e: any) {
    const detail = e?.response?.data?.detail || e?.message || '修复失败'
    deployLastError.value = `编码修复失败：${detail}`
    appendExecutionLog('error', `编码修复失败：${detail}`)
    ElMessage.error(detail)
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

const startDeployFlow = async () => {
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
          // 有未完成步骤时只打开创建过程，具体补跑由用户点击执行/重试触发。
          deployAppId.value = existingAppId.value
          deployOpen.value = true
          deploySteps.value = steps
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
      if (envs.some(e => e.status === 'connected')) {
        // 未绑定环境时，始终弹出选择框
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

// ── 首次部署前的模型 code 冲突预检 ─────────────────────────────
// 流程：create/update app → preflightConflicts → 有冲突则弹框 → applyCodeRename → loadDeployStatusAndRunAll
const conflictDialogVisible = ref(false)
const conflictList = ref<Array<{ name: string; original_code: string; suggested_code: string }>>([])
const conflictApplying = ref(false)
let conflictResolver: ((ok: boolean) => void) | null = null

async function runPreflightConflicts(appId: number): Promise<boolean> {
  let preflight
  try {
    preflight = await applicationApi.preflightConflicts(appId)
  } catch (e) {
    // 预检失败不阻塞部署（和后端 skipped 分支语义一致）
    console.warn('[preflight] 扫描失败，跳过冲突检查', e)
    return true
  }
  if (!preflight || !preflight.has_conflicts) return true

  conflictList.value = preflight.conflicts.map(c => ({
    name: c.name,
    original_code: c.original_code,
    suggested_code: c.suggested_code,
  }))
  conflictDialogVisible.value = true
  return await new Promise<boolean>(resolve => {
    conflictResolver = resolve
  })
}

async function confirmConflictRenames() {
  const renames: Record<string, string> = {}
  for (const c of conflictList.value) {
    const orig = (c.original_code || '').trim()
    const nw = (c.suggested_code || '').trim()
    if (!orig || !nw) continue
    if (orig === nw) continue
    renames[orig] = nw
  }
  if (Object.keys(renames).length === 0) {
    ElMessage.warning('每个冲突都必须给出新编码，且不能和原编码相同')
    return
  }
  conflictApplying.value = true
  try {
    const appId = existingAppId.value
    if (!appId) throw new Error('缺少应用 ID')
    const res = await applicationApi.applyCodeRename(appId, renames)
    ElMessage.success(`已更新 ${res.changed_count} 处引用`)

    // 同步刷新本地 preview，让右侧面板展示新的 code
    try {
      const app = await applicationApi.get(appId)
      const cpRaw = (app as any).config_preview
      if (cpRaw) {
        const cp = typeof cpRaw === 'string' ? JSON.parse(cpRaw) : cpRaw
        const data = cp?.data || cp
        if (data?.models) store.preview.models = data.models
      }
    } catch { /* ignore, 后续 loadDeployStatus 还会再拉 */ }

    conflictDialogVisible.value = false
    if (conflictResolver) { conflictResolver(true); conflictResolver = null }
  } catch (e: any) {
    ElMessage.error('应用新编码失败：' + (e?.message || ''))
  } finally {
    conflictApplying.value = false
  }
}

function cancelConflictResolve() {
  conflictDialogVisible.value = false
  if (conflictResolver) { conflictResolver(false); conflictResolver = null }
}

const startGenerateWithEnv = async (envId: number) => {
  generating.value = true
  try {
    const appCode = parsedAppCode.value || buildAppCode(store.preview.appName)

    const payload = {
      conversation_id: conversationId.value || 0,
      project_id: activeProjectId.value,
      app_name: store.preview.appName,
      app_code: appCode,
      description: store.preview.appName,
      platform_env_id: envId,
      config_preview: {
        type: 'preview',
        data: currentPreviewConfigPayload.value
      }
    }

    let newAppId: number
    let alreadyDeployed = false
    if (existingAppId.value) {
      const app = await applicationApi.update(existingAppId.value, payload)
      newAppId = (app as any).id
      loadedAppCode.value = (app as any).app_code || appCode
      alreadyDeployed = !!(app as any).apaas_app_id
    } else {
      const app = await applicationApi.create(payload)
      newAppId = (app as any).id
      existingAppId.value = newAppId
      loadedAppCode.value = (app as any).app_code || appCode
      alreadyDeployed = !!(app as any).apaas_app_id
    }
    parsedAppCode.value = loadedAppCode.value || appCode

    // 首次部署前做模型 code 冲突预检；已部署的（后续重新部署）跳过
    if (!alreadyDeployed) {
      const ok = await runPreflightConflicts(newAppId)
      if (!ok) {
        ElMessage.info('构建已取消，请在文档中调整模型编码后重试')
        return
      }
    }

    // 不跳转，在本页打开部署面板
    deployAppId.value = newAppId
    deployOpen.value = true
    await loadDeployStatusAndRunAll()
  } catch (e: any) {
    ElMessage.error('创建应用失败: ' + (e.message || ''))
  } finally {
    generating.value = false
  }
}

const uploadDocFile = async (file: File) => {
  // A 严格模式：Builder 只接受 .md/.markdown 标准设计文档。
  // 其它格式直接拦下，引导用户回 AI-Chat 把文档整理成标准格式。
  const lowerName = file.name.toLowerCase()
  if (!/\.(md|markdown)$/.test(lowerName)) {
    ElMessage.error({
      message: 'Builder 只接受 .md / .markdown 标准设计文档。请回 AI-Chat 把文档整理成标准格式。',
      duration: 5000,
    })
    return
  }
  const fileText = await file.text()
  resetPreviewForNewParse()
  const codeFromDoc = extractAppCodeFromText(fileText)
  if (codeFromDoc) {
    parsedAppCode.value = codeFromDoc
  }

  const userMsgId = Date.now()
  messages.push({ id: userMsgId, role: 'user', content: `📄 上传设计文档: ${file.name}`, created_at: '' })

  isDocParsing.value = true
  docParsingStep.value = '正在读取文档...'

  const progressMsgId = userMsgId + 1
  const parseTracker = reactive({
    currentStep: '正在读取文档...',
    docs: 'done',
    roles: 'pending',
    dicts: 'pending',
    models: 'pending',
    forms: 'pending',
    permissions: 'pending',
  } as Record<string, string>)

  const syncParseTrackerFromPreview = (markDone = false) => {
    if (store.preview.roles.length > 0 || markDone) parseTracker.roles = 'done'
    if (store.preview.dicts.length > 0 || markDone) parseTracker.dicts = 'done'
    if (store.preview.models.length > 0 || markDone) parseTracker.models = 'done'
    if (formPreviewItems.value.length > 0 || markDone) parseTracker.forms = 'done'
    if (permissionPreviewItems.value.length > 0 || markDone) parseTracker.permissions = 'done'
  }

  const buildProgressContent = (done = false) => {
    const lines = [`**📄 解析文档：${file.name}**`, '']
    const summaryItems = [
      { key: 'roles', label: '角色', count: store.preview.roles.length },
      { key: 'dicts', label: '数据字典', count: store.preview.dicts.length },
      { key: 'models', label: '数据模型', count: store.preview.models.length },
      { key: 'forms', label: '表单', count: formPreviewItems.value.length },
      { key: 'permissions', label: '权限', count: permissionPreviewItems.value.length },
      { key: 'docs', label: '文档', count: (latestDocContent.value.trim() || fileText.trim()) ? 1 : 0 },
    ]
    syncParseTrackerFromPreview(done)
    const doneCount = summaryItems.filter(item => item.key === 'docs' ? true : (done || parseTracker[item.key] === 'done')).length
    const percent = Math.round(doneCount / summaryItems.length * 100)
    const effectiveDone = done || percent >= 100
    const currentStepText = effectiveDone
      ? '解析完成'
      : String(parseTracker.currentStep || '')
          .replace(/^配置组装完成[！!：:].*$/u, '配置组装完成')
          .replace(/^配置组装完成$/u, '配置组装完成')

    lines.push(`**解析进度** ${percent}%`)
    lines.push(`当前步骤：${currentStepText || '正在解析中...'}`)
    const parseMetaSummary = formatParseMetaSummary(latestParseMeta.value)
    if (parseMetaSummary) {
      lines.push(parseMetaSummary)
      lines.push('')
    }
    for (const item of summaryItems) {
      const status = effectiveDone ? 'done' : parseTracker[item.key]
      const icon = status === 'done' ? '✅' : status === 'running' ? '🔄' : '○'
      const suffix = status === 'running' && item.count === 0 ? '解析中...' : `${item.count} 项`
      lines.push(`${icon} **${item.label}** ${suffix}`)
    }

    if (effectiveDone) {
      lines.push('')
      lines.push('请检查右侧预览内容，点击右上方「开始构建」即可开始在低代码上搭建。')
    }

    return lines.join('\n')
  }

  messages.push({ id: progressMsgId, role: 'assistant', agent: 'builder', content: buildProgressContent(), created_at: '' })
  scrollToBottom()

  try {
    const token = localStorage.getItem('token')
    const formData = new FormData()
    formData.append('file', file)
    if (conversationId.value) {
      formData.append('conversation_id', String(conversationId.value))
    }

    // 先本地读文档头部推断应用名，立即填进 store（标准 md 首行就是 # 应用名）。
    // 后端 SSE done 返回真值时 setAppName 会用后端结果覆盖（setter 会过滤默认值）。
    try {
      const head = await file.slice(0, 8192).text()
      const local = extractAppNameFromText(head)
      if (local) store.setAppName(local)
    } catch { /* 读失败就走原路径，不阻塞上传 */ }

    const response = await fetch(`${API_PREFIX}/applications/upload-doc-with-conversation`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}` },
      body: formData
    })

    if (!response.ok) {
      const errBody = await response.json().catch(() => ({ detail: '请求失败' }))
      const detail = errBody.detail
      if (detail && typeof detail === 'object' && detail.code === 'DOC_NOT_STANDARD') {
        const lines = [
          `❌ **文档标准度 ${detail.score}/100，未达到 90 分门槛**`,
        ]
        if (Array.isArray(detail.missing_sections) && detail.missing_sections.length) {
          lines.push(`- 缺少章节：${detail.missing_sections.join('、')}`)
        }
        if (Array.isArray(detail.weak_sections) && detail.weak_sections.length) {
          lines.push(`- 待加强章节：${detail.weak_sections.join('、')}`)
        }
        if (detail.signals && typeof detail.signals === 'object') {
          const sigLabel: Record<string, string> = {
            section_coverage: '章节覆盖',
            header_format: '标题格式',
            table_header_match: '表头匹配',
            code_compliance: '编码合规',
            ref_integrity: '引用完整',
          }
          const sigs = Object.entries(detail.signals)
            .map(([k, v]) => `${sigLabel[k] || k} ${Math.round(Number(v) * 100)}%`)
            .join(' · ')
          if (sigs) lines.push(`- 各项评分：${sigs}`)
        }
        lines.push('')
        lines.push('点下方按钮直接返回 AI-Chat 让助手按标准 6 章规范重写文档。')
        const e: any = new Error(lines.join('\n'))
        e._docNotStandardDetail = detail
        throw e
      }
      throw new Error(typeof detail === 'string' ? detail : '文档上传失败')
    }

    const reader = response.body?.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let finalResult: any = null

    let currentEvent = ''
    const handleSseLines = (lines: string[]) => {
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
              if (data.parse_meta) latestParseMeta.value = data.parse_meta || null
              const phaseMatch = msg.match(/^\[(\w+)\]\s*(.*)/)
              parseTracker.currentStep = phaseMatch?.[2] || msg || '正在解析中...'
              docParsingStep.value = String(parseTracker.currentStep || '')

              // skeleton 阶段不改各模块状态，只在收到具体模块进度时才更新
              const phase = phaseMatch?.[1] || ''
              if (phase === 'roles') {
                parseTracker.roles = 'running'
              } else if (phase === 'dicts') {
                parseTracker.dicts = 'running'
              } else if (phase === 'models') {
                parseTracker.models = 'running'
              } else if (phase === 'forms') {
                parseTracker.forms = 'running'
              } else if (phase === 'permissions') {
                parseTracker.permissions = 'running'
              } else if (phase === 'complete') {
                // 全部完成：未 done 的标记为 running（即将由 syncParseTrackerFromPreview 更新为 done）
                for (const k of ['roles', 'dicts', 'models', 'forms', 'permissions']) {
                  if (parseTracker[k] !== 'done') parseTracker[k] = 'running'
                }
              } else if (phase === 'skeleton') {
                // skeleton 只表示整体进度，不改各模块状态
              }

              if (data.batch && Array.isArray(data.batch)) {
                const phaseKey = phaseMatch?.[1] || ''
                if (phaseKey === 'roles') {
                  for (const r of data.batch) {
                    if (!store.preview.roles.find((x: any) => x.code === r.code)) {
                      store.preview.roles.push(r)
                    }
                  }
                } else if (phaseKey === 'dicts') {
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
                } else if (phaseKey === 'forms') {
                  if (!store.preview.forms) store.preview.forms = []
                  for (const f of data.batch) {
                    const key = f.formCode || f.code || f.modelCode
                    const existing = store.preview.forms.find((x: any) => (x.formCode || x.code || x.modelCode) === key)
                    if (existing) Object.assign(existing, f)
                    else store.preview.forms.push(f)
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

              if (data.data) {
                const skeletonName = pickAppName(data.data)
                const skeletonCode = pickAppCode(data.data)
                if (skeletonName && !store.preview.appName) {
                  store.setAppName(skeletonName)
                  store.currentApp = { status: 'draft' }
                }
                if (skeletonCode) {
                  parsedAppCode.value = skeletonCode
                } else if (!parsedAppCode.value && store.preview.appName) {
                  parsedAppCode.value = buildAppCode(store.preview.appName)
                }
                if (!store.preview.roles.length && Array.isArray(data.data.roles)) {
                  store.preview.roles = data.data.roles
                }
                syncParseTrackerFromPreview()
                if (!store.preview.models.length && Array.isArray(data.data.models) && data.data.models.length) {
                  store.preview.models = data.data.models
                }
                if (!store.preview.dicts.length && Array.isArray(data.data.dicts) && data.data.dicts.length) {
                  store.preview.dicts = data.data.dicts
                }
                if (!store.preview.permissions?.length && Array.isArray(data.data.permissions) && data.data.permissions.length) {
                  store.preview.permissions = data.data.permissions
                }
                syncParseTrackerFromPreview()
              }

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
            // JSON 解析失败多见于大 done 事件跨 chunk 被切断；完整的 data 行
            // 会在下一次 read 拼接后重新进入这段 handleSseLines。保留警告便于排查。
            console.warn('[SSE] JSON parse failed (possibly mid-chunk)', {
              event: currentEvent,
              lineLen: (line || '').length,
              preview: String(line || '').slice(0, 200),
              error: parseErr.message,
            })
          }
        }
      }
    }

    while (reader) {
      const { done, value } = await reader.read()
      if (value) buffer += decoder.decode(value, { stream: !done })

      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      handleSseLines(lines)

      if (done) break
    }

    if (buffer.trim()) handleSseLines([buffer])

    // 完成：更新进度消息为最终总结
    const pmsg = messages.find(m => m.id === progressMsgId)

    if (finalResult) {
      latestParseMeta.value = finalResult.parse_meta || null
      conversationId.value = finalResult.conversation_id
      selectedConversationId.value = finalResult.conversation_id
      if (conversationId.value && !existingAppId.value) {
        try {
          await conversationApi.updateAgentType(conversationId.value, 'requirements')
        } catch (e) {
          console.warn('Failed to keep uploaded-doc conversation in requirements mode', e)
        }
        currentAgent.value = 'requirements'
      }
      router.replace(`/chat/${finalResult.conversation_id}`)
      let loadedUploadedSpec = await loadUploadedDocumentSpec(finalResult.spec_id || null)
      lastParsedFilename.value = file.name
      latestDocContent.value = finalResult.rendered_doc || fileText || ''
      latestDocAppId.value = null
      latestDocConversationId.value = finalResult.conversation_id || null

      // 最终更新 store
      const previewData = finalResult.preview?.data || finalResult.preview
      const appName = pickAppName(previewData)
      const appCode = pickAppCode(previewData)
      if (previewData?.appName || previewData?.models || appName || appCode) {
        store.currentApp = { status: 'draft' }
        store.setAppName(appName)
        parsedAppCode.value = appCode || buildAppCode(store.preview.appName)
        store.preview.roles = previewData.roles || []
        store.preview.dicts = previewData.dicts || []
        store.preview.models = previewData.models || []
        store.preview.forms = previewData.forms || []
        store.preview.workflows = previewData.workflows || []
        store.preview.permissions = previewData.permissions || []
        setPreviewCustomDevelopment(previewData)
        syncCurrentDocFromPreview('当前解析出的最新文档', finalResult.rendered_doc || '')
      }

      // 文档上传完成后自动创建 Application（如果还没有）
      if (!existingAppId.value && store.preview.appName) {
        try {
          const result = await applicationApi.autoCreate({
            app_name: store.preview.appName,
            config_preview: currentPreviewConfigPayload.value,
            conversation_id: conversationId.value || undefined,
            project_id: activeProjectId.value,
          })
          existingAppId.value = result.app_id
          loadedAppCode.value = result.app_code || ''
          parsedAppCode.value = result.app_code || ''
          parsedAppCode.value = result.app_code || loadedAppCode.value || ''
          router.replace({ query: { ...route.query, app_id: String(result.app_id) } })
          // 来自 AIChat 的 → Builder 入口：把 (session+filename) → app_id 写本地缓存，
          // 同一来源再点 → Builder 直接跳已有应用，不重复建
          recordMdToBuilderCache(result.app_id)
          console.log(`Doc upload auto-created app: id=${result.app_id}, is_new=${result.is_new}`)
        } catch (e) {
          console.warn('文档上传后自动创建应用失败:', e)
        }
      }

      // 文档上传完成后自动刷新文档版本列表
      await fetchDocVersions()
      // 上传解析会同时创建/回填 Spec。自动创建应用和版本列表刷新后再强制
      // 拉一次，可以避免右侧预览仍停留在空态，需要用户再发消息才刷新。
      loadedUploadedSpec = (await loadUploadedDocumentSpec(finalResult.spec_id || null)) || loadedUploadedSpec
      if (!loadedUploadedSpec) {
        await loadUploadedDocumentSpec(null)
      }

      // 替换进度消息为完成总结
      if (pmsg) {
        parseTracker.currentStep = '解析完成'
        isDocParsing.value = false
        parseReady.value = true
        pmsg.content = buildProgressContent(true)
      }
    } else if (store.preview.models.length > 0 || store.preview.dicts.length > 0 || store.preview.roles.length > 0) {
      // done 事件未收到（大 payload SSE 丢失），但 progress 已逐步推送了数据到 store
      console.warn('done 事件丢失，使用 store 中已累积的数据兜底')
      if (!store.currentApp) {
        store.currentApp = { status: 'draft' }
      }
      parseReady.value = true
      lastParsedFilename.value = file.name
      latestDocContent.value = latestDocContent.value || fileText || ''
      latestDocAppId.value = null
      latestDocConversationId.value = conversationId.value
      // 自动创建 Application
      if (!existingAppId.value && store.preview.appName) {
        try {
          const result = await applicationApi.autoCreate({
            app_name: store.preview.appName,
            config_preview: currentPreviewConfigPayload.value,
            project_id: activeProjectId.value,
          })
          existingAppId.value = result.app_id
          loadedAppCode.value = result.app_code || ''
          parsedAppCode.value = result.app_code || ''
          router.replace({ query: { ...route.query, app_id: String(result.app_id) } })
          recordMdToBuilderCache(result.app_id)
        } catch (e) {
          console.warn('兜底模式创建应用失败:', e)
        }
      }

      await fetchDocVersions()
      await loadUploadedDocumentSpec(null)

      if (pmsg) {
        parseTracker.currentStep = '解析完成'
        isDocParsing.value = false
        pmsg.content = buildProgressContent(true)
      }
    } else if (pmsg) {
      isDocParsing.value = false
      parseReady.value = false
      docParsingStep.value = ''
      pmsg.content += '\n\n❌ 解析中断：未收到后端完成结果，请重试。'
    }
  } catch (err: any) {
    // 假阳性判定：store.preview 已有完整数据（progress 事件累积）或
    // 消息里已显示成功标记，就认为是 SSE 尾部假阳性，抢救状态并忽略错误。
    const pmsg = messages.find(m => m.id === progressMsgId)
    const hasAccumulatedPreview =
      store.preview.models.length > 0 ||
      store.preview.dicts.length > 0 ||
      store.preview.roles.length > 0 ||
      formPreviewItems.value.length > 0 ||
      permissionPreviewItems.value.length > 0
    const contentShowsSuccess = pmsg && typeof pmsg.content === 'string'
      && (pmsg.content.includes('请检查右侧预览内容') || pmsg.content.includes('解析进度 100'))
    if (parseReady.value || contentShowsSuccess || hasAccumulatedPreview) {
      console.warn('[SSE] 解析已完成，忽略尾部假阳性错误:', err?.message)
      // 抢救状态：原本成功分支会做的关键赋值补一下，否则右侧 UI 过不去
      parseReady.value = true
      if (!store.currentApp && store.preview.appName) {
        store.currentApp = { status: 'draft' }
      }
      await loadUploadedDocumentSpec(null)
      if (pmsg && !contentShowsSuccess) {
        pmsg.content = buildProgressContent(true)
      }
    } else if (pmsg) {
      pmsg.content += `\n\n${err?.message || '❌ 解析失败：未知错误'}`
      if (err?._docNotStandardDetail) {
        ;(pmsg as any).actions = [
          { kind: 'back-to-aichat', type: 'primary', label: '↩ 返回 AI-Chat 修订文档' },
        ]
      }
    } else {
      const newMsg: any = { id: Date.now(), role: 'assistant', agent: 'builder', content: `文档解析失败: ${err?.message || '未知错误'}`, created_at: '' }
      if (err?._docNotStandardDetail) {
        newMsg.actions = [{ kind: 'back-to-aichat', type: 'primary', label: '↩ 返回 AI-Chat 修订文档' }]
      }
      messages.push(newMsg)
    }
    isDocParsing.value = false
  }
  scrollToBottom()
}

const handleDocUpload = async (e: Event) => {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  target.value = '' // reset for re-upload

  // 图片文件 → 作为附件附加到输入框
  if (file.type.startsWith('image/')) {
    attachPendingAttachmentFile(file, 'image')
    return
  }

  // 已有应用 → 走增量更新流程
  if (existingAppId.value) {
    try {
      await ElMessageBox.confirm(
        `当前已关联应用，上传新文档将与现有配置对比并生成变更计划。`,
        '更新设计文档',
        { confirmButtonText: '增量更新', cancelButtonText: '取消', type: 'info' }
      )
      await handleDocVersionUpload(file, existingAppId.value)
    } catch {
      // 用户取消
    }
    return
  }

  await uploadDocFile(file)
}

type DocVersionUploadOptions = {
  userMessageContent?: string | null
  title?: string
  forceNewConversation?: boolean
}

// ── 上传文档新版本并分析变更 ──
const handleDocVersionUpload = async (file: File, appId: number, options: DocVersionUploadOptions = {}) => {
  lastParsedFilename.value = file.name
  latestDocContent.value = ''
  latestParseMeta.value = null
  currentDocPreviewOverride.value = null

  const userMsgId = Date.now()
  if (options.userMessageContent !== null) {
    messages.push({
      id: userMsgId,
      role: 'user',
      content: options.userMessageContent || `📄 上传文档新版本: ${file.name}`,
      created_at: ''
    })
  }

  const progressMsgId = userMsgId + 1
  const updateProgressTitle = options.title || `上传文档新版本：${file.name}`
  const updateParseTracker = reactive({
    currentStep: '准备开始...',
    compare: 'pending',
    parse: 'pending',
    merge: 'pending',
    diff: 'pending',
    save: 'pending',
  } as Record<string, string>)

  const buildUpdateProgressContent = (done = false, extraMessage = '') => {
    const phases = [
      { key: 'compare', label: '文档对比' },
      { key: 'parse', label: '章节解析' },
      { key: 'merge', label: '结果合并' },
      { key: 'diff', label: '资源对比' },
      { key: 'save', label: '保存结果' },
    ]
    const completed = done
      ? phases.length
      : phases.filter(item => updateParseTracker[item.key] === 'done').length
    const percent = Math.round(completed / phases.length * 100)
    const lines = [
      `**📄 ${updateProgressTitle}**`,
      '',
      `**解析进度** ${percent}%`,
      `当前步骤：${done ? '处理完成' : updateParseTracker.currentStep}`,
      '',
    ]
    const parseMetaSummary = formatParseMetaSummary(latestParseMeta.value)
    if (parseMetaSummary) {
      lines.push(parseMetaSummary)
      lines.push('')
    }

    for (const phase of phases) {
      const status = done ? 'done' : updateParseTracker[phase.key]
      const icon = status === 'done' ? '✅' : status === 'running' ? '🔄' : '○'
      const suffix = status === 'running' ? '进行中...' : status === 'done' ? '已完成' : '等待中'
      lines.push(`${icon} **${phase.label}** ${suffix}`)
    }

    if (extraMessage) {
      lines.push('')
      lines.push(extraMessage)
    }

    return lines.join('\n')
  }

  messages.push({
    id: progressMsgId,
    role: 'assistant',
    agent: 'builder',
    content: buildUpdateProgressContent(),
    created_at: ''
  })
  scrollToBottom()

  try {
    // 已部署应用直接上传新文档时强制新建会话；对话式更新已提前创建会话，需要沿用它。
    const shouldForceNewConversation = options.forceNewConversation !== false && isPlatformDeployed.value
    if (!conversationId.value || shouldForceNewConversation) {
      conversationId.value = null
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
      const errBody = await response.json().catch(() => ({ detail: '请求失败' }))
      const detail = errBody.detail
      if (detail && typeof detail === 'object' && detail.code === 'DOC_NOT_STANDARD') {
        const lines = [
          `❌ **文档标准度 ${detail.score}/100，未达到 90 分门槛**`,
        ]
        if (Array.isArray(detail.missing_sections) && detail.missing_sections.length) {
          lines.push(`- 缺少章节：${detail.missing_sections.join('、')}`)
        }
        if (Array.isArray(detail.weak_sections) && detail.weak_sections.length) {
          lines.push(`- 待加强章节：${detail.weak_sections.join('、')}`)
        }
        if (detail.signals && typeof detail.signals === 'object') {
          const sigLabel: Record<string, string> = {
            section_coverage: '章节覆盖',
            header_format: '标题格式',
            table_header_match: '表头匹配',
            code_compliance: '编码合规',
            ref_integrity: '引用完整',
          }
          const sigs = Object.entries(detail.signals)
            .map(([k, v]) => `${sigLabel[k] || k} ${Math.round(Number(v) * 100)}%`)
            .join(' · ')
          if (sigs) lines.push(`- 各项评分：${sigs}`)
        }
        lines.push('')
        lines.push('点下方按钮直接返回 AI-Chat 让助手按标准 6 章规范重写文档。')
        const e: any = new Error(lines.join('\n'))
        e._docNotStandardDetail = detail
        throw e
      }
      throw new Error(typeof detail === 'string' ? detail : '文档上传失败')
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
                updateParseTracker.currentStep = msg || step || '处理中...'
                if (step === 'text_diff') {
                  updateParseTracker.compare = 'done'
                  updateParseTracker.parse = 'running'
                } else if (step === 'parse_changes' || step === 'AI 解析文档配置...') {
                  updateParseTracker.parse = 'running'
                } else if (step === 'merge') {
                  updateParseTracker.parse = 'done'
                  updateParseTracker.merge = 'running'
                } else if (step === '对比资源差异...') {
                  updateParseTracker.merge = 'done'
                  updateParseTracker.diff = 'running'
                } else if (step === '保存版本记录...') {
                  updateParseTracker.diff = 'done'
                  updateParseTracker.save = 'running'
                } else if (msg.includes('正在对比文档章节')) {
                  updateParseTracker.compare = 'running'
                }

	                if (data.data && typeof data.data === 'object' && step === 'text_diff') {
	                  const stats = data.data
	                  pmsg.content = buildUpdateProgressContent(false, `章节统计：新增 ${stats.added || 0}、修改 ${stats.modified || 0}、删除 ${stats.removed || 0}、未变更 ${stats.unchanged || 0}`)
	                } else {
                    const phase = String((msg.match(/^\[(\w+)\]/)?.[1]) || '')
                    if (data.batch && Array.isArray(data.batch)) {
                      if (phase === 'roles') store.preview.roles = data.batch
                      else if (phase === 'dicts') store.preview.dicts = data.batch
                      else if (phase === 'models') store.preview.models = data.batch
                      else if (phase === 'forms') store.preview.forms = data.batch
                      else if (phase === 'permissions') store.preview.permissions = data.batch
                    }
	                  pmsg.content = buildUpdateProgressContent()
	                }
              }
              scrollToBottom()
            } else if (currentEvent === 'done') {
              updateParseTracker.compare = 'done'
              updateParseTracker.parse = 'done'
              updateParseTracker.merge = 'done'
              updateParseTracker.diff = 'done'
              updateParseTracker.save = 'done'
              updateParseTracker.currentStep = '处理完成'
              changePlanData = data.change_plan || data
              latestParseMeta.value = data.parse_meta || null
              if (data.parsed_config) {
                const pc = data.parsed_config.data || data.parsed_config
                store.setAppName(pc.appName)
                store.preview.models = pc.models || []
                store.preview.forms = pc.forms || []
                store.preview.dicts = pc.dicts || []
                store.preview.roles = pc.roles || []
                store.preview.workflows = pc.workflows || []
                store.preview.permissions = pc.permissions || []
                setPreviewCustomDevelopment(pc)
                store.currentApp = {
                  ...(store.currentApp || {}),
                  status: 'draft',
                  apaas_app_id: store.currentApp?.apaas_app_id,
                }
                syncCurrentDocFromPreview('当前解析出的最新文档', data.rendered_doc || '')
              }
            } else if (currentEvent === 'error') {
              if (data.code === 'doc_not_standard') {
                const modules = Array.isArray(data.failed_modules) ? data.failed_modules : []
                const moduleLabels: Record<string, string> = {
                  app_info: '一、应用信息',
                  roles: '二、角色列表',
                  dicts: '三、数据字典',
                  models: '四、数据模型',
                  forms: '五、表单配置',
                  permissions: '六、权限配置',
                  config_validator: '配置结构校验',
                }
                const modulesText = modules.length
                  ? modules.map(m => moduleLabels[m] || m).join('、')
                  : '未知模块'
                const errorLines = Array.isArray(data.errors) ? data.errors.slice(0, 6) : []
                const err = new Error(
                  `文档未按模板规范，更新已中止。\n` +
                  `无法解析的模块：${modulesText}\n` +
                  (errorLines.length ? `\n问题：\n- ${errorLines.join('\n- ')}\n` : '') +
                  `\n请按标准模板调整文档后重新上传（更新模式不允许 AI 兜底修复）。`
                )
                ;(err as any).code = 'doc_not_standard'
                throw err
              }
              throw new Error(data.message || '文档分析失败')
            }
          } catch (parseErr: any) {
            if (parseErr.message && !parseErr.message.includes('JSON')) throw parseErr
          }
        }
      }
    }

    // 处理变更计划 —— 启用对比视图，右侧展示变更详情
    if (changePlanData) {
      const normalizedChangePlan = normalizeChangePlanState(changePlanData)
      const hasHistory = normalizedChangePlan && normalizedChangePlan.fromVersion > 0

      // 将最新解析结果更新到 store
      const pc = changePlanData.parsed_config?.data || changePlanData.parsed_config
      if (pc) {
        store.setAppName(pc.appName)
        store.preview.roles = pc.roles || []
        store.preview.dicts = pc.dicts || []
        store.preview.models = pc.models || []
        store.preview.forms = pc.forms || []
        store.preview.workflows = pc.workflows || []
        store.preview.permissions = pc.permissions || []
        setPreviewCustomDevelopment(pc)
        syncCurrentDocFromPreview('当前解析出的最新文档', changePlanData.rendered_doc || '')
      }

      // 启用 update review 模式，右侧面板展示变更对比
      applyChangePlanState(changePlanData)
      const pmsg = messages.find(m => m.id === progressMsgId)
      if (pmsg) {
        const addCount = changePlanData.actions?.filter((a: any) => a.op?.startsWith('add')).length || 0
        const modCount = changePlanData.actions?.filter((a: any) => a.op?.startsWith('modify') || a.op?.startsWith('update')).length || 0
        const delCount = changePlanData.actions?.filter((a: any) => a.op?.startsWith('remove') || a.op?.startsWith('delete')).length || 0
        pmsg.content = hasHistory
          ? buildUpdateProgressContent(true, `文档更新解析完成：与上一版对比，新增 ${addCount} 项，修改 ${modCount} 项，删除 ${delCount} 项。右侧已展示变更对比详情，确认后可点击「执行更新」。`)
          : buildUpdateProgressContent(true, `文档解析完成，识别到 ${store.preview.models.length} 个模型、${store.preview.dicts.length} 个字典、${store.preview.roles.length} 个角色。右侧已展示配置详情。`)
      }

    } else {
      const pmsg = messages.find(m => m.id === progressMsgId)
      if (pmsg) {
        pmsg.content = buildUpdateProgressContent(true, '文档分析完成，未发现配置变更。')
      }
    }
  } catch (err: any) {
    const pmsg = messages.find(m => m.id === progressMsgId)
    if (pmsg) {
      pmsg.content = `❌ ${buildUpdateProgressContent(false, `文档变更分析失败：${err?.message || '未知错误'}`)}`
      if (err?._docNotStandardDetail) {
        ;(pmsg as any).actions = [
          { kind: 'back-to-aichat', type: 'primary', label: '↩ 返回 AI-Chat 修订文档' },
        ]
      }
    } else {
      const newMsg: any = {
        id: Date.now(),
        role: 'assistant',
        agent: 'builder',
        content: `文档变更分析失败: ${err?.message || '未知错误'}`,
        created_at: ''
      }
      if (err?._docNotStandardDetail) {
        newMsg.actions = [{ kind: 'back-to-aichat', type: 'primary', label: '↩ 返回 AI-Chat 修订文档' }]
      }
      messages.push(newMsg)
    }
  }
  scrollToBottom()
}

const executeChangePlan = async () => {
  if (!store.changePlan || !existingAppId.value) return
  const appId = existingAppId.value
  const planId = store.changePlan.id
  const selectedActions = Array.isArray(store.changePlan.actions)
    ? store.changePlan.actions.filter((action: any) => action.selected !== false)
    : []

  executingChangePlan.value = true
  deployOpen.value = true
  deployLastError.value = ''
  resetExecutionLogs()
  appendExecutionLog('info', '开始执行文档增量更新')
  updateExecutionItems.value = buildUpdateExecutionItems(selectedActions)
  updateExecutionStage.value = 'prepare'
  updateExecutionStepText.value = '准备执行本次更新...'

  // 构建 selections
  const selections: Record<string, boolean> = {}
  store.changePlan.actions.forEach(a => {
    selections[a.id] = a.selected
  })

  clearChangePlanExecutionMessages()
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
              completeCurrentUpdateExecutionItems()
              markUpdateExecutionStage(data.stage || '', data.step || data.message || '')
              appendExecutionLog('info', data.message || data.step || '正在执行更新步骤')
              const emsg = messages.find(m => m.id === execMsgId)
              if (emsg) {
                const msg = data.message || ''
                const step = data.step || ''
                const icon = data.status === 'done' ? '✅' : '⏳'
                emsg.content = `${icon} ${msg || step}`
              }
              scrollToBottom()
            } else if (currentEvent === 'done') {
              if (data?.platform_synced === false || (Array.isArray(data?.sync_errors) && data.sync_errors.length > 0)) {
                const detail = Array.isArray(data?.sync_errors) && data.sync_errors.length
                  ? data.sync_errors.join('；')
                  : '平台同步未完成'
                throw new Error(detail)
              }
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
        store.setAppName(previewData.appName)
        store.preview.roles = previewData.roles || store.preview.roles
        store.preview.dicts = previewData.dicts || store.preview.dicts
        store.preview.models = previewData.models || store.preview.models
        store.preview.forms = previewData.forms || store.preview.forms
        store.preview.workflows = previewData.workflows || store.preview.workflows
        store.preview.permissions = previewData.permissions || store.preview.permissions
      }
    }

    const emsg = messages.find(m => m.id === execMsgId)
    if (emsg) {
      emsg.content = `✅ 变更计划执行完成！已选 ${changePlanSelectedCount.value} 项变更已应用。`
    }
    appendExecutionLog('success', `变更计划执行完成，已应用 ${changePlanSelectedCount.value} 项变更`)
    updateExecutionItems.value = updateExecutionItems.value.map((item) => ({ ...item, status: 'completed', detail: item.detail || '已完成' }))
    updateExecutionStepText.value = '本次更新执行完成'

    if (existingAppId.value) {
      await fetchDocVersions()
      await loadLatestDocForApp(existingAppId.value)
      await refreshCurrentAppRemoteMeta(existingAppId.value)
    }

    clearChangePlanState()
  } catch (err: any) {
    const detail = err?.message || '未知错误'
    updateExecutionItems.value = updateExecutionItems.value.map((item, index) => {
      const isFirstPending = item.status === 'current' || (item.status === 'pending' && !updateExecutionItems.value.slice(0, index).some(prev => prev.status === 'pending' || prev.status === 'current'))
      return isFirstPending ? { ...item, status: 'error', detail } : item
    })
    const emsg = messages.find(m => m.id === execMsgId)
    if (emsg) {
      emsg.content = `❌ 变更执行失败: ${detail}`
    }
    deployLastError.value = `更新执行失败：${detail}`
    deployOpen.value = true
    appendExecutionLog('error', `更新执行失败：${detail}`)
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
            store.setAppName(sk.appName)
            store.preview.roles = sk.roles || []
            // 用骨架的 dict_names 创建空字典占位
            store.preview.dicts = (sk.dict_names || []).map((d: any) => ({
              name: d.name, code: d.code, options: []
            }))
            // 用骨架的 model_names 创建空模型占位
            store.preview.models = (sk.model_names || []).map((m: any) => ({
              name: m.name, code: m.code, fields: []
            }))
            store.currentApp = { status: 'draft' }
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
            store.setAppName(d.appName)
            store.preview.roles = d.roles || store.preview.roles
            store.preview.dicts = d.dicts || store.preview.dicts
            store.preview.models = d.models || store.preview.models
            store.preview.forms = d.forms || store.preview.forms
            store.preview.workflows = d.workflows || []
            store.preview.permissions = d.permissions || []
            store.currentApp = { status: 'ready' }
            parseReady.value = true
          }

          if (evt.type === 'done') break

        } catch (e) { /* ignore parse errors */ }
      }
    }

    // 添加完成消息到对话
    if (conversationId.value && currentAgent.value === 'requirements') {
      try {
        await conversationApi.updateAgentType(conversationId.value, 'builder')
        currentAgent.value = 'builder'
      } catch {
        // 忽略切换失败，不影响右侧解析结果展示
      }
    }
    messages.push({
      id: Date.now(), role: 'assistant', agent: 'builder',
      content: `解析信息已生成！${store.preview.models.length} 个模型、${store.preview.dicts.length} 个字典、${store.preview.roles.length} 个角色。\n\n你可以继续补充右侧解析内容，确认无误后再点击 **开始构建**。`,
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

const generatePreviewFromConversation = async () => {
  if (assembling.value || generating.value) return
  const hasUserInput = messages.some(msg => msg.role === 'user' && msg.content.trim())
  if (!hasUserInput) {
    ElMessage.warning('先告诉我你想搭什么，再生成右侧解析信息')
    return
  }
  await startAssembleConfig()
}

const isConfirmationIntent = (text: string) => {
  const normalized = String(text || '').trim().toLowerCase()
  if (!normalized) return false
  const compact = normalized.replace(/\s+/g, '')
  if (compact.length > 24) return false
  const exactIntents = [
    '确认', '可以', '可以了', '好的', '好', 'ok', 'okay', '没问题', '就这样',
    '开始生成', '生成吧', '直接生成', '立即生成', '开始吧', '开始构建', '开始搭建', '继续生成', '继续'
  ]
  if (exactIntents.includes(compact)) return true
  return /^(可以|确认|好的|好|ok|没问题).*(生成|构建|搭建)$/.test(compact)
    || /^(开始|继续|直接|立即).*(生成|构建|搭建)$/.test(compact)
}

const isBuildStartIntent = (text: string) => {
  const normalized = String(text || '').trim().toLowerCase()
  if (!normalized) return false
  const compact = normalized.replace(/\s+/g, '')
  if (!compact || compact.length > 36) return false

  const exactIntents = [
    '开始构建', '开始搭建', '开始创建', '开始生成', '开始部署',
    '构建吧', '搭建吧', '创建吧', '生成吧', '部署吧',
    '可以开始构建', '可以开始搭建', '可以开始创建', '可以开始生成',
    '部署到预览', '发布到预览', '开始预览', '上线预览',
  ]
  if (exactIntents.includes(compact)) return true

  return /^(可以|确认|好的|好|ok|没问题)?(开始|继续|直接|立即)?(创建|构建|搭建|生成|部署|上线)(应用|配置|到预览|吧)?$/.test(compact)
    || /^(帮我|给我|麻烦)?(开始|直接)?(创建|构建|搭建|生成|部署)(这个|当前)?(应用|项目|配置)?(吧)?$/.test(compact)
}

const looksLikeGeneratedDesignDoc = (input: string) => {
  const text = String(input || '').trim()
  if (!text) return false
  const cleaned = stripHiddenAssistantBlocks(text)
  return (
    cleaned.includes('功能设计文档')
    || cleaned.includes('应用设计文档')
    || (cleaned.includes('## 一、') && cleaned.includes('## 四、数据模型'))
    || (cleaned.startsWith('# ') && cleaned.includes('## 一、项目目标'))
  )
}

const createConversation = async () => {
  const agentTypeForCreate = currentAgent.value as ConversationCreate['agent_type']
  try {
    let specIdForConversation = agentTypeForCreate === 'requirements'
      ? specStore.current?.id || null
      : null
    if (agentTypeForCreate === 'requirements' && !specIdForConversation) {
      try {
        specIdForConversation = await specStore.create(null)
      } catch (e) {
        console.warn('Failed to create spec, proceeding without spec_id', e)
      }
    }
    const data = await conversationApi.create({
      agent_type: agentTypeForCreate,
      ...(specIdForConversation ? { spec_id: specIdForConversation } : {}),
      ...(selectedBuilderModelId.value != null ? { selected_llm_config_id: selectedBuilderModelId.value } : {}),
    }) as any
    if (specIdForConversation) {
      try {
        await specStore.load(specIdForConversation)
      } catch (e) {
        console.warn('Failed to load spec into store', e)
      }
    }
    conversationId.value = data.id
    selectedConversationId.value = data.id
    applyBuilderModelSelection(data.selected_llm_config_id)
    // 更新 URL，刷新后能恢复对话
    router.replace(`/chat/${data.id}`)
    // 刷新对话列表
    fetchConversationList()
  } catch (e) {
    console.error('创建对话失败', e)
  }
}

const ensureApplicationUpdateConversation = async () => {
  if (conversationId.value) {
    try {
      await conversationApi.get(conversationId.value)
      return true
    } catch (e: any) {
      if (e?.response?.status !== 404) {
        console.warn('校验更新会话失败，将尝试创建新会话:', e)
      }
      conversationId.value = null
      selectedConversationId.value = null
    }
  }
  try {
    const data = await conversationApi.create({
      agent_type: 'builder',
      ...(selectedBuilderModelId.value != null ? { selected_llm_config_id: selectedBuilderModelId.value } : {}),
    }) as any
    conversationId.value = data.id
    selectedConversationId.value = data.id
    currentAgent.value = 'builder'
    applyBuilderModelSelection(data.selected_llm_config_id)
    router.replace({
      path: `/chat/${data.id}`,
      query: {
        ...route.query,
        ...(existingAppId.value ? { app_id: String(existingAppId.value) } : {}),
        view: 'builder',
      },
    })
    fetchConversationList()
    return true
  } catch (e) {
    console.error('创建更新对话失败', e)
    return false
  }
}

/**
 * 流式调用 draft-doc-update-stream：
 * - thinking 事件 → 调 onThinking 实时更新进度文案
 * - result 事件 → 拿到原 JSON（与同步版结构完全一致）
 * - error 事件 → 抛错让上层 catch
 * 体验对齐 ai-chat / vibe-coding：首字节 1s 内出，全程有 AI 在做什么的反馈
 */
async function streamDraftDocUpdate(
  appId: number,
  payload: { instruction: string; conversation_id?: number | null; selected_llm_config_id?: number | null; current_doc?: string },
  onThinking: (text: string) => void,
): Promise<any> {
  const token = localStorage.getItem('token') || ''
  const url = `${API_PREFIX}/applications/${appId}/draft-doc-update-stream`
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
    body: JSON.stringify(payload),
    signal: currentAbortController.value?.signal,
  })
  if (!response.ok) {
    let detail: any = ''
    try { detail = (await response.json())?.detail } catch { /* ignore */ }
    throw new Error(typeof detail === 'string' && detail ? detail : `请求失败 ${response.status}`)
  }
  const reader = response.body?.getReader()
  if (!reader) throw new Error('无法读取响应流')
  const decoder = new TextDecoder()
  let buffer = ''
  let currentEvent = ''
  let resolved: any = null
  let errorDetail: string | null = null

  while (true) {
    const { done, value } = await reader.read()
    if (value) buffer += decoder.decode(value, { stream: !done })
    const lines = buffer.split('\n')
    buffer = done ? '' : (lines.pop() || '')
    for (const rawLine of lines) {
      const line = rawLine.trimEnd()
      if (!line) { currentEvent = ''; continue }
      if (line.startsWith('event:')) { currentEvent = line.slice(6).trim(); continue }
      if (!line.startsWith('data:')) continue
      const dataStr = line.startsWith('data: ') ? line.slice(6) : line.slice(5)
      if (!dataStr.trim()) continue
      try {
        const parsed = JSON.parse(dataStr)
        if (currentEvent === 'thinking') {
          onThinking(String(parsed.data || '正在处理...'))
        } else if (currentEvent === 'result') {
          resolved = parsed
        } else if (currentEvent === 'error') {
          errorDetail = String(parsed.data || '响应失败')
        }
      } catch (err) { console.warn('SSE parse failed', err) }
    }
    if (done) break
  }
  if (errorDetail) throw new Error(errorDetail)
  if (resolved === null) throw new Error('未收到结果事件')
  return resolved
}

const submitApplicationUpdateMessage = async (
  text: string,
  attachmentPayload: { file: File; kind: 'image' | 'file'; previewUrl: string } | null
) => {
  if (!existingAppId.value) return
  isTyping.value = false
  currentAgent.value = 'builder'

  if (attachmentPayload) {
    if (attachmentPayload.kind === 'file' && /\.(md|markdown)$/i.test(attachmentPayload.file.name)) {
      updatingDocVersion.value = true
      try {
        await handleDocVersionUpload(attachmentPayload.file, existingAppId.value, {
          userMessageContent: null,
          title: '上传新版 SPEC 并分析更新',
          forceNewConversation: false,
        })
      } finally {
        updatingDocVersion.value = false
      }
      return
    }

    messages.push({
      id: Date.now(),
      role: 'assistant',
      agent: 'builder',
      content: '更新应用当前支持直接描述修改诉求，或上传 Markdown 版新版 SPEC。其他附件请先转成文字描述后再发送。',
      created_at: ''
    })
    scrollToBottom()
    return
  }

  const instruction = text.trim()
  if (!instruction) {
    messages.push({
      id: Date.now(),
      role: 'assistant',
      agent: 'builder',
      content: '请直接描述这次要更新的内容，例如新增字段、调整表单、补充权限或优化流程。',
      created_at: ''
    })
    scrollToBottom()
    return
  }

  // 用 Date.now()+随机后缀避免和 sendMessage 里刚刚 push 的 user 消息撞 id
  // （两个 push 在同一 ms 内时，下面 messages.find(msg.id === progressMsgId)
  //  会命中 user 消息并把它的 content 覆盖成 AI summary，相当于"用户消息没了"）
  const progressMsgId = Date.now() + Math.floor(Math.random() * 10000) + 1
  messages.push({
    id: progressMsgId,
    role: 'assistant',
    agent: 'builder',
    content: '正在理解你的诉求，并判断要改哪一块配置...',
    created_at: ''
  })
  scrollToBottom()

  updatingDocVersion.value = true
  try {
    const currentDoc = (
      selectedDocDisplayContent.value ||
      latestDocContent.value ||
      buildDocMarkdownFromPreview(currentPreviewConfigPayload.value)
    ).trim()
    const shouldSendInlineDoc = docVersions.value.length === 0 && currentDoc.length > 0 && currentDoc.length <= 12000
    const result = await streamDraftDocUpdate(existingAppId.value, {
      instruction,
      conversation_id: conversationId.value,
      selected_llm_config_id: selectedBuilderModelId.value,
      ...(shouldSendInlineDoc ? { current_doc: currentDoc } : {}),
    }, (thinkingText) => {
      // 流式 thinking 事件 → 实时更新进度 message，让用户看到 AI 正在做什么
      const progressMsg = messages.find(msg => msg.id === progressMsgId && msg.role === 'assistant')
      if (progressMsg) progressMsg.content = thinkingText
    })

    if (result?.actionable_update === false || result?.type === 'assistant_reply') {
      const progressMsg = messages.find(msg => msg.id === progressMsgId && msg.role === "assistant")
      if (progressMsg) {
        progressMsg.content = result.message || result.summary || '我理解了。你可以继续补充要调整的业务范围、字段、表单、权限或流程。'
      }
      return
    }

    if (result?.direct_config_update && (result.change_plan || result.change_plan_id)) {
      const planPayload = result.change_plan || result
      const parsedConfig = planPayload.parsed_config?.data || planPayload.parsed_config || result.app_config?.data || result.app_config
      if (parsedConfig) {
        hydratePreviewFromConfig(parsedConfig)
        store.currentApp = {
          ...(store.currentApp || {}),
          status: 'updating',
          apaas_app_id: store.currentApp?.apaas_app_id,
        }
      }
      latestParseMeta.value = planPayload.parse_meta || null
      currentDocVersionNumber.value = Number(planPayload.to_version || planPayload.version || currentDocVersionNumber.value || 1)
      lastParsedFilename.value = result.filename || lastParsedFilename.value
      const renderedDoc = planPayload.rendered_doc || result.rendered_doc || result.markdown || ''
      if (renderedDoc) {
        syncCurrentDocFromPreview('当前更新后的最新文档', renderedDoc)
      }
      applyChangePlanState(planPayload)
      await fetchDocVersions()
      const progressMsg = messages.find(msg => msg.id === progressMsgId && msg.role === "assistant")
      if (progressMsg) {
        const actionCount = Array.isArray(planPayload.actions) ? planPayload.actions.length : changePlanTotalCount.value
        progressMsg.content = `${result.summary || '已生成本次配置变更计划。'}\n\n右侧已更新 SPEC，并识别出 ${actionCount || 0} 项可执行变更。确认后点击「执行更新」同步到平台。`
      }
      return
    }

    if (!result?.markdown?.trim()) {
      throw new Error('后端未返回新版 SPEC 内容')
    }

    const progressMsg = messages.find(msg => msg.id === progressMsgId && msg.role === "assistant")
    if (progressMsg) {
      progressMsg.content = `${result.summary || '新版 SPEC 已生成'}\n\n正在生成配置变更计划...`
    }
    const generatedFile = new File(
      [result.markdown],
      result.filename || `${displayAppCode.value || 'app'}-update-${Date.now()}.md`,
      { type: 'text/markdown' }
    )
    await handleDocVersionUpload(generatedFile, existingAppId.value, {
      userMessageContent: null,
      title: '根据对话生成新版 SPEC 并分析变更',
      forceNewConversation: false,
    })
  } catch (error: any) {
    const progressMsg = messages.find(msg => msg.id === progressMsgId && msg.role === "assistant")
    if (progressMsg) {
      progressMsg.content = `更新分析失败：${error?.response?.data?.detail || error?.message || '请稍后重试'}`
    }
    handleError(error, { fallback: '生成新版 SPEC 失败' })
  } finally {
    updatingDocVersion.value = false
    scrollToBottom()
  }
}

const sendMessage = async () => {
  if (!canSendMessage.value || sendingMessage.value) return
  sendingMessage.value = true
  // 新建本轮请求的 AbortController；用户点中断按钮 → controller.abort() → 所有 fetch 立即终止
  currentAbortController.value = new AbortController()
  const abortSignal = currentAbortController.value.signal
  const text = inputText.value.trim()
  const attachmentPayloads = pendingChatAttachments.value.slice()
  inputText.value = ''
  pendingChatAttachments.value = []
  if (chatImageInputRef.value) chatImageInputRef.value.value = ''
  messages.push({
    id: Date.now(),
    role: 'user',
    content: attachmentPayloads.length > 0
      ? buildUserChatAttachmentContent(text, attachmentPayloads)
      : text,
    created_at: ''
  })
  scrollToBottom()
  isTyping.value = true

  if (!conversationId.value && pendingInitialConversationPromise) {
    await pendingInitialConversationPromise
  }

  const isApplicationUpdateMessage = isApplicationUpdateChatMode.value && isPlatformDeployed.value && !!existingAppId.value

  // 如果还没有对话，先创建
  if (!conversationId.value) {
    if (isApplicationUpdateMessage) {
      await ensureApplicationUpdateConversation()
    } else {
      await createConversation()
    }
  }

  if (!conversationId.value) {
    isTyping.value = false
    sendingMessage.value = false
    messages.push({ id: Date.now(), role: 'assistant', agent: currentAgent.value, content: '创建对话失败，请重试。', created_at: '' })
    scrollToBottom()
    return
  }

  if (isApplicationUpdateMessage) {
    // 应用更新流程暂只支持单个附件（保留旧 API 签名），多文件场景取第一个
    await submitApplicationUpdateMessage(text, attachmentPayloads[0] || null)
    sendingMessage.value = false
    if (chatImageInputRef.value) {
      chatImageInputRef.value.value = ''
    }
    return
  }

  const shouldStartBuildFromChat = !isRequirementsMode.value
    && attachmentPayloads.length === 0
    && isBuildStartIntent(text)
    && hasPreviewContent.value
    && !deployAllDone.value
    && !deployRunningAll.value
    && deployExecuting.value === null

  if (shouldStartBuildFromChat) {
    isTyping.value = false
    messages.push({
      id: Date.now(),
      role: 'assistant',
      agent: currentAgent.value,
      content: '收到，我现在开始构建并部署到预览。执行进度会在右侧构建面板里显示。',
      created_at: ''
    })
    scrollToBottom()
    await startDeployFlow()
    sendingMessage.value = false
    return
  }

  const shouldSwitchToBuilder = !attachmentPayloads.some(a => a.kind === 'image')
    && (parseReady.value || !!existingAppId.value || hasPreviewContent.value)
    && currentAgent.value === 'requirements'
    && !specStore.current

  if (shouldSwitchToBuilder && conversationId.value) {
    try {
      await conversationApi.updateAgentType(conversationId.value, 'builder')
      currentAgent.value = 'builder'
    } catch (e) {
      console.warn('Failed to switch conversation to builder mode before sending message', e)
    }
  }

  const incrementalConfigPayload = (parseReady.value || !!existingAppId.value || hasPreviewContent.value)
    ? { type: 'preview', data: currentPreviewConfigPayload.value }
    : null

  // 调用后端API
  try {
    const token = localStorage.getItem('token')
    const response = attachmentPayloads.length > 0
      ? await (() => {
          const formData = new FormData()
          formData.append('message', text)
          // 多文件：每个 attachment 都 append 同名 'files'，FastAPI 会收成 List[UploadFile]
          for (const att of attachmentPayloads) {
            formData.append('files', att.file)
          }
          formData.append('conversation_id', String(conversationId.value))
          if (incrementalConfigPayload) {
            formData.append('current_config', JSON.stringify(incrementalConfigPayload))
          }
          // Phase E E3：传 application_id 激活 Phase B fork hook
          // chat.py 当 conversation.spec_id 空 + application 有 canonical 时
          // 自动 fork canonical → personal draft，SpecAgent 编辑的是 draft
          {
            const appIdNum = Number(store.currentApp?.id)
            if (Number.isFinite(appIdNum) && appIdNum > 0) {
              formData.append('application_id', String(appIdNum))
            }
          }
          const url = `${API_PREFIX}/chat/send-with-file`
          return fetch(url, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` },
            body: formData,
            signal: abortSignal,
          })
        })()
      : await (() => {
          const url = `${API_PREFIX}/chat/send`
          const appIdNum = Number(store.currentApp?.id)
          const body: Record<string, any> = {
            conversation_id: conversationId.value,
            message: text,
            ...(incrementalConfigPayload ? { current_config: incrementalConfigPayload } : {}),
            ...(Number.isFinite(appIdNum) && appIdNum > 0 ? { application_id: appIdNum } : {}),
          }
          return fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            body: JSON.stringify(body),
            signal: abortSignal,
          })
        })()

    if (!response.ok) throw new Error('发送失败')

    const reader = response.body?.getReader()
    const decoder = new TextDecoder()
    let assistantContent = ''
    let sseBuffer = ''
    let currentEvent = ''
    let serverConfigReceived = false  // 服务端已推送 config，done 时跳过客户端重提取
    let specPatchReceived = false
    let toolErrorCount = 0

    if (!reader) throw new Error('无法读取响应')

    const updateStreamStatus = (statusText: string) => {
      if (!getRenderableContentText(assistantContent)) {
        setStreamingAssistantMessage(statusText)
      }
    }

    updateStreamStatus('正在理解你的需求...')

    while (true) {
      const { done, value } = await reader.read()
      if (value) sseBuffer += decoder.decode(value, { stream: !done })

      const lines = sseBuffer.split('\n')
      sseBuffer = done ? '' : (lines.pop() || '')

      for (const rawLine of lines) {
        const line = rawLine.trimEnd()
        if (!line) {
          currentEvent = ''
          continue
        }
        if (line.startsWith('event:')) {
          currentEvent = line.slice(6).trim()
          continue
        }
        if (!line.startsWith('data:')) continue

        const dataStr = line.startsWith('data: ') ? line.slice(6) : line.slice(5)
        if (!dataStr.trim()) continue
        try {
          const parsed = JSON.parse(dataStr)
          const normalizedType = parsed.type || currentEvent

          if (normalizedType === 'thinking') {
            updateStreamStatus(String(parsed.data || parsed.content || '正在思考你的需求...'))
            continue
          }

          if (normalizedType === 'message' || normalizedType === 'chunk') {
            const content = parsed.data ?? parsed.content ?? ''
            if (!content) continue
            assistantContent += content
            const renderableAssistantContent = getRenderableContentText(assistantContent)
            if (!renderableAssistantContent) {
              updateStreamStatus('正在整理回复内容...')
              continue
            }
            isTyping.value = false
            const lastMsg = messages[messages.length - 1]
            streamingAssistantMessageId.value = STREAMING_ASSISTANT_ID
            if (lastMsg && lastMsg.role === 'assistant' && lastMsg.agent === currentAgent.value && lastMsg.id === STREAMING_ASSISTANT_ID) {
              lastMsg.content = assistantContent
            } else {
              messages.push({ id: STREAMING_ASSISTANT_ID, role: 'assistant', agent: currentAgent.value, content: assistantContent, created_at: '' })
            }
            scrollToBottom()
            continue
          }

          if (normalizedType === 'error') {
            isTyping.value = false
            const detail = parsed.data || parsed.message || '模型返回异常，请切换模型后重试。'
            const specVersionMismatch = /Spec\s+\S+\s+version mismatch/i.test(String(detail))
            if (specVersionMismatch && specStore.current?.id) {
              try {
                await specStore.load(specStore.current.id)
              } catch (e) {
                console.warn('刷新 SPEC 状态失败:', e)
              }
            }
            replaceOrAppendAssistantMessage(
              specVersionMismatch
                ? 'SPEC 状态同步遇到版本冲突，已刷新本地状态。请重新发送这条消息。'
                : `AI 响应失败：${detail}`
            )
            sendingMessage.value = false
            return
          }

          // 服务端推送 config（pipeline 解析完成 或 LLM 生成/patch 后）
          if (normalizedType === 'config' || currentEvent === 'config') {
            const configData = parsed.data ?? parsed
            if (configData && typeof configData === 'object') {
              const d = configData.data ?? configData
              if (d.appName !== undefined) store.setAppName(d.appName)
              if (Array.isArray(d.roles)) store.preview.roles = d.roles
              if (Array.isArray(d.dicts)) store.preview.dicts = d.dicts
              if (Array.isArray(d.models)) store.preview.models = d.models
              if (Array.isArray(d.forms)) store.preview.forms = d.forms
              if (Array.isArray(d.permissions)) store.preview.permissions = d.permissions
              parseReady.value = true
              serverConfigReceived = true  // 服务端已合并，done 时跳过客户端重提取
              updateStreamStatus('正在更新右侧配置预览...')
            }
            continue
          }

          if (currentEvent === 'spec_patch' || normalizedType === 'spec_patch') {
            if (parsed?.data) {
              specStore.applyPatch(parsed.data)
              specPatchReceived = true
              updateStreamStatus('正在把确认结果写入 SPEC...')
            }
            continue
          }

          if (currentEvent === 'tool_error' || normalizedType === 'tool_error') {
            toolErrorCount += 1
            updateStreamStatus(
              toolErrorCount === 1
                ? '正在校验已有配置，避免重复写入...'
                : `正在处理第 ${toolErrorCount} 个校验提示...`
            )
            continue
          }

          if (normalizedType === 'progress' || currentEvent === 'progress') {
            // pipeline 解析进度：有局部数据时实时更新右侧预览
            if (parsed.module && Array.isArray(parsed.data)) {
              const mod = parsed.module as string
              const data = parsed.data
              if (mod === 'roles') store.preview.roles = data
              else if (mod === 'dicts') store.preview.dicts = data
              else if (mod === 'models') store.preview.models = data
              else if (mod === 'forms') store.preview.forms = data
              else if (mod === 'permissions') store.preview.permissions = data
              parseReady.value = true
              serverConfigReceived = true
              updateStreamStatus('正在更新右侧预览...')
            }
            continue
          }

          if (normalizedType === 'done') {
            const lastMsg = messages[messages.length - 1]
            const fallbackMessage = specPatchReceived
              ? '已更新 SPEC，右侧预览已同步。你可以继续确认，或者告诉我下一步要调整什么。'
              : serverConfigReceived
                ? '已更新右侧配置预览。'
                : ''
            if (!assistantContent && fallbackMessage) {
              assistantContent = fallbackMessage
              if (lastMsg && lastMsg.id === STREAMING_ASSISTANT_ID) {
                lastMsg.content = fallbackMessage
              }
            }
            if (lastMsg && lastMsg.id === STREAMING_ASSISTANT_ID) lastMsg.id = Date.now()
            streamingAssistantMessageId.value = null
            isTyping.value = false
            // 服务端已推送合并后的 config，跳过客户端重提取，避免 patch 二次应用
            const patchApplied = serverConfigReceived ? false : await extractPatchData(assistantContent)
            if (!patchApplied && !serverConfigReceived) extractPreviewData(assistantContent)
            if (!store.currentApp && assistantContent.length > 50) {
              const appNameMatch = assistantContent.match(/搭建.*?[**](.+?)[**]/)
              if (appNameMatch) {
                store.setAppName(appNameMatch[1])
                store.currentApp = { status: 'talking' }
              }
            }
          }
        } catch (e) { /* ignore parse errors */ }
      }

      if (done) {
        break
      }
    }
    if (!assistantContent) {
      replaceOrAppendAssistantMessage('当前模型没有返回内容，请切换模型后再试一次。')
    }
  } catch (error) {
    // 用户主动中断 → AbortError，不当作"发送失败"显示红字
    if ((error as Error)?.name === 'AbortError') {
      replaceOrAppendAssistantMessage('已中断本次回复。')
    } else {
      console.error('Send error:', error)
      replaceOrAppendAssistantMessage('发送失败，请重试。')
    }
  } finally {
    streamingAssistantMessageId.value = null
    sendingMessage.value = false
    isTyping.value = false
    currentAbortController.value = null
    if (pendingChatAttachments.value.length === 0 && chatImageInputRef.value) {
      chatImageInputRef.value.value = ''
    }
  }
}

function normalizeCustomDevelopmentItems(preview: any): CustomDevelopmentItem[] {
  const source = preview?.custom_development
    || preview?.customDevelopment
    || preview?.customDevelopments
    || preview?.custom_dev
    || preview?.customDev
  const items = Array.isArray(source)
    ? source
    : (source?.items || source?.tasks || source?.features || [])
  if (!Array.isArray(items)) return []

  return items
    .map((item: any, index: number) => ({
      type: String(item?.type || item?.scene || item?.category || '开发扩展').trim(),
      name: String(item?.name || item?.item_name || item?.title || item?.module || `开发项 ${index + 1}`).trim(),
      trigger: String(item?.trigger || item?.reason || item?.condition || item?.description || '配置能力无法完整覆盖').trim(),
      scope: String(item?.scope || item?.implementation || item?.deliverable || item?.deliverables || '在 IDE 中实现并回写项目上下文').trim(),
      acceptance: String(item?.acceptance || item?.acceptance_criteria || item?.test || '完成源码、联调和可演示验证').trim(),
    }))
    .filter((item: any) => item.name)
}

const syncCustomDevelopmentFromDocResult = (docResult: any) => {
  const source = docResult?.custom_development
    || docResult?.customDevelopment
    || docResult?.customDevelopments
    || docResult?.custom_dev
    || docResult?.customDev
  const items = Array.isArray(source)
    ? source
    : (source?.items || source?.tasks || source?.features || [])
  ;(store.preview as any).custom_development = Array.isArray(items) ? items : []
  const flows = docResult?.flows || docResult?.workflows
  ;(store.preview as any).flows = Array.isArray(flows) ? flows : []
}

function setPreviewCustomDevelopment(source: any) {
  const hasCustomSource = !!source && (
    Object.prototype.hasOwnProperty.call(source, 'custom_development')
    || Object.prototype.hasOwnProperty.call(source, 'customDevelopment')
    || Object.prototype.hasOwnProperty.call(source, 'customDevelopments')
    || Object.prototype.hasOwnProperty.call(source, 'custom_dev')
    || Object.prototype.hasOwnProperty.call(source, 'customDev')
  )
  if (hasCustomSource) {
    ;(store.preview as any).custom_development = normalizeCustomDevelopmentItems(source)
  }
  if (Array.isArray(source?.flows)) {
    ;(store.preview as any).flows = source.flows
  }
}

function buildGeneratedPreviewPayload(appConfig: any, docResult: any) {
  const rawFlows = Array.isArray(docResult?.flows)
    ? docResult.flows
    : Array.isArray(appConfig?.flows)
      ? appConfig.flows
      : Array.isArray(docResult?.workflows)
        ? docResult.workflows
        : []
  return {
    ...appConfig,
    flows: rawFlows,
    custom_development: normalizeCustomDevelopmentItems(docResult),
  }
}

function isActionableCustomDev(item: CustomDevelopmentItem) {
  const type = String(item.type || '').trim().toLowerCase()
  const text = `${item.type} ${item.name} ${item.trigger} ${item.scope}`.toLowerCase()
  if (!item.name.trim()) return false
  if (['none', 'no', 'no_custom', 'config_only', 'configuration', '配置优先'].includes(type)) return false
  if (text.includes('暂无强制开发扩展') || text.includes('无需开发扩展') || text.includes('配置优先')) return false
  return true
}

function customDevTypeLabel(type: string) {
  const normalized = String(type || '').trim().toLowerCase()
  const labels: Record<string, string> = {
    form_component: '表单组件',
    component: '组件',
    form_page: '表单页面',
    web_page: 'PC 页面',
    list_custom_module: '列表模块',
    web_list_view: '列表视图',
    mobile_page: '移动页面',
    mobile_component: '移动组件',
    backend_api: '后端接口',
    backend: '后端能力',
    integration: '外部集成',
    hook: 'Hook',
    report: '报表看板',
    plugin: '插件',
    none: '配置优先',
    no_custom: '配置优先',
    config_only: '配置优先',
  }
  return labels[normalized] || type || '开发扩展'
}

function inferCodingSceneCategory(type: string) {
  const normalized = String(type || '').trim().toLowerCase()
  if (normalized.includes('mobile') && normalized.includes('page')) return 'page-mobile'
  if (normalized.includes('mobile')) return 'component-mobile'
  if (
    normalized.includes('backend')
    || normalized.includes('api')
    || normalized.includes('integration')
    || normalized.includes('hook')
    || normalized.includes('plugin')
    || normalized.includes('接口')
  ) {
    return 'backend'
  }
  if (
    normalized.includes('page')
    || normalized.includes('list')
    || normalized.includes('report')
    || normalized.includes('看板')
    || normalized.includes('页面')
    || normalized.includes('列表')
  ) {
    return 'page-pc'
  }
  return 'component-pc'
}

function truncateCodingContext(content: string, maxLength = 12000) {
  const normalized = String(content || '').trim()
  if (normalized.length <= maxLength) return normalized
  return `${normalized.slice(0, maxLength)}\n\n...（SPEC 过长，已截断；请以当前应用上下文继续实现）`
}

function resolveCurrentSpecMarkdown() {
  const fromDoc = String(selectedDocDisplayContent.value || latestDocContent.value || chatGeneratedDocContent.value || '').trim()
  if (fromDoc) return fromDoc
  return buildDocMarkdownFromPreview(currentPreviewConfigPayload.value)
}

function buildCustomDevCodingBrief(item: CustomDevelopmentItem, index: number) {
  const specContext = truncateCodingContext(resolveCurrentSpecMarkdown())
  return [
    '# 来自 aPaaS Builder SPEC 的开发任务',
    '',
    `应用名称：${store.preview.appName || builderAppDisplayName.value || '未命名应用'}`,
    `应用编码：${displayAppCode.value || '-'}`,
    `任务编号：DEV-${index + 1}`,
    `开发类型：${customDevTypeLabel(item.type)}（${item.type || '-'}）`,
    `任务名称：${item.name}`,
    '',
    '## 触发条件',
    item.trigger,
    '',
    '## 实现范围',
    item.scope,
    '',
    '## 验收口径',
    item.acceptance,
    '',
    '## 执行要求',
    '- 先判断该内容是否确实需要进入开发入口；如果平台配置可覆盖，说明原因并给出配置方案。',
    '- 如果确实需要开发扩展，按当前项目的 Vibe Coding 规范实现，并保留可验证说明。',
    '- 不要改动与本任务无关的模型、表单、流程、权限定义。',
    '',
    '## 当前 SPEC 上下文',
    '```markdown',
    specContext,
    '```',
  ].join('\n')
}

function buildGeneralSpecCodingBrief() {
  const specContext = truncateCodingContext(resolveCurrentSpecMarkdown())
  return [
    '# 从当前 SPEC 进入 IDE',
    '',
    `应用名称：${store.preview.appName || builderAppDisplayName.value || '未命名应用'}`,
    `应用编码：${displayAppCode.value || '-'}`,
    '',
    '当前 SPEC 没有识别到强制开发扩展。请先基于 SPEC 检查是否存在配置能力无法覆盖的复杂组件、Hook、外部接口、算法规则或报表看板。',
    '如果存在，请拆分为可实现的开发任务；如果不存在，请输出“配置优先”的判断和建议。',
    '',
    '## 当前 SPEC 上下文',
    '```markdown',
    specContext,
    '```',
  ].join('\n')
}

function dispatchCodingTask(message: string, sceneCategory: string) {
  const payload = {
    message,
    projectId: activeProjectId.value || null,
    sceneCategory,
  }
  window.sessionStorage.setItem(AI_BUILDER_PENDING_CODING_KEY, JSON.stringify(payload))
  codingDispatchToken.value = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  openCodingWorkspace(codingDispatchToken.value)
}

function dispatchCustomDevToCoding(item: CustomDevelopmentItem, index: number) {
  if (!isActionableCustomDev(item)) return
  dispatchCodingTask(buildCustomDevCodingBrief(item, index), inferCodingSceneCategory(item.type))
  ElMessage.success('已将开发任务派发到 IDE')
}

function dispatchGeneralSpecToCoding() {
  dispatchCodingTask(buildGeneralSpecCodingBrief(), 'component-pc')
  ElMessage.success('已将当前 SPEC 带入 IDE')
}

const buildDocMarkdownFromPreview = (previewOverride?: any) => {
  const preview = previewOverride || store.preview
  const appName = preview?.appName || ''
  const appCode = previewOverride ? (preview?.appCode || '') : displayAppCode.value
  const lines: string[] = []
  const models = preview?.models || []
  const forms = preview?.forms || []
  const workflows = preview?.workflows || preview?.flows || []
  const { modelsByCode, fieldsByModel } = docExportModelMaps(models)

  lines.push(`# ${appName}`, '', '## 一、应用信息', '')
  lines.push('| 应用编码 | 应用名称 |', '|---------|---------|')
  lines.push(`| ${appCode} | ${appName} |`, '', '---', '')

  lines.push('## 二、角色列表', '')
  const roles = preview?.roles || []
  if (roles.length) {
    lines.push('| 角色编码 | 角色名称 | 职责说明 |', '|---------|---------|---------|')
    roles.forEach((r: any) => lines.push(`| ${r?.code || ''} | ${r?.name || ''} | ${r?.description || ''} |`))
  } else {
    lines.push('暂无角色配置')
  }
  lines.push('', '---', '')

  lines.push('## 三、数据字典', '')
  const dicts = preview?.dicts || []
  if (dicts.length) {
    dicts.forEach((dict: any) => {
      lines.push(`### ${dict?.name || dict?.code || '未命名字典'}（${dict?.code || ''}）`, '')
      lines.push('| 选项编码 | 选项名称 |', '|---------|---------|')
      const opts = dict?.options || []
      if (opts.length) {
        opts.forEach((item: any) => {
          const name = typeof item === 'string' ? item : (item?.name || item?.item_name || '')
          const code = typeof item === 'string' ? '' : (item?.code || item?.item_code || '')
          lines.push(`| ${code} | ${name} |`)
        })
      } else {
        lines.push('| - | - |')
      }
      lines.push('')
    })
  } else {
    lines.push('暂无数据字典')
  }
  lines.push('---', '')

  lines.push('## 四、数据模型', '')
  if (models.length) {
    models.forEach((model: any) => {
      const tag = model?.table_type === '子表' || model?.parent_code ? '【子表】' : '【主表】'
      lines.push(`### ${model?.name || model?.code || '未命名模型'}（${model?.code || ''}）${tag}`, '')
      lines.push('| 字段编码 | 字段名称 | 字段类型 | 字典编码 | 关联模型编码 | 关联显示字段编码 |')
      lines.push('|---------|---------|---------|---------|------------|----------------|')
      const fields = model?.fields || []
      if (fields.length) {
        fields.forEach((f: any) => {
          const dictCode = f?.dict || f?.dictCode || ''
          const refModel = f?.ref?.model || f?.refModelCode || ''
          const refField = f?.ref?.field || f?.refDisplayField || ''
          lines.push(`| ${f?.code || ''} | ${f?.name || ''} | ${f?.type || ''} | ${dictCode} | ${refModel} | ${refField} |`)
        })
      } else {
        lines.push('| - | - | - | | | |')
      }
      lines.push('')
    })
  } else {
    lines.push('暂无数据模型')
  }
  lines.push('---', '')

  lines.push('## 五、表单配置', '')
  if (forms.length) {
    forms.forEach((form: any, formIndex: number) => {
      const formName = form?.formName || form?.name || form?.formCode || '未命名表单'
      const formCode = form?.formCode || form?.code || ''
      const modelCode = form?.modelCode || form?.bindModelCode || ''
      const fieldMap = fieldsByModel.get(String(modelCode || '')) || new Map<string, any>()
      const components = form?.components || []
      const mainComponents = components.filter((component: any) => !isSubTableComponent(component))
      const subTables = components.filter((component: any) => isSubTableComponent(component))

      lines.push(`### ${formName}（${formCode}）`, '')
      lines.push(`绑定模型：${modelCode || '-'}`, '')
      lines.push(`#### 5.${formIndex + 1}.1 主表字段组件`, '')
      lines.push('| 字段编码 | 字段名称 | 组件类型 | 必填 | 隐藏 | 只读 | 列表展示 | 查询条件 | 说明 |')
      lines.push('|---------|---------|---------|------|------|------|----------|----------|------|')
      if (mainComponents.length) {
        mainComponents.forEach((component: any) => {
          const fieldCode = String(component?.code || docExportFieldCode(component?.modelField || ''))
          const fieldMeta = fieldMap.get(fieldCode) || {}
          lines.push(`| ${fieldCode} | ${component?.label || component?.name || fieldMeta?.name || ''} | ${docExportComponentTypeLabel(component?.componentType || component?.component_type, fieldMeta?.type)} | ${docExportBool(component?.required)} | ${docExportBool(component?.hidden)} | ${docExportBool(component?.readonly || component?.readOnly)} | ${docExportBool(component?.showInList || component?.list_visible)} | ${docExportBool(component?.searchable || component?.queryable)} | ${component?.description || fieldMeta?.description || ''} |`)
        })
      } else {
        lines.push('| - | - | - | 否 | 否 | 否 | 否 | 否 | |')
      }
      lines.push('', `#### 5.${formIndex + 1}.2 子表区域`, '')
      if (subTables.length) {
        lines.push('| 子表模型编码 | 子表模型名称 | 子表显示名称 |')
        lines.push('|---------------|--------------|--------------|')
        subTables.forEach((subTable: any, subIndex: number) => {
          const subModelCode = String(subTable?.tableModelCode || subTable?.table_model_code || '')
          const subModel = modelsByCode.get(subModelCode) || {}
          const subFields = fieldsByModel.get(subModelCode) || new Map<string, any>()
          const subLabel = subTable?.label || subTable?.name || subModel?.name || subModelCode
          lines.push(`| ${subModelCode} | ${subModel?.name || ''} | ${subLabel} |`)
          lines.push('', `##### 5.${formIndex + 1}.2.${subIndex + 1} 子表：${subLabel}`, '')
          lines.push('| 子表字段编码 | 子表字段名称 | 组件类型 | 必填 | 隐藏 | 只读 | 列表展示 | 查询条件 | 说明 |')
          lines.push('|-------------|-------------|---------|------|------|------|----------|----------|------|')
          const columns = subTable?.tableColumn || subTable?.table_column || []
          if (columns.length) {
            columns.forEach((column: any) => {
              const fieldCode = String(column?.code || docExportFieldCode(column?.modelField || ''))
              const fieldMeta = subFields.get(fieldCode) || {}
              lines.push(`| ${fieldCode} | ${column?.label || column?.name || fieldMeta?.name || ''} | ${docExportComponentTypeLabel(column?.componentType || column?.component_type, fieldMeta?.type)} | ${docExportBool(column?.required)} | ${docExportBool(column?.hidden)} | ${docExportBool(column?.readonly || column?.readOnly)} | ${docExportBool(column?.showInList || column?.list_visible)} | ${docExportBool(column?.searchable || column?.queryable)} | ${column?.description || fieldMeta?.description || ''} |`)
            })
          } else {
            lines.push('| - | - | - | 否 | 否 | 否 | 否 | 否 | |')
          }
          lines.push('')
        })
      } else {
        lines.push('无', '')
      }
    })
  } else {
    lines.push('暂无表单配置')
  }
  lines.push('---', '')

  lines.push('## 六、流程配置', '')
  if (workflows.length) {
    workflows.forEach((flow: any, flowIndex: number) => {
      const flowName = flow?.name || flow?.flow_name || flow?.workflowName || `流程${flowIndex + 1}`
      const flowCode = flow?.code || flow?.flow_code || flow?.workflowCode || ''
      const flowDesc = flow?.description || flow?.remark || ''
      lines.push(`### ${flowName}（${flowCode || '-'}）`, '')
      if (flowDesc) lines.push(flowDesc, '')
      const steps = flow?.steps || flow?.nodes || flow?.actions || []
      lines.push('| 步骤 | 动作 | 角色 | 状态/结果 |')
      lines.push('|------|------|------|-----------|')
      if (steps.length) {
        steps.forEach((step: any, stepIndex: number) => {
          lines.push(`| ${step?.step || stepIndex + 1} | ${step?.action || step?.name || step?.label || ''} | ${step?.role || step?.assignee || ''} | ${step?.status || step?.result || ''} |`)
        })
      } else {
        lines.push('| - | - | - | - |')
      }
      lines.push('')
    })
  } else {
    lines.push('暂无流程配置；默认先按表单的基础新增、查看、编辑和权限控制闭环。')
  }
  lines.push('', '---', '')

  lines.push('## 七、权限配置', '')
  const perms = preview?.permissions || []
  if (perms.length) {
    lines.push('| 表单名称 | 角色编码 | 可暂存 | 可新增 | 可导入 | 可查看 | 可编辑 | 可删除 | 可导出 | 数据范围 |')
    lines.push('|---------|---------|------|------|------|------|------|------|------|---------|')
    const scopeLabel: Record<string, string> = {
      ALL: '全公司', SELF: '仅本人',
      CURRENT_USER_DEPT: '本部门',
      CURRENT_USER_DEPT_LOW_LEVEL: '本部门及下属部门',
    }
    const yn = (v: any) => v ? '是' : '否'
    perms.forEach((perm: any) => {
      const formName = perm?.form || ''
      ;(perm?.rules || []).forEach((rule: any) => {
        const isAll = rule?.op === 'all'
        const ops = (rule?.op || '').split(',')
        const hasOp = (op: string) => isAll || ops.includes(op)
        const scope = scopeLabel[rule?.data] || rule?.data || '全公司'
        lines.push(`| ${formName} | ${rule?.role || ''} | ${yn(rule?.canDraft)} | ${yn(hasOp('add'))} | ${yn(rule?.canImport)} | ${yn(hasOp('view'))} | ${yn(hasOp('edit'))} | ${yn(hasOp('delete'))} | ${yn(rule?.canExport)} | ${scope} |`)
      })
    })
  } else {
    lines.push('暂无权限配置')
  }
  lines.push('', '---', '')

  lines.push('## 八、开发边界', '')
  lines.push('### 8.1 开发边界说明', '')
  lines.push('| 范围 | 说明 | 交付物 |')
  lines.push('|------|------|--------|')
  lines.push('| 平台配置优先 | 数据模型、表单布局、权限矩阵、基础流程和字典优先由 aPaaS 配置生成 | 配置预览、部署流水线 |')
  lines.push('| 开发触发条件 | 复杂前端组件、定制页面、外部系统接口、复杂校验/计算、Hook、报表看板等配置无法完整覆盖的内容 | IDE 任务、源码变更、测试说明 |')
  lines.push('', '### 8.2 已识别开发项', '')
  lines.push('| 类型 | 名称 | 触发条件 | 实现范围 | 验收口径 |')
  lines.push('|------|------|----------|----------|----------|')
  const customDevItems = normalizeCustomDevelopmentItems(preview)
  if (customDevItems.length) {
    customDevItems.forEach(item => {
      lines.push(`| ${item.type} | ${item.name} | ${item.trigger} | ${item.scope} | ${item.acceptance} |`)
    })
  } else {
    lines.push('| 暂无强制开发扩展 | 配置优先 | 当前需求可先由模型、表单、权限和流程配置覆盖 | 如后续出现复杂交互、外部接口或算法规则，再进入 IDE 补充 | 低代码配置可完成主流程演示 |')
  }
  lines.push('')

  return lines.join('\n')
}

const buildDocMarkdownFromVersion = (item?: DocVersionListItem | null) => {
  const parsed = item?.parsed_config?.data || item?.parsed_config
  if (parsed && typeof parsed === 'object') {
    return buildDocMarkdownFromPreview(parsed).trim()
  }
  return ''
}

const downloadCurrentDoc = () => {
  const content = selectedDocDisplayContent.value.trim()
  const filename = buildDocFilename(selectedDocVersionItem.value || displayDocVersions.value[0])
  if (!content) {
    ElMessage.warning('暂无可下载的设计文档内容')
    return
  }
  downloadMarkdownContent(content, filename)
}

const buildDocFilename = (ver?: Pick<DocVersion, 'filename' | 'version'> | null) => {
  const baseName = getDocDisplayFilename(ver) || lastParsedFilename.value || `${store.preview.appName || '功能设计文档'}`
  const normalized = baseName.endsWith('.md') ? baseName.slice(0, -3) : baseName
  const displayVersion = getDocDisplayVersion(ver)
  if (displayVersion && !/[-_ ]v\d+$/i.test(normalized)) {
    return `${normalized}-V${displayVersion}.md`
  }
  return baseName.endsWith('.md') ? baseName : `${baseName}.md`
}

const downloadMarkdownContent = (content: string, filename: string) => {
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

const downloadDocVersion = (ver: DocVersionListItem) => {
  const content = resolveDocDisplayContent(ver).trim()
  if (!content) {
    ElMessage.warning('暂无可下载的设计文档内容')
    return
  }
  downloadMarkdownContent(content, buildDocFilename(ver))
}

const stripHiddenAssistantBlocks = (input: string) => {
  let text = String(input || '')

  while (true) {
    const thinkStart = text.indexOf('<think>')
    if (thinkStart === -1) break
    const thinkEnd = text.indexOf('</think>', thinkStart + 7)
    if (thinkEnd === -1) {
      text = text.slice(0, thinkStart)
      break
    }
    text = `${text.slice(0, thinkStart)}${text.slice(thinkEnd + 8)}`
  }

  return text
}

const getRenderableContentText = (input: string) => {
  let text = stripHiddenAssistantBlocks(input)
  // 隐藏JSON代码块，只显示文字部分
  text = text.replace(/```json[\s\S]*?```/g, '')
  // 清理多余空行
  return text.replace(/\n{3,}/g, '\n\n').trim()
}

const normalizeLoadedAssistantContent = (input: string) => {
  const cleaned = getRenderableContentText(input)
  if (!cleaned) return ''
  if (cleaned.includes('<!-- TRIGGER_BUILD -->')) {
    return '需求已确认，完整设计文档已同步到右侧，正在准备开始构建。'
  }
  if (cleaned.includes('<!-- DESIGN_COMPLETE -->') || looksLikeGeneratedDesignDoc(cleaned)) {
    return '设计文档已生成，完整内容请查看右侧预览。'
  }
  return cleaned
}

// 把后端拼接的 user message 里的 `[上传文件：X]\n\n<full content>` 折叠成 chip：
// 只展示文件名 chip，不展示完整正文（LLM 后续对话仍能从 DB 原文读到内容）
const formatUserAttachmentBlocks = (text: string): string => {
  const markerRe = /\[上传(文件|截图)：([^\]]+?)\]/g
  const markers: { type: '文件' | '截图'; name: string; start: number }[] = []
  let m: RegExpExecArray | null
  while ((m = markerRe.exec(text)) !== null) {
    markers.push({ type: m[1] as '文件' | '截图', name: m[2], start: m.index })
  }
  if (markers.length === 0) return text
  const userText = text.slice(0, markers[0].start).replace(/\s+$/, '')
  const chipsHtml = markers.map(mk => {
    const icon = mk.type === '截图' ? '🖼️' : '📄'
    const cls = mk.type === '截图' ? 'msg-attachment-chip image' : 'msg-attachment-chip file'
    const safeName = escapeHtml(mk.name)
    return `<span class="${cls}" title="${safeName}"><span class="msg-attachment-icon" aria-hidden="true">${icon}</span><span class="msg-attachment-name">${safeName}</span></span>`
  }).join('')
  // 用 block 包裹 chip 列表，紧跟 userText 之后；不用换行符避免被外层 \n→<br> 拉开
  return userText + `<div class="msg-attachment-list">${chipsHtml}</div>`
}

const formatContent = (t: string) => {
  let text = getRenderableContentText(t)
  text = formatUserAttachmentBlocks(text)
  return text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>').replace(/• /g, '<span style="color:#818cf8;margin-right:4px">•</span> ')
}

// 处理消息附带的 action 按钮点击（DOC_NOT_STANDARD 错误的"返回 AI-Chat"等）
function handleMessageAction(action: { kind?: string; label?: string }) {
  if (!action) return
  if (action.kind === 'back-to-aichat') {
    router.push({ path: '/ai-chat' })
  }
}

// ── dolphin 需求分析助手 deeplink (?from=requirements) ─────────────────────
// 用户在 dolphin chat 里点 agent 给的 [→ Builder](deeplink) 链接进来，
// 立刻从 backend cache 拿 md（agent 已通过 submit_design_doc 工具 push 进去），
// 弹 ChooseAppTargetDialog 让用户选「新建应用」或「更新到现有应用」。
const reqDialogVisible = ref(false)
const reqDialogLoading = ref(false)
const reqDialogFilename = ref('')
const reqDialogSuggestedName = ref('')
const reqDialogCandidates = ref<Array<{ id: number; app_name: string; app_code: string; status: string; apaas_app_id?: string | null; updated_at?: string | null }>>([])
let reqPendingMd: { filename: string; content: string; pendingId: string | null } | null = null

function _extractAppNameFromMd(md: string): string {
  if (!md) return ''
  const m = md.match(/^\s*#\s+([^\n]+?)\s*$/m)
  if (m) return m[1].trim().slice(0, 60)
  return ''
}
function _fallbackNameFromFilename(filename: string): string {
  return (filename || '')
    .replace(/\.(md|markdown)$/i, '')
    .replace(/[-_\s]*(设计文档|需求文档|设计说明|需求说明|design|spec)$/i, '')
    .trim()
}

async function tryLoadFromRequirements() {
  try {
    const res = await request.get<unknown, {
      has_doc?: boolean
      pending_id?: string
      file_name?: string
      md_content?: string
      score?: number
    }>('/requirements/latest-doc')
    if (!res?.has_doc || !res.md_content) {
      ElMessage.warning('暂无可用的设计文档 — 请回到 dolphin 让需求分析助手重新生成一份')
      return
    }
    const filename = res.file_name || 'design-doc.md'
    const inferred = _extractAppNameFromMd(res.md_content) || _fallbackNameFromFilename(filename)
    reqPendingMd = { filename, content: res.md_content, pendingId: res.pending_id || null }
    reqDialogFilename.value = filename
    reqDialogSuggestedName.value = inferred
    reqDialogCandidates.value = []
    reqDialogVisible.value = true
    if (inferred) {
      reqDialogLoading.value = true
      try {
        reqDialogCandidates.value = await applicationApi.matchByName(inferred, 5)
      } catch { /* 列表为空也能用「新建」 */ }
      reqDialogLoading.value = false
    }
  } catch (e) {
    console.warn('[ChatPage] /requirements/latest-doc failed', e)
  }
}

async function handleRequirementsConfirm(payload: { mode: 'new' } | { mode: 'update'; appId: number; appName: string }) {
  if (!reqPendingMd) return
  const pending = reqPendingMd
  reqPendingMd = null
  // consume cache，避免下次进 ChatPage 又被同一份 md 触发弹窗
  if (pending.pendingId) {
    try { await request.post(`/requirements/consume-doc/${pending.pendingId}`) } catch { /* 不阻塞主流程 */ }
  }
  const file = new File([pending.content], pending.filename, { type: 'text/markdown' })
  if (payload.mode === 'new') {
    resetConversationWorkspace()
    resetMessagesToWelcome()
    await nextTick()
    await uploadDocFile(file)
  } else {
    existingAppId.value = payload.appId
    await nextTick()
    try {
      await handleDocVersionUpload(file, payload.appId, {
        userMessageContent: `📄 从需求分析助手更新设计文档：${pending.filename}`,
        title: `更新设计文档：${pending.filename}`,
      })
    } catch (e) {
      console.error('[ChatPage] handleDocVersionUpload from requirements deeplink failed', e)
    }
  }
}

onMounted(async () => {
  store.showConnectModal = false
  // 同步当前应用到 backend（让 dolphin agent 通过 user_id 拿到 current app_id）
  void syncCurrentAppToBackend()
  // dolphin 改 SPEC 后右侧自动刷新 — 启动 5s 轮询
  startAppPolling()
  // 立刻拉一次基线 —— 不依赖第一次 5s tick 后才建立 baseline。
  // 若 agent 在 mount 后、第一次 tick 前改了 SPEC，原来"首次 tick 建基线"逻辑
  // 会把改过的 updated_at 当成 baseline，永远检测不到这次变化。
  void primeAppPollingBaseline()
  const initialPrompt = typeof route.query.prompt === 'string' ? route.query.prompt : ''
  // 加载左侧 sidebar 应用列表（不阻塞主流程）
  if (!embedMode.value) loadSidebarApps()

  // ── 防状态残留：从其他页面（Landing 等）进来时，如果路由里既没 app_id
  // 也没 conversation id，说明是"全新对话"场景，必须先清掉上一次挂在 store
  // 里的 preview / currentApp —— 否则右侧会显示上一个应用的脏数据。
  // pendingFile / pendingMarkdown 是上传流程在 Landing 页临时 set 的，要留。
  const hasAppId = !!route.query.app_id
  const hasConvId = !!route.params.id
  if (!hasAppId && !hasConvId && !store.pendingFile && !store.pendingMarkdown) {
    store.reset()
    specStore.reset()
    existingAppId.value = null
    parseReady.value = false
    parsedAppCode.value = ''
    loadedAppCode.value = ''
    conversationId.value = null
    currentAgent.value = 'requirements'
  }

  // 2026-05-18: 把 pendingMarkdown / pendingFile 处理提前到 onMounted 最早 —
  // 文档上传不应该等 /apaas/status 和 loadBuilderModelOptions 拖慢，否则用户从
  // AI-Chat → Builder 跳过来后看见空白页面以为坏了。pendingDocUpdate 依赖
  // existingAppId（在下方 app_id 分支里 set），所以留在原位。
  // ⚠️ 必须 await uploadDocFile — fire-and-forget 会跟后续代码（fetchConversationList
  // 等）race condition：uploadDocFile 内部异步创建 conversation + auto-create app，
  // 后续 fetchSidebarApps 等可能在 conversation 还没 set conversationId 前就跑完，
  // 导致 conv=None spec=None 的应用残留（5/18 实测最近 app 77, 76 都 conv=None）。
  if (store.pendingMarkdown) {
    const pending = store.pendingMarkdown
    store.pendingMarkdown = null
    pendingMdSource.value = {
      sessionId: pending.sourceSessionId ?? null,
      filename: pending.filename,
    }
    resetConversationWorkspace()
    resetMessagesToWelcome()
    const file = new File([pending.content], pending.filename, { type: 'text/markdown' })
    await nextTick()
    await uploadDocFile(file)
  } else if (store.pendingFile) {
    const file = store.pendingFile
    store.pendingFile = null
    resetConversationWorkspace()
    resetMessagesToWelcome()
    await nextTick()
    await uploadDocFile(file)
  }

  // 检查平台连接状态
  try {
    const token = localStorage.getItem('token')
    if (token) {
      const data = await request.get<any, any>('/apaas/status')
      if (data) {
        store.connected = data.connected
      }
    }
  } catch (e) { /* ignore */ }

  await loadBuilderModelOptions()
  if (store.pendingBuilderModelId != null) {
    applyBuilderModelSelection(store.pendingBuilderModelId)
    store.pendingBuilderModelId = null
  }

  // ── 优先通过 app_id 加载应用（应用为锚点）──
  const appIdParam = route.query.app_id as string
  if (appIdParam) {
    const aid = Number(appIdParam)
    if (aid) {
      existingAppId.value = aid
      parsedAppCode.value = ''
      loadedAppCode.value = ''
      try {
        const app = await applicationApi.get(aid) as any
        platformDirectUrl.value = app.apaas_url || ''
        // 恢复配置
        let configData: any = null
        if (app.config_preview) {
          const data = app.config_preview.data || app.config_preview
          configData = data
          store.setAppName(data.appName || app.app_name)
          store.preview.models = data.models || []
          store.preview.forms = data.forms || []
          store.preview.dicts = data.dicts || []
          store.preview.roles = data.roles || []
          store.preview.workflows = data.workflows || []
          store.preview.permissions = data.permissions || []
          setPreviewCustomDevelopment(data)
          store.currentApp = { status: app.status || 'ready', apaas_app_id: app.apaas_app_id }
          platformDirectUrl.value = app.apaas_url || ''
          parseReady.value = store.preview.models.length > 0 || store.preview.forms.length > 0
          currentAgent.value = 'builder'
        }
        loadedAppCode.value = app.app_code || pickAppCode(configData) || ''
        parsedAppCode.value = loadedAppCode.value
        deployAppId.value = aid
        await loadDeployStatus()
        await refreshCurrentAppRemoteMeta(aid)
        await restoreActiveViewForApp(app)
        const docVersionPayload = await loadLatestDocForApp(aid)
        await restorePendingChangePlan(aid, docVersionPayload)
        console.log(`Loaded app ${aid}: ${app.app_name}, status=${app.status}, conv=${app.conversation_id}`)
        // 加载关联对话的历史消息
        if (app.conversation_id) {
          conversationId.value = app.conversation_id
          selectedConversationId.value = app.conversation_id
          await syncBuilderModelFromConversation(app.conversation_id, { syncAgent: false, syncSpec: false })
          if (!appParsedMode.value) {
            const historyMessages = await conversationApi.getMessages(app.conversation_id)
            if (historyMessages?.length) {
              messages.splice(0, messages.length)
              for (const msg of historyMessages) {
                if (msg.role === 'system') continue
                if (msg.role === 'assistant' && isAutoDocSummaryMessage(msg.content)) continue
                const normalizedContent = msg.role === 'assistant'
                  ? normalizeLoadedAssistantContent(msg.content)
                  : msg.content
                messages.push({ id: msg.id, role: msg.role as any, agent: msg.role === 'assistant' ? 'builder' : undefined, content: normalizedContent, created_at: msg.created_at })
              }
              scrollToBottom()
            }
          }
        }
        enterGeneratedApplicationWorkspace(app)
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
              if (msg.role === 'assistant' && isAutoDocSummaryMessage(msg.content)) {
                continue
              }
              const normalizedContent = msg.role === 'assistant'
                ? normalizeLoadedAssistantContent(msg.content)
                : msg.content
              messages.push({
                id: msg.id,
                role: msg.role as any,
                agent: msg.role === 'assistant' ? 'builder' : undefined,
                content: normalizedContent,
                created_at: msg.created_at
              })
              if (msg.role === 'assistant') {
                extractPreviewData(normalizedContent)
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
                store.setAppName(data.appName)
                store.preview.models = data.models || []
                store.preview.forms = data.forms || []
                store.preview.dicts = data.dicts || []
                store.preview.roles = data.roles || []
                store.preview.workflows = data.workflows || []
                store.preview.permissions = data.permissions || []
                setPreviewCustomDevelopment(data)
                store.currentApp = { status: 'draft', apaas_app_id: linkedApp.apaas_app_id }
                parseReady.value = store.preview.models.length > 0 || store.preview.forms.length > 0
                existingAppId.value = linkedApp.id
                loadedAppCode.value = linkedApp.app_code || ''
                parsedAppCode.value = loadedAppCode.value
                deployAppId.value = linkedApp.id
                await loadDeployStatus()
                await refreshCurrentAppRemoteMeta(linkedApp.id)
                const docVersionPayload = await loadLatestDocForApp(linkedApp.id)
                await restorePendingChangePlan(linkedApp.id, docVersionPayload)
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
      parsedAppCode.value = ''
      loadedAppCode.value = ''
      deployOpen.value = true
      loadDeployStatus()
      // 加载应用信息到预览
      try {
        const app = await applicationApi.get(aid) as any
        platformDirectUrl.value = app.apaas_url || ''
        let configData: any = null
        if (app.config_preview) {
          const data = app.config_preview.data || app.config_preview
          configData = data
          store.setAppName(data.appName || app.app_name)
          store.preview.models = data.models || []
          store.preview.forms = data.forms || []
          store.preview.dicts = data.dicts || []
          store.preview.roles = data.roles || []
          store.currentApp = { status: app.status || 'ready', apaas_app_id: app.apaas_app_id }
          parseReady.value = store.preview.models.length > 0 || store.preview.forms.length > 0
          currentAgent.value = 'builder'
        }
        loadedAppCode.value = app.app_code || pickAppCode(configData) || ''
        parsedAppCode.value = loadedAppCode.value
        deployAppId.value = aid
        await loadDeployStatus()
        await refreshCurrentAppRemoteMeta(aid)
        await restoreActiveViewForApp(app)
        const docVersionPayload = await loadLatestDocForApp(aid)
        await restorePendingChangePlan(aid, docVersionPayload)
        // 加载关联的对话
        if (app.conversation_id) {
          conversationId.value = app.conversation_id
          await syncBuilderModelFromConversation(app.conversation_id, { syncAgent: false, syncSpec: false })
          if (!appParsedMode.value) {
            const historyMessages = await conversationApi.getMessages(app.conversation_id)
            if (historyMessages?.length) {
              messages.splice(0, messages.length)
              for (const msg of historyMessages) {
                if (msg.role === 'system') continue
                if (msg.role === 'assistant' && isAutoDocSummaryMessage(msg.content)) continue
                const normalizedContent = msg.role === 'assistant'
                  ? normalizeLoadedAssistantContent(msg.content)
                  : msg.content
                messages.push({ id: msg.id, role: msg.role as any, agent: msg.role === 'assistant' ? 'builder' : undefined, content: normalizedContent, created_at: msg.created_at })
              }
            }
          }
        }
      } catch { /* ignore */ }
    }
  }

  if (initialPrompt && !appParsedMode.value && !store.pendingMarkdown && !store.pendingFile) {
    inputText.value = initialPrompt
    await nextTick()
    await sendMessage()
  }

  // pendingMarkdown / pendingFile 处理已提前到 onMounted 最早（见上方）。
  // 这里只留 pendingDocUpdate（依赖 existingAppId 已 set 才能走）。

  // 从 AIChat → Builder 选目标对话框选了「更新到 X」的：直接走 upload-doc-version 流程
  // existingAppId 在前面 app_id 加载分支里已 set，这里 sanity check 一下保持一致
  if (store.pendingDocUpdate && existingAppId.value === store.pendingDocUpdate.appId) {
    const pending = store.pendingDocUpdate
    store.pendingDocUpdate = null
    const file = new File([pending.content], pending.filename, { type: 'text/markdown' })
    await nextTick()
    try {
      await handleDocVersionUpload(file, pending.appId, {
        userMessageContent: `📄 从 AI-Chat 更新设计文档：${pending.filename}`,
        title: `更新设计文档：${pending.filename}`,
      })
    } catch (e) {
      console.error('upload-doc-version from aichat failed', e)
    }
  } else if (store.pendingDocUpdate) {
    // app_id 与 pending 不一致（理论不该发生）— 清掉避免下次再误触发
    store.pendingDocUpdate = null
  }

  // pendingFile 处理已提前到 onMounted 最早（见上方）。

  // 从 dolphin 需求分析助手 deeplink 进来 (?from=requirements)：拉 cache 弹选目标对话框
  if (route.query.from === 'requirements') {
    await tryLoadFromRequirements()
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
  store.preview.forms = []
  store.preview.dicts = []
  store.preview.roles = []
  store.preview.workflows = []
  ;(store.preview as any).flows = []
  store.preview.permissions = []
  ;(store.preview as any).custom_development = []
  store.setAppName('', { force: true })
  store.currentApp = null
  parsedAppCode.value = ''
  loadedAppCode.value = ''
  latestDocContent.value = ''
  latestDocAppId.value = null
  latestDocConversationId.value = null
  conversationId.value = null
  activeView.value = 'builder'
  platformIframeUrl.value = ''
  platformIframeKey.value = 0
  platformAppUrl.value = ''
  platformDirectUrl.value = ''
  platformIframeAppId.value = null
  platformLoading.value = false
  platformError.value = ''
  platformLoginHint.value = ''
  deployOpen.value = false

  try {
    clearChangePlanState()
    const app = await applicationApi.get(aid) as any
    let configData: any = null
    if (app.config_preview) {
      const data = app.config_preview.data || app.config_preview
      configData = data
      store.setAppName(data.appName || app.app_name)
      store.preview.models = data.models || []
      store.preview.forms = data.forms || []
      store.preview.dicts = data.dicts || []
      store.preview.roles = data.roles || []
      store.preview.workflows = data.workflows || []
      store.preview.permissions = data.permissions || []
      setPreviewCustomDevelopment(data)
      store.currentApp = { status: app.status || 'ready', apaas_app_id: app.apaas_app_id }
      platformDirectUrl.value = app.apaas_url || ''
      parseReady.value = store.preview.models.length > 0 || store.preview.forms.length > 0
      currentAgent.value = 'builder'
    }
    loadedAppCode.value = app.app_code || pickAppCode(configData) || ''
    parsedAppCode.value = loadedAppCode.value
    await restoreActiveViewForApp(app)
    const docVersionPayload = await loadLatestDocForApp(aid)
    await restorePendingChangePlan(aid, docVersionPayload)
    if (app.conversation_id) {
      conversationId.value = app.conversation_id
      selectedConversationId.value = app.conversation_id
      await syncBuilderModelFromConversation(app.conversation_id, { syncAgent: false, syncSpec: false })
      if (!appParsedMode.value) {
        const historyMessages = await conversationApi.getMessages(app.conversation_id)
        if (historyMessages?.length) {
          for (const msg of historyMessages) {
            if (msg.role === 'system') continue
            if (msg.role === 'assistant' && isAutoDocSummaryMessage(msg.content)) continue
            messages.push({ id: msg.id, role: msg.role as any, agent: msg.role === 'assistant' ? 'builder' : undefined, content: msg.content, created_at: msg.created_at })
          }
          scrollToBottom()
        }
      }
    }
    enterGeneratedApplicationWorkspace(app)
  } catch (e) {
    console.error('Failed to switch app:', e)
  }
})

watch(() => route.params.id, (newConversationId, oldConversationId) => {
  if (!newConversationId || newConversationId === oldConversationId) return
  if (route.query.app_id) return
  parsedAppCode.value = ''
  loadedAppCode.value = ''
  latestDocContent.value = ''
  latestDocAppId.value = null
  latestDocConversationId.value = null
})

watch(() => route.query.view, (nextView) => {
  const requestedView = Array.isArray(nextView) ? nextView[0] : nextView
  if (requestedView === 'builder' && activeView.value !== 'builder') {
    activeView.value = 'builder'
  }
})

onBeforeUnmount(() => {
  clearPendingChatAttachments()
  clearPlatformIframeRepairTimer()
  stopAppPolling()
})

watch(activeView, (view) => {
  persistAppActiveView(view)
})

watch(isUpdateReviewMode, (enabled) => {
  if (!enabled) return
  deployOpen.value = true
  // 原先这里会根据 isUpdateReviewMode 切换到合适的 tab，但 tab 机制已废弃，
  // 右侧永远走文档对比视图，保留 watch 仅为打开右侧部署面板。
}, { immediate: true })

watch(displayDocVersions, (versions) => {
  if (versions.length < 2) {
    docVersionHistoryOpen.value = false
  }
  if (expandedDocVersionKey.value && !versions.some(ver => ver.key === expandedDocVersionKey.value)) {
    expandedDocVersionKey.value = null
  }
  if (selectedDocVersionKey.value && !versions.some(ver => ver.key === selectedDocVersionKey.value)) {
    selectedDocVersionKey.value = versions[0]?.key || null
  }
}, { immediate: true })

watch(existingAppId, (id) => {
  if (id) {
    fetchDocVersions()
  }
})
watch(conversationId, (id) => {
  if (isDocParsing.value) {
    if (id && docVersions.value.length === 0) {
      fetchDocVersions()
    }
    return
  }
  if (route.query.app_id || existingAppId.value) {
    if (id && docVersions.value.length === 0) {
      fetchDocVersions()
    }
    return
  }
  store.reset()
  existingAppId.value = null
  docVersions.value = []
  currentDocPreviewOverride.value = null
  if (id) {
    fetchDocVersions()
  }
})
</script>

<style scoped>
/* v2 redesign (Session 5): 3-column shell wrapper that holds
   ChatConversationList + <main class="chat-main"> (existing chat-page-shell)
   + AppBlueprintPanel. Existing layout inside .chat-page-shell unchanged. */
.chat-shell { display: flex; height: 100%; min-height: 0; background: var(--bg-app); }
.chat-main { flex: 1; min-width: 0; min-height: 0; height: 100%; display: flex; flex-direction: column; overflow: hidden; }
/* ══════════════════════════════════════════════
   Theme — uses CSS custom properties (var(--t-*))
   for light/dark theme support.
   See theme definition for variable values.
   ══════════════════════════════════════════════ */

.chat-page-shell { flex: 1; height: 100%; display: flex; flex-direction: row; min-width: 0; min-height: 0; }
.chat-page { flex: 1; min-width: 0; height: 100%; display: flex; flex-direction: column; background: var(--t-bg-base); color: var(--t-text-primary); }

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
.top-bar-center {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.top-bar-app-name {
  display: inline-flex;
  align-items: center;
  height: 28px;
  padding: 0 10px;
  border-radius: 999px;
  background: rgba(247, 249, 255, 0.94);
  border: 1px solid rgba(128, 145, 255, 0.14);
  font-size: 12px;
  font-weight: 600;
  color: var(--t-text-secondary);
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mode-switcher {
  display: flex;
  gap: 3px;
  padding: 3px;
  background: rgba(245, 247, 255, 0.92);
  border: 1px solid rgba(128, 145, 255, 0.14);
  border-radius: 12px;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.65);
}
.mode-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 30px;
  padding: 0 11px;
  border-radius: 9px;
  font-size: 11px;
  font-weight: 600;
  background: transparent;
  border: none;
  color: var(--t-text-muted);
  cursor: pointer;
  transition: all 0.2s ease;
}
.mode-btn:hover { color: var(--t-text-primary); background: rgba(93, 114, 255, 0.06); }
.mode-btn-link {
  text-decoration: none;
  margin-left: 6px;
  border: 1px solid rgba(124, 58, 237, 0.28);
  color: #6d28d9;
}
.mode-btn-link:hover {
  background: rgba(124, 58, 237, 0.08);
  color: #5b21b6;
  border-color: rgba(124, 58, 237, 0.5);
}
html[data-theme="dark"] .mode-btn-link {
  color: #c4b5fd;
  border-color: rgba(167, 139, 250, 0.4);
}
html[data-theme="dark"] .mode-btn-link:hover {
  background: rgba(167, 139, 250, 0.14);
  color: #ddd6fe;
}
.mode-btn.active {
  background: linear-gradient(135deg, rgba(255,255,255,0.98), rgba(242, 246, 255, 0.94));
  color: var(--t-brand-text);
  box-shadow: 0 8px 14px rgba(92, 115, 255, 0.08);
}
.mode-btn-icon {
  width: 14px;
  height: 14px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: currentColor;
  opacity: 0.72;
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.mode-btn-icon svg {
  width: 14px;
  height: 14px;
}
.mode-btn.active .mode-btn-icon { opacity: 1; transform: scale(1.04); }
.top-status-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 32px;
  padding: 0 12px;
  border-radius: 999px;
  border: 1px solid rgba(128, 145, 255, 0.14);
  background: rgba(248, 250, 255, 0.92);
  color: #60708d;
  font-size: 12px;
  font-weight: 700;
}
.top-status-badge.inline {
  margin-left: 12px;
}
.top-status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
}
.top-status-badge.draft {
  color: #94a3b8;
  background: rgba(248, 250, 252, 0.96);
}
.top-status-badge.generated {
  color: #4f78ff;
  background: rgba(239, 244, 255, 0.96);
}
.top-status-badge.deployed {
  color: #10b981;
  background: rgba(236, 253, 245, 0.98);
}
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
.main-area {
  flex: 1;
  display: flex;
  flex-direction: row;
  overflow: hidden;
  position: relative;
  background:
    radial-gradient(circle at top left, rgba(114, 135, 255, 0.08), transparent 26%),
    linear-gradient(180deg, #f6f8ff 0%, #f9fbff 100%);
}
.content-area { flex: 1; display: flex; flex-direction: column; overflow: hidden; min-width: 0; }

/* ── 智能搭建内容区（横向布局） ── */
.builder-content {
  flex: 1;
  display: flex;
  overflow: hidden;
  min-height: 0;
  margin: 12px;
  border-radius: 28px;
  border: 1px solid rgba(128, 145, 255, 0.12);
  background: linear-gradient(180deg, rgba(255,255,255,0.8), rgba(245, 248, 255, 0.86));
  box-shadow: 0 20px 50px rgba(31, 41, 85, 0.06), inset 0 1px 0 rgba(255,255,255,0.75);
}

.dolphin-loading-pane {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: #8a9099;
  font-size: 14px;
  background: var(--b-bg, #fff);
}

.dolphin-loading-pane .loading-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #7c3aed;
  animation: pulse-dot 1s ease-in-out infinite;
}

@keyframes pulse-dot {
  0%, 100% { opacity: 0.3; transform: scale(0.8); }
  50% { opacity: 1; transform: scale(1.1); }
}

/* ── SPEC three-pane (Phase β) ── */
.spec-phasebar-strip {
  padding: 12px 16px;
  border-bottom: 1px solid var(--t-border-subtle);
  background: var(--t-bg-panel);
}
.spec-canvas-pane {
  flex: 1;
  display: flex;
  overflow: hidden;
}
.spec-inspector-pane {
  flex-shrink: 0;
}
@media (max-width: 1280px) {
  .spec-inspector-pane { display: none; }
}
.builder-content.single-pane .preview-side {
  flex: 1;
  max-width: none;
  width: auto;
}

/* ── 左侧对话 ── */
.chat-side {
  flex: 1.08;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-width: 320px;
  background: linear-gradient(180deg, rgba(242, 246, 255, 0.55), rgba(239, 244, 255, 0.68));
}

.builder-workbench {
  padding: 0 14px 8px;
  display: flex;
  flex-direction: column;
  gap: 0;
  background: transparent;
}
.builder-composer-shell {
  display: flex;
  flex-direction: column;
  gap: 0;
  padding: 6px;
  border-radius: 16px;
  background: linear-gradient(180deg, rgba(248, 249, 255, 0.94), rgba(240, 244, 255, 0.9));
  border: 1px solid rgba(128, 145, 255, 0.12);
  box-shadow: 0 12px 26px rgba(31, 41, 85, 0.05);
}
.builder-inline-model-select {
  width: min(240px, 100%);
}
.builder-inline-model-select.in-card {
  width: min(176px, 100%);
}
.builder-inline-model-select :deep(.el-select__wrapper) {
  min-height: 28px;
  border-radius: 7px;
  background: rgba(255, 255, 255, 0.92);
  box-shadow: inset 0 0 0 1px rgba(128, 145, 255, 0.16);
}
.builder-inline-model-select :deep(.el-select__selected-item),
.builder-inline-model-select :deep(.el-select__placeholder) {
  font-size: 12px;
}
.builder-inline-model-select :deep(.el-select__wrapper.is-focused) {
  box-shadow: inset 0 0 0 1px var(--t-brand), 0 0 0 4px rgba(110, 131, 255, 0.12);
}
.builder-control-hint {
  font-size: 11px;
  line-height: 1.5;
  color: var(--t-text-muted);
}
.builder-control-hint.inside-card {
  padding: 0 6px 2px;
  font-size: 10px;
  line-height: 1.35;
}
.builder-generate-btn {
  height: 36px;
  min-width: 96px;
  padding: 0 16px;
  border: none;
  border-radius: 10px;
  background: var(--t-brand-gradient);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  box-shadow: 0 10px 20px rgba(92, 115, 255, 0.18);
  transition: transform 0.2s ease, box-shadow 0.2s ease, opacity 0.2s ease;
}
.builder-generate-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 16px 30px rgba(92, 115, 255, 0.28);
}
.builder-generate-btn.compact {
  height: 28px;
  min-width: 68px;
  padding: 0 9px;
  border-radius: 9px;
  font-size: 10px;
  align-self: flex-end;
  margin-top: 4px;
}
.builder-generate-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
  box-shadow: none;
}
.quick-edit-bar {
  padding: 0;
  justify-content: stretch;
}
.quick-edit-card {
  position: relative;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.88);
  border-color: rgba(128, 145, 255, 0.14);
  box-shadow: 0 8px 18px rgba(31, 41, 85, 0.04);
}
.quick-edit-glow {
  position: absolute;
  inset: 0 auto auto 0;
  width: 120px;
  height: 52px;
  background: radial-gradient(circle, rgba(104, 127, 255, 0.18), rgba(104, 127, 255, 0));
  pointer-events: none;
  animation: aiPulse 3.2s ease-in-out infinite;
}
.composer-toolbar {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 6px;
  padding: 2px 6px 1px;
}
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
.doc-view-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}
.doc-download-btn {
  border: 1px solid var(--t-border-subtle);
  background: var(--t-bg-panel);
  color: var(--t-text-secondary);
  border-radius: 7px;
  height: 24px;
  padding: 0 8px;
  font-size: 11px;
  cursor: pointer;
}
.doc-download-btn:hover {
  border-color: var(--t-border-strong);
  color: var(--t-text-primary);
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

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 18px 22px 14px;
  background: transparent;
}
.chat-bubble { margin-bottom: 14px; animation: fadeUp 0.3s ease-out; }
.chat-bubble.user { display: flex; justify-content: flex-end; }
.chat-bubble.assistant { display: flex; justify-content: flex-start; }
.bubble-row { display: flex; align-items: flex-start; gap: 10px; }
.bubble-row.user { justify-content: flex-end; width: 100%; }
.bubble-row.assistant { width: 100%; }
.bubble-inner { max-width: 80%; }
.bubble-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
  padding: 0 4px;
}
.bubble-action-btn {
  appearance: none;
  border: 1px solid color-mix(in srgb, var(--t-brand, #5a78ff) 30%, transparent);
  background: color-mix(in srgb, var(--t-brand, #5a78ff) 10%, transparent);
  color: var(--t-brand, #5a78ff);
  font-size: 13px;
  font-weight: 500;
  padding: 6px 14px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s, transform 0.05s;
}
.bubble-action-btn:hover {
  background: color-mix(in srgb, var(--t-brand, #5a78ff) 20%, transparent);
  border-color: color-mix(in srgb, var(--t-brand, #5a78ff) 50%, transparent);
}
.bubble-action-btn:active { transform: translateY(1px); }
.bubble-action-btn.primary {
  background: var(--t-brand, #5a78ff);
  color: #fff;
  border-color: transparent;
}
.bubble-action-btn.primary:hover {
  background: color-mix(in srgb, var(--t-brand, #5a78ff) 88%, black);
}
.chat-bubble.assistant .bubble-inner {
  max-width: min(720px, calc(100% - 36px));
}
.bubble-inner.welcome-bubble {
  max-width: min(920px, 96%);
}
.assistant-avatar {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #6c82ff, #4d68ff);
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  box-shadow: 0 6px 16px rgba(92, 115, 255, 0.18);
  animation: avatarBlink 2.8s ease-in-out infinite;
}
.agent-label { display: flex; align-items: center; gap: 4px; font-size: 11px; color: var(--t-text-muted); margin-bottom: 4px; }
.bubble-content { padding: 12px 16px; border-radius: 14px; font-size: 13px; line-height: 1.65; }
.bubble-content.user {
  background: var(--t-brand-gradient);
  color: #fff; border-bottom-right-radius: 4px;
}
.bubble-content.assistant {
  background: var(--t-bg-panel); border: 1px solid var(--t-border-subtle);
  color: var(--t-text-primary); border-bottom-left-radius: 4px;
  box-shadow: var(--t-shadow-sm);
}
.chat-bubble.streaming-message .assistant-avatar {
  animation: avatarBlink 1.4s ease-in-out infinite;
}
.chat-bubble.streaming-message .bubble-content.assistant {
  position: relative;
  border-color: rgba(91, 111, 255, 0.28);
  background:
    linear-gradient(90deg, rgba(91, 111, 255, 0.08), rgba(20, 184, 166, 0.06)),
    var(--t-bg-panel);
}
.chat-bubble.streaming-message .bubble-content.assistant::after {
  content: '';
  display: inline-block;
  width: 1.2em;
  height: 1em;
  margin-left: 4px;
  vertical-align: -0.1em;
  background: radial-gradient(circle, currentColor 45%, transparent 48%) 0.05em 0.58em / 0.34em 0.34em no-repeat,
    radial-gradient(circle, currentColor 45%, transparent 48%) 0.43em 0.58em / 0.34em 0.34em no-repeat,
    radial-gradient(circle, currentColor 45%, transparent 48%) 0.81em 0.58em / 0.34em 0.34em no-repeat;
  opacity: 0.72;
  animation: streamDots 1.2s steps(3, end) infinite;
}
.chat-inline-upload {
  margin-top: 8px;
  padding: 10px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.14);
  border: 1px solid rgba(255, 255, 255, 0.18);
  max-width: min(320px, 100%);
}
.chat-inline-upload.file {
  padding: 12px;
}
.bubble-content.assistant .chat-inline-upload {
  background: rgba(99, 102, 241, 0.08);
  border-color: rgba(129, 140, 248, 0.16);
}
.chat-inline-upload-head {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  margin-bottom: 8px;
}
.chat-inline-upload-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  background: rgba(255, 255, 255, 0.18);
  color: inherit;
  flex-shrink: 0;
}
.bubble-content.assistant .chat-inline-upload-badge {
  background: rgba(99, 102, 241, 0.12);
  color: var(--t-brand-light);
}
.chat-inline-upload-name {
  min-width: 0;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.chat-inline-upload-image {
  display: block;
  width: 100%;
  max-width: min(300px, 100%);
  max-height: 240px;
  border-radius: 12px;
  object-fit: cover;
  border: 1px solid rgba(255, 255, 255, 0.16);
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.14);
}
.bubble-content.assistant .chat-inline-upload-image {
  border-color: rgba(129, 140, 248, 0.14);
}
.chat-inline-upload-foot {
  margin-top: 8px;
  font-size: 11px;
  line-height: 1.5;
  opacity: 0.82;
}
.chat-inline-upload-file-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.08);
}
.bubble-content.assistant .chat-inline-upload-file-row {
  background: rgba(99, 102, 241, 0.06);
}
.chat-inline-upload-file-icon {
  font-size: 18px;
  line-height: 1;
}
.chat-inline-upload-file-tip {
  min-width: 0;
  font-size: 12px;
  opacity: 0.88;
}
@keyframes fadeUp { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
@keyframes aiPulse {
  0%, 100% { opacity: 0.55; transform: scale(1); }
  50% { opacity: 1; transform: scale(1.04); }
}
@keyframes avatarBlink {
  0%, 100% { box-shadow: 0 6px 16px rgba(92, 115, 255, 0.18); filter: brightness(1); }
  50% { box-shadow: 0 8px 22px rgba(92, 115, 255, 0.32); filter: brightness(1.12); }
}
@keyframes streamDots {
  0% { clip-path: inset(0 0.82em 0 0); }
  33% { clip-path: inset(0 0.42em 0 0); }
  66%, 100% { clip-path: inset(0 0 0 0); }
}

.typing-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--t-text-muted); display: inline-block; animation: pulseDot 1.4s infinite ease-in-out both; margin-right: 3px; }
.typing-dot:nth-child(1) { animation-delay: -0.32s; }
.typing-dot:nth-child(2) { animation-delay: -0.16s; }
@keyframes pulseDot { 0%,80%,100% { transform: scale(0); } 40% { transform: scale(1); } }

/* 底部输入框 */
/* ── Input bar (Claude-style card) ── */
.input-bar {
  padding: 0;
  background: transparent;
  flex-shrink: 0;
  display: flex;
  justify-content: center;
}
.input-card {
  width: 100%;
  background: rgba(255, 255, 255, 0.94);
  border: 1px solid rgba(128, 145, 255, 0.14);
  border-radius: 9px;
  overflow: hidden;
  box-shadow: 0 8px 18px rgba(31, 41, 85, 0.04);
  transition: border-color 0.2s, box-shadow 0.2s;
}
.input-card:focus-within {
  border-color: var(--t-brand);
  box-shadow: 0 0 0 4px rgba(110, 131, 255, 0.12), 0 16px 36px rgba(31, 41, 85, 0.08);
}
.input-card-top {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
}
.upload-btn {
  cursor: pointer;
  color: var(--t-text-muted);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 4px;
  border-radius: 6px;
  border: none;
  background: transparent;
  transition: color 0.15s, background-color 0.15s;
  flex-shrink: 0;
}
.upload-btn:hover { color: var(--t-text-primary); background: rgba(129, 140, 248, 0.08); }
.upload-btn.screenshot { margin-left: 2px; }
.input-card-top textarea {
  flex: 1;
  border: none;
  background: transparent;
  resize: none;
  outline: none;
  font-size: 13px;
  line-height: 1.5;
  color: var(--t-text-primary);
  min-height: 38px;
  max-height: 200px;
  overflow-y: auto;
  padding: 7px 0;
  font-family: inherit;
}
.input-card-top textarea::placeholder { color: var(--t-text-muted); }
.send-btn {
  width: 30px; height: 30px; border-radius: 9px;
  background: var(--t-brand-gradient);
  color: #fff;
  border: none; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 6px 14px rgba(92, 115, 255, 0.16);
  transition: transform 0.15s, box-shadow 0.15s, opacity 0.15s;
}
.send-btn.disabled { opacity: 0.2; cursor: not-allowed; }
.send-btn:hover:not(.disabled) { opacity: 0.92; transform: translateY(-1px); box-shadow: 0 14px 24px rgba(92, 115, 255, 0.28); }
/* 中断按钮：sendingMessage=true 时替代发送按钮，红色，让用户感觉"按下就停" */
.send-btn.stop-btn {
  background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
  box-shadow: 0 6px 14px rgba(239, 68, 68, 0.22);
}
.send-btn.stop-btn:hover { box-shadow: 0 14px 24px rgba(239, 68, 68, 0.32); transform: translateY(-1px); }
/* AI 工作中状态：dots + 倒计时 */
.typing-with-meta {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
}
.typing-meta {
  font-size: 12px;
  color: var(--t-text-muted);
  letter-spacing: 0.2px;
}
.chat-attachment-preview-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 2px 8px 8px;
}

/* 历史消息里附件展示成 Claude 风格紧凑 pill — 文件名 + 图标，不展示正文 */
.msg-attachment-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 6px;
}
.msg-attachment-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 5px 10px 5px 8px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.14);
  font-size: 12.5px;
  line-height: 1.3;
  width: fit-content;
  max-width: 100%;
  color: inherit;
}
.msg-attachment-chip .msg-attachment-icon {
  font-size: 14px;
  line-height: 1;
  opacity: 0.85;
}
.msg-attachment-chip .msg-attachment-name {
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 280px;
}
html[data-theme="light"] .msg-attachment-chip {
  background: rgba(15, 23, 42, 0.05);
  border-color: rgba(15, 23, 42, 0.1);
}
.chat-attachment-preview {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 12px;
  background: rgba(99, 102, 241, 0.08);
  border: 1px solid rgba(129, 140, 248, 0.18);
}
.chat-attachment-preview-image {
  width: 48px;
  height: 48px;
  border-radius: 10px;
  object-fit: cover;
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.12);
  flex-shrink: 0;
}
.chat-attachment-preview-file {
  width: 48px;
  height: 48px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  background: rgba(99, 102, 241, 0.12);
  border: 1px solid rgba(129, 140, 248, 0.18);
  flex-shrink: 0;
}
.chat-attachment-preview-meta {
  min-width: 0;
  flex: 1;
}
.chat-attachment-preview-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--t-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chat-attachment-preview-tip {
  margin-top: 2px;
  font-size: 11px;
  color: var(--t-text-muted);
}
.chat-attachment-remove {
  width: 24px;
  height: 24px;
  border-radius: 999px;
  border: none;
  background: rgba(148, 163, 184, 0.16);
  color: var(--t-text-muted);
  cursor: pointer;
  flex-shrink: 0;
}
.chat-attachment-remove:hover {
  background: rgba(239, 68, 68, 0.14);
  color: #ef4444;
}
.input-card-bottom {
  display: flex;
  align-items: center;
  padding: 4px 12px 8px;
  border-top: 1px solid var(--t-border-subtle);
}
.kbd-hint {
  font-size: 11px;
  color: var(--t-text-muted);
  opacity: 0.6;
  white-space: nowrap;
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
  .mode-switcher {
    width: 100%;
    justify-content: flex-start;
    overflow-x: auto;
  }
  .builder-composer-shell {
    padding: 12px;
    border-radius: 18px;
  }
  .builder-content {
    margin: 8px;
    border-radius: 22px;
    flex-direction: column;
  }
  .chat-side,
  .preview-side {
    flex: none;
  }
  .preview-side::before {
    display: none;
  }
  .builder-inline-model-select {
    width: 100%;
  }
  .composer-toolbar {
    flex-direction: column;
    align-items: stretch;
  }
  .builder-generate-btn {
    width: 100%;
  }
  .preview-side-header,
  .preview-side-heading {
    flex-direction: column;
    align-items: flex-start;
  }
  .preview-side-actions {
    width: 100%;
    justify-content: flex-start;
  }
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
  flex: 0.92;
  background: rgba(255,255,255,0.78);
  display: flex;
  flex-direction: column;
  min-width: 0;
  position: relative;
  backdrop-filter: blur(6px);
}
.preview-side::before {
  content: '';
  position: absolute;
  left: 0;
  top: 22px;
  bottom: 22px;
  width: 1px;
  background: linear-gradient(180deg, transparent, rgba(128, 145, 255, 0.28), transparent);
}
.preview-side-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 18px 20px 8px;
}
.preview-side-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.preview-side-heading {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  min-width: 0;
}
.preview-side-heading-main {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.preview-side-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.preview-side-title {
  font-size: 17px;
  font-weight: 700;
  color: var(--t-text-primary);
  letter-spacing: 0.01em;
}
.preview-app-edit-btn {
  width: 28px;
  height: 28px;
  border-radius: 9px;
  border: 1px solid rgba(92, 115, 255, 0.14);
  background: rgba(247, 249, 255, 0.96);
  color: #7b89ab;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all .18s ease;
}
.preview-app-edit-btn svg {
  width: 14px;
  height: 14px;
}
.preview-app-edit-btn:hover {
  color: var(--t-brand-text);
  border-color: rgba(92, 115, 255, 0.22);
  background: rgba(92, 115, 255, 0.08);
}
.doc-preview-card {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 20px;
  border-radius: 22px;
  border: 1px solid rgba(128, 145, 255, 0.12);
  background: linear-gradient(180deg, rgba(255,255,255,0.98), rgba(247, 249, 255, 0.94));
  box-shadow: 0 10px 28px rgba(31, 41, 85, 0.05);
}
.doc-preview-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.doc-preview-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--t-text-primary);
}
.doc-preview-subtitle {
  margin-top: 4px;
  font-size: 12px;
  color: var(--t-text-muted);
}
.doc-preview-download {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 34px;
  padding: 0 12px;
  border-radius: 10px;
  border: 1px solid rgba(92, 115, 255, 0.14);
  background: rgba(247, 249, 255, 0.96);
  color: var(--t-brand-text);
  cursor: pointer;
  transition: all .18s ease;
}
.doc-preview-download:hover {
  background: rgba(92, 115, 255, 0.08);
  border-color: rgba(92, 115, 255, 0.22);
}
.doc-preview-download svg {
  width: 14px;
  height: 14px;
}
.doc-preview-download.compact {
  height: 30px;
  padding: 0 10px;
  border-radius: 8px;
  font-size: 11px;
}
.doc-preview-content {
  margin: 0;
  min-height: 360px;
  max-height: calc(100vh - 340px);
  overflow: auto;
  padding: 18px;
  border-radius: 16px;
  background: #f8faff;
  border: 1px solid rgba(128, 145, 255, 0.1);
  color: #4e5f7d;
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}
.preview-side-status {
  display: flex;
  align-items: flex-start;
  flex-direction: column;
  gap: 8px;
  font-size: 12px;
  color: #7c8ba8;
}
.preview-side-status.inline-meta {
  flex-direction: row;
  align-items: center;
  gap: 8px;
}
.preview-side-app-code-label {
  color: var(--t-text-muted);
  line-height: 1;
}
.preview-app-code-chip {
  display: inline-flex;
  align-items: center;
  padding: 4px 8px;
  border-radius: 999px;
  background: rgba(92, 115, 255, 0.08);
  color: var(--t-brand-text);
  border: 1px solid rgba(92, 115, 255, 0.14);
  font-size: 11px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.preview-app-code-chip.inline {
  padding: 3px 8px;
  font-size: 10px;
}
.preview-side-cta {
  border: none;
  background: var(--t-brand-gradient);
  color: #fff;
  height: 30px;
  padding: 0 12px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.preview-side-cta .cta-icon {
  width: 14px;
  height: 14px;
  margin-right: 6px;
}
.preview-side-cta.success {
  background: linear-gradient(135deg, #16a34a 0%, #22c55e 100%);
}
.preview-side-cta.secondary {
  border: 1px solid rgba(92, 115, 255, 0.16);
  background: rgba(247, 249, 255, 0.96);
  color: var(--t-brand-text);
}
.preview-side-cta:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.deploy-inline-card {
  margin: 0 14px 12px;
  padding: 12px 14px;
  border: 1px solid rgba(128, 145, 255, 0.12);
  border-radius: 12px;
  background: rgba(248, 250, 255, 0.9);
}
.deploy-inline-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}
.deploy-inline-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--t-text-primary);
}
.deploy-inline-meta,
.deploy-inline-copy {
  font-size: 11px;
  color: var(--t-text-muted);
}
.deploy-progress.inline {
  margin: 0 0 8px;
}
.builder-step-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 0 20px 12px;
  border-bottom: 1px solid rgba(128, 145, 255, 0.1);
  overflow-x: auto;
}
.builder-step-item {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  border: none;
  border-radius: 0;
  background: transparent;
  color: #8694af;
  white-space: nowrap;
  cursor: pointer;
  transition: all 0.2s ease;
}
.builder-step-item:hover {
  background: transparent;
  color: var(--t-text-primary);
}
.builder-step-copy {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
}
.builder-step-index {
  width: 22px;
  height: 22px;
  border-radius: 999px;
  background: rgba(128, 145, 255, 0.08);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
}
.builder-step-label {
  font-size: 11px;
  font-weight: 700;
  line-height: 1.2;
}
.builder-step-meta {
  font-size: 10px;
  color: #9aa7bf;
  line-height: 1.2;
}
.builder-step-item.active {
  color: var(--t-brand-text);
  background: transparent;
  box-shadow: none;
}
.builder-step-item.active .builder-step-index {
  background: var(--t-brand-gradient);
  color: #fff;
}
.builder-step-item.active .builder-step-meta {
  color: var(--t-brand-text);
}
.preview-body {
  flex: 1;
  overflow-y: auto;
  background: transparent;
}
.tab-content {
  padding: 20px;
}
.builder-step-item.done .builder-step-index {
  background: rgba(16, 185, 129, 0.14);
  color: var(--t-success);
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
.update-review-banner {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  margin: 0 0 12px 0;
  border-radius: 8px;
  background: var(--t-brand-soft, rgba(46, 132, 255, 0.08));
  border: 1px solid var(--t-brand-border, rgba(46, 132, 255, 0.2));
  font-size: 13px;
  color: var(--t-text-primary);
}
.update-review-banner-prefix {
  font-weight: 600;
  margin-right: 4px;
  color: var(--t-brand-light, #2e84ff);
}
.update-review-banner-chip {
  padding: 2px 10px;
  border-radius: 999px;
  background: var(--t-surface, rgba(255, 255, 255, 0.6));
  border: 1px solid var(--t-border-subtle, rgba(0, 0, 0, 0.08));
  font-size: 12px;
  white-space: nowrap;
}
.preview-empty { padding: 24px; text-align: center; color: var(--t-text-muted); font-size: 13px; margin-top: 80px; }
.preview-empty .empty-icon { font-size: 40px; opacity: 0.3; margin-bottom: 12px; }
.preview-empty.small { margin-top: 0; padding: 32px; }
.preview-empty-stage {
  max-width: 560px;
  margin: 72px auto 0;
  padding: 0;
  color: #8b97ae;
  text-align: center;
}
.preview-empty-icon {
  width: 56px;
  height: 56px;
  border-radius: 18px;
  background: linear-gradient(180deg, rgba(255,255,255,0.92), rgba(238,237,254,0.88));
  box-shadow: inset 0 0 0 1px rgba(125,114,246,0.14), 0 12px 28px rgba(103,96,180,0.10);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #7D72F6;
  margin-bottom: 16px;
}
.preview-empty-features {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  text-align: left;
  background: rgba(255,255,255,0.72);
  border: 1px solid rgba(83,74,183,0.12);
  border-radius: 16px;
  padding: 16px 18px;
}
.preview-empty-feature {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  color: #534AB7;
}
.preview-empty-feature-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #7D72F6;
  flex-shrink: 0;
}
.preview-empty-stage.parsing {
  margin-top: 120px;
}
.preview-empty-title {
  font-size: 16px;
  font-weight: 700;
  color: #31405e;
  margin-bottom: 8px;
}
.preview-empty-copy {
  font-size: 13px;
  line-height: 1.7;
}
.preview-empty-copy.single-line {
  display: inline-block;
  width: max-content;
  max-width: none;
  white-space: nowrap;
}
.parsing-spinner {
  width: 36px; height: 36px;
  border: 3px solid #e8ecf4;
  border-top-color: #6366f1;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin: 0 auto 16px;
}
@keyframes spin { to { transform: rotate(360deg); } }
.preview-body { flex: 1; overflow-y: auto; }
.tab-content { padding: 16px; }
/* ── 文档版本 ── */
.doc-versions-tab { display: flex; flex-direction: column; gap: 12px; }
.doc-version-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
  border-radius: 20px;
  border: 1px solid rgba(128, 145, 255, 0.12);
  background: linear-gradient(180deg, rgba(255,255,255,0.98), rgba(247, 249, 255, 0.94));
  box-shadow: 0 10px 28px rgba(31, 41, 85, 0.05);
}
.doc-version-panel.list-only {
  width: 100%;
}
.doc-upload-bar { display: flex; align-items: center; justify-content: space-between; }
.doc-top-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.doc-tab-title { font-size: 14px; font-weight: 600; color: var(--t-text-primary); }
.doc-tab-title.with-icon {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.doc-title-icon {
  width: 26px;
  height: 26px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: rgba(92, 115, 255, 0.08);
  color: var(--t-brand-text);
}
.doc-title-icon svg {
  width: 14px;
  height: 14px;
}
.doc-tab-subtitle {
  margin-top: 4px;
  font-size: 11px;
  line-height: 1.5;
  color: var(--t-text-muted);
}
.doc-tab-meta-sep {
  margin: 0 4px;
}
.doc-upload-btn {
  padding: 5px 12px; font-size: 11px; font-weight: 600; border: none; border-radius: 8px;
  background: var(--t-brand-gradient); color: #fff; cursor: pointer;
  transition: opacity 0.2s;
}
.doc-upload-btn:hover { opacity: 0.85; }
.doc-upload-btn.subtle {
  background: rgba(247, 249, 255, 0.96);
  border: 1px solid rgba(92, 115, 255, 0.14);
  color: var(--t-brand-text);
}
.doc-upload-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.doc-version-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 96px;
  padding: 14px;
  border-radius: 12px;
  border: 1px dashed rgba(128, 145, 255, 0.18);
  background: rgba(248, 250, 255, 0.82);
  color: var(--t-text-muted);
  font-size: 11px;
}
.doc-current-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.doc-current-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.doc-current-badge {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 9px;
  border-radius: 999px;
  background: rgba(92, 115, 255, 0.08);
  color: var(--t-brand-text);
  font-size: 10px;
  font-weight: 700;
}
.doc-current-tools {
  display: flex;
  align-items: center;
  gap: 8px;
}
.doc-version-switcher {
  padding: 16px 16px 0;
}
.doc-version-current-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 12px 14px;
  border: 1px solid rgba(92, 115, 255, 0.24);
  border-radius: 16px;
  background:
    linear-gradient(135deg, rgba(92, 115, 255, 0.12), rgba(255, 255, 255, 0.92)),
    var(--t-bg-elevated);
  box-shadow: 0 8px 24px rgba(51, 65, 145, 0.08);
}
.doc-version-current-main {
  min-width: 0;
  flex: 1;
  display: inline-flex;
  align-items: center;
  gap: 12px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--t-text-primary);
  text-align: left;
  cursor: pointer;
}
.doc-version-current-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 34px;
  height: 28px;
  padding: 0 10px;
  border-radius: 999px;
  background: rgba(92, 115, 255, 0.14);
  color: var(--t-brand-text);
  font-size: 13px;
  font-weight: 800;
  line-height: 1;
  flex-shrink: 0;
}
.doc-version-current-text {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.doc-version-current-text strong {
  overflow: hidden;
  color: var(--t-text-primary);
  font-size: 13px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.doc-version-current-text small {
  overflow: hidden;
  color: var(--t-text-muted);
  font-size: 11px;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.doc-version-current-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.doc-version-action,
.doc-version-history-toggle,
.doc-version-mini-action {
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 0 12px;
  border: 1px solid rgba(92, 115, 255, 0.16);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.88);
  color: var(--t-text-primary);
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
  white-space: nowrap;
  cursor: pointer;
  transition: border-color 0.18s ease, background 0.18s ease, color 0.18s ease, transform 0.18s ease;
}
.doc-version-action:hover,
.doc-version-history-toggle:hover,
.doc-version-mini-action:hover {
  border-color: rgba(92, 115, 255, 0.32);
  background: rgba(92, 115, 255, 0.08);
  color: var(--t-brand-text);
}
.doc-version-history-toggle {
  min-width: 126px;
}
.doc-version-history-toggle span {
  color: var(--t-text-muted);
  font-size: 11px;
  font-weight: 700;
}
.doc-version-history-panel {
  max-height: 268px;
  overflow: auto;
  margin-top: 10px;
  padding: 6px;
  border: 1px solid rgba(92, 115, 255, 0.14);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 12px 28px rgba(31, 41, 85, 0.08);
}
.doc-version-history-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px;
  border-radius: 10px;
  transition: background 0.18s ease;
}
.doc-version-history-row + .doc-version-history-row {
  border-top: 1px solid rgba(128, 145, 255, 0.10);
}
.doc-version-history-row:hover,
.doc-version-history-row.active {
  background: rgba(92, 115, 255, 0.08);
}
.doc-version-history-main {
  min-width: 0;
  flex: 1;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 0;
  border: 0;
  background: transparent;
  text-align: left;
  cursor: pointer;
}
.doc-history-version {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 28px;
  border-radius: 999px;
  background: rgba(92, 115, 255, 0.10);
  color: var(--t-brand-text);
  font-size: 12px;
  font-weight: 800;
  flex-shrink: 0;
}
.doc-history-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.doc-history-copy strong {
  overflow: hidden;
  color: var(--t-text-primary);
  font-size: 12px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.doc-history-copy small {
  overflow: hidden;
  color: var(--t-text-muted);
  font-size: 11px;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.doc-version-history-main em {
  margin-left: auto;
  color: var(--t-brand-text);
  font-size: 11px;
  font-style: normal;
  font-weight: 800;
  flex-shrink: 0;
}
.doc-version-history-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}
.doc-version-mini-action {
  height: 30px;
  padding: 0 10px;
  font-size: 11px;
}
/* 版本列表选中态：明显蓝色高亮（覆盖默认的 .current 浅色） */
.version-row-selectable { cursor: pointer; }
.version-row-selectable.version-row-active {
  border-color: var(--t-brand) !important;
  background: rgba(92, 115, 255, 0.08) !important;
  box-shadow: 0 0 0 1px var(--t-brand) inset;
}
.version-row-selectable.version-row-active .doc-ver-header strong {
  color: var(--t-brand);
}
.doc-version-list { display: flex; flex-direction: column; gap: 10px; }
.doc-version-list.compact {
  gap: 12px;
}
.doc-version-row {
  border: 1px solid var(--t-border-subtle);
  border-radius: 16px;
  background: var(--t-bg-elevated);
  transition: border-color 0.2s ease, box-shadow 0.2s ease, background 0.2s ease;
}
.doc-version-row:hover {
  border-color: var(--t-brand-glow);
  box-shadow: 0 8px 20px rgba(31, 41, 85, 0.06);
}
.doc-version-row.current {
  border-color: rgba(92, 115, 255, 0.22);
  background: rgba(242, 246, 255, 0.96);
}
.doc-version-row.expanded {
  background: rgba(245, 248, 255, 0.98);
}
.doc-version-summary {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
}
.doc-version-toggle {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
  border: none;
  background: transparent;
  padding: 0;
  text-align: left;
  cursor: pointer;
}
.doc-version-main {
  min-width: 0;
  flex: 1;
}
.doc-ver-header { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; min-width: 0; }
.doc-ver-icon {
  width: 24px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: rgba(92, 115, 255, 0.08);
  color: var(--t-brand-text);
  flex-shrink: 0;
}
.doc-ver-icon svg {
  width: 14px;
  height: 14px;
}
.doc-ver-num {
  flex-shrink: 0;
  font-size: 13px; font-weight: 700;
  background: var(--t-brand-gradient);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
}
.doc-ver-filename {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  color: var(--t-text-primary);
  font-weight: 600;
}
.doc-ver-current {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(92, 115, 255, 0.1);
  color: var(--t-brand-text);
  font-size: 10px;
  font-weight: 600;
}
.doc-ver-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 10px;
}
.doc-ver-time { font-size: 11px; color: var(--t-text-muted); }
.doc-ver-summary { font-size: 11px; color: var(--t-text-secondary); }
.doc-ver-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.doc-action-btn {
  padding: 6px 12px;
  font-size: 11px;
  font-weight: 600;
  border-radius: 8px;
  cursor: pointer;
  border: 1px solid rgba(128, 145, 255, 0.14);
  background: rgba(247, 249, 255, 0.96);
  color: var(--t-brand-text);
  transition: all 0.2s;
}
.doc-action-btn:hover {
  background: rgba(92, 115, 255, 0.08);
  border-color: rgba(92, 115, 255, 0.22);
}
.doc-action-btn.primary {
  background: var(--t-brand-gradient);
  border-color: transparent;
  color: #fff;
}
.doc-action-btn.primary:hover { opacity: 0.9; }
.doc-action-btn.diff { border-color: var(--t-brand-glow); color: var(--t-brand-light); }
.doc-action-btn.diff:hover { background: var(--t-brand-subtle); }
.doc-action-btn.danger {
  border-color: rgba(225, 90, 90, 0.18);
  color: #cf4343;
  background: rgba(255, 247, 247, 0.96);
}
.doc-action-btn.danger:hover {
  background: rgba(225, 90, 90, 0.08);
  border-color: rgba(225, 90, 90, 0.28);
}
.deploy-log-card {
  margin: 0 12px 12px;
  padding: 10px 12px;
  border-radius: 18px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  background: rgba(255, 255, 255, 0.9);
}
.deploy-log-card.compact {
  margin-top: 8px;
}
.deploy-log-card.expanded {
  padding-bottom: 12px;
}
.deploy-log-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: var(--t-text-primary);
  font-size: 13px;
  font-weight: 700;
}
.deploy-log-header.toggle {
  width: 100%;
  padding: 0;
  border: none;
  background: transparent;
  cursor: pointer;
  text-align: left;
}
.deploy-log-title-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.deploy-log-summary {
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex: 1;
}
.deploy-log-summary-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--t-text-secondary);
  font-size: 12px;
  font-weight: 500;
}
.deploy-log-toggle {
  color: var(--t-brand-text);
  font-size: 12px;
  font-weight: 700;
}
.deploy-log-count {
  color: var(--t-text-muted);
  font-size: 11px;
  font-weight: 600;
}
.deploy-log-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 180px;
  overflow-y: auto;
  margin-top: 10px;
}
.deploy-log-item {
  padding: 8px 10px;
  border-radius: 12px;
  border: 1px solid rgba(148, 163, 184, 0.12);
  background: rgba(248, 250, 252, 0.96);
}
.deploy-log-item.info {
  border-color: rgba(92, 115, 255, 0.14);
  background: rgba(244, 247, 255, 0.96);
}
.deploy-log-item.success {
  border-color: rgba(34, 197, 94, 0.16);
  background: rgba(240, 253, 244, 0.96);
}
.deploy-log-item.error {
  border-color: rgba(225, 90, 90, 0.18);
  background: rgba(255, 245, 245, 0.96);
}
.deploy-log-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 2px;
}
.deploy-log-level {
  font-size: 10px;
  font-weight: 700;
  color: var(--t-text-secondary);
}
.deploy-log-time {
  font-size: 10px;
  color: var(--t-text-muted);
}
.deploy-log-text {
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--t-text-primary);
  font-size: 11px;
  line-height: 1.45;
}
.doc-expand-icon {
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: rgba(92, 115, 255, 0.08);
  color: var(--t-brand-text);
  flex-shrink: 0;
  transition: transform 0.2s ease, background 0.2s ease;
}
.doc-expand-icon svg {
  width: 14px;
  height: 14px;
}
.doc-expand-icon.expanded {
  transform: rotate(180deg);
  background: rgba(92, 115, 255, 0.14);
}
.doc-version-body {
  padding: 0 16px 16px;
}
.doc-version-body-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
  padding-top: 2px;
}
.doc-version-body-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--t-text-primary);
}
.doc-version-content {
  margin: 0;
  min-height: 160px;
  max-height: 460px;
  overflow: auto;
  padding: 16px 18px;
  border-radius: 12px;
  background: var(--t-bg-base, #f8faff);
  border: 1px solid var(--t-border-subtle, rgba(128, 145, 255, 0.1));
  color: var(--t-text-primary, #2d3a56);
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
.doc-version-content.expanded {
  min-height: 260px;
  max-height: none;
}
.structured-doc-panel {
  padding: 14px 16px;
  background: rgba(247, 249, 255, 0.96);
}
/* 文档预览弹窗 */
:deep(.doc-preview-dialog) .el-dialog { background: var(--t-bg-panel); color: var(--t-text-primary); }
:deep(.doc-preview-dialog) .el-dialog__header { border-bottom: 1px solid var(--t-border-subtle); }
:deep(.doc-preview-dialog) .el-dialog__title { color: var(--t-text-primary); }
:deep(.doc-preview-dialog) .el-dialog__headerbtn .el-dialog__close { color: var(--t-text-secondary); }
:deep(.doc-preview-dialog-fullscreen) .el-dialog {
  height: 96vh;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
}
:deep(.doc-preview-dialog-fullscreen) .el-dialog__body {
  flex: 1;
  min-height: 0;
  padding: 16px 20px 20px;
}
.doc-preview-body {
  max-height: 70vh; overflow-y: auto; overflow-x: auto; padding: 16px;
  font-size: 13px; line-height: 1.7; color: var(--t-text-primary);
  background: var(--t-bg-base); border-radius: 8px;
  /* 让内容跟随容器宽度自适应，表格变窄时按列宽换行而不是被裁掉 */
  width: 100%; min-width: 0; box-sizing: border-box;
}
.doc-preview-body.fullscreen {
  max-height: none;
  height: 100%;
  min-height: 0;
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
.doc-preview-body :deep(.doc-table-scroll) { width: 100%; overflow-x: auto; margin: 10px 0; }
.doc-preview-body :deep(table) {
  /* 表格按内容撑（避免列数多时挤压到列名重叠）；超出容器宽度时由
     .doc-preview-body 父级 overflow-x: auto 横向滚动 */
  width: max-content;
  min-width: 100%;
  border-collapse: collapse;
  margin: 0;
  font-size: 12px;
  table-layout: auto;
}
.doc-preview-body :deep(table td),
.doc-preview-body :deep(table th) {
  /* 单元格内容默认按词换行；中文/编码不强制 break-word 避免被撕开 */
  white-space: normal;
  overflow-wrap: break-word;
}
.doc-preview-body :deep(th) {
  background: var(--t-brand-subtle);
  color: var(--t-brand-light);
  text-align: left;
  padding: 8px 12px;
  border: 1px solid var(--t-border-subtle);
  font-weight: 600;
  white-space: nowrap;
  word-break: keep-all;
}
.doc-preview-body :deep(td) {
  padding: 6px 12px;
  border: 1px solid var(--t-border-subtle);
  white-space: nowrap;
  word-break: keep-all;
  overflow-wrap: normal;
}
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
.diff-stat.modified { color: var(--t-warning); }
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
.doc-diff-structured {
  padding: 14px 16px 18px;
  font-family: inherit;
}
.doc-diff-structured :deep(.structured-doc) {
  font-size: 13px;
}
.doc-diff-structured :deep(.doc-app-name) {
  font-size: 28px;
  margin-bottom: 10px;
}
.doc-diff-structured :deep(.doc-section) {
  margin-bottom: 18px;
}
.doc-diff-structured :deep(.doc-section-title) {
  font-size: 18px;
  margin-bottom: 10px;
}
.doc-diff-structured :deep(.doc-subsection-title) {
  font-size: 15px;
}
.doc-diff-structured :deep(.doc-table) {
  font-size: 12px;
}
.doc-diff-structured :deep(th),
.doc-diff-structured :deep(td) {
  padding: 6px 10px;
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
.dict-option-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.dict-option-row {
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid rgba(128, 145, 255, 0.08);
  background: rgba(247, 249, 255, 0.72);
  border-radius: 8px;
  padding: 6px 8px;
}
.dict-option-row.diff {
  justify-content: space-between;
  background: rgba(255,255,255,0.88);
}
.dict-option-row.versioned {
  justify-content: space-between;
  background: rgba(255,255,255,0.88);
}
.dict-option-code {
  min-width: 88px;
  font-size: 10px;
  color: var(--t-brand-text);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.dict-option-name {
  font-size: 12px;
  color: var(--t-text-primary);
}
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
.diff-model-card {
  border-color: rgba(92, 115, 255, 0.14);
  box-shadow: 0 10px 24px rgba(31, 41, 85, 0.04);
}
.model-name { font-weight: 600; color: var(--t-text-primary); }
.model-title-stack {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}
.model-summary {
  font-size: 11px;
  color: var(--t-text-secondary);
  line-height: 1.45;
}
.model-code { margin-left: auto; font-size: 10px; color: var(--t-text-muted); font-family: monospace; }
.preview-item-card {
  border: 1px solid rgba(128, 145, 255, 0.1);
  border-radius: 12px;
  padding: 12px 12px 10px;
  margin-bottom: 10px;
  background: rgba(255,255,255,0.56);
}
.preview-item-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 6px;
}
.preview-item-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.preview-item-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--t-text-primary);
}
.versioned-card {
  background: linear-gradient(180deg, rgba(255,255,255,0.96), rgba(246, 248, 255, 0.92));
  box-shadow: 0 10px 24px rgba(31, 41, 85, 0.04);
}
.history-muted-card {
  border-color: rgba(148, 163, 184, 0.2);
  background: linear-gradient(180deg, rgba(248, 250, 252, 0.98), rgba(241, 245, 249, 0.94));
}
.history-muted-card .preview-item-title,
.history-muted-card .model-name,
.history-muted-card .form-change-name,
.history-muted-card .field-name {
  color: #667085;
}
.history-muted-card .preview-item-code,
.history-muted-card .preview-item-desc,
.history-muted-card .model-summary,
.history-muted-card .field-code,
.history-muted-card .form-change-detail {
  color: #94a3b8;
}
.history-muted-card .form-meta-chip {
  background: rgba(148, 163, 184, 0.12);
  color: #94a3b8;
  border-color: rgba(148, 163, 184, 0.16);
}
.diff-preview-card {
  border-color: rgba(92, 115, 255, 0.14);
  background: linear-gradient(180deg, rgba(255,255,255,0.96), rgba(246, 248, 255, 0.92));
  box-shadow: 0 10px 24px rgba(31, 41, 85, 0.04);
}
.change-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 22px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.02em;
}
.change-badge.create {
  background: rgba(16, 185, 129, 0.12);
  color: #047857;
}
.change-badge.update {
  background: rgba(92, 115, 255, 0.12);
  color: var(--t-brand-text);
}
.change-badge.delete {
  background: rgba(239, 68, 68, 0.12);
  color: #b91c1c;
}
.change-badge.disable {
  background: rgba(245, 158, 11, 0.14);
  color: #b45309;
}
.change-badge.mini {
  height: 20px;
  padding: 0 7px;
}
.version-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 22px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.02em;
  border: 1px solid transparent;
}
.version-badge.active {
  background: rgba(92, 115, 255, 0.1);
  color: var(--t-brand-text);
  border-color: rgba(92, 115, 255, 0.16);
}
.version-badge.deleted,
.version-badge.disabled {
  background: rgba(148, 163, 184, 0.14);
  color: #64748b;
  border-color: rgba(148, 163, 184, 0.2);
}
.version-badge.mini {
  min-height: 20px;
  padding: 0 7px;
}
.preview-item-code {
  margin-top: 2px;
  font-size: 11px;
  color: #7f8ca5;
  font-family: monospace;
}
.preview-item-desc {
  font-size: 12px;
  line-height: 1.55;
  color: #53627d;
}
.builder-edit-link {
  width: 24px;
  height: 24px;
  min-width: 24px;
  border: 1px solid rgba(128, 145, 255, 0.14);
  border-radius: 8px;
  background: rgba(255,255,255,0.86);
  color: #7d8aac;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.18s ease;
}
.builder-edit-link svg {
  width: 13px;
  height: 13px;
}
.builder-edit-link:hover {
  color: var(--t-brand-text);
  border-color: rgba(93, 114, 255, 0.22);
  background: rgba(93, 114, 255, 0.08);
}
.builder-edit-link.inline {
  margin-left: 6px;
}
.field-list { }
.field-row { display: flex; justify-content: space-between; align-items: center; padding: 0 12px; height: 44px; min-height: 44px; border-top: 1px solid var(--t-border-subtle); transition: background 0.15s; }
.field-row:hover { background: var(--t-bg-subtle); }
.field-row.diff {
  min-height: 52px;
  height: auto;
  padding: 10px 12px;
}
.field-row.versioned {
  min-height: 52px;
  height: auto;
  padding: 10px 12px;
}
.history-muted-row {
  background: rgba(241, 245, 249, 0.72) !important;
  border-color: rgba(148, 163, 184, 0.16) !important;
}
.history-muted-row .dict-option-code,
.history-muted-row .dict-option-name,
.history-muted-row .field-icon,
.history-muted-row .field-name,
.history-muted-row .field-code,
.history-muted-row .ftype,
.history-muted-row .form-change-name,
.history-muted-row .form-change-detail {
  color: #94a3b8;
}
.field-left { display: flex; align-items: center; gap: 8px; min-width: 0; flex: 1; }
.field-text { display: flex; flex-direction: column; min-width: 0; }
.field-icon { width: 24px; min-width: 24px; height: 24px; display: flex; align-items: center; justify-content: center; font-size: 12px; background: var(--t-border-subtle); border-radius: 6px; color: var(--t-text-muted); flex-shrink: 0; }
.field-name { font-size: 13px; color: var(--t-text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.field-code { font-size: 10px; color: var(--t-text-muted); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.req { color: var(--t-danger); font-size: 10px; margin-left: 2px; flex-shrink: 0; }
.field-right { display: flex; align-items: center; gap: 6px; flex-shrink: 0; margin-left: 12px; }
.ftag { font-size: 10px; padding: 2px 8px; border-radius: 4px; white-space: nowrap; line-height: 1.4; }
.ftag.dict { background: rgba(245,158,11,0.12); color: var(--t-warning); }
.ftag.ref { background: rgba(96,165,250,0.12); color: var(--t-info); }
.ftype { font-size: 11px; color: var(--t-text-muted); white-space: nowrap; }

/* 模型选择 */
.model-select-bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; padding: 8px 12px; background: var(--t-border-subtle); border-radius: 8px; }
.builder-model-bar { gap: 14px; border: 1px solid var(--t-border-subtle); background: var(--t-bg-elevated); border-radius: 12px; padding: 10px 14px; }

@media (max-width: 980px) {
  .doc-upload-bar,
  .doc-version-summary,
  .doc-version-body-head {
    align-items: stretch;
    flex-direction: column;
  }

  .doc-current-head,
  .doc-top-actions,
  .doc-version-current-strip {
    align-items: stretch;
    flex-direction: column;
  }

  .doc-version-toggle {
    width: 100%;
  }

  .doc-version-current-actions,
  .doc-ver-actions {
    width: 100%;
    justify-content: flex-start;
    flex-wrap: wrap;
  }

  .doc-version-history-row {
    align-items: stretch;
    flex-direction: column;
  }

  .doc-version-history-actions {
    justify-content: flex-start;
  }

  .form-change-row,
  .update-change-row {
    align-items: flex-start;
    flex-direction: column;
  }
}
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
.builder-model-option-row { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; padding: 2px 0; }
.builder-model-option-name { color: var(--t-text-primary); font-size: 12px; line-height: 1.35; }
.builder-model-option-meta { font-size: 10px; color: var(--t-text-muted); line-height: 1.3; }

:deep(.model-select-dropdown) {
  border-radius: 10px;
  padding: 4px;
}

:deep(.model-select-dropdown .el-select-dropdown__item) {
  min-height: 40px;
  padding: 7px 10px;
  border-radius: 8px;
}

:deep(.model-select-dropdown .el-select-dropdown__item.is-selected) {
  font-weight: 600;
}
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
.form-preview-card {
  padding-bottom: 12px;
}
.form-meta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}
.resource-meta-row {
  margin-top: 2px;
}
.form-meta-chip {
  display: inline-flex;
  align-items: center;
  padding: 4px 8px;
  font-size: 11px;
  border-radius: 999px;
  background: rgba(92, 115, 255, 0.08);
  color: var(--t-brand-text);
  border: 1px solid rgba(92, 115, 255, 0.12);
}
.form-meta-chip.subtle {
  background: rgba(15, 23, 42, 0.04);
  color: var(--t-text-secondary);
  border-color: rgba(15, 23, 42, 0.08);
}
.form-change-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.form-change-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid rgba(128, 145, 255, 0.1);
  border-radius: 10px;
  background: rgba(255,255,255,0.88);
}
.form-change-row.versioned {
  align-items: flex-start;
}
.form-change-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.form-change-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--t-text-primary);
}
.form-change-detail {
  font-size: 11px;
  color: var(--t-text-secondary);
}
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
.perm-header { padding: 8px 12px; background: var(--t-bg-subtle); font-size: 12px; font-weight: 600; color: var(--t-text-primary); display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.perm-heading-block { display: flex; flex-direction: column; gap: 2px; }
.perm-code-text { font-size: 10px; color: var(--t-text-muted); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
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
.deploy-title-row { display: flex; align-items: center; gap: 8px; }
.deploy-title { font-size: 14px; font-weight: 700; color: var(--t-text-primary); }
.deploy-desc { font-size: 11px; color: var(--t-text-muted); margin-top: 2px; }
.deploy-live-badge {
  display: inline-flex;
  align-items: center;
  height: 20px;
  padding: 0 8px;
  border-radius: 999px;
  background: rgba(92, 115, 255, 0.1);
  color: var(--t-brand-text);
  font-size: 10px;
  font-weight: 700;
  box-shadow: 0 0 0 1px rgba(92, 115, 255, 0.08);
}
.deploy-current-step {
  margin-top: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--t-text-primary);
}
.deploy-close { all: unset; cursor: pointer; color: var(--t-text-muted); font-size: 16px; padding: 4px; transition: color 0.2s; }
.deploy-close:hover { color: var(--t-text-secondary); }
.deploy-header-actions { display: flex; align-items: center; gap: 8px; }
.deploy-retry-all-btn {
  display: inline-flex; align-items: center; gap: 4px;
  background: var(--t-brand-soft, rgba(90, 120, 255, 0.12));
  color: var(--t-brand, #5a78ff);
  border: 1px solid var(--t-brand-border, rgba(90, 120, 255, 0.35));
  border-radius: 6px;
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}
.deploy-retry-all-btn:hover:not(:disabled) {
  background: var(--t-brand-soft-strong, rgba(90, 120, 255, 0.2));
  border-color: var(--t-brand, #5a78ff);
}
.deploy-retry-all-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.deploy-retry-all-icon { font-size: 13px; line-height: 1; }

.deploy-progress { padding: 0 16px 8px; display: flex; align-items: center; gap: 8px; }
.dp-track { flex: 1; height: 3px; background: var(--t-border-subtle); border-radius: 2px; overflow: hidden; }
.dp-fill { height: 100%; background: var(--t-brand-gradient); border-radius: 2px; transition: width 0.5s; }
.dp-meta { font-size: 10px; color: var(--t-text-muted); white-space: nowrap; }

.deploy-actions { padding: 0 16px 12px; }
.deploy-conflict-card {
  margin: 0 16px 12px;
  padding: 12px;
  border-radius: 12px;
  background: rgba(255, 248, 246, 0.96);
  border: 1px solid rgba(239, 68, 68, 0.16);
}
.deploy-conflict-title {
  font-size: 13px;
  font-weight: 700;
  color: #b45309;
  margin-bottom: 6px;
}
.deploy-conflict-copy {
  font-size: 12px;
  color: var(--t-text-secondary);
  line-height: 1.6;
}
.deploy-conflict-copy code {
  padding: 1px 6px;
  border-radius: 999px;
  background: rgba(239, 68, 68, 0.08);
  color: #b91c1c;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.deploy-conflict-input-row {
  margin-top: 10px;
  display: flex;
  gap: 8px;
}
.deploy-conflict-input {
  flex: 1;
  height: 34px;
  padding: 0 10px;
  border-radius: 8px;
  border: 1px solid rgba(239, 68, 68, 0.18);
  background: #fff;
  font-size: 12px;
  outline: none;
}
.deploy-conflict-input:focus {
  border-color: var(--t-brand);
}
.deploy-conflict-btn {
  border: none;
  border-radius: 8px;
  padding: 0 12px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.deploy-conflict-btn.primary {
  background: var(--t-brand-gradient);
  color: #fff;
}
.deploy-conflict-btn:disabled { opacity: 0.5; cursor: not-allowed; }
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
.dg.current {
  border-color: rgba(92, 115, 255, 0.22);
  box-shadow: 0 10px 24px rgba(92, 115, 255, 0.08);
}
.dg-hd { display: flex; align-items: center; gap: 6px; padding: 10px 14px; background: var(--t-bg-subtle); font-size: 12px; }
.dg.current .dg-hd {
  background: linear-gradient(180deg, var(--t-brand-subtle), color-mix(in srgb, var(--t-brand) 5%, transparent));
}
.update-review-groups {
  padding-top: 4px;
}
.dg.update .dg-hd {
  background: linear-gradient(180deg, var(--t-brand-subtle), color-mix(in srgb, var(--t-brand) 5%, transparent));
}
.dg-icon { font-size: 13px; }
.dg-name { font-weight: 600; color: var(--t-text-primary); flex: 1; }
.dg-badge { font-size: 9px; padding: 1px 6px; border-radius: 99px; font-weight: 600; background: var(--t-border-subtle); color: var(--t-text-muted); }
.dg-badge.done { background: rgba(16,185,129,0.12); color: var(--t-success); }
.dg-badge.err { background: rgba(239,68,68,0.12); color: var(--t-danger); }
.update-change-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 14px;
}
.update-change-row + .update-change-row {
  border-top: 1px solid var(--t-border-subtle);
}
.update-change-copy {
  min-width: 0;
  flex: 1;
}
.update-change-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--t-text-primary);
}
.update-change-meta {
  margin-top: 3px;
  font-size: 10px;
  color: var(--t-text-muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.ds { display: flex; align-items: center; padding: 7px 14px; gap: 10px; font-size: 12px; }
.ds + .ds { border-top: 1px solid var(--t-border-subtle); }
.ds:hover { background: var(--t-bg-subtle); }
.ds.current {
  background: linear-gradient(90deg, rgba(92, 115, 255, 0.08), rgba(92, 115, 255, 0.02));
}
.ds-dot { width: 18px; height: 18px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 9px; font-weight: 700; color: #fff; flex-shrink: 0; }
.ds-dot.completed { background: var(--t-success); }
.ds-dot.error { background: var(--t-danger); }
.ds-dot.pending { background: var(--t-border-strong); width: 7px; height: 7px; margin: 0 5.5px; }
.ds-dot.pulse { background: var(--t-brand); animation: dpulse 1.5s infinite; }
@keyframes dpulse { 0%,100% { box-shadow: 0 0 0 0 var(--t-brand-glow); } 50% { box-shadow: 0 0 0 5px var(--t-brand-subtle); } }

.ds-body { flex: 1; min-width: 0; }
.ds-name { color: var(--t-text-primary); }
.ds.current .ds-name {
  color: var(--t-brand-text);
  font-weight: 700;
}
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

.deploy-done {
  padding: 12px 16px;
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 8px;
  text-align: left;
  font-size: 13px;
  color: var(--t-success);
  font-weight: 500;
}
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
.conflict-resolve-box {
  padding: 0;
  min-width: 0;
}
.chat-bubble.assistant:has(.conflict-resolve-box) .assistant-avatar {
  width: 30px;
  height: 30px;
  min-width: 30px;
  border-radius: 10px;
  font-size: 12px;
}
.chat-bubble.assistant:has(.conflict-resolve-box) .bubble-inner {
  max-width: 380px;
}
.chat-bubble.assistant:has(.conflict-resolve-box) .bubble-content.assistant {
  padding: 10px 12px;
  border-radius: 14px;
}
.conflict-label {
  margin-bottom: 5px;
  font-size: 11px;
  line-height: 1.3;
  color: var(--t-text-primary);
  white-space: nowrap;
}
.conflict-label code {
  background: rgba(92, 115, 255, 0.12);
  color: var(--t-brand-text);
  padding: 1px 6px;
  border-radius: 999px;
  font-family: monospace;
  font-size: 11px;
}
.conflict-input-row {
  display: flex;
  gap: 6px;
  align-items: center;
}
.conflict-input {
  flex: 1;
  min-width: 0;
  height: 32px;
  padding: 0 9px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.95);
  color: #0f172a;
  font-size: 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  outline: none;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.conflict-input::placeholder {
  color: #94a3b8;
}
.conflict-input:focus {
  border-color: rgba(92, 115, 255, 0.42);
  box-shadow: 0 0 0 3px rgba(92, 115, 255, 0.08);
}
.conflict-input:disabled { opacity: 0.5; }
.conflict-btn {
  min-width: 48px;
  height: 32px;
  border: none;
  cursor: pointer;
  border-radius: 8px;
  font-size: 11px;
  font-weight: 600;
  padding: 0 10px;
  transition: all 0.2s;
}
.conflict-btn.confirm { background: var(--t-brand-gradient); color: #fff; }
.conflict-btn.confirm:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 2px 8px var(--t-brand-glow); }
.conflict-btn.cancel { background: rgba(241, 245, 249, 0.95); color: #64748b; }
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

/* ── 模型编码冲突弹窗 ── */
.conflict-dialog-tip {
  font-size: 13px;
  line-height: 1.6;
  color: var(--t-text-secondary);
  margin-bottom: 14px;
}
.conflict-dialog-tip code {
  background: rgba(124, 58, 237, 0.12);
  color: var(--t-text-primary);
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 12px;
}
.conflict-dialog-table {
  display: flex;
  flex-direction: column;
  gap: 1px;
  background: var(--t-border-subtle);
  border-radius: 8px;
  overflow: hidden;
  max-height: 420px;
  overflow-y: auto;
}
.conflict-row {
  display: grid;
  grid-template-columns: 1fr 1.1fr 1.3fr;
  gap: 12px;
  padding: 10px 14px;
  background: var(--t-bg-panel);
  align-items: center;
}
.conflict-row.conflict-head {
  background: var(--t-bg-elevated);
  font-size: 12px;
  color: var(--t-text-muted);
  font-weight: 500;
}
.conflict-row .col-name {
  font-size: 13px;
  color: var(--t-text-primary);
  word-break: break-all;
}
.conflict-row .col-orig code {
  background: rgba(220, 38, 38, 0.12);
  color: #f87171;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  word-break: break-all;
}
.conflict-btn {
  padding: 8px 18px;
  border-radius: 8px;
  border: none;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
  margin-left: 8px;
}
.conflict-btn.cancel {
  background: transparent;
  color: var(--t-text-secondary);
  border: 1px solid var(--t-border-subtle);
}
.conflict-btn.cancel:hover:not(:disabled) {
  background: var(--t-bg-elevated);
}
.conflict-btn.confirm {
  background: linear-gradient(135deg, #7c3aed, #5b21b6);
  color: #fff;
}
.conflict-btn.confirm:hover:not(:disabled) {
  opacity: 0.92;
}
.conflict-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 新版 AI-Builder 外观：保留真实搭建逻辑，只重排视觉层 */
.chat-page {
  background: #eef1f6;
}

.chat-page .top-bar {
  height: 46px;
  padding: 0 12px;
  background: #fff;
  border-bottom: 1px solid #dfe4ec;
}

.builder-chat-top-center {
  flex: 1;
  justify-content: space-between;
}

.builder-chat-crumbs {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
  color: #647085;
  font-size: 12px;
  font-weight: 600;
}

.builder-chat-crumbs button {
  border: 0;
  background: transparent;
  padding: 0;
  color: #475569;
  font: inherit;
  cursor: pointer;
}

.builder-chat-crumbs strong {
  color: #111827;
}

.builder-top-action {
  height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 7px;
  padding: 0 12px;
  border: 1px solid #dbe2ea;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}

.builder-top-action.ghost {
  background: #fff;
  color: #111827;
}

.builder-top-action.ai-adjust-action {
  background: linear-gradient(135deg, #f3eefe 0%, #e9deff 100%);
  border-color: #c4b5fd;
  color: #6d28d9;
}

.builder-top-action.ai-adjust-action:hover {
  background: linear-gradient(135deg, #e9deff 0%, #d6c2fc 100%);
  border-color: #a78bfa;
}

.builder-top-action.primary {
  border-color: #111827;
  background: #111827;
  color: #fff;
}

.builder-top-action.artifact {
  background: transparent;
  color: #647085;
}

.builder-top-action.icon-only {
  width: 32px;
  padding: 0;
  border-radius: 8px;
}

.builder-top-action.artifact[aria-pressed="true"] {
  border-color: #cbd5e1;
  background: #f8fafc;
  color: #111827;
}

.builder-top-action-icon {
  width: 15px;
  height: 15px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
}

.builder-top-action-icon svg {
  width: 15px;
  height: 15px;
}

.builder-top-action:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.builder-chat-phase-strip {
  height: 42px;
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 0 18px;
  background: #fff;
  border-bottom: 1px solid #dfe4ec;
  flex-shrink: 0;
}

.builder-chat-agent {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  font-size: 12px;
  font-weight: 700;
  color: #111827;
}

.builder-chat-agent-dot,
.state-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: #4f6bff;
  flex: 0 0 auto;
}

.builder-chat-agent code {
  max-width: 190px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  border: 1px solid #dbe2ea;
  border-radius: 6px;
  background: #f3f6fb;
  padding: 2px 7px;
  color: #647085;
  font-size: 11px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.builder-chat-phases {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 0;
}

.builder-chat-phase {
  height: 26px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid #dbe2ea;
  border-radius: 999px;
  padding: 0 10px 0 7px;
  background: #f7f9fc;
  color: #7b8798;
  font-size: 12px;
  white-space: nowrap;
}

.builder-chat-phase span {
  width: 17px;
  height: 17px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: #e8edf5;
  color: #647085;
  font-size: 10px;
  font-weight: 700;
}

.builder-chat-phase.active {
  border-color: #cbd5e1;
  background: #fff;
  color: #1f2937;
  font-weight: 700;
}

.builder-chat-phase.active span {
  background: #4f6bff;
  color: #fff;
}

.builder-chat-phase.done {
  color: #475569;
  background: #fff;
}

.builder-chat-phase.done span {
  background: #e6f7ee;
  color: #178a53;
}

.builder-chat-save-state {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: #475569;
  font-size: 12px;
  font-weight: 700;
}

.state-dot.deployed {
  background: #12b981;
}

.state-dot.generated {
  background: #4f6bff;
}

.state-dot.draft {
  background: #a5adba;
}

.content-area {
  background: #eef1f6;
  min-height: 0;
}

.builder-content {
  margin: 0;
  border: 0;
  border-radius: 0;
  box-shadow: none;
  background: #eef1f6;
  height: 100%;
  min-height: 0;
}

.builder-content.artifacts-hidden {
  justify-content: center;
  padding: 0 clamp(16px, 5vw, 72px);
}

.builder-content.artifacts-hidden .chat-side {
  flex: 1 1 auto;
  width: min(100%, 860px);
  max-width: 860px;
  min-width: 0;
  margin: 0 auto;
  border-right: 0;
  background: transparent;
}

.builder-content.artifacts-hidden .messages {
  padding: 20px clamp(4px, 1.8vw, 18px) 14px;
}

.builder-content.artifacts-hidden .builder-spec-brief {
  width: min(100%, 780px);
  margin: 14px auto 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 12px 14px;
  border: 1px solid #dbe2ea;
  border-radius: 12px;
  background: #fff;
}

/* SPEC 入口提示 — 默认状态先 Claude 风格纯对话；AI 判定需求清晰后 SPEC 三栏自动展开 */
.spec-cta-banner {
  width: min(100%, 780px);
  margin: 14px auto 4px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  border-radius: 10px;
  background: rgba(79, 110, 247, 0.06);
  border: 1px solid rgba(79, 110, 247, 0.18);
}
.spec-cta-text {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #5a6680;
  font-size: 13px;
  line-height: 1.5;
}
.spec-cta-icon {
  font-size: 16px;
  line-height: 1;
  opacity: 0.85;
}
html[data-theme="dark"] .spec-cta-banner {
  background: rgba(79, 110, 247, 0.08);
  border-color: rgba(79, 110, 247, 0.25);
}
html[data-theme="dark"] .spec-cta-text { color: #b8c0d6; }

.builder-content.artifacts-hidden .builder-spec-brief-main {
  min-width: 190px;
  gap: 3px;
}

.builder-content.artifacts-hidden .builder-spec-brief-main strong {
  font-size: 15px;
}

.builder-content.artifacts-hidden .builder-spec-brief-main p {
  max-width: 360px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.builder-content.artifacts-hidden .builder-spec-brief-stats {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 0 1 auto;
}

.builder-content.artifacts-hidden .builder-spec-brief-stats button {
  width: 72px;
  min-height: 42px;
  padding: 5px 6px;
}

.builder-content.artifacts-hidden .builder-workbench {
  width: min(100%, 780px);
  margin: 0 auto 14px;
  border: 1px solid #dbe2ea;
  border-radius: 14px;
}

.builder-content.artifacts-hidden .builder-composer-shell {
  border: 0;
  box-shadow: none;
}

.builder-content.artifacts-open .chat-side {
  border-right: 1px solid #dfe4ec;
}

.chat-side {
  flex: 0 0 420px;
  min-width: 360px;
  max-width: 440px;
  background: #fff;
  border-right: 1px solid #dfe4ec;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.messages {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding: 18px 14px 14px;
}

.bubble-content {
  border-radius: 10px;
  font-size: 13px;
}

.bubble-content.assistant {
  background: #fff;
  border-color: #e1e6ee;
  box-shadow: none;
}

.bubble-content.user {
  background: #111827;
}

.assistant-avatar {
  border-radius: 6px;
  background: #111827;
  box-shadow: none;
  animation: none;
}

.builder-workbench {
  flex: 0 0 auto;
  margin-top: auto;
  padding: 10px 12px;
  border-top: 1px solid #e5eaf1;
  background: #fff;
  position: sticky;
  bottom: 0;
  z-index: 4;
  box-shadow: 0 -10px 24px rgba(15, 23, 42, 0.04);
}

.builder-composer-shell {
  padding: 0;
  border-radius: 10px;
  border-color: #dbe2ea;
  background: #fff;
  box-shadow: none;
}

.input-card {
  border-radius: 10px;
  background: #fff;
  box-shadow: none;
}

.quick-edit-glow {
  display: none;
}

.input-card-top textarea {
  min-height: 38px;
  font-size: 13px;
  line-height: 1.5;
  color: #111827;
}

.send-btn {
  border-radius: 8px;
  background: #111827;
  box-shadow: none;
}

.chat-side {
  flex: 0 0 clamp(380px, 32vw, 520px);
  max-width: 540px;
  background: #fff;
  border-right: 1px solid #dfe4ec;
}

.builder-workbench {
  padding: 10px 14px 14px;
  border-top: 1px solid #e3e8f0;
  background: linear-gradient(180deg, rgba(255,255,255,0.72), #fff);
}

.builder-composer-shell {
  border-radius: 12px;
  background: #fff;
  border-color: #dbe2ea;
  box-shadow: 0 -8px 24px rgba(15, 23, 42, 0.04);
}

.builder-spec-brief {
  flex-shrink: 0;
  display: grid;
  gap: 12px;
  padding: 14px 16px;
  border-bottom: 1px solid #dfe4ec;
  background: #fff;
}

.builder-spec-brief-main {
  display: grid;
  gap: 4px;
}

.builder-spec-kicker,
.spec-overview-eyebrow {
  color: #647085;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0;
  text-transform: uppercase;
}

.builder-spec-brief-main strong {
  color: #111827;
  font-size: 16px;
  line-height: 1.2;
}

.builder-spec-brief-main p {
  margin: 0;
  color: #647085;
  font-size: 12px;
  line-height: 1.55;
}

.builder-spec-brief-stats {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 6px;
}

.builder-spec-brief-stats button {
  min-width: 0;
  border: 1px solid #dbe2ea;
  border-radius: 8px;
  background: #f8fafc;
  color: #647085;
  padding: 7px 6px;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
}

.builder-spec-brief-stats button:hover {
  border-color: #b8c3d4;
  background: #fff;
  color: #111827;
}

.builder-spec-brief-stats span {
  display: block;
  color: #111827;
  font-size: 15px;
  line-height: 1.1;
}

.builder-result-side.preview-side {
  flex: 1 1 auto;
  background: #eef1f6;
}

.preview-side::before {
  display: none;
}

.builder-canvas-tabs {
  height: 44px;
  display: flex;
  align-items: flex-end;
  gap: 6px;
  padding: 0 18px;
  background: #fff;
  border-bottom: 1px solid #dfe4ec;
  flex-shrink: 0;
}

.builder-canvas-tab {
  height: 43px;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  border: 0;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: #647085;
  padding: 0 10px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}

.builder-canvas-tab.active {
  border-bottom-color: #111827;
  color: #111827;
}

.builder-canvas-tab em {
  min-width: 20px;
  height: 19px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: #edf2f8;
  color: #647085;
  font-size: 11px;
  font-style: normal;
  padding: 0 6px;
}

.preview-side-header {
  padding: 12px 18px;
  background: #fff;
  border-bottom: 1px solid #dfe4ec;
}

.preview-side-title {
  font-size: 15px;
  letter-spacing: 0;
}

.preview-side-cta {
  height: 29px;
  border-radius: 7px;
  background: #111827;
  box-shadow: none;
}

.preview-side-cta.secondary {
  border-color: #dbe2ea;
  background: #fff;
  color: #111827;
}

.preview-panel-collapse {
  width: 34px;
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid #dbe2ea;
  border-radius: 8px;
  background: #fff;
  color: #647085;
  cursor: pointer;
}

.preview-panel-collapse:hover {
  border-color: #cbd5e1;
  color: #111827;
}

.preview-panel-collapse svg {
  width: 16px;
  height: 16px;
}

.preview-body {
  background: #eef1f6;
}

.tab-content {
  padding: 24px 32px 36px;
}

.spec-tab-content {
  display: grid;
  gap: 16px;
}

.spec-overview-panel {
  max-width: 1280px;
  width: 100%;
  margin: 0 auto;
  padding: 18px;
  border: 1px solid #dbe2ea;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
  box-sizing: border-box;
  min-width: 0;
}

.spec-overview-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  padding-bottom: 14px;
  border-bottom: 1px solid #edf1f7;
}

.spec-overview-head h3 {
  margin: 3px 0 5px;
  color: #111827;
  font-size: 18px;
  line-height: 1.3;
}

.spec-overview-head p {
  margin: 0;
  color: #647085;
  font-size: 12px;
  line-height: 1.6;
}

.spec-score {
  flex-shrink: 0;
  min-width: 96px;
  border: 1px solid #dbe2ea;
  border-radius: 8px;
  background: #f8fafc;
  padding: 10px 12px;
  text-align: right;
}

.spec-score.complete {
  border-color: rgba(18, 185, 129, 0.28);
  background: #f0fdf7;
}

.spec-score strong {
  display: block;
  color: #111827;
  font-size: 22px;
  line-height: 1.1;
}

.spec-score span {
  display: block;
  margin-top: 4px;
  color: #647085;
  font-size: 11px;
  font-weight: 700;
}

.spec-overview-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-top: 14px;
}

.spec-overview-stat {
  min-width: 0;
  text-align: left;
  border: 1px solid #dbe2ea;
  border-radius: 8px;
  background: #f8fafc;
  padding: 12px;
  cursor: pointer;
}

.spec-overview-stat:hover {
  border-color: #b8c3d4;
  background: #fff;
}

.spec-overview-stat span {
  display: block;
  color: #111827;
  font-size: 24px;
  font-weight: 800;
  line-height: 1;
}

.spec-overview-stat strong {
  display: block;
  margin-top: 8px;
  color: #1f2937;
  font-size: 13px;
}

.spec-overview-stat em {
  display: block;
  margin-top: 4px;
  color: #8792a4;
  font-size: 11px;
  font-style: normal;
}

.spec-readiness-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 14px;
}

.spec-readiness-item {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 3px 8px;
  align-items: center;
  border: 1px solid #e3e8f0;
  border-radius: 8px;
  background: #fff;
  padding: 10px 12px;
}

.spec-readiness-item span {
  grid-row: span 2;
  align-self: flex-start;
  border-radius: 999px;
  background: #f3f6fb;
  color: #647085;
  padding: 2px 7px;
  font-size: 10px;
  font-weight: 800;
}

.spec-readiness-item.ready span {
  background: #ecfdf5;
  color: #059669;
}

.spec-readiness-item strong {
  min-width: 0;
  color: #111827;
  font-size: 12px;
}

.spec-readiness-item em {
  min-width: 0;
  color: #647085;
  font-size: 11px;
  font-style: normal;
  line-height: 1.45;
}

.doc-version-content.expanded.doc-preview-body {
  /* 跟随 preview-side 宽度自适应；超宽屏才限到 1280 保阅读舒适度 */
  width: 100%;
  max-width: 1280px;
  margin: 0 auto;
  padding: 28px clamp(16px, 3vw, 34px);
  border-radius: 8px;
  border: 1px solid #dbe2ea;
  background: #fff;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
  box-sizing: border-box;
  min-width: 0;
}

.builder-canvas-panel {
  max-width: 960px;
  margin: 24px auto 36px;
  padding: 0 24px;
}

.canvas-panel-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  margin-bottom: 14px;
}

.canvas-panel-head h3 {
  margin: 0;
  font-size: 16px;
  color: #111827;
}

.canvas-panel-head p {
  margin: 5px 0 0;
  color: #647085;
  font-size: 12px;
  line-height: 1.5;
}

.canvas-panel-head > span {
  border: 1px solid #dbe2ea;
  border-radius: 999px;
  background: #fff;
  color: #647085;
  padding: 4px 9px;
  font-size: 12px;
  font-weight: 700;
}

.canvas-model-grid,
.canvas-form-list,
.canvas-flow-list {
  display: grid;
  gap: 12px;
}

.canvas-model-grid {
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
}

.canvas-basic-grid {
  display: grid;
  grid-template-columns: minmax(220px, 0.9fr) minmax(320px, 1.1fr);
  gap: 12px;
}

.canvas-basic-section {
  display: grid;
  gap: 12px;
  align-content: start;
  border: 1px solid #dbe2ea;
  border-radius: 8px;
  background: #fff;
  padding: 14px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
}

.canvas-basic-section-head,
.canvas-dict-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}

.canvas-basic-section-head strong,
.canvas-dict-title strong,
.canvas-role-card strong {
  color: #111827;
  font-size: 13px;
}

.canvas-basic-section-head span {
  color: #8792a4;
  font-size: 12px;
  font-weight: 700;
}

.canvas-role-list,
.canvas-dict-list {
  display: grid;
  gap: 8px;
}

.canvas-role-card,
.canvas-dict-card {
  border: 1px solid #e3e8f0;
  border-radius: 8px;
  background: #f8fafc;
  padding: 10px 12px;
}

.canvas-role-card {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}

.canvas-role-card div {
  display: grid;
  gap: 5px;
  min-width: 0;
}

.canvas-role-card code,
.canvas-dict-title code {
  color: #647085;
  background: #edf2f8;
  border: 1px solid #e3e8f0;
  border-radius: 6px;
  padding: 2px 6px;
  font-size: 11px;
  width: fit-content;
}

.canvas-role-card > span {
  color: #647085;
  font-size: 12px;
  white-space: nowrap;
}

.canvas-dict-card {
  display: grid;
  gap: 10px;
}

.canvas-dict-options {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.canvas-dict-options span,
.canvas-dict-options em {
  border: 1px solid #e3e8f0;
  border-radius: 999px;
  padding: 3px 8px;
  color: #475569;
  background: #fff;
  font-size: 12px;
  font-style: normal;
}

.canvas-model-card,
.canvas-form-card,
.canvas-flow-group,
.code-panel-button {
  border: 1px solid #dbe2ea;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
}

.canvas-model-card,
.canvas-form-card,
.canvas-flow-group {
  padding: 14px;
}

.canvas-model-title,
.canvas-form-head,
.canvas-flow-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
}

.canvas-flow-title > div {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.canvas-model-title strong,
.canvas-form-head strong,
.canvas-flow-title strong {
  color: #111827;
  font-size: 13px;
}

.canvas-model-title code,
.canvas-form-head code,
.canvas-flow-title code {
  color: #647085;
  background: #f3f6fb;
  border: 1px solid #e3e8f0;
  border-radius: 6px;
  padding: 2px 6px;
  font-size: 11px;
  width: fit-content;
}

.canvas-model-meta {
  color: #647085;
  font-size: 12px;
  margin-bottom: 10px;
}

.canvas-field-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.canvas-field-list span {
  border: 1px solid #e3e8f0;
  border-radius: 999px;
  padding: 3px 8px;
  color: #475569;
  background: #f8fafc;
  font-size: 12px;
}

.canvas-flow-desc {
  margin: 0 0 10px;
  color: #647085;
  font-size: 12px;
  line-height: 1.6;
}

.canvas-flow-step {
  display: grid;
  grid-template-columns: 10px 1fr auto;
  align-items: center;
  gap: 8px;
  min-height: 28px;
  color: #475569;
  font-size: 12px;
}

.canvas-flow-step.business {
  align-items: flex-start;
  min-height: 34px;
  padding: 6px 0;
  border-top: 1px solid #edf1f7;
}

.canvas-flow-step.business > span:nth-child(2) {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.canvas-flow-step.business b {
  color: #1f2937;
  font-weight: 600;
}

.canvas-flow-step.business small {
  color: #647085;
  font-size: 11px;
}

.canvas-flow-step .flow-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: #a5adba;
}

.canvas-flow-step.completed .flow-dot {
  background: #12b981;
}

.canvas-flow-step.current .flow-dot,
.canvas-flow-step.running .flow-dot {
  background: #4f6bff;
}

.canvas-flow-step.error .flow-dot {
  background: #ef4444;
}

.canvas-flow-step em {
  color: #8792a4;
  font-size: 11px;
  font-style: normal;
}

.custom-dev-list {
  display: grid;
  gap: 12px;
}

.custom-dev-card {
  display: grid;
  gap: 12px;
  border: 1px solid #dbe2ea;
  border-radius: 8px;
  background: #fff;
  padding: 14px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
}

.custom-dev-card.muted {
  background: #f8fafc;
}

.custom-dev-card-head {
  display: flex;
  justify-content: space-between;
  gap: 14px;
  align-items: flex-start;
}

.custom-dev-card-head h4 {
  margin: 5px 0 0;
  color: #111827;
  font-size: 14px;
  line-height: 1.4;
}

.custom-dev-type,
.custom-dev-state {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
}

.custom-dev-type {
  height: 20px;
  padding: 0 8px;
  background: #edf2f8;
  color: #475569;
}

.custom-dev-state {
  height: 22px;
  border: 1px solid #dbe2ea;
  background: #fff;
  color: #647085;
  padding: 0 9px;
}

.custom-dev-meta {
  display: grid;
  gap: 8px;
  margin: 0;
}

.custom-dev-meta div {
  display: grid;
  grid-template-columns: 72px 1fr;
  gap: 10px;
  align-items: baseline;
}

.custom-dev-meta dt {
  color: #8792a4;
  font-size: 12px;
  font-weight: 700;
}

.custom-dev-meta dd {
  margin: 0;
  color: #475569;
  font-size: 12px;
  line-height: 1.6;
}

.custom-dev-empty {
  display: grid;
  gap: 10px;
  border: 1px dashed #cbd5e1;
  border-radius: 8px;
  background: #fff;
  padding: 18px;
}

.custom-dev-empty strong {
  color: #111827;
  font-size: 14px;
}

.custom-dev-empty span {
  color: #647085;
  font-size: 12px;
  line-height: 1.6;
}

.code-panel-button {
  height: 38px;
  justify-self: flex-start;
  padding: 0 14px;
  color: #fff;
  background: #111827;
  border-color: #111827;
  cursor: pointer;
  font-weight: 700;
}

.code-panel-button.secondary {
  color: #111827;
  background: #fff;
  border-color: #dbe2ea;
}

.code-panel-button:disabled {
  color: #8792a4;
  background: #f3f6fb;
  border-color: #dbe2ea;
  box-shadow: none;
  cursor: not-allowed;
}

.deploy-side {
  background: #fff;
  border-left-color: #dfe4ec;
}

.deploy-side.open {
  width: 300px;
  min-width: 300px;
}

@media (max-width: 1180px) {
  .builder-chat-phase-strip {
    height: auto;
    min-height: 42px;
    align-items: flex-start;
    flex-wrap: wrap;
    padding: 8px 14px;
  }

  .chat-side {
    flex-basis: 360px;
  }

  .builder-chat-phases {
    order: 3;
    flex-basis: 100%;
    overflow-x: auto;
  }
}

@media (max-width: 900px) {
  .builder-content {
    flex-direction: column;
  }

  .chat-side {
    flex: 0 0 44%;
    max-width: none;
    min-width: 0;
    border-right: 0;
    border-bottom: 1px solid #dfe4ec;
  }

  .builder-canvas-panel,
  .tab-content {
    padding-left: 14px;
    padding-right: 14px;
  }

  .spec-overview-head,
  .preview-side-header {
    flex-direction: column;
    align-items: stretch;
  }

  .spec-score {
    text-align: left;
  }

  .spec-overview-grid,
  .builder-spec-brief-stats,
  .spec-readiness-list {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .canvas-basic-grid {
    grid-template-columns: 1fr;
  }
}
</style>

<style>
html[data-theme="dark"] .chat-page,
html[data-theme="dark"] .content-area,
html[data-theme="dark"] .builder-content,
html[data-theme="dark"] .builder-result-side.preview-side,
html[data-theme="dark"] .preview-body {
  background: #090b10 !important;
  color: rgba(248, 250, 252, 0.94) !important;
}

html[data-theme="dark"] .chat-page .top-bar,
html[data-theme="dark"] .builder-chat-phase-strip,
html[data-theme="dark"] .builder-canvas-tabs,
html[data-theme="dark"] .preview-side-header {
  background: #0d1117 !important;
  border-color: rgba(148, 163, 184, 0.14) !important;
}

html[data-theme="dark"] .builder-chat-crumbs,
html[data-theme="dark"] .builder-chat-crumbs button,
html[data-theme="dark"] .builder-chat-save-state,
html[data-theme="dark"] .builder-chat-agent,
html[data-theme="dark"] .preview-side-status {
  color: rgba(203, 213, 225, 0.68) !important;
}

html[data-theme="dark"] .builder-chat-crumbs strong,
html[data-theme="dark"] .builder-chat-agent span,
html[data-theme="dark"] .preview-side-title,
html[data-theme="dark"] .builder-spec-brief-main strong,
html[data-theme="dark"] .spec-overview-head h3,
html[data-theme="dark"] .spec-score strong,
html[data-theme="dark"] .spec-overview-stat span,
html[data-theme="dark"] .spec-overview-stat strong,
html[data-theme="dark"] .spec-readiness-item strong,
html[data-theme="dark"] .canvas-panel-head h3,
html[data-theme="dark"] .canvas-basic-section-head strong,
html[data-theme="dark"] .canvas-role-card strong,
html[data-theme="dark"] .canvas-dict-title strong,
html[data-theme="dark"] .canvas-model-title strong,
html[data-theme="dark"] .canvas-form-head strong,
html[data-theme="dark"] .canvas-flow-title strong,
html[data-theme="dark"] .custom-dev-card-head h4,
html[data-theme="dark"] .custom-dev-empty strong {
  color: rgba(248, 250, 252, 0.94) !important;
}

html[data-theme="dark"] .builder-chat-agent code,
html[data-theme="dark"] .builder-canvas-tab em,
html[data-theme="dark"] .canvas-role-card code,
html[data-theme="dark"] .canvas-dict-title code,
html[data-theme="dark"] .canvas-model-title code,
html[data-theme="dark"] .canvas-form-head code,
html[data-theme="dark"] .canvas-flow-title code,
html[data-theme="dark"] .preview-app-code-chip {
  background: rgba(148, 163, 184, 0.10) !important;
  border-color: rgba(148, 163, 184, 0.14) !important;
  color: rgba(203, 213, 225, 0.70) !important;
}

html[data-theme="dark"] .mode-switcher,
html[data-theme="dark"] .builder-chat-phase,
html[data-theme="dark"] .builder-spec-brief-stats button,
html[data-theme="dark"] .spec-score,
html[data-theme="dark"] .spec-overview-stat,
html[data-theme="dark"] .spec-readiness-item,
html[data-theme="dark"] .canvas-basic-section,
html[data-theme="dark"] .canvas-role-card,
html[data-theme="dark"] .canvas-dict-card,
html[data-theme="dark"] .canvas-model-card,
html[data-theme="dark"] .canvas-form-card,
html[data-theme="dark"] .canvas-flow-group,
html[data-theme="dark"] .custom-dev-card,
html[data-theme="dark"] .custom-dev-empty,
html[data-theme="dark"] .doc-version-content.expanded.doc-preview-body {
  background: #111318 !important;
  border-color: rgba(148, 163, 184, 0.14) !important;
  box-shadow: none !important;
}

html[data-theme="dark"] .builder-spec-brief-stats button {
  color: rgba(203, 213, 225, 0.66) !important;
}

html[data-theme="dark"] .builder-spec-brief-stats span {
  color: #b6c2ff !important;
  opacity: 0.92 !important;
}

html[data-theme="dark"] .builder-spec-brief-stats button:hover {
  background: #151922 !important;
  border-color: rgba(124, 140, 255, 0.28) !important;
  color: rgba(248, 250, 252, 0.90) !important;
}

html[data-theme="dark"] .builder-canvas-tab {
  color: rgba(148, 163, 184, 0.72) !important;
}

html[data-theme="dark"] .builder-canvas-tab.active {
  background: rgba(124, 140, 255, 0.08) !important;
  border-bottom-color: #8b9aff !important;
  color: rgba(248, 250, 252, 0.94) !important;
}

html[data-theme="dark"] .builder-canvas-tab.active em {
  background: #8b9aff !important;
  border-color: #8b9aff !important;
  color: #090b10 !important;
}

html[data-theme="dark"] .mode-btn.active,
html[data-theme="dark"] .builder-chat-phase.active {
  background: #151922 !important;
  border-color: rgba(124, 140, 255, 0.26) !important;
  color: rgba(248, 250, 252, 0.88) !important;
  box-shadow: none !important;
}

html[data-theme="dark"] .builder-chat-phase.active span {
  background: #8b9aff !important;
  color: #090b10 !important;
}

html[data-theme="dark"] .spec-score.complete,
html[data-theme="dark"] .spec-readiness-item.ready {
  background: rgba(52, 211, 153, 0.08) !important;
  border-color: rgba(52, 211, 153, 0.18) !important;
}

html[data-theme="dark"] .builder-chat-phase.done {
  background: #111318 !important;
  border-color: rgba(148, 163, 184, 0.14) !important;
  color: rgba(203, 213, 225, 0.70) !important;
}

html[data-theme="dark"] .builder-chat-phase.done span {
  background: rgba(52, 211, 153, 0.12) !important;
  color: #7dd3a7 !important;
}

html[data-theme="dark"] .builder-top-action.artifact {
  background: transparent !important;
  border-color: rgba(148, 163, 184, 0.16) !important;
  color: rgba(203, 213, 225, 0.80) !important;
}

html[data-theme="dark"] .builder-top-action.artifact[aria-pressed="true"] {
  background: #202636 !important;
  border-color: rgba(148, 163, 184, 0.22) !important;
  color: rgba(248, 250, 252, 0.92) !important;
}

html[data-theme="dark"] .builder-content.artifacts-hidden .chat-side {
  background: transparent !important;
  border-color: transparent !important;
}

html[data-theme="dark"] .builder-content.artifacts-hidden .messages {
  background: transparent !important;
}

html[data-theme="dark"] .chat-side,
html[data-theme="dark"] .builder-spec-brief,
html[data-theme="dark"] .builder-workbench,
html[data-theme="dark"] .builder-composer-shell,
html[data-theme="dark"] .input-card,
html[data-theme="dark"] .deploy-side {
  background: #111318 !important;
  border-color: rgba(148, 163, 184, 0.14) !important;
  box-shadow: none !important;
}

html[data-theme="dark"] .builder-inline-model-select .el-select__wrapper {
  min-height: 28px !important;
  background: #151922 !important;
  border: 1px solid rgba(148, 163, 184, 0.16) !important;
  box-shadow: none !important;
}

html[data-theme="dark"] .builder-inline-model-select .el-select__wrapper.is-focused {
  border-color: rgba(124, 140, 255, 0.34) !important;
  box-shadow: 0 0 0 1px rgba(124, 140, 255, 0.16) inset !important;
}

html[data-theme="dark"] .builder-inline-model-select .el-select__selected-item,
html[data-theme="dark"] .builder-inline-model-select .el-select__placeholder,
html[data-theme="dark"] .builder-inline-model-select .el-select__caret,
html[data-theme="dark"] .builder-inline-model-select .el-icon {
  color: rgba(203, 213, 225, 0.78) !important;
  font-size: 12px !important;
}

html[data-theme="dark"] .doc-version-current-strip {
  background: linear-gradient(135deg, rgba(124, 140, 255, 0.12), #151922) !important;
  border-color: rgba(124, 140, 255, 0.30) !important;
  box-shadow: none !important;
}

html[data-theme="dark"] .doc-version-current-text strong,
html[data-theme="dark"] .doc-history-copy strong {
  color: rgba(248, 250, 252, 0.92) !important;
}

html[data-theme="dark"] .doc-version-current-text small,
html[data-theme="dark"] .doc-history-copy small,
html[data-theme="dark"] .doc-version-history-toggle span {
  color: rgba(148, 163, 184, 0.72) !important;
}

html[data-theme="dark"] .doc-version-current-badge,
html[data-theme="dark"] .doc-history-version {
  background: rgba(124, 140, 255, 0.18) !important;
  color: #b6c2ff !important;
}

html[data-theme="dark"] .doc-version-history-panel {
  background: #111318 !important;
  border-color: rgba(148, 163, 184, 0.14) !important;
  box-shadow: none !important;
}

html[data-theme="dark"] .doc-version-history-row + .doc-version-history-row {
  border-top-color: rgba(148, 163, 184, 0.12) !important;
}

html[data-theme="dark"] .doc-version-history-row:hover,
html[data-theme="dark"] .doc-version-history-row.active {
  background: rgba(124, 140, 255, 0.10) !important;
}

html[data-theme="dark"] .doc-version-action,
html[data-theme="dark"] .doc-version-history-toggle,
html[data-theme="dark"] .doc-version-mini-action {
  background: #151922 !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: rgba(248, 250, 252, 0.88) !important;
}

html[data-theme="dark"] .doc-version-action:hover,
html[data-theme="dark"] .doc-version-history-toggle:hover,
html[data-theme="dark"] .doc-version-mini-action:hover {
  border-color: rgba(124, 140, 255, 0.32) !important;
  background: rgba(124, 140, 255, 0.12) !important;
  color: #b6c2ff !important;
}

html[data-theme="dark"] .builder-control-hint.inside-card {
  color: rgba(148, 163, 184, 0.58) !important;
}

html[data-theme="dark"] .builder-workbench {
  background: linear-gradient(180deg, rgba(9, 11, 16, 0.20), #090b10) !important;
}

html[data-theme="dark"] .messages {
  background: #111318 !important;
}

html[data-theme="dark"] .bubble-content.assistant {
  background: #151922 !important;
  border-color: rgba(148, 163, 184, 0.16) !important;
  color: rgba(248, 250, 252, 0.92) !important;
}

html[data-theme="dark"] .chat-bubble.streaming-message .bubble-content.assistant {
  background:
    linear-gradient(90deg, rgba(124, 140, 255, 0.16), rgba(45, 212, 191, 0.08)),
    #151922 !important;
  border-color: rgba(124, 140, 255, 0.36) !important;
}

html[data-theme="dark"] .builder-top-action.primary,
html[data-theme="dark"] .preview-side-cta,
html[data-theme="dark"] .code-panel-button {
  background: #9aa8ff !important;
  border-color: #9aa8ff !important;
  color: #090b10 !important;
  box-shadow: none !important;
}

html[data-theme="dark"] .bubble-content.user {
  background: rgba(124, 140, 255, 0.16) !important;
  border: 1px solid rgba(124, 140, 255, 0.26) !important;
  color: rgba(248, 250, 252, 0.94) !important;
  box-shadow: none !important;
}

html[data-theme="dark"] .assistant-avatar {
  background: #202636 !important;
  border: 1px solid rgba(148, 163, 184, 0.16) !important;
  color: #b6c2ff !important;
  box-shadow: none !important;
}

html[data-theme="dark"] .builder-top-action.ghost,
html[data-theme="dark"] .preview-side-cta.secondary,
html[data-theme="dark"] .preview-panel-collapse,
html[data-theme="dark"] .code-panel-button.secondary,
html[data-theme="dark"] .doc-upload-btn.subtle,
html[data-theme="dark"] .doc-action-btn {
  background: #151922 !important;
  border-color: rgba(148, 163, 184, 0.18) !important;
  color: rgba(248, 250, 252, 0.88) !important;
}

html[data-theme="dark"] .input-card-top textarea,
html[data-theme="dark"] .conflict-input {
  color: rgba(248, 250, 252, 0.92) !important;
}

html[data-theme="dark"] .input-card:focus-within {
  border-color: rgba(124, 140, 255, 0.32) !important;
  box-shadow: 0 0 0 1px rgba(124, 140, 255, 0.18) inset !important;
}

html[data-theme="dark"] .input-card-top textarea::placeholder,
html[data-theme="dark"] .conflict-input::placeholder {
  color: rgba(148, 163, 184, 0.54) !important;
}

html[data-theme="dark"] .conflict-input,
html[data-theme="dark"] .deploy-inline-card,
html[data-theme="dark"] .doc-preview-card,
html[data-theme="dark"] .doc-preview-content,
html[data-theme="dark"] .doc-version-panel,
html[data-theme="dark"] .doc-version-empty,
html[data-theme="dark"] .doc-version-row,
html[data-theme="dark"] .doc-version-row.current,
html[data-theme="dark"] .doc-version-row.expanded,
html[data-theme="dark"] .structured-doc-panel,
html[data-theme="dark"] .deploy-log-card,
html[data-theme="dark"] .deploy-log-item,
html[data-theme="dark"] .deploy-log-item.info,
html[data-theme="dark"] .deploy-log-item.success,
html[data-theme="dark"] .deploy-log-item.error {
  background: #151922 !important;
  border-color: rgba(148, 163, 184, 0.14) !important;
  color: rgba(203, 213, 225, 0.72) !important;
  box-shadow: none !important;
}

html[data-theme="dark"] .preview-empty-title {
  color: rgba(248, 250, 252, 0.94) !important;
}

html[data-theme="dark"] .preview-empty-stage,
html[data-theme="dark"] .preview-empty-copy,
html[data-theme="dark"] .spec-overview-head p,
html[data-theme="dark"] .spec-readiness-item em,
html[data-theme="dark"] .builder-spec-brief-main p,
html[data-theme="dark"] .canvas-panel-head p,
html[data-theme="dark"] .canvas-basic-section-head span,
html[data-theme="dark"] .canvas-role-card > span,
html[data-theme="dark"] .canvas-model-meta,
html[data-theme="dark"] .canvas-flow-desc,
html[data-theme="dark"] .canvas-flow-step,
html[data-theme="dark"] .custom-dev-meta dt,
html[data-theme="dark"] .custom-dev-meta dd,
html[data-theme="dark"] .custom-dev-empty span {
  color: rgba(203, 213, 225, 0.66) !important;
}

html[data-theme="dark"] .preview-empty-features,
html[data-theme="dark"] .preview-empty-icon,
html[data-theme="dark"] .canvas-dict-options span,
html[data-theme="dark"] .canvas-dict-options em,
html[data-theme="dark"] .canvas-field-list span,
html[data-theme="dark"] .custom-dev-type,
html[data-theme="dark"] .custom-dev-state {
  background: rgba(148, 163, 184, 0.10) !important;
  border-color: rgba(148, 163, 184, 0.14) !important;
  color: rgba(203, 213, 225, 0.76) !important;
}
</style>
