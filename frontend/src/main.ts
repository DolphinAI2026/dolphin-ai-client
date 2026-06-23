import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import router from './router'
import App from './App.vue'
// 字体 self-host(2026-06-13): latin 走仓库内 Geist, CJK 落系统字体(苹方/雅黑)。
// 此前 design-v3-tokens.css 远程 @import Google Fonts, 网络不通时整页回落系统字体, 观感漂移。
import '@fontsource/geist-sans/400.css'
import '@fontsource/geist-sans/500.css'
import '@fontsource/geist-sans/600.css'
import '@fontsource/geist-sans/700.css'
import '@fontsource/geist-mono/400.css'
import '@fontsource/geist-mono/500.css'
import './styles/theme-vars.css'
// v3 2026-05-20 cleanup (code review P3-4): design-v2-tokens.css 已删
// theme-vars.css (v1 era --t-* legacy aliases) 保留向后兼容
// design-v3-tokens.css 现在是唯一 brand/state/surface token 来源
import './styles/design-v3-tokens.css'
// Codex 复刻 token(.codex-skin 作用域,Code 模式专用,唯一 --cx-* 定义处)
import './styles/codex-tokens.css'
import './style.css'
import './styles/builder.css'
import { useThemeStore } from './stores/theme'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(router)
app.use(ElementPlus, { locale: zhCn })

// Initialize theme before mount
useThemeStore()

app.mount('#app')
