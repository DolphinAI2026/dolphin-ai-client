import "./form-page-local/index.js";
import ApaasCustomPage from "./form-page/apaas-custom-map-view.vue";

const install = function (Vue) {
  Vue.component("apaas-custom-map-view", ApaasCustomPage);
  window[Symbol.for("apaas-custom-map-view")] = ApaasCustomPage;
};

export default { install };
