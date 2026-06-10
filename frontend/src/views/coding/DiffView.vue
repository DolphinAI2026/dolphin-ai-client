<template>
  <div class="diff-view" role="table" aria-label="文件改动对比">
    <div
      v-for="(row, i) in rows"
      :key="i"
      class="dv-row"
      :class="`dv-${row.type}`"
    >
      <template v-if="row.type === 'hunk'">
        <span class="dv-hunk-text">⋯ {{ row.text || '未改动区域已折叠' }}</span>
      </template>
      <template v-else>
        <span class="dv-no dv-no-old">{{ row.oldNo ?? '' }}</span>
        <span class="dv-no dv-no-new">{{ row.newNo ?? '' }}</span>
        <span class="dv-sign">{{ row.type === 'add' ? '+' : row.type === 'del' ? '−' : '' }}</span>
        <span class="dv-text">{{ row.text }}</span>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { parseUnifiedDiff } from './unifiedDiff'

const props = defineProps<{ diff: string }>()
const rows = computed(() => parseUnifiedDiff(props.diff))
</script>

<style scoped>
.diff-view {
  font-family: var(--font-mono, monospace);
  font-size: 12.5px;
  line-height: 1.45;
  padding: 6px 0 14px;
  min-width: 100%;
  width: max-content;
}
.dv-row {
  display: flex;
  align-items: baseline;
  white-space: pre;
  padding-right: 16px;
}
.dv-no {
  flex: none;
  width: 2.6em;
  padding-right: 0.7em;
  text-align: right;
  color: var(--fg-faint, #bbb);
  user-select: none;
  position: sticky;
  z-index: 1;
  background: inherit;
}
.dv-no-old { left: 0; }
.dv-no-new { left: 3.3em; }
.dv-sign {
  flex: none;
  width: 1.2em;
  text-align: center;
  user-select: none;
}
.dv-text { flex: 1; }
.dv-ctx { background: var(--bg, #fff); color: var(--fg-dim, #555); }
.dv-add { background: color-mix(in srgb, var(--t-success, #16a34a) 14%, var(--bg, #fff)); }
.dv-add .dv-sign, .dv-add .dv-text { color: var(--t-success, #16a34a); }
.dv-del { background: color-mix(in srgb, var(--t-danger, #e5484d) 12%, var(--bg, #fff)); }
.dv-del .dv-sign, .dv-del .dv-text { color: var(--t-danger, #e5484d); }
.dv-hunk {
  background: var(--bg-sub, rgba(0, 0, 0, 0.03));
  color: var(--fg-faint, #999);
  padding: 3px 12px;
  margin: 4px 0;
  font-size: 11.5px;
  user-select: none;
}
.dv-hunk-text { position: sticky; left: 12px; }
</style>
