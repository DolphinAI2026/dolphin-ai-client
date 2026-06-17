"""本地 authority 模式下开一个桌面产品账号(带独立租户 + tenant_admin)。

桌面 .app 默认 authority 模式(见 desktop_sidecar.py): 桌面账号在本地 SQLite 校验。
公网账号权威(agent.dfy)部署前, 用这个脚本直接往桌面 app 的本地库开号。

用法(在 backend/ 下, 用 .venv):
    .venv/bin/python scripts/seed_desktop_account.py --username mars --password ruijing2026

--data-dir 默认指向 Tauri 的 app_data_dir (identifier=com.ruijing.builder), 即 .app 真正用的库。
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

# backend/ 进 sys.path, 以便 import desktop_sidecar / app.*
BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import desktop_sidecar  # noqa: E402  复用 build_env, 与 sidecar 运行时 env 零漂移


def _default_data_dir() -> Path:
    # 与 Tauri app_data_dir() 一致: ~/Library/Application Support/<identifier>
    return Path.home() / "Library" / "Application Support" / "com.ruijing.builder"


async def _run(username: str, password: str, data_dir: Path) -> int:
    db_path = data_dir / "app.db"
    print(f"==> 目标库: {db_path}")
    # 注入与 sidecar 一致的本地 env(DATABASE_URL/DESKTOP_MODE/JWT/加密 key 等), 必须早于 import app.*
    desktop_sidecar.build_env(data_dir=data_dir, port=0)

    from app.database import init_db, AsyncSessionLocal  # noqa: E402
    from app import desktop_accounts as da  # noqa: E402
    from app.deps import resolve_default_tenant_id_for_user  # noqa: E402
    from app.models import User  # noqa: E402
    from sqlalchemy import select  # noqa: E402

    await init_db()  # create_all + 幂等 ALTER(给 Phase 0 老库加 account_source 列)

    async with AsyncSessionLocal() as db:
        existing = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
        if existing is not None:
            tid = await resolve_default_tenant_id_for_user(db, existing.id)
            print(f"账号 {username!r} 已存在 (id={existing.id}, account_source={existing.account_source}, "
                  f"tenant_id={tid}) — 不重复建号。")
            if existing.account_source != "desktop":
                print("  ⚠️ 该账号 account_source 不是 'desktop', 桌面登录(/api/desktop-auth/login)不会认它。")
            return 0
        # 本地 authority 开号 = 本机管理员(能进平台管理配自己的 LLM/aPaaS)。
        user = await da.provision_local_admin_account(db, username, password)
        await db.commit()
        tid = await resolve_default_tenant_id_for_user(db, user.id)
        print(f"✅ 建号成功: {username!r} (id={user.id}, account_source={user.account_source}, "
              f"tenant_id={tid}, is_platform_admin=True)")
        print(f"   登录: 桌面 app 用 用户名={username} 密码={password}")
    return 0


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--username", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--data-dir", default=str(_default_data_dir()),
                   help="桌面 app 的 app_data_dir (默认 com.ruijing.builder)")
    args = p.parse_args()
    if len(args.password) < 8:
        print("密码至少 8 位。", file=sys.stderr)
        sys.exit(2)
    rc = asyncio.run(_run(args.username, args.password, Path(args.data_dir)))
    sys.exit(rc)


if __name__ == "__main__":
    main()
