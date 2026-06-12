<template>
  <div class="agent-conversation" :class="{ 'theme-dark': themeStore.isDark }">
    <div class="ac-list" ref="listRef" @scroll="onScroll">
      <slot name="list-prefix" />

      <div v-if="!timeline.length && !loading" class="ac-empty">
        <slot name="empty">
          <div class="ac-empty-default">
            <h2><AppIcon v-if="!emptyTitle" name="wave" :size="18" /> {{ emptyTitle || '开始对话' }}</h2>
            <p>{{ emptyHint || '在下方输入问题或描述需求。' }}</p>
          </div>
        </slot>
      </div>

      <template v-for="(item, idx) in timeline" :key="itemKey(item, idx)">
        <!-- ─── tool group：连续同名工具折叠 ─── -->
        <div v-if="isGroup(item)" class="ac-row assistant tool-row">
          <div class="ac-avatar-spacer"></div>
          <div class="ac-bubble process">
            <div class="ac-tool-group" :class="{ expanded: isGroupOpen(item.id, item), running: groupRunning(item) }">
              <div class="ac-tool-head" @click="toggleGroup(item.id, item)">
                <span class="ac-tool-icon"><AppIcon :name="toolIcon(item.name)" :size="13" /></span>
                <span class="ac-tool-name">{{ item.name }}</span>
                <span class="ac-group-count">×{{ item.tools.length }}</span>
                <span class="ac-tool-args">{{ groupSummary(item) }}</span>
                <span class="ac-tool-toggle">▶</span>
              </div>
              <div v-if="isGroupOpen(item.id, item)" class="ac-group-body">
                <ToolCard
                  v-for="t in item.tools"
                  :key="(t.id ?? t.name) + ''"
                  :tool="t"
                  mini
                  :expanded="isToolOpen(String(t.id ?? ''), t)"
                  @toggle="toggleTool(String(t.id ?? ''), t)"
                />
              </div>
            </div>
          </div>
        </div>

        <!-- ─── 常规消息 ─── -->
        <template v-else>
          <!-- user -->
          <div v-if="item.kind === 'user'" class="ac-row user">
            <div class="ac-user-wrap">
              <div class="ac-bubble user-bubble">
                <div class="ac-text">{{ item.content }}</div>
                <div v-if="item.attachments && item.attachments.length" class="ac-attach-chips">
                  <span v-for="a in item.attachments" :key="a.id ?? a.filename" class="ac-attach-chip">
                    <img v-if="a.kind === 'image' && a.url" class="thumb" :src="a.url" :alt="a.filename" />
                    <span v-else class="icon"><AppIcon :name="a.kind === 'image' ? 'image' : 'file'" :size="13" /></span>
                    <span class="name">{{ a.filename }}</span>
                  </span>
                </div>
                <slot name="user-extra" :message="item" />
              </div>
              <div class="ac-user-meta">
                <span class="ac-user-time" v-if="item.timestamp">{{ formatTime(item.timestamp) }}</span>
              </div>
            </div>
            <div class="ac-user-tag">我</div>
          </div>

          <!-- assistant — 对话界面风格：方形蓝头像 + 无气泡 markdown 直渲 -->
          <div v-else-if="item.kind === 'assistant' || item.kind === 'streaming'" class="ac-row assistant">
            <div class="ac-avatar brand">A</div>
            <div class="ac-assistant-wrap">
              <div class="ac-bubble assistant-naked">
                <div class="ac-text" v-html="renderMd(item.content || '')"></div>
                <span v-if="item.kind === 'streaming' || item.streaming" class="ac-cursor"></span>
              </div>
              <!-- 流式完成才显示反馈按钮（避免还在生成就被复制）-->
              <div
                v-if="item.kind === 'assistant' && !item.streaming && (item.content || '').trim().length > 0"
                class="ac-feedback"
              >
                <button class="ac-fb-btn" :title="'复制'" @click="onCopyMessage(item)">
                  <AppIcon :name="copiedId === (item.id ?? '') ? 'check' : 'clipboard'" :size="13" />
                </button>
                <button class="ac-fb-btn" :title="'反馈：回复不准确'" @click="$emit('feedback', item)"><AppIcon name="thumbs-down" :size="13" /></button>
                <button
                  v-if="item.meta?.run_id"
                  class="ac-fb-btn"
                  :title="'查看本次 trace'"
                  @click="$emit('open-trace', item)"
                ><AppIcon name="search" :size="13" /></button>
              </div>
            </div>
          </div>

          <!-- thinking -->
          <div v-else-if="item.kind === 'thinking'" class="ac-row assistant">
            <div class="ac-avatar thinking">…</div>
            <div class="ac-bubble">
              <slot name="thinking" :thinking="item.thinking">
                <div class="ac-thinking" v-html="renderMd(item.thinking?.text || item.content || '')"></div>
              </slot>
            </div>
          </div>

          <!-- tool — 对话界面风格：无独立头像，工具卡左缩进与 AI 头像对齐 -->
          <div v-else-if="item.kind === 'tool' && item.tool" class="ac-row assistant tool-row">
            <div class="ac-avatar-spacer"></div>
            <div class="ac-bubble process">
              <slot name="tool-renderer" :tool="item.tool" :message="item">
                <ToolCard
                  :tool="item.tool"
                  :expanded="isToolOpen(String(item.tool.id ?? item.id), item.tool)"
                  @toggle="toggleTool(String(item.tool.id ?? item.id), item.tool)"
                />
              </slot>
            </div>
          </div>

          <!-- ask -->
          <div v-else-if="item.kind === 'ask' && item.ask" class="ac-row assistant">
            <div class="ac-avatar">?</div>
            <div class="ac-bubble">
              <div class="ac-ask-card">
                <div class="ac-ask-q">{{ item.ask.question }}</div>
                <div v-if="item.ask.options?.length" class="ac-ask-options">
                  <button
                    v-for="opt in item.ask.options"
                    :key="opt"
                    class="ac-ask-opt"
                    :class="{ answered: item.ask.answered === opt, disabled: item.ask.answered }"
                    :disabled="!!item.ask.answered"
                    @click="$emit('answer-ask', opt, item)"
                  >{{ opt }}</button>
                </div>
              </div>
            </div>
          </div>

          <!-- artifact card（inline） -->
          <div v-else-if="item.kind === 'artifact' && item.artifact" class="ac-row assistant">
            <div class="ac-avatar tool"><AppIcon name="file" :size="14" /></div>
            <div class="ac-bubble process">
              <slot name="artifact" :artifact="item.artifact" :message="item">
                <div class="ac-artifact-card" @click="$emit('open-artifact', item.artifact, item)">
                  <div class="ac-art-head">
                    <span class="ac-art-icon"><AppIcon name="file" :size="13" /></span>
                    <span class="ac-art-name">{{ item.artifact.filename }}</span>
                    <span v-if="item.artifact.version" class="ac-art-version">v{{ item.artifact.version }}</span>
                    <span class="ac-art-arrow">›</span>
                  </div>
                  <div v-if="item.artifact.preview" class="ac-art-preview">{{ item.artifact.preview }}</div>
                </div>
              </slot>
            </div>
          </div>

          <!-- error / status -->
          <div v-else-if="item.kind === 'error'" class="ac-row assistant">
            <div class="ac-avatar error">!</div>
            <div class="ac-bubble error">
              <div class="ac-text">{{ item.content }}</div>
            </div>
          </div>
          <div v-else-if="item.kind === 'status'" class="ac-row status">
            <div class="ac-status">{{ item.content }}</div>
          </div>

          <!-- custom slot -->
          <div v-else-if="item.kind === 'custom'" class="ac-row">
            <slot name="custom" :message="item" />
          </div>
        </template>
      </template>

      <!-- typing indicator -->
      <div v-if="typing" class="ac-row assistant">
        <slot name="typing">
          <!-- 克制的三点 typing 指示器（对齐 assistant 列）+ 计时,干净专业、Coding/Builder/AIChat 一致 -->
          <div class="ac-typing-row">
            <div class="ac-typing" aria-label="AI 正在思考">
              <span></span><span></span><span></span>
            </div>
            <span v-if="(typingSeconds || 0) > 0" class="ac-typing-secs">AI 思考中 {{ typingSeconds }}s</span>
          </div>
        </slot>
      </div>

      <slot name="list-suffix" />
    </div>

    <slot name="footer" />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { marked } from 'marked'
