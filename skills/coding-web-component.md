# aPaaS Web端自开发组件开发指南

## 概述
Web端自开发组件是aPaaS平台表单中使用的自定义Vue组件，包含编辑态和只读态两个独立组件。

## 开发流程
1. 使用 `x-apaas-cli init <模块名>` 初始化项目
2. 编写组件配置 (config.js)
3. 编写编辑态组件 (edit/*.vue)
4. 编写只读态组件 (read/*.vue)
5. 在index.js中注册组件
6. 配置apaas.json
7. 打包上传: `x-apaas-cli build <模块名>`

## 核心概念

### FormWidgetConfigMixin
所有自开发组件必须引入此mixin，提供以下属性：
- `widget` - 组件配置信息（label, isInTable等）
- `formValue` - 当前组件值（可读写，双向绑定）
- `showRequired` - 是否显示必填星号
- `validatorRules` - 校验规则数组
- `validateKey` - 校验标识
- `validateInfo` - 校验信息对象
- `formReadonly` - 表单是否只读
- `formDisabled` - 表单是否禁用

### x-proxy-form-item
使自开发组件样式与系统组件一致的包裹组件，接收属性：
- isInTable, showRequired, label, validatorRules, validateKey, validateInfo

### 跨组件通信
通过watch其他组件的formValue实现。

### 自定义校验
在created中通过validatorRules注册自定义校验器。

## 实战示例

### 上传头像组件
使用vue-cropper实现图片裁剪上传，裁剪后转File类型再上传。

### 时间区间选择
两个组件互相watch对方的formValue，实现开始时间不能晚于结束时间的校验。

### 判断手机号运营商
通过正则表达式判断手机号段，注册自定义校验器进行验证。

### 获取客户端IP
在created中自动获取IP并赋值给formValue。

### 调用第三方天气接口
watch城市选择组件变化，调用天气API显示结果。
