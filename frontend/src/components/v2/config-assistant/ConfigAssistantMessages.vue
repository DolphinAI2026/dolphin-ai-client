<!-- frontend/src/components/v2/config-assistant/ConfigAssistantMessages.vue
     2026-05-24 从 ConfigAssistantPanel.vue 拆出 (refactor #9).
     主消息区 — 空态 + 消息列表 + thinking dot + plan card + hero CTA + change_plan info card. -->
<script setup lang="ts">
import { watch } from 'vue'
import type { ChatMsg } from './types'
import { renderMd } from '@/utils/markdown'
import { countModifyOps, extractPlan } from './composables/useConfigChat'

const props = defineProps<{
  messages: ChatMsg[]
  sending: boolean
  emptyHint: string
}>()

const emit = defineEmits<{
  (e: 'refresh-iframe'): void
}>()

// 截图大图查看 — 新 tab 打开 data URL
function openScreenshot(dataUrl: string) {
  try {
    const w = window.open()
    if (w) w.document.write(`<img src="${dataUrl}" style="max-width:100%;height:auto;" />`)
  } catch {
    /* popup blocked */
  }
}

// 2026-05-26 / 2026-05-27 P2: AI 调完工具自动刷预览 — 不再让用户点"刷新预览"按钮.
// 检测: 消息列表里出现一个 assistant 消息, !streaming + countModifyOps>0, 且
// 还没被自动刷过 (用 Set<id> 去重防多次触发). 满足就 emit refresh-iframe.
// 注: design-v4 后 ChatPage 同步 bump designerRefreshKey 让 5 个原生 panel re-mount,
// 不再纯依赖 iframe.reload — event 名暂留 'refresh-iframe' 不改 (兼容旧调用方).
const _autoRefreshed = new Set<number>()
watch(() => props.messages, (msgs) => {
  for (const m of msgs) {
    if (m.role !== 'assistant') continue
    if (m.streaming) continue
    if (!m.id || _autoRefreshed.has(m.id)) continue
    if (countModifyOps(m) <= 0) continue
    _autoRefreshed.add(m.id)
    // 略延 200ms 给 platform 端 API 真正落库
    setTimeout(() => emit('refresh-iframe'), 200)
  }
}, { deep: true, immediate: false })
</script>

<template>
  <div class="ca-scroll">
    <!-- 空态 -->
    <div v-if="messages.length === 0" class="ca-empty">
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 12a8 8 0 0 1-11.9 7L4 21l1.6-4.4A8 8 0 1 1 21 12z" />
      </svg>
      <div class="ca-empty-hint">{{ emptyHint }}</div>
    </div>

    <!-- 消息列表 -->
    <div
      v-for="m in messages"
      :key="m.id"
      class="ca-msg"
      :class="`ca-msg-${m.role}`"
    >
      <div class="ca-bubble">
        <!-- 工具卡片 chips -->
        <div
          v-if="m.role === 'assistant' && m.tool_trace && m.tool_trace.length"
          class="ca-tool-chips"
        >
          <span
            v-for="(t, i) in m.tool_trace"
            :key="i"
            class="ca-tool-chip"
            :class="t.ok ? 'ca-tool-chip-ok' : 'ca-tool-chip-err'"
            :title="t.summary"
          >
            {{ t.ok ? '✓' : '✗' }} {{ t.tool_name }}
          </span>
        </div>

        <!-- 浏览器截图直接渲染 (Claude in Chrome 风格) -->
        <div
          v-if="m.role === 'assistant' && m.tool_trace && m.tool_trace.some(t => t.image_data_url)"
          class="ca-screenshots"
        >
          <figure
            v-for="(t, i) in m.tool_trace.filter(t => t.image_data_url)"
            :key="'shot-' + i"
            class="ca-screenshot"
          >
            <img :src="t.image_data_url" alt="browser screenshot" @click="openScreenshot(t.image_data_url!)" />
            <figcaption>📸 {{ t.tool_name }}</figcaption>
          </figure>
        </div>

        <!-- streaming progress log: SSE 期间显示工具调用实时进度 -->
        <div
          v-if="m.streaming && m.progressLog && m.progressLog.length"
          class="ca-stream-log"
        >
          <div v-for="(l, i) in m.progressLog" :key="i" class="ca-stream-line">{{ l }}</div>
        </div>

        <!-- 2026-05-21 Phase 2: plan 卡片 — agent 给"我的计划:" 列表时单独渲染顶部 -->
        <template v-if="m.role === 'assistant' && m.content">
          <div v-if="extractPlan(m.content).planMd" class="ca-plan-card">
            <div class="ca-plan-head">
              <span class="ca-plan-icon">📋</span>
              <span class="ca-plan-title">执行计划</span>
              <span v-if="m.streaming" class="ca-plan-status">执行中…</span>
              <span v-else class="ca-plan-status ca-plan-status-done">已完成</span>
            </div>
            <div class="ca-plan-body" v-html="renderMd(extractPlan(m.content).planMd)" />
          </div>
          <div
            v-if="extractPlan(m.content).rest"
            class="ca-bubble-text"
            v-html="renderMd(extractPlan(m.content).rest)"
          />
        </template>
        <div v-else-if="m.content" class="ca-bubble-text" v-html="renderMd(m.content)" />
        <div v-else-if="m.streaming" class="ca-bubble-typing">
          <span class="ca-dot" /><span class="ca-dot" /><span class="ca-dot" />
        </div>

        <!-- 2026-05-21 Phase 2 / 2026-05-26 v2: 完成态 hero CTA.
             改自动刷预览, 不再让用户点按钮. 按钮位降级为"已自动刷新"被动提示 + 兜底手动按钮. -->
        <div
          v-if="m.role === 'assistant' && !m.streaming && countModifyOps(m) > 0"
          class="ca-hero-cta"
        >
          <div class="ca-hero-text">
            <span class="ca-hero-icon">✅</span>
            <span>已完成 <strong>{{ countModifyOps(m) }}</strong> 步调整 · 已自动刷新预览</span>
          </div>
          <button
            type="button"
            class="ca-hero-btn ca-hero-btn-subtle"
            @click="emit('refresh-iframe')"
            title="若预览没更新, 点这里手动刷新"
          >
            ↻
          </button>
        </div>

        <!-- 2026-05-21 Task #13: ChangePlan 纯信息卡片 (无按钮, agent 真要改配置直接调真工具) -->
        <div v-if="m.change_plan" class="ca-change-card ca-change-card-info">
          <div class="ca-change-title">📋 AI 给的方案分析</div>
          <ul v-if="m.actions_summary && m.actions_summary.length" class="ca-change-list">
            <li v-for="(a, i) in m.actions_summary" :key="i">{{ a }}</li>
          </ul>
          <pre v-else class="ca-change-json">{{ JSON.stringify(m.change_plan, null, 2) }}</pre>
          <div class="ca-change-note">
            💡 仅展示 — 如要实际改配置，直接告诉 AI「把 XX 字段改成必填 / 加角色 / 加字典选项」让它调真工具。
          </div>
        </div>
      </div>
    </div>

    <!-- 兜底 thinking dot (sending=true 但还没 push placeholder 的瞬间) -->
    <div v-if="sending" class="ca-msg ca-msg-assistant">
      <div class="ca-bubble ca-thinking">
        <span class="ca-dot" /><span class="ca-dot" /><span class="ca-dot" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.ca-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* ─── 空态 ──────────────────────────────────── */
.ca-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 24px 16px;
  color: var(--text-3);
  gap: 8px;
}
.ca-empty svg {
  color: var(--text-4);
  margin-bottom: 4px;
}
.ca-empty-title {
  font-size: 13px;
  font-weight: var(--fw-semibold, 600);
  color: var(--text-2);
}
.ca-empty-hint {
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.2;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ─── 消息 ──────────────────────────────────── */
.ca-msg {
  display: flex;
}
.ca-msg-user {
  justify-content: flex-end;
}
.ca-msg-assistant {
  justify-content: flex-start;
}
.ca-bubble {
  max-width: 92%;
  padding: 8px 10px;
  border-radius: var(--r-3, 6px);
  font-size: 12.5px;
  line-height: 1.55;
  word-break: break-word;
}
.ca-msg-user .ca-bubble {
  background: var(--brand);
  color: var(--text-inverse, #fff);
}
.ca-msg-assistant .ca-bubble {
  background: var(--surface-2);
  color: var(--text);
  border: 1px solid var(--line);
}

/* ─── Markdown 内容 (assistant bubble inside) ────────────── */
.ca-bubble-text :deep(strong) {
  font-weight: var(--fw-semibold, 600);
}
.ca-bubble-text :deep(code) {
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
  font-size: 11.5px;
  background: var(--surface-3, var(--surface));
  padding: 1px 4px;
  border-radius: 3px;
}
.ca-bubble-text :deep(p) {
  margin: 0 0 6px;
}
.ca-bubble-text :deep(p:last-child) { margin-bottom: 0; }
.ca-bubble-text :deep(ul),
.ca-bubble-text :deep(ol) {
  margin: 4px 0 6px;
  padding-left: 18px;
}
.ca-bubble-text :deep(li) {
  margin: 2px 0;
}
.ca-bubble-text :deep(h1),
.ca-bubble-text :deep(h2),
.ca-bubble-text :deep(h3),
.ca-bubble-text :deep(h4) {
  margin: 8px 0 4px;
  font-weight: var(--fw-semibold, 600);
}
.ca-bubble-text :deep(h1) { font-size: 16px; }
.ca-bubble-text :deep(h2) { font-size: 14px; }
.ca-bubble-text :deep(h3) { font-size: 13px; }
.ca-bubble-text :deep(h4) { font-size: 12.5px; }
.ca-bubble-text :deep(pre) {
  margin: 6px 0;
  padding: 8px;
  background: var(--surface-3, var(--surface));
  border-radius: var(--r-2, 4px);
  font-size: 11.5px;
  overflow-x: auto;
}
.ca-bubble-text :deep(pre code) {
  background: transparent;
  padding: 0;
}
.ca-bubble-text :deep(blockquote) {
  margin: 6px 0;
  padding-left: 8px;
  border-left: 3px solid var(--line);
  color: var(--text-3);
}
.ca-bubble-text :deep(table) {
  margin: 6px 0;
  border-collapse: collapse;
  font-size: 11.5px;
}
.ca-bubble-text :deep(thead) {
  background: var(--surface-3, var(--surface));
}
.ca-bubble-text :deep(th),
.ca-bubble-text :deep(td) {
  border: 1px solid var(--line);
  padding: 4px 8px;
  text-align: left;
}
.ca-bubble-text :deep(th) {
  font-weight: var(--fw-semibold, 600);
}
.ca-bubble-text :deep(a) {
  color: var(--brand);
  text-decoration: none;
}
.ca-bubble-text :deep(a:hover) { text-decoration: underline; color: var(--brand-hover); }
.ca-bubble-text :deep(hr) {
  margin: 8px 0;
  border: 0;
  border-top: 1px solid var(--line);
}

/* ─── Streaming 进度日志 ─────────────────────── */
.ca-stream-log {
  margin: 0 0 6px;
  padding: 6px 8px;
  background: var(--surface-3, var(--surface));
  border-radius: var(--r-2, 4px);
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
  font-size: 10.5px;
  color: var(--text-3);
  max-height: 120px;
  overflow-y: auto;
}
.ca-stream-line {
  line-height: 1.5;
  white-space: nowrap;
  overflow-x: auto;
}
.ca-stream-line::-webkit-scrollbar {
  display: none;
}

/* ─── Thinking dots ──────────────────────────── */
.ca-bubble-typing {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.ca-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--text-3);
  animation: ca-dot-pulse 1.2s infinite ease-in-out;
}
.ca-dot:nth-child(2) { animation-delay: 0.16s; }
.ca-dot:nth-child(3) { animation-delay: 0.32s; }

@keyframes ca-dot-pulse {
  0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
  40% { opacity: 1; transform: scale(1); }
}

.ca-thinking {
  padding: 8px 12px;
}

/* ─── 截图 ──────────────────────────────────── */
.ca-screenshots {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 0 0 6px;
}
.ca-screenshot {
  margin: 0;
  border: 1px solid var(--line);
  border-radius: var(--r-2, 4px);
  overflow: hidden;
}
.ca-screenshot img {
  display: block;
  width: 100%;
  height: auto;
  cursor: zoom-in;
  transition: opacity 0.12s ease;
}
.ca-screenshot img:hover {
  opacity: 0.85;
}
.ca-screenshot figcaption {
  padding: 3px 6px;
  font-size: 10.5px;
  color: var(--text-3);
  background: var(--surface);
  font-family: var(--font-mono, monospace);
}

/* ─── 工具 chip ──────────────────────────────── */
.ca-tool-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin: 0 0 6px;
}
.ca-tool-chip {
  padding: 2px 6px;
  border-radius: var(--r-1, 3px);
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
  font-size: 10.5px;
  font-weight: var(--fw-medium, 500);
  letter-spacing: -0.005em;
  cursor: help;
}
.ca-tool-chip-ok {
  color: var(--ok, #16a34a);
  background: rgba(34, 197, 94, 0.08);
}
.ca-tool-chip-err {
  color: var(--err, #dc2626);
  background: rgba(220, 38, 38, 0.08);
}

/* ─── 计划卡片 ──────────────────────────────── */
.ca-plan-card {
  margin: 0 0 8px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r-2, 4px);
  background: var(--surface);
}
.ca-plan-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
  font-size: 11.5px;
  font-weight: var(--fw-semibold, 600);
  color: var(--text-2);
}
.ca-plan-icon { font-size: 14px; }
.ca-plan-title { flex: 1; }
.ca-plan-status {
  padding: 1px 6px;
  font-size: 10.5px;
  font-weight: var(--fw-regular, 400);
  background: var(--brand-soft);
  color: var(--brand);
  border-radius: var(--r-1, 3px);
}
.ca-plan-status-done {
  background: rgba(34, 197, 94, 0.08);
  color: var(--ok, #16a34a);
}
.ca-plan-body {
  font-size: 12px;
  color: var(--text);
}
.ca-plan-body :deep(ol),
.ca-plan-body :deep(ul) {
  margin: 0;
  padding-left: 18px;
}
.ca-plan-body :deep(li) {
  margin: 2px 0;
}

/* ─── 完成态 hero CTA ───────────────────────── */
.ca-hero-cta {
  margin: 8px 0 0;
  padding: 8px 10px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--brand-soft);
  border: 1px solid var(--brand-ring, var(--brand));
  border-radius: var(--r-2, 4px);
}
.ca-hero-text {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-2);
}
.ca-hero-text strong {
  color: var(--brand);
  font-weight: var(--fw-semibold, 600);
}
.ca-hero-icon {
  font-size: 14px;
}
.ca-hero-btn {
  padding: 4px 10px;
  border: 0;
  border-radius: var(--r-2, 4px);
  background: var(--brand);
  color: var(--text-inverse, #fff);
  font-family: inherit;
  font-size: 11.5px;
  font-weight: var(--fw-medium, 500);
  cursor: pointer;
  transition: opacity 0.12s ease;
}
.ca-hero-btn:hover { opacity: 0.88; }
.ca-hero-btn:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}
/* 2026-05-26: 自动刷新后, 按钮降级为兜底, 缩成纯图标 */
.ca-hero-btn-subtle {
  background: transparent;
  color: var(--text-secondary, #64748b);
  border: 1px solid var(--line, rgba(99, 102, 241, 0.15));
  padding: 2px 8px;
  font-size: 13px;
}
.ca-hero-btn-subtle:hover {
  opacity: 1;
  background: var(--bg-panel-hover, rgba(99, 102, 241, 0.06));
  color: var(--brand);
  border-color: var(--brand);
}

/* ─── Change plan 信息卡片 ──────────────────── */
.ca-change-card {
  margin: 8px 0 0;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r-2, 4px);
  background: var(--surface);
}
.ca-change-card-info {
  background: rgba(34, 197, 94, 0.04);
  border-color: rgba(34, 197, 94, 0.2);
}
.ca-change-note {
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px dashed var(--line);
  font-size: 10.5px;
  color: var(--text-3);
  line-height: 1.5;
}
.ca-change-title {
  font-size: 11.5px;
  font-weight: var(--fw-semibold, 600);
  color: var(--text-2);
  margin-bottom: 4px;
}
.ca-change-list {
  margin: 4px 0;
  padding-left: 18px;
  font-size: 12px;
  color: var(--text);
}
.ca-change-json {
  margin: 4px 0;
  padding: 6px;
  background: var(--surface-3, var(--surface-2));
  border-radius: var(--r-1, 3px);
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
  font-size: 10.5px;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 200px;
  overflow-y: auto;
}
</style>
