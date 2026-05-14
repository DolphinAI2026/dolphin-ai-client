# ai-builder 三大 agent 工具分配矩阵 + 接入指南

> v1.0 / 2026-05-14
> 用途：dolphin builder 配置 3 个 agent（ai-builder / ai-coding / vibe-coding）时
> 对照本文档挂 MCP 服务、贴 prompt、传 skill。

---

## 三个 agent 角色边界

| Agent | 定位 | 用户场景 |
|---|---|---|
| **ai-builder** | aPaaS 应用搭建专家 | "我想做个请假管理"→设计文档→生成应用→部署→改动→发布 |
| **ai-coding** | aPaaS 二次开发专家（自开发模版包） | "给请假表单加个 Excel 导出按钮"→写前端组件/后端接口→打包上传 apaas |
| **vibe-coding** | 纯全代码开发助手（跟 aPaaS 无关） | "做个仪表盘 Vue 项目"→搭项目→写代码→跑→预览 |

边界铁律：
- **ai-builder 不写代码**，只产文档 + 配置应用
- **ai-coding 写代码但绑 aPaaS**，必须挂载到某个 apaas 应用
- **vibe-coding 写代码但跟 aPaaS 无关**，独立项目

---

## MCP 服务接入

我们 mcp-server 当前**暴露一个统一入口**（80 工具）：

```
URL:  https://df-aigc.dfy.definesys.cn/mcp-server/api/mcp/mcp
Auth: Bearer <MCP_API_KEYS 里的 key>
```

3 个 agent 都挂这一个 service — 工具按 prompt 里的「能用工具」「禁用工具」白名单约束。

**未来优化**（待实施）：mcp-server 拆 3 个 mount path 让 dolphin 分别挂：
- `/api/mcp-builder/mcp` — 35 工具
- `/api/mcp-coding/mcp` — 30 工具
- `/api/mcp-vibe/mcp` — 11 工具

---

## 工具分配矩阵（80 个 MCP 工具 × 3 agent）

图例：✓ = agent 主要使用 | △ = 偶尔使用 | ✗ = 禁止使用 | — = 不相关

### A. 平台环境（公共，3 agent 都用）

| 工具 | builder | coding | vibe |
|---|---|---|---|
| `list_platform_envs` | ✓ | ✓ | — |

### B. aPaaS 应用内省（公共，builder/coding 主用）

| 工具 | builder | coding | vibe |
|---|---|---|---|
| `list_apaas_apps_in_env` | ✓ | ✓ | — |
| `get_application` | ✓ | △ | — |
| `get_apaas_app_overview` | ✓ | ✓ | — |
| `list_apaas_app_menus` | ✓ | ✓ | — |
| `list_apaas_app_models` | ✓ | ✓ | — |
| `list_apaas_models_in_env` | ✓ | △ | — |
| `list_apaas_app_dicts` | ✓ | ✓ | — |
| `list_apaas_app_roles` | ✓ | ✓ | — |
| `list_apaas_form_views` | ✓ | ✓ | — |
| `list_apaas_form_components` | ✓ | ✓ | — |
| `list_apaas_form_permissions` | ✓ | △ | — |
| `list_my_applications` | ✓ | ✓ | — |
| `check_app_code_conflict` | ✓ | — | — |

### C. ai-builder 专属：应用生命周期 + 文档流

| 工具 | builder | coding | vibe |
|---|---|---|---|
| `get_apaas_doc_template_spec` | ✓ | — | — |
| `parse_design_doc` | ✓ | — | — |
| `validate_apaas_builder_doc` | ✓ | — | — |
| `validate_builder_doc` | ✓ | — | — |
| `submit_design_doc` | ✓ | — | — |
| `generate_app_from_doc` | ✓ | — | — |
| `update_app_from_doc` | ✓ | — | — |
| `get_change_plan` | ✓ | — | — |
| `execute_change_plan` | ✓ | — | — |
| `deploy_application` | ✓ | △ | — |
| `publish_application` | ✓ | — | — |

### D. ai-builder 专属：aPaaS 精细配置（不走 SPEC，直接 CRUD）

| 工具 | builder | coding | vibe |
|---|---|---|---|
| `create_apaas_app_roles` | ✓ | — | — |
| `update_apaas_app_role` | ✓ | — | — |
| `delete_apaas_app_role` | ✓ | — | — |
| `create_apaas_app_dict` | ✓ | — | — |
| `update_apaas_app_dict` | ✓ | — | — |
| `disable_apaas_app_dict` | ✓ | — | — |
| `add_apaas_dict_option` | ✓ | — | — |
| `update_apaas_dict_option` | ✓ | — | — |
| `disable_apaas_dict_option` | ✓ | — | — |
| `update_apaas_app_model` | ✓ | — | — |
| `add_apaas_model_field` | ✓ | — | — |
| `update_apaas_model_field` | ✓ | — | — |
| `disable_apaas_model_field` | ✓ | — | — |
| `create_apaas_form_menu` | ✓ | — | — |
| `delete_apaas_app_menu` | ✓ | — | — |
| `delete_apaas_app_form` | ✓ | — | — |
| `update_apaas_form_component` | ✓ | — | — |
| `set_apaas_form_permissions` | ✓ | — | — |
| `set_apaas_app_access` | ✓ | — | — |
| `set_apaas_app_process` | ✓ | — | — |

### E. ai-builder 专属：业务数据查询

| 工具 | builder | coding | vibe |
|---|---|---|---|
| `query_apaas_business_data` | ✓ | △ | — |

### F. ai-coding 专属：自开发场景规范

| 工具 | builder | coding | vibe |
|---|---|---|---|
| `list_dev_scenes` | — | ✓ | — |
| `get_dev_scene_spec` | — | ✓ | — |
| `get_dev_scene_full_workflow` | — | ✓ | — |

