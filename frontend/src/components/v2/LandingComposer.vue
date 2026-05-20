<!-- frontend/src/components/v2/LandingComposer.vue
  3-mode composer for Landing v3.
  - 睿鲸 AI Builder: 多文件 (any type) + text → /ai-chat（消费 previewStore.pendingAiChatFiles + ?prompt）
  - 睿鲸 AI Coding: text → /coding（进去后 agent 引导选目标应用 + templateType）
  - Vibe Coding:    text → /vibe-coding
-->
<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { usePreviewStore } from '@/stores/preview'

type Mode = 'builder' | 'coding' | 'vibe'
const MODES: { id: Mode; label: string; sub: string; tone: 'ai' | 'brand' | 'emerald' }[] = [
  { id: 'builder', label: '睿鲸 AI Builder', sub: '搭应用 + 应用内自开发（页面 / 接口）',   tone: 'ai' },
  { id: 'coding',  label: '睿鲸 AI Coding',  sub: '通用组件库 — 跨应用复用',                tone: 'brand' },
  { id: 'vibe',    label: 'Vibe Coding',    sub: '浏览器 VS Code 全代码 + AI 协助',        tone: 'emerald' },
]

const mode = ref<Mode>('builder')
const text = ref('')
const files = ref<File[]>([])
const fileInputRef = ref<HTMLInputElement | null>(null)
const router = useRouter()
const previewStore = usePreviewStore()

const placeholder = computed(() => ({
  builder: '说说你想做什么。例：管理我们部门 200 台设备的领用、归还和报废… 也可以直接拖文件进来。\n应用内做自开发（页面 / 后端接口）建议先进入应用，从应用里发起。',
  coding:  '描述要做的通用组件。例：做一个支持多选 + 异步加载的客户树组件 / 一个 OCR 上传组件。',
  vibe:    '描述你想做的代码任务，进入 Vibe Coding 工作区继续。',
}[mode.value]))

const cta = computed(() => ({ builder: '开始对话', coding: '开始生成', vibe: '打开工作区' }[mode.value]))

const canSubmit = computed(() => {
  if (mode.value === 'builder') return !!text.value.trim() || files.value.length > 0
  return !!text.value.trim()
})

function onFilesPicked(e: Event) {
  const target = e.target as HTMLInputElement
  const picked = Array.from(target.files || [])
  files.value.push(...picked)
  target.value = ''
}

function removeFile(idx: number) {
  files.value.splice(idx, 1)
}

function formatBytes(n: number) {
  if (n < 1024) return `${n}B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)}KB`
  return `${(n / 1024 / 1024).toFixed(1)}MB`
}

function submit() {
  if (!canSubmit.value) return
  const userPrompt = text.value.trim()
  if (mode.value === 'builder') {
    // 把多文件交给 store，prompt 走 URL；AIChatPage onMounted 已经会消费 pendingAiChatFiles + ?prompt
    previewStore.pendingAiChatFiles = [...files.value]
    router.push({
      path: '/ai-chat',
      query: { mode: 'requirements', ...(userPrompt ? { prompt: userPrompt } : {}) },
    })
  } else if (mode.value === 'coding') {
    // Landing 选应用 + 直接跳 /coding 的链路撤掉（UX 不顺）— 进 /coding 后由 agent 引导选目标 app
    router.push({ path: '/coding', query: userPrompt ? { prompt: userPrompt } : {} })
  } else {
    router.push({ path: '/vibe-coding', query: userPrompt ? { prompt: userPrompt } : {} })
  }
}
</script>

