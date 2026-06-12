"""dev_scene_runtime_api — aPaaS 平台运行时 HTTP API 速查（写自开发 vue 代码用）。

设计目的
========
外部 agent 端到端写 form-page / form-list / mobile-page 自开发组件时，需要
**直接知道** vue 代码里 `this.$request({...})` 该调哪些 endpoint、payload 怎么填、
返回怎么解析。

跟 V2.1/V2.5 元数据查询工具的区别
================================
- 元数据查询工具（list_apaas_form_views / list_apaas_form_components ...）：
  agent **写代码前** 调 MCP 拿到 form_id / tab_id / component_uuid 等 ID
- 本文档（PLATFORM_API_QUICK_REF）：agent **写代码时** 拿到 vue 代码里
  `this.$request({...})` 该调的 endpoint + payload schema

引用方式
========
- dev_scene_workflow.py 在 form-page / form-list / mobile-page 的 workflow
  末尾自动 append PLATFORM_API_QUICK_REF（精简版，1.5KB）
- 完整版 PLATFORM_API_FULL_REF 给需要复杂场景（流程审批 / 高级筛选 / CRUD）
  的 agent 按需查（V2.6 可考虑做成单独 MCP 工具或写到 workspace 的
  .cursor/rules/ 文件）
"""
from __future__ import annotations


# ─────────────────────── 精简速查（嵌 workflow 用，~1.8KB）───────────────────────


