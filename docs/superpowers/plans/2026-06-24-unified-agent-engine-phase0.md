# 统一智能体引擎 — Phase 0:引擎地基 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 `AgentProfile` 抽象 + 统一工具白名单解析器,作为「一套 BaseAgent 引擎 + 每场景一份 profile」的地基;清理死代码。纯加法,不改任何现有 agent 行为。

**Architecture:** 新增 `app/agents/profile.py`:`AgentProfile`(冻结 dataclass,描述一个场景需要什么)+ `resolve_profile(name)`(从统一来源解析工具名 = MCP yaml `tools_for_agent` 并集 ∪ 本地基础工具,并去掉暂停的 business_event 工具)。这层是新引擎读取场景配置的唯一入口,先落地、再在后续 Phase 接进 BaseAgent。

**Tech Stack:** Python 3.13, pytest, 现有 `app/tool_registry.py`(yaml 视图)、`app/coding/tools.py`(本地基础工具)。

## Global Constraints

- 引擎层不依赖任何具体场景;场景差异只进 `AgentProfile`。
- 工具白名单单一真相:MCP 工具来自 `tool_registry.yaml`(经 `tools_for_agent`),本地执行工具来自 `app/coding/tools.py:TOOL_DEFINITIONS`。**禁止把本地工具塞进 MCP yaml**(会破坏 `tests/test_tool_registry.py` 的 yaml↔mcp 一致性)。
- business_event 类工具当前暂停(见 `ai_chat/tools.py` 注释),`dev-apaas` profile 必须排除。
- 纯加法:本 Phase 不改 `run_agent`/`CodingAgent`/`SpecAgent` 任何运行时行为。
- TDD;每个 Task 独立可测、独立提交;只 `git add` 本 Task 涉及文件。
- venv:`backend/.venv/bin/python`;测试:`backend/.venv/bin/python -m pytest`。

---

### Task 1: `AgentProfile` 数据结构

**Files:**
- Create: `backend/app/agents/profile.py`
- Test: `backend/tests/test_agent_profile.py`

**Interfaces:**
- Produces: `AgentProfile`(frozen dataclass)字段 `name:str`, `system_prompt:str`, `tool_names:tuple[str,...]`, `skill_pack:tuple[str,...]=()`, `use_mcp:bool=True`, `max_turns:int=30`。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_agent_profile.py
from app.agents.profile import AgentProfile


