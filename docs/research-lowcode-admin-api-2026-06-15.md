# 低代码租户后台 API 调研清单

- 日期: 2026-06-15
- 调研目标: `https://apaas-trial.definesys.cn/platform/828940713101099009/admin/tenant-log`
- 租户 ID: `828940713101099009`
- 前端版本: 页面可见 `v5.0.0-20260427.2.11820.20260508`
- 调研方式: 当前登录后台页面观察 + 前端静态包路径提取
- 结论状态: endpoint 路径已初步确认; 请求 payload/响应 schema 需继续用 DevTools 网络面板补样本

## 1. 调研边界

本次抓取重点是确定 AI Builder 接入低代码后台时需要覆盖的 API 域, 不是完整接口协议反推。

已完成:

- 从前端 bundle 提取约 790 个 `/xdap-admin`、`/xdap-app`、`/xdap-plugin` 路径。
- 按应用、配置、流程事件、权限、自开发、服务集成、运维等域聚合。
- 结合后台 UI 验证租户菜单和单应用详情页的资源边界。

未完成:

- 未逐个接口抓 payload 和响应 schema。
- 未确认所有接口 method; 静态路径只能证明前端存在调用。
- 未抓到「提示词管理」完整 CRUD endpoint。
- 未复刻登录鉴权头; 后续应通过浏览器 DevTools 网络面板或后端代理日志补充。

## 2. API 前缀与鉴权注意

静态包里出现的规范化路径以 `/xdap-app`、`/xdap-admin` 为主。当前 trial 前端可能经 `/backend/xdap-app/...` 代理到后端, 历史业务事件抓包也证明 trial/prod 的 base path 可能不同。

接入设计建议:

| 项 | 策略 |
| --- | --- |
| Base URL | 按环境配置, 不硬编码 `/backend` |
| Tenant | 每个请求绑定当前 `tenantId` |
| App | 应用级 endpoint 绑定 `appId`/`apaas_app_id` |
| Auth | 复用平台登录态或后端安全代理, 不在前端/日志暴露 token |
| Version | connector 记录平台版本, 为路径差异留适配层 |

历史业务事件抓包中出现过这些 header: `xdaptoken`、`xdaptenantid`、`xdaptimestamp`、`appid`、`cookie: token=...`、`content-type`、`rsa-public-key`。是否所有后台域都一致, 需要后续抓包确认。

## 3. 后台 UI 覆盖的资源域

租户后台可见资源域:

- 应用管理、应用发布。
- 资源配置: 数据模型、业务对象、表单管理、业务事件。
- 拓展功能: 服务集成、自开发管理、自开发权限、公式规则。
- 员工与权限: 员工与部门、账号安全、角色管理、应用权限。
- 基础数据: 数据字典、数据源管理、插件管理。
- 运维: 租户日志、异步任务管理。
- AI 管理: 模型与提供商管理、提示词管理。
- 流程中心: 流程管理、流程实例、异常/超时实例、流程授权、流程转办。

单应用详情页可见资源域:

- 应用信息、访问权限、菜单功能、业务事件、高级设置、版本信息、资源管理、权限管理、应用日志。
- 菜单功能内有「AI 功能创建」入口。
- 资源管理内可进入数据模型、业务对象、表单管理、流程管理、服务集成、自开发管理、角色管理、数据字典、数据源管理。

## 4. Endpoint 域统计

前端静态包提取后按前两段 path 粗分, 重点域数量如下:

| 域 | 数量 | 说明 |
| --- | ---: | --- |
| `/xdap-app/formConfig` | 44 | 表单、列表页、权限、业务规则、版本 |
| `/xdap-app/apaasApplications` | 36 | 应用清单、详情、安装、导入导出、发布 |
| `/xdap-app/event` | 32+ | 业务事件、执行历史、触发、模拟 |
| `/xdap-app/process` | 27+ | 流程配置、流程版本、授权转办、节点重试 |
| `/xdap-app/business` | 23 | 业务数据查询 |
| `/xdap-app/serviceIntegration` | 21 | 服务集成、外部动作、认证、日志 |
| `/xdap-app/dataModel` | 20 | 数据模型、字段、SQL、导出 |
| `/xdap-app/menu` | 20+ | 菜单、菜单权限、表单菜单 |
| `/xdap-app/security` | 18 | 角色、资源、用户角色、应用管理员 |
| `/xdap-app/permissionCenter` | 13 | 访问/功能/高级权限 |
| `/xdap-app/selfdevelopment` | 14 | 自开发包 |
| `/xdap-app/selfDevPermission` | 14 | 自开发权限 |
| `/xdap-app/taskcenter` | 7 | 异步任务 |
| `/xdap-app/health` | 5 | 健康指标 |
| `/xdap-app/agent/ai` | 2 | AI 集成配置 |
| `/xdap-admin/processCenter` | 5 | 租户级流程实例/异常/授权/转办 |
| `/xdap-admin/operateLog` | 4 | 平台操作日志 |

