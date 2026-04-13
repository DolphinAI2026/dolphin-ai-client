"""解析功能设计文档 (.md) → preview JSON 格式"""
from __future__ import annotations
import hashlib
import re
from typing import List, Dict, Optional


def _to_ascii_code(text: str) -> str:
    """将任意文本转为纯 ASCII 编码，用于生成 code。
    先提取已有的 ASCII 字母数字，如果结果为空则用短哈希替代。"""
    ascii_part = re.sub(r'[^a-zA-Z0-9]', '_', text)
    ascii_part = re.sub(r'_+', '_', ascii_part).strip('_').lower()
    # 如果提取到的纯ASCII部分太短（全中文场景），用 hash 生成
    if len(ascii_part.replace('_', '')) < 2:
        ascii_part = 'c' + hashlib.md5(text.encode()).hexdigest()[:7]
    return ascii_part


# 组件类型中文 → preview type 映射
_COMPONENT_MAP = {
    '单据号': '单据号', '单行输入': '单行输入', '多行输入': '多行输入',
    '手机号码': '手机号码', '电子邮箱': '电子邮箱',
    '下拉单选': '下拉单选', '下拉框': '下拉多选', '下拉多选': '下拉多选',
    '数据单选': '数据单选', '日期时间': '日期时间',
    '金额': '金额', '数字输入': '数字', '数字': '数字',
    '附件上传': '附件上传', '开关': '开关',
    '人员选择': '人员选择', '定位': '地理位置',
}

_ICON_MAP = {
    '单据号': '#', '单行输入': 'T', '多行输入': '¶',
    '手机号码': '📱', '电子邮箱': '✉', '下拉单选': '▼',
    '下拉多选': '☰', '数据单选': '🔗', '日期时间': '📅',
    '金额': '💰', '数字': '123', '附件上传': '📎',
    '开关': '⊘', '人员选择': '👤', '地理位置': '📍', '子表': '▦',
}


def _parse_table(text: str) -> List[Dict[str, str]]:
    """Parse a markdown table into list of dicts."""
    lines = [l.strip() for l in text.strip().split('\n') if l.strip()]
    table_lines = [l for l in lines if l.startswith('|')]
    if len(table_lines) < 3:
        return []
    header = [c.strip() for c in table_lines[0].split('|')[1:-1]]
    rows = []
    for line in table_lines[2:]:  # skip header + separator
        cells = [c.strip() for c in line.split('|')[1:-1]]
        if len(cells) >= len(header):
            rows.append({header[i]: cells[i] for i in range(len(header))})
    return rows


def _extract_model_code(title: str) -> str:
    """从标题提取模型 code，如 '客户主数据（Customer）' → 'customer'"""
    m = re.search(r'[（(]([a-zA-Z]\w*)[）)]', title)
    return m.group(1).lower() if m else _to_ascii_code(title)


def _extract_form_name(title: str) -> str:
    """从标题提取表单名，如 '表单一：客户主数据（Customer）' → '客户主数据'"""
    m = re.search(r'[：:]\s*(.+?)(?:[（(]|$)', title)
    return m.group(1).strip() if m else title


def _parse_dict_ref(field_setting: str) -> Optional[str]:
    """从字段设置中提取字典 code，如 '字典：region' → 'region'"""
    m = re.search(r'字典[：:]\s*(\S+)', field_setting)
    if not m:
        return None
    raw = m.group(1).strip()
    # 确保 code 是纯 ASCII
    if re.search(r'[^\x00-\x7f]', raw):
        return _to_ascii_code(raw)
    return raw


def _parse_form_ref(row: Dict[str, str]) -> Optional[Dict[str, str]]:
    """从引用表单名称/字段提取 ref 信息"""
    ref_form = row.get('引用表单名称', '').strip()
    ref_field = row.get('引用表单字段', '').strip()
    if ref_form and ref_form != '-':
        ref_code = _extract_model_code(ref_form)
        return {"model": ref_code, "field": ref_field}
    return None


