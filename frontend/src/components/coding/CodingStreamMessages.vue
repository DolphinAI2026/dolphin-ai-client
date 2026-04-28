<template>
  <div ref="containerRef" class="coding-stream-messages">
    <div
      v-for="(msg, idx) in messages"
      :key="`${msg.timestamp}-${idx}`"
      class="stream-msg"
      :class="'msg-' + msg.type"
    >
      <template v-if="msg.type === 'user'">
        <div class="msg-user-bubble user-markdown markdown-body" v-html="renderMarkdown(msg.content)"></div>
      </template>

      <template v-else-if="msg.type === 'message'">
        <div class="msg-ai-message">
          <div class="ai-message-body markdown-body" v-html="renderMarkdown(msg.content)"></div>
        </div>
      </template>

      <template v-else-if="msg.type === 'thinking'">
        <div class="msg-thinking-card" :class="{ 'is-collapsed': msg.collapsed }">
          <button class="thinking-card-header" type="button" @click="$emit('toggle', idx)">
            <svg class="thinking-card-icon" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <circle cx="8" cy="8" r="6.5" stroke="currentColor" stroke-width="1.2"/>
              <path d="M8 5v3.5l2 1.5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>
            </svg>
            <span class="thinking-card-label">思考过程</span>
            <span class="thinking-card-chars">{{ msg.content.length }} 字</span>
            <svg class="thinking-card-chevron" :class="{ rotated: !msg.collapsed }" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path d="M4 6l4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </button>
          <div v-show="!msg.collapsed" class="thinking-card-body">
            <span class="thinking-text markdown-body" v-html="renderMarkdown(msg.content)"></span>
            <span v-if="idx === messages.length - 1 && busy" class="thinking-cursor">|</span>
          </div>
        </div>
      </template>

      <template v-else-if="msg.type === 'status' && !msg.hidden">
        <div v-if="msg.stepDone" class="msg-step-badge">
          <svg class="step-badge-icon" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <circle cx="8" cy="8" r="7" fill="currentColor" opacity="0.15"/>
            <path d="M5 8l2.5 2.5L11 5.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
          <span>{{ msg.content }}</span>
        </div>
        <div v-else class="msg-status" :class="{ 'status-progress': msg.content.endsWith('...') }">
          <span class="status-content">{{ msg.content }}</span>
        </div>
      </template>

      <template v-else-if="msg.type === 'file_write' || msg.type === 'file_edit'">
        <FileCard
          :action="msg.type === 'file_write' ? 'write' : 'edit'"
          :file-name="msg.fileName"
          :file-content="msg.fileContent"
          :collapsed="msg.collapsed"
          @toggle="$emit('toggle', idx)"
        />
      </template>

      <template v-else-if="msg.type === 'tool'">
        <div class="msg-tool-row" :class="{ 'has-result': msg.result }">
          <button class="tool-row-header" type="button" @click="msg.result && $emit('toggleResult', idx)">
            <span class="tool-row-text">{{ msg.content }}</span>
            <svg v-if="msg.result" class="tool-row-chevron" :class="{ rotated: !msg.resultCollapsed }" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path d="M4 6l4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </button>
          <div v-if="msg.result && !msg.resultCollapsed" class="tool-row-result">
            <pre>{{ msg.result }}</pre>
          </div>
        </div>
      </template>

      <template v-else-if="msg.type === 'command'">
        <div class="msg-command-card">
          <div class="command-card-header">
            <span class="command-prompt">$</span>
            <span class="command-text">{{ msg.content.split('\n')[0] }}</span>
          </div>
          <pre v-if="msg.content.includes('\n')" class="command-output">{{ msg.content.split('\n').slice(1).join('\n') }}</pre>
        </div>
      </template>

      <template v-else-if="msg.type === 'error'">
        <div class="msg-error-row">
          <svg class="error-row-icon" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <circle cx="8" cy="8" r="7" stroke="currentColor" stroke-width="1.4"/>
            <path d="M8 5v3.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
            <circle cx="8" cy="11" r="0.75" fill="currentColor"/>
          </svg>
          <span class="error-row-text">{{ msg.content }}</span>
        </div>
      </template>
    </div>

    <div v-if="busy" class="stream-loading">
      <span class="stream-dot"></span>
      <span class="stream-dot"></span>
      <span class="stream-dot"></span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import FileCard from '@/components/FileCard.vue'
import { renderMarkdown, type StreamMessage } from '@/views/coding/useStreamMessages'

const props = defineProps<{
  messages: StreamMessage[]
  busy?: boolean
}>()

defineEmits<{
  toggle: [index: number]
  toggleResult: [index: number]
}>()

const containerRef = ref<HTMLElement | null>(null)

watch(
  () => [props.messages.length, props.busy],
  () => {
    nextTick(() => {
      const el = containerRef.value
      if (el) el.scrollTop = el.scrollHeight
    })
  },
)
</script>

<style scoped>
.coding-stream-messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stream-msg {
  display: flex;
  flex-direction: column;
  animation: fadeInUp 0.18s ease-out;
}

.msg-user {
  align-items: flex-end;
}

.msg-user-bubble {
  max-width: min(78%, 820px);
  padding: 10px 15px;
  border-radius: 14px 14px 4px 14px;
  background: #536dfe;
  color: #fff;
  font-size: 14px;
  line-height: 1.6;
  word-break: break-word;
  box-shadow: 0 10px 24px rgba(83, 109, 254, 0.18);
}

