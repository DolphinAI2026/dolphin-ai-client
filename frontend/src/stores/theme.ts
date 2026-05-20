import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export type ThemeMode = 'light' | 'dark'

const STORAGE_KEY = 'theme'
// v3 (2026-05-20) — bump key so users w/ old purple #6d5df6 in localStorage get the new blue default.
// Existing users who actively picked a custom color via the picker can re-pick — most never touched it.
const ACCENT_STORAGE_KEY = 'theme-accent-color-v3'
const DEFAULT_ACCENT = '#1D4ED8' // v3 brand = blue-700 (matches design-v3-tokens.css --brand)

function resolveInitialTheme(): ThemeMode {
  const saved = localStorage.getItem(STORAGE_KEY) as ThemeMode | null
  if (saved === 'light' || saved === 'dark') return saved
  return 'light'
}

function isHexColor(value: string | null): value is string {
  return !!value && /^#[0-9a-f]{6}$/i.test(value)
}

function clamp(value: number) {
  return Math.max(0, Math.min(255, Math.round(value)))
}

function mix(hex: string, target: string, amount: number) {
  const read = (color: string) => ({
    r: parseInt(color.slice(1, 3), 16),
    g: parseInt(color.slice(3, 5), 16),
    b: parseInt(color.slice(5, 7), 16),
  })
  const a = read(hex)
  const b = read(target)
  const part = (value: number) => value.toString(16).padStart(2, '0')
  return `#${part(clamp(a.r + (b.r - a.r) * amount))}${part(clamp(a.g + (b.g - a.g) * amount))}${part(clamp(a.b + (b.b - a.b) * amount))}`
}

function rgba(hex: string, alpha: number) {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

function resolveInitialAccent(): string {
  const saved = localStorage.getItem(ACCENT_STORAGE_KEY)
  return isHexColor(saved) ? saved : DEFAULT_ACCENT
}

export const useThemeStore = defineStore('theme', () => {
  const mode = ref<ThemeMode>(resolveInitialTheme())
  const accentColor = ref<string>(resolveInitialAccent())

  const isDark = computed(() => mode.value === 'dark')
  const accentVars = computed(() => {
    const color = accentColor.value
    const dark = mode.value === 'dark'
    return {
      '--brand-50': mix(color, '#ffffff', 0.92),
      '--brand-100': mix(color, '#ffffff', 0.82),
      '--brand-200': mix(color, '#ffffff', 0.66),
      '--brand-300': mix(color, '#ffffff', 0.48),
      '--brand-400': mix(color, '#ffffff', 0.24),
      '--brand-500': color,
      '--brand-600': mix(color, '#000000', 0.12),
      '--brand-700': mix(color, '#000000', 0.24),
      '--brand-800': mix(color, '#000000', 0.36),
      '--brand': dark ? mix(color, '#ffffff', 0.18) : color,
      '--brand-hover': dark ? mix(color, '#ffffff', 0.32) : mix(color, '#000000', 0.12),
      '--brand-text': dark ? mix(color, '#ffffff', 0.56) : mix(color, '#000000', 0.24),
      '--brand-soft': dark ? rgba(color, 0.12) : mix(color, '#ffffff', 0.92),
      '--brand-soft-2': dark ? rgba(color, 0.20) : mix(color, '#ffffff', 0.84),
      '--brand-ring': rgba(color, dark ? 0.28 : 0.18),
      '--border-focus': rgba(color, dark ? 0.55 : 0.45),
      '--bg-app': dark
        ? `linear-gradient(180deg, ${mix(color, '#000000', 0.82)} 0%, #0A0913 100%)`
        : `linear-gradient(180deg, ${mix(color, '#ffffff', 0.96)} 0%, ${mix(color, '#ffffff', 0.90)} 100%)`,
      '--bg-rail': dark ? mix(color, '#000000', 0.82) : mix(color, '#ffffff', 0.88),
    }
  })

  function applyTheme(theme: ThemeMode, color = accentColor.value) {
    const html = document.documentElement
    html.setAttribute('data-theme', theme)
    html.setAttribute('data-accent-color', color)
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

  function setAccentColor(nextAccent: string) {
    if (!isHexColor(nextAccent)) return
    accentColor.value = nextAccent
    localStorage.setItem(ACCENT_STORAGE_KEY, nextAccent)
    applyTheme(mode.value, nextAccent)
  }

  function toggle() {
    setTheme(mode.value === 'dark' ? 'light' : 'dark')
  }

  // Apply immediately on store creation
  applyTheme(mode.value, accentColor.value)

  return { mode, accentColor, accentVars, isDark, setTheme, setAccentColor, toggle }
})
