# @skill 接入 coding 代码工作区(full + run_python)

> 2026-06-19 · 优化子项目 #3(共 4:#1 上下文管理[已完成] / #2 token 显示+换 session 提醒 / **#3 @skill 接入** / #4 handoff 结构化)。本 spec 只覆盖 #3。
> 用户拍板:full 方案 + run_python(v1 就让 coding agent 能读 skill 正文 + 跑 skill 脚本)。

## 背景与问题

coding(/coding 代码工作区)对 skill **全链路零接入**(4 路只读调研 + 直接核对源码确认):

- **前端**:`CodingPage.vue:264` 的 `UnifiedChatComposer` 没传 `:skills`/`@skill-picked`(对比 `AIChatPage.vue:256,260` 有);无 `availableSkills`/`listSkills()`/`onSkillPicked`。
- **后端工具**:`build_coding_tools`(`agents/coding/tools.py:517`)只装 22 个工具(read/write/edit/run_command/glob/grep/start_serve + 13 apaas/workspace + 2 deploy + run_workspace_preview),**无 `use_skill`、无 `run_python`**。
- **提示词**:coding 系统提示走 `resolve_prompt(agent_id='whale', phase='default', fallback=AGENT_SYSTEM_PROMPT)`(`pipeline.py:2106`),全文**没有「可用技能」段**。
- **pipeline**:构造 `CodingAgent` 时不扫 `SkillRegistry`、不注入 manifest。

后果:superpowers skill 即使上传到桌面也**只对 AIChat 链路可见**,coding agent 看不到技能名、无工具可调 → 这正是「开发有点笨」的根因。

底座全局共享、无数据层障碍:`skills.py`(`SkillRegistry`/`skills_root`/`build_skill_manifest`)、`routes/skills.py`(`/skills` CRUD)、前端 `api/skills.ts`(`listSkills`)。AIChat 链路已有完整参考实现可照搬。

## 目标

让 coding agent 跨四层接入 skill:前端能 @ 选 → 后端 `use_skill` 读正文+拷文件进 workspace → `run_python` 跑 skill 脚本 → 系统提示带技能清单引导。

**非目标**:多租户 skill 隔离(`skills_root()` 全局,桌面单租户为主,本期不动,文档标注为已知现状);read 路径(`run_read_query` 一次性问答)不接 skill;skill 选择不加 pipeline 新字段(走 message 文本,与 AIChat 一致)。

## 复用现成件(不重造)

| 现成件 | 位置 | 复用方式 |
|---|---|---|
| `SkillRegistry().scan()/get()/read_skill_md()` | `app/ai_chat/skills.py:104+` | 直接调,全局共享 |
| `build_skill_manifest(skills)` | `app/ai_chat/skills.py:260` | 直接调(空集返空串) |
| `execute_use_skill` 拷贝+读正文+路径穿越防护 | `app/ai_chat/tools.py:1250` | **逻辑照搬**,签名 `(args, session, db)` → `(args, ctx)`,workspace 改走 `_resolve_workspace_path(ctx)` |
| `execute_run_python` + `_build_python_argv` 冻结态处理 | `app/ai_chat/tools.py:356,348` | **抽成共享 `app/agents/python_runner.py`(`run_python_in_dir`+`build_python_argv`),coding 与 ai_chat 同源委托**(DRY,避免逻辑块重复;ai_chat 行为字节级不变) |
| `_append_skill_manifest` 注入模式(空集/异常 no-op) | `app/ai_chat/agent.py:53` | coding 在 pipeline 层**等价实现**(注入点不同) |
| 前端 skill 接线 | `AIChatPage.vue:256/260/675-682` + `api/skills.ts:listSkills` | **镜像**到 CodingPage |

## 架构 — 四处接线

### 1. 前端(`frontend/src/views/CodingPage.vue`)
- `import { listSkills } from '@/api/skills'`。
- 加 `const availableSkills = ref<{ name: string; description: string }[]>([])`。
- additive `onMounted`(并入现有或新增):`listSkills().then(s => { availableSkills.value = s }).catch(() => {})`(镜像 `AIChatPage.vue:676-678`)。
- composer(`CodingPage.vue:264` 块)加 `:skills="availableSkills"` + `@skill-picked="onSkillPicked"`。
- `function onSkillPicked(name: string) { const p = `请使用技能 ${name}：`; userInput.value = userInput.value ? `${p}${userInput.value}` : p }`(镜像 `679-682`,**target `userInput` 不是 `inputText`**)。

### 2. 后端 `use_skill` 工具(`backend/app/agents/coding/tools.py`)
新增 coding 版 executor `_use_skill(args, ctx) -> ToolResult`:
- `name` 校验空;`SkillRegistry().get(name)`;`None` → 返回「没有名为 X 的技能。可用技能:…」(照搬 `tools.py:1257-1259`)。
- `ws = _resolve_workspace_path(ctx)`(**不是** `AIChatSession.workspace_dir`)。
- `slug = re.sub(r"[^A-Za-z0-9_-]", "_", name)`;`dest = (ws / f"skill_{slug}").resolve()`;**校验 `ws in dest.parents`**(路径穿越防护,照搬 `1262-1268`)。
- 拷文件(skip `SKILL.md`,`copytree` 子目录 / `copy2` 文件,照搬 `1270-1280`)。
- `body = reg.read_skill_md(name)`;返回格式化文本(标题+来源+正文+文件清单+「用 run_python 执行」说明,照搬 `1284-1288`)。
- 用 `_wrap_result` 包成 `ToolResult`('Error:' 前缀=失败)。
- 在 `build_coding_tools` 的 `return tools`(`:745`)前 `tools.append(Tool(name="use_skill", description=照搬 1298-302, parameters_schema={type:object, properties:{name:{type:string}}, required:[name]}, execute=_use_skill))`。

