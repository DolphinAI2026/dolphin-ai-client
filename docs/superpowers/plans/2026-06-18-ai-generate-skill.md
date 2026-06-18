# AI 生成 Skill 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让桌面 ai-builder 的 agent 把可复用做法沉淀成一个 user skill（SKILL.md + 可选 helper），经一个新的 `create_skill` MCP 工具落盘进本地技能库；提供「存这次对话」「描述从零写」两个前端入口。

**Architecture:** 复用统一 agent（AIChatPage / run_agent）做生成与提炼，新增 `create_skill` 等 5 个 MCP 工具（`backend/app/mcp_tools/skill_authoring.py`）做落盘——MCP 工具同时服务 app 内 agent（经 mcp_bridge）与外部 MCP 客户端。落盘原语全复用 `SkillRegistry`，校验抽成共享函数。前端只加两个按钮 + 一个 dispatch 消费端，镜像现成的 `ai_builder_pending_app_dev` 机制。

**Tech Stack:** FastAPI + FastMCP（`@mcp.tool()` / `@apaas_tool` / `_ok` / `_err` / `ErrorCode`）/ SQLAlchemy（无新表，纯文件系统）/ Vue 3 + TS + Element Plus。后端测试 `cd backend && .venv/bin/python -m pytest <file> -v`（.venv=py3.13，SQLite）；前端 `cd frontend && npm run build:nocheck`。

**关键约定（来自代码接地，务必遵守）:**
- 业务错误统一用 `from app.mcp_envelope import ErrorCode, _err, _ok, apaas_tool`；**不存在** `_business_error`。`_ok(**fields)` → `{ok:true, ...}`；`_err(code, message, **fields)` → `{ok:false, error_code, message, ...}`。新错误码先加进 `ErrorCode` 类（值=字面串，勿改已有）。
- 装饰器顺序：`@mcp.tool()` 在上，`@apaas_tool(required=[...], message=...)` 在下，再 `async def`。
- **MCP 工具硬契约**：每个 `@mcp.tool()` 函数名必须在 `backend/tool_registry.yaml` 有 entry（含 `sections` + `agents`），否则 `tests/test_tool_registry.py::test_yaml_matches_mcp_server_source` 红。`agents` 取值只能是 `builder`/`coding`/`config`（不含 vibe）。本计划用 `agents: [builder, coding]`——统一 agent 的 allow 白名单是三者并集，故对它可见；且**不碰 config 白名单的 `len==74` 精确断言**（只动会破那个测试）。
- skill 名 ASCII（AI 路径强制）；改后端必重启 sidecar/进程（`run.py` reload=False），新 MCP 工具还要让 bridge 重新 ensure_loaded（重启最稳）。
- **只提交本任务列出的文件，不 `git add -A`**（工作树有并发会话的未提交改动）。
- 前端 `vue-tsc` 项目级失效，用 `npm run build:nocheck`。

---

## 文件结构

**后端：**
- `backend/app/ai_chat/skills.py` — 加模块级 `validate_skill_name` / `validate_skill_frontmatter`，重构现有内联校验点调它们。
- `backend/app/mcp_envelope.py` — `ErrorCode` 加 4 个 skill 错误码。
- `backend/app/mcp_tools/skill_authoring.py`（新）— `author_user_skill` 纯函数 + `register(mcp)` 注册 5 个 MCP 工具（create_skill / list_skills / read_skill_file / write_skill_file / update_skill_metadata）。
- `backend/app/mcp_server.py` — import + 调 `register`。
- `backend/tool_registry.yaml` — 加 5 个 entry。
- 测试 `backend/tests/test_skill_authoring.py`（新）。

**前端：**
- `frontend/src/views/AIChatPage.vue` — header-actions 加「存成技能」按钮 + `onSaveAsSkill`；onMounted 加 `skill_authoring` dispatch 消费端。
- `frontend/src/views/SkillLibraryPage.vue` — #actions 加「AI 生成技能」按钮 + `onAiGenerate`（producer）。

---

## Task 1: 共享校验器（skills.py）

**Files:**
- Modify: `backend/app/ai_chat/skills.py`（顶部加 `import re`；在 `_parse_frontmatter` 结束(~行79)后、`class SkillRegistry`(~行82)前加两个模块级函数；重构 `create_user_skill` ~行193-194、`clone_skill` ~行214-215）
- Modify: `backend/app/routes/skills.py`（上传校验 ~行61-68 改调共享函数 + 顶部 import）
- Test: `backend/tests/test_skill_authoring.py`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_skill_authoring.py`:
```python
import pytest
from app.ai_chat import skills as sk


def test_validate_skill_name_ok():
    sk.validate_skill_name("my-skill")  # 不抛
    sk.validate_skill_name("good-name_1", require_ascii=True)


def test_validate_skill_name_rejects_path_sep_and_dots():
    for bad in ("a/b", "a\\b", ".", ".."):
        with pytest.raises(ValueError):
            sk.validate_skill_name(bad)


