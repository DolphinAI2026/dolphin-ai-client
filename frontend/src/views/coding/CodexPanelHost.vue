<template>
  <!-- Codex 面板宿主(可复用): 段控顶栏 + 4 个单面板(审查/终端/浏览器/文件)。
       外栏宽度 + 左缘 resizer + ⌘K 命令面板由宿主页(CodingPage / AIChatPage)控;
       本组件只负责段控切换 + 4 面板渲染 + 文件面板内 树/查看器横排 + 树拖宽 handle。
       根 class 带 codex-skin → 自带 --cx-* 变量(不依赖外层祖先),两页复用一致。 -->
  <div class="codex-panel-host codex-skin">
    <div class="cph-topbar">
      <div class="cph-segments">
        <button
          v-for="c in panelCommands"
          :key="c.id"
          class="cph-seg"
          :class="{ active: activePanel === c.id }"
          :title="c.label"
          @click="emit('update:activePanel', c.id as CodexPanelId)"
        >
          <AppIcon :name="c.icon" :size="14" />
          <span class="cph-seg-label">{{ c.label }}</span>
        </button>
      </div>
      <div class="cph-topbar-actions">
        <button class="cph-icon-btn" title="命令面板 ⌘K" @click="emit('open-palette')">
          <AppIcon name="more" :size="15" />
        </button>
        <button class="cph-icon-btn" title="收起代码栏" @click="emit('update:open', false)">
          <AppIcon name="x" :size="15" />
        </button>
      </div>
    </div>

    <ReviewPanel
      v-show="activePanel === 'review'"
      class="cph-body-panel"
      :changes="changes"
      :selected="selectedFile"
      :accepting="acceptingChanges"
      @select-file="(p: string) => emit('select-file', p)"
      @accept-all="emit('accept-all')"
    />

    <TerminalPanel
      v-show="activePanel === 'terminal'"
      class="cph-body-panel"
      :ws-id="wsId"
      @server-detected="(p: { url: string; port: number }) => emit('server-detected', p)"
    />

    <RunDebugPanel
      v-show="activePanel === 'browser'"
      class="cph-body-panel"
      :ws-id="wsId"
      :dark="dark"
      :active-preview="activePreview"
      @update:active-preview="v => emit('update:activePreview', v)"
    />

    <div v-show="activePanel === 'files'" class="ws-pane-files cph-body-panel">
      <FileTree
        class="ws-pane-tree"
        :style="{ width: treePaneWidth + 'px' }"
        :tree="fileTree"
        :changed="changedPaths"
        :changes="changes"
        :selected="selectedFile"
        :ws-id="wsId"
        @select="(p: string) => emit('select-tree', p)"
        @select-line="(p: { path: string; line: number }) => emit('select-tree-line', p)"
        @accept-all="emit('accept-all')"
      />
      <div class="tree-resizer" title="拖拽调整文件树宽度" @pointerdown="(e: PointerEvent) => emit('tree-resize-start', e)" />
      <CodeViewer
        class="ws-pane-viewer"
        :ws-id="wsId"
        :file-path="selectedFile"
        :diff="selectedGitChange ? null : selectedDiff"
        :change="selectedGitChange"
        :focus-line="viewerFocusLine"
        :dark="dark"
        @quote="(q: ViewerQuote) => emit('viewer-quote', q)"
        @accept-change="(p?: string | null) => emit('accept-change', p)"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import AppIcon from '@/components/common/AppIcon.vue'
import FileTree from './FileTree.vue'
import CodeViewer from './CodeViewer.vue'
import RunDebugPanel from './RunDebugPanel.vue'
import ReviewPanel from './panels/ReviewPanel.vue'
import TerminalPanel from './panels/TerminalPanel.vue'
import type { CodexPanelId, CodexCommand } from './useCodexPanels'
import type { TreeNode } from './fileTree'
import type { FileChange } from './workspaceChanges'
import type { WorkspaceChanges, WorkspaceChangeEntry } from '@/api/coding'

// activePreview 形状与 useCodingStore.activePreview / RunDebugPanel 一致(单一真相源)。
type ActivePreview = {
  dev_url: string; status: string; errors: string[]; capture_available: boolean; round: number | null; source?: string
} | null

type ViewerQuote = { path: string; startLine: number | null; endLine: number | null; text: string }

