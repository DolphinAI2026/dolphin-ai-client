# 桌面端 Skill 上传 v1 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让桌面端能上传「能跑脚本的 skill 包」，对话里被引用后直接产出可下载的 .pptx/.docx。

**Architecture:** skill 以文件夹存桌面 `data_dir/skills/{platform,user}/`（路线1 文件系统库，不进 DB）。run_agent 把 skill 的 name+description 渐进披露注入 prompt；模型调 `use_skill` 展开完整 SKILL.md 并把文件拷进会话 workspace；按手册调 `run_python`（桌面修复后用 sidecar 冻结解释器跑，python-pptx/docx 已打包）产出文件；调 `save_binary_artifact` 登记为二进制产物，前端经下载端点取回。

**Tech Stack:** Python 3.13 / FastAPI / SQLAlchemy(async) / PyInstaller(桌面 sidecar) / Vue 3 + TS。测试 `pytest`（backend，`.venv` 在 `backend/.venv`）。

**关键约定（每个 backend 任务都遵守）：**
- 测试从 `backend/` 跑：`cd backend && .venv/bin/python -m pytest <path> -v`
- 不 commit 与本计划无关的并发改动（admin-spa/*、frontend 里 Codex 在动的文件）。提交只 `git add` 本任务明确列出的文件。
- 工具 handler 签名固定：`async def execute_x(args: dict, session: AIChatSession, db: AsyncSession) -> str`，注册进 `TOOL_HANDLERS`；schema 进 `TOOL_SCHEMAS`（自动入 `CORE_TOOL_NAMES`）。

---

## 文件结构（决策锁定）

**新增：**
- `backend/app/ai_chat/skills.py` — SkillRegistry（扫描/解析/读取）+ `build_skill_manifest`。单一职责：skill 文件系统层。
- `backend/app/routes/skills.py` — `/skills` CRUD（list/upload/delete）。
- `backend/desktop/preset-skills/` — v1 随包预置 skill（一个 PPT、一个 Word 试点）。
- `frontend/src/api/skills.ts` — 前端 skill API 封装。
- `frontend/src/views/SkillLibraryPage.vue`（或设置页内组件）— 技能库管理 UI。
- 各 `backend/tests/test_*.py`。

**修改：**
- `backend/app/ai_chat/tools.py` — 加 `use_skill` / `save_binary_artifact` schema+handler；`execute_run_python` 冻结分支（抽 `_build_python_argv`）。
- `backend/desktop_sidecar.py` — `--run-script` 子命令（抽 `run_script`）。
- `backend/app/ai_chat/agent.py` — 注入 skill 清单（镜像 deferred manifest 注入，~line 814-818 之后）。
- `backend/app/models/ai_chat.py` — `AIChatArtifact` 加 `storage`/`file_path`/`size_bytes`。
- `backend/app/database.py` — `init_db` 加 3 条幂等 `ALTER TABLE ai_chat_artifacts`（~line 153 之后）。
- `backend/app/routes/ai_chat.py` — `_artifact_to_dict` 透出 storage/size；新增 download 端点。
- `backend/app/main.py` — 挂载 `skills.router`。
- `frontend/src/components/common/UnifiedChatComposer.vue` — `@` skill 选单。
- `frontend/src/components/v2/AppAssistantPanel.vue` — 产物二进制下载。
- `scripts/build-desktop.sh` — 拷 `backend/desktop/preset-skills/` 进包。

---

## Task 1: SkillRegistry（文件系统 skill 层）

**Files:**
- Create: `backend/app/ai_chat/skills.py`
- Test: `backend/tests/test_skill_registry.py`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_skill_registry.py`：
```python
import os
import textwrap
from pathlib import Path

import pytest

from app.ai_chat import skills as skmod


def _write_skill(root: Path, source: str, name: str, frontmatter: str, body: str = "做事步骤", files: dict | None = None):
    d = root / source / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n{body}\n", encoding="utf-8")
    for fn, content in (files or {}).items():
        (d / fn).write_text(content, encoding="utf-8")
    return d


@pytest.fixture
def skills_dir(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    root.mkdir()
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(root))
    return root


def test_scan_returns_valid_skills(skills_dir):
    _write_skill(skills_dir, "platform", "pptx-brand", "name: pptx-brand\ndescription: 出品牌PPT", files={"helper.py": "print(1)"})
    found = skmod.SkillRegistry().scan()
    assert [s.name for s in found] == ["pptx-brand"]
    s = found[0]
    assert s.description == "出品牌PPT"
    assert s.source == "platform"
    assert "helper.py" in s.files


def test_scan_skips_bad_package_missing_frontmatter(skills_dir):
    _write_skill(skills_dir, "user", "good", "name: good\ndescription: ok")
    bad = skills_dir / "user" / "bad"
    bad.mkdir(parents=True)
    (bad / "SKILL.md").write_text("没有 frontmatter 的正文", encoding="utf-8")
    names = [s.name for s in skmod.SkillRegistry().scan()]
    assert names == ["good"]


def test_user_overrides_platform_same_name(skills_dir):
    _write_skill(skills_dir, "platform", "dup", "name: dup\ndescription: 平台版")
    _write_skill(skills_dir, "user", "dup", "name: dup\ndescription: 用户版")
    found = {s.name: s for s in skmod.SkillRegistry().scan()}
    assert found["dup"].source == "user"
    assert found["dup"].description == "用户版"


def test_missing_dir_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(tmp_path / "nope"))
    assert skmod.SkillRegistry().scan() == []


def test_get_and_read_skill_md(skills_dir):
    _write_skill(skills_dir, "user", "s1", "name: s1\ndescription: d", body="第一行\n第二行")
    reg = skmod.SkillRegistry()
    assert reg.get("s1").name == "s1"
    assert reg.get("nope") is None
    md = reg.read_skill_md("s1")
    assert "第一行" in md and "---" not in md  # frontmatter 已剥离


def test_manifest_lists_name_and_desc(skills_dir):
    _write_skill(skills_dir, "platform", "a", "name: a\ndescription: 甲")
    manifest = skmod.build_skill_manifest(skmod.SkillRegistry().scan())
    assert "use_skill" in manifest and "a: 甲" in manifest
    assert skmod.build_skill_manifest([]) == ""
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_skill_registry.py -v`
Expected: FAIL（`ModuleNotFoundError: app.ai_chat.skills`）

- [ ] **Step 3: 实现 skills.py**

`backend/app/ai_chat/skills.py`：
```python
"""桌面 Skill 包文件系统层 — 扫描/解析/读取，路线1，不进 DB。

skill = data_dir/skills/{platform,user}/<name>/SKILL.md(+helper/模板/资源)。
SKILL.md frontmatter 需含 name + description（与 Claude Code skill 一致）。
目录不存在 → 空集，云端/无 skill 时整链路 no-op。
"""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


def skills_root() -> Path | None:
    """解析 skill 根目录。优先级：显式 env > 桌面 data_dir > 无。"""
    env = os.environ.get("RUIJING_SKILLS_DIR")
    if env:
        return Path(env)
    # 桌面 sidecar：data_dir 由 desktop_sidecar.build_env 决定（默认 ~/.ruijing-builder）。
    # 这里复用同一约定：DESKTOP_MODE 时取 SIDECAR_DATA_DIR 或默认。
    if os.environ.get("DESKTOP_MODE") == "1" or getattr(sys, "frozen", False):
        data_dir = os.environ.get("SIDECAR_DATA_DIR") or str(Path.home() / ".ruijing-builder")
        return Path(data_dir) / "skills"
    return None


@dataclass
class Skill:
    name: str
    description: str
    dir: Path
    source: str  # "platform" | "user"
    files: list[str] = field(default_factory=list)


def _parse_frontmatter(md_text: str) -> tuple[dict, str]:
    """切出 YAML frontmatter（仅取 name/description 等简单 key: value）+ 正文。

    不引入 yaml 依赖：frontmatter 只用扁平 key: value，手解析足够且更稳。
    """
    if not md_text.startswith("---"):
        return {}, md_text
    lines = md_text.splitlines()
    # 找第二个 '---'
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, md_text
    meta: dict = {}
    for ln in lines[1:end]:
        if ":" in ln:
            k, v = ln.split(":", 1)
            meta[k.strip()] = v.strip()
    body = "\n".join(lines[end + 1:]).lstrip("\n")
    return meta, body


class SkillRegistry:
    def __init__(self, root: Path | None = None):
        self._root = root if root is not None else skills_root()

    def scan(self) -> list[Skill]:
        root = self._root
        if root is None or not root.exists():
            return []
        by_name: dict[str, Skill] = {}
        # platform 先扫，user 后扫覆盖同名（本地优先）。
        for source in ("platform", "user"):
            base = root / source
            if not base.is_dir():
                continue
            for d in sorted(base.iterdir()):
                if not d.is_dir():
                    continue
                md = d / "SKILL.md"
                if not md.is_file():
                    continue
                try:
                    meta, _ = _parse_frontmatter(md.read_text(encoding="utf-8"))
                except Exception as exc:
                    log.warning("skill 读取失败 %s: %r", d, exc)
                    continue
                name = (meta.get("name") or "").strip()
                desc = (meta.get("description") or "").strip()
                if not name or not desc:
                    log.warning("skill 缺 name/description, 跳过: %s", d)
                    continue
                files = [p.name for p in d.iterdir() if p.is_file() and p.name != "SKILL.md"]
                by_name[name] = Skill(name=name, description=desc, dir=d, source=source, files=files)
        return list(by_name.values())

    def get(self, name: str) -> Skill | None:
        for s in self.scan():
            if s.name == name:
                return s
        return None

    def read_skill_md(self, name: str) -> str:
        s = self.get(name)
        if s is None:
            return ""
        _, body = _parse_frontmatter((s.dir / "SKILL.md").read_text(encoding="utf-8"))
        return body


def build_skill_manifest(skills: list[Skill]) -> str:
    """渲染 skill 清单注入 system prompt（渐进披露）。空集返回空串。"""
    if not skills:
        return ""
    lines = [
        "\n\n## 可用技能(Skill)",
        "需要某个技能时, 先调 `use_skill(name)` 读它的完整说明再按其执行(脚本会在本机运行):",
    ]
    for s in skills:
        tag = "平台预置" if s.source == "platform" else "本地上传"
        lines.append(f"- {s.name}: {s.description}  [{tag}]")
    return "\n".join(lines)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_skill_registry.py -v`
Expected: PASS（6 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/ai_chat/skills.py backend/tests/test_skill_registry.py
git commit -m "feat(skill): SkillRegistry 文件系统 skill 层 + manifest"
```

---

## Task 2: run_python 桌面修复（sidecar 当解释器）

**Files:**
- Modify: `backend/desktop_sidecar.py`
- Modify: `backend/app/ai_chat/tools.py`（`execute_run_python` ~line 312-363）
- Test: `backend/tests/test_run_python_frozen.py`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_run_python_frozen.py`：
```python
import sys
from pathlib import Path

import pytest

from app.ai_chat import tools as t
import desktop_sidecar as ds


def test_build_argv_non_frozen_uses_dash_c(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    argv = t._build_python_argv("print(1)", "/tmp/x.py", exe="/usr/bin/python3")
    assert argv == ["/usr/bin/python3", "-c", "print(1)"]


def test_build_argv_frozen_uses_run_script(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    argv = t._build_python_argv("print(1)", "/tmp/x.py", exe="/opt/ruijing-sidecar")
    assert argv == ["/opt/ruijing-sidecar", "--run-script", "/tmp/x.py"]


def test_sidecar_run_script_executes_file(tmp_path):
    out = tmp_path / "out.txt"
    script = tmp_path / "s.py"
    script.write_text(f"open(r'{out}', 'w').write('hello-skill')\n", encoding="utf-8")
    rc = ds.run_script(str(script))
    assert rc == 0
    assert out.read_text() == "hello-skill"


def test_sidecar_run_script_nonzero_on_error(tmp_path):
    script = tmp_path / "bad.py"
    script.write_text("raise SystemExit(3)\n", encoding="utf-8")
    assert ds.run_script(str(script)) == 3
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_run_python_frozen.py -v`
Expected: FAIL（`_build_python_argv` / `run_script` 不存在）

- [ ] **Step 3a: 给 desktop_sidecar.py 加 `run_script`**

在 `backend/desktop_sidecar.py` 顶部 import 区加 `import runpy`、`import sys`、`import traceback`。新增函数（放在 `main()` 之前）：
```python
def run_script(path: str) -> int:
    """用本进程(冻结二进制即自带解释器+已打包依赖)执行一个 .py 文件。

    供 run_python 在桌面态调用: ruijing-sidecar --run-script <file>。
    不起 uvicorn、不建 DB。stdout/stderr 继承父进程(由调用方 subprocess 捕获)。
    """
    try:
        runpy.run_path(path, run_name="__main__")
        return 0
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else (0 if code is None else 1)
    except BaseException:
        traceback.print_exc()
        return 1
```
在 `main()` 里 argparse 加参数并**在 build_env/uvicorn 之前**短路：
```python
    parser.add_argument("--run-script", type=str, default="")
    args = parser.parse_args()

    if args.run_script:
        sys.exit(run_script(args.run_script))
```
（即把 `--run-script` 的判断放在现有 `args = parser.parse_args()` 之后、`data_dir = ...` 之前。）

- [ ] **Step 3b: 改 tools.py 的 run_python**

在 `backend/app/ai_chat/tools.py` 新增 helper（放 `execute_run_python` 上方）：
```python
def _build_python_argv(code: str, tmp_path: str, exe: str | None = None) -> list[str]:
    """桌面冻结态用 sidecar 二进制 --run-script <file>; 否则用解释器 -c code。"""
    exe = exe or sys.executable
    if getattr(sys, "frozen", False):
        return [exe, "--run-script", tmp_path]
    return [exe, "-c", code]
```
把 `execute_run_python`（line 312-363）中间的 subprocess 段改为：
```python
    workspace = session.workspace_dir
    Path(workspace).mkdir(parents=True, exist_ok=True)

    import uuid as _uuid
    tmp_path = ""
    if getattr(sys, "frozen", False):
        tmp_path = str(Path(workspace) / f".run_{_uuid.uuid4().hex}.py")
        Path(tmp_path).write_text(code, encoding="utf-8")
    argv = _build_python_argv(code, tmp_path)

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        # ... (其余 wait_for/超时/捕获/截断逻辑不变) ...
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
```
（保留原有 30s 超时、kill、stdout/stderr 拼装、8000 截断；只把 `proc = create_subprocess_exec(python_exe, "-c", code, ...)` 换成 `*argv`，并加 tmp 文件写/删。原 `python_exe = sys.executable` 行删除。）

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_run_python_frozen.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/desktop_sidecar.py backend/app/ai_chat/tools.py backend/tests/test_run_python_frozen.py
git commit -m "fix(desktop): run_python 用 sidecar --run-script 跑(冻结态), 解 -c 报错"
```

---

## Task 3: AIChatArtifact 二进制列 + 迁移

**Files:**
- Modify: `backend/app/models/ai_chat.py`（`AIChatArtifact` ~line 121-139）
- Modify: `backend/app/database.py`（`init_db` ALTER 列表 ~line 153 后）
- Test: `backend/tests/test_artifact_binary_columns.py`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_artifact_binary_columns.py`：
```python
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import AIChatArtifact


@pytest.mark.asyncio
async def test_artifact_has_binary_fields():
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as db:
        art = AIChatArtifact(session_id=1, filename="a.pptx", format="pptx",
                             storage="file", file_path="/ws/a.pptx", size_bytes=123)
        db.add(art)
        await db.commit()
        row = (await db.execute(select(AIChatArtifact).where(AIChatArtifact.filename == "a.pptx"))).scalar_one()
        assert row.storage == "file"
        assert row.file_path == "/ws/a.pptx"
        assert row.size_bytes == 123


@pytest.mark.asyncio
async def test_artifact_storage_defaults_text():
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as db:
        art = AIChatArtifact(session_id=1, filename="d.md", content="x")
        db.add(art)
        await db.commit()
        row = (await db.execute(select(AIChatArtifact).where(AIChatArtifact.filename == "d.md"))).scalar_one()
        assert row.storage == "text"
        assert row.file_path is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_artifact_binary_columns.py -v`
Expected: FAIL（`AIChatArtifact` 无 `storage` 属性）

- [ ] **Step 3a: 改 model**

`backend/app/models/ai_chat.py` 的 `AIChatArtifact`，在 `version` 列后加：
```python
    # 产物存储方式：text=用 content（默认，老产物不变）；file=二进制落盘
    storage: Mapped[str] = mapped_column(String(10), default="text", nullable=False)
    # storage=file 时指向 session.workspace_dir 下的文件
    file_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
```

- [ ] **Step 3b: 加幂等迁移**

`backend/app/database.py` 的 `init_db` ALTER 列表（line 153 的 `"CREATE INDEX ... ix_users_username ..."` 之后、`]:` 之前）加：
```python
            # 桌面 skill 二进制产物(2026-06-17): pptx/docx 落盘 + 可下载
            "ALTER TABLE ai_chat_artifacts ADD COLUMN storage VARCHAR(10) NOT NULL DEFAULT 'text'",
            "ALTER TABLE ai_chat_artifacts ADD COLUMN file_path VARCHAR(1000)",
            "ALTER TABLE ai_chat_artifacts ADD COLUMN size_bytes BIGINT NOT NULL DEFAULT 0",
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_artifact_binary_columns.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/ai_chat.py backend/app/database.py backend/tests/test_artifact_binary_columns.py
git commit -m "feat(artifact): AIChatArtifact 支持二进制产物(storage/file_path/size_bytes)"
```

---

## Task 4: save_binary_artifact 工具

**Files:**
- Modify: `backend/app/ai_chat/tools.py`（schema 加进 `TOOL_SCHEMAS`，handler 加进 `TOOL_HANDLERS`）
- Test: `backend/tests/test_save_binary_artifact.py`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_save_binary_artifact.py`：
```python
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import AIChatSession, AIChatArtifact
from app.ai_chat.tools import execute_tool


async def _mk(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    db = Session()
    ws = tmp_path / "ws"; ws.mkdir()
    s = AIChatSession(tenant_id=1, user_id=1, workspace_dir=str(ws))
    db.add(s); await db.commit(); await db.refresh(s)
    return db, s, ws


@pytest.mark.asyncio
async def test_register_file_artifact(tmp_path):
    db, s, ws = await _mk(tmp_path)
    (ws / "out.pptx").write_bytes(b"PK\x03\x04demo")
    res = await execute_tool("save_binary_artifact", {"source_path": "out.pptx"}, s, db)
    assert "out.pptx" in res
    row = (await db.execute(select(AIChatArtifact).where(AIChatArtifact.session_id == s.id))).scalar_one()
    assert row.storage == "file"
    assert row.format == "pptx"
    assert row.size_bytes == 8


@pytest.mark.asyncio
async def test_reject_outside_workspace(tmp_path):
    db, s, ws = await _mk(tmp_path)
    res = await execute_tool("save_binary_artifact", {"source_path": "../escape.pptx"}, s, db)
    assert "错误" in res


@pytest.mark.asyncio
async def test_reject_missing_file(tmp_path):
    db, s, ws = await _mk(tmp_path)
    res = await execute_tool("save_binary_artifact", {"source_path": "ghost.pptx"}, s, db)
    assert "错误" in res
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_save_binary_artifact.py -v`
Expected: FAIL（未知工具 `save_binary_artifact`）

- [ ] **Step 3a: 加 schema**

`backend/app/ai_chat/tools.py` 的 `TOOL_SCHEMAS` 列表里追加一项：
```python
    {
        "type": "function",
        "function": {
            "name": "save_binary_artifact",
            "description": (
                "把 skill 脚本(run_python)刚写进会话工作目录的二进制文件(如 .pptx/.docx/.xlsx)"
                "登记为可下载产物，用户能在右侧面板下载。source_path 必须是工作目录内的相对路径。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source_path": {"type": "string", "description": "工作目录内的相对路径，例如 'output.pptx'"},
                    "filename": {"type": "string", "description": "可选；产物展示名，默认用源文件名"},
                },
                "required": ["source_path"],
            },
        },
    },
```

- [ ] **Step 3b: 加 handler + 注册**

在实现区加：
```python
async def execute_save_binary_artifact(args: dict, session: AIChatSession, db: AsyncSession) -> str:
    source_path = (args.get("source_path") or "").strip()
    if not source_path:
        return "错误：缺少 source_path 参数"
    if not session.workspace_dir:
        return "错误：会话工作区未初始化"
    ws = Path(session.workspace_dir).resolve()
    target = (ws / source_path).resolve()
    # 防越界：必须落在 workspace 内
    if ws != target and ws not in target.parents:
        return f"错误：source_path 必须在工作目录内（{source_path} 越界）"
    if not target.is_file():
        return f"错误：文件不存在 '{source_path}'（先用 run_python 生成它）"

    art_name = (args.get("filename") or target.name).strip()
    fmt = target.suffix.lstrip(".").lower() or "bin"
    size = target.stat().st_size

    last = (await db.execute(
        select(AIChatArtifact)
        .where(AIChatArtifact.session_id == session.id, AIChatArtifact.filename == art_name)
        .order_by(desc(AIChatArtifact.version)).limit(1)
    )).scalar_one_or_none()
    new_version = (last.version + 1) if last else 1

    art = AIChatArtifact(
        session_id=session.id, filename=art_name, format=fmt,
        content="", storage="file", file_path=str(target), size_bytes=size,
        version=new_version,
    )
    db.add(art)
    await db.commit()
    await db.refresh(art)
    return f"已登记可下载产物 '{art_name}' (v{new_version}, {size} 字节)。用户已能在右侧面板下载。"


TOOL_HANDLERS["save_binary_artifact"] = execute_save_binary_artifact
```
（注意：`AIChatArtifact` 已在文件顶 import；`Path`/`select`/`desc` 也已 import。）

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_save_binary_artifact.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/ai_chat/tools.py backend/tests/test_save_binary_artifact.py
git commit -m "feat(artifact): save_binary_artifact 工具(登记 workspace 二进制为可下载产物)"
```

---

## Task 5: 产物下载端点 + 序列化透出 storage

**Files:**
- Modify: `backend/app/routes/ai_chat.py`（`_artifact_to_dict` ~line 381；新增 download 端点，挨着 line 791 `get_artifact`）
- Test: `backend/tests/test_artifact_download.py`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_artifact_download.py`（用 FastAPI 路由直测函数，避免起全栈）：
```python
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import AIChatSession, AIChatArtifact
from app.routes.ai_chat import _artifact_to_dict


def test_artifact_dict_exposes_storage():
    a = AIChatArtifact(session_id=1, filename="x.pptx", format="pptx",
                       storage="file", file_path="/ws/x.pptx", size_bytes=9, version=1)
    d = _artifact_to_dict(a)
    assert d["storage"] == "file"
    assert d["size_bytes"] == 9
    # 文本产物不回 file_path 真路径（避免泄漏），但要标 storage
    b = AIChatArtifact(session_id=1, filename="y.md", format="md", content="hi", version=1)
    assert _artifact_to_dict(b)["storage"] == "text"
```
（download 端点的真验证走 Task 13 端到端；此处先锁 `_artifact_to_dict` 契约。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_artifact_download.py -v`
Expected: FAIL（`_artifact_to_dict` 无 `storage` 键）

- [ ] **Step 3a: 改 `_artifact_to_dict`**

先 `Read backend/app/routes/ai_chat.py` 的 `_artifact_to_dict`（~line 381-395）确认现有返回键，再在返回 dict 里加：
```python
        "storage": getattr(a, "storage", "text") or "text",
        "size_bytes": getattr(a, "size_bytes", 0) or 0,
```
（不要回 `file_path` 真路径。）

- [ ] **Step 3b: 加 download 端点**

`Read` `get_artifact`（line 791-820）确认它怎么取 session/artifact 鉴权，照同样模式在其后加：
```python
from fastapi.responses import FileResponse, PlainTextResponse  # 顶部 import（若已存在则跳过）
import mimetypes
from pathlib import Path as _Path

@router.get("/sessions/{session_id}/artifacts/{filename}/download")
async def download_artifact(
    session_id: int,
    filename: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),  # 用与 get_artifact 相同的依赖/鉴权
):
    # 鉴权 + 取最新版本：复用 get_artifact 的查询方式（按 session 归属校验）
    sess = await db.get(AIChatSession, session_id)
    if not sess or sess.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    art = (await db.execute(
        select(AIChatArtifact)
        .where(AIChatArtifact.session_id == session_id, AIChatArtifact.filename == filename)
        .order_by(desc(AIChatArtifact.version)).limit(1)
    )).scalar_one_or_none()
    if not art:
        raise HTTPException(status_code=404, detail="产物不存在")
    if (getattr(art, "storage", "text") or "text") == "file" and art.file_path and _Path(art.file_path).is_file():
        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return FileResponse(art.file_path, media_type=mime, filename=filename)
    # 文本产物：直接回 content
    return PlainTextResponse(art.content or "", headers={"Content-Disposition": f'attachment; filename="{filename}"'})
```
（`get_current_user`/`get_db`/`HTTPException`/`Depends`/`select`/`desc`/`AIChatSession`/`AIChatArtifact` 按文件现有 import 对齐；以 `get_artifact` 的真实签名为准复制鉴权方式。）

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_artifact_download.py -v`
Expected: PASS（1 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/ai_chat.py backend/tests/test_artifact_download.py
git commit -m "feat(artifact): 二进制产物下载端点 + 序列化透出 storage/size"
```

---

## Task 6: use_skill 工具

**Files:**
- Modify: `backend/app/ai_chat/tools.py`
- Test: `backend/tests/test_use_skill.py`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_use_skill.py`：
```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import AIChatSession
from app.ai_chat.tools import execute_tool


async def _mk(tmp_path, monkeypatch):
    root = tmp_path / "skills" / "user" / "pptx-brand"
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text("---\nname: pptx-brand\ndescription: 出PPT\n---\n第一步: 跑 helper.py\n", encoding="utf-8")
    (root / "helper.py").write_text("print('gen')", encoding="utf-8")
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(tmp_path / "skills"))
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    db = Session()
    ws = tmp_path / "ws"; ws.mkdir()
    s = AIChatSession(tenant_id=1, user_id=1, workspace_dir=str(ws))
    db.add(s); await db.commit(); await db.refresh(s)
    return db, s, ws


@pytest.mark.asyncio
async def test_use_skill_expands_and_copies_files(tmp_path, monkeypatch):
    db, s, ws = await _mk(tmp_path, monkeypatch)
    res = await execute_tool("use_skill", {"name": "pptx-brand"}, s, db)
    assert "第一步" in res          # SKILL.md 正文返回
    assert "helper.py" in res       # 文件清单
    # 文件已拷进 workspace（隔离子目录）
    assert (ws / "skill_pptx-brand" / "helper.py").is_file()


@pytest.mark.asyncio
async def test_use_skill_unknown_name(tmp_path, monkeypatch):
    db, s, ws = await _mk(tmp_path, monkeypatch)
    res = await execute_tool("use_skill", {"name": "nope"}, s, db)
    assert "错误" in res and "pptx-brand" in res  # 列出可用 skill
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_use_skill.py -v`
Expected: FAIL（未知工具 `use_skill`）

- [ ] **Step 3a: 加 schema**（追加进 `TOOL_SCHEMAS`）
```python
    {
        "type": "function",
        "function": {
            "name": "use_skill",
            "description": (
                "读取某个技能(Skill)的完整说明并把它的脚本/模板准备到会话工作目录，"
                "之后按说明用 run_python 执行、用 save_binary_artifact 登记产出。"
                "技能清单见系统提示「可用技能」。"
            ),
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "技能名(与清单一致)"}},
                "required": ["name"],
            },
        },
    },
```

- [ ] **Step 3b: 加 handler + 注册**
```python
import shutil  # 顶部 import（若无）

async def execute_use_skill(args: dict, session: AIChatSession, db: AsyncSession) -> str:
    from app.ai_chat.skills import SkillRegistry
    name = (args.get("name") or "").strip()
    if not name:
        return "错误：缺少 name 参数"
    reg = SkillRegistry()
    skill = reg.get(name)
    if skill is None:
        avail = "、".join(s.name for s in reg.scan()) or "（暂无）"
        return f"错误：没有名为 '{name}' 的技能。可用技能：{avail}"
    if not session.workspace_dir:
        return "错误：会话工作区未初始化"
    dest = Path(session.workspace_dir) / f"skill_{name}"
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    for fn in skill.files:
        src = skill.dir / fn
        if src.is_file():
            shutil.copy2(src, dest / fn)
            copied.append(f"skill_{name}/{fn}")
    body = reg.read_skill_md(name)
    files_note = ("已就绪文件(在工作目录):\n" + "\n".join(f"- {p}" for p in copied)) if copied else "(无附带文件)"
    src_tag = "平台预置(已审)" if skill.source == "platform" else "本地上传"
    return (
        f"# 技能 {name}（来源：{src_tag}；脚本将由 run_python 在本机执行）\n\n"
        f"{body}\n\n---\n{files_note}\n\n"
        f"按上面说明执行：用 run_python 跑脚本(可直接打开这些文件)，产出文件后用 save_binary_artifact 登记。"
    )


TOOL_HANDLERS["use_skill"] = execute_use_skill
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_use_skill.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/ai_chat/tools.py backend/tests/test_use_skill.py
git commit -m "feat(skill): use_skill 工具(展开 SKILL.md + 拷文件进 workspace)"
```

---

## Task 7: skill 清单注入 run_agent

**Files:**
- Modify: `backend/app/ai_chat/agent.py`（~line 814-818 deferred manifest 注入之后）
- Test: `backend/tests/test_skill_manifest_injection.py`

- [ ] **Step 1: 写失败测试**（测纯函数 `build_skill_manifest` 已在 Task 1 覆盖；这里测注入 helper 不炸 + 空集 no-op）

`backend/tests/test_skill_manifest_injection.py`：
```python
from app.ai_chat.agent import _append_skill_manifest


def test_append_when_skills_present(monkeypatch):
    from app.ai_chat import skills as skmod
    monkeypatch.setattr(skmod.SkillRegistry, "scan", lambda self: [skmod.Skill("a", "甲", __import__("pathlib").Path("/x"), "user", [])])
    messages = [{"role": "system", "content": "BASE"}]
    _append_skill_manifest(messages)
    assert "可用技能" in messages[0]["content"]
    assert messages[0]["content"].startswith("BASE")


def test_noop_when_empty(monkeypatch):
    from app.ai_chat import skills as skmod
    monkeypatch.setattr(skmod.SkillRegistry, "scan", lambda self: [])
    messages = [{"role": "system", "content": "BASE"}]
    _append_skill_manifest(messages)
    assert messages[0]["content"] == "BASE"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_skill_manifest_injection.py -v`
Expected: FAIL（`_append_skill_manifest` 不存在）

- [ ] **Step 3: 实现注入 helper + 调用**

`backend/app/ai_chat/agent.py` 加 helper（模块级，靠近其他 helper）：
```python
def _append_skill_manifest(messages: list[dict]) -> None:
    """把可用 skill 清单追加到 system message（渐进披露）。空集 no-op、异常不致命。"""
    try:
        from app.ai_chat.skills import SkillRegistry, build_skill_manifest
        manifest = build_skill_manifest(SkillRegistry().scan())
    except Exception as exc:  # noqa: BLE001
        logger.warning("skill manifest 注入失败: %s", exc)
        return
    if manifest and messages and isinstance(messages[0], dict) and messages[0].get("role") == "system":
        messages[0]["content"] = (messages[0].get("content") or "") + manifest
```
在 deferred manifest 注入之后（line 818 之后、line 819 `active_tool_names = ...` 之前）调用：
```python
    _append_skill_manifest(messages)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_skill_manifest_injection.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/ai_chat/agent.py backend/tests/test_skill_manifest_injection.py
git commit -m "feat(skill): run_agent 注入可用 skill 清单(渐进披露)"
```

---

## Task 8: /skills CRUD 端点

**Files:**
- Create: `backend/app/routes/skills.py`
- Modify: `backend/app/main.py`（挂载，~line 156 `ai_chat.router` 旁）
- Test: `backend/tests/test_skills_routes.py`

- [ ] **Step 1: 写失败测试**（直测路由处理函数，避免起全栈；上传用内存 zip）

`backend/tests/test_skills_routes.py`：
```python
import io
import zipfile
import pytest

from app.routes import skills as sk


def _zip_bytes(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()


def test_validate_and_extract_good_zip(tmp_path, monkeypatch):
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(tmp_path / "skills"))
    data = _zip_bytes({"SKILL.md": "---\nname: s1\ndescription: d\n---\n步骤", "helper.py": "print(1)"})
    name = sk._extract_user_skill_zip(data)
    assert name == "s1"
    assert (tmp_path / "skills" / "user" / "s1" / "SKILL.md").is_file()


def test_reject_zip_without_skill_md(tmp_path, monkeypatch):
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(tmp_path / "skills"))
    with pytest.raises(ValueError):
        sk._extract_user_skill_zip(_zip_bytes({"readme.txt": "x"}))


def test_reject_zip_slip(tmp_path, monkeypatch):
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(tmp_path / "skills"))
    with pytest.raises(ValueError):
        sk._extract_user_skill_zip(_zip_bytes({"../evil.py": "x", "SKILL.md": "---\nname: e\ndescription: d\n---\n"}))


def test_delete_user_only(tmp_path, monkeypatch):
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(tmp_path / "skills"))
    (tmp_path / "skills" / "platform" / "p1").mkdir(parents=True)
    (tmp_path / "skills" / "platform" / "p1" / "SKILL.md").write_text("---\nname: p1\ndescription: d\n---\n", encoding="utf-8")
    with pytest.raises(ValueError):
        sk._delete_user_skill("p1")  # platform 只读
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_skills_routes.py -v`
Expected: FAIL（`app.routes.skills` 不存在）

- [ ] **Step 3a: 实现 routes/skills.py**

`backend/app/routes/skills.py`：
```python
"""桌面 Skill 库管理 — /skills list/upload/delete。文件系统层在 ai_chat.skills。"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from app.ai_chat.skills import SkillRegistry, skills_root, _parse_frontmatter
from app.deps import get_current_user  # 以本仓库实际鉴权依赖为准（见 ai_chat.py import）

router = APIRouter(prefix="/skills", tags=["skills"])


def _extract_user_skill_zip(data: bytes) -> str:
    """校验+解压用户 skill zip 到 user/<name>/，返回 skill name。非法抛 ValueError。"""
    root = skills_root()
    if root is None:
        raise ValueError("当前环境不支持 skill 上传（非桌面端）")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        # 找 SKILL.md（允许在顶层或单层目录内）
        skill_md = next((n for n in names if n.rstrip("/").endswith("SKILL.md")), None)
        if not skill_md:
            raise ValueError("zip 内未找到 SKILL.md")
        meta, _ = _parse_frontmatter(z.read(skill_md).decode("utf-8", errors="replace"))
        name = (meta.get("name") or "").strip()
        desc = (meta.get("description") or "").strip()
        if not name or not desc:
            raise ValueError("SKILL.md frontmatter 必须含 name 和 description")
        prefix = skill_md[: -len("SKILL.md")]  # zip 内 skill 根前缀
        dest = (root / "user" / name).resolve()
        dest.mkdir(parents=True, exist_ok=True)
        base = (root / "user").resolve()
        for n in names:
            if n.endswith("/"):
                continue
            if not n.startswith(prefix):
                continue
            rel = n[len(prefix):]
            if not rel:
                continue
            out = (dest / rel).resolve()
            if base not in out.parents and out != dest:  # zip slip 防护
                raise ValueError(f"非法路径: {n}")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(z.read(n))
    return name


def _delete_user_skill(name: str) -> None:
    import shutil
    reg = SkillRegistry()
    s = reg.get(name)
    if s is None:
        raise ValueError("技能不存在")
    if s.source != "user":
        raise ValueError("平台预置技能不可删除")
    shutil.rmtree(s.dir)


@router.get("")
async def list_skills(user=Depends(get_current_user)):
    return {"skills": [
        {"name": s.name, "description": s.description, "source": s.source, "files": s.files}
        for s in SkillRegistry().scan()
    ]}


@router.post("")
async def upload_skill(file: UploadFile = File(...), user=Depends(get_current_user)):
    data = await file.read()
    try:
        name = _extract_user_skill_zip(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "name": name}


@router.delete("/{name}")
async def delete_skill(name: str, user=Depends(get_current_user)):
    try:
        _delete_user_skill(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}
```
（⚠️ `get_current_user` 的真实 import 路径以 `backend/app/routes/ai_chat.py` 顶部为准——执行时先 `Read` ai_chat.py 确认依赖名/来源，照搬。）

- [ ] **Step 3b: 挂载**

`backend/app/main.py` line 156（`ai_chat.router` 之后）加：
```python
from app.routes import skills as skills_routes  # 顶部 import 区
app.include_router(skills_routes.router, prefix="/api")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_skills_routes.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/skills.py backend/app/main.py backend/tests/test_skills_routes.py
git commit -m "feat(skill): /skills list/upload/delete 端点(zip 校验+防 slip)"
```

---

## Task 9: 前端 — skills API + 技能库页

**Files:**
- Create: `frontend/src/api/skills.ts`
- Create: `frontend/src/views/SkillLibraryPage.vue`
- Modify: 路由/设置导航（先 `Read frontend/src/router/index.ts` 找现有 view 注册模式，照加一条 `/skills` 路由 + 设置入口）

- [ ] **Step 1: 写 API 封装**

`frontend/src/api/skills.ts`（对齐 `frontend/src/api/coding.ts` 的 http 客户端用法，先 Read 它确认 baseURL/封装）：
```typescript
import http from './http' // 以 coding.ts 实际用的客户端为准

export interface SkillItem { name: string; description: string; source: 'platform' | 'user'; files: string[] }

export async function listSkills(): Promise<SkillItem[]> {
  const { data } = await http.get('/skills')
  return data.skills || []
}
export async function uploadSkill(file: File): Promise<{ name: string }> {
  const fd = new FormData(); fd.append('file', file)
  const { data } = await http.post('/skills', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
  return data
}
export async function deleteSkill(name: string): Promise<void> {
  await http.delete(`/skills/${encodeURIComponent(name)}`)
}
```

- [ ] **Step 2: 写技能库页**

`frontend/src/views/SkillLibraryPage.vue`（用 Element Plus，对齐仓库现有 el-* 用法）：
```vue
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listSkills, uploadSkill, deleteSkill, type SkillItem } from '@/api/skills'

const skills = ref<SkillItem[]>([])
const loading = ref(false)

async function refresh() {
  loading.value = true
  try { skills.value = await listSkills() } finally { loading.value = false }
}
async function onUpload(file: File) {
  try { const r = await uploadSkill(file); ElMessage.success(`已上传技能 ${r.name}`); await refresh() }
  catch (e: any) { ElMessage.error(e?.response?.data?.detail || '上传失败') }
  return false // 阻止 el-upload 默认上传
}
async function onDelete(name: string) {
  await ElMessageBox.confirm(`删除技能「${name}」？`, '确认', { type: 'warning' })
  try { await deleteSkill(name); ElMessage.success('已删除'); await refresh() }
  catch (e: any) { ElMessage.error(e?.response?.data?.detail || '删除失败') }
}
onMounted(refresh)
</script>

<template>
  <div class="skill-library">
    <div class="header">
      <h2>技能库</h2>
      <el-upload :show-file-list="false" :before-upload="onUpload" accept=".zip">
        <el-button type="primary">上传技能 (zip)</el-button>
      </el-upload>
    </div>
    <el-table :data="skills" v-loading="loading">
      <el-table-column prop="name" label="技能" width="220" />
      <el-table-column prop="description" label="说明" />
      <el-table-column label="来源" width="120">
        <template #default="{ row }">
          <el-tag :type="row.source === 'platform' ? 'info' : 'success'">
            {{ row.source === 'platform' ? '平台预置' : '本地上传' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="脚本/文件" width="240">
        <template #default="{ row }">{{ (row.files || []).join(', ') || '—' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="100">
        <template #default="{ row }">
          <el-button v-if="row.source === 'user'" link type="danger" @click="onDelete(row.name)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<style scoped>
.skill-library { padding: 16px; }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
</style>
```

- [ ] **Step 3: 注册路由 + 入口**

`Read frontend/src/router/index.ts`，照现有 view 注册一条：
```typescript
{ path: '/skills', name: 'skills', component: () => import('@/views/SkillLibraryPage.vue') }
```
在设置/侧栏合适处加「技能库」入口链接到 `/skills`（按仓库导航组件实际结构，先 Read 确认落点）。

- [ ] **Step 4: 编译验证**

Run: `cd frontend && npm run build:nocheck`
Expected: 构建成功，无新报错（全量 `npm run build` 仓库预存坏，不用它判定）。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/skills.ts frontend/src/views/SkillLibraryPage.vue frontend/src/router/index.ts
git commit -m "feat(skill): 前端技能库页(列表/上传/删除)"
```

---

## Task 10: 前端 — 输入框 @ 引用 skill

**Files:**
- Modify: `frontend/src/components/common/UnifiedChatComposer.vue`
- Modify: 使用方（`frontend/src/components/v2/AppAssistantPanel.vue`）把选中 skill 名拼进发送文本

- [ ] **Step 1: composer 加 @ 选单**

`Read UnifiedChatComposer.vue` 确认 props/emit 结构。新增：
- prop `skills?: { name: string; description: string }[]`（默认 `[]`）。
- 监听 textarea 输入，当出现 `@` 触发一个轻量下拉（el-popover/原生列表）列 `skills`；选中后：① 把 `@<name>` 文本去掉/转成 chip；② `emit('skill-picked', name)`。
最小实现（不引第三方 mention 库，原生过滤）：在 script 加
```typescript
const showSkillMenu = ref(false)
const skillFilter = ref('')
function onInputForMention(v: string) {
  const m = v.match(/@([^\s@]*)$/)
  if (m) { showSkillMenu.value = true; skillFilter.value = m[1] }
  else showSkillMenu.value = false
}
function pickSkill(name: string) {
  // 去掉尾部 @filter，emit 选中
  const v = props.modelValue.replace(/@([^\s@]*)$/, '')
  emit('update:modelValue', v)
  showSkillMenu.value = false
  emit('skill-picked', name)
}
```
模板里在输入框上方条件渲染过滤后的 skill 列表（`skills.filter(s => s.name.includes(skillFilter))`），点项调 `pickSkill`。`emit` 定义补 `(e:'skill-picked', name:string)`。

- [ ] **Step 2: 使用方接线**

`Read AppAssistantPanel.vue` 找它给 composer 传 props / 处理发送的地方：传入 `:skills="availableSkills"`（从 `listSkills()` 拉，onMounted 加载），并处理 `@skill-picked="(n)=> pendingSkill = n"`；`doSend` 时若 `pendingSkill`，在发送文本前缀加 `「请使用技能 ${pendingSkill}」\n`，发送后清空。

- [ ] **Step 3: 编译验证**

Run: `cd frontend && npm run build:nocheck`
Expected: 成功。
诚实说明：@ 真机交互需人工在 preview 输 `@` 验证下拉；自动化只验编译+绑定。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/common/UnifiedChatComposer.vue frontend/src/components/v2/AppAssistantPanel.vue
git commit -m "feat(skill): 输入框 @ 引用 skill(强指)"
```

---

## Task 11: 前端 — 产物面板二进制下载

**Files:**
- Modify: `frontend/src/components/v2/AppAssistantPanel.vue`（下载逻辑 ~line 316 `downloadArtifact`）

- [ ] **Step 1: 改下载逻辑**

`Read AppAssistantPanel.vue` 的 `downloadArtifact`（现把 content 当 `text/markdown` blob）。改为：当 artifact `storage === 'file'`（列表项已含 storage，见 Task 5）走后端下载端点：
```typescript
function downloadArtifact() {
  const a = currentArtifactMeta.value // 含 storage / filename（按实际变量名对齐）
  if (a?.storage === 'file') {
    const url = `/api/ai-chat/sessions/${sessionId.value}/artifacts/${encodeURIComponent(a.filename)}/download`
    const link = document.createElement('a')
    link.href = url; link.download = a.filename; link.click()
    return
  }
  // 文本产物：维持现有 blob 下载
  const blob = new Blob([artifactContent.value], { type: 'text/markdown;charset=utf-8' })
  /* ...现有逻辑... */
}
```
（变量名 `sessionId`/`currentArtifactMeta`/`artifactContent` 以组件真实命名为准；下载 URL 若需带 token，按仓库现有「query token 下载」模式补 token 参数——先 Read 确认是否有鉴权 query 约定。）

- [ ] **Step 2: 编译验证**

Run: `cd frontend && npm run build:nocheck`
Expected: 成功。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/v2/AppAssistantPanel.vue
git commit -m "feat(artifact): 产物面板支持二进制(pptx/docx)下载"
```

