# 自开发文档

## 安装依赖

```bash
df-apaas-cli install
```

## 本地调试

```bash
# 第一步使用终端执行
npm run serve
# 第二步 新打开终端 执行
npm run debug
```

## `apaas.json` 介绍

1. `apaas.json` 将作为脚手架打包的配置文件，确保 `src` 目录下有此文件

```ts
type TemplateType = "MENU_PAGE" | "FORM_COMPONENT" | "LIST_VIEW" | "PAGE_LAYOUT";
type StartsWithApaasCustom = `apaas-custom-${string}`;
type ApaasRouterConfig<T extends StartsWithApaasCustom> = {
  [K in T]: {
    name: K;
    path: K;
  };
};
type CustomWidget = {
  code: string;
  text: string;
  description: string;
}
type ApaasListConfig = {
  [K in StartsWithApaasCustom] {
    renderLogic: "FORM_LIST_VIEW",
    desc: string;
    status: "ENABLE" | "DISABLE"
  }
}

type ApaasLayoutConfigItem = {
  name: StartsWithApaasCustom;
  desc: string;
  status: "ENABLE" | "DISABLE"
}

type ApaasLayoutConfig = Array<ApaasLayoutConfigItem>;
```

|属性|类型|备注|
|----|----|----|
|entry|string|打包的入口文件|
|templateType|TemplateType|模版类型|
|router|ApaasRouterConfig|菜单页面路由配置|
|customWidgetList|CustomWidget[]|组件配置|
|list|ApaasListConfig|列表视图配置|
|layout|ApaasLayoutConfig|布局配置|
|copyAssets|string[]|将指定目录下的所有文件拷贝到生成文件下的static目录下|
|outputName|string|输出文件名称|

## 自开发页面开发

1. 开发页面组件例如 `form-page/apaas-custom-demo.vue` 文件
2. 将开发的页面组件在入口文件中引入，并在插件中全局注册，注册的组件名字，必须遵循以 `apaas-custom-` 开头
3. 在 `apaas.json` 中的路由配置中写入相关配置，配置类型的泛型 `T` 为注册页面组件名字的联合。例如

  ```js
  Vue.component("apaas-custom-page", Page);
  ```

  ```json
  {
    // ---
    "router": {
      "apaas-custom-page": {
        "name": "apaas-custom-page",
        "path": "apaas-custom-page"
      }
    }
    // ---
  }
  ```

4. 在平台配置中配置一个自开发页面，填入的页面名称 使用的是注册页面组件时的名称
5. 开发人员使用 `df-apaas-cli debug` 命令调试
6. 调试完毕后，使用 `df-apaas-cli build` 命令打包
7. 将打包后的文件上传至自开发管理中，并和应用绑定，发布应用即可让所有用户使用

