# 平台知识库(规范库)设计 — 2026-06-26

## 背景与问题

得小帆(ai-builder)的 agent 在做「搭建 / 二次开发」时,所依赖的规范、约定、领域规则散落在三处:agent 的 system prompt、代码常量、DB 里的 agent prompt。调整一次规范就要改代码 + 发版(甚至跑 `refresh_coding_prompts.py` 刷库 + 重启进程),很重。

已知的具体窟窿:二次开发时 agent 不知道 definesys 写侧 SDK 的真实 API,只能瞎猜方法名(见 `docs/research-apaas-event-python-spec-2026-06-05.md`);搭建/字段口径等约定也只能硬编码进提示词。

**目标**:把「搭建 / 二次开发」这类规范从 prompt/代码里搬到一个可在线编辑的平台知识库。改规范 = 改知识库,下一次 agent 跑就生效,不改代码、不发版、不刷库。

## 方向与范围(已与用户确认)

- **方向 A**:知识库服务于「配置/开发 agent」,不是终端用户问答库。
- **治理**:平台级单库,全局共享;**写权限只给平台管理员**(团队统一维护),租户/个人只读、不能改。
- **机制**:wiki 式 markdown 文档(渐进披露)+ 关键词/全文检索;**不走向量化**(方案 2)。
- **内容 vs 机制的线**:知识库只装「内容」(规范/约定/领域规则);agent 接线(工具循环、输出格式、权限 payload、安全护栏)留在代码。非工程的人改知识库不应能改坏 agent。

### 非目标(YAGNI)

- 不做向量化 RAG(语料是策展过的有限规范库,几十到上百篇;向量化是过度设计,且切碎规范会让 agent 断章取义误用)。
- 不做租户级覆盖(C 方案):平台默认 + 租户覆盖,等平台级稳了再说。数据模型留 `tenant_id` 列做头部空间,但本期只读写 `NULL`(=全局)。
- 不做 git/PR 版本流(那恰恰还是发版,违背诉求)。
- 不做终端用户问答入口(原 C 方案,另一个用户群)。
- 不接旧 `/coding/pipeline` 引擎(退役中,见「配套清理」)。

## 引擎拓扑(关键:wire-once)

经代码核实,「搭建 / 二次开发 / config 助手」**现在是同一个引擎**:

- `run_agent`(`backend/app/ai_chat/agent.py`)是唯一活跃入口,全仓只在 `backend/app/routes/ai_chat.py:801` 被调。
- 引擎对场景无知,场景 = 一份 `AgentProfile`(`backend/app/agents/profile.py`):默认 = 通用 Builder/配置;`session.mode='code'` → `dev-apaas` profile(换提示词 + 收窄工具集)。背后有统一引擎 spec `docs/superpowers/specs/2026-06-24-unified-agent-engine-design.md`。
- 前端已收口:code 会话路由到 `/ai-chat`(不再走独立 `/coding`)。

**结论**:知识库接进 `run_agent` 一处,Builder + config 助手 + 二次开发(Code)三个场景自动全覆盖。无需按 profile 各接一遍。

## 数据模型

新增 ORM 模型 `backend/app/models/knowledge_doc.py`,类 `KnowledgeDoc`,表 `knowledge_docs`。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int PK | |
| `slug` | String(160) | 唯一,稳定标识;agent 按它 `read_knowledge(slug)` |
| `title` | String(200) | 标题(进目录) |
| `summary` | String(500) | 一句话摘要(进目录,渐进披露靠它) |
| `category` | String(60) | `搭建` / `二次开发` / `平台规范` …(自由字符串,前端给常用枚举) |
| `tags` | String(500) | 逗号分隔,可空 |
| `body_md` | `BigText`(Text→LONGTEXT@mysql) | 文档正文 markdown |
| `status` | String(20) | `draft` / `published`;**只 `published` 进 agent** |
| `tenant_id` | int nullable | **预留**:`NULL`=平台全局;本期恒为 `NULL`。留列避免后续 MySQL `ALTER`(本项目用 `create_all`,加列不会自动迁移) |
| `updated_by` | int nullable | 最后编辑的平台管理员 user_id(审计) |
| `created_at` / `updated_at` | DateTime | |

