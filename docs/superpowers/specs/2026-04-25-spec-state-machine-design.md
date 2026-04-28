# SPEC State Machine — Design Spec

**Date**: 2026-04-25
**Status**: Approved (brainstorm), pending implementation plan
**Owner**: Mars

---

## 1. 背景与诊断

### 1.1 用户感受到的问题（截图证据）

用户在 `localhost:5173/ai-builder/chat/475` 输入 27 字需求「我想做一个预算管理系统，根据老项目backlog+新商机转化进行季度收入预测」，AI 直接输出 markdown 散文式分析（"## 系统核心模型 / 系统的核心逻辑是…" / "让我先创建项目结构"），**右侧 SPEC 面板始终空白**，PhaseBar 卡在「理解需求」。

### 1.2 根因（已通过代码验证，按严重度排序）

**P0-1：PhaseBar 5 阶段是装饰，不是状态机。**
[ChatPage.vue:1187-1208](frontend/src/views/ChatPage.vue:1187) 的 `builderPhaseSteps` 完全是前端被动推断（"LLM 已经吐出 markdown 文档了"=理解需求 done）。后端 [chat.py:629/787/858/970](backend/app/routes/chat.py:629) 写 `conversation.phase = "refining"` 但 `_build_phase_prompt` 不读这个字段，是死代码。

**P0-2：「需求理解」+「SPEC 设计」是同一个 prompt 一把梭。**
[REQUIREMENTS_SYSTEM_PROMPT](backend/app/routes/chat.py:310) 同时管"每次只问一个问题"和"信息够了就生成设计文档"，由 LLM 自己判断切换时机。强模型（opus 4.6）训练偏好"先想完整框架再问细节"，所以一上来就跳过澄清出散文。

**P0-3：SPEC 是 markdown 字符串，不是结构化对象。**
当前数据流：对话 → markdown blob → `<!-- DESIGN_COMPLETE -->` 锚点 → 用户确认 → `<!-- TRIGGER_BUILD -->` 锚点 → `triggerFullBuildPipeline()` → `doc_pipeline.parse_document(markdown)` → JSON config。后果：完成度算不出来、字段级 patch 做不了、markdown↔JSON round-trip 丢精度（[project_current_state.md](memory/project_current_state.md) 待办 #5 就是这个症状）。

**P1-1：右侧 SPEC 面板 placeholder 章节（业务目标/功能模块/数据模型/权限矩阵）跟实际 config 输出（roles/dicts/models/forms/permissions）不对齐。**

**P1-2：REQUIREMENTS prompt 对强模型的"每次只问一个问题"是软约束，opus 4.6 不服从。**

**P1-3：「我帮你设计…」散文反 SPEC-driven UX。** 用户期待"问→答→问→答"节奏，AI 给"思考过程展示"。

**根因总结**：三层同一个根因 — **缺一个真正的 SPEC 状态机**。
| 层 | 现状 | 应有 |
|---|---|---|
| 数据 | markdown blob | 结构化 SPEC 对象 |
| 流程 | 1 prompt 自判断 | 多 phase prompt 链 |
| 交互 | PhaseBar 装饰 | PhaseBar 反映 SPEC 对象 status，可点击 |

---

## 2. 设计决策（已对齐）

| # | 决策 | 选择 | 理由 |
|---|---|---|---|
| 1 | 成功标准 | a+b+c 全要：澄清扎实 + 完成度可见 + 增量精度 | 设计稿 Inspector / 三栏布局都依赖此底座 |
| 2 | 覆盖入口 | 1 chat 多轮 + 2 文档上传 + 3 截图 + 5 已部署对话增量 + 6 已部署文档 V1→V2（不含 4 平台导入） | 4 远端只有技术 config 没业务上下文，强加只会出垃圾 SPEC |
| 3 | 数据形态 | X′ — 结构化 JSON 主，markdown 仅 derived 导出 | 完成度计算+字段级 patch 只能在结构化对象上做 |
| 4 | phase 拆分 | P3 — gathering / drafting / generating，允许回退/跳跃 | 跟现有 PhaseBar 完美对齐，UI 0 改动；三段对应三个 prompt |
| 5 | LLM ↔ SPEC 协议 | T — Tool calling | atomic op、可验证、字段级精度；omnigate 已支持（vibe_agent 在用） |

