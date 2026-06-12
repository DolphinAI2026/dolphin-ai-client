<template>
  <button
    v-if="supported"
    type="button"
    class="voice-input-btn"
    :class="{ recording, loading: transcribing }"
    :title="buttonTitle"
    :disabled="transcribing"
    @click="toggle"
  >
    <svg v-if="!transcribing" width="16" height="16" viewBox="0 0 16 16" fill="none">
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
    <svg v-else class="spin" width="14" height="14" viewBox="0 0 14 14" fill="none">
      <circle cx="7" cy="7" r="5" stroke="currentColor" stroke-width="1.6" stroke-dasharray="8 8" />
    </svg>
    <span v-if="recording" class="voice-pulse" aria-hidden="true"></span>
  </button>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { ElMessage } from 'element-plus'
import request from '@/utils/request'

/**
 * 语音输入按钮 — MediaRecorder 录音 + 后端 STT 中转。
 *
 * 流程：
 *   1. 点击 → getUserMedia 拿麦克风 → MediaRecorder 录 webm/opus
 *   2. 再点击 / 自动 30s 上限 → 停止录音 → POST /api/voice/transcribe
 *   3. 后端复用 LLMConfig 凭证调 OpenAI 兼容 Whisper API → 返回文本
 *   4. 文本按 mode 合并到 v-model
 *
 * 用法：
 *   <VoiceInputButton v-model="inputText" :llm-config-id="selectedLlmId" />
 *
 * 限制：
 *   - 浏览器需支持 MediaRecorder（现代浏览器都支持）
 *   - 必须 HTTPS 或 localhost（getUserMedia 安全限制）
 *   - 后端 LLM 必须支持 Whisper 协议（OneAPI / FastGPT / OpenAI 直连等）
 */
const props = withDefaults(
  defineProps<{
    modelValue?: string
    /** 当前对话选的 LLMConfig.id（不传时后端用租户默认） */
    llmConfigId?: number | null
    /** 识别语言，ISO-639-1：zh / en / ja 等 */
    language?: string
    /** STT 模型名，默认 whisper-1（OpenAI 标准，OneAPI 类网关一般也认） */
    model?: string
    /** 合并模式：append=拼到末尾；replace=覆盖；none=仅 emit */
    mode?: 'append' | 'replace' | 'none'
    /** 录音时长上限（秒，默认 60） */
    maxDurationSec?: number
  }>(),
  {
    modelValue: '',
    llmConfigId: null,
    language: 'zh',
    model: 'whisper-1',
    mode: 'append',
    maxDurationSec: 60,
  },
)

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'transcript', text: string): void
  (e: 'start'): void
  (e: 'end'): void
  (e: 'error', error: string): void
}>()

const supported = ref(typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia && !!(window as any).MediaRecorder)
const recording = ref(false)
const transcribing = ref(false)

let mediaRecorder: MediaRecorder | null = null
let mediaStream: MediaStream | null = null
let chunks: Blob[] = []
let stopTimer: ReturnType<typeof setTimeout> | null = null

const buttonTitle = computed(() => {
  if (transcribing.value) return '识别中…'
  if (recording.value) return '点击停止录音'
  return '语音输入（点击开始说话）'
})

function pickMimeType(): string {
  const candidates = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/ogg;codecs=opus',
    'audio/mp4',
  ]
  for (const t of candidates) {
    if (typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(t)) return t
  }
  return ''
}

