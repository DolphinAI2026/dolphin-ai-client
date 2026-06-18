// 桌面文件夹选择器(Tauri dialog 插件)。在线版无原生选择器, 返 null。
// __DESKTOP__ 是编译期常量:在线 build 里这分支连同 @tauri-apps 动态 import 被 tree-shake。
export async function pickDirectory(title: string): Promise<string | null> {
  if (!__DESKTOP__) return null
  const { open } = await import('@tauri-apps/plugin-dialog')
  const picked = await open({ directory: true, multiple: false, title })
  return typeof picked === 'string' ? picked : null
}