---

## 3. 总架构

### 3.1 数据流

```
┌─────────────────┐                    ┌──────────────────────────┐
│   ChatPage UI   │                    │    后端 spec_engine      │
│ ─────────────── │                    │ ──────────────────────── │
│ Composer (聊天) │ ──→ /chat/send ──→ │ SpecAgent                │
│ Canvas (SPEC 卡)│ ←─ tool result ─── │  ├─ phase 路由           │
│ Inspector       │ ←─ spec patch ──── │  ├─ tool 执行            │
│ PhaseBar (主动) │ ──→ /spec/phase ─→ │  └─ completeness 计算    │
└─────────────────┘                    │ ────────────────────── ↓ │
                                       │ Spec (DB 持久化对象)     │
                                       │ ↓ generate                │
                                       │ spec.converter.spec_to_config│
                                       │ ↓                         │
                                       │ Application.config (现状) │
                                       └──────────────────────────┘
```

### 3.2 模块切分

**新增 backend 模块**（4 个文件）：
- `backend/app/spec/schema.py` — SPEC Pydantic 模型 + completeness rubric + Phase enum
- `backend/app/spec/tools.py` — LLM tool 定义 + tool 执行函数（共 21 个 tool，详见第 5 节）
- `backend/app/spec/agent.py` — SpecAgent：组装 prompt + LLM tool loop + 持久化（参照 [vibe_agent.py](backend/app/coding/vibe_agent.py)）
- `backend/app/spec/converter.py` — `spec_to_config()` 把 ready phase 的 SPEC 转成 Application.config

**改动现有模块**：
- `backend/app/routes/chat.py` — `/send` 路由对 `agent_type == "requirements"` 走 SpecAgent；`/send-with-file` 文档静默生成走 `SpecAgent.bootstrap_from_doc()`
- `backend/app/models/__init__.py` — 新增 Spec 模型；Application 加 `canonical_spec_id`；Conversation 加 `spec_id`
- `backend/app/routes/incremental_update.py` — 增量更新（入口 6）改为 `SpecAgent.bootstrap_from_doc(diff_only=True, base=canonical_spec)`
- `backend/app/config_assembler.py` → 改名 `legacy_config_assembler.py`，新代码禁止 import；老对话 load 时兜底
- `backend/app/doc_pipeline.py` → 保留为 `bootstrap_from_doc` 内部用的"标准度检测 + 章节切分"工具

**前端新增组件**（4 个文件）：
- `frontend/src/components/spec/SpecCanvas.vue` — 中间栏：分块卡片化展示 SPEC，每项 confirm/edit/dismiss
- `frontend/src/components/spec/SpecInspector.vue` — 右栏：completeness、待决策、版本时间线
- `frontend/src/components/PhaseBar.vue` — 抽出现有 ChatPage 内联 phase 条 + "点击切换 phase"
- `frontend/src/api/spec.ts` — SPEC API 封装

**前端改动**：
- `frontend/src/views/ChatPage.vue` — 三栏布局（左 Composer / 中 SpecCanvas / 右 SpecInspector），现有 PreviewPanel 保留为 SpecCanvas 的"技术视图" tab

**保留不动**：
- `backend/app/coding/` 整套
- `backend/app/apaas_client.py` / `platform_sync.py`（入口 4 不收编）

### 3.3 模块依赖

```
routes/chat.py ──→ spec.agent ──→ spec.schema
                       │              ↑
                       ├──→ spec.tools ┤
                       └──→ spec.converter ──→ legacy_config_assembler (fallback)
```

`spec.converter` 是单向（SPEC→config），不双向同步，避免 markdown↔JSON 同步地狱。

