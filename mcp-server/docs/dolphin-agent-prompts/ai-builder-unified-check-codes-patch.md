# ai-builder-unified skill v1.2 补丁 — modelCode 设计阶段预检（2026-05-11）

> Phase 6 实测发现 apaas 平台对保留前缀的 modelCode 主动加 `_` 后缀（如 spec 写
> `org_dept`，apaas 实际创建为 `org_dept_`），导致**过程 SPEC 文档跟实际部署不一致**。
>
> 用户拍板 D 方案：**设计阶段就 check + AI 重选 + SPEC 重出**。

---

## 后端已加 MCP 工具 `check_model_codes` （commit 待 follow）

工具签名：

```python
check_model_codes(env: str, model_codes: list[str]) -> dict
# returns:
#   {
#     ok: True,
#     no_conflict: bool,
#     conflicts: [
#       {code, conflict_type: "tenant_existing" | "reserved_prefix",
#        reason, conflicts_with},
#       ...
#     ],
#     suggestions_avoid: [全部已占用 modelCode],
#     reserved_prefixes: [org_, employee_, attendance_, recruitment_,
#                         headcount_, candidate_, movement_, employment_, ...],
#     summary, user_action_required,
#   }
```

检查 2 层：
1. **租户内冲突**：调 list_apaas_models_in_env(env) 查同租户跨应用全部 modelCode
2. **平台保留前缀**：硬编 8 个已知保留前缀（org_/employee_/... 历史 _ 现象反推 +
   持续维护）

---

## ai-builder-unified skill workflow 补丁

在 skill 现有 STEP 1 (规范驱动写 spec) 之后、**STEP 2 (调 generate_app_from_doc) 之前**，
强制插入这一步：

```markdown
## STEP 1.5：modelCode 设计阶段冲突预检（🆕 v1.2 强制）

写完 spec 第 3 章节"数据模型"后，**调用前必先 check**：

```
1. 提取 spec 里所有 modelCode（含子表）
2. 调 check_model_codes(env=<alias>, model_codes=[...])
3. 看返回的 conflicts:
   - **no_conflict == True** → 直接进 STEP 2
   - **no_conflict == False** → 走【冲突修复子流程】
```

### 冲突修复子流程

```
对每个 conflict：
  - conflict_type=="tenant_existing": 该 code 已被同租户其他应用占用
    → 用 LLM 选语义相近的新 code，前缀加业务命名空间（hr_/sales_/fin_/biz_/proj_）
    → 避开 conflicts_with[].code 整个清单
  - conflict_type=="reserved_prefix": 撞 apaas 平台保留前缀（org_/employee_/...）
    → 换成 hr_*** / staff_*** 等业务前缀

例：
  原 code: org_dept           （撞 reserved_prefix=org_）
  新 code: hr_dept             （换业务前缀）

  原 code: employee_profile    （撞 reserved_prefix=employee_）
  新 code: staff_profile       （换语义近义词）
```

### 🚨 命名铁律

| 禁止 | 允许 |
|------|------|
| 简单加 `_` 后缀 `org_dept_` | 业务前缀 `hr_org_dept` |
| 简单加 `t_` 前缀 `t_org_dept` | 业务前缀 `hr_dept_master` |
| 任意保留前缀 `org_/employee_/attendance_/...` | 显式业务前缀 `hr_/sales_/fin_/proj_/sup_` |
| 与同租户已有 modelCode 完全相同 | 加业务前缀消除歧义 |

### 修完 spec 必须做的 3 件事

1. **回写 md spec 文档**：把所有改过的 modelCode 用 search & replace 替换（包括
   表单 modelField 引用、字段 ref_model_code 引用、SubTable subTableField 等）
2. **重新调 `validate_builder_doc(md_content=...)` 校验** 改后 md 仍 passes_strict
3. **再次调 `check_model_codes(env, model_codes=[改后清单])`** 确认 no_conflict==True

### 🚨 必须把改后的完整 SPEC 重新展示给用户审

冲突修复 = SPEC 内容变化 = 用户审过的 spec 已经不算数。**必须重新展示 + 等用户
明确说"OK 按这个 spec 来"** 才能进 STEP 2 generate_app_from_doc。

不要假设用户隐式同意。

回复模板：

> "我检测到 X 个 modelCode 撞了 apaas 平台保留前缀 / 租户内已有模型，
> 已经改为：
> - org_dept → hr_dept
> - employee_profile → staff_profile
> - ...
>
> 请审一下改后完整 SPEC：
> [完整 md 内容]
>
> 没问题的话我就开始创建应用。"
```

## 在 STEP 4（部署）后也要再做一次回查（兜底）

即使 STEP 1.5 检查过没冲突，apaas 平台**还可能**主动追加 _ 后缀（未知保留字 / 新版本 apaas
保留字扩展）。所以 STEP 4 deploy_application 完成后：

```
1. 调 list_apaas_models_in_env(env=<alias>, apaas_app_id=<新建的 app_id>)
2. 对比平台返的 modelCode 跟 spec 里的 modelCode
3. 不一致 → WARN 报告给用户 + 触发已知保留前缀清单扩展（运维加入 _APAAS_RESERVED_MODEL_PREFIXES）
```

---

## 怎么应用这个补丁

### 方案 1（推荐）：改 dolphin admin 上 ai-builder-unified skill 内容

1. dolphin admin → Skills 管理 → 找 ai-builder-unified
2. 进编辑器
3. 在 STEP 1 章节末尾 + STEP 2 章节前插入「## STEP 1.5：modelCode 设计阶段冲突预检」整段
4. 在 STEP 4 章节末尾追加「## 部署后回查兜底」
5. 保存 → 重新启用 → 发布到能力市场（如果之前公开过）
6. 关联到 AI-aPaaS-Builder agent + AI-aPaaS-Coding agent（如已关联，重新触发缓存刷新）

### 方案 2（轻量）：改 AI-aPaaS-Builder agent prompt 加铁律

在 agent prompt「## 硬规则」末尾追加：

```markdown
**🚨 modelCode 设计阶段预检（v1.2 强制铁律）**：

调 generate_app_from_doc / update_app_from_doc 之前**必先**调
`check_model_codes(env, model_codes=[spec 里所有 modelCode 含子表])`。

返回 conflicts 非空时：
- 不要重试 generate
- 用 LLM 选语义相近的新 code（**加业务前缀** hr_/sales_/fin_/biz_/proj_/sup_/staff_/master_）
- **禁止**简单加 `_` / `t_` 前后缀
- 重写 md spec → 重新 validate_builder_doc → 再次 check_model_codes
- 改后**必须把完整 SPEC 重新展示给用户审过**才 generate
```

方案 2 更快上线（5 分钟），但 skill 内容本身不变，依赖 prompt 引导。方案 1
治根（skill workflow 写死）。

## 维护 `_APAAS_RESERVED_MODEL_PREFIXES`

后端 `backend/app/mcp_server.py` 第 ~1237 行硬编保留前缀清单：

```python
_APAAS_RESERVED_MODEL_PREFIXES = {
    "org_", "employee_", "employment_", "attendance_",
    "recruitment_", "headcount_", "candidate_", "movement_",
    "user_", "role_", "dept_", "position_",
}
```

每次发现新前缀被 apaas 自动加 _ 后缀时，回来追加。