### 3. 后端 `run_python` 工具(`backend/app/agents/coding/tools.py`)
新增 coding 版 executor `_run_python(args, ctx) -> ToolResult`:
- `code` 校验空;`ws = _resolve_workspace_path(ctx)`;`Path(ws).mkdir(parents=True, exist_ok=True)`。
- 冻结态(`runtime.is_frozen()`)落临时 `.run_<uuid>.py` + `_build_python_argv`(`--run-script`);非冻结 `python -c`。**照搬 `execute_run_python:356-417`** 的 subprocess / 超时 30s / 截断 8000 / `finally` 删临时文件。
- **`from app.ai_chat.tools import _build_python_argv`** 复用(避免重复实现冻结态逻辑)。
- `tools.append(Tool(name="run_python", description=照搬 58-62 但 cwd 说成「当前 coding 工作区」, parameters_schema={type:object, properties:{code:{type:string}}, required:[code]}, execute=_run_python, idempotent=False))`。

### 4. 后端 manifest 注入(`backend/app/coding/pipeline.py`)
在 `:2110` `resolve_prompt` 之后、`:2119` `_codegen_app_context_overlays` 之前插入:
```python
try:
    from app.ai_chat.skills import SkillRegistry, build_skill_manifest
    _skill_manifest = build_skill_manifest(SkillRegistry().scan())
    if _skill_manifest:
        _coding_system_prompt = _coding_system_prompt + _skill_manifest
except Exception as exc:  # noqa: BLE001 — skill 扫描失败不中断 codegen
    logger.warning("coding skill manifest 注入失败: %r", exc)
```
⚠️ **不碰 `AGENT_SYSTEM_PROMPT` 常量、不碰 DB seed** —— manifest 运行时拼到 `resolve_prompt` **之后**的字符串,绕开「DB-first 陈旧」坑(改常量对跑过 codegen 的老租户不生效)。注入后 → `_codegen_app_context_overlays` → `_coding_input["system_prompt"]` → `CodingAgent.get_system_prompt()`(`agent.py:178` 读 `ctx.input`)每轮重算(**含 `from_snapshot` resume 轮**,因 `get_system_prompt` 读 ctx.input 而非快照消息)→ resume 轮 manifest 也在。

### 5. 传递(无新字段)
前端把「请使用技能 X:」拼进 `userInput` → 经 pipeline message → `build_initial_user_message`(`agent.py:194` 读 `requirement`)自然带到首条 user message。agent 看系统提示「可用技能」段 + 用户「请使用技能 X」→ 主动调 `use_skill(X)`。无需改 `run_coding_pipeline` 签名。

## 数据流

上传 skill(`/skills`)→ `skills_root()`(桌面 `data_dir/skills`)→ 前端 `listSkills` 显示 → 用户 @ 选 → `userInput` 拼前缀 → agent 看 manifest + 用户消息 → `use_skill` 拷 skill 进 workspace + 读正文喂上下文 →(按需)`run_python` 跑 skill 脚本 → 产出。

## 错误处理

- `skills_root()` 为 None(`RUIJING_SKILLS_DISABLED=1` / 无目录)→ `scan()` 空 → manifest no-op、`use_skill` 返回「无可用技能」、不报错。
- manifest 注入异常 → `try/except` warning,不中断 codegen(照搬 `_append_skill_manifest` 容错)。
- `use_skill` 路径穿越 → `resolve()` + `parents` 校验拦截,返回 error。
- `run_python` 超时 30s `kill`;冻结态临时文件 `finally` 删除。

## 测试

- `test_coding_use_skill.py`:命中 skill → 拷文件 + 返正文;未知 name → 返可用清单;**路径穿越名(含 `../` / 非 ASCII)被拦**;空 `skills_root` → no-op 不报错。
- `test_coding_run_python.py`:非冻结 `python -c` 跑通(stdout 捕获);**冻结态 monkeypatch `is_frozen→True` 走 `--run-script` argv**(断言 argv 形态);超时路径;`cwd=workspace`。
- `test_coding_skill_manifest_injection.py`:注入点把 manifest 拼到 `resolve_prompt` 后的 prompt(monkeypatch `resolve_prompt` + `SkillRegistry.scan`);空集不拼;异常不中断。
- 工具数回归:`build_coding_tools` 改后比改前**多 2 个**且**含 `use_skill`/`run_python`、无重名**(用相对断言,不写死绝对基数——现有代码自身注释对基数口径不一)。
- 全量 backend 回归(pipeline/harness/coding 面不破)。

## 风险

1. **DB-first 陈旧(最高)**:已规避 = 运行时拼 manifest,不碰常量/DB。若误改常量,老租户(梦尔达等存量)需跑 `backend/scripts/refresh_coding_prompts.py`。
2. **冻结态 `run_python`**:照搬 ai_chat 已验逻辑 + 冻结分支单测;coding workspace 与 AIChat session workspace 独立,`cwd` 走 `_resolve_workspace_path`,测试覆盖。
3. **工具集回归(+2 工具)**:可能影响 token 预算 / `split_core_deferred` / 白名单;`use_skill`/`run_python` 作普通工具加入,工具数+含名单测兜底。
4. **路径穿越**:照搬 ai_chat 防护(slug 清洗 + parents 校验),单测覆盖。
5. **租户隔离缺失**:`skills_root()` 全局共享,多租户桌面所有租户看同一套 skill —— 已知现状(非本次引入),桌面单租户本期不动。
