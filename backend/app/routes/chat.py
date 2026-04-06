import json
import base64
import os
import logging
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, File, Form, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse
import httpx
from app.database import get_db
from app.models import User, Conversation, Message
from app.schemas import ChatRequest
from app.deps import get_auth_context, AuthContext
from app.llm_client import LLMClient
from app.field_types import build_prompt_field_types_compact
from app.routes.llm_configs import build_llm_chat_completions_url
from app.context_compact import ContextCompactor


async def _get_tenant_llm_config(db: AsyncSession, tenant_id: int) -> dict | None:
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


async def _stream_with_tenant_llm(cfg: dict | None, messages: list, max_retries: int = 2):
    """使用租户 LLM 配置流式调用，yield OpenAI 格式 JSON 字符串。网络错误自动重试。"""
    import logging as _logging
    _logger = _logging.getLogger(__name__)

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
    timeout = httpx.Timeout(connect=15.0, read=300.0, write=15.0, pool=15.0)
    _logger.info("LLM call: url=%s model=%s base_url=%s", url, cfg["model"], cfg["base_url"])

    import asyncio
    last_err = None
    for attempt in range(max_retries + 1):
        if attempt > 0:
            await asyncio.sleep(1)
            _logger.info("LLM stream retry %d/%d", attempt, max_retries)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if raw == "[DONE]":
                            break
                        try:
                            yield json.dumps(json.loads(raw), ensure_ascii=False)
                        except Exception:
                            continue
                    return
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as e:
            last_err = e
            _logger.warning("LLM stream attempt %d failed: %r (type=%s)", attempt + 1, e, type(e).__name__)
            continue
        except Exception:
            raise

    if last_err:
        raise last_err

def _inject_current_config_context(system_prompt: str, current_config: dict) -> str:
    """在 system prompt 末尾注入当前应用配置摘要，让 AI 感知已有配置。
    用于增量对话场景：用户在已有应用基础上描述变更。"""
    config = current_config
    # 如果是 { type: "preview", data: {...} } 格式，取 data
    if isinstance(config.get("data"), dict):
        config = config["data"]

    parts = []
    app_name = config.get("appName", "未知应用")
    parts.append(f"**当前应用**: {app_name}")

    roles = config.get("roles", [])
    if roles:
        role_strs = [f"{r.get('name', '')}(`{r.get('code', '')}`)" for r in roles if r.get("code")]
        parts.append(f"**已有角色** ({len(roles)}): {', '.join(role_strs)}")

    dicts = config.get("dicts", [])
    if dicts:
        dict_strs = []
        for d in dicts:
            opts = d.get("options", [])
            opt_names = [o.get("name", "") for o in opts[:5] if o.get("name")]
            opt_str = f"[{','.join(opt_names)}{'...' if len(opts) > 5 else ''}]" if opt_names else ""
            dict_strs.append(f"{d.get('name', '')}(`{d.get('code', '')}`){opt_str}")
        parts.append(f"**已有字典** ({len(dicts)}): {'; '.join(dict_strs)}")

    models = config.get("models", [])
    if models:
        model_strs = []
        for m in models:
            fields = m.get("fields", [])
            field_names = [f.get("name", "") for f in fields[:8] if f.get("name")]
            fstr = f"[{','.join(field_names)}{'...' if len(fields) > 8 else ''}]" if field_names else ""
            model_strs.append(f"{m.get('name', '')}(`{m.get('code', '')}`){fstr}")
        parts.append(f"**已有模型** ({len(models)}): {'; '.join(model_strs)}")

    config_context = "\n".join(parts)

    incremental_instruction = f"""

## 当前应用配置（增量对话模式）

{config_context}

**增量模式规则（必须遵守）**：
1. 用户描述的是对现有应用的**变更**，不是重新创建
2. 输出配置 JSON 时，**必须包含所有已有实体**（未变更的原样保留），在此基础上新增/修改/删除
3. 已有实体的 code **绝不能改变**，必须精确复用
4. 新增的实体使用新的 code，风格与已有编码保持一致
5. 如果用户说"加一个字段"、"新增一个角色"等，在已有配置基础上新增，保留所有已有内容
6. 当用户需求明确时，**直接生成配置 JSON**（不需要反复确认模型编码等已知信息），你已经拥有完整的配置上下文
"""
    return system_prompt + incremental_instruction


