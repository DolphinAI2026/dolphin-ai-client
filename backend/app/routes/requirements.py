"""需求分析路由 — 多轮对话式需求澄清 + 结构化功能设计文档生成"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import tempfile
from typing import Annotated, Optional, Any

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

import httpx
from app.database import get_db
from app.deps import get_auth_context, AuthContext
from app.llm_client import LLMClient
from app.models import Conversation, Message
from app.routes.llm_configs import build_llm_chat_completions_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/requirements", tags=["需求分析"])

# ─── System Prompts ───────────────────────────────────────────────────────────

REQUIREMENTS_CHAT_PROMPT = """你是一位经验丰富的产品分析师，负责通过对话帮用户把业务需求梳理清楚，最终生成结构化的功能设计文档。

## 需求收集框架

按以下 6 个维度依次收集，每个维度收集完后归纳确认，再进入下一个：

**① 项目目标**
- 这个系统要解决什么业务问题？
- 主要使用场景和预期效果是什么？

**② 角色**
- 谁会使用这个系统？各有什么不同的职责？
- 【注意】平台已内置组织架构，"全部员工/直属上级"不需要单独定义为角色——只需识别有独立权限配置差异的业务角色（如：HR管理员、财务专员、审批专员、系统管理员等）。当用户说"员工都能提交"时，记录为"全员可操作，数据范围=本人"，不创建员工角色。

**③ 枚举值**
- 系统中哪些字段是下拉选项/状态值？（如：假期类型、申请状态、费用类别等）
- 每个枚举有哪些选项值？
- 【注意】审批状态（待审批/已通过/已拒绝）由平台流程引擎内置，不需要用户定义。

**④ 业务对象**
- 系统要管理哪些核心业务单据或实体？（如：请假申请、报销单、合同、商品等）
- 每个业务对象需要记录哪些关键信息？
- 【关键】每个独立的业务对象 = 一张独立的数据表，绝对不能合并。用户说了几个业务对象，就有几张主表。

**⑤ 流程**
- 每个业务对象有哪些操作流程？（提交→审批→归档？还是直接新增查看？）
- 涉及哪些状态流转？由谁发起、谁审批？
- 流程信息用于推断字段（如：申请日期、审批人、审批意见等）和权限操作（新增/审批/查看等）。

**⑥ 权限对象**
- 每个角色对每张业务对象表能做哪些操作？（新增、编辑、删除、审批、查看等）
- 数据范围是什么？（只能看自己的/本部门的/全公司的）

---

## 文件处理规则（重要）
当用户上传了需求文档（SOW、PRD、需求说明书等），**立即主动从文档中提取**6个维度的信息，而不是重新询问文档中已有的内容：
1. 通读文档全文，按①～⑥维度逐项归纳已知信息
2. 用结构化列表呈现提取结果，格式如：
   - **① 项目目标**：xxx
   - **② 角色**：xxx（已识别 N 个）
   - **③ 枚举值**：xxx
   - **④ 业务对象（表）**：列出每个业务对象名称（这是最关键的，有几个对象就有几张表）
   - **⑤ 流程**：xxx
   - **⑥ 权限**：xxx
3. 提取后询问："以上信息是否准确？是否有需要补充或修改的？"
4. 用户确认后告知可以生成文档

**绝不要**在上传文档后还反问"请描述一下您的应用目标"——答案在文档里，直接读出来。

## 交流原则
- 有文件时：主动提取、确认、补充，而不是从零问起
- 无文件时：每次只聚焦 1 个维度，按①②③④⑤⑥顺序推进，不要一次性问太多
- 每个维度结束后，用列表形式归纳用户确认的内容，确认无误后进入下一个维度
- 用简洁清晰的中文回复，可以适当使用 Markdown 格式
- 6 个维度全部收集完毕后，告知用户："需求已经比较清晰了，您可以点击【生成设计文档】按钮，我将整理成结构化的功能设计文档。"

**注意：** 你只负责需求澄清，不要在对话中直接生成配置 JSON 或代码。"""

GENERATE_DOC_PROMPT = """请根据上面的对话内容，按照以下6个需求维度提取信息，整理成结构化的功能设计文档。

## 提取框架（对话内容 → JSON 字段的映射关系）

| 需求维度 | 对应 JSON 字段 | 提取要点 |
|---------|--------------|---------|
| ① 项目目标 | app_info | 应用名称、编码、一句话描述业务目标 |
| ② 角色 | roles | 有独立权限差异的业务角色（排除员工/直属上级） |
| ③ 枚举值 | data_dictionary | 每类下拉/状态选项 = 一个字典，排除平台内置的审批状态 |
| ④ 业务对象 | tables | 每个业务对象 = 一张独立主表，字段来自对象属性+流程推断 |
| ⑤ 流程 | flows + tables.fields | 每个有流程的业务对象生成一条流程记录；流程也推断字段和可用操作 |
| 功能模块 | modules | 按业务模块归类功能点，标注可操作角色，体现系统能做什么 |
| ⑥ 权限对象 | role_table_mapping | 每个角色对每张主表的操作权限和数据范围 |

---

必须输出严格的 JSON，不包含任何 Markdown 代码块标记、解释性文字或注释。直接输出 JSON 对象：