def test_validate_skill_name_rejects_empty():
    with pytest.raises(ValueError):
        sk.validate_skill_name("")
    with pytest.raises(ValueError):
        sk.validate_skill_name("   ")


def test_validate_skill_name_ascii_gate():
    sk.validate_skill_name("中文名")  # 默认不强制 ASCII，不抛
    with pytest.raises(ValueError):
        sk.validate_skill_name("中文名", require_ascii=True)


def test_validate_skill_frontmatter_ok():
    name, desc = sk.validate_skill_frontmatter({"name": "x", "description": "y"})
    assert name == "x" and desc == "y"


def test_validate_skill_frontmatter_missing():
    with pytest.raises(ValueError):
        sk.validate_skill_frontmatter({"name": "x"})
    with pytest.raises(ValueError):
        sk.validate_skill_frontmatter({"description": "y"})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_skill_authoring.py -v`
Expected: FAIL（`module 'app.ai_chat.skills' has no attribute 'validate_skill_name'`）

- [ ] **Step 3: 实现两个共享函数 + 重构内联点**

`backend/app/ai_chat/skills.py` 顶部 import 区加（若无 `re`）：
```python
import re
```

在 `_parse_frontmatter` 定义结束后、`class SkillRegistry` 之前，加：
```python
_ASCII_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def validate_skill_name(name: str, *, require_ascii: bool = False) -> None:
    """校验 skill 名合法性，非法抛 ValueError（路由/工具层映射成 4xx / error_code）。

    默认沿用历史行为（仅拦空串 + 路径分隔 + ./..）；require_ascii=True 额外要求
    纯 ASCII 字母/数字/连字符/下划线/点 —— AI 生成路径用，防 LLM 造非 ASCII 名引发并发覆盖/路径问题。
    """
    n = (name or "").strip()
    if not n:
        raise ValueError("技能名不能为空")
    if "/" in n or "\\" in n or n in (".", ".."):
        raise ValueError(f"非法技能名: {name}")
    if require_ascii and not _ASCII_SKILL_NAME_RE.match(n):
        raise ValueError(f"技能名必须为 ASCII（字母/数字/连字符/下划线）: {name}")


def validate_skill_frontmatter(meta: dict) -> tuple[str, str]:
    """校验 SKILL.md frontmatter 必含 name + description，返回 (name, description)（已 strip）。"""
    name = (meta.get("name") or "").strip()
    desc = (meta.get("description") or "").strip()
    if not name or not desc:
        raise ValueError("SKILL.md frontmatter 必须含 name 和 description")
    return name, desc
```

重构 `create_user_skill`（把行193-194 的 `if "/" in name ... raise ValueError(...)` 两行替换为）：
```python
    validate_skill_name(name)
```

重构 `clone_skill`（把行214-215 同样的 new_name 内联检查替换为）：
```python
    validate_skill_name(new_name)
```

`backend/app/routes/skills.py`：顶部 import 改为（在原 `from app.ai_chat.skills import ...` 上补两个名）：
```python
from app.ai_chat.skills import (
    SkillRegistry,
    _parse_frontmatter,
    skills_root,
    validate_skill_frontmatter,
    validate_skill_name,
)
```
把 `_extract_user_skill_zip` 内行61-68 这段：
```python
        meta, _ = _parse_frontmatter(z.read(skill_md).decode("utf-8", errors="replace"))
        name = (meta.get("name") or "").strip()
        desc = (meta.get("description") or "").strip()
        if not name or not desc:
            raise ValueError("SKILL.md frontmatter 必须含 name 和 description")
        # name 自身不能含路径分隔（防 frontmatter 注入越界）。
        if "/" in name or "\\" in name or name in (".", ".."):
            raise ValueError(f"非法技能名: {name}")
```
替换为（行为等价；ValueError 仍被上传端点 catch→400）：
```python
        meta, _ = _parse_frontmatter(z.read(skill_md).decode("utf-8", errors="replace"))
        name, _desc = validate_skill_frontmatter(meta)
        validate_skill_name(name)
```
（保留其后行69-73 的平台 shadow 冲突拦截不动。）

- [ ] **Step 4: 跑测试确认通过 + 不回归**

Run: `cd backend && .venv/bin/python -m pytest tests/test_skill_authoring.py tests/test_skill_files.py tests/test_skill_file_routes.py tests/test_skills_routes.py -v`
Expected: PASS（新校验测试绿 + 原有 skill 测试不回归）。
> **必跑 `tests/test_skills_routes.py`**：它覆盖被本任务改动的上传校验路径 `_extract_user_skill_zip`（zip-slip / 平台 shadow 拦截 / 空名缺描述等负路径），是验证「重构行为等价」的关键回归。

- [ ] **Step 5: Commit**

```bash
git add backend/app/ai_chat/skills.py backend/app/routes/skills.py backend/tests/test_skill_authoring.py
git commit -m "feat(skill): 抽共享校验器 validate_skill_name/validate_skill_frontmatter + 收编内联校验点"
```

---

## Task 2: skill_authoring.py — author_user_skill 纯函数 + 错误码

**Files:**
- Modify: `backend/app/mcp_envelope.py`（`ErrorCode` 加 4 个常量）
- Create: `backend/app/mcp_tools/skill_authoring.py`（先只写 `author_user_skill` 纯函数 + import；register 在 Task 3 加）
- Test: `backend/tests/test_skill_authoring.py`（追加）

- [ ] **Step 1: 写失败测试（追加到 test_skill_authoring.py）**

```python
from app.ai_chat import skills as sk
from app.mcp_tools import skill_authoring as sa


