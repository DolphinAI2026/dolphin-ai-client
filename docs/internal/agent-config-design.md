# ai-builder 内置 Agent 配置化重构 — 设计文档

> 起草日期：2026-05-14
> 起因：用户提出 "我们 ai-builder 自己的 agent（ai_chat / cowork / coding）现在
> prompt 和 MCP 工具都是硬写在代码里的，跟得小帆 builder 一对比维护性太差"
> 目标：让 ai-builder admin 用户能像配置 dolphin agent 那样可视化管理我们自己的 agent

---

## 一、现状盘点

### 1.1 ai-builder 现有内置 agent 几个

| Agent | 入口 | prompt 在哪 | 工具来源 | 模型选择 |
|---|---|---|---|---|
| **ai_chat / cowork**（这次重构主目标） | `/ai-chat/{id}` | `app/ai_chat/agent.py:73` `SYSTEM_PROMPT_UNIFIED` 250+ 行硬写 | `app/ai_chat/tools.py:269` 4 个 base 工具硬注册 + `mcp_bridge` 全量拉 80 个 | session 创建时挑一次 `llm_configs` ✓ |
| **coding agent**（AI Coding workspace） | `/coding/workspace/{ws_id}` | `app/coding/prompts.py` AGENT_SYSTEM_PROMPT | hardcoded in `app/agents/coding/tools.py` | `llm_configs` ✓ |
| **vibe agent**（Vibe Coding workspace） | `/online-coding/{ws_id}` | `app/vibe_coding/prompts.py` | hardcoded in `app/coding/vibe_agent.py` | `llm_configs` ✓ |

### 1.2 跟 dolphin builder 的对比

| 维度 | dolphin builder | 我们 ai-builder | 差距 |
|---|---|---|---|
| Prompt 管理 | textarea，运营/管理员可改 | Python 常量硬写 | 改一句话要发布 |
| MCP 工具挂载 | "+ 添加" 按钮，可视化选 N 个 MCP service | mcp_bridge 全量拉 80 个，没 per-agent 筛选 | agent 看到不该看的工具，prompt 上下文浪费 token |
| Skill 引用 | "+ 添加" 按钮，挂载 N 个 skill | `docs/skills/*.md` 写了但没人读 | 我刚加的 apaas-backend-dev skill 实际没生效 |
| 全局记忆 kv | 「+ 添加」配 `env: pg` 等 | 没这概念 | per-user / per-session 注入无法可视化 |
| 长期记忆开关 | UI 开关 | 没实现 | 跨会话 memory 缺失 |
| 短期记忆 | UI 开关 | 默认开（session 表里存 messages） | 一致 ✓ |
| 模型选择 | UI 下拉 | UI 下拉（llm_configs） | 一致 ✓ |
| 运行时令牌 | UI 选 `sk-dolphin-***` 类型 | 模型已含 api_key | 一致（口径不同但等价） |
| 「保存 / 发布」 | 草稿态 vs 发布态 | 直接生效 | 我们简化到 1 种状态 |

---

## 二、目标范围（4 层递进）

按代价 / 价值递增，每层可独立交付。

### 层 1：Prompt 抽到 DB + admin UI textarea ⭐ MVP

**改什么**：

- 加表 `agent_configs`：
  ```
  id INT PK
  code VARCHAR(64) UNIQUE     -- 'ai_chat' / 'cowork' / 'coding' / 'vibe'
  name VARCHAR(128)           -- 「AI 聊天助手」
  description VARCHAR(512)
  system_prompt LONGTEXT      -- 250+ 行 prompt 落 DB
  default_llm_config_id INT   -- 默认模型（创建会话时 fallback）
  status VARCHAR(16)          -- 'active' | 'draft' | 'archived'
  tenant_id INT               -- per-tenant 隔离（可空，NULL 表平台级共享）
  created_at / updated_at / created_by / last_updated_by
  ```

- 加 admin 路由：
  ```
  GET    /admin/agents               列表（按 tenant_id 过滤）
  GET    /admin/agents/{id}          详情
  POST   /admin/agents               新建
  PUT    /admin/agents/{id}          更新
  DELETE /admin/agents/{id}          软删（status=archived）
  ```

- 加 admin 页面 `/admin/agents`：
  - 列表：code / name / status / 最后更新
  - 详情：name / description / status / default_llm_config / system_prompt textarea
  - 「测试对话」按钮：用当前 draft prompt 起临时 session