---

## Task 12: 预置 skill + 构建拷贝

**Files:**
- Create: `backend/desktop/preset-skills/pptx-basic/SKILL.md` + `helper.py`
- Create: `backend/desktop/preset-skills/docx-basic/SKILL.md` + `helper.py`
- Modify: `scripts/build-desktop.sh`（打包时拷进 `skills/platform/`）

- [ ] **Step 1: 写预置 PPT skill**

`backend/desktop/preset-skills/pptx-basic/SKILL.md`：
```markdown
---
name: 基础PPT导出
description: 把要点/大纲生成一个简洁 .pptx；适合通用汇报/宣传
---
## 怎么做
1. 阅读用户给的内容，整理成「封面 + 若干内容页（标题+要点）」。
2. 编辑工作目录里的 `skill_基础PPT导出/helper.py`，把 `SLIDES` 改成实际内容（第一项为封面）。
3. 用 run_python 执行该 helper.py（它用 python-pptx 生成 `output.pptx` 到工作目录）。
4. 用 save_binary_artifact 登记 `output.pptx`（filename 用有意义的中文名，如 `XX汇报.pptx`）。
```
`backend/desktop/preset-skills/pptx-basic/helper.py`：
```python
from pptx import Presentation
from pptx.util import Pt

# [(标题, [要点...])]，第一项作封面（要点为空）
SLIDES = [
    ("示例标题", []),
    ("第一节", ["要点一", "要点二"]),
]

prs = Presentation()
for i, (title, bullets) in enumerate(SLIDES):
    layout = prs.slide_layouts[0 if i == 0 else 1]
    slide = prs.slides.add_slide(layout)
    slide.shapes.title.text = title
    if bullets and len(slide.placeholders) > 1:
        tf = slide.placeholders[1].text_frame
        tf.text = bullets[0]
        for b in bullets[1:]:
            p = tf.add_paragraph(); p.text = b; p.font.size = Pt(18)
prs.save("output.pptx")
print("saved output.pptx")
```

