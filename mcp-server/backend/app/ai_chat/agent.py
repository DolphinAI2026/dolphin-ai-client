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
import re
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


_MODULES_QUESTION = "这个耗材管理系统需要哪些模块？"
_MODULES_OPTIONS = [
    "基础版：耗材档案、入库、领用/出库、库存台账",
    "标准版：基础版 + 盘点、库存预警",
    "采购版：标准版 + 采购申请、供应商管理",
    "完整版：标准版 + 报废/归还、统计分析",
]

_APPROVAL_FLOW_QUESTION = "审批/流转怎么设置？"
_APPROVAL_FLOW_OPTIONS = [
    "简化版：无需审批，管理员/仓管直接登记入库和领用",
    "领用审批：全体人员申请 → 发起人所属部门负责人审批 → 仓管出库",
    "仓管确认：入库、领用、盘点都由仓管确认后生效",
    "完整审批：领用审批 + 盘点差异/报废需管理员审批",
]

_PERMISSION_QUESTION = "权限怎么分配？"
_PERMISSION_OPTIONS = [
    "简单全员版：全部人员可提交/查看，管理员维护全部数据",
    "管理员 + 领用人：管理员维护基础资料和库存，领用人只提交领用并看本人数据",
    "仓管 + 全体人员：仓管管理库存，全体人员提交领用并看本人数据",
    "先按标准版：应用管理员、仓管、全体人员分权，部门负责人只作为审批规则",
]


def _is_modules_question(args: dict) -> bool:
    text = str(args.get("question") or "") + " " + " ".join(
        str(x) for x in (args.get("options") if isinstance(args.get("options"), list) else [])
    )
    return bool(re.search(r"模块|功能|包含|需要哪些|档案|入库|领用|库存|盘点|预警|采购|供应商|报废|统计", text))


def _is_approval_flow_question(args: dict) -> bool:
    text = str(args.get("question") or "") + " " + " ".join(
        str(x) for x in (args.get("options") if isinstance(args.get("options"), list) else [])
    )
    return bool(re.search(r"审批|审核|流转|主管|仓管|确认|申请|报废|盘点差异", text))


def _force_approval_flow_question(args: dict) -> dict:
    next_args = dict(args or {})
    next_args["question"] = _APPROVAL_FLOW_QUESTION
    next_args["options"] = _APPROVAL_FLOW_OPTIONS
    return next_args


def _is_permission_question(args: dict) -> bool:
    text = str(args.get("question") or "") + " " + " ".join(
        str(x) for x in (args.get("options") if isinstance(args.get("options"), list) else [])
    )
    return bool(re.search(r"权限|角色|授权|数据范围|谁能|可见|查看|提交|维护|部门|主管|仓管|领用人", text))


def _force_modules_question(args: dict) -> dict:
    next_args = dict(args or {})
    next_args["question"] = _MODULES_QUESTION
    next_args["options"] = _MODULES_OPTIONS
    return next_args


def _force_permission_question(args: dict) -> dict:
    next_args = dict(args or {})
    next_args["question"] = _PERMISSION_QUESTION
    next_args["options"] = _PERMISSION_OPTIONS
    return next_args


