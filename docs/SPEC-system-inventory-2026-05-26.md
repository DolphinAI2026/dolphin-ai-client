# aPaaS Builder AI — 系统现状 SPEC

> 2026-05-26 实测盘点 (非空想方案)
> 目的: 看清"低代码这块到底有多乱", 再决定怎么重构

---

## 1. 顶层架构

```
┌─────────────────────────── 用户视角 4 条对话入口 ──────────────────────────┐
│                                                                            │
│  /ai-builder/chat       /ai-coding/chat      /vibe-coding/chat            │
│  (AIChatPage)           (CodingPage)         (vibe page)                  │
│  ai-builder agent       ai-coding agent       vibe agent                  │
│  35 tools 白名单        30 tools             11 tools                     │
│                                                                            │
│  /ai-builder/chat?app_id=N  ← ChatPage 右侧 ConfigAssistant (新加)        │
│                                58 tools 白名单 (手工维护)                 │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
                                    ↓
                  统一接 mcp-server (k8s, 80 工具暴露)
                                    ↓
                  调 apaas 平台 API (/xdap-app/* + /common/resource/*)
```

**问题**: 同一个"加表单"操作有 4 个入口, 每个入口工具白名单+prompt 都不同, 行为不一致。

---

## 2. 仓库代码量盘点

| 模块 | LOC | 备注 |
|---|---|---|
| `backend/app/routes/` 47 个文件 | 24836 | 24K 行 |
| `backend/app/mcp_server.py` | 7069 | 单文件 7K 行 (114 MCP 工具) |
| `backend/app/apaas_client.py` | 2240 | apaas 平台 API 调用层 |
| `backend/app/step_executor.py` | 2604 | SPEC 文档 → 资源生成 |
| `frontend/src/views/` 31 个 .vue | — | |
| `frontend/src/views/ChatPage.vue` | ~12K | 单文件 12K 行 ⚠️ |

**问题**: `mcp_server.py` 7K 单文件、`ChatPage.vue` 12K 单文件 — 已经到了维护边缘。

---

## 3. MCP 工具盘点 (114 个)

### 3.1 按业务域分类 (现状没有, 我现盘的)

#### A. 平台 / 应用元信息 (12 个) ✅
```
list_platform_envs, list_apaas_apps_in_env, list_my_applications,
get_application, get_apaas_app_overview, check_app_code_conflict,
list_apaas_models_in_env, list_apaas_business_events_in_tenant,
list_apaas_form_views, list_deploy_records, rollback_application,
list_my_applications
```

#### B. SPEC 文档流 — 全量生成/更新 (10 个)
```
get_apaas_doc_template_spec, parse_design_doc, validate_apaas_builder_doc,
validate_builder_doc, submit_design_doc, save_dev_spec,
generate_app_from_doc, update_app_from_doc,
get_change_plan, execute_change_plan,
deploy_application, publish_application
```

#### C. aPaaS 应用内省 (read) (10 个)
```
list_apaas_app_menus, list_apaas_app_models, list_apaas_app_dicts,
list_apaas_app_roles, list_apaas_form_components,
list_apaas_form_permissions, list_apaas_form_menus_for_event,
list_apaas_business_events, get_apaas_business_event_detail,
query_apaas_business_event_trees, query_apaas_business_data,
list_apaas_business_event_execution_history
```

#### D. 模型/字段 CRUD (5 个)
```
update_apaas_app_model, add_apaas_model_field,
update_apaas_model_field, disable_apaas_model_field
```

#### E. 字典 CRUD (6 个)
```
create_apaas_app_dict, update_apaas_app_dict, disable_apaas_app_dict,
add_apaas_dict_option, update_apaas_dict_option, disable_apaas_dict_option
```

#### F. 角色 / 权限 (4 个)
```
create_apaas_app_roles, update_apaas_app_role, delete_apaas_app_role,
set_apaas_form_permissions, set_apaas_app_access
```

#### G. 菜单 (8 个)
```
create_apaas_form_menu, create_apaas_self_dev_menu,
delete_apaas_app_menu, delete_apaas_app_form,
create_apaas_menu_group, set_apaas_menu_parent, rename_apaas_menu
```

#### H. 表单组件 (3 个)
```
update_apaas_form_component, bind_apaas_form_field_to_dict,
build_apaas_feature_from_spec   ← 高层 wrapper
```

#### I. 流程 (1 个)
```
set_apaas_app_process
```

#### J. 业务事件 (8 个)
```
create_apaas_business_event, save_apaas_business_event,
delete_apaas_business_event, create_form_event_with_python_code,
create_time_event_with_python_code, create_apaas_value_change_assignment_event,
```

