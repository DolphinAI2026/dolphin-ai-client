# aPaaS 表单自开发组件（FORM_COMPONENT）开发指南

> 基于图表分析组件开发实践总结，记录所有踩过的坑。

---

## 一、项目初始化

### 1.1 使用脚手架

```bash
# 安装脚手架
npm install -g @x-apaas/df-apaas-cli

# 初始化表单组件项目
df-apaas-cli init <component-name>
# 选择：表单组件 → Web
```

### 1.2 关键文件结构

```
form-component-xxx/
├── src/
│   ├── index.js                          # 入口文件，注册组件
│   ├── apaas.json                        # 组件清单（平台识别用）
│   ├── mixin/
│   │   ├── form-widget.mixin.js          # 表单组件 Mixin（提供 formValue, widget, formEngine 等）
│   │   └── form-config.mixin.js          # 编辑器配置 Mixin（提供 componentConfig, formEngine 等）
│   ├── validator/                        # 校验器
│   ├── form-component/
│   │   ├── form-widget/
│   │   │   ├── edit/xxx-edit.vue         # 编辑态（前台填写）—— 只渲染，不显示配置
│   │   │   ├── read/xxx-read.vue         # 只读态（前台查看）
│   │   │   ├── ide/xxx-ide.vue           # 设计态（表单设计器中预览）
│   │   │   ├── list/xxx-list.vue         # 列表态
│   │   │   ├── print/xxx-print.vue       # 打印态
│   │   │   ├── search/xxx-search.vue     # 搜索态
│   │   │   └── search-ide/              # 搜索设计态
│   │   └── form-editor/
│   │       └── xxx-setting.vue           # 右侧配置面板（表单设计器中）
│   └── form-component-config/
│       ├── form-widget/xxx.widget.config.js    # 组件配置
│       └── form-editor/xxx.editor.config.js    # 编辑器配置
├── https/                                # HTTPS 证书（debug 必需）
│   ├── server.key
│   └── server.crt
├── vue.config.js
└── package.json
```

---

## 二、构建与打包（坑最多）

### 2.1 构建必须用 UMD library 模式

```json
// package.json
{
  "scripts": {
    "serve": "vue-cli-service serve src/index.js",
    "build": "vue-cli-service build --target lib --name <component-name> src/index.js",
    "debug": "df-apaas-cli debug"
  },
  "templateType": "FORM_COMPONENT"  // debug 命令必需！
}
```

> **坑：** 标准 `vue-cli-service build` 生成的是 Web 应用，平台无法识别。必须用 `--target lib` 生成 UMD 格式。

### 2.2 vue.config.js 配置

```javascript
const { defineConfig } = require('@vue/cli-service')
const fs = require('fs')
const apaasJson = require('./src/apaas.json')

module.exports = defineConfig({
  transpileDependencies: true,
  productionSourceMap: false,
  // 注意：不要加 pages 配置！会影响 serve 模式的 UMD 导出
  devServer: {
    host: '0.0.0.0',
    port: '8080',
    hot: true,
    allowedHosts: 'all',
    https: { key: fs.readFileSync('./https/server.key'), cert: fs.readFileSync('./https/server.crt') },
    headers: { 'Access-Control-Allow-Origin': '*' },
    client: { overlay: false }
  },
  configureWebpack: {
    output: {
      library: apaasJson.outputName,  // 全局变量名，debug 注入时使用
      libraryTarget: 'umd'
    }
  },
  css: {
    loaderOptions: {
      sass: { implementation: require('sass') }
    }
  }
})
```

> **坑：** 不能加 `pages: { index: { entry: 'src/index.js' } }`，否则 serve 模式下 UMD 导出会出问题。

### 2.3 apaas.json 组件清单

```json
{
  "entry": "index.js",
  "templateType": "FORM_COMPONENT",
  "customWidgetList": [
    {
      "code": "FORM_CUSTOM_COMPONENT_XXX",
      "text": "组件名称",
      "description": "组件描述"
    }
  ],
  "copyAssets": ["public/form-component/<component-name>"],
  "router": {},
  "outputName": "<component-name>"
}
```

