"""aPaaS role, form, and permission MCP tools."""
from __future__ import annotations

import copy
import logging

from app.mcp_envelope import _ok
from app.mcp_tools.form_components import _component_snapshot

logger = logging.getLogger(__name__)


class _StaticToolMarker:
    """No-op decorator used so static registry tests can see tool functions."""

    def tool(self):
        def _decorate(fn):
            return fn

        return _decorate


mcp = _StaticToolMarker()

_with_client = None
list_apaas_app_menus = None
list_apaas_app_models = None

# ═══════════════════════════════════════════════════════════════════════════
# aPaaS 应用配置精细操作（角色 CRUD）
#
# 跟 SPEC 文档流程（update_app_from_doc → execute_change_plan）的区别：
# 这些工具是**直接对话式精细操作**，agent 可以在跟用户聊天时直接增删改查应用元素，
# 不必走"写新版 md → diff → 执行"流程。适合用户说"加个 XX 角色"这种增量需求。
# ═══════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def list_apaas_app_roles(env_id: int, apaas_app_id: str, keyword: str = "") -> dict:
    """列指定 aPaaS 应用的角色清单（含 roleId / roleCode / roleName / 启用状态）。

    可选 keyword 模糊过滤。返回的 roleId 给后续 update / delete / 加成员用。
    """
    if not apaas_app_id.strip():
        return {"ok": False, "error_code": "INVALID_APAAS_APP_ID", "message": "apaas_app_id 必填"}
    ok, raw = await _with_client(
        env_id, "列角色",
        lambda c: c.query_roles(apaas_app_id.strip(), keyword=keyword or ""),
    )
    if not ok:
        return raw
    roles = []
    for r in (raw or []):
        if not isinstance(r, dict):
            continue
        roles.append({
            "role_id": str(r.get("id") or r.get("roleId") or ""),
            "role_code": str(r.get("roleCode") or r.get("code") or ""),
            "role_name": str(r.get("roleName") or r.get("name") or ""),
            "use_scope": str(r.get("useScope") or ""),
            "internal_resource": bool(r.get("internalResource", False)),
            "enable_group_param": str(r.get("enableGroupParam") or "DISABLE"),
        })
    return {
        "ok": True, "env_id": env_id, "apaas_app_id": apaas_app_id.strip(),
        "roles": roles, "total": len(roles),
    }


# ─── Phase D: 权限矩阵 ─────────────────────────────────────────────────────────
# 2026-05-26 Phase D — design-v4 RoleManagePanel 矩阵 view 数据源.
# 聚合 roles × resources (page / data / process / app_setting) 一次返回.


# matrix mock 配置 — 根据 role_code 关键字推断默认权限.
# P2 真接 apaas 权限 API (list_apaas_form_permissions × N 拼 + 解析 dataPermGroups
# + 解析 operPermGroups) 替换本表.
_ROLE_CODE_PERMISSION_HINTS: list[tuple[tuple[str, ...], str]] = [
    # (role_code 关键字, default perm) — 第一个匹配的 hint 胜出.
    (("admin", "manager", "管理", "管理员", "超级"), "all"),
    (("approver", "审批", "审核", "approve", "reviewer"), "rw"),
    (("applicant", "submit", "发起", "申请", "员工", "user", "普通"), "rw"),
    (("viewer", "view", "read", "查看", "只读", "guest", "访客"), "r"),
]
# 默认 perm — 没匹配 hint 时给 "rw".
_DEFAULT_ROLE_PERM = "rw"

# 应用设置 — 静态资源, 不来自 apaas API. design 显示的 4 个固定按钮.
_APP_SETTING_RESOURCES: list[dict] = [
    {"code": "app_create", "name": "创建应用"},
    {"code": "app_settings", "name": "应用设置"},
    {"code": "app_deploy", "name": "部署应用"},
    {"code": "app_import_export", "name": "导入导出"},
]


def _infer_role_permission(role_code: str, role_name: str) -> str:
    """根据 role_code / role_name 推断默认权限 — mock 实现.

    返 'all' / 'rw' / 'r' / 'none' 之一. 多 hint 匹配时第一胜出.
    """
    text = (role_code + " " + role_name).lower()
    for keywords, perm in _ROLE_CODE_PERMISSION_HINTS:
        for kw in keywords:
            if kw.lower() in text:
                return perm
    return _DEFAULT_ROLE_PERM


def _mock_matrix_for_resource(
    role_code: str, role_name: str, resource_type: str, resource_code: str,
) -> str:
    """根据 role + resource 双维度 mock 权限值.

    简化策略 (本 session, P2 真接 apaas):
      - 管理员对所有资源都 all
      - 审批/审核对 page=rw / data=r / process=rw / app_setting=none
      - 发起/申请对 page=rw / data=r / process=r / app_setting=none
      - 查看/只读对 page=r / data=none / process=none / app_setting=none
      - 默认 rw / page rw / data r / process r / app_setting none
    """
    base = _infer_role_permission(role_code, role_name)
    if base == "all":
        return "all"
    if resource_type == "app_setting":
        return "all" if base == "all" else "none"
    if resource_type == "data":
        if base == "rw":
            return "r"
        return base
    if resource_type == "process":
        if base == "r":
            return "none"
        return base
    # page
    if base == "none":
        return "r"
    return base


@mcp.tool()
async def get_role_resource_matrix(env_id: int, apaas_app_id: str) -> dict:
    """聚合应用所有角色 × 资源的权限矩阵 (一次拉全, 给前端 design-v4 权限矩阵 view).

    数据来源:
      - 角色: list_apaas_app_roles (复用)
      - 页面 (forms / lists): list_apaas_app_menus 过滤 menu_type=MODEL
      - 数据 (models): list_apaas_app_models (with_fields=False 省 token)
      - 流程 (processes): list_apaas_app_menus 过滤 menu_type=PROCESS, 没有就空 list
      - 应用设置: 静态 4 项 (创建 / 设置 / 部署 / 导入导出)

    matrix 字段:
      role_id → resource_id → perm ∈ {'all', 'rw', 'r', 'none'}
      暂走 mock 推断 (根据 role_code 关键字 + resource_type). P2 真接 apaas
      list_apaas_form_permissions 取代 mock.

    返结构:
      {
        ok: True, env_id, apaas_app_id,
        roles: [{role_id, role_code, role_name, member_count}],
        resources: {
          page: [{id, code, name}],
          data: [{id, code, name}],
          process: [{id, code, name}],
          app_setting: [{code, name}],
        },
        matrix: {role_id: {resource_id: perm}},
        is_mock: True,  # 提示前端 P2 真接前都是 mock
      }
    """
    if not apaas_app_id.strip():
        return {"ok": False, "error_code": "INVALID_APAAS_APP_ID",
                "message": "apaas_app_id 必填"}
    apaas_app_id_clean = apaas_app_id.strip()

    # 1) 拉角色 (复用工具). 失败直接返 — 矩阵核心维度.
    roles_resp = await list_apaas_app_roles(env_id, apaas_app_id_clean)
    if not roles_resp.get("ok"):
        return roles_resp
    roles_raw = roles_resp.get("roles") or []

    # 2) 拉菜单 (页面 + 流程过滤). 失败时降级 — page/process 空 list 不阻断矩阵.
    menus_resp = await list_apaas_app_menus(env_id, apaas_app_id_clean)
    menus_raw: list = []
    if isinstance(menus_resp, dict) and menus_resp.get("ok"):
        m = menus_resp.get("menus") or []
        if isinstance(m, list):
            menus_raw = m

    # 3) 拉模型 (数据维度). 失败时空 list 不阻断.
    models_resp = await list_apaas_app_models(env_id, apaas_app_id_clean, with_fields=False)
    models_raw: list = []
    if isinstance(models_resp, dict) and models_resp.get("ok"):
        ms = models_resp.get("models") or []
        if isinstance(ms, list):
            models_raw = ms

    # 4) 归一资源 list.
    page_resources: list[dict] = []
    process_resources: list[dict] = []
    for m in menus_raw:
        if not isinstance(m, dict):
            continue
        mtype = str(m.get("menu_type") or "").upper()
        item = {
            "id": str(m.get("menu_id") or ""),
            "code": str(m.get("form_code") or m.get("menu_code") or ""),
            "name": str(m.get("menu_name") or ""),
        }
        if not item["id"]:
            continue
        if mtype == "MODEL":
            page_resources.append(item)
        elif mtype == "PROCESS":
            process_resources.append(item)

    data_resources: list[dict] = []
    for d in models_raw:
        if not isinstance(d, dict):
            continue
        data_resources.append({
            "id": str(d.get("model_id") or d.get("id") or ""),
            "code": str(d.get("model_code") or d.get("code") or ""),
            "name": str(d.get("model_name") or d.get("name") or ""),
        })
    data_resources = [d for d in data_resources if d["id"]]

    # app_setting 静态 4 项 — id == code 用于矩阵 key.
    app_setting_resources: list[dict] = [
        {"id": r["code"], "code": r["code"], "name": r["name"]}
        for r in _APP_SETTING_RESOURCES
    ]

    # 5) 归一角色 list (member_count 暂走 0 — P2 真接 list_apaas_role_members).
    roles_out: list[dict] = []
    for r in roles_raw:
        if not isinstance(r, dict):
            continue
        roles_out.append({
            "role_id": str(r.get("role_id") or ""),
            "role_code": str(r.get("role_code") or ""),
            "role_name": str(r.get("role_name") or ""),
            "member_count": 0,  # P2 真接成员数
        })
    roles_out = [r for r in roles_out if r["role_id"]]

    # 6) 构建 matrix — role_id × resource_id → perm.
    matrix: dict[str, dict[str, str]] = {}
    for r in roles_out:
        row: dict[str, str] = {}
        for resource in page_resources:
            row[resource["id"]] = _mock_matrix_for_resource(
                r["role_code"], r["role_name"], "page", resource["code"],
            )
        for resource in data_resources:
            row[resource["id"]] = _mock_matrix_for_resource(
                r["role_code"], r["role_name"], "data", resource["code"],
            )
        for resource in process_resources:
            row[resource["id"]] = _mock_matrix_for_resource(
                r["role_code"], r["role_name"], "process", resource["code"],
            )
        for resource in app_setting_resources:
            row[resource["id"]] = _mock_matrix_for_resource(
                r["role_code"], r["role_name"], "app_setting", resource["code"],
            )
        matrix[r["role_id"]] = row

    return {
        "ok": True,
        "env_id": env_id,
        "apaas_app_id": apaas_app_id_clean,
        "roles": roles_out,
        "resources": {
            "page": page_resources,
            "data": data_resources,
            "process": process_resources,
            "app_setting": app_setting_resources,
        },
        "matrix": matrix,
        "is_mock": True,
        "note": "matrix 字段当前 mock — 根据 role_code 关键字推断. P2 真接 apaas list_apaas_form_permissions.",
    }