#### K. 自开发模版包 / 自开发链路 (15 个) ⚠️ 重型
```
list_dev_scenes, get_dev_scene_spec, get_dev_scene_full_workflow,
create_dev_workspace, init_apaas_backend_workspace,
read_workspace_file, edit_workspace_files, write_workspace_files,
glob_workspace, grep_workspace,
run_workspace_command, lint_apaas_backend_workspace,
doctor_apaas_backend_workspace, import_zip_to_workspace,
publish_dev_workspace, upload_external_zip_to_apaas,
list_apaas_app_dev_kits, attach_dev_packages_to_apaas_app,
republish_apaas_app, get_dev_workspace_status
```

#### L. Vibe Coding (10 个) — 全代码项目
```
vibe_create_workspace, vibe_read_file, vibe_write_file, vibe_edit_file,
vibe_glob, vibe_grep, vibe_run_command, vibe_http_check,
vibe_todo_write, vibe_get_workspace_status
```

#### M. 浏览器自动化 (10 个)
```
browser_snapshot, browser_click, browser_type, browser_wait_for_text,
browser_press_key, browser_screenshot, browser_navigate,
browser_list_pages, browser_select_page,
browser_start_recording, browser_stop_recording
```

#### N. Config skill 自学习 (4 个)
```
save_config_skill, list_config_skills, get_config_skill, delete_config_skill
```

#### O. 数据库 / Quick DB (1 个)
```
query_apaas_business_data
```

**计数**: A12 + B12 + C12 + D4 + E6 + F5 + G7 + H3 + I1 + J6 + K20 + L10 + M11 + N4 = 113 (差 1 个属于 mixed, 不重要)

### 3.2 工具白名单不一致

| Agent / 入口 | 工具数 | 来源 |
|---|---|---|
| **ai-builder agent prompt** | 35 | `docs/skills/ai-builder/prompt.md` 手写白名单 |
| **ai-coding agent prompt** | 30 | `docs/skills/ai-coding/prompt.md` 手写白名单 |
| **vibe-coding agent prompt** | 11 | `docs/skills/vibe-coding/prompt.md` |
| **ChatPage ConfigAssistant** | 58 | `backend/app/routes/applications/__init__.py` `_CONFIG_CHAT_TOOL_WHITELIST` 集合常量 |

**问题**: 4 套白名单各自维护, 加新工具要改 4 个地方; 容易漏。

**例子**: 我前几天加 `set_apaas_app_process` 时只加到 ConfigAssistant 白名单, ai-builder agent 的 prompt 还没改 → builder 不知道。

---

## 4. 前端 31 个 .vue Views — 重复 / 冗余识别

### 4.1 对话相关 4 个 ⚠️ 严重重叠

| Page | 用途 | 路由 | 状态 |
|---|---|---|---|
| **AIChatPage** | builder agent 对话 | `/ai-builder/chat` | 主入口, 跟 builder agent 绑 |
| **ChatPage** | 应用配置 + 右侧 ConfigAssistant | `/ai-builder/chat?app_id=N` | **跟 AIChatPage 重名差点搞混** |
| **CodingPage** | coding agent 对话 + workspace | `/ai-coding/chat` | 跟 OnlineCodingPage 重叠? |
| **OnlineCodingPage** | online coding | `/coding` ? | 看不出跟 CodingPage 区别 |

**问题**: AIChatPage / ChatPage 同名, 内部逻辑完全不一样 — 改代码常错。

### 4.2 MCP 管理 2 个

| Page | 用途 |
|---|---|
| **McpHubPage** | MCP hub (按 service 看) |
| **McpToolsPage** | MCP tools list (按 tool 看) |

是否要合一? 看不到必要保留 2 个。

### 4.3 SPEC 文档 2 个

| Page | 用途 |
|---|---|
| **Generate** | 老 SPEC 生成入口 (?) |
| **SpecsPage** | 新 specs v2 list |
| **ProposalDetailPage** | proposal 详情 |

老 Generate 是不是 dead code?

### 4.4 偏后台运维类 (~7 个)

```
BuilderDevOpsPage, DbConnectionsPage, QuickDbPage,
RuntimePage, SandboxMonitorPage, PlatformEnvs, PlatformTenants,
PlatformAdminEmbed, McpHubPage, McpToolsPage,
TenantSelect, TenantUsers
```

跟"用户配应用"主流程关系不大, 可以归到 admin 二级菜单。

---

## 5. 后端 47 个 routes — 重复识别

### 5.1 Coding 相关 5 个 ⚠️

| Route | LOC | 注释 |
|---|---|---|
| `coding.py` | 3237 | 主 coding 平台 — workspace 建/装/构/IDE |
| `coding_v2.py` | 1348 | "v2" 新 workflow + SPEC start |
| `coding_v2_spec.py` | 275 | v2 SPEC 子路由 |
| `online_coding.py` | ? | "online" |
| `online_coding_runtime.py` | ? | "online runtime" |
| `vibe_coding_chat.py` | 468 | vibe 对话 |

**v1 / v2 共存**: 是不是 v1 该退役了?

### 5.2 SPEC / 需求 相关

```
spec.py, specs_v2.py, requirements.py, proposals.py,
generation_steps.py, incremental_update.py
```

老 spec.py vs 新 specs_v2.py — 共存。

