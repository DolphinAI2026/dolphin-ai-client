/**
 * Codex 风右侧面板状态机 + 命令面板快捷键。
 *
 * 单一真相源,替换 CodingPage 旧的 codePaneOpen(bool) + wsPaneTab('files'|'run')。
 * 纯匹配函数(matchPalette / matchPanelHotkey / isEditableTarget)单独导出便于单测;
 * keydown 监听由 CodingPage 注册(它才知道 embed 模式是否该禁用)。
 */
import { ref } from 'vue'

export type CodexPanelId = 'review' | 'terminal' | 'browser' | 'files'
export type CodexCommandId = CodexPanelId | 'sidechat'

export interface CodexCommand {
  id: CodexCommandId
  label: string
  icon: string // AppIcon name
  hotkeyLabel?: string
  panel?: CodexPanelId // 命中即激活该面板;sidechat 无 panel(留桩)
}

/** 跨平台修饰键:mac ⌘ / win-linux Ctrl(对齐 RailSidebar 写法)。 */
const mod = (e: KeyboardEvent) => e.metaKey || e.ctrlKey

export const CODEX_COMMANDS: CodexCommand[] = [
  { id: 'review', label: '审查', icon: 'eye', hotkeyLabel: '⌃⇧G', panel: 'review' },
  { id: 'terminal', label: '终端', icon: 'terminal', panel: 'terminal' },
  { id: 'browser', label: '浏览器', icon: 'globe', hotkeyLabel: '⌘T', panel: 'browser' },
  { id: 'files', label: '文件', icon: 'doc', hotkeyLabel: '⌘P', panel: 'files' },
  { id: 'sidechat', label: '侧边聊天', icon: 'message', hotkeyLabel: '⌥⌘S' },
]

/** 只有 panel 字段的命令(用于右侧段控)。 */
export const CODEX_PANEL_COMMANDS = CODEX_COMMANDS.filter((c) => !!c.panel)

/** ⌘K / Ctrl K 开关命令面板(不含 shift/alt)。 */
export function matchPalette(e: KeyboardEvent): boolean {
  return mod(e) && e.key.toLowerCase() === 'k' && !e.shiftKey && !e.altKey
}

/** 直达面板快捷键 → 面板 id;不匹配返回 null。 */
export function matchPanelHotkey(e: KeyboardEvent): CodexPanelId | null {
  const k = e.key.toLowerCase()
  if (e.ctrlKey && e.shiftKey && k === 'g') return 'review'
  if (mod(e) && k === 'p' && !e.shiftKey && !e.altKey) return 'files'
  if (mod(e) && k === 't' && !e.shiftKey && !e.altKey) return 'browser'
  return null
}

/** 焦点在输入框/可编辑区时,除 ⌘K 外不抢直达键。
 *  duck-type(不用 instanceof HTMLElement):既可在无 DOM 的单测里跑,也不依赖全局。 */
export function isEditableTarget(t: EventTarget | null): boolean {
  if (!t) return false
  const el = t as { tagName?: unknown; isContentEditable?: unknown }
  const tag = typeof el.tagName === 'string' ? el.tagName.toUpperCase() : ''
  return tag === 'TEXTAREA' || tag === 'INPUT' || el.isContentEditable === true
}

export function useCodexPanels() {
  const open = ref(false) // 宿主是否展开(= 旧 codePaneOpen)
  const active = ref<CodexPanelId>('files') // 当前面板(= 旧 wsPaneTab 升级到 4 值)
  const paletteOpen = ref(false)

  function show(id: CodexPanelId) {
    active.value = id
    open.value = true
  }
  function toggleHost() {
    open.value = !open.value
  }
  function closeHost() {
    open.value = false
  }
  function togglePalette() {
    paletteOpen.value = !paletteOpen.value
  }

  return {
    open,
    active,
    paletteOpen,
    commands: CODEX_COMMANDS,
    panelCommands: CODEX_PANEL_COMMANDS,
    show,
    toggleHost,
    closeHost,
    togglePalette,
  }
}
