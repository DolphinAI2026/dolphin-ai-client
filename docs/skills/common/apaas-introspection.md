# aPaaS 平台元数据查询 — 公共 Skill

> v1.0 / 2026-05-14
> 给 ai-builder + ai-coding 共用。讲清楚环境 / 应用 / 菜单 / 表单 / 模型 / 字段 / 字典 / 角色 / 权限怎么查。

---

## 概念金字塔

```
平台环境 (Platform Env)
  └── 租户 (Tenant)
       └── 应用 (App)
            ├── 角色 (Roles)
            ├── 字典 (Dicts) + 选项 (Options)
            ├── 模型 (Models)
            │    └── 字段 (Fields)
            ├── 菜单 (Menus)
            │    └── 表单 (Forms)
            │         ├── 视图 (Views, aka tabs)
            │         ├── 组件 (Components)
            │         └── 权限 (Permissions)
            └── 流程 (Processes, BPMN)
                 └── 节点 (Nodes) + 边 (Edges)
```

---

## 查询入口（4 个工具，从外到内）

### 1️⃣ 环境

```
list_platform_envs()
→ envs: [{id, name, base_url, is_default, status}]
```

- 优先用全局记忆 `env: <alias>` 拿对应 id
- 没配就用 `is_default=true` 的那条

### 2️⃣ 应用

```
list_apaas_apps_in_env(env_id)
→ apps: [{apaas_app_id, app_code, app_name, status}]

list_my_applications(env_id?, page?, page_size?)
→ 当前用户能管理的应用列表（含 web_url）

get_application(app_id)
→ 应用基本信息 + 状态 + 默认 URL

get_apaas_app_overview(env_id, apaas_app_id)
→ 应用全景：models / forms / menus / roles / dicts 总览（一次性拿全）
```

### 3️⃣ 应用内部资源

| 资源 | 工具 |
|---|---|
| 角色 | `list_apaas_app_roles(env_id, apaas_app_id, keyword?)` |
| 字典 + 选项 | `list_apaas_app_dicts(env_id, apaas_app_id)` |
| 模型 + 字段 | `list_apaas_app_models(env_id, apaas_app_id)` 或全局 `list_apaas_models_in_env(env_id)` |
| 菜单 | `list_apaas_app_menus(env_id, apaas_app_id)` — form 菜单的 form_id 在这里 |

### 4️⃣ 表单内部

```
list_apaas_form_views(env_id, apaas_app_id, form_id)
→ views: [{id, name, isDefault}]  视图（tab）列表

list_apaas_form_components(env_id, apaas_app_id, form_id)
→ components: [{label, componentType, modelField, required, ...}]

list_apaas_form_permissions(env_id, apaas_app_id, form_id)
→ data_permissions + operation_permissions（按角色 / ALL_USER 分组）
```

---

## 常用查询场景速查

### 场景 A：用户问"我有哪些应用"

```
list_my_applications() → 拿 app_code + app_name + web_url 列表
```

### 场景 B：要操作某个应用，先拿基本信息

```
list_apaas_apps_in_env(env_id) → 找到 apaas_app_id（按 app_code 或 app_name 匹配）
get_apaas_app_overview(env_id, apaas_app_id) → 一次拿全：模型 / 表单 / 菜单 / 角色 / 字典
```

### 场景 C：要给某表单加权限，先看现状

```
list_apaas_app_menus(env_id, app_id)              → 找 form 菜单的 menu_id + form_id
list_apaas_form_permissions(env_id, app_id, form_id) → 当前权限矩阵
（用户对齐改动后）set_apaas_form_permissions(...)    → 覆盖式写入
```

### 场景 D：要查业务数据（用户提交的应用数据）

```
list_apaas_app_menus(env_id, app_id) → 找 form_id
query_apaas_business_data(env_id, app_id, form_id, tab_id="", page_size=20)
   tab_id="" 自动拿默认视图
返回 items[]（每行 dict，key 是字段 uuid）+ total + raw_keys
```

### 场景 E：app_code 命名查重

```
check_app_code_conflict(env_id, candidate_app_code)
→ ok: true/false + conflicts: [...]
```

### 场景 F：写后端代码前确认 DB 表名 + 字段名

