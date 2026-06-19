# @skill 接入 coding 代码工作区 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 /coding 代码工作区的 coding agent 能 @ 选技能、读技能正文、把技能脚本拷进工作区并用 run_python 执行,系统提示带技能清单引导。

**Architecture:** 四处接线照搬 AIChat 已验参考实现:① 前端 CodingPage 镜像 AIChatPage 的 skill 接线;② 后端 build_coding_tools 加 use_skill 工具(executor 用 `_resolve_workspace_path(ctx)`);③ 加 run_python 工具(复用 ai_chat 的 `_build_python_argv` 冻结态逻辑);④ pipeline 在 resolve_prompt 之后运行时拼 skill manifest(不碰常量/DB,绕开 DB-first 陈旧)。skill 选择走 message 文本(无新 pipeline 字段)。

**Tech Stack:** Python 3.13 / FastAPI / pytest(asyncio_mode=auto,async 测试自动收集,**不写 `@pytest.mark.asyncio`**);Vue 3 `<script setup>` / Element Plus / vitest(`environment: node`,组件靠 `?raw` 源码字符串断言)。

## Global Constraints

- **绝不改 `AGENT_SYSTEM_PROMPT` 常量、绝不改 DB seed** —— skill manifest 必须运行时拼到 `resolve_prompt` 返回值之后(`pipeline.py:2110` 后)。改常量对跑过 codegen 的老租户不生效(DB-first)。
- use_skill / run_python executor 的错误一律**直接返回 `ToolResult(success=False, ...)`**,不要依赖 `_wrap_result` 的英文 `"Error:"` 前缀嗅探(本功能错误文案是中文「错误/缺少」,会被误判成 success)。
- use_skill 拷文件**必须**:`slug = re.sub(r"[^A-Za-z0-9_-]", "_", name)` 清洗 + `dest.resolve()` 后校验 `ws in dest.parents`(路径穿越防护)。
- run_python **复用** `from app.ai_chat.tools import _build_python_argv`,不重复实现冻结态分支。
- 不给 `run_coding_pipeline` 加新参数;skill 选择经前端拼进 `userInput` → message 文本传递。
- 多租户 skill 隔离不做(`skills_root()` 全局,桌面单租户,已知现状)。
- 后端测试命令:`cd backend && ./.venv/bin/python -m pytest <path> -v`。前端:`cd frontend && npx vitest run <path>`。

---

## Task 0: 模块级 import 兜底(被 Task 1/2 依赖)

**Files:**
- Modify: `backend/app/agents/coding/tools.py`(文件顶部 import 区)

**Interfaces:**
- Produces: 模块级可用名 `re`、`shutil`、`os`、`asyncio`、`runtime`、`Path`、`Any`、`ToolResult`、`Tool`、`_resolve_workspace_path` —— 供 Task 1/2 的 executor + 测试 monkeypatch(`coding_tools.runtime` / `coding_tools.asyncio`)用。

- [ ] **Step 1: 确认/补齐顶部 import**

打开 `backend/app/agents/coding/tools.py`,确认文件顶部(import 区)含以下名;缺哪个补哪个(已有则跳过,Python 重复 import 无害但保持整洁):

```python
import asyncio
import os
import re
import shutil
from pathlib import Path
from typing import Any
from app import runtime
```

`ToolResult` / `Tool` / `AgentContext` / `_resolve_workspace_path` 已在本文件定义或导入(无需新增)。

- [ ] **Step 2: 验证 import 不破**

Run: `cd backend && ./.venv/bin/python -c "import app.agents.coding.tools as t; print(t.runtime.is_frozen(), bool(t.asyncio))"`
Expected: 打印 `False <True 的真值>`(本地非冻结),无 ImportError。

- [ ] **Step 3: Commit**

```bash
git add backend/app/agents/coding/tools.py
git commit -m "chore(coding): 顶部补齐 use_skill/run_python 所需 import"
```

---

## Task 1: use_skill 工具(后端)

**Files:**
- Modify: `backend/app/agents/coding/tools.py`(新增 `_use_skill` executor + 在 `return tools`(约 `:745`)前注册 Tool)
- Test: `backend/tests/test_coding_use_skill.py`

