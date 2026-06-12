"""Help Assistant — aPaaS Builder AI 内置产品助手。

启动时加载 docs/help/*.md 作为知识库，注入 system prompt；
对话流式（SSE），复用 harness/llm_resolver 的统一 LLM 解析。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated, AsyncGenerator, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import AuthContext, get_auth_context
from app.harness.llm_resolver import resolve_llm_config, stream_with_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/help", tags=["help-assistant"])


# ── 知识库加载（启动时一次） ──────────────────────────────────

def _find_help_dir() -> Optional[Path]:
    """从当前文件向上找 docs/help 目录。"""
    current = Path(__file__).resolve()
    for parent in [current.parent, *current.parents]:
        candidate = parent / "docs" / "help"
        if candidate.exists() and candidate.is_dir():
            return candidate
        candidate = parent.parent / "docs" / "help" if parent.parent else None
        if candidate and candidate.exists() and candidate.is_dir():
            return candidate
    return None


def _load_knowledge_base() -> str:
    """读 docs/help/*.md（除 README）并按文件名排序拼接。"""
    help_dir = _find_help_dir()
    if not help_dir:
        logger.warning("docs/help 目录未找到，help-assistant 将仅有产品基础描述")
        return "（知识库未加载，请检查 docs/help 目录是否存在）"

    chunks: list[str] = []
    for md in sorted(help_dir.glob("*.md")):
        if md.name.lower() == "readme.md":
            continue
        try:
            text = md.read_text(encoding="utf-8")
            chunks.append(f"---\n# 来源: {md.name}\n\n{text}")
        except Exception as e:
            logger.warning("读取 %s 失败: %s", md, e)

    if not chunks:
        return "（知识库为空）"
    return "\n\n".join(chunks)


_KNOWLEDGE_BASE: str = _load_knowledge_base()


# ── 路径 → 模块名 / 上下文提示 ──────────────────────────────

_PATH_LABELS: list[tuple[str, str, str]] = [
    # (前缀匹配, 模块名, 简短说明)
    ("/ai-chat", "AI 对话", "用对话整理需求 / 整合材料，产出标准设计文档"),
    ("/chat", "AI 搭建", "把设计文档喂给 AI 生成 SPEC + 应用配置 → 部署到平台"),
    ("/coding", "AI 编码 (睿鲸 IDE)", "对话生成自开发组件 / 页面 / 接口"),
    ("/apps", "应用列表"),
    ("/platform-envs", "平台环境 / LLM 配置"),
    ("/tenant-users", "成员管理"),
    ("/", "首页"),
]


def _build_path_context(path: str) -> str:
    """根据 path 生成「用户现在在哪」的 prompt 片段。"""
    p = (path or "").split("?")[0].rstrip("/") or "/"
    for prefix, name, *rest in _PATH_LABELS:
        if p == prefix or p.startswith(prefix + "/") or (prefix == "/" and p == "/"):
            desc = rest[0] if rest else ""
            extra = f"——{desc}" if desc else ""
            return (
                f"【用户当前所在页面】\n"
                f"路径：`{path}`\n"
                f"模块：**{name}**{extra}\n\n"
                f"回答时优先围绕这个模块。如果用户问的是别的模块，再扩展。"
            )
    return f"【用户当前所在页面】\n路径：`{path}`（未识别的路由，按知识库回答即可）"


def _system_prompt() -> str:
    return f"""你是 aPaaS Builder AI 产品的内置助手。你的职责：

- 回答用户关于产品功能、使用方式、模块差异、典型流程的问题
- 引导用户走通"需求 → 应用"的最短路径
- 用简洁中文回答，必要时给出 步骤 1/2/3 或表格
- 对模块路径用 `代码风格` 标注（如 `/devops` / `+ 创建提案`）
- 如果用户问的内容不在知识库里，明确说"我不确定"，建议去查 GitHub Issues 或联系管理员
- 不要编造功能。只描述知识库里有的能力

【⚡ 关键能力：动作链接】

当用户问"能不能帮我打开/进入/跳转到某模块"，或者你回答里建议用户去某个页面时，**必须**附带一个可点击的动作链接，让用户点一下就跳过去，不要只告诉路径让用户自己点。

格式：标准 markdown 链接，但 href 用 `#nav:/路径` 前缀：
- `[去 AI 编码](#nav:/coding)`
- `[打开 DevOps](#nav:/devops)`
- `[去应用列表](#nav:/apps)`

前端会把 `#nav:/xxx` 链接渲染成醒目的"跳转按钮"，用户点击会自动 router.push 跳转。

可用路径：
- `/` 首页
- `/apps` 应用列表
- `/ai-chat` AI 对话
- `/chat` AI 搭建（不带 app_id 是新建态）
- `/coding` AI 编码
- `/devops` DevOps
- `/platform-envs?tab=llm` LLM 配置
- `/platform-envs?tab=envs` 平台环境
- `/tenant-users` 成员管理

**示例**

用户："能帮我进入 coding 页面吗？"
✅ 正确："好的。[去 AI 编码](#nav:/coding) 即可打开。在那里你可以描述组件需求，AI 会读规范、写代码、跑预览。"
❌ 错误："可以。请打开左侧导航的 AI 编码，或访问 /coding。"（只说路径不给链接 = 没兑现）

用户："想做个完整的 web 应用"
✅ 正确："完整应用的二次开发走 [AI 编码](#nav:/coding)（睿鲸 IDE 里对话生成自开发组件 / 页面 / 接口）。"

【产品知识库】

{_KNOWLEDGE_BASE}

【回答风格】
- 第一句直接给答案，再展开
- 短句 + 列表，避免大段叙述
- 引用具体路径 / 按钮名让用户能直接照做
- 凡是涉及"去某页面"，**永远配 `#nav:/path` 链接**"""


# ── 请求 / 流式响应 ──────────────────────────────────────────

class HelpMessage(BaseModel):
    role: str  # 'user' | 'assistant'
    content: str


class HelpChatRequest(BaseModel):
    messages: list[HelpMessage]
    selected_llm_config_id: Optional[int] = None
    # 用户当前所在路由（前端传 useRoute().fullPath），用于让助手"知道你在哪"
    current_path: Optional[str] = None


@router.post("/chat")
async def help_chat(
    req: HelpChatRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """流式对话：SSE。客户端按 `data: {chunk}\\n\\n` 解析，[DONE] 结束。"""
    # 拼 messages: system + (可选)当前路径上下文 + 用户历史
    api_messages: list[dict] = [{"role": "system", "content": _system_prompt()}]
    if req.current_path:
        # 把"用户当前所在路径"作为额外 system 注入，独立成段更便于 LLM 抓取
        path_hint = _build_path_context(req.current_path)
        if path_hint:
            api_messages.append({"role": "system", "content": path_hint})
    for m in req.messages[-20:]:  # 防止过长，只保留最近 20 条
        if m.role not in ("user", "assistant"):
            continue
        if not (m.content or "").strip():
            continue
        api_messages.append({"role": m.role, "content": m.content})

    if not api_messages or api_messages[-1]["role"] != "user":
        async def _err() -> AsyncGenerator[str, None]:
            yield 'data: {"error": "messages 末尾必须是 user"}\n\n'
            yield "data: [DONE]\n\n"

        return StreamingResponse(_err(), media_type="text/event-stream")

    # 解析 LLM 配置
    config = await resolve_llm_config(
        db,
        tenant_id=ctx.tenant_id,
        purpose="all",
        selected_config_id=req.selected_llm_config_id,
    )

    async def _stream() -> AsyncGenerator[str, None]:
        try:
            async for chunk in stream_with_config(config, api_messages, max_tokens=2048):
                # chunk 是 OpenAI 风格 JSON 字符串：{"choices":[{"delta":{"content":"..."}}]}
                # 我们提取出 delta.content 然后用更简单的格式发给前端，
                # 避免前端再 parse 整个 OpenAI 响应。
                try:
                    obj = json.loads(chunk)
                    delta = obj.get("choices", [{}])[0].get("delta", {})
                    text = delta.get("content")
                    if text:
                        payload = json.dumps({"delta": text}, ensure_ascii=False)
                        yield f"data: {payload}\n\n"
                except Exception:
                    continue
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.exception("help-chat stream failed: %s", e)
            err = json.dumps({"error": str(e)[:200]}, ensure_ascii=False)
            yield f"data: {err}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


# ── 知识库元信息（前端可显示"基于 N 篇文档"） ─────────────────

@router.get("/meta")
async def help_meta(_: Annotated[AuthContext, Depends(get_auth_context)]):
    help_dir = _find_help_dir()
    if not help_dir:
        return {"kb_files": 0, "kb_chars": 0}
    files = [p for p in help_dir.glob("*.md") if p.name.lower() != "readme.md"]
    return {
        "kb_files": len(files),
        "kb_chars": len(_KNOWLEDGE_BASE),
        "files": [p.name for p in sorted(files)],
    }
