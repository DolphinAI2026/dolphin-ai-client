<template>
  <WorkbenchShell>
  <div class="chat-page">
    <TopBar title="" show-back :show-home="false" back-to="/apps">
      <template #center>
        <div class="top-bar-center">
          <div v-if="builderAppDisplayName" class="top-bar-app-name" :title="builderAppDisplayName">
            {{ builderAppDisplayName }}
          </div>
          <div v-if="showViewSwitcher" class="mode-switcher">
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
            <button class="mode-btn" :class="{ active: activeView === 'coding' }" @click="setActiveView('coding')">
              <span class="mode-btn-icon" aria-hidden="true">
                <svg viewBox="0 0 16 16" fill="none">
                  <path d="M5.2 4.4L2.6 8l2.6 3.6M10.8 4.4L13.4 8l-2.6 3.6M9 3l-2 10" stroke="currentColor" stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
              </span>
              <span>智能开发</span>
            </button>
          </div>
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
      <div
        v-show="!SHOW_PLATFORM_CONFIG || activeView === 'builder'"
        class="builder-content"
        :class="{ 'single-pane': isPlatformDeployed && !isUpdateReviewMode }"
      >
      <!-- 左侧对话区 -->
      <div v-if="!isPlatformDeployed || isUpdateReviewMode" class="chat-side">
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
        <div v-else class="messages" ref="messagesRef">
          <div v-for="(msg, idx) in visibleMessages" :key="msg.id ?? `msg-${idx}`" class="chat-bubble" :class="msg.role">
            <div class="bubble-row" :class="msg.role">
              <div v-if="msg.role === 'assistant'" class="assistant-avatar" aria-hidden="true">AI</div>
              <div class="bubble-inner" :class="{ 'welcome-bubble': msg.role === 'assistant' && msg.content === BUILDER_WELCOME_MESSAGE }">
                <div class="bubble-content" :class="msg.role" v-html="formatContent(msg.content)"></div>
              </div>
            </div>
          </div>
          <div v-if="isTyping" class="chat-bubble assistant">
            <div class="bubble-row assistant">
              <div class="assistant-avatar" aria-hidden="true">AI</div>
              <div class="bubble-inner">
                <div class="bubble-content assistant">
                  <span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>
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
                    @change="handleChatImageChange"
                    style="display:none"
                  />
                  <svg width="18" height="18" viewBox="0 0 18 18" fill="none"><path d="M15.5 8.5l-6.4 6.4a3.5 3.5 0 01-5-5l6.4-6.4a2.2 2.2 0 013.1 3.1L7.2 13a.9.9 0 01-1.3-1.3l5.5-5.5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>
                </label>
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
                <button class="send-btn" :class="{ disabled: !canSendMessage }" @click="sendMessage">
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M14 2L7 9M14 2l-4.5 12-2-5.5L2 6.5 14 2z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>
                </button>
              </div>
              <div v-if="pendingChatAttachment" class="chat-attachment-preview">
                <img v-if="pendingChatAttachment.kind === 'image'" class="chat-attachment-preview-image" :src="pendingChatAttachment.previewUrl" :alt="pendingChatAttachment.file.name" />
                <div v-else class="chat-attachment-preview-file">📄</div>
                <div class="chat-attachment-preview-meta">
                  <div class="chat-attachment-preview-name">{{ pendingChatAttachment.file.name }}</div>
                  <div class="chat-attachment-preview-tip">{{ pendingChatAttachment.kind === 'image' ? '发送后会带着这张图片一起参与对话' : '发送后会带着这个附件一起参与对话' }}</div>
                </div>
                <button class="chat-attachment-remove" type="button" @click="clearPendingChatAttachment" aria-label="移除附件">×</button>
              </div>
            </div>
          </div>
          </div>

        </div>
      </div>

      <div class="preview-side builder-result-side">
        <div v-if="!showDeployedVersionedView || isUpdateReviewMode" class="preview-side-header">
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
              @click="triggerDocVersionUpload"
              :disabled="updatingDocVersion || executingChangePlan"
            >
              <svg class="cta-icon" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                <path d="M13.2 5.6A5.5 5.5 0 1 0 14 8" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
                <path d="M10.8 3.6h2.5v2.5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
              <span>{{ updatingDocVersion ? '分析更新中...' : '更新应用' }}</span>
            </button>
            <button
              v-if="showExecuteUpdateButton"
              class="preview-side-cta"
              @click="executeChangePlan"
              :disabled="executingChangePlan || !changePlanSelectedCount"
            >{{ executingChangePlan ? '更新中...' : '执行更新' }}</button>
            <button
              v-if="showStartDeployButton"
              class="preview-side-cta"
              @click="startDeployFlow()"
              :disabled="assembling || generating || deployRunningAll || deployExecuting !== null || !hasPreviewContent"
            >{{ generating || deployRunningAll || deployExecuting !== null ? '构建中...' : '开始构建' }}</button>
            <button
              v-if="showPublishButton"
              class="preview-side-cta success"
              @click="publishCurrentApp"
              :disabled="publishingApp || isAppOnline"
            >{{ publishingApp ? '上线中...' : isAppOnline ? '已上线' : '上线应用' }}</button>
          </div>
        </div>
        <div v-if="showBuilderPreview && isUpdateReviewMode" class="builder-step-bar">
          <button
            v-for="(tab, index) in visibleBuilderPreviewTabs"
            :key="tab.key"
            class="builder-step-item"
            :class="{ active: builderPreviewTab === tab.key, done: index < activeBuilderStepIndex }"
            @click="builderPreviewTab = tab.key"
          >
            <span class="builder-step-index">{{ index + 1 }}</span>
            <span class="builder-step-copy">
              <span class="builder-step-label">{{ tab.label }}</span>
              <span class="builder-step-meta">{{ getBuilderTabMeta(tab.key) }}</span>
            </span>
          </button>
        </div>
        <div class="preview-body">
          <div v-if="showBuilderPreview" class="tab-content">
            <!-- 正常模式：统一用标准文档结构渲染 -->
            <template v-if="!isUpdateReviewMode && !showDeployedVersionedView">
              <div v-if="liveStructuredDocResult" class="doc-version-content expanded doc-preview-body structured-doc-host">
                <StructuredDocRenderer :doc-result="liveStructuredDocResult" />
              </div>
              <pre v-else-if="selectedDocDisplayContent" class="doc-version-content expanded doc-preview-body plain-doc-fallback">{{ selectedDocDisplayContent }}</pre>
              <div v-else class="preview-empty small">暂无可展示的文档内容</div>
            </template>
            <!-- 更新审查/已部署版本模式：保留原有 tab 视图 -->
            <template v-else-if="builderPreviewTab === 'roles'">
              <template v-if="isUpdateReviewMode">
                <div v-if="updateRoleDiffItems.length === 0" class="preview-empty small">本次更新没有角色变更</div>
                <div v-for="(role, idx) in updateRoleDiffItems" :key="role.key" class="preview-item-card diff-preview-card">
                  <div class="preview-item-head">
                    <div>
                      <div class="preview-item-title-row">
                        <div class="preview-item-title">{{ idx + 1 }}. {{ role.name }}</div>
                        <span class="change-badge" :class="role.badge.tone">{{ role.badge.label }}</span>
                      </div>
                      <div class="preview-item-code">{{ role.code }}</div>
                    </div>
                  </div>
                  <div class="preview-item-desc">{{ role.description }}</div>
                </div>
              </template>
              <template v-else-if="showDeployedVersionedView">
                <div v-if="deployedRoleItems.length === 0" class="preview-empty small">暂无角色数据</div>
                <div
                  v-for="(role, idx) in deployedRoleItems"
                  :key="role.key"
                  class="preview-item-card versioned-card"
                  :class="{ 'history-muted-card': role.versionBadge.muted }"
                >
                  <div class="preview-item-head">
                    <div>
                      <div class="preview-item-title-row">
                        <div class="preview-item-title">{{ idx + 1 }}. {{ role.name }}</div>
                        <span class="version-badge" :class="role.versionBadge.tone">{{ role.versionBadge.label }}</span>
                      </div>
                      <div class="preview-item-code">{{ role.code || '未设置编码' }}</div>
                    </div>
                  </div>
                  <div class="preview-item-desc">{{ role.description }}</div>
                </div>
              </template>
              <template v-else>
                <div v-if="store.preview.roles.length === 0" class="preview-empty small">暂无角色数据</div>
                <div v-for="(role, idx) in store.preview.roles" :key="role.code || idx" class="preview-item-card">
                  <div class="preview-item-head">
                    <div>
                      <div class="preview-item-title">{{ idx + 1 }}. {{ role.name || role.code }}</div>
                      <div class="preview-item-code">{{ role.code || '未设置编码' }}</div>
                    </div>
                    <button class="builder-edit-link" @click="startSingleEdit('roles', role)" aria-label="修改角色">
                      <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
                        <path d="M3 11.75V13h1.25l7.18-7.18-1.25-1.25L3 11.75Z" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/>
                        <path d="M9.85 3.73 11.1 2.5a.88.88 0 0 1 1.25 1.25L11.1 5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>
                      </svg>
                    </button>
                  </div>
                  <div class="preview-item-desc">{{ getRoleDescription(role) }}</div>
                </div>
              </template>
            </template>

            <template v-else-if="builderPreviewTab === 'dicts'">
              <template v-if="isUpdateReviewMode">
                <div v-if="updateDictDiffItems.length === 0" class="preview-empty small">本次更新没有数据字典变更</div>
                <div v-for="(dict, idx) in updateDictDiffItems" :key="dict.key" class="preview-item-card diff-preview-card">
                  <div class="preview-item-head">
                    <div>
                      <div class="preview-item-title-row">
                        <div class="preview-item-title">{{ idx + 1 }}. {{ dict.name }}</div>
                        <span class="change-badge" :class="dict.badge.tone">{{ dict.badge.label }}</span>
                      </div>
                      <div class="preview-item-code">{{ dict.code }}</div>
                    </div>
                  </div>
                  <div class="dict-option-list">
                    <div v-for="option in dict.optionChanges" :key="option.key" class="dict-option-row diff">
                      <code class="dict-option-code">{{ option.code }}</code>
                      <span class="dict-option-name">{{ option.name }}</span>
                      <span class="change-badge mini" :class="option.badge.tone">{{ option.badge.label }}</span>
                    </div>
                  </div>
                </div>
              </template>
              <template v-else-if="showDeployedVersionedView">
                <div v-if="deployedDictItems.length === 0" class="preview-empty small">暂无数据字典</div>
                <div
                  v-for="(dict, idx) in deployedDictItems"
                  :key="dict.key"
                  class="preview-item-card versioned-card"
                  :class="{ 'history-muted-card': dict.versionBadge.muted }"
                >
                  <div class="preview-item-head">
                    <div>
                      <div class="preview-item-title-row">
                        <div class="preview-item-title">{{ idx + 1 }}. {{ dict.name }}</div>
                        <span class="version-badge" :class="dict.versionBadge.tone">{{ dict.versionBadge.label }}</span>
                      </div>
                      <div class="preview-item-code">{{ dict.code || '未设置编码' }}</div>
                    </div>
                  </div>
                  <div class="form-meta-row resource-meta-row">
                    <span class="form-meta-chip">{{ dict.optionCount }} 个选项</span>
                    <span class="form-meta-chip subtle">{{ dict.summary }}</span>
                  </div>
                  <div class="dict-option-list">
                    <div
                      v-for="option in dict.options"
                      :key="option.key"
                      class="dict-option-row versioned"
                      :class="{ 'history-muted-row': option.versionBadge.muted }"
                    >
                      <code class="dict-option-code">{{ option.code }}</code>
                      <span class="dict-option-name">{{ option.name }}</span>
                      <span class="version-badge mini" :class="option.versionBadge.tone">{{ option.versionBadge.label }}</span>
                    </div>
                  </div>
                </div>
              </template>
              <template v-else>
                <div v-if="store.preview.dicts.length === 0" class="preview-empty small">暂无数据字典</div>
                <div v-for="(dict, idx) in store.preview.dicts" :key="dict.code || idx" class="preview-item-card">
                  <div class="preview-item-head">
                    <div>
                      <div class="preview-item-title">{{ idx + 1 }}. {{ dict.name || dict.code }}</div>
                      <div class="preview-item-code">{{ dict.code || '未设置编码' }}</div>
                    </div>
                    <button class="builder-edit-link" @click="startSingleEdit('dicts', dict)" aria-label="修改字典">
                      <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
                        <path d="M3 11.75V13h1.25l7.18-7.18-1.25-1.25L3 11.75Z" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/>
                        <path d="M9.85 3.73 11.1 2.5a.88.88 0 0 1 1.25 1.25L11.1 5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>
                      </svg>
                    </button>
                  </div>
                  <div class="dict-option-list">
                    <div v-for="(opt, optIdx) in normalizeDictOptions(dict)" :key="opt.code || optIdx" class="dict-option-row">
                      <code class="dict-option-code">{{ opt.code }}</code>
                      <span class="dict-option-name">{{ opt.name }}</span>
                    </div>
                  </div>
                </div>
              </template>
            </template>

            <template v-else-if="builderPreviewTab === 'models'">
              <template v-if="isUpdateReviewMode">
                <div v-if="updateModelDiffItems.length === 0" class="preview-empty small">本次更新没有数据模型变更</div>
                <div v-for="(model, idx) in updateModelDiffItems" :key="model.key" class="model-card diff-model-card">
                  <div class="model-header">
                    <div class="model-title-stack">
                      <span class="model-name">{{ idx + 1 }}. {{ model.name }}</span>
                      <span class="model-summary">{{ model.summary }}</span>
                    </div>
                    <span class="model-code">{{ model.code }}</span>
                    <span class="change-badge" :class="model.badge.tone">{{ model.badge.label }}</span>
                  </div>
                  <div class="field-list">
                    <div v-for="field in model.fields" :key="field.key" class="field-row diff">
                      <div class="field-left">
                        <div class="field-icon">{{ getFieldIcon(field) }}</div>
                        <div class="field-text">
                          <span class="field-name">{{ field.name }}</span>
                          <span class="field-code">{{ field.code }}</span>
                        </div>
                      </div>
                      <div class="field-right">
                        <span class="ftype">{{ field.type }}</span>
                        <span class="change-badge mini" :class="field.badge.tone">{{ field.badge.label }}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </template>
              <template v-else-if="showDeployedVersionedView">
                <div v-if="deployedModelItems.length === 0" class="preview-empty small">暂无数据模型</div>
                <div
                  v-for="(model, idx) in deployedModelItems"
                  :key="model.key"
                  class="model-card versioned-card"
                  :class="{ 'history-muted-card': model.versionBadge.muted }"
                >
                  <div class="model-header">
                    <div class="model-title-stack">
                      <div class="preview-item-title-row">
                        <span class="model-name">{{ idx + 1 }}. {{ model.name }}</span>
                        <span class="version-badge" :class="model.versionBadge.tone">{{ model.versionBadge.label }}</span>
                      </div>
                      <span class="model-summary">{{ model.summary }}</span>
                    </div>
                    <span class="form-meta-chip subtle">{{ model.tableTypeLabel }}</span>
                    <span class="model-code">{{ model.code || '未设置编码' }}</span>
                  </div>
                  <div class="field-list">
                    <div
                      v-for="field in model.fields"
                      :key="field.key"
                      class="field-row versioned"
                      :class="{ 'history-muted-row': field.versionBadge.muted }"
                    >
                      <div class="field-left">
                        <div class="field-icon">{{ getFieldIcon(field) }}</div>
                        <div class="field-text">
                          <span class="field-name">{{ field.name }}</span>
                          <span class="field-code">{{ field.code }}</span>
                        </div>
                      </div>
                      <div class="field-right">
                        <span class="ftype">{{ field.type }}</span>
                        <span class="version-badge mini" :class="field.versionBadge.tone">{{ field.versionBadge.label }}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </template>
              <template v-else>
                <div v-if="store.preview.models.length === 0" class="preview-empty small">暂无数据模型</div>
                <div v-for="(model, idx) in store.preview.models" :key="model.code || idx" class="model-card">
                  <div class="model-header">
                    <span class="model-name">{{ idx + 1 }}. {{ model.name || model.code }}</span>
                    <span class="model-code">{{ model.code || '未设置编码' }}</span>
                    <button class="builder-edit-link inline" @click="startSingleEdit('models', model)" aria-label="修改模型">
                      <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
                        <path d="M3 11.75V13h1.25l7.18-7.18-1.25-1.25L3 11.75Z" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/>
                        <path d="M9.85 3.73 11.1 2.5a.88.88 0 0 1 1.25 1.25L11.1 5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>
                      </svg>
                    </button>
                  </div>
                  <div class="field-list">
                    <div v-for="(field, fieldIdx) in model.fields || []" :key="getFieldKey(field, fieldIdx)" class="field-row">
                      <div class="field-left">
                        <div class="field-icon">{{ getFieldIcon(field) }}</div>
                        <div class="field-text">
                          <span class="field-name">{{ getFieldLabel(field) }}</span>
                          <span class="field-code">{{ field.code || `field_${fieldIdx + 1}` }}</span>
                        </div>
                      </div>
                      <div class="field-right">
                        <span class="ftype">{{ field.type || '文本' }}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </template>
            </template>

            <template v-else-if="builderPreviewTab === 'forms'">
              <template v-if="isUpdateReviewMode">
                <div v-if="updateFormDiffItems.length === 0" class="preview-empty small">本次更新没有表单变更</div>
                <div v-for="(form, idx) in updateFormDiffItems" :key="form.key" class="preview-item-card form-preview-card diff-preview-card">
                  <div class="preview-item-head">
                    <div>
                      <div class="preview-item-title-row">
                        <div class="preview-item-title">{{ idx + 1 }}. {{ form.name }}</div>
                        <span class="change-badge" :class="form.badge.tone">{{ form.badge.label }}</span>
                      </div>
                      <div class="preview-item-code">{{ form.code }}</div>
                    </div>
                  </div>
                  <div class="form-meta-row">
                    <span v-if="form.modelCode" class="form-meta-chip">{{ form.modelCode }}</span>
                    <span class="form-meta-chip subtle">本次对比 {{ form.componentChanges.length }} 个组件变化</span>
                  </div>
                  <div class="form-change-list">
                    <div v-for="component in form.componentChanges" :key="component.key" class="form-change-row">
                      <div class="form-change-main">
                        <span class="form-change-name">{{ component.name }}</span>
                        <span class="form-change-detail">{{ component.detail }}</span>
                      </div>
                      <span class="change-badge mini" :class="component.badge.tone">{{ component.badge.label }}</span>
                    </div>
                  </div>
                </div>
              </template>
              <template v-else-if="showDeployedVersionedView">
                <div v-if="deployedFormItems.length === 0" class="preview-empty small">暂无表单配置</div>
                <div
                  v-for="(form, idx) in deployedFormItems"
                  :key="form.key"
                  class="preview-item-card form-preview-card versioned-card"
                  :class="{ 'history-muted-card': form.versionBadge.muted }"
                >
                  <div class="preview-item-head">
                    <div>
                      <div class="preview-item-title-row">
                        <div class="preview-item-title">{{ idx + 1 }}. {{ form.name }}</div>
                        <span class="version-badge" :class="form.versionBadge.tone">{{ form.versionBadge.label }}</span>
                      </div>
                      <div class="preview-item-code">{{ form.code || '未设置编码' }}</div>
                    </div>
                  </div>
                  <div class="form-meta-row resource-meta-row">
                    <span v-if="form.modelName" class="form-meta-chip">{{ form.modelName }}</span>
                    <span v-if="form.modelCode" class="form-meta-chip subtle">{{ form.modelCode }}</span>
                    <span class="form-meta-chip subtle">{{ form.tableTypeLabel }}</span>
                    <span class="form-meta-chip subtle">{{ form.componentCount }} 个组件</span>
                  </div>
                  <div class="form-change-list">
                    <div
                      v-for="component in form.components"
                      :key="component.key"
                      class="form-change-row versioned"
                      :class="{ 'history-muted-row': component.versionBadge.muted }"
                    >
                      <div class="form-change-main">
                        <span class="form-change-name">{{ component.name }}</span>
                        <span class="form-change-detail">{{ component.detail }}</span>
                      </div>
                      <span class="version-badge mini" :class="component.versionBadge.tone">{{ component.versionBadge.label }}</span>
                    </div>
                  </div>
                </div>
              </template>
              <template v-else>
                <div v-if="formPreviewItems.length === 0" class="preview-empty small">暂无表单配置</div>
                <div v-for="(form, idx) in formPreviewItems" :key="form.code || idx" class="preview-item-card form-preview-card">
                  <div class="preview-item-head">
                    <div>
                      <div class="preview-item-title">{{ idx + 1 }}. {{ form.name }}</div>
                      <div class="preview-item-code">{{ form.code }}</div>
                    </div>
                    <button class="builder-edit-link" @click="startSingleEdit('forms', form)" aria-label="修改表单">
                      <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
                        <path d="M3 11.75V13h1.25l7.18-7.18-1.25-1.25L3 11.75Z" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/>
                        <path d="M9.85 3.73 11.1 2.5a.88.88 0 0 1 1.25 1.25L11.1 5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>
                      </svg>
                    </button>
                  </div>
                  <div class="form-meta-row">
                    <span class="form-meta-chip">{{ form.modelName }}</span>
                    <span class="form-meta-chip subtle">{{ form.tableTypeLabel }}</span>
                  </div>
                  <div class="form-preview">
                    <div class="form-title">{{ form.name }} 预览</div>
                    <div class="form-fields-grid">
                      <div
                        v-for="(field, fieldIdx) in form.previewFields"
                        :key="field.code || fieldIdx"
                        class="form-field"
                        :class="{ 'full-width': field.fullWidth }"
                      >
                        <div class="form-label">{{ field.name }}</div>
                        <div class="form-mock" :class="{ tall: field.fullWidth }">
                          <span>{{ field.mockText }}</span>
                          <span class="mock-arrow">{{ field.mockIcon }}</span>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </template>
            </template>

            <template v-else-if="builderPreviewTab === 'permissions'">
              <div v-if="permissionPreviewItems.length === 0" class="preview-empty small">暂无权限配置</div>
              <div v-for="(perm, idx) in permissionPreviewItems" :key="perm.code || idx" class="perm-card">
                <div class="perm-header">
                  <div class="perm-heading-block">
                    <span>{{ idx + 1 }}. {{ perm.name }}</span>
                    <span class="perm-code-text">{{ perm.code }}</span>
                  </div>
                  <button class="builder-edit-link inline" @click="startSingleEdit('permissions', perm.raw)" aria-label="修改权限">
                    <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
                      <path d="M3 11.75V13h1.25l7.18-7.18-1.25-1.25L3 11.75Z" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/>
                      <path d="M9.85 3.73 11.1 2.5a.88.88 0 0 1 1.25 1.25L11.1 5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>
                    </svg>
                  </button>
                </div>
                <table class="perm-table">
                  <thead>
                    <tr><th>角色</th><th>表单权限</th><th>可操作数据</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, rowIdx) in perm.rows" :key="`${perm.code}-${row.roleCode}-${rowIdx}`">
                      <td>{{ row.roleName }}</td>
                      <td>{{ row.actionsText }}</td>
                      <td><span class="data-tag" :class="row.scopeClass">{{ row.scopeText }}</span></td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </template>

            <template v-else>
              <div class="doc-versions-tab">
                <div class="doc-version-panel list-only">
                  <div class="doc-upload-bar">
                    <div>
                      <div class="doc-tab-title with-icon">
                        <span class="doc-title-icon" aria-hidden="true">
                          <svg viewBox="0 0 16 16" fill="none">
                            <path d="M5 2.5h4l2.5 2.5v7a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1Z" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/>
                            <path d="M9 2.5V5h2.5" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/>
                          </svg>
                        </span>
                        <span>设计文档版本记录</span>
                      </div>
                      <div v-if="currentDocVersionItem" class="doc-tab-subtitle">
                        {{ currentDocVersionItem.filename || '未命名文档' }}
                        <span class="doc-tab-meta-sep">·</span>
                        {{ formatDocTime(currentDocVersionItem.created_at) || '当前解析结果' }}
                      </div>
                      <div v-else class="doc-tab-subtitle">当前设计文档由 JSON 直接渲染生成。</div>
                    </div>
                    <div class="doc-top-actions">
                      <button
                        v-if="showUpdateButton"
                        class="doc-action-btn"
                        type="button"
                        @click="triggerDocVersionUpload"
                        :disabled="updatingDocVersion || executingChangePlan"
                      >{{ updatingDocVersion ? '分析更新中...' : '更新应用' }}</button>
                      <button
                        v-if="showPublishButton"
                        class="doc-action-btn primary"
                        type="button"
                        @click="publishCurrentApp"
                        :disabled="publishingApp || isAppOnline"
                      >{{ publishingApp ? '上线中...' : isAppOnline ? '已上线' : '上线应用' }}</button>
                    </div>
                  </div>

                  <div v-if="docVersionsLoading" class="doc-version-empty">正在加载版本记录...</div>
                  <div v-else-if="displayDocVersions.length > 1" class="doc-version-history">
                    <div class="doc-version-list compact">
                      <div
                        v-for="ver in displayDocVersions"
                        :key="ver.key"
                        class="doc-version-row"
                        :class="{ current: getDocDisplayVersion(ver) === currentDocVersion, expanded: isDocVersionExpanded(ver) }"
                      >
                        <div class="doc-version-summary">
                          <button class="doc-version-toggle" type="button" @click="toggleDocVersion(ver)">
                            <span class="doc-ver-icon" aria-hidden="true">
                              <svg viewBox="0 0 16 16" fill="none">
                                <path d="M5 2.5h4l2.5 2.5v7a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1Z" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/>
                                <path d="M9 2.5V5h2.5" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/>
                              </svg>
                            </span>
                            <div class="doc-version-main">
                              <div class="doc-ver-header">
                                <span class="doc-ver-num">V{{ getDocDisplayVersion(ver) }}</span>
                                <span class="doc-ver-filename">{{ getDocDisplayFilename(ver) || `设计文档-V${getDocDisplayVersion(ver)}.md` }}</span>
                                <span v-if="getDocDisplayVersion(ver) === currentDocVersion" class="doc-ver-current">当前</span>
                              </div>
                              <div class="doc-ver-meta">
                                <span class="doc-ver-time">{{ formatDocTime(ver.created_at) || '刚刚更新' }}</span>
                                <span class="doc-ver-summary">{{ ver.summary || '点击查看版本内容' }}</span>
                              </div>
                            </div>
                          </button>
                          <div class="doc-ver-actions">
                            <button
                              class="doc-action-btn"
                              type="button"
                              @click.stop="selectDocVersion(ver)"
                            >查看</button>
                            <button
                              v-if="canCompareDocVersion(ver)"
                              class="doc-action-btn diff"
                              type="button"
                              @click.stop="openDocDiff(ver)"
                            >对比</button>
                            <button
                              v-if="showVersionManager && !ver.isVirtual"
                              class="doc-action-btn danger"
                              type="button"
                              :disabled="deletingDocVersionId === ver.id"
                              @click.stop="deleteDocVersion(ver)"
                            >{{ deletingDocVersionId === ver.id ? '删除中...' : '删除' }}</button>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div v-if="!currentDocVersionItem" class="doc-version-empty">暂无可展示的设计文档</div>
                  <div v-else class="doc-current-panel">
                    <div class="doc-current-head">
                      <div class="doc-current-badge">当前文档</div>
                      <div class="doc-current-tools">
                        <button
                          v-if="selectedDocDisplayContent"
                          class="doc-action-btn"
                          type="button"
                          @click="openCurrentDocFullscreen"
                        >全屏</button>
                      </div>
                    </div>
                    <div v-if="liveStructuredDocResult" class="doc-version-content expanded doc-preview-body structured-doc-host">
                      <StructuredDocRenderer :doc-result="liveStructuredDocResult" />
                    </div>
                    <pre v-else-if="selectedDocDisplayContent" class="doc-version-content expanded doc-preview-body plain-doc-fallback">{{ selectedDocDisplayContent }}</pre>
                    <div v-else class="doc-version-empty">暂无可展示的设计文档内容</div>
                  </div>
                </div>
              </div>
            </template>
          </div>
          <div v-else class="preview-empty preview-empty-stage" :class="{ parsing: isDocParsing }">
            <template v-if="isDocParsing">
              <div class="parsing-spinner"></div>
              <div class="preview-empty-title">正在解析文档...</div>
              <div class="preview-empty-copy">{{ docParsingStep || 'AI 正在分析文档内容，请稍候' }}</div>
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

      <aside v-if="showDeploySidebar" class="deploy-side" :class="{ open: deployOpen || isUpdateReviewMode || isUpdateExecutionMode }">
        <div class="deploy-header">
          <div>
            <div class="deploy-title-row">
              <div class="deploy-title">{{ isUpdateExecutionMode ? '更新进度' : isUpdateReviewMode ? '更新概览' : '部署进度' }}</div>
              <span v-if="isUpdateExecutionMode || currentDeployStep" class="deploy-live-badge">执行中</span>
            </div>
            <div class="deploy-desc">
              {{ isUpdateExecutionMode
                ? (updateExecutionAllDone ? '本次更新已执行完成' : '仅展示本次增量更新涉及的步骤')
                : isUpdateReviewMode
                ? (store.changePlan?.diffSummary || '本次仅展示与上一版设计文档对比出的更新项')
                : (deployAllDone ? '已完成全部部署步骤' : deployRunningAll || deployExecuting ? '正在自动执行部署步骤' : deployOpen ? '确认环境后会自动执行部署步骤' : '点击开始构建后在这里查看进度')
              }}
            </div>
            <div v-if="isUpdateExecutionMode && currentUpdateExecutionLabel" class="deploy-current-step">{{ currentUpdateExecutionLabel }}</div>
            <div v-else-if="currentDeployStep" class="deploy-current-step">{{ currentDeployStep.label }}</div>
          </div>
          <button v-if="!isUpdateReviewMode && !isUpdateExecutionMode" class="deploy-close" @click="deployOpen = false" aria-label="关闭部署面板">×</button>
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
          <div class="deploy-conflict-title">构建失败</div>
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
    </div><!-- /builder-content -->
    </div><!-- /content-area -->

    <!-- Modals (在 chat-page 根元素下) -->
    <ConnectModal v-model="store.showConnectModal" />
    <EnvSelectModal v-model="showEnvSelect" @selected="onEnvSelected" />
    <input ref="docVersionInputRef" type="file" accept=".md,text/markdown" hidden @change="handleDocVersionInputChange" />
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
  </div><!-- /chat-page -->
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
import { platformEnvApi } from '@/api/platformEnv'
import request from '@/utils/request'
import { buildPlatformProxyEntryUrl, repairPlatformIframe } from '@/utils/platformIframe'
import type { Message } from '@/types'
import TopBar from '@/components/TopBar.vue'
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import StructuredDocRenderer from '@/components/StructuredDocRenderer.vue'
import StructuredDocDiffRenderer from '@/components/StructuredDocDiffRenderer.vue'
import { llmConfigApi, type BuilderModelOption } from '@/api/llmConfig'
import { requirementsApi } from '@/api/requirements'
import { convertConfig } from '@/api/conversation'
import { buildStructuredDocFromPreviewConfig } from '@/utils/structuredDoc'
import { computeStructuredDocDiff } from '@/utils/structuredDocDiff'

