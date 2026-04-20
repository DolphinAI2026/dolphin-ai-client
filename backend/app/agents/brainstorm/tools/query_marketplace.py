"""query_marketplace tool — 检索相似既有 Spec 作为参考。

MVP 行为：返回空列表（specs 表在 P2.3 才建）。
架构留作占位，让 agent 可以调用而不破坏 system prompt 承诺的 tool 集。

未来升级（P2.3+）：
- 按 scene_type + keyword 做向量/关键词混合检索
- 返回 top-K {spec_id, display_name, similarity, summary}
- 配合 metadata.reference_component_ids 让 CodingAgent 能参考
"""
from __future__ import annotations

from typing import Any

from app.agents.brainstorm.config import MARKETPLACE_TOP_K
from app.agents.brainstorm.state import BrainstormState
from app.agents.types import AgentContext, Tool, ToolResult

_QUERY_MARKETPLACE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "keywords": {
            "type": "string",
            "description": "检索关键词。中文或英文均可。例：评分 / rating star / 多选下拉",
        },
        "scene_filter": {
            "type": "string",
            "description": (
                "可选 — 过滤场景。不填时全库搜索。"
                "取值与 scene_type 一致：web_component_dual / web_page / ..."
            ),
        },
        "top_k": {
            "type": "integer",
            "minimum": 1,
            "maximum": 20,
            "description": f"返回条数上限，默认 {MARKETPLACE_TOP_K}",
        },
    },
    "required": ["keywords"],
    "additionalProperties": False,
}


def build_query_marketplace_tool(state: BrainstormState) -> Tool:
    async def execute(args: dict[str, Any], ctx: AgentContext) -> ToolResult:
        keywords = str(args.get("keywords", "")).strip()
        if not keywords:
            return ToolResult(success=False, content="keywords 不能为空", error="empty_keywords")

        scene_filter = args.get("scene_filter")
        top_k = int(args.get("top_k", MARKETPLACE_TOP_K))
        top_k = max(1, min(20, top_k))

        # 防重复检索
        if keywords in state.marketplace_queries:
            return ToolResult(
                success=True,
                content=f"关键词『{keywords}』已检索过，未发现额外匹配。",
                data={"results": [], "repeat": True},
            )
        state.marketplace_queries.append(keywords)

        # —— MVP 占位实现 —— #
        # P2.3 接 specs 表后改为真实检索
        results: list[dict[str, Any]] = []

        if not results:
            return ToolResult(
                success=True,
                content=(
                    f"未找到与『{keywords}』匹配的既有 Spec（marketplace 当前为空或未命中）。"
                    "请基于需求本身继续推进，不要因没参考就不动。"
                ),
                data={"results": [], "keywords": keywords, "scene_filter": scene_filter},
            )

        # 有结果（未来代码路径）
        lines = [f"找到 {len(results)} 个相似 Spec：", ""]
        for r in results:
            lines.append(
                f"- [{r.get('spec_id')}] {r.get('display_name')} "
                f"(scene={r.get('scene_type')}, similarity={r.get('similarity', 0):.2f})"
            )
        return ToolResult(
            success=True,
            content="\n".join(lines),
            data={"results": results, "keywords": keywords},
        )

    return Tool(
        name="query_marketplace",
        description=(
            "检索既有 Spec（marketplace）作为参考。可选地按场景过滤。"
            "适合在 emit_spec 前确认是否已有相似组件可复用。"
        ),
        parameters_schema=_QUERY_MARKETPLACE_SCHEMA,
        execute=execute,
        idempotent=True,
    )
