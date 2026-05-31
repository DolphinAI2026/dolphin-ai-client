# README

本文档目标是给开发者一份可以直接照着落地的插件开发说明。

## 1. 适用范围

- 工程类型：`FRONTEND_PLUGIN`
- Node 版本：`>= 16.x`
- 前端框架：`Vue 2.7.14`
- 命令体系：`df-apaas-cli` + `vue-cli-service`

## 2. 快速开始

### 2.1 安装依赖

```bash
npm install
```

### 2.2 本地启动

本工程按端分别启动本地开发服务：

```bash
npm run serve-admin
npm run serve-app
npm run serve-mobile
```

对应关系如下：

- `serve-admin` → `src/admin.js`
- `serve-app` → `src/app.js`
- `serve-mobile` → `src/mobile.js`

### 2.3 调试与构建

```bash
npm run debug
npm run build
npm run lint
```

其中：

- `npm run debug` 对应 `df-apaas-cli debug`
- `npm run build` 对应 `df-apaas-cli build`
- `npm run lint` 对应 `vue-cli-service lint`

## 3. 关键文件一览

开发插件时，优先关注下面这些文件：

| 文件 | 作用 |
| --- | --- |
| `package.json` | 定义 Node 版本、依赖、启动/调试/构建脚本 |
| `src/apaas.json` | 插件元信息与各端入口声明 |
| `src/admin.js` | 管理端插件入口 |
| `src/app.js` | 应用端插件入口 |
| `src/mobile.js` | 移动端插件入口 |
| `src/plugin-local/index.js` | 国际化合并入口 |
| `src/plugin-local/zh-CN/index.js` | 中文国际化资源 |
| `src/plugin-local/en-US/index.js` | 英文国际化资源 |
| `src/api/index.js` | 插件接口定义集中处 |
| `vue.config.js` | 本地开发服务、UMD 输出、样式构建配置 |

## 4. 工程目录结构

当前 `src/` 目录结构如下：

```text
src/
├─ api/
│  └─ index.js
├─ plugin-component/
│  └─ .gitkeep
├─ plugin-local/
│  ├─ en-US/
│  │  └─ index.js
│  ├─ zh-CN/
│  │  └─ index.js
│  └─ index.js
├─ admin.js
├─ app.js
├─ mobile.js
└─ apaas.json
```

说明：

- `plugin-component/` 是工程预留的组件目录。
- `plugin-local/` 是国际化目录，语言资源放在 `src/plugin-local/zh-CN` 和 `src/plugin-local/en-US` 中。
- `api/index.js` 是接口声明占位文件。

## 5. 插件配置文件：`src/apaas.json`

本工程中的 `src/apaas.json` 内容如下：

```json
{
  "copyAssets": ["public/frontend-plugin/frontend-plugin-guide"],
  "templateType": "FRONTEND_PLUGIN",
  "code": "PLUGIN_GUIDE",
  "name": "guide",
  "description": "guide",
  "outputName": "frontend-plugin-guide",
  "admin": "admin.js",
  "app": "app.js",
  "mobile": "mobile.js",
  "extraConfig": {}
}
```

建议重点理解以下字段：

- `code`：插件唯一标识。
- `name`：插件名称。
- `description`：插件描述。
- `outputName`：当前插件输出名。
- `admin` / `app` / `mobile`：对应三端入口文件。
- `copyAssets`：声明需要随插件一起处理的静态资源路径。
- `templateType`：工程模板类型，当前值为 `FRONTEND_PLUGIN`。

## 6. 入口文件契约

`src/admin.js`、`src/app.js`、`src/mobile.js` 三个入口文件结构一致，默认骨架如下：

```javascript
import './plugin-local/index.js' // 引入国际化

const install = function (context, hookManager, definition) {

}

const activate = function (context, hookManager, definition) {

}

const staticComponents = []

export default { install, activate, staticComponents }
```

可以据此得到本工程的最小入口契约：

- 每个端的入口文件都需要默认导出一个对象。
- 默认导出对象包含三个字段：`install`、`activate`、`staticComponents`。
- `install` 与 `activate` 都接收 `context`、`hookManager`、`definition` 三个参数。

### 6.1 插件生命周期（机制说明）

一个插件通常包含四个生命周期：安装、生效、失效、卸载。建议这样理解：

- `install`：安装时调用，适合放“插件装上就应该生效”的逻辑，例如注册静态组件、注册安装期钩子等。
- `activate`：生效时调用，适合放“插件启用后才应该生效”的逻辑，例如动态扩展、运行期监听、动态组件注册等。
- `inactivate`：失效时调用，用于清理运行期资源或撤销动态注册。
- `uninstall`：卸载时调用，用于最终清理插件注册的全局资源。

在本工程中，入口方法体现为：

```javascript
const install = function (context, hookManager, definition) {}
const activate = function (context, hookManager, definition) {}
```

可以把它理解为：

- `context`：宿主环境注入的全局上下文对象。
- `hookManager`：钩子管理器，用于监听、调用插件机制中的钩子。
- `definition`：当前插件定义信息。

`context` 中常见的能力可能包括：

- `$root`
- `XEventBus`

### 6.2 插件属性：`staticComponents` 与 `dynamicComponents`

插件组件分成两类：

- `staticComponents`：插件安装后就应可用的静态组件，在安装时注册，在卸载时解除注册。
- `dynamicComponents`：插件生效后才可用的动态组件，在生效时注册，在失效时解除注册。

- 组件需要在插件生效前就能被主工程使用时，应归入 `staticComponents`。
- 组件只在插件生效期间使用时，可以按 `dynamicComponents` 的思路实现。

