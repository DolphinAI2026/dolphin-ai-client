<template>
  <WorkbenchShell>
  <div
    class="ai-chat-app"
    :class="[themeStore.isDark ? 'theme-dark' : 'theme-light', { 'aside-collapsed': asideCollapsed }]"
  >
    <!-- ═══════ 左侧 sessions ═══════ -->
    <aside class="aside-left">
      <template v-if="!asideCollapsed">
        <div class="aside-head">
          <div class="brand"><span class="brand-dot"></span>AI Chat</div>
          <button
            class="aside-toggle"
            @click="setAsideCollapsed(true)"
            title="收起会话列表"
          >«</button>
        </div>
        <el-dropdown trigger="click" placement="bottom-start" @command="onCreateSession">
          <button class="new-btn">
            <span>+ 新会话</span>
            <span class="new-btn-caret">▾</span>
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="chat">
                <div class="new-session-option">
                  <div class="new-session-option-title">
                    <el-icon class="mode-icon chat"><ChatDotRound /></el-icon>
                    <span>Chat 会话</span>
                  </div>
                  <div class="new-session-option-hint">从零对话理需求</div>
                </div>
              </el-dropdown-item>
              <el-dropdown-item command="cowork">
                <div class="new-session-option">
                  <div class="new-session-option-title">
                    <el-icon class="mode-icon cowork"><Folder /></el-icon>
                    <span>Cowork 会话</span>
                  </div>
                  <div class="new-session-option-hint">批量材料整合成标准 md</div>
                </div>
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <!-- 模式分组 tab：全部 / Chat / Cowork -->
        <div class="session-filter-tabs">
          <button
            v-for="tab in sessionFilterTabs"
            :key="tab.key"
            class="filter-tab"
            :class="{ active: sessionsFilter === tab.key }"
            @click="sessionsFilter = tab.key"
            :title="tab.title"
          >
            <el-icon v-if="tab.key === 'chat'" class="filter-tab-icon"><ChatDotRound /></el-icon>
            <el-icon v-else-if="tab.key === 'cowork'" class="filter-tab-icon"><Folder /></el-icon>
            <span>{{ tab.label }}</span>
            <span class="filter-tab-count">{{ tab.count }}</span>
          </button>
        </div>
        <div class="session-list">
          <div
            v-for="s in filteredSessions"
            :key="s.id"
            class="session-item"
            :class="{ active: currentSessionId === s.id }"
            @click="loadSession(s.id)"
            :title="`${s.title}${s.mode === 'cowork' ? '（Cowork 协作整合模式）' : ''}`"
          >
            <el-icon v-if="s.mode === 'cowork'" class="session-mode-badge cowork" title="Cowork 协作整合模式"><Folder /></el-icon>
            <span class="session-name">{{ s.title }}</span>
            <button class="session-menu-btn" @click.stop="onRenameSession(s)" title="重命名">✎</button>
            <button class="session-menu-btn danger" @click.stop="onDeleteSession(s)" title="删除">×</button>
          </div>
          <div v-if="filteredSessions.length === 0" class="empty-hint">
            {{ sessionsFilter === 'all' ? '还没有会话，点上面新建一个' : `还没有 ${sessionsFilter === 'cowork' ? 'Cowork' : 'Chat'} 模式的会话` }}
          </div>
        </div>
        <div class="aside-foot">
          <button class="back-btn" @click="$router.push('/apps')">← 返回应用</button>
        </div>
      </template>
      <template v-else>
        <div class="aside-rail">
          <button
            class="rail-btn"
            @click="setAsideCollapsed(false)"
            title="展开会话列表"
          >»</button>
          <button
            class="rail-btn"
            @click="onCreateSession('chat')"
            title="新建 Chat 会话（展开侧栏可选 Cowork）"
          >+</button>
          <div class="rail-spacer"></div>
          <button
            class="rail-btn"
            @click="$router.push('/apps')"
            title="返回应用"
          >←</button>
        </div>
      </template>
    </aside>

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
            <span v-if="currentSession.mode === 'cowork'" class="header-mode-badge cowork">
              <el-icon><Folder /></el-icon><span>Cowork</span>
            </span>
            <span v-else class="header-mode-badge chat">
              <el-icon><ChatDotRound /></el-icon><span>Chat</span>
            </span>
            {{ currentSession.title }}
          </span>
          <span v-else class="title-placeholder">未选择会话</span>
        </div>
        <div class="header-actions">
          <button
            v-if="artifacts.length > 0"
            class="artifacts-toggle"
            :class="{ active: artifactsPanelOpen }"
            @click="artifactsPanelOpen = !artifactsPanelOpen"
            :title="artifactsPanelOpen ? '收起设计文档' : '展开设计文档'"
          >📄 设计文档 <span class="badge">{{ artifacts.length }}</span></button>
        </div>
      </header>

      <!-- 消息流 -->
      <div class="messages" ref="messagesRef">
        <div v-if="!currentSession" class="welcome">
          <template v-if="incomingMode === 'cowork'">
            <h2><el-icon class="welcome-icon"><Folder /></el-icon> 协作整合材料</h2>
            <p>把你的所有材料（PDF / Word / Excel / 截图 / 现有文档）拖进来，AI 会先并行读完所有附件，给出综合摘要 + 批量澄清问题，然后产出符合 Builder 规范的标准设计文档。</p>
          </template>
          <template v-else>
            <h2>👋 欢迎使用 AI Chat</h2>
            <p>新建一个会话，上传材料，让 AI 帮你梳理需求并生成设计文档。</p>
          </template>
        </div>
        <template v-else>
          <div v-for="(item, idx) in renderTimeline" :key="idx" class="timeline-item">
            <!-- user message -->
            <div v-if="item.kind === 'msg' && item.msg.role === 'user'" class="msg user">
              <div class="bubble">
                <div class="msg-text">{{ item.msg.content }}</div>
                <div v-if="userMessageAttachments(item.msg).length" class="attach-chips">
                  <span v-for="a in userMessageAttachments(item.msg)" :key="a.id" class="attach-chip">
                    <span class="icon">{{ a.kind === 'image' ? '🖼️' : '📄' }}</span>
                    <span class="name">{{ a.filename }}</span>
                  </span>
                </div>
              </div>
            </div>
            <!-- assistant message -->
            <div v-else-if="item.kind === 'msg' && item.msg.role === 'assistant'" class="msg assistant">
              <div class="ai-avatar">AI</div>
              <div class="bubble">
                <div class="msg-text" v-html="renderMd(item.msg.content)"></div>
              </div>
            </div>
            <!-- tool call -->
            <div v-else-if="item.kind === 'tool'" class="msg assistant process">
              <div class="ai-avatar tool">⚒</div>
              <div class="bubble" style="flex: 1">
                <div
                  class="tool-call"
                  :class="{ expanded: isToolBodyOpen(item.tool), running: item.tool.status === 'running' }"
                >
                  <div class="tool-head" @click="toggleTool(item.tool.id)">
                    <span class="tool-icon">{{ toolIcon(item.tool.tool_name) }}</span>
                    <span class="tool-name">{{ item.tool.tool_name }}</span>
                    <span class="tool-args" v-if="toolArgsBrief(item.tool)">{{ toolArgsBrief(item.tool) }}</span>
                    <span class="tool-duration" v-if="item.tool.duration_ms">{{ (item.tool.duration_ms / 1000).toFixed(1) }}s</span>
                    <span class="tool-status" :class="item.tool.status">{{ statusGlyph(item.tool.status) }}</span>
                    <span class="tool-toggle">▶</span>
                  </div>
                  <div class="tool-body" v-if="isToolBodyOpen(item.tool)">
                    <div class="tool-section" v-if="item.tool.args_json">
                      <div class="tool-section-label">参数</div>
                      <pre>{{ JSON.stringify(item.tool.args_json, null, 2) }}</pre>
                    </div>
                    <div class="tool-section" v-if="item.tool.result_text">
                      <div class="tool-section-label">输出</div>
                      <pre>{{ item.tool.result_text }}</pre>
                    </div>
                    <div class="tool-section running-hint" v-else-if="item.tool.status === 'running'">
                      <span class="dots"><span></span><span></span><span></span></span>
                      <span>执行中…</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <!-- tool group (连续同名工具折叠) -->
            <div v-else-if="item.kind === 'tool_group'" class="msg assistant process">
              <div class="ai-avatar tool">⚒</div>
              <div class="bubble" style="flex: 1">
                <div
                  class="tool-group"
                  :class="{
                    expanded: isGroupOpen(item.tools),
                    running: item.tools.some(t => t.status === 'running'),
                  }"
                >
                  <div class="group-head" @click="toggleGroup(item.tools[0].id)">
                    <span class="tool-icon">{{ toolIcon(item.tools[0].tool_name) }}</span>
                    <span class="tool-name">{{ item.tools[0].tool_name }}</span>
                    <span class="group-count">×{{ item.tools.length }}</span>
                    <span class="tool-args">{{ groupSummary(item.tools) }}</span>
                    <span class="tool-toggle">▶</span>
                  </div>
                  <div class="group-body" v-if="isGroupOpen(item.tools)">
                    <div
                      v-for="tool in item.tools"
                      :key="tool.id"
                      class="tool-call mini"
                      :class="{ expanded: isToolBodyOpen(tool), running: tool.status === 'running' }"
                    >
                      <div class="tool-head" @click="toggleTool(tool.id)">
                        <span class="tool-args">{{ toolArgsBrief(tool) }}</span>
                        <span class="tool-duration" v-if="tool.duration_ms">{{ (tool.duration_ms / 1000).toFixed(1) }}s</span>
                        <span class="tool-status" :class="tool.status">{{ statusGlyph(tool.status) }}</span>
                        <span class="tool-toggle">▶</span>
                      </div>
                      <div class="tool-body" v-if="isToolBodyOpen(tool)">
                        <div class="tool-section" v-if="tool.args_json">
                          <div class="tool-section-label">参数</div>
                          <pre>{{ JSON.stringify(tool.args_json, null, 2) }}</pre>
                        </div>
                        <div class="tool-section" v-if="tool.result_text">
                          <div class="tool-section-label">输出</div>
                          <pre>{{ tool.result_text }}</pre>
                        </div>
                        <div class="tool-section running-hint" v-else-if="tool.status === 'running'">
                          <span class="dots"><span></span><span></span><span></span></span>
                          <span>执行中…</span>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <!-- ask_user card -->
            <div v-else-if="item.kind === 'ask'" class="msg assistant">
              <div class="ai-avatar">?</div>
              <div class="bubble">
                <div class="ask-card">
                  <div class="ask-q">{{ item.ask.question }}</div>
                  <div class="ask-options" v-if="item.ask.options?.length">
                    <button v-for="opt in item.ask.options" :key="opt" class="ask-opt" @click="onAnswerAsk(opt)">{{ opt }}</button>
                  </div>
                </div>
              </div>
            </div>
            <!-- 思考（已锁定） -->
            <div v-else-if="item.kind === 'thinking'" class="msg assistant">
              <div class="ai-avatar thinking">…</div>
              <div class="bubble">
                <div class="thinking-text" v-html="renderMd(item.text)"></div>
              </div>
            </div>
            <!-- 流式中：实时拼接的 assistant 文本 -->
            <div v-else-if="item.kind === 'streaming'" class="msg assistant">
              <div class="ai-avatar">AI</div>
              <div class="bubble">
                <div class="msg-text" v-html="renderMd(item.text)"></div>
                <span class="cursor-blink"></span>
              </div>
            </div>
            <!-- 设计文档 inline 卡片（codex 风格） -->
            <div v-else-if="item.kind === 'artifact_card'" class="msg assistant process">
              <div class="ai-avatar tool">📄</div>
              <div class="bubble" style="flex: 1">
                <div class="artifact-card" @click="openArtifactInPanel(item.artifact)">
                  <div class="art-card-head">
                    <span class="art-card-icon">📄</span>
                    <span class="art-card-name">{{ item.artifact.filename }}</span>
                    <span class="art-card-version">v{{ item.artifact.version }}</span>
                    <button
                      v-if="isMarkdownArtifact(item.artifact)"
                      class="art-card-handoff"
                      type="button"
                      @click.stop="sendArtifactToBuilderByName(item.artifact.filename)"
                      title="把这份设计文档交给 Builder 自动搭建"
                    >→ Builder</button>
                    <span class="art-card-arrow">›</span>
                  </div>
                  <div class="art-card-preview" v-if="item.artifact.preview">{{ item.artifact.preview }}</div>
                </div>
              </div>
            </div>
          </div>

          <!-- 流式中 typing 指示（仅在没在 stream 输出时显示，避免和 streaming 重影） -->
          <div v-if="isSending && !lastEventIsAsk && !streamingText" class="msg assistant thinking-row">
            <div class="ai-avatar pulsing">AI</div>
            <div class="bubble thinking-bubble">
              <span class="dots"><span></span><span></span><span></span></span>
              <span class="thinking-label">{{ thinkingLabel }}</span>
              <span class="thinking-secs" v-if="durationSec > 0">{{ durationSec }}s</span>
            </div>
          </div>
        </template>
      </div>

      <!-- 输入区 -->
      <div class="input-area" v-if="currentSession">
        <div class="input-card">
          <div class="input-attaches" v-if="pendingFiles.length">
            <span v-for="(f, i) in pendingFiles" :key="i" class="input-chip">
              📎 {{ f.name }}
              <button class="x" @click="pendingFiles.splice(i, 1)">×</button>
            </span>
          </div>
          <div class="input-row">
            <button class="icon-btn" title="上传附件" @click="fileInputRef?.click()">📎</button>
            <input
              ref="fileInputRef"
              type="file"
              multiple
              hidden
              @change="onFilesSelected"
            />
            <textarea
              v-model="inputText"
              class="textarea"
              :placeholder="isSending ? 'AI 正在工作中…' : '描述需求、追问或要求修改设计文档'"
              rows="1"
              ref="textareaRef"
              @keydown.enter.exact.prevent="onSend"
              @keydown.enter.shift.exact="inputText += '\n'"
              @input="autosizeTextarea"
            ></textarea>
            <button v-if="isSending" class="send-btn stop" @click="onAbort" title="中断">
              <svg width="11" height="11" viewBox="0 0 11 11" fill="currentColor"><rect x="1" y="1" width="9" height="9" rx="1"/></svg>
            </button>
            <button v-else class="send-btn" :disabled="!canSend" @click="onSend" title="发送">
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M12 2L6 8M12 2l-4 10-1.5-4.5L2 6 12 2z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>
            </button>
          </div>
          <div class="input-foot">
            <select
              v-model="selectedLlmId"
              class="model-select-inline"
              @change="onChangeLlm"
            >
              <option :value="null">默认模型</option>
              <option v-for="m in llmOptions" :key="m.id" :value="m.id">{{ m.config_name }}</option>
            </select>
            <span class="hint">{{ messages.length === 0 ? '首条消息会使用当前选择的模型' : '切换后仅影响后续对话' }}</span>
            <span v-if="durationSec > 0" class="hint timer">· AI 思考中 {{ durationSec }}s</span>
          </div>
        </div>
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
          <span class="art-card-dot">📄</span>
          <span class="art-card-fname">{{ fname }}</span>
          <span class="art-card-vbadge">v{{ latestVersionFor(fname) }}</span>
        </div>
      </div>
      <div class="art-preview" v-if="activeArtifactContent">
        <div class="art-preview-head">
          <button
            class="small-btn"
            :class="{ active: !artifactRawView }"
            @click="artifactRawView = false"
          >渲染</button>
          <button
            class="small-btn"
            :class="{ active: artifactRawView }"
            @click="artifactRawView = true"
          >原文</button>
          <span class="art-preview-spacer"></span>
          <span class="art-meta-text">{{ artifactStats }}</span>
          <button class="small-btn" @click="copyArtifact" title="复制">⧉</button>
          <button class="small-btn" @click="downloadArtifact" title="下载">⤓</button>
          <button
            v-if="canSendArtifactToBuilder"
            class="small-btn"
            :disabled="isSending"
            @click="rewriteArtifactToSpec"
            title="让 AI 按 aPaaS 标准规范重写本文档（同名覆盖，自动 +1 版本）"
          >按规范重写</button>
          <button
            v-if="canSendArtifactToBuilder"
            class="small-btn primary"
            @click="sendArtifactToBuilder"
            title="把这份设计文档交给 Builder 自动搭建"
          >→ Builder</button>
        </div>
        <pre v-if="artifactRawView" class="art-preview-body">{{ activeArtifactContent }}</pre>
        <div v-else class="art-preview-body md" v-html="renderMd(activeArtifactContent)"></div>
      </div>
      <div v-else class="art-empty">
        <p class="muted">点击左侧文件查看</p>
      </div>
    </aside>
  </div>
  </WorkbenchShell>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { marked } from 'marked'
