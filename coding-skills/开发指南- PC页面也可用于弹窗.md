# aPaaS 自定义页面开发指南

## 场景说明

这是一个 aPaaS 平台自定义页面，打包为 UMD 组件后部署。它既可以作为独立菜单页面使用，也可以被平台弹窗（x-lov）引用。当被弹窗引用时，弹窗点击"确定"会调用组件实例的 `getSelectedData()` 方法获取选中数据。

技术栈：Vue 2.7 + Element UI 2.x + Node 16.x

---

## 完整项目结构

```
your-project-name/
├── src/
│   ├── index.js                          # UMD 入口（必须）
│   ├── apaas.json                        # 平台路由配置（必须）
│   ├── api/index.js                      # 接口定义
│   ├── form-page/
│   │   └── your-component.vue            # 核心业务组件
│   ├── form-page-local/                  # 国际化（必须，即使为空）
│   │   ├── index.js
│   │   ├── zh-CN/index.js
│   │   └── en-US/index.js
│   └── mixin/                            # 可选的 mixin
│       └── custom-permissions.mixin.js
├── preview/                              # 本地预览环境
│   ├── index.html
│   ├── main.js
│   ├── App.vue
│   └── mock-api.js
├── public/
│   └── form-page/.gitkeep
├── https/                                # HTTPS 证书（serve 模式需要，preview 不需要）
│   ├── server.key
│   └── server.crt
├── package.json
├── vue.config.js
├── babel.config.js
├── jsconfig.json
└── .gitignore
```

---

## 每个文件的完整内容

### package.json

注意：`name` 要改成你的项目名，`build` 使用 `df-apaas-cli build`。

```json
{
  "name": "your-project-name",
  "version": "1.0.0",
  "engines": {
    "node": "16.x"
  },
  "templateType": "MENU_PAGE",
  "private": true,
  "scripts": {
    "lint": "vue-cli-service lint",
    "preview": "VUE_APP_PREVIEW=true vue-cli-service serve preview/main.js",
    "serve": "vue-cli-service serve src/index.js",
    "debug": "df-apaas-cli debug",
    "build": "df-apaas-cli build"
  },
  "dependencies": {
    "core-js": "3.8.3",
    "element-ui": "^2.15.14",
    "vue": "2.7.14"
  },
  "devDependencies": {
    "@babel/core": "7.12.16",
    "@babel/eslint-parser": "7.12.16",
    "@vue/cli-plugin-babel": "5.0.0",
    "@vue/cli-plugin-eslint": "5.0.0",
    "@vue/cli-service": "5.0.8",
    "dart-sass": "1.25.0",
    "eslint": "7.32.0",
    "eslint-plugin-vue": "8.0.3",
    "sass": "1.85.1",
    "sass-loader": "8.0.2",
    "vue-template-compiler": "2.7.14"
  },
  "eslintConfig": {
    "root": true,
    "env": { "node": true },
    "extends": ["plugin:vue/essential", "eslint:recommended"],
    "parserOptions": { "parser": "@babel/eslint-parser" },
    "rules": {}
  },
  "browserslist": ["> 1%", "last 2 versions", "not dead", "Chrome 40.0", "ie >= 11"]
}
```

### vue.config.js

```js
const { defineConfig } = require('@vue/cli-service')
const fs = require('fs')
const path = require('path')
const apaasJson = require('./src/apaas.json')

const isPreview = process.env.VUE_APP_PREVIEW === 'true'

module.exports = defineConfig({
  transpileDependencies: true,
  productionSourceMap: false,
  devServer: {
    host: '0.0.0.0',
    port: isPreview ? 8090 : 8080,
    hot: true,
    allowedHosts: 'all',
    // 预览模式不需要 HTTPS 证书
    ...(isPreview ? {} : {
      https: { key: fs.readFileSync('./https/server.key'), cert: fs.readFileSync('./https/server.crt') }
    }),
    headers: { 'Access-Control-Allow-Origin': '*' },
    client: { overlay: false },
    proxy: {
      '/custom': {       // 改成你的后端接口前缀
        target: 'http://localhost:9092',  // 改成你的后端地址
        changeOrigin: true
      }
    }
  },
  configureWebpack: (config) => {
    if (isPreview) {
      delete config.output.library
      delete config.output.libraryTarget
    } else {
      config.output.library = apaasJson.outputName
      config.output.libraryTarget = 'umd'
    }
  },
  chainWebpack: (config) => {
    if (isPreview) {
      config.plugin('html').tap(args => {
        args[0].template = path.resolve(__dirname, 'preview/index.html')
        return args
      })
    }
  },
  css: {
    loaderOptions: {
      sass: { implementation: require('sass') }
    }
  }
})
```

