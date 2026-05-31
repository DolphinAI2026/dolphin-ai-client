"""设计文档标准格式（Builder 流水线唯一可解析的 markdown 规范）。

doc_pipeline 的"整篇标准化兜底"和 ai_chat agent 的"生成文档"
都引用这一份说明，确保两边产出能被 doc_pipeline 直接解析、不需要 LLM 兜底。

本规范与 design-doc-template.md 保持一致：6 章主结构、数据模型只描述存储、
字典/组件/引用统一在表单定义里表达。
"""

from typing import Dict, List


SECTION_DEFS: List[Dict] = [
    {"key": "app_info", "title": "## 一、应用信息", "required": True, "display": "应用信息"},
    {"key": "roles", "title": "## 二、角色列表", "required": False, "display": "角色列表"},
    {"key": "dicts", "title": "## 三、数据字典", "required": False, "display": "数据字典"},
    {"key": "models", "title": "## 四、数据模型", "required": True, "display": "数据模型"},
    {"key": "forms", "title": "## 五、表单定义", "required": False, "display": "表单定义"},
    {"key": "workflows", "title": "## 六、流程配置", "required": False, "display": "流程配置"},
    {"key": "permissions", "title": "## 七、权限定义", "required": True, "display": "权限定义"},
]
SECTION_KEY_TO_DISPLAY = {s["key"]: s["display"] for s in SECTION_DEFS}

STANDARD_HEADERS_FULL: Dict[str, List[str]] = {
    "app_info": ["项目", "内容"],
    "roles": ["角色编码", "角色名称"],
    "dicts_head": ["字典编码", "字典名称"],
    "dicts_option": ["选项编码", "选项名称"],
    "models_def": ["模型编码", "模型名称"],
    "models_field": ["模型编码", "字段编码", "字段名称", "数据库字段类型", "长度/精度"],
    "forms_list": ["表单编码", "表单名称", "绑定主表模型", "说明"],
    "forms_main": [
        "表单名称", "字段编码", "字段名称", "组件类型", "必填", "隐藏", "只读",
        "列表展示", "查询条件", "字典编码", "目标模型编码", "目标字段编码",
        "本表关联字段编码", "说明",
    ],
    "forms_sub_def": ["表单名称", "子表区域名称", "绑定模型", "说明"],
    "forms_sub": [
        "表单名称", "子表区域名称", "字段编码", "字段名称", "组件类型", "必填",
        "隐藏", "只读", "列表展示", "查询条件", "字典编码", "目标模型编码",
        "目标字段编码", "本表关联字段编码", "说明",
    ],
    "workflows": ["流程名称", "关联表单", "步骤", "动作", "审批角色", "状态/结果"],
    "permissions": [
        "表单名称", "角色编码/授权对象", "可暂存", "可新增", "可导入", "可查看",
        "可编辑", "可删除", "可导出", "数据范围",
    ],
}

STANDARD_HEADERS_REQUIRED: Dict[str, List[str]] = {
    "app_info": ["应用编码", "应用名称"],
    "roles": ["角色编码", "角色名称"],
    "dicts_option": ["选项编码", "选项名称"],
    "models": ["字段编码", "字段名称"],
    "forms": ["字段编码", "字段名称"],
    "permissions": ["表单名称", "可查看", "可编辑", "可删除", "数据范围"],
}

COMPONENT_TYPES_PRIMARY: List[str] = [
    "单据号", "单行输入", "多行输入", "手机号码", "电子邮箱",
    "下拉单选", "下拉多选", "数据单选", "数据选择", "关联表单",
    "日期时间", "金额", "数字", "附件上传", "开关",
    "人员选择", "部门选择", "地理位置", "地区地址", "子表",
    "单选框", "复选框", "富文本", "超链接", "身份证号",
]

COMPONENT_TYPES_ALIAS: Dict[str, str] = {
    "数字输入": "数字",
    "数据多选": "数据选择",
    "证件号": "身份证号",
    "布尔": "开关",
    "签名": "单行输入",
    "多选框": "复选框",
}

DB_FIELD_TYPES: List[str] = ["varchar", "text", "datetime", "date", "decimal", "int", "bigint"]
DATA_SCOPES: List[str] = ["全部数据", "本人数据", "本部门", "本部门及下属部门"]
DICT_BOUND_COMPONENTS = {"下拉单选", "下拉多选", "单选框", "复选框"}
REF_BOUND_COMPONENTS = {"数据单选", "数据选择", "关联表单"}
RESERVED_PROCESS_FIELDS: List[str] = [
    "approver_id", "approver", "approval_status", "approval_time", "approval_note",
    "applicant_id", "applicant", "audit_status", "process_status", "approval_user_id",
]
RESERVED_GENERIC_NAMES: List[str] = [
    "name", "title", "status", "type", "level", "department", "user",
    "phone", "email", "manager", "result", "remark", "description", "content",
]
NAMING_RULES: Dict[str, Dict] = {
    "app_code": {
        "regex": r"^[a-z][a-z0-9-]{0,16}$",
        "desc": "kebab-case，仅小写字母 + 数字 + `-`，字母开头，长度 ≤ 17",
        "examples_ok": ["sales-order", "equip-mgmt", "oms"],
    },
    "snake_code": {
        "regex": r"^[a-z][a-z0-9_]*$",
        "desc": "snake_case，仅小写字母 + 数字 + `_`，字母开头",
        "applies_to": ["角色编码", "字典编码", "选项编码", "模型编码", "字段编码", "表单编码"],
    },
}


