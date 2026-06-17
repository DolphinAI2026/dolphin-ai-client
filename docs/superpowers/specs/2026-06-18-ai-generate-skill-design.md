# 设计：AI 生成 Skill（桌面 agent 自动造技能）

- 日期: 2026-06-18
- 分支: `feat/desktop-login-mvp`
- 状态: 设计已确认，待 writing-plans
- 相关: [docs/handoff-2026-06-17-ai-generate-skill.md](../../handoff-2026-06-17-ai-generate-skill.md)、[2026-06-17-skill-ide-v1.md](../plans/2026-06-17-skill-ide-v1.md)（已实现）、memory `skill_upload_v1_2026_06_17`

## 目标

让桌面 ai-builder 的 agent **把可复用的做法沉淀成一个 skill**（`SKILL.md` + 可选 helper 文件）存进用户技能库——用户靠 AI 攒技能库，而不是只能手动传 zip。这是 SP4 技能库「AI 创建」那一块；上传 / 使用 / IDE 编辑已分别做完，本设计只补「AI 创建」。

## 起点：复用，不重建

落盘原语在 `backend/app/ai_chat/skills.py` 的 `SkillRegistry` 全有：`create_user_skill(name)` / `write_skill_file(name, rel, content)` / `update_skill_metadata(...)` / `list_skill_files` / `read_skill_file` / `clone_skill`。skill 格式 = Claude Code SKILL.md（目录含 `SKILL.md`，frontmatter 扁平 `key: value`，手解析无 yaml 依赖 + helper 文件）。存 `data_dir/skills/{platform,user}/<name>/`。

本设计 = **生成内容（agent 的 LLM 活）+ 落盘（调原语）+ 暴露成 MCP 工具**，不碰存储实现。

## 范围（四个已确认决策）

1. **两个入口**：①会话里「存这次对话/任务成技能」②技能库页「描述需求从零写」。两入口共用同一套生成 → 校验 → 落盘管线。
2. **工具直接存 + IDE 里改**：agent 调工具直接落盘进技能库，生成内容在对话里可见；用户去已有 Skill IDE 工作区细改。不做单独的预览/确认弹框（留 v2）。
3. **内容范围**：SKILL.md + 可选 helper 文件（agent 判断确定性逻辑值得写脚本时带上）。
4. **顺带 MCP 接入**：skill 创作操作暴露成 MCP 工具，app 内 agent 经 bridge 用、外部 MCP 客户端（Claude/Cursor）也能用。

### 非目标（v2）
预览/确认弹框、agent 主动检测可复用模式并建议、生命周期/审核/发布、导出 zip、删除走 MCP（删留给 REST/IDE，外部客户端删 skill 风险高）、标签体系。

## 架构（方案 1：复用统一 agent + create_skill MCP 工具）

「生成/提炼」在 agent 正常对话循环里做（凭对话上下文 + 方法论提示）；「落盘」是 `create_skill` MCP 工具。两个前端入口都只是「注入一段提示 + 发消息」，agent 凭上下文/描述生成内容并调 `create_skill`。MCP 工具天然同时服务 app 内 agent（经 mcp_bridge）和外部 MCP 客户端——MCP 接入不是额外一层。

## 组件

### 1. MCP 工具层 — 新模块 `backend/app/mcp_tools/skill_authoring.py`

仿现有 `mcp_tools/*` 模式：`@mcp.tool()` + `@apaas_tool(required=[...])`，导出 `register(mcp)`，在 `backend/app/mcp_server.py` 统一挂载（与其它 `_register_*_tools` 并列）。工具：

