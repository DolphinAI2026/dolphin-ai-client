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
            "name": "read_artifact",
            "description": (
                "读回某个已有产出物的内容（超过 30000 字符会自动截断）。"
                "调 edit_artifact 之前**必须**先 read_artifact 拿到精确原文，再据此构造 old_string，"
                "不要凭记忆/上一轮的内容拼 old_string（文档可能已被改过）。"
                "大文档被截断时，可传 offset/limit 分页读取后续部分。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "产出物文件名，例如 'seal-lab-mgmt-design.md'",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "起始行号（0-based），用于分页读取大文档。省略则从头读。",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "读取行数，用于分页读取大文档。省略则读全篇（受 30000 字符截断）。",
                    },
                },
                "required": ["filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_artifact",
            "description": (
                "在已有产出物上做精确的字符串替换（找到 old_string 替换成 new_string），"
                "**只改动那一处、不整篇重写**。改设计文档里一个字段/编码/小段落时用它，别用 write_artifact 整篇重发。\n"
                "用法要求：① 先 read_artifact 拿到精确原文，old_string 必须**逐字匹配**（含空白和缩进）；"
                "② old_string 必须在文中**恰好出现一次**——若返回'出现 N 次'，多带几行上下文让它唯一；"
                "③ 若返回'未找到 old_string'，重新 read_artifact 刷新内容再重建 old_string。"
                "替换后会自动落新版本(version++)并重新校验。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "要编辑的产出物文件名（必须已存在）",
                    },
                    "old_string": {
                        "type": "string",
                        "description": "文中要被替换的原文片段，逐字复制自 read_artifact 结果，不要凭记忆拼。",
                    },
                    "new_string": {
                        "type": "string",
                        "description": "替换成的新内容",
                    },
                },
                "required": ["filename", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_artifact_from_attachment",
            "description": (
                "把用户上传的【本身已是结构化设计文档】的附件，原样全文转成设计文档 artifact"
                "（服务端直接复制：不截断、不摘要、不改写），返回 artifact 供 "
                "generate_app_from_doc 使用。"
                "★超大文档（几十上百个模型/表单）必须用本工具——绝不要 read_attachment 读一遍再 "
                "write_artifact 重抄一遍：read_attachment 会在 3 万字处截断，write_artifact 又受输出长度限制，"
                "整篇会被你无意识地摘要/漏掉，导致只建出残缺应用。"
                "本工具把整篇（哪怕 30 万字、132 个模型）一字不差落进 artifact，generate 时由确定性解析器解析全篇。"
                "仅当附件是粗略需求 / PRD 散文、需要你转写成标准 6 章格式时，才改用 read_attachment + write_artifact。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "附件文件名（与上传时一致）",
                    },
                    "artifact_filename": {
                        "type": "string",
                        "description": "可选；产出物文件名（默认用附件名改成 .md）",
                    },
                },
                "required": ["filename"],
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
    {
        "type": "function",
        "function": {
            "name": "search_tools",
            "description": (
                "按需加载延迟工具:当你要用的工具不在当前 tools 列表(但在系统提示的"
                "「可按需加载的工具」清单里)时,先调这个把它加载进来,下一轮就能直接调用。"
                "query 用关键词(如「改字段 必填」),或用 'select:工具名1,工具名2' 精确选。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "关键词,或 select:工具名 精确选"},
                },
                "required": ["query"],
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


async def execute_read_artifact(
    args: dict, session: AIChatSession, db: AsyncSession
) -> str:
    """读回某个产出物的内容 —— 给 edit_artifact 构造精确 old_string 用。

    超过 ARTIFACT_READ_MAX_CHARS 时截断并提示，避免单条 tool_result
    吃掉大量上下文窗口（与 read_attachment 的 30K 上限对齐）。
    支持可选 offset/limit 参数做分页读取大文档。
    """
    filename = args.get("filename", "").strip()
    if not filename:
        return "错误：缺少 filename 参数"
    latest = await _latest_artifact(db, session.id, filename)
    if latest is None:
        return f"错误：产出物 '{filename}' 不存在（确认文件名，或先用 write_artifact 新建）。"

    full_content = latest.content or ""
    total_chars = len(full_content)

    # 分页参数（可选）：按行偏移 + 行数限制
    offset = args.get("offset")  # 起始行号（0-based）
    limit = args.get("limit")    # 读取行数

    if offset is not None or limit is not None:
        lines = full_content.splitlines(keepends=True)
        start = max(0, int(offset or 0))
        end = start + int(limit or 200)
        chunk = "".join(lines[start:end])
        return (
            f"产出物 '{filename}' (v{latest.version}, 共 {len(lines)} 行 / {total_chars} 字符) "
            f"第 {start+1}–{min(end, len(lines))} 行：\n\n{chunk}"
        )

    # 默认：整篇读取，超长截断
    ARTIFACT_READ_MAX_CHARS = 30_000
    if total_chars > ARTIFACT_READ_MAX_CHARS:
        truncated = full_content[:ARTIFACT_READ_MAX_CHARS]
        return (
            f"产出物 '{filename}' (v{latest.version}, 共 {total_chars} 字符) 前 {ARTIFACT_READ_MAX_CHARS} 字符：\n\n"
            f"{truncated}\n\n"
            f"[已截断，原文共 {total_chars} 字符。"
            f"需要后续部分请用 read_artifact(filename=\"{filename}\", offset=行号, limit=行数) 分页读取；"
            f"做精确替换请用 edit_artifact 的 old_string 直接定位。]"
        )
    return f"产出物 '{filename}' (v{latest.version}) 当前内容：\n\n{full_content}"


async def execute_edit_artifact(
    args: dict, session: AIChatSession, db: AsyncSession
) -> str:
    """在已有产出物上做 old_string→new_string 精确替换（不整篇重写）。

    复用 execute_write_artifact 落新版本（version++ + Builder 静默校验），所以下游
    generate_app_from_doc 仍拿到一份完整可解析的文档。old_string 必须在文中恰好出现一次。
    """
    filename = args.get("filename", "").strip()
    old_string = args.get("old_string", "")
    new_string = args.get("new_string", "")
    if not filename:
        return "错误：缺少 filename 参数"
    if not old_string:
        return "错误：缺少 old_string 参数"
    latest = await _latest_artifact(db, session.id, filename)
    if latest is None:
        return f"错误：产出物 '{filename}' 不存在（确认文件名，或先用 write_artifact 新建）。"
    content = latest.content or ""
    n = content.count(old_string)
    if n == 0:
        return (
            f"错误：在 '{filename}' 中未找到 old_string。"
            "请先 read_artifact 拿到精确原文（含空白/缩进）再重试。"
        )
    if n > 1:
        return (
            f"错误：old_string 在 '{filename}' 中出现 {n} 次，无法定位。"
            "请提供更长、更唯一的片段（多带几行上下文）。"
        )
    new_content = content.replace(old_string, new_string, 1)
    # 走 write_artifact：version++ + 校验 + 让上层 agent loop 发 artifact_created 刷新右栏
    return await execute_write_artifact(
        {"filename": filename, "content": new_content, "format": latest.format},
        session,
        db,
    )


async def execute_create_artifact_from_attachment(
    args: dict, session: AIChatSession, db: AsyncSession
) -> str:
    """把用户上传的附件【原样全文】转成设计文档 artifact（不截断/不摘要/不改写）。

    2026-05-29 修"超大附件喂不进 generate"：用户上传含 132 模型 / 42 表单的 33 万字
    标准设计文档时，老路径 read_attachment(截断 3 万字) + write_artifact(LLM 重抄, 受
    输出长度限) 会把整篇摘要/漏掉 → 只建出残缺应用 + 反复撞 appCode。本工具服务端直接把
    attachment.content_text 整篇复制进 artifact，generate_app_from_doc 用确定性解析器
    (doc_pipeline.parse_document) 解析全篇 —— 实测同一份文档可完整还原 132 模型 / 42 表单。
    """
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
        return f"错误：'{filename}' 是图片附件，不能转设计文档"
    content = att.content_text or ""
    if not content.strip():
        return f"错误：'{filename}' 解析为空，无法转 artifact"

    # 产出物文件名：优先参数，否则把附件名改成 .md
    art_name = (args.get("artifact_filename") or "").strip()
    if not art_name:
        art_name = os.path.splitext(filename)[0] + ".md"
    elif not art_name.lower().endswith(".md"):
        art_name = art_name + ".md"

    # 复用 write_artifact 落库（版本管理 + 右栏展示 + 轻量 Builder 校验），content 是整篇原文
    note = await execute_write_artifact(
        {"filename": art_name, "content": content, "format": "md"}, session, db
    )
    return (
        f"已把附件《{filename}》整篇原样写入设计文档 artifact '{art_name}'"
        f"（{len(content)} 字符，未截断/未改写）。"
        f"下一步直接 generate_app_from_doc 创建应用即可——整篇会被确定性解析，"
        f"**不要**自己分批 / 摘要 / 重写文档。{note}"
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

    models = models_res.get("models") or []
    dicts = dicts_res.get("dicts") or []
    roles = roles_res.get("roles") or []
    markdown = _render_apaas_design_doc(
        app=app,
        menus=menus,
        models=models,
        dicts=dicts,
        roles=roles,
        forms=forms,
    )
    filename = str(args.get("filename") or "").strip() or f"{_safe_filename(app_code or app_name)}-design.md"
    await execute_write_artifact({"filename": filename, "content": markdown, "format": "md"}, session, db)

    art = await _latest_artifact(db, session.id, filename)
    validation = _validate_builder_doc_silent(markdown) or {}
    doc_stats = _design_doc_stats(markdown)
    metadata_sparse = _metadata_is_sparse(models, dicts, roles, forms)
    result: dict[str, Any] = {
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
        "metadata_sparse": metadata_sparse,
        "validation": {
            "score": validation.get("score"),
            "passes_strict": validation.get("passes_strict"),
            "missing_sections": validation.get("missing_sections") or [],
            "weak_sections": validation.get("weak_sections") or [],
        },
    }
    if metadata_sparse:
        result["warning"] = (
            "该应用元数据不完整（缺少角色/数据字典，且字段多为内部编码或通用标签），"
            "导出文档可能较简略，建议先在平台完善配置后再导出。"
        )
    return json.dumps(result, ensure_ascii=False)


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


def _metadata_is_sparse(
    models: list[dict],
    dicts: list[dict],
    roles: list[dict],
    forms: list[dict],
) -> bool:
    """元数据是否过于稀疏（无角色/字典 + 字段多为内部编码或通用标签）。

    仅用于在导出结果里给出告警提示，不再据此凭空补全业务字段。
    """
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
    return (
        generic_labels >= max(3, len(components) // 2)
        or internal_fields >= max(3, total_fields // 2)
    )


def _render_menu_section(lines: list[str], menus: list[dict]) -> None:
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
    _table(lines, ["菜单编码", "菜单名称", "菜单类型", "关联表单/模型", "菜单路径", "说明"], rows)


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
    }


# ─────────────────────────── Dispatcher ───────────────────────────

TOOL_HANDLERS = {
    "read_attachment": execute_read_attachment,
    "run_python": execute_run_python,
    "write_artifact": execute_write_artifact,
    "read_artifact": execute_read_artifact,
    "edit_artifact": execute_edit_artifact,
    "create_artifact_from_attachment": execute_create_artifact_from_attachment,
    "ask_clarifying_question": execute_ask_clarifying_question,
    "export_apaas_app_design_doc": execute_export_apaas_app_design_doc,
}


# 原 4 个 base 工具的 schemas（保持原有 TOOL_SCHEMAS 引用名兼容老代码）
BASE_TOOL_SCHEMAS = TOOL_SCHEMAS

# ── 延迟工具拆分: CORE vs DEFERRED ──────────────────────────────────────────────
# 核心集: 恒在每轮 tools 数组，不延迟。= base 本地工具 + search_tools + 数据驱动的高频 apaas 读。
# search_tools 本体在后续 Task 2 添加到 TOOL_SCHEMAS；这里先把名字加入集合，不影响当前行为。
_BASE_LOCAL_NAMES: set[str] = {s["function"]["name"] for s in TOOL_SCHEMAS}
_CORE_HOT_READS: set[str] = {
    "list_apaas_app_models",
    "list_apaas_app_menus",
    "get_apaas_app_overview",
    "list_apaas_app_dicts",
    "list_apaas_app_roles",
}
CORE_TOOL_NAMES: set[str] = _BASE_LOCAL_NAMES | {"search_tools"} | _CORE_HOT_READS


def split_core_deferred(all_schemas: list[dict]) -> tuple[list[dict], dict[str, dict]]:
    """把全集拆成 (core_schemas 列表, deferred_by_name 字典)。

    core 进每轮 tools，deferred 只列清单（名称 + 描述），按需加载完整 schema。
    """
    core: list[dict] = []
    deferred: dict[str, dict] = {}
    for s in all_schemas:
        name = s.get("function", {}).get("name", "")
        if name in CORE_TOOL_NAMES:
            core.append(s)
        else:
            deferred[name] = s
    return core, deferred


# ── 延迟工具搜索 ──────────────────────────────────────────────────────────────

def _search_hint_for(name: str) -> str:
    """从 tool_registry.yaml search_hint 字段取额外关键词索引；异常时静默返空串。"""
    try:
        from app.tool_registry import search_hints
        return search_hints().get(name, "")
    except Exception:
        return ""


def _tokenize(name: str) -> list[str]:
    """把 snake_case/camelCase 工具名拆成小写词列表，供名称命中打分用。"""
    # camelCase → snake_case (防御性，工具名其实都是 snake_case)
    s = re.sub(r"(?<!^)(?=[A-Z])", "_", name)
    return [p for p in re.split(r"[_\W]+", s.lower()) if p]


def search_deferred_tools(
    query: str,
    deferred_by_name: dict[str, dict],
    limit: int = 8,
) -> list[str]:
    """在 deferred 工具集里搜索匹配 query 的工具名列表。

    两种模式：
    - select: 前缀  → 精确按名称列表返回（逗号分隔），用于 ToolSearch select:<name>,...
    - keyword 搜索  → 对名称 tokens + description + search_hint 打分排序，返 top-limit

    scoring:
      名称词命中 +3，描述/hint 文本命中 +1；分数 0 的排除。
    """
    q = (query or "").strip()
    if q.lower().startswith("select:"):
        want = [x.strip() for x in q[len("select:"):].split(",") if x.strip()]
        return [n for n in want if n in deferred_by_name]

    terms = [w for w in re.split(r"[\s,]+", q.lower()) if w]
    if not terms:
        return []

    scored: list[tuple[int, str]] = []
    for name, schema in deferred_by_name.items():
        desc = (schema.get("function", {}).get("description") or "")
        hint = _search_hint_for(name)
        name_tokens = set(_tokenize(name))
        text = (desc + " " + hint).lower()
        score = 0
        for term in terms:
            if term in name_tokens:
                score += 3
            elif term in text:
                score += 1
        if score > 0:
            scored.append((score, name))

    scored.sort(key=lambda x: (-x[0], x[1]))
    return [n for _, n in scored[:limit]]


def build_deferred_manifest(deferred_by_name: dict[str, dict]) -> str:
    """把延迟工具列成一行清单（name: desc(关键词)），注入 system prompt。

    比完整 schema 小得多；模型据此知道有哪些工具、用前先 search_tools 加载。
    空集时返回空串，不注入任何额外文本。
    """
    if not deferred_by_name:
        return ""
    lines = [
        "\n\n## 可按需加载的工具(先 search_tools 再用)",
        "下面这些工具**不在当前 tools 列表里**;要用,先调 `search_tools`(关键词或 `select:工具名`)把它们加载进来,下一轮即可调用:",
    ]
    for name in sorted(deferred_by_name):
        desc = (deferred_by_name[name].get("function", {}).get("description") or "").strip().replace("\n", " ")
        hint = _search_hint_for(name)
        line = f"- {name}: {desc[:80]}"
        if hint:
            line += f"(关键词: {hint})"
        lines.append(line)
    return "\n".join(lines)


async def _handle_search_tools(args: dict, session, db) -> str:
    """search_tools 工具处理器 — 在延迟工具集里搜索并返回命中名列表。

    handler 签名与其他 TOOL_HANDLERS 一致: (args, session, db) -> str (JSON)
    """
    universe = _LAST_TOOL_SCHEMAS or []
    _core, deferred = split_core_deferred(universe)
    names = search_deferred_tools(args.get("query", ""), deferred)
    if not names:
        return json.dumps(
            {"ok": True, "activated": [], "message": "无匹配工具;换个关键词或用 select:工具名"},
            ensure_ascii=False,
        )
    return json.dumps(
        {
            "ok": True,
            "activated": names,
            "message": f"已加载 {len(names)} 个工具,下一轮可直接调用: {', '.join(names)}",
        },
        ensure_ascii=False,
    )


# search_tools handler registered after its definition (TOOL_HANDLERS dict is above)
TOOL_HANDLERS["search_tools"] = _handle_search_tools


# ── 锁定 app 上下文注入 (Task A4, 2026-06-04) ──────────────────────────────────
# 当 AIChatSession.app_id 非空时，把内部 app_id → (env_id, apaas_app_id) 解析出来，
# 并强制注入到声明了这两参数的 apaas 工具 —— 覆盖 LLM 给的值。
# 这样即使 LLM 幻觉传了别的应用 id，工具也只会操作当前会话锁定的应用。
# 自由会话 (app_id=None) 完全不受影响，行为与之前一致。
# 护栏覆盖两个执行路径：base-handler 工具 (TOOL_HANDLERS，含 export_apaas_app_design_doc)
# 和 MCP bridge 工具 —— schema 门控保证只注入实际声明了这两参数的工具。

_LAST_TOOL_SCHEMAS: list[dict] = []  # get_all_tool_schemas 每次调用后更新，供 _tool_declares_param 用


def _tool_declares_param(tool_name: str, param: str) -> bool:
    """该工具的 schema 是否声明了 param（用 _LAST_TOOL_SCHEMAS 缓存判断）。"""
    for s in _LAST_TOOL_SCHEMAS:
        fn = s.get("function", {})
        if fn.get("name") == tool_name:
            props = (fn.get("parameters") or {}).get("properties") or {}
            return param in props
    return False


async def _resolve_locked_app_ctx(session: "AIChatSession", db: "AsyncSession"):
    """internal session.app_id → (env_id, apaas_app_id)。找不到或异常返 (None, None)。

    结果带 per-session 缓存（_locked_app_ctx 属性），同一会话多次工具调用只查一次 DB。
    """
    cached = getattr(session, "_locked_app_ctx", None)
    if cached is not None:
        return cached
    env_id, apaas_app_id = None, None
    try:
        from app.models import Application
        app = await db.get(Application, int(getattr(session, "app_id", 0) or 0))
        if app:
            env_id = getattr(app, "platform_env_id", None)
            apaas_app_id = getattr(app, "apaas_app_id", None)
    except Exception:
        pass
    session._locked_app_ctx = (env_id, apaas_app_id)
    return (env_id, apaas_app_id)


async def _inject_locked_app_ctx(tool_name: str, args: dict, session: "AIChatSession", db) -> dict:
    """把锁定应用的 env_id / apaas_app_id 注入 args（schema 门控 + 仅非 None 值注入）。"""
    if not getattr(session, "app_id", None) or db is None:
        return args
    env_id, apaas_app_id = await _resolve_locked_app_ctx(session, db)
    out = dict(args)
    if env_id is not None and _tool_declares_param(tool_name, "env_id"):
        out["env_id"] = env_id
    if apaas_app_id and _tool_declares_param(tool_name, "apaas_app_id"):
        out["apaas_app_id"] = apaas_app_id
    return out


def _normalize_workspace_match_key(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lower())


async def _find_existing_app_workspace_for_create(args: dict, session: "AIChatSession", db) -> dict | None:
    """Find a same-name app/self workspace before allowing create_dev_workspace.

    App-locked AIChat is a modification surface by default. If the model tries
    to create a workspace with the same project/display name as an accessible
    workspace for this tenant/user, return that workspace so the model can
    switch to read/edit tools instead of creating a duplicate asset.
    """
    app_id = getattr(session, "app_id", None)
    user_id = getattr(session, "user_id", None)
    if not app_id or not user_id:
        return None

    target_names = {
        _normalize_workspace_match_key(args.get("project_name")),
        _normalize_workspace_match_key(args.get("display_name")),
    }
    target_names.discard("")
    if not target_names:
        return None

    try:
        from app.coding.workspace import WorkspaceManager

        manager = WorkspaceManager()
        rows = manager.list_accessible_workspaces(
            int(user_id),
            [int(app_id)],
            tenant_id=int(getattr(session, "tenant_id", 0) or 0) or None,
        )
    except Exception:
        return None

    scene_type = str(args.get("scene_type") or "").strip()
    for ws in rows:
        ws_project_id = ws.get("project_id")
        if ws_project_id not in (None, "") and str(ws_project_id) != str(app_id):
            continue
        ws_type = str(ws.get("project_type") or "").strip()
        if scene_type and ws_type and ws_type != scene_type:
            continue
        candidate_names = {
            _normalize_workspace_match_key(ws.get("project_name")),
            _normalize_workspace_match_key(ws.get("display_name")),
        }
        candidate_names.discard("")
        if target_names & candidate_names:
            return ws
    return None


def _existing_workspace_reuse_result(existing: dict) -> str:
    ws_id = existing.get("id") or existing.get("ws_id")
    project_name = existing.get("project_name") or ""
    display_name = existing.get("display_name") or project_name or ""
    return json.dumps(
        {
            "ok": False,
            "error_code": "WORKSPACE_ALREADY_EXISTS",
            "message": (
                "当前应用/租户下已经有同名自开发 workspace，不能再新建。"
                f"请复用 ws_id={ws_id} 修改原代码。"
            ),
            "existing_workspace": {
                "ws_id": ws_id,
                "project_name": project_name,
                "display_name": display_name,
                "project_type": existing.get("project_type"),
                "project_id": existing.get("project_id"),
                "status": existing.get("status"),
            },
            "next_steps": [
                f"get_dev_workspace_status(ws_id='{ws_id}')",
                f"glob_workspace / grep_workspace / read_workspace_file 读取 ws_id='{ws_id}' 的现有源码",
                f"edit_workspace_files 或 write_workspace_files 修改 ws_id='{ws_id}'，不要再 create_dev_workspace",
            ],
        },
        ensure_ascii=False,
    )


def _inject_locked_workspace_project_id(tool_name: str, args: dict, session: "AIChatSession") -> dict:
    if tool_name != "create_dev_workspace":
        return args
    app_id = getattr(session, "app_id", None)
    if not app_id or args.get("project_id"):
        return args
    try:
        return {**args, "project_id": int(app_id)}
    except Exception:
        return args


async def get_all_tool_schemas() -> list[dict]:
    """合并 base 工具 + MCP bridge 工具 (按 agent 白名单过滤)。

    每次 agent turn 开始时调用——让"装上新 MCP 工具立即可用"，不用重启 backend。

    2026-05-28: 之前把全部 117 个 MCP 工具无过滤塞给 LLM → 工具过载, agent 挑错工具/
    漏参/反复重写 (实测 generate_app_from_doc 失灵 + write_artifact 缺 filename + 一份文档
    写两个名字). 智能搭建 = unified builder+coding+config agent, 按 tool_registry 白名单砍到
    builder ∪ coding ∪ config (~85), 跟 config_chat 同套路. base 本地工具不在 registry, 永远保留.
    """
    from app.ai_chat.mcp_bridge import get_tool_schemas_openai
    from app.tool_registry import tools_for_agent, load as _load_registry
    try:
        mcp_schemas = await get_tool_schemas_openai()
    except Exception as e:
        # MCP 不可用不影响 base 工具
        import logging as _log
        _log.getLogger(__name__).warning("MCP bridge 加载失败，退化到 base 工具：%s", e)
        mcp_schemas = []
    try:
        # Unified AI Builder uses builder/config tools in the embedded app assistant,
        # while coding tools remain available for self-dev deployment flows.
        allow = (
            set(tools_for_agent("builder"))
            | set(tools_for_agent("coding"))
            | set(tools_for_agent("config"))
        )
        # 2026-06-05: 业务事件功能暂停 —— 生成的自定义节点 Python 不符平台 definesys 规范、
        # 建出来的事件不可执行（详 docs/research-apaas-event-python-spec-2026-06-05.md）。
        # 不让助手用任何业务事件 MCP 工具，免得它继续建坏事件。修好生成后删掉这段即恢复。
        _paused = {
            name for name, meta in _load_registry()["tools"].items()
            if (meta.get("category") == "business_event")
        }
        _paused.add("list_apaas_form_menus_for_event")  # 只为建事件服务的 helper, 一并停
        allow -= _paused
        mcp_schemas = [
            s for s in mcp_schemas
            if s.get("function", {}).get("name") in allow
        ]
    except Exception as e:  # 白名单异常时不拦, 退化到全量 (有总比崩好)
        import logging as _log
        _log.getLogger(__name__).warning("工具白名单过滤失败, 退化到全量 MCP: %s", e)
    global _LAST_TOOL_SCHEMAS
    _LAST_TOOL_SCHEMAS = BASE_TOOL_SCHEMAS + mcp_schemas
    return _LAST_TOOL_SCHEMAS


# 2026-05-28: 这几个 doc-pipeline 工具强依赖 artifact_id 指向"当前会话刚写的设计文档".
# 但 LLM 经常传错/传旧的 artifact_id (跨会话残留 / 幻觉) → 拿错文档建错应用.
# 实测: mega-erp(112 模型) 文档被建成无关的"人才管理系统"(14 HR 模型) — agent 传了别的 artifact_id.
# dispatcher 这里按"当前会话最新 .md artifact"强制纠正 —— 会话是真相, 不信 LLM 给的 id.
_ARTIFACT_DOC_TOOLS = {"generate_app_from_doc", "validate_builder_doc", "submit_design_doc"}


async def _resolve_session_doc_artifact_id(
    session: AIChatSession, db: AsyncSession
) -> int | None:
    """当前会话最新的设计文档 artifact id (优先 .md, 没有则最新任意). 找不到返 None."""
    try:
        rows = (await db.execute(
            select(AIChatArtifact.id, AIChatArtifact.filename)
            .where(AIChatArtifact.session_id == session.id)
            .order_by(desc(AIChatArtifact.id))
        )).all()
        if not rows:
            return None
        for aid, fn in rows:
            if str(fn or "").lower().endswith(".md"):
                return aid
        return rows[0][0]
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("_resolve_session_doc_artifact_id failed: %s", exc)
        return None


async def execute_tool(
    tool_name: str, args: dict, session: AIChatSession, db: AsyncSession
) -> str:
    """工具 dispatcher：base 工具走本地 handler；其他兜底走 MCP HTTP bridge。

    自动塞 session.tenant_id / session.user_id 给 MCP（很多 MCP 工具签名隐式接受
    tenant_id / user_id 做 fallback admin）。

    ⚠️ artifact_id 自愈 (2026-05-28)：doc-pipeline 工具的 artifact_id 由 dispatcher 按
    当前会话最新 .md 强制纠正 —— LLM 传错/传旧 id 会拿错文档建错应用 (实测 mega-erp→人才管理).

    ⚠️ Side-effect intercept (2026-05-21)：generate_app_from_doc / update_app_from_doc
    成功调用时，把 args.md_content 落 AIChatArtifact 表（用户能在右侧面板回看 SPEC）。
    不污染 MCP 工具本身（外部 外部 agent / Claude / Cursor 调那俩工具不受影响）。
    """
    handler = TOOL_HANDLERS.get(tool_name)
    if handler:
        args = await _inject_locked_app_ctx(tool_name, args, session, db)
        try:
            return await handler(args, session, db)
        except Exception as e:
            return f"错误：工具 '{tool_name}' 执行异常 - {e}"

    # 兜底：尝试通过 MCP bridge 调本机 MCP server
    from app.ai_chat.mcp_bridge import list_mcp_tool_names_cached, call_tool as _mcp_call
    if tool_name in list_mcp_tool_names_cached():
        if tool_name == "create_dev_workspace":
            existing = await _find_existing_app_workspace_for_create(args, session, db)
            if existing:
                return _existing_workspace_reuse_result(existing)
            args = _inject_locked_workspace_project_id(tool_name, args, session)
        # artifact_id 自愈：用会话最新设计文档覆盖 LLM 给的 id (防张冠李戴)
        if tool_name in _ARTIFACT_DOC_TOOLS:
            real_id = await _resolve_session_doc_artifact_id(session, db)
            if real_id and str(args.get("artifact_id") or "") != str(real_id):
                import logging
                logging.getLogger(__name__).info(
                    "[ai_chat] %s artifact_id 纠正: LLM=%r → 会话最新 .md=%s (session %s)",
                    tool_name, args.get("artifact_id"), real_id, session.id,
                )
                args = {**args, "artifact_id": real_id}
        # 锁定 app 上下文注入：强制覆盖 LLM 给的 env_id / apaas_app_id (Task A4)
        args = await _inject_locked_app_ctx(tool_name, args, session, db)
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
