import zhLocaleModule from './zh-CN/index.js'
import enLocaleModule from './en-US/index.js'

if (window.df.getI18n().mergeLocaleMessage) {
  window.df.getI18n().mergeLocaleMessage('zh-CN', zhLocaleModule)
  window.df.getI18n().mergeLocaleMessage('en-US', enLocaleModule)
}
