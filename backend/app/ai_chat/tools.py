"""AIChat agent 工具集 — 4 个核心工具。

OpenAI tool calling 格式：每个工具有 schema（给 LLM 看）+ 实现（execute_*）。
Dispatcher (`execute_tool`) 根据 tool_name 路由到具体实现。
"""

from __future__ import annotations

import asyncio
import json
import os
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
                "典型用法：写设计文档、写分析报告。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "产出物文件名，例如 '设计文档.md'",
                    },
                    "content": {
                        "type": "string",
                        "description": "完整内容",
                    },
                    "format": {
                        "type": "string",
                        "enum": ["md", "json", "txt", "html", "py"],
                        "description": "格式（默认 md）",
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
    return (
        f"已写入产出物 '{filename}' (v{new_version}, {len(content)} 字符)。"
        f"用户已能在右侧面板查看。"
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


# ─────────────────────────── Dispatcher ───────────────────────────

TOOL_HANDLERS = {
    "read_attachment": execute_read_attachment,
    "run_python": execute_run_python,
    "write_artifact": execute_write_artifact,
    "ask_clarifying_question": execute_ask_clarifying_question,
}


async def execute_tool(
    tool_name: str, args: dict, session: AIChatSession, db: AsyncSession
) -> str:
    handler = TOOL_HANDLERS.get(tool_name)
    if not handler:
        return f"错误：未知工具 '{tool_name}'"
    try:
        return await handler(args, session, db)
    except Exception as e:
        return f"错误：工具 '{tool_name}' 执行异常 - {e}"
