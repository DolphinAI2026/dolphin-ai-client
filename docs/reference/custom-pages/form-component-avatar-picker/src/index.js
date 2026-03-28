import './form-component-local/index.js'
import { customFormEditorList, customFormWidgetList } from './form-component'
import { widgetConfigList, editorConfigList } from './form-component-config'
import { AbilityFieldMap, AbilityFieldConvert } from './form-ability'

const install = function(Vue) {
  // 注册编辑器组件
  customFormEditorList.forEach((comp) => {
    Vue.component(comp.name, comp)
  })
  // 注册表单组件（各场景）
  customFormWidgetList.forEach((comp) => {
    Vue.component(comp.name, comp)
  })
  // 注册编辑器配置
  editorConfigList.forEach((editorConfig) => {
    Vue.FormEngine.WidgetControl.registerEditorConfig(editorConfig)
  })
  // 注册组件配置
  widgetConfigList.forEach((widgetConfig) => {
    Vue.FormEngine && Vue.FormEngine.registerCustomGroupWidgetConfig({ widgetConfig })
  })
  // 注册能力映射
  Vue.FormEngine && Vue.FormEngine.AbilityControl && Vue.FormEngine.AbilityControl.batchRegisterComponentTypeConfig(AbilityFieldMap)
  Vue.FormEngine && Vue.FormEngine.AbilityControl && Vue.FormEngine.AbilityControl.batchRegisterFieldValueConvert(AbilityFieldConvert)
}

export default { install }
