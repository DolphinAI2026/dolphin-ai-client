"""AIChat agent loop — 接 LLM tool calling，自主决定调哪些工具直到给出 final 回答。

核心循环：
  user msg → LLM (with tools) → 看 finish_reason
    ↳ "tool_calls" → 执行每个 tool → 把 result 加 messages → 再调 LLM
    ↳ "stop"      → 输出 final assistant text → 退出 loop
    ↳ ask_user 工具调用 → 暂停（等用户答）

事件流（async generator yield 的）：
  thinking          / 一段思考文本
  tool_call_start   / 准备调某个工具
  tool_call_end     / 工具执行结果
  ask_user          / 反问，loop 暂停
  assistant_message / 最终回复
  artifact_created  / 新产出物（write_artifact 触发）
  done              / loop 完结
  error             / 异常
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, AsyncIterator, Optional
from uuid import uuid4

import httpx
from cryptography.fernet import InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import decrypt_password
from app.doc_spec_standard import STANDARD_DOC_FORMAT
from app.llm_reasoning import strip_think_blocks
from app.models import (
    AIChatSession,
    AIChatMessage,
    AIChatToolCall,
    AIChatAttachment,
    AIChatArtifact,
    LLMConfig,
    User,
)
from app import runtime
from app.code_runtime.auth import control_plane_access_token
from app.code_runtime.control_plane_models import list_control_plane_model_options
from app.code_runtime.service import _control_plane_headers, control_plane_base_url
from app.models.system_assistant_governance import ActionRun, ActionTicket
from app.ai_chat.tools import (
    TOOL_SCHEMAS,
    build_deferred_manifest,
    execute_tool,
    get_all_tool_schemas,
    get_system_asset_tool_schemas,
    split_core_deferred,
)
from app.observability import recorder
from app.routes.llm_configs import (
    build_llm_chat_completions_url,
    build_llm_responses_url,
)
from app.system_assistant.contracts import assistant_model_purpose
from app.system_assistant.result_envelope import (
    apply_tool_call_projection,
    legacy_result_text,
    project_agent_step,
    project_sse_end,
)
from app.system_assistant.action_execution import complete_action_run
from app.system_assistant.governance_dispatcher import dispatch_shadow_action
from app import llm_transport

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GovernanceActionRequest:
    """Explicit authorization context supplied by an upstream governance owner."""

    tool_name: str
    capability_id: str
    action_kind: str
    object_ref: str
    object_revision: str
    policy_revision: int
    snapshot_digest: str
    correlation_id: str


def _consume_governance_action_request(
    session: AIChatSession, tool_name: str,
) -> GovernanceActionRequest | None:
    """Consume one explicit request only for its named live tool call."""
    request = getattr(session, "_governance_action_request", None)
    if not isinstance(request, GovernanceActionRequest) or request.tool_name != tool_name:
        return None
    delattr(session, "_governance_action_request")
    return request


def _tool_args_digest(args: dict[str, Any]) -> str:
    """Persist a stable digest, never the raw live tool arguments, in governance rows."""
    encoded = json.dumps(
        args, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


async def _execute_governed_live_tool(
    db: AsyncSession,
    session: AIChatSession,
    tool_call: AIChatToolCall,
    tool_name: str,
    args: dict[str, Any],
    request: GovernanceActionRequest,
) -> tuple[str, ActionRun | None]:
    """Create and terminalize one durable run around the existing tool handler."""
    tool_call_id = tool_call.id
    if not session.public_id:
        session.public_id = str(uuid4())

    args_digest = _tool_args_digest(args)
    ticket = ActionTicket(
        ticket_id=str(uuid4()),
        tenant_id=session.tenant_id,
        control_plane_tenant_id=(
            session.control_plane_tenant_id or f"legacy-tenant-{session.tenant_id}"
        ),
        user_id=session.user_id,
        session_id=session.id,
        session_public_id=session.public_id,
        object_ref=request.object_ref,
        action_kind=request.action_kind,
        args_digest=args_digest,
        object_revision=request.object_revision,
        policy_revision=request.policy_revision,
        status="authorized",
        expires_at=datetime.utcnow() + timedelta(minutes=5),
        correlation_id=request.correlation_id,
        state_version=1,
    )
    action_run = ActionRun(
        run_id=str(uuid4()),
        ticket_id=ticket.ticket_id,
        tool_call_id=tool_call_id,
        capability_id=request.capability_id,
        action_kind=request.action_kind,
        object_ref=request.object_ref,
        status="authorized",
        args_digest=args_digest,
        object_revision=request.object_revision,
        policy_revision=request.policy_revision,
        correlation_id=request.correlation_id,
        state_version=0,
    )
    ticket_id = ticket.ticket_id
    action_run_id = action_run.run_id
    db.add_all((ticket, action_run))
    await asyncio.shield(db.commit())
    # The execution adapter validates its fence through this same session.
    # Refresh only the governance run after its CAS transition; expiring the
    # live ToolCall would trigger implicit async I/O during compatibility projection.
    db.expire(action_run)

    async def governed_handler(_fence: Any) -> str:
        await db.refresh(session)
        return legacy_result_text(await execute_tool(tool_name, args, session, db))

    execution = await dispatch_shadow_action(
        session=db,
        ticket_id=ticket_id,
        run_id=action_run_id,
        governed_handler=governed_handler,
        legacy_handler=None,
        expected_ticket_state_version=1,
        expected_run_state_version=0,
        args_digest=args_digest,
        object_revision=request.object_revision,
        correlation_id=request.correlation_id,
    )
    if execution.fence is None:
        await db.refresh(session)
        await db.refresh(tool_call)
        return "错误：治理动作未能启动", None

    if execution.error is not None or not execution.governed_called:
        completed = await complete_action_run(
            db,
            execution.fence,
            status="failed",
            result_status="failed",
            result_summary={"digest": request.snapshot_digest},
            error_code="GOVERNED_TOOL_FAILED",
        )
        await db.refresh(session)
        await db.refresh(tool_call)
        if not completed:
            return "错误：治理动作结果未能确认", None
        return "错误：动作执行失败", await _completed_action_run_for_tool_call(db, tool_call_id)

    completed = await complete_action_run(
        db,
        execution.fence,
        status="succeeded",
        result_status="succeeded",
        result_summary={"digest": request.snapshot_digest},
    )
    await db.refresh(session)
    await db.refresh(tool_call)
    if not completed:
        return "错误：治理动作结果未能确认", None
    return legacy_result_text(execution.value), await _completed_action_run_for_tool_call(db, tool_call_id)


async def _completed_action_run_for_tool_call(
    db: AsyncSession, tool_call_id: int | None,
) -> ActionRun | None:
    """Read a completed authoritative ActionRun linked to one legacy ToolCall."""
    if tool_call_id is None:
        return None
    action_run = await db.scalar(
        select(ActionRun)
        .where(ActionRun.tool_call_id == tool_call_id)
        .order_by(ActionRun.updated_at.desc())
        .limit(1)
    )
    if action_run is None or action_run.status not in {
        "succeeded", "recovered", "failed", "partially_failed",
        "recovery_blocked", "outcome_unknown", "aborted",
    }:
        return None
    return action_run


def _apply_session_overrides(session, system_prompt_override, tool_names_override):
    """SP2a:调用方未显式传 override 时,按 session.mode 推导引擎行为。

    返回 (system_prompt_override, tool_names_override, derived_view_context)。语义:
    - 两个 override 都为 None(统一外壳从 /ai-chat 发会话,不传 override)→ 调
      resolve_overrides_for_session 推导:system_assistant 优先拿系统助手提示词和工具集;
      entry_agent 的 code 会话仍拿 dev-apaas 提示词 + 收窄工具,
      并把非空 ws_id 设到 session._locked_ws_id(单工作区锁,execute_tool 据此强锁),
      **同时推导 ws 绑定 view_context(告诉 agent 当前 ws_id)** —— 缺它 agent 会反问
      「请把 ws_id 发我」(2026-06-25 修复)。caller 没传 view_context 时 run_agent 用它。
      非 code 会话推导出全 None → 行为同今天的通用 Builder,零变化。
    - 调用方显式传了任一 override(harness 老路:coding.py 同时传 prompt+tools+自己的
      view_context,并自行设 _locked_ws_id)→ 原样返回 derived_view_context=None,
      **不推导、不碰 _locked_ws_id**,老路一字不改。
    """
    if system_prompt_override is not None or tool_names_override is not None:
        return system_prompt_override, tool_names_override, None
    from app.agents.profile import resolve_overrides_for_session, ws_bind_view_context
    sp, tn, ws_id = resolve_overrides_for_session(session)
    if ws_id:
        session._locked_ws_id = ws_id  # type: ignore[attr-defined]
    return sp, tn, ws_bind_view_context(ws_id)


def _append_skill_manifest(messages: list[dict]) -> None:
    """把可用 skill 清单追加到 system message（渐进披露）。空集 no-op、异常不致命。

    技能清单（桌面上传/平台预置）注入 system prompt，否则 use_skill 的描述指向不存在的
    「可用技能」段、模型无从得知技能名 → use_skill 实际不可达。空集（云端/无 skill）返回空串。
    """
    try:
        from app.ai_chat.skills import SkillRegistry, build_skill_manifest
        manifest = build_skill_manifest(SkillRegistry().scan())
    except Exception as exc:  # noqa: BLE001 — 技能扫描失败不应中断对话
        logger.warning("skill manifest 注入失败: %r", exc)
        return
    if manifest and messages and isinstance(messages[0], dict) and messages[0].get("role") == "system":
        messages[0]["content"] = (messages[0].get("content") or "") + manifest
    elif manifest:
        logger.warning("skill manifest skipped: messages[0] is not a system message")


async def _append_knowledge_manifest(messages: list[dict], db) -> None:
    """把平台知识库 published 文档目录追加到 system message(渐进披露)。

    空库 no-op、异常不致命 —— 与 _append_skill_manifest 同模式,但内容来自 DB。
    """
    try:
        from app.knowledge_base import list_published_docs, build_knowledge_manifest
        manifest = build_knowledge_manifest(await list_published_docs(db))
    except Exception as exc:  # noqa: BLE001 — 知识库扫描失败不应中断对话
        logger.warning("knowledge manifest 注入失败: %r", exc)
        return
    if manifest and messages and isinstance(messages[0], dict) and messages[0].get("role") == "system":
        messages[0]["content"] = (messages[0].get("content") or "") + manifest
    elif manifest:
        logger.warning("knowledge manifest skipped: messages[0] is not a system message")


# The first accepted response from some compatible gateways can still be empty
# or a dropped connection.  Retrying before any model output is safe and keeps
# a transient upstream glitch from terminating a whole Code turn.
LLM_RETRY_ATTEMPTS = 3
LLM_TOOL_RESULT_CONTEXT_MAX_CHARS = 24_000
PERSISTED_TOOL_ARG_PREVIEW_CHARS = 240
PERSISTED_TOOL_ARG_MAX_CHARS = 20_000
_CONTENT_ARG_KEYS = {
    "content",
    "md_content",
    "markdown",
    "html",
    "css",
    "code",
    "old_str",
    "new_str",
    "old_string",
    "new_string",
    "image_data_url",
}


def _compact_tool_result_for_context(result_text: str) -> str:
    """Bound tool output sent back to the model without altering the audit record.

    Some aPaaS write APIs echo the complete process definition in
    ``platform_response.data``.  Keeping that response in the database is useful
    for diagnostics, but replaying a megabyte-sized result into the next LLM
    request makes the provider return a gateway 502.  Preserve the top-level
    operation summary and replace only the oversized provider payload.
    """
    if len(result_text) <= LLM_TOOL_RESULT_CONTEXT_MAX_CHARS:
        return result_text

    try:
        payload = json.loads(result_text)
    except (TypeError, ValueError):
        return result_text[:LLM_TOOL_RESULT_CONTEXT_MAX_CHARS] + (
            f"\n... [工具结果已截断，原始 {len(result_text)} 字符]"
        )

    if isinstance(payload, dict):
        provider_response = payload.get("platform_response")
        if isinstance(provider_response, dict):
            payload = dict(payload)
            payload["platform_response"] = {
                key: provider_response[key]
                for key in ("code", "message", "status")
                if key in provider_response
            }
            payload["platform_response"]["_omitted_large_fields"] = True
        compacted = json.dumps(payload, ensure_ascii=False, default=str)
        if len(compacted) <= LLM_TOOL_RESULT_CONTEXT_MAX_CHARS:
            return compacted

    return result_text[:LLM_TOOL_RESULT_CONTEXT_MAX_CHARS] + (
        f"\n... [工具结果已截断，原始 {len(result_text)} 字符]"
    )


def _summarize_persisted_text(value: str) -> dict:
    preview = value[:PERSISTED_TOOL_ARG_PREVIEW_CHARS]
    if len(value) > PERSISTED_TOOL_ARG_PREVIEW_CHARS:
        preview += f"\n... [omitted, {len(value)} chars total]"
    return {
        "_omitted_large_text": True,
        "chars": len(value),
        "preview": preview,
    }


def _compact_tool_arg_value(value: Any, key: str | None = None) -> Any:
    """Keep tool-call persistence small without changing the live tool input."""
    if isinstance(value, dict):
        return {k: _compact_tool_arg_value(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_compact_tool_arg_value(v, key) for v in value]
    if isinstance(value, str):
        if (key or "").lower() in _CONTENT_ARG_KEYS:
            return _summarize_persisted_text(value)
        if len(value) > PERSISTED_TOOL_ARG_PREVIEW_CHARS * 4:
            return _summarize_persisted_text(value)
    return value


def _compact_tool_args_for_storage(tool_name: str, args: dict) -> dict:
    compacted = _compact_tool_arg_value(args)
    text = json.dumps(compacted, ensure_ascii=False, default=str)
    if len(text) <= PERSISTED_TOOL_ARG_MAX_CHARS:
        return compacted
    return {
        "_compacted": True,
        "tool_name": tool_name,
        "original_json_chars": len(text),
        "summary": "工具参数过大，已从会话持久化记录中省略；实际工具执行使用的是完整参数。",
    }


def _compact_tool_call_for_storage(tool_call: dict) -> dict:
    compacted = dict(tool_call)
    fn = dict(compacted.get("function") or {})
    tool_name = str(fn.get("name") or "")
    raw_args = fn.get("arguments") or "{}"
    try:
        parsed_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
    except Exception:
        parsed_args = {"_raw_arguments": str(raw_args)}
    if isinstance(parsed_args, dict):
        stored_args = _compact_tool_args_for_storage(tool_name, parsed_args)
    else:
        stored_args = _compact_tool_arg_value(parsed_args)
    fn["arguments"] = json.dumps(stored_args, ensure_ascii=False, default=str)
    compacted["function"] = fn
    return compacted


# 错误分类 / 文案 / 退避已收口到 app.llm_transport;这里保留同名薄封装,
# 既不改对外行为,也让既有引用(本文件内多处)不动。
def _is_retryable_llm_error(exc: Exception) -> bool:
    return llm_transport.is_retryable_llm_error(exc)


async def _sleep_before_llm_retry(attempt: int) -> None:
    await llm_transport.sleep_before_retry(attempt)


def _format_llm_error(exc: Exception) -> str:
    return llm_transport.format_llm_error(exc)


# ─────────────────────── Deferred-tool helpers ───────────────────────


def _parse_activated(result_text: str) -> list[str]:
    """从 search_tools 的结果 JSON 里取 activated 名单;非 JSON / 无字段返 []。"""
    try:
        d = json.loads(result_text or "")
        return list(d.get("activated") or []) if isinstance(d, dict) else []
    except Exception:
        return []


async def _reconstruct_active_tools(db: AsyncSession, session) -> set[str]:
    """从历史推导本会话已激活的延迟工具:
    过去 search_tools 调用的 activated 名单 + 已成功调用过的工具名(兜底:用过的保持可用)。
    无状态、重启不丢(从持久化 tool_calls 推)。"""
    from sqlalchemy import select as _sel
    from app.models.ai_chat import AIChatToolCall
    active: set[str] = set()
    try:
        rows = (await db.execute(
            _sel(AIChatToolCall).where(AIChatToolCall.session_id == session.id)
        )).scalars().all()
        for tc in rows:
            if tc.tool_name == "search_tools":
                active.update(_parse_activated(tc.result_text or ""))
            else:
                active.add(tc.tool_name)
    except Exception:
        pass
    return active


# ─────────────────────────── System prompts ──────────────────────────
#
# 两种工作模式共享同一段格式硬约束（_FORMAT_CONSTRAINTS），但前面的
# "工作模式 / 行为指引" 不同：
#   chat   = 从零对话理需求（用户没现成材料）
#   cowork = 批量材料整合（用户拖了一堆材料，AI 主动消化整合）

_FORMAT_CONSTRAINTS = f"""⚠️ 你产出的 markdown 会被 aPaaS Builder 的 doc_pipeline 直接解析、自动生成模型/表单/角色/权限。
**必须严格遵循下面的章节顺序、表格列名、字段编码命名约束**——任何偏差都会让 Builder 拒绝解析（标准度 < 90/100 直接 400）。

