# ai-builder-unified skill v0.1.4 补丁 — 长 SPEC 必先落盘拿 doc_token（2026-05-12）

> **背景**：2026-05-12 SAIC 缺件车管理系统实测翻车——agent 写了 23k 字 SPEC，
> 在 STEP 2 直接调 `generate_app_from_doc(md_content=<23k>)`，dolphin agent
> 容器报「Agent 服务异常」。
>
> 思考过程明文自爆：`"The content is lengthy, around 23k words, so I need to
> consider the token limit"` — LLM 输出 23k 当 tool_use 参数，撞 dolphin omnigate
> / LLM context token 限制。
>
> 用户决策方案 A：加 `save_app_design_doc` 工具落盘 SPEC 拿 32 字 `doc_token`，
> `generate_app_from_doc` 加 `doc_token` 参数替代 md_content 入参。
>
> 后端工具已上线（mcp-server commit 待 follow，61 工具）。本文档是 skill workflow
> 同步规则。

---

## 后端新工具签名

```python
save_app_design_doc(
    md_content: str,           # 完整设计文档 md
    app_name: str = "",         # 可选
    env: str = "",              # 强烈建议传，用于 modelCode 预检
    env_id: int = 0,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict
# returns:
#   {
#     ok: True,
#     doc_token: "appdoc_<uid>_<8hex>",
#     app_name: "缺件车管理系统",
#     summary: {"roles": 8, "dicts": 7, "models": 17, "forms": 20, "perms": 20},
#     doc_md_length: 23456,
#     next_action: "在 chat 给用户展示业务摘要 + 等 OK → generate_app_from_doc(doc_token=...)"
#   }
```

`generate_app_from_doc` 新增 `doc_token` 参数：

```python
generate_app_from_doc(
    md_content: str = "",       # 短 SPEC 可直传；传了 doc_token 时忽略本字段
    doc_token: str = "",        # 🆕 长 SPEC 必传，来自 save_app_design_doc
    app_name: str | None = None,
    env: str = "",
    env_id: int = 0,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict
```

---

## ai-builder-unified skill workflow 补丁

在 STEP 1.5（modelCode 预检）之后、STEP 2（generate_app_from_doc）之前插入：

```markdown
## STEP 1.7：长 SPEC 必先落盘拿 doc_token（🆕 v0.1.4 强制铁律）

### 触发条件

写完完整 spec.md 后，检查 md 总字符数 `len(spec_md)`：

| 长度 | 路径 |
|------|------|
| **>= 8000 字符**（推荐：所有「应用级」SPEC 都走）| **必走** save_app_design_doc 拿 doc_token |
| < 8000 字符（仅简单 demo）| 可直接走 generate_app_from_doc(md_content=...) |

### 为什么必须落盘

- dolphin agent 容器 LLM context 有 token 上限（推测 ~32k 输入 + 8k 输出）
- 23k 字 SPEC 当 tool_use 参数 → tool_use payload 也 ~6k token
- agent 历史 + skill prompt + 工具列表 + 23k SPEC 输入 + tool_use 输出 → **撞限**
- 实测崩：「Agent 服务异常」（2026-05-12 SAIC 缺件车）

### 落盘流程

```
agent: <写完完整 spec.md，23k 字>
agent: 调 save_app_design_doc(md_content=<整篇 SPEC>, app_name="...", env="<alias>")
后端: 落盘 + 解析 + 返回 {doc_token: "appdoc_1_a1b2c3d4", summary: {...}}
agent: 在 chat 展示**业务摘要**给用户：
       "已生成《缺件车管理系统》设计：
        - 角色 8 项（如 APP 现场操作员 / Web 业务管理员 / 主数据管理员 ...）
        - 数据字典 7 项
        - 数据模型 17 项
        - 表单 20 项
        - 权限矩阵 20 项
        这样设计可以开始建应用了吗？同意请回复 OK"
用户: OK
agent: 调 generate_app_from_doc(doc_token="appdoc_1_a1b2c3d4", env="<alias>")
       —— **禁止**再传 md_content