const router = useRouter()
const route = useRoute()
const store = usePreviewStore()
const userStore = useUserStore()
const builderPreviewTab = ref<'roles' | 'dicts' | 'models' | 'forms' | 'permissions' | 'docs'>('docs')
const allBuilderPreviewTabs = [
  { key: 'roles', label: '角色' },
  { key: 'dicts', label: '数据字典' },
  { key: 'models', label: '数据模型' },
  { key: 'forms', label: '表单' },
  { key: 'permissions', label: '权限' },
  { key: 'docs', label: '文档' },
] as const
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
const currentDocAppCode = computed(() => {
  const content = String(selectedDocDisplayContent.value || latestDocContent.value || chatGeneratedDocContent.value || '').trim()
  return content ? extractAppCodeFromText(content) : ''
})
const displayAppCode = computed(() => currentDocAppCode.value || parsedAppCode.value || loadedAppCode.value || buildAppCode(store.preview.appName))
const currentPreviewConfigPayload = computed(() => ({
  ...store.preview,
  appName: store.preview.appName || '',
  appCode: parsedAppCode.value || loadedAppCode.value || currentDocAppCode.value || buildAppCode(store.preview.appName),
}))
function formatParseMetaSummary(meta: any) {
  const score = Number(meta?.standard_score ?? meta?.score)
  if (!Number.isFinite(score)) return ''
  return `文档标准度：${score} 分`
}

