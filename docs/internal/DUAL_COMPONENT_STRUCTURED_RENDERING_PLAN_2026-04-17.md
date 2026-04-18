# 双端 form-component 结构化渲染架构方案

**日期**：2026-04-17
**作者**：Mars + Claude
**状态**：方案已确认，先完成当前打补丁路线的验证，之后按本方案实施。
**范围**：仅 `form-component-dual`（双端表单组件）；单端、页面、布局、后端接口等其他场景保持现有 vibe agent 路径。

---

## 背景与动机

### 当前问题

过去 25+ commit 累积为双端 form-component 生成加了 20+ 条 prompt 铁则（命名/目录结构/editor 选用/数据类型/赋值 editor/widget.config 字段/自造 editor 铁则/工具并行/Error 修复 …）。收益边际递减：

1. **规则互相打架**：如 `76974c7`（修 widget.config 校验、加 Error 修复铁则、加 build 前自检）无意中让 LLM 从"一次 7 个并行 write_file"退化成"一轮 1 个文件"，30 轮上限被耗光，任务失败。直到 `6207d44` 才补回并行约束。这类"修 A 破 B"会持续发生——prompt 规则间耦合是**隐性**的。
2. **没有回归测试**：每次改 prompt 都靠用户手工跑一次生成（20-30 分钟/轮）+ 截图反馈。历史上"并行"规则被破没人知道，直到实际翻车。
3. **LLM 不线性消化 prompt**：第 20 条规则不会比前 19 条同等生效，LLM 会"综合印象"走最保守路径 → 加越多约束 LLM 越畏首畏尾。

### 根本诊断

**当前架构让 LLM 做的大部分事是确定性的**（占工程 80%+）：

- 7 个 mode vue 的骨架（mixin import / `<x-proxy-form-item>` 包裹 / name 命名）
- widget.config.json 的完整字段结构（version/display/allow/default/validator/special/editor/client）
- editor.config.json（4 个固定字段）
- apaas.json
- index.js 聚合

**真正需要 LLM 判断的是业务语义**（占 < 20%）：

- 组件叫啥、有哪些配置项、每项用哪种 editor
- 派生值怎么算
- edit.vue 里的业务 UI 片段

**方向错位**：让 LLM 从零写 100%，再用 prompt 告诉它别写错的每一个细节——顺序反了。

---

## 设计目标

**确定性的事由 Python 保证；业务创造性的事由 LLM 决策。**

LLM 的职责从"自由发挥写 20+ 文件"缩到"产出一份结构化 spec + 填几段业务 UI 片段"。

---

## 架构总览

```
┌──────────────────────────────────────────────────────────────┐
│ 阶段 1：Plan (LLM)                                            │
│   需求 + brainstorm → ComponentSpec DSL (Pydantic schema)      │
│   LLM 只决策业务语义，不写代码                                  │
│   Pydantic 校验失败 → LLM 修 spec（不是改 20 个文件）          │
└──────────────────────────────────────────────────────────────┘
                         ↓
┌──────────────────────────────────────────────────────────────┐
│ 阶段 2：Render (Python, 确定性)                                │
│   ComponentSpec → 20+ 文件渲染                                 │
│   - widget.config.json (shared/)              100% 确定        │
│   - apaas.json × 2 (web/ + mobile/)           100% 确定        │
│   - editor.config.json (web/)                 100% 确定        │
│   - setting.vue (web/)                        100% 模板组装     │
│   - 自造业务 editor.vue                       骨架确定，业务槽位 │
│   - 7 web mode vue + 7 mobile mode vue        骨架确定，业务槽位 │
│   - 所有 index.js 聚合                         100% 确定        │
└──────────────────────────────────────────────────────────────┘
                         ↓
┌──────────────────────────────────────────────────────────────┐
│ 阶段 3：Build + Fix Loop                                       │
│   npm run build 两端                                            │
│   失败 → 错误定位到具体 slot → LLM 只改 slot → 重新 render      │
│   最多 N 次重试，再失败 fallback 到老 vibe agent                │
└──────────────────────────────────────────────────────────────┘
```

---

## ComponentSpec DSL 设计（核心契约）

LLM 唯一产出的结构化数据。用 Pydantic 严格定义 + 跨字段 validator 兜底。

