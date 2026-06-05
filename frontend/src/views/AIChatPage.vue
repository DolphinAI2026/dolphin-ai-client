<template>
  <WorkbenchShell>
  <div
    class="ai-chat-app"
    :class="[themeStore.isDark ? 'theme-dark' : 'theme-light', { 'aside-collapsed': asideCollapsed, 'is-embedded': isEmbeddedAppChat }]"
  >
    <!-- ═══════ 左侧 sessions（嵌入模式隐藏） ═══════ -->
    <SessionSidebar
      v-if="!isEmbeddedAppChat"
      module-name="AI 对话"
      brand-color="#f59e0b"
      :sessions="sessionItems"
      :active-id="currentSessionId"
      :tabs="sidebarTabs"
      :active-tab-key="sessionsFilter"
      :new-options="newSessionOptions"
      :collapsible="true"
      collapse-key="aichat:aside-collapsed"
      new-label="+ 新会话"
      back-route="/apps"
      back-label="返回应用"
      empty-hint="还没有会话，点上面新建一个"
      @select="(id) => loadSession(Number(id))"
      @create="() => onCreateSession()"
      @create-with-option="(cmd) => onCreateSession(cmd)"
      @rename="(s) => onRenameSession(sessionsById.get(Number(s.id)) as AIChatSession)"
      @delete="(s) => onDeleteSession(sessionsById.get(Number(s.id)) as AIChatSession)"
      @tab-change="(k) => (sessionsFilter = k as SessionFilter)"
      @collapse-change="(v) => (asideCollapsed = v)"
    />

    <!-- ═══════ 中间 chat ═══════ -->
    <main class="chat-main">
      <header class="chat-header">
        <div class="chat-title">
          <input
            v-if="currentSession && editingTitle"
            v-model="editingTitleText"
            class="title-input"
            @blur="saveTitle"
            @keydown.enter="saveTitle"
          />
          <span v-else-if="currentSession" @dblclick="startEditTitle" :title="'双击重命名'">
            {{ currentSession.title }}
          </span>
          <span v-else class="title-placeholder">未选择会话</span>
        </div>
        <div class="header-actions">
          <button
            v-if="currentSession"
            class="trace-entry-btn"
            title="查看本次会话的 Agent 活动 / Trace"
            @click="openSessionTrace"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
            </svg>
          </button>
          <button
            v-if="automationRunnerEnabled"
            class="automation-toggle"
            :class="{ active: automationPanelOpen, running: automationRunning }"
            @click="automationPanelOpen = !automationPanelOpen"
            :title="automationPanelOpen ? '收起脚本回放面板' : '打开脚本回放面板'"
          >脚本回放</button>
          <button
            v-if="artifacts.length > 0"
            class="artifacts-toggle"
            :class="{ active: artifactsPanelOpen }"
            @click="artifactsPanelOpen = !artifactsPanelOpen"
            :title="artifactsPanelOpen ? '收起设计文档' : '展开设计文档'"
          ><AppIcon name="file" :size="14" /> 设计文档 <span class="badge">{{ artifacts.length }}</span></button>
        </div>
      </header>

      <!-- 消息流 -->
      <AgentConversation
        v-if="currentSession"
        :messages="agentMessages"
        :typing="isSending && !lastEventIsAsk && !streamingText"
        :tool-grouping="true"
        @answer-ask="onAgentAnswerAsk"
        @open-trace="onOpenTrace"
      >
        <template #empty>
          <div class="welcome welcome-in-conversation">
            <div class="welcome-hero">
              <div class="welcome-badge">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 14 9l6 2-6 2-2 6-2-6-6-2 6-2z"/><path d="M19 17l1 3 3 1-3 1-1 3-1-3-3-1 3-1z"/></svg>
                <span>AI Builder</span>
              </div>
              <h1 class="welcome-title">{{ welcomeTitle }}</h1>
              <p class="welcome-sub">{{ welcomeIntro }}</p>
            </div>
            <div class="welcome-examples" aria-label="开场示例">
              <button
                v-for="example in introExamples"
                :key="example.title"
                type="button"
                class="welcome-example"
                @click="startFromIntroExample(example.prompt)"
              >
                <span class="welcome-example-title">{{ example.title }}</span>
                <span class="welcome-example-text">{{ example.short }}</span>
              </button>
            </div>
            <div class="welcome-capabilities" aria-label="AI Builder 能力范围">
              <span><i></i>整理需求</span>
              <span><i></i>生成 / 更新应用</span>
              <span><i></i>自开发页面和组件</span>
              <span><i></i>联调接口与修错</span>
            </div>
          </div>
        </template>
        <template #artifact="{ artifact }">
          <div class="artifact-card" @click="openArtifactInPanel(artifact.raw)">
            <div class="art-card-head">
              <span class="art-card-icon"><AppIcon name="file" :size="16" /></span>
              <span class="art-card-name">{{ artifact.filename }}</span>
              <span class="art-card-version">v{{ artifact.version }}</span>
              <button
                v-if="isMarkdownArtifact(artifact.raw) && !!getCachedAppId(currentSession?.id ?? 0, artifact.filename)"
                class="art-card-handoff"
                type="button"
                @click.stop="sendArtifactToBuilderByName(artifact.filename)"
                title="跳到 Builder 调整已部署应用"
              >在 Builder 中调整</button>
              <span class="art-card-arrow">›</span>
            </div>
            <div class="art-card-preview" v-if="artifact.preview">{{ artifact.preview }}</div>
          </div>
        </template>
        <!-- 应用就绪 CTA — generate_app_from_doc / deploy_application 成功后 inline 一张大卡，
             一键跳 app_view_url（或 fallback 到 /chat?app_id=N）。
             比让用户从工具卡 result JSON 里抠 app_id 直观得多。 -->
        <template #custom="{ message }">
          <div
            v-if="message.meta?.kind === 'app-ready' && message.meta?.info"
            class="app-ready-cta"
            :class="{ 'is-generating': !ctaIsReady(message.meta.info) && !ctaIsFailed(message.meta.info), 'is-failed': ctaIsFailed(message.meta.info) }"
            @click="(ctaIsReady(message.meta.info) || ctaIsFailed(message.meta.info)) && openAppReady(message.meta.info)"
          >
            <div class="cta-icon">
              <AppIcon v-if="ctaIsReady(message.meta.info)" name="rocket" :size="18" />
              <span v-else-if="ctaIsFailed(message.meta.info)">!</span>
              <AppIcon v-else name="hourglass" :size="18" />
            </div>
            <div class="cta-body">
              <div class="cta-title">
                应用「{{ message.meta.info.appName }}」{{ ctaIsReady(message.meta.info) ? '已就绪' : (ctaIsFailed(message.meta.info) ? '生成失败' : '正在生成中…') }}
              </div>
              <div v-if="!ctaIsReady(message.meta.info)" class="cta-sub">
                <span class="cta-progress-text">{{ ctaProgressText(message.meta.info) }}</span>
              </div>
              <div v-else class="cta-sub">
                <span v-if="message.meta.info.appId">app_id={{ message.meta.info.appId }}</span>
                <span v-if="message.meta.info.appId && message.meta.info.apaasAppId" class="cta-sub-sep">·</span>
                <span v-if="message.meta.info.apaasAppId">apaas_app_id={{ message.meta.info.apaasAppId }}</span>
                <span v-if="message.meta.info.appCode" class="cta-sub-sep">·</span>
                <span v-if="message.meta.info.appCode">{{ message.meta.info.appCode }}</span>
              </div>
              <div v-if="!ctaIsReady(message.meta.info) && !ctaIsFailed(message.meta.info)" class="cta-progress-bar">
                <div class="cta-progress-fill" :style="{ width: ctaPercent(message.meta.info) + '%' }"></div>
              </div>
            </div>
            <button
              v-if="ctaIsReady(message.meta.info) || ctaIsFailed(message.meta.info)"
              class="cta-action"
              type="button"
              @click.stop="openAppReady(message.meta.info)"
            >
              {{ ctaIsReady(message.meta.info) ? '打开应用 →' : '查看详情 →' }}
            </button>
          </div>
        </template>
        <template #typing>
          <div class="ai-avatar pulsing">AI</div>
          <div class="bubble thinking-bubble">
            <span class="dots"><span></span><span></span><span></span></span>
            <span class="thinking-label">{{ thinkingLabel }}</span>
            <span class="thinking-secs" v-if="durationSec > 0">{{ durationSec }}s</span>
          </div>
        </template>
      </AgentConversation>
      <div v-else class="welcome">
        <div class="welcome-hero">
          <div class="welcome-badge">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 14 9l6 2-6 2-2 6-2-6-6-2 6-2z"/><path d="M19 17l1 3 3 1-3 1-1 3-1-3-3-1 3-1z"/></svg>
            <span>AI Builder</span>
          </div>
          <h1 class="welcome-title">{{ welcomeTitle }}</h1>
          <p class="welcome-sub">{{ welcomeIntro }}</p>
        </div>
        <LandingComposer @submit="onStartNew" />
        <div class="welcome-examples" aria-label="开场示例">
          <button
            v-for="example in introExamples"
            :key="example.title"
            type="button"
            class="welcome-example"
            @click="startFromIntroExample(example.prompt)"
          >
            <span class="welcome-example-title">{{ example.title }}</span>
            <span class="welcome-example-text">{{ example.short }}</span>
          </button>
        </div>
        <div class="welcome-capabilities" aria-label="AI Builder 能力范围">
          <span><i></i>整理需求</span>
          <span><i></i>生成 / 更新应用</span>
          <span><i></i>自开发页面和组件</span>
          <span><i></i>联调接口与修错</span>
        </div>
      </div>

      <!-- 输入区 -->
      <div class="input-area" v-if="currentSession">
        <!-- 排队中提示卡（对话界面风格：流式中输入第二条消息会进队列） -->
        <div v-if="pendingQueue.length > 0" class="queue-banner">
          <span class="queue-icon"><AppIcon name="clock" :size="14" /></span>
          <span class="queue-text">{{ pendingQueue.length }} 条消息排队中 · 当前回复结束后自动发送</span>
          <button class="queue-clear" @click="pendingQueue = []" title="清空队列">×</button>
        </div>
        <UnifiedChatComposer
          v-model="inputText"
          :attachments="composerAttachments"
          :sending="isSending"
          :allow-send-while-sending="true"
          :send-disabled="!inputText.trim() && pendingFiles.length === 0"
          :multiple="true"
          accept=".md,.markdown,.txt,.doc,.docx,.pdf,.xls,.xlsx,.csv,.json,.png,.jpg,.jpeg,.gif,.webp,.svg,.html,.htm,.yaml,.yml,.xml,.zip"
          placeholder="输入需求，粘贴图片或点附件..."
          @send="onSend"
          @stop="onAbort"
          @files-picked="onComposerFilesPicked"
          @remove-attachment="removePendingFileByIndex"
        >
          <template #footer-left>
            <select
              v-model="selectedLlmId"
              class="model-select-inline"
              @change="onChangeLlm"
            >
              <option :value="null">默认模型</option>
              <option v-for="m in llmOptions" :key="m.id" :value="m.id">{{ m.config_name }}</option>
            </select>
          </template>
          <template #footer-right>
            <span class="hint">{{ isSending ? 'Enter 排队发送 · Shift+Enter 换行' : 'Enter 发送 · Shift+Enter 换行' }}</span>
            <!-- 等用户回答 (ask_clarifying_question) 时 agent 没在思考，把计时器藏起来；
                 否则显示 "AI 思考中 Ns" — 跟 typing 指示器同条件保持一致 -->
            <span v-if="durationSec > 0 && !lastEventIsAsk" class="hint timer">· AI 思考中 {{ durationSec }}s</span>
          </template>
        </UnifiedChatComposer>
      </div>
    </main>

    <!-- ═══════ 右侧 artifacts（仅在有设计文档 + 用户展开时显示）═══════ -->
    <aside
      class="aside-right"
      v-if="currentSession && artifactsPanelOpen && artifacts.length > 0"
      :style="{ width: asideRightWidth + 'px' }"
    >
      <div
        class="aside-resizer"
        @mousedown="startAsideResize"
        title="拖动调整宽度"
      ></div>
      <div class="art-header">
        <button class="art-close" @click="artifactsPanelOpen = false" title="收起">←</button>
        <span class="art-breadcrumb">
          <span class="seg">设计文档</span>
          <span class="sep">›</span>
          <span class="seg current">{{ activeArtifactName || (artifacts[0]?.filename || '') }}</span>
        </span>
        <span class="count-badge" v-if="artifacts.length > 1">{{ artifacts.length }}</span>
      </div>
      <!-- 文件列表（紧凑模式，仅当 >1 个文件时显示）-->
      <div class="art-list compact" v-if="uniqueFilenames.length > 1">
        <div
          v-for="fname in uniqueFilenames"
          :key="fname"
          class="art-card"
          :class="{ active: activeArtifactName === fname }"
          @click="loadArtifactByName(fname)"
        >
          <span class="art-card-dot"><AppIcon name="file" :size="13" /></span>
          <span class="art-card-fname">{{ fname }}</span>
          <span class="art-card-vbadge">v{{ latestVersionFor(fname) }}</span>
        </div>
      </div>
      <div class="art-preview" v-if="activeArtifactContent">
        <div class="art-preview-head">
          <!-- 2 tabs — 渲染 / 原文 -->
          <button
            class="small-btn"
            :class="{ active: panelTab === 'rendered' }"
            @click="panelTab = 'rendered'"
          >渲染</button>
          <button
            class="small-btn"
            :class="{ active: panelTab === 'raw' }"
            @click="panelTab = 'raw'"
          >原文</button>
          <!-- 历史版本下拉（≥ 2 个版本时显示）-->
          <select
            v-if="activeArtifactVersions.length > 1"
            class="art-version-select"
            :value="activeArtifactVersion"
            @change="onSelectArtifactVersion(($event.target as HTMLSelectElement).value)"
            :title="`共 ${activeArtifactVersions.length} 个版本，可切换查看`"
          >
            <option v-for="v in activeArtifactVersions" :key="v.version" :value="v.version">
              v{{ v.version }}{{ v.version === activeArtifactVersions[0].version ? ' (最新)' : '' }}
            </option>
          </select>
          <span class="art-preview-spacer"></span>
          <span class="art-meta-text">{{ artifactStats }}</span>
          <button class="small-btn" @click="copyArtifact" title="复制">⧉</button>
          <button class="small-btn" @click="downloadArtifact" title="下载">⤓</button>
          <!-- 设计文档完成 → 一键让 agent 调 generate_app_from_doc 工具创建应用。
               之前 agent 文案让用户切到「AI 需求分析」菜单 — 那个菜单已删；
               现在 UX 是用户直接在对话里说"生成应用"，frontend 加按钮帮用户省去打字。 -->
          <button
            v-if="canSendArtifactToBuilder && !alreadyDeployedAppId"
            class="small-btn primary"
            :disabled="isSending"
            @click="sendGenerateAppMessage"
            title="把当前设计文档发给 AI Builder，对话里生成应用（agent 会调 generate_app_from_doc 工具）"
          >→ 生成应用</button>
          <button
            v-if="canSendArtifactToBuilder && alreadyDeployedAppId"
            class="small-btn primary"
            @click="sendArtifactToBuilder"
            title="跳转到 Builder 继续维护已部署应用"
          >在 Builder 中调整</button>
        </div>
        <!-- Tab body -->
        <pre v-if="panelTab === 'raw'" class="art-preview-body">{{ activeArtifactContent }}</pre>
        <!-- HTML 产物: 用沙箱 iframe 原样渲染(等同本地打开), 不要走 markdown 渲染器
             (markdown 会把缩进的 HTML 当代码块, 且不应用文件自带 <style>)。 -->
        <!-- sandbox 不给 allow-scripts: AI 产出的 HTML 可能含恶意/越权脚本, 而 allow-same-origin
             + allow-scripts 同时给 = 脚本能读父页 token/越权。设计文档多是静态 CSS 布局, 去掉
             allow-scripts 仍能原样渲染样式/布局(等同本地打开), 又挡住脚本越权。 -->
        <iframe
          v-else-if="isHtmlArtifact"
          class="art-preview-frame"
          :srcdoc="activeArtifactContent"
          sandbox="allow-same-origin allow-popups"
          referrerpolicy="no-referrer"
          title="HTML 产物预览"
        ></iframe>
        <div v-else class="art-preview-body md" v-html="renderMd(activeArtifactContent)"></div>
      </div>
      <div v-else class="art-empty">
        <p class="muted">点击左侧文件查看</p>
      </div>
    </aside>

    <section
      v-if="automationRunnerEnabled && automationPanelOpen"
      class="automation-panel"
      aria-label="脚本回放面板"
    >
      <div class="automation-head">
        <div>
          <div class="automation-title">脚本回放</div>
          <div class="automation-subtitle">{{ automationStatusText }}</div>
        </div>
        <button
          class="automation-icon-btn"
          type="button"
          @click="automationPanelOpen = false"
          title="收起脚本回放面板"
          aria-label="收起脚本回放面板"
        >×</button>
      </div>
      <textarea
        v-model="automationPrompt"
        class="automation-textarea"
        :disabled="automationRunning"
        aria-label="自动化脚本需求"
      ></textarea>
      <div class="automation-actions">
        <button
          class="automation-primary"
          type="button"
          :disabled="automationRunning || !automationPrompt.trim()"
          @click="runAutomationScript"
        >执行创建应用脚本</button>
        <button
          class="automation-secondary"
          type="button"
          :disabled="!automationRunning"
          @click="stopAutomationScript"
        >停止</button>
        <button
          class="automation-secondary"
          type="button"
          :disabled="automationRunning || automationLogs.length === 0"
          @click="clearAutomationLogs"
        >清空</button>
        <button
          class="automation-secondary"
          type="button"
          :disabled="automationLogs.length === 0"
          @click="copyAutomationLogs"
        >复制日志</button>
      </div>
      <div class="automation-logs" aria-live="polite">
        <div v-if="automationLogs.length === 0" class="automation-log-empty">
          运行后这里会记录发送、工具调用、文档生成和应用生成进度。
        </div>
        <div
          v-for="(log, index) in automationLogs"
          :key="`${log.ts}-${index}`"
          class="automation-log-row"
          :class="`level-${log.level}`"
        >
          <span class="automation-log-time">{{ log.ts }}</span>
          <span class="automation-log-text">{{ log.text }}</span>
        </div>
      </div>
    </section>
  </div>
  <ChooseAppTargetDialog
    v-model="chooseDialogVisible"
    :filename="chooseDialogFilename"
    :suggested-name="chooseDialogSuggestedName"
    :candidates="chooseDialogCandidates"
    :loading="chooseDialogLoading"
    @confirm="onChooseDialogConfirm"
  />
  <AgentRunTraceDrawer
    v-model="traceDrawerVisible"
    :session-id="currentSession?.id ?? null"
    :prefer-run-id="tracePreferRunId"
  />
  </WorkbenchShell>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { marked } from 'marked'
