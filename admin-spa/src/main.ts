import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import './styles/design-v3-tokens.css'  // ★ Claude design v3 — admin-spa 共享 frontend 的 brand/text/surface/line token
import './styles/density-align.css'    // 2026-05-21 — admin-spa 跟 frontend 密度对齐，覆盖 Element Plus 默认值
import './styles/element-plus-dark.css' // 2026-05-22 — Element Plus dark mode 用 design-v3-token 覆盖, 修配色断裂
import App from './App.vue'
import router from './router'

;(window as any).__APAAS_BUILDER_ADMIN_BUILD__ = '20260517-call-log-params'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(ElementPlus)
app.mount('#app')
