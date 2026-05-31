# apaas-builder Draft 工作流 Skill v2

> 替代旧版 `ai-builder-unified-check-codes-patch.md`。把"agent 反复传完整 md"的旧模式换成"draft_id + patch action"的新模式。

---

## 核心原则（6 条铁律）

1. **md 是源 + JSON 是内部表示，但都常驻服务端**。Agent 上下文里**只持有 draft_id**（一串十几字节）。
2. **不在聊天里贴完整 md / 完整字段表**。给用户看就给 `preview_url`，让浏览器去渲染。
3. **不自己跑校验**。`save_design_draft` 服务端会跑，错误用 structured error 直接转述用户。
4. **修改优先 patch action**。整份 md 重传只在用户明确"整套重写"时用。
5. **错误信任 server**，不自己改 md 重试。看 `level` 和 `retriable` 决定下一步。
6. **不能用本地文件代替设计文档保存**。生成完标准 6 章 Markdown 后，必须把完整正文作为 `md_content` 调 `save_design_draft`；不得只生成 `/workspace/*.md`、附件或文件路径后停止，也不得把"文件已生成"说成"设计文档已生成"。如果服务端返回 `DOC_MODULE_PARSE_FAILED`，说明失败模块没按模板解析通过，不是传输限制。

## 澄清与生成节奏

- 首轮澄清优先问**真实业务主流程**，例如耗材管理问 `入库 → 库存台账 → 领用/出库 → 盘点 → 预警/补货` 是否覆盖；不要先问抽象对象边界或权限复杂度。
- 业务主流程不是 Builder 配置步骤。不要输出 `需求成稿 / 表单承载 / 权限分配 / 构建发布` 这类流程。
- 最多问 1-2 轮。用户已经确认主范围和简化/标准方案后，必须直接生成完整 md_content 并调用 `save_design_draft`。
- 调 `get_doc_template_spec` 后，下一步必须写 6 章 Markdown 并调 `save_design_draft`，不能停在"模板已获取"。

---

## 标准工作流

### A. 首次创建应用

```
用户："帮我建一个销售管理系统..."
   ↓
你（内部）：生成完整 md_content（5/6 章必须是后端可纯代码解析的标准表）
   ↓
调 save_design_draft(md_content)
   ↓ 返回 {ok, draft_id, summary, preview_url, level, warnings?}
   │
   ├─ level=standard / partial → 聊天里输出：
   │    "✅ 设计文档已生成
   │     📋 <summary>
   │     👀 预览：<preview_url>
   │     确认后回复"创建"。"
   │
   └─ level=freeform → 拒收，把 errors[].msg 转述给用户，让他决定重写还是其它
   ↓
用户回复"创建"
   ↓
调 promote_draft_to_app(draft_id, env=<用户指定环境别名；未指定则省略>)
   ↓ 返回 {ok, app_id, local_app_id, apaas_app_id, admin_url, status, id_guide}
   │
   ├─ status="deployed" → 输出：
   │    "✅ 已创建：<admin_url>
   │     本地应用 ID：<app_id>（仅用于 AI Builder/MCP 本地接口）
   │     aPaaS 发布应用 ID：<apaas_app_id>（发布/自开发/aPaaS 工具必须用这个）"
   │
   └─ status="in_progress" → 输出：
        "✅ 部署中（30~60s 完成），稍后查询..."
        30s 后用 get_application(app_id, mode="summary") 复查
```

注意：`app_id` 不是发布应用 ID。用户问发布、重发、自开发、aPaaS 查询时，必须使用 `apaas_app_id`。

### B. 修改既有应用（默认走 patch）

