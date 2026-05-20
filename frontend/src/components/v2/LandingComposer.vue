<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

type Mode = 'builder' | 'coding'

const MODES: { id: Mode; label: string; sub: string; icon: string }[] = [
  { id: 'builder', label: 'AI Builder', sub: '需求到应用', icon: 'chat' },
  { id: 'coding', label: 'AI Coding', sub: '低代码扩展', icon: 'code' },
]

const mode = ref<Mode>('builder')
const text = ref('')
const router = useRouter()

const emit = defineEmits<{
  (e: 'upload-file'): void
}>()

const activeIcon = computed(() => (mode.value === 'builder' ? 'chat' : 'code'))
const activeLabel = computed(() => (mode.value === 'builder' ? 'AI Builder' : 'AI Coding'))
const activeSub = computed(() => (mode.value === 'builder' ? '需求到应用' : '低代码扩展'))
const placeholder = computed(() => (
  mode.value === 'builder'
    ? '描述你想做的应用，或把材料拖进来...\n比如：搭建一个客户工单系统，工单流转 + SLA 看板 + 客户回访。'
    : '描述要生成的低代码组件或页面...\n比如：做一个支持多选 + 异步加载的客户树组件。'
))
const cta = computed(() => (mode.value === 'builder' ? '开始构建' : '开始生成'))

const ICONS: Record<string, string> = {
  chat: '<path d="M21 12a8 8 0 0 1-11.9 7L4 21l1.6-4.4A8 8 0 1 1 21 12z"/>',
  code: '<path d="m9 17-5-5 5-5"/><path d="m15 7 5 5-5 5"/><path d="m13 5-2 14"/>',
  upload: '<path d="M12 16V4"/><path d="m7 9 5-5 5 5"/><path d="M5 20h14"/>',
  arrow: '<path d="M5 12h14"/><path d="m13 5 7 7-7 7"/>',
}

function renderIcon(name: string): string {
  const inner = ICONS[name] ?? ''
  return `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`
}

function submit() {
  const prompt = text.value.trim()
  if (!prompt) return
  if (mode.value === 'builder') {
    router.push({ path: '/ai-chat', query: { mode: 'requirements', prompt } })
  } else {
    router.push({ path: '/coding', query: { prompt } })
  }
}
</script>

<template>
  <div class="landing-composer">
    <div class="mode-switcher" aria-label="选择工作模式">
      <button
        v-for="m in MODES"
        :key="m.id"
        type="button"
        class="mode-option"
        :class="{ active: mode === m.id }"
        @click="mode = m.id"
      >
        <span class="mode-icon" v-html="renderIcon(m.icon)" />
        <span class="mode-copy">
          <strong>{{ m.label }}</strong>
          <small>{{ m.sub }}</small>
        </span>
      </button>
    </div>

    <section class="composer-card">
      <header class="composer-head">
        <div class="composer-title">
          <span class="composer-icon" v-html="renderIcon(activeIcon)" />
          <strong>{{ activeLabel }}</strong>
          <span>{{ activeSub }}</span>
        </div>
        <p>{{ mode === 'builder' ? '从需求识别、结构梳理到应用搭建，一次完成。' : '生成低代码扩展组件、页面与接口。' }}</p>
      </header>

      <textarea
        v-model="text"
        class="composer-input"
        :placeholder="placeholder"
        rows="5"
      />

      <footer class="composer-foot">
        <button class="tool-btn" type="button" @click="emit('upload-file')">
          <span v-html="renderIcon('upload')" />
          <span>上传文件</span>
        </button>
        <button class="primary-btn" type="button" :disabled="!text.trim()" @click="submit">
          <span v-html="renderIcon('arrow')" />
          <span>{{ cta }}</span>
          <kbd>⌘↵</kbd>
        </button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
/* v3 redesign · 2026-05-20 — visual refresh only, template/script untouched.
   Preserved (don't change):
     - 2 modes (builder/coding) — NOT 3 (no 低代码 third option)
     - All class names (.landing-composer/.mode-switcher/.mode-option/.composer-card/.composer-head/.composer-input/.composer-foot/.tool-btn/.primary-btn)
     - 860px @media single-column breakpoint
     - submit() router push (in <script>, not touched)
   Refreshed:
     - hardcoded rgba(91,91,214,X)/rgba(45,44,123,X)/rgba(56,55,158,X) → --brand-ring/--brand-glow/--line/--sh-4
     - linear-gradient(--brand-500,--brand-700) primary btn → --brand single color (v3 clean-blue spec)
     - composer-head violet gradient → soft brand-soft fade (matches design-spec hero)
     - radius 14/10px → var(--r-5,16px) outer / var(--r-3,8px) inner
     - weights 780/760/720/650 → capped at fw-semibold(600)/fw-medium(500) per v3 4-档
     - transitions → var(--ease) cubic-bezier(.2,.8,.2,1)
     - kbd font-family typo var(--d-font-mono) → var(--font-mono)
*/
.landing-composer {
  width: min(100%, 920px);
  margin: 0 auto;
}

