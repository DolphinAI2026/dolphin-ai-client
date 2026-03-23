import "./form-page-local/index.js";
import ApaasCustomPage from "./form-page/apaas-custom-data-table.vue";

const install = function (Vue) {
  Vue.component("apaas-custom-data-table", ApaasCustomPage);
  window[Symbol.for("apaas-custom-data-table")] = ApaasCustomPage;
};

export default { install };