function docExportComponentTypeLabel(value: any, modelType?: any) {
  const labels: Record<string, string> = {
    FORM_DOCUMENT_NUMBER: '单据号',
    FORM_TEXT_INPUT: '单行输入',
    FORM_TEXTAREA_INPUT: '多行输入',
    FORM_TEXTAREA: '多行输入',
    FORM_PHONE_INPUT: '手机号码',
    FORM_EMAIL_INPUT: '电子邮箱',
    FORM_SELECT_INPUT_SINGLE: '下拉单选',
    FORM_SELECT_INPUT: '下拉多选',
    FORM_SELECT: '下拉单选',
    FORM_SELECT_MULTI: '下拉多选',
    FORM_DATA_SELECTOR_SINGLE: '数据单选',
    FORM_DATA_SELECTOR: '数据选择',
    FORM_DATEPICK_INPUT: '日期时间',
    FORM_DATE_PICKER: '日期时间',
    FORM_MONEY_INPUT: '金额',
    FORM_NUMBER_INPUT: '数字',
    FORM_FILE_UPLOAD: '附件上传',
    FORM_UPLOAD: '附件上传',
    FORM_SWITCH_SELECT: '开关',
    FORM_SWITCH: '开关',
    FORM_PEOPLE_SELECT: '人员选择',
    FORM_USER_SELECT: '人员选择',
    FORM_DEPARTMENT_SELECT: '部门选择',
    FORM_DEPT_SELECT: '部门选择',
    FORM_WIDGET_LOCATION: '地理位置',
    FORM_WIDGET_SON_TABLE: '子表',
    FORM_RADIO_INPUT: '单选框',
    FORM_RADIO: '单选框',
    FORM_CHECKBOX_INPUT: '复选框',
    FORM_CHECKBOX: '复选框',
    FORM_RICH_TEXT: '富文本',
    FORM_HYPERLINK_INPUT: '超链接',
    FORM_LINK: '超链接',
    FORM_IDCARD_INPUT: '身份证号',
    FORM_ID_CARD: '身份证号',
    FORM_WIDGET_AREA: '地区地址',
    FORM_LOCATION: '地理位置',
    FORM_ADDRESS: '地区地址',
    FORM_ASSOCIATION: '关联表单',
    FORM_SERIAL: '单据号',
  }
  const raw = String(value || '').trim()
  const modelLabel = String(modelType || '').trim()
  const label = labels[raw] || raw || modelLabel || '-'
  if (label === '单行输入' && modelLabel && modelLabel !== '单行输入') return modelLabel
  return label
}

function docExportFieldCode(modelField: any) {
  const raw = String(modelField || '').trim()
  return raw.includes('.') ? raw.split('.').pop() || '' : raw
}

function docExportBool(value: any) {
  return value ? '是' : '否'
}

function isSubTableComponent(component: any) {
  return String(component?.componentType || component?.component_type || '').trim() === 'FORM_WIDGET_SON_TABLE'
}

