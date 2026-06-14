"""aPaaS self-development scene and asset MCP tools."""

from __future__ import annotations

import logging
from typing import Any, Callable


logger = logging.getLogger(__name__)
_registered_tools_by_mcp: dict[int, dict[str, object]] = {}


_PLATFORM_FILE_TYPES_V2_6 = {
    "FRONTENGINE": "Web端自开发页面",
    "FRONTCOMPONENT": "Web端自开发组件",
    "FRONTLAYOUT": "Web端自定义布局",
    "FRONTLISTVIEW": "Web端自定义列表视图",
    "MFRONTENGINE": "移动端自开发页面",
    "MFRONTCOMPONENT": "移动端自开发组件",
    "FRONTTENANTCOMPONENT": "平台前端自开发插件",
    "BACKENDENGINE": "后端自开发模版",
    "BACKPROPERTIES": "后端自开发配置文件",
    "BACKENDENGINEPKG": "后端自开发模版包",
    "DEPORTAL_SELF_PACKAGE": "Web端工作台/仪表板自开发组件",
    "DEPORTAL_MOBILE_SELF_PACKAGE": "移动端工作台/仪表板自开发组件",
}


def _normalize_apaas_user_summary(user: dict[str, Any]) -> dict[str, str]:
    """Pick stable user identity fields from several aPaaS response shapes."""

    def _first(*keys: str) -> str:
        for key in keys:
            value = user.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return ""

    user_id = _first("id", "userId", "user_id")
    user_name = _first("username", "userName", "realName", "name", "nickName")
    account = _first("account", "accountName", "loginName", "mobile")
    return {
        "id": user_id,
        "user_name": user_name,
        "display_name": user_name or account or user_id,
        "account": account,
        "status": _first("status", "accountStatus", "workStatus"),
        "account_type": _first("accountType"),
    }


