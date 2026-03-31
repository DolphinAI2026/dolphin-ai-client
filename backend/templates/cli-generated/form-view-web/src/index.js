import "./form-view-local/index.js"; // 引入国际化
import ApaasCustomDemo from "./form-view/apaas-custom-demo.vue";
const install = function (Vue) {
  Vue.component("apaas-custom-demo", ApaasCustomDemo);
};

const FormView = {
  install: install,
};

export default FormView;
