import './form-component-local/index.js'
import { customFormEditorList, customFormWidgetList } from './form-component'
import { widgetConfigList, editorConfigList } from './form-component-config'
import { AbilityFieldMap, AbilityFieldConvert } from './form-ability'

const install = function(Vue) {
  customFormEditorList.forEach((comp) => { Vue.component(comp.name, comp) })
  customFormWidgetList.forEach((comp) => { Vue.component(comp.name, comp) })
  editorConfigList.forEach((editorConfig) => {
    Vue.FormEngine.WidgetControl.registerEditorConfig(editorConfig)
  })
  widgetConfigList.forEach((widgetConfig) => {
    Vue.FormEngine && Vue.FormEngine.registerCustomGroupWidgetConfig({ widgetConfig })
  })
  Vue.FormEngine && Vue.FormEngine.AbilityControl && Vue.FormEngine.AbilityControl.batchRegisterComponentTypeConfig(AbilityFieldMap)
  Vue.FormEngine && Vue.FormEngine.AbilityControl && Vue.FormEngine.AbilityControl.batchRegisterFieldValueConvert(AbilityFieldConvert)
}

export default { install }
