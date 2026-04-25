import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export type ThemeMode = 'light' | 'dark'

const STORAGE_KEY = 'theme'

function resolveInitialTheme(): ThemeMode {
  const saved = localStorage.getItem(STORAGE_KEY) as ThemeMode | null
  if (saved === 'light' || saved === 'dark') return saved
  return 'light'
}

export const useThemeStore = defineStore('theme', () => {
  const mode = ref<ThemeMode>(resolveInitialTheme())

  const isDark = computed(() => mode.value === 'dark')

  function applyTheme(theme: ThemeMode) {
    const html = document.documentElement
    html.setAttribute('data-theme', theme)
    if (theme === 'dark') {
      html.classList.add('dark')
    } else {
      html.classList.remove('dark')
    }
  }

  function setTheme(theme: ThemeMode) {
    mode.value = theme
    localStorage.setItem(STORAGE_KEY, theme)
    applyTheme(theme)
  }

  function toggle() {
    setTheme(mode.value === 'dark' ? 'light' : 'dark')
  }

  // Apply immediately on store creation
  applyTheme(mode.value)

  return { mode, isDark, setTheme, toggle }
})