# ─── Phase H1: 单 cell 权限改动真存 ───────────────────────────────────────────
# 2026-05-26 design-v4 H1 — RoleManagePanel 矩阵 cell click 改后真写 apaas.
#
# 设计:
#   - form: 走 list_apaas_form_permissions 拿当前 rules → 改这一 role 的 rule
#           → set_apaas_form_permissions 覆盖写回 (覆盖式 API, 必须传完整 list)
#   - model / process / app_setting: P5 接入 (apaas 平台对应权限 API 复杂或没文档)
#
# permission → actions 映射:
#   'all'  → ['view','add','edit','delete','import','draft']  (5 op 全开)
#   'rw'   → ['view','edit']                                   (查改, 不删/不增)
#   'r'    → ['view']                                          (只读)
#   'none' → []                                                (全关 / 等于移除这 role rule)
#
# 覆盖式语义: rules 里没有 role_id 的会被 apaas 清掉 (整 form 范围), 所以必须
# 先读 list 再 merge 再 set, 不能只传一条 rule.


_PERMISSION_TO_ACTIONS: dict[str, list[str]] = {
    "all": ["view", "add", "edit", "delete", "import", "draft"],
    "rw": ["view", "edit"],
    "r": ["view"],
    "none": [],
}


def _form_perms_to_rules(perms_resp: dict, exclude_role_id: str = "") -> list[dict]:
    """把 list_apaas_form_permissions 返的 data_permissions + operation_permissions
    转回 set_apaas_form_permissions 入参格式的 rules list.

    同一 subject_value (role_id 或 ALL_USER) 在 data + operation 里可能各出现一次,
    合并 actions 后归为一条 rule. exclude_role_id 不空时跳过该 role (用于改前剥离).
    """
    # subject_key → rule dict
    by_subject: dict[str, dict] = {}

    def _subject_type(subj: dict) -> str:
        return str(
            subj.get("type")
            or subj.get("subject_type")
            or subj.get("permissionObjectType")
            or ""
        ).upper()

    def _subject_value(subj: dict) -> str:
        return str(
            subj.get("value")
            or subj.get("subject_value")
            or subj.get("permissionObjectValue")
            or ""
        )

    def _subject_name(subj: dict) -> str:
        return str(
            subj.get("name")
            or subj.get("subject_name")
            or subj.get("permissionObjectDisplayName")
            or ""
        )

    def _subject_range_type(subj: dict) -> str:
        perm_range = subj.get("permissionRange") if isinstance(subj.get("permissionRange"), dict) else {}
        return str(
            subj.get("range_type")
            or subj.get("rangeType")
            or perm_range.get("rangeType")
            or "ALL"
        ).upper()

    def _subject_key(subj: dict) -> str:
        st = _subject_type(subj)
        if st == "ALL_USER":
            return "ALL_USER"
        sv = _subject_value(subj)
        return f"{st}:{sv}"

    def _ensure_rule(subj: dict, perm_name: str) -> dict:
        key = _subject_key(subj)
        if key in by_subject:
            return by_subject[key]
        st = _subject_type(subj)
        # ROLE_USER (实测 apaas 返回的角色 type) 写回前面 _build_perm_payload
        # 会自动 normalize, 我们透传原值即可.
        sv = _subject_value(subj)
        sn = _subject_name(subj)
        rule = {
            "subject_type": st or "ROLE_USER",
            "subject_value": sv,
            "subject_name": sn or sv or perm_name,
            "actions": [],
            "range_type": _subject_range_type(subj),
        }
        by_subject[key] = rule
        return rule

    # data_permissions → view/edit/delete
    for g in perms_resp.get("data_permissions") or []:
        if not isinstance(g, dict):
            continue
        subj = g.get("subject") or {}
        if not isinstance(subj, dict):
            continue
        # 跳过指定 role (要被覆盖)
        st = _subject_type(subj)
        sv = _subject_value(subj)
        if exclude_role_id and st in ("ROLE_USER", "ROLE") and sv == exclude_role_id:
            continue
        rule = _ensure_rule(subj, str(g.get("permission_name") or ""))
        if g.get("can_view"): rule["actions"].append("view")
        if g.get("can_edit"): rule["actions"].append("edit")
        if g.get("can_delete"): rule["actions"].append("delete")

    # operation_permissions → add/import/draft
    for g in perms_resp.get("operation_permissions") or []:
        if not isinstance(g, dict):
            continue
        subj = g.get("subject") or {}
        if not isinstance(subj, dict):
            continue
        st = _subject_type(subj)
        sv = _subject_value(subj)
        if exclude_role_id and st in ("ROLE_USER", "ROLE") and sv == exclude_role_id:
            continue
        rule = _ensure_rule(subj, str(g.get("permission_name") or ""))
        if g.get("can_add"): rule["actions"].append("add")
        if g.get("can_import"): rule["actions"].append("import")
        if g.get("can_draft"): rule["actions"].append("draft")

    # dedupe actions per rule
    out: list[dict] = []
    for rule in by_subject.values():
        rule["actions"] = sorted(set(rule["actions"]))
        out.append(rule)
    return out