### babel.config.js

```js
module.exports = {
  presets: ['@vue/cli-plugin-babel/preset']
}
```

### jsconfig.json

```json
{
  "compilerOptions": {
    "target": "es5",
    "module": "esnext",
    "baseUrl": "./",
    "moduleResolution": "node",
    "paths": { "@/*": ["src/*"] },
    "lib": ["esnext", "dom", "dom.iterable", "scripthost"]
  }
}
```

---

### src/apaas.json（平台配置）

**改 3 处**：router 的 key/name/path 改成你的组件名，outputName 改成你的项目名。

```json
{
  "entry": "index.js",
  "templateType": "MENU_PAGE",
  "router": {
    "apaas-custom-your-name": {
      "name": "apaas-custom-your-name",
      "path": "apaas-custom-your-name"
    }
  },
  "customWidgetList": [],
  "copyAssets": ["public/form-page/your-project-name"],
  "outputName": "your-project-name"
}
```

### src/index.js（UMD 入口）

这是平台加载组件的入口。**必须**做两件事：注册全局组件 + 挂载到 window Symbol。

```js
import "./form-page-local/index.js";
import YourComponent from "./form-page/your-component.vue";

const install = function (Vue) {
  // 1. 注册为全局 Vue 组件（平台路由渲染用）
  Vue.component("apaas-custom-your-name", YourComponent);

  // 2. 挂载到 window Symbol（平台弹窗通过这个获取组件定义）
  //    弹窗点击"确定"时，平台会调用实例的 getSelectedData() 方法
  window[Symbol.for("apaas-custom-your-name")] = YourComponent;
};

export default { install };
```

### src/api/index.js（接口定义）

```js
const api = {
  YOUR_API_NAME: {
    url: `/custom/your/endpoint`,    // 以 /custom/ 开头
    method: "POST",
    disableSuccessMsg: true,         // 禁止平台弹出默认成功提示
  },
};

export default api;
```

### src/form-page-local/（国际化 - 必须存在，即使为空）

**src/form-page-local/index.js**
```js
import zhLocaleModule from './zh-CN/index.js'
import enLocaleModule from './en-US/index.js'

if (window.df.getI18n().mergeLocaleMessage) {
  window.df.getI18n().mergeLocaleMessage('zh-CN', zhLocaleModule)
  window.df.getI18n().mergeLocaleMessage('en-US', enLocaleModule)
}
```

**src/form-page-local/zh-CN/index.js**
```js
export default {
  formPage: {},
};
```

**src/form-page-local/en-US/index.js**
```js
export default {
  formPage: {},
};
```

---

### src/form-page/your-component.vue（核心业务组件模板）

以下是一个带筛选 + 表格 + 多选 + 弹窗返回数据的完整模板。你需要根据业务修改筛选区域、表格列、接口。

