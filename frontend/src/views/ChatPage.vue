<template>
  <WorkbenchShell>
  <div class="chat-page">
    <TopBar title="aPaaS Builder">
      <template #center>
        <div v-if="showViewSwitcher" class="mode-switcher">
          <button class="mode-btn" :class="{ active: activeView === 'builder' }" @click="setActiveView('builder')">
            <span class="mode-btn-dot" aria-hidden="true"></span>
            <span>智能搭建</span>
          </button>
          <button v-if="SHOW_PLATFORM_CONFIG" class="mode-btn" :class="{ active: activeView === 'platform' }" @click="setActiveView('platform')">
            <span class="mode-btn-dot" aria-hidden="true"></span>
            <span>辅助搭建</span>
          </button>
          <button class="mode-btn" :class="{ active: activeView === 'coding' }" @click="setActiveView('coding')">
            <span class="mode-btn-dot" aria-hidden="true"></span>
            <span>智能开发</span>
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
      <div
        v-show="!SHOW_PLATFORM_CONFIG || activeView === 'builder'"
        class="builder-content"
      >
      <!-- 左侧对话区 -->
      <div class="chat-side">
        <div v-if="appParsedMode" class="doc-view-wrap">
          <div class="doc-view-head">
            <div class="doc-view-title">功能设计文档</div>
            <div class="doc-view-meta">
              <div class="doc-view-file">{{ lastParsedFilename || `${store.preview.appName || '未命名应用'}.md` }}</div>
              <button class="doc-download-btn" @click="downloadCurrentDoc">下载 .md</button>
            </div>
          </div>
          <DesignDocCard
            v-if="parsedDocResultForCard"
            :doc-result="parsedDocResultForCard"
            :show-actions="false"
          />
          <div v-else class="doc-view-empty">
            暂无可展示的文档内容，可重新上传文档后查看。
          </div>
        </div>
        <div v-else class="messages" ref="messagesRef">
          <div v-for="(msg, idx) in visibleMessages" :key="idx" class="chat-bubble" :class="msg.role">
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
          <!-- 设计文档结构化卡片（requirements 模式生成完成后显示） -->
          <div v-if="docResultForCard" class="chat-bubble assistant">
            <div class="bubble-inner" style="max-width:90%">
              <DesignDocCard
                :doc-result="docResultForCard"
                :confirming="confirmingDoc"
                @confirm="confirmDocAndBuild"
                @edit="(updated: any) => { docResultForCard = updated }"
              />
            </div>
          </div>
          <!-- 编码冲突修复输入 -->
          <div v-if="activeConflict" class="chat-bubble assistant">
            <div class="bubble-row assistant">
              <div class="assistant-avatar" aria-hidden="true">AI</div>
              <div class="bubble-inner">
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
                  <!-- 一键生成按钮已移除：文档上传后自动解析生成配置 -->
                </div>
                <div class="builder-control-hint inside-card">{{ builderModelHint }}</div>
              <div class="input-card-top">
                <label class="upload-btn" title="上传功能设计文档(.md) 或粘贴截图(Cmd+V)">
                  <input type="file" accept=".md,.png,.jpg,.jpeg,.gif,.webp" @change="handleDocUpload" style="display:none" />
                  <svg width="18" height="18" viewBox="0 0 18 18" fill="none"><path d="M15.5 8.5l-6.4 6.4a3.5 3.5 0 01-5-5l6.4-6.4a2.2 2.2 0 013.1 3.1L7.2 13a.9.9 0 01-1.3-1.3l5.5-5.5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>
                </label>
                <div v-if="attachedImage" class="attached-image-preview">
                  <img :src="attachedImageUrl" alt="截图预览" />
                  <button class="attached-image-remove" @click="removeAttachedImage" title="移除图片">&times;</button>
                </div>
                <textarea
                  v-model="inputText"
                  @keydown.enter.exact.prevent="sendMessage"
                  @keydown.enter.shift.exact="inputText += '\n'"
                  @paste="handleImagePaste"
                  :placeholder="builderQuickPlaceholder"
                  rows="1"
                  ref="inputRef"
                  @input="autoResizeTextarea"
                ></textarea>
                <button class="send-btn" :class="{ disabled: !inputText.trim() && !attachedImage }" @click="sendMessage">
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M14 2L7 9M14 2l-4.5 12-2-5.5L2 6.5 14 2z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>
                </button>
              </div>
            </div>
          </div>
          </div>

        </div>
      </div>

      <div class="preview-side builder-result-side">
        <div class="preview-side-header">
          <div class="preview-side-heading">
            <div class="preview-side-heading-main">
              <div class="preview-side-title-row">
                <div class="preview-side-title">{{ builderAppDisplayName }}</div>
                <div class="preview-side-status inline-meta">
                  <code class="preview-app-code-chip inline">{{ displayAppCode }}</code>
                </div>
                <button
                  v-if="showBuilderPreview && !isPlatformDeployed"
                  class="preview-app-edit-btn"
                  @click="editAppMeta"
                  aria-label="修改应用名称和编码"
                  title="修改应用名称和编码"
                >
                  <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
                    <path d="M10.9 2.1a1.5 1.5 0 112.1 2.1l-7.2 7.2-3 .8.8-3 7.3-7.1z" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>
                  </svg>
                </button>
              </div>
            </div>
          </div>
          <button
            v-if="showStartDeployButton"
            class="preview-side-cta"
            @click="startDeployFlow()"
            :disabled="generating || assembling || !hasPreviewContent"
          >{{ generating ? '部署中...' : '开始部署' }}</button>
          <template v-else-if="isPlatformDeployed">
            <button
              class="preview-side-cta"
              @click="openDeployPanel()"
              :disabled="generating"
            >更新部署</button>
            <button
              v-if="showPublishButton"
              class="preview-side-cta success"
              style="margin-left:6px"
              @click="publishCurrentApp"
              :disabled="publishingApp"
            >{{ publishingApp ? '上线中...' : '上线应用' }}</button>
          </template>
        </div>
        <div v-if="showBuilderPreview" class="builder-step-bar">
          <button
            v-for="(tab, index) in builderPreviewTabs"
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
            <template v-if="builderPreviewTab === 'roles'">
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

            <template v-else-if="builderPreviewTab === 'dicts'">
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

            <template v-else-if="builderPreviewTab === 'models'">
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

            <template v-else-if="builderPreviewTab === 'forms'">
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
              <div class="doc-preview-card">
                <div class="doc-preview-head">
                  <div>
                    <div class="doc-preview-title">功能文档</div>
                    <div class="doc-preview-subtitle">整体功能说明的 Markdown 文档</div>
                  </div>
                  <button class="doc-preview-download" @click="downloadCurrentDoc" aria-label="下载文档" title="下载文档">
                    <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
                      <path d="M8 2.5v6m0 0 2.4-2.4M8 8.5 5.6 6.1M3 10.5v1.3c0 .66.54 1.2 1.2 1.2h7.6c.66 0 1.2-.54 1.2-1.2v-1.3" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                    <span>下载</span>
                  </button>
                </div>
                <div class="doc-preview-content doc-rendered" v-html="renderedDocHtml"></div>
              </div>
            </template>
          </div>
          <div v-else class="preview-empty preview-empty-stage">
            <div class="preview-empty-title">还没有解析内容</div>
            <div class="preview-empty-copy">先告诉我你想搭什么，我会根据你的需求生成右侧解析结果。</div>
          </div>
        </div>
      </div>

      <aside class="deploy-side" :class="{ open: deployOpen }">
        <div class="deploy-header">
          <div>
            <div class="deploy-title-row">
              <div class="deploy-title">部署进度</div>
              <span v-if="currentDeployStep" class="deploy-live-badge">执行中</span>
            </div>
            <div class="deploy-desc">{{ deployAllDone ? '已完成全部部署步骤' : deployOpen ? '确认解析后执行右侧部署步骤' : '点击开始部署后在这里执行' }}</div>
            <div v-if="currentDeployStep" class="deploy-current-step">{{ currentDeployStep.label }}</div>
          </div>
          <button class="deploy-close" @click="deployOpen = false" aria-label="关闭部署面板">×</button>
        </div>
        <div v-if="deployOpen" class="deploy-progress">
          <div class="dp-track"><div class="dp-fill" :style="{ width: `${deployPercent}%` }"></div></div>
          <span class="dp-meta">{{ deployDoneCount }}/{{ deploySteps.length || 0 }}</span>
        </div>
        <div v-if="deployOpen && !deployAllDone" class="deploy-actions">
          <button class="dp-run-all" @click="deployRunAll" :disabled="deployRunningAll || deployExecuting !== null || deployAllDone || deploySteps.length === 0">
            {{ deployRunningAll ? '部署中...' : deployAllDone ? '部署完成' : '一键部署' }}
          </button>
        </div>
        <div v-if="deployOpen && activeConflict" class="deploy-conflict-card">
          <div class="deploy-conflict-title">检测到编码冲突</div>
          <div class="deploy-conflict-copy">{{ activeConflict.model_name }} 的编码 <code>{{ activeConflict.current_code }}</code> 已存在，请修改后继续。</div>
          <div class="deploy-conflict-input-row">
            <input
              v-model="activeConflict.newCode"
              class="deploy-conflict-input"
              placeholder="输入新的编码"
              @keydown.enter="resolveConflictAndRetry"
              :disabled="activeConflict.resolving"
            />
            <button class="deploy-conflict-btn primary" @click="resolveConflictAndRetry" :disabled="activeConflict.resolving">{{ activeConflict.resolving ? '处理中...' : '确认' }}</button>
          </div>
        </div>
        <div v-if="deployOpen" class="deploy-groups">
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
      </aside>
    </div><!-- /builder-content -->
    </div><!-- /content-area -->

    <!-- ChangePlan 变更计划浮层 -->
    <Teleport to="body">
      <div v-if="store.showChangePlan && store.changePlan" class="change-plan-overlay" @click.self="store.showChangePlan = false">
        <div class="change-plan-panel">
          <div class="change-plan-header">
            <h3>变更计划 (V{{ store.changePlan.fromVersion }} → V{{ store.changePlan.toVersion }})</h3>
            <button class="change-plan-close" @click="store.showChangePlan = false">&times;</button>
          </div>
          <div class="change-plan-body">
            <ConfigDiff
              v-if="changePlanDiff"
              :has-changes="changePlanDiff.has_changes !== false"
              :summary="changePlanDiff.summary || ''"
              :role-changes="changePlanDiff.role_changes || []"
              :dict-changes="changePlanDiff.dict_changes || []"
              :model-changes="changePlanDiff.model_changes || []"
              :form-changes="changePlanDiff.form_changes || []"
              :process-changes="changePlanDiff.process_changes || []"
              :warnings="changePlanDiff.warnings || []"
              :unsupported-changes="changePlanDiff.unsupported_changes || []"
              :selectable="true"
              :executing="executingChangePlan"
              :show-actions="false"
            />
            <div v-else class="change-plan-diff">
              <pre style="white-space:pre-wrap;">{{ JSON.stringify(store.changePlan, null, 2) }}</pre>
            </div>
          </div>
          <div class="change-plan-footer">
            <span class="change-plan-count">已选 {{ changePlanSelectedCount }}/{{ store.changePlan.actions?.length || 0 }} 项变更</span>
            <div class="change-plan-actions">
              <button class="btn-cancel" @click="store.showChangePlan = false; store.changePlan = null">取消</button>
              <button class="btn-execute" :disabled="executingChangePlan || changePlanSelectedCount === 0" @click="executeChangePlan">
                {{ executingChangePlan ? '执行中...' : '执行变更' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

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
  </WorkbenchShell>
</template>

<script setup lang="ts">
import { API_PREFIX } from '@/utils/request'
import { ref, reactive, computed, nextTick, onMounted, watch } from 'vue'
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
import type { Message } from '@/types'
import TopBar from '@/components/TopBar.vue'
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import { llmConfigApi, type BuilderModelOption } from '@/api/llmConfig'
import DesignDocCard from '@/components/DesignDocCard.vue'
import ConfigDiff from '@/components/ConfigDiff.vue'
import { requirementsApi } from '@/api/requirements'
import { marked } from 'marked'
import { convertConfig } from '@/api/conversation'

const router = useRouter()
const route = useRoute()
const store = usePreviewStore()
const userStore = useUserStore()
const builderPreviewTab = ref<'roles' | 'dicts' | 'models' | 'forms' | 'permissions' | 'docs'>('roles')
const builderPreviewTabs = [
  { key: 'roles', label: '角色' },
  { key: 'dicts', label: '数据字典' },
  { key: 'models', label: '数据模型' },
  { key: 'forms', label: '表单' },
  { key: 'permissions', label: '权限' },
  { key: 'docs', label: '文档' },
] as const
const rightQuickInput = ref('')
const attachedImage = ref<File | null>(null)
const attachedImageUrl = ref('')
const parsedAppCode = ref('')
const loadedAppCode = ref('')
const currentRemoteStatus = ref('')
const lastParsedFilename = ref('')
const latestDocContent = ref('')
const readyForGenerate = computed(() => !!store.currentApp && parseReady.value)
const appParsedMode = computed(() => route.query.app_mode === 'parsed')
const builderAppDisplayName = computed(() => store.preview.appName || store.currentApp?.name || '未命名应用')
const displayAppCode = computed(() => parsedAppCode.value || loadedAppCode.value || buildAppCode(store.preview.appName))
const parsedDocResultForCard = computed(() => {
  if (!store.preview.appName && !store.preview.models.length && !store.preview.dicts.length && !store.preview.roles.length) {
    return null
  }
  const roleTableMapping = (store.preview.permissions || []).map((perm: any, idx: number) => ({
    table_name: perm?.form || perm?.table || `表${idx + 1}`,
    table_code: perm?.form_code || perm?.table_code || `table_${idx + 1}`,
    permissions: (perm?.roles || []).map((r: any, rIdx: number) => ({
      role_code: r?.role_code || r?.code || `role_${rIdx + 1}`,
      role_name: r?.role_name || r?.name || `角色${rIdx + 1}`,
      operations: r?.actions || r?.operations || []
    }))
  }))
  return {
    app_info: {
      name: store.preview.appName || '未命名应用',
      code: displayAppCode.value,
      description: `由 aPaaS Builder AI 解析生成，包含 ${store.preview.models.length} 个模型、${store.preview.dicts.length} 个字典、${store.preview.roles.length} 个角色。`
    },
    roles: (store.preview.roles || []).map((role: any, idx: number) => ({
      role_code: role?.code || `role_${idx + 1}`,
      role_name: role?.name || role?.code || `角色${idx + 1}`,
      description: role?.description || ''
    })),
    data_dictionary: (store.preview.dicts || []).map((dict: any, idx: number) => ({
      dict_code: dict?.code || `dict_${idx + 1}`,
      dict_name: dict?.name || dict?.code || `字典${idx + 1}`,
      items: (dict?.options || []).map((item: any, itemIdx: number) => ({
        item_code: typeof item === 'string' ? `item_${itemIdx + 1}` : (item?.code || item?.item_code || `item_${itemIdx + 1}`),
        item_name: typeof item === 'string' ? item : (item?.name || item?.item_name || `选项${itemIdx + 1}`)
      }))
    })),
    tables: (store.preview.models || []).map((model: any, idx: number) => ({
      table_code: model?.code || `table_${idx + 1}`,
      table_name: model?.name || model?.code || `数据表${idx + 1}`,
      table_type: model?.table_type || '主表',
      fields: (model?.fields || []).map((field: any, fIdx: number) => ({
        field_code: field?.code || `field_${fIdx + 1}`,
        field_name: field?.name || field?.code || `字段${fIdx + 1}`
      }))
    })),
    role_table_mapping: roleTableMapping
  }
})
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
const activeBuilderTabLabel = computed(() => builderPreviewTabs.find(tab => tab.key === builderPreviewTab.value)?.label || '角色')
const activeBuilderStepIndex = computed(() => Math.max(0, builderPreviewTabs.findIndex(tab => tab.key === builderPreviewTab.value)))
const getBuilderTabCount = (tabKey: typeof builderPreviewTab.value) => {
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
// ── ChangePlan (增量更新) ──
const executingChangePlan = ref(false)
const changePlanDiff = computed(() => store.changePlan?.diffSummary || null)
const changePlanSelectedCount = computed(() => {
  if (!store.changePlan?.actions) return 0
  return store.changePlan.actions.filter((a: any) => a.selected).length
})

const showStartDeployButton = computed(() => !deployAllDone.value && !isPlatformDeployed.value)
const showPublishButton = computed(() =>
  isPlatformDeployed.value &&
  !isAppOnline.value &&
  !isAppPublishing.value &&
  !publishingApp.value
)
const showBuilderComposer = computed(() => true)  // 始终显示输入区，已部署应用也需要对话迭代和上传更新文档
const showDeployProgressInline = computed(() => deploySteps.value.length > 0 || deployOpen.value || isPlatformDeployed.value)
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
const hasPreviewContent = computed(() =>
  !!store.preview.appName
  || store.preview.roles.length > 0
  || store.preview.dicts.length > 0
  || store.preview.models.length > 0
  || formPreviewItems.value.length > 0
  || permissionPreviewItems.value.length > 0
)
const showBuilderPreview = computed(() =>
  hasPreviewContent.value && (
    !isRequirementsMode.value ||
    !!existingAppId.value ||
    parseReady.value
  )
)
const docPreviewContent = computed(() => ((latestDocContent.value || '').trim() || buildDocMarkdownFromPreview()).trim())
const renderedDocHtml = computed(() => {
  const md = docPreviewContent.value
  if (!md) return '<p style="color:#9aa;text-align:center;padding:40px 0;">暂无文档内容</p>'
  try {
    return marked.parse(md) as string
  } catch {
    return `<pre>${md}</pre>`
  }
})
const docPreviewAvailable = computed(() => !!docPreviewContent.value)
const publishingApp = ref(false)

const getDataScopeLabel = (scope: string) => {
  const normalized = (scope || '').toLowerCase()
  if (normalized.includes('all') || normalized.includes('全部')) return { text: '全部数据', className: 'all' }
  if (normalized.includes('dept') || normalized.includes('部门')) return { text: '部门数据', className: 'dept' }
  if (normalized.includes('self') || normalized.includes('本人') || normalized.includes('自己')) return { text: '本人数据', className: 'self' }
  return { text: scope || '未配置', className: '' }
}

const editAppMeta = () => {
  builderPreviewTab.value = 'roles'
  inputText.value = `请帮我修改应用名称和应用编码：\n当前应用名称：${builderAppDisplayName.value}\n当前应用编码：${displayAppCode.value}\n目标名称：\n目标编码：`
  ElMessage.info('已切换到左侧对话区，你可以直接描述新的应用名称和编码。')
  focusQuickInput()
}

const formPreviewItems = computed(() =>
  (store.preview.models || []).map((model: any, idx: number) => ({
    name: model?.form_name || model?.name || `表单${idx + 1}`,
    code: model?.form_code || model?.code || `form_${idx + 1}`,
    modelName: model?.name || model?.code || `数据模型${idx + 1}`,
    modelCode: model?.code || `model_${idx + 1}`,
    tableType: String(model?.table_type || model?.type || '').toLowerCase(),
    tableTypeLabel: /sub|child|子表/.test(String(model?.table_type || model?.type || '').toLowerCase()) ? '子表' : '主表',
    fieldCount: Array.isArray(model?.fields) ? model.fields.length : 0,
    fieldsText: Array.isArray(model?.fields) && model.fields.length
      ? model.fields.map((field: any) => field?.name || field?.code || '未命名字段').slice(0, 8).join('、')
      : '暂无字段配置'
    ,
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
)
const permissionPreviewItems = computed(() =>
  (store.preview.permissions || []).map((perm: any, idx: number) => ({
    name: perm?.form || perm?.table || perm?.name || `权限对象${idx + 1}`,
    code: perm?.form_code || perm?.table_code || perm?.code || `perm_${idx + 1}`,
    raw: perm,
    rows: Array.isArray(perm?.roles) && perm.roles.length
      ? perm.roles.map((role: any, roleIdx: number) => {
          const actions = role?.actions || role?.operations || role?.permissions || []
          const scopeInfo = getDataScopeLabel(role?.data_scope || role?.scope || role?.dataScope || '')
          return {
            roleCode: role?.role_code || role?.code || `role_${roleIdx + 1}`,
            roleName: role?.role_name || role?.name || `角色${roleIdx + 1}`,
            actionsText: Array.isArray(actions) && actions.length ? actions.join('、') : '未配置',
            scopeText: scopeInfo.text,
            scopeClass: scopeInfo.className,
          }
        })
      : []
  }))
)

const normalizeDictOptions = (dict: any) =>
  (dict?.options || []).map((item: any, idx: number) => (
    typeof item === 'string'
      ? { name: item, code: `opt_${idx + 1}` }
      : { name: item?.name || item?.item_name || `选项${idx + 1}`, code: item?.code || item?.item_code || `opt_${idx + 1}` }
  ))

const summarizeDictOptions = (dict: any) => {
  const options = normalizeDictOptions(dict)
  if (!options.length) return '暂无选项'
  return options.slice(0, 6).map(option => option.name).join('、') + (options.length > 6 ? ` 等 ${options.length} 项` : '')
}

const BUILDER_WELCOME_MESSAGE = '告诉我你想搭什么，我来帮你生成。\n\n可以直接描述需求，也可以上传原型图或设计稿。'
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
  messages.splice(0, messages.length, createWelcomeMessage())
}

const visibleMessages = computed(() => (messages.length ? messages : [createWelcomeMessage()]))

const focusQuickInput = () => {
  nextTick(() => {
    inputRef.value?.focus()
  })
}

const startSingleEdit = (tab: typeof builderPreviewTab.value, payload: any) => {
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
const platformAppUrl = ref('')  // 应用配置页 URL（登录后跳转用）
const platformLoading = ref(false)
const platformError = ref('')
const platformLoginHint = ref('')
const platformIframeRef = ref<HTMLIFrameElement | null>(null)
const platformIframeAppId = ref<number | null>(null)

const buildPlatformProxyUrl = (appId: number) => {
  const token = userStore.token || localStorage.getItem('token') || ''
  const authQuery = token ? `&_auth=${encodeURIComponent(token)}` : ''
  return `${API_PREFIX}/platform-proxy/entry?app_id=${appId}${authQuery}`
}

const refreshCurrentAppRemoteMeta = async (appId: number) => {
  try {
    const apps = await applicationApi.list({ include_remote: true }) as any[]
    const current = apps.find((item: any) => String(item.id) === String(appId))
    currentRemoteStatus.value = current?.remote_status || ''
    if (current?.apaas_app_id && store.currentApp) {
      store.currentApp = { ...store.currentApp, apaas_app_id: current.apaas_app_id, status: current.local_status || store.currentApp.status, remote_status: current.remote_status }
    }
  } catch {
    currentRemoteStatus.value = ''
  }
}

const loadPlatformUrl = async () => {
  if (!existingAppId.value) return
  platformLoading.value = true
  platformError.value = ''
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
  if (!platformIframeUrl.value || platformIframeAppId.value !== existingAppId.value) {
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
  if (savedView === 'platform' && SHOW_PLATFORM_CONFIG) {
    switchToPlatform()
    return
  }
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

// 按 code 合并两个数组（保留已有 + 更新/新增）
const mergeByCode = (existing: any[], incoming: any[]): any[] => {
  if (!incoming || incoming.length === 0) return existing
  if (!existing || existing.length === 0) return incoming
  const map = new Map<string, any>()
  for (const item of existing) map.set(item.code || item.name, item)
  for (const item of incoming) map.set(item.code || item.name, item)
  return Array.from(map.values())
}

// 从AI回复中提取JSON配置（支持 preview 完整配置 + 增量合并）
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
        const isIncremental = !!existingAppId.value && store.preview.models.length > 0
        if (store.preview.models.length > 0 && !existingAppId.value) {
          console.warn('已有配置且无关联应用，忽略 LLM 重复输出的完整 JSON')
          continue
        }

        if (isIncremental) {
          // 增量模式：保留原有应用名称，不让 AI 覆盖
          store.currentApp = { name: store.preview.appName, status: 'draft' }
        } else {
          store.currentApp = { name: parsed.data.appName || store.preview.appName, status: 'draft' }
          store.preview.appName = parsed.data.appName || store.preview.appName
        }

        if (isIncremental) {
          // 增量模式：按 code 合并，不丢失已有数据
          store.preview.roles = mergeByCode(store.preview.roles, parsed.data.roles)
          store.preview.dicts = mergeByCode(store.preview.dicts, parsed.data.dicts)
          store.preview.models = mergeByCode(store.preview.models, parsed.data.models)
          store.preview.workflows = mergeByCode(store.preview.workflows, parsed.data.workflows)
          store.preview.permissions = parsed.data.permissions || store.preview.permissions
          console.log('Incremental merge complete:', {
            roles: store.preview.roles.length, dicts: store.preview.dicts.length,
            models: store.preview.models.length
          })

          // 同步到后端（会自动重新生成 requirement_doc）
          applicationApi.autoCreate({
            app_name: store.preview.appName,
            config_preview: { ...store.preview },
            conversation_id: conversationId.value || undefined,
            app_id: existingAppId.value || undefined,
          }).then(() => {
            console.log('Incremental config saved to backend')
            // 重新加载文档内容（后端已根据最新 config 重新生成）
            if (existingAppId.value) {
              loadLatestDocForApp(existingAppId.value)
            }
          }).catch(e => {
            console.error('Failed to save incremental config:', e)
          })
        } else {
          // 新建模式：直接赋值
          store.preview.roles = parsed.data.roles || []
          store.preview.dicts = parsed.data.dicts || []
          store.preview.models = parsed.data.models || []
          store.preview.workflows = parsed.data.workflows || []
          store.preview.permissions = parsed.data.permissions || []

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
  created_at: string
}
const docVersions = ref<DocVersion[]>([])
const docVersionsLoading = ref(false)
const docVersionPreviewVisible = ref(false)
const docVersionPreviewContent = ref('')
const docVersionPreviewTitle = ref('')
const docVersionDiffVisible = ref(false)
const docVersionDiffLeft = ref('')
const docVersionDiffRight = ref('')
const docVersionDiffLeftTitle = ref('')
const docVersionDiffRightTitle = ref('')
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
    // 没有 document_version 记录时，fallback 到应用的 requirement_doc
    if (!latestDocContent.value) {
      try {
        const app = await applicationApi.get(appId) as any
        if (app?.requirement_doc) {
          latestDocContent.value = app.requirement_doc
        }
      } catch { /* ignore */ }
    }
    if (!parsedAppCode.value && latestDocContent.value) {
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
  docVersionPreviewTitle.value = `V${ver.version} — ${ver.filename}`
  docVersionPreviewContent.value = ver.raw_content || '（无内容）'
  docVersionPreviewVisible.value = true
}

const openDocDiff = (ver: DocVersion) => {
  const prevVer = docVersions.value.find(v => v.version === ver.version - 1)
  if (!prevVer) return
  docVersionDiffLeftTitle.value = `V${prevVer.version} — ${prevVer.filename}`
  docVersionDiffRightTitle.value = `V${ver.version} — ${ver.filename}`
  docVersionDiffLeft.value = prevVer.raw_content || ''
  docVersionDiffRight.value = ver.raw_content || ''
  docVersionDiffVisible.value = true
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
const currentDeployStep = computed(() =>
  deploySteps.value.find(step => step.key === deployExecuting.value) || null
)
const parseReady = ref(false)

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
  platformIframeAppId.value = null
  platformLoading.value = false
  platformError.value = ''
  platformLoginHint.value = ''

  docVersions.value = []
  docVersionsLoading.value = false
  docVersionPreviewVisible.value = false
  docVersionPreviewContent.value = ''
  docVersionPreviewTitle.value = ''
  docVersionDiffVisible.value = false
  docVersionDiffLeft.value = ''
  docVersionDiffRight.value = ''
  docVersionDiffLeftTitle.value = ''
  docVersionDiffRightTitle.value = ''

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
    // 已在平台上的应用（导入或已部署），不自动弹出部署面板
    // 但如果用户已经手动打开了面板（如点了"更新部署"），保持打开
    if (!deployOpen.value) {
      const alreadyOnPlatform = !!store.currentApp?.apaas_app_id
      if (!alreadyOnPlatform) {
        deployOpen.value = deploySteps.value.length > 0
      }
    }
    if (deploySteps.value.length && deploySteps.value.every(step => step.status === 'completed')) {
      await refreshCurrentAppRemoteMeta(deployAppId.value)
    }
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
  } catch (e: any) {
    const detail = e?.response?.data?.detail || e?.message || '失败'
    if (String(detail).includes('重新连接APaaS平台') || String(detail).includes('Token已过期或无效')) {
      ElMessage.warning('平台登录已失效，请先重新连接平台环境')
      store.showConnectModal = true
    } else {
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
    const detail = e?.response?.data?.detail || e?.message || '失败'
    if (String(detail).includes('重新连接APaaS平台') || String(detail).includes('Token已过期或无效')) {
      ElMessage.warning('平台登录已失效，请先重新连接平台环境')
      store.showConnectModal = true
    } else {
      ElMessage.error(detail)
    }
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
                // 从 data.data 同步模型和字典（纯规则提取时 batch 事件可能未被接收）
                if (!store.preview.models.length && Array.isArray(data.data.models) && data.data.models.length) {
                  store.preview.models = data.data.models
                }
                if (!store.preview.dicts.length && Array.isArray(data.data.dicts) && data.data.dicts.length) {
                  store.preview.dicts = data.data.dicts
                }
                if (!store.preview.permissions?.length && Array.isArray(data.data.permissions) && data.data.permissions.length) {
                  store.preview.permissions = data.data.permissions
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
    } else if (store.preview.models.length > 0 || store.preview.dicts.length > 0 || store.preview.roles.length > 0) {
      // done 事件未收到（大 payload SSE 丢失），但 progress 已逐步推送了数据到 store
      console.warn('done 事件丢失，使用 store 中已累积的数据兜底')
      if (!store.currentApp) {
        store.currentApp = { name: store.preview.appName || '未命名应用', status: 'draft' }
      }
      parseReady.value = true
      lastParsedFilename.value = file.name
      latestDocContent.value = fileText

      // 自动创建 Application
      if (!existingAppId.value && store.preview.appName) {
        try {
          const result = await applicationApi.autoCreate({
            app_name: store.preview.appName,
            config_preview: { ...store.preview },
          })
          existingAppId.value = result.app_id
          loadedAppCode.value = result.app_code || ''
          router.replace({ query: { ...route.query, app_id: String(result.app_id) } })
        } catch (e) {
          console.warn('兜底模式创建应用失败:', e)
        }
      }

      if (pmsg) {
        phases.complete.status = 'done'
        phases.complete.detail = `${store.preview.models.length} 模型, ${store.preview.dicts.length} 字典, ${store.preview.roles.length} 角色`
        pmsg.content = buildProgressContent() + '\n\n配置已就绪（流式累积模式）。'
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

  // 图片文件 → 作为附件附加到输入框
  if (file.type.startsWith('image/')) {
    attachedImage.value = file
    if (attachedImageUrl.value) URL.revokeObjectURL(attachedImageUrl.value)
    attachedImageUrl.value = URL.createObjectURL(file)
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
            store.currentApp = { name: store.preview.appName, status: 'ready' }
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
      content: `解析信息已生成！${store.preview.models.length} 个模型、${store.preview.dicts.length} 个字典、${store.preview.roles.length} 个角色。\n\n你可以继续补充右侧解析内容，确认无误后再点击 **开始部署**。`,
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

// ── 截图粘贴 ──
const handleImagePaste = (e: ClipboardEvent) => {
  const items = e.clipboardData?.items
  if (!items) return
  for (const item of Array.from(items)) {
    if (item.kind === 'file' && item.type.startsWith('image/')) {
      e.preventDefault()
      const file = item.getAsFile()
      if (file) {
        const ext = item.type.split('/')[1] || 'png'
        attachedImage.value = new File([file], `screenshot-${Date.now()}.${ext}`, { type: item.type })
        if (attachedImageUrl.value) URL.revokeObjectURL(attachedImageUrl.value)
        attachedImageUrl.value = URL.createObjectURL(attachedImage.value)
      }
      break
    }
  }
}

const removeAttachedImage = () => {
  attachedImage.value = null
  if (attachedImageUrl.value) {
    URL.revokeObjectURL(attachedImageUrl.value)
    attachedImageUrl.value = ''
  }
}

const sendMessage = async () => {
  const hasImage = !!attachedImage.value
  if (!inputText.value.trim() && !hasImage) return
  const text = inputText.value.trim()
  const imageFile = attachedImage.value
  inputText.value = ''
  removeAttachedImage()

  const displayContent = hasImage ? (text || '已上传截图') + (imageFile ? ` 📷${imageFile.name}` : '') : text
  messages.push({ id: Date.now(), role: 'user', content: displayContent, created_at: '' })
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

    let chatUrl: string
    let chatBody: BodyInit
    let headers: Record<string, string> = { 'Authorization': `Bearer ${token}` }

    if (imageFile) {
      // 有图片：用 FormData 走 /chat/send-with-file
      chatUrl = `${API_PREFIX}/chat/send-with-file`
      const fd = new FormData()
      fd.append('conversation_id', String(conversationId.value))
      fd.append('message', text)
      fd.append('file', imageFile)
      if (existingAppId.value && store.preview.appName) {
        fd.append('current_config', JSON.stringify({ ...store.preview }))
      }
      chatBody = fd
    } else {
      // 纯文本：JSON 走 /chat/send
      chatUrl = `${API_PREFIX}/chat/send`
      chatBody = JSON.stringify({
        conversation_id: conversationId.value,
        message: text,
        ...(existingAppId.value && store.preview.appName ? { current_config: { ...store.preview } } : {})
      })
      headers['Content-Type'] = 'application/json'
    }

    const response = await fetch(chatUrl, {
      method: 'POST',
      headers,
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
            } else if (parsed.type === 'error') {
              isTyping.value = false
              const detail = parsed.data || '模型返回异常，请切换模型后重试。'
              messages.push({
                id: Date.now(),
                role: 'assistant',
                agent: currentAgent.value,
                content: `当前模型暂时不可用：${detail}`,
                created_at: ''
              })
              scrollToBottom()
              return
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

  // 添加进度提示消息
  const progressMsgId = Date.now()
  messages.push({
    id: progressMsgId, role: 'assistant', agent: 'builder',
    content: '⏳ 正在根据需求生成应用配置，请稍候...',
    created_at: ''
  })
  scrollToBottom()

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
            if (data.content) {
              // 实时更新进度消息内容
              const progressMsg = messages.find(m => m.id === progressMsgId)
              if (progressMsg) progressMsg.content = '⏳ ' + data.content
              scrollToBottom()
            }
            if (data.doc_result) {
              docResultForCard.value = data.doc_result
            }
          } catch { /* ignore */ }
        }
      }
    }

    // 移除进度消息，DesignDocCard 会显示结果
    const idx = messages.findIndex(m => m.id === progressMsgId)
    if (idx >= 0) messages.splice(idx, 1)

    if (docResultForCard.value) {
      scrollToBottom()
    }
  } catch (e: any) {
    console.error('Background doc generation failed:', e)
    const progressMsg = messages.find(m => m.id === progressMsgId)
    if (progressMsg) progressMsg.content = '⚠️ 配置生成失败，请重新描述需求后重试。'
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

const buildDocMarkdownFromPreview = () => {
  const appName = store.preview.appName || '未命名应用'
  const appCode = displayAppCode.value
  const roleLines = (store.preview.roles || []).map((role: any) => `| ${role?.code || ''} | ${role?.name || ''} | ${role?.description || ''} |`)
  const dictBlocks = (store.preview.dicts || []).map((dict: any) => {
    const options = (dict?.options || []).map((item: any) => {
      const name = typeof item === 'string' ? item : (item?.name || item?.item_name || '')
      const code = typeof item === 'string' ? '' : (item?.code || item?.item_code || '')
      return `| ${code} | ${name} |`
    })
    return `### ${dict?.name || dict?.code || '未命名字典'} (${dict?.code || ''})\n\n| 编码 | 名称 |\n|---|---|\n${options.join('\n') || '| - | - |'}`
  })
  const tableBlocks = (store.preview.models || []).map((model: any) => {
    const fields = (model?.fields || []).map((field: any) => `| ${field?.code || ''} | ${field?.name || ''} | ${field?.type || ''} |`)
    return `### ${model?.name || model?.code || '未命名模型'} (${model?.code || ''})\n\n| 字段编码 | 字段名称 | 字段类型 |\n|---|---|---|\n${fields.join('\n') || '| - | - | - |'}`
  })
  return [
    `# ${appName}`,
    '',
    '## 一、应用信息',
    '',
    `应用编码：${appCode}`,
    `应用名称：${appName}`,
    '',
    '## 二、角色清单',
    '',
    '| 角色编码 | 角色名称 | 职责描述 |',
    '|---|---|---|',
    roleLines.join('\n') || '| - | - | - |',
    '',
    '## 三、数据字典',
    '',
    dictBlocks.join('\n\n') || '暂无',
    '',
    '## 四、数据模型',
    '',
    tableBlocks.join('\n\n') || '暂无',
    '',
  ].join('\n')
}

const downloadCurrentDoc = () => {
  const content = (latestDocContent.value || '').trim() || buildDocMarkdownFromPreview()
  const filename = lastParsedFilename.value || `${store.preview.appName || '功能设计文档'}.md`
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename.endsWith('.md') ? filename : `${filename}.md`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

const formatContent = (t: string) => {
  // 过滤 <think> 思考内容（包括流式传输中未闭合的 <think> 标签）
  let text = t.replace(/<think>[\s\S]*?<\/think>/g, '')
  text = text.replace(/<think>[\s\S]*$/g, '')  // 未闭合的 <think> 也隐藏
  // 隐藏JSON代码块，只显示文字部分
  text = text.replace(/```json[\s\S]*?```/g, '')
  // 清理多余空行
  text = text.replace(/\n{3,}/g, '\n\n').trim()
  return text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>').replace(/• /g, '<span style="color:#818cf8;margin-right:4px">•</span> ')
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

  // ── 优先通过 app_id 加载应用（应用为锚点）──
  const appIdParam = route.query.app_id as string
  if (appIdParam) {
    const aid = Number(appIdParam)
    if (aid) {
      existingAppId.value = aid
      try {
        const app = await applicationApi.get(aid) as any
        // 恢复配置
        let configData: any = null
        if (app.config_preview) {
          const data = app.config_preview.data || app.config_preview
          configData = data
          store.preview.appName = data.appName || app.app_name || ''
          store.preview.models = data.models || []
          store.preview.dicts = data.dicts || []
          store.preview.roles = data.roles || []
          store.preview.workflows = data.workflows || []
          store.preview.permissions = data.permissions || []
          store.currentApp = { name: store.preview.appName, status: app.status || 'ready', apaas_app_id: app.apaas_app_id }
          parseReady.value = store.preview.models.length > 0
          currentAgent.value = 'builder'
        }
        loadedAppCode.value = app.app_code || pickAppCode(configData) || ''
        parsedAppCode.value = parsedAppCode.value || loadedAppCode.value
        deployAppId.value = aid
        await loadDeployStatus()
        await refreshCurrentAppRemoteMeta(aid)
        await restoreActiveViewForApp(app)
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
                deployAppId.value = linkedApp.id
                await loadDeployStatus()
                await refreshCurrentAppRemoteMeta(linkedApp.id)
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
        let configData: any = null
        if (app.config_preview) {
          const data = app.config_preview.data || app.config_preview
          configData = data
          store.preview.appName = data.appName || app.app_name || ''
          store.preview.models = data.models || []
          store.preview.dicts = data.dicts || []
          store.preview.roles = data.roles || []
          store.currentApp = { name: store.preview.appName, status: app.status || 'ready' }
          parseReady.value = store.preview.models.length > 0
          currentAgent.value = 'builder'
        }
        loadedAppCode.value = app.app_code || pickAppCode(configData) || ''
        parsedAppCode.value = parsedAppCode.value || loadedAppCode.value
        deployAppId.value = aid
        await loadDeployStatus()
        await refreshCurrentAppRemoteMeta(aid)
        await restoreActiveViewForApp(app)
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
  // 只有真正“新建会话”时才创建 requirements，对已有 app 不要覆盖恢复结果
  if (!conversationId.value && !existingAppId.value && !store.pendingMarkdown && !store.pendingFile) {
    resetConversationWorkspace()
    currentAgent.value = 'requirements'
    resetMessagesToWelcome()
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
      resetMessagesToWelcome()
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
  store.preview.dicts = []
  store.preview.roles = []
  store.preview.workflows = []
  store.preview.permissions = []
  store.preview.appName = ''
  store.currentApp = null
  latestDocContent.value = ''
  conversationId.value = null
  activeView.value = 'builder'
  platformIframeUrl.value = ''
  platformAppUrl.value = ''
  platformIframeAppId.value = null
  platformLoading.value = false
  platformError.value = ''
  platformLoginHint.value = ''

  try {
    const app = await applicationApi.get(aid) as any
    let configData: any = null
    if (app.config_preview) {
      const data = app.config_preview.data || app.config_preview
      configData = data
      store.preview.appName = data.appName || app.app_name || ''
      store.preview.models = data.models || []
      store.preview.dicts = data.dicts || []
      store.preview.roles = data.roles || []
      store.preview.workflows = data.workflows || []
      store.preview.permissions = data.permissions || []
      store.currentApp = { name: store.preview.appName, status: app.status || 'ready', apaas_app_id: app.apaas_app_id }
      parseReady.value = store.preview.models.length > 0
      currentAgent.value = 'builder'
    }
    loadedAppCode.value = app.app_code || pickAppCode(configData) || ''
    parsedAppCode.value = loadedAppCode.value || parsedAppCode.value
    await restoreActiveViewForApp(app)
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

watch(activeView, (view) => {
  if (existingAppId.value) {
    localStorage.setItem(getAppViewStorageKey(existingAppId.value), view)
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
.mode-switcher {
  display: flex;
  gap: 4px;
  padding: 4px;
  background: rgba(245, 247, 255, 0.92);
  border: 1px solid rgba(128, 145, 255, 0.14);
  border-radius: 14px;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.65);
}
.mode-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 34px;
  padding: 0 14px;
  border-radius: 10px;
  font-size: 12px;
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
  box-shadow: 0 8px 18px rgba(92, 115, 255, 0.1);
}
.mode-btn-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
  opacity: 0.42;
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.mode-btn.active .mode-btn-dot { opacity: 1; transform: scale(1.1); }
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
.builder-generate-btn.btn-ready {
  background: linear-gradient(135deg, #34a853 0%, #1d8e3e 100%);
  opacity: 0.85;
  cursor: default;
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
  border-radius: 8px;
  height: 28px;
  padding: 0 10px;
  font-size: 12px;
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
.bubble-inner { max-width: 80%; }
.bubble-inner.welcome-bubble { max-width: min(620px, 92%); }
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
  align-items: flex-end;
  gap: 6px;
  padding: 3px 5px 5px;
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
  font-size: 11px;
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
/* 截图粘贴预览 */
.attached-image-preview {
  position: relative; display: inline-block; margin-bottom: 6px;
}
.attached-image-preview img {
  max-height: 80px; max-width: 200px; border-radius: 8px;
  border: 1px solid var(--t-border-subtle); object-fit: cover;
}
.attached-image-remove {
  position: absolute; top: -6px; right: -6px;
  width: 18px; height: 18px; border-radius: 50%;
  background: var(--t-danger, #ef4444); color: #fff;
  border: none; font-size: 12px; line-height: 1;
  cursor: pointer; display: flex; align-items: center; justify-content: center;
}
.send-btn:hover:not(.disabled) { opacity: 0.92; transform: translateY(-1px); box-shadow: 0 14px 24px rgba(92, 115, 255, 0.28); }
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
.doc-preview-content {
  margin: 0;
  min-height: 360px;
  max-height: calc(100vh - 340px);
  overflow: auto;
  padding: 24px 28px;
  border-radius: 16px;
  background: #fff;
  border: 1px solid rgba(128, 145, 255, 0.1);
  color: #2c3e50;
  font-size: 13px;
  line-height: 1.7;
  word-break: break-word;
}
.doc-rendered :deep(h1) { font-size: 22px; font-weight: 600; color: #1a1a2e; margin: 0 0 16px; padding-bottom: 8px; border-bottom: 2px solid #eef0f8; }
.doc-rendered :deep(h2) { font-size: 16px; font-weight: 600; color: #26215C; margin: 24px 0 12px; padding-bottom: 6px; border-bottom: 1px solid #eef0f8; }
.doc-rendered :deep(h3) { font-size: 14px; font-weight: 600; color: #333; margin: 18px 0 8px; }
.doc-rendered :deep(h4) { font-size: 13px; font-weight: 600; color: #555; margin: 14px 0 6px; }
.doc-rendered :deep(hr) { border: none; border-top: 1px solid #e8ecf4; margin: 16px 0; }
.doc-rendered :deep(p) { margin: 6px 0; }
.doc-rendered :deep(table) { width: 100%; border-collapse: collapse; margin: 8px 0 16px; font-size: 12px; }
.doc-rendered :deep(th) { background: #f5f6fa; color: #333; font-weight: 600; text-align: left; padding: 8px 10px; border: 1px solid #e2e5ef; white-space: nowrap; }
.doc-rendered :deep(td) { padding: 6px 10px; border: 1px solid #e8ecf0; color: #444; vertical-align: top; }
.doc-rendered :deep(tr:hover td) { background: #fafbff; }
.doc-rendered :deep(code) { background: #f0f2f8; padding: 1px 5px; border-radius: 3px; font-size: 12px; color: #534AB7; }
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
.preview-side-cta.success {
  background: linear-gradient(135deg, #16a34a 0%, #22c55e 100%);
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
  max-width: 320px;
  margin: 72px auto 0;
  padding: 0;
  color: #8b97ae;
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
.model-name { font-weight: 600; color: var(--t-text-primary); }
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
.preview-item-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--t-text-primary);
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
.dg-icon { font-size: 13px; }
.dg-name { font-weight: 600; color: var(--t-text-primary); flex: 1; }
.dg-badge { font-size: 9px; padding: 1px 6px; border-radius: 99px; font-weight: 600; background: var(--t-border-subtle); color: var(--t-text-muted); }
.dg-badge.done { background: rgba(16,185,129,0.12); color: var(--t-success); }
.dg-badge.err { background: rgba(239,68,68,0.12); color: var(--t-danger); }

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
  position: fixed;
  inset: 0;
  z-index: 2000;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
}
.change-plan-panel {
  background: var(--t-bg-base, #1a1a2e);
  border-radius: 12px;
  border: 1px solid var(--t-border-subtle, #333);
  width: 720px;
  max-width: 90vw;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 24px 48px rgba(0, 0, 0, 0.4);
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
  justify-content: space-between;
  padding: 12px 20px;
  border-top: 1px solid var(--t-border-subtle);
}
.change-plan-count { font-size: 12px; color: var(--t-text-secondary); }
.change-plan-actions { display: flex; gap: 8px; }
.change-plan-actions .btn-cancel {
  padding: 6px 16px; border-radius: 6px; border: 1px solid var(--t-border-strong);
  background: var(--t-bg-subtle); color: var(--t-text-secondary); font-size: 13px; cursor: pointer;
}
.change-plan-actions .btn-cancel:hover { background: var(--t-border-subtle); color: #fff; }
.change-plan-actions .btn-execute {
  padding: 6px 16px; border-radius: 6px; border: none;
  background: var(--t-brand, #7c3aed); color: #fff; font-size: 13px; cursor: pointer;
}
.change-plan-actions .btn-execute:hover { background: #6d28d9; }
.change-plan-actions .btn-execute:disabled { opacity: 0.4; cursor: not-allowed; }
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