{STANDARD_DOC_FORMAT}

## 输出准则（除上面格式硬约束外）
- 主动用工具，不要让用户反复催促
- 一次回复里可以连续调多个工具（并行）
- 不要凭空捏造，所有结论都基于读到的材料 + 用户确认的边界
- 反问要少而精，只问真正影响设计的关键点
- 输出 md 时严格按上面 6 个必填章节顺序，必填章节不能跳过（第 7 章「审批流程」可选，有审批需求才追加在最后）；缺信息留空单元格即可，不要写"未定义"、"待定"占位文字
- 模型/表单/字段命名：英文 snake_case + 业务前缀（避免 name/status 这种通用字段直接用，要 ncr_status / supplier_name）
- **应用编码（appCode）必须满足**：只允许小写字母 / 数字 / 中划线 `-`，以小写字母开头，长度 ≤ 17 字符（正则 `^[a-z][a-z0-9-]{0,16}$`）。**禁止下划线**。如果业务名很长，要主动缩写（如"电力设备管理系统" → `power-equip-mgmt` 或 `power-equip` 而不是 `power_equipment_management`）
- 数据模型只描述"字段在数据库怎么存"，不要在数据模型表里写字典/关联/组件，那些都在「五、表单定义」里
- 数据单选/数据选择/关联表单字段引用的目标模型，必须先在 ## 四、数据模型 里建出来；没材料支持就不要写这种引用，改用单行输入

附件信息会在用户消息后附上"[已上传附件]"列表，告诉你有哪些可以读。"""


SYSTEM_PROMPT_UNIFIED = f"""你是 aPaaS 平台的 AI 全栈助手 — 既能产文档（喂给 ai-builder 生成应用），也能写代码（接入 aPaaS 应用做二次开发，或从零搭独立项目）。看用户场景自适应。

## 三种姿态（自己判断走哪个）

### 姿态 A：用户上传了一堆材料（PDF / Word / Excel / 截图 / 现有文档）→ 产文档
1. **第一个动作不是问"你要做什么"**——用户已经用文件告诉你了，立刻**并行** read_attachment 把每份附件都读一遍
2. 数据类材料（xlsx / csv）配合 run_python 抽要点：表头、行数、枚举值分布、关键字段
3. 图片类材料（截图 / 架构图 / 流程图）已直接附在消息里、你能直接看图，**不要对图片调 read_attachment**（会被拒），直接描述图里内容即可
4. 读完给用户一个**结构化的"我看到了什么"汇总**：识别出 **A 张数据表** / **B 个角色** / **C 个流程** / **D 个枚举字段**
5. **批量**列出 3-5 个澄清问题，每个问题写明"如果选 X / 选 Y 会影响什么"
6. 产出设计文档分两种情况：
   - **附件本身已经是一份结构化设计文档**（含数据模型 / 表单 / 字段表格——哪怕几十上百个模型、几十万字）→ 直接 **create_artifact_from_attachment(filename=附件名)** 把整篇**原样**转成设计文档 artifact。⚠️ 千万**不要** read_attachment 读一遍再 write_artifact 重抄一遍：read_attachment 在 3 万字处截断、write_artifact 又受输出长度限，整篇会被你无意识摘要/漏掉 → 只建出残缺应用。read_attachment 只用于第 1-4 步"理解 + 汇总"。
   - **附件只是粗略需求 / PRD 散文 / 表格数据** → 需求清晰后 write_artifact 一次写完整篇 6 章 markdown 设计文档（应用信息 / 角色 / 字典 / 模型 / 表单 / 权限，有审批需求再加可选的「七、审批流程」）

### 姿态 B：用户没材料只有想法 → 对话挖需求 → 产文档
1. 跟着用户节奏问，每轮最多 1-2 个关键问题（用 ask_clarifying_question）
2. 数据类需求也能用 run_python 编程分析
3. 需求清晰后 write_artifact 一次写完整篇

### 姿态 C：用户要写代码 / 二次开发 / 自开发 → 调代码工具 + 在消息里给代码
**关键约束**：你不仅要把代码写到 workspace（用 write_workspace_files），
**还要在 chat 消息里用 markdown ```代码块``` 把核心片段给用户看一遍**。
不要只丢一句"已写完"就完事——用户没法预览看不到工具卡内部的代码，体验差。

判断走哪条路：
- 用户只是问“查看现有应用 / 查询应用列表 / 我有哪些应用 / 当前租户应用” → **直接调用 list_my_applications**。
  这个工具已经按当前登录 JWT 的 tenant_id 查询当前租户，不需要也不应该先调用 list_platform_envs。
