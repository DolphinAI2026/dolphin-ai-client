"""CodingAgent 使用的 prompt 构造逻辑。

从 backend/app/coding/vibe_agent.py 迁移过来的：
- 5 个 _SHARED_*_SECTION 常量
- 7 个项目类型的 workflow 段
- build_user_prompt() 构造函数

Stage 4 清理 VibeCodingAgent 后，这里成为 CodingAgent 的唯一 prompt 源。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


# ══════════════════════════════════════════════════════════════
# 跨场景共享的 prompt 段
# ══════════════════════════════════════════════════════════════

_SHARED_WIDGET_CONFIG_SECTION = """
## widget.config.json Requirements

### 🛑 生成方式铁则（防止 Pydantic 校验失败）

scaffold 已预置**完整合法**的 widget.config.json 作为模板（路径：
`__WIDGET_CONFIG_TEMPLATE_PATH__`）。模板里每个字段类型、取值都**已经是平台
要求的正确形式**（含 `version: 2.0`、`widget.display.mobileWidth: 12`、
`widget.editor.excludeInTable: ["WIDTH"]`、`client.mobile.widget.editor.excludeInTable` 等）。

**必做**：
1. 先 `read_file` 读这份模板
2. 用 `edit_file` **只修改需要变化的字段值**（`code` / `desc.text` / `desc.description` / `desc.icon` / `component.*` 组件名 / `client.mobile.component.*` / `widget.special.*` / `componentModelField` / `widget.editor.config` 末尾追加 `_SETTING`）
3. **保留**所有其他字段的结构和类型不变
4. **如果 `edit_file` 返回 `Error: old_string not found`**：立即重新 `read_file` 获取文件当前内容，再从当前内容中**逐字复制** old_string，不要凭记忆或之前读取的版本推断构造

**严禁**：
- 用 `write_file` 从零写 widget.config.json —— 从零写几乎必然漏字段或类型错，
  会被 Pydantic 校验拒绝（典型错误：`version — Input should be a valid number`、
  `widget.display.mobileWidth — Field required`、`client.mobile.widget.editor.excludeInTable — Field required`）
- 把 `version` 写成字符串（如 `"1.0.0"`、`"0.0.1"`）—— **必须是 number**（`2.0`）
- 省略 `mobileWidth` / `excludeInTable` / `client.mobile.widget.editor` 等看似可选但实际必填的字段

**如果工具返回 `Error: .../widget.config.json: ... — Field required` 或 `... — Input should be a valid ...`**：
立即 `edit_file` 把对应字段补上或改成正确类型，**不要放弃这个文件的生成**。

### ⚠️ 文件位置（按项目类型严格区分，违反会导致双份/错位）

__WIDGET_CONFIG_FILE_POSITIONS__

### 其他格式要求
- 纯 JSON 文件（不是 JS），以 `.json` 后缀结尾。
- Top-level structure MUST include: `version`, `code`, `desc`, `instance`, `component`, `widget`, `client`, `componentModelField`, `methods`, `formatValueSchema` — 缺少任何一个平台会崩溃。
- `code`: MUST start with `FORM_CUSTOM_` followed by a semantic uppercase string (e.g. `FORM_CUSTOM_DATA_SELECT`). Must match `apaas.json` `code` field.
- `desc.iconType`: fixed value `"DEFAULT"`.
- `desc.icon`: MUST be a real SVG string semantically matching the component (e.g. `"<svg xmlns=\\"http://www.w3.org/2000/svg\\" viewBox=\\"0 0 24 24\\">...</svg>"`). Never use an icon class string.
- **CRITICAL**: `desc.text`、`desc.description`、`widget.display.label` 必须根据**当前需求**填写真实的中文名称和描述，绝对禁止出现 "Demo"、"demo"、"Demo组件"、"Demo组件描述"、"Custom"、"custom"、"Component"、"自定义组件"、"通用组件" 等**占位/通用词**作为组件名称。例如国际手机号组件应填写 `"text": "国际手机号"`；日期时间段组件应填写 `"text": "日期时间段"`。
- **CRITICAL 命名铁则**: 组件的 kebab-case 英文名（用于 `code` 派生和所有文件命名）**必须反映组件核心功能**，从用户需求中提炼语义短语。**严禁**使用以下通用/占位词作为组件英文名：`custom` / `demo` / `component` / `custom-dev` / `form-component` / `custom-component`。示例：
  - 需求"日期时间段选择组件" → kebab-case 名 `date-time-range` → `code: "FORM_CUSTOM_DATE_TIME_RANGE"` → 文件名 `form-component-date-time-range-edit.vue`
  - 需求"星级评分" → `star-rating` → `FORM_CUSTOM_STAR_RATING` → `form-component-star-rating-edit.vue`
  - 需求"颜色选择器" → `color-picker` → `FORM_CUSTOM_COLOR_PICKER` → `form-component-color-picker-edit.vue`

  如果用户给的需求抽象（如"自定义组件"），必须在 brainstorm 阶段反问具体功能后再确定名字，不允许直接用 custom 兜底。
- `instance`: fixed `{ "uuid": "$itemUuid", "inTable": false }`.
- `widget.display.width`: `3 | 6 | 12` (1/4 / 1/2 / full row). `mobileWidth`: `6 | 12`. `height: 1`. `hidden/readOnly/required/onlyCreateEdit`: all `false`.
- `widget.allow`: MUST include all 4 fields: `"calcRule": false`, `"useInTableColumn": <boolean>`, `"scanCode": false`, `"copy": false`. `useInTableColumn` should be `true` by default unless sub-table usage is explicitly not needed.
- `widget.default`: `{ "customDefaultKey": "defaultValue", "value": null }` — value is `null`, NOT `""`.
- `widget.validator`: `{ "uniqueCheck": false }`.
- `widget.special`: MUST include 3 fields: `frontBusinessObjectComponentType`, `saveWithHidden: false`, `customComponentConfig`. **`customComponentConfig` must contain the default values for ALL config properties defined in `setting.vue`** (e.g. `{"defaultCountryCode": "CN", "placeholder": "", "clearable": true}`). Use `{}` only when there is no setting panel. Do NOT use empty strings as defaults for string fields — use `null` or a sensible default instead.
- `widget.special.frontBusinessObjectComponentType` 和 `componentModelField` 按 formValue 存储格式选，**必须严格按下表**（最容易踩的坑是"日期范围/时间段"组件被误判为 DATE，实际要用 STRING/BOF_TEXT）：

| formValue 形态 | componentModelField | frontBusinessObjectComponentType |
|---|---|---|
| 单个短字符串（< 500 字符） | `["STRING"]` | `"BOF_TEXT"` |
| 长字符串、富文本、base64（≥ 500 字符） | `["BIG_TEXT"]` | `"BOF_TEXT"` |
| 纯数字（如 `42`、`3.14`） | `["NUM"]` | `"BOF_NUMBER"` |
| **单个日期**（如 `"2024-01-01"` 或 `"2024-01-01 10:00:00"`，**单一字符串**） | `["DATE"]` | `"BOF_DATE"` |
| **日期范围 / 时间段 / JSON 数组 / 序列化对象**（如 `["2024-01-01", "2024-01-02"]` 或 `'{"start":"...","end":"..."}'`） | `["STRING"]`（< 500 字符）或 `["BIG_TEXT"]`（≥ 500 字符） | `"BOF_TEXT"` |

