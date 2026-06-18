"""表单菜单名修复(共享 sweep)。

复发生产 bug:0-1 生成的应用在 apaas「表单管理」里所有表单「表单名称」都变成
默认占位「我的待办」。aPaaS 给新建表单/菜单分配的默认菜单名就是「我的待办」;
「表单名称」列展示的正是菜单名 menuName。step_executor 建表后会用真实 form_name
调 create_menu 改名覆盖占位,但失败被静默吞掉(不重试/不回读校验),一旦覆盖没
生效整批就留「我的待办」。

repair_form_menu_names 提供「按 formCode 把 spec 真实名回写菜单名」的幂等 sweep:
  - 生成末尾兜底调一次(根治复发)
  - 存量坏应用用 scripts/repair_form_names.py 单独跑

实现刻意防御两种字段 casing:query_menus 返回的是平台 raw(camelCase:
menuName/formId/formCode/menuType/id,子节点在 children/subMenus/submenus),
但偶有归一后的 snake_case(menu_name/form_code/menu_type)。两种都兜。
"""
from __future__ import annotations

from typing import List, Sequence


def _flatten_menus(menus) -> List[dict]:
    """递归拍平菜单树。子节点键防御 children / subMenus / submenus 三种。"""
    flat: List[dict] = []

    def walk(nodes):
        for node in nodes or []:
            if not isinstance(node, dict):
                continue
            flat.append(node)
            walk(node.get("children") or node.get("subMenus") or node.get("submenus") or [])

    if isinstance(menus, dict):
        menus = menus.get("data") or menus.get("table") or []
    walk(menus if isinstance(menus, list) else [])
    return flat


async def repair_form_menu_names(
    client,
    apaas_app_id: str,
    spec_forms,
    *,
    placeholder_names: Sequence[str] = ("我的待办",),
) -> dict:
    """把 spec 里每个表单的真实名按 formCode 回写到对应菜单的 menuName。

    返回 {"fixed": [...], "failed": [...], "skipped": [...]}：
      - fixed:   [{"code", "from", "to"}]  实际改名成功的
      - failed:  [{"code", "error"}]       改名调用抛异常的(收集不抛)
      - skipped: [code, ...]               无需改名(已正确)或无法匹配 spec 名的

    只在菜单名为空、或命中 placeholder_names(默认「我的待办」占位)时才改名,
    刻意不覆盖用户在 apaas 手动改过的合法自定义菜单名(尤其存量修复脚本会跑在
    已上线应用上,那里菜单名可能被人为改成非 spec 名,不能强行抹回)。
    """
    fixed: List[dict] = []
    failed: List[dict] = []
    skipped: List[str] = []

    # 1) name_by_code:spec_forms → {formCode: real_name},两者非空才入表
    name_by_code: dict = {}
    for f in spec_forms or []:
        if not isinstance(f, dict):
            continue
        code = (f.get("formCode") or f.get("code") or "").strip()
        name = (f.get("name") or f.get("formName") or "").strip()
        if code and name:
            name_by_code[code] = name

    placeholder_set = {str(p).strip() for p in (placeholder_names or ()) if str(p).strip()}

    # 2) 拉菜单树并拍平
    menus = await client.query_menus(apaas_app_id)
    flat = _flatten_menus(menus)

    # 3) 逐个 MODEL 菜单纠正
    for m in flat:
        menu_type = (m.get("menuType") or m.get("menu_type") or "").strip()
        form_id = m.get("formId") or m.get("form_id")
        if menu_type != "MODEL" or not form_id:
            continue

        code = (m.get("formCode") or m.get("form_code") or "").strip()
        cur = (m.get("menuName") or m.get("menu_name") or m.get("name") or "").strip()
        real = name_by_code.get(code)
        menu_id = m.get("id") or m.get("menuId") or ""
        # 改名会重写 menuOrder,读回原值透传,避免把菜单排序重置成 0
        order = m.get("menuOrder") or m.get("menu_order") or 0

        # 只在菜单名为空或命中占位集合时才改——不抹用户手改的合法自定义名
        if real and cur != real and (not cur or cur in placeholder_set):
            try:
                await client.create_menu(apaas_app_id, real, form_id, menu_order=order, menu_id=menu_id)
                fixed.append({"code": code, "from": cur, "to": real})
            except Exception as exc:  # 收集不抛——单个失败不应中断整批 sweep
                failed.append({"code": code, "error": str(exc)})
        else:
            skipped.append(code)

    return {"fixed": fixed, "failed": failed, "skipped": skipped}
