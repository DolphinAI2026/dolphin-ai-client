# 域模型与 ID 规则(契约)

> 主计划 Phase 1。这是 AI Builder 域对象与标识符的唯一定义。所有 backend helper / service / 测试中对这些 ID 的处理必须遵守本文。
> 真相边界铁律:**aPaaS 持有 租户/应用/权限 数据的唯一真相;AI Builder 持有 助手运行态 / 草稿 / patch / 工作区绑定 / 交付产物 / 部署观测。**

## 域对象

| 对象 | Owner | 含义 | 关键存储 |
| --- | --- | --- | --- |
| `Tenant` | aPaaS / AI Builder 影子 | 组织边界 | `tenants`(影子) |
| `User` | AI Builder auth | 会话/工作区/管理动作执行者 | `users` |
| `Application` | AI Builder | 本地/影子应用记录 | `applications`(`config_preview` 等) |
| `APaaSApp` | aPaaS | 平台真实低代码应用 | 仅经 `apaas_app_id` 引用,无本地表 |
| `Conversation` | AI Builder | 聊天/coding 讨论历史 | `conversations` / `ai_chat_sessions` |
| `Artifact` | AI Builder | 需求/设计文档/UI 草稿/源码包/生成文件 | `ai_chat_artifacts` / spec 文档表 |
| `Workspace` | AI Builder 本地 FS | 可编辑自开发工作区(带本地 diff 态) | 本地目录 + `.workspace.json` |
| `DevAsset` | AI Builder catalog | 自开发页面/组件/后端包资产 | 工作区目录 + catalog |
| `Deployment` | AI Builder 观测 + aPaaS 动作 | 上传/发布/republish 尝试及当前已知结果 | `deploy_records` + 状态服务 |

**DevAsset 是一等公民**:可绑定 Application,也可独立存在(WorkspaceCatalogPage 同时展示已绑/未绑资产)。`Application → APaaSApp → Workspace → DevAsset` 链只对"已绑定"成立;DevAsset 不强依赖 Application。任何按"DevAsset 必属某 app"假设的代码都是 bug。

## 标识符规则

| ID | 含义 | 规则 |
| --- | --- | --- |
| `app_id` | AI Builder 应用主键 | `Application.id`。本地身份。 |
| `apaas_app_id` | aPaaS 平台应用 ID | 所有配置/生成/发布对 aPaaS 的动作必须锚定它。它是 aPaaS 真相侧的句柄,不可与 `app_id` 互换。 |
| `workspace_id` | AI Builder 可编辑工作区 ID | 常映射本地目录。经 `workspace_binding_service` 解析归属,不在路由里手猜。 |
| `project_id` | **禁止当统一概念** | 每条路径必须标明它指 app 绑定还是协作 project。不同语义不可混用。 |
| `coding_app_id` | coding/自开发绑定的兼容句柄 | 存于 `Conversation.coding_app_id`。**只收口不迁 schema**(归一在 `workspace_binding_service` 后面)。新代码不直接读它,经 service。 |

## 绑定关系(由 `workspace_binding_service` 唯一解析)

- `app_id ↔ workspace_id`(应用绑定的工作区)
- `workspace_id → app_id`(反查)
- `dev_asset_id → app_id`(可为空 = 未绑定资产)
- `project_id` / `coding_app_id` 的兼容查找

**禁止**:任何 route 函数手猜 `project_id` 是 project 还是 application。所有绑定解析与访问检查走 service。

## 写 aPaaS 的确认要求(由 `tool_contract_service` 编码)

- `create_*` / `update_*` / `configure_permissions`:写 aPaaS。细粒度字段 update 可不确认。
- `deploy` / `publish` / `republish`:**必须用户确认**。
- 详见 [tool-contracts.md](tool-contracts.md)。
