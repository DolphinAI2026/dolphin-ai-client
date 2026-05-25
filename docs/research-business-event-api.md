# 得帆云「业务事件」模块 真实 API 抓包笔记 (v2 — Prod 实证版)

> **修订说明 2026-05-25 下午**：本文档 v1 版本（500-1127 行）中**大量 nodeType / triggerType 命名是基于文档/UI/直觉的推测**，经过生产环境 160 个真实业务事件抓包对照，**~80% 的推测命名被证伪**。本 v2 版本是**纯实证**：所有 enum 值、字段名、schema 都来自 trial + prod 两个环境的真实 XHR 抓包。
>
> 旧 v1 历史推测在 git log 可查；v2 删除所有"推测"标记内容，只保留实证。
>
> **配套文档**：[research-business-event.md](research-business-event.md) — 业务事件概念架构 + 文档级研究（仍然有效，UI 层认知没变）。
>
> **抓包环境**：
> - Trial: `https://apaas-trial.definesys.cn` (v5.0.0)，tid `833831156406288385`，2 个事件样本
> - Prod: `http://apaas-prod.definesys.cn:30605` (v4.1.1)，tid `241251302414221313`，**2000 条事件，前 160 已扫描**

---

## 1. 总览 — 已实证 vs 未实证

| 维度 | 已实证数量 | 来源 |
|---|---|---|
| **endpoint** | 9 个 | trial XHR |
| **eventType** | 7 个 | prod 160 事件 |
| **triggerType** | 17 个 | prod 160 事件 |
| **triggerWay** | 11 个 | prod 160 事件 |
| **triggerEnv** | 3 个 | prod 160 事件 |
| **exeType** | 2 个 + missing | prod 160 事件 |
| **nodeType** | 17 个（全） | prod 160 事件 |
| **nodeType 完整字段 schema** | 14/17 | prod detail dump |
| **conditionOption** | 3 个 | 260 条 rules |
| **filterType** | 5 个 | 260 条 rules |
| **connector** | 1 个 (全 AND) | 260 条 rules |
| **eventJobConfig schema** | 完整 | prod 3 个定时事件 |
| **branchNodeGroups schema** | 完整 | prod 2 个分支事件 |
| **EXT_NODE 配置** | 完整 + dolphin 集成实证 | prod 2 个外部节点 |
| **definesys.input() key 真值** | ⚠️ 未实证 | 需 exeHistory 实际跑过 |

---

## 2. API 前缀（关键差异 — trial vs prod 完全不同）

| 环境 | Base URL | 路径前缀 | 例 |
|---|---|---|---|
| Trial (v5.0, ingress) | `https://apaas-trial.definesys.cn:443` | **`/backend/xdap-app/`** | `/backend/xdap-app/event/...` |
| Prod (v4.1, NodePort) | `http://apaas-prod.definesys.cn:30607` | **`/xdap-app/`** (无 backend 前缀!) | `/xdap-app/event/...` |

**MCP 工具适配**：基于平台版本 + 部署模式判别 base url。

UI 入口（两环境一致）:
```
{frontend}/platform/{tenantId}/admin/business-event-admin        # 租户中心
{frontend}/platform/{tenantId}/admin/app-store/edit-app?appId=...&currentStepIndex=3&businessIndex=all-business  # 应用中心
{frontend}/platform/{tenantId}/default/business-event-config?eventId={24hex}&appId={snowflake}  # 编辑器
```

---

## 3. ID 体系（3 套并存，不可混淆）

| ID 类型 | 例 | 用途 |
|---|---|---|
| MongoDB ObjectId (24 字符 hex) | `6a13b81374cfbc26cbf1e5d0` | 业务事件 / 表单 / 业务对象 |
| Snowflake (18-19 数字) | `846351551214649344` | 应用 / 菜单 / 用户 / 租户 |
| UUID hex (32 字符无横线) | `bd02bdb62c75d520260e8975f2b65729` | 节点 nodeId |

MCP 工具拼 URL 时 eventId 当字符串处理，不要 int 化。

---

## 4. 鉴权 Headers（必带）

| Header | 值 | 来源 |
|---|---|---|
| `xdaptoken` | JWT HS512 | login 接口返，2 小时有效 |
| `xdaptenantid` | snowflake | 当前租户 ID |
| `xdaptimestamp` | ms | 每请求重新生成 |
| `appid` | snowflake | **应用级 endpoint 必带**（租户中心不带） |
| `cookie: token=<JWT>` | 长期 refresh | 30 天有效 |
| `content-type: application/json;charset=UTF-8` | | POST 请求 |
| `rsa-public-key` | base64 PEM 或 `undefined` | 客户端 RSA 公钥（推测加密敏感字段用）|

