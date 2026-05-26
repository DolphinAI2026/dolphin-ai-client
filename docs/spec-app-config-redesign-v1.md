# 应用配置中心重设计 SPEC v1

> 2026-05-26 / Writer: Claude (orchestrator)
> Round 1, v1 草稿 — 等 reviewer 审

---

## 0. 背景 / 前置

**现状盘点**: 见 [docs/SPEC-system-inventory-2026-05-26.md](SPEC-system-inventory-2026-05-26.md)

**用户原始诉求**:
1. 把 Coding 融入 Builder, 闭环一个应用
2. 应用管理模块拆 6 section: 基本信息/菜单功能/业务事件/自开发管理/权限管理/基础管理
3. 右侧固定 AI 助手, 对话驱动迭代
4. 重新设计低代码配置后台, AI 驱动 + MCP 按需绑

**已收集证据**:
- 5 平台 UX 调研 (得帆云 / 简道云 / 明道云 / 宜搭 / 飞书 / Retool / Salesforce / Power Apps)
- 实测 codebase: 114 MCP 工具 / 47 routes / 31 views / 4 套白名单

**核心校准** (基于调研后改动用户原方案):
- ✏️ 6 section → **5 section + 1 顶部 CTA** (行业 4-5 sweet spot, 6+ 被批碎片)
- ✏️ "基本信息"section 取消, 改顶部 breadcrumb (Salesforce/Retool 都这么做)
- ✏️ "菜单功能"+"基础管理"按"配置 vs 设计"原则**拆开** (明道云/Salesforce 实证)
- ✏️ ConfigAssistant 跨 section 常驻 + context 切白名单 (飞书/Retool 实证有效, 简道云独立入口被诟病使用率极低)

---

## 1. 顶层架构

```
┌──────────────────────────────────────────────────────────────────────┐
│  TopBar: [< 返] [图书借阅管理系统] [→ 自开发] [🚀 部署] [⏱ 历史] [..] │  ← 顶部 CTA
├──────────────────────────────────────────────────────────────────────┤
│ Section Nav │                                          │ ConfigAssis │
│ (左侧 200px)│         Section 主区域 (iframe / 自建 UI) │ tant 浮动   │
│             │                                          │  FAB 默认收 │
│  ┌─────────┐│                                          │  起, 打开后 │
│  │📊 数据   ││                                          │  position:  │
│  │  模型   ││                                          │  fixed 浮在 │
│  │  字典   ││                                          │  右侧分屏    │
│  ├─────────┤│                                          │             │
│  │🎨 界面   ││                                          │  - 工具白名 │
│  │  菜单   ││                                          │    单跟当前 │
│  │  表单   ││                                          │    section  │
│  │  列表   ││                                          │    切       │
│  ├─────────┤│                                          │  - context  │
│  │⚙️ 逻辑   ││                                          │    含当前 s │
│  │  流程   ││                                          │    ection   │
│  │  事件   ││                                          │    元信息   │
│  ├─────────┤│                                          │  - chat ses │
│  │🔒 权限   ││                                          │    sion 跨  │
│  │  角色   ││                                          │    section  │
│  │  字段权 ││                                          │    全局     │
│  │  菜单可 ││                                          │             │
│  ├─────────┤│                                          │             │
│  │🧩 扩展   ││                                          │             │
│  │  代码节 ││                                          │             │
│  │  自开发 ││                                          │             │
│  │  组件   ││                                          │             │
│  │  → Codi ││                                          │             │
│  │    ng   ││                                          │             │
│  └─────────┘│                                          │             │
└──────────────────────────────────────────────────────────────────────┘
```

**3 区**:
- **左 200px**: Section 导航 (5 个一级 + N 个二级)
- **中**: Section 主区域 (大多嵌平台 iframe 不同 step, 少数自建 UI 比如菜单 sidebar)
- **右 320-880px**: ConfigAssistant (浮动, FAB 收起 / 打开后分屏 — 我们已实现的)

---

## 2. 5 个 Section 详细规范

### Section A — 📊 数据 (data)

**子 tab**: 数据模型 / 字典

**所属能力**:
- 列模型 / 加字段 / 改字段 / 禁用字段 / 改模型基本信息
- 列字典 / 建字典 / 加选项 / 改选项 / 禁用字典