![img](https://edu.definesys.cn/edu-api/attachments/downloadDocImage?path=media/202308/2023-08-23_101603_093013.png)
![img](https://edu.definesys.cn/edu-api/attachments/downloadDocImage?path=media/202308/2023-08-23_101615_837652.png)
![img](https://edu.definesys.cn/edu-api/attachments/downloadDocImage?path=media/202308/2023-08-23_101624_717403.png)
![img](https://edu.definesys.cn/edu-api/attachments/downloadDocImage?path=media/202308/2023-08-23_101649_481620.png)
![img](https://edu.definesys.cn/edu-api/attachments/downloadDocImage?path=media/202308/2023-08-23_101656_296663.png)
![img](https://edu.definesys.cn/edu-api/attachments/downloadDocImage?path=media/202308/2023-08-23_101703_507293.png)

## 自开发列表视图开发

1. 开发列表视图组件 例如 `form-view/apaas-custom-demo.vue` 文件
2. 将开发的列表视图组件在入口文件中引入，并在插件 `install` 函数中全局注册，注册的组件名字，必须遵循以 `apaas-custom-` 开头
3. 在 `apaas.json` 中的列表视图配置中写入相关配置
4. 在平台配置中配置一个列表视图，填入视图名称 使用的是注册视图组件时的名称
5. 开发人员使用 `df-apaas-cli debug` 命令调试
6. 调试完毕后，使用 `df-apaas-cli build` 命令打包
7. 将打包后的文件上传至自开发管理中，并和应用绑定，发布应用即可让所有用户使用

![img](https://edu.definesys.cn/edu-api/attachments/downloadDocImage?path=media/202308/2023-08-23_111745_405010.png)
![img](https://edu.definesys.cn/edu-api/attachments/downloadDocImage?path=media/202308/2023-08-23_111754_110350.png)
![img](https://edu.definesys.cn/edu-api/attachments/downloadDocImage?path=media/202308/2023-08-23_111804_360910.png)
![img](https://edu.definesys.cn/edu-api/attachments/downloadDocImage?path=media/202308/2023-08-23_111813_590259.png)


### ListEngine 介绍

`ListEngine`，即列表引擎，用来生成 `listEngine` 实例，以及注册列表组件的渲染场景`renderLogic`。在自开发工程中已经将 `ListEngine` 挂载到 `Vue` 上了，方便开发者直接使用

#### `listEngine` 实例的属性和方法

|属性|类型|说明|
|----|----|----|
|engineContext|object|实例上下文|
|vm|Object|组件的this|
|listDataControl|object|列表数据控制器，用来存储列表相关数据|
|actionControl|object|列表动作控制器，用来执行列表相关方法|

#### `listEngine` 实例的属性和方法

|属性|类型|说明|默认值|
|----|----|----|-----|
|formId|string|表单ID||
|appId|string|应用ID||
|menuId|string|菜单ID||
|tabId|string|列表tabId||
|tenantId|string|租户ID||
|title|string|表单名称||
|viewType|string|视图类型|LIST_VIEW|

#### `listEngine.listDataControl` 列表数据控制器

|属性|类型|说明|
|----|----|----|
|listPage|object|列表页面配置|
|queryLists|object|列表配置的查询面板|
|tileFormComponent|object|列表配置的列表字段的组件配置|
|tableConfig|object|列表字段表格配置|
|listColDisplayConfig|object|表格列显示配置|
|statisticalFooter|object|表格底部相关配置|
|selectedFormData|array|表格选中的数据|
|listOperationButtons|array|列表操作列按钮数组|
|listButton|array|列表按钮数据|
|renderListButton|array|真正渲染的列表按钮|
|batchButton|array|批量操作按钮|
|shareConfig|object|分享表单配置|
|businessComponents|array|所属表单的组件列表|
|systemComps|array|所属表单的系统字段列表|
|personalSearch|array|个人的查询器列表|
|systemSearch|array|系统查询器列表|
|listAdvanceSearch|array|系统+个人的查询器列表|
|virtualAdvanceSearch|object|暂存的查询器配置|
|allListAdvanceSearch|array|系统+个人+暂存的查询器列表|
|queryConditions|array|查询面板列表|
|searchList|array|查询面板组件渲染构造的数据|
|selectorFilterConditionList|array|查询面板查询时传给后端根据searchList构造的数据|
|searchComponentConfig|array|查询面板组件渲染时的组件名和表单组件类型的对应关系数组|
|filterConditionGroup|array|查询器查询时传给后端构造的数据|
|showPageListLoading|boolean|是否显示列表数据加载loading|
|pageListNetworkError|boolean|列表数据加载是否出现网络错误|
|pageListLoading|boolean|列表数据加载是否正在加载|
|excelImportConfig|object|列表导入配置|
|excelExportConfig|object|列表导出配置|
|destroyVirtualAdvanceSearch|function|销毁暂存的查询器列表|

#### `listEngine.actionControl` 介绍

`actionControl` 为动作控制器，列表中的所有的动作都是通过 `actionControl` 来执行

|属性|类型|说明|
|----|----|----|
|actionMap|Map|实例ActionMap|
|engine|ListEngine|listEngine实例|
|registerAction(actionCode, action)|function|actionCode动作编码，action动作方法，注册局部动作|
|getAction(actionCode)|function|actionCode动作编码，获取指定动作编码的局部动作或全局动作|
|executeActionWithPromise(actionCode, event)|function|actionCode动作编码，event动作的event，执行异步动作，返回Promise|
|executeActionWithSync(actionCode, event)|function|actionCode动作编码，event动作的event，执行同步动作，返回当前注册动作的返回值|

```js
// ActionControl 使用实例
// 1. 注册一个 INIT_MENU_TREE_ACTION 的异步动作 (异步动作指返回一个异步的动作，如返回一个 Promise) 可以使用如下方式进行注册

// 注册的动作中默认会传递两个参数，
// `engine`为`ListEngine`实例，
// `event`为动作事件，可以存放一些其他参数，本次示例中在`event`中存储了`appId`的参数
this.listEngine.actionControl.registerAction('INIT_MENU_TREE_ACTION', (engine, event) => {
  return new Promise((resolve, reject) => {
    const { appId } = event
    const request = { ...apis.APP_ENGINE_HOME_GET_MENU_TREE }
    request.params = {
      appId
    }
    // 调用网络请求this.$request(request)
      .asyncThen(
        (resp) => {
          resolve(resp)
        },
        (error) => {
          reject(error)
        }
      )
      .asyncErrorCatch((error) => {
        reject(error)
      })
  })
})


// 执行名为 INIT_MENU_TREE_ACTION的异步动作，可以使用如下方式
// 执行异步动作
this.listEngine.actionControl
  .executeActionWithPromise('INIT_MENU_TREE_ACTION', {
    appId: this.appId
  })
  .then((resp) => {
    console.log(resp)
  })
  .catch((error) => {
    console.log(error)
  })

// 2. 注册一个名为 `REVERSE_TABLE_DATA` 的同步动作，(同步动作指动作是同步执行，返回动作的返回值)，使用如下方式注册
this.listEngine.actionControl.registerAction('REVERSE_TABLE_DATA', (engine, event) => {
  const { reverseData, key } = event
  const tableConfig = engine.listDataControl.tableConfig
  reverseData.forEach((reverseDataItem) => {
    tableConfig.tableData.forEach((item) => {
      if (item[key] === reverseDataItem[key]) {
        item.selected = true
      }
    })
  })
  return true
})
// 执行名字为REVERSE_TABLE_DATA的同步动作，可以使用如下方式
const flag = this.listEngine.actionControl.executeActionWithSync('REVERSE_TABLE_DATA',
{
  reverseData: this.reverseData,
  key: 'documentId'
}
)
// console.log(flag)
```

#### 默认的动作

|Action|event参数|动作类型|说明|
|----|----|----|----|
|INIT_LIST_CONFIG_ACTION|tabId, userId|异步|查询列表配置接口|
|INIT_LIST_PAGE_BUTTON_ACTION|formId, tabId, userId|异步|查询列表按钮接口|
|QUERY_SHARE_STATUS_ACTION|tabId,formId,dataType: 'FORM'|异步|查询分享表单配置接口|
|QUERY_PRESONAL_ADVANCE_SEARCH_ACTION|formId, tabId|异步|查询个人查询器列表接口|
|QUERY_PRESONAL_ADVANCE_SEARCH_DETAIL|id: 个人查询器id, formId|异步|查询个人查询器明细接口|
|QUERY_TABLE_DATA||异步|查询列表数据接口|
|QUERY_STATISTICS_VALUE_COLUME|uuid:数据统计组件的uuid, formId, documentIdList:要查询的documentId列表|异步|查数据统计组件的值接口|
|QUERY_CALC_TABLE_DATA|formId, tabId, documentIdList|异步|处理虚拟字段的样式模版接口|
|QUERY_OPERATION_COLUMN|formId, tabId, documentIds:要查询的documentId列表, displayLocation: 'LIST_OPERATION_BAR'|异步|查询列表操作列数据接口|
|QUERY_STATISTICAL_TABLE|formId,tabId, selectorFilterConditionList: engine.listDataControl.selectorFilterConditionList, filterConditionGroup: engine.listDataControl.filterConditionGroup, aggregates: engine.listDataControl.statisticalFooter.statisticalTypes|异步|查询列表统计数据接口|
|FORM_EDITOR_QUERY_FORM_COMPONENTS_BY_BLACK|formId, systemField:true,|异步|查询表单组件接口|
|QUERY_LIST_TABLE_DATA||同步|查询列表数据并二次处理数据|
|QUERY_LIST_TABLE_FOOTER_DATA||同步|查询列表统计数据并二次处理数据|
|DO_LIST_SEARCH||同步|查询列表数据（同步执行QUERY_LIST_TABLE_DATA和QUERY_LIST_TABLE_FOOTER_DATA）|
|INIT_LIST_DATA_ACTION||同步|初始化的时候查询列表数据|
|REFRESH_LIST_ACTION||同步|刷新列表数据|
|DO_SPREAD_LIST||同步|展开收起操作按钮点击动作|
|DO_REFRESH_LIST||同步|刷新按钮点击动作|
|DO_ADVANCE_SEARCH|advanceSearchIndex:Number 新增时为-1，编辑时为选中的查询器的index advanceSearchId:String 查询器的id，新增时可不传|同步|打开查询器抽屉动作|
|DO_IMPORT_LIST||同步|导入按钮点击动作|
|DO_EXPORT_LIST||同步|导出按钮点击动作|
|DO_DATA_TEMPLATE|el: 点击的dom|同步|数据模版按钮点击动作|
|DO_TABLE_COLUMNS_CONFIG|el: 点击的dom|同步|字段设置按钮点击动作|
|DO_SHARE||同步|分享表单按钮点击动作|
|LIST_TABLE_RESIZABLE_CHANGE|resizeWidth:Number 拖拽的宽度，columnIndex:Number 拖拽列的index|同步|列表表格列宽度拖拽执行动作|
|LIST_CALC_TABLE_HEIGHT||同步|重新计算表格高度并渲染动作|
|DO_OPEN_CURRENT_ASSO|column.property:关联表单组件的uuid, row:Object 表格行数据|同步|打开分享表单抽屉动作|
|DO_OPEN_ROW_FORM_DRAWER|column.property:当前点击的组件的uuid,e:Object 表格行数据|同步|打开查看数据详情抽屉动作|
|DO_LIST_ADD_CLICK||同步|打开数据新增弹窗动作 // 自开发工程局部没注册，部署到应用里面就有了|
|DO_LIST_CUSTOM_BUTTON_ACTION|button:Object 按钮配置,row:Object 表格行数据|同步|列表操作列按钮点击动作|
|DO_LIST_BATCH_BUTTON_ACTION|button:Object 按钮配置|同步|批量按钮点击动作|
|DO_CUSTOM_BUTTON_CLICK|buttonConfig:Object 按钮配置|同步|列表自定义按钮点击动作|
|DO_LIST_BATCH_DELTE_DATA_ACTION||同步|批量删除按钮点击动作|
|DO_LIST_COPY_NEW_DATA_ACTION||同步|复制新建按钮点击动作|
|DO_DELETE_DATA_BY_DOCUMENTID|documentId|同步|删除指定documentId的数据动作|
|DO_REFRESH_MENU||同步|刷新整个菜单动作|

#### 默认列表相关组件介绍

##### `x-list-view`

`apaas` 默认布局组件，采用上中下布局，按照头部操作按钮-查询面板-列表表格的顺序渲染，默认提供了 `listEngine`

```js
provide() {
  return {
    listEngine: this.listEngine
  }
}
```

![img](https://edu.definesys.cn/edu-api/attachments/downloadDocImage?path=media/202308/2023-08-23_113105_775984.png)

|props|说明|类型|可选值|默认值|
|----|----|----|----|----|
|listEngine|列表引擎|ListEngine|||
|showListHeaderDrawer|是否显示顶部批量操作按钮抽屉|boolean||true|

|slots|说明|
|----|----|
|listHeader|头部操作按钮部分|
|listSearch|查询面板部分|
|listTable|列表表格部分|
|listHeaderDrawer|顶部批量操作按钮抽屉|

##### `x-list-header`

`apaas` 默认头部组件，包括头部右侧按钮部分，可通过插槽自定义 `title` 部分和 `button` 部分 注意：使用该组件必须在父组件中提供`listEngine`

![img](https://edu.definesys.cn/edu-api/attachments/downloadDocImage?path=media/202308/2023-08-23_113319_476163.png)

|slots|说明|
|----|----|
|title|左侧标题部分|
|button|右侧按钮部分|

##### `x-list-search`

`apaas` 默认查询面板组件，包括自定义模块、查询面板、查询器等部分。 注意：使用该组件必须在父组件中提供 `listEngine`

![img](https://edu.definesys.cn/edu-api/attachments/downloadDocImage?path=media/202308/2023-08-23_113438_316113.png)

##### `x-list-table`

`apaas` 默认列表表格部分，包括自定义模块部分和列表表格部分。 可以通过 `customHeadSlot` 插槽来自定义列表表格头部。 注意：使用该组件必须在父组件中提供 `listEngine`

|slots|说明|
|----|----|
|customHeadSlot|自定义列表表格头部|

##### `x-list-header-drawer`

`apaas` 默认顶部批量操作按钮抽屉，用来显示批量操作等按钮。 注意：使用该组件必须在父组件中提供`listEngine`

|props|说明|类型|可选值|默认值|
|----|----|----|----|----|
|customData|自定义模块数据(从接口里获取) {uuid,templateStyle,templateScript}|object|||

##### `advance-search-list`

`apaas` 默认查询器列表组件

|props|说明|类型|可选值|默认值|
|----|----|----|----|----|
|listAdvanceSearch|查询器列表，默认用listEngine.listDataControl.listAdvanceSearch|array|||

|event|说明|回调参数|
|----|----|----|
|edit-search|编辑查询器事件|编辑的查询器配置，编辑的查询器index|
|handler-click|点击查询器查询事件|点击的查询器配置， 点击的查询器index|

##### `list-header-button`

`apaas` 默认列表按钮组件

|props|说明|类型|可选值|默认值|
|----|----|----|----|----|
|buttonList|按钮列表|array|||

|event|说明|回调参数|
|----|----|----|
|list-button-click|按钮点击事件|$event:Event, btnConfig:Object|

##### `list-table-panel`

`apaas` 默认列表表格组件，自带 `loading`

|props|说明|类型|可选值|默认值|
|----|----|----|----|----|
|showPageListLoading|是否显示loading|boolean||false|
|pageListLoading|是否正在加载|boolean||false|
|pageListNetworkError|列表数据加载是否出现网络错误|boolean||false|
|tableConfig|表格配置|array|||
|queryLists|列表列配置|array|||
|listColDisplayConfig|列表列显示配置|array|||
|showStatistical|是否显示底部统计行|boolean||true|
|statisticalFooter|底部统计行配置|array|||
|pageConfig|表格分页相关配置|object|||

|event|说明|回调参数|
|----|----|----|
|loading-refresh|列表数据加载是否出现网络错误重新的点击事件|$event:Event|
|loading-done|列表数据加载完成事件||
|size-change|分页大小改变事件|pageSize:number|
|current-page-change|分页改变事件|currentPage:number|
|selectDataChange|列表选中数据改变事件|selectData:array|
|table-row-click|行点击事件|row:object,column:object|
|openCurrentAsso|行关联表单组件点击事件|row:object|
|type-change|列表统计类型改变事件|{ type:string, uuid:string }|
|listCustomButonClick|列表操作列按钮点击事件|row:object,button:object|
|column-resizable-change|列表列宽度改变事件|columnIndex:number, resizeWidth:number|

|slots|说明|
|----|----|
|customHeadSlot|自定义列表表格头部|

##### `list-design-search-components`

`apaas` 默认列表查询面板组件

|props|说明|类型|可选值|默认值|
|----|----|----|----|----|
|tileFormComponent|查询面板组件配置列表|array|||
|searchList|查询面板组件渲染构造的数据 默认用listEngine.listDataControl.searchList|array|||

|event|说明|回调参数|
|----|----|----|
|search|查询事件||

##### `x-date-search-item`

`apaas` 默认列表查询面板的日期组件

|props|说明|类型|可选值|默认值|
|----|----|----|----|----|
|tileFormComponent|组件配置|object|||
|compInfo|组件配置（同tileFormComponent）|object|||
|value|组件绑定的值|array|||
|element-ui日期组件的props|||||

##### `x-department-search-item`

`apaas` 默认列表查询面板的部门选择组件

|props|说明|类型|可选值|默认值|
|----|----|----|----|----|
|tileFormComponent|组件配置|object|||
|compInfo|组件配置（同tileFormComponent）|object|||
|value|组件绑定的值|array|||
|element-ui的下拉框组件的props|||||

##### `x-select-search-item`

`apaas` 默认列表查询面板的下拉框相关组件

|props|说明|类型|可选值|默认值|
|----|----|----|----|----|
|tileFormComponent|组件配置|object|||
|compInfo|组件配置（同tileFormComponent）|object|||
|value|组件绑定的值|array|||
|element-ui的下拉框组件的props|||||

##### `x-people-search-item`

`apaas` 默认列表查询面板的人员选择组件

|props|说明|类型|可选值|默认值|
|----|----|----|----|----|
|tileFormComponent|组件配置|object|||
|compInfo|组件配置（同tileFormComponent）|object|||
|value|组件绑定的值|array|||
|element-ui的下拉框组件的props|||||

##### `x-switch-search-item`

`apaas` 默认列表查询面板的开关组件

|props|说明|类型|可选值|默认值|
|----|----|----|----|----|
|tileFormComponent|组件配置|object|||
|compInfo|组件配置（同tileFormComponent）|object|||
|value|组件绑定的值|array|||
|element-ui的下拉框组件的props|||||

##### `x-input-search-item`

`apaas` 默认列表查询面板的输入框组件

|props|说明|类型|可选值|默认值|
|----|----|----|----|----|
|tileFormComponent|组件配置|object|||
|compInfo|组件配置（同tileFormComponent）|object|||
|value|组件绑定的值|array|||
|element-ui的输入框组件的props|||||

##### `x-number-search-item`

`apaas` 默认列表查询面板的数字输入组件

|props|说明|类型|可选值|默认值|
|----|----|----|----|----|
|tileFormComponent|组件配置|object|||
|compInfo|组件配置（同tileFormComponent）|object|||
|value|组件绑定的值|array|||
|xui的x-number组件的props|||||

##### `x-money-search-item`

`apaas` 默认列表查询面板的金额输入组件

|props|说明|类型|可选值|默认值|
|----|----|----|----|----|
|tileFormComponent|组件配置|object|||
|compInfo|组件配置（同tileFormComponent）|object|||
|value|组件绑定的值|array|||
|xui的x-number组件的props|||||

#### 高级使用

场景注册，`listEngine` 里面的 `listDataControl` 中的数据，是通过场景来调用初始化而来的，如果不想使用 `apaas` 默认的场景，可以自定义场景

```js
// 使用如下模版新建一个js
// 在组件创建时会依次执行场景对应的钩子方法
export default {
  renderLogicName: 'CUSTOM_XXXXX_LOGIC', // 自定义场景的名称
  methods: {
    onInitQueryParams(vm) {}, // 构造queryParams
    onListEngineCreated(vm) {}, // listEngine创建完成的钩子
    onInitList(vm) {}, // 列表初始化配置和数据的钩子
    onInitListButton(vm) {}, // 初始化列表按钮数据的钩子
    onInitAdvanceSearch(vm) {}, // 初始化查询器数据的钩子
    onInitFormFields(vm) {} // 初始化表单组件的钩子
  },

  actions: {
    // action中可以注册listEngine实例的action,如下// "CUSTOM_XXXXX_ACTION": (engine, event) => {//// }
  }
}
```

写完场景后，在模块的入口文件引入并通过如下方式注册场景

```js
// CUSTOM_XXXXX_LOGIC 为注册的 renderLogicName， logic为引入的场景js文件
Vue.ListEngine.RenderLogicControl.registerRenderLogic('CUSTOM_XXXXX_LOGIC', logic)
```

#### loading 的使用

`listEngine` 的 `loading` 模式是压栈弹栈的方式实现，只有 `loading` 栈为空时，`loading` 结束

```js
// key: string
this.listEngine.listDataControl.loadingEngine.pushLoadingStack(key);
this.listEngine.listDataControl.loadingEngine.popLoadingStack(key)
```

## web自定义布局开发

1. 开发布局组件 例如 `form-view/apaas-custom-demo.vue` 文件
2. 将开发的布局组件在入口文件中引入，并在插件 `install` 函数中使用以下方式进行注册

  ```js
  import CustomLayoutDemo from './custom-layout/custom-layout-demo.vue'
  const install = function(Vue, opts) {
    if (Vue.LayoutEngine) {
      const layoutEngine = Vue.LayoutEngine.getInstance(Vue.LayoutEngine.currentLayoutId)
      layoutEngine.registerLayoutComponent(CustomLayoutDemo)
    }
  }
  ```
3. 在 `apaas.json` 中的布局配置中写入相关配置
4. 开发人员使用 `debug` 命令调试
5. 调试完毕后，使用 `build` 命令打包
6. 将打包后的文件上传至自开发管理中，并和应用绑定，发布应用即可让所有用户使用

![img](https://edu.definesys.cn/edu-api/attachments/downloadDocImage?path=media/202308/2023-08-23_135357_785515.png)
![img](https://edu.definesys.cn/edu-api/attachments/downloadDocImage?path=media/202308/2023-08-23_135406_848900.png)

### LayoutEngine 介绍

`layoutEngine` 单列模式，通过 `LayoutEngine.getInstance(currentLayoutId)` 来获取实例。实例中的属性通过注册的方式来修改。在自开发工程中已经将 `LayoutEngine` 挂在 `Vue` 上

#### LayoutEngine 中的全局属性和方法

|属性|类型|说明|
|----|----|----|
|currentLayoutId|string|当前的LayoutId|
|getInstance(instanceId)|function|instanceId 当前LayoutId,获取实例方法，返回LayoutEngine实例|

#### layoutEngine 实例的属性和方法

|属性|类型|说明|
|----|----|----|
|engineContext|object|实例上下文|
|layoutConfig|object|布局配置|
|renderLogic|string|渲染场景（渲染场景是指layoutEngine实例使用哪个场景来渲染，建议使用我们给出的默认场景）|
|layoutDataControl|object|布局数据控制器|
|registerLayoutComponent(layoutComponent)|function|layoutComponent布局组件,注册布局组件|
|addKeepAliveComps(menu)|function|menu菜单信息,开启路由缓存后，将所选择的菜单缓存起来|
|removeKeepAliveComps(menu)|function|menu菜单信息event动作的event,开启路由缓存后，去除所选择的菜单缓存|

#### engineContext 实例上下文

|属性|类型|说明|
|----|----|----|
|queryParams|object|查询参数，包含appId和tenantId|

#### layoutConfig 布局配置

|属性|类型|说明|
|----|----|----|
|layoutComponentName|string|自定义布局组件name|
|keepAliveRouter|boolean|是否开启路由缓存|
|isActivatedLKeepAlive|boolean|开启路由缓存后，激活组件，是否重新请求接口，刷新数据|
|keepAliveComps|array|缓存的菜单|
|currentMenu|object|当前点击的菜单|

#### layoutDataControl 布局数据控制器

|属性|类型|说明|
|----|----|----|
|appInfo|object|应用信息|
|menuConfig|array|菜单信息|
|menuTreePermissionList|array|菜单权限列表|
|tenantModule|object|租户信息|
|authModule|object|用户信息|
|fontModule|object|字体信息|
|helpDocUrl|string|帮助文档地址|

#### ActionControl 介绍

ActionControl为动作控制器，LayoutEngine中的动作要使用ActionControl来执行。

ActionControl 中的全局属性和方法

|属性|类型|说明|
|----|----|----|
|globalActionMap|Map|全局ActionMap|
|registerGlobalAction(actionCode, action)|function|actionCode动作编码，action动作方法,注册全局动作|

actionControl 实例的属性和方法

|属性|类型|说明|
|----|----|----|
|actionMap|Map|实例ActionMap|
|engine|LayoutEngine|LayoutEngine实例|
|registerAction(actionCode, action)|function|actionCode动作编码，action动作方法，注册局部动作|
|getAction(actionCode)|function|actionCode动作编码，获取指定动作编码的局部动作或全局动作|
|executeActionWithPromise(actionCode, event)|function|actionCode动作编码，event动作的event，执行异步动作，返回Promise|
|executeActionWithSync(actionCode, event)|function|actionCode动作编码，event动作的event，执行同步动作，返回当前注册动作的返回值|

#### ActionControl 使用实例

```js
// 注册一个名字为INIT_MENU_TREE_ACTION的异步动作（异步动作指返回一个异步操作的动作，如返回一个Promise），可以使用如下方式注册
// 注册的动作中默认会传递两个参数，
// `engine`为`LayoutEngine`实例，
// `event`为动作事件，可以存放一些其他参数，本次示例中在`event`中存储了`appId`的参数
const layoutEngine = Vue.LayoutEngine.getInstance(Vue.LayoutEngine.currentLayoutId)
layoutEngine.actionControl.registerAction('INIT_MENU_TREE_ACTION', (engine, event) => {
  return new Promise((resolve, reject) => {
    const { appId } = event
    const request = { ...Vue.LayoutEngine.NetworkControl.apis.APP_ENGINE_HOME_GET_MENU_TREE }
    request.params = {
      appId
    }
    // 调用网络请求
    Vue.LayoutEngine.NetworkControl.globalRequest(request)
      .asyncThen(
        (resp) => {
          resolve(resp)
        },
        (error) => {
          reject(error)
        }
      )
      .asyncErrorCatch((error) => {
        reject(error)
      })
  })
})

// 执行名字为INIT_MENU_TREE_ACTION的异步动作，可以使用如下方式
const layoutEngine = Vue.LayoutEngine.getInstance(Vue.LayoutEngine.currentLayoutId)
// 执行异步动作
layoutEngine.actionControl
  .executeActionWithPromise('INIT_MENU_TREE_ACTION', {
    appId: vm.queryParams.appId
  })
  .then((resp) => {
    console.log(resp)
  })
  .catch((error) => {
    console.log(error)
  })
```

#### 默认 Action

|Action|类型|event参数|说明|
|----|----|----|----|
|GO_PERSONAL|同步||前往个人中心|
|GO_HELPER|同步||前往帮助文档|
|FONT_SIZE_SELECTED|同步|fontSize:'small' | 'middle' | 'large')|改变字体大小|
|TO_ROUTER|同步|menu:Object|跳转菜单|
|OPEN_CURRENT_FORM_DETAIL|同步|routeQuery:object|打开新增弹窗|
|GO_LOGOUT|同步||退出登录方法|
|INIT_APP_INFO_ACTION|异步|appId:string, isSingleApp(默认写true)|获取应用信息|
|INIT_MENU_TREE_ACTION|异步|appId:string|获取菜单信息|
|QUERY_MENU_PERMISSION_ACTION|异步|appId:string|获取菜单权限|
|QUERY_HELP_URL|异步|appId:string|获取应用帮助文档地址|

#### 默认布局组件介绍

##### `x-app-layout`

`apaas` 默认布局组件

|props|说明|类型|可选值|默认值|
|----|----|----|----|----|
|layoutEngine|布局引擎|LayoutEngine|||
|isCollapse|左侧菜单的折叠状态|boolean||false|

|slots|说明|
|----|----|
|header|头部内容|
|menu|左侧菜单内容|
|appPage|右侧页面内容|

##### `x-app-header`

`apaas` 默认头部组件

|props|说明|类型|可选值|默认值|
|----|----|----|----|----|
|layoutEngine|布局引擎|LayoutEngine|||
|appInfo|应用信息|object|||
|headerComponents|头部所展示的组件|array||['XOrgLogo', 'XAppLogo', 'XLayoutPersonAvatar']|

##### `x-org-logo`

`apaas` 默认租户 `logo` 组件

|props|说明|类型|可选值|默认值|
|----|----|----|----|----|
|orgLogoUrl|租户logoUrl|string||""|

|event|说明|回调参数|
|----|----|----|
|org-logo-click|租户logo点击事件|event: Event|

##### `x-app-logo`

`apaas` 默认应用 `logo` 组件

|props|说明|类型|可选值|默认值|
|----|----|----|----|----|
|appInfo|应用信息|object|||

##### `x-layout-person-avatar`

`apaas` 默认应用头像组件

|props|说明|类型|可选值|默认值|
|----|----|----|----|----|
|userInfo|用户信息|object|||
|currentOrg|租户信息|object|||
|storeFontSize|字体大小|string||小|
|helpDocUrl|帮助文档url|string|||

|event|说明|回调参数|
|----|----|----|
|go-personal|个人中心点击事件|event: Event|
|go-helper|帮助文档点击事件|event: Event|
|go-logout|退出登录点击事件|event: Event|
|font-size-selected|字体选择点击事件|fontSize: string|

##### `x-menu`

`apaas` 默认菜单组件

|props|说明|类型|可选值|默认值|
|----|----|----|----|----|
|menuConfig|菜单信息|object|||
|showMenu|是否显示菜单|boolean||true|
|isCollapse|左侧菜单的折叠状态|boolean||false|
|layoutEngine|布局引擎|LayoutEngine|||

|event|说明|回调参数|
|----|----|----|
|menu-add-click|菜单上添加按钮点击事件|event: Event|

##### message-center

`apaas` 默认消息中心组件

|props|说明|类型|可选值|默认值|
|----|----|----|----|----|
|layoutEngine|布局引擎|LayoutEngine|||

##### 消息中执行的 Action

|Action|类型|event参数|说明|
|----|----|----|----|
|INIT_MESSAGE_LIST|异步|page:Number, pageSize:Number, msgType:String("ALL":全部,"UNREAD":未读,"APP_DATA":应用通知,"SYS_DATA":系统通知)|获取消息列表数据|
|GET_MESSAGE_COUNT|异步||获取未读消息条数|
|SCROLL_MESSAGE_LOAD|异步|page:number, pageSize:number, msgType:"ALL" | "UNREAD" | "APP_DATA" | "SYS_DATA")|滚动加载更多消息列表数据|
|CLICK_MESSAGE_TO_READ|异步|msgId:string|点击某一条消息状态变已读|
