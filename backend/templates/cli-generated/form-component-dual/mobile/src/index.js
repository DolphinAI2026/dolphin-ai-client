import '@shared/local/index.js' // 引入国际化
import { customFormEditorList, customFormWidgetList } from './form-component'
import { widgetConfigList, editorConfigList } from './form-component-config'
import { AbilityFieldMap, AbilityFieldConvert } from '@shared/form-ability'

// eslint-disable-next-line
const install = function(Vue, opts) {
  // 注册自开发配置组件
  if (customFormEditorList && Array.isArray(customFormEditorList)) {
    customFormEditorList.forEach((comp) => {
      Vue.component(comp.name, comp)
    })
  }
  // 注册自开发表单组件
  if (customFormWidgetList && Array.isArray(customFormWidgetList)) {
    customFormWidgetList.forEach((comp) => {
      Vue.component(comp.name, comp)
    })
  }
  // 表单引擎注册自开发组件配置
  if (editorConfigList && Array.isArray(editorConfigList)) {
    editorConfigList.forEach((editorConfig) => {
      Vue.FormEngine.WidgetControl.registerEditorConfig(editorConfig)
    })
  }
  // 表单引擎注册自开发组件
  if (widgetConfigList && Array.isArray(widgetConfigList)) {
    widgetConfigList.forEach((widgetConfig) => {
      const compConfig = {
        widgetConfig
      }
      Vue.FormEngine && Vue.FormEngine.registerCustomGroupWidgetConfig(compConfig)
    })
  }

  // 注册组件能力配置
  Vue.FormEngine && Vue.FormEngine.AbilityControl && Vue.FormEngine.AbilityControl.batchRegisterComponentTypeConfig(AbilityFieldMap)
  // 注册字段值转换配置
  Vue.FormEngine && Vue.FormEngine.AbilityControl && Vue.FormEngine.AbilityControl.batchRegisterFieldValueConvert(AbilityFieldConvert)
}

const FormComponent = {
  install: install
}

export default FormComponent