import { aiChatApi, type AIChatSession, type AIChatMessage, type AIChatToolCall, type AIChatAttachment, type AIChatArtifact } from '@/api/aiChat'
import { llmConfigApi, type BuilderModelOption } from '@/api/llmConfig'
import { usePreviewStore } from '@/stores/preview'
import { useThemeStore } from '@/stores/theme'
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ChatDotRound, Folder } from '@element-plus/icons-vue'

const previewStore = usePreviewStore()
const themeStore = useThemeStore()

marked.setOptions({ breaks: true, gfm: true })

const route = useRoute()
const router = useRouter()

// ── State ──
const sessions = ref<AIChatSession[]>([])
const currentSession = ref<AIChatSession | null>(null)
const currentSessionId = computed(() => currentSession.value?.id ?? null)

// 会话列表分组 tab：all / chat / cowork
type SessionFilter = 'all' | 'chat' | 'cowork'
const sessionsFilter = ref<SessionFilter>('all')
const sessionFilterTabs = computed<Array<{ key: SessionFilter; label: string; title: string; count: number }>>(() => {
  const chatCount = sessions.value.filter(s => (s.mode || 'chat') !== 'cowork').length
  const coworkCount = sessions.value.filter(s => s.mode === 'cowork').length
  return [
    { key: 'all', label: '全部', title: '所有会话', count: sessions.value.length },
    { key: 'chat', label: 'Chat', title: '从零理需求的对话', count: chatCount },
    { key: 'cowork', label: 'Cowork', title: '批量材料整合', count: coworkCount },
  ]
})
const filteredSessions = computed(() => {
  if (sessionsFilter.value === 'all') return sessions.value
  if (sessionsFilter.value === 'cowork') return sessions.value.filter(s => s.mode === 'cowork')
  return sessions.value.filter(s => (s.mode || 'chat') !== 'cowork')
})
const messages = ref<AIChatMessage[]>([])
const toolCalls = ref<AIChatToolCall[]>([])
const attachments = ref<AIChatAttachment[]>([])
const artifacts = ref<AIChatArtifact[]>([])

