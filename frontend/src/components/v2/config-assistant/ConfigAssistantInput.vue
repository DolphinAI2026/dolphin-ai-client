<!-- frontend/src/components/v2/config-assistant/ConfigAssistantInput.vue
     2026-05-24 从 ConfigAssistantPanel.vue 拆出 (refactor #9). -->
<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import UnifiedChatComposer from '@/components/common/UnifiedChatComposer.vue'
import type { UnifiedChatAttachment } from '@/components/common/chatComposer'

const props = defineProps<{
  modelValue: string
  sending: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: string): void
  (e: 'send'): void
  (e: 'upload-doc'): void
}>()

type PastedImage = { id: number; name: string; previewUrl: string }
const pastedImages = ref<PastedImage[]>([])

const attachments = computed<UnifiedChatAttachment[]>(() =>
  pastedImages.value.map(item => ({
    id: item.id,
    name: item.name,
    previewUrl: item.previewUrl,
    kind: 'image',
  })),
)

function appendContextLine(line: string) {
  const current = props.modelValue.trimEnd()
  emit('update:modelValue', current ? `${current}\n${line}` : line)
}

function removePastedImage(id: number) {
  const img = pastedImages.value.find(item => item.id === id)
  if (img?.previewUrl) URL.revokeObjectURL(img.previewUrl)
  pastedImages.value = pastedImages.value.filter(item => item.id !== id)
}

function clearPastedImages() {
  pastedImages.value.forEach(item => URL.revokeObjectURL(item.previewUrl))
  pastedImages.value = []
}

function submit() {
  if (!props.modelValue.trim() || props.sending) return
  clearPastedImages()
  emit('send')
}

function onPasteImages(files: File[]) {
  const lines: string[] = []
  for (const file of files) {
    const item = {
      id: Date.now() + pastedImages.value.length,
      name: file.name,
      previewUrl: URL.createObjectURL(file),
    }
    pastedImages.value.push(item)
    lines.push(`[已粘贴图片：${file.name}] 请结合这张图片理解我的需求。`)
  }
  if (lines.length) appendContextLine(lines.join('\n'))
}

onBeforeUnmount(() => {
  clearPastedImages()
})
</script>

<template>
  <footer class="ca-input-area">
    <UnifiedChatComposer
      :model-value="modelValue"
      :attachments="attachments"
      :disabled="sending"
      :sending="sending"
      :show-stop="false"
      :send-disabled="!modelValue.trim()"
      :native-file-picker="false"
      placeholder="输入需求，粘贴图片或点附件..."
      @update:model-value="emit('update:modelValue', $event)"
      @send="submit"
      @attach="emit('upload-doc')"
      @paste-images="onPasteImages"
      @remove-attachment="removePastedImage(Number($event.id))"
    />
  </footer>
</template>

<style scoped>
.ca-input-area {
  border-top: 1px solid var(--line);
  padding: 12px;
  background: var(--surface);
}
</style>
