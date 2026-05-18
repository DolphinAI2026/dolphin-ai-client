<script setup lang="ts">
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import ShellTopBar from '@/components/v2/ShellTopBar.vue'

const TITLE = '运行与发布'
const SUBTITLE = '即将在 P2 完成实现。当前仅占位以让导航生效。'
</script>

<template>
  <WorkbenchShell>
    <ShellTopBar />
    <div class="page">
      <div class="page-pad">
        <div class="page-head">
          <div>
            <h1 class="page-title">{{ TITLE }}</h1>
            <div class="page-subtitle">{{ SUBTITLE }}</div>
          </div>
        </div>
      </div>
    </div>
  </WorkbenchShell>
</template>

<style scoped>
.page { overflow-y: auto; min-height: 0; background: var(--bg-app); height: 100%; flex: 1; }
.page-pad { padding: 28px 32px 40px; max-width: 1320px; margin: 0 auto; }
.page-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin-bottom: 22px; }
.page-title { font-size: 22px; font-weight: 600; color: var(--text); letter-spacing: -0.02em; line-height: 1.2; margin: 0; }
.page-subtitle { font-size: 13px; color: var(--text-2); margin-top: 4px; }
</style>