```python
# app/coding/dual_component/spec.py

from typing import Literal, Any
from pydantic import BaseModel, model_validator

SCENES = ['edit', 'read', 'ide', 'list', 'print', 'search', 'search-ide']

class ConfigPropertySpec(BaseModel):
    """一条 setting.vue 的配置项"""
    property: str                    # 'defaultValue' / 'minDate'
    dataType: Literal['String', 'Number', 'Boolean', 'Array', 'Object']
    uiEditor: str                    # 'form-custom-input-editor' 等，含自造 editor 名
    defaultValue: Any                # 必须和 dataType 一致
    label: str
    help: list[str] = []
    options: list[dict] | None = None        # select 用
    otherFields: list[dict] | None = None    # field-assign 用
    otherTableFields: list[dict] | None = None  # table-field-assign 用


class AssignSourceSpec(BaseModel):
    """组件作为赋值源能产出的字段（喂给 field-assign-editor 的 otherFields）"""
    uuid: str                        # 业务 id: 'diff'
    label: str                       # '时间差'
    componentType: Literal[
        'FORM_NUMBER_INPUT', 'FORM_TEXT_INPUT', 'FORM_MONEY_INPUT',
        'FORM_PHONE_INPUT', 'FORM_EMAIL_INPUT', 'FORM_IDCARD_INPUT',
    ]
    computeExpression: str           # JS 表达式，由 renderer 插入 edit.vue


class CustomEditorSpec(BaseModel):
    """自造业务 editor（预置原子无法覆盖时）"""
    name: str                        # 'form-custom-date-time-editor'
    businessTemplate: str            # <sechma-item> 内的业务 UI 片段（LLM 填）
    extraProps: list[dict] = []      # 业务特有 props


class ModeSlotSpec(BaseModel):
    """某个 scene 的业务代码槽位"""
    businessTemplate: str            # <x-proxy-form-item> 内的业务 UI 片段
    businessScript: str = ""         # data / computed / methods / watch 业务代码


class ComponentSpec(BaseModel):
    # 元数据
    name: str                        # 'date-time-range' (kebab-case，禁 custom/demo/component)
    displayName: str                 # '日期时间段选择'
    description: str
    iconSvg: str                     # LLM 产出的 SVG，必须以 <svg 开头

    # 数据存储
    componentModelField: Literal['STRING', 'BIG_TEXT', 'NUM', 'DATE']
    bofType: Literal['BOF_TEXT', 'BOF_NUMBER', 'BOF_DATE']
    formValueExample: str            # 示例值文本（仅说明用）

    # 配置面板
    configProperties: list[ConfigPropertySpec] = []
    customEditors: list[CustomEditorSpec] = []

    # 赋值源（组件产出的派生字段）
    assignSources: list[AssignSourceSpec] = []

    # 业务代码槽位（每端 7 个 mode）
    webModes: dict[str, ModeSlotSpec]       # key: 'edit'/'read'/'ide'/...
    mobileModes: dict[str, ModeSlotSpec]

    # 第三方依赖
    npmDependencies: list[str] = []

    # ── 跨字段校验（spec 一致性）─────────────────────────
    @model_validator(mode='after')
    def _validate_consistency(self):
        # 1. name 禁占位词
        if self.name.lower() in {'custom', 'demo', 'component', 'custom-dev', 'form-component'}:
            raise ValueError(f"name '{self.name}' 是占位词，必须反映组件功能")

        # 2. componentModelField ↔ bofType 映射
        mapping = {
            'STRING': 'BOF_TEXT', 'BIG_TEXT': 'BOF_TEXT',
            'NUM': 'BOF_NUMBER', 'DATE': 'BOF_DATE',
        }
        if mapping[self.componentModelField] != self.bofType:
            raise ValueError(
                f"componentModelField={self.componentModelField} 应配 {mapping[self.componentModelField]}, "
                f"当前 bofType={self.bofType}"
            )

        # 3. configProperty.uiEditor 如果是自造，必须在 customEditors 里
        preset = {
            'form-custom-input-editor', 'form-custom-select-editor',
            'form-custom-textarea-editor', 'form-custom-switch-editor',
            'form-custom-field-assign-editor', 'form-custom-table-field-assign-editor',
        }
        custom_names = {e.name for e in self.customEditors}
        for prop in self.configProperties:
            if prop.uiEditor not in preset and prop.uiEditor not in custom_names:
                raise ValueError(f"configProperty '{prop.property}' 的 uiEditor '{prop.uiEditor}' 既不是预置也不在 customEditors 列表")

        # 4. 有 assignSources 但没 field-assign-editor 配置项 → 用户永远配不了目标字段
        if self.assignSources and not any(
            p.uiEditor == 'form-custom-field-assign-editor' for p in self.configProperties
        ):
            raise ValueError("声明了 assignSources 但 configProperties 里没有 form-custom-field-assign-editor")

        # 5. iconSvg 必须以 <svg 开头
        if not self.iconSvg.strip().startswith('<svg'):
            raise ValueError("iconSvg 必须是 SVG 字符串（以 <svg 开头）")

        # 6. webModes / mobileModes 必须覆盖全部 7 个 scene
        for side, modes in [('web', self.webModes), ('mobile', self.mobileModes)]:
            missing = set(SCENES) - set(modes.keys())
            if missing:
                raise ValueError(f"{side}Modes 缺少 scene: {missing}")

        # 7. field-assign-editor 配置项的 dataType 必须是 Array
        for prop in self.configProperties:
            if prop.uiEditor in ('form-custom-field-assign-editor',
                                 'form-custom-table-field-assign-editor'):
                if prop.dataType != 'Array':
                    raise ValueError(
                        f"configProperty '{prop.property}' 用 {prop.uiEditor}，dataType 必须是 Array"
                    )

        # 8. defaultValue 类型要和 dataType 一致
        type_check = {
            'String': str, 'Number': (int, float), 'Boolean': bool,
            'Array': list, 'Object': dict,
        }
        for prop in self.configProperties:
            expected = type_check[prop.dataType]
            if prop.defaultValue is not None and not isinstance(prop.defaultValue, expected):
                raise ValueError(
                    f"configProperty '{prop.property}' dataType={prop.dataType} 但 defaultValue 类型是 {type(prop.defaultValue).__name__}"
                )

        return self
```