@pytest.fixture
def reg(tmp_path, monkeypatch):
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(tmp_path / "skills"))
    for source, name in (("user", "u1"), ("platform", "p1")):
        d = tmp_path / "skills" / source / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: d\n---\n正文", encoding="utf-8")
    return sk.SkillRegistry()


def test_author_user_skill_writes_skill_md_and_helpers(reg):
    res = sa.author_user_skill(
        "weekly-report",
        "Use when 用户要生成周报",
        "## 步骤\n1. 收集数据\n2. 渲染",
        helpers=[{"path": "helper.py", "content": "print('hi')"}],
        registry=reg,
    )
    assert res["name"] == "weekly-report"
    assert "SKILL.md" in res["files"] and "helper.py" in res["files"]
    md = reg.read_skill_file("weekly-report", "SKILL.md")
    assert "name: weekly-report" in md and "Use when 用户要生成周报" in md
    assert "## 步骤" in md and "1. 收集数据" in md
    assert reg.read_skill_file("weekly-report", "helper.py") == "print('hi')"
    assert reg.get("weekly-report").source == "user"


def test_author_user_skill_dup_raises(reg):
    with pytest.raises(ValueError):  # u1 已存在
        sa.author_user_skill("u1", "d", "x", registry=reg)


def test_author_user_skill_non_ascii_name_raises(reg):
    with pytest.raises(ValueError):
        sa.author_user_skill("中文技能", "d", "x", registry=reg)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_skill_authoring.py -v`
Expected: FAIL（`No module named 'app.mcp_tools.skill_authoring'`）

- [ ] **Step 3: 加错误码 + 写 author_user_skill**

`backend/app/mcp_envelope.py` 的 `ErrorCode` 类里追加（放在已有常量之后，勿改已有值）：
```python
    SKILL_EXISTS = "SKILL_EXISTS"
    SKILL_NAME_INVALID = "SKILL_NAME_INVALID"
    SKILL_WRITE_FAILED = "SKILL_WRITE_FAILED"
    SKILL_READONLY = "SKILL_READONLY"
    SKILLS_UNSUPPORTED = "SKILLS_UNSUPPORTED"
```
> 已核实（grep mcp_envelope.py）：`ErrorCode.NOT_FOUND`(行91)、`INVALID_PARAMS`(行44) 已存在可直接用；**`FORBIDDEN` 不存在**，故平台只读的 PermissionError 用上面新增的 `SKILL_READONLY`。

新建 `backend/app/mcp_tools/skill_authoring.py`：
```python
"""AI 生成 Skill —— skill 创作 MCP 工具（落盘原语复用 SkillRegistry）。

核心 create_skill 让 agent 把可复用做法沉淀成一个 user skill（SKILL.md + 可选 helper）。
另暴露 list/read/write/update 给 agent 迭代与外部 MCP 客户端创作。删除不走 MCP（留 REST/IDE）。
"""
from __future__ import annotations

from app.ai_chat.skills import (
    SkillRegistry,
    skills_root,
    validate_skill_frontmatter,
    validate_skill_name,
)
from app.mcp_envelope import ErrorCode, _err, _ok, apaas_tool


def author_user_skill(
    name: str,
    description: str,
    instructions: str,
    helpers: list[dict] | None = None,
    *,
    registry: SkillRegistry | None = None,
) -> dict:
    """建一个 user skill：建骨架 → 覆盖 SKILL.md（frontmatter+正文）→ 写 helper。

    纯同步、可单测。校验失败 / 重名 / 写失败抛 ValueError（由 create_skill 包装映射 error_code）。
    """
    reg = registry or SkillRegistry()
    validate_skill_name(name, require_ascii=True)
    validate_skill_frontmatter({"name": name, "description": description})
    reg.create_user_skill(name)  # 重名 / 环境不支持 → ValueError
    content = f"---\nname: {name}\ndescription: {description}\n---\n{instructions}\n"
    reg.write_skill_file(name, "SKILL.md", content)
    for h in (helpers or []):
        if not isinstance(h, dict):
            continue  # agent 可能误传字符串等，跳过非法项（防 AttributeError）
        path = str(h.get("path") or "").strip()
        if not path:
            continue
        reg.write_skill_file(name, path, str(h.get("content") or ""))  # 越界 path 由 _resolve_file 拦 ValueError
    s = reg.get(name)
    return {"name": name, "files": reg.list_skill_files(name), "dir": str(s.dir) if s else ""}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_skill_authoring.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/mcp_envelope.py backend/app/mcp_tools/skill_authoring.py backend/tests/test_skill_authoring.py
