<template>
  <header class="ws-topbar">
    <div class="topbar-left">
      <button class="back-btn" type="button" @click="$router.push('/apps')" title="返回应用列表">
        ← 应用
      </button>
      <h2 class="app-title">{{ app.app_name }}</h2>
      <code class="app-code">{{ app.app_code }}</code>
    </div>
    <div class="topbar-center">
      <ModeToggle
        :mode="effectiveMode"
        :disabled="!canToggleMode"
        @change="$emit('toggleMode', $event)"
      />
    </div>
    <div class="topbar-right">
      <div class="member-avatars" :title="memberSummary">
        <span v-for="m in members.slice(0, 3)" :key="m.user_id" class="avatar">{{ m.username[0].toUpperCase() }}</span>
        <span v-if="members.length > 3" class="avatar-more">+{{ members.length - 3 }}</span>
      </div>
      <span v-if="git" :class="['git-status', git.connected ? 'ok' : 'warn']">
        ◐ {{ git.connected ? 'Synced' : '未连接' }}
      </span>
    </div>
  </header>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import ModeToggle from './ModeToggle.vue'
import type { WorkStateMember } from '@/api/workState'

const props = defineProps<{
  app: { id: number; app_name: string; app_code: string; status: string }
  members: WorkStateMember[]
  git: { repo_url: string; connected: boolean; provider?: string | null; default_branch?: string | null } | null
  effectiveMode: 'simple' | 'pro'
  canToggleMode: boolean
}>()

defineEmits<{
  toggleMode: [mode: 'simple' | 'pro']
}>()

const memberSummary = computed(() => props.members.map(m => m.username).join(', '))
</script>

<style scoped>
.ws-topbar { display: flex; align-items: center; padding: 8px 16px; background: var(--bg-panel); border-bottom: 1px solid var(--line); gap: 16px; }
.topbar-left { display: flex; gap: 12px; align-items: center; flex: 1; }
.topbar-center { display: flex; justify-content: center; }
.topbar-right { display: flex; gap: 12px; align-items: center; flex: 1; justify-content: flex-end; }
.back-btn { background: transparent; border: 0; color: var(--fg-muted); cursor: pointer; padding: 4px 8px; }
.back-btn:hover { color: var(--fg); }
.app-title { margin: 0; font-size: 16px; color: var(--fg); }
.app-code { font-family: var(--b-mono, monospace); font-size: 12px; color: var(--fg-muted); padding: 2px 6px; background: var(--bg-inset); border-radius: 4px; }
.member-avatars { display: flex; gap: 4px; }
.avatar { width: 24px; height: 24px; border-radius: 50%; background: var(--brand); color: var(--fg-on-ink); display: flex; align-items: center; justify-content: center; font-size: 11px; }
.avatar-more { width: 24px; height: 24px; border-radius: 50%; background: var(--bg-inset); color: var(--fg-muted); display: flex; align-items: center; justify-content: center; font-size: 11px; }
.git-status { font-size: 12px; padding: 2px 8px; border-radius: 8px; }
.git-status.ok { background: var(--t-success-subtle); color: var(--t-success); }
.git-status.warn { background: var(--t-warning-subtle); color: var(--t-warning); }
</style>
