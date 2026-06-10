<template>
  <nav class="ws-file-tree" aria-label="工作区文件">
    <div class="ws-file-tree-search">
      <AppIcon name="search" :size="13" :stroke="1.9" class="wfs-icon" />
      <input
        v-model="query"
        class="wfs-input"
        type="text"
        placeholder="筛选文件…"
        spellcheck="false"
        aria-label="筛选文件"
      />
      <button v-if="query" class="wfs-clear" title="清除" @click="query = ''">
        <AppIcon name="x" :size="13" :stroke="2" />
      </button>
    </div>
    <div class="ws-file-tree-body">
      <FileTreeNode
        v-for="node in displayTree"
        :key="node.path"
        :node="node"
        :changed="changed"
        :selected="selected"
        @select="$emit('select', $event)"
      />
      <p v-if="!tree.length" class="ws-file-tree-empty">暂无文件</p>
      <p v-else-if="!displayTree.length" class="ws-file-tree-empty">无匹配文件</p>
    </div>
  </nav>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { TreeNode } from './fileTree'
import AppIcon from '@/components/common/AppIcon.vue'
import FileTreeNode from './FileTreeNode.vue'

const props = defineProps<{
  tree: TreeNode[]
  changed: Set<string>
  selected: string | null
}>()
defineEmits<{ (e: 'select', path: string): void }>()

const query = ref('')

// 递归筛选:保留名字命中的文件 + 其祖先目录(目录名命中则整目录保留)
function filterTree(nodes: TreeNode[], lower: string): TreeNode[] {
  const out: TreeNode[] = []
  for (const n of nodes) {
    if (n.isDir) {
      const kids = filterTree(n.children || [], lower)
      if (kids.length || n.name.toLowerCase().includes(lower)) {
        out.push({ ...n, children: n.name.toLowerCase().includes(lower) ? n.children : kids })
      }
    } else if (n.name.toLowerCase().includes(lower)) {
      out.push(n)
    }
  }
  return out
}

const displayTree = computed(() => {
  const q = query.value.trim().toLowerCase()
  return q ? filterTree(props.tree, q) : props.tree
})
</script>

<style scoped>
.ws-file-tree {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--bg-sub, var(--bg, #fff));
}
.ws-file-tree-search {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: none;
  margin: 8px;
  padding: 5px 9px;
  border: 1px solid var(--line, rgba(0, 0, 0, 0.1));
  border-radius: var(--r-sm, 6px);
  background: var(--bg, #fff);
  transition: border-color 0.12s var(--ease, ease);
}
.ws-file-tree-search:focus-within { border-color: var(--brand, #6366f1); }
.wfs-icon { flex: none; color: var(--fg-faint, #aaa); }
.wfs-input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  color: var(--fg, #222);
  font-size: var(--fs-sm, 13px);
}
.wfs-input::placeholder { color: var(--fg-faint, #aaa); }
.wfs-clear {
  flex: none;
  display: inline-flex;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--fg-faint, #aaa);
  cursor: pointer;
}
.wfs-clear:hover { color: var(--fg, #222); }
.ws-file-tree-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 2px 6px 6px;
}
.ws-file-tree-empty {
  margin: 16px 8px;
  font-size: var(--fs-sm, 13px);
  color: var(--fg-faint, #aaa);
}
</style>
