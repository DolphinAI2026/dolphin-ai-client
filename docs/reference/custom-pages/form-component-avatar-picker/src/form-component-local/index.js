import zhLocaleModule from './zh-CN/index.js'
import enLocaleModule from './en-US/index.js'

const platformI18n =
  window.df?.getI18n?.() ||
  window.APaaSSDK?.context?.globalVueI18n

if (platformI18n?.mergeLocaleMessage) {
  platformI18n.mergeLocaleMessage('zh-CN', zhLocaleModule)
  platformI18n.mergeLocaleMessage('en-US', enLocaleModule)
}