---

## 4. 数据模型

### 4.1 SPEC Pydantic 模型（`backend/app/spec/schema.py`）

```python
from enum import Enum
from typing import Literal, Optional
from datetime import datetime
from pydantic import BaseModel, Field

class Phase(str, Enum):
    GATHERING = "gathering"     # AI 问澄清问题，逐项填字段
    DRAFTING = "drafting"       # AI 整理草案，用户逐项确认
    GENERATING = "generating"   # SPEC → config，触发 build
    READY = "ready"             # 已转 config，可迭代

class Decision(BaseModel):
    id: str                          # d_xxx (uuid 短串)
    topic: str                       # "季度起算月"
    why_blocking: Optional[str] = None
    options: list[str] = []          # 候选答案，可空
    blocking: bool = True            # 是否阻塞 phase 转移
    raised_in_phase: Phase
    resolved: bool = False
    resolution: Optional[str] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None

class Goal(BaseModel):
    title: str                       # 应用名
    summary: str                     # 一段话描述
    business_problem: str            # 解决什么业务问题
    confirmed: bool = False

class Role(BaseModel):
    code: str                        # finance_lead
    name: str                        # 财务负责人
    scope: Literal["SELF", "DEPT", "DEPT_LOW", "ALL"]
    description: Optional[str] = None
    confirmed: bool = False

class FieldSpec(BaseModel):
    code: str
    name: str
    type: str                        # 中文 type，如 "单行输入"
    required: bool = False
    dict_code: Optional[str] = None  # 关联字典
    ref_model: Optional[str] = None  # 关联模型
    ref_field: Optional[str] = None
    description: Optional[str] = None
    confirmed: bool = False

class ObjectSpec(BaseModel):         # 业务对象 / 数据模型
    code: str                        # t_quarter_forecast
    name: str                        # 季度预测
    description: Optional[str] = None
    fields: list[FieldSpec] = []
    sub_objects: dict[str, list[FieldSpec]] = {}  # sub_code -> sub_fields
    confirmed: bool = False

class DictOption(BaseModel):
    code: str
    name: str

class DictSpec(BaseModel):
    code: str
    name: str
    options: list[DictOption] = []
    confirmed: bool = False

class PermissionRule(BaseModel):
    role: str                        # role code or "all"
    op: Literal["all", "add", "edit", "delete", "view"]
    data: Literal["ALL", "SELF", "DEPT", "DEPT_LOW"]

class PermissionSpec(BaseModel):
    object_code: str                 # 对哪个 object
    rules: list[PermissionRule] = []
    confirmed: bool = False

class Completeness(BaseModel):       # derived，每次 tool 调用后重算
    confirmed: int                   # 已 confirm 的 item 数
    total: int                       # SPEC 中 item 总数（goal+roles+objects+dicts+permissions）
    by_section: dict[str, tuple[int, int]]  # {"roles": (3, 5), ...}
    pending_decisions: int
    blocking_decisions: int

class Spec(BaseModel):
    id: str                          # spec_xxx (uuid)
    application_id: Optional[int] = None  # 首次对话时 app 未创建，可空
    version: int = 1
    parent_spec_id: Optional[str] = None  # 链式版本
    phase: Phase = Phase.GATHERING
    goal: Optional[Goal] = None
    roles: list[Role] = []
    objects: list[ObjectSpec] = []
    dicts: list[DictSpec] = []
    permissions: list[PermissionSpec] = []
    decisions_pending: list[Decision] = []
    decisions_resolved: list[Decision] = []
    completeness: Completeness
    created_at: datetime
    updated_at: datetime
    created_by: int
```

### 4.2 DB 持久化（D2 + 简易 version）