.msg-ai-message,
.msg-thinking-card,
.msg-tool-row,
.msg-command-card,
.msg-error-row {
  width: 100%;
  margin-top: 6px;
}

.msg-ai-message,
.msg-thinking-card,
.msg-tool-row,
.msg-command-card {
  border: 1px solid rgba(120, 132, 164, 0.16);
  border-radius: 12px;
  background: #fff;
  color: #263044;
}

.ai-message-body {
  padding: 14px 16px;
  color: #475569;
  font-size: 14px;
  line-height: 1.72;
}

.thinking-card-header,
.tool-row-header {
  width: 100%;
  min-height: 42px;
  border: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
  padding: 0 14px;
  display: flex;
  align-items: center;
  gap: 8px;
  text-align: left;
}

.thinking-card-icon,
.step-badge-icon,
.error-row-icon {
  width: 16px;
  height: 16px;
  flex: 0 0 auto;
}

.thinking-card-label,
.tool-row-text {
  flex: 1;
  min-width: 0;
  color: #607089;
  font-size: 13px;
  font-weight: 700;
}

.thinking-card-chars {
  color: #96a0b5;
  font-size: 12px;
  font-weight: 650;
}

.thinking-card-chevron,
.tool-row-chevron {
  width: 16px;
  height: 16px;
  color: #9aa5b8;
  transition: transform 0.16s ease;
}

.thinking-card-chevron.rotated,
.tool-row-chevron.rotated {
  transform: rotate(180deg);
}

.thinking-card-body,
.tool-row-result,
.command-output {
  border-top: 1px solid rgba(120, 132, 164, 0.13);
  background: #f8fafc;
}

.thinking-card-body {
  padding: 14px 16px;
}

.thinking-text {
  color: #4b5870;
  font-size: 13px;
  line-height: 1.72;
  white-space: pre-wrap;
}

.thinking-cursor {
  margin-left: 2px;
  color: #536dfe;
  animation: blink 1s steps(2, start) infinite;
}

.msg-step-badge {
  width: fit-content;
  margin: 5px 0;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 6px 10px;
  border-radius: 999px;
  background: rgba(34, 197, 94, 0.10);
  color: #15803d;
  font-size: 12px;
  font-weight: 760;
}

.msg-status {
  margin: 4px 0;
  color: #7d8aa3;
  font-size: 13px;
}

.status-progress::after {
  content: '';
  display: inline-block;
  width: 12px;
  height: 12px;
  margin-left: 7px;
  border-radius: 999px;
  border: 2px solid rgba(83, 109, 254, 0.18);
  border-top-color: #536dfe;
  vertical-align: -2px;
  animation: spin 0.8s linear infinite;
}

.tool-row-result pre,
.command-output {
  margin: 0;
  max-height: 260px;
  overflow: auto;
  padding: 12px 14px;
  color: #475569;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  line-height: 1.62;
  white-space: pre-wrap;
}

.command-card-header {
  min-height: 42px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 14px;
}

.command-prompt {
  color: #536dfe;
  font-weight: 800;
}

.command-text {
  color: #475569;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
}

.msg-error-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border: 1px solid rgba(239, 68, 68, 0.20);
  border-radius: 12px;
  background: rgba(254, 242, 242, 0.85);
  color: #b91c1c;
  font-size: 13px;
}

.stream-loading {
  height: 24px;
  display: flex;
  align-items: center;
  gap: 5px;
  padding-left: 4px;
}

.stream-dot {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: #8795b0;
  animation: pulseDot 1.1s infinite ease-in-out;
}

.stream-dot:nth-child(2) {
  animation-delay: 0.13s;
}

.stream-dot:nth-child(3) {
  animation-delay: 0.26s;
}

@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes blink {
  50% { opacity: 0; }
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@keyframes pulseDot {
  0%, 80%, 100% { opacity: 0.35; transform: translateY(0); }
  40% { opacity: 1; transform: translateY(-2px); }
}

:global(html[data-theme="dark"]) .msg-ai-message,
:global(html[data-theme="dark"]) .msg-thinking-card,
:global(html[data-theme="dark"]) .msg-tool-row,
:global(html[data-theme="dark"]) .msg-command-card {
  background: #111318;
  border-color: rgba(148, 163, 184, 0.14);
  color: rgba(226, 232, 240, 0.86);
}

:global(html[data-theme="dark"]) .ai-message-body,
:global(html[data-theme="dark"]) .thinking-text,
:global(html[data-theme="dark"]) .tool-row-result pre,
:global(html[data-theme="dark"]) .command-output,
:global(html[data-theme="dark"]) .command-text {
  color: rgba(203, 213, 225, 0.72);
}

:global(html[data-theme="dark"]) .thinking-card-body,
:global(html[data-theme="dark"]) .tool-row-result,
:global(html[data-theme="dark"]) .command-output {
  background: #0d1117;
  border-color: rgba(148, 163, 184, 0.14);
}

:global(html[data-theme="dark"]) .thinking-card-label,
:global(html[data-theme="dark"]) .tool-row-text {
  color: rgba(203, 213, 225, 0.72);
}

:global(html[data-theme="dark"]) .msg-user-bubble {
  background: rgba(124, 140, 255, 0.18);
  border: 1px solid rgba(124, 140, 255, 0.30);
  color: rgba(248, 250, 252, 0.94);
  box-shadow: none;
}
</style>