```vue
<template>
  <div class="your-component-name">

    <!-- 筛选区（根据业务自定义） -->
    <div class="filter-area">
      <!-- 这里放你的筛选控件 -->
    </div>

    <!-- 查询 / 重置 -->
    <div class="filter-actions">
      <el-button type="primary" size="small" @click="handleQuery">查询</el-button>
      <el-button size="small" @click="handleReset">重置</el-button>
    </div>

    <!-- 已选提示条（弹窗选择场景需要） -->
    <div class="selected-bar">
      <span class="selected-bar-title">
        已选数据
        <span v-if="selectedRows.length" class="selected-badge">{{ selectedRows.length }}</span>
      </span>
      <template v-if="selectedRows.length === 0">
        <span class="selected-bar-empty">暂未选择</span>
      </template>
      <template v-else>
        <div class="selected-bar-tags">
          <span v-for="row in selectedRows" :key="row.id" class="bar-tag">
            <span class="bar-tag-label">{{ row.name || row.id }}</span>
            <span class="bar-tag-close" @click="removeSelected(row)">×</span>
          </span>
        </div>
        <span class="bar-clear" @click="clearAllSelected">清空</span>
      </template>
    </div>

    <!-- 数据表格 —— 直接用 el-table，不要用 x-http-block-table -->
    <div class="table-wrapper" style="overflow-y:auto; flex:1; min-height:0;">
      <el-table
        ref="elTable"
        :data="tableConfig.tableData || []"
        border
        style="width:100%;"
        :max-height="tableConfig.maxHeight || undefined"
        @selection-change="handleSelectionChange"
      >
        <el-table-column type="selection" width="50" fixed />
        <el-table-column type="index" label="序" width="50" fixed :index="indexStart" />
        <el-table-column
          v-for="col in visibleCols"
          :key="col.columnKey"
          :prop="col.prop"
          :label="col.label"
          :min-width="col.minWidth || 120"
          show-overflow-tooltip
        />
      </el-table>
      <el-pagination
        v-if="tableConfig.pagination"
        style="margin-top: 8px; text-align: right; padding: 4px 0"
        :current-page="tableConfig.pagination.currentPage"
        :page-size="tableConfig.pagination.pageSize"
        :total="tableConfig.pagination.total"
        :page-sizes="[10, 50, 100]"
        layout="total, sizes, prev, pager, next"
        @size-change="onSizeChange"
        @current-change="onCurrentPageChange"
      />
    </div>

  </div>
</template>

<script>
import Api from '../api'

export default {
  name: 'YourComponentName',

  data() {
    return {
      selectedRows: [],

      tableConfig: {
        maxHeight: '500',
        colConfigs: [
          // 按需定义列，displayFlag 控制是否显示
          { prop: 'name', columnKey: 'name', displayFlag: true, label: '名称', minWidth: 150 },
          { prop: 'code', columnKey: 'code', displayFlag: true, label: '编码', minWidth: 150 },
          // ... 更多列
        ],
        tableData: [],
        pagination: {
          currentPage: 1,
          pageSize: 10,
          total: 0
        }
      }
    }
  },

  computed: {
    visibleCols() {
      return (this.tableConfig.colConfigs || []).filter(c => c.displayFlag)
    },
    indexStart() {
      const p = this.tableConfig.pagination
      if (!p) return 1
      return (p.currentPage - 1) * p.pageSize + 1
    }
  },

  created() {
    this.loadTableData()
  },

  methods: {
    /**
     * 加载分页数据
     * 注意：$request 不是标准 Promise，用 .asyncThen() / .asyncErrorCatch()
     */
    loadTableData() {
      const { currentPage, pageSize } = this.tableConfig.pagination
      this.$request({
        ...Api.YOUR_API_NAME,
        params: {
          page: currentPage,
          pageSize,
          // ... 你的筛选参数
        }
      })
        .asyncThen((resp) => {
          const list = resp && resp.data ? resp.data : []
          const total = (resp && resp.total) ? resp.total : 0
          this.$set(this.tableConfig, 'tableData', list)
          this.$set(this.tableConfig.pagination, 'total', total)
          // 翻页后恢复已选勾选状态
          const selectedIds = this.selectedRows.map(r => r.id)
          if (selectedIds.length) {
            this.reapplySelection(selectedIds)
          }
        })
        .asyncErrorCatch((error) => {
          console.error('加载数据失败:', error)
        })
    },

    handleQuery() {
      this.$set(this.tableConfig.pagination, 'currentPage', 1)
      this.loadTableData()
    },

    handleReset() {
      // 清空筛选条件...
      this.$set(this.tableConfig.pagination, 'currentPage', 1)
      this.loadTableData()
    },

    onSizeChange(size) {
      this.$set(this.tableConfig.pagination, 'pageSize', size)
      this.$set(this.tableConfig.pagination, 'currentPage', 1)
      this.loadTableData()
    },

    onCurrentPageChange(page) {
      this.$set(this.tableConfig.pagination, 'currentPage', page)
      this.loadTableData()
    },

    /**
     * 跨页多选：el-table 选中变化时，保留其他页已选 + 合并当前页选中
     */
    handleSelectionChange(rows) {
      const currentPageIds = new Set((this.tableConfig.tableData || []).map(r => r.id))
      const otherPageRows = this.selectedRows.filter(r => !currentPageIds.has(r.id))
      this.selectedRows = [...otherPageRows, ...(Array.isArray(rows) ? rows : [])]
    },

    /**
     * 翻页后恢复已选行的勾选状态
     */
    reapplySelection(selectedIds) {
      this.$nextTick(() => {
        const table = this.$refs.elTable
        if (!table) return
        table.clearSelection()
        ;(this.tableConfig.tableData || []).forEach(row => {
          if (selectedIds.includes(row.id)) {
            table.toggleRowSelection(row, true)
          }
        })
      })
    },

    removeSelected(row) {
      this.selectedRows = this.selectedRows.filter(r => r.id !== row.id)
      const table = this.$refs.elTable
      const tableData = this.tableConfig.tableData || []
      const found = tableData.find(r => r.id === row.id)
      if (found && table) {
        table.toggleRowSelection(found, false)
      }
    },

    clearAllSelected() {
      this.selectedRows = []
      const table = this.$refs.elTable
      if (table) table.clearSelection()
    },

    /**
     * 【关键】供弹窗"确定"按钮调用，返回当前所有已选行数据
     * 平台弹窗会调用 组件实例.getSelectedData() 来获取结果
     */
    getSelectedData() {
      return this.selectedRows
    }
  }
}
</script>

<style lang="scss">
.your-component-name {
  height: 100%;
  width: 100%;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px 16px;
  overflow: hidden;

  .filter-actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    flex-shrink: 0;
  }

  .selected-bar {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    flex-shrink: 0;
    padding: 6px 10px;
    background: #f0f7ff;
    border: 1px solid #b3d8ff;
    border-radius: 4px;
    font-size: 13px;
    min-height: 36px;
    max-height: 72px;
    overflow-y: auto;

    .selected-bar-title {
      font-weight: 600;
      color: #303133;
      white-space: nowrap;
      flex-shrink: 0;

      .selected-badge {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 18px;
        height: 18px;
        padding: 0 5px;
        background: #409eff;
        color: #fff;
        border-radius: 9px;
        font-size: 11px;
        font-weight: 600;
        margin-left: 4px;
      }
    }

    .selected-bar-empty { color: #c0c4cc; font-style: italic; }

    .selected-bar-tags {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
      flex: 1;

      .bar-tag {
        display: inline-flex;
        align-items: center;
        gap: 3px;
        height: 22px;
        padding: 0 6px;
        background: #fff;
        border: 1px solid #b3d8ff;
        border-radius: 3px;
        font-size: 12px;
        color: #409eff;

        .bar-tag-label { max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .bar-tag-close { cursor: pointer; color: #909399; &:hover { color: #f56c6c; } }
      }
    }

    .bar-clear {
      margin-left: auto;
      color: #909399;
      cursor: pointer;
      font-size: 12px;
      white-space: nowrap;
      flex-shrink: 0;
      &:hover { color: #f56c6c; }
    }
  }
}

// 弹窗场景下的适配（平台弹窗会套一层 .x-lov-modal）
.x-lov-modal {
  .your-component-name {
    // 弹窗内高度有限，按需压缩各区域
  }
}
</style>
```