def register(
    mcp,
    with_client: Callable,
    invalidate_section_cache_after_write: Callable[[str], None],
) -> dict[str, object]:
    """Register self-development scene and asset tools on the shared FastMCP instance."""
    marker = id(mcp)
    if marker in _registered_tools_by_mcp:
        return _registered_tools_by_mcp[marker]

    @mcp.tool()
    async def list_dev_scenes() -> dict:
        """列出 ai-builder 支持的所有自开发场景类型（首次接到自开发需求时**必调**）。

        返回的是"场景索引"——精简版，只含场景识别需要的核心字段。要拿某个场景的
        完整规范（关键警示 / 必问参数 / 输出文件清单）走 `get_dev_scene_spec`。

        用法：
            step 0: list_dev_scenes()
            step 1: 关键词初筛 + 用户确认场景
            step 2: get_dev_scene_spec(scene_type) 拿详情
            step 3: 用 user_inputs_needed 跟用户对齐参数
            step 4: create_dev_workspace(...)
        """
        from app.dev_scene_spec import SPEC_VERSION, list_scene_briefs

        return {
            "ok": True,
            "spec_version": SPEC_VERSION,
            "scenes": list_scene_briefs(),
        }

    @mcp.tool()
    async def get_dev_scene_spec(scene_type: str) -> dict:
        """拿到某个自开发场景的完整规范。"""
        from app.dev_scene_spec import all_scene_types, get_scene_brief

        scene = get_scene_brief(scene_type)
        if scene is None:
            return {
                "ok": False,
                "error_code": "SCENE_NOT_FOUND",
                "message": f"未知的 scene_type: {scene_type}。可选值：{', '.join(all_scene_types())}",
                "valid_scene_types": all_scene_types(),
            }
        return {"ok": True, "scene": scene}

    @mcp.tool()
    async def get_dev_scene_full_workflow(scene_type: str) -> dict:
        """拿到某个自开发场景的完整开发规范。"""
        from app.dev_scene_spec import all_scene_types
        from app.dev_scene_workflow import get_full_workflow, has_full_workflow

        if scene_type not in all_scene_types():
            return {
                "ok": False,
                "error_code": "SCENE_NOT_FOUND",
                "message": f"未知 scene_type: {scene_type}",
                "valid_scene_types": all_scene_types(),
            }
        return {
            "ok": True,
            "scene_type": scene_type,
            "has_full_workflow": has_full_workflow(scene_type),
            "workflow_markdown": get_full_workflow(scene_type),
        }

    @mcp.tool()
    async def get_apaas_user_name(env_id: int, apaas_user_id: str, apaas_app_id: str = "") -> dict:
        """根据 aPaaS userId 查询用户名称。"""
        target_id = str(apaas_user_id or "").strip()
        if not target_id:
            return {
                "ok": False,
                "error_code": "INVALID_APAAS_USER_ID",
                "message": "apaas_user_id 不能为空",
            }

        app_id = str(apaas_app_id or "").strip()
        ok, users = await with_client(
            env_id,
            "按用户ID查询用户名称",
            lambda c: c.query_users_by_ids([target_id], app_id=app_id or None),
        )
        if not ok:
            return users

        summaries = [
            _normalize_apaas_user_summary(item)
            for item in (users or [])
            if isinstance(item, dict)
        ]
        matched = next(
            (item for item in summaries if item.get("id") == target_id),
            summaries[0] if summaries else None,
        )
        if not matched:
            return {
                "ok": False,
                "error_code": "APAAS_USER_NOT_FOUND",
                "message": f"未查询到用户 {target_id}",
                "env_id": env_id,
                "apaas_user_id": target_id,
            }

        return {
            "ok": True,
            "env_id": env_id,
            "apaas_app_id": app_id,
            "apaas_user_id": target_id,
            "user_name": matched["display_name"],
            "user": matched,
        }

    @mcp.tool()
    async def enable_apaas_self_dev_config(
        env_id: int,
        apaas_app_id: str,
        status: str = "ENABLE",
    ) -> dict:
        """开启 / 关闭 aPaaS 应用的自开发配置开关。"""
        if not apaas_app_id.strip():
            return {"ok": False, "error_code": "INVALID_APAAS_APP_ID", "message": "apaas_app_id 不能为空"}
        if status not in ("ENABLE", "DISABLE"):
            return {"ok": False, "error_code": "INVALID_STATUS", "message": "status 必须是 ENABLE 或 DISABLE"}
        ok, payload = await with_client(
            env_id,
            "开启自开发配置",
            lambda c: c.enable_self_dev_config(apaas_app_id.strip(), status=status),
        )
        if not ok:
            return payload
        return {
            "ok": True,
            "env_id": env_id,
            "apaas_app_id": apaas_app_id.strip(),
            "status": status,
            "message": (payload or {}).get("message", "操作成功"),
        }

    @mcp.tool()
    async def list_apaas_app_dev_kits(
        env_id: int,
        apaas_app_id: str,
        file_name_filter: str = "",
    ) -> dict:
        """列指定 aPaaS 应用可关联的自开发包（zip）。"""
        if not apaas_app_id.strip():
            return {"ok": False, "error_code": "INVALID_APAAS_APP_ID", "message": "apaas_app_id 不能为空"}
        ok, kits = await with_client(
            env_id,
            "列自开发包",
            lambda c: c.query_app_dev_kits(apaas_app_id.strip(), file_name=file_name_filter),
        )
        if not ok:
            return kits
        normalized = [
            {
                "id": str(k.get("id") or ""),
                "fileName": str(k.get("fileName") or ""),
                "fileType": str(k.get("fileType") or ""),
                "size": k.get("size"),
                "userName": k.get("userName"),
                "createTime": k.get("createTime"),
            }
            for k in (kits or [])
            if isinstance(k, dict)
        ]
        return {
            "ok": True,
            "env_id": env_id,
            "apaas_app_id": apaas_app_id.strip(),
            "kits": normalized,
            "total": len(normalized),
        }

    @mcp.tool()
    async def attach_dev_packages_to_apaas_app(
        env_id: int,
        apaas_app_id: str,
        kit_ids: list[str],
    ) -> dict:
        """把已上传到 aPaaS 平台的自开发包关联到应用。"""
        if not apaas_app_id.strip():
            return {"ok": False, "error_code": "INVALID_APAAS_APP_ID", "message": "apaas_app_id 不能为空"}
        if not kit_ids:
            return {"ok": False, "error_code": "EMPTY_KIT_IDS", "message": "kit_ids 不能为空"}
        ok, payload = await with_client(
            env_id,
            "关联自开发包",
            lambda c: c.attach_apaas_source_relation(apaas_app_id.strip(), object_ids=kit_ids),
        )
        if not ok:
            message = str((payload or {}).get("message") or payload or "")
            if not any(marker in message for marker in ("重复", "已存在", "duplicate", "exist")):
                return payload

            attached: list[str] = []
            skipped_duplicates: list[str] = []
            failed: list[dict] = []
            for kit_id in kit_ids:
                item_ok, item_payload = await with_client(
                    env_id,
                    f"关联自开发包 {kit_id}",
                    lambda c, kid=kit_id: c.attach_apaas_source_relation(
                        apaas_app_id.strip(), object_ids=[kid]
                    ),
                )
                if item_ok:
                    attached.append(str(kit_id))
                    continue
                item_message = str((item_payload or {}).get("message") or item_payload or "")
                if any(marker in item_message for marker in ("重复", "已存在", "duplicate", "exist")):
                    skipped_duplicates.append(str(kit_id))
                    continue
                failed.append({"kit_id": str(kit_id), "error": item_payload})
            if failed:
                return {
                    "ok": False,
                    "error_code": "PARTIAL_ATTACH_FAILED",
                    "env_id": env_id,
                    "apaas_app_id": apaas_app_id.strip(),
                    "attached_kit_ids": attached,
                    "skipped_duplicate_kit_ids": skipped_duplicates,
                    "failed": failed,
                    "message": "部分自开发包关联失败",
                }
            return {
                "ok": True,
                "env_id": env_id,
                "apaas_app_id": apaas_app_id.strip(),
                "attached_count": len(attached),
                "skipped_duplicate_count": len(skipped_duplicates),
                "attached_kit_ids": attached,
                "skipped_duplicate_kit_ids": skipped_duplicates,
                "message": (
                    f"已关联 {len(attached)} 个自开发包，"
                    f"跳过 {len(skipped_duplicates)} 个已关联包。下一步：republish_apaas_app 重发版本让组件生效。"
                ),
            }
        return {
            "ok": True,
            "env_id": env_id,
            "apaas_app_id": apaas_app_id.strip(),
            "attached_count": len(kit_ids),
            "message": f"已关联 {len(kit_ids)} 个自开发包。下一步：republish_apaas_app 重发版本让组件生效。",
        }

    @mcp.tool()
    async def republish_apaas_app(
        env_id: int,
        apaas_app_id: str,
        abstract: str = "自开发资源更新自动重发",
        version: str = "",
    ) -> dict:
        """重新发布 aPaaS 应用版本（自开发变更必须 redeploy 才生效）。"""
        if not apaas_app_id.strip():
            return {"ok": False, "error_code": "INVALID_APAAS_APP_ID", "message": "apaas_app_id 不能为空"}

        def _bump_patch(v: str) -> str:
            try:
                parts = [int(p) for p in v.split(".")]
                parts[-1] += 1
                return ".".join(str(p) for p in parts)
            except (ValueError, IndexError):
                return v

        async def _run(client):
            target = version.strip()
            strategy = "explicit"
            if not target:
                detail = await client.query_app_detail(apaas_app_id.strip())
                target = detail.get("currentVersion") or detail.get("appVersion") or detail.get("version") or "1.0.0"
                strategy = "currentVersion"
            try:
                result = await client.deploy_app(apaas_app_id.strip(), target, abstract=abstract)
                return {"version": target, "strategy": strategy, "raw": result}
            except Exception as e1:
                if "版本" in str(e1) or "version" in str(e1).lower():
                    bumped = _bump_patch(target)
                    if bumped != target:
                        result = await client.deploy_app(apaas_app_id.strip(), bumped, abstract=abstract)
                        return {
                            "version": bumped,
                            "strategy": f"{strategy}+bump",
                            "raw": result,
                            "fallback_note": f"{target} 失败，patch+1 到 {bumped} 成功",
                        }
                raise

        ok, result = await with_client(env_id, "重新发布应用", _run)
        if not ok:
            return result
        return {
            "ok": True,
            "env_id": env_id,
            "apaas_app_id": apaas_app_id.strip(),
            "version": (result or {}).get("version"),
            "strategy": (result or {}).get("strategy"),
            "fallback_note": (result or {}).get("fallback_note"),
            "message": f"应用已发布到版本 {(result or {}).get('version')}",
        }

    @mcp.tool()
    async def create_apaas_self_dev_menu(
        env_id: int,
        apaas_app_id: str,
        menu_name: str,
        link_url: str,
        parent_id: str = "",
        menu_icon: str = "userInfo",
        icon_color: str = "#027AFF",
        menu_display: str = "PC",
    ) -> dict:
        """在 aPaaS 应用菜单里创建一个自开发页面菜单（menuType=CUSTOM）。"""
        if not apaas_app_id.strip() or not menu_name.strip() or not link_url.strip():
            return {
                "ok": False,
                "error_code": "INVALID_PARAMS",
                "message": "apaas_app_id / menu_name / link_url 都不能为空",
            }
        ok, payload = await with_client(
            env_id,
            "创建自开发菜单",
            lambda c: c.create_self_dev_menu(
                apaas_app_id.strip(),
                menu_name.strip(),
                link_url.strip(),
                parent_id=parent_id,
                menu_icon=menu_icon,
                icon_color=icon_color,
                menu_display=menu_display,
            ),
        )
        if not ok:
            message = str((payload or {}).get("message") or "")
            if any(marker in message for marker in ("已存在", "重复", "exist", "duplicate")):

                async def _query_existing(client):
                    def _walk(nodes):
                        for node in nodes or []:
                            if not isinstance(node, dict):
                                continue
                            name = str(node.get("menuName") or node.get("menu_name") or node.get("name") or "")
                            if name == menu_name.strip():
                                return node
                            found = _walk(node.get("submenus") or node.get("children") or [])
                            if found:
                                return found
                        return None

                    menus = await client.query_menus(apaas_app_id.strip())
                    return _walk(menus)

                ok_existing, existing = await with_client(env_id, "查询已存在自开发菜单", _query_existing)
                if ok_existing and isinstance(existing, dict):
                    existing_link_url = str(existing.get("linkUrl") or existing.get("link_url") or "")
                    payload = {
                        **payload,
                        "error_code": "SELF_DEV_MENU_EXISTS",
                        "existing_menu": {
                            "menu_id": str(existing.get("id") or existing.get("menuId") or existing.get("menu_id") or ""),
                            "menu_name": menu_name.strip(),
                            "link_url": existing_link_url,
                        },
                        "expected_link_url": link_url.strip(),
                        "link_url_matches": existing_link_url == link_url.strip(),
                        "hint": (
                            "菜单已存在但 linkUrl 与 expected_link_url 不一致时，"
                            "请调用 update_apaas_self_dev_menu_link_url(menu_id=existing_menu.menu_id, "
                            "link_url=expected_link_url, confirmed=true) 更新同一个菜单；不要删除旧菜单或新建同名菜单。"
                        ),
                    }
            return payload
        invalidate_section_cache_after_write(apaas_app_id)
        return {
            "ok": True,
            "env_id": env_id,
            "apaas_app_id": apaas_app_id.strip(),
            "menu_name": menu_name.strip(),
            "link_url": link_url.strip(),
            "message": f"自开发菜单「{menu_name.strip()}」已创建",
        }

    @mcp.tool()
    async def list_apaas_resource_pool_kits(
        env_id: int,
        file_type_filter: str = "",
        key_word: str = "",
        page_size: int = 50,
    ) -> dict:
        """全资源池列 aPaaS 平台上所有自开发包（跨应用、跨 fileType）。"""
        valid_filter = (file_type_filter or "").strip().upper()
        if valid_filter and valid_filter not in _PLATFORM_FILE_TYPES_V2_6:
            return {
                "ok": False,
                "error_code": "INVALID_FILE_TYPE",
                "message": f"file_type_filter '{file_type_filter}' 不在 V2.6 全 12 类里",
                "supported_file_types": _PLATFORM_FILE_TYPES_V2_6,
            }
        ok, kits = await with_client(
            env_id,
            "列全资源池",
            lambda c: c.query_app_dev_kits("", file_name=key_word, page_size=page_size),
        )
        if not ok:
            return kits
        normalized = []
        for k in (kits or []):
            if not isinstance(k, dict):
                continue
            ft = str(k.get("fileType") or "")
            if valid_filter and ft.upper() != valid_filter:
                continue
            normalized.append({
                "id": str(k.get("id") or ""),
                "fileName": str(k.get("fileName") or ""),
                "fileType": ft,
                "fileTypeLabel": _PLATFORM_FILE_TYPES_V2_6.get(ft.upper(), ""),
                "version": str(k.get("version") or ""),
                "userName": k.get("userName"),
                "createTime": k.get("createTime"),
            })
        return {
            "ok": True,
            "env_id": env_id,
            "kits": normalized,
            "total": len(normalized),
            "supported_file_types": _PLATFORM_FILE_TYPES_V2_6,
        }

    @mcp.tool()
    async def upload_external_zip_to_apaas(
        env_id: int,
        file_name: str,
        file_content_b64: str,
        file_type: str,
        description: str = "",
        apaas_app_id: str = "",
        tenant_id: int = 0,
        user_id: int = 0,
    ) -> dict:
        """直接上传一个外部 zip 到 aPaaS 平台。"""
        import base64 as _b64

        valid_ft = (file_type or "").strip().upper()
        if valid_ft not in _PLATFORM_FILE_TYPES_V2_6:
            return {
                "ok": False,
                "error_code": "INVALID_FILE_TYPE",
                "message": f"file_type '{file_type}' 不在 V2.6 全 12 类里",
                "supported_file_types": _PLATFORM_FILE_TYPES_V2_6,
            }
        fname = file_name.strip()
        if not fname or "/" in fname or "\\" in fname:
            return {
                "ok": False,
                "error_code": "INVALID_FILE_NAME",
                "message": "file_name 只能是文件名，不能含路径分隔符",
            }
        if not file_content_b64.strip():
            return {"ok": False, "error_code": "EMPTY_CONTENT", "message": "file_content_b64 不能为空"}
        try:
            zip_bytes = _b64.b64decode(file_content_b64, validate=False)
        except Exception as exc:
            return {"ok": False, "error_code": "B64_DECODE_FAILED", "message": str(exc)}
        if not zip_bytes.startswith(b"PK"):
            return {"ok": False, "error_code": "NOT_A_ZIP", "message": "解码后内容不是 zip（缺 PK 头）"}
        if len(zip_bytes) > 20 * 1024 * 1024:
            return {"ok": False, "error_code": "ZIP_TOO_LARGE", "message": f"zip {len(zip_bytes)} bytes > 20MB"}

        from app.coding.apaas_tools import _get_apaas_client, _relogin_apaas_env
        from app.database import AsyncSessionLocal
        from app.error_messages import is_apaas_token_error
        import httpx

        async with AsyncSessionLocal() as db:
            try:
                client = await _get_apaas_client(env_id, db)
            except Exception as exc:
                return {"ok": False, "error_code": "ENV_NOT_READY", "message": str(exc), "env_id": env_id}

            try:
                kits = await client.query_app_dev_kits("", file_name=fname.replace(".zip", ""))
            except Exception as exc:
                if is_apaas_token_error(str(exc)) and await _relogin_apaas_env(env_id, db):
                    try:
                        client = await _get_apaas_client(env_id, db)
                        kits = await client.query_app_dev_kits("", file_name=fname.replace(".zip", ""))
                    except Exception as exc2:
                        return {"ok": False, "error_code": "QUERY_FAILED", "message": str(exc2)}
                else:
                    return {"ok": False, "error_code": "QUERY_FAILED", "message": str(exc)}
            existing = next(
                (
                    k
                    for k in (kits or [])
                    if isinstance(k, dict) and (k.get("fileName") == fname)
                ),
                None,
            )
            action = "update" if existing else "create"
            existing_id = (existing or {}).get("id")

            ts = client._get_timestamp()
            upload_path = (
                "/xdap-app/selfdevelopment/update/developmentKit"
                if action == "update"
                else "/xdap-app/selfdevelopment/add/developmentKit"
            )
            url = f"{client.base_url}{upload_path}"
            form_data = {
                "fileName": fname,
                "fileType": valid_ft,
                "description": description or "",
            }
            if action == "update" and existing_id:
                form_data["id"] = str(existing_id)
            files = {"file": (fname, zip_bytes, "application/zip")}
            try:
                async with httpx.AsyncClient(verify=False, timeout=120.0) as h:
                    resp = await h.post(
                        url,
                        headers={k: v for k, v in client._get_headers().items() if k != "Content-Type"},
                        params={"timestamp": ts},
                        data=form_data,
                        files=files,
                    )
                    resp.raise_for_status()
                    data = resp.json()
            except Exception as exc:
                return {
                    "ok": False,
                    "error_code": "UPLOAD_FAILED",
                    "message": str(exc),
                    "action": action,
                }
            if data.get("code") not in ("ok", 200):
                return {
                    "ok": False,
                    "error_code": "APAAS_UPLOAD_REJECTED",
                    "message": data.get("message", "apaas 拒绝上传"),
                    "raw": data,
                }

            result = data.get("data") or {}
            new_kit_id = str(result.get("id") or existing_id or "")

            attached = False
            if apaas_app_id and new_kit_id:
                try:
                    await client.attach_apaas_source_relation(apaas_app_id, object_ids=[new_kit_id])
                    attached = True
                except Exception as exc:
                    logger.warning("auto attach failed: %s", exc)

        return {
            "ok": True,
            "env_id": env_id,
            "action": action,
            "kit_id": new_kit_id,
            "file_name": fname,
            "file_type": valid_ft,
            "size_bytes": len(zip_bytes),
            "attached_to_app": attached,
            "apaas_app_id": apaas_app_id or None,
            "message": (
                f"{'更新' if action == 'update' else '新建'} {fname} 成功"
                + (f"，已自动关联到应用 {apaas_app_id}（记得 republish_apaas_app 让组件生效）" if attached else "")
            ),
        }

    tools = {
        "list_dev_scenes": list_dev_scenes,
        "get_dev_scene_spec": get_dev_scene_spec,
        "get_dev_scene_full_workflow": get_dev_scene_full_workflow,
        "get_apaas_user_name": get_apaas_user_name,
        "enable_apaas_self_dev_config": enable_apaas_self_dev_config,
        "list_apaas_app_dev_kits": list_apaas_app_dev_kits,
        "attach_dev_packages_to_apaas_app": attach_dev_packages_to_apaas_app,
        "republish_apaas_app": republish_apaas_app,
        "create_apaas_self_dev_menu": create_apaas_self_dev_menu,
        "list_apaas_resource_pool_kits": list_apaas_resource_pool_kits,
        "upload_external_zip_to_apaas": upload_external_zip_to_apaas,
    }
    _registered_tools_by_mcp[marker] = tools
    return tools
