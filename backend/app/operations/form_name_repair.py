"""表单名修复(共享 sweep)。

复发生产 bug:0-1 生成的应用在 apaas「表单管理」里所有表单「表单名称」都变成
默认占位「我的待办」,但表单编码各不相同且正确。

⚠️ 根因(2026-06-18 浏览器实证纠正):「表单名称」列展示的是**表单实体名**
(allFormConfigList.formName),**不是**菜单名 menuName(菜单名/设计器标题本来就对)。
建表那一刻由 formConfigDetail 保存从 formContext.formName 同步实体名;老版本生成时该
保存(step_executor `_finalize_created_form_config`)偶发失败 → 实体名停在平台默认占位。
实证:在得帆云设计器对表单点保存,「表单管理」对应行「表单名称」即从「我的待办」变真实名。

本模块两个 sweep:
  - repair_form_entity_names —— **真正的修复**:对实体名为占位的模型页面表单重跑
    「查 formContext → 固化真实名 → 存 formConfigDetail」(等价设计器点保存),同步实体名。
    生成末尾兜底调一次 + 存量坏应用用 scripts/repair_form_names.py / MCP repair_apaas_form_names 跑。
  - repair_form_menu_names —— 旧的菜单名回写 sweep(基于早期误诊;菜单名通常已对,
    保留作可选的菜单名纠偏工具,非「表单名称」列的修复路径)。

实现刻意防御两种字段 casing:query_menus 返回的是平台 raw(camelCase:
menuName/formId/formCode/menuType/id,子节点在 children/subMenus/submenus),
但偶有归一后的 snake_case(menu_name/form_code/menu_type)。两种都兜。
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)


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


def _name_by_code_from_spec(spec_forms) -> Dict[str, str]:
    """spec_forms → {formCode: real_name}(两者非空才入表)。"""
    out: Dict[str, str] = {}
    for f in spec_forms or []:
        if not isinstance(f, dict):
            continue
        code = (f.get("formCode") or f.get("code") or "").strip()
        name = (f.get("name") or f.get("formName") or "").strip()
        if code and name:
            out[code] = name
    return out


async def repair_form_entity_names(
    client,
    apaas_app_id: str,
    *,
    placeholder_names: Sequence[str] = ("我的待办",),
    name_by_code: Optional[Dict[str, str]] = None,
    dry_run: bool = False,
) -> dict:
    """修复「表单管理」列表「表单名称」列停在占位「我的待办」的存量表单(真正的修复)。

    机制(2026-06-18 实证):「表单名称」是表单实体名(allFormConfigList.formName),
    建表时由 formConfigDetail 保存从 formContext 同步;老应用该保存失败 → 停在占位。
    本 sweep 对每个「实体名为空或占位」的 MODEL 表单重跑 _finalize_created_form_config
    (查 formContext → 固化真实名到 顶层/simpleFormConfig/detailPage → 存 formConfigDetail),
    等价在设计器点保存,把实体名同步成真实名。幂等:已正确的表单跳过、不重存。

    真实名来源优先级:name_by_code[formCode](spec,可选) > 菜单名 menuName。
    拿不到真实名(菜单名也是占位且无 spec)时跳过,绝不乱写。

    返回 {"fixed":[...], "failed":[...], "skipped":[...], "scanned":N}:
      - fixed:   [{"code","form_id","from","to"[,"dry_run"]}]  实际(或计划)修的
      - failed:  [{"code","form_id","error"}]                  保存抛异常的(收集不抛)
      - skipped: [{"code","form_id","reason"}]                 already_correct / no_real_name
    """
    from app.operations.form_config import _finalize_created_form_config

    placeholder_set = {str(p).strip() for p in (placeholder_names or ()) if str(p).strip()}
    name_by_code = name_by_code or {}

    # 1) 读实体名(坏的那一列)。接口不可用时降级:entity_name_by_id 留空 → 无法判定坏不坏
    #    → 对所有 MODEL 表单重存(幂等,不会改坏已正确的)。
    entity_name_by_id: Dict[str, Optional[str]] = {}
    entity_available = True
    query_all = getattr(client, "query_all_form_configs", None)
    if callable(query_all):
        try:
            for ef in (await query_all(apaas_app_id)) or []:
                if not isinstance(ef, dict):
                    continue
                fid = str(ef.get("id") or ef.get("formId") or ef.get("form_id") or "").strip()
                if fid:
                    entity_name_by_id[fid] = str(ef.get("formName") or ef.get("form_name") or "").strip()
        except Exception as exc:  # noqa: BLE001 — 读不到就降级,不中断修复
            logger.warning("query_all_form_configs 失败,降级重存所有 MODEL 表单 (app=%s): %s", apaas_app_id, exc)
            entity_available = False
    else:
        entity_available = False

    # 实体名清单为空(接口返空 / 响应结构没命中已知 key)→ 降级重存所有 MODEL 表单(幂等),
    # 避免「解析没命中 → 所有表单判 not_in_form_list → 一个都不修」的静默失效。
    if entity_available and not entity_name_by_id:
        logger.warning("query_all_form_configs 返空,降级重存所有 MODEL 表单 (app=%s)", apaas_app_id)
        entity_available = False

    # 2) 拉菜单树拍平,逐个 MODEL 表单修
    menus = await client.query_menus(apaas_app_id)
    flat = _flatten_menus(menus)

    fixed: List[dict] = []
    failed: List[dict] = []
    skipped: List[dict] = []

    for m in flat:
        menu_type = (m.get("menuType") or m.get("menu_type") or "").strip()
        form_id = str(m.get("formId") or m.get("form_id") or "").strip()
        if menu_type != "MODEL" or not form_id:
            continue

        form_code = (m.get("formCode") or m.get("form_code") or "").strip()
        menu_name = (m.get("menuName") or m.get("menu_name") or m.get("name") or "").strip()
        menu_id = str(m.get("id") or m.get("menuId") or "").strip()

        cur_entity = entity_name_by_id.get(form_id) if entity_available else None
        if entity_available:
            if form_id not in entity_name_by_id:
                # 实体名清单里没这个 form(allFormConfigList 没返)→ 无法确认坏,不动
                skipped.append({"code": form_code, "form_id": form_id, "reason": "not_in_form_list"})
                continue
            if cur_entity and cur_entity not in placeholder_set:
                # 实体名非空非占位 → 已正确,跳过
                skipped.append({"code": form_code, "form_id": form_id, "reason": "already_correct"})
                continue

        real_name = (name_by_code.get(form_code) or menu_name).strip()
        if not real_name or real_name in placeholder_set:
            skipped.append({"code": form_code, "form_id": form_id, "reason": "no_real_name"})
            continue

        if dry_run:
            fixed.append({"code": form_code, "form_id": form_id,
                          "from": cur_entity, "to": real_name, "dry_run": True})
            continue

        try:
            await _finalize_created_form_config(
                client,
                apaas_app_id,
                form_id,
                form_name=real_name,
                form_code=form_code,
                all_model_codes=[],
                menu_id=menu_id,
            )
            fixed.append({"code": form_code, "form_id": form_id, "from": cur_entity, "to": real_name})
        except Exception as exc:  # noqa: BLE001 — 单个失败不中断整批 sweep
            failed.append({"code": form_code, "form_id": form_id, "error": str(exc)})

    return {
        "fixed": fixed,
        "failed": failed,
        "skipped": skipped,
        "scanned": len(flat),
        "total_fixed": len(fixed),
        "total_failed": len(failed),
    }


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