@mcp.tool()
async def set_role_resource_permission(
    env_id: int,
    apaas_app_id: str,
    role_id: str,
    resource_type: str,
    resource_id: str,
    permission: str,
) -> dict:
    """改单个 role × resource cell 权限 — design-v4 H1 PermissionMatrix 真存入口.

    按 resource_type 分发:
      - 'form': 走 list_apaas_form_permissions + set_apaas_form_permissions (覆盖式)
                改这一 form 的 advancedPermissionGroups + operationPermissionGroups 里
                该 role_id 的 rule.
      - 'model' / 'process' / 'app_setting': P5 接入 (apaas 模型/流程/应用层权限 API 复杂).

    permission ∈ {'all','rw','r','none'} 映射 actions:
      'all'  → view+add+edit+delete+import+draft  (5+ op 全开)
      'rw'   → view+edit                          (查改)
      'r'    → view                               (只读)
      'none' → []                                 (全关 / 等于移除该 role 的 rule)

    返 {ok, source, message}, ok=True 时 message="已保存",
       ok=False 时含 error_code + reason.

    使用场景: 前端矩阵 cell click → dropdown 选权限 → 调本工具持久化.
    """
    # 参数校验
    if not apaas_app_id.strip():
        return {"ok": False, "source": "set_role_resource_permission",
                "error_code": "INVALID_APAAS_APP_ID", "message": "apaas_app_id 必填"}
    if not role_id.strip():
        return {"ok": False, "source": "set_role_resource_permission",
                "error_code": "INVALID_ROLE_ID", "message": "role_id 必填"}
    if not resource_id.strip():
        return {"ok": False, "source": "set_role_resource_permission",
                "error_code": "INVALID_RESOURCE_ID", "message": "resource_id 必填"}

    rtype = (resource_type or "").strip().lower()
    if rtype not in ("form", "model", "process", "app_setting"):
        return {"ok": False, "source": "set_role_resource_permission",
                "error_code": "INVALID_RESOURCE_TYPE",
                "message": f"resource_type 必须是 form/model/process/app_setting 之一, 实际: {resource_type!r}"}

    perm = (permission or "").strip().lower()
    if perm not in _PERMISSION_TO_ACTIONS:
        return {"ok": False, "source": "set_role_resource_permission",
                "error_code": "INVALID_PERMISSION",
                "message": f"permission 必须是 all/rw/r/none 之一, 实际: {permission!r}"}

    apaas_app_id_clean = apaas_app_id.strip()
    role_id_clean = role_id.strip()
    resource_id_clean = resource_id.strip()

    # 非 form 类型 — P5 留尾.
    if rtype != "form":
        return {
            "ok": False,
            "source": "set_role_resource_permission",
            "error_code": "NOT_IMPLEMENTED",
            "resource_type": rtype,
            "message": f"{rtype} 类型权限真存 P5 接入 — apaas 模型/流程/应用层权限 API 复杂, 当前只支持 form 类型.",
        }

    # ─── form 类型分支 ──────────────────────────────────────────────────────
    # 1) 先反查 form_id 对应的 form_code (set_apaas_form_permissions 需要)
    #    resource_id 在 design-v4 矩阵里就是 menu_id (从 list_apaas_app_menus 来),
    #    需要找到对应的 form_id + form_code.
    menus_resp = await list_apaas_app_menus(env_id, apaas_app_id_clean)
    if not isinstance(menus_resp, dict) or not menus_resp.get("ok"):
        return {
            "ok": False,
            "source": "set_role_resource_permission",
            "error_code": "MENUS_LOAD_FAILED",
            "message": f"查菜单失败: {menus_resp.get('message') if isinstance(menus_resp, dict) else 'unknown'}",
        }

    form_id = ""
    form_code = ""
    for m in (menus_resp.get("menus") or []):
        if not isinstance(m, dict):
            continue
        menu_id = str(m.get("menu_id") or m.get("id") or "")
        menu_form_id = str(m.get("form_id") or m.get("formId") or "")
        # resource_id 在矩阵里通常是 menu_id；兼容直接传 form_id 的调用。
        if menu_id == resource_id_clean or (menu_form_id and menu_form_id == resource_id_clean):
            form_id = menu_form_id
            form_code = str(m.get("form_code") or m.get("formCode") or m.get("menu_code") or "")
            break

    # 部分平台菜单只返回 formId，不带 formCode。此时用表单详情里的主模型编码兜底；
    # aPaaS formPermission API 的 formCode 实测与主模型 code 对齐。
    if form_id and not form_code:
        detail_resp = await get_apaas_form_detail(env_id, apaas_app_id_clean, form_id)
        if isinstance(detail_resp, dict) and detail_resp.get("ok"):
            form_code = str(
                detail_resp.get("form_code")
                or detail_resp.get("main_model_code")
                or detail_resp.get("model_code")
                or ""
            ).strip()

    # 兼容调用方直接把 form_id 放在 resource_id，且该 form 没出现在菜单树的情况。
    if not form_id:
        detail_resp = await get_apaas_form_detail(env_id, apaas_app_id_clean, resource_id_clean)
        if isinstance(detail_resp, dict) and detail_resp.get("ok"):
            form_id = resource_id_clean
            form_code = str(
                detail_resp.get("form_code")
                or detail_resp.get("main_model_code")
                or detail_resp.get("model_code")
                or ""
            ).strip()

    if not form_id or not form_code:
        return {
            "ok": False,
            "source": "set_role_resource_permission",
            "error_code": "FORM_NOT_FOUND",
            "message": (
                f"resource_id={resource_id_clean} 未对应到可写表单 "
                f"(form_id={form_id or '缺失'}, form_code={form_code or '缺失'}). "
                "这个 cell 可能不是 form 类型菜单，或表单详情未返回主模型编码。"
            ),
        }

    # 2) 读当前 form 权限快照 (拿其他 role 的 rules, 避免覆盖式 API 把它们清掉).
    cur_perms = await list_apaas_form_permissions(env_id, apaas_app_id_clean, form_id)
    if not isinstance(cur_perms, dict) or not cur_perms.get("ok"):
        return {
            "ok": False,
            "source": "set_role_resource_permission",
            "error_code": "FORM_PERMS_LOAD_FAILED",
            "message": f"读 form 当前权限失败: {cur_perms.get('message') if isinstance(cur_perms, dict) else 'unknown'}",
        }

    # 3) 转回 rules list, 剥离本 role_id (要被新值覆盖).
    other_rules = _form_perms_to_rules(cur_perms, exclude_role_id=role_id_clean)

    # 4) 拼新 rule. perm='none' 时不加 (等同移除).
    actions = _PERMISSION_TO_ACTIONS[perm]
    new_rules = list(other_rules)
    if actions:  # 'none' 时跳过新加, 等同 remove rule
        new_rules.append({
            "subject_type": "ROLE_USER",
            "subject_value": role_id_clean,
            "subject_name": f"角色{role_id_clean[-6:]}",  # 显示名透传 — apaas 平台会自动用 role_id 反查
            "actions": actions,
            "range_type": "ALL",
        })

    # 5) set_apaas_form_permissions 覆盖写回.
    #    覆盖式 API rules 不能空 — 即使全 remove 也要传 placeholder.
    if not new_rules:
        # 全部 remove 时给个空 ALL_USER rule 让 API 接受 (相当于"全员无权限").
        new_rules = [{
            "subject_type": "ALL_USER",
            "subject_value": "",
            "subject_name": "全员",
            "actions": [],
            "range_type": "ALL",
        }]

    set_resp = await set_apaas_form_permissions(
        env_id=env_id,
        apaas_app_id=apaas_app_id_clean,
        form_id=form_id,
        form_code=form_code,
        rules=new_rules,
    )
    if not isinstance(set_resp, dict) or not set_resp.get("ok"):
        return {
            "ok": False,
            "source": "set_role_resource_permission",
            "error_code": (set_resp.get("error_code") if isinstance(set_resp, dict) else "")
                          or "FORM_PERMS_WRITE_FAILED",
            "message": f"写 form 权限失败: {set_resp.get('message') if isinstance(set_resp, dict) else 'unknown'}",
        }

    return {
        "ok": True,
        "source": "set_role_resource_permission",
        "resource_type": "form",
        "form_id": form_id,
        "form_code": form_code,
        "role_id": role_id_clean,
        "permission": perm,
        "actions": actions,
        "message": "已保存",
    }


