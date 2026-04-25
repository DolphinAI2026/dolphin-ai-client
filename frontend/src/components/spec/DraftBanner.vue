<template>
  <div class="draft-banner">
    <div class="banner-content">
      <span class="banner-icon">✏️</span>
      <span class="banner-text">
        你正在编辑草稿
        <span v-if="canonicalVersion">（基于 canonical v{{ canonicalVersion }}）</span>
      </span>
      <span v-if="currentProposal" class="banner-link">
        ↳ 当前提案：
        <a :href="`/proposals/${currentProposal.id}`">
          {{ currentProposal.title }} ({{ currentProposal.status }})
        </a>
      </span>
    </div>
    <div class="banner-actions">
      <button v-if="!currentProposal" class="builder-btn builder-btn-primary" @click="emit('promote')">
        Promote to Proposal
      </button>
      <button class="builder-btn" @click="emit('discard')">Discard Draft</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { ProposalSummary } from '@/types/proposal'

defineProps<{
  canonicalVersion?: number | null
  currentProposal?: ProposalSummary | null
}>()
const emit = defineEmits<{
  promote: []
  discard: []
}>()
</script>

<style scoped>
.draft-banner {
  display: flex; justify-content: space-between; align-items: center;
  padding: 8px 16px; background: var(--brand-soft);
  border-bottom: 1px solid var(--brand);
  color: var(--fg);
  font-size: 13px;
}
.banner-content { display: flex; gap: 12px; align-items: center; }
.banner-icon { font-size: 16px; }
.banner-link a { color: var(--brand); text-decoration: none; }
.banner-link a:hover { text-decoration: underline; }
.banner-actions { display: flex; gap: 8px; }
</style>
