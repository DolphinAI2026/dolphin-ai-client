// 打开外部链接（aPaaS 低代码后台、线上应用、平台后台等）。
//
// 在 Tauri 桌面端 (WKWebView) 里 `window.open(url, '_blank')` 不会打开外部链接 ——
// 它静默无反应（既不开系统浏览器，也不在 webview 内导航）。必须经 tauri-plugin-shell
// 调系统默认浏览器。在线版 (__DESKTOP__=false) 仍走 window.open 新标签页。
//
// __DESKTOP__ 是编译期常量：在线 build 里这个分支会被 tree-shake 掉，
// 连同 @tauri-apps/plugin-shell 的动态 import 一起消除，不进在线包。
export async function openExternal(url: string): Promise<void> {
  if (!url) return
  if (__DESKTOP__) {
    try {
      const shell = await import('@tauri-apps/plugin-shell')
      await shell.open(url)
      return
    } catch (e) {
      // shell 不可用（权限/插件异常）时退回 window.open 兜底，至少不静默失败。
      console.error('[openExternal] tauri shell open 失败，退回 window.open', e)
    }
  }
  window.open(url, '_blank', 'noopener,noreferrer')
}

// 在 app 内开一个 Tauri 子窗口当"内置浏览器"(顶层 WKWebView, 非 iframe 嵌套)。
// 给「低代码后台」用 — 留在 app 内, 不跳系统浏览器。创建失败(权限等)退回系统浏览器。
// 在线版仍走 window.open。
export async function openInAppBrowser(url: string, title = '内置浏览器'): Promise<void> {
  if (!url) return
  if (!__DESKTOP__) {
    window.open(url, '_blank', 'noopener,noreferrer')
    return
  }
  try {
    const { WebviewWindow } = await import('@tauri-apps/api/webviewWindow')
    const label = 'inapp-' + Date.now()
    const w = new WebviewWindow(label, { url, title, width: 1280, height: 860, center: true })
    w.once('tauri://error', (e) => {
      console.error('[inapp-browser] 创建失败, 退回系统浏览器', e)
      window.open(url, '_blank', 'noopener,noreferrer')
    })
  } catch (e) {
    console.error('[inapp-browser] 异常, 退回系统浏览器', e)
    window.open(url, '_blank', 'noopener,noreferrer')
  }
}
