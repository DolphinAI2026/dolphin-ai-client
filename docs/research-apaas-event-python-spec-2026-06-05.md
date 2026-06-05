# aPaaS 业务事件 自定义节点代码生成规范（从平台 AI prompt 库实证）— 2026-06-05

> 来源：apaas-trial 后台「AI 管理 → 提示词管理」(`/apaas/aigc/api/prompts/pageQuery`)，共 **81 条** 平台内置 prompt。
> 本文抽取与「业务事件自定义节点 Python/JS 代码生成」相关的规范，用于修复 ai-builder
> 生成的业务事件「写的 Python 不符合规范 / 拿不到节点字段属性 → 没法执行」。

## 0. 81 条 prompt 里跟我们相关的

代码/节点类：`Python代码生成`(自定义节点Python) / `JavaScript代码生成`(自定义节点JS) /
`groovy脚本配置` / `正则表达式生成` / `公式规则简易版条件生成` / `整合节点规则`。
流程类：`流程配置设计` / `流程上下文`。
表单类：`表单内容设计` / `表单配置(带子表)json` / `表单执行计划设置` / `表单权限配置` / `数据模型配置` 等。
（完整 81 条可随时再拉；本次重点 Python/JS 节点代码。）

## 1. aPaaS「Python代码生成」prompt 全文（自定义节点）

Role: Python脚本开发专家。Description: 精通Python脚本开发，根据业务需求生成符合要求的脚本代码。

Rules（关键）：
- 代码必须符合 Python 语法 + 完整错误处理。
- **必须参考 `<Return Example>` 结构生成返回 JSON 示例，必须是完全合法 JSON（无注释）。**

Context（平台运行时注入，关键）：
- `### 字段值结构描述` → `{businessDataTemplate}`
- `### 存在的字段描述` → `{fieldDescription}`

Output Format：Python 用 ```python``` 包裹；返回数据用 ```json``` 包裹。

**代码骨架（平台给的 invoke 契约）：**
```python
import os
# os.system("pip2 install requests")

def invoke():
    # 获取数据来源节点全部数据
    output = definesys.input()

    # 在这里进行数据的处理
    # 处理完成后把处理的结果 return 出去
    return output
```
Return Example：
```json
{ "test": "" }
```

## 2. aPaaS「JavaScript代码生成」prompt 的数据结构规范（Python 同源，关键！）

`## Data Structure / 表单数据结构`：
1. 不同组件类型，数据结构不同。
2. **主表字段**（非 `FORM_WIDGET_SON_TABLE` 组件）在 `afterFormData` 里；**子表**（`FORM_WIDGET_SON_TABLE`）在 `afterTableData` 里 —— **都以组件的 uuid 作为 key 存储**（不是字段 code！）。
3. `definesys.input()` 拿到的 `customNodeData` 是**数组**（可能多条，一般取第一条；过滤/统计时用多条）。
4. 子表组件 uuid 用子表组件 `children` 里的字段匹配。
5. 每个组件在自定义节点场景下有**严格的 TS 数据类型**（可选属性需判空）；复杂对象/关联数据（id/code 未指定时）取关联的 `label`/`name`/`username`/`fileName` 等比较。
   - 公共类型示例：`Person { account,id,phone,username,email?,managerId? }`、`Department { id,name,departmentCode,structureCode,structureName,leafNodeFlag }`、`Select { checked,color,id,label,... }` …（每种组件一套）。

> 即：要写出能跑的 Python，**必须先知道触发表单每个字段的 component uuid + 组件类型 + label**，
> 再用 `definesys.input()[0]['afterFormData'][<uuid>]` 取值。这就是用户说的「需要获取节点的字段属性」。

## 3. 我们当前的生成（gap）

`backend/app/mcp_server.py::create_form_event_with_python_code`（路线 A，建「表单触发+Python3自定义节点」事件）：
- 只校验 `python_code` 含 `definesys` + `invoke`，**docstring 没给平台的 invoke/input 契约、没给 afterFormData/afterTableData(by uuid) 数据结构、没让 agent 先拉字段 uuid**。→ agent 凭空写 Python，**寻址不到任何字段 → 不可执行**。
- 自定义节点 `boCodeBORelationProperties: {}` 留空（trigger 节点从 stub detail 拷了平台元数据，custom 节点没有）。
- `relatedDataNodeId` 已指向 trigger 节点（数据来源链路在）。

**我们其实已有工具拿字段 uuid**：`list_apaas_form_components(env_id, apaas_app_id, form_id)` 返回每个组件 `uuid / label / component_type / bo_code / required`（docstring 自己都写了「listPageBusinessData 行数据 key 是 component uuid」）。只是 **event-python 这条没把它接进去 + 没把规范喂给 agent**。

## 4. 修复方向（草案，待与用户确认 §5 写侧）

1. **把 §1+§2 规范写进 `create_form_event_with_python_code` 的 docstring/guidance**（让 agent 照平台 invoke/input/return 契约 + afterFormData/afterTableData(by uuid) 写代码）。
2. **强制 agent 先调 `list_apaas_form_components(trigger_form_id)`**，把 uuid→label/type 映射当作 `businessDataTemplate`/`fieldDescription` 注入；Python 用真实 uuid 取值。
   - 可选：工具内部自动拉一次组件、把「字段 uuid 速查表」回写进返回，降低 agent 出错率。
