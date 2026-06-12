<template>
  <div class="activity-panel">
    <DraftCard v-if="draft" :draft="draft" :mode="mode" />
    <ProposalCard
      v-for="p in visibleProposals"
      :key="p.id"
      :proposal="p"
      :mode="mode"
      :role="role"
    />
    <DeployedCard v-if="canonical" :canonical="canonical" :history="appliedHistory" />
    <GitStatusCard v-if="git && mode === 'pro'" :git="git" />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import DraftCard from './activity/DraftCard.vue'
import ProposalCard from './activity/ProposalCard.vue'
import DeployedCard from './activity/DeployedCard.vue'
import GitStatusCard from './activity/GitStatusCard.vue'
import type { ProposalSummary } from '@/types/proposal'
import type { ProjectRole } from '@/types/collaboration'

const props = defineProps<{
  applicationId: number
  draft: { id: string; version: number; completeness_confirmed: number; completeness_total: number; updated_at: string } | null
  canonical: { id: string; version: number; updated_at: string } | null
  proposals: ProposalSummary[]
  appliedHistory: ProposalSummary[]
  git: { repo_url: string; connected: boolean; provider: string | null; default_branch: string | null } | null
  mode: 'simple' | 'pro'
  role: ProjectRole
}>()

const visibleProposals = computed(() => {
  if (props.mode === 'simple') return []  // 简单模式不展示提案列表
  return props.proposals
})
</script>

<style scoped>
.activity-panel { display: flex; flex-direction: column; gap: 12px; }
</style>