# 章节顺序 + 表头 + 字段约束。任何"产出 md 设计文档"的 LLM 调用都应当注入这段。
STANDARD_DOC_FORMAT = """\
# 标准格式要求

文档建议按照以下章节顺序输出。角色列表、流程配置可省略；应用信息、数据模型、权限定义必须明确。每个章节的表头列名必须与下面给出的列名**逐字一致**，不要新增、删除或改字。

章节标题用 `# / ## / ### ` 任意层级都可识别，下面示例统一用 `## `；子章节（如 4.1 / 5.2、字典子项 3.1）建议用 `### ` 三级。**关键是章节标题里要含中文编号 + 章节名**（`一、应用信息`、`二、角色列表`...）。

## 一、应用信息
键值表，列：`项目 | 内容`，且必须包含三行：`应用名称`、`应用编码`、`说明`。

| 项目 | 内容 |
|---------|---------|
| 应用名称 | 销售订单 |
| 应用编码 | sales-order |
| 说明 | 销售订单录入、查询与权限管理 |

## 二、角色列表
可选章节。需要按角色授权时表格列：`角色编码 | 角色名称`。如果权限统一给全部人员，可以省略本章节。

角色只描述本应用独立的业务权限边界。不要创建 `employee`、`dept_supervisor`、`direct_manager`、`sys_admin`，也不要把普通员工、部门主管、直属上级、部门/人员管理建成角色；这些属于平台内置组织能力。需要应用管理员时，角色编码必须带应用语义或应用前缀，例如 `meeting_admin`、`meet_mgmt_admin`，不要使用泛化的 `sys_admin`。业务表单需要部门归属时，在表单字段中添加"所属部门"并使用部门选择。

## 三、数据字典
每个字典一个 `### N.M 字典名` 子章节（**用 `### ` 三级**），每个子章节包含**两张表**：
1. 字典头表，列：`字典编码 | 字典名称`
2. 选项表，列：`选项编码 | 选项名称`

## 四、数据模型
> 数据模型只描述数据库如何存储。**不要**在本章节表达：必填、组件类型、字典绑定、目标模型编码、列表展示、查询条件、隐藏、只读、主表/子表。这些都属于「五、表单定义」。

### 4.1 模型定义
表格列：`模型编码 | 模型名称`

### 4.2 模型字段（全部模型字段平铺到一张大表）
表格列：`模型编码 | 字段编码 | 字段名称 | 数据库字段类型 | 长度/精度`

## 五、表单定义
> 对普通字段、数据单选、数据选择，`字段编码`对应模型字段编码。
> 对关联表单，`字段编码`表示组件编码，**不要求**在数据模型中存在。
> 主/子表关系、组件类型、必填、字典绑定、关联引用都属于本章节。

### 5.1 表单清单
表格列：`表单编码 | 表单名称 | 绑定主表模型 | 说明`

### 5.2 主表字段定义
表格列（共 14 列，**列序与列名都不要变**）：
`表单名称 | 字段编码 | 字段名称 | 组件类型 | 必填 | 隐藏 | 只读 | 列表展示 | 查询条件 | 字典编码 | 目标模型编码 | 目标字段编码 | 本表关联字段编码 | 说明`

### 5.3 子表区域定义（无子表可省略本小节）
表格列：`表单名称 | 子表区域名称 | 绑定模型 | 说明`

### 5.4 子表字段定义（无子表可省略本小节）
表格列（共 15 列，与 5.2 一致再加`子表区域名称`）：
`表单名称 | 子表区域名称 | 字段编码 | 字段名称 | 组件类型 | 必填 | 隐藏 | 只读 | 列表展示 | 查询条件 | 字典编码 | 目标模型编码 | 目标字段编码 | 本表关联字段编码 | 说明`

## 六、流程配置
可选章节。用户提到审批/流转时必须输出；没有审批流时可省略。表格列：
`流程名称 | 关联表单 | 步骤 | 动作 | 审批角色 | 状态/结果`

| 流程名称 | 关联表单 | 步骤 | 动作 | 审批角色 | 状态/结果 |
|---------|---------|---------|---------|---------|---------|
| 订单审批流程 | 销售订单 | 1 | 提交订单 | 销售专员 | 待审批 |
| 订单审批流程 | 销售订单 | 2 | 审批订单 | 销售主管 | 已通过/已驳回 |

## 七、权限定义
表格列：`表单名称 | 角色编码 | 可暂存 | 可新增 | 可导入 | 可查看 | 可编辑 | 可删除 | 可导出 | 数据范围`

`角色编码`列支持填写具体角色编码，也支持填写 `全部人员` 表示授权给所有用户；写 `全部人员` 时不需要定义角色列表。

审批中的部门负责人、直属上级属于平台组织审批规则，只能出现在流程配置的"审批角色"列中，例如"发起人所属部门负责人"，不要写入角色列表。

# 字段约束

### 编码字段
- **应用编码（appCode）**：kebab-case，**只允许小写字母 / 数字 / 中划线 `-`**，必须以**小写字母开头**，**长度 ≤ 17 字符**。匹配正则 `^[a-z][a-z0-9-]{0,16}$`。例如 `sales-order`、`equip-mgmt`、`oms`。**禁止使用下划线 `_`**、中文、空格或其他字符；超过 17 字符必须缩写（如 `power-equipment-management` ❌ → `power-equip-mgmt` ✓）
- **角色编码 / 字典编码 / 模型编码 / 字段编码 / 表单编码**：snake_case，仅小写字母 + 数字 + 下划线，字母开头
- 通用短名禁止直接使用：`name / title / status / type / level / department / user / phone / email / manager / result / remark / description / content`，必须加业务前缀（如 `supplier_name`、`order_status`）

### 数据库字段类型（仅以下取值）
`varchar / text / datetime / date / decimal / int / bigint`

**类型选择规则（重要）**：
- **附件上传字段** → 必须用 `varchar`（存文件 URL/路径字符串），**不要**用 `text`
- **数据单选 / 数据选择 / 关联表单** → 必须用 `varchar`（存被引用的编码字符串），**不要**用 `text`
- **下拉单选 / 下拉多选 / 单选框 / 复选框** → 必须用 `varchar`（存字典编码）
- 仅当字段是**多行长文本**（说明 / 描述 / 备注 / 详情正文）时才用 `text`

### 表单组件类型（仅以下取值）
`单据号 / 单行输入 / 多行输入 / 手机号码 / 电子邮箱 / 下拉单选 / 下拉多选 / 数据单选 / 数据选择 / 日期时间 / 金额 / 数字 / 附件上传 / 开关 / 人员选择 / 部门选择 / 地理位置 / 子表 / 单选框 / 复选框 / 富文本 / 超链接 / 身份证号 / 地区地址 / 关联表单`
（兼容写法：`数字输入 / 数据多选 / 证件号 / 布尔 / 签名` 也可识别，但请尽量用主名称）

### 数据范围（仅以下取值）
`全部数据 / 本人数据 / 本部门 / 本部门及下属部门`

### 职责分离 ‼️
- 数据模型表只写"字段在数据库怎么存"，**不要**写字典编码、目标模型编码、组件类型
- 字典绑定、组件类型、引用关系一律写到「五、表单定义」里
- `下拉单选 / 下拉多选 / 单选框 / 复选框` 必须在 5.2 / 5.4 的`字典编码`列填写已在第三章定义的字典编码
- `数据单选 / 数据选择 / 关联表单` 必须在 5.2 / 5.4 的`目标模型编码`列填写已在第四章定义的模型编码；`目标字段编码`填该模型上要展示的字段编码
- `关联表单`的`本表关联字段编码`指向当前表单的某个字段，用来从目标模型筛选关联数据
- 子表通过 5.3 子表区域定义声明（`绑定模型`必须在第四章定义），其字段配置写到 5.4，不要把子表当主表字段写到 5.2

### 内容约束
- 不要凭空捏造，原文/对话没有的内容不要新增
- 缺失信息留空单元格（**不要**填"未知"、"待定"、"未定义"等占位文字）；表头必须存在
- 即使没有任何数据字典 / 子表 / 权限，对应章节也要保留表头，不要整段省略
"""


