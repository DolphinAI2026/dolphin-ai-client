# 延迟工具 + ToolSearch(给 run_agent)— 设计文档

- 日期：2026-06-05
- 状态：设计已确认(大明哥),待 plan
- 来源:借鉴 claude-js 的 deferred tools 机制(见 `docs/research-claude-js-harness-borrow-2026-06-05.md` 第 1 项),改写成 OpenAI 兼容网关可用的版本。这是「借鉴 claude-js harness」三件套的第 1 件(后续:#2 上下文压缩、#3 大结果落盘)。

## 1. 背景与目标

### 背景
`run_agent`(`backend/app/ai_chat/agent.py`)现在 `get_all_tool_schemas()`(`tools.py:1384`,返回 `builder∪coding∪config` ~85 工具)开场拉一次,`_run_agent_inner`(`:674`)每轮把全套 schema 原样塞进 `_call_llm_stream` 的 `payload["tools"]`(`:384`/`:403`)。**~85 个完整 schema × 每轮** = 每轮 ~10–30k token + 注意力稀释。这是这次会话「全并 ~85」时实测的痛点。

### 目标
保留「一套引擎、所有工具可用」(不走回头裁剪老路),但**把长尾工具的 schema 从每轮上下文里挪走**:平时只放工具名清单,模型用 `search_tools` 按需把需要的工具激活进 `tools` 数组。每轮 `tools` 从 ~85 完整 schema 降到 核心 ~15 完整 + 长尾一行清单。

### 非目标
- 上下文压缩(#2)、大结果落盘(#3)—— 单独的后续 spec。
- Anthropic `tool_reference`/`defer_loading` 原生机制 —— 网关不支持,本 spec 用「会话 active 集 + 每轮重建 tools 数组」模拟。
- 子 agent 的工具作用域(借鉴清单 #4)—— 不在本 spec。

## 2. 关键决策(已拍板)
- **延迟策略 = 总是延迟长尾**(非阈值/自动切)。
- **核心集 = base 本地工具 + search_tools + 数据驱动的高频 apaas 读**(规模 ~15)。具体哪几个高频读 spec→plan 时查 `agent_step.tool_name` 频次定,不靠猜。
- **active 集从历史推导**(非内存字典/新表):重启不丢、不加 DB 列。

## 3. 架构:工具宇宙三分

`get_all_tool_schemas()` 返回的全集(已含 A4 的 `_LAST_TOOL_SCHEMAS` 缓存 + 今天的 app-locked browser_* 排除)按名字分三类:

| 类 | 内容 | 在每轮 `tools` 里的形态 |
|---|---|---|
| **CORE_LOCAL** | `BASE_TOOL_SCHEMAS`(8 个本地工具,`tools.py:30`)+ 新 `search_tools` | 完整 schema,恒在 |
| **CORE_HOT** | 数据驱动选出的 ~6-10 个高频 apaas 读(list_apaas_app_models/menus、get_apaas_app_overview、list_apaas_app_dicts…) | 完整 schema,恒在 |
| **DEFERRED** | 其余 ~70(写操作 + 长尾) | **不进 `tools`**;只在 system prompt 的「延迟工具清单」里出现(name — desc — search_hint) |

核心集名单用一个显式常量定义(`CORE_TOOL_NAMES: set[str]`),便于审计 + 调整(呼应借鉴清单 #4 的「显式 Set」)。

## 4. 详细设计

### 4.1 延迟工具清单(manifest)注入 system prompt
- 新函数 `build_deferred_tools_manifest(deferred_schemas) -> str`:每个延迟工具一行 `- {name}: {desc 一句话}{ (关键词: search_hint) if 有}`。
- 在 `_build_initial_messages`(`agent.py:490`)组 system prompt 时追加这段(放在工具使用引导附近),并加一句引导:**「下面是可按需加载的工具清单;要用清单里的工具,先调 `search_tools` 把它们加载进来,再调用。」**
- manifest 只含 name+desc+search_hint(≪ 完整 schema)。app 锁定时排除 browser_*(与 `tools` 一致)。

### 4.2 `search_tools` 工具(新 base 工具)
- schema:`{ "query": string }`。加进 `BASE_TOOL_SCHEMAS` + `TOOL_HANDLERS`(`tools.py`)。
- query 两种:
  - `select:name1,name2` —— 精确选(逗号多选)。
  - 关键词 —— 对延迟工具的 `name`(按 `_`/CamelCase 切词)+ `desc` + `search_hint` 打分:name 词精确命中最高,desc 词边界次之,子串再次;返回 top-N(默认 ~8)。
- handler 返回结构化结果:`{"ok": true, "activated": [names], "message": "已加载 N 个工具,下一步可直接调用"}`(搜不到:`{"ok": true, "activated": [], "message": "无匹配;最接近: [...]"}`)。**不在结果里塞完整 schema**(schema 下一轮从 `tools` 数组给)。

### 4.3 每轮重建 `tools`(核心改动,`_run_agent_inner`)
- 现状:`tool_schemas = await get_all_tool_schemas()`(`:674`)开场一次 + 每轮原样传。
- 改为:
  - 开场:`all_schemas = await get_all_tool_schemas()`(已含 app-locked browser_* 排除);拆成 `core_schemas`(CORE_LOCAL+CORE_HOT,按 `CORE_TOOL_NAMES`)+ `deferred_by_name: dict[name, schema]`(其余)。
  - `active: set[str]` = **从历史重建**(见 4.4)。
  - **每次** `_call_llm_stream` 前:`tools = core_schemas + [deferred_by_name[n] for n in active if n in deferred_by_name]`。
  - loop 内执行完一个 `search_tools` 工具调用后:解析其结果的 `activated`,`active |= set(activated)` → 下一轮 LLM 调用这些工具就带 schema 了。

### 4.4 active 集从历史推导(无新表)
- run 开始时,扫本会话 `AIChatToolCall`(`tool_name == "search_tools"`)的 `result_text`,解析其中 `activated` 名单 → 初始 `active`。
- 兜底:历史里**已被成功调用过的延迟工具名**也并进 `active`(防御:即使 search 结果没解析全,用过的就保持可用)。
- 效果:同一会话跨多条 send 粘住;后端重启从持久化 tool_calls 重建,不丢。

### 4.5 search_hint(可选,提召回)
- `tool_registry.yaml` 每条工具可选加 `search_hint: "关键词 词组"`(名字里没有的同义词,如 deploy 类加「发布 上线 go-live」)。`tools_for_agent`/schema 加载时透传到 schema(或单独读)。非必填,缺省空。

## 5. 数据流(一次典型交互)
1. 用户:「把售后需求表单的电话字段改成必填」。
2. system prompt 带:核心集可用 + 延迟工具清单(含 `update_apaas_model_field — 改模型字段必填/类型…`)。
3. 模型先调核心读(list_apaas_app_models)摸清 → 再调 `search_tools("改字段 必填 update field")` → 后端激活 `update_apaas_model_field` 等,返回「已加载」。
4. 下一轮 `tools` 含 `update_apaas_model_field` 完整 schema → 模型调它(app_id 护栏注入照旧)→ 改完。
5. 全程每轮 `tools` = 核心 ~15 + 已激活那几个,而非 ~85。

## 6. 边界 / 兜底
- 函数调用约束:模型只能调 `tools` 里有的 → 它**必须先 search**;靠清单 + 引导句确保它知道要 search。
- 模型不 search 直接想用延迟工具:它发不出该 call(不在 tools 里);引导句兜。
- 搜不到:返回最接近候选,模型换词再搜。
- 自由态(/ai-chat 无 app 锁):同样三分(browser_* 不排除)。
- 与 app_context 注入(A5)/app_id 护栏(A4)正交,不互相影响。

## 7. 测试
- `search_tools` 关键词命中 + `select:` 精确 + 搜不到返候选。
- 切词打分:`update_apaas_model_field` 能被「改字段 字段 必填(经 search_hint)」搜到。
- active 集从历史重建(种 search_tools 历史 → 重建出 activated)。
- 每轮 tools = core + active:延迟工具搜前不在 tools、搜后下一轮在。
- 核心集恒在(CORE_TOOL_NAMES 全在每轮 tools)。
- token:对比改前后 `payload["tools"]` 大小,延迟生效时显著下降(断言长尾不在)。
- 不回归:app_id 护栏注入、app_context、browser_* 排除仍生效。
- 测试基建:沿用 StaticPool 共享内存库 + monkeypatch(同 recorder/migration 测试)。

## 8. plan 阶段待办
- 查 `agent_step.tool_name` 频次,定 CORE_HOT 名单(~6-10 个)。
- 决定 search_hint 透传路径(改 `tools_for_agent`/schema 加载 vs 单独读 yaml)。
- search_tools 激活如何回传 loop:推荐「loop 解析 search_tools 结果」,确认 execute_tool 不必加参。
- manifest 注入位置与现有 system prompt 拼接顺序(别撑爆、别跟 app_context 冲突)。