**Interfaces:**
- Consumes: `_resolve_workspace_path(ctx) -> Path`(Task 0 已确保可 monkeypatch);`SkillRegistry`(`app.ai_chat.skills`,`.get(name)`/`.scan()`/`.read_skill_md(name)`)。
- Produces: 模块级 `async def _use_skill(args: dict[str, Any], ctx) -> ToolResult`;`build_coding_tools()` 返回的列表中出现 `name == "use_skill"` 的 Tool。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_coding_use_skill.py`:

```python
from pathlib import Path
from types import SimpleNamespace

from app.agents.coding import tools as coding_tools


def _make_skill(skills_dir: Path, name: str, body: str, extra: dict | None = None):
    d = skills_dir / "user" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: 测试技能\n---\n{body}\n", encoding="utf-8"
    )
    for fname, content in (extra or {}).items():
        (d / fname).write_text(content, encoding="utf-8")


def _get_tool(name: str):
    for t in coding_tools.build_coding_tools():
        if t.name == name:
            return t
    raise AssertionError(f"tool {name} not found")


async def test_use_skill_copies_files_and_returns_body(tmp_path, monkeypatch):
    skills_dir = tmp_path / "skills"
    _make_skill(skills_dir, "demo", "## 步骤\n1. 做点事", extra={"helper.py": "print('hi')"})
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(skills_dir))
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(coding_tools, "_resolve_workspace_path", lambda ctx: ws)

    res = await _get_tool("use_skill").execute({"name": "demo"}, SimpleNamespace(workspace_id="w1"))

    assert res.success
    assert "## 步骤" in res.content
    assert (ws / "skill_demo" / "helper.py").exists()
    assert not (ws / "skill_demo" / "SKILL.md").exists()


async def test_use_skill_unknown_lists_available(tmp_path, monkeypatch):
    skills_dir = tmp_path / "skills"
    _make_skill(skills_dir, "demo", "x")
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(skills_dir))
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(coding_tools, "_resolve_workspace_path", lambda ctx: ws)

    res = await _get_tool("use_skill").execute({"name": "nope"}, SimpleNamespace(workspace_id="w1"))

    assert not res.success
    assert "demo" in res.content  # 列出可用技能


async def test_use_skill_no_skills_is_graceful(tmp_path, monkeypatch):
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(tmp_path / "empty"))
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(coding_tools, "_resolve_workspace_path", lambda ctx: ws)

    res = await _get_tool("use_skill").execute({"name": "demo"}, SimpleNamespace(workspace_id="w1"))

    assert not res.success  # 无技能 → 友好报错,不抛异常
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_coding_use_skill.py -v`
Expected: FAIL(`tool use_skill not found` —— 工具尚未注册)。

- [ ] **Step 3: 写 executor**

在 `backend/app/agents/coding/tools.py` 中(放在 `build_coding_tools` 定义之前的模块级位置,例如紧挨 `RUN_PREVIEW_TOOL_DESC` 之后)新增:

```python
async def _use_skill(args: dict[str, Any], ctx) -> ToolResult:
    """coding 版 use_skill:把技能正文喂回上下文 + 把脚本/模板拷进当前 workspace。

    逻辑照搬 app.ai_chat.tools.execute_use_skill,但 workspace 走 _resolve_workspace_path(ctx),
    错误用 ToolResult 直接返回(不依赖 _wrap_result 的英文 'Error:' 前缀)。
    """
    from app.ai_chat.skills import SkillRegistry

    name = (args.get("name") or "").strip()
    if not name:
        return ToolResult(success=False, content="缺少 name 参数", error="MISSING_NAME")
    reg = SkillRegistry()
    skill = reg.get(name)
    if skill is None:
        avail = "、".join(s.name for s in reg.scan()) or "(暂无)"
        return ToolResult(success=False, content=f"没有名为 '{name}' 的技能。可用技能:{avail}", error="SKILL_NOT_FOUND")
    try:
        ws = _resolve_workspace_path(ctx).resolve()
    except Exception as e:
        return ToolResult(success=False, content=f"Error resolving workspace: {e}", error=str(e))
    slug = re.sub(r"[^A-Za-z0-9_-]", "_", name)
    dest = (ws / f"skill_{slug}").resolve()
    if ws not in dest.parents:
        return ToolResult(success=False, content="技能名非法,无法写入工作目录", error="BAD_SKILL_NAME")
    dest.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for item in sorted(skill.dir.iterdir()):
        if item.name == "SKILL.md":
            continue
        target = dest / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
            copied.append(f"skill_{slug}/{item.name}/")
        else:
            shutil.copy2(item, target)
            copied.append(f"skill_{slug}/{item.name}")
    body = reg.read_skill_md(name)
    files_note = ("已就绪文件(在工作目录):\n" + "\n".join(f"- {p}" for p in copied)) if copied else "(无附带文件)"
    src_tag = "平台预置(已审)" if skill.source == "platform" else "用户上传"
    content = (
        f"# 技能 {name}(来源:{src_tag};脚本可用 run_python 在当前工作区执行)\n\n"
        f"{body}\n\n---\n{files_note}\n\n"
        f"按上面说明执行:用 run_python 跑脚本(可直接打开这些文件)。"
    )
    return ToolResult(success=True, content=content)
