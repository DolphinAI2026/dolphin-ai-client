<template>
  <div class="agent-conversation" :class="{ 'theme-dark': themeStore.isDark }">
    <div class="ac-list" ref="listRef" @scroll="onScroll">
      <slot name="list-prefix" />

      <div v-if="!timeline.length && !loading" class="ac-empty">
        <slot name="empty">
          <div class="ac-empty-default">
            <h2>{{ emptyTitle || '👋 开始对话' }}</h2>
            <p>{{ emptyHint || '在下方输入问题或描述需求。' }}</p>
          </div>
        </slot>
      </div>

      <template v-for="(item, idx) in timeline" :key="itemKey(item, idx)">
        <!-- ─── tool group：连续同名工具折叠 ─── -->
        <div v-if="isGroup(item)" class="ac-row assistant">
          <div class="ac-avatar tool">⚒</div>
          <div class="ac-bubble process">
            <div class="ac-tool-group" :class="{ expanded: isGroupOpen(item.id, item), running: groupRunning(item) }">
              <div class="ac-tool-head" @click="toggleGroup(item.id, item)">
                <span class="ac-tool-icon">{{ toolIcon(item.name) }}</span>
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
            <div class="ac-bubble user-bubble">
              <div class="ac-text">{{ item.content }}</div>
              <div v-if="item.attachments && item.attachments.length" class="ac-attach-chips">
                <span v-for="a in item.attachments" :key="a.id ?? a.filename" class="ac-attach-chip">
                  <span class="icon">{{ a.kind === 'image' ? '🖼️' : '📄' }}</span>
                  <span class="name">{{ a.filename }}</span>
                </span>
              </div>
              <slot name="user-extra" :message="item" />
            </div>
          </div>

          <!-- assistant -->
          <div v-else-if="item.kind === 'assistant' || item.kind === 'streaming'" class="ac-row assistant">
            <div class="ac-avatar">AI</div>
            <div class="ac-bubble">
              <div class="ac-text" v-html="renderMd(item.content || '')"></div>
              <span v-if="item.kind === 'streaming' || item.streaming" class="ac-cursor"></span>
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

          <!-- tool -->
          <div v-else-if="item.kind === 'tool' && item.tool" class="ac-row assistant">
            <div class="ac-avatar tool">⚒</div>
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
            <div class="ac-avatar tool">📄</div>
            <div class="ac-bubble process">
              <slot name="artifact" :artifact="item.artifact" :message="item">
                <div class="ac-artifact-card" @click="$emit('open-artifact', item.artifact, item)">
                  <div class="ac-art-head">
                    <span class="ac-art-icon">📄</span>
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
          <div class="ac-avatar">AI</div>
          <div class="ac-bubble">
            <div class="ac-typing">
              <span class="dot"></span><span class="dot"></span><span class="dot"></span>
            </div>
          </div>
        </slot>
      </div>

      <slot name="list-suffix" />
    </div>

    <slot name="footer" />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { marked } from 'marked'
import { useThemeStore } from '@/stores/theme'
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
}>()

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

function toolIcon(name: string): string {
  const n = (name || '').toLowerCase()
  if (n.includes('read') || n.includes('cat')) return '📖'
  if (n.includes('write') || n.includes('edit')) return '✏️'
  if (n.includes('bash') || n.includes('exec') || n.includes('run')) return '⚡'
  if (n.includes('search') || n.includes('grep') || n.includes('find')) return '🔍'
  if (n.includes('list') || n.includes('ls')) return '📋'
  if (n.includes('todo')) return '✅'
  if (n.includes('ask')) return '❓'
  return '⚒'
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

onMounted(() => {
  scrollToBottom(true)
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
  border-radius: 8px;
  background: var(--t-brand-soft, rgba(99, 102, 241, 0.16));
  color: var(--t-brand, #6366f1);
  font-size: 11px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.ac-avatar.tool {
  background: rgba(245, 158, 11, 0.16);
  color: #b45309;
}
.ac-avatar.thinking {
  background: rgba(156, 163, 175, 0.18);
  color: #6b7280;
}
.ac-avatar.error {
  background: rgba(239, 68, 68, 0.16);
  color: #b91c1c;
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
  /* 长 URL / hash / 无空格中英文混合都强制在字符内换行，
     不允许气泡内容撑破 max-width */
  overflow-wrap: anywhere;
  word-break: break-word;
}
.ac-bubble.user-bubble {
  background: var(--t-brand-soft, rgba(99, 102, 241, 0.14));
  border-color: rgba(99, 102, 241, 0.22);
  color: var(--t-text-primary);
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
  color: #4f5fe0;
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

.ac-typing {
  display: inline-flex;
  gap: 4px;
  padding: 4px 0;
}
.ac-typing .dot {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: var(--t-text-muted);
  opacity: 0.4;
  animation: ac-typing 1.2s infinite;
}
.ac-typing .dot:nth-child(2) { animation-delay: 0.15s; }
.ac-typing .dot:nth-child(3) { animation-delay: 0.3s; }
@keyframes ac-typing {
  0%, 60%, 100% { opacity: 0.3; transform: translateY(0); }
  30% { opacity: 1; transform: translateY(-3px); }
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