```
用户："客户表加个等级字段，绑客户等级字典"
   ↓
你（内部）：判断当前是否有可用 draft_id
   - 如果上下文里有 draft_id 且仍 active → 直接 patch
   - 如果只有 app_id → 先调 get_application(app_id, mode="summary") 拿 current_draft_id
   - 如果都没有 → 让用户先指定 app
   ↓
调 patch_design_draft(draft_id, action={
  "op": "add_field",
  "model": "customer",
  "field": {"code": "customer_level", "name": "客户等级",
            "type": "下拉单选", "dictCode": "customer_level"}
})
   ↓ 返回 {ok, draft_id: <new>, summary_of_change, preview_url, app_id?}
   ↓
聊天里输出：
  "已更新：<summary_of_change>
   👀 新版预览：<preview_url>
   确认后回复"更新"。"
   ↓
用户回复"更新"
   ↓
调 apply_draft_to_live_app(new_draft_id)
   ↓ 返回 {ok, status, applied_count, summary}
   ↓
聊天里输出：
  "✅ 已同步到应用：<summary>"
```

### C. 整份重写（兜底，少用）

```
用户："我重新整理了一份 md，发我（贴一大段）..."
   ↓
你：调 save_design_draft(md, parent_app_id=<现有 app 的 id>)
   ↓ 服务端会自动跑 doc_differ 算变更计划
   ↓
后续走 admin-spa 预览页确认 → apply_draft_to_live_app
```

---

## 你能调的工具（白名单）

| 工具 | 用途 | 关键输入 | 输出 |
|---|---|---|---|
| `save_design_draft` | 新建 draft（或整份替换） | md_content, parent_app_id? | draft_id, summary, preview_url, level, errors? |
| `patch_design_draft` | 在 draft 上打补丁 | draft_id, action | new draft_id, summary_of_change, preview_url |
| `get_draft_summary` | 看 draft 概况（不返 md） | draft_id | status, summary, app_id, ... |
| `promote_draft_to_app` | 部署 draft 成新应用 | draft_id, env | app_id, apaas_app_id, admin_url, status |
| `apply_draft_to_live_app` | 把新版 draft 应用到已有 app | draft_id | applied_count, summary |
| `get_application` | 查 app 元信息（默认 summary） | app_id, mode='summary' | id, name, code, status, **current_draft_id**, admin_url |
| `list_my_applications` | 列我的应用 | — | apps[] |

## 你不要再调的工具（黑名单）

这些工具加了 `[DEPRECATED]` 标记，旧 agent 还能调但**新流程不要碰**：

- `validate_builder_doc` —— 已内嵌进 save_design_draft
- `parse_design_doc` —— 已内嵌进 save_design_draft
- `check_app_code_conflict` —— 已内嵌进 promote_draft_to_app
- `check_model_codes` —— 已内嵌进 promote_draft_to_app
- `generate_app_from_doc` —— 改用 save + promote
- `deploy_application` —— 已内嵌进 promote_draft_to_app
- `publish_application` —— 已内嵌进 promote/apply
- `update_app_from_doc` —— 改用 patch_design_draft + apply
- `get_change_plan` —— 已内嵌进 apply_draft_to_live_app
- `execute_change_plan` —— 已内嵌进 apply_draft_to_live_app
- `submit_design_doc` —— 已被 save_design_draft 替代

---

## patch action 词汇表

> 用户说什么 → 调哪个 op。

| 用户说 | op | 必填字段 |
|---|---|---|
| "客户表加个等级字段" | `add_field` | model, field.{code, name, type} |
| "合同金额改成必填" | `update_field` | model, field_code, updates.{required: true} |
| "删掉备注字段" | `delete_field` | model, field_code |
| "新增财务角色" | `add_role` | role.{code, name} |
| "删掉销售专员角色" | `delete_role` | role |
| "合同状态加'已归档'" | `add_dict_option` | dict_code, option.{code, name} |
| "新增回款表单" | `add_form` | form.{code, name, mainModel} |
| "销售只能看自己的客户" | `set_permission` | form, role, ops, scope |

### patch action schema

编码要求：已有文档 / 截图 / 表格中的模型、字段、表单、字典、选项编码，满足平台最低规则时必须原样保留；不要为了“更像 snake_case”主动拆词加下划线。只有非法、重复、保留字、超长或非法前缀时才最小化改名，并说明 `old_code -> new_code` 映射。