**主区域 UI**:
- iframe 嵌平台 `/platform/.../admin/app-store/edit-app?currentStepIndex=1` (数据模型 step)
- 切 tab 时只换 sub-step URL, 不重新加载整个 iframe

**ConfigAssistant 白名单** (~14 个):
```
list_apaas_app_models, list_apaas_models_in_env,
update_apaas_app_model, add_apaas_model_field,
update_apaas_model_field, disable_apaas_model_field,
list_apaas_app_dicts, create_apaas_app_dict, update_apaas_app_dict,
disable_apaas_app_dict, add_apaas_dict_option,
update_apaas_dict_option, disable_apaas_dict_option,
+ 通用读 list_apaas_app_menus (字段绑定时要查表单)
```

**典型对话**:
- "加一个『申请人手机号』字段, 单行输入, 长度 20" → `add_apaas_model_field`
- "把『申请状态』字段加一个『已驳回』选项" → `add_apaas_dict_option`

---

### Section B — 🎨 界面 (ui)

**子 tab**: 菜单 / 表单 / 列表

**所属能力**:
- 菜单 CRUD + 分组 + 重命名 + 拖排序
- 表单字段布局 (列宽/必填/隐藏/只读/字典绑定)
- 列表视图配置 (查询条件/列显示)

**主区域 UI**:
- 左侧: **沿用现有 ApaasMenuSidebar** (我们已做完, 含菜单分组/移动/重命名/删除)
- 右侧: 平台 iframe 当前菜单的表单设计 / 列表设计 / 流程设计 (我们已对齐 menu_id → iframe URL)

**ConfigAssistant 白名单** (~20 个):
```
list_apaas_app_menus, list_apaas_form_components, list_apaas_form_views,
create_apaas_form_menu, create_apaas_self_dev_menu, delete_apaas_app_menu,
create_apaas_menu_group, set_apaas_menu_parent, rename_apaas_menu,
update_apaas_form_component, bind_apaas_form_field_to_dict,
build_apaas_feature_from_spec,    # ⭐ 加新表单 high-level
+ 浏览器工具 (菜单拖排序等无 MCP 场景, browser_click/snapshot)
```

**典型对话**:
- "加一张借书申请表单..." → `build_apaas_feature_from_spec` (SPEC 流程)
- "把申请理由改成多行输入" → `update_apaas_form_component`

---

### Section C — ⚙️ 逻辑 (logic)

**子 tab**: 流程 / 业务事件

**所属能力**:
- 表单审批流程配置
- 字段值改变 / 表单提交 / 定时事件 / 外部事件

**主区域 UI**:
- 左侧: 列流程 + 列业务事件 (二选一 tab)
- 右侧: 平台 iframe 流程设计 tab 或事件详情

**ConfigAssistant 白名单** (~16 个):
```
set_apaas_app_process,
list_apaas_business_events, get_apaas_business_event_detail,
create_apaas_business_event, save_apaas_business_event,
delete_apaas_business_event, list_apaas_form_menus_for_event,
list_apaas_business_events_in_tenant, query_apaas_business_event_trees,
list_apaas_business_event_execution_history,
create_form_event_with_python_code, create_time_event_with_python_code,
create_apaas_value_change_assignment_event,    # ⭐ 高频 wrapper
+ list_apaas_app_menus / list_apaas_app_roles 通用读
```

---

### Section D — 🔒 权限 (permission)

**子 tab**: 角色 / 字段权限 / 菜单可见性

**所属能力**:
- 角色 CRUD
- 字段层权限 (谁能看谁能改)
- 菜单层可见性 (角色 ↔ 菜单)

**主区域 UI**:
- iframe 嵌平台对应 step

**ConfigAssistant 白名单** (~8 个):
```
list_apaas_app_roles, create_apaas_app_roles,
update_apaas_app_role, delete_apaas_app_role,
list_apaas_form_permissions, set_apaas_form_permissions,
set_apaas_app_access,
+ 通用读
```

**已知缺口** (要补的工具):
- 菜单可见性配置工具 (`set_apaas_menu_role_visibility`?)
- 数据权限配置工具 (`set_apaas_data_permission`?)

---

### Section E — 🧩 扩展 (extension) ⚠️ 最复杂

**子 tab**: 自开发组件 / 自定义代码节点

**用户原话**: "Coding 入口要的"