async function startRecording() {
  if (recording.value || transcribing.value) return
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true })
  } catch (e: any) {
    const name = e?.name || ''
    if (name === 'NotAllowedError') {
      ElMessage.warning('麦克风权限被拒绝。请在浏览器地址栏点锁标 → 允许麦克风')
    } else if (name === 'NotFoundError') {
      ElMessage.warning('没检测到麦克风设备')
    } else {
      ElMessage.error(`无法启动麦克风: ${e?.message || name}`)
    }
    emit('error', name || 'getUserMedia-failed')
    return
  }

  const mime = pickMimeType()
  try {
    mediaRecorder = new MediaRecorder(mediaStream, mime ? { mimeType: mime } : undefined)
  } catch (e: any) {
    ElMessage.error(`MediaRecorder 初始化失败: ${e?.message || e}`)
    cleanup()
    emit('error', 'recorder-init-failed')
    return
  }

  chunks = []
  mediaRecorder.ondataavailable = (ev) => {
    if (ev.data && ev.data.size > 0) chunks.push(ev.data)
  }
  mediaRecorder.onstop = () => {
    void uploadAndTranscribe()
  }
  mediaRecorder.start()
  recording.value = true
  emit('start')

  // 自动停止：超过上限时间
  stopTimer = setTimeout(() => {
    if (recording.value) {
      ElMessage.info(`已达录音时长上限 ${props.maxDurationSec}s，自动停止`)
      stopRecording()
    }
  }, props.maxDurationSec * 1000)
}

function stopRecording() {
  if (!recording.value) return
  if (stopTimer) {
    clearTimeout(stopTimer)
    stopTimer = null
  }
  recording.value = false
  try {
    mediaRecorder?.stop()
  } catch { /* ignore */ }
  // mediaStream 在 onstop → uploadAndTranscribe 完成后再 cleanup
}

function cleanup() {
  if (mediaStream) {
    mediaStream.getTracks().forEach(t => { try { t.stop() } catch {} })
    mediaStream = null
  }
  mediaRecorder = null
  chunks = []
  if (stopTimer) {
    clearTimeout(stopTimer)
    stopTimer = null
  }
}

async function uploadAndTranscribe() {
  const mime = mediaRecorder?.mimeType || 'audio/webm'
  const blob = new Blob(chunks, { type: mime })
  cleanup()

  if (blob.size < 1024) {
    ElMessage.warning('录音太短，请重试')
    emit('end')
    return
  }

  transcribing.value = true
  try {
    const ext = mime.includes('mp4') ? 'mp4' : mime.includes('ogg') ? 'ogg' : 'webm'
    const filename = `voice-${Date.now()}.${ext}`
    const form = new FormData()
    form.append('audio', blob, filename)
    form.append('language', props.language)
    form.append('model', props.model)
    if (props.llmConfigId != null) form.append('selected_llm_config_id', String(props.llmConfigId))

    const data = await request.post<any, { text: string }>('/voice/transcribe', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 90_000,
    })
    const text = (data?.text || '').trim()
    if (!text) {
      ElMessage.warning('没识别出内容，请说大声一点再试')
      return
    }
    emit('transcript', text)
    if (props.mode === 'append') {
      const next = props.modelValue ? `${props.modelValue} ${text}` : text
      emit('update:modelValue', next)
    } else if (props.mode === 'replace') {
      emit('update:modelValue', text)
    }
  } catch (e: any) {
    const detail = e?.response?.data?.detail || e?.message || '语音识别失败'
    ElMessage.error(detail)
    emit('error', String(detail))
  } finally {
    transcribing.value = false
    emit('end')
  }
}

function toggle() {
  if (transcribing.value) return
  if (recording.value) {
    stopRecording()
  } else {
    void startRecording()
  }
}

onBeforeUnmount(() => {
  stopRecording()
  cleanup()
})

defineExpose({ toggle, recording, transcribing, supported })
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
.voice-input-btn:hover:not(:disabled) {
  background: var(--t-bg-soft, rgba(15, 23, 42, 0.06));
  color: var(--t-text-secondary, #475569);
}
.voice-input-btn:disabled {
  cursor: not-allowed;
  opacity: 0.7;
}
.voice-input-btn.recording {
  color: var(--err);
  background: var(--err-soft);
}
.voice-input-btn.loading {
  color: var(--t-brand, #6366f1);
}
.voice-pulse {
  position: absolute;
  inset: 2px;
  border-radius: 8px;
  border: 1.5px solid var(--err);
  animation: voice-pulse 1.2s ease-out infinite;
  pointer-events: none;
}
.spin {
  animation: voice-spin 0.9s linear infinite;
}
@keyframes voice-pulse {
  0% { transform: scale(0.85); opacity: 0.7; }
  100% { transform: scale(1.4); opacity: 0; }
}
@keyframes voice-spin {
  to { transform: rotate(360deg); }
}
</style>