## 5. P0 只读接口候选

### 5.1 应用与租户资产

| 能力 | Endpoint |
| --- | --- |
| 应用列表 | `/xdap-app/apaasApplications/listApp` |
| 应用详情 | `/xdap-app/apaasApplications/queryAppById` |
| 应用状态列表 | `/xdap-app/apaasApplications/status/queryAppList` |
| 健康视角应用列表 | `/xdap-app/apaasApplications/health/queryAppList` |
| 已安装应用 | `/xdap-app/apaasApplications/query/allTenantInstalledApp` |
| 应用环境信息 | `/xdap-app/apaasApplications/queryAppEnvInformationByAppId` |
| 安装日志 | `/xdap-app/apaasApplications/query/installLogList` |

AI Builder 用法:

- 租户应用清单。
- 应用上线/下线状态。
- 应用复杂度和最近安装/发布线索。

### 5.2 数据模型与业务对象

| 能力 | Endpoint |
| --- | --- |
| 数据模型列表 | `/xdap-app/dataModel/query/list` |
| 数据模型详情 | `/xdap-app/dataModel/query/detail` |
| 应用内模型详情 | `/xdap-app/dataModel/query/detail/app` |
| 模型字段 | `/xdap-app/dataModel/query/modelWithField` |
| 表单可用模型 | `/xdap-app/dataModel/query/listInForm` |
| 业务对象列表 | `/xdap-app/businessObject/query/allBusinessObjectList` |
| 业务对象详情 | `/xdap-app/businessObject/query/propertiesInfo` |
| 业务对象关系 | `/xdap-app/businessObject/query/boRelationship` |

AI Builder 用法:

- 建立数据层节点。
- 识别表单、列表页、业务事件引用的数据对象。
- 发现字段缺失、重复模型、模型和表单不一致。

### 5.3 表单、列表页、菜单

| 能力 | Endpoint |
| --- | --- |
| 全部表单配置 | `/xdap-app/formConfig/query/allFormConfigList` |
| 当前应用表单 | `/xdap-app/formConfig/query/currentAppListAllFormConfig` |
| 详情页配置 | `/xdap-app/formConfig/query/detailPageConfigById` |
| 列表页配置 | `/xdap-app/formConfig/query/listPageConfigById` |
| 单列表页配置 | `/xdap-app/formConfig/query/singleListPageConfigById` |
| 列表页视图与查询条件 | `/xdap-app/formConfig/query/listPageViewsWithQueryList` |
| 表单权限 | `/xdap-app/formConfig/query/formPermissionByFormId` |
| 高级表单权限 | `/xdap-app/formConfig/query/advancedFormPermissionByFormId` |
| 菜单树 | `/xdap-app/menu/query/manageAppMenu` |
| 菜单详情 | `/xdap-app/menu/query/menuDetails` |
| 表单菜单 | `/xdap-app/menu/queryAllFormMenu` |

AI Builder 用法:

- 配置体检核心输入。
- 判断菜单是否挂表单、自开发页面或流程入口。
- 检查列表页是否缺少查询条件、视图、按钮、权限。

### 5.4 流程与业务事件

| 能力 | Endpoint |
| --- | --- |
| 应用流程列表 | `/xdap-app/process/query/processList` |
| 全部流程列表 | `/xdap-app/process/query/allProcessList` |
| 流程配置详情 | `/xdap-app/process/query/processConfigDetail` |
| 流程节点 | `/xdap-app/process/query/processNodeList` |
| 流程状态 | `/xdap-app/process/query/processStatus` |
| 流程版本列表 | `/xdap-app/process/query/processConfigVersionList` |
| 业务事件租户列表 | `/xdap-app/event/query/allEventList` |
| 应用业务事件列表 | `/xdap-app/event/query/list` |
| 业务事件详情 | `/xdap-app/event/query/detail` |
| 业务事件树 | `/xdap-app/event/queryTrees` |
| 事件执行历史 | `/xdap-app/event/query/exeHistory/list` |

AI Builder 用法:

- 发现流程/事件与表单、业务对象的依赖。
- 分析失败事件和异常流程。
- 生成流程自动化、事件自动化改造建议。