import { useThemeStore } from '@/stores/theme'
import AppIcon from '@/components/common/AppIcon.vue'
import ToolCard from './agent-conversation/ToolCard.vue'
import type { AgentMessage, AgentToolPayload, AgentToolGroup, AgentTimelineItem } from './agent-conversation/types'

marked.setOptions({ breaks: true, gfm: true })

const props = withDefaults(defineProps<{
  messages: AgentMessage[]
  typing?: boolean
  loading?: boolean
  /** 是否把连续同名 tool 折叠成 group（AI Chat 风格） */
  toolGrouping?: boolean
  /** 自动滚到底（用户主动向上滚则暂停） */
  autoScroll?: boolean
  /** running 状态的工具/分组默认展开（用户显式收起后保持收起） */
  defaultOpenRunning?: boolean
  emptyTitle?: string
  emptyHint?: string
  /** 流式生成已用秒数(给 typing 指示器显示「AI 思考中 Ns」,对齐 Builder)。0/省略则不显示 */
  typingSeconds?: number
}>(), {
  typing: false,
  loading: false,
  toolGrouping: false,
  autoScroll: true,
  defaultOpenRunning: true,
})

defineEmits<{
  (e: 'answer-ask', option: string, message: AgentMessage): void
  (e: 'open-artifact', artifact: any, message: AgentMessage): void
  (e: 'scroll', payload: { atBottom: boolean; scrollTop: number }): void
  (e: 'feedback', message: AgentMessage): void
  (e: 'open-trace', message: AgentMessage): void
}>()