const llmOptions = ref<BuilderModelOption[]>([])
const selectedLlmId = ref<number | null>(null)

const inputText = ref('')
const pendingFiles = ref<File[]>([])
const fileInputRef = ref<HTMLInputElement>()
const textareaRef = ref<HTMLTextAreaElement>()
const messagesRef = ref<HTMLElement>()

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

// 左栏会话列表的折叠状态（localStorage 持久化）
const ASIDE_COLLAPSED_KEY = 'aichat:aside-collapsed'
const asideCollapsed = ref<boolean>(localStorage.getItem(ASIDE_COLLAPSED_KEY) === '1')
function setAsideCollapsed(v: boolean) {
  asideCollapsed.value = v
  try { localStorage.setItem(ASIDE_COLLAPSED_KEY, v ? '1' : '0') } catch { /* ignore */ }
}

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

const expandedTools = ref<Set<number>>(new Set())
const collapsedTools = ref<Set<number>>(new Set())
const toggleTool = (id: number) => {
  // running 工具默认展开；点击 = 收起。其余工具默认收起；点击 = 展开。
  if (expandedTools.value.has(id)) {
    expandedTools.value.delete(id)
    collapsedTools.value.add(id)
  } else if (collapsedTools.value.has(id)) {
    collapsedTools.value.delete(id)
    expandedTools.value.add(id)
  } else {
    expandedTools.value.add(id)
  }
  expandedTools.value = new Set(expandedTools.value)
  collapsedTools.value = new Set(collapsedTools.value)
}
const isToolBodyOpen = (tc: AIChatToolCall): boolean => {
  if (expandedTools.value.has(tc.id)) return true
  if (collapsedTools.value.has(tc.id)) return false
  return tc.status === 'running'
}
const expandedGroups = ref<Set<number>>(new Set())
const collapsedGroups = ref<Set<number>>(new Set())
const toggleGroup = (gid: number) => {
  if (expandedGroups.value.has(gid)) {
    expandedGroups.value.delete(gid)
    collapsedGroups.value.add(gid)
  } else if (collapsedGroups.value.has(gid)) {
    collapsedGroups.value.delete(gid)
    expandedGroups.value.add(gid)
  } else {
    expandedGroups.value.add(gid)
  }
  expandedGroups.value = new Set(expandedGroups.value)
  collapsedGroups.value = new Set(collapsedGroups.value)
}
const isGroupOpen = (tools: AIChatToolCall[]): boolean => {
  const gid = tools[0].id
  if (expandedGroups.value.has(gid)) return true
  if (collapsedGroups.value.has(gid)) return false
  return tools.some(t => t.status === 'running')
}
const groupSummary = (tools: AIChatToolCall[]): string => {
  const n = tools.length
  if (tools[0].tool_name === 'read_attachment') {
    const names = tools.map(t => t.args_json?.filename).filter(Boolean)
    if (names.length <= 2) return names.join(', ')
    return `${names.slice(0, 2).join(', ')} 等 ${n} 个文件`
  }
  if (tools[0].tool_name === 'run_python') {
    return `${n} 段 Python 代码`
  }
  if (tools[0].tool_name === 'write_artifact') {
    return tools.map(t => t.args_json?.filename).filter(Boolean).join(', ')
  }
  return `${n} 次调用`
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

const toolIcon = (name: string): string => {
  return ({
    read_attachment: '📖',
    run_python: '🐍',
    write_artifact: '✏️',
    ask_clarifying_question: '❓',
  } as any)[name] || '⚒️'
}

const toolArgsBrief = (tc: AIChatToolCall): string => {
  const a = tc.args_json || {}
  if (tc.tool_name === 'read_attachment') return a.filename || ''
  if (tc.tool_name === 'write_artifact') return `${a.filename} (${a.format || 'md'})`
  if (tc.tool_name === 'run_python') return (a.code || '').slice(0, 60).replace(/\n/g, ' ') + '…'
  if (tc.tool_name === 'ask_clarifying_question') return a.question?.slice(0, 80) || ''
  return ''
}

const statusGlyph = (status: string): string => ({ success: '✓', error: '✗', running: '…', pending: '○', aborted: '⨯' } as any)[status] || ''

const formatBytes = (n: number): string => {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(2)} MB`
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
function collapseTools(tcs: AIChatToolCall[]): TLItem[] {
  const out: TLItem[] = []
  // 累计同 filename 的 write_artifact 第几次（用于挑对应版本的 artifact）。
  // 之前用 artifacts.find(filename) 总是返回第一个匹配 → 多次 write 后所有
  // inline 卡片都显示同一个版本。改为按调用顺序对齐 version：
  // 第 N 次成功 write_artifact（同名）→ artifacts 里 version 第 N 大的那一条。
  const seenWriteForFile: Record<string, number> = {}
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
  const flushTools = () => {
    if (!toolBuf.length) return
    for (const it of collapseTools(toolBuf)) items.push(it)
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

const lastEventIsAsk = computed(() => {
  // 最后一次工具调用是 ask_clarifying_question success → AI 在等用户回答
  const tcs = toolCalls.value
  const last = tcs[tcs.length - 1]
  if (!last) return false
  return last.tool_name === 'ask_clarifying_question' && last.status === 'success'
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
    return `AI 正在生成 ${streamingTool.name}${suffix} 参数（已 ${charsSoFar} 字）`
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
    if (selectedLlmId.value == null) {
      const def = (opts as any[]).find(o => o.is_default)
      if (def) selectedLlmId.value = def.id
    }
  } catch (e: any) {
    console.error('拉模型列表失败', e)
    ElMessage.warning(`模型列表加载失败：${e?.response?.data?.detail || e?.message || e}`)
  }
}

async function loadSession(id: number) {
  try {
    const data = await aiChatApi.getSession(id)
    currentSession.value = data.session
    messages.value = data.messages
    toolCalls.value = data.tool_calls
    attachments.value = data.attachments
    artifacts.value = data.artifacts
    // 切到的 session 显式绑了 llm → 用 session 的；否则保留全局 selectedLlmId
    if (data.session.selected_llm_config_id != null) {
      selectedLlmId.value = data.session.selected_llm_config_id
    }
    transientItems.value = []
    streamingText.value = ''
    if (route.params.id !== String(id)) {
      router.replace(`/ai-chat/${id}`)
    }
    await nextTick()
    scrollBottom()
  } catch (e) {
    console.error(e)
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

async function onCreateSession(mode: SessionFilter | string = 'chat') {
  const targetMode: 'chat' | 'cowork' = mode === 'cowork' ? 'cowork' : 'chat'
  const s = await aiChatApi.createSession({
    selected_llm_config_id: selectedLlmId.value,
    mode: targetMode,
  })
  sessions.value.unshift(s)
  // 切换 tab 到对应模式，让新建的会话出现在视野里
  sessionsFilter.value = targetMode
  await loadSession(s.id)
}

async function onChangeLlm() {
  // 没当前会话：只更新本地 selectedLlmId（作为新建会话的默认模型）
  if (!currentSession.value) return
  const updated = await aiChatApi.updateSession(currentSession.value.id, { selected_llm_config_id: selectedLlmId.value })
  currentSession.value.selected_llm_config_id = updated.selected_llm_config_id
}

function onFilesSelected(e: Event) {
  const input = e.target as HTMLInputElement
  if (!input.files) return
  pendingFiles.value.push(...Array.from(input.files))
  input.value = ''
}

async function onSend() {
  if (!currentSession.value || !canSend.value) return
  const text = inputText.value.trim()
  inputText.value = ''
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
    // 重新拉一次 session 拿到完整持久化数据（messages + tool_calls + artifacts）
    if (currentSession.value) await loadSession(currentSession.value.id)
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
      ElMessage.error(data.error || '出错了')
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

const canSendArtifactToBuilder = computed(() =>
  !!activeArtifactName.value
  && !!activeArtifactContent.value
  && /\.md$/i.test(activeArtifactName.value)
)

// 让 AI 用 aPaaS 标准规范重写当前 artifact —— 把现有内容塞进一条消息，
// AI 会调 write_artifact 同名覆盖（后端自动 version+1）。
async function rewriteArtifactToSpec() {
  if (!canSendArtifactToBuilder.value || isSending.value) return
  if (!currentSession.value || !activeArtifactName.value) return
  const filename = activeArtifactName.value
  const content = activeArtifactContent.value
  if (!content) {
    ElMessage.warning('当前文档为空')
    return
  }
  inputText.value = (
    `请按 aPaaS Builder 的设计文档标准规范重写《${filename}》——\n` +
    `必须严格遵循 SYSTEM_PROMPT 中的 6 章节顺序、表头、字段编码与命名约束；` +
    `数据模型只描述数据库怎么存，字典/组件/关联都写到「五、表单定义」里；` +
    `任何"数据单选/数据选择/关联表单"字段引用的目标模型，都必须先在 ## 四、数据模型 中显式定义，` +
    `否则改成单行输入；缺信息留空单元格即可，不要写"未定义"、"待定"等占位文字。\n` +
    `重写完用 write_artifact 同名（${filename}）覆盖保存（会自动 +1 版本）。\n\n` +
    `当前版本内容如下：\n\n\`\`\`markdown\n${content}\n\`\`\``
  )
  await nextTick()
  onSend()
}

