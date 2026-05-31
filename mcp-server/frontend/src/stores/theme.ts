import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export type ThemeMode = 'light' | 'dark'

const STORAGE_KEY = 'theme'

// v3 2026-05-20 cleanup (code review #P2-6, #P2-8):
// 1. 删 setAccentColor / accentColor / accentVars / mix / rgba — picker UI 已删（commit f5e6c0a），
//    这套色阶生成机器没人调用 = 死代码 60+ 行
// 2. 一次性清掉老 'theme-accent-color' / 'theme-accent-color-v3' localStorage key（占用 + 防回归）
// 3. 加 window 'storage' event listener 让多 tab 主题切换实时同步（code review #P1-4）

function resolveInitialTheme(): ThemeMode {
  if (typeof localStorage === 'undefined') return 'light'
  const saved = localStorage.getItem(STORAGE_KEY) as ThemeMode | null
  if (saved === 'light' || saved === 'dark') return saved
  return 'light'
}

// 一次性清掉历史的 accent color storage key — 不用了
function purgeLegacyAccentKey() {
  if (typeof localStorage === 'undefined') return
  try {
    localStorage.removeItem('theme-accent-color')
    localStorage.removeItem('theme-accent-color-v3')
  } catch { /* private mode */ }
}

export const useThemeStore = defineStore('theme', () => {
  purgeLegacyAccentKey()

  const mode = ref<ThemeMode>(resolveInitialTheme())
  const isDark = computed(() => mode.value === 'dark')

  function applyDom(theme: ThemeMode) {
    if (typeof document === 'undefined') return
    const html = document.documentElement
    html.setAttribute('data-theme', theme)
    if (theme === 'dark') html.classList.add('dark')
    else html.classList.remove('dark')
  }

  function setTheme(theme: ThemeMode) {
    if (mode.value === theme) return
    mode.value = theme
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem(STORAGE_KEY, theme)
    }
    applyDom(theme)
  }

  function toggle() {
    setTheme(mode.value === 'dark' ? 'light' : 'dark')
  }

  // 初始 apply
  applyDom(mode.value)

  // v3 2026-05-20 (code review #P1-4): 监听 localStorage 'storage' 事件让多 tab 同步主题
  // tab A 切 dark → 写 localStorage → 浏览器在所有同 origin tab fire 'storage' event
  if (typeof window !== 'undefined') {
    window.addEventListener('storage', (e) => {
      if (e.key !== STORAGE_KEY) return
      const newValue = e.newValue
      if (newValue === 'light' || newValue === 'dark') {
        // 跳过 setTheme 直接更新 — 避免再次写 localStorage 触发 storage event 循环
        if (mode.value !== newValue) {
          mode.value = newValue
          applyDom(newValue)
        }
      }
    })
  }

  return { mode, isDark, setTheme, toggle }
})
