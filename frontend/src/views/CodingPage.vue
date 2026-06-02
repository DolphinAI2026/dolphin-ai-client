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
        module-name="AI Coding"
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

        <div v-if="showCodingUnselected" class="coding-unselected-pane">
          <header class="coding-session-header">
            <div class="coding-session-title-block">
              <strong class="coding-session-title">未选择会话</strong>
            </div>
          </header>
          <div class="coding-unselected-welcome">
            <h2>AI Coding</h2>
            <p>从左侧选择一个开发会话继续，或点击上方「+ 新会话」开始新的自开发任务。AI 会在会话里整理任务、创建工作区，并持续生成页面、接口、脚本或扩展代码。</p>
          </div>
        </div>

        <!-- Stream Pane (对话流视图 - 2026-05-17 B 重构：永远显示，IDE/文件改抽屉) -->
        <div v-else class="stream-pane">
          <header class="coding-session-header">
            <div class="coding-session-title-block">
              <span class="coding-session-kicker">AI Coding</span>
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
          </header>

          <div
            v-if="!isStreaming && streamMessages.length === 0"
            class="coding-empty-thread"
          >
            <div class="coding-empty-title">这个开发会话还没有消息</div>
            <div class="coding-empty-sub">直接在底部输入需求，AI 会整理任务并创建工作区。</div>
          </div>

          <AgentConversation
            v-else
            :messages="agentMessages"
            :typing="isStreaming"
            empty-title=""
            empty-hint=""
          >
            <template #custom="{ message }">
              <template v-if="streamCustom(message)?.sm">
                <!-- file_write / file_edit（native 无对应 kind,保留 FileCard）-->
                <template v-if="['file_write', 'file_edit'].includes(streamCustom(message).sm.type)">
                  <FileCard
                    :action="streamCustom(message).sm.type === 'file_write' ? 'write' : 'edit'"
                    :file-name="streamCustom(message).sm.fileName"
                    :file-content="streamCustom(message).sm.fileContent"
                    :collapsed="streamCustom(message).sm.collapsed"
                    @toggle="streamCustom(message).sm.collapsed = !streamCustom(message).sm.collapsed"
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

          <!-- Chat 底部输入框（非流式时可用） -->
          <div v-if="!isStreaming" class="chat-input-bar">
            <UnifiedChatComposer
              v-model="userInput"
              :attachments="codingComposerAttachments"
              :disabled="isCreating"
              :sending="isCreating"
              :show-stop="false"
              :send-disabled="!userInput.trim() || isCreating"
              accept=".md,.pdf,.docx,.txt,.png,.jpg,.jpeg"
              placeholder="输入需求，粘贴图片或点附件..."
              @send="sendMessage"
              @files-picked="handleComposerFiles"
              @remove-attachment="removeAttachment"
            >
              <template #footer-left>
                <div class="coding-model-inline">
                  <el-popover
                    v-model:visible="codingModelPopoverVisible"
                    placement="top-start"
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
                      <div class="coding-model-tip">{{ codingModelHint }}</div>
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
                </div>
                <VoiceInputButton v-model="userInput" :llm-config-id="selectedCodingModelOption?.id ?? null" />
              </template>
            </UnifiedChatComposer>
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

</template>

<script setup lang="ts">
import { API_PREFIX } from '@/utils/request'
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, ArrowDown, Download, Monitor, Delete, Fold, Expand, ChatDotRound } from '@element-plus/icons-vue'
import { useCodingStore } from '@/stores/coding'
import type { PlatformEnv } from '@/api/platformEnv'
import { useUserStore } from '@/stores/user'
import { codingApi, isIdeUnavailableError } from '@/api/coding'
import type { CodingConversation, WorkspaceInfo, ReplayStreamMessage } from '@/api/coding'
import { gitConnectionApi } from '@/api/gitConnection'
import { applicationApi } from '@/api/application'
import { useThemeStore } from '@/stores/theme'
import BuilderFrame from '@/components/BuilderFrame.vue'
import FileCard from '@/components/FileCard.vue'
import SessionSidebar, { type SessionItem as SidebarSessionItem } from '@/components/common/SessionSidebar.vue'
import AgentConversation from '@/components/common/AgentConversation.vue'
import VoiceInputButton from '@/components/common/VoiceInputButton.vue'
import type { AgentMessage, AgentToolPayload } from '@/components/common/agent-conversation/types'
import { useCodingModel } from './coding/useCodingModel'
import { useStreamMessages, renderMarkdown } from './coding/useStreamMessages'
import { useIdeManager } from './coding/useIdeManager'
import { useCodingWorkspace } from './coding/useCodingWorkspace'
import { useCodingPipeline } from './coding/useCodingPipeline'
import UnifiedChatComposer from '@/components/common/UnifiedChatComposer.vue'
import type { UnifiedChatAttachment } from '@/components/common/chatComposer'

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
  loadCodingModelOptions,
  handleCodingModelChange,
  selectCodingModel,
  formatCodingModelProvider,
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
      out.push({ id: 'sm' + i, kind: 'assistant', content: msg.content })
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

