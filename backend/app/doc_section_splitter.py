"""Markdown 章节拆分器

按照标准文档规范，把 markdown 拆成：
  sections: {section_key: raw_content}
  subsections: [(title, code, content), ...]

章节识别：## N、章节名（通过关键字匹配，不依赖数字顺序）
子章节识别：### 名称（编码）【标记】
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple


# ── 章节关键字 → 内部 key ────────────────────────────────────
_SECTION_KEYWORDS: Dict[str, str] = {
    "应用信息": "app_info",
    "角色列表": "roles",
    "角色清单": "roles",
    "数据字典": "dicts",
    "数据模型": "models",
    "表单配置": "forms",
    "权限配置": "permissions",
    "审批流程": "workflows",
}

# 子章节标题解析：### 名称（code）【tag】 或 ### 名称(code)【tag】
_SUBSECTION_RE = re.compile(
    r"^###\s+(.+?)\s*[（(]([a-zA-Z0-9_]+)[）)]\s*(?:【([^】]*)】)?\s*$"
)

# 审批流程子章节：### 名称（关联表单：表单名）
_WORKFLOW_SUBSECTION_RE = re.compile(
    r"^###\s+(.+?)\s*[（(]关联表单[：:]\s*(.+?)[）)]\s*$"
)

# 章节标题：## N、章节名 或 ## 章节名
_SECTION_HEADER_RE = re.compile(r"^##\s+(?:[一二三四五六七八九十]+[、.]?\s*)?(.+)$")


def _match_section_key(title: str) -> Optional[str]:
    """从章节标题文字匹配内部 key"""
    title = title.strip()
    for keyword, key in _SECTION_KEYWORDS.items():
        if keyword in title:
            return key
    return None


def split_sections(text: str) -> Dict[str, str]:
    """拆分 markdown 为各章节内容（key → raw text）

    Returns:
        {"app_info": "...", "roles": "...", ...}
        缺失章节不含该 key
    """
    lines = text.splitlines()
    sections: Dict[str, str] = {}
    current_key: Optional[str] = None
    current_lines: List[str] = []

    for line in lines:
        m = _SECTION_HEADER_RE.match(line)
        if m:
            # 保存上一章节
            if current_key:
                sections[current_key] = "\n".join(current_lines).strip()
            title = m.group(1).strip()
            current_key = _match_section_key(title)
            current_lines = []
        else:
            if current_key is not None:
                current_lines.append(line)

    # 保存最后一章节
    if current_key:
        sections[current_key] = "\n".join(current_lines).strip()

    return sections


def split_subsections(section_text: str) -> List[Tuple[str, Optional[str], Optional[str], str]]:
    """拆分章节内容为子章节列表

    Returns:
        [(name, code, tag, content), ...]
        - name: 子章节名称（如"供应商"）
        - code: 编码（如"supplier"），无编码时为 None
        - tag: 标记（如"主表"/"子表"），无标记时为 None
        - content: 子章节内容
    """
    lines = section_text.splitlines()
    results: List[Tuple[str, Optional[str], Optional[str], str]] = []
    current: Optional[Tuple[str, Optional[str], Optional[str]]] = None
    current_lines: List[str] = []

    for line in lines:
        if line.startswith("### "):
            # 保存上一子章节
            if current is not None:
                results.append((*current, "\n".join(current_lines).strip()))
            # 解析新子章节标题
            m = _SUBSECTION_RE.match(line)
            if m:
                current = (m.group(1).strip(), m.group(2).strip(), m.group(3))
                current_lines = []
            else:
                # 尝试审批流程格式
                m2 = _WORKFLOW_SUBSECTION_RE.match(line)
                if m2:
                    current = (m2.group(1).strip(), m2.group(2).strip(), None)
                    current_lines = []
                else:
                    # 无编码的子章节（如纯文字标题）
                    raw_name = line[4:].strip()
                    current = (raw_name, None, None)
                    current_lines = []
        else:
            if current is not None:
                current_lines.append(line)

    if current is not None:
        results.append((*current, "\n".join(current_lines).strip()))

    return results


def detect_section_headers(text: str) -> List[Tuple[str, bool]]:
    """检测所有二级标题，返回 [(title, is_standard_format)]

    用于标准度检测。
    """
    results = []
    standard_re = re.compile(r"^##\s+[一二三四五六七八九十]+[、.]\s*.+$")
    header_re = re.compile(r"^##\s+.+$")
    for line in text.splitlines():
        if header_re.match(line):
            is_standard = bool(standard_re.match(line))
            results.append((line.strip(), is_standard))
    return results