- **`create_skill(name, description, instructions, helpers=None)`** — 基石。`helpers` = `[{path, content}]`（可空）。流程：
  1. 校验 `name`（ASCII / 无路径分隔 / 不重名）、必填 `description`（走共享校验器，见下）。
  2. `SkillRegistry.create_user_skill(name)` 建目录骨架（含占位 SKILL.md）。
  3. 拼出完整 `SKILL.md` 内容（frontmatter `name` + `description`，正文 = `instructions`），用 `write_skill_file(name, "SKILL.md", 完整内容)` 覆盖骨架（单次写定，不走 update_skill_metadata 再补正文）。
  4. 逐个写 `helpers`（`write_skill_file(name, h.path, h.content)`，路径越界由 `_resolve_file` 拦）。
  5. 返回 `{ok: true, name, files, dir}`。
  - 失败一律业务错 dict：`{ok: false, error_code, message}`，用 `app.mcp_envelope` 的 `_ok`/`_err`/`ErrorCode`（**非** `_business_error`，该设施不存在）。错误码：重名 `SKILL_EXISTS` / 非法名 `SKILL_NAME_INVALID` / 缺字段经 `@apaas_tool` 自动 `INVALID_PARAMS` / 云端无技能库 `SKILLS_UNSUPPORTED`（`skills_root()` 为 None）/ 平台只读 `SKILL_READONLY` / 写失败 `SKILL_WRITE_FAILED`（新码加进 `ErrorCode` 类）。详见实施计划 `docs/superpowers/plans/2026-06-18-ai-generate-skill.md`。
- **`list_skills()`** — 列已有 skill（name/source/description），供 agent 创建前查重名、外部客户端枚举。
- **`read_skill_file(name, path)`** — 读某 skill 的文件，供 agent/外部客户端回看迭代。
- **`write_skill_file(name, path, content)`** — 写/覆盖文件（仅 user skill，越界拦）。给外部客户端补齐创作面。
- **`update_skill_metadata(name, description=?, tags=?, display_name=?)`** — 改 frontmatter。

工具可达性：`create_skill` 等**走延迟工具**（不动 `agent.py` 的 core 集逻辑，减少跟并发会话 + 已提交 A+B 的冲突面）。按钮注入的提示会明确让 agent `search_tools` 激活并调用 `create_skill`。实测若激活不稳，再把 `create_skill` 提到 core 集（`split_core_deferred`）。

### 2. 共享校验（改 `backend/app/ai_chat/skills.py`）

把上传路径（`backend/app/routes/skills.py` 的 POST upload）那套 frontmatter / 名校验抽成模块级共享函数：

- `validate_skill_name(name)` — ASCII、无路径分隔（`/ \ . ..`）、非空。
- `validate_skill_frontmatter(meta)` — 必含 `name` + `description`。

`create_skill`（MCP）与上传端点两边都调，单一来源。这是交接文档点名的「复用 upload 校验」。

### 3. 生成提示 / skill-creator 方法论

不永久膨胀统一 system prompt。一份 DRY 常量 `SKILL_AUTHORING_GUIDE`（放 `skill_authoring.py`），两处承载：

- **`create_skill` 工具 docstring** 内嵌「怎么填好参数」：
  - `description` 写成第三人称、触发导向的「Use when…」（决定以后 `use_skill` 触发准不准——核心 know-how）。
  - `instructions` 写具体编号步骤，命令式。
  - 确定性逻辑优先写成 helper 脚本，而非塞进长 prose。
  - 单一职责；细节用引用文件渐进披露，SKILL.md 保持精简。
  - 名用英文 kebab-case。
- **两个入口注入的提示** 各带提炼/撰写指令，引用同一方法论。

> 实现时按交接建议，去 `anthropic-skills:skill-creator` 核对最新原则，填进 `SKILL_AUTHORING_GUIDE`。本设计已涵盖其要点（触发式 description / 单一职责 / 脚本优先 / 渐进披露 / 可迭代 eval）。

### 4. 前端两入口（复用对话 + dispatch，不新建页）

- **入口 1「存成技能」** — `frontend/src/views/AIChatPage.vue` 会话内按钮（放会话头部动作或输入区工具条）。点击 → 往当前会话注入一段提示并发送：「回顾这次对话完成的可复用做法，提炼 解决什么 / 何时用（→description）/ 步骤（→instructions）/ 要不要 helper 脚本，然后 `search_tools` 激活 `create_skill` 存进我的技能库，名用英文 kebab-case」。agent 凭已有上下文生成并调 `create_skill`；结果以工具卡呈现 + 一个「去技能库/IDE 打开」链接或 toast。
- **入口 2「AI 生成技能」** — `frontend/src/views/SkillLibraryPage.vue`，挨着现有「+ 上传技能 / 新建空白」。点击 → `ElMessageBox.prompt` 要一句描述 → 经现有 sessionStorage dispatch 机制（新 key `ai_builder_pending_skill_authoring`）带描述跳 AIChatPage → `onMounted` 消费、建会话、发种子提示（镜像现有 `maybeConsumeAiBuilderDispatch`）。

