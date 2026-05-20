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
import json
import logging
import time
from datetime import datetime
from typing import AsyncIterator, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import decrypt_password
from app.doc_spec_standard import STANDARD_DOC_FORMAT
from app.models import (
    AIChatSession,
    AIChatMessage,
    AIChatToolCall,
    AIChatAttachment,
    AIChatArtifact,
    LLMConfig,
)
from app.ai_chat.tools import TOOL_SCHEMAS, execute_tool, get_all_tool_schemas

logger = logging.getLogger(__name__)


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
- 输出 md 时严格按上面 6 个章节顺序，章节不能跳过；缺信息留空单元格即可，不要写"未定义"、"待定"占位文字
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
3. 图片类材料也要 read_attachment 拿到 OCR / 描述
4. 读完给用户一个**结构化的"我看到了什么"汇总**：识别出 **A 张数据表** / **B 个角色** / **C 个流程** / **D 个枚举字段**
5. **批量**列出 3-5 个澄清问题，每个问题写明"如果选 X / 选 Y 会影响什么"
6. 需求清晰后 write_artifact 一次写完整篇 6 章 markdown 设计文档（应用信息 / 角色 / 字典 / 模型 / 表单 / 权限）

### 姿态 B：用户没材料只有想法 → 对话挖需求 → 产文档
1. 跟着用户节奏问，每轮最多 1-2 个关键问题（用 ask_clarifying_question）
2. 数据类需求也能用 run_python 编程分析
3. 需求清晰后 write_artifact 一次写完整篇

### 姿态 C：用户要写代码 / 二次开发 / 自开发 → 调代码工具 + 在消息里给代码
**关键约束**：你不仅要把代码写到 workspace（用 write_workspace_files / vibe_write_file），
**还要在 chat 消息里用 markdown ```代码块``` 把核心片段给用户看一遍**。
不要只丢一句"已写完"就完事——用户没法预览看不到工具卡内部的代码，体验差。

判断走哪条路：
- 给已有 aPaaS 应用做组件 / 页面 / 后端接口扩展 → **AI Coding 路径**：
  list_dev_scenes → get_dev_scene_spec → list_apaas_apps_in_env → list_apaas_app_menus
  → create_dev_workspace → write_workspace_files / edit_workspace_files → run_workspace_command
  → enable_apaas_self_dev_config + attach_dev_packages_to_apaas_app + republish_apaas_app
- 从零搭独立项目（Vue / Next / Go / Python 等，跟 aPaaS 无关）→ **Vibe Coding 路径**：
  vibe_create_workspace → vibe_run_command('npm create vite@latest .') → vibe_write_file
  / vibe_edit_file → vibe_run_command('npm install / build / dev') → vibe_http_check 验证

**代码展示规则**（重要）：
- 写完一个文件，在回复消息里用 ```\\`\\`\\`vue` / ```\\`\\`\\`ts` 等代码块**展示关键内容**
- 长文件可以截关键部分（如组件定义、API 调用、配置）+ 说"完整代码已写到 workspace/<path>"
- 多文件场景：每个文件一个代码块，加上文件路径作为代码块前的说明（**📄 src/components/X.vue**）
- 用户要看完整文件时再读 workspace（你已经写进去了）

### 全栈产物能力（write_artifact 也能产代码到右侧面板）
**除了产 markdown 设计文档外**，当用户说"开发页面 / 写个组件 / 给我个自开发包 / 后端接口存根"时，你应当**用 write_artifact** 把代码也作为产物落到右侧面板（不只是写到 workspace 工具卡里），让用户一眼看见、能下载：
- Vue 单文件组件 → `TalentDashboard.vue` (format=vue) — 完整 `<template>/<script setup>/<style>`
- 自开发包 manifest → `talent-dashboard-package.json` (format=json) — name/version/components/routes/entry
- 自开发包说明 → `talent-dashboard-self-dev-package.md` (format=md) — 包结构 / 集成步骤 / 部署说明
- 后端接口存根 → `talent_routes.py` (format=py) — FastAPI 路由 stub
- TS 类型定义 → `talent.types.ts` (format=ts)

写代码产物的标准三件套：**SPEC.md（设计文档） + Component.vue（核心组件） + package.json / 自开发包说明.md** 配套交付，三者并列放右侧面板。code 类 artifact 不替代 write_workspace_files / vibe_write_file（那些是写进沙箱给后续构建用），而是**给用户看的展示层**。

