"""SpecAgent: drives an LLM tool loop to mutate a SPEC object.

Pattern adapted from app/coding/vibe_agent.py:170-340 — same OpenAI-compatible
streaming + parallel tool_calls + JSON arg accumulation. Simpler because no
filesystem/workspace concerns; tool dispatch is pure SPEC mutation.
"""

from __future__ import annotations
import json
import httpx
from dataclasses import dataclass
from typing import AsyncIterator, Optional

from app.spec.schema import Spec, Phase
from app.spec.tools import TOOL_DEFINITIONS, dispatch_tool, ToolError


SPEC_GATHERING_PROMPT = """你是 aPaaS 业务分析师。当前 SPEC 状态：
{spec_summary}

【硬规则】
1. 首轮回复必须只调用 ask_clarifying_question tool 3-5 次，禁止任何 add_/set_。
   第一个问题必须问真实业务主流程：起点、终点、关键状态流转、是否审批/扣库存/盘点/预警。
   例如耗材管理问"入库→库存→出库是否是主链路，是否还包含盘点、预警、补货？"。
   不要把"需求成稿/表单承载/权限分配/构建发布"当成业务流程。
2. 第二轮起，根据用户回答调 set_goal / add_role / add_object，
   每次问完一个领域再继续问下一个。
3. 禁止在对话内容里写 "## 系统核心模型" "让我帮你设计" 这类元描述。
4. 当 completeness ≥ 0.6 且无 blocking decision 时，调 transition_phase("drafting")。

【tool 调用纪律】
- add_* tool 调用时 confirmed 必须为 false，等用户在 UI 确认。
- 不要一次塞 10 个 tool；每轮 ≤ 5 个 tool 调用。
- ask_clarifying_question 是结构化记录，不是用户可读回复；凡是需要用户确认的问题，必须同时用自然语言写在本轮回复里。
- 除需要用户回答的问题外，不要在对话文本里复述已写入的 SPEC 内容。

【对话语言】
- 用业务语言，对业务用户避免"枚举""数据模型"等技术术语。
- 一次只问一个核心问题，对话节奏像顾问聊需求。
"""


SPEC_DRAFTING_PROMPT = """你正在整理 SPEC 草案。当前 SPEC：
{spec_summary}

【任务】
1. 把 gathering 阶段的零散信息整理成完整 SPEC：补全 fields、推断 dicts、生成 permissions 默认规则。
2. 推断的内容用 add_/update_，confirmed=false，让用户审。
3. 用户主要在对话里确认、忽略或调整；右侧只是结构化预览，你再调对应 tool。
4. 所有项 confirmed=true 且无 blocking decision 时，调 transition_phase("generating")。

【禁止】
- 禁止在用户没说"确认"时主动调 confirm_*。
- 禁止跳回 gathering（除非用户明确说"重来 / 这部分需求要改"）。
- 禁止在对话文本中整段重写 SPEC 内容（用 tool 而不是文本）。

【对话语言】
- 简短解释你正在做什么（"我已经补了 3 个权限规则，请你确认"），不要长篇大论。
- 需要用户确认的内容必须在对话里说清楚；右侧只是结构化预览。
"""


SPEC_BOOTSTRAP_SILENT_PROMPT = """你正在从一份完整的需求文档自动初始化 SPEC。
文档已经过用户预审，将其完整内容当成"用户确认过的事实"对待，不需要再问澄清问题。

【你的任务】
1. 阅读文档，识别业务目标、角色、数据对象（含字段）、字典、权限规则。
2. 用 set_goal / add_role / add_object / add_dict / add_permission 一次性写入 SPEC（confirmed=false）。
3. 写完后用 confirm_* 把所有项目标记为 confirmed=true（用户已认可文档内容）。
4. 调 transition_phase("ready") 完成 bootstrap。
5. 不要 ask_clarifying_question，文档已经覆盖一切。

【纪律】
- 字段类型用中文（"单行输入"/"数字"/"下拉单选"/"单据号"等）。
- code 全部 snake_case，object code 加 t_ 前缀。
- 权限：每个 object 至少一条 role="all" 或具体角色规则。
- 不要在对话文本里复述文档内容（用 tool 而不是文本）。

文档：
---
{doc_text}
---
"""


