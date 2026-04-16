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

| 字段编码 | 字段名称 | 存储类型 | 长度 | 字典编码 | 关联模型编码 | 关联显示字段编码 | 说明 |
|---------|---------|---------|------|---------|------------|----------------|------|
| name | 名称 | varchar | 255 | | | | |
| type | 类型 | varchar | 64 | type_dict | | | |
| ref_id | 关联记录 | varchar | 64 | | other_model | name | |
""",

    "forms": """\
## 五、表单配置

### 模型名称（model_code）

| 字段编码 | 字段名称 | 组件类型 | 是否隐藏 | 是否只读 | 是否必填 | 是否列表展示 | 是否查询条件 | 字典编码 | 目标模型编码 | 目标字段编码 |
|---------|---------|---------|---------|---------|---------|------------|------------|---------|------------|------------|
| name | 名称 | 单行输入 | 否 | 否 | 是 | 是 | 是 | | | |
| type | 类型 | 下拉单选 | 否 | 否 | 是 | 是 | 是 | type_dict | | |
| ref_id | 关联记录 | 数据单选 | 否 | 否 | 否 | 是 | 否 | | other_model | name |
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
你是一个 aPaaS 设计文档模块补齐助手。
下面是一段格式不标准、且可能信息不完整的"{_MODULE_NAMES.get(module, module)}"内容，请将其整理成标准格式，并补齐构建所需的最小信息。

## 目标格式模板
{template}

## 约束规则
- 只输出该模块的标准 Markdown，不要输出其他任何内容
- 优先依据原文抽取；原文未显式列出但可由模块上下文稳定推断的信息，可以补齐
- 允许补齐“构建必需但文档常省略”的最小信息，例如：
  - 模型/字段的存储类型、常见长度
  - 表单组件类型、必填/列表展示/查询条件
  - 权限的基础查看/编辑能力与数据范围
- 补齐时必须遵守模块原意，不得新增原文不存在的业务对象、业务流程、角色或字典
- 无法稳定判断时留空，不要硬猜
- 编码字段只能是英文小写字母+下划线，字母开头
- 所有表格必须有表头行和分隔行
"""

    if module == "models":
        base += (
            "\n- 数据模型里的“存储类型”必须优先保留原文中的数据库类型，例如：varchar / text / decimal / date / datetime / int / bigint / boolean\n"
            "- 只有原文完全没有数据库类型时，才可按字段语义补齐一个最接近的数据库类型\n"
            "- 原文如果同时出现“类型”和“组件”，则：类型用于“存储类型”，组件不要写进数据模型表\n"
            "- 如果字段来自附件/链接/日期/数字等组件，也不要把组件名写进“存储类型”，应写成对应数据库类型\n"
        )
    if module == "forms":
        base += f"\n- 组件类型只能从以下选择：{_VALID_FIELD_TYPES}\n"
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
你是一个 aPaaS 表单配置补齐助手。
下面是一段格式不标准、且可能不完整的"表单配置"内容，请将其转换为标准格式，并补齐构建所需的最小表单信息。

## 目标格式模板
{template}

## 已标准化的数据模型（必须与此保持一致）
以下是本文档数据模型章节的标准化结果，表单中的模型编码和字段编码必须与此完全一致，不得自行更改：

{models_context}

## 约束规则
- 只输出表单配置的标准 Markdown，不要输出其他任何内容
- 表单必须和上方数据模型严格一致，但允许基于模型字段补齐默认表单配置
- ### 子章节标题格式必须是：### 模型名称（model_code）
- model_code 必须与上面数据模型中的模型编码完全一致
- 表格中的字段编码必须与对应模型的字段编码完全一致
- 所有表格必须有表头行和分隔行
- **必须保留原文档的组件类型列（组件类型），不得丢弃**，可用值：单据号、单行输入、多行输入、下拉单选、下拉多选、单选框、复选框、数据单选、数据选择、关联表单、日期时间、数字、金额、附件上传、开关、人员选择、部门选择
- 有字典的字段（下拉单选/单选框等）必须保留字典编码列
- 有关联模型的字段（数据单选/数据选择等）必须保留目标模型编码和目标字段编码列
- 如果原文未逐项描述表单属性，可按常见构建规则补齐：
  - 编码/名称类字段默认可编辑
  - 状态类字段默认列表展示
  - 名称/编码/状态/日期类字段可作为查询条件候选
  - 主键/系统字段不要生成进表单

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
            timeout=45.0,  # 从默认120s降到45s，大多数模块30s内完成
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