def _build_field(row: Dict[str, str], is_sub: bool = False) -> Dict:
    """将一行字段定义转为 preview field 格式"""
    raw_comp = row.get('组件类型', '单行输入').strip()
    comp_type = _COMPONENT_MAP.get(raw_comp, '单行输入')
    icon = _ICON_MAP.get(comp_type, 'T')

    field: Dict = {
        "name": row.get('字段名称', row.get('子表字段', '')).strip(),
        "type": comp_type,
        "icon": icon,
    }

    # required
    rules = row.get('业务规则', '')
    if '必填' in rules:
        field["required"] = True

    # dict
    setting = row.get('字段设置', '')
    dict_code = _parse_dict_ref(setting)
    if dict_code:
        field["dict"] = dict_code

    # ref (数据单选)
    ref = _parse_form_ref(row)
    if ref:
        field["ref"] = ref

    # field code from 备注 column
    remark = row.get('备注', '').strip()
    if remark and remark != '-' and not remark.startswith('（'):
        raw_code = remark.split('（')[0].split('(')[0].strip()
        field["code"] = re.sub(r'[^a-zA-Z0-9_]', '_', raw_code)

    return field


def _parse_roles(text: str) -> List[Dict]:
    """解析角色表"""
    rows = _parse_table(text)
    return [
        {"code": row.get('角色编码', '').strip(), "name": row.get('角色名称', '').strip()}
        for row in rows if row.get('角色编码', '').strip()
    ]


def _parse_dicts(text: str) -> List[Dict]:
    """解析字典配置区域"""
    dicts = []
    # 按 <dictionary-N> 分割
    dict_blocks = re.split(r'<dictionary-\d+>', text)
    for block in dict_blocks:
        if not block.strip():
            continue
        # 提取字典名和 code
        title_m = re.search(r'###\s*(.+?)(?:[（(](\S+?)[）)])', block)
        if not title_m:
            continue
        dict_name = title_m.group(1).strip()
        raw_code = title_m.group(2).strip()
        dict_code = raw_code if re.match(r'^[a-zA-Z]\w*$', raw_code) else _to_ascii_code(raw_code)
        rows = _parse_table(block)
        options = []
        for row in rows:
            opt_name = row.get('选项名称', '').strip()
            opt_code = row.get('选项编码', '').strip()
            if opt_name and opt_code:
                options.append({"name": opt_name, "code": opt_code})
        if options:
            dicts.append({"name": dict_name, "code": dict_code, "options": options})
    return dicts


def _parse_workflows(form_block: str, form_name: str) -> Optional[Dict]:
    """解析流程配置"""
    proc_m = re.search(r'<business-form-processConfig-\d+>(.*?)</business-form-processConfig-\d+>', form_block, re.DOTALL)
    if not proc_m:
        return None
    rows = _parse_table(proc_m.group(1))
    if not rows:
        return None
    nodes = []
    for row in rows:
        node_name = row.get('审批节点', '').strip()
        role = row.get('审批人名称', '').strip()
        node_type = 'approve'
        if node_name == '开始':
            node_type = 'start'
        elif node_name == '结束':
            node_type = 'end'
        nodes.append({"name": node_name, "role": role, "type": node_type})
    return {"name": f"{form_name}流程", "form": form_name, "nodes": nodes}


def _parse_permissions(form_block: str, form_name: str) -> Optional[Dict]:
    """解析权限设计"""
    perm_m = re.search(r'<business-form-permission-\d+>(.*?)</business-form-permission-\d+>', form_block, re.DOTALL)
    if not perm_m:
        return None
    rows = _parse_table(perm_m.group(1))
    if not rows:
        return None
    rules = []
    for row in rows:
        rules.append({
            "role": row.get('权限对象', '').strip(),
            "op": row.get('权限设置', '').strip(),
            "data": row.get('权限范围', '').strip(),
        })
    return {"form": form_name, "rules": rules}


