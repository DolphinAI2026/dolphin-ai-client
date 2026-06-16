<template>
  <WorkbenchShell>
  <!-- v2 redesign (Session 5): 3-column shell — left rail + center main + right blueprint.
       Existing chat-page-shell is moved INSIDE <main class="chat-main"> unchanged. -->
  <div class="chat-shell">
    <main class="chat-main">
  <div class="chat-page-shell">
  <div class="chat-page">
    <TopBar v-if="!embedMode" title="" show-back :show-home="false" back-to="/apps">
      <template #center>
        <div class="top-bar-center builder-chat-top-center">
          <div class="builder-chat-crumbs">
            <button type="button" @click="router.push('/apps')">应用</button>
            <span>/</span>
            <!-- PR3 (SPEC v2 §2): 应用名 breadcrumb 可点编辑 (改名 / 描述).
                 应用已部署到平台 (有 apaas_app_id) 才显示编辑能力, 否则跟以前一样显示 span. -->
            <el-popover
              v-if="canEditApaasInfo"
              v-model:visible="editAppInfoOpen"
              trigger="click"
              :width="320"
              placement="bottom-start"
              popper-class="edit-app-info-popper"
              @show="prefillEditAppInfo"
            >
              <template #reference>
                <button type="button" class="app-name-clickable" :title="`点击编辑应用信息 — ${builderAppDisplayName || '新建应用'}`">
                  {{ builderAppDisplayName || '新建应用' }}
                  <span aria-hidden="true" class="app-name-edit-hint"><AppIcon name="pencil" :size="12" /></span>
                </button>
              </template>
              <div class="edit-app-info-form">
                <div class="edit-app-info-title">编辑应用信息</div>
                <label class="edit-app-info-label">
                  <span>应用名</span>
                  <el-input v-model="editAppName" placeholder="应用名" size="small" maxlength="64" />
                </label>
                <label class="edit-app-info-label">
                  <span>描述</span>
                  <el-input v-model="editAppDesc" type="textarea" placeholder="可选，填给协作者看" :rows="3" maxlength="200" />
                </label>
                <div v-if="editAppInfoError" class="edit-app-info-error">{{ editAppInfoError }}</div>
                <div class="edit-app-info-actions">
                  <button type="button" class="eai-btn ghost" :disabled="editAppInfoSaving" @click="editAppInfoOpen = false">取消</button>
                  <button type="button" class="eai-btn primary" :disabled="editAppInfoSaving || !editAppInfoDirty" @click="saveAppInfo">
                    {{ editAppInfoSaving ? '保存中…' : '保存' }}
                  </button>
                </div>
              </div>
            </el-popover>
            <span v-else>{{ builderAppDisplayName || '新建应用' }}</span>
            <span>/</span>
            <strong>AI-Builder</strong>
            <!-- 2026-05-26 design-v4 Polish F2: 应用发布状态 chip
                 backend 当前 status 枚举: draft/generating/updating/completed/failed
                 兜底逻辑: apaas_app_id 存在或 status='completed' 视为"已发布". -->
            <span
              v-if="builderCurrentAppId"
              class="app-status-chip"
              :class="appPublishStatus"
              :title="appPublishTooltip"
            >
              <span v-if="appPublishStatus === 'published'">
                已发布
                <span v-if="appPublishDetail.latest_deploy?.version" class="app-status-version">
                  {{ appPublishDetail.latest_deploy.version }}
                </span>
              </span>
              <span v-else-if="appPublishStatus === 'draft_on_published'">
                <span class="app-status-dot" />
                已发布 · 有 {{ appPublishDetail.pending_changes_count }} 个未提交
              </span>
              <span v-else-if="appPublishStatus === 'failed'">
                <span class="app-status-dot" />
                {{ appPublishDetail.partial ? '部分失败' : '生成失败' }}
                <button type="button" class="app-status-retry" @click.stop="retryFailedGenerate">重试</button>
              </span>
              <span v-else-if="appPublishStatus === 'generating'">
                <span class="app-status-dot" />
                生成中…
              </span>
              <span v-else>草稿</span>
            </span>
          </div>
        </div>
      </template>
      <template #actions>
        <!-- "AI 调整" 按钮已删（外部 embed 是默认入口），"部署到预览" 按钮已删
             （让 外部 agent 调 publish_application 工具发布，统一对话 UX）-->
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
      </template>
    </TopBar>
    <div class="content-area">

      <!-- 平台配置 iframe + 原生菜单 sidebar（v-show 保持不销毁） -->
      <!-- 2026-05-26 design-v3: 整改 layout — 顶部 5 tab + 左 sub-nav + 中画布 + 右 AI. -->
      <div v-show="SHOW_PLATFORM_CONFIG && activeView === 'platform'" class="platform-shell platform-shell-v3">
        <!-- sub-tab chip strip: 顶部 tab 下方一行. 2026-05-26: 设计 tab 不显
             chip (改用左侧菜单 list + 右侧 designer 4 sub-tab). 其他 tab 保留.
             Q2 2026-05-27: 数据源 tab 也不显 chip (扁平 panel, 无 sub). -->
        <div
          v-if="existingAppId && topTab !== 'design' && topTab !== 'datasource' && topTab !== 'spec'"
          class="sub-chip-strip"
        >
          <button
            v-for="sub in currentSubTabsForTop"
            :key="sub.code"
            class="sub-chip"
            :class="{ active: currentSectionTab === sub.code }"
            @click="onSubNavSwitch(sub.code)"
          >
            {{ sub.label }}
          </button>
        </div>
        <!-- tab content row -->
        <div class="platform-shell-row" :class="{ 'assistant-expanded': assistantExpanded }">
          <!-- 设计 tab: 左侧 ApaasMenuSidebar 长显 (不绑 sub-tab) -->
          <ApaasMenuSidebar
            v-if="existingAppId && topTab === 'design'"
            ref="apaasMenuSidebarRef"
            :app-id="existingAppId"
            :selected-menu-id="selectedApaasMenuId"
            @menu-selected="onApaasMenuSelected"
            @menus-loaded="onApaasMenusLoaded"
          />
          <!-- 其他 sub-tab: 走通用 SectionContentList. 当 native panel 自带 master
               (DictEditorPanel / RoleManagePanel) 时, 不再显 SectionContentList 防重复. -->
          <SectionContentList
            v-if="existingAppId && shouldShowSectionContent && currentSectionContentKind
                  && !isNativeMasterDetailSubTab"
            :app-id="existingAppId"
            :resource-kind="currentSectionContentKind"
            :apaas-app-id="store.currentApp?.apaas_app_id || ''"
            :env-id="store.currentApp?.platform_env_id || 0"
            @select-item="onSectionContentItemSelect"
            @request-create="onSectionContentCreateRequest"
          />
          <!-- 设计 tab: U3 — SPEC 设计层 (跟"功能" tab 平行).
               改 SPEC 文档 → AI 翻译成 apaas 配置. MVP read-only + P2 接 chat. -->
          <SpecDesignPanel
            v-if="topTab === 'spec' && existingAppId"
            :key="`spec-${designerRefreshKey}`"
            class="platform-iframe-container"
            :app-id="existingAppId"
            :apaas-app-id="store.currentApp?.apaas_app_id || ''"
          />
          <!-- 日志 tab: design-v4 K4 — 4 sub-tab LogsPanel (deploy / operation / ai / error) -->
          <LogsPanel
            v-else-if="topTab === 'log' && existingAppId"
            :app-id="existingAppId"
            class="platform-iframe-container"
          />
          <!-- 2026-05-26 design-v3 重构: native panel 替 iframe -->
          <!-- 2026-05-27 R: CUSTOM 菜单 (自开发 Vue) 走专门 panel: preview=iframe runtime, edit=跳 IDE -->
          <CustomPagePreviewPanel
            v-else-if="topTab === 'design' && existingAppId && selectedApaasMenuId && selectedApaasMenuType === 'CUSTOM'"
            :key="`cpp-${selectedApaasMenuId}-${designerRefreshKey}`"
            class="platform-iframe-container"
            :app-id="existingAppId"
            :menu-id="selectedApaasMenuId"
            :menu-name="selectedApaasMenuName"
          />
          <!-- 设计 tab: 选中 MODEL 菜单后显 designer shell (内 4 sub-tab: 表单/列表/流程/页面) -->
          <div
            v-else-if="topTab === 'design' && existingAppId && selectedApaasMenuId"
            class="platform-iframe-container mdsh"
          >
            <!-- designer 内顶部 4 sub-tab -->
            <div class="mdsh-subnav">
              <div class="mdsh-subnav-info">
                <span class="mdsh-menu-name">{{ designerSub === 'dev' ? '自开发资产' : designerSub === 'health' ? '应用体检' : (selectedApaasMenuName || '选中菜单') }}</span>
              </div>
              <div class="mdsh-subnav-tabs" role="tablist">
                <button
                  v-for="sub in DESIGNER_SUBS"
                  :key="sub.code"
                  class="mdsh-subnav-tab"
                  :class="{ active: designerSub === sub.code }"
                  role="tab"
                  :aria-selected="designerSub === sub.code"
                  @click="designerSub = sub.code"
                >
                  {{ sub.label }}
                </button>
              </div>
              <OpenLowcodeBackendButton
                v-if="existingAppId"
                class="mdsh-subnav-lowcode"
                :app-id="existingAppId"
                menu-type="MODEL"
                :menu-id="selectedApaasMenuId"
                :form-id="selectedApaasMenuFormId"
              />
            </div>
            <!-- designer 内容 -->
            <div class="mdsh-body">
              <FormDesignerPanel
                v-if="designerSub === 'form'"
                :key="`form-${selectedApaasMenuId}`"
                :app-id="existingAppId"
                :menu-id="selectedApaasMenuId"
                :menu-name="selectedApaasMenuName"
                :form-id="selectedApaasMenuFormId"
                :refresh-nonce="designerRefreshKey"
              />
              <ListDesignerPanel
                v-else-if="designerSub === 'list'"
                :key="`list-${selectedApaasMenuId}-${designerRefreshKey}`"
                :app-id="existingAppId"
                :menu-id="selectedApaasMenuId"
                :menu-name="selectedApaasMenuName"
                :form-id="selectedApaasMenuFormId"
              />
              <ProcessDesignerPanel
                v-else-if="designerSub === 'process'"
                :key="`process-${selectedApaasMenuId}-${designerRefreshKey}`"
                :app-id="existingAppId"
                :menu-id="selectedApaasMenuId"
                :form-id="selectedApaasMenuFormId"
                :hide-lowcode-btn="true"
                :assistant-open="assistantOpen"
              />
              <BusinessEventPanel
                v-else-if="designerSub === 'event'"
                :key="`event-${selectedApaasMenuId}-${designerRefreshKey}`"
                :app-id="existingAppId"
                :menu-name="selectedApaasMenuName"
              />
              <DataSchemaEditor
                v-else-if="designerSub === 'data'"
                :key="`data-${selectedApaasMenuId}`"
                :app-id="existingAppId"
                :menu-id="selectedApaasMenuId"
                :menu-name="selectedApaasMenuName"
                :form-id="selectedApaasMenuFormId"
                :refresh-nonce="designerRefreshKey"
              />
              <FormPermPanel
                v-else-if="designerSub === 'perm' && selectedApaasMenuFormId"
                :key="`perm-${selectedApaasMenuId}-${designerRefreshKey}`"
                :app-id="existingAppId"
                :form-id="selectedApaasMenuFormId"
                :menu-name="selectedApaasMenuName"
              />
              <AppDevWorkspacePanel
                v-else-if="designerSub === 'dev'"
                :key="`dev-${existingAppId}-${designerRefreshKey}`"
                :app-id="existingAppId"
              />
              <AppHealthPanel
                v-else-if="designerSub === 'health'"
                :key="`health-${existingAppId}-${designerRefreshKey}`"
                :app-id="existingAppId"
              />
              <!-- 2026-05-29: 删「页面设置」sub-tab — 纯占位(⚙️ placeholder "P1 接入"),
                   点了无功能。改设置走配置助手对话。同步从 DESIGNER_SUBS 移除该 tab。 -->
            </div>
          </div>
          <!-- 设计 tab + 未选菜单: 空态提示 -->
          <div
            v-else-if="topTab === 'design' && existingAppId && !selectedApaasMenuId"
            class="platform-iframe-container mdsh-empty"
          >
            <div class="mdsh-empty-icon"><AppIcon name="point-left" :size="32" /></div>
            <h3>选择左侧菜单开始设计</h3>
            <p>从左侧应用菜单列表点击一个菜单, 这里显示该菜单的<strong>表单 / 列表 / 流程 / 页面</strong>设计.</p>
          </div>
          <!-- 流程 tab + 流程 sub: ProcessDesignerPanel (P0 mock 4 节点 demo, x6 driven) -->
          <ProcessDesignerPanel
            v-else-if="topTab === 'logic' && currentSectionTab === 'processes' && existingAppId"
            :key="`process-fb-${designerRefreshKey}`"
            class="platform-iframe-container"
            :app-id="existingAppId"
            :menu-id="selectedApaasMenuId || undefined"
            :form-id="selectedApaasMenuFormId"
            :assistant-open="assistantOpen"
          />
          <!-- 数据 tab + 数据模型 sub: 选中模型显字段表格 -->
          <DataModelDetailPanel
            v-else-if="topTab === 'data' && currentSectionTab === 'models' && existingAppId && selectedSectionItemId"
            :key="`dmd-${selectedSectionItemId}`"
            class="platform-iframe-container"
            :app-id="existingAppId"
            :model-id="selectedSectionItemId"
            :refresh-nonce="designerRefreshKey"
            @back="onNativePanelBack"
          />
          <!-- 数据 tab + 字典 sub: master-detail -->
          <DictEditorPanel
            v-else-if="topTab === 'data' && currentSectionTab === 'dicts' && existingAppId"
            :key="`dict-${designerRefreshKey}`"
            class="platform-iframe-container"
            :app-id="existingAppId"
            :apaas-app-id="store.currentApp?.apaas_app_id || ''"
            :env-id="store.currentApp?.platform_env_id || 0"
          />
          <!-- 权限 tab + 角色 sub: master-detail -->
          <RoleManagePanel
            v-else-if="topTab === 'perm' && currentSectionTab === 'roles' && existingAppId"
            :key="`role-${designerRefreshKey}`"
            class="platform-iframe-container"
            :app-id="existingAppId"
          />
          <!-- 数据源 tab (Q2 2026-05-27): 应用关联的数据源 (DB connection 维度, 只读) -->
          <AppDatasourcePanel
            v-else-if="topTab === 'datasource' && existingAppId"
            :key="`appds-${designerRefreshKey}`"
            class="platform-iframe-container"
            :app-id="existingAppId"
          />
          <!-- 非原生 tab（业务事件/字段权限/菜单可见性等）: 去内嵌, 占位 + 深链低代码后台 -->
          <div v-else class="platform-iframe-container lowcode-deeplink-placeholder">
            <div class="lcd-ph-icon" aria-hidden="true"><AppIcon name="wrench" :size="32" /></div>
            <p class="lcd-ph-hint">这块配置在低代码后台编辑。</p>
            <OpenLowcodeBackendButton v-if="existingAppId" :app-id="existingAppId" />
          </div>
        <!-- 2026-05-29: 配置助手嵌入式右栏 — 对齐「设计」tab(SpecDesignPanel 内嵌 chat)的布局,
             并排不浮盖中间内容。设计 tab(topTab==='spec')自带 SPEC chat, 这里不重复显。
             收起态走右下 FAB(见 chat-shell 下), 展开态在此并排; 宽度由 panel 内 usePanelResize 控制。 -->
        <AppAssistantPanel
          v-if="!embedMode && isPostDeploy && resolvedAppId && topTab !== 'spec' && assistantOpen"
          class="ca-embedded"
          v-model:expanded="assistantExpanded"
          :application-id="resolvedAppId"
          :app-name="builderAppDisplayName || ''"
          :current-section="currentSection"
          :current-section-tab="currentSectionTab"
          :designer-sub="topTab === 'design' && selectedApaasMenuId ? designerSub : null"
          :selected-menu-name="selectedApaasMenuName"
          :selected-menu-id="selectedApaasMenuId"
          @close="toggleAssistant"
          @refresh-iframe="refreshPlatformAndSidebar"
          @upload-doc="triggerDocVersionUpload"
        />
        </div><!-- /.platform-shell-row -->
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
      <!-- 2026-05-29: 退休老 builder-md-viewer (平铺 SPEC dump)。读 SPEC 统一走「设计」tab
           (SpecDesignPanel — 结构化分章 + 用对话改 + 确认并生成 + 版本/对比/导出)。
           草稿应用由 restoreActiveViewForApp 路由到 platform + 设计 tab; 已部署走平台 iframe。
           原 md-viewer 的"下载/打开应用/部署历史"已分别在 设计 tab 导出 / 顶部"查看应用" / 顶部"历史"。-->

      <!-- 2026-05-29: 退休 md-viewer 后, activeView='builder' 这段窗口(应用加载完 →
           restoreActiveViewForApp 翻到 platform 之前)中间会空白。放加载占位别让用户盯白屏;
           应用 load 完翻到 platform 后, builder-content 整体 v-show 隐藏, 此块自然消失。 -->
      <div
        v-if="existingAppId && !isDeploying"
        class="builder-deploy-hero"
      >
        <div class="bdh-card">
          <div class="bdh-loader" aria-hidden="true">
            <span class="bdh-loader-ring"></span>
          </div>
          <div class="bdh-copy">
            <div class="bdh-kicker">AI-Builder</div>
            <div class="bdh-title">正在打开应用</div>
            <div class="bdh-sub">同步菜单、表单和权限配置，完成后自动进入功能页。</div>
          </div>
          <div class="bdh-progress" aria-hidden="true">
            <span class="is-done"></span>
            <span class="is-active"></span>
            <span></span>
          </div>
        </div>
      </div>

      <!-- deploy 进行中的中央等待占位 (deploy 完成后的 🎉 hero 已于 2026-05-28 删) -->
      <div
        v-else-if="isDeploying"
        class="builder-deploy-hero"
      >
        <div class="bdh-card">
          <div class="bdh-loader" aria-hidden="true">
            <span class="bdh-loader-ring"></span>
          </div>
          <div class="bdh-copy">
            <div class="bdh-kicker">生成中</div>
            <div class="bdh-title">正在创建应用</div>
            <div class="bdh-sub">AI 正在生成数据模型、表单和权限配置，右侧会持续更新进度。</div>
          </div>
          <div class="bdh-progress" aria-hidden="true">
            <span class="is-active"></span>
            <span></span>
            <span></span>
          </div>
        </div>
      </div>

      <DeployProgressPanel
        :visible="!useSpecMode && showDeploySidebar"
        :deploy-open="deployOpen"
        :is-update-review-mode="isUpdateReviewMode"
        :is-update-execution-mode="isUpdateExecutionMode"
        :update-execution-all-done="updateExecutionAllDone"
        :current-update-execution-label="currentUpdateExecutionLabel"
        :current-deploy-step="currentDeployStep"
        :deploy-all-done="deployAllDone"
        :deploy-running-all="deployRunningAll"
        :deploy-executing="deployExecuting"
        :deploy-last-error="deployLastError"
        :active-conflict="activeConflict"
        :can-retry-all="canRetryAllDeploy"
        :update-execution-percent="updateExecutionPercent"
        :update-execution-done-count="updateExecutionDoneCount"
        :update-execution-total-count="updateExecutionTotalCount"
        :deploy-percent="deployPercent"
        :deploy-done-count="deployDoneCount"
        :deploy-steps="deploySteps"
        :update-execution-groups="updateExecutionGroups"
        :update-review-groups="updateReviewGroups"
        :deploy-groups="deployGroups"
        :execution-logs="executionLogs"
        :latest-execution-log="latestExecutionLog"
        :log-expanded="deployLogExpanded"
        :diff-summary="store.changePlan?.diffSummary || ''"
        @close="deployOpen = false"
        @retry-all="deployRetryAll"
        @redo="deployRedo"
        @exec="deployExec"
        @open-platform="openInPlatform"
        @update:log-expanded="deployLogExpanded = $event"
      />

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
    <DocVersionDialogs
      v-model:preview-visible="docVersionPreviewVisible"
      v-model:fullscreen-visible="docFullscreenVisible"
      v-model:diff-visible="docVersionDiffVisible"
      :preview-title="docVersionPreviewTitle"
      :preview-structured-result="docVersionPreviewStructuredResult"
      :preview-content="docVersionPreviewContent"
      :fullscreen-title="docFullscreenTitle"
      :fullscreen-structured-result="docFullscreenStructuredResult"
      :fullscreen-content="docFullscreenContent"
      :diff-stats="docDiffStats"
      :diff-change-summary="diffChangeSummary"
      :diff-left-title="docVersionDiffLeftTitle"
      :diff-right-title="docVersionDiffRightTitle"
      :diff-left-structured-result="docVersionDiffLeftStructuredResult"
      :diff-right-structured-result="docVersionDiffRightStructuredResult"
      :structured-doc-diff-meta="structuredDocDiffMeta"
      :doc-diff-result="docDiffResult"
    />
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
              <td class="log-result"><template v-if="log.success"><AppIcon name="check" :size="13" /></template><template v-else>{{ log.error_message?.slice(0, 40) }}</template></td>
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

    <!-- 部署历史 Drawer -->
    <DeployHistoryDrawer
      v-if="store.currentApp?.id"
      :application-id="store.currentApp.id"
      :open="deployHistoryOpen"
      :app-name="builderAppDisplayName"
      @update:open="(v) => { deployHistoryOpen = v }"
      @rolled-back="handleDeployHistoryRollback"
    />
  </div><!-- /chat-page -->
  </div><!-- /chat-page-shell -->
    </main><!-- /chat-main -->

    <!-- 2026-05-19 image #29: 部署执行中时右侧改成 progress 面板（用户："执行过程放右侧"） -->
    <aside v-if="!embedMode && isDeploying" class="deploy-progress-side">
      <div class="dps-head">
        <div class="dps-title"><AppIcon name="rocket" :size="15" /> 部署进行中</div>
        <div class="dps-subtitle">{{ store.preview.appName || builderAppDisplayName }}</div>
      </div>
      <div class="dps-steps">
        <div
          v-for="step in deploySteps"
          :key="step.key"
          class="dps-step"
          :class="['status-' + step.status, { current: step.key === deployExecuting }]"
        >
          <span class="dps-step-icon">
            <span v-if="step.status === 'completed'"><AppIcon name="check" :size="12" /></span>
            <span v-else-if="step.status === 'error'"><AppIcon name="x" :size="12" /></span>
            <span v-else-if="step.status === 'running' || step.key === deployExecuting" class="dps-spin">○</span>
            <span v-else>·</span>
          </span>
          <span class="dps-step-label">{{ step.label }}</span>
          <span v-if="step.error" class="dps-step-error" :title="step.error">!</span>
        </div>
        <div v-if="!deploySteps.length" class="dps-empty">正在初始化部署任务…</div>
      </div>
    </aside>
    <!-- 2026-05-19 post-deploy 形态: 配置助手, 聊增量调整 -->
    <!-- 2026-05-25: 改浮动模式 — 默认收起 FAB, 点开 overlay 在 iframe 上, 不再挤 iframe 宽度 -->
    <!-- U6 (2026-05-27): 设计 tab 隐藏浮窗 — SpecDesignPanel 自带内嵌 SPEC chat,
         避免双 chat 心智混乱 (浮窗 = apaas 现场改 / 内嵌 = SPEC 草稿改). -->
    <!-- 收起态 FAB: 展开面板已改为嵌入式右栏(在 .platform-shell-row 内, 对齐「设计」tab)。
         FAB 仅在 platform 视图显 — 嵌入式面板挂在 platform-shell 里, builder 视图点开会落在 v-show 隐藏容器。 -->
    <template v-if="!embedMode && isPostDeploy && resolvedAppId && topTab !== 'spec' && activeView === 'platform'">
      <button
        v-if="!assistantOpen"
        class="ca-fab"
        title="打开配置助手"
        @click="toggleAssistant"
      >
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
        <span class="ca-fab-text">AI 助手</span>
      </button>
    </template>
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

  <!-- 外部需求分析助手 deeplink (?from=requirements) 进来后的应用目标选择 -->
  <ChooseAppTargetDialog
    v-model="reqDialogVisible"
    :filename="reqDialogFilename"
    :suggested-name="reqDialogSuggestedName"
    :suggested-code="reqDialogSuggestedCode"
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
import { ref, reactive, computed, nextTick, onMounted, onBeforeUnmount, watch, defineAsyncComponent } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { usePreviewStore } from '@/stores/preview'
import { useUserStore } from '@/stores/user'
import { applicationApi } from '@/api/application'
// codingApi / consumeSseResponse no longer needed — coding tab uses iframe
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
import { getPastedImageFiles } from '@/utils/pasteImages'
import {
  buildAppCode,
  pickAppCode,
  pickAppName,
  extractAppCodeFromText,
  extractAppNameFromText,
} from '@/utils/app'
import ApaasMenuSidebar from '@/components/ApaasMenuSidebar.vue'
import AppIcon from '@/components/common/AppIcon.vue'
import SectionContentList from '@/components/v2/SectionContentList.vue'
import AppConfigSubNav from '@/components/v3/AppConfigSubNav.vue'
import FormDesignerPanel from '@/components/v3/FormDesignerPanel.vue'
import ListDesignerPanel from '@/components/v3/ListDesignerPanel.vue'
import ProcessDesignerPanel from '@/components/v3/ProcessDesignerPanel.vue'
import DataSchemaEditor from '@/components/v3/DataSchemaEditor.vue'
import FormPermPanel from '@/components/v3/FormPermPanel.vue'
import BusinessEventPanel from '@/components/v3/BusinessEventPanel.vue'
import OpenLowcodeBackendButton from '@/components/v3/OpenLowcodeBackendButton.vue'
import DataModelDetailPanel from '@/components/v3/DataModelDetailPanel.vue'
import DictEditorPanel from '@/components/v3/DictEditorPanel.vue'
import RoleManagePanel from '@/components/v3/RoleManagePanel.vue'
import LogsPanel from '@/components/v3/LogsPanel.vue'
import AppHealthPanel from '@/views/coding/AppHealthPanel.vue'
import AppDatasourcePanel from '@/components/v3/AppDatasourcePanel.vue'
import CustomPagePreviewPanel from '@/components/v3/CustomPagePreviewPanel.vue'
import AppDevWorkspacePanel from '@/components/v3/AppDevWorkspacePanel.vue'
// U3 (2026-05-27): SPEC 设计层 panel — 跟"功能" tab 平行的 SPEC 编辑层 (MVP read-only).
// SPEC tab 休眠中(SPEC_TAB_ENABLED=false)，异步冷藏使其退出主 bundle；恢复时打开 flag 即可。
// SpecChatPanel/SpecApplyModal 仅被 SpecDesignPanel 引用，会自动跟进同一异步 chunk。
const SpecDesignPanel = defineAsyncComponent(() => import('@/components/v3/SpecDesignPanel.vue'))
import type { ConversationCreate, Message } from '@/types'
import TopBar from '@/components/TopBar.vue'
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import AppChatPanel from '@/components/AppChatPanel.vue'
import ChooseAppTargetDialog from '@/components/ChooseAppTargetDialog.vue'
import SessionSidebar, { type SessionItem as SidebarSessionItem } from '@/components/common/SessionSidebar.vue'
import DeployProgressPanel from '@/components/chat/DeployProgressPanel.vue'
import DocVersionDialogs from '@/components/chat/DocVersionDialogs.vue'
import DeployHistoryDrawer from '@/components/v2/DeployHistoryDrawer.vue'
import { llmConfigApi, type BuilderModelOption } from '@/api/llmConfig'
import { convertConfig } from '@/api/conversation'
import { buildStructuredDocFromPreviewConfig } from '@/utils/structuredDoc'
import { computeStructuredDocDiff } from '@/utils/structuredDocDiff'
import {
  APP_CONFIG_TOP_TABS_ENABLED,
  SECTION_DEFAULT_TAB,
  SECTION_STORAGE_KEY,
  SECTION_TAB_STORAGE_KEY,
  SECTION_TO_TOP_TAB,
  SPEC_TAB_ENABLED,
  TOP_TAB_SUBS,
  DESIGNER_SUBS,
  getInitialSection,
  getInitialSectionTab,
  normalizeTopTab,
  type DesignerSubCode,
} from '@/composables/useAppConfigTabs'
import { useSpecStore } from '@/stores/spec'
import PhaseBar from '@/components/spec/PhaseBar.vue'
import SpecCanvas from '@/components/spec/SpecCanvas.vue'
import SpecInspector from '@/components/spec/SpecInspector.vue'
// v2 redesign (Session 5): 3-column shell — left conversation rail + right SPEC blueprint.
// Existing center content unchanged; new components are pure presentation, no logic.
import AppAssistantPanel from '@/components/v2/AppAssistantPanel.vue'
import DeployConfirmModal from '@/components/v2/DeployConfirmModal.vue'

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
    // 侧栏只用 id/name/code/status，不需要每个应用的完整 config_preview（省 ~1.5MB）。
    // include_remote:false 也避免 N 次阻塞性远程 apaas 调用。
    const apps = await applicationApi.list({ include_remote: false, include_config: false }) as any[]
    sidebarApps.value = Array.isArray(apps) ? apps : []
    appCount.value = sidebarApps.value.length
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
  // 2026-05-29: spec(设计) tab 暂隐藏 — 已生成应用进来落「功能」(design) tab 而非 spec。
  if (isGenerated) return { app_id: appId, tab: SPEC_TAB_ENABLED ? 'spec' : 'design', workspace: 'update' }
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