router = APIRouter(prefix="/chat", tags=["聊天"])

BUILDER_SYSTEM_PROMPT = """你是 aPaaS Builder AI，得帆云低代码平台的智能搭建助手。你的任务是通过多轮对话帮用户理清应用需求，然后生成结构化的应用配置。

## 平台知识

得帆云 aPaaS 是企业级低代码平台，核心架构：平台 → 租户 → 应用 → 菜单 → 表单 → 数据模型。

**7种菜单页面类型**：表单页面（最常用，自动生成数据模型）、模型页面（复用已有模型）、聚合表单（跨表只读汇总）、分析页面（可视化图表）、外部链接、自开发页面、引用功能菜单。

**表单构建四步流程**：表单设计 → 列表设计 → 流程设计 → 页面设置。

**组件分类**：
- 业务组件：单行/多行输入、数字、日期时间、人员/部门选择、单选/多选/下拉、金额、附件、富文本、地址、定位、超链接、开关等
- 高级组件：单据号（自增编号）、数据选择、数据单选、关联表单、数据统计、他表字段、子表、虚拟字段
- 子表适用于明细行（订单明细、配件清单等），会生成独立的子表数据模型

**数据字典**：用于下拉选择类字段的选项管理，支持应用级和租户级共享。

**权限体系**：
- 功能权限：查看、新增、编辑、删除、导入、导出等操作控制
- 数据权限：控制可见数据范围（本人/本部门/全部等）
- 数据范围类型：SELF(本人)、CURRENT_USER_DEPT(本部门)、CURRENT_USER_DEPT_LOW_LEVEL(本部门及下级)、ALL(全部)

**表结构设计规范**：
- 平台自动维护以下系统字段，**设计表结构时绝对不要添加**：id、创建时间、更新时间、创建人、更新人（以及任何同义变体如 create_time、update_by 等）
- 只设计真正的业务字段

**角色设计规范**：
- "员工"、"全体员工"、"所有员工" 等通用性角色**不需要创建**，平台内置"全体成员"概念，在权限配置中用 role="all" 表达
- "直属上级"、"部门经理"、"上级领导" 等层级关系角色**不需要创建**，平台直接读取组织架构，在审批流程节点中配置即可

**重要限制**：
- 应用编码和菜单编码创建后不可修改
- 修改表单后需重新发布才在前台生效
- code 只能用英文字母、数字和下划线，不能用中文，必须以字母开头，不能是数据库保留字

## 对话流程（三阶段）

### 阶段一：需求分析（当用户给的是模糊业务需求时）
如果用户描述的是业务场景而非详细功能设计（如"做个售后管理系统"、"客户报修后派工程师上门"），你需要先做需求拆解：

1. **识别业务实体**：从业务描述中提取核心对象（如：工单、客户、工程师）
2. **推导字段和字典**：为每个实体推导关键字段及其类型、枚举选项（如：工单状态 = 待派工/维修中/已完成）
3. **推导表间关系**：实体之间如何关联（如：工单关联客户、工单关联工程师）
4. **识别流程**：哪些环节需要审批/流转
5. **判断实现方式**：明确告知用户哪些可以通过标准配置实现、哪些需要自开发（见下方"实现方式判断"）

**输出格式**：用 2-3 轮对话完成拆解，每轮给出你的分析并请用户确认/补充：
```
基于你的描述，我分析出以下核心功能：

**可通过标准配置实现：**
- ✅ 工单管理（表单+审批流程）
- ✅ 客户档案（表单）
- ✅ 工程师信息（表单）

**需要自开发实现：**
- 🔧 工程师绩效统计看板（自开发菜单页面）
- 🔧 地图选址组件（自开发表单组件）

**需要你确认：**
1. 派工方式是手动选人还是需要智能派单？
2. 工程师上门需要拍照记录吗？
3. 还有哪些角色？客服、主管？
```

### 阶段二：需求细化（对话引导）
通过提问理清需求细节：数据模型、字段、角色、字典、权限、审批流程。

### 阶段三：配置生成
需求明确后，生成完整的配置JSON。

## 实现方式判断指南

你必须准确判断每个功能适合哪种实现方式，并在需求分析阶段就告知用户：

**✅ 标准配置可实现（搭建智能体处理）：**
- 基础表单（增删改查 + 列表）
- 数据字典（下拉选项管理）
- 表间关联（数据单选/关联表单）
- 子表明细（订单行、配件清单）
- 审批流程（提交→审批→通过/驳回）
- 基础权限（按角色控制操作和数据范围）
- 单据编号（自动编号）
- 人员/部门选择
- 数据统计字段（求和、计数等简单计算）

**🔧 需要自开发实现（开发智能体处理）：**
- 复杂数据可视化（图表看板、统计报表、趋势分析）
- 地图类功能（地图选点、轨迹展示、区域围栏）
- 复杂业务计算逻辑（智能派单算法、绩效考核公式）
- 对接外部系统（ERP/CRM/钉钉/微信等API集成）
- 自定义UI交互（拖拽排序、甘特图、看板视图）
- 文件处理（批量导入、模板生成、合同签章）
- 实时通知（WebSocket推送、短信/邮件触发）
- 自定义打印模板
- AI能力集成（OCR识别、智能分类、内容审核）

**当同一个功能两种方式都能实现时**，优先推荐标准配置，并说明局限性。

## 重要规则
- 用中文回复，使用markdown格式
- 主动引导用户补充信息（特别是：哪些字段需要枚举选项？哪些表单之间有关联？）
- 模型之间有关联时，使用"数据单选"字段类型并指定ref
- 需要枚举选项的字段，**必须**先在dicts中定义字典，再在字段中用dict引用
- 有明细行的表单（如订单明细），使用"子表"字段类型
- 所有code字段只用英文、数字、下划线，以字母开头
- code必须避免数据库保留字，如name/status/type/order/date/number/code/description/title/content/note/remark/contact/price/total/quantity/company/customer/product/service/region等。建议加业务前缀，如customer_name、order_status
- **【禁止】** 在任何表单的 fields 中出现 id、创建时间、更新时间、创建人、更新人及其英文变体（create_time、update_time、created_by、updated_by、creator 等），这些由平台自动维护
- **【禁止】** 创建"员工"、"全体员工"等通用性角色，需要表达全员时直接在 permissions 中使用 role="all"
- **【禁止】** 创建"直属上级"、"部门经理"等层级角色，审批流程中的层级关系由平台组织架构自动处理
- **【必须】** 每个表单的 permissions 中，**默认包含一条 role="all" 的全体人员规则**，再叠加其他角色的差异化权限

## 生成配置
当需求明确后，在回复最后附上配置JSON，用 ```json 代码块包裹：

```json
{"type":"preview","data":{"appName":"应用名","roles":[{"code":"role_admin","name":"管理员"}],"dicts":[{"name":"字典名","code":"dict_code","options":[{"name":"选项名","code":"opt_code"}]}],"models":[{"name":"表单名","code":"model_code","fields":[{"name":"字段名","type":"单行输入","icon":"T","required":true,"code":"field_code","dict":"dict_code","ref":{"model":"other_model_code","field":"display_field_code"},"sub_code":"sub_model_code","sub_fields":[{"name":"子字段名","type":"单行输入","icon":"T","code":"sub_field_code"}]}]}],"permissions":[{"form":"表单名","rules":[{"role":"all","op":"all","data":"ALL"}]}]}}
```

## 字段类型（type可选值及icon）
""" + build_prompt_field_types_compact() + """

## 字段属性说明
- code: 字段编码，英文+下划线，如 asset_name
- dict: 下拉单选/多选时，填写dicts中定义的字典code
- ref: 数据单选时，填写 {"model":"关联模型code","field":"要显示的字段code"}
- sub_code: 子表时，填写子表模型code
- sub_fields: 子表内的字段数组（格式同普通字段）

## 权限配置说明
- role: 角色code，"all" 表示全体人员（平台内置，**无需在 roles 中定义**）
- op: 操作类型，"all"=全部操作, "add"=新增, "edit"=编辑, "delete"=删除
- data: 数据范围，"ALL"=全部, "SELF"=本人, "dept"=本部门
- **每个表单权限必须包含全体人员兜底规则**，示例：`{"role":"all","op":"all","data":"ALL"}`，再按需叠加角色限制"""

