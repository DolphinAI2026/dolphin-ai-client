"""可复用就地修复:把表单菜单名从平台默认占位「我的待办」改回 spec 真实表单名。

复发 bug:0-1 生成的应用所有表单「表单名称」(=菜单 menuName)都变成默认占位
「我的待办」,但表单编码各不相同且正确。本脚本按 apaas_app_id 找到本地 Application,
读它的 config_preview 拿 spec forms(formCode→真实名),拉平台菜单树,按 formCode
把真实名回写到对应菜单名。幂等,可重复跑。

用法: python scripts/repair_form_names.py <apaas_app_id> <env_id>
例:   python scripts/repair_form_names.py 850744994011545600 59
"""
import asyncio
import logging
import sys

logging.disable(logging.CRITICAL)

APP = sys.argv[1] if len(sys.argv) > 1 else ""
ENV = int(sys.argv[2]) if len(sys.argv) > 2 else 59


async def main():
    if not APP:
        print("用法: python scripts/repair_form_names.py <apaas_app_id> <env_id>")
        return

    from sqlalchemy import select

    from app.coding.apaas_tools import call_apaas_with_relogin
    from app.database import AsyncSessionLocal
    from app.json_utils import loads_if_str
    from app.models import Application
    from app.operations.form_name_repair import repair_form_menu_names

    # 1) 本地查 Application 拿 config_preview → spec forms
    async with AsyncSessionLocal() as db:
        row = await db.execute(select(Application).where(Application.apaas_app_id == APP))
        app = row.scalar_one_or_none()
        if not app:
            print(f"未找到 apaas_app_id={APP} 的本地 Application")
            return
        config = loads_if_str(app.config_preview) or {}

    data = config.get("data", config)
    spec_forms = data.get("forms") or config.get("forms") or []
    print(f"app={APP} (本地 id={app.id}, 名称={app.app_name}) spec 表单数={len(spec_forms)}\n")
    if not spec_forms:
        print("config_preview 里没有 forms,无法修复。")
        return

    # 2) call_apaas_with_relogin 调共享 sweep
    async def fn(c):
        return await repair_form_menu_names(c, APP, spec_forms)

    async with AsyncSessionLocal() as db:
        res = await call_apaas_with_relogin(ENV, db, fn)

    # 3) 打印 fixed / failed / skipped
    fixed = res.get("fixed", [])
    failed = res.get("failed", [])
    skipped = res.get("skipped", [])
    print(f"已修复 {len(fixed)} 个:")
    for f in fixed:
        print(f"  {f.get('code'):<24} 「{f.get('from')}」 -> 「{f.get('to')}」")
    if failed:
        print(f"\n失败 {len(failed)} 个(需人工排查):")
        for f in failed:
            print(f"  {f.get('code'):<24} {f.get('error')}")
    print(f"\n跳过(无需改名/无 spec 名){len(skipped)} 个: {skipped}")


if __name__ == "__main__":
    asyncio.run(main())
