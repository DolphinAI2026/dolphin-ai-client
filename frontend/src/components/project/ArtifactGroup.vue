<template>
  <section class="artifact-group">
    <header class="ag-head"><h3 class="ag-label">{{ label }}</h3></header>
    <div class="ag-grid">
      <ArtifactCard v-for="a in artifacts" :key="a.id" :artifact="a" @open="emit('open', $event)" />
    </div>
  </section>
</template>

<script setup lang="ts">
import ArtifactCard from './ArtifactCard.vue'
import type { ArtifactVM } from '@/composables/projectVM'
defineProps<{ label: string; artifacts: ArtifactVM[] }>()
const emit = defineEmits<{ (e: 'open', a: ArtifactVM): void }>()
</script>

<style scoped>
.artifact-group { margin-bottom:28px; }
.ag-label { font-size:13px; color:var(--text-2,#888); margin-bottom:12px; font-weight:600; }
.ag-grid { display:grid; gap:12px; grid-template-columns:repeat(auto-fill, minmax(200px, 1fr)); }
@media (max-width:600px){ .ag-grid { grid-template-columns:1fr; } }
</style>
