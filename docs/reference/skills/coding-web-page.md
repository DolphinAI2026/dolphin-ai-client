# aPaaS Web端自开发页面开发指南

## 概述
Web端自开发页面是应用中的完整自定义页面，通过菜单配置访问。

## 可用服务
- **网络请求**: `this.$request({url, method, params, headers})`
  - 返回格式: `{"code":"ok","message":"","data":{...}}`
  - 使用 `.asyncThen()` 处理成功，`.asyncErrorCatch()` 处理异常
- **日期**: `this.$dayjs`
- **工具**: `this.$lodash`
- **Store**: authModule(权限), tenantModule(租户), appModule(应用)
- **SVG图标**: `<x-svg-icon name="文件名"></x-svg-icon>`
- **环境变量**: `window.GLOBAL_ENV`（仅线上）

## 权限控制
使用 `custom-permissions.mixin.js` 获取 `customPagePermissions` 对象进行权限判断。

## 打开系统弹窗
- 抽屉详情: `window.DETAIL_FORM({ formId, rowDocumentId })`
- 弹窗编辑: `window.EDIT_FORM({ formId, rowDocumentId })` （rowDocumentId为空时新增）

## 实战示例

### 待办列表页面
调用系统API获取待办数据，点击打开审批详情页。

### 项目分析图表
使用vue-echarts展示项目数据图表，支持点击交互。

### 自定义登录页
配置SSO重定向URL，支持验证码/短信/邮箱验证。
