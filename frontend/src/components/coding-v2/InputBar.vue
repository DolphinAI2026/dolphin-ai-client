<template>
  <div class="input-bar">
    <!-- 选项 chips（问题已在聊天列表中，此处只显示选项） -->
    <Transition name="ask-slide">
      <div v-if="pendingQuestion" class="ask-overlay">
        <div class="chips-row">
          <button
            v-for="opt in pendingQuestion.options"
            :key="opt.value"
            class="chip"
            :disabled="disabled || submitting"
            @click="quickAnswer(opt)"
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
import type { AskUserBubble, AskUserOption } from '@/stores/codingV2'

const props = defineProps<{
  pendingAskUser?: AskUserBubble | null
  submitting?: boolean
  disabled?: boolean
}>()

const emit = defineEmits<{
  (e: 'send', text: string): void
  (e: 'answer', payload: { bubbleId: string; answer: string; displayText: string; p1_key?: string | null }): void
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

function quickAnswer(opt: AskUserOption) {
  if (!props.pendingAskUser || props.submitting || props.disabled) return
  emit('answer', {
    bubbleId: props.pendingAskUser.id,
    answer: opt.value,       // 发送给后端的值（可能是 enum key）
    displayText: opt.label,  // 用户气泡展示的可读文字
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

/* ── 选项区（问题在聊天列表里，只显示 chips） ── */
.ask-overlay {
  border-bottom: 1px solid #ede9fe;
  background: #faf5ff;
  padding: 10px 16px;
  display: flex;
  flex-direction: column;
}
.chips-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
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
