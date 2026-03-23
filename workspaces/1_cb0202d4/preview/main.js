import Vue from 'vue'
import ElementUI from 'element-ui'
import 'element-ui/lib/theme-chalk/index.css'

import { installMockRequest } from './mock-api'
import ApaasCustomPage from '../src/form-page/apaas-custom-data-table.vue'
import App from './App.vue'

Vue.use(ElementUI)

// 注入 $request mock
installMockRequest(Vue)

// 注册业务组件
Vue.component('apaas-custom-data-table', ApaasCustomPage)

new Vue({
  el: '#app',
  render: h => h(App)
})