- 用户给出已有 aPaaS 应用链接 / app_code / app_id，要求“生成设计文档 / 反向整理文档 / 为什么不全” → **已有应用反向导出路径**：
  export_apaas_app_design_doc。这个工具会优先使用当前租户绑定的默认环境；只有用户明确指定多个环境或没有默认环境时，才需要额外确认环境。**不要为了“当前租户已绑定环境”的普通操作先调 list_platform_envs**，也不要自己连续调 list_apaas_* 后手写 write_artifact，除非用户明确要求你基于业务常识重写而不是还原平台现状。
- 给已有 aPaaS 应用做组件 / 页面 / 后端接口扩展 → **AI Coding 路径**：
  list_dev_scenes → get_dev_scene_spec → list_apaas_apps_in_env → list_apaas_app_menus
  → create_dev_workspace → write_workspace_files / edit_workspace_files → run_workspace_command
  → enable_apaas_self_dev_config + attach_dev_packages_to_apaas_app + republish_apaas_app

**代码展示规则**（重要）：
- 写完一个文件，在回复消息里用 ```\\`\\`\\`vue` / ```\\`\\`\\`ts` 等代码块**展示关键内容**
- 长文件可以截关键部分（如组件定义、API 调用、配置）+ 说"完整代码已写到 workspace/<path>"
- 多文件场景：每个文件一个代码块，加上文件路径作为代码块前的说明（**📄 src/components/X.vue**）
- 用户要看完整文件时再读 workspace（你已经写进去了）

### 自开发产物边界（非常重要）
当用户要做 aPaaS 自开发页面 / 组件 / 插件时，代码必须写入 workspace（write_workspace_files / edit_workspace_files），右侧产物只用于辅助查看，不能混淆类型：
- 标准 Builder 设计文档（`*-设计文档.md`）只描述低代码应用结构，禁止塞入 Vue/JS/CSS 源码。
- 自开发技术说明可写成 `*-自开发说明.md`，内容是包结构、注册名、构建发布步骤、接口假设和注意事项，不要整段粘贴完整 `.vue` 源码。
- 如果确实要给用户下载完整源码，单独写 `*.vue` / `*.js` / `package.json` 代码产物，format 必须匹配文件类型；不要把它命名为“设计文档”。
- aPaaS 自开发脚手架使用 Vue 2.7 + Vue CLI + UMD 插件注册方式；不要输出 Vue 3 `<script setup>` 代码。

构建步骤也要克制：首次或 package.json 变更后最多跑一次 `run_workspace_command(ws_id, command="npm install")`，随后跑一次 `run_workspace_command(ws_id, command="npm run build")`。不要反复尝试带 `--cache`、`./node_modules/.bin/vue-cli-service build` 的长命令；后端会统一处理缓存安装和兼容构建。

## 🚀 文档 → 应用 → 部署 一气呵成（核心铁律 — 2026-05-21 新增）

用户说"创建应用 / 生成应用 / 部署应用 / 帮我做 XXX 系统" 时，**默认一条龙跑到底**，不要每步停下问"要继续吗"：

### 两阶段 + 1 个用户审核点（重要！）

整个流程拆成 **设计阶段** + **执行阶段**，中间必须**停下来让用户审核 SPEC**。
这不是冗余 — 用户对 5000+ 字应用蓝图有最后审核权，错了改 doc 比改部署后的 aPaaS 应用便宜 10 倍。

### Phase 1 · 设计 + 自检 (agent 自主跑完不停顿)
1. ask_clarifying_question × 1-2 轮 (只问关键边界 + 角色)
2. **write_artifact 一次写完整篇 6 章 md** (应用信息 / 角色 / 字典 / 模型 / 表单 / 权限，有审批需求再加可选的「七、审批流程」) → 返回 `artifact_id`
3. **validate_builder_doc(artifact_id=<上一步的 id>)** ← schema 强制 artifact_id 必填. 拿 score
4. **STOP — 给用户 1-3 句总结 + 主动 hint**:
   - "✅ 设计文档已生成 (右侧可查看)，校验通过 X/100 分。**请 review 一下文档**，没问题告诉我「开始创建」/「部署」/「OK」，我就一条龙跑完到上线；如果要改字段/角色/权限，直接告诉我哪里要改。"

**⚠️ Phase 1 不要调 submit_design_doc**: 该工具是给 外部 agent 81 (跨 chat 容器) cache SPEC + 返 deeplink 用的, ai-chat 内置 agent (你) 在 AIChatPage 内直接 Phase 2 跑 generate, 不需要 cache + deeplink. 调它返 deeplink 用户点 → 跳 ChatPage 把当前 SSE 断 → final summary 跑不出来.

### Phase 2 · 执行 (用户确认 SPEC 后 agent 自主跑完不停顿)
触发条件：用户说 "OK" / "开始创建" / "部署" / "生成应用" / "上线" / 任何明确推进信号
1. **generate_app_from_doc(artifact_id=<Phase 1 write_artifact 的 id>)** 创建应用 (拿 app_id, draft 状态).
   schema 已强制 artifact_id 必填 (2026-05-24, 跟 validate/submit 一致), md_content 参数已删除.
   默认使用当前租户绑定的默认平台环境；不要为了拿默认环境先调 list_platform_envs.
2. deploy_application 部署到 aPaaS (draft → ready, 这一步才是"真创建到 aPaaS 平台")
3. publish_application 发布上线 (ready → published, 用户能真访问)
4. 给一段 1-3 句 final summary: "✅ 已部署完成 - app_id=N, recruit-mgmt - 点击下方按钮打开应用"

### 💰 Token 节省铁律 (2026-05-24 schema 强制版)
**LLM 重写完整 5000+ 字 md 多次是巨大浪费**。正确做法:
- write_artifact 是 LLM **从对话/想法**完整生成 md 的地方 (LLM 输出 content 参数)。
  **但如果用户上传的附件本身就是设计文档, 用 create_artifact_from_attachment 让服务端整篇原样收录, 别让 LLM 重抄** (省 token + 防超大文档被截断漏内容)
- validate_builder_doc / generate_app_from_doc 的 md_content 参数 **2026-05-23/24 已删除** —
  schema 强制 artifact_id 必填. 漏传 → MISSING_ARTIFACT_ID; 没 fallback
- **小改 md（改个字段/编码/某段）→ edit_artifact**：先 read_artifact 拿精确原文，再 old_string→new_string 精确替换，**不要整篇重写**（省 token + 避免大文档被截断漏内容）。同名自动 version++。
- 整篇推倒重来 / 首版生成才用 write_artifact。改完后续工具自动取本会话最新 .md（一般不用手填 artifact_id）
- update_app_from_doc 暂未强制 schema, 仍然接受 md_content (评估中)

### 关键反模式（不要做）
- ❌ **Phase 1 走完 submit 后立刻 generate_app_from_doc** — 必须先停下让用户 review SPEC！跳过审核 = 错了部署后改回来贵 10 倍。
- ❌ **不要为了改一处就 write_artifact 重写整篇 md** — 要改 doc 里某个字段/编码/小段 → edit_artifact 精确改那一处; 应用已创建后要改的是平台配置 → update_app_from_doc (Phase 2 工具)。
- ⚠️ **update_app_from_doc 只生成待确认变更计划，不等于已执行更新** — 调完后必须读取/使用返回的 actions_preview 或 get_change_plan，把新增/修改/删除逐条列给用户确认；用户明确回复确认执行前，禁止调用 execute_change_plan，禁止说"已完成更新"。
- ❌ **Phase 2 内 generate_app_from_doc 完成后停下等用户** — 用户已经在 Phase 1 末说"创建/部署"，意思是要"真能用"，不是"建个 draft"。Phase 2 内继续 deploy + publish 直到上线。
- ❌ **Phase 2 内每个工具调完都问"要继续吗 / 是否部署"** — 用户在 Phase 1 末已确认，Phase 2 自主推进。
- ❌ **遇到 appCode 冲突就改 app_code / 加 -v1 -v2 后缀重试** — appCode = 应用身份, 同 code 就是同一个应用！backend 已自动"同 app_code 复用同一应用 + 增量合并"(2026-05-28)，你**保持原 app_code 重试即可**，千万别加 -v1/-v2 后缀——那会建出一堆残缺重复应用，乱套。同理一份大文档**一次性 generate 整篇**，不要自己拆成多批分别 generate（拆批就会撞 appCode）。

### 例外：什么时候 Phase 1/2 内部也停下问
(a) 需求本身有歧义（如多个候选模型都叫"客户"）
(b) 用户明确说"先停在 draft / 我先看看再决定"
(c) 工具撞 token expired / 权限不足 等需要用户介入的错
(d) 当前租户没有绑定可用默认环境，或绑定了多个 connected 环境且用户明确要求选择目标环境

## 工具速查（按场景挑用，下面只列常用，完整清单以实际可用工具为准）

文档处理：parse_design_doc / validate_builder_doc / write_artifact / read_attachment / export_apaas_app_design_doc
aPaaS 内省：list_apaas_apps_in_env / list_apaas_app_menus / list_apaas_form_views / list_apaas_form_components / list_apaas_app_models / list_apaas_app_dicts
应用生命周期：generate_app_from_doc / get_application / update_app_from_doc / execute_change_plan / deploy_application / publish_application
自开发场景：list_dev_scenes / get_dev_scene_spec / get_dev_scene_full_workflow
AI Coding workspace：create_dev_workspace / read_workspace_file / write_workspace_files / edit_workspace_files / glob_workspace / grep_workspace / run_workspace_command
自开发发布：enable_apaas_self_dev_config / attach_dev_packages_to_apaas_app / republish_apaas_app / create_apaas_self_dev_menu

{_FORMAT_CONSTRAINTS}"""


# 向后兼容：SYSTEM_PROMPT 指向统一版本（旧 chat/cowork 双 prompt 已删，统一走 UNIFIED）
SYSTEM_PROMPT = SYSTEM_PROMPT_UNIFIED

# agent_prompts 表里 unified 系统提示用的 (agent_id, phase)。改提示词不发版靠这两个键。
UNIFIED_AGENT_ID = "unified"
UNIFIED_PHASE = "system"


async def _resolve_unified_system_prompt(
    db: AsyncSession, tenant_id: Optional[int]
) -> str:
    """解析 unified 系统提示的**静态模板**部分（DB-first，查不到回退代码常量）。

    只负责静态模板；STANDARD_DOC_FORMAT 已在 SYSTEM_PROMPT_UNIFIED 编译期烘进去，
    app 上下文等运行时动态拼接仍在 _build_initial_messages 里完成，不进 DB。

    tenant_id 缺失或 DB 异常 → 直接回退 SYSTEM_PROMPT_UNIFIED，绝不让 prompt
    解析挂掉主链路。
    """
    if tenant_id is None:
        return SYSTEM_PROMPT_UNIFIED
    try:
        from app.services.prompt_resolver import resolve_prompt
        return await resolve_prompt(
            db, tenant_id,
            agent_id=UNIFIED_AGENT_ID, phase=UNIFIED_PHASE,
            fallback=SYSTEM_PROMPT_UNIFIED,
        )
    except Exception as e:  # 兜底：任何异常都回退代码常量
        logger.warning(
            "resolve unified system prompt failed for tenant=%s: %s — 回退代码常量",
            tenant_id, e,
        )
        return SYSTEM_PROMPT_UNIFIED


# ─────────────────────────── LLM 调用辅助 ───────────────────────────

class LLMConfigSnapshot:
    """快照 LLMConfig 的解密信息，避免 db 异步调用穿透到 httpx。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        max_tokens: int,
        temperature: float,
        *,
        extra_headers: dict[str, str] | None = None,
        api_format: str = "chat_completions",
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.extra_headers = dict(extra_headers or {})
        self.api_format = api_format


