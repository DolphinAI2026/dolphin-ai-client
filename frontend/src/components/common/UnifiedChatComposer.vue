<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { getPastedImageFiles } from '@/utils/pasteImages'
import type { UnifiedChatAttachment } from './chatComposer'

const props = withDefaults(defineProps<{
  modelValue: string
  attachments?: UnifiedChatAttachment[]
  placeholder?: string
  sending?: boolean
  disabled?: boolean
  sendDisabled?: boolean
  allowSendWhileSending?: boolean
  showStop?: boolean
  showAttach?: boolean
  nativeFilePicker?: boolean
  multiple?: boolean
  accept?: string
  attachLabel?: string
  sendLabel?: string
  stopLabel?: string
  hint?: string
  sendingHint?: string
  minRows?: number
  maxHeight?: number
  /** 可用技能(skill)列表 —— 输入 `@` 时弹轻量下拉供强指引用，空数组则不触发。 */
  skills?: { name: string; description: string }[]
}>(), {
  attachments: () => [],
  placeholder: '输入需求，粘贴图片或点附件...',
  sending: false,
  disabled: false,
  sendDisabled: false,
  allowSendWhileSending: false,
  showStop: true,
  showAttach: true,
  nativeFilePicker: true,
  multiple: false,
  accept: '',
  attachLabel: '',
  sendLabel: '发送',
  stopLabel: '停止',
  hint: 'Enter 发送 · Shift+Enter 换行',
  sendingHint: 'Enter 排队发送 · Shift+Enter 换行',
  minRows: 1,
  maxHeight: 128,
  skills: () => [],
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'send'): void
  (e: 'stop'): void
  (e: 'attach'): void
  (e: 'files-picked', files: File[]): void
  (e: 'paste-images', files: File[]): void
  (e: 'remove-attachment', attachment: UnifiedChatAttachment, index: number): void
  (e: 'skill-picked', name: string): void
}>()

const textareaRef = ref<HTMLTextAreaElement | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)

// 拖拽上传：dragenter/dragleave 会在子元素间反复冒泡触发，用计数器去抖避免高亮闪烁。
const isDragOver = ref(false)
let dragDepth = 0

// @ 技能下拉：输入末尾出现 `@filter` 时弹出，原生过滤，不引第三方 mention 库。
const showSkillMenu = ref(false)
const skillFilter = ref('')
const filteredSkills = computed(() => {
  const f = skillFilter.value.toLowerCase()
  const list = props.skills || []
  if (!f) return list
  return list.filter(s =>
    s.name.toLowerCase().includes(f) || (s.description || '').toLowerCase().includes(f),
  )
})

function syncSkillMenu(v: string) {
  if (!(props.skills && props.skills.length)) {
    showSkillMenu.value = false
    return
  }
  // 仅匹配光标处(输入末尾)的 `@` token；遇空格/换行/第二个 @ 终止。
  const m = v.match(/@([^\s@]*)$/)
  if (m) {
    showSkillMenu.value = true
    skillFilter.value = m[1]
  } else {
    showSkillMenu.value = false
  }
}

function pickSkill(name: string) {
  // 去掉尾部 `@filter`（光标处那段），把选择权交给使用方拼接发送前缀。
  const v = props.modelValue.replace(/@([^\s@]*)$/, '')
  emit('update:modelValue', v)
  showSkillMenu.value = false
  skillFilter.value = ''
  emit('skill-picked', name)
  nextTick(() => {
    textareaRef.value?.focus()
    resize()
  })
}

