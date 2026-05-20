import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import router from './router'
import App from './App.vue'
import './styles/theme-vars.css'
// v3 2026-05-20 cleanup (code review P3-4): design-v2-tokens.css 已删
// theme-vars.css (v1 era --t-* legacy aliases) 保留向后兼容
// design-v3-tokens.css 现在是唯一 brand/state/surface token 来源
import './styles/design-v3-tokens.css'
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