class ControlPlaneModelCatalogError(RuntimeError):
    """The remote model catalogue failed; never disguise this as no model."""


def _apply_provider_payload_compat(cfg: LLMConfigSnapshot, payload: dict) -> dict:
    model = (cfg.model or "").lower()
    base_url = (cfg.base_url or "").lower()
    if "qwen3" in model or "dashscope.aliyuncs.com" in base_url:
        payload["enable_thinking"] = False
    return payload


def _llm_chat_completions_url(cfg: LLMConfigSnapshot) -> str:
    """Use the same OpenAI-compatible URL normalization as LLM config tests."""
    return build_llm_chat_completions_url(cfg.base_url)


async def _resolve_llm_config(
    db: AsyncSession, session: AIChatSession
) -> LLMConfigSnapshot:
    """优先用 session.selected_llm_config_id；没指定则取平台默认模型。

    解析逻辑收口到 routes.llm_configs.resolve_llm_config_for_purpose(purpose="builder")，
    与 harness/llm_resolver 同源——消除「改 LLM scope 要同时 patch ai_chat 和
    llm_resolver 两处」的漂移(commit 8068d895 实证过的坑)。

    兜底链逐行核对与旧 ai_chat 等价:
      ① selected_llm_config_id → get_active_llm_config_by_id_for_purpose
         (id+active, 且 purpose ∈ {builder, all});
      ② 平台默认 builder → 平台默认 all;
      ③ 兜底任意 active(优先 builder 再 all)。
    唯一适配:resolve_* 找不到返回 None,这里转抛与旧版**逐字一致**的 RuntimeError;
    并把 ORM 行包成 LLMConfigSnapshot(解密 + max_tokens/temperature 透传)。

    注:purpose="builder" 等价于旧版 purpose IN ('builder','all')——resolve_* 内部
    精确用途优先、其次 'all'。租户作用域:resolve_* 现按 session.tenant_id **本租户优先**,
    本租户没配则回落全平台共享兜底(2026-06-16),桌面独立租户用自己的、在线版零影响。
    """
    from app.routes.llm_configs import resolve_llm_config_for_purpose

    purpose = assistant_model_purpose(getattr(session, "assistant_profile", None))
    selected_config_id = getattr(session, "selected_llm_config_id", None)
    # Negative IDs are synthesized Control Plane catalogue IDs. Never pass one
    # to the local resolver, otherwise it silently replaces a user-selected
    # online model with an unrelated local default.
    local_selected_config_id = (
        selected_config_id
        if isinstance(selected_config_id, int) and selected_config_id > 0
        else None
    )
    cfg: Optional[LLMConfig] = await resolve_llm_config_for_purpose(
        db,
        getattr(session, "tenant_id", None) or 0,
        purpose,
        local_selected_config_id,
    )
    if local_selected_config_id and cfg and cfg.id == local_selected_config_id:
        return _snapshot_from_local_llm_config(cfg)

    try:
        remote_cfg = await _resolve_control_plane_llm_config(db, session, purpose)
    except ControlPlaneModelCatalogError:
        # A local default is a usable offline fallback, but never replace an
        # explicitly selected online model with it without telling the user.
        if cfg is not None and not (
            isinstance(selected_config_id, int) and selected_config_id < 0
        ):
            return _snapshot_from_local_llm_config(cfg)
        raise
    if remote_cfg is not None:
        return remote_cfg

    if not cfg:
        raise RuntimeError(
            "平台还没有配置可用的大模型,请到「平台管理 → 模型配置」添加一个模型后再使用。"
        )
    return _snapshot_from_local_llm_config(cfg)


def _snapshot_from_local_llm_config(cfg: LLMConfig) -> LLMConfigSnapshot:
    try:
        api_key = decrypt_password(cfg.api_key_enc)
    except InvalidToken as exc:
        raise RuntimeError(
            f"模型配置「{cfg.config_name}」的 API Key 无法解密，"
            "通常是环境加密密钥变更或配置密文已失效。请到「平台管理 → 模型配置」重新保存该模型配置后再试。"
        ) from exc
    return LLMConfigSnapshot(
        base_url=cfg.base_url,
        api_key=api_key,
        model=cfg.model,
        max_tokens=cfg.max_tokens,
        temperature=cfg.temperature,
    )


async def _resolve_control_plane_llm_config(
    db: AsyncSession,
    session: AIChatSession,
    purpose: str,
) -> LLMConfigSnapshot | None:
    """Use the signed-in desktop account's online model as Builder's default.

    Local model configurations remain selectable supplements. They must not be
    required merely because a desktop user has a private local database tenant.
    """
    if not runtime.is_desktop():
        return None
    user = await db.get(User, session.user_id)
    if (
        user is None
        or str(getattr(user, "account_source", "") or "").lower() != "control_plane"
    ):
        return None
    access_token = control_plane_access_token(user)
    control_plane_tenant_id = str(
        getattr(session, "control_plane_tenant_id", None)
        or getattr(user, "coding_tenant_id", None)
        or ""
    ).strip()
    if not access_token or not control_plane_tenant_id:
        return None

    delegated_context = type(
        "ControlPlaneModelContext",
        (),
        {"user": user, "control_plane_tenant_id": control_plane_tenant_id},
    )()
    authorization = f"Bearer {access_token}"
    try:
        options = await list_control_plane_model_options(
            purpose=purpose,
            authorization_header=authorization,
            delegated_context=delegated_context,
        )
    except Exception as exc:
        detail = str(getattr(exc, "detail", None) or exc).strip()
        logger.warning("desktop Control Plane model catalogue unavailable: %s", detail)
        raise ControlPlaneModelCatalogError(
            f"线上模型目录加载失败：{detail[:500] or '未知错误'}"
        ) from exc
    if not options:
        return None

    selected_config_id = getattr(session, "selected_llm_config_id", None)
    selected = next(
        (option for option in options if option.get("id") == selected_config_id),
        None,
    )
    option = selected or next(
        (candidate for candidate in options if candidate.get("is_default")),
        options[0],
    )
    return LLMConfigSnapshot(
        base_url=f"{control_plane_base_url().rstrip('/')}/api/code/model-gateway/v1",
        api_key=access_token,
        model=str(option["model"]),
        max_tokens=8192,
        temperature=0.3,
        extra_headers=_control_plane_headers(
            authorization,
            delegated_context=delegated_context,
        ),
        # The Control Plane intentionally exposes only /v1/responses. Keep the
        # protocol adaptation here rather than pretending its gateway is a
        # chat/completions endpoint (which returns 405).
        api_format="responses",
    )


async def generate_title(
    db: AsyncSession,
    session: AIChatSession,
    user_message: str,
) -> Optional[str]:
    """根据用户首条消息生成 ≤24 字的会话标题。失败返回 None。"""
    try:
        cfg = await _resolve_llm_config(db, session)
    except Exception:
        return None
    prompt = (
        "请根据用户的下一条消息，用 不超过 16 个汉字 概括会话主题，"
        "直接输出标题文本本身（不要带引号、前缀或解释）。\n\n"
        f"用户消息：{user_message[:300]}"
    )
    try:
        # Reuse the transport adapter: desktop Control Plane uses Responses,
        # while a locally selected model still uses Chat Completions.
        message = await _call_llm(
            cfg,
            [{"role": "user", "content": prompt}],
            [],
            timeout=20,
            max_tokens=512,
            temperature=0.3,
        )
        raw_title = message.get("content") or ""
        # 剥离内联 <think>…</think>(MiniMax), 只取可见标题文本。
        title, _reasoning = strip_think_blocks(raw_title)
        title = title.strip()
        # 清理引号 / 多余前缀
        title = title.strip(' "\'`「」')
        if len(title) > 30:
            title = title[:30]
        return title or None
    except Exception as e:
        logger.warning("generate_title failed: %s", e)
        return None


async def _call_llm(
    cfg: LLMConfigSnapshot,
    messages: list[dict],
    tools: list[dict],
    timeout: int = 120,
    max_tokens: int | None = None,
    temperature: float | None = None,
    omit_generation_controls: bool = False,
    omit_tool_choice: bool = False,
) -> dict:
    """non-streaming chat completion + tool calling。返回 OpenAI 格式 response.choices[0].message"""
    payload: dict[str, Any] = {
        "model": cfg.model,
        "messages": messages,
    }
    # A few otherwise OpenAI-compatible gateways treat ``tools: []`` plus an
    # explicit ``tool_choice: auto`` as an invalid tool request and, worse,
    # answer it with HTTP 200 and an empty body.  Omit both when no tool is
    # available; that is also the OpenAI default.  During the compatibility
    # fallback we retain the actual tool definitions but omit tool_choice as
    # well, since ``auto`` is the default there too.
    if tools:
        payload["tools"] = tools
        if not omit_tool_choice:
            payload["tool_choice"] = "auto"
    if not omit_generation_controls:
        payload["temperature"] = cfg.temperature if temperature is None else temperature
        payload["max_tokens"] = cfg.max_tokens if max_tokens is None else max_tokens
    _apply_provider_payload_compat(cfg, payload)
    if getattr(cfg, "api_format", "chat_completions") == "responses":
        return await _complete_responses(cfg, payload, timeout=timeout)
    return await llm_transport.complete(
        base_url=cfg.base_url,
        api_key=cfg.api_key,
        payload=payload,
        timeout=httpx.Timeout(connect=10, read=timeout, write=10, pool=10),
        retry_attempts=LLM_RETRY_ATTEMPTS,
        url=_llm_chat_completions_url(cfg),
        extra_headers=getattr(cfg, "extra_headers", {}) or {},
    )


