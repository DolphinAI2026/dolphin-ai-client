<template>
  <nav class="top-bar">
    <div class="top-bar-left">
      <!-- 汉堡菜单 -->
      <button v-if="showHamburger" class="top-bar-btn" @click="$emit('toggle-sidebar')" title="切换侧栏">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
      </button>
      <!-- 返回按钮 -->
      <button v-if="showBack" class="top-bar-btn" @click="handleBack" title="返回">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>
      </button>
      <!-- Logo + 标题 -->
      <button v-if="showHome" class="top-bar-home" @click="router.push('/')" title="返回首页">
        <div class="top-bar-logo">A</div>
      </button>
      <span v-if="title" class="top-bar-title">{{ title }}</span>
      <!-- 中间 slot -->
      <slot name="center" />
    </div>
    <div v-if="$slots.actions" class="top-bar-right">
      <button class="top-bar-command" type="button" @click="openCommandPalette" title="命令面板">
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <circle cx="7" cy="7" r="4.2" stroke="currentColor" stroke-width="1.4" />
          <path d="m10.2 10.2 2.8 2.8" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
        </svg>
        <span>搜索应用、模型、对话...</span>
        <kbd>⌘K</kbd>
      </button>
      <slot name="actions" />
    </div>
    <div v-else class="top-bar-right">
      <button class="top-bar-command" type="button" @click="openCommandPalette" title="命令面板">
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <circle cx="7" cy="7" r="4.2" stroke="currentColor" stroke-width="1.4" />
          <path d="m10.2 10.2 2.8 2.8" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
        </svg>
        <span>搜索应用、模型、对话...</span>
        <kbd>⌘K</kbd>
      </button>
    </div>
  </nav>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'

const props = withDefaults(defineProps<{
  title?: string
  showHamburger?: boolean
  showBack?: boolean
  showHome?: boolean
  backTo?: string
}>(), {
  title: 'aPaaS Builder AI',
  showHamburger: false,
  showBack: false,
  showHome: true,
  backTo: '/',
})

defineEmits<{
  'toggle-sidebar': []
}>()

const router = useRouter()

function handleBack() {
  router.push(props.backTo)
}

function openCommandPalette() {
  window.dispatchEvent(new CustomEvent('builder:open-command'))
}
</script>

<style scoped>
.top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 48px;
  padding: 0 12px;
  background: var(--t-bg-panel);
  border-bottom: 1px solid var(--t-border-subtle);
  flex-shrink: 0;
  z-index: 10;
}
.top-bar-left {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex: 1;
}
.top-bar-right { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }

.top-bar-command {
  height: 30px;
  min-width: 260px;
  border: 1px solid var(--t-border-subtle);
  border-radius: 8px;
  background: var(--t-bg-input);
  color: var(--t-text-secondary);
  display: inline-flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 0 8px;
  cursor: pointer;
  font-size: 12px;
}

.top-bar-command:hover {
  background: var(--t-bg-panel-hover);
  color: var(--t-text-primary);
}

.top-bar-command kbd {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 10px;
  line-height: 1;
  padding: 3px 5px;
  border-radius: 4px;
  border: 1px solid var(--t-border-subtle);
  background: var(--t-bg-panel);
  color: var(--t-text-muted);
}

/* Buttons */
.top-bar-btn {
  width: 34px;
  height: 34px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--t-text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
  flex-shrink: 0;
}
.top-bar-btn:hover {
  background: var(--t-bg-panel-hover);
  color: var(--t-text-primary);
}

/* Logo */
.top-bar-home {
  border: none;
  background: none;
  cursor: pointer;
  padding: 0;
  display: flex;
  align-items: center;
  flex-shrink: 0;
}
.top-bar-logo {
  width: 28px;
  height: 28px;
  background: var(--t-brand-gradient);
  border-radius: 7px;
  color: #fff;
  font-weight: 700;
  font-size: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* Title */
.top-bar-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--t-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-left: 2px;
}

/* User avatar */
.user-avatar-btn {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  border: none;
  background: var(--t-brand-gradient);
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: opacity 0.15s;
  flex-shrink: 0;
}
.user-avatar-btn:hover {
  opacity: 0.85;
}

/* User menu */
.user-menu-info {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 2px 0;
}
.user-menu-label {
  font-size: 10px;
  color: var(--t-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.user-menu-value {
  font-size: 13px;
  font-weight: 500;
  color: var(--t-text-primary);
}
.menu-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.menu-row svg {
  flex-shrink: 0;
}
</style>