ASSISTANT_SYSTEM_PROMPT = """你是 aPaaS 辅助开发智能体，帮助用户完善已有应用的配置，包括：创建审批流程、配置业务规则、调整表单组件、配置数据权限。用中文回复，使用markdown格式。"""

DEVELOPER_SYSTEM_PROMPT = """你是 aPaaS 复杂开发智能体，帮助用户进行二次开发，包括：自定义Vue组件、后端接口集成、Groovy脚本编写。用中文回复，使用markdown格式。"""

REQUIREMENTS_SYSTEM_PROMPT = """你是 aPaaS Builder AI — 得帆云低代码平台的**需求分析与应用搭建助手**。

你的能力：通过对话帮用户梳理业务需求，生成结构化的功能设计文档，然后**直接在平台上自动生成可运行的应用**（包括数据模型、表单、流程、权限等）。用户不需要写代码，你能帮他们从需求到上线全搞定。

## 需求收集框架

按以下 6 个维度依次收集，每个维度收集完后归纳确认，再进入下一个：

**① 项目目标** - 系统要解决什么业务问题？主要使用场景？
**② 角色** - 谁会使用？各有什么职责？（平台已内置组织架构，"全部员工/直属上级"不需要单独定义为角色）
**③ 枚举值** - 哪些字段是下拉选项/状态值？（审批状态由平台流程引擎内置，不需定义）
**④ 业务对象** - 管理哪些核心业务单据？每个需要记录什么信息？（每个独立业务对象 = 一张独立的数据表）
**⑤ 流程** - 每个业务对象有哪些操作流程？谁发起、谁审批？
**⑥ 权限** - 每个角色对每张表能做哪些操作？数据范围是什么？

## 交流原则
- 每次只聚焦 1 个维度，按①②③④⑤⑥顺序推进
- 每个维度结束后，用列表归纳确认，确认无误后进入下一个
- 用简洁清晰的中文回复，适当使用 Markdown 格式
- 如果用户一次性给出了较完整的需求描述，可以一次性归纳多个维度然后确认
- 如果用户说"就这些"、"可以了"、"没有了"、"差不多了"或类似确认词，说明用户认为需求已经足够

## 自动生成设计文档

当你判断需求已经足够清晰（至少覆盖了项目目标、业务对象、角色这 3 个核心维度），**自动**输出一份完整的功能设计文档。

输出格式为**结构化 Markdown**，按以下模板输出：

---

## 功能设计文档

### 应用概述
- **应用名称**：xxx
- **应用编码**：XXX（英文大写缩写）
- **描述**：xxx

### 角色清单
| 角色编码 | 角色名称 | 职责描述 |
|---------|---------|---------|
| xxx | xxx | xxx |

### 数据字典
**字典名（dict_code）**：选项1、选项2、选项3
（每个字典一行）

### 数据模型
**表名（table_code）**[主表/子表]
描述：xxx
字段：字段1（类型）、字段2（类型）、...
（每张表一段）

### 业务流程
**流程名**：步骤1 → 步骤2 → 步骤3

### 权限设计
| 数据表 | 角色 | 操作权限 | 数据范围 |
|-------|------|---------|---------|
| xxx | xxx | 新增/编辑/查看 | 仅本人/本部门/全公司 |

---

在输出完整设计文档后，在最后一行加上标记：`<!-- DESIGN_COMPLETE -->`

当用户对设计文档表示认可（如"可以了"、"OK"、"没问题"、"开始生成"、"生成应用"等），你应该回复：
"好的，我现在开始为您生成应用配置。"
并在回复最后加上标记：`<!-- TRIGGER_BUILD -->`

**重要**：
- 只输出人类可读的 Markdown 文档，**绝不要输出 JSON**
- 如果某个维度用户没明确说，根据业务场景合理推断
- 数据模型中不要包含 id、created_at 等系统字段
- 标记 `<!-- DESIGN_COMPLETE -->` 和 `<!-- TRIGGER_BUILD -->` 必须在回复的最后一行
- **你有能力直接生成应用**，不要说"我无法创建应用"之类的话"""

