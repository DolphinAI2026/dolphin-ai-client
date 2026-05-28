"""AI Coding 主工作台 — HTML 原型生成。读需求基线 → LLM → 单文件 HTML → 存 app_prototypes。"""
from __future__ import annotations
import json
import logging
from typing import Annotated, AsyncIterator

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy import func as sqlfunc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_auth_context, AuthContext
from app.llm_client import LLMClient
from app.mcp_spec_sections import read_spec_section
from app.models.app_prototype import AppPrototype
from app.routes.applications._helpers import _resolve_builder_llm_cfg
from app.routes.applications.spec_chat import _sse

logger = logging.getLogger(__name__)

# 需求基线里要喂给原型的 section — 按 spec_chat.py _section_key_for 真实约定:
#   data_model chapter → section_type="data_model", section_key="main"
#   dict       chapter → section_type="data_model", section_key="dict"
#   roles      chapter → section_type="permission", section_key="global"
#   menus      chapter → section_type="page",       section_key="global"
#
# 注意: VALID_SECTION_TYPES = ("form","list","process","page","permission","data_model")
# 基线代码里的 section_type="spec" 是无效的, 实际约定用上述 4 对组合.
_BASELINE_SECTIONS: list[tuple[str, str, str]] = [
    # (label_for_prompt, section_type, section_key)
    ("数据模型 (models)", "data_model", "main"),
    ("数据字典 (dicts)",   "data_model", "dict"),
    ("角色权限 (roles)",   "permission", "global"),
    ("菜单结构 (menus)",   "page",       "global"),
]

_PROMPT_HEADER = """你是 AI Coding 的 UI 原型设计师。基于下面的应用需求基线，生成一个**单文件 HTML 原型**，供业务用户确认 UI。

硬性要求：
1. 输出**完整单文件 HTML**（<!DOCTYPE html> 开头），不依赖任何本地资源。
2. 只用 CDN 引 Element Plus + ECharts；其余内联 <style>/<script>。
3. 内置**mock 数据**，不调用任何真实接口、不写任何 token/key/真实地址。
4. 企业级后台风格，清晰稳重，信息密度适中。
5. 每个可点选的功能区块（卡片/表格行/图表/按钮）加属性 `data-block="<简短中文标签>"`，供点选交互使用。
6. HTML 必须能在 iframe 中独立预览。

应用需求基线：
"""


async def build_prototype_prompt(db: AsyncSession, app_id: int) -> str:
    """读 app 的需求基线 spec sections → 拼成 LLM prompt。

    读 4 个 section (数据模型/字典/角色/菜单)，有数据就拼入，没初始化的跳过。
    本函数不调 LLM、不落库 (那是 Task 3 的职责)。
    """
    parts: list[str] = [_PROMPT_HEADER]
    for label, section_type, section_key in _BASELINE_SECTIONS:
        res = await read_spec_section(db, app_id, section_type, section_key)
        if res.get("ok") and res.get("exists"):
            spec_json = res["section"].get("spec_json", {})
            if not spec_json:
                continue
            parts.append(f"\n## {label}\n{json.dumps(spec_json, ensure_ascii=False, indent=2)}")
    parts.append("\n\n现在输出完整单文件 HTML（只输出 HTML，不要解释）：")
    return "".join(parts)


# ---------------------------------------------------------------------------
# LLM 流式产出 HTML
# ---------------------------------------------------------------------------