**铁则**：`DATE` / `BOF_DATE` **只适用于"单一日期字符串"**。任何 JSON 数组、序列化对象、多字段组合值**一律**按字符串存储（`STRING`/`BIG_TEXT` + `BOF_TEXT`）。日期**范围**类组件（日期段、日期时间段、时间段）属于 JSON 数组，不是 DATE。
- `widget.editor.config`: array starting with `["INFO","LABEL","FIELD_CODE","TITLE_DESCRIPTION","WIDTH","HIDDEN","READONLY","REQUIRED","EDITONNEW","UNIQUE","HIDDEN_SAVE","HIDDEN_TRIGGER","TRIGGER_BUSINESS_EVENTS"]`. **CRITICAL**: if a custom setting panel exists, the editor.config.json `code` (= widget code + `_SETTING`) MUST be appended at the **end** of this array. `FORMULA_RULE` only if needed. `excludeInTable` must be `["WIDTH"]` ONLY — do not add other values.
- `client.mobile.widget.editor.config`: same structure as `widget.editor.config`.
- `client.mobile.component`: required fields `edit`, `read`, `ide`; optional `list`, `association`, `lov`, `tableColumn`. Names should be `Mobile` + PC component name convention.
- `component` (PC): required `ide`, `edit`, `read`; optional `list`, `association`, `lov`, `print`, `search`, `searchIde`.
"""

_SHARED_EDITOR_CONFIG_SECTION = """
## editor.config.json Requirements
- **文件格式**: 生成 `{name}.editor.config.json`（纯 JSON，不是 JS 文件），路径为 `__BASE_PATH__/form-component-config/form-editor/{name}.editor.config.json`。**不要**生成 `.editor.config.js`。
- **⚠️ 此文件只有 4 个字段**，不能放任何其他内容（禁止 `editorConfigList`、`options`、`staticData`、`type`、`group` 等）：
  ```json
  {
    "code": "FORM_CUSTOM_RATE_SETTING",
    "editorConfigType": "FORM_CUSTOM_RATE_SETTING",
    "componentName": "FormComponentRateSetting",
    "configProperty": "customComponentConfig"
  }
  ```
- `code` = widget.config.json 的顶层 `code` + `_SETTING`（例如 widget `code` 为 `FORM_CUSTOM_RATE` 则此处为 `FORM_CUSTOM_RATE_SETTING`）。
- `editorConfigType`：**与 `code` 完全相同的值**。
- `componentName`：必须与 `setting.vue` 中的 `name` 选项完全一致。
- `configProperty`：**固定值 `"customComponentConfig"`，不可修改**。
- **文件命名规范**：文件名必须语义化，使用 `{组件名}.editor.config.json`，例如 `form-component-rate.editor.config.json`，不得使用 `dev-edit.editor.config.json` 这类无意义名称。
- **注册**：必须同时更新 `__BASE_PATH__/form-component-config/form-editor/index.js`，添加 import 和注册。
"""

_SHARED_SETTING_VUE_SECTION = """
## setting.vue Rules

### ⚠️ 必须使用 scaffold 预置的 editor 原子组件（严禁用 Element UI 原生）

`__BASE_PATH__/form-component/form-editor/components/` 目录下 scaffold **已预置 6 个 editor 原子组件**（LLM 不要重新生成，直接 import 使用）：

- `form-custom-sechma-item.vue` — **仅在业务 editor 内部作为外壳容器使用**。**严禁**在 setting.vue 主体 template 里直接用：sechma-item 不提供 formValue 双向绑定，setting.vue 本体又没有 formValue，直用后写 `<el-date-picker v-model="formValue" />` 会掉进 phantom property，UI 正常但数据完全不存。
- `form-custom-input-editor.vue` — 单行输入（替代 `<el-input>`）
- `form-custom-select-editor.vue` — 下拉（替代 `<el-select>` + `<el-option>`，通过 `options` prop 传选项）
- `form-custom-textarea-editor.vue` — 多行输入（替代 `<el-input type="textarea">`）
- `form-custom-switch-editor.vue` — 开关（替代 `<el-switch>`）

还有 2 个字段赋值 editor，**严格按场景区分**：
- `form-custom-field-assign-editor.vue` — **主表字段赋值**（默认选它）。组件产出 1~N 个派生值，用户为每个派生值选一个**主表字段**接收。典型：时间差→数字字段、总分→数字字段、选中数据→多个主表字段回填。
- `form-custom-table-field-assign-editor.vue` — **子表字段赋值（仅子表场景）**。**只有**组件产出的是**"整个子表的多行数据"**、需要批量写到某个目标子表时才用。典型：从外部接口拉回一个表格（含多行），把这整张表映射到当前表单的某个子表。

**🔴 严禁误用 table 版**：如果派生值是"单一数值/字符串"（如时间差、合计金额、选中的 1 条记录），**必须用 form-custom-field-assign-editor**（主表版），**不要**因为组件本身"支持在子表中使用"就用 table 版——组件用在子表中 ≠ 赋值目标是子表。只有当 `otherFields`/源字段 componentType 是 `FORM_WIDGET_SON_TABLE` 时才用 table 版。

**⚠️ 任何"组件把派生值/选中值写给其他字段"的场景都必须用字段赋值 editor**（数据选择类回填 / 派生值输出 / 联动赋值），**严禁**靠 aPaaS 字段联动规则等外部机制。

**`otherFields` 是"组件作为赋值源能产出的字段列表"**（组件侧的**源字段**，不是表单里其他字段）。每个元素 `{uuid, label, componentType}`：
- `uuid`：组件内部逻辑 key（自行编造的业务语义 id，不是真实字段 uuid）
- `label`：中文展示名
- `componentType`：按派生值类型选——数字 `FORM_NUMBER_INPUT` / 字符串 `FORM_TEXT_INPUT` / 金额 `FORM_MONEY_INPUT` / 手机号 `FORM_PHONE_INPUT` / 邮箱 `FORM_EMAIL_INPUT` / 证件号 `FORM_IDCARD_INPUT`

示例（时间差组件）：
```vue
<form-custom-field-assign-editor
  label="时间差赋值" property="diffAssign" v-bind="$props"
  :otherFields="diffSourceFields"
></form-custom-field-assign-editor>
```
```js
computed: {
  diffSourceFields() {
    return [{ uuid: 'diff', label: '时间差', componentType: 'FORM_NUMBER_INPUT' }];
  },
}
```

`otherTableFields`（子表赋值）：第一级 `componentType` 必须是 `FORM_WIDGET_SON_TABLE`，`children` 每项按 componentType 映射表选。

edit.vue 消费赋值配置：从 `customComponentConfig.diffAssign` 里拿到 `[{origin, target}]`，按 target.uuid 写值：
```js
this.$set(this.formData, pair.target.uuid, diff);
this.formEngine.formDataControl.ctlFormDataChanged = true;
```

**完整示例和 otherTableFields 结构详见 `.cursor/rules/setting-vue.mdc`。**

## 🛑 自造业务 editor 的强制约定

预置原子无法满足时允许新建 `components/form-custom-{业务名}-editor.vue`，**必须**按以下铁则（否则"UI 正常但数据存不进去"静默 bug）：

1. **必须** `mixins: [EditorFormConfigMixin, FormEditorMixin]` —— `formValue` 由 FormEditorMixin 自动双向绑定到 `componentConfig[configProperty][property]`，**禁止**自己实现 computed getter/setter。
2. **禁止** `this.$parent[configProperty]` 读配置（错误 API）。
3. **禁止**重复声明 `label` / `property` / `help` / `showRequired` / `placeholder` props —— FormEditorMixin 已提供，只声明业务特有 props。
4. **必须**用 `<form-custom-sechma-item>` 包裹（透传 label/property/configProperty/showRequired/help/rules 6 个 prop）。
5. 值变化调 `handleChange`（FormEditorMixin 提供）或让 `v-model="formValue"` 自动触发。**禁止** `$emit('update:componentConfig', ...)`。
6. 参考 scaffold 里 `form-custom-input-editor.vue` / `form-custom-select-editor.vue` 的结构。

**🔴 setting.vue 中严禁直接使用下列 Element UI 原生组件**：
- `<el-form-item>` / `<el-form>` / `<el-input>` / `<el-select>` / `<el-option>`
- `<el-switch>` / `<el-radio>` / `<el-radio-group>` / `<el-checkbox>` / `<el-checkbox-group>`

遇到上述需求**必须**用对应的 `form-custom-*-editor` 原子替换。

### 🔴 import 路径铁则（路径写错直接构建失败，最高频错误）

setting.vue 与 `components/` 目录**同级**，都在 `form-editor/` 下：

```
form-editor/
  ├── {name}-setting.vue     ← 当前文件在这里
  └── components/
        ├── form-custom-input-editor.vue
        ├── form-custom-switch-editor.vue
        ├── form-custom-select-editor.vue
        └── form-custom-textarea-editor.vue
```