const copiedId = ref<string | number | ''>('')
async function onCopyMessage(item: AgentMessage) {
  const text = (item.content || '').trim()
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    // 老浏览器降级：execCommand
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    try { document.execCommand('copy') } catch { /* ignore */ }
    document.body.removeChild(ta)
  }
  copiedId.value = item.id ?? ''
  setTimeout(() => { if (copiedId.value === (item.id ?? '')) copiedId.value = '' }, 1500)
}

const themeStore = useThemeStore()
const listRef = ref<HTMLElement>()

// 三态：'open' / 'closed' / undefined（未显式设置，按默认规则决定）
const toolState = ref<Record<string, 'open' | 'closed'>>({})
const groupState = ref<Record<string, 'open' | 'closed'>>({})

function isToolOpen(id: string, tool?: AgentToolPayload): boolean {
  const explicit = toolState.value[id]
  if (explicit) return explicit === 'open'
  return !!props.defaultOpenRunning && tool?.status === 'running'
}
function isGroupOpen(id: string, group?: AgentToolGroup): boolean {
  const explicit = groupState.value[id]
  if (explicit) return explicit === 'open'
  return !!props.defaultOpenRunning && !!group && groupRunning(group)
}
function toggleTool(id: string, tool?: AgentToolPayload) {
  toolState.value[id] = isToolOpen(id, tool) ? 'closed' : 'open'
}
function toggleGroup(id: string, group?: AgentToolGroup) {
  groupState.value[id] = isGroupOpen(id, group) ? 'closed' : 'open'
}

// ── 把同名连续 tool 折叠成 tool_group ──
const timeline = computed<AgentTimelineItem[]>(() => {
  if (!props.toolGrouping) return props.messages
  const out: AgentTimelineItem[] = []
  for (const msg of props.messages) {
    if (msg.kind === 'tool' && msg.tool) {
      const prev = out[out.length - 1]
      if (prev && (prev as any).kind === 'tool_group' && (prev as AgentToolGroup).name === msg.tool.name) {
        ;(prev as AgentToolGroup).tools.push(msg.tool)
        continue
      }
      // 看下一条是否同名 → 启动 group；否则保持单条
      out.push(msg)
      continue
    }
    out.push(msg)
  }
  // 再扫一次：把相邻的同名单 tool 合并成 group（>=2 个才合并）
  const merged: AgentTimelineItem[] = []
  for (const it of out) {
    const last = merged[merged.length - 1]
    if (
      it.kind === 'tool' && it.tool &&
      last && last.kind === 'tool' && last.tool && last.tool.name === it.tool.name
    ) {
      const group: AgentToolGroup = {
        kind: 'tool_group',
        id: 'g_' + (last.id || last.tool.id || merged.length),
        name: it.tool.name,
        tools: [last.tool, it.tool],
      }
      merged[merged.length - 1] = group as any
    } else if (
      it.kind === 'tool' && it.tool &&
      last && (last as any).kind === 'tool_group' && (last as AgentToolGroup).name === it.tool.name
    ) {
      ;(last as AgentToolGroup).tools.push(it.tool)
    } else {
      merged.push(it)
    }
  }
  return merged
})

