<template>
  <button class="artifact-card" :style="{ '--m': `var(--${artifact.mode})`, '--mbg': `var(--${artifact.mode}-bg)` }"
          @click="emit('open', artifact)">
    <div class="ac-top">
      <span class="ac-icon" :style="{ background: 'var(--mbg)', color: 'var(--m)' }">◧</span>
      <span class="ac-mode" :style="{ background: 'var(--mbg)', color: 'var(--m)' }">{{ modeLabel }}</span>
    </div>
    <div class="ac-name">{{ artifact.name }}</div>
    <div class="ac-summary">{{ artifact.summary }}</div>
    <div class="ac-status">
      <span class="ac-dot" :class="`tone-${artifact.status.tone}`"
            :aria-label="artifact.status.label" :title="artifact.status.label"></span>
      <span v-if="artifact.status.tone === 'error'" class="ac-err" aria-hidden="true">!</span>
      <span class="ac-status-label">{{ artifact.status.label }}</span>
    </div>
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ArtifactVM } from '@/composables/projectVM'
const props = defineProps<{ artifact: ArtifactVM }>()
const emit = defineEmits<{ (e: 'open', a: ArtifactVM): void }>()
const MODE_LABEL: Record<string, string> = { build: '构建', lowcode: '低代码二开', fullcode: 'Code', agent: 'Agent' }
const modeLabel = computed(() => MODE_LABEL[props.artifact.mode] || props.artifact.mode)
</script>

<style scoped>
.artifact-card { display:flex; flex-direction:column; gap:6px; text-align:left;
  min-height:80px; min-width:200px; padding:14px 16px; border:1px solid var(--line-2);
  border-radius:14px; background:var(--surface-2,#fff); cursor:pointer; }
.artifact-card:hover { border-color:var(--m); }
.ac-top { display:flex; justify-content:space-between; align-items:center; }
.ac-icon { width:28px; height:28px; border-radius:8px; display:grid; place-items:center; font-size:14px; }
.ac-mode { font-size:11px; padding:2px 8px; border-radius:8px; }
.ac-name { font-weight:600; font-size:14px; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
.ac-summary { font-size:12px; color:var(--text-2,#888); }
.ac-status { display:flex; align-items:center; gap:6px; font-size:12px; color:var(--text-2,#888); }
.ac-dot { width:7px; height:7px; border-radius:50%; background:var(--text-3,#bbb); }
.ac-dot.tone-building { background:#FBBF24; } .ac-dot.tone-live { background:#34D3E0; }
.ac-dot.tone-done { background:#4fb286; } .ac-dot.tone-error { background:#d9685e; }
.ac-dot.tone-draft { background:#9ba6af; }
.ac-err { color:#d9685e; font-weight:700; }
</style>