因此 import **必须**使用 `./components/`（当前目录的子目录），**严禁** `../components/`（父级路径）：

```js
// ✅ 正确
import FormCustomInputEditor from './components/form-custom-input-editor.vue';
// ❌ 错误 → Module not found: Can't resolve '../components/form-custom-input-editor.vue'
import FormCustomInputEditor from '../components/form-custom-input-editor.vue';
```

### 正确示例（模板即可复用）

```vue
<template>
  <div class="form-custom-{name}-setting">
    <form-custom-input-editor
      label="占位文本" property="placeholder" v-bind="$props"
      :help="['为空时的提示文字']"
    ></form-custom-input-editor>
    <form-custom-select-editor
      label="显示模式" property="mode" v-bind="$props"
      :options="modeOptions" :showRequired="true"
    ></form-custom-select-editor>
    <form-custom-switch-editor
      label="允许为空" property="nullable" v-bind="$props"
    ></form-custom-switch-editor>
  </div>
</template>

<script>
__EDITOR_MIXIN_IMPORT__
import FormCustomInputEditor from './components/form-custom-input-editor.vue';
import FormCustomSelectEditor from './components/form-custom-select-editor.vue';
import FormCustomSwitchEditor from './components/form-custom-switch-editor.vue';

export default {
  name: 'FormComponent{Name}Setting',  // 必须与 editor.config.json 的 componentName 一致（PascalCase）
  mixins: [EditorFormConfigMixin],
  components: { FormCustomInputEditor, FormCustomSelectEditor, FormCustomSwitchEditor },
  computed: {
    modeOptions() { return [{ value: 'a', label: 'A' }, { value: 'b', label: 'B' }]; },
  },
};
</script>
```

所有 editor 原子都约定同一组 props：`label`、`property`、`v-bind="$props"`（**必传**，透传 configProperty 给容器）；`showRequired` / `help`（字符串数组） / `placeholder` 可选；`form-custom-select-editor` 额外需要 `options`。

### 写入路径和校验规范
- setting.vue 通过 `componentConfig` prop 读取平台配置。editor 原子内部已封装 formValue 双向绑定到 `componentConfig.customComponentConfig[property]`，setting.vue 主体代码不需要手写读写逻辑。
- 如果业务必须写 `saveConfig()` / `handleChange()`，只能直接操作 `customComponentConfig.xxx`，严禁通过 `$emit('update:componentConfig', ...)` 或镜像状态回写
- 严禁调用不存在的配置写入 API：`formEngine.updateWidgetConfig(...)`、`formEngine.updateCustomComponentConfig(...)`、`formEngine.updateWidgetCustomConfig(...)`、`formEngine.updateSpecialConfig(...)`、`formEngine.setWidgetInfo(...)`
- 严禁在 setting.vue 中使用 `localConfig`、`formData`、`config` 这类镜像配置
- `inject` 声明必须带 `{ default: null }`
- 配置直接存 `customComponentConfig` 根级别，不要多嵌套（如 `{ chartConfig: { dataSource } }` 错，应为 `{ dataSource }`）
- 不要在 computed 里用 `$set`（会导致无限循环）
- formEngine 通过 prop 传入（不是 inject）
- **最外层容器不要设置 padding**，平台区域已做好布局，额外 padding 会压缩可用空间

### 文件路径
- `setting.vue` must be written to `__BASE_PATH__/form-component/form-editor/{name}-setting.vue`
- `editorConfigList` must be aggregated by `__BASE_PATH__/form-component-config/form-editor/index.js` from `./{name}.editor.config.json`

### ⚠️ Spec 驱动：is_custom_editor 和 validation 必须处理

CodingAgent 读 Spec 配置项表格时，以下两个字段必须响应：

**`is_custom` = 是（is_custom_editor=true）→ 先建业务 editor 文件，再在 setting.vue 使用**

Spec 中 `is_custom` 为"是"的配置项，其 `ui_editor` 值（如 `form-custom-color-editor`）不是预置组件，
必须**在同一批次**先 `write_file` 创建 `__BASE_PATH__/form-component/form-editor/components/{ui_editor}.vue`，
再在 setting.vue 里 import 并使用，严禁先写 setting.vue 后补建 editor（会触发 Module not found）。
业务 editor 必须遵守"🛑 自造业务 editor 的强制约定"章节的规则（mixin + sechma-item 包裹 + v-model=formValue）。

**`校验` 列不为 `—` → 在 editor 节点上添加 `:rules`**

根据 prop type 不同，`:rules` 写法如下：

```vue
<!-- type="number"，validation={min:3, max:10} -->
<form-custom-input-editor
  property="maxScore" v-bind="$props"
  :rules="[
    { pattern: /^[0-9]+$/, message: '请输入整数' },
    { validator: (rule, val, cb) => (Number(val) >= 3 && Number(val) <= 10 ? cb() : cb('请输入 3~10 之间的数字')) }
  ]"
></form-custom-input-editor>

<!-- type="string"，validation={max_length:50} -->
<form-custom-input-editor
  property="label" v-bind="$props"
  :rules="[{ max: 50, message: '不超过 50 个字符' }]"
></form-custom-input-editor>

<!-- type="string"，validation={pattern:"^#[0-9A-Fa-f]{3,6}$"} -->
<form-custom-input-editor
  property="activeColor" v-bind="$props"
  :rules="[{ pattern: /^#[0-9A-Fa-f]{3,6}$/, message: '请输入有效的 hex 颜色值' }]"
></form-custom-input-editor>

<!-- type="array"，validation={min_items:1, max_items:5} -->
<!-- array editor 通常有自己的校验，参考 editor 的 rules API -->
```

`校验` 列为 `—` 的配置项不需要加 `:rules`（但 `required=true` 的配置项需加 `{ required: true, message: '必填' }`）。

### ⚠️ setting.vue 完整注册清单（缺一不可，否则平台加载不到设置面板）

生成 `{name}-setting.vue` 后**必须同时完成以下两处注册**。只改其中一个是 half-register，平台看不到设置面板（用户点击属性面板空空如也）。

**注册 1**：`{name}.editor.config.json` → 追加到 `__BASE_PATH__/form-component-config/form-editor/index.js`
```js
import DemoEditorConfig from './{name}.editor.config.json'
const editorConfigList = [DemoEditorConfig]
export default editorConfigList
```

**注册 2**：`{name}-setting.vue` 本身 → 追加到 `__BASE_PATH__/form-component/form-editor/index.js`（⚠️ **最容易漏**）
```js
import FormComponentDemoSetting from './{name}-setting.vue'
const customFormEditorList = [FormComponentDemoSetting]
export default customFormEditorList
```

两个 index.js 的职责区分：
- `form-component-config/form-editor/index.js` = 平台注册的 JSON 清单（聚合 `.editor.config.json`），导出 `editorConfigList`
- `form-component/form-editor/index.js` = 实际的 Vue 组件清单（聚合 `.vue`），导出 `customFormEditorList`

### ⚠️ 配置项完整性（必须与 brainstorm 方案 1:1 对齐）

setting.vue 的配置项**必须严格对齐 brainstorm "设计方案确认"中"配置项"表格**——表格列了 N 条 property，setting.vue 就要有 N 个对应的 form-custom-*-editor 节点，**每条 property 都要在 setting.vue 里有独立的 editor 节点**。

**严禁**：
- 省略任何配置项（哪怕"看起来可以先跳过"或"实现起来复杂"都不允许）
- 修改 property 名（brainstorm 表格里叫 `defaultValue` 就必须叫这个，不能改名）
- 修改数据类型 / UI 渲染 editor 类型
- 合并多个配置项

**特别注意：brainstorm 里标了自造业务 editor（如 `form-custom-date-time-editor` 等非预置原子）的配置项**：
- 必须**先**按"🛑 自造业务 editor 的强制约定"小节新建该业务 editor 的 vue 文件（使用 `mixins: [EditorFormConfigMixin, FormEditorMixin]` + `<form-custom-sechma-item>` 包裹 + `v-model="formValue"`）
- **再**在 setting.vue 里 import 并使用这个业务 editor
- **严禁**因"这个 editor 比较麻烦，先跳过对应配置项"——如果 brainstorm 方案确定了这个配置项，它就是硬契约。你有义务同时新建业务 editor 并在 setting.vue 使用它。