### 5.5 权限、角色、自开发权限

| 能力 | Endpoint |
| --- | --- |
| 访问权限 | `/xdap-app/permissionCenter/listVisitPermission` |
| 功能权限 | `/xdap-app/permissionCenter/listOperatePermission` |
| 高级权限 | `/xdap-app/permissionCenter/listAdvancedPermission` |
| 权限菜单 | `/xdap-app/permissionCenter/menuList` |
| 权限页面视图 | `/xdap-app/permissionCenter/pageViewList` |
| 应用角色 | `/xdap-app/security/query/roles` |
| 角色资源 | `/xdap-app/security/query/roleResources` |
| 角色列表 | `/xdap-app/roles/query/rolesList` |
| 自开发权限列表 | `/xdap-app/selfDevPermission/list/byPermNameAndPermCode` |
| 菜单自开发权限 | `/xdap-app/selfDevPermission/page/permsByMenuId/likeNameOrCode` |
| 自开发权限访问 | `/xdap-app/selfDevPermission/list/access` |

AI Builder 用法:

- 识别权限缺口、黑名单、角色覆盖范围。
- 检查自开发页面是否有权限对象和菜单绑定。
- 生成权限变更 diff。

### 5.6 自开发与服务集成

| 能力 | Endpoint |
| --- | --- |
| 全部自开发包 | `/xdap-app/selfdevelopment/query/allDevelopmentKit` |
| 应用自开发包 | `/xdap-app/selfdevelopment/query/appDevelopmentKitByAppId` |
| 应用自开发包详情 | `/xdap-app/selfdevelopment/query/developmentKitByAppId` |
| 自开发包模糊查询 | `/xdap-app/selfdevelopment/query/likeDevelopmentKit` |
| 自开发类型 | `/xdap-app/selfdevelopment/typeList` |
| 下载自开发包 | `/xdap-app/selfdevelopment/downloadFile` |
| 服务集成列表 | `/xdap-app/serviceIntegration/query/allServiceIntegration` |
| 按类型查询服务集成 | `/xdap-app/serviceIntegration/query/serviceIntegrationByType` |
| 外部动作列表 | `/xdap-app/serviceIntegration/external/action/query/list` |
| 外部动作日志 | `/xdap-app/serviceIntegration/external/action/logList` |
| 服务函数列表 | `/xdap-app/serviceFunction/query/allServiceFunctionByServiceCode/event` |

AI Builder 用法:

- 建立自开发资产与应用、菜单、权限、服务集成的关系。
- 找到孤立资产、重复包、未授权页面。
- 支持进入 IDE 二次开发。

### 5.7 运维日志、任务、健康

| 能力 | Endpoint |
| --- | --- |
| 租户操作日志 | `/xdap-app/operateLog/query/operateLogs` |
| 操作对象 | `/xdap-app/operateLog/query/operateObjects` |
| 日志存储天数 | `/xdap-app/operateLog/query/storageDays` |
| 应用异步任务 | `/xdap-app/taskcenter/queryPackageTaskForAdmin` |
| 子任务实例 | `/xdap-app/taskcenter/querySubTaskInstances` |
| 任务结果 | `/xdap-app/taskcenter/getPackageTaskResult` |
| 流程实例 | `/xdap-admin/processCenter/list/processInstances` |
| 异常流程实例 | `/xdap-admin/processCenter/list/errorProcessInstances` |
| 流程授权 | `/xdap-admin/processCenter/list/processAuth` |
| 流程转办 | `/xdap-admin/processCenter/list/processForward` |
| 健康信息 | `/xdap-app/health/query/info` |
| CPU | `/xdap-app/health/query/cpuInfo` |
| 堆内存 | `/xdap-app/health/query/heapInfo` |
| 线程 | `/xdap-app/health/query/theadInfo` |

AI Builder 用法:

- 形成运维诊断中心。
- 把失败任务、异常流程、最近配置变更关联起来。
- 生成可执行排障步骤。

## 6. P1 写入接口候选

这些接口存在于前端包, 但接入 AI Builder 前必须补 payload 样本、确认影响范围, 并接入确认门。