{
  "app_info": {
    "code": "应用编码（英文大写缩写，如 OMS、CRM、ERP，若未明确则根据业务域推断）",
    "name": "应用名称（中文）",
    "description": "应用简要描述（1-2句话，体现项目目标）"
  },
  "roles": [
    {
      "role_code": "角色编码（英文小写，如 hr_manager、dept_manager、finance_specialist）",
      "role_name": "角色名称（中文）",
      "description": "角色职责描述"
    }
  ],
  "data_dictionary": [
    {
      "dict_code": "字典编码（英文下划线，如 leave_type、expense_category）",
      "dict_name": "字典名称（中文，如 假期类型、费用类别）",
      "items": [
        {
          "item_code": "枚举值编码（英文大写，如 ANNUAL、SICK）",
          "item_name": "枚举值名称（中文，如 年假、病假）"
        }
      ]
    }
  ],
  "tables": [
    {
      "table_code": "表名（英文下划线，以 t_ 开头，如 t_leave_application）",
      "table_name": "表中文名称（如 请假申请）",
      "table_type": "主表 或 子表（二选一）",
      "parent_table": "父表 table_code（子表填写，主表填空字符串）",
      "description": "表用途描述",
      "fields": [
        {
          "field_code": "字段名（英文下划线）",
          "field_name": "字段中文名",
          "data_type": "VARCHAR/BIGINT/INT/DECIMAL/DATE/DATETIME/TINYINT/TEXT/BOOLEAN",
          "length": "长度（无则填空字符串）",
          "is_pk": false,
          "is_fk": false,
          "nullable": true,
          "default_value": "",
          "description": "字段描述"
        }
      ]
    }
  ],
  "modules": [
    {
      "module_name": "模块名称（中文，如 请假管理、加班管理、年假管理）",
      "module_code": "模块编码（英文下划线，如 leave_mgmt）",
      "description": "模块简要说明，1句话",
      "features": [
        {
          "name": "功能点名称（如 提交请假申请、查看申请状态、审批请假）",
          "description": "功能描述，说明做什么、达到什么效果",
          "roles": ["可操作此功能的角色名（用中文，如 全部员工、部门经理、HR专员）"]
        }
      ]
    }
  ],
  "flows": [
    {
      "flow_name": "流程名称（如 请假审批流程、加班申请流程）",
      "flow_code": "流程编码（英文下划线，如 leave_approval_flow）",
      "description": "流程整体说明",
      "steps": [
        {
          "step": 1,
          "action": "步骤动作（如 员工填写并提交申请）",
          "role": "执行该步骤的角色（用中文，如 全部员工、直属上级、HR专员）",
          "status": "该步骤后的状态（如 待审批、审批通过、已归档）"
        }
      ]
    }
  ],
  "role_table_mapping": [
    {
      "table_code": "主表表名",
      "table_name": "主表中文名",
      "permissions": [
        {
          "role_code": "角色编码",
          "role_name": "角色名称",
          "operations": ["从固定列表选择：暂存、新增、导入、复制新建、批量删除、批量同意、批量拒绝、查看、编辑、删除、查看审批历史、打印、日志、评论、导出"],
          "data_scope": "none/self/dept/all/custom（none=无权限、self=仅本人、dept=本部门、all=全公司、custom=自定义）"
        }
      ]
    }
  ]
}

---

## 生成规则

### 【角色 roles】
- 只列有独立权限配置差异的业务角色
- 【严格禁止】泛化用户角色：员工、普通员工、全部员工、employee、staff、user、all_user（由平台组织架构管理）
- 【严格禁止】层级关系角色：直属上级、上级领导、leader、supervisor（由平台审批流程处理）
- 【严格禁止】把"审批人/approver"单独列为角色——审批是流程动作，应识别出实际承担审批职责的具体岗位（如 dept_manager 部门经理、hr_specialist HR专员），用该岗位角色命名；示例 role_code 中禁止出现 approver
- 这几类的权限通过 data_scope 和流程配置体现，不单独创建角色

### 【枚举值 data_dictionary】
- 每类下拉选项 = 一个字典，items 列出所有枚举值
- 【严格禁止】审批相关字典（平台内置）：approval_status、audit_status、process_status 等
- 从对话中的③枚举值维度提取，同时检查④业务对象的字段中是否还有遗漏的枚举

### 【数据表 tables — 最关键，必须完整提取】

**★ 第一步：扫描文档中所有业务实体，按以下五类逐一识别**

| 类别 | 说明 | 常见示例 |
|-----|------|---------|
| ① 申请/单据类 | 员工需要提交并经过审批的各种申请，每种独立建表 | 请假申请、加班申请、补卡申请、年假延期申请 |
| ② 配置/策略类 | 管理员可维护的规则、政策、参数，每类独立建表 | 假期政策配置、节假日设置、假期规则配置 |
| ③ 余额/台账类 | 追踪员工某类指标的额度或余量，每类独立建表 | 年假余额、加班余额、调休余额 |
| ④ 记录/归档类 | 业务完成后的结果记录，区别于"申请过程" | 考勤打卡记录、假期消耗记录 |
| ⑤ 扩展档案类 | 员工属性扩展或多对多关系表 | 员工假期档案、审批委托记录 |

**★ 第二步：每个识别到的业务实体 = 一张独立主表，绝对禁止合并**
- 禁止把请假/加班/补卡/调休合并成"一张申请表+类型字段"
- 禁止把政策/规则合并成"一张配置表+配置类型字段"
- 如果文档提到"X申请"和"Y申请"，两者各建一张表

**★ 第三步：每张表字段来源（综合三路）**
- 来自业务对象属性：该对象本身需要记录的信息（名称、金额、日期范围、备注等）
- 来自枚举字段：凡用到 data_dictionary 中字典的字段（如 leave_type → VARCHAR，存储枚举 code）
- 来自流程推断：有审批流程的表需要推断：申请日期(apply_date)、申请原因(reason)、附件说明(attachment_desc)等
- 来自关联关系：子表需要父表外键字段（is_fk=true）
- 【禁止】通用字段（平台自动管理）：id、create_time、update_time、create_by、update_by、deleted、approval_status

**★ 字段数量要求：每张表至少 6 个业务字段**

**★ 如果对话中包含 [上传文件：...] 的文件内容，必须扫描文件全文，将所有提及的业务实体（不论对话中是否明确确认）全部识别为表；文件内容中的表格、功能列表、业务流程描述都是提取依据**

### 【权限矩阵 role_table_mapping】
- 只含主表，不含子表
- 每张主表的 permissions 数组，第一条必须是"全部员工"条目：`{"role_code":"all_employee","role_name":"全部员工","operations":[...],"data_scope":"self"}`，表示所有员工对该表的默认权限（通常是新增+暂存+查看自己的数据）
- 之后再列各业务角色的权限条目
- operations 根据⑤流程和⑥权限对象推断：有审批流程的表包含"批量同意/批量拒绝/查看审批历史"
- data_scope 推断：全部员工→self，经办人/申请人→self，部门管理者→dept，HR/管理员/全局角色→all

### 【功能模块 modules】
- 按业务域划分模块，每个主表通常对应1个模块（如"请假申请表" → "请假管理"模块）
- 每个模块的 features 列出该模块下所有功能点（增/删/改/查/审批/统计/导出等）
- roles 字段用中文角色名，全员可用时填"全部员工"，需要特定角色时填对应角色名
- 功能模块数量 = 主表数量（每张主表 ≥ 3 个功能点），另可有跨表的统计/报表模块