git commit -m "feat(skill): skill_authoring.author_user_skill 纯函数 + ErrorCode skill 错误码"
```

---

## Task 3: 注册 5 个 MCP 工具 + tool_registry.yaml + 通过 drift 测试

**Files:**
- Modify: `backend/app/mcp_tools/skill_authoring.py`（加 `register(mcp)` + 5 个 `@mcp.tool()`）
- Modify: `backend/app/mcp_server.py`（import + 调 register）
- Modify: `backend/tool_registry.yaml`（加 5 个 entry）
- Test: `backend/tests/test_tool_registry.py`（不改源码，跑它验证 drift 闸通过）

- [ ] **Step 1: 先跑 drift 测试确认当前绿（基线）**

Run: `cd backend && .venv/bin/python -m pytest tests/test_tool_registry.py -q`
Expected: PASS（改之前的基线；改完若红，按报错补齐 yaml/计数）

- [ ] **Step 2: 写 register + 5 个工具**

`backend/app/mcp_tools/skill_authoring.py` 末尾追加。⚠️ **docstring 必须是纯字面量**——`"""..."""+ 变量` 会让 `__doc__=None`（实测验证），FastMCP 拿到空描述、search_tools 命中与方法论注入全废。故把 skill-creator 方法论**直接写进 create_skill 的三引号 docstring 字面量**（不引用任何变量）：
```python
_registered_mcp_ids: set[int] = set()


def register(mcp):
    """把 skill 创作工具注册进给定的 FastMCP 实例（幂等）。"""
    marker = id(mcp)
    if marker in _registered_mcp_ids:
        return
    _registered_mcp_ids.add(marker)

    @mcp.tool()
    @apaas_tool(
        required=["name", "description", "instructions"],
        message="create_skill 需要 name / description / instructions",
    )
    async def create_skill(
        name: str,
        description: str,
        instructions: str,
        helpers: list | None = None,
        tenant_id: int = 0,
        user_id: int = 0,
    ) -> dict:
        """Use when 用户想把一段可复用做法沉淀成新技能（存成技能 / AI 创建 skill / 沉淀做法）。在本地技能库创建一个 user skill（SKILL.md + 可选 helper 文件）。仅桌面端可用。

        写好一个 skill 的要点：
        - name：英文 kebab-case（如 weekly-report），ASCII、唯一。
        - description：第三人称、触发导向的一句『Use when …』——决定以后 use_skill 触发准不准，必须写清『什么时候该用』并含可被关键词命中的场景词。
        - instructions：SKILL.md 正文，写具体编号步骤（命令式）、单一职责、精简；细节用引用文件而非堆正文。
        - helpers：确定性逻辑（解析/转换/调用）优先写成 helper 脚本（如 helper.py，用 run_python 跑），而非让模型每次重做。每项 {path, content}。
        """
        if skills_root() is None:
            return _err(ErrorCode.SKILLS_UNSUPPORTED, "当前环境不支持创建技能（仅桌面端）")
        reg = SkillRegistry()
        if reg.get(name) is not None:
            return _err(ErrorCode.SKILL_EXISTS, f"技能已存在: {name}")
        try:
            res = author_user_skill(name, description, instructions, helpers, registry=reg)
        except ValueError as e:
            return _err(ErrorCode.SKILL_NAME_INVALID, str(e))
        except Exception as e:  # noqa: BLE001
            return _err(ErrorCode.SKILL_WRITE_FAILED, str(e))
        return _ok(**res)

    @mcp.tool()
    async def list_skills(tenant_id: int = 0, user_id: int = 0) -> dict:
        """列出本地技能库里的全部技能（name/description/source）。创建前可用它查重名。"""
        if skills_root() is None:
            return _err(ErrorCode.SKILLS_UNSUPPORTED, "当前环境无技能库（仅桌面端）")
        items = [
            {"name": s.name, "description": s.description, "source": s.source}
            for s in SkillRegistry().scan()
        ]
        return _ok(skills=items)

    @mcp.tool()
    @apaas_tool(required=["name", "path"], message="read_skill_file 需要 name / path")
    async def read_skill_file(name: str, path: str, tenant_id: int = 0, user_id: int = 0) -> dict:
        """读某个技能内一个文件的内容（如 SKILL.md / helper.py），用于回看与迭代。"""
        try:
            content = SkillRegistry().read_skill_file(name, path)
        except FileNotFoundError as e:
            return _err(ErrorCode.NOT_FOUND, str(e))
        except ValueError as e:
            return _err(ErrorCode.INVALID_PARAMS, str(e))
        return _ok(name=name, path=path, content=content)

    @mcp.tool()
    @apaas_tool(required=["name", "path", "content"], message="write_skill_file 需要 name / path / content")
    async def write_skill_file(name: str, path: str, content: str, tenant_id: int = 0, user_id: int = 0) -> dict:
        """往一个 user 技能写/覆盖一个文件（仅 user skill，越界与 platform 只读由底层拦）。"""
        try:
            SkillRegistry().write_skill_file(name, path, content)
        except FileNotFoundError as e:
            return _err(ErrorCode.NOT_FOUND, str(e))
        except PermissionError as e:
            return _err(ErrorCode.SKILL_READONLY, str(e))
        except ValueError as e:
            return _err(ErrorCode.INVALID_PARAMS, str(e))
        except Exception as e:  # noqa: BLE001
            return _err(ErrorCode.SKILL_WRITE_FAILED, str(e))
        return _ok(name=name, path=path)

    @mcp.tool()
    @apaas_tool(required=["name"], message="update_skill_metadata 需要 name")
    async def update_skill_metadata(
        name: str,
        description: str | None = None,
        tags: list | None = None,
        display_name: str | None = None,
        tenant_id: int = 0,
        user_id: int = 0,
    ) -> dict:
        """改写一个 user 技能 SKILL.md 的 frontmatter（保留正文）。"""
        try:
            SkillRegistry().update_skill_metadata(
                name, description=description, tags=tags, display_name=display_name
            )
        except FileNotFoundError as e:
            return _err(ErrorCode.NOT_FOUND, str(e))
        except PermissionError as e:
            return _err(ErrorCode.SKILL_READONLY, str(e))
        except Exception as e:  # noqa: BLE001
            return _err(ErrorCode.SKILL_WRITE_FAILED, str(e))
        return _ok(name=name)

    return {
        "create_skill": create_skill,
        "list_skills": list_skills,
        "read_skill_file": read_skill_file,
        "write_skill_file": write_skill_file,
        "update_skill_metadata": update_skill_metadata,
    }