```

- [ ] **Step 4: 注册 Tool**

在 `build_coding_tools` 末尾 `return tools` 之前插入:

```python
    tools.append(Tool(
        name="use_skill",
        description=(
            "读取某个技能(Skill)的完整说明并把它的脚本/模板准备到当前工作区,"
            "之后按说明用 run_python 执行。技能清单见系统提示「可用技能」。"
        ),
        parameters_schema={
            "type": "object",
            "properties": {"name": {"type": "string", "description": "技能名(与清单一致)"}},
            "required": ["name"],
        },
        execute=_use_skill,
    ))
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_coding_use_skill.py -v`
Expected: 3 passed。

- [ ] **Step 6: Commit**

```bash
git add backend/app/agents/coding/tools.py backend/tests/test_coding_use_skill.py
git commit -m "feat(coding): use_skill 工具(拷技能进 workspace + 喂正文,带路径穿越防护)"
```

---

## Task 2: run_python 工具 + 工具数回归(后端)

**Files:**
- Modify: `backend/app/agents/coding/tools.py`(新增 `_run_python` executor + 注册 Tool)
- Test: `backend/tests/test_coding_run_python.py`

**Interfaces:**
- Consumes: `_resolve_workspace_path(ctx)`;`from app.ai_chat.tools import _build_python_argv`;`coding_tools.runtime`(冻结态判断,可 monkeypatch);`coding_tools.asyncio`(可 monkeypatch)。
- Produces: 模块级 `async def _run_python(args, ctx) -> ToolResult`;`build_coding_tools()` 含 `name == "run_python"` 的 Tool。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_coding_run_python.py`:

```python
from types import SimpleNamespace

from app.agents.coding import tools as coding_tools


def _get_tool(name: str):
    for t in coding_tools.build_coding_tools():
        if t.name == name:
            return t
    raise AssertionError(f"tool {name} not found")


async def test_run_python_executes_and_captures_stdout(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(coding_tools, "_resolve_workspace_path", lambda ctx: ws)

    res = await _get_tool("run_python").execute(
        {"code": "print('hello-skill')"}, SimpleNamespace(workspace_id="w1")
    )

    assert res.success
    assert "hello-skill" in res.content


async def test_run_python_frozen_uses_run_script(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(coding_tools, "_resolve_workspace_path", lambda ctx: ws)
    monkeypatch.setattr(coding_tools.runtime, "is_frozen", lambda: True)

    captured = {}

    class _FakeProc:
        returncode = 0

        async def communicate(self):
            return (b"ok", b"")

    async def _fake_exec(*argv, **kw):
        captured["argv"] = argv
        captured["cwd"] = kw.get("cwd")
        return _FakeProc()

    monkeypatch.setattr(coding_tools.asyncio, "create_subprocess_exec", _fake_exec)

    res = await _get_tool("run_python").execute(
        {"code": "print(1)"}, SimpleNamespace(workspace_id="w1")
    )

    assert "--run-script" in captured["argv"]
    assert str(ws) == str(captured["cwd"])
    assert res.success


def test_build_coding_tools_has_skill_tools_and_no_dupes():
    names = [t.name for t in coding_tools.build_coding_tools()]
    assert "use_skill" in names
    assert "run_python" in names
    assert len(names) == len(set(names))  # 无重名
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_coding_run_python.py -v`
Expected: FAIL(`tool run_python not found`)。