---

### preview/（本地预览环境）

**preview/index.html**
```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>本地预览</title>
</head>
<body>
  <div id="app"></div>
</body>
</html>
```

**preview/App.vue**
```vue
<template>
  <div style="min-height: 100vh;">
    <apaas-custom-your-name />
  </div>
</template>

<script>
export default { name: 'PreviewApp' }
</script>
```

**preview/main.js**
```js
import Vue from 'vue'
import ElementUI from 'element-ui'
import 'element-ui/lib/theme-chalk/index.css'

import { installMockRequest } from './mock-api'
import YourComponent from '../src/form-page/your-component.vue'
import App from './App.vue'

Vue.use(ElementUI)

// 注入 $request mock（通过 devServer proxy 转发到后端）
installMockRequest(Vue)

// 注册业务组件
Vue.component('apaas-custom-your-name', YourComponent)

new Vue({
  el: '#app',
  render: h => h(App)
})
```

**preview/mock-api.js**

这个文件模拟平台的 `$request` 方法。平台的 `$request` 不是标准 Promise，
它返回一个带 `.asyncThen()` 和 `.asyncErrorCatch()` 的链式调用对象。

```js
/**
 * 模拟平台 $request：通过 devServer proxy 转发到后端
 * 支持 .asyncThen().asyncErrorCatch() 链式调用（与平台行为一致）
 */
export function installMockRequest(Vue) {
  Vue.prototype.$request = function (config) {
    const ctrl = {}

    const promise = fetch(config.url, {
      method: (config.method || 'GET').toUpperCase(),
      headers: { 'Content-Type': 'application/json' },
      body: config.params != null ? JSON.stringify(config.params) : undefined
    }).then(function (res) {
      if (!res.ok) throw new Error('HTTP ' + res.status)
      return res.json()
    })

    ctrl.asyncThen = function (onSuccess, onError) {
      promise.then(onSuccess).catch(onError || function () {})
      return ctrl
    }

    ctrl.asyncErrorCatch = function (onError) {
      promise.catch(onError)
      return ctrl
    }

    return ctrl
  }
}
```