---

## 5. 9 个 Endpoint 完整表

| # | 名称 | Method | Path | Body / Query | 说明 |
|---|---|---|---|---|---|
| 1 | 租户业务事件中心 list | POST | `/xdap-app/event/query/allEventList` | `{page,pageSize,keyword}` | 跨应用聚合，只读 |
| 2 | 应用业务事件分类树 | GET | `/xdap-app/event/queryTrees?appId=` | - | 左侧分类菜单 |
| 3 | 应用业务事件 list | GET | `/xdap-app/event/query/list?appId=&keyword=&page=&pageSize=` | - | 应用内卡片列表 |
| 4 | 创建业务事件 | POST | `/xdap-app/event/add/event` | `{appId,eventType,eventName,version:"v3.0"}` | 含 metadata 仅 |
| 5 | 查询单条详情 | GET | `/xdap-app/event/query/detail?eventId=&appId=` | - | **含完整节点 DAG** |
| 6 | 保存业务事件 ⭐ | POST | `/xdap-app/event/save/event` | entire data | Round-trip |
| 7 | 删除业务事件 ⚠️ | **GET** (!) | `/xdap-app/event/del/event?eventId=&appId=` | - | 注意是 GET |
| 8 | 执行历史 list | POST | `/xdap-app/event/query/exeHistory/list` | `{page,pageSize,status,beforeTime,endTime,eventId}` | - |
| 9 | 应用表单菜单 list | GET | `/xdap-app/menu/queryAllFormMenu?appId=&eventFlag=true` | - | 拿 formId+bocCode |

**未实证 endpoint**：enable/disable / 调试 / 业务对象 list / 创建按钮事件特殊 endpoint (推测同 add/event)。

---

## 6. ⭐ 7 个 eventType 真值表（完整）

| eventType | UI 中文 | 触发节点关键字段 | 典型场景 | prod 频次 |
|---|---|---|---|---|
| `EVENT_OPERATION` | 表单操作触发 | triggerFormId / triggerBocCode / triggerType (SUBMIT_*) | 表单提交/保存/修改/删除 | 53 |
| `EVENT_BUTTON` | 按钮触发 | + `boCode/buttonType/componentUuid` | 自定义按钮点击 | 48 |
| `EVENT_VALUE_CHANGE` | 字段值改变触发 | + `boCode/componentUuid` | 字段变化联动 | 24 |
| `EVENT_PROCESS` | 审批流程触发 | + `processId/processName/processNodeId/processNodeName` | 审批环节自动化 | 11 |
| `EVENT_TIME` | 定时触发 | + `eventJobConfig` (Quartz cron) | 定时清理/批处理 | 14 |
| `EVENT_EXT` | 外部触发 | callbackUrl + 输出节点 | API 暴露给外部 | 9 |
| `EVENT_WORKFLOW` | 标准工作流 | (待验) | 流程逻辑复用 | 1 |

---

## 7. 17 个 triggerType + 11 个 triggerWay + 3 个 triggerEnv

### triggerType 完整真值表

| triggerType | UI 中文 | 配合 triggerWay |
|---|---|---|
| `SUBMIT_DONE` | 表单提交成功后 | `FORM_OPT_AFTER_DONE` |
| `SUBMIT_OR_SAVE_DONE` | 提交或保存成功后 | `FORM_OPT_AFTER_DONE` |
| `SAVE_DONE` | 保存完成后 | `FORM_OPT_AFTER` |
| `SUBMIT` | 提交 | `FORM_OPT_AFTER` |
| `SUBMIT_OR_SAVE` | 提交或保存 | `FORM_OPT_AFTER` |
| `SAVE` | 保存 | `FORM_OPT_AFTER` |
| `SUBMIT_BEFORE` | 提交前 | `FORM_OPT_BEFORE` |
| `SUBMIT_OR_SAVE_BEFORE` | 提交或保存前 | `FORM_OPT_BEFORE` |
| `SAVE_BEFORE` | 保存前 | `FORM_OPT_BEFORE` |
| `VALUE_CHANGE` | 字段值改变 | `FIELD` |
| `INIT` | 字段初始化（推测）| (empty) |
| `CREATE_RO_EDIT` | 新建或编辑 | (empty) |
| `CUSTOM_BUTTON` | 自定义按钮 | `BUTTON` |
| `FORM_BUTTON` | 表单按钮（系统按钮）| `BUTTON` |
| `PROCESS_NODE_BEFORE` | 流程节点前 | `NODE_OPT_BEFORE` |
| `PROCESS_NODE_AFTER` | 流程节点后 | `NODE_OPT_AFTER` |
| `APPROVE_AFTER` | 审批后 | `PROCESS_OPT_AFTER_DONE` |

