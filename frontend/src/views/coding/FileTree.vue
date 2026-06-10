<template>
  <nav class="ws-file-tree" aria-label="工作区文件">
    <div class="ws-file-tree-head">
      <AppIcon name="folder" :size="13" :stroke="1.9" />
      <span>文件</span>
    </div>
    <div class="ws-file-tree-body">
      <FileTreeNode
        v-for="node in tree"
        :key="node.path"
        :node="node"
        :changed="changed"
        :selected="selected"
        @select="$emit('select', $event)"
      />
      <p v-if="!tree.length" class="ws-file-tree-empty">暂无文件</p>
    </div>
  </nav>
</template>

<script setup lang="ts">
import type { TreeNode } from './fileTree'
import AppIcon from '@/components/common/AppIcon.vue'
import FileTreeNode from './FileTreeNode.vue'

defineProps<{
  tree: TreeNode[]
  changed: Set<string>
  selected: string | null
}>()
defineEmits<{ (e: 'select', path: string): void }>()
</script>

<style scoped>
.ws-file-tree {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--bg-sub, var(--bg, #fff));
}
.ws-file-tree-head {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: none;
  padding: 10px 12px;
  font-size: var(--fs-xs, 11px);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--fg-faint, #999);
  border-bottom: 1px solid var(--line, rgba(0, 0, 0, 0.07));
}
.ws-file-tree-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 6px;
}
.ws-file-tree-empty {
  margin: 16px 8px;
  font-size: var(--fs-sm, 13px);
  color: var(--fg-faint, #aaa);
}
</style>
