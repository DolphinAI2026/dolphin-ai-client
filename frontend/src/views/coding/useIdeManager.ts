/**
 * useIdeManager — 嵌入的 code-server IDE iframe 加载/重试/视图切换。
 *
 * 职责：
 * - 维护 `ideUrl`（含 cache-busting 时间戳）、`pendingIdeUrl`
 * - 30 秒加载超时、重试、错误态展示
 * - 同 URL 不重建 iframe（避免闪屏）
 * - `activeView` chat / ide 切换
 */

import { ref, nextTick } from 'vue'

export function useIdeManager() {
  const ideUrl = ref<string | null>(null)
  const ideLoaded = ref(false)
  const ideLoadError = ref('')
  const ideLoadingText = ref('正在连接 IDE...')
  let ideLoadTimer: ReturnType<typeof setTimeout> | null = null

  const pendingIdeUrl = ref<string | null>(null)
  const activeView = ref<'chat' | 'ide'>('chat')

  /** 剥除 URL 尾部的 _t=<ts> 缓存破坏参数，返回 "base URL" 用于比较。 */
  function stripCacheParam(url: string): string {
    return url.replace(/[&?]_t=\d+$/, '')
  }

  /** 在 URL 上追加 _t=<ts> 缓存破坏参数。 */
  function appendCacheParam(base: string): string {
    return base + (base.includes('?') ? '&' : '?') + '_t=' + Date.now()
  }

  async function setIdeUrl(url: string) {
    const baseUrl = stripCacheParam(url)
    const currentBase = stripCacheParam(ideUrl.value || '')

    if (currentBase && currentBase === baseUrl) {
      // 同一个 URL — 不重建 iframe，保留 IDE 状态（Chat 历史、编辑器状态等）
      return
    }

    ideLoaded.value = false  // 显示 loading overlay
    ideLoadError.value = ''
    ideLoadingText.value = '正在连接 IDE...'
    ideUrl.value = null  // 销毁旧 iframe
    await nextTick()  // 等 DOM 更新（替代硬编码 100ms 延迟）
    ideUrl.value = appendCacheParam(baseUrl)
    // 启动 30 秒加载超时
    if (ideLoadTimer) clearTimeout(ideLoadTimer)
    ideLoadTimer = setTimeout(() => {
      if (!ideLoaded.value) {
        ideLoadError.value = 'IDE 加载超时，请检查 code-server 是否运行'
      }
    }, 30_000)
    // 2秒后更新提示文字
    setTimeout(() => {
      if (!ideLoaded.value && !ideLoadError.value) {
        ideLoadingText.value = '正在加载编辑器...'
      }
    }, 2000)
  }

  function onIdeFrameLoad() {
    ideLoaded.value = true
    ideLoadError.value = ''
    if (ideLoadTimer) { clearTimeout(ideLoadTimer); ideLoadTimer = null }
  }

  function onIdeFrameError() {
    ideLoadError.value = 'IDE 加载失败，code-server 可能未启动'
    if (ideLoadTimer) { clearTimeout(ideLoadTimer); ideLoadTimer = null }
  }

  function retryIdeLoad() {
    if (!ideUrl.value) return
    const base = stripCacheParam(ideUrl.value)
    ideLoaded.value = false
    ideLoadError.value = ''
    ideLoadingText.value = '正在重新连接...'
    ideUrl.value = null
    nextTick(() => {
      ideUrl.value = appendCacheParam(base)
      if (ideLoadTimer) clearTimeout(ideLoadTimer)
      ideLoadTimer = setTimeout(() => {
        if (!ideLoaded.value) {
          ideLoadError.value = '重试超时，请检查 code-server 状态'
        }
      }, 30_000)
    })
  }

  async function openPendingIde() {
    if (!pendingIdeUrl.value) return
    await setIdeUrl(pendingIdeUrl.value)
    pendingIdeUrl.value = null
    activeView.value = 'ide'
  }

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