### 【业务流程 flows】
- 凡有审批/多步骤操作的业务对象，必须生成对应流程
- 每条流程 steps 按实际操作顺序排列，step 从 1 开始递增
- role 用中文描述（全部员工/直属上级/部门经理/HR专员等），status 描述该步完成后系统状态
- 纯 CRUD 无审批的表不需要生成流程

### 【其他规则】
- is_pk、is_fk、nullable 必须是布尔值 true 或 false（不能是字符串）
- role_table_mapping 的 operations 只能从固定列表中选择，不能自创操作名"""

# ─── Tenant LLM Helpers ──────────────────────────────────────────────────────

async def _get_tenant_llm_config(db: AsyncSession, tenant_id: int) -> dict | None:
    """查询租户默认 LLM 配置，返回解密后的 dict"""
    from app.harness.llm_resolver import resolve_llm_config
    resolved = await resolve_llm_config(db, tenant_id, purpose="builder")
    if not resolved:
        return None
    return {"api_key": resolved.api_key, "base_url": resolved.base_url, "model": resolved.model, "max_tokens": resolved.max_tokens}


async def _get_conversation_llm_config(db: AsyncSession, conversation: Conversation) -> dict | None:
    from app.harness.llm_resolver import resolve_llm_config
    resolved = await resolve_llm_config(db, conversation.tenant_id, purpose="builder", selected_config_id=conversation.selected_llm_config_id)
    if not resolved:
        return None
    return {"api_key": resolved.api_key, "base_url": resolved.base_url, "model": resolved.model, "max_tokens": resolved.max_tokens}


async def _stream_with_config(cfg: dict | None, messages: list, max_retries: int = 2):
    """使用 cfg 指定的 OpenAI 兼容接口流式调用；cfg 为 None 时 fallback 到 LLMClient。支持重试。"""
    if cfg is None:
        raise ValueError("未配置可用的 LLM 模型，请在环境管理 → 模型配置中添加并启用模型")

    payload = {
        "model": cfg["model"],
        "messages": messages,
        "max_tokens": cfg["max_tokens"],
        "stream": True,
    }
    url = build_llm_chat_completions_url(cfg["base_url"])
    headers = {"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"}
    stream_timeout = httpx.Timeout(connect=15.0, read=300.0, write=15.0, pool=15.0)

    last_err = None
    for attempt in range(max_retries + 1):
        if attempt > 0:
            import asyncio
            await asyncio.sleep(1)
            logger.info("LLM stream retry %d/%d for %s", attempt, max_retries, url)
        try:
            async with httpx.AsyncClient(timeout=stream_timeout) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if raw == "[DONE]":
                            break
                        try:
                            data = json.loads(raw)
                            yield json.dumps(data, ensure_ascii=False)
                        except Exception:
                            continue
                    return  # 成功，不再重试
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as e:
            last_err = e
            logger.warning("LLM stream attempt %d failed: %s", attempt + 1, e)
            continue
        except Exception:
            raise  # 非网络错误直接抛出

    # 所有重试都失败
    if last_err:
        raise last_err


async def _complete_with_config(
    cfg: dict | None,
    messages: list[dict[str, Any]],
    *,
    max_tokens: int = 4096,
    temperature: float = 0.0,
) -> str:
    """非流式调用，用于兜底修复 JSON。"""
    if cfg is None:
        raise ValueError("未配置可用的 LLM 模型")

    payload = {
        "model": cfg["model"],
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    timeout = httpx.Timeout(connect=15.0, read=120.0, write=15.0, pool=15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            build_llm_chat_completions_url(cfg["base_url"]),
            headers={
                "Authorization": f"Bearer {cfg['api_key']}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        return ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "")


async def _repair_doc_json(cfg: dict | None, raw_text: str) -> dict:
    """把模型输出的非标准/不完整文本修复成合法文档 JSON。"""
    repair_messages = [
        {
            "role": "system",
            "content": (
                "你是严格的 JSON 修复器。"
                "请把用户提供的文本修复为一个完整、合法的 JSON 对象。"
                "只输出 JSON，不要输出任何解释、Markdown、代码块、<think>。"
                "JSON 必须包含并仅按以下核心结构组织："
                "app_info(object), roles(array), data_dictionary(array), tables(array), role_table_mapping(array)。"
            ),
        },
        {
            "role": "user",
            "content": f"请修复以下内容并输出合法 JSON：\n\n{raw_text[-20000:]}",
        },
    ]
    repaired_text = await _complete_with_config(cfg, repair_messages, max_tokens=6000, temperature=0.0)
    return extract_json(repaired_text)


async def _regenerate_doc_json(cfg: dict | None, base_messages: list[dict[str, Any]]) -> dict:
    """当提取/修复都失败时，强约束再生成一次完整 JSON。"""
    regen_messages = list(base_messages)
    regen_messages.append(
        {
            "role": "user",
            "content": (
                "请忽略之前的输出形式，重新生成一次。"
                "严格只输出一个完整合法 JSON 对象，不能有 <think>、解释、注释、Markdown 代码块。"
                "如果无法确定字段值，给出合理默认值，但必须保证 JSON 结构完整。"
            ),
        }
    )
    regen_text = await _complete_with_config(cfg, regen_messages, max_tokens=8000, temperature=0.0)
    return extract_json(regen_text)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def extract_json(text: str) -> dict:
    """从 AI 响应中提取 JSON 对象"""
    # 去除 markdown 代码块
    text = re.sub(r'^```(?:json)?\s*', '', text.strip(), flags=re.MULTILINE)
    text = re.sub(r'\s*```$', '', text.strip(), flags=re.MULTILINE)
    text = text.strip()

    start = text.find('{')
    if start == -1:
        raise ValueError('响应中未找到 JSON 对象')

    depth = 0
    end = -1
    for i, ch in enumerate(text[start:], start):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end = i
                break

    if end == -1:
        raise ValueError('JSON 对象不完整')

    return json.loads(text[start:end + 1])


def is_valid_doc_result(doc: dict) -> bool:
    """最小结构校验，避免把无效 JSON 误存为 doc_result。"""
    if not isinstance(doc, dict):
        return False
    return (
        isinstance(doc.get("app_info"), dict)
        and isinstance(doc.get("roles"), list)
        and isinstance(doc.get("data_dictionary"), list)
        and isinstance(doc.get("tables"), list)
        and isinstance(doc.get("role_table_mapping"), list)
    )


def _build_fallback_doc_result(messages: list[dict[str, Any]]) -> dict:
    """兜底：当模型持续无法输出合法 JSON 时，返回可编辑的最小结构，保证页面可用。"""
    user_text = "\n".join((m.get("content") or "") for m in messages if m.get("role") == "user")
    m = re.search(r"([^\n，。；]{2,30}系统)", user_text)
    app_name = m.group(1) if m else "业务管理系统"
    app_code = "APP_" + re.sub(r"[^A-Za-z0-9]", "", app_name.upper())[:8]
    if app_code == "APP_":
        app_code = "APP_DEMO"

    table_name = app_name.replace("系统", "") + "申请"
    table_name = table_name if table_name.strip() else "业务申请"

    return {
        "app_info": {
            "code": app_code,
            "name": app_name,
            "description": "自动兜底生成的基础设计文档，请按实际需求补充和调整。"
        },
        "roles": [
            {"role_code": "applicant", "role_name": "申请人", "description": "发起业务申请"},
            {"role_code": "approver", "role_name": "审批人", "description": "审核并审批申请"},
        ],
        "data_dictionary": [],
        "tables": [
            {
                "table_code": "biz_request",
                "table_name": table_name,
                "table_type": "主表",
                "parent_table": "",
                "description": "基础业务申请主表（兜底生成）",
                "fields": [
                    {
                        "field_code": "id",
                        "field_name": "主键ID",
                        "data_type": "自增ID",
                        "length": "20",
                        "is_pk": True,
                        "is_fk": False,
                        "nullable": False,
                        "default_value": "",
                        "description": "主键",
                    },
                    {
                        "field_code": "applicant_name",
                        "field_name": "申请人",
                        "data_type": "单行输入",
                        "length": "100",
                        "is_pk": False,
                        "is_fk": False,
                        "nullable": False,
                        "default_value": "",
                        "description": "申请人姓名",
                    },
                    {
                        "field_code": "apply_date",
                        "field_name": "申请日期",
                        "data_type": "日期",
                        "length": "",
                        "is_pk": False,
                        "is_fk": False,
                        "nullable": False,
                        "default_value": "",
                        "description": "提交申请日期",
                    },
                    {
                        "field_code": "status",
                        "field_name": "状态",
                        "data_type": "单选",
                        "length": "",
                        "is_pk": False,
                        "is_fk": False,
                        "nullable": False,
                        "default_value": "draft",
                        "description": "草稿/待审批/已通过/已拒绝",
                    },
                ],
            }
        ],
        "role_table_mapping": [
            {
                "table_code": "biz_request",
                "table_name": table_name,
                "permissions": [
                    {"role_code": "all_employee", "role_name": "全部员工", "operations": ["新增", "查看"], "data_scope": "self"},
                    {"role_code": "applicant", "role_name": "申请人", "operations": ["新增", "编辑", "查看"], "data_scope": "self"},
                    {"role_code": "approver", "role_name": "审批人", "operations": ["查看", "审批"], "data_scope": "dept"},
                ],
            }
        ],
        "flows": [
            {
                "flow_code": "biz_request_flow",
                "flow_name": "业务申请审批流程",
                "description": "兜底生成的流程，可按实际业务调整",
                "table_code": "biz_request",
                "steps": [
                    {"step": 1, "action": "提交申请", "role": "申请人", "status": "待审批"},
                    {"step": 2, "action": "审批", "role": "审批人", "status": "已通过/已拒绝"},
                ],
            }
        ],
    }


def json_to_markdown(data: dict) -> str:
    """将 5 模块 JSON 转换为 Markdown 格式的功能设计文档"""
    lines = []
    app_info = data.get('app_info', {})
    lines.append(f"# {app_info.get('name', '功能设计文档')}")
    lines.append('')

    # 一、应用信息
    lines.append('## 一、应用信息')
    lines.append('')
    lines.append(f"- **应用编码**：{app_info.get('code', '')}")
    lines.append(f"- **应用名称**：{app_info.get('name', '')}")
    lines.append(f"- **描述**：{app_info.get('description', '')}")
    lines.append('')

    # 二、角色清单
    lines.append('## 二、角色清单')
    lines.append('')
    lines.append('| 角色编码 | 角色名称 | 职责描述 |')
    lines.append('|---------|---------|---------|')
    for role in data.get('roles', []):
        lines.append(f"| {role.get('role_code', '')} | {role.get('role_name', '')} | {role.get('description', '')} |")
    lines.append('')

    # 三、数据字典
    lines.append('## 三、数据字典')
    lines.append('')
    for d in data.get('data_dictionary', []):
        lines.append(f"### {d.get('dict_name', '')}（{d.get('dict_code', '')}）")
        lines.append('')
        lines.append('| 编码 | 名称 |')
        lines.append('|------|------|')
        for item in d.get('items', []):
            lines.append(f"| {item.get('item_code', '')} | {item.get('item_name', '')} |")
        lines.append('')

    # 四、表结构
    lines.append('## 四、表结构')
    lines.append('')
    for table in data.get('tables', []):
        ttype = table.get('table_type', '主表')
        parent = table.get('parent_table', '')
        parent_str = f' → {parent}' if parent else ''
        lines.append(f"### {table.get('table_name', '')}（{table.get('table_code', '')}）【{ttype}{parent_str}】")
        lines.append('')
        desc = table.get('description', '')
        if desc:
            lines.append(f'> {desc}')
            lines.append('')
        lines.append('| 字段编码 | 字段名称 | 数据类型 | 长度 | 主键 | 外键 | 可空 | 默认值 | 描述 |')
        lines.append('|---------|---------|---------|-----|------|------|------|--------|------|')
        for f in table.get('fields', []):
            pk = '✓' if f.get('is_pk') else '-'
            fk = '✓' if f.get('is_fk') else '-'
            nullable = '是' if f.get('nullable', True) else '否'
            lines.append(
                f"| {f.get('field_code', '')} | {f.get('field_name', '')} | {f.get('data_type', '')} "
                f"| {f.get('length', '')} | {pk} | {fk} | {nullable} | {f.get('default_value', '')} | {f.get('description', '')} |"
            )
        lines.append('')

    # 五、角色权限矩阵
    lines.append('## 五、角色权限矩阵')
    lines.append('')
    SCOPE_LABELS = {'none': '无权限', 'self': '仅本人', 'dept': '本部门', 'all': '全公司', 'custom': '自定义'}
    mappings = data.get('role_table_mapping', [])
    roles = data.get('roles', [])
    if mappings and roles:
        for mapping in mappings:
            lines.append(f"### {mapping.get('table_name', mapping.get('table_code', ''))}")
            lines.append('')
            lines.append('| 角色 | 操作权限 | 数据范围 |')
            lines.append('|------|---------|---------|')
            perm_by_role = {}
            for p in mapping.get('permissions', []):
                perm_by_role[p.get('role_code', '')] = p
            for role in roles:
                rc = role.get('role_code', '')
                rn = role.get('role_name', rc)
                p = perm_by_role.get(rc, {})
                ops = '、'.join(p.get('operations', [])) or '—'
                scope_val = p.get('data_scope', 'none')
                scope_lbl = SCOPE_LABELS.get(scope_val, scope_val)
                lines.append(f'| {rn} | {ops} | {scope_lbl} |')
            lines.append('')

    return '\n'.join(lines)


async def parse_uploaded_file(file: UploadFile) -> str:
    """解析上传的文件内容（支持 PDF/DOCX/MD/TXT）"""
    filename = file.filename or ''
    ext = os.path.splitext(filename)[1].lower()

    content = await file.read()

    if ext in ('.md', '.txt', '.markdown'):
        return content.decode('utf-8', errors='ignore')

    # 需要临时文件处理的格式
    suffix = ext or '.tmp'
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        if ext == '.pdf':
            try:
                import pdfplumber
                parts = []
                with pdfplumber.open(tmp_path) as pdf:
                    for page in pdf.pages:
                        t = page.extract_text()
                        if t:
                            parts.append(t)
                return '\n'.join(parts)
            except ImportError:
                return content.decode('utf-8', errors='ignore')

        elif ext in ('.docx', '.doc'):
            try:
                from docx import Document
                doc = Document(tmp_path)
                parts = []
                for para in doc.paragraphs:
                    if para.text.strip():
                        parts.append(para.text.strip())
                for table in doc.tables:
                    for row in table.rows:
                        row_text = ' | '.join(cell.text.strip() for cell in row.cells if cell.text.strip())
                        if row_text:
                            parts.append(row_text)
                return '\n'.join(parts)
            except ImportError:
                return content.decode('utf-8', errors='ignore')
        else:
            return content.decode('utf-8', errors='ignore')
    finally:
        os.unlink(tmp_path)


# ─── Schemas ──────────────────────────────────────────────────────────────────

class ChatMessageRequest(BaseModel):
    message: str


class RequirementsSessionCreateRequest(BaseModel):
    selected_llm_config_id: Optional[int] = None


class ExportMdRequest(BaseModel):
    doc_result: dict


# ─── Routes ──────────────────────────────────────────────────────────────────

@router.post("/sessions")
async def create_session(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    data: Optional[RequirementsSessionCreateRequest] = Body(default=None),
):
    """创建新的需求分析会话"""
    from app.routes.llm_configs import (
        get_active_llm_config_by_id_for_purpose,
        get_default_llm_config_id_for_purpose,
    )

    selected_llm_config_id: Optional[int] = None
    requested_model_id = data.selected_llm_config_id if data else None
    if requested_model_id is not None:
        config = await get_active_llm_config_by_id_for_purpose(
            db,
            ctx.tenant_id,
            requested_model_id,
            "builder",
        )
        if not config:
            raise HTTPException(status_code=400, detail="所选模型不可用")
        selected_llm_config_id = config.id
    else:
        selected_llm_config_id = await get_default_llm_config_id_for_purpose(
            db,
            ctx.tenant_id,
            "builder",
        )

    conv = Conversation(
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        title="新需求分析",
        agent_type="requirements",
        selected_llm_config_id=selected_llm_config_id,
        status="active",
    )
    db.add(conv)
    await db.flush()

    # 添加 AI 开场白
    greeting = Message(
        conversation_id=conv.id,
        role="assistant",
        content="您好！我是您的需求分析助手，将帮助您梳理应用的业务需求。\n\n请简单描述一下您想要搭建的应用是做什么的？解决什么业务问题？"
    )
    db.add(greeting)
    await db.commit()

    return {
        "id": conv.id,
        "title": conv.title,
        "created_at": conv.created_at.isoformat(),
        "updated_at": conv.updated_at.isoformat(),
        "selected_llm_config_id": conv.selected_llm_config_id,
        "doc_result": None,
        "messages": [
            {"id": greeting.id, "role": "assistant", "content": greeting.content,
             "created_at": greeting.created_at.isoformat()}
        ]
    }


@router.get("/sessions")
async def list_sessions(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """列出当前用户的所有需求分析会话"""
    result = await db.execute(
        select(Conversation)
        .where(
            Conversation.user_id == ctx.user.id,
            Conversation.tenant_id == ctx.tenant_id,
            Conversation.agent_type == "requirements"
        )
        .order_by(Conversation.updated_at.desc())
    )
    convs = result.scalars().all()
    return [
        {
            "id": c.id,
            "title": c.title,
            "created_at": c.created_at.isoformat(),
            "updated_at": c.updated_at.isoformat(),
            "selected_llm_config_id": c.selected_llm_config_id,
            "has_doc": c.doc_result is not None,
        }
        for c in convs
    ]


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """获取会话详情（含全部消息和 doc_result）"""
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == session_id,
            Conversation.user_id == ctx.user.id,
            Conversation.tenant_id == ctx.tenant_id,
            Conversation.agent_type == "requirements"
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")

    msgs_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == session_id)
        .order_by(Message.created_at)
    )
    msgs = msgs_result.scalars().all()

    return {
        "id": conv.id,
        "title": conv.title,
        "created_at": conv.created_at.isoformat(),
        "updated_at": conv.updated_at.isoformat(),
        "selected_llm_config_id": conv.selected_llm_config_id,
        "doc_result": conv.doc_result,
        "messages": [
            {"id": m.id, "role": m.role, "content": m.content,
             "created_at": m.created_at.isoformat()}
            for m in msgs
        ]
    }


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """删除会话"""
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == session_id,
            Conversation.user_id == ctx.user.id,
            Conversation.tenant_id == ctx.tenant_id,
            Conversation.agent_type == "requirements"
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 删除消息
    msgs_result = await db.execute(
        select(Message).where(Message.conversation_id == session_id)
    )
    for msg in msgs_result.scalars().all():
        await db.delete(msg)

    await db.delete(conv)
    await db.commit()
    return {"ok": True}


@router.post("/sessions/{session_id}/chat")
async def chat(
    session_id: int,
    data: ChatMessageRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """多轮对话 — SSE 流式响应"""
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == session_id,
            Conversation.user_id == ctx.user.id,
            Conversation.tenant_id == ctx.tenant_id,
            Conversation.agent_type == "requirements"
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 保存用户消息
    user_msg = Message(
        conversation_id=session_id,
        role="user",
        content=data.message
    )
    db.add(user_msg)
    await db.commit()

    # 更新会话标题（首条用户消息）
    if conv.title == "新需求分析":
        title = data.message[:30] + ("..." if len(data.message) > 30 else "")
        conv.title = title
        await db.commit()

    # 获取历史消息
    msgs_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == session_id)
        .order_by(Message.created_at)
    )
    all_msgs = msgs_result.scalars().all()

    # 构建 LLM 消息
    llm_messages = [{"role": "system", "content": REQUIREMENTS_CHAT_PROMPT}]
    # 截断：最多 20000 字符
    history = [{"role": m.role, "content": m.content} for m in all_msgs]
    truncated = []
    total = 0
    for msg in reversed(history):
        length = len(msg["content"] or "")
        if total + length > 20000 and truncated:
            break
        truncated.insert(0, msg)
        total += length
    llm_messages.extend(truncated)

    # 预取租户 LLM 配置（在 db session 有效时）
    llm_cfg = await _get_conversation_llm_config(db, conv)
    logger.info("requirements chat: conv=%s, selected_llm=%s, cfg=%s",
                session_id, conv.selected_llm_config_id,
                {k: v for k, v in (llm_cfg or {}).items() if k != 'api_key'})

    async def event_generator():
        assistant_content = ""
        try:
            async for chunk in _stream_with_config(llm_cfg, llm_messages):
                chunk_data = json.loads(chunk)
                choices = chunk_data.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    text = delta.get("content", "")
                    if text:
                        assistant_content += text
                        yield {"event": "chunk", "data": json.dumps({"content": text}, ensure_ascii=False)}
        except Exception as e:
            import traceback
            logger.error("requirements chat error: %s\n%s", e, traceback.format_exc())
            yield {"event": "error", "data": json.dumps({"message": str(e) or repr(e)}, ensure_ascii=False)}
            return

        # 保存 AI 消息
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as save_db:
            ai_msg = Message(
                conversation_id=session_id,
                role="assistant",
                content=assistant_content
            )
            save_db.add(ai_msg)
            await save_db.commit()

        yield {"event": "done", "data": "{}"}

    return EventSourceResponse(event_generator())


@router.post("/sessions/{session_id}/chat-with-file")
async def chat_with_file(
    session_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    message: str = Form(default=""),
    file: Optional[UploadFile] = File(default=None)
):
    """发送含文件的消息（解析文件内容并附加到消息；图片使用 vision 多模态）"""
    _IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.webp'}
    _MIME_MAP = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
                 '.gif': 'image/gif', '.webp': 'image/webp'}

    result = await db.execute(
        select(Conversation).where(
            Conversation.id == session_id,
            Conversation.user_id == ctx.user.id,
            Conversation.tenant_id == ctx.tenant_id,
            Conversation.agent_type == "requirements"
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 解析文件内容
    file_content = ""
    file_name = ""
    image_data_url = ""   # 仅图片时非空
    if file and file.filename:
        file_name = file.filename
        ext = os.path.splitext(file_name)[1].lower()
        try:
            if ext in _IMAGE_EXTS:
                raw = await file.read()
                mime = _MIME_MAP.get(ext, 'image/png')
                b64 = base64.b64encode(raw).decode()
                image_data_url = f"data:{mime};base64,{b64}"
            else:
                file_content = await parse_uploaded_file(file)
        except Exception as e:
            logger.warning("file parse error: %s", e)

    # 校验消息非空
    if not message.strip() and not file_content and not image_data_url:
        raise HTTPException(status_code=400, detail="消息不能为空")

    # 保存用户消息（含文件内容，供 generate-doc 使用；前端根据格式识别并只展示文件名）
    if file_content:
        # 文字文档：把文件内容完整存入 DB，generate-doc 时 AI 能看到
        db_content = f"[上传文件：{file_name}]\n\n{file_content}"
        if message.strip():
            db_content = f"{message.strip()}\n\n[上传文件：{file_name}]\n\n{file_content}"
    elif image_data_url:
        # 图片只存文件名（图片内容不适合存文本）
        db_content = message.strip() or f"已上传文件：{file_name}"
    else:
        db_content = message.strip() or f"已上传文件：{file_name}"
    user_msg = Message(
        conversation_id=session_id,
        role="user",
        content=db_content
    )
    db.add(user_msg)
    await db.commit()

    # 更新标题
    if conv.title == "新需求分析":
        title = (message.strip() or file_name)[:30]
        conv.title = title
        await db.commit()

    # 获取历史消息
    msgs_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == session_id)
        .order_by(Message.created_at)
    )
    all_msgs = msgs_result.scalars().all()

    # 构建 LLM 消息（最后一条替换为含文件/图片的完整内容）
    # 上传文件时用专项提示词，让 AI 直接分析而非追问
    _sys_prompt = REQUIREMENTS_CHAT_PROMPT
    if file_content:
        _sys_prompt += (
            "\n\n【文件分析模式】用户已上传需求文档，文档完整内容已附在消息末尾。"
            "请直接阅读文档内容，用 2-3 句话确认已读取并简述系统类型和核心功能，"
            "不要提任何问题，不要要求用户补充信息，系统将自动基于文档内容生成功能设计文档。"
        )
    llm_messages = [{"role": "system", "content": _sys_prompt}]
    history = [{"role": m.role, "content": m.content} for m in all_msgs]

    # 构建最后一条用户消息内容
    if image_data_url:
        # 多模态内容块：文字 + 图片
        last_content: list | str = []
        if message.strip():
            last_content.append({"type": "text", "text": message.strip()})
        last_content.append({"type": "image_url", "image_url": {"url": image_data_url}})
    else:
        # 纯文本（文档内容拼接）
        last_content = message.strip()
        if file_content:
            last_content = f"[上传文件：{file_name}]\n\n{file_content}"
            if message.strip():
                last_content = f"{message.strip()}\n\n[上传文件：{file_name}]\n\n{file_content}"

    if history and history[-1]["role"] == "user":
        history[-1]["content"] = last_content

    def _content_len(c) -> int:
        if isinstance(c, str):
            return len(c)
        if isinstance(c, list):
            return sum(len(b.get("text", "")) if b.get("type") == "text" else 5000 for b in c)
        return 0

    truncated = []
    total = 0
    for msg in reversed(history):
        length = _content_len(msg["content"])
        if total + length > 30000 and truncated:
            break
        truncated.insert(0, msg)
        total += length
    llm_messages.extend(truncated)

    llm_cfg = await _get_conversation_llm_config(db, conv)

    async def event_generator():
        assistant_content = ""
        try:
            async for chunk in _stream_with_config(llm_cfg, llm_messages):
                chunk_data = json.loads(chunk)
                choices = chunk_data.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    text = delta.get("content", "")
                    if text:
                        assistant_content += text
                        yield {"event": "chunk", "data": json.dumps({"content": text}, ensure_ascii=False)}
        except Exception as e:
            import traceback
            logger.error("requirements chat-with-file error: %s\n%s", e, traceback.format_exc())
            yield {"event": "error", "data": json.dumps({"message": str(e)}, ensure_ascii=False)}
            return

        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as save_db:
            # 去重：若最后一条已是 assistant 消息则跳过（防止 SSE 重连导致重复存储）
            last_check = await save_db.execute(
                select(Message)
                .where(Message.conversation_id == session_id)
                .order_by(Message.created_at.desc())
                .limit(1)
            )
            last_db_msg = last_check.scalar_one_or_none()
            if not last_db_msg or last_db_msg.role != "assistant":
                ai_msg = Message(
                    conversation_id=session_id,
                    role="assistant",
                    content=assistant_content
                )
                save_db.add(ai_msg)
                await save_db.commit()

        yield {"event": "done", "data": "{}"}

    return EventSourceResponse(event_generator())


@router.post("/sessions/{session_id}/generate-doc")
async def generate_doc(
    session_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """从对话历史生成结构化功能设计文档 — SSE 流式响应"""
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == session_id,
            Conversation.user_id == ctx.user.id,
            Conversation.tenant_id == ctx.tenant_id,
            Conversation.agent_type == "requirements"
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 获取所有对话消息
    msgs_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == session_id)
        .order_by(Message.created_at)
    )
    all_msgs = msgs_result.scalars().all()

    if not all_msgs:
        raise HTTPException(status_code=400, detail="对话内容为空，无法生成文档")

    # 构建 LLM 消息：system + 对话历史（去掉开头连续 assistant 消息）+ 生成指令
    history = [{"role": m.role, "content": m.content} for m in all_msgs]
    # 确保历史第一条是 user（跳过开头的 assistant 开场白）
    while history and history[0]["role"] == "assistant":
        history = history[1:]
    # 找到含文件内容的第一条用户消息，截断时必须保留
    file_msg = next(
        (m for m in history if m["role"] == "user" and "[上传文件：" in (m.get("content") or "")),
        None
    )
    # 截断历史，最多 25000 字符（从最新往前取，始终保留文件消息）
    truncated = []
    total = 0
    for msg in reversed(history):
        length = len(msg["content"] or "")
        if total + length > 25000 and truncated:
            break
        truncated.insert(0, msg)
        total += length
    # 若文件消息因截断被丢弃，强制插入最前面
    if file_msg and file_msg not in truncated:
        truncated.insert(0, file_msg)
    llm_messages = [
        {"role": "system", "content": "你是一位经验丰富的产品分析师，擅长从需求对话中提取结构化信息。请严格按用户指令输出 JSON，不要添加任何解释文字或 Markdown 代码块标记。"}
    ]
    llm_messages.extend(truncated)
    # 附加生成文档的指令
    llm_messages.append({"role": "user", "content": GENERATE_DOC_PROMPT})

    llm_cfg = await _get_conversation_llm_config(db, conv)
    # generate-doc 输出可能较大，但 qwen-max 最多支持 8192 输出 token，强制不超过此值
    if llm_cfg:
        llm_cfg = {**llm_cfg, "max_tokens": 8000}

    async def event_generator():
        full_text = ""
        try:
            async for chunk in _stream_with_config(llm_cfg, llm_messages):
                chunk_data = json.loads(chunk)
                choices = chunk_data.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    text = delta.get("content", "")
                    if text:
                        full_text += text
                        yield {"event": "chunk", "data": json.dumps({"content": text}, ensure_ascii=False)}
        except Exception as e:
            import traceback
            logger.error("generate-doc error: %s\n%s", e, traceback.format_exc())
            yield {"event": "error", "data": json.dumps({"message": str(e)}, ensure_ascii=False)}
            return

        # 提取 JSON
        logger.info("generate-doc full_text length=%d preview=%r", len(full_text), full_text[:200])
        try:
            doc_result = extract_json(full_text)
        except Exception as e:
            logger.warning("json extract failed, trying repair: %s | full_text_len=%d", e, len(full_text))
            try:
                doc_result = await _repair_doc_json(llm_cfg, full_text)
            except Exception as repair_err:
                logger.warning(
                    "json repair failed, trying regenerate: %s | full_text_len=%d",
                    repair_err,
                    len(full_text),
                )
                try:
                    doc_result = await _regenerate_doc_json(llm_cfg, llm_messages)
                except Exception as regen_err:
                    logger.error(
                        "json regenerate failed: %s | full_text_len=%d | first200=%r",
                        regen_err,
                        len(full_text),
                        full_text[:200],
                    )
                    doc_result = _build_fallback_doc_result(truncated)
                    logger.warning("using fallback doc_result for session_id=%s", session_id)

        if not is_valid_doc_result(doc_result):
            logger.error(
                "invalid doc_result schema | keys=%s | full_text_len=%d",
                list(doc_result.keys()) if isinstance(doc_result, dict) else type(doc_result),
                len(full_text),
            )
            doc_result = _build_fallback_doc_result(truncated)
            logger.warning("invalid schema fallback doc_result for session_id=%s", session_id)

        # 写回数据库
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as save_db:
            save_result = await save_db.execute(
                select(Conversation).where(Conversation.id == session_id)
            )
            save_conv = save_result.scalar_one_or_none()
            if save_conv:
                save_conv.doc_result = doc_result
                await save_db.commit()

        yield {"event": "result", "data": json.dumps({"doc_result": doc_result}, ensure_ascii=False)}
        yield {"event": "done", "data": "{}"}

    return EventSourceResponse(event_generator())


GENERATE_DOC_SUMMARY_PROMPT = """根据我们之前的对话，请帮我整理一份完整的功能设计文档摘要。