**新建表 `specs`**（[backend/app/models/spec.py](backend/app/models/spec.py) 新建）：
```python
class Spec(Base):
    __tablename__ = "specs"
    id: str = Column(String(40), primary_key=True)         # "spec_xxx"
    application_id: int | None = Column(Integer, ForeignKey("applications.id"), nullable=True)
    version: int = Column(Integer, default=1)
    parent_spec_id: str | None = Column(String(40), ForeignKey("specs.id"), nullable=True)
    payload: dict = Column(JSON)                           # 整个 Pydantic Spec 序列化
    phase: str = Column(String(20))                        # 冗余，给 list 查询
    completeness_confirmed: int = Column(Integer, default=0)  # 冗余
    completeness_total: int = Column(Integer, default=0)      # 冗余
    created_at, updated_at
    created_by: int = Column(Integer, ForeignKey("users.id"))
    tenant_id: int = Column(Integer)
```

**Application 加字段**：
```python
canonical_spec_id: str | None = Column(String(40), ForeignKey("specs.id"), nullable=True)
```

**Conversation 加字段**：
```python
spec_id: str | None = Column(String(40), ForeignKey("specs.id"), nullable=True)
# current_config 字段保留，老对话兜底用
```

**版本化策略**：
- 每次 `transition_to_generating` 时**不**新建 spec 行，原 spec 直接 `phase: generating → ready`
- 用户在 ready phase 做重大修改（drafting 回退或入口 5/6 增量）时新建 spec，`parent_spec_id` 指向旧版，`version+=1`
- UI 时间线读 `parent_spec_id` 链

### 4.3 confirmed 状态归属

**默认用户确认**为主，AI 写入默认 `confirmed=false`。例外表：

| 场景 | confirmed 默认值 | 原因 |
|---|---|---|
| AI tool 写入（chat 多轮） | `false` | 用户主导 |
| 用户在 SpecCanvas 卡片点"确认" | `true` | 显式确认 |
| 用户上传成熟文档（标准度 ≥60）走 silent | **全 true** | 用户上传即认 |
| 用户对话明确说"加一个销售总监角色" | `true` | LLM 通过 `add_role(confirmed=true)` 调用 |
| 用户驳回 | 该项删除（不是改 false） | 物理删除避免脏数据 |

**Tool 强制语义**：
- `add_*` / `update_*` tool 默认 `confirmed=false`
- `confirm_*` / `dismiss_*` tool 必须由 LLM 在用户表达"确认/OK/没问题"等意图后调用
- 这一约束写在 prompt 里（不是代码层强制，因为"用户意图"难以精确判断）

### 4.4 老数据迁移策略

**不回填**。老 application 保持 `canonical_spec_id IS NULL`，迭代时如果用户从 chat 入口进来，给一次性提示：
> 「此应用是旧版创建，是否升级到 SPEC 模式？升级会以当前 config 反推一份 SPEC 草案让你逐项确认。」

用户确认后用 `spec_engine.bootstrap_from_legacy_config(app.config)` 反推。三个月观察期后再决定是否批量回填。

---

## 5. Tool 集

按 phase 分组，每个 tool 都是 atomic op。详细 schema 在 `backend/app/spec/tools.py` 的 OpenAI tool definition 格式。

总数：4 通用 + 7 写入 + 5 confirm + 5 dismiss = **21 个 tool**。`confirm_*` / `dismiss_*` 按 5 类 entity（role/object/field/dict/permission）展开。

| 阶段 | Tool | 用途 | confirmed 默认 |
|---|---|---|---|
| **任意** | `ask_clarifying_question(topic, why_blocking, options[])` | 提澄清问题 → `decisions_pending` | n/a |
| | `set_goal(title, summary, business_problem)` | 写应用目标 | false |
| | `transition_phase(target, reason)` | phase 跳转 | n/a |
| | `resolve_decision(decision_id, resolution)` | 关闭一个 pending 决策 | n/a |
| **gathering / drafting** | `add_role(code, name, scope, description)` | 加角色 | false |
| | `update_role(code, **changes)` | 改角色 | 不变 |
| | `add_object(code, name, description, fields[])` | 加业务对象 | false |
| | `add_field(object_code, field)` | 给对象加字段 | false |
| | `update_field(object_code, field_code, **changes)` | 改字段 | 不变 |
| | `add_dict(code, name, options[])` | 加字典 | false |
| | `add_permission(object_code, rules[])` | 配权限 | false |
| **drafting** | `confirm_*` (role/object/field/dict/permission) | 用户表达确认意图后调 | true |
| | `dismiss_*` | 用户驳回（物理删除） | n/a |
| **generating** | (无 tool，纯转换) | `spec_to_config()` 同步执行 | n/a |

