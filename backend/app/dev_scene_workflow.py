"""dev_scene_workflow — 给 外部 agent 用的"按 scene_type 完整开发规范"。

设计原则
========
1. **不动 vibe_agent.py**：vibe_agent 的 _build_prompt() 仍然是给 ai-builder 内置
   agent loop 用的（agent 工作流引导 + 规则），保持原样。
2. **本文件给 外部 agent 看**：外部 agent 通过 MCP 工具 get_dev_scene_full_workflow
   拉取，注入到当前 chat context，让它跟 vibe_agent 拥有同等的"该写什么 / 不该写什么"
   知识。
3. **结构跟 vibe_agent 不一样**：vibe_agent 拿到的是"先 glob 再 read 再 write"工作流；
   外部 agent 拿到的是"开发规范 + critical rules + 自检清单"——agent 自己的
   skill prompt 已有工作流（V2 dev-coding.md），不需要在这里重复。
4. **重要场景细致 / 不常用场景给指针**：form-component-dual / form-page / backend-api
   写完整规范；其他 scene 指向 list_dev_scenes 的 critical_warnings + file_outline。
"""
from __future__ import annotations


# ─────────────────────── 通用片段 ───────────────────────


_GENERIC_PREAMBLE = """\
## 通用约束（所有 aPaaS 自开发场景适用）

- 前端基于 **Vue 2.7**
- **Element UI 已在宿主容器中全局注册**（PC 场景），不要 `import 'element-ui'`
- 私有 npm 源：`https://registry.dfy.definesys.cn/repository/apaas-npm-group/`
- 日期处理用 `this.$dayjs`，工具函数用 `this.$lodash`
- **`console.log` 在生产构建中被剥离 — 调试输出统一用 `console.info`**
- **网络请求**：用 `this.$request({...}).asyncThen(...).asyncErrorCatch(...)` 链式调用，
  **不是** Promise 的 `.then/.catch`。最常见错误是写成 Promise 风格——会编译过但运行时
  无法触发回调
- 不要修改 `vue.config.js`、`babel.config.js` 等基础设施文件
- 只有需要新增 npm 依赖才修改 `package.json`，改完跑 `npm install`
- 组件代码必须是完整的 `.vue` 单文件组件（含 `<template>`、`<script>`、`<style>`）
- 禁止留 TODO 占位符，必须实现完整功能

## df-sdk（全局 window.df，所有场景通用）

- `df.getVue()` — 系统 Vue 实例
- `df.getRouter()` — 系统路由
- `df.getStore()` — Vuex store
- `df.getEnv()` — 环境变量
- `df.page.openFormModal()` — 打开弹窗
- `df.showToast()` — Toast 提示
"""