### 2.4 上传 zip 包结构

```
component-name.zip
├── component-name.umd.min.js
├── component-name.umd.js
├── component-name.common.js
├── component-name.css
├── demo.html
├── apaas.json                    ← 必须包含！
└── static/custom/component-name/ ← 必须包含！（即使空目录）
```

> **坑：** `apaas.json` 和 `static/` 目录必须在 zip 根目录，否则平台不识别组件。

---

## 三、组件配置（widget.config.js）

### 3.1 标准模板

```javascript
const config = {
  version: 2.0,
  code: 'FORM_CUSTOM_COMPONENT_XXX',
  desc: { iconType: 'DEFAULT', icon: '<svg>...</svg>', text: '组件名', description: '描述' },
  instance: { uuid: '$itemUuid', inTable: false },
  component: {
    ide: 'FormComponentXxxIde',
    edit: 'FormComponentXxxEdit',
    read: 'FormComponentXxxRead',
    list: 'FormComponentXxxList',
    association: 'FormComponentXxxList',
    lov: 'FormComponentXxxList',
    print: 'FormComponentXxxPrint',
    search: 'FormComponentXxxSearch',
    searchIde: 'FormComponentXxxSearchIde'
  },
  widget: {
    display: {
      label: '组件名', width: 12, mobileWidth: 12, height: 1,
      hidden: false, readOnly: false, required: false, onlyCreateEdit: false
    },
    allow: { useInTableColumn: true },
    default: { customDefaultKey: 'defaultValue', value: '' },
    validator: { uniqueCheck: false },
    validatorList: [{ validatorConfig: [], validatorMessage: '' }],
    special: { frontBusinessObjectComponentType: 'BOF_TEXT', saveWithHidden: false },
    customComponentConfig: {},   // 自定义配置存储（设计器配置持久化用）
    componentModelField: ['TEXT'],
    editor: {
      config: [
        'INFO', 'LABEL', 'FIELD_CODE', 'TITLE_DESCRIPTION', 'WIDTH',
        'FORM_CUSTOM_COMPONENT_XXX_SETTING',  // 自定义配置面板
        'FORMULA_RULE', 'HIDDEN', 'READONLY', 'REQUIRED', 'EDITONNEW',
        'UNIQUE', 'HIDDEN_SAVE', 'HIDDEN_TRIGGER', 'TRIGGER_BUSINESS_EVENTS'
      ],
      excludeInTable: ['WIDTH']
    }
  },
  methods: {},
  formatValueSchema: {}
}
export default config
```

> **坑1：** `customComponentConfig` 必须在 widget 配置中声明（即使是空对象 `{}`），否则平台保存时不会序列化它。
> **坑2：** `customComponentConfig` 的值不能包含空字符串（如 `{ dataSource: '' }`），否则平台校验会认为"配置不完整"阻止保存。
> **坑3：** 不能删除标准 editor config 项（如 TITLE_DESCRIPTION, FORMULA_RULE 等），否则平台绑定模型字段时会报 `Cannot read properties of undefined (reading 'includes')` 错误。

### 3.2 editor.config.js

```javascript
const config = {
  code: 'FORM_CUSTOM_COMPONENT_XXX_SETTING',
  editorConfigType: 'FORM_CUSTOM_COMPONENT_XXX_SETTING',
  componentName: 'FormComponentXxxSetting',
  configProperty: 'customComponentConfig'  // 关联 widget.customComponentConfig
}
export default config
```

---

## 四、Setting.vue（设计器配置面板）

### 4.1 正确的 Props 和数据存取方式

