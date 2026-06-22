<template>
  <BuilderFrame :breadcrumbs="[]" :class="{ 'is-embedded': embedMode }">
    <!-- Env Picker Dialog -->
    <el-dialog v-model="showEnvPicker" title="选择调试平台环境" width="500px" :append-to-body="true">
      <div v-if="platformEnvs.length === 0" style="text-align:center;color:var(--text-3);padding:20px;">
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
          style="border:1px solid var(--line);border-radius:8px;padding:16px;cursor:pointer;transition:all 0.2s;"
          :style="{ borderColor: env.status === 'connected' ? 'var(--ok)' : 'var(--line)' }"
          @click="openBrowserPreviewWithEnv(env)"
        >
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <strong>{{ env.env_name }}</strong>
            <el-tag v-if="env.status === 'connected'" type="success" size="small">已连接</el-tag>
            <el-tag v-else type="info" size="small">未连接</el-tag>
          </div>
          <div style="color:var(--text-3);font-size:12px;margin-top:6px;">{{ env.base_url }}</div>
        </div>
      </div>
    </el-dialog>

    <div class="coding-body" :class="{ 'code-first': codeFirst }">
      <SessionSidebar
        v-if="!embedMode && !embeddedAppId && !codeFirst && !useRailSessions"
        module-name="代码工作区"
        brand-color="#6366f1"
        :sessions="sidebarCodingItems"
        :active-id="sidebarCodingActiveId"
        collapse-key="coding:aside-collapsed"
        empty-hint="还没有会话，点上面新建一个"
        :enable-rename="false"
        @select="onSidebarCodingSelect"
        @create="onSidebarCodingCreate"
        @delete="onSidebarCodingDelete"
      />
      <!-- Main Content: 对话流 (B 重构 2026-05-17): 合并 Welcome / Chat / IDE -->
      <!-- 代码为主布局下,main-content 收成右侧聊天列(宽度可拖拽);否则维持原全宽 -->
      <div class="main-content">
        <!-- 顶右工具抽屉按钮 (替代 view-toggle-bar): 文件 / 设置 / 产物 -->
        <div
          v-if="!embeddedAppId && !codeFirst && streamMessages.length > 0"
          class="canvas-actions"
        >
          <button class="canvas-actions-back" @click="startNewWorkspace" title="返回首页">
            <el-icon :size="14"><ArrowLeft /></el-icon>
            <span>返回</span>
          </button>
          <div class="canvas-actions-right">
            <button class="canvas-action-btn" @click="filesDrawerOpen = true" title="文件">
              <el-icon :size="14"><Document /></el-icon>
              <span class="canvas-action-label">文件</span>
            </button>
            <button class="canvas-action-btn" @click="editDrawerOpen = true" title="设置">
              <el-icon :size="14"><Setting /></el-icon>
              <span class="canvas-action-label">设置</span>
            </button>
            <button
              class="canvas-action-btn"
              :class="{ active: showCodingArtifactPanel }"
              @click="toggleCodingArtifactPanel"
              :title="showCodingArtifactPanel ? '隐藏产物面板' : '查看产物 / 接入说明'"
            >
              <el-icon :size="14"><Box /></el-icon>
              <span class="canvas-action-label">产物</span>
              <span v-if="codingArtifactsHasAny" class="cap-count-pill">{{ codingArtifacts.new.length + codingArtifacts.modified.length }}</span>
            </button>
          </div>
        </div>

        <!-- Stream Pane (对话流视图): 永远显示。全新会话=对话优先欢迎页(可直接输入 + 打开本地文件夹), IDE/文件改抽屉 -->
        <div class="stream-pane">
          <header class="coding-session-header">
            <div class="coding-session-title-block">
              <span class="coding-session-kicker">代码工作区</span>
              <strong class="coding-session-title">{{ activeCodingSessionTitle }}</strong>
            </div>
            <!-- F3: Builder→Coding handoff 来源应用的「← 回 Builder」回跳链 -->
            <button
              v-if="handoffSourceApp"
              class="coding-back-to-builder"
              @click="backToBuilder"
              :title="`回到 AI Builder 配置「${handoffSourceApp.name}」`"
            >
              <el-icon :size="14"><ArrowLeft /></el-icon>
              <span>回 Builder 配置「{{ handoffSourceApp.name }}」</span>
            </button>
            <!-- code-first 三栏布局没有会话侧栏 → 头部补 会话历史/新建/放大(对齐配置助手) -->
            <div v-if="codeFirst" class="coding-chat-actions">
              <el-popover placement="bottom-end" :width="300" trigger="click">
                <template #reference>
                  <button class="cca-btn" title="会话历史"><AppIcon name="menu" :size="15" /></button>
                </template>
                <div class="cca-conv-list">
                  <button
                    v-for="c in headerConversations"
                    :key="c.id"
                    class="cca-conv-item"
                    :class="{ active: c.id === codingStore.conversationId }"
                    @click="switchConversationFromHeader(c.id)"
                  >
                    <span class="cca-conv-title">{{ c.title || '未命名会话' }}</span>
                    <span class="cca-conv-time">{{ formatConvTime(c.updated_at) }}</span>
                  </button>
                  <p v-if="!headerConversations.length" class="cca-conv-empty">当前工作区还没有其他会话</p>
                </div>
              </el-popover>
              <button class="cca-btn" title="新建会话(沿用当前工作区)" @click="createWorkspaceConversation">
                <AppIcon name="plus" :size="15" />
              </button>
              <button
                v-if="currentGitAppId"
                class="cca-btn"
                :class="{ active: !!currentAppGitRepoUrl }"
                :disabled="syncingToRepo"
                :title="currentGitActionTitle"
                @click="currentAppGitRepoUrl ? onSyncToRepo() : openGitSetupForCurrentApp()"
              >
                <AppIcon :name="syncingToRepo ? 'refresh' : 'link'" :size="14" />
              </button>
              <button class="cca-btn" :class="{ active: codePaneOpen }" title="代码 / 文件" @click="codePaneOpen = !codePaneOpen">
                <AppIcon name="coding" :size="14" />
              </button>
            </div>
          </header>

          <!-- 全新会话: 对话优先欢迎页(参考 Claude Code/Codex)。说一句直接开始(下方输入框),
               或打开本地文件夹 / 去我的开发打开已有工作区。 -->
          <div v-if="isCodeWelcome" class="coding-new-welcome">
            <div class="cnw-hero">
              <h2><AppIcon name="coding" :size="20" /> 全代码开发</h2>
              <p>说出你要开发什么，睿鲸会自动建工作区直接开始。也可以打开本地文件夹继续已有项目。</p>
            </div>
            <div class="cnw-entries">
              <button v-if="isDesktop" type="button" class="cnw-entry" @click="openLocalFolderInCoding">
                <AppIcon name="folder" :size="16" />
                <span>打开本地文件夹</span>
              </button>
              <button type="button" class="cnw-entry" @click="router.push('/workspace-catalog')">
                <AppIcon name="store" :size="16" />
                <span>我的开发 / 导入源码</span>
              </button>
            </div>
            <p class="cnw-hint">在下方输入框描述需求，回车即开始 ↓</p>
          </div>

          <CodingSceneEntry
            v-else-if="!isStreaming && streamMessages.length === 0 && !codeFirst"
            :apps="sceneApps"
            :default-app-id="sceneDefaultAppId"
            @submit="onSceneSubmit"
          />

          <AgentConversation
            v-else
            :messages="agentMessages"
            :typing="isStreaming"
            :typing-seconds="streamSeconds"
            empty-title=""
            empty-hint=""
            @answer-ask="onAnswerAsk"
            @click.capture="onChatClick"
          >
            <!-- codeFirst 空态: 按工作区生成建议提问, 点击直接发送(解决冷启动) -->
            <template v-if="codeFirst" #empty>
              <div class="ac-empty-default coding-empty">
                <h2><AppIcon name="wave" :size="18" /> 开始对话</h2>
                <p>问代码、查改动，或直接说要改什么。</p>
                <div v-if="emptySuggestions.length" class="coding-empty-suggestions">
                  <button
                    v-for="s in emptySuggestions"
                    :key="s"
                    class="ces-chip"
                    @click="sendSuggestion(s)"
                  >{{ s }}</button>
                </div>
              </div>
            </template>
            <template #custom="{ message }">
              <template v-if="streamCustom(message)?.sm">
                <!-- file_write / file_edit（native 无对应 kind,保留 FileCard）-->
                <template v-if="['file_write', 'file_edit'].includes(streamCustom(message).sm.type)">
                  <FileCard
                    :action="streamCustom(message).sm.type === 'file_write' ? 'write' : 'edit'"
                    :file-name="streamCustom(message).sm.fileName"
                    :file-content="streamCustom(message).sm.fileContent"
                    :old-content="streamCustom(message).sm.oldContent"
                    :collapsed="streamCustom(message).sm.collapsed"
                    :openable="codeFirst"
                    @toggle="streamCustom(message).sm.collapsed = !streamCustom(message).sm.collapsed"
                    @open="openFileFromChat(streamCustom(message).sm)"
                  />
                </template>
                <!-- command（native 无对应 kind,保留命令卡）-->
                <template v-else-if="streamCustom(message).sm.type === 'command'">
                  <div class="msg-command-card">
                    <div class="command-card-header">
                      <span class="command-prompt">$</span>
                      <span class="command-text">{{ streamCustom(message).sm.content.split('\n')[0] }}</span>
                    </div>
                    <pre v-if="streamCustom(message).sm.content.includes('\n')" class="command-output">{{ streamCustom(message).sm.content.split('\n').slice(1).join('\n') }}</pre>
                  </div>
                </template>
                <!-- reasoning 思维链折叠卡（默认收起）-->
                <template v-else-if="streamCustom(message).sm.type === 'reasoning'">
                  <div class="msg-reasoning-card">
                    <button type="button" class="mrc-head" @click="streamCustom(message).sm.collapsed = !streamCustom(message).sm.collapsed">
                      <span class="mrc-caret">{{ streamCustom(message).sm.collapsed ? '▶' : '▼' }}</span>
                      <span>💭 思考过程</span>
                    </button>
                    <div v-if="!streamCustom(message).sm.collapsed" class="mrc-body" v-html="renderMarkdown(streamCustom(message).sm.content)"></div>
                  </div>
                </template>
                <!-- run_result（对话驱动运行/调试结果卡）-->
                <template v-else-if="streamCustom(message).sm.type === 'run_result' && streamCustom(message).sm.run">
                  <div class="coding-run-card">
                    <div class="rc-head">
                      <span class="rc-dot" :class="streamCustom(message).sm.run.status" />
                      <span class="rc-title">
                        {{ streamCustom(message).sm.run.source === 'autofix' ? `自愈第 ${streamCustom(message).sm.run.round + 1} 轮` : '运行预览' }}
                        · {{ rcStatusText(streamCustom(message).sm.run) }}
                      </span>
                      <button v-if="streamCustom(message).sm.run.dev_url" class="rc-link" @click="focusPreview(streamCustom(message).sm.run)">查看预览</button>
                    </div>
                    <div v-if="streamCustom(message).sm.run.dev_url" class="rc-url">{{ streamCustom(message).sm.run.dev_url }}</div>
                    <ul v-if="streamCustom(message).sm.run.errors.length" class="rc-errs">
                      <li v-for="(e, ei) in streamCustom(message).sm.run.errors.slice(0, 5)" :key="ei">{{ e }}</li>
                    </ul>
                  </div>
                </template>
                <!-- thinking / status / tool 已迁移到 AgentConversation 原生 kind（见 agentMessages 映射）-->
              </template>
            </template>

            <!-- 2026-05-19 删 list-suffix "打开代码编辑器" 大按钮 — 顶部 toolbar
                 已有 IDE 按钮做同样事（image #24 冗余反馈）-->
            <template #list-suffix>
              <div v-if="false" />
            </template>
          </AgentConversation>

          <!-- SPEC 确认门:出了开发 SPEC、待确认 → 一键「确认开发」+ 提示可直接补充调整(不一股脑直接开发) -->
          <div v-if="awaitingSpecConfirm" class="coding-confirm-bar">
            <div class="ccb-text">
              <strong>开发 SPEC 已生成，待你确认</strong>
              <span>完整 SPEC 在右侧「开发文档」查看；确认无误即开始写代码，要调整就直接在下方补充需求。</span>
            </div>
            <div class="ccb-actions">
              <button class="ccb-btn-ghost" @click="openCodingArtifactTab('spec')">
                <el-icon :size="15"><Document /></el-icon>
                <span>查看开发文档</span>
              </button>
              <button class="ccb-btn" @click="confirmSpec">
                <el-icon :size="16"><CircleCheck /></el-icon>
                <span>确认，开始开发</span>
              </button>
            </div>
          </div>

          <!-- 完成态卡片已去掉；发布入口收进下方输入区 footer（codegen 完成且有产物时出现）-->

          <!-- Chat 底部输入框: 非嵌入模式永远可见(含全新会话,修「新建空白没法输入」);流式中也能输入排队;红色按钮停止 -->
          <div v-if="showCodingComposer" class="chat-input-bar">
            <!-- 上下文过长告警 banner(建议新建会话) -->
            <div v-if="showContextWarning" class="ctx-warn-banner" :class="`lvl-${ctxLevel}`">
              <span class="ctx-warn-text">上下文较长({{ ctxPct }}%),建议新建会话以保持流畅</span>
              <button class="ctx-warn-new" @click="createWorkspaceConversation">一键新建会话</button>
              <button class="ctx-warn-close" title="本会话不再提醒" @click="dismissContextWarn">
                <AppIcon name="x" :size="14" />
              </button>
            </div>
            <!-- 排队提示卡:流式中再输入会进队列,当前回复结束后自动发送(对齐 AI Builder) -->
            <div v-if="pendingQueue.length > 0" class="coding-queue-banner">
              <span class="cqb-icon"><AppIcon name="clock" :size="13" /></span>
              <span class="cqb-text">{{ pendingQueue.length }} 条消息排队中 · 当前回复结束后自动发送</span>
              <button class="cqb-clear" title="清空队列" @click="pendingQueue = []"><AppIcon name="x" :size="14" /></button>
            </div>
            <UnifiedChatComposer
              v-model="userInput"
              :attachments="codingComposerAttachments"
              :sending="codingBusy"
              :show-stop="true"
              :allow-send-while-sending="true"
              :send-disabled="!userInput.trim()"
              accept=".md,.pdf,.docx,.txt,.png,.jpg,.jpeg"
              hint=""
              sending-hint=""
              placeholder="输入需求，粘贴图片或点附件..."
              :skills="availableSkills"
              @skill-picked="onSkillPicked"
              @send="sendOrQueue"
              @stop="stopStream"
              @files-picked="handleComposerFiles"
              @remove-attachment="removeAttachment"
            >
              <template #footer-left>
                <div
                  ref="codingModelPickerRef"
                  class="coding-model-picker"
                  :class="{ 'is-disabled': codingModelPickerDisabled }"
                >
                  <button
                    type="button"
                    class="coding-model-trigger"
                    :class="{ 'is-open': codingModelMenuOpen }"
                    :disabled="codingModelPickerDisabled"
                    :title="codingModelHint"
                    aria-haspopup="listbox"
                    :aria-expanded="codingModelMenuOpen"
                    aria-label="选择模型"
                    @click.stop="toggleCodingModelMenu"
                    @keydown.esc.stop="codingModelMenuOpen = false"
                  >
                    <span class="coding-model-trigger-text">{{ selectedCodingModelLabel }}</span>
                    <el-icon :size="13"><ArrowDown /></el-icon>
                  </button>
                  <div
                    v-if="codingModelMenuOpen"
                    class="coding-model-menu"
                    role="listbox"
                    aria-label="选择模型"
                  >
                    <button
                      v-for="option in codingModelOptions"
                      :key="option.id"
                      type="button"
                      class="coding-model-option"
                      :class="{ 'is-selected': selectedCodingModelValue === toCodingModelValue(option.id) }"
                      role="option"
                      :aria-selected="selectedCodingModelValue === toCodingModelValue(option.id)"
                      @click.stop="chooseCodingModel(toCodingModelValue(option.id))"
                    >
                      <span class="coding-model-option-name">{{ option.config_name }}</span>
                      <span class="coding-model-option-meta">{{ option.provider }} / {{ option.model }}</span>
                    </button>
                  </div>
                </div>
                <span
                  v-if="codingStore.tokenUsage"
                  class="coding-token-usage"
                  :class="`lvl-${ctxLevel}`"
                  :title="`当前上下文占用 ${ctxPct}%(预算 ${codingStore.tokenUsage.contextBudget} tok)· 本会话累计 ${cumTokenText} tok`"
                >上下文 {{ ctxPct }}% · 累计 {{ cumTokenText }} tok</span>
              </template>
            </UnifiedChatComposer>
          </div>
        </div>

      </div>

      <!-- 代码侧栏(对话优先, 参考 Claude Code): 与对话并排推出(不遮挡对话), 文件树 + 查看器 + 预览;
           侧栏左边界可拖宽; × 收起回全宽对话。 -->
      <div
        v-if="codePaneOpen && codingStore.workspace?.id"
        class="ws-pane"
        :style="{ flex: '0 0 ' + codePaneWidth + 'px', width: codePaneWidth + 'px' }"
      >
        <div class="ws-pane-resizer" title="拖拽调整代码栏宽度" @pointerdown="onCodePaneResizeStart" />
        <div class="ws-pane-tabs">
          <button :class="{ active: wsPaneTab === 'files' }" @click="wsPaneTab = 'files'">文件 / 代码</button>
          <button :class="{ active: wsPaneTab === 'run' }" @click="wsPaneTab = 'run'">预览</button>
          <button class="ws-pane-close" title="收起代码栏" @click="codePaneOpen = false">
            <AppIcon name="x" :size="15" />
          </button>
        </div>
        <div v-show="wsPaneTab === 'files'" class="ws-pane-files">
          <FileTree
            class="ws-pane-tree"
            :style="{ width: treePaneWidth + 'px' }"
            :tree="wsFileTree"
            :changed="changedPaths"
            :changes="wsGitChanges"
            :selected="selectedFile"
            :ws-id="codingStore.workspace?.id || ''"
            @select="onTreeSelect"
            @select-line="onTreeSelectLine"
            @accept-all="acceptAllWorkspaceChanges"
          />
          <div class="tree-resizer" title="拖拽调整文件树宽度" @pointerdown="onTreeResizeStart" />
          <CodeViewer
            class="ws-pane-viewer"
            :ws-id="codingStore.workspace?.id || ''"
            :file-path="selectedFile"
            :diff="selectedGitChange ? null : selectedDiff"
            :change="selectedGitChange"
            :focus-line="viewerFocusLine"
            :dark="themeStore.isDark"
            @quote="onViewerQuote"
            @accept-change="acceptWorkspaceChange"
          />
        </div>
        <RunDebugPanel
          v-show="wsPaneTab === 'run'"
          :ws-id="codingStore.workspace?.id || ''"
          :dark="themeStore.isDark"
        />
      </div>

      <!-- 文件抽屉：显示 workspace 文件列表 (P0 留 stub，P1 接 ws files API) -->
      <el-drawer v-model="filesDrawerOpen" title="工作区文件" direction="rtl" size="40%" body-class="coding-files-drawer-body" :append-to-body="true">
        <div class="files-drawer-body">
          <p style="color:var(--text-3);font-size:13px;padding:16px;">
            <AppIcon name="clipboard" :size="13" /> 文件浏览 MVP — 当前展示 workspace 元信息，详细文件树后续接入。
          </p>
          <div v-if="codingStore.workspace" style="padding:0 16px;">
            <div style="margin-bottom:12px;"><strong>名称：</strong>{{ codingStore.workspace.display_name || codingStore.workspace.project_name }}</div>
            <div style="margin-bottom:12px;"><strong>类型：</strong>{{ codingStore.workspace.project_type }}</div>
          </div>
          <div v-else style="padding:16px;color:var(--text-3);">还没有打开工作区</div>
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
            style="color:var(--err);"
            @click="deleteCurrentWorkspace"
          >
            <el-icon :size="14"><Delete /></el-icon>
            <span>删除工作区</span>
          </button>
          <div v-if="!codingStore.workspace" style="color:var(--text-3);">还没有打开工作区</div>
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
            :class="{ active: codingArtifactTab === 'spec' }"
            @click="codingArtifactTab = 'spec'"
          >开发文档</button>
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

        <!-- 开发文档 tab(对标 Builder 设计文档:把开发 SPEC 当一等文档,渲染/原文切换)-->
        <div v-if="codingArtifactTab === 'spec'" class="cap-scroll">
          <template v-if="specMarkdown">
            <div class="cap-spec-bar">
              <div class="cap-spec-seg">
                <button type="button" :class="{ on: specViewMode === 'render' }" @click="specViewMode = 'render'">渲染</button>
                <button type="button" :class="{ on: specViewMode === 'raw' }" @click="specViewMode = 'raw'">原文</button>
              </div>
              <button
                v-if="isBoundDeploy && codingArtifactsHasAny"
                type="button" class="cap-spec-cta" @click="openInstallModal"
              >装回应用</button>
            </div>
            <div v-if="specViewMode === 'render'" class="cap-spec-doc" v-html="renderMarkdown(specMarkdown)"></div>
            <pre v-else class="cap-spec-raw">{{ specMarkdown }}</pre>
          </template>
          <div v-else class="cap-empty">
            <p>暂无开发文档。</p>
            <p class="cap-empty-hint">在左侧描述需求,AI 会先产出「开发 SPEC」——这里就是它的文档视图(可渲染 / 看原文),对标 Builder 的设计文档。</p>
          </div>
        </div>

        <!-- 产物清单 tab -->
        <div v-else-if="codingArtifactTab === 'files'" class="cap-scroll">
          <template v-if="codingArtifactsHasAny">
            <div class="cap-deploy-cta">
              <button class="cap-deploy-btn" @click="openInstallModal">
                {{ isBoundDeploy ? '装回应用' : '发布到资产库' }}
              </button>
              <span class="cap-deploy-hint">{{ isBoundDeploy ? '关联到应用 + 重新发布让组件生效' : '上传到我的开发,跨应用复用' }}</span>
            </div>
            <template v-if="codingArtifacts.new.length > 0">
              <div class="cap-section-head">
                <span class="cap-badge cap-badge-emerald">新增 {{ codingArtifacts.new.length }}</span>
              </div>
              <div
                v-for="(f, idx) in codingArtifacts.new"
                :key="'cn-' + idx + '-' + f.path"
                class="cap-file is-openable"
                title="打开代码"
                @click="openFileFromChat({ filePath: f.path })"
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
                class="cap-file is-openable"
                title="打开代码"
                @click="openFileFromChat({ filePath: f.path })"
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
    <InstallModal
      :visible="installModalVisible"
      :mode="isBoundDeploy ? 'bound' : 'lib'"
      :kit-name="codingStore.workspace?.display_name || codingStore.workspace?.project_name || '自开发包'"
      :app-name="isBoundDeploy ? (sceneApps.find(a => a.id === effectiveDeployAppId)?.name || '应用') : ''"
      :rows="installRows"
      :compiled="true"
      :loading="installLoading"
      @close="installModalVisible = false"
      @confirm="confirmDeploy"
    />
  </BuilderFrame>

