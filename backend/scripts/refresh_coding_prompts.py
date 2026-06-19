"""把 (whale, default) 系统提示词刷新到当前 app.coding.prompts.AGENT_SYSTEM_PROMPT。

背景: coding agent 的系统提示走 prompt_resolver DB-first，而 coding_prompt_seed 是 insert-only
(行存在就 continue)。所以改了代码常量后，**已经 seed 过的老租户 DB 里仍是旧模板**，新引导
(如「运行/预览必须调 run_workspace_preview」)对他们不生效。

本脚本只刷新「未被管理员改过」的自动 seed 行 —— 判据：
  notes 以 'Seeded from app.coding.prompts.AGENT_SYSTEM_PROMPT' 开头（自动 seed 标记）。
管理员经 /agents UI 改过的行会改 notes/内容，不在此列，不会被覆盖。
另只刷新「内容确实过期」的行（不含目标标记字符串），幂等可重复跑。

用法(本地 SQLite):
    cd backend && ./.venv/bin/python scripts/refresh_coding_prompts.py <db_path> [<db_path> ...]
不传 db_path 时默认刷新 dev 库 /tmp/fb_demo.db。
生产 MySQL 不在本脚本范围（用等价 SQL 或经 /agents「重置为默认」）。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# 让 `import app.coding.prompts` 可用（脚本在 backend/scripts/ 下）。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.coding.prompts import AGENT_SYSTEM_PROMPT  # noqa: E402

# 目标内容的稳定标识：新引导一定包含这个工具名。已含 = 已是新版，跳过。
MARKER = "run_workspace_preview"
SEED_NOTES_PREFIX = "Seeded from app.coding.prompts.AGENT_SYSTEM_PROMPT"


def refresh_db(db_path: str) -> int:
    if not Path(db_path).exists():
        print(f"  [skip] {db_path} 不存在")
        return 0
    con = sqlite3.connect(db_path)
    try:
        try:
            rows = con.execute(
                "select id, tenant_id, coalesce(notes,'') from agent_prompts "
                "where agent_id='whale' and phase='default'"
            ).fetchall()
        except sqlite3.OperationalError as e:
            print(f"  [skip] {db_path}: 无 agent_prompts 表 ({e})")
            return 0

        changed = 0
        for row_id, tenant_id, notes in rows:
            cur = con.execute(
                "select template from agent_prompts where id=?", (row_id,)
            ).fetchone()
            template = cur[0] if cur else ""
            if MARKER in (template or ""):
                continue  # 已是新版
            if not notes.startswith(SEED_NOTES_PREFIX):
                print(f"  [keep] tenant={tenant_id} 非自动 seed(疑似已自定义)，不覆盖")
                continue
            con.execute(
                "update agent_prompts set template=?, "
                "notes=notes || ' [refreshed: +run/preview steering]', "
                "version=version+1, updated_at=current_timestamp where id=?",
                (AGENT_SYSTEM_PROMPT, row_id),
            )
            changed += 1
            print(f"  [refresh] tenant={tenant_id} (whale,default) → 已注入运行/预览引导")
        con.commit()
        return changed
    finally:
        con.close()


def main() -> None:
    db_paths = sys.argv[1:] or ["/tmp/fb_demo.db"]
    total = 0
    for db_path in db_paths:
        print(f"== {db_path} ==")
        total += refresh_db(db_path)
    print(f"完成：共刷新 {total} 行 (whale,default)。")


if __name__ == "__main__":
    main()
