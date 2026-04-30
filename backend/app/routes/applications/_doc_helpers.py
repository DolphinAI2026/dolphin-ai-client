"""设计文档 JSON 规范化、校验、修复与渲染的纯函数集合。

从已退役的 `routes/requirements.py` 抽出，由 `applications/docs.py` 和回归测试共用。
**不要** 在这里引入 FastAPI / DB / 任何会话相关副作用。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.app_code import normalize_app_code
from app.llm_client import LLMClient
from app.lowcode_standards import safe_field_code

logger = logging.getLogger(__name__)


# ─── Prompts ────────────────────────────────────────────────────────────────

GENERATE_DOC_PROMPT = """请根据上面的对话内容，按照以下6个需求维度提取信息，整理成结构化的功能设计文档。

## 提取框架（对话内容 → JSON 字段的映射关系）

| 需求维度 | 对应 JSON 字段 | 提取要点 |
|---|---|---|
| ① 项目目标 | app_info | 应用名称、应用编码（仅小写字母+数字+连字符，如 leave-mgmt）、业务目标说明 |
| ② 角色 | roles | 排除"全部员工/直属上级"等平台内置默认角色，只输出业务管理员、HR专员、审批专员等独立配置差异的角色 |
| ③ 枚举值 | data_dictionary | 排除审批状态（平台内置）；只输出真正需要的业务字典 |
| ④ 业务对象 | tables | 每个独立业务对象 = 一张主表，绝对不合并 |
| ⑤ 流程 | flows | 流程步骤、参与角色和状态变化；用于派生字段（如审批日期、申请状态等） |
| ⑥ 权限对象 | role_table_mapping | 角色对每张主表的操作权限（新增/审批/查看/导出等） + 数据范围（self/dept/all） |

## 字段映射要求

- **每张主表至少 6 个业务字段**：从对话中识别真实需要的信息（编号、申请人、日期、金额、状态、备注等）
- **数据类型规范**：仅使用 VARCHAR/INT/BIGINT/DECIMAL/DATE/DATETIME/TEXT，不要使用 JSON/BLOB
- **字段编码用小写下划线英文**（field_code, table_code 等），中文写在 field_name
- **flows 必须有 steps 数组**，每个 step 含 step（序号）/action（动作）/role（参与角色）/status（结果状态）
- **role_table_mapping.permissions[].operations**：从固定列表选 ["暂存","新增","导入","查看","编辑","删除","导出","批量同意","批量拒绝","查看审批历史","审批","归档"]，不能自创
- **role_table_mapping.permissions[].data_scope**：仅可填 self / dept / all / custom

## 输出格式

只输出一个完整的合法 JSON 对象，不要包裹任何 Markdown 代码块、解释、思考过程。

```json
{
  "app_info": {"code": "...", "name": "...", "description": "..."},
  "roles": [{"role_code": "...", "role_name": "...", "description": "..."}],
  "data_dictionary": [{"dict_code": "...", "dict_name": "...", "items": [{"item_code": "...", "item_name": "..."}]}],
  "tables": [{"table_code": "t_...", "table_name": "...", "table_type": "主表", "parent_table": "", "description": "...", "fields": [{"field_code": "...", "field_name": "...", "data_type": "VARCHAR", "length": "255", "is_pk": false, "is_fk": false, "nullable": true, "default_value": "", "description": "..."}]}],
  "modules": [{"module_code": "...", "module_name": "...", "description": "...", "features": [{"name": "...", "description": "...", "roles": ["..."]}]}],
  "flows": [{"flow_code": "...", "flow_name": "...", "description": "...", "table_code": "t_...", "steps": [{"step": 1, "action": "...", "role": "...", "status": "..."}]}],
  "role_table_mapping": [{"table_code": "t_...", "table_name": "...", "permissions": [{"role_code": "...", "role_name": "...", "operations": ["..."], "data_scope": "self"}]}],
  "forms": [],
  "custom_development": []
}
```

## 严格规则

