"""模块级 LLM 标准化兜底

当纯代码解析某个模块失败时，只对该模块调用 LLM，
要求输出标准 markdown 格式，再回流给纯代码解析器。

原则：
- 只处理失败模块，不整篇交给 LLM
- 给 LLM 提供目标格式模板和明确约束
- LLM 输出只作为"更好的输入"，仍走纯代码解析，不直接信任
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


async def _llm_completion(
    messages: List[Dict],
    llm_cfg: Optional[Dict[str, Any]] = None,
    max_tokens: int = 4096,
    temperature: float = 0.1,
    timeout: float = 120.0,
) -> str:
    """统一 LLM 调用：优先用租户配置，降级用全局 LLMClient"""
    if llm_cfg and llm_cfg.get("base_url") and llm_cfg.get("api_key"):
        from app.routes.llm_configs import build_llm_chat_completions_url
        payload = {
            "model": llm_cfg["model"],
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        t = httpx.Timeout(connect=15.0, read=timeout, write=15.0, pool=15.0)
        async with httpx.AsyncClient(timeout=t) as http:
            resp = await http.post(
                build_llm_chat_completions_url(llm_cfg["base_url"]),
                headers={"Authorization": f"Bearer {llm_cfg['api_key']}", "Content-Type": "application/json"},
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
    else:
        from app.llm_client import LLMClient
        client = LLMClient()
        result = await client.chat_completion(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
        )
        return result["choices"][0]["message"]["content"]

# ── 各模块的目标标准模板（提供给 LLM 参考）──────────────────

_TEMPLATES: Dict[str, str] = {
    "roles": """\
## 二、角色列表

| 角色编码 | 角色名称 |
|---------|---------|
| admin | 管理员 |
""",

    "dicts": """\
## 三、数据字典

### 字典名称（dict_code）

| 选项编码 | 选项名称 |
|---------|---------|
| option1 | 选项一 |
| option2 | 选项二 |
""",

    "models": """\
## 四、数据模型

### 模型名称（model_code）【主表】

| 字段编码 | 字段名称 | 字段类型 | 字典编码 | 关联模型编码 | 关联显示字段编码 |
|---------|---------|---------|---------|------------|----------------|
| name | 名称 | 单行输入 | | | |
| type | 类型 | 下拉单选 | type_dict | | |
| ref_id | 关联记录 | 数据单选 | | other_model | name |
""",

    "forms": """\
## 五、表单配置

### 模型名称（model_code）

| 字段编码 | 字段名称 | 是否隐藏 | 是否只读 | 是否必填 | 是否列表展示 | 是否查询条件 |
|---------|---------|---------|---------|---------|------------|------------|
| name | 名称 | 否 | 否 | 是 | 是 | 是 |
""",

    "permissions": """\
## 六、权限配置

| 表单名称 | 角色编码 | 可暂存 | 可新增 | 可导入 | 可查看 | 可编辑 | 可删除 | 可导出 | 数据范围 |
|---------|---------|------|------|------|------|------|------|------|---------|
| 表单名 | admin | 是 | 是 | 是 | 是 | 是 | 是 | 是 | 全公司 |
""",
}

# ── 字段类型枚举（提供给 LLM，防止乱写）──────────────────────
_VALID_FIELD_TYPES = (
    "单据号、单行输入、多行输入、富文本、手机号码、电子邮箱、身份证号、超链接、"
    "数字、金额、日期时间、开关、附件上传、地理位置、地区地址、人员选择、部门选择、"
    "下拉单选（需字典编码）、下拉多选（需字典编码）、单选框（需字典编码）、复选框（需字典编码）、"
    "数据单选（需关联模型编码）、数据选择（需关联模型编码）、关联表单（需关联模型编码）、"
    "子表（关联模型编码填子表模型编码）"
)

_DATA_SCOPES = "全公司 / 本部门 / 本部门及下属部门 / 仅本人"


def _build_prompt(module: str, section_text: str) -> str:
    template = _TEMPLATES.get(module, "")
    base = f"""\
