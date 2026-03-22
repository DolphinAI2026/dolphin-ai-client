"""分阶段配置组装器

对话或文档生成配置时，不再要求 LLM 一次性输出所有内容。
改为分阶段调用，每次只生成一小块，后端拼装成完整配置。

阶段:
  1. 骨架 (skeleton): 应用名、角色、模型名列表、字典名列表
  2. 字典填充 (dicts): 批量填充字典选项（每次 10 个）
  3. 模型填充 (models): 逐个填充模型的字段详情（每次 1-2 个）

每个阶段通过 SSE 向前端推送进度。
"""
from __future__ import annotations

import json
import logging
import re
from typing import AsyncGenerator, Dict, List, Optional, Tuple

from app.llm_client import LLMClient

logger = logging.getLogger(__name__)

# 大文档阈值（字符数），超过此值则做预处理摘要
LARGE_DOC_THRESHOLD = 60_000

# ──────────────────────────────────────────────
# Prompts
# ──────────────────────────────────────────────

SKELETON_PROMPT = """你是得帆云低代码平台的配置设计专家。

请根据用户的需求描述，输出应用的**骨架配置**（不需要字段详情，不需要字典选项）。

只返回 JSON，不要其他文字：
```json
{
  "appName": "应用名称",
  "roles": [{"name": "角色名", "code": "role_code"}],
  "dict_names": [
    {"name": "字典名", "code": "dict_code", "hint": "简短描述用途"}
  ],
  "model_names": [
    {"name": "模型/表单名", "code": "model_code", "hint": "简短描述，列出主要字段名"}
  ],
  "workflow_hints": [
    {"form": "需要审批的表单名", "hint": "审批流转描述，如：员工提交→部门经理审批→HR复核"}
  ]
}
```

规则：
- code 用英文小写+下划线，避免数据库保留字
- 识别所有需要字典的枚举字段（状态、类型、类别等），列入 dict_names
- model_names 只列名称和简短描述，不要列字段详情
- 识别需要审批流程的表单，列入 workflow_hints
- 如果是文档解析结果，完全基于文档内容，不要编造"""

DICTS_PROMPT = """你是得帆云低代码平台的配置设计专家。

请为以下数据字典生成选项。每个字典至少 2 个选项。

只返回 JSON 数组，不要其他文字：
```json
[
  {
    "name": "字典名",
    "code": "dict_code",
    "options": [{"name": "选项名", "code": "option_code"}]
  }
]
```

规则：
- 选项 code 用英文小写+下划线
- 选项要合理、符合业务场景
- 如果文档/需求中明确列出了选项，严格按原文"""

MODEL_PROMPT = """你是得帆云低代码平台的配置设计专家。

请为以下模型/表单生成详细的字段配置。

只返回 JSON 数组，不要其他文字：
```json
[
  {
    "name": "表单名",
    "code": "model_code",
    "fields": [
      {
        "name": "字段名",
        "code": "field_code",
        "type": "字段类型",
        "icon": "图标",
        "required": true,
        "dict": "字典code（下拉类型时）",
        "ref": {"model": "关联模型code", "field": "显示字段code"},
        "sub_code": "子表模型code",
        "sub_fields": [同 fields 格式]
      }
    ]
  }
]
```

可用字段类型：单据号(#)、单行输入(T)、多行输入(¶)、手机号码(📱)、电子邮箱(✉)、下拉单选(▼)、下拉多选(☰)、数据单选(🔗)、日期时间(📅)、金额(💰)、数字(123)、附件上传(📎)、开关(⊘)、人员选择(👤)、地理位置(📍)、子表(▦)

规则：
- code 用英文小写+下划线，避免保留字（加业务前缀如 customer_name）
- 固定枚举选项 → 下拉单选/多选 + 设 dict
- 关联其他表 → 数据单选 + 设 ref
- 明细行 → 子表 + sub_code + sub_fields
- 唯一编号 → 单据号"""