def _parse_sub_tables(form_block: str, base_code: str) -> list:
    """解析子表设计区域，返回子表字段列表"""
    sub_tables = []
    # 匹配 <business-form-son-table-N-M> 块
    pattern = r'<business-form-son-table-\d+-\d+>(.*?)</business-form-son-table-\d+-\d+>'
    for m in re.finditer(pattern, form_block, re.DOTALL):
        block = m.group(1)
        # 提取子表名称
        title_m = re.search(r'###\s*(.+)', block)
        sub_name = title_m.group(1).strip() if title_m else '子表'
        rows = _parse_table(block)
        if not rows:
            continue
        sub_fields = [_build_field(row, is_sub=True) for row in rows]
        sub_tables.append({
            "name": sub_name,
            "sub_code": f"{base_code}_sub",
            "sub_fields": sub_fields,
        })
    return sub_tables


def _infer_field_type(type_str: str) -> str:
    """从文档中的类型描述推断 preview 字段类型"""
    t = type_str.strip().replace('（', '(').replace('）', ')')
    # 去掉括号内容用于匹配
    t_base = re.sub(r'\(.*?\)', '', t).strip()

    mapping = {
        '文本': '单行输入', '单行': '单行输入', '文本输入': '单行输入',
        '长文本': '多行输入', '多行文本': '多行输入', '多行': '多行输入', '大文本': '多行输入',
        '数字': '数字', '数值': '数字', '整数': '数字',
        '金额': '金额',
        '日期': '日期时间', '时间': '日期时间', '日期时间': '日期时间',
        '部门选择': '部门选择', '部门': '部门选择',
        '单选': '下拉单选', '下拉': '下拉单选', '下拉单选': '下拉单选', '选择': '下拉单选',
        '多选': '下拉多选', '下拉多选': '下拉多选',
        '人员选择': '人员选择', '人员': '人员选择', '多人选择': '人员选择',
        '附件': '附件上传', '文件': '附件上传', '上传': '附件上传',
        '开关': '开关', '是否': '开关',
        '关联': '数据单选', '关联品牌': '数据单选',
        '自动编号': '单据号', '编号': '单据号',
        '角色选择': '人员选择',
    }

    # 精确匹配
    if t_base in mapping:
        return mapping[t_base]

    # 包含匹配
    for key, val in mapping.items():
        if key in t_base:
            return val

    # 计算字段/状态 → 单行输入
    if '自动' in t or '计算' in t or '状态' in t:
        return '单行输入'

    return '单行输入'