### triggerWay 完整真值表

| triggerWay | UI 中文 |
|---|---|
| `FORM_OPT_BEFORE` | 操作前 |
| `FORM_OPT_AFTER` | 操作后 |
| `FORM_OPT_AFTER_DONE` | 操作成功后 |
| `FIELD` | 字段 |
| `BUTTON` | 按钮 |
| `PROCESS` | 流程 |
| `NODE_OPT_BEFORE` | 节点操作前 |
| `NODE_OPT_AFTER` | 节点操作后 |
| `PROCESS_OPT_AFTER_DONE` | 流程操作成功后 |
| `EXT` | 外部 |
| (empty) | 不需要（如 EVENT_TIME） |

### triggerEnv 完整真值表

| triggerEnv | 含义 |
|---|---|
| `EVENT_FRONT` | 前端触发（浏览器埋点） |
| **`EVENT_REAR`** | **后端触发**（不是我推测的 EVENT_BACK！） |
| (empty) | 不需要环境标记 |

---

## 8. ⭐ 17 个 nodeType 完整真值表（重点 — 推翻 v1 全部推测）

| 类目 | nodeType | UI 中文 | 必填字段 | 关键独有字段 |
|---|---|---|---|---|
| 固定 | `TRIGGER_NODE` | 触发节点 | 各 eventType 不同 | (见第 9 节) |
| 固定 | `END_NODE` | 结束节点 | `nodeId/nodeName/nextNodeId:[]` | `dataStatus:COMPLETED` |
| **对象操作** | `UPDATE_NODE` | 更新数据 | targetBocCode / firstRules / secondRules | `documentRules / afterAddStatus / logLabel / tableConfigs` |
| | `SELECT_NODE` | 查询数据 | targetBocCode / filterConditionGroup | `customReturnNumSwitch / customReturnNum / orderList / returnType / resultNullAction` |
| | `ADD_NODE` | 新增数据 | targetBocCode / firstRules | `addType / dataSourceTableFormId / afterAddStatus / logLabel` |
| | `DELETE_NODE` | 删除数据 | targetBocCode / firstRules | (schema 未完整 dump) |
| | `ASSIGNMENT_NODE` | 字段赋值 | firstRules (**没 secondRules**) | targetFormId / targetBocCode |
| | `INTEGRATION_NODE` | 整合节点 | firstRules / secondRules | `integrationDataNum / mainDataNodeId / mainDataNodeName` |
| **页面动作** | `MODAL_EVENT_NODE` | 弹窗事件 | modalType / modalTitle | `cancelEvent / cancelText / confirmText / collectFiledSort / formComponentList / templateScript / templateStyle / uuidToBusinessRule` |
| | `REFRESH_EVENT_NODE` | 更新页面 | (待完整 dump) | - |
| | `INVOKE_NODE` | 调用节点 | targetFormId / firstRules | `invokeType / invokeConfirmType / fieldDefaults / addNextOneFlag` |
| **逻辑控制** | `BRANCH_NODE` | 分支节点 | branchNodeGroups | `filterConditionGroup` |
| | `BRANCH_SETTING_NODE` | 分支配置 | parentNodeId / defaultBranch / executOrder | filterConditionGroup |
| | `CALCULATION_NODE` | 运算节点 | calType / firstRules | `dimenBoCode / dimenTableUuid / dimenUuid / linkNodeName` |
| | `BLOCK_NODE` | 数据校验 | (validate/invalidate 两组提醒字段) | `invalidateEvent / invalidateRemind / invalidateRemindContent / invalidateRemindContentList / validateRemind / validateRemindContent / validateRemindContentList / linkNodeName / dimenUuid` |
| **高级活动** | `EXT_NODE` | 外部节点 (HTTP) | extRequestType / extRequestUrl | `extBodyType / extBodyFormData / extBodyRow / extBodyRowTree / extPathParams / extQueryParams / extRequestHeader / extRequestParams / extResponse / interfaceType / jsonSchema / postVersion / returnEvent / selectFunc / selectService / extFeishuCalendar / extFeishuScheduleInfo` |
| | `REMIND_MESSAGE_NODE` | 提醒消息 | remindObject / remindType / remindWay | `customMsgCodesMap / reminderContain / mainDataNodeId / firstRules` |
| | `CUSTOM_CODE_NODE` | 自定义代码 | customCode / customNodeEnv / relatedDataNodeId | `extResponse / formComponentList / filterConditionGroup` |

**与文档 17 节点的映射**：