```javascript
export default {
  name: 'FormComponentXxxSetting',
  props: {
    // 平台通过 EditorFormConfigMixin 传入这些 props
    componentConfig: { default: null },   // widget 对象
    formEngine: { default: null },         // 表单引擎实例
    widget: { default: null },             // 兼容旧方式
    editConfig: { default: null },
    configProperty: { default: null },
    formItemList: { default: null },
    formRule: { default: null },
    globalData: { default: null },
    widgetConfig: { default: null },
    disabled: { default: false }
  },
  inject: {
    renderGlobal: { default: null },       // 必须带 default，否则找不到 provide 时会崩
    getPreviewLanguage: { default: null },
    getI18nShowStatus: { default: null },
    filterTableFromNodeFields: { default: null }
  },
  data() {
    return {
      localConfig: { /* 本地配置状态 */ }
    }
  },
  computed: {
    widgetObj() {
      return this.componentConfig || this.widget || {}
    },
    engine() {
      // formEngine 作为 prop 传入（优先级最高）
      if (this.formEngine) return this.formEngine
      if (this.renderGlobal) return this.renderGlobal
      return null
    }
  },
  created() {
    this.loadConfig()  // 从 widget 读取已保存的配置
  },
  methods: {
    loadConfig() {
      const saved = this.widgetObj.customComponentConfig || {}
      // 合并到 localConfig
    },
    saveConfig() {
      // 用 $set 写回 widget.customComponentConfig
      this.$set(this.widgetObj, 'customComponentConfig', { ...this.localConfig })
    }
  }
}
```

> **坑1：** 不要在 computed 里用 `$set`（副作用），会导致无限循环甚至页面崩溃。用 data + methods 代替。
> **坑2：** `formEngine` 在 setting.vue 中是通过 **prop** 传入的（不是 inject），inject `renderGlobal` 在设计器右侧面板不一定有。
> **坑3：** 配置直接存在 `customComponentConfig` 根级别（如 `{ dataSource, xField, yField }`），不要嵌套 `{ chartConfig: { ... } }`，否则 edit/read/ide.vue 读取路径要一致。
> **坑4：** inject 声明必须带 `{ default: null }`，不能用数组形式 `inject: ['xxx']`，否则找不到 provide 时组件静默崩溃不渲染。

### 4.2 获取子表列表和字段

```javascript
// 获取所有子表
subTableList() {
  if (!this.engine || !this.engine.formDataControl) return []
  const allItems = this.engine.formDataControl.allTileFormItemList || []
  return allItems.filter(item => item.componentType === 'FORM_WIDGET_SON_TABLE')
}

// 获取子表下的字段
availableFields() {
  const allItems = this.engine.formDataControl.allTileFormItemList || []
  const tableUuid = this.localConfig.dataSource
  // 方式1：通过 isInTable + tableUuid 关联
  const fields = allItems.filter(item =>
    item.isInTable && item.tableUuid === tableUuid &&
    item.componentType !== 'FORM_WIDGET_SON_TABLE'
  )
  if (fields.length > 0) return fields.filter(f => f.label)
  // 方式2：从子表的 sonTableColumns 获取
  const table = this.subTableList.find(t => t.uuid === tableUuid)
  if (table?.sonTableColumns) return table.sonTableColumns.filter(col => col.label)
  return []
}
```

---

## 五、Edit/Read/IDE 组件

### 5.1 核心原则

| 场景 | 功能 | 注意 |
|------|------|------|
| **edit.vue** | 前台编辑态，渲染真实数据 | 不要显示配置界面！只渲染图表 |
| **read.vue** | 前台只读态，渲染真实数据 | 同 edit，纯展示 |
| **ide.vue** | 设计器预览，用模拟数据 | 读取 customComponentConfig 显示预览 |
| **setting.vue** | 设计器右侧配置面板 | 写入 customComponentConfig |

### 5.2 读取配置（edit/read/ide 通用）

```javascript
// 直接从 customComponentConfig 读取（不要嵌套 .chartConfig）
computed: {
  chartConfig() {
    return this.widget.customComponentConfig || {}
  },
  isConfigured() {
    const c = this.chartConfig
    return !!(c.dataSource && c.xField && c.yField)
  }
}
```

> **坑：** setting.vue 存储结构和 edit/read/ide 读取结构必须一致！如果 setting 存 `{ dataSource, xField }`，那 edit 就读 `customComponentConfig.dataSource`，不要读 `customComponentConfig.chartConfig.dataSource`。

### 5.3 获取子表真实数据（edit/read）