- [ ] **Step 2: 写预置 Word skill**

`backend/desktop/preset-skills/docx-basic/SKILL.md`：
```markdown
---
name: 基础Word导出
description: 把内容生成一个带标题/小节的 .docx 文档
---
## 怎么做
1. 把用户内容整理成「标题 + 若干小节（小标题 + 段落）」。
2. 编辑 `skill_基础Word导出/helper.py` 的 `TITLE` 和 `SECTIONS`。
3. run_python 执行 helper.py（python-docx 生成 `output.docx`）。
4. save_binary_artifact 登记 `output.docx`（中文名）。
```
`backend/desktop/preset-skills/docx-basic/helper.py`：
```python
from docx import Document

TITLE = "示例文档"
SECTIONS = [("第一节", "这里是正文段落。"), ("第二节", "更多内容。")]

doc = Document()
doc.add_heading(TITLE, level=0)
for h, body in SECTIONS:
    doc.add_heading(h, level=1)
    doc.add_paragraph(body)
doc.save("output.docx")
print("saved output.docx")
```

- [ ] **Step 3: 构建脚本拷贝**

`Read scripts/build-desktop.sh`，在打包后拷预置 skill 到运行时 data_dir 的来源位置。由于 v1 预置随包发：在 sidecar 首次启动 `build_env` 后由后端把 `desktop/preset-skills/*` 同步进 `data_dir/skills/platform/`（更稳，不依赖 PyInstaller datas 的运行期路径）。
实现：在 `desktop_sidecar.build_env` 末尾加一步 `_sync_preset_skills(data_dir)`：
```python
def _sync_preset_skills(data_dir: Path) -> None:
    """把随包的 preset-skills 同步进 data_dir/skills/platform/（覆盖式，平台只读）。"""
    import shutil
    # 冻结态资源在 sys._MEIPASS 下；dev 态在仓库 backend/desktop/preset-skills
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "desktop" / "preset-skills"
    if not base.is_dir():
        return
    dest = Path(data_dir) / "skills" / "platform"
    dest.mkdir(parents=True, exist_ok=True)
    for d in base.iterdir():
        if d.is_dir():
            shutil.copytree(d, dest / d.name, dirs_exist_ok=True)
```
并在 `ruijing-sidecar.spec` 的 `datas` 里加：把 `backend/desktop/preset-skills` 收进包（`datas += [(os.path.join(BACKEND, "desktop/preset-skills"), "desktop/preset-skills")]`，对齐该文件已有 `for src, dst in [("app/templates", ...)]` 的拷法）。`build_env` 调用 `_sync_preset_skills(data_dir)`（在返回前）。

