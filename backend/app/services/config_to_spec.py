"""config_preview JSON → markdown 需求文档

将 config_preview 格式的 JSON 转换为结构化的 markdown 需求文档，
格式与手写规格文档一致（如：项目管理系统.md、供应商管理系统.md）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


# 字段类型 → 数据库数据类型
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

# 权限操作 → 可读名称
_OP_LABELS: Dict[str, str] = {
    "all": "新增、编辑、删除、查看",
    "add": "新增",
    "edit": "编辑",
    "delete": "删除",
    "view": "查看",
}

# 数据范围 → 可读名称
_DATA_LABELS: Dict[str, str] = {
    "ALL": "全公司",
    "SELF": "仅本人",
    "CURRENT_USER_DEPT": "本部门",
    "CURRENT_USER_DEPT_LOW_LEVEL": "本部门及下属部门",
    "ALL_USER": "全部人员",
}


def config_to_markdown(
    config: dict,
    app_description: str = "",
) -> str:
    """将 config_preview JSON 转换为 markdown 需求文档。

    Args:
        config: config_preview dict（可带 "data" wrapper 或直接平铺）
        app_description: 应用描述（可选）

    Returns:
        格式化的 markdown 文本
    """
    data = config.get("data", config)
    app_name = data.get("appName", "未命名应用")
    app_code = data.get("appCode", "")
    roles = data.get("roles", [])
    dicts = data.get("dicts", [])
    models = data.get("models", [])
    workflows = data.get("workflows", [])
    permissions = data.get("permissions", [])

    lines: List[str] = []

    # 一、应用信息
    lines.append(f"# {app_name}")
    lines.append("")
    lines.append("## 一、应用信息")
    lines.append("")
    if app_code:
        lines.append(f"- **应用编码**：{app_code}")
    lines.append(f"- **应用名称**：{app_name}")
    if app_description:
        lines.append(f"- **描述**：{app_description}")
    lines.append("")

    # 二、角色清单
    if roles:
        lines.append("## 二、角色清单")
        lines.append("")
        lines.append("| 角色编码 | 角色名称 |")
        lines.append("|---------|---------|")
        for r in roles:
            lines.append(f"| {r.get('code', '')} | {r.get('name', '')} |")
        lines.append("")

    # 三、数据字典
    if dicts:
        lines.append("## 三、数据字典")
        lines.append("")
        for d in dicts:
            dict_name = d.get("name", "")
            dict_code = d.get("code", "")
            lines.append(f"### {dict_name}（{dict_code}）")
            lines.append("")
            lines.append("| 编码 | 名称 |")
            lines.append("|------|------|")
            for opt in d.get("options", []):
                lines.append(f"| {opt.get('code', '')} | {opt.get('name', '')} |")
            lines.append("")

    # 四、表结构
    if models:
        lines.append("## 四、表结构")
        lines.append("")

        # 收集子表 code → 标记
        sub_codes = set()
        for m in models:
            for f in m.get("fields", []):
                if f.get("sub_code"):
                    sub_codes.add(f["sub_code"])

        for m in models:
            model_name = m.get("name", "")
            model_code = m.get("code", "")
            is_sub = model_code in sub_codes
            tag = "子表" if is_sub else "主表"

            lines.append(f"### {model_name}（{model_code}）【{tag}】")
            lines.append("")

            # 普通字段
            regular_fields = [
                f for f in m.get("fields", [])
                if f.get("type") != "子表"
            ]
            # 子表字段
            sub_table_fields = [
                f for f in m.get("fields", [])
                if f.get("type") == "子表"
            ]

            if regular_fields:
                lines.append(
                    "| 字段编码 | 字段名称 | 数据类型 | 可空 | 描述 |"
                )
                lines.append(
                    "|---------|---------|---------|------|------|"
                )
                for f in regular_fields:
                    lines.append(_format_field_row(f, dicts))
                lines.append("")

            # 子表展开为独立表结构
            for sf in sub_table_fields:
                sub_name = sf.get("name", "")
                sub_code = sf.get("sub_code", "")
                sub_fields = sf.get("sub_fields", [])
                lines.append(f"### {sub_name}（{sub_code}）【子表】")
                lines.append("")
                if sub_fields:
                    lines.append(
                        "| 字段编码 | 字段名称 | 数据类型 | 可空 | 描述 |"
                    )
                    lines.append(
                        "|---------|---------|---------|------|------|"
                    )
                    for sf_item in sub_fields:
                        lines.append(_format_field_row(sf_item, dicts))
                    lines.append("")

    # 五、审批流程
    if workflows:
        lines.append("## 五、审批流程")
        lines.append("")
        for wf in workflows:
            wf_name = wf.get("name", "")
            wf_form = wf.get("form", "")
            lines.append(f"### {wf_name}（关联表单：{wf_form}）")
            lines.append("")
            nodes = wf.get("nodes", [])
            if nodes:
                lines.append("| 节点名称 | 类型 | 角色 |")
                lines.append("|---------|------|------|")
                for n in nodes:
                    node_type = n.get("type", "")
                    type_label = {
                        "start": "发起",
                        "approve": "审批",
                        "end": "结束",
                    }.get(node_type, node_type)
                    lines.append(
                        f"| {n.get('name', '')} | {type_label} | {n.get('role', '')} |"
                    )
                lines.append("")

    # 六、角色权限矩阵
    section_num = "六" if workflows else "五"
    if permissions:
        lines.append(f"## {section_num}、角色权限矩阵")
        lines.append("")
        for p in permissions:
            form_name = p.get("form", "")
            rules = p.get("rules", [])
            lines.append(f"### {form_name}")
            lines.append("")
            lines.append("| 角色 | 操作权限 | 数据范围 |")
            lines.append("|------|---------|---------|")
            for rule in rules:
                role = rule.get("role", "")
                op = rule.get("op", "")
                data_scope = rule.get("data", "")

                # 格式化操作权限
                op_label = _OP_LABELS.get(op, op)
                # 格式化数据范围
                data_label = _DATA_LABELS.get(data_scope, data_scope)

                lines.append(f"| {role} | {op_label} | {data_label} |")
            lines.append("")

    return "\n".join(lines)


def _format_field_row(field: dict, dicts: List[dict]) -> str:
    """格式化单个字段为表格行"""
    code = field.get("code", "")
    name = field.get("name", "")
    field_type = field.get("type", "单行输入")
    required = field.get("required", False)
    nullable = "否" if required else "是"

    db_type = _TYPE_TO_DB.get(field_type, "VARCHAR")

    # 构建描述
    desc_parts: List[str] = []

    # 字典关联
    dict_code = field.get("dict", "")
    if dict_code:
        desc_parts.append(f"关联字典 {dict_code}")
        if field_type == "下拉多选":
            desc_parts.append("多选")

    # 关联模型
    ref = field.get("ref")
    if ref:
        desc_parts.append(f"关联 {ref.get('model', '')}（{ref.get('field', '')}）")
        db_type = "BIGINT"

    # 人员/部门选择
    if field_type in ("人员选择", "部门选择"):
        db_type = "BIGINT"
        desc_parts.append("外键")

    # 开关
    if field_type == "开关":
        desc_parts.append("TRUE/FALSE")

    # 附件
    if field_type == "附件上传":
        desc_parts.append("文件上传组件")

    # 单据号
    if field_type == "单据号":
        desc_parts.append("自动编号")

    desc = "，".join(desc_parts) if desc_parts else field_type

    return f"| {code} | {name} | {db_type} | {nullable} | {desc} |"
