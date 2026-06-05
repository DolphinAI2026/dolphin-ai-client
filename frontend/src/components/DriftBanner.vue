<template>
  <div v-if="status?.drift" class="drift-banner">
    <div class="banner-content">
      <span class="banner-icon"><AppIcon name="warning" :size="16" /></span>
      <span class="banner-text">
        Git main 与 Builder 状态不一致：
        <code>git={{ status.git_sha?.slice(0, 8) || 'none' }}</code>
        vs
        <code>builder={{ (status.builder_sha || 'none').slice(0, 8) }}</code>
        <span v-if="status.reason" class="banner-reason">（{{ status.reason }}）</span>
      </span>
    </div>
    <div class="banner-actions">
      <button class="builder-btn" type="button" @click="$emit('resolve')">解决漂移</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { DriftStatus } from '@/api/gitConnection'
import AppIcon from '@/components/common/AppIcon.vue'

defineProps<{
  status?: DriftStatus | null
}>()
defineEmits<{
  resolve: []
}>()
</script>

<style scoped>
.drift-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 16px;
  background: var(--t-warning-subtle, rgba(251, 191, 36, 0.1));
  color: var(--t-warning, #d97706);
  border-bottom: 1px solid var(--t-warning, #d97706);
  font-size: 13px;
}
.banner-content { display: flex; gap: 12px; align-items: center; }
.banner-icon { font-size: 16px; }
.banner-text code {
  background: rgba(0, 0, 0, .06);
  padding: 1px 4px;
  border-radius: 3px;
  font-family: var(--b-mono, ui-monospace, SFMono-Regular, monospace);
  font-size: 12px;
  margin: 0 2px;
}
.banner-reason {
  margin-left: 4px;
  opacity: 0.8;
  font-size: 12px;
}
.banner-actions { display: flex; gap: 8px; }
.builder-btn {
  padding: 4px 12px;
  font-size: 12px;
  border: 1px solid var(--t-warning, #d97706);
  background: transparent;
  color: var(--t-warning, #d97706);
  border-radius: 4px;
  cursor: pointer;
}
.builder-btn:hover { background: rgba(0, 0, 0, .04); }
</style>
