"""MCP tools for deployment history and self-development workspaces."""
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

_resolve_identity = None
_api_call = None
_api_call_sse_collect = None
_sign_service_token = None
_with_client = None
lint_apaas_backend_workspace = None

# ═══════════════════════════════════════════════════════════════════════════
# Batch 1: 应用部署 + 场景规范（4 工具）
# ═══════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def deploy_application(
    app_id: int,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """把 ai-builder 内 draft 应用首次部署到 aPaaS 平台（写入 apaas_app_id）。

    工作流：
      1) 内部调 SSE GET /applications/{app_id}/generate
      2) 触发 apaas_client.create_app 在 apaas 平台创建应用 → 拿 apaas_app_id
      3) 批量推送字段/模型/表单/权限到平台
      4) 完成后 apaas_app_id 已写入 + status=completed

    与 publish_application 区别：
      - 应用刚创建（apaas_app_id=null, status=draft）→ 必须先调 deploy_application
      - 已部署后改了配置 → 调 publish_application 升 version

    SSE generate 超时控制：25s 内拿不到 complete 事件 → 后台 task 继续跑，工具立即
    返 in_progress + polling_hint，避免 LLM gateway 30s timeout 拦截。
    """
    import asyncio as _asyncio
    tid, uid = _resolve_identity(tenant_id, user_id)
    if not app_id or app_id <= 0:
        return {"ok": False, "error_code": "INVALID_APP_ID", "message": "app_id 必填"}

    sse_token = _sign_service_token(uid, tid)
    FAST_RETURN_TIMEOUT = 25.0

    async def _run_full_sse() -> dict:
        # 2026-05-23 C 方案 B: 传 token_retry_app_id 让 SSE 撞 apaas token 过期时
        # 自动刷 token + 整段 stream 重跑. backend /generate handler 内已有
        # 'if not existing_apaas_app_id' 保护防 double create_app.
        return await _api_call_sse_collect(
            "GET",
            f"/applications/{app_id}/generate",
            tenant_id=tid,
            user_id=uid,
            params={"token": sse_token},
            timeout=600.0,
            token_retry_app_id=app_id,
        )

    sse_task = _asyncio.create_task(_run_full_sse())
    try:
        sse = await _asyncio.wait_for(_asyncio.shield(sse_task), timeout=FAST_RETURN_TIMEOUT)
    except _asyncio.TimeoutError:
        logger.info(
            "deploy_application app_id=%s SSE >%.0fs 未完成，后台继续跑，工具立即返 in_progress",
            app_id, FAST_RETURN_TIMEOUT,
        )
        return {
            "ok": True,
            "app_id": app_id,
            "status": "in_progress",
            "summary": (
                f"部署已启动，后台正在生成模型/表单/权限（generate 流 >{int(FAST_RETURN_TIMEOUT)}s 还在跑）。"
                f"⚠️ 这**还没生成完**。下一步：轮询 `get_application(app_id={app_id})` 直到 status='completed'"
                f"（不是 'generating'）才算就绪；大应用(多表单)可能要几分钟。status=generating 期间**别 publish、"
                f"也别跟用户说'已完成/已上线'**（提前 publish 会被后端拒：STILL_GENERATING）。"
            ),
            "polling_hint": {
                "next_tool": "get_application",
                "next_args": {"app_id": app_id},
                "wait_seconds": 20,
                "until": "status == 'completed'",
                "note": "别用 apaas_app_id 是否写入来判断完成——它生成早期就有了；只认 status='completed'。",
            },
        }

    if sse.get("errors"):
        return {
            "ok": False,
            "error_code": "DEPLOY_FAILED",
            "app_id": app_id,
            "message": sse["errors"][0],
            "all_errors": sse["errors"][:3],
        }

    completed = any(
        (e.get("data") or {}).get("type") == "complete" or e.get("event") == "done"
        for e in (sse.get("events") or [])
    )

    app_now = await _api_call("GET", f"/applications/{app_id}", tenant_id=tid, user_id=uid)
    apaas_app_id = (app_now or {}).get("apaas_app_id") or (app_now or {}).get("apaasAppId")
    status = (app_now or {}).get("status")
    apaas_admin_url = (app_now or {}).get("apaas_url")

    return {
        "ok": completed and bool(apaas_app_id),
        "app_id": app_id,
        "apaas_app_id": apaas_app_id,
        "status": status,
        "apaas_admin_url": apaas_admin_url,
        "events_count": len(sse.get("events") or []),
        "summary": (
            f"首次部署完成！apaas_app_id={apaas_app_id}。后台管理：{apaas_admin_url}"
            if completed and apaas_app_id
            else "部署未完整完成，请用 get_application 检查 apaas_app_id 和 status。"
        ),
    }

