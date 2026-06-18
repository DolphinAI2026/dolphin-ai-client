// 接缝守卫: @tauri-apps 只允许在 src/utils/desktop/ 内 import。
// 防止桌面能力再次渗进业务组件(根因=过去一周大量 commit 慢慢泄漏)。
// 业务代码一律走 '@/utils/desktop' 门面。
import { describe, it, expect } from 'vitest'

// Vite glob 抓 src 下所有源文件原文(编译期内联), 免 node 类型依赖。
const files = import.meta.glob('/src/**/*.{ts,vue,js,mjs}', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

// 只匹配真实 import 语句, 不误伤注释里的 @tauri-apps 字样。
const TAURI_IMPORT = /import\s*\(\s*['"]@tauri-apps|from\s+['"]@tauri-apps/

describe('desktop capability seam', () => {
  it('@tauri-apps 仅允许在 src/utils/desktop/ 内 import', () => {
    const offenders = Object.entries(files)
      .filter(([path]) => !path.startsWith('/src/utils/desktop/'))
      .filter(([, content]) => TAURI_IMPORT.test(content))
      .map(([path]) => path)
    expect(
      offenders,
      `这些文件不应直接 import @tauri-apps, 请走 @/utils/desktop 门面:\n${offenders.join('\n')}`,
    ).toEqual([])
  })
})