defineProps<{
  /** WorkspaceManager slug(FileTree/Terminal/RunDebug/CodeViewer 用) */
  wsId: string
  /** 面板宿主开关(× 收起经 update:open 回写) */
  open: boolean
  /** 当前激活面板 */
  activePanel: CodexPanelId
  /** 段控命令(review/terminal/browser/files) */
  panelCommands: readonly CodexCommand[]
  /** git 基线改动(审查/文件树徽标/diff) */
  changes: WorkspaceChanges | null
  /** 当前选中文件 */
  selectedFile: string | null
  /** 接受变更进行中(禁用按钮) */
  acceptingChanges?: boolean
  /** 文件树 */
  fileTree: TreeNode[]
  /** 本轮改动路径集合(树徽标) */
  changedPaths: Set<string>
  /** 选中文件的对话流 diff(无 git 改动时 CodeViewer 用它) */
  selectedDiff: FileChange | null
  /** 选中文件的 git 基线改动(优先于 diff) */
  selectedGitChange: WorkspaceChangeEntry | null
  /** 内容搜索跳行 */
  viewerFocusLine: number | null
  /** 当前预览(RunDebugPanel) */
  activePreview: ActivePreview
  /** 文件树宽度(宿主页 usePanelResize 控) */
  treePaneWidth: number
  /** 恒暗(Code 模式 true) */
  dark?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:open', v: boolean): void
  (e: 'update:activePanel', v: CodexPanelId): void
  (e: 'open-palette'): void
  (e: 'select-file', path: string): void
  (e: 'accept-all'): void
  (e: 'select-tree', path: string): void
  (e: 'select-tree-line', payload: { path: string; line: number }): void
  (e: 'viewer-quote', q: ViewerQuote): void
  (e: 'accept-change', path?: string | null): void
  (e: 'server-detected', p: { url: string; port: number }): void
  (e: 'update:activePreview', v: ActivePreview): void
  (e: 'tree-resize-start', ev: PointerEvent): void
}>()
</script>

<style>
/* ════════════════════════════════════════════════════════════════════
   Codex 面板外壳 — 右侧单面板宿主 + 段控顶栏。
   非 scoped:从 CodingPage 抽出后两页(CodingPage / AIChatPage)复用,
   .codex-panel-host 类名唯一(全局仅本组件用),不会污染他处。
   --cx-* 由根 .codex-skin 自带(styles/codex-tokens.css)。
   ════════════════════════════════════════════════════════════════════ */
.codex-panel-host {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-height: 0;
  min-width: 0;
  background: var(--cx-bg-1);
  /* 左边界 = 原单 div 上 .codex-panel-host(--cx-border)胜出的那道(非 .ws-pane 的 --line) */
  border-left: 1px solid var(--cx-border);
}
.codex-panel-host .cph-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  height: 40px;
  padding: 0 8px 0 10px;
  border-bottom: 1px solid var(--cx-border);
  background: var(--cx-bg-0);
  flex-shrink: 0;
}
.codex-panel-host .cph-segments { display: flex; align-items: stretch; gap: 2px; height: 100%; }
.codex-panel-host .cph-seg {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--cx-text-3);
  font-size: 12.5px;
  padding: 0 10px;
  cursor: pointer;
  transition: color 0.12s, border-color 0.12s;
}
.codex-panel-host .cph-seg:hover { color: var(--cx-text-1); }
.codex-panel-host .cph-seg.active { color: var(--cx-text-1); border-bottom-color: var(--cx-brand); }
.codex-panel-host .cph-seg-label { line-height: 1; }
.codex-panel-host .cph-topbar-actions { display: inline-flex; align-items: center; gap: 2px; }
.codex-panel-host .cph-icon-btn {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  background: transparent;
  border: none;
  border-radius: 6px;
  color: var(--cx-text-2);
  cursor: pointer;
}
.codex-panel-host .cph-icon-btn:hover { background: var(--cx-bg-3); color: var(--cx-text-1); }
.codex-panel-host .cph-body-panel { flex: 1 1 auto; min-height: 0; overflow: hidden; }
/* 文件面板内部仍是 树+resizer+viewer 横排,沿用 .ws-pane-files 既有布局 */
.codex-panel-host .ws-pane-files.cph-body-panel { display: flex; }

/* 文件面板内部布局(从 CodingPage.global.css 抽出,只本区用)。
   变量引用保持原样(--line/--brand/--ease),CodingPage 暗色 Code 模式下行为字节一致;
   --cx-* 仅托底面板外壳配色,这里沿用既有主题变量不改观感。 */
.codex-panel-host .ws-pane-files { display: flex; flex: 1; min-height: 0; }
.codex-panel-host .ws-pane-tree { flex: none; border-right: 1px solid var(--line, rgba(0,0,0,.08)); }
.codex-panel-host .ws-pane-viewer { flex: 1; min-width: 0; overflow: hidden; }
/* 树右边界拖宽 handle: 骑在边框上不占布局宽度 */
.codex-panel-host .tree-resizer {
  flex: none;
  width: 7px;
  margin: 0 -3px 0 -4px;
  cursor: col-resize;
  z-index: 5;
  position: relative;
  touch-action: none;
  user-select: none;
}
.codex-panel-host .tree-resizer::after {
  content: '';
  position: absolute;
  left: 3px; top: 0; bottom: 0;
  width: 2px;
  background: transparent;
  transition: background 0.15s var(--ease, ease);
}
.codex-panel-host .tree-resizer:hover::after { background: var(--brand, #6366f1); }
</style>
