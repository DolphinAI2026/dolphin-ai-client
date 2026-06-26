"""幂等 upsert 平台知识库 seed 文档。按 slug upsert,可重复跑。

SEED 内容来自 docs/knowledge-seed-inventory-2026-06-26.md 标「可搬」的 6 条 +
definesys 写侧 SDK 1 条占位(status='draft',仓库内无权威来源)。
prompt 留薄(防漂移)步骤已推迟,本模块仅做 seed,不改任何 prompt 文件。
"""
from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.knowledge_doc import KnowledgeDoc

# ---------------------------------------------------------------------------
# C1: df-sdk API 速查（全局 window.df）
# 出处: backend/app/coding/default_rules/前端SDK-v2介绍.mdc + prompts.py:42-49
# ---------------------------------------------------------------------------
_C1_DF_SDK = """\
## df-sdk — 得帆 aPaaS 平台自开发全局 SDK（window.df）

df-sdk 封装在 `window.df` 中，在 aPaaS 自开发场景（自开发页面/组件/业务事件自定义弹窗/自定义节点/列表虚拟字段）下均可直接调用。**不可在 aPaaS 系统外使用。**

### 基础方法

| 方法 | 说明 |
|---|---|
| `df.getVue()` | 获取系统 Vue 实例 |
| `df.getRouter()` | 获取系统路由（支持 `.push()` / `.beforeEach()` 等 Vue Router API） |
| `df.getStore()` | 获取 Vuex store（`state.authModule.userInfo` 等） |
| `df.getEnv()` | 获取环境变量（如 `VUE_APP_BASE_DOMAIN`） |
| `df.getAppEnv()` | 获取应用级环境变量（**仅应用可用，平台不可用**） |
| `df.getI18n()` | 获取国际化对象，支持 `.t(key)` / `._t(key, locale, messages)` |
| `df.showToast({message, type, duration})` | 在当前页面顶部弹出提示框，type 可选 'success'/'error'/'warning' |
| `df.previewImage({imgUrlList})` | 预览图片 |
| `df.getTimezoneDate()` | 获取当前时区时间（**仅应用可用**） |

### 网络请求

```javascript
// 标准请求方式 — 返回的不是 Promise，不能用 .then/.catch
this.$request({
    url: 'xdap-app/plugin/query/list',
    method: 'get',
    params: { ... }
}).asyncThen((resp) => {
    // 成功
}, (err) => {
    // 业务错误
}).asyncErrorCatch((err) => {
    // 网络错误
})

// 也可用 Promise 版本
df.requestWithPromise({ url, method, params, headers, timeout }).asyncThen(...)
```

**注意：网络请求用 `this.$request` 或 `df.requestWithPromise`，不是原生 `fetch` / `axios`，返回对象需用 `.asyncThen()` / `.asyncErrorCatch()`，不支持 `.then()` / `.catch()`。**

### 页面（仅 Web 应用）

| 方法 | 说明 |
|---|---|
| `df.page.openFormModal({formInfo, hook})` | 打开表单新增/编辑弹窗（formId + 可选 documentId） |
| `df.page.openFormListModal({formInfo})` | 以列表弹窗形式打开另一表单，支持过滤参数映射 |
| `df.page.openFormDrawer({formInfo})` | 打开表单详情抽屉 |
| `df.page.openGlobalModal({title, message, okConfig, cancelConfig, closeConfig})` | 打开自定义弹窗（平台 + Web 应用可用） |
| `df.page.closeGlobalModal()` | 关闭自定义弹窗 |

### 附件上传

```javascript
df.uploadWithPromise({ params: formData, headers, timeout })
    .asyncThen((resp) => { ... })
    .asyncErrorCatch((err) => { ... })
```
查看已上传附件 URL 需拼接 tenant_id + token 的 Base64 编码。

### iframe 消息通信（仅 Web/移动端应用）

| 方法 | 说明 |
|---|---|
| `df.postMessage.registerPostMessage({postMessageCode, postMessageMethod})` | 注册消息监听 |
| `df.postMessage.initPostMessage({postMessageKey})` | 创建消息通信 |
| `df.postMessage.destroyPostMessage({postMessageKey})` | 销毁消息通信 |
| `df.postMessage.getPostMessage()` | 获取所有已注册消息通信 |

### 移动端专属（df.thirdApi）

| 方法 | 说明 |
|---|---|
| `df.thirdApi.getPlatformType()` | 获取第三方平台类型（weCome/feishu/third） |
| `df.thirdApi.registerThirdAPIList(apiList)` | 注册自定义 API（替换系统默认实现） |
| `df.thirdApi.invokeThirdApi({functionName, arguments, callback})` | 调用已注册的 API |
| `df.thirdApi.scanQRCodeWithPromise()` | 扫码（返回 Promise） |
| `df.thirdApi.getLocationWithPromise({showMessage, appId})` | 获取定位（返回 Promise） |
"""