**自检**：写完 setting.vue 和相关业务 editor 后，build 前逐条核对 brainstorm 配置项表格：
- 表格里每一行 property 名 → 在 setting.vue 里都能找到一个 `<form-custom-xxx-editor property="{同名}" ...>` 节点
- 表格里标了业务 editor 的行 → `components/form-custom-xxx-editor.vue` 真实存在

### 所有 7 个 scene 都必须完整实现（禁止 half-rename）
- 7 个 scene（edit / read / ide / list / print / search / search-ide）每个目录下的 `.vue` 文件都必须真实存在，对应 `index.js` 每一行 `import` 指向的文件都必须存在。
- **绝对禁止**出现"改了 index.js 的 import 路径但没建对应 vue"的 half-rename 状态——会导致 webpack 报 `Module not found` build 失败。
- 如果某个 scene 用不到，保持 scaffold 默认的 `form-component-demo-{scene}.vue` 原样（连带 index.js 也别改），不要半改。
- 7 个 scene 地位平等：不存在"edit 是主要，其他可简略"这样的优先级——每个 scene 都有独立 UI 职责，必须完整实现。
"""

_SHARED_FORMVALUE_STORAGE_SECTION = """
## formValue 存储规范（★ 必须遵守，否则数据无法入库）
- 组件值改变后必须同步写入 `this.formValue`，平台通过 formValue 将数据持久化到数据库
- 组件内部 UI 状态可以用 `data` 维护，但业务值变化时必须同步到 formValue
- formValue 只接受基本数据类型：`string`、`number`、`boolean`、`null`
- 对象、数组等复杂类型必须先 `JSON.stringify()` 序列化再赋值，读取时用 `JSON.parse()` 反序列化
- 推荐模式：`mounted() { if (this.formValue) try { this.innerValue = JSON.parse(this.formValue) } catch(e) {} }`，`handleChange(val) { this.innerValue = val; this.formValue = JSON.stringify(val) }`
"""

_SHARED_FORMENGINE_API_SECTION = """
## ⚠️ formEngine API 白名单（★ 极严格，违反会运行时崩溃）

**在写任何 `this.formEngine.xxx` 代码前，必须确认该属性/方法在以下白名单中。白名单外的一切 `formEngine.xxx(...)` 方法调用都是 LLM 臆想，不存在。**

### ✅ 允许的只读属性

- `formEngine.engineContext.instance.documentId` — 当前文档 ID
- `formEngine.engineContext.instance.instanceId` — 当前表单实例 ID
- `formEngine.formDataControl.allTileFormItemList` — 所有表单字段配置数组
- `formEngine.formDataControl.componentMap` — uuid → 组件配置 Map（用 `.get(uuid)` 访问）
- `formEngine.formDataControl.ctlComponentMap` — 表单控件实例 Map
- `formEngine.formRef` — 表单 ref 引用

### ✅ 允许调用的方法

- `formEngine.formRef.validateField(propKey, callback)` — 触发单字段校验
- `formEngine.bsEventControl.triggerEventValueChange(widget, event)` — 触发业务事件

### ✅ 允许写的状态标记

- `formEngine.formDataControl.ctlFormDataChanged = true` — 标记表单数据已变更（赋值**后**请确保 `this.formData` 已通过 `$set` 更新）

### ❌ 严禁臆想的方法（下列方法在 formEngine 上**根本不存在**，调用会直接报 `is not a function`）

| 臆想的错误调用 | 正确替代方案 |
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

**铁律**：
1. 写 `this.formEngine.xxx(...)` 前，先检查 xxx 是否在上方"允许调用的方法"中；不在就**不要写**
2. 给其他字段赋值**唯一正确方式**：`this.$set(this.formData, targetUuid, value)` + 可选 `this.formEngine.formDataControl.ctlFormDataChanged = true`
3. 修改自身组件配置**唯一正确方式**：setting.vue 里 `v-model="customComponentConfig.xxx"`
4. 如果你不确定某个 API 是否存在，**宁可不写，不要猜**
"""


def render_form_component_sections(base_path: str) -> str:
    """渲染 form-component 共享段。base_path 单端 `src`，双端 `web/src`。"""
    is_dual = base_path == "web/src"

    # 占位符 → 按项目类型渲染不同内容
    if is_dual:
        widget_config_template_path = "shared/widget.config.json"
        widget_config_file_positions = (
            "- 文件路径：**`shared/widget.config.json`**"
            "（两端共用**唯一一份**，scaffold 已预置，LLM **只修改内容不新建文件**）\n"
            "- **严禁**在 `web/src/form-component-config/form-widget/` 或"
            " `mobile/src/form-component-config/form-widget/` 下新建 `*.widget.config.json`\n"
            "- 两端的 `form-component-config/form-widget/index.js` scaffold 已"
            " `import XxxWidgetConfig from '@shared/widget.config.json'`，**保持原样不动**\n"
            '- 严禁出现"widget.config 在 shared/ 和 web/ 双写"的状态'
        )
        editor_mixin_import = "import EditorFormConfigMixin from '@shared/mixin/form-config.mixin';"
    else:
        widget_config_template_path = (
            "src/form-component-config/form-widget/form-component-demo.widget.config.json"
        )
        widget_config_file_positions = (
            "- 文件路径：`src/form-component-config/form-widget/{name}.widget.config.json`"
            "（每个组件独立一份）\n"
            "- 聚合文件 `src/form-component-config/form-widget/index.js`："
            "`import XxxWidgetConfig from './{name}.widget.config.json'`"
        )
        editor_mixin_import = "import EditorFormConfigMixin from '@/mixin/form-config.mixin';"

    def _render(text: str) -> str:
        return (
            text
            .replace("__BASE_PATH__", base_path)
            .replace("__WIDGET_CONFIG_TEMPLATE_PATH__", widget_config_template_path)
            .replace("__WIDGET_CONFIG_FILE_POSITIONS__", widget_config_file_positions)
            .replace("__EDITOR_MIXIN_IMPORT__", editor_mixin_import)
        )

    return (
        _render(_SHARED_WIDGET_CONFIG_SECTION)
        + _render(_SHARED_EDITOR_CONFIG_SECTION)
        + _render(_SHARED_SETTING_VUE_SECTION)
        + _SHARED_FORMVALUE_STORAGE_SECTION
        + _SHARED_FORMENGINE_API_SECTION
    )


# ══════════════════════════════════════════════════════════════
# 项目类型特定 workflow prompt 段
# ══════════════════════════════════════════════════════════════

_WORKFLOW_FORM_COMPONENT = """
## Workflow — IMPORTANT: Be efficient! Minimize tool calls.
0. **Before tool calls**: First write a short, user-facing progress note in Chinese (1-3 sentences) explaining what you understood and what you will do next.
1. **FIRST** (1 call): Use glob_files to see the project structure
2. **THEN** (1-3 calls max): If `.cursor/rules/*.mdc` exists, read those rule files first, then read ONLY the key implementation files you need (edit.vue and mixin). Do NOT read every file. **必读**：scaffold 默认的 `form-component-demo.widget.config.json` 和一份 `.editor.config.json`，作为后续 edit 的模板——这样能保证结构、字段类型都合法。
3. **IMMEDIATELY write code（一次性并行写多个）**: 严格 schema 的 JSON（widget.config.json 等）走 `edit_file` 改关键字段；新增业务文件才用 `write_file`。**无论 edit_file 还是 write_file 都必须批量并行**——一个 turn 同时发 7+ 个 tool_calls 把所有 mode vue / setting / index.js / widget.config.json 等一次性写/改完。**不要**对 widget.config.json 用 write_file 从零写（漏字段）；**也不要**一轮只 edit/write 一个文件（耗光 30 轮上限任务必失败）。
4. **Build 前一致性自检（必做）**: run build 前，用 glob 或 list_dir **逐个验证** 7 个 scene 目录 (`src/form-component/form-widget/{edit,read,ide,list,print,search,search-ide}/`) 下的 `index.js` 引用的每一个 `.vue` 文件是否都真实存在。只要有一个"index.js 引用了但 vue 不存在"，立即先补建/修正，不要先跑 build。
5. **THEN** run `npm run build` to check compilation
6. If errors, fix and rebuild. If success, report completion.