后端: 读盘 → upload-doc 解析 → auto-create → 返回 app_id
agent: 在 chat 报告创建成功
```

### 🚨 禁止行为

| 禁止 | 正确 |
|------|------|
| save 后立即调 generate（没给用户审摘要）| save → chat 摘要 → 等用户 OK → generate |
| generate(doc_token=...) 同时又传 md_content | 只传 doc_token，md_content 留空 |
| 长 SPEC 直接 generate(md_content=23k) | 必先 save_app_design_doc 拿 token |
| 用户改字段重试时 generate(doc_token=旧, md_content=新) | 重新调 save_app_design_doc 拿新 doc_token，再 generate(doc_token=新) |

### 用户改 X 改 Y 时的协议

```
用户: 把"返修计划员"改成"维修计划员"，再加一个"调度员"角色
agent: 好的，重新整理 SPEC...
agent: <重写完整 spec.md>
agent: 调 save_app_design_doc(md_content=<新 SPEC>, app_name="...", env="...")
后端: 返回 {doc_token: "appdoc_1_x9y8z7w6"}  # 新 token 覆盖旧
agent: chat 展示新摘要 + 等 OK
用户: OK
agent: generate_app_from_doc(doc_token="appdoc_1_x9y8z7w6", env="...")
```

老 doc_token 自然失效（24 小时后清理，或被新 save 覆盖）。

### STEP 1.7 跟 STEP 1.5 的关系

| | STEP 1.5 check_model_codes | STEP 1.7 save_app_design_doc |
|-|---|---|
| 时机 | 写完 spec 数据模型章节 | 写完整篇 spec |
| 输入 | model_codes 数组 | 整篇 md_content |
| 输出 | conflicts / suggestions | doc_token + summary |
| 失败处理 | 改 modelCode 重写 spec → 再 check | 改 md → 重新 save 拿新 token |

两步**都**做。1.5 是子表检查；1.7 是整篇落盘 + 业务摘要给用户审。
```

---

## 在 STEP 2（generate_app_from_doc）章节加规则

```markdown
## STEP 2：generate_app_from_doc 调用（v0.1.4 改）

### 调用规则

| SPEC 长度 | 调法 |
|----------|-----|
| < 8000 字符 | `generate_app_from_doc(md_content=<完整 md>, env="<alias>")` |
| >= 8000 字符 | **必须**先走 STEP 1.7 拿 doc_token，再 `generate_app_from_doc(doc_token="<token>", env="<alias>")` |

### 禁止

- generate(md_content=<23k>) 直接调 → 撞 dolphin agent 容器 token 限
- generate(doc_token=..., md_content=...) 两个都传 → 后端忽略 md_content 但 LLM 已经吐了 23k payload 不划算
```

---

## 怎么应用这个补丁

### Step 1: 编辑 dolphin admin 上的 skill

1. dolphin admin → Skills 管理 → 找 **ai-builder-unified**（v0.1.3 状态）
2. 复制 v0.1.3 内容 → 改成 v0.1.4
3. 在 STEP 1.5 章节后插入「## STEP 1.7：长 SPEC 必先落盘拿 doc_token」整段
4. 改 STEP 2 章节添加调用规则表
5. 保存 → 重新发布到能力市场 → 关联到 4 个 agent（Builder / Coding / 包工 / 复旦 SAIC 私有 builder）

### Step 2: 让 dolphin chat 拉到第 61 个工具

dolphin admin 在 agent 编辑弹窗有缓存，**必须删除现有 MCP 服务关联**再「+ 添加」「连接并获取工具列表」「确认添加」才能拉到 `save_app_design_doc`。

需要操作的 agent（线上 4 个 + 客户私有的）：
- AI-aPaaS-Builder（23c93f30d8）
- AI-aPaaS-Coding（f765238af4）
- AI-aPaaS-Vibe（51ebb5937b）—— Vibe 不需要这两个工具但 MCP 列表也要刷
- 客户私有 Builder agent（如 SAIC 的 1b181a6779，复旦的 547e911115，宝洁的 76b2b8cecc）
- 客户私有 Coding agent

### Step 3: 实测验证

让 SAIC 复测「缺件车管理系统」：
```
用户: 我这边有个需求，叫缺件车管理系统...
agent: <写 SPEC → 1.5 check_model_codes → 1.7 save_app_design_doc>
agent: chat 摘要 + doc_token + 等 OK
用户: OK
agent: generate_app_from_doc(doc_token=..., env="saic")
后端: ✅ 成功创建应用
```

---

## 维护说明

未来如果发现 dolphin agent 容器 token 限制实际更宽 / 更紧，调整 STEP 1.7 触发阈值：

| 调整项 | 当前 | 候选值 |
|--------|------|--------|
| 必走 save 阈值 | 8000 字 | 4000 / 6000 / 12000（按 dolphin 反馈调）|

后续如果做方案 B（分段写 session 模式），STEP 1.7 进一步演化为：
- `start_app_doc_session(app_name)` → session_id
- `append_app_doc_section(session_id, section_name, section_md)` × 6
- `finalize_app_doc(session_id)` → doc_token