```
> 注：已核实 `ErrorCode.NOT_FOUND`(行91) / `INVALID_PARAMS`(行44) 存在可直接用；平台只读 PermissionError 用 Task 2 新增的 `SKILL_READONLY`（`FORBIDDEN` 不存在，勿用）。`apaas_tool` 缺参时自动返回 `INVALID_PARAMS`。

`backend/app/mcp_server.py`：在 import 段（`workspace_core` import 之后，约行569-570）加：
```python
from app.mcp_tools.skill_authoring import register as _register_skill_authoring_tools
```
在调用段（form_components unpack 结束后、drift 断言之前，约行763-764）加：
```python
_register_skill_authoring_tools(mcp)
```

- [ ] **Step 3: 加 tool_registry.yaml entry**

`backend/tool_registry.yaml` 的 `tools:` 下加 5 个 entry（缩进对齐已有项；`search_hint` 可选但建议给，提升 search_tools 命中）：
```yaml
  create_skill:
    sections: [global]
    agents: [builder, coding]
    category: skill_learning
    description: "把一段可复用做法沉淀成一个新技能(SKILL.md+可选helper)，存进本地技能库。"
    search_hint: "创建技能 沉淀 存成技能 AI创建 skill author create"
  list_skills:
    sections: [global]
    agents: [builder, coding]
    category: skill_learning
    description: "列出本地技能库的全部技能，创建前查重名。"
    search_hint: "技能列表 skill list"
  read_skill_file:
    sections: [global]
    agents: [builder, coding]
    category: skill_learning
    description: "读某个技能内的文件(SKILL.md/helper)，用于迭代。"
    search_hint: "读技能文件 skill read"
  write_skill_file:
    sections: [global]
    agents: [builder, coding]
    category: skill_learning
    description: "往一个user技能写/覆盖一个文件。"
    search_hint: "写技能文件 skill write"
  update_skill_metadata:
    sections: [global]
    agents: [builder, coding]
    category: skill_learning
    description: "改写一个user技能SKILL.md的frontmatter(描述/标签)。"
    search_hint: "改技能元数据 skill metadata"
```

> 注：`category` 用已有的 `skill_learning`（不是新造 `skill_authoring`）——`tool_contract_service._CATEGORY_PROFILES` 已登记 skill_learning=(read_only=False, 不写 workspace/apaas/deploy)，语义贴合「写本地技能库不碰 apaas」；新造 category 会落兜底 profile（语义错）且无契约校验。

- [ ] **Step 4: 跑 drift / 注册 / 契约测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_tool_registry.py tests/test_tool_contracts_schema.py -q`
Expected: PASS。
- 若 `test_yaml_matches_mcp_server_source` 报 `only_src`/`only_yaml`：核对 5 个工具名 yaml↔源码一致。
- `test_config_whitelist_matches_current_expected`（==74）**不应受影响**（我们用 [builder, coding] 不含 config）；若它红，说明误把某工具标了 `config`，改回。
- `test_runtime_drift_check_passes_in_clean_state`：确认 register 真被 mcp_server 调到。
- `test_tool_contracts_schema.py`：确认 5 个新工具的 `skill_learning` category 契约可解析、不报错。

- [ ] **Step 5: 写 MCP 包装层 async 测试（覆盖 _ok/_err 映射 + docstring 非空）**