def _responses_input(messages: list[dict]) -> list[dict]:
    """Translate our Chat Completions history into OpenAI Responses input."""
    items: list[dict] = []
    for message in messages:
        role = str(message.get("role") or "user")
        content = message.get("content")
        if role == "tool":
            call_id = str(message.get("tool_call_id") or "").strip()
            if call_id:
                items.append({
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": content or "",
                })
            continue
        normalized_role = "developer" if role == "system" else role
        if normalized_role not in {"developer", "user", "assistant"}:
            normalized_role = "user"
        if content:
            items.append({
                "role": normalized_role,
                "content": str(content),
            })
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            call_id = str(call.get("id") or "").strip()
            name = str(function.get("name") or "").strip()
            if call_id and name:
                items.append({
                    "type": "function_call",
                    "call_id": call_id,
                    "name": name,
                    "arguments": str(function.get("arguments") or "{}"),
                })
    return items


def _responses_tools(tools: list[dict]) -> list[dict]:
    translated: list[dict] = []
    for tool in tools:
        function = tool.get("function") if isinstance(tool, dict) else None
        if not isinstance(function, dict):
            continue
        name = str(function.get("name") or "").strip()
        if not name:
            continue
        translated.append({
            "type": "function",
            "name": name,
            "description": str(function.get("description") or ""),
            "parameters": function.get("parameters") or {"type": "object", "properties": {}},
        })
    return translated


def _responses_message(response: dict) -> dict:
    content_parts: list[str] = []
    tool_calls: list[dict] = []
    for item in response.get("output") or []:
        if item.get("type") == "function_call":
            name = str(item.get("name") or "").strip()
            call_id = str(item.get("call_id") or item.get("id") or "").strip()
            if name and call_id:
                tool_calls.append({
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": str(item.get("arguments") or "{}"),
                    },
                })
            continue
        for part in item.get("content") or []:
            if part.get("type") in {"output_text", "text"}:
                text = part.get("text")
                if text:
                    content_parts.append(str(text))
    return {
        "content": "".join(content_parts),
        "tool_calls": tool_calls or None,
    }


async def _complete_responses(
    cfg: LLMConfigSnapshot,
    chat_payload: dict,
    *,
    timeout: int,
) -> dict:
    request_payload: dict[str, Any] = {
        "model": cfg.model,
        "input": _responses_input(chat_payload["messages"]),
    }
    if "temperature" in chat_payload:
        request_payload["temperature"] = chat_payload["temperature"]
    if "max_tokens" in chat_payload:
        request_payload["max_output_tokens"] = chat_payload["max_tokens"]
    if "tool_choice" in chat_payload:
        request_payload["tool_choice"] = chat_payload["tool_choice"]
    tools = _responses_tools(chat_payload.get("tools") or [])
    if tools:
        request_payload["tools"] = tools
    target = build_llm_responses_url(cfg.base_url)
    response: httpx.Response | None = None
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10, read=timeout, write=10, pool=10)
        ) as client:
            response = await client.post(
                target,
                headers={
                    "Authorization": f"Bearer {cfg.api_key}",
                    "Content-Type": "application/json",
                    **(getattr(cfg, "extra_headers", {}) or {}),
                },
                json=request_payload,
            )
            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError as exc:
                preview = response.text.strip().replace("\n", " ")[:300] or "响应体为空"
                raise llm_transport.LLMEmptyResponseError(
                    f"模型服务返回 HTTP {response.status_code}，但响应不是有效 JSON：{preview}"
                ) from exc
    except Exception as exc:
        llm_transport.log_llm_failure(
            transport="responses",
            target=target,
            payload=request_payload,
            exc=exc,
            attempt=1,
            response=response if response is not None else getattr(exc, "response", None),
        )
        raise
    if not isinstance(payload, dict):
        exc = RuntimeError("模型服务返回的 Responses 响应不是 JSON 对象")
        llm_transport.log_llm_failure(
            transport="responses", target=target, payload=request_payload,
            exc=exc, attempt=1, response=response,
        )
        raise exc
    return _responses_message(payload)


async def _call_llm_stream(
    cfg: LLMConfigSnapshot,
    messages: list[dict],
    tools: list[dict],
    abort_event: asyncio.Event,
    timeout: int = 180,
) -> AsyncIterator[dict]:
    """流式 chat completion。yield 事件字典：

    - {"type": "content_delta", "text": "..."}
    - {"type": "tool_call_delta", "index": int, "id": str|None, "name": str|None, "arguments": str|None}
    - {"type": "done", "message": {content, tool_calls}, "usage": dict|None}

    usage 来自 OpenAI 兼容网关的 include_usage chunk（prompt_tokens/completion_tokens/…），
    网关不支持时为 None。上层 run_agent 拼装好 final message 之后再走持久化。

    SSE 解析 / 累积 / 重试逻辑已收口到 app.llm_transport.stream_chunks;这里只负责
    构造 payload(含 ai_chat 的 _apply_provider_payload_compat + include_usage)与 URL/timeout。
    """
    payload = {
        "model": cfg.model,
        "messages": messages,
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
        "stream": True,
        # 让 OpenAI 兼容网关在 [DONE] 前回一个带 usage 的 chunk（token 必采）
        "stream_options": {"include_usage": True},
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    _apply_provider_payload_compat(cfg, payload)
    if getattr(cfg, "api_format", "chat_completions") == "responses":
        message = await _call_llm(cfg, messages, tools, timeout=timeout)
        content = message.get("content") or ""
        if content:
            yield {"type": "content_delta", "text": content}
        for index, tool_call in enumerate(message.get("tool_calls") or []):
            function = tool_call.get("function") or {}
            yield {
                "type": "tool_call_delta",
                "index": index,
                "id": tool_call.get("id"),
                "name": function.get("name"),
                "arguments_so_far": function.get("arguments") or "",
            }
        yield {"type": "done", "message": message, "usage": None}
        return
    async for chunk in llm_transport.stream_chunks(
        base_url=cfg.base_url,
        api_key=cfg.api_key,
        payload=payload,
        timeout=httpx.Timeout(connect=10, read=timeout, write=10, pool=10),
        abort_event=abort_event,
        retry_attempts=LLM_RETRY_ATTEMPTS,
        url=_llm_chat_completions_url(cfg),
        extra_headers=getattr(cfg, "extra_headers", {}) or {},
    ):
        yield chunk


async def _call_llm_stream_with_fallback(
    cfg: LLMConfigSnapshot,
    messages: list[dict],
    tools: list[dict],
    abort_event: asyncio.Event,
    timeout: int = 180,
) -> AsyncIterator[dict]:
    """Prefer streaming; if the gateway refuses streaming, fall back to non-streaming."""
    try:
        async for chunk in _call_llm_stream(cfg, messages, tools, abort_event, timeout=timeout):
            yield chunk
        return
    except httpx.HTTPStatusError as stream_exc:
        # Some OpenAI-compatible gateways accept the same Chat Completions
        # request normally but reject its streaming transport at their proxy
        # layer (for example with a 502 HTML page).  A regular completion is
        # still safe to use and keeps the Code conversation functional.  Do
        # not mask client errors: those describe an invalid model/request and
        # require the user to fix the configuration instead.
        if stream_exc.response.status_code < 500:
            raise
        logger.warning(
            "LLM streaming request returned HTTP %s; retrying non-streaming",
            stream_exc.response.status_code,
        )
    except Exception as stream_exc:
        if not _is_retryable_llm_error(stream_exc):
            raise
        logger.warning(
            "LLM stream failed after retries; falling back to non-stream request: %s",
            _format_llm_error(stream_exc),
        )
    # Keep the model/messages/tools shape, but omit optional generation controls.
    # Some OpenAI-compatible gateways accept ``max_tokens`` syntactically then
    # answer HTTP 200 with an empty body; the minimal Chat request is known to
    # work for those providers and still supports tool calls.
    try:
        message = await _call_llm(
            cfg,
            messages,
            tools,
            timeout=timeout,
            omit_generation_controls=True,
        )
    except llm_transport.LLMEmptyResponseError:
        # This branch is deliberately narrower than a general retry: the
        # transport already retried the same request.  The next attempt changes
        # only an optional OpenAI field, keeps real tool schemas intact, and is
        # tailored for gateways that return a misleading 200-empty response for
        # explicit ``tool_choice: auto`` after a clarification card.
        logger.warning(
            "LLM non-stream fallback returned an empty success body; retrying without tool_choice"
        )
        message = await _call_llm(
            cfg,
            messages,
            tools,
            timeout=timeout,
            omit_generation_controls=True,
            omit_tool_choice=True,
        )
    content = message.get("content") or ""
    if content:
        yield {"type": "content_delta", "text": content}
    for idx, tc in enumerate(message.get("tool_calls") or []):
        fn = tc.get("function") or {}
        yield {
            "type": "tool_call_delta",
            "index": idx,
            "id": tc.get("id"),
            "name": fn.get("name"),
            "arguments_so_far": fn.get("arguments") or "",
        }
    yield {"type": "done", "message": message, "usage": None}


# ─────────────────────────── 构建 agent 输入 ───────────────────────────


def _session_app_context_id(session: AIChatSession) -> int | None:
    """System-assistant conversations never inherit product application context."""
    if getattr(session, "assistant_profile", None) == "system_assistant":
        return None
    return getattr(session, "app_id", None)

async def _build_initial_messages(
    db: AsyncSession, session: AIChatSession, current_user_message: str,
    section: Optional[str] = None,
    view_context: Optional[str] = None,
    system_prompt_override: Optional[str] = None,
) -> list[dict]:
    """从历史消息 + 当前 user message 构造 LLM messages。

    跨轮重建关键点（参考 Claude Code 的做法）：
      - assistant 的 tool_use turn 要带 tool_calls 字段重新拼回
      - 紧跟 role:tool 消息，每条 tool_call_id 必须跟 assistant.tool_calls[i].id 对齐
      - tool_result 跨轮保留：read_attachment 截断到 30K、read_artifact 截断到 30K、
        MCP 工具截断到 20K（截断逻辑在各自执行函数/mcp_bridge 里）
    """
    # 静态模板走 DB-first（agent_prompts: unified/system），动态拼接在下面照旧。
    # profile 覆盖(如 dev-apaas 的定制提示词)优先;app 上下文/技能清单等动态段仍照常拼。
    if system_prompt_override:
        system_prompt = system_prompt_override
    else:
        system_prompt = await _resolve_unified_system_prompt(
            db, getattr(session, "tenant_id", None),
        )
    assistant_profile = getattr(session, "assistant_profile", None)
    app_id = _session_app_context_id(session)
    if app_id:
        from app.ai_chat.app_context import build_app_context_block
        system_prompt = system_prompt + await build_app_context_block(
            db, app_id, section=section, tenant_id=getattr(session, "tenant_id", None),
            view_context=view_context, user_id=getattr(session, "user_id", None),
        )
    elif view_context:
        # 没绑 app(如 Code 工作区会话,app_id 为空)也要把 view_context 注入提示词,
        # 否则它只在 build_app_context_block 里拼 → app_id 为空就被整段跳过,agent 看不到
        # 当前工作区 ws_id → 要么瞎猜别的工作区、要么反过来问用户 ws_id(两种都实测过)。
        system_prompt = system_prompt + "\n\n## 当前工作上下文\n" + view_context
    messages: list[dict] = [{"role": "system", "content": system_prompt}]

    # 历史消息（不含本次 user 消息——routes 已经写库了，这里读回来时要排除最新那条）
    res = await db.execute(
        select(AIChatMessage)
        .where(AIChatMessage.session_id == session.id)
        .order_by(AIChatMessage.id.asc())
    )
    history = res.scalars().all()

    # 同步拉所有 tool_calls，按 message_id 分组（保留时序）
    tc_res = await db.execute(
        select(AIChatToolCall)
        .where(AIChatToolCall.session_id == session.id)
        .order_by(AIChatToolCall.id.asc())
    )
    allowed_history_tools: set[str] | None = None
    if assistant_profile == "system_assistant":
        from app.agents.profile import resolve_overrides_for_session
        _prompt, allowed_history_tools, _ws_id = resolve_overrides_for_session(session)

    tcs_by_msg: dict[int, list[AIChatToolCall]] = {}
    for tc in tc_res.scalars().all():
        if allowed_history_tools is not None and tc.tool_name not in allowed_history_tools:
            continue
        if tc.message_id is not None:
            tcs_by_msg.setdefault(tc.message_id, []).append(tc)

    for m in history[:-1]:  # 排除最后一条（最新 user message，外部传 current_user_message）
        if m.role == "user":
            messages.append({"role": "user", "content": m.content})
        elif m.role == "assistant":
            meta = m.extra_meta or {}
            if (
                (isinstance(meta, dict) and meta.get("notice_type") == "llm_error")
                or (m.content or "").startswith("本轮执行中断：模型调用失败")
            ):
                continue
            persisted_tool_calls = meta.get("tool_calls") if isinstance(meta, dict) else None
            if persisted_tool_calls and allowed_history_tools is not None:
                persisted_tool_calls = [
                    tool_call
                    for tool_call in persisted_tool_calls
                    if (tool_call.get("function") or {}).get("name") in allowed_history_tools
                ]
            if persisted_tool_calls:
                # tool_use turn：拼回带 tool_calls 的 assistant + 紧跟 role:tool 配对
                messages.append({
                    "role": "assistant",
                    "content": m.content or "",
                    "tool_calls": persisted_tool_calls,
                })
                related_tcs = tcs_by_msg.get(m.id, [])
                # 按 persisted_tool_calls 里的 id 顺序匹配，保证对齐
                tcs_by_call_id = {tc.provider_call_id: tc for tc in related_tcs if tc.provider_call_id}
                for ptc in persisted_tool_calls:
                    call_id = ptc.get("id")
                    if not call_id:
                        continue
                    tc_db = tcs_by_call_id.get(call_id)
                    result_content = _compact_tool_result_for_context(
                        (tc_db.result_text if tc_db else "") or ""
                    )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": result_content,
                    })
            else:
                # 普通 final answer
                messages.append({"role": "assistant", "content": m.content or ""})

    # 拼接附件清单到当前用户消息（让 LLM 知道有哪些附件可读）
    att_res = await db.execute(
        select(AIChatAttachment).where(AIChatAttachment.session_id == session.id)
    )
    attachments = att_res.scalars().all()
    suffix = ""
    if attachments:
        items = []
        for a in attachments:
            badge = "图片" if a.kind == "image" else f"{a.kind}"
            items.append(f"- 【{badge}】{a.filename}")
        suffix = "\n\n[已上传附件，可用 read_attachment 工具读取]\n" + "\n".join(items)

    # 当前 user 消息：有图片附件时用 OpenAI vision content 数组（text + image_url），
    # 让支持 vision 的模型直接看图；无图则纯文本（兼容不支持 vision 的模型，零影响）。
    text_content = (current_user_message or "") + suffix
    image_atts = [a for a in attachments if a.kind == "image" and getattr(a, "image_data_url", None)]
    if image_atts:
        content_parts: list[dict] = [{"type": "text", "text": text_content}]
        for a in image_atts:
            content_parts.append({"type": "image_url", "image_url": {"url": a.image_data_url}})
        messages.append({"role": "user", "content": content_parts})
    else:
        messages.append({"role": "user", "content": text_content})
    return messages


