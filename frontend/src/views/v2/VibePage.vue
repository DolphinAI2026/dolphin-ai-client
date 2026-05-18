<!-- frontend/src/views/v2/VibePage.vue -->
<!--
  Vibe Coding — VS Code Web (code-server) mockup.

  This is a HIGH-FIDELITY STATIC mockup for P2 — code-server iframe wiring
  lands in P3. Reference design: $DESIGN_SRC/page-vibe.jsx (read end-to-end).

  Layout:
    Activity bar (48px) | File tree (240px) | Editor + Terminal + Status | AI panel (320px)
  Code area is abbreviated to ~25 lines (instead of full Apps.vue) per agent brief.

  Real `/vibe-coding` page (OnlineCodingWorkspacePage) is untouched.
-->
<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import WorkbenchShell from '@/components/WorkbenchShell.vue'
import ShellTopBar from '@/components/v2/ShellTopBar.vue'

const router = useRouter()

type FileType = 'dir' | 'vue' | 'ts' | 'css' | 'json' | 'md'
interface TreeNode {
  name: string
  type: FileType
  depth: number
  open?: boolean
  modified?: boolean
  children?: TreeNode[]
}

// Realistic file tree mimicking apaas-builder-ai repo.
const TREE: TreeNode[] = [
  { name: 'frontend/', type: 'dir', open: true, depth: 0, children: [
    { name: 'src/', type: 'dir', open: true, depth: 1, children: [
      { name: 'views/', type: 'dir', open: true, depth: 2, children: [
        { name: 'Apps.vue',            type: 'vue', depth: 3, modified: true },
        { name: 'ChatPage.vue',        type: 'vue', depth: 3 },
        { name: 'CodingPage.vue',      type: 'vue', depth: 3 },
        { name: 'Landing.vue',         type: 'vue', depth: 3 },
        { name: 'MarketplacePage.vue', type: 'vue', depth: 3 },
      ]},
      { name: 'components/', type: 'dir', open: false, depth: 2 },
      { name: 'composables/', type: 'dir', open: true, depth: 2, children: [
        { name: 'useTravelForm.ts', type: 'ts', depth: 3, modified: true },
      ]},
      { name: 'styles/', type: 'dir', open: true, depth: 2, children: [
        { name: 'tokens.css',     type: 'css', depth: 3 },
        { name: 'theme-vars.css', type: 'css', depth: 3 },
      ]},
      { name: 'router/', type: 'dir', open: false, depth: 2 },
      { name: 'stores/', type: 'dir', open: false, depth: 2 },
    ]},
    { name: 'package.json',  type: 'json', depth: 1 },
    { name: 'vite.config.ts', type: 'ts',  depth: 1 },
  ]},
  { name: 'backend/',  type: 'dir', open: false, depth: 0 },
  { name: 'README.md', type: 'md',  depth: 0 },
]

// Flatten visible tree for rendering.
function flattenTree(nodes: TreeNode[]): TreeNode[] {
  const out: TreeNode[] = []
  function walk(n: TreeNode) {
    out.push(n)
    if (n.open && n.children) for (const c of n.children) walk(c)
  }
  for (const n of nodes) walk(n)
  return out
}
const visibleTree = ref<TreeNode[]>(flattenTree(TREE))

const activeFile = ref('Apps.vue')
const openTabs = ref<string[]>(['Apps.vue', 'types.ts'])
const activeActivity = ref<'explorer' | 'search' | 'git' | 'ext' | 'ai'>('explorer')
const termOpen = ref(true)
const aiOpen = ref(true)
const aiInput = ref('')

const ACTIVITY = [
  { key: 'explorer' as const, icon: 'apps',    tip: '资源管理器' },
  { key: 'search'   as const, icon: 'search',  tip: '搜索' },
  { key: 'git'      as const, icon: 'github',  tip: '源代码管理', badge: 3 },
  { key: 'ext'      as const, icon: 'store',   tip: '扩展' },
  { key: 'ai'       as const, icon: 'sparkle', tip: 'MiniMax Chat', special: true },
]

// Abbreviated Apps.vue code (~25 lines incl. diff markers + comments).
interface CodeLine { n: number; t: string; cls?: string; mark?: string }
const CODE_LINES: CodeLine[] = [
  { n: 1,  t: '<template>' },
  { n: 2,  t: '  <WorkbenchShell>' },
  { n: 3,  t: '    <div class="apps-main">' },
  { n: 4,  t: '      <!-- Filter tabs + view toggle -->', cls: 'cmt' },
  { n: 5,  t: '      <div class="filter-bar">' },
  { n: 6,  t: '        <div class="filter-tabs">' },
  { n: 7,  t: '          <button' },
  { n: 8,  t: '            v-for="tab in tabs"' },
  { n: 9,  t: '            :key="tab.value"' },
  { n: 10, t: '            :class="[' },
  { n: 11, t: "              'filter-tab',", cls: 'mod', mark: '~' },
  { n: 12, t: '              { active: activeTab.includes(tab.value) }', cls: 'add', mark: '+' },
  { n: 13, t: '            ]"' },
  { n: 14, t: '            @click="toggleTab(tab.value)"', cls: 'add', mark: '+' },
  { n: 15, t: '          >' },
  { n: 16, t: '            {{ tab.label }}' },
  { n: 17, t: '            <span class="tab-count">{{ tabCounts[tab.value] }}</span>' },
  { n: 18, t: '          </button>' },
  { n: 19, t: '        </div>' },
  { n: 20, t: '        <!-- 新增：已部署筛选 -->', cls: 'cmt add', mark: '+' },
  { n: 21, t: '        <el-checkbox v-model="onlyDeployed">仅看已部署</el-checkbox>', cls: 'add', mark: '+' },
  { n: 22, t: '      </div>' },
  { n: 23, t: '' },
  { n: 24, t: '      <!-- Content area -->', cls: 'cmt' },
  { n: 25, t: '      <div class="app-content" :class="viewMode">' },
  { n: 26, t: '        <div v-if="loading" class="empty-state">加载中...</div>' },
]