// 把右侧当前打开的设计文档送到 Builder：复用 store.pendingMarkdown 通道，
// ChatPage 的 onMounted 会自动把它当成 upload doc 处理。
async function sendArtifactToBuilder() {
  if (!canSendArtifactToBuilder.value) return
  previewStore.pendingMarkdown = {
    filename: activeArtifactName.value,
    content: activeArtifactContent.value,
  }
  ElMessage.success('已发送，正在打开 Builder...')
  await router.push({ path: '/chat', query: { from: 'aichat' } })
}

// inline 卡片的"→ Builder"：拿对应文件最新版本内容，再 push 到 pendingMarkdown
async function sendArtifactToBuilderByName(filename: string) {
  if (!currentSession.value) return
  try {
    const detail = await aiChatApi.getArtifact(currentSession.value.id, filename)
    if (!detail.content) {
      ElMessage.warning('设计文档为空')
      return
    }
    previewStore.pendingMarkdown = { filename, content: detail.content }
    ElMessage.success('已发送，正在打开 Builder...')
    await router.push({ path: '/chat', query: { from: 'aichat' } })
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

function autosizeTextarea() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 160) + 'px'
}

function scrollBottom() {
  const el = messagesRef.value
  if (el) el.scrollTop = el.scrollHeight
}

