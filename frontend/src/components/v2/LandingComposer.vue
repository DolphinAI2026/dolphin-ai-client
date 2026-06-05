<script setup lang="ts">
import { computed, ref } from 'vue'
import { isImageFile } from '@/utils/pasteImages'
import UnifiedChatComposer from '@/components/common/UnifiedChatComposer.vue'
import type { UnifiedChatAttachment } from '@/components/common/chatComposer'

type Mode = 'builder'
const MODES: { id: Mode; label: string; sub: string; tone: 'ai' | 'brand' }[] = [
  { id: 'builder', label: 'AI Builder', sub: '搭应用 + 应用内自开发（页面 / 接口）',   tone: 'ai' },
]

const mode = ref<Mode>('builder')
const text = ref('')
const files = ref<File[]>([])

const emit = defineEmits<{ (e: 'submit', payload: { prompt: string; files: File[] }): void }>()

const placeholder = computed(() => ({
  builder: '例如：给质量部搭一个 QMS 整改闭环，包含问题登记、责任人派发、整改验证、超期提醒和月度统计；后面还要能改页面样式、接审批接口、修构建报错。',
}[mode.value]))

const canSubmit = computed(() => !!text.value.trim() || files.value.length > 0)

const composerAttachments = computed<UnifiedChatAttachment[]>(() =>
  files.value.map((file, index) => ({
    id: index,
    name: file.name,
    kind: isImageFile(file) ? 'image' : 'file',
  })),
)

function onComposerFilesPicked(pastedImages: File[]) {
  files.value.push(...pastedImages)
}

function removeComposerFile(_: UnifiedChatAttachment, index: number) {
  files.value.splice(index, 1)
}

function submit() {
  if (!canSubmit.value) return
  // 就地交给父组件（AIChatPage 空状态）发起新会话；不再 router.push 跳转。
  emit('submit', { prompt: text.value.trim(), files: [...files.value] })
  text.value = ''
  files.value = []
}
</script>

<template>
  <div class="composer">
    <div v-if="MODES.length > 1" class="composer-modes">
      <button
        v-for="m in MODES"
        :key="m.id"
        class="mode-pill"
        :class="['tone-' + m.tone, { active: mode === m.id }]"
        @click="mode = m.id"
      >
        <div class="mode-pill-label">{{ m.label }}</div>
        <div class="mode-pill-sub">{{ m.sub }}</div>
      </button>
    </div>

    <div class="composer-card" :data-tone="MODES.find(m => m.id === mode)?.tone">
      <div class="composer-strip" />

      <UnifiedChatComposer
        v-model="text"
        :attachments="mode === 'builder' ? composerAttachments : []"
        :placeholder="placeholder"
        :send-disabled="!canSubmit"
        :min-rows="4"
        :max-height="260"
        :multiple="true"
        attach-label="上传材料"
        accept=".md,.markdown,.txt,.doc,.docx,.pdf,.xls,.xlsx,.csv,.json,.png,.jpg,.jpeg,.gif,.webp,.svg,.html,.htm,.yaml,.yml,.xml,.zip"
        @send="submit"
        @files-picked="onComposerFilesPicked"
        @remove-attachment="removeComposerFile"
      />
    </div>
  </div>
</template>

<style scoped>
.composer { width: min(100%, 880px); margin: 0 auto; }
.composer-modes { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 14px; }
.mode-pill {
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--surface-2);
  cursor: pointer;
  font-family: inherit;
  text-align: left;
  transition: border-color 0.14s, box-shadow 0.14s, background 0.14s;
}
.mode-pill:hover {
  background: var(--surface);
  border-color: var(--brand-ring, var(--brand));
}
.mode-pill-label { font-size: 13.5px; font-weight: 600; color: var(--text); letter-spacing: 0; }
.mode-pill-sub { font-size: 11.5px; color: var(--text-3); margin-top: 3px; }
.mode-pill.active {
  border-color: currentColor;
  background: var(--surface);
  box-shadow: 0 0 0 3px var(--ring, var(--brand-ring));
}
.mode-pill.tone-ai.active     { color: var(--ai-text);   background: var(--ai-soft);    --ring: var(--ai-ring); }
.mode-pill.tone-brand.active  { color: var(--brand-text); background: var(--brand-soft); --ring: var(--brand-ring); }
.mode-pill.tone-emerald.active{ color: var(--emerald);    background: var(--emerald-bg);--ring: rgba(16, 163, 127, 0.2); }

.composer-card {
  position: relative;
  padding: 14px;
  background: var(--surface);
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  box-shadow: 0 20px 48px rgba(27, 46, 87, 0.12);
  overflow: hidden;
}
.composer-strip {
  position: absolute;
  inset: 0 0 auto;
  height: 4px;
}
.composer-card[data-tone="ai"] .composer-strip      { background: var(--ai); }
.composer-card[data-tone="brand"] .composer-strip   { background: var(--brand); }
.composer-card[data-tone="emerald"] .composer-strip { background: var(--emerald); }

.composer-card :deep(.ucc) {
  position: relative;
  display: block;
}

.composer-card :deep(.ucc-box) {
  border-radius: 8px;
  border-color: var(--line, var(--border));
  background: var(--surface);
}

.composer-card :deep(.ucc-input) {
  min-height: 164px;
  padding: 20px 22px 12px;
  font-size: 16px;
  line-height: 1.65;
}

.composer-card :deep(.ucc-input::placeholder) {
  color: var(--text-3);
}

.composer-card :deep(.ucc-footer) {
  min-height: 54px;
  padding: 0 78px 14px 18px;
}

.composer-card :deep(.ucc-attach) {
  min-height: 36px;
  padding: 0 13px;
  border-radius: 8px;
  font-size: 13.5px;
  color: var(--text-2);
}

.composer-card :deep(.ucc-hint) {
  font-size: 12.5px;
}

.composer-card :deep(.ucc-send) {
  position: absolute;
  right: 14px;
  bottom: 14px;
  width: 42px;
  height: 42px;
  min-height: 42px;
  border-radius: 8px;
}

@media (max-width: 720px) {
  .composer-card {
    padding: 12px;
    border-radius: 16px;
  }

  .composer-card :deep(.ucc) {
    display: block;
  }

  .composer-card :deep(.ucc-input) {
    min-height: 128px;
    padding: 16px 16px 6px;
    font-size: 15px;
  }

  .composer-card :deep(.ucc-footer) {
    padding-right: 66px;
  }

  .composer-card :deep(.ucc-send) {
    width: 40px;
    height: 40px;
    min-height: 40px;
    right: 10px;
    bottom: 10px;
    border-radius: 10px;
  }
}
</style>