**强约束**（写在所有 phase prompt 里）：
1. gathering phase 首轮：如果 `spec.completeness.confirmed == 0`，**禁止**直接调 `add_*` / `set_goal`，必须先 `ask_clarifying_question` 至少 3 次
2. drafting phase：**禁止**调 `confirm_*`，除非用户上一句明确表达"确认/OK/没问题/可以/没问题"等
3. 任何 phase：调 `transition_phase` 前必须 `decisions_pending` 中无 `blocking=true` 项
4. 每轮 tool 调用 ≤ 5 个，让用户能跟上

**强约束 1 的代码层强制**：
- gathering 首轮如果 LLM 直接调 `add_*`，tool 执行函数 reject 并返回 error message：`"在 gathering phase 首轮必须先 ask_clarifying_question 至少 3 次。请重新规划本轮 tool 调用。"` LLM 看到 error 会自己改正（vibe_agent 已验证此模式可行）

---

## 6. Phase Prompt 骨架

### 6.1 `SPEC_GATHERING_PROMPT`

替代 [REQUIREMENTS_SYSTEM_PROMPT](backend/app/routes/chat.py:310)。

```
你是 aPaaS 业务分析师。当前 SPEC 状态：
{spec_summary_block}

【硬规则】
1. 首轮回复必须只调用 ask_clarifying_question tool 3-5 次，禁止任何 add_/set_。
2. 第二轮起，根据用户回答调 set_goal / add_role / add_object，
   每次问完一个领域再继续问下一个，不要一口气铺开。
3. 禁止在对话内容里写 "## 系统核心模型" "让我帮你设计" 这类元描述。
4. 当 completeness ≥ 0.6 且无 blocking decision 时，调 transition_phase("drafting")。

【tool 调用纪律】
- add_* tool 调用时 confirmed 必须为 false，等用户在 UI 确认。
- 不要一次塞 10 个 tool；每轮 ≤ 5 个 tool 调用。
- 对话文本里禁止重复 tool 已经写入的内容（避免冗余）。

【对话语言】
- 用业务语言，对业务用户避免"枚举""数据模型"等技术术语。
- 一次只问一个核心问题，对话节奏像顾问聊需求。
```

### 6.2 `SPEC_DRAFTING_PROMPT`

```
你正在整理 SPEC 草案。当前 SPEC：
{spec_summary_block}

【任务】
1. 把 gathering 阶段的零散信息整理成完整 SPEC：补全 fields、推断 dicts、生成 permissions 默认规则。
2. 推断的内容用 add_/update_，confirmed=false，让用户审。
3. 用户在 UI 上点 confirm/dismiss/edit 后会通过 user message 告诉你，你再调对应 tool。
4. 所有项 confirmed=true 且无 blocking decision 时，调 transition_phase("generating")。

【禁止】
- 禁止在用户没说"确认"时主动调 confirm_*。
- 禁止跳回 gathering（除非用户明确说"重来 / 这部分需求要改"）。
- 禁止在对话文本中重写 SPEC 内容（用 tool 而不是文本）。

【对话语言】
- 简短解释你正在做什么（"我已经补了 3 个权限规则，请你确认"），不要长篇大论。
```

### 6.3 generating phase

不调 LLM。后端 `spec.converter.spec_to_config(spec)` 同步执行 + 写 `Application.config` + 触发现有 `triggerFullBuildPipeline()`。

`spec_to_config` 的字段映射**穷举性**列在 `spec/converter.py` 注释中，每个 SPEC 字段 → config 字段路径都对应单测。

