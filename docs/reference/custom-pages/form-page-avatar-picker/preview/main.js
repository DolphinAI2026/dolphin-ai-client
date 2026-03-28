import Vue from 'vue'
import ElementUI from 'element-ui'
import 'element-ui/lib/theme-chalk/index.css'

import { installMockRequest } from './mock-api'
import ApaasCustomAvatarPicker from '../src/form-page/apaas-custom-avatar-picker.vue'
import App from './App.vue'

// ── Mock 平台依赖 ──
window.df = {
  getI18n() {
    return {
      mergeLocaleMessage() {},
      t(key) { return key },
      locale: 'zh-CN',
      messages: {},
    }
  },
  getStore() {
    return {
      state: {
        authModule: { userInfo: { name: 'preview-user' }, token: 'mock-token' },
        tenantModule: { currentOrg: { id: 'mock-tenant' } },
      },
    }
  },
  getEnv() {
    return { VUE_APP_BASE_DOMAIN: '' }
  },
}

Vue.use(ElementUI)

// 注入 $request mock
installMockRequest(Vue)

// Mock $route
Vue.prototype.$route = {
  query: { currentMenu: 'mock-menu-001' },
  params: {},
  path: '/preview',
}

// 注册业务组件
Vue.component('apaas-custom-avatar-picker', ApaasCustomAvatarPicker)

Vue.config.productionTip = false

new Vue({
  el: '#app',
  render: h => h(App),
})