- [ ] **Step 4: 验证（本环境可做的部分）**

Run: `cd backend && .venv/bin/python -c "from pptx import Presentation; from docx import Document; print('libs ok')"`
Expected: `libs ok`（确认两库在 dev venv 可用）。
诚实说明：随包同步真验证需 macOS 重打包桌面端测，本环境给不了。

- [ ] **Step 5: Commit**

```bash
git add backend/desktop/preset-skills backend/desktop_sidecar.py backend/ruijing-sidecar.spec scripts/build-desktop.sh
git commit -m "feat(skill): 预置基础 PPT/Word skill + 随包同步到 platform 库"
```

---

## Task 13: 端到端测试（最小真 PPT skill 全链路）

**Files:**
- Test: `backend/tests/test_skill_e2e_pptx.py`

- [ ] **Step 1: 写端到端测试**（dev 非冻结态，用真 python-pptx；走 use_skill→run_python→save_binary_artifact→读 artifact）

`backend/tests/test_skill_e2e_pptx.py`：
```python
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import AIChatSession, AIChatArtifact
from app.ai_chat.tools import execute_tool


@pytest.mark.asyncio
async def test_pptx_skill_end_to_end(tmp_path, monkeypatch):
    pytest.importorskip("pptx")
    # 准备一个真 skill
    sk = tmp_path / "skills" / "platform" / "e2e-ppt"
    sk.mkdir(parents=True)
    sk.joinpath("SKILL.md").write_text("---\nname: e2e-ppt\ndescription: 测试PPT\n---\n跑 gen.py\n", encoding="utf-8")
    sk.joinpath("gen.py").write_text(
        "from pptx import Presentation\n"
        "p=Presentation(); s=p.slides.add_slide(p.slide_layouts[0]); s.shapes.title.text='Hi'\n"
        "p.save('output.pptx'); print('ok')\n", encoding="utf-8")
    monkeypatch.setenv("RUIJING_SKILLS_DIR", str(tmp_path / "skills"))

    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    db = Session()
    ws = tmp_path / "ws"; ws.mkdir()
    s = AIChatSession(tenant_id=1, user_id=1, workspace_dir=str(ws))
    db.add(s); await db.commit(); await db.refresh(s)

    # 1) use_skill 展开 + 拷文件
    r1 = await execute_tool("use_skill", {"name": "e2e-ppt"}, s, db)
    assert "gen.py" in r1
    # 2) run_python 跑（dev 态用 venv python，python-pptx 可用）
    code = "import runpy; runpy.run_path('skill_e2e-ppt/gen.py', run_name='__main__')"
    r2 = await execute_tool("run_python", {"code": code}, s, db)
    assert "ok" in r2
    assert (ws / "output.pptx").is_file()
    # 3) 登记二进制产物
    r3 = await execute_tool("save_binary_artifact", {"source_path": "output.pptx", "filename": "测试.pptx"}, s, db)
    assert "测试.pptx" in r3
    art = (await db.execute(select(AIChatArtifact).where(AIChatArtifact.session_id == s.id))).scalar_one()
    assert art.storage == "file" and art.format == "pptx" and art.size_bytes > 0
```

