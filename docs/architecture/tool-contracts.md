# 工具契约(契约)

> 主计划 Phase 1 / Phase 2C。定义工具副作用元数据的契约字段。
> **唯一事实源 = `backend/tool_registry.yaml`**(已是 single source + 双 drift check)。副作用字段作为**新列加进 yaml**,不另立服务事实源。`tool_contract_service` 只读 yaml 派生 + 暴露。drift check 须扩展覆盖新字段。

## 契约字段

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `name` | str | 工具名(与 `@mcp.tool` 注册名一致,drift check 保证) |
| `category` | enum | 现有域分类(create/update/delete/lifecycle/introspection/process/dev_workspace/...) |
| `read_only` | bool | 不产生任何写副作用 |
| `writes_workspace` | bool | 改本地工作区文件 |
| `writes_apaas` | bool | 写 aPaaS(建/改 模型/表单/权限/字典/流程) |
| `deploys_or_publishes` | bool | 触发部署/上传资产库/发布/republish |
| `requires_confirmation` | bool | 执行前需用户显式确认 |
| `idempotency` | enum | `idempotent` / `not_idempotent` / `unknown` |
| `failure_codes` | list[str] | 已知业务错误码(对齐 mcp_envelope error_code) |

## 确认要求规则(域模型已定)

- `read_only=true` → `requires_confirmation=false`。
- `writes_apaas=true` 且 细粒度字段 update → 可 `requires_confirmation=false`。
- `deploys_or_publishes=true` → **`requires_confirmation=true`**(deploy/publish/republish 必须确认)。
- 整包/整文件重写类自开发 patch → `requires_confirmation=true`(阈值见 [deployment-truth.md](deployment-truth.md) 与 patch 守卫)。

## 关键工具的契约(Phase 2C 须落实或明确不可用)

| 工具 | read_only | writes_apaas | deploys | confirm |
| --- | --- | --- | --- | --- |
| `list_apaas_app_*`(introspection) | ✅ | | | |
| `create_*` / `update_*` / `configure_permissions` | | ✅ | | 字段级否 |
| `upload_dev_workspace_to_asset_library` | | | ✅ | ✅ |
| `deploy_dev_workspace_to_app` | | ✅ | ✅ | ✅ |
| `republish_apaas_app` | | ✅ | ✅ | ✅ |
| `get_current_workspace_app_status` | ✅ | | | |

要么按上表暴露正确契约,要么**明确标记不可用并给原因**(让 CodingAgent 能查能力而非幻觉一个不存在的操作)。

## 治理(现状,须保持)

- `tool_registry.yaml` 为白名单单一事实源;`tool_registry.py:load()` 缓存 + fail-fast 校验。
- 双 drift check:静态 AST(`test_tool_registry.py` 扫 `mcp_tools/*.py` 的 `@mcp.tool` 名)+ 运行时(`mcp_server.py` 比 yaml vs FastMCP 注册)。运行时只 log warning 不 raise(怕阻断启动)。
- 副作用新字段加入后,**两层 drift check 都要覆盖**(yaml 字段完整性 + 与实现一致)。

## 业务事件域注意

业务事件类工具(`category==business_event`)运行时被 ai_chat 白名单 `_paused` 屏蔽,但 coding 栈和外部 MCP 调用方不经此过滤,仍能建坏事件。契约层应标记 `requires_confirmation=true` 或在 server 侧 gate(需要时)。