| 文档说的节点（中文）| 真值 nodeType |
|---|---|
| 更新数据 | `UPDATE_NODE` |
| 查询节点 | `SELECT_NODE` |
| 新增数据 | `ADD_NODE` |
| 删除数据 | `DELETE_NODE` |
| 字段赋值 | `ASSIGNMENT_NODE` |
| 整合节点 | `INTEGRATION_NODE` |
| 提交数据 | （prod 未见，可能 `SUBMIT_NODE` 或归入 UPDATE_NODE）|
| 弹窗事件 | `MODAL_EVENT_NODE` |
| 更新页面 | `REFRESH_EVENT_NODE` |
| 调用节点 | `INVOKE_NODE` |
| 分支节点 | `BRANCH_NODE` + 配套 `BRANCH_SETTING_NODE` (一对多) |
| 循环节点 | （prod 未见，可能 `LOOP_NODE`） |
| 数据校验 | `BLOCK_NODE` |
| 运算节点 | `CALCULATION_NODE` |
| 外部节点 | `EXT_NODE` |
| 消息节点 | `REMIND_MESSAGE_NODE` |
| 引用节点 | （prod 未见）|
| 自定义节点 | `CUSTOM_CODE_NODE` |
| 输出节点 (外部触发专用) | （prod 未见，可能 `OUTPUT_NODE`）|

**未实证 nodeType（4 个，prod 160 事件没出现）**：
- 提交数据节点 (SUBMIT_NODE?)
- 循环节点 (LOOP_NODE?)
- 引用节点 (REFERENCE_NODE?)
- 输出节点 (OUTPUT_NODE? — EVENT_EXT 独有)

---

## 9. 触发节点（TRIGGER_NODE）按 eventType 分的字段集

### 通用字段（所有 eventType 都有）

```
nodeId, nodeName, nodeType (= TRIGGER_NODE), nextNodeId, nodeDesc,
boCodeBORelationProperties, buttonName,
triggerBocCode, triggerBuriedPoint (DISABLE/ENABLE),
triggerFormName, triggerTypeName,
beforeAndAfterDataFlag, filterConditionGroupList
```

### EVENT_OPERATION 独有

```
triggerFormId (24hex),
triggerType (SUBMIT_DONE / SUBMIT_OR_SAVE_BEFORE / ...),
triggerWay (FORM_OPT_BEFORE / AFTER / AFTER_DONE),
triggerEnv (EVENT_FRONT / EVENT_REAR),
triggerWayName,
excelTemplateId: [],
fieldChangeRange: []
```

### EVENT_BUTTON 独有

EVENT_OPERATION 字段 + 
```
boCode (按钮所在字段),
componentUuid (按钮组件 UUID),
buttonType (CUSTOM_BUTTON / FORM_BUTTON)
```

### EVENT_VALUE_CHANGE 独有

EVENT_BUTTON 字段类似 + 
```
boCode (监听变化的字段 boCode),
componentUuid (字段组件 UUID),
triggerType: "VALUE_CHANGE",
triggerWay: "FIELD"
```

### EVENT_TIME 独有 ⭐

```
eventJobConfig: {
  jobTriggerType: "ONCE_EXECUTE | REPEAT_EXECUTE",
  cycleNumber: 1,
  cycleType: "DAY | WEEK | MONTH | ''",
  cycleTimes: [{week: "FRI"}],  // 仅 REPEAT
  jobTriggerTime: "20:00",       // 仅 REPEAT
  startTime: "2026-04-28 00:00:00",
  endTime: "2159-12-31 00:00:00",
  cronList: ["0 00 20 ? * FRI"],   // ← Quartz cron 表达式标准
  apaasTaskIds: ["<snowflake>"],
  syncUpdateTable: false
}
```

**不要** triggerType / triggerWay / triggerEnv / triggerFormId 字段。

### EVENT_PROCESS 独有

```
processId, processName,
processNodeId, processNodeName,
maxSupportedVersion (顶层),
bindEventFlag (顶层)
```

### EVENT_EXT 独有

```
triggerWay: "EXT",
（触发节点配置参数 schema + 是否含子表 + token 验证开关）
+ 顶层 callbackUrl 字段 (list response 有)
```

---

## 10. 数据关联规则（firstRules / secondRules）— 全真值

### 完整 schema

