import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import router from './router'
import App from './App.vue'
import './styles/theme-vars.css'
import './styles/design-v2-tokens.css'
import './styles/design-v3-tokens.css'  // ★ Claude design v3 — 覆盖 v2 brand/text/surface 等共享 var；保留 v2 独有色
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