`@mcp.tool()` 原样返回 fn，`register()` 把 5 个工具装进返回 dict，故可建临时 FastMCP 取出直接 await。追加到 `backend/tests/test_skill_authoring.py`：
```python
from mcp.server.fastmcp import FastMCP
from app.mcp_tools import skill_authoring as sa
from app.mcp_envelope import ErrorCode


def _mk_tools(tmp_path, monkeypatch, *, with_root=True):
    if with_root:
        monkeypatch.setenv("RUIJING_SKILLS_DIR", str(tmp_path / "skills"))
        d = tmp_path / "skills" / "platform" / "p1"  # 一个 platform skill 测只读
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("---\nname: p1\ndescription: d\n---\n正文", encoding="utf-8")
        (d / "helper.py").write_text("print(1)", encoding="utf-8")
    else:
        monkeypatch.delenv("RUIJING_SKILLS_DIR", raising=False)
        monkeypatch.delenv("DESKTOP_MODE", raising=False)
        monkeypatch.delenv("APAAS_WORKSPACE_ROOT", raising=False)
    sa._registered_mcp_ids.clear()  # 防 id 复用导致 register 被幂等跳过
    m = FastMCP("test")
    return sa.register(m), m


@pytest.mark.asyncio
async def test_create_skill_ok(tmp_path, monkeypatch):
    tools, _ = _mk_tools(tmp_path, monkeypatch)
    res = await tools["create_skill"](
        name="weekly-report", description="Use when 生成周报",
        instructions="## 步骤\n1. x", helpers=[{"path": "helper.py", "content": "print(1)"}],
    )
    assert res["ok"] is True and res["name"] == "weekly-report"
    assert "SKILL.md" in res["files"] and "helper.py" in res["files"]


@pytest.mark.asyncio
async def test_create_skill_dup_returns_skill_exists(tmp_path, monkeypatch):
    tools, _ = _mk_tools(tmp_path, monkeypatch)
    await tools["create_skill"](name="dupe", description="d", instructions="x")
    res = await tools["create_skill"](name="dupe", description="d", instructions="x")
    assert res["ok"] is False and res["error_code"] == ErrorCode.SKILL_EXISTS


@pytest.mark.asyncio
async def test_create_skill_non_ascii_returns_name_invalid(tmp_path, monkeypatch):
    tools, _ = _mk_tools(tmp_path, monkeypatch)
    res = await tools["create_skill"](name="中文技能", description="d", instructions="x")
    assert res["ok"] is False and res["error_code"] == ErrorCode.SKILL_NAME_INVALID


@pytest.mark.asyncio
async def test_create_skill_unsupported_when_no_root(tmp_path, monkeypatch):
    tools, _ = _mk_tools(tmp_path, monkeypatch, with_root=False)
    res = await tools["create_skill"](name="x", description="d", instructions="y")
    assert res["ok"] is False and res["error_code"] == ErrorCode.SKILLS_UNSUPPORTED


@pytest.mark.asyncio
async def test_write_platform_skill_returns_readonly(tmp_path, monkeypatch):
    tools, _ = _mk_tools(tmp_path, monkeypatch)
    res = await tools["write_skill_file"](name="p1", path="helper.py", content="evil")
    assert res["ok"] is False and res["error_code"] == ErrorCode.SKILL_READONLY


@pytest.mark.asyncio
async def test_read_missing_skill_returns_not_found(tmp_path, monkeypatch):
    tools, _ = _mk_tools(tmp_path, monkeypatch)
    res = await tools["read_skill_file"](name="nope", path="SKILL.md")
    assert res["ok"] is False and res["error_code"] == ErrorCode.NOT_FOUND


def test_create_skill_description_non_empty(tmp_path, monkeypatch):
    """防 docstring 拼接坑：FastMCP 工具 description 必须非空且含触发词。"""
    _, m = _mk_tools(tmp_path, monkeypatch)
    tool = next(t for t in m._tool_manager.list_tools() if t.name == "create_skill")
    assert tool.description and "Use when" in tool.description
```

- [ ] **Step 6: 跑 MCP 包装层测试 + 真注册冒烟（同步 list_tools）**

Run: `cd backend && .venv/bin/python -m pytest tests/test_skill_authoring.py -v`
Expected: 全 PASS（含包装层 _ok/_err 映射 + description 非空）。

Run（注册冒烟，`list_tools()` 是**同步**方法，勿用 asyncio.run）：
`cd backend && .venv/bin/python -c "import app.mcp_server as m; names={t.name for t in m.mcp._tool_manager.list_tools()}; print('create_skill' in names, 'list_skills' in names)"`
Expected: `True True`（若 list_tools 形态不符，回退 `m.mcp._tool_manager._tools.keys()`）。

- [ ] **Step 7: Commit**

```bash
git add backend/app/mcp_tools/skill_authoring.py backend/app/mcp_server.py backend/tool_registry.yaml backend/tests/test_skill_authoring.py
git commit -m "feat(skill): 注册 create_skill 等 5 个 skill 创作 MCP 工具 + tool_registry entry + 包装层测试"
```