function docExportModelMaps(models: any[]) {
  const modelsByCode = new Map<string, any>()
  const fieldsByModel = new Map<string, Map<string, any>>()
  ;(models || []).forEach((model: any) => {
    const modelCode = String(model?.code || '')
    if (!modelCode) return
    modelsByCode.set(modelCode, model)
    const fieldMap = new Map<string, any>()
    ;(model?.fields || []).forEach((field: any) => {
      const fieldCode = String(field?.code || '')
      if (fieldCode) fieldMap.set(fieldCode, field)
    })
    fieldsByModel.set(modelCode, fieldMap)
  })
  return { modelsByCode, fieldsByModel }
}

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
const visibleBuilderPreviewTabs = computed(() =>
  isUpdateReviewMode.value
    ? allBuilderPreviewTabs.filter(tab => tab.key !== 'permissions')
    : allBuilderPreviewTabs.filter(tab => tab.key === 'docs')
)
const activeBuilderTabLabel = computed(() => visibleBuilderPreviewTabs.value.find(tab => tab.key === builderPreviewTab.value)?.label || '角色')
const activeBuilderStepIndex = computed(() => Math.max(0, visibleBuilderPreviewTabs.value.findIndex(tab => tab.key === builderPreviewTab.value)))
const getBuilderTabCount = (tabKey: typeof builderPreviewTab.value) => {
  if (isUpdateReviewMode.value) {
    if (tabKey === 'roles') return updateRoleDiffItems.value.length
    if (tabKey === 'dicts') return updateDictDiffItems.value.length
    if (tabKey === 'models') return updateModelDiffItems.value.length
    if (tabKey === 'forms') return updateFormDiffItems.value.length
    if (tabKey === 'permissions') return 0
    return docPreviewAvailable.value ? 1 : 0
  }
  if (showDeployedVersionedView.value) {
    if (tabKey === 'roles') return deployedRoleItems.value.length
    if (tabKey === 'dicts') return deployedDictItems.value.length
    if (tabKey === 'models') return deployedModelItems.value.length
    if (tabKey === 'forms') return deployedFormItems.value.length
    if (tabKey === 'permissions') return permissionPreviewItems.value.length
    return docPreviewAvailable.value ? 1 : 0
  }
  if (tabKey === 'roles') return store.preview.roles.length
  if (tabKey === 'dicts') return store.preview.dicts.length
  if (tabKey === 'models') return store.preview.models.length
  if (tabKey === 'forms') return formPreviewItems.value.length
  if (tabKey === 'permissions') return permissionPreviewItems.value.length
  return docPreviewAvailable.value ? 1 : 0
}
const getBuilderTabMeta = (tabKey: typeof builderPreviewTab.value) => {
  const count = getBuilderTabCount(tabKey)
  return count > 0 ? `${count} 项` : '待补充'
}
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
const isAppOnline = computed(() =>
  currentRemoteStatus.value === 'ENABLE' ||
  currentRemoteStatus.value === '已上线'
)
const isAppPublishing = computed(() => {
  const status = String(currentRemoteStatus.value || '').toLowerCase()
  return status.includes('publish') || status.includes('上线中') || status.includes('publishing')
})
const showStartDeployButton = computed(() => !deployAllDone.value && !isPlatformDeployed.value)
const showPublishButton = computed(() =>
  isPlatformDeployed.value &&
  !isUpdateReviewMode.value &&
  !isAppPublishing.value
)
const showUpdateButton = computed(() => !!existingAppId.value && isPlatformDeployed.value && !isUpdateReviewMode.value)
const showExecuteUpdateButton = computed(() => isUpdateReviewMode.value && !!store.changePlan?.actions?.length)
const showBuilderComposer = computed(() => !isPlatformDeployed.value || isUpdateReviewMode.value)
const showDeployProgressInline = computed(() => deploySteps.value.length > 0 || deployOpen.value || isPlatformDeployed.value)
const showDeployedVersionedView = computed(() => isPlatformDeployed.value && !isUpdateReviewMode.value)
const showDeploySidebar = computed(() =>
  isUpdateReviewMode.value ||
  isUpdateExecutionMode.value ||
  !showDeployedVersionedView.value
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
const builderQuickPlaceholder = computed(() => `补充或修改${activeBuilderTabLabel.value}内容，例如：把${activeBuilderTabLabel.value}再细化一下...`)
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
        previewFields: components.slice(0, 6).map((component: any, fieldIdx: number) => ({
          name: component?.label || component?.name || component?.code || `字段${fieldIdx + 1}`,
          code: component?.code || `field_${fieldIdx + 1}`,
          fullWidth: ['textarea', '文本域', '描述', '备注', 'rich'].some((keyword) => String(component?.componentType || component?.label || '').toLowerCase().includes(String(keyword).toLowerCase())),
          mockText: ['date', '日期', 'time', '时间'].some((keyword) => String(component?.componentType || '').toLowerCase().includes(String(keyword).toLowerCase()))
            ? '请选择'
            : ['select', 'enum', '字典', '下拉', 'radio', 'checkbox'].some((keyword) => String(component?.componentType || '').toLowerCase().includes(String(keyword).toLowerCase()))
              ? '请选择选项'
              : ['number', '金额', '数值'].some((keyword) => String(component?.componentType || '').toLowerCase().includes(String(keyword).toLowerCase()))
                ? '请输入数值'
                : '请输入内容',
          mockIcon: ['date', '日期', 'time', '时间', 'select', 'enum', '字典', '下拉'].some((keyword) => String(component?.componentType || '').toLowerCase().includes(String(keyword).toLowerCase())) ? '▾' : ''
        }))
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

const deployedRoleItems = computed<VersionedRoleItem[]>(() => {
  const roleMap = new Map<string, VersionedRoleItem>()
  const latestVersion = normalizeVersionNumber(currentDocVersion.value, 1)
  const ensureRoleItem = (source: any, fallbackCode: string, version: number, tone: VersionBadgeMeta['tone']) => {
    const code = getRoleCodeValue(source, fallbackCode)
    const existing = roleMap.get(code)
    const nextItem: VersionedRoleItem = {
      key: existing?.key || `deployed-role-${code}`,
      name: getRoleNameValue(source, existing?.name || code || '未命名角色'),
      code,
      description: getRoleDescription(source || existing || {}),
      versionBadge: buildVersionBadge(tone, version),
    }
    roleMap.set(code, nextItem)
    return nextItem
  }

  completedChangePlans.value.forEach((plan: any) => {
    const version = normalizeVersionNumber(plan?.toVersion, 1)
    const roleChanges = Array.isArray(plan?.resourceDiff?.role_changes) ? plan.resourceDiff.role_changes : []
    roleChanges.forEach((change: any, idx: number) => {
      const source = change?.new_value || change?.old_value || {}
      const code = getRoleCodeValue(source, change?.code || `role_${version}_${idx + 1}`)
      const tone = getVersionToneForChange(change?.change_type, 'role')
      ensureRoleItem({
        ...source,
        code,
        name: getPrimaryText(change?.name, source?.name, source?.roleName),
        description: getRoleDescription(source || change?.old_value || {}),
      }, code, version, tone)
    })
  })

  store.preview.roles.forEach((role: any, idx: number) => {
    ensureRoleItem(role, `role_${idx + 1}`, latestVersion, 'active')
  })

  return sortVersionedItems(Array.from(roleMap.values()))
})

const deployedDictItems = computed<VersionedDictItem[]>(() => {
  const dictMap = new Map<string, {
    key: string
    name: string
    code: string
    versionBadge: VersionBadgeMeta
    optionsMap: Map<string, VersionedDictOptionItem>
  }>()
  const latestVersion = normalizeVersionNumber(currentDocVersion.value, 1)

  const ensureDictItem = (source: any, fallbackCode: string, version: number, tone: VersionBadgeMeta['tone']) => {
    const code = getDictCodeValue(source, fallbackCode)
    const existing = dictMap.get(code)
    const item = existing || {
      key: `deployed-dict-${code}`,
      name: getDictNameValue(source, code || '未命名字典'),
      code,
      versionBadge: buildVersionBadge(tone, version),
      optionsMap: new Map<string, VersionedDictOptionItem>(),
    }
    item.name = getDictNameValue(source, item.name || code || '未命名字典')
    item.code = code
    item.versionBadge = buildVersionBadge(tone, version)
    dictMap.set(code, item)
    return item
  }
  const ensureDictOptionItem = (
    dictItem: { optionsMap: Map<string, VersionedDictOptionItem>; versionBadge: VersionBadgeMeta },
    source: any,
    fallbackCode: string,
    version: number,
    tone: VersionBadgeMeta['tone'],
  ) => {
    const code = getDictOptionCodeValue(source, fallbackCode)
    const existing = dictItem.optionsMap.get(code)
    dictItem.optionsMap.set(code, {
      key: existing?.key || `${code}-${version}`,
      name: getDictOptionNameValue(source, existing?.name || code || '未命名选项'),
      code,
      versionBadge: buildVersionBadge(tone, version),
    })
    if (tone === 'active' && !dictItem.versionBadge.muted) {
      dictItem.versionBadge = buildVersionBadge('active', version)
    }
  }

  completedChangePlans.value.forEach((plan: any) => {
    const version = normalizeVersionNumber(plan?.toVersion, 1)
    const dictChanges = Array.isArray(plan?.resourceDiff?.dict_changes) ? plan.resourceDiff.dict_changes : []
    dictChanges.forEach((change: any, idx: number) => {
      const tone = getVersionToneForChange(change?.change_type, 'dict')
      const source = change?.new_value || change?.old_value || {}
      const code = getDictCodeValue(source, change?.code || `dict_${version}_${idx + 1}`)
      const dictItem = ensureDictItem({
        ...source,
        code,
        name: getPrimaryText(change?.name, source?.name, source?.dictionaryName),
      }, code, version, tone)

      if (String(change?.change_type || '').toLowerCase() === 'added') {
        normalizeDictOptions(change?.new_value || source).forEach((option: any, optionIdx: number) => {
          ensureDictOptionItem(dictItem, option, `opt_${optionIdx + 1}`, version, 'active')
        })
      }

      if (String(change?.change_type || '').toLowerCase() === 'deleted') {
        const deletedOptions = normalizeDictOptions(change?.old_value || source)
        if (!dictItem.optionsMap.size) {
          deletedOptions.forEach((option: any, optionIdx: number) => {
            ensureDictOptionItem(dictItem, option, `opt_${optionIdx + 1}`, version, 'disabled')
          })
        }
        markNestedItemsAsMuted(dictItem.optionsMap, 'disabled', version)
        return
      }

      const optionChanges = Array.isArray(change?.option_changes) ? change.option_changes : []
      optionChanges.forEach((optionChange: any, optionIdx: number) => {
        const optionTone = getVersionToneForChange(optionChange?.change_type, 'dict_option')
        const optionSource = optionChange?.new_value || optionChange?.old_value || {}
        ensureDictOptionItem(dictItem, {
          ...optionSource,
          code: getPrimaryText(optionChange?.code, optionSource?.code, optionSource?.item_code),
          name: getPrimaryText(optionChange?.name, optionSource?.name, optionSource?.item_name),
        }, optionChange?.code || `opt_${version}_${optionIdx + 1}`, version, optionTone)
      })
    })
  })

  store.preview.dicts.forEach((dict: any, idx: number) => {
    const dictItem = ensureDictItem(dict, `dict_${idx + 1}`, latestVersion, 'active')
    normalizeDictOptions(dict).forEach((option: any, optionIdx: number) => {
      ensureDictOptionItem(dictItem, option, `opt_${optionIdx + 1}`, latestVersion, 'active')
    })
  })

  return sortVersionedItems(Array.from(dictMap.values()).map((item) => {
    const options = sortVersionedItems(Array.from(item.optionsMap.values()))
    return {
      key: item.key,
      name: item.name,
      code: item.code,
      versionBadge: item.versionBadge,
      options,
      optionCount: options.length,
      summary: options.length ? options.map(option => option.name).slice(0, 6).join('、') + (options.length > 6 ? ` 等 ${options.length} 项` : '') : '暂无选项',
    }
  }))
})

const deployedModelItems = computed<VersionedModelItem[]>(() => {
  const modelMap = new Map<string, {
    key: string
    name: string
    code: string
    tableTypeLabel: string
    versionBadge: VersionBadgeMeta
    fieldsMap: Map<string, VersionedModelFieldItem>
  }>()
  const latestVersion = normalizeVersionNumber(currentDocVersion.value, 1)

  const ensureModelItem = (source: any, fallbackCode: string, version: number, tone: VersionBadgeMeta['tone']) => {
    const code = getModelCodeValue(source, fallbackCode)
    const existing = modelMap.get(code)
    const item = existing || {
      key: `deployed-model-${code}`,
      name: getModelNameValue(source, code || '未命名模型'),
      code,
      tableTypeLabel: getTableTypeLabel(source?.table_type || source?.tableType || source?.type),
      versionBadge: buildVersionBadge(tone, version),
      fieldsMap: new Map<string, VersionedModelFieldItem>(),
    }
    item.name = getModelNameValue(source, item.name || code || '未命名模型')
    item.code = code
    item.tableTypeLabel = getTableTypeLabel(source?.table_type || source?.tableType || source?.type)
    item.versionBadge = buildVersionBadge(tone, version)
    modelMap.set(code, item)
    return item
  }
  const ensureModelFieldItem = (
    modelItem: { fieldsMap: Map<string, VersionedModelFieldItem>; versionBadge: VersionBadgeMeta },
    source: any,
    fallbackCode: string,
    version: number,
    tone: VersionBadgeMeta['tone'],
  ) => {
    const code = getFieldCodeValue(source, fallbackCode)
    const existing = modelItem.fieldsMap.get(code)
    modelItem.fieldsMap.set(code, {
      key: existing?.key || `${code}-${version}`,
      name: getFieldNameValue(source, existing?.name || code || '未命名字段'),
      code,
      type: getFieldTypeValue(source),
      versionBadge: buildVersionBadge(tone, version),
    })
    if (tone === 'active' && !modelItem.versionBadge.muted) {
      modelItem.versionBadge = buildVersionBadge('active', version)
    }
  }

  completedChangePlans.value.forEach((plan: any) => {
    const version = normalizeVersionNumber(plan?.toVersion, 1)
    const modelChanges = Array.isArray(plan?.resourceDiff?.model_changes) ? plan.resourceDiff.model_changes : []
    modelChanges.forEach((change: any, idx: number) => {
      const tone = getVersionToneForChange(change?.change_type, 'model')
      const source = change?.new_value || change?.old_value || {}
      const code = getModelCodeValue(source, change?.code || `model_${version}_${idx + 1}`)
      const modelItem = ensureModelItem({
        ...source,
        code,
        name: getPrimaryText(change?.name, source?.name, source?.modelName),
      }, code, version, tone)

      if (String(change?.change_type || '').toLowerCase() === 'added') {
        getModelFieldSource(change?.new_value || source).forEach((field: any, fieldIdx: number) => {
          ensureModelFieldItem(modelItem, field, `field_${fieldIdx + 1}`, version, 'active')
        })
      }

      if (String(change?.change_type || '').toLowerCase() === 'deleted') {
        const deletedFields = getModelFieldSource(change?.old_value || source)
        if (!modelItem.fieldsMap.size) {
          deletedFields.forEach((field: any, fieldIdx: number) => {
            ensureModelFieldItem(modelItem, field, `field_${fieldIdx + 1}`, version, 'disabled')
          })
        }
        markNestedItemsAsMuted(modelItem.fieldsMap, 'disabled', version)
        return
      }

      const fieldChanges = Array.isArray(change?.field_changes) ? change.field_changes : []
      fieldChanges.forEach((fieldChange: any, fieldIdx: number) => {
        const fieldTone = getVersionToneForChange(fieldChange?.change_type, 'field')
        const fieldSource = fieldChange?.new_value || fieldChange?.old_value || {}
        ensureModelFieldItem(modelItem, {
          ...fieldSource,
          code: getPrimaryText(fieldChange?.code, fieldSource?.code, fieldSource?.fieldCode),
          name: getPrimaryText(fieldChange?.name, fieldSource?.name, fieldSource?.fieldName),
          type: getPrimaryText(fieldChange?.field_type, fieldSource?.fieldType, fieldSource?.type),
        }, fieldChange?.code || `field_${version}_${fieldIdx + 1}`, version, fieldTone)
      })
    })
  })

  store.preview.models.forEach((model: any, idx: number) => {
    const modelItem = ensureModelItem(model, `model_${idx + 1}`, latestVersion, 'active')
    getModelFieldSource(model).forEach((field: any, fieldIdx: number) => {
      ensureModelFieldItem(modelItem, field, `field_${fieldIdx + 1}`, latestVersion, 'active')
    })
  })

  return sortVersionedItems(Array.from(modelMap.values()).map((item) => {
    const fields = sortVersionedItems(Array.from(item.fieldsMap.values()))
    return {
      key: item.key,
      name: item.name,
      code: item.code,
      tableTypeLabel: item.tableTypeLabel,
      versionBadge: item.versionBadge,
      fields,
      summary: `${item.tableTypeLabel} · ${fields.length} 个字段`,
    }
  }))
})

const deployedFormItems = computed<VersionedFormItem[]>(() => {
  const formMap = new Map<string, {
    key: string
    name: string
    code: string
    modelName: string
    modelCode: string
    tableTypeLabel: string
    versionBadge: VersionBadgeMeta
    componentsMap: Map<string, VersionedFormComponentItem>
  }>()
  const latestVersion = normalizeVersionNumber(currentDocVersion.value, 1)

  const ensureFormItem = (source: any, fallbackCode: string, version: number, tone: VersionBadgeMeta['tone']) => {
    const code = getFormCodeValue(source, fallbackCode)
    const existing = formMap.get(code)
    const item = existing || {
      key: `deployed-form-${code}`,
      name: getFormNameValue(source, code || '未命名表单'),
      code,
      modelName: getPrimaryText(source?.modelName, source?.model_name),
      modelCode: getFormModelCodeValue(source),
      tableTypeLabel: getTableTypeLabel(source?.table_type || source?.tableType || source?.type),
      versionBadge: buildVersionBadge(tone, version),
      componentsMap: new Map<string, VersionedFormComponentItem>(),
    }
    item.name = getFormNameValue(source, item.name || code || '未命名表单')
    item.code = code
    item.modelName = getPrimaryText(source?.modelName, source?.model_name, item.modelName)
    item.modelCode = getFormModelCodeValue(source, item.modelCode)
    item.tableTypeLabel = getTableTypeLabel(source?.table_type || source?.tableType || source?.type)
    item.versionBadge = buildVersionBadge(tone, version)
    formMap.set(code, item)
    return item
  }
  const ensureFormComponentItem = (
    formItem: { componentsMap: Map<string, VersionedFormComponentItem>; versionBadge: VersionBadgeMeta },
    source: any,
    fallbackCode: string,
    version: number,
    tone: VersionBadgeMeta['tone'],
  ) => {
    const code = getFormComponentCodeValue(source, fallbackCode)
    const existing = formItem.componentsMap.get(code)
    formItem.componentsMap.set(code, {
      key: existing?.key || `${code}-${version}`,
      name: getFormComponentNameValue(source, existing?.name || code || '未命名组件'),
      code,
      detail: getFormComponentDetailValue(source),
      versionBadge: buildVersionBadge(tone, version),
    })
    if (tone === 'active' && !formItem.versionBadge.muted) {
      formItem.versionBadge = buildVersionBadge('active', version)
    }
  }

  completedChangePlans.value.forEach((plan: any) => {
    const version = normalizeVersionNumber(plan?.toVersion, 1)
    const formChanges = Array.isArray(plan?.resourceDiff?.form_changes) ? plan.resourceDiff.form_changes : []
    formChanges.forEach((change: any, idx: number) => {
      const tone = getVersionToneForChange(change?.change_type, 'form')
      const source = change?.new_value || change?.old_value || {}
      const code = getFormCodeValue(source, change?.code || `form_${version}_${idx + 1}`)
      const formItem = ensureFormItem({
        ...source,
        code,
        name: getPrimaryText(change?.name, source?.name, source?.formName),
        modelCode: getPrimaryText(change?.model_code, source?.modelCode, source?.model_code),
      }, code, version, tone)

      if (String(change?.change_type || '').toLowerCase() === 'added') {
        getFormComponentSource(change?.new_value || source).forEach((component: any, componentIdx: number) => {
          ensureFormComponentItem(formItem, component, `component_${componentIdx + 1}`, version, 'active')
        })
      }

      if (String(change?.change_type || '').toLowerCase() === 'deleted') {
        const deletedComponents = getFormComponentSource(change?.old_value || source)
        if (!formItem.componentsMap.size) {
          deletedComponents.forEach((component: any, componentIdx: number) => {
            ensureFormComponentItem(formItem, component, `component_${componentIdx + 1}`, version, 'deleted')
          })
        }
        markNestedItemsAsMuted(formItem.componentsMap, 'deleted', version)
        return
      }

      const componentChanges = Array.isArray(change?.component_changes) ? change.component_changes : []
      componentChanges.forEach((componentChange: any, componentIdx: number) => {
        const componentTone = getVersionToneForChange(componentChange?.change_type, 'component')
        const componentSource = componentChange?.new_value || componentChange?.old_value || {}
        ensureFormComponentItem(formItem, {
          ...componentSource,
          code: getPrimaryText(componentChange?.code, componentSource?.code, componentSource?.model_field),
          name: getPrimaryText(componentChange?.name, componentSource?.name, componentSource?.label),
          model_field: getPrimaryText(componentChange?.model_field, componentSource?.model_field),
          table_model_code: getPrimaryText(componentChange?.table_model_code, componentSource?.table_model_code),
          component_type: getPrimaryText(componentChange?.component_type, componentSource?.component_type),
          changed_properties: componentChange?.changed_properties,
        }, componentChange?.code || `component_${version}_${componentIdx + 1}`, version, componentTone)
      })
    })
  })

  store.preview.models
    .filter((model: any) => !/sub|child|子表/.test(String(model?.table_type || model?.type || '').toLowerCase()))
    .forEach((model: any, idx: number) => {
    const modelCode = getModelCodeValue(model, `model_${idx + 1}`)
    const formItem = ensureFormItem({
      name: getPrimaryText(model?.form_name, model?.name),
      code: getPrimaryText(model?.form_code, model?.code, `form_${idx + 1}`),
      modelName: getPrimaryText(model?.name, model?.form_name),
      modelCode,
      table_type: model?.table_type || model?.type,
    }, `form_${idx + 1}`, latestVersion, 'active')
    getModelFieldSource(model).forEach((field: any, fieldIdx: number) => {
      ensureFormComponentItem(formItem, {
        code: getFieldCodeValue(field, `component_${fieldIdx + 1}`),
        name: getFieldNameValue(field, `组件${fieldIdx + 1}`),
        model_field: `${modelCode}.${getFieldCodeValue(field, `field_${fieldIdx + 1}`)}`,
        component_type: getFieldTypeValue(field),
      }, `component_${fieldIdx + 1}`, latestVersion, 'active')
    })
  })

  return sortVersionedItems(Array.from(formMap.values()).map((item) => {
    const components = sortVersionedItems(Array.from(item.componentsMap.values()))
    return {
      key: item.key,
      name: item.name,
      code: item.code,
      modelName: item.modelName,
      modelCode: item.modelCode,
      tableTypeLabel: item.tableTypeLabel,
      versionBadge: item.versionBadge,
      components,
      componentCount: components.length,
    }
  }))
})

const updateReviewGroups = computed(() => [
  { title: '角色', icon: '👥', items: updateRoleDiffItems.value },
  { title: '数据字典', icon: '📖', items: updateDictDiffItems.value },
  { title: '数据模型', icon: '🗃', items: updateModelDiffItems.value },
  { title: '表单配置', icon: '📋', items: updateFormDiffItems.value },
].filter(group => group.items.length > 0))

const getPreferredUpdateTab = () => {
  if (updateModelDiffItems.value.length) return 'models'
  if (updateRoleDiffItems.value.length) return 'roles'
  if (updateDictDiffItems.value.length) return 'dicts'
  if (updateFormDiffItems.value.length) return 'forms'
  return 'docs'
}

const BUILDER_WELCOME_MESSAGE = '你好！我是你的智能搭建助手。\n告诉我你想搭建什么，我会帮你梳理需求、生成设计文档，并引导你完成完整搭建流程。\n可以直接描述业务需求，也可以上传原型图或设计稿开始。'
function createWelcomeMessage(): Message {
  return {
    id: Date.now(),
    role: 'assistant',
    agent: 'requirements',
    content: BUILDER_WELCOME_MESSAGE,
    created_at: ''
  }
}

function resetMessagesToWelcome() {
  messages.splice(0, messages.length)
  messages.push(createWelcomeMessage())
}

function isAutoDocSummaryMessage(content: string) {
  const text = String(content || '').trim()
  if (!text) return false
  if (!text.startsWith('我已经理解了设计文档《')) return false
  return text.includes('识别出：')
    && (text.includes('你可以告诉我需要调整的地方')
      || text.includes('或者直接说"开始生成"')
      || text.includes('或者直接点击"开始生成"'))
}

const visibleMessages = computed(() => messages)

const focusQuickInput = () => {
  nextTick(() => {
    inputRef.value?.focus()
  })
}

const startSingleEdit = (tab: typeof builderPreviewTab.value, payload: any) => {
  if (isUpdateReviewMode.value) {
    ElMessage.info('更新页面当前为变更对比视图，不支持直接编辑，请重新上传设计文档。')
    return
  }
  builderPreviewTab.value = tab
  const targetName = payload?.name || payload?.form || payload?.table || payload?.code || activeBuilderTabLabel.value
  inputText.value = `请帮我修改${activeBuilderTabLabel.value}「${targetName}」：`
  focusQuickInput()
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
const pendingChatAttachment = ref<{ file: File; kind: 'image' | 'file'; previewUrl: string } | null>(null)
const canSendMessage = computed(() => (!!inputText.value.trim() || !!pendingChatAttachment.value) && !sendingMessage.value)

const escapeHtml = (value: string) => String(value || '')
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')
  .replace(/'/g, '&#39;')

const buildUserChatAttachmentContent = (
  text: string,
  attachment: { file: File; kind: 'image' | 'file'; previewUrl: string }
) => {
  const parts: string[] = []
  if (text.trim()) parts.push(escapeHtml(text.trim()))
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
  return parts.join('\n\n')
}

const triggerChatImageUpload = () => {
  chatImageInputRef.value?.click()
}

const clearPendingChatAttachment = () => {
  if (pendingChatAttachment.value?.previewUrl) {
    URL.revokeObjectURL(pendingChatAttachment.value.previewUrl)
  }
  pendingChatAttachment.value = null
  if (chatImageInputRef.value) chatImageInputRef.value.value = ''
}

const attachPendingAttachmentFile = (file: File, kind: 'image' | 'file') => {
  const maxSize = kind === 'image' ? 10 * 1024 * 1024 : 20 * 1024 * 1024
  if (file.size > maxSize) {
    ElMessage.warning(kind === 'image' ? '图片大小请控制在 10MB 以内' : '附件大小请控制在 20MB 以内')
    return false
  }
  clearPendingChatAttachment()
  pendingChatAttachment.value = {
    file,
    kind,
    previewUrl: kind === 'image' ? URL.createObjectURL(file) : '',
  }
  return true
}

const handleChatImageChange = (event: Event) => {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  const lowerName = file.name.toLowerCase()

  if (lowerName.endsWith('.md') || lowerName.endsWith('.markdown')) {
    handleDocUpload(event)
    return
  }

  if (file.type.startsWith('image/')) {
    attachPendingAttachmentFile(file, 'image')
    target.value = ''
    return
  }

  attachPendingAttachmentFile(file, 'file')
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
  return appId ? `${base}/coding?app_id=${appId}&embed_nav=0` : `${base}/coding?embed_nav=0`
})

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
    if (String(detail).includes('重新连接APaaS平台') || String(detail).includes('Token已过期或无效')) {
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
    activeView.value = view
  }
  if (existingAppId.value) {
    localStorage.setItem(getAppViewStorageKey(existingAppId.value), view)
  }
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

  const savedView = (route.query.view as string) || localStorage.getItem(getAppViewStorageKey(app.id)) || 'builder'
  // platform 不作为默认恢复视图，进来始终先展示智能搭建
  activeView.value = savedView === 'coding' ? 'coding' : 'builder'
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
const normalizeVersionNumber = (value: any, fallback = 1) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback
}
const buildVersionBadge = (tone: VersionBadgeMeta['tone'], version: any): VersionBadgeMeta => {
  const normalizedVersion = normalizeVersionNumber(version, 1)
  if (tone === 'active') {
    return {
      label: `最新 V${normalizedVersion}`,
      tone,
      version: normalizedVersion,
      muted: false,
    }
  }
  return {
    label: `${tone === 'deleted' ? '删除' : '禁用'} V${normalizedVersion}`,
    tone,
    version: normalizedVersion,
    muted: true,
  }
}
const getVersionToneForChange = (
  changeType: string,
  scope: Parameters<typeof getChangeBadgeMeta>[1],
): VersionBadgeMeta['tone'] => {
  const badge = getChangeBadgeMeta(changeType, scope)
  if (badge.tone === 'delete') return 'deleted'
  if (badge.tone === 'disable') return 'disabled'
  return 'active'
}
const sortVersionedItems = <T extends { name?: string; code?: string; versionBadge: VersionBadgeMeta }>(items: T[]) =>
  [...items].sort((a, b) => {
    if (a.versionBadge.muted !== b.versionBadge.muted) {
      return a.versionBadge.muted ? 1 : -1
    }
    if (a.versionBadge.version !== b.versionBadge.version) {
      return b.versionBadge.version - a.versionBadge.version
    }
    return String(a.name || a.code || '').localeCompare(String(b.name || b.code || ''), 'zh-Hans-CN', { numeric: true })
  })
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
const markNestedItemsAsMuted = (
  items: Map<string, { versionBadge: VersionBadgeMeta }>,
  tone: VersionBadgeMeta['tone'],
  version: number,
) => {
  items.forEach((item) => {
    item.versionBadge = buildVersionBadge(tone, version)
  })
}
const completedPlanRefsFromVersions = (versions: any[]) => {
  const refs: Array<{ id: number; fromVersion: number; toVersion: number }> = []
  const seen = new Set<number>()
  versions.forEach((versionItem: any) => {
    const plans = Array.isArray(versionItem?.change_plans) ? versionItem.change_plans : []
    plans.forEach((plan: any) => {
      const planId = Number(plan?.id)
      if (!planId || seen.has(planId)) return
      if (String(plan?.status || '').toLowerCase() !== 'completed') return
      seen.add(planId)
      refs.push({
        id: planId,
        fromVersion: normalizeVersionNumber(plan?.from_version, 0),
        toVersion: normalizeVersionNumber(plan?.to_version, 1),
      })
    })
  })
  return refs.sort((a, b) => (a.toVersion - b.toVersion) || (a.fromVersion - b.fromVersion) || (a.id - b.id))
}

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
interface VersionBadgeMeta {
  label: string
  tone: 'active' | 'deleted' | 'disabled'
  version: number
  muted: boolean
}
interface VersionedRoleItem {
  key: string
  name: string
  code: string
  description: string
  versionBadge: VersionBadgeMeta
}
interface VersionedDictOptionItem {
  key: string
  name: string
  code: string
  versionBadge: VersionBadgeMeta
}
interface VersionedDictItem {
  key: string
  name: string
  code: string
  summary: string
  optionCount: number
  options: VersionedDictOptionItem[]
  versionBadge: VersionBadgeMeta
}
interface VersionedModelFieldItem {
  key: string
  name: string
  code: string
  type: string
  versionBadge: VersionBadgeMeta
}
interface VersionedModelItem {
  key: string
  name: string
  code: string
  tableTypeLabel: string
  summary: string
  fields: VersionedModelFieldItem[]
  versionBadge: VersionBadgeMeta
}
interface VersionedFormComponentItem {
  key: string
  name: string
  code: string
  detail: string
  versionBadge: VersionBadgeMeta
}
interface VersionedFormItem {
  key: string
  name: string
  code: string
  modelName: string
  modelCode: string
  tableTypeLabel: string
  componentCount: number
  components: VersionedFormComponentItem[]
  versionBadge: VersionBadgeMeta
}
const docVersions = ref<DocVersion[]>([])
const docVersionsLoading = ref(false)
const updatingDocVersion = ref(false)
const executingChangePlan = ref(false)
const completedChangePlans = ref<any[]>([])
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

const resolveDocDisplayContent = (item?: Pick<DocVersion, 'version' | 'raw_content' | 'parsed_config'> | null) => {
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

const selectedDocDisplayContent = computed(() => resolveDocDisplayContent(selectedDocVersionItem.value))
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

const loadCompletedChangePlans = async (appId: number, docVersionResponse?: any) => {
  if (!appId) {
    completedChangePlans.value = []
    return []
  }
  try {
    const payload = docVersionResponse || await applicationApi.getDocVersions(appId)
    const { versions } = getDocVersionsPayload(payload)
    const planRefs = completedPlanRefsFromVersions(versions)
    if (!planRefs.length) {
      completedChangePlans.value = []
      return []
    }

    const details = await Promise.all(planRefs.map(async (planRef) => {
      try {
        const detail = await applicationApi.getChangePlan(appId, planRef.id)
        const normalized = normalizeChangePlanState(detail)
        if (!normalized) return null
        return {
          ...normalized,
          fromVersion: planRef.fromVersion || normalized.fromVersion,
          toVersion: planRef.toVersion || normalized.toVersion,
        }
      } catch (error) {
        console.error(`Failed to fetch completed change plan ${planRef.id}`, error)
        return null
      }
    }))

    completedChangePlans.value = details
      .filter(Boolean)
      .sort((a: any, b: any) => (normalizeVersionNumber(a?.toVersion, 1) - normalizeVersionNumber(b?.toVersion, 1)))
    return completedChangePlans.value
  } catch (error) {
    console.error('Failed to load completed change plans', error)
    completedChangePlans.value = []
    return []
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

const isUpdateReviewMode = computed(() =>
  !!existingAppId.value && !!store.changePlan
)
const updateResourceDiff = computed<any | null>(() => {
  const diff = store.changePlan?.resourceDiff
  return diff && typeof diff === 'object' ? diff : null
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
    await loadCompletedChangePlans(appId, verRes)
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
      parseReady.value = store.preview.models.length > 0
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
  completedChangePlans.value = []
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
    builderPreviewTab.value = getPreferredUpdateTab()
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
    ElMessage.error(e?.response?.data?.detail || e?.message || '删除版本失败')
  } finally {
    deletingDocVersionId.value = null
  }
}

const triggerDocVersionUpload = () => {
  if (!existingAppId.value) return
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

function suggestNextConflictCode(code: string) {
  const source = String(code || '').trim()
  if (!source) return 'codeV1'
  const matched = source.match(/^(.*?)(?:V(\d+))$/i)
  if (matched) {
    const prefix = matched[1] || source
    const version = Number(matched[2] || '0')
    return `${prefix}V${version + 1}`
  }
  return `${source}V1`
}

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
    if (!/^开始自动构建$|^开始执行：/u.test(log.message)) return log
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
    content: `⚠️ 检测到${payload.modelName}编码冲突：\`${payload.currentCode}\` 已存在。\n\n我先暂停当前构建。你可以确认建议编码 \`${suggestedCode}\`，也可以改成你想要的新编码，确认后我会继续构建。`,
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

function buildAppCode(name: string): string {
  const source = (name || '').trim()
  if (!source) return 'app_builder'

  const phraseMap: Array<[RegExp, string]> = [
    [/档案管理系统|档案管理平台/g, 'archive_mgmt'],
    [/客户管理系统|客户管理平台/g, 'customer_mgmt'],
    [/报销管理系统|报销管理平台/g, 'expense_mgmt'],
    [/请假管理系统|请假管理平台/g, 'leave_mgmt'],
    [/合同管理系统|合同管理平台/g, 'contract_mgmt'],
    [/项目管理系统|项目管理平台/g, 'project_mgmt'],
    [/采购管理系统|采购管理平台/g, 'purchase_mgmt'],
    [/库存管理系统|库存管理平台/g, 'inventory_mgmt'],
    [/员工管理系统|人事管理系统/g, 'employee_mgmt'],
    [/工单管理系统|售后工单系统/g, 'ticket_mgmt'],
  ]
  for (const [pattern, code] of phraseMap) {
    if (pattern.test(source)) return code
  }

  const tokenMap: Array<[RegExp, string]> = [
    [/档案/g, 'archive'],
    [/文档/g, 'document'],
    [/知识库/g, 'knowledge'],
    [/客户/g, 'customer'],
    [/用户/g, 'user'],
    [/会员/g, 'member'],
    [/员工|人事/g, 'employee'],
    [/部门/g, 'department'],
    [/报销|费用/g, 'expense'],
    [/请假|休假/g, 'leave'],
    [/考勤/g, 'attendance'],
    [/合同/g, 'contract'],
    [/采购/g, 'purchase'],
    [/库存/g, 'inventory'],
    [/商品/g, 'product'],
    [/订单/g, 'order'],
    [/销售/g, 'sales'],
    [/项目/g, 'project'],
    [/任务/g, 'task'],
    [/审批/g, 'approval'],
    [/流程/g, 'workflow'],
    [/工单|售后/g, 'ticket'],
    [/设备|资产/g, 'asset'],
    [/财务/g, 'finance'],
    [/管理|平台|系统/g, 'mgmt'],
  ]

  const parts: string[] = []
  for (const [pattern, token] of tokenMap) {
    if (pattern.test(source) && !parts.includes(token)) {
      parts.push(token)
    }
  }

  if (parts.length > 0) {
    const code = parts.slice(0, 3).join('_').replace(/_mgmt_mgmt$/, '_mgmt')
    return code.startsWith('mgmt') ? `app_${code}` : code
  }

  const ascii = source
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
  if (ascii) return ascii
  return 'app_builder'
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
    /\|\s*应用编码\s*\|\s*`?([A-Za-z][A-Za-z0-9_-]{1,63})`?\s*\|/i,
    /\|\s*App\s*Code\s*\|\s*`?([A-Za-z][A-Za-z0-9_-]{1,63})`?\s*\|/i,
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
  completedChangePlans.value = []

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
  store.preview.permissions = []
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
    if (deploySteps.value.length > 0) {
      deployOpen.value = true
    }
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
    content: `❌ 构建失败\n\n步骤：${stepLabel}\n原因：${detail}`,
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
    if (String(detail).includes('重新连接APaaS平台') || String(detail).includes('Token已过期或无效')) {
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

async function deployRunAll() {
  if (!deployAppId.value || deployRunningAll.value || deployExecuting.value !== null || deployAllDone.value) return

  resetExecutionLogs()
  deployRunningAll.value = true
  deployLastError.value = ''
  appendExecutionLog('info', '开始自动构建')
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
    appendExecutionLog('success', '全部部署步骤已完成')
    ElMessage.success('全部完成！')
  } catch (e: any) {
    const detail = e?.response?.data?.detail || e?.message || '失败'
    if (String(detail).includes('重新连接APaaS平台') || String(detail).includes('Token已过期或无效')) {
      ElMessage.warning('平台登录已失效，请先重新连接平台环境')
      store.showConnectModal = true
    } else {
      persistDeployError(currentDeployStep.value?.label || '自动构建', detail)
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
        }
        if (resolveResp?.app_code) {
          loadedAppCode.value = resolveResp.app_code
          parsedAppCode.value = resolveResp.app_code
        }
        parseReady.value = store.preview.models.length > 0
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
          // 有未完成步骤，直接打开部署面板继续
          deployAppId.value = existingAppId.value
          deployOpen.value = true
          await loadDeployStatusAndRunAll()
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
        data: currentPreviewConfigPayload.value
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
    parsedAppCode.value = loadedAppCode.value || appCode
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
      if (conversationId.value && currentAgent.value === 'requirements') {
        try {
          await conversationApi.updateAgentType(conversationId.value, 'builder')
        } catch (e) {
          console.warn('Failed to switch uploaded-doc conversation to builder mode', e)
        }
        currentAgent.value = 'builder'
      }
      router.replace(`/chat/${finalResult.conversation_id}`)
      lastParsedFilename.value = file.name
      latestDocContent.value = ''
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
        syncCurrentDocFromPreview('当前解析出的最新文档', finalResult.rendered_doc || '')
      }

      // 文档上传完成后自动创建 Application（如果还没有）
      if (!existingAppId.value && store.preview.appName) {
        try {
          const result = await applicationApi.autoCreate({
            app_name: store.preview.appName,
            config_preview: currentPreviewConfigPayload.value,
            conversation_id: conversationId.value || undefined,
          })
          existingAppId.value = result.app_id
          loadedAppCode.value = result.app_code || ''
          parsedAppCode.value = result.app_code || ''
          parsedAppCode.value = result.app_code || loadedAppCode.value || ''
          router.replace({ query: { ...route.query, app_id: String(result.app_id) } })
          console.log(`Doc upload auto-created app: id=${result.app_id}, is_new=${result.is_new}`)
        } catch (e) {
          console.warn('文档上传后自动创建应用失败:', e)
        }
      }

      // 文档上传完成后自动刷新文档版本列表
      await fetchDocVersions()

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
      latestDocContent.value = ''
      latestDocAppId.value = null
      latestDocConversationId.value = conversationId.value
      // 自动创建 Application
      if (!existingAppId.value && store.preview.appName) {
        try {
          const result = await applicationApi.autoCreate({
            app_name: store.preview.appName,
            config_preview: currentPreviewConfigPayload.value,
          })
          existingAppId.value = result.app_id
          loadedAppCode.value = result.app_code || ''
          parsedAppCode.value = result.app_code || ''
          router.replace({ query: { ...route.query, app_id: String(result.app_id) } })
        } catch (e) {
          console.warn('兜底模式创建应用失败:', e)
        }
      }

      await fetchDocVersions()

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
    const pmsg = messages.find(m => m.id === progressMsgId)
    if (pmsg) {
      pmsg.content += `\n\n❌ 解析失败: ${err?.message || '未知错误'}`
    } else {
      messages.push({ id: Date.now(), role: 'assistant', agent: 'builder', content: `文档解析失败: ${err?.message || '未知错误'}`, created_at: '' })
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

// ── 上传文档新版本并分析变更 ──
const handleDocVersionUpload = async (file: File, appId: number) => {
  lastParsedFilename.value = file.name
  latestDocContent.value = ''
  latestParseMeta.value = null
  currentDocPreviewOverride.value = null

  const userMsgId = Date.now()
  messages.push({ id: userMsgId, role: 'user', content: `📄 上传文档新版本: ${file.name}`, created_at: '' })

  const progressMsgId = userMsgId + 1
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
      `**📄 上传文档新版本：${file.name}**`,
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
    // 已部署应用更新时强制新建会话，保持每个版本对应独立对话；未部署时复用已有会话
    if (!conversationId.value || isPlatformDeployed.value) {
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
                store.currentApp = {
                  ...(store.currentApp || {}),
                  status: 'draft',
                  apaas_app_id: store.currentApp?.apaas_app_id,
                }
                syncCurrentDocFromPreview('当前解析出的最新文档', data.rendered_doc || '')
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
        syncCurrentDocFromPreview('当前解析出的最新文档', changePlanData.rendered_doc || '')
      }

      // 启用 update review 模式，右侧面板展示变更对比
      applyChangePlanState(changePlanData)
      builderPreviewTab.value = getPreferredUpdateTab()

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
  return [
    '确认', '可以', '可以了', '好的', '好', 'ok', 'okay', '没问题', '就这样',
    '开始生成', '生成吧', '直接生成', '立即生成', '开始吧', '开始构建', '开始搭建', '继续生成', '继续'
  ].some(keyword => normalized.includes(keyword))
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

const getRequirementsSemanticAction = (text: string): 'generate_doc' | 'build' | null => {
  if (!isRequirementsMode.value || !isConfirmationIntent(text)) return null

  const lastAssistant = [...messages].reverse().find((msg) => msg.role === 'assistant')
  const assistantContent = String(lastAssistant?.content || '')
  const hasDocReady = !!docResultForCard.value
    || !!latestDocContent.value.trim()
    || !!chatGeneratedDocContent.value
    || hasStructuredPreviewData.value

  if (assistantContent.includes('请确认操作') || assistantContent.includes('点击下方按钮') || assistantContent.includes('生成结构化的功能设计文档')) {
    return hasDocReady ? 'build' : 'generate_doc'
  }

  if (hasDocReady) return 'build'
  return 'generate_doc'
}

const createConversation = async () => {
  const token = localStorage.getItem('token')
  const agentTypeForCreate = currentAgent.value === 'requirements' ? 'builder' : currentAgent.value
  const res = await fetch(`${API_PREFIX}/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
    body: JSON.stringify({
      agent_type: agentTypeForCreate,
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
  if (!canSendMessage.value || sendingMessage.value) return
  sendingMessage.value = true
  const text = inputText.value.trim()
  const attachmentPayload = pendingChatAttachment.value
  inputText.value = ''
  pendingChatAttachment.value = null
  messages.push({
    id: Date.now(),
    role: 'user',
    content: attachmentPayload
      ? buildUserChatAttachmentContent(text, attachmentPayload)
      : text,
    created_at: ''
  })
  scrollToBottom()
  isTyping.value = true

  if (!conversationId.value && pendingInitialConversationPromise) {
    await pendingInitialConversationPromise
  }

  // 如果还没有对话，先创建
  if (!conversationId.value) {
    await createConversation()
  }

  if (!conversationId.value) {
    isTyping.value = false
    sendingMessage.value = false
    messages.push({ id: Date.now(), role: 'assistant', agent: currentAgent.value, content: '创建对话失败，请重试。', created_at: '' })
    scrollToBottom()
    return
  }

  const semanticAction = getRequirementsSemanticAction(text)
  if (semanticAction) {
    isTyping.value = false
    if (semanticAction === 'build') {
      messages.push({
        id: Date.now(),
        role: 'assistant',
        agent: 'requirements',
        content: '收到确认，正在开始生成应用配置。',
        created_at: ''
      })
      scrollToBottom()
      await triggerFullBuildPipeline()
    } else {
      messages.push({
        id: Date.now(),
        role: 'assistant',
        agent: 'requirements',
        content: '收到确认，正在为你生成设计文档并同步到右侧预览。',
        created_at: ''
      })
      scrollToBottom()
      await generateDocInBackground()
    }
    sendingMessage.value = false
    return
  }

  const shouldSwitchToBuilder = !(attachmentPayload?.kind === 'image')
    && (parseReady.value || !!existingAppId.value || hasPreviewContent.value)
    && currentAgent.value === 'requirements'

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
    const response = attachmentPayload
      ? await (() => {
          const formData = new FormData()
          formData.append('message', text)
          formData.append('file', attachmentPayload.file)
          formData.append('conversation_id', String(conversationId.value))
          if (incrementalConfigPayload) {
            formData.append('current_config', JSON.stringify(incrementalConfigPayload))
          }
          const url = `${API_PREFIX}/chat/send-with-file`
          return fetch(url, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` },
            body: formData
          })
        })()
      : await (() => {
          const url = `${API_PREFIX}/chat/send`
          const body = {
            conversation_id: conversationId.value,
            message: text,
            ...(incrementalConfigPayload ? { current_config: incrementalConfigPayload } : {})
          }
          return fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            body: JSON.stringify(body)
          })
        })()

    if (!response.ok) throw new Error('发送失败')

    const reader = response.body?.getReader()
    const decoder = new TextDecoder()
    let assistantContent = ''
    let sseBuffer = ''
    let currentEvent = ''
    let serverConfigReceived = false  // 服务端已推送 config，done 时跳过客户端重提取

    if (!reader) throw new Error('无法读取响应')

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
            continue
          }

          if (normalizedType === 'message' || normalizedType === 'chunk') {
            const content = parsed.data ?? parsed.content ?? ''
            if (!content) continue
            assistantContent += content
            const renderableAssistantContent = getRenderableContentText(assistantContent)
            if (!renderableAssistantContent) {
              isTyping.value = true
              continue
            }
            isTyping.value = false
            const lastMsg = messages[messages.length - 1]
            if (lastMsg && lastMsg.role === 'assistant' && lastMsg.agent === currentAgent.value && lastMsg.id === -1) {
              lastMsg.content = assistantContent
            } else {
              messages.push({ id: -1, role: 'assistant', agent: currentAgent.value, content: assistantContent, created_at: '' })
            }
            scrollToBottom()
            continue
          }

          if (normalizedType === 'error') {
            isTyping.value = false
            const detail = parsed.data || parsed.message || '模型返回异常，请切换模型后重试。'
            messages.push({
              id: Date.now(),
              role: 'assistant',
              agent: currentAgent.value,
              content: `当前模型暂时不可用：${detail}`,
              created_at: ''
            })
            scrollToBottom()
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
            }
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
            }
            continue
          }

          if (normalizedType === 'done') {
            isTyping.value = false
            const lastMsg = messages[messages.length - 1]
            if (lastMsg && lastMsg.id === -1) lastMsg.id = Date.now()
            if (isRequirementsMode.value) {
              const hasBuildTrigger = assistantContent.includes('<!-- TRIGGER_BUILD -->')
              const hasDesignComplete = assistantContent.includes('<!-- DESIGN_COMPLETE -->')
              const hasGeneratedDocBody = looksLikeGeneratedDesignDoc(assistantContent)
              if (hasBuildTrigger || hasDesignComplete || hasGeneratedDocBody) {
                const fullDocContent = assistantContent
                  .replace('<!-- TRIGGER_BUILD -->', '')
                  .replace('<!-- DESIGN_COMPLETE -->', '')
                  .trim()
                if (fullDocContent) {
                  latestDocContent.value = fullDocContent
                }
                const compactDocMessage = hasBuildTrigger
                  ? '需求已确认，完整设计文档已同步到右侧，正在准备开始构建。'
                  : '设计文档已生成，完整内容请查看右侧预览。'
                if (lastMsg) {
                  lastMsg.content = compactDocMessage
                } else {
                  messages.push({
                    id: Date.now(),
                    role: 'assistant',
                    agent: currentAgent.value,
                    content: compactDocMessage,
                    created_at: ''
                  })
                }
                if (hasBuildTrigger) {
                  triggerFullBuildPipeline()
                } else if (hasDesignComplete) {
                  generateDocInBackground()
                }
              }
            } else {
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
          }
        } catch (e) { /* ignore parse errors */ }
      }

      if (done) {
        break
      }
    }
    if (!assistantContent) {
      isTyping.value = false
      messages.push({
        id: Date.now(),
        role: 'assistant',
        agent: currentAgent.value,
        content: '当前模型没有返回内容，请切换模型后再试一次。',
        created_at: ''
      })
      scrollToBottom()
    }
  } catch (error) {
    console.error('Send error:', error)
    isTyping.value = false
    messages.push({ id: Date.now(), role: 'assistant', agent: currentAgent.value, content: '发送失败，请重试。', created_at: '' })
    scrollToBottom()
  } finally {
    sendingMessage.value = false
    if (!pendingChatAttachment.value && chatImageInputRef.value) {
      chatImageInputRef.value.value = ''
    }
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
      forms: appConfig.forms || [],
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
      config_preview: { type: 'preview', data: currentPreviewConfigPayload.value },
    }
    const created = await applicationApi.create(payload)
    existingAppId.value = created.id
    store.setAppName(appConfig.appName)
    store.currentApp = { status: 'ready' }

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
      const appConfig = await convertConfig(docResultForCard.value)
      store.preview = {
        appName: appConfig.appName || '',
        roles: appConfig.roles || [],
        dicts: appConfig.dicts || [],
        models: appConfig.models || [],
        forms: appConfig.forms || [],
        workflows: appConfig.workflows || [],
        permissions: appConfig.permissions || [],
      }
      if (appConfig.appCode) {
        parsedAppCode.value = appConfig.appCode
      }
      if (appConfig.appName) {
        store.setAppName(appConfig.appName)
        if (!store.currentApp) {
          store.currentApp = { status: 'draft' }
        }
      }
      parseReady.value = true
      syncCurrentDocFromPreview('当前生成的设计文档', buildDocMarkdownFromPreview(appConfig))
      scrollToBottom()
    }
  } catch (e: any) {
    console.error('Background doc generation failed:', e)
    ElMessage.error('配置生成失败，请重新描述需求后重试。')
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
    const progressMessageId = Date.now()
    let hasInsertedProgressMessage = false

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
              if (!hasInsertedProgressMessage) {
                messages.push({
                  id: progressMessageId,
                  role: 'assistant',
                  agent: 'requirements',
                  content: '正在整理设计文档，完整内容会直接显示在右侧预览区。',
                  created_at: ''
                })
                hasInsertedProgressMessage = true
              }
              scrollToBottom()
            }
            // Phase 2: structured JSON result
            if (data.doc_result) {
              docResultForCard.value = data.doc_result
              const progressMsg = messages.find((msg) => msg.id === progressMessageId)
              if (progressMsg) {
                progressMsg.content = '设计文档已生成，完整内容请查看右侧预览。'
              } else {
                messages.push({
                  id: progressMessageId,
                  role: 'assistant',
                  agent: 'requirements',
                  content: '设计文档已生成，完整内容请查看右侧预览。',
                  created_at: ''
                })
              }
            }
          } catch { /* ignore */ }
        }
      }
    }

    isTyping.value = false
    if (!docResultForCard.value) {
      messages.push({ id: Date.now(), role: 'assistant', agent: 'requirements', content: '设计文档生成失败，请重试。', created_at: '' })
    } else {
      try {
        const appConfig = await convertConfig(docResultForCard.value)
        store.preview = {
          appName: appConfig.appName || '',
          roles: appConfig.roles || [],
          dicts: appConfig.dicts || [],
          models: appConfig.models || [],
          forms: appConfig.forms || [],
          workflows: appConfig.workflows || [],
          permissions: appConfig.permissions || [],
        }
        if (appConfig.appCode) {
          parsedAppCode.value = appConfig.appCode
        }
        if (appConfig.appName) {
          store.setAppName(appConfig.appName)
          if (!store.currentApp) {
            store.currentApp = { status: 'draft' }
          }
        }
        parseReady.value = true
        syncCurrentDocFromPreview('当前生成的设计文档', buildDocMarkdownFromPreview(appConfig))
      } catch (error) {
        console.error('Sync generated doc preview failed:', error)
      }
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
      forms: appConfig.forms || [],
      workflows: appConfig.workflows || [],
      permissions: appConfig.permissions || [],
    }
    parsedAppCode.value = appConfig.appCode || ''
    parseReady.value = true
    syncCurrentDocFromPreview('当前生成的设计文档', buildDocMarkdownFromPreview(appConfig))

    // Step 4: Create/update application record
    const appCode = appConfig.appCode || buildAppCode(appConfig.appName || '新应用')
    const payload = {
      conversation_id: conversationId.value,
      app_name: appConfig.appName || '新应用',
      app_code: appCode,
      config_preview: { type: 'preview', data: currentPreviewConfigPayload.value },
    }
    const created = await applicationApi.create(payload)
    existingAppId.value = created.id
    store.setAppName(appConfig.appName)
    store.currentApp = { status: 'ready' }

    // Step 5: Add confirmation message
    messages.push({
      id: Date.now(),
      role: 'assistant',
      agent: 'builder',
      content: `配置已就绪！已提取 ${appConfig.models?.length || 0} 个模型、${appConfig.dicts?.length || 0} 个字典、${appConfig.roles?.length || 0} 个角色。正在开始生成...`,
      created_at: '',
    })

    docResultForCard.value = null  // Clear card
    scrollToBottom()

    // Update URL
    router.replace(`/chat/${conversationId.value}?app_id=${created.id}`)
    fetchConversationList()

    // 自动触发生成流程（合并为一步）
    await nextTick()
    startGenerate()
  } catch (e: any) {
    ElMessage.error('转换失败: ' + (e.message || '未知错误'))
  } finally {
    confirmingDoc.value = false
  }
}