# 2026-05-24 Agent C + 主分支补齐: 部署历史 + 回滚 MCP 工具
@mcp.tool()
async def list_deploy_records(
    app_id: int,
    page: int = 1,
    page_size: int = 20,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """列指定 ai-builder 应用的部署历史 (含 deploy / publish / rollback 全周期记录).

    使用场景: 用户问 "这个应用部署过几次?" / "上次失败的部署详情" / 准备 rollback 前先看历史.

    返回结构: { total, page, page_size, items: [{id, version_label, status, deploy_type,
                 snapshot_version, snapshot_summary, error_message, created_at, completed_at}] }

    每条 record 含 snapshot_artifact_id 指向 SPEC 备份, status=success/failed/in_progress/rolled_back.
    """
    tid, uid = _resolve_identity(tenant_id, user_id)
    if not app_id or app_id <= 0:
        return {"ok": False, "error_code": "INVALID_APP_ID", "message": "app_id 必填"}
    try:
        result = await _api_call(
            "GET",
            f"/applications/{app_id}/deploy-records",
            tenant_id=tid,
            user_id=uid,
            params={"page": page, "page_size": page_size},
        )
        return {"ok": True, **(result if isinstance(result, dict) else {"items": result})}
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "DEPLOY_RECORDS_QUERY_FAILED",
            "message": f"查部署历史失败: {exc}",
            "app_id": app_id,
        }


@mcp.tool()
async def rollback_application(
    app_id: int,
    to_record_id: int,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """回滚 ai-builder 应用到指定历史部署记录的 SPEC 快照.

    用法:
      1. 先调 list_deploy_records(app_id) 找到要回滚到的那条 record_id
      2. 调本工具 rollback_application(app_id, to_record_id=N)
      3. 工具把那个 record 的 SPEC snapshot 写回 application.config_preview, 并插一条新 record
         deploy_type='rollback'
      4. **不直接重 deploy 到 apaas** (避免长 SSE 阻塞). 工具返 next_action 提示用户接下来要
         手动触发 deploy_application 重 deploy.

    返回 { ok, record_id, snapshot_version, message, next_action }.

    使用场景: 用户发现"刚才的 update 把应用搞坏了, 回到 30 分钟前那版" / 失败部署后回滚.
    """
    tid, uid = _resolve_identity(tenant_id, user_id)
    if not app_id or app_id <= 0:
        return {"ok": False, "error_code": "INVALID_APP_ID", "message": "app_id 必填"}
    if not to_record_id or to_record_id <= 0:
        return {"ok": False, "error_code": "INVALID_RECORD_ID", "message": "to_record_id 必填"}
    try:
        result = await _api_call(
            "POST",
            f"/applications/{app_id}/rollback",
            tenant_id=tid,
            user_id=uid,
            json_body={"to_record_id": to_record_id},
        )
        return {"ok": True, **(result if isinstance(result, dict) else {"result": result})}
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "ROLLBACK_FAILED",
            "message": f"回滚失败: {exc}",
            "app_id": app_id,
            "to_record_id": to_record_id,
        }

# ═══════════════════════════════════════════════════════════════════════════
# Batch 3: Workspace 自开发 11 工具
# 6 个 file/IDE 工具薄壳子（复用 coding/tools.py 已有 _read_file 等 executor）
# + 2 个 workspace 管理（create/status，调 internal /api/coding/workspace/* endpoint）
# + 3 个复杂 stub（save_dev_spec / import_zip / publish — 用 ai-builder UI 触发更稳）
# ═══════════════════════════════════════════════════════════════════════════