# ---------------------------------------------------------------------------
# C2: formValue 存储规范
# 出处: backend/app/agents/coding/prompts.py:341-348 _SHARED_FORMVALUE_STORAGE_SECTION
# ---------------------------------------------------------------------------
_C2_FORMVALUE = """\
## formValue 存储规范（★ 必须遵守，否则数据无法入库）

平台通过 `formValue` 将组件数据持久化到数据库。

### 核心规则

1. 组件值改变后**必须**同步写入 `this.formValue`。
2. 组件内部 UI 状态可用 `data()` 维护，但**业务值变化**时必须同步到 formValue。
3. `formValue` 只接受基本数据类型：`string`、`number`、`boolean`、`null`。
4. 对象/数组等复杂类型**必须**先 `JSON.stringify()` 序列化再赋值，读取时用 `JSON.parse()` 反序列化。

### 推荐模式

```javascript
mounted() {
    if (this.formValue) {
        try {
            this.innerValue = JSON.parse(this.formValue)
        } catch(e) {}
    }
},
methods: {
    handleChange(val) {
        this.innerValue = val
        this.formValue = JSON.stringify(val)  // 序列化写回
    }
}
```
"""

# ---------------------------------------------------------------------------
# C3: formEngine API 白名单
# 出处: backend/app/agents/coding/prompts.py:350-392 _SHARED_FORMENGINE_API_SECTION
# ---------------------------------------------------------------------------
_C3_FORMENGINE = """\
## formEngine API 白名单（★ 极严格，违反会运行时崩溃）

在写任何 `this.formEngine.xxx` 代码前，**必须确认该属性/方法在以下白名单中**。白名单外的一切 `formEngine.xxx(...)` 方法调用都是 LLM 臆想，不存在。

### 允许的只读属性

| 属性路径 | 说明 |
|---|---|
| `formEngine.engineContext.instance.documentId` | 当前文档 ID |
| `formEngine.engineContext.instance.instanceId` | 当前表单实例 ID |
| `formEngine.formDataControl.allTileFormItemList` | 所有表单字段配置数组 |
| `formEngine.formDataControl.componentMap` | uuid → 组件配置 Map（用 `.get(uuid)` 访问） |
| `formEngine.formDataControl.ctlComponentMap` | 表单控件实例 Map |
| `formEngine.formRef` | 表单 ref 引用 |

### 允许调用的方法

| 方法 | 说明 |
|---|---|
| `formEngine.formRef.validateField(propKey, callback)` | 触发单字段校验 |
| `formEngine.bsEventControl.triggerEventValueChange(widget, event)` | 触发业务事件 |

### 允许写的状态标记

- `formEngine.formDataControl.ctlFormDataChanged = true` — 标记表单数据已变更（赋值**后**请确保 `this.formData` 已通过 `$set` 更新）

### 严禁臆想的方法（下列方法根本不存在，调用会报 `is not a function`）

| 错误调用 | 正确替代 |
|---|---|
| `formEngine.setWidgetValue(uuid, val)` | `this.$set(this.formData, uuid, val)` |
| `formEngine.setFieldValue(...)` / `setFormValue(...)` | 同上 |
| `formEngine.updateWidgetConfig(...)` | setting.vue 里用 `v-model="customComponentConfig.xxx"` 双向绑定 |
| `formEngine.updateCustomComponentConfig(...)` | 同上 |
| `formEngine.updateWidgetCustomConfig(...)` | 同上 |
| `formEngine.updateSpecialConfig(...)` | 同上 |
| `formEngine.setWidgetInfo(...)` | 同上 |
| `formEngine.saveConfig(...)` / `submitConfig(...)` / `applyConfig(...)` | 不存在，无需调用 |
| `formEngine.getFieldByCode(...)` / `getComponentByCode(...)` | 用 `allTileFormItemList.find(c => c.code === 'xxx')` |

### 铁律

1. 写 `this.formEngine.xxx(...)` 前，先确认 xxx 在上方"允许调用的方法"中；不在就**不要写**。
2. 给其他字段赋值**唯一正确方式**：`this.$set(this.formData, targetUuid, value)` + 可选 `this.formEngine.formDataControl.ctlFormDataChanged = true`。
3. 修改自身组件配置**唯一正确方式**：setting.vue 里 `v-model="customComponentConfig.xxx"`。
4. 不确定某 API 是否存在 → **宁可不写，不要猜**。
"""

