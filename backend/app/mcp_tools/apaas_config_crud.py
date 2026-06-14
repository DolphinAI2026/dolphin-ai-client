"""Direct aPaaS configuration CRUD MCP tools."""

from __future__ import annotations

from typing import Callable

from app.mcp_envelope import ErrorCode, _err, _ok, apaas_tool


_registered_tools_by_mcp: dict[int, dict[str, object]] = {}


def register(
    mcp,
    with_client: Callable,
    invalidate_section_cache_after_write: Callable[[str], None],
) -> dict[str, object]:
    """Register direct aPaaS config write tools on the shared FastMCP instance."""
    marker = id(mcp)
    if marker in _registered_tools_by_mcp:
        return _registered_tools_by_mcp[marker]

    _with_client = with_client
    _invalidate_section_cache_after_write = invalidate_section_cache_after_write

    @mcp.tool()
    async def create_apaas_app_roles(env_id: int, apaas_app_id: str, roles: list) -> dict:
        """批量创建 aPaaS 应用角色（不走 SPEC 文档流程，直接调 apaas 平台）。

        入参 roles 数组每项至少含 {role_code: str, role_name: str}，可选：
          use_scope (str)         角色作用域，默认应用名
          internal_resource (bool) 是否系统资源，默认 true
          enable_group_param (str) DISABLE / ENABLE，默认 DISABLE
          role_params (list)       角色参数定义（高级，一般留空）

        示例：roles=[{"role_code":"reviewer","role_name":"审批人"},
                    {"role_code":"admin","role_name":"管理员"}]

        跟"走 SPEC 文档 update_app_from_doc + execute_change_plan"的区别：
          - 这个：直接对话场景"加 X 角色"，一步建好
          - SPEC 流程：用户给完整新版 md，自动 diff 出所有变更（适合大改）

        创建后调 publish_application 或 republish_apaas_app 让用户能看到。
        """
        if not apaas_app_id.strip():
            return {"ok": False, "error_code": "INVALID_APAAS_APP_ID", "message": "apaas_app_id 必填"}
        if not roles or not isinstance(roles, list):
            return {"ok": False, "error_code": "INVALID_ROLES", "message": "roles 必须是非空数组"}
        # 规整 payload 到 apaas 平台需要的字段（驼峰）
        # 2026-05-24 修 silent-fail bug: 每项 role 必须含 appId 字段,
        # 跟 step_executor.py:236 (generator_v2 真成功路径) 一致.
        # 之前漏 appId 导致 apaas 平台返 200 ok 但角色不创建 (实测 ops_admin 案例).
        apaas_app_id_clean = apaas_app_id.strip()
        payload_roles = []
        for r in roles:
            if not isinstance(r, dict):
                continue
            code = (r.get("role_code") or r.get("roleCode") or "").strip()
            name = (r.get("role_name") or r.get("roleName") or "").strip()
            if not code or not name:
                return {"ok": False, "error_code": "INVALID_ROLE_ITEM",
                        "message": f"每个 role 必须有 role_code + role_name；问题项：{r}"}
            payload_roles.append({
                "appId": apaas_app_id_clean,    # ← 必填, 漏了 apaas silent fail
                "roleCode": code,
                "roleName": name,
                "useScope": r.get("use_scope") or r.get("useScope") or "",
                "internalResource": bool(r.get("internal_resource", r.get("internalResource", True))),
                "enableGroupParam": r.get("enable_group_param") or r.get("enableGroupParam") or "DISABLE",
                "roleParams": r.get("role_params") or r.get("roleParams") or [],
            })

        ok, raw = await _with_client(
            env_id, "批量建角色",
            lambda c: c.create_roles(apaas_app_id.strip(), payload_roles),
        )
        if not ok:
            return raw
        _invalidate_section_cache_after_write(apaas_app_id)
        return {
            "ok": True, "env_id": env_id, "apaas_app_id": apaas_app_id.strip(),
            "created_count": len(payload_roles),
            "roles_summary": [{"role_code": r["roleCode"], "role_name": r["roleName"]} for r in payload_roles],
            "next_step": "调 publish_application(app_id) 或 republish_apaas_app(env_id, apaas_app_id) 让角色生效",
        }


    @mcp.tool()
    async def update_apaas_app_role(
        env_id: int, apaas_app_id: str, role_id: str,
        role_code: str = "", role_name: str = "",
        app_name: str = "", enable_group_param: str = "DISABLE",
        role_params: list | None = None,
    ) -> dict:
        """更新单个 aPaaS 角色（不走 SPEC，直接对话改）。

        先调 list_apaas_app_roles 拿到 role_id，再调本工具改 role_code / role_name 等。
        role_code / role_name 留空时不强制改但 apaas 要求每次 edit 都传全字段 — 留空会拿现值不便。
        建议：先 list 找到要改的角色 → 把 role_code/role_name/role_id 一起传入。
        """
        if not (apaas_app_id.strip() and role_id.strip()):
            return {"ok": False, "error_code": "INVALID_PARAMS",
                    "message": "apaas_app_id + role_id 必填"}
        if not (role_code.strip() and role_name.strip()):
            return {"ok": False, "error_code": "INVALID_PARAMS",
                    "message": "role_code + role_name 必填（apaas edit 接口要求全字段）— 先 list 拿现值"}

        ok, raw = await _with_client(
            env_id, "更新角色",
            lambda c: c.update_role(
                apaas_app_id.strip(), role_id.strip(),
                role_code.strip(), role_name.strip(),
                app_name=app_name,
                enable_group_param=enable_group_param,
                role_params=role_params or [],
            ),
        )
        if not ok:
            return raw
        _invalidate_section_cache_after_write(apaas_app_id)
        return {
            "ok": True, "env_id": env_id, "apaas_app_id": apaas_app_id.strip(),
            "role_id": role_id.strip(), "role_code": role_code, "role_name": role_name,
            "message": f"角色「{role_name}」({role_code}) 已更新",
            "next_step": "调 republish_apaas_app 让变更生效",
        }


    @mcp.tool()
    async def delete_apaas_app_role(env_id: int, apaas_app_id: str, role_id: str) -> dict:
        """删除单个 aPaaS 角色（不走 SPEC 直接删）。

        ⚠️ 慎用：删除前用 list_apaas_app_roles 确认 role_id 对的；删除后已绑该角色的成员
        在 apaas 平台上的访问会受影响。
        """
        if not (apaas_app_id.strip() and role_id.strip()):
            return {"ok": False, "error_code": "INVALID_PARAMS",
                    "message": "apaas_app_id + role_id 必填"}
        ok, raw = await _with_client(
            env_id, "删除角色",
            lambda c: c.delete_role(apaas_app_id.strip(), role_id.strip()),
        )
        if not ok:
            return raw
        _invalidate_section_cache_after_write(apaas_app_id)
        return {
            "ok": True, "env_id": env_id, "apaas_app_id": apaas_app_id.strip(),
            "role_id": role_id.strip(),
            "message": f"角色 role_id={role_id} 已删除",
            "next_step": "调 republish_apaas_app 让变更生效",
        }


    # ───── 字典 CRUD（精细操作） ─────

    @mcp.tool()
    @apaas_tool(required=["apaas_app_id", "dict_code", "dict_name"],
                message="apaas_app_id + dict_code + dict_name 都必填")
    async def create_apaas_app_dict(env_id: int, apaas_app_id: str, dict_code: str, dict_name: str, describe: str = "") -> dict:
        """新建一个字典到 aPaaS 应用（不走 SPEC 文档流，直接对话场景）。

        后续添加选项用 add_apaas_dict_option（先调本工具拿 dict_id）。
        """
        # 2026-05-24 同 create_apaas_app_roles fix: 每项必须含 appId, 漏了 apaas silent ignore
        apaas_app_id_clean = apaas_app_id.strip()
        payload = [{
            "appId": apaas_app_id_clean,
            "dictionaryCode": dict_code.strip(),
            "dictionaryName": dict_name.strip(),
            "dictionaryDescribe": describe or "",
            "dictionaryStatus": "ENABLE",
            "dictionaryMulticolorStatus": "ENABLE",
            "internalResource": True,
        }]
        ok, raw = await _with_client(env_id, "建字典", lambda c: c.create_dicts(apaas_app_id_clean, payload))
        if not ok:
            return raw
        _invalidate_section_cache_after_write(apaas_app_id)
        return _ok(env_id=env_id, apaas_app_id=apaas_app_id.strip(),
                   dict_code=dict_code.strip(), dict_name=dict_name.strip(),
                   next_step="用 list_apaas_app_dicts 拿回 dict_id 再调 add_apaas_dict_option 加选项")


    @mcp.tool()
    @apaas_tool(required=["apaas_app_id", "dict_id", "dict_code", "dict_name"],
                message="apaas_app_id+dict_id+dict_code+dict_name 都必填")
    async def update_apaas_app_dict(env_id: int, apaas_app_id: str, dict_id: str, dict_code: str, dict_name: str, describe: str = "") -> dict:
        """更新字典基本信息（不改选项，选项走 update_apaas_dict_option）。

        先 list_apaas_app_dicts 拿 dict_id；dict_code/dict_name 必填（apaas edit 接口要全字段）。
        """
        ok, raw = await _with_client(env_id, "改字典",
            lambda c: c.update_dict(apaas_app_id.strip(), dict_id.strip(), dict_code.strip(), dict_name.strip(), describe=describe))
        if not ok:
            return raw
        _invalidate_section_cache_after_write(apaas_app_id)
        return _ok(env_id=env_id, apaas_app_id=apaas_app_id.strip(),
                   dict_id=dict_id.strip(), message=f"字典「{dict_name}」({dict_code}) 已更新",
                   next_step="调 republish_apaas_app 让变更生效")


    @mcp.tool()
    @apaas_tool(required=["apaas_app_id", "dict_id", "value_code", "value_name"],
                message="apaas_app_id+dict_id+value_code+value_name 都必填")
    async def add_apaas_dict_option(env_id: int, apaas_app_id: str, dict_id: str,
                                    value_code: str, value_name: str, display_order: int = 0) -> dict:
        """给字典加一个选项。

        例：给"业务状态"字典加"已驳回" → add_apaas_dict_option(env_id, app_id, dict_id, "rejected", "已驳回")
        """
        ok, raw = await _with_client(env_id, "加字典选项",
            lambda c: c.add_dict_option(apaas_app_id.strip(), dict_id.strip(), value_code.strip(), value_name.strip(), display_order))
        if not ok:
            return raw
        _invalidate_section_cache_after_write(apaas_app_id)
        return _ok(env_id=env_id, apaas_app_id=apaas_app_id.strip(),
                   dict_id=dict_id.strip(),
                   value_code=value_code.strip(), value_name=value_name.strip(),
                   message=f"已给字典 {dict_id} 加选项「{value_name}」({value_code})")


    @mcp.tool()
    @apaas_tool(required=["apaas_app_id", "dict_id", "option_id", "value_code", "value_name"],
                message="apaas_app_id+dict_id+option_id+value_code+value_name 都必填")
    async def update_apaas_dict_option(env_id: int, apaas_app_id: str, dict_id: str, option_id: str,
                                       value_code: str, value_name: str,
                                       display_order: int = 0, describe: str = "", multicolor: str = "#027AFF") -> dict:
        """更新字典选项（改 code / name / 排序 / 颜色）。先 list_apaas_app_dicts(with_options=true) 拿 option_id。"""
        ok, raw = await _with_client(env_id, "改字典选项",
            lambda c: c.update_dict_option(apaas_app_id.strip(), dict_id.strip(), option_id.strip(),
                                           value_code.strip(), value_name.strip(),
                                           display_order=display_order, describe=describe, multicolor=multicolor))
        if not ok:
            return raw
        _invalidate_section_cache_after_write(apaas_app_id)
        return _ok(message=f"字典选项「{value_name}」({value_code}) 已更新")


    # ───── 模型 + 字段 CRUD（精细操作） ─────

    @mcp.tool()
    @apaas_tool(required=["apaas_app_id", "model_id", "model_code", "model_name"],
                message="必填全填")
    async def update_apaas_app_model(env_id: int, apaas_app_id: str, model_id: str,
                                     model_code: str, model_name: str,
                                     app_name: str = "", model_data_source: str = "") -> dict:
        """更新模型基本信息（改名/改 code）。不能改字段 — 字段走 add/update_apaas_model_field。

        先 list_apaas_app_models 拿 model_id。
        """
        ok, raw = await _with_client(env_id, "改模型",
            lambda c: c.update_model(apaas_app_id.strip(), model_id.strip(), model_code.strip(), model_name.strip(),
                                     app_name=app_name, model_data_source=model_data_source))
        if not ok:
            return raw
        _invalidate_section_cache_after_write(apaas_app_id)
        return _ok(message=f"模型「{model_name}」({model_code}) 已更新",
                   next_step="调 republish_apaas_app 让变更生效")


    @mcp.tool()
    @apaas_tool(required=["apaas_app_id", "model_id", "model_code", "field_code", "field_name"],
                message="必填全填")
    async def add_apaas_model_field(env_id: int, apaas_app_id: str, model_id: str, model_code: str,
                                    field_code: str, field_name: str,
                                    field_type: str = "STRING", max_length: int = 255,
                                    comment: str = "") -> dict:
        """给已有模型加一个字段。

        field_type 常用：STRING / NUM / DATE / DATETIME / BOOLEAN / TEXT / BIG_TEXT
        ⚠️ 慎用 approver_id / approval_* 等 apaas 流程保留字。
        """
        # 简易保留字预检
        reserved = {"approver_id", "id", "tenant_id"}
        if field_code.strip().lower() in reserved or field_code.strip().lower().startswith("approval_"):
            return _err(ErrorCode.RESERVED_FIELD_CODE,
                        f"field_code '{field_code}' 命中 apaas 保留字 — 建议改成 {model_code}_{field_code}")
        ok, raw = await _with_client(env_id, "加字段",
            lambda c: c.add_model_field(apaas_app_id.strip(), model_id.strip(), model_code.strip(),
                                        field_code.strip(), field_name.strip(),
                                        field_type=field_type, max_length=max_length, comment=comment))
        if not ok:
            return raw
        _invalidate_section_cache_after_write(apaas_app_id)
        return _ok(message=f"模型 {model_code} 已加字段「{field_name}」({field_code} / {field_type})")


    @mcp.tool()
    @apaas_tool(required=["apaas_app_id", "model_id", "field_id", "field_code", "field_name"],
                message="必填全填")
    async def update_apaas_model_field(env_id: int, apaas_app_id: str, model_id: str, field_id: str,
                                       field_code: str, field_name: str,
                                       field_type: str = "", max_length: int = 0, comment: str = "") -> dict:
        """更新字段属性（改名 / 改类型 / 改最大长度）。

        ⚠️ 改 field_type 可能影响存量数据，建议先 disable_apaas_model_field 旧字段 + add_apaas_model_field 新字段。
        本工具不强制，由 agent 决策。

        先 list_apaas_app_models(with_fields=true) 拿 field_id。
        """
        ok, raw = await _with_client(env_id, "改字段",
            lambda c: c.update_model_field(apaas_app_id.strip(), model_id.strip(), field_id.strip(),
                                           field_code.strip(), field_name.strip(),
                                           field_type=field_type or None,
                                           max_length=max_length if max_length > 0 else None,
                                           field_status="ENABLE",
                                           comment=comment or None))
        if not ok:
            return raw
        _invalidate_section_cache_after_write(apaas_app_id)
        return _ok(message=f"字段「{field_name}」({field_code}) 已更新")


    @mcp.tool()
    @apaas_tool(required=["apaas_app_id", "model_id", "field_id", "field_code", "field_name"],
                message="必填全填")
    async def disable_apaas_model_field(env_id: int, apaas_app_id: str, model_id: str, field_id: str,
                                        field_code: str, field_name: str) -> dict:
        """禁用模型字段（apaas 不能真删字段，只能 status=DISABLE）。

        禁用后字段在表单/列表里不可见，但底层数据保留。重新启用调 update_apaas_model_field(field_status=ENABLE)。
        """
        ok, raw = await _with_client(env_id, "禁用字段",
            lambda c: c.update_model_field(apaas_app_id.strip(), model_id.strip(), field_id.strip(),
                                           field_code.strip(), field_name.strip(),
                                           field_status="DISABLE"))
        if not ok:
            return raw
        _invalidate_section_cache_after_write(apaas_app_id)
        return _ok(message=f"字段「{field_name}」({field_code}) 已禁用",
                   note="apaas 字段不能真删只能 DISABLE。重新启用调 update_apaas_model_field(field_status='ENABLE')")


    # ───── 菜单 / 表单（精细操作） ─────

    @mcp.tool()
    async def create_apaas_form_menu(env_id: int, apaas_app_id: str, menu_name: str, form_id: str,
                                     menu_order: int = 0, parent_id: str = "") -> dict:
        """创建普通表单菜单（menuType=MENU/MODEL，关联到表单的 formId）。

        跟 create_apaas_self_dev_menu 区别：那个是 CUSTOM 自开发菜单（linkUrl=组件名），
        这个是普通表单菜单（formId=表单 ID）。

        parent_id 可选: 传了挂到对应 group 下; 不传放根级。
        """
        if not (apaas_app_id.strip() and menu_name.strip() and form_id.strip()):
            return {"ok": False, "error_code": "INVALID_PARAMS", "message": "apaas_app_id+menu_name+form_id 都必填"}
        pid = parent_id.strip()
        # 2026-05-25: create_menu 不直接接 parent_id, 先创建再 update_menu_parent 挂载
        ok, raw = await _with_client(env_id, "建表单菜单",
            lambda c: c.create_menu(apaas_app_id.strip(), menu_name.strip(), form_id.strip(),
                                    menu_order=menu_order, datasource_id="", datasource_code=""))
        if not ok:
            return raw
        _invalidate_section_cache_after_write(apaas_app_id)
        new_menu = raw if isinstance(raw, dict) else {}
        new_menu_id = str(new_menu.get("id") or new_menu.get("menuId") or "")
        if pid and new_menu_id:
            ok2, raw2 = await _with_client(env_id, "挂菜单到分组",
                lambda c: c.update_menu_parent(apaas_app_id.strip(), new_menu_id, parent_id=pid,
                                                menu_order=menu_order))
            if not ok2:
                return {"ok": True, "warning": "菜单已建但挂到分组失败 — 可手动调 set_apaas_menu_parent",
                        "menu_id": new_menu_id, "parent_id_attempted": pid, "parent_error": raw2}
        return {"ok": True,
                "menu_id": new_menu_id,
                "parent_id": pid or None,
                "message": f"表单菜单「{menu_name}」已创建"
                           + (f"（挂到分组 {pid} 下）" if pid else "（根级）")}


    @mcp.tool()
    async def create_apaas_menu_group(
        env_id: int,
        apaas_app_id: str,
        group_name: str,
        menu_order: int = 0,
        parent_id: str = "",
    ) -> dict:
        """创建菜单分组 (menuType=GROUP, 用来归类菜单).

        分组本身没 form_id, 不关联表单. 创建后可用 set_apaas_menu_parent 把已有菜单
        挂到这个分组下, 或 create_apaas_form_menu(parent_id=<group_id>) 直接在
        分组下创建表单菜单。

        parent_id 可选: 嵌套分组用 (group 套 group).
        """
        if not (apaas_app_id.strip() and group_name.strip()):
            return {"ok": False, "error_code": "INVALID_PARAMS",
                    "message": "apaas_app_id+group_name 都必填"}
        ok, raw = await _with_client(env_id, "建菜单分组",
            lambda c: c.create_menu_group(
                apaas_app_id.strip(), group_name.strip(),
                menu_order=menu_order, parent_id=parent_id,
            ))
        if not ok:
            return raw
        _invalidate_section_cache_after_write(apaas_app_id)
        new_group = raw if isinstance(raw, dict) else {}
        return {
            "ok": True,
            "group_id": str(new_group.get("id") or new_group.get("menuId") or ""),
            "group_name": group_name,
            "message": f"菜单分组「{group_name}」已创建"
                       + (f"（嵌套在 {parent_id} 下）" if parent_id else "（根级）"),
        }


    @mcp.tool()
    async def set_apaas_menu_parent(
        env_id: int,
        apaas_app_id: str,
        menu_id: str,
        parent_id: str = "",
        menu_order: int = 0,
    ) -> dict:
        """改菜单的父分组 — 把现有菜单移到某个 group 下, 或移出回根级.

        parent_id="" → 移到根 (脱离任何 group)
        parent_id=<group_menu_id> → 挂到那个 group 下

        ⚠️ 实现是 save/menu 覆盖式更新, 会查现有 menu 完整字段后 merge 改 parentId,
        其他业务字段 (menuName/formId/linkUrl 等) 都保留不动。
        """
        if not (apaas_app_id.strip() and menu_id.strip()):
            return {"ok": False, "error_code": "INVALID_PARAMS",
                    "message": "apaas_app_id+menu_id 都必填"}
        ok, raw = await _with_client(env_id, "改菜单父分组",
            lambda c: c.update_menu_parent(
                apaas_app_id.strip(), menu_id.strip(),
                parent_id=parent_id, menu_order=menu_order,
            ))
        if not ok:
            return raw
        _invalidate_section_cache_after_write(apaas_app_id)
        return {
            "ok": True,
            "menu_id": menu_id,
            "parent_id": parent_id or None,
            "message": (f"菜单 {menu_id} 已挂到分组 {parent_id} 下"
                        if parent_id else f"菜单 {menu_id} 已移出分组到根级"),
        }


    @mcp.tool()
    async def rename_apaas_menu(
        env_id: int,
        apaas_app_id: str,
        menu_id: str,
        new_name: str,
    ) -> dict:
        """改菜单名 — 普通菜单 / 分组 / 自开发菜单 都用这个.

        例: 把分组"测试"改成"业务核心":
            rename_apaas_menu(env_id=49, apaas_app_id="846...",
                              menu_id="846743128927895552", new_name="业务核心")

        实现: GET 菜单完整字段 → POST /xdap-app/menu/save/menu 改 menuName → verify.
        平台 save/menu 接受 menuName 更新 (跟改 parentId 不一样, menuName 正常持久化).
        """
        if not (apaas_app_id.strip() and menu_id.strip() and new_name.strip()):
            return {"ok": False, "error_code": "INVALID_PARAMS",
                    "message": "apaas_app_id + menu_id + new_name 都必填"}
        ok, raw = await _with_client(env_id, "改菜单名",
            lambda c: c.rename_menu(apaas_app_id.strip(), menu_id.strip(), new_name.strip()))
        if not ok:
            return raw
        _invalidate_section_cache_after_write(apaas_app_id)
        return {
            "ok": True,
            "menu_id": menu_id,
            "menu_name": new_name.strip(),
            "message": f"菜单 {menu_id} 已改名为「{new_name}」",
        }


    @mcp.tool()
    async def update_apaas_self_dev_menu_link_url(
        env_id: int,
        apaas_app_id: str,
        menu_id: str,
        link_url: str,
        menu_type: str = "",
        confirmed: bool = False,
    ) -> dict:
        """更新自开发页面菜单的 linkUrl。

        场景：页面包已更新，但菜单已存在且仍指向旧组件注册名，例如
        apaas-custom-form-page-xxx。工具会读取现有菜单完整字段，只覆盖 linkUrl，
        默认保留平台当前 menuType；如确需强制可传 menu_type=CUSTOM 或 MENU。
        若当前 linkUrl 与目标 linkUrl 不一致，默认返回 NEEDS_CONFIRMATION；
        用户确认这是同一个菜单切换到新包后，再传 confirmed=true 执行更新。
        """
        if not (apaas_app_id.strip() and menu_id.strip() and link_url.strip()):
            return {"ok": False, "error_code": "INVALID_PARAMS",
                    "message": "apaas_app_id + menu_id + link_url 都必填"}
        normalized_menu_type = menu_type.strip().upper()
        if normalized_menu_type and normalized_menu_type not in {"CUSTOM", "MENU"}:
            return {"ok": False, "error_code": "INVALID_MENU_TYPE",
                    "message": "menu_type 只能留空或传 CUSTOM / MENU"}
        ok, raw = await _with_client(
            env_id, "更新自开发菜单 linkUrl",
            lambda c: c.update_self_dev_menu_link_url(
                apaas_app_id.strip(),
                menu_id.strip(),
                link_url.strip(),
                menu_type=normalized_menu_type,
                confirmed=confirmed,
            ),
        )
        if not ok:
            return raw
        if (raw or {}).get("needs_confirmation"):
            return {
                "ok": False,
                "error_code": "NEEDS_CONFIRMATION",
                "menu_id": menu_id.strip(),
                "menu_name": (raw or {}).get("menu_name"),
                "current_link_url": (raw or {}).get("old_link_url"),
                "requested_link_url": (raw or {}).get("link_url"),
                "message": (
                    "该菜单当前指向另一个自开发包。请向用户确认是否要把这个菜单切换到"
                    f" {(raw or {}).get('link_url')}；确认后重新调用并传 confirmed=true。"
                ),
            }
        _invalidate_section_cache_after_write(apaas_app_id)
        return {
            "ok": True,
            "menu_id": menu_id.strip(),
            "old_link_url": (raw or {}).get("old_link_url"),
            "link_url": (raw or {}).get("link_url"),
            "menu_type": (raw or {}).get("menu_type"),
            "message": f"菜单 {menu_id.strip()} linkUrl 已更新为 {link_url.strip()}",
        }


    @mcp.tool()
    async def delete_apaas_app_menu(env_id: int, apaas_app_id: str, menu_id: str, menu_name: str = "") -> dict:
        """删除应用菜单（普通菜单 / 表单菜单 / 自开发菜单都用这个）。

        ⚠️ 删除表单菜单会联动删表单本身（apaas 内部行为）。删除前确认 menu_id 对的。
        """
        if not (apaas_app_id.strip() and menu_id.strip()):
            return {"ok": False, "error_code": "INVALID_PARAMS", "message": "apaas_app_id+menu_id 都必填"}
        ok, raw = await _with_client(env_id, "删菜单",
            lambda c: c.delete_menu(apaas_app_id.strip(), menu_id.strip(), menu_name=menu_name))
        if not ok:
            return raw
        _invalidate_section_cache_after_write(apaas_app_id)
        return {"ok": True, "message": f"菜单 {menu_id} 已删除（如果是表单菜单，关联表单也被删了）"}

    @mcp.tool()
    @apaas_tool(required=["apaas_app_id", "form_id", "field_label", "dict_code"],
                message="apaas_app_id+form_id+field_label+dict_code 都必填")
    async def bind_apaas_form_field_to_dict(
        env_id: int,
        apaas_app_id: str,
        form_id: str,
        field_label: str,
        dict_code: str,
    ) -> dict:
        """把表单字段的"数据来源"绑定到指定数据字典 (切组件 + source.type + 选项三件套).

        适用场景: build_apaas_feature_from_spec 时漏了 dict_options, 后期用本工具补绑.
        或者用户手动建的字段, 想绑字典.

        单纯 update_apaas_form_component(updates={dictionaryChooseOptions:[...]}) 不够 —
        平台的"数据来源"由 source.type 决定 (INPUT_TYPE=输入值, DICTIONARY_TYPE=数据字典),
        缺 source 字段平台仍渲染为"输入值". 本工具会:
          1. 反查 dict_code 拿 dictionary_id 和真实 options
          2. 把组件类型改为 FORM_SELECT_INPUT_SINGLE (若不是)
          3. 一并送 source + chooseOptions + dictionaryChooseOptions 给 update_form_component

        前置:
          - dict_code: 已经存在的字典 (没有就先 create_apaas_app_dict 建好)
          - field_label: 字段精确 label (区分大小写, 跟 list_apaas_form_components 拿一致)

        返回: {ok, dictionary_id, options_count, message}
        """
        # 反查字典 — 拿 id + options
        ok_dicts, dicts = await _with_client(env_id, "查字典",
            lambda c: c.query_dicts(apaas_app_id.strip()))
        if not ok_dicts:
            return dicts
        target_dict = None
        for d in (dicts or []):
            if isinstance(d, dict) and str(d.get("dictionaryCode") or "") == dict_code.strip():
                target_dict = d
                break
        if not target_dict:
            return _err(ErrorCode.DICT_NOT_FOUND,
                        f"字典 code={dict_code} 在应用里不存在. 先 create_apaas_app_dict 建好")
        dict_id = str(target_dict.get("id") or "")
        options_raw = target_dict.get("dictionaryOptions") or []
        # 构建 chooseOptions / dictionaryChooseOptions (平台 chooseOptions 跟 dictionaryChooseOptions
        # 实际是同款 schema, 平台保存时分别用)
        choose_options = []
        for o in options_raw:
            if isinstance(o, dict):
                choose_options.append({
                    "id": o.get("optionCode") or o.get("code") or "",
                    "label": o.get("optionName") or o.get("name") or "",
                    "labelI18nAssociated": False,
                    "color": "#027AFF",
                    "status": "ENABLE",
                    "displayOrder": o.get("displayOrder") or 0,
                })

        # 构建 updates: 关键是 source 切 DICTIONARY_TYPE
        updates = {
            "componentType": "FORM_SELECT_INPUT",
            "source": {"type": "DICTIONARY_TYPE", "id": dict_id},
            "chooseType": "SINGLE",
            "multicolor": True,
            "dictionaryMulticolorStatus": "ENABLE",
            "chooseOptions": choose_options,
            "dictionaryChooseOptions": choose_options,
        }

        ok, raw = await _with_client(env_id, "绑字典",
            lambda c: c.update_form_component(
                apaas_app_id.strip(), form_id.strip(), field_label.strip(), updates))
        if not ok:
            return raw

        return _ok(
            form_id=form_id,
            field_label=field_label,
            dictionary_id=dict_id,
            dictionary_code=dict_code,
            options_count=len(choose_options),
            message=(f"字段「{field_label}」已绑定字典「{dict_code}」"
                     f"({len(choose_options)} 选项), 数据来源切为数据字典"),
        )


    # ─── 字典 disable（补 CRUD 的 D）─────────────────────────────────────────
    # apaas 平台没真 delete，"禁用"是终态（运行时不再可选，但历史数据保留引用）。
    # 配套 incremental_executor._disable_dict / _disable_dict_option 用的 GET 接口。

    @mcp.tool()
    @apaas_tool(required=["apaas_app_id", "dict_id"], message="apaas_app_id+dict_id 都必填")
    async def disable_apaas_app_dict(env_id: int, apaas_app_id: str, dict_id: str, dict_name: str = "") -> dict:
        """禁用应用字典（apaas 没真 delete，禁用是终态）。

        ⚠️ 禁用后：
          - 运行时表单上该字典作为下拉选项不再可选
          - 已存在的业务数据里引用此字典的字段保留原值不动
          - 不可逆 — apaas 没暴露"重新启用"接口（如果有需求再单独加 enable）

        dict_id 怎么拿：先调 list_apaas_app_dicts 看现有字典 + id。
        """
        ok, raw = await _with_client(env_id, "禁用字典",
            lambda c: c.disable_dict(apaas_app_id.strip(), dict_id.strip()))
        if not ok:
            return raw
        return _ok(
            dict_id=dict_id,
            message=f"字典「{dict_name or dict_id}」已禁用（运行时不可选，历史数据保留）",
        )


    @mcp.tool()
    @apaas_tool(required=["apaas_app_id", "option_id"], message="apaas_app_id+option_id 都必填")
    async def disable_apaas_dict_option(
        env_id: int,
        apaas_app_id: str,
        option_id: str,
        option_name: str = "",
    ) -> dict:
        """禁用字典里某个选项（apaas 没真 delete，禁用是终态）。

        用法：先调 list_apaas_app_dicts 拿字典 → 看 options 列表 → 拿到要禁用的
        option.id 传进来。

        禁用后选项不再出现在新建表单下拉里，已选过此值的历史数据保留。
        """
        ok, raw = await _with_client(env_id, "禁用字典选项",
            lambda c: c.disable_dict_option(apaas_app_id.strip(), option_id.strip()))
        if not ok:
            return raw
        return _ok(
            option_id=option_id,
            message=f"字典选项「{option_name or option_id}」已禁用",
        )

    tools = {
        "create_apaas_app_roles": create_apaas_app_roles,
        "update_apaas_app_role": update_apaas_app_role,
        "delete_apaas_app_role": delete_apaas_app_role,
        "create_apaas_app_dict": create_apaas_app_dict,
        "update_apaas_app_dict": update_apaas_app_dict,
        "add_apaas_dict_option": add_apaas_dict_option,
        "update_apaas_dict_option": update_apaas_dict_option,
        "update_apaas_app_model": update_apaas_app_model,
        "add_apaas_model_field": add_apaas_model_field,
        "update_apaas_model_field": update_apaas_model_field,
        "disable_apaas_model_field": disable_apaas_model_field,
        "create_apaas_form_menu": create_apaas_form_menu,
        "create_apaas_menu_group": create_apaas_menu_group,
        "set_apaas_menu_parent": set_apaas_menu_parent,
        "rename_apaas_menu": rename_apaas_menu,
        "update_apaas_self_dev_menu_link_url": update_apaas_self_dev_menu_link_url,
        "delete_apaas_app_menu": delete_apaas_app_menu,
        "bind_apaas_form_field_to_dict": bind_apaas_form_field_to_dict,
        "disable_apaas_app_dict": disable_apaas_app_dict,
        "disable_apaas_dict_option": disable_apaas_dict_option,
    }
    _registered_tools_by_mcp[marker] = tools
    return tools