设计要点:
- 正文里用 `[[slug]]` 软互链(像 skills/memory),**不做硬 FK 树** —— wiki 的「感觉」靠互链与 category 分组,不靠数据库层级。
- `BigText = Text().with_variant(LONGTEXT, "mysql")`,沿用 `config_assistant_skill.py` 范式。
- **必须**在 `backend/app/models/__init__.py` 注册导入(`from app.models.knowledge_doc import KnowledgeDoc  # noqa`),否则 ORM 映射/`create_all` 漏表(历史踩过 SpecSection 漏注册的坑)。
- `slug` 唯一约束:String(160),MySQL `utf8mb4` 下 160×4=640 字节 < 3072,普通唯一索引安全(不会重蹈 registered_workspaces 超长索引上线崩的覆辙)。仍需 docker mysql:8 验 `create_all`。

### 为什么存 DB 不存文件系统

平台是 web 服务 + MySQL;k8s pod 上的文件不持久、不跨副本共享。只有 DB 能做到「线上改完下次即生效」。(skills 用文件系统是因为桌面端有持久 `data_dir`,这里场景不同。)

## 编辑面(管理页)

- app 内新增「知识库」管理页,**仅平台管理员可见**。
- 列表(按 category 分组)+ markdown 编辑器 + `status` 发布开关。
- 后端 CRUD 端点(`backend/app/routes/knowledge.py`,前缀如 `/api/knowledge`):
  - `GET /docs`(列表,可按 category/status/q 过滤)
  - `GET /docs/{slug}`
  - `POST /docs` / `PUT /docs/{slug}` / `DELETE /docs/{slug}`
- **鉴权**:写操作要求平台管理员 —— 复用 `backend/app/deps.py` 的 `is_platform_admin` / `tenant_role=="platform_admin"`(与 agent 可观测同一条权限边界)。读操作(管理页浏览)也限管理员;agent 不经 HTTP,直接查 DB。
- **注意** `get_db` 不 autocommit,写端点必须显式 `await db.commit()`(历史踩坑)。

## agent 消费(渐进披露 + 检索)

### 1. 注入目录(渐进披露)

在 `run_agent` 拼 system prompt 时,把 `published` 文档的「标题 + 摘要」按 category 分组渲染成一段目录,注入 system prompt —— **镜像** `_append_skill_manifest`(`agent.py:76`,在 `agent.py:902` 调用)。新增 `_append_knowledge_manifest(messages)` 紧挨着调用。

清单文案(示意):
```
## 平台知识库
需要某条规范时,先 read_knowledge(slug) 读全文,或 search_knowledge(query) 检索:
[二次开发]
- definesys-event-sdk: definesys 自定义事件写侧 SDK 规范与可用 API
[搭建]
- form-field-conventions: 表单字段口径与命名约定
```
- 只列 `published`、`tenant_id IS NULL`。
- 规模上限:本期全量列(策展库,不会上千)。文档涨到目录撑爆 system prompt 时,降级为「只列 category + 数量」,靠 `search_knowledge` 兜底 —— 列为后续项,非本期。

### 2. 两个工具(镜像 use_skill)

注册到 `backend/app/ai_chat/tools.py`(`TOOL_SCHEMAS` + execute dispatch dict,旁边就是 `use_skill`):

- `read_knowledge(slug: str)` → 返回该 `published` 文档全文(`body_md`)。slug 不存在/未发布 → 明确报错。
- `search_knowledge(query: str)` → 对 `title` / `summary` / `body_md` 做关键词匹配,返回命中文档的 `slug` + `title` + 相关片段(摘要或命中段落)。

**为什么注册在 `ai_chat/tools.py` 就够**:该文件的 `TOOL_SCHEMAS` 进 `_BASE_LOCAL_NAMES` 与 `CORE_TOOL_NAMES`(`tools.py:1252/1260`)。
- `CORE_TOOL_NAMES` → 恒在每轮 tools,不被延迟。
- `_BASE_LOCAL_NAMES` → `run_agent` 的 dev-apaas profile 工具过滤(`agent.py`:`name in _BASE_LOCAL_NAMES or name in _allow`)恒保留 base 本地工具。