def build_template_spec() -> Dict:
    return {
        "spec_version": "2026-05-23",
        "sections": [
            {
                "order": idx + 1,
                "key": s["key"],
                "title_example": s["title"],
                "display_name": s["display"],
                "required": s["required"],
            }
            for idx, s in enumerate(SECTION_DEFS)
        ],
        "table_headers_full": {k: list(v) for k, v in STANDARD_HEADERS_FULL.items()},
        "table_headers_required": {k: list(v) for k, v in STANDARD_HEADERS_REQUIRED.items()},
        "component_types": list(COMPONENT_TYPES_PRIMARY),
        "component_type_aliases": dict(COMPONENT_TYPES_ALIAS),
        "db_field_types": list(DB_FIELD_TYPES),
        "data_scopes": list(DATA_SCOPES),
        "dict_bound_components": sorted(DICT_BOUND_COMPONENTS),
        "ref_bound_components": sorted(REF_BOUND_COMPONENTS),
        "naming_rules": {k: dict(v) for k, v in NAMING_RULES.items()},
        "reserved_process_fields": list(RESERVED_PROCESS_FIELDS),
        "reserved_generic_names": list(RESERVED_GENERIC_NAMES),
        "permission_subjects": {
            "all_users": ["全部人员", "全员", "所有人", "所有用户", "all", "*", "ALL_USER"],
            "role_code": "填写角色编码时，建议同时提供二、角色列表",
        },
        "standard_doc_format_md": STANDARD_DOC_FORMAT,
    }