// 产物面板 3 态显示策略（image #24 设计反馈）：
//   null   → 自动：有产物 / streaming 中默认展开，无产物折叠
//   true   → 用户显式 open（强制展开）
//   false  → 用户显式 close（强制折叠，即使有产物也尊重）
// 解决之前 "codingArtifactsHasAny.value return true" 把用户 toggle 意志盖掉的问题。
const codingArtifactPanelUserToggle = ref<boolean | null>(null)

// 仅在「确有产物」时自动弹产物面板。去掉 isStreaming：之前一开始 streaming（含 READ 问答、
// codegen 刚起步还没写文件）就弹空面板，体验差（用户反馈「还没产物不着急弹」）。
const codingArtifactPanelAutoShow = computed(() =>
  codingArtifactsHasAny.value
)

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
    meta: conv.workspace_id || undefined,
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
  const messages = await codingApi.getMessages(conversationId)
  codingStore.reset()
  codingStore.conversationId = conversationId
  setWebIdeAvailable()
  ideUrl.value = null
  pendingIdeUrl.value = null
  ideLoaded.value = false
  activeView.value = 'chat'
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
  setWebIdeAvailable()
  ideUrl.value = null
  pendingIdeUrl.value = null
  ideLoaded.value = false
  streamMessages.value = []
  activeView.value = 'chat'
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

const AI_BUILDER_PENDING_CODING_KEY = 'ai_builder_pending_coding'
// F3 (2026-06-02): 记住 Builder→Coding handoff 的来源应用，给「← 回 Builder」回跳用。
const handoffSourceApp = ref<{ id: string; name: string } | null>(null)
function backToBuilder() {
  const app = handoffSourceApp.value
  if (!app?.id) return
  router.push({ path: '/chat', query: { app_id: app.id, tab: 'spec' } }).catch(() => {})
}
async function maybeConsumeAiBuilderDispatch() {
  if (route.query.from_ai_builder !== '1') return
  if (route.query.workspace_id || route.query.ws) return
  if (streamMessages.value.length > 0 || isCreating.value || isStreaming.value) return

  const raw = sessionStorage.getItem(AI_BUILDER_PENDING_CODING_KEY)
  if (!raw) return

  let payload: { message?: string; projectId?: number | null; sceneCategory?: string; app_id?: number | string; app_name?: string } | null = null
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

  // F3: 记住来源应用做「← 回 Builder」回跳。app_id 在 URL query（buildCodingRouteQuery 已带），
  // app_name 在 sessionStorage payload（之前被丢弃，这里补上）。
  const srcAppId = payload.app_id ?? route.query.app_id
  if (srcAppId) {
    handoffSourceApp.value = { id: String(srcAppId), name: payload.app_name || '应用' }
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
      refreshCodingConversations(),
    ])
    allWorkspaces.value = workspaces
  } catch (e) {
    console.error('\u521D\u59CB\u5316 AI Coding \u9875\u9762\u5931\u8D25:', e)
  }

  const wsId = (route.query.workspace_id || route.query.ws) as string
  if (wsId) {
    await openWorkspaceById(wsId)
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
      await maybeConsumeAiBuilderDispatch()
    }
  }
})

onUnmounted(() => {
  // cleanup if needed
})

// ============ Workspace Operations ============

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
const { sendMessage } = useCodingPipeline({
  model: { codingModelOptions, codingModelLoading, updatingCodingModel, selectedCodingModelValue, persistedCodingModelValue, codingModelPopoverVisible, selectedCodingModelOption, codingModelHint, codingModelSummary, toCodingModelValue, normalizeCodingModelValue, applyCodingModelSelection, loadCodingModelOptions, handleCodingModelChange, selectCodingModel } as any,
  stream: { streamMessages, isStreaming, streamContainerRef, scrollStreamToBottom, addStreamMsg, appendToLastThinking, appendToLastCommand, completeStepMsg, addStepRunningMsg, restoreReplayStreamMessages } as any,
  ide: { ideUrl, ideLoaded, ideLoadError, ideLoadingText, pendingIdeUrl, activeView, setIdeUrl, onIdeFrameLoad, onIdeFrameError, retryIdeLoad, openPendingIde } as any,
  workspace: { allWorkspaces, isDownloading, embeddedAppId, existingWorkspaces, workspaceDisplayName } as any,
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
/* F3: 会话表头里的「← 回 Builder」回跳链，靠右、蓝色 accent */
.coding-back-to-builder {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 28px;
  padding: 0 10px;
  border: 1px solid #3b82f6;
  border-radius: 7px;
  background: transparent;
  color: #3b82f6;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s ease;
}
.coding-back-to-builder:hover {
  background: rgba(59, 130, 246, 0.12);
  color: #2563eb;
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
  color: #6f7ff2;
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
html[data-theme="dark"] .coding-unselected-pane,
html[data-theme="dark"] .stream-pane,
html[data-theme="dark"] .stream-messages,
html[data-theme="dark"] .ide-loading-overlay {
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