import { aiChatApi, type AIChatSession, type AIChatMessage, type AIChatToolCall, type AIChatAttachment, type AIChatArtifact } from '@/api/aiChat'
import { llmConfigApi, type BuilderModelOption } from '@/api/llmConfig'
import { usePreviewStore } from '@/stores/preview'
import { useThemeStore } from '@/stores/theme'
import { useUserStore } from '@/stores/user'
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import SessionSidebar, { type SessionItem, type SessionTab, type NewSessionOption } from '@/components/common/SessionSidebar.vue'
import AgentConversation from '@/components/common/AgentConversation.vue'
import AgentRunTraceDrawer from '@/components/common/AgentRunTraceDrawer.vue'
import ChooseAppTargetDialog from '@/components/ChooseAppTargetDialog.vue'
import type { AgentMessage } from '@/components/common/agent-conversation/types'
import { ElMessage, ElMessageBox } from 'element-plus'
import { isImageFile } from '@/utils/pasteImages'
import UnifiedChatComposer from '@/components/common/UnifiedChatComposer.vue'
import AppIcon from '@/components/common/AppIcon.vue'
import LandingComposer from '@/components/v2/LandingComposer.vue'
import type { UnifiedChatAttachment } from '@/components/common/chatComposer'
// chat / cowork mode 已合并 — ChatDotRound 用作 session 列表前导 icon（对话界面风格）
import { ChatDotRound } from '@element-plus/icons-vue'
import { applicationApi } from '@/api/application'

const previewStore = usePreviewStore()
const themeStore = useThemeStore()
const userStore = useUserStore()

marked.setOptions({ breaks: true, gfm: true })

const route = useRoute()
const router = useRouter()

// ── State ──
const sessions = ref<AIChatSession[]>([])
const currentSession = ref<AIChatSession | null>(null)
const currentSessionId = computed(() => currentSession.value?.id ?? null)
const currentRunId = ref<string | null>(null)       // 最近一次实时 run（会话级入口默认选中）
const traceDrawerVisible = ref(false)
const tracePreferRunId = ref<string | null>(null)    // 抽屉打开时希望预选的 run

// chat / cowork mode 已合并 — 单一模式入口（agent 看附件情况自动切流程）
// 保留 SessionFilter 类型只是为了下面 onCreateSession 签名兼容；实际不再筛选。
type SessionFilter = 'all' | 'chat' | 'cowork'
const sessionsFilter = ref<SessionFilter>('all')
const filteredSessions = computed(() => sessions.value)

// 按更新时间分组：今天 / 昨天 / 本周 / 本月 / 更早（对话界面风格 sidebar）
// 2026-05-21 UI audit Fix 11: 7 天内 → 本周/本月 更精细分组
function _timeGroup(iso: string | null | undefined): string {
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

// SessionSidebar 适配 — 加 group 字段触发 SessionSidebar 的分组渲染
// 2026-05-21 UI audit Fix 11: 加 badgeIcon 让条目有视觉锚点
const sessionItems = computed<SessionItem[]>(() => {
  // 按 updated_at 倒序（最新在前）
  const sorted = [...filteredSessions.value].sort((a, b) => {
    const ta = new Date(a.updated_at || a.created_at || 0).getTime()
    const tb = new Date(b.updated_at || b.created_at || 0).getTime()
    return tb - ta
  })
  return sorted.map(s => ({
    id: s.id,
    title: s.title,
    group: _timeGroup(s.updated_at || s.created_at),
    badgeIcon: ChatDotRound,
    badgeTone: 'chat',
  }))
})
const sessionsById = computed(() => {
  const m = new Map<number, AIChatSession>()
  sessions.value.forEach(s => m.set(s.id, s))
  return m
})
// chat / cowork 已合并 — 不再提供 tab 筛选
const sidebarTabs = computed<SessionTab[]>(() => [])
// 不再提供模式选择菜单 — 单个 "新建会话" 按钮直接建
const newSessionOptions: NewSessionOption[] = []
const messages = ref<AIChatMessage[]>([])
const toolCalls = ref<AIChatToolCall[]>([])
const attachments = ref<AIChatAttachment[]>([])
const artifacts = ref<AIChatArtifact[]>([])

const welcomeTitle = '说出目标，AI 帮你搭应用，也能继续开发。'
const welcomeIntro = '这里不分“需求入口”和“开发入口”。你可以描述业务流程、上传材料、指定要改的页面或贴出运行报错，AI 会先理清上下文，再生成应用、修改代码、联调验证。'
const introExamples = [
  {
    title: '从业务目标开始',
    short: '搭一个整改闭环或审批系统',
    prompt: '给质量部搭一个 QMS 整改闭环，包含问题登记、责任人派发、整改验证、超期提醒和月度统计。',
  },
  {
    title: '从现有应用继续改',
    short: '改页面、补字段、接流程',
    prompt: '我想调整现有应用：新增一个审批状态字段，列表里支持按状态筛选，并把详情页的关键字段重新分组。',
  },
  {
    title: '从报错和联调接入',
    short: '贴接口、截图或构建错误',
    prompt: '我遇到一个接口联调问题，下面会贴报错和请求参数，请帮我定位原因并给出修改方案。',
  },
]

const llmOptions = ref<BuilderModelOption[]>([])
const selectedLlmId = ref<number | null>(null)
const defaultLlmId = computed(() =>
  llmOptions.value.find(option => option.is_default)?.id
  ?? llmOptions.value[0]?.id
  ?? null
)

function normalizeLlmId(id?: number | null): number | null {
  const ids = new Set(llmOptions.value.map(option => option.id))
  if (id != null && ids.has(id)) return id
  return defaultLlmId.value
}

function resetChatTenantState() {
  currentSession.value = null
  messages.value = []
  toolCalls.value = []
  attachments.value = []
  artifacts.value = []
  activeArtifactId.value = null
  activeArtifactName.value = ''
  activeArtifactContent.value = ''
  activeArtifactVersions.value = []
  artifactsPanelOpen.value = false
  transientItems.value = []
  streamingText.value = ''
  streamingTools.value = {}
  pendingChars.value = []
  pendingFinalMessage.value = null
  pendingQueue.value = []
  stopDrain()
  stopGenPoll()
  genProgress.value = null
}

const inputText = ref('')
const pendingFiles = ref<File[]>([])
const messagesRef = ref<HTMLElement>()
const composerAttachments = computed<UnifiedChatAttachment[]>(() =>
  pendingFiles.value.map((file, index) => ({
    id: index,
    name: file.name,
    kind: isImageFile(file) ? 'image' : 'file',
  })),
)

const isSending = ref(false)
const currentAbort = ref<AbortController | null>(null)
const durationSec = ref(0)
let _timer: ReturnType<typeof setInterval> | null = null
watch(isSending, val => {
  if (_timer) { clearInterval(_timer); _timer = null }
  durationSec.value = 0
  if (val) _timer = setInterval(() => { durationSec.value += 1 }, 1000)
})

// 右栏设计文档默认收起，有新文档时自动展开一次
const artifactsPanelOpen = ref(false)

// 左栏会话列表的折叠状态（容器 grid 用，SessionSidebar 自管 localStorage）
const asideCollapsed = ref<boolean>(localStorage.getItem('aichat:aside-collapsed') === '1')

// 右栏宽度（拖拽 + localStorage 持久化）
const ASIDE_RIGHT_WIDTH_KEY = 'aichat:aside-right-width'
const ASIDE_RIGHT_MIN = 360
const ASIDE_RIGHT_MAX_RATIO = 0.8
const asideRightWidth = ref<number>(
  Number.parseInt(localStorage.getItem(ASIDE_RIGHT_WIDTH_KEY) || '', 10) || 480,
)
function startAsideResize(e: MouseEvent) {
  e.preventDefault()
  const startX = e.clientX
  const startW = asideRightWidth.value
  const onMove = (ev: MouseEvent) => {
    // 拖拽手柄在右栏左边缘：向左拖 → delta>0 → 变宽
    const delta = startX - ev.clientX
    const max = Math.floor(window.innerWidth * ASIDE_RIGHT_MAX_RATIO)
    const next = Math.max(ASIDE_RIGHT_MIN, Math.min(max, startW + delta))
    asideRightWidth.value = Math.round(next)
  }
  const onUp = () => {
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
    try { localStorage.setItem(ASIDE_RIGHT_WIDTH_KEY, String(asideRightWidth.value)) } catch { /* ignore */ }
  }
  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
  document.body.style.cursor = 'ew-resize'
  document.body.style.userSelect = 'none'
}

// 临时存储 ask_user / thinking / artifact_card（流式过程中产生但未持久化的）
type TransientItem =
  | { kind: 'ask'; ask: { question: string; options: string[]; tc_id: number } }
  | { kind: 'thinking'; text: string; ts: number }
  | { kind: 'artifact_card'; artifact: AIChatArtifact; ts: number }
const transientItems = ref<TransientItem[]>([])

// 当前正在流式输出的助手内容（assistant_delta 累积）
const streamingText = ref('')

// LLM 正在流式生成 tool_calls 参数时的累积状态（按 tool index 分组）。
// tool_call_delta 阶段（LLM 还在流参数）→ 这里有数据；
// tool_call_start 之后（后端开始执行）→ 对应 index 被清掉。
type StreamingTool = { index: number; name: string; argumentsSoFar: string }
const streamingTools = ref<Record<number, StreamingTool>>({})
// 计算当前正在流式生成参数的 tool（取 index 最小的、有 name 的那个）
const activeStreamingTool = computed<StreamingTool | null>(() => {
  const list = Object.values(streamingTools.value).filter(t => t.name)
  if (!list.length) return null
  return list.sort((a, b) => a.index - b.index)[0]
})
// pending 队列 + 节流：兼容"假流式"LLM（一次性把全部内容吐回来）
// 把字符按 ~80 chars/sec 平滑显示，看起来像真在打字
const pendingChars = ref<string[]>([])
let drainTimer: ReturnType<typeof setInterval> | null = null

// 等流式 buffer 排空后才能推持久化消息（避免 streaming bubble 还在打字时被持久化消息抢走）
const pendingFinalMessage = ref<AIChatMessage | null>(null)
const currentTurnAssistantMessageReceived = ref(false)
const currentTurnFallbackErrorShown = ref(false)

function ensureDrain() {
  if (drainTimer) return
  drainTimer = setInterval(() => {
    if (pendingChars.value.length === 0) {
      stopDrain()
      // 排空了：如果有暂存的最终消息，现在落到 messages 列表
      if (pendingFinalMessage.value) {
        const m = pendingFinalMessage.value
        pendingFinalMessage.value = null
        streamingText.value = ''
        currentTurnAssistantMessageReceived.value = true
        messages.value.push(m)
      }
      return
    }
    // 自适应释放速率：积压少 → 慢慢打字 (~80 chars/sec)；积压多 → 加速追上
    // 公式：max(2, 队列长度的 8%)
    const rate = Math.max(2, Math.ceil(pendingChars.value.length * 0.08))
    const n = Math.min(pendingChars.value.length, rate)
    const slice = pendingChars.value.splice(0, n).join('')
    streamingText.value = streamingText.value + slice
  }, 30)
}

function stopDrain() {
  if (drainTimer) { clearInterval(drainTimer); drainTimer = null }
}

function flushPending() {
  if (pendingChars.value.length) {
    streamingText.value += pendingChars.value.join('')
    pendingChars.value = []
  }
  stopDrain()
}

const editingTitle = ref(false)
const editingTitleText = ref('')
const startEditTitle = () => {
  if (!currentSession.value) return
  editingTitle.value = true
  editingTitleText.value = currentSession.value.title
}
const saveTitle = async () => {
  if (!currentSession.value || !editingTitle.value) return
  const newTitle = editingTitleText.value.trim()
  if (newTitle && newTitle !== currentSession.value.title) {
    const updated = await aiChatApi.updateSession(currentSession.value.id, { title: newTitle })
    currentSession.value.title = updated.title
    const found = sessions.value.find(s => s.id === currentSession.value!.id)
    if (found) found.title = updated.title
  }
  editingTitle.value = false
}

// 活跃设计文档
const activeArtifactId = ref<number | null>(null)
const activeArtifactName = ref('')
const activeArtifactContent = ref('')
const artifactRawView = ref(false)

// 右栏 tab：rendered / raw
type PanelTab = 'rendered' | 'raw'
const panelTab = ref<PanelTab>('rendered')

// 内置脚本回放：给已经登录好的浏览器一个可视化自动执行入口。
type AutomationLogLevel = 'info' | 'warn' | 'error'
interface AutomationLog {
  ts: string
  level: AutomationLogLevel
  text: string
}
const AUTOMATION_PROMPT_KEY = 'ai-builder:script-runner-prompt'
const DEFAULT_AUTOMATION_PROMPT = `请基于以下需求直接生成一份标准应用设计文档，信息不足时请合理假设，不要继续追问。

我要创建一个客户拜访管理应用：
1. 管理客户档案，包含客户名称、行业、联系人、联系电话、客户等级、状态。
2. 管理拜访计划，包含客户、拜访人、拜访时间、拜访目的、计划状态。
3. 管理拜访记录，包含关联计划、拜访结论、后续动作、附件备注。
4. 需要列表、详情、创建、编辑、筛选和状态流转。
5. 设计文档完成后，继续调用工具生成应用。`
const storedAutomationPrompt = (() => {
  try { return localStorage.getItem(AUTOMATION_PROMPT_KEY) || '' }
  catch { return '' }
})()
const automationRunnerEnabled = computed(() => {
  if (route.query.script === '1' || route.query.e2e === '1') return true
  try {
    if (localStorage.getItem('ai-builder:script-runner') === '1') return true
  } catch { /* ignore */ }
  return Boolean(import.meta.env.DEV)
})
const automationPanelOpen = ref(route.query.script === '1' || route.query.e2e === '1')
const automationPrompt = ref(storedAutomationPrompt || DEFAULT_AUTOMATION_PROMPT)
const automationLogs = ref<AutomationLog[]>([])
const automationRunning = ref(false)
const automationStopRequested = ref(false)
const automationStatusText = computed(() => {
  if (automationRunning.value) return '正在执行，可以在页面里观察每一步'
  if (automationLogs.value.some(l => l.level === 'error')) return '上次执行有错误，日志里可查看'
  if (automationLogs.value.length > 0) return '脚本已结束'
  return '登录后点击执行，会在当前页面一步步跑'
})

// ── Render helpers ──

const userMessageAttachments = (msg: AIChatMessage): AIChatAttachment[] => {
  const ids = msg.extra_meta?.attachment_ids || []
  if (!ids.length) return []
  return attachments.value.filter(a => ids.includes(a.id))
}

const renderMd = (text: string): string => {
  if (!text) return ''
  try {
    return marked.parse(text) as string
  } catch (e) {
    console.warn('markdown parse failed', e)
    return text.replace(/</g, '&lt;').replace(/\n/g, '<br>')
  }
}

const toolArgsBrief = (tc: AIChatToolCall): string => {
  const a = tc.args_json || {}
  if (tc.tool_name === 'read_attachment') return a.filename || ''
  if (tc.tool_name === 'write_artifact') return `${a.filename} (${a.format || 'md'})`
  if (tc.tool_name === 'run_python') return (a.code || '').slice(0, 60).replace(/\n/g, ' ') + '…'
  if (tc.tool_name === 'ask_clarifying_question') return a.question?.slice(0, 80) || ''
  return ''
}

/**
 * 安全解析 tool 的 result_text JSON。MCP 工具走 streamable HTTP，result_text 通常是
 * `{"ok": true, ...}` 形态；本地工具（read_attachment/write_artifact 等）也是 JSON。
 * 解析失败返回 null — 上层降级到默认显示，避免崩。
 */
function _parseToolResult(text: string | null | undefined): any | null {
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return null
  }
}

/**
 * 按工具名 + result JSON 生成一行摘要 chip，让用户一眼看出工具做成了什么。
 * status=error 时全部退化到"❌ {error_code or message}"。
 * 解析失败/不认识的工具 → 返回空串，ToolCard 退化到默认 "工具调用 · Xs"。
 */