// 部署历史 Drawer
const deployHistoryOpen = ref(false)
function openDeployHistoryDrawer() {
  if (store.currentApp?.id) {
    deployHistoryOpen.value = true
  }
}
function handleDeployHistoryRollback(_recordId: number) {
  // 回滚后把 currentApp 标记为 updating（提示用户去重新部署）
  if (store.currentApp) {
    store.currentApp = { ...store.currentApp, status: 'updating' }
  }
}

// 初始加载完成前为 false：用于抑制加载期里"部署步骤全完成"误触发重量级远程 meta 刷新
// （那条 list(include_remote:true) 是加载慢/卡 pending 的根因之一）。
const appInitialLoadDone = ref(false)
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

// 把"当前编辑的应用"上报给后端，让 外部 agent 调 MCP 工具时不传 app_id 也能拿到
const currentAppSynced = ref(false)
// 5 秒超时兜底：sync 失败也允许 iframe 加载（init-app-context endpoint 内部
// 会再写一次 state，所以即使前端 sync 失败 外部 agent 也能拿对当前应用）
const syncTimeoutFallback = ref(false)
async function syncCurrentAppToBackend() {
  // ★ 优先用 URL query 里的 app_id（最权威），不要 fallback 到 builderCurrentAppId
  // computed —— 它会回退到 store.currentApp，可能是切页前的旧值，导致 agent
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
  // 5 秒后无论 sync 成败都允许内置组件渲染
  setTimeout(() => { syncTimeoutFallback.value = true }, 5000)
})