def _invalidate_section_cache_after_write(apaas_app_id: str) -> None:
    """写类工具改完配置后失效该 app 的 section_content 缓存 (best-effort, 不抛).

    section_content 路由对读结果有 180s TTL 缓存; 写完不失效会让前端面板刷新
    在缓存窗口内拿到 stale 旧数据 (用户痛点: 字典/角色/菜单改完 3 分钟刷不出).

    覆盖面 (chokepoint 不干净, 故只给已知用户痛点工具显式调): 字典 / 角色 / 菜单
    的 create/update/delete. 别的散落写工具 (表单/流程/业务事件等) 仍靠 spec_apply
    apply 后的失效 + 前端 ?force=true 重试兜底。

    lazy import 避免 module-load 期循环 (section_content 也 lazy import mcp_server)。
    """
    aid = str(apaas_app_id or "").strip()
    if not aid:
        return
    try:
        from app.routes.applications.section_content import invalidate_section_cache_for_app
        cleared = invalidate_section_cache_for_app(aid)
        if cleared:
            logger.info("section_content cache invalidated after write: app=%s cleared=%d", aid, cleared)
    except Exception as exc:  # noqa: BLE001 — 失效失败不能拖垮写操作
        logger.debug("section_content cache invalidate skipped (%s): %s", aid, exc)






@mcp.tool()
async def delete_apaas_app_form(env_id: int, apaas_app_id: str, form_menu_id: str, form_name: str = "") -> dict:
    """删除应用表单 — 实际走"删菜单"，apaas 内部联动删表单。

    先 list_apaas_app_menus 找到 menu_id（form_id 那个菜单的 menu_id）。
    """
    if not (apaas_app_id.strip() and form_menu_id.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "apaas_app_id+form_menu_id 都必填"}
    ok, raw = await _with_client(env_id, "删表单",
        lambda c: c.delete_menu(apaas_app_id.strip(), form_menu_id.strip(), menu_name=form_name))
    if not ok:
        return raw
    return {"ok": True, "message": f"表单「{form_name}」(menu_id={form_menu_id}) 已删除",
            "next_step": "调 republish_apaas_app 让变更生效"}


# ─── 权限矩阵 CRUD ──────────────────────────────────────────────────────────
# apaas 平台只有两条权限 API：
#   读：GET /xdap-app/formConfig/query/detailPageConfigById  → 含 advanced/operation Groups
#   写：POST /common/resource/formPermission                  → 全量覆盖该 form 的权限
# 所以不存在 update_one / delete_one 单条权限，只有"列出 + 覆盖式 set"两个语义。

def _simplify_perm_object(perm_obj: dict) -> dict:
    """精简 advanced/operation Group 里 permissionObjects[0]，给 list 工具的 output。"""
    if not perm_obj:
        return {}
    return {
        "subject_type": perm_obj.get("permissionObjectType"),  # ROLE / ALL_USER / USER / DEPT
        "subject_value": perm_obj.get("permissionObjectValue"),  # role_id / "" / user_id / dept_id
        "subject_name": perm_obj.get("permissionObjectDisplayName"),
        "range_type": (perm_obj.get("permissionRange") or {}).get("rangeType"),
    }


@mcp.tool()
async def list_apaas_form_permissions(env_id: int, apaas_app_id: str, form_id: str) -> dict:
    """列出某个表单的权限矩阵（含数据权限组 + 操作权限组）。

    底层调 query_detail_page_config，返回简化后的权限视图：
      - data_permissions: 数据权限组（查看 / 编辑 / 删除），每组一个 subject
      - operation_permissions: 操作权限组（新增 / 导入 / 暂存 / 批量等），每组一个 subject

    用法：先 list_apaas_app_forms 拿 form_id，再调本工具读现状，最后调
    set_apaas_form_permissions 覆盖式写入。
    """
    if not (apaas_app_id.strip() and form_id.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "apaas_app_id+form_id 都必填"}
    async def _query(client):
        try:
            return await client.query_advanced_form_permission(apaas_app_id.strip(), form_id.strip())
        except Exception as exc:
            logger.warning(
                "query_advanced_form_permission failed, fallback detailPageConfig app_id=%s form_id=%s: %s",
                apaas_app_id.strip(), form_id.strip(), exc,
            )
            return await client.query_detail_page_config(apaas_app_id.strip(), form_id.strip())

    ok, raw = await _with_client(env_id, "查表单权限", _query)
    if not ok:
        return raw

    advanced = raw.get("advancedPermissionGroups") or []
    operation = raw.get("operationPermissionGroups") or []

    data_perms = []
    for g in advanced:
        op_type = g.get("permissionOperationType") or {}
        subj = (g.get("permissionObjects") or [{}])[0]
        data_perms.append({
            "permission_name": g.get("permissionName"),
            "subject": _simplify_perm_object(subj),
            "can_view": bool(op_type.get("queryPermission")),
            "can_edit": bool(op_type.get("updatePermission")),
            "can_delete": bool(op_type.get("deletePermission")),
        })

    op_perms = []
    for g in operation:
        op_type = g.get("permissionOperationType") or {}
        subj = (g.get("permissionObjects") or [{}])[0]
        op_perms.append({
            "permission_name": g.get("permissionName"),
            "subject": _simplify_perm_object(subj),
            "can_add": bool(op_type.get("addPermission")),
            "can_import": bool(op_type.get("importPermission")),
            "can_draft": bool(op_type.get("temporaryStoragePermission")),
            "can_copy_add": bool(op_type.get("copyAddPermission")),
            "can_batch_delete": bool(op_type.get("batchDeletePermission")),
            "can_batch_reject": bool(op_type.get("batchRejectPermission")),
            "can_batch_agree": bool(op_type.get("batchAgreePermission")),
            "can_share_form": bool(op_type.get("shareFormPermission")),
        })

    return {
        "ok": True,
        "form_id": form_id,
        "data_permissions": data_perms,
        "operation_permissions": op_perms,
        "data_count": len(data_perms),
        "operation_count": len(op_perms),
        "hint": "改权限调 set_apaas_form_permissions（覆盖式写入，传完整 rules）",
    }