SYSTEM_PROMPTS = {
    "builder": BUILDER_SYSTEM_PROMPT,
    "requirements": REQUIREMENTS_SYSTEM_PROMPT,
    "assistant": ASSISTANT_SYSTEM_PROMPT,
    "developer": DEVELOPER_SYSTEM_PROMPT,
}


@router.post("/send")
async def send_message(
    data: ChatRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    # 验证对话是否存在且属于当前用户（租户隔离）
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == data.conversation_id,
            Conversation.user_id == ctx.user.id,
            Conversation.tenant_id == ctx.tenant_id
        )
    )
    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(status_code=404, detail="对话不存在")

    # 保存用户消息
    user_message = Message(
        conversation_id=conversation.id,
        role="user",
        content=data.message
    )
    db.add(user_message)
    await db.commit()

    # 自动更新对话标题（首条用户消息时）
    if conversation.title in ("新对话", "需求分析", "智能开发") or conversation.title.startswith("新对话"):
        short_title = data.message.strip().replace("\n", " ")[:30]
        if short_title:
            conversation.title = short_title
            await db.commit()

    # 获取历史消息
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at)
    )
    messages = result.scalars().all()

    # 构建LLM消息列表（加入system prompt）
    system_prompt = SYSTEM_PROMPTS.get(conversation.agent_type, BUILDER_SYSTEM_PROMPT)

    # 增量对话：如果前端传入了 current_config，注入到 system prompt 让 AI 感知已有配置
    if data.current_config and conversation.agent_type in ("builder", "requirements"):
        system_prompt = _inject_current_config_context(system_prompt, data.current_config)

    llm_messages = [{"role": "system", "content": system_prompt}]

    # 预取租户 LLM 配置（必须在 compactor 之前）
    llm_cfg = await _get_conversation_llm_config(db, conversation)

    # 智能上下文压缩（借鉴 Claude Code 的分层压缩策略）
    history_msgs = [{"role": msg.role, "content": msg.content} for msg in messages]
    compactor = ContextCompactor(llm_cfg)
    compacted, new_summary = await compactor.compact_with_summary(
        history_msgs,
        mode="chat",
        existing_summary=getattr(conversation, 'context_summary', None),
    )
    # 如果产生了新摘要，异步存到 conversation 记录
    if new_summary and new_summary != getattr(conversation, 'context_summary', None):
        try:
            conversation.context_summary = new_summary
            await db.commit()
        except Exception:
            pass  # context_summary 列可能还未创建
    llm_messages.extend(compacted)

    # 流式响应
    async def event_generator():
        assistant_content = ""
        thinking_sent = False

        try:
            async for chunk in _stream_with_tenant_llm(llm_cfg, llm_messages):
                chunk_data = json.loads(chunk)
                if "choices" in chunk_data and len(chunk_data["choices"]) > 0:
                    delta = chunk_data["choices"][0].get("delta", {})
                    content = delta.get("content") or ""

                    # MiniMax thinking 模式：前面是思考 chunk（content 空），最后才有实际回答
                    # 思考阶段发一个 thinking 提示，让前端显示"思考中..."
                    has_reasoning = bool(delta.get("reasoning_details") or delta.get("reasoning_content"))
                    if has_reasoning and not thinking_sent:
                        thinking_sent = True
                        yield {
                            "event": "thinking",
                            "data": json.dumps({"type": "thinking", "data": "思考中..."})
                        }

                    if content:
                        assistant_content += content
                        yield {
                            "event": "message",
                            "data": json.dumps({"type": "message", "data": content})
                        }

            # 保存助手消息
            assistant_message = Message(
                conversation_id=conversation.id,
                role="assistant",
                content=assistant_content
            )
            db.add(assistant_message)
            await db.commit()

            yield {
                "event": "done",
                "data": json.dumps({"type": "done", "data": "completed"})
            }

        except Exception as e:
            yield {
                "event": "error",
                "data": json.dumps({"type": "error", "data": str(e)})
            }

    return EventSourceResponse(event_generator())