.mode-switcher {
  width: min(100%, 560px);
  margin: 0 auto 12px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  padding: 6px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-4, 12px);
  background: var(--surface);
  box-shadow: var(--sh-2);
}

.mode-option {
  min-width: 0;
  min-height: 44px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 14px;
  border: 1px solid transparent;
  border-radius: var(--r-3, 8px);
  background: transparent;
  color: var(--text-2);
  cursor: pointer;
  font-family: inherit;
  transition: background 0.16s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.16s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              color 0.16s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              box-shadow 0.16s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.mode-option:hover {
  background: var(--brand-soft);
  color: var(--text);
}

.mode-option.active {
  color: var(--brand);
  background: var(--brand-soft);
  border-color: var(--brand-ring);
  box-shadow: inset 0 0 0 1px var(--brand-ring);
}

.mode-icon,
.composer-icon,
.tool-btn span:first-child,
.primary-btn span:first-child {
  width: 22px;
  height: 22px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
}

.mode-copy {
  min-width: 0;
  display: flex;
  align-items: baseline;
  gap: 12px;
  white-space: nowrap;
}

.mode-copy strong {
  font-size: 13px;
  font-weight: var(--fw-semibold, 600);
}

.mode-copy small {
  color: var(--text-3);
  font-size: var(--t-micro, 11px);
  font-weight: var(--fw-medium, 500);
}

.composer-card {
  overflow: hidden;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-5, 16px);
  background: var(--surface);
  box-shadow: var(--sh-4);
}

.composer-head {
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 0 18px;
  border-bottom: 1px solid var(--line);
  background: linear-gradient(180deg, var(--brand-soft) 0%, var(--surface) 100%);
}

.composer-title {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 12px;
  color: var(--text);
}

.composer-title strong {
  font-size: var(--t-body, 14px);
  font-weight: var(--fw-semibold, 600);
}

.composer-title span:last-child {
  color: var(--text-3);
  font-size: var(--t-small, 12.5px);
  font-weight: var(--fw-regular, 400);
}

.composer-head p {
  margin: 0;
  color: var(--text-3);
  font-size: var(--t-small, 12.5px);
  font-weight: var(--fw-regular, 400);
  white-space: nowrap;
}

.composer-input {
  display: block;
  width: 100%;
  min-height: 150px;
  padding: 20px 24px;
  border: none;
  outline: none;
  resize: none;
  background: transparent;
  color: var(--text);
  font-family: inherit;
  font-size: var(--t-body, 14px);
  line-height: 1.65;
}

.composer-input::placeholder {
  color: var(--text-3);
}

.composer-foot {
  min-height: 58px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 14px;
  border-top: 1px solid var(--line);
  background: var(--surface);
}

.tool-btn,
.primary-btn {
  min-height: 44px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  border-radius: var(--r-3, 8px);
  font-family: inherit;
  font-size: 13px;
  font-weight: var(--fw-semibold, 600);
  cursor: pointer;
  transition: transform 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              background 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              border-color 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1)),
              box-shadow 0.14s var(--ease, cubic-bezier(0.2, 0.8, 0.2, 1));
}

.tool-btn {
  padding: 0 18px;
  color: var(--brand-text);
  background: var(--surface);
  border: 1px solid var(--line-strong);
}

.tool-btn:hover {
  background: var(--brand-soft);
  border-color: var(--brand-ring);
}

.tool-btn:focus-visible,
.primary-btn:focus-visible {
  outline: 2px solid var(--line-focus, var(--brand-ring));
  outline-offset: 2px;
}

.primary-btn {
  padding: 0 18px 0 20px;
  color: #fff;
  background: var(--brand);
  border: 1px solid var(--brand);
  box-shadow: var(--sh-brand);
}

.primary-btn:not(:disabled):hover {
  background: var(--brand-hover);
  border-color: var(--brand-hover);
  transform: translateY(-1px);
}

.primary-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
  box-shadow: none;
}

.primary-btn kbd {
  height: 22px;
  display: inline-flex;
  align-items: center;
  padding: 0 7px;
  border-radius: var(--r-2, 6px);
  color: rgba(255, 255, 255, 0.82);
  background: rgba(255, 255, 255, 0.16);
  font-family: var(--font-mono, 'JetBrains Mono', 'SF Mono', Menlo, monospace);
  font-size: var(--t-micro, 11px);
  font-weight: var(--fw-bold, 700);
}

html[data-theme="dark"] .mode-switcher,
html[data-theme="dark"] .composer-card,
html[data-theme="dark"] .composer-foot {
  background: var(--surface);
}

html[data-theme="dark"] .composer-head {
  background: linear-gradient(180deg, var(--brand-soft) 0%, var(--surface) 100%);
}

@media (max-width: 860px) {
  .mode-switcher {
    grid-template-columns: 1fr;
  }

  .composer-head,
  .composer-foot {
    align-items: stretch;
    flex-direction: column;
    height: auto;
    padding: 16px;
  }

  .composer-head p {
    white-space: normal;
  }

  .primary-btn,
  .tool-btn {
    width: 100%;
  }
}
</style>