- 改 `ai_chat/agent.py` 加载逻辑：
  ```python
  async def get_system_prompt(session: AIChatSession, db) -> str:
      # 1) 优先按 session.agent_code 查 agent_configs（带 5 分钟 cache）
      # 2) 找不到 fallback 到 SYSTEM_PROMPT_UNIFIED 常量（保留向后兼容）
      cfg = await _load_agent_config_cached(session.agent_code or "ai_chat", db)
      return cfg.system_prompt if cfg else SYSTEM_PROMPT_UNIFIED
  ```

- 加 `ai_chat_sessions.agent_code` 字段（NULL=老会话用默认）

**实现工作量**：1-2 天。

**风险**：cache 失效后改 prompt 立即生效，但已存在的 session 不重读（每条消息 turn 都重读 cache 太重，妥协）。

**回滚**：DB migration 可降级，常量 fallback 保证可用。

---

### 层 2：MCP 工具 per-agent 选择

**改什么**：

- 加表 `agent_mcp_bindings`：
  ```
  id INT PK
  agent_config_id INT FK → agent_configs.id
  tool_pattern VARCHAR(128)   -- 支持具体名 'list_platform_envs' 或通配 'list_apaas_*'
  enabled BOOLEAN DEFAULT TRUE
  sort_order INT
  ```

- 改 `mcp_bridge.get_tool_schemas_openai()` 加参数 `agent_code`：
  ```python
  async def get_tool_schemas_openai(agent_code: str = None) -> list[dict]:
      # 不带 agent_code 走老逻辑（全 80）
      # 带就按 agent_mcp_bindings 过滤
      if agent_code:
          patterns = await _load_agent_tool_patterns(agent_code)
          tools = [t for t in tools if _match_any(t.name, patterns)]
  ```

- admin UI 详情页加「MCP 工具」面板：
  - 左侧：所有可用 MCP 工具（按 admin_mcp `_classify_tool` 分类显示）
  - 右侧：勾选 / 输入 pattern
  - 支持 `list_apaas_*` 通配匹配（带类组级开关）

**实现工作量**：+1-2 天。

**值得做的原因**：

1. ai_chat agent 不需要看 publish_dev_workspace / vibe_* 等 coding 工具，浪费上下文
2. coding agent 不需要看 generate_app_from_doc / parse_design_doc 等文档生成工具
3. 不同租户可以挂载不同工具子集

---

### 层 3：Skill 多选引用

**改什么**：

- 加表 `agent_skill_bindings`：
  ```
  id INT PK
  agent_config_id INT FK
  skill_path VARCHAR(512)    -- 'docs/skills/apaas-backend-dev.md'
  inject_mode VARCHAR(16)     -- 'inline' (拼到 prompt) | 'ref' (LLM 按需读)
  ```

- ai_chat 加载 prompt 时按 mode 处理：
  - `inline` — 把 skill .md 内容拼到 SYSTEM_PROMPT 末尾，加 marker `## Skill: apaas-backend-dev`
  - `ref` — 在 SYSTEM_PROMPT 里加一句"可用 skills: [list]，LLM 决定要不要 read 工具读"
    （需要配套加 `read_skill(skill_path)` MCP 工具让 LLM 按需读）

- admin UI：多选 skill 文件（从 `docs/skills/` 目录扫，或者支持 git submodule path）

**实现工作量**：+1 天（不含新加 read_skill 工具）。

**值得做的原因**：

1. 现在 docs/skills/apaas-backend-dev.md 写了 16 坑速查，但 agent prompt 没引用 → 实际没生效
2. 跟 dolphin "ai-builder-coding-workflow" skill 用法对齐
3. 长 prompt 可拆 — 主 prompt 留核心人设，能力按场景拆 skill

---

### 层 4：全局记忆 kv + 长期记忆开关

**改什么**：

- 加表 `agent_global_memory`：
  ```
  id INT PK
  agent_config_id INT FK
  scope VARCHAR(16)          -- 'agent' (此 agent 全员共享) | 'user' (per-user)
  user_id INT NULL           -- scope=user 时非空
  memory_key VARCHAR(64)     -- 'env' / 'department' / 'tenant_default_app'
  memory_value VARCHAR(512)
  ```

- prompt 加载时把 memory 拼到 SYSTEM_PROMPT 头部：
  ```
  [全局记忆]
  - env: pg
  - department: HR
  ```

- 加表 `agent_long_term_memory`：
  ```
  id INT PK
  agent_config_id INT FK
  user_id INT
  fact VARCHAR(2048)         -- "用户偏好简洁回答" / "用户主用 trial env"
  source_session_id INT      -- 哪个会话提取出来的
  confidence FLOAT            -- LLM 给的置信度
  created_at
  ```

