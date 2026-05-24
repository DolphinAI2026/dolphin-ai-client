// frontend/src/components/v2/config-assistant/composables/usePanelResize.ts
//
// 2026-05-24 拆 ConfigAssistantPanel.vue refactor 产物.
// 拖拽改宽度 + localStorage 持久化 hook.
//
// 改进 (vs 老 ConfigAssistantPanel.vue 用 MouseEvent):
// 学 super-agents-dev ai-assistant-sidebar.vue 改 PointerEvent + setPointerCapture
// → 鼠标松开时一定收到 pointerup, 防"拖一半 mouseup 丢失" 卡死 UI
// → 更稳, 也兼容触屏

import { ref } from 'vue'

export function usePanelResize(opts: {
  storageKey: string
  defaultWidth?: number
  minWidth?: number
  maxWidth?: number
}) {
  const { storageKey, defaultWidth = 420, minWidth = 320, maxWidth = 880 } = opts

  const panelWidth = ref<number>(
    parseInt(
      (typeof localStorage !== 'undefined' && localStorage.getItem(storageKey)) || String(defaultWidth),
      10,
    ) || defaultWidth,
  )
  const isResizing = ref(false)

  function clamp(n: number): number {
    if (n < minWidth) return minWidth
    if (n > maxWidth) return maxWidth
    return n
  }

  function persist() {
    try {
      localStorage.setItem(storageKey, String(panelWidth.value))
    } catch {
      // 私密模式 / quota — 忽略
    }
  }

  function onResizeStart(e: PointerEvent) {
    if (e.button !== 0) return // 只响应左键
    e.preventDefault()

    const target = e.currentTarget as HTMLElement
    target.setPointerCapture(e.pointerId)

    isResizing.value = true
    const startX = e.clientX
    const startWidth = panelWidth.value

    const onMove = (ev: PointerEvent) => {
      if (!isResizing.value) return
      // 拖拽 handle 在左边界, 向左拖拽 (dx 为负) = 加宽
      const dx = ev.clientX - startX
      panelWidth.value = clamp(startWidth - dx)
    }

    const onUp = (ev: PointerEvent) => {
      isResizing.value = false
      try {
        target.releasePointerCapture(ev.pointerId)
      } catch {
        /* 已释放 */
      }
      target.removeEventListener('pointermove', onMove)
      target.removeEventListener('pointerup', onUp)
      target.removeEventListener('pointercancel', onUp)
      persist()
    }

    target.addEventListener('pointermove', onMove)
    target.addEventListener('pointerup', onUp)
    target.addEventListener('pointercancel', onUp)
  }

  return { panelWidth, isResizing, onResizeStart }
}