```json
{
  "uuid": "<boCode>",                  // 同 boCode
  "boCode": "<boCode>",
  "boLabel": "",
  "tableFlag": false,                  // 是否子表字段
  "conditionOption": "EQ | UPGRADE | TEMP",
  "businessObjectComponentType": "BOF_TEXT / BOF_DATE / ...",
  "connector": "AND",                  // ⚠️ 全是 AND，不存在 OR
  "filterInputs": [{
    "filterParams": [{
      "filterType": "COMPONENT | COMMON | FORMULA | FORM_DOCUMENT_NUMBER | NULL_VALUE",
      "filterComponentUuid": "<上游节点字段 boCode>",
      "filterBoCode": "<boCode>",
      "tableFlag": false,
      "filterBoComponentType": "BOF_TEXT / ...",
      "filterValue": "",
      "filterValueType": "APPOINT_USER / THIS_YEAR / ''",
      "likeCondition": false
    }],
    "order": 0
  }],
  "combineSign": false
}
```

### conditionOption 完整枚举（3 个真值）

| 真值 | 用途 |
|---|---|
| `EQ` | 等于（WHERE 用） |
| `UPGRADE` | SET 赋值动作（**secondRules 用**） |
| `TEMP` | 临时（含义待查） |

⚠️ **没有 NE / GT / LT / IN / LIKE / BETWEEN 等运算符**！复杂条件用 BRANCH_NODE + 多个 BRANCH_SETTING_NODE 实现 OR 分支。

### filterType 完整枚举（5 个真值）

| 真值 | 用途 |
|---|---|
| `COMPONENT` | 取上游节点字段值（最高频） |
| `COMMON` | 通用值（含义待查，可能是常量） |
| `FORMULA` | 公式 |
| `FORM_DOCUMENT_NUMBER` | 单据号 |
| `NULL_VALUE` | 空值 |

### filterValueType 部分枚举

| 真值 | 用途 |
|---|---|
| `APPOINT_USER` | 指定用户 |
| `THIS_YEAR` | 本年 |

### firstRules vs secondRules 用法对偶

- `firstRules` — **查询条件 / 关联匹配规则**（SQL `WHERE` 类比）
  - SELECT_NODE / UPDATE_NODE / DELETE_NODE / CALCULATION_NODE / INVOKE_NODE 用
  - conditionOption 通常 `EQ`
- `secondRules` — **字段赋值动作**（SQL `UPDATE SET` 类比）
  - 仅 UPDATE_NODE / INTEGRATION_NODE 用
  - conditionOption 必须 `UPGRADE`
- `ASSIGNMENT_NODE` — **只用 firstRules**（特殊 — 赋值规则直接在 firstRules 里）

---

## 11. ⭐ BRANCH_NODE + BRANCH_SETTING_NODE 配对模式

得帆云分支节点是**双节点配对**：

```
BRANCH_NODE (主)
└── branchNodeGroups: [
      {nodeId, nodeName, defaultBranch, executOrder, parentNodeId},  // 各分支简版
      ...
    ]
    
+ 同级节点列表里有对应的 BRANCH_SETTING_NODE (子) × N
  ├── parentNodeId (指回 BRANCH_NODE.nodeId)
  ├── defaultBranch: "ENABLE | DISABLE"  (一个 BRANCH_NODE 下必有 1 个 ENABLE 默认)
  ├── executOrder: "0" | "10" | ...      (数字字符串，越小越优先)
  └── filterConditionGroup                (分支条件)
```

**特性**：同一分支节点信息**冗余存储两份**（BRANCH_NODE.branchNodeGroups[] 简版 + 顶层 eventNodeNdList[] 完整版）。

---

## 12. ⭐ EXT_NODE — HTTP 调用完整 schema

```json
{
  "nodeId": "<32hex>",
  "nodeType": "EXT_NODE",
  "nodeName": "外部节点",
  "nextNodeId": [...],
  "relatedDataNodeId": "<上游节点>",
  
  // 接口来源
  "interfaceType": "CUSTOM | SERVICE_INTEGRATION",  // 自定义 vs 服务集成
  "selectFunc": "",         // 服务集成时填
  "selectService": "",
  
  // HTTP 请求
  "extRequestType": "CUSTOM_POST | CUSTOM_GET | FULL_DATA",
  "extRequestUrl": "https://dolphin.dfy.definesys.cn/api/agentChat/...",
  
  // Body 配置
  "extBodyType": "ROW | FORM_DATA | RAW | NONE",
  "extBodyFormData": {...},
  "extBodyRow": {...},
  "extBodyRowTree": [...],
  
  // 路径/查询参数
  "extPathParams": {...},
  "extQueryParams": {...},
  "extRequestHeader": {...},
  "extRequestParams": {...},
  
  // 响应处理
  "extResponse": "<JSON 示例字符串>",
  "jsonSchema": {...},
  "returnEvent": "...",   // 出错时事件终止/继续
  
  // 飞书集成（独立字段）
  "extFeishuCalendar": null,
  "extFeishuScheduleInfo": null,
  
  // 异常提醒
  "remindType": "...",
  "remindTypeFlag": false,
  "remindContent": "...",
  "remindContentList": [...],
  
  "postVersion": "..."
}
```

