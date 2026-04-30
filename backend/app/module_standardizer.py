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
| sales_admin | 销售管理员 |
""",

    "dicts": """\
## 三、数据字典

### 3.1 订单状态

| 字典编码 | 字典名称 |
|---------|---------|
| order_status | 订单状态 |

| 选项编码 | 选项名称 |
|---------|---------|
| draft | 草稿 |
| submitted | 已提交 |
""",

    # 数据模型只描述存储；不要写字典/关联/组件，那些都在表单定义里
    "models": """\
## 四、数据模型

### 4.1 模型定义

| 模型编码 | 模型名称 |
|---------|---------|
| sales_order | 销售订单 |
| sales_order_item | 销售订单明细 |

### 4.2 模型字段

| 模型编码 | 字段编码 | 字段名称 | 数据库字段类型 | 长度/精度 |
|---------|---------|---------|----------------|-----------|
| sales_order | order_no | 订单编号 | varchar | 64 |
| sales_order | order_date | 下单日期 | datetime |  |
| sales_order | total_amount | 订单金额 | decimal | 18,2 |
| sales_order_item | product_name | 产品名称 | varchar | 128 |
| sales_order_item | quantity | 数量 | decimal | 18,2 |
""",

    "forms": """\
## 五、表单定义

### 5.1 表单清单

| 表单编码 | 表单名称 | 绑定主表模型 | 说明 |
|---------|---------|-------------|------|
| sales_order_form | 销售订单表单 | sales_order | 销售订单录入与查询页面 |

### 5.2 主表字段定义

| 表单名称 | 字段编码 | 字段名称 | 组件类型 | 必填 | 隐藏 | 只读 | 列表展示 | 查询条件 | 字典编码 | 目标模型编码 | 目标字段编码 | 本表关联字段编码 | 说明 |
|---------|---------|---------|---------|------|------|------|----------|----------|---------|------------|------------|----------------|------|
| 销售订单表单 | order_no | 订单编号 | 单行输入 | 是 | 否 | 是 | 是 | 是 |  |  |  |  | 自动生成 |
| 销售订单表单 | order_status | 订单状态 | 下拉单选 | 是 | 否 | 否 | 是 | 是 | order_status |  |  |  |  |
| 销售订单表单 | customer_ref | 客户 | 数据单选 | 是 | 否 | 否 | 否 | 是 |  | customer | customer_name |  | 选择客户主数据 |

### 5.3 子表区域定义

| 表单名称 | 子表区域名称 | 绑定模型 | 说明 |
|---------|-------------|---------|------|
| 销售订单表单 | 订单明细 | sales_order_item | 销售订单明细列表 |

### 5.4 子表字段定义

| 表单名称 | 子表区域名称 | 字段编码 | 字段名称 | 组件类型 | 必填 | 隐藏 | 只读 | 列表展示 | 查询条件 | 字典编码 | 目标模型编码 | 目标字段编码 | 本表关联字段编码 | 说明 |
|---------|-------------|---------|---------|---------|------|------|------|----------|----------|---------|------------|------------|----------------|------|
| 销售订单表单 | 订单明细 | product_name | 产品名称 | 单行输入 | 是 | 否 | 否 | 是 | 否 |  |  |  |  |  |
""",

    "permissions": """\
## 六、权限定义