_FORM_COMPONENT_DUAL_WORKFLOW = """\
# 自开发表单组件（双端 PC + 移动）开发规范

## 🛑 目录结构铁则（绝对不要违反）

PC 端 7 个 scene 的 vue 文件**只能放在以下唯一目录**：

```
web/src/form-component/form-widget/
├── edit/       ← form-component-{name}-edit.vue
├── read/       ← form-component-{name}-read.vue
├── ide/        ← form-component-{name}-ide.vue
├── list/       ← form-component-{name}-list.vue
├── print/      ← form-component-{name}-print.vue
├── search/     ← form-component-{name}-search.vue
└── search-ide/ ← form-component-{name}-search-ide.vue
```

移动端结构对称（`mobile/src/form-component/form-widget/{...}/`）。

**严禁创建以下目录**（scaffold 不存在）：
- ❌ `src/form-component/list-widget/`
- ❌ `src/form-component/print-widget/`
- ❌ `src/form-component/search-widget/`
- ❌ `src/form-component/search-ide-widget/`
- ❌ `src/form-component/edit-widget/`

注意：mixin 文件名（`list-widget.mixin.js`）只是文件名，**不是目录名**。

## 🔴 配置读取铁则（违反必致所有配置失效，必读）

PC + 移动两端 7 个 scene vue（edit/read/ide/list/print/search/search-ide）里
**必须用 `this.widget.customComponentConfig`** 读 setting.vue 里配的参数：

- ❌ 错：`customConfig() { return this.customComponentConfig || {}; }` (拿到 `{}`)
- ✅ 对：`customConfig() { return this.widget.customComponentConfig || {}; }`

setting.vue 里**必须用 `this.componentConfig.customComponentConfig`**：

- EditorFormConfigMixin 提供 `componentConfig` prop（用于 setting.vue）
- FormWidgetMixin 提供 `widget` 对象（用于 7 个 scene vue）
- 两种 mixin 挂载属性名不同，混用会**静默失效**（编译过 build 过，运行时配置全失效）

## Mixin 速查（per mode）

```js
// edit / ide / read
import FormWidgetMixin from '@/mixin/form-widget.mixin'
// list
import ListWidgetMixin from '@/mixin/list-widget.mixin'
// print
import PrintWidgetMixin from '@/mixin/print-widget.mixin'
// search
import SearchWidgetMixin from '@/mixin/search-widget.mixin'
// search-ide
import SearchIdeWidgetMixin from '@/mixin/search-ide-widget.mixin'
// editor (setting.vue)
import EditorFormConfigMixin from '@/mixin/form-config.mixin'
```

**全部用 default import**，不要用 named import。

## Mode-specific Rules（每种模式的特殊规则）

### Edit mode
- 检查 `this.widget.readOnly` 决定是否禁用交互
- guard `formValue` undefined 用 fallback
- 不要在同一 element 同时用 `v-model` 和 `@input`（会无限循环）

### Read mode
- 跟 Edit 类似但所有交互 disabled

### IDE mode
- **所有输入必须 `disabled`** —— IDE 是表单设计器画布，不允许用户交互
- 用 IDE 模式呈现"占位"给设计师看

### List mode
- config 来自 `this.componentConfig`（**不是** `this.widget`）
- `this.formValue` 是值 prop 直接，**不要** propKey 索引
- **不要用** `<x-proxy-form-item>` wrapper

### Print mode
- **禁止使用 `<el-xxx>`** —— Element UI 在打印态不渲染
- 不要 `<x-proxy-form-item>`
- 纯 HTML/CSS，结构：`div.print-item > div.print-item-title + div.print-item-value`
- 当 `widget.isInTable` 为 true 时省略 title

### Search mode
- 不要 `<x-proxy-form-item>`
- emit 必须 wrap 数组：`this.$emit('change', [value])`
- **不要**用 formValue setter

### Search-IDE mode
- 不要 `<x-proxy-form-item>`
- 所有输入 `disabled`
- 只在 Search mode 也实现的情况下实现

## 🚫 严禁使用 `<el-dialog>` 或 `<el-popover>` 内嵌

在 form widget 内**禁止使用 `<el-dialog>`** —— 破坏 FormEngine 组件解析，平台直接崩
（报 `Cannot read properties of undefined (reading 'edit')`）。

需要弹窗交互用 `<el-popover :append-to-body="true">` 替代。

## BOF Type & formValue 处理

- BOF_NUMBER caveat：`formValue` 可能是字符串。要 guard：
  ```js
  const n = Number(this.formValue)
  if (isNaN(n)) { /* fallback */ }
  ```

## formEngine 生命周期

- `formEngine` 在 `beforeCreate()` 不可用 —— 只能在 `created()` 及以后访问 `this.formEngine`

## 关键文件（开发顺序）

1. `shared/widget.config.json` —— **双端唯一配置源**（PC + 移动共享）。改这里就能让两端都生效
2. `shared/mixin/*.js` —— 双端共享业务 mixin（如有）
3. `web/src/form-component/form-widget/{edit,read,ide,list,print,search,search-ide}/*.vue` —— PC 7 scene
4. `mobile/src/form-component/form-widget/{...}/*.vue` —— 移动端 7 scene
5. `web/src/form-component/form-editor/setting.vue` —— PC 配置面板
6. `web/src/form-component/form-editor/{name}.editor.config.json` —— 配置面板 schema
7. `web/src/form-component/form-editor/index.js` —— 注册组件 + setting
8. `web/src/form-component-config/form-editor/index.js` —— 注册 config 项

**关键 batch 操作**：第 3 + 4 步加起来 14 个 vue，应该用 `write_workspace_files`
**一次 batch 写完**（一次 RPC，避免 30+ 次往返）。

## Build 流程

1. `run_workspace_command(ws_id, command="npm install")` —— 装依赖（首次或改了 package.json）
2. `run_workspace_command(ws_id, command="npm run build")` —— 编译两端

build 失败 → `read_workspace_file` 看 stderr 输出 → `edit_workspace_files` 修 → 重新 build。

## 自检清单（build 前）

- [ ] `shared/widget.config.json` 字段类型对（widget.config.json 有 schema 校验）
- [ ] 14 个 scene vue 都存在且 `index.js` 引用正确
- [ ] setting.vue 用 `this.componentConfig.customComponentConfig`
- [ ] 7 个 scene vue 用 `this.widget.customComponentConfig`
- [ ] Print mode 没有任何 `<el-xxx>`
- [ ] Search mode emit 包数组
- [ ] IDE / Search-IDE / Read mode 所有输入 disabled
- [ ] 没用 `<el-dialog>`
"""