---

## Task 4: 前端入口1（AIChatPage 存成技能按钮 + skill_authoring 消费端）

**Files:**
- Modify: `frontend/src/views/AIChatPage.vue`（header-actions ~行89 后加按钮；`<script>` 加 `onSaveAsSkill`；onMounted ~行2658 后加 dispatch 消费分支）

- [ ] **Step 1: 加「存成技能」按钮（模板）**

在 `<div class="header-actions">` 内、artifacts-toggle 按钮（~行89 `</button>`）之后加：
```html
      <button
        v-if="currentSession"
        class="save-skill-btn"
        title="把本次会话产出整理成一个可复用技能"
        @click="onSaveAsSkill"
      >
        <AppIcon name="sparkles" :size="14" /> 存成技能
      </button>
```
> 若 `AppIcon` 无 `sparkles`，执行时 `grep -rn "name=\"" frontend/src/components | grep -i spark` 确认可用图标名，没有就用已有的（如 `name="plus"`）或省略图标。

- [ ] **Step 2: 加 onSaveAsSkill（script）**

在 `<script setup>` 内（靠近 `onDraftSend` / `onSend` 处）加：
```typescript
const SKILL_AUTHORING_PROMPT =
  '回顾我们这次对话里完成的可复用做法，把它沉淀成一个技能（skill）。请：'
  + '1) 想清楚这个技能解决什么问题、什么时候该用（写进 description，用第三人称「Use when …」触发式）；'
  + '2) 把步骤写成具体编号指令（instructions）；'
  + '3) 有确定性逻辑就写成 helper 脚本而非长说明；'
  + '4) 技能名用英文 kebab-case。'
  + '然后用 search_tools 找到并激活 create_skill 工具，调它把技能存进我的技能库。'
  + '存好后告诉我技能名，并提示我可以在技能库 / Skill IDE 里继续编辑。'

async function onSaveAsSkill() {
  if (!currentSession.value) return
  inputText.value = SKILL_AUTHORING_PROMPT
  await nextTick()
  onSend()
}
```
> `nextTick` 若未 import，在顶部 `import { nextTick } from 'vue'`（页面多处已用，通常已 import；执行时确认）。

- [ ] **Step 3: 加 skill_authoring dispatch 消费端（onMounted）**

在 onMounted 里、现有 `app_dev` 消费分支的 `return` 之后（~行2658）、Landing incomingPrompt 分支（~行2661）之前，插入：
```typescript
    const skillRaw = route.query.skill_authoring === '1'
      ? sessionStorage.getItem('ai_builder_pending_skill_authoring')
      : null
    if (!currentSession.value && skillRaw) {
      sessionStorage.removeItem('ai_builder_pending_skill_authoring')
      try {
        const payload = JSON.parse(skillRaw) as { message?: string }
        const created = await aiChatApi.createSession({ selected_llm_config_id: selectedLlmId.value })
        sessions.value.unshift(created)
        await loadSession(created.id)
        inputText.value = (payload.message || '').trim()
          || '我要做一个新技能（skill）。请先问我它要解决什么场景、什么时候触发，再帮我写 SKILL.md 和必要的 helper 脚本，然后用 search_tools 激活 create_skill 存进我的技能库。'
        router.replace({ path: `/ai-chat/${created.id}` })
        await nextTick()
        onSend()
      } catch (e) {
        console.error('AI 生成技能交接失败', e)
        ElMessage.error('进入技能生成失败')
      }
      return
    }
```

- [ ] **Step 4: 编译验证**

Run: `cd frontend && npm run build:nocheck`
Expected: 成功，无新类型/编译错。诚实说明：按钮点击、注入发送、消费端建会话需人工 preview 验。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/AIChatPage.vue
git commit -m "feat(skill): AIChatPage 存成技能按钮 + skill_authoring dispatch 消费端"
```

---

## Task 5: 前端入口2（SkillLibraryPage AI 生成技能按钮 producer）

**Files:**
- Modify: `frontend/src/views/SkillLibraryPage.vue`（#actions 槽 ~行7/18 加按钮；`<script>` 加 `onAiGenerate`）

- [ ] **Step 1: 加「AI 生成技能」按钮（模板）**

在 `<template #actions>` 内、「新建空白」`</button>`（~行7）之后加：
```html
    <button class="new-btn" @click="onAiGenerate">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 14 9l6 2-6 2-2 6-2-6-6-2 6-2z"/></svg>
      AI 生成技能
    </button>
```

- [ ] **Step 2: 加 onAiGenerate（script，producer）**