| 表单名称 | 角色编码 | 可暂存 | 可新增 | 可导入 | 可查看 | 可编辑 | 可删除 | 可导出 | 数据范围 |
|---------|---------|------|------|------|------|------|------|------|---------|
| 销售订单表单 | sales_admin | 是 | 是 | 是 | 是 | 是 | 是 | 是 | 全部数据 |
""",
}

# ── 字段类型枚举（提供给 LLM，防止乱写）──────────────────────
_VALID_FIELD_TYPES = (
    "单据号、单行输入、多行输入、富文本、手机号码、电子邮箱、身份证号、超链接、"
    "数字、金额、日期时间、开关、附件上传、地理位置、地区地址、人员选择、部门选择、"
    "下拉单选（需字典编码）、下拉多选（需字典编码）、单选框（需字典编码）、复选框（需字典编码）、"
    "数据单选（需目标模型编码）、数据选择（需目标模型编码）、关联表单（需目标模型编码 + 本表关联字段编码）、"
    "子表（通过 5.3 子表区域定义声明，绑定模型必须在第四章已定义）"
)

_DATA_SCOPES = "全部数据 / 本人数据 / 本部门 / 本部门及下属部门"


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
            "\n- 必须输出两张表：4.1 模型定义（模型编码 | 模型名称）和 4.2 模型字段（模型编码 | 字段编码 | 字段名称 | 数据库字段类型 | 长度/精度），不要每个模型一个 ### 子章节\n"
            "- 「数据库字段类型」只能使用：varchar / text / decimal / date / datetime / int / bigint，必须优先保留原文中的数据库类型\n"
            "- 只有原文完全没有数据库类型时，才可按字段语义补齐一个最接近的数据库类型\n"
            "- 原文如果同时出现“类型”和“组件”，类型用于“数据库字段类型”，组件不要写进数据模型表（组件类型属于五、表单定义）\n"
            "- 数据模型表里**不要**出现：字典编码、目标模型编码、关联字段编码、组件类型、必填/隐藏/只读 等列，这些都属于表单定义\n"
            "- 字段编码不能直接使用 name/title/status/type/level/department/user/phone/email/manager/result/remark/description/content 等保留短名，必须加业务前缀\n"
        )
    if module == "forms":
        base += (
            "\n- 必须输出 5.1 表单清单 + 5.2 主表字段定义，若有子表再补 5.3 子表区域定义 + 5.4 子表字段定义\n"
            f"- 组件类型只能从以下选择：{_VALID_FIELD_TYPES}\n"
            "- 5.2/5.4 字段表共 14/15 列，列序与列名不可改\n"
            "- 下拉类组件（下拉单选/下拉多选/单选框/复选框）必须填写「字典编码」\n"
            "- 数据类组件（数据单选/数据选择/关联表单）必须填写「目标模型编码」+「目标字段编码」\n"
            "- 关联表单还要填「本表关联字段编码」（指向当前表单中用来筛选目标模型数据的字段）\n"
        )
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
你是一个 aPaaS 表单定义补齐助手。
下面是一段格式不标准、且可能不完整的"表单定义"内容，请将其转换为标准格式，并补齐构建所需的最小表单信息。

## 目标格式模板
{template}

## 已标准化的数据模型（必须与此保持一致）
以下是本文档数据模型章节的标准化结果，表单中的模型编码和字段编码必须与此完全一致，不得自行更改：

{models_context}

## 约束规则
- 只输出表单定义的标准 Markdown，不要输出其他任何内容
- 必须输出 5.1 表单清单 + 5.2 主表字段定义；如有子表再补 5.3 子表区域定义 + 5.4 子表字段定义
- 5.1 表单清单列：表单编码 | 表单名称 | 绑定主表模型 | 说明
- 5.2 主表字段定义共 14 列，列序与列名严格按模板，不要新增/合并/删列
- 表单中"绑定主表模型"必须与上面数据模型中的模型编码完全一致
- 5.2/5.4 中**普通字段、数据单选、数据选择**的"字段编码"必须与对应模型的字段编码完全一致；**关联表单**的"字段编码"是组件编码，不要求在数据模型中存在
- 组件类型只能从以下选择：{_VALID_FIELD_TYPES}
- 下拉单选/下拉多选/单选框/复选框 必须填写「字典编码」（引用第三章已定义的字典）
- 数据单选/数据选择/关联表单 必须填写「目标模型编码」+「目标字段编码」
- 关联表单 还需填「本表关联字段编码」（当前表单内用于筛选目标模型数据的字段编码）
- 子表通过 5.3 表声明（绑定模型必须在数据模型中存在），其字段配置写在 5.4，不要把子表字段塞到 5.2
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