## 工具速查（55 个，按场景挑用）

文档处理：parse_design_doc / validate_builder_doc / write_artifact / read_attachment
aPaaS 内省：list_apaas_apps_in_env / list_apaas_app_menus / list_apaas_form_views / list_apaas_form_components / list_apaas_app_models / list_apaas_app_dicts
应用生命周期：generate_app_from_doc / get_application / update_app_from_doc / execute_change_plan / deploy_application / publish_application
自开发场景：list_dev_scenes / get_dev_scene_spec / get_dev_scene_full_workflow
AI Coding workspace：create_dev_workspace / read_workspace_file / write_workspace_files / edit_workspace_files / glob_workspace / grep_workspace / run_workspace_command
自开发发布：enable_apaas_self_dev_config / attach_dev_packages_to_apaas_app / republish_apaas_app / create_apaas_self_dev_menu
Vibe Coding 全代码：vibe_create_workspace / vibe_read_file / vibe_write_file / vibe_edit_file / vibe_glob / vibe_grep / vibe_run_command / vibe_todo_write / vibe_http_check

{_FORMAT_CONSTRAINTS}"""


# 旧的 chat / cowork prompt 保留（routes/applications/__init__.py 的 chat-session/ensure
# 还可能传 mode 进来），但 _select_system_prompt 永远返回统一版
SYSTEM_PROMPT_CHAT = f"""你是 aPaaS 平台的 AI 需求分析师，帮用户把**模糊的搭建需求**梳理成可被 Builder 流水线直接解析的标准设计文档。

工作模式（chat 从零理需求）：
1. 用户没有现成材料，靠对话挖需求；如有附件，调 read_attachment 辅助理解
2. 跟着用户节奏问，每轮最多 1-2 个关键问题（用 ask_clarifying_question）
3. 数据类材料（xlsx/csv）可用 run_python 编程分析（pandas / openpyxl 都能用）
4. 当需求清晰后，调 write_artifact 输出 markdown 设计文档；filename 建议 `{{应用名}}-设计文档.md`

{_FORMAT_CONSTRAINTS}"""


SYSTEM_PROMPT_COWORK = f"""你是 aPaaS 平台的 AI 协作分析师，帮用户把**一堆杂乱材料**（PDF / Word / Excel / 截图 / 现有文档）整合成可被 Builder 流水线直接解析的标准设计文档。

工作模式（cowork 批量材料整合）—— **跟 chat 模式不一样**：

## 第一步：并行消化所有材料（不等用户引导）
用户进来时往往已经把所有材料一起上传完了。你的第一个动作不是问"你要做什么"，而是：
- 立刻**并行**调 read_attachment 把每一份附件都读一遍（一次回复里可以调多个工具）
- 数据类材料（xlsx/csv）配合 run_python 抽要点：表头、行数、枚举值分布、关键字段
- 图片类材料（架构图 / 截图 / 流程图）也要 read_attachment 拿到 OCR/描述

## 第二步：综合摘要 + 批量提问
读完所有材料后，给用户一个**结构化的"我看到了什么"汇总**：
- 我从你的 N 份材料里识别出：**A 张数据表**（列出名字）/ **B 个角色**（列出）/ **C 个流程**（列出）/ **D 个枚举值字段**（列出）
- 我推断的应用类型 = ...
- **同时**列出 3-5 个澄清问题（**批量**问，不是一句一句挤），每个问题写明"如果选 X / 如果选 Y 会影响什么"

## 第三步：用户回答后产出第一版 md
- 立刻 write_artifact 写出第一版完整 6 章设计文档（应用信息 / 角色 / 字典 / 模型 / 表单 / 权限）
- 不要分章节交付，一次写完整篇

## 第四步：迭代修订
- 用户继续提修订意见时，read_attachment 拿到当前 artifact，做精准修改后 write_artifact 同名覆盖
- 涉及到字段命名、模型关联、权限矩阵这种细节，主动用 run_python 验证一致性

{_FORMAT_CONSTRAINTS}