# ---------------------------------------------------------------------------
# C4: 后端接口路径/包名约定
# 出处: pipeline.py:824-875 _BRAINSTORM_PROMPT_BACKEND_API + workspace.py:4869
# （只搬路径/包名/Maven 源约定；SPEC 输出模板留代码）
# ---------------------------------------------------------------------------
_C4_BACKEND = """\
## aPaaS 后端自开发接口约定（SpringBoot Java）

### 接口路径约定

- 所有自开发接口路径以 **`/custom`** 开头（例：`/custom/battery/list`）。
- 请求方式：GET 或 POST（无 PUT/DELETE）。

### 包名约定

- 顶层包名：**`com.xdap`**（例：`com.xdap.battery`）。
- 主类需扫描两个包：`com.definesys.mpaas`（平台框架包）和 `com.xdap.*`（业务代码）。

```java
@SpringBootApplication
@EnableFeignClients
@ComponentScan({"com.definesys.mpaas", "com.xdap.*"})
public class Application {
    public static void main(String[] args) {
        SpringApplication.run(Application.class, args);
    }
}
```

### Maven 私有源

得帆私有 Maven 仓库（必须配置，否则平台框架依赖 404）：

```xml
<repository>
    <id>dfy-maven</id>
    <url>https://registry.dfy.definesys.cn/repository/maven-public/</url>
</repository>
```
"""

# ---------------------------------------------------------------------------
# C5: 前端技术栈约定
# 出处: prompts.py:35-49 AGENT_SYSTEM_PROMPT §通用技术规范 + workspace.py:407
# ---------------------------------------------------------------------------
_C5_FRONTEND = """\
## aPaaS 前端自开发技术栈约定

### 基础框架

- **Vue 2.7**（不是 Vue 3）。
- **Element UI** 已在宿主容器中**全局注册**，不需要 import（PC 端场景）。
- 日期处理：`this.$dayjs`（不引入 moment/dayjs npm 包）。
- 工具函数：`this.$lodash`（已全局挂载）。

### 调试输出

`console.log` 会在生产构建中被剥离 — **所有调试输出统一使用 `console.info`**。

### 私有 npm 源

得帆私有 npm 源（`@x-apaas/*` scoped 包及代理公共包）：
```
https://registry.dfy.definesys.cn/repository/apaas-npm-group/
```
平台脚手架包 `@x-apaas/df-apaas-cli` **只发布在此私有源**，公共源（npmmirror/npmjs）会 404。必须用 scoped 包名（裸名 `df-apaas-cli` 在任何源都 404）。

### 请求方式

使用 `this.$request({url, method, params})` 而不是 axios/fetch，返回对象使用 `.asyncThen()` / `.asyncErrorCatch()`，不支持 Promise `.then()` / `.catch()`。
"""