---

## 7. 5 个入口的迁移路径

| 入口 | 旧路径 | 新路径 |
|---|---|---|
| 1 chat 多轮 | REQUIREMENTS_SYSTEM_PROMPT 自由对话 → markdown → doc_pipeline | SpecAgent (gathering→drafting→generating) |
| 2 文档 ≥60 | silent_generator → BUILDER prompt 直出 config | `SpecAgent.bootstrap_from_doc(silent=True)` → 一次性吐 SPEC 全 confirmed=true → 直接 phase=ready |
| 2 文档 <60 | doc_pipeline 走 chat 上下文 | `SpecAgent.bootstrap_from_doc(silent=False)` → 进 drafting phase 让用户确认 |
| 3 截图 | OCR/视觉作为对话上下文 | 同入口 1，截图作为 gathering phase 的 user 消息 |
| 5 已部署 + 对话增量 | 老 BUILDER patch JSON | load `app.canonical_spec_id` → SpecAgent 在 ready phase 上 add_/update_ → 重转 config + redeploy |
| 6 已部署 + 文档 V1→V2 | text diff → ChangePlan | `SpecAgent.bootstrap_from_doc(diff_only=True, base=canonical_spec)` |
| 4 平台导入 | platform_sync.sync_from_platform_full | **不变**，不进 SPEC 状态机 |

`config_assembler.py` 改名 `legacy_config_assembler.py`，新代码禁止 import，老对话 load 时兜底。
`doc_pipeline.py` 保留为 `bootstrap_from_doc` 内部用的"标准度检测 + 章节切分"工具。
`ai_doc_parser.py` 保留给入口 4 单独用，新路径不调。

---

## 8. UI 改动

### 8.1 `PhaseBar.vue`（新组件）

- 抽出 [ChatPage.vue:74-83](frontend/src/views/ChatPage.vue:74) 内联 phase 条
- 数据源改为 `spec.phase` 字段（不再前端推断）
- 新增"点击 phase 直接跳转"交互：调 `PUT /spec/{id}/phase` API，后端校验 `decisions_pending` 中无 blocking → 允许

### 8.2 `SpecCanvas.vue`（新组件，中间栏）

替代右侧 `[ChatPage.vue:615-621]` 的"还没有解析内容"占位。

- 5 个 section（goal / roles / objects / dicts / permissions），每个 section 是 collapsible 卡片组
- 每张卡片右上角 3 按钮：✅ confirm / ✏️ edit / ❌ dismiss
- 点击触发 `PUT /spec/{id}/items/{type}/{code}` → 后端调对应 tool → 流式回 SPEC patch → 前端实时刷新

### 8.3 `SpecInspector.vue`（新组件，第三栏）

