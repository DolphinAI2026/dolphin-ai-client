<!-- 模式首页(参考设计): 按当前模式渲 greeting + composer + 快捷动作。Code 模式落 /coding。
     composer 复用 UnifiedChatComposer(附件/粘贴/拖拽/@技能); 发送把文字+附件交给 /ai-chat。 -->
<template>
  <WorkbenchShell>
    <div class="mode-home" :style="{ '--mc': `var(${meta.colorVar})`, '--mcbg': `var(${meta.colorVar}-bg)` }">
      <div class="mh-center">
        <div class="mh-hero">
          <span class="mh-spark" v-html="heroIcon" />
          <h1 class="mh-greeting">{{ greeting }}</h1>
        </div>

        <UnifiedChatComposer
          v-model="text"
          class="mh-composer"
          :attachments="attachments"
          :multiple="true"
          :show-stop="false"
          :send-disabled="!text.trim() && files.length === 0"
          accept=".md,.markdown,.txt,.doc,.docx,.pdf,.xls,.xlsx,.csv,.json,.png,.jpg,.jpeg,.gif,.webp,.svg,.html,.htm,.yaml,.yml,.xml,.zip"
          :placeholder="meta.placeholder"
          :hint="meta.gateway"
          @send="send"
          @files-picked="onFilesPicked"
          @remove-attachment="onRemoveAttachment"
        />

        <div class="mh-actions">
          <button v-for="a in meta.actions" :key="a.label" class="mh-action" @click="runAction(a)">
            <span class="mh-action-icon" v-html="renderIcon(a.icon)" />{{ a.label }}
          </button>
        </div>

        <p class="mh-tagline">{{ meta.tagline }}</p>
      </div>
    </div>
  </WorkbenchShell>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import UnifiedChatComposer from '@/components/common/UnifiedChatComposer.vue'
import type { UnifiedChatAttachment } from '@/components/common/chatComposer'
import { useUserStore } from '@/stores/user'
import { useModeStore } from '@/stores/mode'
import { usePreviewStore } from '@/stores/preview'

const router = useRouter()
const user = useUserStore()
const modeStore = useModeStore()
const previewStore = usePreviewStore()
const text = ref('')
const files = ref<File[]>([])

const name = computed(() => user.user?.display_name || user.user?.username || 'Mars')
const isImage = (f: File) => /^image\//.test(f.type)
const attachments = computed<UnifiedChatAttachment[]>(() =>
  files.value.map((f, i) => ({ id: i, name: f.name, kind: isImage(f) ? 'image' : 'file' })),
)

interface HomeAction { label: string; icon: string; act: 'focus' | 'attach' | 'nav'; to?: string }
interface HomeMeta { colorVar: string; placeholder: string; gateway: string; tagline: string; actions: HomeAction[] }

const HOME: Record<'builder' | 'agent', HomeMeta> = {
  builder: {
    colorVar: '--build',
    placeholder: '描述要搭的应用，或要改的配置端… 也能拖入需求文档 / 原型图',
    gateway: '得小帆网关 · 自动选型',
    tagline: '产物 = 低代码应用 + 低代码二开 · 要纯代码开发？切到 Code',
    actions: [
      { label: '新建应用', icon: 'apps', act: 'focus' },
      { label: '低代码二开', icon: 'store', act: 'nav', to: '/workspace-catalog' },
      { label: '导入需求', icon: 'plus', act: 'attach' },
    ],
  },
  agent: {
    colorVar: '--agent',
    placeholder: '问个业务问题，或描述一个要配置的智能体…',
    gateway: '得小帆 dolphin agent · 自动选型',
    tagline: '不重复造轮子 · 直接接入小帆智能体能力',
    actions: [
      { label: '问业务', icon: 'chat', act: 'focus' },
      { label: '配智能体', icon: 'spark', act: 'focus' },
      { label: '查知识库', icon: 'sparkles', act: 'nav', to: '/skills' },
    ],
  },
}