- agent_configs 加 `long_term_memory_enabled BOOLEAN DEFAULT FALSE`

- 长期记忆 = 会话结束/总结时 LLM 自动提取「我以后要记住的事」存表，下次此用户用同 agent 时拼到 prompt

**实现工作量**：+1-2 天。

**值得做的原因**：

1. dolphin 实测：admin 全局记忆 `env: pg` 后，agent 不用每次问环境
2. 长期记忆让用户跨会话有连续感（dolphin 那边截图开关默认开）

---

## 三、admin UI mock（草图）

```
┌─────────────────────────────────────────────────────────────────────┐
│  /admin/agents                                       [+ 新建 Agent] │
├─────────────────────────────────────────────────────────────────────┤
│  Code           Name                  Status   Updated   Actions    │
│  ai_chat        AI 聊天助手           Active   1h ago    [edit][del]│
│  cowork         AI 协作分析师         Active   2d ago    [edit][del]│
│  coding         AI Coding 开发助手    Active   1w ago    [edit][del]│
│  vibe           Vibe 全代码开发       Draft    Never     [edit][del]│
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  /admin/agents/1  «AI 聊天助手» 编辑                                │
├─────────────────────────────────────────────────────────────────────┤
│  基本信息                                                            │
│  Code: ai_chat            (只读 — 代码引用)                          │
│  Name: [AI 聊天助手               ]                                  │
│  Description: [面向 aPaaS 用户的全栈助手...]                         │
│  Status: ⦿ Active  ○ Draft  ○ Archived                              │
│  Default Model: [GPT-5.5 ▼]                                          │
│                                                                      │
│  ──── 层 1：System Prompt ───────────────────────────────────────    │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │ 你是 aPaaS 平台的 AI 全栈助手 — 既能产文档（喂给 ai-build  │    │
│  │ 流水线直接解析），也能写代码...                            │    │
│  │ (textarea, 全屏可放大)                                     │    │
│  └────────────────────────────────────────────────────────────┘    │
│  [恢复默认] [格式化 Markdown]                                        │
│                                                                      │
│  ──── 层 2：MCP 工具绑定 ────────────────────────────────────────    │
│  ☑ 全选「aPaaS 平台内省」分类 (12 工具)                              │
│  ☑ list_apaas_apps_in_env                                            │
│  ☑ list_apaas_app_menus                                              │
│  ☐ vibe_* (一组 11 个，不需要给 ai_chat)                             │
│  [+ 自定义 pattern]   实际生效 42/80 工具                            │
│                                                                      │
│  ──── 层 3：Skill 引用 ──────────────────────────────────────────    │
│  ☑ docs/skills/apaas-backend-dev.md      Mode: [inline ▼]            │
│  ☑ docs/skills/dev-coding-workflow.md     Mode: [ref ▼]              │
│  [+ 添加 Skill]                                                      │
│                                                                      │
│  ──── 层 4：记忆 ────────────────────────────────────────────────    │
│  全局记忆（注入到 prompt 头部）                                      │
│  - env: pg                              [×]                          │
│  - tenant_default_app: 824710872671... [×]                           │
│  [+ 添加 kv]                                                         │
│                                                                      │
│  长期记忆: [⚪开]   总结跨会话用户偏好                                │
│  短期记忆: [⚪开]   单会话上下文（默认开）                            │
│                                                                      │
│  ──── 调试 ─────────────────────────────────────────────────────    │
│  [💬 用 draft prompt 起测试会话]    上次测试: 5 min ago [查看]      │
│                                                                      │
│  [取消]                                          [保存草稿] [发布]   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 四、迁移路径

按层渐进，每层独立可上线：

```
现状
  ↓ (1-2 天)
层 1: Prompt 落 DB
  ├ migration: 把现有 SYSTEM_PROMPT_UNIFIED / CHAT / COWORK 三个常量 seed 到
  │            agent_configs 表（status=active）
  ├ ai_chat session.agent_code 默认 'ai_chat'
  ├ get_system_prompt 优先读 DB；DB 没有时 fallback 到常量 — 旧 session 不受影响
  └ admin UI 上线
  ↓ (+1-2 天)
层 2: MCP 工具过滤
  ├ migration: seed 现有「ai_chat 看全部 80 工具」的绑定（pattern: '*'）
  ├ mcp_bridge.get_tool_schemas_openai(agent_code) — 不传 agent_code 兼容老代码
  └ admin UI 加工具勾选面板
  ↓ (+1 天)