_FORM_COMPONENT_SINGLE_WORKFLOW = """\
# 自开发表单组件（单端，新建工程已极少出现，多用 form-component-dual）

跟双端规范基本一致，但所有路径**去掉 `web/` 前缀**：

- `src/form-component/form-widget/{edit,read,ide,list,print,search,search-ide}/*.vue`
- `src/form-component/form-editor/setting.vue`
- `src/form-component-config/form-editor/index.js`

其他规则（mixin / 配置读取 / mode-specific / 目录铁则 / 禁用 el-dialog 等）跟
form-component-dual 完全一致——参考那一份。

## 强烈建议

新需求**优先用 form-component-dual**——双端组件即使移动端不用，mobile/ 那边写
空壳即可。单端工程的 build 工具链跟双端不同，维护成本更高。
"""


_FORM_PAGE_WORKFLOW = """\
# 自开发菜单页面（PC）开发规范

## 关键文件结构

```
src/
├── apaas.json              ← templateType 必须是 PAGE_CUSTOM_DEV
├── index.js                ← 注册组件名 apaas-custom-{业务名}
├── page.vue                ← 主页面
└── api/index.js            ← 接口封装（可选）
```

## 命名约定（铁则）

- **组件名 / 路由必须以 `apaas-custom-` 开头**（平台扫描规则）
  - ✅ `apaas-custom-home-dashboard`
  - ❌ `home-dashboard` / `custom-home-dashboard`
- 组件必须在 `custom/` 目录下（默认）

## 网络请求模式

```js
this.$request({
  url: '/xxx/yyy',
  method: 'POST',
  data: {...}
})
.asyncThen((res) => {
  // 成功
})
.asyncErrorCatch((err) => {
  // 失败
})
```

⚠️ **不是 Promise**，不能用 `.then().catch()`。

## 应用 / 表单数据访问

调平台 BOF 接口拿数据（appId / formId 由用户提供）：

```js
this.$request({
  url: `/xdap/api/runtime/${appId}/${formId}/list`,
  method: 'POST',
  data: {
    page: 1, size: 20,
    queryParams: [/* 字段筛选 */]
  }
})
```

弹窗场景用 `df.page.openFormModal()`：

```js
df.page.openFormModal({
  appId: this.appId,
  formId: this.formId,
  type: 'add',  // 'add' / 'edit' / 'view'
  onSuccess: (data) => { /* 关单后回调 */ }
})
```

## index.js 注册模式

```js
import Page from './page.vue'

export default {
  install(Vue) {
    Vue.component('apaas-custom-home-dashboard', Page)
  }
}
```

## apaas.json 关键字段

```json
{
  "templateType": "PAGE_CUSTOM_DEV",
  "code": "apaas-custom-home-dashboard",
  "name": "首页看板",
  "version": "1.0.0",
  "main": "src/index.js"
}
```

## Build

`run_workspace_command(ws_id, command="npm run build")` —— 编译产物到 `lib/`。

## 自检清单

- [ ] 组件名 `apaas-custom-` 开头
- [ ] 网络请求用 `$request().asyncThen().asyncErrorCatch()` 链式
- [ ] 调试输出用 `console.info`（不是 `console.log`）
- [ ] apaas.json 的 templateType 是 `PAGE_CUSTOM_DEV`
- [ ] 没有用 Element UI 的 import（已全局注册）
"""