@mcp.tool()
async def get_apaas_form_detail(env_id: int, apaas_app_id: str, form_id: str, include_raw: bool = False) -> dict:
    """拿表单详情页完整配置 — FormBuilder 用的真 API (跟低代码原生 data-model-fn-config 一致).

    底层调 query_detail_page_config (GET /xdap-app/formConfig/query/detailPageConfigById).
    比 list_apaas_form_components 多返:
      - models: 表单关联的所有 model + 完整字段定义 (含主表 + 子表 + 关联表)
      - components: form 已使用组件 (含默认值/宽度/行为/校验/样式等关键配置)
      - meta: form_name / model_main_code

    使用场景: FormBuilder 数据模型 tab 列 form 关联的真实 model + 已使用字段池,
    不依赖 list_apaas_app_models (会漏 borrow_apply 等 form-scoped model).
    """
    if not (apaas_app_id.strip() and form_id.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "apaas_app_id+form_id 都必填"}
    ok, raw = await _with_client(
        env_id, "查表单详情配置",
        lambda c: c.query_detail_page_config(apaas_app_id.strip(), form_id.strip()),
    )
    if not ok:
        return raw

    # modelWithFieldVoList: 关联 model 列表 (主表 + 子表 + 关联表)
    models = []
    for m in (raw.get("modelWithFieldVoList") or []):
        if not isinstance(m, dict):
            continue
        fields_out = []
        # apaas 平台 modelWithFieldVoList 里 fields 数组的 key 可能是 fields / fieldList /
        # dataModelFields / dataModelFieldList / modelFields (没固定文档).
        raw_fields = (
            m.get("fields")
            or m.get("fieldList")
            or m.get("dataModelFields")
            or m.get("dataModelFieldList")
            or m.get("modelFields")
            or m.get("modelFieldList")
            or []
        )
        for f in raw_fields:
            if not isinstance(f, dict):
                continue
            fields_out.append({
                # 2026-05-26 G1: 加 field_id (update/disable model-field endpoint 必填)
                "field_id": str(f.get("id") or f.get("fieldId") or ""),
                "field_code": str(f.get("fieldCode") or f.get("code") or ""),
                "field_name": str(f.get("fieldName") or f.get("name") or f.get("displayName") or ""),
                "data_type": str(
                    f.get("dataType") or f.get("fieldType") or f.get("databaseFieldType") or ""
                ),
                "required": bool(f.get("required") or f.get("isRequired") or False),
                "max_length": f.get("maxLength") or f.get("length"),
                "dictionary_code": str(f.get("dictionaryCode") or f.get("dictCode") or ""),
                "ref_model_code": str(f.get("refModelCode") or f.get("referenceModelCode") or ""),
                "description": str(f.get("description") or f.get("fieldDesc") or ""),
            })
        models.append({
            "model_id": str(m.get("id") or m.get("modelId") or m.get("dataModelId") or ""),
            "model_code": str(m.get("modelCode") or m.get("code") or ""),
            "model_name": str(m.get("modelName") or m.get("name") or m.get("displayName") or ""),
            "model_type": str(m.get("modelType") or ""),
            # apaas detailPageConfig 用 mainModel: bool 标记主表
            "is_main": bool(m.get("mainModel") or m.get("isMain") or m.get("main") or False),
            "fields": fields_out,
            "field_count": len(fields_out),
        })

    # detailPage.formComponents: form 已用组件
    detail_page = raw.get("detailPage") or {}
    comps = []
    for c in (detail_page.get("formComponents") or raw.get("formComponents") or []):
        if not isinstance(c, dict):
            continue
        comp_type = str(c.get("componentType") or "")
        comp_out = {
            "uuid": str(c.get("uuid") or c.get("id") or ""),
            "label": str(c.get("label") or c.get("name") or ""),
            "component_type": comp_type,
            "bo_code": str(c.get("boCode") or ""),
            "required": bool(c.get("required", False)),
        }
        comp_out.update({
            key: value for key, value in _component_snapshot(c, include_raw=include_raw).items()
            if key not in comp_out
        })
        # 选项类组件 (下拉单选/多选/单选框/复选框) 的选项透出 — 否则只读表单设计器下拉永远空,
        # 绑了字典也拉不到. apaas 组件平铺 dictionaryChooseOptions / chooseOptions ({value,label,code})
        # + chooseType (SINGLE/MULTI) + dictionaryCode. 归一成前端 FieldCard 期望的 {code,name}.
        _raw_opts = c.get("dictionaryChooseOptions") or c.get("chooseOptions") or []
        _opts_out = []
        for _o in _raw_opts:
            if isinstance(_o, dict):
                _opts_out.append({
                    "code": str(_o.get("value") or _o.get("code") or _o.get("id") or ""),
                    "name": str(_o.get("label") or _o.get("name") or _o.get("text") or _o.get("value") or ""),
                })
            elif isinstance(_o, (str, int, float)):
                _opts_out.append({"code": str(_o), "name": str(_o)})
        if _opts_out:
            comp_out["choose_options"] = _opts_out
        if c.get("chooseType"):
            comp_out["choose_type"] = str(c.get("chooseType"))
        if c.get("dictionaryCode"):
            comp_out["dictionary_code"] = str(c.get("dictionaryCode"))
        # 2026-05-28: 自开发组件 (FORM_CUSTOM_COMPONENT_*) 透出声明式 config —
        # 这些组件不是黑盒包, 行为完全由 customComponentConfig 参数化 (apiUrl /
        # welcomeText / quickButtonsText / stream 等), 给前端真渲染用.
        # 脱敏: authorization / token / secret 类字段静态预览用不到, 不泄漏到前端.
        if comp_type.startswith("FORM_CUSTOM_COMPONENT_"):
            ccc = c.get("customComponentConfig")
            if isinstance(ccc, dict):
                _SENSITIVE = ("authorization", "token", "secret", "apikey", "api_key", "password")
                safe_cfg = {
                    k: ("***" if any(s in str(k).lower() for s in _SENSITIVE) else v)
                    for k, v in ccc.items()
                }
                comp_out["custom_component_config"] = safe_cfg
        # 2026-05-31: 子表组件 (FORM_WIDGET_SON_TABLE) — 透出子表 model + 列定义,
        # 给前端 FormDesignerPanel 真渲染成网格 (而非误导性单行文本框).
        # apaas 子表用 tableModelCode 关联子 model; tableColumn[] 是已配置的列,
        # 每列含 modelField (modelCode.fieldCode) + componentType + label.
        if comp_type == "FORM_WIDGET_SON_TABLE":
            comp_out["table_model_code"] = str(c.get("tableModelCode") or "")
            cols_out = []
            for col in (c.get("tableColumn") or c.get("tableColumns") or []):
                if not isinstance(col, dict):
                    continue
                cols_out.append({
                    "uuid": str(col.get("uuid") or col.get("id") or ""),
                    "label": str(col.get("label") or col.get("name") or ""),
                    "component_type": str(col.get("componentType") or ""),
                    "model_field": str(col.get("modelField") or ""),
                    "required": bool(col.get("required", False)),
                })
            comp_out["table_column"] = cols_out
        comps.append(comp_out)

    # apaas detailPageConfigById raw 含 `modelCode` (form 绑定的主表) 直接用
    main_model_code = str(raw.get("modelCode") or raw.get("mainModelCode") or "")
    # 兜底: 从 models 里找 is_main
    if not main_model_code:
        for _mm in models:
            if _mm.get("is_main"):
                main_model_code = _mm["model_code"]
                break
    # 还没就用第一个
    if not main_model_code and models:
        main_model_code = models[0]["model_code"]

    # 2026-05-27 T → T3: 通过 iframe 抓包 + Python 直调验证, 列表设计真 API:
    #   POST /xdap-app/formConfig/query/listPageConfigById, body {formId, appId}
    # 返 data.listPageViews[] (一个 view 一个 tab), 每 view 含:
    #   - queryConditions[]: 查询条件 ({uuid, boCode, label, componentType, filterType})
    #   - queryLists[]: 列字段 ({uuid, label, componentType, displayFlag, ...})
    # 默认抽第一个 view (主 view).
    list_page_view = {"query_conditions": [], "query_list": []}
    try:
        list_cfg_ok, list_cfg_raw = await _with_client(
            env_id, "查列表设计配置 (listPageConfigById)",
            lambda c: c.query_list_page_config(apaas_app_id.strip(), form_id.strip()),
        )
        if list_cfg_ok and isinstance(list_cfg_raw, dict):
            views = list_cfg_raw.get("listPageViews") or []
            if views and isinstance(views[0], dict):
                lpv = views[0]
                list_page_view = {
                    "query_conditions": lpv.get("queryConditions") or [],
                    "query_list": lpv.get("queryLists") or [],
                }
    except Exception as exc:
        logger.warning(f"query_list_page_config 失败 form_id={form_id}: {exc}")
    return {
        "ok": True,
        "form_id": form_id,
        "form_name": str(raw.get("formName") or detail_page.get("formName") or ""),
        "main_model_code": main_model_code,
        "all_model_codes": raw.get("allModelCodes") or [],
        "models": models,
        "components": comps,
        "model_count": len(models),
        "component_count": len(comps),
        "list_page_view": list_page_view,
    }


