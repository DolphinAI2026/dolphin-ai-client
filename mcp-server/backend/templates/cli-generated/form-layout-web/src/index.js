import "./form-layout-local/index.js"; // 引入国际化
import ApaasCustomDemo from "./form-layout/apaas-custom-demo.vue";
const install = function (Vue) {
  if (Vue.LayoutEngine) {
    const layoutEngine = Vue.LayoutEngine.getInstance(Vue.LayoutEngine.currentLayoutId)
    layoutEngine.registerLayoutComponent(ApaasCustomDemo);
  }
};

const FormPage = {
  install: install,
};

export default FormPage;
