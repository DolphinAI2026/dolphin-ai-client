"""Open Design MCP Server — 2026-05-13（独立 FastMCP 实例）

把 `app/resources/open-design/` 下的 craft 设计原则 + 精选 20 品牌 design system
包装为 4 个 MCP 工具。

**架构决策**：本服务**独立于主 MCP（apaas-builder-ai 60+9 工具）**，自起一个
FastMCP 实例，由 main.py mount 到独立路径 `/api/mcp-design/mcp`。设计意图：

  - 零侵入：现有 4 个 dolphin agent 配的"AI-aPaaS-*" MCP 服务工具列表一行不动
  - 解耦：升级 / 回滚本服务时不影响主 MCP；dolphin admin 里表现为独立服务条目
  - 公网 URL：`https://df-aigc.dfy.definesys.cn/mcp-server/api/mcp-design/mcp`
  - auth：复用主 MCP 的 _McpAuthMiddleware（同一份 MCP_API_KEY），见 main.py

设计：
  - 静态只读资源，无 tenant / user 隔离，所有 agent 共享同一份内容
  - name 参数做 path traversal 防护（禁 / 和 ..）
  - 文件不存在走结构化 _business_error 提示 agent 先调 list

资源归属：nexu-io/open-design（MIT），详见 `resources/open-design/ATTRIBUTION.md`
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# 2026-05-13: mcp 1.27 把 TransportSecuritySettings 移走/改名了。本服务跑在 nginx
# ingress 后，不需要 DNS rebinding 保护（ingress 已校验 Host header），所以直接不传
# transport_security 参数。如果 mcp 后续版本恢复该 API，可以再加 try/import。

logger = logging.getLogger(__name__)


_RESOURCES_DIR = Path(__file__).resolve().parent / "resources" / "open-design"
_CRAFT_DIR = _RESOURCES_DIR / "craft"
_DS_DIR = _RESOURCES_DIR / "design-systems"


# ─────────────────────── FastMCP 实例（独立）───────────────────────
# 跟主 mcp_server.py 同款 DNS rebinding 保护开关；stateless_http + json_response
# 是 dolphin 兼容关键（避免 mcp-session-id 跟踪失败和 SSE 解析问题）

design_mcp = FastMCP(
    "open-design",
    instructions=(
        "Open Design 设计能力库（来自 nexu-io/open-design MIT）。"
        "提供 11 篇 craft 设计原则文档 + 20 个主流品牌 design system 完整规范。"
        "生成 UI / 前端代码前先调 list_design_principles 与 list_design_systems 探索；"
        "强烈建议先 get_design_principle('anti-ai-slop') 规避 AI 痕迹。"
    ),
    stateless_http=True,
    json_response=True,
)


# ─────────────────────── helpers ───────────────────────


def _safe_name(name: str) -> str:
    """防 path traversal：strip + 禁 / \\ 和 .."""
    if not name:
        return ""
    cleaned = name.strip().lower()
    if "/" in cleaned or ".." in cleaned or "\\" in cleaned:
        return ""
    return cleaned


def _business_error(*, op: str, error_text: str, extra: dict | None = None) -> dict:
    """简版 business error dict（跟主 mcp_server 同形状，但本服务无业务错误码族，故不复用）。"""
    base: dict = {"ok": False, "op": op, "message": (error_text or "").strip()}
    if extra:
        base.update(extra)
    return base


# ─────────────────────── 4 个 MCP 工具 ───────────────────────


@design_mcp.tool()
async def list_design_principles() -> dict:
    """列出 open-design craft 设计原则文档清单。

    每篇是一个独立的设计原则 markdown（typography / color / anti-ai-slop /
    accessibility-baseline / state-coverage / form-validation / animation-discipline
    / laws-of-ux 等）。

    **强烈建议** agent 在写任何前端代码 / 生成 UI 设计稿之前先调
    `get_design_principle("anti-ai-slop")` 拿到 7 条 AI 痕迹铁律（禁默认 indigo /
    禁 emoji 当图标 / 禁两段 trust 渐变 / 禁假数据 …），避免输出"一眼 AI"风格的 UI。
    """
    if not _CRAFT_DIR.is_dir():
        return _business_error(
            op="list_design_principles",
            error_text="craft 资源目录不存在",
            extra={"error_code": "RESOURCE_DIR_MISSING", "expected_path": str(_CRAFT_DIR)},
        )
    names = sorted(
        p.stem for p in _CRAFT_DIR.glob("*.md")
        if p.stem.upper() != "README"
    )
    return {
        "ok": True,
        "count": len(names),
        "principles": names,
        "hint": "调 get_design_principle(name) 拿某篇完整 markdown",
    }


@design_mcp.tool()
async def get_design_principle(name: str) -> dict:
    """读取指定设计原则文档的完整 markdown。

    Args:
        name: 来自 `list_design_principles` 的名字，例如 "anti-ai-slop" /
              "typography-hierarchy" / "form-validation"
    """
    safe = _safe_name(name)
    if not safe:
        return _business_error(
            op="get_design_principle",
            error_text="name 不能为空且不能含 / 或 ..",
            extra={"error_code": "PARAM_INVALID"},
        )
    path = _CRAFT_DIR / f"{safe}.md"
    if not path.is_file():
        return _business_error(
            op="get_design_principle",
            error_text=f"设计原则 {safe} 不存在",
            extra={
                "error_code": "PRINCIPLE_NOT_FOUND",
                "hint": "调 list_design_principles() 看可用清单",
            },
        )
    return {
        "ok": True,
        "name": safe,
        "content": path.read_text(encoding="utf-8"),
    }


@design_mcp.tool()
async def list_design_systems() -> dict:
    """列出 open-design 精选 20 个主流品牌 design system 清单。

    每个 brand 的 DESIGN.md 是 200-300 行 markdown，含 visual theme & atmosphere /
    color palette & roles / typography & hierarchy / spacing & layout / motion &
    interaction 等完整体系。

    覆盖 6 大类：消费品牌（apple/airbnb/notion）、开发者工具（vercel/github/
    cursor/claude/supabase）、enterprise（ibm/stripe/ant）、低代码搭建（airtable/
    webflow/figma/framer）、AI 时代标杆（linear-app/shadcn）、团队协作（slack/
    discord）、现代消费应用（material）。

    Agent 应在选定一个品牌方向后调 `get_design_system(name)` 拿规范，作为生成
    UI 的 token + 风格依据；不要凭空想象品牌的设计语言。
    """
    if not _DS_DIR.is_dir():
        return _business_error(
            op="list_design_systems",
            error_text="design-systems 资源目录不存在",
            extra={"error_code": "RESOURCE_DIR_MISSING", "expected_path": str(_DS_DIR)},
        )
    brands = sorted(p.name for p in _DS_DIR.iterdir() if p.is_dir())
    return {
        "ok": True,
        "count": len(brands),
        "brands": brands,
        "hint": "调 get_design_system(name) 拿某品牌完整 DESIGN.md（200-300 行）",
    }


@design_mcp.tool()
async def get_design_system(name: str) -> dict:
    """读取指定品牌的 design system 完整 markdown。

    Args:
        name: 来自 `list_design_systems` 的名字，例如 "apple" / "shadcn" /
              "ant" / "linear-app" / "stripe"
    """
    safe = _safe_name(name)
    if not safe:
        return _business_error(
            op="get_design_system",
            error_text="name 不能为空且不能含 / 或 ..",
            extra={"error_code": "PARAM_INVALID"},
        )
    path = _DS_DIR / safe / "DESIGN.md"
    if not path.is_file():
        return _business_error(
            op="get_design_system",
            error_text=f"design system {safe} 不存在",
            extra={
                "error_code": "BRAND_NOT_FOUND",
                "hint": "调 list_design_systems() 看可用清单",
            },
        )
    return {
        "ok": True,
        "name": safe,
        "content": path.read_text(encoding="utf-8"),
    }