WORKFLOW_PROMPT = """你是得帆云低代码平台的流程设计专家。

请为以下表单生成审批流程配置。

只返回 JSON 数组，不要其他文字：
```json
[
  {
    "name": "流程名称",
    "form": "关联表单名",
    "nodes": [
      {"name": "发起申请", "role": "", "type": "start"},
      {"name": "部门经理审批", "role": "角色code", "type": "approve"},
      {"name": "结束", "role": "", "type": "end"}
    ]
  }
]
```

节点类型：
- start: 发起节点（无需审批人）
- approve: 审批节点（需指定角色code作为审批人）
- end: 结束节点

规则：
- 每个流程必须有且仅有一个 start 和一个 end
- approve 节点按审批顺序排列（串行审批）
- role 必须是可用角色列表中的 code
- 流程名称要有业务含义，如"请假审批流程"、"采购申请审批"
- 根据业务场景合理设计审批层级"""


# ──────────────────────────────────────────────
# 大文档预处理
# ──────────────────────────────────────────────

def _summarize_doc_for_skeleton(text: str) -> str:
    """从大文档中提取结构摘要，只保留表单名、角色、字典名（不含详细字段/选项）。
    这样骨架阶段只需处理几千 token 而不是几万。"""

    lines = []
    lines.append("# 文档结构摘要（省略了字段详情和字典选项）\n")

    # 提取表单名称（从 ## 表单N：XXX 格式）
    form_headers = re.findall(r'^##\s+表单.+?：(.+?)$', text, re.MULTILINE)
    if form_headers:
        lines.append(f"## 表单列表（共 {len(form_headers)} 个）")
        for h in form_headers:
            # 提取中文名和英文code，如 "品牌档案（BrandArchive）"
            lines.append(f"- {h.strip()}")
        lines.append("")

    # 提取角色表（通常较短，完整保留）
    role_match = re.search(r'<roles>(.*?)</roles>', text, re.DOTALL)
    if role_match:
        lines.append("## 角色")
        lines.append(role_match.group(1).strip())
        lines.append("")

    # 提取字典名称（只取标题行，不取选项）
    dict_headers = re.findall(r'^###\s+(.+?)$', text, re.MULTILINE)
    # 过滤：只保留字典相关的（在 <dictionarys> 段内的）
    dict_section = re.search(r'<dictionarys>(.*?)</dictionarys>', text, re.DOTALL)
    if dict_section:
        dict_names = re.findall(r'^###\s+(.+?)$', dict_section.group(1), re.MULTILINE)
        if dict_names:
            lines.append(f"## 字典列表（共 {len(dict_names)} 个）")
            for d in dict_names:
                lines.append(f"- {d.strip()}")
            lines.append("")

    # 提取流程相关信息（从 processConfig 段）
    process_sections = re.findall(r'<business-form-processConfig-\d+>(.*?)</business-form-processConfig-\d+>', text, re.DOTALL)
    if process_sections:
        lines.append(f"## 审批流程（共 {len(process_sections)} 个表单有流程）")
        for ps in process_sections:
            # 提取流程描述中的关键信息
            flow_lines = [l.strip() for l in ps.strip().split('\n') if l.strip() and not l.strip().startswith('|---')]
            for fl in flow_lines[:5]:  # 只取前几行
                lines.append(f"  {fl}")
        lines.append("")

    # 如果提取不到结构化信息（非标准格式），退回到截断
    if len(lines) <= 2:
        return text[:20000] + "\n\n... [文档过长，已截断] ..."

    return "\n".join(lines)


def _extract_form_section(text: str, form_name: str, form_code: str) -> str:
    """从文档中提取指定表单的完整内容段落，用于模型字段生成。"""

    # 尝试通过 XML 标签定位
    for match in re.finditer(r'<business-form-\d+>(.*?)</business-form-\d+>', text, re.DOTALL):
        section = match.group(1)
        if form_name in section or form_code in section:
            # 截取合理长度（单个表单不应超过 8000 字符）
            return section[:8000]

    # 退回到按标题定位
    pattern = re.escape(form_name)
    m = re.search(pattern, text)
    if m:
        start = max(0, m.start() - 100)
        return text[start:start + 6000]

    return ""


def _extract_dict_section(text: str, dict_name: str, dict_code: str) -> str:
    """从文档中提取指定字典的选项内容。"""
    for match in re.finditer(r'<dictionary-\d+>(.*?)</dictionary-\d+>', text, re.DOTALL):
        section = match.group(1)
        if dict_name in section or dict_code in section:
            return section.strip()
    return ""


# ──────────────────────────────────────────────
# 分阶段生成
# ──────────────────────────────────────────────