function summarizeToolResult(name: string, status: string, resultText: string | null | undefined): string {
  // 失败时优先用 error message / error_code
  if (status === 'error' || status === 'aborted') {
    const r = _parseToolResult(resultText) || {}
    const ec = r.error_code || r.code
    const msg = r.message || r.error || r.detail
    if (ec) return `❌ ${ec}`
    if (msg) return `❌ ${String(msg).slice(0, 60)}`
    return '❌ 调用失败'
  }
  if (status !== 'success') return ''  // running / pending 不显摘要

  const r = _parseToolResult(resultText)
  if (!r) return ''

  // MCP 平台工具
  if (name === 'list_platform_envs') {
    const envs: any[] = Array.isArray(r.envs) ? r.envs : []
    const count = r.connected_count ?? envs.filter(e => e?.status === 'connected').length ?? envs.length
    const def = envs.find(e => e?.is_default) || envs[0]
    if (def?.name) return `✅ 找到 ${count} 个环境，默认 ${def.name}`
    return `✅ 找到 ${count} 个环境`
  }
  if (name === 'validate_builder_doc' || name === 'validate_apaas_builder_doc') {
    const errs: any[] = Array.isArray(r.errors) ? r.errors : []
    const warns: any[] = Array.isArray(r.warnings) ? r.warnings : []
    const sections = r.section_count ?? r.sections_count ?? (Array.isArray(r.sections) ? r.sections.length : null)
    if (errs.length === 0) {
      const secPart = sections != null ? `${sections} 章节 / ` : ''
      return `✅ 校验通过 ${secPart}${warns.length} warning`
    }
    return `⚠️ ${errs.length} 个错误 / ${warns.length} warning`
  }
  if (name === 'generate_app_from_doc') {
    if (r.ok === false) return '❌ 生成失败'
    const appId = r.app_id ?? r.application_id
    const appName = r.app_name || r.application_name || ''
    if (appId) return `✅ app_id=${appId}${appName ? ' ' + appName : ''}`
    return '✅ 应用已生成'
  }
  if (name === 'deploy_application') {
    if (r.ok === false) return '❌ 部署失败'
    const apaasId = r.apaas_app_id
    const status = r.status || r.deploy_status
    if (apaasId) return `✅ 部署完成 apaas_app_id=${apaasId}`
    if (status === 'pending' || status === 'running') return '🟡 后台部署中'
    return '✅ 部署完成'
  }
  if (name === 'get_application') {
    const appName = r.app_name || r.application_name || ''
    const st = r.status || r.app_status
    if (appName || st) return `应用信息已就绪${appName ? '（' + appName + (st ? ', status=' + st : '') + '）' : st ? '（status=' + st + '）' : ''}`
    return '应用信息已就绪'
  }
  if (name === 'list_my_applications' || name === 'list_applications' || name === 'list_apaas_apps' || name === 'list_apaas_apps_in_env') {
    if (r.ok === false || r.success === false) {
      const rawText = Array.isArray(r.raw?.content)
        ? r.raw.content.map((x: any) => x?.text).filter(Boolean).join('；')
        : ''
      const msg = rawText || r.message || r.error || r.detail || r.error_code
      return msg ? `❌ ${String(msg).slice(0, 60)}` : '❌ 查询应用失败'
    }
    const items: any[] = Array.isArray(r.apps) ? r.apps : Array.isArray(r.applications) ? r.applications : Array.isArray(r.items) ? r.items : []
    return `找到 ${items.length} 个应用`
  }
  if (name === 'ask_clarifying_question') {
    return '⏸️ 等待用户回答'
  }
  if (name === 'write_artifact') {
    const fname = r.filename || r.path
    const ver = r.version
    if (fname && ver != null) return `✅ ${fname} v${ver}`
    if (fname) return `✅ ${fname}`
    return '✅ 已写入设计文档'
  }
  if (name === 'read_attachment') {
    const fname = r.filename
    const lines = r.line_count ?? r.lines
    if (fname && lines != null) return `✅ 读取 ${fname} (${lines} 行)`
    if (fname) return `✅ 读取 ${fname}`
    return '✅ 已读取附件'
  }

  // 兜底：r.ok=true / r.success=true → ✅，否则不显示（让默认 "工具调用 · Xs" 兜底）
  if (r.ok === true || r.success === true) return '✅ 完成'
  if (r.ok === false || r.success === false) return '❌ 失败'
  return ''
}

/**
 * 检测最近一次"应用就绪"事件 — 用于在对话流里 inline 渲染一张"打开应用"CTA 卡片。
 *
 * 触发：tool_calls 数组里存在 generate_app_from_doc / deploy_application 状态为 success
 * 且 result JSON 含 app_id（或 apaas_app_id）。
 *
 * 选取规则：取最新一次（按 tool.id 倒序）匹配 tool 的 result 作为锚点；deploy 比 generate
 * 更晚 → 自然胜出，不会出现两张 CTA。
 *
 * 卡片用 AgentConversation 的 #custom slot 渲染，inline 插在锚点 tool 之后。
 */
interface AppReadyInfo {
  anchorToolId: number          // CTA 卡要插在哪条 tool 之后
  appId: number | null          // ai-builder 本地 app_id
  apaasAppId: string | null     // aPaaS 平台 app_id（部署后才有）
  appName: string
  appCode: string | null
  appViewUrl: string | null     // 工具返回的 view url（若有，优先用）
  status: string | null         // 最近 deploy/generate 工具自报 status (in_progress/completed/generating…)
}
const appReadyInfo = computed<AppReadyInfo | null>(() => {
  // 跨多个 tool 合并 — 不同工具返回不同字段：
  //   - generate_app_from_doc → app_id / app_name / app_code
  //   - deploy_application    → ok / app_view_url (apaas_app_id 有时缺)
  //   - get_application       → app_name / apaas_app_id / status
  // 任一成功就触发；锚点是"最新一次成功"的 tool id（CTA 卡插它后面）。
  const tcs = toolCalls.value
  let anchorToolId: number | null = null
  let appId: number | null = null
  let apaasAppId: string | null = null
  let appName: string = ''
  let appCode: string | null = null
  let appViewUrl: string | null = null
  let toolStatus: string | null = null
  const TRIGGER_TOOLS = new Set(['generate_app_from_doc', 'deploy_application'])
  const MERGE_TOOLS = new Set(['generate_app_from_doc', 'deploy_application', 'get_application'])
  for (const tc of tcs) {
    if (!tc) continue
    if (tc.status !== 'success') continue
    if (!MERGE_TOOLS.has(tc.tool_name)) continue
    const r = _parseToolResult(tc.result_text)
    if (!r || r.ok === false) continue
    // merge fields — 后写的覆盖（保留最新），但只有非空才覆盖（不能把好数据洗掉）
    if (appId == null) {
      const aid = typeof r.app_id === 'number' ? r.app_id : (typeof r.application_id === 'number' ? r.application_id : null)
      if (aid != null) appId = aid
    }
    if (r.apaas_app_id) apaasAppId = String(r.apaas_app_id)
    if (r.app_name || r.application_name) appName = String(r.app_name || r.application_name)
    if (r.app_code) appCode = String(r.app_code)
    if (r.app_view_url) appViewUrl = String(r.app_view_url)
    if (r.status) toolStatus = String(r.status)
    // 锚点：仅 TRIGGER_TOOLS 的最后一次成功；get_application 不算锚点（避免没生成/部署只读取时弹卡）
    if (TRIGGER_TOOLS.has(tc.tool_name)) {
      anchorToolId = tc.id
    }
  }
  if (anchorToolId == null) return null
  if (!appId && !apaasAppId) return null
  return {
    anchorToolId,
    appId,
    apaasAppId,
    appName: appName || '未命名应用',
    appCode,
    appViewUrl,
    status: toolStatus,
  }
})

function openAppReady(info: AppReadyInfo) {
  // 优先用 agent 工具返回的 view url（绝对路径或 /xxx 相对路径）
  if (info.appViewUrl) {
    const localRoute = toLocalBuilderRoute(info.appViewUrl)
    if (localRoute) {
      router.push(localRoute)
      return
    }
    window.location.assign(info.appViewUrl)
    return
  }
  // fallback：用 app_id 跳 ChatPage
  if (info.appId) {
    router.push({ path: '/chat', query: { app_id: String(info.appId), from: 'aichat' } })
    return
  }
  ElMessage.warning('找不到应用入口')
}

function toLocalBuilderRoute(rawUrl: string): string | null {
  if (!rawUrl) return null
  try {
    const parsed = new URL(rawUrl, window.location.origin)
    let path = parsed.pathname || '/'
    if (path.startsWith('/ai-builder/')) path = path.slice('/ai-builder'.length)
    if (path === '/ai-builder') path = '/'
    const isBuilderInternal = path === '/chat' || path.startsWith('/chat/') || path === '/ai-chat' || path.startsWith('/ai-chat/')
    if (!isBuilderInternal && parsed.origin !== window.location.origin) return null
    return `${path}${parsed.search}${parsed.hash}`
  } catch {
    const normalized = rawUrl.startsWith('/') ? rawUrl : `/${rawUrl}`
    return normalized.replace(/^\/ai-builder(?=\/|$)/, '') || '/'
  }
}

// ─────────── 2026-05-28 一键到底：草稿建好后自动触发服务端真生成 ───────────
//
// 痛点：点「生成应用」→ agent 调 generate_app_from_doc 只建本地草稿（status:draft，
// 没碰 apaas）→ md 文档 ≠ 应用。用户还得跑到 Builder 工作台再点一次「生成应用」才真建。
//
// 修复：显式点过「生成应用」(pendingAutoGenerate=true) 后，一旦检测到草稿创建成功
// (appReadyInfo 有 appId 且还没 apaasAppId)，自动 POST /generate-run 让服务端后台真生成。
// 服务端跑（不依赖浏览器），进度可在「打开应用」后的工作台 timeline 看。
// 用 pendingAutoGenerate 门控 + appId 去重 —— 避免打开历史会话时误触发。
const pendingAutoGenerate = ref(false)
const autoGenFiredFor = ref<number | null>(null)
watch(appReadyInfo, async (info) => {
  if (!pendingAutoGenerate.value) return
  if (!info || !info.appId) return
  if (info.apaasAppId) { pendingAutoGenerate.value = false; return }  // 已在平台上，无需再生成
  if (autoGenFiredFor.value === info.appId) return
  autoGenFiredFor.value = info.appId
  pendingAutoGenerate.value = false
  try {
    const r = await applicationApi.generateRun(info.appId)
    if (r?.started) {
      ElMessage.success('已开始把应用真正生成到 apaas 平台（创建模型/表单/角色）—— 点「打开应用」看生成进度')
    } else if (r?.already_running) {
      ElMessage.info('应用正在生成中…')
    }
    // already_done：无需提示，CTA 直接打开
  } catch (e: any) {
    autoGenFiredFor.value = null  // 允许重试
    const detail = e?.response?.data?.detail || e?.message || ''
    ElMessage.warning(`自动生成未启动：${detail}（可在 Builder 工作台手动点「生成应用」）`)
  }
}, { immediate: false })

// ─────────── 2026-05-30 真实生成进度监控 ───────────
// 痛点：deploy_application 25s 超时早返 ok:true(status=in_progress)，apaas 后台还在异步
// 生成模型/表单/菜单(可能几分钟)，但 CTA 直接谎报"已就绪 + 打开应用" → 用户进去看半成品以为是 bug。
// 修：CTA 的"就绪"不信工具自报 status，改用 GET /steps/status(对比 apaas 真实已建对象 vs SPEC
// 期望)轮询判定 —— 没真完成就显"正在生成 X/M"，完成才翻成"打开应用"。
interface GenProgress {
  appId: number
  done: number
  total: number
  complete: boolean
  failed?: boolean
  errorMessage?: string
  byKind: Record<string, { done: number; total: number }>
}
const genProgress = ref<GenProgress | null>(null)
const GEN_KIND_LABEL: Record<string, string> = {
  create_model: '模型', create_form: '表单', create_menu: '菜单',
  create_role: '角色', create_dict: '字典', create_perm: '权限',
}
let genPollTimer: number | null = null
let genPollAppId: number | null = null
let genPollCount = 0
const GEN_POLL_MAX = 120  // 3s × 120 = 6min 上限，防失败步骤导致无限轮询

function stopGenPoll() {
  if (genPollTimer != null) { window.clearInterval(genPollTimer); genPollTimer = null }
}

async function pollGenProgress(appId: number) {
  genPollCount++
  if (genPollCount > GEN_POLL_MAX) { stopGenPoll(); return }
  try {
    const resp: any = await applicationApi.getStepStatus(appId)
    const steps: any[] = Array.isArray(resp?.steps) ? resp.steps : []
    if (resp?.app_status === 'failed') {
      genProgress.value = {
        appId,
        done: steps.filter((s: any) => s?.status === 'completed').length,
        total: steps.length,
        complete: false,
        failed: true,
        errorMessage: String(resp?.error_message || '应用生成失败，请检查平台连接后重试'),
        byKind: {},
      }
      stopGenPoll()
      return
    }
    if (!steps.length) {
      // 无步骤信息(config_preview 空/无 SPEC) — 没东西可等，按就绪处理。
      genProgress.value = { appId, done: 0, total: 0, complete: true, byKind: {} }
      stopGenPoll()
      return
    }
    const byKind: Record<string, { done: number; total: number }> = {}
    let done = 0
    for (const s of steps) {
      const isDone = s?.status === 'completed'
      if (isDone) done++
      const kind = String(s?.key || '').split(':')[0] || ''
      if (GEN_KIND_LABEL[kind]) {
        const b = byKind[kind] || (byKind[kind] = { done: 0, total: 0 })
        b.total++
        if (isDone) b.done++
      }
    }
    const total = steps.length
    const complete = total > 0 && done >= total
    genProgress.value = { appId, done, total, complete, byKind }
    if (complete) stopGenPoll()
  } catch {
    // 读进度失败 — 静默，下次再试(不改 genProgress)
  }
}

function startGenPoll(appId: number) {
  if (genPollAppId === appId && genPollTimer != null) return
  stopGenPoll()
  genPollAppId = appId
  genPollCount = 0
  genProgress.value = null
  pollGenProgress(appId)                                   // 立即拉一次
  genPollTimer = window.setInterval(() => pollGenProgress(appId), 3000)
}

watch(appReadyInfo, (info) => {
  if (info && info.appId) startGenPoll(info.appId)
  else { stopGenPoll(); genProgress.value = null }
}, { immediate: true })

onUnmounted(stopGenPoll)

// CTA 是否"真就绪"(权威：steps/status 全完成)。拿不到进度时保守：仅当工具自报 completed
// 且已在平台才暂信(避免对历史/已完成应用误显生成中)。
function ctaIsReady(info: AppReadyInfo): boolean {
  const gp = genProgress.value
  if (gp && gp.appId === info.appId) return gp.complete
  return info.status === 'completed' && !!info.apaasAppId
}
function ctaIsFailed(info: AppReadyInfo): boolean {
  const gp = genProgress.value
  return !!(gp && gp.appId === info.appId && gp.failed)
}
function ctaProgressText(info: AppReadyInfo): string {
  const gp = genProgress.value
  if (gp && gp.appId === info.appId && gp.failed) {
    return gp.errorMessage || '应用生成失败，请检查平台连接后重试'
  }
  if (!gp || gp.appId !== info.appId || gp.total === 0) return '正在后台生成模型 / 表单 / 菜单…'
  const parts = Object.entries(gp.byKind)
    .filter(([, b]) => b.total > 0)
    .map(([k, b]) => `${GEN_KIND_LABEL[k]} ${b.done}/${b.total}`)
  const head = `已生成 ${gp.done}/${gp.total} 步`
  return parts.length ? `${head} · ${parts.join(' · ')}` : head
}
function ctaPercent(info: AppReadyInfo): number {
  const gp = genProgress.value
  if (!gp || gp.appId !== info.appId || gp.total === 0) return 8
  return Math.max(8, Math.round((gp.done / gp.total) * 100))
}

// 把 messages + tool_calls + transient 按时间合成一条线
type TLItem =
  | { kind: 'msg'; msg: AIChatMessage }
  | { kind: 'tool'; tool: AIChatToolCall }
  | { kind: 'tool_group'; tools: AIChatToolCall[] }
  | { kind: 'ask'; ask: { question: string; options: string[]; tc_id: number } }
  | { kind: 'thinking'; text: string; ts: number }
  | { kind: 'artifact_card'; artifact: AIChatArtifact; ts: number }
  | { kind: 'streaming'; text: string }

// 把同名连续 ≥2 次的 tool calls 折叠成一个 group
// seenWriteForFile 由外层 renderTimeline 维护并跨段累计，否则每次 collapse 都从 0
// 计数 → 多个 segment 的 inline 卡片都误显示成 v1。
function collapseTools(tcs: AIChatToolCall[], seenWriteForFile: Record<string, number>): TLItem[] {
  const out: TLItem[] = []
  let i = 0
  while (i < tcs.length) {
    let j = i + 1
    while (j < tcs.length && tcs[j].tool_name === tcs[i].tool_name) j++
    if (j - i >= 2) {
      out.push({ kind: 'tool_group', tools: tcs.slice(i, j) })
    } else {
      out.push({ kind: 'tool', tool: tcs[i] })
    }
    // 如果当前段最后一条是 write_artifact 成功，紧跟一张 inline artifact card
    const last = tcs[j - 1]
    if (last && last.tool_name === 'write_artifact' && last.status === 'success') {
      const fname = last.args_json?.filename
      if (fname) {
        seenWriteForFile[fname] = (seenWriteForFile[fname] || 0) + 1
        const writeIdx = seenWriteForFile[fname]  // 1-based
        // 该 filename 所有版本按 version 升序，取第 writeIdx 个
        const versions = artifacts.value
          .filter(a => a.filename === fname)
          .sort((a, b) => a.version - b.version)
        const art = versions[writeIdx - 1] || versions[versions.length - 1]
        if (art) {
          out.push({ kind: 'artifact_card', artifact: art, ts: 0 })
        }
      }
    }
    // 如果是 ask_clarifying_question，把 result_text 里的问题/选项渲染成 ask 卡片
    // （和流式时的 transient 'ask' 视觉一致；刷新页面也能看到）
    if (last && last.tool_name === 'ask_clarifying_question' && last.status === 'success') {
      const ask = parseAskFromResult(last.result_text)
      if (ask) {
        out.push({ kind: 'ask', ask: { question: ask.question, options: ask.options, tc_id: last.id } })
      }
    }
    i = j
  }
  return out
}

function parseAskFromResult(result_text: string | null | undefined): { question: string; options: string[] } | null {
  if (!result_text) return null
  try {
    const parsed = JSON.parse(result_text)
    if (parsed && parsed._special === 'ask_user' && typeof parsed.question === 'string') {
      return { question: parsed.question, options: Array.isArray(parsed.options) ? parsed.options : [] }
    }
  } catch { /* not JSON, ignore */ }
  return null
}

// 时间戳辅助：messages 用 created_at，tool_calls 用 started_at（缺则用 id 近似）
function tsOf(s: string | null | undefined): number {
  if (!s) return 0
  const t = Date.parse(s)
  return Number.isNaN(t) ? 0 : t
}

