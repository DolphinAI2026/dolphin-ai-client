// 桌面能力门面 —— 全仓唯一允许 import @tauri-apps 的目录(由 desktop/guard.spec.ts 强制)。
//
// 业务代码一律从 '@/utils/desktop' 取桌面能力, 不直接碰 @tauri-apps。
// __DESKTOP__ 是编译期常量(vite.config define VITE_DESKTOP), 在线 build 下这些
// tauri 动态 import 全被 tree-shake, 不进在线包。需要在模板/逻辑里判桌面态时用
// isDesktop(直接写 __DESKTOP__ 进 <template> 会被 Vue 当 _ctx 属性而永远 undefined)。
export const isDesktop: boolean = __DESKTOP__

export { openExternal, openInAppBrowser } from './openExternal'
export { checkAndPromptUpdate } from './update'
export { pickDirectory } from './dialog'