- forms 当前阶段输出空数组 []（后续由配置转换器派生）
- custom_development 当前阶段输出空数组 []（自开发项不在标准设计文档中生成）
- 不要输出 <think>、思维链、解释、注释
- role_table_mapping 的 operations 只能从固定列表中选择，不能自创操作名"""


# ─── LLM 兜底调用 ───────────────────────────────────────────────────────────

async def _complete_with_config(
    cfg: dict | None,
    messages: list[dict[str, Any]],
    *,
    max_tokens: int = 4096,
    temperature: float = 0.0,
) -> str:
    """非流式调用，用于兜底修复 JSON。"""
    if cfg is None:
        raise ValueError("未配置可用的 LLM 模型")

    llm = LLMClient(api_key=cfg["api_key"], base_url=cfg["base_url"], model=cfg["model"])
    data = await llm.chat_completion(
        messages,
        max_tokens=max_tokens,
        timeout=120.0,
        temperature=temperature,
    )
    return ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "")


async def _repair_doc_json(cfg: dict | None, raw_text: str) -> dict:
    """把模型输出的非标准/不完整文本修复成合法文档 JSON。"""
    repair_messages = [
        {
            "role": "system",
            "content": (
                "你是严格的 JSON 修复器。"
                "请把用户提供的文本修复为一个完整、合法的 JSON 对象。"
                "只输出 JSON，不要输出任何解释、Markdown、代码块、<think>。"
                "JSON 必须包含并仅按以下核心结构组织："
                "app_info(object), roles(array), data_dictionary(array), tables(array), "
                "modules(array), flows(array), role_table_mapping(array), forms(array), custom_development(array)。"
                "每张主表至少保留 6 个业务字段；每张主表都要有表单、功能模块和权限矩阵。"
                "当前配置阶段不生成自开发项，custom_development 必须是空数组 []。"
            ),
        },
        {
            "role": "user",
            "content": f"请修复以下内容并输出合法 JSON：\n\n{raw_text[-20000:]}",
        },
    ]
    repaired_text = await _complete_with_config(cfg, repair_messages, max_tokens=6000, temperature=0.0)
    return extract_json(repaired_text)


async def _regenerate_doc_json(cfg: dict | None, base_messages: list[dict[str, Any]]) -> dict:
    """当提取/修复都失败时，强约束再生成一次完整 JSON。"""
    regen_messages = list(base_messages)
    regen_messages.append(
        {
            "role": "user",
            "content": (
                "请忽略之前的输出形式，重新生成一次。"
                "严格只输出一个完整合法 JSON 对象，不能有 <think>、解释、注释、Markdown 代码块。"
                "必须包含 app_info、roles、data_dictionary、tables、modules、flows、"
                "role_table_mapping、forms、custom_development。"
                "每个业务对象独立成表，每张主表至少 6 个业务字段，并生成对应表单、流程和权限。"
                "custom_development 必须是空数组 []。如果无法确定字段值，给出合理默认值，但必须保证 SPEC 结构完整。"
            ),
        }
    )
    regen_text = await _complete_with_config(cfg, regen_messages, max_tokens=8000, temperature=0.0)
    return extract_json(regen_text)


# ─── JSON 提取 ──────────────────────────────────────────────────────────────

def extract_json(text: str) -> dict:
    """从 AI 响应中提取 JSON 对象"""
    text = re.sub(r'^```(?:json)?\s*', '', text.strip(), flags=re.MULTILINE)
    text = re.sub(r'\s*```$', '', text.strip(), flags=re.MULTILINE)
    text = text.strip()

    start = text.find('{')
    if start == -1:
        raise ValueError('响应中未找到 JSON 对象')

    depth = 0
    end = -1
    for i, ch in enumerate(text[start:], start):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end = i
                break

    if end == -1:
        raise ValueError('JSON 对象不完整')

    return json.loads(text[start:end + 1])


# ─── 常量 ───────────────────────────────────────────────────────────────────

DOC_REQUIRED_LIST_KEYS = (
    "roles",
    "data_dictionary",
    "tables",
    "modules",
    "flows",
    "role_table_mapping",
    "forms",
)

SYSTEM_FIELD_CODES = {
    "id",
    "pk",
    "create_time",
    "created_at",
    "update_time",
    "updated_at",
    "create_by",
    "created_by",
    "update_by",
    "updated_by",
    "deleted",
    "deleted_at",
    "tenant_id",
    "org_id",
    "approval_status",
    "audit_status",
    "process_status",
}

FORBIDDEN_ROLE_CODES = {
    "employee",
    "staff",
    "user",
    "all_user",
    "all_employee",
    "approver",
    "leader",
    "supervisor",
}

FORBIDDEN_ROLE_NAME_KEYWORDS = ("员工", "全部员工", "普通用户", "审批人", "直属上级", "上级领导")


# ─── 文本 / 名称推断 ────────────────────────────────────────────────────────

def _list_or_empty(value: Any) -> list:
    return value if isinstance(value, list) else []


def _text_from_messages(messages: list[dict[str, Any]] | None) -> str:
    if not messages:
        return ""
    chunks: list[str] = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str):
            chunks.append(content)
    return "\n".join(chunks)


def _infer_doc_app_name(messages: list[dict[str, Any]] | None = None) -> str:
    source = _text_from_messages(messages)
    match = re.search(r"([^\n，。；：]{2,30}(系统|平台|管理|应用))", source)
    if match:
        return match.group(1).strip()
    return "业务管理系统"


def _infer_doc_app_code(app_name: str) -> str:
    hints = [
        ("巡检", "insp_mgmt"),
        ("会议", "meeting_req"),
        ("项目", "project_mgmt"),
        ("客户", "crm"),
        ("CRM", "crm"),
        ("财务", "finance_mgmt"),
        ("停车", "parking_mgmt"),
        ("报销", "expense_mgmt"),
        ("请假", "leave_mgmt"),
    ]
    for keyword, code in hints:
        if keyword in app_name:
            return code
    ascii_code = re.sub(r"[^a-zA-Z0-9_]", "_", app_name).strip("_").lower()
    ascii_code = re.sub(r"_+", "_", ascii_code)[:24].strip("_")
    return ascii_code or "app_builder"


def _infer_lowcode_app_code(app_name: str) -> str:
    hints = [
        ("巡检", "insp-mgmt"),
        ("会议", "meeting-req"),
        ("项目", "project-mgmt"),
        ("客户", "crm"),
        ("CRM", "crm"),
        ("财务", "finance-mgmt"),
        ("停车", "parking-mgmt"),
        ("报销", "expense-mgmt"),
        ("请假", "leave-mgmt"),
        ("人事", "hr-mgmt"),
        ("人才", "talent-mgmt"),
        ("员工", "employee-mgmt"),
    ]
    for keyword, code in hints:
        if keyword in app_name:
            return code
    return normalize_app_code(app_name) or "app-builder"


def _infer_unified_app_code(app_name: str) -> str:
    return _infer_lowcode_app_code(app_name)


# ─── app_info / 字段 / 数据类型 ──────────────────────────────────────────────

def _normalize_doc_app_info(raw: Any, messages: list[dict[str, Any]] | None = None) -> dict[str, str]:
    raw = raw if isinstance(raw, dict) else {}
    app_name = str(raw.get("name") or raw.get("app_name") or "").strip() or _infer_doc_app_name(messages)
    raw_code = str(raw.get("code") or raw.get("app_code") or "").strip()
    app_code = normalize_app_code(raw_code) or _infer_lowcode_app_code(app_name)
    description = str(raw.get("description") or "").strip() or f"{app_name}用于承载核心业务数据、流程、权限和后续扩展能力。"
    return {"code": app_code, "name": app_name, "description": description}


def _normalize_doc_data_type(raw_type: Any, field_name: str = "") -> str:
    value = str(raw_type or "").strip()
    if value:
        upper = value.upper()
        allowed = {"VARCHAR", "BIGINT", "INT", "DECIMAL", "DATE", "DATETIME", "TEXT"}
        if upper in allowed:
            return upper.lower()
        if upper in {"TINYINT", "BOOLEAN", "BOOL"}:
            return "int"
        mapping = {
            "单据号": "varchar",
            "单行输入": "varchar",
            "多行输入": "text",
            "富文本": "text",
            "下拉单选": "varchar",
            "下拉多选": "varchar",
            "单选框": "varchar",
            "复选框": "varchar",
            "日期": "date",
            "日期时间": "datetime",
            "时间": "datetime",
            "金额": "decimal",
            "数字": "int",
            # 附件存的是文件 URL/路径字符串，长度可控（≤ 1000 字符），用 varchar
            # 不用 text（text 是 long blob，索引/where 都不友好）
            "附件上传": "varchar",
            # 数据单选 / 数据选择 / 关联表单 存的是被引用记录的编码字符串，varchar
            "数据单选": "varchar",
            "数据选择": "varchar",
            "关联表单": "varchar",
            "人员选择": "varchar",
            "部门选择": "varchar",
            "开关": "int",
        }
        if value in mapping:
            return mapping[value]
    if any(k in field_name for k in ("日期", "时间")):
        return "datetime"
    if any(k in field_name for k in ("金额", "数量", "次数", "评分", "百分比")):
        return "decimal"
    if any(k in field_name for k in ("说明", "描述", "备注", "原因", "内容")):
        return "text"
    return "varchar"


def _field_template(code: str, name: str, data_type: str = "varchar", *, required: bool = False, desc: str = "") -> dict:
    data_type = _normalize_doc_data_type(data_type, name)
    return {
        "field_code": code,
        "field_name": name,
        "data_type": data_type,
        "length": "255" if data_type == "varchar" else "",
        "is_pk": False,
        "is_fk": False,
        "nullable": not required,
        "default_value": "",
        "description": desc or name,
    }


def _default_business_fields(table_name: str) -> list[dict]:
    if "巡检" in table_name or "检查" in table_name:
        return [
            _field_template("inspection_no", "巡检编号", required=True),
            _field_template("inspection_date", "巡检日期", "DATETIME", required=True),
            _field_template("inspection_location", "巡检位置", required=True),
            _field_template("inspection_item", "巡检项目", required=True),
            _field_template("inspection_result", "巡检结果", required=True),
            _field_template("abnormal_desc", "异常说明", "TEXT"),
            _field_template("handler_name", "处理人"),
            _field_template("attachment_desc", "附件说明", "TEXT"),
        ]
    if "会议" in table_name:
        return [
            _field_template("meeting_topic", "会议主题", required=True),
            _field_template("meeting_date", "会议日期", "DATETIME", required=True),
            _field_template("meeting_room", "会议室", required=True),
            _field_template("applicant_name", "报名人", required=True),
            _field_template("participant_count", "参会人数", "INT"),
            _field_template("contact_phone", "联系电话"),
            _field_template("remark", "备注", "TEXT"),
        ]
    return [
        _field_template("record_no", "业务编号", required=True),
        _field_template("title", "标题", required=True),
        _field_template("business_date", "业务日期", "DATETIME", required=True),
        _field_template("owner_name", "负责人"),
        _field_template("department_name", "所属部门"),
        _field_template("business_status", "业务状态"),
        _field_template("attachment_desc", "附件说明", "TEXT"),
        _field_template("remark", "备注", "TEXT"),
    ]


def _normalize_doc_field(field: Any) -> dict | None:
    if not isinstance(field, dict):
        return None
    code = str(field.get("field_code") or field.get("code") or "").strip()
    name = str(field.get("field_name") or field.get("name") or field.get("label") or code).strip()
    if not code or not name:
        return None
    if code.lower() in SYSTEM_FIELD_CODES or field.get("is_pk") is True:
        return None
    return {
        "field_code": code,
        "field_name": name,
        "data_type": _normalize_doc_data_type(field.get("data_type") or field.get("type"), name),
        "length": str(field.get("length") or field.get("max_length") or field.get("maxLength") or ""),
        "is_pk": False,
        "is_fk": bool(field.get("is_fk") or field.get("isFk")),
        "nullable": bool(field.get("nullable", True)),
        "default_value": str(field.get("default_value") or field.get("defaultValue") or ""),
        "description": str(field.get("description") or field.get("comment") or name),
    }


# ─── tables / roles / dicts ────────────────────────────────────────────────

def _normalize_doc_tables(raw_tables: Any, app_info: dict[str, str]) -> list[dict]:
    tables: list[dict] = []
    for idx, raw_table in enumerate(_list_or_empty(raw_tables)):
        if not isinstance(raw_table, dict):
            continue
        table_name = str(raw_table.get("table_name") or raw_table.get("name") or "").strip()
        if not table_name:
            continue
        table_code = str(raw_table.get("table_code") or raw_table.get("code") or "").strip() or f"t_{_infer_doc_app_code(table_name)}"
        if not table_code.startswith("t_"):
            table_code = f"t_{table_code}"
        table_type = str(raw_table.get("table_type") or raw_table.get("type") or "主表").strip() or "主表"
        fields = [f for f in (_normalize_doc_field(item) for item in _list_or_empty(raw_table.get("fields"))) if f]
        used_field_codes: set[str] = set()
        for field in fields:
            field["field_code"] = safe_field_code(
                field.get("field_code"),
                model_code=table_code,
                field_name=str(field.get("field_name") or ""),
                used_codes=used_field_codes,
            )
        seen_codes = {field["field_code"] for field in fields}
        for fallback in _default_business_fields(table_name):
            if len(fields) >= 6:
                break
            fallback["field_code"] = safe_field_code(
                fallback.get("field_code"),
                model_code=table_code,
                field_name=str(fallback.get("field_name") or ""),
                used_codes=used_field_codes,
            )
            if fallback["field_code"] in seen_codes:
                continue
            fields.append(fallback)
            seen_codes.add(fallback["field_code"])
        tables.append({
            "table_code": table_code,
            "table_name": table_name,
            "table_type": table_type,
            "parent_table": str(raw_table.get("parent_table") or raw_table.get("parent_model_code") or "").strip(),
            "description": str(raw_table.get("description") or f"{table_name}的业务数据表"),
            "fields": fields,
        })

    if tables:
        return tables

    entity_name = app_info["name"].replace("系统", "").replace("平台", "").strip() or "业务"
    table_name = f"{entity_name}记录"
    table_code = f"t_{_infer_doc_app_code(table_name)}"
    return [{
        "table_code": table_code,
        "table_name": table_name,
        "table_type": "主表",
        "parent_table": "",
        "description": f"{table_name}主表",
        "fields": _default_business_fields(table_name)[:6],
    }]


def _normalize_doc_roles(raw_roles: Any) -> list[dict[str, str]]:
    roles: list[dict[str, str]] = []
    seen: set[str] = set()
    for idx, raw_role in enumerate(_list_or_empty(raw_roles)):
        if not isinstance(raw_role, dict):
            continue
        code = str(raw_role.get("role_code") or raw_role.get("code") or "").strip()
        name = str(raw_role.get("role_name") or raw_role.get("name") or code).strip()
        if not code:
            code = f"role_{idx + 1}"
        code_lower = code.lower()
        if code_lower in FORBIDDEN_ROLE_CODES:
            continue
        if any(keyword == name or keyword in name for keyword in FORBIDDEN_ROLE_NAME_KEYWORDS):
            continue
        if code_lower in seen or not name:
            continue
        seen.add(code_lower)
        roles.append({
            "role_code": code,
            "role_name": name,
            "description": str(raw_role.get("description") or f"{name}负责对应业务处理和数据维护"),
        })
    if roles:
        return roles
    return [{
        "role_code": "business_admin",
        "role_name": "业务管理员",
        "description": "维护业务配置、查看全量数据并处理异常情况",
    }]


def _normalize_doc_dicts(raw_dicts: Any, tables: list[dict]) -> list[dict]:
    dicts: list[dict] = []
    seen: set[str] = set()
    for idx, raw_dict in enumerate(_list_or_empty(raw_dicts)):
        if not isinstance(raw_dict, dict):
            continue
        code = str(raw_dict.get("dict_code") or raw_dict.get("code") or f"dict_{idx + 1}").strip()
        if code.lower() in {"approval_status", "audit_status", "process_status"} or code in seen:
            continue
        name = str(raw_dict.get("dict_name") or raw_dict.get("name") or code).strip()
        items = []
        for item_idx, raw_item in enumerate(_list_or_empty(raw_dict.get("items") or raw_dict.get("options"))):
            if isinstance(raw_item, dict):
                item_code = str(raw_item.get("item_code") or raw_item.get("code") or f"item_{item_idx + 1}").strip()
                item_name = str(raw_item.get("item_name") or raw_item.get("name") or item_code).strip()
            else:
                item_code = f"item_{item_idx + 1}"
                item_name = str(raw_item).strip()
            if item_name:
                items.append({"item_code": item_code, "item_name": item_name})
        if name and items:
            seen.add(code)
            dicts.append({"dict_code": code, "dict_name": name, "items": items})

    if dicts:
        return dicts

    result_field_name = next(
        (
            field.get("field_name", "")
            for table in tables
            for field in table.get("fields", [])
            if "结果" in field.get("field_name", "")
        ),
        "",
    )
    if result_field_name:
        return [{
            "dict_code": "dict_business_result",
            "dict_name": result_field_name,
            "items": [
                {"item_code": "normal", "item_name": "正常"},
                {"item_code": "abnormal", "item_name": "异常"},
                {"item_code": "pending", "item_name": "待处理"},
            ],
        }]
    return [{
        "dict_code": "dict_business_status",
        "dict_name": "业务状态",
        "items": [
            {"item_code": "draft", "item_name": "草稿"},
            {"item_code": "in_progress", "item_name": "处理中"},
            {"item_code": "completed", "item_name": "已完成"},
            {"item_code": "cancelled", "item_name": "已取消"},
        ],
    }]


# ─── modules / flows / permissions ─────────────────────────────────────────

def _primary_business_role_name(roles: list[dict[str, str]]) -> str:
    return roles[0]["role_name"] if roles else "业务管理员"


def _default_module_features(table_name: str, roles: list[dict[str, str]]) -> list[dict]:
    admin_role = _primary_business_role_name(roles)
    return [
        {
            "name": f"新增{table_name}",
            "description": f"支持用户创建并暂存或提交{table_name}记录。",
            "roles": ["全部员工"],
        },
        {
            "name": f"查看{table_name}",
            "description": f"支持按权限范围查询、查看{table_name}详情和处理状态。",
            "roles": ["全部员工", admin_role],
        },
        {
            "name": f"维护{table_name}",
            "description": f"支持{admin_role}维护{table_name}数据并处理异常或待办事项。",
            "roles": [admin_role],
        },
    ]


def _normalize_doc_modules(raw_modules: Any, tables: list[dict], roles: list[dict[str, str]]) -> list[dict]:
    modules: list[dict] = []
    for idx, raw_module in enumerate(_list_or_empty(raw_modules)):
        if not isinstance(raw_module, dict):
            continue
        name = str(raw_module.get("module_name") or raw_module.get("name") or "").strip()
        if not name:
            continue
        code = str(raw_module.get("module_code") or raw_module.get("code") or _infer_doc_app_code(name)).strip()
        features = []
        for feature_idx, raw_feature in enumerate(_list_or_empty(raw_module.get("features"))):
            if not isinstance(raw_feature, dict):
                continue
            feature_name = str(raw_feature.get("name") or raw_feature.get("feature_name") or f"功能点{feature_idx + 1}").strip()
            features.append({
                "name": feature_name,
                "description": str(raw_feature.get("description") or f"{feature_name}的业务操作"),
                "roles": _list_or_empty(raw_feature.get("roles")) or ["全部员工", _primary_business_role_name(roles)],
            })
        modules.append({
            "module_name": name,
            "module_code": code,
            "description": str(raw_module.get("description") or f"{name}覆盖对应业务对象的日常操作"),
            "features": features,
        })

    module_by_code = {module["module_code"]: module for module in modules}
    for table in tables:
        if str(table.get("table_type", "主表")).lower() in {"子表", "sub", "child"}:
            continue
        table_name = table["table_name"]
        code = table["table_code"].removeprefix("t_")
        if code in module_by_code:
            target = module_by_code[code]
            if len(target.get("features") or []) >= 3:
                continue
            target["features"] = (target.get("features") or []) + _default_module_features(table_name, roles)
            target["features"] = target["features"][:3]
            continue
        modules.append({
            "module_name": f"{table_name}管理",
            "module_code": code,
            "description": f"围绕{table_name}提供新增、查看、维护和处理能力。",
            "features": _default_module_features(table_name, roles),
        })
    return modules


def _normalize_doc_flows(raw_flows: Any, tables: list[dict], roles: list[dict[str, str]]) -> list[dict]:
    flows: list[dict] = []
    for idx, raw_flow in enumerate(_list_or_empty(raw_flows)):
        if not isinstance(raw_flow, dict):
            continue
        name = str(raw_flow.get("flow_name") or raw_flow.get("name") or "").strip()
        if not name:
            continue
        steps = []
        for step_idx, raw_step in enumerate(_list_or_empty(raw_flow.get("steps") or raw_flow.get("nodes"))):
            if not isinstance(raw_step, dict):
                continue
            steps.append({
                "step": raw_step.get("step") or raw_step.get("order") or step_idx + 1,
                "action": str(raw_step.get("action") or raw_step.get("name") or raw_step.get("label") or "").strip(),
                "role": str(raw_step.get("role") or raw_step.get("assignee") or "").strip(),
                "status": str(raw_step.get("status") or raw_step.get("result") or "").strip(),
            })
        if steps:
            flows.append({
                "flow_name": name,
                "flow_code": str(raw_flow.get("flow_code") or raw_flow.get("code") or f"flow_{idx + 1}").strip(),
                "description": str(raw_flow.get("description") or f"{name}用于串联业务提交、处理和归档。"),
                "table_code": str(raw_flow.get("table_code") or "").strip(),
                "steps": steps,
            })

    if flows:
        return flows

    existing_names = {flow["flow_name"] for flow in flows}
    for table in tables:
        if str(table.get("table_type", "主表")).lower() in {"子表", "sub", "child"}:
            continue
        flow_name = f"{table['table_name']}处理流程"
        if flow_name in existing_names:
            continue
        flows.append({
            "flow_name": flow_name,
            "flow_code": f"{table['table_code'].removeprefix('t_')}_flow",
            "description": f"{table['table_name']}从提交、处理到归档的基础业务流程。",
            "table_code": table["table_code"],
            "steps": [
                {"step": 1, "action": f"提交{table['table_name']}", "role": "全部员工", "status": "待处理"},
                {"step": 2, "action": f"处理{table['table_name']}", "role": _primary_business_role_name(roles), "status": "处理中"},
                {"step": 3, "action": "归档完成", "role": "系统", "status": "已完成"},
            ],
        })
    return flows


def _normalize_doc_permissions(raw_mappings: Any, tables: list[dict], roles: list[dict[str, str]]) -> list[dict]:
    existing_by_table: dict[str, dict] = {}
    for raw_mapping in _list_or_empty(raw_mappings):
        if not isinstance(raw_mapping, dict):
            continue
        table_code = str(raw_mapping.get("table_code") or raw_mapping.get("form_code") or "").strip()
        if not table_code:
            continue
        permissions = []
        for raw_perm in _list_or_empty(raw_mapping.get("permissions") or raw_mapping.get("rules")):
            if not isinstance(raw_perm, dict):
                continue
            role_code = str(raw_perm.get("role_code") or raw_perm.get("role") or "").strip()
            role_name = str(raw_perm.get("role_name") or raw_perm.get("name") or role_code).strip()
            if not role_code:
                continue
            operations = raw_perm.get("operations") or raw_perm.get("actions") or []
            if isinstance(operations, str):
                operations = [item.strip() for item in operations.split(",") if item.strip()]
            permissions.append({
                "role_code": role_code,
                "role_name": role_name,
                "operations": operations or ["查看"],
                "data_scope": str(raw_perm.get("data_scope") or raw_perm.get("scope") or raw_perm.get("data") or "self"),
            })
        existing_by_table[table_code] = {
            "table_code": table_code,
            "table_name": str(raw_mapping.get("table_name") or "").strip(),
            "permissions": permissions,
        }

    mappings: list[dict] = []
    for table in tables:
        if str(table.get("table_type", "主表")).lower() in {"子表", "sub", "child"}:
            continue
        table_code = table["table_code"]
        mapping = existing_by_table.get(table_code, {
            "table_code": table_code,
            "table_name": table["table_name"],
            "permissions": [],
        })
        mapping["table_name"] = mapping.get("table_name") or table["table_name"]
        permissions = mapping.get("permissions") or []
        permissions = [perm for perm in permissions if isinstance(perm, dict)]
        permissions = [perm for perm in permissions if perm.get("role_code") != "all_employee"]
        default_permissions = [{
            "role_code": "all_employee",
            "role_name": "全部员工",
            "operations": ["暂存", "新增", "查看", "编辑"],
            "data_scope": "self",
        }]
        existing_role_codes = {perm.get("role_code") for perm in permissions}
        for role in roles:
            if role["role_code"] in existing_role_codes:
                continue
            permissions.append({
                "role_code": role["role_code"],
                "role_name": role["role_name"],
                "operations": ["查看", "编辑", "导出", "查看审批历史"],
                "data_scope": "all",
            })
        mapping["permissions"] = default_permissions + permissions
        mappings.append(mapping)
    return mappings


def _derive_forms_for_doc_result(doc: dict) -> list[dict]:
    existing = doc.get("forms")
    if isinstance(existing, list) and existing:
        return existing
    try:
        from app.services.config_converter import convert_analysis_to_app_config

        return convert_analysis_to_app_config(doc).get("forms") or []
    except Exception as exc:
        logger.warning("derive forms from doc_result failed: %s", exc)
    forms: list[dict] = []
    for table in doc.get("tables", []) or []:
        if str(table.get("table_type", "主表")).lower() in {"子表", "sub", "child"}:
            continue
        table_code = table.get("table_code") or ""
        forms.append({
            "form_name": table.get("table_name") or table_code,
            "form_code": table_code,
            "model_code": table_code,
            "components": [
                {
                    "field_code": field.get("field_code"),
                    "field_name": field.get("field_name"),
                    "label": field.get("field_name"),
                    "modelField": f"{table_code}.{field.get('field_code')}",
                    "componentType": "FORM_TEXT_INPUT",
                    "required": not field.get("nullable", True),
                }
                for field in table.get("fields", []) or []
            ],
        })
    return forms


def _normalize_custom_development_items(doc: dict) -> list[dict[str, str]]:
    source = (
        doc.get("custom_development")
        or doc.get("customDevelopment")
        or doc.get("custom_dev")
        or []
    )
    if isinstance(source, dict):
        source = source.get("items") or source.get("tasks") or source.get("features") or []
    if not isinstance(source, list):
        source = []

    items: list[dict[str, str]] = []
    for idx, item in enumerate(source):
        if not isinstance(item, dict):
            continue
        deliverables = item.get("deliverables") or item.get("deliverable") or ""
        if isinstance(deliverables, list):
            deliverables_text = "、".join(str(v) for v in deliverables if str(v).strip())
        else:
            deliverables_text = str(deliverables or "").strip()
        items.append({
            "type": str(item.get("type") or item.get("scene") or item.get("category") or "自开发扩展").strip(),
            "name": str(item.get("name") or item.get("item_name") or item.get("title") or f"自开发项 {idx + 1}").strip(),
            "trigger": str(item.get("trigger") or item.get("reason") or item.get("condition") or item.get("description") or "配置能力无法完整覆盖").strip(),
            "scope": str(item.get("scope") or item.get("implementation") or deliverables_text or "在 IDE 中实现并回写项目上下文").strip(),
            "acceptance": str(item.get("acceptance") or item.get("acceptance_criteria") or item.get("test") or "完成源码、联调和可演示验证").strip(),
        })

    return items or [{
        "type": "none",
        "name": "暂无强制自开发项",
        "trigger": "当前需求可先由模型、表单、权限和基础流程配置覆盖",
        "scope": "如后续出现复杂交互、外部接口、算法规则或报表看板，再进入 IDE 补充",
        "acceptance": "低代码配置可完成主流程演示",
    }]


# ─── 顶层 API ──────────────────────────────────────────────────────────────

def normalize_doc_result(doc: dict, messages: list[dict[str, Any]] | None = None) -> dict:
    """把模型输出规范化为完整 SPEC，避免缺表单/流程时仍被当成完成态。"""
    source = doc if isinstance(doc, dict) else {}
    normalized = dict(source)
    app_info = _normalize_doc_app_info(source.get("app_info"), messages)
    roles = _normalize_doc_roles(source.get("roles"))
    tables = _normalize_doc_tables(source.get("tables") or source.get("models"), app_info)
    dicts = _normalize_doc_dicts(source.get("data_dictionary") or source.get("dicts"), tables)
    normalized.update({
        "app_info": app_info,
        "roles": roles,
        "data_dictionary": dicts,
        "tables": tables,
    })
    normalized["modules"] = _normalize_doc_modules(source.get("modules"), tables, roles)
    normalized["flows"] = _normalize_doc_flows(source.get("flows") or source.get("workflows"), tables, roles)
    normalized["role_table_mapping"] = _normalize_doc_permissions(
        source.get("role_table_mapping") or source.get("permissions"),
        tables,
        roles,
    )
    normalized["custom_development"] = _normalize_custom_development_items(source)
    normalized["forms"] = _derive_forms_for_doc_result(normalized)
    return normalized


def is_valid_doc_result(doc: dict) -> bool:
    """完整结构校验，避免把半成品 SPEC 误存为 doc_result。"""
    if not isinstance(doc, dict):
        return False
    if not isinstance(doc.get("app_info"), dict):
        return False
    if any(not isinstance(doc.get(key), list) for key in DOC_REQUIRED_LIST_KEYS):
        return False
    main_tables = [
        table for table in doc.get("tables", [])
        if isinstance(table, dict) and str(table.get("table_type", "主表")).lower() not in {"子表", "sub", "child"}
    ]
    if not main_tables:
        return False
    if not doc.get("forms") or not doc.get("modules") or not doc.get("flows") or not doc.get("role_table_mapping"):
        return False
    return all(len(table.get("fields") or []) >= 6 for table in main_tables)


# ─── Markdown 渲染 ─────────────────────────────────────────────────────────

def json_to_markdown(data: dict) -> str:
    """Convert requirements JSON into the standard parseable design-doc MD."""

    def cell(value: Any) -> str:
        text = str(value or "").replace("\r\n", "\n").replace("\n", "<br>")
        return text.replace("|", "\\|").strip()

    def yes_no(value: Any, default: bool = False) -> str:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"是", "yes", "true", "1", "y"}:
                return "是"
            if normalized in {"否", "no", "false", "0", "n"}:
                return "否"
        return "是" if bool(value) else ("是" if default else "否")

    def component_label(value: Any, field: dict | None = None) -> str:
        raw = str(value or "").strip()
        mapping = {
            "FORM_TEXT_INPUT": "单行输入",
            "FORM_TEXTAREA": "多行输入",
            "FORM_SELECT": "下拉单选",
            "FORM_MULTI_SELECT": "下拉多选",
            "FORM_DATE_PICKER": "日期",
            "FORM_DATETIME_PICKER": "日期时间",
            "FORM_NUMBER_INPUT": "数字",
            "FORM_UPLOAD": "附件上传",
            "FORM_USER_SELECT": "人员选择",
            "FORM_DEPT_SELECT": "部门选择",
            "FORM_SWITCH": "开关",
            "FORM_RADIO": "单选框",
            "FORM_CHECKBOX": "复选框",
        }
        if raw in mapping:
            return mapping[raw]
        if raw:
            return raw
        data_type = str((field or {}).get("data_type") or "").upper()
        field_name = str((field or {}).get("field_name") or "")
        if data_type in {"DATE", "DATETIME"} or any(key in field_name for key in ("日期", "时间")):
            return "日期时间" if data_type == "DATETIME" else "日期"
        if data_type in {"INT", "BIGINT", "DECIMAL"}:
            return "数字"
        if data_type == "TEXT" or any(key in field_name for key in ("说明", "描述", "备注", "原因", "内容")):
            return "多行输入"
        return "单行输入"

    def scope_label(value: Any) -> str:
        return {
            "none": "无权限",
            "self": "仅本人",
            "dept": "本部门",
            "all": "全公司",
            "custom": "自定义",
            "SELF": "仅本人",
            "CURRENT_USER_DEPT": "本部门",
            "ALL": "全公司",
        }.get(str(value or "").strip(), str(value or "").strip() or "无权限")

    def permission_flag(operations: list, *keywords: str) -> str:
        ops = {str(op).strip() for op in (operations or [])}
        return "是" if any(keyword in ops for keyword in keywords) else "否"

    app_info = data.get("app_info") or {}
    tables = [table for table in (data.get("tables") or []) if isinstance(table, dict)]
    forms = [form for form in (data.get("forms") or []) if isinstance(form, dict)]
    table_by_code = {str(table.get("table_code") or "").strip(): table for table in tables}

    lines: list[str] = []
    lines.append(f"# {cell(app_info.get('name') or '功能设计文档')}")
    lines.append("")

    lines.append("## 一、应用信息")
    lines.append("")
    lines.append("| 应用名称 | 应用编码 | 说明 |")
    lines.append("|---|---|---|")
    lines.append(f"| {cell(app_info.get('name'))} | {cell(app_info.get('code'))} | {cell(app_info.get('description'))} |")
    lines.append("")

    lines.append("## 二、角色列表")
    lines.append("")
    lines.append("| 角色编码 | 角色名称 | 职责说明 |")
    lines.append("|---|---|---|")
    for role in data.get("roles") or []:
        if not isinstance(role, dict):
            continue
        lines.append(f"| {cell(role.get('role_code'))} | {cell(role.get('role_name'))} | {cell(role.get('description'))} |")
    lines.append("")

    lines.append("## 三、数据字典")
    lines.append("")
    dicts = [item for item in (data.get("data_dictionary") or []) if isinstance(item, dict)]
    if dicts:
        for dictionary in dicts:
            lines.append(f"### {cell(dictionary.get('dict_name'))}（{cell(dictionary.get('dict_code'))}）")
            lines.append("")
            lines.append("| 选项编码 | 选项名称 |")
            lines.append("|---|---|")
            for item in dictionary.get("items") or []:
                if isinstance(item, dict):
                    lines.append(f"| {cell(item.get('item_code'))} | {cell(item.get('item_name'))} |")
            lines.append("")
    else:
        lines.append("暂无数据字典。")
        lines.append("")

    lines.append("## 四、数据模型")
    lines.append("")
    lines.append("### 4.1 模型定义")
    lines.append("")
    lines.append("| 模型编码 | 模型名称 | 类型 | 所属主表模型编码 | 说明 |")
    lines.append("|---|---|---|---|---|")
    for table in tables:
        lines.append(
            "| "
            f"{cell(table.get('table_code'))} | "
            f"{cell(table.get('table_name'))} | "
            f"{cell(table.get('table_type') or '主表')} | "
            f"{cell(table.get('parent_table'))} | "
            f"{cell(table.get('description'))} |"
        )
    lines.append("")
    lines.append("### 4.2 模型字段")
    lines.append("")
    lines.append("| 模型编码 | 字段编码 | 字段名称 | 字段类型 | 数据库字段类型 | 长度/精度 | 必填 | 字典编码 | 关联模型编码 | 关联显示字段编码 | 说明 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for table in tables:
        table_code = str(table.get("table_code") or "").strip()
        for field in table.get("fields") or []:
            if not isinstance(field, dict):
                continue
            data_type = field.get("data_type") or field.get("database_field_type") or ""
            lines.append(
                "| "
                f"{cell(table_code)} | "
                f"{cell(field.get('field_code'))} | "
                f"{cell(field.get('field_name'))} | "
                f"{cell(component_label('', field))} | "
                f"{cell(data_type)} | "
                f"{cell(field.get('length'))} | "
                f"{yes_no(not field.get('nullable', True))} | "
                f"{cell(field.get('dict_code') or field.get('dict'))} | "
                f"{cell(field.get('ref_model') or field.get('target_model_code'))} | "
                f"{cell(field.get('ref_field') or field.get('target_field_code'))} | "
                f"{cell(field.get('description'))} |"
            )
    lines.append("")

    lines.append("## 五、表单定义")
    lines.append("")
    lines.append("### 5.1 表单清单")
    lines.append("")
    lines.append("| 表单编码 | 表单名称 | 绑定主表模型 | 说明 |")
    lines.append("|---|---|---|---|")
    if forms:
        for form in forms:
            form_code = form.get("form_code") or form.get("code") or form.get("model_code") or form.get("modelCode")
            form_name = form.get("form_name") or form.get("name") or form_code
            model_code = form.get("model_code") or form.get("modelCode") or form_code
            lines.append(f"| {cell(form_code)} | {cell(form_name)} | {cell(model_code)} | {cell(form.get('description'))} |")
    else:
        for table in tables:
            if str(table.get("table_type", "主表")).lower() in {"子表", "sub", "child"}:
                continue
            lines.append(f"| {cell(table.get('table_code'))} | {cell(table.get('table_name'))} | {cell(table.get('table_code'))} | {cell(table.get('description'))} |")
    lines.append("")

    lines.append("### 5.2 主表字段定义")
    lines.append("")
    lines.append("| 表单名称 | 字段编码 | 字段名称 | 组件类型 | 必填 | 隐藏 | 只读 | 列表展示 | 查询条件 | 字典编码 | 目标模型编码 | 目标字段编码 | 本表关联字段编码 | 说明 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    if forms:
        for form in forms:
            form_name = str(form.get("form_name") or form.get("name") or form.get("form_code") or "").strip()
            model_code = str(form.get("model_code") or form.get("modelCode") or form.get("form_code") or "").strip()
            model_fields = {
                str(field.get("field_code") or "").strip(): field
                for field in (table_by_code.get(model_code, {}).get("fields") or [])
                if isinstance(field, dict)
            }
            components = form.get("components") or []
            for component in components:
                if not isinstance(component, dict):
                    continue
                section_type = str(component.get("section_type") or component.get("sectionType") or "main").lower()
                if section_type == "sub":
                    continue
                field_code = str(component.get("field_code") or component.get("code") or "").strip()
                field = model_fields.get(field_code, {})
                lines.append(
                    "| "
                    f"{cell(form_name)} | "
                    f"{cell(field_code)} | "
                    f"{cell(component.get('field_name') or component.get('label') or field.get('field_name'))} | "
                    f"{cell(component_label(component.get('component_type') or component.get('componentType'), field))} | "
                    f"{yes_no(component.get('required'))} | "
                    f"{yes_no(component.get('hidden'))} | "
                    f"{yes_no(component.get('readonly'))} | "
                    f"{yes_no(component.get('show_in_list') if 'show_in_list' in component else component.get('showInList'))} | "
                    f"{yes_no(component.get('searchable'))} | "
                    f"{cell(component.get('dict_code') or component.get('dict'))} | "
                    f"{cell(component.get('target_model_code') or component.get('targetModelCode'))} | "
                    f"{cell(component.get('target_field_code') or component.get('targetFieldCode'))} | "
                    f"{cell(component.get('origin_field_code') or component.get('originFieldCode'))} | "
                    f"{cell(component.get('description'))} |"
                )
    else:
        for table in tables:
            if str(table.get("table_type", "主表")).lower() in {"子表", "sub", "child"}:
                continue
            for field in table.get("fields") or []:
                if isinstance(field, dict):
                    lines.append(
                        f"| {cell(table.get('table_name'))} | {cell(field.get('field_code'))} | {cell(field.get('field_name'))} | "
                        f"{cell(component_label('', field))} | {yes_no(not field.get('nullable', True))} | 否 | 否 | 是 | 否 | "
                        f"{cell(field.get('dict_code') or field.get('dict'))} |  |  |  | {cell(field.get('description'))} |"
                    )
    lines.append("")

    lines.append("### 5.3 子表区域定义")
    lines.append("")
    lines.append("| 表单名称 | 子表区域名称 | 绑定模型 | 说明 |")
    lines.append("|---|---|---|---|")
    has_subtable = False
    for table in tables:
        if str(table.get("table_type", "")).lower() in {"子表", "sub", "child"}:
            has_subtable = True
            parent = str(table.get("parent_table") or "").strip()
            parent_name = next(
                (item.get("table_name") for item in tables if item.get("table_code") == parent),
                parent,
            )
            lines.append(f"| {cell(parent_name)} | {cell(table.get('table_name'))} | {cell(table.get('table_code'))} | {cell(table.get('description'))} |")
    if not has_subtable:
        lines.append("|  |  |  | 暂无子表结构 |")
    lines.append("")

    lines.append("### 5.4 子表字段定义")
    lines.append("")
    lines.append("| 表单名称 | 子表区域名称 | 字段编码 | 字段名称 | 组件类型 | 必填 | 隐藏 | 只读 | 列表展示 | 字典编码 | 说明 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    if has_subtable:
        for table in tables:
            if str(table.get("table_type", "")).lower() not in {"子表", "sub", "child"}:
                continue
            parent = str(table.get("parent_table") or "").strip()
            parent_name = next(
                (item.get("table_name") for item in tables if item.get("table_code") == parent),
                parent,
            )
            for field in table.get("fields") or []:
                if isinstance(field, dict):
                    lines.append(
                        f"| {cell(parent_name)} | {cell(table.get('table_name'))} | {cell(field.get('field_code'))} | "
                        f"{cell(field.get('field_name'))} | {cell(component_label('', field))} | {yes_no(not field.get('nullable', True))} | "
                        f"否 | 否 | 是 | {cell(field.get('dict_code') or field.get('dict'))} | {cell(field.get('description'))} |"
                    )
    else:
        lines.append("|  |  |  |  |  | 否 | 否 | 否 | 否 |  | 暂无子表字段 |")
    lines.append("")

    lines.append("## 六、流程配置")
    lines.append("")
    flows = [flow for flow in (data.get("flows") or []) if isinstance(flow, dict)]
    if flows:
        for flow in flows:
            lines.append(f"### {cell(flow.get('flow_name'))}（{cell(flow.get('flow_code'))}）")
            lines.append("")
            if flow.get("description"):
                lines.append(cell(flow.get("description")))
                lines.append("")
            lines.append("| 步骤 | 动作 | 角色 | 状态/结果 |")
            lines.append("|---|---|---|---|")
            for step in flow.get("steps") or []:
                if isinstance(step, dict):
                    lines.append(f"| {cell(step.get('step'))} | {cell(step.get('action'))} | {cell(step.get('role'))} | {cell(step.get('status'))} |")
            lines.append("")
    else:
        lines.append("暂无流程配置。")
        lines.append("")

    lines.append("## 七、权限定义")
    lines.append("")
    lines.append("| 表单名称 | 角色编码 | 可暂存 | 可新增 | 可导入 | 可查看 | 可编辑 | 可删除 | 可导出 | 数据范围 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for mapping in data.get("role_table_mapping") or []:
        if not isinstance(mapping, dict):
            continue
        form_name = mapping.get("table_name") or mapping.get("form_name") or mapping.get("table_code")
        for permission in mapping.get("permissions") or []:
            if not isinstance(permission, dict):
                continue
            operations = permission.get("operations") or []
            lines.append(
                "| "
                f"{cell(form_name)} | "
                f"{cell(permission.get('role_code'))} | "
                f"{permission_flag(operations, '暂存')} | "
                f"{permission_flag(operations, '新增', '复制新建')} | "
                f"{permission_flag(operations, '导入')} | "
                f"{permission_flag(operations, '查看', '查看审批历史')} | "
                f"{permission_flag(operations, '编辑')} | "
                f"{permission_flag(operations, '删除', '批量删除')} | "
                f"{permission_flag(operations, '导出')} | "
                f"{scope_label(permission.get('data_scope'))} |"
            )
    lines.append("")
    lines.append("> 自开发内容不在本次配置文档中生成；后续如需复杂组件、外部接口或 Hook，请从 Vibe Coding/IDE 入口单独处理。")
    lines.append("")

    return "\n".join(lines)
