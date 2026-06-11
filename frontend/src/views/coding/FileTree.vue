<template>
  <nav class="ws-file-tree" aria-label="工作区文件">
    <div class="ws-file-tree-search">
      <AppIcon name="search" :size="13" :stroke="1.9" class="wfs-icon" />
      <input
        v-model="query"
        class="wfs-input"
        type="text"
        placeholder="筛选文件，Enter 搜内容…"
        spellcheck="false"
        aria-label="筛选文件或搜索内容"
        @keydown.enter.prevent="runContentSearch"
      />
      <button v-if="query" class="wfs-clear" title="清除" @click="clearSearch">
        <AppIcon name="x" :size="13" :stroke="2" />
      </button>
    </div>

    <!-- 内容搜索结果(Enter 触发): 替换树视图, 点击命中带行号打开 -->
    <div v-if="contentHits !== null" class="wft-search-results">
      <div class="wftr-head">
        <span class="wftr-title">内容搜索</span>
        <span class="wftc-count">{{ contentHits.length }}</span>
        <span v-if="contentTruncated" class="wftr-truncated">已截断</span>
        <button class="wftr-back" @click="clearSearch">返回文件树</button>
      </div>
      <p v-if="searching" class="ws-file-tree-empty">搜索中…</p>
      <p v-else-if="!contentHits.length" class="ws-file-tree-empty">无匹配内容</p>
      <button
        v-for="(h, i) in contentHits"
        :key="h.path + ':' + h.line + ':' + i"
        class="wftr-hit"
        :title="`${h.path}:${h.line}`"
        @click="$emit('select-line', { path: h.path, line: h.line })"
      >
        <span class="wftr-loc">{{ baseName(h.path) }}<span class="wftr-ln">:{{ h.line }}</span></span>
        <span class="wftr-text">{{ h.text }}</span>
      </button>
    </div>

    <!-- 本轮改动分组(git 基线): 置顶汇总 + 逐文件直达 diff; 构建产物折叠在尾部 -->
    <section v-if="contentHits === null && changeEntries.length" class="wft-changes" aria-label="本轮改动">
      <div class="wftc-head">
        <button type="button" class="wftc-toggle" @click="changesOpen = !changesOpen">
          <svg class="wftc-caret" :class="{ open: changesOpen }" viewBox="0 0 24 24" width="11" height="11" aria-hidden="true">
            <path d="M9 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          <span class="wftc-title">本轮改动</span>
          <span class="wftc-count">{{ sourceEntries.length }}</span>
          <span class="wftc-stats">
            <span v-if="sourceTotals.additions" class="wftc-add">+{{ sourceTotals.additions }}</span>
            <span v-if="sourceTotals.deletions" class="wftc-del">−{{ sourceTotals.deletions }}</span>
          </span>
        </button>
        <button type="button" class="wftc-accept" title="接受全部变更" @click="$emit('accept-all')">接受全部</button>
      </div>
      <template v-if="changesOpen">
        <button
          v-for="f in sourceEntries"
          :key="f.path"
          class="wftc-row"
          :class="{ selected: selected === f.path }"
          :title="f.path"
          @click="$emit('select', f.path)"
        >
          <span class="wftc-status" :class="`st-${f.status.toLowerCase()}`">{{ f.status }}</span>
          <span class="wftc-name" :class="{ deleted: f.status === 'D' }">{{ baseName(f.path) }}</span>
          <span v-if="dirName(f.path)" class="wftc-dir">{{ dirName(f.path) }}</span>
          <span v-if="!f.binary && (f.additions || f.deletions)" class="wftc-rowstats">
            <span v-if="f.additions" class="wftc-add">+{{ f.additions }}</span>
            <span v-if="f.deletions" class="wftc-del">−{{ f.deletions }}</span>
          </span>
        </button>
        <!-- 构建产物(umd/zip 等): 默认折叠, 不混进源码改动 -->
        <template v-if="artifactEntries.length">
          <button type="button" class="wftc-artifacts-toggle" @click="artifactsOpen = !artifactsOpen">
            <svg class="wftc-caret" :class="{ open: artifactsOpen }" viewBox="0 0 24 24" width="10" height="10" aria-hidden="true">
              <path d="M9 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
            <span>构建产物 {{ artifactEntries.length }} 个文件</span>
          </button>
          <template v-if="artifactsOpen">
            <button
              v-for="f in artifactEntries"
              :key="f.path"
              class="wftc-row wftc-row-artifact"
              :class="{ selected: selected === f.path }"
              :title="f.path"
              @click="$emit('select', f.path)"
            >
              <span class="wftc-status" :class="`st-${f.status.toLowerCase()}`">{{ f.status }}</span>
              <span class="wftc-name" :class="{ deleted: f.status === 'D' }">{{ baseName(f.path) }}</span>
              <span v-if="dirName(f.path)" class="wftc-dir">{{ dirName(f.path) }}</span>
            </button>
          </template>
        </template>
      </template>
    </section>

    <div v-if="contentHits === null" class="ws-file-tree-body">
      <FileTreeNode
        v-for="node in displayTree"
        :key="node.path"
        :node="node"
        :changed="changed"
        :change-map="changeMap"
        :changed-dirs="changedDirs"
        :selected="selected"
        @select="$emit('select', $event)"
      />
      <p v-if="!tree.length" class="ws-file-tree-empty">暂无文件</p>
      <p v-else-if="!displayTree.length" class="ws-file-tree-empty">无匹配文件</p>
    </div>
  </nav>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { compactTree, type TreeNode } from './fileTree'