_BACKEND_API_WORKFLOW = """\
# 后端自开发接口（SpringBoot）开发规范

## 关键命名约定（铁则）

- **包名前缀必须 `com.xdap`**（平台扫描规则）
- **接口路径必须 `/custom/` 开头**
- **必须实现 `AllowUrlManage` 注册白名单**（不然平台拦截 401）
- **打包必须带 `-P lib` 参数**

## 文件结构

```
src/main/java/com/xdap/{业务包}/
├── controller/XxxController.java       ← REST 入口
├── service/XxxService.java             ← 业务逻辑
├── service/impl/XxxServiceImpl.java    ← 实现
├── dto/XxxRequest.java / XxxResponse.java
└── config/XxxAllowUrlConfig.java       ← 白名单注册
pom.xml
```

## Controller 模板

```java
package com.xdap.attendance.controller;

import org.springframework.web.bind.annotation.*;
import com.xdap.attendance.service.AttendanceService;
import com.xdap.attendance.dto.*;

@RestController
@RequestMapping("/custom/attendance")  // 必须 /custom 开头
public class AttendanceController {
    private final AttendanceService service;

    public AttendanceController(AttendanceService service) {
        this.service = service;
    }

    @PostMapping("/stat")
    public AttendanceStatResponse stat(@RequestBody AttendanceStatRequest req) {
        return service.stat(req);
    }
}
```

## AllowUrlConfig 模板（必须）

```java
package com.xdap.attendance.config;

import com.xdap.platform.security.AllowUrlManage;
import org.springframework.stereotype.Component;
import java.util.List;

@Component
public class AttendanceAllowUrlConfig implements AllowUrlManage {
    @Override
    public List<String> getAllowUrls() {
        return List.of(
            "/custom/attendance/stat"
            // 把所有要免认证的接口列在这
        );
    }
}
```

## MpaaS 数据库操作（如需访问平台数据）

```java
@Autowired
private DatasourceUtil datasourceUtil;

public List<Map<String, Object>> queryUsers() {
    MpaasQuery q = new MpaasQuery()
        .from("user_table")
        .where("status", 1);
    return datasourceUtil.query(q);
}
```

## pom.xml 关键

```xml
<!-- platform-api 必须 provided（运行时由平台提供） -->
<dependency>
    <groupId>com.xdap</groupId>
    <artifactId>platform-api</artifactId>
    <version>${platform.version}</version>
    <scope>provided</scope>
</dependency>
```

## Build

`run_workspace_command(ws_id, command="mvn -P lib -DskipTests package", timeout=180)`

注意：Maven 编译可能 60-180 秒，timeout 给足。产物在 `target/lib/*.jar`。

## 自检清单

- [ ] 所有包名 `com.xdap` 开头
- [ ] Controller 路径 `/custom` 开头
- [ ] 实现了 `AllowUrlManage` 接口注册白名单
- [ ] pom.xml 用 `-P lib` profile 打包
- [ ] DTO 字段名跟接口约定一致（前端调用时对得上）
"""


_GENERIC_FALLBACK = """\
# 通用自开发规范

详细规范请调 `get_dev_scene_spec(scene_type)` 拿 `critical_warnings` 和
`file_outline`——本场景的 workflow 还没写完整指南，按通用规范 + critical_warnings
去开发即可。

通用规范见上方"通用约束"段。

如果遇到不确定的细节，**问用户**，不要瞎猜。
"""


# ─────────────────────── V2.6 仪表板组件双端规范 ───────────────────────

# 仪表板组件（DEPORTAL）跟 form-component-dual 脚手架同源（CLI_TEMPLATE_MAP 共用
# form-component-dual 模板），但有 4 个 critical 差异，写错任何一个都不会被 apaas
# 工作台识别 / 渲染。