- [ ] **Step 2: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_skill_e2e_pptx.py -v`
Expected: PASS（1 passed）

- [ ] **Step 3: 全量回归（确认没碰坏既有）**

Run: `cd backend && .venv/bin/python -m pytest tests/test_skill_registry.py tests/test_run_python_frozen.py tests/test_artifact_binary_columns.py tests/test_save_binary_artifact.py tests/test_artifact_download.py tests/test_use_skill.py tests/test_skill_manifest_injection.py tests/test_skills_routes.py tests/test_skill_e2e_pptx.py -v`
Expected: 全 PASS。

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_skill_e2e_pptx.py
git commit -m "test(skill): 端到端 use_skill→run_python→save_binary_artifact(真 pptx)"
```

---

## 验收（人工/CI，本环境给不了）

- macOS 跑 `scripts/build-desktop.sh` 重打包 sidecar；装桌面包后：
  1. 「技能库」上传一个带 helper 的 PPT skill zip → 列表出现。
  2. 对话「导成 XX PPT」→ 模型 use_skill → run_python（冻结态 `--run-script`，`import pptx` 不报缺库）→ 产出 .pptx。
  3. 右侧产物面板下载 .pptx，打开正常。
  4. docx 同验。
- 这一步是唯一能确认「冻结二进制里 python-pptx/docx 依赖收全 + `--run-script` 路径通」的方法。

## 非目标（不在本计划，见 spec §3）
云端 skill/沙箱/共享、MCP 接入、skill 版本管理/市场、allowed-tools 强制、AI 自动生成 skill。这些另开 spec。
```
