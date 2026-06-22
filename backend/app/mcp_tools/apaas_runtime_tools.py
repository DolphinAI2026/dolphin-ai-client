"""aPaaS runtime data query and process configuration MCP tools."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class _StaticToolMarker:
    """No-op decorator used so static registry tests can see tool functions."""

    def tool(self):
        def _decorate(fn):
            return fn

        return _decorate


mcp = _StaticToolMarker()

_with_client = None
list_apaas_form_views = None
list_apaas_form_components = None
list_apaas_app_processes = None


def _invalidate_process_caches_after_write(env_id: int, apaas_app_id: str) -> None:
    """Best-effort cache invalidation after process writes."""
    aid = str(apaas_app_id or "").strip()
    if not aid:
        return
    try:
        from app.routes.applications.section_content import invalidate_section_cache_for_app

        cleared = invalidate_section_cache_for_app(aid)
        if cleared:
            logger.info("section_content cache invalidated after process write: app=%s cleared=%d", aid, cleared)
    except Exception as exc:  # noqa: BLE001
        logger.debug("section_content cache invalidate skipped after process write (%s): %s", aid, exc)
    try:
        from app.mcp_tools.process_tools import _process_list_cache

        _process_list_cache.pop(f"{int(env_id)}:{aid}", None)
    except Exception as exc:  # noqa: BLE001
        logger.debug("process list cache invalidate skipped after process write (%s): %s", aid, exc)


# ─── 业务数据查询（运行时 data，外部 agent 看数据）──────────────────────
# 之前所有 apaas 工具都在搭建层（角色 / 字典 / 模型 / 表单 / 权限 / 菜单），
# 没工具能看运行时数据 — 用户在「请假申请」表单提交的具体请假记录。
# 这是 外部 agent 「我帮你查上周的请假情况」类对话的前置能力。
#
# 现阶段只暴露**只读**。写入（saveFormData）暂搁 — 风险高，得单独权限设计。

@mcp.tool()
async def query_apaas_business_data(
    env_id: int,
    apaas_app_id: str,
    form_id: str,
    tab_id: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """查询某表单的运行时业务数据（用户提交的数据行，分页）。

    底层调 POST /xdap-app/business/v2/query/listPageBusinessData — 跟 apaas
    平台表单"列表页"页面背后的真接口一致。

    tab_id（表单视图 id）必填：tab_id="" 时本工具会自动调 list_apaas_form_views
    拿默认 tab，省一步；想指定特定视图请显式传 tab_id。

    返回：
      - items: 数据行数组（每行 dict，key 是字段 uuid，value 是字段值）
      - total: 总行数
      - page / page_size: 当前页
      - raw_keys: apaas 平台返回的原始 dict keys（调试用）

    ⚠️ 只读，不支持写入。
    ⚠️ page_size 上限 200。
    ⚠️ 不支持 filter / sort — 想筛过滤拿到一页后客户端 in-memory 筛。
    """
    if not (apaas_app_id.strip() and form_id.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "apaas_app_id+form_id 都必填"}

    page = max(1, int(page or 1))
    page_size = max(1, min(200, int(page_size or 20)))

    # 1) tab_id 没传时自动拿默认 tab
    resolved_tab = (tab_id or "").strip()
    if not resolved_tab:
        ok_v, views_raw = await _with_client(env_id, "拿表单默认 tab",
            lambda c: c.query_form_views(apaas_app_id.strip(), form_id.strip()))
        if not ok_v:
            return {
                "ok": False, "error_code": "TAB_ID_AUTO_RESOLVE_FAILED",
                "message": f"未传 tab_id 且自动拿默认 tab 失败：{views_raw.get('message')}",
                "hint": "显式传 tab_id（先调 list_apaas_form_views 拿）",
            }
        views = views_raw if isinstance(views_raw, list) else (views_raw or {}).get("views") or []
        # 找 isDefault / 取第一个
        default_tab = next((v for v in views if v.get("isDefault") or v.get("default")), None) or (views[0] if views else None)
        if not default_tab:
            return {
                "ok": False, "error_code": "NO_DEFAULT_TAB",
                "message": f"表单 {form_id} 没有视图（tab），无法查业务数据",
            }
        resolved_tab = str(default_tab.get("id") or default_tab.get("tabId") or "").strip()
        if not resolved_tab:
            return {
                "ok": False, "error_code": "NO_DEFAULT_TAB",
                "message": "默认视图缺 id 字段",
                "hint": f"raw default_tab keys: {list(default_tab.keys()) if isinstance(default_tab, dict) else 'not dict'}",
            }

    # 2) 真查
    ok, raw = await _with_client(env_id, "查业务数据",
        lambda c: c.query_business_data(
            apaas_app_id.strip(), form_id.strip(), resolved_tab,
            page=page, page_size=page_size,
        ))
    if not ok:
        return raw

    # apaas v2 接口返回 schema：{code, message, total, table:[...]}
    # `table` 才是数据数组（不是 data / items / records，2026-05-14 实测）
    items = raw.get("table") or raw.get("data") or raw.get("records") or raw.get("items") or []
    total = raw.get("total") or raw.get("totalCount") or len(items)
    return {
        "ok": True,
        "form_id": form_id,
        "tab_id": resolved_tab,
        "page": page,
        "page_size": page_size,
        "total": total,
        "items_count": len(items),
        "items": items,
        "raw_keys": list(raw.keys()),
    }


# ─── 流程 BPMN（写入式）─────────────────────────────────────────────────
# apaas 平台没暴露按 app 维度 list 流程的 endpoint（实测 6 个候选 path 全 404
# / 405），所以本块只做 write — 按 menu_id 维度覆盖式 set。每个 form 菜单
# 最多 1 个流程，所以"覆盖"不会误伤别的流程。
#
# 抽自 step_executor.py:2200-2300 的 BPMN 构造逻辑，保留 LLM 友好 stages 数组
# 输入 → 平台 nodes/edges/bpmn 输出。

# 最小 BPMN XML 骨架（apaas 平台自己根据 nodes/edges 重建完整 BPMN）
_BPMN_MIN_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL" '
    'xmlns:activiti="http://activiti.org/bpmn" '
    'id="Definitions_1" targetNamespace="http://bpmn.io/schema/bpmn">'
    '<process id="Process_1" isExecutable="true">'
    '<startEvent id="START" name="开始"/>'
    '<endEvent id="END" name="结束"/>'
    '</process></definitions>'
)

# 节点用的固定按钮模板
_APPROVE_BUTTONS = [
    {"buttonCode": "APPROVE", "buttonName": "同意", "buttonLabel": "同意",
     "buttonStatus": True, "buttonStyle": "primary", "buttonLabelI18nAssociated": False},
    {"buttonCode": "REJECT", "buttonName": "拒绝", "buttonLabel": "拒绝",
     "buttonStatus": True, "buttonStyle": "primary", "buttonLabelI18nAssociated": False},
]
_START_BUTTONS = [
    {"buttonCode": "NORMAL_TERMINATE", "buttonName": "终止", "buttonLabel": "终止",
     "buttonStatus": False, "buttonStyle": "primary", "buttonLabelI18nAssociated": False},
    {"buttonCode": "RESTART", "buttonName": "重新提交", "buttonLabel": "重新提交",
     "buttonStatus": False, "buttonStyle": "primary", "buttonLabelI18nAssociated": False},
    {"buttonCode": "WITHDRAW", "buttonName": "撤回", "buttonLabel": "撤回",
     "buttonStatus": False, "buttonStyle": "primary", "buttonLabelI18nAssociated": False,
     "withdrawalType": "NEXT_NODE", "withdrawalList": []},
]
_COMMENT_CONFIG = {"required": False, "attachmentUpload": True, "requiredBtns": [], "show": True}
_PHRASE_CONFIG = {"handleType": "INPUT_TYPE", "phrase": "", "status": False}


from app.process_payload import (  # 流程 payload builder 已抽到共享模块（行为不变）
    _bpmn_random_id,
    _approve_node_data_template,
    _start_node_data,
    _end_node_data,
    _process_edge_template,
    _build_executable_bpmn_xml,
    _build_process_payload_v2,
)


_MIN_BPMN_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<definitions xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" '
    'xmlns:omgdc="http://www.omg.org/spec/DD/20100524/DC" '
    'xmlns:omgdi="http://www.omg.org/spec/DD/20100524/DI" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
    'xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL" typeLanguage="http://www.w3.org/2001/XMLSchema" '
    'expressionLanguage="http://www.w3.org/1999/XPath" targetNamespace="http://www.activiti.org/processdef"/>'
)


@mcp.tool()
async def set_apaas_app_process(
    env_id: int,
    apaas_app_id: str,
    menu_id: str,
    process_name: str,
    process_code: str,
    stages: list | None = None,
    process_definition: dict | None = None,
    append: bool = False,
    replace_existing: bool = False,
) -> dict:
    """给某个表单菜单设置审批流程 (用 /common/resource/processConfig 管理 API).

    ⚠️ 2026-05-28 防"加节点变成冲掉原节点": 本工具是覆盖式, 但"在已有流程上加一个审批节点"
    很容易被误用成 stages=[新节点] → 把原有审批节点全冲掉 (实测: 给"还书"流程加 AAAA,
    原"管理员审批"没了)。现在的保护:
      - 该表单**已有**审批流程时, 默认**拒绝**静默覆盖, 返回 PROCESS_EXISTS + 现有节点清单。
      - append=True  → 现有审批节点 + 你传的 stages (在末尾追加)。**加节点就用这个。**
      - replace_existing=True → 用你传的 stages 整条替换 (显式确认要覆盖)。
      - 首次创建 (无现有流程) → 直接按 stages 建, 不受影响。

    ⚠️ 2026-05-25 修: 老版调 /xdap-app/process/save/processConfig (BPMN XML), 实测
    返 ok=true 但 平台 UI 流程设计页空白 — 那是个不同的 process 存储, 现代 UI 不读.
    切到 super-agents-dev build-system.py 实证 work 的 /common/resource/processConfig
    简单 schema (nodes+edges+approvers, 没 BPMN).

    覆盖式: 每个表单最多 1 个流程, 重复调会覆盖.

    stages 数组每项:
      - name: 阶段名 ("部门主管审批")
      - approver_type: ROLE / SUBMITTER / USER (最常 ROLE)
      - approver_code: 审批人 code (ROLE 时是 roleCode; USER 时是 userId)
      - approver_name: 显示名 (可选, 默认用 stage.name)

    process_definition 可选：完整流程拓扑，shape 与 ProcessDesigner 保存结构一致：
      {
        "nodes": [
          {"id":"START","type":"start","label":"开始","position":{"x":320,"y":40},"props":{}},
          {"id":"gw1","type":"condition","label":"条件判断","position":{...},"props":{}},
          {"id":"approve1","type":"assignee_approval","label":"上级审批","position":{...},
           "props":{"approvers":[{"type":"ROLE","value":"<role_id>"}]}},
          {"id":"END","type":"end","label":"结束","position":{...},"props":{}}
        ],
        "edges": [
          {"id":"e1","source":"START","target":"gw1"},
          {"id":"e2","source":"gw1","target":"approve1","label":"信息泄露",
           "condition":"vuln_category == 'info_disclosure'"}
        ]
      }
      传 process_definition 时支持 condition / multi_branch / parallel_gateway 等拓扑；
      兼容 exclusive_gateway / EXCLUSIVE_GATEWAY 等 BPMN/平台别名，内部会归一为 condition。
      stages 线性数组只用于简单顺序审批。

    工具自动加 "开始" + "结束" 2 个固定节点, stages 串成顺序审批节点.

    示例 — 请假 2 级审批:
        stages=[
            {"name":"部门主管审批","approver_type":"ROLE","approver_code":"manager"},
            {"name":"HR 审批","approver_type":"ROLE","approver_code":"hr"}
        ]

    前置:
      - menu_id 从 list_apaas_app_menus 拿 (form_id 不空那行) — 工具会反查 form_code/form_name
      - approver_code 从 list_apaas_app_roles 拿 role.roleCode (是 code 不是 id)
    """
    if not (apaas_app_id.strip() and menu_id.strip() and
            process_name.strip() and process_code.strip()):
        return {
            "ok": False, "error_code": "INVALID_PARAMS",
            "message": "apaas_app_id+menu_id+process_name+process_code 都必填",
        }
    has_definition = isinstance(process_definition, dict) and isinstance(process_definition.get("nodes"), list)
    if not has_definition and (not isinstance(stages, list) or not stages):
        return {
            "ok": False, "error_code": "INVALID_STAGES",
            "message": "stages 必须是非空数组；如需条件/分支流程，请传 process_definition.nodes + process_definition.edges",
        }
    stages = stages or []

    # 反查 form_code + form_name (管理 API 用 form_code 关联表单, 不是 menu_id)
    # ⚠️ query_menus 返的菜单只有 formId 没 formCode, 必须二级反查 form/query/formContext
    # 拿 formCode + formName.
    ok_menus, menus_raw = await _with_client(env_id, "查菜单",
        lambda c: c.query_menus(apaas_app_id.strip()))
    if not ok_menus:
        return menus_raw
    form_id = None
    # query_menus 返回平 list (含 submenus 嵌套) — 按 id 字段找
    def _find(nodes):
        for n in (nodes or []):
            if not isinstance(n, dict):
                continue
            if str(n.get("id") or "") == menu_id.strip():
                return n
            sub = _find(n.get("submenus") or n.get("children") or [])
            if sub:
                return sub
        return None
    target_menu = _find(menus_raw if isinstance(menus_raw, list) else [])
    if target_menu:
        form_id = str(target_menu.get("formId") or "").strip()
    if not form_id:
        return {
            "ok": False, "error_code": "MENU_NOT_FORM",
            "message": f"menu_id={menu_id} 不是表单菜单 (formId 空) 或菜单不存在. "
                       f"先调 list_apaas_app_menus 找 form_id 不空那行 menu_id",
        }

    # 反查角色 — 把 stages 里的 approver_code 映射到 role_id (snowflake), 平台
    # 接受的是 role_id 不是 role_code.
    ok_roles, roles_list = await _with_client(env_id, "查角色",
        lambda c: c.query_roles(apaas_app_id.strip()))
    if not ok_roles:
        return roles_list
    role_by_code: dict[str, dict] = {}
    role_by_id: dict[str, dict] = {}
    for r in (roles_list or []):
        if isinstance(r, dict):
            rcode = str(r.get("roleCode") or "").strip()
            rid = str(r.get("id") or "").strip()
            rname = str(r.get("roleName") or rcode).strip()
            if rcode: role_by_code[rcode] = {**r, "id": rid, "name": rname}
            if rid: role_by_id[rid] = {**r, "code": rcode, "name": rname}

    # 转 stages → stages_with_role (含 role_id + label)
    stages_with_role = []
    for stage_idx, stage in enumerate(stages, start=1):
        approver_type = (stage.get("approver_type") or "ROLE").strip().upper()
        if approver_type == "SUBMITTER":
            stages_with_role.append({
                "name": stage.get("name") or f"审批 {stage_idx}",
                "approver_type": "SUBMITTER",
                "approver_value": "SUBMITTER",
                "approver_label": "申请人",
            })
            continue
        # ROLE — code 或 id 都接, 缺哪个用反查表补齐
        raw_code = str(stage.get("approver_code") or "").strip()
        role_id = ""
        role_label = stage.get("approver_name") or ""
        if raw_code:
            # 1) 当作 role_code 查
            hit = role_by_code.get(raw_code)
            if hit:
                role_id = hit["id"]
                role_label = role_label or hit["name"]
            # 2) 当作 role_id 查 (AI 可能直接传 id 进来)
            elif raw_code in role_by_id:
                role_id = raw_code
                role_label = role_label or role_by_id[raw_code]["name"]
        if not role_id:
            return {
                "ok": False, "error_code": "ROLE_NOT_FOUND",
                "message": f"stage 「{stage.get('name')}」的 approver_code="
                           f"'{raw_code}' 在应用角色列表里找不到. "
                           f"先调 list_apaas_app_roles 看真实 roleCode/id",
                "available_role_codes": list(role_by_code.keys()),
            }
        stages_with_role.append({
            "name": stage.get("name") or f"审批 {stage_idx}",
            "approver_type": "ROLE",
            "approver_value": role_id,
            "approver_label": role_label or "审批人",
        })

    # 2026-05-28 防覆盖丢节点: 先拉该表单现有流程的审批节点 (apaas node.data.approvers
    # 带 type/value=role_id, 可还原成 stage)。已有节点时按 append/replace_existing 决定,
    # 都没传则拒绝静默覆盖, 把现有节点摆出来逼调用方明确选择。
    existing_swr: list = []
    try:
        ok_list, procs_list = await _with_client(
            env_id, "查现有流程", lambda c: c.list_processes(apaas_app_id.strip()))
        if ok_list and isinstance(procs_list, list):
            for pr in procs_list:
                if not isinstance(pr, dict):
                    continue
                if str(pr.get("formId") or "") != form_id and str(pr.get("menuId") or "") != menu_id.strip():
                    continue
                ap_nodes = [
                    n for n in (pr.get("nodes") or [])
                    if isinstance(n, dict) and (n.get("data") or {}).get("type") == "APPROVE"
                ]
                ap_nodes.sort(key=lambda n: (float(n.get("y") or 0), float(n.get("x") or 0)))
                for n in ap_nodes:
                    d = n.get("data") or {}
                    apv = (d.get("approvers") or [{}])
                    apv0 = apv[0] if isinstance(apv, list) and apv else {}
                    atype = str(apv0.get("type") or "ROLE").upper()
                    aval = str(apv0.get("value") or "")
                    title = str(d.get("title") or "审批")
                    if atype == "SUBMITTER":
                        existing_swr.append({"name": title, "approver_type": "SUBMITTER", "approver_value": "SUBMITTER", "approver_label": "申请人"})
                    elif aval:
                        existing_swr.append({"name": title, "approver_type": "ROLE", "approver_value": aval, "approver_label": role_by_id.get(aval, {}).get("name") or title})
                break  # 一个表单最多一条流程
    except Exception as exc:  # noqa: BLE001 — 读现有流程失败按"无现有"处理, 不挡新建
        logger.warning("set_apaas_app_process: 读现有流程失败 (按无现有处理): %s", exc)

    if existing_swr:
        if append:
            stages_with_role = existing_swr + stages_with_role
        elif replace_existing:
            pass  # 显式整条替换
        else:
            return {
                "ok": False,
                "error_code": "PROCESS_EXISTS",
                "message": (
                    f"该表单已有审批流程 (含 {len(existing_swr)} 个审批节点: "
                    f"{[s['name'] for s in existing_swr]})。set 是覆盖式, 直接保存会把它们冲掉。"
                    f"→ 要在末尾**加节点**: 重调本工具并传 append=True; 要**整条替换**: 传 replace_existing=True; "
                    f"或自己在 stages 里带上要保留的节点。"
                ),
                "existing_stages": [
                    {"name": s["name"], "approver_type": s["approver_type"], "approver_value": s["approver_value"]}
                    for s in existing_swr
                ],
            }

    form_components: list[dict[str, Any]] = []
    ok_components, components_raw = await _with_client(
        env_id, "查表单组件",
        lambda c: c.query_form_components(apaas_app_id.strip(), form_id),
    )
    if ok_components and isinstance(components_raw, list):
        form_components = components_raw

    if has_definition:
        try:
            from app.process_translator import build_apaas_bpmn_xml, translate_definition_to_apaas_schema

            role_lookup: dict[str, dict] = {}
            role_lookup.update(role_by_code)
            role_lookup.update(role_by_id)
            payload, warnings = translate_definition_to_apaas_schema(
                process_definition or {},
                apaas_app_id=apaas_app_id.strip(),
                menu_id=menu_id.strip(),
                role_codes=role_lookup,
                form_id=form_id,
                process_name=process_name.strip(),
                process_code=process_code.strip(),
                form_components=form_components,
            )
        except Exception as exc:
            logger.exception("set_apaas_app_process: translate process_definition failed")
            return {
                "ok": False,
                "error_code": "PROCESS_DEFINITION_TRANSLATE_FAILED",
                "message": f"分支流程拓扑翻译失败: {exc}",
            }

        process_rule = payload.get("processRule") if isinstance(payload.get("processRule"), dict) else {}
        for edge_rule_key, rule in list(process_rule.items()):
            if not isinstance(rule, dict) or rule.get("ruleType") != "simple":
                continue
            if rule.get("simpleRuleId"):
                continue
            simple_rule_config = rule.get("simpleRuleConfig")
            if not isinstance(simple_rule_config, dict):
                continue
            ok_rule, saved_rule = await _with_client(
                env_id, "存流程条件规则",
                lambda c, cfg=simple_rule_config: c.save_simple_rule(
                    apaas_app_id.strip(),
                    menu_id.strip(),
                    cfg,
                ),
            )
            if not ok_rule:
                return saved_rule
            if not isinstance(saved_rule, dict) or not str(saved_rule.get("id") or "").strip():
                return {
                    "ok": False,
                    "error_code": "PROCESS_RULE_SAVE_FAILED",
                    "message": f"条件规则保存后未返回 id，edge_rule_key={edge_rule_key}",
                    "platform_response": saved_rule,
                }
            rule["simpleRuleId"] = str(saved_rule.get("id"))
            rule["simpleRuleConfig"] = saved_rule
        if process_rule:
            payload["bpmn"] = build_apaas_bpmn_xml(
                payload.get("nodes") or [],
                payload.get("edges") or [],
                process_rule,
            )

        ok, raw = await _with_client(
            env_id, "存分支流程",
            lambda c: c.save_process_config(apaas_app_id.strip(), payload),
        )
        if not ok:
            return raw
        _invalidate_process_caches_after_write(env_id, apaas_app_id)
        return {
            "ok": True,
            "menu_id": menu_id,
            "form_id": form_id,
            "process_name": process_name,
            "process_code": process_code,
            "definition_mode": True,
            "nodes_count": len(payload.get("nodes") or []),
            "edges_count": len(payload.get("edges") or []),
            "warnings": warnings,
            "platform_response": raw if isinstance(raw, dict) else {"raw": raw},
            "message": (
                f"流程「{process_name}」已按拓扑定义保存到表单菜单 "
                f"(menu_id={menu_id}, {len(payload.get('nodes') or [])} 节点, "
                f"{len(payload.get('edges') or [])} 连线)"
            ),
        }

    # 用 capture 实证 schema 构建 payload (BPMN nodes/edges + 10 button + voteConfig 等)
    payload = _build_process_payload_v2(
        app_id=apaas_app_id.strip(),
        form_id=form_id,
        menu_id=menu_id.strip(),
        process_name=process_name.strip(),
        process_code=process_code.strip(),
        stages_with_role=stages_with_role,
        form_components=form_components,
    )

    ok, raw = await _with_client(env_id, "存流程",
        lambda c: c.save_process_config(apaas_app_id.strip(), payload))
    if not ok:
        return raw
    _invalidate_process_caches_after_write(env_id, apaas_app_id)

    return {
        "ok": True,
        "menu_id": menu_id,
        "form_id": form_id,
        "process_name": process_name,
        "process_code": process_code,
        "stages_count": len(stages),
        "nodes_count": len(payload["nodes"]),
        "platform_response": raw if isinstance(raw, dict) else {"raw": raw},
        "message": (f"流程「{process_name}」已设到表单菜单 (menu_id={menu_id}): "
                    f"START → {len(stages)} 个审批节点 → END"),
    }



def register(
    mcp,
    with_client,
    list_form_views,
    list_form_components,
    list_app_processes,
):
    global _with_client, list_apaas_form_views, list_apaas_form_components, list_apaas_app_processes
    tools = [query_apaas_business_data, set_apaas_app_process]
    _with_client = with_client
    list_apaas_form_views = list_form_views
    list_apaas_form_components = list_form_components
    list_apaas_app_processes = list_app_processes
    for tool in tools:
        mcp.tool()(tool)
    return {tool.__name__: tool for tool in tools}