def _resolve_workspace_path(ws_id: str, tid: int, uid: int):
    """返回 (ws_path: Path, error_dict: None) 或 (None, error_dict)。

    严格校验：meta.tenant_id 必须匹配；个人 workspace（无 project_id）user_id
    也必须匹配，防止 li.l.77 操作 admin 的 workspace。
    """
    import json as _json
    from app.coding.workspace import WorkspaceManager
    ws_mgr = WorkspaceManager()
    try:
        ws_path = ws_mgr.get_workspace_path(ws_id)
    except FileNotFoundError:
        return None, {
            "ok": False, "error_code": "WORKSPACE_NOT_FOUND",
            "message": f"工作区 {ws_id} 不存在",
        }
    meta_path = ws_path / ".workspace.json"
    meta = {}
    if meta_path.exists():
        try:
            meta = _json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    meta_tid = meta.get("tenant_id")
    meta_uid = meta.get("user_id")
    project_id = meta.get("project_id")
    if meta_tid is not None and int(meta_tid) != int(tid):
        return None, {
            "ok": False, "error_code": "TENANT_MISMATCH",
            "message": f"工作区 {ws_id} 不属于当前租户（meta tenant_id={meta_tid}，your tenant_id={tid}）",
        }
    if project_id is None and meta_uid is not None and int(meta_uid) != int(uid):
        return None, {
            "ok": False, "error_code": "USER_MISMATCH",
            "message": f"工作区 {ws_id} 不属于当前用户",
        }
    return ws_path, None