### 5.3 MCP 相关 3 个

```
admin_mcp.py, builder_mcp.py, mcp_hub.py, mcp_platform.py
```

4 个 MCP 路由是不是太多?

### 5.4 Chat 相关

```
chat.py, ai_chat.py, config_chat_sessions.py, vibe_coding_chat.py
```

`chat.py` vs `ai_chat.py` 区别?

---

## 6. 混乱点 Top 5 (按严重程度)

### 🔴 P0 — 工具白名单 4 份散落
- 改一个工具要追 4 处
- 加新工具时容易漏 (我前几天踩过)
- **建议**: 建 `tool_registry.py` 单一真相 + 按 section/agent 派生白名单

### 🔴 P0 — ChatPage 12K 行 + mcp_server.py 7K 行
- 单文件巨大, 改风险高
- **建议**: ChatPage 拆 section 子组件; mcp_server.py 按业务域拆 (与上一条同步做)

### 🟡 P1 — 对话入口 4 个体验割裂
- builder chat / coding chat / vibe chat / config assistant
- 用户搞不清该用哪个; 同操作行为不一致
- **建议**: 收敛到 2 个 — 应用配置 (融合 builder + config assistant) + 全代码 (vibe)

### 🟡 P1 — v1 / v2 共存
- `coding.py` / `coding_v2.py`, `spec.py` / `specs_v2.py`
- 共存说明 v2 还没替代 v1
- **建议**: 决策 v1 是否退役; 退役就删

### 🟢 P2 — 31 个 view 里 ~10 个偏运维的
- 不是核心用户流程, 应当归到 admin 二级菜单
- **建议**: 主 nav 收敛 5-7 个; 其余归 admin

---

## 7. 你提的 6-section 设计对应到现状

| 你的 section | 我们现有的工具 | UI 现状 | 整理工作量 |
|---|---|---|---|
| **1. 基本信息** | A.12 + B.12 个 (内省类) | 暂无独立 view | 小 |
| **2. 菜单功能** | G.7 + H.3 + I.1 (15 个) | ApaasMenuSidebar (新) | 中 (已经在做) |
| **3. 业务事件** | J.6 + C.4 (10 个) | 无独立 UI, 走 iframe | 中 |
| **4. 自开发管理** | K.15 + L.10 (25 个) | CodingPage / OnlineCodingPage 已有 | **大** (要把 Coding 融进来) |
| **5. 权限管理** | F.5 | 走 iframe | 小 |
| **6. 基础管理** | D.4 + E.6 (10 个) | 走 iframe | 小 |

**总结**: 工具基本都有 (除了基本信息的 update 工具), **真正的工程量在 UI 整合**。

---

## 8. 建议的 SPEC 输出路径

给你 3 个选项, 你定:

**选项 A — 先写完整 SPEC 文档再动手** (推荐)
- 输出 `docs/spec-app-config-redesign.md`:
  - 6 section 详细字段 / 工具 / 操作 / 边界
  - 每 section 在 ChatPage 的 UI 长啥样 (低保真)
  - ConfigAssistant 在每 section 的工具白名单 + prompt
  - section ↔ platform step / iframe URL 映射
  - 跟 ai-builder / ai-coding agent 的关系 (谁退役 / 谁合并)
- 你 review SPEC → 同意 → 然后再写代码
- 工程量: 写 SPEC 半天, 实现 1 周

**选项 B — 边整理边写 SPEC**
- 先把 4 个白名单合一 → 跑通 → 写 SPEC 那一段
- 再拆 ChatPage → 跑通 → 写 SPEC 那一段
- 工程量: 1-2 周, 但 SPEC 是事后产物 (不容易拍板)

**选项 C — 只清理不重构**
- 把混乱 top 5 一个个清掉 (4 份白名单合一 / v1 退役 / view 归类)
- 不动用户体验
- 工程量: 3-4 天, 但你想要的 "6 section + 闭环" 没做

---

## 9. 我的看法

你说 "有点混乱了" — 是的, 因为我们之前是**加法**逻辑 (用户要啥就加), 没有**减法 + 重构**。

**现在到了拐点**:
- 工具 114 个但分散在 4 个白名单
- views 31 个但 4 个 chat 入口割裂
- mcp_server 7K / ChatPage 12K 单文件越来越难维护

**推荐路径**: 选项 A — **先 SPEC 后实现**。

理由:
- 这次重构动的是结构, 不是 feature; SPEC 不写清楚很容易又加层乱
- 你担心的 "6 section + AI 驱动" 是产品方向, 不写下来下次又会改
- SPEC 写完后, 一周内能把核心架子搭起来

下次 session 我可以:
1. 草 `docs/spec-app-config-redesign-v1.md`
2. 你 review + 改 → 定稿
3. 按 SPEC 分 PR 落地

---

**问题**: 这份盘点你看完, 选 A / B / C? 还是先一起改改这份现状盘点 (有没有我漏掉的混乱点)?
