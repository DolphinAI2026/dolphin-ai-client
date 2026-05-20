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
  border: 1px solid var(--border-strong);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.86);
  box-shadow: var(--shadow-sm);
}

.mode-option {
  min-width: 0;
  min-height: 44px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 14px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  color: var(--text-2);
  cursor: pointer;
  font-family: inherit;
  transition: background 0.16s, border-color 0.16s, color 0.16s, box-shadow 0.16s;
}

.mode-option:hover {
  background: var(--brand-soft);
  color: var(--text);
}

.mode-option.active {
  color: var(--brand-text);
  background: var(--brand-soft);
  border-color: rgba(91, 91, 214, 0.35);
  box-shadow: inset 0 0 0 1px rgba(91, 91, 214, 0.08);
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
  font-weight: 760;
}

.mode-copy small {
  color: var(--text-3);
  font-size: 11px;
  font-weight: 600;
}

.composer-card {
  overflow: hidden;
  border: 1px solid rgba(91, 91, 214, 0.22);
  border-radius: 14px;
  background: var(--surface);
  box-shadow: 0 20px 52px rgba(45, 44, 123, 0.12), 0 2px 6px rgba(45, 44, 123, 0.06);
}

.composer-head {
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 0 18px;
  border-bottom: 1px solid rgba(91, 91, 214, 0.14);
  background: linear-gradient(180deg, rgba(242, 240, 254, 0.86), rgba(255, 255, 255, 0.94));
}

.composer-title {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 12px;
  color: var(--text);
}

.composer-title strong {
  font-size: 14px;
  font-weight: 780;
}

.composer-title span:last-child {
  color: var(--text-3);
  font-size: 12px;
  font-weight: 650;
}

.composer-head p {
  margin: 0;
  color: var(--text-3);
  font-size: 12px;
  font-weight: 650;
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
  font-size: 14px;
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
  border-top: 1px solid rgba(91, 91, 214, 0.12);
  background: rgba(255, 255, 255, 0.9);
}

.tool-btn,
.primary-btn {
  min-height: 44px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  border-radius: 10px;
  font-family: inherit;
  font-size: 13px;
  font-weight: 720;
  cursor: pointer;
  transition: transform 0.14s, background 0.14s, border-color 0.14s, box-shadow 0.14s;
}

.tool-btn {
  padding: 0 18px;
  color: var(--brand-text);
  background: var(--surface);
  border: 1px solid rgba(91, 91, 214, 0.18);
}

.tool-btn:hover {
  background: var(--brand-soft);
  border-color: rgba(91, 91, 214, 0.34);
}

.primary-btn {
  padding: 0 18px 0 20px;
  color: #fff;
  background: linear-gradient(135deg, var(--brand-500), var(--brand-700));
  border: 1px solid rgba(56, 55, 158, 0.42);
  box-shadow: 0 14px 28px rgba(91, 91, 214, 0.24);
}

.primary-btn:not(:disabled):hover {
  transform: translateY(-1px);
  box-shadow: 0 18px 34px rgba(91, 91, 214, 0.28);
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
  border-radius: 6px;
  color: rgba(255, 255, 255, 0.82);
  background: rgba(255, 255, 255, 0.16);
  font-family: var(--d-font-mono);
  font-size: 11px;
  font-weight: 700;
}

html[data-theme="dark"] .mode-switcher,
html[data-theme="dark"] .composer-card,
html[data-theme="dark"] .composer-foot {
  background: var(--surface);
}

html[data-theme="dark"] .composer-head {
  background: linear-gradient(180deg, rgba(138, 138, 240, 0.12), rgba(21, 19, 31, 0.92));
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