故两个工具在「默认 Builder」与「dev-apaas(Code)」两个 profile 下都自动可用,无需改 `profile.py` 的白名单计算。

- 两个工具是**本地工具**(直接查 DB),注册进 `ai_chat/tools.py` 的 `TOOL_SCHEMAS` + `TOOL_HANDLERS` 即可;**不进 `tool_registry.yaml`**(经核实那是 MCP 工具专用,base 本地工具如 `use_skill`/`read_attachment` 都不在其中)。
- 两个工具都是**只读**,无副作用,任何 profile 给都安全。

### 检索实现(可移植,避开 SQLite/MySQL 分裂)

本地 dev = SQLite,线上 = MySQL,两者全文检索语法/中文分词不同(SQLite FTS5 vs MySQL FULLTEXT+ngram)。本期 `search_knowledge` 用**归一化 LIKE 子串/关键词匹配**(对 query 简单切词,逐词 `LIKE %word%` over title+summary+body,按命中字段加权排序)。SQLite 与 MySQL 行为一致,策展库(几十~上百篇)全表扫完全够用。性能真成瓶颈时,再把 MySQL FULLTEXT(ngram 解析器)藏到同一函数后面当可选后端 —— 上层接口不变。

## seed(初始内容)+ 防漂移

- **seed**:把现在散在 prompt / 常量 / DB agent prompt 里的「搭建、二次开发」约定提炼成初始文档入库(优先 definesys 写侧 SDK 规范这类已知窟窿)。**能搬多少要实现时读了代码才算数,不打包票**;plan 阶段先做一次「现有规范盘点」。
- **防漂移**:搬进库的那部分,prompt 里对应段落**留薄 / 删掉**,不要 prompt 和知识库各存一份(两份真相源迟早不一致)。这是「迁移」不是「叠加」。

## 配套清理(独立 spec,紧跟本期)

旧 `/coding/pipeline` 引擎(`backend/app/routes/harness.py:231` + `backend/app/coding/pipeline.py`)是另一套独立引擎,有自己的 manifest 注入(`_coding_skill_manifest_suffix`,`pipeline.py:2202`)和工具(`backend/app/agents/coding/tools.py`)。本期**不接它**。

用户要求把退役代码清理掉。这是一项独立、有风险的删除(与 `coding.py` / `online_coding` / `VibeCodingThread` 缠绕),**单独开一份 spec** 处理,删前先查清:前端 `frontend/src/api/harness.ts` 的 `codingPipelineUrl`、`useCodingPipeline` 等是否还有活引用;`/coding/pipeline` 是否真无人走。遵循「删前先看清目标」。**不并入知识库 PR**(避免大删除污染 review/回滚)。

## 测试

- **模型/迁移**:`create_all` 在 docker mysql:8 上验通(唯一索引长度、LONGTEXT)。
- **CRUD + 鉴权**:平台管理员能 CRUD;非管理员写被拒(403);`commit` 后能读到。
- **工具**:`read_knowledge` 命中/未发布/不存在三态;`search_knowledge` 关键词命中与排序;两者只读不改库。
- **manifest**:只含 `published`、按 category 分组;空库 → 空串(no-op,不污染 prompt)。
- **profile 覆盖**:dev-apaas 与默认 Builder 两个 profile 下,两个工具都出现在装配后的 tools 数组(防被过滤/延迟掉)。
- **端到端**:发布一篇 definesys SDK 文档 → 跑一轮二次开发 → agent 主动 `read_knowledge`/`search_knowledge` 并据此作答(真 LLM,本地 tenant + gpt-5.5 omnigate)。

## 风险 / 待定

- 中文 LIKE 切词的召回质量(本期接受朴素切词;不行再上 FULLTEXT/ngram)。
- 管理页是新页面还是挂在现有「平台管理 / 设置」下 —— plan 阶段定。
- seed 可迁移量未知 —— plan 第一步盘点现有 prompt 规范。