**注意**：向外暴露的组件必须包含 `name` 属性，否则宿主环境按名称查找和渲染时可能不会生效。

### 6.3 钩子

在许多宿主环境中，插件与主工程之间通过钩子（hook）完成交互。下面给出常见的使用方式和约定。

#### 注册钩子

示例：

```javascript
ExtensionEngine.getInstance().hookManager.registerHook('hook_name', true)
```

第二个参数用于指定该钩子是否需要精确调起某个目标插件：

- `true`：调用时需要指定目标插件名，只会调起该插件的回调。
- `false`：调用时会执行所有监听了该钩子的插件回调。

> 注意：钩子必须先注册，之后才能监听或调用。

#### 监听钩子

如果宿主环境已经把 `hookManager` 传入入口方法，则可以直接使用该对象：

```javascript
hookManager.onHook('hook_name', (args) => {
  // do your business
})
```

`onHook` 支持 `namespace` 参数；在大多数插件入口场景中通常无需额外指定，如宿主环境有命名空间要求，请以对应文档为准。

#### 调用钩子

示例：

```javascript
ExtensionEngine.getInstance().hookManager.callHook('hook_name'[, name], ...args)
```

语义上需要注意两点：

1. 如果该钩子要求指定插件，则 `args` 的第一个参数会被视为目标插件名。
2. 如果该钩子不要求指定插件，则返回值通常是一个数组，每一项形如：

```json
{
  "code": "plugin_code",
  "result": "回调执行结果"
}
```

没有监听该钩子的插件，不会出现在返回结果中。


> 注意：`ExtensionEngine.getInstance()`、`registerHook()`、`callHook()` 等能力由宿主环境提供。实际开发时请以宿主运行时和相关文档为准。

实际开发时，建议结合宿主环境提供的钩子列表一起使用。

### 6.4 `DynamicComponent` 与动态组件渲染

宿主环境会提供名为 `DynamicComponent` 的渲染组件，用于按名称渲染已经注册到插件系统中的组件。

典型使用方式是给 `DynamicComponent` 传递 `component-name`：

- `component-name` 对应某个插件导出的 `staticComponents`
- 或者对应某个当前处于生效状态插件导出的 `dynamicComponents`

如果 `component-name` 对应不到已注册组件，则不会生效。

这里还需要区分两个概念：

- `DynamicComponent`：宿主环境提供的动态渲染组件。
- `dynamicComponents`：插件自身声明的一组“仅在生效时可用”的组件。

两者不是同一个概念，但会配合使用。

> 注意：`DynamicComponent` 由宿主环境提供；如果宿主没有提供该组件，请采用宿主推荐的渲染方式。

## 7. 国际化写法

本工程的国际化接入方式体现在 `src/plugin-local/index.js`：

```javascript
import zhLocaleModule from './zh-CN/index.js'
import enLocaleModule from './en-US/index.js'

if (window.df.getI18n().mergeLocaleMessage) {
  window.df.getI18n().mergeLocaleMessage('zh-CN', zhLocaleModule)
  window.df.getI18n().mergeLocaleMessage('en-US', enLocaleModule)
}
```

推荐写法如下：

1. 在 `src/plugin-local/zh-CN/index.js`、`src/plugin-local/en-US/index.js` 中维护语言包。
2. 在入口文件中直接 `import './plugin-local/index.js'`。
3. 由该文件统一调用 `window.df.getI18n().mergeLocaleMessage(...)` 合并语言资源。

语言包骨架如下：

```javascript
export default {
  frontendPlugin: {

  }
}
```

因此可以直接把自己的国际化 key 填到 `frontendPlugin` 下。

补充说明：本工程通过 `plugin-local/index.js` 和 `window.df.getI18n().mergeLocaleMessage(...)` 合并语言资源，建议新项目按这一方式实现国际化接入。

## 8. API 组织方式

`src/api/index.js` 提供了一个最小占位：

```javascript
const api = {
  // DEMO: {
  //   url: '/api/demo',
  //   method: 'POST',
  //   disableSuccessMsg: true
  // },
}

export default api
```

推荐做法是把插件中会复用的接口声明统一收敛到这里，再由业务模块按需引用。

## 9. 构建配置要点

`vue.config.js` 里有几项对插件开发比较关键的配置：

### 9.1 本地开发服务

dev server 配置为：

- `host: '0.0.0.0'`
- `port: '8080'`
- `allowedHosts: 'all'`
- 开启 `https`
- 响应头包含 `Access-Control-Allow-Origin: *`

并且它会直接读取以下证书文件：

```text
./https/server.key
./https/server.crt
```

所以如果本地缺少这两个文件，开发服务将无法按当前配置启动。

### 9.2 UMD 输出名

webpack 输出配置如下：

```javascript
output: {
  library: md5(apaasJson.code),
  libraryTarget: 'umd'
}
```

这表示：

- 插件产物使用 `umd` 方式输出。
- 输出库名由 `src/apaas.json` 中的 `code` 经过 `md5` 计算得到。

因此修改 `code` 时，应同步意识到输出库名也会变化。

## 10. 开发建议

1. 先改 `src/apaas.json`，把 `code`、`name`、`description`、`outputName` 改成自己的插件信息。
2. 再按需要实现 `src/admin.js`、`src/app.js`、`src/mobile.js`。
3. 如果有国际化需求，优先补充 `src/plugin-local/zh-CN/index.js` 和 `src/plugin-local/en-US/index.js`。
4. 如果有接口封装需求，统一维护在 `src/api/index.js`。
5. 本地联调时，优先使用`debug`命令与目标端对应的 `serve-*` 命令，并以 `package.json` 中列出的命令为准。
