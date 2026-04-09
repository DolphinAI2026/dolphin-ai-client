"""文档标准度检测器

对上传的 markdown 文档打分，决定走哪条解析路径：
  pure_code      → 直接纯代码解析
  hybrid_fallback → 纯代码主解析 + 失败模块 LLM 修复
  rewrite_first  → 先 LLM 整篇标准化，再纯代码解析
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Set

from app.doc_section_splitter import split_sections, detect_section_headers, split_subsections
from app.doc_table_parser import find_tables, _split_row, _is_separator


# ── 评分权重 ──────────────────────────────────────────────────
_WEIGHTS = {
    "section_coverage": 30,   # 必填章节覆盖率
    "header_format": 15,      # 章节标题格式
    "table_header_match": 25, # 表头匹配率
    "code_compliance": 15,    # 编码合规率
    "ref_integrity": 15,      # 引用完整性
}

# 必填章节 key
_REQUIRED_SECTIONS = {"app_info", "roles", "models", "permissions"}
# 可选章节 key
_OPTIONAL_SECTIONS = {"dicts", "forms", "workflows"}

# 各章节标准表头
_STANDARD_HEADERS: Dict[str, List[str]] = {
    "app_info": ["应用编码", "应用名称"],
    "roles": ["角色编码", "角色名称"],
    "dicts_option": ["选项编码", "选项名称"],
    "models": ["字段编码", "字段名称", "字段类型", "字典编码", "关联模型编码", "关联显示字段编码"],
    "forms": ["字段编码", "字段名称", "是否隐藏", "是否只读", "是否必填", "是否列表展示", "是否查询条件"],
    "permissions": ["表单名称", "角色编码", "可暂存", "可新增", "可导入", "可查看", "可编辑", "可删除", "可导出", "数据范围"],
}

# 编码字段：需要符合英文小写+下划线规则
_CODE_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]*$')


def detect(text: str) -> Dict[str, Any]:
    """对文档进行标准度评分

    Returns:
        {
            "score": 86,
            "level": "standard",      # standard / partial / freeform
            "decision": "pure_code",  # pure_code / hybrid_fallback / rewrite_first
            "missing_sections": ["权限配置"],
            "weak_sections": ["数据字典"],
            "signals": {
                "section_coverage": 0.9,
                "header_format": 1.0,
                "table_header_match": 0.85,
                "code_compliance": 0.9,
                "ref_integrity": 1.0,
            }
        }
    """
    sections = split_sections(text)
    headers = detect_section_headers(text)

    s_section = _score_section_coverage(sections)
    s_header = _score_header_format(headers)
    s_table = _score_table_headers(text, sections)
    s_code = _score_code_compliance(sections)
    s_ref = _score_ref_integrity(sections)

    score = int(
        s_section * _WEIGHTS["section_coverage"]
        + s_header * _WEIGHTS["header_format"]
        + s_table * _WEIGHTS["table_header_match"]
        + s_code * _WEIGHTS["code_compliance"]
        + s_ref * _WEIGHTS["ref_integrity"]
    )

    missing = _find_missing_sections(sections)
    weak = _find_weak_sections(sections, s_table)

    if score >= 80:
        level, decision = "standard", "pure_code"
    elif score >= 50:
        level, decision = "partial", "hybrid_fallback"
    else:
        level, decision = "freeform", "rewrite_first"

    return {
        "score": score,
        "level": level,
        "decision": decision,
        "missing_sections": missing,
        "weak_sections": weak,
        "signals": {
            "section_coverage": round(s_section, 3),
            "header_format": round(s_header, 3),
            "table_header_match": round(s_table, 3),
            "code_compliance": round(s_code, 3),
            "ref_integrity": round(s_ref, 3),
        },
    }


# ── 各项评分函数 ──────────────────────────────────────────────

def _score_section_coverage(sections: Dict[str, str]) -> float:
    """必填章节存在得满分，可选章节额外加分"""
    present = set(sections.keys())
    required_present = len(_REQUIRED_SECTIONS & present)
    return required_present / len(_REQUIRED_SECTIONS)


def _score_header_format(headers: List) -> float:
    """检查二级标题是否符合 ## N、名称 格式"""
    if not headers:
        return 0.0
    standard_count = sum(1 for _, is_std in headers if is_std)
    return standard_count / len(headers)


def _score_table_headers(text: str, sections: Dict[str, str]) -> float:
    """检查各章节表头与标准是否匹配"""
    scores: List[float] = []

    # 应用信息、角色
    for key, expected in [("app_info", "app_info"), ("roles", "roles")]:
        if key in sections:
            scores.append(_match_headers(sections[key], _STANDARD_HEADERS[expected]))

    # 数据字典（每个子章节的选项表）
    if "dicts" in sections:
        subsections = split_subsections(sections["dicts"])
        for _, _, _, content in subsections:
            scores.append(_match_headers(content, _STANDARD_HEADERS["dicts_option"]))

    # 数据模型（每个子章节的字段表）
    if "models" in sections:
        subsections = split_subsections(sections["models"])
        for _, _, _, content in subsections:
            scores.append(_match_headers(content, _STANDARD_HEADERS["models"]))

    # 表单配置
    if "forms" in sections:
        subsections = split_subsections(sections["forms"])
        for _, _, _, content in subsections:
            scores.append(_match_headers(content, _STANDARD_HEADERS["forms"]))

    # 权限配置
    if "permissions" in sections:
        scores.append(_match_headers(sections["permissions"], _STANDARD_HEADERS["permissions"]))

    if not scores:
        return 0.0
    return sum(scores) / len(scores)


