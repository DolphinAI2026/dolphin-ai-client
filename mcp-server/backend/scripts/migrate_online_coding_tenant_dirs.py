"""把 _online_coding/<ws_dir> 老路径迁到 _online_coding/<tenant_id>/<ws_dir> 租户子目录。

背景：之前所有租户的 Vibe Coding workspace 共享同一个 root，文件系统层无隔离；
本脚本按 meta.tenant_id 把每个 workspace 移到 {root}/{tenant_id}/<ws_dir>。

跑法：
    cd backend && source venv/bin/activate
    python scripts/migrate_online_coding_tenant_dirs.py            # dry-run 默认
    python scripts/migrate_online_coding_tenant_dirs.py --apply    # 真正移动

注意：
- 只动顶层直挂 root 的老 workspace，已在 tenant 子目录下的不动（幂等）
- meta 里没有 tenant_id 的会跳过并打 WARN（请人工核查）
- 脚本不会 stop docker/podman 容器；运行前请先停止相关 sandbox 容器
  (例：docker ps --filter name=vibe-sandbox- → docker stop <ids>)，
  否则容器内挂载的 /workspace 卷在迁移后会变成"幽灵 inode"
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


# 让 import app.* 可用
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.routes.online_coding import ONLINE_CODING_ROOT, _meta_path, _tenant_root  # noqa: E402


def _is_legacy_top_level_ws(entry: Path) -> bool:
    """判断是否为老路径直挂在 root 下的 workspace 目录。"""
    if not entry.is_dir() or entry.name.startswith("."):
        return False
    if entry.name.isdigit():
        return False  # tenant 子目录
    return _meta_path(entry).exists()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="真正执行移动（默认 dry-run）")
    parser.add_argument(
        "--root",
        type=Path,
        default=ONLINE_CODING_ROOT,
        help=f"workspace 根目录（默认 {ONLINE_CODING_ROOT}）",
    )
    args = parser.parse_args()

    root: Path = args.root
    if not root.exists():
        print(f"[skip] root 不存在: {root}")
        return 0

    moved = 0
    skipped_no_tenant = 0
    skipped_collision = 0

    for entry in sorted(root.iterdir()):
        if not _is_legacy_top_level_ws(entry):
            continue

        try:
            meta = json.loads(_meta_path(entry).read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[warn] {entry.name}: 读 meta 失败 {exc}; 跳过")
            continue

        tenant_id = meta.get("tenant_id")
        if not tenant_id:
            skipped_no_tenant += 1
            print(f"[warn] {entry.name}: meta 无 tenant_id（owner user_id={meta.get('user_id')}）；请人工归类后重跑")
            continue

        target_parent = _tenant_root(int(tenant_id))
        target = target_parent / entry.name

        if target.exists():
            skipped_collision += 1
            print(f"[skip] {entry.name}: 目标已存在 {target}（可能上次跑过一半），人工核对")
            continue

        if args.apply:
            target_parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(entry), str(target))
            print(f"[move] {entry} → {target}")
        else:
            print(f"[plan] {entry} → {target}")
        moved += 1

    mode = "APPLIED" if args.apply else "DRY-RUN"
    print(
        f"\n[{mode}] 计划/执行 {moved} 个, 跳过(无 tenant)={skipped_no_tenant}, 跳过(目标冲突)={skipped_collision}"
    )
    if not args.apply:
        print("（这是 dry-run；加 --apply 真正移动）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
