# 设计:对话加字段直接铺到表单 —— 新增 MCP 工具 `add_apaas_field_to_form`

日期:2026-06-18
分支:feat/desktop-login-mvp
状态:设计已确认,待 writing-plans

## 背景与根因

用户在 AI 对话/配置助手里说「给表单加个字段」,结果只在**模型(业务对象/BO)**上建了字段,字段**没有出现在表单上**。

根因(已核实):

1. aPaaS 里「模型字段」和「表单布局」是两套独立的东西。表单存自己的一份 `detailPage.formComponents[]`,每个组件用 `modelField: "模型.字段"` 显式引用一个模型字段。模型加字段 ≠ 表单自动多一格,必须再往 `formComponents` 显式塞一个组件。
2. 加字段工具 `add_apaas_model_field`(`backend/app/mcp_tools/apaas_config_crud.py:264`)语义只到模型层:只调 `c.add_model_field(...)` + 失效缓存 + 返回,完全不碰表单,返回里也没有指向「去更新表单」的 next_step。
3. 缺口:没有「往已有表单增量加一个组件」的工具。
   - `form_components.py` 的 `set_apaas_form_component_*` / `update_apaas_form_component` 只改**已存在**组件的属性,不新增。
   - 唯一从模型补表单的 `repair_empty_apaas_form_from_model`(`apaas_form_tools.py:933`)是**全量重建,且只在表单组件数=0 时生效**(`apaas_form_tools.py:952` 与 `:1017` 两道闸,非空直接 `skipped: FORM_ALREADY_HAS_COMPONENTS`,注释:避免覆盖用户手工设计)。
   - 「从 0 建」时字段能上表单,是因为 `build_apaas_feature_from_spec` 把模型字段和表单组件一起生成;但「给已存在的表单加字段」这条增量路径既无工具也无编排。

链路在模型层就断了,所以字段上不了表单。

## 目标

新增一个 MCP 工具,一把做完两件事:给模型建字段(若不存在)+ 把该字段作为组件追加到指定表单详情页,可选同时上列表页。直接根治「只建模型没上表单」。

合并(而非纯增量)的理由:原 bug 的本质是 agent 漏掉第二步;一把做完两件事,agent 无从漏。

## 方案

### 工具

`add_apaas_field_to_form`,放在 `backend/app/mcp_tools/apaas_form_tools.py`(表单中心,且复用件都在此文件)。

复用件:
- `_build_basic_component_from_model_field(field, model_code)`(`apaas_form_tools.py:1338`)—— 组件类型自动推导(绑字典→`FORM_SELECT_INPUT_SINGLE`、BIG_TEXT/TEXT→`FORM_TEXTAREA_INPUT`、NUM 系→`FORM_NUMBER_INPUT`、DATE 系→`FORM_DATEPICK_INPUT`、否则 `FORM_TEXT_INPUT`)。
- `_with_client`(模块全局,`register()` 注入)—— 取 client + 401 自愈,返回 `(ok, raw)`。
- `client.add_model_field(...)` —— 与 `add_apaas_model_field` 同一底座(`apaas_client.py:1152`)。
- `client.query_form_config` / `client.save_form_config`(`apaas_client.py:2575` / `:2691`)。
- `operations/form_config.py` 的 `_save_form_config_with_retry`(乐观锁冲突重试)。

### 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `env_id` | — | 标准 |
| `apaas_app_id` | — | 标准 |
| `model_id` | — | 字段加到哪个模型 |
| `model_code` | — | 同上 |
| `field_code` | — | 字段定义 |
| `field_name` | — | 字段定义 |
| `field_type` | `"STRING"` | STRING/NUM/DATE/DATETIME/BOOLEAN/TEXT/BIG_TEXT |
| `max_length` | `255` | |
| `comment` | `""` | |
| `form_id` | — | 铺到哪张表单 |
| `show_in_list` | `False` | True 时字段也进列表页 `queryList` 列 |

### 执行流程

