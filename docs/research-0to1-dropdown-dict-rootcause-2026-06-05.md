# 0-1 全量生成「下拉变固定值(选项1/2/3)不绑字典」根因 — 2026-06-05

> 方法: 4 agent 并行剖代码 → 综合 → 3 个怀疑者对抗验证(全部 refute 了初版结论)→ 实测 11 个已生成应用的 config 交叉验证。结论高置信。

## 实测铁证(扫 /tmp/fb_demo.db 11 个应用的 config_preview)

| 应用 | requirement_doc | models | forms | 下拉 | **组件带dict引用** | 字典定义/被引用 |
|---|---|---|---|---|---|---|
| app10 电池护照 | 单次解析 | 8 | 8 | 12 | **12/12 ✓** | 8/8 |
| app8 研发实验室 | 单次解析 | 9 | 9 | 10 | **10/10 ✓** | 9/9 |
| app6 报销 | 单次解析 | 7 | 6 | 11 | **11/11 ✓** | 6/6 |
| app4 CRM | 单次解析 | 6 | 6 | 12 | **12/12 ✓** | — |
| **app5 易景QMS** | **54081 字 → 分块** | **79** | **38** | **88** | **0/88 ✗** | **10 定义 / 0 被引用** |

- **不是随机某几个下拉, 是按「整次生成」失败, 强相关于规模/文档长度。** app5(54K 字需求文档 → 超 12K → `_parse_chunked`)88 个下拉全军覆没; 字典 10 个明明定义好(带选项), 但**没有任何字段/组件引用它们**(孤儿)。
- ⚠️**关键纠正(实测推翻了纯代码推理)**: app5 和 app10 的**模型字段 `field.dict` 都是空的**(下拉链接不挂在 model field 上)。下拉→字典的链接挂在**表单组件 `component.dict`/`dictCode`** 上 —— app10 组件有(12/12), app5 组件没有(0/88)。

## 根因(确定性, 只在特定 spec 形状/规模触发, 所以看着像"偶尔")

**大需求文档(>12000 字, `ai_doc_parser.py:30 CHUNK_CHAR_LIMIT`)走 `_parse_chunked`(575-623): 按 section 切块, 每块独立 LLM 调用(temp=0.2, 并发3), 然后 `all_models/all_dicts.extend` 盲合并, 没有跨块校验"每个下拉字段都解析到一个已定义字典"。** 结果: 表单组件出来时**没带 `dict`/`dictCode`**(下拉↔字典的关联在分块里丢了), 即便字典被定义了。→ 每个下拉都是孤儿 → apaas 给默认 选项1/2/3。

- 小文档走单次解析(看到整篇)→ 组件正确带上 dict 引用 → 下拉全绑。这就是"对话路径/小应用正常、0-1 多表单大应用偶尔坏"。
- 全局兜底 `_infer_inline_dicts_from_markdown`(ai_doc_parser.py:223/825-871)本可补救, 但只在"字段被识别成下拉 且 内联选项≥2"时才触发, 覆盖太窄, 漏掉。
- **没有安全网**: `config_validator.py:309-317` 明明**检测**到"下拉无 dict"和"dict 引用不存在", 但只 `warnings.append` → logger.info 前10条 → 不修、不拦、不 gate(`ai_doc_parser.py:241-245` / `doc_pipeline.py:216-219` 把 warnings 丢掉)。生成照样"宣布完成"。
- `generator_v2.py:1658 if dicts and form_ids:` —— data.dicts 空时整段 rebind 跳过。
- 我上次的修复 `_collect_spec_component_dict_map` 读的是 `component.dict` —— 大应用这里是空的, 所以救不了(它修的是"组件有 dict 引用但字典名≠字段label"的小应用场景, 那个仍然有效)。

## 对照: 为什么对话路径(build_apaas_feature_from_spec)从不偶尔漏

`mcp_server.py:6429-6439` 硬门 `SELECT_FIELD_NEEDS_DICTIONARY`(下拉没字典直接报错不让建)+ 6463 用 `field.code+'_dict'` **确定性 code** 从字段自带 dict_options 建字典 + 6541-6564 建时**直写** `component.dictionarySelectConfig.dictionaryCode`(按字段 code 不按名)。全程不靠事后名字匹配, 不分块, 所以不会偶尔漏。

