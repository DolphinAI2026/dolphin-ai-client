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

    <div class="coding-body" :class="{ 'code-first': codeFirst }">
      <SessionSidebar
        v-if="!embedMode && !embeddedAppId && !codeFirst"
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
      <div
        class="main-content"
        :style="codeFirst ? { flex: `0 0 ${chatPaneWidth}px`, width: `${chatPaneWidth}px` } : null"
      >
        <div v-if="codeFirst" class="chat-resizer" @pointerdown="onChatResizeStart" title="拖拽调整聊天宽度" />
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

        <div v-if="showCodingUnselected" class="coding-unselected-pane">
          <header class="coding-session-header">
            <div class="coding-session-title-block">
              <strong class="coding-session-title">未选择会话</strong>
            </div>
          </header>
          <div class="coding-unselected-welcome">
            <h2>代码工作区</h2>
            <p>从左侧选择一个开发会话继续，或点击上方「+ 新会话」开始新的自开发任务。AI 会在会话里整理任务、创建工作区，并持续生成页面、接口、脚本或扩展代码。</p>
          </div>
        </div>

        <!-- Stream Pane (对话流视图 - 2026-05-17 B 重构：永远显示，IDE/文件改抽屉) -->
        <div v-else class="stream-pane">
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
              <button class="cca-btn" :title="chatExpanded ? '还原对话宽度' : '放大对话'" @click="toggleChatExpand">
                <AppIcon :name="chatExpanded ? 'shrink' : 'expand'" :size="14" />
              </button>
            </div>
          </header>

          <CodingSceneEntry
            v-if="!isStreaming && streamMessages.length === 0 && !codeFirst"
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

          <!-- Chat 底部输入框（始终可见:流式中也能输入,按 Enter 进队列;红色按钮可停止生成） -->
          <div v-if="streamMessages.length > 0 || codeFirst" class="chat-input-bar">
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
              @send="sendOrQueue"
              @stop="stopStream"
              @files-picked="handleComposerFiles"
              @remove-attachment="removeAttachment"
            >
              <template #footer-left>
                <!-- 紧凑原生模型选择(对齐 AI Chat 的 model-select-inline,克制不抢眼) -->
                <select
                  class="coding-model-select"
                  :value="selectedCodingModelValue ?? ''"
                  :disabled="codingModelLoading || updatingCodingModel || codingModelOptions.length === 0"
                  :title="codingModelHint"
                  aria-label="选择模型"
                  @change="handleCodingModelChange((($event.target as HTMLSelectElement).value) || null)"
                >
                  <option v-if="codingModelOptions.length === 0" value="">默认模型</option>
                  <option
                    v-for="option in codingModelOptions"
                    :key="option.id"
                    :value="toCodingModelValue(option.id) ?? ''"
                  >{{ option.config_name }}</option>
                </select>
              </template>
            </UnifiedChatComposer>
          </div>
        </div>

      </div>

      <!-- Task 7: 原生文件树 + 代码查看器（常驻右栏，替换 IDE 抽屉视图） -->
      <div
        v-if="codingStore.workspace?.id && !embeddedAppId"
        class="ws-pane"
      >
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

      <!-- 文件抽屉：显示 workspace 文件列表 (P0 留 stub，P1 接 ws files API) -->
      <el-drawer v-model="filesDrawerOpen" title="工作区文件" direction="rtl" size="40%" body-class="coding-files-drawer-body" :append-to-body="true">
        <div class="files-drawer-body">
          <p style="color:#999;font-size:13px;padding:16px;">
            <AppIcon name="clipboard" :size="13" /> 文件浏览 MVP — 当前展示 workspace 元信息，详细文件树后续接入。
          </p>
          <div v-if="codingStore.workspace" style="padding:0 16px;">
            <div style="margin-bottom:12px;"><strong>名称：</strong>{{ codingStore.workspace.display_name || codingStore.workspace.project_name }}</div>
            <div style="margin-bottom:12px;"><strong>类型：</strong>{{ codingStore.workspace.project_type }}</div>
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
              <span class="cap-deploy-hint">{{ isBoundDeploy ? '关联到应用 + 重新发布让组件生效' : '上传到自开发资产库,跨应用复用' }}</span>
            </div>
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
import { useCodingWorkspace } from './coding/useCodingWorkspace'
import { useCodingPipeline } from './coding/useCodingPipeline'
import UnifiedChatComposer from '@/components/common/UnifiedChatComposer.vue'
import type { UnifiedChatAttachment } from '@/components/common/chatComposer'
import FileTree from './coding/FileTree.vue'
import CodeViewer from './coding/CodeViewer.vue'
import { buildFileTree, type TreeNode } from './coding/fileTree'
import { collectChangedFiles, normalizeWorkspacePathLabel, type FileChangeMsg } from './coding/workspaceChanges'
import { usePanelResize } from '@/components/v2/config-assistant/composables/usePanelResize'
import { listWorkspaceFiles, getWorkspaceChanges, acceptWorkspaceChanges, type WorkspaceChanges } from '@/api/coding'

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