SPEC_BOOTSTRAP_INTERACTIVE_PROMPT = """你正在从一份初稿文档预填 SPEC，但文档不够规范，需要用户审核。

【流程】
1. 用 add_*/set_goal 把文档里识别出的元素写入 SPEC（confirmed=false，让用户在 UI 审）。
2. 对文档里语义模糊或缺失的字段，用 ask_clarifying_question 标记。
3. 写完进入 drafting phase: transition_phase("drafting")。
4. 不要主动 confirm_*。

文档：
---
{doc_text}
---
"""


SPEC_BOOTSTRAP_DIFF_PROMPT = """你正在基于已存在的 SPEC 应用文档增量。

当前 SPEC：
{spec_summary}

新文档（V2）：
---
{doc_text}
---

【任务】
1. 找出 V2 相对于现有 SPEC 的差异（新增/修改/删除）。
2. 用 add_*/update_*/dismiss_* 应用差异，confirmed=false 让用户审。
3. 进入 drafting phase: transition_phase("drafting")。
4. 不要 confirm_*；不要复述已有 SPEC 的不变项。

【字段语义】
- code 不变 → 视作"修改"，用 update_*
- code 不存在了 → 视作"删除"，用 dismiss_*
- 新 code 出现 → 视作"新增"，用 add_*
"""


def build_prompt(spec: Spec) -> str:
    summary = _summarize_spec(spec)
    if spec.phase == Phase.GATHERING:
        return SPEC_GATHERING_PROMPT.format(spec_summary=summary)
    if spec.phase == Phase.DRAFTING:
        return SPEC_DRAFTING_PROMPT.format(spec_summary=summary)
    # generating/ready phases don't run agent (handled by converter)
    raise ValueError(f"SpecAgent should not run in phase={spec.phase.value}")


def _summarize_spec(spec: Spec) -> str:
    c = spec.completeness
    parts = [
        f"phase={spec.phase.value}",
        f"completeness={c.confirmed}/{c.total}",
        f"goal={spec.goal.title if spec.goal else 'unset'}",
        f"roles={[r.code for r in spec.roles]}",
        f"objects={[o.code for o in spec.objects]}",
        f"dicts={[d.code for d in spec.dicts]}",
        f"pending_decisions={[(d.id, d.topic, d.blocking) for d in spec.decisions_pending]}",
    ]
    return " | ".join(parts)


@dataclass
class SpecAgentEvent:
    kind: str  # "assistant_delta" | "tool_call" | "tool_result" | "tool_error" | "spec_patch" | "final"
    spec: Spec
    text: Optional[str] = None
    tool_name: Optional[str] = None
    tool_args: Optional[dict] = None
    message: Optional[str] = None


async def _open_stream(client: httpx.AsyncClient, base_url: str, api_key: str, payload: dict):
    """Indirection for testing — async generator yielding SSE lines.

    Tests patch this with a sync function returning an async iterable
    (e.g. FakeLLMStream). Since this is `async def ... yield`, calling
    `_open_stream(...)` returns an async generator without needing await.
    """
    async with client.stream(
        "POST",
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
    ) as stream:
        if stream.status_code != 200:
            body = await stream.aread()
            raise RuntimeError(
                f"LLM API {stream.status_code}: {body[:300].decode(errors='replace')}"
            )
        async for line in stream.aiter_lines():
            yield line