## CRITICAL Rules
- **🔴 Scene vue 读配置铁则（违反必致所有配置失效）**：edit/read/ide/list/print/search/search-ide 这 7 个 scene vue 里**必须用 `this.widget.customComponentConfig`** 读用户在 setting.vue 里配的参数。**严禁**写 `this.customComponentConfig`（组件本身没有这个属性，永远得到 `undefined`，`undefined || {}` 得到 `{}`，导致 displayFormat/allowedWeekdays 等所有配置都永远是默认值，用户配了等于白配）。
  - ❌ 错：`customConfig() { return this.customComponentConfig || {}; }`（拿到 {}）
  - ✅ 对：`customConfig() { return this.widget.customComponentConfig || {}; }`
  - 区别：**setting.vue 用 `this.componentConfig.customComponentConfig`**（EditorFormConfigMixin 提供 componentConfig prop）；**scene vue 用 `this.widget.customComponentConfig`**（FormWidgetMixin 提供 widget）。两种 mixin 挂载的属性名不同，混用会静默失效。
- **🔴 必须 parallel tool_calls，严禁一轮一个文件**：写代码阶段**每个 turn 必须一次发出 5+ 个并行 `write_file`/`edit_file` 调用**。这个组件通常需要写 20+ 个文件（7 个 scene vue + setting.vue + widget.config.json + editor.config.json + 多个 index.js），如果每轮只调 1 个 tool，30 轮上限会被消耗殆尽而组件还没写完，任务失败。
  - ❌ 反例（任务必失败）：`turn1: [write_file]` `turn2: [write_file]` `turn3: [write_file]` ... 每轮 1 个
  - ✅ 正例：`turn1: [write_file×7]`（所有 mode vue 一次性写完）`turn2: [edit_file×3, write_file×2]`（widget.config / editor.config / setting.vue / 两个 index.js）`turn3: [run_command]`（build）
  - 即使工具可能返回 Error，也要**并行发**——Error 后下一轮并行 edit_file 修复，而不是怕 Error 变成一轮一个
- **Progress notes are visible to the user**: keep them brief, concrete, and friendly. Do NOT dump hidden reasoning or long analysis.
- **DO NOT loop**: Never read the same file twice. Never read more than 3 files before writing code.
- **Write ALL files at once**: In a single turn, call write_file for edit.vue, read.vue, ide.vue, setting.vue etc. Do NOT write one file per turn.
- **When generating designer config**: update `src/form-component/form-editor/index.js` and `src/form-component-config/form-editor/index.js` in the same batch as `setting.vue` / `{name}.editor.config.json`.
- **index.js 与 vue 必须一致**: 修改任何 `index.js` 的 import 路径时，**必须**同步确保对应 vue 文件存在（新建或重命名）。不允许出现 "index.js 指向的文件不存在" 的 half-rename 状态。如不需要某个 scene，保持 scaffold 默认的 `form-component-demo-{scene}.vue` 原样，index.js 也别改。
- **工具返回 Error 必须修复，不是放弃信号**：write_file / edit_file / run_command 等工具返回字符串以 `Error:` 开头时（如 `Error: widget.config.json: version — Input should be a valid number`），**必须**立即用 edit_file 修正对应字段再次 write，直到该工具返回 `Successfully wrote ...` 或 `[exit code: 0]`。**严禁**因为连续 3~5 条工具 Error 就终止任务（不要在 LLM 响应里返回空 tool_calls，那会触发 agent 结束）；必须坚持修到成功或撞 30 轮上限。典型修复模式：`write_file A.json → Error: A.json: foo — Field required` → `edit_file A.json 补上 foo` → 再 `write_file` 验证。
- **Be decisive**: You are an expert. After reading the scaffold structure and 1-2 example files, you have enough context to write the component.
- **Maximum 8 turns total**: If you haven't written code by turn 4, something is wrong. Write the code NOW.
- **NEVER use `<el-dialog>` inside form widgets** — it breaks FormEngine component resolution and crashes the platform with `Cannot read properties of undefined (reading 'edit')`. Use `<el-popover :append-to-body="true">` instead for any preview/popup interaction.

## Technical Constraints
- aPaaS form component with 7 render scenes (edit/read/ide/list/print/search/search-ide)
- Scaffold files already exist. Do NOT modify vue.config.js or babel.config.js. Avoid unrelated index.js changes, but you may update `src/form-component/form-editor/index.js` and `src/form-component-config/form-editor/index.js` when adding `setting.vue` / `editor.config.json`.
- Vue 2.7 + Element UI (globally registered, do NOT import Element UI)
- **console.log is stripped in production — use `console.info` for ALL debug output in every mode.**
- **formEngine is NOT available in `beforeCreate()` — only access `this.formEngine` from `created()` or later.**

## 🛑 目录结构铁则（绝对不要违反）

所有 7 个 scene 的 vue 文件**只能放在下列唯一目录下**：

```
src/form-component/form-widget/
├── edit/       ← form-component-{name}-edit.vue
├── read/       ← form-component-{name}-read.vue
├── ide/        ← form-component-{name}-ide.vue
├── list/       ← form-component-{name}-list.vue
├── print/      ← form-component-{name}-print.vue
├── search/     ← form-component-{name}-search.vue
└── search-ide/ ← form-component-{name}-search-ide.vue
```

**禁止**创建以下目录（常见幻觉，scaffold **不存在**）：
- ❌ `src/form-component/list-widget/`
- ❌ `src/form-component/print-widget/`
- ❌ `src/form-component/search-widget/`
- ❌ `src/form-component/search-ide-widget/`
- ❌ `src/form-component/edit-widget/`

注意：mixin 文件名（如 `list-widget.mixin.js`、`search-widget.mixin.js`）**只是文件名**，**不是目录名**。list/search/print/search-ide 的 vue 都在 `form-widget/{mode}/` 下。

## Mixin Per Mode (always use default import, never named import)
- edit / ide / read → `import FormWidgetMixin from '@/mixin/form-widget.mixin'`
- list            → `import ListWidgetMixin from '@/mixin/list-widget.mixin'` （仅是 mixin 文件名，不要据此创建 list-widget/ 目录）
- print           → `import PrintWidgetMixin from '@/mixin/print-widget.mixin'`
- search          → `import SearchWidgetMixin from '@/mixin/search-widget.mixin'`
- search-ide      → `import SearchIdeWidgetMixin from '@/mixin/search-ide-widget.mixin'`
- editor (setting.vue) → `import EditorFormConfigMixin from '@/mixin/form-config.mixin'`

## Mode-specific Rules
- **List mode**: config = `this.componentConfig` (NOT `this.widget`); `this.formValue` is the concrete value prop directly (no propKey indexing); NO `<x-proxy-form-item>` wrapper.
- **Print mode**: NO `<el-xxx>` tags — Element UI does not render in print context; NO `<x-proxy-form-item>`; pure HTML/CSS only; use structure `div.print-item > div.print-item-title + div.print-item-value`; when `widget.isInTable` is true, omit the title.
- **Search mode**: NO `<x-proxy-form-item>`; submit via `this.$emit('change', [value])` — value MUST be wrapped in an array; do NOT use formValue setter.
- **Search-IDE mode**: NO `<x-proxy-form-item>`; all inputs `disabled`; only implement when Search mode is also implemented.
- **IDE mode**: all inputs must be `disabled` — IDE renders in the form designer canvas where user interaction is not allowed.
- **Edit mode**: check `this.widget.readOnly`; guard formValue undefined with fallback; never use both `v-model` and `@input` on the same element (causes infinite loop).