按 [chat-page.jsx:174-248 设计稿原型 Inspector](file:///Users/mars/Desktop/apaas-ai-builder/chat-page.jsx) 实现。

- 顶部：completeness 进度环（`{confirmed}/{total}`）
- 中间：`decisions_pending` 列表，每项显示 topic + options + "去决策→" 按钮（点击在 SpecCanvas 上滚到/高亮对应卡片）
- 底部：版本时间线（按 `parent_spec_id` 链），可点击切换 spec 查看（只读）

### 8.4 ChatPage 三栏布局改造

- 左 Composer（聊天） | 中 SpecCanvas（业务视图）| 右 SpecInspector
- 老 PreviewPanel（roles/dicts/models 表格视图）保留作为 SpecCanvas 的"技术视图" tab，配合"业务视图" tab 切换
- `<1280px` 时 Inspector 自动折成抽屉

---

## 9. API 设计

### 9.1 SPEC 主 API

| Method | Path | 用途 |
|---|---|---|
| POST | `/spec` | 创建空 spec（chat 首次发消息时自动创建） |
| GET | `/spec/{id}` | 读 spec 全量 |
| PUT | `/spec/{id}/phase` | 切换 phase（用户主动跳转） |
| PUT | `/spec/{id}/items/{type}/{code}` | 用户在 Canvas 上 confirm/edit/dismiss 单项 |
| GET | `/spec/{id}/history` | 读 parent_spec_id 链 |

### 9.2 跟现有 chat API 的对接

`POST /chat/send` 当 `conversation.spec_id IS NOT NULL` 时：
- system_prompt 由 SpecAgent 根据 `spec.phase` 选择
- LLM 流式响应附带 `tool_calls`，后端逐个执行 tool，每个 tool 执行后发 SSE event `spec_patch` 给前端实时更新 SpecCanvas/Inspector

`POST /chat/send-with-file` 当文件类型为 markdown/word：
- 标准度 ≥60 → `SpecAgent.bootstrap_from_doc(silent=True)`
- 标准度 <60 → `SpecAgent.bootstrap_from_doc(silent=False)`

---

## 10. 风险评估

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| LLM 不遵守"首轮只问澄清"硬规则 | 中 | 中 | tool 调用层强制：gathering 首轮的 `add_*` tool 直接 reject 返回错误，LLM 看到 error 会改正 |
| tool calling 在某些模型上行为差异 | 中 | 中 | Phase α 只支持 claude-opus-4-6 + gpt-4o，其他模型走旧路径 fallback |
| 老 conversation 数据迁移崩 | 低 | 高 | 不回填，按需 upgrade，分支判断 `spec_id IS NULL` 走老 UI |
| spec_to_config 转换丢字段 | 中 | 高 | 写穷举性单元测试，每个 SPEC 字段 → config 字段路径都有测试 |
| UI 三栏在小屏挤爆 | 低 | 低 | Inspector 在 `<1280px` 时自动折成抽屉 |
| LLM 一次塞 10+ tool 调用堵满 stream | 中 | 中 | prompt 写"每轮 ≤ 5 个 tool"+ tool_choice 软限制 |

---

## 11. 分阶段交付节奏

拆 3 个 PR，每个独立可验证。

### Phase α — 后端骨架（3-4 天）
- `backend/app/spec/{schema,tools,agent,converter}.py`
- `specs` DB 表 + `Application.canonical_spec_id` + `Conversation.spec_id`（含 alembic migration）
- `/spec/{id}` GET/PUT API
- `chat.py` 加分支：`agent_type == "requirements"` 走新路径
- 单元测试：每个 tool atomic 行为 + spec_to_config 字段映射穷举
- **验收**：curl 跑通"chat 多轮 → SPEC gathering → drafting → generating → 转 config"全链路

### Phase β — 前端三栏 + UI tool 调用（4-5 天）
- `PhaseBar.vue` / `SpecCanvas.vue` / `SpecInspector.vue` 三个新组件
- ChatPage 三栏布局重构
- 用户在 Canvas 上 confirm/edit/dismiss 联动 backend
- 流式 SSE `spec_patch` event 接收 + 前端实时更新
- **验收**：真机点 confirm 按钮能改 spec，Inspector 实时反映 completeness

### Phase γ — 入口 2/3/5/6 迁移（3-4 天）
- `bootstrap_from_doc` 实现（silent / non-silent / diff-only 三模式）
- 增量更新（入口 6）切到新路径
- 已部署应用对话增量（入口 5）切到新路径
- legacy fallback 路径完整测试
- **验收**：6 个入口（除 4）全部走新路径，老对话仍可读

**总工期**：10-13 工作日（约 2 周）

---

## 12. 不在本 spec 范围

- 入口 4 平台导入（保持旧路径）
- coding/vibe_agent（自开发流程独立）
- Tier 1 视觉 token 移植（独立 spec，跟此并行）
- 多租户 / 权限收紧（Phase 1 IAM 已在 [PLAN.md](PLAN.md) 单独跟踪）
- SPEC 模板库 / 跨 application 复用（v2 议题）
- audit log 完整时间线（v2 议题，当前用 `parent_spec_id` 链表足够）
