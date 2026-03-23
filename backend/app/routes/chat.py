import json
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse
from app.database import get_db
from app.models import User, Conversation, Message
from app.schemas import ChatRequest
from app.deps import get_auth_context, AuthContext
from app.llm_client import LLMClient

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

**重要限制**：
- 应用编码和菜单编码创建后不可修改
- 修改表单后需重新发布才在前台生效
- code 只能用英文字母、数字和下划线，不能用中文，必须以字母开头，不能是数据库保留字

## 对话流程
1. 用户描述想要的应用（或上传设计文档）
2. 你提问理清需求（数据模型、字段、角色、字典、权限）
3. 用户确认后，你生成完整的配置JSON

## 增量修改模式（非常重要）
如果收到"当前应用配置"的system消息，说明右侧预览面板已有完整配置。此时**绝对禁止重新输出完整配置JSON**！

**用户只是确认时**（"确认"、"可以"、"就这样"）：
- 直接回复："配置已就绪！点击右上角的 **开始生成** 按钮即可创建应用。"

**用户要求修改时**（"加个字段"、"补充字典"、"删除XX"）：
- 先用文字说明修改内容
- 然后输出 **patch 指令JSON**（不是完整配置！），格式如下：

```json
{"type":"patch","actions":[
  {"op":"add_dict","value":{"name":"协议类型","code":"agreement_type","options":[{"name":"劳务派遣协议","code":"labor_dispatch"},{"name":"服务协议","code":"service_agreement"}]}},
  {"op":"add_field","model":"客户信息","value":{"name":"邮箱","type":"电子邮箱","icon":"@","code":"customer_email","required":false}},
  {"op":"update_dict","target":"客户类型","value":{"options":[{"name":"VIP","code":"vip"},{"name":"普通","code":"normal"},{"name":"新增选项","code":"new_opt"}]}},
  {"op":"remove_field","model":"客户信息","target":"传真号"},
  {"op":"remove_dict","target":"旧字典名"},
  {"op":"add_model","value":{"name":"新表单","code":"new_form","fields":[...]}},
  {"op":"remove_model","target":"要删除的表单名"},
  {"op":"add_role","value":{"name":"审批员","code":"role_approver"}},
  {"op":"update_field","model":"客户信息","target":"联系电话","value":{"type":"手机号码","icon":"P"}},
  {"op":"add_workflow","value":{"name":"请假审批流程","form":"请假申请","nodes":[{"name":"发起申请","role":"","type":"start"},{"name":"部门经理审批","role":"dept_manager","type":"approve"},{"name":"结束","role":"","type":"end"}]}},
  {"op":"remove_workflow","target":"旧流程名"}
]}
```

**patch操作说明**：
- `add_dict`: 新增字典，value 是完整字典对象
- `update_dict`: 修改字典，target 是字典名，value 中只需包含要改的属性（如 options）
- `remove_dict`: 删除字典，target 是字典名
- `add_field`: 给模型加字段，model 是模型名，value 是字段对象
- `update_field`: 修改字段，model+target 定位，value 是要改的属性
- `remove_field`: 删除字段，model+target 定位
- `add_model`: 新增模型，value 是完整模型对象
- `remove_model`: 删除模型，target 是模型名
- `add_role`/`remove_role`: 角色操作
- `add_workflow`: 新增审批流程，value 包含 name/form/nodes
- `update_workflow`: 修改流程，target 是流程名
- `remove_workflow`: 删除流程，target 是流程名

**关键**：只输出变更部分的 patch，不要输出完整配置！配置可能有几十个表单和字典，重新输出会浪费大量资源。

## 重要规则
- 用中文回复，使用markdown格式
- 主动引导用户补充信息（特别是：哪些字段需要枚举选项？哪些表单之间有关联？）
- 有当前配置时，必须用 patch 格式；没有当前配置时，用完整的 preview 格式
- 模型之间有关联时，使用"数据单选"字段类型并指定ref
- 需要枚举选项的字段，**必须**先在dicts中定义字典，再在字段中用dict引用
- 有明细行的表单（如订单明细），使用"子表"字段类型
- 所有code字段只用英文、数字、下划线，以字母开头
- code必须避免数据库保留字，如name/status/type/order/date/number/code/description/title/content/note/remark/contact/price/total/quantity/company/customer/product/service/region等。建议加业务前缀，如customer_name、order_status