## 对抗验证记录(为什么结论可信)

初版综合(rank1)把锅扣在 `generator_v2.py:636 _build_form_components_from_definition` 丢 dictCode + "LLM 把字典名起得跟字段label 不一样的命中概率"。**3 个怀疑者各自读码独立 refute**: rebind 还有 `_collect_label_dict_map`(1016-1030)按 `field.dict`→字段label 的确定性路径, 不靠命名巧合。**但我的实测又进一步纠正怀疑者**: field.dict 在好坏应用里都空 —— 真正的载体是 `component.dict`, 大文档分块解析把它丢了(rank2 才是真因)。三方收敛到: **分块解析丢组件 dict 引用 = 确定性代码缺口, 大应用必中。**

## 修复方向(按优先级, 待与用户确认是否动手)

1. **解析层确定性兜底(最高杠杆, 对齐对话路径)**: parse/assemble 后跑一道 reconciliation —— 每个下拉字段/组件必须解析到 data.dicts 里一个已定义字典; 没有就用字段内联选项**自动建字典**(确定性 code, 仿 `field.code+'_dict'`)并回填 `component.dict`。**对分块路径也要跑**(目前 `_infer_inline_dicts` 覆盖太窄)。
2. **校验器从"软警告"升成"自动修 或 硬门"**: `config_validator.py:310-317` 已经检测出来了 —— 接到自动建字典 / 或像对话路径一样 raise 拦住, 别再把 warnings 丢掉。
3. **分块解析补跨块调和**: `_parse_chunked` 合并后, 给每块喂一个共享的"字典 code 注册表"(总览 pass 产出), 或合并后强制每个 field.dict/component.dict 对到已定义字典。
4. (防御纵深)`generator_v2.py:636` 把 `comp.dictCode/dict` 透传到 built; rebind 优先按字段 code 而非 label 字符串。

## 下一步建议(用户给的「脚本回放」可复现)

- 用脚本回放跑一个 **>12K 字需求文档的多表单应用**(强制分块), 看下拉是不是落 选项1/2/3、哪些漏每次都变 —— 复现确认后再按方向1+2 修(TDD: 先写"分块后每个下拉都解析到已建字典"的失败用例)。

---

## 复现 + 修复已落地(2026-06-05)

**复现**: `parse_document`(纯代码标准解析)对 app5 的 54K 文档直接 DocNotStandardError → 确认走 AI 降级 → `_parse_chunked`。实跑 app5 真文档(266s)再次坏(且每次坏法不同: 这次"段1解析失败"+0字典,坐实非确定性)。

**两种坏法**:
- 模式 A 真下拉丢字典链接(分块跨块丢)；
- 模式 B 文档里本是「单行输入」无选项的字段, 被 LLM 按"状态/类型→下拉"规则误升级成下拉, 无字典无选项 → 选项1/2/3。app5: A≈17, B≈71。

**修复(`ai_doc_parser.py`)**: 解析后 `_reconcile_dropdown_dicts_with_llm` 三步 ——
①确定性 `label==字典名` 直连; ②残余 `_relink_dropdowns_via_llm`(LLM 语义把"标准分类"连到"标准类型"字典, 只接受解析到已定义字典的映射, 防乱绑); ③仍连不上的 `downgrade_unbindable_dropdowns` 一律降级单行输入(用户决策 A, 消除空下拉 + 合文档原意)。接在 `parse_doc_with_ai` 的 derive_default_forms 之后, 失败不阻断。

**验证**: app5 真 config 跑全流程 → 17 真下拉连上字典 / 71 假下拉降级单行输入 / **残留空下拉 0**。单测 `tests/test_dropdown_dict_reconcile.py`(7 个)。全量 6 败=预存, 0 新增。

**遗留(可选)**: ① 上游防丢(分块给每块喂共享字典 registry, 减少 A 类丢失/对 LLM relink 的依赖)—— DETAIL prompt 现已要求下拉建字典, 但大文档 LLM 不稳; 鉴于②+降级已消除症状, ① 为可选优化。
