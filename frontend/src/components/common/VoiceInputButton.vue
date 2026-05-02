<template>
  <button
    v-if="supported"
    type="button"
    class="voice-input-btn"
    :class="{ recording }"
    :title="recording ? '停止录音' : '语音输入（中文）'"
    @click="toggle"
  >
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
      <path
        d="M8 1.5a2.5 2.5 0 00-2.5 2.5v4a2.5 2.5 0 005 0V4A2.5 2.5 0 008 1.5z"
        stroke="currentColor"
        stroke-width="1.4"
      />
      <path
        d="M3.5 7.5v.5a4.5 4.5 0 009 0v-.5M8 12.5v2"
        stroke="currentColor"
        stroke-width="1.4"
        stroke-linecap="round"
      />
    </svg>
    <span v-if="recording" class="voice-pulse" aria-hidden="true"></span>
  </button>
</template>

<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from 'vue'

/**
 * 语音输入按钮 — 浏览器原生 webkitSpeechRecognition，无外部依赖。
 *
 * 用法：
 *   <VoiceInputButton v-model="inputText" />
 *   或：<VoiceInputButton @transcript="(t) => inputText += t" />
 *
 * 限制：
 *   - 浏览器需支持 SpeechRecognition（Chrome/Edge 系；Safari 部分支持）
 *   - 部署到 HTTPS 才能用麦克风（浏览器安全限制；localhost 例外）
 *   - 不支持时按钮自动隐藏
 */
const props = withDefaults(
  defineProps<{
    /** 双向绑定输入框文本（识别到 final text 时按 mode 合并） */
    modelValue?: string
    /** 识别语言，默认中文 */
    lang?: string
    /** 合并模式：append=拼到末尾；replace=直接覆盖；none=不动 modelValue（仅 emit transcript） */
    mode?: 'append' | 'replace' | 'none'
  }>(),
  {
    modelValue: '',
    lang: 'zh-CN',
    mode: 'append',
  },
)

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  /** 识别到一段最终文本时 emit（无论 mode） */
  (e: 'transcript', text: string): void
  (e: 'start'): void
  (e: 'end'): void
  (e: 'error', error: string): void
}>()

type SpeechRecognitionLike = any
const supported = ref(false)
const recording = ref(false)
let recognition: SpeechRecognitionLike | null = null

function init() {
  const w = window as any
  const SR = w.SpeechRecognition || w.webkitSpeechRecognition
  if (!SR) {
    supported.value = false
    return
  }
  try {
    recognition = new SR()
    recognition.lang = props.lang
    recognition.continuous = false
    recognition.interimResults = true
    recognition.onresult = (event: any) => {
      let finalText = ''
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const res = event.results[i]
        if (res.isFinal) finalText += res[0].transcript
      }
      if (finalText) {
        const cleaned = finalText.trim()
        emit('transcript', cleaned)
        if (props.mode === 'append') {
          const next = props.modelValue ? `${props.modelValue} ${cleaned}` : cleaned
          emit('update:modelValue', next)
        } else if (props.mode === 'replace') {
          emit('update:modelValue', cleaned)
        }
      }
    }
    recognition.onerror = (e: any) => {
      const msg = e?.error || 'unknown'
      console.warn('[VoiceInputButton] error', msg)
      recording.value = false
      emit('error', String(msg))
    }
    recognition.onend = () => {
      recording.value = false
      emit('end')
    }
    supported.value = true
  } catch (e) {
    console.warn('[VoiceInputButton] init failed', e)
    supported.value = false
    recognition = null
  }
}

function toggle() {
  if (!recognition) return
  if (recording.value) {
    try { recognition.stop() } catch { /* ignore */ }
    recording.value = false
    return
  }
  try {
    recognition.start()
    recording.value = true
    emit('start')
  } catch (e) {
    // 在 start 报 InvalidStateError 时忽略
    recording.value = false
  }
}

onMounted(init)
onBeforeUnmount(() => {
  if (recognition && recording.value) {
    try { recognition.stop() } catch { /* ignore */ }
  }
  recognition = null
})

defineExpose({ toggle, recording, supported })
</script>

<style scoped>
.voice-input-btn {
  position: relative;
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--t-text-muted, #94a3b8);
  cursor: pointer;
  transition: background 0.14s, color 0.14s;
  flex-shrink: 0;
}
.voice-input-btn:hover {
  background: var(--t-bg-soft, rgba(15, 23, 42, 0.06));
  color: var(--t-text-secondary, #475569);
}
.voice-input-btn.recording {
  color: #ef4444;
  background: rgba(239, 68, 68, 0.1);
}
.voice-pulse {
  position: absolute;
  inset: 2px;
  border-radius: 8px;
  border: 1.5px solid #ef4444;
  animation: voice-pulse 1.2s ease-out infinite;
  pointer-events: none;
}
@keyframes voice-pulse {
  0% { transform: scale(0.85); opacity: 0.7; }
  100% { transform: scale(1.4); opacity: 0; }
}
</style>