**所属能力**:
- 自开发组件 (前端/后端 模版包) — 走 Coding 流程
- 自定义代码节点 — Python3 嵌业务事件 / 流程 (得帆云路线)

**主区域 UI** (3 模式渐进):

**E0 (P0 MVP, 1 天可做)**: **跳走兼容模式**
- 主区域显: "→ 打开 Coding 编辑应用扩展" + "→ 打开自开发资源管理 (iframe 嵌平台)"
- 点击跳现有 /coding 或 /online-coding 入口
- ConfigAssistant 只显**只读工具**: `list_dev_scenes / get_dev_scene_spec / list_apaas_app_dev_kits / list_apaas_resource_pool_kits`
- **不让 AI 在这个 section 写代码** (避免跟 Coding agent 抢身位)

**E1 (P1 真闭环, 1-2 周)**: **iframe 嵌 Coding workspace**
- 主区域内嵌 Coding 的 code-server IDE iframe (复用现有 `_build_ide_proxy_api_base`)
- ConfigAssistant 白名单解锁 dev workspace 工具
- Coding 完成 → 调 `publish_dev_workspace` → `attach_dev_packages_to_apaas_app` → `republish_apaas_app`

**E2 (P2 完美态)**: **Coding agent 二级嵌入**
- ConfigAssistant 在扩展 section 可以"代理"调起 Coding agent 完成子任务
- 类似 cursor 的 sub-agent 模式

**P0 选 E0** (推荐) — 用户体验上"扩展"section 也是个一等公民, 但用户点进去会发现跳走是个折中, 跟 P0 整体进度匹配。

**E0 ConfigAssistant 白名单** (~5 个):
```
list_dev_scenes, get_dev_scene_spec, get_dev_scene_full_workflow,
list_apaas_app_dev_kits, list_apaas_resource_pool_kits
```

---

### 顶部 CTA (不算 section)

```
[🚀 部署] — 调 deploy_application + publish_application
[⏱ 历史] — 调 list_deploy_records, 抽屉显部署历史 + 回滚
[更多 ...] — 折叠次要操作
```

**所属能力**:
- 部署 / 发布 / 回滚

**ConfigAssistant 在任何 section 都可用的全局工具** (~6 个):
```
deploy_application, publish_application, list_deploy_records,
rollback_application, republish_apaas_app, get_apaas_app_overview
```

---

## 3. ConfigAssistant 跨 Section 行为

### 3.1 工具白名单切换

**单一真相**: `backend/app/config_chat_sections.py` (新文件)

```python
SECTION_TOOL_WHITELIST = {
  "data":      [...14 工具...],
  "ui":        [...20 工具...],
  "logic":     [...16 工具...],
  "permission":[...8 工具...],
  "extension": [...5 工具...],  # E0
}
SECTION_GLOBAL_TOOLS = [
  # 不论 section 都能用
  "deploy_application", "publish_application", ...
]
```

请求 `/api/applications/{id}/config-chat-stream` 时带 `section=ui` 参数 →
backend 用 `SECTION_TOOL_WHITELIST[section] + SECTION_GLOBAL_TOOLS` 当 tool list 喂 LLM。

### 3.2 Chat session 跨 section 共享

- 同一个 app_id 一个 ConfigAssistant session (`config_chat_sessions` 表已有)
- 切 section 不重启 session, AI 知道上下文跨 section 流动
- 在 system prompt 顶部明示当前 section: `当前 section: 界面设计 / 表单. 可用工具: [...]. 若需切 section 操作, 提示用户切.`

### 3.3 自动提示切 section

如果 AI 检测到用户意图跨 section, 主动说 "这是逻辑 section 的事, 切过去吧" → 后端弹一个 prompt 让前端切 section。

---

## 4. 4 个 Chat 入口收敛方案

| 现入口 | 现路由 | 决策 |
|---|---|---|
| **AIChatPage** (ai-builder agent) | `/ai-builder/chat` (没 app_id) | **保留**, 定位"从零建新应用" — SPEC → generate → deploy |
| **ChatPage** (ConfigAssistant) | `/ai-builder/chat?app_id=N` | **保留** + 重设计为 5 section, 定位"已部署应用配置中心" |
| **CodingPage** (ai-coding agent) | `/ai-coding/chat` | **保留** (用户明确要), 定位"自开发模版包开发" — 跟 ChatPage 的 extension section 互通 |
| **vibe-coding** | `/vibe-coding/chat` | **保留**, 定位"独立全代码项目" — 跟 aPaaS 无关 |