@mcp.tool()
async def repair_empty_apaas_form_from_model(
    env_id: int,
    apaas_app_id: str,
    form_id: str,
    model_code: str = "",
    dry_run: bool = False,
) -> dict:
    """修复已创建但组件为空的表单。

    使用场景：平台表单设计器左侧/画布显示空白，但表单已经绑定了数据模型。
    工具只在当前表单组件数为 0 时生效；已有组件的表单会跳过，避免覆盖用户手工设计。
    """
    if not (apaas_app_id.strip() and form_id.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "apaas_app_id+form_id 都必填"}

    async def _repair(client):
        detail = await client.query_detail_page_config(apaas_app_id.strip(), form_id.strip())
        detail_page = detail.get("detailPage") or {}
        detail_components = detail_page.get("formComponents") or detail.get("formComponents") or []
        if detail_components:
            return {
                "ok": True,
                "skipped": True,
                "reason": "FORM_ALREADY_HAS_COMPONENTS",
                "form_id": form_id,
                "component_count": len(detail_components),
                "message": f"表单已有 {len(detail_components)} 个组件，未覆盖。",
            }

        main_code = str(model_code or detail.get("modelCode") or detail.get("mainModelCode") or "").strip()
        models = _extract_detail_models(detail)
        main_model = _pick_main_model(models, main_code)
        if not main_model:
            return {
                "ok": False,
                "error_code": "NO_BOUND_MODEL",
                "form_id": form_id,
                "message": "表单详情里没有关联模型，无法从模型字段补表单组件。",
            }

        main_code = str(main_model.get("model_code") or main_code).strip()
        fields = [
            field for field in (main_model.get("fields") or [])
            if str(field.get("field_code") or "").strip()
        ]
        if not fields:
            model_id = str(main_model.get("model_id") or "").strip()
            if model_id:
                raw_fields = await client.query_model_fields(apaas_app_id.strip(), model_id)
                fields = [{
                    "field_id": str(f.get("id") or f.get("fieldId") or ""),
                    "field_code": str(f.get("fieldCode") or f.get("code") or ""),
                    "field_name": str(f.get("fieldName") or f.get("name") or f.get("displayName") or ""),
                    "data_type": str(f.get("dataType") or f.get("fieldType") or f.get("databaseFieldType") or ""),
                    "required": bool(f.get("required") or f.get("isRequired") or False),
                    "max_length": f.get("maxLength") or f.get("length"),
                    "dictionary_code": str(f.get("dictionaryCode") or f.get("dictCode") or ""),
                } for f in raw_fields if isinstance(f, dict) and str(f.get("fieldCode") or f.get("code") or "").strip()]
        if not fields:
            return {
                "ok": False,
                "error_code": "NO_MODEL_FIELDS",
                "form_id": form_id,
                "model_code": main_code,
                "message": f"模型 {main_code} 没有可用字段，无法补表单组件。",
            }

        new_components = [
            _build_basic_component_from_model_field(field, main_code)
            for field in fields
        ]
        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "form_id": form_id,
                "model_code": main_code,
                "generated_component_count": len(new_components),
                "components": new_components,
                "message": f"将从模型 {main_code} 生成 {len(new_components)} 个表单组件。",
            }

        form_config = await client.query_form_config(apaas_app_id.strip(), form_id.strip())
        simple_components = (form_config.get("detailPage") or {}).get("formComponents") or []
        if simple_components:
            return {
                "ok": True,
                "skipped": True,
                "reason": "FORM_ALREADY_HAS_COMPONENTS",
                "form_id": form_id,
                "component_count": len(simple_components),
                "message": f"表单已有 {len(simple_components)} 个组件，未覆盖。",
            }
        form_config.setdefault("detailPage", {})["formComponents"] = new_components
        if main_code:
            form_config["modelCode"] = form_config.get("modelCode") or main_code
            all_model_codes = form_config.get("allModelCodes")
            if not isinstance(all_model_codes, list) or main_code not in all_model_codes:
                form_config["allModelCodes"] = [main_code]

        await client.save_form_config(apaas_app_id.strip(), form_config)
        return {
            "ok": True,
            "form_id": form_id,
            "model_code": main_code,
            "created_component_count": len(new_components),
            "field_count": len(fields),
            "message": f"已从模型 {main_code} 补回 {len(new_components)} 个表单组件，请刷新表单设计器。",
        }

    ok, raw = await _with_client(env_id, "修复空表单组件", _repair)
    return raw if ok else raw


def _build_perm_payload_from_simple_rules(
    app_id: str,
    form_code: str,
    form_id: str,
    rules: list,
) -> dict:
    """把 LLM 友好的 rules 数组转成 formPermission API 的标准 payload。

    rules item 示例：
        {
          "subject_type": "ROLE" | "ALL_USER",
          "subject_value": "<role_id>",     # ROLE 时必填；ALL_USER 时忽略
          "subject_name": "管理员",          # 仅用于 permissionName 显示
          "actions": ["view","add","edit","delete","import","draft"],
          "range_type": "ALL"               # 可选，默认 ALL；其他：SELF/DEPT/SUB_DEPT
        }
    """
    data_groups = []
    operation_groups = []

    for rule in rules:
        # aPaaS 权限接口读写不对称：
        # - detailPageConfig 读回的角色主体是 ROLE_USER
        # - formPermission 写入接口稳定接受的是 ROLE
        # 所以入参兼容 ROLE_USER，但最终 payload 必须写 ROLE，否则平台会 500。
        subj_type = str(rule.get("subject_type") or "").strip().upper()
        if subj_type in ("ROLE", "ROLE_USER"):
            subj_type = "ROLE"
        elif subj_type not in ("ALL_USER", "USER", "DEPT"):
            subj_type = "ROLE"

        if subj_type == "ALL_USER":
            subj_value = ""  # 平台规定：ALL_USER 时 permissionObjectValue 必须空串
            subj_name = rule.get("subject_name") or "全部人员"
        else:
            subj_value = str(rule.get("subject_value") or "").strip()
            subj_name = rule.get("subject_name") or subj_value

        actions = [a.strip().lower() for a in (rule.get("actions") or []) if a]
        all_ = "all" in actions
        can_view = all_ or "view" in actions
        can_add = all_ or "add" in actions
        can_edit = all_ or "edit" in actions or "update" in actions
        can_delete = all_ or "delete" in actions
        can_import = all_ or "import" in actions
        can_draft = all_ or "draft" in actions or "temporary" in actions

        range_type = str(rule.get("range_type") or "ALL").strip().upper()

        data_groups.append({
            "permissionName": f"{subj_name}权限",
            "permissionDescribe": "",
            "permissionOperationType": {
                "queryPermission": can_view,
                "updatePermission": can_edit,
                "deletePermission": can_delete,
            },
            "permissionObjects": [{
                "permissionObjectType": subj_type,
                "permissionObjectValue": subj_value,
                "permissionObjectDisplayName": subj_name,
                "permissionRange": {"rangeType": range_type},
            }],
        })

        if any((can_add, can_import, can_draft)):
            operation_groups.append({
                "permissionName": f"{subj_name}操作权限",
                "permissionDescribe": "",
                "permissionOperationType": {
                    "temporaryStoragePermission": can_draft,
                    "addPermission": can_add,
                    "importPermission": can_import,
                    "copyAddPermission": False,
                    "batchDeletePermission": False,
                    "batchRejectPermission": False,
                    "batchAgreePermission": False,
                    "shareFormPermission": False,
                },
                "permissionObjects": [{
                    "permissionObjectType": subj_type,
                    "permissionObjectValue": subj_value,
                    "permissionObjectDisplayName": subj_name,
                    "permissionRange": {"rangeType": range_type},
                }],
            })

    return {
        "formCode": form_code,
        "appId": app_id,
        "tenantId": "",
        "formId": form_id,
        "operationPermissionGroups": operation_groups,
        "dataPermissionGroups": data_groups,
    }