## 生成配置
当需求明确后，在回复最后附上配置JSON，用 ```json 代码块包裹：

```json
{"type":"preview","data":{"appName":"应用名","roles":[{"code":"role_admin","name":"管理员"}],"dicts":[{"name":"字典名","code":"dict_code","options":[{"name":"选项名","code":"opt_code"}]}],"models":[{"name":"表单名","code":"model_code","fields":[{"name":"字段名","type":"单行输入","icon":"T","required":true,"code":"field_code","dict":"dict_code","ref":{"model":"other_model_code","field":"display_field_code"},"sub_code":"sub_model_code","sub_fields":[{"name":"子字段名","type":"单行输入","icon":"T","code":"sub_field_code"}]}]}],"permissions":[{"form":"表单名","rules":[{"role":"all","op":"all","data":"ALL"}]}]}}
```

## 字段类型（type可选值及icon）
单据号=#, 单行输入=T, 多行输入=¶, 手机号码=P, 电子邮箱=@, 下拉单选=V, 下拉多选=M, 数据单选=L, 日期时间=D, 金额=$, 数字=N, 附件上传=F, 开关=S, 人员选择=U, 地理位置=G, 子表=Z

## 字段属性说明
- code: 字段编码，英文+下划线，如 asset_name
- dict: 下拉单选/多选时，填写dicts中定义的字典code
- ref: 数据单选时，填写 {"model":"关联模型code","field":"要显示的字段code"}
- sub_code: 子表时，填写子表模型code
- sub_fields: 子表内的字段数组（格式同普通字段）

## 权限配置说明
- role: 角色code，"all"表示全部人员
- op: 操作类型，"all"=全部操作, "add"=新增, "edit"=编辑, "delete"=删除
- data: 数据范围，"ALL"=全部, "SELF"=本人, "dept"=本部门"""

ASSISTANT_SYSTEM_PROMPT = """你是 aPaaS 辅助开发智能体，帮助用户完善已有应用的配置，包括：创建审批流程、配置业务规则、调整表单组件、配置数据权限。用中文回复，使用markdown格式。"""

DEVELOPER_SYSTEM_PROMPT = """你是 aPaaS 复杂开发智能体，帮助用户进行二次开发，包括：自定义Vue组件、后端接口集成、Groovy脚本编写。用中文回复，使用markdown格式。"""

SYSTEM_PROMPTS = {
    "builder": BUILDER_SYSTEM_PROMPT,
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

    # 获取历史消息
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at)
    )
    messages = result.scalars().all()

    # 构建LLM消息列表（加入system prompt）
    system_prompt = SYSTEM_PROMPTS.get(conversation.agent_type, BUILDER_SYSTEM_PROMPT)
    llm_messages = [{"role": "system", "content": system_prompt}]

    # 注入当前配置摘要（增量修改模式）
    # 注意：不传完整 JSON（太大会导致 LLM 全量复制），只传摘要
    if data.current_config:
        cfg = data.current_config
        models_info = []
        for m in cfg.get("models", []):
            fields = [f.get("name", "") for f in m.get("fields", [])]
            models_info.append(f"  - {m.get('name')}({m.get('code','')}): {', '.join(fields)}")
        dicts_info = []
        for d in cfg.get("dicts", []):
            opts = [o.get("name", "") if isinstance(o, dict) else str(o) for o in d.get("options", [])]
            opts_str = ", ".join(opts) if opts else "⚠️空"
            dicts_info.append(f"  - {d.get('name')}({d.get('code','')}): {opts_str}")
        roles_info = [f"{r.get('name')}({r.get('code','')})" for r in cfg.get("roles", [])]

        summary = f"⚠️ 增量修改模式 — 当前配置已有 {len(cfg.get('models',[]))} 个模型、{len(cfg.get('dicts',[]))} 个字典。\n"
        summary += f"应用名: {cfg.get('appName','')}\n"
        summary += f"角色: {', '.join(roles_info) if roles_info else '无'}\n"
        summary += f"模型:\n" + "\n".join(models_info) + "\n" if models_info else ""
        summary += f"字典:\n" + "\n".join(dicts_info) + "\n" if dicts_info else ""
        summary += "\n请用 patch 格式输出变更，禁止输出完整配置JSON！"

        llm_messages.append({
            "role": "system",
            "content": summary
        })

    # 截断历史消息：只保留最近的消息，总字符数不超过 30000
    history_msgs = [{"role": msg.role, "content": msg.content} for msg in messages]
    truncated = []
    total_chars = 0
    for msg in reversed(history_msgs):
        msg_len = len(msg["content"] or "")
        if total_chars + msg_len > 30000 and truncated:
            break
        truncated.insert(0, msg)
        total_chars += msg_len
    llm_messages.extend(truncated)

    # 流式响应
    async def event_generator():
        llm_client = LLMClient()
        assistant_content = ""
        thinking_sent = False

        try:
            async for chunk in llm_client.chat_completion_stream(llm_messages):
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

    async def event_generator():
        try:
            complete_config = None
            async for event in assemble_config_streaming(data.message, context):
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