const buildDocMarkdownFromPreview = (previewOverride?: any) => {
  const preview = previewOverride || store.preview
  const appName = preview?.appName || ''
  const appCode = previewOverride ? (preview?.appCode || '') : displayAppCode.value
  const lines: string[] = []
  const models = preview?.models || []
  const forms = preview?.forms || []
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

  lines.push('## 六、权限配置', '')
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

const formatContent = (t: string) => {
  const text = getRenderableContentText(t)
  return text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>').replace(/• /g, '<span style="color:#818cf8;margin-right:4px">•</span> ')
}

let pendingInitialConversationPromise: Promise<void> | null = null

const ensureFreshRequirementsConversation = async () => {
  if (conversationId.value || existingAppId.value || store.pendingMarkdown || store.pendingFile) return

  if (pendingInitialConversationPromise) {
    await pendingInitialConversationPromise
    return
  }

  resetConversationWorkspace()
  currentAgent.value = 'requirements'
  resetMessagesToWelcome()

  pendingInitialConversationPromise = (async () => {
    const token = localStorage.getItem('token')
    const res = await fetch(`${API_PREFIX}/conversations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({
        agent_type: 'builder',
        ...(selectedBuilderModelId.value != null ? { selected_llm_config_id: selectedBuilderModelId.value } : {}),
      })
    })
    if (!res.ok) return

    const data = await res.json()
    conversationId.value = data.id
    selectedConversationId.value = data.id
    currentAgent.value = 'requirements'
    router.replace(`/chat/${data.id}`)
    resetMessagesToWelcome()
  })().finally(() => {
    pendingInitialConversationPromise = null
  })

  await pendingInitialConversationPromise
}

onMounted(async () => {
  store.showConnectModal = false
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
          store.currentApp = { status: app.status || 'ready', apaas_app_id: app.apaas_app_id }
          platformDirectUrl.value = app.apaas_url || ''
          parseReady.value = store.preview.models.length > 0
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
          await syncBuilderModelFromConversation(app.conversation_id)
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
                store.currentApp = { status: 'draft', apaas_app_id: linkedApp.apaas_app_id }
                parseReady.value = store.preview.models.length > 0
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
          parseReady.value = store.preview.models.length > 0
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
          await syncBuilderModelFromConversation(app.conversation_id)
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

  // ── 新对话：自动进入 requirements 模式 ──
  // 只有真正“新建会话”时才创建 requirements，对已有 app 不要覆盖恢复结果
  if (!conversationId.value && !existingAppId.value && !store.pendingMarkdown && !store.pendingFile) {
    await ensureFreshRequirementsConversation()
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
    resetMessagesToWelcome()
    const file = new File([pending.content], pending.filename, { type: 'text/markdown' })
    await nextTick()
    await uploadDocFile(file)
  }

  // 从 Landing 页带过来的待解析文件
  if (store.pendingFile) {
    const file = store.pendingFile
    store.pendingFile = null
    resetConversationWorkspace()
    resetMessagesToWelcome()
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
  store.preview.forms = []
  store.preview.dicts = []
  store.preview.roles = []
  store.preview.workflows = []
  store.preview.permissions = []
  store.setAppName('', { force: true })
  store.currentApp = null
  parsedAppCode.value = ''
  loadedAppCode.value = ''
  latestDocContent.value = ''
  latestDocAppId.value = null
  latestDocConversationId.value = null
  conversationId.value = null
  completedChangePlans.value = []
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
      store.currentApp = { status: app.status || 'ready', apaas_app_id: app.apaas_app_id }
      platformDirectUrl.value = app.apaas_url || ''
      parseReady.value = store.preview.models.length > 0
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

onBeforeUnmount(() => {
  clearPendingChatAttachment()
  clearPlatformIframeRepairTimer()
})

watch(activeView, (view) => {
  if (existingAppId.value) {
    localStorage.setItem(getAppViewStorageKey(existingAppId.value), view)
  }
})

watch(isUpdateReviewMode, (enabled) => {
  if (!enabled) return
  deployOpen.value = true
  const currentTabVisible = visibleBuilderPreviewTabs.value.some(tab => tab.key === builderPreviewTab.value)
  if (!currentTabVisible || getBuilderTabCount(builderPreviewTab.value) === 0) {
    builderPreviewTab.value = getPreferredUpdateTab()
  }
}, { immediate: true })

watch(showDeployedVersionedView, (enabled) => {
  if (!enabled) return
  builderPreviewTab.value = 'docs'
}, { immediate: true })

watch(displayDocVersions, (versions) => {
  if (expandedDocVersionKey.value && !versions.some(ver => ver.key === expandedDocVersionKey.value)) {
    expandedDocVersionKey.value = null
  }
  if (selectedDocVersionKey.value && !versions.some(ver => ver.key === selectedDocVersionKey.value)) {
    selectedDocVersionKey.value = versions[0]?.key || null
  }
}, { immediate: true })

// 切换到文档 tab 时自动加载版本列表
watch(builderPreviewTab, (tab) => {
  if (tab === 'docs' && (existingAppId.value || conversationId.value) && docVersions.value.length === 0) {
    fetchDocVersions()
  }
})
watch(existingAppId, (id) => {
  if (id && builderPreviewTab.value === 'docs') {
    fetchDocVersions()
  }
})
watch(conversationId, (id) => {
  if (isDocParsing.value) {
    if (id && builderPreviewTab.value === 'docs' && docVersions.value.length === 0) {
      fetchDocVersions()
    }
    return
  }
  if (route.query.app_id || existingAppId.value) {
    if (id && builderPreviewTab.value === 'docs' && docVersions.value.length === 0) {
      fetchDocVersions()
    }
    return
  }
  store.reset()
  existingAppId.value = null
  docVersions.value = []
  currentDocPreviewOverride.value = null
  if (id && builderPreviewTab.value === 'docs') {
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
  font-size: 9px;
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
  font-size: 15px;
  line-height: 1.65;
  color: var(--t-text-primary);
  min-height: 42px;
  max-height: 200px;
  overflow-y: auto;
  padding: 8px 0;
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
.chat-attachment-preview {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 2px 8px 8px;
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
  max-height: 70vh; overflow-y: auto; padding: 16px;
  font-size: 13px; line-height: 1.7; color: var(--t-text-primary);
  background: var(--t-bg-base); border-radius: 8px;
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
  width: max-content;
  min-width: 100%;
  border-collapse: collapse;
  margin: 0;
  font-size: 12px;
  table-layout: auto;
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
  .doc-top-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .doc-version-toggle {
    width: 100%;
  }

  .doc-ver-actions {
    width: 100%;
    justify-content: flex-start;
    flex-wrap: wrap;
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
  background: linear-gradient(180deg, rgba(242, 246, 255, 0.96), rgba(247, 249, 255, 0.9));
}
.update-review-groups {
  padding-top: 4px;
}
.dg.update .dg-hd {
  background: linear-gradient(180deg, rgba(242, 246, 255, 0.96), rgba(247, 249, 255, 0.9));
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
</style>