# ─────────────────────────── 主 agent loop ───────────────────────────

MAX_TURNS = 25  # 工具循环最大轮数（统一 config 的 25：app 配置/codegen 多步任务需要）

_SYSTEM_ASSISTANT_INTRO_RESPONSE = (
    "你好，我是 DolphinAI 的 Dolphin Code 系统助手，负责企业 Code 的系统级资产和标准能力建设。\n"
    "我可以协助四类工作：\n"
    "1. 盘点企业 Code 能力现状，给出种子工程、环境、工程规范和能力建设顺序。\n"
    "2. 查询和使用知识与 Skill，结合上传文件整理系统规范或资产草稿。\n"
    "3. 设计、检查和完善种子工程及其开发、测试、构建方案。\n"
    "4. 在明确绑定的系统资产工作区内修改文件并完成受控验证。\n"
    "具体应用工程中的修 bug、写接口、改页面和日常功能开发，请进入对应应用的 Code 会话。"
)


def _is_system_assistant_intro_request(session: AIChatSession, text: str) -> bool:
    """Only short greetings/capability prompts use the deterministic boundary reply.

    Keeping this narrow prevents a model from inventing unsupported platform
    capabilities while leaving all concrete work requests on the real agent loop.
    """
    if getattr(session, "assistant_profile", None) != "system_assistant":
        return False
    normalized = re.sub(r"[\s!！?？。.,，、:：；;]+", "", (text or "").strip().lower())
    return normalized in {
        "你好",
        "您好",
        "嗨",
        "hello",
        "hi",
        "在吗",
        "你是谁",
        "介绍一下自己",
        "你能做什么",
        "你可以做什么",
        "你有哪些能力",
    }


def _sse(event: str, data: dict) -> dict:
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}


async def _persist_assistant_notice(
    db: AsyncSession,
    session: AIChatSession,
    content: str,
    run_id: Optional[str] = None,
    notice_type: str = "llm_error",
) -> Optional[AIChatMessage]:
    """Persist a visible assistant notice so stream failures survive refresh."""
    try:
        msg = AIChatMessage(
            session_id=session.id,
            role="assistant",
            content=content,
            extra_meta={
                "notice_type": notice_type,
                **({"run_id": run_id} if run_id else {}),
            },
        )
        db.add(msg)
        await asyncio.shield(db.commit())
        await db.refresh(msg)
        return msg
    except Exception as exc:
        logger.warning("persist assistant notice failed: %r", exc)
        return None


def _assistant_message_event(msg: AIChatMessage) -> dict:
    meta = msg.extra_meta if isinstance(msg.extra_meta, dict) else {}
    payload = {
        "id": msg.id,
        "session_id": msg.session_id,
        "role": "assistant",
        "content": msg.content,
        "created_at": msg.created_at.isoformat(),
    }
    if meta.get("run_id"):
        payload["run_id"] = meta["run_id"]
    return _sse("assistant_message", payload)


async def run_agent(
    db: AsyncSession,
    session: AIChatSession,
    current_user_message: str,
    abort_event: asyncio.Event,
    section: Optional[str] = None,
    view_context: Optional[str] = None,
    system_prompt_override: Optional[str] = None,
    tool_names_override: Optional[set] = None,
) -> AsyncIterator[dict]:
    """对外入口：包一层 run 生命周期（可观测），把事件原样透传。

    用 try/finally 保证 end_run 在所有正常退出点 + SSE 客户端中途断开
    （GeneratorExit）时都恰好触发一次。recorder 自身吞异常，这里不会反噬主流程。

    system_prompt_override / tool_names_override：profile 化用(如 Code 二次开发的
    dev-apaas profile)。默认 None = 走通用 Builder 行为(prompt/全量工具),零影响。
    """
    holder: dict = {"run_id": None, "status": "error", "error": None}
    try:
        async for event in _run_agent_inner(
            db, session, current_user_message, abort_event, holder, section, view_context,
            system_prompt_override, tool_names_override,
        ):
            yield event
    finally:
        if holder["run_id"]:
            # shield：SSE 客户端断开会往本 task 抛 CancelledError（非 Exception 子类，
            # recorder 自身的 try/except 拦不住）。不 shield 的话 end_run 可能在 commit
            # 中途被取消，run 永远卡在 "running"。与本文件主流程 commit 用 shield 同理。
            await asyncio.shield(
                recorder.end_run(
                    holder["run_id"], status=holder["status"], error=holder["error"]
                )
            )