**校验 → LLM 修 spec**的反馈循环比"校验 → LLM 修 20 个文件"快 10 倍，因为修的是 JSON 字段而不是跨文件语法。

---

## Renderer 职责清单

```python
# app/coding/dual_component/renderer.py

class DualComponentRenderer:
    def render(self, spec: ComponentSpec, ws_path: Path) -> RenderResult:
        files_written: list[Path] = []

        # 1. shared/widget.config.json — 完整合法（Pydantic 再次校验）
        self._render_widget_config(spec, ws_path, files_written)

        # 2. web/src/apaas.json + mobile/src/apaas.json
        self._render_apaas_json(spec, ws_path, 'web', files_written)
        self._render_apaas_json(spec, ws_path, 'mobile', files_written)

        # 3. web/src/form-component-config/form-editor/{name}.editor.config.json
        if spec.configProperties:
            self._render_editor_config(spec, ws_path, files_written)

        # 4. 自造业务 editor
        for editor in spec.customEditors:
            self._render_custom_editor(spec, editor, ws_path, files_written)

        # 5. web/src/form-component/form-editor/{name}-setting.vue
        if spec.configProperties:
            self._render_setting_vue(spec, ws_path, files_written)

        # 6. 14 个 mode vue
        for mode in SCENES:
            self._render_mode_vue(spec, 'web', mode, ws_path, files_written)
            self._render_mode_vue(spec, 'mobile', mode, ws_path, files_written)

        # 7. 所有 index.js 聚合（14 个 scene index.js + 2 个 form-editor index.js）
        self._update_all_index_js(spec, ws_path, files_written)

        return RenderResult(files=files_written, spec=spec)
```

每个 `_render_*` 方法使用 Jinja2 模板 + spec 字段插值。模板里**硬编码**（LLM 永远看不到）：

- `import FormWidgetMixin from '@shared/mixin/form-widget.mixin'`
- `<x-proxy-form-item :isInTable="widget.isInTable" ... >` 包裹
- `mixins: [FormWidgetMixin]`
- 组件 name 约定（`FormComponentXxxEdit` / `MobileFormComponentXxxEdit`）
- 目录路径
- index.js 的 `customFormEditorList` / `editorConfigList` 变量名约定

**LLM 永远看不到**这些，自然永远不会错。

### 模板结构示例（web edit.vue）

