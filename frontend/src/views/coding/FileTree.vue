<template>
  <div class="ws-file-tree">
    <FileTreeNode
      v-for="node in tree"
      :key="node.path"
      :node="node"
      :changed="changed"
      :selected="selected"
      @select="$emit('select', $event)"
    />
  </div>
</template>

<script setup lang="ts">
import type { TreeNode } from './fileTree'
import FileTreeNode from './FileTreeNode.vue'

defineProps<{
  tree: TreeNode[]
  changed: Set<string>
  selected: string | null
}>()
defineEmits<{ (e: 'select', path: string): void }>()
</script>

<style scoped>
.ws-file-tree { font-size: 13px; padding: 6px 4px; overflow: auto; }
</style>