层 3: Skill 引用
  ├ migration: seed apaas-backend-dev / dev-coding-workflow 等已有 skill 到 ai_chat
  ├ prompt 拼接逻辑
  └ admin UI 加 skill 多选
  ↓ (+1-2 天)
层 4: 全局记忆 / 长期记忆
  ├ 全局记忆: seed env: pg / department: HR 之类
  ├ 长期记忆: 会话结束 LLM extract → 入表 → 下次拼 prompt
  └ admin UI 加 kv + 开关
```

**回滚策略**：每层 migration 都可降级，DB 表保留但 Python 加载逻辑回到 fallback 常量分支。

---

## 五、跟 dolphin builder 对照表（最终态）

| dolphin builder 字段 | 我们实现 |
|---|---|
| 人设提示词 textarea | `agent_configs.system_prompt` + admin textarea |
| 聊天头像 | `agent_configs.avatar_url`（可选，层 1 阶段先 skip） |
| 模型下拉 | `agent_configs.default_llm_config_id` 选 llm_configs |
| 运行时令牌 | llm_configs 已含 api_key |
| 多模态 / 深度思考 | llm_configs.model 字段决定（GPT-5.5 / o1 等） |
| MCP 服务（多个） | `agent_mcp_bindings`（层 2） |
| Skills（多个） | `agent_skill_bindings`（层 3） |
| 全局记忆 kv | `agent_global_memory`（层 4） |
| 长期记忆开关 | `agent_configs.long_term_memory_enabled` |
| 短期记忆开关 | 默认开（不暴露开关，session messages 就是短期） |
| 「保存」「发布」双状态 | `agent_configs.status` 加 'draft' / 'active'；可选实现版本号 |
| 「去对话」按钮 | admin UI 详情页加按钮 → 跳 /ai-chat?agent_code=xxx 起新会话 |
| 调试与预览面板 | admin UI 详情页右侧加 iframe 嵌 /ai-chat |

---

## 六、风险 / 已知问题

1. **Prompt 改了立即生效 vs 历史会话上下文不一致**
   - 历史 session 还在用旧 prompt 加载的 tools schema（OpenAI 协议上下文会保留），
     新 prompt 当前 turn 才生效
   - 妥协：admin UI 改完弹「这 N 个活动会话仍在用旧 prompt，下一 turn 后切换」

2. **Skill inline 模式 prompt 长度**
   - 拼太多 skill 会爆 LLM context window
   - admin UI 显示「拼后总 prompt 长度 / 模型限制」实时进度条

3. **全局记忆 user-scope 实现成本**
   - per-user kv 实现简单，但 dolphin 是从 dolphin user 体系拿；我们要对接的话需要
     ai-builder users 表 + ctx.user_id 注入
   - 层 4 默认只做 `scope=agent`（agent 内全员共享），user-scope 留 TODO

4. **draft / active 双状态 vs 简化单状态**
   - 简化做：直接编辑 active，立即生效（dev 友好）
   - 完整做：draft 编辑 → 测试 → 发布到 active（运营友好）
   - 建议层 1 简化做，等真有运营踩坑再加 draft

5. **dolphin 那套也要保留**
   - dolphin agent 仍然是租户管理员可接入的外部能力，本重构只动 ai-builder 内置 agent
   - 两套并存：dolphin agent 在右上角浮窗 / nav 入口；ai-builder 内置 agent 在 ai-chat / coding / vibe 页

---

## 七、未来扩展（不在 4 层范围内，记录待办）

- **agent 模板市场**：导入 / 导出 agent 配置 JSON，社区分享
- **agent 版本号**：每次发布存 snapshot，可回滚
- **agent 间链式调用**：agent A 在工具调用里调 agent B
- **A/B 测试 prompt**：50% session 用 v1 prompt，50% v2，比对完成率
- **prompt 编辑器助手**：admin UI 里嵌一个小 LLM 帮运营改 prompt

---

## 八、决策点 — 等用户拍板

1. **范围确认**：4 层全做？还是先做层 1 验证？
2. **节奏**：每层做完 push 上线 review，还是 4 层一起做完上线？
3. **租户隔离**：agent_configs 要不要 per-tenant？还是全平台共享一套（dolphin trial 就是平台级共享）？
4. **draft 双状态**：层 1 简化做（直接编辑 active）还是完整做（draft→publish）？
5. **admin UI 框架**：跟 PlatformTenants / PlatformEnvs 一样用 Element UI table + form 走，还是借机做更现代的卡片式？

---

**下次接手第一步**：用户 review 本文档 → 给上面 5 个决策点答案 → 我按答案动手做层 1。
