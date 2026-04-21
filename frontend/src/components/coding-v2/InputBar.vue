<template>
  <div class="input-bar">
    <!-- Codex 风格反问区：仅当有待答问题时展示 -->
    <Transition name="ask-slide">
      <div v-if="pendingQuestion" class="ask-overlay">
        <div class="ask-banner">
          <span class="ask-icon">💬</span>
          <span class="ask-text">{{ pendingQuestion.question }}</span>
          <span v-if="pendingQuestion.context" class="ask-ctx">{{ pendingQuestion.context }}</span>
        </div>
        <div class="chips-row">
          <button
            v-for="opt in pendingQuestion.options"
            :key="opt.value"
            class="chip"
            :disabled="disabled || submitting"
            @click="quickAnswer(opt.value)"
          >
            {{ opt.label }}
          </button>
          <button
            v-if="pendingQuestion.allow_free_text"
            class="chip chip-custom"
            :disabled="disabled || submitting"
            @click="focusInput"
          >
            自定义...
          </button>
        </div>
      </div>
    </Transition>

    <!-- 输入行 -->
    <div class="composer-row">
      <textarea
        ref="inputRef"
        v-model="localInput"
        class="composer-input"
        :placeholder="placeholder"
        :disabled="disabled || submitting"
        rows="1"
        @keydown.ctrl.enter.prevent="send"
        @keydown.meta.enter.prevent="send"
        @input="autoResize"
      />
      <button
        class="send-btn"
        :disabled="!localInput.trim() || submitting || disabled"
        @click="send"
        :title="submitting ? '发送中...' : 'Ctrl/⌘+Enter 发送'"
      >
        <span v-if="submitting" class="send-spinner" />
        <span v-else class="send-arrow">↑</span>
      </button>
    </div>
    <div class="composer-hint">Ctrl/⌘+Enter 发送</div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import type { AskUserBubble } from '@/stores/codingV2'

const props = defineProps<{
  pendingAskUser?: AskUserBubble | null
  submitting?: boolean
  disabled?: boolean
}>()

const emit = defineEmits<{
  (e: 'send', text: string): void
  (e: 'answer', payload: { bubbleId: string; answer: string; p1_key?: string | null }): void
}>()

const localInput = ref('')
const inputRef = ref<HTMLTextAreaElement>()

const pendingQuestion = computed(() =>
  props.pendingAskUser && !props.pendingAskUser.answered ? props.pendingAskUser : null,
)

const placeholder = computed(() => {
  if (pendingQuestion.value) return '或者直接输入你的回答...'
  return '说说你要做什么...'
})

function send() {
  const text = localInput.value.trim()
  if (!text || props.submitting || props.disabled) return
  emit('send', text)
  localInput.value = ''
  nextTick(() => {
    if (inputRef.value) {
      inputRef.value.style.height = 'auto'
    }
  })
}

function quickAnswer(value: string) {
  if (!props.pendingAskUser || props.submitting || props.disabled) return
  emit('answer', {
    bubbleId: props.pendingAskUser.id,
    answer: value,
    p1_key: props.pendingAskUser.p1_key,
  })
}

function focusInput() {
  nextTick(() => inputRef.value?.focus())
}

function autoResize() {
  const el = inputRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 160) + 'px'
}
</script>

<style scoped>
.input-bar {
  border-top: 1px solid #e5e7eb;
  background: white;
  padding: 0;
  display: flex;
  flex-direction: column;
}

/* ── 反问区 ── */
.ask-overlay {
  border-bottom: 1px solid #e5e7eb;
  background: #faf5ff;
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.ask-banner {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  flex-wrap: wrap;
}
.ask-icon { font-size: 15px; flex-shrink: 0; margin-top: 1px; }
.ask-text {
  font-size: 14px;
  font-weight: 500;
  color: #1e1b4b;
  flex: 1;
  line-height: 1.5;
}
.ask-ctx {
  display: block;
  width: 100%;
  font-size: 12px;
  color: #6b7280;
  padding-left: 23px;
  margin-top: -4px;
}
.chips-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding-left: 23px;
}
.chip {
  padding: 5px 14px;
  border-radius: 999px;
  background: white;
  border: 1px solid #c4b5fd;
  color: #5b21b6;
  font-size: 13px;
  cursor: pointer;
  transition: background 120ms, color 120ms, border-color 120ms;
  white-space: nowrap;
}
.chip:hover:not(:disabled) {
  background: #7c3aed;
  color: white;
  border-color: #7c3aed;
}
.chip:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.chip-custom {
  background: transparent;
  border-style: dashed;
  color: #6b7280;
  border-color: #d1d5db;
}
.chip-custom:hover:not(:disabled) {
  background: #f3f4f6;
  color: #374151;
  border-color: #9ca3af;
  border-style: solid;
}

/* ── 输入行 ── */
.composer-row {
  display: flex;
  align-items: flex-end;
  gap: 0;
  padding: 10px 12px 4px;
}
.composer-input {
  flex: 1;
  resize: none;
  border: 1px solid #d1d5db;
  border-radius: 10px;
  padding: 9px 12px;
  font-size: 14px;
  font-family: inherit;
  line-height: 1.5;
  min-height: 42px;
  max-height: 160px;
  outline: none;
  transition: border-color 150ms;
  background: #f9fafb;
  overflow-y: auto;
}
.composer-input:focus {
  border-color: #8b5cf6;
  background: white;
}
.composer-input:disabled {
  background: #f3f4f6;
  color: #9ca3af;
}
.send-btn {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  background: #7c3aed;
  border: none;
  color: white;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-left: 8px;
  flex-shrink: 0;
  margin-bottom: 2px;
  transition: background 150ms;
}
.send-btn:hover:not(:disabled) { background: #6d28d9; }
.send-btn:disabled { background: #d1d5db; cursor: not-allowed; }
.send-arrow { font-size: 16px; font-weight: 700; line-height: 1; }
.send-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255,255,255,0.4);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 600ms linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.composer-hint {
  font-size: 11px;
  color: #9ca3af;
  text-align: right;
  padding: 2px 14px 8px;
}

/* ── 动画 ── */
.ask-slide-enter-active,
.ask-slide-leave-active {
  transition: max-height 250ms ease, opacity 200ms ease, padding 250ms ease;
  overflow: hidden;
}
.ask-slide-enter-from,
.ask-slide-leave-to {
  max-height: 0;
  opacity: 0;
  padding-top: 0;
  padding-bottom: 0;
}
.ask-slide-enter-to,
.ask-slide-leave-from {
  max-height: 200px;
  opacity: 1;
}
</style>
