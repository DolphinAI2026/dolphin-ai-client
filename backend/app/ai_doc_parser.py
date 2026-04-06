"""AI 驱动的文档解析器

不再为每种文档格式写死正则解析规则，而是让 LLM 阅读任意格式的文档，
统一输出符合 preview JSON 规范的结构化数据。

大文档自动拆分为多段，分别调用 AI 解析后合并结果。

输出规范参考: /docs/表单内容设计-优化建议.md
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Callable, Coroutine, Dict, List, Optional

# 进度回调类型：async def callback(message: str) -> None
ProgressCallback = Optional[Callable[[str], Coroutine]]

from app.llm_client import LLMClient
from app.config_validator import validate_full_config
from app.field_types import get_icon_map, build_prompt_field_types_table

logger = logging.getLogger(__name__)

# 单次 AI 调用可处理的文档字符上限（大约 15K tokens）
CHUNK_CHAR_LIMIT = 12000

# ──────────────────────────────────────────────
# System prompt
# ──────────────────────────────────────────────

_OUTPUT_SPEC = """\
只返回一个 JSON 对象，不要其他文字。JSON 结构如下：

```json
{
  "appName": "应用名称",
  "roles": [
    {"name": "角色名（中文）", "code": "role_code_英文小写"}
  ],
  "dicts": [
    {
      "name": "字典名（中文）",
      "code": "dict_code_英文小写",
      "options": [
        {"name": "选项名（中文）", "code": "option_code_英文小写"}
      ]
    }
  ],
  "models": [
    {
      "name": "表单/模型名（中文）",
      "code": "model_code_英文小写",
      "fields": [
        {
          "name": "字段名（中文）",
          "code": "field_code_英文小写",
          "type": "字段类型",
          "icon": "图标",
          "required": true,
          "dict": "对应字典的code（仅下拉单选/下拉多选时）",
          "ref": {"model": "关联模型code", "field": "显示字段code"},
          "sub_code": "子表模型code（仅子表时）",
          "sub_fields": [同 fields 格式]
        }
      ]
    }
  ],
  "workflows": [],
  "permissions": [
    {
      "form": "表单名（中文，对应 models 中的 name）",
      "rules": [
        {"role": "角色code 或 all", "op": "all 或 add/edit/delete", "data": "ALL/SELF/CURRENT_USER_DEPT"}
      ]
    }
  ]
}
```"""

_FIELD_TYPES = build_prompt_field_types_table()

_RULES = """\
## 核心规则

1. **严格按文档内容生成** — 禁止自行编造表单和字段，只从文档中提取
2. **所有 code 必须是英文小写 + 下划线**，禁止中文、拼音或纯数字
3. **字典必须有选项** — 每个字典至少 2 个选项，选项 code 用英文
4. **组件类型选择**：
   - 唯一标识 → 单据号
   - 固定枚举选项 → 下拉单选/多选（绑定字典）
   - 关联其他表 → 数据单选（设 ref）
   - 人员 → 人员选择
   - 状态字段有固定选项 → 下拉单选 + 字典
5. **有明细行的数据**（订单行、配件等）→ 使用子表，子表内字段放 sub_fields
6. **下拉单选/多选字段必须设 dict**，数据单选字段必须设 ref
7. **权限配置**：根据文档中的角色和权限描述，为每个表单生成权限规则：
   - role: 角色code（对应 roles 中的 code），"all" 表示全部人员
   - op: 操作类型，"all"=全部操作, "add"=新增, "edit"=编辑, "delete"=删除
   - data: 数据范围，"ALL"=全部数据, "SELF"=仅本人数据, "CURRENT_USER_DEPT"=本部门数据
   - 如果文档未明确权限，默认为每个表单生成 {"role":"all","op":"all","data":"ALL"}"""

# ── Step 1: 概览提取 ──
OVERVIEW_SYSTEM_PROMPT = f"""你是得帆云低代码平台的功能设计专家。
用户会给你一份需求文档，请快速浏览全文，提取概览信息。

只返回 JSON，不要其他文字：
```json
{{
  "appName": "应用名称",
  "roles": [{{"name": "角色名", "code": "英文code"}}],
  "model_names": ["表单1名称", "表单2名称", ...],
  "section_ranges": [
    {{"name": "表单名", "start_heading": "该表单对应的章节标题原文"}}
  ]
}}
```

要求：
- 识别文档中所有业务表单/数据模型（通常在二级或三级标题下）
- 识别所有角色
- model_names 只列名称，不需要字段详情
- code 必须是英文小写+下划线
"""

# ── Step 2: 分段详细解析 ──
DETAIL_SYSTEM_PROMPT = f"""你是得帆云低代码平台的功能设计专家。
用户会给你一段需求文档（可能是完整文档的一部分），请提取其中所有业务表单的详细字段配置。

{_OUTPUT_SPEC}

{_FIELD_TYPES}

{_RULES}