**清晰角色**:
- AIChatPage: "我要建应用" (从无到有)
- ChatPage: "我要改应用" (已部署调参)
- CodingPage: "我要写自开发包" (前/后端代码)
- vibe-coding: "我要写独立项目"

**消除混淆的方案**:
- 4 入口在 Landing 页面有清晰**入口卡片** (描述 + 示例)
- AIChatPage 上方 banner: "已经有应用？→ 点应用名进应用配置中心"
- ChatPage 上方 banner: "需要写代码？→ 跳 Coding agent" (扩展 section 也提示)

### 4.1 重叠路由的处理

`OnlineCodingPage` vs `CodingPage`:
- **现状**: 24 处前端调用 OnlineCodingPage 都在用 → **不能删**
- **决策**: OnlineCodingPage 是"老 workspace 入口", CodingPage 是"v2 SPEC→Coding agent 入口"
- **重命名 + 文档化**: OnlineCodingPage → `WorkspaceLegacyPage` (注释标"老工作流, 新人优先用 CodingPage")
- 长期目标: v2 完整覆盖 v1 后退役

---

## 5. 4 套白名单合并方案

### 5.1 现状 (有 design intent 但维护痛)

| 名单 | 工具数 | 用途 |
|---|---|---|
| ai-builder agent prompt | 46 | "从零建应用" 全流程 |
| ai-coding agent prompt | 30 | 自开发包开发 |
| vibe-coding agent prompt | 11 | 独立项目 |
| ConfigAssistant `_CONFIG_CHAT_TOOL_WHITELIST` | 62 | 已部署调参 + 浏览器 + 事件 |
| **重叠 28 个** (CRUD 核心) | | 4 处都要维护 |

### 5.2 重构: 单一真相 + 派生视图

新文件 `backend/app/tool_registry.py`:

```python
# 工具注册表 — 单一真相. 每个工具一行, 带 tag.
TOOL_REGISTRY = {
  "list_apaas_apps_in_env": {
    "section": "data|ui|logic|permission|extension",  # 哪些 section 用得到
    "agents": ["builder", "coding", "config"],         # 哪些 agent 可见
    "category": "introspection",                       # 内省类
    "description": "...",
  },
  "deploy_application": {
    "section": "global",                               # 全 section 都能用
    "agents": ["builder"],                             # 仅 builder
    "category": "lifecycle",
  },
  ...
}

# 派生 — ai-builder agent 白名单
def builder_whitelist():
    return [k for k, v in TOOL_REGISTRY.items() if "builder" in v["agents"]]

# 派生 — ConfigAssistant 按 section 白名单
def section_whitelist(section: str):
    return [
      k for k, v in TOOL_REGISTRY.items()
      if "config" in v["agents"]
      and (section in (v.get("section") or "").split("|") or v.get("section") == "global")
    ]
```

**好处**: 加新工具改一处, 自动派生 4 套白名单。

**实施**:
- P1.1: 写 tool_registry.py + 单元测试
- P1.2: 改 ai-builder/coding/vibe prompt.md 生成器, 引用 registry
- P1.3: 改 `_CONFIG_CHAT_TOOL_WHITELIST` 引用 registry

### 5.3 agent prompt 自动化

`docs/skills/ai-builder/prompt.md` 现状是手写的。
**重构**: prompt 拆 template + 工具列表两文件, 工具列表自动从 registry 生成:
- `docs/skills/ai-builder/prompt.template.md` (手写)
- `docs/skills/ai-builder/tools.generated.md` (自动生成, gitignore? 或 generated 标记)
- 部署脚本 cat 两者拼一起

---

## 6. v1 / v2 / online_coding 三套并存的"何时用哪个"决策标

**问题**: 实测 coding.py + coding_v2.py + online_coding.py 都活跃, 但用户搞不清何时用哪个。

**新增 `docs/decision-coding-flows.md`** (这个 SPEC 拆出去单独文档):

| 用户场景 | 用哪条 |
|---|---|
| 我要给已部署应用加个组件 | CodingPage (v1 通用入口) |
| 我从 SPEC 进 Coding 流程 (Builder 协同) | CodingPage v2 (`/coding/v2/spec/{id}/start-coding`) |
| 我要单独管 workspace (老用户习惯) | OnlineCodingPage (`/online-coding/...`) |
| 我要写跟 aPaaS 无关的纯代码项目 | VibeCoding (`/vibe-coding/...`) |