| 域 | Endpoint 示例 | 风险 |
| --- | --- | --- |
| 应用 | `/xdap-app/apaasApplications/saveApp`、`deleteAppById`、`publish/storeApp` | 高 |
| 数据模型 | `/xdap-app/dataModel/add`、`update`、`delete` | 高 |
| 表单 | `/xdap-app/formConfig/save/formConfigDetail` | 高 |
| 列表页 | `/xdap-app/formConfig/update/listPageConfig` | 中 |
| 表单权限 | `/xdap-app/formConfig/update/formPermission`、`update/advancedFormPermission` | 高 |
| 菜单 | `/xdap-app/menu/save/menu`、`delete/menu` | 高 |
| 业务事件 | `/xdap-app/event/add/event`、`save/event`、`del/event`、`operate/status` | 高 |
| 流程 | `/xdap-app/process/save/processConfig`、`close/processConfig`、`open/processVersion` | 高 |
| 权限中心 | `/xdap-app/permissionCenter/editAccessPermission`、`editOperatePermission`、`editAdvancedPermission` | 高 |
| 自开发 | `/xdap-app/selfdevelopment/add/developmentKit`、`update/developmentKit`、`delete/developmentKit` | 高 |
| 自开发权限 | `/xdap-app/selfDevPermission/insert/permission`、`update/permission`、`batchSave/menuIdAndPermIds` | 高 |
| 服务集成 | `/xdap-app/serviceIntegration/save/serviceIntegration`、`external/action/save` | 高 |
| 运维任务 | `/xdap-app/taskcenter/retryTaskPackage`、`abortTaskPackage` | 中/高 |
| 流程运维 | `/xdap-app/process/add/procAuth`、`update/procForward`、`eventNodeRetry` | 高 |

## 7. AI 管理接口现状

已在静态包中看到:

- `/xdap-app/agent/ai/integration/config/query`
- `/xdap-app/agent/ai/integration/config/save`

后台 UI 可见:

- 模型与提供商管理: 已有通义千问提供商卡片。
- 提示词管理: 列表显示 81 条提示词, 包括权限对象生成、过滤条件生成、公式规则条件生成、流程上下文等。

待补抓:

- 提供商列表、详情、新增、编辑、禁用、删除。
- 模型列表、模型配置、默认模型。
- 提示词列表、详情、新增、编辑、发布、停用、删除。
- 提示词与用途场景、状态、版本、应用/租户范围的关系。

AI Builder 接入建议:

- P0 只读 AI 配置和提示词清单, 用于判断平台 AI 能力现状。
- P1 再做 Prompt 治理建议, 不直接覆盖平台内置提示词。
- 平台内置提示词属于高风险配置, 写入必须有二次确认和版本备份。

## 8. 与 AI Builder 能力的映射

| AI Builder 能力 | 主要 API 域 |
| --- | --- |
| 租户应用总览 | `apaasApplications`, `operateLog`, `taskcenter` |
| 单应用资源图谱 | `menu`, `dataModel`, `businessObject`, `formConfig`, `process`, `event`, `permissionCenter`, `selfdevelopment`, `serviceIntegration` |
| 配置体检 | `formConfig`, `menu`, `dataModel`, `permissionCenter`, `roles` |
| 二次开发辅助 | `selfdevelopment`, `selfDevPermission`, `menu`, `serviceIntegration` |
| 运维诊断 | `operateLog`, `taskcenter`, `processCenter`, `health`, `event history` |
| 运营报告 | 应用清单 + 资源规模 + 风险 finding + 日志/任务趋势 |
| AI 治理 | `agent/ai/integration/config`, 待补 Prompt/Provider API |

## 9. 后续抓包计划

1. 用 DevTools 网络面板抓 5 个代表页面:
   - 应用管理列表。
   - 单应用详情页/菜单功能。
   - 单应用资源管理/表单管理。
   - 自开发管理。
   - 提示词管理。
2. 每个页面至少保存:
   - endpoint、method、query、body、response sample。
   - 必需 headers, 尤其 tenant/app 相关字段。
   - 错误响应格式。
3. 建立 `LowCodeAdminConnector` endpoint registry。
4. 先实现只读工具:
   - `scan_tenant_apps`
   - `get_app_resource_graph`
   - `analyze_app_config_health`
   - `analyze_app_dev_assets`
   - `analyze_app_ops_signals`
5. 再为写接口补 diff/confirmation contract。

## 10. 原始提取摘要

本次本地临时提取目录:

```text
/tmp/ai-builder-apaas-api-scan
```

主要静态包:

```text
app.js
chunk-x-apaas.js
chunk-vendors.js
```

提取命令产物:

```text
/tmp/ai-builder-apaas-api-scan/endpoints.txt
```

该临时文件包含约 790 个唯一 endpoint。后续如果需要长期留档, 建议把确认后的 endpoint registry 落到代码或 `docs/reference` 中, 不直接提交未经验证的全量静态提取结果。
