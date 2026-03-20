# aPaaS 脚本扩展开发指南

## 概述
脚本扩展用于业务事件的自定义节点中，支持JavaScript、Python、Groovy三种语言。

## JavaScript脚本
- 数据获取: `lowCodeContext.businessEventEngine.customNodeData`
- 返回格式: 对象 `{}` 或对象数组 `[{},{}]`
- 运行环境: 浏览器端

## Python脚本
- 数据获取: `definesys.input()` 返回字典
- 返回格式: 字典
- 运行环境: 服务器端

## Groovy脚本
- 数据获取: `xdapEventSystemFunctions.getFullData()`
- 字段key前缀: `bof_code_`
- 运行环境: 服务器端

## 业务事件自定义弹窗
- 语言: Vue模板语法
- 获取数据: `lowCodeContext.businessEventEngine.inputDatas`
- 确认: `lowCodeContext.businessEventEngine.confirmEventEmit(params)`
- 取消: `lowCodeContext.businessEventEngine.cancelEventEmit()`
- 配置: language, template, footerTemplate, modalOptions

## 界面样式扩展(CSS)
- 作用域: `.form-custom-style`
- 定位组件: `.form-item-wrapper[data-component-id="xxx"]`
- 配置位置: 表单设计 → 表单设置 → 更多设置

## 列表自定义模块
- 脚本: Vue/HTML语法
- 数据: `lowCodeContext.pageViewConfig`
- 样式: SCSS
- 可用方法: queryListBusinessData, queryListStatisticalData, generateSearchItem