## BOF Type & formValue
- BOF_NUMBER caveat: `formValue` may arrive as a string from the platform. Always guard: `const n = Number(this.formValue); if (isNaN(n)) { /* fallback */ }`.
"""


_WORKFLOW_FORM_COMPONENT_DUAL = """
## Workflow — IMPORTANT: Be efficient! Minimize tool calls.
0. **Before tool calls**: First write a short, user-facing progress note in Chinese (1-3 sentences) explaining what you understood and what you will do next.
1. **FIRST** (1 call): Use glob_files to see the project structure
2. **THEN** (1-3 calls max): If `.cursor/rules/*.mdc` exists, read those rule files first, then read ONLY the key implementation files you need. Do NOT read every file. **必读**：scaffold 默认的 `shared/widget.config.json` 和一份 `.editor.config.json`，作为后续 edit 的模板——保证结构、字段类型都合法。
3. **IMMEDIATELY write code（一次性并行写多个）**: 严格 schema 的 JSON（`shared/widget.config.json` 等）走 `edit_file` 改关键字段；新增业务文件才用 `write_file`。**无论 edit_file 还是 write_file 都必须批量并行**——一个 turn 同时发 7+ 个 tool_calls 把 web/ 和 mobile/ 的所有 mode vue / setting / index.js 等一次性写/改完。**不要**对 widget.config.json 用 write_file 从零写（漏字段）；**也不要**一轮只 edit/write 一个文件（耗光 30 轮上限任务必失败）。
4. **Build 前一致性自检（必做）**: run build 前，用 glob 或 list_dir **逐个验证**两端 7 个 scene 目录（`web/src/form-component/form-widget/{edit,read,ide,list,print,search,search-ide}/` 和 `mobile/src/form-component/form-widget/{...}/`）下的 `index.js` 引用的每一个 `.vue` 文件是否都真实存在。只要有一个"index.js 引用了但 vue 不存在"，立即先补建/修正，不要先跑 build。
5. **THEN** run `npm run build` to check compilation (builds both web/ and mobile/)
6. If errors, fix and rebuild. If success, report completion.

## CRITICAL Rules
- **🔴 Scene vue 读配置铁则（违反必致所有配置失效）**：web/ 和 mobile/ 两端 7 个 scene vue（edit/read/ide/list/print/search/search-ide）里**必须用 `this.widget.customComponentConfig`** 读用户在 setting.vue 里配的参数。**严禁**写 `this.customComponentConfig`（组件本身没有这个属性，永远得到 `undefined`，`undefined || {}` 得到 `{}`，导致 displayFormat/allowedWeekdays 等所有配置都永远是默认值，用户配了等于白配）。
  - ❌ 错：`customConfig() { return this.customComponentConfig || {}; }`（拿到 {}）
  - ✅ 对：`customConfig() { return this.widget.customComponentConfig || {}; }`
  - 区别：**setting.vue（web/src/form-component/form-editor/）用 `this.componentConfig.customComponentConfig`**（EditorFormConfigMixin 提供 componentConfig prop）；**scene vue（web/src/form-component/form-widget/{mode}/ 和 mobile/src/form-component/form-widget/{mode}/）用 `this.widget.customComponentConfig`**（FormWidgetMixin 提供 widget）。两种 mixin 挂载的属性名不同，混用会静默失效（编译过 build 过，运行时配置全部失效）。
- **🔴 必须 parallel tool_calls，严禁一轮一个文件**：写代码阶段**每个 turn 必须一次发出 7+ 个并行 `write_file`/`edit_file` 调用**。双端组件通常需要写 30+ 个文件（web 7 个 scene vue + mobile 7 个 scene vue + setting.vue + widget.config.json + editor.config.json + 多个 index.js），如果每轮只调 1 个 tool，30 轮上限会被消耗殆尽而组件还没写完，任务失败。
  - ❌ 反例（任务必失败）：`turn1: [write_file]` `turn2: [write_file]` `turn3: [write_file]` ... 每轮 1 个
  - ✅ 正例：`turn1: [write_file×7]`（web/ 7 个 mode vue 一次性写完）`turn2: [write_file×7]`（mobile/ 7 个 mode vue 一次性写完）`turn3: [edit_file×3, write_file×2]`（widget.config / editor.config / setting.vue / 两个 index.js）`turn4: [run_command]`（build）
  - 即使工具可能返回 Error，也要**并行发**——Error 后下一轮并行 edit_file 修复，而不是怕 Error 变成一轮一个
- **Progress notes are visible to the user**: keep them brief, concrete, and friendly. Do NOT dump hidden reasoning or long analysis.
- **DO NOT loop**: Never read the same file twice. Never read more than 3 files before writing code.
- **Write ALL files at once**: In a single turn, call write_file for ALL web/ and mobile/ vue files. Do NOT write one file per turn.
- **When generating designer config**: update `web/src/form-component/form-editor/index.js` and `web/src/form-component-config/form-editor/index.js` in the same batch as `setting.vue` / `{name}.editor.config.json`.
- **index.js 与 vue 必须一致**: 修改任何 `index.js` 的 import 路径时，**必须**同步确保对应 vue 文件存在（新建或重命名）。不允许出现 "index.js 指向的文件不存在" 的 half-rename 状态。如不需要某个 scene，保持 scaffold 默认的 `form-component-demo-{scene}.vue` / `mobile-form-component-demo-{scene}.vue` 原样，index.js 也别改。
- **工具返回 Error 必须修复，不是放弃信号**：write_file / edit_file / run_command 等工具返回字符串以 `Error:` 开头时（如 `Error: widget.config.json: version — Input should be a valid number`），**必须**立即用 edit_file 修正对应字段再次 write，直到该工具返回 `Successfully wrote ...` 或 `[exit code: 0]`。**严禁**因为连续 3~5 条工具 Error 就终止任务（不要在 LLM 响应里返回空 tool_calls，那会触发 agent 结束）；必须坚持修到成功或撞 30 轮上限。典型修复模式：`write_file A.json → Error: A.json: foo — Field required` → `edit_file A.json 补上 foo` → 再 `write_file` 验证。
- **Be decisive**: You are an expert. After reading the scaffold structure and 1-2 example files, you have enough context to write the component.
- **Maximum 8 turns total**: If you haven't written code by turn 4, something is wrong. Write the code NOW.
- **NEVER use `<el-dialog>` inside form widgets** — it breaks FormEngine component resolution and crashes the platform with `Cannot read properties of undefined (reading 'edit')`. Use `<el-popover :append-to-body="true">` instead for any preview/popup interaction.

## Technical Constraints — Dual-End Project
- This is a **dual-end** (PC + Mobile) project with three directories: `shared/`, `web/`, `mobile/`
- aPaaS form component with 7 render scenes (edit/read/ide/list/print/search/search-ide), both web/ and mobile/ have the same scenes
- Scaffold files already exist. Do NOT modify vue.config.js or babel.config.js.
- Vue 2.7 for both ends
- **PC (web/)**: Element UI (`el-*` components), globally registered, do NOT import
- **Mobile (mobile/)**: 可使用 **cube-ui**（平台全局注册，无需 import）或 **Vant 2**（`<van-*>` 组件，vue.config.js 已配置 `unplugin-vue-components` + `VantResolver` 按需自动引入，无需手动 import）。**注意：必须使用 Vant 2（vant@latest-v2），不要使用 Vant 3/4，因为项目基于 Vue 2.7**
- **console.log is stripped in production — use `console.info` for ALL debug output in every mode.**
- **formEngine is NOT available in `beforeCreate()` — only access `this.formEngine` from `created()` or later.**

## 🛑 目录结构铁则（双端项目，绝对不要违反）

web/ 和 mobile/ **两端**的 7 个 scene vue 都**只能放在各自的 form-widget/ 下**：

```
web/src/form-component/form-widget/
├── edit/       ← form-component-{name}-edit.vue
├── read/       ← form-component-{name}-read.vue
├── ide/        ← form-component-{name}-ide.vue
├── list/       ← form-component-{name}-list.vue
├── print/      ← form-component-{name}-print.vue
├── search/     ← form-component-{name}-search.vue
└── search-ide/ ← form-component-{name}-search-ide.vue

mobile/src/form-component/form-widget/
├── edit/       ← mobile-form-component-{name}-edit.vue
├── read/       ← mobile-form-component-{name}-read.vue
├── ide/        ← mobile-form-component-{name}-ide.vue
├── list/       ← mobile-form-component-{name}-list.vue
├── print/      ← mobile-form-component-{name}-print.vue
├── search/     ← mobile-form-component-{name}-search.vue
└── search-ide/ ← mobile-form-component-{name}-search-ide.vue
```