@router.post("/send-with-file")
async def send_message_with_file(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    conversation_id: int = Form(...),
    message: str = Form(default=""),
    current_config: Optional[str] = Form(default=None),
    file: Optional[UploadFile] = File(default=None),
):
    """发送含文件（图片/文档）的消息，图片走 Vision 多模态。"""
    _IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.webp'}
    _MIME_MAP = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
                 '.gif': 'image/gif', '.webp': 'image/webp'}
    logger = logging.getLogger(__name__)

    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == ctx.user.id,
            Conversation.tenant_id == ctx.tenant_id
        )
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="对话不存在")

    # 解析文件
    image_data_url = ""
    file_name = ""
    if file and file.filename:
        file_name = file.filename
        ext = os.path.splitext(file_name)[1].lower()
        if ext in _IMAGE_EXTS:
            raw = await file.read()
            mime = _MIME_MAP.get(ext, 'image/png')
            b64 = base64.b64encode(raw).decode()
            image_data_url = f"data:{mime};base64,{b64}"

    if not message.strip() and not image_data_url:
        raise HTTPException(status_code=400, detail="消息不能为空")

    # 保存用户消息
    db_content = message.strip() or f"已上传图片：{file_name}"
    user_message = Message(conversation_id=conversation.id, role="user", content=db_content)
    db.add(user_message)
    await db.commit()

    # 更新标题
    if conversation.title in ("新对话", "需求分析", "智能开发") or conversation.title.startswith("新对话"):
        short_title = (message.strip() or file_name).replace("\n", " ")[:30]
        if short_title:
            conversation.title = short_title
            await db.commit()

    # 获取历史消息
    result = await db.execute(
        select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at)
    )
    messages_list = result.scalars().all()

    # 构建 system prompt
    system_prompt = SYSTEM_PROMPTS.get(conversation.agent_type, BUILDER_SYSTEM_PROMPT)
    if current_config:
        try:
            config_dict = json.loads(current_config)
            if conversation.agent_type in ("builder", "requirements"):
                system_prompt = _inject_current_config_context(system_prompt, config_dict)
        except Exception:
            pass

    llm_cfg = await _get_conversation_llm_config(db, conversation)
    llm_messages = [{"role": "system", "content": system_prompt}]

    # 历史消息（压缩）
    history_msgs = [{"role": msg.role, "content": msg.content} for msg in messages_list]
    compactor = ContextCompactor(llm_cfg)
    compacted, new_summary = await compactor.compact_with_summary(
        history_msgs, mode="chat",
        existing_summary=getattr(conversation, 'context_summary', None),
    )
    if new_summary and new_summary != getattr(conversation, 'context_summary', None):
        try:
            conversation.context_summary = new_summary
            await db.commit()
        except Exception:
            pass

    # 替换最后一条消息为多模态内容
    if image_data_url and compacted:
        last_content: list = []
        if message.strip():
            last_content.append({"type": "text", "text": message.strip()})
        last_content.append({"type": "image_url", "image_url": {"url": image_data_url}})
        compacted[-1]["content"] = last_content

    llm_messages.extend(compacted)

    async def event_generator():
        assistant_content = ""
        thinking_sent = False
        try:
            async for chunk in _stream_with_tenant_llm(llm_cfg, llm_messages):
                chunk_data = json.loads(chunk)
                if "choices" in chunk_data and len(chunk_data["choices"]) > 0:
                    delta = chunk_data["choices"][0].get("delta", {})
                    content = delta.get("content") or ""
                    has_reasoning = bool(delta.get("reasoning_details") or delta.get("reasoning_content"))
                    if has_reasoning and not thinking_sent:
                        thinking_sent = True
                        yield {"event": "thinking", "data": json.dumps({"type": "thinking", "data": "思考中..."})}
                    if content:
                        assistant_content += content
                        yield {"event": "message", "data": json.dumps({"type": "message", "data": content})}

            assistant_message = Message(conversation_id=conversation.id, role="assistant", content=assistant_content)
            db.add(assistant_message)
            await db.commit()
            yield {"event": "done", "data": json.dumps({"type": "done", "data": "completed"})}
        except Exception as e:
            yield {"event": "error", "data": json.dumps({"type": "error", "data": str(e)})}

    return EventSourceResponse(event_generator())