</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, ArrowDown, Download, Delete, Fold, Expand, ChatDotRound, Document, Setting, Box, CircleCheck } from '@element-plus/icons-vue'
import { useCodingStore } from '@/stores/coding'
import AppIcon from '@/components/common/AppIcon.vue'
import type { PlatformEnv } from '@/api/platformEnv'
import { useUserStore } from '@/stores/user'
import { codingApi } from '@/api/coding'
import { openExternal, isDesktop, pickDirectory } from '@/utils/desktop'
import type { CodingConversation, WorkspaceInfo, ReplayStreamMessage } from '@/api/coding'
import CodingSceneEntry from './coding/CodingSceneEntry.vue'
import InstallModal from './coding/InstallModal.vue'
import { gitConnectionApi } from '@/api/gitConnection'
import { applicationApi } from '@/api/application'
import { useThemeStore } from '@/stores/theme'
import BuilderFrame from '@/components/BuilderFrame.vue'
import FileCard from '@/components/FileCard.vue'
import SessionSidebar, { type SessionItem as SidebarSessionItem } from '@/components/common/SessionSidebar.vue'
import AgentConversation from '@/components/common/AgentConversation.vue'
import type { AgentMessage, AgentToolPayload } from '@/components/common/agent-conversation/types'
import { useCodingModel } from './coding/useCodingModel'
import { useStreamMessages, renderMarkdown } from './coding/useStreamMessages'
import { formatTokenCount, contextRatio, contextLevel } from './coding/contextUsage'
import { useCodingWorkspace } from './coding/useCodingWorkspace'
import { useCodingPipeline } from './coding/useCodingPipeline'
import UnifiedChatComposer from '@/components/common/UnifiedChatComposer.vue'
import type { UnifiedChatAttachment } from '@/components/common/chatComposer'
import FileTree from './coding/FileTree.vue'
import CodeViewer from './coding/CodeViewer.vue'
import RunDebugPanel from './coding/RunDebugPanel.vue'
import { buildFileTree, type TreeNode } from './coding/fileTree'
import { isCodingWelcome, shouldShowCodingComposer } from './coding/codingLayout'
import { collectChangedFiles, normalizeWorkspacePathLabel, type FileChangeMsg } from './coding/workspaceChanges'
import { usePanelResize } from '@/components/v2/config-assistant/composables/usePanelResize'
import { listWorkspaceFiles, getWorkspaceChanges, acceptWorkspaceChanges, type WorkspaceChanges } from '@/api/coding'
import { listSkills } from '@/api/skills'

