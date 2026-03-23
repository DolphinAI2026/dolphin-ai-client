import "./form-page-local/index.js";
import ApaasCustomAvatarPicker from "./form-page/apaas-custom-avatar-picker.vue";

const install = function (Vue) {
  // 1. 注册为全局 Vue 组件（平台路由渲染用）
  Vue.component("apaas-custom-avatar-picker", ApaasCustomAvatarPicker);

  // 2. 挂载到 window Symbol（平台弹窗通过这个获取组件定义）
  window[Symbol.for("apaas-custom-avatar-picker")] = ApaasCustomAvatarPicker;
};

export default { install };
