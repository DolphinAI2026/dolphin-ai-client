import "./form-page-local/index.js"; // 引入国际化
import ApaasCustomDemo from "./form-page/apaas-custom-demo.vue";
const install = function (Vue) {
  Vue.component("apaas-custom-demo", ApaasCustomDemo);
};

const FormPage = {
  install: install,
};

export default FormPage;