#### add_field

```json
{
  "op": "add_field",
  "model": "<model_code>",
  "field": {
    "code": "<field_code>",        // 合法原文编码优先保留；非法/重复时才最小改名
    "name": "<字段名称>",
    "type": "<组件类型>",          // 单行输入/下拉单选/数据单选/日期时间/...
    "databaseFieldType": "varchar",
    "maxLength": "64",
    "required": true,               // 可选
    "dictCode": "<dict_code>",      // 下拉单选/复选时填
    "refModel": "<model_code>",     // 数据单选/数据选择时填
    "refField": "<field_code>"      // 数据单选/数据选择时填
  }
}
```

#### update_field

```json
{
  "op": "update_field",
  "model": "<model_code>",
  "field_code": "<existing_field_code>",
  "updates": {
    "name": "新字段名",
    "required": true,
    "type": "多行输入",
    "dictCode": "<dict_code>"
  }
}
```

只填要改的 key，其它字段保持原样。

#### delete_field

```json
{"op": "delete_field", "model": "<model_code>", "field_code": "<field_code>"}
```

#### add_role

```json
{"op": "add_role", "role": {"code": "<role_code>", "name": "<角色名>"}}
```

#### delete_role

```json
{"op": "delete_role", "role": "<role_code>"}
```

会自动清理 permissions 里所有引用该 role 的规则。

#### add_dict_option

```json
{
  "op": "add_dict_option",
  "dict_code": "<dict_code>",
  "option": {"code": "<option_code>", "name": "<选项名>"}
}
```

#### add_form

```json
{
  "op": "add_form",
  "form": {
    "code": "<form_code>",
    "name": "<表单名>",
    "mainModel": "<model_code>",       // 必填，绑定的主表
    "description": "<说明>",
    "fields": [...]                      // 可选，初始字段（一般留空再用 add_field 加）
  }
}
```

#### set_permission

```json
{
  "op": "set_permission",
  "form": "<form_code 或 form_name>",
  "role": "<role_code>",
  "ops": ["view", "edit"],          // 或 ["all"] 表示全权限
  "scope": "本人数据"                // 或 "全部数据" / "本部门数据" / "本部门及下级数据"
}
```

`ops` 取值（可组合）：`view` / `add` / `edit` / `delete` / `import` / `export` / `draft` / `all`

---

## 修改场景决策树

```
用户提需求（含修改意图）
   │
   ▼
agent 上下文里有 draft_id 吗？
   │
   ├─ 有，且 status='active'   → 直接 patch_design_draft(draft_id, ...)
   │
   ├─ 有 draft_id 但 status='superseded'  →
   │       说明用户之前的 patch 链没 apply，把链条上最新的（next-of-kin）找出来 patch
   │
   └─ 没有 draft_id
        │
        ▼
        agent 上下文里有 app_id 吗？
           │
           ├─ 有 → 调 get_application(app_id, mode="summary")
           │       拿 current_draft_id → patch
           │
           └─ 没有 → 调 list_my_applications，
                   让用户选一个，再 get_application → patch
```

---

## 风险确认规则

下列修改**先问用户一句确认**，再调 patch：

| 操作 | 是否确认 | 措辞 |
|---|---|---|
| 新增字段 | 不确认 | 直接 patch + 给 preview_url |
| 新增字典项 | 不确认 | 同上 |
| 改字段 name / 备注 | 不确认 | 同上 |
| 改字段 `required` | 不确认 | 直接 patch |
| 改字段 type | **确认** | "改类型可能影响已录入数据，确认改吗？" |
| 改权限范围（变严） | **确认** | "<role> 的 <ops> 权限会收紧到 <scope>，确认吗？" |
| 删字段 | **必须确认** | "字段 X 删除后已录入数据会丢失，确认吗？" |
| 删模型 / 表单 / 角色 | **必须确认** | 同上 |

---

## 错误处理范式