const route = useRoute()
const router = useRouter()
const codingStore = useCodingStore()

// Embed mode (?embed=true) used by WorkspaceShell CodeView iframe
// (Phase F Task 9): hides nav rail + topbar via .is-embedded CSS hack.
const embedMode = computed(() => route.query.embed === 'true')
// 2026-06-21: coding 会话收进全局左栏(ModeRail/RailSidebar, 参考 Claude Code 单一左栏),
// 页面内层 SessionSidebar 不再渲染。置 false 即恢复页面内层会话目录。
const useRailSessions = true
const userStore = useUserStore()
const themeStore = useThemeStore()

// ============ Core State ============
const userInput = ref('')
const isCreating = ref(false)

// skill @-pick 接线 (镜像 AIChatPage)
const availableSkills = ref<{ name: string; description: string }[]>([])
onMounted(() => {
  listSkills().then((s) => { availableSkills.value = s }).catch(() => { /* 无 skill 库则空 */ })
})
function onSkillPicked(name: string) {
  const prefix = `请使用技能 ${name}：`
  userInput.value = userInput.value ? `${prefix}${userInput.value}` : prefix
}

// 2026-05-17 B 重构：抽屉式文件 / 设置 (IDE 抽屉已删)
const filesDrawerOpen = ref(false)
const editDrawerOpen = ref(false)

// ── Coding 模型选择（已抽成 composable）──
const {
  codingModelOptions,
  codingModelLoading,
  updatingCodingModel,
  selectedCodingModelValue,
  persistedCodingModelValue,
  selectedCodingModelOption,
  codingModelHint,
  toCodingModelValue,
  normalizeCodingModelValue,
  applyCodingModelSelection,
  loadCodingModelOptions,
  handleCodingModelChange,
} = useCodingModel()
const codingModelMenuOpen = ref(false)
const codingModelPickerRef = ref<HTMLElement | null>(null)
const codingModelPickerDisabled = computed(() =>
  codingModelLoading.value || updatingCodingModel.value || codingModelOptions.value.length === 0,
)
const selectedCodingModelLabel = computed(() => {
  if (codingModelLoading.value) return '加载中'
  if (codingModelOptions.value.length === 0) return '未配置模型'
  // 触发按钮显真实模型(如 gpt-5.5), 而非陈旧/含网关名的 config_name(如「Dolphin-默认」);
  // 完整配置名 + 厂商在下拉菜单里(option.config_name / provider / model)。
  const opt = selectedCodingModelOption.value
  return opt?.model || opt?.config_name || '选择模型'
})

function toggleCodingModelMenu() {
  if (codingModelPickerDisabled.value) return
  codingModelMenuOpen.value = !codingModelMenuOpen.value
}

async function chooseCodingModel(nextValue: string | null) {
  codingModelMenuOpen.value = false
  if (nextValue === selectedCodingModelValue.value) return
  await handleCodingModelChange(nextValue)
}

function closeCodingModelMenuOnOutside(event: MouseEvent) {
  const root = codingModelPickerRef.value
  if (!root || !codingModelMenuOpen.value) return
  if (event.target instanceof Node && root.contains(event.target)) return
  codingModelMenuOpen.value = false
}

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

// ── 原生文件树 + 代码查看器（Task 7: 替换 IDE 抽屉）──
const wsFileTree = ref<TreeNode[]>([])
const selectedFile = ref<string | null>(null)

async function loadWsFileTree() {
  const id = codingStore.workspace?.id
  if (!id) { wsFileTree.value = []; return }
  try { wsFileTree.value = buildFileTree(await listWorkspaceFiles(id)) }
  catch (e) { console.warn('[coding] 加载工作区文件树失败', e); wsFileTree.value = [] }
}

const wsChanges = computed(() => collectChangedFiles(streamMessages.value as FileChangeMsg[]))
const changedPaths = computed(() => new Set(wsChanges.value.changed.keys()))
const selectedDiff = computed(() =>
  selectedFile.value ? wsChanges.value.changed.get(selectedFile.value) || null : null,
)

