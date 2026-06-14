"""录制 VibeCodingAgent 当前行为作为迁移前基线（offline 模式）。

不启动 HTTP backend，直接 import 并调用 `run_coding_pipeline`，
用 .env 里的 LLM 配置真实跑一次 agent，录制事件流 + workspace 产物。

用法：
  python scripts/record_agent_baseline.py case_a_rating_star \\
      --message "做一个星级评分组件，支持半星和自定义颜色" \\
      --output tests/fixtures/baselines/case_a_rating_star_run1

环境变量（都从 backend/.env 自动加载）：
  LLM_API_KEY / LLM_API_BASE / LLM_MODEL （或 ANTHROPIC_*）
  JWT_SECRET_KEY （任意非空字符串即可，录制不用 auth）

脚本会：
  - 用独立的临时 SQLite（不污染真实 DB）
  - 用独立的 workspace 目录（默认 ./_record_workspaces/，避免污染主 workspaces/）
  - 真实调用 LLM API（扣费产生）

产出目录结构：
  {output}/
    ├── events.jsonl
    ├── metadata.json
    ├── workspace_tree.txt
    ├── workspace/                 # 关键配置文件拷贝
    └── recorded_at.txt
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path


# ══════════════════════════════════════════════════════════════
# 环境初始化 — 必须在 import backend 代码之前完成
# ══════════════════════════════════════════════════════════════

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BACKEND_DIR = _REPO_ROOT / "backend"
_BASELINES_DIR = _REPO_ROOT / "tests" / "fixtures" / "baselines"


def _bootstrap_env(workspace_root: Path, sqlite_db: Path) -> None:
    """加载 .env，然后覆盖几个关键项为脚本专属值。"""
    from dotenv import load_dotenv
    env_file = _BACKEND_DIR / ".env"
    if not env_file.exists():
        print(f"❌ 未找到 {env_file}", file=sys.stderr)
        sys.exit(2)
    load_dotenv(env_file)

    # 覆盖：独立 DB（SQLite 避免污染真实数据库）
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{sqlite_db.resolve()}"
    # 覆盖：独立 workspace root（避免污染真实 workspaces/）
    os.environ["APAAS_WORKSPACE_ROOT"] = str(workspace_root.resolve())

    workspace_root.mkdir(parents=True, exist_ok=True)
    sqlite_db.parent.mkdir(parents=True, exist_ok=True)


def _setup_sys_path():
    sys.path.insert(0, str(_BACKEND_DIR))


# ══════════════════════════════════════════════════════════════
# 录制核心
# ══════════════════════════════════════════════════════════════

KEY_FILE_PATTERNS = (
    "shared/widget.config.json",
    "web/src/apaas.json",
    "mobile/src/apaas.json",
    "src/apaas.json",
    "**/*.widget.config.json",
    "**/*.editor.config.json",
    "pom.xml",
)

IGNORE_DIRS = {
    "node_modules", ".git", "dist", "__pycache__", ".pytest_cache",
    ".idea", ".vscode", "https", "target",
}


async def _ensure_fixtures(db) -> tuple[int, int]:
    """插入最小 fixture：tenant + user。返回 (user_id, tenant_id)。"""
    from sqlalchemy import select
    from app.models import User
    from app.models.tenant import Tenant

    # Tenant
    result = await db.execute(select(Tenant).where(Tenant.id == 1))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        tenant = Tenant(
            id=1,
            tenant_name="baseline-tenant",
            tenant_code="baseline",
        )
        db.add(tenant)
        await db.commit()

    # User
    result = await db.execute(select(User).where(User.id == 1))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            id=1,
            username="baseline_recorder",
            hashed_password="-",  # 不用于登录
        )
        db.add(user)
        await db.commit()

    return 1, 1


async def _run_one_turn(
    db,
    *,
    case_name: str,
    message: str,
    user_id: int,
    tenant_id: int,
    conversation_id: int | None,
    workspace_id: str | None,
    label: str,
) -> tuple[list[dict], dict, str | None, int | None, str | None]:
    """跑一次 pipeline，收集事件。返回 (events, final_data, error, conv_id, ws_id)"""
    from app.coding.pipeline import PipelineParams, run_coding_pipeline

    params = PipelineParams(
        message=message,
        user_id=user_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        conversation_id=conversation_id,
        selected_model=None,
        project_id=None,
    )

    events: list[dict] = []
    final_data: dict = {}
    error_message: str | None = None
    ws_id_local: str | None = workspace_id
    conv_id_local: int | None = conversation_id

    print(f"\n→ [{label}] run_coding_pipeline")
    print(f"  message: {message[:80]}...")

    try:
        async for event in run_coding_pipeline(params, db):
            events.append(event)
            t = event.get("type")
            if t == "done":
                final_data = event
                ws_id_local = event.get("ws_id") or event.get("workspace_id") or ws_id_local
                # done 事件里 conversation_id 才是已创建的（scene_detected 那时还是 None）
                if event.get("conversation_id") is not None:
                    conv_id_local = event.get("conversation_id")
            elif t == "scene_detected":
                # scene_detected 的 conversation_id 可能是 None，要忽略
                if event.get("conversation_id") is not None:
                    conv_id_local = event.get("conversation_id")
            elif t == "agent_error":
                error_message = event.get("message") or "agent error"

            if t == "step":
                print(f"  step: {event.get('step')} [{event.get('status')}]")
            elif t == "agent_tool":
                print(f"  → tool: {event.get('name')}")
            elif t == "agent_thinking":
                pass
            elif t == "done":
                waiting = event.get("waiting_confirmation")
                tag = "waiting_confirmation" if waiting else f"ws_id={ws_id_local}"
                print(f"  done: {tag}")
    except Exception as exc:
        import traceback
        error_message = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
        print(f"❌ {label} 中断：{error_message}", file=sys.stderr)

    return events, final_data, error_message, conv_id_local, ws_id_local


async def record_case(
    case_name: str,
    message: str,
    output_dir: Path,
    *,
    workspace_root: Path,
    sqlite_db: Path,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)

    from app.database import AsyncSessionLocal, init_db
    await init_db()

    all_events: list[dict] = []
    final_data: dict = {}
    error_message: str | None = None
    ws_id: str | None = None
    start_ts = time.time()

    async with AsyncSessionLocal() as db:
        user_id, tenant_id = await _ensure_fixtures(db)

        # ── 第一轮：发需求，brainstorm 或直接生成 ── #
        events1, final1, err1, conv_id, ws_id = await _run_one_turn(
            db, case_name=case_name, message=message,
            user_id=user_id, tenant_id=tenant_id,
            conversation_id=None, workspace_id=None,
            label="Turn 1 (initial)",
        )
        all_events.extend(events1)
        if err1:
            error_message = err1

        waiting_confirm = (final1 or {}).get("waiting_confirmation")

        # ── 第二轮：如果第一轮触发 brainstorm 等确认，发"确认"消息 ── #
        if waiting_confirm and not ws_id and not error_message:
            confirm_msg = "确认"  # 中文触发 classify_brainstorm_response=confirm
            events2, final2, err2, conv_id, ws_id = await _run_one_turn(
                db, case_name=case_name, message=confirm_msg,
                user_id=user_id, tenant_id=tenant_id,
                conversation_id=conv_id, workspace_id=None,
                label="Turn 2 (confirm brainstorm)",
            )
            all_events.extend(events2)
            if err2:
                error_message = err2
            final_data = final2 or final1
        else:
            final_data = final1

    duration = round(time.time() - start_ts, 1)
    events = all_events

    duration = round(time.time() - start_ts, 1)
    if not ws_id and final_data:
        ws_id = final_data.get("ws_id") or final_data.get("workspace_id")

    # —— 写 events.jsonl —— #
    with (output_dir / "events.jsonl").open("w", encoding="utf-8") as f:
        for evt in events:
            f.write(json.dumps(evt, ensure_ascii=False, default=str) + "\n")

    # —— 统计 metadata —— #
    tool_calls = [e for e in events if e.get("type") == "agent_tool"]
    # VibeCodingAgent 用 "tool" 字段；兼容也看 "name"（个别旧数据）
    metadata = {
        "case_name": case_name,
        "message": message,
        "duration_seconds": duration,
        "total_events": len(events),
        "events_by_type": dict(Counter(e.get("type") for e in events)),
        "event_type_sequence": [e.get("type") for e in events],
        "tool_call_count": len(tool_calls),
        "tool_names_called": [e.get("tool") or e.get("name") for e in tool_calls],
        "workspace_id": ws_id,
        "final_status": "success" if (ws_id and not error_message) else "failed",
        "error_message": error_message,
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2)
    )

    # —— workspace tree + 关键文件 —— #
    if ws_id:
        try:
            _record_workspace_artifacts(ws_id, output_dir, workspace_root)
            print(f"  workspace tree recorded: {ws_id}")
        except Exception as exc:
            print(f"⚠️ workspace 产物录制失败：{exc}", file=sys.stderr)

    # —— recorded_at.txt —— #
    (output_dir / "recorded_at.txt").write_text(
        "\n".join([
            f"recorded_at: {datetime.now().isoformat()}",
            f"mode: offline (direct pipeline call)",
            f"workspace_root: {workspace_root}",
            f"sqlite_db: {sqlite_db}",
            f"duration_s: {duration}",
            f"workspace_id: {ws_id}",
            f"final_status: {metadata['final_status']}",
        ])
    )

    return metadata


def _record_workspace_artifacts(ws_id: str, output_dir: Path, workspace_root: Path) -> None:
    """从 workspace_root 找到 ws_id 对应目录，读 tree + 拷贝关键文件"""
    from app.coding.workspace import WorkspaceManager
    ws_mgr = WorkspaceManager()
    try:
        ws_path = ws_mgr.get_workspace_path(ws_id)
    except FileNotFoundError:
        # fallback：手动扫 workspace_root
        cand = [p for p in workspace_root.iterdir() if ws_id in p.name]
        if not cand:
            raise FileNotFoundError(f"workspace {ws_id} 未找到")
        ws_path = cand[0]

    tree_lines: list[str] = []
    key_dir = output_dir / "workspace"
    key_dir.mkdir(exist_ok=True)

    def _is_key_file(rel: Path) -> bool:
        import fnmatch
        rel_str = str(rel)
        for pat in KEY_FILE_PATTERNS:
            if rel.match(pat):
                return True
            if fnmatch.fnmatch(rel_str, pat):
                return True
        return False

    for path in sorted(ws_path.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(ws_path)
        if any(part in IGNORE_DIRS for part in rel.parts):
            continue
        size = path.stat().st_size
        try:
            md5 = hashlib.md5(path.read_bytes()).hexdigest()[:12]
        except OSError:
            md5 = "-"
        tree_lines.append(f"{rel}\t{size}\t{md5}")

        if _is_key_file(rel):
            target = key_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                target.write_bytes(path.read_bytes())
            except OSError:
                pass

    (output_dir / "workspace_tree.txt").write_text("\n".join(tree_lines))


# ══════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Record VibeCodingAgent baseline (offline mode, direct pipeline call)",
    )
    parser.add_argument("case_name", help="Case 名称（如 case_a_rating_star）")
    parser.add_argument("--message", required=True, help="用户需求描述")
    parser.add_argument("--output", required=True, help="输出目录")
    parser.add_argument(
        "--workspace-root",
        default=str(_BASELINES_DIR / "_record_workspaces"),
        help="专用 workspace 根目录（录完可删）",
    )
    parser.add_argument(
        "--sqlite-db",
        default=str(_BASELINES_DIR / "_record_db.sqlite3"),
        help="专用 SQLite DB 文件路径",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="录制前清空专用 workspace + DB",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="非交互模式：输出目录非空时直接覆盖，不提示",
    )
    args = parser.parse_args()

    workspace_root = Path(args.workspace_root)
    sqlite_db = Path(args.sqlite_db)

    if args.clean:
        import shutil
        if sqlite_db.exists():
            sqlite_db.unlink()
            print(f"🧹 cleaned: {sqlite_db}")
        if workspace_root.exists():
            shutil.rmtree(workspace_root)
            print(f"🧹 cleaned: {workspace_root}")

    _bootstrap_env(workspace_root, sqlite_db)
    _setup_sys_path()

    output_dir = Path(args.output).resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        if args.yes or not sys.stdin.isatty():
            print(f"⚠️  输出目录非空，直接覆盖：{output_dir}")
        else:
            print(f"⚠️  输出目录非空：{output_dir}")
            resp = input("继续覆盖？[y/N]: ").strip().lower()
            if resp != "y":
                print("取消")
                return 1

    metadata = asyncio.run(
        record_case(
            args.case_name,
            args.message,
            output_dir,
            workspace_root=workspace_root,
            sqlite_db=sqlite_db,
        )
    )

    print()
    print("═" * 60)
    print(f"✓ 录制完成：{output_dir}")
    print(f"  final_status: {metadata['final_status']}")
    print(f"  total_events: {metadata['total_events']}")
    print(f"  tool_calls:   {metadata['tool_call_count']}")
    print(f"  duration:     {metadata['duration_seconds']}s")
    if metadata.get("error_message"):
        print(f"  ⚠️ error:      {metadata['error_message']}")
    print("═" * 60)

    return 0 if metadata["final_status"] == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