注意：
- 只输出这段文档中包含的表单，不要编造
- 如果这段中包含字典定义（枚举值），也要输出到 dicts 中
- 如果某个字段的选项值在文档中明确列出了，一定要创建对应字典并在字段上设 dict
"""

# ── 小文档一次性解析 ──
SINGLE_SYSTEM_PROMPT = f"""你是得帆云低代码平台的功能设计专家。你的任务是阅读用户提供的需求文档（任意格式），
然后输出标准化的 JSON 配置，供平台自动生成应用。

{_OUTPUT_SPEC}

{_FIELD_TYPES}

{_RULES}

## 自检清单

输出前请确认：
- 所有 code 都是纯英文小写+下划线
- 所有字典都有 ≥2 个选项
- 下拉单选/多选字段都设了 dict
- 数据单选字段都设了 ref
- 子表字段都设了 sub_code 和 sub_fields
- 每个表单都有对应的 permissions 规则
"""


# ================================================================
# 公开接口
# ================================================================

async def parse_doc_with_ai(
    text: str, filename: str = "", on_progress: ProgressCallback = None,
    existing_codes: Optional[Dict] = None,
    existing_config: Optional[Dict] = None,
    llm_cfg: Optional[Dict] = None,
) -> Dict:
    """用 AI 解析任意格式的需求文档，返回标准 preview JSON。

    小文档（<= CHUNK_CHAR_LIMIT）：单次 AI 调用
    大文档：先提概览，再按章节分段解析，最后合并

    on_progress: 可选的异步回调，用于报告解析进度
    existing_codes: 可选的已有编码信息（用于增量解析时复用编码），格式：
        {"model_codes": [...], "dict_codes": [...], "role_codes": [...],
         "field_codes": {...model_code: [field_codes]}}
    existing_config: 可选的 V1 完整配置（用于增量解析时保持名称和编码一致），
        传入时会在 prompt 中注入详细的约束信息（名称+编码映射）
    """
    logger.info(f"AI 文档解析: {filename}, 长度 {len(text)} 字符")

    async def _progress(msg: str):
        if on_progress:
            await on_progress(msg)

    await _progress(f"文档长度 {len(text)} 字符，开始解析...")

    # 构建已有配置约束文本（仅增量模式）
    config_constraint = ""
    if existing_config:
        config_constraint = _build_existing_config_constraint(existing_config)
        if config_constraint:
            logger.info(f"增量解析：注入已有配置约束（{len(config_constraint)} 字符）")

    if len(text) <= CHUNK_CHAR_LIMIT:
        await _progress("小文档，单次 AI 解析...")
        data = await _parse_single(text, filename, existing_codes=existing_codes, config_constraint=config_constraint, llm_cfg=llm_cfg)
    else:
        data = await _parse_chunked(text, filename, _progress, existing_codes=existing_codes, config_constraint=config_constraint, llm_cfg=llm_cfg)

    # 对 Markdown 中显式定义的字典做规则兜底，避免 LLM 漏掉未引用字典或漏掉选项
    extracted_dicts = _extract_markdown_dicts(text)
    if extracted_dicts:
        _merge_explicit_dicts(data, extracted_dicts)

    # 后处理
    await _progress("正在整理结果...")
    _sanitize_codes(data)
    _fill_icons(data)
    _dedup_dicts(data)

    # 标准模板编码校正：最后执行，确保文档中的编码不被任何后处理覆盖
    template_codes = _extract_template_codes(text)
    has_template = any(template_codes.get(k) for k in ("roles", "dicts", "models"))
    if has_template:
        logger.info(f"检测到标准模板编码: roles={len(template_codes.get('roles',[]))}, "
                    f"dicts={len(template_codes.get('dicts',[]))}, models={len(template_codes.get('models',[]))}")
        _apply_template_codes(data, template_codes)

    # Schema 校验 & 自动修复
    try:
        data, validation_warnings = validate_full_config(data)
        if validation_warnings:
            logger.info(f"配置校验产生 {len(validation_warnings)} 条警告")
            for w in validation_warnings[:10]:  # 最多记录前 10 条
                logger.warning(f"  校验: {w}")
    except ValueError as e:
        logger.error(f"配置校验失败: {e}")
        # 不阻断流程，返回原始数据
        pass

    summary = (
        f"解析完成！{len(data.get('models', []))} 个表单、"
        f"{len(data.get('dicts', []))} 个字典、"
        f"{len(data.get('roles', []))} 个角色"
    )
    await _progress(summary)
    logger.info(f"AI 解析完成: {summary}")
    return data


# ================================================================
# 已有编码提取 & prompt 构建
# ================================================================

def extract_existing_codes(parsed_config: Dict) -> Dict:
    """从已有的 parsed_config 中提取所有编码信息，用于增量解析时传给 AI。

    返回:
    {
        "model_codes": ["work_order", "engineer", ...],
        "dict_codes": ["customer_level", "work_order_status", ...],
        "role_codes": ["admin", "dispatcher", ...],
        "field_codes": {"work_order": ["order_no", "title", ...], ...}
    }
    """
    model_codes = []
    field_codes = {}
    for m in parsed_config.get("models", []):
        code = m.get("code", "")
        if code:
            model_codes.append(code)
            fields = []
            for f in m.get("fields", []):
                fc = f.get("code", "")
                if fc:
                    fields.append(fc)
                for sf in f.get("sub_fields", []):
                    sfc = sf.get("code", "")
                    if sfc:
                        fields.append(sfc)
            if fields:
                field_codes[code] = fields

    dict_codes = [d.get("code", "") for d in parsed_config.get("dicts", []) if d.get("code")]
    role_codes = [r.get("code", "") for r in parsed_config.get("roles", []) if r.get("code")]

    return {
        "model_codes": model_codes,
        "dict_codes": dict_codes,
        "role_codes": role_codes,
        "field_codes": field_codes,
    }


def _build_existing_codes_prompt(existing_codes: Dict) -> str:
    """构建"复用已有编码"的 prompt 片段。"""
    parts = []
    if existing_codes.get("model_codes"):
        parts.append(f"已有的数据模型编码：{', '.join(existing_codes['model_codes'])}")
    if existing_codes.get("dict_codes"):
        parts.append(f"已有的字典编码：{', '.join(existing_codes['dict_codes'])}")
    if existing_codes.get("role_codes"):
        parts.append(f"已有的角色编码：{', '.join(existing_codes['role_codes'])}")
    if existing_codes.get("field_codes"):
        field_parts = []
        for model_code, fields in existing_codes["field_codes"].items():
            field_parts.append(f"  {model_code}: {', '.join(fields)}")
        parts.append("已有的字段编码：\n" + "\n".join(field_parts))

    if not parts:
        return ""

    return (
        "【重要】以下是上一版本已有的编码，如果本次内容对应已有的业务概念，"
        "请复用已有编码，不要重新生成新编码。文档中明确标注了编码的以文档为准。\n\n"
        + "\n".join(parts) + "\n\n"
    )


def _build_existing_config_constraint(config: Dict) -> str:
    """从 V1 完整配置中构建约束文本，注入到 V2 解析 prompt 中。

    与 _build_existing_codes_prompt 不同，此函数输出名称+编码的完整映射，
    让 AI 能准确匹配语义相同但措辞不同的实体，从而保持一致性。
    输出 **全部** 字段和选项编码，确保 AI 精准复用。
    """
    if not config:
        return ""

    parts = []

    # 角色（完整列出）
    roles = config.get("roles", [])
    if roles:
        role_lines = []
        for r in roles:
            name = r.get("name", "")
            code = r.get("code", "")
            if name and code:
                role_lines.append(f"- {name} → code=`{code}`")
        if role_lines:
            parts.append("### 已有角色\n" + "\n".join(role_lines))

    # 字典（包含所有选项的 name→code 映射）
    dicts = config.get("dicts", [])
    if dicts:
        dict_lines = []
        for d in dicts:
            name = d.get("name", "")
            code = d.get("code", "")
            if name and code:
                options = d.get("options", [])
                opt_strs = []
                for o in options:
                    on = o.get("name", "")
                    oc = o.get("code", "")
                    if on and oc:
                        opt_strs.append(f"{on}(`{oc}`)")
                    elif on:
                        opt_strs.append(on)
                opt_str = ", ".join(opt_strs) if opt_strs else "无选项"
                dict_lines.append(f"- {name} → code=`{code}` | 选项: {opt_str}")
        if dict_lines:
            parts.append("### 已有字典\n" + "\n".join(dict_lines))

    # 模型及字段（列出全部字段，不截断）
    models = config.get("models", [])
    if models:
        model_lines = []
        for m in models:
            name = m.get("name", "")
            code = m.get("code", "")
            if name and code:
                fields = m.get("fields", [])
                field_strs = []
                for f in fields:
                    fn = f.get("name", "")
                    fc = f.get("code", "")
                    ft = f.get("type", "")
                    if fn and fc:
                        desc = f"{fn}→`{fc}`"
                        if ft:
                            desc += f"[{ft}]"
                        # 包含 dict / ref / sub_code 等关键属性
                        if f.get("dict"):
                            desc += f"{{dict:{f['dict']}}}"
                        if f.get("ref"):
                            ref = f["ref"]
                            desc += f"{{ref:{ref.get('model','')}.{ref.get('field','')}}}"
                        if f.get("sub_code"):
                            desc += f"{{子表:{f['sub_code']}}}"
                        field_strs.append(desc)
                model_lines.append(f"- **{name}** → code=`{code}`\n  字段: {', '.join(field_strs)}")
        if model_lines:
            parts.append("### 已有模型及字段\n" + "\n".join(model_lines))

    if not parts:
        return ""

    header = (
        "## 已有配置约束（最高优先级！必须严格遵守）\n\n"
        "当前应用已有以下配置。解析新文档时 **必须** 遵守以下规则：\n\n"
        "1. **编码必须精确复用**：如果新文档中的实体与已有实体是同一概念（即使名称措辞略有不同），**必须**使用已有的 code，绝不能生成新编码\n"
        "2. **名称保持一致**：已有实体的名称不要改动，除非新文档明确修改了名称\n"
        "3. **字段编码一一对应**：模型中已有字段的 code 必须原样保留，新增字段才使用新编码\n"
        "4. **字典选项编码保持**：已有字典选项的 code 原样保留，新增选项用新编码\n"
        "5. **属性保持稳定**：字段的 required / dict / ref / sub_code 等属性如果文档未明确变更，保持原值\n"
        "6. **只有文档中明确新增的内容**才使用新的名称和编码\n\n"
    )

    return header + "\n\n".join(parts) + "\n\n"


# ================================================================
# 小文档：单次调用
# ================================================================

async def _parse_single(text: str, filename: str, existing_codes: Optional[Dict] = None, config_constraint: str = "", llm_cfg: Optional[Dict] = None) -> Dict:
    if llm_cfg:
        client = LLMClient(api_key=llm_cfg.get("api_key"), base_url=llm_cfg.get("base_url"), model=llm_cfg.get("model"))
    else:
        client = LLMClient()
    # 智能截断：优先保留 ER 图和业务具体方案（含子表/字段定义）
    if len(text) > 40000:
        import re
        # 找关键章节
        er_match = re.search(r'(#{1,3}\s*.*?ER图.*?)(?=\n#{1,2}\s|\Z)', text, re.DOTALL)
        biz_match = re.search(r'(#{1,3}\s*.*?业务具体方案.*?)(?=\n#{1,2}\s[^#]|\Z)', text, re.DOTALL)
        perm_match = re.search(r'(#{1,3}\s*.*?(?:权限|角色|组织).*?)(?=\n#{1,2}\s|\Z)', text, re.DOTALL)

        # 前 20000 字符（背景、目标、流程等）
        head = text[:20000]
        # 拼接关键章节
        critical = ""
        for m in [er_match, biz_match, perm_match]:
            if m and m.group(1) not in head:
                critical += "\n\n" + m.group(1)[:15000]  # 每个关键章节最多 15000 字符
        truncated = head + critical
        truncated = truncated[:50000]  # 最终上限 50000
    else:
        truncated = text

    user_msg = f"请分析以下需求文档，提取所有业务表单、字段、角色、字典等信息，输出标准 JSON。\n特别注意：\n- 识别所有子表/明细表关系（1:N），用 sub_fields 表示\n- 识别权限角色和数据权限规则\n\n"
    if config_constraint:
        user_msg += config_constraint
    elif existing_codes:
        user_msg += _build_existing_codes_prompt(existing_codes)
    if filename:
        user_msg += f"文档名：{filename}\n\n"
    user_msg += f"---\n\n{truncated}"

    # 文档解析用配置中的文档模型，避免业务代码写死模型名
    result = await client.chat_completion(
        [{"role": "system", "content": SINGLE_SYSTEM_PROMPT},
         {"role": "user", "content": user_msg}],
        max_tokens=16384, timeout=300.0, temperature=0.2,
        model=client.doc_model
    )
    content = result["choices"][0]["message"]["content"]
    data = _extract_json(content)
    if not data or not data.get("models"):
        raise ValueError("AI 未能识别出业务表单")
    return data


# ================================================================
# 大文档：分段解析
# ================================================================

async def _parse_chunked(text: str, filename: str, progress=None, existing_codes: Optional[Dict] = None, config_constraint: str = "", llm_cfg: Optional[Dict] = None) -> Dict:
    """大文档分段解析流程：
    1. 用 AI 快速提取概览（应用名、角色、表单清单）
    2. 按章节拆分文档
    3. 并发调用 AI 解析每段的详细字段
    4. 合并所有结果
    """
    async def _p(msg):
        if progress:
            await progress(msg)

    if llm_cfg:
        client = LLMClient(api_key=llm_cfg.get("api_key"), base_url=llm_cfg.get("base_url"), model=llm_cfg.get("model"))
    else:
        client = LLMClient()

    # ── Step 1: 概览 ──
    await _p("Step 1/3: 提取文档概览...")
    logger.info("Step 1: 提取文档概览")
    # 概览只需要看每个章节的标题和开头，截取摘要
    overview_text = _build_overview_text(text)

    overview_user_msg = f"文档名：{filename}\n\n"
    if config_constraint:
        overview_user_msg += config_constraint
    overview_user_msg += f"---\n\n{overview_text}"

    overview_result = await client.chat_completion(
        [{"role": "system", "content": OVERVIEW_SYSTEM_PROMPT},
         {"role": "user", "content": overview_user_msg}],
        max_tokens=4096, timeout=60.0, temperature=0.1
    )
    overview_content = overview_result["choices"][0]["message"]["content"]
    overview = _extract_json(overview_content) or {}

    app_name = overview.get("appName", "业务应用")
    roles = overview.get("roles", [])
    model_names = overview.get("model_names", [])
    await _p(f"识别到应用「{app_name}」，{len(roles)} 个角色，{len(model_names)} 个表单")
    logger.info(f"概览: appName={app_name}, {len(roles)} 个角色, {len(model_names)} 个表单")

    # ── Step 2: 拆分文档 ──
    chunks = _split_doc_by_sections(text)
    await _p(f"Step 2/3: 文档拆分为 {len(chunks)} 段，开始逐段解析...")
    logger.info(f"文档拆分为 {len(chunks)} 段")

    # ── Step 3: 并发解析每段 ──
    all_models = []
    all_dicts = []
    all_permissions = []

    # 控制并发数（避免 API rate limit）
    semaphore = asyncio.Semaphore(3)

    async def parse_chunk(idx: int, chunk: str):
        async with semaphore:
            await _p(f"Step 3/3: 解析第 {idx+1}/{len(chunks)} 段...")
            logger.info(f"解析段 {idx+1}/{len(chunks)}, 长度 {len(chunk)} 字符")
            try:
                chunk_user_msg = "以下是需求文档的一部分，请提取其中的表单和字典配置：\n\n"
                if config_constraint:
                    chunk_user_msg += config_constraint
                elif existing_codes:
                    chunk_user_msg += _build_existing_codes_prompt(existing_codes)
                chunk_user_msg += f"---\n\n{chunk}"
                r = await client.chat_completion(
                    [{"role": "system", "content": DETAIL_SYSTEM_PROMPT},
                     {"role": "user", "content": chunk_user_msg}],
                    max_tokens=16384, timeout=180.0, temperature=0.2
                )
                c = r["choices"][0]["message"]["content"]
                part = _extract_json(c)
                if part:
                    return part
            except Exception as e:
                logger.warning(f"段 {idx+1} 解析失败: {e}")
            return None

    tasks = [parse_chunk(i, c) for i, c in enumerate(chunks)]
    results = await asyncio.gather(*tasks)

    for part in results:
        if not part:
            continue
        all_models.extend(part.get("models", []))
        all_dicts.extend(part.get("dicts", []))
        all_permissions.extend(part.get("permissions", []))
        # 从分段结果中也收集角色（可能概览漏掉）
        for r in part.get("roles", []):
            if r not in roles:
                roles.append(r)

    if not all_models:
        raise ValueError("AI 未能从文档中识别出业务表单")

    return {
        "appName": app_name,
        "roles": roles,
        "dicts": all_dicts,
        "models": all_models,
        "workflows": [],
        "permissions": all_permissions,
    }


# ================================================================
# 文档拆分工具
# ================================================================

def _build_overview_text(text: str) -> str:
    """构建概览文本：保留所有标题和每个章节的前几行"""
    lines = text.split('\n')
    out = []
    skip_count = 0
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('#'):
            out.append(line)
            skip_count = 0
        elif skip_count < 3:
            # 保留标题后的前 3 行（通常包含字段说明或简介）
            out.append(line)
            skip_count += 1
        elif '|' in stripped and skip_count < 5:
            # 保留表格的前几行
            out.append(line)
            skip_count += 1

    result = '\n'.join(out)
    # 概览不需要太长
    return result[:8000]


def _split_doc_by_sections(text: str) -> List[str]:
    """按二级/三级标题拆分文档为多段，每段不超过 CHUNK_CHAR_LIMIT"""
    # 按 ## 或 ### 拆分
    parts = re.split(r'\n(?=#{2,3}\s)', text)

    chunks: List[str] = []
    current = ""

    for part in parts:
        # 如果当前块加上这部分还不超限，合并
        if len(current) + len(part) <= CHUNK_CHAR_LIMIT:
            current += ("\n" if current else "") + part
        else:
            if current:
                chunks.append(current)
            # 如果单个 part 就超限，需要进一步拆分
            if len(part) > CHUNK_CHAR_LIMIT:
                sub_parts = _split_large_section(part)
                chunks.extend(sub_parts)
                current = ""
            else:
                current = part

    if current:
        chunks.append(current)

    return chunks


def _split_large_section(text: str) -> List[str]:
    """将超大段落按表格边界或行数拆分"""
    lines = text.split('\n')
    chunks = []
    current = []
    current_len = 0

    for line in lines:
        current.append(line)
        current_len += len(line) + 1
        if current_len >= CHUNK_CHAR_LIMIT:
            chunks.append('\n'.join(current))
            current = []
            current_len = 0

    if current:
        chunks.append('\n'.join(current))
    return chunks


def _extract_markdown_dicts(text: str) -> List[Dict]:
    """从 Markdown 文档中直接提取显式定义的数据字典和选项。"""
    lines = text.splitlines()
    in_dict_section = False
    current: Optional[Dict] = None
    extracted: List[Dict] = []

    def flush_current():
        nonlocal current
        if current and current.get("name") and current.get("code"):
            extracted.append(current)
        current = None

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("## "):
            if current:
                flush_current()
            lowered = stripped.lower()
            in_dict_section = "数据字典" in stripped or "dictionary" in lowered
            continue

        if not in_dict_section:
            continue

        heading_match = re.match(
            r"^###\s+(?:\d+(?:\.\d+)?\s+)?(.+?)\s+\(`([^`]+)`\)\s*$",
            stripped,
        )
        if heading_match:
            flush_current()
            current = {
                "name": heading_match.group(1).strip(),
                "code": heading_match.group(2).strip(),
                "options": [],
            }
            continue

        if not current or not stripped.startswith("|"):
            continue

        cols = [col.strip() for col in stripped.strip("|").split("|")]
        if len(cols) < 2:
            continue

        raw_code = cols[0].strip("`").strip()
        raw_name = cols[1].strip("`").strip()
        code_lower = raw_code.lower()
        name_lower = raw_name.lower()

        if code_lower in {"编码", "code", "valuecode"}:
            continue
        if not raw_code or set(raw_code) <= {"-", ":"}:
            continue
        if name_lower in {"显示值", "名称", "name", "valuename"}:
            continue

        current["options"].append({"code": raw_code, "name": raw_name})

    if current:
        flush_current()

    return extracted


def _merge_explicit_dicts(data: Dict, extracted_dicts: List[Dict]):
    """用文档中显式定义的字典覆盖/补全 AI 结果。"""
    dicts = list(data.get("dicts", []) or [])
    by_code = {d.get("code", ""): d for d in dicts if d.get("code")}
    by_name = {d.get("name", ""): d for d in dicts if d.get("name")}

    for extracted in extracted_dicts:
        target = by_code.get(extracted["code"]) or by_name.get(extracted["name"])
        if target:
            target["name"] = extracted["name"]
            target["code"] = extracted["code"]
            if extracted.get("options"):
                target["options"] = extracted["options"]
        else:
            dicts.append(extracted)
            by_code[extracted["code"]] = extracted
            by_name[extracted["name"]] = extracted

    data["dicts"] = dicts


# ================================================================
# 标准模板文档：完整编码提取（角色 + 字典 + 模型 + 字段）
# ================================================================

def _extract_template_codes(text: str) -> Dict:
    """从标准模板格式的 Markdown 文档中直接提取所有编码。

    支持提取：应用信息、角色、字典（含选项）、模型、字段。
    返回格式与 preview JSON 兼容，可直接用于校正 AI 生成的编码。
    """
    lines = text.splitlines()
    result: Dict = {"appName": "", "appCode": "", "roles": [], "dicts": [], "models": []}

    section = ""  # 当前大章节: app_info / roles / dicts / models / forms / permissions
    current_dict: Optional[Dict] = None
    current_model: Optional[Dict] = None
    table_type = ""  # 当前表格类型: dict_meta / dict_options / model_meta / field_list / role_list / app_info
    header_cols: List[str] = []

    _CODE_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')

    def _flush_dict():
        nonlocal current_dict
        if current_dict and current_dict.get("code"):
            result["dicts"].append(current_dict)
        current_dict = None

    def _flush_model():
        nonlocal current_model
        if current_model and current_model.get("code"):
            result["models"].append(current_model)
        current_model = None

    for line in lines:
        stripped = line.strip()

        # 检测大章节
        if stripped.startswith("## "):
            _flush_dict()
            _flush_model()
            table_type = ""
            low = stripped.lower()
            if "应用信息" in stripped:
                section = "app_info"
            elif "角色" in stripped:
                section = "roles"
            elif "数据字典" in stripped or "字典" in stripped:
                section = "dicts"
            elif "数据模型" in stripped or "模型" in stripped:
                section = "models"
            elif "表单" in stripped:
                section = "forms"
            elif "权限" in stripped:
                section = "permissions"
            else:
                section = ""
            continue

        # 子标题（字典/模型的具体条目）
        if stripped.startswith("### "):
            if section == "dicts":
                _flush_dict()
                # 尝试从标题中提取字典名称
                m = re.match(r'^###\s+(?:\d+(?:\.\d+)?\s+)?(.+)', stripped)
                if m:
                    name = m.group(1).strip()
                    # 去掉 (code) 后缀
                    code_m = re.match(r'(.+?)\s*\(`?([^`\)]+)`?\)', name)
                    if code_m:
                        current_dict = {"name": code_m.group(1).strip(), "code": code_m.group(2).strip(), "options": []}
                    else:
                        current_dict = {"name": name, "code": "", "options": []}
            elif section == "models":
                _flush_model()
                current_model = {"name": "", "code": "", "fields": []}
            table_type = ""
            continue

        # 表格行
        if not stripped.startswith("|"):
            continue
        cols = [c.strip().strip("`") for c in stripped.strip("|").split("|")]
        if len(cols) < 2:
            continue

        # 分隔线跳过
        if all(set(c) <= {"-", ":", " "} for c in cols):
            continue

        # 检测表头
        col0 = cols[0].strip()
        col1 = cols[1].strip() if len(cols) > 1 else ""

        # 应用信息表
        if section == "app_info":
            if col0 in ("项目", "项") and col1 in ("值",):
                table_type = "app_info"
                continue
            if table_type == "app_info" or not table_type:
                if "应用编码" in col0 or "编码" in col0:
                    result["appCode"] = col1
                elif "应用名称" in col0 or "名称" in col0:
                    result["appName"] = col1
            continue

        # 角色表
        if section == "roles":
            if "角色编码" in col0:
                table_type = "role_list"
                header_cols = [c.strip() for c in cols]
                continue
            if table_type == "role_list" and _CODE_RE.match(col0):
                role = {"code": col0, "name": col1}
                if len(cols) > 2:
                    role["description"] = cols[2].strip()
                result["roles"].append(role)
            continue

        # 字典表
        if section == "dicts" and current_dict is not None:
            if "字典编码" in col0:
                table_type = "dict_meta"
                continue
            if "选项编码" in col0:
                table_type = "dict_options"
                continue
            if table_type == "dict_meta" and _CODE_RE.match(col0):
                current_dict["code"] = col0
                current_dict["name"] = col1
                continue
            if table_type == "dict_options" and col0 and not set(col0) <= {"-", ":"}:
                current_dict["options"].append({"code": col0, "name": col1})
                continue
            continue

        # 模型表
        if section == "models" and current_model is not None:
            if "模型编码" in col0:
                table_type = "model_meta"
                continue
            if "字段编码" in col0:
                table_type = "field_list"
                header_cols = [c.strip() for c in cols]
                continue
            if table_type == "model_meta" and _CODE_RE.match(col0):
                current_model["code"] = col0
                current_model["name"] = col1
                if len(cols) > 2:
                    current_model["table_type"] = cols[2].strip()
                continue
            if table_type == "field_list" and _CODE_RE.match(col0):
                field: Dict = {"code": col0, "name": col1}
                # 解析更多列（数据库字段类型、长度、必填、字典编码、关联模型编码、关联显示字段编码、说明）
                if len(cols) > 2:
                    db_type = cols[2].strip()
                    if db_type:
                        field["_db_type"] = db_type
                if len(cols) > 4:
                    req = cols[4].strip()
                    field["required"] = req in ("是", "Yes", "true", "TRUE")
                if len(cols) > 5:
                    dict_code = cols[5].strip()
                    if dict_code and _CODE_RE.match(dict_code):
                        field["dict"] = dict_code
                if len(cols) > 6:
                    ref_model = cols[6].strip()
                    if ref_model and _CODE_RE.match(ref_model):
                        ref_field = cols[7].strip() if len(cols) > 7 and cols[7].strip() else ""
                        field["ref"] = {"model": ref_model, "field": ref_field}
                current_model["fields"].append(field)
                continue

    _flush_dict()
    _flush_model()
    return result


def _apply_template_codes(data: Dict, template: Dict):
    """用从 markdown 模板直接提取的编码校正 AI 生成的配置。

    原则：如果模板中有明确定义的编码，以模板为准；
    AI 额外推断的内容保留（如字段类型、图标等模板中没有的属性）。
    """
    # 应用信息
    if template.get("appCode"):
        data["appCode"] = template["appCode"]
    if template.get("appName"):
        data["appName"] = template["appName"]

    # 角色：按名称匹配，校正编码
    if template.get("roles"):
        tpl_roles_by_name = {r["name"]: r for r in template["roles"]}
        for role in data.get("roles", []):
            tpl = tpl_roles_by_name.get(role.get("name"))
            if tpl:
                role["code"] = tpl["code"]
                if tpl.get("description"):
                    role["description"] = tpl["description"]
        # 补全模板中有但 AI 遗漏的角色
        ai_role_names = {r.get("name") for r in data.get("roles", [])}
        for tpl_role in template["roles"]:
            if tpl_role["name"] not in ai_role_names:
                data.setdefault("roles", []).append(tpl_role)

    # 字典：按名称匹配，校正编码和选项
    if template.get("dicts"):
        tpl_dicts_by_name = {d["name"]: d for d in template["dicts"]}
        tpl_dicts_by_code = {d["code"]: d for d in template["dicts"] if d.get("code")}
        for d in data.get("dicts", []):
            tpl = tpl_dicts_by_name.get(d.get("name")) or tpl_dicts_by_code.get(d.get("code"))
            if tpl:
                d["code"] = tpl["code"]
                d["name"] = tpl["name"]
                if tpl.get("options"):
                    d["options"] = tpl["options"]
        # 补全
        ai_dict_names = {d.get("name") for d in data.get("dicts", [])}
        for tpl_dict in template["dicts"]:
            if tpl_dict["name"] not in ai_dict_names:
                data.setdefault("dicts", []).append(tpl_dict)

    # 模型：按名称匹配，校正模型编码和字段编码
    if template.get("models"):
        tpl_models_by_name = {m["name"]: m for m in template["models"]}
        for model in data.get("models", []):
            tpl = tpl_models_by_name.get(model.get("name"))
            if not tpl:
                continue
            model["code"] = tpl["code"]
            # 字段编码校正：精确匹配 → 包含匹配 → code 前缀匹配
            if tpl.get("fields"):
                tpl_fields_by_name = {f["name"]: f for f in tpl["fields"]}
                tpl_fields_list = tpl["fields"]
                for field in model.get("fields", []):
                    fname = field.get("name", "")
                    # 1. 精确匹配
                    tpl_f = tpl_fields_by_name.get(fname)
                    # 2. 包含匹配（AI 缩短名称：如"开始日期"匹配"计划开始日期"）
                    if not tpl_f and fname:
                        for tf in tpl_fields_list:
                            if fname in tf["name"] or tf["name"] in fname:
                                tpl_f = tf
                                break
                    if tpl_f:
                        field["code"] = tpl_f["code"]
                        if tpl_f.get("required") is not None:
                            field["required"] = tpl_f["required"]
                        if tpl_f.get("dict"):
                            field["dict"] = tpl_f["dict"]
                        if tpl_f.get("ref"):
                            field["ref"] = tpl_f["ref"]

    logger.info(f"模板编码校正完成: roles={len(template.get('roles', []))}, "
                f"dicts={len(template.get('dicts', []))}, models={len(template.get('models', []))}")


# ================================================================
# JSON 提取 & 后处理
# ================================================================

def _extract_json(content: str) -> Optional[Dict]:
    """从 AI 回复中提取 JSON 对象"""
    # 先尝试 ```json 代码块
    m = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # 尝试直接解析整段
    try:
        return json.loads(content.strip())
    except json.JSONDecodeError:
        pass

    # 尝试找到第一个 { 到最后一个 }
    start = content.find('{')
    end = content.rfind('}')
    if start >= 0 and end > start:
        try:
            return json.loads(content[start:end + 1])
        except json.JSONDecodeError:
            pass

    return None


def _sanitize_codes(data: Dict):
    """确保所有 code 字段为纯 ASCII 英文小写+下划线"""
    import hashlib

    def _fix(code: Optional[str], fallback: str = "") -> str:
        if not code:
            if fallback:
                return _fix(fallback)
            return ""
        if re.match(r'^[a-zA-Z][a-zA-Z0-9_]*$', code):
            return code.lower()
        ascii_part = re.sub(r'[^a-zA-Z0-9_]', '', code).lower()
        if len(ascii_part) >= 2:
            return ascii_part
        return 'c' + hashlib.md5(code.encode()).hexdigest()[:7]

    for r in (data.get("roles") or []):
        r["code"] = _fix(r.get("code"), r.get("name", ""))

    for d in (data.get("dicts") or []):
        d["code"] = _fix(d.get("code"), d.get("name", ""))
        for opt in (d.get("options") or []):
            opt["code"] = _fix(opt.get("code"), opt.get("name", ""))

    for m in (data.get("models") or []):
        m["code"] = _fix(m.get("code"), m.get("name", ""))
        for f in (m.get("fields") or []):
            f["code"] = _fix(f.get("code"), f.get("name", ""))
            if f.get("dict"):
                f["dict"] = _fix(f["dict"])
            if f.get("ref") and isinstance(f["ref"], dict):
                f["ref"]["model"] = _fix(f["ref"].get("model", ""))
                f["ref"]["field"] = _fix(f["ref"].get("field", ""))
            if f.get("sub_code"):
                f["sub_code"] = _fix(f["sub_code"])
            for sf in (f.get("sub_fields") or []):
                sf["code"] = _fix(sf.get("code"), sf.get("name", ""))
                if sf.get("dict"):
                    sf["dict"] = _fix(sf["dict"])
                if sf.get("ref") and isinstance(sf["ref"], dict):
                    sf["ref"]["model"] = _fix(sf["ref"].get("model", ""))
                    sf["ref"]["field"] = _fix(sf["ref"].get("field", ""))


_ICON_MAP = get_icon_map()


def _fill_icons(data: Dict):
    """始终用 _ICON_MAP 覆盖 icon 字段（LLM 可能返回中文类型名导致竖排）"""
    for m in (data.get("models") or []):
        for f in (m.get("fields") or []):
            f["icon"] = _ICON_MAP.get(f.get("type", ""), "T")
            for sf in (f.get("sub_fields") or []):
                sf["icon"] = _ICON_MAP.get(sf.get("type", ""), "T")


def _dedup_dicts(data: Dict):
    """去重字典（分段解析可能产生重复）"""
    seen = {}
    deduped = []
    for d in (data.get("dicts") or []):
        code = d.get("code", "")
        if code not in seen:
            seen[code] = d
            deduped.append(d)
        else:
            # 合并选项（保留更多选项的那个）
            existing = seen[code]
            if len(d.get("options", [])) > len(existing.get("options", [])):
                existing["options"] = d["options"]
    data["dicts"] = deduped