@mcp.tool()
async def set_apaas_form_permissions(
    env_id: int,
    apaas_app_id: str,
    form_id: str,
    form_code: str,
    rules: list,
) -> dict:
    """覆盖式设置某个表单的权限矩阵（一次调用替换该表单的所有权限）。

    ⚠️ 覆盖式 — apaas 平台 formPermission API 是按 form_id 全量替换的：
      - rules 里没列的 subject（角色 / ALL_USER），权限会被清空
      - 想增量改：先 list_apaas_form_permissions 读现状，合并后再 set

    rules 数组示例：
        [
          {
            "subject_type": "ROLE_USER",
            "subject_value": "<role_id>",
            "subject_name": "管理员",
            "actions": ["view","add","edit","delete","import","draft"],
            "range_type": "ALL"
          },
          {
            "subject_type": "ALL_USER",
            "actions": ["view"],
            "range_type": "SELF"
          }
        ]

    subject_type 取值（apaas 平台实测）：
      - "ROLE_USER" — 角色（"ROLE" 也接受，会 alias 成 "ROLE_USER"）
      - "ALL_USER"  — 全部人员（subject_value 留空）
      - "USER"      — 具体用户
      - "DEPT"      — 具体部门

    actions 取值：view / add / edit / delete / import / draft，或者 ["all"] 表示全开

    range_type 常见取值（透传给 apaas，不做白名单限制）：
      - "ALL"                         — 全部数据
      - "SELF"                        — 本人
      - "CURRENT_USER_DEPT"           — 本部门
      - "CURRENT_USER_DEPT_LOW_LEVEL" — 本部门及下级
      - 其他高级取值参考 apaas 平台文档

    role_id 怎么拿：先调 list_apaas_app_roles 拿 role.id 字段。
    """
    if not (apaas_app_id.strip() and form_id.strip() and form_code.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS",
                "message": "apaas_app_id+form_id+form_code 都必填（form_code 从 list_apaas_app_forms 拿）"}
    if not isinstance(rules, list) or not rules:
        return {"ok": False, "error_code": "INVALID_RULES",
                "message": "rules 必须是非空数组；想清空所有权限请显式传 [{subject_type:'ALL_USER',actions:[]}]"}

    payload = _build_perm_payload_from_simple_rules(
        app_id=apaas_app_id.strip(),
        form_code=form_code.strip(),
        form_id=form_id.strip(),
        rules=rules,
    )
    async def _save(client):
        return await client.create_form_permissions(apaas_app_id.strip(), [payload])

    ok, raw = await _with_client(env_id, "设表单权限", _save)
    if not ok:
        return raw
    return {
        "ok": True,
        "form_id": form_id,
        "data_groups_count": len(payload["dataPermissionGroups"]),
        "operation_groups_count": len(payload["operationPermissionGroups"]),
        "message": "表单权限已覆盖写入（apaas 平台运行时立即生效，不需要 republish）",
    }


# ─── 应用访问授权 ──────────────────────────────────────────────────────────
# 应用层"谁能看到这个应用"的开关，跟表单 / 数据权限独立：
#   ALL  — 开放给租户内全员（最常用，部署完不开就所有人看不见）
#   ROLE — 只给指定角色（object_ids = role_id 列表）
#   USER — 只给指定用户（object_ids = user_id 列表）
#   DEPT — 只给指定部门（object_ids = dept_id 列表）
# 平台没有 query 接口，只能 set；一次只能一种 type（混合得调多次）。

@mcp.tool()
async def set_apaas_app_access(
    env_id: int,
    apaas_app_id: str,
    object_type: str = "ALL",
    object_ids: list = None,
) -> dict:
    """设置应用访问授权（控制"谁能进这个应用"，覆盖式）。

    ⚠️ 应用部署完默认**不开放访问**，所有人都看不见 — 必须显式调一次本工具。

    object_type:
      - "ALL"  — 开放给租户内全部用户（推荐；object_ids 留空 / 留 []）
      - "ROLE" — 只给指定角色（object_ids = list_apaas_app_roles 拿到的 role.id 列表）
      - "USER" — 只给指定用户（object_ids = user_id 列表）
      - "DEPT" — 只给指定部门（object_ids = dept_id 列表）

    覆盖式：本调用替换该应用之前的所有访问授权。

    平台限制：一次调用只能传一种 object_type；想混合（如管理员 ROLE + 几个具体 USER）
    得分两次调用，但实际上 apaas 后调会覆盖先调 — 这种场景没法实现，建议用 ROLE。
    """
    if not apaas_app_id.strip():
        return {"ok": False, "error_code": "INVALID_PARAMS", "message": "apaas_app_id 必填"}

    obj_type = (object_type or "ALL").strip().upper()
    if obj_type not in ("ALL", "ROLE", "USER", "DEPT"):
        return {
            "ok": False, "error_code": "INVALID_OBJECT_TYPE",
            "message": f"object_type 必须是 ALL/ROLE/USER/DEPT 之一，收到 {object_type}",
        }

    ids = [str(x).strip() for x in (object_ids or []) if str(x).strip()]
    if obj_type != "ALL" and not ids:
        return {
            "ok": False, "error_code": "MISSING_OBJECT_IDS",
            "message": f"object_type={obj_type} 时 object_ids 必填，至少传 1 个 id",
        }

    ok, raw = await _with_client(env_id, "设应用访问授权",
        lambda c: c.save_app_access(apaas_app_id.strip(), obj_type, ids))
    if not ok:
        return raw
    return {
        "ok": True,
        "apaas_app_id": apaas_app_id,
        "object_type": obj_type,
        "object_ids_count": len(ids),
        "message": f"应用访问授权已设为 {obj_type}"
                   + (f"（{len(ids)} 个对象）" if ids else "（全员可见）"),
    }


# ─── 表单单组件 update 已拆到 app.mcp_tools.form_components ─────────────────────

def _extract_detail_models(raw: dict) -> list[dict]:
    models = []
    for m in (raw.get("modelWithFieldVoList") or []):
        if not isinstance(m, dict):
            continue
        raw_fields = (
            m.get("fields")
            or m.get("fieldList")
            or m.get("dataModelFields")
            or m.get("dataModelFieldList")
            or m.get("modelFields")
            or m.get("modelFieldList")
            or []
        )
        fields_out = []
        for f in raw_fields:
            if not isinstance(f, dict):
                continue
            fields_out.append({
                "field_id": str(f.get("id") or f.get("fieldId") or ""),
                "field_code": str(f.get("fieldCode") or f.get("code") or ""),
                "field_name": str(f.get("fieldName") or f.get("name") or f.get("displayName") or ""),
                "data_type": str(f.get("dataType") or f.get("fieldType") or f.get("databaseFieldType") or ""),
                "required": bool(f.get("required") or f.get("isRequired") or False),
                "max_length": f.get("maxLength") or f.get("length"),
                "dictionary_code": str(f.get("dictionaryCode") or f.get("dictCode") or ""),
                "ref_model_code": str(f.get("refModelCode") or f.get("referenceModelCode") or ""),
                "description": str(f.get("description") or f.get("fieldDesc") or ""),
            })
        models.append({
            "model_id": str(m.get("id") or m.get("modelId") or m.get("dataModelId") or ""),
            "model_code": str(m.get("modelCode") or m.get("code") or ""),
            "model_name": str(m.get("modelName") or m.get("name") or m.get("displayName") or ""),
            "model_type": str(m.get("modelType") or ""),
            "is_main": bool(m.get("mainModel") or m.get("isMain") or m.get("main") or False),
            "fields": fields_out,
            "field_count": len(fields_out),
        })
    return models


def _component_type_from_model_field(field: dict) -> str:
    dict_code = str(field.get("dictionary_code") or field.get("dictionaryCode") or "").strip()
    if dict_code:
        return "FORM_SELECT_INPUT_SINGLE"

    data_type = str(field.get("data_type") or field.get("fieldType") or "").strip().upper()
    if data_type in {"BIG_TEXT", "TEXT", "LONGTEXT", "CLOB"}:
        return "FORM_TEXTAREA_INPUT"
    if data_type in {"NUM", "NUMBER", "DECIMAL", "DOUBLE", "FLOAT", "INT", "INTEGER", "BIGINT"}:
        return "FORM_NUMBER_INPUT"
    if data_type in {"DATE", "DATETIME", "TIMESTAMP"}:
        return "FORM_DATEPICK_INPUT"
    return "FORM_TEXT_INPUT"


def _build_basic_component_from_model_field(field: dict, model_code: str) -> dict:
    field_code = str(field.get("field_code") or field.get("fieldCode") or "").strip()
    field_name = str(field.get("field_name") or field.get("fieldName") or field_code).strip()
    comp_type = _component_type_from_model_field(field)
    component = {
        "componentType": comp_type,
        "label": field_name,
        "modelField": f"{model_code}.{field_code}",
        "required": bool(field.get("required", False)),
        "hidden": False,
        "readOnly": False,
        "showInList": True,
        "searchable": False,
    }
    max_length = field.get("max_length") or field.get("maxLength")
    if comp_type == "FORM_TEXT_INPUT" and max_length:
        component["lengthLimit"] = max_length
    dict_code = str(field.get("dictionary_code") or field.get("dictionaryCode") or "").strip()
    if dict_code and comp_type == "FORM_SELECT_INPUT_SINGLE":
        component["chooseType"] = "SINGLE"
        component["dictionarySelectConfig"] = {
            "dictionaryCode": dict_code,
            "dictionarySelectOptions": [],
        }
    return component