@router.post("/generate-config")
async def generate_config_phased(
    data: ChatRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """分阶段生成配置 (SSE)。

    前端在用户需求明确后调用此端点，替代让 LLM 一次性输出完整 JSON。
    分3阶段: 骨架 → 字典 → 模型，每阶段 yield 进度，前端实时更新预览。
    """
    from app.config_assembler import assemble_config_streaming

    # 验证对话
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == data.conversation_id,
            Conversation.user_id == ctx.user.id,
            Conversation.tenant_id == ctx.tenant_id
        )
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="对话不存在")

    # 收集历史上下文（摘要，不是全部消息）
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at)
        .limit(20)
    )
    messages_list = result.scalars().all()
    context = "\n".join(
        f"{'用户' if m.role == 'user' else 'AI'}: {m.content[:500]}"
        for m in messages_list
        if m.role in ("user", "assistant")
    )

    llm_cfg = await _get_conversation_llm_config(db, conversation)

    async def event_generator():
        try:
            complete_config = None
            async for event in assemble_config_streaming(data.message, context, llm_cfg=llm_cfg):
                yield {
                    "event": "progress",
                    "data": json.dumps(event, ensure_ascii=False)
                }
                if event.get("phase") == "complete":
                    complete_config = event.get("data")

            # 保存完整配置为 system 消息，便于历史恢复
            if complete_config:
                config_msg = Message(
                    conversation_id=conversation.id,
                    role="system",
                    content=f"```json\n{json.dumps({'type': 'preview', 'data': complete_config}, ensure_ascii=False)}\n```"
                )
                db.add(config_msg)

                # 保存助手摘要消息
                summary = (
                    f"配置生成完成！共 {len(complete_config.get('models', []))} 个模型、"
                    f"{len(complete_config.get('dicts', []))} 个字典、"
                    f"{len(complete_config.get('roles', []))} 个角色。\n\n"
                    f"右侧预览已更新，你可以：\n"
                    f"1. 点击字典/角色上的编辑按钮直接修改\n"
                    f"2. 告诉我需要调整的内容\n"
                    f"3. 确认无误后点击 **开始生成**"
                )
                assistant_msg = Message(
                    conversation_id=conversation.id,
                    role="assistant",
                    content=summary
                )
                db.add(assistant_msg)
                await db.commit()

            yield {
                "event": "done",
                "data": json.dumps({"type": "done"})
            }
        except Exception as e:
            yield {
                "event": "error",
                "data": json.dumps({"type": "error", "message": str(e)})
            }

    return EventSourceResponse(event_generator())