---

## 关键规则（必读）

### 1. 不要使用 x-http-block-table

平台有一个 `<x-http-block-table>` 组件，但部署后行为和样式与本地不一致。
**必须直接使用 Element UI 的 `<el-table>` + `<el-pagination>`**。

### 2. $request 不是 Promise

平台注入的 `this.$request()` 返回的不是标准 Promise，不能用 `.then()` / `.catch()`。
必须用：
```js
this.$request({ url, method, params })
  .asyncThen((resp) => { /* 成功 */ })
  .asyncErrorCatch((error) => { /* 失败 */ })
```

### 3. getSelectedData() 方法

如果组件会被弹窗引用（x-lov 场景），**必须**实现 `getSelectedData()` 方法，
返回用户选中的行数据数组。平台弹窗点击"确定"时会调用这个方法。

### 4. window Symbol 注册

`src/index.js` 中必须通过 `window[Symbol.for("组件名")]` 注册组件，
这是平台弹窗发现自定义组件的约定。

### 5. 跨页多选

el-table 翻页会清空选中状态，需要自己维护 `selectedRows` 数组：
- `handleSelectionChange`：合并当前页选中 + 其他页已选
- `reapplySelection`：翻页后用 `toggleRowSelection` 恢复勾选
- 数据更新用 `this.$set()` 确保响应式

### 6. 弹窗高度适配

组件会被嵌入弹窗，空间有限：
- 用 `flex` 布局，表格区域用 `flex: 1` 填充剩余空间
- 筛选区域限制 `max-height`
- 已选提示条限制 `max-height: 72px` + `overflow-y: auto`
- 通过 `.x-lov-modal .your-component` 选择器覆写弹窗内样式

### 7. 构建

```bash
npm run build
```
产物是根目录下的 `your-project-name.zip`，上传到平台即可。

### 8. 本地预览

```bash
npm run preview
# 访问 http://localhost:8090
```
需要后端服务在 `localhost:9092`（或你 proxy 配置的地址）运行。

---

## 新建项目的操作步骤

1. 复制本项目整个目录
2. 改 `package.json` 的 `name`
3. 改 `src/apaas.json` 的 `router` 名称和 `outputName`
4. 改 `src/index.js` 的组件注册名和 Symbol 名
5. 在 `src/form-page/` 下创建你的 .vue 文件
6. 在 `src/api/index.js` 定义接口
7. 改 `preview/main.js` 和 `preview/App.vue` 引用你的组件
8. 改 `vue.config.js` 的 proxy 指向你的后端
9. `npm install` → `npm run preview` 本地调试
10. `npm run build` 打包 → 上传 zip 到平台