async def assemble_config_streaming(
    user_prompt: str,
    context: str = "",
) -> AsyncGenerator[Dict, None]:
    """分阶段生成配置，通过 yield 返回进度和结果。

    每个 yield 的 dict 格式:
    - {"phase": "skeleton", "status": "running", "message": "..."}
    - {"phase": "skeleton", "status": "done", "data": {...骨架...}}
    - {"phase": "dicts", "status": "running", "message": "生成字典 1-10/37...", "batch": [...]}
    - {"phase": "models", "status": "running", "message": "生成模型: 客户信息...", "batch": [...]}
    - {"phase": "complete", "data": {...完整配置...}}
    """
    client = LLMClient()

    # 大文档预处理：提取摘要用于骨架阶段，保留原文用于后续阶段
    original_context = context
    is_large_doc = len(context) > LARGE_DOC_THRESHOLD
    if is_large_doc:
        logger.info(f"检测到大文档（{len(context)} 字符），进行预处理摘要")
        skeleton_context = _summarize_doc_for_skeleton(context)
        logger.info(f"摘要后长度：{len(skeleton_context)} 字符")
    else:
        skeleton_context = context

    # ── Phase 1: 骨架 ──
    yield {"phase": "skeleton", "status": "running", "message": f"正在分析需求，提取配置骨架...{'（大文档模式）' if is_large_doc else ''}"}

    skeleton_messages = [
        {"role": "system", "content": SKELETON_PROMPT},
        {"role": "user", "content": f"{skeleton_context}\n\n{user_prompt}" if skeleton_context else user_prompt},
    ]
    # 大文档给更长超时
    skeleton_timeout = 120.0 if is_large_doc else 60.0
    skeleton_result = await client.chat_completion(
        skeleton_messages, max_tokens=4096, timeout=skeleton_timeout, temperature=0.2
    )
    skeleton_text = skeleton_result["choices"][0]["message"]["content"]
    skeleton = _extract_json(skeleton_text)
    if not skeleton:
        yield {"phase": "skeleton", "status": "error", "message": "无法解析骨架配置"}
        return

    app_name = skeleton.get("appName", "应用")
    roles = skeleton.get("roles") or []
    dict_names = skeleton.get("dict_names") or []
    model_names = skeleton.get("model_names") or []

    yield {
        "phase": "skeleton", "status": "done",
        "message": f"骨架完成：{len(model_names)} 个模型、{len(dict_names)} 个字典、{len(roles)} 个角色",
        "data": skeleton,
    }

    # ── Phase 2: 字典填充 ──
    all_dicts: List[dict] = []
    if dict_names:
        batch_size = 10
        for i in range(0, len(dict_names), batch_size):
            batch = dict_names[i:i + batch_size]
            batch_end = min(i + batch_size, len(dict_names))
            yield {
                "phase": "dicts", "status": "running",
                "message": f"生成字典选项 {i + 1}-{batch_end}/{len(dict_names)}...",
            }

            batch_desc = "\n".join(
                f"- {d['name']} ({d['code']}): {d.get('hint', '')}"
                for d in batch
            )
            # 大文档模式：从原文中提取字典的详细选项作为参考
            dict_extra = ""
            if is_large_doc:
                for d in batch:
                    section = _extract_dict_section(original_context, d['name'], d['code'])
                    if section:
                        dict_extra += f"\n\n文档中「{d['name']}」的原始定义：\n{section[:2000]}"
            dict_messages = [
                {"role": "system", "content": DICTS_PROMPT},
                {"role": "user", "content": f"请为以下字典生成选项：\n\n{batch_desc}\n\n背景：{user_prompt[:500]}{dict_extra}"},
            ]
            try:
                dict_result = await client.chat_completion(
                    dict_messages, max_tokens=8192, timeout=90.0, temperature=0.2
                )
                dict_text = dict_result["choices"][0]["message"]["content"]
                batch_dicts = _extract_json_array(dict_text)
                if batch_dicts:
                    all_dicts.extend(batch_dicts)
                    yield {
                        "phase": "dicts", "status": "running",
                        "message": f"字典 {i + 1}-{batch_end} 完成（{len(batch_dicts)} 个）",
                        "batch": batch_dicts,
                    }
                else:
                    # 如果解析失败，用空选项兜底
                    for d in batch:
                        all_dicts.append({"name": d["name"], "code": d["code"], "options": []})
                    yield {
                        "phase": "dicts", "status": "running",
                        "message": f"字典 {i + 1}-{batch_end} 选项生成失败，已创建空字典",
                    }
            except Exception as e:
                logger.warning(f"字典批次 {i + 1}-{batch_end} 失败: {e}")
                for d in batch:
                    all_dicts.append({"name": d["name"], "code": d["code"], "options": []})

    yield {
        "phase": "dicts", "status": "done",
        "message": f"字典生成完成：{len(all_dicts)} 个",
    }

    # ── Phase 3: 模型填充 ──
    all_models: List[dict] = []
    if model_names:
        # 每次 1-2 个模型
        batch_size = 2
        available_dicts = ", ".join(f"{d['name']}({d['code']})" for d in all_dicts)
        available_models = ", ".join(f"{m['name']}({m['code']})" for m in model_names)

        for i in range(0, len(model_names), batch_size):
            batch = model_names[i:i + batch_size]
            batch_end = min(i + batch_size, len(model_names))
            names = "、".join(m["name"] for m in batch)
            yield {
                "phase": "models", "status": "running",
                "message": f"生成模型字段 {i + 1}-{batch_end}/{len(model_names)}: {names}...",
            }

            batch_desc = "\n".join(
                f"- {m['name']} ({m['code']}): {m.get('hint', '')}"
                for m in batch
            )
            # 大文档模式：从原文中提取对应表单的详细字段定义
            form_extra = ""
            if is_large_doc:
                for m in batch:
                    section = _extract_form_section(original_context, m['name'], m['code'])
                    if section:
                        form_extra += f"\n\n文档中「{m['name']}」的原始定义：\n{section}"
            model_messages = [
                {"role": "system", "content": MODEL_PROMPT},
                {"role": "user", "content": (
                    f"请为以下模型生成字段配置：\n\n{batch_desc}\n\n"
                    f"可用字典: {available_dicts}\n"
                    f"可关联模型: {available_models}\n\n"
                    f"背景：{user_prompt[:800]}"
                    f"{form_extra}"
                )},
            ]
            try:
                model_result = await client.chat_completion(
                    model_messages, max_tokens=8192, timeout=120.0, temperature=0.2
                )
                model_text = model_result["choices"][0]["message"]["content"]
                batch_models = _extract_json_array(model_text)
                if batch_models:
                    all_models.extend(batch_models)
                    yield {
                        "phase": "models", "status": "running",
                        "message": f"模型 {names} 完成（{sum(len(m.get('fields', [])) for m in batch_models)} 个字段）",
                        "batch": batch_models,
                    }
                else:
                    # 兜底：空模型
                    for m in batch:
                        all_models.append({"name": m["name"], "code": m["code"], "fields": []})
                    yield {
                        "phase": "models", "status": "running",
                        "message": f"模型 {names} 字段生成失败，已创建空模型",
                    }
            except Exception as e:
                logger.warning(f"模型批次 {i + 1}-{batch_end} 失败: {e}")
                for m in batch:
                    all_models.append({"name": m["name"], "code": m["code"], "fields": []})

    yield {
        "phase": "models", "status": "done",
        "message": f"模型生成完成：{len(all_models)} 个",
    }

    # ── Phase 4: 流程生成 ──
    all_workflows: List[dict] = []
    workflow_hints = skeleton.get("workflow_hints") or []
    if workflow_hints and roles:
        yield {"phase": "workflows", "status": "running", "message": f"生成 {len(workflow_hints)} 个审批流程..."}

        available_roles = ", ".join(f"{r['name']}({r['code']})" for r in roles)
        wf_desc = "\n".join(
            f"- 表单「{w['form']}」: {w.get('hint', '需要审批')}"
            for w in workflow_hints
        )
        wf_messages = [
            {"role": "system", "content": WORKFLOW_PROMPT},
            {"role": "user", "content": f"请为以下表单生成审批流程：\n\n{wf_desc}\n\n可用角色: {available_roles}\n\n背景：{user_prompt[:500]}"},
        ]
        try:
            wf_result = await client.chat_completion(
                wf_messages, max_tokens=4096, timeout=60.0, temperature=0.2
            )
            wf_text = wf_result["choices"][0]["message"]["content"]
            wf_data = _extract_json_array(wf_text)
            if wf_data:
                all_workflows = wf_data
                yield {
                    "phase": "workflows", "status": "running",
                    "message": f"流程生成完成（{len(all_workflows)} 个）",
                    "batch": all_workflows,
                }
        except Exception as e:
            logger.warning(f"流程生成失败: {e}")
            yield {"phase": "workflows", "status": "running", "message": f"流程生成失败（不阻断）: {e}"}

        yield {"phase": "workflows", "status": "done", "message": f"流程完成：{len(all_workflows)} 个"}
    else:
        if not workflow_hints:
            yield {"phase": "workflows", "status": "done", "message": "无需审批流程"}

    # ── 组装完整配置 ──
    complete_config = {
        "appName": app_name,
        "roles": roles,
        "dicts": all_dicts,
        "models": all_models,
        "workflows": all_workflows,
        "permissions": [],
    }

    # 后处理（加保护，不让后处理错误导致整体失败）
    try:
        from app.ai_doc_parser import _sanitize_codes, _fill_icons, _dedup_dicts
        _fix_field_types(complete_config)
        _sanitize_codes(complete_config)
        _fill_icons(complete_config)
        _dedup_dicts(complete_config)
    except Exception as e:
        logger.warning(f"后处理出错（不阻断）: {e}", exc_info=True)

    yield {
        "phase": "complete", "status": "done",
        "message": f"配置组装完成！{len(all_models)} 个模型、{len(all_dicts)} 个字典、{len(roles)} 个角色",
        "data": complete_config,
    }


