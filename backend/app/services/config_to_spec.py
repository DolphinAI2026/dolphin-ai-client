"""config_preview JSON → markdown 需求文档

将 config_preview 格式的 JSON 转换为标准应用设计文档模板格式。
参照 /Users/mars/Desktop/标准应用设计文档模板.md 的结构输出。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


# 字段类型 → 数据库字段类型
_TYPE_TO_DB: Dict[str, str] = {
    "单行输入": "VARCHAR",
    "手机号码": "VARCHAR",
    "电子邮箱": "VARCHAR",
    "单据号": "VARCHAR",
    "超链接": "VARCHAR",
    "身份证号": "VARCHAR",
    "多行输入": "TEXT",
    "富文本": "TEXT",
    "日期时间": "DATETIME",
    "数字": "DOUBLE",
    "金额": "DOUBLE",
    "人员选择": "BIGINT",
    "部门选择": "BIGINT",
    "开关": "VARCHAR",
    "下拉单选": "VARCHAR",
    "下拉多选": "VARCHAR",
    "单选框": "VARCHAR",
    "复选框": "VARCHAR",
    "附件上传": "VARCHAR",
    "地理位置": "VARCHAR",
    "地区地址": "VARCHAR",
    "数据单选": "BIGINT",
    "数据选择": "VARCHAR",
    "关联表单": "BIGINT",
}

# 字段类型 → 默认长度
_TYPE_TO_LENGTH: Dict[str, str] = {
    "VARCHAR": "200",
    "TEXT": "",
    "DATETIME": "",
    "DOUBLE": "",
    "BIGINT": "",
}

# 字段类型 → 组件类型名称
_TYPE_TO_COMPONENT: Dict[str, str] = {
    "单行输入": "单行输入",
    "多行输入": "多行输入",
    "手机号码": "手机号码",
    "电子邮箱": "电子邮箱",
    "单据号": "单据号",
    "下拉单选": "下拉单选",
    "下拉多选": "下拉多选",
    "数据单选": "数据单选",
    "日期时间": "日期时间",
    "金额": "金额",
    "数字": "数字",
    "附件上传": "附件上传",
    "开关": "开关",
    "人员选择": "人员选择",
    "部门选择": "部门选择",
    "富文本": "富文本",
    "单选框": "单选框",
    "复选框": "复选框",
    "超链接": "超链接",
    "身份证号": "身份证号",
    "地理位置": "地理位置",
    "地区地址": "地区地址",
    "数据选择": "数据选择",
    "关联表单": "关联表单",
}


def config_to_markdown(
    config: dict,
    app_description: str = "",
) -> str:
    """将 config_preview JSON 转换为标准应用设计文档。"""
    data = config.get("data", config)
    app_name = data.get("appName", "未命名应用")
    app_code = data.get("appCode", "")
    roles = data.get("roles", [])
    dicts = data.get("dicts", [])
    models = data.get("models", [])
    workflows = data.get("workflows", [])
    permissions = data.get("permissions", [])

    lines: List[str] = []

    # ── 1. 应用信息 ──
    lines.append(f"# {app_name}")
    lines.append("")
    lines.append("## 1. 应用信息")
    lines.append("")
    lines.append("| 项目 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| 应用编码 | {app_code or app_name} |")
    lines.append(f"| 应用名称 | {app_name} |")
    if app_description:
        lines.append(f"| 描述 | {app_description} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ── 2. 角色列表 ──
    lines.append("## 2. 角色列表")
    lines.append("")
    lines.append("| 角色编码 | 角色名称 | 职责说明 |")
    lines.append("|---|---|---|")
    for r in roles:
        lines.append(f"| {r.get('code', '')} | {r.get('name', '')} | |")
    if not roles:
        lines.append("| | | |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ── 3. 数据字典 ──
    lines.append("## 3. 数据字典")
    lines.append("")
    for i, d in enumerate(dicts, 1):
        dict_name = d.get("name", "")
        dict_code = d.get("code", "")
        options = d.get("options", [])
        lines.append(f"### 3.{i} {dict_name}")
        lines.append("")
        lines.append("| 字典编码 | 字典名称 |")
        lines.append("|---|---|")
        lines.append(f"| {dict_code} | {dict_name} |")
        lines.append("")
        if options:
            lines.append("| 选项编码 | 选项名称 |")
            lines.append("|---|---|")
            for opt in options:
                lines.append(f"| {opt.get('code', '')} | {opt.get('name', '')} |")
            lines.append("")
    if not dicts:
        lines.append("暂无数据字典")
        lines.append("")
    lines.append("---")
    lines.append("")

    # ── 4. 数据模型 ──
    lines.append("## 4. 数据模型")
    lines.append("")

    # 收集子表 code
    sub_codes: Dict[str, str] = {}  # sub_code → parent model_code
    for m in models:
        for f in m.get("fields", []):
            if f.get("type") == "子表" and f.get("sub_code"):
                sub_codes[f["sub_code"]] = m.get("code", "")

    model_idx = 0
    for m in models:
        model_name = m.get("name", "")
        model_code = m.get("code", "")
        is_sub = model_code in sub_codes
        model_idx += 1
        tag = "子表" if is_sub else "主表"

        lines.append(f"### 4.{model_idx} {tag}：{model_name}")
        lines.append("")

        # 模型元信息表
        if is_sub:
            lines.append("| 模型编码 | 模型名称 | 类型 | 所属主表模型编码 |")
            lines.append("|---|---|---|---|")
            lines.append(f"| {model_code} | {model_name} | 子表 | {sub_codes[model_code]} |")
        else:
            lines.append("| 模型编码 | 模型名称 | 类型 |")
            lines.append("|---|---|---|")
            lines.append(f"| {model_code} | {model_name} | 主表 |")
        lines.append("")

        # 普通字段
        regular_fields = [
            f for f in m.get("fields", []) if f.get("type") != "子表"
        ]
        if regular_fields:
            lines.append("| 字段编码 | 字段名称 | 数据库字段类型 | 长度/精度 | 必填 | 字典编码 | 关联模型编码 | 关联显示字段编码 | 说明 |")
            lines.append("|---|---|---|---|---|---|---|---|---|")
            for f in regular_fields:
                lines.append(_format_field_row(f))
            lines.append("")

        # 内嵌子表字段 → 单独的模型段落
        sub_fields_list = [
            f for f in m.get("fields", []) if f.get("type") == "子表"
        ]
        for sf in sub_fields_list:
            sub_name = sf.get("name", "")
            sub_code = sf.get("sub_code", "")
            sub_fields = sf.get("sub_fields", [])
            if sub_fields:
                model_idx += 1
                lines.append(f"### 4.{model_idx} 子表：{sub_name}")
                lines.append("")
                lines.append("| 模型编码 | 模型名称 | 类型 | 所属主表模型编码 |")
                lines.append("|---|---|---|---|")
                lines.append(f"| {sub_code} | {sub_name} | 子表 | {model_code} |")
                lines.append("")
                lines.append("| 字段编码 | 字段名称 | 数据库字段类型 | 长度/精度 | 必填 | 字典编码 | 关联模型编码 | 关联显示字段编码 | 说明 |")
                lines.append("|---|---|---|---|---|---|---|---|---|")
                for sf_item in sub_fields:
                    lines.append(_format_field_row(sf_item))
                lines.append("")

    lines.append("---")
    lines.append("")

    # ── 5. 表单配置 ──
    lines.append("## 5. 表单配置")
    lines.append("")

    form_idx = 0
    for m in models:
        model_name = m.get("name", "")
        model_code = m.get("code", "")
        if model_code in sub_codes:
            continue  # 子表不单独生成表单

        form_idx += 1
        form_code = f"form_{model_code}"
        lines.append(f"### 5.{form_idx} 表单：{model_name}")
        lines.append("")
        lines.append("| 表单编码 | 表单名称 | 绑定主表模型编码 |")
        lines.append("|---|---|---|")
        lines.append(f"| {form_code} | {model_name} | {model_code} |")
        lines.append("")

        # 主表字段组件
        regular_fields = [
            f for f in m.get("fields", []) if f.get("type") != "子表"
        ]
        if regular_fields:
            lines.append(f"#### 5.{form_idx}.1 主表字段组件")
            lines.append("")
            lines.append("| 字段编码 | 字段名称 | 组件类型 | 是否只读 | 是否列表展示 | 是否查询条件 | 说明 |")
            lines.append("|---|---|---|---|---|---|---|")
            for f in regular_fields:
                lines.append(_format_form_field_row(f))
            lines.append("")

        # 子表区域
        sub_table_fields = [
            f for f in m.get("fields", []) if f.get("type") == "子表"
        ]
        if sub_table_fields:
            lines.append(f"#### 5.{form_idx}.2 子表区域")
            lines.append("")
            for sf in sub_table_fields:
                sub_name = sf.get("name", "")
                sub_code = sf.get("sub_code", "")
                lines.append("| 子表模型编码 | 子表模型名称 | 子表显示名称 |")
                lines.append("|---|---|---|")
                lines.append(f"| {sub_code} | {sub_name} | {sub_name} |")
                lines.append("")
                sub_fields = sf.get("sub_fields", [])
                if sub_fields:
                    lines.append("| 子表字段编码 | 子表字段名称 | 组件类型 | 是否必填 | 说明 |")
                    lines.append("|---|---|---|---|---|")
                    for sf_item in sub_fields:
                        ft = sf_item.get("type", "单行输入")
                        comp = _TYPE_TO_COMPONENT.get(ft, ft)
                        req = "是" if sf_item.get("required") else "否"
                        desc = _build_field_desc(sf_item)
                        lines.append(f"| {sf_item.get('code', '')} | {sf_item.get('name', '')} | {comp} | {req} | {desc} |")
                    lines.append("")

    lines.append("---")
    lines.append("")

    # ── 6. 权限配置 ──
    lines.append("## 6. 权限配置")
    lines.append("")
    lines.append("### 6.1 表单权限")
    lines.append("")

    if permissions:
        lines.append("| 表单编码 | 角色编码 | 可暂存 | 可新增 | 可导入 | 可查看 | 可编辑 | 可删除 | 可导出 | 数据范围 |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        for p in permissions:
            form_name = p.get("form", "")
            # 找到对应 model code 生成 form_code
            form_code = ""
            for m in models:
                if m.get("name") == form_name:
                    form_code = f"form_{m.get('code', '')}"
                    break
            if not form_code:
                form_code = f"form_{form_name}"

            for rule in p.get("rules", []):
                role = rule.get("role", "")
                op = rule.get("op", "")
                data_scope = rule.get("data", "ALL")

                ops = set(op.split(",")) if op else set()
                can_save = "是" if "暂存" in ops else "否"
                can_add = "是" if ("新增" in ops or "add" in ops or op == "all") else "否"
                can_import = "是" if ("导入" in ops or "import" in ops) else "否"
                can_view = "是" if ("查看" in ops or "view" in ops or op == "all") else "否"
                can_edit = "是" if ("编辑" in ops or "edit" in ops or op == "all") else "否"
                can_delete = "是" if ("删除" in ops or "delete" in ops or op == "all") else "否"
                can_export = "是" if ("导出" in ops or "export" in ops) else "否"

                scope_label = {
                    "ALL": "全公司",
                    "SELF": "仅本人",
                    "CURRENT_USER_DEPT": "本部门",
                    "CURRENT_USER_DEPT_LOW_LEVEL": "本部门及下属部门",
                }.get(data_scope, data_scope)

                lines.append(
                    f"| {form_code} | {role} | {can_save} | {can_add} | {can_import} | {can_view} | {can_edit} | {can_delete} | {can_export} | {scope_label} |"
                )
        lines.append("")
    else:
        lines.append("暂无权限配置")
        lines.append("")

    return "\n".join(lines)


def _format_field_row(field: dict) -> str:
    """格式化数据模型字段行"""
    code = field.get("code", "")
    name = field.get("name", "")
    field_type = field.get("type", "单行输入")
    required = "是" if field.get("required") else "否"

    db_type = _TYPE_TO_DB.get(field_type, "VARCHAR")
    length = _TYPE_TO_LENGTH.get(db_type, "")
    if db_type == "VARCHAR":
        length = "200"

    dict_code = field.get("dict", "")
    ref = field.get("ref")
    ref_model = ref.get("model", "") if ref else ""
    ref_field = ref.get("field", "") if ref else ""

    # 关联类型强制 BIGINT
    if ref_model:
        db_type = "BIGINT"
        length = ""

    desc = _build_field_desc(field)

    return f"| {code} | {name} | {db_type} | {length} | {required} | {dict_code} | {ref_model} | {ref_field} | {desc} |"


def _format_form_field_row(field: dict) -> str:
    """格式化表单配置字段行"""
    code = field.get("code", "")
    name = field.get("name", "")
    field_type = field.get("type", "单行输入")
    comp = _TYPE_TO_COMPONENT.get(field_type, field_type)
    desc = _build_field_desc(field)

    return f"| {code} | {name} | {comp} | 否 | 是 | 否 | {desc} |"


def _build_field_desc(field: dict) -> str:
    """构建字段说明"""
    parts: List[str] = []
    field_type = field.get("type", "")

    if field_type == "单据号":
        parts.append("自动编号")
    if field_type == "开关":
        parts.append("TRUE/FALSE")
    if field_type == "附件上传":
        parts.append("文件上传")

    dict_code = field.get("dict", "")
    if dict_code:
        parts.append(f"关联字典 {dict_code}")

    ref = field.get("ref")
    if ref:
        parts.append(f"关联 {ref.get('model', '')}")

    return "；".join(parts)