```javascript
tableData() {
  if (!this.chartConfig.dataSource || !this.formData) return []
  const sourceId = this.chartConfig.dataSource
  // 通过 uuid 找到子表的 code
  const allItems = this.formEngine?.formDataControl?.allTileFormItemList || []
  const table = allItems.find(item => item.uuid === sourceId)
  const code = table ? table.code : sourceId
  // formData 中子表数据的 key 是 code
  return this.formData[code] || this.formData[sourceId] || []
}
```

---

## 六、本地调试（Debug）

### 6.1 前置条件

1. **HTTPS 证书** — `https/server.key` + `https/server.crt` 必须存在
2. **package.json** 中必须有 `"templateType": "FORM_COMPONENT"`
3. **vue.config.js** 中不能有 `pages` 配置

### 6.2 调试步骤

```bash
npm run serve    # 先启动本地 HTTPS 服务（https://localhost:8080/）
npm run debug    # 再启动 debug（打开 Chromium）
```

Debug 参数：
- 调试模式：**本地调试**
- 目标环境：**平台**（设计态）或 **应用**（运行态）
- 本地服务地址：`https://localhost:8080/`（注意是 HTTPS！）
- 目标线上环境地址：平台 → `https://xxx/platform/`，应用 → `https://xxx/app/`
- 租户ID / 应用ID：从平台获取

### 6.3 Debug 原理

Debug 模式通过 Puppeteer 打开 Chromium，注入本地的 `chunk-vendors.js` 和 `app.js` 到目标平台页面中。注入后调用 `Vue.use()` 注册组件，再通过 `refreshGroupWidgetList` 事件刷新组件列表。

> **坑1：** 登录后必须 **F5 刷新页面**，组件才会注入。
> **坑2：** `df-apaas-cli debug` 进程退出后 Chromium 会关闭（Puppeteer 没有 keep-alive）。
> **坑3：** 如果页面加载超过 30 秒会超时崩溃，需要增加 timeout。

---

## 七、常见错误速查

| 错误 | 原因 | 解决 |
|------|------|------|
| 组件上传后不可见 | build 格式不对 | 用 `--target lib` 构建 |
| zip 上传失败 | 缺少 apaas.json | zip 根目录必须有 apaas.json 和 static/ |
| `Cannot read 'includes'` | widget.config.js 缺少标准 editor 配置项 | 保留所有标准 editor config |
| Setting 面板不显示 | inject 没有 default 导致组件崩溃 | inject 必须用 `{ default: null }` |
| 配置保存后丢失 | customComponentConfig 未在 widget 模板中声明 | widget.config.js 中加 `customComponentConfig: {}` |
| 配置保存后丢失（2） | setting 存的路径和 edit 读的路径不一致 | 统一存取路径 |
| "配置不完整" 阻止保存 | customComponentConfig 包含空字符串 | 默认值用 `{}` 不要带空字段 |
| 前台显示配置界面 | edit.vue 混入了配置 UI | edit 只渲染图表，配置 UI 放 setting |
| Debug 页面白屏 | 组件注入导致 JS 错误 | 组件代码中加 try-catch，检查 Console |
| Debug 浏览器关闭 | Puppeteer 进程退出 | 需要 `await browser.on('disconnected')` 保活 |
| Debug 组件列表没有新组件 | 注入时序问题 | 多次 emit `refreshGroupWidgetList` |

---

## 八、FormEngine API 速查

```javascript
// 通过 FormWidgetMixin（edit/read/ide 中）
this.formEngine          // = this.renderGlobal（inject 获取）
this.formValue           // 当前组件绑定字段的值
this.formData            // 整个表单的数据对象
this.widget              // 当前组件的配置对象
this.renderScene         // 渲染场景：edit/read/ide/list/print/search/searchIde

// 获取所有表单项（平铺列表）
this.formEngine.formDataControl.allTileFormItemList

// 子表判断
item.componentType === 'FORM_WIDGET_SON_TABLE'

// 子表字段判断
item.isInTable === true && item.tableUuid === '子表uuid'

// 子表数据（在 formData 中，key 是子表的 code）
this.formData['子表code']
```
