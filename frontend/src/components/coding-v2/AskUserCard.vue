<template>
  <div class="ask-card" :class="priorityClass">
    <div class="header">
      <span class="icon">🤖</span>
      <span class="turn">
        第 {{ bubble.ask_turn }} / {{ bubble.max_ask_turns }} 轮反问
      </span>
      <span class="prio-tag">{{ priorityLabel }}</span>
    </div>

    <div class="question">{{ bubble.question }}</div>

    <div v-if="bubble.context" class="ctx">ℹ️ {{ bubble.context }}</div>

    <div v-if="!bubble.answered" class="options-row">
      <button
        v-for="opt in bubble.options"
        :key="opt.value"
        class="opt"
        :disabled="submitting"
        @click="pickOption(opt)"
      >
        {{ opt.label }}
      </button>
      <button v-if="bubble.allow_free_text" class="opt self-decide" :disabled="submitting"
        @click="selfDecide">
        让我自己决定
      </button>
    </div>

    <div v-if="!bubble.answered && bubble.allow_free_text" class="free-text-row">
      <input
        v-model="freeText"
        type="text"
        placeholder="或自由输入答案..."
        class="input"
        :disabled="submitting"
        @keydown.enter="submitFree"
      />
      <button class="opt submit" :disabled="!freeText.trim() || submitting" @click="submitFree">
        提交
      </button>
    </div>

    <div v-if="bubble.answered" class="answered">
      <span class="label">你的回答：</span>
      <span class="answer-text">{{ bubble.answer }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { AskUserBubble, AskUserOption } from '@/stores/codingV2'

const props = defineProps<{
  bubble: AskUserBubble
  submitting?: boolean
}>()

const emit = defineEmits<{
  (e: 'answer', payload: { bubbleId: string; answer: string; p1_key?: string | null }): void
}>()

const freeText = ref('')

const priorityClass = computed(() => `prio-${props.bubble.priority}`)
const priorityLabel = computed(() => {
  switch (props.bubble.priority) {
    case 1: return 'P1 关键'
    case 2: return 'P2 重要'
    case 3: return 'P3 可选'
    default: return '未知'
  }
})

function pickOption(opt: AskUserOption) {
  emit('answer', {
    bubbleId: props.bubble.id,
    answer: opt.value,
    p1_key: props.bubble.p1_key,
  })
}

function selfDecide() {
  emit('answer', {
    bubbleId: props.bubble.id,
    answer: '让我自己决定',
    p1_key: props.bubble.p1_key,
  })
}

function submitFree() {
  const v = freeText.value.trim()
  if (!v) return
  emit('answer', {
    bubbleId: props.bubble.id,
    answer: v,
    p1_key: props.bubble.p1_key,
  })
  freeText.value = ''
}
</script>

<style scoped>
.ask-card {
  background: white;
  border-radius: 10px;
  border: 1px solid #e5e7eb;
  border-left-width: 4px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
}
.prio-1 { border-left-color: #ef4444; }
.prio-2 { border-left-color: #f59e0b; }
.prio-3 { border-left-color: #9ca3af; }
.header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #6b7280;
}
.icon { font-size: 14px; }
.turn { color: #6b7280; }
.prio-tag {
  margin-left: auto;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 500;
}
.prio-1 .prio-tag { background: #fee2e2; color: #b91c1c; }
.prio-2 .prio-tag { background: #fef3c7; color: #92400e; }
.prio-3 .prio-tag { background: #e5e7eb; color: #4b5563; }

.question {
  color: #111827;
  font-size: 15px;
  font-weight: 500;
  line-height: 1.5;
}
.ctx {
  color: #6b7280;
  font-size: 12px;
  background: #f9fafb;
  padding: 6px 10px;
  border-radius: 4px;
}
.options-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.opt {
  padding: 6px 14px;
  border-radius: 999px;
  background: #f3f4f6;
  border: 1px solid transparent;
  color: #374151;
  cursor: pointer;
  font-size: 13px;
  transition: background 120ms;
}
.opt:hover:not(:disabled) {
  background: #dbeafe;
  color: #1d4ed8;
}
.opt:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.opt.self-decide {
  background: transparent;
  border-color: #d1d5db;
  color: #6b7280;
}
.opt.submit {
  background: #3b82f6;
  color: white;
}
.opt.submit:hover:not(:disabled) { background: #2563eb; }
.free-text-row { display: flex; gap: 8px; }
.input {
  flex: 1;
  padding: 6px 12px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  font-size: 13px;
  outline: none;
}
.input:focus { border-color: #3b82f6; }
.answered {
  padding: 8px 12px;
  background: #f0fdf4;
  border-radius: 6px;
  font-size: 13px;
}
.label { color: #6b7280; }
.answer-text { color: #065f46; font-weight: 500; }
</style>