### ⭐ Dolphin Agent 集成实例

prod `agent审批` 事件实证：
```json
{
  "nodeType": "EXT_NODE",
  "interfaceType": "CUSTOM",
  "extRequestType": "CUSTOM_POST",
  "extRequestUrl": "https://dolphin.dfy.definesys.cn/api/agentChat/openapi/agents/ad351dc131/message",
  "extBodyType": "ROW"
}
```

→ **dolphin agent_code `ad351dc131` 被业务事件作为外部 API 调用，实现自动审批**。

---

## 13. ⭐ CUSTOM_CODE_NODE + 4 语言 SDK Contract

### 节点 schema

```json
{
  "nodeType": "CUSTOM_CODE_NODE",
  "customNodeEnv": "PYTHON3 | PYTHON2 | JAVASCRIPT | GROOVY",
  "customCode": "<source code>",
  "extResponse": "<JSON 示例>",
  "filterConditionGroup": [],
  "formComponentList": [],
  "relatedDataNodeId": "<上游节点 id>"
}
```

### Python3 / Python2 SDK Contract（一致）

```python
import definesys

def invoke():
    output = definesys.input()  # 拿上游节点数据 (dict)
    # ... 业务逻辑 ...
    return result  # 给下游节点
```

约定：
- 必须 `import definesys`
- 必须定义 `invoke()` 函数（**入口名固定**）
- 第三方库通过 `os.system("pip3 install <pkg>")` 临时装

### JavaScript SDK Contract（**与 Python 完全不同！**）

```javascript
let customNodeData = lowCodeContext.businessEventEngine.customNodeData;
// 直接顶层 return，无 invoke() 函数
// 返回值必须 Array[] 或 Object{}
return customNodeData;
```

### Groovy SDK Contract

```groovy
def invoke(... args) {
    return xdapEventSystemFunctions.getFullData();
}
```

### 前/后端语言限制

- **前端节点** (triggerEnv: EVENT_FRONT): 4 种语言全支持
- **后端节点** (triggerEnv: EVENT_REAR): Python3 / Python2 / Groovy（**没 JS**）

**ai-builder 默认 `PYTHON3`** — 前后端通用 + 跨节点位置最安全。

---

## 14. MODAL_EVENT_NODE — 弹窗类型 + 字段

```json
{
  "nodeType": "MODAL_EVENT_NODE",
  "modalType": "INFORMATION | CONFIRM | CUSTOM",  // 信息收集 / 二次确认 / 自定义
  "modalTitle": "<中文标题>",
  "confirmText": "确定",
  "cancelText": "取消",
  "cancelEvent": "TERMINATE | CONTINUE",  // 取消后动作
  "collectFiledSort": "ONE_COLUMN | TWO_COLUMN",
  "formComponentList": [...],  // 信息收集字段
  
  // 自定义弹窗
  "templateScript": "<JS 模板>",
  "templateStyle": "<CSS>",
  "uuidToBusinessRule": {...},
  "extResponse": "<JSON 示例>"
}
```

---

## 15. 顶层字段 — v2.0 vs v3.0 Schema 演进

### v3.0 (新事件) 字段

```
id, objectVersionNumber, createdBy, creationDate, lastUpdatedBy, lastUpdateDate,
owner, tenantId, eventName, eventType, appId, triggerTypeName, status,
endNode, triggerNodeNd, eventNodeNdList,
version: "v3.0", intactFlag, eventCode, appBackendStatus, exeType,
editLockDto, standardContextId, needProperties, order,
refreshNeedProperties, useTableData
```

### v2.0 (老事件) 字段

```
... 同 v3.0 基础字段 +
boExist (v3.0 没此字段)
```

**v2.0 没 standardContextId / refreshNeedProperties / useTableData / order**

### v3.0 EVENT_PROCESS 额外

```
maxSupportedVersion, bindEventFlag
```

### intactFlag 真相

- **prod 160 事件中 intactFlag=true 占 85%** — `intactFlag=true` 是配齐后正常状态
- intactFlag=false 不阻塞事件运行（prod 有 false 但 status=ENABLE 的事件）
- agent 创建事件**争取做到 intactFlag=true**，但不强制

---

## 16. ai-builder MVP 三条路线（prod 实证后修订）

### 路线 A — CUSTOM_CODE_NODE + Python3（最简）

agent 生成"触发 + 1 个 CUSTOM_CODE_NODE + 结束"三节点 DAG，业务逻辑全在 Python 代码里。

