# aPaaS 前端组件自开发 — Skill

> v1.0 / 2026-05-14
> 给 ai-coding agent 引用。覆盖 9 个前端 scene_type 的关键规范。

---

## 技术栈

| 项 | 值 | 备注 |
|---|---|---|
| 框架 | Vue **2.7** | 不是 Vue 3！ |
| UI 库 | Element UI | **已全局注册**，不要 `import 'element-ui'` |
| 私有 npm | https://registry.dfy.definesys.cn/repository/apaas-npm-group/ | 走它装平台 SDK |
| 构建 | df-apaas-cli build (脚手架自带) | `npm run build` 触发 |
| 网络请求 | `this.$request` | **不是标准 axios** |
| 日期处理 | `this.$dayjs` | 不引 dayjs |
| 工具函数 | `this.$lodash` | 不引 lodash |
| 调试输出 | `console.info`（生产保留） | `console.log` 生产被剥离 |

---

## 9 个支持的 scene_type

调 `list_dev_scenes` 拿当前最新列表。常见：

| scene_type | 用途 | 主要产物 |
|---|---|---|
| `form-component-dual` | 表单字段组件（PC + 移动双端） | 14 个 scene vue + setting + widget config |
| `form-component-pc` | 表单字段组件（仅 PC） | 7 个 scene vue + setting |
| `form-page` | 自开发表单页 | 1 个主 vue |
| `form-list` | 自开发列表页 | 1 个主 vue |
| `mobile-page` | 移动端自开发页 | 1 个主 vue（移动适配） |
| `login-page` | 自定义登录页 | 1 个 LoginView.vue + 配置 |
| `dashboard` | 看板组件 / 看板页 | N 个 widget + `widget.config.json` |
| `custom-page` | 任意自开发页面（非表单） | 1 个主 vue + 自定义路由 |

写代码前**必须**：

```
get_dev_scene_spec(scene_type)  → 拿 spec 字段
get_dev_scene_full_workflow(scene_type)  → 拿 step-by-step + sample 代码
```

它们是 single source of truth，比文档准。

---

## 网络请求规范 — `this.$request`

aPaaS 平台 SDK 不是标准 axios。**body 走 `params`，不是 `data`** ← 这个坑过 N 次。

### 推荐：抽 Api 对象 + spread

```js
// src/api/index.js
const api = {
  QUERY_LIST: {
    url: '/xdap-app/business/v2/query/listPageBusinessData',
    method: 'POST',
    disableSuccessMsg: true,
  },
  FORM_SAVE: {
    url: '/xdap-app/engine/form/saveFormData',
    method: 'POST',
  },
};
export default api;
```

```js
// vue 组件
import Api from '../api';

this.$request({
  ...Api.QUERY_LIST,
  params: {                                   // ⭐ 不是 data
    formId: this.formId,
    tabId: this.tabId,
    page: 1, pageSize: 50,
    selectorFilterConditionList: [],
    filterConditionGroup: [],
    orders: [],
    type: 'initialize',
  },
}).asyncThen((res) => {
  // res.data 是 [{字段uuid: 值, ...}, ...]
  // res.total = 总条数
}).asyncErrorCatch((err) => {
  console.info('list err', err);
});
```

### 链式 API

**不是** Promise — 用 `.asyncThen(cb).asyncErrorCatch(cb)`，不能 `.then().catch()`。

---

## 业务数据列表查询（最常用）

**关键端点**：`POST /xdap-app/business/v2/query/listPageBusinessData`

必填字段：
- `formId` — 当前表单 ID（宿主已注入到 this.formId）
- `tabId` — 当前视图 ID（宿主已注入到 this.tabId）
- `page` / `pageSize` — 分页
- `selectorFilterConditionList: []` — 必传，无筛选给空数组
- `filterConditionGroup: []` — 必传空数组
- `orders: []` — 必传空数组
- `type: 'initialize'` — 首次加载用 'initialize'，搜索用 'search'

返回结构（实测 2026-05-14）：
```json
{
  "code": "ok",
  "message": null,
  "total": 42,
  "table": [
    { "id": "...", "document_id": "...", "字段uuid1": "值1", ... },
    ...
  ]
}
```

注意：`table` 才是数据数组，**不是 `data`** —— 跟单条详情接口 `/xdap-app/business/query/detailBusinessData` 不同。

---

## 业务数据写入（FORM_SAVE）

```js
this.$request({
  ...Api.FORM_SAVE,
  params: {
    formId: this.formId,
    formData: {
      字段uuid1: '值1',
      字段uuid2: ['option_code_1'],   // 下拉/单选必须 JSON 数组（坑 1）
      ...
    },
  },
}).asyncThen((res) => { /* res.data.documentId */ });
```

下拉字段写入注意：哪怕只选一个，也必须是数组 `["code_xxx"]`。

---

## 子表关联