你是一个 Markdown 文档格式化助手。
下面是一段格式不标准的"{_MODULE_NAMES.get(module, module)}"内容，请将其转换为标准格式。

## 目标格式模板
{template}

## 约束规则
- 只输出该模块的标准 Markdown，不要输出其他任何内容
- 不要脑补、不要新增文档中没有的内容
- 缺失信息留空（单元格写空或省略该行）
- 编码字段只能是英文小写字母+下划线，字母开头
- 所有表格必须有表头行和分隔行
"""

    if module == "models":
        base += f"\n- 字段类型只能从以下选择：{_VALID_FIELD_TYPES}\n"
    if module == "permissions":
        base += f"\n- 数据范围只能是：{_DATA_SCOPES}\n"

    base += f"""
## 待转换内容
{section_text}

## 输出（只输出标准 Markdown，不要加解释）
"""
    return base


def _build_forms_prompt(section_text: str, models_context: str) -> str:
    """表单配置专用 prompt，附上已标准化的数据模型作为约束"""
    template = _TEMPLATES.get("forms", "")
    return f"""\
你是一个 Markdown 文档格式化助手。
下面是一段格式不标准的"表单配置"内容，请将其转换为标准格式。

## 目标格式模板
{template}

## 已标准化的数据模型（必须与此保持一致）
以下是本文档数据模型章节的标准化结果，表单中的模型编码和字段编码必须与此完全一致，不得自行更改：

{models_context}

## 约束规则
- 只输出表单配置的标准 Markdown，不要输出其他任何内容
- 不要脑补、不要新增文档中没有的内容
- ### 子章节标题格式必须是：### 模型名称（model_code）
- model_code 必须与上面数据模型中的模型编码完全一致
- 表格中的字段编码必须与对应模型的字段编码完全一致
- 所有表格必须有表头行和分隔行

## 待转换内容
{section_text}

## 输出（只输出标准 Markdown，不要加解释）
"""


_MODULE_NAMES = {
    "app_info": "应用信息",
    "roles": "角色列表",
    "dicts": "数据字典",
    "models": "数据模型",
    "forms": "表单配置",
    "permissions": "权限配置",
}


async def standardize_module(
    module: str,
    section_text: str,
    llm_cfg: Optional[Dict[str, Any]] = None,
    models_context: Optional[str] = None,
) -> str:
    """调用 LLM 将非标准模块内容转换为标准 Markdown

    Args:
        module: 模块 key（roles/dicts/models/forms/permissions）
        section_text: 原始非标准内容
        llm_cfg: tenant 级 LLM 配置，None 时用全局配置

    Returns:
        标准化后的 Markdown 文本（只含该模块内容，不含章节标题）
    """
    if not section_text.strip():
        logger.warning(f"module_standardizer: {module} 内容为空，跳过")
        return section_text

    if module == "forms" and models_context:
        prompt = _build_forms_prompt(section_text, models_context)
    else:
        prompt = _build_prompt(module, section_text)

    try:
        raw = await _llm_completion(
            messages=[{"role": "user", "content": prompt}],
            llm_cfg=llm_cfg,
            temperature=0.1,
            max_tokens=4096,
        )
        standardized = _extract_markdown(raw)
        logger.info(f"module_standardizer: {module} 标准化完成，输出 {len(standardized)} 字符")
        return standardized
    except Exception as e:
        logger.error(f"module_standardizer: {module} LLM 调用失败: {e}")
        return section_text  # 失败时返回原文，让解析器继续尝试


def _extract_markdown(text: str) -> str:
    """从 LLM 输出中提取 Markdown 内容（去掉可能的代码块包装）"""
    text = text.strip()
    # 去掉 ```markdown ... ``` 包装
    m = re.match(r"^```(?:markdown)?\s*\n([\s\S]*?)\n```\s*$", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # 去掉单独的 ``` 包装
    m = re.match(r"^```\s*\n([\s\S]*?)\n```\s*$", text)
    if m:
        return m.group(1).strip()
    return text
