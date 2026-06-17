// 桌面端自动更新。仅 __DESKTOP__ 下生效:在线版调用是 no-op。
// 提示用 Element Plus 弹窗(webview 内可用),下载/安装/重启用 tauri 插件。
// 动态 import tauri 插件 → 在线 build 里这分支被 tree-shake 掉, 不进在线包。
import { ElMessageBox, ElMessage } from 'element-plus'

function errText(e: any): string {
  if (!e) return '未知错误'
  if (typeof e === 'string') return e
  return e.message || e.toString?.() || JSON.stringify(e)
}

export async function checkAndPromptUpdate(opts: { silentIfNone: boolean }): Promise<void> {
  if (!__DESKTOP__) return

  // check() 失败自动重试一次(扛瞬时网络抖动);仍失败则报真实错误。
  let update: any = null
  let lastErr: any = null
  for (let attempt = 1; attempt <= 2; attempt++) {
    try {
      const updater = await import('@tauri-apps/plugin-updater')
      update = await updater.check()
      lastErr = null
      break
    } catch (e) {
      lastErr = e
      console.error(`[update] check 第 ${attempt} 次失败`, e)
    }
  }
  if (lastErr) {
    // 真实错误透出(之前写死"无法连接"会误导诊断)。
    if (!opts.silentIfNone) ElMessage.error(`检查更新失败:${errText(lastErr)}`)
    return
  }

  if (!update) {
    if (!opts.silentIfNone) ElMessage.success('已是最新版本')
    return
  }
  try {
    await ElMessageBox.confirm(
      `发现新版本 ${update.version}\n\n${update.body || ''}`,
      '有可用更新',
      { confirmButtonText: '立即更新', cancelButtonText: '稍后', type: 'info' },
    )
  } catch {
    return // 用户点了「稍后」
  }
  const loading = ElMessage({ message: '正在下载更新…', duration: 0 })
  try {
    await update.downloadAndInstall()
    loading.close()
    const proc = await import('@tauri-apps/plugin-process')
    await proc.relaunch()
  } catch (e) {
    loading.close()
    ElMessage.error(`更新失败:${errText(e)}`)
    console.error('[update] downloadAndInstall 失败', e)
  }
}