<template>
  <div class="composer">
    <div class="composer-modes">
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

      <!-- builder 模式：附件 chip 列表 -->
      <div v-if="mode === 'builder' && files.length" class="file-chips">
        <span v-for="(f, i) in files" :key="i" class="file-chip">
          <span class="file-chip-icon">{{ /\.(png|jpe?g|gif|webp|svg)$/i.test(f.name) ? '🖼️' : '📄' }}</span>
          <span class="file-chip-name" :title="f.name">{{ f.name }}</span>
          <span class="file-chip-size">{{ formatBytes(f.size) }}</span>
          <button class="file-chip-x" type="button" aria-label="移除" @click="removeFile(i)">×</button>
        </span>
      </div>

      <textarea v-model="text" class="composer-input" :placeholder="placeholder" rows="3" />

      <div class="composer-foot">
        <div class="composer-tools">
          <template v-if="mode === 'builder'">
            <button class="btn btn-ghost btn-sm" type="button" @click="fileInputRef?.click()">
              📎 添加附件（多文件）
            </button>
            <input
              ref="fileInputRef"
              type="file"
              multiple
              accept=".md,.markdown,.txt,.doc,.docx,.pdf,.xls,.xlsx,.csv,.json,.png,.jpg,.jpeg,.gif,.webp,.svg"
              hidden
              @change="onFilesPicked"
            />
            <span v-if="files.length" class="file-count">已选 {{ files.length }} 个文件</span>
          </template>
        </div>
        <button class="btn btn-primary" :disabled="!canSubmit" @click="submit">{{ cta }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.composer { width: 100%; max-width: 760px; margin: 0 auto; }
.composer-modes { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 14px; }
.mode-pill { padding: 12px 14px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); cursor: pointer; font-family: inherit; text-align: left; transition: border-color 0.14s, box-shadow 0.14s, background 0.14s; }
.mode-pill-label { font-size: 13.5px; font-weight: 600; color: var(--text); letter-spacing: -0.005em; }
.mode-pill-sub { font-size: 11.5px; color: var(--text-3); margin-top: 3px; }
.mode-pill.active { border-color: currentColor; box-shadow: 0 0 0 3px var(--ring, var(--brand-ring)); }
.mode-pill.tone-ai.active     { color: var(--ai-text);   background: var(--ai-soft);    --ring: var(--ai-ring); }
.mode-pill.tone-brand.active  { color: var(--brand-text); background: var(--brand-soft); --ring: var(--brand-ring); }
.mode-pill.tone-emerald.active{ color: var(--emerald);    background: var(--emerald-bg);--ring: rgba(16, 163, 127, 0.2); }

.composer-card { position: relative; background: var(--surface); border: 1px solid var(--border-strong); border-radius: 16px; box-shadow: var(--shadow-md); overflow: hidden; }
.composer-strip { height: 3px; }
.composer-card[data-tone="ai"] .composer-strip      { background: var(--ai); }
.composer-card[data-tone="brand"] .composer-strip   { background: var(--brand); }
.composer-card[data-tone="emerald"] .composer-strip { background: var(--emerald); }

/* File chips (builder mode) */
.file-chips { display: flex; flex-wrap: wrap; gap: 6px; padding: 12px 14px 0; }
.file-chip { display: inline-flex; align-items: center; gap: 6px; height: 26px; padding: 0 4px 0 8px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 6px; font-size: 12px; max-width: 240px; }
.file-chip-icon { font-size: 12px; line-height: 1; flex-shrink: 0; }
.file-chip-name { color: var(--text); font-weight: 500; max-width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-chip-size { color: var(--text-3); font-size: 11px; font-variant-numeric: tabular-nums; }
.file-chip-x { width: 20px; height: 20px; display: grid; place-items: center; padding: 0; background: transparent; border: none; border-radius: 4px; color: var(--text-3); cursor: pointer; font-size: 14px; line-height: 1; font-family: inherit; }
.file-chip-x:hover { background: var(--surface-3, var(--surface)); color: var(--text); }

/* Textarea */
.composer-input { width: 100%; min-height: 84px; padding: 14px 16px; border: none; outline: none; resize: none; background: transparent; color: var(--text); font-size: 14px; line-height: 1.55; font-family: inherit; }

/* Foot */
.composer-foot { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px 12px; gap: 8px; }
.composer-tools { display: flex; align-items: center; gap: 8px; }
.file-count { color: var(--text-3); font-size: 11.5px; }

.btn { display: inline-flex; align-items: center; gap: 6px; height: 32px; padding: 0 14px; border-radius: 8px; font-size: 13px; font-weight: 500; cursor: pointer; border: 1px solid transparent; background: transparent; color: var(--text); font-family: inherit; transition: background 0.12s, border-color 0.12s; }
.btn-sm { height: 26px; padding: 0 10px; font-size: 12px; border-radius: 6px; }
.btn-primary { background: var(--brand); color: #fff; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-primary:not(:disabled):hover { background: var(--brand-hover); }
.btn-ghost { color: var(--text-2); }
.btn-ghost:hover { background: var(--surface-2); color: var(--text); }
</style>