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
  "permissions": []
}
```"""

_FIELD_TYPES = """\
## 字段类型及图标（只能使用以下类型）

| type | icon | 使用场景 |
|------|------|----------|
| 单据号 | # | 唯一编号，自动生成 |
| 单行输入 | T | 普通文本：名称、标题 |
| 多行输入 | ¶ | 长文本：描述、备注 |
| 手机号码 | 📱 | 手机号 |
| 电子邮箱 | ✉ | 邮箱 |
| 下拉单选 | ▼ | 固定选项单选，必须绑定字典（设 dict 字段） |
| 下拉多选 | ☰ | 固定选项多选，必须绑定字典 |
| 数据单选 | 🔗 | 关联其他表单数据，必须设 ref |
| 日期时间 | 📅 | 日期、时间 |
| 金额 | 💰 | 金额 |
| 数字 | 123 | 数量、数值 |
| 附件上传 | 📎 | 文件上传 |
| 开关 | ⊘ | 是/否 |
| 人员选择 | 👤 | 选择系统用户 |
| 地理位置 | 📍 | 地址定位 |
| 子表 | ▦ | 明细行（订单行、配件清单等） |"""

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
6. **下拉单选/多选字段必须设 dict**，数据单选字段必须设 ref"""

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
"""


# ================================================================
# 公开接口
# ================================================================

async def parse_doc_with_ai(
    text: str, filename: str = "", on_progress: ProgressCallback = None
) -> Dict:
    """用 AI 解析任意格式的需求文档，返回标准 preview JSON。

    小文档（<= CHUNK_CHAR_LIMIT）：单次 AI 调用
    大文档：先提概览，再按章节分段解析，最后合并

    on_progress: 可选的异步回调，用于报告解析进度
    """
    logger.info(f"AI 文档解析: {filename}, 长度 {len(text)} 字符")

    async def _progress(msg: str):
        if on_progress:
            await on_progress(msg)

    await _progress(f"文档长度 {len(text)} 字符，开始解析...")

    if len(text) <= CHUNK_CHAR_LIMIT:
        await _progress("小文档，单次 AI 解析...")
        data = await _parse_single(text, filename)
    else:
        data = await _parse_chunked(text, filename, _progress)

    # 后处理
    await _progress("正在整理结果...")
    _sanitize_codes(data)
    _fill_icons(data)
    _dedup_dicts(data)

    summary = (
        f"解析完成！{len(data.get('models', []))} 个表单、"
        f"{len(data.get('dicts', []))} 个字典、"
        f"{len(data.get('roles', []))} 个角色"
    )
    await _progress(summary)
    logger.info(f"AI 解析完成: {summary}")
    return data


# ================================================================
# 小文档：单次调用
# ================================================================

async def _parse_single(text: str, filename: str) -> Dict:
    client = LLMClient()
    # 大文档截断，防止 API 超时（保留前 60000 字符，约 30000 汉字）
    truncated = text[:60000] if len(text) > 60000 else text
    user_msg = f"请分析以下需求文档，提取所有业务表单、字段、角色、字典等信息，输出标准 JSON。\n\n"
    if filename:
        user_msg += f"文档名：{filename}\n\n"
    user_msg += f"---\n\n{truncated}"

    result = await client.chat_completion(
        [{"role": "system", "content": SINGLE_SYSTEM_PROMPT},
         {"role": "user", "content": user_msg}],
        max_tokens=16384, timeout=300.0, temperature=0.2
    )
    content = result["choices"][0]["message"]["content"]
    data = _extract_json(content)
    if not data or not data.get("models"):
        raise ValueError("AI 未能识别出业务表单")
    return data


# ================================================================
# 大文档：分段解析
# ================================================================

async def _parse_chunked(text: str, filename: str, progress=None) -> Dict:
    """大文档分段解析流程：
    1. 用 AI 快速提取概览（应用名、角色、表单清单）
    2. 按章节拆分文档
    3. 并发调用 AI 解析每段的详细字段
    4. 合并所有结果
    """
    async def _p(msg):
        if progress:
            await progress(msg)

    client = LLMClient()

    # ── Step 1: 概览 ──
    await _p("Step 1/3: 提取文档概览...")
    logger.info("Step 1: 提取文档概览")
    # 概览只需要看每个章节的标题和开头，截取摘要
    overview_text = _build_overview_text(text)

    overview_result = await client.chat_completion(
        [{"role": "system", "content": OVERVIEW_SYSTEM_PROMPT},
         {"role": "user", "content": f"文档名：{filename}\n\n---\n\n{overview_text}"}],
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

    # 控制并发数（避免 API rate limit）
    semaphore = asyncio.Semaphore(3)

    async def parse_chunk(idx: int, chunk: str):
        async with semaphore:
            await _p(f"Step 3/3: 解析第 {idx+1}/{len(chunks)} 段...")
            logger.info(f"解析段 {idx+1}/{len(chunks)}, 长度 {len(chunk)} 字符")
            try:
                r = await client.chat_completion(
                    [{"role": "system", "content": DETAIL_SYSTEM_PROMPT},
                     {"role": "user", "content": f"以下是需求文档的一部分，请提取其中的表单和字典配置：\n\n---\n\n{chunk}"}],
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
        "permissions": [],
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


_ICON_MAP = {
    '单据号': '#', '单行输入': 'T', '多行输入': '¶',
    '手机号码': '📱', '电子邮箱': '✉', '下拉单选': '▼',
    '下拉多选': '☰', '数据单选': '🔗', '日期时间': '📅',
    '金额': '💰', '数字': '123', '附件上传': '📎',
    '开关': '⊘', '人员选择': '👤', '地理位置': '📍', '子表': '▦',
}


def _fill_icons(data: Dict):
    """补充缺失的 icon 字段"""
    for m in (data.get("models") or []):
        for f in (m.get("fields") or []):
            if not f.get("icon"):
                f["icon"] = _ICON_MAP.get(f.get("type", ""), "T")
            for sf in (f.get("sub_fields") or []):
                if not sf.get("icon"):
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