const renderTimeline = computed<TLItem[]>(() => {
  // 按时间戳交错排列 messages 和 tool_calls，连续同名 tool_calls 会再被 collapseTools 折叠
  type Sortable =
    | { kind: 'msg'; ts: number; seq: number; msg: AIChatMessage }
    | { kind: 'tc'; ts: number; seq: number; tool: AIChatToolCall }

  const sortable: Sortable[] = []
  for (const m of messages.value) {
    sortable.push({ kind: 'msg', ts: tsOf(m.created_at), seq: m.id, msg: m })
  }
  for (const tc of toolCalls.value) {
    // 同一 turn 内 tool_calls 间隔可能 < 1ms，用 id 作为次序回退
    sortable.push({ kind: 'tc', ts: tsOf(tc.started_at), seq: tc.id, tool: tc })
  }
  sortable.sort((a, b) => {
    if (a.ts !== b.ts) return a.ts - b.ts
    // 同时间戳：msg 优先于 tc（确保用户消息在它触发的 tools 之前），再按 seq(id)
    if (a.kind !== b.kind) return a.kind === 'msg' ? -1 : 1
    return a.seq - b.seq
  })

  const items: TLItem[] = []
  let toolBuf: AIChatToolCall[] = []
  // 跨所有 segment 累计的 write_artifact 计数，让 inline 卡片版本号正确递增
  const seenWriteForFile: Record<string, number> = {}
  const flushTools = () => {
    if (!toolBuf.length) return
    for (const it of collapseTools(toolBuf, seenWriteForFile)) items.push(it)
    toolBuf = []
  }
  for (const item of sortable) {
    if (item.kind === 'tc') {
      toolBuf.push(item.tool)
    } else {
      flushTools()
      items.push({ kind: 'msg', msg: item.msg })
    }
  }
  flushTools()

  for (const t of transientItems.value) items.push(t)
  if (streamingText.value) items.push({ kind: 'streaming', text: streamingText.value })
  return items
})

// 把 renderTimeline 映射成 AgentConversation 公共消息契约
const agentMessages = computed<AgentMessage[]>(() => {
  const out: AgentMessage[] = []
  const mapStatus = (s: string): 'pending' | 'running' | 'success' | 'error' =>
    (s === 'aborted' ? 'error' : (s as any)) || 'pending'
  const mapTool = (tc: AIChatToolCall) => ({
    id: tc.id,
    name: tc.tool_name,
    args: tc.args_json,
    argsBrief: toolArgsBrief(tc),
    result: tc.result_text || undefined,
    resultSummary: summarizeToolResult(tc.tool_name, tc.status, tc.result_text) || undefined,
    status: mapStatus(tc.status),
    duration_ms: tc.duration_ms ?? undefined,
  })
  const ctaInfo = appReadyInfo.value
  for (const item of renderTimeline.value) {
    if (item.kind === 'msg' && item.msg.role === 'user') {
      const atts = userMessageAttachments(item.msg)
      out.push({
        id: 'm' + item.msg.id,
        kind: 'user',
        content: item.msg.content,
        attachments: atts.length
          ? atts.map(a => ({ id: a.id, kind: (a.kind === 'image' ? 'image' : 'file') as 'image' | 'file', filename: a.filename }))
          : undefined,
      })
    } else if (item.kind === 'msg' && item.msg.role === 'assistant') {
      if (item.msg.content) {
        out.push({
          id: 'm' + item.msg.id,
          kind: 'assistant',
          content: item.msg.content,
          meta: (item.msg as any).run_id ? { run_id: (item.msg as any).run_id } : undefined,
        })
      }
    } else if (item.kind === 'tool') {
      out.push({ id: 't' + item.tool.id, kind: 'tool', tool: mapTool(item.tool) })
      if (ctaInfo && item.tool.id === ctaInfo.anchorToolId) {
        out.push({ id: 'cta-app-ready-' + ctaInfo.anchorToolId, kind: 'custom', meta: { kind: 'app-ready', info: ctaInfo } })
      }
    } else if (item.kind === 'tool_group') {
      // 把 group 拆开成单条 tool — AgentConversation 内部按需 re-group
      // 但 AIChatPage 已经预先 collapseTools 了，这里直接传成 group 的"展开形式"
      // 让 AgentConversation 用 toolGrouping=false 时按单条渲染（连续同名也会单条显示）
      // 为了保持 group 视觉，我们手动构造一条 group：用 kind='custom' 不行，
      // 干脆把 toolGrouping 打开 → 但那要求所有同名 tool 连续才会被合并
      // AIChat 的 collapseTools 保证了 group 内 tool 是连续的，传单条 + toolGrouping=true 即可
      for (const t of item.tools) {
        out.push({ id: 't' + t.id, kind: 'tool', tool: mapTool(t) })
        if (ctaInfo && t.id === ctaInfo.anchorToolId) {
          out.push({ id: 'cta-app-ready-' + ctaInfo.anchorToolId, kind: 'custom', meta: { kind: 'app-ready', info: ctaInfo } })
        }
      }
    } else if (item.kind === 'ask') {
      out.push({
        id: 'ask' + item.ask.tc_id,
        kind: 'ask',
        ask: { question: item.ask.question, options: item.ask.options },
      })
    } else if (item.kind === 'thinking') {
      out.push({ id: 'tk' + item.ts, kind: 'thinking', thinking: { text: item.text, locked: true } })
    } else if (item.kind === 'artifact_card') {
      out.push({
        id: 'art' + item.artifact.id,
        kind: 'artifact',
        artifact: {
          id: item.artifact.id,
          filename: item.artifact.filename,
          version: item.artifact.version,
          preview: item.artifact.preview || undefined,
          raw: item.artifact,
        },
      })
    } else if (item.kind === 'streaming') {
      out.push({ id: 'streaming', kind: 'streaming', content: item.text, streaming: true })
    }
  }
  return out
})

function onAgentAnswerAsk(option: string) {
  onAnswerAsk(option)
}

// 每条回复脚注点「查看本次 trace」
function onOpenTrace(message: any) {
  const rid = message?.meta?.run_id
  if (!rid) return
  tracePreferRunId.value = rid
  traceDrawerVisible.value = true
}
// 会话头部「Agent 活动」入口（默认选最近一次 run）
function openSessionTrace() {
  tracePreferRunId.value = currentRunId.value
  traceDrawerVisible.value = true
}

const lastEventIsAsk = computed(() => {
  // 最后一次工具调用是 ask_clarifying_question success → AI 在等用户回答
  // 但前提是用户还没回答 — 如果在最后一个 ask 之后已经有新 user message，
  // 说明用户已答, agent 正在跑下一轮, 不应再显示"等用户回答"状态
  // (2026-05-21 fix: 之前的 bug 导致 typing bubble + thinkingLabel 在 ask → user
  // 答 → turn 2 LLM 调用期间不渲染, 用户看不到 "AI 正在写设计文档" 文案)
  const tcs = toolCalls.value
  const last = tcs[tcs.length - 1]
  if (!last) return false
  if (last.tool_name !== 'ask_clarifying_question' || last.status !== 'success') return false
  // 检查最后一条 message 是不是 user message (用户已回答)
  const msgs = messages.value
  const lastMsg = msgs[msgs.length - 1]
  if (lastMsg?.role === 'user') return false
  return true
})

const canSend = computed(() => !isSending.value && (!!inputText.value.trim() || pendingFiles.value.length > 0))

// 等待状态文案：随时间变化，避免用户以为断了
const thinkingLabel = computed(() => {
  const s = durationSec.value
  // 优先：LLM 正在流式生成工具参数
  const streamingTool = activeStreamingTool.value
  if (streamingTool) {
    const charsSoFar = streamingTool.argumentsSoFar.length
    // 试着抽出 filename 让用户知道在写哪个文件
    let suffix = ''
    const filenameMatch = streamingTool.argumentsSoFar.match(/"filename"\s*:\s*"([^"]+)"/)
    if (filenameMatch) suffix = `《${filenameMatch[1]}》`
    // gpt-5.5/omnigate 等 provider 不真流式 tool args — charsSoFar 卡在很小数字
    // 此时给一个更准的"在写啥"文案，让用户知道 agent 在干啥不是死了
    if (charsSoFar < 50 && streamingTool.name === 'write_artifact') {
      return `AI 正在写设计文档（约 5000+ 字 / 30-60s）…`
    }
    return `AI 正在生成 ${streamingTool.name}${suffix} 参数（已 ${charsSoFar} 字）`
  }
  // 2026-05-21: validate_builder_doc 刚跑完 + LLM 没流式 tool args = 一定是在写 write_artifact
  // gpt-5.5 类 provider 不流式 tool args, streamingTools 永远空，fallback 文案不准
  const recentTools = toolCalls.value.slice(-3)
  const justValidated = recentTools.length > 0 &&
    recentTools[recentTools.length - 1]?.tool_name === 'validate_builder_doc' &&
    recentTools[recentTools.length - 1]?.status === 'success'
  if (justValidated && s > 2) {
    return `AI 正在写设计文档（约 5000+ 字 / 30-60s）…`
  }
  // 后端正在执行某个工具
  if (toolCalls.value.some(t => t.status === 'running')) {
    const running = toolCalls.value.find(t => t.status === 'running')!
    return `正在执行 ${running.tool_name}…`
  }
  if (s < 3) return 'AI 正在思考'
  if (s < 8) return 'AI 还在生成回复，稍等'
  if (s < 20) return 'AI 在处理较复杂的内容'
  return `AI 仍在工作（${s}s），可以再等等`
})

// ── API actions ──

async function loadSessions() {
  try {
    const data = await aiChatApi.listSessions()
    sessions.value = data.sessions
  } catch (e: any) {
    console.error(e)
    ElMessage.error('拉会话列表失败')
  }
}

async function loadLlmOptions() {
  try {
    // 拉所有 purpose=builder 的可用模型；'all' 不是合法 purpose
    const opts = await llmConfigApi.listOptions('builder')
    llmOptions.value = (opts || []) as any
    selectedLlmId.value = normalizeLlmId(currentSession.value?.selected_llm_config_id ?? selectedLlmId.value)
    if (
      currentSession.value &&
      currentSession.value.selected_llm_config_id !== selectedLlmId.value
    ) {
      const updated = await aiChatApi.updateSession(currentSession.value.id, {
        selected_llm_config_id: selectedLlmId.value ?? 0,
      })
      currentSession.value.selected_llm_config_id = updated.selected_llm_config_id
    }
  } catch (e: any) {
    console.error('拉模型列表失败', e)
    llmOptions.value = []
    selectedLlmId.value = null
    ElMessage.warning(`模型列表加载失败：${e?.response?.data?.detail || e?.message || e}`)
  }
}

async function loadSession(id: number) {
  // 切到不同 session 之前，先 abort 进行中的 SSE — 否则旧 stream 的 chunk 会继续
  // 通过 handleSseEvent 写到 transientItems / streamingText，造成"新会话主区显示
  // 旧会话尾巴消息"的串会话错觉（DB 实际是干净的）。
  if (currentSession.value && currentSession.value.id !== id) {
    if (currentAbort.value) {
      try { currentAbort.value.abort() } catch { /* ignore */ }
      currentAbort.value = null
    }
    transientItems.value = []
    streamingText.value = ''
    streamingTools.value = {}
    pendingChars.value = []
    pendingFinalMessage.value = null
    stopDrain()
    isSending.value = false
    currentRunId.value = null  // 切会话清掉上个会话的 run 提示，避免「Agent 活动」带过去的陈旧 preferRunId
  }
  try {
    const data = await aiChatApi.getSession(id)
    currentSession.value = data.session
    messages.value = data.messages
    toolCalls.value = data.tool_calls
    attachments.value = data.attachments
    artifacts.value = data.artifacts
    // 只接受当前租户 options 中存在的会话模型；否则回到当前租户默认模型。
    selectedLlmId.value = normalizeLlmId(data.session.selected_llm_config_id ?? selectedLlmId.value)
    transientItems.value = []
    streamingText.value = ''
    if (route.params.id !== String(id)) {
      router.replace(`/ai-chat/${id}`)
    }
    await nextTick()
    scrollBottom()
  } catch (e) {
    console.error(e)
    currentSession.value = null
    messages.value = []
    toolCalls.value = []
    attachments.value = []
    artifacts.value = []
    selectedLlmId.value = normalizeLlmId(selectedLlmId.value)
    ElMessage.error('加载会话失败')
  }
}

async function onRenameSession(s: AIChatSession) {
  try {
    const res = await ElMessageBox.prompt('新的会话名称', '重命名', {
      inputValue: s.title,
      inputPattern: /\S+/,
      inputErrorMessage: '名称不能为空',
      confirmButtonText: '保存',
      cancelButtonText: '取消',
    }) as { value: string }
    const newTitle = res.value.trim()
    if (!newTitle || newTitle === s.title) return
    const updated = await aiChatApi.updateSession(s.id, { title: newTitle })
    s.title = updated.title
    if (currentSession.value?.id === s.id) currentSession.value.title = updated.title
  } catch (e) {
    /* user cancelled */
  }
}