// 点击对话里的写/改文件卡 → 左侧打开该文件（有 git 改动 CodeViewer 自动进对比模式）
function openFileFromChat(sm: { filePath?: string; fileName?: string }) {
  const rawPath = normalizeWorkspacePathLabel(sm.filePath || sm.fileName)
  const target = resolveWorkspacePath(rawPath) || rawPath || null
  if (target) selectedFile.value = target
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
watch(() => wsChanges.value.lastChangedFile, (p) => { if (p) selectedFile.value = p })
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
// 右侧聊天列可拖宽（复用 config 的 usePanelResize，handle 在聊天列左边界）
const { panelWidth: chatPaneWidth, onResizeStart: onChatResizeStart } = usePanelResize({
  storageKey: 'coding:chat-pane-width',
  defaultWidth: 420,
  minWidth: 320,
  maxWidth: 760,
})

// ── code-first 聊天头部: 会话历史 / 新建会话 / 放大(对齐配置助手) ──
const chatExpanded = ref(false)
let chatWidthBeforeExpand = 420
function toggleChatExpand() {
  if (chatExpanded.value) {
    chatPaneWidth.value = chatWidthBeforeExpand
    chatExpanded.value = false
  } else {
    chatWidthBeforeExpand = chatPaneWidth.value
    chatPaneWidth.value = Math.min(Math.floor(window.innerWidth * 0.55), 980)
    chatExpanded.value = true
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

// 头部切换 = 只换聊天上下文, 工作区(文件树/查看器)保持不动
async function switchConversationFromHeader(id: number) {
  if (id === codingStore.conversationId) return
  handoffSourceApp.value = null
  const _boundAppId = codingConversations.value.find(c => c.id === id)?.coding_app_id ?? null
  deployAppId.value = _boundAppId
  deployMode.value = 'bound'
  try {
    // 切回工作区主会话时优先富回放(结构化工具卡/diff), 其他会话纯消息回放
    if (codingStore.workspace?.id) {
      try {
        const wc = await codingApi.getWorkspaceConversation(codingStore.workspace.id)
        if (wc.conversation_id === id) {
          codingStore.conversationId = id
          applyCodingModelSelection(wc.selected_llm_config_id)
          loadConversationHistory(wc.messages, wc.stream_messages || [])
          syncCodingUrl(id)
          return
        }
      } catch { /* 降级走纯消息回放 */ }
    }
    const messages = await codingApi.getMessages(id)
    codingStore.conversationId = id
    loadConversationHistory(messages as any, [])
    syncCodingUrl(id)
  } catch (e: any) {
    ElMessage.error(`切换会话失败: ${e?.message || e}`)
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
      out.push({ id: 'sm' + i, kind: 'user', content: msg.content })
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

const showCodingUnselected = computed(() =>
  !isStreaming.value &&
  streamMessages.value.length === 0 &&
  !codingStore.workspace &&
  !codingStore.conversationId,
)

async function loadCodingConversationOnly(conversationId: number) {
  handoffSourceApp.value = null  // F3: 切到已有会话时清掉 handoff 回跳链，避免串到别的会话
  // 恢复「在应用上定制」绑定:会话持久化了 coding_app_id 就接着绑(刷新/侧栏点开仍记得是哪个应用),
  // 没有才清空,避免把上个会话选的应用串过来。后端也会从会话回读做兜底,这里主要保证 UI 一致。
  const _boundAppId = codingConversations.value.find(c => c.id === conversationId)?.coding_app_id ?? null
  deployAppId.value = _boundAppId; deployMode.value = 'bound'
  const messages = await codingApi.getMessages(conversationId)
  codingStore.reset()
  codingStore.conversationId = conversationId
  localStorage.removeItem('coding_last_workspace_id')
  loadConversationHistory(messages as any, [])
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
  { icon: 'store', title: '资产登记', desc: '同时登记到自开发资产库,可跨应用复用' },
] : [
  { icon: 'store', title: '自开发资产库', desc: '上传到组件库,可在任意应用的表单设计器中引用' },
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
      ElMessage.success(r.hint || '已发布到自开发资产库')
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

  const wsId = (route.query.workspace_id || route.query.ws) as string
  if (wsId) {
    await openWorkspaceById(wsId)
    // URL 还带 conversation_id 且不是工作区主会话(头部切过会话后刷新) → 保工作区, 切回该会话
    const _qConvId = Number(route.query.conversation_id)
    if (Number.isFinite(_qConvId) && _qConvId > 0 && _qConvId !== codingStore.conversationId) {
      await switchConversationFromHeader(_qConvId)
    }
  } else {
    const conversationId = Number(route.query.conversation_id)
    if (Number.isFinite(conversationId) && conversationId > 0) {
      // F2: 直接导航到 /coding?conversation_id=N 时，若该会话有 workspace（codegen 会话），
      // 走 openWorkspaceById 恢复结构化工具卡历史（与 onSidebarCodingSelect 一致）；
      // 无 workspace（如 READ 问答会话）才降级为纯文本 loadCodingConversationOnly。
      let wsForConv: string | null = null
      try {
        const relation = await codingApi.getConversationWorkspace(conversationId)
        wsForConv = relation.workspace_id
      } catch {
        wsForConv = null
      }
      if (wsForConv) {
        await openWorkspaceById(wsForConv)
        router.replace({ path: '/coding', query: { conversation_id: String(conversationId), workspace_id: wsForConv } }).catch(() => {})
      } else {
        await loadCodingConversationOnly(conversationId)
      }
    } else {
      selectedCodingModelValue.value = normalizeCodingModelValue(selectedCodingModelValue.value)
    }
  }
})

onUnmounted(() => {
  // cleanup if needed
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

function startNewWorkspace() {
  handoffSourceApp.value = null
  deployAppId.value = null; deployMode.value = 'bound'  // 重置分场景部署绑定(新会话从分场景入口重新选)
  codingStore.reset()
  persistedCodingModelValue.value = null
  selectedCodingModelValue.value = normalizeCodingModelValue(selectedCodingModelValue.value)
  streamMessages.value = []
  localStorage.removeItem('coding_last_workspace_id')
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
// SSE handlers + upload + build request + consume SSE + load IDE URL + sendMessage
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
  onAfterPipeline: refreshCodingConversations,
})


// ============ Header Actions ============

async function openBrowserPreviewWithEnv(env: PlatformEnv) {
  if (!codingStore.workspace) return
  showEnvPicker.value = false
  const platformBase = env.base_url.replace(/\/backend\/?$/, '')
  window.open(platformBase, '_blank', 'noopener,noreferrer')
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

// 主题变更不再需要同步 IDE URL（IDE 已删）

watch(() => codingStore.conversationId, (id) => {
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
/* F3: 会话表头里的「← 回 Builder」回跳链，靠右、蓝色 accent */
.coding-back-to-builder {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 28px;
  padding: 0 10px;
  border: 1px solid var(--t-brand);
  border-radius: 7px;
  background: transparent;
  color: var(--t-brand);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s ease;
}
.coding-back-to-builder:hover {
  background: color-mix(in srgb, var(--t-brand) 12%, transparent);
  color: var(--t-brand);
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
  background: var(--t-brand-primary-subtle, rgba(29, 78, 216, 0.12));
  color: var(--t-brand-primary, #1D4ED8);
  border-color: var(--t-brand-primary, #1D4ED8);
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
  background: var(--t-brand-primary, #1D4ED8);
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

/* 2026-05-21 UI audit Fix 17: SessionSidebar 右边框加重 + bg 略偏白让左右两区视觉清晰
   原 SessionSidebar 自身 border 用 --t-border-soft (alpha 0.16) 太弱，从 CodingPage 这边强化 */
.coding-body :deep(.session-sidebar) {
  background: var(--t-bg-elevated, #ffffff);
  border-right-color: var(--t-border-strong, rgba(11, 27, 63, 0.14));
  box-shadow: 1px 0 0 rgba(11, 27, 63, 0.04);
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
  background: var(--t-bg-base, #f7f9fd);
}

.welcome-inner {
  width: min(100%, 900px);
  min-height: 100%;
  margin: 0 auto;
  padding: 72px 32px 56px;
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
  gap: 18px;
}

/* ============ Welcome Input Area ============ */
.welcome-input-area {
  width: min(100%, 1280px);
  margin-bottom: 12px;
}

/* 紧凑原生模型选择(对齐 AI Chat 的 model-select-inline,克制不抢眼) */
.coding-model-select {
  background: transparent;
  border: 1px solid var(--t-border-subtle);
  color: var(--t-text-muted);
  padding: 3px 8px;
  border-radius: 5px;
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  outline: none;
  max-width: 220px;
  transition: border-color 0.14s ease, color 0.14s ease;
}
.coding-model-select:hover:not(:disabled) { border-color: var(--t-border-strong); color: var(--t-text-primary); }
.coding-model-select:disabled { opacity: 0.55; cursor: not-allowed; }

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
  .welcome-hero {
    min-height: auto;
    justify-content: flex-start;
  }

  .composer-topline {
    flex-direction: column;
    align-items: stretch;
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
  width: min(100%, 760px);
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
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 6px;
  text-align: left;
}

.coding-command-kicker {
  margin: 0;
  color: #6f7ff2;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: none;
}

.coding-command-title {
  margin: 0;
  color: var(--t-text-primary);
  font-size: 26px;
  line-height: 1.25;
  font-weight: 720;
  letter-spacing: 0;
}

.coding-command-subtitle {
  margin: 0;
  max-width: 680px;
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
  padding: 0;
  box-shadow: 0 10px 28px rgba(15, 23, 42, 0.05);
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.qc-shell:focus-within {
  border-color: #c7d2fe;
  box-shadow: 0 0 0 3px rgba(111, 127, 242, 0.10);
}

.qc-shell :deep(.ucc) {
  display: flex;
}

.qc-shell :deep(.ucc-box) {
  border: 0;
  border-radius: 0;
  background: #fff;
}

.qc-shell :deep(.ucc-input) {
  min-height: 58px;
  padding: 14px 16px 2px;
  font-size: 14px;
  line-height: 1.55;
}

.qc-shell :deep(.ucc-input::placeholder) {
  color: #73819a;
}

.qc-shell :deep(.ucc-footer) {
  min-height: 42px;
  padding: 0 12px 10px;
}

.qc-shell :deep(.ucc-attach) {
  min-height: 36px;
  padding: 0 13px;
  border-radius: 8px;
  font-size: 13.5px;
  color: var(--text-2, #52617a);
}

.qc-shell :deep(.ucc-hint) {
  font-size: 12.5px;
}

.qc-shell :deep(.ucc-send) {
  width: 48px;
  height: auto;
  min-height: 48px;
  border-radius: 0;
  border-top: 0;
  border-right: 0;
  border-bottom: 0;
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
  /* 2026-05-21 UI audit Fix 18: center → flex-start，让多行 pill 顶部对齐而不是中线对齐 */
  align-items: flex-start;
  gap: 8px;
  color: var(--t-text-muted);
  font-size: 12px;
  line-height: 1.4;
}

.qc-hints-label {
  flex-shrink: 0;
  margin-right: 2px;
  /* 2026-05-21 UI audit Fix 18: align-items: flex-start 后，label 加 padding-top 与 pill 第一行视觉对齐 */
  padding-top: 6px;
  color: var(--t-text-muted);
  font-weight: 600;
}

.qc-hint-item {
  border: 1px solid #dbe2ea;
  background: #fff;
  color: #61708c;
  font-size: 12px;
  cursor: pointer;
  padding: 6px 12px;
  border-radius: 14px;
  transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease, transform 0.15s ease;
  /* 2026-05-21 UI audit Fix 18: 长 prompt 不要截断 — 限宽 + 允许换行 + 行高调好
     原 border-radius 999px 在多行时变怪，改 14px 长方圆角 */
  max-width: 300px;
  text-align: left;
  white-space: normal;
  line-height: 1.45;
  word-break: break-word;
  /* 行内 button 默认 inherit display；保留 flex 让父 .qc-hints 排版正常 */
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
  /* 2026-05-21 UI audit Fix 18: 分隔点也对齐到 pill 第一行中部 */
  padding-top: 6px;
}

@media (max-width: 760px) {
  .welcome-inner {
    padding: 36px 18px 32px;
    gap: 20px;
  }

  .coding-command-title {
    font-size: 24px;
  }

  .qc-section {
    width: 100%;
  }

  .qc-shell {
    padding: 0;
    border-radius: 14px;
  }

  .qc-shell :deep(.ucc-input) {
    min-height: 68px;
    padding: 14px 14px 2px;
    font-size: 15px;
  }

  .qc-shell :deep(.ucc-footer) {
    padding-right: 12px;
  }

  .qc-shell :deep(.ucc-send) {
    width: 46px;
    min-height: 46px;
    border-radius: 0;
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
  background: var(--t-bg-base, #f7f9fd);
}

.coding-unselected-pane {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--t-bg-base, #f7f9fd);
}

.coding-unselected-welcome {
  flex: 1;
  min-height: 0;
  display: grid;
  place-content: center;
  justify-items: center;
  gap: 10px;
  padding: 32px;
  text-align: center;
  color: var(--t-text-secondary);
}

.coding-unselected-welcome h2 {
  margin: 0;
  color: var(--t-text-primary);
  font-size: 22px;
  line-height: 1.25;
  font-weight: 720;
}

.coding-unselected-welcome p {
  max-width: 560px;
  margin: 0;
  color: var(--t-text-muted);
  font-size: 13px;
  line-height: 1.7;
}

/* ── code-first 聊天头部动作: 会话历史 / 新建 / 放大 ── */
.coding-chat-actions {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex: none;
}
.cca-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 1px solid var(--t-border-subtle, rgba(116, 128, 171, 0.16));
  border-radius: 7px;
  background: transparent;
  color: var(--t-text-muted, #888);
  cursor: pointer;
  transition: background 0.12s ease, color 0.12s ease;
}
.cca-btn:hover { background: var(--t-bg-panel-hover, rgba(0, 0, 0, 0.05)); color: var(--t-text-primary, #222); }
.cca-conv-list { max-height: 320px; overflow: auto; display: flex; flex-direction: column; gap: 2px; }
.cca-conv-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 7px 10px;
  border: none;
  border-radius: 6px;
  background: transparent;
  cursor: pointer;
  text-align: left;
  font-size: 13px;
  color: var(--t-text-primary, #333);
}
.cca-conv-item:hover { background: var(--t-bg-panel-hover, rgba(0, 0, 0, 0.05)); }
.cca-conv-item.active { background: var(--brand-soft, rgba(99, 102, 241, 0.1)); color: var(--brand-ink, #4f46e5); }
.cca-conv-title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cca-conv-time { flex: none; font-size: 11px; color: var(--t-text-muted, #999); }
.cca-conv-empty { margin: 10px; font-size: 12.5px; color: var(--t-text-muted, #999); }

/* ── codeFirst 空态建议提问 ── */
.coding-empty-suggestions {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  margin-top: 18px;
}
.ces-chip {
  max-width: 320px;
  padding: 7px 16px;
  border: 1px solid var(--t-border-subtle, rgba(116, 128, 171, 0.2));
  border-radius: 999px;
  background: var(--t-bg-panel, #fff);
  color: var(--t-text-secondary, #555);
  font-size: 13px;
  cursor: pointer;
  transition: border-color 0.12s ease, color 0.12s ease, background 0.12s ease;
}
.ces-chip:hover {
  border-color: color-mix(in srgb, var(--brand, #4f6ef7) 40%, transparent);
  color: var(--brand-ink, var(--brand, #4f46e5));
  background: var(--brand-soft, rgba(79, 110, 247, 0.06));
}

.coding-session-header {
  flex-shrink: 0;
  min-height: 58px;
  padding: 10px 22px;
  border-bottom: 1px solid var(--t-border-subtle, rgba(116, 128, 171, 0.16));
  background: var(--t-bg-elevated, #fff);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.coding-session-title-block {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.coding-session-kicker {
  color: var(--t-brand);
  font-size: 11px;
  font-weight: 700;
  line-height: 1.2;
}

.coding-session-title {
  max-width: 520px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--t-text-primary);
  font-size: 15px;
  line-height: 1.3;
}

.coding-session-ide-btn {
  height: 32px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 12px;
  border: 1px solid var(--t-border-subtle, rgba(116, 128, 171, 0.18));
  border-radius: 8px;
  background: var(--t-bg-base, #f8fafc);
  color: var(--t-text-secondary);
  font-size: 12px;
  font-weight: 650;
  cursor: pointer;
}

.coding-session-ide-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.coding-empty-thread {
  flex: 1;
  min-height: 0;
  display: grid;
  place-content: center;
  gap: 6px;
  text-align: center;
  color: var(--t-text-muted);
}

.coding-empty-title {
  color: var(--t-text-secondary);
  font-size: 14px;
  font-weight: 650;
}

.coding-empty-sub {
  font-size: 12.5px;
}

.stream-pane :deep(.agent-conversation) {
  flex: 1;
  min-height: 0;
}

/* 把对话收进一个居中的可读列 —— 宽主区不再 edge-to-edge 左铺、右侧留大片空,
   跟 Builder 侧栏 / Claude / ChatGPT 一样耐看。仅 CodingPage 作用域,不影响共享组件别处。
   每行限宽居中,行内 user 右 / assistant 左 的对齐语义保持不变。 */
.stream-pane :deep(.ac-row) {
  width: 100%;
  max-width: 880px;
  margin-inline: auto;
}
/* assistant 内容填满该列(否则 fit-content 挤成窄条、SPEC 表格没地方),
   与上下工具卡同宽,整列宽度一致更整齐(临时预览页截图自测确认过) */
.stream-pane :deep(.ac-row.assistant .ac-assistant-wrap),
.stream-pane :deep(.ac-bubble.assistant-naked) {
  width: 100%;
  max-width: 100%;
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

/* thinking / status / tool 的卡片样式已随「迁移到 AgentConversation 原生 kind」一并移除
   （thinking→原生 thinking、tool→ToolCard、status→原生 status pill;见 agentMessages 映射 + ToolCard.vue）。
   command / file 卡 native 无对应 kind,仍走 #custom slot,样式见下方 .msg-command-card / .msg-file-card。 */

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
/* 输入框收进与对话同宽的居中列(880),全宽分隔线保留 */
.chat-input-bar :deep(.ucc) {
  max-width: 880px;
  margin-inline: auto;
}

html:not([data-theme="dark"]) .chat-input-bar :deep(.ucc-box) {
  background: var(--t-bg-panel, #ffffff);
  border-color: var(--t-border-subtle, rgba(15, 23, 42, 0.08));
  box-shadow: 0 10px 28px rgba(15, 23, 42, 0.06);
}

html:not([data-theme="dark"]) .chat-input-bar :deep(.ucc-box:focus-within) {
  border-color: rgba(79, 110, 247, 0.34);
  box-shadow:
    0 12px 32px rgba(15, 23, 42, 0.08),
    0 0 0 3px rgba(79, 110, 247, 0.10);
}

html:not([data-theme="dark"]) .chat-input-bar :deep(.ucc-input) {
  color: var(--t-text-primary, #1e293b);
}

html:not([data-theme="dark"]) .chat-input-bar :deep(.ucc-input::placeholder) {
  color: rgba(100, 116, 139, 0.62);
}

/* 排队消息提示卡:流式中再输入会进队列,居中同列(880) */
.coding-queue-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  max-width: 880px;
  margin: 0 auto 8px;
  padding: 7px 12px;
  border: 1px solid var(--t-border-subtle);
  border-radius: 10px;
  background: var(--t-bg-panel);
  font-size: 12.5px;
  color: var(--t-text-secondary);
}
.cqb-icon { flex-shrink: 0; font-size: 13px; }
.cqb-text { flex: 1; min-width: 0; }
.cqb-clear {
  flex-shrink: 0;
  width: 20px; height: 20px;
  display: inline-flex; align-items: center; justify-content: center;
  border: none; border-radius: 6px;
  background: transparent; color: var(--t-text-muted);
  font-size: 15px; line-height: 1; cursor: pointer;
}
.cqb-clear:hover { background: var(--t-bg-elevated); color: var(--t-text-primary); }

/* SPEC 确认门 bar(出 SPEC 后等确认,brand 强调) */
.coding-confirm-bar {
  flex-shrink: 0;
  width: calc(100% - 32px);
  max-width: 880px;
  margin: 0 auto 10px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 13px 16px;
  border: 1px solid var(--t-brand);
  border-radius: 14px;
  background: color-mix(in srgb, var(--t-brand) 7%, var(--t-bg-panel));
}
.ccb-text { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.ccb-text strong { font-size: 13.5px; font-weight: 650; color: var(--t-text-primary); }
.ccb-text span { font-size: 12px; color: var(--t-text-muted); }
.ccb-actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.ccb-btn {
  display: inline-flex; align-items: center; gap: 6px;
  height: 34px; padding: 0 16px; border: none; border-radius: 9px;
  background: var(--t-brand); color: #fff; font-size: 13px; font-weight: 600;
  cursor: pointer; flex-shrink: 0; transition: filter 0.15s ease;
}
.ccb-btn:hover { filter: brightness(0.92); }
.ccb-btn-ghost {
  display: inline-flex; align-items: center; gap: 6px;
  height: 34px; padding: 0 13px; border: 1px solid var(--t-border-strong); border-radius: 9px;
  background: transparent; color: var(--t-text-secondary); font-size: 13px; font-weight: 500;
  cursor: pointer; flex-shrink: 0; transition: all 0.15s ease;
}
.ccb-btn-ghost:hover { border-color: var(--t-brand); color: var(--t-brand); }
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

/* ── 开发文档 tab(对标 Builder 设计文档:渲染/原文 + 文档观感)── */
.cap-spec-bar { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 12px; }
.cap-spec-seg { display: inline-flex; border: 1px solid var(--t-border-subtle); border-radius: 8px; overflow: hidden; }
.cap-spec-seg button { height: 28px; padding: 0 12px; border: none; background: transparent; color: var(--t-text-secondary); font-size: 12.5px; cursor: pointer; }
.cap-spec-seg button.on { background: var(--t-brand); color: #fff; }
.cap-spec-cta { height: 28px; padding: 0 14px; border: none; border-radius: 8px; background: var(--t-brand); color: #fff; font-size: 12.5px; font-weight: 600; cursor: pointer; }
.cap-spec-raw { margin: 0; padding: 12px; background: var(--t-bg-soft, rgba(15, 23, 42, 0.05)); border-radius: 10px; font-size: 12px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; color: var(--t-text-primary); font-family: var(--font-mono, ui-monospace, monospace); }
.cap-spec-doc { font-size: 13px; line-height: 1.7; color: var(--t-text-primary); }
.cap-spec-doc :deep(h1), .cap-spec-doc :deep(h2) { font-size: 15.5px; font-weight: 700; margin: 14px 0 8px; }
.cap-spec-doc :deep(h3) { font-size: 13.5px; font-weight: 650; margin: 13px 0 6px; }
.cap-spec-doc :deep(p) { margin: 0 0 8px; }
.cap-spec-doc :deep(ul), .cap-spec-doc :deep(ol) { margin: 6px 0; padding-left: 20px; }
.cap-spec-doc :deep(li) { margin: 3px 0; }
.cap-spec-doc :deep(table) { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 12px; }
.cap-spec-doc :deep(th), .cap-spec-doc :deep(td) { border: 1px solid var(--t-border-subtle); padding: 6px 9px; text-align: left; vertical-align: top; word-break: break-word; }
.cap-spec-doc :deep(th) { background: var(--t-bg-soft, rgba(15, 23, 42, 0.04)); font-weight: 600; }
.cap-spec-doc :deep(code) { background: var(--t-bg-soft, rgba(15, 23, 42, 0.06)); padding: 1px 5px; border-radius: 4px; font-size: 12px; font-family: var(--font-mono, ui-monospace, monospace); }
.cap-spec-doc :deep(hr) { border: none; border-top: 1px solid var(--t-border-subtle); margin: 12px 0; }
.cap-spec-doc :deep(strong) { font-weight: 650; }

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
.cap-deploy-cta {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px;
  margin-bottom: 10px;
  border-radius: 12px;
  background: var(--brand-soft);
  border: 1px solid var(--brand-soft-2);
}
.cap-deploy-btn {
  height: 38px;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  background: var(--blue-950);
  color: #fff;
  font-size: 13.5px;
  font-weight: 600;
  font-family: var(--font-mono);
  transition: transform 0.15s;
}
.cap-deploy-btn:hover { transform: translateY(-1px); }
.cap-deploy-hint { font-size: 11px; color: var(--text-3); text-align: center; }
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
/* 2026-05-17 文件 / 设置抽屉 body padding 0：
   append-to-body=true → 必须用全局（非 scoped）CSS。
   body-class prop 把这些类直接打到 .el-drawer__body 上。 */
.coding-files-drawer-body,
.coding-edit-drawer-body {
  padding: 0 !important;
  display: flex !important;
  flex-direction: column;
  overflow: hidden;
}

html:not([data-theme="dark"]) .coding-body.code-first {
  background: #f3f6fb !important;
  color: #172033;
}

html:not([data-theme="dark"]) .coding-body.code-first .ws-pane {
  --bg: #ffffff;
  --bg-sub: #f8fafc;
  --bg-hover: #eef3fb;
  --fg: #172033;
  --fg-muted: #475569;
  --fg-dim: #64748b;
  --fg-faint: #94a3b8;
  --line: rgba(15, 23, 42, 0.08);
  --line-strong: rgba(15, 23, 42, 0.14);
  background: #ffffff;
}

html:not([data-theme="dark"]) .coding-body.code-first .ws-pane-tree {
  border-right-color: rgba(15, 23, 42, 0.09);
}

html:not([data-theme="dark"]) .coding-body.code-first .ws-pane-viewer {
  background: #ffffff;
}

html:not([data-theme="dark"]) .coding-body.code-first .main-content {
  background: #f7f9fd;
  border-left-color: rgba(15, 23, 42, 0.09);
  box-shadow: -12px 0 30px rgba(15, 23, 42, 0.035);
}

html:not([data-theme="dark"]) .coding-body.code-first .stream-pane {
  background: linear-gradient(180deg, #f8faff 0%, #f4f7fc 100%);
}

html:not([data-theme="dark"]) .coding-body.code-first .coding-session-header {
  background: rgba(255, 255, 255, 0.92);
  border-bottom-color: rgba(15, 23, 42, 0.08);
  box-shadow: 0 1px 0 rgba(255, 255, 255, 0.72);
}

html:not([data-theme="dark"]) .coding-body.code-first .coding-session-kicker {
  color: #4f6ef7;
  letter-spacing: 0.02em;
}

html:not([data-theme="dark"]) .coding-body.code-first .coding-session-title {
  color: #0f172a;
  font-weight: 720;
}

html:not([data-theme="dark"]) .coding-body.code-first .cca-btn {
  background: #ffffff;
  border-color: rgba(15, 23, 42, 0.14);
  color: #334155;
  box-shadow:
    0 1px 2px rgba(15, 23, 42, 0.05),
    inset 0 0 0 1px rgba(255, 255, 255, 0.70);
}

html:not([data-theme="dark"]) .coding-body.code-first .cca-btn .app-icon {
  color: inherit !important;
  opacity: 1;
}

html:not([data-theme="dark"]) .coding-body.code-first .cca-btn .app-icon svg {
  color: inherit !important;
}

html:not([data-theme="dark"]) .coding-body.code-first .cca-btn:hover {
  background: #eef3ff;
  border-color: rgba(79, 110, 247, 0.36);
  color: #2445d8;
  box-shadow:
    0 4px 10px rgba(79, 110, 247, 0.10),
    inset 0 0 0 1px rgba(255, 255, 255, 0.72);
}

html:not([data-theme="dark"]) .coding-body.code-first .cca-btn:focus {
  outline: none;
}

html:not([data-theme="dark"]) .coding-body.code-first .cca-btn:focus-visible {
  border-color: rgba(79, 110, 247, 0.42);
  box-shadow: 0 0 0 3px rgba(79, 110, 247, 0.14);
}

html:not([data-theme="dark"]) .coding-body.code-first .stream-pane .agent-conversation {
  background: transparent;
}

html:not([data-theme="dark"]) .coding-body.code-first .stream-pane .ac-list {
  padding: 18px 18px 20px;
  gap: 14px;
}

html:not([data-theme="dark"]) .coding-body.code-first .stream-pane .ac-avatar.brand {
  background: #4f6ef7 !important;
  box-shadow: 0 5px 14px rgba(79, 110, 247, 0.18);
}

html:not([data-theme="dark"]) .coding-body.code-first .stream-pane .ac-bubble.assistant-naked {
  padding: 10px 12px;
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid rgba(15, 23, 42, 0.07);
  border-radius: 10px;
  color: #1e293b;
  box-shadow: 0 8px 22px rgba(15, 23, 42, 0.035);
}

html:not([data-theme="dark"]) .coding-body.code-first .stream-pane .ac-bubble.user-bubble {
  background: #eaf0ff;
  border: 1px solid rgba(79, 110, 247, 0.16);
  color: #1e293b;
}

html:not([data-theme="dark"]) .coding-body.code-first .chat-input-bar {
  padding: 12px 16px 15px;
  border-top-color: rgba(15, 23, 42, 0.08);
  background: linear-gradient(180deg, rgba(247, 249, 253, 0), #f8fafc 24%);
}

html:not([data-theme="dark"]) .coding-body.code-first .coding-model-select {
  background: #f8fafc;
  border-color: rgba(15, 23, 42, 0.08);
  color: #64748b;
}

html[data-theme="dark"] .coding-page,
html[data-theme="dark"] .coding-body,
html[data-theme="dark"] .main-content,
html[data-theme="dark"] .welcome-pane,
html[data-theme="dark"] .coding-unselected-pane {
  background: #090b10 !important;
  color: rgba(248, 250, 252, 0.94) !important;
}

html[data-theme="dark"] .coding-header,
html[data-theme="dark"] .coding-session-header,
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
html[data-theme="dark"] .workspace-card-meta,
html[data-theme="dark"] .creating-text,
html[data-theme="dark"] .stream-actions-hint {
  color: rgba(203, 213, 225, 0.68) !important;
}

html[data-theme="dark"] .view-toggle,
html[data-theme="dark"] .toggle-bar-back-btn,
html[data-theme="dark"] .header-btn,
html[data-theme="dark"] .qc-shell,
html[data-theme="dark"] .qc-chip,
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
html[data-theme="dark"] .chat-input-wrapper:focus-within {
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
html[data-theme="dark"] .workspace-card-action-primary {
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
html[data-theme="dark"] .workspace-card-action:hover {
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

/* ============ Task 7: 原生文件树 + 代码查看器右栏 ============ */
.ws-pane { display: flex; height: 100%; min-height: 0; min-width: 0; border-left: 1px solid var(--line, rgba(0,0,0,.08)); width: 420px; flex-shrink: 0; }
.ws-pane-tree { flex: none; border-right: 1px solid var(--line, rgba(0,0,0,.08)); }
.ws-pane-viewer { flex: 1; min-width: 0; overflow: hidden; }
/* 树右边界拖宽 handle: 骑在边框上不占布局宽度 */
.tree-resizer {
  flex: none;
  width: 7px;
  margin: 0 -3px 0 -4px;
  cursor: col-resize;
  z-index: 5;
  position: relative;
  touch-action: none;
  user-select: none;
}
.tree-resizer::after {
  content: '';
  position: absolute;
  left: 3px; top: 0; bottom: 0;
  width: 2px;
  background: transparent;
  transition: background 0.15s var(--ease, ease);
}
.tree-resizer:hover::after { background: var(--brand, #6366f1); }

/* 代码为主三栏布局: SessionSidebar | 文件树+大代码区(主角) | 右聊天列(可拖宽) */
.coding-body.code-first .ws-pane {
  order: 1;
  flex: 1 1 auto;
  width: auto;
  border-left: none;
}
.coding-body.code-first .main-content {
  order: 2;
  border-left: 1px solid var(--line, rgba(0,0,0,.08));
  position: relative;
}
.chat-resizer {
  position: absolute;
  left: -6px; top: 0; bottom: 0;
  width: 12px;
  cursor: col-resize;
  z-index: 30;
  touch-action: none;
  user-select: none;
}
/* 常驻一条细分隔线提示可拖,hover 加重 */
.chat-resizer::after {
  content: '';
  position: absolute;
  left: 5px; top: 0; bottom: 0;
  width: 2px;
  background: transparent;
  transition: background 0.15s var(--ease, ease);
}
.chat-resizer:hover::after { background: var(--brand, #6366f1); }
</style>