```vue
{# web-edit.vue.j2 #}
<template>
  <div class="form-widget form-component-{{ spec.name }}-edit">
    <x-proxy-form-item
      :isInTable="widget.isInTable"
      :showRequired="showRequired"
      :label="widget.label"
      :titleDescription="widget.titleDescription"
      :renderScene="renderScene"
      :validatorRules="validatorRules"
      :validateKey="validateKey"
      :validateInfo="validateInfo"
      :webFormSettings="webFormSettings"
    >
      {# ↓ LLM 填的业务 UI 片段 #}
      {{ spec.webModes.edit.businessTemplate }}
    </x-proxy-form-item>
  </div>
</template>

<script>
import FormWidgetMixin from '@shared/mixin/form-widget.mixin'

export default {
  name: '{{ pascal(spec.name) }}Edit',
  mixins: [FormWidgetMixin],
  {# ↓ LLM 填的业务 data/computed/methods/watch #}
  {{ spec.webModes.edit.businessScript }}
}
</script>
```

---

## LLM 负责的 3 件事

| # | 工作 | 输入 | 输出 | 格式 |
|---|---|---|---|---|
| 1 | 产出 Spec | 需求 + brainstorm proposal | ComponentSpec JSON | 结构化 |
| 2 | 填业务 UI 片段 | spec.{web,mobile}Modes 每个 slot | Vue `<template>` 片段 + 短 script | 字符串 < 50 行 |
| 3 | Slot 修复 | build error + 该 slot 当前内容 | 修正后的 slot | 字符串 |

**完全不做**的事：
- 写 widget.config.json / index.js / apaas.json / editor.config.json（不碰）
- 决定文件路径 / 命名 / import 写法
- 判断是否并行 tool_calls
- 处理 Error 信息（Python renderer 自己处理）

---

## Pipeline 集成

```python
# pipeline.py

if project_type == ProjectType.FORM_COMPONENT_DUAL.value:
    # 新路径
    async for event in run_dual_component_pipeline(
        params, ws_path, brainstorm_proposal, db, conversation_id,
    ):
        yield event
    return

# 其他项目类型保留原 VibeCodingAgent 路径
agent = VibeCodingAgent(...)
async for event in agent.run(...): yield event
```

```python
# app/coding/dual_component/pipeline.py

async def run_dual_component_pipeline(params, ws_path, proposal, db, conv_id):
    # 阶段 1：LLM 产出 spec
    yield event('step', status='planning')
    spec = await llm_generate_spec_with_retry(
        params.message, proposal, model=params.model, max_retry=3,
    )

    # 阶段 2：Python 渲染
    yield event('step', status='rendering')
    result = DualComponentRenderer().render(spec, ws_path)
    for f in result.files:
        yield event('file_write', fileName=f.name, fileContent=f.read_text())

    # 阶段 3：build + slot-fix 循环
    yield event('step', status='building')
    for attempt in range(5):
        build_result = await WorkspaceManager().build_project(params.workspace_id)
        if build_result.status == 'ok':
            break
        slot_patches = await llm_fix_slots(build_result.errors, spec, ws_path)
        spec = apply_slot_patches(spec, slot_patches)
        DualComponentRenderer().render(spec, ws_path)

    yield event('done', workspace_id=params.workspace_id, ...)
```

### LLM 产出 spec 的 prompt 结构

```
你是 aPaaS 表单组件架构师。根据下面的设计方案，产出 ComponentSpec JSON。

[原始需求]
{user_requirement}

[已确认的设计方案]
{brainstorm_proposal}

输出格式：严格符合 ComponentSpec Pydantic schema 的 JSON，不要任何其他文字。
关键字段要求：
- name: kebab-case，反映功能，禁 custom/demo/component
- componentModelField / bofType: 按 formValue 形态选择（见下表）
- configProperties: 按 brainstorm 方案的配置项表格 1:1 列出
- customEditors: 预置原子无法覆盖的业务 editor（如日期范围）
- assignSources: 如果组件产出可赋值的派生字段
- webModes / mobileModes: 每个 scene 的业务 template 片段 + script

[formValue 形态 → componentModelField 映射表]
...
```

LLM 产出 JSON → Pydantic 构造 → 失败抛 `ValidationError` → 把 error 喂回给 LLM 让它修 JSON → 直到通过或 retry 上限。

---

## 工作量分期