def _result_text_mentions_approval(result_text: str | None) -> bool:
    text = result_text or ""
    if text.lstrip().startswith("{"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return _is_approval_flow_question(parsed)
        except Exception:
            pass
    return bool(re.search(r"审批|审核|流转|主管|仓管|确认|申请|报废|盘点差异", text))


def _result_text_mentions_modules(result_text: str | None) -> bool:
    text = result_text or ""
    if text.lstrip().startswith("{"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return _is_modules_question(parsed)
        except Exception:
            pass
    return bool(re.search(r"模块|功能|包含|需要哪些|档案|入库|领用|库存|盘点|预警|采购|供应商|报废|统计", text))


def _result_text_mentions_permission(result_text: str | None) -> bool:
    text = result_text or ""
    if text.lstrip().startswith("{"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return _is_permission_question(parsed)
        except Exception:
            pass
    return bool(re.search(r"权限|角色|授权|数据范围|谁能|可见|查看|提交|维护|部门|主管|仓管|领用人", text))


def _md_has_workflow_section(md_content: str) -> bool:
    return bool(re.search(r"^#{1,3}\s*(?:[一二三四五六七八九十]+[、.]?\s*)?(流程配置|审批流程|业务流程)", md_content or "", re.M))


def _extract_form_names_from_md(md_content: str) -> list[str]:
    names: list[str] = []
    try:
        from app.doc_table_parser import parse_all_tables

        for table in parse_all_tables(md_content or ""):
            if not table:
                continue
            sample = table[0]
            if "表单名称" not in sample:
                continue
            for row in table:
                value = str(row.get("表单名称") or "").strip()
                if value and value not in names:
                    names.append(value)
    except Exception:
        pass
    return names[:8]


def _pick_form_name(form_names: list[str], *keywords: str, fallback: str = "业务表单") -> str:
    for name in form_names:
        if any(keyword and keyword in name for keyword in keywords):
            return name
    return form_names[0] if form_names else fallback


def _build_workflow_rows_from_context(md_content: str, context_text: str) -> list[tuple[str, str, int, str, str, str]]:
    text = f"{context_text}\n{md_content}"
    forms = _extract_form_names_from_md(md_content)
    rows: list[tuple[str, str, int, str, str, str]] = []

    if re.search(r"变更申请|变更.*审批|研发主管审批", text):
        form = _pick_form_name(forms, "变更", "申请", fallback="变更管理")
        rows.extend([
            ("变更审批流程", form, 1, "提交变更申请", "申请人", "待审批"),
            ("变更审批流程", form, 2, "研发主管审批", "研发主管", "已通过/已驳回"),
        ])

    if re.search(r"版本发布|发布.*确认|质量.*研发.*确认|研发.*质量.*确认", text):
        form = _pick_form_name(forms, "版本", "发布", fallback="版本管理")
        rows.extend([
            ("版本发布确认流程", form, 1, "提交版本发布申请", "发布负责人", "待确认"),
            ("版本发布确认流程", form, 2, "质量/研发确认", "质量负责人/研发负责人", "已确认/已退回"),
        ])

    if re.search(r"BOM.*(修改|变更|审批|变更单)|BOM 修改", text, re.I):
        form = _pick_form_name(forms, "BOM", fallback="BOM管理")
        rows.extend([
            ("BOM变更审批流程", form, 1, "提交BOM变更单", "研发人员", "待审批"),
            ("BOM变更审批流程", form, 2, "变更单审批", "研发主管", "已通过/已驳回"),
        ])

    if not rows and re.search(r"审批|审核|流转|确认|变更单", text):
        form = _pick_form_name(forms, "申请", "变更", fallback="业务表单")
        rows.extend([
            ("标准审批流程", form, 1, "提交申请", "申请人", "待审批"),
            ("标准审批流程", form, 2, "审批确认", "审批负责人", "已通过/已驳回"),
        ])

    return rows


def _ensure_workflow_section(md_content: str, context_text: str) -> str:
    """模型漏写流程章时，按已确认的审批/流转上下文补一张标准流程表。"""
    if not md_content or _md_has_workflow_section(md_content):
        return md_content
    rows = _build_workflow_rows_from_context(md_content, context_text)
    if not rows:
        return md_content

    table_lines = [
        "## 六、流程配置",
        "",
        "| 流程名称 | 关联表单 | 步骤 | 动作 | 审批角色 | 状态/结果 |",
        "|---|---|---|---|---|---|",
    ]
    table_lines.extend(
        f"| {flow_name} | {form_name} | {step} | {action} | {role} | {status} |"
        for flow_name, form_name, step, action, role, status in rows
    )
    workflow_section = "\n".join(table_lines) + "\n\n"

    permission_re = re.compile(r"(?m)^#{1,3}\s*(?:六|七|6|7)[、.]?\s*(权限定义|权限配置).*$")
    match = permission_re.search(md_content)
    if match:
        before = md_content[:match.start()].rstrip()
        after = md_content[match.start():]
        after = re.sub(
            r"(?m)^(#{1,3})\s*(?:六|6)[、.]?\s*(权限定义|权限配置)",
            r"\1 七、\2",
            after,
            count=1,
        )
        return f"{before}\n\n{workflow_section}{after.lstrip()}"
    return f"{md_content.rstrip()}\n\n{workflow_section}"


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
- 输出 md 时严格按上面章节顺序；如果用户确认了审批/流转，必须包含「流程配置」章节；缺信息留空单元格即可，不要写"未定义"、"待定"占位文字
- 模型/表单/字段命名：英文 snake_case + 业务前缀（避免 name/status 这种通用字段直接用，要 ncr_status / supplier_name）
- **应用编码（appCode）必须满足**：只允许小写字母 / 数字 / 中划线 `-`，以小写字母开头，长度 ≤ 17 字符（正则 `^[a-z][a-z0-9-]{0,16}$`）。**禁止下划线**。如果业务名很长，要主动缩写（如"电力设备管理系统" → `power-equip-mgmt` 或 `power-equip` 而不是 `power_equipment_management`）
- 数据模型只描述"字段在数据库怎么存"，不要在数据模型表里写字典/关联/组件，那些都在「五、表单定义」里
- 数据单选/数据选择/关联表单字段引用的目标模型，必须先在 ## 四、数据模型 里建出来；没材料支持就不要写这种引用，改用单行输入
- 角色只生成本应用业务权限边界。普通员工、部门主管、直属上级、部门/人员管理都是平台内置组织能力，不要写入角色列表；需要管理员时用带应用语义的编码（如 asset_admin、stock_admin），不要用 sys_admin。
- 表单需要组织归属时添加"所属部门"字段并使用部门选择；审批负责人写"发起人所属部门负责人"这类组织规则。
- 耗材管理这类常见业务，AI 应自动梳理业务主流程，不要让用户选择"入库→库存台账→领用/出库"这种主流程。需要向用户确认的是产品设计决策：**有哪些模块、审批流怎么走、权限怎么搞**。
- 澄清最多 3 轮，且顺序固定：
  1. 模块范围：耗材档案、入库、领用/出库、库存台账、盘点、预警、采购、供应商、报废/归还、统计等要哪些。
  2. 审批/流转：领用是否审批、入库是否仓管确认、盘点差异/报废是否审批。
  3. 权限：应用管理员、仓管等业务角色怎么分权；全体人员、本部门等平台范围怎么看。
- 三项确认后，AI 自己梳理业务主流程并生成完整标准 md，调用 save_design_draft；用户提到审批/流转时必须写「流程配置」章节。

附件信息会在用户消息后附上"[已上传附件]"列表，告诉你有哪些可以读。"""


SYSTEM_PROMPT_UNIFIED = f"""你是 aPaaS 平台的 AI 全栈助手 — 既能产文档（喂给 ai-builder 生成应用），也能写代码（接入 aPaaS 应用做二次开发，或从零搭独立项目）。看用户场景自适应。

## 三种姿态（自己判断走哪个）

### 姿态 A：用户上传了一堆材料（PDF / Word / Excel / 截图 / 现有文档）→ 产文档
1. **第一个动作不是问"你要做什么"**——用户已经用文件告诉你了，立刻**并行** read_attachment 把每份附件都读一遍
2. 数据类材料（xlsx / csv）配合 run_python 抽要点：表头、行数、枚举值分布、关键字段
3. 图片类材料也要 read_attachment 拿到 OCR / 描述
4. **如果用户上传的是 .md 设计文档，并且正文已经包含「应用信息 / 数据模型 / 权限定义」等 Builder 标准章节：不要 write_artifact，不要重写，不要另存“标准设计文档”副本。直接把 read_attachment 返回的原始 content 作为 md_content 调 save_design_draft。**
   - 只有 save_design_draft 明确返回 DOC_MODULE_PARSE_FAILED / MISSING_SECTION，或用户明确说“帮我标准化/重写/整理一版”时，才允许 write_artifact 生成新版。
   - 如果只是轻微规范化（如 `全部人员`、组件别名、通用字段自动修正），让 save_design_draft 的解析/校验处理，并在回复里说明解析层做了哪些修正；不要让 LLM 重写全文。
   - 如果用户上传标准 md 后说“帮我创建应用”，流程是：read_attachment → get_doc_template_spec（可选）→ save_design_draft(md_content=原文) → 等用户 review/确认；跳过 write_artifact。
4. 读完给用户一个**结构化的"我看到了什么"汇总**：识别出 **A 张数据表** / **B 个角色** / **C 个流程** / **D 个枚举字段**
5. **批量**列出 3-5 个澄清问题，每个问题写明"如果选 X / 选 Y 会影响什么"
6. 需求清晰后直接把完整标准 markdown 作为 `md_content` 调用 save_design_draft（应用信息 / 角色 / 字典 / 模型 / 表单 / 流程配置 / 权限）。用户提到审批/流转时必须写「流程配置」章节。这个工具会同时保存右侧 Markdown 设计文档，并返回 HTML 效果预览链接；不要再额外 write_artifact 生成一张重复文档卡。

### 姿态 B：用户没材料只有想法 → 对话挖需求 → 产文档
1. 跟着用户节奏问，每轮最多 1 个关键问题（用 ask_clarifying_question）。耗材管理这类常见系统不要问主流程，AI 自己按行业常识梳理；只确认模块范围、审批/流转、权限分配。
2. 数据类需求也能用 run_python 编程分析
3. 需求清晰后直接调用 save_design_draft 保存完整篇；它会同时生成右侧 Markdown 设计文档和 HTML 效果预览

### 姿态 C：用户要写代码 / 二次开发 / 自开发 → 调代码工具 + 在消息里给代码
**关键约束**：你不仅要把代码写到 workspace（用 write_workspace_files / vibe_write_file），
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

## 🚀 设计文档 → 应用 一气呵成（当前 MCP 工具流）

用户说"创建应用 / 生成应用 / 部署应用 / 帮我做 XXX 系统" 时，**默认一条龙跑到底**，不要每步停下问"要继续吗"：

### 两阶段 + 1 个用户审核点（重要！）

整个流程拆成 **设计文档阶段** + **执行阶段**，中间必须**停下来让用户审核 SPEC**。
这不是冗余 — 用户对 5000+ 字应用蓝图有最后审核权，错了改 doc 比改部署后的 aPaaS 应用便宜 10 倍。

### Phase 1 · 设计 + 自检 (agent 自主跑完不停顿)
1. ask_clarifying_question × 最多 3 轮。
   - 第 1 轮必须只问模块范围：耗材档案、入库、领用/出库、库存台账、盘点、预警、采购、供应商、报废/归还、统计等要哪些。
   - 第 2 轮必须只问审批/流转：领用是否审批、入库是否仓管确认、盘点差异/报废是否审批、由谁处理。
   - 第 3 轮必须只问权限分配：应用管理员、仓管等业务角色怎么分权；全体人员、本部门等平台范围怎么看。
   - 不要问用户"主流程怎么走"，AI 需要自己按模块和审批流梳理业务主流程；更不要问"需求成稿/表单承载/权限分配"这类构建配置流程。
2. 如果是 AI 从零生成设计文档：直接把完整标准 md 作为 `md_content` 调 **save_design_draft(md_content=<完整 md>)**；用户提到审批/流转时必须写「流程配置」章节。
3. 如果用户上传的 .md 已经是标准/准标准设计文档：直接用 read_attachment 的原始 content 调 **save_design_draft(md_content=<原文>)**。
4. save_design_draft 会同时完成：解析/校验/落库、保存右侧 Markdown 设计文档、返回 HTML 效果预览链接。不要为了同一份 Builder 设计文档再调用 write_artifact。
5. **STOP — 给用户 1-3 句总结 + 主动 hint**:
   - "✅ 设计文档已生成 (右侧可查看 Markdown 文档，也可打开效果预览，文档编号=xxx)。**请 review 一下文档和预览效果**，没问题告诉我「开始创建」/「部署」/「OK」，我就创建并发布到 aPaaS；如果要改字段/角色/权限，直接告诉我哪里要改。"

### Phase 2 · 执行 (用户确认 SPEC 后 agent 自主跑完不停顿)
触发条件：用户说 "OK" / "开始创建" / "部署" / "生成应用" / "上线" / 任何明确推进信号
1. 如果上一轮已经拿到 `draft_id`，直接调用 **promote_draft_to_app(draft_id, env=<用户指定的环境别名>)**；如果用户没有显式指定环境，才只传 draft_id 让服务端用 MCP Header 当前环境。
2. 如果上一轮只有右侧 Markdown 文档、还没有 draft_id，则先读取/复用完整 md_content 调 **save_design_draft(md_content)**，再按上条规则调用 **promote_draft_to_app**。
3. `promote_draft_to_app` 内部会创建 AI Builder 应用、推送到 aPaaS、回填 apaas_app_id/admin_url。不要再找 `generate_app_from_doc / deploy_application / publish_application`，这些旧工具当前没有暴露。
4. 给一段 1-3 句 final summary: "✅ 已创建完成 - app_id=N, apaas_app_id=XXX - 点击下方按钮打开应用"

### 💰 Token 节省铁律 (2026-05-21)
**LLM 重写完整 5000+ 字 md 多次是巨大浪费**。正确做法:
- write_artifact 只用于**非 Builder 设计文档产物**，或用户明确要求“只写一份文档/报告/代码给我看，不进入 Builder 预览”。创建/预览 aPaaS 应用时，直接 save_design_draft。
- save_design_draft 必须接收完整 md_content；后续执行只传 draft_id。
- 实在改 md → 重新生成完整 md_content 调 save_design_draft，或按补丁场景用 patch_design_draft。

### 关键反模式（不要做）
- ❌ **为同一份 Builder 设计文档先 write_artifact 再 save_design_draft** — save_design_draft 已经会保存右侧 Markdown 设计文档并返回 HTML 预览，重复工具会让用户看到两张卡。
- ❌ **Phase 1 保存设计文档后立刻 promote_draft_to_app** — 必须先停下让用户 review SPEC！跳过审核 = 错了部署后改回来贵 10 倍。
- ❌ **save_design_draft 之后又 write_artifact 重写同一份 md** — 设计文档已经持久化，Markdown 也已经在右栏，不要重复！用户要改 → patch_design_draft 或重新生成新版设计文档。
- ❌ **Phase 2 内 promote_draft_to_app 完成后停下等用户** — 用户已经确认，意思是要"真能用"，不是"只生成设计文档"。
- ❌ **Phase 2 内每个工具调完都问"要继续吗 / 是否部署"** — 用户在 Phase 1 末已确认，Phase 2 自主推进。
- ❌ **遇到 APP_CODE_CONFLICT 直接停下报错** — 自己改 app_code 后重新保存 draft/创建（不用问用户）

### 例外：什么时候 Phase 1/2 内部也停下问
(a) 需求本身有歧义（如多个候选模型都叫"客户"）
(b) 用户明确说"先停在 draft / 我先看看再决定"
(c) 工具撞 token expired / 权限不足 等需要用户介入的错
(d) 当前租户没有绑定可用默认环境，或绑定了多个 connected 环境且用户明确要求选择目标环境

## 工具速查（55 个，按场景挑用）

文档处理：write_artifact / read_attachment / export_apaas_app_design_doc / get_doc_template_spec
aPaaS 内省：list_apaas_apps_in_env / list_apaas_app_menus / list_apaas_form_views / list_apaas_form_components / list_apaas_app_models / list_apaas_app_dicts
应用生命周期：save_design_draft / get_draft_summary / promote_draft_to_app / patch_design_draft / apply_draft_to_live_app / get_application
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
2. 跟着用户节奏问，每轮最多 1 个关键问题（用 ask_clarifying_question）。耗材管理这类常见系统不要问主流程；按模块范围、审批/流转、权限分配确认，AI 自己梳理业务流程。
3. 数据类材料（xlsx/csv）可用 run_python 编程分析（pandas / openpyxl 都能用）
4. 当需求清晰后，直接调用 save_design_draft 保存完整 markdown 设计文档；它会同步生成右侧文档和 HTML 预览

{_FORMAT_CONSTRAINTS}"""


SYSTEM_PROMPT_COWORK = f"""你是 aPaaS 平台的 AI 协作分析师，帮用户把**一堆杂乱材料**（PDF / Word / Excel / 截图 / 现有文档）整合成可被 Builder 流水线直接解析的标准设计文档。

工作模式（cowork 批量材料整合）—— **跟 chat 模式不一样**：

## 第一步：并行消化所有材料（不等用户引导）
用户进来时往往已经把所有材料一起上传完了。你的第一个动作不是问"你要做什么"，而是：
- 立刻**并行**调 read_attachment 把每一份附件都读一遍（一次回复里可以调多个工具）
- 数据类材料（xlsx/csv）配合 run_python 抽要点：表头、行数、枚举值分布、关键字段
- 图片类材料（架构图 / 截图 / 流程图）也要 read_attachment 拿到 OCR/描述
- 如果读到的附件本身是 `.md` 标准设计文档（含应用信息、数据模型、权限定义等章节），不要进入“整合重写”流程；直接用原文调 save_design_draft。只有用户明确要整理/修订，或 save_design_draft 返回模块解析失败，才 write_artifact 生成新版。

## 第二步：综合摘要 + 批量提问
读完所有材料后，给用户一个**结构化的"我看到了什么"汇总**：
- 我从你的 N 份材料里识别出：**A 张数据表**（列出名字）/ **B 个角色**（列出）/ **C 个流程**（列出）/ **D 个枚举值字段**（列出）
- 我推断的应用类型 = ...
- **同时**列出 3-5 个澄清问题（**批量**问，不是一句一句挤），每个问题写明"如果选 X / 如果选 Y 会影响什么"

## 第三步：用户回答后产出第一版 md
- 如果没有现成标准 md，立刻调 save_design_draft 保存第一版完整标准设计文档（应用信息 / 角色 / 字典 / 模型 / 表单 / 流程配置 / 权限）；用户提到审批/流转时必须写「流程配置」章节
- 如果已经有用户上传的标准 md，跳过 write_artifact，直接 save_design_draft 原文
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
    """优先用 session.selected_llm_config_id；没指定则取平台全局 default。"""
    cfg: Optional[LLMConfig] = None
    if session.selected_llm_config_id:
        res = await db.execute(
            select(LLMConfig).where(
                LLMConfig.id == session.selected_llm_config_id,
                LLMConfig.tenant_id.is_(None),
            )
        )
        cfg = res.scalar_one_or_none()
    if not cfg:
        # fallback：global default
        res = await db.execute(
            select(LLMConfig)
            .where(
                LLMConfig.tenant_id.is_(None),
                LLMConfig.is_default == True,  # noqa: E712
                LLMConfig.status == "active",
            )
            .limit(1)
        )
        cfg = res.scalar_one_or_none()
    if not cfg:
        # 兜底：旧会话模型绑定漂移时，仍允许使用 active 默认模型。
        res = await db.execute(
            select(LLMConfig)
            .where(
                LLMConfig.is_default == True,  # noqa: E712
                LLMConfig.status == "active",
            )
            .order_by(LLMConfig.id.asc())
            .limit(1)
        )
        cfg = res.scalar_one_or_none()
    if not cfg:
        res = await db.execute(
            select(LLMConfig)
            .where(LLMConfig.status == "active")
            .order_by(LLMConfig.id.asc())
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

    attempts = 2
    for attempt in range(attempts):
        received_any = False
        try:
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
                            received_any = True
                            text = delta["content"]
                            accumulated_content += text
                            yield {"type": "content_delta", "text": text}
                        for tc in (delta.get("tool_calls") or []):
                            received_any = True
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
            break
        except (httpx.RemoteProtocolError, httpx.ReadError, httpx.ConnectError) as e:
            if received_any or attempt >= attempts - 1 or abort_event.is_set():
                raise
            logger.warning("LLM stream disconnected before first chunk, retrying once: %s", e)
            await asyncio.sleep(0.8)

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
            # 2026-05-21：LLM 跑完一串工具后可能直接 stop 没输出文本。
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
                    async for chunk in _call_llm_stream(cfg, retry_messages, tool_schemas, abort_event):
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
                        # 忽略 tool_call_delta — system 已经禁止工具调用，万一 LLM 不听话也不执行
                except Exception as e:
                    logger.warning("final-summary retry failed: %s", e)
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
                )
                db.add(asst_db)
                await asyncio.shield(db.commit())
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
        # 2026-05-21 fix: shield 防 cancel — 见上方注释
        await asyncio.shield(db.commit())
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
            if tool_name == "save_design_draft" and isinstance(args, dict):
                original_md = str(args.get("md_content") or "")
                context_text = "\n".join(
                    str(m.get("content") or "")
                    for m in messages
                    if isinstance(m, dict) and m.get("role") in {"user", "assistant"}
                )
                patched_md = _ensure_workflow_section(original_md, context_text)
                if patched_md != original_md:
                    args["md_content"] = patched_md

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
            # 2026-05-21 fix: shield 防 cancel
            await asyncio.shield(db.commit())
            await db.refresh(tc_db)
            yield _sse("tool_call_start", {
                "id": tc_db.id,
                "tool_name": tool_name,
                "args": args,
                "started_at": _start_dt.isoformat(),
            })

            # 执行
            try:
                if tool_name == "ask_clarifying_question":
                    prev_asks_res = await db.execute(
                        select(AIChatToolCall.result_text)
                        .where(
                            AIChatToolCall.session_id == session.id,
                            AIChatToolCall.tool_name == "ask_clarifying_question",
                            AIChatToolCall.status == "success",
                            AIChatToolCall.id != tc_db.id,
                        )
                    )
                    prev_ask_results = list(prev_asks_res.scalars().all())
                    prev_had_modules = any(_result_text_mentions_modules(r) for r in prev_ask_results)
                    prev_had_approval = any(_result_text_mentions_approval(r) for r in prev_ask_results)
                    prev_had_permission = any(_result_text_mentions_permission(r) for r in prev_ask_results)
                    if not prev_had_modules:
                        if not _is_modules_question(args):
                            args = _force_modules_question(args)
                            tc_db.args_json = args
                        result_text = await execute_tool(tool_name, args, session, db)
                    elif not prev_had_approval:
                        if not _is_approval_flow_question(args):
                            args = _force_approval_flow_question(args)
                            tc_db.args_json = args
                        result_text = await execute_tool(tool_name, args, session, db)
                    elif not prev_had_permission:
                        if not _is_permission_question(args):
                            args = _force_permission_question(args)
                            tc_db.args_json = args
                        result_text = await execute_tool(tool_name, args, session, db)
                    else:
                        result_text = json.dumps(
                            {
                                "ok": True,
                                "_special": "continue_without_asking",
                                "message": (
                                    "用户已经回答过模块范围、审批/流转和权限分配。不要继续提问；"
                                    "请基于已确认范围直接生成完整标准设计文档，并写入「流程配置」章节，"
                                    "然后调用 save_design_draft。"
                                ),
                            },
                            ensure_ascii=False,
                        )
                else:
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
            # 2026-05-21 fix: shield 防 cancel
            await asyncio.shield(db.commit())
            await db.refresh(tc_db)

            yield _sse("tool_call_end", {
                "id": tc_db.id,
                "tool_name": tool_name,
                "status": tc_db.status,
                "result_text": result_text[:600] + ("..." if len(result_text) > 600 else ""),
                "duration_ms": tc_db.duration_ms,
            })

            # 特殊：save_design_draft 成功 → 单独通知前端渲染设计文档卡片。
            # 只靠 tool_call_end 时，结果会被截断且 UI 只显示在工具折叠条里；
            # draft_saved 是给聊天正文的即时可见入口。
            if tool_name == "save_design_draft" and tc_db.status == "success":
                try:
                    parsed = json.loads(result_text)
                    if isinstance(parsed, dict) and parsed.get("ok") is not False:
                        draft_id = parsed.get("draft_id") or parsed.get("id")
                        if draft_id:
                            yield _sse("draft_saved", {
                                "tool_call_id": tc_db.id,
                                "draft_id": draft_id,
                                "summary": parsed.get("summary"),
                                "preview_url": parsed.get("preview_url"),
                                "level": parsed.get("level"),
                                "warnings": parsed.get("warnings") or [],
                            })
                except Exception:
                    pass

            # 特殊：write_artifact / save_design_draft 成功 → 单独通知前端刷新右栏
            _emits_artifact = (
                (tool_name == "write_artifact" and tc_db.status == "success")
                or (tool_name in (
                    "export_apaas_app_design_doc",
                    "save_design_draft",
                ) and tc_db.status == "success")
            )
            if _emits_artifact:
                from sqlalchemy import desc as _desc
                # write_artifact: filename 在 args；其他工具直接拉本 session 最近落的那条。
                if tool_name == "write_artifact":
                    res = await db.execute(
                        select(AIChatArtifact)
                        .where(
                            AIChatArtifact.session_id == session.id,
                            AIChatArtifact.filename == args.get("filename"),
                        )
                        .order_by(_desc(AIChatArtifact.version))
                        .limit(1)
                    )
                else:
                    res = await db.execute(
                        select(AIChatArtifact)
                        .where(AIChatArtifact.session_id == session.id)
                        .order_by(_desc(AIChatArtifact.id))
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