### G. ai-coding 专属：Workspace 文件操作

| 工具 | builder | coding | vibe |
|---|---|---|---|
| `create_dev_workspace` | — | ✓ | — |
| `get_dev_workspace_status` | — | ✓ | — |
| `read_workspace_file` | — | ✓ | — |
| `write_workspace_files` | — | ✓ | — |
| `edit_workspace_files` | — | ✓ | — |
| `glob_workspace` | — | ✓ | — |
| `grep_workspace` | — | ✓ | — |
| `run_workspace_command` | — | ✓ | — |
| `save_dev_spec` | — | ✓ | — |
| `import_zip_to_workspace` | — | ✓ | — |

### H. ai-coding 专属：后端自开发模版包

| 工具 | builder | coding | vibe |
|---|---|---|---|
| `init_apaas_backend_workspace` | — | ✓ | — |
| `lint_apaas_backend_workspace` | — | ✓ | — |
| `doctor_apaas_backend_workspace` | — | ✓ | — |

### I. ai-coding 专属：自开发发布链路

| 工具 | builder | coding | vibe |
|---|---|---|---|
| `enable_apaas_self_dev_config` | — | ✓ | — |
| `list_apaas_app_dev_kits` | — | ✓ | — |
| `attach_dev_packages_to_apaas_app` | — | ✓ | — |
| `republish_apaas_app` | — | ✓ | — |
| `create_apaas_self_dev_menu` | — | ✓ | — |
| `list_apaas_resource_pool_kits` | — | ✓ | — |
| `upload_external_zip_to_apaas` | — | ✓ | — |
| `publish_dev_workspace` | — | ✓ | — |

### J. vibe-coding 专属：全代码工具集（vibe_*）

| 工具 | builder | coding | vibe |
|---|---|---|---|
| `vibe_create_workspace` | — | — | ✓ |
| `vibe_get_workspace_status` | — | — | ✓ |
| `vibe_read_file` | — | — | ✓ |
| `vibe_write_file` | — | — | ✓ |
| `vibe_edit_file` | — | — | ✓ |
| `vibe_glob` | — | — | ✓ |
| `vibe_grep` | — | — | ✓ |
| `vibe_run_command` | — | — | ✓ |
| `vibe_todo_write` | — | — | ✓ |
| `vibe_http_check` | — | — | ✓ |

---

## 三 agent 工具数汇总

| 主用 (✓) | 偶尔 (△) | 合计 |
|---|---|---|
| **ai-builder**: 35 | 2 (deploy_application + query_apaas_business_data) | 37 |
| **ai-coding**: 30 | 4 (get_application + list_apaas_models_in_env + list_apaas_form_permissions + query_apaas_business_data) | 34 |
| **vibe-coding**: 11 | 0 | 11 |

---

## Skill 文档配套

每个 agent 在 dolphin builder「Skills」面板挂载以下 markdown（本地上传）：

| Agent | Skill 文件 | 用途 |
|---|---|---|
| **ai-builder** | `docs/skills/ai-builder/workflow.md` | 应用搭建标准工作流（需求→文档→生成→部署→发布） |
| **ai-builder** | `docs/skills/common/apaas-introspection.md` | aPaaS 平台元数据查询规范（共享） |
| **ai-coding** | `docs/skills/ai-coding/workflow.md` | 二次开发标准工作流 |
| **ai-coding** | `docs/skills/ai-coding/backend-dev.md` | 后端 Java 自开发（16 坑 + init/lint/doctor） |
| **ai-coding** | `docs/skills/ai-coding/frontend-component-dev.md` | 前端组件自开发（Vue 2.7 / Element UI / 9 scene） |
| **ai-coding** | `docs/skills/common/apaas-introspection.md` | （共享） |
| **vibe-coding** | `docs/skills/vibe-coding/workflow.md` | SPEC-driven 全代码工作流 |

---

## 接入操作步骤（dolphin builder UI）

每个 agent 重复以下步骤：

1. 进 dolphin builder → 编辑 agent
2. **人设提示词**：复制对应 `docs/skills/{agent}/prompt.md` 全文粘贴
3. **工具 → MCP 服务**：「+ 添加」 → 输入 mcp-server URL + Bearer key → 测试连接 + 保存
   - 同一个 URL 三个 agent 都挂（暂时不拆 service）
4. **工具 → Skills**：「+ 添加」→ 本地上传对应 skill .md 文件（按上表）
5. **记忆 → 全局记忆**：加 `env: <租户默认 alias>`（如 `env: pg`）
6. **模型**：选 GPT-5.5 / 深度思考（推荐）
7. **保存** + **发布**

---

## 公共全局记忆 kv 建议

每个用户首次跟 agent 对话前，dolphin admin 给 agent 配 per-user 全局记忆：

```
env: <租户的环境 alias>     # 如 pg / dev8 / trial / fudan
```

这样 agent 不用每次问"你想部署到哪个环境"，直接默认走 env alias。

---

## 自检 checklist（接入完毕）

- [ ] 3 个 agent 都挂了 mcp-server（80 工具）
- [ ] 每个 agent 的 prompt 已替换为 `prompt.md`
- [ ] Skills 按上表挂齐
- [ ] 全局记忆 `env: <alias>` 已配
- [ ] 模型选了支持 tool calling 的（GPT-5.5+）
- [ ] 跟每个 agent 测一句简单问候验证连通

测试用例：
- **ai-builder**: "帮我看下我有哪些应用" → 应调 `list_my_applications`
- **ai-coding**: "我想给请假表单加个 Excel 导出按钮" → 应调 `list_dev_scenes` → `get_dev_scene_spec`
- **vibe-coding**: "做个 todo list Vue 项目" → 应调 `vibe_create_workspace`