前端 API（`frontend/src/api/skills.ts`）`createSkill`/`listSkills` 等 F1 已有；本设计前端基本只加两个按钮 + 一个 dispatch 消费端，无新页。

## 数据流

```
入口1: 用户点「存成技能」→ 注入提示进当前会话 → run_agent
入口2: 用户点「AI生成技能」→ prompt 描述 → sessionStorage dispatch → AIChatPage 建会话发提示 → run_agent
                                          ↓ (两路汇合)
   agent: 读上下文/描述 → search_tools 激活 create_skill → 生成 name/description/instructions(+helpers)
                                          ↓
   create_skill (MCP, 经 mcp_bridge): 共享校验 → SkillRegistry.create_user_skill + write_skill_file*N
                                          ↓
   落盘 data_dir/skills/user/<name>/ → 返回 {ok,name,files,dir} → 工具卡 + 去 IDE 打开
```

## 错误处理

`create_skill` 失败一律 `ok:false` + `error_code`（见上枚举）。agent 按仓库铁律读 `error_code` 不瞎猜（`agent_hallucinates_token_expired` 教训）。前端 REST 路径用现有 toast。云端（`skills_root()` 为 None）返回 `SKILLS_UNSUPPORTED`，前端入口在非桌面环境隐藏/禁用。

## 测试

- 后端 `backend/tests/test_skill_authoring.py`（pytest，`backend/.venv`，SQLite）：
  - `create_skill` 正路：文件落盘 + frontmatter 正确 + helpers 写入 + 返回结构。
  - 重名 → `SKILL_EXISTS`；非 ASCII 名 → `INVALID_NAME`；缺 description → `MISSING_FIELD`。
  - `list_skills` / `read_skill_file` / `write_skill_file` / `update_skill_metadata` 包装。
  - 共享校验器 `validate_skill_name` / `validate_skill_frontmatter` 单测。
  - 注册冒烟：新工具进 `mcp_server`、schema 合法、不破坏 tool-registry drift 计数（对齐 `test_mcp_envelope` / `test_tool_registry`）。
- 前端 `npm run build:nocheck`（`vue-tsc` 项目级失效，用 nocheck）；两按钮人工 preview。
- 生成质量无法单测 → 人工 eval 1-2 个真实例（存一次真实对话 + 描述写一个已知技能），诚实标注。

## 落地坑（已纳入设计）

- skill 名必须 ASCII + 无路径分隔（frontmatter 注入越界防护，`routes/skills.py` 已有校验）。
- **改后端必重启 sidecar/进程**（`run.py` reload=False）才生效；新 MCP 工具还要清 `__pycache__` + proxy 重新「获取工具列表」（`python_pyc_stale_cache` 教训）。
- 前端 `vue-tsc` 项目级失效，用 `npm run build:nocheck`。
- 生成的 helper 靠 run_python `--run-script`（桌面）执行，见 memory `skill_upload_v1_2026_06_17`。

## 涉及文件 & 协作

**新增**：`backend/app/mcp_tools/skill_authoring.py`、`backend/tests/test_skill_authoring.py`。
**改**：`backend/app/ai_chat/skills.py`（抽共享校验）、`backend/app/mcp_server.py`（注册）、`frontend/src/views/AIChatPage.vue`（入口1 按钮）、`frontend/src/views/SkillLibraryPage.vue`（入口2 按钮）、可能 `frontend/src/api/skills.ts`（若 dispatch 需要）。

⚠️ **协作**：技能库前端（`SkillLibraryPage.vue`/`api/skills.ts`）+ `skills.py`/`routes/skills.py` 有另一会话在活跃开发。开工前确认它当前没在改这些文件，**只提交自己的文件、不 `git add -A`**（工作树有并发未提交改动）。

## 分解

单一主题，一份 plan 足够。任务约：①抽共享校验（skills.py）②`skill_authoring.py` create_skill + 4 个辅助工具 + 注册（mcp_server.py）③`SKILL_AUTHORING_GUIDE` + docstring ④入口1（AIChatPage 按钮）⑤入口2（SkillLibraryPage 按钮 + dispatch 消费）⑥测试 + build + 人工 eval。writing-plans 细化。
