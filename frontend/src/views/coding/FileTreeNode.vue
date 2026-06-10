<template>
  <div class="ftn">
    <div
      class="ftn-row"
      :class="{ selected: !node.isDir && selected === node.path }"
      :style="{ paddingLeft: depth * 12 + 8 + 'px' }"
      @click="onClick"
    >
      <span v-if="node.isDir" class="ftn-caret">{{ open ? '▾' : '▸' }}</span>
      <span class="ftn-name">{{ node.name }}</span>
      <span v-if="!node.isDir && changed.has(node.path)" class="ftn-dot" />
    </div>
    <template v-if="node.isDir && open">
      <FileTreeNode
        v-for="child in node.children"
        :key="child.path"
        :node="child"
        :changed="changed"
        :selected="selected"
        :depth="depth + 1"
        @select="$emit('select', $event)"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { TreeNode } from './fileTree'

const props = withDefaults(defineProps<{
  node: TreeNode
  changed: Set<string>
  selected: string | null
  depth?: number
}>(), { depth: 0 })
const emit = defineEmits<{ (e: 'select', path: string): void }>()

const open = ref(true)
function onClick() {
  if (props.node.isDir) open.value = !open.value
  else emit('select', props.node.path)
}
</script>

<style scoped>
.ftn-row { display: flex; align-items: center; gap: 4px; padding: 3px 4px; border-radius: 4px; cursor: pointer; white-space: nowrap; }
.ftn-row:hover { background: var(--ac-bg-hover, rgba(0,0,0,.04)); }
.ftn-row.selected { background: var(--ac-bg-active, rgba(64,128,255,.12)); }
.ftn-caret { width: 10px; color: var(--ac-text-secondary, #888); }
.ftn-name { overflow: hidden; text-overflow: ellipsis; }
.ftn-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--ac-warning, #e6a23c); margin-left: auto; flex: none; }
</style>