import { searchWorkspaceContent, type WorkspaceChanges, type WorkspaceSearchHit } from '@/api/coding'
import AppIcon from '@/components/common/AppIcon.vue'
import FileTreeNode from './FileTreeNode.vue'

const props = defineProps<{
  tree: TreeNode[]
  changed: Set<string>
  changes?: WorkspaceChanges | null
  selected: string | null
  /** 内容搜索需要(不传则 Enter 搜索不可用) */
  wsId?: string
}>()
defineEmits<{
  (e: 'select', path: string): void
  (e: 'select-line', payload: { path: string; line: number }): void
  (e: 'accept-all'): void
}>()

const query = ref('')
const changesOpen = ref(true)
const artifactsOpen = ref(false)

// ── 内容搜索(Enter 触发, 后端逐行扫描) ──
const contentHits = ref<WorkspaceSearchHit[] | null>(null)
const contentTruncated = ref(false)
const searching = ref(false)

async function runContentSearch() {
  const q = query.value.trim()
  if (!q || !props.wsId) return
  searching.value = true
  contentHits.value = contentHits.value || []
  try {
    const res = await searchWorkspaceContent(props.wsId, q)
    contentHits.value = res.hits
    contentTruncated.value = res.truncated
  } catch {
    contentHits.value = []
    contentTruncated.value = false
  } finally {
    searching.value = false
  }
}

function clearSearch() {
  query.value = ''
}

// 清空输入 → 退出内容搜索模式回到树
watch(query, (v) => { if (!v.trim()) { contentHits.value = null; contentTruncated.value = false } })

const changeEntries = computed(() => (props.changes?.enabled ? props.changes.files : []))
const sourceEntries = computed(() => changeEntries.value.filter(f => !f.artifact))
const artifactEntries = computed(() => changeEntries.value.filter(f => f.artifact))
const sourceTotals = computed(() => ({
  additions: sourceEntries.value.reduce((s, f) => s + (f.additions || 0), 0),
  deletions: sourceEntries.value.reduce((s, f) => s + (f.deletions || 0), 0),
}))

// path → status, 文件节点徽标用
const changeMap = computed(() => {
  const m = new Map<string, string>()
  for (const f of changeEntries.value) m.set(f.path, f.status)
  return m
})

// 含改动的目录集合(所有祖先), 目录节点小圆点用; compactTree 合并链取最深 path 也能命中
const changedDirs = computed(() => {
  const dirs = new Set<string>()
  for (const f of changeEntries.value) {
    const parts = f.path.split('/')
    for (let i = 1; i < parts.length; i++) dirs.add(parts.slice(0, i).join('/'))
  }
  return dirs
})

