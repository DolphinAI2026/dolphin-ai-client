#!/usr/bin/env python3
"""创建 / 重置一个本地平台管理员账号（不依赖 aPaaS 自举）。

背景：本平台默认「首个管理员靠登录时镜像 aPaaS 用户自举」（routes/auth.py
_ensure_apaas_user），seed_initial_data 只建租户+角色不建用户。客户若不接 aPaaS，
就没有第一个能登录的管理员。本脚本补这个缺口，幂等。

用法（在 backend/ 目录，用项目 venv）：
    venv/bin/python scripts/create_admin.py --username admin --password 'Str0ng!Pass'

不传 --password 时从环境变量 ADMIN_PASSWORD 读；都没有则报错退出。
已存在同名用户则更新其密码并提升为平台管理员（可用于重置密码）。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

from sqlalchemy import select

# 允许从 backend/ 根目录 import app.*（脚本在 backend/scripts/ 下）
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from app.database import AsyncSessionLocal, init_db  # noqa: E402
from app.auth import get_password_hash  # noqa: E402
from app.models import User  # noqa: E402
from app.models.tenant import Tenant, Role, UserTenant  # noqa: E402
from app.seed_data import seed_initial_data  # noqa: E402


async def create_admin(username: str, password: str, tenant_code: str) -> int:
    # 1. 确保表结构存在（首次部署时这步建表）
    await init_db()

    async with AsyncSessionLocal() as db:
        # 2. 确保默认租户 + 系统角色存在
        await seed_initial_data(db)

        tenant = (
            await db.execute(select(Tenant).where(Tenant.tenant_code == tenant_code))
        ).scalar_one_or_none()
        if tenant is None:
            print(f"❌ 未找到租户 tenant_code={tenant_code}，无法创建管理员")
            return 1

        role = (
            await db.execute(
                select(Role).where(
                    Role.tenant_id == tenant.id, Role.role_code == "R_tenant_admin"
                )
            )
        ).scalar_one_or_none()

        # 3. upsert 用户（sha256 口令，与 auth.verify_password 对齐）
        user = (
            await db.execute(select(User).where(User.username == username))
        ).scalar_one_or_none()
        created = user is None
        if user is None:
            user = User(
                username=username,
                hashed_password=get_password_hash(password),
                is_platform_admin=True,
                is_active=True,
            )
            db.add(user)
        else:
            user.hashed_password = get_password_hash(password)
            user.is_platform_admin = True
            user.is_active = True
        await db.flush()  # 拿到 user.id

        # 4. upsert 租户成员关系（带租户管理员角色，设为默认租户）
        membership = (
            await db.execute(
                select(UserTenant).where(
                    UserTenant.user_id == user.id, UserTenant.tenant_id == tenant.id
                )
            )
        ).scalar_one_or_none()
        if membership is None:
            db.add(
                UserTenant(
                    user_id=user.id,
                    tenant_id=tenant.id,
                    role_id=role.id if role else None,
                    is_default=True,
                    status=1,
                )
            )
        else:
            if role:
                membership.role_id = role.id
            membership.is_default = True
            membership.status = 1

        await db.commit()

    action = "创建" if created else "更新"
    print(
        f"✅ {action}平台管理员成功: username={username} "
        f"tenant={tenant_code}(id={tenant.id}) is_platform_admin=True"
    )
    print('   登录: POST /api/auth/login  {"username": "%s", "password": "<你的密码>"}' % username)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="创建/重置本地平台管理员账号")
    ap.add_argument("--username", default=os.getenv("ADMIN_USERNAME", "admin"))
    ap.add_argument(
        "--password",
        default=os.getenv("ADMIN_PASSWORD"),
        help="管理员口令；省略则读环境变量 ADMIN_PASSWORD",
    )
    ap.add_argument("--tenant-code", default="default", help="所属租户 code，默认 default")
    args = ap.parse_args()

    if not args.password:
        print("❌ 必须提供 --password 或设置环境变量 ADMIN_PASSWORD")
        return 2

    return asyncio.run(create_admin(args.username, args.password, args.tenant_code))


if __name__ == "__main__":
    raise SystemExit(main())