async def _llm_html_stream(
    prompt: str, db: AsyncSession, tenant_id: int, app_id: int
) -> AsyncIterator[str]:
    """调 LLMClient 流式产出 HTML chunk，每次 yield 一个 delta string。

    按 spec_chat.py 的模式: _resolve_builder_llm_cfg → LLMClient →
    chat_completion_stream(messages, max_tokens) → 解析 OpenAI delta JSON → yield content。
    """
    llm_cfg = await _resolve_builder_llm_cfg(db, tenant_id, conversation_id=None)
    if not llm_cfg:
        raise RuntimeError(f"租户 {tenant_id} 没有可用的 LLM 配置，无法生成原型")

    llm = LLMClient(
        api_key=llm_cfg["api_key"],
        base_url=llm_cfg["base_url"],
        model=llm_cfg["model"],
    )
    messages = [{"role": "user", "content": prompt}]
    async for chunk_str in llm.chat_completion_stream(
        messages,
        max_tokens=llm_cfg.get("max_tokens", 4096),
    ):
        try:
            chunk = json.loads(chunk_str)
        except Exception:
            continue
        if not isinstance(chunk, dict):
            continue
        choices = chunk.get("choices") or []
        if not choices:
            continue
        delta = (choices[0] or {}).get("delta") or {}
        content = delta.get("content") or ""
        if content:
            yield content


# ---------------------------------------------------------------------------
# 版本号计算
# ---------------------------------------------------------------------------


async def _next_version(db: AsyncSession, app_id: int) -> int:
    """返回 app_id 的下一个原型版本号 (current_max + 1，从 1 开始)。"""
    cur = (await db.execute(
        select(sqlfunc.max(AppPrototype.version)).where(AppPrototype.app_id == app_id)
    )).scalar()
    return (cur or 0) + 1


# ---------------------------------------------------------------------------
# SSE event generator
# ---------------------------------------------------------------------------


async def _generate_event_stream(
    db: AsyncSession, app_id: int, tenant_id: int, user_id: int
):
    """SSE 主生成器 — 读基线 → LLM → 校验 → 落库 → 吐 started/progress/error/prototype_ready。"""
    yield _sse("started", {"app_id": app_id})

    # ── 1. 构造 prompt ────────────────────────────────────────────────────
    try:
        prompt = await build_prototype_prompt(db, app_id)
    except Exception as exc:
        logger.exception("prototype: build_prototype_prompt failed")
        yield _sse("error", {"message": f"构造 prompt 失败：{exc}"})
        return

    # ── 2. LLM 流式产出 HTML ─────────────────────────────────────────────
    html_parts: list[str] = []
    try:
        async for chunk in _llm_html_stream(prompt, db, tenant_id, app_id):
            html_parts.append(chunk)
            yield _sse("progress", {"chars": sum(len(p) for p in html_parts)})
    except Exception as exc:
        logger.exception("prototype: _llm_html_stream failed")
        yield _sse("error", {"message": f"原型生成失败：{exc}"})
        return

    # ── 3. 校验输出 ──────────────────────────────────────────────────────
    html = "".join(html_parts).strip()
    if not html:
        yield _sse("error", {"message": "LLM 输出为空，原型生成失败"})
        return
    html_lower = html.lower()
    if "<body" not in html_lower and "<html" not in html_lower:
        yield _sse("error", {"message": "生成内容不是合法 HTML（缺 <body> 或 <html> 标签）"})
        return

    # ── 4. 落库 ──────────────────────────────────────────────────────────
    try:
        version = await _next_version(db, app_id)
        proto = AppPrototype(
            app_id=app_id,
            tenant_id=tenant_id,
            version=version,
            html_content=html,
            created_by=user_id,
        )
        db.add(proto)
        await db.commit()
        await db.refresh(proto)
    except Exception as exc:
        logger.exception("prototype: DB persist failed")
        yield _sse("error", {"message": f"原型落库失败：{exc}"})
        return

    yield _sse("prototype_ready", {"prototype_id": proto.id, "version": proto.version})


# ---------------------------------------------------------------------------
# Router + Endpoint
# ---------------------------------------------------------------------------

router = APIRouter()


@router.post("/{app_id}/prototype/generate")
async def generate_prototype(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """SSE endpoint: POST /api/applications/{app_id}/prototype/generate

    读需求基线 → LLM 流式产出单文件 HTML → 落库 → SSE 吐事件。
    事件序列: started → progress(N 次) → prototype_ready | error
    """
    from sse_starlette.sse import EventSourceResponse
    return EventSourceResponse(
        _generate_event_stream(
            db,
            app_id=app_id,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user.id,
        )
    )