def _parse_generic_md(content: str) -> dict:
    """通用 Markdown 格式解析：识别 ### 标题 + 字段表格"""
    models: list = []
    dicts: list = []
    roles: list = []
    dict_codes: set = set()

    # 按 ### 分割章节
    sections = re.split(r'\n(?=###\s)', content)

    for section in sections:
        # 匹配 ### X.X 表单名 格式的标题
        title_m = re.match(r'###\s+(\d+\.\d+)\s+(.+)', section)
        if not title_m:
            continue

        section_num = title_m.group(1)
        section_name = title_m.group(2).strip()

        # 跳过纯说明性章节（没有字段表格的）
        # 检查是否有 | 字段名称 | 开头的表格
        if '| 字段名称' not in section and '| 字段名' not in section:
            # 也检查是否有枚举值定义（可作为字典）
            _extract_inline_dicts(section, section_name, dicts, dict_codes)
            continue

        form_name = re.sub(r'[（(].*?[）)]', '', section_name).strip()
        model_code = _extract_model_code(section_name)

        # 可能有多个表格（按 #### 分区）
        # 分成子区块
        sub_sections = re.split(r'\n(?=####\s)', section)

        all_fields = []
        sub_table_fields = []
        is_sub_table = False

        for sub in sub_sections:
            # 检查子区块标题是否暗示子表
            sub_title_m = re.match(r'####\s+(.+)', sub)
            sub_title = sub_title_m.group(1).strip() if sub_title_m else ''

            # 解析表格
            rows = _parse_table(sub)
            if not rows:
                continue

            # 检查表头是否包含字段名称列
            first_row = rows[0]
            if '字段名称' not in first_row and '字段名' not in first_row:
                continue

            # 如果子标题包含"可多行"、"子表"、"明细"等关键词，作为子表处理
            is_sub = any(kw in sub_title for kw in ['多行', '子表', '明细', '多SKU'])

            for row in rows:
                field_name = (row.get('字段名称') or row.get('字段名', '')).strip()
                if not field_name:
                    continue

                type_str = (row.get('类型') or row.get('字段类型', '文本')).strip()
                required_str = (row.get('必填') or row.get('是否必填', '')).strip()
                desc_str = (row.get('字段说明') or row.get('说明', '')).strip()

                field_type = _infer_field_type(type_str)
                icon = _ICON_MAP.get(field_type, 'T')

                field: Dict = {
                    "name": field_name,
                    "type": field_type,
                    "icon": icon,
                }

                if '必填' in required_str or '★' in required_str:
                    field["required"] = True

                # 从类型或说明中提取枚举值 → 自动生成字典
                enum_values = _extract_enum_from_desc(desc_str, type_str)
                if enum_values and field_type in ('下拉单选', '下拉多选'):
                    dict_code = f"dict_{_to_ascii_code(model_code)}_{_to_ascii_code(field_name)}"
                    if dict_code not in dict_codes:
                        dict_codes.add(dict_code)
                        dicts.append({
                            "name": field_name,
                            "code": dict_code,
                            "options": [{"name": v, "code": f"opt_{i}"} for i, v in enumerate(enum_values)]
                        })
                    field["dict"] = dict_code

                if is_sub:
                    sub_table_fields.append(field)
                else:
                    all_fields.append(field)

        # 如果有子表字段，添加为子表组件
        if sub_table_fields:
            all_fields.append({
                "name": f"{form_name}明细",
                "type": "子表",
                "icon": "▦",
                "sub_code": f"{model_code}_sub",
                "sub_fields": sub_table_fields,
            })

        if all_fields:
            models.append({
                "name": form_name,
                "code": model_code,
                "fields": all_fields,
            })

        # 提取内联枚举/字典
        _extract_inline_dicts(section, section_name, dicts, dict_codes)

    # 从文档中提取角色信息
    role_m = re.search(r'系统角色.*?[：:]\s*(.+?)(?:\n|$)', content)
    if role_m:
        role_names = re.split(r'\s*/\s*', role_m.group(1).strip())
        for rn in role_names:
            rn = rn.strip()
            if rn:
                role_code = re.sub(r'[^a-zA-Z0-9]', '_', rn)
                roles.append({"name": rn, "code": role_code})

    # 推断应用名
    app_name = '业务应用'
    title_m = re.search(r'^#\s+(.+?)(?:\s*[—–-]|$)', content, re.MULTILINE)
    if title_m:
        app_name = title_m.group(1).strip()

    return {
        "type": "preview",
        "data": {
            "appName": app_name,
            "roles": roles,
            "dicts": dicts,
            "models": models,
            "workflows": [],
            "permissions": [],
        }
    }


def _extract_enum_from_desc(desc: str, type_str: str) -> List[str]:
    """从字段说明中提取枚举选项"""
    # 匹配 "如 A/B/C" 或 "A/B/C" 格式
    for text in [desc, type_str]:
        m = re.search(r'(?:如|见|：|:)?\s*([\u4e00-\u9fff\w]+(?:\s*/\s*[\u4e00-\u9fff\w]+){2,})', text)
        if m:
            return [v.strip() for v in m.group(1).split('/') if v.strip()]
    return []


def _extract_inline_dicts(section: str, section_name: str, dicts: list, dict_codes: set):
    """从文档段落中提取内联的枚举值定义"""
    # 匹配 **枚举值（已确认）**：A / B / C
    for m in re.finditer(r'\*\*(.+?)\*\*\s*[：:]\s*([\u4e00-\u9fff\w]+(?:\s*/\s*[\u4e00-\u9fff\w/]+)+)', section):
        label = m.group(1).strip()
        values = [v.strip() for v in m.group(2).split('/') if v.strip()]
        if len(values) >= 2:
            dict_code = f"dict_{_to_ascii_code(label)}"
            if dict_code not in dict_codes:
                dict_codes.add(dict_code)
                # 从 label 中提取更友好的名称
                dict_name = re.sub(r'[（(].*?[）)]', '', label).strip()
                dicts.append({
                    "name": dict_name,
                    "code": dict_code,
                    "options": [{"name": v, "code": f"opt_{i}"} for i, v in enumerate(values)]
                })


