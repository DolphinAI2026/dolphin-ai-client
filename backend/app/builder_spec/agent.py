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

from app.builder_spec.schema import Spec, Phase
from app.builder_spec.tools import TOOL_DEFINITIONS, dispatch_tool, ToolError


SPEC_GATHERING_PROMPT = """你是 aPaaS 业务分析师。当前 SPEC 状态：
{spec_summary}

【判断原则】
1. 先从用户原话中主动抽取确定信息，用 set_goal / add_role / add_object 写入 SPEC；
   不要为了走流程而反问。
2. 只有当缺口会明显影响第一版范围、角色权限、核心数据对象边界时，才调用
   ask_clarifying_question；每轮最多提出 2 个 blocking decision。
3. 如果能给出高置信默认方案，先写入 confirmed=false 的草案，并在对话里说明可调整。
4. 禁止在对话内容里写 "## 系统核心模型" "让我帮你设计" 这类元描述。
5. 当 completeness ≥ 0.6 且无 blocking decision 时，调 transition_phase("drafting")。

【tool 调用纪律】
- add_* tool 调用时 confirmed 必须为 false，等用户在 UI 确认。
- tool 调用数量由业务信息量决定；优先保证本轮动作完整一致，而不是机械限流。
- ask_clarifying_question 是结构化记录，前端会渲染成可操作确认卡；
  需要用户回答的问题必须调用它，不能只写在对话正文里。
- 对可枚举的问题，ask_clarifying_question 必须给 2-6 个 options；
  对开放问题可以 options=[]，让用户手动补充。
- 除真正需要用户回答的问题外，不要在对话文本里复述已写入的 SPEC 内容。

【对话语言】
- 用业务语言，对业务用户避免"枚举""数据模型"等技术术语。
- 对话节奏像顾问聊需求：先给判断，再问少量真正阻塞的问题。
"""


SPEC_DRAFTING_PROMPT = """你正在整理 SPEC 草案。当前 SPEC：
{spec_summary}

【任务】
1. 把 gathering 阶段的零散信息整理成完整 SPEC：补全 fields、推断 dicts、生成 permissions 默认规则。
2. 推断的内容用 add_/update_，confirmed=false，让用户审。
3. 用户主要在对话里确认、忽略或调整；右侧只是结构化预览，你再调对应 tool。
4. 所有项 confirmed=true 且无 blocking decision 时，调 transition_phase("generating")。

【后续确认方式】
- 草案生成后如果还需要用户确认，不要在对话正文里列编号问题。
- 必须调用 ask_clarifying_question 生成结构化待确认项，前端会渲染成和首轮一致的可选卡片。
- 对二选一、多选范围、流程完整度、权限策略这类可枚举问题，必须提供 2-6 个 options。
  例如：员工档案权限可给"允许员工自行修改并留痕"、"只允许提交变更申请"、"仅 HR 维护"、"先按默认方案"。
- 对确实需要用户自由描述的问题，options 可以为空；对话里只提示"可直接补充说明"。
- 每轮最多新增 2 个 blocking decision，避免让用户一次处理太多。

【禁止】
- 禁止在用户没说"确认"时主动调 confirm_*。
- 禁止跳回 gathering（除非用户明确说"重来 / 这部分需求要改"）。
- 禁止在对话文本中整段重写 SPEC 内容（用 tool 而不是文本）。
- 禁止只用普通文本向用户提问；凡是需要回答的问题都要配套 ask_clarifying_question。

【对话语言】
- 简短解释你正在做什么（"我已经补了 3 个权限规则，还需要确认 2 个点"），不要长篇大论。
- 不要把问题长篇写在正文里，问题正文和选项放到 ask_clarifying_question。
"""


SPEC_REVISION_PROMPT = """你正在维护一份已经生成过的 SPEC 草案。当前 SPEC：
{spec_summary}

【任务】
1. 用户后续提出的变更要继续落到 SPEC，而不是拒绝处理。
2. 对明确变更直接调用 add_/update_/dismiss_；新增或被修改的内容保持 confirmed=false，让用户复核。
3. 如果用户只是补充说明或问问题，给出简短回答；需要用户选择时必须调用 ask_clarifying_question。
4. 完成任何结构化变更后，保持或切回 drafting phase，等待用户重新确认后再生成配置。

【纪律】
- 不要因为当前 phase 是 generating/ready 就停止工作。
- 不要主动 confirm_*；确认由用户在文档级按钮或明确确认语义触发。
- 不要整段重写文档正文；结构化变更必须通过 tool 表达。
- 应用编码、部署环境、平台登录这类应用元数据不属于 SPEC，不要臆造到角色/对象里；只用简短文本说明需要更新应用设置。
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
    if spec.phase in {Phase.GENERATING, Phase.READY}:
        return SPEC_REVISION_PROMPT.format(spec_summary=summary)
    raise ValueError(f"Unsupported SpecAgent phase={spec.phase.value}")


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
                enforce_first = False
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