# ---------------------------------------------------------------------------
# C6: definesys Python 读侧契约（status=published）
# 出处: docs/research-apaas-event-python-spec-2026-06-05.md §1-§2
# 写侧 SDK 仓库内无权威来源，独立建 draft 占位（见 SEED 末条）
# ---------------------------------------------------------------------------
_C6_PYTHON_READ = """\
## aPaaS 业务事件自定义节点 Python 契约（读侧）

> 来源：apaas-trial 后台「AI 管理 → 提示词管理」81 条平台内置 prompt 中的「Python代码生成」规范（2026-06-05 实证）。
> **写侧 SDK（definesys.create/update）在平台 AI prompt 库和帮助文档中均未找到，见独立 draft 文档 `平台规范/apaas-event-python-write-sdk`。**

### invoke 契约（骨架）

```python
import os
# os.system("pip2 install requests")

def invoke():
    # 获取数据来源节点全部数据
    output = definesys.input()

    # 在这里进行数据处理
    # 处理完成后把处理结果 return 出去
    return output
```

- 入口函数名必须是 **`invoke`**（无参数）。
- 用 **`definesys.input()`** 拿上游数据，**不是** `get_trigger_data()` / `getInput()` 等（这些不存在）。
- 返回值必须是**合法 JSON 对象**（无注释）。

### 数据结构规范（afterFormData / afterTableData，by uuid）

`definesys.input()` 返回 `customNodeData`，它是一个**数组**（一般取第一条 `[0]`，过滤/统计时用多条）：

```python
output = definesys.input()
node_data = output[0]  # 通常取第一条

# 主表字段（非 FORM_WIDGET_SON_TABLE 组件）— key 是组件 uuid，不是字段 code！
main_field_value = node_data['afterFormData']['<component_uuid>']

# 子表（FORM_WIDGET_SON_TABLE 组件）— 同样以组件 uuid 为 key
son_table_rows = node_data['afterTableData']['<son_table_component_uuid>']
```

**关键**：
- 字段 key 是组件的 **uuid**（不是 code / label / 字段名）。
- 主表字段在 `afterFormData`，子表在 `afterTableData`，两者都挂在 `customNodeData[i]` 下。
- 要写出能跑的 Python，**必须先拿到触发表单每个字段的 component uuid + 组件类型**（可用 `list_apaas_form_components(env_id, apaas_app_id, form_id)` 工具获取）。

### 常见组件类型数据示例

- **Person**（人员）：`{ account, id, phone, username, email?, managerId? }`
- **Department**（部门）：`{ id, name, departmentCode, structureCode, structureName, leafNodeFlag }`
- **Select**（下拉/单选）：`{ checked, color, id, label, ... }`
- 可选属性需判空再访问。

### 返回格式

```python
return {"result_field": "value", ...}  # 必须是合法 JSON，无注释
```

### 注意事项

- 平台 AI（海豚AI）自身也只用 `definesys.input()` → 处理 → `return` 范式，**不使用写 SDK**。
- 「写其他模型/更新记录」建议用下游节点（ASSIGNMENT_NODE 赋值节点 / UPDATE_NODE / 新增数据节点），而非在 Python 里直接写库。
"""