def _match_headers(text: str, expected: List[str]) -> float:
    """计算文本中第一个表格的表头与期望表头的匹配率"""
    tables = find_tables(text)
    if not tables:
        return 0.0

    # 取第一个表格的表头行
    lines = tables[0].splitlines()
    if not lines:
        return 0.0

    actual_cells = _split_row(lines[0])
    actual_set = {c.strip() for c in actual_cells if c.strip()}

    matched = sum(1 for h in expected if h in actual_set)
    return matched / len(expected)


def _score_code_compliance(sections: Dict[str, str]) -> float:
    """检查编码字段是否都是英文小写+下划线"""
    codes: List[str] = []

    # 从各章节表格中提取编码列
    for key in ("app_info", "roles", "dicts", "models", "permissions"):
        if key not in sections:
            continue
        tables = find_tables(sections[key])
        for table_text in tables:
            tlines = [l for l in table_text.splitlines() if l.strip()]
            if len(tlines) < 2:
                continue
            headers = [c.strip() for c in _split_row(tlines[0])]
            for i, h in enumerate(headers):
                if "编码" in h:
                    for dline in tlines[2:]:
                        cells = _split_row(dline)
                        if i < len(cells) and cells[i].strip():
                            codes.append(cells[i].strip())

    if not codes:
        return 1.0  # 无编码字段，不扣分

    valid = sum(1 for c in codes if _CODE_RE.match(c))
    return valid / len(codes)


def _score_ref_integrity(sections: Dict[str, str]) -> float:
    """检查字典引用、模型引用是否在文档内闭合"""
    # 收集已定义的字典编码
    dict_codes: Set[str] = set()
    if "dicts" in sections:
        for name, code, _, _ in split_subsections(sections["dicts"]):
            if code:
                dict_codes.add(code.lower())

    # 收集已定义的模型编码
    model_codes: Set[str] = set()
    if "models" in sections:
        for name, code, _, _ in split_subsections(sections["models"]):
            if code:
                model_codes.add(code.lower())

    if not dict_codes and not model_codes:
        return 1.0

    broken = 0
    total = 0

    if "models" in sections:
        tables = find_tables(sections["models"])
        for table_text in tables:
            tlines = [l for l in table_text.splitlines() if l.strip()]
            if len(tlines) < 2:
                continue
            headers = [c.strip() for c in _split_row(tlines[0])]
            dict_idx = next((i for i, h in enumerate(headers) if "字典编码" in h), None)
            ref_idx = next((i for i, h in enumerate(headers) if "关联模型编码" in h), None)

            for dline in tlines[2:]:
                cells = _split_row(dline)
                if dict_idx is not None and dict_idx < len(cells):
                    v = cells[dict_idx].strip()
                    if v:
                        total += 1
                        if v.lower() not in dict_codes:
                            broken += 1
                if ref_idx is not None and ref_idx < len(cells):
                    v = cells[ref_idx].strip()
                    if v:
                        total += 1
                        if v.lower() not in model_codes:
                            broken += 1

    if total == 0:
        return 1.0
    return max(0.0, 1.0 - broken / total)


def _find_missing_sections(sections: Dict[str, str]) -> List[str]:
    key_to_name = {
        "app_info": "应用信息",
        "roles": "角色列表",
        "models": "数据模型",
        "permissions": "权限配置",
    }
    return [name for key, name in key_to_name.items() if key not in sections]


def _find_weak_sections(sections: Dict[str, str], table_score: float) -> List[str]:
    """找出表头不标准的章节（粗粒度）"""
    weak = []
    key_to_name = {
        "app_info": "应用信息",
        "roles": "角色列表",
        "dicts": "数据字典",
        "models": "数据模型",
        "forms": "表单配置",
        "permissions": "权限配置",
    }
    for key, name in key_to_name.items():
        if key not in sections:
            continue
        if key in ("dicts", "models", "forms"):
            subs = split_subsections(sections[key])
            for _, _, _, content in subs:
                expected = _STANDARD_HEADERS.get(
                    "dicts_option" if key == "dicts" else key, []
                )
                if expected and _match_headers(content, expected) < 0.7:
                    weak.append(name)
                    break
        else:
            expected = _STANDARD_HEADERS.get(key, [])
            if expected and _match_headers(sections[key], expected) < 0.7:
                weak.append(name)
    return weak