## cowork 模式特别强调
- **不要先问"你要做什么"**——用户已经用文件告诉你了，直接读
- **不要分多轮试探**——用户期望"一站式整合"，不是漫长对话
- **批量并行**：read_attachment / run_python 一次回复里能调几个就调几个
- 反问尽量集中在一两轮，避免拉长流程"""


def _select_system_prompt(mode: Optional[str]) -> str:
    """统一 prompt — chat / cowork mode 已合并，统一用 UNIFIED 版（agent 看附件自己切流程）。

    mode 参数保留只是因为旧 session 表里还有这字段，不再实际影响行为。
    """
    return SYSTEM_PROMPT_UNIFIED


# 向后兼容：SYSTEM_PROMPT 指向统一版本
SYSTEM_PROMPT = SYSTEM_PROMPT_UNIFIED


# ─────────────────────────── LLM 调用辅助 ───────────────────────────

class LLMConfigSnapshot:
    """快照 LLMConfig 的解密信息，避免 db 异步调用穿透到 httpx。"""

    def __init__(self, base_url: str, api_key: str, model: str, max_tokens: int, temperature: float):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature


def _apply_provider_payload_compat(cfg: LLMConfigSnapshot, payload: dict) -> dict:
    model = (cfg.model or "").lower()
    base_url = (cfg.base_url or "").lower()
    if "qwen3" in model or "dashscope.aliyuncs.com" in base_url:
        payload["enable_thinking"] = False
    return payload


async def _resolve_llm_config(
    db: AsyncSession, session: AIChatSession
) -> LLMConfigSnapshot:
    """优先用 session.selected_llm_config_id；没指定则取该 tenant 的 default。"""
    cfg: Optional[LLMConfig] = None
    if session.selected_llm_config_id:
        res = await db.execute(
            select(LLMConfig).where(
                LLMConfig.id == session.selected_llm_config_id,
                LLMConfig.tenant_id == session.tenant_id,
            )
        )
        cfg = res.scalar_one_or_none()
    if not cfg:
        # fallback：tenant default
        res = await db.execute(
            select(LLMConfig)
            .where(
                LLMConfig.tenant_id == session.tenant_id,
                LLMConfig.is_default == True,  # noqa: E712
                LLMConfig.status == "active",
            )
            .limit(1)
        )
        cfg = res.scalar_one_or_none()
    if not cfg:
        raise RuntimeError(
            "找不到可用的 LLM 配置，请先在「大模型管理」里配置一个并设为默认。"
        )
    return LLMConfigSnapshot(
        base_url=cfg.base_url,
        api_key=decrypt_password(cfg.api_key_enc),
        model=cfg.model,
        max_tokens=cfg.max_tokens,
        temperature=cfg.temperature,
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
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=20, write=10, pool=10)) as client:
            resp = await client.post(
                f"{cfg.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {cfg.api_key}",
                    "Content-Type": "application/json",
                },
                json=_apply_provider_payload_compat(cfg, {
                    "model": cfg.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 60,
                }),
            )
            resp.raise_for_status()
            data = resp.json()
        title = (data["choices"][0]["message"].get("content") or "").strip()
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
) -> dict:
    """non-streaming chat completion + tool calling。返回 OpenAI 格式 response.choices[0].message"""
    payload = {
        "model": cfg.model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
    }
    _apply_provider_payload_compat(cfg, payload)
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=timeout, write=10, pool=10)) as client:
        resp = await client.post(
            f"{cfg.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {cfg.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]


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
    - {"type": "done", "message": {content, tool_calls}}

    上层 run_agent 拼装好 final message 之后再走持久化。
    """
    payload = {
        "model": cfg.model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
        "stream": True,
    }
    _apply_provider_payload_compat(cfg, payload)
    accumulated_content = ""
    tool_buf: dict[int, dict] = {}

    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=timeout, write=10, pool=10)) as client:
        async with client.stream(
            "POST",
            f"{cfg.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {cfg.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            json=payload,
        ) as resp:
            if resp.status_code >= 400:
                await resp.aread()
                resp.raise_for_status()
            async for raw_line in resp.aiter_lines():
                if abort_event.is_set():
                    break
                if not raw_line:
                    continue
                line = raw_line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except Exception:
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                if delta.get("content"):
                    text = delta["content"]
                    accumulated_content += text
                    yield {"type": "content_delta", "text": text}
                for tc in (delta.get("tool_calls") or []):
                    idx = tc.get("index", 0)
                    buf = tool_buf.setdefault(
                        idx,
                        {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                    )
                    if tc.get("id"):
                        buf["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        buf["function"]["name"] = fn["name"]
                    if fn.get("arguments"):
                        buf["function"]["arguments"] += fn["arguments"]
                    yield {
                        "type": "tool_call_delta",
                        "index": idx,
                        "id": buf["id"],
                        "name": buf["function"]["name"],
                        "arguments_so_far": buf["function"]["arguments"],
                    }

    final_tool_calls = [tool_buf[k] for k in sorted(tool_buf.keys())]
    yield {
        "type": "done",
        "message": {
            "content": accumulated_content,
            "tool_calls": final_tool_calls if final_tool_calls else None,
        },
    }


# ─────────────────────────── 构建 agent 输入 ───────────────────────────

async def _build_initial_messages(
    db: AsyncSession, session: AIChatSession, current_user_message: str
) -> list[dict]:
    """从历史消息 + 当前 user message 构造 LLM messages。

    跨轮重建关键点（参考 Claude Code 的做法）：
      - assistant 的 tool_use turn 要带 tool_calls 字段重新拼回
      - 紧跟 role:tool 消息，每条 tool_call_id 必须跟 assistant.tool_calls[i].id 对齐
      - tool_result 完整保留（已在执行时截断到 30K），让 LLM 跨轮看得到，避免重复 read
    """
    system_prompt = _select_system_prompt(getattr(session, "mode", None))
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
    tcs_by_msg: dict[int, list[AIChatToolCall]] = {}
    for tc in tc_res.scalars().all():
        if tc.message_id is not None:
            tcs_by_msg.setdefault(tc.message_id, []).append(tc)

    for m in history[:-1]:  # 排除最后一条（最新 user message，外部传 current_user_message）
        if m.role == "user":
            messages.append({"role": "user", "content": m.content})
        elif m.role == "assistant":
            meta = m.extra_meta or {}
            persisted_tool_calls = meta.get("tool_calls") if isinstance(meta, dict) else None
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
                    result_content = (tc_db.result_text if tc_db else "") or ""
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

    messages.append({"role": "user", "content": (current_user_message or "") + suffix})
    return messages


# ─────────────────────────── 主 agent loop ───────────────────────────

MAX_TURNS = 20  # 工具循环最大轮数


def _sse(event: str, data: dict) -> dict:
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}


async def run_agent(
    db: AsyncSession,
    session: AIChatSession,
    current_user_message: str,
    abort_event: asyncio.Event,
) -> AsyncIterator[dict]:
    """主 agent loop。yield SSE 事件给 routes 转发到前端。"""
    try:
        cfg = await _resolve_llm_config(db, session)
    except RuntimeError as e:
        yield _sse("error", {"error": str(e)})
        yield _sse("done", {"ok": False})
        return

    yield _sse("thinking", {"text": f"使用模型：{cfg.model}"})

    try:
        messages = await _build_initial_messages(db, session, current_user_message)
    except Exception as e:
        yield _sse("error", {"error": f"构建上下文失败：{e}"})
        yield _sse("done", {"ok": False})
        return

    asked_user = False  # 一旦 ask_user，loop 提前退出

    # 每个 session 的第一轮拉一次合并 schemas（base 4 + MCP bridge 注入的 N 个）
    # 这是 lazy 设计 — backend 启动时 MCP 可能还没 ready，所以放在 turn loop 外的第一次调用
    tool_schemas = await get_all_tool_schemas()

    for turn in range(MAX_TURNS):
        if abort_event.is_set():
            yield _sse("aborted", {"turn": turn})
            yield _sse("done", {"ok": False, "aborted": True})
            return

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

        try:
            async for chunk in _call_llm_stream(cfg, messages, tool_schemas, abort_event):
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
            if assistant_msg is None:
                # 流被外部 abort 了
                yield _sse("aborted", {"turn": turn})
                yield _sse("done", {"ok": False, "aborted": True})
                return
        except httpx.HTTPStatusError as e:
            # 流式 response 必须 aread 才能拿 .text；老代码直接 .text 会被
            # httpx 抛 ResponseNotRead 把真错盖住（2026-05-14 修）
            try:
                await e.response.aread()
                detail = e.response.text[:300]
            except Exception:
                detail = "(响应体读取失败)"
            yield _sse("error", {"error": f"LLM 调用失败 {e.response.status_code}: {detail}"})
            yield _sse("done", {"ok": False})
            return
        except Exception as e:
            yield _sse("error", {"error": f"LLM 调用失败：{e}"})
            yield _sse("done", {"ok": False})
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
            if content:
                # 持久化 assistant message
                asst_db = AIChatMessage(
                    session_id=session.id,
                    role="assistant",
                    content=content,
                )
                db.add(asst_db)
                await db.commit()
                await db.refresh(asst_db)
                yield _sse("assistant_message", {
                    "id": asst_db.id,
                    "session_id": asst_db.session_id,
                    "role": "assistant",
                    "content": content,
                    "created_at": asst_db.created_at.isoformat(),
                })
            yield _sse("done", {"ok": True})
            return

        # 有工具调用：每个执行一遍
        # 注：tool 之前的 content 已经通过 assistant_delta 流式推过了，
        # 前端会在 tool_call_start 时把 streaming buffer 锁定为一段"思考"
        if content:
            yield _sse("assistant_thinking_lock", {"text": content})

        # ── 持久化 assistant 这条 tool_use turn 到 DB（跨轮 history 重建必需）──
        # 把 LLM 返回的 tool_calls 序列化进 extra_meta（以便下次 _build_initial_messages
        # 重建消息时拼回完整的 assistant.tool_calls + role:tool 配对）
        asst_tool_use_db = AIChatMessage(
            session_id=session.id,
            role="assistant",
            content=content or "",
            extra_meta={"tool_calls": tool_calls},
        )
        db.add(asst_tool_use_db)
        await db.commit()
        await db.refresh(asst_tool_use_db)
        asst_message_id = asst_tool_use_db.id

        for tc in tool_calls:
            if abort_event.is_set():
                yield _sse("aborted", {"turn": turn})
                yield _sse("done", {"ok": False, "aborted": True})
                return

            tc_id = tc.get("id", "")
            fn = tc.get("function", {})
            tool_name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:
                args = {}

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
                args_json=args,
                status="running",
                started_at=_start_dt,
            )
            db.add(tc_db)
            await db.commit()
            await db.refresh(tc_db)
            yield _sse("tool_call_start", {
                "id": tc_db.id,
                "tool_name": tool_name,
                "args": args,
                "started_at": _start_dt.isoformat(),
            })

            # 执行
            try:
                result_text = await execute_tool(tool_name, args, session, db)
                tc_db.status = "success"
                tc_db.result_text = result_text
            except Exception as e:
                tc_db.status = "error"
                tc_db.error_message = str(e)
                tc_db.result_text = f"错误：{e}"
                result_text = tc_db.result_text

            tc_db.ended_at = datetime.utcnow()
            tc_db.duration_ms = int((time.monotonic() - _start_mono) * 1000)
            await db.commit()
            await db.refresh(tc_db)

            yield _sse("tool_call_end", {
                "id": tc_db.id,
                "tool_name": tool_name,
                "status": tc_db.status,
                "result_text": result_text[:600] + ("..." if len(result_text) > 600 else ""),
                "duration_ms": tc_db.duration_ms,
            })

            # 特殊：write_artifact 成功 → 单独通知前端刷新右栏
            if tool_name == "write_artifact" and tc_db.status == "success":
                # 拿最新版本
                from sqlalchemy import desc as _desc
                res = await db.execute(
                    select(AIChatArtifact)
                    .where(
                        AIChatArtifact.session_id == session.id,
                        AIChatArtifact.filename == args.get("filename"),
                    )
                    .order_by(_desc(AIChatArtifact.version))
                    .limit(1)
                )
                art = res.scalar_one_or_none()
                if art:
                    yield _sse("artifact_created", {
                        "id": art.id,
                        "filename": art.filename,
                        "format": art.format,
                        "version": art.version,
                        "preview": art.content[:200],
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
                "content": result_text,
            })

        if asked_user:
            # 提了问题就停 loop，等下一轮 user send
            yield _sse("done", {"ok": True, "awaiting_user": True})
            return

    # 超过 MAX_TURNS
    yield _sse("error", {"error": f"达到最大循环次数 {MAX_TURNS}，已停止"})
    yield _sse("done", {"ok": False})