class SpecAgent:
    def __init__(
        self,
        llm_base_url: str,
        llm_api_key: str,
        llm_model: str,
        max_turns: int = 12,
    ):
        self.base_url = llm_base_url
        self.api_key = llm_api_key
        self.model = llm_model
        self.max_turns = max_turns

    async def run(
        self,
        spec: Spec,
        user_message: str,
        history: Optional[list[dict]] = None,
    ) -> AsyncIterator[SpecAgentEvent]:
        """Drive one LLM turn-loop over the SPEC. Yields events; mutates spec in place.

        history: optional prior conversation messages [{"role": ..., "content": ...}]
        """
        history = history or []
        system_prompt = build_prompt(spec)
        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            *history,
            {"role": "user", "content": user_message},
        ]

        full_content = ""
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10, read=300, write=10, pool=10)
        ) as client:
            for turn in range(self.max_turns):
                payload = {
                    "model": self.model,
                    "messages": messages,
                    "tools": TOOL_DEFINITIONS,
                    "max_tokens": 4096,
                    "temperature": 0.2,
                    "stream": True,
                }
                full_content = ""
                tool_calls_map: dict = {}

                stream = _open_stream(client, self.base_url, self.api_key, payload)
                async for line in stream:
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    if delta.get("content"):
                        full_content += delta["content"]
                        yield SpecAgentEvent(
                            kind="assistant_delta", spec=spec, text=delta["content"]
                        )
                    if delta.get("tool_calls"):
                        for tc in delta["tool_calls"]:
                            idx = tc.get("index", 0)
                            entry = tool_calls_map.setdefault(
                                idx, {"id": "", "name": "", "arguments": ""}
                            )
                            if tc.get("id"):
                                entry["id"] = tc["id"]
                            func = tc.get("function", {})
                            if func.get("name"):
                                entry["name"] = func["name"]
                            if func.get("arguments"):
                                entry["arguments"] += func["arguments"]

                # Reconstruct assistant message
                assistant_msg: dict = {"role": "assistant", "content": full_content or None}
                assembled: list[dict] = []
                for idx in sorted(tool_calls_map.keys()):
                    entry = tool_calls_map[idx]
                    if not entry["name"]:
                        continue
                    raw = entry["arguments"] or "{}"
                    try:
                        json.loads(raw)
                        valid_args = raw
                    except json.JSONDecodeError:
                        valid_args = "{}"
                    assembled.append({
                        "id": entry["id"] or f"call_{turn}_{idx}",
                        "type": "function",
                        "function": {"name": entry["name"], "arguments": valid_args},
                    })
                if assembled:
                    assistant_msg["tool_calls"] = assembled
                messages.append(assistant_msg)

                if not assembled:
                    # No tool calls → agent done for this user turn
                    yield SpecAgentEvent(kind="final", spec=spec, text=full_content)
                    return

                # Execute tools sequentially against spec; feed results back.
                # enforce_first_turn=True only on turn 0 (the very first LLM
                # response of this run).
                enforce_first = (turn == 0)
                for tc in assembled:
                    name = tc["function"]["name"]
                    try:
                        args = json.loads(tc["function"]["arguments"] or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    yield SpecAgentEvent(
                        kind="tool_call", spec=spec, tool_name=name, tool_args=args
                    )
                    try:
                        spec = dispatch_tool(
                            spec, name, args, enforce_first_turn=enforce_first
                        )
                        result_str = "ok"
                        yield SpecAgentEvent(
                            kind="spec_patch", spec=spec, tool_name=name
                        )
                    except ToolError as e:
                        result_str = f"Error: {e}"
                        yield SpecAgentEvent(
                            kind="tool_error",
                            spec=spec,
                            tool_name=name,
                            message=str(e),
                        )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result_str,
                    })

            # Hit max_turns
            yield SpecAgentEvent(kind="final", spec=spec, text=full_content)

    async def bootstrap_from_doc(
        self,
        spec: Spec,
        doc_text: str,
        *,
        silent: bool = False,
        diff_only: bool = False,
    ) -> AsyncIterator[SpecAgentEvent]:
        """Drive the LLM to populate (or diff-update) a SPEC from a document.

        Modes:
        - silent=True: doc is authoritative; LLM auto-confirms + jumps to Phase.READY
        - silent=False, diff_only=False: doc is a draft; LLM populates with confirmed=false, transitions to drafting
        - diff_only=True: doc is a V2 increment; LLM applies diff against existing spec, transitions to drafting
        """
        if diff_only:
            system_prompt = SPEC_BOOTSTRAP_DIFF_PROMPT.format(
                spec_summary=_summarize_spec(spec),
                doc_text=doc_text,
            )
        elif silent:
            system_prompt = SPEC_BOOTSTRAP_SILENT_PROMPT.format(doc_text=doc_text)
        else:
            system_prompt = SPEC_BOOTSTRAP_INTERACTIVE_PROMPT.format(doc_text=doc_text)

        user_msg = "请按上述指令处理文档。" if not diff_only else "请应用 V2 文档的差异。"
        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ]

        full_content = ""
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10, read=300, write=10, pool=10)
        ) as client:
            for turn in range(self.max_turns):
                payload = {
                    "model": self.model,
                    "messages": messages,
                    "tools": TOOL_DEFINITIONS,
                    "max_tokens": 4096,
                    "temperature": 0.2,
                    "stream": True,
                }
                full_content = ""
                tool_calls_map: dict = {}

                stream = _open_stream(client, self.base_url, self.api_key, payload)
                async for line in stream:
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    if delta.get("content"):
                        full_content += delta["content"]
                        yield SpecAgentEvent(
                            kind="assistant_delta", spec=spec, text=delta["content"]
                        )
                    if delta.get("tool_calls"):
                        for tc in delta["tool_calls"]:
                            idx = tc.get("index", 0)
                            entry = tool_calls_map.setdefault(
                                idx, {"id": "", "name": "", "arguments": ""}
                            )
                            if tc.get("id"):
                                entry["id"] = tc["id"]
                            func = tc.get("function", {})
                            if func.get("name"):
                                entry["name"] = func["name"]
                            if func.get("arguments"):
                                entry["arguments"] += func["arguments"]

                assistant_msg: dict = {"role": "assistant", "content": full_content or None}
                assembled: list[dict] = []
                for idx in sorted(tool_calls_map.keys()):
                    entry = tool_calls_map[idx]
                    if not entry["name"]:
                        continue
                    raw = entry["arguments"] or "{}"
                    try:
                        json.loads(raw)
                        valid_args = raw
                    except json.JSONDecodeError:
                        valid_args = "{}"
                    assembled.append({
                        "id": entry["id"] or f"call_{turn}_{idx}",
                        "type": "function",
                        "function": {"name": entry["name"], "arguments": valid_args},
                    })
                if assembled:
                    assistant_msg["tool_calls"] = assembled
                messages.append(assistant_msg)

                if not assembled:
                    yield SpecAgentEvent(kind="final", spec=spec, text=full_content)
                    return

                # bootstrap_from_doc: NEVER enforce_first_turn (doc IS the answer)
                for tc in assembled:
                    name = tc["function"]["name"]
                    try:
                        args = json.loads(tc["function"]["arguments"] or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    yield SpecAgentEvent(
                        kind="tool_call", spec=spec, tool_name=name, tool_args=args
                    )
                    try:
                        spec = dispatch_tool(spec, name, args, enforce_first_turn=False)
                        result_str = "ok"
                        yield SpecAgentEvent(
                            kind="spec_patch", spec=spec, tool_name=name
                        )
                    except ToolError as e:
                        result_str = f"Error: {e}"
                        yield SpecAgentEvent(
                            kind="tool_error",
                            spec=spec,
                            tool_name=name,
                            message=str(e),
                        )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result_str,
                    })

            yield SpecAgentEvent(kind="final", spec=spec, text=full_content)