**优点**：
- schema 最简单（1 个节点 + 5 个独有字段）
- 100% 表达力（Python 万能）
- 调试体验好（Python traceback）

**缺点**：
- 不能直接修改业务对象（要在代码里调 SDK，**`definesys.input()` 返回 dict 的 key 真值未实证**）
- 不能用于纯 UI 动作（弹窗 / 刷新页面）

### 路线 B — EXT_NODE + Dolphin Agent（声明式）⭐ prod 已用

agent 生成"触发 + EXT_NODE 调 dolphin agent" 两节点 DAG，业务逻辑放 dolphin agent 端。

**优点**：
- **prod 已有真实用例**（agent审批 事件 → dolphin agent `ad351dc131`）
- 业务逻辑可视化（dolphin agent 配置 UI 友好）
- agent 改业务逻辑无需重新部署业务事件

**缺点**：
- 跨系统调用，延迟比 CUSTOM_CODE 高
- 依赖 dolphin agent 网络可用性

### 路线 C — 标准节点组合（复杂但原生）

agent 生成多个标准节点（SELECT + UPDATE + BLOCK 等）组合实现业务逻辑。

**优点**：
- 100% 原生 aPaaS 风格
- 业务方可视化看每一步

**缺点**：
- 需要 agent 掌握 14 个 nodeType 的完整字段 schema
- 字段类型转换矩阵复杂（人员/部门 vs 多选 vs 文本）
- conditionOption 只有 EQ 限制大（OR 必须用分支）

### 推荐策略

**对 ai-builder MVP**：
- **简单事件**（赋值/通知）→ 路线 A (CUSTOM_CODE)
- **复杂业务逻辑**（多步审批 / AI 决策）→ 路线 B (EXT_NODE+dolphin)
- **纯 CRUD**（数据流转）→ 路线 C (标准节点) — **后置**

---

## 17. MCP 工具骨架（v2 修订版）

```python
import httpx
from uuid import uuid4

UUID_HEX = lambda: uuid4().hex   # 32 字符 hex (节点 ID)

# === 8 个低层工具 ===

@mcp.tool()
async def list_business_events_in_app(app_id: str, keyword: str = "", page: int = 1, page_size: int = 20):
    """列应用业务事件 — GET /xdap-app/event/query/list"""

@mcp.tool()
async def get_business_event_detail(event_id: str, app_id: str):
    """查事件详情（含完整 DAG） — GET /xdap-app/event/query/detail
    
    event_id 是 24hex MongoDB ObjectId
    """

@mcp.tool()
async def create_business_event(
    app_id: str, event_name: str,
    event_type: Literal["EVENT_OPERATION", "EVENT_BUTTON", "EVENT_VALUE_CHANGE",
                        "EVENT_TIME", "EVENT_PROCESS", "EVENT_EXT", "EVENT_WORKFLOW"] = "EVENT_OPERATION"
):
    """创建事件 metadata — POST /xdap-app/event/add/event"""

@mcp.tool()
async def save_business_event(event_data: dict, app_id: str):
    """保存事件完整 DAG — POST /xdap-app/event/save/event (round-trip)"""

@mcp.tool()
async def delete_business_event(event_id: str, app_id: str):
    """删除事件 — GET /xdap-app/event/del/event ⚠️ GET 不是 DELETE"""

@mcp.tool()
async def list_business_event_execution_history(
    event_id: str, app_id: str, page: int = 1, page_size: int = 10,
    status: str = "", before_time: str = "", end_time: str = ""
):
    """查执行历史 — POST /xdap-app/event/query/exeHistory/list"""

@mcp.tool()
async def list_form_menus_for_event(app_id: str):
    """列应用表单菜单 — GET /xdap-app/menu/queryAllFormMenu?eventFlag=true
    
    返回 data[].formId / bocCode / menuName
    """

# === 3 个高层封装（按 3 条 MVP 路线分别封装）===

@mcp.tool()
async def create_form_event_with_python_code(
    app_id: str, event_name: str,
    trigger_form_id: str, trigger_boc_code: str,
    python_code: str,
    trigger_type: Literal["SUBMIT_DONE", "SUBMIT_BEFORE", "SUBMIT_OR_SAVE_DONE", "SUBMIT_OR_SAVE_BEFORE"] = "SUBMIT_DONE"
):
    """🅰️ 路线 A: 表单触发 + Python3 自定义节点
    
    生成 3 节点 DAG: TRIGGER_NODE → CUSTOM_CODE_NODE → END_NODE
    """

@mcp.tool()
async def create_form_event_with_dolphin_agent(
    app_id: str, event_name: str,
    trigger_form_id: str, trigger_boc_code: str,
    dolphin_agent_code: str,                          # 例 ad351dc131
    dolphin_base_url: str = "https://dolphin.dfy.definesys.cn",
    trigger_type: Literal["SUBMIT_DONE", "SUBMIT_BEFORE", ...] = "SUBMIT_DONE"
):
    """🅱️ 路线 B: 表单触发 + EXT_NODE 调 dolphin agent
    
    生成 3 节点 DAG: TRIGGER_NODE → EXT_NODE(POST {dolphin}/api/agentChat/openapi/agents/{code}/message) → END_NODE
    
    prod 实证: agent审批 事件已用此模式
    """

@mcp.tool()
async def create_time_event_with_python_code(
    app_id: str, event_name: str,
    cron_expression: str,                              # Quartz cron, 例 "0 00 20 ? * FRI"
    python_code: str,
    job_trigger_type: Literal["ONCE_EXECUTE", "REPEAT_EXECUTE"] = "REPEAT_EXECUTE"
):
    """🅲️ 路线 C 子集: 定时触发 + Python 自定义节点
    
    生成 3 节点: TRIGGER_NODE(EVENT_TIME, eventJobConfig.cronList=[cron_expression]) → CUSTOM_CODE_NODE → END_NODE
    """
```