**禁止**创建以下目录（常见幻觉，scaffold **不存在**）：
- ❌ `web/src/form-component/list-widget/` / `print-widget/` / `search-widget/` / `search-ide-widget/`
- ❌ `mobile/src/form-component/list-widget/` / `print-widget/` / `search-widget/` / `search-ide-widget/`

注意：mixin 文件名（`list-widget.mixin.js` / `search-widget.mixin.js` / `print-widget.mixin.js`）**只是文件名**，**不是目录名**。list/search/print/search-ide 的 vue 全部在各端的 `form-widget/{mode}/` 下，没有例外。

## Mixin Per Mode — IMPORTANT: use @shared/ alias (NOT @/)
- edit / ide / read → `import FormWidgetMixin from '@shared/mixin/form-widget.mixin'`
- list            → `import ListWidgetMixin from '@shared/mixin/list-widget.mixin'` （仅是 mixin 文件名，不要据此创建 list-widget/ 目录）
- print           → `import PrintWidgetMixin from '@shared/mixin/print-widget.mixin'`
- search          → `import SearchWidgetMixin from '@shared/mixin/search-widget.mixin'`
- search-ide      → `import SearchIdeWidgetMixin from '@shared/mixin/search-ide-widget.mixin'`
- editor (setting.vue, web only) → `import EditorFormConfigMixin from '@shared/mixin/form-config.mixin'`
- **NEVER use `@/mixin/...`** — shared mixins live in `shared/mixin/`, the alias `@shared` points to `../shared`

## Mode-specific Rules
- **List mode**: config = `this.componentConfig` (NOT `this.widget`); `this.formValue` is the concrete value prop directly (no propKey indexing); NO `<x-proxy-form-item>` wrapper.
- **Print mode**: NO UI component tags — neither Element UI nor Vant renders in print context; NO `<x-proxy-form-item>`; pure HTML/CSS only; use structure `div.print-item > div.print-item-title + div.print-item-value`; when `widget.isInTable` is true, omit the title.
- **Search mode**: NO `<x-proxy-form-item>`; submit via `this.$emit('change', [value])` — value MUST be wrapped in an array; do NOT use formValue setter.
- **Search-IDE mode**: NO `<x-proxy-form-item>`; all inputs `disabled`; only implement when Search mode is also implemented.
- **IDE mode**: all inputs must be `disabled` — IDE renders in the form designer canvas where user interaction is not allowed.
- **Edit mode**: check `this.widget.readOnly`; guard formValue undefined with fallback; never use both `v-model` and `@input` on the same element (causes infinite loop).

## BOF Type & formValue
- BOF_NUMBER caveat: `formValue` may arrive as a string from the platform. Always guard: `const n = Number(this.formValue); if (isNaN(n)) { /* fallback */ }`.

## 组件 name 命名约定
- PC 组件：`FormComponentXxxEdit` / `FormComponentXxxIde` / `FormComponentXxxRead` 等（PascalCase）
- 移动端组件：`MobileFormComponentXxxEdit` / `MobileFormComponentXxxIde` 等（Mobile 前缀 + PC 命名）
- 移动端文件名：`mobile-{name}-edit.vue`（kebab-case，加 `mobile-` 前缀）

## widget.config.json 中必须同时声明 PC 和移动端组件
```json
{
  "component": { "ide": "FormComponentXxxIde", "edit": "FormComponentXxxEdit", ... },
  "client": {
    "mobile": {
      "component": { "ide": "MobileFormComponentXxxIde", "edit": "MobileFormComponentXxxEdit", ... }
    }
  }
}
```

## ⚠️ code 字段三文件必须同步
`shared/widget.config.json.code`、`web/src/apaas.json.customWidgetList[0].code`、`mobile/src/apaas.json.customWidgetList[0].code` 三者必须**完全一致**。如果使用语义化 code（如 `FORM_CUSTOM_TIME_PICKER`），必须同时更新这三个文件的 `code` 字段。

## ⚠️ 移动端 edit.vue 必须使用 `<x-proxy-form-item>` 包裹（与 PC 端一致）
- `mobile/src/form-component/form-widget/edit/mobile-{name}-edit.vue` 模板最外层必须是 `<x-proxy-form-item>`
- 即使移动端使用 cube-ui 或 Vant，`x-proxy-form-item` 仍由 shared/ 平台注入，用于标题/校验提示/只读态等统一行为
- 此规则**仅对 edit 场景生效**，list/print/search/search-ide 场景仍**不要**包裹 `x-proxy-form-item`

## ⚠️ 文件命名必须与 widget.config.json.code 语义一致
- 若 `shared/widget.config.json.code = FORM_CUSTOM_TIME_PICKER`，则 semantic = `time-picker`
- 各 scene 下文件名必须为 `form-component-time-picker-{scene}.vue`（PC）/ `mobile-form-component-time-picker-{scene}.vue`（移动）
- 禁止出现与 code 语义不一致的文件名（如 `form-component-time-only-picker-edit.vue`）

## ⚠️ "一个组件 = 一套文件"
- 每个自开发组件对应 7 个 scene 各一个 vue 文件（共 14 个：PC 7 + 移动 7），构成"一套"
- 多组件工程（`customWidgetList` 多项）每个组件一套，互不覆盖，`index.js` 按 code 聚合
- 单组件工程里每个 scene 目录**只保留这一个组件的 vue 文件**，其他一律清理（脚手架占位 `form-component-demo-*.vue` / `mobile-form-component-demo-*.vue` / 旧文件 / 语义不一致的副本必须显式 delete）

## FORM_COMPONENT_DUAL 路径规范（双端组件）
- 所有 widget.config.json / editor.config.json / setting.vue / index.js 都在 `web/` 子目录下，路径前缀为 `web/src/`
- 配置面板聚合文件：`web/src/form-component/form-editor/index.js`（import setting.vue 并放入数组）
- editorConfigList 聚合文件：`web/src/form-component-config/form-editor/index.js`（import editor.config.json）
- 以上 4 个文件必须**同一批次一起写入**
- 移动端 `mobile/` 没有 setting.vue 和 editor.config.json
"""


_WORKFLOW_PAGE = """
## Workflow — IMPORTANT: Be efficient! Minimize tool calls.
0. **Before tool calls**: First write a short, user-facing progress note in Chinese (1-3 sentences) explaining what you understood and what you will do next.
1. **FIRST** (1 call): Use glob_files to see the project structure
2. **THEN** (1-2 calls max): Read ONLY the key files (`src/apaas.json`, `src/index.js`, `src/form-page/*.vue` or `src/Home.vue`, `src/api/index.js`)
3. **IMMEDIATELY write code**: Update the page files in one batch. Do NOT apply the 7-scene form-component pattern.
4. **THEN** run `npm run build` to check compilation
5. If errors, fix and rebuild. If success, report completion.

## CRITICAL Rules
- **Progress notes are visible to the user**: keep them brief, concrete, and friendly.
- **DO NOT loop**: Never read the same file twice. Never read more than 3 files before writing code.
- **Do NOT generate `widget.config.json`, `editor.config.json`, or `setting.vue`** — 这些是表单组件专属，页面场景不需要
- **Do NOT apply 7-scene pattern** (edit/read/ide/list/print/search/search-ide) — 页面只是普通 Vue 组件