// 当前路由进来的 mode（影响欢迎语 / 默认开场提示）
const incomingMode = computed(() => {
  const m = typeof route.query.mode === 'string' ? route.query.mode : ''
  return m === 'cowork' ? 'cowork' : 'chat'
})

// ── Lifecycle ──

onMounted(async () => {
  await Promise.all([loadSessions(), loadLlmOptions()])
  const idParam = route.params.id ? Number(route.params.id) : null
  if (idParam) {
    await loadSession(idParam)
  }
  // 从 Landing 页带过来的首条 prompt + 可选附件：建会话 → 上传附件 → 把 prompt 发出去
  const incomingPrompt = typeof route.query.prompt === 'string' ? route.query.prompt.trim() : ''
  const incomingFiles = (previewStore.pendingAiChatFiles || []).slice()
  const incomingFromCowork = incomingMode.value === 'cowork'
  if (!currentSession.value && (incomingPrompt || incomingFiles.length || incomingFromCowork)) {
    try {
      const created = await aiChatApi.createSession({
        selected_llm_config_id: selectedLlmId.value,
        ...(incomingFromCowork ? { mode: 'cowork' as const } : {}),
      })
      sessions.value.unshift(created)
      await loadSession(created.id)
      // 把 Landing 带过来的附件搬进 pendingFiles，让 onSend 一并处理
      if (incomingFiles.length) {
        pendingFiles.value.push(...incomingFiles)
        previewStore.pendingAiChatFiles = []
      }
      // cowork 模式：用户已经传了材料，给一句默认开场让 agent 自动开始消化
      if (incomingFromCowork && !incomingPrompt && pendingFiles.value.length) {
        inputText.value = '材料都在附件里了，请按 cowork 流程：先并行读完所有附件，给我综合摘要 + 批量澄清问题。'
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
  }
})
</script>

<style scoped>
/* AI Chat 主题色映射 — 通过 v-bind 注入 .theme-dark / .theme-light class 来切换。
   品牌色统一用全局 --t-brand 跟随。 */
.ai-chat-app {
  --ac-brand: var(--t-brand, #5a78ff);
  --ac-brand-soft: color-mix(in srgb, var(--ac-brand) 16%, transparent);
  --ac-brand-glow: color-mix(in srgb, var(--ac-brand) 20%, transparent);

  display: grid;
  grid-template-columns: 240px 1fr auto;  /* 右栏 auto 自适应：无内容时 0 宽 */
  height: 100vh;
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
.artifacts-toggle {
  appearance: none;
  background: var(--ac-input);
  border: 1px solid var(--ac-border-strong);
  color: var(--ac-text-mute);
  padding: 5px 12px;
  border-radius: 6px;
  font-size: 12.5px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  transition: all 0.15s;
}
.artifacts-toggle:hover { color: var(--ac-text); border-color: var(--ac-border-strong); }
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
  border: 1px solid var(--ac-border-strong);
  color: var(--ac-text-mute);
  padding: 3px 8px;
  border-radius: 5px;
  font-size: 12px;
  cursor: pointer;
  outline: none;
}
.model-select-inline:hover { border-color: var(--ac-border-strong); color: var(--ac-text); }
.input-foot .hint { color: var(--ac-text-faint); font-size: 11.5px; }
.input-foot .timer { color: var(--ac-brand); }

/* ─── Aside left ─── */
.aside-left {
  background: var(--ac-panel);
  border-right: 1px solid var(--ac-border);
  display: flex;
  flex-direction: column;
  padding: 16px 12px;
  gap: 12px;
  overflow: hidden;
}
.ai-chat-app.aside-collapsed .aside-left {
  padding: 12px 4px;
  gap: 6px;
}
.aside-head {
  display: flex; align-items: center; justify-content: space-between; gap: 4px;
}
.aside-toggle {
  appearance: none; background: transparent; border: none; color: var(--ac-text-faint);
  font-size: 14px; cursor: pointer; padding: 2px 8px; border-radius: 5px;
  line-height: 1; flex-shrink: 0;
}
.aside-toggle:hover { background: var(--ac-border-faint); color: var(--ac-text); }
.aside-rail {
  display: flex; flex-direction: column; align-items: center; gap: 6px; height: 100%;
}
.rail-spacer { flex: 1; }
.rail-btn {
  width: 32px; height: 32px;
  background: transparent; border: 1px solid transparent; color: var(--ac-text-mute);
  border-radius: 6px; cursor: pointer; font-size: 14px;
  display: grid; place-items: center; line-height: 1;
  transition: all 0.12s;
}
.rail-btn:hover { background: var(--ac-border-faint); color: var(--ac-text); border-color: var(--ac-border); }
.brand { display: flex; align-items: center; gap: 8px; padding: 4px 8px; font-weight: 600; }
.brand-dot { width: 8px; height: 8px; background: #f0824a; border-radius: 2px; }
.new-btn {
  background: var(--ac-btn); border: 1px solid var(--ac-border); color: var(--ac-text);
  padding: 8px 12px; border-radius: 8px; font-size: 13px; cursor: pointer; text-align: left;
}
.new-btn:hover { background: var(--ac-border-faint); }
.new-btn {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  gap: 6px;
}
.new-btn-caret {
  color: var(--ac-text-faint);
  font-size: 11px;
  margin-left: auto;
  transform: translateY(-1px);
}
.new-session-option {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 2px 0;
  min-width: 180px;
}
.new-session-option-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary, #1f2937);
}
.new-session-option-hint {
  font-size: 11.5px;
  color: var(--el-text-color-secondary, #6b7280);
}

.session-filter-tabs {
  display: flex;
  gap: 4px;
  margin: 8px 0 6px;
  padding: 3px;
  background: var(--ac-border-faint);
  border-radius: 8px;
}
.filter-tab {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 5px 6px;
  border: 0;
  background: transparent;
  color: var(--ac-text-mute);
  font-size: 11.5px;
  border-radius: 5px;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
  white-space: nowrap;
}
.filter-tab:hover { color: var(--ac-text); }
.filter-tab.active {
  background: var(--ac-panel);
  color: var(--ac-text);
  box-shadow: 0 1px 2px rgba(0,0,0,0.06);
}
.filter-tab-count {
  font-size: 10px;
  color: var(--ac-text-faint);
  background: var(--ac-border);
  padding: 0 5px;
  border-radius: 8px;
  line-height: 14px;
  min-width: 14px;
  text-align: center;
}
.filter-tab.active .filter-tab-count {
  background: color-mix(in srgb, var(--ac-brand) 16%, transparent);
  color: var(--ac-brand);
}

.session-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 2px; }
.session-item {
  padding: 7px 10px; border-radius: 6px; color: var(--ac-text-mute); cursor: pointer; font-size: 13px;
  display: flex; align-items: center; gap: 4px;
  position: relative;
}
.session-item:hover { background: var(--ac-border-faint); }
.session-item.active { background: var(--ac-btn); color: var(--ac-text); }
.session-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.session-mode-badge {
  font-size: 13px;
  line-height: 1;
  flex-shrink: 0;
  color: #c2630b;
}
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
.mode-icon {
  font-size: 14px;
  margin-right: 6px;
  vertical-align: -2px;
}
.mode-icon.chat { color: var(--el-color-primary, #409eff); }
.mode-icon.cowork { color: #c2630b; }
.new-session-option-title {
  display: flex;
  align-items: center;
}
.filter-tab-icon {
  font-size: 12px;
  margin-right: 2px;
}
.session-menu-btn {
  appearance: none;
  background: transparent;
  border: none;
  color: var(--ac-text-faint);
  font-size: 13px;
  cursor: pointer;
  padding: 2px 5px;
  border-radius: 4px;
  opacity: 0;
  transition: opacity 0.15s, background 0.15s, color 0.15s;
  flex-shrink: 0;
}
.session-item:hover .session-menu-btn { opacity: 1; }
.session-menu-btn:hover { background: var(--ac-border-strong); color: var(--ac-text); }
.session-menu-btn.danger:hover { background: rgba(248,113,113,0.18); color: #f87171; }
.empty-hint { color: var(--ac-text-faint); font-size: 12.5px; padding: 12px 8px; }
.aside-foot { padding-top: 12px; border-top: 1px solid var(--ac-border); }
.back-btn { background: transparent; border: none; color: var(--ac-text-mute); cursor: pointer; font-size: 12.5px; }
.back-btn:hover { color: var(--ac-text); }

/* ─── Chat main ─── */
.chat-main { display: flex; flex-direction: column; overflow: hidden; }
.chat-header {
  padding: 12px 24px; border-bottom: 1px solid var(--ac-border);
  display: flex; align-items: center; justify-content: space-between;
}
.chat-title { font-size: 14px; font-weight: 500; }
.title-placeholder { color: var(--ac-text-faint); }
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
.welcome { max-width: 600px; margin: 80px auto; padding: 0 24px; text-align: center; color: var(--ac-text-mute); }
.welcome h2 { color: var(--ac-text); }

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
.input-area { border-top: 1px solid var(--ac-border); padding: 16px 24px 20px; }
.input-card {
  max-width: 760px; margin: 0 auto;
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
  width: 32px; height: 32px; border-radius: 8px; background: var(--ac-brand);
  border: none; color: var(--ac-text); cursor: pointer; display: grid; place-items: center;
  flex-shrink: 0; transition: all 0.15s;
}
.send-btn:hover:not(:disabled) { transform: translateY(-1px); }
.send-btn:disabled { opacity: 0.3; cursor: not-allowed; }
.send-btn.stop { background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%); }

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