def _pick_main_model(models: list[dict], preferred_model_code: str = "") -> dict | None:
    preferred_model_code = str(preferred_model_code or "").strip()
    if preferred_model_code:
        for model in models:
            if str(model.get("model_code") or "").strip() == preferred_model_code:
                return model
    for model in models:
        if model.get("is_main"):
            return model
    return models[0] if models else None


def _is_dup_field_error(exc: Exception) -> bool:
    """字段已存在类业务错误 — 用于合并工具容忍 re-run / 「字段已在模型」场景。

    token 错误(401/登录失效)不含这些 marker → 不会被误判为 dup → 由调用方先行 raise 走 relogin。
    """
    raw = str(exc)
    if any(m in raw for m in ("已存在", "重复", "已被使用")):
        return True
    low = raw.lower()
    return "duplicate" in low or "already exist" in low


async def _add_field_to_form_core(
    client,
    *,
    apaas_app_id: str,
    model_id: str,
    model_code: str,
    field_code: str,
    field_name: str,
    field_type: str = "STRING",
    max_length: int = 255,
    comment: str = "",
    form_id: str = "",
    show_in_list: bool = False,
) -> dict:
    """给模型加字段(若不存在)并把字段铺到表单详情页(可选上列表页)。

    接收 client 作首参 → 可直接喂 fake client 单测(镜像 repair_form_menu_names 范式)。
    token 错误一律 raise 交上层 call_apaas_with_relogin 重试;整段操作幂等可重跑。
    """
    from app.error_messages import is_apaas_token_error

    # ── 入参 + 保留字校验(不碰 client)──
    if not (apaas_app_id.strip() and model_id.strip() and model_code.strip()
            and field_code.strip() and field_name.strip() and form_id.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS",
                "message": "apaas_app_id/model_id/model_code/field_code/field_name/form_id 都必填"}
    fc = field_code.strip().lower()
    if fc in {"approver_id", "id", "tenant_id"} or fc.startswith("approval_"):
        return {"ok": False, "error_code": "RESERVED_FIELD_CODE",
                "message": f"field_code '{field_code}' 命中 apaas 保留字 — 建议改成 {model_code}_{field_code}"}

    aid = apaas_app_id.strip()
    mcode = model_code.strip()
    fcode = field_code.strip()
    target = f"{mcode}.{fcode}"

    # ── 1. 加模型字段(容忍已存在;token 错 / 真失败照常处理)──
    try:
        await client.add_model_field(aid, model_id.strip(), mcode, fcode, field_name.strip(),
                                     field_type=field_type, max_length=max_length, comment=comment)
    except Exception as exc:
        if is_apaas_token_error(str(exc)):
            raise
        if not _is_dup_field_error(exc):
            return {"ok": False, "error_code": "ADD_FIELD_FAILED",
                    "message": f"给模型 {mcode} 加字段「{field_name}」失败：{exc}"}
        logger.info("add_apaas_field_to_form: 字段 %s 已在模型上, 跳过建字段直接铺表单", target)

    # ── 2. 构造组件(类型自动推导, 复用现成构造器)──
    field = {
        "field_code": fcode,
        "field_name": field_name.strip(),
        "data_type": field_type,
        "max_length": max_length,
        "dictionary_code": "",
        "required": False,
    }
    component = _build_basic_component_from_model_field(field, mcode)

    def _apply_append(cfg: dict) -> None:
        detail = cfg.setdefault("detailPage", {})
        comps = detail.setdefault("formComponents", [])
        if not any(isinstance(c, dict) and str(c.get("modelField") or "") == target for c in comps):
            comps.append(component)
        amc = cfg.get("allModelCodes")
        if not isinstance(amc, list):
            amc = []
            cfg["allModelCodes"] = amc
        if mcode not in amc:
            amc.append(mcode)
        if show_in_list:
            ql = detail.setdefault("listPageView", {}).setdefault("queryList", [])
            if target not in ql:
                ql.append(target)

    # ── 3. 读表单 → 幂等短路 → 追加 → 存回(乐观锁重试)──
    form_config = await client.query_form_config(aid, form_id.strip())
    existing = (form_config.get("detailPage") or {}).get("formComponents") or []
    if any(isinstance(c, dict) and str(c.get("modelField") or "") == target for c in existing):
        return {"ok": True, "skipped": True, "reason": "FIELD_ALREADY_ON_FORM",
                "form_id": form_id, "model_field": target,
                "message": f"字段「{field_name}」已在表单上, 未重复添加。"}

    _apply_append(form_config)

    from app.operations.form_config import _save_form_config_with_retry
    try:
        await _save_form_config_with_retry(client, aid, form_config,
                                           form_id=form_id.strip(), apply_latest=_apply_append,
                                           reason="对话加字段铺表单")
    except Exception as exc:
        if is_apaas_token_error(str(exc)):
            raise
        return {"ok": False, "error_code": "FORM_SAVE_FAILED",
                "message": f"字段「{field_name}」已加到模型 {mcode}, 但铺到表单失败：{exc}",
                "field_on_model": True, "field_on_form": False}

    return {"ok": True, "form_id": form_id, "model_code": mcode, "field_code": fcode,
            "model_field": target, "component_type": component["componentType"],
            "show_in_list": show_in_list,
            "message": f"字段「{field_name}」({fcode}) 已加到模型「{mcode}」并铺到表单。",
            "next_step": "调 republish_apaas_app 让模型变更生效; 刷新表单设计器查看新字段。"}


@mcp.tool()
async def add_apaas_field_to_form(
    env_id: int, apaas_app_id: str, model_id: str, model_code: str,
    field_code: str, field_name: str,
    field_type: str = "STRING", max_length: int = 255, comment: str = "",
    form_id: str = "", show_in_list: bool = False,
) -> dict:
    """给模型加一个字段并直接铺到表单(详情页, 可选上列表页) — 一步到位。

    解决「对话加字段只建了模型、没出现在表单上」: 本工具内部先给模型加字段
    (若已存在则跳过建字段), 再把该字段作为组件追加到指定表单的详情页。
    show_in_list=True 时字段也加进列表页的列(queryList)。

    field_type 常用: STRING / NUM / DATE / DATETIME / BOOLEAN / TEXT / BIG_TEXT。
    form_id 先 list_apaas_app_menus(menu_type_filter=MODEL) 拿。
    下拉字段建完后再调 bind_apaas_form_field_to_dict 绑字典。
    """
    ok, raw = await _with_client(
        env_id, "加字段并铺到表单",
        lambda c: _add_field_to_form_core(
            c, apaas_app_id=apaas_app_id, model_id=model_id, model_code=model_code,
            field_code=field_code, field_name=field_name, field_type=field_type,
            max_length=max_length, comment=comment, form_id=form_id, show_in_list=show_in_list))
    if not ok:
        return raw
    if isinstance(raw, dict) and raw.get("ok"):
        _invalidate_section_cache_after_write(apaas_app_id)
    return raw


def register(
    mcp,
    with_client,
    list_app_menus,
    list_app_models,
    list_app_roles=None,
    get_form_detail=None,
    list_form_permissions=None,
    set_form_permissions=None,
):
    global _with_client, list_apaas_app_menus, list_apaas_app_models
    global list_apaas_app_roles, get_apaas_form_detail
    global list_apaas_form_permissions, set_apaas_form_permissions
    tools = [
        list_apaas_app_roles,
        get_role_resource_matrix,
        set_role_resource_permission,
        delete_apaas_app_form,
        list_apaas_form_permissions,
        get_apaas_form_detail,
        repair_empty_apaas_form_from_model,
        set_apaas_form_permissions,
        set_apaas_app_access,
        add_apaas_field_to_form,
    ]
    _with_client = with_client
    list_apaas_app_menus = list_app_menus
    list_apaas_app_models = list_app_models
    if list_app_roles is not None:
        list_apaas_app_roles = list_app_roles
    if get_form_detail is not None:
        get_apaas_form_detail = get_form_detail
    if list_form_permissions is not None:
        list_apaas_form_permissions = list_form_permissions
    if set_form_permissions is not None:
        set_apaas_form_permissions = set_form_permissions
    for tool in tools:
        mcp.tool()(tool)
    return {tool.__name__: tool for tool in tools}
