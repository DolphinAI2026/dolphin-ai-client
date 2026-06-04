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
from app.observability import recorder

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
- ❌ **Phase 2 内 generate_app_from_doc 完成后停下等用户** — 用户已经在 Phase 1 末说"创建/部署"，意思是要"真能用"，不是"建个 draft"。Phase 2 内继续 deploy + publish 直到上线。
- ❌ **Phase 2 内每个工具调完都问"要继续吗 / 是否部署"** — 用户在 Phase 1 末已确认，Phase 2 自主推进。
- ❌ **遇到 appCode 冲突就改 app_code / 加 -v1 -v2 后缀重试** — appCode = 应用身份, 同 code 就是同一个应用！backend 已自动"同 app_code 复用同一应用 + 增量合并"(2026-05-28)，你**保持原 app_code 重试即可**，千万别加 -v1/-v2 后缀——那会建出一堆残缺重复应用，乱套。同理一份大文档**一次性 generate 整篇**，不要自己拆成多批分别 generate（拆批就会撞 appCode）。

### 例外：什么时候 Phase 1/2 内部也停下问
(a) 需求本身有歧义（如多个候选模型都叫"客户"）
(b) 用户明确说"先停在 draft / 我先看看再决定"
(c) 工具撞 token expired / 权限不足 等需要用户介入的错
(d) 当前租户没有绑定可用默认环境，或绑定了多个 connected 环境且用户明确要求选择目标环境

## 工具速查（55 个，按场景挑用）

文档处理：parse_design_doc / validate_builder_doc / write_artifact / read_attachment / export_apaas_app_design_doc
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
- 图片类材料（架构图 / 截图 / 流程图）已直接附在消息里、你能直接看图，**不要对图片调 read_attachment**（会被拒），直接描述图里内容即可

## 第二步：综合摘要 + 批量提问
读完所有材料后，给用户一个**结构化的"我看到了什么"汇总**：
- 我从你的 N 份材料里识别出：**A 张数据表**（列出名字）/ **B 个角色**（列出）/ **C 个流程**（列出）/ **D 个枚举值字段**（列出）
- 我推断的应用类型 = ...
- **同时**列出 3-5 个澄清问题（**批量**问，不是一句一句挤），每个问题写明"如果选 X / 如果选 Y 会影响什么"

## 第三步：用户回答后产出第一版 md
- 立刻 write_artifact 写出第一版完整 6 章设计文档（应用信息 / 角色 / 字典 / 模型 / 表单 / 权限，有审批需求再加可选的「七、审批流程」）
- 不要分章节交付，一次写完整篇