function isGroup(it: AgentTimelineItem): it is AgentToolGroup {
  return (it as any).kind === 'tool_group'
}
function groupRunning(g: AgentToolGroup) {
  return g.tools.some(t => t.status === 'running')
}
function groupSummary(g: AgentToolGroup) {
  const briefs = g.tools.map(t => t.argsBrief).filter(Boolean) as string[]
  if (!briefs.length) return ''
  if (briefs.length <= 3) return briefs.join(', ')
  return briefs.slice(0, 3).join(', ') + ` +${briefs.length - 3}`
}

function itemKey(item: AgentTimelineItem, idx: number): string {
  if (isGroup(item)) return 'g_' + item.id
  return 'm_' + (item.id ?? idx)
}

function renderMd(text: string): string {
  if (!text) return ''
  try {
    return marked.parse(text) as string
  } catch {
    return text
  }
}

function formatTime(ts: number | string | undefined): string {
  if (!ts) return ''
  try {
    const d = typeof ts === 'number' ? new Date(ts) : new Date(ts)
    if (Number.isNaN(d.getTime())) return ''
    const hh = String(d.getHours()).padStart(2, '0')
    const mm = String(d.getMinutes()).padStart(2, '0')
    return `${hh}:${mm}`
  } catch {
    return ''
  }
}

function toolIcon(name: string): string {
  const n = (name || '').toLowerCase()
  if (n.includes('read') || n.includes('cat')) return 'book-open'
  if (n.includes('write') || n.includes('edit')) return 'pencil'
  if (n.includes('bash') || n.includes('exec') || n.includes('run')) return 'zap'
  if (n.includes('search') || n.includes('grep') || n.includes('find')) return 'search'
  if (n.includes('list') || n.includes('ls')) return 'clipboard'
  if (n.includes('todo')) return 'check-circle'
  if (n.includes('ask')) return 'help-circle'
  return 'tool'
}

// ── 自动滚动 ──
const userScrolledUp = ref(false)
function isAtBottom(el: HTMLElement) {
  return el.scrollHeight - el.scrollTop - el.clientHeight < 40
}
function onScroll(e: Event) {
  const el = e.target as HTMLElement
  userScrolledUp.value = !isAtBottom(el)
}
async function scrollToBottom(force = false) {
  if (!props.autoScroll && !force) return
  const el = listRef.value
  if (!el) return
  if (userScrolledUp.value && !force) return
  await nextTick()
  el.scrollTop = el.scrollHeight
}

watch(() => props.messages.length, () => {
  scrollToBottom()
})
watch(() => props.typing, () => {
  if (props.typing) scrollToBottom()
})

// 2026-05-16：监听最后一条消息 content / tool result / thinking 长度变化 ——
// SSE 流式 append assistant_delta 时 messages.length 不变（只是某条 message.content
// 在长大），原来的 length watch 触发不到，导致流式过程中 scroll 不跟。
watch(
  () => {
    const arr = props.messages
    if (!arr.length) return 0
    const last = arr[arr.length - 1]
    const c = typeof last.content === 'string' ? last.content.length : 0
    const t = last.thinking?.text?.length || 0
    const r = last.tool?.result?.length || 0
    return c + t + r
  },
  () => { scrollToBottom() },
)

// ResizeObserver 兜底 —— 哪怕上面 watch 漏触发（比如自定义 slot 渲染高度变化），
// listRef 高度增长就跟着 scroll，保证流式内容永远可见。
let resizeObserver: ResizeObserver | null = null

onMounted(() => {
  scrollToBottom(true)
  if (listRef.value && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => { scrollToBottom() })
    resizeObserver.observe(listRef.value)
  }
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
})

defineExpose({
  scrollToBottom,
  expandTool: (id: string | number) => { toolState.value[String(id)] = 'open' },
  collapseAllTools: () => { toolState.value = {} },
})
</script>

