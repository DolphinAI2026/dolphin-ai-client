// 桌面端自动更新。仅 __DESKTOP__ 下生效:在线版调用是 no-op。
// 提示用 Element Plus 弹窗(webview 内可用),下载/安装/重启用 tauri 插件。
// 动态 import tauri 插件 → 在线 build 里这分支被 tree-shake 掉, 不进在线包。
import { ElMessageBox, ElMessage } from 'element-plus'

export async function checkAndPromptUpdate(opts: { silentIfNone: boolean }): Promise<void> {
  if (!__DESKTOP__) return
  let update: any = null
  try {
    const updater = await import('@tauri-apps/plugin-updater')
    update = await updater.check()
  } catch (e) {
    if (!opts.silentIfNone) ElMessage.error('检查更新失败:无法连接更新服务')
    console.error('[update] check 失败', e)
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
    ElMessage.error('更新失败,请稍后重试或手动下载')
    console.error('[update] downloadAndInstall 失败', e)
  }
}