1. **保留字预检** —— 复用 `add_apaas_model_field` 的逻辑(`approver_id`/`id`/`tenant_id`/`approval_*` 命中即 `RESERVED_FIELD_CODE` 报错)。
2. **加模型字段** —— 调 `client.add_model_field(...)`。
   - 返回「字段已存在」类错误 → **容忍**,继续往下(工具可重跑;也支持「字段已在模型上、只想铺表单」)。
   - 其它错误 → 直接返回错误,不往下。
3. **构造组件** —— 用参数拼 field dict(`field_code`/`field_name`/`data_type=field_type`/`max_length`/`dictionary_code=""`),喂 `_build_basic_component_from_model_field(field, model_code)`。
4. **读表单 → 幂等 → 追加 → 存回**
   - `client.query_form_config(apaas_app_id, form_id)` 读当前配置。
   - 扫 `detailPage.formComponents`:若已有组件 `modelField == f"{model_code}.{field_code}"` → **跳过追加**,返回 ok 带「字段已在表单上」。
   - 否则 append 到 `detailPage.formComponents` 末尾;确保 `allModelCodes` 含 `model_code`(无则补)。
   - `show_in_list=True`:把 `f"{model_code}.{field_code}"` 追加进 `detailPage.listPageView.queryList`(已存在则不重复)。
   - `client.save_form_config(...)` 存回;乐观锁冲突走 `_save_form_config_with_retry`(冲突时重读最新配置、重新追加一次再存)。
5. **收尾** —— 失效缓存(同 `add_apaas_model_field` 的 `_invalidate_section_cache_after_write(apaas_app_id)`);返回 `next_step` 提示 `republish_apaas_app` 让模型变更生效 + 刷新表单设计器;若字段意图是下拉,提示后续 `bind_apaas_form_field_to_dict` 绑字典。

### 错误处理(不静默吞)

- 模型加成功但表单 `save` 失败 → 返回**部分成功错误**,明说「字段已加到模型,但铺表单失败:<原因>」,让用户知道真实状态(避免本仓库最忌的「parser 非法即默默 continue → 用户无感丢数据」)。
- 已在表单上 / 已在 `queryList` → 幂等跳过,不报错、不重复。

### 工具注册

`backend/tool_registry.yaml` 加一条 `add_apaas_field_to_form`:`sections: [data, ui]`、`agents: [builder, config]`、`category: update`。

## 测试(TDD,fake client,不连真 apaas)

内存假 client:持有一份 `form_config` dict + 记录 `add_model_field` 调用 + 可注入 `save` 异常。覆盖:

1. 新字段 → `add_model_field` 被调 + 组件入 `detailPage.formComponents` + `allModelCodes` 含 `model_code` + `save_form_config` 被调。
2. 幂等:字段已在表单(`formComponents` 已有同 `modelField`)→ 不重复追加,返回「已在表单上」。
3. 字段已在模型:`add_model_field` 返回重复错误 → 容忍,继续铺表单成功。
4. `show_in_list=True` → `model_code.field_code` 进 `detailPage.listPageView.queryList`。
5. 默认 `show_in_list=False` → `queryList` 不动。
6. `save_form_config` 抛错 → 返回「已上模型未上表单」部分成功错误。
7. 组件类型推导:`field_type=NUM` → 组件 `componentType == FORM_NUMBER_INPUT`。

## 已知风险(首次真机必验)

1. `detailPage.listPageView.queryList` 跟着 `save_form_config`(`POST /xdap-app/formConfig/save/formConfigDetail`)一起存,平台认不认这条列表写法**没核过**——没有独立的 list-page 写回方法(只有读:`query_list_page_config` → `listPageConfigById`)。若不认,`show_in_list` 降级为 Phase 2,详情页追加这条主路径不受影响。
2. 追加组件后表单设计器渲染是否正常(本仓库有 `webFormSettings` 注入致画布空白的坑)——靠复用 `_build_basic_component_from_model_field` 现成口径规避,首次真机看一眼画布即可。

## 非目标(YAGNI / Phase 2)

- 子表(`FORM_WIDGET_SON_TABLE`)字段:v1 只管主模型字段。
- 组件类型显式覆盖参数:v1 只自动推导。
- 组件落点位置控制:v1 一律追加到末尾。
- 自动绑字典:仍走独立的 `bind_apaas_form_field_to_dict`。