// 外部 agent 改完应用后右侧不联动 — 轮询应用 updated_at 变了就重新加载 SPEC
// 注意：不用 watch(builderCurrentAppId, ...) — 直接 ref source 建立 watcher 会
// 在 setup 同步阶段触发 computed 求值，而 builderCurrentAppId 引用的 existingAppId
// 在文件后面才声明，会触发 TDZ。改成 polling 内部对比 _lastAppId 检测切换。
let _lastAppId: number | null = null
let _lastAppUpdatedAt = ''
let _appPollTimer: any = null
let _appPollVisHandler: (() => void) | null = null

// 用主加载已经取到的 app 对象建立轮询基线，避免为了一个 updated_at 再单独 GET 一次
// 完整应用详情（大应用 config_preview ~948kB，原 primeAppPollingBaseline 是纯重复请求）。
// 基线 = 加载时刻的 updated_at，仍是"最早可能"的时间点，先于第一次 5s tick，
// 保持原来"避免首次 tick 把已改过的 updated_at 当基线"的语义。
function seedAppPollingBaseline(app: any) {
  const aid = Number(app?.id)
  if (!Number.isFinite(aid) || aid <= 0) return
  _lastAppId = aid
  _lastAppUpdatedAt = String(app?.updated_at || app?.last_updated_at || '')
}
async function pollAppForChanges() {
  let appId: number | null = null
  try { appId = builderCurrentAppId.value } catch { return }
  if (!appId) return
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
  // 用户从 外部 admin / 别的 tab 切回来的瞬间最可能想立刻看到右侧最新状态。
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
// currentRemoteStatus 来自得帆云远程状态（需重量级 list(include_remote:true)，仅在
// 发布/部署等用户动作后刷新）。加载态下不再拉远程列表，改用已加载的本地 publish-status
// 兜底判断上线/发布中 —— 远程真值（'ENABLE'）可用时仍优先。
const isAppOnline = computed(() =>
  currentRemoteStatus.value === 'ENABLE' ||
  currentRemoteStatus.value === '已上线' ||
  appPublishDetail.value.status === 'published' ||
  appPublishDetail.value.status === 'draft_on_published'
)
const isAppPublishing = computed(() => {
  const status = String(currentRemoteStatus.value || '').toLowerCase()
  if (status.includes('publish') || status.includes('上线中') || status.includes('publishing')) return true
  return appPublishDetail.value.status === 'generating'
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
// 内置 agent" 决策砍掉左侧 AI 助手对话区：用户只需点
// 右上角"开始构建"按钮即可。右侧 SPEC 区因 .single-pane class 自动 full-width。
// 老 computed 逻辑保留作 ref，下次彻底砍 chat-side block 时一并清。
// 2026-05-18 撤销 cf75367 "恢复 chat panel" — 用户拍板 md 预览区不要 AI 助手。
const showBuilderChatSide = computed(() => false)
const showDeployProgressInline = computed(() => deploySteps.value.length > 0 || deployOpen.value || isPlatformDeployed.value)
// 用户已决定废弃 "已部署应用版本化视图"：右侧永远显示文档（单文档或 diff），
// 不再区分 showDeployedVersionedView 模式。保留此处常量以便语义搜索，
// 但所有分支按 false 处理（= 渲染文档视图）。
const showDeploySidebar = computed(() => {
  // 2026-05-21 删左侧"创建过程" sidebar（image: 左右两侧重复显示步骤列表）。
  // 新建应用的 deploy 进度统一去右侧 .deploy-progress-side timeline；
  // 完成态去中间 hero CTA。左侧 sidebar 只保留"更新应用"流程
  // （isUpdateReviewMode / isUpdateExecutionMode）— 它没有右侧对应面板。
  return isUpdateReviewMode.value || isUpdateExecutionMode.value
})
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
  return options.slice(0, 6).map((option: { name: string; code: string }) => option.name).join('、') + (options.length > 6 ? ` 等 ${options.length} 项` : '')
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
  { title: '角色', icon: 'users', items: updateRoleDiffItems.value },
  { title: '数据字典', icon: 'book-open', items: updateDictDiffItems.value },
  { title: '数据模型', icon: 'database', items: updateModelDiffItems.value },
  { title: '表单配置', icon: 'clipboard', items: updateFormDiffItems.value },
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
const STANDARD_DESIGN_DOC_RE = /\.(md|markdown)$/i

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
            <span class="chat-inline-upload-file-icon"><AppIcon name="file" :size="14" /></span>
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

const queueMaterialFileForChat = (file: File, options: { autoSend?: boolean; message?: string } = {}) => {
  const kind = file.type.startsWith('image/') ? 'image' : 'file'
  const attached = attachPendingAttachmentFile(file, kind)
  if (!attached) return false

  const fallbackMessage = options.message || (
    existingAppId.value
      ? '请基于这个附件理解我的修改需求，整理成新版设计文档并生成变更建议。'
      : '请基于这个附件理解需求，先整理成标准设计文档，再继续生成应用。'
  )
  if (!inputText.value.trim()) {
    inputText.value = fallbackMessage
  }
  if (options.autoSend) {
    nextTick(() => {
      if (!sendingMessage.value) sendMessage()
    })
  }
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
    if (STANDARD_DESIGN_DOC_RE.test(lowerName)) {
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
  const pastedImages = getPastedImageFiles(event, 'builder-pasted-image')
  const pastedFile = pastedImages[0]
  if (!pastedFile) return
  event.preventDefault()
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
    // 只数应用个数 — 走精简列表（无 config_preview、无远程 apaas 调用），别拉 1.5MB。
    const apps = await applicationApi.list({ include_remote: false, include_config: false }) as any[]
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

// ── Builder → 二次开发 handoff bridge ──
// 把当前应用的结构（模型/表单/流程/角色）打包成 message，结构化交接到 AIChatPage 在应用上下文里
// 做二次开发，不再跳独立 /coding。AIChatPage.vue onMounted 读 sessionStorage('ai_builder_pending_app_dev')
// （route.query.app_dev=1 时）建会话并把 message 作为首条发出。
// ── 配置助手浮动 (2026-05-25) ──
// 默认收起为 FAB, 不再挤压 iframe. localStorage 持久化用户偏好.
const ASSISTANT_OPEN_KEY = 'apaas-config-assistant-open-v1'
const assistantOpen = ref(localStorage.getItem(ASSISTANT_OPEN_KEY) === 'true')
const assistantExpanded = ref(false)
function toggleAssistant() {
  assistantOpen.value = !assistantOpen.value
  if (!assistantOpen.value) assistantExpanded.value = false
  try { localStorage.setItem(ASSISTANT_OPEN_KEY, String(assistantOpen.value)) } catch { /* private mode */ }
}

// ── 平台配置 iframe ──
// 2026-05-27 P2: design-v4 panel 刷新 key — ConfigAssistant 完成调整后 bump 这个,
// 让 FormDesignerPanel / ListDesignerPanel / ProcessDesignerPanel / DataSchemaEditor /
// RoleManagePanel 重新挂载 + 重新拉数据 (替代老 iframe.reload). 5 panel 都 bind
// :key="`{prefix}-${designerRefreshKey}`" 触发 remount.
const designerRefreshKey = ref(0)

// PR2b (SPEC v2 §1.1) — SectionNav 状态
// 5 section: data/ui/logic/permission/extension, 默认 ui (跟以前 ApaasMenuSidebar 行为对齐)
// 2026-05-31: 顶部「功能 / 数据源 / 权限 / 日志」入口移除, 进入应用直接展示功能页。
const _initSection = getInitialSection()
const _initSectionTab = getInitialSectionTab(_initSection)
const currentSection = ref<string>(_initSection)
const currentSectionTab = ref<string>(_initSectionTab)

// 2026-05-26 design-v3: 顶部 5 tab (设计/数据/流程/权限/日志). 跟旧 currentSection 双向同步.
// 旧 SECTION (data/ui/logic/permission/extension) 映射到新 TopTab:
//   data → data, ui → design, logic → logic, permission → perm, extension → 日志 (extension 退场)
// 2026-05-29: 暂时隐藏「设计」(spec) tab — 用户反馈那一大坨 read-only SPEC 文档平铺太重,
// 进应用直接用「功能」tab + 配置助手对话调整即可。改开关为 true 即整体恢复(组件/逻辑都保留,
// 仅不显示 + 把落到 spec 的入口归一到 design)。⚠️ 别删 SpecDesignPanel 本体(low-code 核心线)。
const topTab = ref<string>(normalizeTopTab(SECTION_TO_TOP_TAB[_initSection] || 'design'))
function onSubNavSwitch(sub: string) {
  currentSectionTab.value = sub
  try { localStorage.setItem(SECTION_TAB_STORAGE_KEY, sub) } catch {}
}
// sub-tab chips for current top tab (5 个 top tab 各有自己的 sub-tab 集合)
const currentSubTabsForTop = computed(() => TOP_TAB_SUBS[topTab.value] || [])

// 2026-05-26 设计 tab 内部 designer sub-nav (跟 apaas form designer 顶部 4 tab 对齐).
// 用户在左侧 ApaasMenuSidebar 选中菜单后, designer 主区域顶部 4 tab 切对应 panel.
const designerSub = ref<DesignerSubCode>('form')

// P1-N6: 这些 sub-tab 走 native master-detail panel — 不需要再显 SectionContentList.
const isNativeMasterDetailSubTab = computed(() => {
  if (topTab.value === 'data' && currentSectionTab.value === 'dicts') return true
  if (topTab.value === 'perm' && currentSectionTab.value === 'roles') return true
  return false
})
function onSwitchSection(section: string, tab?: string) {
  // SPEC v2 Issue #6: 切 section 前提示用户保存(dirty editor) — 通过 postMessage 探 iframe.
  // P0 简化: 直接切, 后续 PR2c 在 ConfigAssistant 接入 dirty probe.
  const sectionChanged = currentSection.value !== section
  currentSection.value = section
  if (tab) currentSectionTab.value = tab
  else if (sectionChanged) {
    // 切到新 section 时 sub-tab 重置到该 section 默认
    currentSectionTab.value = SECTION_DEFAULT_TAB[section] || ''
  }
  try {
    localStorage.setItem(SECTION_STORAGE_KEY, section)
    localStorage.setItem(SECTION_TAB_STORAGE_KEY, currentSectionTab.value)
  } catch { /* private mode */ }
}

// PR2b-followup (2026-05-26): SectionNav sub-tab → SectionContentList resource kind mapping.
// data/ui/logic/permission 大部分 sub-tab 都接 SectionContentList; 例外:
//   - ui:menus 走老 ApaasMenuSidebar (功能已成熟, 保留)
//   - extension:* 走 ExtensionSectionPanel (PR6 已实现)
//   - permission:field_perm / menu_vis 暂无后端 endpoint, fallback null (落 iframe)
const SECTION_TAB_TO_KIND: Record<string, 'models' | 'dicts' | 'forms' | 'lists' | 'processes' | 'business-events' | 'roles' | 'field-permissions' | 'menu-visibility'> = {
  'data:models': 'models',
  'data:dicts': 'dicts',
  'ui:forms': 'forms',
  'ui:lists': 'lists',
  'logic:processes': 'processes',
  'logic:events': 'business-events',
  'permission:roles': 'roles',
  'permission:field_perm': 'field-permissions',
  'permission:menu_vis': 'menu-visibility',
}
const currentSectionContentKind = computed(() => {
  const key = `${currentSection.value}:${currentSectionTab.value}`
  return SECTION_TAB_TO_KIND[key] || null
})
const shouldShowSectionContent = computed(() => {
  if (currentSection.value === 'extension') return false  // 走 ExtensionSectionPanel
  if (currentSection.value === 'ui' && currentSectionTab.value === 'menus') return false  // 走 ApaasMenuSidebar
  return currentSectionContentKind.value !== null
})
// 2026-05-26 design-v3 P1-N6: 选中资源 item 时 native panel 用的 state.
const selectedSectionItemId = ref<string>('')
const selectedApaasMenuName = ref<string>('')
const selectedApaasMenuFormId = ref<string>('')
// 2026-05-27 R: 选中菜单的 menu_type — CUSTOM/MODEL/PROCESS 等. CUSTOM 走 CustomPagePreviewPanel.
const selectedApaasMenuType = ref<string>('')
function onNativePanelBack() {
  selectedSectionItemId.value = ''
}

function onSectionContentItemSelect(item: any) {
  // 记下 native panel 用的 item id + 元信息
  selectedSectionItemId.value = String(item?.id || item?.menu_id || '')
  selectedApaasMenuName.value = String(item?.name || '')
  selectedApaasMenuFormId.value = String(item?.form_id || item?.extra?.form_id || '')

  // 凡是 menu-based 的资源 (forms / lists / processes / field-permissions / menu-visibility)
  // 都走 onApaasMenuSelected 跳到该菜单的编辑页. item 有 menu_id + form_id (来自 extra).
  // P1-N6: 设计 tab + forms/lists 时, 不切 iframe — FormDesignerPanel 直接显字段.
  const isMenuBased = (
    (currentSection.value === 'ui' && (currentSectionTab.value === 'forms' || currentSectionTab.value === 'lists'))
    || (currentSection.value === 'logic' && currentSectionTab.value === 'processes')
    || (currentSection.value === 'permission' && (currentSectionTab.value === 'field_perm' || currentSectionTab.value === 'menu_vis'))
  )
  if (isMenuBased) {
    const menuId = item?.menu_id || item?.id || item?.extra?.menu_id
    if (menuId) {
      // 设计 tab + forms/lists: FormDesignerPanel 自己接 menu_id, 不需要切 iframe.
      // 逻辑 tab + processes / 权限 tab + field_perm/menu_vis: 还走 iframe (P2 改 native).
      if (topTab.value !== 'design') {
        onApaasMenuSelected({
          menu_id: menuId,
          form_id: item?.form_id || item?.extra?.form_id,
          menu_type: item?.menu_type || item?.extra?.menu_type,
          menu_display: item?.extra?.menu_display,
        } as any)
      } else {
        // design tab: 记下 selectedApaasMenuId 让 FormDesignerPanel 拿到
        selectedApaasMenuId.value = String(menuId)
      }
      return
    }
  }
  // models / dicts / business-events / roles: 平台无直接 deeplink.
  // P1-N6 现在 data:models 走 DataModelDetailPanel — 由 selectedSectionItemId 触发.
  console.log('[SectionContentList] selected item:', item)
}
function onSectionContentCreateRequest() {
  // P0: 提示用户用 AI 助手创建. P1 接对应 modal.
  console.log('[SectionContentList] create requested for', currentSectionContentKind.value)
}

// PR2b-followup (2026-05-26 P0-5): SectionNav section 切换驱动 iframe 跳到对应 apaas tab.
// apaas 平台 app-store/edit-app 的 currentStepIndex 控制顶部 tab:
//   0 = 应用信息 | 1 = 访问权限 | 2 = 菜单功能 | 3 = 数据可视化 | 4 = 高级设置
// 我们的 SectionNav 5 section → step_index 映射:
//   data       → 0 (应用信息) — 模型/字典管理多在该 tab 或独立页, P0 先落总览
//   ui         → 2 (菜单功能) — 跟点菜单走 menu_id 路径前的总览一致
//   logic      → 2 (菜单功能, 流程挂菜单上)
//   permission → 1 (访问权限) — 角色管理在这
//   extension  → 不跳 iframe (走 ExtensionSectionPanel)
// 2026-05-26: sidebar 引用 — AI 完成调整后联动 reload, 让新建菜单立刻显
const apaasMenuSidebarRef = ref<{ reload: () => Promise<void> } | null>(null)
function refreshPlatformAndSidebar() {
  // bump design-v4 panel key — 让 5 个 Vue 原生 panel re-mount + re-fetch
  designerRefreshKey.value += 1
  // 略延 300ms 给平台 API 落库, 然后 reload 菜单树
  setTimeout(() => {
    try { apaasMenuSidebarRef.value?.reload?.() } catch { /* sidebar 还没 mount 时忽略 */ }
  }, 300)
}

// 2026-05-25 B-4: 原生菜单 sidebar 选中态 + 切 iframe handler
const selectedApaasMenuId = ref<string | null>(null)

// 2026-05-25 修不伦不类: sidebar 加载完 menus 后, 若还没选过菜单, 自动跳第一个 form 菜单.
// 跳过应用总览页 (app-store/edit-app) — 那个页面带平台一整套 chrome (得帆云 logo / nav /
// 应用 tab 栏) 跟我们外层 ChatPage 重叠. 直接进 fn-config 干净设计器视觉一致.
function onApaasMenusLoaded(_menus: any[], firstFormMenu: any) {
  if (!firstFormMenu) return  // app 只有 task_center 等无表单菜单, 留在总览页
  if (selectedApaasMenuId.value) return  // 用户已经手动选过菜单, 不要覆盖
  onApaasMenuSelected(firstFormMenu)
}

function onApaasMenuSelected(menu: {
  menu_id: string
  menu_name?: string
  menu_type?: string
  form_id?: string | null
  menu_display?: string
}) {
  if (!existingAppId.value) return
  selectedApaasMenuId.value = menu.menu_id
  // design-v4 Phase A: FormDesignerPanel 用 menu_name / form_id 反查 model
  selectedApaasMenuName.value = menu.menu_name || ''
  selectedApaasMenuFormId.value = menu.form_id ? String(menu.form_id) : ''
  // R (2026-05-27): 保存 menu_type 让 CUSTOM 菜单走 CustomPagePreviewPanel 分支
  selectedApaasMenuType.value = (menu.menu_type || menu.menu_display || '').toUpperCase()
  // 仅在切到 platform 视图后才允许切菜单
  if (activeView.value !== 'platform') activeView.value = 'platform'
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

const switchToPlatform = () => {
  activeView.value = 'platform'
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

  // 主加载已取到完整 app — 顺手建立轮询基线，省掉原 primeAppPollingBaseline 的重复 GET。
  seedAppPollingBaseline(app)

  const isDeployed = !!app.apaas_app_id || app.status === 'completed'
  if (!isDeployed) {
    // 2026-05-29: 草稿(未部署)应用进 platform 视图。原默认落「设计」(spec) tab,
    // 现 spec tab 暂隐藏(SPEC_TAB_ENABLED=false)→ 经 normalizeTopTab 落「功能」(design)。
    activeView.value = 'platform'
    topTab.value = normalizeTopTab('spec')
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
  // 2026-05-19 image #29: 部署 confirm 后立即关 modal，把执行过程放右侧。
  deployConfirmOpen.value = false
  startDeployFromArtifact()
}

// ─────────── PR3 (SPEC v2 §2): 顶部 CTA + 应用信息编辑 ───────────
//
// 复用现有 deployConfirmOpen / deployHistoryOpen — 不重写 DeployConfirmModal /
// DeployHistoryDrawer. 这里只是给顶部 [部署] / [历史] / [更多] 按钮注入入口.
//
// canEditApaasInfo / canDeployFromTopCTA 是只读 guard, 应用没部署 / 没生成内容时
// 把按钮 disable 掉避免空打.

// 2026-05-26 (PR3 reviewer P1 #5): viewer 假阳性修复 — 检查 EDIT 权限.
// store.currentApp.permissions.edit 在 fetchAppDetail 中由 /api/applications/{id} 返回填充
// (后端 _UserAppPermissionsResp 包 view/edit/delete bool). viewer 没 edit 权限时
// 编辑入口直接 disable, 不再让用户点开 popover 填完才被 403 拒.
const canEditApaasInfo = computed(() => {
  if (!store.currentApp?.apaas_app_id || !builderCurrentAppId.value) return false
  // 老数据 / 老 API 不返 permissions 时不卡, 保留旧行为 (RBAC 在后端 enforce)
  const perms = (store.currentApp as any)?.permissions
  if (perms && typeof perms.edit === 'boolean') return perms.edit
  return true
})

// ─────────────── 2026-05-26 design-v4 Polish F2 ───────────────
// 应用发布状态 chip
//   backend Application.status 枚举: draft/generating/updating/completed/failed
//   2026-05-27 design-v4 K3: 接 /applications/{id}/publish-status 真值 3 态:
//     'draft' / 'published' / 'draft_on_published' (有未发布改动)
const appPublishDetail = ref<{
  status: 'draft' | 'published' | 'draft_on_published' | 'failed' | 'generating'
  latest_deploy: { version?: string; completed_at?: string; user_id?: number } | null
  pending_changes_count: number
  partial: boolean
}>({ status: 'draft', latest_deploy: null, pending_changes_count: 0, partial: false })

const appPublishStatus = computed<'published' | 'draft' | 'draft_on_published' | 'failed' | 'generating'>(() => appPublishDetail.value.status)
const appPublishTooltip = computed(() => {
  const d = appPublishDetail.value
  if (d.status === 'published') {
    if (!d.latest_deploy) return '已发布到 aPaaS 平台'
    return `已发布 ${d.latest_deploy.version || ''} · ${d.latest_deploy.completed_at?.slice(0, 19) || ''}`
  }
  if (d.status === 'draft_on_published') {
    return `已发布 ${d.latest_deploy?.version || ''}, 但有 ${d.pending_changes_count} 个未发布改动`
  }
  if (d.status === 'failed') {
    return d.partial
      ? '上次生成中途失败，已建了一部分模型/表单。点「重试」幂等续跑补全缺失项。'
      : '上次生成失败。点「重试」重新生成。'
  }
  if (d.status === 'generating') {
    return '正在生成到 aPaaS 平台…（创建模型/表单/角色）'
  }
  return '应用尚未发布到平台（草稿）'
})

async function refreshAppPublishStatus() {
  if (!existingAppId.value) return
  try {
    const resp = await request.get<any, any>(`/applications/${existingAppId.value}/publish-status`)
    if (resp?.ok) {
      appPublishDetail.value = {
        status: resp.status || 'draft',
        latest_deploy: resp.latest_deploy || null,
        pending_changes_count: resp.pending_changes_count || 0,
        partial: !!resp.partial,
      }
    }
  } catch {
    // 失败兜底用老逻辑
    const app = store.currentApp as any
    appPublishDetail.value = {
      status: app?.apaas_app_id || app?.status === 'completed' ? 'published' : 'draft',
      latest_deploy: null,
      pending_changes_count: 0,
      partial: false,
    }
  }
}

// 2026-05-29: 失败应用的「重试」— 幂等 generate-run 续跑补全, 复用已建对象不撞冲突。
async function retryFailedGenerate() {
  if (!existingAppId.value) return
  try {
    await applicationApi.generateRun(existingAppId.value)
    ElMessage.success('已重新触发生成，稍后刷新查看进度')
    appPublishDetail.value = { ...appPublishDetail.value, status: 'generating' }
    setTimeout(() => refreshAppPublishStatus(), 2000)
  } catch (e: any) {
    ElMessage.error('重试失败：' + (e?.response?.data?.detail || e?.message || '未知错误'))
  }
}
watch(() => existingAppId.value, () => refreshAppPublishStatus(), { immediate: true })

const editAppInfoOpen = ref(false)
const editAppName = ref('')
const editAppDesc = ref('')
const editAppInfoSaving = ref(false)
const editAppInfoError = ref('')
const _editAppInfoInitial = ref({ name: '', desc: '' })

const editAppInfoDirty = computed(() => {
  const n = editAppName.value.trim()
  const d = editAppDesc.value.trim()
  return n !== _editAppInfoInitial.value.name || d !== _editAppInfoInitial.value.desc
})

function prefillEditAppInfo() {
  const initName = (store.preview.appName || (store.currentApp as any)?.app_name || (store.currentApp as any)?.name || '').trim()
  const initDesc = ((store.currentApp as any)?.description || (store.currentApp as any)?.appDesc || '').trim()
  editAppName.value = initName
  editAppDesc.value = initDesc
  _editAppInfoInitial.value = { name: initName, desc: initDesc }
  editAppInfoError.value = ''
}

async function saveAppInfo() {
  const appId = builderCurrentAppId.value
  if (!appId) {
    editAppInfoError.value = '当前应用未保存，无法编辑'
    return
  }
  const name = editAppName.value.trim()
  const desc = editAppDesc.value.trim()
  if (!name && !desc) {
    editAppInfoError.value = '请填应用名或描述至少一个字段'
    return
  }
  if (name && name.length > 64) {
    editAppInfoError.value = '应用名最多 64 字符'
    return
  }
  editAppInfoSaving.value = true
  editAppInfoError.value = ''
  try {
    const resp = await request.post<any, any>(
      `/applications/${appId}/update-apaas-info`,
      {
        app_name: name !== _editAppInfoInitial.value.name ? name : '',
        description: desc !== _editAppInfoInitial.value.desc ? desc : '',
      },
    )
    if (resp?.ok) {
      // 同步本地 store, 让 builderAppDisplayName 立刻刷新
      if (name) {
        store.preview.appName = name
        if (store.currentApp) {
          store.currentApp = { ...store.currentApp, app_name: name, name: name } as any
        }
      }
      if (desc && store.currentApp) {
        store.currentApp = { ...store.currentApp, description: desc } as any
      }
      // 2026-05-26 (PR3 reviewer #7): 同步更新 _editAppInfoInitial 基线 —
      // popover 不关时再改回原值不会触发空操作 diff payload.
      _editAppInfoInitial.value = { name, desc }
      // 2026-05-26 (PR3 reviewer P1 #2): partial_success — 平台已改但 DB sync 失败时
      // 给用户友好提示, 不当成"成功"也不当成"失败".
      if (resp?.partial_success) {
        ElMessage.warning(
          `应用信息已存到平台 (${(resp.updated_fields || []).join(', ') || '已保存'})，`
          + '本地缓存稍后会同步, 刷新页面看到最新',
        )
      } else {
        ElMessage.success(`应用信息已更新（${(resp.updated_fields || []).join(', ') || '已保存'}）`)
      }
      editAppInfoOpen.value = false
    } else if (resp?.error_code === 'NOT_IMPLEMENTED') {
      editAppInfoError.value = resp.message || '平台无对应更新接口，请到平台 UI 修改'
    } else if (resp?.error_code === 'APP_NOT_DEPLOYED') {
      editAppInfoError.value = resp.message || '应用尚未部署，先部署后才能编辑信息'
    } else {
      editAppInfoError.value = resp?.message || '保存失败'
    }
  } catch (e: any) {
    editAppInfoError.value = e?.response?.data?.detail || e?.message || '网络错误'
  } finally {
    editAppInfoSaving.value = false
  }
}

// 顶部 CTA handlers — 复用现有 deploy modal / history drawer / popover
function onTopCtaMoreCommand(cmd: string) {
  if (cmd === 'edit_info') {
    if (!canEditApaasInfo.value) {
      ElMessage.warning('应用尚未部署到平台，无法编辑应用信息')
      return
    }
    prefillEditAppInfo()
    editAppInfoOpen.value = true
  } else if (cmd === 'open_platform') {
    if (store.currentApp?.apaas_app_id) {
      openInPlatform()
    } else {
      ElMessage.warning('应用尚未部署，无法跳转平台 UI')
    }
  }
}

// 部署是否在跑（任意 step running 或刚启动尚未拿到 steps）
const isDeploying = computed(() => {
  if (deployExecuting.value !== null) return true
  if (deployRunningAll.value) return true
  return deploySteps.value.some((s: any) => s.status === 'running')
})

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
    { icon: 'users', label: '角色', count: updateRoleDiffItems.value.length },
    { icon: 'book-open', label: '字典', count: updateDictDiffItems.value.length },
    { icon: 'database', label: '模型', count: updateModelDiffItems.value.length },
    { icon: 'clipboard', label: '表单', count: updateFormDiffItems.value.length },
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
  if (!STANDARD_DESIGN_DOC_RE.test(file.name.toLowerCase())) {
    queueMaterialFileForChat(file, {
      autoSend: true,
      message: existingAppId.value
        ? '请基于这个附件重新理解需求，整理成新版设计文档并生成变更建议。'
        : '请基于这个附件理解需求，整理成标准设计文档并继续生成应用。',
    })
    return
  }
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
  if (!STANDARD_DESIGN_DOC_RE.test(file.name.toLowerCase())) {
    queueMaterialFileForChat(file, {
      autoSend: true,
      message: '请基于这个附件理解我的更新需求，整理成新版设计文档并生成变更计划。',
    })
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
interface DeployStep { key: string; label: string; status: 'pending' | 'running' | 'completed' | 'error'; deps_met: boolean; error?: string; result?: any }
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
    { title: '初始化', icon: 'rocket', test: (s: DeployStep) => s.key === 'create_app' },
    { title: '角色', icon: 'users', test: (s: DeployStep) => s.key.startsWith('create_role:') || s.key === 'create_roles_dicts' },
    { title: '数据字典', icon: 'book-open', test: (s: DeployStep) => s.key.startsWith('create_dict:') },
    { title: '数据模型', icon: 'database', test: (s: DeployStep) => s.key.startsWith('create_model:') },
    { title: '表单配置', icon: 'clipboard', test: (s: DeployStep) => s.key.startsWith('create_form:') },
    { title: '权限配置', icon: 'lock', test: (s: DeployStep) => s.key === 'configure_permissions' },
  ]
  return defs.map(d => {
    const ss = deploySteps.value.filter(d.test)
    return { ...d, steps: ss, allDone: ss.length > 0 && ss.every(s => s.status === 'completed'), hasError: ss.some(s => s.status === 'error'), doneCount: ss.filter(s => s.status === 'completed').length }
  }).filter(d => d.steps.length > 0)
})

const updateExecutionGroups = computed(() => {
  const defs = [
    { key: 'roles', title: '角色', icon: 'users' },
    { key: 'dicts', title: '数据字典', icon: 'book-open' },
    { key: 'models', title: '数据模型', icon: 'database' },
    { key: 'forms', title: '表单', icon: 'clipboard' },
    { key: 'permissions', title: '权限', icon: 'lock' },
    { key: 'other', title: '其他', icon: 'puzzle' },
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
      // 初始加载期不刷远程 meta（重量级 list(include_remote:true) → pending）；
      // 上线徽章此时已由本地 publish-status 兜底。部署动作完成后（appInitialLoadDone=true）才刷真值。
      if (appInitialLoadDone.value) await refreshCurrentAppRemoteMeta(deployAppId.value)
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
      if (resolveResp?.doc_version && deployAppId.value != null) {
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
  // Markdown 走标准设计文档解析；Word/PDF/TXT 等材料走聊天附件，由 AI 先整理成标准设计文档。
  const lowerName = file.name.toLowerCase()
  if (!STANDARD_DESIGN_DOC_RE.test(lowerName)) {
    queueMaterialFileForChat(file, {
      autoSend: true,
      message: existingAppId.value
        ? '请基于这个附件理解我的修改需求，整理成新版设计文档并生成变更建议。'
        : '请基于这个附件理解需求，先整理成标准设计文档，再继续生成应用。',
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

  // 非 Markdown 文件统一作为需求材料交给 AI 理解；Markdown 才走标准设计文档解析/增量对比。
  if (!STANDARD_DESIGN_DOC_RE.test(file.name.toLowerCase())) {
    queueMaterialFileForChat(file, {
      autoSend: true,
      message: existingAppId.value
        ? '请基于这个附件理解我的修改需求，整理成新版设计文档并生成变更建议。'
        : '请基于这个附件理解需求，先整理成标准设计文档，再继续生成应用。',
    })
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
                  ? modules.map((m: string) => moduleLabels[m] || m).join('、')
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
  store.changePlan.actions.forEach((a: { id: string; selected: boolean }) => {
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
    if (attachmentPayload.kind === 'file' && STANDARD_DESIGN_DOC_RE.test(attachmentPayload.file.name.toLowerCase())) {
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

  const shouldUseApplicationUpdateShortcut = isApplicationUpdateMessage
    && (
      attachmentPayloads.length === 0
      || (
        attachmentPayloads.length === 1
        && attachmentPayloads[0].kind === 'file'
        && STANDARD_DESIGN_DOC_RE.test(attachmentPayloads[0].file.name.toLowerCase())
      )
    )

  if (shouldUseApplicationUpdateShortcut) {
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

// ── 外部需求分析助手 deeplink (?from=requirements) ─────────────────────
// 用户在 MCP 客户端 chat 里点 agent 给的 [→ Builder](deeplink) 链接进来，
// 立刻从 backend cache 拿 md（agent 已通过 submit_design_doc 工具 push 进去），
// 弹 ChooseAppTargetDialog 让用户选「新建应用」或「更新到现有应用」。
const reqDialogVisible = ref(false)
const reqDialogLoading = ref(false)
const reqDialogFilename = ref('')
const reqDialogSuggestedName = ref('')
const reqDialogSuggestedCode = ref('')
const reqDialogCandidates = ref<Array<{ id: number; app_name: string; app_code: string; status: string; apaas_app_id?: string | null; updated_at?: string | null; match_reasons?: string[]; name_will_change?: boolean }>>([])
let reqPendingMd: { filename: string; content: string; pendingId: string | null } | null = null

function _extractAppNameFromMd(md: string): string {
  if (!md) return ''
  const standardName = extractAppNameFromText(md)
  if (standardName) return standardName.slice(0, 60)
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
      ElMessage.warning('暂无可用的设计文档 — 请回到外部 让需求分析助手重新生成一份')
      return
    }
    const filename = res.file_name || 'design-doc.md'
    const inferred = _extractAppNameFromMd(res.md_content) || _fallbackNameFromFilename(filename)
    const inferredCode = extractAppCodeFromText(res.md_content)
    reqPendingMd = { filename, content: res.md_content, pendingId: res.pending_id || null }
    reqDialogFilename.value = filename
    reqDialogSuggestedName.value = inferred
    reqDialogSuggestedCode.value = inferredCode
    reqDialogCandidates.value = []
    reqDialogVisible.value = true
    if (inferred || inferredCode) {
      reqDialogLoading.value = true
      try {
        reqDialogCandidates.value = await applicationApi.matchByName(inferred, 5, inferredCode)
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
  if (payload.mode === 'new') {
    const codeDuplicate = reqDialogCandidates.value.find(app => (app.match_reasons || []).includes('code_exact'))
    if (codeDuplicate) {
      try {
        await ElMessageBox.confirm(
          `检测到应用编码「${reqDialogSuggestedCode.value || codeDuplicate.app_code}」已被现有应用「${codeDuplicate.app_name}」使用。继续新建会为新应用编码自动加后缀，生成后的应用名称/编码可能不再与文档完全一致；如果要沿用这个编码，请选择更新现有应用。`,
          '应用编码重复',
          {
            confirmButtonText: '仍然新建',
            cancelButtonText: '返回选择',
            type: 'warning',
          },
        )
      } catch {
        reqPendingMd = pending
        reqDialogVisible.value = true
        return
      }
    }
  }
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
  // 同步当前应用到 backend（让 外部 agent 通过 user_id 拿到 current app_id）
  void syncCurrentAppToBackend()
  // agent 改 SPEC 后右侧自动刷新 — 启动 5s 轮询
  startAppPolling()
  // 轮询基线改由主加载路径用已取到的 app 对象 seedAppPollingBaseline() 建立，
  // 不再为了一个 updated_at 单独 GET 一次完整应用详情（见 seedAppPollingBaseline 注释）。
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
          parseReady.value = store.preview.models.length > 0 || store.preview.forms.length > 0
          currentAgent.value = 'builder'
        }
        loadedAppCode.value = app.app_code || pickAppCode(configData) || ''
        parsedAppCode.value = loadedAppCode.value
        deployAppId.value = aid
        // 先翻视图消占位（detail 已就绪），再后台拉部署步骤 —— 别让 8s 的 steps/status
        // (后端按 apaas 真实对象远程重建进度) 把"加载应用配置中"占位卡 8 秒。
        // restoreActiveViewForApp 只用 app 本身, 不依赖 deploySteps。
        await restoreActiveViewForApp(app)
        void loadDeployStatus()
        // 加载期不刷远程 meta（apaas_url 已由 GET /applications/{id} 提供，上线徽章走本地 publish-status）。
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
                // 加载期不刷远程 meta（重量级 list(include_remote:true)）；上线徽章走本地 publish-status。
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
        // 加载期不刷远程 meta（apaas_url 已由 GET /applications/{id} 提供，上线徽章走本地 publish-status）。
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
        // 2026-05-21 用户点 Apps 列表"构建"按钮 → 期望立即开跑 deploy 流程，
        // 不是只看 SPEC 干等。Agent C (commit de3a041) 删左侧 deploy 面板后
        // "一键跑全部"按钮没了，需要这里自动触发。
        // deployRunAll 自带 guard：deployAllDone / running / executing 任一为
        // true 时 noop，所以已经部署完的应用重新打开不会重跑。
        if (!deployAllDone.value && deploySteps.value.length > 0) {
          deployRunAll().catch(e => {
            console.error('[deploy_app_id] auto deployRunAll 失败', e)
          })
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

  // 从 外部需求分析助手 deeplink 进来 (?from=requirements)：拉 cache 弹选目标对话框
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

  // 初始加载流程结束 — 此后部署/发布动作触发的 loadDeployStatus 才允许刷新远程 meta。
  appInitialLoadDone.value = true
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

<style scoped src="./ChatPage.styles.css"></style>

<style src="./ChatPage.global.css"></style>
