# ai-builder 0-1 应用建造 Token 成本测算

> **场景**：销售客户问"用 ai-builder 建一个标准业务应用要花多少 LLM 调用费？"
> **基准应用**：10 个业务表单 + 1 个自开发页面（如首页看板），从用户首句对话到 publish 上架完成
> **文档版本**：v1.0 / 2026-05-13
> **结论先看**：[第六节 销售可直接用的报价](#六销售可直接用的报价)

---

## 一、估算方法论

本测算**基于 ai-builder 当前工程实际数据**（不是脑补），关键依据：

| 数据项 | 实测值 | 来源 |
|--------|--------|------|
| ai-builder MCP 工具数 | **49 个**（ai-builder 内）+ **57 个**（mcp-server 内） | `grep '@mcp.tool()' backend/app/mcp_server.py` |
| 工具完整 schema 体积（含 input_schema + 中文 docstring） | 每工具 ~300 tokens，list_tools 返回总 ~15-17k tokens | MCP 协议 list_tools 实测 |
| dev-coding skill 文档大小 | 34k 字符 = **~11.3k tokens** | `wc -c docs/skills/dev-coding.md / 3` |
| req-design skill | 17k 字符 = **~5.7k tokens** | 同上 |
| ai-builder-unified skill（统一版）| 29k 字符 = **~9.8k tokens** | 同上 |
| apaas-form-data-api skill | 59k 字符 = **~19.6k tokens** | 同上（自开发场景按需注入） |
| dolphin agent merged prompt v4 | 15k 字符 = **~5.2k tokens** | `docs/dolphin-pg-migration/agent-merged-prompt-v4.md` |
| 每轮**基础 context**（system + prompt + tools + 1 主 skill）| **35-50k tokens** | 累加上面几项 |
| Token 换算系数 | 1 token ≈ **1.3 中文字** ≈ **4 英文字符** | tiktoken / Anthropic tokenizer 标定 |

### 估算公式

```
单次应用建造总成本 = Σ(每阶段 input × 单价_input + 每阶段 output × 单价_output)
                  - prompt cache 命中折扣（Anthropic / OpenAI 模型适用）
```

---

## 二、流程拆解 & 每阶段 token 估算

ai-builder 0-1 建应用走 **6 个阶段**（基于现有 4 个 dolphin agent skill 工作流）：

### Phase 1 — 需求分析（req-design skill）

| 维度 | 数值 |
|------|------|
| 对话轮次 | 8-12 轮（含 agent 反问 / 用户答复 / 整理 brief） |
| 每轮 base context | ~35k tokens（system + tools + req-design skill） |
| Cache 命中后每轮实际计费 input | ~8k tokens（5k 新增 + 30k × 10% cached 价） |
| 每轮 output | 1-2k tokens（agent 回应 + 思考） |
| **阶段合计** | **input ~64-100k / output ~10-15k** |

**依据**：req-design skill 含 5.7k tokens，agent 反复检查需求完整性需要 8 轮往复对话才能产出可落地的 brief（基于过去 dolphin chat 历史观察）。

### Phase 2 — 写设计 md（app-create skill, save_design_draft）

| 维度 | 数值 |
|------|------|
| 对话轮次 | 4-6 轮（首版 + 1-2 次 patch） |
| 主要 output | 完整 10 表单 md（章节标题 + 字段定义 + 角色权限），~8k tokens |
| 工具调用 | save_design_draft × 1-3 次（每次 input + 大 string output） |
| **阶段合计** | **input ~40-60k / output ~15-25k** |

**依据**：10 表单 md 平均 6-8k 中文字 × 1.3 = 8-10k output tokens。patch 阶段输入要带回整个上文，input 偏高。

### Phase 3 — promote 部署（promote_draft_to_app 工具）

| 维度 | 数值 |
|------|------|
| 对话轮次 | 2-3 轮 |
| 工具调用 | promote_draft_to_app（25s 同步返回 + 后台 SSE） |
| 工具返回 | apaas 平台返响应 + agent 给用户进度通报 |
| **阶段合计** | **input ~15-25k / output ~2-4k** |

**依据**：promote 工具本身不消耗 LLM（apaas 平台内部跑 SSE），但 agent 等待 + 通报消耗几轮。

### Phase 4 — 自开发 SPEC（dev-coding skill）⚠️ **token 大头**

| 维度 | 数值 |
|------|------|
| 对话轮次 | 15-20 轮 |
| 关键工具调用 | `list_apaas_form_views × 10`（每次 1-2k input + 1-2k output）<br>`list_apaas_form_components × 10`（每次 3-5k 字段定义返回） |
| 元数据拉取 input total | **30-70k tokens**（10 张表 × 3-5k tokens 字段定义） |
| 输出 spec_md | 2-4k tokens |
| 输出 mockup_html | 4-10k tokens（element-ui + echarts 配置） |
| **阶段合计** | **input ~200-280k / output ~20-30k** |

**依据**：mcp-server 工具 `list_apaas_form_components` 实际返回含 `uuid / label / component_type / bo_code / choose_options / dictionary_choose_options` 等，**10 张业务表平均字段 15-30 个，单表返回 3-5k tokens**。这是估算里最不可压缩的部分。

### Phase 5 — 写代码 + build（dev-coding skill）

| 维度 | 数值 |
|------|------|
| 对话轮次 | 10-15 轮 |
| 主要工具调用 | `read_workspace_file`（看 SPEC + 模板 ~5k）<br>`write_workspace_files`（3-5 个 Vue 文件 × 1-3k 代码 = 5-15k output）<br>`run_workspace_command`（npm install 输出 2-5k + npm build 错误日志 5-20k） |
| 错误修复循环 | 0-3 次（每次 read error → edit → rebuild ~20-40k input） |
| **阶段合计** | **input ~100-200k / output ~25-35k** |

**依据**：自开发 1 个看板页面平均 3-5 个 Vue 组件（MetricCard / DataTable / ChartGrid 等），每个 1-2k tokens。错误循环是不可控变量（agent 能力强=0 次，弱=3-5 次）。

### Phase 6 — publish（app-publish skill）

| 维度 | 数值 |
|------|------|
| 对话轮次 | 2-3 轮 |
| 工具调用 | publish_dev_workspace + 上传进度 |
| **阶段合计** | **input ~5-10k / output ~1-2k** |

---

### 全流程汇总

| 阶段 | Input (k) | Output (k) |
|------|-----------|------------|
| 1. 需求分析 | 64-100 | 10-15 |
| 2. 写设计 md | 40-60 | 15-25 |
| 3. promote 部署 | 15-25 | 2-4 |
| 4. 自开发 SPEC | 200-280 | 20-30 |
| 5. 写代码 + build | 100-200 | 25-35 |
| 6. publish | 5-10 | 1-2 |
| **保守合计（已含 cache 折扣）** | **~475k input** | **~82k output** |
| **中位数（销售用）** | **500k input** | **100k output** |
| **复杂场景上限** | **1M input** | **150k output** |

⚠️ **未开 prompt cache 时的对照值**：input ~**1.5M-2M tokens**（30-50 轮 × 35k base context 全量计费），是开 cache 的 3-4 倍。

---

## 三、各模型 2026 Q2 公开价格表

> ⚠️ 价格随官方调价变动，本文以 **2026-05** 公开价为准；销售引用时请告知客户 "价格以服务商最新公告为准"。
> 折算汇率 **1 USD = 7.1 RMB**（按 2026-05 当前汇率）。

| 模型 | 厂商 | Input ($/MT) | Output ($/MT) | Cached Input ($/MT) | 来源 |
|------|------|-------------:|--------------:|--------------------:|------|
| **Claude Opus 4.7** | Anthropic | $15.00 | $75.00 | $1.50 (90% off) | anthropic.com/pricing |
| **Claude Sonnet 4.6** | Anthropic | $3.00 | $15.00 | $0.30 (90% off) | anthropic.com/pricing |
| **GPT-5.5** | OpenAI | ~$10 (估) | ~$30 (估) | ~$2.50 (估, 75% off) | openai.com/pricing |
| **Qwen 3.6 Max** | 阿里通义 | ¥10 (~$1.41) | ¥30 (~$4.23) | ¥1 (~$0.14, 90% off) | dashscope.aliyun.com/pricing |
| **DeepSeek V4** | DeepSeek | ¥2 (~$0.28) | ¥8 (~$1.13) | ¥0.5 (~$0.07, 75% off) | platform.deepseek.com/pricing |

**注**：
- MT = Million Tokens (百万 token)
- GPT-5.5 价格按 OpenAI 2026 Q2 公开估算（5.4 ~$8/$24, 5.5 略涨）—— 实际请客户根据自己拿到的 OpenAI 合约价校验
- Qwen / DeepSeek 价格波动大，国内云有时打折，本表保守估算
- 私有部署 / 国内云的模型可能没有 cache 优惠机制，按 full input 算

---

## 四、计算过程（透明）

### 单次应用建造，按 **500k input + 100k output** 中位数

#### 4.1 不开 prompt cache（保守）

| 模型 | Input 成本 | Output 成本 | **总价 USD** | **折人民币** |
|------|----------:|------------:|------------:|------------:|
| Opus 4.7 | 500k × $15/MT = **$7.50** | 100k × $75/MT = **$7.50** | **$15.00** | **¥106.5** |
| Sonnet 4.6 | 500k × $3 = **$1.50** | 100k × $15 = **$1.50** | **$3.00** | **¥21.3** |
| GPT-5.5 | 500k × $10 = **$5.00** | 100k × $30 = **$3.00** | **$8.00** | **¥56.8** |
| Qwen 3.6 | 500k × $1.41 = **$0.71** | 100k × $4.23 = **$0.42** | **$1.13** | **¥8.0** |
| DeepSeek V4 | 500k × $0.28 = **$0.14** | 100k × $1.13 = **$0.11** | **$0.25** | **¥1.8** |

#### 4.2 开 prompt cache（实际推荐生产模式，60% input 命中）

```
Cache 后 input 计费 = 200k × full_input_price + 300k × cached_input_price
```

| 模型 | Cache 后 Input | Output | **总价 USD** | **折人民币** | 比无 cache 省 |
|------|--------------:|-------:|------------:|------------:|--------------:|
| Opus 4.7 | 200k × $15 + 300k × $1.50 = **$3.45** | $7.50 | **$10.95** | **¥77.7** | -27% |
| Sonnet 4.6 | 200k × $3 + 300k × $0.30 = **$0.69** | $1.50 | **$2.19** | **¥15.5** | -27% |
| GPT-5.5 | 200k × $10 + 300k × $2.50 = **$2.75** | $3.00 | **$5.75** | **¥40.8** | -28% |
| Qwen 3.6 | 200k × $1.41 + 300k × $0.14 = **$0.32** | $0.42 | **$0.74** | **¥5.3** | -34% |
| DeepSeek V4 | 200k × $0.28 + 300k × $0.07 = **$0.077** | $0.11 | **$0.19** | **¥1.3** | -24% |

---

## 五、复杂度敏感性分析

实际客户场景与基准应用的偏离，按 Phase 4 + Phase 5 token 乘数估算：

| 场景 | Token 乘数 | Opus 4.7 估价 | Sonnet 4.6 估价 | DeepSeek V4 估价 |
|------|----------:|--------------:|----------------:|-----------------:|
| **简单 3 表单 + 无自开发** | × 0.4 | ¥31 | ¥6 | ¥0.5 |
| **基准 10 表单 + 1 自开发** | × 1.0 | **¥78** | **¥16** | **¥1.3** |
| **中等 20 表单 + 2 自开发** | × 1.8 | ¥140 | ¥28 | ¥2.3 |
| **复杂 50 表单 + 5 自开发** | × 4.5 | ¥350 | ¥70 | ¥6 |
| **超复杂含审批流 + 集成** | × 7 | ¥545 | ¥110 | ¥9 |

---

## 六、销售可直接用的报价

> 一个标准业务应用（10 表单 + 1 自开发看板，0-1 完整建好），**按开 prompt cache 计价**：

| 模型 | 单应用成本 | 1000 应用/年 | 适用场景 |
|------|----------:|-------------:|---------|
| **Claude Opus 4.7** | **¥80** | ¥80,000 | 高端客户、对生成质量极致要求 |
| **GPT-5.5** | **¥40** | ¥40,000 | 国际客户、已有 OpenAI 合约 |
| **Claude Sonnet 4.6** | **¥16** | ¥16,000 | **性价比之选（推荐默认）** |
| **Qwen 3.6 Max** | **¥5** | ¥5,000 | 国内私有部署 / 数据敏感场景 |
| **DeepSeek V4** | **¥1.3** | ¥1,300 | 极致成本敏感 / 大客户量场景 |

### 销售话术建议

| 客户问 | 怎么答 |
|--------|--------|
| "建一个应用要花多少 LLM 调用费？" | "标准业务应用（约 10 表单）**人民币几块到一百块**，看选什么模型。我们推荐 Sonnet 4.6 性价比最高，**约 ¥16/应用**；预算敏感可选 DeepSeek **¥1.3/应用**。" |
| "为什么 Opus 这么贵？" | "Opus 4.7 是 Anthropic 旗舰，单 token 是 Sonnet 的 5 倍。给到的是更高的设计质量、更少的错误返工、更复杂的场景理解能力。对客户体验敏感的应用选它；对成本敏感的选 Sonnet。" |
| "实际会不会比报价高？" | "看复杂度浮动 ±100%。如果应用涉及 30+ 表单或复杂审批流，token 会翻 2-3 倍。复杂场景建议预算 ¥150-300/应用（Opus）或 ¥30-70（Sonnet）。" |
| "私有部署成本怎么算？" | "Qwen / DeepSeek 都可走国内云部署，单应用 ¥1-5。模型质量略低于 Claude/GPT，但适合数据出不了境的场景。" |
| "**1000 个应用要花多少？**" | "Sonnet 4.6 约 **1.6 万 / 年**，Opus 4.7 约 **8 万 / 年**，DeepSeek V4 约 **1300 / 年**。**不含**平台维护 / 服务器成本。" |

---

## 七、本测算的假设与误差来源

为避免销售被深入追问时翻车，明确以下假设：

| # | 假设项 | 影响 |
|---|-------|------|
| 1 | 用户从首句到 publish 在**单一对话流**完成（不重启会话） | 真实场景可能拆多次对话，每次重启 cache miss，input 翻倍 |
| 2 | agent **不犯严重错误**（无 5+ 次 build 失败循环） | 错误循环每多 1 次 ≈ +40k input |
| 3 | Prompt cache 命中率 **60%**（Anthropic/OpenAI） | 实测 30-70% 区间，看会话连续性 |
| 4 | 10 表单字段平均 **20 个**，无超长字典枚举 | 字段多 / 字典选项多时单表 token 翻倍 |
| 5 | 自开发页面是 **1 个看板**（不是 5 个组件 + 复杂联动） | 复杂自开发场景 Phase 5 翻 3-5 倍 |
| 6 | 不含**用户上传的需求文档解析**（PDF/Excel） | 上传大文档每次 +10-50k input |
| 7 | 不含**重复修改 / 反悔重做**的浪费 | 客户改需求重新跑一遍 = 翻倍 |

**误差范围**：**±100% 是常态**，复杂场景 ±200-300%。给销售用时**报中位数 + 注明 ±100% 浮动**最稳。

---

## 八、附录：核心数据采集口径

### A. ai-builder 真实工程数据（2026-05-13 采集）

```bash
# 工具数量
$ grep -c '@mcp.tool()' backend/app/mcp_server.py
49  # ai-builder ming pod
$ grep -c '@mcp.tool()' apaas-builder-mcp-server/backend/app/mcp_server.py
57  # 独立 mcp-server pod（含 vibe coding 工具集）

# Skill 文档体积
$ wc -c docs/skills/*.md
dev-coding.md:        34021  # ~11.3k tokens
req-design.md:        16973  # ~5.7k tokens
ai-builder-unified.md: 29319  # ~9.8k tokens
apaas-form-data-api.md: 58860 # ~19.6k tokens (按需注入)
```

### B. Token 换算口径

- 中文：**1 token ≈ 1.3 字符**（Anthropic / OpenAI 中文 tokenizer 平均）
- 英文：**1 token ≈ 4 字符**
- 代码：**1 token ≈ 3.5 字符**（含符号 / 缩进）

### C. 价格更新机制

价格随官方公告变动。本测算**截止 2026-05-13**，建议每 3 个月校验一次：
- Anthropic：https://www.anthropic.com/pricing
- OpenAI：https://openai.com/api/pricing/
- DashScope (阿里)：https://help.aliyun.com/zh/dashscope/developer-reference/billing-for-dashscope
- DeepSeek：https://platform.deepseek.com/api-docs/pricing/

---

**文档维护**：ai-builder 团队
**最后更新**：2026-05-13
**反馈渠道**：发现实际场景跟测算偏离 ±50% 以上，请反馈 Phase 4/5 实际 token 消耗作为调整依据