## 第四步：迭代修订
- 用户提小修订（改字段/编码/某段）时，read_artifact 拿当前 artifact 原文，再 edit_artifact 精确替换那一处，别整篇 write_artifact 重发；整篇推倒重来才 write_artifact 同名覆盖
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
    # 注意:删掉了原「跨租户兜底」两步(借任意租户的 is_default / 任意 active 模型)。
    # 那既是产品上要去掉的「兜底模型」,又是租户隔离泄漏 —— 等于拿别的租户的 API Key 跑当前租户的对话。
    # 现在只认**当前租户**的配置(上面 step1 selected + step2 tenant default),没有就明确提示去平台管理加。
    if not cfg:
        raise RuntimeError(
            "当前租户还没有配置可用的大模型,请到「平台管理 → 模型配置」添加一个模型后再使用。"
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
    - {"type": "done", "message": {content, tool_calls}, "usage": dict|None}

    usage 来自 OpenAI 兼容网关的 include_usage chunk（prompt_tokens/completion_tokens/…），
    网关不支持时为 None。上层 run_agent 拼装好 final message 之后再走持久化。
    """
    payload = {
        "model": cfg.model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
        "stream": True,
        # 让 OpenAI 兼容网关在 [DONE] 前回一个带 usage 的 chunk（token 必采）
        "stream_options": {"include_usage": True},
    }
    _apply_provider_payload_compat(cfg, payload)
    accumulated_content = ""
    usage_data: Optional[dict] = None
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
                # usage chunk：choices 为空、带 usage（include_usage 开启后 [DONE] 前到达）
                if chunk.get("usage"):
                    usage_data = chunk["usage"]
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
        "usage": usage_data,
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

MAX_TURNS = 20  # 工具循环最大轮数


def _sse(event: str, data: dict) -> dict:
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}


async def run_agent(
    db: AsyncSession,
    session: AIChatSession,
    current_user_message: str,
    abort_event: asyncio.Event,
) -> AsyncIterator[dict]:
    """对外入口：包一层 run 生命周期（可观测），把事件原样透传。

    用 try/finally 保证 end_run 在所有正常退出点 + SSE 客户端中途断开
    （GeneratorExit）时都恰好触发一次。recorder 自身吞异常，这里不会反噬主流程。
    """
    holder: dict = {"run_id": None, "status": "error", "error": None}
    try:
        async for event in _run_agent_inner(
            db, session, current_user_message, abort_event, holder
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
) -> AsyncIterator[dict]:
    """主 agent loop body。run 生命周期由外层 run_agent wrapper 管。
    holder = {"run_id": str|None, "status": "running"/"success"/"error", "error": str|None}
    """
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
        model=cfg.model,
    )
    yield _sse("run_started", {"run_id": holder["run_id"]})
    _obs_seq = 0  # run 内 step 单调递增序号

    try:
        messages = await _build_initial_messages(db, session, current_user_message)
    except Exception as e:
        holder["error"] = f"构建上下文失败：{e}"
        yield _sse("error", {"error": holder["error"]})
        yield _sse("done", {"ok": False, "run_id": holder["run_id"]})
        return

    asked_user = False  # 一旦 ask_user，loop 提前退出

    # 每个 session 的第一轮拉一次合并 schemas（base 4 + MCP bridge 注入的 N 个）
    # 这是 lazy 设计 — backend 启动时 MCP 可能还没 ready，所以放在 turn loop 外的第一次调用
    tool_schemas = await get_all_tool_schemas()

    for turn in range(MAX_TURNS):
        if abort_event.is_set():
            holder["status"] = "aborted"
            yield _sse("aborted", {"turn": turn})
            yield _sse("done", {"ok": False, "aborted": True, "run_id": holder["run_id"]})
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
            holder["error"] = f"LLM 调用失败 {e.response.status_code}: {detail}"
            yield _sse("error", {"error": holder["error"]})
            yield _sse("done", {"ok": False, "run_id": holder["run_id"]})
            return
        except Exception as e:
            holder["error"] = f"LLM 调用失败：{e}"
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
                yield _sse("assistant_message", {
                    "id": asst_db.id,
                    "session_id": asst_db.session_id,
                    "role": "assistant",
                    "content": content,
                    "run_id": holder["run_id"],
                    "created_at": asst_db.created_at.isoformat(),
                })
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

            # ── 可观测：双写 tool step（AIChatToolCall 已写，这里给统一底座再记一笔） ──
            _obs_seq += 1
            await recorder.record_step(
                holder["run_id"], step_type="tool", seq=_obs_seq,
                tool_name=tool_name, args=args, result_text=result_text,
                status=tc_db.status, duration_ms=tc_db.duration_ms,
            )

            # 特殊：write_artifact 成功 → 单独通知前端刷新右栏
            # 2026-05-21 扩展：update_app_from_doc / export_apaas_app_design_doc 也会
            # 被 dispatcher 拦截把 md_content 落 artifact（见 tools._persist_spec_artifact），
            # 这两个工具结束时也得发 artifact_created 让右栏立即刷新。
            # 2026-05-24: generate_app_from_doc 改强制 artifact_id 后, 不再产新 artifact
            # (用户 write_artifact 已经落表), 从列表去掉.
            _emits_artifact = (
                (tool_name in ("write_artifact", "edit_artifact") and tc_db.status == "success")
                or (tool_name in (
                    "update_app_from_doc",
                    "export_apaas_app_design_doc",
                ) and tc_db.status == "success")
            )
            if _emits_artifact:
                from sqlalchemy import desc as _desc
                # write_artifact: filename 在 args；generate/update_app_from_doc:
                # 不知道 dispatcher 落 artifact 用了什么 filename，直接拉本 session
                # 最近落的那条
                if tool_name in ("write_artifact", "edit_artifact"):
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
            holder["status"] = "success"
            yield _sse("done", {"ok": True, "awaiting_user": True, "run_id": holder["run_id"]})
            return

    # 超过 MAX_TURNS
    holder["error"] = f"达到最大循环次数 {MAX_TURNS}，已停止"
    yield _sse("error", {"error": holder["error"]})
    yield _sse("done", {"ok": False, "run_id": holder["run_id"]})