- [ ] **Step 3: 写 executor**

在 `backend/app/agents/coding/tools.py` 中(`_use_skill` 之后)新增:

```python
async def _run_python(args: dict[str, Any], ctx) -> ToolResult:
    """coding 版 run_python:在当前 workspace 跑 Python(cwd=workspace)。

    冻结态用 sidecar --run-script,非冻结用解释器 -c,照搬 app.ai_chat.tools.execute_run_python。
    """
    import uuid as _uuid
    from app.ai_chat.tools import _build_python_argv

    code = args.get("code", "")
    if not code.strip():
        return ToolResult(success=False, content="缺少 code 参数", error="MISSING_CODE")
    try:
        ws = _resolve_workspace_path(ctx)
    except Exception as e:
        return ToolResult(success=False, content=f"Error resolving workspace: {e}", error=str(e))
    Path(ws).mkdir(parents=True, exist_ok=True)
    tmp_path = ""
    if runtime.is_frozen():
        tmp_path = str(Path(ws) / f".run_{_uuid.uuid4().hex}.py")
        Path(tmp_path).write_text(code, encoding="utf-8")
    argv = _build_python_argv(code, tmp_path)
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(ws),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return ToolResult(success=False, content="执行超时(30 秒)", error="TIMEOUT")
        out = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace")
        parts = []
        if out:
            parts.append(f"[stdout]\n{out.rstrip()}")
        if err:
            parts.append(f"[stderr]\n{err.rstrip()}")
        if proc.returncode != 0:
            parts.append(f"[exit code: {proc.returncode}]")
        result = "\n\n".join(parts) if parts else "[无输出]"
        if len(result) > 8000:
            result = result[:8000] + f"\n\n[输出已截断,原长度 {len(result)} 字符]"
        ok = proc.returncode == 0
        return ToolResult(success=ok, content=result, error=None if ok else f"exit {proc.returncode}")
    except Exception as e:
        return ToolResult(success=False, content=f"执行失败 - {e}", error=str(e))
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
```

- [ ] **Step 4: 注册 Tool**

在 `build_coding_tools` 的 `return tools` 之前(`use_skill` 注册之后)插入:

```python
    tools.append(Tool(
        name="run_python",
        description=(
            "在当前 coding 工作区执行 Python 代码(cwd 已 cd 到 workspace)。"
            "stdout/stderr 作为结果返回,执行超时 30 秒。配合 use_skill 跑技能脚本。"
        ),
        parameters_schema={
            "type": "object",
            "properties": {"code": {"type": "string", "description": "完整可执行的 Python 代码"}},
            "required": ["code"],
        },
        execute=_run_python,
        idempotent=False,
    ))
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_coding_run_python.py -v`
Expected: 4 passed。

- [ ] **Step 6: Commit**

```bash
git add backend/app/agents/coding/tools.py backend/tests/test_coding_run_python.py
git commit -m "feat(coding): run_python 工具(复用 ai_chat 冻结态 argv)+ 工具数回归"
```

---

## Task 3: skill manifest 运行时注入(pipeline)

**Files:**
- Modify: `backend/app/coding/pipeline.py`(新增 `_coding_skill_manifest_suffix()` 助手 + 在 `:2110` resolve_prompt 后调用)
- Test: `backend/tests/test_coding_skill_manifest_injection.py`

**Interfaces:**
- Consumes: `app.ai_chat.skills.SkillRegistry().scan()` + `build_skill_manifest(skills)`。
- Produces: 模块级 `def _coding_skill_manifest_suffix() -> str`(空集 / 异常 → 返回 `""`);`_coding_system_prompt` 在注入点被追加该 suffix。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_coding_skill_manifest_injection.py`:

```python
from pathlib import Path