`<script setup>` 内、`onNewBlank` 附近加（`useRouter`/`router` 已在 L84/L91 就绪；`ElMessageBox`/`ElMessage` 页面已用）：
```typescript
async function onAiGenerate() {
  let intent = ''
  try {
    const { value } = await ElMessageBox.prompt(
      '一句话描述你想要的技能（可留空，进去再聊）',
      'AI 生成技能',
      { confirmButtonText: '开始', cancelButtonText: '取消', inputPlaceholder: '例如：把一段会议纪要整理成结构化待办' },
    )
    intent = (value || '').trim()
  } catch {
    return // 用户取消
  }
  const message = intent
    ? `我想要一个新技能（skill）：${intent}。请先想清楚它解决什么场景、什么时候触发，再按 skill 规范写出 SKILL.md（frontmatter name+description + 编号步骤正文）和必要的 helper 脚本，然后用 search_tools 激活 create_skill 存进我的技能库。技能名用英文 kebab-case。`
    : ''
  sessionStorage.setItem(
    'ai_builder_pending_skill_authoring',
    JSON.stringify({ message, intent, from: 'skill-library' }),
  )
  router.push({ path: '/ai-chat', query: { skill_authoring: '1' } })
}
```

- [ ] **Step 3: 编译验证**

Run: `cd frontend && npm run build:nocheck`
Expected: 成功。诚实说明：prompt → 跳转 → 消费端建会话需人工 preview 验。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/SkillLibraryPage.vue
git commit -m "feat(skill): 技能库 AI 生成技能 入口(dispatch 到 AIChatPage)"
```

---

## Task 6: 端到端验证 + 人工 eval

- [ ] **Step 1: 后端全量 skill 相关测试**

Run: `cd backend && .venv/bin/python -m pytest tests/test_skill_authoring.py tests/test_skill_files.py tests/test_skill_file_routes.py tests/test_skills_routes.py tests/test_skill_registry.py tests/test_use_skill.py tests/test_tool_registry.py tests/test_tool_contracts_schema.py -q`
Expected: 全 PASS。

- [ ] **Step 2: 前端整体编译**

Run: `cd frontend && npm run build:nocheck`
Expected: 成功。

- [ ] **Step 3: 人工 eval（桌面 preview，诚实记录）**

重启 sidecar（`run.py` reload=False），按 memory `desktop_nearfield_hardening_2026_06_17` 的桌面验证法起 source sidecar + chrome MCP，跑两条真实路径：
- 入口1：在一个有产出的会话点「存成技能」→ 看 agent 是否 search_tools 激活 create_skill、生成合理 name/description/instructions、技能落进技能库、能在技能库看到、对话里 @ 能引用。
- 入口2：技能库点「AI 生成技能」→ 输一句意图 → 跳 AIChatPage 建会话 → agent 追问/生成 → create_skill 落盘。
记录结果（成功/问题），不通过则回到对应 Task 修。客观判定锚点（逐条勾验，别"看着像就算过"）：
- 落盘：`SkillRegistry().get("<name>")` 非空且 `source=="user"`，`data_dir/skills/user/<name>/SKILL.md` 存在且 frontmatter 含 name+description。
- 可见：REST `GET /skills` / 技能库页能列出该技能；对话 `@` 引用能命中。
- **激活链路（显式 pass/fail）**：agent 是否真的 `search_tools` 激活了 `create_skill` 并调用成功？若多次不稳，按「备注」把 create_skill 提进 `_CORE_HOT_READS`。

- [ ] **Step 4: Commit（若 eval 中有修）**

```bash
git add <本轮真正改的文件>
git commit -m "fix(skill): AI 生成 skill 人工 eval 修正"
```

---

## 备注

- 不发版（用户另行决定）。本计划纯功能实现，发版走 `scripts/release-desktop.sh`（已修 source 兜底）。
- 删除技能不走 MCP（外部客户端删 skill 风险高），留 REST `DELETE /skills/{name}` + IDE。
- create_skill 走延迟工具，靠 search_tools 激活；若人工 eval 发现激活不稳，可把 `'create_skill'` 加进 `backend/app/ai_chat/tools.py` 的 `_CORE_HOT_READS`（~行1313）提到 core 集（另起小改动 + 注意它会进每轮 tools）。
- **前端入口云端可见性**：skill 是桌面特性（云端 `skills_root()` 为 None，后端返回 SKILLS_UNSUPPORTED 兜底）。技能库页/AIChatPage 若在云端 web 也可达，执行 Task 4/5 时给两个按钮加桌面探测（复用现有 `__DESKTOP__` / DESKTOP_MODE 前端开关）隐藏；若交付仅桌面包则此条不适用。执行者先确认页面是否云端可达再决定，别默默漏。
- **入口1 收尾引导降级**：spec 期望落盘后给「去技能库/IDE 打开」链接/toast；本计划用「工具卡展示 {ok,name,files,dir} + agent 文末提示可去技能库编辑」做 baseline，专门的 toast/跳转按钮留 v2。
- **author_user_skill 的 root 守卫**：纯函数不自检 `skills_root()` 为 None（云端会从 `create_user_skill` 抛 ValueError）；精确的 SKILLS_UNSUPPORTED 由 create_skill MCP 入口前置守。纯函数若被别处直接调用，错误码会归到 NAME_INVALID——调用方需自行 root 守卫。