// ── git 基线改动（后端 /changes）: 刷新后仍在、覆盖命令行写入，喂树徽标/改动分组/diff 查看 ──
const wsGitChanges = ref<WorkspaceChanges | null>(null)
let gitChangesTimer: ReturnType<typeof setTimeout> | null = null
const acceptingWorkspaceChanges = ref(false)

async function loadWsGitChanges() {
  const id = codingStore.workspace?.id
  if (!id) { wsGitChanges.value = null; return }
  try { wsGitChanges.value = await getWorkspaceChanges(id) }
  catch (e) { console.warn('[coding] 加载工作区改动失败', e); wsGitChanges.value = null }
}

// 流式期间 agent 连续写文件 → 去抖刷新，别每个文件打一次后端
function scheduleGitChangesRefresh() {
  if (gitChangesTimer) clearTimeout(gitChangesTimer)
  gitChangesTimer = setTimeout(() => { void loadWsGitChanges() }, 800)
}

// 选中文件对应的 git 改动（有 → CodeViewer 默认对比模式）
const selectedGitChange = computed(() =>
  wsGitChanges.value?.enabled && selectedFile.value
    ? wsGitChanges.value.files.find(f => f.path === selectedFile.value) || null
    : null,
)

async function acceptWorkspaceChange(path?: string | null) {
  const id = codingStore.workspace?.id
  if (!id || acceptingWorkspaceChanges.value) return
  acceptingWorkspaceChanges.value = true
  try {
    wsGitChanges.value = await acceptWorkspaceChanges(id, path || null)
    await loadWsFileTree()
    ElMessage.success(path ? '已接受此文件变更' : '已接受全部变更')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '接受变更失败')
  } finally {
    acceptingWorkspaceChanges.value = false
  }
}

