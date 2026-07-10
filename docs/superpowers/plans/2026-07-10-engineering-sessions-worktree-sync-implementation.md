# 工程会话与 Worktree 同步机制实施计划

> **执行方式：** 使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 按任务实施，并用复选框记录完成状态。

**目标：** 交付第一版可运行的工程会话基础能力：会话 registry、Git worktree 创建、同步状态、checkpoint、archive、reconcile 和本地 CLI。

**架构：** 新增 `backend/app/engineering_sessions/` 作为独立后端模块，不侵入现有 `ai_chat`、`code_runtime` 和 `coding` 路由。会话状态写入 Codex 全局目录 `~/.codex/.agentic-coding/workspaces/<repo-id>/sessions/`，真实冲突和分支状态只读取 Git，registry 不记录文件锁和路径锁。

**技术栈：** Python 3.11+、Pydantic v2、PyYAML、subprocess Git CLI、argparse、pytest。

---

## 范围

本计划实现设计文档中的 P1/P2 可用基础，并补齐 P0 文档入口：

- 会话类型、状态、registry YAML。
- `agentic_session.py create/resume/sync/list/archive/checkpoint/reconcile`。
- 创建 branch + worktree。
- 读取 clean/dirty/ahead/behind/merged/stale/missing/branch_mismatch。
- dirty worktree 的 checkpoint commit。
- registry 与真实 worktree 双向 reconcile。
- README 增加本地 CLI 使用方式。

本计划不包含产品 UI、部署队列和完整 `agentic-ai-user-engineering-manager` 技能接入，这三块依赖基础 CLI 稳定后单独实现。

## 文件结构

- Create `backend/app/engineering_sessions/__init__.py`: 模块导出。
- Create `backend/app/engineering_sessions/models.py`: 会话类型、状态、Pydantic 数据模型、branch slug 工具。
- Create `backend/app/engineering_sessions/paths.py`: repo id、registry root、默认 worktree parent。
- Create `backend/app/engineering_sessions/git_state.py`: Git CLI 封装、状态读取、worktree list 解析。
- Create `backend/app/engineering_sessions/registry.py`: YAML registry 读写、原子保存、ID 分配。
- Create `backend/app/engineering_sessions/service.py`: create/resume/sync/archive/checkpoint/reconcile orchestration。
- Create `backend/app/engineering_sessions/cli.py`: argparse CLI。
- Create `backend/scripts/agentic_session.py`: 从 `backend/scripts` 启动 CLI 的薄 wrapper。
- Modify `backend/requirements.txt`: 增加 `PyYAML>=6.0.2`。
- Modify `README.md`: 增加工程会话本地运行方式。
- Create `backend/tests/test_engineering_sessions_models.py`: 模型和 branch 命名测试。
- Create `backend/tests/test_engineering_sessions_registry.py`: registry YAML 读写测试。
- Create `backend/tests/test_engineering_sessions_git_state.py`: git 状态测试。
- Create `backend/tests/test_engineering_sessions_service.py`: worktree、checkpoint、archive、reconcile 测试。
- Create `backend/tests/test_engineering_sessions_cli.py`: CLI smoke 测试。

---

### Task 1：增加依赖和模块骨架

**文件：**
- 修改： `backend/requirements.txt`
- 新增： `backend/app/engineering_sessions/__init__.py`

- [x] **步骤 1：增加 PyYAML 依赖**

编辑 `backend/requirements.txt`，在 `pydantic-settings==2.6.0` 后插入：

```text
PyYAML>=6.0.2
```

- [x] **步骤 2：创建模块导出文件**

创建 `backend/app/engineering_sessions/__init__.py`：

```python
"""Engineering session registry and Git worktree orchestration."""

from app.engineering_sessions.models import (
    EngineeringSession,
    SessionStatus,
    SessionType,
)
from app.engineering_sessions.service import EngineeringSessionService

__all__ = [
    "EngineeringSession",
    "EngineeringSessionService",
    "SessionStatus",
    "SessionType",
]
```

- [x] **步骤 3：运行无依赖导入检查**

运行：

```bash
cd backend && python3 - <<'PY'
import app.engineering_sessions
print(app.engineering_sessions.__all__)
PY
```

后续任务实施前的预期：失败，并出现 `ModuleNotFoundError: No module named 'app.engineering_sessions.models'`。

- [x] **步骤 4：提交**

```bash
git add backend/requirements.txt backend/app/engineering_sessions/__init__.py
git commit -m "feat: add engineering sessions module shell"
```

---

### Task 2：定义会话模型

**文件：**
- 修改： `backend/app/engineering_sessions/__init__.py`
- 新增： `backend/app/engineering_sessions/models.py`
- 测试： `backend/tests/test_engineering_sessions_models.py`

- [x] **步骤 1：编写失败的模型测试**

创建 `backend/tests/test_engineering_sessions_models.py`：

```python
from datetime import timezone

from app.engineering_sessions.models import (
    EngineeringSession,
    SessionStatus,
    SessionType,
    build_session_branch,
    slugify_title,
)


def test_slugify_title_keeps_ascii_and_compacts_separators():
    assert slugify_title("Fix Code 空白页 / Internal Server Error!") == "fix-code-internal-server-error"


def test_build_session_branch_includes_session_type_and_short_title():
    assert (
        build_session_branch("S-002", SessionType.FEATURE, "aPaaS 账号绑定")
        == "session/S-002-feature-apaas"
    )


def test_engineering_session_defaults_are_serializable():
    session = EngineeringSession(
        id="S-001",
        type=SessionType.BUGFIX,
        title="Code blank page",
        repo="apaas-builder-ai",
        repo_path="/repo",
        base_branch="main",
        branch="session/S-001-bugfix-code-blank-page",
        worktree_path="/worktrees/S-001-bugfix-code-blank-page",
    )

    data = session.model_dump(mode="json")

    assert data["status"] == SessionStatus.RUNNING.value
    assert data["git_state"]["clean"] is True
    assert data["verification"]["last_status"] == "pending"
    assert data["cleanup"]["auto_delete"] is False
    assert session.created_at.tzinfo == timezone.utc


def test_engineering_session_enum_defaults_dump_as_plain_strings():
    session = EngineeringSession(
        id="S-003",
        type=SessionType.DOC_CHANGE,
        title="README runbook",
        repo="apaas-builder-ai",
        repo_path="/repo",
        branch="session/S-003-doc-change-readme-runbook",
    )

    data = session.model_dump(mode="python")

    assert session.type == "doc-change"
    assert session.status == "running"
    assert data["type"] == "doc-change"
    assert data["status"] == "running"

    session.status = SessionStatus.VERIFYING
    assigned = session.model_dump(mode="python")

    assert session.status == "verifying"
    assert assigned["status"] == "verifying"


def test_package_import_does_not_require_service_module_yet():
    import app.engineering_sessions as engineering_sessions

    assert "EngineeringSession" in engineering_sessions.__all__
    assert "EngineeringSessionService" not in engineering_sessions.__all__
    assert hasattr(engineering_sessions, "EngineeringSessionService") is False
```

- [x] **步骤 2：运行模型测试并确认失败**