function resize() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, props.maxHeight)}px`
}

function onInput(e: Event) {
  const v = (e.target as HTMLTextAreaElement).value
  emit('update:modelValue', v)
  syncSkillMenu(v)
  nextTick(resize)
}

function onAttachClick() {
  emit('attach')
  if (props.nativeFilePicker) fileInputRef.value?.click()
}

function onFilesPicked(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files || [])
  if (files.length) emit('files-picked', files)
  input.value = ''
}

function onDragEnter(e: DragEvent) {
  if (props.disabled) return
  // 只在拖拽包含文件时响应（拖文本/拖选区不算）。
  if (!e.dataTransfer || !Array.from(e.dataTransfer.types || []).includes('Files')) return
  e.preventDefault()
  e.stopPropagation()
  dragDepth += 1
  isDragOver.value = true
}

function onDragOver(e: DragEvent) {
  if (props.disabled) return
  if (!e.dataTransfer || !Array.from(e.dataTransfer.types || []).includes('Files')) return
  // dragover 必须 preventDefault 才能让随后的 drop 生效。
  e.preventDefault()
  e.stopPropagation()
  e.dataTransfer.dropEffect = 'copy'
  isDragOver.value = true
}

function onDragLeave(e: DragEvent) {
  if (props.disabled) return
  e.preventDefault()
  e.stopPropagation()
  dragDepth -= 1
  if (dragDepth <= 0) {
    dragDepth = 0
    isDragOver.value = false
  }
}

function onDrop(e: DragEvent) {
  dragDepth = 0
  isDragOver.value = false
  if (props.disabled) return
  e.preventDefault()
  e.stopPropagation()
  const files = Array.from(e.dataTransfer?.files || [])
  // 复用与点选/粘贴相同的出口；不在此处加 accept 校验，与原生文件选择保持一致。
  if (files.length) emit('files-picked', files)
}

function onPaste(e: ClipboardEvent) {
  const images = getPastedImageFiles(e, 'pasted-image')
  if (!images.length) return
  e.preventDefault()
  emit('paste-images', images)
  emit('files-picked', images)
}

function onKeydown(e: KeyboardEvent) {
  if (e.key !== 'Enter' || e.shiftKey || e.isComposing) return
  e.preventDefault()
  if (props.disabled) return
  if (props.sending && !props.allowSendWhileSending) return
  if (!props.sending && props.sendDisabled) return
  emit('send')
}

function onPrimaryClick() {
  if (props.sending && props.showStop) {
    emit('stop')
    return
  }
  if (props.sendDisabled || props.disabled) return
  emit('send')
}

watch(() => props.modelValue, () => nextTick(resize))
</script>

<template>
  <div class="ucc">
    <div
      class="ucc-box"
      :class="{ 'is-disabled': disabled, 'is-drag-over': isDragOver }"
      @dragenter="onDragEnter"
      @dragover="onDragOver"
      @dragleave="onDragLeave"
      @drop="onDrop"
    >
      <div v-if="attachments.length" class="ucc-attachments" aria-label="已添加附件">
        <div
          v-for="(attachment, index) in attachments"
          :key="attachment.id"
          class="ucc-attachment"
        >
          <img
            v-if="attachment.previewUrl"
            :src="attachment.previewUrl"
            alt=""
            class="ucc-attachment-thumb"
          />
          <span v-else class="ucc-attachment-icon" aria-hidden="true">
            <svg v-if="attachment.kind === 'image'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <rect x="3" y="5" width="18" height="14" rx="2" />
              <path d="m8 13 2.2-2.2a1.2 1.2 0 0 1 1.7 0L17 16" />
              <circle cx="8" cy="9" r="1.4" />
            </svg>
            <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <path d="M14 2H7a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7z" />
              <path d="M14 2v5h5" />
            </svg>
          </span>
          <span class="ucc-attachment-name" :title="attachment.name">{{ attachment.name }}</span>
          <button
            type="button"
            class="ucc-attachment-remove"
            title="移除附件"
            @click="emit('remove-attachment', attachment, index)"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>
      </div>

      <textarea
        ref="textareaRef"
        class="ucc-input"
        :value="modelValue"
        :placeholder="placeholder"
        :disabled="disabled"
        :rows="minRows"
        @input="onInput"
        @paste="onPaste"
        @keydown="onKeydown"
      />

      <div class="ucc-footer">
        <div class="ucc-footer-left">
          <button
            v-if="showAttach"
            type="button"
            class="ucc-attach"
            :disabled="disabled"
            title="添加附件"
            :aria-label="attachLabel || '添加附件'"
            @click="onAttachClick"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
              <path d="m21.4 11.1-9.2 9.2a6 6 0 0 1-8.5-8.5l9.2-9.2a4 4 0 0 1 5.7 5.7l-9.2 9.2a2 2 0 0 1-2.8-2.8l8.5-8.5" />
            </svg>
            <span v-if="attachLabel">{{ attachLabel }}</span>
          </button>
          <slot name="footer-left" />
        </div>
        <div class="ucc-footer-right">
          <slot name="footer-right">
            <span v-if="sending ? sendingHint : hint" class="ucc-hint">{{ sending ? sendingHint : hint }}</span>
          </slot>
        </div>
      </div>

      <input
        ref="fileInputRef"
        type="file"
        :multiple="multiple"
        :accept="accept || undefined"
        hidden
        @change="onFilesPicked"
      />
    </div>

    <div v-if="showSkillMenu && filteredSkills.length" class="ucc-skill-menu" role="listbox">
      <button
        v-for="s in filteredSkills"
        :key="s.name"
        type="button"
        class="ucc-skill-item"
        @mousedown.prevent="pickSkill(s.name)"
      >
        <span class="ucc-skill-name">@{{ s.name }}</span>
        <span class="ucc-skill-desc">{{ s.description }}</span>
      </button>
    </div>

    <button
      type="button"
      class="ucc-send"
      :class="{ 'is-stop': sending && showStop }"
      :disabled="(!sending && (disabled || sendDisabled)) || (sending && !showStop)"
      :title="sending && showStop ? stopLabel : sendLabel"
      @click="onPrimaryClick"
    >
      <template v-if="sending && showStop">
        <span class="ucc-stop-icon" aria-hidden="true" />
        <span class="ucc-send-label">{{ stopLabel }}</span>
      </template>
      <template v-else>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
          <path d="m22 2-7 20-4-9-9-4z" />
          <path d="M22 2 11 13" />
        </svg>
        <span class="ucc-send-label">{{ sendLabel }}</span>
      </template>
    </button>
  </div>
</template>

<style scoped>
.ucc {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  width: 100%;
  position: relative;
}

.ucc-skill-menu {
  position: absolute;
  left: 0;
  right: 44px;
  bottom: calc(100% + 6px);
  z-index: 20;
  max-height: 220px;
  overflow-y: auto;
  background: var(--surface, var(--t-bg-input, #fff));
  border: 1px solid var(--line, var(--t-border-subtle, #dbe3ef));
  border-radius: var(--r-3, 8px);
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.12);
  padding: 4px;
}

.ucc-skill-item {
  display: flex;
  flex-direction: column;
  gap: 1px;
  width: 100%;
  text-align: left;
  padding: 6px 10px;
  border: 0;
  background: transparent;
  border-radius: 6px;
  cursor: pointer;
}

.ucc-skill-item:hover {
  background: var(--surface-2, var(--t-bg-panel, #f1f5fb));
}

.ucc-skill-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text, #1f2937);
}

.ucc-skill-desc {
  font-size: 12px;
  color: var(--text-muted, #6b7280);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ucc-box {
  flex: 1;
  min-width: 0;
  border: 1px solid var(--line, var(--t-border-subtle, #dbe3ef));
  border-radius: var(--r-3, 8px);
  background: var(--surface, var(--t-bg-input, #fff));
  transition: border-color 0.14s ease, box-shadow 0.14s ease, background 0.14s ease;
  overflow: hidden;
}

.ucc-box:focus-within {
  border-color: var(--brand-ring, var(--brand, #2f6bff));
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--brand, #2f6bff) 10%, transparent);
}

.ucc-box.is-drag-over {
  border-color: var(--brand-ring, var(--brand, #2f6bff));
  border-style: dashed;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--brand, #2f6bff) 14%, transparent);
  background: color-mix(in srgb, var(--brand, #2f6bff) 5%, var(--surface, var(--t-bg-input, #fff)));
}

.ucc-box.is-disabled {
  background: var(--surface-2, var(--t-bg-panel, #f8fafc));
}

.ucc-attachments {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 10px 12px 0;
}

.ucc-attachment {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  min-height: 30px;
  padding: 3px 7px 3px 4px;
  border: 1px solid var(--line, var(--t-border-subtle, #dbe3ef));
  border-radius: 999px;
  background: var(--surface-2, var(--t-bg-panel, #f8fafc));
  color: var(--text-3, var(--t-text-muted, #64748b));
  font-size: 12px;
  line-height: 1;
}

.ucc-attachment-thumb,
.ucc-attachment-icon {
  width: 22px;
  height: 22px;
  flex: 0 0 22px;
  border-radius: 999px;
}

.ucc-attachment-thumb {
  object-fit: cover;
}

.ucc-attachment-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: color-mix(in srgb, var(--brand, #2f6bff) 10%, white);
  color: var(--brand, #2f6bff);
}

.ucc-attachment-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ucc-attachment-remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  padding: 0;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--text-4, var(--t-text-muted, #94a3b8));
  cursor: pointer;
}

.ucc-attachment-remove:hover {
  background: var(--line, var(--t-border-subtle, #dbe3ef));
  color: var(--text, var(--t-text-primary, #16233d));
}

.ucc-input {
  display: block;
  width: 100%;
  min-height: 38px;
  max-height: 128px;
  padding: 13px 16px 2px;
  border: 0;
  outline: none;
  resize: none;
  background: transparent;
  color: var(--text, var(--t-text-primary, #16233d));
  font-family: inherit;
  font-size: 14px;
  line-height: 1.5;
}

.ucc-input::placeholder {
  color: var(--text-4, var(--t-text-muted, #94a3b8));
}

.ucc-input:disabled {
  cursor: not-allowed;
}

.ucc-footer {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  flex-wrap: wrap;
  gap: 10px;
  min-height: 36px;
  padding: 0 12px 9px;
}

.ucc-footer-left,
.ucc-footer-right {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  max-width: 100%;
}

.ucc-footer-left {
  flex: 1 1 160px;
  overflow: hidden;
}

.ucc-footer-right {
  flex: 1 1 170px;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 4px 6px;
}

.ucc-attach {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex: 0 0 auto;
  white-space: nowrap;
  min-height: 30px;
  padding: 0 10px;
  border: 1px solid var(--line, var(--t-border-subtle, #dbe3ef));
  border-radius: var(--r-2, 6px);
  background: var(--surface-2, var(--t-bg-panel, #f8fafc));
  color: var(--text-3, var(--t-text-muted, #64748b));
  font: inherit;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.14s ease;
}

.ucc-attach:hover:not(:disabled) {
  border-color: var(--brand, #2f6bff);
  color: var(--brand, #2f6bff);
  background: var(--brand-soft, color-mix(in srgb, var(--brand, #2f6bff) 8%, white));
}

.ucc-attach:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.ucc-hint {
  color: var(--text-4, var(--t-text-muted, #94a3b8));
  font-size: 12px;
  line-height: 1.35;
  white-space: normal;
  overflow-wrap: anywhere;
}

:slotted(select) {
  flex: 1 1 120px;
  min-width: 0;
  max-width: min(220px, 100%);
}

:slotted(.hint) {
  min-width: 0;
  max-width: 100%;
  color: var(--text-4, var(--t-text-muted, #94a3b8));
  font-size: 12px;
  line-height: 1.35;
  white-space: normal;
  overflow-wrap: anywhere;
}

:slotted(.timer) {
  flex: 0 0 auto;
  color: var(--brand, var(--t-brand, #2f6bff));
  white-space: nowrap;
}

.ucc-send {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  min-height: 44px;
  border: 1px solid var(--brand, var(--t-brand, #2f6bff));
  border-radius: var(--r-3, 8px);
  background: var(--brand, var(--t-brand, #2f6bff));
  color: #fff;
  font: inherit;
  cursor: pointer;
  transition: transform 0.14s ease, background 0.14s ease, border-color 0.14s ease, color 0.14s ease, opacity 0.14s ease;
  flex-shrink: 0;
  box-shadow: var(--sh-1, 0 1px 2px rgba(15, 23, 42, 0.08));
}

.ucc-send:hover:not(:disabled) {
  transform: translateY(-1px);
  background: color-mix(in srgb, var(--brand, var(--t-brand, #2f6bff)) 88%, black);
  border-color: color-mix(in srgb, var(--brand, var(--t-brand, #2f6bff)) 88%, black);
}

.ucc-send:disabled {
  background: var(--surface, var(--t-bg-input, #fff));
  border-color: var(--line, var(--t-border-subtle, #dbe3ef));
  color: var(--text-4, var(--t-text-muted, #8aa0bc));
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

.ucc-send.is-stop {
  background: var(--err-soft);
  color: var(--err);
  border: 1px solid var(--err-soft);
}

.ucc-stop-icon {
  width: 14px;
  height: 14px;
  border-radius: 3px;
  background: currentColor;
}

.ucc-send-label {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

@media (max-width: 720px) {
  .ucc {
    gap: 8px;
  }

  .ucc-send {
    width: 44px;
    min-height: 44px;
  }

  .ucc-footer {
    align-items: flex-start;
    flex-direction: column;
    gap: 6px;
  }

  .ucc-footer-left,
  .ucc-footer-right {
    flex: 0 1 auto;
    width: 100%;
  }

  .ucc-footer-right {
    align-self: stretch;
    justify-content: flex-start;
  }
}
</style>