// ─── Token-based highlighter ported from $DESIGN_SRC/page-vibe.jsx ────────
// Returns an HTML string ready for v-html.
function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}
function highlightLine(t: string): string {
  if (!t) return ''
  // Comment first — wraps everything else.
  const cmt = t.match(/^(\s*)(<!--.+?-->)(.*)$/)
  if (cmt) {
    return escapeHtml(cmt[1]) + `<span class="hl-cmt">${escapeHtml(cmt[2])}</span>` + escapeHtml(cmt[3])
  }
  const out: string[] = []
  let i = 0
  while (i < t.length) {
    const rest = t.slice(i)
    const str = rest.match(/^("[^"]*"|'[^']*')/)
    if (str) { out.push(`<span class="hl-str">${escapeHtml(str[0])}</span>`); i += str[0].length; continue }
    const tag = rest.match(/^(<\/?)([A-Za-z][\w-]*)/)
    if (tag) {
      out.push(`<span class="hl-punct">${escapeHtml(tag[1])}</span><span class="hl-tag">${escapeHtml(tag[2])}</span>`)
      i += tag[0].length
      continue
    }
    const attr = rest.match(/^(\s+)([:@v]?[\w-]+)(?==)/)
    if (attr) {
      out.push(escapeHtml(attr[1]) + `<span class="hl-attr">${escapeHtml(attr[2])}</span>`)
      i += attr[0].length
      continue
    }
    const kw = rest.match(/^(v-for|v-if|v-model|v-show)\b/)
    if (kw) { out.push(`<span class="hl-key">${escapeHtml(kw[0])}</span>`); i += kw[0].length; continue }
    out.push(escapeHtml(t[i]))
    i++
  }
  return out.join('')
}

function fileTypeBadge(name: string): { type: FileType; mark: string } {
  if (name.endsWith('.vue')) return { type: 'vue',  mark: 'V' }
  if (name.endsWith('.ts'))  return { type: 'ts',   mark: 'TS' }
  if (name.endsWith('.css')) return { type: 'css',  mark: '#' }
  if (name.endsWith('.md'))  return { type: 'md',   mark: 'M' }
  if (name.endsWith('.json')) return { type: 'json', mark: '{}' }
  return { type: 'dir', mark: '' }
}

function onTreeClick(n: TreeNode): void {
  if (n.type === 'dir') {
    n.open = !n.open
    visibleTree.value = flattenTree(TREE)
    return
  }
  activeFile.value = n.name
  if (!openTabs.value.includes(n.name)) openTabs.value.push(n.name)
}

function onCloseTab(name: string, ev: Event): void {
  ev.stopPropagation()
  openTabs.value = openTabs.value.filter(t => t !== name)
  if (activeFile.value === name && openTabs.value.length > 0) {
    activeFile.value = openTabs.value[0]
  }
}

function notImpl(action: string): void {
  ElMessage.info(`${action} 即将上线`)
}

function onOpenSandbox(): void {
  router.push('/runtime')
}

// ─── Icons (subset for this page) ─────────────────────────────────────────
const ICONS: Record<string, string> = {
  apps:     '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  search:   '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  github:   '<path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.4 3.4 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.4 13.4 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22"/>',
  store:    '<path d="M3 9V6l2-3h14l2 3v3"/><path d="M21 9a3 3 0 0 1-6 0 3 3 0 0 1-6 0 3 3 0 0 1-6 0"/><path d="M4 22V11"/><path d="M20 22V11"/>',
  sparkle:  '<path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/>',
  user:     '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  gear:     '<path d="M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8 2 2 0 1 1-2.8 2.8 1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5 2 2 0 1 1-4 0 1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3 2 2 0 1 1-2.8-2.8 1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1 2 2 0 1 1 0-4 1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8 2 2 0 1 1 2.8-2.8 1.7 1.7 0 0 0 1.8.3 1.7 1.7 0 0 0 1-1.5 2 2 0 1 1 4 0 1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3 2 2 0 1 1 2.8 2.8 1.7 1.7 0 0 0-.3 1.8 1.7 1.7 0 0 0 1.5 1 2 2 0 1 1 0 4 1.7 1.7 0 0 0-1.5 1z"/>',
  plus:     '<path d="M12 5v14"/><path d="M5 12h14"/>',
  refresh:  '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
  chevronR: '<path d="m9 6 6 6-6 6"/>',
  chevronD: '<path d="m6 9 6 6 6-6"/>',
  copy:     '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>',
  cloud:    '<path d="M18 18a4 4 0 0 0 0-8 6 6 0 0 0-12 1 4 4 0 0 0 0 8z"/>',
  trash:    '<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6 7v13h12V7"/>',
  check:    '<path d="m5 13 4 4 10-10"/>',
  code:     '<path d="m8 6-6 6 6 6"/><path d="m16 6 6 6-6 6"/>',
  book:     '<path d="M4 5a2 2 0 0 1 2-2h13v18H6a2 2 0 0 1 0-4h13"/><path d="M9 7h6"/>',
  send:     '<path d="m3 11 18-8-8 18-2-8z"/>',
}
function renderIcon(name: string, size = 16): string {
  const inner = ICONS[name] || ''
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`
}
</script>

<template>
  <WorkbenchShell>
    <ShellTopBar />
    <div class="vibe-page">
      <!-- ───────── Activity bar (slim left) ───────── -->
      <div class="vibe-activity">
        <button
          v-for="a in ACTIVITY"
          :key="a.key"
          :class="['vibe-activity-btn', { active: activeActivity === a.key, 'is-ai': a.special }]"
          :title="a.tip"
          @click="activeActivity = a.key; if (a.key === 'ai') aiOpen = true"
        >
          <span class="icon" v-html="renderIcon(a.icon, 18)" />
          <span v-if="a.badge" class="vibe-activity-badge">{{ a.badge }}</span>
        </button>
        <div style="flex: 1;" />
        <button class="vibe-activity-btn" title="账户" @click="notImpl('账户')">
          <span class="icon" v-html="renderIcon('user', 18)" />
        </button>
        <button class="vibe-activity-btn" title="设置" @click="notImpl('设置')">
          <span class="icon" v-html="renderIcon('gear', 18)" />
        </button>
      </div>

      <!-- ───────── File tree ───────── -->
      <aside class="vibe-tree">
        <div class="vibe-tree-head">
          <span class="vibe-tree-title">资源管理器</span>
          <div style="margin-left: auto; display: flex; gap: 2px;">
            <button class="icon-btn" style="width: 22px; height: 22px;" title="新建文件" @click="notImpl('新建文件')">
              <span class="icon" v-html="renderIcon('plus', 12)" />
            </button>
            <button class="icon-btn" style="width: 22px; height: 22px;" title="刷新" @click="notImpl('刷新')">
              <span class="icon" v-html="renderIcon('refresh', 12)" />
            </button>
          </div>
        </div>
        <div class="vibe-tree-project">
          <span class="icon" v-html="renderIcon('chevronD', 11)" />
          <span>APAAS-BUILDER-AI</span>
        </div>
        <div class="vibe-tree-list">
          <div
            v-for="(n, i) in visibleTree"
            :key="`${n.name}-${i}-${n.depth}`"
            :class="['vibe-tree-row', { active: activeFile === n.name, modified: n.modified }]"
            :style="{ paddingLeft: (6 + n.depth * 12) + 'px' }"
            @click="onTreeClick(n)"
          >
            <span v-if="n.type === 'dir'" class="vibe-tree-chev icon" v-html="renderIcon(n.open ? 'chevronD' : 'chevronR', 11)" />
            <span v-else style="width: 11px;" />
            <span
              :class="['coding-file-icon', `coding-file-${fileTypeBadge(n.name).type === 'dir' ? 'dir' : fileTypeBadge(n.name).type}`]"
            >
              {{ fileTypeBadge(n.name).mark }}
            </span>
            <span class="vibe-tree-name">{{ n.name }}</span>
            <span v-if="n.modified" class="vibe-tree-dot" title="已修改">M</span>
          </div>
        </div>
        <div class="vibe-tree-foot">
          <div class="vibe-outline">
            <div class="vibe-outline-head">大纲</div>
            <div v-for="o in ['template', 'script setup', '  tabs', '  activeTab', '  toggleTab', 'style scoped']" :key="o" class="vibe-outline-item">
              <span class="icon" v-html="renderIcon('code', 10)" />
              <span>{{ o.trim() }}</span>
            </div>
          </div>
        </div>
      </aside>

      <!-- ───────── Editor + Terminal + Status ───────── -->
      <div class="vibe-main">
        <!-- Tabs -->
        <div class="vibe-tabs">
          <button
            v-for="t in openTabs"
            :key="t"
            :class="['vibe-tab', { active: activeFile === t }]"
            @click="activeFile = t"
          >
            <span :class="['coding-file-icon', `coding-file-${fileTypeBadge(t).type}`]">{{ fileTypeBadge(t).mark }}</span>
            <span>{{ t }}</span>
            <span v-if="t === 'Apps.vue'" class="vibe-tab-dot">●</span>
            <button class="vibe-tab-close" @click="onCloseTab(t, $event)">×</button>
          </button>
          <div style="flex: 1;" />
          <button class="icon-btn" style="width: 26px; height: 26px;" title="拆分编辑器" @click="notImpl('拆分编辑器')">
            <span class="icon" v-html="renderIcon('copy', 13)" />
          </button>
        </div>

        <!-- Breadcrumb -->
        <div class="vibe-breadcrumb">
          <span>frontend</span><span class="icon" v-html="renderIcon('chevronR', 10)" />
          <span>src</span><span class="icon" v-html="renderIcon('chevronR', 10)" />
          <span>views</span><span class="icon" v-html="renderIcon('chevronR', 10)" />
          <span style="color: var(--text);">{{ activeFile }}</span>
          <div style="margin-left: auto; display: flex; align-items: center; gap: 6px;">
            <button class="vibe-sbx-chip" @click="onOpenSandbox" title="查看沙箱详情">
              <span class="icon" v-html="renderIcon('cloud', 11)" />
              <span><b>sbx-2b1c</b> · 4C/8G · 剩余 47m</span>
            </button>
            <span style="color: var(--text-3); font-size: 11px;">UTF-8 · LF · Vue</span>
          </div>
        </div>

        <!-- Editor -->
        <div class="vibe-editor">
          <pre class="vibe-code">
            <div
              v-for="l in CODE_LINES"
              :key="l.n"
              :class="['vibe-code-line', l.cls]"
            ><span class="vibe-gutter">{{ l.n }}</span><span class="vibe-mark">{{ l.mark || '' }}</span><span class="vibe-line-text" v-html="highlightLine(l.t)" /></div>
            <div class="vibe-cursor-line"><span class="vibe-gutter">27</span><span class="vibe-mark"></span><span class="vibe-line-text" style="position: relative;"><span class="vibe-cursor" /></span></div>
          </pre>

          <!-- Minimap (decorative) -->
          <div class="vibe-minimap" aria-hidden="true">
            <div
              v-for="(l, i) in CODE_LINES"
              :key="i"
              class="vibe-minimap-line"
              :style="{ width: Math.min(40, Math.max(4, l.t.length * 0.8)) + 'px' }"
            />
          </div>
        </div>

        <!-- Terminal -->
        <div v-if="termOpen" class="vibe-term">
          <div class="vibe-term-head">
            <div class="vibe-term-tabs">
              <button class="vibe-term-tab active">npm run dev</button>
              <button class="vibe-term-tab" @click="notImpl('git terminal')">git</button>
              <button class="vibe-term-tab" @click="notImpl('新建终端')">+</button>
            </div>
            <div style="margin-left: auto; display: flex; gap: 2px;">
              <button class="icon-btn" style="width: 24px; height: 24px;" title="清空" @click="notImpl('清空终端')">
                <span class="icon" v-html="renderIcon('trash', 12)" />
              </button>
              <button class="icon-btn" style="width: 24px; height: 24px;" title="关闭" @click="termOpen = false">
                <span class="icon" v-html="renderIcon('chevronD', 12)" />
              </button>
            </div>
          </div>
          <div class="vibe-term-body">
            <div class="vibe-term-line"><span class="vibe-term-prompt mono">~/apaas-builder-ai/frontend</span> <span class="mono">$ npm run dev</span></div>
            <div class="vibe-term-line mono" style="color: var(--text-3);">  VITE v5.4.2  ready in 412 ms</div>
            <div class="vibe-term-line mono">
              <span style="color: var(--brand-text);">  ➜ </span><span> Local:   </span><span style="color: var(--ai-text, var(--sky));">http://localhost:5173/</span>
            </div>
            <div class="vibe-term-line mono">
              <span style="color: var(--brand-text);">  ➜ </span><span> Network: use --host to expose</span>
            </div>
            <div class="vibe-term-line mono" style="color: var(--emerald);">  [HMR] update Apps.vue · 12:48:22</div>
            <div class="vibe-term-line">
              <span class="vibe-term-prompt mono">~/apaas-builder-ai/frontend</span>
              <span class="mono">$ </span>
              <span class="vibe-term-spinner" />
            </div>
          </div>
        </div>

        <!-- Status bar -->
        <div class="vibe-statusbar">
          <span class="vibe-statusbar-item vibe-statusbar-brand">
            <span class="icon" v-html="renderIcon('github', 11)" /> main ↑1
          </span>
          <span class="vibe-statusbar-item">
            <span class="icon" v-html="renderIcon('check', 11)" /> 0 errors 2 warnings
          </span>
          <span class="vibe-statusbar-item">27:1</span>
          <div style="flex: 1;" />
          <span class="vibe-statusbar-item">UTF-8</span>
          <span class="vibe-statusbar-item">LF</span>
          <span class="vibe-statusbar-item vibe-statusbar-ai" @click="aiOpen = !aiOpen">
            <span class="icon" v-html="renderIcon('sparkle', 11)" /> MiniMax Chat 已就绪
          </span>
        </div>
      </div>

      <!-- ───────── AI side panel (MiniMax Chat) ───────── -->
      <aside v-if="aiOpen" class="vibe-ai">
        <div class="vibe-ai-head">
          <span class="icon" style="color: var(--ai-text, var(--sky));" v-html="renderIcon('sparkle', 14)" />
          <span style="font-size: 13px; font-weight: 600;">MiniMax Chat</span>
          <span class="badge badge-outline" style="margin-left: 4px;">本工程</span>
          <div style="margin-left: auto; display: flex; gap: 2px;">
            <button class="icon-btn" style="width: 24px; height: 24px;" title="历史" @click="notImpl('历史')">
              <span class="icon" v-html="renderIcon('book', 12)" />
            </button>
            <button class="icon-btn" style="width: 24px; height: 24px;" title="新会话" @click="notImpl('新会话')">
              <span class="icon" v-html="renderIcon('plus', 12)" />
            </button>
            <button class="icon-btn" style="width: 24px; height: 24px;" title="关闭" @click="aiOpen = false">
              <span class="icon" v-html="renderIcon('chevronR', 12)" />
            </button>
          </div>
        </div>

        <div class="vibe-ai-thread">
          <div class="vibe-ai-msg vibe-ai-msg-user">
            <div class="vibe-ai-bubble">
              把 Apps.vue 的筛选 tab 改成多选，加一个"已部署"筛项。
              <div class="vibe-ai-attach">
                <span class="icon" v-html="renderIcon('code', 10)" /> <span class="mono">Apps.vue · 12-26 行</span>
              </div>
            </div>
          </div>
          <div class="vibe-ai-msg vibe-ai-msg-ai">
            <div class="vibe-ai-bubble">
              好。改动分三步：<br />
              <b>1.</b> 把 <code class="mono">activeTab</code> 从 <code class="mono">String</code> 改成 <code class="mono">String[]</code><br />
              <b>2.</b> tab 点击逻辑改成 toggle<br />
              <b>3.</b> 新增 <code class="mono">onlyDeployed</code> 状态 + 复选框<br />
              我已经把变更写到编辑器里了，你可以审阅一下：
            </div>
            <div class="vibe-ai-applied">
              <span class="icon" v-html="renderIcon('check', 11)" />
              <span>已修改 <code class="mono">Apps.vue</code> · +4 / -2</span>
              <button class="vibe-ai-apply-btn" @click="notImpl('查看 diff')">查看 diff</button>
            </div>
            <div class="vibe-ai-applied">
              <span class="icon" v-html="renderIcon('check', 11)" />
              <span>已修改 <code class="mono">useAppsFilter.ts</code> · +12 / -3</span>
              <button class="vibe-ai-apply-btn" @click="notImpl('查看 diff')">查看 diff</button>
            </div>
          </div>
          <div class="vibe-ai-msg vibe-ai-msg-user">
            <div class="vibe-ai-bubble">tab-count 还是旧的，能同步过滤吗？</div>
          </div>
          <div class="vibe-ai-msg vibe-ai-msg-ai">
            <div class="vibe-ai-bubble">
              <div class="typing-dots"><span /><span /><span /></div>
            </div>
          </div>
        </div>

        <div class="vibe-ai-context">
          <span class="vibe-ai-context-label">上下文</span>
          <span class="vibe-ai-context-chip">
            <span class="icon" v-html="renderIcon('code', 10)" /> Apps.vue
          </span>
          <span class="vibe-ai-context-chip">
            <span class="icon" v-html="renderIcon('code', 10)" /> useAppsFilter.ts
          </span>
          <button class="vibe-ai-context-add" @click="notImpl('添加文件')">+ 添加文件</button>
        </div>

        <div class="vibe-ai-composer">
          <textarea
            v-model="aiInput"
            class="vibe-ai-input"
            placeholder="选中代码后按 ⌘L 唤起对话；或在这里继续提问…"
            rows="2"
          />
          <div class="vibe-ai-foot">
            <div style="display: flex; gap: 4px;">
              <button class="vibe-ai-mode active">代理模式</button>
              <button class="vibe-ai-mode">询问模式</button>
            </div>
            <button class="btn btn-primary btn-sm" :disabled="!aiInput.trim()" @click="notImpl('发送')">
              发送 <span class="icon" v-html="renderIcon('send', 11)" />
            </button>
          </div>
        </div>
      </aside>
    </div>
  </WorkbenchShell>
</template>

<style scoped>
/* ═══════════════════════════════════════════════════════════════
   Vibe Coding — VS Code-like full IDE mockup (P2)
   Layout: 48px activity | 240px tree | flex editor | 320px AI panel
   ═══════════════════════════════════════════════════════════════ */
.vibe-page {
  display: grid;
  grid-template-columns: 48px 240px 1fr 320px;
  height: 100%;
  min-height: 0;
  flex: 1;
  background: var(--surface);
  --vibe-bg: var(--surface);
  --vibe-bg-2: var(--surface-2);
  --vibe-bg-3: var(--surface-3);
  --vibe-line: var(--border);
}
@media (max-width: 1280px) {
  .vibe-page { grid-template-columns: 48px 220px 1fr 300px; }
}

/* ── Activity bar ── */
.vibe-activity {
  background: var(--vibe-bg-3);
  border-right: 1px solid var(--vibe-line);
  display: flex; flex-direction: column;
  padding: 8px 0; gap: 2px;
}
.vibe-activity-btn {
  width: 48px; height: 40px;
  border: none; background: transparent;
  display: grid; place-items: center;
  cursor: pointer; color: var(--text-3);
  position: relative; transition: color 0.12s;
}
.vibe-activity-btn .icon :deep(svg) { display: block; }
.vibe-activity-btn:hover { color: var(--text); }
.vibe-activity-btn.active {
  color: var(--text);
  box-shadow: inset 2px 0 0 var(--brand);
}
.vibe-activity-btn.is-ai { color: var(--ai-text, var(--sky)); }
.vibe-activity-btn.is-ai.active { color: var(--ai, var(--sky)); }
.vibe-activity-badge {
  position: absolute; top: 6px; right: 6px;
  background: var(--brand); color: #fff;
  font-size: 9px; font-weight: 700;
  padding: 1px 5px; border-radius: 999px;
  min-width: 16px; text-align: center;
}

/* ── File tree ── */
.vibe-tree {
  background: var(--vibe-bg-2);
  border-right: 1px solid var(--vibe-line);
  display: flex; flex-direction: column;
  min-height: 0; min-width: 0;
}
.vibe-tree-head {
  display: flex; align-items: center;
  padding: 8px 12px; height: 32px;
}
.vibe-tree-title {
  font-size: 10.5px; font-weight: 600;
  letter-spacing: 0.10em; text-transform: uppercase;
  color: var(--text-3);
}
.vibe-tree-project {
  display: flex; align-items: center; gap: 4px;
  padding: 4px 12px;
  font-size: 11px; font-weight: 600; letter-spacing: 0.04em;
  color: var(--text-2);
  background: var(--vibe-bg-3);
}
.vibe-tree-project .icon :deep(svg) { color: var(--text-3); display: block; }
.vibe-tree-list {
  flex: 1; overflow-y: auto;
  padding: 4px 0 8px; min-height: 0;
}
.vibe-tree-row {
  display: flex; align-items: center; gap: 4px;
  padding: 3px 8px 3px 6px;
  cursor: pointer;
  font-size: 12.5px; color: var(--text-2);
  transition: background 0.10s;
  height: 22px;
  white-space: nowrap;
}
.vibe-tree-row .icon :deep(svg) { display: block; }
.vibe-tree-row:hover { background: var(--vibe-bg-3); color: var(--text); }
.vibe-tree-row.active {
  background: var(--brand-soft);
  color: var(--brand-text);
}
.vibe-tree-row.modified .vibe-tree-name { color: var(--amber); }
.vibe-tree-chev { color: var(--text-3); }
.vibe-tree-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.vibe-tree-dot {
  font-size: 10px; font-weight: 700;
  font-family: var(--d-font-mono, ui-monospace, monospace);
  color: var(--amber);
}
.vibe-tree-foot { border-top: 1px solid var(--vibe-line); padding: 8px 0; }
.vibe-outline { padding: 0 12px; }
.vibe-outline-head {
  font-size: 10.5px; font-weight: 600;
  letter-spacing: 0.10em; text-transform: uppercase;
  color: var(--text-3); margin-bottom: 4px;
}
.vibe-outline-item {
  display: flex; align-items: center; gap: 6px;
  padding: 2px 4px;
  font-size: 11.5px; color: var(--text-2);
}
.vibe-outline-item .icon :deep(svg) { color: var(--brand-text); display: block; }

/* File-type icon badges (vue/ts/css/...). */
.coding-file-icon {
  display: inline-grid; place-items: center;
  width: 16px; height: 16px;
  font-size: 9px; font-weight: 700;
  border-radius: 3px; flex-shrink: 0;
  color: #fff; background: var(--text-4);
  font-family: var(--d-font-mono, ui-monospace, monospace);
}
.coding-file-vue  { background: #41B883; }
.coding-file-ts   { background: #3178C6; }
.coding-file-css  { background: #2965F1; }
.coding-file-json { background: #888; color: #fff; }
.coding-file-md   { background: #6E7681; }
.coding-file-dir  { background: transparent; color: var(--text-3); }

/* ── Main editor area ── */
.vibe-main {
  display: grid;
  grid-template-rows: 34px 26px 1fr auto 22px;
  min-width: 0; min-height: 0;
  background: var(--vibe-bg);
}

/* Tabs */
.vibe-tabs {
  display: flex; align-items: stretch;
  background: var(--vibe-bg-2);
  border-bottom: 1px solid var(--vibe-line);
  padding-left: 2px;
}
.vibe-tab {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 0 10px;
  background: transparent; border: none;
  border-right: 1px solid var(--vibe-line);
  font-size: 12px; color: var(--text-3);
  cursor: pointer; font-family: inherit;
  position: relative;
}
.vibe-tab:hover { color: var(--text-2); }
.vibe-tab.active {
  background: var(--vibe-bg);
  color: var(--text);
}
.vibe-tab.active::after {
  content: ''; position: absolute;
  top: 0; left: 0; right: 0;
  height: 2px; background: var(--brand);
}
.vibe-tab-dot { font-size: 9px; color: var(--amber); }
.vibe-tab-close {
  width: 16px; height: 16px;
  background: transparent; border: none;
  cursor: pointer; color: var(--text-3);
  font-size: 14px; line-height: 1;
  border-radius: 3px;
  display: grid; place-items: center;
  padding: 0; margin-left: 2px;
}
.vibe-tab-close:hover { background: var(--vibe-bg-3); color: var(--text); }

/* Breadcrumb */
.vibe-breadcrumb {
  display: flex; align-items: center; gap: 4px;
  padding: 0 12px;
  background: var(--vibe-bg);
  border-bottom: 1px solid var(--vibe-line);
  font-size: 11.5px; color: var(--text-3);
}
.vibe-breadcrumb .icon :deep(svg) { color: var(--text-4); display: block; }

/* Editor */
.vibe-editor {
  display: flex;
  background: var(--vibe-bg);
  overflow: hidden;
  position: relative;
  min-height: 0;
}
.vibe-code {
  flex: 1; margin: 0; padding: 8px 0;
  font-family: var(--d-font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);
  font-size: 12.5px; line-height: 1.65;
  color: var(--text);
  overflow: auto;
  white-space: pre;
}
.vibe-code-line {
  display: flex; align-items: stretch;
  padding: 0; min-height: 20px;
  position: relative;
}
.vibe-code-line.add { background: rgba(16, 163, 127, 0.10); }
.vibe-code-line.mod { background: rgba(217, 119, 6, 0.08); }
.vibe-code-line.cmt .vibe-line-text { color: var(--text-3); font-style: italic; }
.vibe-cursor-line { display: flex; align-items: stretch; min-height: 20px; }
.vibe-gutter {
  width: 40px; text-align: right;
  padding-right: 10px;
  color: var(--text-4);
  font-size: 11.5px; user-select: none;
  flex-shrink: 0;
}
.vibe-code-line.add .vibe-gutter,
.vibe-code-line.mod .vibe-gutter { color: var(--text-2); }
.vibe-mark {
  width: 14px; font-weight: 700;
  text-align: center; flex-shrink: 0;
}
.vibe-code-line.add .vibe-mark { color: var(--emerald); }
.vibe-code-line.mod .vibe-mark { color: var(--amber); }
.vibe-line-text { padding: 0 12px; font-size: 12.5px; }
.vibe-cursor {
  position: absolute;
  width: 1.5px; height: 16px;
  background: var(--brand);
  animation: vibeCursor 1s steps(2) infinite;
}
@keyframes vibeCursor { 50% { opacity: 0; } }

/* Syntax tokens — light/dark via brand palette. */
.vibe-code :deep(.hl-tag)   { color: #800080; }
.vibe-code :deep(.hl-attr)  { color: #1E40AF; }
.vibe-code :deep(.hl-str)   { color: #B91C1C; }
.vibe-code :deep(.hl-cmt)   { color: var(--text-3); font-style: italic; }
.vibe-code :deep(.hl-key)   { color: #1D4ED8; }
.vibe-code :deep(.hl-punct) { color: var(--text-3); }

/* Minimap */
.vibe-minimap {
  width: 60px; flex-shrink: 0;
  border-left: 1px solid var(--vibe-line);
  background: var(--vibe-bg-2);
  padding: 8px 4px;
  display: flex; flex-direction: column; gap: 1px;
  overflow: hidden;
}
.vibe-minimap-line {
  height: 2px;
  background: var(--text-4);
  opacity: 0.4;
  border-radius: 1px;
}

/* Terminal */
.vibe-term {
  background: var(--vibe-bg-2);
  border-top: 1px solid var(--vibe-line);
  display: flex; flex-direction: column;
  max-height: 180px;
}
.vibe-term-head {
  display: flex; align-items: center;
  height: 28px;
  border-bottom: 1px solid var(--vibe-line);
  padding: 0 4px;
}
.vibe-term-tabs { display: flex; }
.vibe-term-tab {
  height: 28px; padding: 0 12px;
  background: transparent; border: none;
  border-right: 1px solid var(--vibe-line);
  font-size: 11.5px; color: var(--text-3);
  cursor: pointer; font-family: inherit;
}
.vibe-term-tab.active { color: var(--text); background: var(--vibe-bg); }
.vibe-term-body {
  flex: 1; overflow-y: auto;
  padding: 6px 12px;
  font-family: var(--d-font-mono, ui-monospace, monospace);
  font-size: 11.5px; line-height: 1.65;
  color: var(--text-2);
}
.vibe-term-line { white-space: pre; }
.vibe-term-prompt { color: var(--brand-text); font-weight: 500; }
.vibe-term-spinner {
  display: inline-block;
  width: 10px; height: 10px;
  margin-left: 4px; vertical-align: -1px;
  border: 2px solid var(--brand);
  border-top-color: transparent;
  border-radius: 50%;
  animation: vibeSpin 0.8s linear infinite;
}
@keyframes vibeSpin { to { transform: rotate(360deg); } }

/* Status bar (bottom) */
.vibe-statusbar {
  display: flex; align-items: center; gap: 0;
  height: 22px;
  background: var(--brand-700, var(--brand));
  color: rgba(255, 255, 255, 0.85);
  font-size: 11px;
  padding: 0 4px;
}
.vibe-statusbar-item {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 0 8px; height: 100%;
  cursor: pointer;
}
.vibe-statusbar-item .icon :deep(svg) { color: rgba(255, 255, 255, 0.85); display: block; }
.vibe-statusbar-item:hover { background: rgba(255, 255, 255, 0.10); }
.vibe-statusbar-brand { background: rgba(255, 255, 255, 0.10); }
.vibe-statusbar-ai    { background: rgba(91, 187, 215, 0.30); }
.vibe-statusbar-ai .icon :deep(svg) { color: #fff; }

/* ── AI side panel ── */
.vibe-ai {
  background: var(--vibe-bg-2);
  border-left: 1px solid var(--vibe-line);
  display: flex; flex-direction: column;
  min-height: 0; min-width: 0;
}
.vibe-ai-head {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 12px;
  height: 40px;
  border-bottom: 1px solid var(--vibe-line);
  background: var(--vibe-bg-3);
}
.vibe-ai-head .icon :deep(svg) { display: block; }
.vibe-ai-thread {
  flex: 1; overflow-y: auto;
  padding: 14px;
  display: flex; flex-direction: column; gap: 14px;
  min-height: 0;
}
.vibe-ai-msg { display: flex; flex-direction: column; gap: 4px; }
.vibe-ai-msg-user { align-items: flex-end; }
.vibe-ai-bubble {
  max-width: 88%;
  padding: 9px 12px;
  border-radius: 11px;
  font-size: 12.5px; line-height: 1.55;
  color: var(--text);
  background: var(--vibe-bg);
  border: 1px solid var(--vibe-line);
}
.vibe-ai-bubble code {
  background: var(--surface-3, #f3f3f3);
  color: var(--text);
  padding: 0 5px; border-radius: 3px;
  font-size: 11.5px;
}
.vibe-ai-msg-user .vibe-ai-bubble {
  background: var(--ai-soft, var(--sky-bg));
  border-color: var(--ai-soft-2, var(--sky-bg));
  color: var(--text);
}
.vibe-ai-attach {
  display: inline-flex; align-items: center; gap: 4px;
  margin-top: 6px;
  padding: 2px 7px;
  background: var(--vibe-bg-3);
  border-radius: 5px;
  font-size: 11px;
  color: var(--text-3);
}
.vibe-ai-attach .icon :deep(svg) { display: block; }
.vibe-ai-applied {
  display: flex; align-items: center; gap: 6px;
  padding: 6px 10px;
  background: var(--emerald-bg);
  border: 1px solid rgba(16, 163, 127, 0.20);
  border-radius: 8px;
  font-size: 11.5px; color: var(--text-2);
  max-width: 88%;
}
.vibe-ai-applied .icon :deep(svg) { color: var(--emerald); display: block; }
.vibe-ai-apply-btn {
  margin-left: auto;
  border: none; background: transparent;
  color: var(--brand-text); cursor: pointer;
  font-size: 11px; font-weight: 500; font-family: inherit;
}

.vibe-ai-context {
  display: flex; align-items: center; gap: 4px;
  padding: 8px 14px;
  border-top: 1px solid var(--vibe-line);
  background: var(--vibe-bg-3);
  flex-wrap: wrap;
}
.vibe-ai-context-label {
  font-size: 10.5px; font-weight: 600;
  letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--text-3);
}
.vibe-ai-context-chip {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 2px 7px;
  background: var(--vibe-bg);
  border: 1px solid var(--vibe-line);
  border-radius: 5px;
  font-size: 11px;
  color: var(--text-2);
}
.vibe-ai-context-chip .icon :deep(svg) { color: var(--brand-text); display: block; }
.vibe-ai-context-add {
  border: 1px dashed var(--border-strong);
  background: transparent;
  border-radius: 5px;
  padding: 2px 7px;
  font-size: 11px;
  color: var(--text-3); cursor: pointer; font-family: inherit;
}

.vibe-ai-composer { padding: 10px 12px 12px; border-top: 1px solid var(--vibe-line); }
.vibe-ai-input {
  width: 100%;
  border: 1px solid var(--vibe-line);
  background: var(--vibe-bg);
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 12.5px; font-family: inherit;
  color: var(--text);
  resize: none; outline: none;
  line-height: 1.55;
  box-sizing: border-box;
}
.vibe-ai-input:focus {
  border-color: var(--ai, var(--brand));
  box-shadow: 0 0 0 3px var(--ai-ring, var(--brand-ring));
}
.vibe-ai-input::placeholder { color: var(--text-3); }
.vibe-ai-foot {
  display: flex; justify-content: space-between; align-items: center;
  margin-top: 6px;
}
.vibe-ai-mode {
  padding: 4px 9px;
  border: 1px solid var(--vibe-line);
  background: var(--vibe-bg);
  border-radius: 6px;
  font-size: 11px;
  color: var(--text-3); cursor: pointer; font-family: inherit;
}
.vibe-ai-mode.active {
  background: var(--ai-soft, var(--sky-bg));
  border-color: var(--ai-soft-2, var(--sky-bg));
  color: var(--ai-text, var(--sky));
  font-weight: 500;
}

/* Sandbox chip in breadcrumb (deeplinks /runtime) */
.vibe-sbx-chip {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 2px 8px;
  background: var(--brand-soft);
  border: 1px solid var(--brand-soft-2, var(--brand-soft));
  border-radius: 5px;
  color: var(--brand-text);
  font-size: 11px; cursor: pointer; font-family: inherit;
}
.vibe-sbx-chip .icon :deep(svg) { color: var(--brand-text); display: block; }
.vibe-sbx-chip:hover { background: var(--brand-soft-2, var(--brand-soft)); }
.vibe-sbx-chip b {
  font-family: var(--d-font-mono, ui-monospace, monospace);
  font-weight: 600;
}

/* Buttons shared */
.btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  height: 32px; padding: 0 14px; border-radius: 8px;
  font-size: 13px; font-weight: 500; cursor: pointer;
  border: 1px solid transparent; background: transparent; color: var(--text); font-family: inherit;
  white-space: nowrap; transition: background 0.12s, border-color 0.12s, box-shadow 0.12s;
}
.btn-sm { height: 26px; padding: 0 10px; font-size: 12px; border-radius: 6px; }
.btn-primary { background: var(--brand); color: #fff; }
.btn-primary:hover { background: var(--brand-hover); }
.btn-primary:disabled { background: var(--surface-3); color: var(--text-3); cursor: not-allowed; }
.btn .icon { display: inline-flex; align-items: center; }
.btn .icon :deep(svg) { display: block; }

.icon-btn {
  display: inline-grid; place-items: center; width: 24px; height: 24px;
  border-radius: 6px; border: 1px solid transparent; background: transparent;
  color: var(--text-3); cursor: pointer; transition: background 0.14s, color 0.14s;
}
.icon-btn:hover { background: var(--vibe-bg-3); color: var(--text); }
.icon-btn .icon :deep(svg) { display: block; }

.badge {
  display: inline-flex; align-items: center; gap: 4px;
  height: 18px; padding: 0 6px; border-radius: 4px;
  font-size: 10.5px; font-weight: 500;
  background: var(--surface-3); color: var(--text-3);
  border: 1px solid var(--border);
}
.badge-outline { background: transparent; color: var(--text-3); }

.typing-dots {
  display: flex; align-items: center;
  gap: 4px; padding: 4px 0;
}
.typing-dots span {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--text-3);
  animation: typing 1.2s infinite;
}
.typing-dots span:nth-child(2) { animation-delay: 0.15s; }
.typing-dots span:nth-child(3) { animation-delay: 0.30s; }
@keyframes typing {
  0%, 60%, 100% { opacity: 0.3; transform: translateY(0); }
  30%           { opacity: 1;   transform: translateY(-3px); }
}

.mono { font-family: var(--d-font-mono, ui-monospace, SFMono-Regular, Menlo, monospace); }
</style>