PLATFORM_API_QUICK_REF = """\
---

## ⭐ aPaaS 平台运行时 HTTP API 速查（写代码必看）

写 vue 代码调表单数据用——agent 必须按下面 5 个核心 endpoint 的 schema 来。

> 🚨 **2026-05-08 重大修订**：得帆云 `this.$request({...})` **不是标准 axios**！
> POST 请求的 body **走 `params` 字段**，**不是** axios 的 `data`。之前所有写
> `data: {...}` 的代码 vue 跑起来 content-length=0 → 平台后端拿不到 formId →
> 全部 500 + 接口请求超时。这是真实事故根因。

### 调用前置（已经从 MCP 工具拿到）

写代码前应该已经从 MCP 拿到这些 ID（**用户不知道这些，agent 必须自己查**）：
- `appId` = 用户选定应用的 apaas_app_id（list_apaas_apps_in_env 拿）
- `formId` = 用户提到的中文表单名对应的 ID（list_apaas_app_menus 拿，找 menu_name 匹配 → form_id）
- `menuId` = 同上 menu_id（**注意：menuId 不进 body，平台从 url referer 自己识别**）
- `tabId` = 列表视图 ID（**list_apaas_form_views(form_id) 必调拿默认 tab**）
- 字段 `uuid → label` 映射 = list_apaas_form_components(form_id) 拿（**列表数据返回 key 是 uuid 不是字段名**）

### ⚠️ 调用层铁则（写错 1 个 0 字节 body / 接口超时 / 500）

1. **`this.$request` 用 `params` 不是 `data`**：得帆云 sdk 的签名是
   `{url, method, params, headers, timeout, disableSuccessMsg, disableErrorMsg}`，
   **没有 `data` 字段**。POST 也用 `params` 字段传 body（sdk 内部按 method 决定塞 query 还是 body）。
   写 `data: {...}` sdk **直接忽略**，发出去 body 空 content-length=0 → 必撞超时 500。
2. **URL 用相对路径**：`this.$request({url: '/xdap-app/...'})` —— 平台 axios 自动加前缀变成 `/apaas/backend/{tenant_code}/{app_code}/xdap-app/...`，**绝对不要**写完整 URL（`https://apaas-trial...`）
3. **header 平台自动注入**：`xdapappid` / `xdaptenantid` / `xdaptoken` / `xdapversion` / `xdaptimestamp` 这 5 个 header 平台 axios 拦截器会自动加，**agent 不用管，更不要塞 body**
4. **params 不传 `appId` / `menuId`**：appId 走 header `xdapappid`，menuId 走 referer 上下文
5. **链式 API**：`.asyncThen(cb).asyncErrorCatch(cb)` —— **不是** Promise 的 `.then().catch()`

### 推荐：抽 Api 对象 + spread 调用（来自线上能跑通的真实自开发包）

```js
// src/api/index.js
const api = {
  QUERY_LIST: {
    url: '/xdap-app/business/v2/query/listPageBusinessData',
    method: 'POST',
    disableSuccessMsg: true,   // 推荐：列表加载不弹"操作成功"提示
  },
  FORM_SAVE: {
    url: '/xdap-app/engine/form/saveFormData',
    method: 'POST',
  },
  // ...
};
export default api;
```

```js
// vue 组件中：
import Api from '../api';

// 列表查询
this.$request({
  ...Api.QUERY_LIST,         // 注入 url / method / disableSuccessMsg
  params: {                   // ⭐⭐⭐ POST body 走 params！
    formId,
    tabId,
    page: 1,
    pageSize: 10,
    selectorFilterConditionList: [],
    filterConditionGroup: [],
    orders: [],
    type: 'initialize',
  },
}).asyncThen((res) => {
  // res.data 是 [{字段uuid: 值, ...}, ...]，total = res.total
}).asyncErrorCatch((err) => { console.info('list err', err); });
```

### 1. 列表数据 listPageBusinessData（最常用）✅ 线上跑通真实写法

```js
this.$request({
  url: '/xdap-app/business/v2/query/listPageBusinessData',
  method: 'POST',
  params: {                              // ⭐ 不是 data
    formId: this.formId,                  // ✅ 必传
    tabId: this.tabId,                    // ✅ 必传（list_apaas_form_views 拿默认 tab）
    page: 1,
    pageSize: 10,                         // ⚠️ 平台默认 10，写 500 可能超限
    selectorFilterConditionList: [],      // ✅ 必传（无筛选给空数组；有筛选见下）
    filterConditionGroup: [],             // ✅ 必传空数组
    orders: [],                           // ✅ 必传空数组
    type: 'initialize'                    // ✅ 必传：首次加载='initialize'，搜索='search'
    // ❌ 不传 appId（走 header xdapappid）
    // ❌ 不传 menuId（走 referer 上下文）
    // ❌ 不传 searchConditions（旧字段已废弃）
  }
}).asyncThen((res) => {
  // res.data 是 [{字段uuid: 值, ...}, ...]
  // res.total 是数据库总数（**不要用 res.data.length 当总数**——那只是当前页）
}).asyncErrorCatch((err) => { console.info('list err', err) })
```

**有筛选条件时 `selectorFilterConditionList` 长这样**（线上 cURL 实抓）：

```js
selectorFilterConditionList: [
  {
    uuid: '6ef2f83b1bd84720810919fd192f61b6',
    componentType: 'FORM_TEXT_INPUT',
    conditionOption: 'CONTAIN',                    // CONTAIN / EQUAL / IN / GT / LT / BETWEEN ...
    filterInputs: [{ filterParams: ['搜索词'], order: 0 }],
    connector: 'AND'
  },
]
```

### 2. 详情数据 detailBusinessData

```js
this.$request({
  url: '/xdap-app/business/query/detailBusinessData',
  method: 'GET',
  params: { formId, id: rowId }   // GET 也是 params（sdk 自动塞 query string）
}).asyncThen((res) => { /* res.data 是 {uuid: 值} dict */ })
  .asyncErrorCatch((err) => {})
```

### 3. 新增/编辑 saveFormData（端点见参考实现 form-page-smart_dispatch）

```js
this.$request({
  url: '/xdap-app/engine/form/saveFormData',
  method: 'POST',
  params: {                                          // ⭐ 不是 data
    formId,
    data: { 字段uuid_1: '值1', 字段uuid_2: '值2' },   // ⚠️ data 是 params 内的字段（业务数据 dict），不是 sdk 顶层
    id: rowId   // 编辑时传，新增不传
  }
}).asyncThen((res) => {})
  .asyncErrorCatch((err) => {})
```

### 4. 删除 form/delete (单条) / form/batch/delete (批量)

```js
// 单条
this.$request({
  url: '/xdap-app/business/v2/form/delete',
  method: 'POST',
  params: { formId, id: rowId }       // ⭐ params
}).asyncThen(...).asyncErrorCatch(...)

// 批量
this.$request({
  url: '/xdap-app/business/v2/form/batch/delete',
  method: 'POST',
  params: { formId, ids: [rowId1, rowId2] }
}).asyncThen(...).asyncErrorCatch(...)
```

### 5. 弹窗打开 form 详情/编辑（df-sdk）

```js
df.page.openFormModal({
  appId: this.appId,
  formId: this.formId,
  type: 'view',           // 'add' / 'edit' / 'view'
  id: rowId,              // 'add' 时不传
  onSuccess: (data) => { /* 关单后回调，刷新列表 */ }
})
```

### 必须遵守的铁则

1. **`this.$request` body 用 `params`，不是 `data`** —— 这条最容易错，所有 5 个 endpoint 全用 params
2. **🚫 tabId / formId / 字段 uuid 严禁编造**：得帆云的这些 ID 都是 **24 位 hex 字符串**
   （类似 `69834a5d544f072b5be9b84a`），**不是** `"tab_default"` / `"form_xxx"` / `"course_id"`
   这种语义字符串。写代码前**必须**调 `list_apaas_form_views(env_id, apaas_app_id, form_id)`
   拿真实 default_tab_id，绝不能瞎编。撞错业务码 4224 = "tabId不合法" 就是编造的代价。
3. **行数据 key 是组件 uuid**：渲染表格列 `<el-table-column :prop="comp.uuid" :label="comp.label" />`，不要写 `boCode` 或字段中文名当 prop
4. **listPageBusinessData params 4 必传字段**：`selectorFilterConditionList` / `filterConditionGroup` / `orders` / `type` 任一缺失或 null 都 400
5. **总数用 `res.total`，不要 `res.data.length`** —— length 只是当前页条数
6. **撞错先看 Network**：F12 抓真实 cURL，看 `--data-raw` 部分，跟 vue 代码 params 字段名 1:1 比对

### 🚨 写代码前自检清单（违反任一条 = 必撞错）

```
□ 每个 form_id 都是 24 位 hex（list_apaas_app_menus 返回的）
□ 每个 tab_id 都是 24 位 hex（list_apaas_form_views 返回的 default_tab_id）
□ 每个 字段 uuid 都是 32 位 hex（list_apaas_form_components 返回的）
□ 没有任何 "tab_default" / "form_xxx" / "course_id" / 中文/拼音 当 ID
□ this.$request 调用都用 params 不是 data
□ 4 个必传字段：selectorFilterConditionList / filterConditionGroup / orders / type
□ 表格 prop 用 uuid 不用语义名
□ 指标用 res.total 不用 res.data.length
```

### 调用顺序（form-page 典型）

```
mounted()
  ├─ 并行：list_apaas_form_components 已拿过 → 用 chat 里的映射做表头
  ├─       list_apaas_form_views 已拿过 → 拿 tabId
  └─ this.$request 调 listPageBusinessData（params 含 formId/tabId/4 必传字段）
       → asyncThen 拿 res.data + res.total → 表格渲染
```

完整运行时 API 文档当前未内置到仓库；复杂场景先按本摘要实现，缺口再补专用工具或知识文档。
"""


# ─────────────────────── 完整版（57KB，给 V2.6 cursor rule / 独立 MCP 用）─────


def get_full_runtime_api_doc() -> str:
    """返回完整 17 个 API 的 markdown（57KB）。

    完整文档未随仓库发布时返回精简版，避免运行时引用不存在的文件。
    """
    from pathlib import Path
    import logging
    logger = logging.getLogger(__name__)
    candidates = [
        # 仓库相对路径（开发 + 容器内同时容错）
        Path(__file__).resolve().parent.parent.parent / "docs" / "skills" / "ai-coding" / "apaas-form-data-api.md",
        Path("/root/apaas-builder/docs/skills/ai-coding/apaas-form-data-api.md"),
    ]
    for p in candidates:
        if p.exists():
            try:
                return p.read_text(encoding="utf-8")
            except Exception as exc:
                logger.warning("读 apaas-form-data-api.md 失败 %s: %s", p, exc)
    return PLATFORM_API_QUICK_REF  # fallback：找不到完整版至少有精简版


__all__ = ["PLATFORM_API_QUICK_REF", "get_full_runtime_api_doc"]