const mode = computed<'builder' | 'agent'>(() => (modeStore.mode === 'agent' ? 'agent' : 'builder'))
const meta = computed<HomeMeta>(() => HOME[mode.value])
const greeting = computed(() =>
  mode.value === 'agent' ? `${timeGreeting()}，${name.value}` : `来搭点什么，${name.value}`,
)

function timeGreeting(): string {
  const h = new Date().getHours()
  if (h < 6) return '夜深了'
  if (h < 12) return '早上好'
  if (h < 14) return '中午好'
  if (h < 18) return '下午好'
  return '晚上好'
}

function focusComposer() {
  const ta = document.querySelector<HTMLTextAreaElement>('.mh-composer textarea')
  ta?.focus()
}

function onFilesPicked(picked: File[]) { files.value.push(...picked) }
function onRemoveAttachment(_a: UnifiedChatAttachment, i: number) { files.value.splice(i, 1) }

function send() {
  const t = text.value.trim()
  if (!t && files.value.length === 0) return
  if (files.value.length) previewStore.pendingAiChatFiles = files.value.slice()
  router.push({ path: '/ai-chat', query: t ? { prompt: t } : {} })
}

function runAction(a: HomeAction) {
  if (a.act === 'nav' && a.to) { router.push(a.to); return }
  if (a.act === 'attach') {
    const btn = document.querySelector<HTMLElement>('.mh-composer [class*="attach"], .mh-composer button[title*="附件"]')
    if (btn) btn.click(); else focusComposer()
    return
  }
  focusComposer()
}

// Code 模式不停留在首页 —— 切到代码工作区
function bounceIfCode() { if (modeStore.mode === 'code') router.replace('/coding') }
watch(() => modeStore.mode, bounceIfCode)
onMounted(() => { bounceIfCode(); focusComposer() })

const heroIcon = '<svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 14 9l6 2-6 2-2 6-2-6-6-2 6-2z"/></svg>'
const ACT_ICONS: Record<string, string> = {
  apps: '<path d="M3 5h7v7H3z"/><path d="M14 5h7v7h-7z"/><path d="M3 16h7v5H3z"/><path d="M14 16h7v5h-7z"/>',
  store: '<path d="M3 9 5 4h14l2 5"/><path d="M4 9v10a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V9"/>',
  plus: '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
  chat: '<path d="M21 12a8 8 0 0 1-11.9 7L4 21l1.6-4.4A8 8 0 1 1 21 12z"/>',
  spark: '<path d="M12 3 14 9l6 2-6 2-2 6-2-6-6-2 6-2z"/>',
  sparkles: '<path d="M9 4 10 7 13 8 10 9 9 12 8 9 5 8 8 7z"/>',
}
function renderIcon(n: string) {
  return `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${ACT_ICONS[n] || ''}</svg>`
}
</script>

<style scoped>
.mode-home { height: 100%; display: flex; align-items: center; justify-content: center; padding: 24px; overflow: auto; }
.mh-center { width: 100%; max-width: 720px; }
.mh-hero { display: flex; align-items: center; justify-content: center; gap: 12px; margin-bottom: 26px; }
.mh-spark { color: var(--mc); display: inline-flex; }
.mh-greeting { font-size: 30px; font-weight: 700; color: var(--text, #eee); letter-spacing: .5px; }
.mh-composer { --uc-accent: var(--mc); }
.mh-actions { display: flex; gap: 10px; justify-content: center; margin-top: 18px; flex-wrap: wrap; }
.mh-action { display: inline-flex; align-items: center; gap: 7px; padding: 8px 16px; border: 1px solid var(--line-2, #333); border-radius: 10px; background: var(--surface-2, #161616); color: var(--text, #eee); font-size: 13px; font-weight: 500; cursor: pointer; transition: all .12s; }
.mh-action:hover { border-color: var(--mc); color: var(--mc); }
.mh-action-icon { display: inline-flex; color: var(--mc); }
.mh-tagline { text-align: center; margin-top: 16px; font-size: 12.5px; color: var(--text-3, #777); }
</style>
