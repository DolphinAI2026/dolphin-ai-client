"""可复用就地修复:把「表单管理」列表里停在平台默认占位「我的待办」的表单实体名同步回真实名。

复发 bug:0-1 生成的应用所有表单「表单名称」都显示占位「我的待办」,但表单编码、菜单名、
设计器标题都对。根因(实证):「表单名称」列是表单实体名(allFormConfigList.formName),
建表时由 formConfigDetail 保存从 formContext 同步,老版本该保存偶发失败 → 停在占位。
本脚本按 apaas_app_id 找本地 Application 读 config_preview 拿 spec(formCode→真实名),
对实体名为占位的模型页面表单重跑「查 formContext → 固化真实名 → 存 formConfigDetail」
(等价设计器点保存),同步实体名。幂等,可重复跑;没 spec 时退化用菜单名作真实名。

用法: python scripts/repair_form_names.py <apaas_app_id> <env_id> [--dry-run]
例:   python scripts/repair_form_names.py 855238283054022656 2
"""
import asyncio
import logging
import sys

logging.disable(logging.CRITICAL)

_args = [a for a in sys.argv[1:] if not a.startswith("--")]
APP = _args[0] if len(_args) > 0 else ""
ENV = int(_args[1]) if len(_args) > 1 else 59
DRY_RUN = "--dry-run" in sys.argv[1:]


async def main():
    if not APP:
        print("用法: python scripts/repair_form_names.py <apaas_app_id> <env_id> [--dry-run]")
        return

    from sqlalchemy import select

    from app.coding.apaas_tools import call_apaas_with_relogin
    from app.database import AsyncSessionLocal
    from app.json_utils import loads_if_str
    from app.models import Application
    from app.operations.form_name_repair import (
        repair_form_entity_names,
        _name_by_code_from_spec,
    )

    # 1) 本地查 Application 拿 config_preview → spec forms(formCode→真实名,可选;缺则用菜单名)
    name_by_code = {}
    async with AsyncSessionLocal() as db:
        row = await db.execute(select(Application).where(Application.apaas_app_id == APP))
        app = row.scalar_one_or_none()
        if app:
            config = loads_if_str(app.config_preview) or {}
            data = config.get("data", config)
            spec_forms = data.get("forms") or config.get("forms") or []
            name_by_code = _name_by_code_from_spec(spec_forms)
            print(f"app={APP} (本地 id={app.id}, 名称={app.app_name}) spec 表单数={len(spec_forms)}\n")
        else:
            print(f"未找到 apaas_app_id={APP} 的本地 Application,退化用平台菜单名作真实名。\n")

    # 2) call_apaas_with_relogin 调实体名 sweep
    async def fn(c):
        return await repair_form_entity_names(
            c, APP, name_by_code=name_by_code, dry_run=DRY_RUN
        )

    async with AsyncSessionLocal() as db:
        res = await call_apaas_with_relogin(ENV, db, fn)

    # 3) 打印 fixed / failed / skipped
    fixed = res.get("fixed", [])
    failed = res.get("failed", [])
    skipped = res.get("skipped", [])
    verb = "将修复(dry-run)" if DRY_RUN else "已修复"
    print(f"{verb} {len(fixed)} 个 (扫描 {res.get('scanned', 0)} 个菜单):")
    for f in fixed:
        print(f"  {str(f.get('code')):<24} 「{f.get('from')}」 -> 「{f.get('to')}」")
    if failed:
        print(f"\n失败 {len(failed)} 个(需人工排查):")
        for f in failed:
            print(f"  {str(f.get('code')):<24} {f.get('error')}")
    print(f"\n跳过(已正确/无真实名){len(skipped)} 个")


if __name__ == "__main__":
    asyncio.run(main())