3. **补 custom 节点 `boCodeBORelationProperties`**（若运行时确实需要节点字段绑定 —— 待 §5 验证）。

## 5. ⚠️ 未解：数据「写」侧 SDK / 节点（必须先搞清才能正确修）

用户的样例事件要做**两个写操作**：①把当前电池护照 `lifecycle_stage` 改成 `produced`；②新增一条「生命周期事件」记录。
但 §1 的自定义节点契约是 **input → 处理 → return**（读 + 算 + 回传），**没覆盖「写其它模型/更新记录」**。两种可能：
- (a) 写操作由 **下游节点**（`ASSIGNMENT_NODE` 赋值 / `UPDATE_NODE` 更新 / 「新增数据」节点）完成，Python 只算值 return 给下游；
- (b) Python 直接用 `definesys` 的写 API（create/update/DAO）写库。

`create_form_value_change_event`（我们另一个工具）用的是 `ASSIGNMENT_NODE`（赋值节点）—— 说明平台对「改字段」有专门节点。所以本事件大概率是 **(a) 多节点 DAG**，单 custom Python 节点可能根本不够。

**待办**：从 apaas prompt 库 / helpDoc 再挖：①definesys Python SDK 的写 API（若有）；②`整合节点规则`/`表单执行计划设置` 里的节点编排规范；③确认「更新记录 + 新增记录」该用哪些节点类型。

## 6. 决策 + 卡点（2026-06-05）

- **用户选定写侧机制 = (b) definesys SDK 直接写**（Python 自定义节点里直接调 SDK 写库，不靠下游节点）。
- **卡点**：定位 definesys Python SDK 的写 API 时——
  - 81 条 prompt 库**只出现 `definesys.input()`**（读），无任何 `definesys.create/update/save/query/dao` 等写方法；
  - `xdap-admin/helpDoc/query` 裸调返 500（缺参/头）。
  → **写 SDK 不在 AI prompt 库里**，需另找：apaas 自定义节点代码编辑器内联的「API 说明 / 函数列表」面板（最权威，可读）/ 得帆云开发者文档 / 用户直接给参考。
- **下一步**：拿到 definesys 写 SDK（方法签名 + 例子：如何按 boCode/modelCode create 一条记录、按 id update 一条记录、query）后，即可重写 `create_form_event_with_python_code` 的 guidance（§4）让 agent 照 §1+§2 读 + 该 SDK 写。

## 7. 「去扒」结果（2026-06-05，浏览器实测）

用 Claude-in-Chrome 进 apaas 后台扒了一圈，**写 SDK 在前端/平台 AI 工具里都找不到**：
- **打开了那个 AI 建的事件的自定义节点编辑器**（DAG = 表单操作触发 → AI 业务逻辑(PYTHON3) → 结束，正是我们生成的 3 节点）。
- **读出节点里我们生成的 Python（6259 字）**：开头就是 `def _call(module, names, *args)` —「兼容不同运行时 API 命名：按候选方法名依次尝试」+ `_trigger_data()` 里挨个试 `get_trigger_data/getTriggerData/get_input/getInput/get_context/getContext`。**= agent 根本不知道真 API，在瞎猜方法名**（坐实 root cause）。正确读法本应是 `definesys.input()`（§1）。
- `window.APaaSSDK` = 前端 Vue SDK（router/store/env），**不是后端 Python definesys**。
- 编辑器加载时**没拉任何 SDK/函数列表接口**（只拉 event detail）；`helpDoc/query` 裸调 500。
- 「生成参数列表」按钮 = 生成**返回 Response 示例**的字段表（我们代码没正经 return → 暂无数据），不是输入字段结构。
- **海豚AI**（平台自带 AI 代码生成）背后就是 §1 那条「Python代码生成」prompt —— **只覆盖 input→transform→return，没有写 SDK**。

**⇒ 关键信号**：apaas 自己的 AI 代码生成范式就是「读 `definesys.input()` → 处理 → `return`」，**平台 AI 不用 SDK 写库**。所以「definesys SDK 直接写」要么是**开发者文档专属**（`https://definesys.cn/support/product-center/docs/`，未在本次 headless 扒到具体页），要么真实范式其实是 **下游写节点**（UPDATE_NODE / 新增数据 / ASSIGNMENT_NODE —— 我们 `create_form_value_change_event` 已用 ASSIGNMENT_NODE，平台明确支持）。**需用户拍板**（见 §8）。

## 8. 无论写侧怎么定，先能做的（READ 侧修复，正确性独立）

把 `create_form_event_with_python_code` 的 guidance 重写成真 spec：
1. 强制 agent 先 `list_apaas_form_components(trigger_form_id)` 拿 uuid→label/type；
2. Python 按 `output = definesys.input()` → `output[0]['afterFormData'][<uuid>]` 读（§1+§2），**禁止再 `_call`/猜方法名**；
3. return 结构按平台 Response 示例。
这一步把「输入侧瞎猜 API」根治（半个问题），且与写侧机制无关。**写侧等用户给 definesys 写 SDK 文档 / 或改走下游写节点。**