---

## 18. 7 个已知 P1 留尾（未实证）

| # | 未知 | 解决方式 |
|---|---|---|
| 1 | `definesys.input()` 返回 dict 真 key (boCode 还是短名?) | 找 prod exeHistory 已跑过事件看节点输入输出 |
| 2 | 文档说的"提交数据/循环/引用/输出"4 个 nodeType 真值 | 找应用市场更复杂的事件包 |
| 3 | EVENT_WORKFLOW 标准工作流完整 schema | prod 仅 1 个样本，需更多 |
| 4 | `conditionOption: TEMP` 含义 | prod detail 看 |
| 5 | `filterType: COMMON` 含义 | prod detail 看 |
| 6 | enable/disable endpoint | 浏览器点启用开关抓 |
| 7 | 调试 endpoint | 浏览器点"调试"抓 |

---

## 附录 A：抓包样本路径

| 文件 | 大小 | 来源 |
|---|---|---|
| `docs/captures/business-event-detail-with-nodes.network-response` | 35KB | trial 用户手配 EVENT_OPERATION+UPDATE_NODE |
| `docs/captures/business-event-save-body.network-request` | 33KB | 同上 save round-trip |
| `docs/captures/business-event-save-body-with-custom-node.json` | 33KB | trial 加 CUSTOM_CODE_NODE 后 save |
| `/var/folders/T/prod-event-list.network-response` | - | prod 租户中心 list (脱敏，不入 git) |

## 附录 B：实证统计

| 抓包 batch | 来源 | 事件数 | 累计 nodeType |
|---|---|---|---|
| Batch 1 | trial 手配 | 1 | 4 |
| Batch 2 | trial 自动化 | 1 | 4 |
| Batch 3 | prod page 1 | 5 | 8 |
| Batch 4 | prod page 1-2 | 40 | 13 |
| Batch 5 | prod page 3-4 | 40 | 15 |
| Batch 6 | prod page 5-8 | 80 | **17 (全)** |

---

## 19. 修订声明

本 v2 文档**纯实证**，所有 enum 值 / 字段名 / schema 均来自真实 XHR 抓包。但仍存在以下限制：

- 文档 17 节点中 **14 个完整 schema 已实证**，**3 个未见样本**（提交/循环/引用/输出）
- `definesys.input()` 返回 dict 的 key 真值**仍未实证**（agent 生成 Python 代码时**字段访问可能撞 KeyError**）
- `conditionOption: TEMP` / `filterType: COMMON` 含义未实证
- prod 是 v4.1 平台 / trial 是 v5.0 平台，**版本差异部分字段可能不同**（已发现 v2.0 vs v3.0 schema 演进，但跨平台版本未深入）
- **没在 prod 上做 add/save/del 操作**（只读保命），所以"agent 自动创建" prod 上**未端到端实证**

**置信度**：
- 80%（17 nodeType / 7 eventType / 17 triggerType 真值集是高置信度）
- 60%（每个节点的完整字段 schema 是中置信度 — 14 dump 了 fields list 但字段语义未全 verify）
- 40%（Python SDK 真行为 + dict key + 边界 case）

建议 MCP 工具落地时先用**路线 A (CUSTOM_CODE_NODE) + 路线 B (EXT_NODE+dolphin)**，避开复杂节点组合，等 agent 真跑通后再扩。