def parse_design_doc(content: str) -> dict:
    """解析功能设计文档 → preview JSON 格式

    支持两种文档格式：
    1. XML 标签格式（<business-form-N> 等）
    2. 通用 Markdown 格式（### X.X 标题 + 字段表格）

    返回: {"type": "preview", "data": {"appName", "roles", "dicts", "models", "workflows", "permissions"}}
    """
    roles: list = []
    dicts: list = []
    models: list = []
    workflows: list = []
    permissions: list = []

    # 1. 解析公共配置（角色 + 字典）— XML 标签模式
    pub_m = re.search(r'<publicConfig>(.*?)</publicConfig>', content, re.DOTALL)
    if pub_m:
        pub_block = pub_m.group(1)
        roles_m = re.search(r'<roles>(.*?)</roles>', pub_block, re.DOTALL)
        if roles_m:
            roles = _parse_roles(roles_m.group(1))
        dicts_m = re.search(r'<dictionarys>(.*?)</dictionarys>', pub_block, re.DOTALL)
        if dicts_m:
            dicts = _parse_dicts(dicts_m.group(1))

    all_dict_codes = {d['code'] for d in dicts}

    # 2. 解析业务表单 — XML 标签模式
    form_pattern = r'<business-form-(\d+)>(.*?)</business-form-\1>'
    for fm in re.finditer(form_pattern, content, re.DOTALL):
        form_idx = fm.group(1)
        form_block = fm.group(2)

        title_m = re.search(r'##\s*表单.+?[：:]\s*(.+)', form_block)
        if not title_m:
            continue
        full_title = title_m.group(1).strip()
        form_name = _extract_form_name('：' + full_title)
        model_code = _extract_model_code(full_title)

        main_m = re.search(
            rf'<business-form-main-table-{form_idx}>(.*?)</business-form-main-table-{form_idx}>',
            form_block, re.DOTALL
        )
        fields = []
        if main_m:
            rows = _parse_table(main_m.group(1))
            fields = [_build_field(row) for row in rows]

        sub_tables = _parse_sub_tables(form_block, model_code)
        for st in sub_tables:
            fields.append({
                "name": st["name"],
                "type": "子表",
                "icon": "▦",
                "sub_code": st["sub_code"],
                "sub_fields": st["sub_fields"],
            })

        models.append({"name": form_name, "code": model_code, "fields": fields})

        wf = _parse_workflows(form_block, form_name)
        if wf:
            workflows.append(wf)
        perm = _parse_permissions(form_block, form_name)
        if perm:
            permissions.append(perm)

    # 3. 如果 XML 模式没解析到 models，尝试通用 Markdown 格式
    if not models:
        result = _parse_generic_md(content)
        return result

    # 补全字典引用（确保 code 为纯 ASCII）
    for m in models:
        for f in m.get("fields", []):
            dc = f.get("dict")
            if dc and re.search(r'[^\x00-\x7f]', dc):
                dc = _to_ascii_code(dc)
                f["dict"] = dc
            if dc and dc not in all_dict_codes:
                all_dict_codes.add(dc)
                dict_name = f.get("name", dc)
                dicts.append({"name": dict_name, "code": dc, "options": []})
            for sf in f.get("sub_fields", []):
                sdc = sf.get("dict")
                if sdc and re.search(r'[^\x00-\x7f]', sdc):
                    sdc = _to_ascii_code(sdc)
                    sf["dict"] = sdc
                if sdc and sdc not in all_dict_codes:
                    all_dict_codes.add(sdc)
                    dict_name = sf.get("name", sdc)
                    dicts.append({"name": dict_name, "code": sdc, "options": []})

    app_name = '应用'
    if models:
        title_m = re.search(r'#\s*(.+?)(?:\n|$)', content)
        if title_m and '表单' not in title_m.group(1):
            app_name = title_m.group(1).strip()
        else:
            app_name = '业务应用'

    return {
        "type": "preview",
        "data": {
            "appName": app_name,
            "roles": roles,
            "dicts": dicts,
            "models": models,
            "workflows": workflows,
            "permissions": permissions,
        }
    }