async function acceptAllWorkspaceChanges() {
  if (!wsGitChanges.value?.files.length) return
  try {
    await ElMessageBox.confirm(
      '接受后会把当前所有改动设为新的对比基线，本轮改动列表将清空。',
      '接受全部变更',
      { confirmButtonText: '接受全部', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  await acceptWorkspaceChange(null)
}

// ── 对话 ↔ 代码联动 ──
function flattenTreeFiles(nodes: TreeNode[], out: string[] = []): string[] {
  for (const n of nodes) {
    if (n.isDir) flattenTreeFiles(n.children || [], out)
    else out.push(n.path)
  }
  return out
}

// 文件卡只有 basename 或路径不在树上时反查：精确命中 > git 改动表 > 树内 basename 唯一/首个命中
function resolveWorkspacePath(p: string): string | null {
  p = normalizeWorkspacePathLabel(p)
  if (!p) return null
  const all = flattenTreeFiles(wsFileTree.value)
  if (all.includes(p)) return p
  const base = p.split('/').pop() || p
  const inChanges = wsGitChanges.value?.files.find(f => f.path === p || f.path.endsWith('/' + base))
  if (inChanges) return inChanges.path
  return all.find(t => t === base || t.endsWith('/' + base)) || null
}

// 真实工作区路径不含空格/代码括号; 过滤混入代码文本的坏 fileName(避免打开不存在的文件 → 红错)。
function looksLikeFilePath(p: string): boolean {
  return !!p && p.length < 200 && !/\s/.test(p) && !/[(){}<>]/.test(p)
}

// 点击对话里的写/改文件卡 / 产物清单 → 打开代码抽屉并定位该文件（有 git 改动 CodeViewer 自动进对比模式）
function openFileFromChat(sm: { filePath?: string; fileName?: string }) {
  const rawPath = normalizeWorkspacePathLabel(sm.filePath || sm.fileName)
  // 解析到真实文件才打开; 解析不到只接受"看着像路径"的(刚写、树未刷新), 坏路径(含代码)忽略。
  const target = resolveWorkspacePath(rawPath) || (looksLikeFilePath(rawPath) ? rawPath : null)
  if (target) {
    selectedFile.value = target
    wsPaneTab.value = 'files'
    codePaneOpen.value = true
  }
}

// 查看器选中代码「引用到对话」→ 追加 `路径:行号` + 代码块进输入框
function onViewerQuote(q: { path: string; startLine: number | null; endLine: number | null; text: string }) {
  const loc = q.startLine
    ? `:${q.startLine}${q.endLine && q.endLine !== q.startLine ? '-' + q.endLine : ''}`
    : ''
  const block = '引用 `' + q.path + loc + '`:\n```\n' + q.text + '\n```\n'
  userInput.value = (userInput.value.trim() ? userInput.value.replace(/\s+$/, '') + '\n\n' : '') + block
  void nextTick(() => {
    (document.querySelector('.chat-input-bar textarea') as HTMLTextAreaElement | null)?.focus()
  })
}

// codeFirst 空态建议提问: 按工作区元信息生成(冷启动引导)
const emptySuggestions = computed<string[]>(() => {
  if (!codeFirst.value) return []
  const kindLabel = ({
    'form-page': '页面', 'menu-page': '页面', 'mobile-page': '页面',
    'form-component-dual': '组件', 'form-list': '列表', 'backend-api': '接口',
  } as Record<string, string>)[codingStore.workspace?.project_type || ''] || '项目'
  const out = ['讲讲这个项目的结构和入口文件']
  if ((wsGitChanges.value?.files || []).some(f => !f.artifact)) out.push('评审一下本轮改动，有什么问题？')
  out.push(`这个${kindLabel}的主要逻辑在哪？`)
  return out
})

function sendSuggestion(text: string) {
  userInput.value = text
  void sendOrQueue()
}

// 内容搜索跳行: 选中文件 + 目标行(查看器全文视图滚动+闪烁); 普通选择时清掉
const viewerFocusLine = ref<number | null>(null)
function onTreeSelect(path: string) {
  viewerFocusLine.value = null
  selectedFile.value = path
}
function onTreeSelectLine(payload: { path: string; line: number }) {
  selectedFile.value = payload.path
  viewerFocusLine.value = payload.line
}

// agent 改完最后一个文件 → 自动打开它（纯前端，不发请求）
watch(() => wsChanges.value.lastChangedFile, (p) => {
  // 打开/改动时自动跳到该文件 —— 但坏路径(混入代码的 fileName)会害打开态落到文件红错, 守卫掉。
  if (!p) return
  const t = resolveWorkspacePath(p) || (looksLikeFilePath(p) ? p : null)
  if (t) selectedFile.value = t
})
// 仅当改动文件“集合增长”（写了新文件）时才重载树，避免多文件 codegen 期间每写一个文件就重复拉一次
watch(() => changedPaths.value.size, () => { void loadWsFileTree(); scheduleGitChangesRefresh() })
// 一轮跑完 → 改动清单收口刷新（含 run_command 等树/流事件看不到的写入）
watch(isStreaming, (s) => { if (!s) { void loadWsGitChanges(); void loadWsFileTree() } })
// 切换工作区 → 清空选中并重载树 + 改动
watch(() => codingStore.workspace?.id, () => {
  selectedFile.value = null
  wsGitChanges.value = null
  void loadWsFileTree()
  void loadWsGitChanges()
}, { immediate: true })

// 工作区打开 → 代码为主三栏布局（文件树 | 大代码区 | 右聊天）；未进工作区时维持原引导/新建流程
const codeFirst = computed(() => !!codingStore.workspace?.id && !embeddedAppId.value)
const wsPaneTab = ref<'files' | 'run'>('files')

// 对话优先(参考 Claude Code/Codex 桌面): 对话是常驻主列, 永远能输入;
// 点产物/文件/「代码」按钮 → 代码作为右侧并排侧栏推出(文件树+查看器+预览), 不遮挡对话;
// 关掉(×)回全宽对话。不是覆盖式抽屉(会盖住对话没法聊), 也不是旧的「文件树为主+对话窄栏」。
const codePaneOpen = ref(false)
// 右侧代码侧栏可拖宽(handle 在侧栏左边界); 对话(main-content)吃 flex:1 剩余空间作主列。
const { panelWidth: codePaneWidth, onResizeStart: onCodePaneResizeStart } = usePanelResize({
  storageKey: 'coding:code-pane-width',
  defaultWidth: 640,
  minWidth: 360,
  maxWidth: 1280,
})
// 对话优先(参考 Claude Code/Codex): 全新会话渲染欢迎页(可直接输入 + 打开本地文件夹),
// 底部输入框在非嵌入模式永远可用(修「新建空白没法输入」)。
const codingViewState = computed(() => ({
  embedded: !!embeddedAppId.value,
  codeFirst: codeFirst.value,
  streaming: isStreaming.value,
  messageCount: streamMessages.value.length,
}))
const isCodeWelcome = computed(() => isCodingWelcome(codingViewState.value))
const showCodingComposer = computed(() => shouldShowCodingComposer(codingViewState.value))

// 新建会话「打开本地文件夹」(桌面端): 复用 我的开发 同款 pickDirectory + open-local,
// 选完直接进 /coding?workspace_id 打开该工作区(对齐 Claude Code/Codex 的 open folder)。
async function openLocalFolderInCoding() {
  const picked = await pickDirectory('选择要打开的项目文件夹')
  if (!picked) return
  try {
    await ElMessageBox.confirm(
      'AI 将能读取并修改该文件夹内的文件。请确认这是你信任的项目目录。',
      '打开本地文件夹',
      { confirmButtonText: '打开', cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }
  try {
    const ws = await codingApi.openLocalFolder(picked)
    router.push({ path: '/coding', query: { workspace_id: ws.ws_id } })
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '打开文件夹失败')
  }
}

// 头部 ≡ 只列当前工作区的会话(含还没绑定的当前新会话)——它是"本工作区的聊天历史",
// 不是跨工作区切换器(那是侧栏/资产库的事)。
const headerConversations = computed(() => {
  const wsId = codingStore.workspace?.id
  if (!wsId) return codingConversations.value
  return codingConversations.value.filter(
    c => c.workspace_id === wsId || c.id === codingStore.conversationId,
  )
})

// 同步地址栏但不动路由 —— App.vue 的 <component :key="$route.fullPath"> 会让任何
// query 变化整页重挂载, onMounted 再按 workspace_id 灌主会话回放, 把刚切的会话覆盖掉。
function syncCodingUrl(conversationId: number) {
  const q = new URLSearchParams()
  q.set('conversation_id', String(conversationId))
  if (codingStore.workspace?.id) q.set('workspace_id', codingStore.workspace.id)
  window.history.replaceState(window.history.state, '', `${window.location.pathname}?${q.toString()}`)
}

// 切会话/工作区/新建前, 掐断仍在跑的 SSE —— 否则旧流的回调会继续往「现在已切到新会话」的
// 共享 streamMessages/conversationId 里写(串台/污染)。旧实现靠 /coding remount 销毁 pipeline
// 闭包来顺带 abort; 现在 /coding 稳定 key 原地切, 必须显式 stopStream()。
function abortInflightStream() {
  if (isStreaming.value) stopStream()
}

// 头部切换 = 只换聊天上下文, 工作区(文件树/查看器)保持不动
async function switchConversationFromHeader(id: number) {
  if (id === codingStore.conversationId) return
  abortInflightStream()
  handoffSourceApp.value = null
  const _boundAppId = codingConversations.value.find(c => c.id === id)?.coding_app_id ?? null
  deployAppId.value = _boundAppId
  deployMode.value = 'bound'
  try {
    // 富回放按会话存 DB(conversation_replays), 任何会话切换都拿得到结构化工具卡;
    // 没有回放行(老会话/纯 READ 首轮)时 stream 为空, loadConversationHistory 回退纯消息重建。
    const replay = await codingApi.getConversationReplay(id)
    codingStore.conversationId = id
    applyCodingModelSelection(replay.selected_llm_config_id)
    loadConversationHistory(replay.messages as any, replay.stream_messages || [])
    syncCodingUrl(id)
  } catch (e: any) {
    ElMessage.error(`切换会话失败: ${e?.message || e}`)
  }
}

// 按当前 route.query 原地解析要打开的会话/工作区(不 remount, 不闪)。
// onMounted 首次 + route.query 变化(rail 换会话)都走它; 用 syncCodingUrl(history)同步地址栏,
// 不经 vue-router 二次导航(避免再触发 watcher)。
async function resolveCodingRouteSession() {
  const wsId = (route.query.workspace_id || route.query.ws) as string
  if (wsId) {
    if (codingStore.workspace?.id !== wsId) { abortInflightStream(); await openWorkspaceById(wsId) }
    // URL 还带 conversation_id 且不是工作区主会话(头部切过会话) → 保工作区, 切回该会话
    const qConvId = Number(route.query.conversation_id)
    if (Number.isFinite(qConvId) && qConvId > 0 && qConvId !== codingStore.conversationId) {
      await switchConversationFromHeader(qConvId)
    }
    return
  }
  const conversationId = Number(route.query.conversation_id)
  if (!(Number.isFinite(conversationId) && conversationId > 0)) return
  if (conversationId === codingStore.conversationId) return  // 已是当前会话, 跳过
  // 该会话若有 workspace(codegen 会话) → 开工作区恢复结构化工具卡; 无 → 纯文本回放。
  let wsForConv: string | null = null
  try {
    wsForConv = (await codingApi.getConversationWorkspace(conversationId)).workspace_id
  } catch {
    wsForConv = null
  }
  if (wsForConv) {
    await openWorkspaceById(wsForConv)
    syncCodingUrl(conversationId)
  } else {
    await loadCodingConversationOnly(conversationId)
  }
}

function formatConvTime(iso?: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const p = (n: number) => String(n).padStart(2, '0')
  const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  return sameDay ? `${p(d.getHours())}:${p(d.getMinutes())}` : `${d.getMonth() + 1}/${d.getDate()}`
}

// 新建会话但保留当前工作区——首条消息发出后由后端把会话回填绑定到工作区
async function createWorkspaceConversation() {
  const created = normalizeCreatedCodingConversation(
    await codingApi.createConversation(selectedCodingModelOption.value?.id ?? null),
  )
  codingConversations.value = [created, ...codingConversations.value.filter(c => c.id !== created.id)]
  codingStore.conversationId = created.id
  streamMessages.value = []
  selectedFile.value = null
  // history.replaceState 而非 router.replace: 避免 fullPath key 重挂载把新会话覆盖回主会话
  syncCodingUrl(created.id)
}
// 文件树列也可拖宽(handle 在树右边界, 长 Java 类名放不下时拖开)
const { panelWidth: treePaneWidth, onResizeStart: onTreeResizeStart } = usePanelResize({
  storageKey: 'coding:tree-pane-width',
  defaultWidth: 236,
  minWidth: 180,
  maxWidth: 480,
  handleSide: 'right',
})

// ── 工作区列表和元信息展示（已抽成 composable）──
const {
  allWorkspaces,
  isDownloading,
  embeddedAppId,
  existingWorkspaces,
  workspaceDisplayName,
} = useCodingWorkspace()

/** 正在打开的会话 id */
const openingWsId = ref<string | null>(null)
/** 正在删除的工作区 id */
const deletingWsId = ref<string | null>(null)
const codingConversations = ref<CodingConversation[]>([])

// ── AgentConversation 公共契约映射（保留 streamMessages 原 reactive 对象，slot 直接引用 meta.streamMsg） ──
const agentMessages = computed<AgentMessage[]>(() => {
  const list = streamMessages.value
  const out: AgentMessage[] = []
  for (let i = 0; i < list.length; i++) {
    const msg = list[i]!
    if (msg.type === 'status' && msg.hidden) continue
    if (msg.type === 'user') {
      out.push({
        id: 'sm' + i,
        kind: 'user',
        content: msg.content,
        attachments: (msg.attachments || []).map(a => ({
          kind: a.kind,
          filename: a.filename,
          url: a.url,
        })),
      })
    } else if (msg.type === 'message') {
      // 开发 SPEC 不在对话里大段铺(和右侧「开发文档」重复)——收成一行里程碑提示,完整 SPEC 去产物看。
      if (/开发\s*SPEC\s*确认|📋\s*开发\s*SPEC/.test(msg.content || '')) {
        out.push({ id: 'sm' + i, kind: 'status', content: '📋 已生成开发 SPEC —— 在右侧「开发文档」查看完整内容' })
      } else {
        out.push({ id: 'sm' + i, kind: 'assistant', content: msg.content })
      }
    } else if (msg.type === 'clarify') {
      // 澄清 → 共享 ask 卡片(可点选项,对齐 Builder);点选项走 @answer-ask
      out.push({ id: 'sm' + i, kind: 'ask', ask: { question: msg.question || msg.content, options: msg.options || [], answered: msg.answered } })
    } else if (msg.type === 'error') {
      out.push({ id: 'sm' + i, kind: 'error', content: msg.content })
    } else if (msg.type === 'reasoning') {
      // 思维链 → custom kind, 走 #custom slot 的折叠卡
      out.push({ id: 'sm' + i, kind: 'custom', meta: { streamMsg: msg, isLast: i === list.length - 1 } })
    } else if (msg.type === 'thinking') {
      // 全面 native:thinking → AgentConversation 原生 thinking(斜体),对齐 Builder / AIChat
      out.push({ id: 'sm' + i, kind: 'thinking', thinking: { text: msg.content } })
    } else if (msg.type === 'tool') {
      // 全面 native:tool → 原生 ToolCard 结果芯片(✓ 已完成 · …),对齐 Builder
      out.push({ id: 'sm' + i, kind: 'tool', tool: toolPayloadFromStreamMsg(msg, 'sm' + i, i === list.length - 1) })
    } else if (msg.type === 'status') {
      // 全面 native:status → AgentConversation 原生 status(居中胶囊);完成步骤补 ✓ 保留里程碑信号
      const text = msg.stepDone && !/^[✓✅]/.test(msg.content || '') ? `✓ ${msg.content}` : msg.content
      out.push({ id: 'sm' + i, kind: 'status', content: text })
    } else {
      // file_write / file_edit / command — native 无对应 kind,仍走 #custom slot
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

// 运行结果卡（type=run_result）的状态文案 + 「查看预览」聚焦到预览位
function rcStatusText(r: any): string {
  if (!r) return ''
  if (r.status === 'running') return '运行中…'
  if (r.status === 'ok') return r.capture_available ? '通过，无报错' : '已启动'
  return `${(r.errors || []).length} 个报错`
}
function focusPreview(r: any) {
  if (r?.dev_url) {
    codingStore.activePreview = { dev_url: r.dev_url, status: r.status, errors: r.errors, capture_available: r.capture_available, round: r.round }
  }
  wsPaneTab.value = 'run'
  codePaneOpen.value = true
}

// 对话里点链接: localhost 预览地址 → 聚焦预览位(不导航主界面, 根除「回不去」); 外链 → 系统浏览器。
// 裸 marked 链接是 <a href> 无处理, 在 Tauri webview 里点了会把主界面导航走 → 死胡同。
function onChatClick(e: MouseEvent) {
  const a = (e.target as HTMLElement | null)?.closest?.('a') as HTMLAnchorElement | null
  if (!a) return
  const href = a.getAttribute('href') || ''
  if (!/^https?:\/\//i.test(href)) return  // 站内相对链接(router)不拦
  e.preventDefault()
  e.stopPropagation()
  if (/^https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?/i.test(href)) {
    // marked 自动链接常把后面的中文标点也吞进 href(如 8083/;本轮…), 本地预览只取干净 origin。
    let dev = href
    try { dev = new URL(href).origin + '/' } catch { /* 解析失败用原始 href 兜底 */ }
    codingStore.activePreview = { dev_url: dev, status: 'ok', errors: [], capture_available: false, round: null, source: 'panel' }
    wsPaneTab.value = 'run'
    codePaneOpen.value = true  // 对话里点本地预览链接 → 打开代码侧栏的「预览」位(否则切了 tab 但侧栏关着看不到)
  } else {
    void openExternal(href)
  }
}

// 预览结果一到达就自动切到「预览」位并弹出代码抽屉, 不用再点链接:
// - previewEpoch: agent 每跑一次预览(run_result)+1(主路径; 自愈轮不递增, 不打扰)→ 顺手开抽屉给用户看运行结果。
// - activePreview.dev_url 变化: 覆盖按钮/链接等其它写入路径, 只切 tab(开抽屉交给 previewEpoch / 点击行为, 避免重复弹)。
watch(() => codingStore.previewEpoch, () => { wsPaneTab.value = 'run'; codePaneOpen.value = true })
watch(() => codingStore.activePreview?.dev_url, (url, old) => {
  if (url && url !== old) wsPaneTab.value = 'run'
})

/** Coding 的 tool StreamMessage(展示字符串模型,content='📖 读取 X' / '🔧 <display>',
 *  live 时可选 toolName=真实工具名)→ AgentConversation 原生 ToolCard payload。
 *  replay 老数据无 toolName → 去掉前导 emoji 后整段当 name 兜底。 */
function toolPayloadFromStreamMsg(msg: any, id: string, isLast: boolean): AgentToolPayload {
  const raw = String(msg.content || '').trim()
  const display = raw.replace(/^[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}✅❌️\s]+/u, '').trim()
  const realName: string | undefined = msg.toolName
  return {
    id,
    name: realName || display || '工具',
    argsBrief: realName ? display : undefined,
    result: msg.result || undefined,
    status: msg.result ? 'success' : (isLast && isStreaming.value ? 'running' : 'success'),
  }
}

// ── v2 redesign: 产物清单 / 接入说明 面板 ──
// 把 streamMessages 里的 file_write / file_edit 整成 new/modified 两组，
// 提供给右侧 CodingArtifactPanel 渲染。最后一条 file_write 在 isStreaming
// 时视为「正在写入」展示 spinner。
const codingArtifactTab = ref<'spec' | 'files' | 'integrate'>('spec')
const specViewMode = ref<'render' | 'raw'>('render')
// 开发文档(对标 Builder 设计文档):从对话流取最新「开发 SPEC」md。
// live(content 事件落 streamMsg)+ 历史回放(带 BRAINSTORM marker)都覆盖,marker 去掉。
const specMarkdown = computed<string>(() => {
  const list = streamMessages.value as any[]
  for (let i = list.length - 1; i >= 0; i--) {
    const c = String(list[i]?.content || '')
    if (/开发\s*SPEC\s*确认|📋\s*开发\s*SPEC/.test(c)) {
      return c.replace(/^<!--\s*BRAINSTORM_PROPOSAL\s*-->\s*/, '').trim()
    }
  }
  return ''
})
// SPEC 确认门:出了开发 SPEC、还没产物、不在流式 → 等用户确认(不一股脑直接开发)
const awaitingSpecConfirm = computed(() =>
  !isStreaming.value && streamMessages.value.length > 0 && !!specMarkdown.value && !codingArtifactsHasAny.value
)
function confirmSpec() {
  if (isStreaming.value) return
  userInput.value = '确认,按这份开发 SPEC 开始生成代码'
  nextTick(() => { sendMessage() })
}

// 点澄清选项卡片(对齐 Builder):置灰已选 + 把选项作为回答发出
function onAnswerAsk(option: string) {
  if (isStreaming.value || isCreating.value || !option) return
  for (let i = streamMessages.value.length - 1; i >= 0; i--) {
    const m = streamMessages.value[i] as any
    if (m && m.type === 'clarify' && !m.answered) { m.answered = option; break }
  }
  userInput.value = option
  nextTick(() => { sendMessage() })
}

// 流式计时:对齐 Builder 的「AI 思考中 Ns」。开始流式起秒表,停了清零。
const streamSeconds = ref(0)
let _streamTimer: ReturnType<typeof setInterval> | null = null
watch(isStreaming, (on) => {
  if (_streamTimer) { clearInterval(_streamTimer); _streamTimer = null }
  if (on) {
    streamSeconds.value = 0
    _streamTimer = setInterval(() => { streamSeconds.value += 1 }, 1000)
  } else {
    streamSeconds.value = 0
  }
})
onUnmounted(() => { if (_streamTimer) { clearInterval(_streamTimer); _streamTimer = null } })

// ── 排队消息(对齐 AI Builder / 需求分析助手):流式中按 Enter → 进队列,当前回复结束自动发出 ──
// codingBusy = 流式中 or 建工作区中(两者皆 false 才算真空闲,可发下一条);
// sendOrQueue:忙时入队、闲时直接发;闲下来 watch 自动把队首发出去。
const pendingQueue = ref<string[]>([])
const codingBusy = computed(() => isStreaming.value || isCreating.value)
function sendOrQueue() {
  if (codingBusy.value) {
    const txt = userInput.value.trim()
    if (!txt) return
    pendingQueue.value.push(txt)
    userInput.value = ''
    return
  }
  sendMessage()
}
watch(codingBusy, (now, prev) => {
  // 上一轮彻底结束(流式 + 建区都 false)→ 把队首自动发出去,透气一帧让用户看见
  if (prev && !now && pendingQueue.value.length > 0) {
    const next = pendingQueue.value.shift()!
    userInput.value = next
    setTimeout(() => { sendMessage() }, 220)
  }
})

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
    const path = normalizeWorkspacePathLabel(m.filePath || m.fileName)
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

// 产物面板 3 态显示策略（image #24 设计反馈）：
//   null   → 自动：有产物 / streaming 中默认展开，无产物折叠
//   true   → 用户显式 open（强制展开）
//   false  → 用户显式 close（强制折叠，即使有产物也尊重）
// 解决之前 "codingArtifactsHasAny.value return true" 把用户 toggle 意志盖掉的问题。
const codingArtifactPanelUserToggle = ref<boolean | null>(null)

// 仅在「确有产物」时自动弹产物面板。去掉 isStreaming：之前一开始 streaming（含 READ 问答、
// codegen 刚起步还没写文件）就弹空面板，体验差（用户反馈「还没产物不着急弹」）。
// 产物面板改为「按需唤出」(对齐 Builder 的设计文档面板):不再随产物自动弹出挤窄对话区。
// 完成后由会话流里的「完成态卡片」提示 + 给「查看产物 / 装回应用」入口,需要时再点开面板。
const codingArtifactPanelAutoShow = computed(() => false)

const showCodingArtifactPanel = computed(() => {
  if (embeddedAppId.value) return false
  if (codingArtifactPanelUserToggle.value !== null) {
    return codingArtifactPanelUserToggle.value
  }
  return codingArtifactPanelAutoShow.value
})

const toggleCodingArtifactPanel = () => {
  // 反转当前显示状态，把意志写入 userToggle（之后跟随用户，不再随 auto 变）
  codingArtifactPanelUserToggle.value = !showCodingArtifactPanel.value
}

// 明确「打开」产物面板到指定 tab(不是切换)——给确认条/完成卡的「查看开发文档/产物」用
function openCodingArtifactTab(tab: 'spec' | 'files' | 'integrate') {
  codingArtifactTab.value = tab
  codingArtifactPanelUserToggle.value = true
}

function codingTimeGroup(iso: string | null | undefined): string {
  if (!iso) return '更早'
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return '更早'
  const now = new Date()
  const today0 = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const dayMs = 24 * 60 * 60 * 1000
  if (t >= today0) return '今天'
  if (t >= today0 - dayMs) return '昨天'
  if (t >= today0 - 7 * dayMs) return '本周'
  if (t >= today0 - 30 * dayMs) return '本月'
  return '更早'
}

function compactTitle(title: string | null | undefined, fallback: string) {
  const raw = (title || '').trim() || fallback
  return raw.length > 30 ? `${raw.slice(0, 30)}...` : raw
}

async function refreshCodingConversations() {
  try {
    const list = await codingApi.getConversations()
    codingConversations.value = Array.isArray(list) ? list : []
  } catch {
    codingConversations.value = []
  }
}

const sidebarCodingItems = computed<SidebarSessionItem[]>(() => {
  const conversations = [...codingConversations.value].sort((a, b) => {
    const ta = new Date(a.updated_at || a.created_at || 0).getTime()
    const tb = new Date(b.updated_at || b.created_at || 0).getTime()
    return tb - ta
  })
  return conversations.map(conv => ({
    id: `conv:${conv.id}`,
    title: compactTitle(conv.title, `开发会话 #${conv.id}`),
    meta: undefined,  // 不暴露 workspace_id 内部 ID(对用户无意义的噪声);时间已在分组头(今天/昨天)
    group: codingTimeGroup(conv.updated_at || conv.created_at),
    badgeIcon: ChatDotRound,
    badgeTone: 'chat',
  }))
})

const sidebarCodingActiveId = computed<string | null>(() => {
  if (codingStore.conversationId) return `conv:${codingStore.conversationId}`
  return null
})

const activeCodingConversation = computed(() =>
  codingConversations.value.find(conv => conv.id === codingStore.conversationId) || null,
)

const activeCodingSessionTitle = computed(() => {
  if (activeCodingConversation.value) {
    return compactTitle(activeCodingConversation.value.title, `开发会话 #${activeCodingConversation.value.id}`)
  }
  if (codingStore.workspace) {
    return workspaceDisplayName(codingStore.workspace) || codingStore.workspace.project_name || '开发会话'
  }
  return '新建开发会话'
})

// Token 用量显示（footer）
const ctxRatio = computed(() => {
  const u = codingStore.tokenUsage
  return u ? contextRatio(u.contextTokens, u.contextBudget) : 0
})
const ctxPct = computed(() => Math.round(ctxRatio.value * 100))
const ctxLevel = computed(() => contextLevel(ctxRatio.value))
const showContextWarning = computed(
  () => !!codingStore.tokenUsage && ctxLevel.value !== 'ok' && !codingStore.contextWarnDismissed,
)
function dismissContextWarn() {
  codingStore.contextWarnDismissed = true
}
const cumTokenText = computed(() => {
  const u = codingStore.tokenUsage
  return u ? formatTokenCount(u.input + u.output) : ''
})

async function loadCodingConversationOnly(conversationId: number) {
  abortInflightStream()  // 切到别的会话前掐断旧 SSE(防串台)
  handoffSourceApp.value = null  // F3: 切到已有会话时清掉 handoff 回跳链，避免串到别的会话
  // 恢复「在应用上定制」绑定:会话持久化了 coding_app_id 就接着绑(刷新/侧栏点开仍记得是哪个应用),
  // 没有才清空,避免把上个会话选的应用串过来。后端也会从会话回读做兜底,这里主要保证 UI 一致。
  const _boundAppId = codingConversations.value.find(c => c.id === conversationId)?.coding_app_id ?? null
  deployAppId.value = _boundAppId; deployMode.value = 'bound'
  // 富回放按会话存 DB — 无工作区的会话(READ 问答等)也能恢复结构化工具卡
  const replay = await codingApi.getConversationReplay(conversationId)
  codingStore.reset()
  codingStore.conversationId = conversationId
  localStorage.removeItem('coding_last_workspace_id')
  loadConversationHistory(replay.messages as any, replay.stream_messages || [])
}

function normalizeCreatedCodingConversation(conv: CodingConversation): CodingConversation {
  const now = new Date().toISOString()
  return {
    ...conv,
    title: conv.title || '新开发会话',
    workspace_id: conv.workspace_id ?? null,
    selected_llm_config_id: conv.selected_llm_config_id ?? selectedCodingModelOption.value?.id ?? null,
    created_at: conv.created_at || now,
    updated_at: conv.updated_at || now,
  }
}

async function createCodingConversation() {
  const created = normalizeCreatedCodingConversation(
    await codingApi.createConversation(selectedCodingModelOption.value?.id ?? null),
  )
  codingConversations.value = [
    created,
    ...codingConversations.value.filter(conv => conv.id !== created.id),
  ]
  codingStore.reset()
  codingStore.conversationId = created.id
  persistedCodingModelValue.value = normalizeCodingModelValue(selectedCodingModelValue.value)
  streamMessages.value = []
  localStorage.removeItem('coding_last_workspace_id')
  router.replace({ path: '/coding', query: { conversation_id: String(created.id) } }).catch(() => {})
}

async function onSidebarCodingSelect(id: string | number) {
  const itemId = String(id)
  if (sidebarCodingActiveId.value === itemId || openingWsId.value) return
  if (!itemId.startsWith('conv:')) return
  const conversationId = Number(itemId.slice(5))
  if (!Number.isFinite(conversationId) || conversationId <= 0) return
  openingWsId.value = itemId
  try {
    const conversation = codingConversations.value.find(conv => conv.id === conversationId)
    let workspaceId = conversation?.workspace_id || null
    if (!workspaceId) {
      try {
        const relation = await codingApi.getConversationWorkspace(conversationId)
        workspaceId = relation.workspace_id
      } catch {
        workspaceId = null
      }
    }
    if (workspaceId) {
      await openWorkspaceById(workspaceId)
      router.replace({ path: '/coding', query: { conversation_id: String(conversationId), workspace_id: workspaceId } }).catch(() => {})
    } else {
      await loadCodingConversationOnly(conversationId)
      router.replace({ path: '/coding', query: { conversation_id: String(conversationId) } }).catch(() => {})
    }
  } finally {
    openingWsId.value = null
  }
}

function onSidebarCodingCreate() {
  createCodingConversation().catch((e: any) => {
    ElMessage.error(e?.response?.data?.detail || e?.message || '新建会话失败')
  })
}

async function onSidebarCodingDelete(s: SidebarSessionItem) {
  const itemId = String(s.id)
  if (!itemId.startsWith('conv:')) return
  const conversationId = Number(itemId.slice(5))
  if (!Number.isFinite(conversationId) || conversationId <= 0) return
  const workspaceId = codingConversations.value.find(conv => conv.id === conversationId)?.workspace_id || ''

  // 1) 确认（用户取消 → 直接返回，不当成错误）
  try {
    await ElMessageBox.confirm(`删除会话「${s.title}」吗？关联工作区会一并清理。`, '删除会话', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
      confirmButtonClass: 'el-button--danger',
    })
  } catch {
    return // 取消
  }

  // 2) 执行（删会话，后端 best-effort 清工作区）
  try {
    deletingWsId.value = workspaceId
    await codingApi.deleteConversation(conversationId)
    if (workspaceId) {
      allWorkspaces.value = allWorkspaces.value.filter((w: any) => w.id !== workspaceId)
      if (codingStore.workspace?.id === workspaceId) {
        startNewWorkspace()
      }
    }
    await refreshCodingConversations()
    ElMessage.success('已删除')
  } catch (e: any) {
    ElMessage.error('删除失败：' + (e?.message || e?.detail || '请重试'))
  } finally {
    deletingWsId.value = null
  }
}

const embeddedPanelCollapsed = ref(false)

// ── Phase D Task 6：Sync workspace → repo ──
const syncingToRepo = ref(false)
const currentAppGitRepoUrl = ref<string | null>(null)
const currentAppProjectId = ref<number | null>(null)

async function loadCurrentAppGitRepo() {
  const appId = currentGitAppId.value
  if (!appId) {
    currentAppGitRepoUrl.value = null
    currentAppProjectId.value = null
    return
  }
  try {
    const app = await applicationApi.get(appId)
    currentAppGitRepoUrl.value = app?.git_repo_url || null
    currentAppProjectId.value = app?.project_id ?? null
  } catch {
    currentAppGitRepoUrl.value = null
    currentAppProjectId.value = null
  }
}

function openGitSetupForCurrentApp() {
  if (currentAppProjectId.value) {
    router.push({ path: `/project/${currentAppProjectId.value}/git` }).catch(() => {})
    return
  }
  ElMessage.warning('当前应用未关联项目，暂不能配置 Git/GitHub')
}

async function onSyncToRepo() {
  const ws = codingStore.workspace
  const appId = currentGitAppId.value
  if (!ws || !appId) return
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

// ============ Attachment State ============
const attachedFile = ref<File | null>(null)
const attachedPreviewUrl = ref<string | null>(null)
const isUploading = ref(false)
const codingComposerAttachments = computed<UnifiedChatAttachment[]>(() => {
  if (!attachedFile.value) return []
  return [{
    id: 'attached',
    name: attachedFile.value.name,
    previewUrl: attachedPreviewUrl.value,
    kind: attachedPreviewUrl.value ? 'image' : 'file',
  }]
})

// ============ Env Picker ============
const showEnvPicker = ref(false)
const platformEnvs = ref<PlatformEnv[]>([])


function canDeleteWorkspace(ws: WorkspaceInfo) {
  return ws.permissions?.delete !== false
}

// ============ Scene Categories & Suggestions ============
const sceneSuggestions: Record<string, string[]> = {
  auto: [
    '做一个质量整改看板页面，按责任部门、状态和超期风险筛选',
    '开发一个供应商月度评分接口，返回排名、扣分项和趋势',
    '给设备台账加一个批量导入脚本，支持校验重复编号',
    '做一个表单里的拍照上传扩展，支持压缩、预览和必填校验',
  ],
}

const activeSceneCategory = ref('auto')

const pendingSceneCategory = ref<string | null>(null)

const sceneCategoryToProjectType: Record<string, string> = {
  auto: '',
}

// F3 (2026-06-02): 记住 Builder→Coding handoff 的来源应用，给「← 回 Builder」回跳用。
const handoffSourceApp = ref<{ id: string; name: string } | null>(null)

// ── 分场景部署:装回应用 / 发布到资产库(借鉴 Claude Design 原型 CodingEntry + InstallModal）──
const sceneApps = ref<{ id: number; name: string }[]>([])
const deployMode = ref<'bound' | 'lib'>('bound')
const deployAppId = ref<number | null>(null)
const installModalVisible = ref(false)
const installLoading = ref(false)

const sceneDefaultAppId = computed<number | null>(() => {
  const h = handoffSourceApp.value?.id
  if (h != null && Number.isFinite(Number(h))) return Number(h)
  const e = embeddedAppId.value
  return e != null && Number.isFinite(Number(e)) ? Number(e) : null
})
const effectiveDeployAppId = computed<number | null>(() => deployAppId.value ?? sceneDefaultAppId.value)
const isBoundDeploy = computed(() => deployMode.value === 'bound' && effectiveDeployAppId.value != null)
const currentGitAppId = computed<number | null>(() => {
  const raw = effectiveDeployAppId.value
  if (raw == null) return null
  const id = Number(raw)
  return Number.isFinite(id) ? id : null
})
const currentGitActionTitle = computed(() => {
  if (syncingToRepo.value) return '正在同步到 Git 仓库'
  return currentAppGitRepoUrl.value ? '同步当前工作区到 Git 仓库' : '配置 Git/GitHub 仓库'
})
watch(() => currentGitAppId.value, () => {
  void loadCurrentAppGitRepo()
}, { immediate: true })
const installRows = computed(() => isBoundDeploy.value ? [
  { icon: 'doc', title: '应用页面 / 组件', desc: '页面类挂到应用菜单下;组件类在表单设计器中引用' },
  { icon: 'flow', title: '路由 / 菜单', desc: '页面类自动注册自开发菜单' },
  { icon: 'lock', title: '权限', desc: '沿用应用现有角色的数据范围' },
  { icon: 'store', title: '资产登记', desc: '同时登记到我的开发,可跨应用复用' },
] : [
  { icon: 'store', title: '我的开发', desc: '上传到组件库,可在任意应用的表单设计器中引用' },
])

function onSceneSubmit(p: { mode: 'bound' | 'lib'; appId: number | null; text: string }) {
  deployMode.value = p.mode
  deployAppId.value = p.appId
  // bound:记下选中的目标应用 —— codegen 经 boundAppId 拿 app_id 复用其模型/接口,
  // 同时让会话头显示该应用(修「选了应用却没带过去」)。lib:清掉,不绑应用。
  if (p.mode === 'bound' && p.appId != null) {
    const name = sceneApps.value.find(a => a.id === p.appId)?.name || '应用'
    handoffSourceApp.value = { id: String(p.appId), name }
  } else {
    handoffSourceApp.value = null
  }
  userInput.value = p.text
  nextTick(() => { sendMessage() })
}
function openInstallModal() { installModalVisible.value = true }
async function confirmDeploy() {
  const wsId = codingStore.workspace?.id
  if (!wsId) { ElMessage.warning('还没有工作区,无法部署'); return }
  installLoading.value = true
  try {
    const r = await codingApi.deployToApp(
      String(wsId),
      isBoundDeploy.value ? (effectiveDeployAppId.value ?? undefined) : undefined,
    )
    installModalVisible.value = false
    if (r.status === 'installed') {
      ElMessage.success(`已装回应用${r.app?.name ? '「' + r.app.name + '」' : ''}${r.version ? ' · v' + r.version : ''}`)
    } else {
      ElMessage.success(r.hint || '已发布到我的开发')
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '装回失败')
  } finally {
    installLoading.value = false
  }
}

// apps 列表(给分场景入口的「目标应用」选择器)—— 单独 onMounted,additive 不动既有 onMounted
onMounted(async () => {
  try {
    const apps = await applicationApi.list()
    sceneApps.value = (apps || []).map((a: any) => ({
      id: a.id, name: a.app_name || a.name || a.app_code || ('应用 ' + a.id),
    }))
  } catch { /* 列表加载失败不阻断入口 */ }
})
onMounted(() => {
  document.addEventListener('click', closeCodingModelMenuOnOutside)
})
function backToBuilder() {
  const app = handoffSourceApp.value
  if (!app?.id) return
  router.push({ path: '/chat', query: { app_id: app.id, tab: 'spec' } }).catch(() => {})
}
// ============ Lifecycle ============

onMounted(async () => {
  // 申请浏览器通知权限（用于开发 SPEC 生成后提醒用户）
  if ('Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission()
  }

  try {
    const [workspaces] = await Promise.all([
      codingApi.listWorkspaces(),
      loadCodingModelOptions(),
      refreshCodingConversations(),
    ])
    allWorkspaces.value = workspaces
  } catch (e) {
    console.error('\u521D\u59CB\u5316 AI Coding \u9875\u9762\u5931\u8D25:', e)
  }

  const hasRouteSession = !!(route.query.workspace_id || route.query.ws) ||
    (Number.isFinite(Number(route.query.conversation_id)) && Number(route.query.conversation_id) > 0)
  if (hasRouteSession) {
    await resolveCodingRouteSession()
  } else {
    selectedCodingModelValue.value = normalizeCodingModelValue(selectedCodingModelValue.value)
  }
})

onUnmounted(() => {
  document.removeEventListener('click', closeCodingModelMenuOnOutside)
})

// ============ Workspace Operations ============

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
    deployAppId.value = workspaceConversation.coding_app_id ?? null
    deployMode.value = 'bound'
    if (deployAppId.value) {
      const appName = sceneApps.value.find(a => a.id === deployAppId.value)?.name || '应用'
      handoffSourceApp.value = { id: String(deployAppId.value), name: appName }
    } else {
      handoffSourceApp.value = null
    }

    // 从后端加载历史消息填充到 streamMessages
    loadConversationHistory(
      workspaceConversation.messages,
      workspaceConversation.stream_messages || [],
    )
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
  for (let k = 0; k < messages.length; k++) {
    const msg = messages[k]
    if (!msg) continue
    const content = msg.content || ''
    if (msg.role === 'user') {
      addStreamMsg({ type: 'user', content })
    } else if (msg.role === 'assistant') {
      if (content.startsWith('<!-- BRAINSTORM_CLARIFY -->')) {
        // 澄清(JSON)→ 还原成可点选项卡片;若后面已有 user 回答则置灰
        const raw = content.replace(/^<!-- BRAINSTORM_CLARIFY -->/, '').trim()
        let q = raw; let opts: string[] = []
        try {
          const parsed = JSON.parse(raw)
          q = parsed.question || raw; opts = Array.isArray(parsed.options) ? parsed.options : []
        } catch { /* 非 JSON(旧 markdown 澄清)→ 当问题文本展示 */ }
        const nextUser = messages.slice(k + 1).find(m => m?.role === 'user')
        addStreamMsg({ type: 'clarify', content: q, question: q, options: opts, answered: nextUser?.content })
      } else if (content.startsWith('<!-- BRAINSTORM_PROPOSAL -->')) {
        addStreamMsg({
          type: 'message',
          content: content.replace(/^<!-- BRAINSTORM_PROPOSAL -->/, '').trim(),
        })
      } else if (/🔧|✨|Agent (完成|错误)|>\s*[✅❌]/.test(content)) {
        // codegen 叙述(含工具/Agent 标记)→ 按原逻辑解析成工具/思考卡片
        parseAssistantHistory(content)
      } else {
        // 纯文本答案(如 READ 路径的查询回答)→ 正常 Markdown 消息,不塞进折叠思考卡
        addStreamMsg({ type: 'message', content })
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

// 清回「新建会话」欢迎态(不导航)。startNewWorkspace = 它 + 跳 /coding;
// rail 点「新建会话」导航到无参 /coding 时, query watcher 也调它(因 /coding 现在稳定 key 不 remount)。
function resetCodingToWelcome() {
  abortInflightStream()  // 新建会话前掐断旧 SSE(防旧流写进新建态)
  handoffSourceApp.value = null
  deployAppId.value = null; deployMode.value = 'bound'  // 重置分场景部署绑定(新会话从分场景入口重新选)
  codingStore.reset()
  persistedCodingModelValue.value = null
  selectedCodingModelValue.value = normalizeCodingModelValue(selectedCodingModelValue.value)
  streamMessages.value = []
  localStorage.removeItem('coding_last_workspace_id')
}
function startNewWorkspace() {
  resetCodingToWelcome()
  router.replace({ path: '/coding' }).catch(() => {})
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

function handleComposerFiles(files: File[]) {
  const file = files[0]
  if (file) setAttachment(file)
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
// SSE handlers + upload + build request + consume SSE + sendMessage
// 全部抽到 useCodingPipeline composable
const { sendMessage, stopStream } = useCodingPipeline({
  model: { codingModelOptions, codingModelLoading, updatingCodingModel, selectedCodingModelValue, persistedCodingModelValue, selectedCodingModelOption, codingModelHint, toCodingModelValue, normalizeCodingModelValue, applyCodingModelSelection, loadCodingModelOptions, handleCodingModelChange } as any,
  stream: { streamMessages, isStreaming, streamContainerRef, scrollStreamToBottom, addStreamMsg, appendToLastThinking, appendToLastCommand, completeStepMsg, addStepRunningMsg, restoreReplayStreamMessages } as any,
  workspace: { allWorkspaces, isDownloading, embeddedAppId, existingWorkspaces, workspaceDisplayName } as any,
  activeSceneCategory,
  pendingSceneCategory,
  sceneCategoryToProjectType,
  userInput,
  attachedFile,
  attachedPreviewUrl,
  isUploading,
  isCreating,
  boundAppId: deployAppId,
  onAfterPipeline: () => {
    refreshCodingConversations()
    // 流式建出会话后把地址栏同步成带 conversation_id —— 否则页面停在裸 /coding 却有内容,
    // 之后点 rail「新建会话」(也跳裸 /coding)query 没变, watcher 不触发, 残留内容清不掉。
    if (codingStore.conversationId) syncCodingUrl(codingStore.conversationId)
  },
})


// ============ Header Actions ============

async function openBrowserPreviewWithEnv(env: PlatformEnv) {
  if (!codingStore.workspace) return
  showEnvPicker.value = false
  const platformBase = env.base_url.replace(/\/backend\/?$/, '')
  void openExternal(platformBase)
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

// 主题变更只影响 Web 工作区自身，不再同步外部 IDE。

watch(() => codingStore.conversationId, (id, oldId) => {
  // 仅在切换离开非空会话时清 token 用量态，避免旧会话的告警/百分比泄漏到新会话
  // 首轮新会话(oldId==null)不清，防止 done handler 设置的 tokenUsage 被误抹
  if (oldId != null) {
    codingStore.tokenUsage = null
    codingStore.contextWarnDismissed = false
  }
  if (!id) return
  window.setTimeout(() => {
    refreshCodingConversations()
  }, 300)
})

watch(() => codingStore.workspace?.id, (id) => {
  if (!id) return
  window.setTimeout(() => {
    refreshCodingConversations()
  }, 300)
})

watch(() => route.path, () => {
  if (!route.path.startsWith('/coding')) {
    codingStore.reset()
  }
})

// /coding 现在用稳定 key(App.vue), query 变化不再 remount → 监听 query 原地切会话/工作区(不闪)。
// onMounted 首次解析; 之后 rail 点会话/新建走这里。syncCodingUrl 用 history 不改 vue-route, 不会回环触发。
watch(
  () => `${route.query.conversation_id ?? ''}|${route.query.workspace_id ?? route.query.ws ?? ''}`,
  () => {
    if (route.path !== '/coding') return
    const convId = Number(route.query.conversation_id)
    const wsId = (route.query.workspace_id || route.query.ws) as string
    const hasSession = !!wsId || (Number.isFinite(convId) && convId > 0)
    if (!hasSession) {
      // 导航到无参 /coding(rail「新建会话」)→ 回欢迎态(仅当前有加载内容时才清, 避免空转)
      if (codingStore.workspace || codingStore.conversationId || streamMessages.value.length) {
        resetCodingToWelcome()
      }
      return
    }
    void resolveCodingRouteSession()
  },
)
</script>

<style scoped src="./CodingPage.styles.css"></style>

<style src="./CodingPage.global.css"></style>
