"""扫描 workspace .workspace.json，给老 meta 回填 tenant_id。

问题：
- 老的 component workspace meta 大多没有 tenant_id 字段
- list_accessible_workspaces 的 fallback 让 meta_tenant=None 时不过滤 → 跨租户泄漏

回填策略：
- 按 meta.user_id 查 user_tenants，取该用户的默认 active 租户
- 没默认租户的退到该用户的第一个 active membership
- user_id 也没的（极少数）跳过 + 打 warn

跑法：
    cd backend && source .venv/bin/activate
    python scripts/migrate_workspace_tenant_id.py            # dry-run
    python scripts/migrate_workspace_tenant_id.py --apply    # 真正写入
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.coding.workspace import WORKSPACE_SEARCH_ROOTS  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="真正写入（默认 dry-run）")
    args = parser.parse_args()

    import pymysql  # 用同步 driver 避免 asyncio 复杂度

    # 读 .env 拿 db 连接
    env_path = Path(__file__).resolve().parents[1] / ".env"
    db_url = ""
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                db_url = line.split("=", 1)[1].strip().strip("'\"")
                break
    if not db_url:
        import os
        db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        print("[error] DATABASE_URL not found")
        return 1

    # mysql+aiomysql://user:pw@host:port/db?...
    import re
    m = re.match(r"mysql\+\w+://([^:]+):([^@]+)@([^:]+):(\d+)/(\w+)", db_url)
    if not m:
        print(f"[error] DATABASE_URL pattern not recognized: {db_url}")
        return 1
    user, pw, host, port, db = m.group(1), m.group(2), m.group(3), int(m.group(4)), m.group(5)

    conn = pymysql.connect(host=host, port=port, user=user, password=pw, database=db, charset="utf8mb4")
    cur = conn.cursor()

    # 一次性把 user → default tenant 映射拉下来
    cur.execute(
        "SELECT user_id, tenant_id, is_default FROM user_tenants WHERE status = 1 ORDER BY is_default DESC, joined_at ASC"
    )
    user_tenant_map: dict[int, int] = {}
    for uid, tid, _is_default in cur.fetchall():
        user_tenant_map.setdefault(int(uid), int(tid))
    conn.close()
    print(f"loaded {len(user_tenant_map)} user → default tenant mappings")

    counts = {"with_tenant": 0, "filled": 0, "skipped_no_user": 0, "skipped_no_membership": 0}
    plan: list[tuple[Path, int, int]] = []

    for root in WORKSPACE_SEARCH_ROOTS:
        if not Path(root).exists():
            continue
        for p in Path(root).rglob(".workspace.json"):
            # 跳过 node_modules 等无关目录
            if any(part in ("node_modules", ".dependency-cache", ".git") for part in p.parts):
                continue
            try:
                meta = json.loads(p.read_text(encoding="utf-8"))
            except Exception as exc:
                print(f"[warn] {p}: 读 meta 失败 {exc}; 跳过")
                continue

            if meta.get("tenant_id") is not None:
                counts["with_tenant"] += 1
                continue

            uid = meta.get("user_id")
            if uid is None:
                counts["skipped_no_user"] += 1
                print(f"[warn] {p}: meta 无 user_id；跳过")
                continue

            tid = user_tenant_map.get(int(uid))
            if tid is None:
                counts["skipped_no_membership"] += 1
                print(f"[warn] {p}: user_id={uid} 没找到 active 租户成员关系；跳过")
                continue

            plan.append((p, int(uid), int(tid)))

    print(f"\n准备回填 {len(plan)} 个 workspace meta（应用前 {counts['with_tenant']} 个已有 tenant_id）")
    for p, uid, tid in plan[:5]:
        print(f"  示例: {p.parent.name[:50]:<50} user_id={uid} → tenant_id={tid}")
    if len(plan) > 5:
        print(f"  ... 还有 {len(plan) - 5} 个")

    if args.apply:
        for p, uid, tid in plan:
            try:
                meta = json.loads(p.read_text(encoding="utf-8"))
                meta["tenant_id"] = tid
                p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
                counts["filled"] += 1
            except Exception as exc:
                print(f"[error] 写 {p}: {exc}")

    mode = "APPLIED" if args.apply else "DRY-RUN"
    print(f"\n[{mode}]")
    print(f"  已有 tenant_id: {counts['with_tenant']}")
    print(f"  回填: {counts['filled' if args.apply else 'with_tenant']}（计划 {len(plan)}）")
    print(f"  跳过(无 user_id): {counts['skipped_no_user']}")
    print(f"  跳过(无 membership): {counts['skipped_no_membership']}")
    if not args.apply:
        print("\n（这是 dry-run；加 --apply 真正写入）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
