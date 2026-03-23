import Vue from 'vue'
import ElementUI from 'element-ui'
import 'element-ui/lib/theme-chalk/index.css'
import PreviewApp from './PreviewApp.vue'

Vue.use(ElementUI, { size: 'small' })
Vue.config.productionTip = false

new Vue({
  render: h => h(PreviewApp)
}).$mount('#app')