```
list_apaas_app_models(env_id, app_id) → 模型 list（每个 model 的 modelCode）
真实表名一般是 modelCode（小写下划线版） + 后缀（实测变体多，可能 _xhs9 / _ehd 等）
真实业务字段名可能是 fieldCode / f_fieldCode（4.1.1-rc 实测 fieldCode）
**写 SQL 前必须 SELECT * FROM 表 LIMIT 1 确认列名**（坑 12）
```

---

## ID 系统注意

aPaaS 平台几套 ID 容易混：

| ID | 长啥样 | 来源 |
|---|---|---|
| `apaas_app_id` | 18 位数字（雪花 ID） | `list_apaas_apps_in_env`.apaas_app_id |
| `app_code` | kebab-case 英文 | 同上 |
| `model_id` | 18 位数字 | `list_apaas_app_models`.id |
| `modelCode` | snake_case 英文 | 同上 |
| `field_id` | 18 位数字 | model.fields[].id |
| `fieldCode` | snake_case 英文 | 同上 |
| `form_id` | **24 位 hex**（mongodb ObjectId 风格） | `list_apaas_app_menus`.form_id |
| `tab_id`（aka view_id） | 24 位 hex | `list_apaas_form_views`.id |
| `role_id` | 18 位数字 | `list_apaas_app_roles`.role_id |
| `roleCode` | snake_case，常带 `R_` 前缀 | 同上 |
| `menu_id` | 18 位数字 | `list_apaas_app_menus`.menu_id |
| `dict_id` | 18 位数字 | `list_apaas_app_dicts`.id |
| `option_id` | 18 位数字 | dict.options[].id |
| `documentId`（业务数据） | 18 位数字 | 业务数据行 |

**绝对禁止**：

- 不要硬编 ID 用「猜的」字符串 / 数字
- 不要在 chat 里复述用户给的 ID 让用户「确认对不对」—— ID 太长用户看不出来
- 反查永远从 list 工具的 response 里拿

---

## 常见 pitfall

### 1. `env_id` vs `apaas_app_id` 搞混

`env_id` 是 ai-builder 平台环境 ID（小整数，1-100），`apaas_app_id` 是 aPaaS 平台应用 ID（18 位长整数）。不能互换。

### 2. `app_id` vs `app_code`

- `apaas_app_id` 才是 18 位长整数，工具大部分要这个
- `app_code` 是 kebab-case 英文（如 `leave-mgmt`）只在少数工具 / 显示用
- **API 内部参数严格用 `apaas_app_id`**

### 3. 跨租户 / 跨环境

每个工具都带 `env_id`，**严禁** 让 LLM 在一个 session 里跨 env 操作 — 用户切 env 应该新建对话。
（极少数场景跨 env 比对数据可以连调，但要明显告诉用户）

### 4. form_id 跨应用？

实测发现 form_id 在 apaas 平台是**全局唯一**的 24 位 hex（不按 app 重置）— 但**只能在所属 app 范围内调用工具**。强行用 A app 的 form_id 调 B app 的工具会失败。

### 5. 业务数据查询的两个端点

容易混（实测踩过）：

| 端点 | 用途 | 工具 |
|---|---|---|
| `/business/query/detailBusinessData` | 查**单条**详情（需 documentId） | 暂未暴露成工具 |
| `/business/v2/query/listPageBusinessData` | 查**列表**（分页） | `query_apaas_business_data` |

**list 用 v2 那个**，返回字段是 `table` 不是 `data`。

---

## 工具调用顺序最佳实践

```
START
  ↓
list_platform_envs / 用 env 别名 → env_id
  ↓
list_apaas_apps_in_env(env_id) → apaas_app_id
  ↓
（根据需求分支）
  │
  ├─ 看应用全景 → get_apaas_app_overview
  ├─ 改单个资源 → list_apaas_app_X → 拿到 X_id → 改/删工具
  ├─ 改表单内的东西 → list_apaas_app_menus → form_id → list_apaas_form_* → 操作
  └─ 查业务数据 → list_apaas_app_menus → form_id → query_apaas_business_data
```

**反模式**（不要这样）：

- 直接对话里编造 form_id / role_id 调写操作
- 跳过 list 工具就调 update/delete
- 一次性串调 5+ 个工具不告诉用户中间结果