function baseName(p: string) { return p.split('/').pop() || p }
function dirName(p: string) {
  const i = p.lastIndexOf('/')
  return i >= 0 ? p.slice(0, i) : ''
}

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
  return compactTree(q ? filterTree(props.tree, q) : props.tree)
})
</script>

<style scoped>
.ws-file-tree {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: linear-gradient(180deg, var(--bg-sub, #f8fafc) 0%, var(--bg-inset, var(--bg-sub, #f8fafc)) 100%);
}
.ws-file-tree-search {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: none;
  min-height: 36px;
  margin: 10px 10px 8px;
  padding: 6px 10px;
  border: 1px solid var(--line, rgba(0, 0, 0, 0.1));
  border-radius: var(--r-md, 8px);
  background: var(--bg, #fff);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03);
  transition: border-color 0.12s var(--ease, ease), box-shadow 0.12s var(--ease, ease);
}
.ws-file-tree-search:focus-within {
  border-color: color-mix(in srgb, var(--brand, #4f6ef7) 36%, var(--line, rgba(0, 0, 0, 0.1)));
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--brand, #4f6ef7) 10%, transparent);
}
.wfs-icon { flex: none; color: var(--fg-dim, #64748b); }
.wfs-input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  color: var(--fg, #222);
  font-size: 12.5px;
}
.wfs-input::placeholder { color: var(--fg-faint, #94a3b8); }
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

/* ── 内容搜索结果 ── */
.wft-search-results {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 0 8px 10px;
}
.wftr-head {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 28px;
  padding: 4px 6px;
  font-size: var(--fs-sm, 13px);
  font-weight: 600;
  color: var(--fg, #222);
}
.wftr-truncated { font-size: var(--fs-xs, 11px); color: var(--warn, #d97706); font-weight: 500; }
.wftr-back {
  margin-left: auto;
  padding: 2px 8px;
  border: none;
  background: transparent;
  color: var(--brand-ink, var(--brand, #4f46e5));
  font-size: var(--fs-xs, 11.5px);
  cursor: pointer;
  border-radius: var(--r-sm, 6px);
}
.wftr-back:hover { background: var(--brand-soft, rgba(79, 110, 247, 0.10)); }
.wftr-hit {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 1px;
  width: 100%;
  padding: 5px 8px;
  border: none;
  background: transparent;
  border-radius: var(--r-sm, 6px);
  cursor: pointer;
  text-align: left;
}
.wftr-hit:hover { background: var(--bg-hover, rgba(0, 0, 0, 0.04)); }
.wftr-loc {
  font-size: var(--fs-xs, 12px);
  font-weight: 600;
  color: var(--fg, #222);
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wftr-ln { color: var(--brand-ink, var(--brand, #4f46e5)); font-weight: 500; }
.wftr-text {
  font-family: var(--font-mono, monospace);
  font-size: 11.5px;
  color: var(--fg-dim, #666);
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ── 本轮改动分组 ── */
.wft-changes {
  flex: none;
  margin: 0 8px 8px;
  padding: 3px 0 8px;
  border-bottom: 1px solid var(--line, rgba(0, 0, 0, 0.07));
  max-height: 40%;
  overflow: auto;
}
.wftc-head {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  min-height: 28px;
  padding: 0;
}
.wftc-toggle {
  display: flex;
  align-items: center;
  gap: 5px;
  flex: 1;
  min-width: 0;
  min-height: 28px;
  padding: 5px 6px;
  border: none;
  background: transparent;
  border-radius: var(--r-md, 8px);
  cursor: pointer;
  color: var(--fg, #222);
  font-size: var(--fs-sm, 13px);
  font-weight: 600;
}
.wftc-toggle:hover { background: rgba(79, 110, 247, 0.06); }
.wftc-toggle:focus { outline: none; }
.wftc-toggle:focus-visible {
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--brand, #4f6ef7) 22%, transparent);
}
.wftc-caret { flex: none; color: var(--fg-dim, #64748b); transition: transform 0.16s var(--ease, ease); }
.wftc-caret.open { transform: rotate(90deg); }
.wftc-title { flex: none; }
.wftc-count {
  flex: none;
  min-width: 17px;
  padding: 0 5px;
  border-radius: 999px;
  background: var(--brand-soft, rgba(79, 110, 247, 0.10));
  color: var(--brand-ink, var(--brand, #4f46e5));
  font-size: var(--fs-xs, 11px);
  font-weight: 600;
  text-align: center;
}
.wftc-stats { margin-left: auto; display: inline-flex; gap: 6px; font-size: var(--fs-xs, 11px); font-weight: 500; }
.wftc-accept {
  flex: none;
  min-height: 24px;
  padding: 2px 7px;
  border: 1px solid var(--line, rgba(0, 0, 0, 0.1));
  border-radius: var(--r-sm, 6px);
  background: var(--bg, #fff);
  color: var(--brand-ink, var(--brand, #4f46e5));
  font-size: var(--fs-xs, 11px);
  font-weight: 600;
  cursor: pointer;
}
.wftc-accept:hover {
  border-color: color-mix(in srgb, var(--brand, #4f6ef7) 32%, var(--line, rgba(0, 0, 0, 0.1)));
  background: var(--brand-soft, rgba(79, 110, 247, 0.10));
}
.wftc-add { color: var(--t-success, #16a34a); }
.wftc-del { color: var(--t-danger, #e5484d); }
.wftc-row {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  min-height: 27px;
  padding: 4px 8px 4px 20px;
  border: none;
  background: transparent;
  border-radius: var(--r-sm, 6px);
  cursor: pointer;
  font-size: var(--fs-sm, 13px);
  color: var(--fg-dim, #555);
  white-space: nowrap;
  position: relative;
}
.wftc-row:hover { background: var(--bg-hover, rgba(0, 0, 0, 0.04)); color: var(--fg, #222); }
.wftc-row:focus { outline: none; }
.wftc-row:focus-visible {
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--brand, #4f6ef7) 22%, transparent);
}
.wftc-row.selected {
  background: linear-gradient(
    90deg,
    color-mix(in srgb, var(--brand, #4f6ef7) 12%, transparent),
    color-mix(in srgb, var(--brand, #4f6ef7) 6%, transparent)
  );
  color: var(--brand-ink, var(--brand, #4f46e5));
}
.wftc-status {
  flex: none;
  width: 14px;
  font-family: var(--font-mono, monospace);
  font-size: 11px;
  font-weight: 700;
  text-align: center;
}
.wftc-status.st-a { color: var(--t-success, #16a34a); }
.wftc-status.st-m { color: var(--warn, #d97706); }
.wftc-status.st-d { color: var(--t-danger, #e5484d); }
.wftc-name { flex: none; overflow: hidden; text-overflow: ellipsis; max-width: 55%; }
.wftc-name.deleted { text-decoration: line-through; opacity: 0.7; }
.wftc-dir {
  flex: 0 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  direction: rtl;
  color: var(--fg-faint, #aaa);
  font-size: var(--fs-xs, 11.5px);
}
.wftc-rowstats { margin-left: auto; display: inline-flex; gap: 5px; font-size: var(--fs-xs, 11px); }
.wftc-artifacts-toggle {
  display: flex;
  align-items: center;
  gap: 5px;
  width: 100%;
  min-height: 24px;
  padding: 3px 8px 3px 20px;
  border: none;
  background: transparent;
  border-radius: var(--r-sm, 6px);
  cursor: pointer;
  font-size: var(--fs-xs, 11.5px);
  color: var(--fg-faint, #94a3b8);
}
.wftc-artifacts-toggle:hover { background: var(--bg-hover, rgba(0, 0, 0, 0.04)); color: var(--fg-dim, #666); }
.wftc-row-artifact { opacity: 0.6; }

.ws-file-tree-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 2px 8px 10px;
}
.ws-file-tree-empty {
  margin: 16px 8px;
  font-size: var(--fs-sm, 13px);
  color: var(--fg-faint, #aaa);
}
</style>