请按以下格式输出（使用 Markdown）：

## 功能设计文档

### 应用概述
简要描述应用名称、用途和核心目标。

### 角色定义
列出所有角色及其职责。

### 数据字典
列出所有枚举值/下拉选项。

### 数据模型
列出每张表的名称、用途和关键字段。

### 业务流程
描述主要的审批/业务流程。

### 权限设计
简述各角色的数据范围和操作权限。

请简洁清晰地输出，不要输出 JSON，只输出可读的 Markdown 文档。"""


@router.post("/sessions/{session_id}/generate-doc-chat")
async def generate_doc_chat(
    session_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """
    两步流式生成设计文档:
    1. 先流式输出人类可读的设计摘要（作为对话消息）
    2. 再在后台生成结构化 JSON（作为 doc_result 事件）

    SSE 事件:
    - event: content  → 流式文字（给对话气泡显示）
    - event: doc_result → 结构化 JSON（给前端解析为卡片）
    - event: error → 错误信息
    - event: done → 完成
    """
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == session_id,
            Conversation.user_id == ctx.user.id,
            Conversation.tenant_id == ctx.tenant_id,
            Conversation.agent_type == "requirements"
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")

    msgs_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == session_id)
        .order_by(Message.created_at)
    )
    all_msgs = msgs_result.scalars().all()
    if not all_msgs:
        raise HTTPException(status_code=400, detail="对话内容为空")

    history = [{"role": m.role, "content": m.content} for m in all_msgs]
    while history and history[0]["role"] == "assistant":
        history = history[1:]

    # Truncate history to 25000 chars
    file_msg = next(
        (m for m in history if m["role"] == "user" and "[上传文件：" in (m.get("content") or "")),
        None
    )
    truncated = []
    total = 0
    for msg in reversed(history):
        length = len(msg["content"] or "")
        if total + length > 25000 and truncated:
            break
        truncated.insert(0, msg)
        total += length
    if file_msg and file_msg not in truncated:
        truncated.insert(0, file_msg)

    llm_cfg = await _get_conversation_llm_config(db, conv)
    if llm_cfg:
        llm_cfg = {**llm_cfg, "max_tokens": 8000}

    async def event_generator():
        # ── Phase 1: Stream human-readable summary ──
        summary_messages = [
            {"role": "system", "content": "你是一位经验丰富的产品分析师。请根据对话历史整理出结构化的功能设计文档。"}
        ]
        summary_messages.extend(truncated)
        summary_messages.append({"role": "user", "content": GENERATE_DOC_SUMMARY_PROMPT})

        summary_text = ""
        try:
            async for chunk in _stream_with_config(llm_cfg, summary_messages):
                chunk_data = json.loads(chunk)
                choices = chunk_data.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    text = delta.get("content", "")
                    if text:
                        summary_text += text
                        yield {"event": "content", "data": json.dumps({"content": text}, ensure_ascii=False)}
        except Exception as e:
            logger.error("generate-doc-chat summary error: %s", e, exc_info=True)
            yield {"event": "error", "data": json.dumps({"message": str(e)}, ensure_ascii=False)}
            return

        # Save summary as assistant message
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as save_db:
            save_db.add(Message(
                conversation_id=session_id,
                role="assistant",
                content=summary_text,
            ))
            await save_db.commit()

        # Signal that streaming text is done
        yield {"event": "content_done", "data": "{}"}

        # ── Phase 2: Generate structured JSON ──
        json_messages = [
            {"role": "system", "content": "你是一位经验丰富的产品分析师，擅长从需求对话中提取结构化信息。请严格按用户指令输出 JSON，不要添加任何解释文字或 Markdown 代码块标记。"}
        ]
        json_messages.extend(truncated)
        json_messages.append({"role": "user", "content": GENERATE_DOC_PROMPT})

        full_text = ""
        try:
            async for chunk in _stream_with_config(llm_cfg, json_messages):
                chunk_data = json.loads(chunk)
                choices = chunk_data.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    text = delta.get("content", "")
                    if text:
                        full_text += text
        except Exception as e:
            logger.error("generate-doc-chat json error: %s", e, exc_info=True)
            yield {"event": "error", "data": json.dumps({"message": str(e)}, ensure_ascii=False)}
            return

        # Extract and validate JSON
        try:
            doc_result = extract_json(full_text)
        except Exception:
            try:
                doc_result = await _repair_doc_json(llm_cfg, full_text)
            except Exception:
                try:
                    doc_result = await _regenerate_doc_json(llm_cfg, json_messages)
                except Exception:
                    doc_result = _build_fallback_doc_result(truncated)

        if not is_valid_doc_result(doc_result):
            doc_result = _build_fallback_doc_result(truncated)

        # Save to database
        async with AsyncSessionLocal() as save_db:
            save_result = await save_db.execute(
                select(Conversation).where(Conversation.id == session_id)
            )
            save_conv = save_result.scalar_one_or_none()
            if save_conv:
                save_conv.doc_result = doc_result
                await save_db.commit()

        yield {"event": "doc_result", "data": json.dumps({"doc_result": doc_result}, ensure_ascii=False)}
        yield {"event": "done", "data": "{}"}

    return EventSourceResponse(event_generator())


@router.post("/export-md")
async def export_md(
    data: ExportMdRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)]
):
    """将 5 模块 JSON 转换为 Markdown 字符串"""
    try:
        md = json_to_markdown(data.doc_result)
        return {"markdown": md}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Markdown 生成失败: {e}")
