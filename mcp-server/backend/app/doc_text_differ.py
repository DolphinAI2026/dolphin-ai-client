"""文档文本级别对比 — 按章节做 diff（不调 LLM）

在增量更新流程中，先对 V1/V2 文档做纯文本级别的章节对比，
快速识别出新增/修改/删除/未变更的章节，从而只对变更部分调 LLM 解析，
节省 60-80% 的 token 消耗。

与 doc_differ.py（config 级别的语义对比）互补：
- doc_text_differ.py: 文本级别，判断哪些章节变了
- doc_differ.py: config 级别，判断模型/字段/字典的增删改
"""
from __future__ import annotations

import hashlib
import re
from typing import Dict, List, Optional


def split_sections(text: str) -> Dict[str, str]:
    """按 markdown heading (## / ###) 分章节，返回 {heading: content}

    heading 包含层级标记，如 "## 工单管理" / "### 字段设计"。
    content 是该标题到下一个同级或更高级标题之间的全部文本（含标题行本身）。
    """
    sections: Dict[str, str] = {}
    lines = text.split('\n')
    current_heading: Optional[str] = None
    current_lines: List[str] = []

    for line in lines:
        m = re.match(r'^(#{2,4})\s+(.+)', line)
        if m:
            # 遇到新标题，保存之前的章节
            if current_heading is not None:
                sections[current_heading] = '\n'.join(current_lines)
            current_heading = line.strip()
            current_lines = [line]
        else:
            if current_heading is not None:
                current_lines.append(line)
            # 标题之前的内容归入 "__preamble__"（如果有的话）
            elif line.strip():
                if "__preamble__" not in sections:
                    sections["__preamble__"] = ""
                sections["__preamble__"] += line + '\n'

    # 保存最后一个章节
    if current_heading is not None:
        sections[current_heading] = '\n'.join(current_lines)

    return sections


def _section_hash(content: str) -> str:
    """计算章节内容的 hash，用于快速判断是否变更。
    对内容做标准化处理：去除首尾空白、统一换行符。
    """
    normalized = content.strip().replace('\r\n', '\n')
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def _normalize_heading(heading: str) -> str:
    """标准化标题用于匹配：去掉 # 前缀和空白，只保留文字内容"""
    return re.sub(r'^#{1,4}\s+', '', heading).strip().lower()


def diff_sections(v1_text: str, v2_text: str) -> Dict:
    """对比两个文档的章节变化

    返回:
    {
        "added": [{"heading": str, "content": str}],       # V2 新增的章节
        "modified": [{"heading": str, "v1_content": str, "v2_content": str}],  # 变更的章节
        "removed": [{"heading": str, "content": str}],     # V1 有但 V2 没有的章节
        "unchanged": [{"heading": str}]                     # 未变更的章节
    }
    """
    v1_sections = split_sections(v1_text)
    v2_sections = split_sections(v2_text)

    # 构建标准化标题 -> 原始标题的映射，用于模糊匹配
    v1_norm: Dict[str, str] = {_normalize_heading(h): h for h in v1_sections}
    v2_norm: Dict[str, str] = {_normalize_heading(h): h for h in v2_sections}

    # 先用原始标题精确匹配，再用标准化标题模糊匹配
    v1_matched: set = set()
    v2_matched: set = set()

    added: List[Dict] = []
    modified: List[Dict] = []
    removed: List[Dict] = []
    unchanged: List[Dict] = []

    # Pass 1: 精确匹配（原始标题完全一致）
    for heading in v2_sections:
        if heading in v1_sections:
            v1_matched.add(heading)
            v2_matched.add(heading)
            v1_hash = _section_hash(v1_sections[heading])
            v2_hash = _section_hash(v2_sections[heading])
            if v1_hash == v2_hash:
                unchanged.append({"heading": heading})
            else:
                modified.append({
                    "heading": heading,
                    "v1_content": v1_sections[heading],
                    "v2_content": v2_sections[heading],
                })

    # Pass 2: 标准化标题模糊匹配（处理标题微调的情况）
    for v2_heading in v2_sections:
        if v2_heading in v2_matched:
            continue
        v2_norm_key = _normalize_heading(v2_heading)
        if v2_norm_key in v1_norm:
            v1_heading = v1_norm[v2_norm_key]
            if v1_heading not in v1_matched:
                v1_matched.add(v1_heading)
                v2_matched.add(v2_heading)
                v1_hash = _section_hash(v1_sections[v1_heading])
                v2_hash = _section_hash(v2_sections[v2_heading])
                if v1_hash == v2_hash:
                    unchanged.append({"heading": v2_heading})
                else:
                    modified.append({
                        "heading": v2_heading,
                        "v1_content": v1_sections[v1_heading],
                        "v2_content": v2_sections[v2_heading],
                    })

    # 未匹配的 V2 章节 = 新增
    for heading in v2_sections:
        if heading not in v2_matched:
            added.append({"heading": heading, "content": v2_sections[heading]})

    # 未匹配的 V1 章节 = 删除
    for heading in v1_sections:
        if heading not in v1_matched:
            removed.append({"heading": heading, "content": v1_sections[heading]})

    return {
        "added": added,
        "modified": modified,
        "removed": removed,
        "unchanged": unchanged,
    }


def build_changed_text(diff_result: Dict) -> str:
    """将 added + modified 的章节拼接成文本，供 AI 解析。

    只包含变更部分，未变更的章节不传给 LLM，节省 token。
    """
    parts: List[str] = []

    for item in diff_result.get("added", []):
        parts.append(item["content"])

    for item in diff_result.get("modified", []):
        parts.append(item["v2_content"])

    return "\n\n".join(parts)


def get_diff_stats(diff_result: Dict) -> Dict:
    """获取 diff 的统计信息，用于 SSE 进度汇报"""
    return {
        "added": len(diff_result.get("added", [])),
        "modified": len(diff_result.get("modified", [])),
        "removed": len(diff_result.get("removed", [])),
        "unchanged": len(diff_result.get("unchanged", [])),
    }