server 错误一律是 structured error：

```json
{
  "ok": false,
  "level": "freeform" | "partial" | "platform_error" | "conflict" | "invalid_patch" | "not_found",
  "errors": [
    {
      "code": "INVALID_APP_CODE",
      "msg": "应用编码必须 kebab-case",
      "fix": "把 sales_order 改为 sales-order"
    }
  ],
  "retriable": false
}
```

处理规则：

1. **直接转述** `errors[].msg` 和 `errors[].fix` 给用户。
2. **不自己改 md 重试**。让用户决策。
3. `retriable: true` 时才考虑重试，否则等用户输入。
4. `level=freeform` → 文档要重写，把 errors 列给用户看让他决定方向。
5. `level=conflict` → app_code / model_code 撞了，让用户决定换名或更新已有应用。
6. `level=platform_error` → aPaaS 平台报错，转述错误，建议用户稍后重试或联系运维。
7. `level=invalid_patch` → patch 目标找不到 / 字段不合法，直接告诉用户哪里不对。

---

## 聊天输出规范

| 场景 | 输出长度 | 必含 |
|---|---|---|
| draft 已生成 | ≤ 3 行 | summary 一行 + preview_url |
| patch 完成 | ≤ 2 行 | summary_of_change + 新 preview_url |
| 应用部署成功 | 1 行 | admin_url |
| 同步成功 | 1 行 | applied_count + admin_url |
| 错误 | ≤ errors 数 | 每条 errors[].msg + 可选 fix |

**禁止做的事**：

- 贴完整 md
- 列字段表 / 模型表（用 preview_url 让用户去看）
- 复述"我刚才调了 X 工具"
- 把上一轮的状态再重复一遍
- 让用户手打“开始创建 / 部署 / OK”。draft 已生成或 patch 完成后，必须调用 `ask_clarifying_question` 渲染 `["开始创建", "继续修改"]` 两个选项。

---

## 完整示例对话

```
用户：帮我建一个销售管理系统，要客户/合同/回款，三个角色：管理员/销售/财务。

你（内部）：写 md，调 save_design_draft(md)
你（聊天）：
  ✅ 设计文档已生成
  📋 销售管理系统｜模型 3｜表单 3｜角色 3
  👀 预览：https://your-domain/admin/design-preview/d_abc123
你（内部）：调 ask_clarifying_question(options=["开始创建", "继续修改"])

用户：客户加个等级字段

你（内部）：调 patch_design_draft(draft_id="d_abc123", action={op:"add_field","model":"customer",...})
你（聊天）：
  已更新：客户模型新增「客户等级」字段（下拉单选，绑客户等级字典）
  👀 新版预览：https://your-domain/admin/design-preview/d_abc124
你（内部）：调 ask_clarifying_question(options=["开始创建", "继续修改"])

用户：开始创建

你（内部）：调 promote_draft_to_app("d_abc124")
你（聊天）：
  ✅ 已创建：https://apaas-poc.../app/sales-crm

用户：合同里加个状态字段

你（内部）：先 get_application(app_id=244, mode="summary") 拿 current_draft_id
       然后 patch_design_draft(current_draft_id, ...)
你（聊天）：
  已更新：合同模型新增「合同状态」字段
  👀 新版预览：https://your-domain/admin/design-preview/d_abc125
  确认后回复"更新"。

用户：更新

你（内部）：apply_draft_to_live_app("d_abc125")
你（聊天）：
  ✅ 已同步到合同应用（新增 1 个字段）
```

---

## 关键端点（仅供参考，agent 一般用不到）

- **预览页（用户直接打开，无鉴权）**：`{preview_base_url}/design-preview/{draft_id}`
  服务端直出 HTML（≈30KB 自包含），不依赖前端 SPA 登录态，类似 google-doc 的 anyone-with-link 模式
- Spec API（JSON）：`GET /api/design-drafts/{draft_id}/spec`
- Promote API：`POST /api/design-drafts/{draft_id}/promote`