运行：

```bash
cd backend && pytest tests/test_engineering_sessions_models.py -q
```

预期：FAIL because `app.engineering_sessions.models` does not exist.

- [x] **步骤 3：实现模型**

创建 `backend/app/engineering_sessions/models.py`：

```python
from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SessionType(str, Enum):
    NEW_APP = "new-app"
    FEATURE = "feature"
    BUGFIX = "bugfix"
    DEPLOY = "deploy"
    REVIEW = "review"
    DOC_CHANGE = "doc-change"
    SPEC_CHANGE = "spec-change"


class SessionStatus(str, Enum):
    RUNNING = "running"
    VERIFYING = "verifying"
    WAITING_MERGE = "waiting_merge"
    MERGED_RETAINED = "merged_retained"
    ARCHIVED_DIRTY = "archived_dirty"
    BLOCKED_RETAINED = "blocked_retained"
    ABANDONED_RETAINED = "abandoned_retained"
    MISSING_WORKTREE = "missing_worktree"
    ORPHAN_SESSION = "orphan_session"


class GitState(BaseModel):
    clean: bool = True
    ahead: int = 0
    behind: int = 0
    merged_to_base: bool = False
    dirty_uncheckpointed: bool = False
    stale: bool = False
    very_stale: bool = False
    missing_worktree: bool = False
    branch_mismatch: bool = False
    retained: bool = False
    current_branch: str | None = None
    head_commit: str | None = None


class RuntimeProfile(BaseModel):
    backend_port: int | None = None
    frontend_port: int | None = None
    db_profile: str | None = None
    env_file: str | None = None
    log_path: str | None = None
    started_from_worktree: str | None = None


class VerificationState(BaseModel):
    last_status: Literal["pending", "passed", "failed", "skipped"] = "pending"
    last_commands: list[str] = Field(default_factory=list)


class CleanupState(BaseModel):
    suggested: bool = False
    auto_delete: bool = False


class EngineeringSession(BaseModel):
    model_config = ConfigDict(
        use_enum_values=True,
        validate_default=True,
        validate_assignment=True,
    )

    id: str
    type: SessionType
    title: str
    status: SessionStatus = SessionStatus.RUNNING
    repo: str
    repo_path: str
    base_branch: str = "main"
    branch: str
    worktree_path: str | None = None
    base_commit: str | None = None
    head_commit: str | None = None
    merged_commit: str | None = None
    git_state: GitState = Field(default_factory=GitState)
    runtime_profile: RuntimeProfile = Field(default_factory=RuntimeProfile)
    roles: list[str] = Field(default_factory=lambda: ["engineering-manager"])
    verification: VerificationState = Field(default_factory=VerificationState)
    cleanup: CleanupState = Field(default_factory=CleanupState)
    depends_on: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    last_sync_at: datetime | None = None
    summary: str | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not re.fullmatch(r"S-\d{3,}", value):
            raise ValueError("session id must use S-001 format")
        return value


def slugify_title(title: str, *, max_length: int = 48) -> str:
    ascii_title = title.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        slug = "session"
    return slug[:max_length].rstrip("-")


def build_session_branch(session_id: str, session_type: SessionType | str, title: str) -> str:
    type_value = session_type.value if isinstance(session_type, SessionType) else str(session_type)
    return f"session/{session_id}-{type_value}-{slugify_title(title, max_length=40)}"
```

- [x] **步骤 4：让包导出兼容 Task 5 后续增加 service**

更新 `backend/app/engineering_sessions/__init__.py`：

```python
"""Engineering session registry and Git worktree orchestration."""

from app.engineering_sessions.models import (
    EngineeringSession,
    SessionStatus,
    SessionType,
)

__all__ = [
    "EngineeringSession",
    "SessionStatus",
    "SessionType",
]


def __getattr__(name: str) -> object:
    if name == "EngineeringSessionService":
        try:
            from app.engineering_sessions.service import EngineeringSessionService
        except ModuleNotFoundError as exc:
            if exc.name == "app.engineering_sessions.service":
                raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
            raise

        return EngineeringSessionService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

- [x] **步骤 5：运行模型测试并确认通过**

运行：

```bash
cd backend && pytest tests/test_engineering_sessions_models.py -q
```

预期：`5 passed`.

- [x] **步骤 6：提交**

```bash
git add backend/app/engineering_sessions/__init__.py backend/app/engineering_sessions/models.py backend/tests/test_engineering_sessions_models.py
git commit -m "feat: define engineering session models"
```

---

### Task 3：实现 registry 路径和 YAML 存储

**文件：**
- 新增： `backend/app/engineering_sessions/paths.py`
- 新增： `backend/app/engineering_sessions/registry.py`
- 测试： `backend/tests/test_engineering_sessions_registry.py`

- [x] **步骤 1：编写失败的 registry 测试**

创建 `backend/tests/test_engineering_sessions_registry.py`：

```python
from pathlib import Path

from app.engineering_sessions.models import SessionType
from app.engineering_sessions.paths import registry_root_for_repo, repo_id_for_path
from app.engineering_sessions.registry import SessionRegistry, SessionRegistryError


def test_repo_id_is_stable_and_path_safe(tmp_path: Path):
    repo = tmp_path / "apaas-builder-ai"
    repo.mkdir()

    repo_id = repo_id_for_path(repo)

    assert repo_id.startswith("apaas-builder-ai-")
    assert "/" not in repo_id