@mcp.tool()
async def create_dev_workspace(
    scene_type: str,
    project_name: str,
    display_name: str = "",
    initial_requirement: str = "",
    env_id: int = 0,
    apaas_app_id: str = "",
    apaas_app_name: str = "",
    project_id: int = 0,
    confirmed: bool = False,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """在 ai-builder /coding 下创建一个自开发 workspace（脚手架已就位、可以开始写代码）。

    内部调本机 POST /api/coding/workspace/create — 脚手架由 df-apaas-cli 拉模板，
    所有 .cursor/rules/*.mdc 默认规则文件已经被复制到工作区。

    入参：
        scene_type           list_dev_scenes 返回的 scene_type
        project_name         英文短名（kebab-case），如 "form-page-home-dashboard"
        display_name         中文名（用户看得到的标题）
        initial_requirement  跟用户对齐好的需求 brief（200-2000 字），自动喂给 vibe_agent
        project_id           可选：AI Builder 本地 applications.id，用于把 workspace 绑定回应用资产
        env_id               可选；传了会先查 aPaaS 自开发资源池是否已有同名包
        confirmed            命中重复包/菜单后，用户确认继续时传 true

    返回：{ok, ws_id, scene_type, project_name, display_name}
    """
    from app.dev_scene_spec import all_scene_types
    from app.coding.workspace import ProjectType, WorkspaceManager
    if scene_type not in all_scene_types():
        return {
            "ok": False, "error_code": "SCENE_NOT_FOUND",
            "message": f"未知 scene_type: {scene_type}",
            "valid_scene_types": all_scene_types(),
        }
    if not project_name.strip():
        return {"ok": False, "error_code": "INVALID_PROJECT_NAME", "message": "project_name 不能为空"}

    tid, uid = _resolve_identity(tenant_id, user_id)
    final_display_name = (display_name or "").strip() or project_name.strip()

    def _expected_self_dev_names() -> dict[str, Any]:
        try:
            project_type = ProjectType(scene_type)
            safe_name = WorkspaceManager()._normalize_project_name(project_type, project_name.strip())
        except Exception:
            safe_name = project_name.strip()
        short_name = safe_name
        for prefix in ("form-page-", "form-component-", "form-view-", "form-layout-", "frontend-plugin-"):
            if short_name.startswith(prefix):
                short_name = short_name[len(prefix):]
                break
        file_names = [f"{safe_name}.zip"]
        if scene_type == "form-component-dual":
            file_names.append(f"{safe_name}-m.zip")
        register_name = f"apaas-custom-{short_name}" if scene_type in ("form-page", "menu-page", "mobile-page") else ""
        return {
            "project_name": safe_name,
            "short_name": short_name,
            "file_names": file_names,
            "register_name": register_name,
        }

    def _english_terms(text: str) -> set[str]:
        import re as _re
        normalized = (text or "").lower()
        normalized = normalized.replace(".zip", " ")
        for prefix in ("apaas-custom-", "form-page-", "form-component-", "form-view-", "form-layout-", "frontend-plugin-"):
            normalized = normalized.replace(prefix, " ")
        tokens = set(_re.findall(r"[a-z0-9]{2,}", normalized))
        stop = {
            "apaas", "custom", "form", "page", "component", "view", "layout",
            "frontend", "plugin", "mobile", "web", "self", "dev", "zip",
        }
        return {token for token in tokens if token not in stop}

    def _compact_text(text: str) -> str:
        import re as _re
        return _re.sub(r"\s+", "", (text or "").lower())

    def _similarity(a: str, b: str) -> float:
        from difflib import SequenceMatcher
        left = _compact_text(a)
        right = _compact_text(b)
        if not left or not right:
            return 0.0
        return SequenceMatcher(None, left, right).ratio()

    def _requirement_aliases(expected: dict[str, Any]) -> dict[str, Any]:
        requirement_text = initial_requirement or ""
        english_source = " ".join([
            expected["project_name"], expected["short_name"], final_display_name, requirement_text,
        ])
        return {
            "english_terms": _english_terms(english_source),
            "display_name": final_display_name,
            "requirement": requirement_text,
        }

    def _package_conflict(kit: dict[str, Any], expected: dict[str, Any], aliases: dict[str, Any]) -> dict[str, Any] | None:
        file_name = str(kit.get("fileName") or "")
        description = " ".join(
            str(kit.get(key) or "")
            for key in ("description", "desc", "remark", "name", "resourceName", "componentLabel")
        )
        candidate_text = f"{file_name} {description}"
        reasons: list[str] = []
        matched_terms: list[str] = []
        score = 0.0

        if file_name in set(expected["file_names"]):
            reasons.append("exact_file_name")
            score = max(score, 1.0)
        elif expected["project_name"] and expected["project_name"] in file_name:
            reasons.append("project_name_contains")
            score = max(score, 0.9)

        display_name_value = aliases["display_name"]
        requirement_text = aliases["requirement"]
        compact_candidate = _compact_text(candidate_text)
        if display_name_value and _compact_text(display_name_value) in compact_candidate:
            reasons.append("display_name_in_package_metadata")
            score = max(score, 0.85)
        if requirement_text and description and (
            _compact_text(display_name_value) in _compact_text(requirement_text)
            and _compact_text(display_name_value) in _compact_text(description)
        ):
            reasons.append("requirement_display_name_matches_package_metadata")
            score = max(score, 0.85)

        candidate_terms = _english_terms(candidate_text)
        shared_terms = sorted(aliases["english_terms"] & candidate_terms)
        if len(shared_terms) >= 2:
            matched_terms.extend(shared_terms)
            overlap_score = min(0.84, 0.45 + 0.13 * len(shared_terms))
            reasons.append("english_requirement_terms_overlap")
            score = max(score, overlap_score)

        if not reasons:
            return None
        return {
            "id": str(kit.get("id") or ""),
            "fileName": file_name,
            "fileType": str(kit.get("fileType") or ""),
            "createTime": kit.get("createTime"),
            "score": round(score, 2),
            "reasons": reasons,
            "matched_terms": matched_terms[:8],
        }

    def _menu_conflict(node: dict[str, Any], expected: dict[str, Any], aliases: dict[str, Any]) -> dict[str, Any] | None:
        menu_name = str(node.get("menuName") or node.get("menu_name") or node.get("name") or "")
        link_url = str(node.get("linkUrl") or node.get("link_url") or "")
        reasons: list[str] = []
        matched_terms: list[str] = []
        score = 0.0
        display_name_value = aliases["display_name"]
        requirement_text = aliases["requirement"]

        if display_name_value and menu_name == display_name_value:
            reasons.append("exact_menu_name")
            score = max(score, 1.0)
        elif display_name_value and (
            _compact_text(display_name_value) in _compact_text(menu_name)
            or _compact_text(menu_name) in _compact_text(display_name_value)
        ):
            reasons.append("menu_name_contains_display_name")
            score = max(score, 0.9)
        elif display_name_value and _similarity(display_name_value, menu_name) >= 0.72:
            reasons.append("menu_name_similar_to_display_name")
            score = max(score, 0.78)

        if expected["register_name"] and link_url == expected["register_name"]:
            reasons.append("exact_register_name")
            score = max(score, 1.0)

        if requirement_text and menu_name and len(_compact_text(menu_name)) >= 4:
            compact_req = _compact_text(requirement_text)
            compact_menu = _compact_text(menu_name)
            if compact_menu in compact_req:
                reasons.append("menu_name_in_requirement")
                score = max(score, 0.9)
            elif display_name_value and _compact_text(display_name_value) in compact_req and _similarity(display_name_value, menu_name) >= 0.72:
                reasons.append("requirement_display_name_similar_to_menu")
                score = max(score, 0.78)

        candidate_terms = _english_terms(f"{menu_name} {link_url}")
        shared_terms = sorted(aliases["english_terms"] & candidate_terms)
        if len(shared_terms) >= 2:
            matched_terms.extend(shared_terms)
            reasons.append("english_requirement_terms_overlap")
            score = max(score, min(0.82, 0.45 + 0.13 * len(shared_terms)))

        if not reasons:
            return None
        return {
            "menu_id": str(node.get("id") or node.get("menuId") or node.get("menu_id") or ""),
            "menu_name": menu_name,
            "link_url": link_url,
            "menu_type": str(node.get("menuType") or node.get("menu_type") or ""),
            "score": round(score, 2),
            "reasons": reasons,
            "matched_terms": matched_terms[:8],
        }

    if env_id and not confirmed:
        expected = _expected_self_dev_names()
        aliases = _requirement_aliases(expected)

        async def _find_conflicts(client):
            package_hits: list[dict[str, Any]] = []
            try:
                kits = await client.query_app_dev_kits("", file_name="", page_size=200)
            except TypeError:
                kits = await client.query_app_dev_kits("", file_name="")
            for kit in kits or []:
                if not isinstance(kit, dict):
                    continue
                conflict = _package_conflict(kit, expected, aliases)
                if conflict:
                    package_hits.append(conflict)
            package_hits.sort(key=lambda item: item.get("score", 0), reverse=True)
            package_hits = package_hits[:10]

            menu_hits: list[dict[str, Any]] = []
            if apaas_app_id.strip():
                menus = await client.query_menus(apaas_app_id.strip())

                def _walk(nodes):
                    for node in nodes or []:
                        if not isinstance(node, dict):
                            continue
                        conflict = _menu_conflict(node, expected, aliases)
                        if conflict:
                            menu_hits.append(conflict)
                        _walk(node.get("submenus") or node.get("children") or [])

                _walk(menus or [])
            menu_hits.sort(key=lambda item: item.get("score", 0), reverse=True)
            menu_hits = menu_hits[:10]
            return {"packages": package_hits, "menus": menu_hits}

        ok_conflicts, conflicts = await _with_client(env_id, "检查自开发包重复", _find_conflicts)
        if not ok_conflicts:
            return conflicts
        package_hits = (conflicts or {}).get("packages") or []
        menu_hits = (conflicts or {}).get("menus") or []
        if package_hits or menu_hits:
            return {
                "ok": False,
                "error_code": "NEEDS_CONFIRMATION",
                "requires_user_confirmation": True,
                "message": (
                    "检测到可能重复的自开发包或菜单。请先向用户确认：是更新这些已有资源，"
                    "还是换一个新的项目名/菜单名后再创建。确认更新已有资源后，可重新调用并传 confirmed=true。"
                ),
                "candidate": expected,
                "duplicate_packages": package_hits,
                "duplicate_menus": menu_hits,
                "next_options": [
                    "用户确认更新已有资源：沿用 candidate.project_name / candidate.file_names / candidate.register_name，重新调用 create_dev_workspace(..., confirmed=true)，后续上传会按同名 fileName 走 update/developmentKit",
                    "用户要新建独立包：换一个新的 project_name/display_name，确保生成新的 fileName / register_name 后再调用",
                ],
            }

    # /coding/workspace/create 实际签名 (CreateWorkspaceRequest):
    #   project_type / project_name / display_name (可选) / project_id (可选)
    # 不接 initial_requirement / apaas_app_id / apaas_app_name —— 这些是工具层语义参数。
    payload = {
        "project_type": scene_type,  # scene_type 跟 ProjectType 枚举值一致
        "project_name": project_name.strip(),
        "display_name": final_display_name,
    }
    if project_id:
        payload["project_id"] = int(project_id)
    res = await _api_call("POST", "/coding/workspace/create", tenant_id=tid, user_id=uid, json_body=payload)
    ws_id = (res or {}).get("ws_id") or (res or {}).get("id") or (res or {}).get("workspace_id")
    if isinstance(res, dict) and ws_id:
        return {
            "ok": True,
            "ws_id": ws_id,
            "scene_type": scene_type,
            "project_name": project_name.strip(),
            "display_name": display_name or project_name,
            "tenant_id": tid,
            "user_id": uid,
            "project_id": project_id or None,
            "next_steps": [
                f"用 get_dev_workspace_status('{ws_id}') 查工作区状态",
                "用 read_workspace_file / write_workspace_files / edit_workspace_files 写代码",
                "完成后 run_workspace_command('npm run build') + publish_dev_workspace",
            ],
            "note_unused_args": (
                "initial_requirement / apaas_app_id / apaas_app_name 这次未传给底层 endpoint"
                "（当前 /coding/workspace/create 不接这些字段）；如需要让 vibe_agent "
                "拿到 brief，请 workspace 创建后用 write_workspace_files 写 .coding-pending-requirement.txt"
                if (initial_requirement or apaas_app_id or apaas_app_name) else None
            ),
        }
    return {"ok": False, "error_code": "CREATE_FAILED", "message": "create_workspace 返回异常", "raw": res}


@mcp.tool()
async def save_dev_spec(
    ws_id: str,
    project_name: str,
    spec_md: str,
    mockup_html: str = "",
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """Phase 1 必调：落盘双产物（技术 SPEC + 业务可视 HTML mockup）到 workspace。

    落到 workspace `.dev-spec/<project_name>/` 目录：
      spec.md      技术 SPEC（给 LLM 看，含 form_id / tab_id / uuid 真值）
      mockup.html  业务可视 HTML mockup（给用户审，单文件 CDN 引 echarts/element-ui）

    流程：
      1. 调元数据工具拿完 form_views / form_components 等
      2. 写 spec_md（技术）和 mockup_html（业务，看板/列表场景必填）
      3. 调本工具一次落两份盘
      4. 给用户业务摘要 + spec_md 关键片段（用 markdown 代码块展示）
      5. 等用户表态 OK 后继续 write_workspace_files 写代码

    入参：
      ws_id         AI Coding workspace ID（'X_xxx' 格式）
      project_name  英文短名（kebab-case），决定 .dev-spec 子目录
      spec_md       技术 SPEC markdown（至少 100 字符）
      mockup_html   业务 HTML（可选；看板类强烈建议）

    返回 {ok, ws_id, project_name, spec_path, mockup_path?, preview_path}
    """
    import re as _re
    from pathlib import Path
    if not _re.match(r"^[a-zA-Z0-9_\-]+$", project_name):
        return {"ok": False, "error_code": "INVALID_PROJECT_NAME",
                "message": "project_name 只能含 字母/数字/_/-"}
    if not spec_md or len(spec_md.strip()) < 100:
        return {"ok": False, "error_code": "SPEC_TOO_SHORT",
                "message": f"spec_md 太短 ({len(spec_md.strip())} 字符)，至少 100 字符"}
    tid, uid = _resolve_identity(tenant_id, user_id)

    from app.coding.workspace import WorkspaceManager
    try:
        repo_dir = WorkspaceManager().get_workspace_path(ws_id)
    except FileNotFoundError:
        return {"ok": False, "error_code": "WORKSPACE_NOT_FOUND",
                "message": f"workspace {ws_id} 找不到"}

    spec_root = repo_dir / ".dev-spec" / project_name
    spec_root.mkdir(parents=True, exist_ok=True)
    spec_path = spec_root / "spec.md"
    spec_path.write_text(spec_md, encoding="utf-8")

    out: dict[str, Any] = {
        "ok": True,
        "ws_id": ws_id,
        "project_name": project_name,
        "spec_path": f".dev-spec/{project_name}/spec.md",
        "spec_bytes": len(spec_md.encode("utf-8")),
        "preview_path": f".dev-spec/{project_name}/",
        "next_steps": [
            "用 read_workspace_file 读 .dev-spec/<project>/spec.md 拿回内容（供下次迭代）",
            "在 chat 里给用户业务摘要 + 等用户确认",
            "确认后 → write_workspace_files 开始写代码",
        ],
    }
    if mockup_html.strip():
        mockup_path = spec_root / "mockup.html"
        mockup_path.write_text(mockup_html, encoding="utf-8")
        out["mockup_path"] = f".dev-spec/{project_name}/mockup.html"
        out["mockup_bytes"] = len(mockup_html.encode("utf-8"))
        out["has_mockup"] = True
    return out


@mcp.tool()
async def publish_dev_workspace(
    ws_id: str,
    env_id: int,
    skip_lint: bool = False,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """把 AI Coding workspace build 产物部署到 aPaaS 平台。

    内部调 POST /coding/workspace/{ws_id}/upload-to-platform，
    后端自动：build → 打 zip → upload to apaas → 查重判 update/create。
    上传成功后再用 attach_dev_packages_to_apaas_app + republish_apaas_app 让组件生效。

    ⚠️ 仅支持 AI Coding workspace（'X_xxx' 格式）。Vibe Coding workspace ('oc_xxx') 不绑
    aPaaS 平台，无需 publish；如需上传到 apaas 应自己用 run_workspace_command 打 zip
    再用 upload_external_zip_to_apaas（实现中）。

    入参：
      ws_id     AI Coding workspace ID (不以 'oc_' 开头)
      env_id    平台环境 ID（apaas 部署目标）
      skip_lint 默认 false — publish 前先 lint，发现 fatal 问题就拒绝上传；
                改 true 跳过 lint 强发（不推荐）

    返回 internal endpoint 原样响应 — 含 uploaded_kits / errors 等
    """
    if ws_id.startswith("oc_"):
        return {"ok": False, "error_code": "WRONG_WS_TYPE",
                "message": "publish_dev_workspace 只支持 AI Coding workspace（非 oc_ 前缀）。"
                           "Vibe workspace 请自己 zip + 用 upload_external_zip_to_apaas"}
    if not env_id:
        return {"ok": False, "error_code": "INVALID_ENV_ID", "message": "env_id 必填"}

    tid, uid = _resolve_identity(tenant_id, user_id)

    # 上传前 lint 预检 — 防止把含 fatal 坑的代码发出去
    if not skip_lint:
        try:
            lint_res = await lint_apaas_backend_workspace(
                ws_id=ws_id, tenant_id=tid, user_id=uid,
            )
        except Exception as exc:
            # lint 自身崩了 — 提示但不拦截
            lint_res = {
                "ok": False, "files_scanned": -1,
                "lint_internal_error": str(exc),
            }
        if lint_res.get("files_scanned", 0) > 0 and lint_res.get("fatal_count", 0) > 0:
            return {
                "ok": False, "error_code": "LINT_FAILED_BEFORE_PUBLISH",
                "message": (f"lint 发现 {lint_res['fatal_count']} 个 fatal 问题，"
                            f"先修了再发；想强发请传 skip_lint=true（不推荐）"),
                "lint_findings": [f for f in lint_res.get("findings", [])
                                  if f.get("severity") == "fatal"][:20],
                "hint": "调 lint_apaas_backend_workspace 看全部 findings 详情",
            }

    try:
        res = await _api_call(
            "POST", f"/coding/workspace/{ws_id}/upload-to-platform",
            tenant_id=tid, user_id=uid, json_body={"env_id": env_id},
            timeout=600.0,  # build + upload 可能耗时
        )
    except Exception as exc:
        # _api_call HTTP 4xx/5xx 时 raise — detail 里可能含 build / upload 失败原因，
        # 按关键词分类成 error_code 让 agent 知道下一步做什么。
        detail = str(exc)
        return _classify_publish_failure(ws_id, env_id, detail)

    if isinstance(res, dict):
        return {"ok": True, "ws_id": ws_id, "env_id": env_id, **res}
    return {"ok": False, "error_code": "UPLOAD_FAILED", "raw": res}


def _classify_publish_failure(ws_id: str, env_id: int, detail: str) -> dict:
    """publish 失败时按 detail 字符串里的 keyword 分类。

    跟 workspace.diagnose_build_failure 的 error_code 对齐 — agent 拿到同一套码可
    决定动作（去查 settings.xml / 改 JDK / 调 doctor / 调 lint 等）。
    """
    d = detail or ""
    error_code, hint = "UPLOAD_FAILED", None

    if "401 Unauthorized" in d or "Authentication failed" in d:
        error_code = "MVN_AUTH_FAIL"
        hint = "Maven Nexus 认证失败 — 调 doctor_apaas_backend_workspace 看 settings.xml 配置"
    elif "Could not resolve dependencies" in d or "Could not find artifact" in d:
        error_code = "MVN_DEPS_RESOLVE_FAIL"
        hint = "依赖拉不到 — 调 doctor_apaas_backend_workspace 排查 pom <repositories> + settings.xml"
    elif "The requested profile" in d and "could not be activated" in d:
        error_code = "MVN_PROFILE_NOT_FOUND"
        hint = "-P lib profile 不存在 — 调 init_apaas_backend_workspace 重写 pom"
    elif "source release" in d and "requires target release" in d:
        error_code = "MVN_JDK_MISMATCH"
        hint = "JDK 版本不匹配 — 检查 APAAS_BACKEND_JDK_VERSION / JAVA_HOME，并调 doctor_apaas_backend_workspace"
    elif ("COMPILATION ERROR" in d or "cannot find symbol" in d
            or "package does not exist" in d):
        error_code = "MVN_COMPILE_FAIL"
        hint = "Java 编译错 — 先调 lint_apaas_backend_workspace 看代码问题"
    elif "BUILD FAILURE" in d or "Failed to execute goal" in d:
        error_code = "MVN_BUILD_FAILURE"
        hint = "Maven BUILD FAILURE — 调 doctor_apaas_backend_workspace 排查环境配置"
    elif "Failed to compile" in d or "[eslint]" in d:
        error_code = "FE_COMPILE_FAIL"
        hint = "前端编译失败 — 看 eslint / TS 错"
    elif "构建失败" in d:
        error_code = "BUILD_FAILED"
        hint = "构建失败但未识别具体原因 — 调 doctor 体检 + 看 backend log 完整错"

    return {
        "ok": False,
        "error_code": error_code,
        "ws_id": ws_id,
        "env_id": env_id,
        "message": detail[:1000],
        "hint": hint,
        "next_step": (
            "调 doctor_apaas_backend_workspace 看打包前置问题；"
            "调 lint_apaas_backend_workspace 看代码问题；"
            "都没问题再看 backend log /tmp/apaas-backend.log 完整错"
        ),
    }


def register(
    mcp,
    resolve_identity,
    api_call,
    api_call_sse_collect,
    sign_service_token,
    with_client,
    lint_backend_workspace,
):
    global _resolve_identity, _api_call, _api_call_sse_collect, _sign_service_token
    global _with_client, lint_apaas_backend_workspace
    _resolve_identity = resolve_identity
    _api_call = api_call
    _api_call_sse_collect = api_call_sse_collect
    _sign_service_token = sign_service_token
    _with_client = with_client
    lint_apaas_backend_workspace = lint_backend_workspace
    tools = [
        deploy_application,
        list_deploy_records,
        rollback_application,
        create_dev_workspace,
        save_dev_spec,
        publish_dev_workspace,
    ]
    for tool in tools:
        mcp.tool()(tool)
    return {tool.__name__: tool for tool in tools}
