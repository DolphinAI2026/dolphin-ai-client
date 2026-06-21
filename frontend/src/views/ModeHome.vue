<!-- 模式首页(参考设计): 按当前模式渲染 greeting + composer + 快捷动作。Code 模式落 /coding。 -->
<template>
  <WorkbenchShell>
    <div class="mode-home" :style="{ '--mc': `var(${meta.colorVar})`, '--mcbg': `var(${meta.colorVar}-bg)` }">
      <div class="mh-center">
        <div class="mh-hero">
          <span class="mh-spark" v-html="heroIcon" />
          <h1 class="mh-greeting">{{ meta.greeting }}</h1>
        </div>

        <div class="mh-composer">
          <textarea
            ref="ta"
            v-model="text"
            class="mh-textarea"
            :placeholder="meta.placeholder"
            rows="2"
            @keydown.enter.exact.prevent="send"
          ></textarea>
          <div class="mh-composer-foot">
            <span class="mh-gateway">
              <span class="mh-dot" />{{ meta.gateway }}
            </span>
            <button class="mh-send" :disabled="!text.trim()" @click="send" title="发送 (Enter)">
              <span v-html="sendIcon" />
            </button>
          </div>
        </div>

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
import { useUserStore } from '@/stores/user'
import { useModeStore } from '@/stores/mode'

const router = useRouter()
const user = useUserStore()
const modeStore = useModeStore()
const text = ref('')
const ta = ref<HTMLTextAreaElement | null>(null)

const name = computed(() => user.user?.display_name || user.user?.username || 'Mars')

interface HomeAction { label: string; icon: string; prompt?: string; to?: string }
interface HomeMeta { colorVar: string; greeting: string; placeholder: string; gateway: string; tagline: string; actions: HomeAction[] }

const HOME: Record<'builder' | 'agent', HomeMeta> = {
  builder: {
    colorVar: '--build',
    greeting: `来搭点什么，${name.value}`,
    placeholder: '描述要搭的应用，或要改的配置端… 也能拖入需求文档 / 原型图',
    gateway: '得小帆网关 · 自动选型',
    tagline: '产物 = 低代码应用 + 低代码二开 · 要纯代码开发？切到 Code',
    actions: [
      { label: '新建应用', icon: 'apps', to: '/apps' },
      { label: '低代码二开', icon: 'store', to: '/workspace-catalog' },
      { label: '导入需求', icon: 'plus', prompt: '我有一份需求文档，请帮我读完后给出应用搭建方案。' },
    ],
  },
  agent: {
    colorVar: '--agent',
    greeting: `${timeGreeting()}，${name.value}`,
    placeholder: '问个业务问题，或描述一个要配置的智能体…',
    gateway: '得小帆 dolphin agent · 自动选型',
    tagline: '不重复造轮子 · 直接接入小帆智能体能力',
    actions: [
      { label: '问业务', icon: 'chat', prompt: '' },
      { label: '配智能体', icon: 'spark', prompt: '我想配一个智能体，请先问我它的场景、人设和要挂的知识库。' },
      { label: '查知识库', icon: 'sparkles', to: '/skills' },
    ],
  },
}

const meta = computed<HomeMeta>(() => HOME[modeStore.mode === 'agent' ? 'agent' : 'builder'])

function timeGreeting(): string {
  const h = new Date().getHours()
  if (h < 6) return '夜深了'
  if (h < 12) return '早上好'
  if (h < 14) return '中午好'
  if (h < 18) return '下午好'
  return '晚上好'
}

function send() {
  const t = text.value.trim()
  if (!t) return
  router.push({ path: '/ai-chat', query: { prompt: t } })
}

function runAction(a: HomeAction) {
  if (a.to) { router.push(a.to); return }
  if (a.prompt) { router.push({ path: '/ai-chat', query: { prompt: a.prompt } }); return }
  // 无 prompt/to 的（如「问业务」）→ 聚焦输入框
  ta.value?.focus()
}

// Code 模式不在首页停留 —— 切到代码工作区
function bounceIfCode() {
  if (modeStore.mode === 'code') router.replace('/coding')
}
watch(() => modeStore.mode, bounceIfCode)
onMounted(() => { bounceIfCode(); ta.value?.focus() })

const heroIcon = '<svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 14 9l6 2-6 2-2 6-2-6-6-2 6-2z"/></svg>'
const sendIcon = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/></svg>'
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
.mh-composer { border: 1px solid var(--line-2, #333); border-radius: 16px; background: var(--surface-2, #161616); padding: 14px 16px 10px; transition: border-color .15s; }
.mh-composer:focus-within { border-color: var(--mc); }
.mh-textarea { width: 100%; border: none; outline: none; resize: none; background: transparent; color: var(--text, #eee); font-size: 15px; line-height: 1.5; font-family: inherit; }
.mh-textarea::placeholder { color: var(--text-3, #777); }
.mh-composer-foot { display: flex; align-items: center; justify-content: space-between; margin-top: 8px; }
.mh-gateway { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-3, #888); }
.mh-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--mc); }
.mh-send { width: 34px; height: 34px; border: none; border-radius: 10px; background: var(--mc); color: #0c0b0a; display: inline-flex; align-items: center; justify-content: center; cursor: pointer; }
.mh-send:disabled { opacity: .4; cursor: default; }
.mh-actions { display: flex; gap: 10px; justify-content: center; margin-top: 18px; flex-wrap: wrap; }
.mh-action { display: inline-flex; align-items: center; gap: 7px; padding: 8px 16px; border: 1px solid var(--line-2, #333); border-radius: 10px; background: var(--surface-2, #161616); color: var(--text, #eee); font-size: 13px; font-weight: 500; cursor: pointer; transition: all .12s; }
.mh-action:hover { border-color: var(--mc); color: var(--mc); }
.mh-action-icon { display: inline-flex; color: var(--mc); }
.mh-tagline { text-align: center; margin-top: 16px; font-size: 12.5px; color: var(--text-3, #777); }
</style>