_DASHBOARD_COMPONENT_DUAL_WORKFLOW = """\
# 自开发工作台/仪表板组件（双端 PC + 移动）开发规范 V2.6

## 跟 form-component-dual 的关系

脚手架结构**完全相同**（shared/widget.config.json + shared/mixin + web|mobile/src/form-component/）。
form-component-dual 规范里所有"目录结构铁则"、"配置读取铁则"、"7 个 scene"都**继续适用**。

## 🛑 4 个 DEPORTAL 专属差异（写错一个组件就不显示）

### 1. shared/widget.config.json `templateType` 改成 `DEPORTAL_PANEL`

```json
{
  "templateType": "DEPORTAL_PANEL",     ← form-component 是 "FORM_COMPONENT"
  "componentName": "apaas-custom-dashboard-xxx",
  "componentLabel": "用户给的中文名",
  "icon": "el-icon-monitor",
  "panelType": "card",                  ← 新增字段：card / chart / kanban / custom
  "supportedSlots": ["dashboard", "homepage"],  ← 新增：哪些工作台槽位可挂
  "defaultSize": {"w": 6, "h": 4}       ← 新增：栅格默认占位（24 列栅格）
}
```

### 2. PC fileType=DEPORTAL_SELF_PACKAGE，移动端 fileType=DEPORTAL_MOBILE_SELF_PACKAGE

build_and_package_dual 已自动处理（按 ProjectType.DASHBOARD_COMPONENT_DUAL 派发），
你不用改代码——但要知道**关联到应用时这两个 fileType 不可互换**。

### 3. 不要继承 form-widget.mixin.js

form-widget.mixin 里的 `getValue / setValue / validate` 是给表单字段组件用的，
DEPORTAL 不挂表单值。改用：

```js
// shared/mixin/dashboard-panel.mixin.js（你自己写的）
export default {
  props: {
    panelConfig: { type: Object, default: () => ({}) },  // 工作台配置
    dataSource: { type: Object, default: () => ({}) },   // 数据源（dataSourceType / params）
  },
  inject: {
    dashboardBus: { default: null },     // 工作台事件总线（跨组件刷新通讯）
  },
  mounted() {
    this.dashboardBus?.on('refresh', this.onRefresh);
    this.loadData();
  },
  beforeDestroy() {
    this.dashboardBus?.off('refresh', this.onRefresh);
  },
  methods: {
    onRefresh() { this.loadData(); },
    loadData() { /* 子类实现 */ },
  },
};
```

### 4. 7 个 scene 缩到 2 个：edit + ide

DEPORTAL 不参与表单，没有 read / list / print / search / search-ide。每端只需要：

```
{web|mobile}/src/form-component/form-widget/
├── edit/       ← dashboard-{name}-edit.vue   （工作台前台展示）
└── ide/        ← dashboard-{name}-ide.vue    （工作台编辑器里的预览/配置）
```

src/form-component/index.js 里也只 register 这 2 个 scene。

## 数据加载 + 主题适配

- **数据接口**：用 `this.$request({url:'/xdap-app/dashboardData/query', method:'POST', data:{panelId, params}}).asyncThen(...)`，
  跟工作台总线协调（不是直接走业务表单接口）。
- **主题**：工作台支持 light/dark 两套 CSS 变量，组件 `<style>` 用 `var(--de-text-primary)` /
  `var(--de-bg-primary)` 等。**不要硬编码颜色**，否则切主题会割裂。
- **响应式**：栅格变化时 `this.$watch('$el.clientWidth', ...)` + chart 重排。

## 自检清单

- [ ] shared/widget.config.json `templateType: "DEPORTAL_PANEL"`
- [ ] componentName 以 `apaas-custom-dashboard-` 开头
- [ ] PC + 移动各只有 edit/ + ide/ 两个 scene
- [ ] 用 `dashboard-panel.mixin`，不继承 form-widget.mixin
- [ ] CSS 用主题 var，不硬编码颜色
- [ ] 数据接口走 `/xdap-app/dashboardData/query`
"""


# ─────────────────────── 注册表 ───────────────────────


_WORKFLOW_BY_SCENE: dict[str, str] = {
    "form-component-dual": _FORM_COMPONENT_DUAL_WORKFLOW,
    "form-component": _FORM_COMPONENT_SINGLE_WORKFLOW,
    "form-page": _FORM_PAGE_WORKFLOW,
    "menu-page": _FORM_PAGE_WORKFLOW,  # menu-page 跟 form-page 等价
    "backend-api": _BACKEND_API_WORKFLOW,
    # V2.6 仪表板组件双端
    "dashboard-component-dual": _DASHBOARD_COMPONENT_DUAL_WORKFLOW,
}

# 数据驱动场景：workflow 末尾追加 PLATFORM_API_QUICK_REF，让 外部 agent 拿到
# 写代码必备的 listPageBusinessData / detailBusinessData / form/save 等运行时 API。
# form-component-dual / layout / plugin / web-login 不需要（不调表单数据接口）。
_DATA_DRIVEN_SCENES = {"form-page", "menu-page", "form-list", "mobile-page"}


def get_full_workflow(scene_type: str) -> str:
    """按 scene_type 拿完整开发规范（critical rules / mixin / 目录铁则 / 自检清单
    + 数据驱动场景的运行时 API 速查）。

    给 外部 agent 通过 MCP 工具 get_dev_scene_full_workflow 拉取，注入到当前
    chat context。返回 markdown 字符串，agent 应该把它视为开发本场景的 single
    source of truth。

    没写完整指南的场景返回通用兜底（指向 list_dev_scenes / get_dev_scene_spec）。
    """
    body = _WORKFLOW_BY_SCENE.get(scene_type, _GENERIC_FALLBACK)
    out = _GENERIC_PREAMBLE + "\n\n---\n\n" + body
    # 数据驱动场景追加平台运行时 API 速查（写代码时直接抄）
    if scene_type in _DATA_DRIVEN_SCENES:
        from app.dev_scene_runtime_api import PLATFORM_API_QUICK_REF
        out += "\n\n" + PLATFORM_API_QUICK_REF
    return out


def has_full_workflow(scene_type: str) -> bool:
    """这个 scene 是否有完整 workflow（vs fallback）。"""
    return scene_type in _WORKFLOW_BY_SCENE


__all__ = ["get_full_workflow", "has_full_workflow"]
