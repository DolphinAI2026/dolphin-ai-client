/// <reference types="vite/client" />

// 编译期常量: 桌面构建(build:desktop, VITE_DESKTOP=1)为 true, web 构建为 false。
// 由 vite.config.ts 的 define 注入。放在 src/ 下以便 tsconfig.app.json(include: src/**) 收录。
declare const __DESKTOP__: boolean
// 浏览器预览桌面初始化流程时启用，仅 mock Tauri 桌面桥接，不进入正式桌面包。
declare const __DESKTOP_WEB_PREVIEW__: boolean
// 应用版本号(取自 src-tauri/tauri.conf.json), 编译期注入。
declare const __APP_VERSION__: string