**长期归约 (P3)**: 把 OnlineCodingPage 的能力合到 CodingPage v1, OnlineCodingPage 退役。

---

## 7. UI 低保真

### 7.1 主框架

```
+---------------------------------------------------------------------------+
| ☰  图书借阅管理系统 / 应用配置中心                  [→ 自开发] [部署] [史] |
+--------+------------------------------------------------------+-----------+
| 📊 数据 |  数据模型                                         |  ┌────────┐|
|  ├模型 |  +─────────────────────────────────────────────+   |  │AI 助手 ││
|  ├字典 |  | (iframe 嵌平台数据模型设计页)                |   |  │浮动收起│|
|        |  |                                              |   |  └────────┘|
| 🎨 界面 |  |                                              |   |             |
|  ├菜单 |  |                                              |   |             |
|  ├表单 |  |                                              |   |             |
|  ├列表 |  +─────────────────────────────────────────────+   |             |
| ...    |                                                     |             |
+--------+-----------------------------------------------------+-------------+
```

### 7.2 切 section 行为

- 点左侧 section → 中间区域换 iframe URL (或自建 UI)
- ConfigAssistant 不动 (UI 上)
- 后台对 ConfigAssistant 发 `update_section({section: "ui"})` → 切白名单
- AI 下条回复时知道新 section + 可用工具变了

### 7.3 ConfigAssistant 浮动状态

(已实现) 默认收起 FAB 在右下, 点开后 position:fixed 浮在 iframe 上方 (split mode, 不再 overlay)。

---

## 8. 实施 PR 切分 (按依赖排序)

### PR1 — 单一真相 tool_registry (P0)
- 写 `tool_registry.py` + 1 个测试
- 改 `_CONFIG_CHAT_TOOL_WHITELIST` 引用 registry
- ai-builder/coding/vibe prompt 暂不动 (P1.2 再上)
- **预期 LOC**: ~500 行 + 测试
- **风险**: 现 ConfigAssistant 行为不变 (派生白名单跟现状一致)

### PR2 — 5 Section 框架 + section-aware 白名单 (P0)
- 改 ChatPage.vue:
  - 左侧 `ApaasMenuSidebar` 重构为 `SectionNav` (5 一级 + N 二级)
  - 切 section 时换中间 iframe URL
  - 切 section 时调后端 `set_chat_section` 切白名单
- backend 新加 `/api/applications/{id}/config-chat-stream` 接 `section` 参数
- 用 tool_registry 派生 section 白名单
- 现 ApaasMenuSidebar 作为"界面 section / 菜单 sub-tab"的子组件保留
- **预期 LOC**: ChatPage +500 / -300, backend +200
- **风险**: ChatPage 12K 行, 改要小心

### PR3 — 顶部 CTA (P0)
- 部署按钮 / 历史按钮 / 自开发跳转
- 复用现有 DeployHistoryDrawer
- **预期 LOC**: ChatPage +100, 不动 backend

### PR4 — 4 chat 入口 banner / 边界提示 (P1)
- AIChatPage / ChatPage / CodingPage 加 banner 说明各自定位
- 加 cross-link
- **预期 LOC**: 200

### PR5 — agent prompt 引用 registry (P1)
- 写 prompt template + tools.generated.md 拼装脚本
- 改 3 个 agent prompt.md
- **预期 LOC**: 300 + 删除散落白名单

### PR6 — 扩展 section E0 跳走入口 (P0)
- "扩展" section UI: 显两张大卡片跳 /coding 和 /online-coding
- 只读工具白名单
- **预期 LOC**: 150

### PR7 — 补缺口工具 (P1)
- `update_apaas_app_info` (基本信息更新, 虽然 section 没了但 breadcrumb 需要)
- `set_apaas_menu_role_visibility`
- `set_apaas_data_permission`
- **预期 LOC**: 600

### PR8 — 扩展 section E1 真嵌入 (P2, 1-2 周)
- code-server IDE iframe 嵌 ChatPage 扩展 section
- ConfigAssistant 白名单解锁 dev workspace 工具

