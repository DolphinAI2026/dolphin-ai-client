<template>
  <div class="ftn">
    <button
      type="button"
      class="ftn-row"
      :class="{ selected: !node.isDir && selected === node.path, dir: node.isDir }"
      :style="{ paddingLeft: depth * 12 + 8 + 'px' }"
      @click="onClick"
    >
      <svg
        v-if="node.isDir"
        class="ftn-caret"
        :class="{ open }"
        viewBox="0 0 24 24" width="12" height="12" aria-hidden="true"
      >
        <path d="M9 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
      <span v-else class="ftn-caret-spacer" />
      <AppIcon class="ftn-icon" :class="{ folder: node.isDir }" :name="iconName" :size="14" :stroke="1.9" />
      <span class="ftn-name" :class="changeClass" :title="node.name">{{ node.name }}</span>
      <span v-if="fileStatus" class="ftn-badge" :class="`st-${fileStatus.toLowerCase()}`" :title="fileStatus === 'A' ? '本轮新增' : '本轮修改'">{{ fileStatus }}</span>
      <span v-else-if="dirHasChanges" class="ftn-dot" title="目录内有改动" />
      <span v-else-if="!node.isDir && changed.has(node.path)" class="ftn-dot" title="本轮有改动" />
    </button>
    <template v-if="node.isDir && open">
      <FileTreeNode
        v-for="child in node.children"
        :key="child.path"
        :node="child"
        :changed="changed"
        :change-map="changeMap"
        :changed-dirs="changedDirs"
        :selected="selected"
        :depth="depth + 1"
        @select="$emit('select', $event)"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import AppIcon from '@/components/common/AppIcon.vue'
import type { TreeNode } from './fileTree'

const props = withDefaults(defineProps<{
  node: TreeNode
  changed: Set<string>
  /** path → A/M/D(git 基线), 提供时优先于 changed 圆点 */
  changeMap?: Map<string, string>
  /** 含改动的目录集合 */
  changedDirs?: Set<string>
  selected: string | null
  depth?: number
}>(), { depth: 0 })
const emit = defineEmits<{ (e: 'select', path: string): void }>()

const open = ref(true)
function onClick() {
  if (props.node.isDir) open.value = !open.value
  else emit('select', props.node.path)
}

const fileStatus = computed(() =>
  !props.node.isDir ? props.changeMap?.get(props.node.path) || null : null,
)
const dirHasChanges = computed(() => !!(props.node.isDir && props.changedDirs?.has(props.node.path)))
const changeClass = computed(() => (fileStatus.value ? `changed-${fileStatus.value.toLowerCase()}` : ''))

// 按扩展名挑图标，沿用 app 的 AppIcon 词表
const iconName = computed(() => {
  if (props.node.isDir) return 'folder'
  const ext = props.node.name.split('.').pop()?.toLowerCase() || ''
  if (['md', 'mdc', 'txt'].includes(ext)) return 'doc'
  if (['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'ico'].includes(ext)) return 'image'
  if (['json', 'yaml', 'yml', 'config'].includes(ext)) return 'settings'
  return 'file'
})
</script>

<style scoped>
.ftn-row {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 4px 8px 4px 0;
  border: none;
  background: transparent;
  border-radius: var(--r-sm, 6px);
  cursor: pointer;
  white-space: nowrap;
  color: var(--fg-dim, #555);
  font-size: var(--fs-sm, 13px);
  line-height: 1.4;
  position: relative;
  transition: background 0.12s var(--ease, ease), color 0.12s var(--ease, ease);
}
.ftn-row:hover { background: var(--bg-hover, rgba(0, 0, 0, 0.04)); color: var(--fg, #222); }
.ftn-row.dir { color: var(--fg, #222); font-weight: 500; }
.ftn-row.selected {
  background: var(--brand-soft, rgba(99, 102, 241, 0.1));
  color: var(--brand-ink, var(--brand, #4f46e5));
}
.ftn-row.selected::before {
  content: '';
  position: absolute;
  left: 0; top: 3px; bottom: 3px;
  width: 2.5px;
  border-radius: 2px;
  background: var(--brand, #6366f1);
}
.ftn-caret {
  flex: none;
  color: var(--fg-faint, #aaa);
  transition: transform 0.16s var(--ease, ease);
}
.ftn-caret.open { transform: rotate(90deg); }
.ftn-caret-spacer { width: 12px; flex: none; }
.ftn-icon { flex: none; color: var(--fg-faint, #999); }
.ftn-icon.folder { color: var(--brand, #6366f1); opacity: 0.75; }
.ftn-row.selected .ftn-icon { color: inherit; }
.ftn-name { overflow: hidden; text-overflow: ellipsis; }
/* git 状态着色: 新增绿 / 修改琥珀(对齐 VS Code 心智) */
.ftn-name.changed-a { color: var(--t-success, #16a34a); }
.ftn-name.changed-m { color: var(--warn, #d97706); }
.ftn-row.selected .ftn-name { color: inherit; }
.ftn-badge {
  margin-left: auto;
  flex: none;
  font-family: var(--font-mono, monospace);
  font-size: 10.5px;
  font-weight: 700;
  line-height: 1;
}
.ftn-badge.st-a { color: var(--t-success, #16a34a); }
.ftn-badge.st-m { color: var(--warn, #d97706); }
.ftn-badge.st-d { color: var(--t-danger, #e5484d); }
.ftn-dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: var(--ai, var(--brand, #6366f1));
  margin-left: auto;
  flex: none;
  box-shadow: 0 0 0 2px var(--bg, #fff);
}
</style>