子表行通过 `tab_doc_id` 关联主表的 `document_id`（不是 parent_id / main_id）。

写主表 + 子表时：

```js
this.$request({
  ...Api.FORM_SAVE,
  params: {
    formId: this.formId,
    formData: {
      // 主表字段
      字段uuid1: '...',
      // 子表数组（key 是子表 form 的 modelCode 或 reservedFieldCode）
      detailList: [
        { 字段子1: '...', 字段子2: '...' },
        { 字段子1: '...', 字段子2: '...' },
      ],
    },
  },
});
```

平台自动给每条子表行打 `tab_doc_id = 主表 documentId`。

---

## form-component-dual 场景（双端组件）

最复杂的场景 — 一个组件包含 14 个 scene vue：

```
src/
├── pc/
│   ├── views/
│   │   ├── ComponentBuild.vue       # 表单编辑态 - 占位渲染
│   │   ├── ComponentFormShow.vue    # 表单录入态 - 真实输入
│   │   ├── ComponentReadOnly.vue    # 详情查看态
│   │   ├── ListShow.vue              # 列表态
│   │   ├── ListDetail.vue            # 列表详情
│   │   ├── ProcessShow.vue           # 流程审批态
│   │   └── ExportShow.vue            # 导出态
│   ├── setting.vue                   # 组件配置面板
│   └── widget.config.json            # 组件元信息
└── mobile/
    └── ... (镜像同样 7 个 scene)
```

**容易踩**：

- 7 个 scene 必须**全部实现**（哪怕只是空 div + 显示一个值），少一个平台运行时报错
- ComponentBuild.vue 只渲染**占位** —— 表单设计器里看到的，不应该真做交互
- ComponentFormShow.vue 才是真用户输入界面 — `v-model` 接 `value`，emit `input`
- `setting.vue` 接收 `componentInfo` props，写回 `componentInfo.value` 上的字段

完整 sample：调 `get_dev_scene_full_workflow("form-component-dual")` 拿 step-by-step。

---

## 看板组件（dashboard）

```
src/
├── widgets/
│   ├── widget-a/
│   │   ├── index.vue
│   │   └── widget.config.json
│   └── widget-b/
│       ├── index.vue
│       └── widget.config.json
└── df-apaas.config.json    # 整个包配置
```

每个 widget 一个独立目录 + config。widget 拿到的 props：
- `dataSource` — 看板配置的数据源
- `filters` — 看板筛选条件
- `dimensions` — 维度

数据查询：用 `this.$request` 调 `/xdap-app/dashboardData/query` 等 endpoint。

---

## 常见坑速查

| 坑 | 怎么躲 |
|---|---|
| 引了 element-ui 双重注册 | 不要 `import 'element-ui'`，宿主全局注册 |
| `console.log` 调试日志生产没了 | 改 `console.info` |
| `this.$request({...Api.X, data:{...}})` 拿不到数据 | body 改 `params` 不是 `data` |
| 下拉字段写入 `'code_xxx'` 直接没生效 | 改 `['code_xxx']` JSON 数组 |
| 子表行查询 `WHERE parent_id=...` 报 Unknown column | 改 `WHERE tab_doc_id=...` |
| FORM_SAVE 后 list 拿不到新数据 | 看 res.code === 'ok' 才算成功；errors 字段看具体原因 |
| `.then(cb)` 不工作 | 改 `.asyncThen(cb).asyncErrorCatch(cb)` 链式 |
| 表单组件 7 个 scene 漏一个 | 全部实现，至少空 div 兜底 |
| ComponentBuild.vue 写了真交互 | 改成纯占位渲染 |
| 组件 setting.vue 改了字段但运行时拿不到 | 写回 `componentInfo.value.xxx` 不是 `data.xxx` |

---

## 发布

调 `publish_dev_workspace` 一键打包上传。失败看 `error_code`：

- `FE_COMPILE_FAIL` — npm build 失败，先 `run_workspace_command("npm run build")` 本地复现看错
- `MVN_*` — 是后端项目走错了 workflow

构建成功后：

```
publish_dev_workspace(ws_id, env_id) 
  ↓
拿到 kit_id（FRONTEND 类型）
  ↓
enable_apaas_self_dev_config(app_id)
attach_dev_packages_to_apaas_app(app_id, kit_id, kit_type="FRONTEND")
republish_apaas_app(app_id)
```

如果是「自开发菜单」（独立 custom-page），还要：

```
create_apaas_self_dev_menu(app_id, menu_name, component_name)
```

---

## URL 调用路径

| 场景 | 路径 |
|---|---|
| 前端按钮事件 fetch 后端 | `/apaas/backend/model/{app_code}/custom/{project_name}/{api_path}` |
| aPaaS 服务集成（按钮配的） | 同上，domain + path 拆配 |
| 外部 Postman | 同上，加 `xdaptoken` + `xdaptimestamp` 头 |