### PR9 — coding v1 / v2 / online 决策文档 (P3)
- 写 `docs/decision-coding-flows.md`
- 长期 OnlineCodingPage 退役

---

## 9. 关键决策与未决问题

### 9.1 已决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 顶层 section 数 | 5 + 1 顶部 CTA | 行业 4-5 sweet spot |
| Coding 入口 | 保留 + 融入扩展 section | 用户明确要 |
| 数据 vs 界面 | 严格分离 | 明道云/Salesforce 实证 |
| 白名单管理 | 单一真相 registry 派生 | 维护成本降 |
| v1/v2/online_coding | 并存 + 决策文档 | 实测都活跃, 不删 |
| ConfigAssistant | 跨 section 常驻 + context 切 | Retool/飞书实证有效 |

### 9.2 待用户拍板

**Q1 — extension section P0 模式**:
- 选项 A: E0 跳走 (我推荐, 1 天可做)
- 选项 B: E1 真嵌入 (1-2 周, 体验完整)

**Q2 — agent prompt 自动生成**:
- 选项 A: 拆 template + 自动拼接 (PR5)
- 选项 B: 继续手写 (但加新工具要追多处)

**Q3 — section 命名 (中文)**:
- 我用了: 数据 / 界面 / 逻辑 / 权限 / 扩展
- 备选: 数据模型 / 界面设计 / 业务逻辑 / 权限管理 / 扩展开发
- 你倾向?

**Q4 — section 顺序**:
- 我用了: 数据 → 界面 → 逻辑 → 权限 → 扩展 (经典 MVC + 安全 + 扩展)
- 平台默认: 基本信息 → 数据 → BO → 表单 → 流程 → 角色 → 字典 → 自开发
- 用户感觉: 配应用先建数据再设计界面? 还是先设计界面再补字段? 

### 9.3 风险

| 风险 | 缓解 |
|---|---|
| ChatPage 12K 改风险 | 分 PR 落地, 每步可回滚; 不动现有 ApaasMenuSidebar 子树 |
| tool_registry 迁移影响 4 套白名单 | PR1 单独跑, 派生跟现状对齐 (无行为变化), CI 加白名单 diff 测试 |
| extension section 跳走 vs 嵌入选错 | P0 先 E0, P2 看用户反馈再升 E1 |
| 用户被 4 个 chat 入口绕晕 | PR4 banner 优先做, Landing 也加入口卡 |

---

## 10. 工程量估算

| Phase | PR | 工程量 |
|---|---|---|
| P0 (1 周内做完) | PR1 + PR2 + PR3 + PR6 | ~3-4 天 (含测试) |
| P1 (2 周内) | PR4 + PR5 + PR7 | ~3-4 天 |
| P2 (1 个月内) | PR8 (E1 真嵌入) | ~1-2 周 |
| P3 (随缘) | PR9 (v1 退役决策) | 1-2 天 |

**总: P0+P1 ~2 周** 能让用户看到"5 section + section-aware AI" 主体体验。

---

## 11. 验收标准 (per phase)

### P0 验收
- [ ] ChatPage 进入应用后, 左侧显 5 section 导航 (data/ui/logic/permission/extension)
- [ ] 切 section, iframe URL 跟着切 / 内置 UI 跟着换
- [ ] ConfigAssistant 可用工具数 跟当前 section 匹配 (查浏览器 devtools network)
- [ ] 顶部 [部署] [历史] 能用
- [ ] 扩展 section 跳走入口能跳到 /coding 和 /online-coding

### P1 验收
- [ ] 一处 `tool_registry.py` 加新工具, 4 套白名单自动派生
- [ ] AIChatPage / CodingPage 顶部 banner 显角色提示
- [ ] 菜单可见性 / 数据权限工具能用

### P2 验收
- [ ] 扩展 section 嵌 code-server IDE iframe
- [ ] ConfigAssistant 在扩展 section 能调起 workspace 工具
- [ ] Coding 完成 → publish + attach + republish 一气呵成

---

## 12. 下一步

1. **Reviewer (`ce-adversarial-document-reviewer`) 审 v1** — 我消化 issues → v2
2. **你 review v2** — 拍板 + 回答 Q1-Q4 待定决策
3. **进 Round 2 (实现)** — 按 PR1→PR2→PR3→PR6 顺序做 P0

---

(SPEC v1 草稿结束 — 等 reviewer + 用户 review)
