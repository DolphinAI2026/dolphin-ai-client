<!-- 审查面板:Codex「已编辑 N 个文件 +X -Y」摘要 + 文件清单。
     不重写 diff 渲染——点文件 emit select-file,CodingPage 切到文件面板用 CodeViewer 看 diff。 -->
<template>
  <div class="review-panel">
    <div class="rv-summary">
      <div class="rv-summary-text">
        <span class="rv-files-n">已编辑 {{ totalFiles }} 个文件</span>
        <span v-if="totalAdds" class="rv-add">+{{ totalAdds }}</span>
        <span v-if="totalDels" class="rv-del">-{{ totalDels }}</span>
      </div>
      <button
        v-if="totalFiles > 0"
        class="rv-accept-all"
        :disabled="accepting"
        @click="$emit('accept-all')"
      >审核</button>
    </div>

    <div v-if="files.length" class="rv-files">
      <button
        v-for="f in files"
        :key="f.path"
        class="rv-file"
        :class="{ 'is-selected': f.path === selected }"
        :title="f.path"
        @click="$emit('select-file', f.path)"
      >
        <span class="rv-badge" :class="'st-' + f.status">{{ f.status }}</span>
        <span class="rv-path">{{ f.path }}</span>
        <span v-if="f.additions" class="rv-add">+{{ f.additions }}</span>
        <span v-if="f.deletions" class="rv-del">-{{ f.deletions }}</span>
      </button>
    </div>
    <p v-else class="rv-empty">本轮暂无文件改动</p>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { WorkspaceChanges } from '@/api/coding'

const props = defineProps<{
  changes: WorkspaceChanges | null
  selected: string | null
  accepting?: boolean
}>()
defineEmits<{ (e: 'select-file', path: string): void; (e: 'accept-all'): void }>()

const files = computed(() => props.changes?.files ?? [])
const totalFiles = computed(() => props.changes?.total?.files ?? files.value.length)
const totalAdds = computed(() => props.changes?.total?.additions ?? 0)
const totalDels = computed(() => props.changes?.total?.deletions ?? 0)
</script>

<style scoped>
.review-panel { display: flex; flex-direction: column; height: 100%; overflow: hidden; background: var(--cx-bg-0); }
.rv-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--cx-border);
}
.rv-summary-text { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; color: var(--cx-text-1); }
.rv-files-n { font-weight: 500; }
.rv-add { color: var(--cx-green); font-family: var(--cx-mono); font-size: 12px; }
.rv-del { color: var(--cx-red); font-family: var(--cx-mono); font-size: 12px; }
.rv-accept-all {
  background: var(--cx-bg-3);
  border: 1px solid var(--cx-border-hi);
  color: var(--cx-text-1);
  border-radius: 6px;
  padding: 4px 12px;
  font-size: 12px;
  cursor: pointer;
}
.rv-accept-all:hover:not(:disabled) { background: var(--cx-brand); border-color: var(--cx-brand); color: #fff; }
.rv-accept-all:disabled { opacity: 0.5; cursor: default; }
.rv-files { flex: 1; overflow-y: auto; padding: 6px; }
.rv-file {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  background: transparent;
  border: none;
  border-radius: 6px;
  padding: 6px 8px;
  cursor: pointer;
  text-align: left;
  font-size: 12.5px;
}
.rv-file:hover { background: var(--cx-bg-hover); }
.rv-file.is-selected { background: var(--cx-bg-3); }
.rv-badge {
  flex-shrink: 0;
  width: 16px;
  text-align: center;
  font-family: var(--cx-mono);
  font-size: 11px;
  border-radius: 3px;
}
.rv-badge.st-A { color: var(--cx-green); }
.rv-badge.st-M { color: var(--cx-accent); }
.rv-badge.st-D { color: var(--cx-red); }
.rv-path {
  flex: 1;
  color: var(--cx-text-2);
  font-family: var(--cx-mono);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  direction: rtl;
  text-align: left;
}
.rv-empty { color: var(--cx-text-3); font-size: 13px; text-align: center; padding: 24px 12px; margin: 0; }
</style>