from app.coding import pipeline
from app.ai_chat.skills import Skill


def test_manifest_suffix_appends_available_skills(monkeypatch):
    monkeypatch.setattr(
        "app.ai_chat.skills.SkillRegistry.scan",
        lambda self: [Skill(name="demo", description="演示技能", dir=Path("/x"), source="user")],
    )
    suffix = pipeline._coding_skill_manifest_suffix()
    assert "可用技能" in suffix
    assert "demo" in suffix


def test_manifest_suffix_empty_when_no_skills(monkeypatch):
    monkeypatch.setattr("app.ai_chat.skills.SkillRegistry.scan", lambda self: [])
    assert pipeline._coding_skill_manifest_suffix() == ""


def test_manifest_suffix_swallows_errors(monkeypatch):
    def _boom(self):
        raise RuntimeError("scan failed")

    monkeypatch.setattr("app.ai_chat.skills.SkillRegistry.scan", _boom)
    assert pipeline._coding_skill_manifest_suffix() == ""
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_coding_skill_manifest_injection.py -v`
Expected: FAIL(`module 'app.coding.pipeline' has no attribute '_coding_skill_manifest_suffix'`)。

- [ ] **Step 3: 写助手函数**

在 `backend/app/coding/pipeline.py` 模块级(靠近其它模块级 helper,`logger` 已在本文件定义)新增:

```python
def _coding_skill_manifest_suffix() -> str:
    """扫描技能库生成 manifest 文本,追加到 coding 系统提示末尾(渐进披露)。

    空集 / 扫描异常 → 返回空串(no-op),不中断 codegen。等价 ai_chat._append_skill_manifest,
    但作纯函数返回 suffix,便于在 resolve_prompt 之后运行时拼接(绕开 DB-first 陈旧)。
    """
    try:
        from app.ai_chat.skills import SkillRegistry, build_skill_manifest

        return build_skill_manifest(SkillRegistry().scan())
    except Exception as exc:  # noqa: BLE001 — 技能扫描失败不应中断 codegen
        logger.warning("coding skill manifest 注入失败: %r", exc)
        return ""
```

- [ ] **Step 4: 在注入点调用**

在 `backend/app/coding/pipeline.py` 的 `resolve_prompt(...)` 调用之后(约 `:2110`,即 `_coding_system_prompt = await resolve_prompt(...)` 这条语句紧后面)、`_codegen_app_context_overlays(...)` 调用(约 `:2119`)之前,插入一行:

```python
        _coding_system_prompt = _coding_system_prompt + _coding_skill_manifest_suffix()
```

(注意缩进:与 `_coding_system_prompt = await resolve_prompt(...)` 同级。)

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_coding_skill_manifest_injection.py -v`
Expected: 3 passed。

- [ ] **Step 6: Commit**

```bash
git add backend/app/coding/pipeline.py backend/tests/test_coding_skill_manifest_injection.py
git commit -m "feat(coding): 运行时把 skill manifest 拼进系统提示(不碰常量/DB,绕 DB-first 陈旧)"
```

---

## Task 4: 前端 skill 接线(CodingPage)

**Files:**
- Modify: `frontend/src/views/CodingPage.vue`
- Test: `frontend/src/views/CodingPage.skill.spec.ts`

**Interfaces:**
- Consumes: `listSkills()`(`@/api/skills`,返回 `{name, description, source, files}[]`);`UnifiedChatComposer` 已声明的 `skills` prop + `skill-picked` emit(AIChatPage 已在用,**组件本身无需改**);CodingPage 已有的 `userInput` ref。
- Produces: `availableSkills` ref + `onSkillPicked(name)` + composer 上的 `:skills`/`@skill-picked` 绑定。

- [ ] **Step 1: 写失败测试**

创建 `frontend/src/views/CodingPage.skill.spec.ts`:

```ts
import { describe, it, expect } from 'vitest'
import src from './CodingPage.vue?raw'

describe('CodingPage skill 接线', () => {
  it('imports listSkills from skills api', () => {
    expect(src).toContain("from '@/api/skills'")
    expect(src).toMatch(/listSkills\s*\(/)
  })

  it('binds :skills and @skill-picked on the composer', () => {
    expect(src).toContain(':skills="availableSkills"')
    expect(src).toContain('@skill-picked="onSkillPicked"')
  })

  it('onSkillPicked prepends 请使用技能 prefix to userInput', () => {
    expect(src).toMatch(/function onSkillPicked/)
    expect(src).toContain('请使用技能')
    expect(src).toMatch(/userInput\.value/)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/views/CodingPage.skill.spec.ts`
Expected: FAIL(源码尚无 `:skills="availableSkills"` 等)。

- [ ] **Step 3: 加 import + state + handler**

在 `frontend/src/views/CodingPage.vue` 的 `<script setup>` 中:

(a) 加 import(与其它 `@/api/...` import 放一起):
```ts
import { listSkills } from '@/api/skills'
```

(b) 加 state + 加载 + handler(放在已有 ref 声明区附近):
```ts
const availableSkills = ref<{ name: string; description: string }[]>([])
onMounted(() => {
  listSkills().then((s) => { availableSkills.value = s }).catch(() => { /* 无 skill 库则空 */ })
})
function onSkillPicked(name: string) {
  const prefix = `请使用技能 ${name}：`
  userInput.value = userInput.value ? `${prefix}${userInput.value}` : prefix
}
```
(`onMounted` 已在 CodingPage 顶部 import,新增这个是 additive,不动既有 onMounted。`ref` 也已 import。)

- [ ] **Step 4: 绑定到 composer**

在 `frontend/src/views/CodingPage.vue` 模板的 `<UnifiedChatComposer ...>`(约 `:264`)标签上,加两行属性(放在 `@send` 等事件旁):
```html
              :skills="availableSkills"
              @skill-picked="onSkillPicked"
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/views/CodingPage.skill.spec.ts`
Expected: 3 passed。

- [ ] **Step 6: 类型检查(不阻断,仅看本文件无新错)**

Run: `cd frontend && npx vue-tsc --noEmit -p tsconfig.json 2>&1 | grep CodingPage || echo "no new CodingPage type error"`
Expected: 不新增 CodingPage 相关类型错(注:仓库 `npm run build` 预存类型错,无关本任务)。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/views/CodingPage.vue frontend/src/views/CodingPage.skill.spec.ts
git commit -m "feat(coding): 前端接 @skill(镜像 AIChatPage:listSkills + :skills + onSkillPicked)"
```

---

## Final Verification(全部 task 后)

- [ ] 后端全量回归:`cd backend && ./.venv/bin/python -m pytest -q` → 期望 passed 数 = 改前(1174)+ 本计划新增测试数,0 failed。
- [ ] 前端相关回归:`cd frontend && npx vitest run src/views/CodingPage.skill.spec.ts src/views/coding` → 全 passed。
- [ ] (人工/真机,可延后)重打桌面包 → 在 /coding 输入框 @ 选一个上传的 superpowers skill → 看 agent 是否在系统提示「可用技能」段看到它、主动调 `use_skill`、必要时 `run_python` 跑脚本。此步需真机 + 已上传 skill,与 #1 live 验一并做。

## Self-Review(已对 spec 核查)

- **Spec 覆盖**:前端接线(Task 4)/ use_skill(Task 1)/ run_python(Task 2)/ manifest 注入(Task 3)/ 传递走 message 文本(无需 task,前端拼前缀已在 Task 4)/ 测试(各 task 内 + Final)/ 风险规避(DB-first→Task 3 运行时拼;路径穿越→Task 1;冻结态→Task 2 测试)全部有对应任务。
- **Placeholder 扫描**:无 TBD/TODO;每个代码步骤含完整代码。
- **类型一致**:`_use_skill`/`_run_python` 签名 `(args, ctx) -> ToolResult`,`_coding_skill_manifest_suffix() -> str`,`onSkillPicked(name: string)`,`availableSkills` 类型在 Task 2/3/4 引用一致。