<style scoped>
.agent-conversation {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  position: relative;
}
.ac-list {
  flex: 1;
  min-height: 0;
  min-width: 0;
  /* overflow-x:hidden 防止单条消息里的超长 URL / 无空格字符撑开整个列表，
     导致整个对话区横向溢出（之前 bug：粘了 600+ 字符的图片直链 URL，
     一条消息把整个对话流推出屏幕外）*/
  overflow-x: hidden;
  overflow-y: auto;
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.ac-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  min-width: 0;
  max-width: 100%;
}
.ac-row.user {
  justify-content: flex-end;
}
.ac-row.status {
  justify-content: center;
}

.ac-avatar {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  background: var(--t-brand-soft, rgba(59, 130, 246, 0.14));
  color: var(--t-brand, #3b82f6);
  font-size: 11px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
/* 对话界面风格：assistant 蓝色实底白字方形头像 'A' */
.ac-avatar.brand {
  background: var(--brand) !important;
  color: #fff !important;
  font-size: 13px;
  font-weight: 700;
}
/* 工具行不显头像，用 spacer 占位让 ToolCard 左缘跟 AI 消息文本左缘对齐 */
.ac-avatar-spacer {
  flex-shrink: 0;
  width: 28px;
  height: 1px;
}

/* 对话界面风格：assistant 消息 hover 时下方出现反馈按钮 */
.ac-assistant-wrap {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  min-width: 0;
  flex: 1;
}
.ac-feedback {
  display: flex;
  gap: 4px;
  margin-top: 6px;
  opacity: 0;
  transition: opacity 0.18s;
}
.ac-row.assistant:hover .ac-feedback {
  opacity: 1;
}
.ac-fb-btn {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: 1px solid transparent;
  background: transparent;
  color: rgba(116, 128, 171, 0.7);
  font-size: 13px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}
.ac-fb-btn:hover {
  background: rgba(116, 128, 171, 0.08);
  color: var(--text);
  border-color: rgba(116, 128, 171, 0.18);
}
.ac-avatar.tool {
  background: rgba(245, 158, 11, 0.16);
  color: var(--warn);
}
.ac-avatar.thinking {
  background: rgba(156, 163, 175, 0.18);
  color: var(--text-3);
}
.ac-avatar.error {
  background: rgba(239, 68, 68, 0.16);
  color: var(--err);
}

.ac-bubble {
  max-width: min(740px, 78%);
  min-width: 0;
  padding: 10px 14px;
  border-radius: 12px;
  background: var(--t-bg-elevated, #fff);
  border: 1px solid var(--t-border-soft, rgba(116, 128, 171, 0.16));
  font-size: 13.5px;
  line-height: 1.6;
  color: var(--t-text-primary);
  position: relative;
  overflow-wrap: anywhere;
  word-break: break-word;
}
/* 对话界面风格：assistant 消息无气泡 — markdown 直接渲染在背景上 */
.ac-bubble.assistant-naked {
  background: transparent;
  border-color: transparent;
  padding: 4px 0 0;
  max-width: min(880px, 92%);
}
/* 对话界面风格：user 消息浅灰圆角小气泡 */
.ac-bubble.user-bubble {
  background: rgba(116, 128, 171, 0.10);
  border-color: transparent;
  color: var(--t-text-primary);
  padding: 8px 14px;
  border-radius: 14px;
  /* 覆盖 .ac-bubble 默认的 anywhere/break-word（那个是为 AI 长 URL/hash 设的） */
  /* user 短文本"111"被强制单字符断成竖排 → 改回标准换行 */
  word-break: normal;
  overflow-wrap: break-word;
  white-space: pre-wrap;
  width: fit-content;
  max-width: 100%;
}
.ac-bubble.process {
  background: transparent;
  border-color: transparent;
  padding: 0;
  max-width: 100%;
  flex: 1;
}
.ac-bubble.error {
  background: rgba(239, 68, 68, 0.08);
  border-color: rgba(239, 68, 68, 0.24);
}

/* 对话界面风格：user 消息右侧"我"标签 + 下方时间戳 */
.ac-user-wrap {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  max-width: min(620px, 75%);
  /* 关键：不让 wrap 被父 flex row 压缩到子内容最小宽度（否则"1"会一个字一行）*/
  flex-shrink: 1;
  min-width: 0;
}
.ac-user-meta {
  margin-top: 4px;
  font-size: 11px;
  color: rgba(116, 128, 171, 0.7);
  padding-right: 4px;
}
.ac-user-tag {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  border-radius: 14px;
  background: rgba(116, 128, 171, 0.14);
  color: rgba(116, 128, 171, 0.85);
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
}

/* 三点 typing 指示器（流式生成中）+ 计时,克制干净 */
.ac-typing-row {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 8px 0 8px 38px;  /* 左缩进对齐 assistant 内容列 */
}
.ac-typing {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.ac-typing-secs {
  font-size: 12px;
  color: var(--t-text-muted, #94a3b8);
  font-variant-numeric: tabular-nums;  /* 数字等宽,秒数跳动不抖 */
  letter-spacing: 0.01em;
}
.ac-typing span {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--t-text-muted, #94a3b8);
  animation: ac-typing-bounce 1.3s ease-in-out infinite;
}
.ac-typing span:nth-child(2) { animation-delay: 0.16s; }
.ac-typing span:nth-child(3) { animation-delay: 0.32s; }
@keyframes ac-typing-bounce {
  0%, 70%, 100% { transform: translateY(0); opacity: 0.4; }
  35% { transform: translateY(-4px); opacity: 0.85; }
}

.ac-text :deep(p) { margin: 0 0 6px; }
.ac-text :deep(p:last-child) { margin-bottom: 0; }
.ac-text :deep(pre) {
  background: var(--t-bg-soft, rgba(15, 23, 42, 0.06));
  padding: 10px 12px;
  border-radius: 8px;
  overflow-x: auto;
  font-size: 12.5px;
  margin: 6px 0;
}
.ac-text :deep(code) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, monospace;
  font-size: 0.9em;
}
.ac-text :deep(ul), .ac-text :deep(ol) {
  margin: 6px 0;
  padding-left: 22px;
}

/* markdown 表格样式 — 之前缺，列粘一起没法看 */
.ac-text :deep(table) {
  border-collapse: collapse;
  margin: 10px 0;
  font-size: 12.5px;
  width: auto;
  max-width: 100%;
}
.ac-text :deep(table th),
.ac-text :deep(table td) {
  border: 1px solid rgba(116, 128, 171, 0.20);
  padding: 6px 12px;
  text-align: left;
  vertical-align: top;
  white-space: normal;     /* 允许长中文单元格换行,表格不再溢出窄列、不用横滚 */
  word-break: break-word;
}
.ac-text :deep(table th) {
  background: rgba(116, 128, 171, 0.06);
  font-weight: 600;
  color: inherit;  /* 继承 .ac-text 主题色 — 写死深色会在暗色模式黑字黑底看不见 */
}
.ac-text :deep(table tr:nth-child(even) td) {
  background: rgba(116, 128, 171, 0.025);
}
/* markdown blockquote 样式 */
.ac-text :deep(blockquote) {
  margin: 8px 0;
  padding: 6px 12px;
  border-left: 3px solid rgba(59, 130, 246, 0.5);
  background: rgba(59, 130, 246, 0.04);
  color: var(--text-2);
}
.ac-text :deep(blockquote p) { margin: 0; }
/* markdown headings — h2/h3 之间留点呼吸 */
.ac-text :deep(h1), .ac-text :deep(h2), .ac-text :deep(h3) {
  margin: 14px 0 6px;
  font-weight: 600;
}
.ac-text :deep(h2) { font-size: 15px; }
.ac-text :deep(h3) { font-size: 14px; }
.ac-text :deep(h2:first-child), .ac-text :deep(h3:first-child) { margin-top: 0; }
/* 行内 code */
.ac-text :deep(code:not(pre code)) {
  background: rgba(116, 128, 171, 0.10);
  padding: 1px 6px;
  border-radius: 4px;
}

.ac-cursor {
  display: inline-block;
  width: 7px;
  height: 14px;
  margin-left: 2px;
  background: var(--t-brand, #6366f1);
  vertical-align: -2px;
  animation: ac-blink 1.1s infinite;
}
@keyframes ac-blink {
  0%, 49% { opacity: 1; }
  50%, 100% { opacity: 0; }
}

.ac-thinking {
  font-size: 13px;
  color: var(--t-text-secondary);
  font-style: italic;
}

.ac-attach-chips {
  margin-top: 8px;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.ac-attach-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  font-size: 11px;
  background: var(--t-bg-soft, rgba(15, 23, 42, 0.06));
  border-radius: 6px;
  color: var(--t-text-secondary);
}
.ac-attach-chip .thumb {
  width: 28px;
  height: 20px;
  object-fit: cover;
  border-radius: 4px;
  border: 1px solid var(--t-border-soft, rgba(116, 128, 171, 0.22));
  background: var(--t-bg-base, #fff);
}

.ac-ask-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.ac-ask-q { font-size: 13.5px; color: var(--t-text-primary); }
.ac-ask-options {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.ac-ask-opt {
  border: 1px solid var(--t-border-soft, rgba(116, 128, 171, 0.22));
  background: var(--t-bg-elevated, #fff);
  color: var(--t-text-primary);
  padding: 5px 12px;
  font-size: 12px;
  border-radius: 999px;
  cursor: pointer;
  transition: background 0.14s, border-color 0.14s;
}
.ac-ask-opt:hover:not(:disabled) {
  background: rgba(99, 102, 241, 0.08);
  border-color: rgba(99, 102, 241, 0.32);
}
.ac-ask-opt.answered {
  background: rgba(99, 102, 241, 0.16);
  border-color: rgba(99, 102, 241, 0.42);
}
.ac-ask-opt:disabled {
  cursor: not-allowed;
  opacity: 0.65;
}

.ac-artifact-card {
  border: 1px solid var(--t-border-soft, rgba(116, 128, 171, 0.18));
  border-radius: 10px;
  padding: 10px 12px;
  background: var(--t-bg-elevated, #fff);
  cursor: pointer;
  transition: border-color 0.14s, background 0.14s;
  max-width: 480px;
}
.ac-artifact-card:hover {
  border-color: rgba(99, 102, 241, 0.42);
  background: rgba(99, 102, 241, 0.05);
}
.ac-art-head {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}
.ac-art-name { flex: 1; font-weight: 600; color: var(--t-text-primary); }
.ac-art-version {
  font-size: 11px;
  color: var(--t-text-muted);
  font-family: ui-monospace, monospace;
}
.ac-art-arrow { color: var(--t-text-muted); }
.ac-art-preview {
  margin-top: 6px;
  font-size: 12px;
  color: var(--t-text-secondary);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.ac-tool-group {
  border: 1px solid var(--t-border-soft, rgba(116, 128, 171, 0.18));
  border-radius: 10px;
  background: var(--t-bg-elevated, #fff);
  overflow: hidden;
}
.ac-tool-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  font-size: 12.5px;
}
.ac-tool-head:hover { background: rgba(99, 102, 241, 0.05); }
.ac-tool-icon { flex-shrink: 0; }
.ac-tool-name { font-weight: 600; color: var(--t-text-primary); }
.ac-tool-args { color: var(--t-text-muted); font-family: ui-monospace, monospace; font-size: 11.5px; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ac-tool-toggle {
  font-size: 9px;
  color: var(--t-text-muted);
  transition: transform 0.18s;
}
.ac-tool-group.expanded .ac-tool-toggle { transform: rotate(90deg); }
.ac-group-count {
  background: rgba(99, 102, 241, 0.12);
  color: var(--brand-text);
  padding: 1px 7px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 700;
}
.ac-group-body {
  padding: 4px 8px 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.ac-status {
  font-size: 11.5px;
  color: var(--t-text-muted);
  background: var(--t-bg-soft, rgba(15, 23, 42, 0.05));
  padding: 4px 10px;
  border-radius: 999px;
}

.ac-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
}
.ac-empty-default {
  text-align: center;
  color: var(--t-text-muted);
}
.ac-empty-default h2 {
  margin: 0 0 8px;
  font-size: 18px;
  color: var(--t-text-primary);
}
.ac-empty-default p {
  margin: 0;
  font-size: 13px;
}

/* dark theme */
.agent-conversation.theme-dark .ac-bubble {
  background: rgba(20, 24, 33, 0.92);
  border-color: rgba(148, 163, 184, 0.16);
}
.agent-conversation.theme-dark .ac-bubble.user-bubble {
  background: rgba(99, 102, 241, 0.22);
  border-color: rgba(124, 140, 255, 0.42);
}
.agent-conversation.theme-dark .ac-artifact-card,
.agent-conversation.theme-dark .ac-tool-group {
  background: rgba(20, 24, 33, 0.92);
  border-color: rgba(148, 163, 184, 0.16);
}
</style>
