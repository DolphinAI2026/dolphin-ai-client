<template>
  <section class="activity-card">
    <h4><AppIcon name="link" :size="15" /> Git 仓库</h4>
    <p>
      <a v-if="git.repo_url" :href="git.repo_url" target="_blank">{{ git.provider || 'git' }} ↗</a>
    </p>
    <p class="muted small">分支：{{ git.default_branch || 'main' }}</p>
    <p :class="['muted', 'small', git.connected ? 'ok' : 'warn']">
      {{ git.connected ? '✓ Connection 配置正常' : '⚠ Project 未连接 git' }}
    </p>
  </section>
</template>

<script setup lang="ts">
import AppIcon from '@/components/common/AppIcon.vue'

defineProps<{
  git: { repo_url: string; provider: string | null; default_branch: string | null; connected: boolean }
}>()
</script>

<style scoped>
.activity-card { padding: 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--bg-panel); }
h4 { margin: 0 0 8px; font-size: 14px; color: var(--fg); }
a { color: var(--brand); text-decoration: none; }
.muted { color: var(--fg-muted); font-size: 11px; }
.small { font-size: 11px; }
.ok { color: var(--t-success); }
.warn { color: var(--t-warning); }
</style>
