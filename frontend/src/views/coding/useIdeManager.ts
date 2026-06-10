/**
 * useIdeManager — 嵌入的 code-server IDE iframe 加载/重试/视图切换。
 *
 * 职责：
 * - 维护 `ideUrl`（含 cache-busting 时间戳）、`pendingIdeUrl`
 * - 30 秒加载超时、重试、错误态展示
 * - 同 URL 不重建 iframe（避免闪屏）
 * - `activeView` chat / ide 切换
 */

import { ref, nextTick, onBeforeUnmount } from 'vue'
import { useThemeStore } from '@/stores/theme'

const IDE_LOAD_TIMEOUT_MS = 45_000
const IDE_READY_POLL_MS = 500
const CROSS_ORIGIN_READY_GRACE_MS = 1500

export function useIdeManager() {
  const themeStore = useThemeStore()
  const ideUrl = ref<string | null>(null)
  const ideLoaded = ref(false)
  const ideLoadError = ref('')
  const ideLoadingText = ref('正在连接 IDE...')
  let ideLoadTimer: ReturnType<typeof setTimeout> | null = null
  let ideReadyProbeTimer: ReturnType<typeof setInterval> | null = null
  let ideReadyProbeStartedAt = 0

  const pendingIdeUrl = ref<string | null>(null)
  const activeView = ref<'chat' | 'ide'>('chat')

  function clearIdeLoadTimer() {
    if (!ideLoadTimer) return
    clearTimeout(ideLoadTimer)
    ideLoadTimer = null
  }

  function clearIdeReadyProbe() {
    if (!ideReadyProbeTimer) return
    clearInterval(ideReadyProbeTimer)
    ideReadyProbeTimer = null
  }

  function clearIdeTimers() {
    clearIdeLoadTimer()
    clearIdeReadyProbe()
  }

  /** 剥除 URL 尾部的 _t=<ts> 缓存破坏参数，返回 "base URL" 用于比较。 */
  function stripCacheParam(url: string): string {
    return url.replace(/[&?]_t=\d+$/, '')
  }

  /** 在 URL 上追加 _t=<ts> 缓存破坏参数。 */
  function appendCacheParam(base: string): string {
    return base + (base.includes('?') ? '&' : '?') + '_t=' + Date.now()
  }

  function appendThemeParams(base: string): string {
    try {
      const url = new URL(base, window.location.href)
      url.searchParams.set('vibe_ui_theme', themeStore.mode)
      url.searchParams.set('vscode_theme', themeStore.isDark ? 'Default Dark Modern' : 'Default Light Modern')
      return url.toString()
    } catch {
      const joiner = base.includes('?') ? '&' : '?'
      return `${base}${joiner}vibe_ui_theme=${themeStore.mode}`
    }
  }

  async function setIdeUrl(url: string) {
    const baseUrl = appendThemeParams(stripCacheParam(url))
    const currentBase = stripCacheParam(ideUrl.value || '')

    if (currentBase && currentBase === baseUrl) {
      // 同一个 URL — 不重建 iframe，保留 IDE 状态（Chat 历史、编辑器状态等）
      return
    }

    ideLoaded.value = false  // 显示 loading overlay
    ideLoadError.value = ''
    ideLoadingText.value = '正在连接 IDE...'
    clearIdeTimers()
    ideUrl.value = null  // 销毁旧 iframe
    await nextTick()  // 等 DOM 更新（替代硬编码 100ms 延迟）
    ideUrl.value = appendCacheParam(baseUrl)
    // 启动加载超时
    ideLoadTimer = setTimeout(() => {
      if (!ideLoaded.value) {
        ideLoadError.value = 'IDE 加载超时，请检查 code-server 是否运行或重新打开 IDE'
        clearIdeReadyProbe()
      }
    }, IDE_LOAD_TIMEOUT_MS)
    // 2秒后更新提示文字
    setTimeout(() => {
      if (!ideLoaded.value && !ideLoadError.value) {
        ideLoadingText.value = '正在加载编辑器...'
      }
    }, 2000)
  }

  function isIdeFrameReady(frame: HTMLIFrameElement): 'ready' | 'waiting' | 'inaccessible' {
    try {
      const doc = frame.contentDocument
      const text = doc?.body?.innerText || ''
      if (!doc || !doc.body) return 'waiting'
      if (text.includes('Do you trust the authors') || text.includes('Restricted Mode')) {
        return 'waiting'
      }
      if (doc.querySelector('.monaco-workbench')) return 'ready'
      if (doc.querySelector('.gettingStartedContainer')) return 'ready'
      if (doc.querySelector('.part.activitybar')) return 'ready'
      if (text.includes('睿鲸AI Coding') || text.includes('EXPLORER') || text.includes('CHAT')) {
        return 'ready'
      }
      return 'waiting'
    } catch {
      return 'inaccessible'
    }
  }

  function markIdeReady() {
    ideLoaded.value = true
    ideLoadError.value = ''
    clearIdeTimers()
  }

  function startIdeReadyProbe(frame: HTMLIFrameElement) {
    clearIdeReadyProbe()
    ideLoadingText.value = '正在启动编辑器...'
    ideReadyProbeStartedAt = Date.now()

    const probe = () => {
      if (ideLoaded.value || ideLoadError.value) {
        clearIdeReadyProbe()
        return
      }

      const state = isIdeFrameReady(frame)
      if (state === 'ready') {
        markIdeReady()
        return
      }

      if (state === 'inaccessible' && Date.now() - ideReadyProbeStartedAt > CROSS_ORIGIN_READY_GRACE_MS) {
        markIdeReady()
      }
    }

    probe()
    if (!ideLoaded.value && !ideLoadError.value) {
      ideReadyProbeTimer = setInterval(probe, IDE_READY_POLL_MS)
    }
  }

  function onIdeFrameLoad(event: Event) {
    const frame = event.target instanceof HTMLIFrameElement ? event.target : null
    if (!frame) {
      markIdeReady()
      return
    }
    startIdeReadyProbe(frame)
  }

  function onIdeFrameError() {
    ideLoadError.value = 'IDE 加载失败，code-server 可能未启动'
    clearIdeTimers()
  }

  function retryIdeLoad() {
    if (!ideUrl.value) return
    const base = stripCacheParam(ideUrl.value)
    ideLoaded.value = false
    ideLoadError.value = ''
    ideLoadingText.value = '正在重新连接...'
    clearIdeTimers()
    ideUrl.value = null
    nextTick(() => {
      ideUrl.value = appendCacheParam(base)
      ideLoadTimer = setTimeout(() => {
        if (!ideLoaded.value) {
          ideLoadError.value = '重试超时，请检查 code-server 状态或重新打开 IDE'
          clearIdeReadyProbe()
        }
      }, IDE_LOAD_TIMEOUT_MS)
    })
  }

  async function openPendingIde() {
    if (!pendingIdeUrl.value) return
    await setIdeUrl(pendingIdeUrl.value)
    pendingIdeUrl.value = null
    activeView.value = 'ide'
  }

  onBeforeUnmount(() => {
    clearIdeTimers()
  })

  return {
    // state
    ideUrl,
    ideLoaded,
    ideLoadError,
    ideLoadingText,
    pendingIdeUrl,
    activeView,
    // methods
    setIdeUrl,
    onIdeFrameLoad,
    onIdeFrameError,
    retryIdeLoad,
    openPendingIde,
  }
}