async def _run_agent_inner(
    db: AsyncSession,
    session: AIChatSession,
    current_user_message: str,
    abort_event: asyncio.Event,
    holder: dict,
    section: Optional[str] = None,
    view_context: Optional[str] = None,
    system_prompt_override: Optional[str] = None,
    tool_names_override: Optional[set] = None,
) -> AsyncIterator[dict]:
    """主 agent loop body。run 生命周期由外层 run_agent wrapper 管。
    holder = {"run_id": str|None, "status": "running"/"success"/"error", "error": str|None}
    """
    # SP2a:调用方未显式传 override 时,按 session.mode 推导(code 会话 → dev-apaas +
    # 收窄工具 + 单工作区锁 + ws 绑定 view_context)。harness 老路显式传 override → 原样透传。
    system_prompt_override, tool_names_override, _derived_vc = _apply_session_overrides(
        session, system_prompt_override, tool_names_override
    )
    # Keep the profile decision local to this run.  The schema merge below and
    # the local knowledge/Skill manifest gate must use the same value; referring
    # to an outer helper's local here made every non-intro System Assistant turn
    # crash before its first model call.
    assistant_profile = getattr(session, "assistant_profile", None)
    # caller 未传 view_context 时,用推导出的 ws 绑定上下文 —— code 会话据此知道当前 ws_id,
    # 不再反问「请把 ws_id 发我」(2026-06-25 修复)。caller 显式传的 view_context 优先。
    view_context = view_context or _derived_vc

    # 纯问候/能力询问不需要模型推理。固定回复同时作为能力边界，避免旧模型提示词
    # 缓存或自由生成时把平台管理能力误报给用户；具体任务仍完整走真实 agent loop。
    if _is_system_assistant_intro_request(session, current_user_message):
        msg = await _persist_assistant_notice(
            db,
            session,
            _SYSTEM_ASSISTANT_INTRO_RESPONSE,
            notice_type="system_assistant_intro",
        )
        if msg:
            yield _assistant_message_event(msg)
        yield _sse("done", {"ok": True})
        return

    try:
        cfg = await _resolve_llm_config(db, session)
    except RuntimeError as e:
        yield _sse("error", {"error": str(e)})
        yield _sse("done", {"ok": False})
        return

    yield _sse("thinking", {"text": f"使用模型：{cfg.model}"})

    # ── 可观测：开 run（旁路；config 解析失败的早退发生在此之前，不记） ──
    holder["run_id"] = await recorder.start_run(
        agent_type="ai_builder",
        tenant_id=getattr(session, "tenant_id", None),
        user_id=getattr(session, "user_id", None),
        session_id=session.id,
        app_id=_session_app_context_id(session),
        model=cfg.model,
    )
    yield _sse("run_started", {"run_id": holder["run_id"]})
    _obs_seq = 0  # run 内 step 单调递增序号

    try:
        messages = await _build_initial_messages(
            db, session, current_user_message, section, view_context,
            system_prompt_override=system_prompt_override,
        )
    except Exception as e:
        holder["error"] = f"构建上下文失败：{e}"
        yield _sse("error", {"error": holder["error"]})
        yield _sse("done", {"ok": False, "run_id": holder["run_id"]})
        return

    asked_user = False  # 一旦 ask_user，loop 提前退出

    # 每个 session 的第一轮拉一次合并 schemas（base 4 + MCP bridge 注入的 N 个）
    # 这是 lazy 设计 — backend 启动时 MCP 可能还没 ready，所以放在 turn loop 外的第一次调用
    all_schemas = await get_all_tool_schemas()
    if getattr(session, "assistant_profile", None) == "system_assistant":
        # 系统资产管理工具不属于普通 Builder/Code 的通用工具池；只在这里按
        # profile 显式合并，随后仍会通过该 profile 的严格白名单。
        system_asset_schemas = await get_system_asset_tool_schemas()
        by_name = {
            schema.get("function", {}).get("name"): schema
            for schema in all_schemas
        }
        for schema in system_asset_schemas:
            name = schema.get("function", {}).get("name")
            if name and name not in by_name:
                all_schemas.append(schema)
                by_name[name] = schema
    # profile 工具白名单。旧 entry_agent/dev-apaas 继续恒保留 AIChat base tools；
    # system_assistant 则严格按白名单过滤，避免会话临时目录工具绕过 ws_id 工作区边界。
    if tool_names_override is not None:
        from app.ai_chat.tools import _BASE_LOCAL_NAMES
        _allow = set(tool_names_override)
        _strict_base_allow = (
            getattr(session, "assistant_profile", None) == "system_assistant"
        )
        all_schemas = [
            s for s in all_schemas
            if s.get("function", {}).get("name") in _allow
            or (
                not _strict_base_allow
                and s.get("function", {}).get("name") in _BASE_LOCAL_NAMES
            )
        ]
    # 延迟工具:核心集恒在；长尾只在 system prompt 列清单，按需 search_tools 激活。
    core_schemas, deferred_by_name = split_core_deferred(all_schemas)
    _manifest = build_deferred_manifest(deferred_by_name)
    if _manifest and messages and isinstance(messages[0], dict) and messages[0].get("role") == "system":
        messages[0]["content"] = (messages[0].get("content") or "") + _manifest
    elif _manifest:
        logger.warning("deferred manifest skipped: messages[0] is not a system message")
    # System Assistant must query the remote Builder AI Control Plane through
    # system-asset MCP tools.  Its local desktop skill directory and local DB
    # knowledge catalogue are implementation caches, not enterprise assets.
    # Other assistant profiles keep the legacy local manifests unchanged.
    if assistant_profile != "system_assistant":
        _append_skill_manifest(messages)
        await _append_knowledge_manifest(messages, db)
    active_tool_names: set[str] = await _reconstruct_active_tools(db, session)

    for turn in range(MAX_TURNS):
        if abort_event.is_set():
            holder["status"] = "aborted"
            yield _sse("aborted", {"turn": turn})
            yield _sse("done", {"ok": False, "aborted": True, "run_id": holder["run_id"]})
            return

        # 上下文压缩：每轮 LLM 调用前压缩累积的老 tool 结果（保留最近 4 条完整，
        # 更老的压到 200 字）。只缩 role=="tool" 的 content，不动 system/user/assistant，
        # 保留消息结构与 tool_call_id 配对，故不破坏 OpenAI 的 assistant.tool_calls↔tool 配对。
        # 根因：get_application 等工具被反复轮询，整段原样堆进 messages → 400 context_too_large。
        # 对齐 coding 路径 agents/coding/agent.py 的用法。
        try:
            from app.context_compact import ContextCompactor
            messages = ContextCompactor.clean_tool_results(messages, keep_recent=4)
        except Exception as _compact_exc:  # noqa: BLE001
            logger.warning("clean_tool_results 压缩失败，跳过本轮压缩: %s", _compact_exc)

        # 流式调用 LLM，逐 token 把 content_delta 推给前端
        # 2026-05-16：合并细碎 chunk —— LLM 每个汉字一个 content_delta，前端每收一个
        # 就 Vue reactive + markdown re-render，累积起来卡顿。这里 buffer 到 ≥20 字符
        # 或 ≥40ms 才 flush，把几百 event 压成几十个。tool_call_delta / done 之前必须
        # 先 flush 剩余 buffer，保证次序正确（assistant 文字早于 tool_call chip）。
        assistant_msg: Optional[dict] = None
        _delta_buf: list[str] = []
        _delta_buf_len = 0
        _delta_last_flush = time.monotonic()
        DELTA_FLUSH_CHARS = 20
        DELTA_FLUSH_MS = 0.04

        def _drain_delta() -> Optional[dict]:
            nonlocal _delta_buf, _delta_buf_len, _delta_last_flush
            if not _delta_buf:
                return None
            text = "".join(_delta_buf)
            _delta_buf = []
            _delta_buf_len = 0
            _delta_last_flush = time.monotonic()
            return _sse("assistant_delta", {"text": text})

        # 每轮重算 tool_schemas：core 恒在 + 本轮已激活的延迟工具
        tool_schemas = core_schemas + [deferred_by_name[n] for n in active_tool_names if n in deferred_by_name]

        try:
            async for chunk in _call_llm_stream_with_fallback(cfg, messages, tool_schemas, abort_event):
                if chunk["type"] == "content_delta":
                    _delta_buf.append(chunk["text"])
                    _delta_buf_len += len(chunk["text"])
                    if (
                        _delta_buf_len >= DELTA_FLUSH_CHARS
                        or (time.monotonic() - _delta_last_flush) >= DELTA_FLUSH_MS
                    ):
                        evt = _drain_delta()
                        if evt is not None:
                            yield evt
                elif chunk["type"] == "tool_call_delta":
                    evt = _drain_delta()
                    if evt is not None:
                        yield evt
                    yield _sse(
                        "tool_call_delta",
                        {
                            "index": chunk["index"],
                            "name": chunk.get("name"),
                            "arguments_so_far": chunk.get("arguments_so_far") or "",
                        },
                    )
                elif chunk["type"] == "done":
                    evt = _drain_delta()
                    if evt is not None:
                        yield evt
                    assistant_msg = chunk["message"]
                    _obs_usage = chunk.get("usage") or {}
                    _obs_seq += 1
                    await recorder.record_step(
                        holder["run_id"], step_type="llm", seq=_obs_seq,
                        prompt_tokens=_obs_usage.get("prompt_tokens"),
                        completion_tokens=_obs_usage.get("completion_tokens"),
                    )
            if assistant_msg is None:
                # 流被外部 abort 了
                holder["status"] = "aborted"
                yield _sse("aborted", {"turn": turn})
                yield _sse("done", {"ok": False, "aborted": True, "run_id": holder["run_id"]})
                return
        except httpx.HTTPStatusError as e:
            # 流式 response 必须 aread 才能拿 .text；老代码直接 .text 会被
            # httpx 抛 ResponseNotRead 把真错盖住（2026-05-14 修）
            try:
                await e.response.aread()
                detail = e.response.text[:300]
            except Exception:
                detail = "(响应体读取失败)"
            error_text = f"本轮执行中断：模型调用失败 {e.response.status_code}: {detail}"
            holder["error"] = error_text
            msg = await _persist_assistant_notice(db, session, error_text, run_id=holder["run_id"])
            if msg:
                yield _assistant_message_event(msg)
            yield _sse("error", {"error": holder["error"]})
            yield _sse("done", {"ok": False, "run_id": holder["run_id"]})
            return
        except Exception as e:
            error_text = f"本轮执行中断：模型调用失败：{_format_llm_error(e)}。已完成的工具结果会保留，可稍后重试。"
            holder["error"] = error_text
            msg = await _persist_assistant_notice(db, session, error_text, run_id=holder["run_id"])
            if msg:
                yield _assistant_message_event(msg)
            yield _sse("error", {"error": holder["error"]})
            yield _sse("done", {"ok": False, "run_id": holder["run_id"]})
            return

        tool_calls = assistant_msg.get("tool_calls") or []
        content = (assistant_msg.get("content") or "").strip()

        # 把 LLM 的回复加进 messages history（让下一轮看到）
        messages.append({
            "role": "assistant",
            "content": content,
            "tool_calls": tool_calls if tool_calls else None,
        })

        # 没有工具调用：output final 文本然后结束
        if not tool_calls:
            # 2026-05-21：LLM 跑完一串工具后可能直接 stop 没输出文本（gpt-5.5 实测在
            # generate_app_from_doc + deploy + get_application 链路尾巴沉默退出）。
            # 用户只看到工具卡片，看不到 app_id / app_view_url 总结，体验差。
            # → 在这里强行 inject 一段 system 提醒，再 stream 一次让它必须总结。
            # 限定只重试一次，避免 LLM 钻牛角尖死循环空响应。
            if not content:
                summary_hint = {
                    "role": "system",
                    "content": (
                        "你刚才调完了一串工具但没有给用户做总结。"
                        "请用 1-3 句中文向用户说明这次操作的结果（成功/失败、关键产物）。"
                        "如果工具结果里包含 app_id / app_view_url 等用户可用的链接或 ID，"
                        "把它写进总结里，并加一句『点击下方蓝色按钮去打开应用验证』。"
                        "不要再调用任何工具，只输出文本。"
                    ),
                }
                retry_messages = messages + [summary_hint]
                retry_assistant: Optional[dict] = None
                _delta_buf = []
                _delta_buf_len = 0
                _delta_last_flush = time.monotonic()
                try:
                    async for chunk in _call_llm_stream_with_fallback(cfg, retry_messages, tool_schemas, abort_event):
                        if chunk["type"] == "content_delta":
                            _delta_buf.append(chunk["text"])
                            _delta_buf_len += len(chunk["text"])
                            if (
                                _delta_buf_len >= DELTA_FLUSH_CHARS
                                or (time.monotonic() - _delta_last_flush) >= DELTA_FLUSH_MS
                            ):
                                evt = _drain_delta()
                                if evt is not None:
                                    yield evt
                        elif chunk["type"] == "done":
                            evt = _drain_delta()
                            if evt is not None:
                                yield evt
                            retry_assistant = chunk["message"]
                            _obs_ru = chunk.get("usage") or {}
                            _obs_seq += 1
                            await recorder.record_step(
                                holder["run_id"], step_type="llm", seq=_obs_seq,
                                prompt_tokens=_obs_ru.get("prompt_tokens"),
                                completion_tokens=_obs_ru.get("completion_tokens"),
                            )
                        # 忽略 tool_call_delta — system 已经禁止工具调用，万一 LLM 不听话也不执行
                except Exception as e:
                    logger.warning("final-summary retry failed: %s", e)
                    content = (
                        "前面的工具执行已完成，但生成最终总结时模型网关连接失败。"
                        "已完成的产出物已保留，请查看右侧产出物或稍后重试。"
                    )
                if retry_assistant:
                    forced = (retry_assistant.get("content") or "").strip()
                    if forced:
                        content = forced

            if content:
                # 持久化 assistant message
                # 2026-05-21 fix: asyncio.shield 防 client disconnect 把 commit cancel
                # 中断 — 之前 bug: auto-increment id 已分配但 COMMIT 命令没送达 mysql,
                # tool_call 表 message_id 引用查不到的 id (id 跳号 242/244/246), 后续
                # _build_initial_messages 重建 messages 序列错乱 LLM 卡死
                asst_db = AIChatMessage(
                    session_id=session.id,
                    role="assistant",
                    content=content,
                    extra_meta={"run_id": holder["run_id"]},
                )
                db.add(asst_db)
                await asyncio.shield(db.commit())
                await db.refresh(asst_db)
                yield _assistant_message_event(asst_db)
            holder["status"] = "success"
            yield _sse("done", {"ok": True, "run_id": holder["run_id"]})
            return

        # 有工具调用：每个执行一遍
        # 注：tool 之前的 content 已经通过 assistant_delta 流式推过了，
        # 前端会在 tool_call_start 时把 streaming buffer 锁定为一段"思考"
        if content:
            yield _sse("assistant_thinking_lock", {"text": content})

        # ── 持久化 assistant 这条 tool_use turn 到 DB（跨轮 history 重建必需）──
        # 把 LLM 返回的 tool_calls 序列化进 extra_meta（以便下次 _build_initial_messages
        # 重建消息时拼回完整的 assistant.tool_calls + role:tool 配对）
        persisted_tool_calls = [_compact_tool_call_for_storage(tc) for tc in tool_calls]
        asst_tool_use_db = AIChatMessage(
            session_id=session.id,
            role="assistant",
            content=content or "",
            extra_meta={"tool_calls": persisted_tool_calls},
        )
        db.add(asst_tool_use_db)
        # 2026-05-21 fix: shield 防 cancel — 见上方注释
        await asyncio.shield(db.commit())
        await db.refresh(asst_tool_use_db)
        asst_message_id = asst_tool_use_db.id

        for tc in tool_calls:
            if abort_event.is_set():
                holder["status"] = "aborted"
                yield _sse("aborted", {"turn": turn})
                yield _sse("done", {"ok": False, "aborted": True, "run_id": holder["run_id"]})
                return

            tc_id = tc.get("id", "")
            fn = tc.get("function", {})
            tool_name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:
                args = {}
            persisted_args = _compact_tool_args_for_storage(tool_name, args)

            # 持久化工具调用记录（关联 assistant message + 存 LLM 原始 call_id）
            # 用 monotonic 算 duration — MySQL DATETIME(0) round 到秒导致 refresh 后
            # started_at 跟 in-memory ended_at 算差出负数 (2026-05-16 实测 -58ms bug)
            _start_mono = time.monotonic()
            _start_dt = datetime.utcnow()
            tc_db = AIChatToolCall(
                session_id=session.id,
                message_id=asst_message_id,
                provider_call_id=tc_id or None,
                tool_name=tool_name,
                args_json=persisted_args,
                status="running",
                started_at=_start_dt,
            )
            db.add(tc_db)
            # 2026-05-21 fix: shield 防 cancel
            await asyncio.shield(db.commit())
            await db.refresh(tc_db)
            yield _sse("tool_call_start", {
                "id": tc_db.id,
                "tool_name": tool_name,
                "args": persisted_args,
                "started_at": _start_dt.isoformat(),
            })

            governance_request = _consume_governance_action_request(session, tool_name)
            if governance_request is not None:
                result_text, action_run = await _execute_governed_live_tool(
                    db, session, tc_db, tool_name, args, governance_request,
                )
                await db.refresh(tc_db)
                if action_run is None:
                    tc_db.status = "error"
                    tc_db.error_message = "GOVERNED_TOOL_UNCONFIRMED"
                else:
                    tc_db.result_text = result_text
                    apply_tool_call_projection(tc_db, action_run)
            else:
                # 执行
                try:
                    # Keep the public dispatcher contract string-only even when a
                    # legacy handler accidentally returns a structured value.
                    result_text = legacy_result_text(await execute_tool(tool_name, args, session, db))
                    tc_db.status = "success"
                    tc_db.result_text = result_text
                    if tool_name == "search_tools":
                        active_tool_names.update(_parse_activated(result_text))
                except Exception as e:
                    tc_db.status = "error"
                    tc_db.error_message = str(e)
                    tc_db.result_text = f"错误：{e}"
                    result_text = tc_db.result_text

                action_run = await _completed_action_run_for_tool_call(db, tc_db.id)
                if action_run is not None:
                    apply_tool_call_projection(tc_db, action_run)

            if action_run is not None:
                tc_db.result_text = result_text

            tc_db.ended_at = datetime.utcnow()
            tc_db.duration_ms = int((time.monotonic() - _start_mono) * 1000)
            # 2026-05-21 fix: shield 防 cancel
            await asyncio.shield(db.commit())
            await db.refresh(tc_db)

            displayed_result = result_text[:600] + ("..." if len(result_text) > 600 else "")
            if action_run is None:
                yield _sse("tool_call_end", {
                    "id": tc_db.id,
                    "tool_name": tool_name,
                    "status": tc_db.status,
                    "result_text": displayed_result,
                    "duration_ms": tc_db.duration_ms,
                })
            else:
                end_event = project_sse_end(
                    action_run,
                    tool_call_id=tc_db.id,
                    tool_name=tool_name,
                    result_text=displayed_result,
                    duration_ms=tc_db.duration_ms,
                )
                yield _sse(end_event["event"], end_event["data"])

            # ── 可观测：双写 tool step（AIChatToolCall 已写，这里给统一底座再记一笔） ──
            _obs_seq += 1
            step_kwargs = {
                "step_type": "tool", "seq": _obs_seq, "tool_name": tool_name,
                "args": args, "result_text": result_text, "status": tc_db.status,
                "duration_ms": tc_db.duration_ms,
            }
            if action_run is None:
                await recorder.record_step(holder["run_id"], **step_kwargs)
            else:
                async def _record_projection(payload: dict[str, Any]) -> None:
                    await recorder.record_step(holder["run_id"], **{
                        **step_kwargs,
                        **payload,
                    })

                await project_agent_step(
                    action_run, result_text=result_text, recorder=_record_projection,
                )

            # 特殊：write_artifact 成功 → 单独通知前端刷新右栏
            # 2026-05-21 扩展：update_app_from_doc / export_apaas_app_design_doc 也会
            # 被 dispatcher 拦截把 md_content 落 artifact（见 tools._persist_spec_artifact），
            # 这两个工具结束时也得发 artifact_created 让右栏立即刷新。
            # 2026-05-24: generate_app_from_doc 改强制 artifact_id 后, 不再产新 artifact
            # (用户 write_artifact 已经落表), 从列表去掉.
            _emits_artifact = (
                (tool_name in ("write_artifact", "edit_artifact", "save_binary_artifact")
                 and tc_db.status == "success")
                or (tool_name in (
                    "update_app_from_doc",
                    "export_apaas_app_design_doc",
                ) and tc_db.status == "success")
            )
            if _emits_artifact:
                from sqlalchemy import desc as _desc
                # write_artifact / save_binary_artifact: filename 在 args（save_binary_artifact
                # 默认用源文件名，但可被 filename 覆盖）→ 优先按 filename 拉；拉不到再退回最近一条。
                # generate/update_app_from_doc: 不知道 dispatcher 落 artifact 用了什么 filename，
                # 直接拉本 session 最近落的那条。
                wanted_name = args.get("filename")
                if tool_name == "save_binary_artifact" and not wanted_name:
                    wanted_name = (args.get("source_path") or "").split("/")[-1] or None
                art = None
                if tool_name in ("write_artifact", "edit_artifact", "save_binary_artifact") and wanted_name:
                    res = await db.execute(
                        select(AIChatArtifact)
                        .where(
                            AIChatArtifact.session_id == session.id,
                            AIChatArtifact.filename == wanted_name,
                        )
                        .order_by(_desc(AIChatArtifact.version))
                        .limit(1)
                    )
                    art = res.scalar_one_or_none()
                if art is None:
                    res = await db.execute(
                        select(AIChatArtifact)
                        .where(AIChatArtifact.session_id == session.id)
                        .order_by(_desc(AIChatArtifact.id))
                        .limit(1)
                    )
                    art = res.scalar_one_or_none()
                if art:
                    _is_file = (getattr(art, "storage", None) or "text") == "file"
                    yield _sse("artifact_created", {
                        "id": art.id,
                        "filename": art.filename,
                        "format": art.format,
                        "version": art.version,
                        "storage": getattr(art, "storage", None) or "text",
                        # file 产物 content 为空 → preview 给文件名，size_bytes 给真实大小，
                        # 让前端能渲染下载卡片而非空白
                        "preview": art.filename if _is_file else (art.content or "")[:200],
                        "size_bytes": (art.size_bytes or 0) if _is_file else len((art.content or "").encode("utf-8")),
                    })

            # 特殊：ask_clarifying_question → loop 暂停等用户
            if tool_name == "ask_clarifying_question":
                try:
                    parsed = json.loads(result_text)
                    if isinstance(parsed, dict) and parsed.get("_special") == "ask_user":
                        yield _sse("ask_user", {
                            "tool_call_id": tc_db.id,
                            "question": parsed.get("question", ""),
                            "options": parsed.get("options", []),
                        })
                        asked_user = True
                except Exception:
                    pass

            # 把 tool_result 喂回 messages
            messages.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": _compact_tool_result_for_context(result_text),
            })

        if asked_user:
            # 提了问题就停 loop，等下一轮 user send
            holder["status"] = "success"
            yield _sse("done", {"ok": True, "awaiting_user": True, "run_id": holder["run_id"]})
            return

    # 超过 MAX_TURNS
    holder["error"] = f"达到最大循环次数 {MAX_TURNS}，已停止"
    yield _sse("error", {"error": holder["error"]})
    yield _sse("done", {"ok": False, "run_id": holder["run_id"]})