## Technical Constraints — MENU_PAGE / FORM_PAGE
- 页面打包为 UMD 组件后部署，可作为独立菜单页面或被平台弹窗（x-lov）引用
- `templateType` 必须是 `MENU_PAGE`（或对应页面类型）
- Vue 2.7 + Element UI（全局注册，不要 import）
- **`$request` 不是 Promise** — 必须用 `.asyncThen()` / `.asyncErrorCatch()`，**不能用** `.then()` / `.catch()`
- **不要使用** `x-http-block-table` / `x-ag-grid` — 直接使用 Element UI 的 `<el-table>` + `<el-pagination>`
- 组件名必须是 `apaas-custom-{kebab-name}` 格式，与 `apaas.json` 的 router 配置一致
- `src/index.js` 中必须 `window[Symbol.for("组件名")] = Component` 注册
- 弹窗场景必须实现 `getSelectedData()` 方法，返回 `this.selectedRows` 数组
- **跨页多选** — el-table 翻页会清空选中，需自己维护 `selectedRows` 并用 `toggleRowSelection` 恢复
- 布局用 flex，表格区域 `flex: 1` 填充剩余空间
- 国际化目录 `src/form-page-local/` 必须存在（即使只有中文也要）
- 只修改 `src/` 下的业务文件，不要改 `vue.config.js`、`babel.config.js`

## API 来源说明（开始开发前必须确认）
页面需要数据才有意义。如果用户未说明数据来源，必须先问：
1. "数据从哪里获取？是使用低代码平台现有表单的 API，还是自定义外部 API？"
2. **平台 API**：需要 formId、tabId、字段映射
3. **自定义 API**：需要 API 地址和参数格式

若用户未提供，可用 mock 数据实现 UI 并标注 `// TODO: 替换为实际 API`，同时告知用户需要补充。

## mobile-page 特殊说明
- 移动端页面使用 cube-ui 组件库（平台全局注册，无需 import）
- 其他规则与 menu-page 相同
"""


_WORKFLOW_LAYOUT = """
## Workflow — IMPORTANT: Be efficient! Minimize tool calls.
0. **Before tool calls**: First write a short, user-facing progress note in Chinese (1-3 sentences) explaining what you understood and what you will do next.
1. **FIRST** (1 call): Use glob_files to see the project structure
2. **THEN** (1-2 calls max): Read ONLY the key files you need (`src/apaas.json`, `src/index.js`, `src/form-layout/*.vue` or `src/Home.vue`)
3. **IMMEDIATELY write code**: Update the layout files in one batch. Do NOT apply the 7-scene form-component pattern.
4. **THEN** run `npm run build` to check compilation
5. If errors, fix and rebuild. If success, report completion.

## CRITICAL Rules
- **Progress notes are visible to the user**: keep them brief, concrete, and friendly. Do NOT dump hidden reasoning or long analysis.
- **Do NOT generate `widget.config.json`, `editor.config.json`, or `setting.vue` by default**.
- **Focus on layout structure**: `x-app-layout`, `header`, `menu`, `appPage`, and any optional layout-only subcomponents.
- `templateType` must remain `PAGE_LAYOUT`
- `appPage` must forward platform content with `<slot name="appPage">`
- Do NOT modify package.json unless the task explicitly requires it.
"""


_WORKFLOW_FORM_LIST = """
## Workflow — IMPORTANT: Be efficient! Minimize tool calls.
0. **Before tool calls**: First write a short, user-facing progress note in Chinese (1-3 sentences) explaining what you understood and what you will do next.
1. Use glob_files to inspect the project structure
2. Read only the key files you need (`src/apaas.json`, `src/index.js`, `src/form-view/*.vue`)
3. Write the list-view files in one batch
4. Run `npm run build` to check compilation
5. If errors, fix and rebuild. If success, report completion.

## CRITICAL Rules
- `templateType` must remain `LIST_VIEW`
- Do NOT apply the 7-scene form-component pattern
- Focus on `index.js`, `apaas.json`, `form-view/*.vue`, and i18n files
"""


_WORKFLOW_PLUGIN = """
## Workflow — IMPORTANT: Be efficient! Minimize tool calls.
0. **Before tool calls**: First write a short, user-facing progress note in Chinese (1-3 sentences) explaining what you understood and what you will do next.
1. Use glob_files to inspect the project structure
2. Read only the key files you need (`src/apaas.json`, `src/admin.js`, `src/app.js`, `src/mobile.js`, `src/extension.js`)
3. Write the plugin files in one batch
4. Run `npm run build` to check compilation
5. If errors, fix and rebuild. If success, report completion.

## CRITICAL Rules
- `templateType` must remain `FRONTEND_PLUGIN`
- Every entry file must default-export `{ install, activate, staticComponents }`
- Do NOT generate form-component files like edit.vue/read.vue/setting.vue
"""


_WORKFLOW_BACKEND_API = """
## Workflow — IMPORTANT: Be efficient! Minimize tool calls.
0. **Before tool calls**: First write a short, user-facing progress note in Chinese (1-3 sentences) explaining what you understood and what you will do next.
1. Use glob_files to inspect the project structure
2. Read only the key backend files you need (controller/service/config/pom)
3. Write or update the backend files in one batch
4. Run the appropriate backend build/test command (`mvn test`, `mvn -q -DskipTests package`, etc.)
5. If errors, fix and rerun. If success, report completion.

## CRITICAL Rules
- This is a backend project. Do NOT generate Vue component files.
- Do NOT apply form-component rules like edit.vue/read.vue/setting.vue.
- Prefer minimal, runnable Java/Spring-style changes that match the scaffold.
"""


# ══════════════════════════════════════════════════════════════
# build_user_prompt — 从 VibeCodingAgent._build_prompt 迁移
# ══════════════════════════════════════════════════════════════

def build_user_prompt(
    *,
    requirement: str,
    conversation_summary: str,
    workspace_info: dict[str, Any],
    workspace_path: Path,
    spec_brief: str | None = None,
) -> str:
    """构造 CodingAgent 的首条 user message（替代 VibeCodingAgent._build_prompt）。

    输出结构：Task → (Structured Spec) → Workspace Info → Workspace Rules → Previous Summary → Workflow

    Args:
        spec_brief: 可选 — BrainstormAgent emit 的 Spec 渲染后的 markdown 摘要。
                    传入时在 Task 之后插入"## Structured Spec"段，LLM 应优先参考此段。
                    不传（None 或 ""）时保持旧行为（与 snapshot 字节级一致）。
    """
    project_type = (workspace_info.get("project_type", "") or "").lower()
    files = workspace_info.get("files", []) or []
    rule_files = [
        file_path for file_path in files
        if file_path.startswith(".cursor/rules/") and file_path.endswith(".mdc")
    ]

    parts: list[str] = [
        f"## Task\n{requirement}",
    ]

    # Spec 驱动路径：把结构化规格紧跟 Task 展示
    if spec_brief:
        parts.append(
            "\n## Structured Spec (from BrainstormAgent)\n"
            "以下是 brainstorm agent 与用户确认后产出的结构化规格。**优先按此段实现，"
            "Task 段只是用户原话，细节以 Spec 为准**。\n\n"
            + spec_brief.rstrip()
        )

    parts.extend([
        "\n## Workspace Info",
        f"- Project name: {workspace_info.get('project_name', '')}",
        f"- Project type: {project_type}",
        f"- Working directory: {workspace_path}",
    ])

    if rule_files:
        parts.append("\n## Workspace Rules")
        parts.extend(
            f"- Read and follow `{rule_file}` before writing code"
            for rule_file in rule_files
        )

    if conversation_summary:
        parts.append(f"\n## Previous Conversation Summary\n{conversation_summary}")
    else:
        parts.append("\n## Previous Conversation Summary\nNone (first development session)")

    if project_type == "form-component-dual":
        workflow = _WORKFLOW_FORM_COMPONENT_DUAL + render_form_component_sections(base_path="web/src")
    elif project_type in ("menu-page", "form-page", "mobile-page"):
        workflow = _WORKFLOW_PAGE
    elif project_type == "layout":
        workflow = _WORKFLOW_LAYOUT
    elif project_type == "form-list":
        workflow = _WORKFLOW_FORM_LIST
    elif project_type == "plugin":
        workflow = _WORKFLOW_PLUGIN
    elif project_type == "backend-api":
        workflow = _WORKFLOW_BACKEND_API
    else:
        workflow = _WORKFLOW_FORM_COMPONENT + render_form_component_sections(base_path="src")

    parts.append(workflow)
    return "\n".join(parts)