async function onDeleteSession(s: AIChatSession) {
  try {
    await ElMessageBox.confirm(`确认删除会话「${s.title}」？此操作不可撤销，附件和设计文档会一并删除。`, '删除会话', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return // 用户点了取消
  }
  try {
    await aiChatApi.deleteSession(s.id)
    sessions.value = sessions.value.filter(x => x.id !== s.id)
    if (currentSession.value?.id === s.id) {
      currentSession.value = null
      messages.value = []
      toolCalls.value = []
      attachments.value = []
      artifacts.value = []
      router.replace('/ai-chat')
    }
    ElMessage.success('已删除')
  } catch (e: any) {
    console.error('删除会话失败', e)
    const detail = e?.response?.data?.detail || e?.message || String(e)
    ElMessage.error(`删除失败：${detail}`)
  }
}

async function onCreateSession(_mode?: SessionFilter | string) {
  // chat / cowork mode 已合并 — 后端字段保留但不再区分行为，统一建一个会话即可
  const s = await aiChatApi.createSession({
    selected_llm_config_id: selectedLlmId.value,
    mode: 'chat',
  })
  sessions.value.unshift(s)
  await loadSession(s.id)
}

let bootstrappingBlankSession = false
async function createBlankSessionForEntry() {
  if (currentSession.value || bootstrappingBlankSession) return
  bootstrappingBlankSession = true
  try {
    await onCreateSession()
  } finally {
    bootstrappingBlankSession = false
  }
}

// 空状态（首页 / AI Builder 融合页）就地新建：建会话 → 把首条需求/附件发出去。
// 复用 onMounted 里 Landing prompt 那套逻辑，不再靠 router.push 跳转。
async function onStartNew(payload: { prompt: string; files: File[] }) {
  if (isSending.value || currentSession.value) return
  const text = (payload?.prompt || '').trim()
  const files = payload?.files || []
  if (!text && files.length === 0) return
  try {
    const created = await aiChatApi.createSession({ selected_llm_config_id: selectedLlmId.value })
    sessions.value.unshift(created)
    await loadSession(created.id)
    if (files.length) pendingFiles.value.push(...files)
    inputText.value = text || '材料都在附件里了，请先并行读完所有附件，给我综合摘要 + 关键澄清问题。'
    router.replace({ path: `/ai-chat/${created.id}` })
    await nextTick()
    await onSend()
  } catch (e: any) {
    ElMessage.error(`创建会话失败：${e?.message || e}`)
  }
}

async function startFromIntroExample(prompt: string) {
  if (currentSession.value) {
    inputText.value = prompt
    await nextTick()
    return
  }
  await onStartNew({ prompt, files: [] })
}

async function onChangeLlm() {
  // 没当前会话：只更新本地 selectedLlmId（作为新建会话的默认模型）
  if (!currentSession.value) return
  const updated = await aiChatApi.updateSession(currentSession.value.id, { selected_llm_config_id: selectedLlmId.value ?? 0 })
  currentSession.value.selected_llm_config_id = updated.selected_llm_config_id
}

function onComposerFilesPicked(files: File[]) {
  pendingFiles.value.push(...files)
}

function removePendingFileByIndex(_: UnifiedChatAttachment, index: number) {
  pendingFiles.value.splice(index, 1)
}

// 对话界面风格：流式中可继续输入，按 Enter 进入队列等待
const pendingQueue = ref<string[]>([])

async function onSend() {
  if (!currentSession.value) return
  // 流式中按发送 → 进队列（仅文字，不带附件 — 附件场景太复杂留待后续）
  if (isSending.value) {
    const txt = inputText.value.trim()
    if (!txt) return
    pendingQueue.value.push(txt)
    inputText.value = ''
    return
  }
  if (!canSend.value) return
  const text = inputText.value.trim()
  inputText.value = ''
  if (currentSession.value.selected_llm_config_id !== selectedLlmId.value) {
    try {
      const updated = await aiChatApi.updateSession(currentSession.value.id, {
        selected_llm_config_id: selectedLlmId.value ?? 0,
      })
      currentSession.value.selected_llm_config_id = updated.selected_llm_config_id
    } catch (e: any) {
      inputText.value = text
      ElMessage.error(`切换模型失败：${e?.response?.data?.detail || e?.message || '请重新选择模型'}`)
      return
    }
  }
  // 上传附件
  let uploadedAttIds: number[] = []
  if (pendingFiles.value.length > 0) {
    try {
      const result = await aiChatApi.uploadAttachments(currentSession.value.id, pendingFiles.value)
      attachments.value.push(...result.attachments)
      uploadedAttIds = result.attachments.map(a => a.id)
      pendingFiles.value = []
    } catch (e) {
      ElMessage.error('上传附件失败')
      return
    }
  }
  // 发送
  isSending.value = true
  transientItems.value = []
  streamingText.value = ''
  streamingTools.value = {}
  pendingChars.value = []
  pendingFinalMessage.value = null
  currentTurnAssistantMessageReceived.value = false
  currentTurnFallbackErrorShown.value = false
  stopDrain()
  currentAbort.value = new AbortController()
  try {
    await aiChatApi.sendMessage(
      currentSession.value.id,
      { message: text, attachment_ids: uploadedAttIds },
      {
        signal: currentAbort.value.signal,
        onEvent: handleSseEvent,
      },
    )
  } catch (e: any) {
    if (e.name !== 'AbortError') {
      console.error(e)
      ElMessage.error(`发送失败：${e.message}`)
    }
  } finally {
    // 等队列清空（让打字动画走完）再切回非流式状态
    let waited = 0
    while (pendingChars.value.length > 0 && waited < 30000) {
      await new Promise(r => setTimeout(r, 50))
      waited += 50
    }
    stopDrain()
    pendingFinalMessage.value = null
    isSending.value = false
    currentAbort.value = null
    transientItems.value = []
    streamingText.value = ''
    currentTurnAssistantMessageReceived.value = false
    currentTurnFallbackErrorShown.value = false
    // 重新拉一次 session 拿到完整持久化数据（messages + tool_calls + artifacts）
    if (currentSession.value) await loadSession(currentSession.value.id)
    // 队列消费：上一轮跑完后，把队列里第一条自动发出去
    if (pendingQueue.value.length > 0) {
      const next = pendingQueue.value.shift()!
      inputText.value = next
      // 给 UI 一帧透气，让用户看见自动发送的过程
      await new Promise(r => setTimeout(r, 200))
      onSend()
    }
  }
}

async function onAbort() {
  if (!currentSession.value) return
  try {
    await aiChatApi.abort(currentSession.value.id)
  } catch (e) { /* ignore */ }
  currentAbort.value?.abort()
}

function handleSseEvent(eventName: string, data: any) {
  switch (eventName) {
    case 'user_message':
      messages.value.push(data)
      break
    case 'run_started':
      // agent loop 起跑：记下本次实时 run_id（会话级 trace 入口默认选中它）
      currentRunId.value = data.run_id || null
      break
    case 'thinking':
      // "使用模型 xxx" 之类元事件
      transientItems.value.push({ kind: 'thinking', text: data.text || '', ts: Date.now() })
      break
    case 'assistant_delta':
      // 流式 token：放入 pending 队列，平滑节流释放（即使 LLM 假流式也看着像真在打字）
      for (const ch of (data.text || '')) pendingChars.value.push(ch)
      ensureDrain()
      break
    case 'assistant_thinking_lock':
      // 后端通知：streamed content 是工具前的思考，锁定为 thinking transient
      flushPending()
      if (streamingText.value) {
        transientItems.value.push({ kind: 'thinking', text: streamingText.value, ts: Date.now() })
        streamingText.value = ''
      }
      break
    case 'tool_call_start': {
      // 收到第一个工具：streaming 缓冲若有内容则锁为 thinking
      flushPending()
      if (streamingText.value) {
        transientItems.value.push({ kind: 'thinking', text: streamingText.value, ts: Date.now() })
        streamingText.value = ''
      }
      // 该 tool 开始执行 → 从 streamingTools 移除（参数已生成完）
      streamingTools.value = {}
      const tc: AIChatToolCall = {
        id: data.id,
        session_id: currentSession.value?.id || 0,
        message_id: null,
        tool_name: data.tool_name,
        args_json: data.args || {},
        result_text: null,
        status: 'running',
        error_message: null,
        duration_ms: null,
        started_at: data.started_at || null,
        ended_at: null,
      }
      toolCalls.value.push(tc)
      break
    }
    case 'tool_call_delta': {
      // LLM 正在流式生成 tool_calls 的参数。把 arguments_so_far 累积到 streamingTools，
      // 让 thinkingLabel 能展示进度（"AI 正在生成 write_artifact《xxx-设计文档.md》参数（已 2543 字）"）
      const idx = data.index ?? 0
      const cur = streamingTools.value[idx] || { index: idx, name: '', argumentsSoFar: '' }
      if (data.name) cur.name = data.name
      // arguments_so_far 是后端累计的完整字符串，直接覆盖即可
      if (typeof data.arguments_so_far === 'string') cur.argumentsSoFar = data.arguments_so_far
      streamingTools.value = { ...streamingTools.value, [idx]: cur }
      break
    }
    case 'tool_call_end': {
      const found = toolCalls.value.find(t => t.id === data.id)
      if (found) {
        found.status = data.status
        found.result_text = data.result_text
        found.duration_ms = data.duration_ms
      }
      break
    }
    case 'ask_user':
      // ask 卡片改由 collapseTools 从持久化 toolCalls.result_text 渲染，避免刷新后丢失。
      // 这里只用作信号：ask_user 事件到达 = 已经在等用户回答（lastEventIsAsk 通过 toolCalls 末尾感知）
      break
    case 'assistant_message':
      // 等 drain 把 pendingChars 排空后再展示持久化消息（让打字效果走完）
      currentTurnAssistantMessageReceived.value = true
      if (pendingChars.value.length === 0) {
        streamingText.value = ''
        messages.value.push(data)
      } else {
        pendingFinalMessage.value = data
        // ensureDrain 已经在 assistant_delta 时启动；当它发现 pending 排空且有暂存消息时会自动接管
      }
      break
    case 'artifact_created': {
      // 刷新右栏 list；inline 卡片由 renderTimeline 基于 tool_calls + artifacts 自动渲染
      if (currentSession.value) {
        aiChatApi.listArtifacts(currentSession.value.id).then(d => { artifacts.value = d.artifacts })
      }
      // 不再自动弹开右栏 — 用户点 inline 卡片再看
      break
    }
    case 'session_updated':
      if (currentSession.value && data.id === currentSession.value.id) {
        currentSession.value.title = data.title
        const found = sessions.value.find(s => s.id === data.id)
        if (found) found.title = data.title
      }
      break
    case 'error':
      {
        const message = data.error || data.message || '出错了'
        if (!currentTurnAssistantMessageReceived.value && !currentTurnFallbackErrorShown.value && currentSession.value) {
          currentTurnFallbackErrorShown.value = true
          messages.value.push({
            id: -Date.now(),
            session_id: currentSession.value.id,
            role: 'assistant',
            content: message,
            extra_meta: { local_error: true },
            created_at: new Date().toISOString(),
          })
        }
        transientItems.value.push({ kind: 'thinking', text: `错误：${message}`, ts: Date.now() })
        if (automationRunning.value) addAutomationLog('error', message)
        ElMessage.error(message)
      }
      break
  }
  nextTick(scrollBottom)
}

function onAnswerAsk(option: string) {
  inputText.value = option
  onSend()
}

async function openArtifactInPanel(a: AIChatArtifact) {
  artifactsPanelOpen.value = true
  await loadArtifact(a)
}

// 同名 artifact 多版本时取最新版作为列表项
const uniqueFilenames = computed<string[]>(() => {
  const seen = new Set<string>()
  const out: string[] = []
  for (const a of artifacts.value) {
    if (!seen.has(a.filename)) { seen.add(a.filename); out.push(a.filename) }
  }
  return out
})

const latestVersionFor = (fname: string): number => {
  let v = 0
  for (const a of artifacts.value) {
    if (a.filename === fname && a.version > v) v = a.version
  }
  return v
}

async function loadArtifactByName(fname: string) {
  const latest = artifacts.value
    .filter(a => a.filename === fname)
    .sort((x, y) => y.version - x.version)[0]
  if (latest) await loadArtifact(latest)
  // 同步拉该 filename 所有历史版本（用于版本下拉切换）
  if (currentSession.value && fname) {
    try {
      const res = await aiChatApi.listArtifactVersions(currentSession.value.id, fname)
      activeArtifactVersions.value = res.versions || []
    } catch {
      activeArtifactVersions.value = []
    }
  }
}

// 当前打开 filename 的所有历史版本（按 version 降序）
const activeArtifactVersions = ref<AIChatArtifact[]>([])
// 当前展示的版本号
const activeArtifactVersion = computed(() => {
  if (!activeArtifactName.value) return 0
  // 取目前 activeArtifactContent 对应的版本号——通过 id 查 versions
  const id = activeArtifactId.value
  const found = activeArtifactVersions.value.find(v => v.id === id)
  return found?.version || activeArtifactVersions.value[0]?.version || 0
})

async function onSelectArtifactVersion(versionStr: string) {
  if (!currentSession.value || !activeArtifactName.value) return
  const v = parseInt(versionStr, 10)
  if (!Number.isFinite(v)) return
  try {
    const detail = await aiChatApi.getArtifact(
      currentSession.value.id,
      activeArtifactName.value,
      v,
    )
    activeArtifactId.value = detail.id
    activeArtifactContent.value = detail.content || ''
  } catch {
    ElMessage.error('加载历史版本失败')
  }
}

// 自动选首个 artifact 作为右栏默认显示
watch(
  [() => artifactsPanelOpen.value, () => artifacts.value.length],
  ([open, n]) => {
    if (open && n > 0 && !activeArtifactContent.value && uniqueFilenames.value[0]) {
      loadArtifactByName(uniqueFilenames.value[0])
    }
  },
)

// 已经从该会话部署过这份 md 的话，本地缓存里会有 application id
// — 用于"在 Builder 中调整"按钮的 v-if gate
const alreadyDeployedAppId = computed<number | null>(() => {
  if (!currentSession.value || !activeArtifactName.value) return null
  return getCachedAppId(currentSession.value.id, activeArtifactName.value)
})

const artifactStats = computed(() => {
  const c = activeArtifactContent.value || ''
  const lines = c ? c.split('\n').length : 0
  const chars = c.length
  return `${lines} 行 · ${chars} 字符`
})

async function loadArtifact(a: AIChatArtifact) {
  activeArtifactId.value = a.id
  activeArtifactName.value = a.filename
  try {
    const detail = await aiChatApi.getArtifact(currentSession.value!.id, a.filename)
    activeArtifactContent.value = detail.content || ''
  } catch (e) {
    ElMessage.error('加载设计文档失败')
  }
}

function copyArtifact() {
  navigator.clipboard.writeText(activeArtifactContent.value).then(() => ElMessage.success('已复制'))
}

function isMarkdownArtifact(a: AIChatArtifact): boolean {
  if (!a) return false
  if ((a.format || '').toLowerCase() === 'md') return true
  return /\.md$/i.test(a.filename || '')
}

// HTML 产物(文件名 .html/.htm 或内容以 <!doctype/<html 开头)→ 用 iframe 原样渲染,
// 不走 markdown(否则缩进 HTML 被当代码块 + 文件自带样式不生效)。
const isHtmlArtifact = computed<boolean>(() => {
  const name = (activeArtifactName.value || '').toLowerCase()
  if (/\.html?$/.test(name)) return true
  const head = (activeArtifactContent.value || '').trimStart().slice(0, 200).toLowerCase()
  return head.startsWith('<!doctype html') || head.startsWith('<html')
})

const canSendArtifactToBuilder = computed(() =>
  !!activeArtifactName.value
  && !!activeArtifactContent.value
  && /\.md$/i.test(activeArtifactName.value)
)

// localStorage 缓存：(session_id + artifact filename) → 已建 application id
// 同一个 md → Builder 重复点不再重复建应用，直接跳已有应用的 SPEC 工作台
const MD_TO_APP_CACHE_KEY = 'mdToBuilderAppMap'

function readMdToAppCache(): Record<string, number> {
  try {
    const raw = localStorage.getItem(MD_TO_APP_CACHE_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch { return {} }
}
function getCachedAppId(sessionId: number | string, filename: string): number | null {
  const map = readMdToAppCache()
  const id = map[`${sessionId}::${filename}`]
  return typeof id === 'number' && id > 0 ? id : null
}

// ── → Builder 选目标对话框 ──
// 先按推断的 app_name 调 /applications/match-by-name 拉候选，弹框让用户选「新建」或「更新到 X」
const chooseDialogVisible = ref(false)
const chooseDialogLoading = ref(false)
const chooseDialogCandidates = ref<Array<{ id: number; app_name: string; app_code: string; status: string; apaas_app_id?: string | null; updated_at?: string | null }>>([])
const chooseDialogFilename = ref('')
const chooseDialogSuggestedName = ref('')
const chooseDialogContent = ref('')
const chooseDialogSourceSessionId = ref<number | string | null>(null)

// 从 md 正文里抓 H1（## 之前的第一行 # XXX）当作应用名候选
function extractAppNameFromMarkdown(md: string): string {
  if (!md) return ''
  const m = md.match(/^\s*#\s+([^\n]+?)\s*$/m)
  if (m) return m[1].trim().slice(0, 60)
  return ''
}

// 文件名去掉扩展和"-设计文档"等后缀，作为兜底候选
function fallbackNameFromFilename(filename: string): string {
  return (filename || '')
    .replace(/\.(md|markdown)$/i, '')
    .replace(/[-_\s]*(设计文档|需求文档|设计说明|需求说明|design|spec)$/i, '')
    .trim()
}

async function openChooseDialog(filename: string, content: string, sourceSessionId?: number | string | null) {
  chooseDialogFilename.value = filename
  chooseDialogContent.value = content
  chooseDialogSourceSessionId.value = sourceSessionId ?? null
  const inferred = extractAppNameFromMarkdown(content) || fallbackNameFromFilename(filename)
  chooseDialogSuggestedName.value = inferred
  chooseDialogCandidates.value = []
  chooseDialogVisible.value = true
  if (!inferred) return  // 无候选关键词 → 弹框只提供「新建」按钮
  chooseDialogLoading.value = true
  try {
    chooseDialogCandidates.value = await applicationApi.matchByName(inferred, 5)
  } catch (e) {
    console.warn('match-by-name failed', e)
    chooseDialogCandidates.value = []
  } finally {
    chooseDialogLoading.value = false
  }
}

// 用户选「新建」→ 走原 pendingMarkdown 通道
function handleChooseNew() {
  previewStore.pendingMarkdown = {
    filename: chooseDialogFilename.value,
    content: chooseDialogContent.value,
    sourceSessionId: chooseDialogSourceSessionId.value,
  }
  ElMessage.success('已发送，正在打开 Builder 创建新应用...')
  router.push({ path: '/chat', query: { from: 'aichat' } })
}

// 用户选「更新到 X」→ 走 pendingDocUpdate 通道，并回写本地 dedup cache
function handleChooseUpdate(appId: number, appName: string) {
  previewStore.pendingDocUpdate = {
    appId,
    filename: chooseDialogFilename.value,
    content: chooseDialogContent.value,
    sourceSessionId: chooseDialogSourceSessionId.value,
  }
  // 同 source 下次再点 → Builder 直接进这个 app，不再弹框
  if (chooseDialogSourceSessionId.value) {
    try {
      const raw = localStorage.getItem(MD_TO_APP_CACHE_KEY)
      const map = raw ? JSON.parse(raw) : {}
      map[`${chooseDialogSourceSessionId.value}::${chooseDialogFilename.value}`] = appId
      localStorage.setItem(MD_TO_APP_CACHE_KEY, JSON.stringify(map))
    } catch { /* ignore */ }
  }
  ElMessage.success(`正在打开 Builder 更新「${appName}」...`)
  router.push({ path: '/chat', query: { app_id: String(appId), from: 'aichat' } })
}

function onChooseDialogConfirm(payload: { mode: 'new' } | { mode: 'update'; appId: number; appName: string }) {
  if (payload.mode === 'new') handleChooseNew()
  else handleChooseUpdate(payload.appId, payload.appName)
}

// 在 chatbox 注入一条"生成应用"命令，让 agent 调 generate_app_from_doc 工具
// 取代过时的"切到 AI 需求分析菜单"引导。
async function sendGenerateAppMessage() {
  if (!canSendArtifactToBuilder.value || isSending.value) return
  if (!activeArtifactName.value) return
  // 一键到底：标记"本次点击后要自动把草稿真生成到 apaas"。
  // 只有显式点了「生成应用」才置 true —— 避免打开历史会话时 appReadyInfo 重算误触发生成。
  pendingAutoGenerate.value = true
  inputText.value = `请基于《${activeArtifactName.value}》调用 generate_app_from_doc 工具直接生成应用，生成完告诉我 app_id。`
  await nextTick()
  await onSend()
}

function automationNow(): string {
  return new Date().toLocaleTimeString('zh-CN', { hour12: false })
}

function addAutomationLog(level: AutomationLogLevel, text: string) {
  automationLogs.value.push({ ts: automationNow(), level, text })
  if (automationLogs.value.length > 240) automationLogs.value.splice(0, automationLogs.value.length - 240)
}

function automationDelay(ms: number) {
  return new Promise<void>((resolve) => window.setTimeout(resolve, ms))
}

function automationArtifactKey(artifact: AIChatArtifact): string {
  return `${artifact.id}:${artifact.filename}:${artifact.version}`
}

async function waitForAutomationStep(
  label: string,
  predicate: () => boolean,
  timeoutMs = 180000,
  intervalMs = 500,
) {
  const startedAt = Date.now()
  while (!predicate()) {
    if (automationStopRequested.value) throw new Error('脚本已停止')
    if (Date.now() - startedAt > timeoutMs) throw new Error(`${label}超时`)
    await automationDelay(intervalMs)
  }
}

async function runAutomationScript() {
  if (automationRunning.value) return
  const prompt = automationPrompt.value.trim()
  if (!prompt) {
    ElMessage.warning('请先填写脚本需求')
    return
  }
  automationPanelOpen.value = true
  automationRunning.value = true
  automationStopRequested.value = false
  const initialArtifactCount = artifacts.value.length
  const initialArtifactKeys = new Set(artifacts.value.map(automationArtifactKey))
  const findNewArtifact = () => artifacts.value.find(a => !initialArtifactKeys.has(automationArtifactKey(a)))
  try {
    addAutomationLog('info', '开始执行创建应用脚本')
    await waitForAutomationStep('等待上一轮回复结束', () => !isSending.value, 300000)
    if (currentSession.value) {
      addAutomationLog('info', `复用当前会话 #${currentSession.value.id} 发送需求`)
      inputText.value = prompt
      await nextTick()
      await onSend()
    } else {
      addAutomationLog('info', '创建新会话并发送需求')
      await onStartNew({ prompt, files: [] })
    }

    addAutomationLog('info', '等待设计文档或 app_id 返回')
    await waitForAutomationStep(
      '等待设计文档生成',
      () => !!appReadyInfo.value || !!findNewArtifact() || (initialArtifactCount === 0 && uniqueFilenames.value.length > 0),
      360000,
    )

    if (!appReadyInfo.value) {
      artifactsPanelOpen.value = true
      await nextTick()
      const filename = findNewArtifact()?.filename || uniqueFilenames.value[0]
      if (!filename) throw new Error('没有检测到可用于生成应用的设计文档')
      addAutomationLog('info', `打开设计文档：${filename}`)
      await loadArtifactByName(filename)
      await waitForAutomationStep('等待设计文档载入', () => !!activeArtifactName.value && !!activeArtifactContent.value, 60000)
      await waitForAutomationStep('等待对话空闲', () => !isSending.value, 300000)
      addAutomationLog('info', `触发生成应用：${activeArtifactName.value}`)
      await sendGenerateAppMessage()
    }

    await waitForAutomationStep(
      '等待应用生成结果',
      () => !!appReadyInfo.value?.appId || !!appReadyInfo.value?.apaasAppId,
      360000,
    )
    const info = appReadyInfo.value
    addAutomationLog('info', `已拿到应用信息：${info?.appName || '未命名应用'}${info?.appId ? ` app_id=${info.appId}` : ''}`)

    if (info?.appId) {
      addAutomationLog('info', '等待真实生成步骤完成')
      await waitForAutomationStep(
        '等待真实生成步骤完成',
        () => {
          const gp = genProgress.value
          return !!gp && gp.appId === info.appId && (gp.complete || !!gp.failed)
        },
        480000,
        1000,
      )
      const gp = genProgress.value
      if (gp?.failed) throw new Error(gp.errorMessage || '应用生成失败')
      addAutomationLog('info', `真实生成完成：${gp?.done ?? 0}/${gp?.total ?? 0}`)
    }

    addAutomationLog('info', '脚本执行完成')
    ElMessage.success('脚本执行完成')
  } catch (e: any) {
    const message = e?.message || String(e)
    if (message === '脚本已停止') {
      addAutomationLog('warn', '脚本已停止')
      ElMessage.info('脚本已停止')
    } else {
      addAutomationLog('error', message)
      ElMessage.error(`脚本执行失败：${message}`)
    }
  } finally {
    automationRunning.value = false
    automationStopRequested.value = false
  }
}

async function stopAutomationScript() {
  if (!automationRunning.value) return
  automationStopRequested.value = true
  addAutomationLog('warn', '正在停止脚本')
  if (isSending.value) await onAbort()
}

function clearAutomationLogs() {
  automationLogs.value = []
}

async function copyAutomationLogs() {
  const text = automationLogs.value.map(l => `[${l.ts}] ${l.level.toUpperCase()} ${l.text}`).join('\n')
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('日志已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选中日志内容')
  }
}

watch(automationPrompt, (value) => {
  try { localStorage.setItem(AUTOMATION_PROMPT_KEY, value) }
  catch { /* ignore */ }
})

watch(
  () => toolCalls.value.map(t => `${t.id}:${t.tool_name}:${t.status}:${t.duration_ms ?? ''}`).join('|'),
  () => {
    if (!automationRunning.value) return
    const latest = toolCalls.value[toolCalls.value.length - 1]
    if (!latest) return
    const resultBrief = summarizeToolResult(latest.tool_name, latest.status, latest.result_text)
    const statusText = latest.status === 'running' ? '执行中' : latest.status
    addAutomationLog('info', `工具 ${latest.tool_name} ${statusText}${resultBrief ? `：${resultBrief}` : ''}`)
  },
)

watch(appReadyInfo, (info) => {
  if (!automationRunning.value || !info) return
  addAutomationLog('info', `应用信息更新：${info.appName}${info.appId ? ` app_id=${info.appId}` : ''}${info.apaasAppId ? ` apaas_app_id=${info.apaasAppId}` : ''}`)
})

watch(
  () => {
    const gp = genProgress.value
    return gp ? `${gp.appId}:${gp.done}:${gp.total}:${gp.complete}:${gp.failed || false}` : ''
  },
  () => {
    if (!automationRunning.value) return
    const gp = genProgress.value
    if (!gp) return
    if (gp.failed) {
      addAutomationLog('error', gp.errorMessage || '应用生成失败')
      return
    }
    addAutomationLog('info', `生成进度 ${gp.done}/${gp.total}${gp.complete ? '，已完成' : ''}`)
  },
)

// 把右侧当前打开的设计文档送到 Builder：先弹"新建/更新"选目标对话框
async function sendArtifactToBuilder() {
  if (!canSendArtifactToBuilder.value) return
  // 已建过同名 → 直接跳应用，不重复 upload（保持原 dedup 行为）
  if (currentSession.value) {
    const cachedId = getCachedAppId(currentSession.value.id, activeArtifactName.value)
    if (cachedId) {
      ElMessage.success('已找到此设计文档对应的应用，正在打开...')
      await router.push({ path: '/chat', query: { app_id: String(cachedId), from: 'aichat' } })
      return
    }
  }
  await openChooseDialog(
    activeArtifactName.value,
    activeArtifactContent.value,
    currentSession.value?.id,
  )
}

// inline 卡片的"→ Builder"：拿对应文件最新版本内容，再走选目标对话框
async function sendArtifactToBuilderByName(filename: string) {
  if (!currentSession.value) return
  const cachedId = getCachedAppId(currentSession.value.id, filename)
  if (cachedId) {
    ElMessage.success('已找到此设计文档对应的应用，正在打开...')
    await router.push({ path: '/chat', query: { app_id: String(cachedId), from: 'aichat' } })
    return
  }
  try {
    const detail = await aiChatApi.getArtifact(currentSession.value.id, filename)
    if (!detail.content) {
      ElMessage.warning('设计文档为空')
      return
    }
    await openChooseDialog(filename, detail.content, currentSession.value.id)
  } catch (e) {
    console.error(e)
    ElMessage.error('加载设计文档失败')
  }
}

function downloadArtifact() {
  const blob = new Blob([activeArtifactContent.value], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = activeArtifactName.value
  a.click()
  URL.revokeObjectURL(url)
}

function scrollBottom() {
  const el = messagesRef.value
  if (el) el.scrollTop = el.scrollHeight
}

// ── Lifecycle ──

// 兼容旧 SFC template 中的 isEmbeddedAppChat 引用（AI-Builder 应用调整改抽屉嵌入，
// 不再走 ai-chat 跳转方案，这里永远 false）
const isEmbeddedAppChat = computed(() => false)

// 2026-05-21 修 KeepAlive singleton 的副作用：/ai-chat/12 ↔ /ai-chat/14
// 切换不再触发 component remount（共享 cache entry），所以要 watch route
// param 主动 loadSession 否则切 session 不刷新内容。
// onMounted 那次会先跑，watch 用 flush:'post' + 跳过初次 trigger 避免重复。
watch(
  () => route.params.id,
  async (newId, oldId) => {
    if (newId === oldId) return
    const id = newId ? Number(newId) : null
    if (id && currentSession.value?.id !== id) {
      await loadSession(id)
    }
  },
)

watch(
  () => userStore.tenantId,
  async (newTenantId, oldTenantId) => {
    if (!oldTenantId || newTenantId === oldTenantId) return
    if (currentAbort.value) {
      try { currentAbort.value.abort() } catch { /* ignore */ }
      currentAbort.value = null
    }
    resetChatTenantState()
    await Promise.all([loadLlmOptions(), loadSessions()])
    if (route.path.startsWith('/ai-chat')) {
      await router.replace('/ai-chat')
      await createBlankSessionForEntry()
    }
  },
)

onMounted(async () => {
  await Promise.all([loadSessions(), loadLlmOptions()])


  const idParam = route.params.id ? Number(route.params.id) : null
  if (idParam) {
    await loadSession(idParam)
  }
  // 从 AI Builder 各处「二次开发」入口结构化交接：读 sessionStorage，在应用上下文里发起开发。
  // 落点从旧的 /coding 改到这里 —— AIChatPage 的 agent 已有 coding 工具(create_dev_workspace 等)。
  const appDevRaw = route.query.app_dev === '1' ? sessionStorage.getItem('ai_builder_pending_app_dev') : null
  if (!currentSession.value && appDevRaw) {
    sessionStorage.removeItem('ai_builder_pending_app_dev')
    try {
      const payload = JSON.parse(appDevRaw) as { message?: string }
      const created = await aiChatApi.createSession({ selected_llm_config_id: selectedLlmId.value })
      sessions.value.unshift(created)
      await loadSession(created.id)
      inputText.value = (payload.message || '').trim()
        || '我要在这个应用上做二次开发，请先读它的结构再问我具体要做什么。'
      router.replace({ path: `/ai-chat/${created.id}` })
      await nextTick()
      onSend()
    } catch (e) {
      console.error('AI Builder 二次开发交接失败', e)
      ElMessage.error('进入二次开发失败')
    }
    return
  }

  // 从 Landing 页带过来的首条 prompt + 可选附件：建会话 → 上传附件 → 把 prompt 发出去
  const incomingPrompt = typeof route.query.prompt === 'string' ? route.query.prompt.trim() : ''
  const incomingFiles = (previewStore.pendingAiChatFiles || []).slice()
  if (!currentSession.value && (incomingPrompt || incomingFiles.length)) {
    try {
      const created = await aiChatApi.createSession({
        selected_llm_config_id: selectedLlmId.value,
      })
      sessions.value.unshift(created)
      await loadSession(created.id)
      // 把 Landing 带过来的附件搬进 pendingFiles，让 onSend 一并处理
      if (incomingFiles.length) {
        pendingFiles.value.push(...incomingFiles)
        previewStore.pendingAiChatFiles = []
      }
      // 有附件无 prompt → 给 agent 一句默认开场（让它并行读附件 + 给综合摘要）
      // 这是统一 prompt 后的自适应行为，不再依赖 mode 字段
      if (!incomingPrompt && pendingFiles.value.length) {
        inputText.value = '材料都在附件里了，请先并行读完所有附件，给我综合摘要 + 关键澄清问题。'
      } else {
        inputText.value = incomingPrompt
      }
      // 清掉 query 防止刷新时再发一次
      router.replace({ path: `/ai-chat/${created.id}` })
      await nextTick()
      // 没文字也允许发：onSend 内部会把附件 upload 当成首条消息上下文
      if (inputText.value || pendingFiles.value.length) onSend()
    } catch (e) {
      console.error('从 Landing 进入 AI Chat 失败', e)
      ElMessage.error('创建会话失败')
    }
    return
  }

  if (!currentSession.value) {
    try {
      await createBlankSessionForEntry()
    } catch (e) {
      console.error('创建入口新会话失败', e)
      ElMessage.error('创建新会话失败')
    }
  }
})
</script>

<style scoped>
/* AI Chat 主题色映射 — 通过 v-bind 注入 .theme-dark / .theme-light class 来切换。
   品牌色统一用全局 --t-brand 跟随。 */
.ai-chat-app {
  --ac-brand: var(--brand, var(--t-brand, #1D4ED8));
  --ac-brand-soft: color-mix(in srgb, var(--ac-brand) 16%, transparent);
  --ac-brand-glow: color-mix(in srgb, var(--ac-brand) 20%, transparent);

  display: grid;
  grid-template-columns: 240px 1fr auto;  /* 右栏 auto 自适应：无内容时 0 宽 */
  flex: 1;
  min-width: 0;
  min-height: 0;
  height: 100%;
  background: var(--ac-bg);
  color: var(--ac-text);
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
  font-size: 14px;
  line-height: 1.6;
  transition: grid-template-columns 0.18s ease;
}
.ai-chat-app.aside-collapsed {
  grid-template-columns: 44px 1fr auto;
}
/* 嵌入模式（应用对话调整 iframe）：隐藏 sidebar，主区铺满 */
.ai-chat-app.is-embedded {
  grid-template-columns: 1fr auto;
  height: 100%;
}
.ai-chat-shell-host {
  display: contents;
}

.ai-chat-app.theme-dark {
  --ac-bg: #0a0a0c;
  --ac-panel: #111114;
  --ac-input: #16171b;
  --ac-btn: #1d1e23;
  --ac-text: #e8eaed;
  --ac-text-mute: #a1a4ad;
  --ac-text-faint: #6c707a;
  --ac-border: rgba(255, 255, 255, 0.06);
  --ac-border-faint: rgba(255, 255, 255, 0.04);
  --ac-border-strong: rgba(255, 255, 255, 0.10);
}

/* 浅色主题：工作室风格（off-white 主调 + 清晰分层 + 品牌蓝点缀），
   不直接套全局淡蓝，避免变成"通用浅色"没有质感 */
.ai-chat-app.theme-light {
  --ac-bg: #f7f8fa;             /* 主背景 — 微暖灰白 */
  --ac-panel: #ffffff;          /* 侧栏/卡片 */
  --ac-input: #f1f3f6;          /* 输入框/二级背景 */
  --ac-btn: #ffffff;            /* 按钮基底 */
  --ac-text: #0f172a;           /* slate-900，正文最深 */
  --ac-text-mute: #475569;      /* slate-600，次级文字保持可读 */
  --ac-text-faint: #64748b;     /* slate-500，提示文字也不至于看不清 */
  --ac-border: rgba(15, 23, 42, 0.10);
  --ac-border-faint: rgba(15, 23, 42, 0.05);
  --ac-border-strong: rgba(15, 23, 42, 0.18);
}
/* .aside-right 宽度由 inline style + 拖拽控制；最小宽度交给 JS clamp 处理 */

/* artifacts toggle 按钮 */
.apply-md-btn {
  appearance: none;
  border: 0;
  height: 30px;
  padding: 0 14px;
  border-radius: 7px;
  background: var(--ac-brand);
  color: #fff;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.15s;
}
.apply-md-btn:hover:not(:disabled) {
  background: color-mix(in srgb, var(--ac-brand) 88%, black);
}
.apply-md-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.back-app-btn {
  appearance: none;
  background: var(--ac-input);
  border: 1px solid var(--ac-border-strong);
  color: var(--ac-text-mute);
  padding: 5px 12px;
  border-radius: 6px;
  font-size: 12.5px;
  cursor: pointer;
  white-space: nowrap;
}
.back-app-btn:hover {
  color: var(--ac-text);
}

.artifacts-toggle {
  appearance: none;
  background: var(--ac-input);
  border: 1px solid var(--ac-border-strong);
  color: var(--ac-text-mute);
  padding: 5px 12px;
  min-height: 32px;
  border-radius: 6px;
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  transition: all 0.15s;
}
.artifacts-toggle:hover { color: var(--ac-text); border-color: var(--ac-border-strong); }
/* AppIcon 的 .app-icon 撞上全局 builder.css 的 .app-icon(app 磁贴 36×36)→ 图标被撑到 36px,
   按钮被顶到 48px。这里把它收回内联图标尺寸(贴着 14px svg), 按钮才回到 32px 跟另俩齐。 */
.artifacts-toggle :deep(.app-icon) { width: auto; height: auto; border-radius: 0; }
.artifacts-toggle.active {
  background: color-mix(in srgb, var(--ac-brand) 12%, transparent);
  border-color: color-mix(in srgb, var(--ac-brand) 50%, transparent);
  color: var(--ac-text);
}
.artifacts-toggle .badge {
  background: var(--ac-border-strong);
  padding: 1px 7px;
  border-radius: 9px;
  font-size: 11px;
  font-family: ui-monospace, Menlo, monospace;
}
.trace-entry-btn {
  appearance: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  background: var(--ac-input);
  border: 1px solid var(--ac-border-strong);
  color: var(--ac-text-mute);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
}
.trace-entry-btn:hover { color: var(--ac-text); border-color: var(--ac-border-strong); }
.automation-toggle {
  appearance: none;
  background: var(--ac-input);
  border: 1px solid var(--ac-border-strong);
  color: var(--ac-text-mute);
  padding: 5px 12px;
  border-radius: 6px;
  font-size: 12.5px;
  cursor: pointer;
  transition: all 0.15s;
  min-height: 32px;
  font-weight: 500;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.automation-toggle:hover {
  color: var(--ac-text);
  border-color: var(--ac-border-strong);
}
.automation-toggle.active {
  color: var(--ac-text);
  border-color: color-mix(in srgb, #0f9f8f 52%, transparent);
  background: color-mix(in srgb, #0f9f8f 12%, var(--ac-input));
}
.automation-toggle.running {
  color: #0f9f8f;
  border-color: color-mix(in srgb, #0f9f8f 60%, transparent);
}

.automation-panel {
  position: fixed;
  right: 22px;
  bottom: 22px;
  z-index: 40;
  width: min(440px, calc(100vw - 44px));
  max-height: min(680px, calc(100dvh - 44px));
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px;
  border: 1px solid var(--ac-border-strong);
  border-radius: 8px;
  background: color-mix(in srgb, var(--ac-panel) 94%, #ffffff);
  box-shadow: 0 18px 48px rgba(15, 23, 42, 0.24);
}
.theme-dark .automation-panel {
  background: color-mix(in srgb, var(--ac-input) 92%, #0f172a);
  box-shadow: 0 20px 54px rgba(0, 0, 0, 0.42);
}
.automation-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.automation-title {
  color: var(--ac-text);
  font-size: 13px;
  font-weight: 800;
  line-height: 1.3;
}
.automation-subtitle {
  margin-top: 3px;
  color: var(--ac-text-faint);
  font-size: 12px;
  line-height: 1.45;
}
.automation-icon-btn {
  width: 30px;
  height: 30px;
  border-radius: 6px;
  border: 1px solid var(--ac-border);
  background: transparent;
  color: var(--ac-text-mute);
  cursor: pointer;
  font-size: 18px;
  line-height: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.automation-icon-btn:hover {
  color: var(--ac-text);
  background: var(--ac-border-faint);
}
.automation-textarea {
  width: 100%;
  min-height: 138px;
  max-height: 220px;
  resize: vertical;
  border: 1px solid var(--ac-border);
  border-radius: 7px;
  background: var(--ac-input);
  color: var(--ac-text);
  padding: 10px 11px;
  font-family: inherit;
  font-size: 12.5px;
  line-height: 1.65;
  outline: none;
}
.automation-textarea:focus {
  border-color: color-mix(in srgb, var(--ac-brand) 48%, transparent);
}
.automation-textarea:disabled {
  opacity: 0.72;
  cursor: not-allowed;
}
.automation-actions {
  display: grid;
  grid-template-columns: minmax(0, 1fr) repeat(3, auto);
  gap: 8px;
  align-items: center;
}
.automation-primary,
.automation-secondary {
  min-height: 34px;
  border-radius: 6px;
  font-size: 12.5px;
  font-weight: 750;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s;
}
.automation-primary {
  border: 1px solid color-mix(in srgb, #0f9f8f 65%, transparent);
  background: #0f9f8f;
  color: #fff;
  padding: 0 13px;
}
.automation-primary:hover:not(:disabled) {
  background: color-mix(in srgb, #0f9f8f 88%, #0f172a);
}
.automation-secondary {
  border: 1px solid var(--ac-border);
  background: transparent;
  color: var(--ac-text-mute);
  padding: 0 10px;
}
.automation-secondary:hover:not(:disabled) {
  color: var(--ac-text);
  background: var(--ac-border-faint);
}
.automation-primary:disabled,
.automation-secondary:disabled {
  opacity: 0.48;
  cursor: not-allowed;
}
.automation-logs {
  min-height: 132px;
  max-height: 260px;
  overflow-y: auto;
  border: 1px solid var(--ac-border);
  border-radius: 7px;
  background: color-mix(in srgb, var(--ac-bg) 72%, transparent);
  padding: 8px;
}
.automation-log-empty {
  color: var(--ac-text-faint);
  font-size: 12px;
  line-height: 1.6;
  padding: 4px 2px;
}
.automation-log-row {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  gap: 8px;
  padding: 5px 4px;
  border-radius: 5px;
  color: var(--ac-text-mute);
  font-size: 12px;
  line-height: 1.45;
}
.automation-log-row + .automation-log-row {
  margin-top: 1px;
}
.automation-log-row.level-warn {
  color: #c2630b;
  background: rgba(245, 158, 11, 0.08);
}
.automation-log-row.level-error {
  color: #dc2626;
  background: rgba(220, 38, 38, 0.08);
}
.automation-log-time {
  font-family: ui-monospace, Menlo, monospace;
  color: var(--ac-text-faint);
}
.automation-log-text {
  min-width: 0;
  overflow-wrap: anywhere;
}

/* 输入框底部工具栏（模型选择 + 提示） */
.input-foot {
  padding: 6px 10px 4px;
  display: flex;
  align-items: center;
  gap: 8px;
  border-top: 1px solid rgba(255, 255, 255, 0.04);
  margin-top: 4px;
}
.model-select-inline {
  background: transparent;
  border: 1px solid var(--ac-border);
  color: var(--ac-text-mute);
  padding: 3px 8px;
  border-radius: 5px;
  font-size: 12px;
  cursor: pointer;
  outline: none;
}
.model-select-inline:hover { border-color: var(--ac-border-strong); color: var(--ac-text); }
.input-foot .hint { color: var(--ac-text-faint); font-size: 11.5px; }
/* 2026-05-21 UI audit Fix 12: 模型说明字号 11.5 → 12.5px / faint → mute / 加 ⓘ icon */
.input-foot .hint-info {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--ac-text-mute);
  font-size: 12.5px;
  cursor: help;
}
.input-foot .hint-info-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 13px;
  height: 13px;
  border-radius: 50%;
  font-size: 11px;
  font-weight: 600;
  color: var(--ac-text-faint);
  opacity: 0.9;
}
.input-foot .hint-info:hover .hint-info-icon {
  color: var(--ac-brand);
  opacity: 1;
}
.input-foot .timer { color: var(--ac-brand); }

.header-mode-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 10px;
  margin-right: 8px;
  vertical-align: middle;
  letter-spacing: 0.3px;
}
.header-mode-badge .el-icon {
  font-size: 12px;
}
.header-mode-badge.cowork {
  background: color-mix(in srgb, #f59e0b 18%, transparent);
  color: #c2630b;
  border: 1px solid color-mix(in srgb, #f59e0b 30%, transparent);
}
.header-mode-badge.chat {
  background: color-mix(in srgb, var(--ac-brand) 14%, transparent);
  color: var(--ac-brand);
  border: 1px solid color-mix(in srgb, var(--ac-brand) 28%, transparent);
}
.welcome-icon {
  vertical-align: -3px;
  margin-right: 4px;
  color: #c2630b;
}
.art-version-select {
  appearance: none;
  background: var(--ac-btn);
  border: 1px solid var(--ac-border);
  color: var(--ac-text);
  font-size: 12px;
  padding: 3px 22px 3px 8px;
  border-radius: 5px;
  cursor: pointer;
  font-family: ui-monospace, Menlo, monospace;
  background-image: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 10 10"><path d="M2 4 L5 7 L8 4" stroke="%23999" stroke-width="1.4" fill="none" stroke-linecap="round"/></svg>');
  background-repeat: no-repeat;
  background-position: right 6px center;
}
.art-version-select:hover { border-color: var(--ac-border-strong); }
/* ─── Chat main ─── */
.chat-main { display: flex; flex-direction: column; overflow: hidden; min-width: 0; min-height: 0; }
.ai-chat-app :deep(.new-btn) {
  height: 36px;
  border-color: color-mix(in srgb, var(--ac-brand) 16%, var(--ac-border));
  background: color-mix(in srgb, var(--ac-brand) 5%, var(--ac-panel));
  color: var(--ac-text);
  font-size: 13px;
  font-weight: 750;
  box-shadow: none;
}
.ai-chat-app :deep(.new-btn:hover) {
  border-color: color-mix(in srgb, var(--ac-brand) 28%, var(--ac-border));
  background: color-mix(in srgb, var(--ac-brand) 8%, var(--ac-panel));
  color: var(--ac-text);
}
.ai-chat-app :deep(.session-sidebar.is-empty .empty-hint) {
  padding-top: 58px;
  color: #94a3b8;
  font-size: 18px;
  text-align: center;
}
.chat-header {
  padding: 12px 24px; border-bottom: 1px solid var(--ac-border);
  display: flex; align-items: center; justify-content: space-between;
}
.chat-title { font-size: 14px; font-weight: 650; }
.title-placeholder { color: var(--ac-text-mute); }
.title-input {
  background: var(--ac-input); border: 1px solid var(--ac-border-strong); color: var(--ac-text);
  padding: 4px 10px; border-radius: 4px; outline: none; font-size: 14px; min-width: 280px;
}
.header-actions { display: flex; align-items: center; gap: 12px; }
.model-select {
  background: var(--ac-input); border: 1px solid var(--ac-border); color: var(--ac-text);
  padding: 5px 10px; border-radius: 4px; font-size: 12.5px; cursor: pointer; outline: none;
}
.model-select:disabled { opacity: 0.4; }

.messages { flex: 1; overflow-y: auto; padding: 24px 0; }
.welcome { width: min(100%, 900px); margin: 0 auto; padding: 72px 24px 40px; display: flex; flex-direction: column; align-items: stretch; justify-content: flex-start; min-height: 100%; color: var(--ac-text-mute); }
.welcome-in-conversation {
  width: min(100%, 880px);
  min-height: auto;
  padding: 46px 0 18px;
}
.welcome-hero { text-align: left; margin: 0 auto 26px; width: min(100%, 880px); }
.welcome-badge { display: inline-flex; align-items: center; gap: 7px; height: 38px; padding: 0 15px; border-radius: 999px; background: var(--ai-soft); color: var(--ai-text); font-weight: 700; font-size: 13px; border: 1px solid var(--ai-soft-2); margin-bottom: 18px; }
.welcome-title { max-width: 820px; font-size: 32px; font-weight: 750; color: var(--ac-text); line-height: 1.24; letter-spacing: 0; margin: 0 0 14px; word-break: break-word; }
.welcome-title .hl { font-weight: 750; color: var(--ac-brand); }
.welcome-sub { font-size: 14px; color: var(--ac-text-mute); max-width: 760px; margin: 0; line-height: 1.7; }
.welcome-examples {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  width: min(100%, 880px);
  margin: 16px auto 0;
}
.welcome-example {
  min-width: 0;
  min-height: 76px;
  padding: 13px 14px;
  border-radius: 8px;
  border: 1px solid var(--ac-border);
  background: color-mix(in srgb, var(--ac-panel) 86%, transparent);
  color: var(--ac-text-mute);
  text-align: left;
  font: inherit;
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease, transform 0.15s ease;
}
.welcome-example:hover {
  border-color: color-mix(in srgb, var(--ac-brand) 38%, var(--ac-border));
  background: color-mix(in srgb, var(--ac-brand) 5%, var(--ac-panel));
  transform: translateY(-1px);
}
.welcome-example:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--ac-brand) 45%, transparent);
  outline-offset: 2px;
}
.welcome-example-title {
  display: block;
  color: var(--ac-text);
  font-size: 13px;
  font-weight: 750;
  line-height: 1.35;
}
.welcome-example-text {
  display: block;
  margin-top: 5px;
  color: var(--ac-text-faint);
  font-size: 12px;
  line-height: 1.45;
}
.welcome-capabilities {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  width: min(100%, 880px);
  margin: 22px auto 0;
}
.welcome-capabilities span {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 34px;
  padding: 0 12px;
  border-radius: 8px;
  border: 1px solid var(--ac-border);
  background: color-mix(in srgb, var(--ac-panel) 78%, transparent);
  color: var(--ac-text-mute);
  font-size: 12px;
  font-weight: 700;
}
.welcome-capabilities i {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: #0f9f8f;
}
.ai-chat-app :deep(.ac-empty) {
  align-items: flex-start;
  justify-content: center;
  padding: 28px 22px 36px;
}

@media (max-width: 1280px) {
  .welcome { width: min(100%, 680px); padding-top: 58px; }
  .welcome-in-conversation { width: min(100%, 680px); padding-top: 34px; }
  .welcome-title { font-size: 26px; max-width: 560px; line-height: 1.3; }
  .welcome-sub { max-width: 600px; }
  .welcome-examples { grid-template-columns: 1fr; width: min(100%, 680px); }
  .welcome-example { min-height: 64px; }
}

@media (max-width: 720px) {
  .chat-header {
    padding: 10px 14px;
    gap: 10px;
  }
  .header-actions {
    gap: 8px;
  }
  .automation-toggle,
  .artifacts-toggle {
    min-height: 34px;
    padding: 5px 9px;
    font-size: 12px;
  }
  .automation-panel {
    left: 10px;
    right: 10px;
    bottom: 10px;
    width: auto;
    max-height: calc(100dvh - 20px);
  }
  .automation-actions {
    grid-template-columns: 1fr 1fr;
  }
  .automation-primary {
    grid-column: 1 / -1;
  }
  .automation-logs {
    max-height: 220px;
  }
}

.timeline-item { max-width: 760px; margin: 0 auto 18px; padding: 0 24px; }
.msg.user { display: flex; justify-content: flex-end; }
.msg.user .bubble {
  background: var(--ac-input); border: 1px solid var(--ac-border); border-radius: 12px;
  padding: 12px 16px; max-width: 85%; width: fit-content;
  color: var(--ac-text);
}
/* 浅色下用户气泡换成品牌淡蓝底，明显区分于 AI 文本流 */
.ai-chat-app.theme-light .msg.user .bubble {
  background: color-mix(in srgb, var(--ac-brand) 10%, #ffffff);
  border-color: color-mix(in srgb, var(--ac-brand) 22%, transparent);
}
.msg.assistant { display: flex; gap: 12px; align-items: flex-start; }
.msg.assistant .ai-avatar {
  width: 28px; height: 28px; background: var(--ac-btn); border: 1px solid var(--ac-border);
  border-radius: 50%; display: grid; place-items: center; font-size: 11px;
  color: #f0824a; font-weight: 600; flex-shrink: 0; margin-top: 2px;
}
.msg.assistant .ai-avatar.tool { color: var(--ac-brand); }
.msg.assistant .ai-avatar.thinking { color: var(--ac-text-faint); }
.msg.assistant .bubble { color: var(--ac-text); line-height: 1.7; flex: 1; min-width: 0; }
.msg-text { word-break: break-word; }
.msg-text :deep(strong) { color: var(--ac-text); }
.msg-text :deep(p) { margin: 0 0 6px; line-height: 1.65; color: var(--ac-text); }
.msg-text :deep(p:last-child) { margin-bottom: 0; }
.msg-text :deep(ul), .msg-text :deep(ol) { margin: 2px 0 6px 22px; padding: 0; }
.msg-text :deep(ul:last-child), .msg-text :deep(ol:last-child) { margin-bottom: 0; }
.msg-text :deep(li) { margin: 0 0 1px; line-height: 1.6; color: var(--ac-text); }
.msg-text :deep(li > p) { margin: 0; }                    /* 去掉 marked 在松散列表里给 li 套的 <p> 的多余间距 */
.msg-text :deep(li > p + p) { margin-top: 4px; }
.msg-text :deep(li > ul), .msg-text :deep(li > ol) { margin: 2px 0 2px 18px; }
.msg-text :deep(h1), .msg-text :deep(h2), .msg-text :deep(h3), .msg-text :deep(h4) {
  color: var(--ac-text); margin: 14px 0 4px; font-weight: 600; line-height: 1.35;
}
.msg-text :deep(h1:first-child), .msg-text :deep(h2:first-child), .msg-text :deep(h3:first-child) { margin-top: 0; }
.msg-text :deep(h1) { font-size: 17px; }
.msg-text :deep(h2) { font-size: 15px; }
.msg-text :deep(h3) { font-size: 14px; }
.msg-text :deep(code) {
  background: var(--ac-border-strong);
  padding: 1px 6px;
  border-radius: 3px;
  font-family: ui-monospace, Menlo, monospace;
  font-size: 12.5px;
  color: #f0824a;
}
.msg-text :deep(pre) {
  background: var(--ac-bg);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 6px;
  padding: 10px 12px;
  overflow-x: auto;
  margin: 6px 0;
}
.msg-text :deep(pre code) { background: transparent; padding: 0; color: var(--ac-text); font-size: 12px; }
.msg-text :deep(table) { border-collapse: collapse; margin: 8px 0; font-size: 12.5px; }
.msg-text :deep(th), .msg-text :deep(td) { border: 1px solid var(--ac-border-strong); padding: 4px 8px; text-align: left; color: var(--ac-text); }
.msg-text :deep(th) { background: var(--ac-border-faint); font-weight: 600; }
.msg-text :deep(blockquote) { border-left: 3px solid var(--ac-border-strong); padding-left: 10px; color: var(--ac-text-mute); margin: 6px 0; }
.msg-text :deep(a) { color: var(--ac-brand); }

.attach-chips { display: flex; flex-direction: column; gap: 4px; margin-top: 8px; }
.attach-chip {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 5px 10px 5px 8px; background: var(--ac-border-faint);
  border: 1px solid var(--ac-border); border-radius: 6px; font-size: 12.5px;
  color: var(--ac-text-mute); width: fit-content; max-width: 100%;
}
.attach-chip .icon { font-size: 13px; opacity: 0.85; }
.attach-chip .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 280px; }

/* 工作过程类消息：相比对话内容更窄，视觉区分"AI 在做什么" vs "AI 在说什么" */
.msg.assistant.process .bubble {
  max-width: 560px;
}

.tool-call {
  border: 1px solid var(--ac-border); border-radius: 8px; background: var(--ac-panel);
  overflow: hidden; transition: border-color 0.15s, box-shadow 0.2s;
}
.tool-call:hover { border-color: var(--ac-border-strong); }
.tool-call.running {
  border-color: color-mix(in srgb, var(--ac-brand) 45%, transparent);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--ac-brand) 20%, transparent);
}
.tool-call.running .tool-name { color: var(--ac-brand); }
.tool-group.running {
  border-color: color-mix(in srgb, var(--ac-brand) 45%, transparent);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--ac-brand) 20%, transparent);
}
.running-hint {
  display: flex; align-items: center; gap: 8px;
  color: var(--ac-text-mute); font-size: 12.5px;
}
.tool-head {
  display: flex; align-items: center; gap: 10px; padding: 8px 12px;
  cursor: pointer; user-select: none; font-size: 13px;
}
.tool-head:hover { background: var(--ac-border-faint); }
.tool-icon { font-size: 13px; opacity: 0.9; }
.tool-name { font-family: ui-monospace, Menlo, monospace; font-size: 12.5px; color: #f0824a; }
.tool-args {
  color: var(--ac-text-mute); font-size: 12.5px; flex: 1;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.tool-duration { color: var(--ac-text-faint); font-family: ui-monospace, Menlo, monospace; font-size: 11.5px; }
.tool-status { width: 14px; height: 14px; display: grid; place-items: center; font-size: 10px; border-radius: 50%; }
.tool-status.success { background: rgba(52,211,153,0.15); color: #34d399; }
.tool-status.running { background: color-mix(in srgb, var(--ac-brand) 18%, transparent); color: var(--ac-brand); }
.tool-status.error { background: rgba(248,113,113,0.18); color: #f87171; }
.tool-toggle { color: var(--ac-text-faint); font-size: 10px; transition: transform 0.15s; }
.tool-call.expanded .tool-toggle { transform: rotate(90deg); }
.tool-group {
  border: 1px solid var(--ac-border);
  border-radius: 8px;
  overflow: hidden;
  background: var(--ac-panel);
}
.tool-group:hover { border-color: var(--ac-border-strong); }
.tool-group .group-head {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 12px; cursor: pointer; user-select: none; font-size: 13px;
}
.tool-group .group-head:hover { background: var(--ac-border-faint); }
.tool-group .group-count {
  font-family: ui-monospace, Menlo, monospace;
  font-size: 11px;
  background: rgba(240, 130, 74, 0.15);
  color: #f0824a;
  padding: 1px 7px;
  border-radius: 9px;
}
.tool-group.expanded .tool-toggle { transform: rotate(90deg); }
.tool-group .group-body {
  border-top: 1px solid var(--ac-border);
  background: rgba(0,0,0,0.2);
}
.tool-call.mini { border: none; border-radius: 0; background: transparent; }
.tool-call.mini:hover { background: rgba(255,255,255,0.03); }
.tool-call.mini .tool-head { padding: 6px 12px 6px 28px; font-size: 12.5px; }
.tool-call.mini .tool-body { padding: 6px 12px 10px 28px; }
.tool-body { border-top: 1px solid var(--ac-border); padding: 12px; background: rgba(0,0,0,0.25); }
.tool-section { margin-bottom: 10px; font-size: 12.5px; }
.tool-section:last-child { margin-bottom: 0; }
.tool-section-label { font-size: 11px; text-transform: uppercase; color: var(--ac-text-faint); letter-spacing: 0.4px; margin-bottom: 6px; }
.tool-section pre {
  margin: 0; padding: 10px 12px; background: var(--ac-bg); border: 1px solid var(--ac-border);
  border-radius: 6px; font-family: ui-monospace, Menlo, monospace; font-size: 11.5px;
  overflow-x: auto; white-space: pre-wrap; word-break: break-word;
}

.ask-card { background: color-mix(in srgb, var(--ac-brand) 6%, transparent); border: 1px solid color-mix(in srgb, var(--ac-brand) 25%, transparent); border-radius: 10px; padding: 12px 14px; }
.ask-q { font-weight: 500; color: var(--ac-text); margin-bottom: 10px; }
.ask-options { display: flex; flex-wrap: wrap; gap: 6px; }
.ask-opt {
  background: var(--ac-input); border: 1px solid var(--ac-border-strong); color: var(--ac-text);
  padding: 5px 12px; border-radius: 14px; font-size: 12.5px; cursor: pointer;
  transition: all 0.15s;
}
.ask-opt:hover { background: var(--ac-brand); border-color: var(--ac-brand); color: var(--ac-text); }

.thinking-text {
  color: var(--ac-text-mute);
  font-size: 13px;
  border-left: 2px solid var(--ac-border-strong);
  padding-left: 10px;
  line-height: 1.65;
}
.thinking-text :deep(p) { margin: 0 0 6px; }
.thinking-text :deep(p:last-child) { margin-bottom: 0; }

/* 流式光标：在 streaming 文本末尾闪烁的小条 */
.cursor-blink {
  display: inline-block;
  width: 7px;
  height: 14px;
  background: var(--ac-brand);
  vertical-align: text-bottom;
  margin-left: 2px;
  animation: blink 1s step-end infinite;
  border-radius: 1px;
}
@keyframes blink { 50% { opacity: 0 } }

/* 设计文档 inline 卡片 (codex 风) */
.artifact-card {
  border: 1px solid color-mix(in srgb, var(--ac-brand) 35%, transparent);
  background: linear-gradient(135deg, color-mix(in srgb, var(--ac-brand) 8%, transparent), color-mix(in srgb, var(--ac-brand) 2%, transparent));
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.15s;
  overflow: hidden;
}
.artifact-card:hover { border-color: color-mix(in srgb, var(--ac-brand) 60%, transparent); transform: translateY(-1px); }
.art-card-head {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 14px;
  background: color-mix(in srgb, var(--ac-brand) 6%, transparent);
}
.art-card-icon { font-size: 14px; }
.art-card-name {
  flex: 1;
  font-family: ui-monospace, Menlo, monospace;
  font-size: 13px;
  color: var(--ac-text);
  font-weight: 500;
}
.art-card-version {
  font-family: ui-monospace, Menlo, monospace;
  font-size: 11px;
  background: color-mix(in srgb, var(--ac-brand) 18%, transparent);
  color: #a8b8ff;
  padding: 1px 7px;
  border-radius: 9px;
}
.art-card-arrow { color: var(--ac-brand); font-size: 16px; line-height: 1; }
.art-card-handoff {
  appearance: none;
  background: rgba(240, 130, 74, 0.16);
  border: 1px solid rgba(240, 130, 74, 0.45);
  color: #f4a47b;
  font-size: 11px;
  padding: 3px 8px;
  border-radius: 5px;
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.15s, color 0.15s;
}
.art-card-handoff:hover {
  background: rgba(240, 130, 74, 0.28);
  color: #fbcfb1;
}
.art-card-preview {
  padding: 10px 14px;
  font-family: ui-monospace, Menlo, monospace;
  font-size: 11.5px;
  color: var(--ac-text-faint);
  border-top: 1px solid color-mix(in srgb, var(--ac-brand) 15%, transparent);
  max-height: 60px;
  overflow: hidden;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.5;
  position: relative;
}
.art-card-preview::after {
  content: '';
  position: absolute; left: 0; right: 0; bottom: 0;
  height: 28px;
  background: linear-gradient(180deg, transparent, var(--ac-input));
  pointer-events: none;
}

/* 应用就绪 CTA — 大号 inline 蓝条卡，generate / deploy 成功后渲染在工具卡后 */
.app-ready-cta {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 18px;
  border-radius: 12px;
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.14), rgba(99, 102, 241, 0.10));
  border: 1px solid rgba(59, 130, 246, 0.42);
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s, transform 0.15s;
  max-width: 600px;
  width: 100%;
}
.app-ready-cta:hover {
  border-color: rgba(59, 130, 246, 0.75);
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.22), rgba(99, 102, 241, 0.16));
  transform: translateY(-1px);
}
.app-ready-cta .cta-icon {
  font-size: 28px;
  line-height: 1;
  flex-shrink: 0;
}
.app-ready-cta .cta-body {
  flex: 1;
  min-width: 0;
}
.app-ready-cta .cta-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--ac-text, #1f2937);
  margin-bottom: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.app-ready-cta .cta-sub {
  font-size: 12px;
  color: var(--ac-text-faint, rgba(116, 128, 171, 0.85));
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.app-ready-cta .cta-sub-sep {
  opacity: 0.5;
}
.app-ready-cta .cta-action {
  flex-shrink: 0;
  appearance: none;
  background: #3b82f6;
  border: none;
  color: #fff;
  padding: 9px 18px;
  font-size: 13px;
  font-weight: 600;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s, transform 0.1s;
  white-space: nowrap;
}
.app-ready-cta .cta-action:hover {
  background: #2563eb;
}
.app-ready-cta .cta-action:active {
  transform: scale(0.97);
}
/* 2026-05-30 生成中态: 蓝→琥珀(不谎报就绪) + 进度条/进度文字。配色沿用本组件硬编码风格 */
.app-ready-cta.is-generating {
  background: linear-gradient(135deg, rgba(245, 158, 11, 0.14), rgba(217, 119, 6, 0.08));
  border-color: rgba(245, 158, 11, 0.42);
  cursor: default;
}
.app-ready-cta.is-generating:hover {
  border-color: rgba(245, 158, 11, 0.7);
  background: linear-gradient(135deg, rgba(245, 158, 11, 0.20), rgba(217, 119, 6, 0.12));
  transform: none;
}
.app-ready-cta.is-generating .cta-action { background: #d97706; }
.app-ready-cta.is-generating .cta-action:hover { background: #b45309; }
.app-ready-cta.is-failed {
  background: linear-gradient(135deg, rgba(239, 68, 68, 0.12), rgba(220, 38, 38, 0.06));
  border-color: rgba(239, 68, 68, 0.38);
}
.app-ready-cta.is-failed:hover {
  border-color: rgba(239, 68, 68, 0.62);
  background: linear-gradient(135deg, rgba(239, 68, 68, 0.16), rgba(220, 38, 38, 0.09));
}
.app-ready-cta.is-failed .cta-icon {
  color: #dc2626;
  background: rgba(239, 68, 68, 0.12);
}
.app-ready-cta.is-failed .cta-action { background: #dc2626; }
.app-ready-cta.is-failed .cta-action:hover { background: #b91c1c; }
.app-ready-cta .cta-progress-text {
  font-family: system-ui, -apple-system, "PingFang SC", sans-serif;
  color: var(--ac-text-mute, rgba(116, 128, 171, 0.95));
}
.app-ready-cta .cta-progress-bar {
  margin-top: 8px;
  height: 5px;
  border-radius: 999px;
  background: rgba(245, 158, 11, 0.18);
  overflow: hidden;
}
.app-ready-cta .cta-progress-fill {
  height: 100%;
  border-radius: 999px;
  background: #d97706;
  transition: width 0.4s ease;
}

.dots { display: inline-flex; gap: 4px; vertical-align: middle; }
.dots span { width: 6px; height: 6px; border-radius: 50%; background: var(--ac-brand); animation: pulse 1.2s ease-in-out infinite; }
.dots span:nth-child(2) { animation-delay: -0.16s; }
.dots span:nth-child(3) { animation-delay: -0.32s; }
@keyframes pulse { 0%,80%,100% { opacity: 0.3; transform: scale(0.85); } 40% { opacity: 1; transform: scale(1); } }
.typing-meta { color: var(--ac-text-faint); font-size: 12px; margin-left: 10px; }

/* AI 思考状态：整行水平居中，让"还在工作"这个全局状态更聚焦 */
.msg.assistant.thinking-row {
  justify-content: center;
  align-items: center;
}

/* AI 思考状态：醒目的 bubble，让用户清楚 AI 没断 */
.thinking-bubble {
  /* 覆盖 .bubble 默认的 flex:1，让 bubble 只包住自身内容 */
  flex: 0 0 auto !important;
  display: inline-flex !important;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  background: color-mix(in srgb, var(--ac-brand) 8%, transparent);
  border: 1px solid color-mix(in srgb, var(--ac-brand) 22%, transparent);
  border-radius: 14px;
  width: fit-content;
  max-width: 100%;
}
.thinking-label {
  color: #c5c8d0;
  font-size: 13px;
}
.thinking-secs {
  font-family: ui-monospace, Menlo, monospace;
  color: var(--ac-brand);
  font-size: 11.5px;
  background: color-mix(in srgb, var(--ac-brand) 12%, transparent);
  padding: 1px 7px;
  border-radius: 9px;
}
.ai-avatar.pulsing {
  animation: avatarPulse 2s ease-in-out infinite;
  border-color: color-mix(in srgb, var(--ac-brand) 40%, transparent) !important;
  color: var(--ac-brand) !important;
}
@keyframes avatarPulse {
  0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--ac-brand) 40%, transparent); }
  50% { box-shadow: 0 0 0 6px color-mix(in srgb, var(--ac-brand) 0%, transparent); }
}

/* ─── Input area ─── */
.input-area {
  border-top: 1px solid var(--ac-border);
  padding: 10px 16px calc(14px + env(safe-area-inset-bottom, 0px));
  flex-shrink: 0;
}

/* 对话界面风格队列提示卡 */
.queue-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  margin-bottom: 8px;
  background: var(--brand-soft, rgba(29, 78, 216, 0.06));
  border: 1px solid var(--brand-ring, rgba(29, 78, 216, 0.18));
  border-radius: 10px;
  font-size: 12.5px;
  color: rgba(31, 41, 55, 0.85);
}
.queue-icon { font-size: 13px; }
.queue-text { flex: 1; }
.queue-clear {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  border: none;
  background: rgba(116, 128, 171, 0.12);
  color: rgba(116, 128, 171, 0.85);
  cursor: pointer;
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.queue-clear:hover { background: rgba(116, 128, 171, 0.2); }
.input-card {
  width: 100%;
  max-width: none;
  margin: 0;
  background: var(--ac-input); border: 1px solid var(--ac-border-strong); border-radius: 14px; padding: 8px;
  transition: border-color 0.15s;
}
.input-card:focus-within { border-color: color-mix(in srgb, var(--ac-brand) 50%, transparent); }
.input-attaches { padding: 4px 8px 6px; display: flex; flex-wrap: wrap; gap: 4px; }
.input-chip {
  display: inline-flex; align-items: center; gap: 6px;
  background: var(--ac-btn); border: 1px solid var(--ac-border);
  border-radius: 6px; padding: 3px 6px 3px 8px; font-size: 12px;
}
.input-chip .x {
  background: transparent; border: none; color: var(--ac-text-faint); cursor: pointer; padding: 0 2px;
}
.input-row { display: flex; align-items: flex-end; gap: 6px; padding: 4px 4px 4px 8px; }
.icon-btn {
  background: transparent; border: none; color: var(--ac-text-mute); cursor: pointer;
  width: 32px; height: 32px; border-radius: 8px; display: grid; place-items: center;
  font-size: 16px; flex-shrink: 0; transition: all 0.15s;
}
.icon-btn:hover { background: var(--ac-border-faint); color: var(--ac-text); }
.textarea {
  flex: 1; background: transparent; border: none; color: var(--ac-text);
  font-family: inherit; font-size: 14px; line-height: 1.5;
  resize: none; outline: none; min-height: 22px; max-height: 160px; padding: 6px 8px;
}
.textarea::placeholder { color: var(--ac-text-faint); }
.send-btn {
  width: 34px; height: 34px; border-radius: 50%; background: var(--ac-brand);
  border: none; color: #fff; cursor: pointer; display: grid; place-items: center;
  flex-shrink: 0; transition: all 0.15s;
  box-shadow: var(--sh-brand, 0 2px 6px rgba(29, 78, 216, 0.3));
}
.send-btn:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 3px 10px color-mix(in srgb, var(--ac-brand) 40%, transparent); }
.send-btn:disabled { opacity: 0.35; cursor: not-allowed; box-shadow: none; }
.send-btn.stop {
  background: #ef4444;
  box-shadow: 0 2px 6px rgba(239, 68, 68, 0.35);
  animation: send-btn-pulse 1.4s ease-in-out infinite;
}
.send-btn.stop:hover { box-shadow: 0 3px 10px rgba(239, 68, 68, 0.5); }
@keyframes send-btn-pulse {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.05); }
}

/* ─── Aside right (codex-style file viewer) ─── */
.aside-right {
  background: var(--ac-input); border-left: 1px solid var(--ac-border);
  display: flex; flex-direction: column; overflow: hidden;
  position: relative;
  flex-shrink: 0;
}
/* 左边缘拖拽手柄：默认透明，hover 时显示品牌色细条 */
.aside-resizer {
  position: absolute;
  left: 0; top: 0; bottom: 0;
  width: 5px;
  cursor: ew-resize;
  background: transparent;
  z-index: 3;
  transition: background 0.12s;
}
.aside-resizer:hover,
.aside-resizer:active {
  background: color-mix(in srgb, var(--ac-brand) 45%, transparent);
}
.art-header {
  padding: 12px 16px; border-bottom: 1px solid var(--ac-border);
  display: flex; align-items: center; gap: 10px;
}
.art-close {
  background: transparent; border: none; color: var(--ac-text-mute);
  font-size: 16px; cursor: pointer; padding: 2px 8px; border-radius: 5px;
  line-height: 1; flex-shrink: 0;
}
.art-close:hover { background: var(--ac-border); color: var(--ac-text); }
.art-breadcrumb {
  flex: 1; font-size: 12.5px; color: var(--ac-text-faint);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.art-breadcrumb .seg { color: var(--ac-text-faint); }
.art-breadcrumb .seg.current { color: var(--ac-text); font-weight: 500; }
.art-breadcrumb .sep { margin: 0 6px; color: #4a4d56; }
.count-badge { background: var(--ac-btn); padding: 2px 8px; border-radius: 10px; font-size: 11px; color: var(--ac-text-mute); flex-shrink: 0; }

.art-list { padding: 8px 8px; border-bottom: 1px solid var(--ac-border); max-height: 180px; overflow-y: auto; }
.art-list.compact { display: flex; flex-direction: column; gap: 1px; }
.art-card {
  padding: 6px 10px; border-radius: 5px; cursor: pointer; transition: background 0.1s;
  display: flex; align-items: center; gap: 8px;
}
.art-card:hover { background: var(--ac-border-faint); }
.art-card.active { background: var(--ac-btn); }
.art-card-dot { font-size: 12px; }
.art-card-fname {
  flex: 1; font-size: 12.5px; color: var(--ac-text);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-family: ui-monospace, Menlo, monospace;
}
.art-card-vbadge {
  font-family: ui-monospace, Menlo, monospace; font-size: 10.5px;
  background: var(--ac-border); padding: 1px 6px; border-radius: 8px; color: var(--ac-text-mute);
}

.art-empty { padding: 40px 18px; color: var(--ac-text-faint); font-size: 13px; text-align: center; }
.art-empty .muted { color: var(--ac-text-faint); font-size: 12px; }

.art-preview { flex: 1; overflow-y: auto; display: flex; flex-direction: column; }
.art-preview-head {
  padding: 8px 14px; border-bottom: 1px solid var(--ac-border);
  display: flex; align-items: center; gap: 4px;
  position: sticky; top: 0; background: var(--ac-input); z-index: 1;
}
.art-preview-head .art-meta-text {
  font-family: ui-monospace, Menlo, monospace; font-size: 11px; color: var(--ac-text-faint); margin-right: 6px;
}
.art-preview-spacer { flex: 1; }
.small-btn {
  background: transparent; border: 1px solid var(--ac-border); color: var(--ac-text-mute);
  padding: 3px 10px; border-radius: 5px; font-size: 11.5px; cursor: pointer;
  transition: all 0.12s;
}
.small-btn:hover { color: var(--ac-text); border-color: rgba(255,255,255,0.18); background: var(--ac-border-faint); }
.small-btn.active { color: var(--ac-text); background: color-mix(in srgb, var(--ac-brand) 16%, transparent); border-color: color-mix(in srgb, var(--ac-brand) 40%, transparent); }
.small-btn.primary {
  background: rgba(240, 130, 74, 0.18);
  border-color: rgba(240, 130, 74, 0.5);
  color: #f4a47b;
}
.small-btn.primary:hover {
  background: rgba(240, 130, 74, 0.32);
  color: #fbcfb1;
  border-color: rgba(240, 130, 74, 0.7);
}
.art-preview-body {
  margin: 0; padding: 16px 18px;
  font-family: ui-monospace, Menlo, monospace; font-size: 11.5px;
  color: var(--ac-text-mute); white-space: pre-wrap; word-break: break-word;
}
/* HTML 产物预览: 沙箱 iframe 铺满预览区, 白底(等同本地打开浏览器) */
.art-preview-frame {
  flex: 1 1 auto;
  width: 100%;
  min-height: 600px;
  border: 0;
  background: #fff;
  display: block;
}
.art-preview-body.md {
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif;
  font-size: 13px;
  color: var(--ac-text);
  white-space: normal;
  line-height: 1.7;
}
.art-preview-body.md :deep(h1) { font-size: 18px; color: var(--ac-text); margin: 16px 0 8px; font-weight: 600; }
.art-preview-body.md :deep(h2) { font-size: 15px; color: var(--ac-text); margin: 14px 0 6px; font-weight: 600; }
.art-preview-body.md :deep(h3) { font-size: 13.5px; color: var(--ac-text); margin: 12px 0 6px; font-weight: 600; }
.art-preview-body.md :deep(p) { margin: 0 0 8px; }
.art-preview-body.md :deep(ul), .art-preview-body.md :deep(ol) { margin: 4px 0 10px 20px; padding: 0; }
.art-preview-body.md :deep(li) { margin-bottom: 2px; }
.art-preview-body.md :deep(table) { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 12px; }
.art-preview-body.md :deep(th), .art-preview-body.md :deep(td) { border: 1px solid var(--ac-border-strong); padding: 5px 9px; }
.art-preview-body.md :deep(th) { background: var(--ac-border-faint); color: var(--ac-text); }
.art-preview-body.md :deep(code) { background: var(--ac-border-strong); padding: 1px 6px; border-radius: 3px; color: #f0824a; font-family: ui-monospace, Menlo, monospace; font-size: 11.5px; }
.art-preview-body.md :deep(pre) { background: var(--ac-bg); border: 1px solid var(--ac-border); border-radius: 6px; padding: 10px 12px; overflow-x: auto; }
.art-preview-body.md :deep(pre code) { background: transparent; padding: 0; color: var(--ac-text); }
.art-preview-body.md :deep(blockquote) { border-left: 3px solid rgba(255,255,255,0.2); padding-left: 10px; color: var(--ac-text-mute); }
</style>