def test_agent_profile_is_frozen_and_holds_scenario_config():
    p = AgentProfile(
        name="demo",
        system_prompt="你是助手",
        tool_names=("write_file", "read_file"),
        skill_pack=("apaas-conventions",),
        use_mcp=True,
        max_turns=20,
    )
    assert p.name == "demo"
    assert p.tool_names == ("write_file", "read_file")
    assert p.skill_pack == ("apaas-conventions",)
    assert p.use_mcp is True
    assert p.max_turns == 20
    # frozen: 不可改
    import dataclasses, pytest
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.name = "x"  # type: ignore
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_agent_profile.py -q`
Expected: FAIL（`ModuleNotFoundError: app.agents.profile`）

- [ ] **Step 3: 写最小实现**

```python
# backend/app/agents/profile.py
"""AgentProfile — 一套 BaseAgent 引擎的「场景配置」对象。

引擎对场景无知:它只消费 AgentProfile 字段。每个场景(dev-apaas / builder-config /
dev-fullcode)= 一份 profile。详见 docs/superpowers/specs/2026-06-24-unified-agent-engine-design.md
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgentProfile:
    name: str
    system_prompt: str
    tool_names: tuple[str, ...]
    skill_pack: tuple[str, ...] = ()
    use_mcp: bool = True
    max_turns: int = 30
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_agent_profile.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/agents/profile.py backend/tests/test_agent_profile.py
git commit -m "feat(agents): AgentProfile 场景配置对象(统一引擎地基)"
```

---

### Task 2: 统一工具白名单解析 + 命名 profile 注册

**Files:**
- Modify: `backend/app/agents/profile.py`
- Test: `backend/tests/test_agent_profile.py`

**Interfaces:**
- Consumes: `app.tool_registry.tools_for_agent`(yaml 视图)、`app.coding.tools.TOOL_DEFINITIONS`(7 个本地工具)。
- Produces:
  - `BASE_LOCAL_TOOLS: tuple[str,...]` = 本地执行工具名(从 `TOOL_DEFINITIONS` 派生)。
  - `resolve_profile(name: str) -> AgentProfile`。已知 name:`"dev-apaas"`。未知 name 抛 `KeyError`。

- [ ] **Step 1: 写失败测试**

```python
# 追加到 backend/tests/test_agent_profile.py
from app.agents.profile import resolve_profile, BASE_LOCAL_TOOLS


def test_base_local_tools_cover_the_seven_exec_tools():
    for name in ("read_file", "write_file", "edit_file", "run_command",
                 "glob_files", "grep_search", "start_serve"):
        assert name in BASE_LOCAL_TOOLS


def test_dev_apaas_profile_unions_mcp_and_local_tools_minus_paused():
    p = resolve_profile("dev-apaas")
    # 本地执行工具在内(让 agent 能直接写文件)
    assert "write_file" in p.tool_names
    # MCP workspace 工具也在内(run_agent 现有好行为:读/写/跑 workspace)
    assert "write_workspace_files" in p.tool_names
    assert "read_workspace_file" in p.tool_names
    # business_event 暂停工具被排除
    from app.tool_registry import load as _load
    paused = {n for n, m in _load()["tools"].items() if m.get("category") == "business_event"}
    assert paused.isdisjoint(set(p.tool_names))
    # 无重复
    assert len(p.tool_names) == len(set(p.tool_names))


def test_resolve_unknown_profile_raises():
    import pytest
    with pytest.raises(KeyError):
        resolve_profile("nope")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_agent_profile.py -q`
Expected: FAIL（`ImportError: cannot import name 'resolve_profile'`）

- [ ] **Step 3: 写实现**

```python
# 追加到 backend/app/agents/profile.py 顶部 import 区
from app.coding.tools import TOOL_DEFINITIONS
from app.tool_registry import load as _load_registry, tools_for_agent

# ── 本地执行工具(非 MCP,经 app/coding/tools.py execute_tool 跑)──
BASE_LOCAL_TOOLS: tuple[str, ...] = tuple(
    d["function"]["name"] for d in TOOL_DEFINITIONS if d.get("function", {}).get("name")
)


def _paused_tool_names() -> set[str]:
    """当前暂停、不暴露给任何 agent 的工具(business_event,见 ai_chat/tools.py 注释)。"""
    reg = _load_registry()
    paused = {n for n, m in reg["tools"].items() if m.get("category") == "business_event"}
    paused.add("list_apaas_form_menus_for_event")  # 只为建事件服务的 helper
    return paused


def _dev_apaas_tool_names() -> tuple[str, ...]:
    """dev-apaas 工具集 = run_agent 现有并集(builder∪coding∪config)∪ 本地工具 − 暂停。

    复刻 ai_chat/tools.py 现在跑通的并集,保证迁移时行为不退化。
    """
    allow = (
        set(tools_for_agent("builder"))
        | set(tools_for_agent("coding"))
        | set(tools_for_agent("config"))
    )
    allow |= set(BASE_LOCAL_TOOLS)
    allow -= _paused_tool_names()
    # 稳定顺序:本地工具在前,其余按名排序(确定性,便于测试/diff)
    local = [t for t in BASE_LOCAL_TOOLS if t in allow]
    rest = sorted(allow - set(local))
    return tuple(local + rest)


_PROFILE_BUILDERS = {
    "dev-apaas": lambda: AgentProfile(
        name="dev-apaas",
        system_prompt="",  # Phase 1 接入瘦提示词 + skill 包,这里先留空占位
        tool_names=_dev_apaas_tool_names(),
        skill_pack=(),
        use_mcp=True,
        max_turns=30,
    ),
}


def resolve_profile(name: str) -> AgentProfile:
    """按场景名解析 AgentProfile。未知 name 抛 KeyError。"""
    if name not in _PROFILE_BUILDERS:
        raise KeyError(f"未知 agent profile: {name!r}(已知:{sorted(_PROFILE_BUILDERS)})")
    return _PROFILE_BUILDERS[name]()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_agent_profile.py -q`
Expected: PASS（4 项全过)

- [ ] **Step 5: 提交**

```bash
git add backend/app/agents/profile.py backend/tests/test_agent_profile.py
git commit -m "feat(agents): resolve_profile + dev-apaas 工具白名单(复刻 run_agent 并集)"
```

---

### Task 3: 清理 `harness/tool_registry.py` 死 filter

**Files:**
- Modify: `backend/app/harness/tool_registry.py`
- Test: `backend/tests/test_harness_tool_registry.py`

**Interfaces:**
- `ToolRegistry` 保留(被 `agents/coding/tools.py:637` 构造);删 `_allowed_tools` 状态、`filter()` 方法,以及 `definitions`/`execute` 里据此过滤的死分支。`definitions` 直接返回全量;`execute` 直接委托。

**前置验证(已在规划期确认):** `grep -rn "\.filter(" backend/app --include=*.py` 对 `ToolRegistry` 无外部调用;`_allowed_tools` 仅在本文件内被引用。

- [ ] **Step 1: 写测试(锁定简化后契约)**

```python
# backend/tests/test_harness_tool_registry.py
from app.harness.tool_registry import ToolRegistry


def test_registry_exposes_full_coding_definitions():
    reg = ToolRegistry(profile="coding")
    names = reg.tool_names
    for n in ("read_file", "write_file", "edit_file", "run_command"):
        assert n in names


def test_registry_has_no_dead_filter_api():
    reg = ToolRegistry(profile="coding")
    assert not hasattr(reg, "filter")
    assert not hasattr(reg, "_allowed_tools")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_harness_tool_registry.py -q`
Expected: FAIL（`filter`/`_allowed_tools` 仍存在）

- [ ] **Step 3: 改实现(删死 filter)**

把 `backend/app/harness/tool_registry.py` 改成:

```python
"""Harness Core — Tool Registry