def test_registry_root_uses_override_home(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()

    root = registry_root_for_repo(repo, home=tmp_path / "agentic-home")

    assert root.parent.name == repo_id_for_path(repo)
    assert root.name == "sessions"


def test_registry_create_save_load_list(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    registry = SessionRegistry(repo, root=tmp_path / "sessions")

    session = registry.create(
        session_type=SessionType.DOC_CHANGE,
        title="README 本地运行方式",
        base_branch="main",
        worktree_path=str(tmp_path / "worktrees" / "S-001-doc"),
        base_commit="abc123",
    )
    registry.save(session)

    loaded = registry.load("S-001")
    sessions = registry.list()

    assert loaded.id == "S-001"
    assert loaded.type == SessionType.DOC_CHANGE.value
    assert loaded.branch == "session/S-001-doc-change-readme"
    assert loaded.base_commit == "abc123"
    assert [item.id for item in sessions] == ["S-001"]


def test_registry_rejects_invalid_session_id_paths(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    registry = SessionRegistry(repo, root=tmp_path / "sessions")

    try:
        registry.path_for("../S-001")
    except SessionRegistryError as exc:
        assert "invalid session id" in str(exc)
    else:
        raise AssertionError("expected invalid session id to be rejected")


def test_registry_reserves_ids_before_save_and_preserves_explicit_roles(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    registry = SessionRegistry(repo, root=tmp_path / "sessions")

    first = registry.create(
        session_type=SessionType.FEATURE,
        title="First",
        base_branch="main",
        worktree_path=None,
        roles=[],
    )
    second = registry.create(
        session_type=SessionType.BUGFIX,
        title="Second",
        base_branch="main",
        worktree_path=None,
    )

    assert first.id == "S-001"
    assert first.roles == []
    assert second.id == "S-002"
```

- [x] **步骤 2：运行 registry 测试并确认失败**

运行：

```bash
cd backend && pytest tests/test_engineering_sessions_registry.py -q
```

预期：FAIL because `paths.py` and `registry.py` do not exist.

- [x] **步骤 3：实现路径工具**

创建 `backend/app/engineering_sessions/paths.py`：

```python
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path


def _safe_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    return name or "repo"


def repo_id_for_path(repo_path: str | Path) -> str:
    resolved = Path(repo_path).resolve()
    digest = hashlib.sha1(str(resolved).encode("utf-8")).hexdigest()[:8]
    return f"{_safe_name(resolved.name)}-{digest}"


def registry_root_for_repo(repo_path: str | Path, *, home: str | Path | None = None) -> Path:
    override = os.environ.get("AGENTIC_SESSION_HOME")
    if home is not None:
        base = Path(home)
    elif override:
        base = Path(override)
    else:
        base = Path.home() / ".codex" / ".agentic-coding" / "workspaces"
    return base / repo_id_for_path(repo_path) / "sessions"


def default_worktree_parent(repo_path: str | Path) -> Path:
    return Path(repo_path).resolve().parent / "worktrees"
```

- [x] **步骤 4：实现 YAML registry**

创建 `backend/app/engineering_sessions/registry.py`：

```python
from __future__ import annotations

import re
from pathlib import Path

import yaml

from app.engineering_sessions.models import (
    EngineeringSession,
    SessionType,
    build_session_branch,
    utc_now,
)
from app.engineering_sessions.paths import registry_root_for_repo


class SessionRegistryError(RuntimeError):
    pass


class SessionRegistry:
    def __init__(self, repo_path: str | Path, *, root: str | Path | None = None) -> None:
        self.repo_path = Path(repo_path).resolve()
        self.root = Path(root).resolve() if root is not None else registry_root_for_repo(self.repo_path)
        self._reserved_ids: set[str] = set()

    def path_for(self, session_id: str) -> Path:
        if not re.fullmatch(r"S-\d{3,}", session_id):
            raise SessionRegistryError(f"invalid session id: {session_id}")
        return self.root / f"{session_id}.yaml"

    def next_id(self) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        highest = 0
        for path in self.root.glob("S-*.yaml"):
            match = re.fullmatch(r"S-(\d+)\.yaml", path.name)
            if match:
                highest = max(highest, int(match.group(1)))
        while True:
            candidate = f"S-{highest + 1:03d}"
            if candidate not in self._reserved_ids:
                self._reserved_ids.add(candidate)
                return candidate
            highest += 1

    def create(
        self,
        *,
        session_type: SessionType | str,
        title: str,
        base_branch: str,
        worktree_path: str | None,
        base_commit: str | None = None,
        roles: list[str] | None = None,
    ) -> EngineeringSession:
        session_id = self.next_id()
        normalized_type = SessionType(session_type)
        return EngineeringSession(
            id=session_id,
            type=normalized_type,
            title=title,
            repo=self.repo_path.name,
            repo_path=str(self.repo_path),
            base_branch=base_branch,
            branch=build_session_branch(session_id, normalized_type, title),
            worktree_path=worktree_path,
            base_commit=base_commit,
            roles=roles if roles is not None else ["engineering-manager"],
        )

    def save(self, session: EngineeringSession) -> EngineeringSession:
        self.root.mkdir(parents=True, exist_ok=True)
        session.updated_at = utc_now()
        data = session.model_dump(mode="json")
        target = self.path_for(session.id)
        tmp = target.with_suffix(".yaml.tmp")
        tmp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        tmp.replace(target)
        return session

    def load(self, session_id: str) -> EngineeringSession:
        path = self.path_for(session_id)
        if not path.exists():
            raise SessionRegistryError(f"session not found: {session_id}")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return EngineeringSession.model_validate(data)

    def list(self) -> list[EngineeringSession]:
        if not self.root.exists():
            return []
        sessions = []
        for path in sorted(self.root.glob("S-*.yaml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            sessions.append(EngineeringSession.model_validate(data))
        return sessions
```

- [x] **步骤 5：运行 registry 测试并确认通过**

运行：

```bash
cd backend && pytest tests/test_engineering_sessions_registry.py -q
```

预期：`5 passed`.

- [x] **步骤 6：提交**

```bash
git add backend/app/engineering_sessions/paths.py backend/app/engineering_sessions/registry.py backend/tests/test_engineering_sessions_registry.py
git commit -m "feat: add engineering session registry"
```

---

### Task 4：读取 Git 状态

**文件：**
- 新增： `backend/app/engineering_sessions/git_state.py`
- 测试： `backend/tests/test_engineering_sessions_git_state.py`

- [x] **步骤 1：编写失败的 Git 状态测试**

创建 `backend/tests/test_engineering_sessions_git_state.py`：

```python
import shutil
import subprocess
import shutil
from pathlib import Path

from app.engineering_sessions.git_state import (
    current_branch,
    inspect_git_state,
    list_git_worktrees,
    rev_parse_head,
)


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.email", "t@example.com")
    run_git(repo, "config", "user.name", "Tester")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "base")
    return repo


def test_current_branch_and_head(tmp_path: Path):
    repo = make_repo(tmp_path)

    assert current_branch(repo) == "main"
    assert len(rev_parse_head(repo)) >= 7


def test_current_branch_is_not_confused_by_same_name_tag(tmp_path: Path):
    repo = make_repo(tmp_path)
    run_git(repo, "tag", "main")

    assert current_branch(repo) == "main"


def test_inspect_git_state_reports_dirty_and_ahead(tmp_path: Path):
    repo = make_repo(tmp_path)
    run_git(repo, "checkout", "-b", "session/S-001-bugfix-test")
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    run_git(repo, "add", "feature.txt")
    run_git(repo, "commit", "-m", "feature")
    (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    state = inspect_git_state(repo, base_branch="main")

    assert state.clean is False
    assert state.ahead == 1
    assert state.behind == 0
    assert state.stale is False
    assert state.current_branch == "session/S-001-bugfix-test"


def test_inspect_missing_worktree(tmp_path: Path):
    state = inspect_git_state(tmp_path / "missing", base_branch="main")

    assert state.missing_worktree is True
    assert state.clean is False


def test_inspect_existing_non_git_directory_is_missing_worktree(tmp_path: Path):
    not_repo = tmp_path / "not-repo"
    not_repo.mkdir()

    state = inspect_git_state(not_repo, base_branch="main")

    assert state.missing_worktree is True
    assert state.clean is False


def test_inspect_nested_repo_directory_is_not_a_worktree_root(tmp_path: Path):
    repo = make_repo(tmp_path)
    nested = repo / "nested"
    nested.mkdir()

    state = inspect_git_state(nested, base_branch="main")

    assert state.missing_worktree is True
    assert state.clean is False


def test_inspect_git_state_reports_branch_mismatch_and_very_stale(tmp_path: Path):
    repo = make_repo(tmp_path)
    run_git(repo, "checkout", "-b", "session/S-003-feature-stale")
    run_git(repo, "checkout", "main")
    for idx in range(2):
        (repo / "README.md").write_text(f"base {idx}\n", encoding="utf-8")
        run_git(repo, "add", "README.md")
        run_git(repo, "commit", "-m", f"base {idx}")
    run_git(repo, "checkout", "session/S-003-feature-stale")

    state = inspect_git_state(
        repo,
        base_branch="main",
        expected_branch="session/S-999-wrong",
        very_stale_behind=2,
    )

    assert state.ahead == 0
    assert state.behind == 2
    assert state.stale is True
    assert state.very_stale is True
    assert state.branch_mismatch is True


def test_merged_to_base_turns_true_after_branch_commit_is_merged(tmp_path: Path):
    repo = make_repo(tmp_path)
    base_commit = rev_parse_head(repo)
    run_git(repo, "checkout", "-b", "session/S-004-feature-merged")
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    run_git(repo, "add", "feature.txt")
    run_git(repo, "commit", "-m", "feature")
    run_git(repo, "checkout", "main")
    run_git(repo, "merge", "--no-ff", "session/S-004-feature-merged", "-m", "merge feature")
    run_git(repo, "checkout", "session/S-004-feature-merged")

    state = inspect_git_state(repo, base_branch="main", session_base_commit=base_commit)

    assert state.merged_to_base is True
    assert state.retained is True


def test_unmodified_session_branch_is_not_marked_merged(tmp_path: Path):
    repo = make_repo(tmp_path)
    base_commit = rev_parse_head(repo)
    run_git(repo, "checkout", "-b", "session/S-007-feature-empty")

    state = inspect_git_state(repo, base_branch="main", session_base_commit=base_commit)

    assert state.merged_to_base is False
    assert state.retained is False


def test_state_calculation_ignores_tag_with_same_name_as_base_branch(tmp_path: Path):
    repo = make_repo(tmp_path)
    base_commit = rev_parse_head(repo)
    run_git(repo, "checkout", "-b", "session/S-008-feature-tag-conflict")
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    run_git(repo, "add", "feature.txt")
    run_git(repo, "commit", "-m", "feature")
    run_git(repo, "tag", "main")

    state = inspect_git_state(repo, base_branch="main", session_base_commit=base_commit)

    assert state.ahead == 1
    assert state.behind == 0
    assert state.merged_to_base is False
    assert state.retained is False


def test_list_git_worktrees_parses_porcelain(tmp_path: Path):
    repo = make_repo(tmp_path)
    linked = tmp_path / "linked"
    run_git(repo, "worktree", "add", "-b", "session/S-002-feature-x", str(linked), "main")

    worktrees = list_git_worktrees(repo)

    assert str(repo) in worktrees
    assert str(linked) in worktrees
    assert worktrees[str(linked)]["branch"] == "session/S-002-feature-x"
    assert worktrees[str(linked)]["prunable"] is False


def test_git_ignores_inherited_repository_selection_env(tmp_path: Path, monkeypatch):
    target_root = tmp_path / "target"
    target_root.mkdir()
    target = make_repo(target_root)
    decoy_root = tmp_path / "decoy"
    decoy_root.mkdir()
    decoy = make_repo(decoy_root)
    run_git(decoy, "checkout", "-b", "wrong-branch")
    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(decoy))
    monkeypatch.setenv("GIT_SHALLOW_FILE", str(tmp_path / "missing-shallow"))
    monkeypatch.setenv("GIT_CONFIG", str(tmp_path / "missing-config"))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.bare")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")

    assert current_branch(target) == "main"


def test_list_git_worktrees_marks_prunable_entries(tmp_path: Path):
    repo = make_repo(tmp_path)
    linked = tmp_path / "linked-prunable"
    run_git(repo, "worktree", "add", "-b", "session/S-005-feature-prunable", str(linked), "main")
    shutil.rmtree(linked)

    worktrees = list_git_worktrees(repo)

    assert worktrees[str(linked)]["prunable"] is True


def test_list_git_worktrees_preserves_newlines_in_paths(tmp_path: Path):
    repo = make_repo(tmp_path)
    linked = tmp_path / "linked\nnewline"
    run_git(repo, "worktree", "add", "-b", "session/S-006-feature-newline", str(linked), "main")

    worktrees = list_git_worktrees(repo)

    assert str(linked) in worktrees
    assert worktrees[str(linked)]["branch"] == "session/S-006-feature-newline"
```

- [x] **步骤 2：运行 Git 状态测试并确认失败**

运行：

```bash
cd backend && pytest tests/test_engineering_sessions_git_state.py -q
```

预期：FAIL because `git_state.py` does not exist.

- [x] **步骤 3：实现 Git 状态模块**

创建 `backend/app/engineering_sessions/git_state.py`：

```python
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import TypedDict

from app.engineering_sessions.models import GitState

_GIT_TIMEOUT = 90
_REPOSITORY_ENV_KEYS = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_DIR",
    "GIT_GRAFT_FILE",
    "GIT_IMPLICIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_NAMESPACE",
    "GIT_NO_REPLACE_OBJECTS",
    "GIT_OBJECT_DIRECTORY",
    "GIT_PREFIX",
    "GIT_REPLACE_REF_BASE",
    "GIT_SHALLOW_FILE",
    "GIT_WORK_TREE",
)
_CONFIG_ENV_KEYS = {
    "GIT_CONFIG",
    "GIT_CONFIG_COUNT",
    "GIT_CONFIG_PARAMETERS",
}


class GitCommandError(RuntimeError):
    pass


class GitWorktreeEntry(TypedDict):
    head: str | None
    branch: str | None
    prunable: bool


def git(repo_path: str | Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("HOME", str(Path.home()))
    for key in list(env):
        if (
            key in _REPOSITORY_ENV_KEYS
            or key in _CONFIG_ENV_KEYS
            or key.startswith("GIT_CONFIG_KEY_")
            or key.startswith("GIT_CONFIG_VALUE_")
        ):
            env.pop(key, None)
    result = subprocess.run(
        ["git", "-C", str(repo_path), *args],
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT,
        env=env,
    )
    if check and result.returncode != 0:
        message = (result.stderr or result.stdout).strip()[:500]
        raise GitCommandError(f"git {' '.join(args)} failed: {message}")
    return result


def rev_parse_head(repo_path: str | Path) -> str:
    return git(repo_path, "rev-parse", "HEAD").stdout.strip()


def current_branch(repo_path: str | Path) -> str:
    result = git(repo_path, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    return result.stdout.strip() if result.returncode == 0 else "HEAD"


def has_ref(repo_path: str | Path, ref: str) -> bool:
    return git(repo_path, "rev-parse", "--verify", "--quiet", ref, check=False).returncode == 0


def is_work_tree_root(repo_path: str | Path) -> bool:
    result = git(repo_path, "rev-parse", "--path-format=absolute", "--show-toplevel", check=False)
    if result.returncode != 0:
        return False
    top_level = Path(result.stdout.rstrip("\n")).resolve()
    return top_level == Path(repo_path).resolve()


def status_clean(repo_path: str | Path) -> bool:
    result = git(repo_path, "status", "--porcelain", "-uall")
    return not result.stdout.strip()


def ahead_behind(repo_path: str | Path, base_ref: str, head_ref: str = "HEAD") -> tuple[int, int]:
    if not has_ref(repo_path, base_ref) or not has_ref(repo_path, head_ref):
        return 0, 0
    result = git(repo_path, "rev-list", "--left-right", "--count", f"{base_ref}...{head_ref}")
    parts = result.stdout.split()
    if len(parts) != 2:
        return 0, 0
    behind, ahead = int(parts[0]), int(parts[1])
    return ahead, behind


def merged_to_base(repo_path: str | Path, base_ref: str, head_ref: str = "HEAD") -> bool:
    if not has_ref(repo_path, base_ref) or not has_ref(repo_path, head_ref):
        return False
    return git(repo_path, "merge-base", "--is-ancestor", head_ref, base_ref, check=False).returncode == 0


def inspect_git_state(
    worktree_path: str | Path | None,
    *,
    base_branch: str,
    expected_branch: str | None = None,
    session_base_commit: str | None = None,
    very_stale_behind: int = 20,
) -> GitState:
    if worktree_path is None or not Path(worktree_path).exists():
        return GitState(clean=False, missing_worktree=True, stale=True)
    if not is_work_tree_root(worktree_path):
        return GitState(clean=False, missing_worktree=True, stale=True)

    branch = current_branch(worktree_path)
    head = rev_parse_head(worktree_path)
    clean = status_clean(worktree_path)
    remote_ref = f"refs/remotes/origin/{base_branch}"
    local_ref = f"refs/heads/{base_branch}"
    base_ref = remote_ref if has_ref(worktree_path, remote_ref) else local_ref
    ahead, behind = ahead_behind(worktree_path, base_ref)
    merged = merged_to_base(worktree_path, base_ref)
    if session_base_commit is not None and head == session_base_commit:
        merged = False
    branch_mismatch = expected_branch is not None and branch != expected_branch
    return GitState(
        clean=clean,
        ahead=ahead,
        behind=behind,
        merged_to_base=merged,
        stale=behind > 0,
        very_stale=behind >= very_stale_behind,
        missing_worktree=False,
        branch_mismatch=branch_mismatch,
        current_branch=branch,
        head_commit=head,
        retained=merged,
    )


def fetch_origin(repo_path: str | Path) -> bool:
    if not has_ref(repo_path, "refs/remotes/origin/HEAD"):
        remotes = git(repo_path, "remote", check=False)
        if "origin" not in remotes.stdout.split():
            return False
    return git(repo_path, "fetch", "origin", check=False).returncode == 0


def list_git_worktrees(repo_path: str | Path) -> dict[str, GitWorktreeEntry]:
    result = git(repo_path, "worktree", "list", "--porcelain", "-z")
    items: dict[str, GitWorktreeEntry] = {}
    for block in result.stdout.split("\0\0"):
        fields = [field for field in block.split("\0") if field]
        if not fields or not fields[0].startswith("worktree "):
            continue
        path = fields[0].removeprefix("worktree ")
        entry: GitWorktreeEntry = {"head": None, "branch": None, "prunable": False}
        for field in fields[1:]:
            if field.startswith("HEAD "):
                entry["head"] = field.removeprefix("HEAD ")
            elif field.startswith("branch "):
                entry["branch"] = field.removeprefix("branch refs/heads/")
            elif field.startswith("prunable"):
                entry["prunable"] = True
        items[path] = entry
    return items
```

- [x] **步骤 4：运行 Git 状态测试并确认通过**

运行：

```bash
cd backend && pytest tests/test_engineering_sessions_git_state.py -q
```

预期：`14 passed`.

- [x] **步骤 5：提交**

```bash
git add backend/app/engineering_sessions/git_state.py backend/tests/test_engineering_sessions_git_state.py
git commit -m "feat: inspect engineering session git state"
```

---

### Task 5：实现会话服务、worktree、checkpoint 和归档

**文件：**
- 修改： `backend/app/engineering_sessions/__init__.py`
- 新增： `backend/app/engineering_sessions/service.py`
- 修改： `backend/tests/test_engineering_sessions_models.py`
- 测试： `backend/tests/test_engineering_sessions_service.py`

- [x] **步骤 1：编写失败的 service 测试**

创建 `backend/tests/test_engineering_sessions_service.py`：

```python
import shutil
import subprocess
from pathlib import Path

import app.engineering_sessions as engineering_sessions
from app.engineering_sessions.models import SessionStatus, SessionType
from app.engineering_sessions.service import EngineeringSessionService


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.email", "t@example.com")
    run_git(repo, "config", "user.name", "Tester")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "base")
    return repo


def test_create_builds_registry_and_worktree(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = EngineeringSessionService(
        repo,
        registry_root=tmp_path / "sessions",
        worktree_parent=tmp_path / "worktrees",
    )

    session = service.create(SessionType.FEATURE, "Add fast conversation creation")

    assert session.id == "S-001"
    assert session.worktree_path is not None
    assert Path(session.worktree_path).exists()
    assert run_git(Path(session.worktree_path), "branch", "--show-current") == session.branch
    assert service.registry.load("S-001").branch == session.branch
    assert session.status == SessionStatus.RUNNING.value
    assert session.git_state.merged_to_base is False


def test_create_without_worktree_remains_running(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = EngineeringSessionService(repo, registry_root=tmp_path / "sessions", worktree_parent=tmp_path / "worktrees")

    session = service.create(SessionType.REVIEW, "Read-only review", create_worktree=False)

    assert session.worktree_path is None
    assert session.status == SessionStatus.RUNNING.value
    assert session.git_state.missing_worktree is False


def test_sync_updates_dirty_state(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = EngineeringSessionService(repo, registry_root=tmp_path / "sessions", worktree_parent=tmp_path / "worktrees")
    session = service.create(SessionType.BUGFIX, "Code blank page")
    worktree = Path(session.worktree_path or "")
    (worktree / "bug.txt").write_text("dirty\n", encoding="utf-8")

    synced = service.sync(session.id)

    assert synced.git_state.clean is False
    assert synced.git_state.current_branch == session.branch


def test_checkpoint_commits_dirty_changes(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = EngineeringSessionService(repo, registry_root=tmp_path / "sessions", worktree_parent=tmp_path / "worktrees")
    session = service.create(SessionType.DOC_CHANGE, "README runbook")
    worktree = Path(session.worktree_path or "")
    (worktree / "runbook.md").write_text("run\n", encoding="utf-8")

    created = service.checkpoint(session.id, message="checkpoint: S-001 README runbook")
    synced = service.sync(session.id)

    assert created is True
    assert synced.git_state.clean is True
    assert synced.git_state.ahead == 1


def test_archive_dirty_without_checkpoint_marks_archived_dirty(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = EngineeringSessionService(repo, registry_root=tmp_path / "sessions", worktree_parent=tmp_path / "worktrees")
    session = service.create(SessionType.BUGFIX, "Dirty archive")
    Path(session.worktree_path or "", "dirty.txt").write_text("dirty\n", encoding="utf-8")

    archived = service.archive(session.id, checkpoint=False)
    resumed = service.sync(session.id)

    assert archived.status == SessionStatus.ARCHIVED_DIRTY.value
    assert archived.git_state.dirty_uncheckpointed is True
    assert resumed.git_state.dirty_uncheckpointed is True


def test_checkpoint_rejects_branch_mismatch(tmp_path: Path):
    repo = make_repo(tmp_path)
    service = EngineeringSessionService(repo, registry_root=tmp_path / "sessions", worktree_parent=tmp_path / "worktrees")
    session = service.create(SessionType.BUGFIX, "Wrong branch")
    worktree = Path(session.worktree_path or "")
    run_git(worktree, "checkout", "-b", "wrong-branch")
    (worktree / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    created = service.checkpoint(session.id)

    assert created is False
    assert run_git(worktree, "status", "--porcelain")


def test_reconcile_creates_orphan_session_for_unregistered_worktree(tmp_path: Path):
    repo = make_repo(tmp_path)
    worktree_parent = tmp_path / "worktrees"
    worktree_parent.mkdir()
    orphan_path = worktree_parent / "orphan"
    run_git(repo, "worktree", "add", "-b", "session/S-099-feature-orphan", str(orphan_path), "main")
    service = EngineeringSessionService(
        repo,
        registry_root=tmp_path / "sessions",
        worktree_parent=worktree_parent,
    )

    changed = service.reconcile()

    orphan = next(item for item in changed if item.status == SessionStatus.ORPHAN_SESSION.value)
    assert orphan.branch == "session/S-099-feature-orphan"
    assert orphan.worktree_path == str(orphan_path)


def test_reconcile_skips_prunable_worktree_entries(tmp_path: Path):
    repo = make_repo(tmp_path)
    worktree_parent = tmp_path / "worktrees"
    worktree_parent.mkdir()
    prunable_path = worktree_parent / "prunable"
    run_git(repo, "worktree", "add", "-b", "session/S-100-feature-prunable", str(prunable_path), "main")
    shutil.rmtree(prunable_path)
    service = EngineeringSessionService(
        repo,
        registry_root=tmp_path / "sessions",
        worktree_parent=worktree_parent,
    )

    changed = service.reconcile()

    assert all(item.branch != "session/S-100-feature-prunable" for item in changed)


def test_package_exports_service_after_service_module_exists():
    assert "EngineeringSessionService" in engineering_sessions.__all__
    assert engineering_sessions.EngineeringSessionService is EngineeringSessionService
```

- [x] **步骤 2：运行 service 测试并确认失败**

运行：

```bash
cd backend && pytest tests/test_engineering_sessions_service.py -q
```

预期：FAIL because `service.py` does not exist.

- [x] **步骤 3：实现 service**

创建 `backend/app/engineering_sessions/service.py`：

```python
from __future__ import annotations

from pathlib import Path

from app.engineering_sessions.git_state import (
    current_branch,
    fetch_origin,
    git,
    has_ref,
    inspect_git_state,
    list_git_worktrees,
    rev_parse_head,
)
from app.engineering_sessions.models import EngineeringSession, SessionStatus, SessionType, utc_now
from app.engineering_sessions.paths import default_worktree_parent
from app.engineering_sessions.registry import SessionRegistry

_COMMIT_IDENTITY = [
    "-c",
    "user.name=ai-builder",
    "-c",
    "user.email=ai-builder@local",
]


class EngineeringSessionService:
    def __init__(
        self,
        repo_path: str | Path,
        *,
        registry_root: str | Path | None = None,
        worktree_parent: str | Path | None = None,
    ) -> None:
        self.repo_path = Path(repo_path).resolve()
        self.registry = SessionRegistry(self.repo_path, root=registry_root)
        self.worktree_parent = Path(worktree_parent).resolve() if worktree_parent else default_worktree_parent(self.repo_path)

    def create(
        self,
        session_type: SessionType | str,
        title: str,
        *,
        base_branch: str | None = None,
        create_worktree: bool = True,
        roles: list[str] | None = None,
    ) -> EngineeringSession:
        fetch_origin(self.repo_path)
        base = base_branch or current_branch(self.repo_path)
        base_commit = rev_parse_head(self.repo_path)
        preview = self.registry.create(
            session_type=session_type,
            title=title,
            base_branch=base,
            worktree_path=None,
            base_commit=base_commit,
            roles=roles,
        )
        if create_worktree:
            preview.worktree_path = str(self.worktree_parent / preview.branch.replace("/", "-"))
            self._ensure_worktree(preview)
        session = self.sync_model(preview)
        self.registry.save(session)
        return session

    def resume(self, session_id: str) -> EngineeringSession:
        return self.sync(session_id)

    def sync(self, session_id: str) -> EngineeringSession:
        session = self.registry.load(session_id)
        session = self.sync_model(session)
        self.registry.save(session)
        return session

    def sync_model(self, session: EngineeringSession) -> EngineeringSession:
        if session.worktree_path is None:
            session.head_commit = session.base_commit
            session.last_sync_at = utc_now()
            return session
        fetch_origin(session.worktree_path or self.repo_path)
        dirty_uncheckpointed = session.git_state.dirty_uncheckpointed
        state = inspect_git_state(
            session.worktree_path,
            base_branch=session.base_branch,
            expected_branch=session.branch,
            session_base_commit=session.base_commit,
        )
        state.dirty_uncheckpointed = dirty_uncheckpointed and not state.clean
        session.git_state = state
        session.head_commit = state.head_commit
        session.last_sync_at = utc_now()
        if state.missing_worktree:
            session.status = SessionStatus.MISSING_WORKTREE
        elif state.merged_to_base and state.clean:
            session.status = SessionStatus.MERGED_RETAINED
            session.cleanup.suggested = True
        return session

    def checkpoint(self, session_id: str, *, message: str | None = None) -> bool:
        session = self.registry.load(session_id)
        if not session.worktree_path:
            return False
        worktree = Path(session.worktree_path)
        state = inspect_git_state(
            worktree,
            base_branch=session.base_branch,
            expected_branch=session.branch,
            session_base_commit=session.base_commit,
        )
        state.dirty_uncheckpointed = session.git_state.dirty_uncheckpointed and not state.clean
        if state.missing_worktree or state.branch_mismatch:
            session.git_state = state
            self.registry.save(session)
            return False
        if state.clean:
            session.git_state = state
            self.registry.save(session)
            return False
        git(worktree, "add", "-A")
        commit_message = message or f"checkpoint: {session.id} {session.title}"
        result = git(worktree, *_COMMIT_IDENTITY, "commit", "--no-verify", "-m", commit_message, check=False)
        if result.returncode != 0:
            return False
        self.sync(session.id)
        return True

    def archive(self, session_id: str, *, checkpoint: bool = True) -> EngineeringSession:
        session = self.sync(session_id)
        if checkpoint and not session.git_state.clean:
            self.checkpoint(session.id)
            session = self.sync(session.id)
        if session.git_state.clean and session.git_state.merged_to_base:
            session.status = SessionStatus.MERGED_RETAINED
            session.cleanup.suggested = True
        elif session.git_state.clean:
            session.status = SessionStatus.ABANDONED_RETAINED
        else:
            session.status = SessionStatus.ARCHIVED_DIRTY
            session.git_state.dirty_uncheckpointed = True
        self.registry.save(session)
        return session

    def list(self, *, sync: bool = False) -> list[EngineeringSession]:
        sessions = self.registry.list()
        if not sync:
            return sessions
        return [self.sync(item.id) for item in sessions]

    def reconcile(self) -> list[EngineeringSession]:
        sessions = {item.branch: item for item in self.registry.list()}
        changed: list[EngineeringSession] = []
        for session in list(sessions.values()):
            changed.append(self.sync(session.id))

        known_branches = set(sessions)
        for path, item in list_git_worktrees(self.repo_path).items():
            if item["prunable"]:
                continue
            branch = item["branch"]
            if not branch or not branch.startswith("session/") or branch in known_branches:
                continue
            orphan = self.registry.create(
                session_type=SessionType.FEATURE,
                title=branch.removeprefix("session/"),
                base_branch=current_branch(self.repo_path),
                worktree_path=path,
                base_commit=item["head"],
                roles=["engineering-manager"],
            )
            orphan.branch = branch
            orphan.status = SessionStatus.ORPHAN_SESSION
            orphan.git_state = inspect_git_state(path, base_branch=orphan.base_branch, expected_branch=branch)
            orphan.head_commit = orphan.git_state.head_commit
            orphan.last_sync_at = utc_now()
            self.registry.save(orphan)
            changed.append(orphan)
        return changed

    def _ensure_worktree(self, session: EngineeringSession) -> None:
        if not session.worktree_path:
            raise ValueError("worktree_path is required")
        worktree = Path(session.worktree_path)
        worktree.parent.mkdir(parents=True, exist_ok=True)
        if worktree.exists():
            state = inspect_git_state(
                worktree,
                base_branch=session.base_branch,
                expected_branch=session.branch,
                session_base_commit=session.base_commit,
            )
            if state.missing_worktree or state.branch_mismatch:
                raise ValueError(f"worktree path is not usable: {worktree}")
            return
        if has_ref(self.repo_path, f"refs/heads/{session.branch}"):
            git(self.repo_path, "worktree", "add", str(worktree), session.branch)
        else:
            base_ref = f"refs/heads/{session.base_branch}"
            if not has_ref(self.repo_path, base_ref):
                raise ValueError(f"base branch not found: {session.base_branch}")
            git(self.repo_path, "worktree", "add", "-b", session.branch, str(worktree), base_ref)
```

- [x] **步骤 4：恢复包级 service 导出**

更新 `backend/app/engineering_sessions/__init__.py`：

```python
"""Engineering session registry and Git worktree orchestration."""

from app.engineering_sessions.models import (
    EngineeringSession,
    SessionStatus,
    SessionType,
)
from app.engineering_sessions.service import EngineeringSessionService

__all__ = [
    "EngineeringSession",
    "EngineeringSessionService",
    "SessionStatus",
    "SessionType",
]
```

- [x] **步骤 5：删除 Task 2 的过渡包测试**

从 `backend/tests/test_engineering_sessions_models.py` 删除 `test_package_import_does_not_require_service_module_yet`。Task 5 已提供 `service.py`，并在 `test_package_exports_service_after_service_module_exists` 中验证最终包导出。

- [x] **步骤 6：运行 service 测试并确认通过**

运行：

```bash
cd backend && pytest tests/test_engineering_sessions_service.py -q
```

预期：`9 passed`.

- [x] **步骤 7：提交**

```bash
git add backend/app/engineering_sessions/__init__.py backend/app/engineering_sessions/service.py backend/tests/test_engineering_sessions_models.py backend/tests/test_engineering_sessions_service.py
git commit -m "feat: manage engineering session worktrees"
```

---

### Task 6：增加 CLI 和脚本入口

**文件：**
- 新增： `backend/app/engineering_sessions/cli.py`
- 新增： `backend/scripts/agentic_session.py`
- 测试： `backend/tests/test_engineering_sessions_cli.py`

- [x] **步骤 1：编写失败的 CLI 测试**

创建 `backend/tests/test_engineering_sessions_cli.py`：

```python
import json
import subprocess
import sys
from pathlib import Path


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.email", "t@example.com")
    run_git(repo, "config", "user.name", "Tester")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "base")
    return repo


def test_cli_create_list_resume(tmp_path: Path):
    repo = make_repo(tmp_path)
    registry = tmp_path / "sessions"
    worktrees = tmp_path / "worktrees"

    create = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.engineering_sessions.cli",
            "--repo",
            str(repo),
            "--registry-root",
            str(registry),
            "--worktree-parent",
            str(worktrees),
            "create",
            "--type",
            "feature",
            "--title",
            "Fast new conversation",
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    )
    created = json.loads(create.stdout)

    assert created["id"] == "S-001"
    assert Path(created["worktree_path"]).exists()

    listed = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.engineering_sessions.cli",
            "--repo",
            str(repo),
            "--registry-root",
            str(registry),
            "--worktree-parent",
            str(worktrees),
            "list",
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(listed.stdout)

    assert data[0]["id"] == "S-001"
```

- [x] **步骤 2：运行 CLI 测试并确认失败**

运行：

```bash
cd backend && pytest tests/test_engineering_sessions_cli.py -q
```

预期：FAIL because `cli.py` does not exist.

- [x] **步骤 3：实现 CLI**

创建 `backend/app/engineering_sessions/cli.py`：

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.engineering_sessions.models import SessionType
from app.engineering_sessions.service import EngineeringSessionService


def _json(data: Any) -> None:
    if hasattr(data, "model_dump"):
        data = data.model_dump(mode="json")
    elif isinstance(data, list):
        data = [item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in data]
    print(json.dumps(data, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentic session")
    parser.add_argument("--repo", default=".", help="Git repo path")
    parser.add_argument("--registry-root", default=None, help="Override session registry root")
    parser.add_argument("--worktree-parent", default=None, help="Override worktree parent directory")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create")
    create.add_argument("--type", required=True, choices=[item.value for item in SessionType])
    create.add_argument("--title", required=True)
    create.add_argument("--base-branch", default=None)
    create.add_argument("--no-worktree", action="store_true")

    for name in ("resume", "sync", "archive", "checkpoint"):
        item = sub.add_parser(name)
        item.add_argument("session_id")
    sub.add_parser("list").add_argument("--sync", action="store_true")
    sub.add_parser("reconcile")

    checkpoint = sub.choices["checkpoint"]
    checkpoint.add_argument("--message", default=None)
    archive = sub.choices["archive"]
    archive.add_argument("--no-checkpoint", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    service = EngineeringSessionService(
        Path(args.repo),
        registry_root=args.registry_root,
        worktree_parent=args.worktree_parent,
    )

    if args.command == "create":
        session = service.create(
            args.type,
            args.title,
            base_branch=args.base_branch,
            create_worktree=not args.no_worktree,
        )
        _json(session)
        return 0
    if args.command == "resume":
        _json(service.resume(args.session_id))
        return 0
    if args.command == "sync":
        _json(service.sync(args.session_id))
        return 0
    if args.command == "list":
        _json(service.list(sync=args.sync))
        return 0
    if args.command == "archive":
        _json(service.archive(args.session_id, checkpoint=not args.no_checkpoint))
        return 0
    if args.command == "checkpoint":
        _json({"created": service.checkpoint(args.session_id, message=args.message)})
        return 0
    if args.command == "reconcile":
        _json(service.reconcile())
        return 0
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **步骤 4：实现脚本包装器**

创建 `backend/scripts/agentic_session.py`：

```python
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.engineering_sessions.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **步骤 5：运行 CLI 测试并确认通过**

运行：

```bash
cd backend && pytest tests/test_engineering_sessions_cli.py -q
```

预期：`1 passed`.

- [x] **步骤 6：提交**

```bash
git add backend/app/engineering_sessions/cli.py backend/scripts/agentic_session.py backend/tests/test_engineering_sessions_cli.py
git commit -m "feat: add engineering session cli"
```

---

### Task 7：记录本地使用方式

**文件：**
- 修改： `README.md`

- [x] **步骤 1：增加 README 章节**

Append this section near the local development or backend tooling section in `README.md`:

````markdown
## 工程会话与 Worktree

本地可用 `backend/scripts/agentic_session.py` 管理工程会话。工程会话会把可写任务放到独立 Git branch + worktree 中，registry 写入 `~/.codex/.agentic-coding/workspaces/<repo-id>/sessions/`，不会写进业务仓库。

创建功能会话：

```bash
cd backend
python3 scripts/agentic_session.py --repo .. create --type feature --title "新增会话先返回再异步加载"
```

查看会话：

```bash
cd backend
python3 scripts/agentic_session.py --repo .. list --sync
```

恢复并同步会话：

```bash
cd backend
python3 scripts/agentic_session.py --repo .. resume S-001
```

离开或归档前创建 checkpoint：

```bash
cd backend
python3 scripts/agentic_session.py --repo .. checkpoint S-001 --message "checkpoint: S-001 async conversation create"
```

归档会话但保留 worktree：

```bash
cd backend
python3 scripts/agentic_session.py --repo .. archive S-001
```

扫描 registry 和真实 worktree 的差异：

```bash
cd backend
python3 scripts/agentic_session.py --repo .. reconcile
```

约束：

- 可写任务默认使用独立 worktree。
- 不记录文件锁、路径锁和模块锁，冲突由 Git merge/rebase 暴露。
- dirty worktree 归档前会 checkpoint；显式 `--no-checkpoint` 会标记 `dirty_uncheckpointed`。
- 已合并且 clean 的 worktree 只提示清理，不自动删除。
- 部署必须来自 default/release/merged commit，不能从 dirty worktree 部署。
````

- [x] **步骤 2：验证 README 命令可解析**

运行：

```bash
cd backend && python3 scripts/agentic_session.py --help
```

预期：output contains `create`, `resume`, `sync`, `archive`, `checkpoint`, `reconcile`.

- [x] **步骤 3：提交**

```bash
git add README.md
git commit -m "docs: document engineering session worktree cli"
```

---

### Task 8：最终验证

**文件：**
- 无新增文件。

- [x] **步骤 1：运行聚焦测试**

运行：

```bash
cd backend && pytest \
  tests/test_engineering_sessions_models.py \
  tests/test_engineering_sessions_registry.py \
  tests/test_engineering_sessions_git_state.py \
  tests/test_engineering_sessions_service.py \
  tests/test_engineering_sessions_cli.py \
  -q
```

预期：全部工程会话测试通过。

- [x] **步骤 2：运行相邻 Git 测试**

运行：

```bash
cd backend && pytest tests/test_workspace_git_p1.py tests/test_workspace_git_changes.py -q
```

预期：现有工作区 Git 测试通过。

- [x] **步骤 3：在当前 worktree 运行 CLI smoke**

运行：

```bash
cd backend
tmp_root="$(mktemp -d)"
python3 scripts/agentic_session.py \
  --repo .. \
  --registry-root "$tmp_root/sessions" \
  --worktree-parent "$tmp_root/worktrees" \
  create --type doc-change --title "README smoke"
python3 scripts/agentic_session.py \
  --repo .. \
  --registry-root "$tmp_root/sessions" \
  --worktree-parent "$tmp_root/worktrees" \
  list --sync
```

预期：第一个命令输出会话 `S-001`；第二个命令输出包含 `S-001` 的列表，`type` 为 `doc-change`，且 `git_state.current_branch` 以 `session/S-001-doc-change-` 开头。

- [x] **步骤 4：检查 worktree 差异**

运行：

```bash
git status --short
git diff --stat
```

预期：只有本计划列出的文件发生修改或新增。

- [x] **步骤 5：如果 smoke 后 README 变化则提交最终说明**

如果验证期间 README 有变化，运行：

```bash
git add README.md
git commit -m "docs: refine engineering session usage"
```

预期：smoke 验证未修改 README 时不需要额外提交。

实际验证结果：

- 工程会话聚焦测试：`56 passed`。
- 相邻 workspace Git 测试：`17 passed`。
- CLI smoke：创建 `S-001`，类型为 `doc-change`，分支为 `session/S-001-doc-change-readme-smoke`，`list --sync` 返回 1 条 clean 会话。
- README 未被 smoke 修改，无需额外 README 提交。

---

## 自检

规格覆盖：

- 会话类型与状态：Task 2。
- YAML registry：Task 3。
- 独立 branch + worktree：Task 5。
- clean/dirty/ahead/behind/merged/stale/missing/branch_mismatch：Task 4 和 Task 5。
- checkpoint：Task 5。
- 归档时保留 worktree：Task 5。
- reconcile orphan/missing/drift：Task 5。
- doc-change/spec-change 作为一等会话类型：Task 2 和 Task 6 的 CLI choices。
- README 本地运行方式：Task 7。

类型一致性：

- `SessionType` 取值与设计文档一致。
- `SessionStatus.ORPHAN_SESSION` 使用 `orphan_session`。
- `EngineeringSessionService` 在 Task 5 完成后由包入口直接导出。
- CLI 命令调用 `EngineeringSessionService` 已定义的方法。
- YAML registry 使用 `EngineeringSession.model_dump(mode="json")` 和 `EngineeringSession.model_validate`。

实施加固：

- registry 的 read-modify-save 使用线程锁与 `flock` 事务锁，避免多会话并发创建、归档和 reconcile 相互覆盖。
- registry 原子保存使用唯一同目录临时文件，避免并发写共享 `.tmp` 文件。
- 显式 `base_branch` 使用捕获的 commit 哈希创建 worktree，避免分支引用推进造成基线漂移。
- 配置了 `origin` 时，fetch 失败会阻止同步状态和 `last_sync_at` 落盘。
- `new-app` 和 `spec-change` 在 service 与 CLI 两层强制使用 worktree。
- checkpoint 提交后只做本地状态刷新，避免提交已成功但第二次 fetch 失败造成结果歧义。