# ──────────────────────────────────────────────
# 后处理：修正字段类型
# ──────────────────────────────────────────────

# LLM 有时用 icon 或缩写代替中文类型名
_TYPE_FIX_MAP = {
    "#": "单据号", "T": "单行输入", "¶": "多行输入",
    "📱": "手机号码", "✉": "电子邮箱", "▼": "下拉单选",
    "☰": "下拉多选", "🔗": "数据单选", "📅": "日期时间",
    "💰": "金额", "123": "数字", "📎": "附件上传",
    "⊘": "开关", "👤": "人员选择", "📍": "地理位置", "▦": "子表",
    "text": "单行输入", "textarea": "多行输入", "select": "下拉单选",
    "number": "数字", "date": "日期时间", "money": "金额",
    "phone": "手机号码", "email": "电子邮箱", "file": "附件上传",
    "switch": "开关", "user": "人员选择", "location": "地理位置",
}

def _fix_field_types(data: dict):
    """修正 LLM 可能输出的非标准字段类型"""
    for m in (data.get("models") or []):
        for f in (m.get("fields") or []):
            t = f.get("type", "")
            if t in _TYPE_FIX_MAP:
                f["type"] = _TYPE_FIX_MAP[t]
            for sf in (f.get("sub_fields") or []):
                st = sf.get("type", "")
                if st in _TYPE_FIX_MAP:
                    sf["type"] = _TYPE_FIX_MAP[st]


# ──────────────────────────────────────────────
# JSON 提取
# ──────────────────────────────────────────────

def _extract_json(content: str):
    """提取 JSON 对象"""
    m = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(content.strip())
    except json.JSONDecodeError:
        pass
    start = content.find('{')
    end = content.rfind('}')
    if start >= 0 and end > start:
        try:
            return json.loads(content[start:end + 1])
        except json.JSONDecodeError:
            pass
    return None


def _extract_json_array(content: str):
    """提取 JSON 数组"""
    m = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
    if m:
        try:
            result = json.loads(m.group(1))
            return result if isinstance(result, list) else [result]
        except json.JSONDecodeError:
            pass
    try:
        result = json.loads(content.strip())
        return result if isinstance(result, list) else [result]
    except json.JSONDecodeError:
        pass
    # 尝试找 [ ... ]
    start = content.find('[')
    end = content.rfind(']')
    if start >= 0 and end > start:
        try:
            return json.loads(content[start:end + 1])
        except json.JSONDecodeError:
            pass
    # 尝试找 { ... } (单个对象)
    obj = _extract_json(content)
    if obj:
        return [obj]
    return None
