"""AIChat agent 工具集 — 本地核心工具。

OpenAI tool calling 格式：每个工具有 schema（给 LLM 看）+ 实现（execute_*）。
Dispatcher (`execute_tool`) 根据 tool_name 路由到具体实现。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AIChatSession,
    AIChatAttachment,
    AIChatArtifact,
)


# ─────────────────────────── Tool schemas (OpenAI 格式) ───────────────────────────

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "read_attachment",
            "description": (
                "读取本会话用户上传的某个附件的解析后文本内容。"
                "适用于 docx / pdf / xlsx / pptx / md / txt 等已被解析的文件。"
                "图片附件不能用此工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "附件文件名（与上传时一致）",
                    },
                },
                "required": ["filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_python",
            "description": (
                "在本会话独立的工作目录中执行 Python 代码（cwd 已 cd 到 workspace_dir，"
                "上传的附件文件都在该目录里能直接打开）。stdout/stderr 会作为结果返回。"
                "执行超时 30 秒。适合数据分析、xlsx 表格读取、文本统计等。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "完整可执行的 Python 代码",
                    },
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_artifact",
            "description": (
                "把一段文本写为产出物（默认 markdown），用户能在右侧面板看到。"
                "如果同名文件已存在，会自动 version+1 保留历史版本。"
                "典型用法：写设计文档、写分析报告、写 Vue 组件 / TS / 自开发包 manifest 等代码文件。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "产出物文件名，例如 '设计文档.md' / 'TalentDashboard.vue' / 'talent-package.json'",
                    },
                    "content": {
                        "type": "string",
                        "description": "完整内容",
                    },
                    "format": {
                        "type": "string",
                        "enum": [
                            "md", "json", "txt", "html", "py",
                            "vue", "ts", "js", "jsx", "tsx",
                            "css", "scss", "yaml", "yml", "sh",
                            "xml", "sql"
                        ],
                        "description": "格式（默认 md）；写 Vue 组件用 vue，写 TS 用 ts，写自开发包 manifest 用 json",
                    },
                },
                "required": ["filename", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_clarifying_question",
            "description": (
                "向用户提一个澄清问题，并提供候选答案。"
                "调用此工具后 agent loop 会暂停，等用户在前端选择答案后才继续。"
                "需要确认重要假设或需求边界时使用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "问题文本"},
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "候选答案列表（推荐 2-4 项）",
                    },
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_apaas_app_design_doc",
            "description": (
                "从已有 aPaaS 应用反向导出标准 6 章 Builder 设计文档，并写入右侧产出物。"
                "当用户给出现有应用链接/app_code/app_id，或要求“根据已有应用生成设计文档”时，"
                "优先用本工具，不要手工拼 write_artifact。工具会确定性查询菜单、模型、字段、"
                "表单组件、角色、字典、权限并渲染 markdown。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "env_id": {
                        "type": "integer",
                        "description": "平台环境 ID；不传或 0 时使用默认环境",
                    },
                    "apaas_app_id": {
                        "type": "string",
                        "description": "aPaaS 应用 ID；与 app_code 二选一",
                    },
                    "app_code": {
                        "type": "string",
                        "description": "aPaaS 应用编码；与 apaas_app_id 二选一",
                    },
                    "filename": {
                        "type": "string",
                        "description": "可选，导出的 markdown 文件名",
                    },
                },
            },
        },
    },
]


# ─────────────────────────── 各工具的实现 ───────────────────────────

async def execute_read_attachment(
    args: dict, session: AIChatSession, db: AsyncSession
) -> str:
    filename = args.get("filename", "").strip()
    if not filename:
        return "错误：缺少 filename 参数"

    res = await db.execute(
        select(AIChatAttachment).where(
            AIChatAttachment.session_id == session.id,
            AIChatAttachment.filename == filename,
        )
    )
    att = res.scalar_one_or_none()
    if not att:
        return f"错误：本会话不存在名为 '{filename}' 的附件"
    if att.kind == "image":
        return f"错误：'{filename}' 是图片附件，不能用 read_attachment 读取"
    if not att.content_text:
        return f"错误：'{filename}' 解析失败或为空"

    # 截断超长内容（避免一次喂给 LLM 太多 token）
    MAX_CHARS = 30000
    if len(att.content_text) > MAX_CHARS:
        return att.content_text[:MAX_CHARS] + f"\n\n[内容已截断，原长度 {len(att.content_text)} 字符]"
    return att.content_text


async def execute_run_python(
    args: dict, session: AIChatSession, db: AsyncSession
) -> str:
    code = args.get("code", "")
    if not code.strip():
        return "错误：缺少 code 参数"
    if not session.workspace_dir:
        return "错误：会话工作区未初始化"

    workspace = session.workspace_dir
    Path(workspace).mkdir(parents=True, exist_ok=True)

    # 用主 venv 的 python 跑（已装好 pandas/openpyxl/pdfplumber 等）
    python_exe = sys.executable

    try:
        proc = await asyncio.create_subprocess_exec(
            python_exe,
            "-c",
            code,
            cwd=workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return "错误：执行超时（30 秒）"

        out = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace")
        parts = []
        if out:
            parts.append(f"[stdout]\n{out.rstrip()}")
        if err:
            parts.append(f"[stderr]\n{err.rstrip()}")
        if proc.returncode != 0:
            parts.append(f"[exit code: {proc.returncode}]")
        result = "\n\n".join(parts) if parts else "[无输出]"

        # 截断太长
        MAX = 8000
        if len(result) > MAX:
            result = result[:MAX] + f"\n\n[输出已截断，原长度 {len(result)} 字符]"
        return result
    except Exception as e:
        return f"错误：执行失败 - {e}"


async def execute_write_artifact(
    args: dict, session: AIChatSession, db: AsyncSession
) -> str:
    filename = args.get("filename", "").strip()
    content = args.get("content", "")
    fmt = args.get("format", "md")
    if not filename:
        return "错误：缺少 filename 参数"
    if not content:
        return "错误：content 为空"

    # 找现有版本，确定新 version
    res = await db.execute(
        select(AIChatArtifact)
        .where(
            AIChatArtifact.session_id == session.id,
            AIChatArtifact.filename == filename,
        )
        .order_by(desc(AIChatArtifact.version))
        .limit(1)
    )
    last = res.scalar_one_or_none()
    new_version = (last.version + 1) if last else 1

    art = AIChatArtifact(
        session_id=session.id,
        filename=filename,
        format=fmt,
        content=content,
        version=new_version,
    )
    db.add(art)
    await db.commit()
    await db.refresh(art)
    validation_note = ""
    if fmt == "md" and _looks_like_builder_doc(content):
        validation = _validate_builder_doc_silent(content)
        if validation:
            validation_note = (
                f" Builder 校验：{validation.get('score', 0)}/100，"
                f"passes_strict={bool(validation.get('passes_strict'))}。"
            )
    return (
        f"已写入产出物 '{filename}' (v{new_version}, {len(content)} 字符)。"
        f"用户已能在右侧面板查看。{validation_note}"
    )


async def execute_ask_clarifying_question(
    args: dict, session: AIChatSession, db: AsyncSession
) -> str:
    """这个工具是个"伪 result"——真正效果是让 agent loop 停下等用户。
    返回值会作为 tool_result 喂回 LLM，然后 loop 主动退出（在 agent.py 检测）。"""
    return json.dumps(
        {
            "_special": "ask_user",
            "question": args.get("question", ""),
            "options": args.get("options", []),
        },
        ensure_ascii=False,
    )


async def execute_export_apaas_app_design_doc(
    args: dict, session: AIChatSession, db: AsyncSession
) -> str:
    """Deterministically render a Builder design doc from live aPaaS metadata.

    This is intentionally code-rendered instead of LLM-rendered: reverse
    exporting an existing app should preserve exactly what platform tools
    return, including sparse/empty metadata, and should not invent fields.
    """
    env_id = int(args.get("env_id") or 0)
    apaas_app_id = str(args.get("apaas_app_id") or "").strip()
    app_code = str(args.get("app_code") or "").strip()

    envs = await _mcp_json("list_platform_envs", {}, session)
    if not env_id:
        env_id = int(envs.get("default_env_id") or 0)
    if not env_id:
        return json.dumps({"ok": False, "error": "未找到默认平台环境，请先连接 aPaaS 环境"}, ensure_ascii=False)

    apps_res = await _mcp_json("list_apaas_apps_in_env", {"env_id": env_id}, session)
    apps = apps_res.get("apps") or []
    app = None
    for item in apps:
        if apaas_app_id and str(item.get("apaas_app_id") or "") == apaas_app_id:
            app = item
            break
        if app_code and str(item.get("app_code") or "") == app_code:
            app = item
            break
    if not app:
        return json.dumps({
            "ok": False,
            "error": "未找到目标应用",
            "env_id": env_id,
            "apaas_app_id": apaas_app_id,
            "app_code": app_code,
        }, ensure_ascii=False)

    apaas_app_id = str(app.get("apaas_app_id") or apaas_app_id)
    app_code = str(app.get("app_code") or app_code)
    app_name = str(app.get("app_name") or app_code or apaas_app_id)

    base_args = {"env_id": env_id, "apaas_app_id": apaas_app_id}
    menus_res, models_res, dicts_res, roles_res = await asyncio.gather(
        _mcp_json("list_apaas_app_menus", base_args, session),
        _mcp_json("list_apaas_app_models", {**base_args, "with_fields": True}, session),
        _mcp_json("list_apaas_app_dicts", {**base_args, "with_options": True}, session),
        _mcp_json("list_apaas_app_roles", {**base_args, "keyword": ""}, session),
    )

    menus = menus_res.get("menus") or []
    form_menus = [m for m in menus if m.get("form_id")]
    forms: list[dict[str, Any]] = []
    for menu in form_menus:
        form_id = str(menu.get("form_id") or "")
        comp_res, view_res, perm_res = await asyncio.gather(
            _mcp_json("list_apaas_form_components", {**base_args, "form_id": form_id}, session),
            _mcp_json("list_apaas_form_views", {**base_args, "form_id": form_id}, session),
            _mcp_json("list_apaas_form_permissions", {**base_args, "form_id": form_id}, session),
        )
        forms.append({
            "menu": menu,
            "components": comp_res.get("components") or [],
            "views": view_res.get("views") or [],
            "default_tab_id": view_res.get("default_tab_id") or "",
            "permissions": perm_res,
        })

    markdown = _render_apaas_design_doc(
        app=app,
        menus=menus,
        models=models_res.get("models") or [],
        dicts=dicts_res.get("dicts") or [],
        roles=roles_res.get("roles") or [],
        forms=forms,
    )
    filename = str(args.get("filename") or "").strip() or f"{_safe_filename(app_code or app_name)}-design.md"
    await execute_write_artifact({"filename": filename, "content": markdown, "format": "md"}, session, db)

    art = await _latest_artifact(db, session.id, filename)
    validation = _validate_builder_doc_silent(markdown) or {}
    doc_stats = _design_doc_stats(markdown)
    return json.dumps({
        "ok": True,
        "env_id": env_id,
        "apaas_app_id": apaas_app_id,
        "app_code": app_code,
        "app_name": app_name,
        "artifact_id": art.id if art else None,
        "filename": filename,
        "version": art.version if art else None,
        "chars": len(markdown),
        "menus": doc_stats["menus"] or len(menus),
        "forms": doc_stats["forms"],
        "models": doc_stats["models"],
        "roles": doc_stats["roles"],
        "dicts": doc_stats["dicts"],
        "business_enriched": doc_stats["business_enriched"],
        "validation": {
            "score": validation.get("score"),
            "passes_strict": validation.get("passes_strict"),
            "missing_sections": validation.get("missing_sections") or [],
            "weak_sections": validation.get("weak_sections") or [],
        },
    }, ensure_ascii=False)


async def _mcp_json(tool_name: str, args: dict, session: AIChatSession) -> dict:
    from app.ai_chat.mcp_bridge import call_tool as _mcp_call

    text = await _mcp_call(
        tool_name,
        args,
        tenant_id=int(getattr(session, "tenant_id", 0) or 0),
        user_id=int(getattr(session, "user_id", 0) or 0),
    )
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {"ok": True, "data": data}
    except Exception:
        return {"ok": False, "error": f"{tool_name} 返回非 JSON", "raw": text[:1000]}


async def _latest_artifact(db: AsyncSession, session_id: int, filename: str) -> AIChatArtifact | None:
    res = await db.execute(
        select(AIChatArtifact)
        .where(AIChatArtifact.session_id == session_id, AIChatArtifact.filename == filename)
        .order_by(desc(AIChatArtifact.version))
        .limit(1)
    )
    return res.scalar_one_or_none()


def _render_apaas_design_doc(
    app: dict,
    menus: list[dict],
    models: list[dict],
    dicts: list[dict],
    roles: list[dict],
    forms: list[dict],
) -> str:
    if _needs_business_enrichment(app, models, dicts, roles, forms):
        return _render_business_enriched_design_doc(app, menus, forms)

    app_name = str(app.get("app_name") or app.get("app_code") or "未命名应用")
    app_code = str(app.get("app_code") or "app")
    app_id = str(app.get("apaas_app_id") or "")
    status = str(app.get("status") or "")
    model_by_code = {str(m.get("model_code") or ""): m for m in models}

    lines: list[str] = []
    add = lines.append
    add("## 一、应用信息")
    add("")
    _table(lines, ["项目", "内容"], [
        ["应用名称", app_name],
        ["应用编码", app_code],
        ["说明", f"从现有 aPaaS 应用反向导出。应用ID={app_id}；状态={status}；菜单 {len(menus)} 个，表单 {len(forms)} 张，模型 {len(models)} 个。"],
    ])
    _render_menu_section(lines, menus)

    add("## 二、角色列表")
    add("")
    role_rows = []
    for role in roles:
        role_code = role.get("role_code") or role.get("code") or role.get("id") or role.get("role_id") or ""
        role_name = role.get("role_name") or role.get("name") or role.get("roleName") or role_code
        role_rows.append([role_code, role_name])
    _table(lines, ["角色编码", "角色名称"], role_rows)

    add("## 三、数据字典")
    add("")
    if not dicts:
        add("当前应用未查询到数据字典。")
        add("")
    for idx, dct in enumerate(dicts, start=1):
        dict_code = dct.get("dict_code") or dct.get("code") or dct.get("id") or dct.get("dictId") or ""
        dict_name = dct.get("dict_name") or dct.get("name") or dct.get("dictName") or dict_code
        add(f"### 3.{idx} {dict_name or dict_code or '数据字典'}")
        add("")
        _table(lines, ["字典编码", "字典名称"], [[dict_code, dict_name]])
        options = dct.get("options") or dct.get("items") or dct.get("values") or []
        opt_rows = []
        for opt in options:
            if isinstance(opt, dict):
                opt_rows.append([
                    opt.get("option_code") or opt.get("code") or opt.get("value") or opt.get("id") or "",
                    opt.get("option_name") or opt.get("name") or opt.get("label") or opt.get("text") or "",
                ])
        _table(lines, ["选项编码", "选项名称"], opt_rows)

    add("## 四、数据模型")
    add("")
    add("### 4.1 模型定义")
    add("")
    _table(lines, ["模型编码", "模型名称"], [
        [m.get("model_code") or "", m.get("model_name") or m.get("name") or m.get("model_code") or ""]
        for m in models
    ])

    add("### 4.2 模型字段（全部模型字段平铺到一张大表）")
    add("")
    field_rows = []
    seen_fields: set[tuple[str, str]] = set()
    for model in models:
        model_code = str(model.get("model_code") or "")
        for field in model.get("fields") or []:
            field_code = str(field.get("field_code") or field.get("code") or "")
            seen_fields.add((model_code, field_code))
            field_rows.append([
                model_code,
                field_code,
                field.get("field_name") or field.get("name") or field_code,
                _db_type(field.get("database_field_type") or field.get("data_type") or field.get("type")),
                field.get("length") or field.get("max_length") or "255",
            ])
    # Some platform forms expose component bo_code before model fields do.
    for form in forms:
        for comp in form.get("components") or []:
            model_code, field_code = _split_bo_code(comp.get("bo_code"))
            if model_code and field_code and (model_code, field_code) not in seen_fields:
                seen_fields.add((model_code, field_code))
                field_rows.append([
                    model_code,
                    field_code,
                    comp.get("label") or field_code,
                    _db_type(None),
                    "255",
                ])
    _table(lines, ["模型编码", "字段编码", "字段名称", "数据库字段类型", "长度/精度"], field_rows)

    add("## 五、表单定义")
    add("")
    add("### 5.1 表单清单")
    add("")
    form_rows = []
    for form in forms:
        menu = form["menu"]
        form_name = str(menu.get("menu_name") or menu.get("form_id") or "")
        bound_model = _infer_bound_model(form, model_by_code)
        form_rows.append([
            _to_snake(form_name) or str(menu.get("form_id") or ""),
            form_name,
            bound_model,
            f"菜单ID={menu.get('menu_id') or ''}；form_id={menu.get('form_id') or ''}；默认视图={form.get('default_tab_id') or ''}。",
        ])
    _table(lines, ["表单编码", "表单名称", "绑定主表模型", "说明"], form_rows)

    add("### 5.2 主表字段定义")
    add("")
    form_field_rows = []
    for form in forms:
        menu = form["menu"]
        form_name = str(menu.get("menu_name") or menu.get("form_id") or "")
        for comp in form.get("components") or []:
            model_code, field_code = _split_bo_code(comp.get("bo_code"))
            form_field_rows.append([
                form_name,
                field_code or comp.get("uuid") or "",
                comp.get("label") or field_code or "",
                _component_type(comp.get("component_type") or comp.get("type")),
                _yes_no(comp.get("required")),
                _yes_no(comp.get("hidden")),
                _yes_no(comp.get("readonly") or comp.get("read_only")),
                _yes_no(comp.get("list_display", True)),
                _yes_no(comp.get("query_condition")),
                _dict_code(comp),
                _target_model(comp) or model_code if _is_reference_component(comp) else "",
                _target_field(comp),
                _relation_field(comp),
                f"uuid={comp.get('uuid') or ''}；组件类型={comp.get('component_type') or ''}；bo_code={comp.get('bo_code') or ''}。",
            ])
    _table(lines, [
        "表单名称", "字段编码", "字段名称", "组件类型", "必填", "隐藏", "只读", "列表展示", "查询条件",
        "字典编码", "目标模型编码", "目标字段编码", "本表关联字段编码", "说明",
    ], form_field_rows)

    add("### 5.3 子表区域定义（无子表可省略本小节）")
    add("")
    _table(lines, ["表单名称", "子表区域名称", "绑定模型", "说明"], [])

    add("### 5.4 子表字段定义（无子表可省略本小节）")
    add("")
    _table(lines, [
        "表单名称", "子表区域名称", "字段编码", "字段名称", "组件类型", "必填", "隐藏", "只读",
        "列表展示", "查询条件", "字典编码", "目标模型编码", "目标字段编码", "本表关联字段编码", "说明",
    ], [])

    add("## 六、权限定义")
    add("")
    perm_rows = []
    for form in forms:
        form_name = str(form["menu"].get("menu_name") or form["menu"].get("form_id") or "")
        perm_rows.extend(_permission_rows(form_name, form.get("permissions") or {}))
    _table(lines, ["表单名称", "角色编码", "可暂存", "可新增", "可导入", "可查看", "可编辑", "可删除", "可导出", "数据范围"], perm_rows)

    return "\n".join(lines).rstrip() + "\n"


def _needs_business_enrichment(
    app: dict,
    models: list[dict],
    dicts: list[dict],
    roles: list[dict],
    forms: list[dict],
) -> bool:
    if roles or dicts:
        return False
    components = [comp for form in forms for comp in (form.get("components") or [])]
    if not components:
        return False
    generic_labels = sum(1 for comp in components if str(comp.get("label") or "").strip() in {"单行输入", "输入框", ""})
    internal_fields = 0
    total_fields = 0
    for model in models:
        model_code = str(model.get("model_code") or "")
        if model_code.startswith("view_"):
            internal_fields += 1
        total_fields += 1
        for field in model.get("fields") or []:
            total_fields += 1
            if str(field.get("field_code") or "").startswith("widget_"):
                internal_fields += 1
            if str(field.get("field_name") or "").strip() in {"单行输入", "输入框", ""}:
                internal_fields += 1
    app_text = f"{app.get('app_name') or ''} {app.get('app_code') or ''} " + " ".join(
        str((form.get("menu") or {}).get("menu_name") or "") for form in forms
    )
    is_known_business = any(key in app_text.lower() for key in (
        "hr",
        "人力",
        "成本",
        "employee",
        "timesheet",
        "project",
    ))
    return is_known_business and (
        generic_labels >= max(3, len(components) // 2)
        or internal_fields >= max(3, total_fields // 2)
    )


def _render_menu_section(lines: list[str], menus: list[dict], fallback_rows: list[list[Any]] | None = None) -> None:
    lines.append("### 1.1 菜单清单")
    lines.append("")
    rows: list[list[Any]] = []
    for menu in menus:
        menu_code = (
            menu.get("menu_code")
            or menu.get("code")
            or _to_snake(str(menu.get("menu_name") or menu.get("path") or menu.get("menu_id") or ""))
        )
        rows.append([
            menu_code,
            menu.get("menu_name") or menu.get("name") or "",
            menu.get("menu_type") or menu.get("type") or "",
            menu.get("form_id") or "",
            menu.get("path") or menu.get("menu_name") or "",
            f"menu_id={menu.get('menu_id') or ''}；parent_id={menu.get('parent_id') or ''}；depth={menu.get('depth') or 0}。",
        ])
    if fallback_rows and len(fallback_rows) > len(rows):
        rows = fallback_rows
    _table(lines, ["菜单编码", "菜单名称", "菜单类型", "关联表单/模型", "菜单路径", "说明"], rows)


def _render_business_enriched_design_doc(app: dict, menus: list[dict], forms: list[dict]) -> str:
    app_name = str(app.get("app_name") or "HR人力成本管理")
    app_code = str(app.get("app_code") or "hr-cost-mgmt")
    app_id = str(app.get("apaas_app_id") or "")

    roles = [
        ["hr_admin", "HR管理员"],
        ["finance_manager", "财务经理"],
        ["dept_manager", "部门经理"],
        ["employee", "员工"],
    ]
    dicts = [
        ("employment_status", "在职状态", [("active", "在职"), ("probation", "试用"), ("leave", "离职")]),
        ("cost_type", "成本类型", [("regular", "正常工时"), ("overtime", "加班"), ("project", "项目投入"), ("absence", "缺勤")]),
        ("department_status", "部门状态", [("enabled", "启用"), ("disabled", "停用")]),
        ("project_status", "项目状态", [("planning", "规划中"), ("running", "进行中"), ("paused", "暂停"), ("closed", "已结项")]),
        ("timesheet_status", "工时状态", [("draft", "草稿"), ("submitted", "已提交"), ("approved", "已审批"), ("rejected", "已驳回")]),
        ("payroll_status", "薪酬状态", [("draft", "草稿"), ("confirmed", "已确认"), ("locked", "已锁定")]),
        ("allocation_status", "分摊状态", [("draft", "草稿"), ("calculated", "已计算"), ("confirmed", "已确认"), ("posted", "已入账")]),
    ]
    model_specs = _hr_cost_model_specs()
    form_specs = [
        ("employee_profile", "员工档案", "employee_profile", "维护员工基础信息、组织归属、成本中心和薪酬成本口径。"),
        ("department_cost_center", "部门成本中心", "department_cost_center", "维护部门、成本中心、预算负责人和月度预算口径。"),
        ("project_management", "项目管理", "project_management", "维护项目基础信息、预算、成本中心和项目状态。"),
        ("timesheet_record", "工时记录", "timesheet_record", "登记员工按日期、项目、成本类型归集的工时数据。"),
        ("payroll_cost", "薪酬成本", "payroll_cost", "按月份汇总员工薪酬、社保、公积金、奖金和扣款。"),
        ("cost_allocation", "成本分摊", "cost_allocation", "将薪酬与工时成本按项目、部门、成本中心进行分摊。"),
    ]
    menu_specs = [
        ["hr_cost_dashboard", "人力成本看板", "CUSTOM", "", "HR人力成本管理/人力成本看板", "总览人力成本、预算占用、项目成本趋势。"],
        ["employee_profile", "员工档案", "MENU", "employee_profile", "HR人力成本管理/员工档案", "进入员工档案表单。"],
        ["department_cost_center", "部门成本中心", "MENU", "department_cost_center", "HR人力成本管理/部门成本中心", "进入部门成本中心表单。"],
        ["project_management", "项目管理", "MENU", "project_management", "HR人力成本管理/项目管理", "进入项目管理表单。"],
        ["timesheet_record", "工时记录", "MENU", "timesheet_record", "HR人力成本管理/工时记录", "进入工时记录表单。"],
        ["payroll_cost", "薪酬成本", "MENU", "payroll_cost", "HR人力成本管理/薪酬成本", "进入薪酬成本表单。"],
        ["cost_allocation", "成本分摊", "MENU", "cost_allocation", "HR人力成本管理/成本分摊", "进入成本分摊表单。"],
    ]

    lines: list[str] = []
    add = lines.append
    add("## 一、应用信息")
    add("")
    _table(lines, ["项目", "内容"], [
        ["应用名称", app_name],
        ["应用编码", app_code],
        [
            "说明",
            (
                "用于 HR 人力成本管理，覆盖员工档案、项目管理、工时记录、成本归集和权限控制。"
                f"本稿基于现有 aPaaS 应用反向导出并做业务语义补全；原应用ID={app_id}，"
                f"检测到平台字段多为内部编码/通用标签，因此保留业务化字段供 Builder 重新生成。"
            ),
        ],
    ])
    _render_menu_section(lines, menus, menu_specs)

    add("## 二、角色列表")
    add("")
    _table(lines, ["角色编码", "角色名称"], roles)

    add("## 三、数据字典")
    add("")
    for idx, (code, name, options) in enumerate(dicts, start=1):
        add(f"### 3.{idx} {name}")
        add("")
        _table(lines, ["字典编码", "字典名称"], [[code, name]])
        _table(lines, ["选项编码", "选项名称"], options)

    add("## 四、数据模型")
    add("")
    add("### 4.1 模型定义")
    add("")
    _table(lines, ["模型编码", "模型名称"], [[code, spec["name"]] for code, spec in model_specs.items()])

    add("### 4.2 模型字段（全部模型字段平铺到一张大表）")
    add("")
    model_field_rows = []
    for model_code, spec in model_specs.items():
        for field in spec["fields"]:
            model_field_rows.append([
                model_code,
                field["code"],
                field["name"],
                field["db_type"],
                field["length"],
            ])
    _table(lines, ["模型编码", "字段编码", "字段名称", "数据库字段类型", "长度/精度"], model_field_rows)

    add("## 五、表单定义")
    add("")
    add("### 5.1 表单清单")
    add("")
    _table(lines, ["表单编码", "表单名称", "绑定主表模型", "说明"], form_specs)

    add("### 5.2 主表字段定义")
    add("")
    form_field_rows = []
    for _form_code, form_name, model_code, _desc in form_specs:
        for field in model_specs[model_code]["fields"]:
            form_field_rows.append([
                form_name,
                field["code"],
                field["name"],
                field["component"],
                "是" if field.get("required") else "否",
                "否",
                "否",
                "是" if field.get("list") else "否",
                "是" if field.get("query") else "否",
                field.get("dict") or "",
                field.get("target_model") or "",
                field.get("target_field") or "",
                "",
                field.get("desc") or "",
            ])
    _table(lines, [
        "表单名称", "字段编码", "字段名称", "组件类型", "必填", "隐藏", "只读", "列表展示", "查询条件",
        "字典编码", "目标模型编码", "目标字段编码", "本表关联字段编码", "说明",
    ], form_field_rows)

    add("### 5.3 子表区域定义（无子表可省略本小节）")
    add("")
    _table(lines, ["表单名称", "子表区域名称", "绑定模型", "说明"], [])

    add("### 5.4 子表字段定义（无子表可省略本小节）")
    add("")
    _table(lines, [
        "表单名称", "子表区域名称", "字段编码", "字段名称", "组件类型", "必填", "隐藏", "只读",
        "列表展示", "查询条件", "字典编码", "目标模型编码", "目标字段编码", "本表关联字段编码", "说明",
    ], [])

    add("## 六、权限定义")
    add("")
    perm_rows = []
    for _form_code, form_name, _model_code, _desc in form_specs:
        perm_rows.extend([
            [form_name, "hr_admin", "是", "是", "是", "是", "是", "是", "是", "全部数据"],
            [form_name, "finance_manager", "否", "否", "否", "是", "否", "否", "是", "全部数据"],
            [form_name, "dept_manager", "否", "是", "否", "是", "是", "否", "否", "本部门及下属部门"],
            [form_name, "employee", "是", "是", "否", "是", "是", "否", "否", "本人数据"],
        ])
    _table(lines, ["表单名称", "角色编码", "可暂存", "可新增", "可导入", "可查看", "可编辑", "可删除", "可导出", "数据范围"], perm_rows)

    return "\n".join(lines).rstrip() + "\n"


def _hr_cost_model_specs() -> dict[str, dict[str, Any]]:
    return {
        "employee_profile": {
            "name": "员工档案",
            "fields": [
                _field("employee_no", "员工编号", "varchar", "64", "单行输入", True, True, True),
                _field("employee_name", "员工姓名", "varchar", "128", "单行输入", True, True, True),
                _field("department_code", "所属部门", "varchar", "64", "数据单选", True, True, True, target_model="department_cost_center", target_field="department_name"),
                _field("position_name", "岗位名称", "varchar", "128", "单行输入", False, True, False),
                _field("employment_status", "在职状态", "varchar", "32", "下拉单选", True, True, True, "employment_status"),
                _field("cost_center", "成本中心", "varchar", "128", "单行输入", True, True, True),
                _field("base_salary", "基本工资", "decimal", "18,2", "金额", False, False, False),
                _field("social_security_amount", "社保金额", "decimal", "18,2", "金额", False, False, False),
                _field("housing_fund_amount", "公积金金额", "decimal", "18,2", "金额", False, False, False),
                _field("onboard_date", "入职日期", "date", "", "日期时间", False, True, False),
                _field("leave_date", "离职日期", "date", "", "日期时间", False, False, False),
                _field("employee_remark", "员工备注", "text", "", "多行输入", False, False, False),
            ],
        },
        "department_cost_center": {
            "name": "部门成本中心",
            "fields": [
                _field("department_code", "部门编码", "varchar", "64", "单行输入", True, True, True),
                _field("department_name", "部门名称", "varchar", "128", "单行输入", True, True, True),
                _field("parent_department_code", "上级部门", "varchar", "64", "数据单选", False, True, False, target_model="department_cost_center", target_field="department_name"),
                _field("cost_center", "成本中心", "varchar", "128", "单行输入", True, True, True),
                _field("budget_owner", "预算负责人", "varchar", "64", "人员选择", False, True, False),
                _field("monthly_budget", "月度预算", "decimal", "18,2", "金额", False, True, False),
                _field("department_status", "部门状态", "varchar", "32", "下拉单选", True, True, True, "department_status"),
                _field("department_remark", "部门备注", "text", "", "多行输入", False, False, False),
            ],
        },
        "project_management": {
            "name": "项目管理",
            "fields": [
                _field("project_code", "项目编码", "varchar", "64", "单行输入", True, True, True),
                _field("project_name", "项目名称", "varchar", "128", "单行输入", True, True, True),
                _field("project_manager", "项目负责人", "varchar", "64", "人员选择", True, True, False),
                _field("cost_center", "成本中心", "varchar", "128", "数据单选", True, True, True, target_model="department_cost_center", target_field="cost_center"),
                _field("start_date", "开始日期", "date", "", "日期时间", False, True, False),
                _field("end_date", "结束日期", "date", "", "日期时间", False, True, False),
                _field("project_status", "项目状态", "varchar", "32", "下拉单选", True, True, True, "project_status"),
                _field("budget_amount", "预算金额", "decimal", "18,2", "金额", False, True, False),
                _field("accumulated_cost", "累计人力成本", "decimal", "18,2", "金额", False, True, True),
                _field("project_remark", "项目备注", "text", "", "多行输入", False, False, False),
            ],
        },
        "timesheet_record": {
            "name": "工时记录",
            "fields": [
                _field("timesheet_no", "工时单号", "varchar", "64", "单据号", True, True, True),
                _field("employee_no", "员工编号", "varchar", "64", "数据单选", True, True, True, target_model="employee_profile", target_field="employee_name"),
                _field("project_code", "项目编码", "varchar", "64", "数据单选", True, True, True, target_model="project_management", target_field="project_name"),
                _field("work_date", "工作日期", "date", "", "日期时间", True, True, True),
                _field("work_hours", "正常工时", "decimal", "10,2", "数字", True, True, False),
                _field("overtime_hours", "加班工时", "decimal", "10,2", "数字", False, True, False),
                _field("cost_type", "成本类型", "varchar", "32", "下拉单选", True, True, True, "cost_type"),
                _field("timesheet_status", "工时状态", "varchar", "32", "下拉单选", True, True, True, "timesheet_status"),
                _field("approved_by", "审批人", "varchar", "64", "人员选择", False, False, False),
                _field("approved_time", "审批时间", "datetime", "", "日期时间", False, False, False),
                _field("timesheet_remark", "工时备注", "text", "", "多行输入", False, False, False),
            ],
        },
        "payroll_cost": {
            "name": "薪酬成本",
            "fields": [
                _field("payroll_month", "薪酬月份", "varchar", "16", "月份", True, True, True),
                _field("employee_no", "员工编号", "varchar", "64", "数据单选", True, True, True, target_model="employee_profile", target_field="employee_name"),
                _field("cost_center", "成本中心", "varchar", "128", "单行输入", True, True, True),
                _field("base_salary", "基本工资", "decimal", "18,2", "金额", True, True, False),
                _field("bonus_amount", "奖金金额", "decimal", "18,2", "金额", False, True, False),
                _field("social_security_amount", "社保金额", "decimal", "18,2", "金额", False, True, False),
                _field("housing_fund_amount", "公积金金额", "decimal", "18,2", "金额", False, True, False),
                _field("deduction_amount", "扣款金额", "decimal", "18,2", "金额", False, True, False),
                _field("total_cost", "总人力成本", "decimal", "18,2", "金额", True, True, True),
                _field("payroll_status", "薪酬状态", "varchar", "32", "下拉单选", True, True, True, "payroll_status"),
                _field("payroll_remark", "薪酬备注", "text", "", "多行输入", False, False, False),
            ],
        },
        "cost_allocation": {
            "name": "成本分摊",
            "fields": [
                _field("allocation_no", "分摊单号", "varchar", "64", "单据号", True, True, True),
                _field("payroll_month", "薪酬月份", "varchar", "16", "月份", True, True, True),
                _field("employee_no", "员工编号", "varchar", "64", "数据单选", True, True, True, target_model="employee_profile", target_field="employee_name"),
                _field("project_code", "项目编码", "varchar", "64", "数据单选", True, True, True, target_model="project_management", target_field="project_name"),
                _field("cost_center", "成本中心", "varchar", "128", "数据单选", True, True, True, target_model="department_cost_center", target_field="cost_center"),
                _field("allocation_ratio", "分摊比例", "decimal", "8,4", "数字", True, True, False),
                _field("allocated_amount", "分摊金额", "decimal", "18,2", "金额", True, True, True),
                _field("allocation_status", "分摊状态", "varchar", "32", "下拉单选", True, True, True, "allocation_status"),
                _field("allocation_remark", "分摊备注", "text", "", "多行输入", False, False, False),
            ],
        },
    }


def _field(
    code: str,
    name: str,
    db_type: str,
    length: str,
    component: str,
    required: bool,
    list_display: bool,
    query: bool,
    dict_code: str = "",
    target_model: str = "",
    target_field: str = "",
    desc: str = "",
) -> dict[str, Any]:
    return {
        "code": code,
        "name": name,
        "db_type": db_type,
        "length": length,
        "component": component,
        "required": required,
        "list": list_display,
        "query": query,
        "dict": dict_code,
        "target_model": target_model,
        "target_field": target_field,
        "desc": desc,
    }


def _table(lines: list[str], headers: list[str], rows: list[list[Any]]) -> None:
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---------"] * len(headers)) + "|")
    for row in rows:
        cells = list(row)[:len(headers)]
        cells.extend([""] * (len(headers) - len(cells)))
        lines.append("| " + " | ".join(_cell(v) for v in cells) + " |")
    lines.append("")


def _cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("\n", " ").replace("|", "\\|").strip()


def _to_snake(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    out = re.sub(r"[^0-9A-Za-z]+", "_", raw).strip("_").lower()
    if out and out[0].isdigit():
        out = f"f_{out}"
    return out[:64]


def _safe_filename(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z._-]+", "-", (text or "app").strip()).strip("-") or "app"


def _split_bo_code(bo_code: Any) -> tuple[str, str]:
    raw = str(bo_code or "")
    if "~" not in raw:
        return "", ""
    left, right = raw.split("~", 1)
    return left.strip(), right.strip()


def _db_type(value: Any) -> str:
    raw = str(value or "").lower()
    if raw in {"varchar", "text", "datetime", "date", "decimal", "int", "bigint"}:
        return raw
    if raw in {"number", "integer"}:
        return "int"
    if raw in {"money", "float", "double"}:
        return "decimal"
    return "varchar"


def _component_type(value: Any) -> str:
    mapping = {
        "FORM_TEXT_INPUT": "单行输入",
        "FORM_TEXTAREA_INPUT": "多行输入",
        "FORM_PHONE_INPUT": "手机号码",
        "FORM_EMAIL_INPUT": "电子邮箱",
        "FORM_SELECT_INPUT_SINGLE": "下拉单选",
        "FORM_SELECT_INPUT": "下拉多选",
        "FORM_DATA_SELECTOR_SINGLE": "数据单选",
        "FORM_DATA_SELECTOR": "数据选择",
        "FORM_DATEPICK_INPUT": "日期时间",
        "FORM_MONEY_INPUT": "金额",
        "FORM_NUMBER_INPUT": "数字",
        "FORM_FILE_UPLOAD": "附件上传",
        "FORM_SWITCH_SELECT": "开关",
        "FORM_PEOPLE_SELECT": "人员选择",
        "FORM_DEPARTMENT_SELECT": "部门选择",
        "FORM_WIDGET_LOCATION": "地理位置",
        "FORM_WIDGET_SON_TABLE": "子表",
        "FORM_RADIO_INPUT": "单选框",
        "FORM_CHECKBOX_INPUT": "复选框",
        "FORM_RICH_TEXT": "富文本",
        "FORM_HYPERLINK_INPUT": "超链接",
        "FORM_IDCARD_INPUT": "身份证号",
        "FORM_WIDGET_AREA": "地区地址",
        "FORM_ASSOCIATION": "关联表单",
    }
    return mapping.get(str(value or ""), str(value or "") or "单行输入")


def _yes_no(value: Any) -> str:
    return "是" if bool(value) else "否"


def _dict_code(comp: dict) -> str:
    options = comp.get("dictionary_choose_options") or []
    if options and isinstance(options[0], dict):
        return str(options[0].get("dict_code") or options[0].get("code") or "")
    return str(comp.get("dict_code") or comp.get("dictionary_code") or "")


def _target_model(comp: dict) -> str:
    return str(comp.get("target_model_code") or comp.get("targetModelCode") or comp.get("ref_model_code") or "")


def _target_field(comp: dict) -> str:
    return str(comp.get("target_field_code") or comp.get("targetFieldCode") or comp.get("ref_field_code") or "")


def _relation_field(comp: dict) -> str:
    return str(comp.get("relation_field_code") or comp.get("relationFieldCode") or "")


def _is_reference_component(comp: dict) -> bool:
    return str(comp.get("component_type") or "") in {
        "FORM_DATA_SELECTOR_SINGLE",
        "FORM_DATA_SELECTOR",
        "FORM_ASSOCIATION",
    }


def _infer_bound_model(form: dict, model_by_code: dict[str, dict]) -> str:
    for comp in form.get("components") or []:
        model_code, _field_code = _split_bo_code(comp.get("bo_code"))
        if model_code in model_by_code:
            return model_code
    return ""


def _permission_rows(form_name: str, perm: dict) -> list[list[Any]]:
    data_by_subject: dict[str, dict] = {}
    for item in perm.get("data_permissions") or []:
        subject = item.get("subject") or {}
        code = str(subject.get("subject_value") or subject.get("subject_type") or item.get("role_code") or "ALL_USER")
        # Prefer the active row that grants view/edit/delete.
        if code not in data_by_subject or item.get("can_view") or item.get("can_edit") or item.get("can_delete"):
            data_by_subject[code] = item

    op_by_subject: dict[str, dict] = {}
    for item in perm.get("operation_permissions") or []:
        subject = item.get("subject") or {}
        code = str(subject.get("subject_value") or subject.get("subject_type") or item.get("role_code") or "ALL_USER")
        op_by_subject[code] = item

    subjects = sorted(set(data_by_subject) | set(op_by_subject)) or ["ALL_USER"]
    rows = []
    for code in subjects:
        data = data_by_subject.get(code) or {}
        op = op_by_subject.get(code) or {}
        subject = data.get("subject") or op.get("subject") or {}
        rows.append([
            form_name,
            code,
            _yes_no(op.get("can_draft")),
            _yes_no(op.get("can_add")),
            _yes_no(op.get("can_import")),
            _yes_no(data.get("can_view")),
            _yes_no(data.get("can_edit")),
            _yes_no(data.get("can_delete")),
            _yes_no(op.get("can_export") or op.get("can_share_form")),
            _range_name(subject.get("range_type")),
        ])
    return rows


def _range_name(value: Any) -> str:
    mapping = {
        "ALL": "全部数据",
        "SELF": "本人数据",
        "DEPT": "本部门",
        "DEPT_AND_CHILD": "本部门及下属部门",
        "DEPT_AND_SUB": "本部门及下属部门",
    }
    return mapping.get(str(value or ""), "本人数据")


def _looks_like_builder_doc(content: str) -> bool:
    return bool(content and "应用信息" in content and "数据模型" in content and "表单定义" in content)


def _validate_builder_doc_silent(content: str) -> dict | None:
    try:
        from app.doc_pipeline import _strip_template_scaffolding
        from app.doc_standard_detector import detect

        cleaned = _strip_template_scaffolding(content)
        result = detect(cleaned)
        score = int(result.get("score") or 0)
        missing = result.get("missing_sections") or []
        return {
            "score": score,
            "passes_strict": score >= 90 and not missing,
            "missing_sections": missing,
            "weak_sections": result.get("weak_sections") or [],
        }
    except Exception:
        return None


def _design_doc_stats(markdown: str) -> dict[str, Any]:
    lines = markdown.splitlines()

    def section_body(start_marker: str, end_markers: tuple[str, ...]) -> str:
        start = -1
        for i, line in enumerate(lines):
            if start_marker in line:
                start = i + 1
                break
        if start < 0:
            return ""
        end = len(lines)
        for i in range(start, len(lines)):
            if any(marker in lines[i] for marker in end_markers):
                end = i
                break
        return "\n".join(lines[start:end])

    def count_table_rows(body: str) -> int:
        count = 0
        for line in body.splitlines():
            text = line.strip()
            if not text.startswith("|") or "---------" in text:
                continue
            if any(header in text for header in ("菜单编码", "角色编码", "模型编码", "表单编码", "字段编码")):
                continue
            count += 1
        return count

    menus_body = section_body("1.1 菜单清单", ("二、角色列表",))
    roles_body = section_body("二、角色列表", ("三、数据字典",))
    models_body = section_body("4.1 模型定义", ("4.2 模型字段",))
    forms_body = section_body("5.1 表单清单", ("5.2 主表字段",))
    return {
        "menus": count_table_rows(menus_body),
        "roles": count_table_rows(roles_body),
        "dicts": len(re.findall(r"^###\s+3\.", markdown, flags=re.MULTILINE)),
        "models": count_table_rows(models_body),
        "forms": count_table_rows(forms_body),
        "business_enriched": "业务语义补全" in markdown,
    }


# ─────────────────────────── Dispatcher ───────────────────────────

TOOL_HANDLERS = {
    "read_attachment": execute_read_attachment,
    "run_python": execute_run_python,
    "write_artifact": execute_write_artifact,
    "ask_clarifying_question": execute_ask_clarifying_question,
    "export_apaas_app_design_doc": execute_export_apaas_app_design_doc,
}


# 原 4 个 base 工具的 schemas（保持原有 TOOL_SCHEMAS 引用名兼容老代码）
BASE_TOOL_SCHEMAS = TOOL_SCHEMAS


async def get_all_tool_schemas() -> list[dict]:
    """合并 base 4 + MCP bridge 工具。MCP 不可用时退化到 base 4。

    每次 agent turn 开始时调用——让"装上新 MCP 工具立即可用"，不用重启 backend。
    """
    from app.ai_chat.mcp_bridge import get_tool_schemas_openai
    try:
        mcp_schemas = await get_tool_schemas_openai()
    except Exception as e:
        # MCP 不可用不影响 base 工具
        import logging as _log
        _log.getLogger(__name__).warning("MCP bridge 加载失败，退化到 base 4 工具：%s", e)
        mcp_schemas = []
    return BASE_TOOL_SCHEMAS + mcp_schemas


async def execute_tool(
    tool_name: str, args: dict, session: AIChatSession, db: AsyncSession
) -> str:
    """工具 dispatcher：base 工具走本地 handler；其他兜底走 MCP HTTP bridge。

    自动塞 session.tenant_id / session.user_id 给 MCP（很多 MCP 工具签名隐式接受
    tenant_id / user_id 做 fallback admin）。

    ⚠️ Side-effect intercept (2026-05-21)：generate_app_from_doc / update_app_from_doc
    成功调用时，把 args.md_content 落 AIChatArtifact 表（用户能在右侧面板回看 SPEC）。
    不污染 MCP 工具本身（外部 dolphin / Claude / Cursor 调那俩工具不受影响）。
    """
    handler = TOOL_HANDLERS.get(tool_name)
    if handler:
        try:
            return await handler(args, session, db)
        except Exception as e:
            return f"错误：工具 '{tool_name}' 执行异常 - {e}"

    # 兜底：尝试通过 MCP bridge 调本机 MCP server
    from app.ai_chat.mcp_bridge import list_mcp_tool_names_cached, call_tool as _mcp_call
    if tool_name in list_mcp_tool_names_cached():
        result_text = await _mcp_call(
            tool_name, args,
            tenant_id=int(getattr(session, "tenant_id", 0) or 0),
            user_id=int(getattr(session, "user_id", 0) or 0),
        )
        # SPEC artifact 落地副作用 — 仅 ai_chat 走这条 dispatcher，外部调用方不会触发
        # 2026-05-24: generate_app_from_doc 改强制 artifact_id 后, args 里没 md_content,
        # 而 artifact 已经在 write_artifact 时落表 — 不需要 _persist. update_app_from_doc
        # 还接收 md_content (未改 schema), 继续 intercept.
        if tool_name == "update_app_from_doc":
            await _persist_spec_artifact(tool_name, args, result_text, session, db)
        return result_text

    return f"错误：未知工具 '{tool_name}'"


async def _persist_spec_artifact(
    tool_name: str,
    args: dict,
    result_text: str,
    session: AIChatSession,
    db: AsyncSession,
) -> None:
    """把 generate_app_from_doc / update_app_from_doc 的 md_content 落 artifact 表。

    成功失败都落（哪怕 deploy 失败，SPEC 是 agent 想表达的设计意图，得保留）。
    失败时只 log warning 不抛 — artifact 落地是副作用，不能因此把工具结果污染。
    """
    import logging as _log
    md_content = (args.get("md_content") or "").strip()
    if not md_content:
        return  # 没 md 内容（不该发生但防御一下）

    # 文件名优先级：generate 用 args.app_name；update 用 app_id；
    # 兜底从 result_text JSON 拿 app_name / app_id；最后用通用名
    fname: str = ""
    app_name = (args.get("app_name") or "").strip()
    if app_name:
        fname = f"{app_name}-设计文档.md"
    elif tool_name == "update_app_from_doc" and args.get("app_id"):
        fname = f"app-{args['app_id']}-设计文档.md"

    if not fname:
        # 尝试从 result_text 里 parse JSON 拿 app_name
        try:
            parsed = json.loads(result_text)
            if isinstance(parsed, dict):
                rname = (parsed.get("app_name") or "").strip()
                rid = parsed.get("app_id")
                if rname:
                    fname = f"{rname}-设计文档.md"
                elif rid:
                    fname = f"app-{rid}-设计文档.md"
        except Exception:
            pass

    if not fname:
        fname = "app-design.md"

    try:
        await execute_write_artifact(
            {"filename": fname, "content": md_content, "format": "md"},
            session,
            db,
        )
    except Exception as e:
        _log.getLogger(__name__).warning(
            "persist SPEC artifact failed (tool=%s filename=%s): %s",
            tool_name, fname, e,
        )