| 阶段 | 范围 | 时间 |
|---|---|---|
| P1 | ComponentSpec Pydantic 定义 + `model_validator` 跨字段约束 + 单测 | 0.5 天 |
| P2 | widget.config.json / apaas.json / editor.config.json 渲染器（纯 JSON） | 0.5 天 |
| P3 | Jinja2 模板 × 7 mode × 2 端 + `_render_mode_vue` 业务槽位插值 | 1 天 |
| P4 | setting.vue / 自造 editor / index.js 聚合渲染器 | 0.5 天 |
| P5 | `llm_generate_spec` prompt + Pydantic 错误→LLM retry 循环 | 0.5 天 |
| P6 | `run_dual_component_pipeline` + pipeline.py 分支集成 + build-fix loop | 0.5 天 |
| P7 | 3-5 个固定需求端到端测试（golden file + 端到端 run） | 0.5 天 |

**合计 ~4 天饱和**，风险缓冲到 5 天。

### 每阶段独立可验证

- P1 完成：可手工构造 ComponentSpec 实例，跑通 Pydantic 校验
- P2 完成：给一个 spec 实例，能手工渲染出合法 widget.config.json（Pydantic 再次校验通过）
- P3 完成：给 spec + 业务槽位样本，能渲染出可 compile 的 mode vue
- P6 完成：可在前端触发一次完整 codegen 流程

---

## 迁移策略

1. **新路径完全独立**：`app/coding/dual_component/` 新目录，`pipeline.py` 里加 `if` 分支走新路径
2. **老路径保留**：单端 / 页面 / 布局 / 后端接口全部继续走 `VibeCodingAgent`
3. **Feature flag**：`APAAS_DUAL_STRUCTURED=true` 环境变量控制新路径开关，出问题一键回退
4. **双路并存期**：新路径上线后观察 1-2 周。通过后再删老路径中**只服务双端**的 prompt 铁则（`_SHARED_*_SECTION` 里的双端描述 + `apaas-form-component-dual-dev.mdc` 等）

---

## Prompt 减负预估

| 位置 | 当前 | 新方案后 |
|---|---|---|
| `_SHARED_WIDGET_CONFIG_SECTION`（双端部分） | ~60 行 | 删除 |
| `_SHARED_EDITOR_CONFIG_SECTION`（双端部分） | ~20 行 | 删除 |
| `_SHARED_SETTING_VUE_SECTION`（双端部分） | ~200 行 | 删除 |
| `apaas-form-component-dual-dev.mdc` | ~440 行 | 保留（兜底） |
| 双端 `setting-vue.mdc` | ~440 行 | 删除 |
| 双端 `df-sdk-common.mdc` | ~260 行 | 保留（LLM 填 slot 时需要 df API 知识） |

**净删 ~900 行 prompt，LLM 上下文轻 2-3k token。** 推理更快、准确率更高。

---

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| Spec 第一版覆盖不全特殊场景 | spec 加 `extraFiles: dict[path, content]` 作为 escape hatch，LLM 可以在 slot 覆盖不到时自由写几个文件。稀有场景出现时再扩 spec |
| 模板与 scaffold 变动脱钩 | 对应 scaffold 文件加 golden test：CI 读 scaffold 跑 Jinja2 渲染一个 demo，对比输出是否合法。scaffold 变动立即报错 |
| LLM 产出的 spec 字段类型错 | Pydantic 前置拦截，errors 结构化回给 LLM；比让 LLM 看一堆 vue 编译错定位快 10 倍 |
| build 仍可能失败（业务片段写坏） | slot-fix 循环最多 5 次；失败时 fallback 到老 VibeCodingAgent |
| LLM 响应非合法 JSON | 用 JSON mode（OpenAI）或 structured output（Anthropic），双重保险 |

---

## 收益对比

| 维度 | 当前 | 目标 |
|---|---|---|
| 主要故障点数量 | 30+（LLM 可能在任何文件任何位置出错） | 3（spec / slot / build error 修复） |
| 单次生成成功率 | ~30%（日期时间段组件 3 次测试 0 次跑通） | > 90%（常规组件） |
| 新增一类组件的 prompt 调整 | 高（加铁则） | 低（改 spec schema） |
| 回归测试 | 无 | Pydantic 单测 + golden file 对比 |
| LLM token 消耗 | ~8k prompt/call | ~3k |
| 并行/Error/路径/命名问题 | 反复出现 | 彻底消失（Python 保证） |

---

## 决策记录

- **2026-04-17** 方案确认，决定**先完成当前打补丁路线的验证**（跑通一次日期时间段组件生成），再按本方案实施。
- 实施时机：待当前路径稳定跑通常规组件后启动。
- 范围承诺：**只替换双端路径**，单端保留 vibe agent。
- 实施人：待定。