# ---------------------------------------------------------------------------
# 写侧 SDK 占位（status=draft）
# ---------------------------------------------------------------------------
_C6_WRITE_DRAFT = """\
> 占位文档（status=draft），尚未收录 definesys Python 写侧 SDK 权威文档。

## 待补充：definesys Python 写侧 SDK

调研结论（2026-06-05）：
- 平台 AI prompt 库（81 条）**只出现 `definesys.input()`**（读），无任何 `definesys.create/update/save/query/dao` 等写方法。
- apaas 自定义节点编辑器、帮助文档均未暴露写 SDK API 列表。
- 平台推荐的「写」方式是使用下游节点（ASSIGNMENT_NODE / UPDATE_NODE / 新增数据节点）。

**何时转 published**：用户提供 definesys Python SDK 的写 API 文档（方法签名 + 示例）后，更新此文档并改 status=published。

参考已知读侧规范：`平台规范/apaas-event-python-read-contract`
"""

# ---------------------------------------------------------------------------
# SEED 列表
# ---------------------------------------------------------------------------
SEED: list[dict] = [
    {
        "slug": "platform/df-sdk-api",
        "title": "df-sdk API 速查（全局 window.df）",
        "summary": "得帆 aPaaS 平台自开发全局 SDK，含 getVue/getRouter/getStore/getEnv/$request/openFormModal/showToast 等完整 API",
        "category": "平台规范",
        "body_md": _C1_DF_SDK,
        "status": "published",
    },
    {
        "slug": "二次开发/form-component-formvalue-storage",
        "title": "formValue 存储规范",
        "summary": "自开发组件值必须同步到 formValue 才能入库；复杂类型须 JSON.stringify/parse；推荐 mounted+handleChange 模式",
        "category": "二次开发",
        "body_md": _C2_FORMVALUE,
        "status": "published",
    },
    {
        "slug": "二次开发/form-engine-api-whitelist",
        "title": "formEngine API 白名单",
        "summary": "formEngine 合法属性/方法白名单及臆想方法黑名单（违反会运行时崩溃）；正确赋值用 this.$set(this.formData, uuid, val)",
        "category": "二次开发",
        "body_md": _C3_FORMENGINE,
        "status": "published",
    },
    {
        "slug": "二次开发/backend-api-conventions",
        "title": "后端自开发接口约定（SpringBoot）",
        "summary": "接口路径以 /custom 开头；包名 com.xdap；@ComponentScan 扫 com.definesys.mpaas + com.xdap.*；得帆私有 Maven 源",
        "category": "二次开发",
        "body_md": _C4_BACKEND,
        "status": "published",
    },
    {
        "slug": "二次开发/frontend-tech-stack",
        "title": "前端自开发技术栈约定",
        "summary": "Vue 2.7；Element UI 全局注册无需 import；$dayjs/$lodash；console.info 代替 console.log；得帆私有 npm 源",
        "category": "二次开发",
        "body_md": _C5_FRONTEND,
        "status": "published",
    },
    {
        "slug": "平台规范/apaas-event-python-read-contract",
        "title": "aPaaS 业务事件 Python 自定义节点——读侧契约",
        "summary": "invoke() 入口 + definesys.input() 取 customNodeData[0][afterFormData/afterTableData][<uuid>]；返回合法 JSON",
        "category": "平台规范",
        "body_md": _C6_PYTHON_READ,
        "status": "published",
    },
    {
        "slug": "平台规范/apaas-event-python-write-sdk",
        "title": "definesys Python 自定义节点——写侧 SDK（待补充）",
        "summary": "（占位 draft）definesys 写 SDK API（create/update 等）在平台 AI prompt 库和文档中均未找到，待用户提供权威文档后补充",
        "category": "平台规范",
        "body_md": _C6_WRITE_DRAFT,
        "status": "draft",
    },
]


async def upsert_seed_docs(db: AsyncSession) -> int:
    """幂等 upsert SEED 文档。按 slug 更新或插入，返回处理条数。"""
    n = 0
    for item in SEED:
        existing = (
            await db.execute(select(KnowledgeDoc).where(KnowledgeDoc.slug == item["slug"]))
        ).scalar_one_or_none()
        if existing:
            for k, v in item.items():
                setattr(existing, k, v)
            existing.tenant_id = None
        else:
            db.add(KnowledgeDoc(**item, tenant_id=None))
        n += 1
    await db.commit()
    return n
