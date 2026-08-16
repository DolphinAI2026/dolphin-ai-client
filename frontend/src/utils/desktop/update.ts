// 桌面端自动更新。仅 __DESKTOP__ 下生效:在线版调用是 no-op。
// 提示用 Element Plus 弹窗(webview 内可用),下载/安装/重启用 tauri 插件。
// 动态 import tauri 插件 → 在线 build 里这分支被 tree-shake 掉, 不进在线包。
import { ElMessageBox, ElMessage } from 'element-plus'

export type DesktopUpdateCheckResult =
  | { status: 'not-available' | 'no-update' | 'dismissed' | 'installed' }
  | { status: 'failed'; error: string }

let updateCheckPromise: Promise<DesktopUpdateCheckResult> | null = null

function errText(e: any): string {
  if (!e) return '未知错误'
  if (typeof e === 'string') return e
  return e.message || e.toString?.() || JSON.stringify(e)
}

function failedUpdateResult(stage: string, error: unknown): DesktopUpdateCheckResult {
  console.warn(`[update] ${stage} failed`, errText(error))
  return { status: 'failed', error: '检查更新失败，请稍后重试' }
}

export async function checkAndPromptUpdate(opts: { silentIfNone: boolean }): Promise<DesktopUpdateCheckResult> {
  if (!__DESKTOP__ || __DESKTOP_WEB_PREVIEW__) return { status: 'not-available' }

  // App.vue and the desktop rail both mount during startup. Share one check so
  // a single launch cannot produce duplicate network requests or dialogs.
  if (updateCheckPromise) return updateCheckPromise
  updateCheckPromise = checkAndPromptUpdateOnce()
    .catch(error => failedUpdateResult('unexpected update check', error))
    .finally(() => { updateCheckPromise = null })
  return updateCheckPromise
}

async function checkAndPromptUpdateOnce(): Promise<DesktopUpdateCheckResult> {
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
    // 自动检查调用方可以安全忽略失败；手动检查调用方负责展示结果。
    return failedUpdateResult('check', lastErr)
  }

  if (!update) {
    return { status: 'no-update' }
  }
  try {
    await ElMessageBox.confirm(
      `发现新版本 ${update.version}\n\n${update.body || ''}`,
      '有可用更新',
      { confirmButtonText: '立即更新', cancelButtonText: '稍后', type: 'info' },
    )
  } catch (error) {
    if (error === 'cancel' || error === 'close') return { status: 'dismissed' }
    return failedUpdateResult('update prompt', error)
  }
  let loading: ReturnType<typeof ElMessage> | null = null
  try {
    loading = ElMessage({ message: '正在下载更新…', duration: 0 })
    await update.downloadAndInstall()
    loading.close()
    const proc = await import('@tauri-apps/plugin-process')
    await proc.relaunch()
    return { status: 'installed' }
  } catch (e) {
    loading?.close()
    return failedUpdateResult('download and install', e)
  }
}