对 coding/tools.py 的薄包装,让 Agent 通过 registry 访问本地执行工具,
而不是直接 import 全局列表。
"""
from pathlib import Path
from typing import Awaitable, Callable, Optional

from app.coding.tools import TOOL_DEFINITIONS, execute_tool


class ToolRegistry:
    """本地执行工具注册表(read_file/write_file/edit_file/run_command/…)。"""

    def __init__(self, profile: str = "coding"):
        self._profile = profile
        self._definitions = list(TOOL_DEFINITIONS)

    @property
    def definitions(self) -> list[dict]:
        """返回给 LLM 的 tool schema(OpenAI function-calling 格式)。"""
        return self._definitions

    @property
    def tool_names(self) -> list[str]:
        return [d.get("function", {}).get("name", "") for d in self._definitions]

    async def execute(
        self,
        tool_name: str,
        arguments: dict,
        workspace_path: Path,
        progress_callback: Optional[Callable[[str], Awaitable[None] | None]] = None,
    ) -> str:
        """执行工具调用,委托给 coding/tools.py。"""
        return await execute_tool(tool_name, arguments, workspace_path, progress_callback)
```

- [ ] **Step 4: 跑测试确认通过 + 回归**

Run: `cd backend && .venv/bin/python -m pytest tests/test_harness_tool_registry.py -q && .venv/bin/python -m pytest tests/ -q -k "coding or tool_registry" 2>&1 | tail -5`
Expected: 新测试 PASS;coding/tool_registry 相关测试不回归。

- [ ] **Step 5: 提交**

```bash
git add backend/app/harness/tool_registry.py backend/tests/test_harness_tool_registry.py
git commit -m "refactor(harness): 删 ToolRegistry 死 filter/_allowed_tools(无外部调用)"
```

---

## Self-Review

- **Spec coverage**:本计划覆盖 spec §8 Phase 0(统一工具来源 + 删死 filter)与 §4.2 `AgentProfile` 地基。Phase 1-4(接 BaseAgent、退役 coding 流水线、收编 SpecAgent、dev-fullcode)各自独立成计划,本计划不含。
- **Placeholder 扫描**:`dev-apaas` 的 `system_prompt=""` 是**显式占位**,标注「Phase 1 接入」——非含糊 TODO,是有意分阶段。其余步骤均有完整代码与命令。
- **类型一致性**:`AgentProfile` 字段在 Task 1 定义,Task 2 `resolve_profile` 返回同一类型;`tool_names: tuple[str,...]` 全程一致。
- **不破坏一致性测试**:Task 2 用「yaml 并集 ∪ 本地工具」解析,不改 yaml,`test_tool_registry.py` 不受影响。
